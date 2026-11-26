# Power-loss recovery and first-tool probing

## R4 standalone print mesh

Print preparation atomically saves the current job's `[bed_mesh wmp_print]`
profile in `wmp-plr-mesh-v1.cfg`. The optional include loads it on restart,
including after power loss. A pause keeps it. Finish, cancellation and confirmed
recovery discard remove the file when recovery is retired. The user's default
mesh and other calibrations stay in their original configuration.

Upgrading removes the obsolete autosaved `wmp_print` profile from `printer.cfg`.
Print preparation creates the recovery mesh file when needed. The next successful mesh save removes
old WM+ backups named `printer-mesh-<eight random characters>.cfg`. Klipper's
timestamped configuration backups are retained.

## Current standalone UI development candidate — 12 November 2026

The unreleased `feature/standalone-ui` candidate uses managed recovery on the
qualified 1.1.13 client. Native Continue enters WM+'s numbered progress view;
the backend owns preparation, exact-file selection and continuation. It does
not delegate the return sequence to the stock recovery worker. See the
[release checklist](ui/standalone-completion.md#current-release-checklist--standalone-wm-updated-12-november-2026)
for current acceptance and remaining requirements.

Two narrow physical paths are now accepted: r151 resumed a genuinely interrupted
Head 4 coupon through all stages to print completion; r153 stopped recovery,
confirmed DISCARD and restarted without offering that discarded job again.
The original job/execution/offer bytes remain archived. These results do not
qualify every interruption point, old record format or openACE-owned job.

### Record compatibility

Recovery data contains several independent format versions. Do not treat a
version in one file as the version of the whole recovery system.

| Record | Current reader | Older-record limitation |
|---|---|---|
| Saved `wmp_print_context` | Version 2 | Version 1 lacks the current tool-map contract |
| Managed job | Version 1, with file identity, owner, sources and map | A stock coordinate checkpoint alone does not supply this job binding |
| Completed execution | Version 4 | Version 1 lacks parser/machine coordinates, mesh transform and accounting; version 2 lacks mesh transform and accounting; version 3 lacks printing-time and filament-use accounting |
| Recovery attempt | Version 1 | Interrupted running stages become unknown; original bytes are archived before rewriting |
| Abandonment archive | Version 1 | Both the earlier job/execution pair and the newer job/execution/offer set are readable |

The execution reader currently refuses versions 1–3 and unknown versions without
rewriting them. That refusal is implemented; supported migration remains open.
Changing a version number, using today's mesh or assigning zero accounting does
not recover the missing evidence. A future migration must identify its source
evidence, preserve the original bytes and qualify the resulting continuation.

Raw-evidence retirement is also distinct from discarding a valid managed
attempt. Candidate r154 archives job, execution, attempt, envelope, A/B
checkpoints, coordinate sidecars and `plr.ini`. After confirmation it can clear
a valid reviewed offer flag and bind that result in a version-2 receipt.
Malformed offers refuse cleanup; partial publication requires readback or a
fresh review, with original archives retained. This implementation is installed
and locally tested, but the r153 valid-attempt acceptance does **not** establish
device acceptance of raw discard for malformed or older records. Supported
older-record continuation also remains separate from discarding those records.

## Earlier stock-driven recovery implementation

The description below records the earlier implementation and its limitations.
It is not the execution sequence used by the standalone development candidate
above. Later dated sections retain the development history; their local or
pending labels are superseded only by explicit current-checklist evidence.

WM+ saves the bed mesh and physical probing head used for each print, then restores
them after power loss. It also preserves the slicer-to-head mapping and corrects
the touchscreen's saved coordinates. Install both `config` and `preload` for the
complete implementation.

**Remaining limits:** the vendor returns with only 3 mm above saved Z, which can
hit taller objects along the route. File position and motion are sampled separately,
so not every interrupted tool change has a consistent resume point. A part that
detached while cooling cannot be repaired by restoring coordinates.

Two-color prints completed after power cuts on September 14, 2026, using T0 and T2
probing heads and remapped tools. Those trials used firmware 1.1.08. Firmware 1.1.13
has local coverage but still needs printer testing.

## Before an upgrade or recovery

Do not update an interrupted older print expecting it to resume automatically.
Recovery needs the matching saved mesh, probing head, calibration, tool mapping,
filename, and a verified coordinate checkpoint. Missing or mismatched information
blocks recovery instead of guessing.

Installing the coordinate patch does not convert older records. If preserving a
pending print, follow the [checkpoint upgrade guidance](../client-preload/README.md#upgrading-with-an-interrupted-print).
Do not subtract a tool-change lift or label old coordinates as G-code coordinates
without evidence of their meaning at the saved file position.

If recovery is blocked, the console and `/tmp/wmp_recoveryfix.log` explain the
failed check. Some macro checks shut Klipper down because the screen sends further
movement requests independently. Resolve the issue and start a new print; do not
change calibration or bypass checks merely to accept an old record.

## Bed mesh and tool reference

A bed mesh records height corrections across the plate. Tool offsets account for
differences between heads. Both depend on which physical head established the
print's reference.

Fresh meshes, including full, bounded, and native adaptive probing, use the
reserved `wmp_print` profile. A saved-default start loads `default` using physical
T0, then copies it to `wmp_print`. Startup saves that copy before marking the print
ready. Changing `default` later cannot silently replace the recovery mesh.

`G29` selects physical T0 even if slicer T0 maps to another head. Normal default
calibration/loading rejects a nonzero probing reference. Startup never overwrites
`default`. If an older configuration may have overwritten it with another head's
mesh, regenerate it with `G29` on a clear bed.

Manual LOAD/SAVE/REMOVE of `wmp_print` is blocked; it belongs to startup and
recovery. Other named profiles retain normal Klipper behavior, and their probing
reference remains the caller's responsibility.

## Saved print information

`START_PRINT` clears the previous `wmp_print_context`, then commits a new record
after mesh persistence and startup/purge finish. The record contains:

- Format version, physical probing head, and mesh name.
- All four tool-offset vectors and slicer-to-head mappings.
- Filename encoded as UTF-8 hex so punctuation cannot corrupt the saved command.

Version 2 includes tool mapping; version 1 is not accepted by current macros.
The filename identifies a name, not a hash of file contents. End, cancel, and
`G29` clear the record. A failed new startup therefore cannot reuse the previous
job's information.

This record survives restart independently of `probe_tool`, which resets to T0
for idle/manual work. Persistence uses the vendor's existing configuration and
saved-variable mechanisms; WM+ does not add filesystem transaction guarantees.

## How recovery runs

1. **Establish Z before pickup or XY travel.** The required `wmp_recovery` helper
   homes to the bottom endstop if no real Z reference exists. It leaves the bed
   there, without nozzle-contact probing, XY travel, or an upward return.
2. **Restore the print reference.** The recovery homing branch checks saved print
   information, homes only missing X/Y axes, loads `wmp_print`, and applies mounted
   tool offsets relative to the saved probing head. It skips normal center Z
   preparation, including probe-head pickup and the LEVELING pulse.
3. **Let the vendor perform its return.** The screen selects the interrupted head,
   raises to saved Z + 3, extrudes/wipes, returns Y/X, and lowers to saved Z.
   Its later legacy mesh requests are redirected to the saved print mesh.
4. **Restore mapping just before file execution.** `M24` checks filename, mesh,
   and probing reference, restores the saved tool mapping after the client's last
   setup writes, then continues the file.

The real Z marker comes from homing events. Z motor disable, shutdown, and restart
invalidate it; assigning software coordinates cannot create it. Idle selection
benefits from the same bottom-first check. Bottom homing is blocked during a paused
print or active print body, and failure shuts down to block queued continuation.

The earlier pickup can already have homed XYZ before a later context check stops
recovery. “Blocked” does not always mean no preparation motion has occurred.
The checkpoint-coordinate check in the preload runs before the vendor recovery
start sends motion.

Ordinary pause/resume differs from power-loss recovery. Its intentional spool
remapping updates the matching saved print record at M24 for a later interruption;
it does not restore an old recovery mapping during every resume.

## Local coverage

`tests/test_print_recovery.py` executes nested startup, homing, mesh, and recovery
macros across a simulated restart. Cases include opt-outs, remapped T0, all startup
mesh choices, persistence, changed offsets, missing data, mismatched files, filename
encoding, and rejection of default calibration under another head's reference.

Other checks exercise real C coordinate markers and guards, modified executables,
stale cached records, and emulated ARM coordinate loads. Heater waits, contacts,
and probe readings are simulated; these tests do not establish physical clearance
or checkpoint consistency for every print.

## Physical test record

These entries preserve the rollout sequence. Intermediate failures and pending
checks describe the date shown, not the final status of firmware 1.1.08.

### September 13: recovery exposed mapping and contact faults

A two-color cube used physical T0/T2 with sliced T1 mapped to T2. Normal changes
worked and visual results were reported good. Power was cut during a T2-to-T0 change.
After reboot, IDs, mesh, and saved information survived, but recovery contacted the
part. Two T0 layers appeared acceptable, then sliced T1 selected physical T1.
The printer was paused.

Captured commands repeatedly set `box_modify_t1=1`, including after recovery
homing and before M24; its pre-cut value was 2. All board IDs were correct, so this
was tool-mapping loss, separate from an earlier board-assignment incident.
Version 2 saved mapping independently and restored it at M24 after those writes.
Tests also covered stale pause backups and the next sliced T1 command.

Part contact did not establish that software Z zero had reset. Native homing
establishes Z300 at the bottom; outer macros and later client return moves needed
separate investigation. Two checkpoint records also differed by the 2 mm tool-change
lift at the same file position. Restoring mapping did not solve either problem.

After the trial was cancelled, only `macros.cfg` was uploaded and Klipper returned
Ready. Calibration and tool-board files matched backups. At that stage the mapping
fix passed 104 offline tests. [The bottom-Z investigation](z-recovery-investigation.md)
then established the initial-motion fix.

### September 14: bottom-first deployment and empty-bed checks

The deployment backed up 57 configuration files and the optional diagnostic,
installed `wmp_recovery.py`, and uploaded `printer.cfg` and `change_macros.cfg` with
restart deferred. Saved calibration was retained. The diagnostic include, module,
and cache were removed. Restart returned Ready with axes unhomed and the reference
marker false.

Empty-bed motion checks ran without heating or extrusion:

| Check | Result |
|---|---|
| Fresh-restart T2 selection | Z homed before XY/pickup; correct T2; final Z299.954063 including its offset |
| M84, synthetic Z3, select mounted T2 | Homed-axis flag alone did not satisfy the marker; native bottom homing ended at Z300 |
| Ordinary full G28 | Selected T0 and ended at Z7, preserving normal homing |
| Early recovery T0 then recovery G28 | Reused bottom-homed axes, restored a T2 probing reference and mesh; offset yielded Z300.045937 |
| Vendor return replay from test Z40 | Started at clearance Z43, wiped, returned Y/X, and routed the mesh request correctly |
| Actual M24 on a 46-byte test file | Restored mapping [0,2,2,3]; sliced T1 selected physical T2 and completed |

The first synthetic record used JSON lists instead of native offset tuples and
was correctly rejected before return travel. Retrying with the production commit
macro preserved types; no check was relaxed. A one-second completion poll missed
a brief complete state before client print-end reset it to standby. A 0.3-second
monitor and console completion confirmed success.

Cleanup restored T0, prior mapping/preference, and cleared test files/information.
A screen-service restart also restarted Klipper, leaving axes unhomed with the bed
physically down. Calibration, tool-board files, helper source, and diagnostic removal
were verified. This was a motion integration test, not a resumed physical print.

### September 14: T0-reference print completed after power loss

`Cube_PLA_17m19s.gcode` completed after a cut during a change with all heads docked
and target T0. Recovery and a later T0 filament-runout load/resume kept sliced T0/T1
mapped to physical T0/T2. The exact mesh and offset record survived; bottom homing
was logged before pickup.

Checkpoint A pointed to byte 76447, the T0 command, with lifted Z3.5. Later sliced
commands explicitly restored Z1.6 before extrusion. No record was edited. This
successful case does not prove recovery for files without that explicit Z move.
Recovery return used vendor F3000 (50 mm/s); normal tool returns were 200 mm/s.

Completion cleared recovery information and print-ready state. Klipper was Ready,
standby, unpaused, with all heater targets zero. Visual seam quality and a T2 probing
reference remained pending until the next trial.

### September 14: T2-reference coordinate fault found and corrected

The next print mapped sliced T0/T1 to physical T2/T0 and started with a good reported
first layer. Its saved probing head was 2, mapping [2,0,2,3], with matching offsets
and `wmp_print`. These survived the cut, and sensors agreed that T2 was mounted.

Before Continue, checkpoint A/B positions 185799/185865 saved XYZ
[188,252.3,4.29526]. Matching pre-cut evidence recorded G-code Z4.8 and compensated
physical Z4.295262554799677. The file resumed extrusion before another Z command.
Reusing 4.29526 as G-code would apply corrections twice, about 0.505 mm too low.
Recovery was held at the prompt.

The preload was changed to write logical G-code XYZ and verify companion markers.
Local tests then passed 136 cases, including ARM emulation; the C marker harness
also ran on the printer's ARM CPU. Both pending records were migrated to
[188,252.3,4.8] from matching pre-cut samples, with backups.

Running-memory checks confirmed four XYZ load patches, three hooks, cached position
[188,252.3,4.8], selected file position 185865, and a valid B marker. Calibration,
mesh, and saved print information remained intact. No recovery movement was sent
during installation.

After Continue, logs showed bottom Z before XY, return Z7.8 then Z4.8, restored
probe head 2/mapping [2,0,2,3], and file resume at 185865. Both physical T0 and T2
changes worked. A new record at byte 197931 saved [188.25,247.550003,5.2], matching
client G-code floats rather than raw [188.171875,247.817187,4.746380194337592].
This verified correction of both XY tool offsets and Z mesh/tool compensation.
The user reported good visual results and the print completed with cleanup.

## Managed recovery admission (R22 implementation contract)

This is required work on the standalone UI branch, not an implemented guarantee.
The existing coordinate/mesh checks and the historical recovery trials above
do not establish managed filament readiness.

The deployed entry is `wmp_recoveryfix.c::start_recovery`: after verifying the
loaded checkpoint hash it invokes `original_start()`. The existing
`_WMP_RECOVERY_BEGIN` macro runs from recovery G28, and M24 performs another
check before file continuation. Neither is an adequate first admission boundary:
vendor preparation can already have begun. Do not implement R22 solely by adding
a filament check to either macro.

### Durable context and admission lifetime

1. Persist a versioned job-material record before allowing a managed print to
   become recoverable. Bind it to the actual selected file identity, committed
   print context, owner, sliced-tool assignments, and identities of the required
   physical heads/sources. Bind the execution head at the saved file position
   separately from the probing reference; neither the mounted head after restart
   nor an unbound native backup variable supplies that evidence. The current
   version-2 `wmp_print_context` stores only
   filename, mesh, probing head, offsets and four mapping entries; it cannot
   establish material continuity. `wm_material.print_submission` is in-memory
   and cannot supply that evidence after restart.
2. Capture the required tool set from the admitted job, not all four mapping
   entries. Unused mapped heads may correctly be empty. For openACE, retain
   owner-provided source and job evidence rather than converting it into
   standalone loaded flags. A changed or missing owner needs explicit supported
   recovery, never fallback to whichever component happens to be installed.
3. Before delegating to any vendor preparation, obtain acknowledged backend
   admission for the exact loaded checkpoint and durable job context. Validate
   current sensor/loaded evidence, required source identities, installed heads,
   fault/setup state and unfinished or uncertain tool/filament operations.
   Sensor presence alone cannot satisfy loaded state. A previous operation
   restored as unknown must remain a hold.
4. Bind the admission to a fresh backend session and single recovery attempt;
   recheck checkpoint and state at consumption. A cached GUI result, old token,
   duplicate Continue, replaced checkpoint or disconnect cannot authorize a new
   attempt. Do not manufacture a live pause origin to satisfy CHECK_RESUME.
5. Keep admission and preparation under one owner. A status-only check followed
   by unrestricted `original_start()` leaves an interleaving window: unrelated
   service commands can change material after the check. The implementation must
   serialize that interval, reject competing operations, and reconcile partial
   preparation before allowing a later request.
6. Preserve the existing coordinate marker, file/mesh/reference/mapping checks,
   bottom-Z recovery ordering and M24 validation. Filament-service XY-only
   homing is a different operation and must not replace recovery's real Z
   reference. This admission change does not solve the documented object
   clearance or interrupted-tool-change geometry limits.
7. Clear or replace the durable job record at new-job startup, cancellation and
   completion in concert with the existing print context. Any supported
   mid-print remap or guided material replacement must update the recovery
   evidence transactionally; do not treat legitimate managed replacement as
   permanent corruption or silently accept arbitrary profile edits.
8. Older checkpoints without material evidence must be identified explicitly.
   Do not silently promote current filament metadata into historical evidence.
   A supported migration/recovery flow requires its own reviewed contract; an
   unexplained disabled Continue is not feature completion.

### Implementation findings and remaining integration — 11 November

Current state (through r127): atomic job-material staging, startup commit,
cancellation/completion invalidation and native checkpoint/job byte binding are
installed alongside the managed recovery receiver. Material-bound selections
never delegate to stock preparation. A loaded managed receiver also blocks the
legacy coordinate-only fallback when the managed job is missing, independently
of the required-job environment flag. The recovery-fix-only installation retains
its separate legacy behavior. Installation and local tests do not establish
physical recovery acceptance; use the current standalone completion checklist
for remaining native-flow, interrupted-result and physical gates.

The startup preservation correction in `712405e` additionally archives exact
pre-restart attempt bytes before converting interrupted work to unknown. It has
passed focused/backend tests and is installed in r127 with matching backend
bytes and preserved configuration/filament state. It does not reconstruct
missing historical fields or dispose of an orphaned saved job.

The inspected native `plr_dataA.ini` stores positions, file offset, temperatures,
fan state and tool-change state, but no filename. The early admission bridge must
therefore supply and verify the actual native-selected file against the committed
job and its content identity; matching a checkpoint offset is insufficient.
The reviewed 1.1.13 selection source is now traced: `plr_load_AorB()` reads
`/home/t13dp/TM_T1/bin/plr.ini`, section `plr_print`, key `plr_file`, into
`plr_gcode_path` (32-byte C++ string at `0xe644ff8`). `start_plr_print()` copies
that global for metadata at `0x62d96c`, then reads it again at `0x62e94c` to
construct `SDCARD_SELECT_FILE`. The admission request must capture this selection
and preparation must prevent/reject changes before the later selection command;
a one-time check cannot establish that guarantee. The vendor missing-value
fallback `hanzao` is not recovery evidence.

Reproduce the exact-ELF provenance with
`python3 tools/inspect_stock_recovery.py <client>`. Its fingerprint, symbols,
literals and instruction windows support this static finding; they do not prove
runtime serialization or physical recovery acceptance.

### Native preparation ownership findings — 11 November

The exact 1.1.13 `start_plr_print()` has 41 direct `run_a_gcode` call sites
(including loops/branches; this is not 41 commands on every execution). Before
G28 it writes identity tool mappings, restores bed/nozzle targets, waits on a
nozzle target, selects a head and retracts. It later restores backup mappings,
homes, selects the captured head again, primes/wipes, restores position and
extrusion modes, selects the SD file, seeks and issues M24. Its sleeps and separate
command submissions do not establish one backend-owned operation.

At `0x62d94c` it captures `current_extruder_backup` (`0xe645710`) into a local
variable used for the heating/tool-selection path. `box_modify_t_backup`
(`0x385c4e8`) separately supplies mapping restoration. Neither is a field of the
bound A/B coordinate record. The committed context's `tool` is the **probing
reference head**, not the head executing at the saved file offset. Do not reuse
it as the resume head or infer a resume head from whichever head happens to be
mounted after restart.

The owned recovery contract must therefore include a checkpoint-bound execution
head and its mapping/source identity. Capture must correspond to the checkpoint's
file position and stable tool-change state, not an unrelated later status read.
The current material-bound sidecar is a prerequisite, not sufficient execution
context. Older records without this evidence need an explicit supported recovery
route; refusing them alone does not finish the feature.

Preferred implementation direction: the native entry submits one immutable
recovery request and does not call the stock preparation sequence. A backend-owned
procedure consumes verified checkpoint/material/execution context, preserves the
reviewed bottom-Z/mesh safeguards, and stops before subsequent stages when a stage
fails. If any stock preparation is retained instead, every command must be tied
to the same owned attempt; an initial permission check followed by unrestricted
`original_start()` remains unacceptable. The shared command queue, cancellation,
transport loss and uncertain partial execution need actual boundary tests.

The reproducible inspector now records the separate global symbols, decisive
instruction windows and all direct preparation call sites. This is static
provenance, not live recovery qualification.

### Native tuple calibration versus JSON arrays — 12 November

The r147 physical coupon reached completion, but capture refused the saved job
context. Native `SAVE_VARIABLE` preserves tuple-valued nozzle offsets while the
managed JSON job round-trip yields lists. Direct Python equality therefore
rejected equal coordinates, both during capture and recovery after restart.
Readback confirmed tuple offsets on the test printer; local regressions reproduced
both failures before correction.

WM+ now compares normalized four-by-three offset arrays at the persisted/live
boundary (capture, publication, admission and preparation). Only list/tuple
representation is normalized; finite numeric coordinates, context fields, job
bytes and file/mapping/owner checks remain enforced. No saved-variable or JSON
record is rewritten for this comparison, preserving native checkpoint fingerprints.
Local coverage includes tuple startup commit, capture/publication, post-restart
material review and preparation, plus malformed coordinates and context drift.
Physical publication and recovery continuation remain unproven.

### Natural scheduling capture implemented locally — 12 November

WM+ now binds the outer active SD dispatch before calling the retained
`run_script`, and observes it only after successful return with the command mutex
released. The binding retains the file object, old/completed byte positions and
session; any drift rejects capture. Nested, failed and unrelated dispatches do
not create completion evidence. Observation is limited to once per second.

A coherent immutable snapshot can now retain a nonempty lookahead tail. Its
completion time stays unknown until that exact move's retained timing callback
runs. The callback supplies the natural move-end time; it does not flush, yield,
write files or submit G-code. Publication waits until the MCU estimate reaches
that time and all existing source/file/job/session checks still pass. Retired
candidates, replaced queues, invalid clocks and callbacks from earlier sessions
cannot revive evidence. The old timer remains as a secondary observation path.

Focused tests execute the retained `_process_moves` and `run_script` methods:
failed dispatch does not notify; natural scheduling supplies the time; queued
motion is not marked completed early; later parser changes do not change the
captured record; stale bindings/callbacks are refused. Device qualification is
still required; this local implementation does not close R22.

### Live execution publication gap — 12 November

The r146 H4 coupon completed with committed material/job evidence, valid native
checkpoints and a Z1.0 deposition envelope, but no execution JSON. No deliberate
interruption was performed. The original timer-only capture requirement below
is insufficient for continuous motion and is not release-qualified.

`tests/test_recovery_sampler_schedule.py` executes the retained vendor SD worker
and `run_script` with deterministic reactor/backpressure scheduling. During 1600
commands, command yields hold the mutex; later 8192-byte file-read yields release
it but retain unscheduled lookahead. There is no capturable empty-queue boundary
after the first command. This proves a valid starvation schedule (test passes),
not the exact live refusal reason. Local status diagnostics distinguish busy
commands, refused capture, waiting motion and successful publication.

Required correction: observe successful completion of an outer SD command,
without confusing its `next_file_position` with a still-executing macro. Capture
parser/source/file/mesh state atomically, then bind that exact immutable candidate
to the tail move's natural timing callback. Publish only after the MCU estimate
passes that scheduled completion time and existing job/session/material guards
still pass. Do not flush lookahead, insert dwell/M400 commands, or infer executed
position from the latest queued command. Preserve a candidate while it matures;
reset, failed command, replaced file, owner change and callback loss must fail
closed. Tests must execute the retained command and timing callback boundaries,
including continuous nonempty lookahead, before another physical recovery trial.

### Execution evidence status and sampler contract — 11 November

Local code now validates restored material/checkpoint schemas and current-machine
readiness, captures coherent execution state without yielding, retains a pending
candidate until its scheduled motion has completed, and atomically publishes a
self-contained completed record. Thermal targets, fan fractions and elapsed time
are captured with the head/file/parser state. The strict completed-record reader
rechecks job/material/file binding after any yielding verification. The latest
backend suite passed 684 tests; none of this constitutes deployed recovery entry
integration or physical acceptance.

A one-second backend timer now invokes capture/publication locally; the native
entry does not consume completed execution records. The sampler must run at low frequency,
skip capture while the G-code command mutex is held, and validate the already-open
SD file without recursive directory enumeration or full-file hashing on each
sample. Full content verification remains an admission task. Capture must never
flush lookahead, submit G-code, block GUI/status updates or replace an immature
candidate with newer state. Deduplicate unchanged boundaries, invalidate pending
state on disconnect/fault, and recover from storage errors without losing the
previous durable record. The command-mutex capture guard and open-SD-file
validation without directory enumeration are now implemented locally (686 backend
tests passed). Timer integration, unchanged-boundary deduplication, idle skipping
and storage-error recovery now have coverage in the 690-test backend suite.
There is still no deployed recovery consumer.

Remaining implementation gates:

- Integrate the locally tested restored-record and readiness validators at the
  actual entry boundary, and connect the sampler described above. Validation
  helpers alone must not be treated as admission or exclusive ownership.
- Obtain an explicit backend acceptance before native preparation; serialize the
  accepted attempt through preparation and reconcile interruption or lost replies.
- Qualify the locally implemented installer path binding on target. The service
  environment now follows active wm_material ini_path and requires its job record;
  missing managed evidence must not select unmanaged compatibility.
- Update evidence atomically for supported mid-print changes and define the
  supported route for older records and openACE-owned jobs.
- Test the actual delegation boundary and then qualify controlled physical
  recovery separately. Do not repeat unrelated accepted load/unload tests.

### Focused qualification

Host coverage must exercise the actual entry/delegation boundary and verify zero
vendor calls on refusal, not merely a standalone predicate. Include valid
single-head recovery with unused empty heads, nonidentity mapping, changed file
at the same path, changed source/owner, sensor-present-but-unloaded, sensor clear,
uncertain operation after restart, stale session, duplicate Continue, checkpoint
replacement, and state changes between admission and preparation. Test new-job
failure, cancellation and managed replacement record lifetimes.

Exercise the backend and native failure paths for transport timeout or lost
acknowledgement without retrying uncertain preparation. The observed vendor
Moonraker HTTP multiline-error serialization defect makes a disconnect distinct
from an explicit refusal; JSON-RPC can return structured command errors, but
transport choice alone does not establish single-owner execution.

Live qualification remains a separate controlled interrupted-print test with
operator attendance and print authorization. Do not generate a power-loss event
or invoke stock Continue merely to validate the early refusal code.

## Maintainer integration reference

The inspected 1.1.08 `start_plr_print()` at `0x62d5d8` restores heaters/head using
temporary identity mappings, sends `Z_HOMING.z_raise=0` then G28, reselects the
interrupted tool, returns, loads a legacy mesh, selects/seeks the file, marks the
body ready, and sends M24. `_CHANGING_TOOL` is early enough to guard its first pickup.

`_WMP_HOME_Z_BOTTOM` calls native Z-only homing, keeping driver diagnostics,
2 mm retract, and the second seek. Individual stepper disables and M84 invalidate
the real reference. The older synthetic lift fallbacks also use bottom homing.
No touchscreen patch is needed for that initial ordering fix.

The profile wrapper redirects legacy `default`/`adaptive_mesh` loads only during
recovery. Internal profile operations use the renamed native handler. M24 delegates
to native M9924 after checks. Mapping restoration at G28 alone is too early because
the screen writes mappings again afterward. The print-body gate remains false
until the client marks it ready before M24. Startup retains the client-recognized
`adaptive_mesh` label; that label does not describe the actual probing area.

## Local evidence paths

These directories are ignored by Git and absent from a normal checkout:

| Path under `analysis/` | Evidence |
|---|---|
| `fw_1.1.08_diff/implementation/ghidra/calibration-fan-callers-strings.c` | Vendor recovery sequence |
| `backups/pre-max-z-recovery-20260914T061559Z/` | Configuration/diagnostic backups |
| `z-recovery-investigation/integration-20260914T062111Z/` | Ordering tests and rejected fixture |
| `z-recovery-investigation/integration-20260914T062555Z/` | Corrected record, SD completion, cleanup |
| `print-validation-20260914T124401Z/` | T0-reference print |
| `print-validation-20260914T140040Z/` | T2-reference print and checkpoint evidence |
| `backups/pre-checkpoint-coordinate-fix-20260914T143857Z/` | Original checkpoints, migration plan, prior preload state |

### G92 and transformed endpoint evidence — 11 November

Retained Klipper source confirms `gcode_move.homing_origin` is not the complete
coordinate base: G92 alters `base_position` independently. Execution schema 2 now
captures `gcode_move.position` (pre-mesh parser endpoint) and `toolhead.position`
(transformed commanded endpoint) alongside G-code position and homing origin.
The XYZ base is parser minus G-code position; E additionally uses the captured
extrusion factor. Neither coordinate representation can substitute for the other.

Current-machine review rejects missing/invalid XYZ bounds and transformed endpoints
outside those bounds. This is not route clearance or proof that reloading the mesh
recreates the same transform. Both remain preparation requirements. Schema 1 was
local and undeployed; it lacks sufficient coordinate evidence and is explicitly
rejected. A supported legacy recovery route remains required before release.


### Installer record-path binding — 11 November

Preload staging now resolves the installed active configuration (including
includes) and derives the recovery job path beside wm_material's ini_path.
Tilde expansion uses the printer account's home, not the privileged installer's.
The transactional service drop-in carries WMP_RECOVERY_JOB_PATH and
WMP_RECOVERY_JOB_REQUIRED=1 when wm_material is configured. Systemd percent and
quoted-string escaping are applied. Missing/invalid active configuration fails
before publication intent or service restart; a configuration without wm_material
retains the legacy path policy.

The native binding reader refuses missing job evidence when required, including
when a legacy coordinate marker exists. This is still a prerequisite: valid bytes
do not replace backend admission, and the current successful native path still
calls stock preparation. No recovery authorization or live acceptance is implied.

### Parser restoration contract — 11 November

The reviewed vendor GCodeMove reports `speed` in G-code F units (mm/min): it
returns internal speed divided by the internal factor, whose baseline is 1/60.
Do not multiply the captured feedrate by 60. Its RESTORE_GCODE_STATE has base and
homing-position restoration commented out, so it is insufficient for PLR.

The local parser restore helper requires command ownership, completed buffered
motion and matching parser/transformed XYZ endpoints before dispatch. It restores
M220/M221, explicit homing offsets with MOVE=0, G92 coordinates, feedrate and modes,
then verifies parser readback and unchanged physical coordinates. Historical
machine E is not a travel destination: prime/purge may have changed it. Logical
E is restored relative to the current E coordinate and captured extrusion factor.
The F-only G1 invokes the existing transform at the unchanged position; tests
against the retained vendor parser confirm no coordinate or extrusion delta.

This helper remains disconnected from native/public recovery entry. The caller
must establish the correct mesh, head, clearance and owned attempt before using
it; mutex presence alone is not a complete external admission protocol.

### Heater and fan restoration stages — 11 November

Initial preparation now restores physical heater targets and named fan values,
with current-limit admission and target readback. WM's M106 macro truncates S;
the renamed native M99106 retains the fractional value needed to restore captured
main-fan state. Target acceptance and temperature readiness are separate stages:
this implementation has not yet added the cancellable temperature wait or any
extrusion/return/SD-start stage. Do not use completion of these initial stages as
permission to resume the file.

### Temperature readiness — 11 November

The local initial-stage chain now includes cancellable warmup after heater/fan
target acceptance. Nonzero targets must remain within ±2 C for two seconds;
zero targets do not require zero-degree cooling. Half-second polls recheck
ownership/state, configured temperature bounds and unchanged targets, with a
20-minute timeout. Current/target progress is volatile backend status. Errors and
cancellation prevent subsequent stages and retain an unknown attempt outcome.
Before exposing the full operation, integrate heater cleanup and a deliberate
stopped-outcome reconciliation path; the wait itself does not authorize Resume.

### Failure cleanup and retained holds — 11 November

The local stage wrapper now attempts heater-off cleanup only after the attempt
reached heater-target restoration, using physical heater names and readback.
Cleanup remains within the admitted session/owner and command mutex; loss of that
ownership records an unconfirmed result instead of commanding another owner.
Per-heater results are durable, and errors do not mask the original failure.
Stopped/unknown preparation remains an admission hold even after confirmed cleanup.
An explicit reconciliation/abandonment path is still required before enabling a
public recovery operation; heater-off alone must never erase physical uncertainty.

### Explicit abandonment — 11 November

A local no-motion abandonment method can now reconcile a stopped/unknown attempt.
It requires current-session selection, idle/Ready state, zero heater targets,
completed queued motion and consistent attachment, with no unresolved stock or
managed fault. It invalidates the matching recovery job before closing its selected
file and clearing recovery flags/context, then durably records abandonment.
It does not reset fault flags, change filament evidence, heat, home or retry.
Another selected file/job is preserved; partial failure retains the hold and allows
only an explicit retry of this same abandonment. There is no public/UI entry yet.

### Physical head selection in initial preparation — 11 November

The local stage factory now persists `select_head` after bottom-Z and XY homing
and before heater targets. It binds dock calibration at stage construction,
checks the actual bottom position and travel limits, and verifies seating,
coupling, departure identity and extruder activation. Attachment transitions are
allowed only inside selection; subsequent guards require the selected head.
No generic retry or fault clearing is used. The actuator adapter propagates
errors from the vendor lower-level homing API instead of calling its exception-
swallowing G-code handler. Cancellation or uncertain selection retains the
attempt and prevents heating.

This does not complete PLR. Mesh/clearance/purge/return and exact-file continuation
still need integration, followed by native handoff/UI and physical qualification.
The initial-stage factory remains private and undeployed. Ordinary filament
service and its XY-only homing behavior are unchanged.

### Mesh binding and restoration — 11 November

Local execution schema 3 adds a SHA-256 fingerprint of the active interpolation
grid, XY bounds/mesh offsets, fade start/end/distance/target and tool offset.
Capture requires the active `wmp_print` profile with finite rectangular data.
Numeric values are normalized before hashing. Local undeployed schemas 1/2 lack
this evidence and are rejected; supported legacy migration remains release work.

The initial runner restores `wmp_print` after head selection and before heating,
compares the transform fingerprint, then computes the transformed saved parser
endpoint and requires it to match the saved machine XYZ. Changed grid, fade or
offsets and inconsistent endpoints prevent later stages. This verifies the saved
endpoint, not the clearance of the return route. Nondefault runtime mesh offsets
must be restored explicitly if needed; a fingerprint mismatch is not a completed
recovery route. Purge/wipe, return clearance, file continuation and native handoff
remain unfinished. No live deployment or motion.

### Runtime mesh offsets and travel ordering — 11 November

Schema 3 now also records runtime mesh X/Y and ZFADE offsets. Restoration applies
BED_MESH_OFFSET after loading the profile, then checks the full fingerprint and
saved transformed endpoint. This supports nonzero runtime offsets rather than
refusing them merely because profile loading resets them. The retained vendor
BED_MESH_OFFSET, fade-factor and inverse-position methods are exercised directly
in host tests across the fade range.

Return-route implementation must account for mesh compensation during travel:
a constant parser Z at the bottom reference can generate varying physical Z and
cross the limit. The planned purge/return phase must establish explicit machine
coordinates with compensation cleared, preserve the verified saved transform,
then restore it at the return endpoint before parser restoration/continuation.
A saved endpoint check alone remains insufficient to qualify object clearance.

### Machine-coordinate preparation before docking — 11 November

The initial stage chain now establishes an uncompensated machine-coordinate frame
between XY homing and head selection. It requires completed motion, valid XYZ
reference and command ownership; clears mesh, chooses absolute coordinates and
normal feed override, clears XYZ tool offsets without motion, then uses G92 to
align XYZ with the observed physical position. It verifies physical position and
E did not move, the mesh is cleared, and parser/G-code/origin readback agrees.
Extrusion base/mode/factor remain untouched for later explicit parser restoration.

This prevents dock travel from inheriting an arbitrary G92 shift. The same helper
is available for the later purge/return machine-coordinate phase; those travel
stages and object-clearance validation are still required. Tests execute retained
vendor parser handlers, including ignored commands and stale ownership/motion.

### Guarded purge-position travel — 11 November

The private initial chain now follows warmup with purge_position. It validates
all XY waypoints against current machine bounds before coordinate setup, retains
the verified physical bottom reference, and clears compensation through the
machine-frame helper. Travel exits along X to -13, then follows that off-bed edge
to Y80, matching the managed service position. Travel feed is 12000 mm/min.
Each waypoint drains queued motion and verifies XYZ and unchanged extrusion
position; changed reference/bounds/frame, cancellation or unconfirmed movement
stops subsequent travel and retains the attempt. Heating-stage cleanup applies.

These checks establish commanded route/bounds/reference consistency, not
printed-object clearance. That admission/qualification remains required before
public recovery can be enabled. No extrusion, wipe, return or continuation is
included in this stage. The bed is never raised by purge-position travel.

### Managed priming and wipe stages — 11 November

Private recovery preparation now primes after verified purge-position travel,
then wipes before any return. `[wm_material] recovery_purge_mm` accepts 1–300 mm
of input filament and defaults to `load_purge_mm`. This is recovery priming of
the admitted same material, not permission to substitute a spool or replay a
sliced material-transition purge. Changing filament identity still needs the
separate managed recovery/material review.

Priming uses physical-head temperature/readiness, a nonzero saved target and
confirmed off-bed bottom-reference position. It normalizes feed/flow and uses
relative extrusion, splitting into at most 25-mm moves within the head's configured
extrusion-only limit. Each command drains motion and checks commanded E progress
with unchanged XYZ. Cancellation, cold state, target drift or uncertain delivery
leaves an unknown attempt and prevents automatic re-priming.

Wiping uses the saved off-bed wipe position and configured WIPE_NOZZLE wipe_speed
(default 12000 mm/min), reproducing four pairs of 35-mm strokes through the guarded
XY mover. It avoids the stock macro's implicit homing, clearance and parser restore.
Calibration drift or failed travel stops the sequence; a completed prime remains
recorded even if wiping fails. These are local undeployed stages. Return clearance,
pose/parser restoration, exact file continuation and native/UI integration remain
required before a supported end-to-end recovery operation exists.

### Physical return stages — 11 November

The private chain now returns along the off-bed X edge to the saved Y, then to
saved X, while retaining bottom Z. All saved XYZ coordinates are checked against
current travel bounds before return travel. A separate vertical stage requires
confirmed target XY and bottom reference, re-establishes machine coordinates,
and submits one Z move to the captured physical height. It verifies drained
motion, unchanged XY/E and exact physical Z before restoring the saved mesh and
runtime offsets. Historical E is never a return destination: priming advancement
is preserved for later logical/parser restoration.

XY return, Z return and final mesh restoration have separate durable stages.
Failure/cancellation retains uncertainty and prevents continuation; completed
prime/wipe stages are not replayed. Object-clearance admission and physical
qualification are still required before exposure. Parser-state restoration and
file/native/UI continuation remain integration work; reaching the saved physical
pose is not proof that a print can safely resume.

### Parser restoration integrated after return — 11 November

The private preparation chain now finishes with restore_parser after verified
physical XYZ and mesh restoration. It restores feed/flow, homing origin, G92
logical coordinates, feed rate and absolute/relative modes through explicit
commands, preserving the advanced physical E from priming. Ownership/cancellation
checks run before and after every parser command. An ignored command or changed
owner/fault retains the attempt and prevents continuation.

Integration tests execute the retained vendor parser handlers rather than
simulating their state updates. SD-file selection/seek/start remains separate
unfinished work: preparation completion does not authorize native M24/Resume.
The retained M23 loader enumerates root files only by default, so the final file
handoff must explicitly support validated subdirectories and verify the opened
file identity; it must not assume a submitted filename proves the selected file.

### Exact-file selection and seek — 11 November

The private chain now follows parser restoration with a durable select_file stage.
It hashes the exact validated file, checks identity before and after hashing,
requires a completed byte/line boundary, opens through the retained vendor loader
with subdirectory support, and verifies the opened descriptor and M26 position.
It also seeks the stream explicitly and confirms its byte position. Another
selected job prevents replacement. The stage never starts the SD worker.

Ignored seek, lost acknowledgement or owner changes leave the attempt unknown;
completed prime/wipe/parser stages remain recorded rather than replayed. This is
still a private preparation chain. Worker-start acknowledgement, elapsed-state
restoration, object-clearance admission and native/UI integration remain open.
Vendor print_stats.set_current_file resets duration; assigning total_duration
alone cannot restore it because note_start/get_status derive it from the start
clock. The eventual continuation boundary must restore elapsed accounting using
that lifecycle, without counting recovery preparation as resumed print time.

### Recovery accounting lifecycle — 11 November

Local execution schema 4 additionally captures print_duration and filament_used
with total_duration at the same checkpoint boundary. All values must be finite;
printing duration must lie between zero and total duration. Signed filament
usage is retained because the native tracker includes retractions. Earlier local
schemas lack this evidence and are rejected; supported older-record migration
remains separate work.

The private accounting helper requires the exact selected checkpoint, idle SD,
standby print statistics and command ownership. It calls native note_start to
establish the current E baseline after priming, restores elapsed and printing
seconds, and preserves historical filament usage. Historic non-printing time is
carried as one excluded duration rather than guessing how much was initial
preparation versus pauses. Later native worker note_start, pause/resume and
completion keep their normal accounting. A repeated or unacknowledged accounting
start is rejected; it does not start the SD worker.

This helper belongs at the final continuation boundary and is not connected to
the preparation chain. The future handoff must acknowledge worker startup and
reconcile any partial accounting transition; standby-to-printing is not itself
proof that SD continuation began. No public/native entry or live deployment is
added by this work.

### Durable worker scheduling — 11 November

The private continuation helper registers the SD worker at the reactor's NEVER
deadline with an unarmed callback. The attempt runner may activate it only after
all stage verifiers pass, completion is persisted, and the matching complete
receipt is read back from disk. The callback cannot enter the vendor worker while
the command mutex remains held. Timer activation acknowledges scheduling, not
physical print progress or a successful first resumed line.

Registration, verification, persistence or activation failure disarms the token
and unregisters the known timer before heater cleanup. Even a registration whose
reply was lost leaves an unarmed callback. An unregister failure retains an
unknown cleanup outcome but does not re-arm the callback or skip heater cleanup.
A Stop received after the last stage but before activation also disarms it.
No failed handoff retries preparation or starts the SD body automatically.

This scheduling primitive is connected to the attempt runner but not yet to the
preparation stage factory or a native/public entry. Final context/mapping and
print-ready restoration, accounting integration, post-handoff runtime outcomes,
object-clearance admission and controlled physical qualification remain required.

### Private continuation chain integration — 11 November

The stage factory's explicit continue_print option now appends restore_routes,
accounting and start_file after verified file selection. It restores both live
and backup physical-head maps from the admitted execution record, clears the
recovery-active flag and sets print_body_ready. Readback must confirm all routes,
flags, probe reference, mesh, returned pose and selected byte position before
accounting or dormant worker registration. The ownership guard admits only this
attempt's deliberate accounting transition and registered dormant worker.

The runner persists and reads back completion before timer activation. Tests run
the retained vendor loader, parser, PrintStats and SD work_handler around simulated
motion, and verify that only the next checkpointed line is submitted. This is
host integration, not physical print acceptance. A failed or stopped handoff
first disarms its worker, then cancels only its own idle accounting context and
cleans up heaters. Changed owner/file/position prevents accounting cleanup and
retains uncertainty; it must never cancel another print.

The default factory still produces preparation-only stages, and no native/public
entry invokes the continuation option. Object-clearance admission, post-handoff
runtime outcomes, native/UI integration, record migration and owner-specific
qualification are still required before enabling recovery on the printer.

### Recovered worker outcomes and error fallback — 11 November

A dispatched recovery callback is single-use. While the retained SD worker runs,
its error template is temporarily replaced with TURN_OFF_HEATERS, avoiding the
configured stock CANCEL_PRINT motion/context-reset fallback. The original template
is restored when the worker returns. Completion, deliberate pause and cancellation
are recorded as continuation outcomes with the observed SD position. A command
failure, unexpected worker exception or unrequested paused result records an
unknown attempt and prevents automatic replay or ordinary managed Resume.

Heater-only cleanup checks the current owner/session/file. A still-printing owned
statistics context is marked errored rather than left falsely printing. Changed
ownership retains uncertainty instead of issuing cleanup against another job.
This covers the recovered worker invocation, not a later native Resume worker;
crash-window reconciliation and broader print error/Cancel ownership still need
qualification before public recovery is enabled.

### Restart boundaries around SD activation — 11 November

The attempt now persists a job-fingerprint/start-position binding and a scheduled
continuation before dormant timer registration. The callback persists started
before entering the vendor worker. Restoring either phase after restart produces
an interrupted continuation and an unknown attempt, preserving the hold against
new physical operations. A mere complete preparation receipt no longer hides
whether continuation was interrupted.

An explicit private no-motion reconciliation path can supersede that hold only
with a new completed execution record from the interrupted attempt's session,
bound to the same committed job and at or beyond its starting position. Reusing
the original execution fingerprint is rejected. The selected checkpoint, current
material/file evidence and immutable attempt journal are checked again around
file-hash yields. The machine must be idle, ready, fault-free and command-owned.
Reconciliation records checkpointed, preserves the committed job and filament
records, and sends no G-code. It is not recovery admission: the next attempt still
needs fresh machine/mesh/clearance/material review.

If no superseding checkpoint exists, the interrupted handoff remains unknown;
it is never replayed automatically. Native/UI presentation and the explicit
operator path for that case remain part of public recovery integration.

### Bottom-reference geometry correction — 11 November

The configured physical Z endstop is 300 mm while the allowed Z travel maximum
is 305 mm. These are different contracts. Recovery docking, purge/prime, XY
traverse and return prerequisites must use stepper_z.position_endstop, not
axis_maximum.z. The latter remains the limit for validating commanded endpoints.
The stage factory binds the positive-direction endstop before dispatch and refuses
missing/nonfinite/out-of-bounds or changed configuration. Host recovery fixtures
now deliberately use unequal values matching the retained printer configuration.

This fixes a local prerequisite that would reject genuine bottom homing. It does
not prove printed-object clearance. The actual 300-mm separation, rather than a
305-mm limit or a test fixture's 350-mm value, must be used by the pending route
admission calculation. No live geometry change or homing test is implied.

### Deposition envelope for clearance admission — 11 November

A saved nozzle height is not the highest object height when a job prints objects
sequentially. A one-second sample can also miss deposition between checkpoints.
The local RecoveryDepositionEnvelope primitive therefore retains a monotonic
physical-Z ceiling from positive-extrusion kinematic segments, including both
segment endpoints. It excludes travel/retraction and E-only service purge. Mesh
subdivisions and arcs must be observed below transforms as physical linear moves.
The ceiling rounds upward to whole millimeters, limiting writes to newly crossed
height bounds rather than every segment. Each increased bound is persisted before
its move is submitted. Failed persistence blocks submission; uncertain submission
blocks replay while retaining the conservative bound.

The record binds a job ID and full file SHA-256. It must begin before startup
purging for an admitted new job, survive pauses/tool changes/material replacement,
and seed a recovered job from its validated durable envelope. Clearance compares
the actual bottom endstop against this ceiling, a configured required gap and the
validated head-offset span. These calculations do not establish that the part
remained attached or reconstruct unobserved blobs/obstructions.

**Historical status at the primitive-only stage:** queue installation and normal
job persistence were still missing; the following observer/lifecycle section
records their subsequent local implementation. Recovery admission consumption
and resumed-job restoration remain open. The retained
vendor toolhead.move updates commanded_pos before lookahead.add_move. If evidence
persistence fails at that boundary, the adapter must stop further motion rather
than let a stock error/Cancel sequence use that advanced commanded position.
Lifecycle binding, checkpoint/restart admission, supported geometry and physical
qualification are prerequisites to enabling recovery. Timer samples and slicer
height comments must not silently substitute for complete deposition coverage.

### Deposition observer and startup lifecycle — 11 November

The local backend now installs the observer at toolhead.lookahead.add_move, below
mesh transformations and after native move validation. With no active envelope it
passes moves through unchanged. Managed _WMP_RECOVERY_JOB_BEGIN starts a new
job/file-bound record before startup motion/purging; COMMIT retains that instance
and CLEAR stops recording. Pauses and tool changes do not reset it. A restored
record can seed the same adapter without lowering its bound; recovery admission
must still validate and explicitly connect that restoration.

The adapter writes only when the rounded ceiling increases. It performs no file
reads, status serialization or G-code dispatch for ordinary segments. If recording
or queue submission fails, it invokes shutdown before propagating the exception,
because the retained vendor toolhead.move has already advanced commanded_pos at
this point. This prevents subsequent stock error/Cancel movement from trusting
an unexecuted pose. An ownership/session change while recording follows the same
stop policy. The observer is installed once and refuses silent replacement.

This integration is local and undeployed. Jobs without the supported observer
must not be admitted as having complete deposition coverage. Reading/binding the
durable envelope in recovery review, restoring it for continuation, configured
clearance/offset limits and physical qualification remain required.

### Clearance admission integration — 11 November

Local execution review now requires the durable deposition envelope to match the
selected execution's job ID and file SHA-256. It verifies the job fingerprint and
all four finite head-offset vectors, then compares the actual positive-Z endstop
against the highest deposition ceiling, offset span and `recovery_clearance_mm`
(default 10 mm, configurable 1–50 mm). All heads contribute to the span because
preparation can dock an attached head outside the resumed job's tool map.

The review retains the exact envelope SHA-256 and calculated clearance. The stage
factory and its command guard recheck them, so an envelope or clearance-setting
change after review stops preparation. Missing records are not replaced by empty
ones. This is local admission coverage, not physical proof that a part is attached
or that the travel route is unobstructed. Resumed-job observer restoration, native
handoff and controlled physical qualification remain open.

### Resumed-job deposition lifecycle — 11 November

The local continuation factory now refuses an unsupported motion queue before
preparation. After returning and selecting the exact file, a durable
`restore_deposition` stage seeds the observer from the reviewed record without
rewriting or lowering its height. Remaining preparation guards require the same
recorder, session, record and installed queue hook. Worker handoff retains that
binding; before its first SD command, the callback checks the recorder and its
durable record again. A lost binding retains an unknown outcome with heater-only
cleanup instead of starting the file.

Resumed positive-extrusion moves retain earlier object heights and persist newly
higher bounds through the existing queue observer. The native Continue path is
still not connected to this private chain; this is not deployed recovery support.

### Immutable native request consumer — 11 November (local)

The backend now has a private consumer for a version-1 hex-encoded JSON request
containing exactly `id`, `session`, `owner`, `file`, `checkpoint`,
`checkpoint_hash`, `job_hash`, `execution_hash`, `deposition_sha256`, and `version`.
It rejects duplicate JSON keys, unexpected fields and unsupported ownership.
Consumption requires the command mutex and validates both the native selection
and managed completed execution against current readiness and the same job/file.
The stage guards retain the native checkpoint/marker/job and execution hashes;
replacement after review stops preparation. The existing durable attempt runner
owns execution and duplicate-request refusal.

Native A/B sampling and managed completion sampling are asynchronous. Native
selection remains a required binding and interrupted-tool-change check; all resume
pose, parser, routes, accounting and byte position come from the coherent managed
completed record. No individual native coordinate or offset overrides that record.
The selected deposition SHA-256 must match the reviewed envelope.

The private consumer connects this contract to the full continuation chain. It is
not registered as a public command yet: native capture, asynchronous submission,
status/stop handling and UI integration must accompany that activation. The stock
`start_recovery` source remains unchanged at this stage; no deployed early-entry
interception or physical recovery acceptance is claimed.


### Native early-entry interception — 11 November (local, undeployed)

For a checkpoint with managed material binding, the preload now captures the
selected filename after the native loader and requires that same filename at
Continue. After rechecking checkpoint/job binding, it copies filename, checkpoint
basename and both hashes under the record mutex. It releases that mutex before
calling the version-1 `wmp_managed_recovery_select` receiver. The receiver must
copy its arguments synchronously and only enqueue screen/worker processing.
Acceptance is selection delivery, not backend admission or completed recovery.

Managed Continue always returns without `original_start`, including when the
receiver is missing or refuses selection. Missing/changed file evidence also
refuses before stock preparation. A diagnostic M118 explains the refusal. The
historical coordinate-only path retains its existing behavior when no managed
job binding is present; required-job configuration still forbids that downgrade.

The unified-screen receiver, selected execution/deposition capture, backend
submission, status/stop UI and deployment remain unfinished. This intermediate
source change must not be deployed as a usable managed recovery feature yet.

### Explicit Continue command and preparation STOP — 11 November (local)

`WMP_RECOVERY_CONTINUE REQUEST=<hex UTF-8 JSON>` now consumes the version-1
immutable selection under the G-code mutex. Its response is the durable
preparation receipt, not a claim that the scheduled SD worker has started printing.
`recovery_attempt` and its continuation phase remain the source of outcome truth.
The helper advertises `recovery_continue_protocol=1` and `recovery_stop_protocol=1`.

The reactor endpoint `wmp/recovery/stop` accepts the active request's `session` and
`id`. It only records intent, without waiting for the G-code mutex or issuing
motion. The running procedure checks that intent at its stage/wait boundaries and
owns cleanup. Other sessions, requests and owners are refused; after continuation,
normal print controls apply. `recovery_stop_requested` is temporary intent;
restart still restores an interrupted attempt as unknown from its durable journal.
STOP does not imply an instantaneous emergency stop or successful physical undo.

The native unified receiver and screen progress/stop controls are not connected
yet. This API is local and undeployed; registering it does not constitute native
integration or physical recovery acceptance.

### Explicit screen review and request construction — 11 November (local)

The read-only reactor endpoint `wmp/recovery/review` accepts the native selection
(`id`, `session`, `file`, `checkpoint`, `checkpoint_hash`, `job_hash`). It resolves
an absolute native filename only inside the G-code root, reads and validates the
managed execution/deposition evidence, and returns the immutable request plus
execution and clearance details. Busy command ownership before or after review
refuses the response. This work happens only on explicit review, never each status
poll. Continue repeats full admission; the review does not reserve the printer.

The C++ request builder validates the returned original filename, session, request
ID, native checkpoint/job hashes and completed execution filename/job binding
before constructing the hex-encoded Continue command. The GUI need not read
backend recovery files directly. Neither this helper nor the review response
submits motion. Native receiver, background delivery and progress UI remain to be
wired together; these components are local and undeployed.

### Background recovery delivery worker — 11 November (local)

A runtime-lifetime C++ worker now performs explicit review and one-shot Continue
submission on a command thread. A separate thread/transport sends STOP, while
ordinary status observation remains independent of both. No thread accesses
LVGL. Selection requires fresh standalone helper status and the three supported
protocols; consumed request IDs cannot be reused. Queued/running/unknown/stopped
outcomes block replacement requests.

Status receipts must match ID, backend session, canonical filename and execution
hash. A late/lost HTTP acknowledgement cannot overwrite a matching backend result.
A scheduled or started continuation remains pending; completion requires the
backend continuation outcome. Unmatched replies never imply success or trigger
resubmission. STOP has separate queued/requested/unconfirmed delivery state and
never claims physical completion by itself.

The loopback transport allows only the exact recovery review/stop routes. Larger
G-code bodies are accepted only for bounded hex-encoded recovery requests; the
existing size limit still applies to other command forms. Native receiver and
progress-panel integration are still pending, so the worker is not activated in
the runtime or deployed yet.

### Pre-admission refusal receipts — 11 November (local)

The explicit Continue command now publishes `recovery_submission`, bound to
request ID, session, filename and execution hash. A new syntactically valid
current-session request is `reviewing` before admission. If it fails before any
attempt journal is created, its result is `refused` with a bounded reason. Once
an attempt exists, the submission is only `attempted`; the durable journal owns
its actual outcome. Malformed/stale-session requests and duplicate tickets cannot
overwrite another submission or relabel an attempted operation as a refusal.
Consumed command IDs are retained for the session, including refused requests.

The C++ worker uses only an exactly matching refusal when no matching durable
attempt exists. A matching attempt always takes precedence. A later HTTP failure
cannot erase the confirmed refusal or turn it into a silent retry. This closes
the pre-admission error-reporting gap; explicit reconciliation/abandonment UI and
native receiver/panel wiring remain outstanding.

### Native progress panel — 11 November (local)

`StockRecoveryProgress` renders the request-bound result with a numbered,
scrollable preparation sequence. Completed stages are gray, running stages orange
and future stages white. During heating it displays each reported heater's
current/target temperature. Status updates retain the labels, buttons and scroll
position; an opaque panel blocks controls behind it. CLOSE only dismisses the
view. STOP is disabled on stale status or after a stop request, and its delivery
state is shown separately from the recorded operation outcome.

The native lifecycle test covers temperature/color updates without widget churn,
stale-status refusal, duplicate STOP taps, terminal updates, dismissal and parent
destruction. The panel is not yet connected to the runtime or native selection
receiver. No deployment or physical recovery acceptance is implied.

### Native runtime connection — 11 November (local)

The unified bootstrap exports `wmp_managed_recovery_select` with bounded copied
arguments and the existing version-1 contract. It configures independent command
and STOP transports before publishing the runtime. The poll thread observes raw
helper status; the GUI timer alone creates/updates the opaque progress panel.
There are no network waits or LVGL operations in the selection callback. Repeated
selections retain the original request/result; reopening an already visible
panel does not recreate widgets. Other selections cannot replace unresolved,
printing or paused attempts.

The panel now follows actual continuation states instead of labelling a resumed
print pending indefinitely. An uncertain continuation retains its error and does
not offer retry. Stale status withholds STOP, whose backend delivery still uses
its separate thread. Closing the view does not cancel or reset the attempt.

Host runtime/lifecycle/worker and native interception tests passed. This
supersedes earlier notes that receiver/panel wiring was absent; deployment and
physical qualification remain pending, as do explicit interrupted-result actions.

### Explicit interrupted-attempt resolution API — 11 November (local)

`wmp/recovery/resolve_review` accepts `id` (new resolution ticket), `attempt_id`,
current `session` and `action` (`reconcile` or `abandon`). It checks the selected
action's prerequisites without commands or writes and returns a version-1 request
bound to the attempt journal's SHA-256 and current execution fingerprint. Review
runs only on explicit request, refuses a busy command mutex, and rechecks evidence
after action-specific validation. It does not release the recovery hold.

`WMP_RECOVERY_RESOLVE REQUEST=<hex JSON>` accepts exactly that reviewed request.
It requires command ownership and repeats evidence/owner/session checks before
calling the selected action. Reconciliation preserves the job, releases only a
restart-interrupted continuation superseded by a newer completed checkpoint and
never resumes printing. Abandonment requires idle, heaters off and known attachment;
it drains prior motion, invalidates continuation authority and clears only the
matching runtime context. It adds no movement, heating or filament operations.

`recovery_resolution_protocol = 1` and `recovery_resolution` expose the action's
request-bound pending/complete/refused/unknown result. Consumed ticket IDs cannot
be replayed or replace their result. Failures after entering an action remain
unknown; the durable attempt journal remains authoritative after restart. A new
explicit review can reconcile partial abandonment cleanup, never replay recovery
preparation. These APIs remain undeployed and their screen controls are pending.

### Screen resolution review and confirmation — 11 November (local)

Interrupted-attempt controls are now connected to a separate background worker.
DISCARD requests read-only abandonment review; REVIEW requests checkpoint
reconciliation review where applicable. The returned identity and fingerprints
are validated before displaying the consequences and enabling CONFIRM. Only that
separate tap sends `WMP_RECOVERY_RESOLVE`; completion of review or a status sync
never submits it. Exact matching status receipts override late/lost HTTP replies.
An unconfirmed delivery cannot be retried; a backend-recorded partial failure
permits a new explicit review and confirmation with a new ticket.

The runtime displays a restored unknown/stopped attempt once per session/attempt,
without sending commands. Closing it does not discard it. Native Continue on that
hold reopens its result instead of submitting another preparation. Stale status
retains the display and disables actions. Final abandonment/checkpoint resolution
remains visible. A new session can release the prior local hold only by reporting
a durable resolution of that exact attempt; a new explicit recovery still needs
normal admission.

This supersedes earlier notes that resolution controls were unconnected. Native
visual/touch and physical qualification remain pending; no deployment is implied.

### Saved execution compatibility evidence — 11 November (local)

Schema history was checked against `caff9a1` (coordinate transforms), `23285b1`
(mesh binding) and `e84a910` (accounting). These are distinct missing inputs:

| Execution schema | Missing from the current execution contract | Current behavior |
|---|---|---|
| 1 | Saved parser/machine coordinates, mesh transform, printing duration and filament use | Specific refusal; retain original bytes |
| 2 | Mesh transform, printing duration and filament use | Specific refusal; retain original bytes |
| 3 | Printing duration and filament use | Specific refusal; retain original bytes |
| 4 | None by version alone | Full shape, file/job, geometry, mesh, material and separate deposition-envelope validation still required |
| Unknown/newer, missing or unreadable | Cannot establish a supported completed execution record | Specific refusal; no rewriting or automatic recovery |

Native review failures now preserve the bounded backend explanation in the
progress panel rather than replacing every refusal with a generic review error.
Neither this reporting nor version recognition migrates records. Historical
values must not be filled from current machine state or zeroed merely to satisfy
the schema. A supported interrupted-print upgrade/disposal policy remains an
open release requirement; the current change does not close it.


### Numbered review before preparation — 11 November, local

Recovery selection previously showed only status text until the backend created
an attempt receipt. The retained progress panel now starts with numbered
“Review saved recovery.” A refused review shows “Review saved recovery (blocked)”
and does not imply completed preparation. A successful review is gray; while
awaiting the attempt receipt, a numbered preparation-wait row is orange. The
actual receipt stages follow the completed review row once available, preserving
future/active/completed colors and live heating temperatures. Cancellation's
existing stage sequence is unchanged.

The lifecycle harness verifies review/refusal/wait/receipt transitions without
widget recreation or scroll loss. Local lifecycle test and ARM build passed; deployed acceptance is
tracked separately in the standalone completion checklist. No recovery command
or printer action was performed to test this presentation correction.

R128 activation follow-up: numbered recovery preflight is installed with exact
screen-artifact readback and native bootstrap Running. Configuration/PID/filament
preservation passed. Recovery-flow visual and physical acceptance remain open;
no recovery attempt was started for this installation check.

### Explicit retirement of incompatible evidence — implementation contract, 11 November

This defines the separate disposal path, implemented in the evidence store,
backend commands and native retirement worker/panel. Native-device acceptance
remains open; see the standalone completion checklist for deployment and test
evidence. The existing attempt-resolution command cannot serve this purpose: it requires a
valid attempt, readable execution and a matching job. Those prerequisites fail
for precisely the old, missing or corrupt records being retired.

**Compatibility policy.** Execution formats 1–3 cannot be promoted automatically:
the omitted historical coordinates, mesh and accounting cannot be reconstructed
from the current printer. Unsupported newer schemas remain untouched. Valid
current records use normal Continue or attempt resolution. An incompatible saved
print can instead be explicitly retired after review. Retirement means that
this exact saved evidence can no longer authorize recovery; it does not mean
that filament, calibration, machine position or the physical print is cleared.

**Read-only review.** Collect an allowlisted set of original bytes: the managed
job, execution, attempt and deposition envelope; both native `plr_dataA.ini`
and `plr_dataB.ini` checkpoints and their `.wmp-coordinates` sidecars. Record
absence explicitly. Bind the review to a printer session and a canonical
SHA-256 manifest covering each logical name, presence, size and byte hash.
Unreadable JSON is still preservable raw evidence. Permission errors, symlinks,
nonregular files, oversized files or changing reads refuse review rather than
being represented as absence. Do not scan arbitrary paths supplied by a client.
Display the actual incompatibility, any identifiable filename, and what will be
retained. An unidentifiable filename must remain unknown.

**Explicit confirmation.** Use a separate operation and protocol from recovery
Continue/Resolve; a failed recovery review must never implicitly authorize
retirement. Require a fresh matching manifest, the original session, idle SD and
pause state, no command/recovery worker, no unresolved material/tool/cancel
operation, heaters off, settled motion and known attachment. Review is read-only;
confirmation runs under command ownership. Recheck admission and file identities
after every filesystem operation that can yield. Do not home, mount, heat,
extrude, wipe, restore parser state or resume a print.

**Durable ordering.** Publish and fsync an immutable archive containing the exact
bytes and explicit missing entries; verify its hash and readback. Only then
atomically publish a retirement receipt bound to that archive and manifest.
Keep original evidence in place. Recovery admission recognizes whole-job
retirement only when the complete current evidence still matches the receipt.
A new print or externally replaced record cannot inherit an old retirement.
This avoids a multi-file deletion transaction and preserves support evidence.
A corrupt attempt may bypass normal restoration only after its own exact
identity and bytes match the verified retirement archive. This per-attempt
check remains valid when a subsequent job replaces the other records; it never
retires the new job or its checkpoint. Replacing even an identical attempt file
invalidates that exemption. Invalid unretired attempts allow the plugin to start
in an explicitly unresolved state so the UI can review them; normal machine
operations remain blocked. Never treat arbitrary parse failures as idle.
Missing/unreadable archives or altered receipts retain a visible unresolved
state. Neither startup nor a status poll executes retirement.

**Screen contract.** Offer REVIEW from the incompatible-record result, show a
numbered evidence review and confirmation, then an explicit DISCARD action with
“Discard recovery for this saved print?” text. Explain that original records are
archived and the physical print remains. CANCEL returns without changes. A
retained terminal receipt supports reopening; a lost acknowledgement queries the
receipt rather than submitting again. A successful result says recovery was
discarded, not that the printer has been reset or homed. Full native integration
and live visual acceptance are required before this path is considered complete.

**Required fault checks.** Cover each historical schema, corrupt/empty/missing
records, invalid file types, unsupported newer versions, archive write/fsync/read
failure, same-content replacement during review, edits between review/confirm,
restart before and after receipt publication, duplicate confirmation, lost
acknowledgement and a new job replacing old evidence. Prove no original bytes or
unrelated state change and no machine commands occur. Prove retired evidence
cannot Continue, changed evidence is not silently retired, and valid newer
prints retain their normal recovery path.
