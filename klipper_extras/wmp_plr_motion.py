# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery physical preparation and machine/parser restoration.

Runs only through explicitly admitted continuation stages. Shared attempt state
and cancellation are supplied by the coordinator; this module adds no new gates."""
import copy
import json
import logging
import math

class RecoveryMotion:
    def __init__(self, material):
        self.material = material

    def _recovery_actuator_stroke(self, lock, guard, disable_on_success=True):
        """Use the vendor actuator API below its exception-swallowing command."""
        guard()
        gcode = self.material.printer.lookup_object("gcode")
        if type(lock) is not bool or not gcode.get_mutex().test():
            raise ValueError("Recovery actuator requires direction and command ownership")
        actuator = self.material.printer.lookup_object("echelon_stepper trans_stepper", None)
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
            self.material.printer.lookup_object("toolhead").wait_moves()
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


    def _recovery_bottom_reference(self, toolhead_state):
        """Native homing ends at position_endstop, not the travel maximum."""
        now = self.material.printer.get_reactor().monotonic()
        settings = self.material.printer.lookup_object("configfile").get_status(now)["settings"]
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
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        def status(name):
            return self.material.printer.lookup_object(name).get_status(reactor.monotonic())
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
            if self.material._attachment(reactor.monotonic()) != expected:
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
                run("_UNLOCK_TOOL T=%d SERVICE=1" % int(current["head"][1]))
                attachment({"state": "empty", "head": ""})
            run("_LOCK_TOOL T=%d SERVICE=1 RECOVERY=1" % head)
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
        self.material._verify_recovery_native_selection(review)
        job_bytes = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        if self.material._recovery_fingerprint(job_bytes) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed before preparation")
        record = json.loads(job_bytes)
        if self.material._recovery_clearance_evidence(execution) != review.get("deposition"):
            raise ValueError("Recovery clearance evidence changed before preparation")
        gcode = self.material.printer.lookup_object("gcode")
        reactor = self.material.printer.get_reactor()
        def status(name):
            return self.material.printer.lookup_object(name).get_status(reactor.monotonic())
        expected_attachment = copy.deepcopy(admitted["attachment"])
        reference_z = self._recovery_bottom_reference(status("toolhead"))
        if continue_print and not self.material._install_deposition_observer():
            raise ValueError("Recovery requires a supported deposition observer")
        restored_envelope = [None]
        handoff = {"accounting": False, "queued": False}
        dock_positions = copy.deepcopy([status("save_variables")["variables"].get("t%d_position" % i) for i in range(4)])
        def guard(check_attachment=True):
            if not gcode.get_mutex().test() or self.material.session_id != admitted["session"]:
                raise ValueError("Recovery command ownership or session changed: " + ("G-code mutex is not held" if not gcode.get_mutex().test() else "printer session differs from admitted session"))
            self.material._verify_recovery_native_selection(review)
            if self._recovery_bottom_reference(status("toolhead")) != reference_z:
                raise ValueError("Recovery bottom endstop changed during preparation")
            if self.material._recovery_clearance_evidence(execution) != review["deposition"]:
                raise ValueError("Recovery clearance evidence changed during preparation")
            if restored_envelope[0] is not None:
                self.material._verify_deposition_observer(restored_envelope[0], review["deposition"]["record"])
            if (self.material.printer.is_shutdown() or status("webhooks").get("state") != "ready"
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Recovery readiness or owner changed")
            sd = self.material.printer.lookup_object("virtual_sdcard")
            pending = getattr(self.material, "_recovery_pending_worker", None)
            own_worker = handoff["queued"] and pending is not None and pending["sd"] is sd and sd.work_timer is pending["timer"]
            allowed_stats = ("standby", "complete", "cancelled", "error", "printing") if handoff["accounting"] else ("standby", "complete", "cancelled", "error")
            if ((sd.is_active() and not own_worker) or sd.is_cmd_from_sd()
                    or status("pause_resume").get("is_paused") is not False
                    or status("print_stats").get("state") not in allowed_stats):
                raise ValueError("Another print context interrupted recovery")
            saved = status("save_variables")["variables"]
            if (self.material._recovery_context(saved.get("wmp_print_context")) != self.material._recovery_context(record["context"])
                    or self.material._recovery_offsets([saved.get("t%d_offset" % i) for i in range(4)]) != record["context"]["offsets"]
                    or any(type(saved.get(key)) is not int or saved[key] != 0 for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Recovery calibration, context or fault state changed")
            for name in ("filament_operation", "toolhead_operation"):
                if self.material._material_operation_active(name):
                    raise ValueError("Service operation interrupted recovery preparation")
            loaded = self.material._loaded_filament_status(reactor.monotonic())
            for key, saved_source in record["heads"].items():
                if (not self.material._loaded_source_matches(loaded.get(key, {}), saved_source)):
                    raise ValueError("Loaded source changed during recovery preparation")
            if check_attachment and self.material._attachment(reactor.monotonic()) != expected_attachment:
                raise ValueError("Head attachment changed during reference preparation")
            if self.material._recovery_fingerprint(self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)) != execution["job_fingerprint"]:
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
        def home_xy():
            return self.material._recovery_lifecycle().run_boundary_stage(
                guard, lambda: dispatch("G28 X Y\nM400"))
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
            self.material._recovery_heater_state(reactor.monotonic(), targets.items())
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
                if self.material.printer.lookup_object(name, None) is None:
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
        purge_amount = getattr(self.material, "recovery_purge_mm", getattr(self.material, "load_purge_mm", 50.))
        def prime():
            def priming_guard():
                guard()
                if cancelled():
                    raise ValueError("Recovery priming stopped; do not repeat the purge")
            self._recovery_prime(execution, purge_amount, priming_guard)
        wipe_position = copy.deepcopy(status("save_variables")["variables"].get("wipe_position", [-13., 240.]))
        wipe_macro = self.material.printer.lookup_object("gcode_macro WIPE_NOZZLE", None)
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
            selected_file[:] = [self.material._recovery_select_file(execution, returning_guard)]
        def file_ok():
            returning_guard()
            sd = self.material.printer.lookup_object("virtual_sdcard")
            identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
            return (bool(selected_file) and parser_ok()
                    and sd.file_position == execution["file_position"]
                    and sd.current_file.tell() == execution["file_position"]
                    and self.material._recovery_active_file(sd, identity) == self.material._print_file(sd, identity))
        def fans_ok():
            guard()
            return all(math.isclose(status(name).get("speed", float("nan")), speed,
                                    rel_tol=1e-10, abs_tol=1e-10)
                       for name, speed in fan_targets())
        stages = [("context", lambda: dispatch("_WMP_RECOVERY_BEGIN"), context_ok),
                ("bottom_z", lambda: dispatch("_WMP_HOME_Z_BOTTOM"), bottom_ok),
                ("home_xy", home_xy, xy_ok),
                ("machine_frame", travel_frame, frame_ok),
                ("select_head", select_head, selected_ok),
                ("restore_mesh", lambda: self.material._restore_recovery_mesh(execution, guard),
                 lambda: self.material._recovery_mesh_fingerprint() == execution["mesh_fingerprint"]),
                ("heater_targets", set_heaters, heaters_ok),
                ("fan_targets", set_fans, fans_ok),
                ("heating", lambda: self._wait_recovery_temperatures(execution, guard, cancelled),
                 lambda: self._recovery_temperatures_ready(execution, guard)),
                ("purge_position", purge_position, stage_completed),
                ("prime", prime, stage_completed),
                ("wipe", wipe, stage_completed),
                ("return_xy", return_xy, stage_completed),
                ("return_z", return_z, stage_completed),
                ("return_mesh", lambda: self.material._restore_recovery_mesh(execution, returning_guard),
                 lambda: self.material._recovery_mesh_fingerprint() == execution["mesh_fingerprint"] and stage_completed()),
                ("restore_parser", restore_parser, parser_ok),
                ("select_file", select_file, file_ok)]
        if continue_print:
            def restore_deposition():
                returning_guard()
                # An explicit admitted continuation owns this mutation. Review
                # never materializes the file-derived fallback.
                try:
                    self.material._recovery_read_bytes(self.material._deposition_envelope_path(), 65536)
                except FileNotFoundError:
                    if not self.material.printer.lookup_object("gcode").get_mutex().test():
                        raise ValueError("Recovery envelope publication requires command ownership")
                    self.material._write_recovery_json(self.material._deposition_envelope_path(for_write=True), review["deposition"]["record"])
                if not self.material._begin_deposition_envelope(record, restored=review["deposition"]["record"]):
                    raise ValueError("Recovery deposition restoration failed")
                restored_envelope[0] = self.material._deposition_envelope
            def deposition_ok():
                returning_guard()
                return restored_envelope[0] is not None
            def restore_routes():
                if not file_ok() or self.material._recovery_mesh_fingerprint() != execution["mesh_fingerprint"]:
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
                        and self.material._recovery_mesh_fingerprint() == execution["mesh_fingerprint"]
                        and all(saved.get("box_modify_t%d%s" % (tool, suffix)) == head
                                for tool, head in enumerate(execution["mapping"]) for suffix in ("", "_backup")))
            def accounting():
                if not routes_ok():
                    raise ValueError("Recovery routes were not confirmed")
                handoff["accounting"] = True
                self.material._recovery_start_accounting(execution, returning_guard)
            def accounting_ok():
                return routes_ok() and status("print_stats").get("state") == "printing"
            def queue_worker():
                if not accounting_ok():
                    raise ValueError("Recovery accounting was not confirmed")
                handoff["queued"] = True
                self.material._recovery_queue_worker(execution, returning_guard)
            stages.extend([("restore_deposition", restore_deposition, deposition_ok),
                           ("restore_routes", restore_routes, routes_ok),
                           ("accounting", accounting, accounting_ok),
                           ("start_file", queue_worker, accounting_ok)])
        return stages


    def _recovery_temperatures_ready(self, execution, guard):
        guard()
        now = self.material.printer.get_reactor().monotonic()
        targets = execution["heater_targets"]
        self.material._recovery_heater_state(now, targets.items())
        observed = {}
        ready = True
        for name, target in targets.items():
            current = self.material.printer.lookup_object(name).get_status(now)
            actual_target = current.get("target")
            if (type(actual_target) not in (int, float) or not math.isfinite(actual_target)
                    or not math.isclose(actual_target, target, rel_tol=1e-10, abs_tol=1e-10)):
                raise ValueError("Recovery heater target changed while waiting: " + name)
            temperature = current["temperature"]
            observed[name] = {"temperature": temperature, "target": target}
            if target > 0 and abs(temperature - target) > 2.:
                ready = False
        # Volatile progress only; do not fsync the receipt on each temperature poll.
        self.material._recovery_temperatures = observed
        return ready


    def _wait_recovery_temperatures(self, execution, guard, cancelled, timeout=1200.):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid recovery heating timeout")
        reactor = self.material.printer.get_reactor()
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
        reactor = self.material.printer.get_reactor()
        now = reactor.monotonic()
        toolhead = self.material.printer.lookup_object("toolhead")
        gcode = self.material.printer.lookup_object("gcode")
        state = toolhead.get_status(now)
        recovery = self.material.printer.lookup_object("wmp_recovery").get_status(now)
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
        gcode = self.material.printer.lookup_object("gcode")
        toolhead = self.material.printer.lookup_object("toolhead")
        reactor = self.material.printer.get_reactor()
        settings = self.material.printer.lookup_object("configfile").get_status(reactor.monotonic())["settings"][heater]
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
                    or self.material._attachment(now) != {"state": "attached", "head": execution["head"]}
                    or self.material.printer.lookup_object(heater).get_status(now).get("can_extrude") is not True
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
            move = self.material.printer.lookup_object("gcode_move").get_status(reactor.monotonic())
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
        reactor = self.material.printer.get_reactor()
        toolhead = self.material.printer.lookup_object("toolhead")
        gcode = self.material.printer.lookup_object("gcode")
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
            recovery = self.material.printer.lookup_object("wmp_recovery").get_status(now)
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
            if self.material.printer.lookup_object("bed_mesh").get_mesh() is not None:
                raise ValueError("Recovery travel compensation changed")
            frame = self.material.printer.lookup_object("gcode_move").get_status(reactor.monotonic())
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
        gcode = self.material.printer.lookup_object("gcode")
        toolhead = self.material.printer.lookup_object("toolhead")
        move = self.material.printer.lookup_object("gcode_move")
        mesh = self.material.printer.lookup_object("bed_mesh")
        reactor = self.material.printer.get_reactor()
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
        gcode = self.material.printer.lookup_object("gcode")
        if not gcode.get_mutex().test():
            raise ValueError("Recovery parser restore requires command ownership")
        vectors = [execution[key] for key in ("gcode_position", "homing_origin", "parser_position", "machine_position")]
        factors = [execution[key] for key in ("speed", "speed_factor", "extrude_factor")]
        if (any(not isinstance(v, (list, tuple)) or len(v) != 4 for v in vectors)
                or any(type(v) not in (int, float) or not math.isfinite(v) for vector in vectors for v in vector)
                or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in factors)
                or any(type(execution[key]) is not bool for key in ("absolute_coordinates", "absolute_extrude"))):
            raise ValueError("Invalid recovery parser state")
        now = self.material.printer.get_reactor().monotonic()
        move = self.material.printer.lookup_object("gcode_move")
        toolhead = self.material.printer.lookup_object("toolhead")
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
        after = move.get_status(self.material.printer.get_reactor().monotonic())
        if (not same(list(after["position"]), list(before["position"]))
                or not same(list(toolhead.get_status(now)["position"]), machine)
                or any(not same(list(after[key]), execution[key]) for key in ("gcode_position", "homing_origin"))
                or any(after[key] is not execution[key] for key in ("absolute_coordinates", "absolute_extrude"))
                or any(not math.isclose(after[key], execution[key], rel_tol=1e-10, abs_tol=1e-10)
                       for key in ("speed", "speed_factor", "extrude_factor"))):
            raise ValueError("Recovery parser restoration was not confirmed")
        return True


