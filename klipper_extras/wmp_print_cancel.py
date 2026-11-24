# SPDX-License-Identifier: GPL-3.0-or-later
"""Managed print cancellation and its durable outcome records.

Owns cancellation attempts, request tickets and resolution state. The material
coordinator supplies shared printer access, command generation and PLR evidence;
no operation is dispatched merely by reading this component's state.
"""
import copy
import hashlib
import json
import logging
import math
import os
import re
import uuid


class PrintCancellation:
    _CANCEL_STAGES = ("stopping", "draining", "cooling", "invalidating", "cancelling", "clearing_pause")

    def __init__(self, material):
        self.material = material

    def _handle_print_cancel_review(self, web_request):
        """Capture the exact open print for a separate explicit cancellation.

        Review creates no stop intent, timer, G-code or durable mutation. A
        bounded, expiring token retains the file object so reopening the same
        filename cannot transfer cancellation authority to another print.
        """
        try:
            if web_request.get_str('start', ''):
                return self.material._print_service().review_pending_stop(web_request)
            request = {key: web_request.get_str(key) for key in ("id", "session", "file")}
            if (not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request["id"])
                    or request["session"] != self.material.session_id
                    or not 0 < len(request["file"]) <= 4096):
                raise ValueError("Invalid print cancellation review identity")
            if self._print_cancel_active():
                raise ValueError("Previous print cancellation needs resolution")
            reactor = self.material.printer.get_reactor()
            sd = self.material.printer.lookup_object("virtual_sdcard")
            stats = self.material.printer.lookup_object("print_stats")
            if (self.material.printer.is_shutdown()
                    or self.material.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state") != "ready"
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None
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
                "binding": {"session": self.material.session_id, "file": request["file"], "handle": sd.current_file},
                "expires": reactor.monotonic() + 60.}
            self._print_cancel_tickets = tickets
            web_request.send({"request": request})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise web_request.error(str(error))


    def _handle_print_cancel(self, web_request):
        """Record reactor intent only after the reviewed token is confirmed."""
        try:
            if web_request.get_str('start', ''):
                return self.material._print_service().cancel_pending_stop(web_request)
            request = {key: web_request.get_str(key) for key in ("id", "session", "file", "token")}
            ticket = getattr(self, "_print_cancel_tickets", {}).get(request["id"])
            if (ticket is None or ticket["used"] or request != ticket["request"]
                    or request["session"] != self.material.session_id
                    or self.material.printer.get_reactor().monotonic() >= ticket["expires"]):
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
                    or request["session"] != self.material.session_id):
                raise ValueError("Invalid cancellation resolution identity")
            now = self.material.printer.get_reactor().monotonic()
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
            request = self.material._decode_recovery_json(gcmd.get("REQUEST"), limit=4096)
        except (ValueError, KeyError, TypeError) as error:
            raise gcmd.error(str(error))
        tickets = getattr(self, "_print_cancel_resolution_tickets", {})
        ticket = tickets.get(request.get("id")) if isinstance(request, dict) and isinstance(request.get("id"), str) else None
        if (ticket is None or ticket["used"] or request != ticket["request"]
                or request["session"] != self.material.session_id
                or self.material.printer.get_reactor().monotonic() >= ticket["expires"]):
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
            self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
            self._print_cancel.update(state="complete", phase="complete", message="Print cancellation resolved")
            self._record_print_cancel()
            self.material._recovery_release_paused_worker(cancelled=True)
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
            return hashlib.sha256(self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)).hexdigest()
        except FileNotFoundError:
            return "missing"


    def _print_cancel_resolution_evidence(self, cancel_id, owned=False):
        """Read-only evidence for an explicit finish, discard or acknowledgement."""
        record = getattr(self, "_print_cancel", {})
        reactor = self.material.printer.get_reactor()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        stats = self.material.printer.lookup_object("print_stats")
        if (record.get("id") != cancel_id or record.get("state") != "unknown"
                or not record.get("file") or not record.get("session")
                or self.material.printer.is_shutdown() or self.material.printer.lookup_object("gcode").get_mutex().test() is not owned
                or self.material.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state") != "ready"
                or self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None
                or sd.is_active() or sd.is_cmd_from_sd()
                or getattr(self, "_print_cancel_resolution", {}).get("state") == "pending"):
            raise ValueError("Cancellation resolution requires the stopped standalone attempt")
        if any(op.get("state") in ("pending", "running") for op in
               (self.material.filament_operation, getattr(self.material, "toolhead_operation", {}))):
            raise ValueError("Wait for managed service to stop before resolving cancellation")
        try:
            raw = self.material._recovery_read_bytes(self._print_cancel_path(), 65536)
            saved = json.loads(raw)
            if any(saved.get(key) != record.get(key) for key in ("id", "session", "file")):
                raise ValueError("Durable cancellation identity changed")
            receipt_hash = hashlib.sha256(raw).hexdigest()
        except FileNotFoundError:
            # A same-process intent can fail its first write. No identity may
            # be invented for a missing/corrupt record after process restart.
            live = getattr(self, "_print_cancel_live_binding", None)
            if live is None or live["cancel_id"] != cancel_id or live["session"] != self.material.session_id:
                raise ValueError("Durable cancellation identity is unavailable")
            receipt_hash = "missing"
        binding = {"session": self.material.session_id, "file": stats.filename, "handle": sd.current_file,
                   "job_hash": self._cancel_job_digest()}
        if sd.current_file is not None:
            live = getattr(self, "_print_cancel_live_binding", None)
            if (live is None or live["cancel_id"] != cancel_id or live["session"] != self.material.session_id
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
                        or live["session"] != self.material.session_id
                        or live["file"] != stats.filename
                        or stats.filename != record["file"]
                        or live["handle"] is None or not live["handle"].closed):
                    raise ValueError("Stopped error cannot be identified as the interrupted cancellation")
            binding["idle_resolution"] = True
            action = "finish_idle_cleanup"
        variables = self.material.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
        context = copy.deepcopy(variables.get("wmp_print_context"))
        job = None if binding["job_hash"] == "missing" else self.material._read_recovery_job()
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
        names = self.material.printer.lookup_object("heaters").get_all_heaters()
        if not isinstance(names, (list, tuple)) or not names:
            raise ValueError("Heater inventory is unavailable")
        for name in names:
            target = self.material.printer.lookup_object(name).get_status(reactor.monotonic()).get("target")
            if type(target) not in (int, float) or not math.isfinite(target):
                raise ValueError("Heater target is unavailable")
            heaters[name] = target
        paused = self.material.printer.lookup_object("pause_resume").get_status(reactor.monotonic()).get("is_paused")
        begin = self.material.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(reactor.monotonic()).get("active")
        body = self.material.printer.lookup_object("gcode_macro START_PRINT").get_status(reactor.monotonic()).get("print_body_ready")
        if (action == "finish_idle_cleanup" and context == {} and paused is False
                and type(variables.get("changing_tool", 0)) is int and variables.get("changing_tool", 0) == 0
                and begin in (False, 0) and body in (False, 0) and all(v == 0 for v in heaters.values())):
            action = "acknowledge_complete"
        return {"binding": binding, "action": action, "cancel_id": cancel_id,
                "receipt_hash": receipt_hash, "record": copy.deepcopy(record), "context": context,
                "job_id": job_id, "heaters": heaters,
                "paused": paused, "begin": begin, "body": body}


    def _print_cancel_path(self):
        return os.path.join(os.path.dirname(self.material.profile_path), "wmp_print_cancel.json")


    def _print_cancel_unresolved(self):
        """Diagnostic history, not standalone machine-operation admission."""
        return getattr(self, "_print_cancel", {}).get("state") in ("pending", "unknown")


    def _print_cancel_active(self):
        # Pending belongs to this process's queued/running cleanup. Unknown is
        # a terminal or restored result; its old callback cannot run again.
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return self._print_cancel_unresolved()
        return getattr(self, "_print_cancel", {}).get("state") == "pending"


    def _record_print_cancel(self):
        record = dict(self._print_cancel)
        record.pop("persistence_error", None)
        try:
            self.material._write_recovery_json(self._print_cancel_path(), record)
        except (OSError, ValueError) as error:
            message = str(error)[:256]
            if self._print_cancel.get("persistence_error") != message:
                logging.warning("Unable to persist cancellation result: %s", message)
            self._print_cancel["persistence_error"] = message


    def _print_cancel_stage(self, name, state="running"):
        record = self._print_cancel
        if "stages" not in record:
            record.update(version=max(2, record.get("version", 2)),
                          stages=[{"name": n, "state": "pending"} for n in self._CANCEL_STAGES])
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
            record = json.loads(self.material._recovery_read_bytes(self._print_cancel_path(), 65536))
            version = record.get("version") if isinstance(record, dict) else None
            keys = {"version", "id", "session", "file", "state", "phase", "message"}
            if version in (2, 3):
                keys.add("stages")
            # Version 3 adds an optional stop_point written by wmp_stop_points.
            if (type(version) is not int or version not in (1, 2, 3)
                    or not (set(record) == keys or (version == 3 and set(record) == keys | {"stop_point"}))
                    or not isinstance(record["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", record["id"])
                    or not isinstance(record["session"], str) or not record["session"]
                    or not isinstance(record["file"], str) or not record["file"]
                    or record["state"] not in ("pending", "unknown", "complete")
                    or not isinstance(record["phase"], str) or not isinstance(record["message"], str)):
                raise ValueError("Invalid print cancellation record")
            if "stop_point" in record:
                stop = record["stop_point"]
                if (not isinstance(stop, dict) or set(stop) != {"phase", "label", "state"}
                        or any(not isinstance(value, str) for value in stop.values())
                        or not re.fullmatch(r"[a-z0-9_]{1,48}", stop["phase"])
                        or len(stop["label"]) > 160 or len(stop["state"]) > 160):
                    raise ValueError("Invalid cancellation stop point")
            if record["version"] >= 2:
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
        sd = self.material.printer.lookup_object("virtual_sdcard")
        stats = self.material.printer.lookup_object("print_stats")
        reactor = self.material.printer.get_reactor()
        gcode = self.material.printer.lookup_object("gcode")
        current_refusal = ['']
        def current():
            def refuse(reason):
                current_refusal[0] = reason
                return False
            current_refusal[0] = ''
            if binding["session"] != self.material.session_id: return refuse('printer session changed')
            if self.material.printer.is_shutdown(): return refuse('printer is shut down')
            state = self.material.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state")
            if state != "ready": return refuse('webhooks.state=' + repr(state)[:80])
            if self.material.printer.lookup_object("openace", None) is not None: return refuse('openace owner is present')
            if self.material.printer.lookup_object("AFC", None) is not None: return refuse('AFC owner is present')
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
        # Only an already-admitted coupling stroke may finish across this fence.
        self._coupling_finish_generation = getattr(self.material, "_command_generation", 0)
        self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
        used.add(request_id)
        self._print_cancel_requests = used
        self._print_cancel_live_binding = dict(binding, cancel_id=request_id)
        self._print_cancel = {"version": 2, "id": request_id, "session": self.material.session_id,
            "file": binding["file"], "state": "pending", "phase": "stopping",
            "message": "Waiting for current work to stop",
            "stages": [{"name": n, "state": "running" if n == "stopping" else "pending"}
                       for n in self._CANCEL_STAGES]}
        def persist():
            self._record_print_cancel()
        def unknown(error):
            # Terminal failure retires commands admitted during the live stop,
            # just as successful cleanup does. History never revives that tail.
            self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
            self._print_cancel.update(state="unknown", message=str(error))
            self._print_cancel_interrupted_stages()
            try:
                persist()
            except (OSError, ValueError):
                pass  # Preserve the in-memory result; never fabricate completion.
        # Stop intent is live state, not contingent on diagnostic storage.
        sd.must_pause_work = True
        if (self.material.filament_operation.get("state") == "running"
                and self.material.filament_operation.get("session") == self.material.session_id):
            self.material.filament_operation.update(cancel_requested=True,
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
                    self.material._command_generation = getattr(self.material, "_command_generation", 0) + 1
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
        """Cleanup an admitted, stopped SD job and lower its homed bed.

        Private primitive: the reactor intent/fence must stop SD dispatch and
        acquire the G-code mutex before calling. The caller journals any partial
        outcome; an exception never authorizes replay of the old cleanup.
        """
        self.material._close_stop_waits()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        stats = self.material.printer.lookup_object("print_stats")
        gcode = self.material.printer.lookup_object("gcode")
        reactor = self.material.printer.get_reactor()
        idle_resolution = binding.get("idle_resolution") is True
        cancelled = [idle_resolution]
        def guard():
            def refuse(reason):
                raise ValueError("Print cancellation lost its stopped job or command ownership: " + reason)
            if binding["session"] != self.material.session_id: refuse('printer session changed')
            if self.material.printer.is_shutdown(): refuse('printer is shut down')
            if not gcode.get_mutex().test(): refuse('G-code mutex is not held')
            if self.material.printer.lookup_object("openace", None) is not None: refuse('openace owner is present')
            if self.material.printer.lookup_object("AFC", None) is not None: refuse('AFC owner is present')
            state = self.material.printer.lookup_object("webhooks").get_status(reactor.monotonic()).get("state")
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
        def drain():
            run("M400")
            try:
                from .wmp_stop_points import finish_cancelled_toolchange
            except ImportError:
                from wmp_stop_points import finish_cancelled_toolchange
            finish_cancelled_toolchange(self.material.printer, lambda: guard() is None)
        drained = attempt("draining", drain)
        def cool():
            run("TURN_OFF_HEATERS")
            names = self.material.printer.lookup_object("heaters").get_all_heaters()
            if not isinstance(names, (list, tuple)) or not names:
                raise ValueError("Heater inventory is unavailable")
            for name in names:
                target = self.material.printer.lookup_object(name).get_status(reactor.monotonic()).get("target")
                if type(target) not in (int, float) or target != 0:
                    raise ValueError("Heater shutdown is not confirmed for %s" % name)
        attempt("cooling", cool)
        def invalidate():
            if "job_hash" in binding and self._cancel_job_digest() != binding["job_hash"]:
                raise ValueError("Saved job changed before cancellation invalidation")
            run("_WMP_PRINT_CONTEXT_CLEAR")
            variables = self.material.printer.lookup_object("save_variables").get_status(reactor.monotonic())["variables"]
            context = self.material._read_recovery_job()
            if (variables.get("wmp_print_context") != {}
                    or context.get("state") != "invalidated" or context.get("session") != self.material.session_id
                    or self.material.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(reactor.monotonic()).get("active") not in (False, 0)):
                raise ValueError("Cancelled job recovery authority was not invalidated")
            run("SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False")
            if self.material.printer.lookup_object("gcode_macro START_PRINT").get_status(reactor.monotonic()).get("print_body_ready") not in (False, 0):
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
            if self.material.printer.lookup_object("pause_resume").get_status(reactor.monotonic()).get("is_paused") is not False:
                raise ValueError("Native pause cleanup was not confirmed")
            self.material._recovery_release_paused_worker(cancelled=True)
        attempt("clearing_pause", clear_pause)
        # Lower only an actual cancelled job after its queued motion drained.
        # The shared helper clamps physical Z, then parks only with homed axes,
        # actual clearance and confirmed attachment. No home, pickup, E or wipe.
        mesh_cleared = False
        if drained and cancelled[0] and not idle_resolution:
            try:
                run("BED_MESH_CLEAR")
                mesh_cleared = True
                run("_WMP_PRINT_LOWER_BED PARK=1")
                run("M400")
            except Exception as error:
                warnings.append("bed lowering/parking: " + str(error))
        # These independent actions restore stock non-motion housekeeping.
        housekeeping = ["M107"] + ([] if mesh_cleared else ["BED_MESH_CLEAR"]) + ["M220 S100",
            "SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=adaptive_mesh VALUE=0",
            "RESET_FLOW_EXTRUDER"]
        # Keep the selected tool mapping and physical Z reference. A cancelled
        # attempt did not acquire ownership of the user's persistent selection.
        try:
            settings = self.material.printer.lookup_object("configfile").get_status(reactor.monotonic())["settings"]
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


