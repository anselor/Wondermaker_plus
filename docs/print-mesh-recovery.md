# Power-loss recovery and first-tool probing

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
