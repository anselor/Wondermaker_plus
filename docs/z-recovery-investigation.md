# Why recovery homes Z at the bottom

Latest field verification: User2 reports homing and docking/mounting now work,
with markedly improved Fluidd responsiveness after the memory fix. Two process
readings showed unchanged PID and RSS. The reported homing failure is resolved
by operator confirmation; the evidence below preserves the failure mechanism
and limits of causal attribution. User1 also confirms docking/release works.

## November 14, 2026 field report — failure recurred after reinstall

The temporary recovery below was superseded by a new report after installing
the latest push: platform lowering still fails. `klippy(16).log` records new
`ZRU-C016` shutdowns at 03:31:33, 03:49:01, and 03:51:17. In the last MCU dump,
the first post-halt Z move queues 41,670 positive steps before the next endstop
seek (26.04375 mm using the supplied 1,600 steps/mm configuration). The G-code
state at shutdown is Z296. The vendor homing code assigns this coordinate when
preparing the second seek after a 2 mm retract from Z300; it is not a measurement
of physical bed position. The same dump lacks the first hit's endstop/position
reply in its retained receive window, so the exact trigger/halt discrepancy
cannot be reconstructed from that dump alone.

The log also records multiple negative Z FORCE_MOVE commands between 03:50:18
and 03:50:43, before the last attempt. These may be manual repositioning after
the preceding fault; they do not establish its cause. The exact new homing
command and current installed configuration/hash are still needed. Do not
treat the earlier successful reinstall as a confirmed fix.

### Confirmed late-step mechanism; source of host delay still under investigation

The 03:49:01 dump provides a more complete first-hit record:

| Observation | Value |
|---|---|
| Endstop trigger received | host 5196.095091; MCU clock 3118203319 |
| Subsequent endstop reply | next_clock 3118197871; pin_value 1 |
| Actual halted Z counter | 44431 |
| Homing steps sent after the hit | 28,801 (12 × 2,400 plus one) |
| Next queued positive Z move | 15,819 steps, 9.886875 mm at the supplied steps/mm |

The first hit and queried endstop clock agree closely. The host sends steps in
roughly 0.6-second batches, rather than keeping its 50 ms homing segments ahead
of execution. The retained packet window does not contain the entire first
seek, so the following trigger counter is inferred, not directly logged:
retracting to Z298 with a positive 9.886875 mm move implies the host's corrected
halt coordinate was Z288.113125. Its inferred halt-minus-trigger correction is
therefore -19,019 steps, corresponding to a trigger counter of 63450 and about
396 ms at 30 mm/s.

The shipped MCU firmware explains how late generation can cause this discrepancy.
`klipper.bin` SHA256
`777af4b5bcb6800229e80f76aa590edf13cfa8ae240648573b93a5aa3c2a326b`
matches the extracted 1.1.08 and 1.1.13 image. Its step loader at `0x0800ae00`
clamps a late nominal step timestamp to the current cycle counter plus a minimum
interval. Raw instructions at `0x0800ae24–0x0800ae3e` and
`0x0800ae5a–0x0800ae78` confirm the behavior: literal `0x0800ae94` points to
`0xe0001000`, and the code reads the DWT cycle counter at offset 4. The fast
path adds 350 ticks; the other path uses the configured pulse duration.
The existing local decompile is
`analysis/z-recovery-investigation/mcu-motion-callbacks.c`.

Host `stepcompress.c` records nominal step clocks. Vendor `homing.py` subtracts
the trigger-time history position from the actual halted counter and adds the
difference to the Z300 reference. If actual execution lags nominal history,
this correction can be negative enough to turn the subsequent retract to Z298
into downward travel. This is a concrete mechanism consistent with the packet
trace; identifying which host work caused the delay remains necessary.
The concurrent touchscreen polling investigation is testing reactor load, not
assuming that response size or WM+ telemetry is the cause.

