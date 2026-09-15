# Recovery from the max-Z endstop: investigation, 2026-09-14

Status: empty-bed characterization passed, including contact-height
comparisons across a controller firmware restart. Max-only homing preserves
the measured Z reference on this printer at the tested temperatures.
Production max-Z ordering was subsequently deployed on 2026-09-14; see
[the recovery integration](print-mesh-recovery.md) for its validation record.
An actual resumed print after mains power loss has not been validated.

## Findings supported by the installed software

The installed `kinematics/corexy.py`, `extras/homing.py`, `mcu.py` and
`extras/tmc.py` match the extracted 1.1.08 payload byte for byte. The running
main MCU reports `KLP_MCU_WM_ZRU_20260408_185504`, matching the packaged image.
The CELL MCU reports `KLP_CELL_WM_ZRU_20251223_162212`; its image is not in the
1.1.08 package, so its internals were not inspected.

The active Z configuration uses PC2 steps, PC3 direction, PD2 endstop,
positive-direction homing, `position_endstop=300`, 40 mm/s first seek,
2 mm retract, and 2 mm/s second seek. Native `PrinterHoming.cmd_G28` with
only Z specified calls CoreXY's Z rail homing. It seeks the positive
endstop, retracts 2 mm, seeks again, and assigns Z300. That host path contains
no subsequent full upward nozzle-contact move and no measured nozzle-zero
calibration. It must not be confused with the outer homing macro.

`Z_HOMING` adds tool selection, center travel, `_LEVELING_TRIGGER_S`, driver
diagnostic setup, and usually a post-home `G1 Z7`. `_LEVELING_TRIGGER_S`
pulses main-MCU PB5 low for 888 ms. GANTRY is another output, PB4. The
meaning of those signals at their receiving hardware is not established by
the host source. Normal mesh probes separately pulse PB5 for 22 ms and
read the nozzle-contact input on PB6.

Ghidra inspection of the main MCU image found generic GPIO output, step
queue and endstop handlers in the relevant command path. The endstop
callback samples the configured input and signals the stop; the digital
output callback writes the configured GPIO. No Z-specific two-stage
bottom-to-nozzle cycle was found in these handlers. This is evidence about
the inspected paths, not proof about every MCU function or external hardware.

Relevant addresses (image base `0x08008000`):

| Function | Address |
|---|---|
| config_endstop | 0x0800a568 |
| endstop_home | 0x0800a024 |
| endstop sampling callback | 0x0800b094 |
| config_digital_out | 0x08009be8 |
| queue_digital_out | 0x08009cec |
| GPIO queue callback | 0x080083cc |
| config_stepper | 0x0800a3b4 |
| queue_step | 0x0800af04 |

