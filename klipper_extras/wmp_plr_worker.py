# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery continuation worker and SD/parser handoff."""
import copy
import hashlib
import json
import logging
import math
import os


class RecoveryWorker:
    def __init__(self, material):
        self.material = material

    def _recovery_disarm_worker(self):
        pending = getattr(self, "_recovery_pending_worker", None)
        if pending is None:
            return
        pending["armed"] = False
        sd = pending["sd"]
        timer = pending.get("timer")
        try:
            if timer is not None:
                self.material.printer.get_reactor().unregister_timer(timer)
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
        reactor = self.material.printer.get_reactor()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        gcode = self.material.printer.lookup_object("gcode")
        stats = self.material.printer.lookup_object("print_stats")
        runner = self.material._recovery_attempt
        if (not gcode.get_mutex().test() or not runner.busy or runner.record["state"] != "running"
                or getattr(self, "_recovery_pending_worker", None) is not None
                or sd.is_active() or sd.is_cmd_from_sd()
                or stats.state != "printing" or stats.filename != execution["file"]["path"]
                or sd.file_position != execution["file_position"]):
            raise ValueError("Recovery worker handoff is not owned or ready")
        token = {"armed": False, "timer": None, "sd": sd,
                 "session": self.material.session_id, "request": copy.deepcopy(runner.record["request"])}
        envelope = getattr(self.material, "_deposition_envelope", None)
        envelope_record = copy.deepcopy(envelope.record) if envelope is not None else None
        self._recovery_pending_worker = token
        runner._save(checkpoint={"job_fingerprint": execution["job_fingerprint"], "file_position": execution["file_position"]},
                     continuation={"state": "scheduled", "file_position": execution["file_position"], "error": ""})
        def verify_observer():
            if envelope is not None:
                self.material._verify_deposition_observer(envelope, envelope_record)
                persisted = json.loads(self.material._recovery_read_bytes(self.material._deposition_envelope_path(), 65536))
                if persisted != envelope_record:
                    raise ValueError("Recovery deposition observer lost durable evidence")
        def work(eventtime):
            if (not token["armed"] or self.material.session_id != token["session"]
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
            runner = getattr(self.material, "_recovery_attempt", None)
            if (runner is not None and binding["session"] == self.material.session_id
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
        reactor = self.material.printer.get_reactor()
        stats = self.material.printer.lookup_object("print_stats")
        gcode = self.material.printer.lookup_object("gcode")
        def validate():
            if (self.material.session_id != session or self.material.printer.is_shutdown()
                    or self.material._print_cancel_active()
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None
                    or runner.record["request"] != request or runner.record["state"] != "complete"
                    or runner.record.get("continuation", {}).get("state") != "paused"
                    or stats.filename != filename or stats.state != "paused"
                    or sd.current_file is not selected_file or selected_file is None
                    or sd.work_handler is not wrapper):
                raise ValueError("Recovered pause no longer owns this Resume")
            if self.material._recovery_fingerprint(self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)) != execution["job_fingerprint"]:
                raise ValueError("Recovered job changed before Resume")
            envelope = getattr(self.material, "_deposition_envelope", None)
            if envelope is None:
                raise ValueError("Recovered deposition evidence is unavailable")
            record = copy.deepcopy(envelope.record)
            self.material._verify_deposition_observer(envelope, record)
            if json.loads(self.material._recovery_read_bytes(self.material._deposition_envelope_path(), 65536)) != record:
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
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        stats = self.material.printer.lookup_object("print_stats")
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
                if (self.material.session_id != token["session"] or self.material.printer.is_shutdown()
                        or stats.filename != filename
                        or self.material.printer.lookup_object("openace", None) is not None
                        or self.material.printer.lookup_object("AFC", None) is not None):
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
        runner = self.material._recovery_attempt
        if (pending["request"] != request or pending["session"] != self.material.session_id
                or runner.record["state"] != "complete" or runner.record["request"] != request
                or not self.material.printer.lookup_object("gcode").get_mutex().test()
                or pending["sd"].work_timer is not pending["timer"]):
            raise ValueError("Recovery worker activation lost ownership")
        # Confirm the completed receipt actually reached disk before activation.
        persisted = json.loads(self.material._recovery_read_bytes(self.material._recovery_attempt_path(), 65536))
        if persisted != runner.record:
            raise ValueError("Recovery completion receipt was not persisted")
        pending["armed"] = True
        reactor = self.material.printer.get_reactor()
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
        gcode = self.material.printer.lookup_object("gcode")
        sd = self.material.printer.lookup_object("virtual_sdcard")
        stats = self.material.printer.lookup_object("print_stats")
        reactor = self.material.printer.get_reactor()
        identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
        if (not gcode.get_mutex().test() or sd.is_active() or sd.is_cmd_from_sd()
                or stats.state != "standby" or stats.print_start_time is not None
                or stats.filename != execution["file"]["path"]
                or sd.file_position != execution["file_position"]
                or self.material._recovery_active_file(sd, identity) != self.material._print_file(sd, identity)):
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
        gcode = self.material.printer.lookup_object("gcode")
        sd = self.material.printer.lookup_object("virtual_sdcard")
        reactor = self.material.printer.get_reactor()
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
        full, before = self.material._print_file(sd, identity)
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
        if digest.hexdigest() != info["sha256"] or self.material._print_file(sd, identity) != (full, before):
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
        if (self.material._recovery_active_file(sd, identity) != (full, before)
                or sd.file_size != info["size"]):
            raise ValueError("Recovery loader selected different file contents")
        seek = gcode.create_gcode_command("M26", "M26 S%d" % position, {"S": str(position)})
        sd.cmd_M26(seek)
        sd.current_file.seek(position)
        idle()
        if (sd.file_position != position or sd.current_file.tell() != position
                or self.material._recovery_active_file(sd, identity) != (full, before)):
            raise ValueError("Recovery file seek was not confirmed")
        return {"file": info["path"], "file_position": position}


