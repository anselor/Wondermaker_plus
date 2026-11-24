# Standalone homing cancellation: route evidence and implementation requirements

Status: touchscreen Home and otherwise-unowned top-level G28 ownership/UI are
implemented and locally tested. Supervised physical qualification remains open.
The ongoing print is reserved. No printer access or motion qualification.

## Verified stock route

Supported client SHA256:
`b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715`.
The XYZ screen has separate worker functions; each first calls its command
sender, which submits one exact G28 string through `run_a_gcode` at 0x614338.

| Worker | Sender | Command |
| --- | --- | --- |
| x_homing 0x52810c | 0x614f74 | G28 X |
| y_homing 0x52834c | 0x614ff0 | G28 Y |
| xy_homing 0x528590 | 0x614ef8 | G28 X Y |
| z_homing 0x5287e0 | 0x61506c | G28 Z |
| xyz_homing 0x528a30 | 0x614e7c | G28 |

`tests/test_standalone_home_stock_route.py` verifies actual branch instructions
and file-backed command literals. Together with the real macro boundary tests,
23 checks pass. This proves the route, not cancellability or physical safety.
The click handler at 0x526770 uses userdata 10/11/12/13/14 for
X/Y/XY/Z/XYZ. Actual instruction emulation confirms that each idle/ready
click constructs its matching worker and submits it to `enqueue_event`
(0x655874); printing or non-ready backend states submit no worker. Therefore
these are queued workers, not synchronous motion inside the LVGL callback.
The implementation below bypasses those post-send worker status loops and uses
the bound backend outcome instead of treating stock client messages as proof.

## Existing backend boundaries and remaining ownership

`wmp_xy_homing.XYHoming` checks before/after native axis homing returns and
between fixed-X Y confirmation approaches. The homing override checks after
XY completion and before Z positioning. Existing shared stop observation only
recognizes bound calibration or managed-print ownership. It intentionally does
nothing for an unbound standalone Home; merely adding a Cancel button would
therefore be misleading.

Retained stock `extras/homing.py:PrinterHoming.cmd_G28` catches command errors
from `kin.home` and calls `stepper_enable.motor_off()`. Never inject a cancel
exception inside that try block. Stop between completed native calls, outside
that handler. Preserve holding torque and established axis references; an
interrupted Y verification must retain its existing invalidation behavior.

## Required implementation

- Trace XYZ event controls, worker admission and completion/error states; retain
  GUI responsiveness and reject stale/hidden/repeated requests.
- Bind standalone Home to a session/request/ticket and the shared out-of-band
  stop transport. Do not add a global stop flag or queued Cancel G-code.
- Preserve requested axes and parameters. Nested homing already owned by a
  print, calibration or filament service must keep that owner.
- Show CANCEL for the entire owned run; check between native axes and service
  phases. Let lock/unlock coupling strokes finish.
- Drain accepted moves and report the last verified phase. Do not synthesize
  position, disable motors, restart, or automatically dock without valid Z and
  tool-state authority. Unconfirmed completion blocks subsequent motion.
- Exercise actual vendor dispatch, cross-operation races, early/late Cancel,
  fault versus Cancel precedence and stale receipts before ARM packaging.
- Keep supervised physical qualification pending until explicitly available.

## Local implementation

The five XYZ Home clicks now enter a dedicated Home progress overlay and queue
one `_WMP_HOME_COMMAND` through the existing background command transport.
The vendor Home/status-loop workers are not queued by these clicks. Other XYZ
controls retain their original callback when no owned Home overlay is active.
A fresh external-manager owner keeps the original Home callback; stale owner
status never permits that fallback, and the standalone backend entry refuses
openACE/AFC without consuming its ticket.
The overlay's title and CANCEL/DONE share one header; body text uses the common
progress renderer without a redundant split. Unchanged views are cached.

The backend entry reuses the calibration command owner's session/request/ticket
admission and its out-of-band Cancel endpoint. An immutable `operation=home`
distinguishes the attempt. Only the five exact stock G28 commands are admitted;
legacy/unbound Home requests, saves and other calibration/motion commands are
rejected. A completed Home ticket becomes terminal rather than remaining open
for calibration stages. Raw G28 and nested managed-print/calibration requests
retain their existing owners; no global G28 interception is installed.

On Cancel, this owner cools only its own changed heaters, drains accepted moves
and holds position. It never automatically docks or performs a second home.
Native G28 still completes before a boundary can raise. Implicit stop checks
require the executing command greenlet's ownership; an unrelated reactor
callback cannot consume this pending stop. An actual homing fault remains the
primary error even if Cancel also arrives. That case reports holding as
unconfirmed unless a genuine cancellation boundary was recorded; stock native
homing can disable motors for actual faults.

Nested tool preparation now calls the same `_WMP_HOME_XY` helper under standalone
ownership, avoiding `homing_override.in_script` bypass into a combined native
XY call. A stop point follows the initial completed bottom-Z reference before
XY starts. External managers retain the vendor nested homing route.

HTTP success alone does not release the UI reservation. Fresh matching backend
session/request/ticket/operation and a terminal outcome are required, along
with return of the delivery worker. Stale or foreign receipts keep the hold.
An unexpected Klipper restart explicitly reports an unconfirmed result; it
never replays the operation. DONE only dismisses this overlay.

Local qualification: expanded backend/checkpoint/resonance/bottom-Z/homing
batch 335 passed; final Home checks 25 passed, including both retained-native
Y/X stop boundaries; scrub regression 49 passed. Native hook/profile checks
passed (3); the final native lifecycle outcome run passed (1), exercising all
five controls, bound Cancel, normal completion despite a lost command response,
ordinary failure, restart, stale/foreign receipts and unchanged-view caching.
Matching package/installer tests passed 244 checks.
All 25 config files validate. ARM SHA256:
`9b3dcc51b6340cb056e0bb02854d4dbf1464c35c90a716ae050c8f173a2ca69d`.
The delivery export verifies against the exact stock client and current bound
sources. Raw G28 ownership is now covered by `2026-11-19-raw-home-ownership.md`.
Physical qualification remains open.
No printer installation or push.

The later raw-Home adapter preserves the original command object and callback,
keeps nested manager/macro ownership, and lets the same dialog observe a fresh
backend request without submitting another G28. It also prioritizes a new Home
over an old result pane; see `2026-11-19-raw-home-ownership.md` for evidence.
