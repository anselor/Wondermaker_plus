# Why recovery homes Z at the bottom

Empty-bed tests on September 14, 2026 found that homing only to the bottom endstop
preserved the measured Z reference on the test printer. WM+ uses that result to
establish Z before recovery pickup and XY travel, without probing the occupied bed.

Production recovery was later installed and completed power-cut print trials with
T0 and T2 probing heads; see [the recovery record](print-mesh-recovery.md).
This page records the investigation behind that decision. The optional diagnostic
used here is not included in normal deployment and was removed from the printer
afterward.

The measurements apply to this printer at the tested temperatures. They do not
establish accuracy for every machine, temperature, or mechanical change.

## Native homing versus the full homing macro

Native Z homing moves the bed down to its positive endstop, retracts 2 mm, seeks
again, and assigns Z300. It does not then move up to the nozzle or measure a new
nozzle zero. The configured first seek is 40 mm/s and the second is 2 mm/s.

The outer `Z_HOMING` macro adds head selection, center travel, a LEVELING pulse,
driver setup, and usually a return to Z7. Recovery also sends upward return commands
after homing. These operations must be distinguished from the native endstop seek.

The installed host modules matched extracted 1.1.08 files byte-for-byte. The main
MCU reported `KLP_MCU_WM_ZRU_20260408_185504`, matching the packaged firmware.
The CELL MCU reported `KLP_CELL_WM_ZRU_20251223_162212`; its image was not packaged,
so its internals were not inspected.

## Why the diagnosis changed

Normal homing was observed moving down and then up to nozzle contact. Recovery
also contacted the part. Those observations did not establish that contact reset
software Z zero. In the captured recovery, the client requested Z6.045160 and then
Z3.045160 after G28: real upward moves from the bottom.

The selected second checkpoint included a 2 mm tool-change lift. Its coordinate
meaning and consistency with file position required a separate investigation.
A saved Z value is not necessarily the sliced layer height. Later tests identified
and fixed the checkpoint's mesh/tool-coordinate error; sampling limits remain.

No separate bottom-to-nozzle measurement was found in the inspected native host
path. The candidate recovery reference was the configured bottom endstop plus the
print's saved mesh and tool offsets. Empty-bed tests checked whether the vendor's
additional preparation changed that relationship.

## Optional diagnostic commands

`klipper_extras/wmp_z_diagnostics.py` can be loaded explicitly as
`[wmp_z_diagnostics]`. It is an investigation tool, not a recovery command.

| Command | Action |
|---|---|
| `WMP_Z_SNAPSHOT` | Wait for queued movement, then log coordinates, mesh, and Z step counter; enqueue no movement |
| `WMP_Z_MAX_TEST` | Clear mesh compensation, enable driver diagnostics, run native Z-only homing, disable diagnostics, and log before/after state |

The test requires an idle, unpaused printer with the supported Z configuration and
already-inactive LEVELING/GANTRY signals. It leaves the bed at the bottom. It adds
no XY move, pickup, GPIO pulse, heater change, or upward return beyond the native
2 mm retract. Failure attempts driver cleanup and does not continue to a return.

It does not restore the old mesh/coordinates, save calibration, change recovery
information, or resume a file. Do not run it during an interrupted print.

When Z was previously homed, it estimates the endstop position in the earlier
coordinate frame:

```text
previous_commanded_Z + (after_MCU_steps - before_MCU_steps) * step_distance
```

The step counter survives coordinate relabeling within one connected MCU session.
It counts commanded motor steps, not measured bed motion. Missed steps or independent
movement invalidate that physical interpretation; it cannot bridge a power cycle.

Local tests check idle/state guards, supported endstop settings, inactive signals,
Z-only dispatch, absence of return motion, and cleanup. They cannot establish
physical repeatability.

## Empty-bed procedure used

1. Remove printed objects and loose material; leave the plate installed. Confirm
   idle state and have an observer present.
2. Back up configuration, install only the optional diagnostic and its include,
   restart, and check Ready. Loading it does not home.
3. Capture status and logs. Run `WMP_Z_SNAPSHOT`, then one `WMP_Z_MAX_TEST`.
4. Expect a downward seek, 2 mm retract, second seek, then stop. Unexpected XY,
   pickup, or a full upward approach requires stopping and investigating.
5. After confirming that result, move slightly from the bottom and repeat to
   compare endstop repeatability.
6. On the empty plate at stable temperatures, compare contact heights after
   normal preparation and after isolated bottom homing. Contact probing here
   measures the reference; it is never part of loaded-bed recovery.

The diagnostic itself performs only step 3's native home. Later moves and contact
measurements were separate commands after review of the earlier result.

## First home and repeats

The first test began unhomed and finished with only Z homed at reported Z300 in
about 13.65 seconds. X/Y stayed unchanged, LEVELING/GANTRY remained high, and heater
targets stayed zero. The Z step counter went from 0 to 442736 at 0.000625 mm/step.
The observer confirmed downward travel and only the short retract.

Three repeats used `G90`, `G1 Z280 F1200`, `M400`, then `WMP_Z_MAX_TEST`.
Each moved 20 mm away from the bottom before homing again, without XY movement or
heating. The prior feedrate was restored afterward.

