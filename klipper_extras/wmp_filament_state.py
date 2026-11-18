# SPDX-License-Identifier: GPL-3.0-or-later
"""Filament sensors, runout notifications and loaded/material-history state."""
import copy
import json
import logging
import os
import uuid

try:
    from .wmp_persistence import atomic_write
    from .wmp_observation import _status_observation
except ImportError:
    from wmp_persistence import atomic_write
    from wmp_observation import _status_observation

class FilamentState:
    def __init__(self, material):
        self.material = material

    def _clear_filament_checks(self, *args):
        self.material._toolchange_pause = None
        if getattr(self.material, "_pause_origin", None) and self.material._pause_origin.get("kind") == "toolchange":
            self.material._pause_origin = None
        self._filament_checks.clear()
        self.material._recovery_release_paused_worker()


    def _filament_sensors_ready(self):
        # Match Klipper RunoutHelper's initial two-second settling window.
        self._filament_sensors_ready_at = self.material.printer.get_reactor().monotonic() + 2.
        self._guard_filament_notifications()


    def _runout_owned(self):
        # Claim the native detector only after all factory sensor paths are
        # guarded. An unsupported/missing helper retains factory protection.
        if any(self.material.printer.lookup_object(owner, None) is not None
               for owner in ("openace", "AFC")):
            return False
        guarded = getattr(self, "_guarded_filament_notifications", set())
        return all(name in guarded for head in range(4)
                   for name in ("filament%d" % head, "path_%d" % head))

    def _guard_filament_notifications(self):
        # The vendor emits its error before checking whether a print needs this
        # sensor. Guard only that notification, not sensor updates or callbacks.
        guarded = getattr(self, "_guarded_filament_notifications", set())
        self._guarded_filament_notifications = guarded
        for head in range(4):
            for name in ("filament%d" % head, "path_%d" % head):
                sensor = self.material.printer.lookup_object("filament_switch_sensor " + name, None)
                helper = getattr(sensor, "runout_helper", None)
                original = getattr(helper, "_respond_runout_error", None)
                if not callable(original) or name in guarded:
                    continue
                def notify(original=original, head=head, name=name):
                    if any(self.material.printer.lookup_object(owner, None) is not None
                           for owner in ("openace", "AFC")):
                        return original()
                    now = self.material.printer.get_reactor().monotonic()
                    stats = self.material.printer.lookup_object("print_stats").get_status(now)
                    pause = self.material.printer.lookup_object("pause_resume").get_status(now)
                    if stats.get("state") == "printing" and self._runout_pause_needed(pause):
                        attachment = self.material._attachment(now)
                        if attachment == {"state": "attached", "head": "h%d" % head}:
                            # Factory ZRU errors also activate the touchscreen's
                            # independent pause/recovery path. The guarded sensor
                            # callback below owns pausing; publish plain guidance.
                            self.material.printer.lookup_object("gcode").respond_info(
                                "%s on Head %d; checking filament." % (
                                    "Filament path blocked" if name.startswith("path_")
                                    else "Filament not detected", head + 1))
                            return
                        if attachment.get("state") == "unknown":
                            # Report the actual sensor without inventing which
                            # head is attached or changing pause admission.
                            self.material.printer.lookup_object("gcode").respond_info(
                                "Filament sensor %s reported empty; attached head is unknown. "
                                "Check head attachment and filament." % name)
                helper._respond_runout_error = notify
                # Path sensors use the vendor's immediate pause callback. Unlike
                # filament runout macros, it does not recheck the required head.
                event = getattr(helper, "_runout_event_handler", None)
                if name.startswith("path_") and callable(event):
                    def path_event(eventtime, original=event, helper=helper, head=head):
                        if any(self.material.printer.lookup_object(owner, None) is not None
                               for owner in ("openace", "AFC")):
                            return original(eventtime)
                        now = self.material.printer.get_reactor().monotonic()
                        stats = self.material.printer.lookup_object("print_stats").get_status(now)
                        pause = self.material.printer.lookup_object("pause_resume").get_status(now)
                        if (helper.sensor_enabled and not helper.filament_present
                                and stats.get("state") == "printing" and self._runout_pause_needed(pause)
                                and self.material._attachment(now) == {"state": "attached", "head": "h%d" % head}):
                            return original(eventtime)
                        # note_filament_present set NEVER when it queued this
                        # callback. Release that gate even when no pause is due.
                        helper.min_event_systime = now + helper.event_delay
                        if helper.sensor_enabled and not helper.filament_present and stats.get("state") == "printing":
                            self._defer_path_runout(helper, head, original)
                    helper._runout_event_handler = path_event
                guarded.add(name)


    def _runout_pause_needed(self, pause):
        if pause.get("is_paused") is False:
            return True
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        return sd is not None and sd.is_active()


    def _defer_path_runout(self, helper, head, original):
        """Retain a tangle across a transient head change, scoped to this file."""
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        stream = getattr(sd, "current_file", None)
        if stream is None or stream.closed:
            return
        reactor = self.material.printer.get_reactor()
        pending = getattr(self, "_deferred_path_runouts", {})
        self._deferred_path_runouts = pending
        if pending.get(head) is stream:
            return
        pending[head] = stream
        def retry(now):
            if pending.get(head) is not stream:
                return reactor.NEVER
            stats = self.material.printer.lookup_object("print_stats").get_status(now)
            pause = self.material.printer.lookup_object("pause_resume").get_status(now)
            if (getattr(sd, "current_file", None) is not stream or stream.closed
                    or not helper.sensor_enabled or helper.filament_present
                    or stats.get("state") != "printing"
                    or any(self.material.printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))):
                pending.pop(head, None)
                return reactor.NEVER
            if self._runout_pause_needed(pause) and self.material._attachment(now) == {"state": "attached", "head": "h%d" % head}:
                pending.pop(head, None)
                original(now)
                return reactor.NEVER
            return now + .25
        reactor.register_timer(retry, reactor.monotonic() + .25)


    def _filament_sensors_unavailable(self):
        self._filament_sensors_ready_at = float("inf")
        self.material._pending_execution_snapshot = None


    @_status_observation
    def _hotend_material_history(self):
        self._hotend_history_error = ""
        try:
            return self._read_hotend_material_history()
        except (ValueError, UnicodeError, OSError) as error:
            self._hotend_history_error = "Hotend history unavailable; residue is unknown: " + str(error)
            return {}


    def _read_hotend_material_history(self):
        """Residual material history, independent of presence and spool edits.

        Missing history is unknown, never inferred from current spool settings.
        Corrupt history is preserved by the writer; readers use unknown residue.
        """
        path = os.path.join(os.path.dirname(self.material.profile_path), "wmp_hotend_materials.json")
        try:
            with open(path, encoding="utf-8") as stream:
                text = stream.read(32769)
            if len(text) > 32768:
                raise ValueError("Hotend material history is too large")
            data = json.loads(text)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or set(data) != {"version", "heads"} or data["version"] != 1:
            raise ValueError("Invalid hotend material history")
        heads = data["heads"]
        if not isinstance(heads, dict):
            raise ValueError("Invalid hotend material heads")
        for head, record in heads.items():
            if head not in ("h0", "h1", "h2", "h3") or not isinstance(record, dict):
                raise ValueError("Invalid hotend material head")
            if (set(record) != {"state", "materials", "unknown_residue"}
                    or record["state"] not in ("mixed", "purged")
                    or type(record["unknown_residue"]) is not bool
                    or not isinstance(record["materials"], list)
                    or not 1 <= len(record["materials"]) <= 8):
                raise ValueError("Invalid hotend material record")
            if record["state"] == "purged" and (len(record["materials"]) != 1 or record["unknown_residue"]):
                raise ValueError("Invalid purged hotend material record")
            for identity in record["materials"]:
                self.material._validate_identity(identity)
        return heads


    def _record_hotend_material(self, head, identity, purged):
        if head not in ("h0", "h1", "h2", "h3"):
            raise ValueError("Invalid hotend material head")
        self.material._validate_identity(identity)
        heads = self._hotend_material_history()
        previous = heads.get(head)
        materials = copy.deepcopy(previous["materials"]) if previous and not purged else []
        unknown = not purged and (previous is None or previous["unknown_residue"])
        if identity not in materials:
            materials.append(copy.deepcopy(identity))
        if len(materials) > 8:
            materials = materials[-8:]
            unknown = True
        heads[head] = {"state": "purged" if purged else "mixed",
                       "materials": materials, "unknown_residue": unknown}
        parent = os.path.dirname(self.material.profile_path)
        path = os.path.join(parent, "wmp_hotend_materials.json")
        if getattr(self, "_hotend_history_error", ""):
            # Only a deliberate material operation may replace bad history.
            # Preserve the exact inode bytes before atomic replacement; reads
            # never repair files. If preservation is impossible, retain unknown
            # history rather than destroying evidence or blocking the printer.
            try:
                os.link(path, path + ".invalid-" + uuid.uuid4().hex)
            except OSError as error:
                logging.warning("Hotend history was not updated: cannot preserve original: %s", error)
                return
        atomic_write(path, json.dumps({"version": 1, "heads": heads}), ".wmp-hotend-")


    def _load_filament_flags(self):
        if not hasattr(self, "_loaded_flags"):
            path = os.path.join(os.path.dirname(self.material.profile_path), "wmp_filament_loaded.json")
            try:
                with open(path) as stream:
                    values = json.load(stream)
                self._loaded_flags = {"h%d" % i: values.get("h%d" % i) is True for i in range(4)}
            except (OSError, ValueError, AttributeError):
                self._loaded_flags = {}
        return self._loaded_flags


    def _set_filament_loaded(self, head, loaded):
        self._presence_adopted = True  # An explicit load/unload supersedes migration.
        flags = dict(self._load_filament_flags())
        if flags.get(head, False) == loaded:
            return
        flags[head] = loaded
        self._persist_filament_flags(flags)


    def _persist_filament_flags(self, flags):
        try:
            self._write_filament_flags(flags)
            self._filament_presence_error = ""
        except OSError as error:
            # Presence is a current observation even when optional persistence
            # fails. Do not retry the same write from every status publication.
            self._loaded_flags = dict(flags)
            message = str(error)[:256]
            if getattr(self, "_filament_presence_error", "") != message:
                logging.warning("Filament presence persistence unavailable: %s", message)
            self._filament_presence_error = message


    def _write_filament_flags(self, flags):
        parent = os.path.dirname(self.material.profile_path)
        path = os.path.join(parent, "wmp_filament_loaded.json")
        atomic_write(path, json.dumps(flags), ".wmp-loaded-")
        self._loaded_flags = flags


    def _job_filament_losses(self, current_file):
        loss = getattr(self, "_filament_loss_job", None)
        if loss and loss["file"] is current_file and not current_file.closed:
            return set(loss["heads"])
        return set()


    def _record_job_filament_loss(self, head, eventtime):
        # An inlet transition clears the loaded flag permanently. Retain which
        # head lost its confirmed load even if a queued tool change finishes
        # before PAUSE captures the mounted head. Bind to the open file object,
        # never a reusable filename, and never infer a reload from reinsertion.
        if self.material.printer.lookup_object("openace", None) is not None:
            return
        stats = self.material.printer.lookup_object("print_stats", None)
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if stats is None or sd is None:
            return
        current_file = getattr(sd, "current_file", None)
        if (stats.get_status(eventtime).get("state") not in ("printing", "paused")
                or current_file is None or current_file.closed):
            return
        heads = self._job_filament_losses(current_file) | {head}
        self._filament_loss_job = {"file": current_file, "heads": heads}
        origin = getattr(self.material, "_pause_origin", None)
        if origin and origin["file"] is current_file and origin["session"] == self.material.session_id:
            origin["filament_required"] = sorted(set(origin.get("filament_required", [])) | heads)


    @_status_observation
    def _loaded_filament_status(self, eventtime):
        records = self._sensor_filament_status(eventtime)
        # First-install adoption only. Once WM+ has saved presence (including
        # all-empty), reinsertion must never silently become a completed load.
        loaded_path = os.path.join(os.path.dirname(self.material.profile_path), "wmp_filament_loaded.json")
        if (not os.path.exists(loaded_path) and not getattr(self, "_presence_adopted", False)
                and self.material._idle_for_filament_settings(eventtime)
                and not any(getattr(self.material, name, {}).get("state") in ("running", "unknown")
                            for name in ("filament_operation", "toolhead_operation"))):
            try:
                # Reuse the loaded catalogue or stock projection. An existing
                # catalogue does not mean presence migration already happened.
                legacy, _ = self.material._profiles()
            except (OSError, ValueError):
                legacy = {}
            if legacy and all(records[head]["state"] in ("loaded", "empty") for head in legacy):
                self._persist_filament_flags({head: head in legacy and record["state"] == "loaded"
                                              for head, record in records.items()})
                self._presence_adopted = True
        empty_since = getattr(self, "_filament_empty_since", {})
        self._filament_empty_since = empty_since
        for head, record in records.items():
            present = record["state"] == "loaded"
            record["sensor_present"] = present if record["state"] != "unknown" else None
            if record["state"] == "empty":
                sd = self.material.printer.lookup_object("virtual_sdcard", None)
                stream = getattr(sd, "current_file", None)
                began, job = empty_since.setdefault(head, (eventtime, stream))
                if job is not stream:
                    began = eventtime
                    empty_since[head] = (began, stream)
                if eventtime - began >= .25:
                    if self._load_filament_flags().get(head, False):
                        self._record_job_filament_loss(head, eventtime)
                    self._set_filament_loaded(head, False)
            else:
                empty_since.pop(head, None)
                if present and not self._load_filament_flags().get(head, False):
                    record["state"] = "empty"
                    record.pop("identity", None)
                    record.pop("source", None)
        return records


    @_status_observation
    def _sensor_filament_status(self, eventtime):
        """Physical presence is live evidence, independent of saved/operator state.

        enabled controls runout handling, not whether the switch is readable.
        Metadata describes the configured spool; it cannot prove its identity.
        """
        try:
            profiles, _ = self.material._profiles()
        except (ValueError, OSError):
            profiles = {}
        result = {}
        for i in range(4):
            sensor = self.material.printer.lookup_object("filament_switch_sensor filament%d" % i, None)
            observed = sensor.get_status(eventtime) if sensor is not None else {}
            detected = observed.get("filament_detected")
            if eventtime < getattr(self, "_filament_sensors_ready_at", 0.):
                detected = None
            key = "h%d" % i
            record = {"state": "unknown", "evidence": "sensor", "session": self.material.session_id}
            if type(detected) is bool:
                record["state"] = "loaded" if detected else "empty"
                if detected:
                    record.update(source="external:" + key, identity=dict(profiles.get(key, {})))
            result[key] = record
        return result


    def _filament_check_context(self, head, now):
        """A check records current evidence; it never runs a filament procedure."""
        self.material._require_no_recovery_attempt()
        if self.material._identification_pending(now):
            raise ValueError("Wait for the running head identification before checking filament")
        if any(getattr(self.material, name, {}).get("state") in ("pending", "running")
               for name in ("filament_operation", "toolhead_operation")):
            raise ValueError("Wait for the running filament or toolhead operation before checking filament")
        if self.material._idle_for_filament_settings(now):
            return
        # Permit a stopped paused job's original/affected head. This validates
        # the current pause, not a historic load/unload receipt.
        self.material._paused_filament_origin(head, now)


    def _filament_status(self, eventtime):
        checks = self._filament_checks
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            checks.clear()
        for head, record in list(checks.items()):
            try:
                self._filament_check_context(int(head[1]), eventtime)
            except (AttributeError, KeyError, TypeError, ValueError):
                del checks[head]
                continue
            sensor = self.material.printer.lookup_object("filament_switch_sensor filament%d" % int(head[1]), None)
            observed = sensor.get_status(eventtime) if sensor is not None else {}
            # enabled controls runout handling, not switch readability.
            if observed.get("filament_detected") is not (record["state"] == "loaded"):
                del checks[head]
        return {head: dict(record) for head, record in checks.items()}


    def cmd_FORGET_FILAMENT(self, gcmd):
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        self._filament_checks.pop("h%d" % head, None)


    def cmd_CONFIRM_FILAMENT(self, gcmd):
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            raise gcmd.error("Another manager owns filament evidence")
        now = self.material.printer.get_reactor().monotonic()
        head = gcmd.get_int("HEAD", minval=0, maxval=3)
        try:
            self._filament_check_context(head, now)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise gcmd.error("Filament check requires idle or a fully paused affected head: " + str(error))
        key = "h%d" % head
        heater = "extruder" if head == 0 else "extruder%d" % head
        if self.material.printer.lookup_object(heater, None) is None:
            raise gcmd.error("Physical head is not installed")
        state = gcmd.get("STATE")
        if state not in ("loaded", "empty") or gcmd.get("SESSION") != self.material.session_id:
            raise gcmd.error("Invalid filament check or stale printer session")
        try:
            profiles, revision = self.material._profiles()
            if gcmd.get("EXPECT") != revision or key not in profiles:
                raise ValueError("Filament settings changed or are missing; refresh before confirming")
        except (ValueError, OSError) as error:
            raise gcmd.error(str(error))
        sensor = self.material.printer.lookup_object("filament_switch_sensor filament%d" % head, None)
        observed = sensor.get_status(now) if sensor is not None else {}
        if (now < getattr(self, "_filament_sensors_ready_at", 0.)
                or observed.get("filament_detected") is not (state == "loaded")):
            raise gcmd.error("The head sensor disagrees or is unavailable; check the filament first")
        # This is explicitly an operator assertion backed by sensor consistency,
        # not an automatic claim that commanded extrusion reached the nozzle.
        record = {"state": state, "evidence": "operator", "session": self.material.session_id}
        if state == "loaded":
            record.update(source="external:" + key, identity=dict(profiles[key]))
        self._set_filament_loaded(key, state == "loaded")
        self._filament_checks[key] = record
        gcmd.respond_info("Recorded operator filament check for head %d" % (head + 1))