The initial guard in `BottomZ._home_move_end` rejected negative discrepancies
of two or more steps. Local physical-screen Home All subsequently produced a
nine-step discrepancy (0.005625 mm at 1,600 steps/mm), falsely stopping homing.
That evidence disproves the assumption that only one step of negative error
can occur in normal operation.

An intermediate revised guard used the native Z rail's actual retract distance and the
stepper's step distance: it rejects `delta_steps * step_distance <= -retract_distance`.
For the admitted positive-Z home, the commanded retract is
`-(retract_distance + correction)`; the rejected condition would consume or
reverse the retract. Nine negative steps still permit 1.994375 mm upward travel.
At 1,600 steps/mm, -3,199 steps permit upward travel, -3,200 consume the retract,
and the inferred -19,019 steps reverse it. The same bound rejects a grossly
shifted reference on the second seek; no additional retract follows that seek.
The native event runs before the first retract is queued. Failure handling
disables diagnostics, invalidates the reference, shuts down, and clears captured
geometry. Missing/nonfinite/nonpositive geometry is refused. This contains the
dangerous extra move; it does not by itself make a delayed home succeed or
establish the accuracy of every smaller discrepancy. Tests cover both seeks,
the field discrepancy, boundary cases, different step distances, invalid
geometry, and exclusion of unrelated homing.

The user subsequently requested removal of the added counter guard entirely.
That decision supersedes both guard variants above: `BottomZ` no longer hooks
`homing:homing_move_end` or compares halt/trigger counters. Native seek,
overshoot correction, retract, and second-seek behavior remain with the vendor.
Existing endstop checks, supported-configuration admission, diagnostic cleanup,
reference invalidation, and shutdown on native homing failure remain intact.
The status/allocation fixes address demonstrated sources of host load, but the
guard removal does not prove that all timing discrepancies are impossible.
The counter replay above remains historical investigation evidence, not a
description of an active protection.

A user reported additional downward travel and belt skipping during `G28 X`.
Their supplied configuration called `z_rise`, which invokes `_WMP_HOME_Z_BOTTOM`
when the Z reference is invalid. Z was configured with a 2 mm retract, positive
homing to Z300, 64 microsteps, 200 full steps/revolution, and 8 mm/revolution.

The supplied log's final failure (02:55:43) contains 22,057 queued Z steps after
the first endstop hit and before the second endstop seek: 13.785625 mm at 1,600
steps/mm. The queued direction is positive with the supplied non-inverted PC3
direction pin. The shutdown is the vendor Z stall detector's `ZRU-C016`. An
earlier bottom-Z home in the same log completed at 02:11:49. These observations
establish anomalous commanded travel; they do not establish its underlying cause.

The user subsequently reported that reinstalling WM+ restored Z homing, using
the version preceding the November 14 UI/docking fix push (`6d1f1a5`). Exact
installed before/after hashes and confirmation using the same `G28 X` path
are pending. The new docking/UI changes therefore do not explain the recovery.
Do not infer a broken endstop, a confirmed software fix, or a
specific cause from the successful reinstall alone. No Z-motion change was
released in response to this report.

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

## November 15 idle disconnection — Moonraker log evidence

User2 supplied `/mnt/c/Users/ansel/Downloads/moonraker(1).log` after reporting
an idle Fluidd reset. This local evidence file is not part of the repository.
The log supports a Klippy connection loss, not a Moonraker process restart:

- Line 4968 records the last Moonraker server startup at 03:54:06.358.
  There is no new server startup around the reported incident.
- Lines 5494–5544 show repeated Moonraker `EVENT LOOP BLOCKED` reports from
  04:18:01 through 04:19:17, lasting 5.35–17.75 seconds. Lines 5543–5566
  show Klippy requests pending for approximately 74–80 seconds.
- Lines 5567–5587 show Unix socket `ConnectionResetError`, including
  `Connection reset by peer`, then Klippy connection removal at 04:19:18.122.
