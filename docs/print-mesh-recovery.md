# First-tool probing, saved meshes and power-loss recovery

Implemented and deployed for vendor 1.1.08. First-tool probing is enabled by
default; explicit saved opt-outs remain effective. On 2026-09-14, two-color
prints completed after mains power cuts with T0 and T2 probing references,
correct tool mappings and restored per-print meshes. The T2-reference trial
also verified the corrected checkpoint writer and visual recovery result.

The complete implementation requires the config's native bottom-Z extra and
the touchscreen `recovery-fix` preload. The final suite passes 125 tests after
removing the unrelated chamber-fan cooling experiment. The dated findings
below record the defects discovered and the fixes validated during rollout;
known remaining client clearance and checkpoint-sampling limits still apply.

## Mesh ownership

- Fresh START_PRINT meshes use `PROFILE=wmp_print`, including explicit bounds,
  full meshes and native adaptive meshing. Native adaptive probing suppresses
  implicit profile saving in the vendor's bed_mesh.py, so START_PRINT also
  explicitly saves and loads the active mesh as `wmp_print`.
- G31/saved-default starts retain the T0 reference and load `default`, then
  copy that mesh into `wmp_print` for this print's recovery. Later changes to
  `default` cannot silently change the recovery snapshot.
- `SAVE_CONFIG_NO_RESTART` persists the snapshot before the print is marked
  ready. Persistence is required by power-loss recovery and is retained.
- G29 explicitly selects physical tool 0, even when logical T0 is mapped
  elsewhere. A bare/default BED_MESH_CALIBRATE and a normal default-profile
  load reject a nonzero probing reference. START_PRINT never overwrites
  `default`, even when requesting a full mesh.
- `wmp_print` is reserved for startup/recovery. The normal profile command
  rejects direct LOAD/SAVE/REMOVE of this name. Internal macros use the
  renamed native handler. Other named profiles retain ordinary Klipper
  behavior; their manual reference management remains the caller's job.

Existing default meshes are treated as T0 calibrations, matching the prior
G31 convention. This cannot determine the provenance of a mesh already
overwritten by an older configuration; regenerate an uncertain default
with G29. New guards prevent the automatic overwrite path going forward.

## Persistent print context

START_PRINT first invalidates the previous `wmp_print_context`. After the
mesh has been persisted and startup/purge have completed, it commits one
saved dictionary containing a schema version, physical probing tool, all
four tool-offset vectors, all four logical-to-physical tool mappings, the
filename encoded as UTF-8 hex, and mesh name. Context version 2 adds the
mapping; version 1 records cannot be recovered with the updated macros.
Filename encoding avoids G-code comment characters and ConfigParser percent
interpolation. It identifies the filename, not a cryptographic content hash.

The dictionary survives Klipper restart separately from the ordinary
`probe_tool` variable, which still resets to T0 for idle/manual work. End,
cancel and G29 invalidate the context. Power loss during an incomplete new
start therefore cannot reuse a previous job's reference. The macros use the
vendor's existing saved-variable and config-file persistence; this does not
add filesystem transaction/fsync guarantees to those vendor mechanisms.

## Verified vendor recovery integration point

Ghidra evidence: 1.1.08 `start_plr_print()` at **0x62d5d8**, retained locally in
`analysis/fw_1.1.08_diff/implementation/ghidra/calibration-fan-callers-strings.c`.
Its relevant sequence is:

1. Restore heater targets and the previously active physical tool, using
   temporary identity tool mappings, then restore the saved mappings.
2. Send `SET_GCODE_VARIABLE MACRO=Z_HOMING VARIABLE=z_raise VALUE=0`, then G28.
3. Re-select the interrupted tool, return to saved coordinates, then load
   either `default` or `adaptive_mesh` according to its saved leveling label.
4. Select the saved file, seek with M26, mark print_body_ready and send M24.

Before the client's early tool pickup, `_CHANGING_TOOL` checks the real Z
reference exposed by the required `wmp_recovery` extra. If invalid, it runs
`_WMP_HOME_Z_BOTTOM` before its XY home, docking or wiping. That command
bypasses homing_override and calls native Z-only homing, retaining the vendor
Z driver diagnostic setup and 2 mm retract/second seek. It leaves the bed at
the bottom, with no LEVELING pulse, XY move, nozzle contact or Z7 return.

