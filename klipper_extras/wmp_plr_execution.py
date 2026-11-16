# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery execution sampling and deposition evidence.

Owns sampler timers, cached execution state and deposition observation. The
coordinator supplies live printer state and other PLR lifecycle services."""
import copy
import hashlib
import json
import logging
import math
import os
import re

try:
    from .wmp_plr_records import RecoveryDepositionEnvelope
except ImportError:
    from wmp_plr_records import RecoveryDepositionEnvelope

class ExecutionEvidence:
    def __init__(self, material):
        self.material = material

    def _deposition_envelope_path(self, for_write=False):
        return self.material._recovery_runtime_path("wmp_recovery_envelope.json", for_write)


    def _disable_print_recovery(self, reason):
        """Retire optional job evidence without taking ownership of the printer."""
        self._print_recovery_error = str(reason)[:512]
        self.material._pending_recovery_submission = None
        self._deposition_envelope = None
        self._pending_execution_snapshot = None
        failures = []
        try:
            self.material._write_recovery_job({"version": 1, "state": "invalidated",
                                      "reason": self._print_recovery_error,
                                      "session": self.material.session_id})
        except (OSError, ValueError, AttributeError) as error:
            failures.append(str(error))
        # Delete and durably retire fallback bytes before removing runtime
        # authority. If the job write also failed, reversing this order could
        # expose an older legacy checkpoint after an unlink failure/power loss.
        legacy_dir = os.path.dirname(self.material.profile_path)
        runtime_dir = getattr(self.material, "recovery_checkpoint_dir", legacy_dir)
        names = ("wmp_recovery_execution.json", "wmp_recovery_envelope.json")
        def remove(path):
            try:
                os.unlink(path)
                return True
            except FileNotFoundError:
                return True
            except OSError as error:
                failures.append(str(error))
                return False
        def sync(parent):
            try:
                directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return True
            except OSError as error:
                failures.append(str(error))
                return False
        if os.path.abspath(legacy_dir) != os.path.abspath(runtime_dir):
            removed = {name: remove(os.path.join(legacy_dir, name)) for name in names}
            legacy_synced = sync(legacy_dir)
            for name in names:
                if removed[name] and legacy_synced:
                    remove(os.path.join(runtime_dir, name))
        else:
            for name in names:
                remove(os.path.join(runtime_dir, name))
        sync(runtime_dir)
        self._recovery_invalidation_error = "; ".join(failures)[:512]
        logging.warning("Power-loss recovery disabled for current job: %s%s",
                        self._print_recovery_error,
                        "; evidence invalidation: " + self._recovery_invalidation_error if failures else "")


    def _install_deposition_observer(self):
        toolhead = self.material.printer.lookup_object("toolhead")
        queue = getattr(toolhead, "lookahead", None)
        if queue is None or not callable(getattr(queue, "add_move", None)):
            return False
        installed = getattr(self, "_deposition_queue_hook", None)
        if installed is not None:
            if queue.add_move is not installed:
                raise ValueError("Recovery deposition observer was replaced")
            return True
        original = queue.add_move
        def enqueue(move):
            envelope = getattr(self, "_deposition_envelope", None)
            if envelope is not None:
                try:
                    if (self.material.session_id != self._deposition_session
                            or self.material.printer.lookup_object("openace", None) is not None
                            or self.material.printer.lookup_object("AFC", None) is not None):
                        raise ValueError("Deposition recording lost standalone ownership")
                    envelope.observe(move)
                except Exception as error:
                    # The vendor already advanced commanded_pos. Optional
                    # recording must never suppress this validated move.
                    self._disable_print_recovery("Deposition evidence failed: " + str(error))
            # Submission is deliberately outside the evidence exception handler:
            # a genuine queue error propagates, and is never retried.
            return original(move)
        self._deposition_queue_hook = enqueue
        self._deposition_queue = queue
        queue.add_move = enqueue
        return True


    def _verify_deposition_observer(self, envelope, record):
        queue = getattr(self.material.printer.lookup_object("toolhead"), "lookahead", None)
        if (envelope is not getattr(self, "_deposition_envelope", None)
                or envelope.failed or envelope.record != record
                or getattr(self, "_deposition_session", None) != self.material.session_id
                or queue is not getattr(self, "_deposition_queue", None)
                or queue is None or queue.add_move is not getattr(self, "_deposition_queue_hook", None)):
            raise ValueError("Recovery deposition observer lost its admitted binding")


    def _begin_deposition_envelope(self, record, restored=None):
        if (not self._install_deposition_observer()
                or self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None):
            self._deposition_envelope = None
            return False
        self._deposition_envelope = RecoveryDepositionEnvelope(
            lambda value: self.material._write_recovery_json(self._deposition_envelope_path(for_write=True), value),
            record["id"], record["file"]["sha256"], restored)
        self._deposition_session = self.material.session_id
        return True


    def _execution_ready(self):
        self._install_deposition_observer()
        reactor = self.material.printer.get_reactor()
        self._execution_stopped = False
        if getattr(self, "_execution_timer", None) is None:
            self._execution_timer = reactor.register_timer(self._execution_tick, reactor.monotonic() + 1.)
        else:
            reactor.update_timer(self._execution_timer, reactor.monotonic() + 1.)


    def _execution_stop(self, *args):
        self._execution_stopped = True
        self._execution_state = "stopped"
        self._pending_execution_snapshot = None
        if getattr(self, "_execution_timer", None) is not None:
            reactor = self.material.printer.get_reactor()
            reactor.update_timer(self._execution_timer, reactor.NEVER)


    def _execution_sd_boundary(self):
        """Bind the outer SD dispatch before it runs; never bind a nested call."""
        try:
            sd = self.material.printer.lookup_object("virtual_sdcard")
            if (self.material.printer.lookup_object("gcode").get_mutex().test()
                    or not sd.is_active() or not sd.is_cmd_from_sd()
                    or sd.current_file is None or sd.current_file.closed
                    or type(sd.file_position) is not int
                    or type(sd.next_file_position) is not int
                    or sd.next_file_position <= sd.file_position):
                return None
            return (sd, sd.current_file, sd.file_position, sd.next_file_position, self.material.session_id)
        except (AttributeError, KeyError, TypeError):
            return None


    def _execution_sample_batch(self, boundary=None):
        # This publication/capture pair is synchronous: share live observations
        # only for this batch and reuse the save-invalidated loaded profiles.
        # Command admission still calls _profiles outside this observation scope.
        previous = getattr(self.material, "_status_observation_cache", None)
        self.material._status_observation_cache = {}
        try:
            self._publish_recovery_execution()
            self._queue_recovery_execution(boundary)
        finally:
            self.material._status_observation_cache = previous


    def _execution_command_completed(self, boundary):
        # run_script has returned successfully and released its mutex, but the
        # retained SD worker has not yet advanced file_position. No yield here.
        if (getattr(self, "_execution_stopped", True)
                or getattr(self, "_print_recovery_error", "")):
            return
        try:
            if self._execution_sd_boundary() != boundary:
                raise ValueError("Completed SD command binding changed")
            now = self.material.printer.get_reactor().monotonic()
            if now < getattr(self, "_execution_next_capture_time", 0.):
                return
            self._execution_next_capture_time = now + 1.
            self._execution_sample_batch(boundary)
            self._execution_error = ""
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            self._pending_execution_snapshot = None
            self._execution_state = "refused"
            self._execution_error = str(error)


    def _execution_tick(self, eventtime):
        reactor = self.material.printer.get_reactor()
        if self._execution_stopped:
            self._execution_state = "stopped"
            return reactor.NEVER
        if getattr(self, "_print_recovery_error", ""):
            self._execution_state = "unavailable"
            self._execution_error = self._print_recovery_error
            return eventtime + 1.
        try:
            sd = self.material.printer.lookup_object("virtual_sdcard", None)
            if (sd is None or not sd.is_active()
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None):
                self._pending_execution_snapshot = None
                self._execution_state = "inactive"
                return eventtime + 1.
            # Do not observe transient state partway through any command, even
            # one submitted externally rather than by the SD worker.
            if self.material.printer.lookup_object("gcode").get_mutex().test():
                self._execution_state = "command_busy"
                return eventtime + 1.
            self._execution_sample_batch()
            candidate = self._pending_execution_snapshot
            self._execution_state = ("observing" if candidate is None else
                "waiting_schedule" if candidate["scheduled_print_time"] is None else "waiting_motion")
            self._execution_error = ""
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            self._pending_execution_snapshot = None
            self._execution_state = "refused"
            self._execution_error = str(error)
        return eventtime + 1.


    @staticmethod
    def _execution_boundary(snapshot):
        return (snapshot["session"], snapshot["job_fingerprint"], snapshot["file_position"])


    def _recovery_mesh_fingerprint(self):
        """Bind the active interpolation grid, offsets and fade configuration."""
        mesh = self.material.printer.lookup_object("bed_mesh")
        status = mesh.get_status(self.material.printer.get_reactor().monotonic())
        grid = status.get("mesh_matrix")
        if (status.get("profile_name") != "wmp_print" or not isinstance(grid, (list, tuple))
                or not 2 <= len(grid) <= 256 or not isinstance(grid[0], (list, tuple))
                or not 2 <= len(grid[0]) <= 256
                or any(not isinstance(row, (list, tuple)) or len(row) != len(grid[0]) for row in grid)):
            raise ValueError("Recovery requires the active saved print mesh")
        active = mesh.get_mesh()
        parameters = [getattr(mesh, name, None) for name in
                      ("fade_start", "fade_end", "fade_dist", "fade_target", "tool_offset")]
        bounds = [status.get("mesh_min"), status.get("mesh_max"), getattr(active, "mesh_offsets", None)]
        if (any(not isinstance(v, (list, tuple)) or len(v) != 2 for v in bounds)
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in parameters + [v for pair in bounds for v in pair] + [v for row in grid for v in row])
                or any(bounds[0][i] >= bounds[1][i] for i in range(2))):
            raise ValueError("Invalid recovery mesh transform")
        canonical = [[[float(v) for v in row] for row in grid],
                     [[float(v) for v in pair] for pair in bounds], [float(v) for v in parameters]]
        payload = json.dumps(canonical, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(payload).hexdigest()


    def _restore_recovery_mesh(self, execution, guard):
        guard()
        gcode = self.material.printer.lookup_object("gcode")
        if not gcode.get_mutex().test():
            raise ValueError("Recovery mesh restore requires command ownership")
        offsets = execution["mesh_offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offsets)):
            raise ValueError("Invalid recovery mesh offsets")
        gcode.run_script_from_command("BED_MESH_PROFILE_BASE LOAD=wmp_print")
        guard()
        gcode.run_script_from_command("BED_MESH_OFFSET X=%.17g Y=%.17g ZFADE=%.17g" % tuple(offsets))
        guard()
        if self._recovery_mesh_fingerprint() != execution["mesh_fingerprint"]:
            raise ValueError("Saved recovery mesh transform changed")
        mesh = self.material.printer.lookup_object("bed_mesh")
        parser, machine = execution["parser_position"], execution["machine_position"]
        factor = mesh.get_z_factor(parser[2])
        correction = factor * mesh.get_mesh().calc_z(parser[0], parser[1]) + (1. - factor) * mesh.fade_target
        predicted = [parser[0], parser[1], parser[2] + correction]
        if (not math.isfinite(factor) or not 0 <= factor <= 1
                or any(not math.isfinite(v) or not math.isclose(v, actual, abs_tol=1e-5, rel_tol=0)
                       for v, actual in zip(predicted, machine[:3]))):
            raise ValueError("Recovery mesh does not reproduce the saved machine position")
        return True


    def _recovery_execution_snapshot(self, sd_boundary=None, queued_tail=None):
        """Capture parser/head state at a completed SD command boundary.

        No reactor yield or G-code dispatch is permitted in this reader. This is
        not proof that buffered physical motion completed and is not persisted
        or exposed as a recoverable checkpoint until that contract is resolved.
        """
        if self.material.printer.lookup_object("gcode").get_mutex().test():
            raise ValueError("G-code command prevents checkpoint capture")
        now = self.material.printer.get_reactor().monotonic()
        sd = self.material.printer.lookup_object("virtual_sdcard")
        if (self.material.printer.lookup_object("openace", None) is not None
                or self.material.printer.lookup_object("AFC", None) is not None
                or not sd.is_active()
                or (sd.is_cmd_from_sd() if sd_boundary is None
                    else self._execution_sd_boundary() != sd_boundary)
                or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                or self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False
                or self.material.printer.lookup_object("gcode_macro START_PRINT").get_status(now).get("print_body_ready") is not True):
            raise ValueError("No completed standalone print-command boundary")
        for name in ("filament_operation", "toolhead_operation"):
            if self.material._material_operation_active(name):
                raise ValueError("Service operation prevents checkpoint capture")
        job_bytes = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        record = json.loads(job_bytes)
        if record.get("state") != "committed" or record.get("owner") != "standalone":
            raise ValueError("No committed standalone job for checkpoint capture")
        if self.material._retire_changed_print_recovery(record=record):
            raise ValueError("Recovery evidence retired after print recipe changed")
        variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
        if (self.material._recovery_context(variables.get("wmp_print_context")) != self.material._recovery_context(record.get("context"))
                or any(type(variables.get(key)) is not int or variables[key] != 0
                       for key in ("fail_flag", "is_nozzle_setting"))
                or any(variables.get("box_modify_t%d%s" % (tool, suffix)) != head
                       for tool, head in enumerate(record["mapping"]) for suffix in ("", "_backup"))):
            raise ValueError("Checkpoint job context, mapping or tool state changed")
        file_info = {key: record["file"][key] for key in ("path", "size", "modified")}
        self.material._recovery_active_file(sd, file_info)
        # get_file_position() returns next_file_position, which can describe a
        # still-executing command. Public status is the completed file position.
        position = (sd.get_status(now).get("file_position") if sd_boundary is None
                    else sd_boundary[3])
        if type(position) is not int or not 0 < position < file_info["size"]:
            raise ValueError("No unfinished completed-file position")
        attachment = self.material._attachment(now)
        if attachment.get("state") != "attached" or attachment.get("head") not in record["heads"]:
            raise ValueError("Checkpoint head attachment is not a required loaded source")
        head = int(attachment["head"][1:])
        toolhead_object = self.material.printer.lookup_object("toolhead")
        toolhead = toolhead_object.get_status(now)
        scheduled, estimated, lookahead_empty = toolhead_object.check_busy(now)
        if ((lookahead_empty is not True and queued_tail is None)
                or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                       for value in (scheduled, estimated))):
            raise ValueError("Checkpoint motion has not reached a scheduled boundary")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if toolhead.get("extruder") != heater or variables.get("current_extruder") != head:
            raise ValueError("Checkpoint active extruder and attachment disagree")
        loaded = self.material._loaded_filament_status(now).get(attachment["head"], {})
        saved = record["heads"][attachment["head"]]
        if not self.material._loaded_source_matches(loaded, saved):
            raise ValueError("Checkpoint loaded source changed")
        move = self.material.printer.lookup_object("gcode_move").get_status(now)
        coordinates = list(move.get("gcode_position", []))
        origin = list(move.get("homing_origin", []))
        parser_position = list(move.get("position", []))
        machine_position = list(toolhead.get("position", []))
        if (any(len(vector) != 4 for vector in (coordinates, origin, parser_position, machine_position))
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in coordinates + origin + parser_position + machine_position)
                or any(type(move.get(key)) is not bool for key in ("absolute_coordinates", "absolute_extrude"))
                or any(type(move.get(key)) not in (int, float) or not math.isfinite(move[key]) or move[key] <= 0
                       for key in ("speed", "speed_factor", "extrude_factor"))):
            raise ValueError("Checkpoint G-code state is unavailable")
        settings = self.material.printer.lookup_object("configfile").get_status(now)["settings"]
        targets = {}
        for name in ["extruder", "extruder1", "extruder2", "extruder3", "heater_bed"]:
            obj = self.material.printer.lookup_object(name, None)
            if obj is None:
                if name == "heater_bed":
                    raise ValueError("Checkpoint bed heater is unavailable")
                continue
            target = obj.get_status(now).get("target")
            limits = settings.get(name, {})
            minimum, maximum = limits.get("min_temp"), limits.get("max_temp")
            if (any(type(v) not in (int, float) or not math.isfinite(v)
                    for v in (target, minimum, maximum))
                    or minimum >= maximum or target < 0
                    or (target != 0 and not minimum <= target <= maximum)):
                raise ValueError("Invalid checkpoint heater target: " + name)
            targets[name] = target
        fans = {}
        for name in ("fan", "fan_generic auxiliary_fan", "fan_generic air_fan"):
            obj = self.material.printer.lookup_object(name, None)
            if obj is None:
                if name == "fan":
                    raise ValueError("Checkpoint fan state is unavailable: " + name)
                continue
            speed = obj.get_status(now).get("speed")
            if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 1:
                raise ValueError("Invalid checkpoint fan speed: " + name)
            fans[name] = speed
        stats = self.material.printer.lookup_object("print_stats").get_status(now)
        accounting = {key: stats.get(key) for key in ("total_duration", "print_duration", "filament_used")}
        self.material._validate_recovery_accounting(accounting)
        mesh = self.material.printer.lookup_object("bed_mesh")
        fingerprint = self._recovery_mesh_fingerprint()
        mesh_offsets = list(mesh.get_mesh().mesh_offsets) + [mesh.tool_offset]
        return {"version": 4, "mesh_fingerprint": fingerprint, "mesh_offsets": mesh_offsets,
                "job_id": record["id"], "session": self.material.session_id,
                "job_fingerprint": self.material._recovery_fingerprint(job_bytes),
                "file": copy.deepcopy(record["file"]), "file_position": position,
                "head": attachment["head"], "source": copy.deepcopy(saved),
                "mapping": list(record["mapping"]), "gcode_position": coordinates,
                "parser_position": parser_position, "machine_position": machine_position,
                "heater_targets": targets, "fans": fans, **accounting,
                "homing_origin": origin, "scheduled_print_time": scheduled,
                "observed_print_time": estimated, **{key: move[key] for key in
                    ("absolute_coordinates", "absolute_extrude", "speed", "speed_factor", "extrude_factor")}}


    def _recovery_execution_path(self, for_write=False):
        return self.material._recovery_runtime_path("wmp_recovery_execution.json", for_write)


    def _recovery_execution_bytes(self):
        try:
            return self.material._recovery_read_bytes(self._recovery_execution_path(), 65536)
        except FileNotFoundError as error:
            raise ValueError("No managed execution checkpoint was saved for this print; recovery cannot continue") from error


    @staticmethod
    def _parse_recovery_execution_format(payload):
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Saved recovery record is unreadable; original records were not changed") from error
        if isinstance(value, dict) and type(value.get("version")) is int and value["version"] != 4:
            missing = {
                1: "saved parser/machine coordinates, mesh transform and print accounting",
                2: "saved mesh transform and print accounting",
                3: "saved printing-time and filament-use accounting",
            }.get(value["version"])
            if missing is not None:
                raise ValueError("Saved recovery format %d lacks %s. Recovery cannot continue; original records were not changed" % (value["version"], missing))
            raise ValueError("Saved recovery format is not supported by this WM+ version; original records were not changed")
        return value


    def _read_completed_recovery_execution(self, selected_file):
        self.material._require_recovery_not_retired()
        payload = self._recovery_execution_bytes()
        value = self._parse_recovery_execution_format(payload)
        fields = {"version", "job_id", "session", "job_fingerprint", "file", "file_position",
                  "head", "source", "mapping", "gcode_position", "homing_origin", "heater_targets",
                  "fans", "total_duration", "print_duration", "filament_used", "scheduled_print_time", "observed_print_time",
                  "completed_print_time", "absolute_coordinates", "absolute_extrude", "speed",
                  "speed_factor", "extrude_factor", "state", "parser_position", "machine_position", "mesh_fingerprint", "mesh_offsets"}
        if (not isinstance(value, dict) or set(value) != fields
                or type(value["version"]) is not int or value["version"] != 4
                or value["state"] != "completed"):
            raise ValueError("Invalid completed execution record")
        if not isinstance(value["mesh_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["mesh_fingerprint"]):
            raise ValueError("Invalid recovery mesh fingerprint")
        if (not isinstance(value["mesh_offsets"], list) or len(value["mesh_offsets"]) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in value["mesh_offsets"])):
            raise ValueError("Invalid recovery mesh offsets")
        for key in ("job_id", "session"):
            if not isinstance(value[key], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value[key]):
                raise ValueError("Invalid execution record identifier")
        if (value["head"] not in ("h0", "h1", "h2", "h3")
                or not isinstance(value["mapping"], list) or len(value["mapping"]) != 4
                or any(type(head) is not int or head not in range(4) for head in value["mapping"])):
            raise ValueError("Invalid execution head or mapping")
        for key in ("gcode_position", "homing_origin", "parser_position", "machine_position"):
            vector = value[key]
            if (not isinstance(vector, list) or len(vector) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
                raise ValueError("Invalid execution coordinates or origin")
        for key in ("absolute_coordinates", "absolute_extrude"):
            if type(value[key]) is not bool:
                raise ValueError("Invalid execution coordinate mode")
        for key in ("total_duration", "scheduled_print_time", "observed_print_time", "completed_print_time",
                    "speed", "speed_factor", "extrude_factor"):
            number = value[key]
            if (type(number) not in (int, float) or not math.isfinite(number) or number < 0
                    or (key in ("speed", "speed_factor", "extrude_factor") and number == 0)):
                raise ValueError("Invalid execution timing or motion factor")
        self.material._validate_recovery_accounting(value)
        if value["completed_print_time"] < max(value["scheduled_print_time"], value["observed_print_time"]):
            raise ValueError("Execution record was published before scheduled completion")
        targets, fans = value["heater_targets"], value["fans"]
        if (not isinstance(targets, dict) or "heater_bed" not in targets
                or set(targets) - {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in targets.values())
                or not isinstance(fans, dict) or "fan" not in fans
                or set(fans) - {"fan", "fan_generic auxiliary_fan", "fan_generic air_fan"}
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in fans.values())):
            raise ValueError("Invalid execution heater/fan state")
        job_bytes = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        if value["job_fingerprint"] != self.material._recovery_fingerprint(job_bytes):
            raise ValueError("Execution record belongs to different job evidence")
        record = self.material._recovery_material_evidence(selected_file)
        if (value["job_id"] != record["id"] or value["file"] != record["file"]
                or value["mapping"] != record["mapping"] or value["head"] not in record["heads"]
                or value["source"] != record["heads"][value["head"]]
                or type(value["file_position"]) is not int
                or not 0 < value["file_position"] < record["file"]["size"]):
            raise ValueError("Execution file, mapping or loaded head differs from committed job")
        heater = "extruder" if value["head"] == "h0" else "extruder" + value["head"][1:]
        if heater not in targets:
            raise ValueError("Execution head has no captured heater target")
        if (self.material._recovery_read_bytes(self._recovery_execution_path(), 65536) != payload
                or self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536) != job_bytes):
            raise ValueError("Execution evidence changed during verification")
        return copy.deepcopy(value)


    def _queue_recovery_execution(self, sd_boundary=None):
        # Keep one immutable candidate until it matures; never continually
        # replace it with newer, still-buffered motion and starve publication.
        if getattr(self, "_pending_execution_snapshot", None) is not None:
            return False
        toolhead = self.material.printer.lookup_object("toolhead")
        queue = getattr(toolhead, "lookahead", None)
        tail = queue.get_last() if queue is not None else None
        snapshot = self._recovery_execution_snapshot(sd_boundary, tail)
        if self._execution_boundary(snapshot) == getattr(self, "_execution_last_boundary", None):
            return False
        candidate = copy.deepcopy(snapshot)
        self._pending_execution_snapshot = candidate
        self._execution_state = "waiting_motion"
        if tail is not None:
            if queue.get_last() is not tail or not isinstance(tail.timing_callbacks, list):
                self._pending_execution_snapshot = None
                raise ValueError("Recovery lookahead boundary changed")
            earliest = candidate["scheduled_print_time"]
            candidate["scheduled_print_time"] = None
            self._execution_state = "waiting_schedule"
            def scheduled(print_time):
                if (self._pending_execution_snapshot is not candidate
                        or candidate["session"] != self.material.session_id
                        or getattr(self, "_execution_stopped", True)):
                    return
                if candidate["scheduled_print_time"] is not None:
                    return
                if getattr(toolhead, "lookahead", None) is not queue:
                    self._pending_execution_snapshot = None
                    self._execution_state = "refused"
                    self._execution_error = "Recovery lookahead queue was replaced"
                    return
                if (type(print_time) not in (int, float) or not math.isfinite(print_time)
                        or print_time < earliest or print_time < candidate["observed_print_time"]):
                    self._pending_execution_snapshot = None
                    self._execution_state = "refused"
                    self._execution_error = "Invalid recovery move scheduling time"
                    return
                candidate["scheduled_print_time"] = print_time
                self._execution_state = "waiting_motion"
            # Attach directly: register_lookahead_callback may flush when empty.
            # This callback is naturally invoked by retained _process_moves.
            tail.timing_callbacks.append(scheduled)
        return True


    def _publish_recovery_execution(self):
        """Publish a queued snapshot only after its scheduled motion time.

        The low-frequency sampler calls this. Publication is execution evidence,
        not native checkpoint selection or permission to resume a print.
        """
        pending = getattr(self, "_pending_execution_snapshot", None)
        if pending is None:
            return False
        if pending["scheduled_print_time"] is None:
            return False
        try:
            now = self.material.printer.get_reactor().monotonic()
            if (pending["session"] != self.material.session_id or self.material.printer.is_shutdown()
                    or self.material.printer.lookup_object("webhooks").get_status(now).get("state") != "ready"
                    or self.material.printer.lookup_object("openace", None) is not None
                    or self.material.printer.lookup_object("AFC", None) is not None):
                raise ValueError("Checkpoint session, readiness or owner changed")
            sd = self.material.printer.lookup_object("virtual_sdcard")
            if (not sd.is_active()
                    or self.material.printer.lookup_object("print_stats").get_status(now).get("state") != "printing"
                    or self.material.printer.lookup_object("pause_resume").get_status(now).get("is_paused") is not False):
                raise ValueError("Checkpoint job is no longer actively printing")
            position = sd.get_status(now).get("file_position")
            if type(position) is not int or position < pending["file_position"]:
                raise ValueError("Checkpoint file position moved backwards")
            for name in ("filament_operation", "toolhead_operation"):
                if self.material._material_operation_active(name):
                    raise ValueError("Service operation interrupted checkpoint completion")
            job_bytes = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
            if self.material._recovery_fingerprint(job_bytes) != pending["job_fingerprint"]:
                raise ValueError("Checkpoint job evidence changed")
            record = json.loads(job_bytes)
            variables = self.material.printer.lookup_object("save_variables").get_status(now)["variables"]
            if (self.material._recovery_context(variables.get("wmp_print_context")) != self.material._recovery_context(record["context"])
                    or any(type(variables.get(key)) is not int or variables[key] != 0
                           for key in ("fail_flag", "is_nozzle_setting"))):
                raise ValueError("Checkpoint context or fault state changed")
            loaded = self.material._loaded_filament_status(now)
            for key, saved in record["heads"].items():
                if not self.material._loaded_source_matches(loaded.get(key, {}), saved):
                    raise ValueError("Checkpoint loaded source changed")
            file_info = {key: pending["file"][key] for key in ("path", "size", "modified")}
            self.material._recovery_active_file(sd, file_info)
            scheduled, estimated, unused_empty = self.material.printer.lookup_object("toolhead").check_busy(now)
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in (scheduled, estimated))
                    or scheduled < pending["scheduled_print_time"]
                    or estimated < pending["observed_print_time"]):
                raise ValueError("Checkpoint motion clock changed or regressed")
            if estimated < pending["scheduled_print_time"]:
                return False
            # Later queued moves/head changes do not rewrite the captured parser
            # state. This receipt describes the earlier completed boundary.
            completed = dict(pending, state="completed", completed_print_time=estimated)
            self.material._write_recovery_json(self._recovery_execution_path(for_write=True), completed)
            self._execution_last_boundary = self._execution_boundary(pending)
            self._pending_execution_snapshot = None
            return True
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self._pending_execution_snapshot = None
            raise


