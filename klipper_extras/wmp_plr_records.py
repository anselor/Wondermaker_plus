# SPDX-License-Identifier: GPL-3.0-or-later
"""Power Loss Recovery journals and deposition evidence.

Independent of Klipper objects: callers supply persistence and stage callbacks.
Loading evidence never dispatches printer operations.
"""
import copy
import math
import re


class RecoveryDepositionEnvelope:
    """Conservative queued-deposition ceiling, persisted before enqueue.

    The caller must install this below mesh transforms, begin on an admitted
    empty-bed job, and retain the same instance across tool changes and pauses.
    The backend installs this at the validated motion-queue boundary.
    """
    def __init__(self, persist, job_id, file_sha256, record=None):
        if (not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id)
                or not isinstance(file_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", file_sha256)):
            raise ValueError("Invalid deposition-envelope job binding")
        self.persist, self.failed = persist, False
        if record is None:
            record = {"version": 1, "job_id": job_id, "file_sha256": file_sha256, "max_z": 0.}
            persist(copy.deepcopy(record))
        if (not isinstance(record, dict) or set(record) != {"version", "job_id", "file_sha256", "max_z"}
                or type(record["version"]) is not int or record["version"] != 1
                or record["job_id"] != job_id or record["file_sha256"] != file_sha256
                or type(record["max_z"]) not in (int, float) or not math.isfinite(record["max_z"])
                or record["max_z"] < 0):
            raise ValueError("Invalid or mismatched deposition envelope")
        self.record = copy.deepcopy(record)

    def observe(self, move):
        if self.failed:
            raise ValueError("Deposition envelope is unresolved")
        try:
            start, end = list(move.start_pos), list(move.end_pos)
            if (len(start) != 4 or len(end) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in start + end)
                    or type(move.is_kinematic_move) is not bool):
                raise ValueError("Invalid deposition move geometry")
            if move.is_kinematic_move and end[3] > start[3]:
                # Include both ends of every physical linear segment. Bed-mesh
                # subdivisions and arcs reach this layer as separate segments.
                ceiling = float(math.ceil(max(start[2], end[2], 0.)))
                if ceiling > self.record["max_z"]:
                    updated = dict(self.record, max_z=ceiling)
                    self.persist(copy.deepcopy(updated))
                    self.record = updated
        except Exception:
            # Evidence failure invalidates this observer, not motion.
            self.failed = True
            raise

    def enqueue(self, move, submit):
        self.observe(move)
        try:
            return submit(move)
        except Exception:
            self.failed = True
            raise

    def clearance(self, bottom_z, required_gap, head_offset_span=0.):
        if (self.failed or any(type(v) not in (int, float) or not math.isfinite(v)
                               for v in (bottom_z, required_gap, head_offset_span))
                or required_gap <= 0 or head_offset_span < 0):
            raise ValueError("Invalid recovery clearance inputs")
        available = bottom_z - self.record["max_z"] - head_offset_span
        if available < required_gap:
            raise ValueError("Printed envelope leaves insufficient bottom-Z clearance")
        return {"printed_max_z": self.record["max_z"], "bottom_z": bottom_z,
                "available_gap": available, "required_gap": required_gap,
                "head_offset_span": head_offset_span}