Private evidence is under `analysis/z-recovery-investigation/`: extracted
identify dictionary, command table and Ghidra seed addresses; decompiled
handlers/callbacks; Ghidra project/logs; live status and downloaded source.
The dictionary's zlib stream starts at file offset `0xae40`. Command names
were matched to the embedded dispatch table, using Klipper's
[command-table generation source](https://raw.githubusercontent.com/Klipper3d/klipper/master/scripts/buildcommands.py)
as a format reference. This is not an MCU patch.

## What this changes about the diagnosis

The user observed normal homing travel down to max Z and then up to nozzle
contact. The resumed cube print also physically contacted the part. Neither
observation is disputed. However, the earlier explanation that the contact
necessarily reset the software Z zero was not established and should not be
treated as a verified mechanism. The native host routine establishes Z300
at the endstop. Later host travel or hardware controlled by LEVELING needs
to be distinguished from that routine.

In the captured recovery, the client requested `G1 Z6.045160` after G28 and
later `G1 Z3.045160`. Those are real upward return commands from the bottom.
The second checkpoint (including the 2 mm tool-change lift) was selected.
Its coordinate frame and its consistency with the selected file position
still need investigation; do not interpret a raw saved Z as slicer layer Z.

No independently saved bottom-to-nozzle measurement was found in the
inspected host homing path. The candidate reference is the configured max-Z
datum plus the original print's mesh, probing reference and G-code/tool
offsets. Hardware tests must determine whether the vendor GPIO sequence
changes the physical relationship to that software datum.

## Prepared optional diagnostic

Source: `klipper_extras/wmp_z_diagnostics.py`. It is not part of the normal
deployment and is not included in `config/live`.

When explicitly loaded as `[wmp_z_diagnostics]`, it provides:

- `WMP_Z_SNAPSHOT`: waits for queued motion to finish and logs coordinates,
  homing origin, active mesh, commanded Z and the Z MCU step counter. It
  does not enqueue motion.
- `WMP_Z_MAX_TEST`: accepts only an idle, unpaused printer with the inspected
  Z geometry and already-high LEVELING/GANTRY outputs. It snapshots state,
  clears the active mesh without moving, enables the existing Z driver
  diagnostic mode, directly invokes native `PrinterHoming.cmd_G28` with
  only Z, waits for completion, disables diagnostic mode and snapshots again.
  It bypasses the G-code homing override entirely. There is no XY travel,
  pickup, LEVELING/GANTRY pulse, heater change, or post-home upward return.
  The native 2 mm endstop retract remains. On native homing failure the
  helper attempts to restore driver mode and does not continue to a return.

The helper does not restore the old mesh or old coordinates, save calibration,
modify recovery context, or resume a file. It leaves the bed at the native
max-Z position for inspection. Do not use it during an interrupted print.

If Z was already homed, the report also estimates the endstop's coordinate
in the previous frame:

`previous_commanded_Z + (after_MCU_steps - before_MCU_steps) * step_distance`

The normalized step counter is preserved through coordinate relabeling
within a connected MCU session. It counts motor commands, not an encoder
measurement; missed steps or independent mechanical movement invalidate the
physical interpretation. This calculation cannot bridge a power cycle.

Tests cover no motion on load/snapshot, idle/paused guards, incompatible
endstop rejection, active GPIO rejection, native Z-only dispatch, no macro
return or GPIO pulse, and driver cleanup on homing failure. They do not
establish physical endstop repeatability or independent-controller behavior.

## Empty-bed procedure to review before installing or running

1. Remove the failed cubes, prime tower and loose material. Keep the plate
   installed. Confirm the printer is idle and an observer is present.
2. Back up configuration, install only the optional diagnostic extra and
   its include, restart, and verify Ready. Installation runs no homing.
3. Start read-only motion/status and Klipper log capture. Run
   `WMP_Z_SNAPSHOT`, then exactly one `WMP_Z_MAX_TEST`.
4. Expected motion: downward to the max stop, a short 2 mm endstop retract,
   the second downward seek, then stop. No XY, tool pickup or full upward
   approach should occur. If it does, stop the test and investigate the
   hardware control path; do not proceed to a loaded-bed recovery trial.
5. Review the observed movement and logged result before any subsequent
   motion. If the first stage behaves as expected, make a small controlled
   move away from the bottom, repeat max homing, and compare repeatability.
6. With the same tool and stable temperatures on the empty bed, compare
   bed-contact measurements after normal vendor preparation versus the
   isolated max-home path. Contact probing is allowed only for this empty-bed
   characterization, never as a recovery operation. Determine whether the
   original mesh/reference remains valid and quantify the Z difference.

Steps 5–6 need a concrete coordinate/temperature sequence after the first
result; they are not bundled into the diagnostic command. The initial trial
is deliberately one native max-home operation with no subsequent return.

## Production design after the measurement

If max-only homing preserves the required reference, recovery should establish
that reference before all XY or pickup activity. The existing client selects
a tool before its explicit recovery G28, so changing Z_HOMING alone is too
late. The client entry sequence or its first motion path must be changed.
Then restore the print mesh and offsets, select the intended physical tool,
and return using coordinates reconciled to the saved file checkpoint.

If the vendor preparation shifts the endstop-to-print relationship, capture
that relationship during the original empty-bed startup and persist it with
the print. Do not manufacture it from the nominal number 300. If it cannot
be established reliably, max-home recovery is not ready to implement.

## First empty-bed test — 2026-09-14

After the user confirmed the plate clear, backed up the live printer.cfg and
saved variables, installed the optional extra with a separate config file,
and added a temporary include at the top of the live printer.cfg. The repo's
config/live/printer.cfg was not changed. Firmware restart returned Ready
with no configuration warnings. The extra remains explicitly installed for
this investigation; ordinary config deployment does not include it.

Sent only `WMP_Z_SNAPSHOT` followed by one `WMP_Z_MAX_TEST`. The command
returned successfully in approximately 13.65 seconds. It began with no
homed axes and finished with only Z homed, at reported Z300. X/Y stayed at
their pre-test coordinates. Both LEVELING and GANTRY remained high in every
captured status sample. Heater targets remained zero. The normalized Z step
counter changed from 0 to 442736 (step distance 0.000625 mm); these are
commanded steps, not independent physical measurements.

The software trace contains no full upward return. The user confirmed:
"Moved down and stayed at the bottom, with only a short retract." This
establishes the observed behavior of this isolated stage on the machine;
it does not by itself validate the old print's Z reference or recovery.

Private backup, exact command, motion/status capture and Klipper log:
`analysis/z-recovery-investigation/max-test-20260914T051444Z/`.

### Repeatability at the bottom

After the physical confirmation, ran three cycles of `G90`, `G1 Z280 F1200`,
`M400`, `WMP_Z_MAX_TEST`. X/Y remained unchanged and heaters stayed off.
Each cycle raised the bed 20 mm from the bottom, then sought the max endstop
again. All completed successfully. Restored the prior feedrate afterward
without moving. The final reported position is Z300.

| Home | Normalized Z step count at end | Difference from first home |
|---|---:|---:|
| Initial | 442736 | 0 mm |
| Repeat 1 | 442729 | -0.004375 mm |
| Repeat 2 | 442714 | -0.013750 mm |
| Repeat 3 | 442722 | -0.008750 mm |

At 0.000625 mm per step, the recorded endpoint spread across all four homes
is 0.01375 mm. This is a small preliminary sample of endstop repeatability
in motor-step coordinates, not an independent nozzle-to-bed measurement.
Raw commands, results and motion capture are in the trial's `repeatability/`
subdirectory. It does not establish repeatability across a power cycle,
temperature change, or the vendor's LEVELING preparation.

The contact-height comparisons below followed this repeatability check.
They characterize the reference on an empty plate; they do not introduce
probing into print recovery.


### Contact reference: normal versus max-only homing

With the user's authorization to perform the required empty-bed tests, used
physical T0 at 140°C and bed at 55°C, with 120 seconds continuously within
±2.5°C nozzle / ±1°C bed before beginning. Compared normal `G28` (including
vendor LEVELING preparation) against native max-only homing. Each group
contains three `PROBE` measurements at X150 Y135, each using the installed
two-sample probe settings. Raised to Z7 between measurements. Contact probing
here measures the reference on an empty plate; it is not part of recovery.

| Group | Mean contact Z | Spread of three measurements |
|---|---:|---:|
| A1: normal | -0.474583 mm | 0.007813 mm |
| B1: max-only | -0.472604 mm | 0.004375 mm |
| A2: normal | -0.482396 mm | 0.011563 mm |
| B2: max-only | -0.484375 mm | 0.004062 mm |

The paired differences (max-only minus normal) were +0.001979 mm and
-0.001979 mm, both smaller than the within-group measurement spread. These
measurements support preserving the existing Z reference without the outer
vendor homing preparation on this printer at these temperatures. Absolute
contact Z is the raw probe coordinate, not a new calibration to save.
No offsets or meshes were recalibrated or saved by this test. The test ended
parked at native Z300 with all heaters turned off.

Private commands, responses, individual probe history, results, motion and
temperature capture: `analysis/z-recovery-investigation/reference-test-20260914T053706Z/`.
The subsequent comparison below restarted the controllers before establishing
max Z and returning to the measurement point.


### Reference after controller reset

Sent `FIRMWARE_RESTART` with the bed parked at the bottom and heaters off.
Klipper logs record reset commands to the main MCU, CELL, HUB, EX_T and all
four tool boards, followed by reconnection. Before restart, position was
[150, 135, 300] with XYZ homed; afterward it was [0, 0, 0] with no homed axes.
The MCU estimated print clock also restarted. This exercises loss of host
position state and resets the configured controllers; it is not a mains
power interruption of every electrical component.

Reheated physical T0 to 140°C and bed to 55°C using the same stabilization
criterion. Established max Z before `G28 X Y` and any XY travel, then measured
at X150 Y135. No normal Z homing or 888 ms LEVELING preparation ran before
these measurements. Ordinary measurement probes retain their own 22 ms
activation pulse. Followed with normal homing and another three measurements
as the control.

| Group | Mean contact Z | Spread of three measurements |
|---|---:|---:|
| C1: max-only after restart | -0.490313 mm | 0.009688 mm |
| D1: normal control after restart | -0.489792 mm | 0.003750 mm |

C1 minus D1 is -0.000521 mm. C1 differs from the last pre-restart max-only
group by -0.005938 mm. Both are within the observed measurement spread and
provide no evidence of a lost reference that normal homing needs to restore.
These are small-sample results, not a universal accuracy guarantee across
machines, materials, temperatures or mechanical changes.

The test completed successfully and parked at native Z300 with all heaters
off. Remote printer.cfg and macros.cfg remained byte-identical to their
pre-measurement backups. Saved calibration values were unchanged; the only
saved-variable changes were current_extruder and current_extruder_backup
from 1 to 0, reflecting the test's deliberate selection of physical T0.
The optional diagnostic was still installed at the end of characterization;
it was removed during the subsequent production-helper deployment.

Private evidence: `analysis/z-recovery-investigation/restart-test-20260914T055229Z/`
contains the script, reset evidence, before/after state, exact commands,
probe responses, motion/thermal trace, configuration comparison and results.

### Decision and remaining implementation

Use native max-Z homing as the recovery reference on this machine, preserving
the original print's saved mesh and tool-offset reference. The measurements
do not indicate a need for a new bottom-to-nozzle calibration or any recovery
probe of the plate. Keep the native 2 mm endstop retract and second seek.

This establishes the feasibility of the homing primitive, not completion of
the recovery fix. The production sequence must still:

1. Validate the saved print context and home Z to the bottom **before the
   client's first tool selection or XY movement**. The existing full-G28
   recovery hook runs too late for that first pickup.
2. Bypass the outer normal Z-homing preparation and its center travel during
   recovery. Home XY with the bed already down, and keep the bed down through
   tool selection. Do not perform nozzle-contact probing.
3. Restore the exact print mesh and tool offsets, reconcile the selected
   saved checkpoint's coordinate frame (including interrupted-tool-change
   lifts), and return to the print at the correct height. Preserve the
   separately deployed mapping restoration before SD resumption.
4. Validate the integrated sequence on the empty printer, then perform a
   physical print/power-cut recovery trial. The old recovery path remains
   unchanged by these diagnostic tests and is not yet accepted for use.


### Subsequent production implementation

The design review found that the existing _CHANGING_TOOL path is early enough
to guard the touchscreen's first pickup. The production change therefore uses
that macro and a native Klipper helper; a touchscreen patch is not required
for the initial ordering fix. The preceding design checklist records the
investigation state, not a claim that a client patch was necessary. See
[the deployment and known limits](print-mesh-recovery.md) for the implementation.
The optional diagnostic module, config and cache were removed from the printer
after the production helper was installed; no diagnostic include remains.
