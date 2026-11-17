# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone filament load/unload execution, cancellation and result records."""
import json
import logging
import os
import re
import uuid

try:
    from .wmp_persistence import atomic_write
    from .wmp_filament_types import FilamentCancelled
except ImportError:
    from wmp_persistence import atomic_write
    from wmp_filament_types import FilamentCancelled

try:
    from .wmp_filament_planning import service_progress_steps
except ImportError:
    from wmp_filament_planning import service_progress_steps


class FilamentService:
    def __init__(self, material):
        self.material = material

    def _filament_operation_path(self):
        return os.path.join(os.path.dirname(self.material.profile_path), "wmp_filament_operation.json")


    def _persist_filament_operation(self):
        # openACE owns its own recovery. Never overwrite a standalone journal
        # with an operation whose outcome is managed by another component.
        if self.material.printer.lookup_object("openace", None) is not None:
            return
        operation = self.filament_operation
        if not operation.get("id"):
            return
        path = self._filament_operation_path()
        payload = json.dumps({"version": 1, "operation": operation}, sort_keys=True)
        if payload == getattr(self, "_filament_journal_payload", None):
            return
        atomic_write(path, payload, ".wmp-operation-")
        self._filament_journal_payload = payload


    def _record_filament_result(self):
        # This journal describes an attempt. In-memory request IDs, generation
        # retirement and current worker ownership—not durable ACKs—prevent replay.
        try:
            self._persist_filament_operation()
        except Exception as error:
            message = str(error)[:512]
            if self.filament_operation.get("persistence_error") != message:
                logging.exception("Unable to persist filament result")
            self.filament_operation["persistence_error"] = message


    def _restore_filament_operation(self):
        path = self._filament_operation_path()
        try:
            with open(path) as stream:
                payload = stream.read(131073)
        except FileNotFoundError:
            return
        except (OSError, UnicodeError) as error:
            self.filament_operation = {"state": "unknown", "message": "Saved filament result is unreadable: " + str(error)[:512]}
            return
        try:
            if len(payload) > 131072:
                raise ValueError("journal too large")
            record = json.loads(payload)
            operation = record["operation"]
            if (record.get("version") != 1 or not isinstance(operation, dict)
                    or not isinstance(operation.get("id"), str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", operation["id"])
                    or operation.get("head") not in ("h0", "h1", "h2", "h3")
                    or operation.get("action") not in ("load", "unload")
                    or operation.get("state") not in ("running", "unknown", "complete", "failed", "refused")):
                raise ValueError("invalid operation")
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.filament_operation = {"state": "unknown", "message": "Saved filament result is invalid: " + str(error)[:512]}
            return
        operation["previous_session"] = operation.get("previous_session", operation.get("session", ""))
        operation["session"] = self.material.session_id
        if operation.get("state") in ("running", "unknown"):
            operation.update(state="unknown", message="Filament operation interrupted by restart; verify stopped state before continuing")
            # The old pause cannot authorize motion or resume in a new process.
            if "pause_origin" in operation:
                operation["interrupted_pause_origin"] = operation.pop("pause_origin")
        self.filament_operation = operation
        self._filament_requests.add(operation["id"])


    def cmd_FILAMENT_SERVICE(self, gcmd):
        # Console/legacy entry point: retain the same admission, operation
        # receipt, cancellation and completion implementation as the screen.
        # T is intentionally unsupported: vendor service macros mixed physical
        # ACTIVATE_EXTRUDER selection with logical M109 addressing.
        if set(gcmd.get_command_parameters()) - {"HEAD", "ACTION", "ID"}:
            raise gcmd.error("Use ACTION=load|unload HEAD=0..3 and optional ID; HEAD is physical, not a mapped T tool")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        if action not in ("load", "unload"):
            raise gcmd.error("ACTION must be load or unload")
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if sd is None or sd.is_cmd_from_sd():
            raise gcmd.error("Use Filaments for managed service; this asynchronous command cannot run from print G-code")
        request_id = gcmd.get("ID", "service-" + uuid.uuid4().hex)
        try:
            now = self.material.printer.get_reactor().monotonic()
            if action == "load" and self.material.printer.lookup_object("openace", None) is not None:
                plans = [p for p in self.material._openace_load_plans(head, now)
                         if p.get("direct") and p.get("source") == "external:h%d" % head]
                if len(plans) != 1:
                    raise ValueError("Select an ACE slot in Filaments to load this head")
                plan = plans[0]
            else:
                plan = self.material._filament_plan(head, action, now)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            raise gcmd.error(str(error))
        arguments = {"HEAD": str(head), "ACTION": action, "ID": request_id,
                     "TOKEN": plan["token"]}
        if (gcmd.get("ID", None) is None
                and self.material.printer.lookup_object("openace", None) is None
                and self.material.printer.lookup_object("AFC", None) is None):
            sequence = getattr(self.material, "_filament_request_sequence", 0) + 1
            request_id = "filament_" + str(sequence)
            arguments.update(ID=request_id, SESSION=self.material.session_id, SEQUENCE=str(sequence))
        command = self.material.printer.lookup_object("gcode").create_gcode_command(
            "WMP_FILAMENT_SEQUENCE", "WMP_FILAMENT_SEQUENCE", arguments)
        self.cmd_FILAMENT_SEQUENCE(command)
        gcmd.respond_info("Filament operation %s: %s" %
                          (request_id, self.filament_operation.get("state", "unknown")))


    def cmd_FILAMENT_SEQUENCE(self, gcmd):
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid filament request ID")
        sequenced = self.material._admit_material_sequence(gcmd, "filament", request_id)
        if self.material._material_operation_active("toolhead_operation"):
            raise gcmd.error("Toolhead operation is unresolved: state=" + str(getattr(self.material, "toolhead_operation", {}).get("state"))[:80])
        if self.filament_operation.get("state") == "running":
            raise gcmd.error("A filament operation is already running: filament_operation.state=running")
        if not sequenced and request_id in self._filament_requests:
            raise gcmd.error("Filament request already attempted; inspect its result")
        if self.filament_operation.get("state") == "unknown" and (
                self.material.printer.lookup_object("openace", None) is not None
                and getattr(self.material, "_openace_filament_recovery", None) is not None):
            raise gcmd.error("Previous filament operation is unresolved")
        if not sequenced and len(self._filament_requests) >= 1024:
            raise gcmd.error("Legacy filament request limit reached; use the current touchscreen or WMP_FILAMENT_SERVICE without ID")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        action = gcmd.get("ACTION")
        try:
            now = self.material.printer.get_reactor().monotonic()
            if action == "load" and self.material.printer.lookup_object("openace", None) is not None:
                plans = self.material._openace_load_plans(head, now)
                plan = next((p for p in plans if p["token"] == gcmd.get("TOKEN")), None)
                if plan is None:
                    raise ValueError("Selected ACE Load procedure changed; review it again")
            else:
                plan = self.material._filament_plan(head, action, now)
            if gcmd.get("TOKEN") != plan["token"]:
                raise ValueError("Filament procedure changed; review it again")
            self.material._begin_explicit_physical_action("filament " + action)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            if not sequenced:
                self._filament_requests.add(request_id)
            self.filament_operation = {"id": request_id, "session": self.material.session_id,
                "head": "h%d" % head, "action": action, "state": "refused",
                "message": str(error)}
            raise gcmd.error(str(error))
        if not sequenced:
            self._filament_requests.add(request_id)
        self.material._filament_checks.pop(plan["head"], None)
        self.filament_operation = {"id": request_id, "session": self.material.session_id,
            "head": plan["head"], "action": action, "state": "running",
            "command_generation": plan["command_generation"]}
        if plan.get("pause_origin"):
            self.filament_operation["pause_origin"] = plan["pause_origin"]
        self._record_filament_result()
        if "service" in plan or plan.get("owner") == "openace":
            # Return the command receipt before long waits, so the screen's
            # status worker keeps polling live preparation/insertion progress.
            scheduling_failed = False
            def execute(now):
                if scheduling_failed:
                    return
                dispatched = False
                try:
                    with self.material.printer.lookup_object("gcode").get_mutex():
                        now = self.material.printer.get_reactor().monotonic()
                        if not self.material._filament_context_valid(plan, now):
                            raise ValueError("Printer became busy before loading: " + getattr(self.material, "_filament_context_refusal", "context admission was not confirmed"))
                        if plan.get("owner") == "openace" and action == "load":
                            current = next((p for p in self.material._openace_load_plans(head, now) if p["token"] == plan["token"]), None)
                        else:
                            current = self.material._filament_plan(head, action, now)
                        if current != plan:
                            raise ValueError("Filament service context changed")
                        dispatched = True
                        self._execute_filament(gcmd, head, action, plan)
                except Exception as error:
                    if self.filament_operation.get("state") == "running":
                        self.filament_operation.update(state="failed" if dispatched else "refused", message=str(error))
                        self._record_filament_result()
            try:
                self.material.printer.get_reactor().register_callback(execute)
            except Exception as error:
                # A callback can be enqueued before registration raises. It
                # must never execute after we have reported that nothing ran.
                scheduling_failed = True
                self.filament_operation.update(state="refused", message=str(error))
                self._record_filament_result()
                raise
            return
        self._execute_filament(gcmd, head, action, plan)


    def _handle_filament_cancel(self, web_request):
        # Webhooks run on the reactor without waiting for the G-code mutex.
        # Only record intent here; the running procedure owns hardware cleanup.
        operation = self.filament_operation
        if (web_request.get_str("session") != self.material.session_id or
                operation.get("session") != self.material.session_id or
                web_request.get_str("id") != operation.get("id") or
                web_request.get_str("head") != operation.get("head")):
            raise web_request.error("Filament operation changed")
        if operation.get("state") != "running":
            raise web_request.error("Filament operation is not running")
        owner = self.material.printer.lookup_object("openace", None)
        binding = getattr(self.material, "_openace_filament_cancel", None)
        if owner is not None or binding is not None:
            if (binding is None or owner is not binding["owner"]
                    or operation is not binding["operation"]):
                raise web_request.error("openACE filament owner changed")
            plan = binding["plan"]
            now = self.material.printer.get_reactor().monotonic()
            ace = owner.get_status(now)
            if (not self.material._filament_context_valid(plan, now)
                    or ace.get("session_id") != plan["ace_session"]
                    or ace.get("operation") not in (None, binding["owner_operation"])
                    or "job" not in ace or ace["job"] is not None and
                    (not isinstance(ace["job"], dict) or ace["job"].get("active") is not False)):
                raise web_request.error("openACE filament operation changed")
            operation.update(cancel_requested=True, message="Requesting openACE stop")
            # Between commands WM+ owns the insertion wait. During a command,
            # ask the owner to abort on the reactor, never queue behind G-code.
            # Intent must stay latched even if dispatch fails, but a failed
            # dispatch must not suppress a later STOP retry. The binding is
            # revalidated above on every request before touching the owner.
            if binding["active"] and not binding.get("abort_dispatched", False):
                owner.abort_operation("WM+ filament STOP " + operation["id"])
                binding["abort_dispatched"] = True
        operation.update(cancel_requested=True, message="Cancellation requested; waiting for the current phase to stop")
        web_request.send({"id": operation["id"], "session": self.material.session_id,
                          "state": "requested"})


    def cmd_RECOVER_FILAMENT(self, gcmd):
        operation = self.filament_operation
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        if (gcmd.get("SESSION") != self.material.session_id or operation.get("session") != self.material.session_id
                or gcmd.get("ID") != operation.get("id") or operation.get("head") != "h%d" % head):
            reason = ("SESSION differs from printer session" if gcmd.get("SESSION") != self.material.session_id else
                      "operation session differs from printer session" if operation.get("session") != self.material.session_id else
                      "ID differs from operation" if gcmd.get("ID") != operation.get("id") else
                      "HEAD differs from operation; requested=h%d, recorded=%s" % (head, str(operation.get("head"))[:80]))
            raise gcmd.error("Filament operation changed; reopen recovery: " + reason)
        if operation.get("state") != "unknown":
            raise gcmd.error("Filament operation does not need reconciliation: state=" + str(operation.get("state"))[:80])
        binding = getattr(self.material, "_openace_filament_recovery", None)
        if binding is not None:
            if (operation is not binding["operation"]
                    or self.material.printer.lookup_object("openace", None) is not binding["owner"]
                    or gcmd.get_int("GENERATION", minval=0, maxval=9223372036854775807)
                    != getattr(self.material, "_command_generation", 0)):
                raise gcmd.error("openACE recovery context changed")
            try:
                self.material._finish_openace_filament_stop(binding["plan"], head)
            except Exception as error:
                operation.update(state="unknown", message="Stop not confirmed: " + str(error))
                raise gcmd.error(operation["message"])
            self.material._openace_filament_recovery = None
            operation.pop("openace_recovery_supported", None)
            gcmd.respond_info(operation["message"])
            return
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another filament manager owns this printer")
        # Explicit cleanup is a new admission, not a replay of retired feed work.
        recovery_context = dict(operation, command_generation=getattr(self.material, "_command_generation", 0))
        if not self.material._filament_context_valid(recovery_context, self.material.printer.get_reactor().monotonic()):
            raise gcmd.error("Filament recovery requires an idle printer: " + getattr(self.material, "_filament_context_refusal", "context admission was not confirmed"))
        if self.material._material_operation_active("toolhead_operation"):
            raise gcmd.error("Resolve the toolhead operation first")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.material.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is unavailable")
        run = self.material.printer.lookup_object("gcode").run_script_from_command
        operation.update(phase="draining", steps=[
            {"phase": "draining", "label": "Wait for motion to stop"},
            {"phase": "cooling", "label": "Turn heater off"},
            {"phase": "verifying", "label": "Verify filament and attachment sensors"}])
        errors = []
        failed_phase = None
        # No feed, tool-change, homing or retry of the original sequence. Even
        # if draining fails, still attempt to stop this operation's heater.
        try:
            run("M400")
        except Exception as error:
            errors.append("motion stop: " + str(error))
            failed_phase = "draining"
        operation["phase"] = "cooling"
        try:
            run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
            now = self.material.printer.get_reactor().monotonic()
            if self.material.printer.lookup_object(heater).get_status(now).get("target") != 0:
                raise ValueError("heater target is not zero")
        except Exception as error:
            errors.append("heater off: " + str(error))
            failed_phase = failed_phase or "cooling"
        operation["phase"] = "verifying"
        try:
            now = self.material.printer.get_reactor().monotonic()
            if not self.material._filament_context_valid(recovery_context, now):
                raise ValueError("printer became busy: " + getattr(self.material, "_filament_context_refusal", "context admission was not confirmed"))
            attachment = self.material._attachment(now)
            if attachment.get("state") not in ("attached", "empty"):
                raise ValueError("head attachment sensors disagree")
            presence = self.material._sensor_filament_status(now)[operation["head"]]["state"]
            if presence not in ("loaded", "empty"):
                raise ValueError("filament sensor is unavailable")
        except Exception as error:
            errors.append("sensor verification: " + str(error))
            failed_phase = failed_phase or "verifying"
        if errors:
            # Later safety cleanup is still attempted, but must not make an
            # earlier failed stage appear completed in the progress display.
            operation.update(phase=failed_phase, message="Recovery not confirmed: " + "; ".join(errors))
            self._record_filament_result()
            raise gcmd.error(operation["message"])
        confirmed = self.material._loaded_filament_status(now).get(operation["head"], {}).get("state") == "loaded"
        operation.update(state="failed", recovered=True, phase="stopped",
                         recovery_presence=presence, recovery_attachment=attachment,
                         message=("Stopped. Filament remains loaded." if confirmed else
                                  "Stopped. Filament is present; complete Load before printing." if presence == "loaded" else
                                  "Stopped. Head is empty."))
        self._record_filament_result()
        gcmd.respond_info(operation["message"])


    def _filament_checkpoint(self, phase):
        self.filament_operation["phase"] = phase
        self._record_filament_result()
        if self.filament_operation.get("cancel_requested"):
            raise FilamentCancelled("Filament operation cancelled")
        if self.filament_operation.get("pause_origin") and not self.material._filament_context_valid(
                self.filament_operation, self.material.printer.get_reactor().monotonic()):
            raise ValueError("Paused print context changed during filament service: " + getattr(self.material, "_filament_context_refusal", "context admission was not confirmed"))


    def _execute_filament(self, gcmd, head, action, plan):
        try:
            if plan.get("pause_origin"):
                self.material._pause_origin.update(serviced=True, ready=False)
                if self.material._pause_origin.get("kind") == "toolchange":
                    self.material._pause_origin["fault"]["service_required"].add(plan["head"])
            return self._execute_filament_impl(gcmd, head, action, plan)
        finally:
            binding = getattr(self.material, "_openace_filament_cancel", None)
            if binding is not None and self.filament_operation.get("state") == "unknown":
                self.material._openace_filament_recovery = binding
                self.filament_operation["openace_recovery_supported"] = True
            self.material._openace_filament_cancel = None
            self.filament_operation.pop("openace_cancel_supported", None)
            self._record_filament_result()


    def _execute_filament_impl(self, gcmd, head, action, plan):
        if plan.get("owner") == "openace":
            steps = ([{"phase": "heating", "label": "Mount and heat head"},
                      {"phase": "inserting", "label": "Insert filament"},
                      {"phase": "feeding", "label": "Load filament"}] if plan.get("direct") else
                     [{"phase": "feeding", "label": "Load filament via openACE" if action == "load" else "Unload filament via openACE"}])
            steps.append({"phase": "verifying", "label": "Verify filament state"})
            self.filament_operation.update(steps=steps, phase=steps[0]["phase"])
            try:
                run = self.material.printer.lookup_object("gcode").run_script_from_command
                owner = self.material.printer.lookup_object("openace")
                owner_operation = ("openace_load_direct " + plan["head"] if plan.get("direct") else
                                   "select T%d" % plan["tool"] if action == "load" else "unload " + plan["head"])
                binding = {"owner": owner, "operation": self.filament_operation,
                           "plan": plan, "active": False, "owner_operation": owner_operation}
                if callable(getattr(owner, "abort_operation", None)):
                    self.material._openace_filament_cancel = binding
                    self.filament_operation["openace_cancel_supported"] = True
                def checkpoint():
                    if self.filament_operation.get("cancel_requested"):
                        raise FilamentCancelled("openACE filament stop requested")
                def owner_command(command):
                    checkpoint()
                    binding["active"] = True
                    try:
                        run(command)
                    finally:
                        binding["active"] = False
                    checkpoint()
                if plan.get("direct"):
                    self.filament_operation.update(message="Mounting and heating the head")
                    owner_command("OPENACE_LOAD_DIRECT HEAD=%s TEMP=%.3f" % (plan["head"], plan["target"]))
                    self.filament_operation.update(phase="inserting", message="Insert filament into Head %d" % (head + 1))
                    reactor = self.material.printer.get_reactor(); deadline = reactor.monotonic() + 180
                    while True:
                        checkpoint()
                        self.material._openace_filament_context(plan, reactor.monotonic())
                        if self.material._sensor_filament_status(reactor.monotonic())[plan["head"]]["state"] == "loaded":
                            break
                        if reactor.monotonic() >= deadline:
                            raise ValueError("No filament detected; loading timed out")
                        reactor.pause(reactor.monotonic() + .25)
                    self.filament_operation.update(phase="feeding", message="Loading filament")
                    owner_command("OPENACE_LOAD_DIRECT HEAD=%s DONE=1" % plan["head"])
                else:
                    owner_command(("OPENACE_SELECT TOOL=%d" % plan["tool"]) if action == "load" else "OPENACE_UNLOAD HEAD=" + plan["head"])
                self.filament_operation["phase"] = "verifying"
                ace = self.material.printer.lookup_object("openace").get_status(self.material.printer.get_reactor().monotonic())
                actual = ace.get("loaded", {}).get(plan["head"], {})
                completed = (actual.get("state") == "loaded" and actual.get("verified") is True
                             and actual.get("destination") == plan["destination"]
                             and isinstance(actual.get("identity"), dict)
                             and all(actual["identity"].get(field) == plan["identity"].get(field)
                                     for field in ("material", "color"))) if action == "load" else actual.get("state") == "empty"
                if (ace.get("session_id") != plan["ace_session"]
                        or "operation" not in ace or ace["operation"] is not None or not completed):
                    raise gcmd.error("openACE %s completion is not confirmed" % action)
            except Exception:
                if self.filament_operation.get("cancel_requested"):
                    try:
                        self.material._finish_openace_filament_stop(plan, head)
                    except Exception as error:
                        self.filament_operation.update(state="unknown", message="Stop not confirmed: " + str(error))
                        raise
                    return
                if plan.get("direct"):
                    try:
                        # Do not cool a replacement job or owner's heater.
                        self.material._openace_filament_context(plan, self.material.printer.get_reactor().monotonic())
                        run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % ("extruder" if head == 0 else "extruder%d" % head))
                    except Exception:
                        pass
                self.filament_operation.update(state="unknown", message="openACE filament outcome uncertain; inspect backend recovery state")
                raise
            self.filament_operation.update(state="complete", message="openACE verified the selected source loaded" if action == "load" else "openACE reports the head empty")
            gcmd.respond_info(self.filament_operation["message"])
            return
        steps = []
        if "service" in plan:
            steps.extend(service_progress_steps(head, plan["service"]))
            steps.append(("heating", "Heat nozzle"))
            if action == "load":
                steps.append(("inserting", "Insert filament"))
        steps.append(("feeding", "Feed filament" if action == "load" else "Retract filament"))
        if action == "load":
            steps.append(("purging", "Purge nozzle"))
            if "service" in plan:
                steps.append(("wiping", "Wipe nozzle"))
        if plan.get("service", {}).get("return_head") is not None:
            returning = dict(plan["service"], needs_home=False, attachment={"head": "h%d" % head})
            steps.extend(service_progress_steps(plan["service"]["return_head"], returning, "returning"))
        steps.append(("finishing", "Finish and turn heater off"))
        self.filament_operation["steps"] = [{"phase": phase, "label": label} for phase, label in steps]
        try:
            self._filament_checkpoint(steps[0][0])
            if "service" in plan:
                self.material._prepare_service(head, plan["service"])
                self._filament_checkpoint("heating")
                heater = "extruder" if head == 0 else "extruder%d" % head
                gcode = self.material.printer.lookup_object("gcode")
                self.filament_operation.update(message="Heating Head %d" % (head + 1))
                gcode.run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.3f" % (heater, plan["target"]))
                reactor = self.material.printer.get_reactor(); heat_deadline = reactor.monotonic() + 300
                while True:
                    self._filament_checkpoint("heating")
                    state = self.material.printer.lookup_object(heater).get_status(reactor.monotonic())
                    if state.get("target") != plan["target"] or not self.material._filament_context_valid(plan, reactor.monotonic()):
                        raise ValueError("Heating cancelled or printer became busy: " + ("heater target=%s; expected %s" % (repr(state.get("target"))[:80], repr(plan["target"])[:80]) if state.get("target") != plan["target"] else getattr(self.material, "_filament_context_refusal", "context admission was not confirmed")))
                    if abs(state.get("temperature", 0) - plan["target"]) <= 3 and state.get("can_extrude"):
                        break
                    if reactor.monotonic() >= heat_deadline:
                        raise ValueError("Nozzle heating timed out")
                    reactor.pause(reactor.monotonic() + .25)
                if action == "load":
                    self.filament_operation.update(message="Insert filament into Head %d" % (head + 1))
                    reactor = self.material.printer.get_reactor()
                    deadline = reactor.monotonic() + 180
                    while self.material._sensor_filament_status(reactor.monotonic())[plan["head"]]["state"] != "loaded":
                        self._filament_checkpoint("inserting")
                        if reactor.monotonic() >= deadline:
                            raise ValueError("No filament detected; loading timed out")
                        reactor.pause(reactor.monotonic() + .25)
                if not self.material._filament_context_valid(plan, reactor.monotonic()) or self.material._attachment(reactor.monotonic()) != {"state": "attached", "head": plan["head"]}:
                    raise ValueError("Printer or attachment changed before extrusion")
                if self.material.printer.lookup_object("toolhead").get_status(reactor.monotonic()).get("extruder") != heater:
                    raise ValueError("Active extruder changed before feeding")
                if self.material.printer.lookup_object(heater).get_status(reactor.monotonic()).get("target") != plan["target"]:
                    raise ValueError("Heating cancelled")
                self.filament_operation.update(message="Loading filament" if action == "load" else "Unloading filament")
            self._filament_checkpoint("feeding")
            sequence = "G1 E%g F400" % plan.get("feed_mm", 55.) if action == "load" else "_TIP_SHAPE_MOVES CLASS=" + plan["class"]
            if action == "load":
                # Persist uncertainty before dispatch: a partial feed may leave
                # both materials in the hotend even if the command raises.
                self.material._record_hotend_material(plan["head"], plan["identity"], purged=False)
            if action == "unload":
                # Once explicit withdrawal begins, the old loaded confirmation
                # is no longer trustworthy, even if the process dies mid-move.
                # Keep identity; inlet presence alone must never restore it.
                self.material._set_filament_loaded(plan["head"], False)
            self.material._run_filament_extrusion(self.material.printer, sequence)
            if action == "unload":
                self.material._set_filament_loaded(plan["head"], False)
            else:
                if "service" in plan and self.material._sensor_filament_status(self.material.printer.get_reactor().monotonic())[plan["head"]]["state"] != "loaded":
                    raise ValueError("Filament sensor does not confirm loading")
                # Confirm loaded only after purge/wipe and final checks. A
                # stopped partial Load is present, but not ready for printing.
                self._filament_checkpoint("purging")
                self.filament_operation.update(message="Purging nozzle")
                self.material._run_filament_extrusion(self.material.printer, "G1 E%g F400" % plan.get("purge_mm", 50.))
                self.material._record_hotend_material(plan["head"], plan["identity"], purged=True)
                if "service" in plan:
                    self._filament_checkpoint("wiping")
                    self.filament_operation.update(message="Wiping nozzle")
                    now = self.material.printer.get_reactor().monotonic()
                    th = self.material.printer.lookup_object("toolhead").get_status(now)
                    if (not self.material._filament_context_valid(plan, now)
                            or self.material._attachment(now) != {"state": "attached", "head": plan["head"]}
                            or th.get("extruder") != heater
                            or not all(axis in th.get("homed_axes", "") for axis in "xy")):
                        raise ValueError("Printer or attachment changed before wiping")
                    self.material.printer.lookup_object("gcode").run_script_from_command("WIPE_NOZZLE XY_ONLY=1\nM400")
            if plan.get("service", {}).get("return_head") is not None:
                self._filament_checkpoint("return_docking")
                self.material.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
                now = self.material.printer.get_reactor().monotonic()
                return_head = plan["service"]["return_head"]
                returning = self.material._service_context(return_head, now)
                for field, indices in (("positions", "dock_heads"), ("offsets", "offset_heads")):
                    if any(returning[field][index] != plan["service"][field][index]
                           for index in set(returning[indices]) | set(plan["service"][indices])):
                        raise ValueError("Calibration changed before returning the paused head")
                if returning["probe"] != plan["service"]["probe"]:
                    raise ValueError("Probe reference changed before returning the paused head")
                if returning["attachment"] != {"state": "attached", "head": plan["head"]}:
                    raise ValueError("Service head attachment changed before return")
                returning["restore_offset"] = plan["service"]["return_offset"]
                self.material._prepare_service(return_head, returning, phase_name="returning")
            self._filament_checkpoint("finishing")
            if "service" in plan:
                self.material.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
                if self.material.printer.lookup_object(heater).get_status(self.material.printer.get_reactor().monotonic()).get("target") != 0:
                    raise ValueError("Heater shutdown is not confirmed")
                if action == "load" and self.material._sensor_filament_status(self.material.printer.get_reactor().monotonic())[plan["head"]]["state"] != "loaded":
                    raise ValueError("Filament sensor does not confirm completion")
            self.material._set_filament_loaded(plan["head"], action == "load")
        except Exception as error:
            # A caught exception proves dispatch returned, not that queued moves
            # drained. Only release the UI for an operator check after M400.
            state = "unknown"
            try:
                self.material.printer.lookup_object("gcode").run_script_from_command("M400")
                state = "failed"
            except Exception:
                pass
            if "service" in plan or isinstance(error, FilamentCancelled):
                try:
                    self.material.printer.lookup_object("gcode").run_script_from_command("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % ("extruder" if head == 0 else "extruder%d" % head))
                    if self.material.printer.lookup_object("extruder" if head == 0 else "extruder%d" % head).get_status(self.material.printer.get_reactor().monotonic()).get("target") != 0:
                        state = "unknown"
                except Exception:
                    state = "unknown"
            cancelled = isinstance(error, FilamentCancelled)
            self.filament_operation.update(state=state, cancelled=cancelled,
                message=("Cancelled; inspect filament before another operation" if cancelled and state == "failed" else
                         "Procedure interrupted; stopping and heater state need verification" if state == "unknown" else
                         str(error) + "; inspect filament before another operation"), error=str(error))
            raise
        if plan.get("pause_origin"):
            if not self.material._filament_context_valid(plan, self.material.printer.get_reactor().monotonic()):
                self.filament_operation.update(state="failed", message="Paused context changed at completion")
                raise gcmd.error("Paused context changed at completion")
            self.material._pause_origin["ready"] = action == "load"
        self.filament_operation.update(state="complete", message="Filament loaded." if action == "load" else "Filament unloaded. Please remove filament.")
        gcmd.respond_info(self.filament_operation["message"])