class RecoveryAttempt:
    """Durable stage execution; caller must hold machine-command ownership.

    Dispatch completion is not physical completion. Each stage has a separate
    verifier, and an interrupted/dispatched stage is never automatically retried.
    Startup restores evidence and uncertainty; it never dispatches stages.
    """
    def __init__(self, persist, record=None):
        self.persist = persist
        self.record = copy.deepcopy(record) if record is not None else None
        self.busy = False
        if self.record is not None:
            if (not isinstance(self.record, dict)
                    or set(self.record) - {"cleanup", "resolution", "continuation", "checkpoint"} != {"version", "request", "state", "stages", "error"}
                    or type(self.record["version"]) is not int or self.record["version"] != 1
                    or self.record["state"] not in ("pending", "running", "unknown", "complete", "stopped", "abandoned")
                    or not isinstance(self.record["error"], str)
                    or not isinstance(self.record["stages"], list) or not self.record["stages"]):
                raise ValueError("Invalid recovery attempt journal")
            self._validate_request(self.record["request"])
            if "continuation" in self.record:
                outcome = self.record["continuation"]
                if (not isinstance(outcome, dict) or set(outcome) != {"state", "file_position", "error"}
                        or outcome["state"] not in ("complete", "paused", "cancelled", "unknown", "scheduled", "started", "interrupted", "checkpointed")
                        or type(outcome["file_position"]) is not int or outcome["file_position"] < 0
                        or not isinstance(outcome["error"], str)
                        or outcome["state"] in ("unknown", "interrupted") and self.record["state"] not in ("unknown", "abandoned")):
                    raise ValueError("Invalid recovery continuation outcome")
            if "checkpoint" in self.record:
                checkpoint = self.record["checkpoint"]
                if (not isinstance(checkpoint, dict) or set(checkpoint) != {"job_fingerprint", "file_position"}
                        or not isinstance(checkpoint["job_fingerprint"], str)
                        or not re.fullmatch(r"[0-9a-f]{16}", checkpoint["job_fingerprint"])
                        or type(checkpoint["file_position"]) is not int or checkpoint["file_position"] <= 0):
                    raise ValueError("Invalid recovery continuation checkpoint")
            if self.record.get("continuation", {}).get("state") in ("scheduled", "started", "interrupted", "checkpointed") and "checkpoint" not in self.record:
                raise ValueError("Recovery continuation has no checkpoint binding")
            if "cleanup" in self.record:
                cleanup = self.record["cleanup"]
                if (not isinstance(cleanup, dict) or set(cleanup) != {"state", "heaters", "error"}
                        or cleanup["state"] not in ("complete", "unknown") or not isinstance(cleanup["error"], str)
                        or not isinstance(cleanup["heaters"], dict)
                        or set(cleanup["heaters"]) - {"extruder", "extruder1", "extruder2", "extruder3", "heater_bed"}
                        or any(type(value) is not bool for value in cleanup["heaters"].values())
                        or cleanup["state"] == "complete" and not all(cleanup["heaters"].values())):
                    raise ValueError("Invalid recovery cleanup journal")
            if self.record["state"] == "abandoned" or "resolution" in self.record:
                resolution = self.record.get("resolution")
                if (not isinstance(resolution, dict) or set(resolution) != {"session", "attachment"}
                        or not isinstance(resolution["session"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", resolution["session"])
                        or resolution["attachment"] not in ([{"state": "attached", "head": "h%d" % i} for i in range(4)]
                                                           + [{"state": "empty", "head": ""}, {"state": "unknown", "head": ""}])):
                    raise ValueError("Invalid recovery abandonment receipt")
            names, incomplete = set(), False
            for stage in self.record["stages"]:
                if (not isinstance(stage, dict) or set(stage) != {"name", "state"}
                        or not isinstance(stage["name"], str) or not re.fullmatch(r"[a-z_]{1,48}", stage["name"])
                        or stage["name"] in names or stage["state"] not in ("pending", "running", "complete")
                        or (incomplete and stage["state"] != "pending")):
                    raise ValueError("Invalid recovery stage journal")
                names.add(stage["name"])
                incomplete = incomplete or stage["state"] != "complete"
            if self.record["state"] == "complete" and incomplete:
                raise ValueError("Incomplete recovery marked complete")
            if self.record.get("continuation", {}).get("state") in ("scheduled", "started"):
                self.record["continuation"].update(state="interrupted", error="Worker continuation was interrupted by restart")
                self.record.update(state="unknown", error="Review the interrupted recovery checkpoint before another operation")
                self.persist(copy.deepcopy(self.record))
            if self.record["state"] in ("pending", "running"):
                self.record.update(state="unknown", error="Recovery interrupted; inspect the machine before another attempt")
                self.persist(copy.deepcopy(self.record))

    @staticmethod
    def _validate_request(request):
        if (not isinstance(request, dict) or set(request) != {"id", "session", "execution_hash", "file"}
                or any(not isinstance(request[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request[k])
                       for k in ("id", "session"))
                or not isinstance(request["execution_hash"], str)
                or not re.fullmatch(r"[0-9a-f]{16}", request["execution_hash"])
                or not isinstance(request["file"], str) or not request["file"]):
            raise ValueError("Invalid recovery attempt request")

    def _save(self, **changes):
        # Keep the actual outcome in memory even if this write fails. The
        # current attempt stops; a fresh explicit request is assessed separately.
        self.record.update(changes)
        self.persist(copy.deepcopy(self.record))

    def run(self, request, stages, cancelled=lambda: False, owner=None, started=None):
        if self.busy:
            raise ValueError("Recovery attempt is running")
        self._validate_request(request)
        if self.record is not None and request["id"] == self.record["request"]["id"]:
            raise ValueError("Recovery request was already attempted")
        stages = tuple(stages)
        names = [stage[0] for stage in stages]
        if (not stages or len(set(names)) != len(names)
                or any(not isinstance(name, str) or not re.fullmatch(r"[a-z_]{1,48}", name) for name in names)
                or any(len(stage) != 3 or not callable(stage[1]) or not callable(stage[2]) for stage in stages)):
            raise ValueError("Invalid recovery stages")
        expected = copy.deepcopy(request)
        record = {"version": 1, "request": copy.deepcopy(expected), "state": "pending",
                  "stages": [{"name": name, "state": "pending"} for name in names], "error": ""}
        self.busy, self.record = True, record
        def retained():
            return self.record is record and record.get('request') == expected
        def owned():
            if not retained():
                return False
            try:
                return (owner is None or owner() is True) and retained()
            except Exception:
                return False
        def guard():
            if not owned():
                raise ValueError('Recovery attempt ownership changed')
        def save(**changes):
            guard()
            self._save(**changes)
            guard()
        try:
            if started is not None:
                started(record)
            save()
            for index, (name, dispatch, verify) in enumerate(stages):
                guard()
                stopping = cancelled()
                guard()
                if stopping:
                    save(state="stopped", error="Recovery stopped before " + name)
                    return copy.deepcopy(record)
                record["stages"][index]["state"] = "running"
                save(state="running")
                dispatch()
                guard()
                confirmed = verify()
                guard()
                if confirmed is not True:
                    raise ValueError("Recovery completion was not confirmed: " + name)
                record["stages"][index]["state"] = "complete"
                save()
            save(state="complete")
            return copy.deepcopy(record)
        except Exception as error:
            if owned():
                record.update(state="unknown", error=str(error))
                try:
                    self.persist(copy.deepcopy(record))
                except Exception:
                    # Retain the original error. Interrupted disk evidence is
                    # still pending/running and restores as unknown.
                    pass
            raise
        finally:
            # An old stack cannot clear a replacement attempt's busy flag.
            if retained():
                self.busy = False
