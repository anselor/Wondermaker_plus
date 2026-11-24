# Completed calibration checkpoints

Status: implemented and locally tested for bound Maintenance and setup-guide invocations on
`work/r4-print-time-fixes`. Unbound console commands retain their existing save
semantics; the owned entry-point inventory and qualification matrix are in
`2026-11-19-operation-cancel-ownership-audit.md`. Physical qualification remains
open. No installation or push under this backlog goal.

The owner requests a durable save after each completed calibration type, so a
later failure or cancellation cannot discard an earlier completed result.
A partial type must not overwrite the previous good calibration. Keep the
vendor worker running between types; do not restart Klipper between stages.

## Source findings

- `CalibrationCommands.cmd_run` is the admitted, ticket-bound wrapper around
  each Maintenance worker command. Completion currently sets `earlier_results`
  only; the final `SAVE_CONFIG` is the usual durable write and restart.
- G29 saves its profile into `configfile.autosave`, not onto disk.
- Both shaper helpers save `input_shaper` type/frequency options. Their callers
  apply and save each axis separately. Cancellation fitting Y can leave X
  applied and pending even though the vibration type never completed.
- The factory PID command removes the whole heater autosave section before
  setting control/Kp/Ki/Kd. A checkpoint must preserve unrelated options such
  as a user-calibrated rotation distance in that same section.
- `SAVE_CONFIG_NO_RESTART` exists, but writes the entire pending autosave set
  and uses two renames. Calling it blindly would persist unrelated user edits
  and can leave printer.cfg absent after an intermediate failure.
- `ConfigurationSave._publish_print_mesh` already has an atomic, fsynced
  publication path, but admits only a mesh-only pending set for print recovery.
  Maintenance checkpoints need their own explicit completed-type scope.
- Offsets use saved variables and the existing offset snapshot/restore owner;
  do not invent a second offset persistence or restoration path.

## Required behavior

1. Bind each checkpoint to the current session, request, ticket and completed
   command. Only the command greenlet may publish. A stale attempt, external
   owner, shutdown or coupling fault cannot acquire a new save authority.
2. Persist completed G29 mesh, completed XY shaper calibration, and each
   successfully completed PID heater result before another type starts.
   Publish only their owned options; preserve every other on-disk setting.
   A completed offsets stage keeps its existing saved-variable authority.
3. Capture and roll back failed-type changes, including partially applied
   shaper axes. Preserve pre-existing pending edits and writes from another
   actor outside the completed type's owned result options. The requested
   calibration replaces those result options. Track mutation ownership rather
   than treating equal values as proof
   that no external write happened. A foreign write of the same value still
   changes ownership.
4. A normal command return plus the existing health checks establishes a
   completed measurement. A Cancel delivered immediately after that return
   may stop the next stage, but should not discard this completed result.
   A stop/error inside the operation must never checkpoint partial results.
5. Write a complete candidate config to a temporary file, flush/fsync it,
   atomically replace the original and fsync the directory. Validate the
   original identity/content before publication and verify the scoped result
   afterwards. Preserve file permissions and unrelated includes/SAVE_CONFIG
   data. No repeated backups of backups or automatic replay after restart.
6. Publish bounded checkpoint evidence and an honest failure reason. A failed
   checkpoint cannot be reported as saved or allow subsequent stages to hide
   it. Keep final save/restart confirmation compatible with existing receipts.

## Local verification before printer qualification

Use retained config parsing/writing and the actual vendor calibration source
where practical. Test mesh followed by failed PID, vibration followed by Cancel,
a partially fitted second axis, and PID with unrelated tuning in its section.
Include pre-existing pending edits, foreign writes (including equal values),
stale tickets, retries, injected write/fsync/replace/readback failures, and
cleanup errors. Prove the last good on-disk config survives failed publication
before the atomic replacement. After replacement, a directory fsync/readback
failure must report an unconfirmed result and leave a complete config file;
it must never pretend that the old contents necessarily remain. Verify that
no restart or later calibration runs as an accidental side effect.

Physical verification remains deferred while the printer is reserved. The
local branch must not be installed or pushed under this backlog authorization.

## Implemented path and evidence

`wmp_calibration_checkpoint.Checkpoints.stage` runs inside the admitted
calibration command and its heater/greenlet owner. It observes configuration
set/remove calls and per-axis shaper updates only for that stage; all temporary
hooks are removed on exit. A soft fault is checked before a result can publish.
A normal verified completion is checkpointed before a subsequent Cancel is
observed. A stop inside the operation rolls its owned changes back instead.
Foreign writes, including equal values, are preserved and revoke overlapping
result authority. A failed second shaper axis restores prior parameters and
runtime shaping, retaining intervening foreign-axis updates. An unconfirmed
rollback blocks automatic docking through the existing cleanup receipt.

The publisher merges the completed type with the on-disk autosave rather than
serializing all live pending settings. It preserves unrelated tuning, comments,
includes, ownership and permissions, refuses linked targets and concurrent
config changes, fsyncs a temporary file, atomically replaces the target, fsyncs
the directory and verifies readback. Checkpoints create no backup files and
are never replayed. Status retains at most 16 bounded receipts. Pending settings
still represent values the running firmware may need to reload; final
SAVE_CONFIG/restart confirmation remains unchanged.

The native result screen validates checkpoint records, caches unchanged saved
summaries, and names completed saved types after a stopped/cancelled run. It
states that Klipper must restart to apply saved settings, without triggering a
restart. Existing offset saved-variable ownership/acceptance and cancellation
restoration remain unchanged; this component adds no competing offset writer.

Local checks include retained factory config and PID code, both shaper writer
versions, real bound command dispatch, late/in-operation Cancel, soft faults,
stale tickets, tuning/pending-edit preservation, foreign writes, runtime
rollback, invalid meshes/results, linked targets, metadata preservation,
write/fsync/replace/readback failures, bounded receipts/files and the final
factory restart receipt. A batch of 579 regression tests passed; a further
checkpoint/backend acceptance batch passed 226 tests. Native lifecycle and
real stock-font checks passed, including the longest saved-type summary.
Matching package checks and all printer qualification remain separate gates.
