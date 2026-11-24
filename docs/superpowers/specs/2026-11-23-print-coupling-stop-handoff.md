# SD print Stop must finish an admitted coupling approach and retreat

Status: implemented and live-qualified for cold SD dock/pickup and calibration docking Stop; see validation record.
Found by real cold qualification on candidate `5d785c3`.
No publication is authorized by this test goal.

## Reproduction and physical evidence

The real SD file `WMP_TRANSIENT_TOOL_STOP_8344ae200aaa.gcode` contains only a
marker, `_CHANGE_TOOL T=0`, M400, a dwell and a tail marker. It contains no heat
or extrusion commands. It starts with physical Head 3 mounted. Stop is requested
while that head reaches its own dock.

The job closes, but Stop interrupts before `_CHECK_AND_UNLOCK` can run its
native unlock/back-off. Position remains X168.36875/Y340.40625/Z300, matching
the saved Head 3 dock. Hall 4547 and sensor_b=True show the head still locked;
all dock switches are True because the carriage is pressed against the dock.
The material attachment is correctly unknown. The new transient cleanup refuses
this inconsistent post-drain attachment, leaving changing_tool=1 and cancellation
unknown. No tail marker runs. Heaters are zero and Z stays held.

The trace reports `Command invalidated by cancellation or restart; review again`.
The generation fence advances at print Stop before nested macro templates render
`_WMP_CHECK_DOCK_SUPPORT` and `_WMP_COUPLING_STROKE`. Existing permission only
finishes an already-entered actuator stroke; it does not protect dock approach
through unlock and mandatory retreat. `cmd_COUPLING_STROKE` also deliberately
raises after a stopped stroke, before its enclosing macro can retreat.

## Required fix

An immutable, same-actor, command-owned region must cover the admitted dock or
pickup approach through its native coupling, mandatory back-off and confirmation.
Arm after preparatory homing/observation, before entering the dock. Retire after
verified retreat, and always retire in a finally path on failure. The original
macro invocation, material/component identities, session, command generation,
head/kind, G-code actor/mutex and original SD filename/file-handle binding are
execution authority. A boolean flag or a request queued during Stop is not.

Only the same ordinary print Stop fence may finish this already-admitted region.
Do not permit new pickup, wipe, heating, model travel or file-tail work. Foreign
actors, replaced owners/files/sessions, extra generation changes, shutdown,
quick-stop and real coupling faults must keep refusing. Homing remains cancelable
before the protected approach starts. Keep external openACE/AFC behavior intact.

Possible implementation: wrap the real `_UNLOCK_TOOL`/`_LOCK_TOOL` invocation for
lifetime retirement, with bound BEGIN/END commands around the actual approach and
retreat. The existing generation checker can consult that proof for its known
coupling commands. Do not broaden the existing generation exception globally.
Actuator completion within the region must return to its native back-off rather
than throw early; ordinary Stop must be observed once the region is safely done.
Any macro change also requires review/update of the pinned recovery effect
contract, matched source package, and retained-dispatcher regression coverage.

Add host coverage for Stop during dock approach, actuator stroke and back-off,
and pickup counterparts; require actual retreat/confirmation before unwind and
no later stage. Cover stale/session/actor/owner/file/generation/fault rejection.
Repeat the exact cold SD test after the fix. The passed identification,
standalone and calibration cases do not prove this distinct SD ownership path.

Also review cancellation resolution: acknowledgement currently considers heater,
pause and recovery flags but not changing_tool. A failed transient cleanup must
not become an automatic acknowledgement while that marker remains set.

## Recovery already performed

A fresh generation-guarded native `_CHECK_AND_UNLOCK T=2` was admitted only after
checking Ready/idle, closed SD handle, exact saved dock position, supported and
locked Head 3, all zero heater targets, no fault and homed/held axes. It performed
the original support check, unlock, back-off to Y310 and post-retreat release
check. Only then was the normal changing_tool reset performed. All heads are now
docked; Z remained held and no Z movement occurred. No forced coordinates,
motor-off, restart, old-file replay or automatic retry was used.

A fresh reviewed cancellation-resolution token then acknowledged the independently
verified cleanup without motion. The original failed test and original failed
receipt remain preserved in the off-printer evidence. This recovery does not
make the failed Stop test pass.

Evidence: primary-repo `analysis/backlog-qualification-20261122/`:
`transient-print-tool-before.json`, `transient-print-tool-after.json`,
`transient-print-tool-refusal-sensors.json`, native-correction and resolution
before/after files, archived harnesses and correlated `results.jsonl` records.

## Local implementation under verification

`wmp_coupling_region.py` wraps the real native macro invocation and binds the
BEGIN/END region to its original actor, owners, mutex, session, generation,
head, geometry and SD file handle. Only the bound ordinary Stop can finish its
known coupling commands. The region retires in a finally path on any unwind.
No physical travel rates or actuator sequences were changed.

After a stopped pickup, verified head selection and its offset are adopted with
`MOVE=0` before unwinding, so the parent cannot apply an offset travel or start
wiping. Other service owners retain their existing post-mount adoption and Stop
checkpoints. Cancellation acknowledgement also requires changing_tool=0.

The retained vendor dispatcher executes the actual nested dock macro templates
in regression tests for Stop during approach, stroke and retreat, including
repeated wrapper installation. Separate pickup tests require no-travel frame
adoption before the Stop boundary. These are host checks, not live qualification.