| Home | Normalized Z step count at end | Difference from first home |
|---|---:|---:|
| Initial | 442736 | 0 mm |
| Repeat 1 | 442729 | -0.004375 mm |
| Repeat 2 | 442714 | -0.013750 mm |
| Repeat 3 | 442722 | -0.008750 mm |

The endpoint spread was 0.01375 mm in commanded-step coordinates. This small sample
did not independently measure nozzle-to-bed distance or test a power cycle.

## Contact-height comparison

Physical T0 was held at 140°C and the bed at 55°C, continuously within ±2.5°C nozzle
and ±1°C bed for 120 seconds before measurement. Each group contained three
`PROBE` measurements at X150 Y135, using the installed two-sample settings and
returning to Z7 between measurements.

| Group | Mean contact Z | Spread of three measurements |
|---|---:|---:|
| A1: normal | -0.474583 mm | 0.007813 mm |
| B1: max-only | -0.472604 mm | 0.004375 mm |
| A2: normal | -0.482396 mm | 0.011563 mm |
| B2: max-only | -0.484375 mm | 0.004062 mm |

The paired bottom-only minus normal differences were +0.001979 mm and -0.001979 mm,
smaller than the within-group spreads. This supported using the existing reference
without the outer preparation at these temperatures. Contact Z is a raw probe
coordinate, not a new offset to save. No mesh or offset was recalibrated or saved;
the test ended at Z300 with heaters off.

## Contact height after controller restart

`FIRMWARE_RESTART` reset the main MCU, CELL, HUB, EX_T, and all four tool boards.
Software position changed from [150,135,300], XYZ homed, to [0,0,0], unhomed.
The MCU print clock restarted. This tested loss of host state and controller resets,
not mains power loss to every electrical component.

After reheating with the same stabilization criterion, Z homed at the bottom before
X/Y homing and travel. Three contact measurements followed without the normal
888 ms preparation pulse. Ordinary probes still used their own 22 ms pulse.
Normal homing and three more measurements provided the control.

| Group | Mean contact Z | Spread of three measurements |
|---|---:|---:|
| C1: max-only after restart | -0.490313 mm | 0.009688 mm |
| D1: normal control after restart | -0.489792 mm | 0.003750 mm |

C1 minus D1 was -0.000521 mm. C1 differed from the last pre-restart bottom-only group
by -0.005938 mm. Both differences were within the observed spread and gave no
evidence that the normal preparation was needed to restore the reference.

Configuration and saved calibration stayed unchanged. The current-head saved
variables changed from 1 to 0 because T0 was deliberately selected. The printer
ended at Z300 with heaters off. The diagnostic was still installed at this stage
and was removed during the production-helper deployment.

## Decision and later implementation

Use native bottom homing before the first recovery pickup or XY movement, preserve
the print's mesh/tool reference, and avoid probing the occupied plate. Keep the
native retract and second seek. The measurements did not indicate a need for a
new bottom-to-nozzle calibration.

The early design considered changing the screen because its explicit recovery G28
occurs after pickup. Review found that `_CHANGING_TOOL` runs early enough to guard
that pickup. Production therefore uses that macro with `wmp_recovery.py`; a screen
patch is not needed for the initial ordering fix. The separate coordinate patch
was added later for the saved-position defect.

Integration first ran on an empty printer, then in physical power-cut print trials.
See [the implementation, trials, and remaining limits](print-mesh-recovery.md).

## Hardware and firmware reference

Z uses PC2 steps, PC3 direction, PD2 endstop, positive homing, and
`position_endstop=300`. `_LEVELING_TRIGGER_S` pulses main-MCU PB5 low for 888 ms;
GANTRY is PB4. Mesh probing pulses PB5 for 22 ms and reads nozzle contact on PB6.
The host source does not establish how the receiving hardware interprets the
preparation signals.

Decompilation of the main MCU found generic GPIO, step-queue, and endstop handlers.
The inspected endstop callback samples its input and stops motion; digital output
writes the configured pin. No Z-specific bottom-to-nozzle cycle was found in those
handlers. This does not prove behavior of every MCU function or external hardware.

Addresses below use image base `0x08008000`:

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

The embedded identify dictionary's zlib stream begins at file offset `0xae40`.
Command names were matched to the dispatch table using Klipper's recorded
[command-table generation source](https://raw.githubusercontent.com/Klipper3d/klipper/master/scripts/buildcommands.py)
as a format reference. No MCU patch was made.

## Local evidence paths

These files are under ignored `analysis/z-recovery-investigation/`, absent from a
normal checkout:

| Directory | Evidence |
|---|---|
| Investigation root | Downloaded source/status, identify dictionary, command table, decompiled handlers, and Ghidra project/logs |
| `max-test-20260914T051444Z/` | Backup, first command, status/motion/log capture; `repeatability/` contains repeats |
| `reference-test-20260914T053706Z/` | Contact comparison, probe history, thermal traces, and results |
| `restart-test-20260914T055229Z/` | Controller reset, contact results, exact commands, configuration comparison, and cleanup |
