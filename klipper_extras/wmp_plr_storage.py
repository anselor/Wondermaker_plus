# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery saved records and checkpoint file validation."""
import configparser
import hashlib
import json
import math
import os
import re
import stat
import tempfile

try:
    from . import wmp_recovery_retirement
    from .wmp_persistence import atomic_write
except ImportError:
    import wmp_recovery_retirement
    from wmp_persistence import atomic_write

class RecoveryStorage:
    def __init__(self, material):
        self.material = material

    def _recovery_active_file(self, sd, identity):
        # The loader already selected this open stream. Validate its actual
        # descriptor instead of enumerating the entire G-code directory again.
        full, file_identity = self.material._print_file_identity(sd, identity)
        stream = getattr(sd, "current_file", None)
        if stream is None or stream.closed or os.path.realpath(stream.name) != full:
            raise ValueError("Checkpoint active file changed")
        info = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != file_identity:
            raise ValueError("Checkpoint active file was replaced")
        return full, file_identity


    def _recovery_job_path(self):
        return os.path.join(os.path.dirname(self.material.profile_path), "wmp_recovery_job.json")


    @staticmethod
    def _recovery_read_bytes(path, limit):
        # Do not follow a final symlink or block on a FIFO. Detect replacement
        # during the read as well as in-place edits before returning evidence.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                raise ValueError("Invalid recovery evidence file")
            payload = stream.read(limit + 1)
            def identity(info):
                return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            if (len(payload) != before.st_size
                    or identity(os.fstat(stream.fileno())) != identity(before)
                    or identity(os.stat(path, follow_symlinks=False)) != identity(before)):
                raise ValueError("Recovery evidence changed while reading")
        return payload


    def _read_recovery_job(self):
        payload = self._recovery_read_bytes(self._recovery_job_path(), 65536)
        value = json.loads(payload)
        if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
            raise ValueError("Invalid recovery job record")
        return value


    @staticmethod
    def _recovery_offsets(offsets):
        # SAVE_VARIABLE uses literal_eval and preserves native tuple offsets.
        # JSON converts those tuples to arrays. Compare the same coordinates,
        # without rewriting either durable record or relaxing numeric checks.
        if (not isinstance(offsets, (list, tuple)) or len(offsets) != 4
                or any(not isinstance(row, (list, tuple)) or len(row) != 3
                       or any(type(v) not in (int, float) or not math.isfinite(v)
                              for v in row) for row in offsets)):
            raise ValueError("Invalid recovery calibration offsets")
        return [list(row) for row in offsets]


    @classmethod
    def _recovery_context(cls, context):
        if not isinstance(context, dict):
            raise ValueError("Invalid recovery context")
        return dict(context, offsets=cls._recovery_offsets(context.get("offsets")))


    @staticmethod
    def _recovery_fingerprint(payload):
        # Match the reviewed native sidecar format exactly. This detects stale
        # bytes; it is not an authenticity or physical-readiness guarantee.
        value = 0xcbf29ce484222325
        for byte in payload:
            value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
        return "%016x" % value


    @staticmethod
    def _recovery_checkpoint_values(payload, file_size):
        # Parse the reviewed vendor format without defaults/interpolation. Native
        # fallback-to-zero parsing must not turn truncated evidence into a job.
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.optionxform = str
        try:
            parser.read_string(payload.decode("ascii"))
        except (UnicodeError, configparser.Error) as error:
            raise ValueError("Malformed recovery checkpoint: " + str(error))
        if parser.sections() != ["plr_data"] or parser.defaults():
            raise ValueError("Invalid recovery checkpoint section")
        fields = dict(parser["plr_data"])
        integers = {"last_file_pos", "absolute_e", "timestamp", "print_time", "last_is_during_T",
                    "last_heater_bed_target"} | {"last_extruder%d_target" % i for i in range(4)}
        floats = {"last_x", "last_y", "last_z", "last_e", "last_gcode_move_speed",
                  "last_gcode_move_speed_factor", "last_gcode_move_extrude_factor",
                  "last_fan_speed", "last_auxiliary_fan_speed", "last_air_fan_speed"}
        if not (integers | floats | {"last_leveling_type"}).issubset(fields):
            raise ValueError("Recovery checkpoint required fields are missing")
        values = {}
        for key in integers | floats:
            text = fields[key]
            pattern = r"[+-]?[0-9]+" if key in integers else r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
            if not re.fullmatch(pattern, text):
                raise ValueError("Invalid recovery checkpoint number: " + key)
            value = int(text) if key in integers else float(text)
            if key in floats and not math.isfinite(value):
                raise ValueError("Nonfinite recovery checkpoint number: " + key)
            values[key] = value
        if not 0 < values["last_file_pos"] < min(file_size, 2147483648):
            raise ValueError("Recovery file position is outside the unfinished file")
        if any(values[key] not in (0, 1) for key in ("absolute_e", "last_is_during_T")):
            raise ValueError("Invalid recovery extrusion/tool-change mode")
        if values["timestamp"] <= 0 or values["print_time"] < 0:
            raise ValueError("Recovery checkpoint is reset or has invalid elapsed time")
        if any(values[key] < 0 for key in integers if key.endswith("_target")):
            raise ValueError("Negative recovery heater target")
        for key in ("last_gcode_move_speed", "last_gcode_move_speed_factor", "last_gcode_move_extrude_factor"):
            if values[key] <= 0:
                raise ValueError("Invalid recovery motion factor: " + key)
        for key in ("last_fan_speed", "last_auxiliary_fan_speed", "last_air_fan_speed"):
            if not 0 <= values[key] <= 1:
                raise ValueError("Invalid recovery fan fraction: " + key)
        if fields["last_leveling_type"] not in ("adaptive_mesh", "default_mesh"):
            raise ValueError("Unsupported recovery leveling context")
        values["last_leveling_type"] = fields["last_leveling_type"]
        # G-code coordinates include offsets; range checks need the restored
        # transform. Heater limits and interrupted-tool-change handling likewise
        # belong to current-machine admission, not this format parser.
        return values


    def _recovery_checkpoint_evidence(self, selected_file, checkpoint, checkpoint_hash, job_hash):
        """Bind current evidence to the native loader's cached selection.

        Still a read-only prerequisite, not an admission lease or permission to
        call stock preparation. The caller must separately validate checkpoint
        semantics, machine state and exclusive recovery ownership.
        """
        if checkpoint not in ("plr_dataA.ini", "plr_dataB.ini"):
            raise ValueError("Invalid recovery checkpoint selection")
        for value in (checkpoint_hash, job_hash):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{16}", value):
                raise ValueError("Invalid native recovery fingerprint")
        path = os.path.join(self.material.recovery_checkpoint_dir, checkpoint)
        paths = (path, path + ".wmp-coordinates", self._recovery_job_path())
        limits = (65536, 256, 65536)
        before = tuple(self._recovery_read_bytes(name, limit) for name, limit in zip(paths, limits))
        marker = before[1].decode("ascii").split()
        if (marker != ["WMP-GCODE-XYZ-MATERIAL-2", checkpoint_hash, job_hash]
                or self._recovery_fingerprint(before[0]) != checkpoint_hash
                or self._recovery_fingerprint(before[2]) != job_hash):
            raise ValueError("Selected checkpoint and recovery job binding differ")
        record = self.material._recovery_material_evidence(selected_file)
        values = self._recovery_checkpoint_values(before[0], record["file"]["size"])
        # File-content hashing yields. Recheck all bindings afterward, even if
        # the replacement record happens to describe the same job semantically.
        after = tuple(self._recovery_read_bytes(name, limit) for name, limit in zip(paths, limits))
        if after != before or record != json.loads(before[2]):
            raise ValueError("Recovery checkpoint or job changed during verification")
        return {"record": record, "checkpoint": checkpoint, "values": values,
                "checkpoint_hash": checkpoint_hash, "job_hash": job_hash}


    def _recovery_runtime_path(self, filename, for_write=False):
        legacy = os.path.join(os.path.dirname(self.material.profile_path), filename)
        runtime = os.path.join(getattr(self.material, "recovery_checkpoint_dir",
                                      os.path.dirname(self.material.profile_path)), filename)
        # Runtime evidence is not configuration. Keep old interrupted records
        # readable without rewriting their bytes or retirement file identities.
        # An existing malformed/symlink runtime entry must not expose older data.
        return runtime if for_write else wmp_recovery_retirement.runtime_evidence_path(legacy, runtime)


    def _archive_recovery_evidence(self, evidence):
        """Publish immutable original bytes before retiring continuation authority."""
        if (set(evidence) not in ({"job", "execution"}, {"job", "execution", "offer"})
                or any(not isinstance(v, bytes) or not 0 < len(v) <= 65536 for v in evidence.values())):
            raise ValueError("Invalid recovery archive evidence")
        payload = json.dumps({"version": 1, "records": {k: v.hex() for k, v in evidence.items()}},
                             sort_keys=True).encode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        path = os.path.join(os.path.dirname(self.material.profile_path), "wmp_recovery_archive_" + digest + ".json")
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix=".wmp-recovery-archive-", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)  # Never overwrite an existing archive.
            except FileExistsError:
                if self._recovery_read_bytes(path, 450000) != payload:
                    raise wmp_recovery_retirement.ArchiveUnavailable("Recovery archive conflicts with preserved evidence")
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self._recovery_read_bytes(path, 450000) != payload:
                raise wmp_recovery_retirement.ArchiveUnavailable("Recovery archive readback differs")
            return digest
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


    def _read_archived_recovery_evidence(self, digest):
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Original recovery archive is unavailable; inspect preserved records")
        path = os.path.join(os.path.dirname(self.material.profile_path), "wmp_recovery_archive_" + digest + ".json")
        try:
            payload = self._recovery_read_bytes(path, 450000)
        except FileNotFoundError as error:
            raise ValueError("Original recovery archive is missing; inspect preserved records") from error
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("Original recovery archive changed")
        value = json.loads(payload)
        if (not isinstance(value, dict) or set(value) != {"version", "records"}
                or type(value["version"]) is not int or value["version"] != 1
                or not isinstance(value["records"], dict)
                or set(value["records"]) not in ({"job", "execution"}, {"job", "execution", "offer"})
                or any(not isinstance(v, str) or not 0 < len(v) <= 131072 or len(v) % 2
                       or not re.fullmatch(r"[0-9a-f]+", v) for v in value["records"].values())):
            raise ValueError("Invalid original recovery archive")
        return {k: bytes.fromhex(v) for k, v in value["records"].items()}


    def _recovery_offer(self, filename):
        """Bind the stock startup prompt to this file, without deleting checkpoints."""
        path = os.path.join(getattr(self.material, "recovery_checkpoint_dir", os.path.dirname(self.material.profile_path)), "plr.ini")
        try:
            raw = self._recovery_read_bytes(path, 65536)
        except FileNotFoundError:
            return path, None, None
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(raw.decode("utf-8"))
        if parser.defaults() or parser.sections() != ["plr_print"]:
            raise ValueError("Unrecognized native recovery offer")
        flag = parser.get("plr_print", "was_interrupted")
        if flag == "False":
            return path, raw, raw
        sd = self.material.printer.lookup_object("virtual_sdcard")
        if (flag != "True" or parser.get("plr_print", "plr_file") not in
                (filename, os.path.join(sd.sdcard_dirname, filename))):
            raise ValueError("Native recovery offer belongs to another file")
        updated, count = re.subn(rb"(?m)^(\s*was_interrupted\s*=\s*)True([ \t]*\r?$)",
                                 rb"\g<1>False\2", raw)
        if count != 1:
            raise ValueError("Unrecognized native recovery offer flag")
        return path, raw, updated


    def _clear_recovery_offer(self, path, before, after, guard):
        if before == after:
            return
        guard()
        if self._recovery_read_bytes(path, 65536) != before:
            raise ValueError("Native recovery offer changed before discard")
        fd, temporary = tempfile.mkstemp(prefix=".wmp-offer-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode))
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            guard()
            if self._recovery_read_bytes(path, 65536) != before:
                raise ValueError("Native recovery offer changed during discard")
            os.replace(temporary, path)
            directory = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if self._recovery_read_bytes(path, 65536) != after:
                raise ValueError("Native recovery offer discard was not confirmed")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


    def _recovery_archive_matches_attempt(self, evidence, receipt):
        if self._recovery_fingerprint(evidence["execution"]) != receipt["request"]["execution_hash"]:
            return False
        execution = json.loads(evidence["execution"])
        job = json.loads(evidence["job"])
        # Pre-archive versions already retired the original job. Preserve that
        # marker as evidence of the loss; never claim it is a committed job.
        legacy = (isinstance(job, dict) and set(job) in ({"version", "state", "reason", "id", "session"},
                                                {"version", "state", "reason", "id", "session", "job_fingerprint"})
                  and type(job["version"]) is int and job["version"] == 1
                  and job["state"] == "invalidated" and job["reason"] == "recovery-abandoned"
                  and job["id"] == receipt["request"]["id"]
                  and isinstance(job["session"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job["session"]))
        expected = job.get("job_fingerprint", receipt.get("checkpoint", {}).get("job_fingerprint")) if legacy else self._recovery_fingerprint(evidence["job"])
        return (isinstance(execution, dict) and isinstance(expected, str)
                and bool(re.fullmatch(r"[0-9a-f]{16}", expected)) and execution.get("job_fingerprint") == expected)


    def _write_recovery_job(self, record):
        # Neither staging nor a startup commit alone authorizes recovery.
        # The recovery entry must still admit the matching checkpoint/state.
        self._write_recovery_json(self._recovery_job_path(), record)


    @staticmethod
    def _write_recovery_json(path, record):
        payload = json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")
        if len(payload) > 65536:
            raise ValueError("Recovery job record is too large")
        atomic_write(path, payload, ".wmp-recovery-job-")


