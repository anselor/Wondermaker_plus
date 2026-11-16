"""WM+ material command, configuration and status entry point.

Feature modules own their implementations and state. This facade preserves the
existing Klipper commands, configuration options and status interface.
"""
# Copyright (C) 2026  Wondermaker+ contributors
# This file may be distributed under the terms of the GNU GPLv3 license.
import os
import copy
import configparser
import json
import logging
import hashlib
import tempfile
import re
import uuid
import math
import stat
import threading
import queue
from functools import wraps
import urllib.request
import urllib.error
import urllib.parse



try:
    from .wmp_observation import _status_observation
    from .wmp_toolhead_service import ToolheadService
    from .wmp_plr_execution import ExecutionEvidence
    from .wmp_plr_motion import RecoveryMotion
    from .wmp_plr_storage import RecoveryStorage
    from .wmp_plr_worker import RecoveryWorker
    from .wmp_plr_attempt import RecoveryLifecycle
    from .wmp_plr_clearance import RecoveryClearance
    from .wmp_plr_jobs import RecoveryJobs
    from .wmp_plr_review import RecoveryReview
    from .wmp_print_submission import PrintSubmission
    from .wmp_filament_planning import FilamentPlanning
    from .wmp_filament_service import FilamentService
    from .wmp_toolchange_repair import ToolchangeRepair
    from .wmp_paused_service import PausedService
    from .wmp_material_settings import MaterialSettings
    from .wmp_filament_state import FilamentState
    from .wmp_config_save import ConfigurationSave
    from .wmp_material_status import MaterialStatus
    from .wmp_command_routing import CommandRouting
    from .wmp_material_owners import MaterialOwners
    from .wmp_print_cancel import PrintCancellation
    from .wmp_component import component_state, component_method, component_accessor
    from .wmp_persistence import atomic_write
    from . import wmp_filament_profiles
    from .wmp_filament_types import (FilamentCancelled, MATERIALS, GENERIC_NOZZLE_RANGES, SLOTS, DEFAULT_INI, parse_slot_materials, material_name, material_temp, material_temperature_range, material_family, cross_family_purge, transition_temperature)
    from . import wmp_orca_profiles
    from . import wmp_nozzles
    from . import wmp_saved_variables
    from . import wmp_recovery_retirement
    from . import wmp_recovery_file_envelope
    from .wmp_plr_records import RecoveryAttempt, RecoveryDepositionEnvelope
except ImportError:
    from wmp_observation import _status_observation
    from wmp_toolhead_service import ToolheadService
    from wmp_plr_execution import ExecutionEvidence
    from wmp_plr_motion import RecoveryMotion
    from wmp_plr_storage import RecoveryStorage
    from wmp_plr_worker import RecoveryWorker
    from wmp_plr_attempt import RecoveryLifecycle
    from wmp_plr_clearance import RecoveryClearance
    from wmp_plr_jobs import RecoveryJobs
    from wmp_plr_review import RecoveryReview
    from wmp_print_submission import PrintSubmission
    from wmp_filament_planning import FilamentPlanning
    from wmp_filament_service import FilamentService
    from wmp_toolchange_repair import ToolchangeRepair
    from wmp_paused_service import PausedService
    from wmp_material_settings import MaterialSettings
    from wmp_filament_state import FilamentState
    from wmp_config_save import ConfigurationSave
    from wmp_material_status import MaterialStatus
    from wmp_command_routing import CommandRouting
    from wmp_material_owners import MaterialOwners
    from wmp_print_cancel import PrintCancellation
    from wmp_component import component_state, component_method, component_accessor
    from wmp_persistence import atomic_write
    import wmp_filament_profiles
    from wmp_filament_types import (FilamentCancelled, MATERIALS, GENERIC_NOZZLE_RANGES, SLOTS, DEFAULT_INI, parse_slot_materials, material_name, material_temp, material_temperature_range, material_family, cross_family_purge, transition_temperature)
    import wmp_orca_profiles
    import wmp_nozzles
    import wmp_saved_variables
    import wmp_recovery_retirement
    import wmp_recovery_file_envelope
    from wmp_plr_records import RecoveryAttempt, RecoveryDepositionEnvelope

def run_standalone_extrusion_sequence(printer, sequence):
    """Execute a prevalidated E-only procedure, preserving vendor G-code state.

    Internal building block, not a public G-code command. The caller must check
    idle state, attachment, material and temperature before entering. Never pass
    user-supplied G-code here. This does not restore physical filament position.
    """
    if (printer.lookup_object("openace", None) is not None
            or printer.lookup_object("AFC", None) is not None):
        raise ValueError("Another manager owns filament operations")
    move = printer.lookup_object("gcode_move")
    status = move.get_status(printer.get_reactor().monotonic())
    old_e = float(status["gcode_position"][3])
    if not math.isfinite(old_e):
        raise ValueError("Invalid extrusion coordinate")
    gcode = printer.lookup_object("gcode")
    # A unique name avoids overwriting a caller's saved state.
    name = "WMP_FILAMENT_" + uuid.uuid4().hex
    gcode.run_script_from_command("SAVE_GCODE_STATE NAME=" + name)
    try:
        # Shaping distances and rates must not depend on print overrides.
        gcode.run_script_from_command("M221 S100\nM220 S100\nM83")
        gcode.run_script_from_command(sequence)
        gcode.run_script_from_command("M400")
    finally:
        try:
            gcode.run_script_from_command("RESTORE_GCODE_STATE NAME=" + name + " MOVE=0")
            # Vendor RESTORE omits base_position restoration. Shaping uses G92,
            # so explicitly restore logical E *after* the saved flow factor.
            gcode.run_script_from_command("G92 E%.17g" % old_e)
        finally:
            move.saved_states.pop(name, None)