The extra observes actual Z-rail homing events (including ordinary G28 Z),
and invalidates the reference at Z homing begin, Z motor disable, shutdown
and restart. Individual SET_STEPPER_ENABLE disables are covered as well as
M84. Merely setting coordinates cannot create a valid reference. The old
synthetic `z_rise` and `_raise_z` fallback paths also use bottom homing.
Normal idle tool selection, including selection of the mounted tool, benefits
from the same guard. The helper rejects resetting Z in an active print body
or paused print and shuts down on failure to block queued continuation.

The homing override recognizes the existing z_raise=0/full-G28 signal and
validates the context with `_WMP_RECOVERY_BEGIN`. It homes Z to the bottom if
the reference is still invalid, then homes only missing X/Y axes. It skips
the entire Z_HOMING preparation: no probe-tool pickup, center travel or
LEVELING pulse. It restores `wmp_print`, reapplies the mounted tool offsets
relative to the saved probing tool, and resets z_raise for normal operation.
When the early pickup already established XYZ, this branch does not rehome.

During this recovery phase, the BED_MESH_PROFILE wrapper routes the vendor's
legacy profile-load requests to the exact snapshot. M24 verifies the chosen
filename, active mesh and probing reference before delegating to native
M24 (renamed M9924), restores the recorded logical-to-physical mapping before
SD execution, then leaves recovery mode. Restoring at G28 alone is too early:
the client writes mappings again afterward. Normal M24 does not restore an
old mapping; it records any intentional mapping change from ordinary RESUME
in the matching print context for the next interruption. No touchscreen
binary changes are needed for this integration; the recovery signal is tied
to the inspected vendor sequence.

The normal print-body gate stays false during recovery preparation, so its
tool selections cannot trigger an in-print XY return. The vendor restores
the flag immediately before M24. Startup continues to announce the vendor's
recognized `adaptive_mesh` label for the private per-print recovery copy;
this label does not change the actual mesh's probing area or density.

## Invalid recovery

Missing context, a missing mesh, an invalid probing tool or changed tool
offsets stops recovery at its full-G28 boundary. The earlier tool selection
can already have homed XYZ at that point. A selected-file/mesh/reference
mismatch at M24 stops resumption. These paths invoke Klipper shutdown:
the touchscreen submits subsequent movement commands independently, so a
simple macro error would not reliably stop its continuation. A fresh print
is required after resolving the shutdown; no reference is guessed.

Recovery records from prints started before this implementation have no
matching context and are deliberately rejected. Do not upgrade/restart
configuration expecting to resume an already interrupted older print.

### Known limits of the retained client sequence

The max-Z guard fixes the initial unreferenced pickup/XY ordering. The client
still raises the bed to checkpoint Z + 3 **before** extrusion, wiping and
travel to the saved Y/X, then lowers nozzle clearance to checkpoint Z. It
does not keep the bed at the bottom through the entire recovery sequence.
Objects taller than that clearance along the return path can still collide.
Changing this client-side sequence is a separate follow-up; no touchscreen
binary patch was added for max-Z ordering.

Checkpoint selection also remains the vendor's. In the failed trial, A/B
records had the same file position but differed by the 2 mm tool-change lift.
The stock writer used toolhead XYZ, not simply slicer-layer XYZ; the
coordinate preload described below corrects that domain, but not sampling. Reconciliation must
include mesh, offsets, modal state and file position; do not blindly choose
lower Z or subtract a lift. Persisted changing_tool is useful evidence but
_CHANGE_TOOL clears it early. No new checkpoint-selection or forced re-docking
policy is included in this change. A detached part after cooling is not made
recoverable by restoring the coordinate reference.

## Validation

### Physical trial findings — September 13, 2026

The two-color cube print used physical T0/T2, with sliced T1 mapped to T2.
Normal tool changes succeeded in both directions and the user reported good
visual results. Power was interrupted during a T2-to-T0 change. The printer
rebooted Ready; board UUID assignments, the per-print mesh and context survived.

