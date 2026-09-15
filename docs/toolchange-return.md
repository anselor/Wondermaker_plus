# Explicit XY return after toolchange

Implemented in `config/live/change_macros.cfg` for the 1.1.08 rebase.
Stock baselines are unchanged. Deployed on 2026-09-13 with Klipper Ready;
offline sequence tests pass. Physical motion validation remains outstanding.

## Sequence

1. `_CHANGE_TOOL` calls `_WMP_TOOL_RETURN_BEGIN` once before checks/docking.
   It reads `printer.print_stats.state` and `_CHANGE_TOOL.save_position`
   explicitly. For a real printing toolchange with save_position=1 and
   START_PRINT.print_body_ready=True, it
   captures the original G-code XYZ, coordinate modes, feedrate and override.
2. Require homed XYZ and room for the 2 mm print lift, including offset
   transitions. Raise once and retain that lift through retries.
3. Dock/pick up, verify success, apply the new offsets and flow, activate
   the extruder, wait for its existing target, and wipe.
4. `_WMP_TOOL_RETURN_FINISH` evaluates after those commands execute.
   On success while still printing/unpaused, maintain at least original
   Z+2, return XY at 200 mm/s, then lower to the original logical Z.
5. Consume the pending return and restore the caller's modes/feedrate/
   override without changing the new tool's flow or issuing any E movement.

The return uses the new tool's coordinate transform. No full
`RESTORE_GCODE_STATE` is used for the toolchange. The existing wipe's local
state restore remains valid because it runs after new-tool setup.

Startup, manual/paused, same-tool and save_position=0 operations do not return
to a print position. print_stats is already "printing" during START_PRINT;
the body-ready gate prevents a post-mesh toolchange from returning to the
last mesh point. Homed idle tool selection establishes the calibration
minimum of 7 mm even for the already-loaded tool; the display sends T0
before PROBE_CALIBRATE. Printing retains its separate 2 mm relative lift.

Terminal failure clears the retry flag so `_CHECK_CHANGE_TOOL_AGAIN`
cannot mistake the vendor's subsequently cleared fail_flag for success.
A failed change never wipes or returns and leaves its print lift in place.
A later change captures a new destination. An interrupted macro cannot run
a stale finish automatically; the next `_CHANGE_TOOL` resets its context.

## Why the contributed SAVE/RESTORE needed reconciliation

The vendor's bare printer_state/save_position names were undefined in
`_CHANGING_TOOL`. Enabling them alone returns before success/offset/wipe
handling. The proposed MOVE_SPEED=12000 is mm/s; the stated 200 mm/s intent
corresponds to G1 F12000.

Tests executing the extracted vendor state methods establish that SAVE
stores raw coordinates, while RESTORE does not restore XYZ base/homing
coordinates. Logical X100 with old offset +1 saves raw X101: restoring it
before applying new offset +3 produces logical X101; restoring after the
new offset produces X98. Full RESTORE also overwrites the new tool's flow
factor with the old tool's factor. Capturing logical coordinates and
restoring only the needed modes avoids these problems.

## Validation

`tests/test_toolchange_return.py` expands the actual nested Jinja macros
at execution time. Hardware contact checks and heater waits are stubbed.
Cases include success, retry-success, terminal pickup/sequence failures,
logical coordinates across different offsets, retained new-tool flow,
absolute/relative modes, speed overrides, no-return paths, missing homing,
Z limits, and a new change following a failed one. Additional cases cover
calibration clearance and idle same-tool selection before offset moves.

The three vendor-method checks require the local extracted firmware source
and skip when it is unavailable. The remaining sequence checks run without
firmware artifacts.

Supervised acceptance remains: a normal small print with a toolchange,
checking pickup → wipe → XY return → Z descent, clearance and resumed
extrusion. Retain surrounding slicer G-code and klippy.log if behavior
needs investigation. Failed pickups are tested offline, not induced.