class WMMaterial:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.load_feed_mm = config.getfloat("load_feed_mm", 55., minval=1., maxval=200.)
        self.load_purge_mm = config.getfloat("load_purge_mm", 50., minval=1., maxval=300.)
        self.recovery_purge_mm = config.getfloat("recovery_purge_mm", self.load_purge_mm, minval=1., maxval=300.)
        self.recovery_clearance_mm = config.getfloat("recovery_clearance_mm", 10., minval=1., maxval=50.)
        self.cross_material_purge_mm = config.getfloat(
            "cross_material_purge_mm", self.load_purge_mm, minval=1., maxval=300.)
        self.session_id = uuid.uuid4().hex
        # SwitchSensor defaults to False before the MCU reports its input.
        self._filament_sensors_ready_at = float("inf")
        self._pending_execution_snapshot = None
        self._execution_timer = None
        self._execution_stopped = True
        self._execution_last_boundary = None
        self._execution_error = ""
        self._filament_checks = {}
        self._filament_requests = set()
        self.filament_operation = {}
        self.toolhead_operation = {}
        self._toolhead_requests = set()
        self._print_requests = set()
        self.print_submission = {}
        self._pending_recovery_submission = None
        self.ini_path = os.path.expanduser(
            config.get("ini_path", DEFAULT_INI))
        self.profile_path = os.path.join(os.path.dirname(self.ini_path), "wmp_filaments.json")
        self.recovery_checkpoint_dir = os.path.abspath(os.path.expanduser(
            config.get("recovery_checkpoint_dir", "~/TM_T1/bin")))
        self._restore_filament_operation()
        self._restore_toolhead_operation()
        self._restore_recovery_attempt()
        self._restore_print_cancel()
        self._command_generation = 0
        self.catalogue_path = os.path.join(os.path.dirname(self.ini_path), "wmp_filament_catalogue.json")
        self._nozzles = wmp_nozzles.NozzleSettings(
            self.printer.get_start_args()["config_file"], self.ini_path)
        self.nozzle_save = {}
        self._profile_importer = wmp_orca_profiles.UsbProfileImport(
            os.path.expanduser(config.get("usb_profile_root", "~/printer_data/gcodes/USB")), self.catalogue_path)
        self.profile_import = {"state": "idle"}
        self._profile_import_busy = False
        self._async_completions = queue.SimpleQueue()
        self._mtime = None
        self._slots = {}
        self.printer.register_event_handler("klippy:ready", self._filament_sensors_ready)
        self.printer.register_event_handler("klippy:disconnect", self._filament_sensors_unavailable)
        self.printer.register_event_handler("klippy:shutdown", self._filament_sensors_unavailable)
        self.printer.register_event_handler("klippy:ready", self._refresh)
        self.printer.register_event_handler("klippy:ready", self._saved_variables_ready)
        self.printer.register_event_handler("klippy:ready", self._execution_ready)
        self.printer.register_event_handler("klippy:ready", self._cancel_routes_ready)
        self.printer.register_event_handler("klippy:ready", self._config_save_routes_ready)
        self.printer.register_event_handler("gcode:request_restart", self._restart_requested)
        self.printer.register_event_handler("klippy:disconnect", self._execution_stop)
        self.printer.register_event_handler("klippy:shutdown", self._execution_stop)
        self.printer.register_event_handler("klippy:ready", self._afc_ready)
        self.printer.register_event_handler("klippy:disconnect", self._afc_stop)
        self.printer.register_event_handler("klippy:shutdown", self._afc_stop)
        self.printer.register_event_handler("virtual_sdcard:reset_file", self._clear_filament_checks)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/filament/cancel", self._handle_filament_cancel)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/print/cancel_review", self._handle_print_cancel_review)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/print/cancel", self._handle_print_cancel)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/print/cancel_resolve_review", self._handle_print_cancel_resolution_review)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/recovery/stop", self._handle_recovery_stop)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/recovery/review", self._handle_recovery_review)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/recovery/retire_review", self._handle_recovery_retirement_review)
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/recovery/retire_result", self._handle_recovery_retirement_result)
        gcode = self.printer.lookup_object("gcode")
        gcode.register_command("WMP_RETIRE_RECOVERY", self.cmd_RETIRE_RECOVERY,
                               desc="Explicitly archive and retire reviewed saved recovery evidence; no motion")
        gcode.register_command("WMP_RECOVERY_CONTINUE", self.cmd_RECOVERY_CONTINUE,
                               desc="Run an explicitly selected managed recovery attempt")
        gcode.register_command("WMP_RECOVERY_RESOLVE", self.cmd_RECOVERY_RESOLVE,
                               desc="Explicitly reconcile or abandon a reviewed recovery; no preparation")
        self.printer.lookup_object("webhooks").register_endpoint(
            "wmp/recovery/resolve_review", self._handle_recovery_resolution_review)
        gcode.register_command("WMP_RESOLVE_PRINT_CANCEL", self.cmd_RESOLVE_PRINT_CANCEL,
                               desc="Resolve a separately reviewed interrupted print cancellation")
        gcode.register_command("WMP_CHECK_SCRIPT_GENERATION", self.cmd_CHECK_SCRIPT_GENERATION,
                               when_not_ready=True, desc="Check legacy script admission after waiting for command ownership")
        gcode.register_command("WMP_CHECK_COMMAND_GENERATION", self.cmd_CHECK_COMMAND_GENERATION,
                               desc="Refuse commands queued before cancellation or restart")
        gcode.register_command("WMP_CHECK_RESUME", self.cmd_CHECK_RESUME,
                               desc="Verify paused filament service is complete before resume")
        gcode.register_command("WMP_PREPARE_RESUME_E", self.cmd_PREPARE_RESUME_E)
        gcode.register_command("WMP_RESTORE_RESUME_E", self.cmd_RESTORE_RESUME_E,
                               desc="Restore captured logical extrusion coordinate after paused return; no motion")
        gcode.register_command("WMP_CAPTURE_PAUSE", self.cmd_CAPTURE_PAUSE,
                               desc="Capture the paused job origin for filament service; no motion")
        gcode.register_command("WMP_SET_FILAMENT", self.cmd_SET_FILAMENT,
                               desc="Save standalone physical-head filament settings (no motion)")
        gcode.register_command("WMP_FORGET_FILAMENT", self.cmd_FORGET_FILAMENT,
                               desc="Invalidate a standalone operator filament check; no motion")
        gcode.register_command("WMP_CONFIRM_FILAMENT", self.cmd_CONFIRM_FILAMENT,
                               desc="Record an operator filament check; no motion or heating")
        gcode.register_command("WMP_START_PRINT", self.cmd_START_PRINT,
                               desc="Submit a validated standalone print with explicit mappings")
        gcode.register_command("_WMP_DISPATCH_SD_PRINT", self.cmd_DISPATCH_SD_PRINT,
                               desc="Dispatch an admitted filename without G-code comment parsing")
        gcode.register_command("_WMP_SAVE_PRINT_MESH", self.cmd_SAVE_PRINT_MESH,
                               desc="Persist only the current print mesh; optional recovery evidence")
        gcode.register_command("_WMP_RECOVERY_JOB_BEGIN", self.cmd_RECOVERY_JOB_BEGIN,
                               desc="Bind staged material evidence to the active SD startup")
        gcode.register_command("_WMP_RECOVERY_JOB_COMMIT", self.cmd_RECOVERY_JOB_COMMIT,
                               desc="Commit material evidence after print startup")
        gcode.register_command("_WMP_RECOVERY_JOB_CLEAR", self.cmd_RECOVERY_JOB_CLEAR,
                               desc="Invalidate completed or cancelled job material evidence")
        gcode.register_command("WMP_FILAMENT_SEQUENCE", self.cmd_FILAMENT_SEQUENCE,
                               desc="Run a reviewed standalone E-only load/unload procedure")
        gcode.register_command("WMP_FILAMENT_SERVICE", self.cmd_FILAMENT_SERVICE,
                               desc="Start managed external load/unload for an explicit physical HEAD=0..3")
        gcode.register_command("WMP_RECOVER_FILAMENT", self.cmd_RECOVER_FILAMENT,
                               desc="Verify an interrupted filament operation stopped; no extrusion or tool travel")
        gcode.register_command("WMP_RECOVER_TOOLHEAD", self.cmd_RECOVER_TOOLHEAD,
                               desc="Reconcile an interrupted tool change from sensors without repeating travel")
        gcode.register_command("_WMP_FAILED_PICKUP_CLEANUP", self.cmd_FAILED_PICKUP_CLEANUP,
                               desc="Release a supported failed pickup, retreat, then report the failed attempt")
        gcode.register_command("_WMP_CHECK_DOCK_SUPPORT", self.cmd_CHECK_DOCK_SUPPORT,
                               desc="Confirm dock support before unlock; stationary bounded observation")
        gcode.register_command("_WMP_CHECK_PICKUP_RELEASE", self.cmd_CHECK_PICKUP_RELEASE,
                               desc="Confirm the selected dock cleared after pickup; stationary bounded observation")
        gcode.register_command("_WMP_COUPLING_STROKE", self.cmd_COUPLING_STROKE,
                               desc="Run one owned coupling stroke with propagated homing errors")
        gcode.register_command("_WMP_TOOLHEAD_PROGRESS", self.cmd_TOOLHEAD_PROGRESS,
                               desc="Update a matching touchscreen toolhead progress step; no motion")
        gcode.register_command("WMP_TOOLHEAD_ACTION", self.cmd_TOOLHEAD_ACTION,
                               desc="Mount or dock a physical head using WM toolchange macros")
        gcode.register_command("WMP_PROFILE_IMPORT", self.cmd_PROFILE_IMPORT,
                               desc="Scan, review and save Orca filament presets from USB")
        gcode.register_command("WMP_SET_NOZZLE", self.cmd_SET_NOZZLE,
                               desc="Save physical nozzle settings without restarting or moving")
        gcode.register_command("WM_MATERIAL_STATUS", self.cmd_STATUS,
                               desc=self.cmd_STATUS_help)

    _cancellation = component_accessor(PrintCancellation, '_print_cancellation')
    _print_cancel = component_state("_cancellation", "_print_cancel")
    _print_cancel_resolution = component_state("_cancellation", "_print_cancel_resolution")
    _toolheads = component_accessor(ToolheadService, '_toolhead_service')

    toolhead_operation = component_state("_toolheads", "toolhead_operation")
    _toolhead_requests = component_state("_toolheads", "_toolhead_requests")
    _execution_evidence = component_accessor(ExecutionEvidence, '_plr_execution_component')

    _deposition_envelope = component_state("_execution_evidence", "_deposition_envelope")
    _deposition_queue = component_state("_execution_evidence", "_deposition_queue")
    _deposition_queue_hook = component_state("_execution_evidence", "_deposition_queue_hook")
    _deposition_session = component_state("_execution_evidence", "_deposition_session")
    _execution_error = component_state("_execution_evidence", "_execution_error")
    _execution_last_boundary = component_state("_execution_evidence", "_execution_last_boundary")
    _execution_next_capture_time = component_state("_execution_evidence", "_execution_next_capture_time")
    _execution_state = component_state("_execution_evidence", "_execution_state")
    _execution_stopped = component_state("_execution_evidence", "_execution_stopped")
    _execution_timer = component_state("_execution_evidence", "_execution_timer")
    _pending_execution_snapshot = component_state("_execution_evidence", "_pending_execution_snapshot")
    _print_recovery_error = component_state("_execution_evidence", "_print_recovery_error")
    _recovery_invalidation_error = component_state("_execution_evidence", "_recovery_invalidation_error")
    _recovery_motion = component_accessor(RecoveryMotion, '_plr_motion_component')


    _recovery_storage = component_accessor(RecoveryStorage, '_plr_storage_component')
    _recovery_worker = component_accessor(RecoveryWorker, '_plr_worker_component')

    _recovery_pending_worker = component_state("_recovery_worker", "_recovery_pending_worker")
    _recovery_paused_worker = component_state("_recovery_worker", "_recovery_paused_worker")
    _recovery_lifecycle = component_accessor(RecoveryLifecycle, '_plr_lifecycle_component')

    _recovery_attempt = component_state("_recovery_lifecycle", "_recovery_attempt")
    _recovery_restore_error = component_state("_recovery_lifecycle", "_recovery_restore_error")
    _recovery_temperatures = component_state("_recovery_lifecycle", "_recovery_temperatures")
    _recovery_clearance = component_accessor(RecoveryClearance, '_plr_clearance_component')

    _file_clearance_cache = component_state("_recovery_clearance", "_file_clearance_cache")
    _recovery_jobs = component_accessor(RecoveryJobs, '_plr_jobs_component')

    _pending_recovery_submission = component_state("_recovery_jobs", "_pending_recovery_submission")
    _print_mesh_persisted = component_state("_recovery_jobs", "_print_mesh_persisted")
    _recovery_review_service = component_accessor(RecoveryReview, '_plr_review_component')

    _recovery_tickets = component_state("_recovery_review_service", "_recovery_tickets")
    _recovery_resolution = component_state("_recovery_review_service", "_recovery_resolution")
    _recovery_resolution_ids = component_state("_recovery_review_service", "_recovery_resolution_ids")
    _recovery_stop_request = component_state("_recovery_review_service", "_recovery_stop_request")
    _recovery_command_active = component_state("_recovery_review_service", "_recovery_command_active")
    _recovery_command_ids = component_state("_recovery_review_service", "_recovery_command_ids")
    _recovery_submission = component_state("_recovery_review_service", "_recovery_submission")
    _recovery_retirement_result = component_state("_recovery_review_service", "_recovery_retirement_result")
    _print_service = component_accessor(PrintSubmission, '_print_submission_component')

    _print_requests = component_state("_print_service", "_print_requests")
    print_submission = component_state("_print_service", "print_submission")
    _print_request_sequence = component_state("_print_service", "_print_request_sequence")

    def _run_filament_extrusion(self, printer, sequence):
        return run_standalone_extrusion_sequence(printer, sequence)

    _filament_planning = component_accessor(FilamentPlanning, '_filament_planning_component')
    _filament_service = component_accessor(FilamentService, '_filament_service_component')

    filament_operation = component_state("_filament_service", "filament_operation")
    _filament_requests = component_state("_filament_service", "_filament_requests")
    _toolchange_repair = component_accessor(ToolchangeRepair, '_toolchange_repair_component')

    _toolchange_pause = component_state("_toolchange_repair", "_toolchange_pause")
    _paused_service = component_accessor(PausedService, '_paused_service_component')

    _pause_origin = component_state("_paused_service", "_pause_origin")
    _resume_progress = component_state("_paused_service", "_resume_progress")
    _filament_context_refusal = component_state("_paused_service", "_filament_context_refusal")
    _material_settings = component_accessor(MaterialSettings, '_material_settings_component')

    profile_import = component_state("_material_settings", "profile_import")
    _profile_import_busy = component_state("_material_settings", "_profile_import_busy")
    _profile_importer = component_state("_material_settings", "_profile_importer")
    _status_catalogue_snapshot = component_state("_material_settings", "_status_catalogue_snapshot")
    _profile_entry_errors = component_state("_material_settings", "_profile_entry_errors")
    _idle_settings_refusal = component_state("_material_settings", "_idle_settings_refusal")
    nozzle_save = component_state("_material_settings", "nozzle_save")
    _filament_state = component_accessor(FilamentState, '_filament_state_component')

    _filament_checks = component_state("_filament_state", "_filament_checks")
    _filament_sensors_ready_at = component_state("_filament_state", "_filament_sensors_ready_at")
    _guarded_filament_notifications = component_state("_filament_state", "_guarded_filament_notifications")
    _deferred_path_runouts = component_state("_filament_state", "_deferred_path_runouts")
    _hotend_history_error = component_state("_filament_state", "_hotend_history_error")
    _loaded_flags = component_state("_filament_state", "_loaded_flags")
    _presence_adopted = component_state("_filament_state", "_presence_adopted")
    _filament_presence_error = component_state("_filament_state", "_filament_presence_error")
    _filament_loss_job = component_state("_filament_state", "_filament_loss_job")
    _filament_empty_since = component_state("_filament_state", "_filament_empty_since")
    _configuration_save = component_accessor(ConfigurationSave, '_configuration_save_component')

    _config_save_handlers = component_state("_configuration_save", "_config_save_handlers")
    _material_status = component_accessor(MaterialStatus, '_material_status_component')

    _slots = component_state("_material_status", "_slots")
    _mtime = component_state("_material_status", "_mtime")
    _command_routing = component_accessor(CommandRouting, '_command_routing_component')

    _cancel_script_wrapper = component_state("_command_routing", "_cancel_script_wrapper")
    _command_generation = component_state("_command_routing", "_command_generation")
    _filament_request_sequence = component_state("_command_routing", "_filament_request_sequence")
    _toolhead_request_sequence = component_state("_command_routing", "_toolhead_request_sequence")
    _material_owners = component_accessor(MaterialOwners, '_material_owners_component')

    _afc_busy = component_state("_material_owners", "_afc_busy")
    _afc_declined = component_state("_material_owners", "_afc_declined")
    _afc_error = component_state("_material_owners", "_afc_error")
    _afc_last = component_state("_material_owners", "_afc_last")
    _afc_stopped = component_state("_material_owners", "_afc_stopped")
    _openace_filament_cancel = component_state("_material_owners", "_openace_filament_cancel")
    _openace_filament_recovery = component_state("_material_owners", "_openace_filament_recovery")

    def _drain_async_completions(self, now=None):
        # Only called by the reactor. A lost wake-up must not strand a finished
        # metadata worker; status polling and the publisher timer also drain it.
        while True:
            try:
                finish = self._async_completions.get_nowait()
            except queue.Empty:
                return
            finish(now)

    def _queue_async_completion(self, finish):
        self._async_completions.put(finish)
        try:
            self.printer.get_reactor().register_async_callback(self._drain_async_completions)
        except Exception:
            logging.exception("WM+ metadata completion wake-up failed; result retained for reactor polling")

    cmd_PROFILE_IMPORT = component_method("_material_settings", "cmd_PROFILE_IMPORT")
    _afc_ready = component_method("_material_owners", "_afc_ready")

    _afc_stop = component_method("_material_owners", "_afc_stop")
    _lane_data = component_method("_material_owners", "_lane_data")

    _lane_snapshot = component_method("_material_owners", "_lane_snapshot")
    cmd_AFC_METADATA = component_method("_material_owners", "cmd_AFC_METADATA")

    _afc_tick = component_method("_material_owners", "_afc_tick")
    _afc_publish = component_method("_material_owners", "_afc_publish")

    _saved_variables_ready = component_method("_material_status", "_saved_variables_ready")

    _refresh = component_method("_material_status", "_refresh")
    get_status = component_method("_material_status", "get_status")



    _restore_toolhead_operation = component_method("_toolheads", "_restore_toolhead_operation")
    _material_operation_active = component_method("_command_routing", "_material_operation_active")

    _begin_explicit_physical_action = component_method("_command_routing", "_begin_explicit_physical_action")

    _ordinary_paused_toolhead_status = component_method("_toolheads", "_ordinary_paused_toolhead_status")

    _admit_material_sequence = component_method("_command_routing", "_admit_material_sequence")
    cmd_TOOLHEAD_PROGRESS = component_method("_toolheads", "cmd_TOOLHEAD_PROGRESS")
    cmd_TOOLHEAD_ACTION = component_method("_toolheads", "cmd_TOOLHEAD_ACTION")

    cmd_RECOVER_TOOLHEAD = component_method("_toolheads", "cmd_RECOVER_TOOLHEAD")
    _filament_position_status = component_method("_filament_planning", "_filament_position_status")

    _service_context = component_method("_filament_planning", "_service_context")
    _prepare_service = component_method("_filament_planning", "_prepare_service")

    _filament_plan = component_method("_filament_planning", "_filament_plan")
    _openace_idle_status = component_method("_material_owners", "_openace_idle_status")

    _openace_load_plans = component_method("_material_owners", "_openace_load_plans")
    _openace_unload_plan = component_method("_material_owners", "_openace_unload_plan")

    _recovery_attempt_path = component_method("_recovery_lifecycle", "_recovery_attempt_path")
    _restore_recovery_attempt = component_method("_recovery_lifecycle", "_restore_recovery_attempt")

    _recovery_attempt_status = component_method("_recovery_lifecycle", "_recovery_attempt_status")

    _recovery_attempt_active = component_method("_recovery_lifecycle", "_recovery_attempt_active")

    _require_no_recovery_attempt = component_method("_recovery_lifecycle", "_require_no_recovery_attempt")


    _restore_filament_operation = component_method("_filament_service", "_restore_filament_operation")

    cmd_FILAMENT_SERVICE = component_method("_filament_service", "cmd_FILAMENT_SERVICE")
    cmd_FILAMENT_SEQUENCE = component_method("_filament_service", "cmd_FILAMENT_SEQUENCE")

    _config_save_routes_ready = component_method("_configuration_save", "_config_save_routes_ready")
    cmd_SAVE_PRINT_MESH = component_method("_configuration_save", "cmd_SAVE_PRINT_MESH")


    _stock_startup_file = component_method("_configuration_save", "_stock_startup_file")
    _restart_requested = component_method("_configuration_save", "_restart_requested")

    cmd_SCREEN_RESUME_PREHEAT = component_method("_paused_service", "cmd_SCREEN_RESUME_PREHEAT")
    cmd_TOOLCHANGE_FAULT = component_method("_toolchange_repair", "cmd_TOOLCHANGE_FAULT")

    _fault_pause_context = component_method("_toolchange_repair", "_fault_pause_context")

    _fault_service_origin = component_method("_toolchange_repair", "_fault_service_origin")

    _toolchange_pause_status = component_method("_toolchange_repair", "_toolchange_pause_status")
    _capture_toolchange_pause = component_method("_toolchange_repair", "_capture_toolchange_pause")

    _retry_paused_toolchange = component_method("_toolchange_repair", "_retry_paused_toolchange")

    _cancel_routes_ready = component_method("_command_routing", "_cancel_routes_ready")

    _script_command_names = component_method("_command_routing", "_script_command_names", CommandRouting._script_command_names)

    _handle_print_cancel_review = component_method("_cancellation", "_handle_print_cancel_review")
    _handle_print_cancel = component_method("_cancellation", "_handle_print_cancel")

    _handle_print_cancel_resolution_review = component_method("_cancellation", "_handle_print_cancel_resolution_review")
    cmd_RESOLVE_PRINT_CANCEL = component_method("_cancellation", "cmd_RESOLVE_PRINT_CANCEL")



    _print_cancel_active = component_method("_cancellation", "_print_cancel_active")

    _CANCEL_STAGES = PrintCancellation._CANCEL_STAGES


    _restore_print_cancel = component_method("_cancellation", "_restore_print_cancel")

    _begin_print_cancel = component_method("_cancellation", "_begin_print_cancel")

    _handle_filament_cancel = component_method("_filament_service", "_handle_filament_cancel")
    cmd_RECOVER_FILAMENT = component_method("_filament_service", "cmd_RECOVER_FILAMENT")

    _filament_checkpoint = component_method("_filament_service", "_filament_checkpoint")

    _openace_filament_context = component_method("_material_owners", "_openace_filament_context")
    _finish_openace_filament_stop = component_method("_material_owners", "_finish_openace_filament_stop")

    _attachment = component_method("_material_status", "_attachment")

    _screen_configuration_status = component_method("_material_settings", "_screen_configuration_status")
    _nozzle_status = component_method("_material_settings", "_nozzle_status")

    cmd_SET_NOZZLE = component_method("_material_settings", "cmd_SET_NOZZLE")

    _profiles = component_method("_material_settings", "_profiles")


    _validate_identity = staticmethod(wmp_filament_profiles.validate_identity)

    cmd_CAPTURE_PAUSE = component_method("_paused_service", "cmd_CAPTURE_PAUSE")

    _paused_filament_origin = component_method("_paused_service", "_paused_filament_origin")
    _paused_filament_status = component_method("_paused_service", "_paused_filament_status")

    _filament_context_valid = component_method("_paused_service", "_filament_context_valid")
    cmd_CHECK_SCRIPT_GENERATION = component_method("_command_routing", "cmd_CHECK_SCRIPT_GENERATION")

    cmd_CHECK_COMMAND_GENERATION = component_method("_command_routing", "cmd_CHECK_COMMAND_GENERATION")
    _check_command_generation = component_method("_command_routing", "_check_command_generation")

    _retire_changed_print_recovery = component_method("_paused_service", "_retire_changed_print_recovery")
    _observe_resume = component_method("_paused_service", "_observe_resume")

    cmd_CHECK_RESUME = component_method("_paused_service", "cmd_CHECK_RESUME")

    cmd_PREPARE_RESUME_E = component_method("_paused_service", "cmd_PREPARE_RESUME_E")
    cmd_RESTORE_RESUME_E = component_method("_paused_service", "cmd_RESTORE_RESUME_E")

    _identification_pending = component_method("_material_settings", "_identification_pending")
    _idle_for_filament_settings = component_method("_material_settings", "_idle_for_filament_settings")

    _filament_recipe = component_method("_material_settings", "_filament_recipe", MaterialSettings._filament_recipe)
    _loaded_source_matches = component_method("_material_settings", "_loaded_source_matches", MaterialSettings._loaded_source_matches)

    _profile_recipes = component_method("_material_settings", "_profile_recipes")


    _begin_usage_scan = component_method("_material_settings", "_begin_usage_scan")
    _finish_usage_scan = component_method("_material_settings", "_finish_usage_scan")

    _bind_usage_stream = component_method("_material_settings", "_bind_usage_stream")

    _recipe_write_status = component_method("_material_settings", "_recipe_write_status")

    cmd_SET_FILAMENT = component_method("_material_settings", "cmd_SET_FILAMENT")
    _clear_filament_checks = component_method("_filament_state", "_clear_filament_checks")

    _filament_sensors_ready = component_method("_filament_state", "_filament_sensors_ready")


    _filament_sensors_unavailable = component_method("_filament_state", "_filament_sensors_unavailable")
    _hotend_material_history = component_method("_filament_state", "_hotend_material_history")

    _record_hotend_material = component_method("_filament_state", "_record_hotend_material")

    _set_filament_loaded = component_method("_filament_state", "_set_filament_loaded")


    _job_filament_losses = component_method("_filament_state", "_job_filament_losses")

    _loaded_filament_status = component_method("_filament_state", "_loaded_filament_status")
    _sensor_filament_status = component_method("_filament_state", "_sensor_filament_status")

    _filament_status = component_method("_filament_state", "_filament_status")

    cmd_FORGET_FILAMENT = component_method("_filament_state", "cmd_FORGET_FILAMENT")
    cmd_CONFIRM_FILAMENT = component_method("_filament_state", "cmd_CONFIRM_FILAMENT")

    _print_admission = component_method("_print_service", "_print_admission")
    _openace_print_plan = component_method("_material_owners", "_openace_print_plan")



    _print_file_identity = component_method("_print_service", "_print_file_identity")

    _print_file = component_method("_print_service", "_print_file")
    _recovery_active_file = component_method("_recovery_storage", "_recovery_active_file")

    _recovery_job_path = component_method("_recovery_storage", "_recovery_job_path")
    _recovery_read_bytes = component_method("_recovery_storage", "_recovery_read_bytes", RecoveryStorage._recovery_read_bytes)

    _read_recovery_job = component_method("_recovery_storage", "_read_recovery_job")
    _recovery_offsets = component_method("_recovery_storage", "_recovery_offsets", RecoveryStorage._recovery_offsets)

    _recovery_context = component_method("_recovery_storage", "_recovery_context", RecoveryStorage._recovery_context)
    _recovery_fingerprint = component_method("_recovery_storage", "_recovery_fingerprint", RecoveryStorage._recovery_fingerprint)

    _recovery_checkpoint_evidence = component_method("_recovery_storage", "_recovery_checkpoint_evidence")

    _recovery_runtime_path = component_method("_recovery_storage", "_recovery_runtime_path")
    _deposition_envelope_path = component_method("_execution_evidence", "_deposition_envelope_path")


    _disable_print_recovery = component_method("_execution_evidence", "_disable_print_recovery")
    _install_deposition_observer = component_method("_execution_evidence", "_install_deposition_observer")

    _verify_deposition_observer = component_method("_execution_evidence", "_verify_deposition_observer")
    _begin_deposition_envelope = component_method("_execution_evidence", "_begin_deposition_envelope")

    _execution_ready = component_method("_execution_evidence", "_execution_ready")
    _execution_stop = component_method("_execution_evidence", "_execution_stop")

    _execution_sd_boundary = component_method("_execution_evidence", "_execution_sd_boundary")

    _execution_command_completed = component_method("_execution_evidence", "_execution_command_completed")

    _recovery_mesh_fingerprint = component_method("_execution_evidence", "_recovery_mesh_fingerprint")

    _restore_recovery_mesh = component_method("_execution_evidence", "_restore_recovery_mesh")

    _recovery_retirement_store = component_method("_recovery_review_service", "_recovery_retirement_store")

    _handle_recovery_retirement_review = component_method("_recovery_review_service", "_handle_recovery_retirement_review")
    cmd_RETIRE_RECOVERY = component_method("_recovery_review_service", "cmd_RETIRE_RECOVERY")

    _handle_recovery_retirement_result = component_method("_recovery_review_service", "_handle_recovery_retirement_result")
    _recovery_execution_path = component_method("_execution_evidence", "_recovery_execution_path")

    _recovery_execution_bytes = component_method("_execution_evidence", "_recovery_execution_bytes")
    _parse_recovery_execution_format = component_method("_execution_evidence", "_parse_recovery_execution_format", ExecutionEvidence._parse_recovery_execution_format)

    _require_recovery_not_retired = component_method("_recovery_review_service", "_require_recovery_not_retired")
    _read_completed_recovery_execution = component_method("_execution_evidence", "_read_completed_recovery_execution")


    _recovery_heater_state = component_method("_recovery_review_service", "_recovery_heater_state")

    _reconcile_recovery_continuation = component_method("_recovery_lifecycle", "_reconcile_recovery_continuation")
    _archive_recovery_evidence = component_method("_recovery_storage", "_archive_recovery_evidence")

    _read_archived_recovery_evidence = component_method("_recovery_storage", "_read_archived_recovery_evidence")
    _recovery_offer = component_method("_recovery_storage", "_recovery_offer")

    _clear_recovery_offer = component_method("_recovery_storage", "_clear_recovery_offer")
    _recovery_archive_matches_attempt = component_method("_recovery_storage", "_recovery_archive_matches_attempt")

    _abandon_recovery_attempt = component_method("_recovery_lifecycle", "_abandon_recovery_attempt")

    _run_recovery_stages = component_method("_recovery_lifecycle", "_run_recovery_stages")
    cmd_FAILED_PICKUP_CLEANUP = component_method("_toolheads", "cmd_FAILED_PICKUP_CLEANUP")

    cmd_CHECK_DOCK_SUPPORT = component_method("_toolheads", "cmd_CHECK_DOCK_SUPPORT")
    cmd_CHECK_PICKUP_RELEASE = component_method("_toolheads", "cmd_CHECK_PICKUP_RELEASE")

    cmd_COUPLING_STROKE = component_method("_toolheads", "cmd_COUPLING_STROKE")
    _recovery_actuator_stroke = component_method("_recovery_motion", "_recovery_actuator_stroke")

    _recovery_bottom_reference = component_method("_recovery_motion", "_recovery_bottom_reference")

    _recovery_initial_stages = component_method("_recovery_motion", "_recovery_initial_stages")




    _recovery_disarm_worker = component_method("_recovery_worker", "_recovery_disarm_worker")

    _recovery_queue_worker = component_method("_recovery_worker", "_recovery_queue_worker")
    _recovery_release_paused_worker = component_method("_recovery_worker", "_recovery_release_paused_worker")


    _recovery_activate_worker = component_method("_recovery_worker", "_recovery_activate_worker")
    _validate_recovery_accounting = component_method("_recovery_worker", "_validate_recovery_accounting", RecoveryWorker._validate_recovery_accounting)

    _recovery_start_accounting = component_method("_recovery_worker", "_recovery_start_accounting")
    _recovery_select_file = component_method("_recovery_worker", "_recovery_select_file")

    _recovery_file_effect_contract = component_method("_recovery_clearance", "_recovery_file_effect_contract")

    _recovery_deposition_payload = component_method("_recovery_clearance", "_recovery_deposition_payload")
    _recovery_clearance_evidence = component_method("_recovery_clearance", "_recovery_clearance_evidence")

    _decode_recovery_json = component_method("_recovery_review_service", "_decode_recovery_json", RecoveryReview._decode_recovery_json)

    _verify_recovery_native_selection = component_method("_recovery_review_service", "_verify_recovery_native_selection")



    _handle_recovery_review = component_method("_recovery_review_service", "_handle_recovery_review")

    _handle_recovery_resolution_review = component_method("_recovery_review_service", "_handle_recovery_resolution_review")

    cmd_RECOVERY_RESOLVE = component_method("_recovery_review_service", "cmd_RECOVERY_RESOLVE")
    _handle_recovery_stop = component_method("_recovery_review_service", "_handle_recovery_stop")

    cmd_RECOVERY_CONTINUE = component_method("_recovery_review_service", "cmd_RECOVERY_CONTINUE")


    _recovery_material_evidence = component_method("_recovery_review_service", "_recovery_material_evidence")

    cmd_RECOVERY_JOB_BEGIN = component_method("_recovery_jobs", "cmd_RECOVERY_JOB_BEGIN")

    cmd_RECOVERY_JOB_COMMIT = component_method("_recovery_jobs", "cmd_RECOVERY_JOB_COMMIT")
    cmd_RECOVERY_JOB_CLEAR = component_method("_recovery_jobs", "cmd_RECOVERY_JOB_CLEAR")

    _write_recovery_job = component_method("_recovery_storage", "_write_recovery_job")
    _write_recovery_json = component_method("_recovery_storage", "_write_recovery_json", RecoveryStorage._write_recovery_json)

    _stage_recovery_job = component_method("_recovery_jobs", "_stage_recovery_job")
    cmd_DISPATCH_SD_PRINT = component_method("_print_service", "cmd_DISPATCH_SD_PRINT")

    cmd_START_PRINT = component_method("_print_service", "cmd_START_PRINT")

    cmd_STATUS_help = "Report the touchscreen's per-slot filament material"

    cmd_STATUS = component_method("_material_status", "cmd_STATUS")


def load_config(config):
    return WMMaterial(config)
