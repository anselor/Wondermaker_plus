# SPDX-License-Identifier: GPL-3.0-or-later
"""Command ingress, sequence retirement and explicit operation routing."""
import logging
import re
import uuid


class CommandRouting:
    def __init__(self, material):
        self.material = material

    def _material_operation_active(self, name):
        state = getattr(self.material, name, {}).get("state")
        if state in ("pending", "running"):
            return True
        # External integration is unchanged by the standalone lifecycle repair.
        return (state == "unknown" and any(self.material.printer.lookup_object(owner, None) is not None
                                          for owner in ("openace", "AFC")))


    def _begin_explicit_physical_action(self, action, allow_active=False):
        """Retire historical fault authority at a fresh user action only.

        Internal macros and post-effect checks must never call this. The
        retained saved-variable status exposes the live dictionary; clearing
        history here needs no diagnostic file write and no replay of old work.
        """
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return
        now = self.material.printer.get_reactor().monotonic()
        saved_object = self.material.printer.lookup_object("save_variables", None)
        if saved_object is None:
            return
        saved = saved_object.get_status(now).get("variables", {})
        old = saved.get("fail_flag", 0)
        mode = saved.get("is_nozzle_setting", 0)
        retire_mode = action == "head identification" and mode != 0
        if old == 0 and not retire_mode:
            saved.setdefault("fail_flag", 0)
            return
        gcode = self.material.printer.lookup_object("gcode")
        if self.material.printer.is_shutdown() or getattr(self.material.printer, "quick_stop_flag", False):
            raise ValueError("Cannot retry while printer is shutdown or stopped")
        if (self.material._print_cancel_active() or self.material._recovery_attempt_active()
                or any(self._material_operation_active(name)
                       for name in ("filament_operation", "toolhead_operation"))):
            raise ValueError("Wait for the current physical operation to stop before retrying")
        recovery = self.material.printer.lookup_object("wmp_recovery", None)
        if recovery is not None:
            current = recovery.get_status(now)
            if (current.get("calibration_active") or current.get("homing")
                    or current.get("identification", {}).get("state") in ("pending", "running")):
                raise ValueError("Wait for current calibration, homing or head identification to stop before retrying")
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if not allow_active and sd is not None and (sd.is_active() or sd.is_cmd_from_sd()):
            raise ValueError("Wait for the current print to stop before retrying")
        if mode != 0 and not retire_mode:
            raise ValueError("Head identification mode remains set; inspect the printer, then retry Head identification to restore normal sensor checks")
        if retire_mode and (type(mode) is not int or mode != 1):
            raise ValueError("Head identification mode is invalid: is_nozzle_setting=%r; inspect the saved configuration before retrying Head identification" % mode)
        # Stationary UNLOCK is itself the way to correct a constrained carriage.
        # Other retries require a coherent present attachment, not an old code.
        if action != "UNLOCK":
            attachment = self.material._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("Current head attachment sensors disagree; inspect seating and release the coupling before retrying")
        if retire_mode:
            # Bypass mode changes physical sensor checks, unlike a diagnostic
            # fault. Restore it durably and verify before a new setup sequence.
            # Only deliberate identification Retry/Start owns this transition.
            try:
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0")
                # Stock SAVE_VARIABLE reloads and replaces its dictionary.
                saved = saved_object.get_status(self.material.printer.get_reactor().monotonic()).get("variables", {})
                observed = saved.get("is_nozzle_setting")
                if type(observed) is not int or observed != 0:
                    raise ValueError("clear readback is %r, expected integer 0" % observed)
            except Exception as error:
                raise ValueError("Cannot restore normal head sensor checks: %s. No identification movement started; correct the reported issue and retry Head identification" % error) from error
            logging.info("Explicit head identification retry cleared interrupted identification mode")
        saved["fail_flag"] = 0
        logging.info("Fresh %s retires historical toolhead failure %r", action, old)


    def _admit_material_sequence(self, gcmd, kind, request_id):
        sequence = gcmd.get("SEQUENCE", None)
        if sequence is None:
            if request_id.startswith(("filament_", "toolhead_")):
                raise gcmd.error("Sequenced material request requires SESSION and SEQUENCE; review again")
            return False
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Sequenced material requests require standalone ownership")
        if gcmd.get("SESSION", None) != self.material.session_id:
            raise gcmd.error("Printer session changed; review again")
        sequence = gcmd.get_int("SEQUENCE", minval=1, maxval=9223372036854775807)
        if request_id != kind + "_" + str(sequence):
            raise gcmd.error("Material request ID does not match SEQUENCE")
        key = "_" + kind + "_request_sequence"
        if sequence <= getattr(self.material, key, 0):
            raise gcmd.error("Material request already attempted or superseded; review again")
        # Consume before any semantic refusal or effect. Missing sequence numbers
        # are valid (a UI may abandon queued work); none can later be replayed.
        setattr(self.material, key, sequence)
        return True


    def _cancel_routes_ready(self):
        """Admit legacy script/API Cancel before run_script acquires its mutex.

        Nested Cancel binds the current job without waiting for its own mutex,
        then unwinds the enclosing command tails. Direct SD and HTTP scripts use
        the same intent and deferred command-owned cleanup.
        """
        gcode = self.material.printer.lookup_object("gcode")
        if getattr(self, "_cancel_script_wrapper", None) is not None:
            return
        original_script = gcode.run_script
        gcode.register_command("_WMP_TOOLCHANGE_FAULT", self.material.cmd_TOOLCHANGE_FAULT)
        gcode.register_command("_WMP_SCREEN_RESUME_PREHEAT", self.material.cmd_SCREEN_RESUME_PREHEAT)
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if sd is not None and callable(getattr(sd, "do_resume", None)):
            original_sd_resume = sd.do_resume
            def sd_resume():
                if self.material._toolchange_pause_status():
                    raise gcode.error("Tool change is paused; use Resume to retry the tool change before continuing this job")
                return original_sd_resume()
            sd.do_resume = sd_resume
        for name in ("RESUME", "M24"):
            original = gcode.register_command(name, None)
            if original is not None:
                def resume(gcmd, original=original):
                    def execute():
                        if not self.material._retry_paused_toolchange(gcmd):
                            return original(gcmd)
                    return self.material._observe_resume(execute)
                gcode.register_command(name, resume)
        original_cancel = gcode.register_command("CANCEL_PRINT", None)
        if original_cancel is None:
            raise self.material.printer.config_error("Managed cancellation requires CANCEL_PRINT")
        self.material._stop_points().install()
        def other_owner():
            return (self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None)
        def request_cancel():
            sd = self.material.printer.lookup_object("virtual_sdcard")
            stats = self.material.printer.lookup_object("print_stats")
            if sd.current_file is None and not sd.is_active() and not sd.is_cmd_from_sd():
                pending = self.material._print_service().cancel_current_pending_start()
                if pending is not None:
                    return pending
                gcode.respond_info("No open print to cancel")
                return
            binding = {"session": self.material.session_id, "file": stats.filename, "handle": sd.current_file}
            return self.material._begin_print_cancel("legacy_cancel_" + uuid.uuid4().hex, binding)
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
            session, generation = self.material.session_id, getattr(self, "_command_generation", 0)
            def check():
                if (session != self.material.session_id or generation != getattr(self, "_command_generation", 0)
                        or (not allow_hold and self.material._print_cancel_active())):
                    raise gcode.error("Command invalidated by cancellation or restart; submit a new command")
                if other_owner():
                    raise gcode.error("Standalone command owner changed")
            boundary = self.material._execution_sd_boundary()
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
                        if self.material._capture_toolchange_pause(boundary, commands, error):
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
                self.material._execution_command_completed(boundary)
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


    def cmd_CHECK_SCRIPT_GENERATION(self, gcmd):
        allow_hold = gcmd.get_int("ALLOW_HOLD", minval=0, maxval=1) == 1
        self._check_command_generation(gcmd, allow_hold)


    def cmd_CHECK_COMMAND_GENERATION(self, gcmd):
        self._check_command_generation(gcmd)


    def _check_command_generation(self, gcmd, allow_cancel_hold=False, finish_coupling=False, coupling_region=False, coupling_owner=None):
        # Prefix to the same run_script RPC as the command. Vendor dispatch
        # aborts the remaining script on command error, while holding its mutex.
        generation = gcmd.get_int("GENERATION", minval=0, maxval=9223372036854775807)
        cancellation = self.material._cancellation()
        active = self.material._print_cancel_active()
        service = getattr(self.material, '_toolhead_service', None)
        if coupling_owner is not None and service is not coupling_owner:
            raise gcmd.error('Coupling command owner changed')
        regions = getattr(service, '_coupling_regions', None)
        protected = coupling_region and regions is not None and regions.allows(gcmd)
        finishing = (finish_coupling and active
            and (regions is None or regions.scope is None)
            and getattr(cancellation, "_coupling_finish_generation", None) == generation
            and getattr(self, "_command_generation", 0) == generation + 1
            and getattr(cancellation, "_print_cancel", {}).get("phase") == "stopping")
        if (gcmd.get("SESSION") != self.material.session_id
                or (generation != getattr(self, "_command_generation", 0) and not finishing and not protected)
                or (not allow_cancel_hold and active and not finishing and not protected)):
            if (gcmd.get("SESSION") == self.material.session_id and active
                    and getattr(cancellation, "_coupling_finish_generation", None) == generation
                    and getattr(self, "_command_generation", 0) == generation + 1
                    and not self.material.printer.is_shutdown()
                    and not getattr(self.material.printer, "quick_stop_flag", False)
                    and self.material.stop_requested() is not None):
                # Same job, exact ordinary Stop fence: retire the macro tail as
                # cancellation, not a print fault. Other invalidations stay errors.
                raise gcmd.error("Print cancellation requested; stopped at command boundary")
            raise gcmd.error("Command invalidated by cancellation or restart; review again")
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Standalone command owner changed")


