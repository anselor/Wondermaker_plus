# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery review, explicit requests and result reconciliation."""
import copy
import hashlib
import json
import math
import os
import re
import uuid

try:
    from . import wmp_recovery_retirement
    from .wmp_plr_records import RecoveryAttempt
except ImportError:
    import wmp_recovery_retirement
    from wmp_plr_records import RecoveryAttempt

class RecoveryReview:
    def __init__(self, material):
        self.material = material

    def _recovery_retirement_store(self):
        directory = os.path.dirname(self.material.profile_path)
        return wmp_recovery_retirement.EvidenceStore(
            directory, getattr(self.material, 'recovery_checkpoint_dir', directory),
            runtime_directory=getattr(self.material, 'recovery_checkpoint_dir', directory))


    def _recovery_retirement_admit(self, session, locked):
        # This operation retires saved evidence. It does not move the printer,
        # reset physical faults, change targets, or claim recovery succeeded.
        if session != self.material.session_id:
            raise ValueError('Recovery printer session changed')
        if locked and not self.material.printer.lookup_object('gcode').get_mutex().test():
            raise ValueError('Recovery discard command ownership changed')
        if any(self.material.printer.lookup_object(owner, None) is not None
               for owner in ('openace', 'AFC')):
            raise ValueError('Another filament manager owns recovery')
        if self.material._recovery_attempt_active() or self.material._print_cancel_active():
            raise ValueError('Wait for the running recovery or cancellation to stop before discarding its evidence')
        now = self.material.printer.get_reactor().monotonic()
        sd = self.material.printer.lookup_object('virtual_sdcard')
        if not locked:
            return {'session': session, 'file': getattr(sd, 'current_file', None)}
        pause = self.material.printer.lookup_object('pause_resume').get_status(now)
        stats = self.material.printer.lookup_object('print_stats').get_status(now)
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
            if getattr(self.material, '_recovery_restore_error', ''):
                self.material._restore_recovery_attempt()
                if self.material._recovery_restore_error:
                    raise ValueError(self.material._recovery_restore_error)
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
            if session != self.material.session_id:
                raise ValueError('Recovery printer session changed')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', request_id):
                raise ValueError('Invalid recovery discard request')
            receipt = self._recovery_retirement_store().retirement()
            if session != self.material.session_id:
                raise ValueError('Recovery printer session changed')
            result = {'id': request_id, 'state': 'unknown'}
            if receipt is not None and receipt['id'] == request_id:
                result = dict(receipt, state='complete' if receipt['matches'] else 'superseded')
            web_request.send({'session': session, 'result': result})
        except Exception as error:
            raise web_request.error(str(error))


    def _require_recovery_not_retired(self):
        retired = self._recovery_retirement_store().retirement()
        if retired is not None and retired['matches']:
            raise ValueError("Recovery for this saved print was explicitly discarded; original records are archived")


    def _recovery_machine_state(self, session, values=None, allow_invalid_recovery=False):
        """Read current prerequisites; caller still must serialize preparation."""
        if session != self.material.session_id or not isinstance(session, str):
            raise ValueError("Recovery printer session changed")
        now = self.material.printer.get_reactor().monotonic()
        if (self.material.printer.is_shutdown()
                or self.material.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"):
            raise ValueError("Printer is not ready for recovery")
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Another filament manager owns recovery")
        if not self.material._idle_for_filament_settings(now, allow_invalid_recovery=allow_invalid_recovery):
            raise ValueError("Another print, pause or identification context owns the printer: " + getattr(self.material, "_idle_settings_refusal", "idle admission was not confirmed"))
        for name in ("filament_operation", "toolhead_operation"):
            operation = getattr(self.material, name, {})
            if self.material._material_operation_active(name):
                raise ValueError("Resolve the material or tool operation before recovery: %s.state=%s" % ("filament_operation" if operation is self.material.filament_operation else "toolhead_operation", str(operation.get("state"))[:80]))
        variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        if any(type(variables.get(key)) is not int or variables[key] != 0
               for key in ("is_nozzle_setting",)):
            raise ValueError("Inspect the head, then retry Head identification to clear interrupted setup before recovery: " + next(key + "=" + repr(variables.get(key))[:80] + "; expected integer 0" for key in ("is_nozzle_setting",) if type(variables.get(key)) is not int or variables[key] != 0))
        recovery = self.material.printer.lookup_object("wmp_recovery").get_status(now)
        if (recovery.get("homing") is not False or recovery.get("calibration_active") is not False
                or recovery.get("identification", {}).get("state") != "idle"):
            raise ValueError("Homing, calibration or identification prevents recovery: " +
                             ("homing=" + repr(recovery.get("homing"))[:80] if recovery.get("homing") is not False else
                              "calibration_active=" + repr(recovery.get("calibration_active"))[:80] if recovery.get("calibration_active") is not False else
                              "identification.state=" + repr(recovery.get("identification", {}).get("state"))[:80]))
        if self.material.printer.lookup_object("gcode_macro _WMP_RECOVERY_BEGIN").get_status(now).get("active") is not False:
            raise ValueError("Recovery preparation is already active")
        attachment = self.material._attachment(now)
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
        settings = self.material.printer.lookup_object("configfile").get_status(now)["settings"]
        for name, target in targets:
            heater = self.material.printer.lookup_object(name, None)
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
        path = os.path.join(self.material.recovery_checkpoint_dir, selection["checkpoint"])
        payload = self.material._recovery_read_bytes(path, 65536)
        marker = self.material._recovery_read_bytes(path + ".wmp-coordinates", 256).decode("ascii").split()
        if (self.material._recovery_fingerprint(payload) != selection["checkpoint_hash"]
                or marker != ["WMP-GCODE-XYZ-MATERIAL-2", selection["checkpoint_hash"], selection["job_hash"]]
                or self.material._recovery_fingerprint(self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)) != selection["job_hash"]
                or self.material._recovery_fingerprint(self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)) != review["execution_hash"]):
            raise ValueError("Recovery selection changed before continuation")


    def _recovery_ticket_state(self):
        state = getattr(self, "_recovery_tickets", None)
        if state is None or state["session"] != self.material.session_id:
            # Native protocol requires ID == prefix + decimal sequence. Seed
            # the counter per session so retained attempts never collide with
            # the next session's first request; leave 32 bits for local counts.
            seed = int.from_bytes(hashlib.sha256(self.material.session_id.encode("utf-8")).digest()[:16], "big") << 32
            state = {"session": self.material.session_id, "continue": {"issued": seed, "consumed": seed, "slots": {}},
                     "resolve": {"issued": seed, "consumed": seed, "slots": {}}}
            self._recovery_tickets = state
        return state


    def _issue_recovery_ticket(self, kind, request):
        """Bounded read-only evidence ticket, never a physical reservation."""
        if request["session"] != self.material.session_id:
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
        if request["session"] != self.material.session_id:
            raise ValueError("Recovery ticket printer session changed")
        state = self._recovery_ticket_state()[kind]
        slot = "continue" if kind == "continue" else request["action"]
        issued = state["slots"].get(slot)
        if (issued is None or issued["sequence"] <= state["consumed"]
                or issued["request"] != request or issued["ticket"]["token"] != token):
            raise ValueError("Recovery ticket was consumed, superseded, or does not match this request; review again")
        if kind == 'continue' and issued.get('cancel_requested') is True and getattr(self, '_recovery_command_active', False):
            self._recovery_stop_request = {key: request[key] for key in ('id', 'session', 'file', 'execution_hash')}
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
            gcode = self.material.printer.lookup_object("gcode")
            if gcode.get_mutex().test():
                raise ValueError("Printer command is busy; review recovery when idle")
            request = {key: web_request.get_str(key) for key in
                       ("id", "session", "file", "checkpoint", "checkpoint_hash", "job_hash")}
            selected = request["file"]
            if os.path.isabs(selected):
                root = os.path.realpath(self.material.printer.lookup_object("virtual_sdcard").sdcard_dirname)
                if os.path.commonpath((root, selected)) != root:
                    raise ValueError("Selected recovery file is outside the G-code directory")
                request["file"] = os.path.relpath(selected, root)
            execution_bytes = self.material._recovery_execution_bytes()
            self.material._parse_recovery_execution_format(execution_bytes)
            envelope_bytes = self.material._recovery_deposition_payload(json.loads(execution_bytes))
            request.update(version=1, owner="standalone",
                           execution_hash=self.material._recovery_fingerprint(execution_bytes),
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
        runner = self.material._recovery_attempt
        receipt = runner.record
        now = self.material.printer.get_reactor().monotonic()
        if (identity["session"] != self.material.session_id or runner.busy
                or getattr(self, "_recovery_command_active", False)
                or receipt is None or receipt["state"] not in ("unknown", "stopped")
                or receipt["request"]["id"] != identity["attempt_id"]
                or (identity["action"] != "abandon" and (self.material.printer.is_shutdown()
                or self.material.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"))
                or self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise ValueError("Recovery resolution request, owner or readiness changed: " +
                             ("SESSION differs from printer session" if identity["session"] != self.material.session_id else
                              "recovery runner is busy" if runner.busy else
                              "recovery command is active" if getattr(self, "_recovery_command_active", False) else
                              "recovery receipt is missing" if receipt is None else
                              "receipt.state=" + repr(receipt["state"])[:80] if receipt["state"] not in ("unknown", "stopped") else
                              "attempt ID differs from receipt" if receipt["request"]["id"] != identity["attempt_id"] else
                              "printer is shut down" if self.material.printer.is_shutdown() else
                              "webhooks is not ready" if self.material.printer.lookup_object("webhooks").get_status(now).get("state") != "ready" else
                              "openace owner is present" if self.material.printer.lookup_object("openace", None) is not None else "AFC owner is present"))
        journal = self.material._recovery_read_bytes(self.material._recovery_attempt_path(), 65536)
        if json.loads(journal) != receipt:
            raise ValueError("Recovery attempt journal changed")
        execution = self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)
        execution_hash = self.material._recovery_fingerprint(execution)
        if identity["action"] == "reconcile" and (
                receipt.get("continuation", {}).get("state") != "interrupted"
                or receipt["request"]["session"] == self.material.session_id
                or execution_hash == receipt["request"]["execution_hash"]):
            raise ValueError("Reconciliation requires a new checkpoint after interrupted continuation")
        return dict(identity, version=1, journal_sha256=hashlib.sha256(journal).hexdigest(),
                    execution_hash=execution_hash)


    def _handle_recovery_resolution_review(self, web_request):
        try:
            gcode = self.material.printer.lookup_object("gcode")
            identity = {key: web_request.get_str(key) for key in ("id", "attempt_id", "session", "action")}
            request = self._recovery_resolution_selection(identity)
            if identity["action"] == "reconcile":
                self.material._reconcile_recovery_continuation(identity["session"], identity["attempt_id"],
                                                      request["execution_hash"], review_only=True)
            else:
                self.material._abandon_recovery_attempt(identity["session"], identity["attempt_id"], review_only=True)
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
            if request["session"] != self.material.session_id:
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
            if not self.material.printer.lookup_object("gcode").get_mutex().test():
                raise ValueError("Recovery resolution requires command ownership")
            entered = True
            if request["action"] == "reconcile":
                result = self.material._reconcile_recovery_continuation(request["session"], request["attempt_id"], request["execution_hash"])
            else:
                result = self.material._abandon_recovery_attempt(request["session"], request["attempt_id"])
            self._recovery_resolution.update(state="complete", message="Recovery checkpoint reconciled" if request["action"] == "reconcile" else "Recovery abandoned")
            if result.get("archive_warning"):
                self._recovery_resolution["message"] += "; archive unavailable: " + result["archive_warning"]
            gcmd.respond_info(json.dumps(result, sort_keys=True))
        except Exception as error:
            if tracked is not None:
                self._recovery_resolution.update(state="unknown" if entered else "refused", message=str(error)[:512])
            raise gcmd.error(str(error))


    def _handle_recovery_stop(self, web_request):
        # Reactor intent only. Retire an exact reviewed ticket before execution,
        # or latch the existing active request; never acquire the G-code mutex.
        session, identity = web_request.get_str('session'), web_request.get_str('id')
        token = web_request.get_str('ticket', '')
        if (session != self.material.session_id
                or any(self.material.printer.lookup_object(name, None) is not None for name in ('openace', 'AFC'))):
            raise web_request.error('Recovery request or owner changed')
        runner = getattr(self.material, '_recovery_attempt', None)
        receipt = runner.record if runner is not None else None
        pending = getattr(self.material, '_recovery_pending_worker', None)
        preparing = runner is not None and (runner.busy or pending is not None and not pending['armed'])
        lifecycle = getattr(self.material, '_plr_lifecycle_component', None)
        scope = getattr(lifecycle, '_execution_scope', None)
        active = getattr(self, '_recovery_active_ticket', None)
        command_active = getattr(self, '_recovery_command_active', False)
        if (command_active and preparing and receipt is not None
                and receipt['state'] in ('pending', 'running', 'complete')):
            request = receipt['request']
            if (scope is None or not lifecycle._scope_owned(scope) or scope['record'] is not receipt
                    or request['session'] != session or request['id'] != identity
                    or token and (active is None or active['token'] != token)):
                raise web_request.error('Recovery request or owner changed')
            self._recovery_stop_request = copy.deepcopy(request)
        elif command_active:
            # The ticket was consumed but review has not created a runner yet.
            if (scope is not None or active is None or not token or active['token'] != token
                    or active['request']['session'] != session or active['request']['id'] != identity
                    or receipt is not None and receipt['request'] == active['request']):
                raise web_request.error('Recovery preparation is not running; use print controls after continuation')
            self._recovery_stop_request = copy.deepcopy(active['request'])
        else:
            tickets = getattr(self, '_recovery_tickets', None)
            state = tickets.get('continue') if tickets is not None and tickets['session'] == session else None
            issued = state['slots'].get('continue') if state is not None else None
            if (preparing or not token or issued is None or issued['sequence'] <= state['consumed']
                    or issued['request']['session'] != session or issued['request']['id'] != identity
                    or issued['ticket']['token'] != token):
                raise web_request.error('Recovery preparation is not running or its ticket changed')
            issued['cancel_requested'] = True
        web_request.send({'session': session, 'id': identity, 'state': 'requested'})

    @staticmethod
    def _cancelled_before_preparation(attempt):
        return {'request': copy.deepcopy(attempt), 'state': 'cancelled', 'before_execution': True,
                'message': 'Recovery cancelled before preparation; nothing moved or heated.'}

    def cmd_RECOVERY_CONTINUE(self, gcmd):
        if getattr(self, "_recovery_command_active", False):
            raise gcmd.error("Recovery command is already active")
        self._recovery_command_active = True
        self._recovery_stop_request = None
        self._recovery_active_ticket = None
        tracked = submission = None
        try:
            encoded = gcmd.get("REQUEST")
            request, attempt = self._decode_recovery_request(encoded)
            if attempt["session"] != self.material.session_id:
                raise ValueError("Recovery printer session changed")
            ticketed = self._consume_recovery_ticket("continue", request, gcmd)
            if not ticketed:
                seen = getattr(self, "_recovery_command_ids", set())
                runner = self.material._recovery_attempt
                if (attempt["id"] in seen
                        or runner.record is not None and runner.record["request"]["id"] == attempt["id"]):
                    raise ValueError("Recovery request was already attempted")
                if len(seen) >= 1024:
                    raise ValueError("Legacy recovery history is full; update the WM+ screen for bounded tickets or restart Klipper")
                seen.add(attempt["id"])
                self._recovery_command_ids = seen
            if ticketed:
                self._recovery_active_ticket = {"request": copy.deepcopy(attempt), "token": gcmd.get("TICKET")}
            tracked = attempt
            submission = {"request": copy.deepcopy(attempt), "state": "reviewing", "message": "Reviewing recovery"}
            self._recovery_submission = submission
            if self._recovery_stop_request == attempt:
                result = self._cancelled_before_preparation(attempt)
            else:
                result = self._consume_recovery_request(encoded,
                    lambda: self._recovery_stop_request is not None)
            if self._recovery_submission is submission:
                if result.get('before_execution') is True:
                    submission.update(state='cancelled', message=result['message'], before_execution=True)
                else:
                    submission.update(state="attempted", message="Read the recovery attempt for its outcome")
            # A scheduled worker is not proof of resumed printing.
            if result.get("archive_warning"):
                self._recovery_resolution["message"] += "; archive unavailable: " + result["archive_warning"]
            gcmd.respond_info(json.dumps(result, sort_keys=True))
        except Exception as error:
            if tracked is not None and self._recovery_submission is submission:
                record = self.material._recovery_attempt.record
                attempted = record is not None and record["request"]["id"] == tracked["id"]
                self._recovery_submission.update(state="attempted" if attempted else "refused",
                                                 message=str(error)[:512])
            raise gcmd.error(str(error))
        finally:
            if submission is None or self._recovery_submission is submission:
                self._recovery_command_active = False
                self._recovery_stop_request = None
                self._recovery_active_ticket = None


    def _consume_recovery_request(self, encoded, cancelled=lambda: False):
        """Single-owner handoff target for the explicit managed Continue command."""
        if not self.material.printer.lookup_object("gcode").get_mutex().test():
            raise ValueError("Recovery request requires command ownership")
        attempt, review = self._recovery_request_review(encoded)
        if cancelled():
            return self._cancelled_before_preparation(attempt)
        self.material._begin_explicit_physical_action("recovery continue")
        stages = self.material._recovery_initial_stages(review, cancelled, continue_print=True)
        return self.material._run_recovery_stages(attempt, review, stages, cancelled)


    def _recovery_execution_review(self, session, selected_file, execution_hash):
        if getattr(self.material, "_print_recovery_error", ""):
            raise ValueError("Recovery unavailable for this job: " + self.material._print_recovery_error)
        """Review an immutable completed-record selection before owned admission.

        This reader sends no commands and grants no permission to prepare. The
        eventual attempt must retain this exact selection and serialize execution.
        """
        try:
            if not isinstance(execution_hash, str) or not re.fullmatch(r"[0-9a-f]{16}", execution_hash):
                raise ValueError("Invalid selected execution fingerprint")
            before = self._recovery_machine_state(session)
            payload = self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)
            if self.material._recovery_fingerprint(payload) != execution_hash:
                raise ValueError("Selected execution checkpoint changed")
            execution = self.material._read_completed_recovery_execution(selected_file)
            after = self._recovery_machine_state(session)
            self._recovery_heater_state(self.material.printer.get_reactor().monotonic(),
                                        execution["heater_targets"].items())
            toolhead = self.material.printer.lookup_object("toolhead").get_status(self.material.printer.get_reactor().monotonic())
            minimum, maximum = toolhead.get("axis_minimum"), toolhead.get("axis_maximum")
            if (not isinstance(minimum, (list, tuple)) or not isinstance(maximum, (list, tuple))
                    or len(minimum) < 3 or len(maximum) < 3):
                raise ValueError("Recovery machine travel limits are unavailable")
            for axis in range(3):
                low, high = minimum[axis], maximum[axis]
                if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, high))
                        or low >= high or not low <= execution["machine_position"][axis] <= high):
                    raise ValueError("Recovery endpoint exceeds current machine travel limits")
            clearance = self.material._recovery_clearance_evidence(execution)
            # Endpoint bounds do not establish a clear route past the object or
            # validate a newly restored mesh transform; preparation must do both.
            missing_fans = []
            for name in execution["fans"]:
                if self.material.printer.lookup_object(name, None) is None:
                    if name == "fan":
                        raise ValueError("Required part-cooling fan is not installed: " + name)
                    missing_fans.append(name)
            if before != after:
                raise ValueError("Head attachment changed during recovery verification")
            if self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536) != payload:
                raise ValueError("Selected execution checkpoint changed during verification")
            if self.material._recovery_clearance_evidence(execution) != clearance:
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
            evidence = self.material._recovery_checkpoint_evidence(selected_file, checkpoint, checkpoint_hash, job_hash)
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
        record = self.material._read_recovery_job()
        if (set(record) != {"version", "state", "owner", "id", "session", "file",
                            "mapping", "required_tools", "heads", "context"}
                or record["state"] != "committed" or record["owner"] != "standalone"
                or self.material.printer.lookup_object("openace", None) is not None):
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
            self.material._validate_identity(saved["identity"])
            head = int(key[1:])
            if self.material.printer.lookup_object("extruder" if head == 0 else "extruder%d" % head, None) is None:
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
            now = self.material.printer.get_reactor().monotonic()
            variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            offsets = [variables.get("t%d_offset" % i) for i in range(4)]
            mesh = self.material.printer.lookup_object("bed_mesh").get_status(now)
            # The saved mesh need not already be active after restart.
            if (self.material._recovery_context(variables.get("wmp_print_context")) != self.material._recovery_context(context)
                    or context.get("offsets") != self.material._recovery_offsets(offsets)
                    or "wmp_print" not in mesh.get("profiles", {})):
                raise ValueError("Recovery context, calibration or saved mesh changed")
            if self.material.printer.lookup_object("openace", None) is not None:
                raise ValueError("Recovery owner changed")
            loaded = self.material._loaded_filament_status(now)
            for key, saved in heads.items():
                if (not self.material._loaded_source_matches(loaded.get(key, {}), saved)):
                    raise ValueError("Required recovery filament is not loaded with its saved identity")
            if any(self.material._material_operation_active(name)
                   for name in ("filament_operation", "toolhead_operation")):
                raise ValueError("Unfinished material or tool operation prevents recovery")

        current_evidence()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        identity = {key: file_info[key] for key in ("path", "size", "modified")}
        full, before = self.material._print_file(sd, identity)
        digest = hashlib.sha256()
        with open(full, "rb") as stream:
            def unchanged(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == before
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed before verification")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                reactor = self.material.printer.get_reactor()
                reactor.pause(reactor.monotonic() + 0.001)
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Recovery file changed during verification")
        if digest.hexdigest() != file_info["sha256"] or self.material._print_file(sd, identity) != (full, before):
            raise ValueError("Recovery file content changed")
        current_evidence()
        if self.material._read_recovery_job() != record:
            raise ValueError("Recovery job evidence changed during verification")
        return copy.deepcopy(record)


