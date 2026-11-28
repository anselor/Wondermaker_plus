# SPDX-License-Identifier: GPL-3.0-or-later
"""Material status projection, attachment observation and stock INI refresh."""
import copy
import os

try:
    from . import wmp_orca_profiles, wmp_saved_variables
    from .wmp_observation import _status_observation, copy_status
    from .wmp_filament_types import MATERIALS, SLOTS, material_name, material_temp, parse_slot_materials
except ImportError:
    import wmp_orca_profiles, wmp_saved_variables
    from wmp_observation import _status_observation, copy_status
    from wmp_filament_types import MATERIALS, SLOTS, material_name, material_temp, parse_slot_materials

class MaterialStatus:
    def __init__(self, material):
        self.material = material

    def _saved_variables_ready(self):
        store = self.material.printer.lookup_object("save_variables", None)
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
        recovery = self.material.printer.lookup_object("wmp_recovery", None)
        calibration = getattr(recovery, "calibration", None)
        if (getattr(calibration, "active", False) is True or
                any(getattr(self.material, name, {}).get("state") == "running"
                    for name in ("toolhead_operation", "filament_operation"))):
            reactor = self.material.printer.get_reactor()
            reactor.pause(reactor.monotonic())


    def _refresh(self, eventtime=None):
        try:
            mtime = os.path.getmtime(self.material.ini_path)
        except OSError:
            self._mtime, self._slots = None, {}
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.material.ini_path, "r", errors="replace") as f:
                self._slots = parse_slot_materials(f.read())
            self._mtime = mtime
        except OSError:
            self._mtime, self._slots = None, {}


    def get_status(self, eventtime, detailed=False):
        self.material._drain_async_completions(eventtime)
        previous = getattr(self.material, '_status_observation_cache', None)
        self.material._status_observation_cache = {}
        try:
            return self._status_snapshot(eventtime, detailed=True) if detailed else self._status_snapshot(eventtime)
        finally:
            self.material._status_observation_cache = previous


    def handle_details(self, request):
        # Display review only. Commands still build and validate their own plan.
        request.send(self.get_status(self.material.printer.get_reactor().monotonic(), detailed=True))


    def _status_snapshot(self, eventtime, detailed=False):
        if eventtime is None:
            eventtime = self.material.printer.get_reactor().monotonic()
        self._refresh()
        cancel = copy.deepcopy(getattr(self.material, "_print_cancel", {}))
        if self.material._cancellation().can_clear_cancelled():
            cancel["clearable"] = True
        status = {"available": self._mtime is not None,
                  "ini_path": self.material.ini_path, "session_id": self.material.session_id,
                  "command_generation": getattr(self.material, "_command_generation", 0),
                  "command_generation_protocol": 1,
                  "attachment": self._attachment(eventtime),
                  "toolhead_action_protocol": 1,
                  "material_request_sequence_protocol": 1,
                  "filament_request_sequence": getattr(self.material, "_filament_request_sequence", 0),
                  "toolhead_request_sequence": getattr(self.material, "_toolhead_request_sequence", 0),
                  "toolhead_recovery_protocol": 1,
                  "toolhead_cancel_protocol": 1,
                  "toolhead_operation": dict(getattr(self.material, "toolhead_operation", {})),
                  "toolchange_pause": self.material._toolchange_pause_status(),
                  "print_submission": dict(self.material.print_submission),
                  "print_preparation": self.material._print_preparation().get_status(eventtime),
                  "print_cancel": cancel,
                  "print_cancel_protocol": 1,
                  "print_start_cancel_protocol": 1,
                  "script_generation_protocol": 1 if getattr(self.material, "_cancel_script_wrapper", None) is not None else 0,
                  "print_cancel_ingress_protocol": 1 if getattr(self.material, "_cancel_script_wrapper", None) is not None else 0,
                  "print_cancel_resolution_protocol": 1,
                  "print_cancel_resolution": copy.deepcopy(getattr(self.material, "_print_cancel_resolution", {})),
                  "recovery_review_protocol": 1,
                  "recovery_continue_protocol": 1,
                  "recovery_ticket_protocol": 1,
                  "recovery_stop_protocol": 1,
                  "recovery_early_stop_protocol": 1,
                  "recovery_resolution_protocol": 1,
                  "recovery_retirement_protocol": 1,
                  "recovery_resolution": copy.deepcopy(getattr(self.material, "_recovery_resolution", {})),
                  "recovery_retirement": copy.deepcopy(getattr(self.material, "_recovery_retirement_result", {})),
                  "recovery_stop_requested": getattr(self.material, "_recovery_stop_request", None) is not None,
                  "recovery_submission": copy.deepcopy(getattr(self.material, "_recovery_submission", {})),
                  "recovery_attempt": self.material._recovery_attempt_status(),
                  "recovery_restore_error": getattr(self.material, "_recovery_restore_error", ""),
                  "recovery_execution_sampler": {
                      "state": getattr(self.material, "_execution_state", "starting"),
                      "error": getattr(self.material, "_execution_error", ""),
                      "pending": getattr(self.material, "_pending_execution_snapshot", None) is not None,
                      "published": getattr(self.material, "_execution_last_boundary", None) is not None},
                  "recovery_temperatures": copy.deepcopy(getattr(self.material, "_recovery_temperatures", {})),
                  "profile_import_protocol": 1,
                  "profile_import": dict(getattr(self.material, "profile_import", {"state": "idle"})),
                  "print_mesh_persisted": getattr(self.material, "_print_mesh_persisted", None),
                  "print_recovery_error": getattr(self.material, "_print_recovery_error", ""),
                  "recovery_invalidation_error": getattr(self.material, "_recovery_invalidation_error", ""),
                  "print_start_protocol": 1,
                  "print_sequence_protocol": 1,
                  "print_material_confirmation_protocol": 1,
                  "print_request_sequence": getattr(self.material, "_print_request_sequence", 0),
                  "openace_print_start_protocol": 1,
                  "filament_check_protocol": 0 if any(self.material.printer.lookup_object(owner, None) is not None
                      for owner in ("openace", "AFC")) else 1,
                  "filament_presence": self.material._sensor_filament_status(eventtime),
                  "filament_loaded": self.material._loaded_filament_status(eventtime),
                  "filament_presence_error": getattr(self.material, "_filament_presence_error", ""),
                  "filament_sequence_protocol": 1,
                  "filament_cancel_protocol": 1,
                  "filament_recovery_protocol": 1,
                  "filament_runout_protocol": int(self.material._filament_state()._runout_owned()),
                  "openace_unload_protocol": 1,
                  "openace_load_protocol": 1,
                  "filament_materials": [name for name, temperature in MATERIALS],
                  "filament_operation": dict(self.material.filament_operation),
                  "afc_metadata": {"owner": "openace" if self.material.printer.lookup_object("openace", None) is not None else "AFC" if self.material.printer.lookup_object("AFC", None) is not None else "standalone",
                                   "error": getattr(self.material, "_afc_error", ""), "declined_commands": getattr(self.material, "_afc_declined", [])},
                  "filament_checks": self.material._filament_status(eventtime)}
        status["paused_filament"] = self.material._paused_filament_status(eventtime)
        status["paused_toolhead_actions"] = self.material._ordinary_paused_toolhead_status(eventtime)
        status["resume_progress"] = dict(getattr(self.material, "_resume_progress", {}))
        status["filament_position"] = self.material._filament_position_status(eventtime)
        status["filament_recipe_write_protocol"] = 1
        status["filament_details_protocol"] = 1
        status["filament_details_ready"] = detailed
        status["filament_recipe_write"] = self.material._recipe_write_status(eventtime) if detailed else {}
        status.update(self.material._nozzle_status(eventtime, detailed=detailed))
        status.update(self.material._screen_configuration_status(eventtime))
        status["filament_catalogue"] = []
        if detailed:
            try:
                cached_catalogue = getattr(self.material, '_status_catalogue_snapshot', None)
                if cached_catalogue is None:
                    cached_catalogue = wmp_orca_profiles.read_catalogue(getattr(self.material, "catalogue_path", os.path.join(os.path.dirname(self.material.profile_path), "wmp_filament_catalogue.json")))
                    self.material._status_catalogue_snapshot = copy.deepcopy(cached_catalogue)
                catalogue, revision = copy_status(cached_catalogue)
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
            profiles, revision = self.material._profiles()
            status.update(identities=profiles, identity_revision=revision,
                          identity_writable=True, identity_error="; ".join(getattr(self.material, "_profile_entry_errors", {}).values()),
                          identity_entry_errors=copy.deepcopy(getattr(self.material, "_profile_entry_errors", {})))
        except (ValueError, OSError) as error:
            status.update(identities={}, identity_revision="", identity_writable=False,
                          identity_error=str(error))
        plans, errors = self._procedure_status(status, eventtime) if detailed else ([], {})
        status["filament_procedures"] = plans
        status["filament_procedure_errors"] = errors
        return status


    def _procedure_status_key(self, status, now):
        """Only stopped standalone service has a compact, stable plan context.

        Moving/paused/integrated procedures retain their existing live path.
        This key is display-only: explicit Begin always builds its own plan.
        """
        m = self.material
        if (getattr(m, '_status_observation_cache', None) is None
                or any(m.printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC'))
                or m.printer.lookup_object('wmp_recovery', None) is None
                or status.get('identity_writable') is not True
                or any(getattr(m, name, {}).get('state') in ('pending', 'running', 'unknown')
                       for name in ('filament_operation', 'toolhead_operation'))
                or not m._idle_for_filament_settings(now)):
            return None
        try:
            th = m.printer.lookup_object('toolhead').get_status(now)
            saved = m.printer.lookup_object('save_variables').get_status(now)['variables']
            settings = m.printer.lookup_object('configfile').get_status(now)['settings']
            history = m._hotend_material_history()
            keys = ('probe_tool', 'current_extruder', 'fail_flag', 'is_nozzle_setting')
            keys += tuple('t%d_%s' % (i, kind) for i in range(SLOTS) for kind in ('position', 'offset'))
            return {'session': status['session_id'], 'generation': status['command_generation'],
                    'attachment': status['attachment'], 'loaded': status['filament_loaded'],
                    'identities': status['identities'], 'revision': status['identity_revision'],
                    'history': history, 'history_error': getattr(m, '_hotend_history_error', ''),
                    'geometry': {key: saved.get(key) for key in keys},
                    'travel': {key: th.get(key) for key in ('homed_axes', 'axis_minimum', 'axis_maximum', 'extruder')},
                    'max_temp': [settings.get('extruder' + (str(i) if i else ''), {}).get('max_temp') for i in range(SLOTS)],
                    'feed': getattr(m, 'load_feed_mm', 55.),
                    'purge': getattr(m, 'load_purge_mm', 50.),
                    'cross_purge': getattr(m, 'cross_material_purge_mm', getattr(m, 'load_purge_mm', 50.)),
                    'macros': [m.printer.lookup_object(name, None) is not None for name in
                               ('gcode_macro WIPE_NOZZLE', 'gcode_macro _TIP_SHAPE_MOVES')]}
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            return None

    def _procedure_status(self, status, eventtime):
        key = self._procedure_status_key(status, eventtime)
        cached = getattr(self, '_procedure_status_cache', None)
        if key is not None and cached is not None and key == cached[0]:
            return copy_status(cached[1])
        self._procedure_status_cache = None
        plans, errors = [], {}
        ace_status_cache = {}
        for head in range(SLOTS):
            for action in ('load', 'unload'):
                try:
                    if action == 'load' and self.material.printer.lookup_object('openace', None) is not None:
                        plans.extend(self.material._openace_load_plans(head, eventtime, ace_status_cache))
                    else:
                        plans.append(self.material._filament_plan(head, action, eventtime, ace_status_cache))
                except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
                    errors['h%d:%s' % (head, action)] = str(error)
        result = (plans, errors)
        if key is not None:
            self._procedure_status_cache = (copy.deepcopy(key), copy.deepcopy(result))
        return result


    @_status_observation
    def _attachment(self, eventtime):
        # An active Klipper extruder alone is not proof of an attached head.
        result = {"state": "unknown", "head": ""}
        def status(name):
            obj = self.material.printer.lookup_object(name, None)
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


    def cmd_STATUS(self, gcmd):
        st = self.get_status(None)
        if not st["available"]:
            gcmd.respond_info("Material settings unavailable: cannot read %s" % self.material.ini_path)
            return
        gcmd.respond_info("Slot materials: " + ", ".join(
            "T%d: %s" % (s, st["material%d" % s])
            for s in range(SLOTS)))


