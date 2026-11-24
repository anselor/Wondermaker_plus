# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery job evidence staged around normal print startup."""
import copy
import hashlib
import logging
import os
import re
import uuid


class _ScanCooperator:
    """Bound startup bookkeeping without changing the active G-code stream."""
    def __init__(self, reactor, progress=None, source=''):
        self.reactor = reactor
        self.started = reactor.monotonic()
        self.deadline = self.started + .020
        self.bytes = self.lines = self.processed = self.yields = 0
        self.progress, self.source = progress, source

    def advance(self, size):
        self.bytes += size
        self.processed += size
        self.lines += 1
        # Check wall time at most every 64 bounded line chunks; bytes also
        # bound progress for long slicer comments. Avoid tell() per G-code line.
        if self.bytes < 65536 and self.lines < 64:
            return
        self.lines = 0
        now = self.reactor.monotonic()
        if self.bytes >= 65536 or now >= self.deadline:
            if self.progress is not None:
                self.progress(self.processed)
            self.yields += 1
            self.reactor.pause(now + .001)
            self.bytes = 0
            self.deadline = self.reactor.monotonic() + .020


    def finish(self):
        if self.progress is not None:
            self.progress(self.processed)
        if self.source:
            logging.info("WM+ startup file scan: source=%s bytes=%d seconds=%.3f yields=%d",
                         self.source, self.processed,
                         self.reactor.monotonic() - self.started, self.yields)


