# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery attempt lifecycle, interruption and cleanup."""
import copy
import hashlib
import json
import logging
import os
import tempfile

try:
    from . import wmp_recovery_retirement
    from .wmp_plr_records import RecoveryAttempt
except ImportError:
    import wmp_recovery_retirement
    from wmp_plr_records import RecoveryAttempt

class RecoveryLifecycle:
    def __init__(self, material):
        self.material = material
        self._execution_scope = None

    @staticmethod
    def _current_actor():
        from greenlet import getcurrent
        return getcurrent()

    def _scope_owned(self, scope):
        record = scope['record']
        pending = getattr(self.material, '_recovery_pending_worker', None)
        return (self._execution_scope is scope
                and getattr(self.material, '_plr_lifecycle_component', None) is self
                and self.material.session_id == scope['request']['session']
                and getattr(self.material, '_command_generation', 0) == scope['generation']
                and self._recovery_attempt is scope['runner']
                and (record is None or scope['runner'].record is record
                     and record.get('request') == scope['request'])
                and (pending is None or pending.get('session') == scope['request']['session']
                     and pending.get('request') == scope['request'])
                and getattr(self.material, '_plr_review_component', None) is scope['review_owner']
                and getattr(scope['review_owner'], '_recovery_submission', None) is scope['submission']
                and getattr(scope['review_owner'], '_recovery_stop_request', None) in (None, scope['request'])
                and all(self.material.printer.lookup_object(name, None) is owner
                        for name, owner in scope['owners']))

    def _require_scope(self, scope):
        if not self._scope_owned(scope):
            raise ValueError('Recovery preparation ownership changed')

    def run_boundary_stage(self, guard, execute):
        scope = self._execution_scope
        if scope is None:
            return execute()  # Private stage-only validation keeps its semantics.
        if scope['actor'] is not self._current_actor():
            raise ValueError('Recovery stage command owner changed')
        self._require_scope(scope)
        previous, scope['guard'] = scope['guard'], guard
        try:
            return execute()
        finally:
            if self._execution_scope is scope and scope['guard'] is guard:
                scope['guard'] = previous

    def check_operation_boundary(self, label):
        scope = self._execution_scope
        if scope is None or scope['actor'] is not self._current_actor():
            return
        self._require_scope(scope)
        if scope['cleanup']:
            return
        printer = self.material.printer
        now = printer.get_reactor().monotonic()
        saved = printer.lookup_object('save_variables').get_status(now)['variables']
        if (printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False)
                or printer.lookup_object('webhooks').get_status(now).get('state') != 'ready'
                or any(type(saved.get(key)) is not int or saved[key] != 0
                       for key in ('fail_flag', 'is_nozzle_setting'))):
            raise ValueError('Recovery interrupted by a printer fault')
        stopping = scope['cancelled']()
        self._require_scope(scope)
        if stopping:
            if scope['guard'] is not None:
                scope['guard']()  # Full stage/frame evidence before acknowledging Stop.
            self._require_scope(scope)
            scope['cancel_phase'] = label[:160]
            raise ValueError('Recovery preparation stopped ' + label[:160])

    def _recovery_attempt_path(self):
        return os.path.join(os.path.dirname(self.material.profile_path), "wmp_recovery_attempt.json")


    def _restore_recovery_attempt(self):
        path = self._recovery_attempt_path()
        self._recovery_restore_error = ''
        self.material._recovery_retirement_result = {}
        try:
            store = self.material._recovery_retirement_store()
            retired = store.retirement()
            if retired is not None:
                self.material._recovery_retirement_result = dict(retired, state='complete' if retired['matches'] else 'superseded')
                if not retired['matches']:
                    retired = store.retirement(attempt_only=True)
            if retired is not None and retired['matches']:
                self._recovery_attempt = RecoveryAttempt(lambda value: self.material._write_recovery_json(path, value))
                return
            original = self.material._recovery_read_bytes(path, 65536)
            record = json.loads(original)
            if not isinstance(record, dict):
                raise ValueError('Invalid recovery attempt journal')
        except FileNotFoundError:
            original, record = None, None
        except (ValueError, OSError) as error:
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self.material._write_recovery_json(path, value))
            return
        try:
            # Invalid evidence stays untouched for diagnostics. It neither
            # establishes active work nor prevents Klipper startup.
            RecoveryAttempt(lambda value: None, record)
        except (ValueError, TypeError, KeyError) as error:
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self.material._write_recovery_json(path, value))
            return
        restoring = True
        def persist(value):
            if restoring and original is not None:
                # RecoveryAttempt records interrupted work as unknown on load.
                # Preserve exact pre-restart evidence before that first rewrite.
                self._preserve_recovery_attempt_original(original)
                if self.material._recovery_read_bytes(path, 65536) != original:
                    raise ValueError("Recovery attempt changed during startup review")
            self.material._write_recovery_json(path, value)
        try:
            self._recovery_attempt = RecoveryAttempt(persist, record)
        except (ValueError, OSError) as error:
            # Keep the diagnostic failure visible without a machine hold.
            # No archived operation is replayed by startup.
            self._recovery_restore_error = 'Saved recovery requires review: ' + str(error)[:512]
            self._recovery_attempt = RecoveryAttempt(lambda value: self.material._write_recovery_json(path, value))
        restoring = False


    def _preserve_recovery_attempt_original(self, payload):
        """Keep immutable bytes before startup marks an attempt interrupted."""
        digest = hashlib.sha256(payload).hexdigest()
        parent = os.path.dirname(self.material.profile_path)
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
                if self.material._recovery_read_bytes(path, 65536) != payload:
                    raise ValueError("Original recovery attempt archive conflicts with saved evidence")
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self.material._recovery_read_bytes(path, 65536) != payload:
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
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return self._recovery_attempt_unresolved()
        runner = getattr(self, "_recovery_attempt", None)
        return bool((runner is not None and runner.busy)
                    or getattr(self.material, "_recovery_pending_worker", None) is not None)


    def _require_no_recovery_attempt(self):
        if self.material._print_cancel_active():
            raise ValueError("Print cancellation is running; wait for it to stop")
        if self._recovery_attempt_active():
            raise ValueError("Power-loss recovery is running; stop it before another operation")


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
                or session != self.material.session_id or receipt["request"]["session"] == session):
            raise ValueError("No matching restart-interrupted continuation to reconcile")
        expected_receipt = copy.deepcopy(receipt)
        journal_bytes = self.material._recovery_read_bytes(self._recovery_attempt_path(), 65536)
        if json.loads(journal_bytes) != expected_receipt:
            raise ValueError("Recovery continuation journal changed")
        def guard():
            now = self.material.printer.get_reactor().monotonic()
            sd = self.material.printer.lookup_object("virtual_sdcard")
            saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            if (runner.record is not receipt or runner.record != expected_receipt
                    or self.material._recovery_read_bytes(self._recovery_attempt_path(), 65536) != journal_bytes
                    or self.material.session_id != session
                    or self.material.printer.lookup_object("gcode").get_mutex().test() != (not review_only)
                    or self.material.printer.is_shutdown()
                    or self.material.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None
                    or sd.is_active() or sd.is_cmd_from_sd()
                    or self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False
                    or self.material.printer.lookup_object("print_stats").get_status(now).get("state") not in ("standby", "complete", "cancelled")
                    or any(saved.get(key) != 0 for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Recovery reconciliation ownership or idle state changed")
        guard()
        payload = self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)
        if (self.material._recovery_fingerprint(payload) != execution_hash
                or execution_hash == receipt["request"]["execution_hash"]):
            raise ValueError("A new completed execution checkpoint is required")
        execution = self.material._read_completed_recovery_execution(receipt["request"]["file"])
        if (execution["session"] != receipt["request"]["session"]
                or execution["job_fingerprint"] != receipt["checkpoint"]["job_fingerprint"]
                or execution["file_position"] < receipt["checkpoint"]["file_position"]):
            raise ValueError("Completed checkpoint does not supersede this continuation")
        guard()
        if self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536) != payload:
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


    def _abandon_recovery_attempt(self, session, request_id, review_only=False):
        """Explicit no-motion abandonment; caller owns the G-code mutex."""
        runner = self._recovery_attempt
        receipt = runner.record
        if (self._recovery_attempt_active() or self.material._print_cancel_active() or receipt is None or receipt["state"] not in ("unknown", "stopped")
                or receipt["request"]["id"] != request_id or session != self.material.session_id):
            raise ValueError("Recovery abandonment request is stale or not stopped")
        gcode = self.material.printer.lookup_object("gcode")
        reactor = self.material.printer.get_reactor()
        job_expected = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        job = json.loads(job_expected)
        already_invalidated = (job.get("state") == "invalidated" and job.get("reason") == "recovery-abandoned"
                               and job.get("id") == request_id)
        archive = None
        archive_warning = ""
        archive_evidence = None
        if already_invalidated and "archive" in job:
            archive = job["archive"]
            try:
                archive_evidence = self.material._read_archived_recovery_evidence(archive)
            except (OSError, ValueError) as error:
                # The current marker still binds this exact stopped attempt.
                # Missing diagnostic bytes cannot veto its explicit dismissal.
                archive_warning = str(error)[:512]
                logging.warning("Recovery discard original archive unavailable: %s", archive_warning)
                archive = None
                payload = self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)
                if self.material._recovery_fingerprint(payload) != receipt["request"]["execution_hash"]:
                    raise ValueError("Another job owns the recovery execution")
            else:
                if not self.material._recovery_archive_matches_attempt(archive_evidence, receipt):
                    raise ValueError("Another job owns the original recovery archive")
        else:
            payload = self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536)
            if not self.material._recovery_archive_matches_attempt({"job": job_expected, "execution": payload}, receipt):
                raise ValueError("Another job owns the recovery evidence")
        def status(name):
            return self.material.printer.lookup_object(name).get_status(reactor.monotonic())
        def stopped():
            nonlocal archive_warning
            if (runner.record is not receipt or self.material.session_id != session or (not review_only and not gcode.get_mutex().test())
                    or self.material.printer.lookup_object("openace", None) is not None or self.material.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Recovery abandonment ownership is unavailable")
            if self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536) != job_expected:
                raise ValueError("Recovery job changed during abandonment")
            if archive is not None and archive_evidence is not None and not archive_warning:
                try:
                    if self.material._read_archived_recovery_evidence(archive) != archive_evidence:
                        raise ValueError("Recovery diagnostic archive changed")
                except (OSError, ValueError) as error:
                    archive_warning = str(error)[:512]
                    logging.warning("Recovery discard archive unavailable: %s", archive_warning)
            sd = self.material.printer.lookup_object("virtual_sdcard")
            if not review_only and (sd.is_active() or sd.is_cmd_from_sd() or status("pause_resume").get("is_paused") is not False
                    or status("print_stats").get("state") not in ("standby", "complete", "cancelled", "error")):
                raise ValueError("A print or pause is still active")
            stream = getattr(sd, "current_file", None)
            if not review_only and stream is not None and os.path.realpath(stream.name) != os.path.realpath(
                    os.path.join(sd.sdcard_dirname, receipt["request"]["file"])):
                raise ValueError("Another file is selected; recovery abandonment did not close it")
            return {"state": "unknown", "head": ""}
        attachment = stopped()
        offer_path, offer_before, offer_after = self.material._recovery_offer(receipt["request"]["file"])
        if review_only:
            return copy.deepcopy(runner.record)
        runner.busy = True
        try:
            # Preserve the original bytes before retiring continuation authority.
            # A retry after partial cleanup retains the original archive reference.
            if archive is None:
                if self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536) != payload:
                    raise ValueError("Recovery execution changed before archival")
                archive_evidence = {"job": job_expected, "execution": payload}
                if offer_before is not None and offer_before != offer_after:
                    archive_evidence["offer"] = offer_before
                try:
                    archive = self.material._archive_recovery_evidence(archive_evidence)
                except (OSError, wmp_recovery_retirement.ArchiveUnavailable) as error:
                    archive_warning = str(error)[:512]
                    logging.warning("Recovery discard archive unavailable: %s", archive_warning)
                if stopped() != attachment or self.material._recovery_read_bytes(self.material._recovery_execution_path(), 65536) != payload:
                    raise ValueError("Recovery evidence changed during archival")
            elif offer_before is not None and offer_before != offer_after and "offer" not in archive_evidence:
                # Upgrade a retry of an older abandonment without losing its
                # original job/execution bytes or mutating the old archive.
                upgraded = dict(archive_evidence, offer=offer_before)
                try:
                    archive = self.material._archive_recovery_evidence(upgraded)
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
            self.material._write_recovery_job(invalidated)
            job_expected = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
            if json.loads(job_expected) != invalidated:
                raise ValueError("Recovery abandonment evidence changed")
            for script in ("SDCARD_RESET_FILE", "SET_GCODE_VARIABLE MACRO=_WMP_RECOVERY_BEGIN VARIABLE=active VALUE=False",
                           "SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False",
                           'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="{}"'):
                if stopped() != attachment:
                    raise ValueError("Recovery dismissal context changed")
                gcode.run_script_from_command(script)
            if (stopped() != attachment or self.material.printer.lookup_object("virtual_sdcard").current_file is not None
                    or status("gcode_macro _WMP_RECOVERY_BEGIN").get("active") is not False
                    or status("gcode_macro START_PRINT").get("print_body_ready") is not False
                    or status("save_variables")["variables"].get("wmp_print_context") != {}):
                raise ValueError("Recovery abandonment was not confirmed")
            self.material._clear_recovery_offer(offer_path, offer_before, offer_after, stopped)
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


    def _stop_recovery_heaters(self, review, owner=None):
        """Best-effort heater-only cleanup; never moves or resolves the attempt."""
        names = sorted(review["execution"]["heater_targets"])
        allowed = {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
        if set(names) - allowed:
            raise ValueError("Invalid recovery cleanup heater")
        gcode = self.material.printer.lookup_object("gcode")
        result = {"state": "complete", "heaters": {}, "error": ""}
        errors = []
        for name in names:
            try:
                if (owner is not None and owner() is not True
                        or self.material.session_id != review["machine"]["session"] or not gcode.get_mutex().test()
                        or self.material.printer.is_shutdown() or self.material.printer.lookup_object("openace", None) is not None
                        or self.material.printer.lookup_object("AFC", None) is not None):
                    raise ValueError("Recovery cleanup command ownership is unavailable")
                gcode.run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % name)
                if owner is not None and owner() is not True:
                    raise ValueError("Recovery cleanup owner changed after heater command")
                target = self.material.printer.lookup_object(name).get_status(self.material.printer.get_reactor().monotonic()).get("target")
                if owner is not None and owner() is not True:
                    raise ValueError("Recovery cleanup owner changed during readback")
                if type(target) not in (int, float) or target != 0:
                    raise ValueError("Heater-off target was not confirmed")
                result["heaters"][name] = True
            except Exception as error:
                result["heaters"][name] = False
                errors.append(name + ": " + str(error))
        if errors:
            result.update(state="unknown", error="; ".join(errors))
        if owner is None or owner() is True:
            self._recovery_temperatures = {}
        return result


    def _run_recovery_stages(self, request, review, stages, cancelled=lambda: False):
        if self._execution_scope is not None:
            raise ValueError('Recovery preparation is already executing')
        printer = self.material.printer
        if printer.lookup_object('wm_material', None) is not self.material:
            raise ValueError('Recovery material owner changed')
        scope = {'actor': self._current_actor(), 'request': copy.deepcopy(request),
                 'runner': self._recovery_attempt, 'record': None,
                 'generation': getattr(self.material, '_command_generation', 0),
                 'review_owner': getattr(self.material, '_plr_review_component', None),
                 'submission': getattr(getattr(self.material, '_plr_review_component', None), '_recovery_submission', None),
                 'owners': tuple((name, printer.lookup_object(name, None)) for name in
                                 ('wm_material', 'gcode', 'virtual_sdcard', 'wmp_recovery', 'openace', 'AFC')),
                 'guard': None, 'cancelled': cancelled, 'cancel_phase': '', 'cleanup': False}
        self._execution_scope = scope
        try:
            return self._run_owned_stages(request, review, stages, cancelled, scope)
        finally:
            if self._execution_scope is scope:
                self._execution_scope = None

    def _run_owned_stages(self, request, review, stages, cancelled, scope):
        """Run an admitted chain under the caller's command mutex, with cleanup."""
        review = copy.deepcopy(review)
        RecoveryAttempt._validate_request(request)
        if (request["session"] != review["machine"]["session"]
                or request["execution_hash"] != review["execution_hash"]
                or request["file"] != review["execution"]["file"]["path"]):
            raise ValueError("Recovery request differs from its admitted evidence")
        runner = self._recovery_attempt
        previous = runner.record
        def owned():
            return self._scope_owned(scope)
        def started(record):
            self._require_scope(scope)
            if record is not runner.record or record['request'] != scope['request']:
                raise ValueError('Recovery attempt request changed before dispatch')
            scope['record'] = record
        def cleanup():
            self._require_scope(scope)
            scope['cleanup'] = True
            if runner.record is previous or runner.record is None or runner.record["state"] == "complete":
                return
            if runner.record.get("continuation", {}).get("state") == "scheduled":
                runner.record["continuation"].update(state="unknown", error=runner.record["error"])
                runner.record["state"] = "unknown"
            disarm_error = ""
            try:
                self._require_scope(scope)
                self.material._recovery_disarm_worker()
                self._require_scope(scope)
            except Exception as error:
                disarm_error = str(error)
            self._require_scope(scope)
            accounting_error = ""
            if any(stage["name"] == "accounting" and stage["state"] != "pending"
                   for stage in runner.record["stages"]):
                try:
                    sd = self.material.printer.lookup_object("virtual_sdcard")
                    stats = self.material.printer.lookup_object("print_stats")
                    gcode = self.material.printer.lookup_object("gcode")
                    execution = review["execution"]
                    identity = {key: execution["file"][key] for key in ("path", "size", "modified")}
                    if (self.material.session_id != request["session"] or not gcode.get_mutex().test()
                            or self.material.printer.lookup_object("openace", None) is not None
                            or self.material.printer.lookup_object("AFC", None) is not None
                            or sd.is_active() or sd.is_cmd_from_sd()
                            or stats.filename != execution["file"]["path"]
                            or sd.file_position != execution["file_position"]
                            or self.material._recovery_active_file(sd, identity) != self.material._print_file(sd, identity)):
                        raise ValueError("Recovery accounting cleanup lost ownership")
                    self._require_scope(scope)
                    if stats.state == "printing":
                        stats.note_cancel()
                    self._require_scope(scope)
                    if stats.state not in ("standby", "cancelled"):
                        raise ValueError("Recovery accounting stop was not confirmed")
                except Exception as error:
                    accounting_error = str(error)
            self._require_scope(scope)
            touched = any(stage["name"] == "heater_targets" and stage["state"] != "pending"
                          for stage in runner.record["stages"])
            result = self._stop_recovery_heaters(review, owner=owned) if touched else {"state": "complete", "heaters": {}, "error": ""}
            self._require_scope(scope)
            transient_error = ""
            if scope['cancel_phase']:
                try:
                    try:
                        from .wmp_stop_points import finish_cancelled_toolchange
                    except ImportError:
                        from wmp_stop_points import finish_cancelled_toolchange
                    transient = finish_cancelled_toolchange(self.material.printer, owned)
                    if transient != 'not_needed':
                        result['toolchange'] = transient
                except Exception as error:
                    result['toolchange'] = 'unconfirmed'
                    transient_error = str(error)
            self._require_scope(scope)
            if disarm_error or accounting_error or transient_error:
                result.update(state="unknown", error="; ".join(filter(None,
                    (result.get("error", ""), disarm_error, accounting_error, transient_error))))
            if result["state"] != "complete":
                runner.record["state"] = "unknown"
            try:
                runner._save(cleanup=result)
                self._require_scope(scope)
            except Exception:
                if owned():
                    runner.record["state"] = "unknown"
                raise
        try:
            runner.run(request, stages, cancelled, owner=owned, started=started)
            self._require_scope(scope)
            if runner.record["state"] == "complete":
                try:
                    if getattr(self.material, "_recovery_pending_worker", None) is not None and cancelled():
                        raise ValueError("Recovery stopped before worker activation")
                    self._require_scope(scope)
                    self.material._recovery_activate_worker(request)
                    self._require_scope(scope)
                except Exception as error:
                    if owned():
                        runner.record.update(state="unknown", error=str(error))
                    raise
        except Exception:
            try:
                cleanup()
            except Exception:
                pass  # Preserve the original failure; retained outcome is unknown.
            raise
        self._require_scope(scope)
        if runner.record["state"] != "complete":
            cleanup()
        return copy.deepcopy(runner.record)


