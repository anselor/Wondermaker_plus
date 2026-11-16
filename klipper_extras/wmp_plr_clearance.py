# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery printed-envelope clearance and file evidence."""
import copy
import hashlib
import json
import math
import os
import stat

try:
    from . import wmp_recovery_file_envelope
    from .wmp_plr_records import RecoveryDepositionEnvelope
except ImportError:
    import wmp_recovery_file_envelope
    from wmp_plr_records import RecoveryDepositionEnvelope

class RecoveryClearance:
    def __init__(self, material):
        self.material = material

    def _recovery_file_effect_contract(self):
        # Installed-source identity, assuming the normal module-loading lifecycle.
        # This is not attestation against live monkeypatches or replaced bytecode.
        import sys
        now = self.material.printer.get_reactor().monotonic()
        settings = self.material.printer.lookup_object("configfile").get_status(now)["settings"]
        transforms = {}
        for name in ("gcode_move", "bed_mesh"):
            obj = self.material.printer.lookup_object(name)
            module = sys.modules[type(obj).__module__]
            path = module.__file__
            if path.endswith(".pyc"):
                path = path[:-1]
            transforms[name] = hashlib.sha256(self.material._recovery_read_bytes(path, 1024 * 1024)).hexdigest()
        return wmp_recovery_file_envelope.effect_contract(settings, transforms)


    def _recovery_file_mesh(self, execution):
        """Reconstruct saved interpolation without loading/mutating live mesh."""
        import sys
        mesh = self.material.printer.lookup_object("bed_mesh")
        profile = copy.deepcopy(mesh.pmgr.get_profiles().get("wmp_print"))
        if not isinstance(profile, dict):
            raise ValueError("Saved print mesh is unavailable for file clearance")
        offsets = execution.get("mesh_offsets")
        if (not isinstance(offsets, list) or len(offsets) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in offsets)):
            raise ValueError("Invalid recovery mesh offsets")
        params, points = profile.get("mesh_params", {}), profile.get("points")
        for axis in ("x", "y"):
            count, pps = params.get(axis + "_count"), params.get("mesh_" + axis + "_pps")
            if (type(count) is not int or type(pps) is not int or not 2 <= count <= 256
                    or pps < 0 or (count - 1) * pps + count > 256):
                raise ValueError("Saved recovery mesh exceeds bounded interpolation dimensions")
        if (not isinstance(points, (list, tuple)) or len(points) != params["y_count"]
                or any(not isinstance(row, (list, tuple)) or len(row) != params["x_count"]
                       or any(not wmp_recovery_file_envelope.finite(v) for v in row) for row in points)):
            raise ValueError("Invalid saved recovery mesh points")
        module = sys.modules[type(mesh).__module__]
        detached = module.ZMesh(params, "wmp_print")
        detached.build_mesh(profile["points"])
        grid = detached.get_mesh_matrix()
        target = 0.
        if mesh.fade_end != mesh.FADE_DISABLE:
            target = detached.get_z_average() if mesh.base_fade_target is None else mesh.base_fade_target
            low, high = detached.get_z_range()
            if (target != 0. and not low <= target <= high) or mesh.fade_dist <= max(abs(low), abs(high)):
                raise ValueError("Saved recovery mesh has invalid fade configuration")
        params = profile["mesh_params"]
        bounds = [[params["min_x"], params["min_y"]],
                  [params["max_x"], params["max_y"]], offsets[:2]]
        parameters = [mesh.fade_start, mesh.fade_end, mesh.fade_dist, target, offsets[2]]
        canonical = [[[float(v) for v in row] for row in grid],
                     [[float(v) for v in pair] for pair in bounds], [float(v) for v in parameters]]
        payload = json.dumps(canonical, separators=(",", ":"), allow_nan=False).encode()
        fingerprint = hashlib.sha256(payload).hexdigest()
        if fingerprint != execution["mesh_fingerprint"]:
            raise ValueError("Saved recovery mesh differs from the print checkpoint")
        return grid, target, fingerprint


    def _recovery_deposition_payload(self, execution):
        """Prefer measured evidence; derive absent evidence without writing."""
        try:
            return self.material._recovery_read_bytes(self.material._deposition_envelope_path(), 65536)
        except FileNotFoundError:
            pass
        job_bytes = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        if self.material._recovery_fingerprint(job_bytes) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed during file-clearance review")
        context = json.loads(job_bytes)["context"]
        if not isinstance(context.get("file_effect_contract"), dict):
            raise ValueError("No deposition record or print-start macro proof was saved for this older print; file-derived recovery cannot verify clearance. Start a new print after updating WM+.")
        proof = self._recovery_file_effect_contract()
        if proof != context["file_effect_contract"]:
            raise ValueError("Print-start macro/transform proof changed; file-derived recovery cannot verify clearance")
        grid, fade_target, mesh_fingerprint = self._recovery_file_mesh(execution)
        sd = self.material.printer.lookup_object("virtual_sdcard")
        full, identity = self.material._print_file_identity(sd, execution["file"])
        info = os.stat(full, follow_symlinks=False)
        key = (hashlib.sha256(wmp_recovery_file_envelope.canonical(execution)).hexdigest(),
               hashlib.sha256(job_bytes).hexdigest(), mesh_fingerprint,
               proof["sha256"], identity, info.st_ctime_ns)
        cached = getattr(self, "_file_clearance_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        descriptor = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != identity:
                raise ValueError("Recovery G-code changed before analysis")
            record = wmp_recovery_file_envelope.analyze(stream, execution, context,
                grid, fade_target, proof,
                lambda: self.material.printer.get_reactor().pause(self.material.printer.get_reactor().monotonic() + .001))
            after = os.fstat(stream.fileno())
        latest = os.stat(full, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(item, field) for item in (after, latest) for field in fields):
            raise ValueError("Recovery G-code changed during analysis")
        if (self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536) != job_bytes
                or self._recovery_file_mesh(execution)[2] != mesh_fingerprint
                or self._recovery_file_effect_contract() != proof):
            raise ValueError("Recovery file-clearance context changed during analysis")
        payload = json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8")
        self._file_clearance_cache = (key, payload)
        return payload


    def _recovery_clearance_evidence(self, execution):
        """Read job-bound deposition evidence; never substitute checkpoint Z."""
        payload = self._recovery_deposition_payload(execution)
        record = json.loads(payload)
        envelope = RecoveryDepositionEnvelope(lambda value: None, execution["job_id"],
                                               execution["file"]["sha256"], record)
        job_payload = self.material._recovery_read_bytes(self.material._recovery_job_path(), 65536)
        if self.material._recovery_fingerprint(job_payload) != execution["job_fingerprint"]:
            raise ValueError("Recovery job changed during clearance review")
        offsets = json.loads(job_payload)["context"]["offsets"]
        if (not isinstance(offsets, list) or len(offsets) != 4
                or any(not isinstance(row, list) or len(row) != 3
                       or any(type(v) not in (int, float) or not math.isfinite(v) for v in row)
                       for row in offsets)):
            raise ValueError("Recovery head offsets are unavailable")
        # Include all heads: preparation may dock the currently attached head
        # even when that head is absent from the resumed job's route map.
        span = max(row[2] for row in offsets) - min(row[2] for row in offsets)
        state = self.material.printer.lookup_object("toolhead").get_status(self.material.printer.get_reactor().monotonic())
        clearance = envelope.clearance(self.material._recovery_bottom_reference(state),
                                       getattr(self.material, "recovery_clearance_mm", 10.), span)
        return {"record": record, "sha256": hashlib.sha256(payload).hexdigest(),
                "clearance": clearance}


