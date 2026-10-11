# Return to the print after a tool change

WM+ returns the new tool to the saved print position after successful pickup,
offset setup, and wiping. It keeps a 2 mm lift during the return, then lowers to
the original printing height. The XY return runs at 200 mm/s.

The sequence was added for firmware 1.1.08 and loaded September 13, 2026. Later
two-color print trials exercised normal tool changes in both directions; see
[the recovery test record](print-mesh-recovery.md#physical-test-record).
The local tests cover failure paths without deliberately causing failed pickups
on the printer.

## When the return runs

It requires a running print, `START_PRINT.print_body_ready=True`, and
`_CHANGE_TOOL.save_position=1`. Startup, idle/paused selection, same-tool calls,
and calls without position saving do not return to a saved print point.

The startup check matters because Klipper already reports “printing” while it
runs `START_PRINT`. Without it, a tool change after meshing could return to the
last probe position.

## Sequence

1. `_WMP_TOOL_RETURN_BEGIN` saves logical G-code XYZ, coordinate modes, feedrate,
   and speed override before docking.
2. Check that XYZ is homed and enough Z travel remains for the 2 mm lift,
   including tool-offset changes. Lift once and keep it through retries.
3. Pick up the tool, verify success, apply its offsets and flow, activate its
   extruder, wait for its existing temperature target, and wipe.
4. `_WMP_TOOL_RETURN_FINISH` checks the resulting live state. If still printing
   and unpaused after success, return XY with at least 2 mm clearance, then lower Z.
5. Clear the pending return and restore modes, feedrate, and speed override.
   Keep the new tool's flow setting and issue no extrusion move.

A terminal failure clears the retry flag, does not wipe or return, and leaves
the lift in place. A later tool change captures a new destination. Starting a new
change also resets any unfinished return information.

Homed idle selection establishes a separate minimum 7 mm clearance, even when
selecting the mounted head. This covers the screen's T0 command before offset
calibration. Printing keeps its relative 2 mm lift.

## Why the coordinates are saved explicitly

A full `RESTORE_GCODE_STATE` can apply the old tool's coordinates or flow to the
new tool. In the reviewed vendor implementation, it saves raw coordinates but
does not restore the XYZ base/homing coordinates. For example, logical X100 with
old offset +1 saves raw X101; applying a new +3 offset before restoring can yield
logical X98. Restoring earlier produces a different wrong result.

WM+ saves logical coordinates and restores only the needed modes and speed.
The wipe's local save/restore remains valid because it happens after new-tool setup.

The earlier contributed return also used undefined variable names and returned
before success and wipe handling. Its `MOVE_SPEED=12000` was in mm/s;
200 mm/s corresponds to `G1 F12000`, since G-code feedrate is in mm/min.

## Tests and practical limits

`tests/test_toolchange_return.py` expands nested macros in execution order. It
covers successful and retried changes, terminal failures, changed offsets, flow
preservation, coordinate modes, overrides, no-return cases, missing homing,
Z limits, and the next change after a failure. Heater waits and hardware contacts
are simulated. Three vendor-method checks require local firmware extracts.

For a new firmware or geometry, observe a normal small tool-changing print:
pickup, wipe, XY return, Z descent, then extrusion. Local sequence tests cannot
measure physical clearance. Save surrounding slicer commands and `klippy.log`
if motion needs investigation.
