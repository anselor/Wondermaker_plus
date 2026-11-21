# Factory-state extrusion timing comparison

Status: planned after the install-lifecycle branch passes review and the printer
passes factory-state verification. No print outcome is claimed here.

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