The user resumed and confirmed that recovery's center Z home contacted the
part. Two T0 layers then printed acceptably by visual observation, followed
by a sliced T1 selecting physical T1 instead of T2. The printer was paused.
This does not validate the Z reference after contact with the part.

Follow-up inspection distinguishes the observed contact from the native
homing primitive: native Z homing seeks the positive endstop and assigns
Z300; outer macros also pulse LEVELING and the client later commands upward
return travel. The earlier explanation that contact necessarily reset Z zero
was not established. See [the max-Z investigation](z-recovery-investigation.md)
for the inspected MCU/host paths and the prepared empty-bed diagnostic.

Captured recovery commands explicitly wrote `box_modify_t1=1` repeatedly,
including after recovery homing and before M24. Before power loss its value
was 2. The client also wrote identity pause backups just after M24. All four
board UUIDs remained correct: this is logical mapping loss, separate from
the earlier board-assignment incident. The version 1 W+ context and tests
omitted mapping restoration through the client's identity writes.

The version 2 correction saves the print mapping independently and
restores live mappings at recovery M24, after vendor setup. Subsequent stale
client writes to pause backups do not change live tool dispatch; PAUSE
already snapshots live mappings before resetting them for manual use.
Tests reproduce identity writes before and after G28, stale backup writes
after M24, and the next sliced T1 dispatch. An ordinary resume with a changed
mapping updates the context for subsequent power loss.

The initial unreferenced travel was addressed by the max-Z ordering change
above. Two saved checkpoints
also differed by the 2 mm tool-change lift at the same file position; selection
and consistency of interrupted-tool-change checkpoints need investigation.
Neither issue is fixed by restoring tool mappings. No recovery changes were
deployed or restarted during the paused physical trial. After the user
requested cancellation and deployment, the print was cancelled, heaters
were verified off, and only macros.cfg was uploaded. A firmware restart
returned Ready; the loaded config includes context version 2, while
printer.cfg (including calibration) and all four tool MCU configuration
files matched the backup. The previous print context was cleared by cancel.
At this stage the mapping fix had **104 passing offline tests**; the later
physical trials below verified recovery with the completed fixes.

### Offline coverage

`tests/test_print_recovery.py` executes the actual nested startup, homing,
context and recovery templates across a simulated restart. It covers:

- enabled defaults, explicit opt-outs and saved-default fallback;
- logical-to-physical mapping, including remapped logical T0;
- explicit-bounds, native-adaptive, full and saved-default mesh paths;
- preservation of default, persistence and restoration of the exact snapshot;
- context invalidation, changed offsets, missing data and mismatched files;
- filename quoting/encoding through the actual vendor SaveVariables methods;
- native command rename compatibility and rejection of default calibration
  under a nonzero reference.

Hardware contacts, probe readings and heater waits are stubbed. Physical
acceptance of the new recovery path remains a supervised recovery of a
suitable small print starting on a nonzero physical tool, checking the
reference and mesh before resumed extrusion. Previously reported normal
first-tool probing tests do not substitute for this recovery check.


### Deployment of max-Z ordering — 2026-09-14

Before deployment, backed up 57 configuration files and the optional diagnostic
module under `analysis/backups/pre-max-z-recovery-20260914T061559Z/`. Installed
`wmp_recovery.py`, then uploaded only printer.cfg and change_macros.cfg with
restart deferred. Config deployment preserves the existing SAVE_CONFIG block.
Removed wmp_z_diagnostics.cfg, wmp_z_diagnostics.py and its compiled cache;
the new printer.cfg has no temporary diagnostic include. Firmware restart
returned Ready with no configuration warnings, all axes unhomed and the new
reference marker false. The earlier mapping macros and touchscreen binaries
were not changed by this deployment.

The config component now requires SSH for installation because it installs
the required helper before configuration can restart. Direct config_sync.py
push does not install Python extras; use it only after that matching module
is installed. Status/diff/pull still use Moonraker HTTP.


