# SPDX-License-Identifier: GPL-3.0-or-later
"""Paused print filament service context and resume coordinate restoration."""
import copy
import logging
import math
import re
import uuid


class PausedService:
    def __init__(self, material):
        self.material = material

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
        if (not any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))
                and self.material._toolchange_pause_status()):
            logging.info("Screen Resume preheat omitted for managed tool-change retry; captured job targets own Resume: %s", command)
            return
        send = lambda: self.material.printer.lookup_object("gcode").run_script_from_command(command)
        if command.startswith("M109 "):
            return self._observe_resume(send, phase="preheating")
        return send()


    def cmd_CAPTURE_PAUSE(self, gcmd):
        # Called at the end of WM PAUSE. A failed capture must not unpause the
        # job or prevent the already-requested heater shutdown/parking.
        prior = getattr(self, "_pause_origin", None)
        if any(self.material.printer.lookup_object(owner, None) is not None
               for owner in ("openace", "AFC")):
            # Retained owner macros do not enter standalone capture. A direct
            # call must not replace or erase a prior standalone pause on handover.
            if prior:
                raise gcmd.error("Another manager owns paused filament service")
            return
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        current_file = getattr(sd, "current_file", None)
        same_job = (prior and prior.get("session") == self.material.session_id
                    and current_file is not None and not current_file.closed
                    and prior.get("file") is current_file)
        # Cancellation may leave an unfinished service record for a closed job.
        # It must not prevent capture of a later print's independent pause.
        if (self.material._material_operation_active("filament_operation")
                or (same_job and prior.get("serviced") and not prior.get("ready"))):
            raise gcmd.error("Cannot replace an unresolved filament-service pause")
        self._pause_origin = None
        try:
            now = self.material.printer.get_reactor().monotonic()
            if self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True:
                raise ValueError("Native pause is not established")
            sd = self.material.printer.lookup_object("virtual_sdcard")
            if sd.current_file is None or sd.current_file.closed:
                raise ValueError("No paused SD file")
            attachment = self.material._attachment(now)
            if attachment.get("state") != "attached":
                raise ValueError("Paused head attachment is unknown")
            head = attachment["head"]
            heater = "extruder" if head == "h0" else "extruder" + head[1:]
            if self.material.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
                raise ValueError("Paused head and active extruder disagree")
            saved = self.material.printer.lookup_object("gcode_move").saved_states
            if not all(name in saved for name in ("PAUSE", "PAUSEPARK")):
                raise ValueError("Paused return position is missing")
            self._pause_origin = {"id": uuid.uuid4().hex, "session": self.material.session_id,
                                  "head": head, "file": sd.current_file,
                                  "states": copy.deepcopy({name: saved[name] for name in ("PAUSE", "PAUSEPARK")}),
                                  "recipe": self._pause_recipe(now), "position": None,
                                  "offset": list(self.material.printer.lookup_object("gcode_move").get_status(now)["homing_origin"][:3]),
                                  "filament_required": sorted(self.material._job_filament_losses(sd.current_file))}
            self._pause_origin_error = ""
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            self._pause_origin_error = str(error)
            gcmd.respond_info("Paused filament service unavailable: " + str(error))


    def _pause_recipe(self, now):
        variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        mapping = [variables["box_modify_t%d_backup" % i] for i in range(4)]
        if any(type(head) is not int or not 0 <= head < 4 for head in mapping):
            raise ValueError("Paused tool mapping is invalid")
        resume = self.material.printer.lookup_object("gcode_macro RESUME").get_status(now)
        keys = ["resume_temperature%d" % i for i in range(4)] + ["resume_bed", "zhop", "fan", "afan", "airfan"]
        recipe = {key: resume[key] for key in keys}
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in recipe.values()):
            raise ValueError("Paused resume settings are invalid")
        return {"mapping": mapping, "resume": recipe}


    def _paused_filament_origin(self, head, now):
        """Validate pause ownership; this alone never authorizes service motion."""
        fault = getattr(self.material, "_toolchange_pause", None)
        origin = self.material._fault_service_origin(now) if fault else getattr(self, "_pause_origin", None)
        if not origin or origin["session"] != self.material.session_id:
            raise ValueError("Pause context is unavailable; paused service cannot proceed")
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another manager owns paused filament service")
        sd = self.material.printer.lookup_object("virtual_sdcard")
        if (self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                or self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True
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
            saved = self.material.printer.lookup_object("gcode_move").saved_states
            if any(saved.get(name) != value for name, value in origin["states"].items()):
                raise ValueError("Paused return position changed")
            self._pause_recipe(now)  # Validate current edits; the captured recipe is not a lease.
        if "h%d" % head not in set(origin.get("filament_required", [])) | {origin["head"]}:
            raise ValueError("Select the original paused head or a head that lost filament in this print")
        return {"id": origin["id"], "session": origin["session"],
                "head": origin["head"], "file_position": position}


    def _paused_filament_status(self, now):
        if getattr(self.material, "_toolchange_pause", None):
            try:
                self.material._fault_service_origin(now)
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                return {"available": False, "reason": str(error)}
        origin = getattr(self, "_pause_origin", None)
        if not origin:
            return {"available": False, "reason": "No captured pause context"}
        try:
            context = self._paused_filament_origin(int(origin["head"][1:]), now)
            attachment = self.material._attachment(now)
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
        if plan.get("command_generation", 0) != getattr(self.material, "_command_generation", 0):
            return refuse('command generation changed after admission')
        if self.material._print_cancel_active(): return refuse('print cancellation is unresolved')
        origin = plan.get("pause_origin")
        if not origin:
            if self.material._idle_for_filament_settings(now): return True
            return refuse(getattr(self.material, '_idle_settings_refusal', '') or 'idle admission was not confirmed')
        try:
            if self._paused_filament_origin(int(plan["head"][1:]), now) == origin: return True
            return refuse('paused filament origin differs from admitted origin')
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return refuse('paused filament origin unavailable: ' + type(error).__name__ + ': ' + str(error)[:160])


    def _retire_changed_print_recovery(self, gcmd=None, record=None):
        """Retire optional evidence after a proven edit, never hold resume.

        Backup mapping is the user's resume mapping. Current mapping and
        missing sensor evidence may be transient during tool/service work and
        are deliberately not treated as proof that the job recipe changed.
        """
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return False
        try:
            if record is None:
                record = self.material._read_recovery_job()
            if record.get("state") != "committed" or record.get("owner") != "standalone":
                return False
            sd = self.material.printer.lookup_object("virtual_sdcard")
            self.material._recovery_active_file(sd, {key: record["file"][key]
                                           for key in ("path", "size", "modified")})
            now = self.material.printer.get_reactor().monotonic()
            variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            mapping = [variables.get("box_modify_t%d_backup" % i) for i in range(4)]
            reason = ""
            if (all(type(head) is int and head in range(4) for head in mapping)
                    and mapping != record["mapping"]):
                reason = "Print mapping changed after the saved recovery checkpoint"
            loaded = self.material._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                current = loaded.get(key, {})
                if (current.get("state") == "loaded" and isinstance(current.get("identity"), dict)
                        and isinstance(current.get("source"), str)
                        and not self.material._loaded_source_matches(current, saved)):
                    reason = "Loaded material identity changed after the saved recovery checkpoint"
                    break
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            # Unavailable evidence is not proof of a user edit and cannot
            # prohibit normal resume. Recovery performs its own full review.
            return False
        if not reason:
            return False
        self.material._disable_print_recovery(reason)
        if gcmd is not None:
            gcmd.respond_info(reason + ". Printing can continue without power-loss recovery.")
        return True


    def _observe_resume(self, execute, phase="checking"):
        """Read-only progress for the command lifetime; never an admission flag."""
        if (getattr(self, "_resume_progress", None)
                or any(self.material.printer.lookup_object(owner, None) is not None
                       for owner in ("openace", "AFC"))):
            return execute()
        self._resume_progress = {"phase": phase}
        try:
            if self.material._toolchange_pause_status():
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
            self.material._require_no_recovery_attempt()
            paused_worker = getattr(self.material, "_recovery_paused_worker", None)
            if paused_worker is not None:
                paused_worker["validate"]()
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise gcmd.error(str(error))
        if any(self.material.printer.lookup_object(owner, None) is not None
               for owner in ("openace", "AFC")):
            if getattr(self, "_pause_origin", None):
                raise gcmd.error("Another manager owns paused filament service")
            return
        now = self.material.printer.get_reactor().monotonic()
        try:
            sd = self.material.printer.lookup_object("virtual_sdcard")
            if (self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not True
                    or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                    or sd.is_active() or sd.is_cmd_from_sd()):
                raise ValueError("Wait for the print to finish pausing before resuming")
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error(str(error))
        if self.material._material_operation_active("toolhead_operation"):
            raise gcmd.error("Finish or recover the toolhead operation before resuming")
        operation = self.material.filament_operation
        if self.material._material_operation_active("filament_operation"):
            raise gcmd.error("Finish or recover filament service before resuming")
        origin = getattr(self, "_pause_origin", None)
        if not origin:
            # Ordinary stock pauses need no WM+ service receipt. A confirmed
            # loss in this open job still requires the user's reload/check.
            loaded = self.material._loaded_filament_status(now)
            for head in sorted(self.material._job_filament_losses(sd.current_file)):
                if loaded.get(head, {}).get("state") != "loaded":
                    raise gcmd.error("Load filament in Head %d before resuming" % (int(head[1:]) + 1))
            self._retire_changed_print_recovery(gcmd)
            self._resume_phase("heating")
            return
        try:
            now = self.material.printer.get_reactor().monotonic()
            self._paused_filament_origin(int(origin["head"][1:]), now)
            if origin.get("serviced") and not origin.get("ready"):
                raise ValueError("Complete filament loading before resuming")
            if self.material._attachment(now) != {"state": "attached", "head": origin["head"]}:
                raise ValueError("Mount the original paused head before resuming")
            heater = "extruder" if origin["head"] == "h0" else "extruder" + origin["head"][1:]
            if self.material.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
                raise ValueError("Active extruder does not match the paused head")
            path_sensor = self.material.printer.lookup_object(
                "filament_switch_sensor path_" + origin["head"][1:], None)
            if path_sensor is not None:
                path = path_sensor.get_status(now)
                if path.get("enabled") is not False and path.get("filament_detected") is not True:
                    raise ValueError("Untangle filament for Head %d before resuming" % (int(origin["head"][1:]) + 1))
            loaded = self.material._loaded_filament_status(now)
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
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
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
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            raise gcmd.error("Another manager owns paused filament service")
        logical_e = getattr(self, "_resume_e_correction", None)
        self._resume_e_correction = None
        if logical_e is not None:
            self.material.printer.lookup_object("gcode").run_script_from_command("G92 E%.17g" % logical_e)


