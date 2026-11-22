# Factory-state extrusion timing comparison

Status: factory and all three reintroduction stages printed cleanly; original
extrusion symptom not reproduced after the clean reinstall.

## Observed factory result

After the verified stock restore, the user reported that the first PA test
finished cleanly, the Vehicles file finished cleanly, and a subsequent PA test
also finished cleanly. The first PA run was started through Moonraker on Head 3
using the unchanged `pa_pattern_147_5000_PLA_7m22s.gcode` at 220°C/55°C.
The later runs and their visual results are user-reported; continuous settings
capture, exact file hashes and restart boundaries were not independently
recorded for those later runs. These were completed-print tests, not a confirmed
stock-screen cancel-path reproduction.

Subsequent read-only Moonraker history confirmed all three jobs completed:
`pa_pattern_147_5000_PLA_7m22s.gcode`,
`TFT 2026 Vehicles Orca_ZRU_PLA_3h40m.gcode`, and
`pa_pattern_147_5000_PLA_13m3s.gcode`. The second PA therefore used a different
existing PA file; compare like-for-like on reintroduction.

This materially strengthens a WM+ software/configuration interaction as the
leading suspect, especially because the two-head print did not spoil the next
PA test. It does not yet identify a component or prove electrical motor timing
misalignment. Keep this stock state as the comparison baseline.

## Next controlled comparison

Reintroduce only the input-shaper backport first, retaining stock macros,
screen, bridge and Moonraker. Repeat PA → Vehicles → PA with the same files,
heads and effective settings, recording any restart boundary. If clean, add
the matched WM+ config/material/native-screen group and repeat. Add the
touchscreen bridge separately last. This respects the current package's
dependency group rather than installing incompatible screen/backend pieces.

If a stage reproduces the fault, capture effective PA, flow, retraction,
speed/acceleration limits and shaper state before any restart. Compare the same
stage after a restart, then narrow changes inside that stage. Completion and
cancellation paths need separate trials because the reported trigger is
state-dependent. Do not infer which component is responsible merely from its
installation causing a restart.

The shaper-only stage is installed and Ready. Its six files classify as the
known backport and its C helper is current. Remaining checked motion sources,
critical macros and screen still match stock; no WM+ library is mapped. Retained
settings are X `3hump_ei` at 81.8 Hz and Y `mzv` at 39.2 Hz. No recalibration or
other tuning change was made for this comparison. The backport changes the
definition of `3hump_ei`, so this is a software/definition comparison at retained
frequencies, not a claim of newly calibrated shaping.

A five-second observer records existing object status, cumulative toolhead
stalls and Klipper CPU-time deltas, plus Moonraker's existing one-second CPU
history (deduplicated). Klipper interval CPU is an average and cannot rule out
shorter peaks. No logging commands are inserted into G-code. Plate clearance is
confirmed before the first shaper-only print.

The user reported clean printing on the first shaper-only PA repeat and asked
to stop it. API cancellation returned success; subsequent status was standby,
unpaused, with no active virtual-SD job. Across 23 samples after purge, Klipper
CPU-time deltas averaged 19.96% of one core (maximum five-second interval
24.69%); Moonraker's 122 captured one-second samples averaged 13.15%, with a
99.61% peak. Toolhead stall count stayed zero and status queries succeeded.
The visible clean result despite a Moonraker CPU peak shows a peak alone does
not establish the extrusion defect. Short Klipper peaks are not resolved by
five-second averaging.

The user then reported healthy Vehicles printing through the colour change,
stopped it, and confirmed plate clearance. A subsequent PA start was initially
mapped to Head 3; the user requested red Head 1 for better contrast. That startup
was cancelled without restarting Klipper. Stock cancellation waited for the
startup macro and purge, after which the user cleared the plate. The same 7m22s
PA file then ran on red Head 1 and the user reported a clean result. Thus the
shaper-only PA → Vehicles → red PA sequence did not reproduce the visible fault,
including an additional startup cancellation. This does not exclude an
interaction between shaping and the remaining WM+ components.

The user stopped the clean red test and cleared the plate. The next stage adds
the matched config/material/native-screen group (and its required Moonraker
patches), retaining the shaper and excluding the touchscreen camera bridge.
Installation necessarily restarts the backend; do not treat the first clean
print after that restart as clearing the stage. Repeat the tool-change and
subsequent-PA sequence before drawing that conclusion.

Stage 2 completed its red PA → Vehicles colour change → red PA sequence without
a further Klipper restart, with each print reported clean by the user. The final
PA reached `complete` in the status capture. Its 80 samples with filament-used
above 25 mm had mean/max Klipper interval CPU of 26.44%/37.64% and deduplicated
Moonraker one-second CPU of 12.38%/23.21%; toolhead stalls stayed zero and queries
succeeded. These are capture-window summaries, not a controlled CPU benchmark.

The user confirmed the final PA was clean and the bed clear. Stage 3 adds the
touchscreen camera bridge to this working combination. The remaining full
combination has not yet been cleared by a multi-print comparison. Clean stages
do not establish the original fault's cause or rule out a longer-lived trigger,
an older mixed installation, or a workload not exercised here.

