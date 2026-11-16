# SPDX-License-Identifier: GPL-3.0-or-later
"""Paused print tool-change repair and explicit retry."""
import copy
import math
import re
import uuid


class ToolchangeRepair:
    def __init__(self, material):
        self.material = material

    def cmd_TOOLCHANGE_FAULT(self, gcmd):
        """Typed coupling failure; only the outer SD boundary may retain a job."""
        now = self.material.printer.get_reactor().monotonic()
        saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
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
            hall = self.material.printer.lookup_object("custom_hall").get_status(now)
            sensor = self.material.printer.lookup_object("filament_switch_sensor sensor_b").get_status(now)
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
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            raise ValueError("Another manager owns paused tool repair")
        self.material._require_no_recovery_attempt()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        pause = self.material.printer.lookup_object("pause_resume")
        position = record["end"] if record["state"] == "ready" else record["start"]
        if (record["session"] != self.material.session_id or sd.current_file is not record["handle"]
                or record["handle"].closed or sd.file_position != position or sd.is_active()
                or sd.is_cmd_from_sd() or not pause.is_paused
                or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"):
            raise ValueError("Wait for the same print to finish pausing")
        if (self.material._print_cancel_active() or self.material.printer.is_shutdown()
                or self.material.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.material.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise ValueError("Paused repair needs valid XYZ reference and no cancellation")
        saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        if [saved.get("box_modify_t%d" % i) for i in range(4)] != record["mapping"]:
            raise ValueError("Tool mapping changed during the paused print")
        if not allow_filament and self.material._material_operation_active("filament_operation"):
            raise ValueError("Wait for the running filament operation")
        if not allow_toolhead and self.material._material_operation_active("toolhead_operation"):
            raise ValueError("Wait for the running toolhead operation")
        return record


    def _fault_manual_toolhead(self, now):
        try:
            self._fault_pause_context(now)
            if self.material._attachment(now).get("state") not in ("attached", "empty"):
                raise ValueError("Head attachment sensors disagree; inspect the head")
            if self.material._identification_pending(now):
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
        origin = getattr(self.material, "_pause_origin", None)
        same = origin and origin.get("kind") == "toolchange" and origin.get("fault") is record
        if same and self.material._material_operation_active("filament_operation"):
            return origin
        attachment = self.material._attachment(now)
        head = attachment.get("head", "")
        if attachment.get("state") != "attached" or head not in ("h0", "h1", "h2", "h3"):
            raise ValueError("Mount a head before paused filament service")
        heater = "extruder" if head == "h0" else "extruder" + head[1:]
        if self.material.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
            raise ValueError("Mounted head and active extruder disagree")
        if same and origin["head"] == head:
            origin["position"] = record["end"] if record["state"] == "ready" else record["start"]
            return origin
        offset = list(self.material.printer.lookup_object("gcode_move").get_status(now)["homing_origin"])[:3]
        if len(offset) != 3 or any(type(v) not in (float, int) or not math.isfinite(v) for v in offset):
            raise ValueError("Paused head offset is unavailable")
        origin = {"kind": "toolchange", "fault": record, "id": uuid.uuid4().hex,
                  "session": self.material.session_id, "file": record["handle"], "head": head,
                  "position": record["end"] if record["state"] == "ready" else record["start"],
                  "offset": offset, "filament_required": sorted(record.get("service_required", set()))}
        self.material._pause_origin = origin
        return origin


    def _check_fault_service_complete(self, record, now):
        self._fault_pause_context(now)
        required = set(record.get("service_required", set())) | self.material._job_filament_losses(record["handle"])
        if required:
            loaded = self.material._loaded_filament_status(now)
            for head in sorted(required):
                if loaded.get(head, {}).get("state") != "loaded":
                    raise ValueError("Load or check filament in Head %d before resuming" % (int(head[1:]) + 1))


    def _toolchange_pause_status(self):
        record = getattr(self, "_toolchange_pause", None)
        if not record:
            return {}
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if (record["session"] != self.material.session_id or sd is None
                or sd.current_file is not record["handle"] or record["handle"].closed):
            return {}
        available, reason = self._fault_manual_toolhead(self.material.printer.get_reactor().monotonic())
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
        now = self.material.printer.get_reactor().monotonic()
        gcode = self.material.printer.lookup_object("gcode")
        if (self.material.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False)
                or self.material._print_cancel_active() or session != self.material.session_id
                or sd.current_file is not handle or handle.closed
                or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                or not self.material.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready")
                or self.material.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.material.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            return False
        context = copy.deepcopy(self.material.printer.lookup_object("gcode_macro _WMP_TOOL_RETURN_BEGIN").get_status(now))
        if stage == "begin":
            gm = self.material.printer.lookup_object("gcode_move").get_status(now)
            th = self.material.printer.lookup_object("toolhead").get_status(now)
            context.update(pending=1, success=0, position=list(gm["gcode_position"])[:3],
                           acceleration=th["max_accel"], feedrate=gm["speed"], override=gm["speed_factor"],
                           absolute=gm["absolute_coordinates"], absolute_e=gm["absolute_extrude"])
        elif not context.get("pending"):
            return False
        saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        target = saved.get("box_modify_t" + commands[0][1])
        if type(target) is not int or target not in range(4):
            return False
        temperatures = {}
        for name in ("heater_bed", "extruder", "extruder1", "extruder2", "extruder3"):
            heater = self.material.printer.lookup_object(name, None)
            if heater is not None:
                temperature = heater.get_status(now).get("target")
                if type(temperature) not in (int, float) or not math.isfinite(temperature) or temperature < 0:
                    return False
                temperatures[name] = temperature
        gm = self.material.printer.lookup_object("gcode_move").get_status(now)
        logical_e = gm["gcode_position"][3]
        active_extruder = self.material.printer.lookup_object("toolhead").get_status(now).get("extruder")
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
        pause = self.material.printer.lookup_object("pause_resume")
        self.material._pause_origin = None
        self._toolchange_pause = {"logical_e": expected_e, "extrude_factor": factor,
            "active_extruder": active_extruder, "captured_logical_e": logical_e,
            "mapping": mapping, "service_required": set(),"state": "paused", "message": str(error), "session": session,
            "handle": handle, "start": start, "end": end, "target": target,
            "logical": commands[0], "context": context, "temperatures": temperatures,
            "stage": stage or "coupling", "wipe_complete": stage == "return",
            "lift": copy.deepcopy(self.material.printer.lookup_object("gcode_macro _descend_z").get_status(now))}
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
            if getattr(self.material, "_pause_origin", None) and self.material._pause_origin.get("kind") == "toolchange":
                self.material._pause_origin = None
            return False
        sd = self.material.printer.lookup_object("virtual_sdcard")
        pause = self.material.printer.lookup_object("pause_resume")
        gcode = self.material.printer.lookup_object("gcode")
        now = self.material.printer.get_reactor().monotonic()
        if (any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))
                or record["state"] not in ("paused", "ready") or sd.is_active() or sd.is_cmd_from_sd()
                or sd.file_position != record["end" if record["state"] == "ready" else "start"] or not pause.is_paused
                or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "paused"
                or self.material.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.material.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise gcmd.error("Tool change retry needs the stopped paused job with homed XYZ; no movement started")
        saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
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
            self.material._begin_explicit_physical_action("print tool change retry")
            attachment = self.material._attachment(self.material.printer.get_reactor().monotonic())
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
            generation = getattr(self.material, "_command_generation", 0)
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
                if (getattr(self.material, "_command_generation", 0) != generation or self.material._print_cancel_active()
                        or self.material.printer.is_shutdown() or sd.current_file is not record["handle"]):
                    raise ValueError("Tool change retry interrupted; no print continuation was started")
                if line.startswith("_CHANGING_TOOL"):
                    record["stage"] = "coupling"
                gcode.run_script_from_command(line)
                if line == "WIPE_NOZZLE":
                    record["wipe_complete"] = True
                if line.startswith("_WMP_TOOL_RETURN_FINISH"):
                    record["stage"] = "return"
                    record["context"]["success"] = 1
            if (self.material.printer.is_shutdown() or sd.current_file is not record["handle"]
                    or sd.file_position != record["start"] or self.material._print_cancel_active()
                    or self.material._attachment(self.material.printer.get_reactor().monotonic()) != {"state": "attached", "head": "h%d" % target}):
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
        record.update(state="ready", return_position=list(self.material.printer.lookup_object("gcode_move").get_status(
            self.material.printer.get_reactor().monotonic())["gcode_position"])[:3])
        return self._resume_completed_toolchange(gcmd, record)


    def _resume_completed_toolchange(self, gcmd, record):
        sd = self.material.printer.lookup_object("virtual_sdcard")
        pause = self.material.printer.lookup_object("pause_resume")
        now = self.material.printer.get_reactor().monotonic()
        position = list(self.material.printer.lookup_object("gcode_move").get_status(now)["gcode_position"])[:3]
        if (self.material._attachment(now) != {"state": "attached", "head": "h%d" % record["target"]}
                or any(abs(a-b) > .00001 for a, b in zip(position, record["return_position"]))):
            # An intervening manual change requires a fresh explicit retry,
            # not a permanent completion latch or a blind worker release.
            record["state"] = "paused"
            sd.file_position = sd.next_file_position = record["start"]
            raise gcmd.error("Print remains paused: attachment or print return position changed. Resume again to recheck the head and restore the print position")
        gm = self.material.printer.lookup_object("gcode_move").get_status(now)
        run = self.material.printer.lookup_object("gcode").run_script_from_command
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
        origin = getattr(self.material, "_pause_origin", None)
        if origin and origin.get("kind") == "toolchange" and origin.get("fault") is record:
            self.material._pause_origin = None
        return True