class RecoveryJobs:
    def __init__(self, material):
        self.material = material

    def _pending_recovery_file(self):
        pending = getattr(self, "_pending_recovery_submission", None)
        if not pending:
            raise ValueError("No current managed print submission: submission is absent")
        if pending["record"]["session"] != self.material.session_id:
            raise ValueError("No current managed print submission: backend session changed")
        now = self.material.printer.get_reactor().monotonic()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        prefix = "Recovery material commit requires the active standalone SD startup: "
        if self.material.printer.lookup_object("openace", None) is not None:
            raise ValueError(prefix + "openACE owns the printer")
        if not sd.is_cmd_from_sd():
            raise ValueError(prefix + "command is not from virtual SD")
        if not sd.is_active():
            raise ValueError(prefix + "virtual SD worker is inactive")
        state = self.material.printer.lookup_object("print_stats").get_status(now).get("state")
        if state != "printing":
            raise ValueError(prefix + "print_stats.state=%r; expected 'printing'" % state)
        stream = getattr(sd, "current_file", None)
        if stream is None:
            raise ValueError("Active SD file differs from the submitted job: no file is selected")
        if stream.closed:
            raise ValueError("Active SD file differs from the submitted job: file is closed")
        if os.path.realpath(stream.name) != pending["full"]:
            raise ValueError("Active SD file differs from the submitted job: path changed")
        for label, info in (("open handle", os.fstat(stream.fileno())), ("path", os.stat(pending["full"]))):
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if actual != pending["identity"]:
                changed = [field for field, before, after in zip(
                    ("device", "inode", "size", "mtime_ns"), pending["identity"], actual) if before != after]
                raise ValueError("Active SD file changed after submission: %s %s" % (label, ", ".join(changed)))
        if self.material._read_recovery_job() != pending["record"]:
            raise ValueError("Staged recovery material evidence changed")
        return pending


    def _stage_active_sd_recovery(self):
        """Stage optional evidence from the actual SD job, regardless of UI."""
        binding = self.material._stock_startup_file()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        relative = os.path.relpath(binding["path"], os.path.realpath(sd.sdcard_dirname))
        if relative == ".." or relative.startswith(".." + os.sep):
            raise ValueError("Active print file is outside the SD directory")
        content, tools = hashlib.sha256(), set()
        usage = self.material._begin_usage_scan(binding["path"])
        preparation = self.material._print_preparation()
        attempt = preparation.begin_file_scan(relative, os.stat(binding["path"]).st_size)
        cooperate = _ScanCooperator(self.material.printer.get_reactor(),
                progress=lambda completed: preparation.file_scan_progress(attempt, completed), source='active-sd')
        with open(binding["path"], "rb") as stream:
            continuing = False
            while True:
                raw = stream.readline(65536)
                if not raw:
                    break
                content.update(raw)
                if usage is not None: usage["scanner"].feed(raw)
                # Hash the whole file without allocating an arbitrarily long
                # slicer polygon/comment line. Only the first chunk can name
                # a command; never interpret continuation text as a new tool.
                if continuing or raw.startswith((b"G0 ", b"G1 ", b";", b"#")):
                    continuing = not raw.endswith(b"\n")
                    cooperate.advance(len(raw))
                    continue
                line = raw.decode("utf-8", errors="replace").split(";", 1)[0].split("#", 1)[0].strip()
                if (not continuing and not raw.endswith(b"\n") and len(raw) == 65536
                        and b";" not in raw and b"#" not in raw
                        and re.match(r"(?:T[0-3]|START_PRINT)(?:\s|$)", line, re.IGNORECASE)):
                    raise ValueError("Tool selection line too long to inspect for recovery")
                continuing = not raw.endswith(b"\n")
                match = re.match(r"T([0-3])(?:\s|$)", line, re.IGNORECASE)
                if match:
                    tools.add(int(match.group(1)))
                if re.match(r"START_PRINT(?:\s|$)", line, re.IGNORECASE):
                    initial = re.search(r"\bINITIAL_TOOL=([0-3])(?:\s|$)", line, re.IGNORECASE)
                    if initial:
                        tools.add(int(initial.group(1)))
                cooperate.advance(len(raw))
        cooperate.finish()
        self.material._finish_usage_scan(usage, content.hexdigest(), binding["stream"])
        if not tools:
            raise ValueError("Cannot identify physical tool requirements in the SD file")
        current = self.material._stock_startup_file()
        if any(current[key] != binding[key] for key in binding):
            raise ValueError("Active SD job changed while staging recovery")
        now = self.material.printer.get_reactor().monotonic()
        variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        mapping = [variables.get("box_modify_t%d" % tool) for tool in range(4)]
        if any(type(head) is not int or head not in range(4) for head in mapping):
            raise ValueError("Physical print mapping is unavailable")
        loaded, heads = self.material._loaded_filament_status(now), {}
        for tool in tools:
            key = "h%d" % mapping[tool]
            head = loaded.get(key, {})
            if head.get("state") != "loaded" or not isinstance(head.get("identity"), dict):
                raise ValueError("Loaded material evidence is unavailable for " + key)
            self.material._validate_identity(head["identity"])
            heads[key] = {"source": head.get("source"), "identity": copy.deepcopy(head["identity"])}
        info = os.stat(binding["path"])
        record = {"version": 1, "state": "staged", "owner": "standalone",
                  "id": "sd_" + uuid.uuid4().hex, "session": self.material.session_id,
                  "file": {"path": relative, "size": info.st_size, "modified": info.st_mtime,
                           "sha256": content.hexdigest()},
                  "mapping": mapping, "required_tools": {str(tool): mapping[tool] for tool in sorted(tools)},
                  "heads": heads}
        self.material._write_recovery_job(record)
        self._pending_recovery_submission = {"record": record, "full": binding["path"],
                                             "identity": binding["identity"]}
        return self._pending_recovery_submission


    def cmd_RECOVERY_JOB_BEGIN(self, gcmd):
        self.material._bind_usage_stream()
        self.material._print_recovery_error = ""
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            self._print_mesh_persisted = None
            self.cmd_RECOVERY_JOB_CLEAR(gcmd)
            return
        self._print_mesh_persisted = False
        # One fresh boundary per actual SD START_PRINT invocation. A nested
        # second BEGIN in the same source line cannot erase a current failure.
        try:
            binding = self.material._stock_startup_file()
            with open(binding["path"], "rb") as source:
                source.seek(binding["positions"][0])
                line = source.readline(8192).decode("utf-8", errors="replace")
            if self.material._script_command_names(line) != ["START_PRINT"]:
                raise ValueError("Only the actual SD START_PRINT line opens a fresh physical attempt")
            key = (binding["session"], binding["stream"], binding["identity"], binding["positions"])
        except (ValueError, KeyError, AttributeError, TypeError, OSError):
            key = None
        if key is not None and key != getattr(self, "_physical_startup_boundary", None):
            self._physical_startup_boundary = key
            try:
                self.material._begin_explicit_physical_action("print startup", allow_active=True)
            except ValueError as error:
                raise gcmd.error(str(error)) from error
        try:
            self.material.printer.lookup_object("gcode").run_script_from_command(
                'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="{}"')
            pending = getattr(self, "_pending_recovery_submission", None)
            if pending:
                try:
                    pending = self._pending_recovery_file()
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    # An old submission cannot reserve a different current SD
                    # print. Build fresh optional evidence from the actual file.
                    pending = None
                    self._pending_recovery_submission = None
            if pending is None:
                self.cmd_RECOVERY_JOB_CLEAR(gcmd)
                pending = self._stage_active_sd_recovery()
            if pending.get("begun"):
                raise ValueError("Print recovery staging already began")
            self.material._begin_deposition_envelope(pending["record"])
            pending["begun"] = True
        except (OSError, ValueError, KeyError, TypeError, AttributeError, self.material.printer.command_error) as error:
            self.material._disable_print_recovery("Recovery staging unavailable: " + str(error))
            gcmd.respond_info(self.material._print_recovery_error + ". Printing can continue.")


    def cmd_RECOVERY_JOB_COMMIT(self, gcmd):
        if (getattr(self, "_print_mesh_persisted", None) is False
                or getattr(self.material, "_print_recovery_error", "")):
            self._pending_recovery_submission = None
            self.material._deposition_envelope = None
            gcmd.respond_info("Power-loss recovery unavailable: " +
                              (getattr(self.material, "_print_recovery_error", "") or "print mesh was not persisted"))
            return
        if not getattr(self, "_pending_recovery_submission", None):
            gcmd.respond_info("No managed material snapshot; managed power-loss admission is unavailable")
            return
        try:
            pending = self._pending_recovery_file()
            if not pending.get("begun"):
                raise ValueError("Managed startup has not begun")
            now = self.material.printer.get_reactor().monotonic()
            variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            record = pending["record"]
            context = {"version": 2, "tool": variables.get("probe_tool"), "mesh": "wmp_print",
                       "mapping": [variables.get("box_modify_t%d" % i) for i in range(4)],
                       "offsets": [variables.get("t%d_offset" % i) for i in range(4)],
                       "file_hex": record["file"]["path"].encode("utf-8").hex()}
            mesh = self.material.printer.lookup_object("bed_mesh").get_status(now)
            if (context.get("version") != 2 or context.get("mapping") != record["mapping"]
                    or context.get("file_hex") != record["file"]["path"].encode("utf-8").hex()
                    or type(context.get("tool")) is not int or context["tool"] not in range(4)
                    or context.get("offsets") != [variables.get("t%d_offset" % i) for i in range(4)]
                    or any(variables.get("t%d_offset" % i) is None for i in range(4))
                    or context.get("mesh") != "wmp_print" or mesh.get("profile_name") != "wmp_print"
                    or "wmp_print" not in mesh.get("profiles", {})):
                raise ValueError("Committed mesh, mapping or calibration differs from the managed job")
            loaded = self.material._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                if (not self.material._loaded_source_matches(loaded.get(key, {}), saved)):
                    raise ValueError("Loaded filament changed during print startup")
            if any(self.material._material_operation_active(name)
                   for name in ("filament_operation", "toolhead_operation")):
                raise ValueError("Unfinished material or tool operation at print startup")
            try:
                context["file_effect_contract"] = self.material._recovery_file_effect_contract()
            except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
                # Optional fallback qualification must never abort normal print.
                logging.info("File-derived recovery fallback unavailable: %s", error)
            encoded = repr(context).replace("\\", "\\\\").replace('"', '\\"')
            self.material.printer.lookup_object("gcode").run_script_from_command(
                'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="%s"' % encoded)
            current = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            if current.get("wmp_print_context") != context:
                raise ValueError("Print recovery context write was not confirmed")
            committed = dict(record, state="committed", context=copy.deepcopy(context))
            self.material._write_recovery_job(committed)
            self._pending_recovery_submission = None
        except (OSError, ValueError, KeyError, TypeError, AttributeError,
                self.material.printer.command_error) as error:
            # Never retry a failed commit against a later job or modified state.
            self.material._disable_print_recovery("Print recovery commit unavailable: " + str(error))
            gcmd.respond_info(self.material._print_recovery_error + ". Printing can continue.")


    def cmd_RECOVERY_JOB_CLEAR(self, gcmd):
        self.material._deposition_envelope = None
        self._pending_recovery_submission = None
        try:
            self.material._write_recovery_job({"version": 1, "state": "invalidated",
                                      "reason": "print-context-cleared", "session": self.material.session_id})
            return True
        except (OSError, ValueError) as error:
            # The preceding macro already cleared the saved mesh context.
            # Do not block cancellation's heater/motion cleanup on storage I/O.
            gcmd.respond_info("Recovery material clear failed; cleared print context prevents admission: " + str(error))
            return False


    def _stage_recovery_job(self, gcmd, request, full, file_identity, mapping, admitted_recipes=None):
        if mapping is None:
            # openACE must supply its own durable job/source contract. A stale
            # standalone record must never become fallback authority for it.
            self.material._write_recovery_job({"version": 1, "state": "owner-required",
                                      "owner": "openace", "id": request["id"],
                                      "session": self.material.session_id})
            return

        # Recovery metadata is optional, but keep its pre-scan snapshot so an
        # intervening used-head/source change cannot silently replace evidence.
        loaded_error = None
        try:
            loaded = copy.deepcopy(self.material._loaded_filament_status(self.material.printer.get_reactor().monotonic()))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            loaded, loaded_error = {}, error

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

        content = hashlib.sha256()
        usage = self.material._begin_usage_scan(full)
        cooperate = _ScanCooperator(self.material.printer.get_reactor(), source='screen-submission')
        with open(full, "rb") as stream:
            if identity(os.fstat(stream.fileno())) != file_identity:
                raise ValueError("Print file changed before recovery staging")
            for chunk in iter(lambda: stream.readline(65536), b""):
                content.update(chunk)
                if usage is not None: usage["scanner"].feed(chunk)
                # Large G-code files must not starve status/sensor processing.
                # The G-code lock remains held; revalidate after yielding.
                cooperate.advance(len(chunk))
            if identity(os.fstat(stream.fileno())) != file_identity:
                raise ValueError("Print file changed during recovery staging")
        if identity(os.stat(full)) != file_identity:
            raise ValueError("Print file replaced during recovery staging")
        self.material.printer.get_reactor().pause(self.material.printer.get_reactor().monotonic() + .001)
        cooperate.finish()
        self.material._finish_usage_scan(usage, content.hexdigest())
        if loaded_error is not None:
            raise loaded_error
        required = sorted(set(request["mapping"].values()))
        heads = {}
        for head in required:
            key = "h%d" % head
            record = loaded.get(key, {})
            if (record.get("state") != "loaded"
                    or record.get("source") != "external:" + key
                    or not isinstance(record.get("identity"), dict)):
                raise ValueError("Loaded source identity is unavailable for Head %d" % (head + 1))
            self.material._validate_identity(record["identity"])
            heads[key] = {"source": record["source"], "identity": copy.deepcopy(record["identity"])}

        sd = self.material._print_admission(gcmd)
        if (self.material._profiles()[1] != request["profile_revision"] if admitted_recipes is None
                else self.material._profile_recipes(admitted_recipes) != admitted_recipes):
            raise ValueError("Filament recipe changed during recovery staging")
        variables = self.material.printer.lookup_object("save_variables").get_status(
            self.material.printer.get_reactor().monotonic())["variables"]
        if any(variables.get("box_modify_t%d%s" % (tool, suffix)) != head
               for tool, head in enumerate(mapping) for suffix in ("", "_backup")):
            raise ValueError("Tool mapping changed during recovery staging")
        current = self.material._loaded_filament_status(self.material.printer.get_reactor().monotonic())
        if any(current.get(key, {}).get("state") != "loaded"
               or any(current[key].get(field) != value for field, value in saved.items())
               for key, saved in heads.items()):
            raise ValueError("Loaded filament changed during recovery staging")
        fresh_full, fresh_identity = self.material._print_file(sd, request["file"])
        if fresh_full != full or fresh_identity != file_identity:
            raise ValueError("Print file changed during recovery staging")
        # Only the used sliced tools are requirements; unused mapping entries
        # do not require loading otherwise empty physical heads.
        record = {
            "version": 1, "state": "staged", "owner": "standalone",
            "id": request["id"], "session": self.material.session_id,
            "file": dict(request["file"], sha256=content.hexdigest()),
            "mapping": list(mapping), "required_tools": dict(request["mapping"]),
            "heads": heads}
        self.material._write_recovery_job(record)
        self._pending_recovery_submission = {"record": copy.deepcopy(record),
                                             "full": full, "identity": file_identity}