Stage 3 bridge installation passed service, snapshot and nginx endpoint checks;
Klipper was Ready with PID 1061851. The red Head 1 PA test was started, the user
was asked to leave the Fluidd Touchscreen stream open, and reported clean
printing, then stopped it and cleared the bed. Stream-view state was not
independently captured. The full-combination Vehicles comparison follows, with
no Klipper restart requested between these tests.

The full-combination Vehicles job subsequently completed successfully in
Moonraker history (16,088 seconds); the user reported no artifacts or issues
and cleared the bed. Klipper PID remained 1061851 when the final red Head 1 PA
was started, confirming no host-process restart across this stage. The bounded
observer expired during the long Vehicles run, so continuous CPU/stall coverage
of its later portion is unavailable. A fresh observer was started for the final
PA. The user reported that final PA still printed cleanly and cleared the bed;
the final captured state was cancelled with `plate_cleared: true`. In 22 samples
above 25 mm reported filament use, Klipper interval CPU averaged 23.43% with a
41.18% maximum; Moonraker one-second CPU averaged 12.34% with a 21.55% maximum.
Toolhead stalls stayed zero and no status-query errors were recorded.

## Result and remaining uncertainty

Stock printed PA → completed Vehicles → PA cleanly. Shaper alone and the matched
WM+ group passed the attended colour-change/subsequent-PA checks. The full setup
then passed PA → completed Vehicles → red PA with the same Klipper PID. No code
change to print motion was made during these comparisons. Camera stream viewing
was requested but not independently verified.

The original fault remains unexplained. The current component combination is
not sufficient to reproduce it in these tests; neither shaping nor CPU spikes
have been established as its cause. An older mixed deployment, stale loaded
state, a longer-lived trigger or a different workload remain possibilities.
Preserve this working installation for ordinary use rather than restarting or
reinstalling it again. If the symptom returns, capture current versions, process
identity, effective PA/flow/retraction/shaping, queue-stall counters and bounded
CPU history before restarting. Report deposited-filament defects separately
from visible motor motion or carriage freezes. Off-bed cancellation parking is
tracked as a separate behavior change; it was not changed during this test.

The previous fault disappeared after a Klipper restart, then returned after
multiple prints or a two-head print. Deposited gaps/blobs alone do not establish
that the extruder motor started late. A successful first print after restoration
cannot rule out the reported state-dependent fault.

## Preserve the comparison

- Keep the user's geometry, extruder rotation distances, saved offsets, heater
  tuning and other calibrated hardware settings. Record effective acceleration,
  PA, shaper and bed/nozzle targets for each run. Factory tool-selection PA
  behavior may differ from WM+; record the effective value rather than silently
  changing the factory macro.
- Keep uploaded G-code. Identify the exact stock-compatible PA and two-colour
  Vehicles files and record their hashes. Do not insert logging commands into
  one comparison file or change its extrusion/retraction settings between runs.
- Save current configuration off the printer before removal. A protected backup
  of 52 current `.cfg` files was captured locally on 2026-11-21. No broad log,
  machine-identity, service-file or installed-binary export was performed.
- Run uninstall preflight, then the verified removal. Confirm Ready and run
  `tools/verify_factory_state.py`. Resolve any mismatched source, macro, loaded
  library, stale C helper or retained WM+ dependency before motion.
- Independently check loaded Z rotation distance, microsteps and motion limits
  against the preserved configuration. Do not use position overrides or force
  moves as a shortcut. Do not send bootloader requests to CELL.

## Attended sequence

1. Confirm the plate is physically clear and the user can watch. Establish one
   normal first layer with the PA file. Record starts/ends, temperature, applied
   PA and any pauses. Stop and clear the plate between tests.
2. Repeat that file through the stock screen's cancel/start path without a
   Klipper restart. Keep the same head and material.
3. Run the two-head Vehicles file through at least one colour change. Inspect
   both colours, then cancel through the stock screen.
4. Run the same PA file again without restarting. This sequence matters more
   than a series of clean single-head starts alone.
5. If the fault returns, stop the print and record the observation before any
   restart. Distinguish deposited filament from visible drive-gear motion.
   Separate an XY freeze from an extrusion start/end defect.
6. Repeat only an agreed controlled comparison after a restart, keeping the
   same file and settings. Record whether it changes the result.

Use ordinary status and a bounded low-rate observer if needed. Avoid bulk motion
queue dumps or high-rate subscriptions that can change host load and confound
the test. Commanded step timestamps cannot prove actual physical motor motion.
If a dock, homing or adhesion fault occurs, stop; do not classify that run as
proof of extrusion synchronization. Clear the plate only after motion stops.

## Evidence and interpretation

Record the software verification report, exact file, head/colour, effective
settings, stop/start route, restart boundary, first-layer observation and any
stutters for every run. The conclusion may be “not reproduced”; do not claim the
fault is fixed or exclusive to WM+ merely because a few factory runs are normal.
A recurrence with the verified vendor baseline would show the fault can occur
without WM+ host code, while leaving its mechanical or firmware cause unresolved.
