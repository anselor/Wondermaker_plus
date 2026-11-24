# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone print admission, file binding and submission.

Owns print request history and submission results; the coordinator supplies
material state, owner routing and PLR startup evidence."""
import copy
import uuid
import json
import math
import os
import re
import stat


class PrintSubmission:
    def __init__(self, material):
        self.material = material

    def _pending_stop_binding(self, request):
        printer = self.material.printer
        now = printer.get_reactor().monotonic()
        sd = printer.lookup_object('virtual_sdcard')
        stats = printer.lookup_object('print_stats').get_status(now)
        submission = self.print_submission
        if (printer.is_shutdown()
                or printer.lookup_object('webhooks').get_status(now).get('state') != 'ready'
                or any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC'))
                or request['session'] != self.material.session_id
                or submission.get('session') != request['session']
                or submission.get('id') != request['start']
                or submission.get('file') != request['file']
                or submission.get('state') != 'pending'
                or sd.is_active() or sd.is_cmd_from_sd()
                or stats.get('state') in ('printing', 'paused')
                or self.material._print_cancel_active()):
            raise ValueError('Pending print start changed; refresh cancellation')
        return (submission, getattr(self.material, '_command_generation', 0),
                getattr(sd, 'current_file', None), stats.get('filename'))

    def review_pending_stop(self, web_request):
        request = {key: web_request.get_str(key) for key in ('id', 'session', 'file', 'start')}
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', request['id'])
                or not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', request['start'])
                or not 0 < len(request['file']) <= 4096):
            raise ValueError('Invalid pending-start cancellation request')
        binding = self._pending_stop_binding(request)
        cancellation = self.material._cancellation()
        if request['id'] in getattr(cancellation, '_print_cancel_requests', set()):
            raise ValueError('Cancellation ID was already attempted')
        now = self.material.printer.get_reactor().monotonic()
        tickets = {key: value for key, value in getattr(self, '_pending_stop_tickets', {}).items()
                   if not value['used'] and now < value['expires']}
        old = tickets.get(request['id'])
        if old is not None:
            if (old['binding'][0] is not binding[0] or old['binding'][1:] != binding[1:]
                    or any(old['request'][key] != value for key, value in request.items())):
                raise ValueError('Pending-start cancellation review changed')
            web_request.send(dict(request=old['request']))
            return
        if len(tickets) >= 1024:
            raise ValueError('Too many pending-start cancellation reviews')
        request['token'] = uuid.uuid4().hex
        tickets[request['id']] = dict(request=dict(request), binding=binding, used=False, expires=now + 60.)
        self._pending_stop_tickets = tickets
        web_request.send(dict(request=request))

    def cancel_pending_stop(self, web_request):
        request = {key: web_request.get_str(key) for key in ('id', 'session', 'file', 'start', 'token')}
        ticket = getattr(self, '_pending_stop_tickets', {}).get(request['id'])
        now = self.material.printer.get_reactor().monotonic()
        if ticket is None or ticket['used'] or now >= ticket['expires'] or request != ticket['request']:
            raise ValueError('Pending-start cancellation review expired, changed or was used')
        binding = self._pending_stop_binding(request)
        if ticket['binding'][0] is not binding[0] or ticket['binding'][1:] != binding[1:]:
            raise ValueError('Pending start changed after cancellation review')
        ticket['used'] = True
        web_request.send(self._retire_pending_start(request, binding))

    def cancel_current_pending_start(self):
        submission = getattr(self, 'print_submission', {})
        if submission.get('state') != 'pending':
            return None
        request = dict(id='legacy_cancel_' + uuid.uuid4().hex, session=self.material.session_id,
                       file=submission['file'], start=submission['id'])
        return self._retire_pending_start(request, self._pending_stop_binding(request))

    def _retire_pending_start(self, request, binding):
        # No SD execution, heating or movement has been dispatched in this
        # phase. Retire its generation before acknowledging Stop. The command
        # and scan recheck this fence before writing evidence or opening SD.
        self.material._command_generation = binding[1] + 1
        self.print_submission.update(state='not_started', message='Print cancelled before it started.',
                                     error='Cancelled by user')
        self.material._pending_recovery_submission = None
        cancellation = self.material._cancellation()
        used = getattr(cancellation, '_print_cancel_requests', set())
        if len(used) >= 1024:
            used = set()
        cancellation._print_cancel_requests = used | {request['id']}
        cancellation._print_cancel_live_binding = None
        cancellation._print_cancel = dict(version=3, id=request['id'], session=request['session'],
            file=request['file'], state='complete', phase='complete', message='Print cancelled before it started',
            stages=[dict(name=name, state='complete') for name in cancellation._CANCEL_STAGES],
            stop_point=dict(phase='file_preparation', label='Reading/processing G-code',
                            state='start retired; no heating or movement dispatched'))
        cancellation._record_print_cancel()
        return copy.deepcopy(cancellation._print_cancel)

    def _print_admission(self, gcmd, openace=False):
        try:
            self.material._require_no_recovery_attempt()
        except ValueError as error:
            raise gcmd.error(str(error))
        if self.material._identification_pending(self.material.printer.get_reactor().monotonic()):
            raise gcmd.error("Restart Klipper after head identification before printing")
        present = self.material.printer.lookup_object("openace", None) is not None
        if present != openace or (not openace and self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Print submission ownership changed")
        if not openace and any(self.material._material_operation_active(name)
                               for name in ("filament_operation", "toolhead_operation")):
            raise gcmd.error("Wait for the running filament or toolhead operation before starting a print")
        now = self.material.printer.get_reactor().monotonic()
        stats = self.material.printer.lookup_object("print_stats").get_status(now)
        sd = self.material.printer.lookup_object("virtual_sdcard")
        paused = self.material.printer.lookup_object("pause_resume").get_status(now)
        if (stats.get("state") not in (("standby", "complete", "cancelled") if openace
                    else ("standby", "complete", "cancelled", "error"))
                or paused.get("is_paused") is not False
                or sd.is_active() or sd.is_cmd_from_sd()):
            raise gcmd.error("Another print or recovery context is active")
        return sd


    def _print_plan(self, gcmd, request):
        if isinstance(request, dict) and request.get("owner") == "openace":
            return self.material._openace_print_plan(gcmd, request)
        # Validation is complete before any settings, file reset or motion.
        sd = self._print_admission(gcmd)
        if not isinstance(request, dict) or set(request) - {"sequence", "material_confirmation", "sliced_materials"} != {
                "id", "session", "profile_revision", "file", "mapping",
                "expected_mapping", "leveling"}:
            raise ValueError("Invalid print request fields")
        ticket = request["id"]
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if request["session"] != self.material.session_id:
            raise ValueError("Printer session changed; refresh preview")
        self._check_print_ticket(request)
        if type(request["leveling"]) is not bool:
            raise ValueError("Invalid leveling option")
        profiles, revision = self.material._profiles()
        if request["profile_revision"] != revision:
            raise ValueError("Filament settings changed; refresh preview")
        variables = self.material.printer.lookup_object("save_variables").get_status(
            self.material.printer.get_reactor().monotonic())["variables"]
        previous = [variables.get("box_modify_t%d" % i) for i in range(4)]
        expected = request["expected_mapping"]
        if (not isinstance(expected, list) or len(expected) != 4
                or any(type(v) is not int or not 0 <= v <= 3 for v in expected)
                or any(type(v) is not int for v in previous)
                or previous != expected):
            raise ValueError("Tool mapping changed; refresh preview")
        chosen = request["mapping"]
        if not isinstance(chosen, dict) or not chosen or len(chosen) > 4:
            raise ValueError("Choose destinations for the sliced tools")
        mapping = list(previous)
        for tool, head in chosen.items():
            if tool not in ("0", "1", "2", "3") or type(head) is not int or not 0 <= head <= 3:
                raise ValueError("Invalid sliced tool or physical head")
            heater = "extruder" if head == 0 else "extruder%d" % head
            if self.material.printer.lookup_object(heater, None) is None:
                raise ValueError("Selected physical head is not installed")
            mapping[int(tool)] = head
        self._require_print_materials(request, profiles)
        full, identity = self._print_file(sd, request["file"])
        return mapping, full, identity


    def _check_print_ticket(self, request):
        ticket = request.get("id")
        if request.get("session") != self.material.session_id:
            raise ValueError("Printer session changed; refresh preview")
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if "sequence" in request:
            sequence = request["sequence"]
            if (type(sequence) is not int or not 1 <= sequence <= 9007199254740991
                    or ticket != "print_%d" % sequence):
                raise ValueError("Invalid sequenced print request identity")
            if sequence != getattr(self, "_print_request_sequence", 0) + 1:
                raise ValueError("Print request sequence expired; refresh preview and check its result")
        else:
            if ticket.startswith("print_"):
                raise ValueError("Sequenced print request ID requires its sequence")
            if len(self._print_requests) >= 1024:
                raise ValueError("Legacy print request capacity reached; refresh with a sequence-capable client")
        if ticket in self._print_requests:
            raise ValueError("Print request already attempted; check its result")


    def _remember_print_ticket(self, request):
        if isinstance(request, dict) and request.get("owner") == "openace":
            ticket = request.get("id")
            if (request.get("session") != self.material.session_id or not isinstance(ticket, str)
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket)
                    or ticket in self._print_requests or len(self._print_requests) >= 1024):
                return False
            self._print_requests.add(ticket)
            return True
        try:
            self._check_print_ticket(request)
        except (AttributeError, ValueError):
            return False
        if "sequence" in request:
            self._print_request_sequence = request["sequence"]
        else:
            self._print_requests.add(request["id"])
        return True


    def _require_print_materials(self, request, profiles=None):
        confirmation = request.get("material_confirmation", False)
        if type(confirmation) is not bool:
            raise ValueError("Invalid material confirmation")
        sliced = request.get("sliced_materials", {})
        if (not isinstance(sliced, dict) or set(sliced) - set(request["mapping"])
                or any(not isinstance(v, str) or len(v) > 128
                       or any(ord(c) < 32 for c in v) for v in sliced.values())):
            raise ValueError("Invalid sliced material review")
        if profiles is None:
            profiles = self.material._profiles()[0]
        now = self.material.printer.get_reactor().monotonic()
        sensed = self.material._sensor_filament_status(now)
        loaded = self.material._loaded_filament_status(now)
        for tool, head in request["mapping"].items():
            key = "h%d" % head
            if sensed.get(key, {}).get("state") != "loaded":
                raise ValueError("Head %d filament sensor is empty or unavailable" % (head + 1))
            configured = profiles.get(key, {}).get("material", "")
            expected = sliced.get(tool, "")
            needs_review = (not configured or loaded.get(key, {}).get("state") != "loaded"
                            or (expected and configured.casefold() != expected.casefold()))
            if needs_review and not confirmation:
                raise ValueError("Confirm filament metadata/loading for Head %d before printing" % (head + 1))


    def _require_loaded_print_heads(self, heads):
        # Configured identity and an inlet switch alone do not prove loading.
        loaded = self.material._loaded_filament_status(self.material.printer.get_reactor().monotonic())
        for head in heads:
            if loaded.get("h%d" % head, {}).get("state") != "loaded":
                raise ValueError("Load filament in Head %d before printing" % (head + 1))


    def _print_file_identity(self, sd, identity):
        if not isinstance(identity, dict) or set(identity) != {"path", "size", "modified"}:
            raise ValueError("Invalid file identity")
        path = identity["path"]
        if (not isinstance(path, str) or not path or len(path) > 1024
                or path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/"))
                or any(ord(c) < 32 or ord(c) == 127 or c in '\\"' for c in path)):
            raise ValueError("Unsupported print filename")
        size, modified = identity["size"], identity["modified"]
        if (type(size) is not int or size <= 0
                or type(modified) not in (int, float) or not math.isfinite(modified)):
            raise ValueError("Invalid file size or modification time")
        root = os.path.realpath(sd.sdcard_dirname)
        full = os.path.realpath(os.path.join(root, path))
        if os.path.commonpath([root, full]) != root:
            raise ValueError("Print file is outside the G-code directory")
        info = os.stat(full)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size or info.st_mtime != modified:
            raise ValueError("Print file changed; refresh preview")
        return full, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


    def _print_file(self, sd, identity):
        full, file_identity = self._print_file_identity(sd, identity)
        path = identity["path"]
        # The stock loader enumerates files and can case-fold names. Require the
        # exact selected entry so it cannot silently choose a different file.
        if path not in {name for name, unused_size in sd.get_file_list(True)}:
            raise ValueError("Print file is not available to the SD loader")
        return full, file_identity


    def cmd_DISPATCH_SD_PRINT(self, gcmd):
        # The vendor extended-command parser strips #, ; and * even inside
        # quotes. Decode only at this boundary and retain the SD backend's own
        # work-timer, selected-file, storage and start validation.
        try:
            path = bytes.fromhex(gcmd.get("FILENAME_HEX")).decode("utf-8")
            if (gcmd.get("SESSION") != self.material.session_id
                    or int(gcmd.get("GENERATION")) != getattr(self.material, "_command_generation", 0)
                    or self.print_submission.get("state") != "pending"
                    or self.print_submission.get("file") != path):
                raise ValueError("Print dispatch was retired or its selection changed")
            sd = self._print_admission(gcmd)
        except (UnicodeError, ValueError) as error:
            raise gcmd.error(str(error))
        command = self.material.printer.lookup_object("gcode").create_gcode_command(
            "SDCARD_PRINT_FILE", "", {"FILENAME": path})
        sd.cmd_SDCARD_PRINT_FILE(command)


    def cmd_START_PRINT(self, gcmd):
        request = None
        try:
            encoded = gcmd.get("REQUEST")
            if len(encoded) > 8192 or not re.fullmatch(r"[0-9a-fA-F]+", encoded):
                raise ValueError("Invalid encoded print request")
            request = json.loads(bytes.fromhex(encoded).decode("utf-8"))
            mapping, full, identity = self._print_plan(gcmd, request)
            admitted_recipes = (self.material._profile_recipes({"h%d" % head for head in request["mapping"].values()})
                                if mapping is not None else None)
        except Exception as error:
            # A refusal receipt proves that no preparation or SD command was
            # attempted. Never replace an already-attempted ticket's outcome.
            if (isinstance(request, dict) and isinstance(request.get("file"), dict)
                    and isinstance(request["file"].get("path"), str)
                    and self._remember_print_ticket(request)):
                self.print_submission = {"id": request["id"], "session": self.material.session_id,
                                         "file": request["file"]["path"], "state": "refused"}
            raise gcmd.error(str(error))
        if mapping is not None:
            try:
                self.material._begin_explicit_physical_action("print start")
            except ValueError as error:
                raise gcmd.error(str(error)) from error
        ticket = request["id"]
        self._remember_print_ticket(request)
        self.print_submission = {"id": ticket, "session": self.material.session_id,
                                 "file": request["file"]["path"], "state": "pending"}
        if mapping is not None:
            self.material._print_preparation().begin_submission(self.print_submission, identity[2])
        gcode = self.material.printer.lookup_object("gcode")
        sd_dispatch_attempted = False
        generation = getattr(self.material, "_command_generation", 0)
        try:
            self.material._pending_recovery_submission = None
            # Invalidate historical material evidence before the first admitted
            # new-job side effect, including a startup that subsequently fails.
            self.material._print_recovery_error = ""
            try:
                self.material._write_recovery_job({"version": 1, "state": "invalidated",
                                          "reason": "new-print", "id": ticket,
                                          "session": self.material.session_id})
            except (OSError, ValueError) as error:
                if mapping is None:
                    raise
                self.material._disable_print_recovery("New-job evidence unavailable: " + str(error))
                gcmd.respond_info("Print will continue without recovery: " + str(error))
            for tool, head in enumerate(mapping or []):
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=box_modify_t%d VALUE=%d" % (tool, head))
                gcode.run_script_from_command("SAVE_VARIABLE VARIABLE=box_modify_t%d_backup VALUE=%d" % (tool, head))
            gcode.run_script_from_command("G30" if request["leveling"] else "G31")
            if not getattr(self.material, "_print_recovery_error", ""):
                try:
                    self.material._stage_recovery_job(gcmd, request, full, identity, mapping, admitted_recipes)
                except (OSError, ValueError) as error:
                    if mapping is None:
                        raise
                    self.material._disable_print_recovery("Job evidence unavailable: " + str(error))
                    gcmd.respond_info("Print will continue without recovery: " + str(error))
            if mapping is None:
                _, fresh_full, fresh_identity = self.material._openace_print_plan(gcmd, request, recheck=True)
                if fresh_full != full or fresh_identity != identity:
                    raise gcmd.error("Print file changed during preparation; not started")
                script = 'SDCARD_PRINT_FILE FILENAME="%s" OPENACE_MAP="%s"' % (
                    request["file"]["path"], json.dumps(request["pairs"], separators=(",", ":")))
            else:
                sd = self._print_admission(gcmd)
                current = self.material.printer.lookup_object("save_variables").get_status(
                    self.material.printer.get_reactor().monotonic())["variables"]
                if any(current.get("box_modify_t%d%s" % (tool, suffix)) != head
                       for tool, head in enumerate(mapping) for suffix in ("", "_backup")):
                    raise gcmd.error("Prepared mapping was not confirmed; not started")
                self._require_print_materials(request)
                if self.material._profile_recipes(admitted_recipes) != admitted_recipes:
                    raise gcmd.error("Filament recipe changed during preparation; not started")
                if os.path.realpath(os.path.join(sd.sdcard_dirname, request["file"]["path"])) != full:
                    raise gcmd.error("Print file changed during preparation; not started")
                info = os.stat(full)
                if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identity:
                    raise gcmd.error("Print file changed during preparation; not started")
                script = 'SDCARD_PRINT_FILE FILENAME="%s"' % request["file"]["path"]
                if any(char in request["file"]["path"] for char in "#;*"):
                    script = "_WMP_DISPATCH_SD_PRINT FILENAME_HEX=%s SESSION=%s GENERATION=%d" % (
                        request["file"]["path"].encode("utf-8").hex(), self.material.session_id,
                        getattr(self.material, "_command_generation", 0))
            if generation != getattr(self.material, "_command_generation", 0):
                raise gcmd.error("Print request retired during preparation; not started")
            sd_dispatch_attempted = True
            gcode.run_script_from_command(script)
            if mapping is not None:
                self.material._print_preparation().bind_dispatched_submission(self.print_submission)
        except Exception as error:
            # Preparation can partially change mapping/leveling settings, but
            # cannot start SD execution. Once dispatch is attempted its outcome
            # is uncertain even if the command raises. Never retry this ticket.
            self.material._pending_recovery_submission = None
            self.print_submission["state"] = (
                "unknown" if sd_dispatch_attempted else "not_started")
            if not sd_dispatch_attempted and self.print_submission.get("error") != "Cancelled by user":
                self.print_submission["message"] = (
                    "Print was not started. Preparation failed; tool mapping or leveling "
                    "settings may have changed. Review them before trying again.")
                self.print_submission["error"] = str(error)[:240]
            raise
        self.print_submission["state"] = "submitted"
        gcmd.respond_info("Print submitted: " + ticket)


