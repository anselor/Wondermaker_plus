# SPDX-License-Identifier: GPL-3.0-or-later
"""Filament profile editing/import, nozzle settings and active-job recipe usage."""
import copy
import json
import math
import os
import re
import threading

try:
    from . import wmp_recovery_file_envelope, wmp_filament_profiles, wmp_nozzles, wmp_nozzle_runtime
    from .wmp_observation import _status_observation
    from .wmp_filament_types import SLOTS
except ImportError:
    import wmp_recovery_file_envelope, wmp_filament_profiles, wmp_nozzles, wmp_nozzle_runtime
    from wmp_observation import _status_observation
    from wmp_filament_types import SLOTS

class MaterialSettings:
    _validate_identity = staticmethod(wmp_filament_profiles.validate_identity)

    def __init__(self, material):
        self.material = material
        self._nozzle_runtime = wmp_nozzle_runtime.NozzleRuntime(material.printer, self._saved_nozzle_diameter)

    def _saved_nozzle_diameter(self, name):
        head = 'h' + (name[len('extruder'):] or '0')
        return self.material._nozzles.read()[0][head]['diameter']

    def cmd_PROFILE_IMPORT(self, gcmd):
        self.material._drain_async_completions()
        if self.material.printer.lookup_object("openace", None) is not None:
            raise gcmd.error("This catalogue is managed by standalone WM+")
        now = self.material.printer.get_reactor().monotonic()
        if self._profile_import_busy:
            raise gcmd.error("Profile import is busy")
        request_id = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request_id):
            raise gcmd.error("Invalid import request ID")
        action = gcmd.get("ACTION")
        if action not in ("scan", "review", "save"):
            raise gcmd.error("Unknown profile import action")
        if action == "save" and not self._idle_for_filament_settings(now):
            raise gcmd.error("Profile import save requires an idle printer: " + getattr(self, "_idle_settings_refusal", "idle admission was not confirmed"))
        value = gcmd.get("FILE") if action == "review" else gcmd.get("TOKEN") if action == "save" else ""
        if action != "scan" and not re.fullmatch(r"[0-9a-f]{%d}" % (64 if action == "review" else 48), value):
            raise gcmd.error("Invalid profile selection")
        self._profile_import_busy = True
        self.profile_import = {"state": "busy", "action": action, "id": request_id}
        reactor = self.material.printer.get_reactor()
        def worker():
            try:
                if action == "scan": result = self._profile_importer.scan()
                elif action == "review": result = self._profile_importer.review(value)
                else: result = self._profile_importer.save(value)
            except Exception as error:
                result = {"state": "error", "message": str(error)}
            def finish(now):
                if action == "save":
                    self._status_catalogue_snapshot = None
                result["id"] = request_id
                self.profile_import = result
                self._profile_import_busy = False
            self.material._queue_async_completion(finish)
        try:
            threading.Thread(target=worker, name="wm-profile-import", daemon=True).start()
        except Exception as error:
            self._profile_import_busy = False
            self.profile_import = {"state": "error", "action": action,
                                   "id": request_id, "message": str(error)}
            raise


    def _profile_import_writing(self):
        return (getattr(self, "_profile_import_busy", False)
                and getattr(self, "profile_import", {}).get("action") == "save")


    def _screen_configuration_status(self, now):
        # The screen needs three fields per heater and four mapping values,
        # not the full macro configuration or saved-variable database.
        heaters = {}
        mapping = [None] * SLOTS
        try:
            settings = wmp_nozzle_runtime.active_settings(self.material.printer,
                self.material.printer.lookup_object("configfile").get_status(now)["settings"])
            for index in range(SLOTS):
                name = "extruder" + (str(index) if index else "")
                values = settings.get(name, {})
                heaters[name] = {key: values[key] for key in
                                 ("min_temp", "max_temp", "nozzle_diameter")
                                 if type(values.get(key)) in (int, float)
                                 and math.isfinite(values[key])}
        except (AttributeError, KeyError, TypeError):
            heaters = {}
        try:
            saved = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            mapping = [saved.get("box_modify_t%d" % i) for i in range(SLOTS)]
            mapping = [v if type(v) is int and 0 <= v < SLOTS else None for v in mapping]
        except (AttributeError, KeyError, TypeError):
            pass
        return {"screen_status_protocol": 1, "heater_settings": heaters,
                "physical_mapping": mapping}


    def _nozzle_status(self, now, detailed=True):
        result = {"nozzle_settings_protocol": 0, "nozzles": {},
                  "nozzle_save": dict(getattr(self, "nozzle_save", {}))}
        store = getattr(self.material, "_nozzles", None)
        if store is None:
            return result
        try:
            heads, revision = store.read_status()
            settings = wmp_nozzle_runtime.active_settings(self.material.printer,
                self.material.printer.lookup_object("configfile").get_status(now)["settings"])
            for head, values in heads.items():
                heater = "extruder" + (head[1] if head != "h0" else "")
                active = settings.get(heater, {}).get("nozzle_diameter")
                if type(active) not in (int, float) or not math.isfinite(active):
                    raise ValueError("Active nozzle diameter is unavailable")
                values["active_diameter"] = active
                values["apply_pending"] = heater in self._nozzle_runtime.pending
                values["apply_error"] = self._nozzle_runtime.errors.get(heater, "")
                values["live_update_supported"] = self._nozzle_runtime.status_supported(heater, fresh=detailed)
                values["restart_required"] = not values["live_update_supported"] and abs(active - values["diameter"]) > 0.000001
            result.update(nozzle_settings_protocol=1, nozzles=heads, nozzle_revision=revision)
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            result["nozzle_error"] = str(error)
        return result


    def cmd_SET_NOZZLE(self, gcmd):
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another filament manager owns nozzle settings")
        now = self.material.printer.get_reactor().monotonic()
        state = self.material.printer.lookup_object("print_stats").get_status(now).get("state")
        paused = self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused", False)
        sd_active = self.material.printer.lookup_object("virtual_sdcard").is_active()
        if state in ("printing", "paused") or paused or sd_active:
            raise gcmd.error("Finish or cancel the print before changing nozzle settings: "
                             "print_stats.state=%r, is_paused=%s, sd_active=%s" % (state, paused, sd_active))
        # Live geometry applies at an idle planner boundary, never from a read.
        if self._identification_pending(now):
            raise gcmd.error("Wait for head identification to finish before saving nozzle settings")
        if gcmd.get("SESSION") != self.material.session_id:
            raise gcmd.error("Printer session changed; reopen the nozzle editor")
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        heater = "extruder" + (str(head) if head else "")
        if self.material.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        request = gcmd.get("ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", request):
            raise gcmd.error("Invalid nozzle request ID")
        result = {"id": request, "session": self.material.session_id, "head": "h%d" % head}
        try:
            diameter = float(gcmd.get("DIAMETER"))
            material = gcmd.get_int("MATERIAL", minval=0, maxval=1)
            live = self._nozzle_runtime.supported(heater)
            if live:
                self._nozzle_runtime.prepare(heater, diameter)
            heads, revision = self.material._nozzles.save(head, diameter, wmp_nozzles.MATERIALS[material], gcmd.get("EXPECT"))
            if live:
                self._nozzle_runtime.committed(heater, diameter, now)
            result.update(state="complete", values=heads["h%d" % head], revision=revision)
            self.nozzle_save = result
            gcmd.respond_info("Nozzle settings saved" + ("; diameter not applied: " + self._nozzle_runtime.errors[heater] if heater in self._nozzle_runtime.errors else "; diameter will apply when idle" if heater in self._nozzle_runtime.pending else ""))
        except (OSError, ValueError) as error:
            result.update(state="failed", message=str(error))
            self.nozzle_save = result
            raise gcmd.error(str(error))


    def _legacy_profiles(self):
        if any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
            return {}
        def read_variables():
            saved = self.material.printer.lookup_object("save_variables", None)
            return saved.get_status(self.material.printer.get_reactor().monotonic()).get("variables", {}) if saved else {}
        return wmp_filament_profiles.read_legacy(getattr(self.material, "ini_path", None), read_variables)


    @_status_observation
    def _profiles(self):
        # Polling is a read of the loaded profile, not a reload operation.
        # Explicit command admission still re-reads disk before comparing its
        # revision. Supported saves publish the new snapshot after commit.
        snapshot = getattr(self, '_status_profiles_snapshot', None)
        if getattr(self.material, '_status_observation_cache', None) is not None and snapshot is not None:
            # The observation decorator makes the caller's isolated copy.
            return snapshot
        try:
            result = self._read_profiles()
        except Exception:
            self._status_profiles_snapshot = None
            raise
        self._status_profiles_snapshot = copy.deepcopy(result)
        return result


    def _profile_storage(self):
        storage = getattr(self, "_profile_store", None)
        if storage is None or storage.path != self.material.profile_path:
            storage = self._profile_store = wmp_filament_profiles.ProfileStore(self.material.profile_path)
        return storage


    def _read_profiles(self):
        storage = self._profile_storage()
        result = storage.read(self._legacy_profiles, self.material._validate_identity)
        self._profiles_raw = copy.deepcopy(storage.raw)
        self._profile_entry_errors = copy.deepcopy(storage.errors)
        return result


    @_status_observation
    def _identification_pending(self, now):
        recovery = self.material.printer.lookup_object("wmp_recovery", None)
        if recovery is None:
            return False
        try:
            return recovery.get_status(now).get("identification", {}).get("state", "idle") in ("pending", "running")
        except (AttributeError, KeyError, TypeError, ValueError):
            return True


    def _idle_for_filament_settings(self, now, allow_invalid_recovery=False):
        # Availability callers stay silent; command boundaries append this
        # bounded observation when the same admission check refuses a request.
        self._idle_settings_refusal = ''
        def refuse(reason):
            self._idle_settings_refusal = reason[:256]
            return False
        if self.material._print_cancel_active(): return refuse('print cancellation is unresolved')
        if self.material._recovery_attempt_active():
            return refuse('power-loss recovery attempt is unresolved')
        # A completed print_stats state does not overrule pause or SD ownership.
        try:
            if self._identification_pending(now):
                return refuse('head identification is pending or its status is unavailable')
            stats = self.material.printer.lookup_object("print_stats", None).get_status(now)
            pause = self.material.printer.lookup_object("pause_resume", None).get_status(now)
            sd = self.material.printer.lookup_object("virtual_sdcard", None)
            stopped = ("standby", "complete", "cancelled")
            if not any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC")):
                stopped += ("error",)
            if stats.get("state") not in stopped:
                return refuse('print_stats.state=' + repr(stats.get('state'))[:80])
            if pause.get("is_paused") is not False:
                return refuse('pause_resume.is_paused=' + repr(pause.get('is_paused'))[:80])
            active = sd.is_active()
            if active is not False: return refuse('virtual_sdcard.is_active=' + repr(active)[:80])
            from_sd = sd.is_cmd_from_sd()
            if from_sd is not False: return refuse('virtual_sdcard.is_cmd_from_sd=' + repr(from_sd)[:80])
            return True
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            return refuse('idle status evidence unavailable: ' + type(error).__name__ + ': ' + str(error)[:160])


    @staticmethod
    def _filament_recipe(identity):
        """Physical recipe comparison; labels never establish spool changes."""
        return {key: copy.deepcopy(value) for key, value in identity.items()
                if key not in ("brand", "color", "appearance")}


    @classmethod
    def _loaded_source_matches(cls, current, saved):
        if (current.get("state") != "loaded" or current.get("source") != saved.get("source")
                or not isinstance(current.get("identity"), dict)
                or not isinstance(saved.get("identity"), dict)):
            return False
        cls._validate_identity(current["identity"])
        cls._validate_identity(saved["identity"])
        return cls._filament_recipe(current["identity"]) == cls._filament_recipe(saved["identity"])


    def _profile_recipes(self, heads=None):
        profiles = self._profiles()[0]
        selected = profiles if heads is None else heads
        return {head: self._filament_recipe(profiles[head]) if head in profiles else None
                for head in selected}


    @staticmethod
    def _usage_file_identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


    def _usage_mapping(self, now):
        values = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        maps = tuple(tuple(values.get("box_modify_t%d%s" % (i, suffix)) for i in range(4))
                     for suffix in ("", "_backup"))
        if any(type(h) is not int or h not in range(4) for row in maps for h in row):
            raise ValueError("Complete current and saved tool mapping is unavailable")
        return maps


    def _usage_macros(self, now):
        settings = wmp_nozzle_runtime.active_settings(self.material.printer,
                self.material.printer.lookup_object("configfile").get_status(now)["settings"])
        return {name: settings.get('gcode_macro ' + name.lower(), {}).get('gcode')
                for name in wmp_recovery_file_envelope.MACROS}


    def _begin_usage_scan(self, path):
        self._recipe_usage_observation = None
        try:
            now = self.material.printer.get_reactor().monotonic()
            return {"scanner": wmp_recovery_file_envelope.ToolUsage(),
                    "session": self.material.session_id, "path": os.path.realpath(path),
                    "identity": self._usage_file_identity(os.stat(path)),
                    "mapping": self._usage_mapping(now), "proof": self.material._recovery_file_effect_contract(),
                    "macros": self._usage_macros(now)}
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_error = str(error)
            return None


    def _finish_usage_scan(self, scan, digest, stream=None):
        if scan is None: return
        try:
            now = self.material.printer.get_reactor().monotonic()
            tools = scan["scanner"].complete()
            if (self.material.session_id != scan["session"]
                    or self._usage_mapping(now) != scan["mapping"]
                    or self._usage_macros(now) != scan["macros"]
                    or self._usage_file_identity(os.stat(scan["path"])) != scan["identity"]):
                raise ValueError("File, macro effects or tool mapping changed during usage scan")
            if stream is not None and self._usage_file_identity(os.fstat(stream.fileno())) != scan["identity"]:
                raise ValueError("Active SD stream differs from scanned file")
            self._recipe_usage_observation = {key: value for key, value in scan.items() if key != "scanner"}
            self._recipe_usage_observation.update(tools=tuple(tools), sha256=digest, stream=stream)
            self._recipe_usage_error = ""
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_observation = None
            self._recipe_usage_error = str(error)


    def _bind_usage_stream(self):
        """Bind a pre-dispatch scan to the actual opened SD file, never by name alone."""
        observed = getattr(self, "_recipe_usage_observation", None)
        if not observed or observed.get("stream") is not None: return
        try:
            stream = self.material.printer.lookup_object("virtual_sdcard").current_file
            if (stream is None or stream.closed or os.path.realpath(stream.name) != observed["path"]
                    or self._usage_file_identity(os.fstat(stream.fileno())) != observed["identity"]
                    or self._usage_file_identity(os.stat(observed["path"])) != observed["identity"]):
                raise ValueError("Opened SD file differs from admitted usage scan")
            observed["stream"] = stream
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_observation = None
            self._recipe_usage_error = str(error)


    def _active_recipe_heads(self, now, check_file=False):
        """No filesystem operations during status; final Save checks file identity."""
        observed = getattr(self, "_recipe_usage_observation", None)
        try:
            if not observed: raise ValueError(getattr(self, "_recipe_usage_error", "Complete active-job head usage is unavailable"))
            stream = self.material.printer.lookup_object("virtual_sdcard").current_file
            if (stream is None or stream.closed or stream is not observed["stream"]
                    or observed["session"] != self.material.session_id
                    or self._usage_mapping(now) != observed["mapping"]
                    or self._usage_macros(now) != observed["macros"]):
                raise ValueError("Active file, session, mapping or macro effects changed")
            if check_file and (self._usage_file_identity(os.fstat(stream.fileno())) != observed["identity"]
                    or self._usage_file_identity(os.stat(observed["path"])) != observed["identity"]):
                raise ValueError("Active print file changed since tool usage was established")
            return {"h%d" % observed["mapping"][0][tool] for tool in observed["tools"]}
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as error:
            self._recipe_usage_error = str(error)
            return None


    def _unused_recipe_head(self, head, now, check_file=False):
        if self.material._print_cancel_active() or self.material._recovery_attempt_active(): return False
        used = self._active_recipe_heads(now, check_file)
        return used is not None and "h%d" % head not in used


    def _recipe_write_status(self, now):
        result = {}
        identifying = self._identification_pending(now)
        idle = self._idle_for_filament_settings(now)
        active = self.material._material_operation_active("filament_operation")
        affected = getattr(self.material, "filament_operation", {}).get("head")
        used = self._active_recipe_heads(now) if not idle else None
        for head in range(4):
            key = "h%d" % head
            allowed = (not identifying and not (active and (affected == key or affected not in ('h0','h1','h2','h3')))
                       and (idle or (not self.material._print_cancel_active() and not self.material._recovery_attempt_active()
                                     and used is not None and key not in used)))
            reason = ("Head identification is running" if identifying else
                      "Active filament service uses this head or its head is unknown" if active and (affected == key or affected not in ('h0','h1','h2','h3')) else
                      "Print cancellation is running" if self.material._print_cancel_active() else
                      "Print recovery is running" if self.material._recovery_attempt_active() else
                      "This print uses this head; use the paused empty-head editor" if used is not None and key in used else
                      getattr(self, "_recipe_usage_error", "Active-job head usage is unavailable"))
            result[key] = {"allowed": bool(allowed), "reason": "" if allowed else reason}
        return result


    def cmd_SET_FILAMENT(self, gcmd):
        if self._identification_pending(self.material.printer.get_reactor().monotonic()):
            raise gcmd.error("Resolve head identification before editing filament")
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another manager owns filament settings")
        eventtime = self.material.printer.get_reactor().monotonic()
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.material.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        try:
            encoded = gcmd.get("PROFILE")
            if len(encoded) > 1024 or not re.fullmatch(r"[0-9a-fA-F]+", encoded):
                raise ValueError("Invalid encoded filament settings")
            identity = json.loads(bytes.fromhex(encoded).decode("utf-8"))
            self.material._validate_identity(identity)
            profiles, revision = self._profiles()
            if gcmd.get("EXPECT") != revision:
                raise ValueError("Filament settings changed; refresh before saving")
            previous = profiles.get("h%d" % head)
            cosmetic = (previous is not None and
                        self._filament_recipe(previous) == self._filament_recipe(identity))
            if not cosmetic:
                if self.material._material_operation_active("filament_operation"):
                    active_head = self.material.filament_operation.get("head")
                    if active_head not in ("h0", "h1", "h2", "h3"):
                        raise gcmd.error("Cannot establish which head the active filament operation uses; wait for it to finish before changing the recipe")
                    if active_head == "h%d" % head:
                        raise gcmd.error("Head %d has an active filament operation; wait before changing its recipe" % (head + 1))
                pause_token = gcmd.get("PAUSE", None)
                if self._unused_recipe_head(head, eventtime, check_file=True):
                    pass
                elif self._idle_for_filament_settings(eventtime):
                    if pause_token is not None:
                        raise gcmd.error("Paused edit expired; refresh before saving")
                else:
                    if pause_token is None:
                        reason = (self._recipe_write_status(eventtime)["h%d" % head]["reason"]
                                  or getattr(self, "_recipe_usage_error", "Active-job file binding changed"))
                        raise gcmd.error("Filament recipe Save requires idle, an unused active-job head or the paused-head editor: " + reason)
                    try:
                        origin = self.material._paused_filament_origin(head, eventtime)
                        if pause_token != origin["id"]:
                            raise ValueError("Paused edit context changed")
                        if not self.material._paused_filament_status(eventtime).get("available"):
                            raise ValueError("Paused head attachment changed")
                        if self.material._loaded_filament_status(eventtime).get("h%d" % head, {}).get("state") != "empty":
                            raise ValueError("Unload the paused head before changing filament settings")
                    except (AttributeError, KeyError, TypeError, ValueError) as error:
                        raise gcmd.error(str(error))
            profiles = copy.deepcopy(getattr(self, "_profiles_raw", profiles))
            profiles["h%d" % head] = identity
            self._status_profiles_snapshot = None
            self._profile_storage().write(profiles)
            self._status_profiles_snapshot = None
            self._profiles()
        except (ValueError, OSError, UnicodeError) as error:
            raise gcmd.error(str(error))
        gcmd.respond_info("Filament settings saved for head %d" % (head + 1))