- Lines 5858–5864 show the `ip -json -det address` failure at 04:19:22.782,
  after the stalls and socket reset. Read-only inspection of installed
  Moonraker confirms `machine.py:709–711` catches this exception, logs it,
  and returns. `shell_command.py:228–280` uses a two-second default timeout;
  the generic error alone does not distinguish timeout from another failure.
- Line 5920 records reconnection at 04:19:32.702; line 5924 records Klippy
  ready at 04:20:13.711. Moonraker continues logging throughout.

The network error is not evidence that it restarted Moonraker.
The subsequently supplied `/mnt/c/Users/ansel/Downloads/klippy(17).log`
confirms fresh Klippy process starts: line 33784 at 04:19:30.566 and line 34183
at 04:25:43.754. Both follow the previous session's normal startup/remote-method
registration messages without a logged preceding shutdown, exception, or
restart request. This differs from the explicit MCU resets and
`Restarting printer` at 04:12:06–04:12:08 (lines 33559–33568).
The new sessions' monotonic times increase from 1560.9 to 1934.0, consistent
with process relaunches rather than a host reboot. The records establish
repeated process starts but do not identify the termination mechanism or
initiator; a kill, crash, or service restart cannot be distinguished here.
The service/kernel journal has been requested, initially for 04:17–04:20;
the later 04:25 relaunch should also be included when available.

The subsequently supplied journal confirms the first termination mechanism:
at 04:19:17 the kernel OOM killer killed Klippy's Python process (PID 6359),
reporting `anon-rss:327780kB` and `total-vm:1674420kB`; systemd recorded
`klipper.service` exiting with signal 9/KILL. The journal describes roughly
422 MB anonymous memory and 9 MB free on the 512 MB board. Moonraker was about
42 MB. The `client invoked oom-killer` line identifies the allocation that
triggered OOM handling, not the source of Klippy's retained memory. This
establishes memory exhaustion for the 04:19 incident but does not identify
which component allocated or retained it, nor independently establish the
04:25 termination cause. Investigate memory growth before assigning blame.

Subsequent reproduction isolated repeated legacy filament INI parsing as a
collectable-allocation source. User2 confirmed the profile JSON is absent while
the saved presence JSON exists. For this exact file combination, 1,000 status
publications with cyclic collection disabled retained 92.8 MB in the original
helper versus 55 KB with the `253159d` profile snapshot. See
[the memory tests](ui/status-polling-latency.md#legacy-adoption-and-deferred-cyclic-collection).
This is a strong candidate for the observed OOM, pending stable field memory
after updating; the actual duration of deferred collection was not logged.

Vendor `klippy.py` disables automatic GC and constructs a GC-checking reactor.
In `reactor.py`, `_check_timers` collects only before the next timer is due and
when the preceding poll handled no file descriptors. Continuous FD readiness
can therefore suppress collection. `QueryStatusHelper` reschedules at callback
start plus 250 ms; work taking that interval can instead keep its timer overdue
and bypass the same idle collection branch. These source paths establish that
starvation is possible, not that ordinary low-rate polling always causes it.

Moonraker's event loop is separate from Klipper's reactor. The stalls warrant
investigation but do not by themselves establish the cause of the earlier
homing delays, or prove a shared cause or a WM+ regression.

## Subsequent calibration reports and local guard removal

User2's later `klippy(19).log` C015 occurred during Head 2's X-positive
alignment-sensor scan, after two successful Z probes and successful Y contacts.
The vendor AIR probing path uses the same C015 wording for those XY contacts;
this is not evidence of another bottom-Z failure. A missing contact and a sensor
error are not distinguishable from that log. Keep this report open pending field
confirmation; no speculative coordinate change was made.

Our local rapid-offset attempt initially still raised the removed counter
check (four steps): the helper had changed on disk but FIRMWARE_RESTART retained
the imported Python module. An actual Klipper service restart loaded `2d4682f`.
The subsequent screen-menu Rapid Alignment completed on all four heads,
persisted offsets and docked/released the final head. This verifies our local
bottom homing and rapid offsets after removal, not User2's separate contact scan.