### Empty-bed integration results — 2026-09-14

All tests below ran with an empty plate and no extrusion/heating commands:

- From a fresh restart, T2 selection homed native Z before XY and picked the
  correct physical T2. Sampled X/Y positions were unchanged until the real Z
  reference became valid. The final bed coordinate was 299.954063, including
  the existing T2 offset.
- After M84 and an explicit synthetic SET_KINEMATIC_POSITION Z=3, the homed-axis
  flag included Z but the real-reference marker remained false. Selecting the
  already mounted T2 established bottom Z before XY, ending at native Z300.
- An ordinary full G28 still selected the configured T0 reference and ended
  at Z7, confirming that normal homing retains its intended behavior.
- Recovery's early same-tool T0 selection established XYZ at the bottom. The
  later recovery G28 reused those axes without a second Z home or center move,
  restored wmp_print and a synthetic saved probing reference of physical T2,
  and reapplied T0's offset relative to it. The resulting Z300.045937 reflects
  that 0.045937 mm offset, not a return to the model.
- Replayed the vendor's motion sequence with a test checkpoint at Z40 (initial
  clearance Z43), wipe, Y/X return and legacy mesh-profile load. Omitted heater
  waits and extrusion because this was an empty-bed motion test. Selected a
  46-byte SD file containing T1, M400 and a completion message, then invoked
  the actual M24 wrapper. It restored mapping [0,2,2,3]; sliced T1 selected
  physical T2 and completed. The recovery active flag was cleared. The client
  subsequently issued PRINT_END, returning the printer to standby.

Two harness issues were diagnosed, with raw failure records retained:

1. The first manually synthesized context was built from Moonraker JSON,
   converting native offset tuples into lists. The existing strict comparison
   rejected it and shut down at Z300 with XYZ already homed, before recovery
   return movement. The retry used the actual _WMP_PRINT_CONTEXT_COMMIT macro,
   preserving the native types as production START_PRINT does. No calibration
   guard was relaxed. A regression test now covers native tuple offsets.
2. The one-second completion poll missed the transient complete state before
   the client PRINT_END reset it to standby. The independent 0.3-second monitor
   captured complete with physical T2, the correct mapping and recovery inactive;
   the console recorded the test completion message and Done printing file.
   This established success despite the harness timeout. Cleanup ran separately.

The test context used an existing saved mesh to exercise routing and reference
restoration; no new mesh was measured or saved. This was not a resumed physical
print and does not resolve the retained client's clearance/checkpoint limits.

Artifacts: `analysis/z-recovery-investigation/integration-20260914T062111Z/`
(initial ordering tests and rejected fixture) and
`analysis/z-recovery-investigation/integration-20260914T062555Z/`
(corrected context, recovery sequence, captured SD completion and cleanup).

Cleanup restored physical T0, the original mapping and probing preference,
cleared the temporary context, removed the test SD file, and parked at Z300
with all heater targets zero. Restarted only makerbase-client.service to clear
the stale shutdown dialog. The vendor touchscreen startup also restarted the
Klipper host (recorded at 14:31:00 in the printer log), so final software
coordinates reset to zero with axes unhomed and the reference marker false;
the bed remained physically at the bottom. Klipper returned Ready with no
warnings and all heater targets zero. Deployment verification
checks the preserved SAVE_CONFIG block, four tool-board files, saved calibration,
loaded helper source and absence of the temporary diagnostic.

### Physical print recovery — 2026-09-14

The two-cube print `Cube_PLA_17m19s.gcode` completed after a mains power cut,
Wi-Fi reconnect trouble, recovery, and a subsequent T0 filament-runout reload
and resume. The user confirmed that sliced T0/T1 selected physical T0/T2;
the logs show repeated correct changes both before and after the runout pause.
The original `wmp_print` mesh survived exactly, native saved offset tuples
matched the production context, and the bottom-reference completion was logged
before the recovery tool pickup. Completion logged `Done printing file` and
`PRINT_END`; final status was Ready/standby, unpaused, all heater targets zero,
empty recovery context, recovery inactive and print_body_ready false.

