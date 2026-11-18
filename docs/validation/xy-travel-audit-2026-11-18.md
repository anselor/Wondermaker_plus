# XY travel audit — 2026-11-18

The user reported slow travel from the wiper to the center during homing,
requested an audit of other slow free travel, chose 300 mm/s for general clear
XY moves, and requested 500 mm/s where faster hot-nozzle travel reduces the
opportunity for ooze over the print.

## Findings and changes

Recent stored Orca jobs (`pa_pattern_147_5000_PLA_7m22s.gcode`,
`TFT Locomotive_PLA_2h52m.gcode`, and `OrcaCube_v2_PLA_1h53m.gcode`) all specify
`travel_speed = 500,500,500,500`. Live normal XY limit is 600 mm/s; the live
speed override was 100%. Those settings do not replace feedrates explicitly
specified by maintenance macros.

All rates below are mm/s; G-code F values use mm/min.

| Path | Previous requested rate | New requested rate |
|---|---:|---:|
| Homing center move | 50 | 300 |
| Clear cross-dock aisles and travel after controlled retreat | 200 | 300 |
| Main wiper approach | 200 | 500 |
| Off-bed filament service positioning | 100 | 500 |
| Return to print after wiping | 200 | 500 |
| Startup purge positioning, without extrusion | 167 / 83 | 500 |
| Pause parking after the existing successful Z-clearance branch | 100 | 500 |
| Bed-mesh XY travel | 300 | 300 |

Coordinates, routes, offsets, contact checks and operation ordering are
unchanged. Requested rates still obey acceleration, user overrides and machine
limits; short segments need not reach the requested top speed.

Brush strokes retain their configured rate (default 200 mm/s). Dock seating,
engagement and initial release/retreat retain their controlled rates, including
the final 16.7 mm/s dock seating segment. Sensorless homing taps and all Z/probe
rates are unchanged. Pause parking without available Z clearance remains at
100 mm/s. Front-edge idle parking, special recovery routes and calibration
contact/approach paths remain conservative rather than receiving a blanket
speed increase.

The mesh already requested 300 mm/s. Live probing uses 3.6 mm/s contact,
3 mm/s lift, two samples, and a 3 mm horizontal-move height. The retained vendor
helper uses the mesh speed for XY and probe lift speed for Z. Probe activation
temporarily lowers acceleration to 14 mm/s²; with the configured
`deactivate_on_each_sample=True`, vendor `probe_finish()` restores the configured
acceleration after each sample. No mesh or contact-accuracy tuning was changed.

Normal tool changes and wiping already bracket their acceleration and speed
override and restore the caller's values. Those mechanisms remain intact.
Standalone filament positioning retains its existing override behavior. The
legacy `_SAVE_SPEED`/`_RESTORE_SPEED` pair has no configured callers; normal
WM+ tool-return handling uses its separate retained-state implementation.

## Migration and packaging

A pre-motion check caught the preserved old `variable_return_speed=200` after
installation. No motion was issued by that refused check. Configuration
reconciliation now migrates exactly that former default to the new 500 mm/s
default. Non-default operator values, including 300 and 350, are preserved.
Tests verify the actual vendor parser, unchanged underlying custom config and
repeat installation. The override is owned and rollback remains receipted.

Native screen artifact remains
`935306b2b9ad11722926f00e234389f6e8614b5435a6be3816fe1308bba768f2`.
Compiled source hashes and the artifact were verified unchanged; runtime and
installer source hashes/archive were refreshed. Final source binding is current.

## Verification

Software checks passed:

- 116 affected macro cases covering homing, purge, pause, docking and pickup order.
- 126 standalone service cases.
- 114 recovery/cleanup cases, with two optional fixtures skipped.
- 93 tool-return/pause cases, with three old-vendor fixtures skipped; wiper
  checks separately assert 500 mm/s approach and unchanged 200 mm/s strokes,
  plus acceleration/override restoration.
- 116 configuration reconciliation cases, including default-only migration.
- 67 other configuration/migration/parser checks.
- 144 delivery checks; final source-bound package checked again after migration.

The final batch was installed using normal preserved configuration deployment.
Before physical testing, checks confirmed Z UART PC1, 64 microsteps, 8 mm
rotation distance, 200 full steps, 40/2 mm/s Z homing settings, 30 mm/s Z limit,
5000 mm/s² machine acceleration, probe offset -0.145 and the requested extruder
rotation distances (21.6485, 21.6485, 21.6485, 21.7441).

Guarded full G28 completed in 54.122 seconds with Head 3 attached. Total homing
time is not a controlled old/new comparison because its starting bed height
and homing contacts vary.

A controlled 214.87 mm cold wiper-to-center XY leg, with M400 at its endpoint,
took 4.642 seconds at 50 mm/s, 1.162 seconds at 300 mm/s, and 0.898 seconds at
500 mm/s. These observations include local command/observation overhead.
Z stayed unchanged, parser/override state was restored, no fault occurred and
all heaters stayed off.

Public mount actions then completed Head 3 → Head 4 → Head 3, confirming both
attachments and leaving fail_flag zero. Times were 15.913 and 17.152 seconds,
including actuator strokes, checks and normal idle positioning. Head 3 was
restored and all heaters remained off. This is cold travel qualification;
o hot-print quality improvement or reduction in actual stringing was measured.

Raw evidence and test scripts are retained locally in the ignored
`analysis/homing-center-travel/` directory. Nothing was pushed.
