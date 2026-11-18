# SPDX-License-Identifier: GPL-3.0-or-later
"""Scoped print-mesh persistence and configuration save/restart routing."""
import configparser
import os
import stat
import tempfile


class ConfigurationSave:
    def __init__(self, material):
        self.material = material

    def _config_save_routes_ready(self):
        """Admit persistent writes before the vendor writer, not its restart.

        Both touchscreen and remote G-code enter these handlers. Keep the
        original writer and other-owner policy; no pending setting is changed
        or discarded when standalone admission refuses.
        """
        if getattr(self, "_config_save_handlers", None) is not None:
            return
        gcode = self.material.printer.lookup_object("gcode")
        originals = {}
        for name in ("SAVE_CONFIG", "SAVE_CONFIG_NO_RESTART"):
            original = gcode.register_command(name, None)
            if original is not None:
                originals[name] = original
        if "SAVE_CONFIG" not in originals:
            for name, original in originals.items():
                gcode.register_command(name, original)
            raise self.material.printer.config_error("Managed configuration requires SAVE_CONFIG")
        def wrap(name, original):
            def save(gcmd):
                if (self.material.printer.lookup_object("openace", None) is None
                        and self.material.printer.lookup_object("AFC", None) is None):
                    if self.material.printer.is_shutdown():
                        raise gcmd.error("Configuration save stopped: printer is shutdown")
                    if getattr(self.material.printer, "quick_stop_flag", False):
                        raise gcmd.error("Configuration save stopped: printer.quick_stop_flag is set")
                    # An explicit no-restart command expresses whole-set save
                    # intent. It is not a restart. START_PRINT uses the scoped
                    # mesh command below instead of this general writer.
                    if name == "SAVE_CONFIG":
                        self._restart_requested(None)
                return original(gcmd)
            return save
        for name, original in originals.items():
            gcode.register_command(name, wrap(name, original))
        self._config_save_handlers = originals


    def cmd_SAVE_PRINT_MESH(self, gcmd):
        """Optional print recovery persistence; never save unrelated edits."""
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            return self._config_save_handlers["SAVE_CONFIG_NO_RESTART"](gcmd)
        self.material._print_mesh_persisted = False
        try:
            now = self.material.printer.get_reactor().monotonic()
            config = self.material.printer.lookup_object("configfile")
            mesh = self.material.printer.lookup_object("bed_mesh").get_status(now)
            reason = self._mesh_pending_reason(mesh, config.status_save_pending)
            if reason:
                raise ValueError(reason)
            self._publish_print_mesh(config)
            self.material._print_mesh_persisted = True
        except (OSError, ValueError, AttributeError, KeyError, TypeError, configparser.Error,
                self.material.printer.command_error) as error:
            self.material._print_recovery_error = "Print mesh was not persisted: " + str(error)[:384]
            gcmd.respond_info(self.material._print_recovery_error +
                              ". Printing can continue; power-loss recovery is unavailable for this job.")


    def _publish_print_mesh(self, config):
        """Retained config serialization with a single atomic replacement.

        Only called with mesh-only pending settings under the G-code mutex.
        Unlike the vendor two-rename writer, a failed publication cannot leave
        printer.cfg absent. In-memory pending settings are not modified.
        """
        path = self.material.printer.get_start_args()["config_file"]
        if os.path.islink(path):
            raise ValueError("Mesh save cannot replace a linked printer configuration")
        original = config._read_config_file(path)
        regular, old_autosave = config._find_autosave_data(original)
        config._build_config_wrapper(regular, path)
        regular = config._strip_duplicates(regular, config.autosave)
        config._disallow_include_conflicts(regular, path, self.material.printer.lookup_object("gcode"))
        # Preserve the retained writer's header rather than inventing a second
        # config format. It is defined in the writer's module globals.
        header = config.cmd_SAVE_CONFIG_NO_RESTART.__func__.__globals__["AUTOSAVE_HEADER"]
        lines = [("#*# " + line).strip()
                 for line in config._build_config_string(config.autosave).split("\n")]
        payload = (regular.rstrip() + "\n" + header.rstrip() + "\n"
                   + "\n".join(lines) + "\n").encode("utf-8")
        directory = os.path.dirname(os.path.abspath(path))
        metadata = os.stat(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-print-mesh-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if config._read_config_file(path) != original:
                raise ValueError("Printer configuration changed during mesh save")
            # Retain a backup before publication; failure leaves the original
            # untouched. A unique name avoids overwriting another save's backup.
            backup_fd, backup = tempfile.mkstemp(prefix="printer-mesh-", suffix=".cfg", dir=directory)
            with os.fdopen(backup_fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                stream.write(original.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


    def _mesh_pending_reason(self, mesh, items):
        if mesh.get("profile_name") != "wmp_print":
            return "active mesh is %r; expected 'wmp_print'" % mesh.get("profile_name")
        if set(items) != {"bed_mesh wmp_print"}:
            sections = ", ".join(sorted(str(key) for key in items))[:256]
            return "pending config sections are [%s]; expected only [bed_mesh wmp_print]" % sections
        if not isinstance(items["bed_mesh wmp_print"], dict):
            return "pending [bed_mesh wmp_print] settings are not a dictionary"
        if not items["bed_mesh wmp_print"]:
            return "pending [bed_mesh wmp_print] settings are empty"
        return ""


    def _stock_startup_file(self):
        """Read-only binding for a stock SD START_PRINT, never a remote save."""
        now = self.material.printer.get_reactor().monotonic()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        stream = getattr(sd, "current_file", None)
        prefix = "Stock startup mesh save requires the active SD startup: "
        if self.material.printer.lookup_object("openace", None) is not None:
            raise ValueError(prefix + "openACE owns the printer")
        if self.material.printer.lookup_object("AFC", None) is not None:
            raise ValueError(prefix + "AFC owns the printer")
        if sd.is_active() is not True:
            raise ValueError(prefix + "virtual_sdcard.is_active is not True")
        if sd.is_cmd_from_sd() is not True:
            raise ValueError(prefix + "command is not executing from virtual SD")
        state = self.material.printer.lookup_object("print_stats").get_status(now).get("state")
        if state != "printing":
            raise ValueError(prefix + "print_stats.state=%r; expected 'printing'" % state)
        paused = self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused")
        if paused is not False:
            raise ValueError(prefix + "pause_resume.is_paused=%r; expected False" % paused)
        ready = self.material.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready")
        if ready is not False:
            raise ValueError(prefix + "START_PRINT.print_body_ready=%r; expected False" % ready)
        if stream is None:
            raise ValueError(prefix + "no open SD file")
        if stream.closed:
            raise ValueError(prefix + "SD file is closed")
        path = os.path.realpath(stream.name)
        positions = tuple(getattr(sd, name, None) for name in ("file_position", "next_file_position"))
        if any(type(value) is not int or value < 0 for value in positions):
            raise ValueError("Stock startup SD command position unavailable: file_position=%r, next_file_position=%r" % positions)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        opened, current = identity(os.fstat(stream.fileno())), identity(os.stat(path))
        if opened != current:
            changed = [name for name, before, after in zip(
                ("device", "inode", "size", "mtime_ns"), opened, current) if before != after]
            raise ValueError("Stock startup file changed: " + ", ".join(changed))
        return {"session": self.material.session_id, "stream": stream, "path": path,
                "identity": opened, "positions": positions,
                "generation": getattr(self.material, "_command_generation", 0)}


    def _restart_requested(self, print_time, probe_editor=None):
        """Reject a Ready-state restart before the vendor drain/exit sequence.

        The vendor dispatch calls this under its command mutex. System-service
        restarts bypass it; not-ready recovery keeps the vendor's explicit
        restart route. No journal is cleared and no operation is replayed here.
        """
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            return
        try:
            now = self.material.printer.get_reactor().monotonic()
            stats = self.material.printer.lookup_object("print_stats").get_status(now)
            pause = self.material.printer.lookup_object("pause_resume").get_status(now)
            sd = self.material.printer.lookup_object("virtual_sdcard")
            current_file = getattr(sd, "current_file", None)
            if stats.get("state") not in ("standby", "complete", "cancelled", "error"):
                raise ValueError("Finish or cancel the print before restarting: print_stats.state=%r" % stats.get("state"))
            if pause.get("is_paused") is not False:
                raise ValueError("Finish or cancel the print before restarting: pause_resume.is_paused=%r" % pause.get("is_paused"))
            if sd.is_active() is not False:
                raise ValueError("Finish or cancel the print before restarting: virtual SD worker is active")
            if sd.is_cmd_from_sd() is not False:
                raise ValueError("Finish or cancel the print before restarting: command is executing from virtual SD")
            if self.material._print_cancel_active():
                raise ValueError("Resolve the managed cancellation result before restarting")
            if self.material._recovery_attempt_active():
                raise ValueError("Resolve the managed recovery result before restarting")
            for name in ("filament_operation", "toolhead_operation"):
                state = getattr(self.material, name, {}).get("state")
                if self.material._material_operation_active(name):
                    raise ValueError("Stop and resolve the filament/tool operation before restarting: %s.state=%s" % (name, state))
            if getattr(self.material, "_pending_recovery_submission", None):
                raise ValueError("Wait for the managed operation before restarting: print submission is pending")
            if (getattr(self.material, "_profile_import_busy", False)
                    and getattr(self.material, "profile_import", {}).get("action") == "save"):
                raise ValueError("Wait for the managed operation before restarting: profile import save is writing settings")
            recovery = self.material.printer.lookup_object("wmp_recovery", None)
            calibration_status = recovery.get_status(now) if recovery is not None else {}
            if recovery is not None and calibration_status.get("calibration_active") is not False:
                calibration = getattr(recovery, 'calibration', None)
                # SAVE_CONFIG was admitted before writing. Permit its own
                # synchronous restart only; other active stages remain held.
                editor_admission = (probe_editor is not None
                    and getattr(calibration, 'probe_editor', None) is probe_editor
                    and getattr(calibration, 'active', True) is False)
                if not editor_admission and not (getattr(calibration, 'active', False) is True
                        and getattr(calibration, '_saving', False) is True
                        and getattr(calibration, 'failure', None) == ''):
                    raise ValueError("Finish or stop calibration before restarting: calibration_active=%r, command_active=%r, saving=%r, failure=%r" % (
                        calibration_status.get("calibration_active"), getattr(calibration, 'active', None),
                        getattr(calibration, '_saving', None), str(getattr(calibration, 'failure', None))[:160]))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            # Keep the existing explicit emergency-stop/restart route reachable
            # when readiness cannot be established. This is guidance, not an
            # automatic shutdown or a new way around current-operation checks.
            raise self.material.printer.command_error(
                "Restart not admitted: " + str(error)
                + ". To deliberately stop the printer, send M112, then send "
                "FIRMWARE_RESTART separately. This interrupts any work and "
                "requires rehoming.")