The cut interrupted a tool change with all four heads docked and target T0.
Checkpoint A pointed to byte 76447, the T0 command, with elevated saved Z3.5.
The subsequent sliced commands explicitly restored Z1.6 before extrusion.
No checkpoint was edited. This successful case does not establish general
handling of checkpoints that lack an explicit layer-Z restoration.

The user reported slow travel only after the recovery wipe. The touchscreen
issued explicit F3000 XY moves (50 mm/s); normal tool-change returns were
observed at 200 mm/s. The user accepted the recovery speed unchanged.
Paused filament loading also exposed the then-idle-only cooling-assist
restriction. Assistance was subsequently extended and tested, then removed
after cooldown measurements showed no benefit; see [the experiment](cooling-assist.md).

At this stage, visual quality at the recovery seam and a physical recovery
using T2 as the probing reference were still unverified. The later T2 trial
below completed that validation.
Artifacts: `analysis/print-validation-20260914T124401Z/`.

### T2 reference checkpoint coordinate defect — 2026-09-14

The next print swapped sliced T0/T1 to physical T2/T0. Startup selected T2 as
the probing reference; the user reported a good first layer. The production
context saved tool=2, mapping [2,0,2,3], matching offsets and `wmp_print`.
After a power cut, these all survived and dock sensors agreed with mounted T2.

Pre-Continue inspection found a different checkpoint case: A/B file positions
185799/185865 saved XYZ [188,252.3,4.29526], while matching pre-cut snapshots
recorded G-code XYZ [188,252.3,4.8] and compensated toolhead Z4.295262554799677.
The file resumes prime-tower extrusion before its next explicit Z command.
Recovery was therefore held at the prompt: replaying Z4.29526 as G-code with
the restored mesh would apply compensation twice and put the nozzle about
0.505 mm below its intended position. This is a checkpoint coordinate defect,
not a failure of the T2 reference or max-Z homing.

The `recovery-fix` touchscreen preload changes the checkpoint writer to G-code
XYZ and adds hash-bound format sidecars plus a guard before recovery starts.
See [client-preload/README.md](../client-preload/README.md) for exact scope,
legacy migration, crash behavior and remaining sampling limitations. Local
tests: 136 passed, including emulated ARM loads and actual C guard behavior;
the guard harness also passed on the printer's ARM CPU.

For this pending print, both records were migrated to [188,252.3,4.8] using
captured pre-cut samples at their respective file positions. Original records,
the migration plan and prior preload state are backed up in
`analysis/backups/pre-checkpoint-coordinate-fix-20260914T143857Z/`.
Print evidence is in `analysis/print-validation-20260914T140040Z/`.
Subsequent resumed-print and production-writer observations are recorded below.

Deployment verification read the running client's memory: all four XYZ load
patches and three entry hooks were present; cached XYZ was [188,252.3,4.8],
file position 185865, and the selected B checkpoint's format guard was valid.
The exact mesh, offset calibration and T2 recovery context were preserved.
After the touchscreen restart Klipper was Ready/standby, axes unhomed and all
heater targets zero. No recovery movement was requested during deployment.

After the user pressed Continue, the client guard accepted the migrated record.
Logs confirmed bottom-Z referencing before XY, recovery commands Z7.8 then
Z4.8, restored `wmp_print`/probe_tool=2/mapping [2,0,2,3], and SD resume at
185865. Subsequent physical T0 and T2 changes completed. Fresh A/B records
were written with valid format markers. At byte 197931 the new record saved
[188.25,247.550003,5.2], matching the client's float G-code coordinates; the
monitor at that file position showed raw toolhead coordinates
[188.171875,247.817187,4.746380194337592]. This verifies correction of both
tool-offset XY and mesh/tool-offset Z in the production writer. The user subsequently reported everything looked good, passing the visual
recovery-layer check. The second print subsequently completed: logs recorded `Done printing file`
and `PRINT_END`; final state was Ready/standby, unpaused, all heater targets
zero, recovery context empty, recovery inactive and print_body_ready false.
The tested T2-reference recovery, swapped mapping, corrected checkpoint
writer and completion cleanup therefore passed physical validation.
