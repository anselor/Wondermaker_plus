# wm_material: expose the WonderMaker touchscreen's per-slot filament material
# to Klipper macros as printer.wm_material.material0..3 (and index0..3,
# temp0..3, available). Source: the touchscreen's tmt1.ini, [slot]
# material0..3. Config: [wm_material] ini_path. G-code: WM_MATERIAL_STATUS.
# Install: tools/deploy.py install material (SSH).
#
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


def _status_observation(method):
    """Reuse an observation only within one synchronous status publication.

    A status contains four heads and eight possible procedures. Re-reading the
    same files and sensors for every branch blocks Klipper's reactor, even when
    all values are unchanged. Live observations expire after the publication;
    loaded profiles have their own save-invalidated snapshot. Command admission
    re-reads profiles, including edits preserving file size and timestamps.
    """
    @wraps(method)
    def observe(self, *args, **kwargs):
        cache = getattr(self, '_status_observation_cache', None)
        if cache is None:
            return method(self, *args, **kwargs)
        key = (method.__name__, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = method(self, *args, **kwargs)
        # Callers may enrich returned records or build an edited profile draft.
        # Neither must mutate the shared observation within this publication.
        return copy.deepcopy(cache[key])
    return observe

try:
    from . import wmp_orca_profiles
    from . import wmp_nozzles
    from . import wmp_saved_variables
    from . import wmp_recovery_retirement
    from . import wmp_recovery_file_envelope
except ImportError:
    import wmp_orca_profiles
    import wmp_nozzles
    import wmp_saved_variables
    import wmp_recovery_retirement
    import wmp_recovery_file_envelope

# Material table hardcoded in the touchscreen binary (client 1.1.04,
# `materials_str` + `fila_extrude_temp`, recovered with Ghidra).
MATERIALS = [
    ("PLA", 220), ("PLA Silk", 220), ("ABS", 250), ("PETG", 250),
    ("PLA Matte", 220), ("PLA Metal", 220), ("ABS Matte", 250),
    ("PETG Matte", 250), ("PVA", 220), ("TPE", 230), ("Marble", 220),
    ("HIPS", 250), ("TPU", 230), ("PET", 300), ("Wood", 220), ("ASA", 260),
    ("PA", 260), ("PC", 270),
    # WM+ additions. Append to preserve stock numeric material indices.
    # Starting service temperatures; spool-specific settings can override loading.
    ("PCTG", 260), ("PA6", 260), ("PA12", 260), ("PP", 240),
]
# Generic starting ranges, not certification for a brand/formulation. Provenance:
# OrcaSlicer e23af6d7b075ab6e317485551c7cbee33d1b4c4b, BBL fdm_filament_*
# presets (PLA inherits common). See docs/ui/standalone-filament-management.md.
GENERIC_NOZZLE_RANGES = {
    "PLA": (190, 240), "PLA SILK": (190, 240), "PLA MATTE": (190, 240),
    "PLA METAL": (190, 240), "ABS": (240, 280), "ABS MATTE": (240, 280),
    "ASA": (240, 280), "PETG": (220, 260), "PETG MATTE": (220, 260),
    "PCTG": (220, 260), "TPU": (200, 250), "PVA": (190, 240),
    "HIPS": (220, 270), "PA": (260, 300), "PA6": (260, 300),
    "PA12": (260, 300), "PC": (260, 290), "PP": (220, 250),
}
SLOTS = 4
DEFAULT_INI = "~/printer_data/config/tmt1.ini"


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


def parse_slot_materials(text):
    """Return {slot: material_index} from the `[slot]` section of tmt1.ini.

    Tolerant of comments (`;`/`#`), blank lines and unknown keys. Slots that
    are missing or unparsable are omitted.
    """
    result = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "slot" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        if not key.startswith("material"):
            continue
        try:
            slot = int(key[len("material"):])
            result[slot] = int(value.strip())
        except ValueError:
            continue
    return result


def material_name(index):
    if 0 <= index < len(MATERIALS):
        return MATERIALS[index][0]
    return "Unknown"


def material_temp(index):
    if 0 <= index < len(MATERIALS):
        return MATERIALS[index][1]
    return 0


def material_temperature_range(identity):
    """Use generic swap ranges; spool printing bounds are fallback only."""
    material = identity["material"].upper()
    fallback = GENERIC_NOZZLE_RANGES.get(material) or GENERIC_NOZZLE_RANGES.get(material_family(identity))
    if fallback is not None:
        return fallback[0], fallback[1], "generic"
    if fallback is None:
        recipe = dict((name.upper(), temp) for name, temp in MATERIALS).get(material)
        if recipe is not None:
            fallback = (recipe, recipe)
    low, high = identity.get("nozzle_temp_min", 0), identity.get("nozzle_temp_max", 0)
    explicit = bool(low and high)
    if fallback is not None:
        low, high = low or fallback[0], high or fallback[1]
    if not (0 < low <= high):
        raise ValueError("Set a valid nozzle temperature range for " + identity["material"])
    return low, high, "spool" if explicit else "generic" if material in GENERIC_NOZZLE_RANGES else "recipe-only"


def material_family(identity):
    """Group finish/filler variants without conflating distinct polymers."""
    name = str(identity.get("material", "")).strip().upper()
    return re.split(r"[\s-]+", name, maxsplit=1)[0]


def cross_family_purge(identity, previous):
    # Unknown residue cannot establish that a same-family purge is sufficient.
    incoming = material_family(identity)
    if not incoming or not previous or previous.get("unknown_residue"):
        return True
    residual = previous.get("materials", [])
    return not residual or any(material_family(old) != incoming for old in residual)


def transition_temperature(identity, previous, default_target):
    """Return a target and explanation without inventing missing spool limits."""
    if previous is None:
        return default_target, "Previous nozzle material is unknown; using the incoming filament temperature."
    residual = previous["materials"]
    unknown_note = " Additional previous residue is unknown." if previous.get("unknown_residue") else ""
    # A same-material/color-only reload retains its normal service temperature.
    thermal_keys = ("material", "nozzle_temp", "nozzle_temp_min", "nozzle_temp_max")
    if all(all(old.get(k) == identity.get(k) for k in thermal_keys) for old in residual):
        return default_target, unknown_note.strip()
    ranges = []
    range_sources = set()
    for item in [identity] + residual:
        low, high, source = material_temperature_range(item)
        range_sources.add(source)
        ranges.append((low, high))
    low, high = max(r[0] for r in ranges), min(r[1] for r in ranges)
    if low > high:
        raise ValueError("No shared nozzle temperature range; this material change needs a transition recipe")
    recipes = dict((name.upper(), temp) for name, temp in MATERIALS)
    old_targets = [item.get("nozzle_temp") or recipes.get(item["material"].upper()) for item in residual]
    if any(t is None for t in old_targets):
        target = low  # Residue's required lower bound, not an invented incoming default.
    elif all(t is not None and t > default_target for t in old_targets):
        target = high  # Cooler incoming material: use the upper shared limit.
    elif all(t is not None and t < default_target for t in old_targets):
        target = low   # Hotter incoming material: use the lower shared limit.
    else:
        target = min(high, max(low, default_target))
    defaults_note = " Uses generic material ranges." if "generic" in range_sources else ""
    if "recipe-only" in range_sources:
        defaults_note += " A material has only a service-temperature default."
    return target, ("Material transition: %g C within the shared %g–%g C range." % (target, low, high)) + defaults_note + unknown_note


class FilamentCancelled(Exception):
    pass


class RecoveryDepositionEnvelope:
    """Conservative queued-deposition ceiling, persisted before enqueue.

    The caller must install this below mesh transforms, begin on an admitted
    empty-bed job, and retain the same instance across tool changes and pauses.
    The backend installs this at the validated motion-queue boundary.
    """
    def __init__(self, persist, job_id, file_sha256, record=None):
        if (not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id)
                or not isinstance(file_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", file_sha256)):
            raise ValueError("Invalid deposition-envelope job binding")
        self.persist, self.failed = persist, False
        if record is None:
            record = {"version": 1, "job_id": job_id, "file_sha256": file_sha256, "max_z": 0.}
            persist(copy.deepcopy(record))
        if (not isinstance(record, dict) or set(record) != {"version", "job_id", "file_sha256", "max_z"}
                or type(record["version"]) is not int or record["version"] != 1
                or record["job_id"] != job_id or record["file_sha256"] != file_sha256
                or type(record["max_z"]) not in (int, float) or not math.isfinite(record["max_z"])
                or record["max_z"] < 0):
            raise ValueError("Invalid or mismatched deposition envelope")
        self.record = copy.deepcopy(record)

    def observe(self, move):
        if self.failed:
            raise ValueError("Deposition envelope is unresolved")
        try:
            start, end = list(move.start_pos), list(move.end_pos)
            if (len(start) != 4 or len(end) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in start + end)
                    or type(move.is_kinematic_move) is not bool):
                raise ValueError("Invalid deposition move geometry")
            if move.is_kinematic_move and end[3] > start[3]:
                # Include both ends of every physical linear segment. Bed-mesh
                # subdivisions and arcs reach this layer as separate segments.
                ceiling = float(math.ceil(max(start[2], end[2], 0.)))
                if ceiling > self.record["max_z"]:
                    updated = dict(self.record, max_z=ceiling)
                    self.persist(copy.deepcopy(updated))
                    self.record = updated
        except Exception:
            # Evidence failure invalidates this observer, not motion.
            self.failed = True
            raise

    def enqueue(self, move, submit):
        self.observe(move)
        try:
            return submit(move)
        except Exception:
            self.failed = True
            raise

    def clearance(self, bottom_z, required_gap, head_offset_span=0.):
        if (self.failed or any(type(v) not in (int, float) or not math.isfinite(v)
                               for v in (bottom_z, required_gap, head_offset_span))
                or required_gap <= 0 or head_offset_span < 0):
            raise ValueError("Invalid recovery clearance inputs")
        available = bottom_z - self.record["max_z"] - head_offset_span
        if available < required_gap:
            raise ValueError("Printed envelope leaves insufficient bottom-Z clearance")
        return {"printed_max_z": self.record["max_z"], "bottom_z": bottom_z,
                "available_gap": available, "required_gap": required_gap,
                "head_offset_span": head_offset_span}


class RecoveryAttempt:
    """Durable stage execution; caller must hold machine-command ownership.

    Dispatch completion is not physical completion. Each stage has a separate
    verifier, and an interrupted/dispatched stage is never automatically retried.
    Startup restores evidence and uncertainty; it never dispatches stages.
    """
    def __init__(self, persist, record=None):
        self.persist = persist
        self.record = copy.deepcopy(record) if record is not None else None
        self.busy = False
        if self.record is not None:
            if (not isinstance(self.record, dict)
                    or set(self.record) - {"cleanup", "resolution", "continuation", "checkpoint"} != {"version", "request", "state", "stages", "error"}
                    or type(self.record["version"]) is not int or self.record["version"] != 1
                    or self.record["state"] not in ("pending", "running", "unknown", "complete", "stopped", "abandoned")
                    or not isinstance(self.record["error"], str)
                    or not isinstance(self.record["stages"], list) or not self.record["stages"]):
                raise ValueError("Invalid recovery attempt journal")
            self._validate_request(self.record["request"])
            if "continuation" in self.record:
                outcome = self.record["continuation"]
                if (not isinstance(outcome, dict) or set(outcome) != {"state", "file_position", "error"}
                        or outcome["state"] not in ("complete", "paused", "cancelled", "unknown", "scheduled", "started", "interrupted", "checkpointed")
                        or type(outcome["file_position"]) is not int or outcome["file_position"] < 0
                        or not isinstance(outcome["error"], str)
                        or outcome["state"] in ("unknown", "interrupted") and self.record["state"] not in ("unknown", "abandoned")):
                    raise ValueError("Invalid recovery continuation outcome")
            if "checkpoint" in self.record:
                checkpoint = self.record["checkpoint"]
                if (not isinstance(checkpoint, dict) or set(checkpoint) != {"job_fingerprint", "file_position"}
                        or not isinstance(checkpoint["job_fingerprint"], str)
                        or not re.fullmatch(r"[0-9a-f]{16}", checkpoint["job_fingerprint"])
                        or type(checkpoint["file_position"]) is not int or checkpoint["file_position"] <= 0):
                    raise ValueError("Invalid recovery continuation checkpoint")
            if self.record.get("continuation", {}).get("state") in ("scheduled", "started", "interrupted", "checkpointed") and "checkpoint" not in self.record:
                raise ValueError("Recovery continuation has no checkpoint binding")
            if "cleanup" in self.record:
                cleanup = self.record["cleanup"]
                if (not isinstance(cleanup, dict) or set(cleanup) != {"state", "heaters", "error"}
                        or cleanup["state"] not in ("complete", "unknown") or not isinstance(cleanup["error"], str)
                        or not isinstance(cleanup["heaters"], dict)
                        or set(cleanup["heaters"]) - {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
                        or any(type(value) is not bool for value in cleanup["heaters"].values())
                        or cleanup["state"] == "complete" and not all(cleanup["heaters"].values())):
                    raise ValueError("Invalid recovery cleanup journal")
            if self.record["state"] == "abandoned" or "resolution" in self.record:
                resolution = self.record.get("resolution")
                if (not isinstance(resolution, dict) or set(resolution) != {"session", "attachment"}
                        or not isinstance(resolution["session"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", resolution["session"])
                        or resolution["attachment"] not in ([{"state": "attached", "head": "h%d" % i} for i in range(4)]
                                                           + [{"state": "empty", "head": ""}, {"state": "unknown", "head": ""}])):
                    raise ValueError("Invalid recovery abandonment receipt")
            names, incomplete = set(), False
            for stage in self.record["stages"]:
                if (not isinstance(stage, dict) or set(stage) != {"name", "state"}
                        or not isinstance(stage["name"], str) or not re.fullmatch(r"[a-z_]{1,48}", stage["name"])
                        or stage["name"] in names or stage["state"] not in ("pending", "running", "complete")
                        or (incomplete and stage["state"] != "pending")):
                    raise ValueError("Invalid recovery stage journal")
                names.add(stage["name"])
                incomplete = incomplete or stage["state"] != "complete"
            if self.record["state"] == "complete" and incomplete:
                raise ValueError("Incomplete recovery marked complete")
            if self.record.get("continuation", {}).get("state") in ("scheduled", "started"):
                self.record["continuation"].update(state="interrupted", error="Worker continuation was interrupted by restart")
                self.record.update(state="unknown", error="Review the interrupted recovery checkpoint before another operation")
                self.persist(copy.deepcopy(self.record))
            if self.record["state"] in ("pending", "running"):
                self.record.update(state="unknown", error="Recovery interrupted; inspect the machine before another attempt")
                self.persist(copy.deepcopy(self.record))

    @staticmethod
    def _validate_request(request):
        if (not isinstance(request, dict) or set(request) != {"id", "session", "execution_hash", "file"}
                or any(not isinstance(request[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request[k])
                       for k in ("id", "session"))
                or not isinstance(request["execution_hash"], str)
                or not re.fullmatch(r"[0-9a-f]{16}", request["execution_hash"])
                or not isinstance(request["file"], str) or not request["file"]):
            raise ValueError("Invalid recovery attempt request")

    def _save(self, **changes):
        # Keep the actual outcome in memory even if this write fails. The
        # current attempt stops; a fresh explicit request is assessed separately.
        self.record.update(changes)
        self.persist(copy.deepcopy(self.record))

    def run(self, request, stages, cancelled=lambda: False):
        if self.busy:
            raise ValueError("Recovery attempt is running")
        self._validate_request(request)
        if self.record is not None and request["id"] == self.record["request"]["id"]:
            raise ValueError("Recovery request was already attempted")
        stages = tuple(stages)
        names = [stage[0] for stage in stages]
        if (not stages or len(set(names)) != len(names)
                or any(not isinstance(name, str) or not re.fullmatch(r"[a-z_]{1,48}", name) for name in names)
                or any(len(stage) != 3 or not callable(stage[1]) or not callable(stage[2]) for stage in stages)):
            raise ValueError("Invalid recovery stages")
        self.busy = True
        self.record = {"version": 1, "request": copy.deepcopy(request), "state": "pending",
                       "stages": [{"name": name, "state": "pending"} for name in names], "error": ""}
        try:
            self._save()
            for index, (name, dispatch, verify) in enumerate(stages):
                if cancelled():
                    self._save(state="stopped", error="Recovery stopped before " + name)
                    return copy.deepcopy(self.record)
                self.record["stages"][index]["state"] = "running"
                self._save(state="running")
                dispatch()
                if verify() is not True:
                    raise ValueError("Recovery completion was not confirmed: " + name)
                self.record["stages"][index]["state"] = "complete"
                self._save()
            self._save(state="complete")
            return copy.deepcopy(self.record)
        except Exception as error:
            self.record.update(state="unknown", error=str(error))
            try:
                self.persist(copy.deepcopy(self.record))
            except Exception:
                # The previous on-disk pending/running record also restores as
                # unknown. Keep the original failure rather than masking it.
                pass
            raise
        finally:
            self.busy = False


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
        gcode.register_command("WMP_TOOLHEAD_ACTION", self.cmd_TOOLHEAD_ACTION,
                               desc="Take or dock a physical head using WM toolchange macros")
        gcode.register_command("WMP_PROFILE_IMPORT", self.cmd_PROFILE_IMPORT,
                               desc="Scan, review and save Orca filament presets from USB")
        gcode.register_command("WMP_SET_NOZZLE", self.cmd_SET_NOZZLE,
                               desc="Save physical nozzle settings without restarting or moving")
        gcode.register_command("WM_MATERIAL_STATUS", self.cmd_STATUS,
                               desc=self.cmd_STATUS_help)

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

    def cmd_PROFILE_IMPORT(self, gcmd):
        self._drain_async_completions()
        if self.printer.lookup_object("openace", None) is not None:
            raise gcmd.error("This catalogue is managed by standalone WM+")
        now = self.printer.get_reactor().monotonic()
        if self._profile_import_busy:
            raise gcmd.error("Profile import is busy")
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid import request ID")
        action = gcmd.get("ACTION")
        if action not in ("scan", "review", "save"):
            raise gcmd.error("Unknown profile import action")
        if action == "save" and not self._idle_for_filament_settings(now):
            raise gcmd.error("Profile import save requires an idle printer: " + getattr(self, "_idle_settings_refusal", "idle admission was not confirmed"))
        value = gcmd.get("FILE") if action == "review" else gcmd.get("TOKEN") if action == "save" else ""
        if action != "scan" and not re.fullmatch(r"[0-9a-f]{%d}" % (64 if action == "review" else 48), value):
            raise gcmd.error("Invalid profile selection")
        self._profile_import_busy = True
        self.profile_import = {"state": "busy", "action": action, "id": request_id}
        reactor = self.printer.get_reactor()
        def worker():
            try:
                if action == "scan": result = self._profile_importer.scan()
                elif action == "review": result = self._profile_importer.review(value)
                else: result = self._profile_importer.save(value)
            except Exception as error:
                result = {"state": "error", "message": str(error)}
            def finish(now):
                if action == "save":
                    self._status_catalogue_snapshot = None
                result["id"] = request_id
                self.profile_import = result
                self._profile_import_busy = False
            self._queue_async_completion(finish)
        try:
            threading.Thread(target=worker, name="wm-profile-import", daemon=True).start()
        except Exception as error:
            self._profile_import_busy = False
            self.profile_import = {"state": "error", "action": action,
                                   "id": request_id, "message": str(error)}
            raise

    def _afc_ready(self):
        self._afc_stopped = False
        self._afc_busy = False
        self._afc_last = None
        self._afc_error = ""
        self._afc_declined = []
        gcode = self.printer.lookup_object("gcode")
        owner = self.printer.lookup_object("openace", None) or self.printer.lookup_object("AFC", None)
        commands = gcode.get_status(self.printer.get_reactor().monotonic()).get("commands", {})
        for name in ("SET_COLOR", "SET_MATERIAL", "AFC_SET_SPOOL_TEMP", "WMP_SET_BRAND"):
            if owner or name in commands:
                self._afc_declined.append(name)
                continue
            gcode.register_command(name, self.cmd_AFC_METADATA, desc="Set standalone WM+ filament metadata; no motion")
        self.printer.get_reactor().register_timer(self._afc_tick, self.printer.get_reactor().NOW)

    def _afc_stop(self, *args):
        self._afc_stopped = True

    def _lane_data(self, now):
        previous = getattr(self, '_status_observation_cache', None)
        self._status_observation_cache = {} if previous is None else previous
        try:
            return self._lane_snapshot(now)
        finally:
            self._status_observation_cache = previous

    def _lane_snapshot(self, now):
        if self.printer.lookup_object("openace", None) or self.printer.lookup_object("AFC", None):
            return {}
        profiles, revision = self._profiles()
        presence = self._loaded_filament_status(now)
        saved = self.printer.lookup_object("save_variables", None)
        variables = saved.get_status(now).get("variables", {}) if saved else {}
        rows = {}
        for tool in range(4):
            head = variables.get("box_modify_t%d" % tool, tool)
            if type(head) is not int or not 0 <= head < 4:
                continue
            heater = "extruder" if head == 0 else "extruder%d" % head
            if self.printer.lookup_object(heater, None) is None:
                continue
            loaded = presence["h%d" % head]["state"] == "loaded"
            # Orca treats a nonempty material as presence, ignoring `loaded`.
            # Keep saved spool metadata canonical, but expose it only when sensed.
            identity = profiles.get("h%d" % head, {}) if loaded else {}
            rows["wmplus_tool_%d" % tool] = {
                "lane": str(tool), "extruder_index": head,
                "material": identity.get("material", ""), "color": identity.get("color", ""),
                "bed_temp": identity.get("bed_temp", 0),
                "nozzle_temp": identity.get("nozzle_temp", dict(MATERIALS).get(identity.get("material"), 0)),
                "spool_id": None, "weight": None, "unit": None, "unit_name": None, "slot": None,
                "name": " ".join(filter(None, (identity.get("brand"), identity.get("material")))),
                "loaded": loaded,
                "brand": identity.get("brand", ""),
                "nozzle_temp_min": identity.get("nozzle_temp_min", 0),
                "nozzle_temp_max": identity.get("nozzle_temp_max", 0),
            }
        return rows

    def cmd_AFC_METADATA(self, gcmd):
        if self.printer.lookup_object("openace", None) or self.printer.lookup_object("AFC", None):
            raise gcmd.error("Another filament manager owns this printer")
        now = self.printer.get_reactor().monotonic()
        lane = gcmd.get("LANE").strip()
        # Match openACE's public lane forms, resolving logical tools through the
        # same current mapping used to publish lane_data (not as physical IDs).
        match = re.fullmatch(r"(?:wmplus_tool_|[Tt])?([0-3])", lane)
        if match is None:
            raise gcmd.error("Unknown WM+ lane; use wmplus_tool_N, TN or N (0-3)")
        lane = "wmplus_tool_" + match.group(1)
        rows = self._lane_data(now)
        if lane not in rows:
            raise gcmd.error("Unknown WM+ lane")
        head = rows[lane]["extruder_index"]
        profiles, revision = self._profiles()
        identity = dict(profiles.get("h%d" % head, {"brand": "Generic", "material": "Unknown", "color": "#888888"}))
        command = gcmd.get_command()
        if command == "SET_COLOR":
            value = gcmd.get("COLOR")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
                raise gcmd.error("COLOR must be six hex digits without #")
            identity["color"] = "#" + value.upper()
        elif command == "SET_MATERIAL":
            identity["material"] = gcmd.get("MATERIAL")
            # Changing material invalidates the previous spool's temperature recipe.
            for key in ("nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"):
                identity.pop(key, None)
        elif command == "WMP_SET_BRAND":
            identity["brand"] = gcmd.get("BRAND")
        elif command == "AFC_SET_SPOOL_TEMP":
            for param, key in (("BED_TEMP", "bed_temp"), ("EXTRUDER_TEMP", "nozzle_temp"),
                               ("MIN_TEMP", "nozzle_temp_min"), ("MAX_TEMP", "nozzle_temp_max")):
                value = gcmd.get(param, None)
                if value is not None:
                    identity[key] = float(value)
        else:
            raise gcmd.error("Unsupported metadata command")
        # Reuse the native editor's atomic storage and idle/ownership validation.
        proxy = self.printer.lookup_object("gcode").create_gcode_command(
            "WMP_SET_FILAMENT", "", {"HEAD": str(head), "EXPECT": revision,
                                      "PROFILE": json.dumps(identity).encode().hex()})
        self.cmd_SET_FILAMENT(proxy)

    def _afc_tick(self, now):
        self._drain_async_completions(now)
        reactor = self.printer.get_reactor()
        if self._afc_stopped:
            return reactor.NEVER
        if not self._afc_busy:
            try:
                rows = self._lane_data(now)
                if rows != self._afc_last:
                    self._afc_busy = True
                    try:
                        threading.Thread(target=self._afc_publish, args=(rows,), daemon=True).start()
                    except Exception:
                        self._afc_busy = False
                        raise
            except Exception as error:
                self._afc_error = str(error)
        return now + 2.

    def _afc_publish(self, rows):
        # Network I/O never runs on Klipper's reactor. Touch only immutable rows
        # here; publish completion back on the reactor. Retire only known WM+ /
        # inactive openACE projection keys; unrelated AFC records are untouched.
        error = ""
        try:
            def call(method, query="", body=None, endpoint="/server/database/item"):
                if self._afc_stopped:
                    raise ValueError("Publisher stopped")
                req = urllib.request.Request("http://127.0.0.1:7125" + endpoint + query,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={"Content-Type": "application/json"}, method=method)
                with urllib.request.urlopen(req, timeout=2) as response:
                    return json.load(response)
            def owner_now():
                status = call("GET", "?wm_material=session_id,afc_metadata", endpoint="/printer/objects/query")["result"]["status"]["wm_material"]
                if status.get("session_id") != self.session_id:
                    raise ValueError("Filament publisher session changed")
                owner = status.get("afc_metadata", {}).get("owner")
                if owner not in ("standalone", "openace", "AFC"):
                    raise ValueError("Filament publisher ownership unavailable")
                return owner
            owner = owner_now()
            if rows and owner != "standalone":
                raise ValueError("Another filament manager owns this printer")
            def mutate(method, query="", body=None):
                if owner_now() != owner:
                    raise ValueError("Filament publisher ownership changed")
                return call(method, query, body)
            try:
                old = call("GET", "?namespace=lane_data").get("result", {}).get("value", {})
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                old = {}
            # Publish replacements before retiring stale cached projections.
            for key, value in rows.items():
                if old.get(key) != value:
                    mutate("POST", body={"namespace": "lane_data", "key": key, "value": value})
            for key in old:
                own_obsolete = re.fullmatch(r"wmplus_tool_[0-9]+", key) and key not in rows
                ace_obsolete = owner == "standalone" and re.fullmatch(r"openace_tool_[0-9]+", key)
                if own_obsolete or ace_obsolete:
                    mutate("DELETE", "?namespace=lane_data&key=" + urllib.parse.quote(key))
        except Exception as exc:
            error = str(exc)
        def finished(now):
            self._afc_busy = False
            self._afc_error = error
            if not error:
                self._afc_last = rows
        self._queue_async_completion(finished)

    def _saved_variables_ready(self):
        store = self.printer.lookup_object("save_variables", None)
        self._saved_variables_cache_active = (store is not None and
            wmp_saved_variables.install(store, self._yield_saved_variables))

    def _yield_saved_variables(self):
        # Stock tool macros issue several saves before their first motion wait.
        # While our serialized procedure owns those commands, let status timers
        # run after each complete save. The G-code mutex remains held, so another
        # command cannot interleave with the procedure. No added yields in prints
        # or ordinary stock callers outside a WM+ procedure or calibration.
        # Calibration invokes stock tool changes directly, without publishing a
        # managed toolhead_operation. Those saves need the same cooperation.
        recovery = self.printer.lookup_object("wmp_recovery", None)
        calibration = getattr(recovery, "calibration", None)
        if (getattr(calibration, "active", False) is True or
                any(getattr(self, name, {}).get("state") == "running"
                    for name in ("toolhead_operation", "filament_operation"))):
            reactor = self.printer.get_reactor()
            reactor.pause(reactor.monotonic())

    def _refresh(self, eventtime=None):
        try:
            mtime = os.path.getmtime(self.ini_path)
        except OSError:
            self._mtime, self._slots = None, {}
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.ini_path, "r", errors="replace") as f:
                self._slots = parse_slot_materials(f.read())
            self._mtime = mtime
        except OSError:
            self._mtime, self._slots = None, {}

    def get_status(self, eventtime):
        self._drain_async_completions(eventtime)
        previous = getattr(self, '_status_observation_cache', None)
        self._status_observation_cache = {}
        try:
            return self._status_snapshot(eventtime)
        finally:
            self._status_observation_cache = previous

    def _status_snapshot(self, eventtime):
        if eventtime is None:
            eventtime = self.printer.get_reactor().monotonic()
        self._refresh()
        status = {"available": self._mtime is not None,
                  "ini_path": self.ini_path, "session_id": self.session_id,
                  "command_generation": getattr(self, "_command_generation", 0),
                  "command_generation_protocol": 1,
                  "attachment": self._attachment(eventtime),
                  "toolhead_action_protocol": 1,
                  "material_request_sequence_protocol": 1,
                  "filament_request_sequence": getattr(self, "_filament_request_sequence", 0),
                  "toolhead_request_sequence": getattr(self, "_toolhead_request_sequence", 0),
                  "toolhead_recovery_protocol": 1,
                  "toolhead_operation": dict(getattr(self, "toolhead_operation", {})),
                  "toolchange_pause": self._toolchange_pause_status(),
                  "print_submission": dict(self.print_submission),
                  "print_cancel": copy.deepcopy(getattr(self, "_print_cancel", {})),
                  "print_cancel_protocol": 1,
                  "script_generation_protocol": 1 if getattr(self, "_cancel_script_wrapper", None) is not None else 0,
                  "print_cancel_ingress_protocol": 1 if getattr(self, "_cancel_script_wrapper", None) is not None else 0,
                  "print_cancel_resolution_protocol": 1,
                  "print_cancel_resolution": copy.deepcopy(getattr(self, "_print_cancel_resolution", {})),
                  "recovery_review_protocol": 1,
                  "recovery_continue_protocol": 1,
                  "recovery_ticket_protocol": 1,
                  "recovery_stop_protocol": 1,
                  "recovery_resolution_protocol": 1,
                  "recovery_retirement_protocol": 1,
                  "recovery_resolution": copy.deepcopy(getattr(self, "_recovery_resolution", {})),
                  "recovery_retirement": copy.deepcopy(getattr(self, "_recovery_retirement_result", {})),
                  "recovery_stop_requested": getattr(self, "_recovery_stop_request", None) is not None,
                  "recovery_submission": copy.deepcopy(getattr(self, "_recovery_submission", {})),
                  "recovery_attempt": self._recovery_attempt_status(),
                  "recovery_restore_error": getattr(self, "_recovery_restore_error", ""),
                  "recovery_execution_sampler": {
                      "state": getattr(self, "_execution_state", "starting"),
                      "error": getattr(self, "_execution_error", ""),
                      "pending": getattr(self, "_pending_execution_snapshot", None) is not None,
                      "published": getattr(self, "_execution_last_boundary", None) is not None},
                  "recovery_temperatures": copy.deepcopy(getattr(self, "_recovery_temperatures", {})),
                  "profile_import_protocol": 1,
                  "profile_import": dict(getattr(self, "profile_import", {"state": "idle"})),
                  "print_mesh_persisted": getattr(self, "_print_mesh_persisted", None),
                  "print_recovery_error": getattr(self, "_print_recovery_error", ""),
                  "recovery_invalidation_error": getattr(self, "_recovery_invalidation_error", ""),
                  "print_start_protocol": 1,
                  "print_sequence_protocol": 1,
                  "print_material_confirmation_protocol": 1,
                  "print_request_sequence": getattr(self, "_print_request_sequence", 0),
                  "openace_print_start_protocol": 1,
                  "filament_check_protocol": 0 if any(self.printer.lookup_object(owner, None) is not None
                      for owner in ("openace", "AFC")) else 1,
                  "filament_presence": self._sensor_filament_status(eventtime),
                  "filament_loaded": self._loaded_filament_status(eventtime),
                  "filament_presence_error": getattr(self, "_filament_presence_error", ""),
                  "filament_sequence_protocol": 1,
                  "filament_cancel_protocol": 1,
                  "filament_recovery_protocol": 1,
                  "openace_unload_protocol": 1,
                  "openace_load_protocol": 1,
                  "filament_materials": [name for name, temperature in MATERIALS],
                  "filament_operation": dict(self.filament_operation),
                  "afc_metadata": {"owner": "openace" if self.printer.lookup_object("openace", None) is not None else "AFC" if self.printer.lookup_object("AFC", None) is not None else "standalone",
                                   "error": getattr(self, "_afc_error", ""), "declined_commands": getattr(self, "_afc_declined", [])},
                  "filament_checks": self._filament_status(eventtime)}
        status["paused_filament"] = self._paused_filament_status(eventtime)
        status["paused_toolhead_actions"] = self._ordinary_paused_toolhead_status(eventtime)
        status["resume_progress"] = dict(getattr(self, "_resume_progress", {}))
        status["filament_position"] = self._filament_position_status(eventtime)
        status["filament_recipe_write_protocol"] = 1
        status["filament_recipe_write"] = self._recipe_write_status(eventtime)
        status.update(self._nozzle_status(eventtime))
        status.update(self._screen_configuration_status(eventtime))
        try:
            cached_catalogue = getattr(self, '_status_catalogue_snapshot', None)
            if cached_catalogue is None:
                cached_catalogue = wmp_orca_profiles.read_catalogue(getattr(self, "catalogue_path", os.path.join(os.path.dirname(self.profile_path), "wmp_filament_catalogue.json")))
                self._status_catalogue_snapshot = copy.deepcopy(cached_catalogue)
            catalogue, revision = copy.deepcopy(cached_catalogue)
            status["filament_catalogue"] = list(catalogue.values())
            status["catalogue_revision"] = revision
        except (ValueError, OSError) as error:
            status["filament_catalogue"] = []
            status["catalogue_error"] = str(error)
        for slot in range(SLOTS):
            idx = self._slots.get(slot, -1)
            status["index%d" % slot] = idx
            status["material%d" % slot] = material_name(idx)
            status["temp%d" % slot] = material_temp(idx)
        try:
            profiles, revision = self._profiles()
            status.update(identities=profiles, identity_revision=revision,
                          identity_writable=True, identity_error="; ".join(getattr(self, "_profile_entry_errors", {}).values()),
                          identity_entry_errors=copy.deepcopy(getattr(self, "_profile_entry_errors", {})))
        except (ValueError, OSError) as error:
            status.update(identities={}, identity_revision="", identity_writable=False,
                          identity_error=str(error))
        status["filament_procedures"] = []
        status["filament_procedure_errors"] = {}
        ace_status_cache = {}
        for head in range(SLOTS):
            for action in ("load", "unload"):
                try:
                    if action == "load" and self.printer.lookup_object("openace", None) is not None:
                        status["filament_procedures"].extend(self._openace_load_plans(head, eventtime, ace_status_cache))
                    else:
                        status["filament_procedures"].append(self._filament_plan(head, action, eventtime, ace_status_cache))
                except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
                    status["filament_procedure_errors"]["h%d:%s" % (head, action)] = str(error)
        return status

    def _toolhead_operation_path(self):
        return os.path.join(os.path.dirname(self.profile_path), "wmp_toolhead_operation.json")

    def _persist_toolhead_operation(self):
        operation = self.toolhead_operation
        if not operation.get("id"):
            return
        path = self._toolhead_operation_path()
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-toolhead-", dir=parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "operation": operation}, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _record_toolhead_result(self):
        try:
            self._persist_toolhead_operation()
        except Exception as error:
            message = str(error)[:512]
            if self.toolhead_operation.get("persistence_error") != message:
                logging.exception("Unable to persist toolhead result")
            self.toolhead_operation["persistence_error"] = message

    def _restore_toolhead_operation(self):
        path = self._toolhead_operation_path()
        try:
            with open(path) as stream:
                payload = stream.read(131073)
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as error:
            self.toolhead_operation = {"state": "unknown", "message": "Saved toolhead result is unreadable: " + str(error)[:512]}
            return
        try:
            record = json.loads(payload)
            operation = record["operation"]
            if (len(payload) > 131072 or record.get("version") != 1
                    or not isinstance(operation, dict)
                    or not isinstance(operation.get("id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", operation["id"])
                    or operation.get("head") not in ("h0", "h1", "h2", "h3")
                    or operation.get("action") not in ("take", "dock")
                    or operation.get("state") not in ("running", "unknown", "complete", "failed", "refused")):
                raise ValueError("invalid operation")
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.toolhead_operation = {"state": "unknown", "message": "Saved toolhead result is invalid: " + str(error)[:512]}
            return
        operation["previous_session"] = operation.get("previous_session", operation.get("session", ""))
        operation["session"] = self.session_id
        if operation["state"] in ("running", "unknown"):
            operation.update(state="unknown", message="Toolhead operation interrupted by restart; verify attachment before continuing")
            operation.pop("recovered", None)
        self.toolhead_operation = operation
        self._toolhead_requests.add(operation["id"])

    def _material_operation_active(self, name):
        state = getattr(self, name, {}).get("state")
        if state in ("pending", "running"):
            return True
        # External integration is unchanged by the standalone lifecycle repair.
        return (state == "unknown" and any(self.printer.lookup_object(owner, None) is not None
                                          for owner in ("openace", "AFC")))

    def _begin_explicit_physical_action(self, action, allow_active=False):
        """Retire historical fault authority at a fresh user action only.

        Internal macros and post-effect checks must never call this. The
        retained saved-variable status exposes the live dictionary; clearing
        history here needs no diagnostic file write and no replay of old work.
        """
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return
        now = self.printer.get_reactor().monotonic()
        saved_object = self.printer.lookup_object("save_variables", None)
        if saved_object is None:
            return
        saved = saved_object.get_status(now).get("variables", {})
        old = saved.get("fail_flag", 0)
        mode = saved.get("is_nozzle_setting", 0)
        retire_mode = action == "head identification" and mode != 0
        if old == 0 and not retire_mode:
            saved.setdefault("fail_flag", 0)
            return
        gcode = self.printer.lookup_object("gcode")
        if self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
            raise ValueError("Cannot retry while printer is shutdown or stopped")
        if (self._print_cancel_active() or self._recovery_attempt_active()
                or any(self._material_operation_active(name)
                       for name in ("filament_operation", "toolhead_operation"))):
            raise ValueError("Wait for the current physical operation to stop before retrying")
        recovery = self.printer.lookup_object("wmp_recovery", None)
        if recovery is not None:
            current = recovery.get_status(now)
            if (current.get("calibration_active") or current.get("homing")
                    or current.get("identification", {}).get("state") in ("pending", "running")):
                raise ValueError("Wait for current calibration, homing or head identification to stop before retrying")
        sd = self.printer.lookup_object("virtual_sdcard", None)
        if not allow_active and sd is not None and (sd.is_active() or sd.is_cmd_from_sd()):
            raise ValueError("Wait for the current print to stop before retrying")
        if mode != 0 and not retire_mode:
            raise ValueError("Head identification mode remains set; inspect the printer, then retry Head identification to restore normal sensor checks")
        if retire_mode and (type(mode) is not int or mode != 1):
            raise ValueError("Head identification mode is invalid: is_nozzle_setting=%r; inspect the saved configuration before retrying Head identification" % mode)
        # Stationary UNLOCK is itself the way to correct a constrained carriage.
        # Other retries require a coherent present attachment, not an old code.
        if action != "UNLOCK":
            attachment = self._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("Current head attachment sensors disagree; inspect seating and release the coupling before retrying")
        if retire_mode:
            # Bypass mode changes physical sensor checks, unlike a diagnostic
            # fault. Restore it durably and verify before a new setup sequence.
            # Only deliberate identification Retry/Start owns this transition.
            try:
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0")
                # Stock SAVE_VARIABLE reloads and replaces its dictionary.
                saved = saved_object.get_status(self.printer.get_reactor().monotonic()).get("variables", {})
                observed = saved.get("is_nozzle_setting")
                if type(observed) is not int or observed != 0:
                    raise ValueError("clear readback is %r, expected integer 0" % observed)
            except Exception as error:
                raise ValueError("Cannot restore normal head sensor checks: %s. No identification movement started; correct the reported issue and retry Head identification" % error) from error
            logging.info("Explicit head identification retry cleared interrupted identification mode")
        saved["fail_flag"] = 0
        logging.info("Fresh %s retires historical toolhead failure %r", action, old)

    def _ordinary_paused_toolhead_context(self, head, action, now, allow_toolhead=False):
        origin = getattr(self, "_pause_origin", None)
        if getattr(self, "_toolchange_pause", None) or not origin or origin.get("kind") == "toolchange":
            raise ValueError("Ordinary paused print context is unavailable")
        self._paused_filament_origin(head, now)
        if origin["head"] != "h%d" % head:
            raise ValueError("Select the original paused Head %d" % (int(origin["head"][1:]) + 1))
        if (self.printer.is_shutdown() or self._print_cancel_active()
                or self.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise ValueError("Paused head repair needs valid XYZ reference and no cancellation")
        if self._identification_pending(now):
            raise ValueError("Wait for head identification")
        if (self._material_operation_active("filament_operation")
                or (not allow_toolhead and self._material_operation_active("toolhead_operation"))):
            raise ValueError("Wait for the current physical operation")
        offset = origin.get("offset")
        if (not isinstance(offset, (list, tuple)) or len(offset) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offset)):
            raise ValueError("Captured paused coordinate offset is unavailable")
        attachment = self._attachment(now)
        expected = {"state": "attached", "head": origin["head"]} if action == "dock" else {"state": "empty", "head": ""}
        if action not in ("take", "dock") or attachment != expected:
            raise ValueError("Dock the original paused head, or mount it from an empty carriage")
        return origin

    def _ordinary_paused_toolhead_status(self, now):
        result = {"head": "", "actions": [], "reason": ""}
        try:
            origin = getattr(self, "_pause_origin", None)
            if not origin or getattr(self, "_toolchange_pause", None):
                return result
            result["head"] = origin["head"]
            action = "take" if self._attachment(now).get("state") == "empty" else "dock"
            self._ordinary_paused_toolhead_context(int(origin["head"][1:]), action, now)
            result["actions"] = [action]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            result["reason"] = str(error)
        return result

    def _toolhead_context(self, head, action, now, fresh=False):
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another filament manager owns toolhead operations: " + ("openace" if self.printer.lookup_object("openace", None) is not None else "AFC"))
        if type(head) is not int or not 0 <= head < SLOTS or action not in ("take", "dock"):
            raise ValueError("Invalid physical toolhead action")
        if not self._idle_for_filament_settings(now):
            # Explicit repair of this stopped fault is not a competing print.
            # Dispatch revalidates the same binding while its own receipt runs.
            if getattr(self, "_toolchange_pause", None):
                self._fault_pause_context(now, allow_toolhead=True)
            elif (getattr(self, "_pause_origin", None)
                  and self._pause_origin.get("kind") != "toolchange"):
                self._ordinary_paused_toolhead_context(head, action, now, allow_toolhead=True)
            else:
                raise ValueError("Toolhead changes require an idle printer or a captured paused print: " + getattr(self, "_idle_settings_refusal", "idle admission was not confirmed"))
            if self._identification_pending(now):
                raise ValueError("Wait for head identification")
        if self._material_operation_active("filament_operation"):
            raise ValueError("Resolve the filament operation first")
        attachment = self._attachment(now)
        if attachment["state"] not in ("attached", "empty"):
            raise ValueError("Head attachment sensors disagree")
        if action == "dock" and attachment != {"state": "attached", "head": "h%d" % head}:
            raise ValueError("Selected head is not mounted")
        macro = "_CHANGE_TOOL" if action == "take" else "PARK_CURRENT_TOOL"
        if self.printer.lookup_object("gcode_macro " + macro, None) is None:
            raise ValueError("WM toolchange macro is unavailable")
        saved = self.printer.lookup_object("save_variables").get_status(now).get("variables", {})
        if (not fresh and saved.get("fail_flag", 0) != 0) or saved.get("is_nozzle_setting", 0) != 0:
            raise ValueError("Inspect the head, then retry Head identification if setup mode remains set; current: " + ("fail_flag=" + repr(saved.get("fail_flag", 0))[:80] if saved.get("fail_flag", 0) != 0 else "is_nozzle_setting=" + repr(saved.get("is_nozzle_setting", 0))[:80]))
        # Preserve normal macro travel/homing. Standalone failure branches retain
        # their faults and refuse automatic coupling, homing or tool-change retries.
        return attachment

    def _admit_material_sequence(self, gcmd, kind, request_id):
        sequence = gcmd.get("SEQUENCE", None)
        if sequence is None:
            if request_id.startswith(("filament_", "toolhead_")):
                raise gcmd.error("Sequenced material request requires SESSION and SEQUENCE; review again")
            return False
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Sequenced material requests require standalone ownership")
        if gcmd.get("SESSION", None) != self.session_id:
            raise gcmd.error("Printer session changed; review again")
        sequence = gcmd.get_int("SEQUENCE", minval=1, maxval=9223372036854775807)
        if request_id != kind + "_" + str(sequence):
            raise gcmd.error("Material request ID does not match SEQUENCE")
        key = "_" + kind + "_request_sequence"
        if sequence <= getattr(self, key, 0):
            raise gcmd.error("Material request already attempted or superseded; review again")
        # Consume before any semantic refusal or effect. Missing sequence numbers
        # are valid (a UI may abandon queued work); none can later be replayed.
        setattr(self, key, sequence)
        return True

    def cmd_TOOLHEAD_ACTION(self, gcmd):
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid toolhead request ID")
        if gcmd.get("SESSION") != self.session_id:
            raise gcmd.error("Printer session changed")
        sequenced = self._admit_material_sequence(gcmd, "toolhead", request_id)
        requests = self._toolhead_requests
        if not sequenced and request_id in requests:
            raise gcmd.error("Toolhead request already attempted; inspect its result")
        if not sequenced and len(requests) >= 1024:
            raise gcmd.error("Legacy toolhead request limit reached; use the current touchscreen or a SESSION/SEQUENCE request")
        if self._material_operation_active("toolhead_operation"):
            raise gcmd.error("Previous toolhead operation is unresolved")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        reactor = self.printer.get_reactor()
        try:
            attachment = self._toolhead_context(head, action, reactor.monotonic(), fresh=True)
            paused_origin = (getattr(self, "_pause_origin", None)
                             if not getattr(self, "_toolchange_pause", None)
                             and self.printer.lookup_object("print_stats").get_status(reactor.monotonic()).get("state") == "paused" else None)
            expected = gcmd.get("ATTACHED")
            if expected != (attachment["head"] or "none"):
                raise ValueError("Head attachment changed; review again")
            self._begin_explicit_physical_action("toolhead " + action)
        except (ValueError, KeyError, AttributeError, TypeError) as error:
            # A validated request rejected before dispatch still needs an
            # authoritative receipt. An RPC error alone cannot tell the UI
            # whether a physical operation started.
            if not sequenced:
                requests.add(request_id)
            self.toolhead_operation = {"id": request_id, "session": self.session_id,
                "head": "h%d" % head, "action": action, "state": "refused",
                "message": str(error)}
            raise gcmd.error(str(error))
        if not sequenced:
            requests.add(request_id)
        self.toolhead_operation = {"id": request_id, "session": self.session_id,
                                   "head": "h%d" % head, "action": action,
                                   "state": "running", "message": "Taking head" if action == "take" else "Docking head",
                                   "phase": "checking", "steps": [
                                       {"phase": "checking", "label": "Check head attachment"},
                                       {"phase": "moving", "label": "Mount head" if action == "take" else "Dock head"},
                                       {"phase": "verifying", "label": "Verify attachment sensors"}]}
        # Record intent for diagnostics. Live ownership and the session/request
        # generation retire callbacks independently of durable acknowledgement.
        self._record_toolhead_result()
        generation = getattr(self, "_command_generation", 0)
        session = self.session_id
        scheduling_failed = False
        def execute(now):
            if scheduling_failed:
                return
            dispatched = False
            try:
                gcode = self.printer.lookup_object("gcode")
                with gcode.get_mutex():
                    if session != self.session_id or generation != getattr(self, "_command_generation", 0):
                        raise ValueError("Toolhead request invalidated by cancellation or restart")
                    if paused_origin is not None and getattr(self, "_pause_origin", None) is not paused_origin:
                        raise ValueError("Paused print context changed before dispatch")
                    if self._toolhead_context(head, action, reactor.monotonic()) != attachment:
                        raise ValueError("Head attachment changed before dispatch")
                    run = gcode.run_script_from_command
                    # The legacy dock macro reads current_extruder. Reconcile
                    # that bookkeeping from sensors, never from a UI selection.
                    if attachment["state"] == "attached":
                        run("SAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % int(attachment["head"][1]))
                    dispatched = True
                    self.toolhead_operation["phase"] = "moving"
                    run("_CHANGE_TOOL T=%d" % head if action == "take" else "PARK_CURRENT_TOOL")
                    run("M400")
                    self.toolhead_operation["phase"] = "verifying"
                    observed = self._attachment(reactor.monotonic())
                    wanted = {"state": "attached", "head": "h%d" % head} if action == "take" else {"state": "empty", "head": ""}
                    saved = self.printer.lookup_object("save_variables").get_status(reactor.monotonic()).get("variables", {})
                    if observed != wanted or saved.get("fail_flag", 0) != 0:
                        raise ValueError("Toolhead sensors did not confirm completion")
                    if paused_origin is not None and action == "take":
                        if generation != getattr(self, "_command_generation", 0) or self.printer.is_shutdown() or self._print_cancel_active():
                            raise ValueError("Paused head repair interrupted before offset restoration")
                        self._paused_filament_origin(head, reactor.monotonic())
                        # Stock pickup restores its configured offset, whereas
                        # this paused job may have an additional user offset.
                        # Preserve physical position and the original PAUSE states.
                        run("SET_GCODE_OFFSET X=%.17g Y=%.17g Z=%.17g MOVE=0" % tuple(paused_origin["offset"]))
                    self.toolhead_operation.update(state="complete", message="Head mounted" if action == "take" else "Head docked")
            except Exception as error:
                if dispatched:
                    self._command_generation = getattr(self, "_command_generation", 0) + 1
                self.toolhead_operation.update(state="unknown" if dispatched else "refused", message=str(error))
            finally:
                self._record_toolhead_result()
        try:
            reactor.register_callback(execute)
        except Exception as error:
            # A scheduler may enqueue before raising. Retire that callback as
            # well as the receipt, so it cannot move after a reported refusal.
            scheduling_failed = True
            self.toolhead_operation.update(state="refused", message=str(error))
            self._record_toolhead_result()
            raise

    def cmd_RECOVER_TOOLHEAD(self, gcmd):
        operation = self.toolhead_operation
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        if (gcmd.get("SESSION") != self.session_id or operation.get("session") != self.session_id
                or gcmd.get("ID") != operation.get("id") or operation.get("head") != "h%d" % head):
            reason = ("SESSION differs from printer session" if gcmd.get("SESSION") != self.session_id else
                      "operation session differs from printer session" if operation.get("session") != self.session_id else
                      "ID differs from operation" if gcmd.get("ID") != operation.get("id") else
                      "HEAD differs from operation; requested=h%d, recorded=%s" % (head, str(operation.get("head"))[:80]))
            raise gcmd.error("Toolhead operation changed; reopen recovery: " + reason)
        if operation.get("state") != "unknown" or operation.get("action") not in ("take", "dock"):
            raise gcmd.error("Toolhead operation does not need reconciliation: state=%s, action=%s" % (str(operation.get("state"))[:80], str(operation.get("action"))[:80]))

        def context():
            if (self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Another filament manager owns this printer")
            now = self.printer.get_reactor().monotonic()
            if not self._idle_for_filament_settings(now):
                raise ValueError("Toolhead recovery requires an idle printer")
            if self._material_operation_active("filament_operation"):
                raise ValueError("Resolve the filament operation first")
            saved = self.printer.lookup_object("save_variables").get_status(now).get("variables", {})
            if saved.get("fail_flag") != 0 or saved.get("is_nozzle_setting") != 0:
                raise ValueError("Finish stock toolhead recovery or setup first")
            attachment = self._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("Head attachment sensors disagree")
            return attachment

        try:
            self._begin_explicit_physical_action("toolhead reconcile")
            context()
        except (ValueError, KeyError, AttributeError, TypeError) as error:
            operation.update(message="Recovery not confirmed: " + str(error))
            raise gcmd.error(operation["message"])
        operation.update(phase="draining", steps=[
            {"phase": "draining", "label": "Wait for motion to stop"},
            {"phase": "verifying", "label": "Verify attachment sensors"}])
        try:
            # Wait for already queued movement only. Never repeat Take/Dock,
            # clear a stock fault, alter heating, or infer completion from the
            # requested head rather than physical attachment evidence.
            self.printer.lookup_object("gcode").run_script_from_command("M400")
            operation["phase"] = "verifying"
            attachment = context()
        except Exception as error:
            operation.update(message="Recovery not confirmed: " + str(error))
            raise gcmd.error(operation["message"])
        message = ("Stopped. Head %d is mounted." % (int(attachment["head"][1:]) + 1)
                   if attachment["state"] == "attached" else "Stopped. All heads are docked.")
        operation.update(state="failed", recovered=True, recovery_attachment=attachment, message=message)
        self._record_toolhead_result()
        gcmd.respond_info(message)

    def _filament_position_status(self, now):
        recovery = self.printer.lookup_object("wmp_recovery", None)
        if recovery is None:
            return {"ready": True}  # Legacy fixed-position service has no travel.
        try:
            axes = self.printer.lookup_object("toolhead").get_status(now).get("homed_axes", "")
            return {"ready": True, "home_xy": not all(axis in axes for axis in "xy")}
        except (AttributeError, KeyError, TypeError, ValueError):
            return {"ready": False, "reason": "Printer position is unavailable. Wait for fresh printer status."}

    def _service_context(self, head, now, allow_homing=False, allow_history=False, offset_heads=()):
        """Capture calibrated travel and whether stock homing is required."""
        if self._identification_pending(now):
            raise ValueError("Restart Klipper after head identification before filament service")
        def status(name):
            obj = self.printer.lookup_object(name, None)
            if obj is None:
                raise ValueError("Missing service dependency: " + name)
            return obj.get_status(now)
        th = status("toolhead")
        position = self._filament_position_status(now)
        if not position["ready"]:
            raise ValueError(position["reason"])
        needs_home = not all(axis in th.get("homed_axes", "") for axis in "xy")
        if needs_home and not allow_homing:
            raise ValueError("Homing did not establish a valid XY reference")
        attachment = self._attachment(now)
        if attachment["state"] not in ("attached", "empty"):
            raise ValueError("Head attachment sensors disagree")
        saved = status("save_variables").get("variables", {})
        if (not allow_history and saved.get("fail_flag", 0) != 0) or saved.get("is_nozzle_setting", 0) != 0:
            raise ValueError("Inspect the head, then retry Head identification if setup mode remains set; current: " + ("fail_flag=" + repr(saved.get("fail_flag", 0))[:80] if saved.get("fail_flag", 0) != 0 else "is_nozzle_setting=" + repr(saved.get("is_nozzle_setting", 0))[:80]))
        # get_status exposes the live saved-variable dictionary. Keep admission
        # geometry immutable across homing/service yields, including callers
        # that update a coordinate list in place rather than SAVE_VARIABLE.
        positions = copy.deepcopy([saved.get("t%d_position" % i) for i in range(4)])
        offsets = copy.deepcopy([saved.get("t%d_offset" % i) for i in range(4)])
        minimum, maximum = th["axis_minimum"], th["axis_maximum"]
        probe = saved.get("probe_tool", 0)
        if type(probe) is not int or not 0 <= probe < 4:
            raise ValueError("Invalid probe reference")
        current = attachment["head"]
        dock_heads = ({head} | ({int(current[1:])} if current else set())
                      if current != "h%d" % head else set())
        required_offsets = {head, probe} | set(offset_heads)
        if dock_heads and not (minimum[1] <= 270 <= 310 <= maximum[1]):
            raise ValueError("Dock staging path exceeds travel limits")
        for index in sorted(dock_heads):
            point = positions[index]
            if not isinstance(point, (list, tuple)) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                raise ValueError("Invalid dock calibration for Head %d" % (index + 1))
            if not minimum[0] <= point[0] <= maximum[0] or not 310 <= point[1] <= maximum[1] - .4:
                raise ValueError("Dock calibration exceeds travel limits for Head %d" % (index + 1))
        for index in sorted(required_offsets):
            offset = offsets[index]
            if not isinstance(offset, (list, tuple)) or len(offset) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 20 for v in offset):
                raise ValueError("Invalid toolhead offsets for Head %d" % (index + 1))
        if not minimum[0] <= -13 <= maximum[0] or not minimum[1] <= 80 <= maximum[1]:
            raise ValueError("Purge position is outside travel limits")
        return {"attachment": attachment, "positions": positions, "offsets": offsets,
                "probe": probe, "needs_home": needs_home,
                "dock_heads": sorted(dock_heads), "offset_heads": sorted(required_offsets)}

    def _prepare_service(self, head, context, phase_name="preparing"):
        gcode = self.printer.lookup_object("gcode")
        run = gcode.run_script_from_command
        reactor = self.printer.get_reactor()
        def phase(text):
            self.filament_operation.update(message=text)
        def observed(expected):
            run("M400")
            if self._attachment(reactor.monotonic()) != expected:
                raise ValueError("Head attachment sensors do not confirm the move")
        if context.get("needs_home", False):
            self._filament_checkpoint("homing")
            phase("Homing X/Y")
            # XY-only homing must preserve the existing Z datum and probe head.
            run("G28 X Y\nM400")
            self._filament_checkpoint("homing")
            now = reactor.monotonic()
            if not self._filament_context_valid(self.filament_operation, now):
                raise ValueError("Printer became busy during homing: " + getattr(self, "_filament_context_refusal", "context admission was not confirmed"))
            homed = self._service_context(head, now, offset_heads=context.get("offset_heads", ()))
            for key, indices in (("positions", "dock_heads"), ("offsets", "offset_heads")):
                if any(homed[key][index] != context[key][index]
                       for index in set(homed[indices]) & set(context[indices])):
                    raise ValueError("Toolhead calibration changed during homing")
            if homed["probe"] != context["probe"]:
                raise ValueError("Unexpected probe reference after homing")
            # Revalidate calibration and sensor evidence before service travel.
            if "restore_offset" in context:
                homed["restore_offset"] = context["restore_offset"]
            context = homed
        self._filament_checkpoint(phase_name)
        current = context["attachment"]["head"]
        phase("Moving to filament service position")
        # Filament service uses the dock/purge XY path at the existing bed height.
        # Never home, lift, or synthesize a Z reference, including mid-print.
        run("G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
        if current != "h%d" % head:
            if current:
                index = int(current[1]); x, y = context["positions"][index]
                phase("Docking Head %d" % (index + 1))
                run("G1 Y270 F6000\nG1 X%.5f F6000\nG1 Y310 F6000\nG1 Y%.5f F1000\nG4 P1000\nM400" % (x, y))
                dock = self.printer.lookup_object("filament_switch_sensor docked%d" % index).get_status(reactor.monotonic())
                if dock.get("filament_detected") is not True:
                    run("SAVE_VARIABLE VARIABLE=fail_tool VALUE=%d\nSAVE_VARIABLE VARIABLE=fail_flag VALUE=-3" % index)
                    raise ValueError("Head is not seated in its dock")
                run("UNLOCK\nG4 P1000\nM400")
                # Match stock docking: proximity to the seated head can still
                # trip presence sensors until the unlocked carriage retreats.
                run("G1 Y310 F6000\nM400")
                hall = self.printer.lookup_object("custom_hall").get_status(reactor.monotonic()).get("Raw", 0)
                lock = self.printer.lookup_object("filament_switch_sensor sensor_b").get_status(reactor.monotonic())
                if not isinstance(hall, (int, float)) or not hall >= 4700 or lock.get("filament_detected") is not False:
                    run("SAVE_VARIABLE VARIABLE=fail_tool VALUE=%d\nSAVE_VARIABLE VARIABLE=fail_flag VALUE=-3" % index)
                    raise ValueError("Head coupling did not release after retreat (Hall=%r, sensor_b=%r); inspect the dock before recovery" %
                                     (hall, lock.get("filament_detected")))
                observed({"state": "empty", "head": ""})
            x, y = context["positions"][head]
            phase("Mounting Head %d" % (head + 1))
            run("G1 Y310 F6000\nG1 X%.5f F6000\nG1 Y%.5f F6000\nM400\nLOCK" % (x, y + .4))
            # At the dock the head still trips the dock switch; verify the
            # coupling before leaving, then verify the unique missing head.
            hall = self.printer.lookup_object("custom_hall").get_status(reactor.monotonic()).get("Raw", 0)
            lock = self.printer.lookup_object("filament_switch_sensor sensor_b").get_status(reactor.monotonic())
            if not 3450 <= hall < 4700 or lock.get("filament_detected") is not True:
                raise ValueError("Head coupling did not lock")
            run("G1 Y310 F6000\nG1 Y270 F6000")
        observed({"state": "attached", "head": "h%d" % head})
        heater = "extruder" if head == 0 else "extruder%d" % head
        run("ACTIVATE_EXTRUDER EXTRUDER=%s\nSAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % (heater, head))
        # Off-bed purge in machine coordinates. Restore head-relative offsets
        # without travel after arriving; never restore the previous XY point.
        run("G1 X-13 F6000\nG1 Y80 F6000\nM400")
        offset, reference = context["offsets"][head], context["offsets"][context["probe"]]
        restore_offset = context.get("restore_offset", tuple(a-b for a,b in zip(offset, reference)))
        run("SET_GCODE_OFFSET X=%.5f Y=%.5f Z=%.5f MOVE=0" % tuple(restore_offset))

    def _filament_plan(self, head, action, now, ace_status_cache=None):
        self._require_no_recovery_attempt()
        if action not in ("load", "unload") or type(head) is not int or not 0 <= head <= 3:
            raise ValueError("Invalid filament procedure")
        if self.printer.lookup_object("openace", None) is not None:
            return self._openace_unload_plan(head, action, now, ace_status_cache)
        if self.printer.lookup_object("AFC", None) is not None:
            raise ValueError("AFC owns filament service; use its managed controls")
        pause_origin = None
        if not self._idle_for_filament_settings(now):
            pause_origin = self._paused_filament_origin(head, now)
        key = "h%d" % head
        service = self.printer.lookup_object("wmp_recovery", None) is not None
        context = self._service_context(head, now, allow_homing=True,
            allow_history=not self._material_operation_active("filament_operation"),
            offset_heads=(int(self._pause_origin["head"][1:]),) if pause_origin else ()) if service else None
        if pause_origin:
            origin = self._pause_origin
            allowed = set(origin.get("filament_required", [])) | {origin["head"]}
            if (not service or context["attachment"].get("state") != "attached"
                    or context["attachment"].get("head") not in allowed):
                raise ValueError("Paused service requires a confirmed recovery head mounted")
            original = int(origin["head"][1:])
            context["restore_offset"] = [v + dst - src for v, dst, src in
                zip(origin["offset"], context["offsets"][head], context["offsets"][original])]
            if head != original:
                context["return_head"] = original
                context["return_offset"] = list(origin["offset"])
        if not service and self._attachment(now) != {"state": "attached", "head": key}:
            raise ValueError("Take the selected head first; attachment must be confirmed")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if not service and self.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
            raise ValueError("Active extruder does not match the mounted head")
        profiles, revision = self._profiles()
        if key not in profiles:
            raise ValueError("Configure the external filament first")
        identity = profiles[key]
        if service:
            presence = self._loaded_filament_status(now).get(key, {}).get("state")
            if presence != ("empty" if action == "load" else "loaded"):
                raise ValueError("Filament sensor does not match the requested operation")
        if action == "unload":
            loaded = self._loaded_filament_status(now).get(key, {})
            if loaded.get("state") != "loaded":
                raise ValueError("The head sensor does not report filament")
            identity = loaded["identity"]
        material = identity["material"].upper()
        temperatures = {name.upper(): temp for name, temp in MATERIALS}
        recipe_material = material if material in temperatures else material_family(identity)
        if recipe_material not in temperatures:
            raise ValueError("No supported %s recipe for %s" % (action, identity["material"]))
        # Match the existing shaping classes. Do not derive a physical head
        # from box_modify or use the logical M104/M109 handlers here.
        base = material_family(identity)
        base = {"PCTG": "PETG", "PA6": "PA", "PA12": "PA"}.get(base, base)
        cls = "soft" if base in ("TPU", "TPE") else "petg" if base in ("PETG", "PET") else "abs" if base in ("ABS", "ASA", "HIPS", "WOOD") else "pla"
        target = temperatures[recipe_material] if action == "load" else {"PETG": 235, "PET": 235, "ABS": 280, "ASA": 280, "HIPS": 280, "PA": 280, "PC": 300}.get(base, 250)
        if action == "load" and identity.get("nozzle_temp", 0) > 0:
            target = identity["nozzle_temp"]
        previous_material, transition_note = None, ""
        if action == "load":
            previous_material = self._hotend_material_history().get(key)
            target, transition_note = transition_temperature(identity, previous_material, target)
        minimum, maximum = identity.get("nozzle_temp_min", 0), identity.get("nozzle_temp_max", 0)
        if action == "load" and material in GENERIC_NOZZLE_RANGES:
            minimum, maximum = GENERIC_NOZZLE_RANGES[material]
        if action == "unload":
            # Use the existing shaping class at a spool-supported temperature.
            # Bounds constrain the recipe, not the spool's load target.
            if minimum:
                target = max(target, minimum)
            if maximum:
                target = min(target, maximum)
        if minimum and target < minimum:
            raise ValueError("%s requires %g C; filament minimum is %g C" % (action.capitalize(), target, minimum))
        if maximum and target > maximum:
            raise ValueError("%s requires %g C; filament maximum is %g C" % (action.capitalize(), target, maximum))
        heater = "extruder" if head == 0 else "extruder%d" % head
        state = self.printer.lookup_object(heater).get_status(now)
        config = self.printer.lookup_object("configfile").get_status(now)["settings"][heater]
        maximum_heater_temp = float(config["max_temp"])
        if target > maximum_heater_temp:
            raise ValueError("Recipe requires %g C; %s maximum is %g C" %
                             (target, heater, maximum_heater_temp))
        actual = float(state.get("temperature", float("nan")))
        if not service and (state.get("can_extrude") is not True or state.get("target") != target
                or not math.isfinite(actual) or abs(actual - target) > 5):
            raise ValueError("Heat Head %d to %d C before %s" % (head + 1, target, action))
        if service and action == "load" and self.printer.lookup_object("gcode_macro WIPE_NOZZLE", None) is None:
            raise ValueError("Nozzle wipe macro is unavailable")
        if action == "unload" and self.printer.lookup_object("gcode_macro _TIP_SHAPE_MOVES", None) is None:
            raise ValueError("Tip shaping macro is unavailable")
        plan = {"head": key, "action": action, "source": "external:" + key,
                "session": self.session_id, "identity_revision": revision,
                "identity": identity, "target": target, "class": cls}
        if action == "load":
            # Bind review to nozzle history as well as the editable spool profile.
            plan["previous_material"] = previous_material
            plan["history_error"] = getattr(self, "_hotend_history_error", "")
            if plan["history_error"]:
                transition_note = (transition_note + " " + plan["history_error"]).strip()
            plan["transition_note"] = transition_note
            plan["temperature_description"] = "Load temperature: %g C." % target
            if transition_note:
                plan["temperature_description"] += " " + transition_note
        if pause_origin:
            plan["pause_origin"] = pause_origin
        if action == "load":
            normal_purge = getattr(self, "load_purge_mm", 50.)
            cross_material = cross_family_purge(identity, previous_material)
            purge = getattr(self, "cross_material_purge_mm", normal_purge) if cross_material else normal_purge
            plan.update(feed_mm=getattr(self, "load_feed_mm", 55.), purge_mm=purge,
                        purge_source="cross_material" if cross_material else "same_family")
        if service:
            plan["service"] = context
        plan["command_generation"] = getattr(self, "_command_generation", 0)
        plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        plan["description"] = ("Head %d stays at its current position. " % (head + 1)
            + ("Feed %g mm, then purge %g mm at 400 mm/min. " % (plan["feed_mm"], plan["purge_mm"]) if action == "load" else "Run the existing %s tip-shaping and withdrawal sequence. " % cls.upper())
            + "No homing, docking, XYZ travel or heater changes. Check the filament afterward.")
        if service:
            plan["description"] = (
                ("Home X/Y, then mount" if context["needs_home"] else "Mount")
                + " Head %d, park at the purge position and heat to %d C. " % (head + 1, target)
                + ("Insert filament when prompted; feed %g mm, purge %g mm, then wipe the nozzle." % (plan["feed_mm"], plan["purge_mm"]) if action == "load"
                   else "Shape the filament tip and withdraw it."))
        if transition_note:
            plan["description"] += " " + transition_note
        return plan

    def _openace_idle_status(self, now, ace_status_cache=None):
        stats = self.printer.lookup_object("print_stats").get_status(now)
        pause = self.printer.lookup_object("pause_resume").get_status(now)
        sd = self.printer.lookup_object("virtual_sdcard")
        if (stats.get("state") not in ("standby", "complete", "cancelled")
                or pause.get("is_paused") is not False or sd.is_active() or sd.is_cmd_from_sd()):
            raise ValueError("Use the recovery flow during an active or paused print")
        # One read per status publication; command dispatch passes no cache and
        # therefore always validates against a fresh owner snapshot.
        if ace_status_cache is not None and "status" in ace_status_cache:
            ace = ace_status_cache["status"]
        else:
            ace = self.printer.lookup_object("openace").get_status(now)
            if ace_status_cache is not None:
                ace_status_cache["status"] = ace
        if "job" not in ace or (ace["job"] is not None
                and (not isinstance(ace["job"], dict) or ace["job"].get("active") is not False)):
            raise ValueError("An openACE print map is active or unavailable; use recovery controls")
        if "operation" not in ace or ace["operation"] is not None:
            raise ValueError("Wait for the current openACE operation")
        if type(ace.get("session_id")) is not int or type(ace.get("config_revision")) is not int:
            raise ValueError("openACE session or configuration is unavailable")
        return ace

    def _openace_load_plans(self, head, now, ace_status_cache=None):
        self._require_no_recovery_attempt()
        ace = self._openace_idle_status(now, ace_status_cache)
        key = "h%d" % head
        loaded = ace.get("loaded", {}).get(key, {})
        routes = ace.get("default_tool_map", {})
        managed = any(isinstance(r, dict) and r.get("head") == key and r.get("unit") for r in routes.values())
        if not managed:
            owner_load = copy.deepcopy(loaded)
            loaded = self._sensor_filament_status(now).get(key, {})
            # Presence at the inlet is not a completed load. Let the owning
            # backend prepare/feed an inserted strand when it records empty;
            # never use presence to resolve an unknown or already-loaded head.
            inserted = (isinstance(owner_load, dict) and owner_load.get("state") == "empty"
                        and loaded.get("state") == "loaded")
            if loaded.get("state") != "empty" and not inserted:
                raise ValueError("Head must be empty or contain an inserted, unloaded filament; resolve openACE state before loading")
        elif not isinstance(loaded, dict) or loaded.get("state") != "empty":
            raise ValueError("The head sensor must report empty before loading")
        if not managed:
            identity = copy.deepcopy(ace.get("management", {}).get("identity_settings", {}).get(key, {}).get("values", {}))
            target = identity.get("nozzle_temp", identity.get("temp", 0))
            if type(target) not in (int, float) or not math.isfinite(target) or target <= 0:
                raise ValueError("Set a filament temperature before loading")
            plan = {"owner": "openace", "direct": True, "head": key, "action": "load",
                    "source": "external:" + key, "target": target,
                    "destination": {"head": key, "unit": None, "slot": None},
                    "session": self.session_id, "ace_session": ace["session_id"],
                    "config_revision": ace["config_revision"], "loaded": loaded,
                    "owner_load": owner_load, "identity": identity}
            plan["command_generation"] = getattr(self, "_command_generation", 0)
            plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            plan["description"] = "Mount and heat Head %d. Insert filament when prompted." % (head + 1)
            return [plan]
        plans, sources = [], set()
        routes = ace.get("default_tool_map", {})
        for tool in range(32):
            route = routes.get(str(tool), {})
            if not isinstance(route, dict):
                continue
            unit, slot = route.get("unit"), route.get("slot")
            if (route.get("head") != key or not isinstance(unit, str) or not unit
                    or type(slot) is not int or not 0 <= slot <= 3
                    or str(tool) in ace.get("blocked_tools", {})):
                continue
            if ace.get("devices", {}).get("units", {}).get(unit, {}).get("connected") is not True:
                continue
            source = "%s:%d" % (unit, slot)
            if source in sources:
                continue
            identity = ace.get("inventory", {}).get(source)
            if (not isinstance(identity, dict) or not isinstance(identity.get("material"), str)
                    or not identity["material"] or not isinstance(identity.get("color"), str)):
                continue
            sources.add(source)
            plan = {"owner": "openace", "head": key, "action": "load", "source": source,
                    "tool": tool, "destination": {"head": key, "unit": unit, "slot": slot},
                    "session": self.session_id, "ace_session": ace["session_id"],
                    "config_revision": ace["config_revision"], "loaded": copy.deepcopy(loaded), "identity": copy.deepcopy(identity)}
            plan["command_generation"] = getattr(self, "_command_generation", 0)
            plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            plan["description"] = ("Load %s into Head %d using Tool T%d through openACE. " % (source, head + 1, tool)
                + "This can select/park the head, heat, feed and prime filament. "
                + "The backend owns movement and readiness checks. This does not start or resume a print.")
            plans.append(plan)
        if not plans:
            raise ValueError("No connected ACE slot with a configured filament is available for this head; external loading needs its separate preparation flow")
        return plans

    def _openace_unload_plan(self, head, action, now, ace_status_cache=None):
        if action != "unload":
            raise ValueError("Select a source-specific openACE Load plan")
        ace = self._openace_idle_status(now, ace_status_cache)
        key = "h%d" % head
        loaded = ace.get("loaded", {}).get(key, {})
        if not isinstance(loaded, dict):
            raise ValueError("openACE loaded state is unavailable")
        destination = loaded.get("destination", {})
        direct = isinstance(destination, dict) and destination.get("unit") is None and destination.get("slot") is None
        if direct:
            raise ValueError("This openACE version does not support managed unloading of externally fed filament")
        if (loaded.get("state") != "loaded" or loaded.get("verified") is not True
                or not isinstance(destination, dict) or destination.get("head") != key
                or (not direct and (not isinstance(destination.get("unit"), str) or not destination["unit"]
                or type(destination.get("slot")) is not int or not 0 <= destination["slot"] <= 3))):
            raise ValueError("A verified ACE-loaded source is required for this unload")
        source = "external:" + key if direct else "%s:%d" % (destination["unit"], destination["slot"])
        plan = {"owner": "openace", "head": key, "action": "unload", "source": source,
                "session": self.session_id, "ace_session": ace["session_id"],
                "config_revision": ace["config_revision"], "loaded": copy.deepcopy(loaded)}
        plan["command_generation"] = getattr(self, "_command_generation", 0)
        plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        plan["description"] = ("Unload Head %d from %s through openACE. " % (head + 1, source)
            + "This can select/park the head, heat, shape the tip and retract with ACE assistance. "
            + "This is not a distance-only retract. It does not eject the spool or resume a print.")
        return plan

    def _recovery_attempt_path(self):
        return os.path.join(os.path.dirname(self.profile_path), "wmp_recovery_attempt.json")

    def _restore_recovery_attempt(self):
        path = self._recovery_attempt_path()
        self._recovery_restore_error = ''
        self._recovery_retirement_result = {}
        try:
            store = self._recovery_retirement_store()
            retired = store.retirement()
            if retired is not None:
                self._recovery_retirement_result = dict(retired, state='complete' if retired['matches'] else 'superseded')
                if not retired['matches']:
                    retired = store.retirement(attempt_only=True)
            if retired is not None and retired['matches']:
                self._recovery_attempt = RecoveryAttempt(lambda value: self._write_recovery_json(path, value))
                return
            original = self._recovery_read_bytes(path, 65536)
            record = json.loads(original)
            if not isinstance(record, dict):
                raise ValueError('Invalid recovery attempt journal')
        except FileNotFoundError:
            original, record = None, None
        except (ValueError, OSError) as error:
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self._write_recovery_json(path, value))
            return
        try:
            # Invalid evidence stays untouched for diagnostics. It neither
            # establishes active work nor prevents Klipper startup.
            RecoveryAttempt(lambda value: None, record)
        except (ValueError, TypeError, KeyError) as error:
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self._write_recovery_json(path, value))
            return
        restoring = True
        def persist(value):
            if restoring and original is not None:
                # RecoveryAttempt records interrupted work as unknown on load.
                # Preserve exact pre-restart evidence before that first rewrite.
                self._preserve_recovery_attempt_original(original)
                if self._recovery_read_bytes(path, 65536) != original:
                    raise ValueError("Recovery attempt changed during startup review")
            self._write_recovery_json(path, value)
        try:
            self._recovery_attempt = RecoveryAttempt(persist, record)
        except (ValueError, OSError) as error:
            # Keep the diagnostic failure visible without a machine hold.
            # No archived operation is replayed by startup.
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self._write_recovery_json(path, value))
        restoring = False

    def _preserve_recovery_attempt_original(self, payload):
        """Keep immutable bytes before startup marks an attempt interrupted."""
        digest = hashlib.sha256(payload).hexdigest()
        parent = os.path.dirname(self.profile_path)
        path = os.path.join(parent, "wmp_recovery_attempt_original_" + digest + ".json")
        fd, temporary = tempfile.mkstemp(prefix=".wmp-recovery-attempt-original-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self._recovery_read_bytes(path, 65536) != payload:
                    raise ValueError("Original recovery attempt archive conflicts with saved evidence")
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self._recovery_read_bytes(path, 65536) != payload:
                raise ValueError("Original recovery attempt archive readback differs")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _recovery_attempt_status(self):
        runner = getattr(self, "_recovery_attempt", None)
        return copy.deepcopy(runner.record) if runner is not None and runner.record is not None else {}

    def _recovery_attempt_unresolved(self):
        """Diagnostic history, not standalone machine-operation admission."""
        if getattr(self, '_recovery_restore_error', ''):
            return True
        runner = getattr(self, "_recovery_attempt", None)
        return bool(runner is not None and (runner.busy or
                    runner.record is not None and runner.record["state"] in ("pending", "running", "unknown", "stopped")))

    def _recovery_attempt_active(self):
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return self._recovery_attempt_unresolved()
        runner = getattr(self, "_recovery_attempt", None)
        return bool((runner is not None and runner.busy)
                    or getattr(self, "_recovery_pending_worker", None) is not None)

    def _profile_import_writing(self):
        return (getattr(self, "_profile_import_busy", False)
                and getattr(self, "profile_import", {}).get("action") == "save")

    def _require_no_recovery_attempt(self):
        if self._print_cancel_active():
            raise ValueError("Print cancellation is running; wait for it to stop")
        if self._recovery_attempt_active():
            raise ValueError("Power-loss recovery is running; stop it before another operation")

    def _filament_operation_path(self):
        return os.path.join(os.path.dirname(self.profile_path), "wmp_filament_operation.json")

    def _persist_filament_operation(self):
        # openACE owns its own recovery. Never overwrite a standalone journal
        # with an operation whose outcome is managed by another component.
        if self.printer.lookup_object("openace", None) is not None:
            return
        operation = self.filament_operation
        if not operation.get("id"):
            return
        path = self._filament_operation_path()
        parent = os.path.dirname(path)
        payload = json.dumps({"version": 1, "operation": operation}, sort_keys=True)
        if payload == getattr(self, "_filament_journal_payload", None):
            return
        fd, temporary = tempfile.mkstemp(prefix=".wmp-operation-", dir=parent)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self._filament_journal_payload = payload
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _record_filament_result(self):
        # This journal describes an attempt. In-memory request IDs, generation
        # retirement and current worker ownership—not durable ACKs—prevent replay.
        try:
            self._persist_filament_operation()
        except Exception as error:
            message = str(error)[:512]
            if self.filament_operation.get("persistence_error") != message:
                logging.exception("Unable to persist filament result")
            self.filament_operation["persistence_error"] = message

    def _restore_filament_operation(self):
        path = self._filament_operation_path()
        try:
            with open(path) as stream:
                payload = stream.read(131073)
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as error:
            self.filament_operation = {"state": "unknown", "message": "Saved filament result is unreadable: " + str(error)[:512]}
            return
        try:
            if len(payload) > 131072:
                raise ValueError("journal too large")
            record = json.loads(payload)
            operation = record["operation"]
            if (record.get("version") != 1 or not isinstance(operation, dict)
                    or not isinstance(operation.get("id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", operation["id"])
                    or operation.get("head") not in ("h0", "h1", "h2", "h3")
                    or operation.get("action") not in ("load", "unload")
                    or operation.get("state") not in ("running", "unknown", "complete", "failed", "refused")):
                raise ValueError("invalid operation")
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.filament_operation = {"state": "unknown", "message": "Saved filament result is invalid: " + str(error)[:512]}
            return
        operation["previous_session"] = operation.get("previous_session", operation.get("session", ""))
        operation["session"] = self.session_id
        if operation.get("state") in ("running", "unknown"):
            operation.update(state="unknown", message="Filament operation interrupted by restart; verify stopped state before continuing")
            # The old pause cannot authorize motion or resume in a new process.
            if "pause_origin" in operation:
                operation["interrupted_pause_origin"] = operation.pop("pause_origin")
        self.filament_operation = operation
        self._filament_requests.add(operation["id"])

    def cmd_FILAMENT_SERVICE(self, gcmd):
        # Console/legacy entry point: retain the same admission, operation
        # receipt, cancellation and completion implementation as the screen.
        # T is intentionally unsupported: vendor service macros mixed physical
        # ACTIVATE_EXTRUDER selection with logical M109 addressing.
        if set(gcmd.get_command_parameters()) - {"HEAD", "ACTION", "ID"}:
            raise gcmd.error("Use ACTION=load|unload HEAD=0..3 and optional ID; HEAD is physical, not a mapped T tool")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        if action not in ("load", "unload"):
            raise gcmd.error("ACTION must be load or unload")
        sd = self.printer.lookup_object("virtual_sdcard", None)
        if sd is None or sd.is_cmd_from_sd():
            raise gcmd.error("Use Filaments for managed service; this asynchronous command cannot run from print G-code")
        request_id = gcmd.get("ID", "service-" + uuid.uuid4().hex)
        try:
            now = self.printer.get_reactor().monotonic()
            if action == "load" and self.printer.lookup_object("openace", None) is not None:
                plans = [p for p in self._openace_load_plans(head, now)
                         if p.get("direct") and p.get("source") == "external:h%d" % head]
                if len(plans) != 1:
                    raise ValueError("Select an ACE slot in Filaments to load this head")
                plan = plans[0]
            else:
                plan = self._filament_plan(head, action, now)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            raise gcmd.error(str(error))
        arguments = {"HEAD": str(head), "ACTION": action, "ID": request_id,
                     "TOKEN": plan["token"]}
        if (gcmd.get("ID", None) is None
                and self.printer.lookup_object("openace", None) is None
                and self.printer.lookup_object("AFC", None) is None):
            sequence = getattr(self, "_filament_request_sequence", 0) + 1
            request_id = "filament_" + str(sequence)
            arguments.update(ID=request_id, SESSION=self.session_id, SEQUENCE=str(sequence))
        command = self.printer.lookup_object("gcode").create_gcode_command(
            "WMP_FILAMENT_SEQUENCE", "WMP_FILAMENT_SEQUENCE", arguments)
        self.cmd_FILAMENT_SEQUENCE(command)
        gcmd.respond_info("Filament operation %s: %s" %
                          (request_id, self.filament_operation.get("state", "unknown")))

    def cmd_FILAMENT_SEQUENCE(self, gcmd):
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid filament request ID")
        sequenced = self._admit_material_sequence(gcmd, "filament", request_id)
        if self._material_operation_active("toolhead_operation"):
            raise gcmd.error("Toolhead operation is unresolved: state=" + str(getattr(self, "toolhead_operation", {}).get("state"))[:80])
        if self.filament_operation.get("state") == "running":
            raise gcmd.error("A filament operation is already running: filament_operation.state=running")
        if not sequenced and request_id in self._filament_requests:
            raise gcmd.error("Filament request already attempted; inspect its result")
        if self.filament_operation.get("state") == "unknown" and (
                self.printer.lookup_object("openace", None) is not None
                and getattr(self, "_openace_filament_recovery", None) is not None):
            raise gcmd.error("Previous filament operation is unresolved")
        if not sequenced and len(self._filament_requests) >= 1024:
            raise gcmd.error("Legacy filament request limit reached; use the current touchscreen or WMP_FILAMENT_SERVICE without ID")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        try:
            now = self.printer.get_reactor().monotonic()
            if action == "load" and self.printer.lookup_object("openace", None) is not None:
                plans = self._openace_load_plans(head, now)
                plan = next((p for p in plans if p["token"] == gcmd.get("TOKEN")), None)
                if plan is None:
                    raise ValueError("Selected ACE Load procedure changed; review it again")
            else:
                plan = self._filament_plan(head, action, now)
            if gcmd.get("TOKEN") != plan["token"]:
                raise ValueError("Filament procedure changed; review it again")
            self._begin_explicit_physical_action("filament " + action)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            if not sequenced:
                self._filament_requests.add(request_id)
            self.filament_operation = {"id": request_id, "session": self.session_id,
                "head": "h%d" % head, "action": action, "state": "refused",
                "message": str(error)}
            raise gcmd.error(str(error))
        if not sequenced:
            self._filament_requests.add(request_id)
        self._filament_checks.pop(plan["head"], None)
        self.filament_operation = {"id": request_id, "session": self.session_id,
            "head": plan["head"], "action": action, "state": "running",
            "command_generation": plan["command_generation"]}
        if plan.get("pause_origin"):
            self.filament_operation["pause_origin"] = plan["pause_origin"]
        self._record_filament_result()
        if "service" in plan or plan.get("owner") == "openace":
            # Return the command receipt before long waits, so the screen's
            # status worker keeps polling live preparation/insertion progress.
            scheduling_failed = False
            def execute(now):
                if scheduling_failed:
                    return
                dispatched = False
                try:
                    with self.printer.lookup_object("gcode").get_mutex():
                        now = self.printer.get_reactor().monotonic()
                        if not self._filament_context_valid(plan, now):
                            raise ValueError("Printer became busy before loading: " + getattr(self, "_filament_context_refusal", "context admission was not confirmed"))
                        if plan.get("owner") == "openace" and action == "load":
                            current = next((p for p in self._openace_load_plans(head, now) if p["token"] == plan["token"]), None)
                        else:
                            current = self._filament_plan(head, action, now)
                        if current != plan:
                            raise ValueError("Filament service context changed")
                        dispatched = True
                        self._execute_filament(gcmd, head, action, plan)
                except Exception as error:
                    if self.filament_operation.get("state") == "running":
                        self.filament_operation.update(state="failed" if dispatched else "refused", message=str(error))
                        self._record_filament_result()
            try:
                self.printer.get_reactor().register_callback(execute)
            except Exception as error:
                # A callback can be enqueued before registration raises. It
                # must never execute after we have reported that nothing ran.
                scheduling_failed = True
                self.filament_operation.update(state="refused", message=str(error))
                self._record_filament_result()
                raise
            return
        self._execute_filament(gcmd, head, action, plan)

    def _config_save_routes_ready(self):
        """Admit persistent writes before the vendor writer, not its restart.

        Both touchscreen and remote G-code enter these handlers. Keep the
        original writer and other-owner policy; no pending setting is changed
        or discarded when standalone admission refuses.
        """
        if getattr(self, "_config_save_handlers", None) is not None:
            return
        gcode = self.printer.lookup_object("gcode")
        originals = {}
        for name in ("SAVE_CONFIG", "SAVE_CONFIG_NO_RESTART"):
            original = gcode.register_command(name, None)
            if original is not None:
                originals[name] = original
        if "SAVE_CONFIG" not in originals:
            for name, original in originals.items():
                gcode.register_command(name, original)
            raise self.printer.config_error("Managed configuration requires SAVE_CONFIG")
        def wrap(name, original):
            def save(gcmd):
                if (self.printer.lookup_object("openace", None) is None
                        and self.printer.lookup_object("AFC", None) is None):
                    if self.printer.is_shutdown():
                        raise gcmd.error("Configuration save stopped: printer is shutdown")
                    if getattr(gcode, "quick_stop_flag", False):
                        raise gcmd.error("Configuration save stopped: gcode.quick_stop_flag is set")
                    # An explicit no-restart command expresses whole-set save
                    # intent. It is not a restart. START_PRINT uses the scoped
                    # mesh command below instead of this general writer.
                    if name == "SAVE_CONFIG":
                        self._restart_requested(None)
                return original(gcmd)
            return save
        for name, original in originals.items():
            gcode.register_command(name, wrap(name, original))
        self._config_save_handlers = originals

    def cmd_SAVE_PRINT_MESH(self, gcmd):
        """Optional print recovery persistence; never save unrelated edits."""
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            return self._config_save_handlers["SAVE_CONFIG_NO_RESTART"](gcmd)
        self._print_mesh_persisted = False
        try:
            now = self.printer.get_reactor().monotonic()
            config = self.printer.lookup_object("configfile")
            mesh = self.printer.lookup_object("bed_mesh").get_status(now)
            reason = self._mesh_pending_reason(mesh, config.status_save_pending)
            if reason:
                raise ValueError(reason)
            self._publish_print_mesh(config)
            self._print_mesh_persisted = True
        except (OSError, ValueError, AttributeError, KeyError, TypeError, configparser.Error,
                self.printer.command_error) as error:
            self._print_recovery_error = "Print mesh was not persisted: " + str(error)[:384]
            gcmd.respond_info(self._print_recovery_error +
                              ". Printing can continue; power-loss recovery is unavailable for this job.")

    def _publish_print_mesh(self, config):
        """Retained config serialization with a single atomic replacement.

        Only called with mesh-only pending settings under the G-code mutex.
        Unlike the vendor two-rename writer, a failed publication cannot leave
        printer.cfg absent. In-memory pending settings are not modified.
        """
        path = self.printer.get_start_args()["config_file"]
        if os.path.islink(path):
            raise ValueError("Mesh save cannot replace a linked printer configuration")
        original = config._read_config_file(path)
        regular, old_autosave = config._find_autosave_data(original)
        config._build_config_wrapper(regular, path)
        regular = config._strip_duplicates(regular, config.autosave)
        config._disallow_include_conflicts(regular, path, self.printer.lookup_object("gcode"))
        # Preserve the retained writer's header rather than inventing a second
        # config format. It is defined in the writer's module globals.
        header = config.cmd_SAVE_CONFIG_NO_RESTART.__func__.__globals__["AUTOSAVE_HEADER"]
        lines = [("#*# " + line).strip()
                 for line in config._build_config_string(config.autosave).split("\n")]
        payload = (regular.rstrip() + "\n" + header.rstrip() + "\n"
                   + "\n".join(lines) + "\n").encode("utf-8")
        directory = os.path.dirname(os.path.abspath(path))
        metadata = os.stat(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-print-mesh-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if config._read_config_file(path) != original:
                raise ValueError("Printer configuration changed during mesh save")
            # Retain a backup before publication; failure leaves the original
            # untouched. A unique name avoids overwriting another save's backup.
            backup_fd, backup = tempfile.mkstemp(prefix="printer-mesh-", suffix=".cfg", dir=directory)
            with os.fdopen(backup_fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                stream.write(original.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _mesh_pending_reason(self, mesh, items):
        if mesh.get("profile_name") != "wmp_print":
            return "active mesh is %r; expected 'wmp_print'" % mesh.get("profile_name")
        if set(items) != {"bed_mesh wmp_print"}:
            sections = ", ".join(sorted(str(key) for key in items))[:256]
            return "pending config sections are [%s]; expected only [bed_mesh wmp_print]" % sections
        if not isinstance(items["bed_mesh wmp_print"], dict):
            return "pending [bed_mesh wmp_print] settings are not a dictionary"
        if not items["bed_mesh wmp_print"]:
            return "pending [bed_mesh wmp_print] settings are empty"
        return ""

    def _stock_startup_file(self):
        """Read-only binding for a stock SD START_PRINT, never a remote save."""
        now = self.printer.get_reactor().monotonic()
        sd = self.printer.lookup_object("virtual_sdcard")
        stream = getattr(sd, "current_file", None)
        prefix = "Stock startup mesh save requires the active SD startup: "
        if self.printer.lookup_object("openace", None) is not None:
            raise ValueError(prefix + "openACE owns the printer")
        if self.printer.lookup_object("AFC", None) is not None:
            raise ValueError(prefix + "AFC owns the printer")
        if sd.is_active() is not True:
            raise ValueError(prefix + "virtual_sdcard.is_active is not True")
        if sd.is_cmd_from_sd() is not True:
            raise ValueError(prefix + "command is not executing from virtual SD")
        state = self.printer.lookup_object("print_stats").get_status(now).get("state")
        if state != "printing":
            raise ValueError(prefix + "print_stats.state=%r; expected 'printing'" % state)
        paused = self.printer.lookup_object("pause_resume").get_status(now).get("is_paused")
        if paused is not False:
            raise ValueError(prefix + "pause_resume.is_paused=%r; expected False" % paused)
        ready = self.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready")
        if ready is not False:
            raise ValueError(prefix + "START_PRINT.print_body_ready=%r; expected False" % ready)
        if stream is None:
            raise ValueError(prefix + "no open SD file")
        if stream.closed:
            raise ValueError(prefix + "SD file is closed")
        path = os.path.realpath(stream.name)
        positions = tuple(getattr(sd, name, None) for name in ("file_position", "next_file_position"))
        if any(type(value) is not int or value < 0 for value in positions):
            raise ValueError("Stock startup SD command position unavailable: file_position=%r, next_file_position=%r" % positions)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        opened, current = identity(os.fstat(stream.fileno())), identity(os.stat(path))
        if opened != current:
            changed = [name for name, before, after in zip(
                ("device", "inode", "size", "mtime_ns"), opened, current) if before != after]
            raise ValueError("Stock startup file changed: " + ", ".join(changed))
        return {"session": self.session_id, "stream": stream, "path": path,
                "identity": opened, "positions": positions,
                "generation": getattr(self, "_command_generation", 0)}

    def _restart_requested(self, print_time, probe_editor=None):
        """Reject a Ready-state restart before the vendor drain/exit sequence.

        The vendor dispatch calls this under its command mutex. System-service
        restarts bypass it; not-ready recovery keeps the vendor's explicit
        restart route. No journal is cleared and no operation is replayed here.
        """
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            return
        try:
            now = self.printer.get_reactor().monotonic()
            stats = self.printer.lookup_object("print_stats").get_status(now)
            pause = self.printer.lookup_object("pause_resume").get_status(now)
            sd = self.printer.lookup_object("virtual_sdcard")
            current_file = getattr(sd, "current_file", None)
            if stats.get("state") not in ("standby", "complete", "cancelled", "error"):
                raise ValueError("Finish or cancel the print before restarting: print_stats.state=%r" % stats.get("state"))
            if pause.get("is_paused") is not False:
                raise ValueError("Finish or cancel the print before restarting: pause_resume.is_paused=%r" % pause.get("is_paused"))
            if sd.is_active() is not False:
                raise ValueError("Finish or cancel the print before restarting: virtual SD worker is active")
            if sd.is_cmd_from_sd() is not False:
                raise ValueError("Finish or cancel the print before restarting: command is executing from virtual SD")
            if self._print_cancel_active():
                raise ValueError("Resolve the managed cancellation result before restarting")
            if self._recovery_attempt_active():
                raise ValueError("Resolve the managed recovery result before restarting")
            for name in ("filament_operation", "toolhead_operation"):
                state = getattr(self, name, {}).get("state")
                if self._material_operation_active(name):
                    raise ValueError("Stop and resolve the filament/tool operation before restarting: %s.state=%s" % (name, state))
            if getattr(self, "_pending_recovery_submission", None):
                raise ValueError("Wait for the managed operation before restarting: print submission is pending")
            if (getattr(self, "_profile_import_busy", False)
                    and getattr(self, "profile_import", {}).get("action") == "save"):
                raise ValueError("Wait for the managed operation before restarting: profile import save is writing settings")
            recovery = self.printer.lookup_object("wmp_recovery", None)
            calibration_status = recovery.get_status(now) if recovery is not None else {}
            if recovery is not None and calibration_status.get("calibration_active") is not False:
                calibration = getattr(recovery, 'calibration', None)
                # SAVE_CONFIG was admitted before writing. Permit its own
                # synchronous restart only; other active stages remain held.
                editor_admission = (probe_editor is not None
                    and getattr(calibration, 'probe_editor', None) is probe_editor
                    and getattr(calibration, 'active', True) is False)
                if not editor_admission and not (getattr(calibration, 'active', False) is True
                        and getattr(calibration, '_saving', False) is True
                        and getattr(calibration, 'failure', None) == ''):
                    raise ValueError("Finish or stop calibration before restarting: calibration_active=%r, command_active=%r, saving=%r, failure=%r" % (
                        calibration_status.get("calibration_active"), getattr(calibration, 'active', None),
                        getattr(calibration, '_saving', None), str(getattr(calibration, 'failure', None))[:160]))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            # Keep the existing explicit emergency-stop/restart route reachable
            # when readiness cannot be established. This is guidance, not an
            # automatic shutdown or a new way around current-operation checks.
            raise self.printer.command_error(
                "Restart not admitted: " + str(error)
                + ". To deliberately stop the printer, send M112, then send "
                "FIRMWARE_RESTART separately. This interrupts any work and "
                "requires rehoming.")

    def cmd_SCREEN_RESUME_PREHEAT(self, gcmd):
        """Retire only the stock screen preheat prefix of an owned tool retry.

        Ordinary pauses/runout keep the stock command bytes and temperatures.
        Manual M104/M109 do not enter this command. No UI freshness observation
        decides whether an old screen temperature may overwrite captured targets.
        """
        try:
            encoded = gcmd.get("COMMAND_HEX")
            if not isinstance(encoded, str) or len(encoded) > 1024:
                raise ValueError("COMMAND_HEX exceeds the 512-byte command limit")
            command = bytes.fromhex(encoded).decode("ascii")
            if not re.fullmatch(r"(?:M104|M109) T[0-3] S[0-9]+|SET_GCODE_VARIABLE MACRO=RESUME VARIABLE=resume_temperature[0-3] VALUE=[0-9]+", command):
                raise ValueError("expected one stock M104/M109 T0..3 S<integer> or RESUME resume_temperature0..3 write; received %r" % command)
        except (ValueError, UnicodeError) as error:
            raise gcmd.error("Screen Resume preheat rejected: %s" % error) from error
        if (not any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))
                and self._toolchange_pause_status()):
            logging.info("Screen Resume preheat omitted for managed tool-change retry; captured job targets own Resume: %s", command)
            return
        send = lambda: self.printer.lookup_object("gcode").run_script_from_command(command)
        if command.startswith("M109 "):
            return self._observe_resume(send, phase="preheating")
        return send()

    def cmd_TOOLCHANGE_FAULT(self, gcmd):
        """Typed coupling failure; only the outer SD boundary may retain a job."""
        now = self.printer.get_reactor().monotonic()
        saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        stage = gcmd.get("STAGE", None)
        if stage in ("begin", "return"):
            required, maximum = gcmd.get_float("REQUIRED"), gcmd.get_float("MAXIMUM")
            message = ("Insufficient Z travel for toolchange clearance: required Z=%.3f must be below axis_maximum.z=%.3f."
                       if stage == "begin" else "Insufficient Z travel for print return: required Z=%.3f exceeds axis_maximum.z=%.3f.") % (required, maximum)
            error = gcmd.error(message)
            error.wmp_toolchange_clearance = stage
            raise error
        code = saved.get("fail_flag", 0)
        reason = gcmd.get("REASON", "toolchange")
        message = "Tool change failed: fail_flag=%s, reason=%s. Inspect the head before retrying" % (code, reason)
        if reason == "release_sensors":
            hall = self.printer.lookup_object("custom_hall").get_status(now)
            sensor = self.printer.lookup_object("filament_switch_sensor sensor_b").get_status(now)
            message += "; custom_hall.Raw=%r (expected >=4700), sensor_b=%r (expected False)" % (hall.get("Raw"), sensor.get("filament_detected"))
        elif reason == "dock_sensor":
            message += "; docked%s.filament_detected=False (expected True before unlocking)" % gcmd.get("T", "?")
        error = gcmd.error(message)
        error.wmp_toolchange_fault = (code, reason)
        raise error

    def _fault_pause_context(self, now, allow_filament=False, allow_toolhead=False):
        """Current stopped SD ownership, never a historical failure receipt."""
        record = getattr(self, "_toolchange_pause", None)
        if not record or record.get("state") not in ("paused", "ready"):
            raise ValueError("No stopped tool-change retry")
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            raise ValueError("Another manager owns paused tool repair")
        self._require_no_recovery_attempt()
        sd = self.printer.lookup_object("virtual_sdcard")
        pause = self.printer.lookup_object("pause_resume")
        position = record["end"] if record["state"] == "ready" else record["start"]
        if (record["session"] != self.session_id or sd.current_file is not record["handle"]
                or record["handle"].closed or sd.file_position != position or sd.is_active()
                or sd.is_cmd_from_sd() or not pause.is_paused
                or self.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"):
            raise ValueError("Wait for the same print to finish pausing")
        if (self._print_cancel_active() or self.printer.is_shutdown()
                or self.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise ValueError("Paused repair needs valid XYZ reference and no cancellation")
        saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        if [saved.get("box_modify_t%d" % i) for i in range(4)] != record["mapping"]:
            raise ValueError("Tool mapping changed during the paused print")
        if not allow_filament and self._material_operation_active("filament_operation"):
            raise ValueError("Wait for the running filament operation")
        if not allow_toolhead and self._material_operation_active("toolhead_operation"):
            raise ValueError("Wait for the running toolhead operation")
        return record

    def _fault_manual_toolhead(self, now):
        try:
            self._fault_pause_context(now)
            if self._attachment(now).get("state") not in ("attached", "empty"):
                raise ValueError("Head attachment sensors disagree; inspect the head")
            if self._identification_pending(now):
                raise ValueError("Wait for head identification")
            return True, ""
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return False, str(error)

    def _fault_service_origin(self, now):
        """Observe a real mounted head without parking or inventing PAUSE states.

        This caches only UI/service binding data. Original print coordinates and
        E remain in the independent fault record, never in a manufactured stock
        PAUSE/PAUSEPARK entry. An actual service keeps its origin across yields.
        """
        record = self._fault_pause_context(now, allow_filament=True)
        origin = getattr(self, "_pause_origin", None)
        same = origin and origin.get("kind") == "toolchange" and origin.get("fault") is record
        if same and self._material_operation_active("filament_operation"):
            return origin
        attachment = self._attachment(now)
        head = attachment.get("head", "")
        if attachment.get("state") != "attached" or head not in ("h0", "h1", "h2", "h3"):
            raise ValueError("Mount a head before paused filament service")
        heater = "extruder" if head == "h0" else "extruder" + head[1:]
        if self.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
            raise ValueError("Mounted head and active extruder disagree")
        if same and origin["head"] == head:
            origin["position"] = record["end"] if record["state"] == "ready" else record["start"]
            return origin
        offset = list(self.printer.lookup_object("gcode_move").get_status(now)["homing_origin"])[:3]
        if len(offset) != 3 or any(type(v) not in (float, int) or not math.isfinite(v) for v in offset):
            raise ValueError("Paused head offset is unavailable")
        origin = {"kind": "toolchange", "fault": record, "id": uuid.uuid4().hex,
                  "session": self.session_id, "file": record["handle"], "head": head,
                  "position": record["end"] if record["state"] == "ready" else record["start"],
                  "offset": offset, "filament_required": sorted(record.get("service_required", set()))}
        self._pause_origin = origin
        return origin

    def _check_fault_service_complete(self, record, now):
        self._fault_pause_context(now)
        required = set(record.get("service_required", set())) | self._job_filament_losses(record["handle"])
        if required:
            loaded = self._loaded_filament_status(now)
            for head in sorted(required):
                if loaded.get(head, {}).get("state") != "loaded":
                    raise ValueError("Load or check filament in Head %d before resuming" % (int(head[1:]) + 1))

    def _toolchange_pause_status(self):
        record = getattr(self, "_toolchange_pause", None)
        if not record:
            return {}
        sd = self.printer.lookup_object("virtual_sdcard", None)
        if (record["session"] != self.session_id or sd is None
                or sd.current_file is not record["handle"] or record["handle"].closed):
            return {}
        available, reason = self._fault_manual_toolhead(self.printer.get_reactor().monotonic())
        return {"state": record["state"], "message": record["message"],
                "manual_toolhead_available": available, "manual_toolhead_reason": reason,
                "target_head": "h%d" % record["target"], "retry_available": record["state"] in ("paused", "ready")}

    def _capture_toolchange_pause(self, boundary, commands, error):
        fault = getattr(error, "wmp_toolchange_fault", None)
        stage = getattr(error, "wmp_toolchange_clearance", None)
        if ((stage not in ("begin", "return") and (not fault or fault[0] not in (-1, -2, -3, -4, -5))) or boundary is None
                or len(commands) != 1 or not re.fullmatch(r"T[0-3]", commands[0])):
            return False
        sd, handle, start, end, session = boundary
        now = self.printer.get_reactor().monotonic()
        gcode = self.printer.lookup_object("gcode")
        if (self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False)
                or self._print_cancel_active() or session != self.session_id
                or sd.current_file is not handle or handle.closed
                or self.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                or not self.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready")
                or self.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            return False
        context = copy.deepcopy(self.printer.lookup_object("gcode_macro _WMP_TOOL_RETURN_BEGIN").get_status(now))
        if stage == "begin":
            gm = self.printer.lookup_object("gcode_move").get_status(now)
            th = self.printer.lookup_object("toolhead").get_status(now)
            context.update(pending=1, success=0, position=list(gm["gcode_position"])[:3],
                           acceleration=th["max_accel"], feedrate=gm["speed"], override=gm["speed_factor"],
                           absolute=gm["absolute_coordinates"], absolute_e=gm["absolute_extrude"])
        elif not context.get("pending"):
            return False
        saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        target = saved.get("box_modify_t" + commands[0][1])
        if type(target) is not int or target not in range(4):
            return False
        temperatures = {}
        for name in ("heater_bed", "extruder", "extruder1", "extruder2", "extruder3"):
            heater = self.printer.lookup_object(name, None)
            if heater is not None:
                temperature = heater.get_status(now).get("target")
                if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
                    return False
                temperatures[name] = temperature
        gm = self.printer.lookup_object("gcode_move").get_status(now)
        logical_e = gm["gcode_position"][3]
        active_extruder = self.printer.lookup_object("toolhead").get_status(now).get("extruder")
        target_extruder = "extruder" if target == 0 else "extruder%d" % target
        # Match uninterrupted retained CHECK success: M221 preserves logical E,
        # then an actual ACTIVATE resets E to zero and factor to one. Same-head
        # activation is a no-op. A return fault is already past those effects.
        completed_activation = stage == "return" or context.get("success") == 1
        factor = gm.get("extrude_factor") if completed_activation else (
            1. if active_extruder != target_extruder else saved.get("t%d_flow_extruder" % target))
        if not completed_activation and active_extruder == target_extruder and type(factor) in (int, float):
            factor /= 100.
        mapping = [saved.get("box_modify_t%d" % i) for i in range(4)]
        if (type(logical_e) not in (int, float) or not math.isfinite(logical_e)
                or active_extruder not in ("extruder", "extruder1", "extruder2", "extruder3")
                or type(factor) not in (int, float) or not math.isfinite(factor) or factor <= 0
                or any(type(head) is not int or head not in range(4) for head in mapping)):
            gcode.respond_info("Cannot retain tool-change retry: active extruder, target saved flow or extrusion coordinate is invalid. Correct the reported printer configuration before retrying.")
            return False
        expected_e = logical_e if completed_activation or active_extruder == target_extruder else 0.
        pause = self.printer.lookup_object("pause_resume")
        self._pause_origin = None
        self._toolchange_pause = {"logical_e": expected_e, "extrude_factor": factor,
            "active_extruder": active_extruder, "captured_logical_e": logical_e,
            "mapping": mapping, "service_required": set(),"state": "paused", "message": str(error), "session": session,
            "handle": handle, "start": start, "end": end, "target": target,
            "logical": commands[0], "context": context, "temperatures": temperatures,
            "stage": stage or "coupling", "wipe_complete": stage == "return",
            "lift": copy.deepcopy(self.printer.lookup_object("gcode_macro _descend_z").get_status(now))}
        if stage == "begin":
            self._toolchange_pause["lift"]["need_descend"] = 0
        # No PAUSE macro: it parks/retracts, which is not justified at a faulted dock.
        # Returning normally lets the retained worker note_pause instead of note_error.
        sd.must_pause_work = True
        sd.next_file_position = start
        pause.is_paused = pause.sd_paused = pause.pause_command_sent = True
        instruction = ("Resolve the clearance condition, then Resume to retry the pending stage."
                       if stage else "Correct the head problem, then Resume to retry the tool change.")
        gcode.respond_info("Print paused: %s. %s" % (error, instruction))
        return True

    def _retry_paused_toolchange(self, gcmd):
        record = getattr(self, "_toolchange_pause", None)
        if not self._toolchange_pause_status():
            self._toolchange_pause = None
            if getattr(self, "_pause_origin", None) and self._pause_origin.get("kind") == "toolchange":
                self._pause_origin = None
            return False
        sd = self.printer.lookup_object("virtual_sdcard")
        pause = self.printer.lookup_object("pause_resume")
        gcode = self.printer.lookup_object("gcode")
        now = self.printer.get_reactor().monotonic()
        if (any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))
                or record["state"] not in ("paused", "ready") or sd.is_active() or sd.is_cmd_from_sd()
                or sd.file_position != record["end" if record["state"] == "ready" else "start"] or not pause.is_paused
                or self.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                or self.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise gcmd.error("Tool change retry needs the stopped paused job with homed XYZ; no movement started")
        saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        if saved.get("box_modify_t" + record["logical"][1]) != record["target"]:
            raise gcmd.error("Tool mapping changed during the pause; restore the selected mapping before Resume")
        try:
            self._check_fault_service_complete(record, now)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error("Print remains paused: " + str(error))
        if record["state"] == "ready":
            return self._resume_completed_toolchange(gcmd, record)
        stage = record.get("stage", "coupling")
        starting = stage == "begin"
        try:
            if stage == "begin":
                # Recheck current physical clearance after inspection; restore
                # the separately retained print origin below, never the jog.
                gcode.run_script_from_command("_WMP_TOOL_RETURN_BEGIN T=%d RESUMING=1" % record["target"])
                stage = "coupling"
            self._begin_explicit_physical_action("print tool change retry")
            attachment = self._attachment(self.printer.get_reactor().monotonic())
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("Current attachment is uncertain; inspect the head before Resume")
            current = int(attachment["head"][1]) if attachment["state"] == "attached" else 99
            if stage == "return" and current != record["target"]:
                raise ValueError("Mount the completed toolchange head before retrying its print return")
            record["state"] = "retrying"
            # Like explicit Take/Dock, select the physical current head from
            # present sensors, not stale bookkeeping left halfway through pickup.
            gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % current)
            for key, value in record["context"].items():
                gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=_WMP_TOOL_RETURN_BEGIN VARIABLE=%s VALUE='%s'" % (key, repr(value)))
            for key, value in record["lift"].items():
                gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=_descend_z VARIABLE=%s VALUE='%s'" % (key, repr(value)))
            target = record["target"]
            generation = getattr(self, "_command_generation", 0)
            retry_script = "".join("SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.17g\n" % (name, temperature)
                                   for name, temperature in record["temperatures"].items())
            bed = record["temperatures"].get("heater_bed", 0)
            if bed > 0:
                retry_script += "TEMPERATURE_WAIT SENSOR=heater_bed MINIMUM=%.17g\n" % (bed - 2.5)
            if starting:
                # BEGIN failed before _CHANGE_TOOL's first bookkeeping line.
                # Complete that original prefix before checks/coupling, once.
                retry_script += ("SAVE_VARIABLE VARIABLE=fail_flag VALUE=0\n"
                                 "SAVE_VARIABLE VARIABLE=fail_tool VALUE=%d\n"
                                 "SAVE_VARIABLE VARIABLE=changing_tool VALUE=0\n"
                                 "SAVE_VARIABLE VARIABLE=current_extruder_backup VALUE=%d\n" % (current, target))
            if stage != "return":
                retry_script += ("SET_GCODE_VARIABLE MACRO=_CHECK_CHANGE_TOOL VARIABLE=retry VALUE=0\n"
                "_check_current_extruder_value\n_check_hall_sensor\n_check_tool_exist T=%d\n"
                "_CHANGING_TOOL T=%d\n_CHECK_CHANGE_TOOL T=%d SKIP_WIPE=1\n_CHECK_CHANGE_TOOL_AGAIN T=%d\n" % (target, target, target, target))
            if stage == "return":
                retry_script += "_WAIT_TOOL_TEMPERATURE\n"
            if stage != "return" and not record.get("wipe_complete"):
                retry_script += "WIPE_NOZZLE\n"
            retry_script += ("_WMP_TOOL_RETURN_FINISH RESUMING=1\nSAVE_VARIABLE VARIABLE=changing_tool VALUE=0\n"
                "SET_GCODE_VARIABLE MACRO=_CHANGE_TOOL VARIABLE=save_position VALUE=1\nM400")
            for line in retry_script.split("\n"):
                if (getattr(self, "_command_generation", 0) != generation or self._print_cancel_active()
                        or self.printer.is_shutdown() or sd.current_file is not record["handle"]):
                    raise ValueError("Tool change retry interrupted; no print continuation was started")
                if line.startswith("_CHANGING_TOOL"):
                    record["stage"] = "coupling"
                gcode.run_script_from_command(line)
                if line == "WIPE_NOZZLE":
                    record["wipe_complete"] = True
                if line.startswith("_WMP_TOOL_RETURN_FINISH"):
                    record["stage"] = "return"
                    record["context"]["success"] = 1
            if (self.printer.is_shutdown() or sd.current_file is not record["handle"]
                    or sd.file_position != record["start"] or self._print_cancel_active()
                    or self._attachment(self.printer.get_reactor().monotonic()) != {"state": "attached", "head": "h%d" % target}):
                raise ValueError("Tool change retry completion could not be confirmed")
        except Exception as error:
            failed_stage = getattr(error, "wmp_toolchange_clearance", None)
            if failed_stage == "return":
                record["stage"] = "return"
                record["context"]["success"] = 1
                record["wipe_complete"] = True
            record.update(state="paused", message=str(error))
            raise gcmd.error("Print remains paused: %s. Correct the problem, then Resume to retry." % error) from error
        # Physical completion and worker scheduling are separate checkpoints.
        # A scheduling failure must not replay docking, heating or wiping.
        sd.file_position = sd.next_file_position = record["end"]
        record.update(state="ready", return_position=list(self.printer.lookup_object("gcode_move").get_status(
            self.printer.get_reactor().monotonic())["gcode_position"])[:3])
        return self._resume_completed_toolchange(gcmd, record)

    def _resume_completed_toolchange(self, gcmd, record):
        sd = self.printer.lookup_object("virtual_sdcard")
        pause = self.printer.lookup_object("pause_resume")
        now = self.printer.get_reactor().monotonic()
        position = list(self.printer.lookup_object("gcode_move").get_status(now)["gcode_position"])[:3]
        if (self._attachment(now) != {"state": "attached", "head": "h%d" % record["target"]}
                or any(abs(a-b) > .00001 for a, b in zip(position, record["return_position"]))):
            # An intervening manual change requires a fresh explicit retry,
            # not a permanent completion latch or a blind worker release.
            record["state"] = "paused"
            sd.file_position = sd.next_file_position = record["start"]
            raise gcmd.error("Print remains paused: attachment or print return position changed. Resume again to recheck the head and restore the print position")
        gm = self.printer.lookup_object("gcode_move").get_status(now)
        run = self.printer.lookup_object("gcode").run_script_from_command
        if gm["extrude_factor"] != record["extrude_factor"]:
            run("M221 S%.17g" % (record["extrude_factor"] * 100.))
        if gm["gcode_position"][3] != record["logical_e"]:
            run("G92 E%.17g" % record["logical_e"])
        self._toolchange_pause = None
        try:
            sd.do_resume()
        except Exception as error:
            self._toolchange_pause = record
            record["message"] = "Tool change complete, but print could not resume: %s. Resume to try again." % error
            raise gcmd.error(record["message"]) from error
        pause.is_paused = pause.sd_paused = pause.pause_command_sent = False
        origin = getattr(self, "_pause_origin", None)
        if origin and origin.get("kind") == "toolchange" and origin.get("fault") is record:
            self._pause_origin = None
        return True

    def _cancel_routes_ready(self):
        """Admit legacy script/API Cancel before run_script acquires its mutex.

        Nested Cancel binds the current job without waiting for its own mutex,
        then unwinds the enclosing command tails. Direct SD and HTTP scripts use
        the same intent and deferred command-owned cleanup.
        """
        gcode = self.printer.lookup_object("gcode")
        if getattr(self, "_cancel_script_wrapper", None) is not None:
            return
        original_script = gcode.run_script
        gcode.register_command("_WMP_TOOLCHANGE_FAULT", self.cmd_TOOLCHANGE_FAULT)
        gcode.register_command("_WMP_SCREEN_RESUME_PREHEAT", self.cmd_SCREEN_RESUME_PREHEAT)
        sd = self.printer.lookup_object("virtual_sdcard", None)
        if sd is not None and callable(getattr(sd, "do_resume", None)):
            original_sd_resume = sd.do_resume
            def sd_resume():
                if self._toolchange_pause_status():
                    raise gcode.error("Tool change is paused; use Resume to retry the tool change before continuing this job")
                return original_sd_resume()
            sd.do_resume = sd_resume
        for name in ("RESUME", "M24"):
            original = gcode.register_command(name, None)
            if original is not None:
                def resume(gcmd, original=original):
                    def execute():
                        if not self._retry_paused_toolchange(gcmd):
                            return original(gcmd)
                    return self._observe_resume(execute)
                gcode.register_command(name, resume)
        original_cancel = gcode.register_command("CANCEL_PRINT", None)
        if original_cancel is None:
            raise self.printer.config_error("Managed cancellation requires CANCEL_PRINT")
        def other_owner():
            return (self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None)
        def request_cancel():
            sd = self.printer.lookup_object("virtual_sdcard")
            stats = self.printer.lookup_object("print_stats")
            if sd.current_file is None and not sd.is_active() and not sd.is_cmd_from_sd():
                gcode.respond_info("No open print to cancel")
                return
            binding = {"session": self.session_id, "file": stats.filename, "handle": sd.current_file}
            return self._begin_print_cancel("legacy_cancel_" + uuid.uuid4().hex, binding)
        def guarded_cancel(gcmd):
            if other_owner():
                return original_cancel(gcmd)
            try:
                request_cancel()
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise gcode.error(str(error))
            # Returning would execute the rest of the enclosing macro and its
            # caller. Unwind both; an SD error fallback coalesces the same intent.
            raise gcode.error("Print cancellation requested; remaining macro commands retired")
        gcode.register_command("CANCEL_PRINT", guarded_cancel,
                               desc="Cancel through managed print ingress")
        def script(script):
            if other_owner():
                return original_script(script)
            commands = self._script_command_names(script)
            if "CANCEL_PRINT" in commands:
                try:
                    return request_cancel()
                except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                    raise gcode.error(str(error))
            if commands == ["M112"]:
                return original_script(script)
            allow_hold = self._cancel_cooling_script(script, commands)
            if commands in (["WMP_RESOLVE_PRINT_CANCEL"],):
                allow_hold = True
            if commands in (["RESTART"], ["FIRMWARE_RESTART"]) and gcode.is_printer_ready is False:
                allow_hold = True
            session, generation = self.session_id, getattr(self, "_command_generation", 0)
            def check():
                if (session != self.session_id or generation != getattr(self, "_command_generation", 0)
                        or (not allow_hold and self._print_cancel_active())):
                    raise gcode.error("Command invalidated by cancellation or restart; submit a new command")
                if other_owner():
                    raise gcode.error("Standalone command owner changed")
            boundary = self._execution_sd_boundary()
            process = getattr(gcode, "_process_commands", None)
            if callable(process):
                # Retained dispatcher accepts an iterable. Check immediately
                # before each original line, including after a yielding command,
                # without formatting/parsing an additional G-code command.
                def lines():
                    for line in script.split('\n'):
                        check()
                        yield line
                with gcode.get_mutex():
                    check()
                    if any(name in ("G28", "G29", "_CHANGE_TOOL", "PARK_CURRENT_TOOL", "LOCK", "UNLOCK",
                                    "BED_MESH_CALIBRATE", "PID_CALIBRATE", "SHAPER_CALIBRATE", "PROBE_CALIBRATE",
                                    "NOZZLE_PREPARE", "NOZZLE_CALIBRATE_TOOL_OFFSET", "RAPID_MODE", "_WMP_CALIBRATION_TOOL")
                           or re.fullmatch(r"T[0-3]", name) for name in commands):
                        try:
                            self._begin_explicit_physical_action("UNLOCK" if commands == ["UNLOCK"] else "console motion")
                        except ValueError as error:
                            raise gcode.error(str(error)) from error
                    try:
                        result = process(lines(), need_ack=False)
                    except Exception as error:
                        if self._capture_toolchange_pause(boundary, commands, error):
                            self._command_generation = getattr(self, "_command_generation", 0) + 1
                            return
                        # Retire requests queued before this failed batch; a
                        # fresh explicit action gets a new generation.
                        self._command_generation = getattr(self, "_command_generation", 0) + 1
                        raise
            else:
                # Compatibility for a dispatcher without the retained iterator
                # API: preserve the previous queue fence rather than bypass it.
                prefix = "WMP_CHECK_SCRIPT_GENERATION SESSION=%s GENERATION=%d ALLOW_HOLD=%d" % (
                    session, generation, allow_hold)
                guarded = []
                for line in script.split('\n'):
                    if line.split(';', 1)[0].strip(): guarded.append(prefix)
                    guarded.append(line)
                result = original_script("\n".join(guarded))
            if boundary is not None:
                self._execution_command_completed(boundary)
            return result
        self._cancel_script_wrapper = script
        gcode.run_script = script

    @staticmethod
    def _cancel_cooling_script(script, commands):
        """Admit explicit cooling and its diagnostics during live cancellation.

        A mixed batch containing movement or heating is not a cooling request.
        Old-generation requests remain retired regardless of this classification.
        """
        if not commands:
            return True
        for line, command in zip((line for line in script.split('\n')
                                  if line.strip().split(';', 1)[0].strip()), commands):
            if command in ("TURN_OFF_HEATERS", "M118", "RESPOND"):
                continue
            if command in ("M104", "M140"):
                target = re.search(r'(?i)\bS\s*([-+]?\d+(?:\.\d*)?)\s*(?:;.*)?$', line)
            elif command == "SET_HEATER_TEMPERATURE":
                targets = re.findall(r'(?i)\bTARGET\s*=\s*([-+]?\d+(?:\.\d*)?)(?:\s|$)', line)
                if len(targets) != 1 or float(targets[0]) != 0:
                    return False
                continue
            else:
                return False
            if target is None or float(target[1]) != 0:
                return False
        return True

    @staticmethod
    def _script_command_names(script):
        # Same command-name parsing as the retained vendor GCodeDispatch.
        commands = []
        for line in script.split('\n'):
            line = line.strip().split(';', 1)[0]
            if not line.strip():
                continue
            parts = re.split('([A-Z_]+|[A-Z*/])', line.upper())
            index = 3 if len(parts) >= 3 and parts[1] == 'N' else 1
            commands.append(parts[index] + parts[index + 1].strip() if len(parts) > index + 1 else "")
        return commands

    @classmethod
    def _script_has_print_cancel(cls, script):
        return "CANCEL_PRINT" in cls._script_command_names(script)

    def _handle_print_cancel_review(self, web_request):
        """Capture the exact open print for a separate explicit cancellation.

        Review creates no stop intent, timer, G-code or durable mutation. A
        bounded, expiring token retains the file object so reopening the same
        filename cannot transfer cancellation authority to another print.
        """
        try:
            request = {key: web_request.get_str(key) for key in ("id", "session", "file")}
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request["id"])
                    or request["session"] != self.session_id
                    or not 0 < len(request["file"]) <= 4096):
                raise ValueError("Invalid print cancellation review identity")
            if self._print_cancel_active():
                raise ValueError("Previous print cancellation needs resolution")
            reactor = self.printer.get_reactor()
            sd = self.printer.lookup_object("virtual_sdcard")
            stats = self.printer.lookup_object("print_stats")
            if (self.printer.is_shutdown()
                    or self.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state") != "ready"
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None
                    or stats.state not in ("printing", "paused", "error") or stats.filename != request["file"]
                    or sd.current_file is None):
                raise ValueError("No matching standalone print is available to cancel")
            now = reactor.monotonic()
            # Read-only reviews reserve no lasting cancellation authority.
            # Pruned tokens cannot revive: every replacement gets a new token;
            # actual attempted operation IDs retain their separate replay fence.
            tickets = {key: value for key, value in
                       getattr(self, "_print_cancel_tickets", {}).items()
                       if not value["used"] and now < value["expires"]}
            self._print_cancel_tickets = tickets
            existing = tickets.get(request["id"])
            if existing is not None:
                if (existing["used"] or reactor.monotonic() >= existing["expires"]
                        or existing["binding"]["handle"] is not sd.current_file
                        or any(existing["request"][key] != value for key, value in request.items())):
                    raise ValueError("Cancellation review was consumed or changed; review with a new ID")
                web_request.send({"request": dict(existing["request"])})
                return
            if request["id"] in getattr(self, "_print_cancel_requests", set()):
                raise ValueError("Cancellation ID was already attempted; use a new ID")
            if len(tickets) >= 1024:
                raise ValueError("Too many live cancellation reviews; wait for them to expire")
            request["token"] = uuid.uuid4().hex
            tickets[request["id"]] = {"request": dict(request), "used": False,
                "binding": {"session": self.session_id, "file": request["file"], "handle": sd.current_file},
                "expires": reactor.monotonic() + 60.}
            self._print_cancel_tickets = tickets
            web_request.send({"request": request})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise web_request.error(str(error))

    def _handle_print_cancel(self, web_request):
        """Record reactor intent only after the reviewed token is confirmed."""
        try:
            request = {key: web_request.get_str(key) for key in ("id", "session", "file", "token")}
            ticket = getattr(self, "_print_cancel_tickets", {}).get(request["id"])
            if (ticket is None or ticket["used"] or request != ticket["request"]
                    or request["session"] != self.session_id
                    or self.printer.get_reactor().monotonic() >= ticket["expires"]):
                raise ValueError("Print cancellation review is stale, changed or already used")
            ticket["used"] = True  # Consume before scheduling; a lost reply never replays.
            binding = ticket["binding"]
            ticket["binding"] = None
            result = self._begin_print_cancel(request["id"], binding)
            web_request.send(result)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise web_request.error(str(error))

    def _handle_print_cancel_resolution_review(self, web_request):
        try:
            request = {key: web_request.get_str(key) for key in ("id", "session", "cancel_id")}
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request["id"])
                    or request["session"] != self.session_id):
                raise ValueError("Invalid cancellation resolution identity")
            now = self.printer.get_reactor().monotonic()
            # Automatic read-only refresh must not exhaust a lifetime ticket
            # quota. Removed tokens remain ineligible; a later review creates a
            # different random token, never authority to replay an old command.
            tickets = {key: value for key, value in
                       getattr(self, "_print_cancel_resolution_tickets", {}).items()
                       if not value["used"] and now < value["expires"]}
            self._print_cancel_resolution_tickets = tickets
            evidence = self._print_cancel_resolution_evidence(request["cancel_id"])
            ticket = tickets.get(request["id"])
            if ticket is not None:
                if (any(ticket["request"][key] != value for key, value in request.items())
                        or ticket["evidence"] != evidence):
                    raise ValueError("Cancellation resolution evidence changed; use a new resolution ID")
                request = dict(ticket["request"])
            else:
                if len(tickets) >= 1024:
                    raise ValueError("Too many live cancellation reviews; wait for them to expire")
                request.update(token=uuid.uuid4().hex, action=evidence["action"], job_id=evidence["job_id"])
                tickets[request["id"]] = {"request": dict(request), "evidence": evidence, "used": False,
                    "expires": now + 60.}
            messages = {"finish_cleanup": "Finish cancelling the original open print",
                        "finish_idle_cleanup": "Finish heater and pause cleanup; no print file is open",
                        "discard_saved_job": "Discard the reviewed saved job and finish cancellation cleanup",
                        "acknowledge_complete": "Record verified cancellation completion; no printer commands"}
            web_request.send({"request": request, "file": evidence["record"]["file"],
                              "message": messages[evidence["action"]]})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise web_request.error(str(error))

    def cmd_RESOLVE_PRINT_CANCEL(self, gcmd):
        try:
            request = self._decode_recovery_json(gcmd.get("REQUEST"), limit=4096)
        except (ValueError, KeyError, TypeError) as error:
            raise gcmd.error(str(error))
        tickets = getattr(self, "_print_cancel_resolution_tickets", {})
        ticket = tickets.get(request.get("id")) if isinstance(request, dict) and isinstance(request.get("id"), str) else None
        if (ticket is None or ticket["used"] or request != ticket["request"]
                or request["session"] != self.session_id
                or self.printer.get_reactor().monotonic() >= ticket["expires"]):
            raise gcmd.error("Cancellation resolution review is stale, changed or already used")
        ticket["used"] = True
        entered = False
        try:
            evidence = self._print_cancel_resolution_evidence(request["cancel_id"], owned=True)
            if evidence != ticket["evidence"]:
                raise ValueError("Cancellation resolution evidence changed; review again")
            self._print_cancel_resolution = dict(request, state="pending", message="Resolving cancellation")
            entered = True
            self._print_cancel["message"] = "Resolving cancellation"
            phase = self._print_cancel_stage
            if evidence["action"] != "acknowledge_complete":
                self._cancel_print_cleanup(evidence["binding"], phase)
            self._command_generation = getattr(self, "_command_generation", 0) + 1
            self._print_cancel.update(state="complete", phase="complete", message="Print cancellation resolved")
            self._record_print_cancel()
            self._recovery_release_paused_worker(cancelled=True)
            self._print_cancel_resolution.update(state="complete", message="Print cancellation resolved")
        except Exception as error:
            if entered:
                self._print_cancel.update(state="unknown", message=str(error))
                self._print_cancel_interrupted_stages()
                try:
                    self._record_print_cancel()
                except (OSError, ValueError):
                    pass
            self._print_cancel_resolution = dict(request, state="unknown" if entered else "refused", message=str(error))
            raise gcmd.error(str(error))
        gcmd.respond_info("Print cancellation resolved")

    def _cancel_job_digest(self):
        try:
            return hashlib.sha256(self._recovery_read_bytes(self._recovery_job_path(), 65536)).hexdigest()
        except FileNotFoundError:
            return "missing"

    def _print_cancel_resolution_evidence(self, cancel_id, owned=False):
        """Read-only evidence for an explicit finish, discard or acknowledgement."""
        record = getattr(self, "_print_cancel", {})
        reactor = self.printer.get_reactor()
        sd = self.printer.lookup_object("virtual_sdcard")
        stats = self.printer.lookup_object("print_stats")
        if (record.get("id") != cancel_id or record.get("state") != "unknown"
                or not record.get("file") or not record.get("session")
                or self.printer.is_shutdown() or self.printer.lookup_object("gcode").get_mutex().test() is not owned
                or self.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state") != "ready"
                or self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None
                or sd.is_active() or sd.is_cmd_from_sd()
                or getattr(self, "_print_cancel_resolution", {}).get("state") == "pending"):
            raise ValueError("Cancellation resolution requires the stopped standalone attempt")
        if any(op.get("state") in ("pending", "running") for op in
               (self.filament_operation, getattr(self, "toolhead_operation", {}))):
            raise ValueError("Wait for managed service to stop before resolving cancellation")
        try:
            raw = self._recovery_read_bytes(self._print_cancel_path(), 65536)
            saved = json.loads(raw)
            if any(saved.get(key) != record.get(key) for key in ("id", "session", "file")):
                raise ValueError("Durable cancellation identity changed")
            receipt_hash = hashlib.sha256(raw).hexdigest()
        except FileNotFoundError:
            # A same-process intent can fail its first write. No identity may
            # be invented for a missing/corrupt record after process restart.
            live = getattr(self, "_print_cancel_live_binding", None)
            if live is None or live["cancel_id"] != cancel_id or live["session"] != self.session_id:
                raise ValueError("Durable cancellation identity is unavailable")
            receipt_hash = "missing"
        binding = {"session": self.session_id, "file": stats.filename, "handle": sd.current_file,
                   "job_hash": self._cancel_job_digest()}
        if sd.current_file is not None:
            live = getattr(self, "_print_cancel_live_binding", None)
            if (live is None or live["cancel_id"] != cancel_id or live["session"] != self.session_id
                    or live["handle"] is not sd.current_file or live["file"] != stats.filename
                    or stats.state not in ("paused", "error")):
                raise ValueError("An open file cannot be identified as the interrupted cancellation")
            action = "finish_cleanup"
        else:
            if stats.state not in ("standby", "cancelled", "error") or stats.filename not in ("", record["file"]):
                raise ValueError("Another print context is present")
            if stats.state == "error":
                # A cancellation fence can leave the original vendor error
                # label after closing its file. Do not attribute an unrelated
                # later error to this receipt based on filename alone.
                live = getattr(self, "_print_cancel_live_binding", None)
                if (live is None or live["cancel_id"] != cancel_id
                        or live["session"] != self.session_id
                        or live["file"] != stats.filename
                        or stats.filename != record["file"]
                        or live["handle"] is None or not live["handle"].closed):
                    raise ValueError("Stopped error cannot be identified as the interrupted cancellation")
            binding["idle_resolution"] = True
            action = "finish_idle_cleanup"
        variables = self.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
        context = copy.deepcopy(variables.get("wmp_print_context"))
        job = None if binding["job_hash"] == "missing" else self._read_recovery_job()
        if job is not None and job.get("state") != "invalidated" and job.get("file", {}).get("path") != record["file"]:
            raise ValueError("Another saved job is present")
        job_id = job.get("id", "") if job else ""
        if not isinstance(job_id, str) or (job_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", job_id)):
            raise ValueError("Saved job identity is invalid")
        # With no open file, remaining recovery authority is a separate explicit
        # discard decision, never inferred from filename equality after restart.
        if binding.get("idle_resolution") and (context or job is not None and job.get("state") != "invalidated"):
            if (job is None or job.get("file", {}).get("path") != record["file"]
                    or not isinstance(job.get("id"), str) or not job["id"]):
                raise ValueError("Remaining saved job needs its own recovery review")
            action = "discard_saved_job"
        heaters = {}
        names = self.printer.lookup_object("heaters").get_all_heaters()
        if not isinstance(names, (list, tuple)) or not names:
            raise ValueError("Heater inventory is unavailable")
        for name in names:
            target = self.printer.lookup_object(name).get_status(reactor.monotonic()).get("target")
            if type(target) not in (int, float) or not math.isfinite(target):
                raise ValueError("Heater target is unavailable")
            heaters[name] = target
        paused = self.printer.lookup_object("pause_resume").get_status(reactor.monotonic()).get("is_paused")
        begin = self.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(reactor.monotonic()).get("active")
        body = self.printer.lookup_object("gcode_macro START_PRINT").get_status(reactor.monotonic()).get("print_body_ready")
        if (action == "finish_idle_cleanup" and context == {} and paused is False
                and begin in (False, 0) and body in (False, 0) and all(v == 0 for v in heaters.values())):
            action = "acknowledge_complete"
        return {"binding": binding, "action": action, "cancel_id": cancel_id,
                "receipt_hash": receipt_hash, "record": copy.deepcopy(record), "context": context,
                "job_id": job_id, "heaters": heaters,
                "paused": paused, "begin": begin, "body": body}

    def _print_cancel_path(self):
        return os.path.join(os.path.dirname(self.profile_path), "wmp_print_cancel.json")

    def _print_cancel_unresolved(self):
        """Diagnostic history, not standalone machine-operation admission."""
        return getattr(self, "_print_cancel", {}).get("state") in ("pending", "unknown")

    def _print_cancel_active(self):
        # Pending belongs to this process's queued/running cleanup. Unknown is
        # a terminal or restored result; its old callback cannot run again.
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return self._print_cancel_unresolved()
        return getattr(self, "_print_cancel", {}).get("state") == "pending"

    _CANCEL_STAGES = ("stopping", "draining", "cooling", "invalidating", "cancelling", "clearing_pause")

    def _record_print_cancel(self):
        record = dict(self._print_cancel)
        record.pop("persistence_error", None)
        try:
            self._write_recovery_json(self._print_cancel_path(), record)
        except (OSError, ValueError) as error:
            message = str(error)[:256]
            if self._print_cancel.get("persistence_error") != message:
                logging.warning("Unable to persist cancellation result: %s", message)
            self._print_cancel["persistence_error"] = message

    def _print_cancel_stage(self, name, state="running"):
        record = self._print_cancel
        if "stages" not in record:
            record.update(version=2, stages=[{"name": n, "state": "pending"} for n in self._CANCEL_STAGES])
        record["phase"] = name
        for stage in record["stages"]:
            if stage["name"] == name:
                stage["state"] = state
                break
        self._record_print_cancel()

    def _print_cancel_interrupted_stages(self):
        for stage in self._print_cancel.get("stages", []):
            if stage["state"] == "running":
                stage["state"] = "unknown"

    def _restore_print_cancel(self):
        self._print_cancel_live_binding = None
        self._print_cancel = {}
        try:
            record = json.loads(self._recovery_read_bytes(self._print_cancel_path(), 65536))
            if (not isinstance(record, dict) or set(record) != ({"version", "id", "session", "file", "state", "phase", "message"}
                        | ({"stages"} if record.get("version") == 2 else set()))
                    or type(record["version"]) is not int or record["version"] not in (1, 2)
                    or not isinstance(record["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", record["id"])
                    or not isinstance(record["session"], str) or not record["session"]
                    or not isinstance(record["file"], str) or not record["file"]
                    or record["state"] not in ("pending", "unknown", "complete")
                    or not isinstance(record["phase"], str) or not isinstance(record["message"], str)):
                raise ValueError("Invalid print cancellation record")
            if record["version"] == 2:
                stages = record["stages"]
                if (not isinstance(stages, list) or len(stages) != len(self._CANCEL_STAGES)
                        or any(not isinstance(stage, dict) or set(stage) != {"name", "state"}
                               or stage["name"] != name or stage["state"] not in
                               ("pending", "running", "complete", "failed", "unknown")
                               for stage, name in zip(stages, self._CANCEL_STAGES))):
                    raise ValueError("Invalid cancellation stages")
            if record["state"] == "pending":
                record.update(state="unknown", message="Print cancellation was interrupted; cleanup needs review")
            self._print_cancel = record
            if record["state"] == "unknown":
                self._print_cancel_interrupted_stages()
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError) as error:
            self._print_cancel = {"state": "unknown", "message": "Print cancellation record is unreadable: " + str(error)}

    def _begin_print_cancel(self, request_id, binding):
        """Reactor-intent core; the public endpoint binds explicit user review.

        Queued managed work is fenced immediately; only the stopped worker
        schedules command-owned cleanup.
        """
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise ValueError("Invalid print cancellation identity")
        used = getattr(self, "_print_cancel_requests", set())
        if request_id in used and not self._print_cancel_active():
            raise ValueError("Print cancellation already attempted")
        binding = dict(binding)
        sd = self.printer.lookup_object("virtual_sdcard")
        stats = self.printer.lookup_object("print_stats")
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        current_refusal = ['']
        def current():
            def refuse(reason):
                current_refusal[0] = reason
                return False
            current_refusal[0] = ''
            if binding["session"] != self.session_id: return refuse('printer session changed')
            if self.printer.is_shutdown(): return refuse('printer is shut down')
            state = self.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state")
            if state != "ready": return refuse('webhooks.state=' + repr(state)[:80])
            if self.printer.lookup_object("openace", None) is not None: return refuse('openace owner is present')
            if self.printer.lookup_object("AFC", None) is not None: return refuse('AFC owner is present')
            if stats.filename != binding["file"]: return refuse('print_stats.filename differs from reviewed job')
            if binding["handle"] is None: return refuse('reviewed file handle is missing')
            if sd.current_file is not binding["handle"]: return refuse('virtual_sdcard file handle changed')
            return True
        if not current() or stats.state not in ("printing", "paused", "error"):
            raise ValueError("Print cancellation review no longer matches the current job: " +
                             (current_refusal[0] or 'print_stats.state=' + repr(stats.state)[:80]))
        live = getattr(self, "_print_cancel_live_binding", None)
        if self._print_cancel_active():
            if (live is not None and all(live.get(key) == binding.get(key) for key in ("session", "file"))
                    and live.get("handle") is binding.get("handle") is sd.current_file):
                return copy.deepcopy(self._print_cancel)
            raise ValueError("A different current cancellation is already running")
        if request_id in used:
            raise ValueError("Print cancellation already attempted")
        if len(used) >= 1024:
            # This bounded receipt cache cannot disable Stop. Current-job binding
            # and the live-worker coalescing above are the execution authority.
            used = set()
        # Retire admitted callbacks/review tokens even if the intent write fails.
        # Clearing the cancellation hold must never revive pre-cancel work.
        self._command_generation = getattr(self, "_command_generation", 0) + 1
        used.add(request_id)
        self._print_cancel_requests = used
        self._print_cancel_live_binding = dict(binding, cancel_id=request_id)
        self._print_cancel = {"version": 2, "id": request_id, "session": self.session_id,
            "file": binding["file"], "state": "pending", "phase": "stopping",
            "message": "Waiting for current work to stop",
            "stages": [{"name": n, "state": "running" if n == "stopping" else "pending"}
                       for n in self._CANCEL_STAGES]}
        def persist():
            self._record_print_cancel()
        def unknown(error):
            # Terminal failure retires commands admitted during the live stop,
            # just as successful cleanup does. History never revives that tail.
            self._command_generation = getattr(self, "_command_generation", 0) + 1
            self._print_cancel.update(state="unknown", message=str(error))
            self._print_cancel_interrupted_stages()
            try:
                persist()
            except (OSError, ValueError):
                pass  # Preserve the in-memory result; never fabricate completion.
        # Stop intent is live state, not contingent on diagnostic storage.
        sd.must_pause_work = True
        if (self.filament_operation.get("state") == "running"
                and self.filament_operation.get("session") == self.session_id):
            self.filament_operation.update(cancel_requested=True,
                message="Print cancelled; waiting for filament service to stop")
        persist()
        phase = self._print_cancel_stage
        timer = None
        def retire_timer():
            nonlocal timer
            if timer is not None:
                reactor.unregister_timer(timer)
                timer = None
        def cleanup(eventtime):
            waiting = False
            try:
                if self._print_cancel.get("id") != request_id or self._print_cancel.get("state") != "pending":
                    return reactor.NEVER
                if not current():
                    raise ValueError("Print cancellation lost its admitted job or owner: " + (current_refusal[0] or "command generation changed"))
                if sd.is_active() or sd.is_cmd_from_sd() or gcode.get_mutex().test():
                    waiting = True
                    return eventtime + .05
                with gcode.get_mutex():
                    result = self._cancel_print_cleanup(binding, phase)
                    # Also retire commands submitted while the hold was active.
                    self._command_generation = getattr(self, "_command_generation", 0) + 1
                    warnings = result.get("warnings", []) if isinstance(result, dict) else []
                    message = "Print cancelled" + ("; housekeeping warnings: " + "; ".join(warnings)[:384] if warnings else "")
                    self._print_cancel.update(state="complete", phase="complete", message=message)
                    persist()
            except Exception as error:
                unknown(error)
            finally:
                # NEVER stops scheduling but leaves the callback and job binding
                # in the reactor's timer list. Only a live wait owns this timer.
                if not waiting:
                    retire_timer()
            return reactor.NEVER
        try:
            timer = reactor.register_timer(cleanup, reactor.NEVER)
            if timer is None:
                raise ValueError("Print cancellation worker registration failed")
            reactor.update_timer(timer, reactor.NOW)
        except Exception as error:
            try:
                unknown(error)
            finally:
                retire_timer()
            raise
        return copy.deepcopy(self._print_cancel)

    def _cancel_print_cleanup(self, binding, phase=lambda name, state="running": None):
        """Cleanup an admitted, stopped SD job without adding physical motion.

        Private primitive: the reactor intent/fence must stop SD dispatch and
        acquire the G-code mutex before calling. The caller journals any partial
        outcome; an exception never authorizes replay of the old cleanup.
        """
        sd = self.printer.lookup_object("virtual_sdcard")
        stats = self.printer.lookup_object("print_stats")
        gcode = self.printer.lookup_object("gcode")
        reactor = self.printer.get_reactor()
        idle_resolution = binding.get("idle_resolution") is True
        cancelled = [idle_resolution]
        def guard():
            def refuse(reason):
                raise ValueError("Print cancellation lost its stopped job or command ownership: " + reason)
            if binding["session"] != self.session_id: refuse('printer session changed')
            if self.printer.is_shutdown(): refuse('printer is shut down')
            if not gcode.get_mutex().test(): refuse('G-code mutex is not held')
            if self.printer.lookup_object("openace", None) is not None: refuse('openace owner is present')
            if self.printer.lookup_object("AFC", None) is not None: refuse('AFC owner is present')
            state = self.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state")
            if state != "ready": refuse('webhooks.state=' + repr(state)[:80])
            if stats.filename != binding["file"]: refuse('print_stats.filename differs from admitted job')
            if sd.is_active(): refuse('virtual_sdcard is active')
            if sd.is_cmd_from_sd(): refuse('virtual_sdcard command is active')
            if sd.current_file is not (None if cancelled[0] else binding["handle"]):
                refuse('virtual_sdcard file handle differs from stopped job')
            if binding["handle"] is None and not idle_resolution: refuse('admitted file handle is missing')
            if idle_resolution and stats.state not in ("standby", "cancelled", "error"):
                refuse('idle resolution print_stats.state=' + repr(stats.state)[:80])
        def run(command):
            guard()
            gcode.run_script_from_command(command)
            guard()
        guard()
        errors, warnings = [], []
        def cleanup_phase(name, state="running"):
            try:
                phase(name, state)
            except Exception as error:
                warnings.append("cleanup progress: " + str(error))
        def attempt(name, callback):
            cleanup_phase(name)
            try:
                guard()
                callback()
                guard()
            except Exception as error:
                errors.append(name + ": " + str(error))
                cleanup_phase(name, "failed")
                return False
            cleanup_phase(name, "complete")
            return True
        cleanup_phase("stopping", "complete")
        attempt("draining", lambda: run("M400"))
        def cool():
            run("TURN_OFF_HEATERS")
            names = self.printer.lookup_object("heaters").get_all_heaters()
            if not isinstance(names, (list, tuple)) or not names:
                raise ValueError("Heater inventory is unavailable")
            for name in names:
                target = self.printer.lookup_object(name).get_status(reactor.monotonic()).get("target")
                if type(target) not in (int, float) or target != 0:
                    raise ValueError("Heater shutdown is not confirmed for %s" % name)
        attempt("cooling", cool)
        def invalidate():
            if "job_hash" in binding and self._cancel_job_digest() != binding["job_hash"]:
                raise ValueError("Saved job changed before cancellation invalidation")
            run("_WMP_PRINT_CONTEXT_CLEAR")
            variables = self.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            context = self._read_recovery_job()
            if (variables.get("wmp_print_context") != {}
                    or context.get("state") != "invalidated" or context.get("session") != self.session_id
                    or self.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(reactor.monotonic()).get("active") not in (False, 0)):
                raise ValueError("Cancelled job recovery authority was not invalidated")
            run("SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False")
            if self.printer.lookup_object("gcode_macro START_PRINT").get_status(reactor.monotonic()).get("print_body_ready") not in (False, 0):
                raise ValueError("Print body authority was not cleared")
        attempt("invalidating", invalidate)
        def close_file():
            if not idle_resolution:
                try:
                    sd.do_cancel()
                finally:
                    # A handler can throw after closing the file. Recognize the
                    # same file's actual outcome so pause cleanup remains reachable.
                    if sd.current_file is None and binding["handle"].closed:
                        cancelled[0] = True
                # Retiring a running SD command unwinds through note_error().
                # The vendor then clears print_start_time, so its later
                # note_cancel() intentionally leaves that terminal error intact.
                # Confirm the stopped, closed job rather than requiring the
                # historical label to change; preserve its diagnostic message.
                guard()
                if stats.state not in ("cancelled", "error") or not cancelled[0]:
                    raise ValueError("SD cancellation was not confirmed")
        attempt("cancelling", close_file)
        def clear_pause():
            run("CLEAR_PAUSE")
            if self.printer.lookup_object("pause_resume").get_status(reactor.monotonic()).get("is_paused") is not False:
                raise ValueError("Native pause cleanup was not confirmed")
            self._recovery_release_paused_worker(cancelled=True)
        attempt("clearing_pause", clear_pause)
        # These independent actions restore stock non-motion housekeeping. Never
        # enter retract, park, wipe, homing or a coupling sequence from Cancel.
        housekeeping = ["M107", "BED_MESH_CLEAR", "M220 S100",
            "SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=adaptive_mesh VALUE=0",
            "RESET_FLOW_EXTRUDER"]
        # Keep the selected tool mapping and physical Z reference. A cancelled
        # attempt did not acquire ownership of the user's persistent selection.
        try:
            settings = self.printer.lookup_object("configfile").get_status(reactor.monotonic())["settings"]
            housekeeping.extend([
                "SET_VELOCITY_LIMIT VELOCITY=%s ACCEL=%s" % (settings["printer"]["max_velocity"], settings["printer"]["max_accel"]),
                "SET_IDLE_TIMEOUT TIMEOUT=%s" % settings["idle_timeout"]["timeout"]])
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            warnings.append("speed/idle-timeout settings unavailable: " + str(error))
        housekeeping.append("_WMP_CASE_LIGHT_PRINT_END")
        for command in housekeeping:
            try:
                run(command)
            except Exception as error:
                warnings.append(command.split()[0] + ": " + str(error))
        if warnings:
            logging.warning("Cancellation housekeeping warnings: %s", "; ".join(warnings))
        if errors:
            raise ValueError("; ".join(errors))
        return {"state": "complete", "file": binding["file"], "message": "Print cancelled",
                "warnings": warnings}

    def _handle_filament_cancel(self, web_request):
        # Webhooks run on the reactor without waiting for the G-code mutex.
        # Only record intent here; the running procedure owns hardware cleanup.
        operation = self.filament_operation
        if (web_request.get_str("session") != self.session_id or
                operation.get("session") != self.session_id or
                web_request.get_str("id") != operation.get("id") or
                web_request.get_str("head") != operation.get("head")):
            raise web_request.error("Filament operation changed")
        if operation.get("state") != "running":
            raise web_request.error("Filament operation is not running")
        owner = self.printer.lookup_object("openace", None)
        binding = getattr(self, "_openace_filament_cancel", None)
        if owner is not None or binding is not None:
            if (binding is None or owner is not binding["owner"]
                    or operation is not binding["operation"]):
                raise web_request.error("openACE filament owner changed")
            plan = binding["plan"]
            now = self.printer.get_reactor().monotonic()
            ace = owner.get_status(now)
            if (not self._filament_context_valid(plan, now)
                    or ace.get("session_id") != plan["ace_session"]
                    or ace.get("operation") not in (None, binding["owner_operation"])
                    or "job" not in ace or ace["job"] is not None and
                    (not isinstance(ace["job"], dict) or ace["job"].get("active") is not False)):
                raise web_request.error("openACE filament operation changed")
            operation.update(cancel_requested=True, message="Requesting openACE stop")
            # Between commands WM+ owns the insertion wait. During a command,
            # ask the owner to abort on the reactor, never queue behind G-code.
            # Intent must stay latched even if dispatch fails, but a failed
            # dispatch must not suppress a later STOP retry. The binding is
            # revalidated above on every request before touching the owner.
            if binding["active"] and not binding.get("abort_dispatched", False):
                owner.abort_operation("WM+ filament STOP " + operation["id"])
                binding["abort_dispatched"] = True
        operation.update(cancel_requested=True, message="Cancellation requested; waiting for the current phase to stop")
        web_request.send({"id": operation["id"], "session": self.session_id,
                          "state": "requested"})

    def cmd_RECOVER_FILAMENT(self, gcmd):
        operation = self.filament_operation
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        if (gcmd.get("SESSION") != self.session_id or operation.get("session") != self.session_id
                or gcmd.get("ID") != operation.get("id") or operation.get("head") != "h%d" % head):
            reason = ("SESSION differs from printer session" if gcmd.get("SESSION") != self.session_id else
                      "operation session differs from printer session" if operation.get("session") != self.session_id else
                      "ID differs from operation" if gcmd.get("ID") != operation.get("id") else
                      "HEAD differs from operation; requested=h%d, recorded=%s" % (head, str(operation.get("head"))[:80]))
            raise gcmd.error("Filament operation changed; reopen recovery: " + reason)
        if operation.get("state") != "unknown":
            raise gcmd.error("Filament operation does not need reconciliation: state=" + str(operation.get("state"))[:80])
        binding = getattr(self, "_openace_filament_recovery", None)
        if binding is not None:
            if (operation is not binding["operation"]
                    or self.printer.lookup_object("openace", None) is not binding["owner"]
                    or gcmd.get_int("GENERATION", minval=0, maxval=9223372036854775807)
                    != getattr(self, "_command_generation", 0)):
                raise gcmd.error("openACE recovery context changed")
            try:
                self._finish_openace_filament_stop(binding["plan"], head)
            except Exception as error:
                operation.update(state="unknown", message="Stop not confirmed: " + str(error))
                raise gcmd.error(operation["message"])
            self._openace_filament_recovery = None
            operation.pop("openace_recovery_supported", None)
            gcmd.respond_info(operation["message"])
            return
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another filament manager owns this printer")
        # Explicit cleanup is a new admission, not a replay of retired feed work.
        recovery_context = dict(operation, command_generation=getattr(self, "_command_generation", 0))
        if not self._filament_context_valid(recovery_context, self.printer.get_reactor().monotonic()):
            raise gcmd.error("Filament recovery requires an idle printer: " + getattr(self, "_filament_context_refusal", "context admission was not confirmed"))
        if self._material_operation_active("toolhead_operation"):
            raise gcmd.error("Resolve the toolhead operation first")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is unavailable")
        run = self.printer.lookup_object("gcode").run_script_from_command
        operation.update(phase="draining", steps=[
            {"phase": "draining", "label": "Wait for motion to stop"},
            {"phase": "cooling", "label": "Turn heater off"},
            {"phase": "verifying", "label": "Verify filament and attachment sensors"}])
        errors = []
        failed_phase = None
        # No feed, tool-change, homing or retry of the original sequence. Even
        # if draining fails, still attempt to stop this operation's heater.
        try:
            run("M400")
        except Exception as error:
            errors.append("motion stop: " + str(error))
            failed_phase = "draining"
        operation["phase"] = "cooling"
        try:
            run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
            now = self.printer.get_reactor().monotonic()
            if self.printer.lookup_object(heater).get_status(now).get("target") != 0:
                raise ValueError("heater target is not zero")
        except Exception as error:
            errors.append("heater off: " + str(error))
            failed_phase = failed_phase or "cooling"
        operation["phase"] = "verifying"
        try:
            now = self.printer.get_reactor().monotonic()
            if not self._filament_context_valid(recovery_context, now):
                raise ValueError("printer became busy: " + getattr(self, "_filament_context_refusal", "context admission was not confirmed"))
            attachment = self._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("head attachment sensors disagree")
            presence = self._sensor_filament_status(now)[operation["head"]]["state"]
            if presence not in ("loaded", "empty"):
                raise ValueError("filament sensor is unavailable")
        except Exception as error:
            errors.append("sensor verification: " + str(error))
            failed_phase = failed_phase or "verifying"
        if errors:
            # Later safety cleanup is still attempted, but must not make an
            # earlier failed stage appear completed in the progress display.
            operation.update(phase=failed_phase, message="Recovery not confirmed: " + "; ".join(errors))
            self._record_filament_result()
            raise gcmd.error(operation["message"])
        confirmed = self._loaded_filament_status(now).get(operation["head"], {}).get("state") == "loaded"
        operation.update(state="failed", recovered=True, phase="stopped",
                         recovery_presence=presence, recovery_attachment=attachment,
                         message=("Stopped. Filament remains loaded." if confirmed else
                                  "Stopped. Filament is present; complete Load before printing." if presence == "loaded" else
                                  "Stopped. Head is empty."))
        self._record_filament_result()
        gcmd.respond_info(operation["message"])

    def _filament_checkpoint(self, phase):
        self.filament_operation["phase"] = phase
        self._record_filament_result()
        if self.filament_operation.get("cancel_requested"):
            raise FilamentCancelled("Filament operation cancelled")
        if self.filament_operation.get("pause_origin") and not self._filament_context_valid(
                self.filament_operation, self.printer.get_reactor().monotonic()):
            raise ValueError("Paused print context changed during filament service: " + getattr(self, "_filament_context_refusal", "context admission was not confirmed"))

    def _execute_filament(self, gcmd, head, action, plan):
        try:
            if plan.get("pause_origin"):
                self._pause_origin.update(serviced=True, ready=False)
                if self._pause_origin.get("kind") == "toolchange":
                    self._pause_origin["fault"]["service_required"].add(plan["head"])
            return self._execute_filament_impl(gcmd, head, action, plan)
        finally:
            binding = getattr(self, "_openace_filament_cancel", None)
            if binding is not None and self.filament_operation.get("state") == "unknown":
                self._openace_filament_recovery = binding
                self.filament_operation["openace_recovery_supported"] = True
            self._openace_filament_cancel = None
            self.filament_operation.pop("openace_cancel_supported", None)
            self._record_filament_result()

    def _openace_filament_context(self, plan, now):
        # Preparation and the insertion wait yield to the reactor. A reviewed
        # plan must not authorize feeding into a replacement owner/job/config.
        binding = (getattr(self, "_openace_filament_cancel", None)
                   or getattr(self, "_openace_filament_recovery", None))
        if (binding is not None and self.printer.lookup_object("openace", None) is not binding["owner"]
                or plan.get("session") != self.session_id
                or not self._filament_context_valid(plan, now)):
            raise ValueError("Filament service context changed")
        ace = self._openace_idle_status(now)
        identity = (ace.get("management", {}).get("identity_settings", {}).get(plan["head"], {}).get("values", {})
                    if plan.get("direct") else ace.get("inventory", {}).get(plan.get("source"), {}))
        if (ace["session_id"] != plan["ace_session"]
                or ace["config_revision"] != plan["config_revision"]
                or plan["action"] == "load" and identity != plan["identity"]):
            raise ValueError("openACE filament context changed; review again")
        return ace

    def _finish_openace_filament_stop(self, plan, head):
        reactor = self.printer.get_reactor()
        run = self.printer.lookup_object("gcode").run_script_from_command
        self._openace_filament_context(plan, reactor.monotonic())
        self.filament_operation.update(phase="draining", steps=[
            {"phase": "draining", "label": "Wait for motion to stop"},
            {"phase": "cooling", "label": "Turn heater off"},
            {"phase": "verifying", "label": "Verify openACE stop"}])
        run("M400")
        self._openace_filament_context(plan, reactor.monotonic())
        self.filament_operation["phase"] = "cooling"
        heater = "extruder" if head == 0 else "extruder%d" % head
        run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
        self.filament_operation["phase"] = "verifying"
        ace = self._openace_filament_context(plan, reactor.monotonic())
        devices = ace.get("devices", {})
        abort = devices.get("abort", {})
        if (abort.get("requested") is not False or abort.get("scopes") != []
                or devices.get("stop_pending") != {}
                or self.printer.lookup_object(heater).get_status(reactor.monotonic()).get("target") != 0):
            raise ValueError("openACE stop or heater shutdown is not confirmed")
        # Stopped motion is separate from the owner's filament assessment.
        self.filament_operation.update(state="failed", cancelled=True, stopped=True, recovered=True,
            message="Stopped; heater off. Check openACE filament state before loading again.")

    def _execute_filament_impl(self, gcmd, head, action, plan):
        if plan.get("owner") == "openace":
            steps = ([{"phase": "heating", "label": "Mount and heat head"},
                      {"phase": "inserting", "label": "Insert filament"},
                      {"phase": "feeding", "label": "Load filament"}] if plan.get("direct") else
                     [{"phase": "feeding", "label": "Load filament via openACE" if action == "load" else "Unload filament via openACE"}])
            steps.append({"phase": "verifying", "label": "Verify filament state"})
            self.filament_operation.update(steps=steps, phase=steps[0]["phase"])
            try:
                run = self.printer.lookup_object("gcode").run_script_from_command
                owner = self.printer.lookup_object("openace")
                owner_operation = ("openace_load_direct " + plan["head"] if plan.get("direct") else
                                   "select T%d" % plan["tool"] if action == "load" else "unload " + plan["head"])
                binding = {"owner": owner, "operation": self.filament_operation,
                           "plan": plan, "active": False, "owner_operation": owner_operation}
                if callable(getattr(owner, "abort_operation", None)):
                    self._openace_filament_cancel = binding
                    self.filament_operation["openace_cancel_supported"] = True
                def checkpoint():
                    if self.filament_operation.get("cancel_requested"):
                        raise FilamentCancelled("openACE filament stop requested")
                def owner_command(command):
                    checkpoint()
                    binding["active"] = True
                    try:
                        run(command)
                    finally:
                        binding["active"] = False
                    checkpoint()
                if plan.get("direct"):
                    self.filament_operation.update(message="Mounting and heating the head")
                    owner_command("OPENACE_LOAD_DIRECT HEAD=%s TEMP=%.3f" % (plan["head"], plan["target"]))
                    self.filament_operation.update(phase="inserting", message="Insert filament into Head %d" % (head + 1))
                    reactor = self.printer.get_reactor(); deadline = reactor.monotonic() + 180
                    while True:
                        checkpoint()
                        self._openace_filament_context(plan, reactor.monotonic())
                        if self._sensor_filament_status(reactor.monotonic())[plan["head"]]["state"] == "loaded":
                            break
                        if reactor.monotonic() >= deadline:
                            raise ValueError("No filament detected; loading timed out")
                        reactor.pause(reactor.monotonic() + .25)
                    self.filament_operation.update(phase="feeding", message="Loading filament")
                    owner_command("OPENACE_LOAD_DIRECT HEAD=%s DONE=1" % plan["head"])
                else:
                    owner_command(("OPENACE_SELECT TOOL=%d" % plan["tool"]) if action == "load" else "OPENACE_UNLOAD HEAD=" + plan["head"])
                self.filament_operation["phase"] = "verifying"
                ace = self.printer.lookup_object("openace").get_status(self.printer.get_reactor().monotonic())
                actual = ace.get("loaded", {}).get(plan["head"], {})
                completed = (actual.get("state") == "loaded" and actual.get("verified") is True
                             and actual.get("destination") == plan["destination"]
                             and isinstance(actual.get("identity"), dict)
                             and all(actual["identity"].get(field) == plan["identity"].get(field)
                                     for field in ("material", "color"))) if action == "load" else actual.get("state") == "empty"
                if (ace.get("session_id") != plan["ace_session"]
                        or "operation" not in ace or ace["operation"] is not None or not completed):
                    raise gcmd.error("openACE %s completion is not confirmed" % action)
            except Exception:
                if self.filament_operation.get("cancel_requested"):
                    try:
                        self._finish_openace_filament_stop(plan, head)
                    except Exception as error:
                        self.filament_operation.update(state="unknown", message="Stop not confirmed: " + str(error))
                        raise
                    return
                if plan.get("direct"):
                    try:
                        # Do not cool a replacement job or owner's heater.
                        self._openace_filament_context(plan, self.printer.get_reactor().monotonic())
                        run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % ("extruder" if head == 0 else "extruder%d" % head))
                    except Exception:
                        pass
                self.filament_operation.update(state="unknown", message="openACE filament outcome uncertain; inspect backend recovery state")
                raise
            self.filament_operation.update(state="complete", message="openACE verified the selected source loaded" if action == "load" else "openACE reports the head empty")
            gcmd.respond_info(self.filament_operation["message"])
            return
        steps = []
        if "service" in plan:
            if plan["service"].get("needs_home"):
                steps.append(("homing", "Home X/Y"))
            steps.extend([("preparing", "Position head"), ("heating", "Heat nozzle")])
            if action == "load":
                steps.append(("inserting", "Insert filament"))
        steps.append(("feeding", "Feed filament" if action == "load" else "Retract filament"))
        if action == "load":
            steps.append(("purging", "Purge nozzle"))
            if "service" in plan:
                steps.append(("wiping", "Wipe nozzle"))
        if plan.get("service", {}).get("return_head") is not None:
            steps.append(("returning", "Return original paused head"))
        steps.append(("finishing", "Finish and turn heater off"))
        self.filament_operation["steps"] = [{"phase": phase, "label": label} for phase, label in steps]
        try:
            self._filament_checkpoint(steps[0][0])
            if "service" in plan:
                self._prepare_service(head, plan["service"])
                self._filament_checkpoint("heating")
                heater = "extruder" if head == 0 else "extruder%d" % head
                gcode = self.printer.lookup_object("gcode")
                self.filament_operation.update(message="Heating Head %d" % (head + 1))
                gcode.run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.3f" % (heater, plan["target"]))
                reactor = self.printer.get_reactor(); heat_deadline = reactor.monotonic() + 300
                while True:
                    self._filament_checkpoint("heating")
                    state = self.printer.lookup_object(heater).get_status(reactor.monotonic())
                    if state.get("target") != plan["target"] or not self._filament_context_valid(plan, reactor.monotonic()):
                        raise ValueError("Heating cancelled or printer became busy: " + ("heater target=%s; expected %s" % (repr(state.get("target"))[:80], repr(plan["target"])[:80]) if state.get("target") != plan["target"] else getattr(self, "_filament_context_refusal", "context admission was not confirmed")))
                    if abs(state.get("temperature", 0) - plan["target"]) <= 3 and state.get("can_extrude"):
                        break
                    if reactor.monotonic() >= heat_deadline:
                        raise ValueError("Nozzle heating timed out")
                    reactor.pause(reactor.monotonic() + .25)
                if action == "load":
                    self.filament_operation.update(message="Insert filament into Head %d" % (head + 1))
                    reactor = self.printer.get_reactor()
                    deadline = reactor.monotonic() + 180
                    while self._sensor_filament_status(reactor.monotonic())[plan["head"]]["state"] != "loaded":
                        self._filament_checkpoint("inserting")
                        if reactor.monotonic() >= deadline:
                            raise ValueError("No filament detected; loading timed out")
                        reactor.pause(reactor.monotonic() + .25)
                if not self._filament_context_valid(plan, reactor.monotonic()) or self._attachment(reactor.monotonic()) != {"state": "attached", "head": plan["head"]}:
                    raise ValueError("Printer or attachment changed before extrusion")
                if self.printer.lookup_object("toolhead").get_status(reactor.monotonic()).get("extruder") != heater:
                    raise ValueError("Active extruder changed before feeding")
                if self.printer.lookup_object(heater).get_status(reactor.monotonic()).get("target") != plan["target"]:
                    raise ValueError("Heating cancelled")
                self.filament_operation.update(message="Loading filament" if action == "load" else "Unloading filament")
            self._filament_checkpoint("feeding")
            sequence = "G1 E%g F400" % plan.get("feed_mm", 55.) if action == "load" else "_TIP_SHAPE_MOVES CLASS=" + plan["class"]
            if action == "load":
                # Persist uncertainty before dispatch: a partial feed may leave
                # both materials in the hotend even if the command raises.
                self._record_hotend_material(plan["head"], plan["identity"], purged=False)
            if action == "unload":
                # Once explicit withdrawal begins, the old loaded confirmation
                # is no longer trustworthy, even if the process dies mid-move.
                # Keep identity; inlet presence alone must never restore it.
                self._set_filament_loaded(plan["head"], False)
            run_standalone_extrusion_sequence(self.printer, sequence)
            if action == "unload":
                self._set_filament_loaded(plan["head"], False)
            else:
                if "service" in plan and self._sensor_filament_status(self.printer.get_reactor().monotonic())[plan["head"]]["state"] != "loaded":
                    raise ValueError("Filament sensor does not confirm loading")
                # Confirm loaded only after purge/wipe and final checks. A
                # stopped partial Load is present, but not ready for printing.
                self._filament_checkpoint("purging")
                self.filament_operation.update(message="Purging nozzle")
                run_standalone_extrusion_sequence(self.printer, "G1 E%g F400" % plan.get("purge_mm", 50.))
                self._record_hotend_material(plan["head"], plan["identity"], purged=True)
                if "service" in plan:
                    self._filament_checkpoint("wiping")
                    self.filament_operation.update(message="Wiping nozzle")
                    now = self.printer.get_reactor().monotonic()
                    th = self.printer.lookup_object("toolhead").get_status(now)
                    if (not self._filament_context_valid(plan, now)
                            or self._attachment(now) != {"state": "attached", "head": plan["head"]}
                            or th.get("extruder") != heater
                            or not all(axis in th.get("homed_axes", "") for axis in "xy")):
                        raise ValueError("Printer or attachment changed before wiping")
                    self.printer.lookup_object("gcode").run_script_from_command("WIPE_NOZZLE XY_ONLY=1\nM400")
            if plan.get("service", {}).get("return_head") is not None:
                self._filament_checkpoint("returning")
                self.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
                now = self.printer.get_reactor().monotonic()
                return_head = plan["service"]["return_head"]
                returning = self._service_context(return_head, now)
                for field, indices in (("positions", "dock_heads"), ("offsets", "offset_heads")):
                    if any(returning[field][index] != plan["service"][field][index]
                           for index in set(returning[indices]) | set(plan["service"][indices])):
                        raise ValueError("Calibration changed before returning the paused head")
                if returning["probe"] != plan["service"]["probe"]:
                    raise ValueError("Probe reference changed before returning the paused head")
                if returning["attachment"] != {"state": "attached", "head": plan["head"]}:
                    raise ValueError("Service head attachment changed before return")
                returning["restore_offset"] = plan["service"]["return_offset"]
                self._prepare_service(return_head, returning, phase_name="returning")
            self._filament_checkpoint("finishing")
            if "service" in plan:
                self.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
                if self.printer.lookup_object(heater).get_status(self.printer.get_reactor().monotonic()).get("target") != 0:
                    raise ValueError("Heater shutdown is not confirmed")
                if action == "load" and self._sensor_filament_status(self.printer.get_reactor().monotonic())[plan["head"]]["state"] != "loaded":
                    raise ValueError("Filament sensor does not confirm completion")
            self._set_filament_loaded(plan["head"], action == "load")
        except Exception as error:
            # A caught exception proves dispatch returned, not that queued moves
            # drained. Only release the UI for an operator check after M400.
            state = "unknown"
            try:
                self.printer.lookup_object("gcode").run_script_from_command("M400")
                state = "failed"
            except Exception:
                pass
            if "service" in plan or isinstance(error, FilamentCancelled):
                try:
                    self.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % ("extruder" if head == 0 else "extruder%d" % head))
                    if self.printer.lookup_object("extruder" if head == 0 else "extruder%d" % head).get_status(self.printer.get_reactor().monotonic()).get("target") != 0:
                        state = "unknown"
                except Exception:
                    state = "unknown"
            cancelled = isinstance(error, FilamentCancelled)
            self.filament_operation.update(state=state, cancelled=cancelled,
                message=("Cancelled; inspect filament before another operation" if cancelled and state == "failed" else
                         "Procedure interrupted; stopping and heater state need verification" if state == "unknown" else
                         str(error) + "; inspect filament before another operation"), error=str(error))
            raise
        if plan.get("pause_origin"):
            if not self._filament_context_valid(plan, self.printer.get_reactor().monotonic()):
                self.filament_operation.update(state="failed", message="Paused context changed at completion")
                raise gcmd.error("Paused context changed at completion")
            self._pause_origin["ready"] = action == "load"
        self.filament_operation.update(state="complete", message="Filament loaded." if action == "load" else "Filament unloaded. Please remove filament.")
        gcmd.respond_info(self.filament_operation["message"])

    @_status_observation
    def _attachment(self, eventtime):
        # An active Klipper extruder alone is not proof of an attached head.
        result = {"state": "unknown", "head": ""}
        def status(name):
            obj = self.printer.lookup_object(name, None)
            return obj.get_status(eventtime) if obj is not None else {}
        try:
            hall = status("custom_hall").get("Raw")
            lock = status("filament_switch_sensor sensor_b").get("filament_detected")
            docks = [status("filament_switch_sensor docked%d" % i).get("filament_detected") for i in range(4)]
            if not isinstance(hall, (int, float)) or not 3450 <= hall <= 6000:
                return result
            if any(type(d) is not bool for d in docks):
                return result
            if hall >= 4700 and lock is False and all(docks):
                return {"state": "empty", "head": ""}
            if hall < 4700 and lock is True and docks.count(False) == 1:
                return {"state": "attached", "head": "h%d" % docks.index(False)}
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
        return result

    def _screen_configuration_status(self, now):
        # The screen needs three fields per heater and four mapping values,
        # not the full macro configuration or saved-variable database.
        heaters = {}
        mapping = [None] * SLOTS
        try:
            settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
            for index in range(SLOTS):
                name = "extruder" + (str(index) if index else "")
                values = settings.get(name, {})
                heaters[name] = {key: values[key] for key in
                                 ("min_temp", "max_temp", "nozzle_diameter")
                                 if type(values.get(key)) in (int, float)
                                 and math.isfinite(values[key])}
        except (AttributeError, KeyError, TypeError):
            heaters = {}
        try:
            saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            mapping = [saved.get("box_modify_t%d" % i) for i in range(SLOTS)]
            mapping = [v if type(v) is int and 0 <= v < SLOTS else None for v in mapping]
        except (AttributeError, KeyError, TypeError):
            pass
        return {"screen_status_protocol": 1, "heater_settings": heaters,
                "physical_mapping": mapping}

    def _nozzle_status(self, now):
        result = {"nozzle_settings_protocol": 0, "nozzles": {},
                  "nozzle_save": dict(getattr(self, "nozzle_save", {}))}
        store = getattr(self, "_nozzles", None)
        if store is None:
            return result
        try:
            heads, revision = store.read()
            settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
            for head, values in heads.items():
                heater = "extruder" + (head[1] if head != "h0" else "")
                active = settings.get(heater, {}).get("nozzle_diameter")
                if type(active) not in (int, float) or not math.isfinite(active):
                    raise ValueError("Active nozzle diameter is unavailable")
                values["active_diameter"] = active
                values["restart_required"] = abs(active - values["diameter"]) > 0.000001
            result.update(nozzle_settings_protocol=1, nozzles=heads, nozzle_revision=revision)
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            result["nozzle_error"] = str(error)
        return result

    def cmd_SET_NOZZLE(self, gcmd):
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another filament manager owns nozzle settings")
        now = self.printer.get_reactor().monotonic()
        # These writes change saved configuration only; active heater geometry
        # is loaded at restart. Serialize with the actual head-config publisher,
        # not unrelated motion, a print, or a filament operation.
        if self._identification_pending(now):
            raise gcmd.error("Wait for head identification to finish before saving nozzle settings")
        if gcmd.get("SESSION") != self.session_id:
            raise gcmd.error("Printer session changed; reopen the nozzle editor")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        heater = "extruder" + (str(head) if head else "")
        if self.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        request = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request):
            raise gcmd.error("Invalid nozzle request ID")
        result = {"id": request, "session": self.session_id, "head": "h%d" % head}
        try:
            diameter = float(gcmd.get("DIAMETER"))
            material = gcmd.get_int("MATERIAL", minval=0, maxval=1)
            heads, revision = self._nozzles.save(head, diameter, wmp_nozzles.MATERIALS[material], gcmd.get("EXPECT"))
            result.update(state="complete", values=heads["h%d" % head], revision=revision)
            self.nozzle_save = result
            gcmd.respond_info("Nozzle settings saved; diameter changes take effect after a Klipper restart")
        except (OSError, ValueError) as error:
            result.update(state="failed", message=str(error))
            self.nozzle_save = result
            raise gcmd.error(str(error))

    def _legacy_profiles(self):
        """Project stock logical slots onto unambiguous physical heads."""
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return {}
        path = getattr(self, "ini_path", None)
        if not path:
            return {}
        try:
            with open(path, encoding="utf-8") as stream:
                text = stream.read(65537)
        except FileNotFoundError:
            return {}
        if len(text) > 65536:
            raise ValueError("Stock filament settings file is too large")
        ini = configparser.ConfigParser(interpolation=None)
        try:
            ini.read_string(text)
        except configparser.Error as error:
            raise ValueError("Invalid stock filament settings: " + str(error))
        if not ini.has_section("slot"):
            return {}
        saved = self.printer.lookup_object("save_variables", None)
        variables = saved.get_status(self.printer.get_reactor().monotonic()).get("variables", {}) if saved else {}
        colours = ("#ffffff", "#e7ceb5", "#714623", "#97999b", "#0c0809", "#49c5b1",
                   "#009cde", "#03257e", "#00b140", "#265b31", "#fce300", "#fe5000",
                   "#f5b6cd", "#e10098", "#cd001a", "#5f249f")
        custom_colours = {}
        section = ""
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().lower()
            match = re.fullmatch(r";\s*orca-color([0-3])\s*=\s*(#[0-9a-fA-F]{6})", line)
            if section == "slot" and match:
                custom_colours[int(match[1])] = match[2]
        profiles, ambiguous = {}, set()
        for slot in range(4):
            head = variables.get("box_modify_t%d" % slot, slot)
            if type(head) is not int or not 0 <= head < 4:
                continue
            key = "h%d" % head
            try:
                material = ini.getint("slot", "material%d" % slot)
                colour = ini.getint("slot", "color%d" % slot)
            except (ValueError, configparser.Error):
                continue
            rgb = custom_colours.get(slot, colours[colour] if 0 <= colour < len(colours) else None)
            if not 0 <= material < len(MATERIALS) or rgb is None:
                continue
            identity = {"brand": "Generic", "material": material_name(material), "color": rgb}
            if key in profiles and profiles[key] != identity:
                ambiguous.add(key)
            profiles[key] = identity
        return {key: value for key, value in profiles.items() if key not in ambiguous}

    @_status_observation
    def _profiles(self):
        # Polling is a read of the loaded profile, not a reload operation.
        # Explicit command admission still re-reads disk before comparing its
        # revision. Supported saves publish the new snapshot after commit.
        snapshot = getattr(self, '_status_profiles_snapshot', None)
        if getattr(self, '_status_observation_cache', None) is not None and snapshot is not None:
            return copy.deepcopy(snapshot)
        try:
            result = self._read_profiles()
        except Exception:
            self._status_profiles_snapshot = None
            raise
        self._status_profiles_snapshot = copy.deepcopy(result)
        return result

    def _read_profiles(self):
        try:
            with open(self.profile_path, "r", encoding="utf-8") as stream:
                text = stream.read(16385)
            if len(text) > 16384:
                raise ValueError("Filament settings file is too large")
        except FileNotFoundError:
            text = None
        legacy = self._legacy_profiles() if text is None else None
        cache_key = (text, legacy)
        # Read every time: external edits must invalidate admission revisions,
        # including same-size edits with unchanged timestamps. Cache only the
        # validation/serialization work, never the file or mutable caller data.
        cached = getattr(self, "_profiles_cache", None)
        if cached is not None and cached[0] == cache_key:
            self._profiles_raw = copy.deepcopy(cached[3])
            self._profile_entry_errors = copy.deepcopy(cached[4])
            return copy.deepcopy(cached[1]), cached[2]
        raw = legacy or {}
        if text is not None:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("Invalid filament settings file")
        profiles, errors = {}, {}
        for head, identity in raw.items():
            try:
                if head not in ("h0", "h1", "h2", "h3"):
                    raise ValueError("Invalid physical head in settings")
                self._validate_identity(identity)
            except ValueError as error:
                errors[head] = "%s: %s (entry preserved)" % (head, error)
            else:
                profiles[head] = identity
        # Bind Save to every entry, including unreadable entries. An unrelated
        # save must preserve those entries instead of silently dropping them.
        revision = hashlib.sha256(json.dumps(raw, sort_keys=True,
                                            ensure_ascii=True).encode()).hexdigest()
        self._profiles_raw = copy.deepcopy(raw)
        self._profile_entry_errors = errors
        self._profiles_cache = (copy.deepcopy(cache_key), copy.deepcopy(profiles), revision,
                                copy.deepcopy(raw), copy.deepcopy(errors))
        return profiles, revision

    @staticmethod
    def _validate_identity(identity):
        if not isinstance(identity, dict) or (not {"brand", "material", "color"}.issubset(identity) or set(identity) - {"brand", "material", "color", "nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"}):
            raise ValueError("Filament needs brand, material and color")
        for key in ("nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"):
            if key in identity and (type(identity[key]) not in (int, float) or not math.isfinite(identity[key]) or not 0 <= identity[key] <= (150 if key == "bed_temp" else 350)):
                raise ValueError("Invalid filament temperature")
        if identity.get("nozzle_temp_min", 0) > identity.get("nozzle_temp_max", 350):
            raise ValueError("Filament temperature minimum exceeds maximum")
        for field in ("brand", "material"):
            value = identity[field]
            if not isinstance(value, str) or not value.strip() or len(value) > 64 or any(ord(c) < 32 for c in value):
                raise ValueError("Invalid filament " + field)
        if not isinstance(identity["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", identity["color"]):
            raise ValueError("Color must be #RRGGBB")

    def cmd_CAPTURE_PAUSE(self, gcmd):
        # Called at the end of WM PAUSE. A failed capture must not unpause the
        # job or prevent the already-requested heater shutdown/parking.
        prior = getattr(self, "_pause_origin", None)
        if any(self.printer.lookup_object(owner, None) is not None
               for owner in ("openace", "AFC")):
            # Retained owner macros do not enter standalone capture. A direct
            # call must not replace or erase a prior standalone pause on handover.
            if prior:
                raise gcmd.error("Another manager owns paused filament service")
            return
        sd = self.printer.lookup_object("virtual_sdcard", None)
        current_file = getattr(sd, "current_file", None)
        same_job = (prior and prior.get("session") == self.session_id
                    and current_file is not None and not current_file.closed
                    and prior.get("file") is current_file)
        # Cancellation may leave an unfinished service record for a closed job.
        # It must not prevent capture of a later print's independent pause.
        if (self._material_operation_active("filament_operation")
                or (same_job and prior.get("serviced") and not prior.get("ready"))):
            raise gcmd.error("Cannot replace an unresolved filament-service pause")
        self._pause_origin = None
        try:
            now = self.printer.get_reactor().monotonic()
            if self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True:
                raise ValueError("Native pause is not established")
            sd = self.printer.lookup_object("virtual_sdcard")
            if sd.current_file is None or sd.current_file.closed:
                raise ValueError("No paused SD file")
            attachment = self._attachment(now)
            if attachment.get("state") != "attached":
                raise ValueError("Paused head attachment is unknown")
            head = attachment["head"]
            heater = "extruder" if head == "h0" else "extruder" + head[1:]
            if self.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
                raise ValueError("Paused head and active extruder disagree")
            saved = self.printer.lookup_object("gcode_move").saved_states
            if not all(name in saved for name in ("PAUSE", "PAUSEPARK")):
                raise ValueError("Paused return position is missing")
            self._pause_origin = {"id": uuid.uuid4().hex, "session": self.session_id,
                                  "head": head, "file": sd.current_file,
                                  "states": copy.deepcopy({name: saved[name] for name in ("PAUSE", "PAUSEPARK")}),
                                  "recipe": self._pause_recipe(now), "position": None,
                                  "offset": list(self.printer.lookup_object("gcode_move").get_status(now)["homing_origin"][:3]),
                                  "filament_required": sorted(self._job_filament_losses(sd.current_file))}
            self._pause_origin_error = ""
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self._pause_origin_error = str(error)
            gcmd.respond_info("Paused filament service unavailable: " + str(error))

    def _pause_recipe(self, now):
        variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        mapping = [variables["box_modify_t%d_backup" % i] for i in range(4)]
        if any(type(head) is not int or not 0 <= head < 4 for head in mapping):
            raise ValueError("Paused tool mapping is invalid")
        resume = self.printer.lookup_object("gcode_macro RESUME").get_status(now)
        keys = ["resume_temperature%d" % i for i in range(4)] + ["resume_bed", "zhop", "fan", "afan", "airfan"]
        recipe = {key: resume[key] for key in keys}
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in recipe.values()):
            raise ValueError("Paused resume settings are invalid")
        return {"mapping": mapping, "resume": recipe}

    def _paused_filament_origin(self, head, now):
        """Validate pause ownership; this alone never authorizes service motion."""
        fault = getattr(self, "_toolchange_pause", None)
        origin = self._fault_service_origin(now) if fault else getattr(self, "_pause_origin", None)
        if not origin or origin["session"] != self.session_id:
            raise ValueError("Pause context is unavailable; paused service cannot proceed")
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another manager owns paused filament service")
        sd = self.printer.lookup_object("virtual_sdcard")
        if (self.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                or self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True
                or sd.is_active() or sd.is_cmd_from_sd()):
            raise ValueError("Print is not fully paused")
        if sd.current_file is not origin["file"] or sd.current_file.closed:
            raise ValueError("Paused print file changed")
        # When PAUSE originated in the SD stream its line is accounted after
        # the macro returns. Bind the byte offset only once the worker stops.
        position = sd.file_position
        if type(position) is not int or position < 0:
            raise ValueError("Paused file position is invalid")
        if origin["position"] is None:
            origin["position"] = position
        if origin["position"] != position:
            raise ValueError("Paused file position changed")
        if origin.get("kind") != "toolchange":
            saved = self.printer.lookup_object("gcode_move").saved_states
            if any(saved.get(name) != value for name, value in origin["states"].items()):
                raise ValueError("Paused return position changed")
            self._pause_recipe(now)  # Validate current edits; the captured recipe is not a lease.
        if "h%d" % head not in set(origin.get("filament_required", [])) | {origin["head"]}:
            raise ValueError("Select the original paused head or a head that lost filament in this print")
        return {"id": origin["id"], "session": origin["session"],
                "head": origin["head"], "file_position": position}

    def _paused_filament_status(self, now):
        if getattr(self, "_toolchange_pause", None):
            try:
                self._fault_service_origin(now)
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                return {"available": False, "reason": str(error)}
        origin = getattr(self, "_pause_origin", None)
        if not origin:
            return {"available": False, "reason": "No captured pause context"}
        try:
            context = self._paused_filament_origin(int(origin["head"][1:]), now)
            attachment = self._attachment(now)
            if (attachment.get("state") != "attached" or attachment.get("head") not in
                    set(origin.get("filament_required", [])) | {origin["head"]}):
                raise ValueError("Paused head attachment changed")
            return {"available": True, "origin": context, "head": origin["head"],
                    "serviced": bool(origin.get("serviced")),
                    "wipe_completed": bool(origin.get("ready")),
                    "filament_required": sorted(set(origin.get("filament_required", [])) | {origin["head"]})}
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return {"available": False, "reason": str(error)}

    def _filament_context_valid(self, plan, now):
        self._filament_context_refusal = ''
        def refuse(reason):
            self._filament_context_refusal = reason[:256]
            return False
        if plan.get("command_generation", 0) != getattr(self, "_command_generation", 0):
            return refuse('command generation changed after admission')
        if self._print_cancel_active(): return refuse('print cancellation is unresolved')
        origin = plan.get("pause_origin")
        if not origin:
            if self._idle_for_filament_settings(now): return True
            return refuse(getattr(self, '_idle_settings_refusal', '') or 'idle admission was not confirmed')
        try:
            if self._paused_filament_origin(int(plan["head"][1:]), now) == origin: return True
            return refuse('paused filament origin differs from admitted origin')
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return refuse('paused filament origin unavailable: ' + type(error).__name__ + ': ' + str(error)[:160])

    def cmd_CHECK_SCRIPT_GENERATION(self, gcmd):
        allow_hold = gcmd.get_int("ALLOW_HOLD", minval=0, maxval=1) == 1
        self._check_command_generation(gcmd, allow_hold)

    def cmd_CHECK_COMMAND_GENERATION(self, gcmd):
        self._check_command_generation(gcmd)

    def _check_command_generation(self, gcmd, allow_cancel_hold=False):
        # Prefix to the same run_script RPC as the command. Vendor dispatch
        # aborts the remaining script on command error, while holding its mutex.
        generation = gcmd.get_int("GENERATION", minval=0, maxval=9223372036854775807)
        if (gcmd.get("SESSION") != self.session_id
                or generation != getattr(self, "_command_generation", 0)
                or (not allow_cancel_hold and self._print_cancel_active())):
            raise gcmd.error("Command invalidated by cancellation or restart; review again")
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Standalone command owner changed")

    def _retire_changed_print_recovery(self, gcmd=None, record=None):
        """Retire optional evidence after a proven edit, never hold resume.

        Backup mapping is the user's resume mapping. Current mapping and
        missing sensor evidence may be transient during tool/service work and
        are deliberately not treated as proof that the job recipe changed.
        """
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return False
        try:
            if record is None:
                record = self._read_recovery_job()
            if record.get("state") != "committed" or record.get("owner") != "standalone":
                return False
            sd = self.printer.lookup_object("virtual_sdcard")
            self._recovery_active_file(sd, {key: record["file"][key]
                                           for key in ("path", "size", "modified")})
            now = self.printer.get_reactor().monotonic()
            variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            mapping = [variables.get("box_modify_t%d_backup" % i) for i in range(4)]
            reason = ""
            if (all(type(head) is int and head in range(4) for head in mapping)
                    and mapping != record["mapping"]):
                reason = "Print mapping changed after the saved recovery checkpoint"
            loaded = self._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                current = loaded.get(key, {})
                if (current.get("state") == "loaded" and isinstance(current.get("identity"), dict)
                        and isinstance(current.get("source"), str)
                        and not self._loaded_source_matches(current, saved)):
                    reason = "Loaded material identity changed after the saved recovery checkpoint"
                    break
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Unavailable evidence is not proof of a user edit and cannot
            # prohibit normal resume. Recovery performs its own full review.
            return False
        if not reason:
            return False
        self._disable_print_recovery(reason)
        if gcmd is not None:
            gcmd.respond_info(reason + ". Printing can continue without power-loss recovery.")
        return True

    def _observe_resume(self, execute, phase="checking"):
        """Read-only progress for the command lifetime; never an admission flag."""
        if (getattr(self, "_resume_progress", None)
                or any(self.printer.lookup_object(owner, None) is not None
                       for owner in ("openace", "AFC"))):
            return execute()
        self._resume_progress = {"phase": phase}
        try:
            if self._toolchange_pause_status():
                self._resume_progress["phase"] = "toolchange"
            return execute()
        finally:
            # Includes refusal, cancellation, shutdown and nested M24 exits.
            self._resume_progress = {}

    def _resume_phase(self, phase):
        progress = getattr(self, "_resume_progress", None)
        if progress and progress.get("phase") != "toolchange":
            progress["phase"] = phase

    def cmd_CHECK_RESUME(self, gcmd):
        try:
            self._require_no_recovery_attempt()
            paused_worker = getattr(self, "_recovery_paused_worker", None)
            if paused_worker is not None:
                paused_worker["validate"]()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise gcmd.error(str(error))
        if any(self.printer.lookup_object(owner, None) is not None
               for owner in ("openace", "AFC")):
            if getattr(self, "_pause_origin", None):
                raise gcmd.error("Another manager owns paused filament service")
            return
        now = self.printer.get_reactor().monotonic()
        try:
            sd = self.printer.lookup_object("virtual_sdcard")
            if (self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True
                    or self.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                    or sd.is_active() or sd.is_cmd_from_sd()):
                raise ValueError("Wait for the print to finish pausing before resuming")
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error(str(error))
        if self._material_operation_active("toolhead_operation"):
            raise gcmd.error("Finish or recover the toolhead operation before resuming")
        operation = self.filament_operation
        if self._material_operation_active("filament_operation"):
            raise gcmd.error("Finish or recover filament service before resuming")
        origin = getattr(self, "_pause_origin", None)
        if not origin:
            # Ordinary stock pauses need no WM+ service receipt. A confirmed
            # loss in this open job still requires the user's reload/check.
            loaded = self._loaded_filament_status(now)
            for head in sorted(self._job_filament_losses(sd.current_file)):
                if loaded.get(head, {}).get("state") != "loaded":
                    raise gcmd.error("Load filament in Head %d before resuming" % (int(head[1:]) + 1))
            self._retire_changed_print_recovery(gcmd)
            self._resume_phase("heating")
            return
        try:
            now = self.printer.get_reactor().monotonic()
            self._paused_filament_origin(int(origin["head"][1:]), now)
            if origin.get("serviced") and not origin.get("ready"):
                raise ValueError("Complete filament loading before resuming")
            if self._attachment(now) != {"state": "attached", "head": origin["head"]}:
                raise ValueError("Mount the original paused head before resuming")
            heater = "extruder" if origin["head"] == "h0" else "extruder" + origin["head"][1:]
            if self.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
                raise ValueError("Active extruder does not match the paused head")
            path_sensor = self.printer.lookup_object(
                "filament_switch_sensor path_" + origin["head"][1:], None)
            if path_sensor is not None:
                path = path_sensor.get_status(now)
                if path.get("enabled") is not False and path.get("filament_detected") is not True:
                    raise ValueError("Untangle filament for Head %d before resuming" % (int(origin["head"][1:]) + 1))
            loaded = self._loaded_filament_status(now)
            required = set(origin.get("filament_required", []))
            if origin.get("serviced"):
                required.add(origin["head"])
            for head in sorted(required):
                if loaded.get(head, {}).get("state") != "loaded":
                    raise ValueError("Load filament in Head %d before resuming" % (int(head[1:]) + 1))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error(str(error))
        self._retire_changed_print_recovery(gcmd)
        self._resume_phase("heating")

    def cmd_PREPARE_RESUME_E(self, gcmd):
        """Validate parser correction before the return move, not at the part."""
        self._resume_e_correction = None
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            raise gcmd.error("Another manager owns paused filament service")
        self.cmd_CHECK_RESUME(gcmd)
        self._resume_phase("returning")
        origin = getattr(self, "_pause_origin", None)
        # Manual state-preserving extrusion can also change the vendor E base.
        # Restore every captured pause; serviced only governs load/wipe policy.
        if not origin:
            return
        try:
            saved = origin["states"]["PAUSE"]
            factor = float(saved["extrude_factor"])
            logical_e = (float(saved["last_position"][3]) - float(saved["base_position"][3])) / factor
            if not math.isfinite(logical_e) or not math.isfinite(factor) or factor <= 0:
                raise ValueError("Invalid saved extrusion coordinate")
        except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError) as error:
            raise gcmd.error("Cannot prepare paused extrusion coordinate: " + str(error))
        self._resume_e_correction = logical_e

    def cmd_RESTORE_RESUME_E(self, gcmd):
        # The macro prepared this before any return motion. Do not fail a
        # completed return on a new sensor poll, recipe edit or UI state.
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            raise gcmd.error("Another manager owns paused filament service")
        logical_e = getattr(self, "_resume_e_correction", None)
        self._resume_e_correction = None
        if logical_e is not None:
            self.printer.lookup_object("gcode").run_script_from_command("G92 E%.17g" % logical_e)

    @_status_observation
    def _identification_pending(self, now):
        recovery = self.printer.lookup_object("wmp_recovery", None)
        if recovery is None:
            return False
        try:
            return recovery.get_status(now).get("identification", {}).get("state", "idle") in ("pending", "running")
        except (AttributeError, KeyError, TypeError, ValueError):
            return True

    def _idle_for_filament_settings(self, now, allow_invalid_recovery=False):
        # Availability callers stay silent; command boundaries append this
        # bounded observation when the same admission check refuses a request.
        self._idle_settings_refusal = ''
        def refuse(reason):
            self._idle_settings_refusal = reason[:256]
            return False
        if self._print_cancel_active(): return refuse('print cancellation is unresolved')
        if self._recovery_attempt_active():
            return refuse('power-loss recovery attempt is unresolved')
        # A completed print_stats state does not overrule pause or SD ownership.
        try:
            if self._identification_pending(now):
                return refuse('head identification is pending or its status is unavailable')
            stats = self.printer.lookup_object("print_stats", None).get_status(now)
            pause = self.printer.lookup_object("pause_resume", None).get_status(now)
            sd = self.printer.lookup_object("virtual_sdcard", None)
            stopped = ("standby", "complete", "cancelled")
            if not any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
                stopped += ("error",)
            if stats.get("state") not in stopped:
                return refuse('print_stats.state=' + repr(stats.get('state'))[:80])
            if pause.get("is_paused") is not False:
                return refuse('pause_resume.is_paused=' + repr(pause.get('is_paused'))[:80])
            active = sd.is_active()
            if active is not False: return refuse('virtual_sdcard.is_active=' + repr(active)[:80])
            from_sd = sd.is_cmd_from_sd()
            if from_sd is not False: return refuse('virtual_sdcard.is_cmd_from_sd=' + repr(from_sd)[:80])
            return True
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return refuse('idle status evidence unavailable: ' + type(error).__name__ + ': ' + str(error)[:160])

    @staticmethod
    def _filament_recipe(identity):
        """Physical recipe comparison; labels never establish spool changes."""
        return {key: copy.deepcopy(value) for key, value in identity.items()
                if key not in ("brand", "color")}

    @classmethod
    def _loaded_source_matches(cls, current, saved):
        if (current.get("state") != "loaded" or current.get("source") != saved.get("source")
                or not isinstance(current.get("identity"), dict)
                or not isinstance(saved.get("identity"), dict)):
            return False
        cls._validate_identity(current["identity"])
        cls._validate_identity(saved["identity"])
        return cls._filament_recipe(current["identity"]) == cls._filament_recipe(saved["identity"])

    def _profile_recipes(self, heads=None):
        profiles = self._profiles()[0]
        selected = profiles if heads is None else heads
        return {head: self._filament_recipe(profiles[head]) if head in profiles else None
                for head in selected}

    @staticmethod
    def _usage_file_identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _usage_mapping(self, now):
        values = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        maps = tuple(tuple(values.get("box_modify_t%d%s" % (i, suffix)) for i in range(4))
                     for suffix in ("", "_backup"))
        if any(type(h) is not int or h not in range(4) for row in maps for h in row):
            raise ValueError("Complete current and saved tool mapping is unavailable")
        return maps

    def _usage_macros(self, now):
        settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
        return {name: settings.get('gcode_macro ' + name.lower(), {}).get('gcode')
                for name in wmp_recovery_file_envelope.MACROS}

    def _begin_usage_scan(self, path):
        self._recipe_usage_observation = None
        try:
            now = self.printer.get_reactor().monotonic()
            return {"scanner": wmp_recovery_file_envelope.ToolUsage(),
                    "session": self.session_id, "path": os.path.realpath(path),
                    "identity": self._usage_file_identity(os.stat(path)),
                    "mapping": self._usage_mapping(now), "proof": self._recovery_file_effect_contract(),
                    "macros": self._usage_macros(now)}
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_error = str(error)
            return None

    def _finish_usage_scan(self, scan, digest, stream=None):
        if scan is None: return
        try:
            now = self.printer.get_reactor().monotonic()
            tools = scan["scanner"].complete()
            if (self.session_id != scan["session"]
                    or self._usage_mapping(now) != scan["mapping"]
                    or self._usage_macros(now) != scan["macros"]
                    or self._usage_file_identity(os.stat(scan["path"])) != scan["identity"]):
                raise ValueError("File, macro effects or tool mapping changed during usage scan")
            if stream is not None and self._usage_file_identity(os.fstat(stream.fileno())) != scan["identity"]:
                raise ValueError("Active SD stream differs from scanned file")
            self._recipe_usage_observation = {key: value for key, value in scan.items() if key != "scanner"}
            self._recipe_usage_observation.update(tools=tuple(tools), sha256=digest, stream=stream)
            self._recipe_usage_error = ""
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_observation = None
            self._recipe_usage_error = str(error)

    def _bind_usage_stream(self):
        """Bind a pre-dispatch scan to the actual opened SD file, never by name alone."""
        observed = getattr(self, "_recipe_usage_observation", None)
        if not observed or observed.get("stream") is not None: return
        try:
            stream = self.printer.lookup_object("virtual_sdcard").current_file
            if (stream is None or stream.closed or os.path.realpath(stream.name) != observed["path"]
                    or self._usage_file_identity(os.fstat(stream.fileno())) != observed["identity"]
                    or self._usage_file_identity(os.stat(observed["path"])) != observed["identity"]):
                raise ValueError("Opened SD file differs from admitted usage scan")
            observed["stream"] = stream
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_observation = None
            self._recipe_usage_error = str(error)

    def _active_recipe_heads(self, now, check_file=False):
        """No filesystem operations during status; final Save checks file identity."""
        observed = getattr(self, "_recipe_usage_observation", None)
        try:
            if not observed: raise ValueError(getattr(self, "_recipe_usage_error", "Complete active-job head usage is unavailable"))
            stream = self.printer.lookup_object("virtual_sdcard").current_file
            if (stream is None or stream.closed or stream is not observed["stream"]
                    or observed["session"] != self.session_id
                    or self._usage_mapping(now) != observed["mapping"]
                    or self._usage_macros(now) != observed["macros"]):
                raise ValueError("Active file, session, mapping or macro effects changed")
            if check_file and (self._usage_file_identity(os.fstat(stream.fileno())) != observed["identity"]
                    or self._usage_file_identity(os.stat(observed["path"])) != observed["identity"]):
                raise ValueError("Active print file changed since tool usage was established")
            return {"h%d" % observed["mapping"][0][tool] for tool in observed["tools"]}
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_error = str(error)
            return None

    def _unused_recipe_head(self, head, now, check_file=False):
        if self._print_cancel_active() or self._recovery_attempt_active(): return False
        used = self._active_recipe_heads(now, check_file)
        return used is not None and "h%d" % head not in used

    def _recipe_write_status(self, now):
        result = {}
        identifying = self._identification_pending(now)
        idle = self._idle_for_filament_settings(now)
        active = self._material_operation_active("filament_operation")
        affected = getattr(self, "filament_operation", {}).get("head")
        used = self._active_recipe_heads(now) if not idle else None
        for head in range(4):
            key = "h%d" % head
            allowed = (not identifying and not (active and (affected == key or affected not in ('h0','h1','h2','h3')))
                       and (idle or (not self._print_cancel_active() and not self._recovery_attempt_active()
                                     and used is not None and key not in used)))
            reason = ("Head identification is running" if identifying else
                      "Active filament service uses this head or its head is unknown" if active and (affected == key or affected not in ('h0','h1','h2','h3')) else
                      "Print cancellation is running" if self._print_cancel_active() else
                      "Print recovery is running" if self._recovery_attempt_active() else
                      "This print uses this head; use the paused empty-head editor" if used is not None and key in used else
                      getattr(self, "_recipe_usage_error", "Active-job head usage is unavailable"))
            result[key] = {"allowed": bool(allowed), "reason": "" if allowed else reason}
        return result

    def cmd_SET_FILAMENT(self, gcmd):
        if self._identification_pending(self.printer.get_reactor().monotonic()):
            raise gcmd.error("Resolve head identification before editing filament")
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another manager owns filament settings")
        eventtime = self.printer.get_reactor().monotonic()
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        try:
            encoded = gcmd.get("PROFILE")
            if len(encoded) > 1024 or not re.fullmatch(r"[0-9a-fA-F]+", encoded):
                raise ValueError("Invalid encoded filament settings")
            identity = json.loads(bytes.fromhex(encoded).decode("utf-8"))
            self._validate_identity(identity)
            profiles, revision = self._profiles()
            if gcmd.get("EXPECT") != revision:
                raise ValueError("Filament settings changed; refresh before saving")
            previous = profiles.get("h%d" % head)
            cosmetic = (previous is not None and
                        self._filament_recipe(previous) == self._filament_recipe(identity))
            if not cosmetic:
                if self._material_operation_active("filament_operation"):
                    active_head = self.filament_operation.get("head")
                    if active_head not in ("h0", "h1", "h2", "h3"):
                        raise gcmd.error("Cannot establish which head the active filament operation uses; wait for it to finish before changing the recipe")
                    if active_head == "h%d" % head:
                        raise gcmd.error("Head %d has an active filament operation; wait before changing its recipe" % (head + 1))
                pause_token = gcmd.get("PAUSE", None)
                if self._unused_recipe_head(head, eventtime, check_file=True):
                    pass
                elif self._idle_for_filament_settings(eventtime):
                    if pause_token is not None:
                        raise gcmd.error("Paused edit expired; refresh before saving")
                else:
                    if pause_token is None:
                        reason = (self._recipe_write_status(eventtime)["h%d" % head]["reason"]
                                  or getattr(self, "_recipe_usage_error", "Active-job file binding changed"))
                        raise gcmd.error("Filament recipe Save requires idle, an unused active-job head or the paused-head editor: " + reason)
                    try:
                        origin = self._paused_filament_origin(head, eventtime)
                        if pause_token != origin["id"]:
                            raise ValueError("Paused edit context changed")
                        if not self._paused_filament_status(eventtime).get("available"):
                            raise ValueError("Paused head attachment changed")
                        if self._loaded_filament_status(eventtime).get("h%d" % head, {}).get("state") != "empty":
                            raise ValueError("Unload the paused head before changing filament settings")
                    except (AttributeError, KeyError, TypeError, ValueError) as error:
                        raise gcmd.error(str(error))
            profiles = copy.deepcopy(getattr(self, "_profiles_raw", profiles))
            profiles["h%d" % head] = identity
            parent = os.path.dirname(self.profile_path)
            temporary = None
            self._status_profiles_snapshot = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent,
                                                 prefix=".wmp-filaments-", delete=False) as stream:
                    temporary = stream.name
                    json.dump(profiles, stream, sort_keys=True, ensure_ascii=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.profile_path)
                temporary = None
                directory = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if temporary is not None:
                    os.unlink(temporary)
            self._status_profiles_snapshot = None
            self._profiles()
        except (ValueError, OSError, UnicodeError) as error:
            raise gcmd.error(str(error))
        gcmd.respond_info("Filament settings saved for head %d" % (head + 1))

    def _clear_filament_checks(self, *args):
        self._toolchange_pause = None
        if getattr(self, "_pause_origin", None) and self._pause_origin.get("kind") == "toolchange":
            self._pause_origin = None
        self._filament_checks.clear()
        self._recovery_release_paused_worker()

    def _filament_sensors_ready(self):
        # Match Klipper RunoutHelper's initial two-second settling window.
        self._filament_sensors_ready_at = self.printer.get_reactor().monotonic() + 2.
        self._guard_filament_notifications()

    def _guard_filament_notifications(self):
        # The vendor emits its error before checking whether a print needs this
        # sensor. Guard only that notification, not sensor updates or callbacks.
        guarded = getattr(self, "_guarded_filament_notifications", set())
        self._guarded_filament_notifications = guarded
        for head in range(4):
            for name in ("filament%d" % head, "path_%d" % head):
                sensor = self.printer.lookup_object("filament_switch_sensor " + name, None)
                helper = getattr(sensor, "runout_helper", None)
                original = getattr(helper, "_respond_runout_error", None)
                if not callable(original) or name in guarded:
                    continue
                def notify(original=original, head=head, name=name):
                    if any(self.printer.lookup_object(owner, None) is not None
                           for owner in ("openace", "AFC")):
                        return original()
                    now = self.printer.get_reactor().monotonic()
                    stats = self.printer.lookup_object("print_stats").get_status(now)
                    pause = self.printer.lookup_object("pause_resume").get_status(now)
                    if stats.get("state") == "printing" and self._runout_pause_needed(pause):
                        attachment = self._attachment(now)
                        if attachment == {"state": "attached", "head": "h%d" % head}:
                            return original()
                        if attachment.get("state") == "unknown":
                            # Report the actual sensor without inventing which
                            # head is attached or changing pause admission.
                            self.printer.lookup_object("gcode").respond_info(
                                "Filament sensor %s reported empty; attached head is unknown. "
                                "Check head attachment and filament." % name)
                helper._respond_runout_error = notify
                # Path sensors use the vendor's immediate pause callback. Unlike
                # filament runout macros, it does not recheck the required head.
                event = getattr(helper, "_runout_event_handler", None)
                if name.startswith("path_") and callable(event):
                    def path_event(eventtime, original=event, helper=helper, head=head):
                        if any(self.printer.lookup_object(owner, None) is not None
                               for owner in ("openace", "AFC")):
                            return original(eventtime)
                        now = self.printer.get_reactor().monotonic()
                        stats = self.printer.lookup_object("print_stats").get_status(now)
                        pause = self.printer.lookup_object("pause_resume").get_status(now)
                        if (helper.sensor_enabled and not helper.filament_present
                                and stats.get("state") == "printing" and self._runout_pause_needed(pause)
                                and self._attachment(now) == {"state": "attached", "head": "h%d" % head}):
                            return original(eventtime)
                        # note_filament_present set NEVER when it queued this
                        # callback. Release that gate even when no pause is due.
                        helper.min_event_systime = now + helper.event_delay
                        if helper.sensor_enabled and not helper.filament_present and stats.get("state") == "printing":
                            self._defer_path_runout(helper, head, original)
                    helper._runout_event_handler = path_event
                guarded.add(name)

    def _runout_pause_needed(self, pause):
        if pause.get("is_paused") is False:
            return True
        sd = self.printer.lookup_object("virtual_sdcard", None)
        return sd is not None and sd.is_active()

    def _defer_path_runout(self, helper, head, original):
        """Retain a tangle across a transient head change, scoped to this file."""
        sd = self.printer.lookup_object("virtual_sdcard", None)
        stream = getattr(sd, "current_file", None)
        if stream is None or stream.closed:
            return
        reactor = self.printer.get_reactor()
        pending = getattr(self, "_deferred_path_runouts", {})
        self._deferred_path_runouts = pending
        if pending.get(head) is stream:
            return
        pending[head] = stream
        def retry(now):
            if pending.get(head) is not stream:
                return reactor.NEVER
            stats = self.printer.lookup_object("print_stats").get_status(now)
            pause = self.printer.lookup_object("pause_resume").get_status(now)
            if (getattr(sd, "current_file", None) is not stream or stream.closed
                    or not helper.sensor_enabled or helper.filament_present
                    or stats.get("state") != "printing"
                    or any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))):
                pending.pop(head, None)
                return reactor.NEVER
            if self._runout_pause_needed(pause) and self._attachment(now) == {"state": "attached", "head": "h%d" % head}:
                pending.pop(head, None)
                original(now)
                return reactor.NEVER
            return now + .25
        reactor.register_timer(retry, reactor.monotonic() + .25)

    def _filament_sensors_unavailable(self):
        self._filament_sensors_ready_at = float("inf")
        self._pending_execution_snapshot = None

    @_status_observation
    def _hotend_material_history(self):
        self._hotend_history_error = ""
        try:
            return self._read_hotend_material_history()
        except (ValueError, UnicodeError, OSError) as error:
            self._hotend_history_error = "Hotend history unavailable; residue is unknown: " + str(error)
            return {}

    def _read_hotend_material_history(self):
        """Residual material history, independent of presence and spool edits.

        Missing history is unknown, never inferred from current spool settings.
        Corrupt history is preserved by the writer; readers use unknown residue.
        """
        path = os.path.join(os.path.dirname(self.profile_path), "wmp_hotend_materials.json")
        try:
            with open(path, encoding="utf-8") as stream:
                text = stream.read(32769)
            if len(text) > 32768:
                raise ValueError("Hotend material history is too large")
            data = json.loads(text)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or set(data) != {"version", "heads"} or data["version"] != 1:
            raise ValueError("Invalid hotend material history")
        heads = data["heads"]
        if not isinstance(heads, dict):
            raise ValueError("Invalid hotend material heads")
        for head, record in heads.items():
            if head not in ("h0", "h1", "h2", "h3") or not isinstance(record, dict):
                raise ValueError("Invalid hotend material head")
            if (set(record) != {"state", "materials", "unknown_residue"}
                    or record["state"] not in ("mixed", "purged")
                    or type(record["unknown_residue"]) is not bool
                    or not isinstance(record["materials"], list)
                    or not 1 <= len(record["materials"]) <= 8):
                raise ValueError("Invalid hotend material record")
            if record["state"] == "purged" and (len(record["materials"]) != 1 or record["unknown_residue"]):
                raise ValueError("Invalid purged hotend material record")
            for identity in record["materials"]:
                self._validate_identity(identity)
        return heads

    def _record_hotend_material(self, head, identity, purged):
        if head not in ("h0", "h1", "h2", "h3"):
            raise ValueError("Invalid hotend material head")
        self._validate_identity(identity)
        heads = self._hotend_material_history()
        previous = heads.get(head)
        materials = copy.deepcopy(previous["materials"]) if previous and not purged else []
        unknown = not purged and (previous is None or previous["unknown_residue"])
        if identity not in materials:
            materials.append(copy.deepcopy(identity))
        if len(materials) > 8:
            materials = materials[-8:]
            unknown = True
        heads[head] = {"state": "purged" if purged else "mixed",
                       "materials": materials, "unknown_residue": unknown}
        parent = os.path.dirname(self.profile_path)
        path = os.path.join(parent, "wmp_hotend_materials.json")
        if getattr(self, "_hotend_history_error", ""):
            # Only a deliberate material operation may replace bad history.
            # Preserve the exact inode bytes before atomic replacement; reads
            # never repair files. If preservation is impossible, retain unknown
            # history rather than destroying evidence or blocking the printer.
            try:
                os.link(path, path + ".invalid-" + uuid.uuid4().hex)
            except OSError as error:
                logging.warning("Hotend history was not updated: cannot preserve original: %s", error)
                return
        fd, temporary = tempfile.mkstemp(prefix=".wmp-hotend-", dir=parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"version": 1, "heads": heads}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _load_filament_flags(self):
        if not hasattr(self, "_loaded_flags"):
            path = os.path.join(os.path.dirname(self.profile_path), "wmp_filament_loaded.json")
            try:
                with open(path) as stream:
                    values = json.load(stream)
                self._loaded_flags = {"h%d" % i: values.get("h%d" % i) is True for i in range(4)}
            except (OSError, ValueError, AttributeError):
                self._loaded_flags = {}
        return self._loaded_flags

    def _set_filament_loaded(self, head, loaded):
        self._presence_adopted = True  # An explicit load/unload supersedes migration.
        flags = dict(self._load_filament_flags())
        if flags.get(head, False) == loaded:
            return
        flags[head] = loaded
        self._persist_filament_flags(flags)

    def _persist_filament_flags(self, flags):
        try:
            self._write_filament_flags(flags)
            self._filament_presence_error = ""
        except OSError as error:
            # Presence is a current observation even when optional persistence
            # fails. Do not retry the same write from every status publication.
            self._loaded_flags = dict(flags)
            message = str(error)[:256]
            if getattr(self, "_filament_presence_error", "") != message:
                logging.warning("Filament presence persistence unavailable: %s", message)
            self._filament_presence_error = message

    def _write_filament_flags(self, flags):
        parent = os.path.dirname(self.profile_path)
        path = os.path.join(parent, "wmp_filament_loaded.json")
        fd, temporary = tempfile.mkstemp(prefix=".wmp-loaded-", dir=parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(flags, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self._loaded_flags = flags
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _job_filament_losses(self, current_file):
        loss = getattr(self, "_filament_loss_job", None)
        if loss and loss["file"] is current_file and not current_file.closed:
            return set(loss["heads"])
        return set()

    def _record_job_filament_loss(self, head, eventtime):
        # An inlet transition clears the loaded flag permanently. Retain which
        # head lost its confirmed load even if a queued tool change finishes
        # before PAUSE captures the mounted head. Bind to the open file object,
        # never a reusable filename, and never infer a reload from reinsertion.
        if self.printer.lookup_object("openace", None) is not None:
            return
        stats = self.printer.lookup_object("print_stats", None)
        sd = self.printer.lookup_object("virtual_sdcard", None)
        if stats is None or sd is None:
            return
        current_file = getattr(sd, "current_file", None)
        if (stats.get_status(eventtime).get("state") not in ("printing", "paused")
                or current_file is None or current_file.closed):
            return
        heads = self._job_filament_losses(current_file) | {head}
        self._filament_loss_job = {"file": current_file, "heads": heads}
        origin = getattr(self, "_pause_origin", None)
        if origin and origin["file"] is current_file and origin["session"] == self.session_id:
            origin["filament_required"] = sorted(set(origin.get("filament_required", [])) | heads)

    @_status_observation
    def _loaded_filament_status(self, eventtime):
        records = self._sensor_filament_status(eventtime)
        # First-install adoption only. Once WM+ has saved presence (including
        # all-empty), reinsertion must never silently become a completed load.
        loaded_path = os.path.join(os.path.dirname(self.profile_path), "wmp_filament_loaded.json")
        if (not os.path.exists(loaded_path) and not getattr(self, "_presence_adopted", False)
                and self._idle_for_filament_settings(eventtime)
                and not any(getattr(self, name, {}).get("state") in ("running", "unknown")
                            for name in ("filament_operation", "toolhead_operation"))):
            try:
                # Reuse the loaded catalogue or stock projection. An existing
                # catalogue does not mean presence migration already happened.
                legacy, _ = self._profiles()
            except (OSError, ValueError):
                legacy = {}
            if legacy and all(records[head]["state"] in ("loaded", "empty") for head in legacy):
                self._persist_filament_flags({head: head in legacy and record["state"] == "loaded"
                                              for head, record in records.items()})
                self._presence_adopted = True
        empty_since = getattr(self, "_filament_empty_since", {})
        self._filament_empty_since = empty_since
        for head, record in records.items():
            present = record["state"] == "loaded"
            record["sensor_present"] = present if record["state"] != "unknown" else None
            if record["state"] == "empty":
                sd = self.printer.lookup_object("virtual_sdcard", None)
                stream = getattr(sd, "current_file", None)
                began, job = empty_since.setdefault(head, (eventtime, stream))
                if job is not stream:
                    began = eventtime
                    empty_since[head] = (began, stream)
                if eventtime - began >= .25:
                    if self._load_filament_flags().get(head, False):
                        self._record_job_filament_loss(head, eventtime)
                    self._set_filament_loaded(head, False)
            else:
                empty_since.pop(head, None)
                if present and not self._load_filament_flags().get(head, False):
                    record["state"] = "empty"
                    record.pop("identity", None)
                    record.pop("source", None)
        return records

    @_status_observation
    def _sensor_filament_status(self, eventtime):
        """Physical presence is live evidence, independent of saved/operator state.

        enabled controls runout handling, not whether the switch is readable.
        Metadata describes the configured spool; it cannot prove its identity.
        """
        try:
            profiles, _ = self._profiles()
        except (ValueError, OSError):
            profiles = {}
        result = {}
        for i in range(4):
            sensor = self.printer.lookup_object("filament_switch_sensor filament%d" % i, None)
            observed = sensor.get_status(eventtime) if sensor is not None else {}
            detected = observed.get("filament_detected")
            if eventtime < getattr(self, "_filament_sensors_ready_at", 0.):
                detected = None
            key = "h%d" % i
            record = {"state": "unknown", "evidence": "sensor", "session": self.session_id}
            if type(detected) is bool:
                record["state"] = "loaded" if detected else "empty"
                if detected:
                    record.update(source="external:" + key, identity=dict(profiles.get(key, {})))
            result[key] = record
        return result

    def _filament_check_context(self, head, now):
        """A check records current evidence; it never runs a filament procedure."""
        self._require_no_recovery_attempt()
        if self._identification_pending(now):
            raise ValueError("Wait for the running head identification before checking filament")
        if any(getattr(self, name, {}).get("state") in ("pending", "running")
               for name in ("filament_operation", "toolhead_operation")):
            raise ValueError("Wait for the running filament or toolhead operation before checking filament")
        if self._idle_for_filament_settings(now):
            return
        # Permit a stopped paused job's original/affected head. This validates
        # the current pause, not a historic load/unload receipt.
        self._paused_filament_origin(head, now)

    def _filament_status(self, eventtime):
        checks = self._filament_checks
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            checks.clear()
        for head, record in list(checks.items()):
            try:
                self._filament_check_context(int(head[1]), eventtime)
            except (AttributeError, KeyError, TypeError, ValueError):
                del checks[head]
                continue
            sensor = self.printer.lookup_object("filament_switch_sensor filament%d" % int(head[1]), None)
            observed = sensor.get_status(eventtime) if sensor is not None else {}
            # enabled controls runout handling, not switch readability.
            if observed.get("filament_detected") is not (record["state"] == "loaded"):
                del checks[head]
        return {head: dict(record) for head, record in checks.items()}

    def cmd_FORGET_FILAMENT(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        self._filament_checks.pop("h%d" % head, None)

    def cmd_CONFIRM_FILAMENT(self, gcmd):
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another manager owns filament evidence")
        now = self.printer.get_reactor().monotonic()
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        try:
            self._filament_check_context(head, now)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error("Filament check requires idle or a fully paused affected head: " + str(error))
        key = "h%d" % head
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        state = gcmd.get("STATE")
        if state not in ("loaded", "empty") or gcmd.get("SESSION") != self.session_id:
            raise gcmd.error("Invalid filament check or stale printer session")
        try:
            profiles, revision = self._profiles()
            if gcmd.get("EXPECT") != revision or key not in profiles:
                raise ValueError("Filament settings changed or are missing; refresh before confirming")
        except (ValueError, OSError) as error:
            raise gcmd.error(str(error))
        sensor = self.printer.lookup_object("filament_switch_sensor filament%d" % head, None)
        observed = sensor.get_status(now) if sensor is not None else {}
        if (now < getattr(self, "_filament_sensors_ready_at", 0.)
                or observed.get("filament_detected") is not (state == "loaded")):
            raise gcmd.error("The head sensor disagrees or is unavailable; check the filament first")
        # This is explicitly an operator assertion backed by sensor consistency,
        # not an automatic claim that commanded extrusion reached the nozzle.
        record = {"state": state, "evidence": "operator", "session": self.session_id}
        if state == "loaded":
            record.update(source="external:" + key, identity=dict(profiles[key]))
        self._set_filament_loaded(key, state == "loaded")
        self._filament_checks[key] = record
        gcmd.respond_info("Recorded operator filament check for head %d" % (head + 1))

    def _print_admission(self, gcmd, openace=False):
        try:
            self._require_no_recovery_attempt()
        except ValueError as error:
            raise gcmd.error(str(error))
        if self._identification_pending(self.printer.get_reactor().monotonic()):
            raise gcmd.error("Restart Klipper after head identification before printing")
        present = self.printer.lookup_object("openace", None) is not None
        if present != openace or (not openace and self.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Print submission ownership changed")
        if not openace and any(self._material_operation_active(name)
                               for name in ("filament_operation", "toolhead_operation")):
            raise gcmd.error("Wait for the running filament or toolhead operation before starting a print")
        now = self.printer.get_reactor().monotonic()
        stats = self.printer.lookup_object("print_stats").get_status(now)
        sd = self.printer.lookup_object("virtual_sdcard")
        paused = self.printer.lookup_object("pause_resume").get_status(now)
        if (stats.get("state") not in (("standby", "complete", "cancelled") if openace
                    else ("standby", "complete", "cancelled", "error"))
                or paused.get("is_paused") is not False
                or sd.is_active() or sd.is_cmd_from_sd()):
            raise gcmd.error("Another print or recovery context is active")
        return sd

    def _openace_print_plan(self, gcmd, request, recheck=False):
        sd = self._print_admission(gcmd, openace=True)
        if not isinstance(request, dict) or set(request) != {
                "id", "session", "owner", "ace_session", "config_revision",
                "pairs", "file", "leveling"} or request["owner"] != "openace":
            raise ValueError("Invalid openACE print request fields")
        ticket = request["id"]
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if request["session"] != self.session_id:
            raise ValueError("Printer session changed; refresh preview")
        if not recheck and (ticket in self._print_requests or len(self._print_requests) >= 1024):
            raise ValueError("Print request already attempted or capacity reached")
        if type(request["leveling"]) is not bool:
            raise ValueError("Invalid leveling option")
        ace = self.printer.lookup_object("openace").get_status(
            self.printer.get_reactor().monotonic())
        for key, expected in (("session_id", request["ace_session"]),
                              ("config_revision", request["config_revision"])):
            if type(expected) is not int or type(ace.get(key)) is not int or ace[key] != expected:
                raise ValueError("openACE configuration or session changed")
        if "operation" not in ace or ace["operation"] is not None:
            raise ValueError("An openACE operation is active or unavailable")
        pairs = request["pairs"]
        if not isinstance(pairs, list) or not pairs or len(pairs) > 32:
            raise ValueError("Invalid openACE print mapping")
        seen = set()
        routes = ace.get("default_tool_map", {})
        for pair in pairs:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(v) is not int or not 0 <= v <= 31 for v in pair)
                    or pair[0] in seen or str(pair[1]) not in routes):
                raise ValueError("Invalid or unavailable virtual tool mapping")
            seen.add(pair[0])
        # openACE's public start wrapper owns material/preflight validation and
        # freezes these virtual routes. WM+ never updates box_modify here.
        # The structured standalone filename transport does not alter the
        # separately owned openACE command transport's existing restrictions.
        if isinstance(request.get("file"), dict) and isinstance(request["file"].get("path"), str):
            if any(char in request["file"]["path"] for char in "#;"):
                raise ValueError("Unsupported print filename")
        full, identity = self._print_file(sd, request["file"])
        return None, full, identity

    def _print_plan(self, gcmd, request):
        if isinstance(request, dict) and request.get("owner") == "openace":
            return self._openace_print_plan(gcmd, request)
        # Validation is complete before any settings, file reset or motion.
        sd = self._print_admission(gcmd)
        if not isinstance(request, dict) or set(request) - {"sequence", "material_confirmation", "sliced_materials"} != {
                "id", "session", "profile_revision", "file", "mapping",
                "expected_mapping", "leveling"}:
            raise ValueError("Invalid print request fields")
        ticket = request["id"]
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if request["session"] != self.session_id:
            raise ValueError("Printer session changed; refresh preview")
        self._check_print_ticket(request)
        if type(request["leveling"]) is not bool:
            raise ValueError("Invalid leveling option")
        profiles, revision = self._profiles()
        if request["profile_revision"] != revision:
            raise ValueError("Filament settings changed; refresh preview")
        variables = self.printer.lookup_object("save_variables").get_status(
            self.printer.get_reactor().monotonic())["variables"]
        previous = [variables.get("box_modify_t%d" % i) for i in range(4)]
        expected = request["expected_mapping"]
        if (not isinstance(expected, list) or len(expected) != 4
                or any(type(v) is not int or not 0 <= v <= 3 for v in expected)
                or any(type(v) is not int for v in previous)
                or previous != expected):
            raise ValueError("Tool mapping changed; refresh preview")
        chosen = request["mapping"]
        if not isinstance(chosen, dict) or not chosen or len(chosen) > 4:
            raise ValueError("Choose destinations for the sliced tools")
        mapping = list(previous)
        for tool, head in chosen.items():
            if tool not in ("0", "1", "2", "3") or type(head) is not int or not 0 <= head <= 3:
                raise ValueError("Invalid sliced tool or physical head")
            heater = "extruder" if head == 0 else "extruder%d" % head
            if self.printer.lookup_object(heater, None) is None:
                raise ValueError("Selected physical head is not installed")
            mapping[int(tool)] = head
        self._require_print_materials(request, profiles)
        full, identity = self._print_file(sd, request["file"])
        return mapping, full, identity

    def _check_print_ticket(self, request):
        ticket = request.get("id")
        if request.get("session") != self.session_id:
            raise ValueError("Printer session changed; refresh preview")
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if "sequence" in request:
            sequence = request["sequence"]
            if (type(sequence) is not int or not 1 <= sequence <= 9007199254740991
                    or ticket != "print_%d" % sequence):
                raise ValueError("Invalid sequenced print request identity")
            if sequence != getattr(self, "_print_request_sequence", 0) + 1:
                raise ValueError("Print request sequence expired; refresh preview and check its result")
        else:
            if ticket.startswith("print_"):
                raise ValueError("Sequenced print request ID requires its sequence")
            if len(self._print_requests) >= 1024:
                raise ValueError("Legacy print request capacity reached; refresh with a sequence-capable client")
        if ticket in self._print_requests:
            raise ValueError("Print request already attempted; check its result")

    def _remember_print_ticket(self, request):
        if isinstance(request, dict) and request.get("owner") == "openace":
            ticket = request.get("id")
            if (request.get("session") != self.session_id or not isinstance(ticket, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket)
                    or ticket in self._print_requests or len(self._print_requests) >= 1024):
                return False
            self._print_requests.add(ticket)
            return True
        try:
            self._check_print_ticket(request)
        except (AttributeError, ValueError):
            return False
        if "sequence" in request:
            self._print_request_sequence = request["sequence"]
        else:
            self._print_requests.add(request["id"])
        return True

    def _require_print_materials(self, request, profiles=None):
        confirmation = request.get("material_confirmation", False)
        if type(confirmation) is not bool:
            raise ValueError("Invalid material confirmation")
        sliced = request.get("sliced_materials", {})
        if (not isinstance(sliced, dict) or set(sliced) - set(request["mapping"])
                or any(not isinstance(v, str) or len(v) > 128
                       or any(ord(c) < 32 for c in v) for v in sliced.values())):
            raise ValueError("Invalid sliced material review")
        if profiles is None:
            profiles = self._profiles()[0]
        now = self.printer.get_reactor().monotonic()
        sensed = self._sensor_filament_status(now)
        loaded = self._loaded_filament_status(now)
        for tool, head in request["mapping"].items():
            key = "h%d" % head
            if sensed.get(key, {}).get("state") != "loaded":
                raise ValueError("Head %d filament sensor is empty or unavailable" % (head + 1))
            configured = profiles.get(key, {}).get("material", "")
            expected = sliced.get(tool, "")
            needs_review = (not configured or loaded.get(key, {}).get("state") != "loaded"
                            or (expected and configured.casefold() != expected.casefold()))
            if needs_review and not confirmation:
                raise ValueError("Confirm filament metadata/loading for Head %d before printing" % (head + 1))

    def _require_loaded_print_heads(self, heads):
        # Configured identity and an inlet switch alone do not prove loading.
        loaded = self._loaded_filament_status(self.printer.get_reactor().monotonic())
        for head in heads:
            if loaded.get("h%d" % head, {}).get("state") != "loaded":
                raise ValueError("Load filament in Head %d before printing" % (head + 1))

    def _print_file_identity(self, sd, identity):
        if not isinstance(identity, dict) or set(identity) != {"path", "size", "modified"}:
            raise ValueError("Invalid file identity")
        path = identity["path"]
        if (not isinstance(path, str) or not path or len(path) > 1024
                or path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/"))
                or any(ord(c) < 32 or ord(c) == 127 or c in '\\"' for c in path)):
            raise ValueError("Unsupported print filename")
        size, modified = identity["size"], identity["modified"]
        if (type(size) is not int or size <= 0
                or type(modified) not in (int, float) or not math.isfinite(modified)):
            raise ValueError("Invalid file size or modification time")
        root = os.path.realpath(sd.sdcard_dirname)
        full = os.path.realpath(os.path.join(root, path))
        if os.path.commonpath([root, full]) != root:
            raise ValueError("Print file is outside the G-code directory")
        info = os.stat(full)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size or info.st_mtime != modified:
            raise ValueError("Print file changed; refresh preview")
        return full, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def _print_file(self, sd, identity):
        full, file_identity = self._print_file_identity(sd, identity)
        path = identity["path"]
        # The stock loader enumerates files and can case-fold names. Require the
        # exact selected entry so it cannot silently choose a different file.
        if path not in {name for name, unused_size in sd.get_file_list(True)}:
            raise ValueError("Print file is not available to the SD loader")
        return full, file_identity

    def _recovery_active_file(self, sd, identity):
        # The loader already selected this open stream. Validate its actual
        # descriptor instead of enumerating the entire G-code directory again.
        full, file_identity = self._print_file_identity(sd, identity)
        stream = getattr(sd, "current_file", None)
        if stream is None or stream.closed or os.path.realpath(stream.name) != full:
            raise ValueError("Checkpoint active file changed")
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != file_identity:
            raise ValueError("Checkpoint active file was replaced")
        return full, file_identity

    def _recovery_job_path(self):
        return os.path.join(os.path.dirname(self.profile_path), "wmp_recovery_job.json")

    @staticmethod
    def _recovery_read_bytes(path, limit):
        # Do not follow a final symlink or block on a FIFO. Detect replacement
        # during the read as well as in-place edits before returning evidence.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError("Invalid recovery evidence file")
            payload = stream.read(limit + 1)
            def identity(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if (len(payload) != before.st_size
                    or identity(os.fstat(stream.fileno())) != identity(before)
                    or identity(os.stat(path, follow_symlinks=False)) != identity(before)):
                raise ValueError("Recovery evidence changed while reading")
        return payload

    def _read_recovery_job(self):
        payload = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        value = json.loads(payload)
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("Invalid recovery job record")
        return value

    @staticmethod
    def _recovery_offsets(offsets):
        # SAVE_VARIABLE uses literal_eval and preserves native tuple offsets.
        # JSON converts those tuples to arrays. Compare the same coordinates,
        # without rewriting either durable record or relaxing numeric checks.
        if (not isinstance(offsets, (list, tuple)) or len(offsets) != 4
                or any(not isinstance(row, (list, tuple)) or len(row) != 3
                       or any(type(v) not in (int, float) or not math.isfinite(v)
                              for v in row) for row in offsets)):
            raise ValueError("Invalid recovery calibration offsets")
        return [list(row) for row in offsets]

    @classmethod
    def _recovery_context(cls, context):
        if not isinstance(context, dict):
            raise ValueError("Invalid recovery context")
        return dict(context, offsets=cls._recovery_offsets(context.get("offsets")))

    @staticmethod
    def _recovery_fingerprint(payload):
        # Match the reviewed native sidecar format exactly. This detects stale
        # bytes; it is not an authenticity or physical-readiness guarantee.
        value = 0xcbf29ce484222325
        for byte in payload:
            value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
        return "%016x" % value

    @staticmethod
    def _recovery_checkpoint_values(payload, file_size):
        # Parse the reviewed vendor format without defaults/interpolation. Native
        # fallback-to-zero parsing must not turn truncated evidence into a job.
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        try:
            parser.read_string(payload.decode("ascii"))
        except (UnicodeError, configparser.Error) as error:
            raise ValueError("Malformed recovery checkpoint: " + str(error))
        if parser.sections() != ["plr_data"] or parser.defaults():
            raise ValueError("Invalid recovery checkpoint section")
        fields = dict(parser["plr_data"])
        integers = {"last_file_pos", "absolute_e", "timestamp", "print_time", "last_is_during_T",
                    "last_heater_bed_target"} | {"last_extruder%d_target" % i for i in range(4)}
        floats = {"last_x", "last_y", "last_z", "last_e", "last_gcode_move_speed",
                  "last_gcode_move_speed_factor", "last_gcode_move_extrude_factor",
                  "last_fan_speed", "last_auxiliary_fan_speed", "last_air_fan_speed"}
        if not (integers | floats | {"last_leveling_type"}).issubset(fields):
            raise ValueError("Recovery checkpoint required fields are missing")
        values = {}
        for key in integers | floats:
            text = fields[key]
            pattern = r"[+-]?[0-9]+" if key in integers else r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
            if not re.fullmatch(pattern, text):
                raise ValueError("Invalid recovery checkpoint number: " + key)
            value = int(text) if key in integers else float(text)
            if key in floats and not math.isfinite(value):
                raise ValueError("Nonfinite recovery checkpoint number: " + key)
            values[key] = value
        if not 0 < values["last_file_pos"] < min(file_size, 2147483648):
            raise ValueError("Recovery file position is outside the unfinished file")
        if any(values[key] not in (0, 1) for key in ("absolute_e", "last_is_during_T")):
            raise ValueError("Invalid recovery extrusion/tool-change mode")
        if values["timestamp"] <= 0 or values["print_time"] < 0:
            raise ValueError("Recovery checkpoint is reset or has invalid elapsed time")
        if any(values[key] < 0 for key in integers if key.endswith("_target")):
            raise ValueError("Negative recovery heater target")
        for key in ("last_gcode_move_speed", "last_gcode_move_speed_factor", "last_gcode_move_extrude_factor"):
            if values[key] <= 0:
                raise ValueError("Invalid recovery motion factor: " + key)
        for key in ("last_fan_speed", "last_auxiliary_fan_speed", "last_air_fan_speed"):
            if not 0 <= values[key] <= 1:
                raise ValueError("Invalid recovery fan fraction: " + key)
        if fields["last_leveling_type"] not in ("adaptive_mesh", "default_mesh"):
            raise ValueError("Unsupported recovery leveling context")
        values["last_leveling_type"] = fields["last_leveling_type"]
        # G-code coordinates include offsets; range checks need the restored
        # transform. Heater limits and interrupted-tool-change handling likewise
        # belong to current-machine admission, not this format parser.
        return values

    def _recovery_checkpoint_evidence(self, selected_file, checkpoint, checkpoint_hash, job_hash):
        """Bind current evidence to the native loader's cached selection.

        Still a read-only prerequisite, not an admission lease or permission to
        call stock preparation. The caller must separately validate checkpoint
        semantics, machine state and exclusive recovery ownership.
        """
        if checkpoint not in ("plr_dataA.ini", "plr_dataB.ini"):
            raise ValueError("Invalid recovery checkpoint selection")
        for value in (checkpoint_hash, job_hash):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{16}", value):
                raise ValueError("Invalid native recovery fingerprint")
        path = os.path.join(self.recovery_checkpoint_dir, checkpoint)
        paths = (path, path + ".wmp-coordinates", self._recovery_job_path())
        limits = (65536, 256, 65536)
        before = tuple(self._recovery_read_bytes(name, limit) for name, limit in zip(paths, limits))
        marker = before[1].decode("ascii").split()
        if (marker != ["WMP-GCODE-XYZ-MATERIAL-2", checkpoint_hash, job_hash]
                or self._recovery_fingerprint(before[0]) != checkpoint_hash
                or self._recovery_fingerprint(before[2]) != job_hash):
            raise ValueError("Selected checkpoint and recovery job binding differ")
        record = self._recovery_material_evidence(selected_file)
        values = self._recovery_checkpoint_values(before[0], record["file"]["size"])
        # File-content hashing yields. Recheck all bindings afterward, even if
        # the replacement record happens to describe the same job semantically.
        after = tuple(self._recovery_read_bytes(name, limit) for name, limit in zip(paths, limits))
        if after != before or record != json.loads(before[2]):
            raise ValueError("Recovery checkpoint or job changed during verification")
        return {"record": record, "checkpoint": checkpoint, "values": values,
                "checkpoint_hash": checkpoint_hash, "job_hash": job_hash}

    def _recovery_runtime_path(self, filename, for_write=False):
        legacy = os.path.join(os.path.dirname(self.profile_path), filename)
        runtime = os.path.join(getattr(self, "recovery_checkpoint_dir",
                                      os.path.dirname(self.profile_path)), filename)
        # Runtime evidence is not configuration. Keep old interrupted records
        # readable without rewriting their bytes or retirement file identities.
        # An existing malformed/symlink runtime entry must not expose older data.
        return runtime if for_write else wmp_recovery_retirement.runtime_evidence_path(legacy, runtime)

    def _deposition_envelope_path(self, for_write=False):
        return self._recovery_runtime_path("wmp_recovery_envelope.json", for_write)


    def _disable_print_recovery(self, reason):
        """Retire optional job evidence without taking ownership of the printer."""
        self._print_recovery_error = str(reason)[:512]
        self._pending_recovery_submission = None
        self._deposition_envelope = None
        self._pending_execution_snapshot = None
        failures = []
        try:
            self._write_recovery_job({"version": 1, "state": "invalidated",
                                      "reason": self._print_recovery_error,
                                      "session": self.session_id})
        except (OSError, ValueError, AttributeError) as error:
            failures.append(str(error))
        # Delete and durably retire fallback bytes before removing runtime
        # authority. If the job write also failed, reversing this order could
        # expose an older legacy checkpoint after an unlink failure/power loss.
        legacy_dir = os.path.dirname(self.profile_path)
        runtime_dir = getattr(self, "recovery_checkpoint_dir", legacy_dir)
        names = ("wmp_recovery_execution.json", "wmp_recovery_envelope.json")
        def remove(path):
            try:
                os.unlink(path)
                return True
            except FileNotFoundError:
                return True
            except OSError as error:
                failures.append(str(error))
                return False
        def sync(parent):
            try:
                directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return True
            except OSError as error:
                failures.append(str(error))
                return False
        if os.path.abspath(legacy_dir) != os.path.abspath(runtime_dir):
            removed = {name: remove(os.path.join(legacy_dir, name)) for name in names}
            legacy_synced = sync(legacy_dir)
            for name in names:
                if removed[name] and legacy_synced:
                    remove(os.path.join(runtime_dir, name))
        else:
            for name in names:
                remove(os.path.join(runtime_dir, name))
        sync(runtime_dir)
        self._recovery_invalidation_error = "; ".join(failures)[:512]
        logging.warning("Power-loss recovery disabled for current job: %s%s",
                        self._print_recovery_error,
                        "; evidence invalidation: " + self._recovery_invalidation_error if failures else "")

    def _install_deposition_observer(self):
        toolhead = self.printer.lookup_object("toolhead")
        queue = getattr(toolhead, "lookahead", None)
        if queue is None or not callable(getattr(queue, "add_move", None)):
            return False
        installed = getattr(self, "_deposition_queue_hook", None)
        if installed is not None:
            if queue.add_move is not installed:
                raise ValueError("Recovery deposition observer was replaced")
            return True
        original = queue.add_move
        def enqueue(move):
            envelope = getattr(self, "_deposition_envelope", None)
            if envelope is not None:
                try:
                    if (self.session_id != self._deposition_session
                            or self.printer.lookup_object("openace", None) is not None
                            or self.printer.lookup_object("AFC", None) is not None):
                        raise ValueError("Deposition recording lost standalone ownership")
                    envelope.observe(move)
                except Exception as error:
                    # The vendor already advanced commanded_pos. Optional
                    # recording must never suppress this validated move.
                    self._disable_print_recovery("Deposition evidence failed: " + str(error))
            # Submission is deliberately outside the evidence exception handler:
            # a genuine queue error propagates, and is never retried.
            return original(move)
        self._deposition_queue_hook = enqueue
        self._deposition_queue = queue
        queue.add_move = enqueue
        return True

    def _verify_deposition_observer(self, envelope, record):
        queue = getattr(self.printer.lookup_object("toolhead"), "lookahead", None)
        if (envelope is not getattr(self, "_deposition_envelope", None)
                or envelope.failed or envelope.record != record
                or getattr(self, "_deposition_session", None) != self.session_id
                or queue is not getattr(self, "_deposition_queue", None)
                or queue is None or queue.add_move is not getattr(self, "_deposition_queue_hook", None)):
            raise ValueError("Recovery deposition observer lost its admitted binding")

    def _begin_deposition_envelope(self, record, restored=None):
        if (not self._install_deposition_observer()
                or self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            self._deposition_envelope = None
            return False
        self._deposition_envelope = RecoveryDepositionEnvelope(
            lambda value: self._write_recovery_json(self._deposition_envelope_path(for_write=True), value),
            record["id"], record["file"]["sha256"], restored)
        self._deposition_session = self.session_id
        return True

    def _execution_ready(self):
        self._install_deposition_observer()
        reactor = self.printer.get_reactor()
        self._execution_stopped = False
        if getattr(self, "_execution_timer", None) is None:
            self._execution_timer = reactor.register_timer(self._execution_tick, reactor.monotonic() + 1.)
        else:
            reactor.update_timer(self._execution_timer, reactor.monotonic() + 1.)

    def _execution_stop(self, *args):
        self._execution_stopped = True
        self._execution_state = "stopped"
        self._pending_execution_snapshot = None
        if getattr(self, "_execution_timer", None) is not None:
            reactor = self.printer.get_reactor()
            reactor.update_timer(self._execution_timer, reactor.NEVER)

    def _execution_sd_boundary(self):
        """Bind the outer SD dispatch before it runs; never bind a nested call."""
        try:
            sd = self.printer.lookup_object("virtual_sdcard")
            if (self.printer.lookup_object("gcode").get_mutex().test()
                    or not sd.is_active() or not sd.is_cmd_from_sd()
                    or sd.current_file is None or sd.current_file.closed
                    or type(sd.file_position) is not int
                    or type(sd.next_file_position) is not int
                    or sd.next_file_position <= sd.file_position):
                return None
            return (sd, sd.current_file, sd.file_position, sd.next_file_position, self.session_id)
        except (AttributeError, KeyError, TypeError):
            return None

    def _execution_sample_batch(self, boundary=None):
        # This publication/capture pair is synchronous: share live observations
        # only for this batch and reuse the save-invalidated loaded profiles.
        # Command admission still calls _profiles outside this observation scope.
        previous = getattr(self, "_status_observation_cache", None)
        self._status_observation_cache = {}
        try:
            self._publish_recovery_execution()
            self._queue_recovery_execution(boundary)
        finally:
            self._status_observation_cache = previous

    def _execution_command_completed(self, boundary):
        # run_script has returned successfully and released its mutex, but the
        # retained SD worker has not yet advanced file_position. No yield here.
        if (getattr(self, "_execution_stopped", True)
                or getattr(self, "_print_recovery_error", "")):
            return
        try:
            if self._execution_sd_boundary() != boundary:
                raise ValueError("Completed SD command binding changed")
            now = self.printer.get_reactor().monotonic()
            if now < getattr(self, "_execution_next_capture_time", 0.):
                return
            self._execution_next_capture_time = now + 1.
            self._execution_sample_batch(boundary)
            self._execution_error = ""
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            self._pending_execution_snapshot = None
            self._execution_state = "refused"
            self._execution_error = str(error)

    def _execution_tick(self, eventtime):
        reactor = self.printer.get_reactor()
        if self._execution_stopped:
            self._execution_state = "stopped"
            return reactor.NEVER
        if getattr(self, "_print_recovery_error", ""):
            self._execution_state = "unavailable"
            self._execution_error = self._print_recovery_error
            return eventtime + 1.
        try:
            sd = self.printer.lookup_object("virtual_sdcard", None)
            if (sd is None or not sd.is_active()
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None):
                self._pending_execution_snapshot = None
                self._execution_state = "inactive"
                return eventtime + 1.
            # Do not observe transient state partway through any command, even
            # one submitted externally rather than by the SD worker.
            if self.printer.lookup_object("gcode").get_mutex().test():
                self._execution_state = "command_busy"
                return eventtime + 1.
            self._execution_sample_batch()
            candidate = self._pending_execution_snapshot
            self._execution_state = ("observing" if candidate is None else
                "waiting_schedule" if candidate["scheduled_print_time"] is None else "waiting_motion")
            self._execution_error = ""
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            self._pending_execution_snapshot = None
            self._execution_state = "refused"
            self._execution_error = str(error)
        return eventtime + 1.

    @staticmethod
    def _execution_boundary(snapshot):
        return (snapshot["session"], snapshot["job_fingerprint"], snapshot["file_position"])

    def _recovery_mesh_fingerprint(self):
        """Bind the active interpolation grid, offsets and fade configuration."""
        mesh = self.printer.lookup_object("bed_mesh")
        status = mesh.get_status(self.printer.get_reactor().monotonic())
        grid = status.get("mesh_matrix")
        if (status.get("profile_name") != "wmp_print" or not isinstance(grid, (list, tuple))
                or not 2 <= len(grid) <= 256 or not isinstance(grid[0], (list, tuple))
                or not 2 <= len(grid[0]) <= 256
                or any(not isinstance(row, (list, tuple)) or len(row) != len(grid[0]) for row in grid)):
            raise ValueError("Recovery requires the active saved print mesh")
        active = mesh.get_mesh()
        parameters = [getattr(mesh, name, None) for name in
                      ("fade_start", "fade_end", "fade_dist", "fade_target", "tool_offset")]
        bounds = [status.get("mesh_min"), status.get("mesh_max"), getattr(active, "mesh_offsets", None)]
        if (any(not isinstance(v, (list, tuple)) or len(v) != 2 for v in bounds)
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in parameters + [v for pair in bounds for v in pair] + [v for row in grid for v in row])
                or any(bounds[0][i] >= bounds[1][i] for i in range(2))):
            raise ValueError("Invalid recovery mesh transform")
        canonical = [[[float(v) for v in row] for row in grid],
                     [[float(v) for v in pair] for pair in bounds], [float(v) for v in parameters]]
        payload = json.dumps(canonical, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(payload).hexdigest()

    def _restore_recovery_mesh(self, execution, guard):
        guard()
        gcode = self.printer.lookup_object("gcode")
        if not gcode.get_mutex().test():
            raise ValueError("Recovery mesh restore requires command ownership")
        offsets = execution["mesh_offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offsets)):
            raise ValueError("Invalid recovery mesh offsets")
        gcode.run_script_from_command("BED_MESH_PROFILE_BASE LOAD=wmp_print")
        guard()
        gcode.run_script_from_command("BED_MESH_OFFSET X=%.17g Y=%.17g ZFADE=%.17g" % tuple(offsets))
        guard()
        if self._recovery_mesh_fingerprint() != execution["mesh_fingerprint"]:
            raise ValueError("Saved recovery mesh transform changed")
        mesh = self.printer.lookup_object("bed_mesh")
        parser, machine = execution["parser_position"], execution["machine_position"]
        factor = mesh.get_z_factor(parser[2])
        correction = factor * mesh.get_mesh().calc_z(parser[0], parser[1]) + (1. - factor) * mesh.fade_target
        predicted = [parser[0], parser[1], parser[2] + correction]
        if (not math.isfinite(factor) or not 0 <= factor <= 1
                or any(not math.isfinite(v) or not math.isclose(v, actual, abs_tol=1e-5, rel_tol=0)
                       for v, actual in zip(predicted, machine[:3]))):
            raise ValueError("Recovery mesh does not reproduce the saved machine position")
        return True

    def _recovery_execution_snapshot(self, sd_boundary=None, queued_tail=None):
        """Capture parser/head state at a completed SD command boundary.

        No reactor yield or G-code dispatch is permitted in this reader. This is
        not proof that buffered physical motion completed and is not persisted
        or exposed as a recoverable checkpoint until that contract is resolved.
        """
        if self.printer.lookup_object("gcode").get_mutex().test():
            raise ValueError("G-code command prevents checkpoint capture")
        now = self.printer.get_reactor().monotonic()
        sd = self.printer.lookup_object("virtual_sdcard")
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None
                or not sd.is_active()
                or (sd.is_cmd_from_sd() if sd_boundary is None
                    else self._execution_sd_boundary() != sd_boundary)
                or self.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                or self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False
                or self.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready") is not True):
            raise ValueError("No completed standalone print-command boundary")
        for name in ("filament_operation", "toolhead_operation"):
            if self._material_operation_active(name):
                raise ValueError("Service operation prevents checkpoint capture")
        job_bytes = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        record = json.loads(job_bytes)
        if record.get("state") != "committed" or record.get("owner") != "standalone":
            raise ValueError("No committed standalone job for checkpoint capture")
        if self._retire_changed_print_recovery(record=record):
            raise ValueError("Recovery evidence retired after print recipe changed")
        variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        if (self._recovery_context(variables.get("wmp_print_context")) != self._recovery_context(record.get("context"))
                or any(type(variables.get(key)) is not int or variables[key] != 0
                       for key in ("fail_flag", "is_nozzle_setting"))
                or any(variables.get("box_modify_t%d%s" % (tool, suffix)) != head
                       for tool, head in enumerate(record["mapping"]) for suffix in ("", "_backup"))):
            raise ValueError("Checkpoint job context, mapping or tool state changed")
        file_info = {key: record["file"][key] for key in ("path", "size", "modified")}
        self._recovery_active_file(sd, file_info)
        # get_file_position() returns next_file_position, which can describe a
        # still-executing command. Public status is the completed file position.
        position = (sd.get_status(now).get("file_position") if sd_boundary is None
                    else sd_boundary[3])
        if type(position) is not int or not 0 < position < file_info["size"]:
            raise ValueError("No unfinished completed-file position")
        attachment = self._attachment(now)
        if attachment.get("state") != "attached" or attachment.get("head") not in record["heads"]:
            raise ValueError("Checkpoint head attachment is not a required loaded source")
        head = int(attachment["head"][1:])
        toolhead_object = self.printer.lookup_object("toolhead")
        toolhead = toolhead_object.get_status(now)
        scheduled, estimated, lookahead_empty = toolhead_object.check_busy(now)
        if ((lookahead_empty is not True and queued_tail is None)
                or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in (scheduled, estimated))):
            raise ValueError("Checkpoint motion has not reached a scheduled boundary")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if toolhead.get("extruder") != heater or variables.get("current_extruder") != head:
            raise ValueError("Checkpoint active extruder and attachment disagree")
        loaded = self._loaded_filament_status(now).get(attachment["head"], {})
        saved = record["heads"][attachment["head"]]
        if not self._loaded_source_matches(loaded, saved):
            raise ValueError("Checkpoint loaded source changed")
        move = self.printer.lookup_object("gcode_move").get_status(now)
        coordinates = list(move.get("gcode_position", []))
        origin = list(move.get("homing_origin", []))
        parser_position = list(move.get("position", []))
        machine_position = list(toolhead.get("position", []))
        if (any(len(vector) != 4 for vector in (coordinates, origin, parser_position, machine_position))
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in coordinates + origin + parser_position + machine_position)
                or any(type(move.get(key)) is not bool for key in ("absolute_coordinates", "absolute_extrude"))
                or any(type(move.get(key)) not in (int, float) or not math.isfinite(move[key]) or move[key] <= 0
                       for key in ("speed", "speed_factor", "extrude_factor"))):
            raise ValueError("Checkpoint G-code state is unavailable")
        settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
        targets = {}
        for name in ["extruder", "extruder1", "extruder2", "extruder3", "heater_bed"]:
            obj = self.printer.lookup_object(name, None)
            if obj is None:
                if name == "heater_bed":
                    raise ValueError("Checkpoint bed heater is unavailable")
                continue
            target = obj.get_status(now).get("target")
            limits = settings.get(name, {})
            minimum, maximum = limits.get("min_temp"), limits.get("max_temp")
            if (any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (target, minimum, maximum))
                    or minimum >= maximum or target < 0
                    or (target != 0 and not minimum <= target <= maximum)):
                raise ValueError("Invalid checkpoint heater target: " + name)
            targets[name] = target
        fans = {}
        for name in ("fan", "fan_generic auxiliary_fan", "fan_generic air_fan"):
            obj = self.printer.lookup_object(name, None)
            if obj is None:
                if name == "fan":
                    raise ValueError("Checkpoint fan state is unavailable: " + name)
                continue
            speed = obj.get_status(now).get("speed")
            if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 1:
                raise ValueError("Invalid checkpoint fan speed: " + name)
            fans[name] = speed
        stats = self.printer.lookup_object("print_stats").get_status(now)
        accounting = {key: stats.get(key) for key in ("total_duration", "print_duration", "filament_used")}
        self._validate_recovery_accounting(accounting)
        mesh = self.printer.lookup_object("bed_mesh")
        fingerprint = self._recovery_mesh_fingerprint()
        mesh_offsets = list(mesh.get_mesh().mesh_offsets) + [mesh.tool_offset]
        return {"version": 4, "mesh_fingerprint": fingerprint, "mesh_offsets": mesh_offsets,
                "job_id": record["id"], "session": self.session_id,
                "job_fingerprint": self._recovery_fingerprint(job_bytes),
                "file": copy.deepcopy(record["file"]), "file_position": position,
                "head": attachment["head"], "source": copy.deepcopy(saved),
                "mapping": list(record["mapping"]), "gcode_position": coordinates,
                "parser_position": parser_position, "machine_position": machine_position,
                "heater_targets": targets, "fans": fans, **accounting,
                "homing_origin": origin, "scheduled_print_time": scheduled,
                "observed_print_time": estimated, **{key: move[key] for key in
                    ("absolute_coordinates", "absolute_extrude", "speed", "speed_factor", "extrude_factor")}}

    def _recovery_retirement_store(self):
        directory = os.path.dirname(self.profile_path)
        return wmp_recovery_retirement.EvidenceStore(
            directory, getattr(self, 'recovery_checkpoint_dir', directory),
            runtime_directory=getattr(self, 'recovery_checkpoint_dir', directory))

    def _recovery_retirement_admit(self, session, locked):
        # This operation retires saved evidence. It does not move the printer,
        # reset physical faults, change targets, or claim recovery succeeded.
        if session != self.session_id:
            raise ValueError('Recovery printer session changed')
        if locked and not self.printer.lookup_object('gcode').get_mutex().test():
            raise ValueError('Recovery discard command ownership changed')
        if any(self.printer.lookup_object(owner, None) is not None
               for owner in ('openace', 'AFC')):
            raise ValueError('Another filament manager owns recovery')
        if self._recovery_attempt_active() or self._print_cancel_active():
            raise ValueError('Wait for the running recovery or cancellation to stop before discarding its evidence')
        now = self.printer.get_reactor().monotonic()
        sd = self.printer.lookup_object('virtual_sdcard')
        if not locked:
            return {'session': session, 'file': getattr(sd, 'current_file', None)}
        pause = self.printer.lookup_object('pause_resume').get_status(now)
        stats = self.printer.lookup_object('print_stats').get_status(now)
        if (sd.is_active() or sd.is_cmd_from_sd() or pause.get('is_paused') is not False
                or stats.get('state') not in ('standby', 'complete', 'cancelled', 'error')):
            raise ValueError('Finish or cancel the current print before discarding its saved recovery evidence')
        return {'session': session, 'file': getattr(sd, 'current_file', None)}

    def _handle_recovery_retirement_review(self, web_request):
        try:
            session, request_id = web_request.get_str('session'), web_request.get_str('id')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
                raise ValueError('Invalid recovery discard request')
            before = self._recovery_retirement_admit(session, False)
            store = self._recovery_retirement_store()
            evidence = store.review()
            manifest, raw = store.snapshot()
            if manifest != evidence['manifest']:
                raise ValueError('Recovery discard evidence changed')
            filename = None
            try:
                candidate = json.loads(raw['job']).get('file', {}).get('path')
                if (isinstance(candidate, str) and 0 < len(candidate) < 4096
                        and not any(ord(c) < 32 for c in candidate)):
                    filename = candidate
            except (ValueError, TypeError, AttributeError):
                pass  # Raw preservation must not depend on parsing a bad job.
            if not any(r['present'] for r in evidence['manifest']['records'].values()):
                raise ValueError('There is no saved recovery evidence to discard')
            if (self._recovery_retirement_admit(session, False) != before
                    or store.review() != evidence):
                raise ValueError('Recovery discard review changed')
            web_request.send({'file': filename, 'request': {'version': 1, 'id': request_id,
                                         'session': session, 'evidence': evidence}})
        except Exception as error:
            raise web_request.error(str(error))

    def cmd_RETIRE_RECOVERY(self, gcmd):
        request = None
        try:
            request = self._decode_recovery_json(gcmd.get('REQUEST'), 16384)
            if (not isinstance(request, dict) or set(request) != {'version', 'id', 'session', 'evidence'}
                    or type(request['version']) is not int or request['version'] != 1
                    or not isinstance(request['evidence'], dict)):
                raise ValueError('Invalid recovery discard confirmation')
            before = self._recovery_retirement_admit(request['session'], True)
            def admit():
                if self._recovery_retirement_admit(request['session'], True) != before:
                    raise ValueError('Recovery discard machine context changed')
            self._recovery_retirement_result = {'id': request['id'], 'state': 'pending'}
            result = self._recovery_retirement_store().retire(
                request['evidence'], request['id'], request['session'], admit)
            if getattr(self, '_recovery_restore_error', ''):
                self._restore_recovery_attempt()
                if self._recovery_restore_error:
                    raise ValueError(self._recovery_restore_error)
            self._recovery_retirement_result = dict(result, state='complete')
            gcmd.respond_info(json.dumps(result, sort_keys=True))
        except Exception as error:
            self._recovery_retirement_result = {'id': request.get('id', '') if isinstance(request, dict) else '',
                                               'state': 'unknown', 'message': str(error)[:512]}
            raise gcmd.error(str(error))

    def _handle_recovery_retirement_result(self, web_request):
        # Explicit readback, never filesystem work in the periodic status path.
        # An old receipt is evidence of that action, not permission for a new one.
        try:
            session = web_request.get_str('session')
            request_id = web_request.get_str('id')
            if session != self.session_id:
                raise ValueError('Recovery printer session changed')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
                raise ValueError('Invalid recovery discard request')
            receipt = self._recovery_retirement_store().retirement()
            if session != self.session_id:
                raise ValueError('Recovery printer session changed')
            result = {'id': request_id, 'state': 'unknown'}
            if receipt is not None and receipt['id'] == request_id:
                result = dict(receipt, state='complete' if receipt['matches'] else 'superseded')
            web_request.send({'session': session, 'result': result})
        except Exception as error:
            raise web_request.error(str(error))

    def _recovery_execution_path(self, for_write=False):
        return self._recovery_runtime_path("wmp_recovery_execution.json", for_write)

    def _recovery_execution_bytes(self):
        try:
            return self._recovery_read_bytes(self._recovery_execution_path(), 65536)
        except FileNotFoundError as error:
            raise ValueError("No managed execution checkpoint was saved for this print; recovery cannot continue") from error

    @staticmethod
    def _parse_recovery_execution_format(payload):
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Saved recovery record is unreadable; original records were not changed") from error
        if isinstance(value, dict) and type(value.get("version")) is int and value["version"] != 4:
            missing = {
                1: "saved parser/machine coordinates, mesh transform and print accounting",
                2: "saved mesh transform and print accounting",
                3: "saved printing-time and filament-use accounting",
            }.get(value["version"])
            if missing is not None:
                raise ValueError("Saved recovery format %d lacks %s. Recovery cannot continue; original records were not changed" % (value["version"], missing))
            raise ValueError("Saved recovery format is not supported by this WM+ version; original records were not changed")
        return value

    def _require_recovery_not_retired(self):
        retired = self._recovery_retirement_store().retirement()
        if retired is not None and retired['matches']:
            raise ValueError("Recovery for this saved print was explicitly discarded; original records are archived")

    def _read_completed_recovery_execution(self, selected_file):
        self._require_recovery_not_retired()
        payload = self._recovery_execution_bytes()
        value = self._parse_recovery_execution_format(payload)
        fields = {"version", "job_id", "session", "job_fingerprint", "file", "file_position",
                  "head", "source", "mapping", "gcode_position", "homing_origin", "heater_targets",
                  "fans", "total_duration", "print_duration", "filament_used", "scheduled_print_time", "observed_print_time",
                  "completed_print_time", "absolute_coordinates", "absolute_extrude", "speed",
                  "speed_factor", "extrude_factor", "state", "parser_position", "machine_position", "mesh_fingerprint", "mesh_offsets"}
        if (not isinstance(value, dict) or set(value) != fields
                or type(value["version"]) is not int or value["version"] != 4
                or value["state"] != "completed"):
            raise ValueError("Invalid completed execution record")
        if not isinstance(value["mesh_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["mesh_fingerprint"]):
            raise ValueError("Invalid recovery mesh fingerprint")
        if (not isinstance(value["mesh_offsets"], list) or len(value["mesh_offsets"]) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in value["mesh_offsets"])):
            raise ValueError("Invalid recovery mesh offsets")
        for key in ("job_id", "session"):
            if not isinstance(value[key], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value[key]):
                raise ValueError("Invalid execution record identifier")
        if (value["head"] not in ("h0", "h1", "h2", "h3")
                or not isinstance(value["mapping"], list) or len(value["mapping"]) != 4
                or any(type(head) is not int or head not in range(4) for head in value["mapping"])):
            raise ValueError("Invalid execution head or mapping")
        for key in ("gcode_position", "homing_origin", "parser_position", "machine_position"):
            vector = value[key]
            if (not isinstance(vector, list) or len(vector) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
                raise ValueError("Invalid execution coordinates or origin")
        for key in ("absolute_coordinates", "absolute_extrude"):
            if type(value[key]) is not bool:
                raise ValueError("Invalid execution coordinate mode")
        for key in ("total_duration", "scheduled_print_time", "observed_print_time", "completed_print_time",
                    "speed", "speed_factor", "extrude_factor"):
            number = value[key]
            if (type(number) not in (int, float) or not math.isfinite(number) or number < 0
                    or (key in ("speed", "speed_factor", "extrude_factor") and number == 0)):
                raise ValueError("Invalid execution timing or motion factor")
        self._validate_recovery_accounting(value)
        if value["completed_print_time"] < max(value["scheduled_print_time"], value["observed_print_time"]):
            raise ValueError("Execution record was published before scheduled completion")
        targets, fans = value["heater_targets"], value["fans"]
        if (not isinstance(targets, dict) or "heater_bed" not in targets
                or set(targets) - {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in targets.values())
                or not isinstance(fans, dict) or "fan" not in fans
                or set(fans) - {"fan", "fan_generic auxiliary_fan", "fan_generic air_fan"}
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in fans.values())):
            raise ValueError("Invalid execution heater/fan state")
        job_bytes = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        if value["job_fingerprint"] != self._recovery_fingerprint(job_bytes):
            raise ValueError("Execution record belongs to different job evidence")
        record = self._recovery_material_evidence(selected_file)
        if (value["job_id"] != record["id"] or value["file"] != record["file"]
                or value["mapping"] != record["mapping"] or value["head"] not in record["heads"]
                or value["source"] != record["heads"][value["head"]]
                or type(value["file_position"]) is not int
                or not 0 < value["file_position"] < record["file"]["size"]):
            raise ValueError("Execution file, mapping or loaded head differs from committed job")
        heater = "extruder" if value["head"] == "h0" else "extruder" + value["head"][1:]
        if heater not in targets:
            raise ValueError("Execution head has no captured heater target")
        if (self._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload
                or self._recovery_read_bytes(self._recovery_job_path(), 65536) != job_bytes):
            raise ValueError("Execution evidence changed during verification")
        return copy.deepcopy(value)

    def _queue_recovery_execution(self, sd_boundary=None):
        # Keep one immutable candidate until it matures; never continually
        # replace it with newer, still-buffered motion and starve publication.
        if getattr(self, "_pending_execution_snapshot", None) is not None:
            return False
        toolhead = self.printer.lookup_object("toolhead")
        queue = getattr(toolhead, "lookahead", None)
        tail = queue.get_last() if queue is not None else None
        snapshot = self._recovery_execution_snapshot(sd_boundary, tail)
        if self._execution_boundary(snapshot) == getattr(self, "_execution_last_boundary", None):
            return False
        candidate = copy.deepcopy(snapshot)
        self._pending_execution_snapshot = candidate
        self._execution_state = "waiting_motion"
        if tail is not None:
            if queue.get_last() is not tail or not isinstance(tail.timing_callbacks, list):
                self._pending_execution_snapshot = None
                raise ValueError("Recovery lookahead boundary changed")
            earliest = candidate["scheduled_print_time"]
            candidate["scheduled_print_time"] = None
            self._execution_state = "waiting_schedule"
            def scheduled(print_time):
                if (self._pending_execution_snapshot is not candidate
                        or candidate["session"] != self.session_id
                        or getattr(self, "_execution_stopped", True)):
                    return
                if candidate["scheduled_print_time"] is not None:
                    return
                if getattr(toolhead, "lookahead", None) is not queue:
                    self._pending_execution_snapshot = None
                    self._execution_state = "refused"
                    self._execution_error = "Recovery lookahead queue was replaced"
                    return
                if (type(print_time) not in (int, float) or not math.isfinite(print_time)
                        or print_time < earliest or print_time < candidate["observed_print_time"]):
                    self._pending_execution_snapshot = None
                    self._execution_state = "refused"
                    self._execution_error = "Invalid recovery move scheduling time"
                    return
                candidate["scheduled_print_time"] = print_time
                self._execution_state = "waiting_motion"
            # Attach directly: register_lookahead_callback may flush when empty.
            # This callback is naturally invoked by retained _process_moves.
            tail.timing_callbacks.append(scheduled)
        return True

    def _publish_recovery_execution(self):
        """Publish a queued snapshot only after its scheduled motion time.

        The low-frequency sampler calls this. Publication is execution evidence,
        not native checkpoint selection or permission to resume a print.
        """
        pending = getattr(self, "_pending_execution_snapshot", None)
        if pending is None:
            return False
        if pending["scheduled_print_time"] is None:
            return False
        try:
            now = self.printer.get_reactor().monotonic()
            if (pending["session"] != self.session_id or self.printer.is_shutdown()
                    or self.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Checkpoint session, readiness or owner changed")
            sd = self.printer.lookup_object("virtual_sdcard")
            if (not sd.is_active()
                    or self.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                    or self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False):
                raise ValueError("Checkpoint job is no longer actively printing")
            position = sd.get_status(now).get("file_position")
            if type(position) is not int or position < pending["file_position"]:
                raise ValueError("Checkpoint file position moved backwards")
            for name in ("filament_operation", "toolhead_operation"):
                if self._material_operation_active(name):
                    raise ValueError("Service operation interrupted checkpoint completion")
            job_bytes = self._recovery_read_bytes(self._recovery_job_path(), 65536)
            if self._recovery_fingerprint(job_bytes) != pending["job_fingerprint"]:
                raise ValueError("Checkpoint job evidence changed")
            record = json.loads(job_bytes)
            variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            if (self._recovery_context(variables.get("wmp_print_context")) != self._recovery_context(record["context"])
                    or any(type(variables.get(key)) is not int or variables[key] != 0
                           for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Checkpoint context or fault state changed")
            loaded = self._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                if not self._loaded_source_matches(loaded.get(key, {}), saved):
                    raise ValueError("Checkpoint loaded source changed")
            file_info = {key: pending["file"][key] for key in ("path", "size", "modified")}
            self._recovery_active_file(sd, file_info)
            scheduled, estimated, unused_empty = self.printer.lookup_object("toolhead").check_busy(now)
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (scheduled, estimated))
                    or scheduled < pending["scheduled_print_time"]
                    or estimated < pending["observed_print_time"]):
                raise ValueError("Checkpoint motion clock changed or regressed")
            if estimated < pending["scheduled_print_time"]:
                return False
            # Later queued moves/head changes do not rewrite the captured parser
            # state. This receipt describes the earlier completed boundary.
            completed = dict(pending, state="completed", completed_print_time=estimated)
            self._write_recovery_json(self._recovery_execution_path(for_write=True), completed)
            self._execution_last_boundary = self._execution_boundary(pending)
            self._pending_execution_snapshot = None
            return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._pending_execution_snapshot = None
            raise

    def _recovery_machine_state(self, session, values=None, allow_invalid_recovery=False):
        """Read current prerequisites; caller still must serialize preparation."""
        if session != self.session_id or not isinstance(session, str):
            raise ValueError("Recovery printer session changed")
        now = self.printer.get_reactor().monotonic()
        if (self.printer.is_shutdown()
                or self.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"):
            raise ValueError("Printer is not ready for recovery")
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another filament manager owns recovery")
        if not self._idle_for_filament_settings(now, allow_invalid_recovery=allow_invalid_recovery):
            raise ValueError("Another print, pause or identification context owns the printer: " + getattr(self, "_idle_settings_refusal", "idle admission was not confirmed"))
        for name in ("filament_operation", "toolhead_operation"):
            operation = getattr(self, name, {})
            if self._material_operation_active(name):
                raise ValueError("Resolve the material or tool operation before recovery: %s.state=%s" % ("filament_operation" if operation is self.filament_operation else "toolhead_operation", str(operation.get("state"))[:80]))
        variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        if any(type(variables.get(key)) is not int or variables[key] != 0
               for key in ("is_nozzle_setting",)):
            raise ValueError("Inspect the head, then retry Head identification to clear interrupted setup before recovery: " + next(key + "=" + repr(variables.get(key))[:80] + "; expected integer 0" for key in ("is_nozzle_setting",) if type(variables.get(key)) is not int or variables[key] != 0))
        recovery = self.printer.lookup_object("wmp_recovery").get_status(now)
        if (recovery.get("homing") is not False or recovery.get("calibration_active") is not False
                or recovery.get("identification", {}).get("state") != "idle"):
            raise ValueError("Homing, calibration or identification prevents recovery: " +
                             ("homing=" + repr(recovery.get("homing"))[:80] if recovery.get("homing") is not False else
                              "calibration_active=" + repr(recovery.get("calibration_active"))[:80] if recovery.get("calibration_active") is not False else
                              "identification.state=" + repr(recovery.get("identification", {}).get("state"))[:80]))
        if self.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(now).get("active") is not False:
            raise ValueError("Recovery preparation is already active")
        attachment = self._attachment(now)
        if attachment.get("state") not in ("attached", "empty"):
            raise ValueError("Head attachment sensors disagree; inspect coupling before recovery")
        if values is not None:
            if values["last_is_during_T"]:
                raise ValueError("Interrupted tool-change recovery requires an explicit attachment recovery plan")
            targets = [("extruder" if i == 0 else "extruder%d" % i,
                        values["last_extruder%d_target" % i]) for i in range(4)]
            targets.append(("heater_bed", values["last_heater_bed_target"]))
            self._recovery_heater_state(now, targets)
        # Historical results are visible to review consistency, not permission
        # gates. A change during the read still invalidates that review.
        return {"session": session, "attachment": attachment,
                "fault_history": variables.get("fail_flag"),
                "calibration_history": recovery.get("calibration_failed")}

    def _recovery_heater_state(self, now, targets):
        settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
        for name, target in targets:
            heater = self.printer.lookup_object(name, None)
            if heater is None:
                if target != 0:
                    raise ValueError("Recovery heater is not installed: " + name)
                continue
            limits = settings.get(name, {})
            minimum, maximum = limits.get("min_temp"), limits.get("max_temp")
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (minimum, maximum))
                    or minimum >= maximum or (target != 0 and not minimum <= target <= maximum)):
                raise ValueError("Recovery target is outside configured heater limits: " + name)
            temperature = heater.get_status(now).get("temperature")
            if (type(temperature) not in (int, float) or not math.isfinite(temperature)
                    or not minimum <= temperature <= maximum):
                raise ValueError("Recovery heater temperature is unavailable or invalid: " + name)

    def _reconcile_recovery_continuation(self, session, request_id, execution_hash, review_only=False):
        """Release only a restart-interrupted handoff superseded by fresh evidence.

        This does not move, heat, invalidate the job or authorize continuation.
        A subsequent recovery still needs its complete current admission review.
        """
        runner = self._recovery_attempt
        receipt = runner.record
        if (runner.busy or receipt is None or receipt["state"] != "unknown"
                or receipt.get("continuation", {}).get("state") != "interrupted"
                or receipt["request"]["id"] != request_id
                or session != self.session_id or receipt["request"]["session"] == session):
            raise ValueError("No matching restart-interrupted continuation to reconcile")
        expected_receipt = copy.deepcopy(receipt)
        journal_bytes = self._recovery_read_bytes(self._recovery_attempt_path(), 65536)
        if json.loads(journal_bytes) != expected_receipt:
            raise ValueError("Recovery continuation journal changed")
        def guard():
            now = self.printer.get_reactor().monotonic()
            sd = self.printer.lookup_object("virtual_sdcard")
            saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            if (runner.record is not receipt or runner.record != expected_receipt
                    or self._recovery_read_bytes(self._recovery_attempt_path(), 65536) != journal_bytes
                    or self.session_id != session
                    or self.printer.lookup_object("gcode").get_mutex().test() != (not review_only)
                    or self.printer.is_shutdown()
                    or self.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None
                    or sd.is_active() or sd.is_cmd_from_sd()
                    or self.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False
                    or self.printer.lookup_object("print_stats").get_status(now).get("state") not in ("standby", "complete", "cancelled")
                    or any(saved.get(key) != 0 for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Recovery reconciliation ownership or idle state changed")
        guard()
        payload = self._recovery_read_bytes(self._recovery_execution_path(), 65536)
        if (self._recovery_fingerprint(payload) != execution_hash
                or execution_hash == receipt["request"]["execution_hash"]):
            raise ValueError("A new completed execution checkpoint is required")
        execution = self._read_completed_recovery_execution(receipt["request"]["file"])
        if (execution["session"] != receipt["request"]["session"]
                or execution["job_fingerprint"] != receipt["checkpoint"]["job_fingerprint"]
                or execution["file_position"] < receipt["checkpoint"]["file_position"]):
            raise ValueError("Completed checkpoint does not supersede this continuation")
        guard()
        if self._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload:
            raise ValueError("Recovery checkpoint changed during reconciliation")
        if review_only:
            return copy.deepcopy(runner.record)
        try:
            runner._save(state="complete", error="", continuation={"state": "checkpointed",
                         "file_position": execution["file_position"], "error": ""})
        except Exception:
            # A failed acknowledgement must not release the in-process hold.
            # The writer may have replaced the journal before reporting failure;
            # restore the unresolved receipt on disk where storage permits it.
            runner.record = expected_receipt
            try:
                runner.persist(copy.deepcopy(expected_receipt))
            except Exception:
                logging.exception("Unable to restore unresolved recovery reconciliation")
            raise
        return copy.deepcopy(runner.record)

    def _archive_recovery_evidence(self, evidence):
        """Publish immutable original bytes before retiring continuation authority."""
        if (set(evidence) not in ({"job", "execution"}, {"job", "execution", "offer"})
                or any(not isinstance(v, bytes) or not 0 < len(v) <= 65536 for v in evidence.values())):
            raise ValueError("Invalid recovery archive evidence")
        payload = json.dumps({"version": 1, "records": {k: v.hex() for k, v in evidence.items()}},
                             sort_keys=True).encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        path = os.path.join(os.path.dirname(self.profile_path), "wmp_recovery_archive_" + digest + ".json")
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-recovery-archive-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)  # Never overwrite an existing archive.
            except FileExistsError:
                if self._recovery_read_bytes(path, 450000) != payload:
                    raise wmp_recovery_retirement.ArchiveUnavailable("Recovery archive conflicts with preserved evidence")
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self._recovery_read_bytes(path, 450000) != payload:
                raise wmp_recovery_retirement.ArchiveUnavailable("Recovery archive readback differs")
            return digest
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _read_archived_recovery_evidence(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Original recovery archive is unavailable; inspect preserved records")
        path = os.path.join(os.path.dirname(self.profile_path), "wmp_recovery_archive_" + digest + ".json")
        try:
            payload = self._recovery_read_bytes(path, 450000)
        except FileNotFoundError as error:
            raise ValueError("Original recovery archive is missing; inspect preserved records") from error
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("Original recovery archive changed")
        value = json.loads(payload)
        if (not isinstance(value, dict) or set(value) != {"version", "records"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["records"], dict)
                or set(value["records"]) not in ({"job", "execution"}, {"job", "execution", "offer"})
                or any(not isinstance(v, str) or not 0 < len(v) <= 131072 or len(v) % 2
                       or not re.fullmatch(r"[0-9a-f]+", v) for v in value["records"].values())):
            raise ValueError("Invalid original recovery archive")
        return {k: bytes.fromhex(v) for k, v in value["records"].items()}

    def _recovery_offer(self, filename):
        """Bind the stock startup prompt to this file, without deleting checkpoints."""
        path = os.path.join(getattr(self, "recovery_checkpoint_dir", os.path.dirname(self.profile_path)), "plr.ini")
        try:
            raw = self._recovery_read_bytes(path, 65536)
        except FileNotFoundError:
            return path, None, None
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(raw.decode("utf-8"))
        if parser.defaults() or parser.sections() != ["plr_print"]:
            raise ValueError("Unrecognized native recovery offer")
        flag = parser.get("plr_print", "was_interrupted")
        if flag == "False":
            return path, raw, raw
        sd = self.printer.lookup_object("virtual_sdcard")
        if (flag != "True" or parser.get("plr_print", "plr_file") not in
                (filename, os.path.join(sd.sdcard_dirname, filename))):
            raise ValueError("Native recovery offer belongs to another file")
        updated, count = re.subn(rb"(?m)^(\s*was_interrupted\s*=\s*)True([ \t]*\r?$)",
                                 rb"\g<1>False\2", raw)
        if count != 1:
            raise ValueError("Unrecognized native recovery offer flag")
        return path, raw, updated

    def _clear_recovery_offer(self, path, before, after, guard):
        if before == after:
            return
        guard()
        if self._recovery_read_bytes(path, 65536) != before:
            raise ValueError("Native recovery offer changed before discard")
        fd, temporary = tempfile.mkstemp(prefix=".wmp-offer-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode))
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            guard()
            if self._recovery_read_bytes(path, 65536) != before:
                raise ValueError("Native recovery offer changed during discard")
            os.replace(temporary, path)
            directory = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self._recovery_read_bytes(path, 65536) != after:
                raise ValueError("Native recovery offer discard was not confirmed")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _recovery_archive_matches_attempt(self, evidence, receipt):
        if self._recovery_fingerprint(evidence["execution"]) != receipt["request"]["execution_hash"]:
            return False
        execution = json.loads(evidence["execution"])
        job = json.loads(evidence["job"])
        # Pre-archive versions already retired the original job. Preserve that
        # marker as evidence of the loss; never claim it is a committed job.
        legacy = (isinstance(job, dict) and set(job) in ({"version", "state", "reason", "id", "session"},
                                                {"version", "state", "reason", "id", "session", "job_fingerprint"})
                  and type(job["version"]) is int and job["version"] == 1
                  and job["state"] == "invalidated" and job["reason"] == "recovery-abandoned"
                  and job["id"] == receipt["request"]["id"]
                  and isinstance(job["session"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job["session"]))
        expected = job.get("job_fingerprint", receipt.get("checkpoint", {}).get("job_fingerprint")) if legacy else self._recovery_fingerprint(evidence["job"])
        return (isinstance(execution, dict) and isinstance(expected, str)
                and bool(re.fullmatch(r"[0-9a-f]{16}", expected)) and execution.get("job_fingerprint") == expected)

    def _abandon_recovery_attempt(self, session, request_id, review_only=False):
        """Explicit no-motion abandonment; caller owns the G-code mutex."""
        runner = self._recovery_attempt
        receipt = runner.record
        if (self._recovery_attempt_active() or self._print_cancel_active() or receipt is None or receipt["state"] not in ("unknown", "stopped")
                or receipt["request"]["id"] != request_id or session != self.session_id):
            raise ValueError("Recovery abandonment request is stale or not stopped")
        gcode = self.printer.lookup_object("gcode")
        reactor = self.printer.get_reactor()
        job_expected = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        job = json.loads(job_expected)
        already_invalidated = (job.get("state") == "invalidated" and job.get("reason") == "recovery-abandoned"
                               and job.get("id") == request_id)
        archive = None
        archive_warning = ""
        archive_evidence = None
        if already_invalidated and "archive" in job:
            archive = job["archive"]
            try:
                archive_evidence = self._read_archived_recovery_evidence(archive)
            except (OSError, ValueError) as error:
                # The current marker still binds this exact stopped attempt.
                # Missing diagnostic bytes cannot veto its explicit dismissal.
                archive_warning = str(error)[:512]
                logging.warning("Recovery discard original archive unavailable: %s", archive_warning)
                archive = None
                payload = self._recovery_read_bytes(self._recovery_execution_path(), 65536)
                if self._recovery_fingerprint(payload) != receipt["request"]["execution_hash"]:
                    raise ValueError("Another job owns the recovery execution")
            else:
                if not self._recovery_archive_matches_attempt(archive_evidence, receipt):
                    raise ValueError("Another job owns the original recovery archive")
        else:
            payload = self._recovery_read_bytes(self._recovery_execution_path(), 65536)
            if not self._recovery_archive_matches_attempt({"job": job_expected, "execution": payload}, receipt):
                raise ValueError("Another job owns the recovery evidence")
        def status(name):
            return self.printer.lookup_object(name).get_status(reactor.monotonic())
        def stopped():
            nonlocal archive_warning
            if (runner.record is not receipt or self.session_id != session or (not review_only and not gcode.get_mutex().test())
                    or self.printer.lookup_object("openace", None) is not None or self.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Recovery abandonment ownership is unavailable")
            if self._recovery_read_bytes(self._recovery_job_path(), 65536) != job_expected:
                raise ValueError("Recovery job changed during abandonment")
            if archive is not None and archive_evidence is not None and not archive_warning:
                try:
                    if self._read_archived_recovery_evidence(archive) != archive_evidence:
                        raise ValueError("Recovery diagnostic archive changed")
                except (OSError, ValueError) as error:
                    archive_warning = str(error)[:512]
                    logging.warning("Recovery discard archive unavailable: %s", archive_warning)
            sd = self.printer.lookup_object("virtual_sdcard")
            if not review_only and (sd.is_active() or sd.is_cmd_from_sd() or status("pause_resume").get("is_paused") is not False
                    or status("print_stats").get("state") not in ("standby", "complete", "cancelled", "error")):
                raise ValueError("A print or pause is still active")
            stream = getattr(sd, "current_file", None)
            if not review_only and stream is not None and os.path.realpath(stream.name) != os.path.realpath(
                    os.path.join(sd.sdcard_dirname, receipt["request"]["file"])):
                raise ValueError("Another file is selected; recovery abandonment did not close it")
            return {"state": "unknown", "head": ""}
        attachment = stopped()
        offer_path, offer_before, offer_after = self._recovery_offer(receipt["request"]["file"])
        if review_only:
            return copy.deepcopy(runner.record)
        runner.busy = True
        try:
            # Preserve the original bytes before retiring continuation authority.
            # A retry after partial cleanup retains the original archive reference.
            if archive is None:
                if self._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload:
                    raise ValueError("Recovery execution changed before archival")
                archive_evidence = {"job": job_expected, "execution": payload}
                if offer_before is not None and offer_before != offer_after:
                    archive_evidence["offer"] = offer_before
                try:
                    archive = self._archive_recovery_evidence(archive_evidence)
                except (OSError, wmp_recovery_retirement.ArchiveUnavailable) as error:
                    archive_warning = str(error)[:512]
                    logging.warning("Recovery discard archive unavailable: %s", archive_warning)
                if stopped() != attachment or self._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload:
                    raise ValueError("Recovery evidence changed during archival")
            elif offer_before is not None and offer_before != offer_after and "offer" not in archive_evidence:
                # Upgrade a retry of an older abandonment without losing its
                # original job/execution bytes or mutating the old archive.
                upgraded = dict(archive_evidence, offer=offer_before)
                try:
                    archive = self._archive_recovery_evidence(upgraded)
                    archive_evidence = upgraded
                except (OSError, wmp_recovery_retirement.ArchiveUnavailable) as error:
                    archive_warning = str(error)[:512]
                    logging.warning("Recovery discard archive upgrade unavailable: %s", archive_warning)
            # Invalidate durable continuation authority before clearing runtime
            # flags or closing the selected file. A partial failure stays visible.
            invalidated = {"version": 1, "state": "invalidated", "reason": "recovery-abandoned",
                           "id": request_id, "session": session}
            if archive is not None:
                invalidated["archive"] = archive
            else:
                # Bind a retry after partial publication without requiring the
                # original diagnostic archive to have been writable.
                invalidated["job_fingerprint"] = json.loads(payload)["job_fingerprint"]
            # Archival is diagnostic; invalidation and its readback are required.
            self._write_recovery_job(invalidated)
            job_expected = self._recovery_read_bytes(self._recovery_job_path(), 65536)
            if json.loads(job_expected) != invalidated:
                raise ValueError("Recovery abandonment evidence changed")
            for script in ("SDCARD_RESET_FILE", "SET_GCODE_VARIABLE MACRO=_WMP_RECOVERY_BEGIN VARIABLE=active VALUE=False",
                           "SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False",
                           'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="{}"'):
                if stopped() != attachment:
                    raise ValueError("Recovery dismissal context changed")
                gcode.run_script_from_command(script)
            if (stopped() != attachment or self.printer.lookup_object("virtual_sdcard").current_file is not None
                    or status("gcode_macro _WMP_RECOVERY_BEGIN").get("active") is not False
                    or status("gcode_macro START_PRINT").get("print_body_ready") is not False
                    or status("save_variables")["variables"].get("wmp_print_context") != {}):
                raise ValueError("Recovery abandonment was not confirmed")
            self._clear_recovery_offer(offer_path, offer_before, offer_after, stopped)
            runner._save(state="abandoned", resolution={"session": session, "attachment": attachment})
            result = copy.deepcopy(runner.record)
            if archive_warning:
                result["archive_warning"] = archive_warning
            return result
        except Exception:
            runner.record["state"] = "unknown"
            try:
                runner.persist(copy.deepcopy(runner.record))
            except Exception:
                pass
            raise
        finally:
            runner.busy = False

    def _stop_recovery_heaters(self, review):
        """Best-effort heater-only cleanup; never moves or resolves the attempt."""
        names = sorted(review["execution"]["heater_targets"])
        allowed = {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
        if set(names) - allowed:
            raise ValueError("Invalid recovery cleanup heater")
        gcode = self.printer.lookup_object("gcode")
        result = {"state": "complete", "heaters": {}, "error": ""}
        errors = []
        for name in names:
            try:
                if (self.session_id != review["machine"]["session"] or not gcode.get_mutex().test()
                        or self.printer.is_shutdown() or self.printer.lookup_object("openace", None) is not None
                        or self.printer.lookup_object("AFC", None) is not None):
                    raise ValueError("Recovery cleanup command ownership is unavailable")
                gcode.run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % name)
                target = self.printer.lookup_object(name).get_status(self.printer.get_reactor().monotonic()).get("target")
                if type(target) not in (int, float) or target != 0:
                    raise ValueError("Heater-off target was not confirmed")
                result["heaters"][name] = True
            except Exception as error:
                result["heaters"][name] = False
                errors.append(name + ": " + str(error))
        if errors:
            result.update(state="unknown", error="; ".join(errors))
        self._recovery_temperatures = {}
        return result

    def _run_recovery_stages(self, request, review, stages, cancelled=lambda: False):
        """Run an admitted chain under the caller's command mutex, with cleanup."""
        review = copy.deepcopy(review)
        RecoveryAttempt._validate_request(request)
        if (request["session"] != review["machine"]["session"]
                or request["execution_hash"] != review["execution_hash"]
                or request["file"] != review["execution"]["file"]["path"]):
            raise ValueError("Recovery request differs from its admitted evidence")
        runner = self._recovery_attempt
        previous = runner.record
        def cleanup():
            if runner.record is previous or runner.record is None or runner.record["state"] == "complete":
                return
            if runner.record.get("continuation", {}).get("state") == "scheduled":
                runner.record["continuation"].update(state="unknown", error=runner.record["error"])
                runner.record["state"] = "unknown"
            disarm_error = ""
            try:
                self._recovery_disarm_worker()
            except Exception as error:
                disarm_error = str(error)
            accounting_error = ""
            if any(stage["name"] == "accounting" and stage["state"] != "pending"
                   for stage in runner.record["stages"]):
                try:
                    sd = self.printer.lookup_object("virtual_sdcard")
                    stats = self.printer.lookup_object("print_stats")
                    gcode = self.printer.lookup_object("gcode")
                    execution = review["execution"]
                    identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
                    if (self.session_id != request["session"] or not gcode.get_mutex().test()
                            or self.printer.lookup_object("openace", None) is not None
                            or self.printer.lookup_object("AFC", None) is not None
                            or sd.is_active() or sd.is_cmd_from_sd()
                            or stats.filename != execution["file"]["path"]
                            or sd.file_position != execution["file_position"]
                            or self._recovery_active_file(sd, identity) != self._print_file(sd, identity)):
                        raise ValueError("Recovery accounting cleanup lost ownership")
                    if stats.state == "printing":
                        stats.note_cancel()
                    if stats.state not in ("standby", "cancelled"):
                        raise ValueError("Recovery accounting stop was not confirmed")
                except Exception as error:
                    accounting_error = str(error)
            touched = any(stage["name"] == "heater_targets" and stage["state"] != "pending"
                          for stage in runner.record["stages"])
            result = self._stop_recovery_heaters(review) if touched else {"state": "complete", "heaters": {}, "error": ""}
            if disarm_error or accounting_error:
                result.update(state="unknown", error="; ".join(filter(None,
                    (result.get("error", ""), disarm_error, accounting_error))))
            if result["state"] != "complete":
                runner.record["state"] = "unknown"
            try:
                runner._save(cleanup=result)
            except Exception:
                runner.record["state"] = "unknown"
                raise
        try:
            runner.run(request, stages, cancelled)
            if runner.record["state"] == "complete":
                try:
                    if getattr(self, "_recovery_pending_worker", None) is not None and cancelled():
                        raise ValueError("Recovery stopped before worker activation")
                    self._recovery_activate_worker(request)
                except Exception as error:
                    runner.record.update(state="unknown", error=str(error))
                    raise
        except Exception:
            try:
                cleanup()
            except Exception:
                pass  # Preserve the original failure; retained outcome is unknown.
            raise
        if runner.record["state"] != "complete":
            cleanup()
        return copy.deepcopy(runner.record)

    def cmd_FAILED_PICKUP_CLEANUP(self, gcmd):
        """Stock protective release only at the supported, completed pickup approach.

        This is reached after LOCK returned, not after an actuator exception.
        It always raises the pickup failure, retiring the outer macro tail.
        """
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        def status(name):
            return self.printer.lookup_object(name).get_status(reactor.monotonic())
        def guard():
            self._check_command_generation(gcmd)
            if self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Pickup cleanup stopped: printer shutdown or stop requested")
            if not gcode.get_mutex().test():
                raise gcmd.error("Pickup cleanup requires command ownership")
            saved = status("save_variables")["variables"]
            if type(saved.get("fail_flag")) is not int or saved["fail_flag"] != 0:
                raise gcmd.error("Pickup cleanup stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        guard()
        stage = "dock support"
        message = ""
        try:
            self.printer.lookup_object("toolhead").wait_moves()
            saved = guard()
            position = status("gcode_move")["position"]
            dock = saved.get("t%d_position" % head)
            homed = status("toolhead").get("homed_axes", "")
            if (not all(axis in homed for axis in "xy")
                    or not isinstance(dock, (list, tuple)) or len(dock) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in dock)
                    or any(not math.isfinite(float(position[i])) or
                           abs(float(position[i]) - (dock[i] + (.4 if i == 1 else 0.))) > 1e-5
                           for i in (0, 1))):
                raise ValueError("carriage is not at the completed Head %d dock approach" % (head + 1))
            docked = status("filament_switch_sensor docked%d" % head).get("filament_detected")
            if docked is not True:
                raise ValueError("docked%d=%r; expected True before protective unlock" % (head, docked))
            stage = "unlock"
            # Verified actuator release precedes retreat. Head presence at the
            # dock is ambiguous and must NOT be used as a pre-retreat veto.
            self._recovery_actuator_stroke(False, guard)
            stage = "retreat"
            for command in ("G90", "G0 Y310 F9600", "G0 Y270 F12000", "M400"):
                guard()
                gcode.run_script_from_command(command)
            guard()
            stage = "detachment"
            hall = status("custom_hall").get("Raw")
            locked = status("filament_switch_sensor sensor_b").get("filament_detected")
            docked = status("filament_switch_sensor docked%d" % head).get("filament_detected")
            if (type(hall) not in (int, float) or not math.isfinite(hall)
                    or hall < 4700 or locked is not False or docked is not True):
                raise ValueError("after retreat hall=%r (expected >=4700), sensor_b=%r (expected False), "
                                 "docked%d=%r (expected True)" % (hall, locked, head, docked))
            guard()["current_extruder"] = 99
            message = "Pickup failed; Head %d released in its dock. Resume or retry to try pickup again" % (head + 1)
        except Exception as error:
            # A canceled/replaced owner gets no new fault or cleanup commands.
            guard()
            message = "Head %d pickup failed; protective cleanup stopped at %s: %s" % (head + 1, stage, error)
        saved = guard()
        saved["fail_flag"] = -2  # Current attempt only; no durable permission latch.
        self._command_generation = getattr(self, "_command_generation", 0) + 1
        logging.warning(message)
        error = gcmd.error(message)
        error.wmp_toolchange_fault = (-2, "pickup_cleanup")
        raise error

    def cmd_CHECK_DOCK_SUPPORT(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        def guard():
            self._check_command_generation(gcmd)
            if self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Dock support verification stopped; inspect the current printer state")
            saved = self.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            if saved.get("fail_flag", 0) != 0:
                raise gcmd.error("Dock support verification stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        def read(name, field):
            try:
                return self.printer.lookup_object(name, None).get_status(reactor.monotonic()).get(field)
            except (AttributeError, KeyError, TypeError, ValueError):
                return None
        guard()
        start = reactor.monotonic()
        name = "filament_switch_sensor docked%d" % head
        initial = observed = read(name, "filament_detected")
        # M400 completes motion, not delivery of the MCU button report. Give
        # queued callbacks up to 0.5s while stationary. A missing/unknown support
        # signal never permits unlock; there is no re-dock or coupling retry.
        while observed is not True and reactor.monotonic() - start < .5:
            reactor.pause(min(start + .5, reactor.monotonic() + .05))
            guard()  # Cancellation/new ownership retires this old observation.
            observed = read(name, "filament_detected")
        saved = guard()
        elapsed = reactor.monotonic() - start
        hall = read("custom_hall", "Raw")
        locked = read("filament_switch_sensor sensor_b", "filament_detected")
        logging.info("Pre-unlock dock check head=%d initial=%r final=%r elapsed=%.3fs hall=%r sensor_b=%r",
                     head, initial, observed, elapsed, hall, locked)
        if observed is True:
            return
        # Current-attempt fault only. Never require a diagnostic disk write or
        # clear an earlier fault; a fresh explicit user action can retry later.
        saved["fail_tool"] = head
        saved["fail_flag"] = -3
        self._command_generation = getattr(self, "_command_generation", 0) + 1
        error = gcmd.error("Head %d dock support not confirmed after %.3fs: docked%d=%r (initial=%r; expected True before unlock). "
                         "Check that the head is fully seated in its dock, then retry. Unlock was not attempted."
                         % (head + 1, elapsed, head, observed, initial))
        error.wmp_toolchange_fault = (-3, "dock_sensor")
        raise error

    def cmd_CHECK_PICKUP_RELEASE(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        def guard():
            self._check_command_generation(gcmd)
            if self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Pickup verification stopped; inspect the current printer state")
            saved = self.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            if saved.get("fail_flag", 0) != 0:
                raise gcmd.error("Pickup verification stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        def read(name, field):
            try:
                return self.printer.lookup_object(name).get_status(reactor.monotonic()).get(field)
            except (AttributeError, KeyError, TypeError, ValueError):
                return None
        guard()
        start = reactor.monotonic()
        name = "filament_switch_sensor docked%d" % head
        initial = observed = read(name, "filament_detected")
        # M400 completes motion, not delivery of the MCU button report. Give
        # queued callbacks up to 0.5s while stationary; this is not a new stroke,
        # homing retry, or permission to ignore a persistently occupied dock.
        while observed is not False and reactor.monotonic() - start < .5:
            reactor.pause(min(start + .5, reactor.monotonic() + .05))
            guard()  # Cancellation/new ownership retires this old observation.
            observed = read(name, "filament_detected")
        saved = guard()
        elapsed = reactor.monotonic() - start
        hall = read("custom_hall", "Raw")
        locked = read("filament_switch_sensor sensor_b", "filament_detected")
        logging.info("Pickup dock check head=%d initial=%r final=%r elapsed=%.3fs hall=%r sensor_b=%r",
                     head, initial, observed, elapsed, hall, locked)
        if observed is False:
            return
        # Current-attempt fault only. Never require a diagnostic disk write or
        # clear an earlier fault; a fresh explicit user action can retry later.
        saved["fail_flag"] = -5
        self._command_generation = getattr(self, "_command_generation", 0) + 1
        error = gcmd.error("Head %d pickup not confirmed after %.3fs: docked%d=%r (initial=%r; expected False after retreat). "
                         "Inspect the picked-up head and its dock switch, then retry; no automatic motion was repeated."
                         % (head + 1, elapsed, head, observed, initial))
        error.wmp_toolchange_fault = (-5, "pickup_dock_sensor")
        raise error

    def cmd_COUPLING_STROKE(self, gcmd):
        lock = gcmd.get_int("LOCK", minval=0, maxval=1) == 1
        retry = gcmd.get_int("RETRY", 0, minval=0, maxval=4)
        if retry and not lock:
            raise gcmd.error("Confirmation retry requires LOCK=1")
        gcode = self.printer.lookup_object("gcode")
        def guard():
            self._check_command_generation(gcmd)
            if self.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Coupling stopped; inspect the printer before recovery")
            now = self.printer.get_reactor().monotonic()
            saved = self.printer.lookup_object("save_variables").get_status(now).get("variables", {})
            if type(saved.get("fail_flag")) is not int or saved["fail_flag"] != 0:
                raise gcmd.error("Resolve the existing toolhead fault before coupling")
        guard()
        try:
            # LOCK/UNLOCK retain their original successful motor-disable timing.
            if retry:
                # Stock absolute confirmation positions, not homing strokes.
                # The vendor move command propagates errors and owns timing.
                gcode.run_script_from_command(
                    "ECHELON_STEPPER STEPPER=trans_stepper SPEED=10 MOVE=%d" %
                    (-125 - retry * 10))
                guard()
            else:
                self._recovery_actuator_stroke(lock, guard, disable_on_success=False)
        except Exception as error:
            try:
                guard()
            except Exception:
                raise gcmd.error(str(error)) from error
            if retry:
                # The failed move bypassed LOCK's final disable. Only clean up
                # this still-owned actuator; retain the original move error.
                try:
                    self.printer.lookup_object("echelon_stepper trans_stepper").do_enable(False)
                except Exception:
                    pass
                try:
                    guard()
                except Exception:
                    raise gcmd.error(str(error)) from error
            expected_fault = -2 if lock else -3
            now = self.printer.get_reactor().monotonic()
            saved = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            saved["fail_flag"] = expected_fault
            self._command_generation = getattr(self, "_command_generation", 0) + 1
            logging.warning("Coupling attempt stopped (fail_flag=%d): %s", expected_fault, error)
            failure = gcmd.error(str(error))
            failure.wmp_toolchange_fault = (expected_fault, "coupling_stroke")
            raise failure from error

    def _recovery_actuator_stroke(self, lock, guard, disable_on_success=True):
        """Use the vendor actuator API below its exception-swallowing command."""
        guard()
        gcode = self.printer.lookup_object("gcode")
        if type(lock) is not bool or not gcode.get_mutex().test():
            raise ValueError("Recovery actuator requires direction and command ownership")
        actuator = self.printer.lookup_object("echelon_stepper trans_stepper", None)
        required = ("do_homing_move", "do_set_position", "do_move", "do_enable")
        if (actuator is None or any(not callable(getattr(actuator, name, None)) for name in required)
                or type(getattr(actuator, "accel", None)) not in (int, float)
                or not math.isfinite(actuator.accel) or actuator.accel < 0):
            raise ValueError("Supported recovery coupling actuator is unavailable")
        try:
            # do_homing_move propagates manual_home failure. The public vendor
            # command catches it and still sends PDI, so must not be called here.
            actuator.do_homing_move(150., 100., actuator.accel, True, 1)
            guard()
            actuator.do_set_position(0.)
            if lock:
                actuator.do_move(-125., 100., actuator.accel, True)
            self.printer.lookup_object("toolhead").wait_moves()
            guard()
            if disable_on_success:
                actuator.do_enable(False)
        except Exception:
            # Preserve the original error. Do not command a changed owner/session
            # even for cleanup; the attempt remains unknown and cannot continue.
            try:
                guard()
                actuator.do_enable(False)
            except Exception:
                pass
            raise

    def _recovery_couple_head(self, lock, guard):
        """One coupling attempt; never enter stock LOCK/_LOCK_CHECK retries.

        The caller owns dock positioning and verifies seating before release.
        A verified coupling alone does not prove which physical head is mounted.
        """
        if type(lock) is not bool:
            raise ValueError("Invalid recovery coupling direction")
        guard()
        gcode = self.printer.lookup_object("gcode")
        if not gcode.get_mutex().test():
            raise ValueError("Recovery coupling requires command ownership")
        self._recovery_actuator_stroke(lock, guard)
        guard()
        if not lock:
            # The caller must retreat and verify an empty attachment before
            # further travel. Presence readings at the dock are ambiguous.
            return True
        now = self.printer.get_reactor().monotonic()
        hall = self.printer.lookup_object("custom_hall").get_status(now).get("Raw")
        detected = self.printer.lookup_object("filament_switch_sensor sensor_b").get_status(now).get("filament_detected")
        valid_hall = type(hall) in (int, float) and math.isfinite(hall)
        confirmed = valid_hall and ((3450 <= hall < 4700 and detected is True) if lock
                                    else (hall >= 4700 and detected is False))
        if not confirmed:
            raise ValueError("Recovery coupling did not %s; inspect attachment before continuing" %
                             ("lock" if lock else "release"))
        return True

    def _recovery_bottom_reference(self, toolhead_state):
        """Native homing ends at position_endstop, not the travel maximum."""
        now = self.printer.get_reactor().monotonic()
        settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
        z = settings.get("stepper_z", {})
        bottom = z.get("position_endstop")
        low, high = toolhead_state.get("axis_minimum"), toolhead_state.get("axis_maximum")
        if (z.get("homing_positive_dir") is not True
                or type(bottom) not in (int, float) or not math.isfinite(bottom)
                or not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple))
                or len(low) < 3 or len(high) < 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (low[2], high[2]))
                or not low[2] < bottom <= high[2]):
            raise ValueError("Recovery bottom endstop is unavailable or outside travel bounds")
        return float(bottom)

    def _recovery_select_head(self, head, context, guard):
        """Select a physical head at the verified bottom reference.

        The outer guard checks job/session/owner/faults, not a fixed attachment:
        this operation deliberately changes attachment, verified at each boundary.
        It leaves offsets zero and does not purge or return to the print.
        """
        if type(head) is not int or not 0 <= head < 4:
            raise ValueError("Invalid recovery physical head")
        context = copy.deepcopy(context)
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        def status(name):
            return self.printer.lookup_object(name).get_status(reactor.monotonic())
        def check():
            guard()
            if not gcode.get_mutex().test():
                raise ValueError("Recovery head selection requires command ownership")
            th, recovery = status("toolhead"), status("wmp_recovery")
            maximum, minimum = th["axis_maximum"], th["axis_minimum"]
            z = th["position"][2]
            if (not all(axis in th.get("homed_axes", "") for axis in "xyz")
                    or recovery.get("z_reference_valid") is not True
                    or recovery.get("homing") is not False
                    or type(z) not in (int, float) or not math.isfinite(z)
                    or not math.isclose(z, self._recovery_bottom_reference(th), abs_tol=.05, rel_tol=0)):
                raise ValueError("Recovery head selection requires the bottom reference")
            positions = context["positions"]
            saved = status("save_variables")["variables"]
            if (len(positions) != 4 or positions != [saved.get("t%d_position" % i) for i in range(4)]
                    or any(type(saved.get(k)) is not int or saved[k] != 0
                           for k in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Recovery dock calibration or fault state changed")
            if not minimum[1] <= 270 < 310 <= maximum[1]:
                raise ValueError("Recovery dock approach exceeds travel limits")
            for point in positions:
                if (not isinstance(point, (list, tuple)) or len(point) != 2
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
                        or not minimum[0] <= point[0] <= maximum[0]
                        or not 310 <= point[1] <= maximum[1] - .4):
                    raise ValueError("Invalid recovery dock calibration")
        def run(script):
            check()
            gcode.run_script_from_command(script)
            check()
        def attachment(expected):
            check()
            if self._attachment(reactor.monotonic()) != expected:
                raise ValueError("Recovery head attachment is not confirmed")
        check()
        current = context["attachment"]
        if current not in ([{"state": "empty", "head": ""}] +
                           [{"state": "attached", "head": "h%d" % i} for i in range(4)]):
            raise ValueError("Invalid recovery attachment evidence")
        attachment(current)
        target = {"state": "attached", "head": "h%d" % head}
        run("G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
        if current != target:
            if current["head"]:
                index = int(current["head"][1])
                x, y = context["positions"][index]
                run("G1 Y270 F6000\nG1 X%.5f F6000\nG1 Y310 F6000\nG1 Y%.5f F1000\nG4 P1000\nM400" % (x, y))
                if status("filament_switch_sensor docked%d" % index).get("filament_detected") is not True:
                    raise ValueError("Recovery head is not seated in its dock")
                self._recovery_couple_head(False, check)
                run("G1 Y310 F6000\nM400")
                attachment({"state": "empty", "head": ""})
            x, y = context["positions"][head]
            if status("filament_switch_sensor docked%d" % head).get("filament_detected") is not True:
                raise ValueError("Recovery target head is not in its dock")
            run("G1 Y310 F6000\nG1 X%.5f F6000\nG1 Y%.5f F6000\nM400" % (x, y + .4))
            self._recovery_couple_head(True, check)
            run("G1 Y310 F6000\nG1 Y270 F6000\nM400")
        attachment(target)
        heater = "extruder" + (str(head) if head else "")
        run("ACTIVATE_EXTRUDER EXTRUDER=%s\nSAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % (heater, head))
        attachment(target)
        if (status("toolhead").get("extruder") != heater
                or status("save_variables")["variables"].get("current_extruder") != head):
            raise ValueError("Recovery extruder activation was not confirmed")
        return True

    def _recovery_initial_stages(self, review, cancelled=lambda: False, continue_print=False):
        """Initial owned preparation stages, not a complete recovery procedure."""
        review = copy.deepcopy(review)
        execution, admitted = review["execution"], review["machine"]
        self._verify_recovery_native_selection(review)
        job_bytes = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        if self._recovery_fingerprint(job_bytes) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed before preparation")
        record = json.loads(job_bytes)
        if self._recovery_clearance_evidence(execution) != review.get("deposition"):
            raise ValueError("Recovery clearance evidence changed before preparation")
        gcode = self.printer.lookup_object("gcode")
        reactor = self.printer.get_reactor()
        def status(name):
            return self.printer.lookup_object(name).get_status(reactor.monotonic())
        expected_attachment = copy.deepcopy(admitted["attachment"])
        reference_z = self._recovery_bottom_reference(status("toolhead"))
        if continue_print and not self._install_deposition_observer():
            raise ValueError("Recovery requires a supported deposition observer")
        restored_envelope = [None]
        handoff = {"accounting": False, "queued": False}
        dock_positions = copy.deepcopy([status("save_variables")["variables"].get("t%d_position" % i) for i in range(4)])
        def guard(check_attachment=True):
            if not gcode.get_mutex().test() or self.session_id != admitted["session"]:
                raise ValueError("Recovery command ownership or session changed: " + ("G-code mutex is not held" if not gcode.get_mutex().test() else "printer session differs from admitted session"))
            self._verify_recovery_native_selection(review)
            if self._recovery_bottom_reference(status("toolhead")) != reference_z:
                raise ValueError("Recovery bottom endstop changed during preparation")
            if self._recovery_clearance_evidence(execution) != review["deposition"]:
                raise ValueError("Recovery clearance evidence changed during preparation")
            if restored_envelope[0] is not None:
                self._verify_deposition_observer(restored_envelope[0], review["deposition"]["record"])
            if (self.printer.is_shutdown() or status("webhooks").get("state") != "ready"
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Recovery readiness or owner changed")
            sd = self.printer.lookup_object("virtual_sdcard")
            pending = getattr(self, "_recovery_pending_worker", None)
            own_worker = handoff["queued"] and pending is not None and pending["sd"] is sd and sd.work_timer is pending["timer"]
            allowed_stats = ("standby", "complete", "cancelled", "error", "printing") if handoff["accounting"] else ("standby", "complete", "cancelled", "error")
            if ((sd.is_active() and not own_worker) or sd.is_cmd_from_sd()
                    or status("pause_resume").get("is_paused") is not False
                    or status("print_stats").get("state") not in allowed_stats):
                raise ValueError("Another print context interrupted recovery")
            saved = status("save_variables")["variables"]
            if (self._recovery_context(saved.get("wmp_print_context")) != self._recovery_context(record["context"])
                    or self._recovery_offsets([saved.get("t%d_offset" % i) for i in range(4)]) != record["context"]["offsets"]
                    or any(type(saved.get(key)) is not int or saved[key] != 0 for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Recovery calibration, context or fault state changed")
            for name in ("filament_operation", "toolhead_operation"):
                if self._material_operation_active(name):
                    raise ValueError("Service operation interrupted recovery preparation")
            loaded = self._loaded_filament_status(reactor.monotonic())
            for key, saved_source in record["heads"].items():
                if (not self._loaded_source_matches(loaded.get(key, {}), saved_source)):
                    raise ValueError("Loaded source changed during recovery preparation")
            if check_attachment and self._attachment(reactor.monotonic()) != expected_attachment:
                raise ValueError("Head attachment changed during reference preparation")
            if self._recovery_fingerprint(self._recovery_read_bytes(self._recovery_job_path(), 65536)) != execution["job_fingerprint"]:
                raise ValueError("Recovery job changed during reference preparation")
        def dispatch(script):
            guard()
            gcode.run_script_from_command(script)
        def context_ok():
            guard()
            saved = status("save_variables")["variables"]
            return (status("gcode_macro _WMP_RECOVERY_BEGIN").get("active") is True
                    and status("gcode_macro START_PRINT").get("print_body_ready") is False
                    and saved.get("probe_tool") == record["context"]["tool"])
        def bottom_ok():
            guard()
            recovery = status("wmp_recovery")
            state = status("toolhead")
            pose = state.get("position", [])
            return (recovery.get("z_reference_valid") is True and recovery.get("homing") is False
                    and "z" in state.get("homed_axes", "") and len(pose) == 4
                    and type(pose[2]) in (int, float) and math.isfinite(pose[2])
                    and math.isclose(pose[2], reference_z, abs_tol=.05, rel_tol=0))
        def xy_ok():
            return bottom_ok() and all(axis in status("toolhead").get("homed_axes", "") for axis in "xy")
        frame_ready = [False]
        def travel_frame():
            self._recovery_machine_frame(guard)
            frame_ready[0] = True
        def frame_ok():
            return xy_ok() and frame_ready[0]
        def select_head():
            nonlocal expected_attachment
            guard()
            def selecting_guard():
                if cancelled():
                    raise ValueError("Recovery head selection stopped; inspect attachment")
                guard(check_attachment=False)
            context = {"attachment": copy.deepcopy(expected_attachment), "positions": dock_positions}
            self._recovery_select_head(int(execution["head"][1:]), context, selecting_guard)
            expected_attachment = {"state": "attached", "head": execution["head"]}
            guard()
        def selected_ok():
            guard()
            head = int(execution["head"][1:])
            heater = "extruder" + (str(head) if head else "")
            return (expected_attachment == {"state": "attached", "head": execution["head"]}
                    and status("toolhead").get("extruder") == heater
                    and status("save_variables")["variables"].get("current_extruder") == head)
        def set_heaters():
            guard()
            targets = execution["heater_targets"]
            self._recovery_heater_state(reactor.monotonic(), targets.items())
            for name, target in sorted(targets.items()):
                # Physical heater names bypass logical M104/M109 tool mapping.
                dispatch("SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.17g" % (name, target))
        def heaters_ok():
            guard()
            return all(math.isclose(status(name).get("target", float("nan")), target,
                                    rel_tol=1e-10, abs_tol=1e-10)
                       for name, target in execution["heater_targets"].items())
        warned_fans = set()
        def fan_targets():
            targets = []
            for name, speed in sorted(execution["fans"].items()):
                if self.printer.lookup_object(name, None) is None:
                    if name == "fan":
                        raise ValueError("Required part-cooling fan is not installed: " + name)
                    if name not in warned_fans:
                        message = "Optional cooling fan is not installed; restoration skipped: " + name
                        logging.warning(message)
                        respond = getattr(gcode, "respond_info", None)
                        if callable(respond):
                            respond(message)
                        warned_fans.add(name)
                    continue
                targets.append((name, speed))
            return targets
        def set_fans():
            for name, speed in fan_targets():
                if name == "fan":
                    # Stock M106 truncates S to an integer. Its renamed native
                    # command accepts the full captured fraction without loss.
                    script = "M99106 S%.17g" % (speed * 255.)
                else:
                    script = "SET_FAN_SPEED FAN=%s SPEED=%.17g" % (name.split(" ", 1)[1], speed)
                dispatch(script)
        def stage_completed():
            # Movement/priming helpers already verify their semantic result with
            # tolerances. Do not recompare returned software poses by exact
            # equality (native Coord/rounding previously stopped a valid purge).
            guard()
            return True
        def purge_position():
            def moving_guard():
                guard()
                if cancelled():
                    raise ValueError("Recovery purge travel stopped")
            y = status("toolhead")["position"][1]
            self._recovery_bottom_xy([[-13., y], [-13., 80.]], moving_guard)
        purge_amount = getattr(self, "recovery_purge_mm", getattr(self, "load_purge_mm", 50.))
        def prime():
            def priming_guard():
                guard()
                if cancelled():
                    raise ValueError("Recovery priming stopped; do not repeat the purge")
            self._recovery_prime(execution, purge_amount, priming_guard)
        wipe_position = copy.deepcopy(status("save_variables")["variables"].get("wipe_position", [-13., 240.]))
        wipe_macro = self.printer.lookup_object("gcode_macro WIPE_NOZZLE", None)
        wipe_speed = wipe_macro.get_status(reactor.monotonic()).get("wipe_speed", 12000.) if wipe_macro else 12000.
        def wipe():
            def wiping_guard():
                guard()
                if cancelled():
                    raise ValueError("Recovery wiping stopped")
                if status("save_variables")["variables"].get("wipe_position", [-13., 240.]) != wipe_position:
                    raise ValueError("Recovery wipe calibration changed")
            wiping_guard()
            if (not isinstance(wipe_position, (list, tuple)) or len(wipe_position) != 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in wipe_position)
                    or wipe_position[0] >= 0):
                raise ValueError("Recovery requires an off-bed wipe position")
            x, y = wipe_position
            # Match the configured stock four 35-mm strokes without its hidden
            # homing, clearance, state restore or other preparation commands.
            points = [[x, 80.]] + [[x, y], [x, y + 35.]] * 4
            self._recovery_bottom_xy(points, wiping_guard, feed=wipe_speed)
        def returning_guard():
            guard()
            if cancelled():
                raise ValueError("Recovery return stopped; inspect position before continuing")
        def return_xy():
            returning_guard()
            state = status("toolhead")
            target = execution["machine_position"]
            if any(not state["axis_minimum"][i] <= target[i] <= state["axis_maximum"][i] for i in range(3)):
                raise ValueError("Recovery return endpoint exceeds current limits")
            x = state["position"][0]
            self._recovery_bottom_xy([[x, target[1]], target[:2]], returning_guard)
        def return_z():
            self._recovery_return_z(execution, returning_guard)
        parser_ready = [False]
        def restore_parser():
            parser_ready[0] = self._restore_recovery_parser(execution, returning_guard)
        def parser_ok():
            return stage_completed() and parser_ready[0]
        selected_file = []
        def select_file():
            selected_file[:] = [self._recovery_select_file(execution, returning_guard)]
        def file_ok():
            returning_guard()
            sd = self.printer.lookup_object("virtual_sdcard")
            identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
            return (bool(selected_file) and parser_ok()
                    and sd.file_position == execution["file_position"]
                    and sd.current_file.tell() == execution["file_position"]
                    and self._recovery_active_file(sd, identity) == self._print_file(sd, identity))
        def fans_ok():
            guard()
            return all(math.isclose(status(name).get("speed", float("nan")), speed,
                                    rel_tol=1e-10, abs_tol=1e-10)
                       for name, speed in fan_targets())
        stages = [("context", lambda: dispatch("_WMP_RECOVERY_BEGIN"), context_ok),
                ("bottom_z", lambda: dispatch("_WMP_HOME_Z_BOTTOM"), bottom_ok),
                ("home_xy", lambda: dispatch("G28 X Y\nM400"), xy_ok),
                ("machine_frame", travel_frame, frame_ok),
                ("select_head", select_head, selected_ok),
                ("restore_mesh", lambda: self._restore_recovery_mesh(execution, guard),
                 lambda: self._recovery_mesh_fingerprint() == execution["mesh_fingerprint"]),
                ("heater_targets", set_heaters, heaters_ok),
                ("fan_targets", set_fans, fans_ok),
                ("heating", lambda: self._wait_recovery_temperatures(execution, guard, cancelled),
                 lambda: self._recovery_temperatures_ready(execution, guard)),
                ("purge_position", purge_position, stage_completed),
                ("prime", prime, stage_completed),
                ("wipe", wipe, stage_completed),
                ("return_xy", return_xy, stage_completed),
                ("return_z", return_z, stage_completed),
                ("return_mesh", lambda: self._restore_recovery_mesh(execution, returning_guard),
                 lambda: self._recovery_mesh_fingerprint() == execution["mesh_fingerprint"] and stage_completed()),
                ("restore_parser", restore_parser, parser_ok),
                ("select_file", select_file, file_ok)]
        if continue_print:
            def restore_deposition():
                returning_guard()
                # An explicit admitted continuation owns this mutation. Review
                # never materializes the file-derived fallback.
                try:
                    self._recovery_read_bytes(self._deposition_envelope_path(), 65536)
                except FileNotFoundError:
                    if not self.printer.lookup_object("gcode").get_mutex().test():
                        raise ValueError("Recovery envelope publication requires command ownership")
                    self._write_recovery_json(self._deposition_envelope_path(for_write=True), review["deposition"]["record"])
                if not self._begin_deposition_envelope(record, restored=review["deposition"]["record"]):
                    raise ValueError("Recovery deposition restoration failed")
                restored_envelope[0] = self._deposition_envelope
            def deposition_ok():
                returning_guard()
                return restored_envelope[0] is not None
            def restore_routes():
                if not file_ok() or self._recovery_mesh_fingerprint() != execution["mesh_fingerprint"]:
                    raise ValueError("Recovery continuation context changed")
                for tool, head in enumerate(execution["mapping"]):
                    for suffix in ("", "_backup"):
                        returning_guard()
                        dispatch("SAVE_VARIABLE VARIABLE=box_modify_t%d%s VALUE=%d" % (tool, suffix, head))
                dispatch("SET_GCODE_VARIABLE MACRO=_WMP_RECOVERY_BEGIN VARIABLE=active VALUE=False")
                dispatch("SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=True")
            def routes_ok():
                returning_guard()
                saved = status("save_variables")["variables"]
                return (file_ok() and status("gcode_macro _WMP_RECOVERY_BEGIN").get("active") is False
                        and status("gcode_macro START_PRINT").get("print_body_ready") is True
                        and saved.get("probe_tool") == record["context"]["tool"]
                        and self._recovery_mesh_fingerprint() == execution["mesh_fingerprint"]
                        and all(saved.get("box_modify_t%d%s" % (tool, suffix)) == head
                                for tool, head in enumerate(execution["mapping"]) for suffix in ("", "_backup")))
            def accounting():
                if not routes_ok():
                    raise ValueError("Recovery routes were not confirmed")
                handoff["accounting"] = True
                self._recovery_start_accounting(execution, returning_guard)
            def accounting_ok():
                return routes_ok() and status("print_stats").get("state") == "printing"
            def queue_worker():
                if not accounting_ok():
                    raise ValueError("Recovery accounting was not confirmed")
                handoff["queued"] = True
                self._recovery_queue_worker(execution, returning_guard)
            stages.extend([("restore_deposition", restore_deposition, deposition_ok),
                           ("restore_routes", restore_routes, routes_ok),
                           ("accounting", accounting, accounting_ok),
                           ("start_file", queue_worker, accounting_ok)])
        return stages

    def _recovery_temperatures_ready(self, execution, guard):
        guard()
        now = self.printer.get_reactor().monotonic()
        targets = execution["heater_targets"]
        self._recovery_heater_state(now, targets.items())
        observed = {}
        ready = True
        for name, target in targets.items():
            current = self.printer.lookup_object(name).get_status(now)
            actual_target = current.get("target")
            if (type(actual_target) not in (int, float) or not math.isfinite(actual_target)
                    or not math.isclose(actual_target, target, rel_tol=1e-10, abs_tol=1e-10)):
                raise ValueError("Recovery heater target changed while waiting: " + name)
            temperature = current["temperature"]
            observed[name] = {"temperature": temperature, "target": target}
            if target > 0 and abs(temperature - target) > 2.:
                ready = False
        # Volatile progress only; do not fsync the receipt on each temperature poll.
        self._recovery_temperatures = observed
        return ready

    def _wait_recovery_temperatures(self, execution, guard, cancelled, timeout=1200.):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid recovery heating timeout")
        reactor = self.printer.get_reactor()
        started = previous = reactor.monotonic()
        stable_since = None
        while True:
            if cancelled():
                raise ValueError("Recovery heating stopped; preparation is incomplete")
            now = reactor.monotonic()
            if not math.isfinite(now) or now < previous:
                raise ValueError("Recovery heating clock changed")
            previous = now
            ready = self._recovery_temperatures_ready(execution, guard)
            if ready:
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= 2.:
                    return
            else:
                stable_since = None
            if now - started >= timeout:
                raise ValueError("Recovery heaters did not reach stable target temperatures before timeout")
            reactor.pause(min(now + .5, started + timeout))

    def _recovery_return_z(self, execution, guard):
        """Raise the bed only after bottom-reference XY return is confirmed."""
        guard()
        reactor = self.printer.get_reactor()
        now = reactor.monotonic()
        toolhead = self.printer.lookup_object("toolhead")
        gcode = self.printer.lookup_object("gcode")
        state = toolhead.get_status(now)
        recovery = self.printer.lookup_object("wmp_recovery").get_status(now)
        target = execution["machine_position"]
        before = list(state["position"])
        low, high = state["axis_minimum"], state["axis_maximum"]
        if (recovery.get("z_reference_valid") is not True or recovery.get("homing") is not False
                or not gcode.get_mutex().test() or len(target) != 4 or len(before) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in target + before)
                or any(not low[i] <= target[i] <= high[i] for i in range(3))
                or not all(axis in state.get("homed_axes", "") for axis in "xyz")
                or any(not math.isclose(before[i], target[i], abs_tol=1e-5, rel_tol=0) for i in (0, 1))
                or not math.isclose(before[2], self._recovery_bottom_reference(state), abs_tol=.05, rel_tol=0)):
            raise ValueError("Recovery Z return requires confirmed bottom-reference XY")
        # Reconcile G92/mesh state without moving before the single vertical move.
        self._recovery_machine_frame(guard)
        guard()
        gcode.run_script_from_command("G1 Z%.17g F1800\nM400" % target[2])
        guard()
        now = reactor.monotonic()
        actual = toolhead.get_status(now)["position"]
        scheduled, estimated, empty = toolhead.check_busy(now)
        if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                    for v in (scheduled, estimated)) or estimated < scheduled
                or len(actual) != 4 or any(type(v) not in (int, float) or not math.isfinite(v)
                      or not math.isclose(v, wanted, abs_tol=1e-5, rel_tol=0)
                      for v, wanted in zip(actual, target[:3] + [before[3]]))):
            raise ValueError("Recovery vertical return was not confirmed")
        return list(actual)

    def _recovery_prime(self, execution, amount, guard):
        """Prime once at the off-bed position, verifying each bounded E move."""
        if type(amount) not in (int, float) or not math.isfinite(amount) or not 1 <= amount <= 300:
            raise ValueError("Invalid recovery purge distance")
        head = int(execution["head"][1:])
        heater = "extruder" + (str(head) if head else "")
        gcode = self.printer.lookup_object("gcode")
        toolhead = self.printer.lookup_object("toolhead")
        reactor = self.printer.get_reactor()
        settings = self.printer.lookup_object("configfile").get_status(reactor.monotonic())["settings"][heater]
        limit = settings.get("max_extrude_only_distance", 50.)
        if type(limit) not in (int, float) or not math.isfinite(limit) or limit < 1.:
            raise ValueError("Invalid recovery extrusion limit")
        def check():
            guard()
            now = reactor.monotonic()
            if not gcode.get_mutex().test() or not self._recovery_temperatures_ready(execution, guard):
                raise ValueError("Recovery priming requires stable heat and command ownership")
            scheduled, estimated, empty = toolhead.check_busy(now)
            if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                        for v in (scheduled, estimated)) or estimated < scheduled):
                raise ValueError("Recovery priming movement has not completed")
            if execution["heater_targets"].get(heater, 0) <= 0:
                raise ValueError("Recovery priming requires a saved heating target")
            state = toolhead.get_status(now)
            pose = list(state["position"])
            if (len(pose) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in pose)
                    or not all(axis in state.get("homed_axes", "") for axis in "xyz")
                    or state.get("extruder") != heater
                    or self._attachment(now) != {"state": "attached", "head": execution["head"]}
                    or self.printer.lookup_object(heater).get_status(now).get("can_extrude") is not True
                    or not math.isclose(pose[0], -13., abs_tol=1e-5, rel_tol=0)
                    or not math.isclose(pose[1], 80., abs_tol=1e-5, rel_tol=0)
                    or not math.isclose(pose[2], self._recovery_bottom_reference(state), abs_tol=.05, rel_tol=0)):
                raise ValueError("Recovery priming head or purge position is not confirmed")
            return pose
        before = check()
        for script in ("M220 S100", "M221 S100", "M83"):
            check()
            gcode.run_script_from_command(script)
        left, expected = amount, before[3]
        while left > 1e-9:
            pose = check()
            move = self.printer.lookup_object("gcode_move").get_status(reactor.monotonic())
            if (move.get("absolute_extrude") is not False or move.get("extrude_factor") != 1.
                    or move.get("speed_factor") != 1.
                    or not math.isclose(pose[3], expected, abs_tol=1e-5, rel_tol=0)):
                raise ValueError("Recovery priming coordinate state changed")
            length = min(left, 25., limit)
            gcode.run_script_from_command("G1 E%.17g F400\nM400" % length)
            expected += length
            pose = check()
            scheduled, estimated, empty = toolhead.check_busy(reactor.monotonic())
            if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                        for v in (scheduled, estimated)) or estimated < scheduled
                    or any(not math.isclose(v, target, abs_tol=1e-5, rel_tol=0)
                           for v, target in zip(pose, before[:3] + [expected]))):
                raise ValueError("Recovery priming movement was not confirmed")
            left -= length
        return expected

    def _recovery_bottom_xy(self, points, guard, feed=12000.):
        """Traverse validated XY waypoints at the verified physical bottom Z.

        This establishes machine-limit compliance, not printed-object clearance.
        The enclosing recovery admission must establish route clearance.
        """
        if type(feed) not in (int, float) or not math.isfinite(feed) or not 1 <= feed <= 30000:
            raise ValueError("Invalid recovery travel feed rate")
        points = copy.deepcopy(points)
        reactor = self.printer.get_reactor()
        toolhead = self.printer.lookup_object("toolhead")
        gcode = self.printer.lookup_object("gcode")
        guard()
        state = toolhead.get_status(reactor.monotonic())
        low, high = state.get("axis_minimum"), state.get("axis_maximum")
        if (not isinstance(low, (list, tuple)) or not isinstance(high, (list, tuple))
                or len(low) < 3 or len(high) < 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in list(low[:3]) + list(high[:3]))
                or any(low[i] >= high[i] for i in range(3))):
            raise ValueError("Invalid recovery travel bounds")
        if (not isinstance(points, (list, tuple)) or not 1 <= len(points) <= 32
                or any(not isinstance(p, (list, tuple)) or len(p) != 2
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in p)
                       or any(not low[i] <= p[i] <= high[i] for i in range(2)) for p in points)):
            raise ValueError("Recovery XY path exceeds travel limits")
        low, high = copy.deepcopy(low), copy.deepcopy(high)
        reference_z = self._recovery_bottom_reference(state)
        def bottom():
            guard()
            now = reactor.monotonic()
            current = toolhead.get_status(now)
            recovery = self.printer.lookup_object("wmp_recovery").get_status(now)
            position = current.get("position", [])
            if (current.get("axis_minimum") != low or current.get("axis_maximum") != high
                    or recovery.get("z_reference_valid") is not True or recovery.get("homing") is not False
                    or len(position) != 4 or type(position[2]) not in (int, float)
                    or self._recovery_bottom_reference(current) != reference_z
                    or not math.isfinite(position[2]) or not math.isclose(position[2], reference_z, abs_tol=.05, rel_tol=0)):
                raise ValueError("Recovery travel lost its bottom reference or bounds")
        bottom()
        position = self._recovery_machine_frame(guard)
        z, e = position[2:]
        for x, y in points:
            bottom()
            if self.printer.lookup_object("bed_mesh").get_mesh() is not None:
                raise ValueError("Recovery travel compensation changed")
            frame = self.printer.lookup_object("gcode_move").get_status(reactor.monotonic())
            physical = toolhead.get_status(reactor.monotonic())["position"]
            coordinates = frame.get("gcode_position", [])
            if (frame.get("absolute_coordinates") is not True or len(coordinates) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           or not math.isclose(v, target, abs_tol=1e-6, rel_tol=0)
                           for v, target in zip(coordinates[:3], physical[:3]))):
                raise ValueError("Recovery travel coordinate frame changed")
            gcode.run_script_from_command("G1 X%.17g Y%.17g F%.17g\nM400" % (x, y, feed))
            bottom()
            now = reactor.monotonic()
            actual = toolhead.get_status(now)["position"]
            scheduled, estimated, empty = toolhead.check_busy(now)
            if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                        for v in (scheduled, estimated)) or estimated < scheduled
                    or any(type(v) not in (int, float) or not math.isfinite(v)
                           or not math.isclose(v, wanted, abs_tol=1e-5, rel_tol=0)
                           for v, wanted in zip(actual, (x, y, z, e)))):
                raise ValueError("Recovery XY movement was not confirmed")
        return [points[-1][0], points[-1][1], z, e]

    def _recovery_machine_frame(self, guard):
        """Establish uncompensated machine XYZ without submitting movement."""
        gcode = self.printer.lookup_object("gcode")
        toolhead = self.printer.lookup_object("toolhead")
        move = self.printer.lookup_object("gcode_move")
        mesh = self.printer.lookup_object("bed_mesh")
        reactor = self.printer.get_reactor()
        def check():
            guard()
            if not gcode.get_mutex().test():
                raise ValueError("Recovery travel frame requires command ownership")
            now = reactor.monotonic()
            state = toolhead.get_status(now)
            position = list(state.get("position", []))
            if (len(position) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)
                    or not all(axis in state.get("homed_axes", "") for axis in "xyz")):
                raise ValueError("Recovery travel requires a known machine position")
            scheduled, estimated, empty = toolhead.check_busy(now)
            if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                        for v in (scheduled, estimated)) or estimated < scheduled):
                raise ValueError("Recovery movement has not completed")
            return position
        before = check()
        scripts = ["BED_MESH_CLEAR", "G90", "M220 S100",
                   "SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0",
                   "G92 X%.17g Y%.17g Z%.17g" % tuple(before[:3])]
        for script in scripts:
            guard()
            gcode.run_script_from_command(script)
        after = check()
        state = move.get_status(reactor.monotonic())
        def same(values, expected):
            return (isinstance(values, (list, tuple)) and len(values) >= len(expected)
                    and all(type(v) in (int, float) and math.isfinite(v)
                            and math.isclose(v, target, abs_tol=1e-6, rel_tol=0)
                            for v, target in zip(values, expected)))
        if (not same(after, before) or mesh.get_mesh() is not None
                or not same(state.get("position"), before)
                or not same(state.get("gcode_position"), before[:3])
                or not same(state.get("homing_origin"), [0., 0., 0.])
                or state.get("absolute_coordinates") is not True
                or not math.isclose(state.get("speed_factor", float("nan")), 1., abs_tol=1e-10)):
            raise ValueError("Recovery machine-coordinate frame was not confirmed")
        return before

    def _restore_recovery_parser(self, execution, guard=lambda: None):
        """Restore parser state only after the owned procedure reaches its pose.

        Requires the command mutex; never calls vendor RESTORE_GCODE_STATE,
        whose reviewed implementation omits coordinate-base restoration.
        Historical machine E is not a destination: preparation may have primed.
        """
        guard()
        gcode = self.printer.lookup_object("gcode")
        if not gcode.get_mutex().test():
            raise ValueError("Recovery parser restore requires command ownership")
        vectors = [execution[key] for key in ("gcode_position", "homing_origin", "parser_position", "machine_position")]
        factors = [execution[key] for key in ("speed", "speed_factor", "extrude_factor")]
        if (any(not isinstance(v, (list, tuple)) or len(v) != 4 for v in vectors)
                or any(type(v) not in (int, float) or not math.isfinite(v) for vector in vectors for v in vector)
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in factors)
                or any(type(execution[key]) is not bool for key in ("absolute_coordinates", "absolute_extrude"))):
            raise ValueError("Invalid recovery parser state")
        now = self.printer.get_reactor().monotonic()
        move = self.printer.lookup_object("gcode_move")
        toolhead = self.printer.lookup_object("toolhead")
        before = move.get_status(now)
        machine = list(toolhead.get_status(now)["position"])
        scheduled, estimated, empty = toolhead.check_busy(now)
        if (empty is not True or any(type(v) not in (int, float) or not math.isfinite(v)
                                     for v in (scheduled, estimated)) or estimated < scheduled):
            raise ValueError("Recovery movement has not completed")
        if any(not math.isfinite(value * 100.) for value in factors[1:]):
            raise ValueError("Invalid recovery parser scaling")
        def same(left, right):
            return len(left) == len(right) and all(math.isfinite(a) and abs(a-b) <= 0.00001 for a, b in zip(left, right))
        if (not same(list(before["position"])[:3], execution["parser_position"][:3])
                or not same(machine[:3], execution["machine_position"][:3])):
            raise ValueError("Recovery has not reached the saved transformed position")
        number = lambda value: format(value, ".17g")
        scripts = ["M220 S" + number(execution["speed_factor"] * 100.),
                   "M221 S" + number(execution["extrude_factor"] * 100.),
                   "SET_GCODE_OFFSET " + " ".join(axis + "=" + number(value)
                       for axis, value in zip("XYZE", execution["homing_origin"])) + " MOVE=0",
                   "G92 " + " ".join(axis + number(value) for axis, value in zip("XYZE", execution["gcode_position"])),
                   # Klipper status speed is G-code F in mm/min, not mm/s.
                   "G1 F" + number(execution["speed"]),
                   "G90" if execution["absolute_coordinates"] else "G91",
                   "M82" if execution["absolute_extrude"] else "M83"]
        for script in scripts:
            guard()
            gcode.run_script_from_command(script)
            guard()
        after = move.get_status(self.printer.get_reactor().monotonic())
        if (not same(list(after["position"]), list(before["position"]))
                or not same(list(toolhead.get_status(now)["position"]), machine)
                or any(not same(list(after[key]), execution[key]) for key in ("gcode_position", "homing_origin"))
                or any(after[key] is not execution[key] for key in ("absolute_coordinates", "absolute_extrude"))
                or any(not math.isclose(after[key], execution[key], rel_tol=1e-10, abs_tol=1e-10)
                       for key in ("speed", "speed_factor", "extrude_factor"))):
            raise ValueError("Recovery parser restoration was not confirmed")
        return True

    def _recovery_disarm_worker(self):
        pending = getattr(self, "_recovery_pending_worker", None)
        if pending is None:
            return
        pending["armed"] = False
        sd = pending["sd"]
        timer = pending.get("timer")
        try:
            if timer is not None:
                self.printer.get_reactor().unregister_timer(timer)
        finally:
            if timer is not None and sd.work_timer is timer:
                sd.work_timer = None
            self._recovery_pending_worker = None

    def _recovery_queue_worker(self, execution, guard):
        """Register an inert SD worker; only durable completion can activate it.

        Caller must finish context/accounting restoration first. No public entry
        invokes this helper yet. Timer registration itself is not continuation.
        """
        guard()
        reactor = self.printer.get_reactor()
        sd = self.printer.lookup_object("virtual_sdcard")
        gcode = self.printer.lookup_object("gcode")
        stats = self.printer.lookup_object("print_stats")
        runner = self._recovery_attempt
        if (not gcode.get_mutex().test() or not runner.busy or runner.record["state"] != "running"
                or getattr(self, "_recovery_pending_worker", None) is not None
                or sd.is_active() or sd.is_cmd_from_sd()
                or stats.state != "printing" or stats.filename != execution["file"]["path"]
                or sd.file_position != execution["file_position"]):
            raise ValueError("Recovery worker handoff is not owned or ready")
        token = {"armed": False, "timer": None, "sd": sd,
                 "session": self.session_id, "request": copy.deepcopy(runner.record["request"])}
        envelope = getattr(self, "_deposition_envelope", None)
        envelope_record = copy.deepcopy(envelope.record) if envelope is not None else None
        self._recovery_pending_worker = token
        runner._save(checkpoint={"job_fingerprint": execution["job_fingerprint"], "file_position": execution["file_position"]},
                     continuation={"state": "scheduled", "file_position": execution["file_position"], "error": ""})
        def verify_observer():
            if envelope is not None:
                self._verify_deposition_observer(envelope, envelope_record)
                persisted = json.loads(self._recovery_read_bytes(self._deposition_envelope_path(), 65536))
                if persisted != envelope_record:
                    raise ValueError("Recovery deposition observer lost durable evidence")
        def work(eventtime):
            if (not token["armed"] or self.session_id != token["session"]
                    or runner.record["state"] != "complete" or runner.record["request"] != token["request"]):
                return reactor.NEVER
            # Never dispatch an SD body while the handoff still holds command
            # ownership, even if a reactor implementation invokes us immediately.
            if gcode.get_mutex().test():
                return eventtime + .001
            token["armed"] = False  # A delivered callback is never replayable.
            self._recovery_pending_worker = None
            result = self._recovery_dispatch_sd_worker(
                sd, runner, token, execution["file"]["path"], sd.work_handler,
                verify_observer, eventtime)
            if runner.record.get("continuation", {}).get("state") == "paused":
                self._recovery_bind_paused_worker(sd, runner, token, execution)
            return result
        sd.must_pause_work = False
        token["timer"] = reactor.register_timer(work, reactor.NEVER)
        if token["timer"] is None:
            raise ValueError("Recovery worker registration was not acknowledged")
        sd.work_timer = token["timer"]
        return True

    def _recovery_release_paused_worker(self, cancelled=False):
        binding = getattr(self, "_recovery_paused_worker", None)
        if binding is None:
            return
        if cancelled:
            runner = getattr(self, "_recovery_attempt", None)
            if (runner is not None and binding["session"] == self.session_id
                    and runner.record is not None and runner.record["request"] == binding["request"]
                    and runner.record["state"] == "complete"
                    and runner.record.get("continuation", {}).get("state") == "paused"):
                runner._save(continuation=dict(runner.record["continuation"], state="cancelled", error=""))
        sd = binding["sd"]
        if sd.work_handler is binding["wrapper"]:
            sd.work_handler = binding["original"]
        self._recovery_paused_worker = None

    def _recovery_bind_paused_worker(self, sd, runner, initial_token, execution):
        """Keep subsequent vendor Resume/M24 workers under this attempt's owner.

        The vendor continues to own pause-state return and timer registration.
        Only its selected worker is wrapped; other jobs regain the original
        handler on terminal completion or the native reset-file event.
        """
        if getattr(self, "_recovery_paused_worker", None) is not None:
            raise ValueError("A recovery pause worker is already owned")
        original = sd.work_handler
        selected_file = sd.current_file
        request = copy.deepcopy(initial_token["request"])
        session = initial_token["session"]
        filename = execution["file"]["path"]
        reactor = self.printer.get_reactor()
        stats = self.printer.lookup_object("print_stats")
        gcode = self.printer.lookup_object("gcode")
        def validate():
            if (self.session_id != session or self.printer.is_shutdown()
                    or self._print_cancel_active()
                    or self.printer.lookup_object("openace", None) is not None
                    or self.printer.lookup_object("AFC", None) is not None
                    or runner.record["request"] != request or runner.record["state"] != "complete"
                    or runner.record.get("continuation", {}).get("state") != "paused"
                    or stats.filename != filename or stats.state != "paused"
                    or sd.current_file is not selected_file or selected_file is None
                    or sd.work_handler is not wrapper):
                raise ValueError("Recovered pause no longer owns this Resume")
            if self._recovery_fingerprint(self._recovery_read_bytes(self._recovery_job_path(), 65536)) != execution["job_fingerprint"]:
                raise ValueError("Recovered job changed before Resume")
            envelope = getattr(self, "_deposition_envelope", None)
            if envelope is None:
                raise ValueError("Recovered deposition evidence is unavailable")
            record = copy.deepcopy(envelope.record)
            self._verify_deposition_observer(envelope, record)
            if json.loads(self._recovery_read_bytes(self._deposition_envelope_path(), 65536)) != record:
                raise ValueError("Recovered deposition evidence changed before Resume")
        def wrapper(eventtime):
            if sd.work_timer is None:
                return reactor.NEVER
            if gcode.get_mutex().test():
                return eventtime + .001
            token = {"session": session, "request": request, "timer": sd.work_timer}
            result = self._recovery_dispatch_sd_worker(
                sd, runner, token, filename, original, validate, eventtime)
            if runner.record.get("continuation", {}).get("state") in ("complete", "cancelled"):
                self._recovery_release_paused_worker()
            return result
        self._recovery_paused_worker = {"sd": sd, "original": original,
                                       "wrapper": wrapper, "validate": validate,
                                       "session": session, "request": request}
        sd.work_handler = wrapper

    def _recovery_dispatch_sd_worker(self, sd, runner, token, filename, handler,
                                     verify_observer, eventtime):
        """Execute one admitted SD worker with managed failure/outcome handling.

        Scheduling, pause-state return and initial preparation belong to the
        caller. This boundary must not prime, restore accounting or resume a
        timer itself. The temporary error handler belongs only to this dispatch.
        """
        reactor = self.printer.get_reactor()
        gcode = self.printer.lookup_object("gcode")
        stats = self.printer.lookup_object("print_stats")
        original_error = sd.on_error_gcode
        failure = [""]
        class RecoveryErrorScript:
            def render(self):
                failure[0] = "Recovered print command failed"
                return "TURN_OFF_HEATERS"
        sd.on_error_gcode = RecoveryErrorScript()
        try:
            verify_observer()
            runner._save(continuation={"state": "started", "file_position": sd.file_position, "error": ""})
            result = handler(eventtime)
        except Exception as error:
            failure[0] = str(error)
            result = reactor.NEVER
        finally:
            sd.on_error_gcode = original_error
        state = stats.state
        if (failure[0] or state not in ("complete", "paused", "cancelled")
                or state == "paused" and not sd.must_pause_work):
            message = failure[0] or getattr(stats, "error_message", "") or "Recovered SD worker stopped without a confirmed outcome"
            # Never run the stock CANCEL_PRINT movement/reset prefix on an
            # uncertain dispatch. Preserve the selected file and receipt.
            sd.must_pause_work = True
            if sd.work_timer is token["timer"]:
                reactor.unregister_timer(token["timer"])
                sd.work_timer = None
            try:
                if (self.session_id != token["session"] or self.printer.is_shutdown()
                        or stats.filename != filename
                        or self.printer.lookup_object("openace", None) is not None
                        or self.printer.lookup_object("AFC", None) is not None):
                    raise ValueError("Recovery failure cleanup lost ownership")
                if stats.state == "printing":
                    stats.note_error(message)
                gcode.run_script("TURN_OFF_HEATERS")
            except Exception as error:
                message += "; heater cleanup: " + str(error)
            runner._save(state="unknown", error=message,
                continuation={"state": "unknown", "file_position": sd.file_position, "error": message})
        else:
            try:
                runner._save(continuation={"state": state, "file_position": sd.file_position, "error": ""})
            except Exception as error:
                message = "Unable to record recovered worker %s outcome: %s" % (state, error)
                runner.record.update(state="unknown", error=message,
                    continuation={"state": "unknown", "file_position": sd.file_position, "error": message})
                try:
                    runner.persist(copy.deepcopy(runner.record))
                except Exception:
                    logging.exception("Unable to persist unresolved recovered worker outcome")
                raise
        return result

    def _recovery_activate_worker(self, request):
        pending = getattr(self, "_recovery_pending_worker", None)
        if pending is None:
            return  # Existing private preparation-only chains have no worker.
        runner = self._recovery_attempt
        if (pending["request"] != request or pending["session"] != self.session_id
                or runner.record["state"] != "complete" or runner.record["request"] != request
                or not self.printer.lookup_object("gcode").get_mutex().test()
                or pending["sd"].work_timer is not pending["timer"]):
            raise ValueError("Recovery worker activation lost ownership")
        # Confirm the completed receipt actually reached disk before activation.
        persisted = json.loads(self._recovery_read_bytes(self._recovery_attempt_path(), 65536))
        if persisted != runner.record:
            raise ValueError("Recovery completion receipt was not persisted")
        pending["armed"] = True
        reactor = self.printer.get_reactor()
        reactor.update_timer(pending["timer"], reactor.NOW)

    @staticmethod
    def _validate_recovery_accounting(value):
        for key in ("total_duration", "print_duration", "filament_used"):
            number = value.get(key)
            if type(number) not in (int, float) or not math.isfinite(number):
                raise ValueError("Checkpoint print accounting is unavailable")
        if not 0 <= value["print_duration"] <= value["total_duration"]:
            raise ValueError("Invalid checkpoint elapsed print time")

    def _recovery_start_accounting(self, execution, guard):
        """Initialize vendor accounting at final handoff; does not start SD work.

        The eventual continuation owner must allow the standby -> printing state
        transition. This helper is deliberately absent from preparation stages.
        """
        self._validate_recovery_accounting(execution)
        guard()
        gcode = self.printer.lookup_object("gcode")
        sd = self.printer.lookup_object("virtual_sdcard")
        stats = self.printer.lookup_object("print_stats")
        reactor = self.printer.get_reactor()
        identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
        if (not gcode.get_mutex().test() or sd.is_active() or sd.is_cmd_from_sd()
                or stats.state != "standby" or stats.print_start_time is not None
                or stats.filename != execution["file"]["path"]
                or sd.file_position != execution["file_position"]
                or self._recovery_active_file(sd, identity) != self._print_file(sd, identity)):
            raise ValueError("Recovery accounting requires the selected idle checkpoint")
        # note_start captures the current physical E baseline after recovery prime.
        # A later worker note_start preserves this start clock and resets E again.
        stats.note_start()
        if stats.state != "printing" or stats.print_start_time is None:
            raise ValueError("Recovery print accounting start was not confirmed")
        stats.print_start_time -= execution["total_duration"]
        stats.total_duration = execution["total_duration"]
        stats.init_duration = 0.
        # Preserve all historic non-printing time without inventing its split
        # between initial preparation and pauses. Future pause tracking is native.
        stats.prev_pause_duration = execution["total_duration"] - execution["print_duration"]
        stats.filament_used = execution["filament_used"]
        guard()
        actual = stats.get_status(reactor.monotonic())
        if (actual["state"] != "printing"
                or actual["total_duration"] < execution["total_duration"]
                or not math.isclose(actual["total_duration"] - actual["print_duration"],
                                    stats.prev_pause_duration, abs_tol=1e-7)
                or actual["filament_used"] != execution["filament_used"]):
            raise ValueError("Recovery print accounting restoration was not confirmed")
        return True

    def _recovery_select_file(self, execution, guard):
        """Open and seek the exact bound file; never start the SD worker."""
        gcode = self.printer.lookup_object("gcode")
        sd = self.printer.lookup_object("virtual_sdcard")
        reactor = self.printer.get_reactor()
        info = execution["file"]
        identity = {key: info[key] for key in ("path", "size", "modified")}
        position = execution["file_position"]
        if type(position) is not int or not 0 < position < info["size"]:
            raise ValueError("Invalid recovery file offset")
        def idle():
            guard()
            if not gcode.get_mutex().test() or sd.is_active() or sd.is_cmd_from_sd():
                raise ValueError("Recovery file selection lost command or SD ownership")
        idle()
        full, before = self._print_file(sd, identity)
        current = getattr(sd, "current_file", None)
        if current is not None and os.path.realpath(current.name) != full:
            raise ValueError("Another selected file prevents recovery handoff")
        def unchanged(stat_info):
            return (stat_info.st_dev, stat_info.st_ino, stat_info.st_size, stat_info.st_mtime_ns) == before
        digest = hashlib.sha256()
        with open(full, "rb") as stream:
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed before handoff")
            stream.seek(position - 1)
            if stream.read(1) != b"\n":
                raise ValueError("Recovery file offset is not a completed line boundary")
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                reactor.pause(reactor.monotonic() + .001)
                idle()
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed during handoff")
        if digest.hexdigest() != info["sha256"] or self._print_file(sd, identity) != (full, before):
            raise ValueError("Recovery file content changed before selection")
        idle()
        command = gcode.create_gcode_command("WMP_RECOVERY_FILE", "WMP_RECOVERY_FILE", {})
        # Stock parse_gcode_response treats "File opened:" as a new print:
        # it resets both native checkpoints and writes identity route backups.
        # This is an internal reopen of the admitted job, not a new start.
        # Filter only the loader's two announcements on this private command;
        # preserve errors and any unexpected response, and leave M23 unchanged.
        respond_raw = command.respond_raw
        announcements = {"File opened:%s Size:%d" % (info["path"], info["size"]),
                         "File selected"}
        command.respond_raw = lambda message: None if message in announcements else respond_raw(message)
        # The native M23 path only lists root files. Use its actual loader with
        # subdirectory enumeration, then verify its selected descriptor (it can
        # otherwise fall back to a case-insensitive filename match).
        sd._reset_file()
        idle()
        sd._load_file(command, info["path"], check_subdirs=True)
        idle()
        if (self._recovery_active_file(sd, identity) != (full, before)
                or sd.file_size != info["size"]):
            raise ValueError("Recovery loader selected different file contents")
        seek = gcode.create_gcode_command("M26", "M26 S%d" % position, {"S": str(position)})
        sd.cmd_M26(seek)
        sd.current_file.seek(position)
        idle()
        if (sd.file_position != position or sd.current_file.tell() != position
                or self._recovery_active_file(sd, identity) != (full, before)):
            raise ValueError("Recovery file seek was not confirmed")
        return {"file": info["path"], "file_position": position}

    def _recovery_file_effect_contract(self):
        # Installed-source identity, assuming the normal module-loading lifecycle.
        # This is not attestation against live monkeypatches or replaced bytecode.
        import sys
        now = self.printer.get_reactor().monotonic()
        settings = self.printer.lookup_object("configfile").get_status(now)["settings"]
        transforms = {}
        for name in ("gcode_move", "bed_mesh"):
            obj = self.printer.lookup_object(name)
            module = sys.modules[type(obj).__module__]
            path = module.__file__
            if path.endswith(".pyc"):
                path = path[:-1]
            transforms[name] = hashlib.sha256(self._recovery_read_bytes(path, 1024 * 1024)).hexdigest()
        return wmp_recovery_file_envelope.effect_contract(settings, transforms)

    def _recovery_file_mesh(self, execution):
        """Reconstruct saved interpolation without loading/mutating live mesh."""
        import sys
        mesh = self.printer.lookup_object("bed_mesh")
        profile = copy.deepcopy(mesh.pmgr.get_profiles().get("wmp_print"))
        if not isinstance(profile, dict):
            raise ValueError("Saved print mesh is unavailable for file clearance")
        offsets = execution.get("mesh_offsets")
        if (not isinstance(offsets, list) or len(offsets) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offsets)):
            raise ValueError("Invalid recovery mesh offsets")
        params, points = profile.get("mesh_params", {}), profile.get("points")
        for axis in ("x", "y"):
            count, pps = params.get(axis + "_count"), params.get("mesh_" + axis + "_pps")
            if (type(count) is not int or type(pps) is not int or not 2 <= count <= 256
                    or pps < 0 or (count - 1) * pps + count > 256):
                raise ValueError("Saved recovery mesh exceeds bounded interpolation dimensions")
        if (not isinstance(points, (list, tuple)) or len(points) != params["y_count"]
                or any(not isinstance(row, (list, tuple)) or len(row) != params["x_count"]
                       or any(not wmp_recovery_file_envelope.finite(v) for v in row) for row in points)):
            raise ValueError("Invalid saved recovery mesh points")
        module = sys.modules[type(mesh).__module__]
        detached = module.ZMesh(params, "wmp_print")
        detached.build_mesh(profile["points"])
        grid = detached.get_mesh_matrix()
        target = 0.
        if mesh.fade_end != mesh.FADE_DISABLE:
            target = detached.get_z_average() if mesh.base_fade_target is None else mesh.base_fade_target
            low, high = detached.get_z_range()
            if (target != 0. and not low <= target <= high) or mesh.fade_dist <= max(abs(low), abs(high)):
                raise ValueError("Saved recovery mesh has invalid fade configuration")
        params = profile["mesh_params"]
        bounds = [[params["min_x"], params["min_y"]],
                  [params["max_x"], params["max_y"]], offsets[:2]]
        parameters = [mesh.fade_start, mesh.fade_end, mesh.fade_dist, target, offsets[2]]
        canonical = [[[float(v) for v in row] for row in grid],
                     [[float(v) for v in pair] for pair in bounds], [float(v) for v in parameters]]
        payload = json.dumps(canonical, separators=(",", ":"), allow_nan=False).encode()
        fingerprint = hashlib.sha256(payload).hexdigest()
        if fingerprint != execution["mesh_fingerprint"]:
            raise ValueError("Saved recovery mesh differs from the print checkpoint")
        return grid, target, fingerprint

    def _recovery_deposition_payload(self, execution):
        """Prefer measured evidence; derive absent evidence without writing."""
        try:
            return self._recovery_read_bytes(self._deposition_envelope_path(), 65536)
        except FileNotFoundError:
            pass
        job_bytes = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        if self._recovery_fingerprint(job_bytes) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed during file-clearance review")
        context = json.loads(job_bytes)["context"]
        if not isinstance(context.get("file_effect_contract"), dict):
            raise ValueError("No deposition record or print-start macro proof was saved for this older print; file-derived recovery cannot verify clearance. Start a new print after updating WM+.")
        proof = self._recovery_file_effect_contract()
        if proof != context["file_effect_contract"]:
            raise ValueError("Print-start macro/transform proof changed; file-derived recovery cannot verify clearance")
        grid, fade_target, mesh_fingerprint = self._recovery_file_mesh(execution)
        sd = self.printer.lookup_object("virtual_sdcard")
        full, identity = self._print_file_identity(sd, execution["file"])
        info = os.stat(full, follow_symlinks=False)
        key = (hashlib.sha256(wmp_recovery_file_envelope.canonical(execution)).hexdigest(),
               hashlib.sha256(job_bytes).hexdigest(), mesh_fingerprint,
               proof["sha256"], identity, info.st_ctime_ns)
        cached = getattr(self, "_file_clearance_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        descriptor = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != identity:
                raise ValueError("Recovery G-code changed before analysis")
            record = wmp_recovery_file_envelope.analyze(stream, execution, context,
                grid, fade_target, proof,
                lambda: self.printer.get_reactor().pause(self.printer.get_reactor().monotonic() + .001))
            after = os.fstat(stream.fileno())
        latest = os.stat(full, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(item, field) for item in (after, latest) for field in fields):
            raise ValueError("Recovery G-code changed during analysis")
        if (self._recovery_read_bytes(self._recovery_job_path(), 65536) != job_bytes
                or self._recovery_file_mesh(execution)[2] != mesh_fingerprint
                or self._recovery_file_effect_contract() != proof):
            raise ValueError("Recovery file-clearance context changed during analysis")
        payload = json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")
        self._file_clearance_cache = (key, payload)
        return payload

    def _recovery_clearance_evidence(self, execution):
        """Read job-bound deposition evidence; never substitute checkpoint Z."""
        payload = self._recovery_deposition_payload(execution)
        record = json.loads(payload)
        envelope = RecoveryDepositionEnvelope(lambda value: None, execution["job_id"],
                                               execution["file"]["sha256"], record)
        job_payload = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        if self._recovery_fingerprint(job_payload) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed during clearance review")
        offsets = json.loads(job_payload)["context"]["offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 4
                or any(not isinstance(row, list) or len(row) != 3
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                       for row in offsets)):
            raise ValueError("Recovery head offsets are unavailable")
        # Include all heads: preparation may dock the currently attached head
        # even when that head is absent from the resumed job's route map.
        span = max(row[2] for row in offsets) - min(row[2] for row in offsets)
        state = self.printer.lookup_object("toolhead").get_status(self.printer.get_reactor().monotonic())
        clearance = envelope.clearance(self._recovery_bottom_reference(state),
                                       getattr(self, "recovery_clearance_mm", 10.), span)
        return {"record": record, "sha256": hashlib.sha256(payload).hexdigest(),
                "clearance": clearance}

    @staticmethod
    def _decode_recovery_json(encoded, limit=16384):
        """Decode bounded JSON without duplicate fields, I/O or side effects."""
        if (not isinstance(encoded, str) or not 0 < len(encoded) <= limit
                or len(encoded) % 2 or not re.fullmatch(r"[0-9a-fA-F]+", encoded)):
            raise ValueError("Invalid encoded recovery request")
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Duplicate recovery request field")
                result[key] = value
            return result
        return json.loads(bytes.fromhex(encoded).decode("utf-8"), object_pairs_hook=unique_fields)

    def _decode_recovery_request(self, encoded):
        """Parse bounded request identity without I/O or side effects."""
        request = self._decode_recovery_json(encoded)
        if (not isinstance(request, dict) or set(request) != {
                "version", "id", "session", "owner", "file", "checkpoint",
                "checkpoint_hash", "job_hash", "execution_hash", "deposition_sha256"}
                or type(request["version"]) is not int or request["version"] != 1
                or request["owner"] != "standalone"
                or not isinstance(request["file"], str) or not request["file"]
                or not isinstance(request["deposition_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request["deposition_sha256"])):
            raise ValueError("Invalid recovery request fields")
        attempt = {key: request[key] for key in ("id", "session", "file", "execution_hash")}
        RecoveryAttempt._validate_request(attempt)
        return request, attempt

    def _recovery_request_review(self, encoded):
        """Validate one immutable native selection; no commands or lease."""
        request, attempt = self._decode_recovery_request(encoded)
        native = self._recovery_review(request["session"], request["file"], request["checkpoint"],
                                       request["checkpoint_hash"], request["job_hash"])
        review = self._recovery_execution_review(request["session"], request["file"], request["execution_hash"])
        if (native["machine"] != review["machine"]
                or request["job_hash"] != review["execution"]["job_fingerprint"]
                or native["record"]["id"] != review["execution"]["job_id"]
                or request["deposition_sha256"] != review["deposition"]["sha256"]):
            raise ValueError("Recovery selections do not describe the same admitted job")
        # Native and managed sampling are asynchronous. The managed completed
        # execution record supplies the resume offset and pose; never merge its
        # fields with the native sample. Keep native selection bound throughout.
        review["native_selection"] = {key: request[key] for key in
                                     ("checkpoint", "checkpoint_hash", "job_hash")}
        self._verify_recovery_native_selection(review)
        return attempt, review

    def _verify_recovery_native_selection(self, review):
        selection = review.get("native_selection")
        if selection is None:
            return  # Private stage fixtures/preparation callers predate native handoff.
        path = os.path.join(self.recovery_checkpoint_dir, selection["checkpoint"])
        payload = self._recovery_read_bytes(path, 65536)
        marker = self._recovery_read_bytes(path + ".wmp-coordinates", 256).decode("ascii").split()
        if (self._recovery_fingerprint(payload) != selection["checkpoint_hash"]
                or marker != ["WMP-GCODE-XYZ-MATERIAL-2", selection["checkpoint_hash"], selection["job_hash"]]
                or self._recovery_fingerprint(self._recovery_read_bytes(self._recovery_job_path(), 65536)) != selection["job_hash"]
                or self._recovery_fingerprint(self._recovery_read_bytes(self._recovery_execution_path(), 65536)) != review["execution_hash"]):
            raise ValueError("Recovery selection changed before continuation")

    def _recovery_ticket_state(self):
        state = getattr(self, "_recovery_tickets", None)
        if state is None or state["session"] != self.session_id:
            # Native protocol requires ID == prefix + decimal sequence. Seed
            # the counter per session so retained attempts never collide with
            # the next session's first request; leave 32 bits for local counts.
            seed = int.from_bytes(hashlib.sha256(self.session_id.encode("utf-8")).digest()[:16], "big") << 32
            state = {"session": self.session_id, "continue": {"issued": seed, "consumed": seed, "slots": {}},
                     "resolve": {"issued": seed, "consumed": seed, "slots": {}}}
            self._recovery_tickets = state
        return state

    def _issue_recovery_ticket(self, kind, request):
        """Bounded read-only evidence ticket, never a physical reservation."""
        if request["session"] != self.session_id:
            raise ValueError("Recovery ticket printer session changed")
        if request["id"].startswith(("wmp2rc_", "wmp2rr_")):
            raise ValueError("Recovery selection ID is reserved for server-issued operations")
        state = self._recovery_ticket_state()[kind]
        slot = "continue" if kind == "continue" else request["action"]
        previous = state["slots"].get(slot)
        if previous is not None and previous["selection"] == request:
            return copy.deepcopy(previous["request"]), copy.deepcopy(previous["ticket"])
        state["issued"] += 1
        sequence = state["issued"]
        issued = dict(request, id=("wmp2rc_" if kind == "continue" else "wmp2rr_") + str(sequence))
        ticket = {"protocol": 1, "selection_id": request["id"], "sequence": str(sequence),
                  "token": uuid.uuid4().hex + uuid.uuid4().hex}
        state["slots"][slot] = {"selection": copy.deepcopy(request), "request": issued,
                                "ticket": ticket, "sequence": sequence}
        return copy.deepcopy(issued), copy.deepcopy(ticket)

    def _consume_recovery_ticket(self, kind, request, gcmd):
        token = gcmd.get("TICKET", None)
        reserved = request["id"].startswith(("wmp2rc_", "wmp2rr_"))
        if not reserved and token is None:
            return False  # Legacy callers retain their non-evicting ID ledger.
        if not reserved or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
            raise ValueError("Recovery operation requires its exact server-issued TICKET")
        if request["session"] != self.session_id:
            raise ValueError("Recovery ticket printer session changed")
        state = self._recovery_ticket_state()[kind]
        slot = "continue" if kind == "continue" else request["action"]
        issued = state["slots"].get(slot)
        if (issued is None or issued["sequence"] <= state["consumed"]
                or issued["request"] != request or issued["ticket"]["token"] != token):
            raise ValueError("Recovery ticket was consumed, superseded, or does not match this request; review again")
        state["consumed"] = issued["sequence"]
        state["slots"] = {key: value for key, value in state["slots"].items()
                          if value["sequence"] > state["consumed"]}
        return True

    @staticmethod
    def _wants_recovery_ticket(web_request):
        protocol = web_request.get_str("ticket_protocol", "0")
        if protocol not in ("0", "1"):
            raise ValueError("Unsupported recovery ticket protocol: " + protocol)
        return protocol == "1"

    def _handle_recovery_review(self, web_request):
        """Resolve a native selection on explicit review, never on status polls."""
        try:
            gcode = self.printer.lookup_object("gcode")
            if gcode.get_mutex().test():
                raise ValueError("Printer command is busy; review recovery when idle")
            request = {key: web_request.get_str(key) for key in
                       ("id", "session", "file", "checkpoint", "checkpoint_hash", "job_hash")}
            selected = request["file"]
            if os.path.isabs(selected):
                root = os.path.realpath(self.printer.lookup_object("virtual_sdcard").sdcard_dirname)
                if os.path.commonpath((root, selected)) != root:
                    raise ValueError("Selected recovery file is outside the G-code directory")
                request["file"] = os.path.relpath(selected, root)
            execution_bytes = self._recovery_execution_bytes()
            self._parse_recovery_execution_format(execution_bytes)
            envelope_bytes = self._recovery_deposition_payload(json.loads(execution_bytes))
            request.update(version=1, owner="standalone",
                           execution_hash=self._recovery_fingerprint(execution_bytes),
                           deposition_sha256=hashlib.sha256(envelope_bytes).hexdigest())
            encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8").hex()
            attempt, review = self._recovery_request_review(encoded)
            if gcode.get_mutex().test():
                raise ValueError("Printer command started during recovery review")
            # This selection is immutable, not a lease: Continue repeats admission.
            result = {"selected_file": selected, "request": request, "encoded": encoded,
                      "execution": review["execution"], "clearance": review["deposition"]["clearance"],
                      "fan_warnings": review.get("fan_warnings", [])}
            if self._wants_recovery_ticket(web_request):
                result["request"], result["ticket"] = self._issue_recovery_ticket("continue", request)
                result["encoded"] = json.dumps(result["request"], sort_keys=True, separators=(",", ":")).encode().hex()
            web_request.send(result)
        except Exception as error:
            raise web_request.error(str(error))

    @staticmethod
    def _validate_recovery_resolution_identity(request):
        if (request.get("action") not in ("reconcile", "abandon")
                or any(not isinstance(request.get(key), str)
                       or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request[key])
                       for key in ("id", "attempt_id", "session"))):
            raise ValueError("Invalid recovery resolution identity")

    def _recovery_resolution_selection(self, identity):
        """Bind an explicit action to unchanged evidence; no writes or commands."""
        self._validate_recovery_resolution_identity(identity)
        runner = self._recovery_attempt
        receipt = runner.record
        now = self.printer.get_reactor().monotonic()
        if (identity["session"] != self.session_id or runner.busy
                or getattr(self, "_recovery_command_active", False)
                or receipt is None or receipt["state"] not in ("unknown", "stopped")
                or receipt["request"]["id"] != identity["attempt_id"]
                or (identity["action"] != "abandon" and (self.printer.is_shutdown()
                or self.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"))
                or self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Recovery resolution request, owner or readiness changed: " +
                             ("SESSION differs from printer session" if identity["session"] != self.session_id else
                              "recovery runner is busy" if runner.busy else
                              "recovery command is active" if getattr(self, "_recovery_command_active", False) else
                              "recovery receipt is missing" if receipt is None else
                              "receipt.state=" + repr(receipt["state"])[:80] if receipt["state"] not in ("unknown", "stopped") else
                              "attempt ID differs from receipt" if receipt["request"]["id"] != identity["attempt_id"] else
                              "printer is shut down" if self.printer.is_shutdown() else
                              "webhooks is not ready" if self.printer.lookup_object("webhooks").get_status(now).get("state") != "ready" else
                              "openace owner is present" if self.printer.lookup_object("openace", None) is not None else "AFC owner is present"))
        journal = self._recovery_read_bytes(self._recovery_attempt_path(), 65536)
        if json.loads(journal) != receipt:
            raise ValueError("Recovery attempt journal changed")
        execution = self._recovery_read_bytes(self._recovery_execution_path(), 65536)
        execution_hash = self._recovery_fingerprint(execution)
        if identity["action"] == "reconcile" and (
                receipt.get("continuation", {}).get("state") != "interrupted"
                or receipt["request"]["session"] == self.session_id
                or execution_hash == receipt["request"]["execution_hash"]):
            raise ValueError("Reconciliation requires a new checkpoint after interrupted continuation")
        return dict(identity, version=1, journal_sha256=hashlib.sha256(journal).hexdigest(),
                    execution_hash=execution_hash)

    def _handle_recovery_resolution_review(self, web_request):
        try:
            gcode = self.printer.lookup_object("gcode")
            identity = {key: web_request.get_str(key) for key in ("id", "attempt_id", "session", "action")}
            request = self._recovery_resolution_selection(identity)
            if identity["action"] == "reconcile":
                self._reconcile_recovery_continuation(identity["session"], identity["attempt_id"],
                                                      request["execution_hash"], review_only=True)
            else:
                self._abandon_recovery_attempt(identity["session"], identity["attempt_id"], review_only=True)
            if self._recovery_resolution_selection(identity) != request:
                raise ValueError("Printer command or recovery evidence changed during resolution review")
            result = {"request": request}
            if self._wants_recovery_ticket(web_request):
                result["request"], result["ticket"] = self._issue_recovery_ticket("resolve", request)
            web_request.send(result)
        except Exception as error:
            raise web_request.error(str(error))

    def cmd_RECOVERY_RESOLVE(self, gcmd):
        tracked = None
        entered = False
        try:
            request = self._decode_recovery_json(gcmd.get("REQUEST"), 4096)
            if (not isinstance(request, dict) or set(request) != {
                    "version", "id", "attempt_id", "session", "action", "journal_sha256", "execution_hash"}
                    or type(request["version"]) is not int or request["version"] != 1
                    or not isinstance(request["journal_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", request["journal_sha256"])
                    or not isinstance(request["execution_hash"], str)
                    or not re.fullmatch(r"[0-9a-f]{16}", request["execution_hash"])):
                raise ValueError("Invalid recovery resolution fields")
            self._validate_recovery_resolution_identity(request)
            if request["session"] != self.session_id:
                raise ValueError("Recovery resolution session changed")
            if not self._consume_recovery_ticket("resolve", request, gcmd):
                seen = getattr(self, "_recovery_resolution_ids", set())
                if request["id"] in seen:
                    raise ValueError("Resolution request was already attempted")
                if len(seen) >= 1024:
                    raise ValueError("Legacy recovery resolution history is full; update the WM+ screen for bounded tickets or restart Klipper")
                seen.add(request["id"])
                self._recovery_resolution_ids = seen
            tracked = request
            self._recovery_resolution = {"request": copy.deepcopy(request), "state": "pending", "message": "Checking recovery evidence"}
            identity = {key: request[key] for key in ("id", "attempt_id", "session", "action")}
            if self._recovery_resolution_selection(identity) != request:
                raise ValueError("Recovery evidence changed after resolution review")
            if not self.printer.lookup_object("gcode").get_mutex().test():
                raise ValueError("Recovery resolution requires command ownership")
            entered = True
            if request["action"] == "reconcile":
                result = self._reconcile_recovery_continuation(request["session"], request["attempt_id"], request["execution_hash"])
            else:
                result = self._abandon_recovery_attempt(request["session"], request["attempt_id"])
            self._recovery_resolution.update(state="complete", message="Recovery checkpoint reconciled" if request["action"] == "reconcile" else "Recovery abandoned")
            if result.get("archive_warning"):
                self._recovery_resolution["message"] += "; archive unavailable: " + result["archive_warning"]
            gcmd.respond_info(json.dumps(result, sort_keys=True))
        except Exception as error:
            if tracked is not None:
                self._recovery_resolution.update(state="unknown" if entered else "refused", message=str(error)[:512])
            raise gcmd.error(str(error))

    def _handle_recovery_stop(self, web_request):
        # Reactor endpoint: never queue behind the G-code mutex or issue motion.
        runner = getattr(self, "_recovery_attempt", None)
        receipt = runner.record if runner is not None else None
        pending = getattr(self, "_recovery_pending_worker", None)
        preparing = runner is not None and (runner.busy or pending is not None and not pending["armed"])
        if (not getattr(self, "_recovery_command_active", False) or not preparing
                or receipt is None or receipt["state"] not in ("pending", "running", "complete")):
            raise web_request.error("Recovery preparation is not running; use print controls after continuation")
        request = receipt["request"]
        if (self.printer.lookup_object("openace", None) is not None
                or self.printer.lookup_object("AFC", None) is not None
                or web_request.get_str("session") != self.session_id
                or request["session"] != self.session_id
                or web_request.get_str("id") != request["id"]):
            raise web_request.error("Recovery request or owner changed: " +
                                    ("openace owner is present" if self.printer.lookup_object("openace", None) is not None else
                                     "AFC owner is present" if self.printer.lookup_object("AFC", None) is not None else
                                     "SESSION differs from printer session" if web_request.get_str("session") != self.session_id else
                                     "receipt session differs from printer session" if request["session"] != self.session_id else
                                     "ID differs from recovery receipt"))
        self._recovery_stop_request = copy.deepcopy(request)
        web_request.send({"session": self.session_id, "id": request["id"], "state": "requested"})

    def cmd_RECOVERY_CONTINUE(self, gcmd):
        if getattr(self, "_recovery_command_active", False):
            raise gcmd.error("Recovery command is already active")
        self._recovery_command_active = True
        self._recovery_stop_request = None
        tracked = None
        try:
            encoded = gcmd.get("REQUEST")
            request, attempt = self._decode_recovery_request(encoded)
            if attempt["session"] != self.session_id:
                raise ValueError("Recovery printer session changed")
            if not self._consume_recovery_ticket("continue", request, gcmd):
                seen = getattr(self, "_recovery_command_ids", set())
                runner = self._recovery_attempt
                if (attempt["id"] in seen
                        or runner.record is not None and runner.record["request"]["id"] == attempt["id"]):
                    raise ValueError("Recovery request was already attempted")
                if len(seen) >= 1024:
                    raise ValueError("Legacy recovery history is full; update the WM+ screen for bounded tickets or restart Klipper")
                seen.add(attempt["id"])
                self._recovery_command_ids = seen
            tracked = attempt
            self._recovery_submission = {"request": copy.deepcopy(attempt), "state": "reviewing", "message": "Reviewing recovery"}
            result = self._consume_recovery_request(encoded,
                lambda: self._recovery_stop_request is not None)
            self._recovery_submission.update(state="attempted", message="Read the recovery attempt for its outcome")
            # A scheduled worker is not proof of resumed printing.
            if result.get("archive_warning"):
                self._recovery_resolution["message"] += "; archive unavailable: " + result["archive_warning"]
            gcmd.respond_info(json.dumps(result, sort_keys=True))
        except Exception as error:
            if tracked is not None:
                record = self._recovery_attempt.record
                attempted = record is not None and record["request"]["id"] == tracked["id"]
                self._recovery_submission.update(state="attempted" if attempted else "refused",
                                                 message=str(error)[:512])
            raise gcmd.error(str(error))
        finally:
            self._recovery_command_active = False
            self._recovery_stop_request = None

    def _consume_recovery_request(self, encoded, cancelled=lambda: False):
        """Single-owner handoff target for the explicit managed Continue command."""
        if not self.printer.lookup_object("gcode").get_mutex().test():
            raise ValueError("Recovery request requires command ownership")
        attempt, review = self._recovery_request_review(encoded)
        self._begin_explicit_physical_action("recovery continue")
        stages = self._recovery_initial_stages(review, cancelled, continue_print=True)
        return self._run_recovery_stages(attempt, review, stages, cancelled)

    def _recovery_execution_review(self, session, selected_file, execution_hash):
        if getattr(self, "_print_recovery_error", ""):
            raise ValueError("Recovery unavailable for this job: " + self._print_recovery_error)
        """Review an immutable completed-record selection before owned admission.

        This reader sends no commands and grants no permission to prepare. The
        eventual attempt must retain this exact selection and serialize execution.
        """
        try:
            if not isinstance(execution_hash, str) or not re.fullmatch(r"[0-9a-f]{16}", execution_hash):
                raise ValueError("Invalid selected execution fingerprint")
            before = self._recovery_machine_state(session)
            payload = self._recovery_read_bytes(self._recovery_execution_path(), 65536)
            if self._recovery_fingerprint(payload) != execution_hash:
                raise ValueError("Selected execution checkpoint changed")
            execution = self._read_completed_recovery_execution(selected_file)
            after = self._recovery_machine_state(session)
            self._recovery_heater_state(self.printer.get_reactor().monotonic(),
                                        execution["heater_targets"].items())
            toolhead = self.printer.lookup_object("toolhead").get_status(self.printer.get_reactor().monotonic())
            minimum, maximum = toolhead.get("axis_minimum"), toolhead.get("axis_maximum")
            if (not isinstance(minimum, (list, tuple)) or not isinstance(maximum, (list, tuple))
                    or len(minimum) < 3 or len(maximum) < 3):
                raise ValueError("Recovery machine travel limits are unavailable")
            for axis in range(3):
                low, high = minimum[axis], maximum[axis]
                if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high))
                        or low >= high or not low <= execution["machine_position"][axis] <= high):
                    raise ValueError("Recovery endpoint exceeds current machine travel limits")
            clearance = self._recovery_clearance_evidence(execution)
            # Endpoint bounds do not establish a clear route past the object or
            # validate a newly restored mesh transform; preparation must do both.
            missing_fans = []
            for name in execution["fans"]:
                if self.printer.lookup_object(name, None) is None:
                    if name == "fan":
                        raise ValueError("Required part-cooling fan is not installed: " + name)
                    missing_fans.append(name)
            if before != after:
                raise ValueError("Head attachment changed during recovery verification")
            if self._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload:
                raise ValueError("Selected execution checkpoint changed during verification")
            if self._recovery_clearance_evidence(execution) != clearance:
                raise ValueError("Recovery clearance evidence changed during verification")
            return {"execution": execution, "execution_hash": execution_hash, "machine": after,
                    "deposition": clearance,
                    "fan_warnings": ["Optional cooling fan is not installed; restoration will be skipped: " + name
                                     for name in missing_fans]}
        except (AttributeError, KeyError, TypeError, OSError) as error:
            raise ValueError("Recovery evidence or current machine state is unavailable: " + str(error))

    def _recovery_review(self, session, selected_file, checkpoint, checkpoint_hash, job_hash):
        # Review is intentionally not exposed as authorization. A future command
        # must hold its attempt ownership while consuming this evidence.
        try:
            before = self._recovery_machine_state(session)
            self._require_recovery_not_retired()
            evidence = self._recovery_checkpoint_evidence(selected_file, checkpoint, checkpoint_hash, job_hash)
            after = self._recovery_machine_state(session, evidence["values"])
            if before != after:
                raise ValueError("Head attachment changed during recovery verification")
            return dict(evidence, machine=after)
        except (AttributeError, KeyError, TypeError, OSError) as error:
            raise ValueError("Recovery evidence or current machine state is unavailable: " + str(error))

    def _recovery_material_evidence(self, selected_file):
        """Validate restored evidence, not permission to execute recovery.

        The caller must still bind a checkpoint, admit machine state and own
        preparation through completion. No G-code is sent by this helper.
        """
        record = self._read_recovery_job()
        if (set(record) != {"version", "state", "owner", "id", "session", "file",
                            "mapping", "required_tools", "heads", "context"}
                or record["state"] != "committed" or record["owner"] != "standalone"
                or self.printer.lookup_object("openace", None) is not None):
            raise ValueError("No committed standalone recovery material evidence")
        for field in ("id", "session"):
            if not isinstance(record[field], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", record[field]):
                raise ValueError("Invalid recovery job identifier")
        mapping, required, heads = record["mapping"], record["required_tools"], record["heads"]
        if (not isinstance(mapping, list) or len(mapping) != 4
                or any(type(head) is not int or head not in range(4) for head in mapping)
                or not isinstance(required, dict) or not required or len(required) > 4
                or any(tool not in ("0", "1", "2", "3") or type(head) is not int
                       or head not in range(4) or mapping[int(tool)] != head
                       for tool, head in required.items())
                or not isinstance(heads, dict)
                or set(heads) != {"h%d" % head for head in required.values()}):
            raise ValueError("Invalid recovery tool/source assignments")
        for key, saved in heads.items():
            if (not isinstance(saved, dict) or set(saved) != {"source", "identity"}
                    or saved["source"] != "external:" + key):
                raise ValueError("Invalid recovery source identity")
            self._validate_identity(saved["identity"])
            head = int(key[1:])
            if self.printer.lookup_object("extruder" if head == 0 else "extruder%d" % head, None) is None:
                raise ValueError("Required recovery head is not installed")
        file_info = record["file"]
        if (not isinstance(file_info, dict) or set(file_info) != {"path", "size", "modified", "sha256"}
                or not isinstance(selected_file, str) or file_info["path"] != selected_file
                or not isinstance(file_info["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", file_info["sha256"])):
            raise ValueError("Selected recovery file differs from the committed job")
        context = record["context"]
        if (not isinstance(context, dict) or type(context.get("version")) is not int
                or context["version"] != 2 or context.get("mapping") != mapping
                or context.get("file_hex") != selected_file.encode("utf-8").hex()
                or type(context.get("tool")) is not int or context["tool"] not in range(4)
                or context.get("mesh") != "wmp_print"):
            raise ValueError("Invalid committed recovery context")

        def current_evidence():
            now = self.printer.get_reactor().monotonic()
            variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            offsets = [variables.get("t%d_offset" % i) for i in range(4)]
            mesh = self.printer.lookup_object("bed_mesh").get_status(now)
            # The saved mesh need not already be active after restart.
            if (self._recovery_context(variables.get("wmp_print_context")) != self._recovery_context(context)
                    or context.get("offsets") != self._recovery_offsets(offsets)
                    or "wmp_print" not in mesh.get("profiles", {})):
                raise ValueError("Recovery context, calibration or saved mesh changed")
            if self.printer.lookup_object("openace", None) is not None:
                raise ValueError("Recovery owner changed")
            loaded = self._loaded_filament_status(now)
            for key, saved in heads.items():
                if (not self._loaded_source_matches(loaded.get(key, {}), saved)):
                    raise ValueError("Required recovery filament is not loaded with its saved identity")
            if any(self._material_operation_active(name)
                   for name in ("filament_operation", "toolhead_operation")):
                raise ValueError("Unfinished material or tool operation prevents recovery")

        current_evidence()
        sd = self.printer.lookup_object("virtual_sdcard")
        identity = {key: file_info[key] for key in ("path", "size", "modified")}
        full, before = self._print_file(sd, identity)
        digest = hashlib.sha256()
        with open(full, "rb") as stream:
            def unchanged(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == before
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed before verification")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                reactor = self.printer.get_reactor()
                reactor.pause(reactor.monotonic() + 0.001)
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed during verification")
        if digest.hexdigest() != file_info["sha256"] or self._print_file(sd, identity) != (full, before):
            raise ValueError("Recovery file content changed")
        current_evidence()
        if self._read_recovery_job() != record:
            raise ValueError("Recovery job evidence changed during verification")
        return copy.deepcopy(record)

    def _pending_recovery_file(self):
        pending = getattr(self, "_pending_recovery_submission", None)
        if not pending:
            raise ValueError("No current managed print submission: submission is absent")
        if pending["record"]["session"] != self.session_id:
            raise ValueError("No current managed print submission: backend session changed")
        now = self.printer.get_reactor().monotonic()
        sd = self.printer.lookup_object("virtual_sdcard")
        prefix = "Recovery material commit requires the active standalone SD startup: "
        if self.printer.lookup_object("openace", None) is not None:
            raise ValueError(prefix + "openACE owns the printer")
        if not sd.is_cmd_from_sd():
            raise ValueError(prefix + "command is not from virtual SD")
        if not sd.is_active():
            raise ValueError(prefix + "virtual SD worker is inactive")
        state = self.printer.lookup_object("print_stats").get_status(now).get("state")
        if state != "printing":
            raise ValueError(prefix + "print_stats.state=%r; expected 'printing'" % state)
        stream = getattr(sd, "current_file", None)
        if stream is None:
            raise ValueError("Active SD file differs from the submitted job: no file is selected")
        if stream.closed:
            raise ValueError("Active SD file differs from the submitted job: file is closed")
        if os.path.realpath(stream.name) != pending["full"]:
            raise ValueError("Active SD file differs from the submitted job: path changed")
        for label, info in (("open handle", os.fstat(stream.fileno())), ("path", os.stat(pending["full"]))):
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if actual != pending["identity"]:
                changed = [field for field, before, after in zip(
                    ("device", "inode", "size", "mtime_ns"), pending["identity"], actual) if before != after]
                raise ValueError("Active SD file changed after submission: %s %s" % (label, ", ".join(changed)))
        if self._read_recovery_job() != pending["record"]:
            raise ValueError("Staged recovery material evidence changed")
        return pending

    def _stage_active_sd_recovery(self):
        """Stage optional evidence from the actual SD job, regardless of UI."""
        binding = self._stock_startup_file()
        sd = self.printer.lookup_object("virtual_sdcard")
        relative = os.path.relpath(binding["path"], os.path.realpath(sd.sdcard_dirname))
        if relative == ".." or relative.startswith(".." + os.sep):
            raise ValueError("Active print file is outside the SD directory")
        content, tools = hashlib.sha256(), set()
        usage = self._begin_usage_scan(binding["path"])
        with open(binding["path"], "rb") as stream:
            continuing = False
            while True:
                raw = stream.readline(65536)
                if not raw:
                    break
                content.update(raw)
                if usage is not None: usage["scanner"].feed(raw)
                # Hash the whole file without allocating an arbitrarily long
                # slicer polygon/comment line. Only the first chunk can name
                # a command; never interpret continuation text as a new tool.
                line = "" if continuing else raw.decode("utf-8", errors="replace").split(";", 1)[0].split("#", 1)[0].strip()
                if (not continuing and not raw.endswith(b"\n") and len(raw) == 65536
                        and b";" not in raw and b"#" not in raw
                        and re.match(r"(?:T[0-3]|START_PRINT)(?:\s|$)", line, re.IGNORECASE)):
                    raise ValueError("Tool selection line too long to inspect for recovery")
                continuing = not raw.endswith(b"\n")
                match = re.match(r"T([0-3])(?:\s|$)", line, re.IGNORECASE)
                if match:
                    tools.add(int(match.group(1)))
                if re.match(r"START_PRINT(?:\s|$)", line, re.IGNORECASE):
                    initial = re.search(r"\bINITIAL_TOOL=([0-3])(?:\s|$)", line, re.IGNORECASE)
                    if initial:
                        tools.add(int(initial.group(1)))
                if stream.tell() % (1024 * 1024) < len(raw):
                    reactor = self.printer.get_reactor()
                    reactor.pause(reactor.monotonic() + .001)
        self._finish_usage_scan(usage, content.hexdigest(), binding["stream"])
        if not tools:
            raise ValueError("Cannot identify physical tool requirements in the SD file")
        current = self._stock_startup_file()
        if any(current[key] != binding[key] for key in binding):
            raise ValueError("Active SD job changed while staging recovery")
        now = self.printer.get_reactor().monotonic()
        variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
        mapping = [variables.get("box_modify_t%d" % tool) for tool in range(4)]
        if any(type(head) is not int or head not in range(4) for head in mapping):
            raise ValueError("Physical print mapping is unavailable")
        loaded, heads = self._loaded_filament_status(now), {}
        for tool in tools:
            key = "h%d" % mapping[tool]
            head = loaded.get(key, {})
            if head.get("state") != "loaded" or not isinstance(head.get("identity"), dict):
                raise ValueError("Loaded material evidence is unavailable for " + key)
            self._validate_identity(head["identity"])
            heads[key] = {"source": head.get("source"), "identity": copy.deepcopy(head["identity"])}
        info = os.stat(binding["path"])
        record = {"version": 1, "state": "staged", "owner": "standalone",
                  "id": "sd_" + uuid.uuid4().hex, "session": self.session_id,
                  "file": {"path": relative, "size": info.st_size, "modified": info.st_mtime,
                           "sha256": content.hexdigest()},
                  "mapping": mapping, "required_tools": {str(tool): mapping[tool] for tool in sorted(tools)},
                  "heads": heads}
        self._write_recovery_job(record)
        self._pending_recovery_submission = {"record": record, "full": binding["path"],
                                             "identity": binding["identity"]}
        return self._pending_recovery_submission

    def cmd_RECOVERY_JOB_BEGIN(self, gcmd):
        self._bind_usage_stream()
        self._print_recovery_error = ""
        if any(self.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            self._print_mesh_persisted = None
            self.cmd_RECOVERY_JOB_CLEAR(gcmd)
            return
        self._print_mesh_persisted = False
        # One fresh boundary per actual SD START_PRINT invocation. A nested
        # second BEGIN in the same source line cannot erase a current failure.
        try:
            binding = self._stock_startup_file()
            with open(binding["path"], "rb") as source:
                source.seek(binding["positions"][0])
                line = source.readline(8192).decode("utf-8", errors="replace")
            if self._script_command_names(line) != ["START_PRINT"]:
                raise ValueError("Only the actual SD START_PRINT line opens a fresh physical attempt")
            key = (binding["session"], binding["stream"], binding["identity"], binding["positions"])
        except (ValueError, KeyError, AttributeError, TypeError, OSError):
            key = None
        if key is not None and key != getattr(self, "_physical_startup_boundary", None):
            self._physical_startup_boundary = key
            try:
                self._begin_explicit_physical_action("print startup", allow_active=True)
            except ValueError as error:
                raise gcmd.error(str(error)) from error
        try:
            self.printer.lookup_object("gcode").run_script_from_command(
                'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="{}"')
            pending = getattr(self, "_pending_recovery_submission", None)
            if pending:
                try:
                    pending = self._pending_recovery_file()
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    # An old submission cannot reserve a different current SD
                    # print. Build fresh optional evidence from the actual file.
                    pending = None
                    self._pending_recovery_submission = None
            if pending is None:
                self.cmd_RECOVERY_JOB_CLEAR(gcmd)
                pending = self._stage_active_sd_recovery()
            if pending.get("begun"):
                raise ValueError("Print recovery staging already began")
            self._begin_deposition_envelope(pending["record"])
            pending["begun"] = True
        except (OSError, ValueError, KeyError, TypeError, AttributeError, self.printer.command_error) as error:
            self._disable_print_recovery("Recovery staging unavailable: " + str(error))
            gcmd.respond_info(self._print_recovery_error + ". Printing can continue.")

    def cmd_RECOVERY_JOB_COMMIT(self, gcmd):
        if (getattr(self, "_print_mesh_persisted", None) is False
                or getattr(self, "_print_recovery_error", "")):
            self._pending_recovery_submission = None
            self._deposition_envelope = None
            gcmd.respond_info("Power-loss recovery unavailable: " +
                              (getattr(self, "_print_recovery_error", "") or "print mesh was not persisted"))
            return
        if not getattr(self, "_pending_recovery_submission", None):
            gcmd.respond_info("No managed material snapshot; managed power-loss admission is unavailable")
            return
        try:
            pending = self._pending_recovery_file()
            if not pending.get("begun"):
                raise ValueError("Managed startup has not begun")
            now = self.printer.get_reactor().monotonic()
            variables = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            record = pending["record"]
            context = {"version": 2, "tool": variables.get("probe_tool"), "mesh": "wmp_print",
                       "mapping": [variables.get("box_modify_t%d" % i) for i in range(4)],
                       "offsets": [variables.get("t%d_offset" % i) for i in range(4)],
                       "file_hex": record["file"]["path"].encode("utf-8").hex()}
            mesh = self.printer.lookup_object("bed_mesh").get_status(now)
            if (context.get("version") != 2 or context.get("mapping") != record["mapping"]
                    or context.get("file_hex") != record["file"]["path"].encode("utf-8").hex()
                    or type(context.get("tool")) is not int or context["tool"] not in range(4)
                    or context.get("offsets") != [variables.get("t%d_offset" % i) for i in range(4)]
                    or any(variables.get("t%d_offset" % i) is None for i in range(4))
                    or context.get("mesh") != "wmp_print" or mesh.get("profile_name") != "wmp_print"
                    or "wmp_print" not in mesh.get("profiles", {})):
                raise ValueError("Committed mesh, mapping or calibration differs from the managed job")
            loaded = self._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                if (not self._loaded_source_matches(loaded.get(key, {}), saved)):
                    raise ValueError("Loaded filament changed during print startup")
            if any(self._material_operation_active(name)
                   for name in ("filament_operation", "toolhead_operation")):
                raise ValueError("Unfinished material or tool operation at print startup")
            try:
                context["file_effect_contract"] = self._recovery_file_effect_contract()
            except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
                # Optional fallback qualification must never abort normal print.
                logging.info("File-derived recovery fallback unavailable: %s", error)
            encoded = repr(context).replace("\\", "\\\\").replace('"', '\\"')
            self.printer.lookup_object("gcode").run_script_from_command(
                'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="%s"' % encoded)
            current = self.printer.lookup_object("save_variables").get_status(now)["variables"]
            if current.get("wmp_print_context") != context:
                raise ValueError("Print recovery context write was not confirmed")
            committed = dict(record, state="committed", context=copy.deepcopy(context))
            self._write_recovery_job(committed)
            self._pending_recovery_submission = None
        except (OSError, ValueError, KeyError, TypeError, AttributeError,
                self.printer.command_error) as error:
            # Never retry a failed commit against a later job or modified state.
            self._disable_print_recovery("Print recovery commit unavailable: " + str(error))
            gcmd.respond_info(self._print_recovery_error + ". Printing can continue.")

    def cmd_RECOVERY_JOB_CLEAR(self, gcmd):
        self._deposition_envelope = None
        self._pending_recovery_submission = None
        try:
            self._write_recovery_job({"version": 1, "state": "invalidated",
                                      "reason": "print-context-cleared", "session": self.session_id})
            return True
        except (OSError, ValueError) as error:
            # The preceding macro already cleared the saved mesh context.
            # Do not block cancellation's heater/motion cleanup on storage I/O.
            gcmd.respond_info("Recovery material clear failed; cleared print context prevents admission: " + str(error))
            return False

    def _write_recovery_job(self, record):
        # Neither staging nor a startup commit alone authorizes recovery.
        # The recovery entry must still admit the matching checkpoint/state.
        self._write_recovery_json(self._recovery_job_path(), record)

    @staticmethod
    def _write_recovery_json(path, record):
        payload = json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(payload) > 65536:
            raise ValueError("Recovery job record is too large")
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-recovery-job-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _stage_recovery_job(self, gcmd, request, full, file_identity, mapping, admitted_recipes=None):
        if mapping is None:
            # openACE must supply its own durable job/source contract. A stale
            # standalone record must never become fallback authority for it.
            self._write_recovery_job({"version": 1, "state": "owner-required",
                                      "owner": "openace", "id": request["id"],
                                      "session": self.session_id})
            return

        # Recovery metadata is optional, but keep its pre-scan snapshot so an
        # intervening used-head/source change cannot silently replace evidence.
        loaded_error = None
        try:
            loaded = copy.deepcopy(self._loaded_filament_status(self.printer.get_reactor().monotonic()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            loaded, loaded_error = {}, error

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

        content = hashlib.sha256()
        usage = self._begin_usage_scan(full)
        with open(full, "rb") as stream:
            if identity(os.fstat(stream.fileno())) != file_identity:
                raise ValueError("Print file changed before recovery staging")
            for chunk in iter(lambda: stream.readline(65536), b""):
                content.update(chunk)
                if usage is not None: usage["scanner"].feed(chunk)
                # Large G-code files must not starve status/sensor processing.
                # The G-code lock remains held; revalidate after yielding.
                reactor = self.printer.get_reactor()
                if stream.tell() % (1024 * 1024) < len(chunk):
                    reactor.pause(reactor.monotonic() + 0.001)
            if identity(os.fstat(stream.fileno())) != file_identity:
                raise ValueError("Print file changed during recovery staging")
        if identity(os.stat(full)) != file_identity:
            raise ValueError("Print file replaced during recovery staging")
        self.printer.get_reactor().pause(self.printer.get_reactor().monotonic() + .001)
        self._finish_usage_scan(usage, content.hexdigest())
        if loaded_error is not None:
            raise loaded_error
        required = sorted(set(request["mapping"].values()))
        heads = {}
        for head in required:
            key = "h%d" % head
            record = loaded.get(key, {})
            if (record.get("state") != "loaded"
                    or record.get("source") != "external:" + key
                    or not isinstance(record.get("identity"), dict)):
                raise ValueError("Loaded source identity is unavailable for Head %d" % (head + 1))
            self._validate_identity(record["identity"])
            heads[key] = {"source": record["source"], "identity": copy.deepcopy(record["identity"])}

        sd = self._print_admission(gcmd)
        if (self._profiles()[1] != request["profile_revision"] if admitted_recipes is None
                else self._profile_recipes(admitted_recipes) != admitted_recipes):
            raise ValueError("Filament recipe changed during recovery staging")
        variables = self.printer.lookup_object("save_variables").get_status(
            self.printer.get_reactor().monotonic())["variables"]
        if any(variables.get("box_modify_t%d%s" % (tool, suffix)) != head
               for tool, head in enumerate(mapping) for suffix in ("", "_backup")):
            raise ValueError("Tool mapping changed during recovery staging")
        current = self._loaded_filament_status(self.printer.get_reactor().monotonic())
        if any(current.get(key, {}).get("state") != "loaded"
               or any(current[key].get(field) != value for field, value in saved.items())
               for key, saved in heads.items()):
            raise ValueError("Loaded filament changed during recovery staging")
        fresh_full, fresh_identity = self._print_file(sd, request["file"])
        if fresh_full != full or fresh_identity != file_identity:
            raise ValueError("Print file changed during recovery staging")
        # Only the used sliced tools are requirements; unused mapping entries
        # do not require loading otherwise empty physical heads.
        record = {
            "version": 1, "state": "staged", "owner": "standalone",
            "id": request["id"], "session": self.session_id,
            "file": dict(request["file"], sha256=content.hexdigest()),
            "mapping": list(mapping), "required_tools": dict(request["mapping"]),
            "heads": heads}
        self._write_recovery_job(record)
        self._pending_recovery_submission = {"record": copy.deepcopy(record),
                                             "full": full, "identity": file_identity}

    def cmd_DISPATCH_SD_PRINT(self, gcmd):
        # The vendor extended-command parser strips #, ; and * even inside
        # quotes. Decode only at this boundary and retain the SD backend's own
        # work-timer, selected-file, storage and start validation.
        try:
            path = bytes.fromhex(gcmd.get("FILENAME_HEX")).decode("utf-8")
            if (gcmd.get("SESSION") != self.session_id
                    or int(gcmd.get("GENERATION")) != getattr(self, "_command_generation", 0)
                    or self.print_submission.get("state") != "pending"
                    or self.print_submission.get("file") != path):
                raise ValueError("Print dispatch was retired or its selection changed")
            sd = self._print_admission(gcmd)
        except (UnicodeError, ValueError) as error:
            raise gcmd.error(str(error))
        command = self.printer.lookup_object("gcode").create_gcode_command(
            "SDCARD_PRINT_FILE", "", {"FILENAME": path})
        sd.cmd_SDCARD_PRINT_FILE(command)

    def cmd_START_PRINT(self, gcmd):
        request = None
        try:
            encoded = gcmd.get("REQUEST")
            if len(encoded) > 8192 or not re.fullmatch(r"[0-9a-fA-F]+", encoded):
                raise ValueError("Invalid encoded print request")
            request = json.loads(bytes.fromhex(encoded).decode("utf-8"))
            mapping, full, identity = self._print_plan(gcmd, request)
            admitted_recipes = (self._profile_recipes({"h%d" % head for head in request["mapping"].values()})
                                if mapping is not None else None)
        except Exception as error:
            # A refusal receipt proves that no preparation or SD command was
            # attempted. Never replace an already-attempted ticket's outcome.
            if (isinstance(request, dict) and isinstance(request.get("file"), dict)
                    and isinstance(request["file"].get("path"), str)
                    and self._remember_print_ticket(request)):
                self.print_submission = {"id": request["id"], "session": self.session_id,
                                         "file": request["file"]["path"], "state": "refused"}
            raise gcmd.error(str(error))
        if mapping is not None:
            try:
                self._begin_explicit_physical_action("print start")
            except ValueError as error:
                raise gcmd.error(str(error)) from error
        ticket = request["id"]
        self._remember_print_ticket(request)
        self.print_submission = {"id": ticket, "session": self.session_id,
                                 "file": request["file"]["path"], "state": "pending"}
        gcode = self.printer.lookup_object("gcode")
        sd_dispatch_attempted = False
        generation = getattr(self, "_command_generation", 0)
        try:
            self._pending_recovery_submission = None
            # Invalidate historical material evidence before the first admitted
            # new-job side effect, including a startup that subsequently fails.
            self._print_recovery_error = ""
            try:
                self._write_recovery_job({"version": 1, "state": "invalidated",
                                          "reason": "new-print", "id": ticket,
                                          "session": self.session_id})
            except (OSError, ValueError) as error:
                if mapping is None:
                    raise
                self._disable_print_recovery("New-job evidence unavailable: " + str(error))
                gcmd.respond_info("Print will continue without recovery: " + str(error))
            for tool, head in enumerate(mapping or []):
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=box_modify_t%d VALUE=%d" % (tool, head))
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=box_modify_t%d_backup VALUE=%d" % (tool, head))
            gcode.run_script_from_command("G30" if request["leveling"] else "G31")
            if not getattr(self, "_print_recovery_error", ""):
                try:
                    self._stage_recovery_job(gcmd, request, full, identity, mapping, admitted_recipes)
                except (OSError, ValueError) as error:
                    if mapping is None:
                        raise
                    self._disable_print_recovery("Job evidence unavailable: " + str(error))
                    gcmd.respond_info("Print will continue without recovery: " + str(error))
            if mapping is None:
                _, fresh_full, fresh_identity = self._openace_print_plan(gcmd, request, recheck=True)
                if fresh_full != full or fresh_identity != identity:
                    raise gcmd.error("Print file changed during preparation; not started")
                script = 'SDCARD_PRINT_FILE FILENAME="%s" OPENACE_MAP="%s"' % (
                    request["file"]["path"], json.dumps(request["pairs"], separators=(",", ":")))
            else:
                sd = self._print_admission(gcmd)
                current = self.printer.lookup_object("save_variables").get_status(
                    self.printer.get_reactor().monotonic())["variables"]
                if any(current.get("box_modify_t%d%s" % (tool, suffix)) != head
                       for tool, head in enumerate(mapping) for suffix in ("", "_backup")):
                    raise gcmd.error("Prepared mapping was not confirmed; not started")
                self._require_print_materials(request)
                if self._profile_recipes(admitted_recipes) != admitted_recipes:
                    raise gcmd.error("Filament recipe changed during preparation; not started")
                if os.path.realpath(os.path.join(sd.sdcard_dirname, request["file"]["path"])) != full:
                    raise gcmd.error("Print file changed during preparation; not started")
                info = os.stat(full)
                if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity:
                    raise gcmd.error("Print file changed during preparation; not started")
                script = 'SDCARD_PRINT_FILE FILENAME="%s"' % request["file"]["path"]
                if any(char in request["file"]["path"] for char in "#;*"):
                    script = "_WMP_DISPATCH_SD_PRINT FILENAME_HEX=%s SESSION=%s GENERATION=%d" % (
                        request["file"]["path"].encode("utf-8").hex(), self.session_id,
                        getattr(self, "_command_generation", 0))
            if generation != getattr(self, "_command_generation", 0):
                raise gcmd.error("Print request retired during preparation; not started")
            sd_dispatch_attempted = True
            gcode.run_script_from_command(script)
        except Exception as error:
            # Preparation can partially change mapping/leveling settings, but
            # cannot start SD execution. Once dispatch is attempted its outcome
            # is uncertain even if the command raises. Never retry this ticket.
            self._pending_recovery_submission = None
            self.print_submission["state"] = (
                "unknown" if sd_dispatch_attempted else "not_started")
            if not sd_dispatch_attempted:
                self.print_submission["message"] = (
                    "Print was not started. Preparation failed; tool mapping or leveling "
                    "settings may have changed. Review them before trying again.")
                self.print_submission["error"] = str(error)[:240]
            raise
        self.print_submission["state"] = "submitted"
        gcmd.respond_info("Print submitted: " + ticket)

    cmd_STATUS_help = "Report the touchscreen's per-slot filament material"

    def cmd_STATUS(self, gcmd):
        st = self.get_status(None)
        if not st["available"]:
            gcmd.respond_info("Material settings unavailable: cannot read %s" % self.ini_path)
            return
        gcmd.respond_info("Slot materials: " + ", ".join(
            "T%d: %s" % (s, st["material%d" % s])
            for s in range(SLOTS)))


def load_config(config):
    return WMMaterial(config)
