# SPDX-License-Identifier: GPL-3.0-or-later
"""Physical toolhead service, sensor checks and operation outcomes.

Owns toolhead request/result state. Shared printer access and command generation
remain with the material coordinator; stock motion is preserved and pickup checks
settle after retreat, with final identity confirmation before model travel."""
import json
import logging
import math
import os
import re

try:
    from .wmp_filament_types import SLOTS
    from .wmp_persistence import atomic_write
except ImportError:
    from wmp_filament_types import SLOTS
    from wmp_persistence import atomic_write

class ToolheadService:
    def __init__(self, material):
        self.material = material

    def _toolhead_operation_path(self):
        return os.path.join(os.path.dirname(self.material.profile_path), "wmp_toolhead_operation.json")


    def _persist_toolhead_operation(self):
        operation = self.toolhead_operation
        if not operation.get("id"):
            return
        path = self._toolhead_operation_path()
        atomic_write(path, json.dumps({"version": 1, "operation": operation}, sort_keys=True),
                     ".wmp-toolhead-")


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
        operation["session"] = self.material.session_id
        if operation["state"] in ("running", "unknown"):
            operation.update(state="unknown", message="Toolhead operation interrupted by restart; verify attachment before continuing")
            operation.pop("recovered", None)
        self.toolhead_operation = operation
        self._toolhead_requests.add(operation["id"])


    def _ordinary_paused_toolhead_context(self, head, action, now, allow_toolhead=False):
        origin = getattr(self.material, "_pause_origin", None)
        if getattr(self.material, "_toolchange_pause", None) or not origin or origin.get("kind") == "toolchange":
            raise ValueError("Ordinary paused print context is unavailable")
        self.material._paused_filament_origin(head, now)
        if origin["head"] != "h%d" % head:
            raise ValueError("Select the original paused Head %d" % (int(origin["head"][1:]) + 1))
        if (self.material.printer.is_shutdown() or self.material._print_cancel_active()
                or self.material.printer.lookup_object("toolhead").get_status(now).get("homed_axes") != "xyz"
                or not self.material.printer.lookup_object("wmp_recovery").get_status(now).get("z_reference_valid")):
            raise ValueError("Paused head repair needs valid XYZ reference and no cancellation")
        if self.material._identification_pending(now):
            raise ValueError("Wait for head identification")
        if (self.material._material_operation_active("filament_operation")
                or (not allow_toolhead and self.material._material_operation_active("toolhead_operation"))):
            raise ValueError("Wait for the current physical operation")
        offset = origin.get("offset")
        if (not isinstance(offset, (list, tuple)) or len(offset) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offset)):
            raise ValueError("Captured paused coordinate offset is unavailable")
        attachment = self.material._attachment(now)
        expected = {"state": "attached", "head": origin["head"]} if action == "dock" else {"state": "empty", "head": ""}
        if action not in ("take", "dock") or attachment != expected:
            raise ValueError("Dock the original paused head, or mount it from an empty carriage")
        return origin


    def _ordinary_paused_toolhead_status(self, now):
        result = {"head": "", "actions": [], "reason": ""}
        try:
            origin = getattr(self.material, "_pause_origin", None)
            if not origin or getattr(self.material, "_toolchange_pause", None):
                return result
            result["head"] = origin["head"]
            action = "take" if self.material._attachment(now).get("state") == "empty" else "dock"
            self._ordinary_paused_toolhead_context(int(origin["head"][1:]), action, now)
            result["actions"] = [action]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            result["reason"] = str(error)
        return result


    def _toolhead_context(self, head, action, now, fresh=False):
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another filament manager owns toolhead operations: " + ("openace" if self.material.printer.lookup_object("openace", None) is not None else "AFC"))
        if type(head) is not int or not 0 <= head < SLOTS or action not in ("take", "dock"):
            raise ValueError("Invalid physical toolhead action")
        if not self.material._idle_for_filament_settings(now):
            # Explicit repair of this stopped fault is not a competing print.
            # Dispatch revalidates the same binding while its own receipt runs.
            if getattr(self.material, "_toolchange_pause", None):
                self.material._fault_pause_context(now, allow_toolhead=True)
            elif (getattr(self.material, "_pause_origin", None)
                  and self.material._pause_origin.get("kind") != "toolchange"):
                self._ordinary_paused_toolhead_context(head, action, now, allow_toolhead=True)
            else:
                raise ValueError("Toolhead changes require an idle printer or a captured paused print: " + getattr(self.material, "_idle_settings_refusal", "idle admission was not confirmed"))
            if self.material._identification_pending(now):
                raise ValueError("Wait for head identification")
        if self.material._material_operation_active("filament_operation"):
            raise ValueError("Resolve the filament operation first")
        attachment = self.material._attachment(now)
        if attachment["state"] not in ("attached", "empty"):
            raise ValueError("Head attachment sensors disagree")
        if action == "dock" and attachment != {"state": "attached", "head": "h%d" % head}:
            raise ValueError("Selected head is not mounted")
        macro = "_CHANGE_TOOL" if action == "take" else "PARK_CURRENT_TOOL"
        if self.material.printer.lookup_object("gcode_macro " + macro, None) is None:
            raise ValueError("WM toolchange macro is unavailable")
        saved = self.material.printer.lookup_object("save_variables").get_status(now).get("variables", {})
        if (not fresh and saved.get("fail_flag", 0) != 0) or saved.get("is_nozzle_setting", 0) != 0:
            raise ValueError("Inspect the head, then retry Head identification if setup mode remains set; current: " + ("fail_flag=" + repr(saved.get("fail_flag", 0))[:80] if saved.get("fail_flag", 0) != 0 else "is_nozzle_setting=" + repr(saved.get("is_nozzle_setting", 0))[:80]))
        # Preserve normal macro travel/homing. Standalone failure branches retain
        # their faults and refuse automatic coupling, homing or tool-change retries.
        return attachment


    def cmd_TOOLHEAD_PROGRESS(self, gcmd):
        # Presentation only. Print-driven changes have no matching UI operation;
        # never admit/refuse motion or create a receipt from this notification.
        operation = self.toolhead_operation
        phase = gcmd.get("PHASE", "")
        if (operation.get("state") == "running" and operation.get("action") in ("take", "dock")
                and operation.get("head") == "h" + gcmd.get("T", "")
                and phase in {step["phase"] for step in operation.get("steps", [])}
                and phase in ("homing", "docking", "moving")):
            operation["phase"] = phase
            operation["message"] = ("Homing axes..." if phase == "homing" else
                "Docking Head %d..." % (int(operation["previous_head"][1]) + 1) if phase == "docking" else
                "Mounting Head %d..." % (int(operation["head"][1]) + 1) if operation["action"] == "take" else "Docking head...")

    def cmd_TOOLHEAD_ACTION(self, gcmd):
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid toolhead request ID")
        if gcmd.get("SESSION") != self.material.session_id:
            raise gcmd.error("Printer session changed")
        sequenced = self.material._admit_material_sequence(gcmd, "toolhead", request_id)
        requests = self._toolhead_requests
        if not sequenced and request_id in requests:
            raise gcmd.error("Toolhead request already attempted; inspect its result")
        if not sequenced and len(requests) >= 1024:
            raise gcmd.error("Legacy toolhead request limit reached; use the current touchscreen or a SESSION/SEQUENCE request")
        if self.material._material_operation_active("toolhead_operation"):
            raise gcmd.error("Previous toolhead operation is unresolved")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        reactor = self.material.printer.get_reactor()
        try:
            attachment = self._toolhead_context(head, action, reactor.monotonic(), fresh=True)
            paused_origin = (getattr(self.material, "_pause_origin", None)
                             if not getattr(self.material, "_toolchange_pause", None)
                             and self.material.printer.lookup_object("print_stats").get_status(reactor.monotonic()).get("state") == "paused" else None)
            expected = gcmd.get("ATTACHED")
            if expected != (attachment["head"] or "none"):
                raise ValueError("Head attachment changed; review again")
            self.material._begin_explicit_physical_action("toolhead " + action)
        except (ValueError, KeyError, AttributeError, TypeError) as error:
            # A validated request rejected before dispatch still needs an
            # authoritative receipt. An RPC error alone cannot tell the UI
            # whether a physical operation started.
            if not sequenced:
                requests.add(request_id)
            self.toolhead_operation = {"id": request_id, "session": self.material.session_id,
                "head": "h%d" % head, "action": action, "state": "refused",
                "message": str(error)}
            raise gcmd.error(str(error))
        if not sequenced:
            requests.add(request_id)
        previous_head = attachment["head"] if attachment["state"] == "attached" else ""
        switching = action == "take" and previous_head and previous_head != "h%d" % head
        steps = [{"phase": "checking", "label": "Check head attachment"}]
        th = self.material.printer.lookup_object("toolhead").get_status(reactor.monotonic())
        recovery = self.material.printer.lookup_object("wmp_recovery").get_status(reactor.monotonic())
        if not all(axis in th.get("homed_axes", "") for axis in "xy") or (action == "take" and not recovery.get("z_reference_valid")):
            steps.append({"phase": "homing", "label": "Home axes"})
        if switching:
            steps.append({"phase": "docking", "label": "Dock Head %d" % (int(previous_head[1]) + 1)})
        steps.extend([{"phase": "moving", "label": "Mount Head %d" % (head + 1) if action == "take" else "Dock head"},
                      {"phase": "verifying", "label": "Verify attachment sensors"}])
        self.toolhead_operation = {"id": request_id, "session": self.material.session_id,
                                   "head": "h%d" % head, "action": action, "previous_head": previous_head,
                                   "state": "running", "message": ("Mounting Head %d..." if action == "take" else "Docking Head %d...") % (head + 1),
                                   "phase": "checking", "steps": steps}
        # Record intent for diagnostics. Live ownership and the session/request
        # generation retire callbacks independently of durable acknowledgement.
        self._record_toolhead_result()
        generation = getattr(self.material, "_command_generation", 0)
        session = self.material.session_id
        scheduling_failed = False
        def execute(now):
            if scheduling_failed:
                return
            dispatched = False
            try:
                gcode = self.material.printer.lookup_object("gcode")
                with gcode.get_mutex():
                    if session != self.material.session_id or generation != getattr(self.material, "_command_generation", 0):
                        raise ValueError("Toolhead request invalidated by cancellation or restart")
                    if paused_origin is not None and getattr(self.material, "_pause_origin", None) is not paused_origin:
                        raise ValueError("Paused print context changed before dispatch")
                    if self._toolhead_context(head, action, reactor.monotonic()) != attachment:
                        raise ValueError("Head attachment changed before dispatch")
                    run = gcode.run_script_from_command
                    # The legacy dock macro reads current_extruder. Reconcile
                    # that bookkeeping from sensors, never from a UI selection.
                    if attachment["state"] == "attached":
                        run("SAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % int(attachment["head"][1]))
                    dispatched = True
                    first_phase = steps[1]["phase"]
                    self.toolhead_operation["phase"] = first_phase
                    if first_phase == "homing":
                        self.toolhead_operation["message"] = "Homing axes..."
                    elif switching:
                        self.toolhead_operation["message"] = "Docking Head %d..." % (int(previous_head[1]) + 1)
                    run("_CHANGE_TOOL T=%d" % head if action == "take" else "PARK_CURRENT_TOOL")
                    run("M400")
                    self.toolhead_operation["phase"] = "verifying"
                    observed = self.material._attachment(reactor.monotonic())
                    wanted = {"state": "attached", "head": "h%d" % head} if action == "take" else {"state": "empty", "head": ""}
                    saved = self.material.printer.lookup_object("save_variables").get_status(reactor.monotonic()).get("variables", {})
                    if observed != wanted or saved.get("fail_flag", 0) != 0:
                        raise ValueError("Toolhead sensors did not confirm completion")
                    if paused_origin is not None and action == "take":
                        if generation != getattr(self.material, "_command_generation", 0) or self.material.printer.is_shutdown() or self.material._print_cancel_active():
                            raise ValueError("Paused head repair interrupted before offset restoration")
                        self.material._paused_filament_origin(head, reactor.monotonic())
                        # Stock pickup restores its configured offset, whereas
                        # this paused job may have an additional user offset.
                        # Preserve physical position and the original PAUSE states.
                        run("SET_GCODE_OFFSET X=%.17g Y=%.17g Z=%.17g MOVE=0" % tuple(paused_origin["offset"]))
                    self.toolhead_operation.update(state="complete", message="Head mounted" if action == "take" else "Head docked")
            except Exception as error:
                if dispatched:
                    self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
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
        if (gcmd.get("SESSION") != self.material.session_id or operation.get("session") != self.material.session_id
                or gcmd.get("ID") != operation.get("id") or operation.get("head") != "h%d" % head):
            reason = ("SESSION differs from printer session" if gcmd.get("SESSION") != self.material.session_id else
                      "operation session differs from printer session" if operation.get("session") != self.material.session_id else
                      "ID differs from operation" if gcmd.get("ID") != operation.get("id") else
                      "HEAD differs from operation; requested=h%d, recorded=%s" % (head, str(operation.get("head"))[:80]))
            raise gcmd.error("Toolhead operation changed; reopen recovery: " + reason)
        if operation.get("state") != "unknown" or operation.get("action") not in ("take", "dock"):
            raise gcmd.error("Toolhead operation does not need reconciliation: state=%s, action=%s" % (str(operation.get("state"))[:80], str(operation.get("action"))[:80]))

        def context():
            if (self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Another filament manager owns this printer")
            now = self.material.printer.get_reactor().monotonic()
            if not self.material._idle_for_filament_settings(now):
                raise ValueError("Toolhead recovery requires an idle printer")
            if self.material._material_operation_active("filament_operation"):
                raise ValueError("Resolve the filament operation first")
            saved = self.material.printer.lookup_object("save_variables").get_status(now).get("variables", {})
            if saved.get("fail_flag") != 0 or saved.get("is_nozzle_setting") != 0:
                raise ValueError("Finish stock toolhead recovery or setup first")
            attachment = self.material._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("Head attachment sensors disagree")
            return attachment

        try:
            self.material._begin_explicit_physical_action("toolhead reconcile")
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
            self.material.printer.lookup_object("gcode").run_script_from_command("M400")
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


    def cmd_FAILED_PICKUP_CLEANUP(self, gcmd):
        """Stock protective release only at the supported, completed pickup approach.

        This is reached after LOCK returned, not after an actuator exception.
        It always raises the pickup failure, retiring the outer macro tail.
        """
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        def status(name):
            return self.material.printer.lookup_object(name).get_status(reactor.monotonic())
        def guard():
            self.material._check_command_generation(gcmd)
            if self.material.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Pickup cleanup stopped: printer shutdown or stop requested")
            if not gcode.get_mutex().test():
                raise gcmd.error("Pickup cleanup requires command ownership")
            saved = status("save_variables")["variables"]
            if type(saved.get("fail_flag")) is not int or saved["fail_flag"] != 0:
                raise gcmd.error("Pickup cleanup stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        guard()
        evidence = self._pickup_sensors()
        logging.warning("Pickup lock confirmation failed before retreat head=%d hall=%r sensor_b=%r docks=%r",
                        head, evidence["hall"], evidence["locked"], evidence["docks"])
        stage = "dock support"
        message = ""
        try:
            self.material.printer.lookup_object("toolhead").wait_moves()
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
            self.material._recovery_actuator_stroke(False, guard)
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
        self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
        logging.warning(message)
        error = gcmd.error(message)
        error.wmp_toolchange_fault = (-2, "pickup_cleanup")
        raise error


    def cmd_CHECK_DOCK_SUPPORT(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        def guard():
            self.material._check_command_generation(gcmd)
            if self.material.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Dock support verification stopped; inspect the current printer state")
            saved = self.material.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            if saved.get("fail_flag", 0) != 0:
                raise gcmd.error("Dock support verification stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        def read(name, field):
            try:
                return self.material.printer.lookup_object(name, None).get_status(reactor.monotonic()).get(field)
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
        self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
        error = gcmd.error("Head %d dock support not confirmed after %.3fs: docked%d=%r (initial=%r; expected True before unlock). "
                         "Check that the head is fully seated in its dock, then retry. Unlock was not attempted."
                         % (head + 1, elapsed, head, observed, initial))
        error.wmp_toolchange_fault = (-3, "dock_sensor")
        raise error


    def _pickup_sensors(self):
        now = self.material.printer.get_reactor().monotonic()
        def read(name, field):
            try:
                return self.material.printer.lookup_object(name).get_status(now).get(field)
            except (AttributeError, KeyError, TypeError, ValueError):
                return None
        return {"hall": read("custom_hall", "Raw"),
                "locked": read("filament_switch_sensor sensor_b", "filament_detected"),
                "docks": [read("filament_switch_sensor docked%d" % i, "filament_detected") for i in range(4)]}

    def cmd_PICKUP_BEGIN(self, gcmd):
        # Observation only: no motion, admission latch or saved failure state.
        self.material._check_command_generation(gcmd)
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        sensors = self._pickup_sensors()
        hall = sensors["hall"]
        self._pickup_observation = {
            "head": head, "session": self.material.session_id,
            "defer": gcmd.get("DEFER", "0") == "1",
            "generation": getattr(self.material, "_command_generation", 0),
            "empty": type(hall) in (int, float) and 4700 <= hall <= 6000
                     and sensors["locked"] is False and all(v is True for v in sensors["docks"])}
        logging.info("Pickup approach head=%d empty=%r hall=%r sensor_b=%r docks=%r",
                     head, self._pickup_observation["empty"], hall, sensors["locked"], sensors["docks"])

    def cmd_CHECK_PICKUP_RELEASE(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        def guard():
            self.material._check_command_generation(gcmd)
            if self.material.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Pickup verification stopped; inspect the current printer state")
            saved = self.material.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            if saved.get("fail_flag", 0) != 0:
                raise gcmd.error("Pickup verification stopped: current fail_flag=%r" % saved.get("fail_flag"))
            return saved
        def read(name, field):
            try:
                return self.material.printer.lookup_object(name).get_status(reactor.monotonic()).get(field)
            except (AttributeError, KeyError, TypeError, ValueError):
                return None
        guard()
        proof = getattr(self, "_pickup_observation", None)
        self._pickup_observation = None  # One check, never authority for a later pickup.
        def confirmed_approach():
            if (observed is not True or not proof or not proof["empty"]
                    or not proof["defer"] or gcmd.get("FINAL", "0") != "0"):
                return False
            if (proof["head"] != head or proof["session"] != self.material.session_id
                    or proof["generation"] != getattr(self.material, "_command_generation", 0)):
                return False
            sensors = self._pickup_sensors()
            hall = sensors["hall"]
            confirmed = (type(hall) in (int, float) and 3450 <= hall < 4700
                         and sensors["locked"] is True
                         and all(value is True for i, value in enumerate(sensors["docks"]) if i != head))
            if confirmed:
                logging.warning("Pickup provisionally confirmed from empty-to-coupled transition head=%d: "
                                "dock switch still occupied; final identity check required; hall=%r sensor_b=%r docks=%r",
                                head, hall, sensors["locked"], sensors["docks"])
            return confirmed
        start = reactor.monotonic()
        name = "filament_switch_sensor docked%d" % head
        initial = observed = read(name, "filament_detected")
        # M400 finishes motion, not delivery of the MCU button report. A
        # mismatch in the first short observation window is provisional: give
        # the switch a separate stationary recheck before interrupting a print.
        # Clear docks take no extra time. Neither window repeats any motion.
        approach_confirmed = False
        for deadline in (start + .5, start + 2.):
            while observed is not False and reactor.monotonic() < deadline:
                reactor.pause(min(deadline, reactor.monotonic() + .05))
                guard()  # Cancellation/new ownership retires this observation.
                observed = read(name, "filament_detected")
            if observed is False:
                break
            approach_confirmed = confirmed_approach()
            if approach_confirmed:
                break
            if deadline == start + .5:
                logging.warning("Pickup dock indication provisional head=%d docked=%r; "
                                "rechecking while stationary before pausing", head, observed)
        saved = guard()
        elapsed = reactor.monotonic() - start
        hall = read("custom_hall", "Raw")
        locked = read("filament_switch_sensor sensor_b", "filament_detected")
        logging.info("Pickup dock check head=%d initial=%r final=%r elapsed=%.3fs hall=%r sensor_b=%r",
                     head, initial, observed, elapsed, hall, locked)
        if observed is False or approach_confirmed:
            return
        # Current-attempt fault only. Never require a diagnostic disk write or
        # clear an earlier fault; a fresh explicit user action can retry later.
        logging.warning("Pickup confirmation unresolved head=%d approach=%r sensors=%r",
                        head, proof, self._pickup_sensors())
        saved["fail_flag"] = -5
        self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
        error = gcmd.error("Head %d pickup not confirmed after %.3fs: docked%d=%r (initial=%r; expected False after retreat). "
                         "Inspect the picked-up head and its dock switch, then retry; no automatic motion was repeated."
                         % (head + 1, elapsed, head, observed, initial))
        error.wmp_toolchange_fault = (-5, "pickup_dock_sensor")
        raise error


    def _settle_lock_report(self, guard, retry):
        # Wait for the MCU button callback before a fresh _LOCK_CHECK macro
        # decides whether another stock adjustment is needed. No motion, fault
        # flag or rejection is created by a sensor mismatch in this window.
        reactor = self.material.printer.get_reactor()
        def detected():
            sensor = self.material.printer.lookup_object("filament_switch_sensor sensor_b", None)
            return sensor.get_status(reactor.monotonic()).get("filament_detected") if sensor else None
        guard()
        start = reactor.monotonic()
        initial = value = detected()
        while value is not True and reactor.monotonic() < start + 2.:
            reactor.pause(min(start + 2., reactor.monotonic() + .05))
            guard()
            value = detected()
        guard()
        hall = self.material.printer.lookup_object("custom_hall", None)
        raw = hall.get_status(reactor.monotonic()).get("Raw") if hall else None
        logging.info("Lock confirmation retry=%d initial=%r final=%r elapsed=%.3fs hall=%r",
                     retry, initial, value, reactor.monotonic()-start, raw)
        return value is True


    def cmd_COUPLING_STROKE(self, gcmd):
        lock = gcmd.get_int("LOCK", minval=0, maxval=1) == 1
        retry = gcmd.get_int("RETRY", 0, minval=0, maxval=4)
        if retry and not lock:
            raise gcmd.error("Confirmation retry requires LOCK=1")
        gcode = self.material.printer.lookup_object("gcode")
        def guard():
            self.material._check_command_generation(gcmd)
            if self.material.printer.is_shutdown() or getattr(gcode, "quick_stop_flag", False):
                raise gcmd.error("Coupling stopped; inspect the printer before recovery")
            now = self.material.printer.get_reactor().monotonic()
            saved = self.material.printer.lookup_object("save_variables").get_status(now).get("variables", {})
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
                self.material.printer.lookup_object("toolhead").wait_moves()
                guard()
            else:
                self.material._recovery_actuator_stroke(lock, guard, disable_on_success=False)
        except Exception as error:
            try:
                guard()
            except Exception:
                raise gcmd.error(str(error)) from error
            if retry:
                # The failed move bypassed LOCK's final disable. Only clean up
                # this still-owned actuator; retain the original move error.
                try:
                    self.material.printer.lookup_object("echelon_stepper trans_stepper").do_enable(False)
                except Exception:
                    pass
                try:
                    guard()
                except Exception:
                    raise gcmd.error(str(error)) from error
            expected_fault = -2 if lock else -3
            now = self.material.printer.get_reactor().monotonic()
            saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            saved["fail_flag"] = expected_fault
            self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
            logging.warning("Coupling attempt stopped (fail_flag=%d): %s", expected_fault, error)
            failure = gcmd.error(str(error))
            failure.wmp_toolchange_fault = (expected_fault, "coupling_stroke")
            raise failure from error
        if lock:
            self._settle_lock_report(guard, retry)


