# R4 progress phase audit — 2026-11-24

Scope: shorten scrolling progress lists by separating major phases from the
current physical action. This is presentation only: no command order, motion,
request ownership or cancellation boundary changes.

| Dialog | Major phases | Right-side detail |
| --- | --- | --- |
| Filament load/unload | Prepare head; heat; insert when required; load/purge or unload; return previous head when required; finish | Homing, docking, mounting, positioning, feeding, purging and wiping; temperatures and hot-nozzle warning |
| Print preparation | Read/process G-code when required; prepare printer; heat bed/chamber; mesh; heat print nozzle; prime | Preheat/homing action; temperatures, stabilization countdown, probe point/count, file percentage |
| Power-loss recovery | Check saved print; prepare printer; heat; prime/wipe; return; continue | Request receipt supplies the active homing, selection, positioning, wipe/prime, restore or return action; temperatures |
| Nozzle scrub | Prepare; each head; calibrate (at most six rows) | Mount, position, heat, hand-brush prompt, cooling/reheating and measurement/recheck detail |
| Paused-print resume | Check; heat; return (three rows) | Temperatures; tool-change retry/preheat have their own current-action display |
| Tool mount/dock | Attachment check; optional home; optional previous dock; mount/dock; verify (at most five rows) | Attachment guidance; no extra numbered wiping/travel rows |
| Calibration selector/status | Existing selected calibration types and current status | Mesh/probe/sweep/PID details remain within the current calibration |
| Standalone homing | Current-action status | No numbered list of individual moves |
| Head identification | Existing per-head identification | Only current/failed rows shown, not a scrolling list of all micro-actions |

Filament and print preparation combine adjacent actions only; they do not move
later work before earlier work. A grouped phase remains running while its
current action runs and does not complete while later constituent actions are
pending. Recovery retains failure precedence across its grouped actions.
Optional work remains omitted when the backend omitted it. Unknown actions
retain their own filament/print-preparation row rather than being discarded.

The shared panel continues suppressing text identical to a major-step label
and uses the full width when there is no additional detail. Scrolling remains
available for genuine overflow, translations and unusual extensions; reducing
font size is not the remedy.

Scrub preparation now distinguishes request-bound initial homing from actual
mounting and positioning. Stale homing status cannot override an acknowledged
scrub mounting/positioning phase or label a subsequent head as homing.

Local verification:

- Native lifecycle regression passes, including every grouped action transition,
  current-action recovery detail, navigation/Stop and existing widget reuse.
- Scrub flow regression passes with request-bound homing/mounting/positioning.
- Six retained-stock accounting regressions and 259 material component/install
  tests pass; accounting is documented separately.
- ARM build passes with warnings treated as errors. Reviewed delivery artifact:
  `20a1121fd7bd91f9073455af5745ec3da0e9e86c5ff3aab580011491f9ad609c`.
- Screen package is source-current. Installed functional commit `11275655`;
  native GUI/status synchronization verified by the installer, screen PID352351,
  and the actual About row displays `work/r4-finish-camera-ui@11275655`.
- Post-install Klipper Ready/standby, all heater targets zero, Head3 attached.
  Loaded configuration, saved variables and filament identities compare equal
  to the pre-install snapshot.
- Exact factory font measurements: all four worst-case six-row lists fit in
  208 pixels with no wrapped rows (print, filament, scrub and recovery).
- Attended operation/progress acceptance remains pending plate-clear/watch
  confirmation. Installation restarted services; no heating or motion test
  was dispatched.

No release/push authorization is implied.


## Attended checks

On the clear printer, Head3 unload showed four major rows without scrolling:
Prepare head, Heat nozzle, Unload filament, Finish. During XY homing its current
action appeared on the right; during heating it showed 184/220 C and the hot
nozzle warning. Native STOP cancelled during heating, before retraction. The
backend confirmed `phase=heating`, `cancelled=true`, heater target zero and the
same attached head. No API stop fallback was used. Final live E position was
zero, as before the test.

An initial stock Rapid-mode run bypassed the brush workflow; it was stopped
after G28 without offset measurements and completed safe parking. The subsequent
Accurate-entry/Wire-brush run showed `Homing printer...` with the request-bound
backend homing and scrub-idle statuses. Native CANCEL stopped after Y homing,
with complete cleanup, all heads docked, no measurements and heater targets zero.
No API fallback was used.

The latter view exposed early highlighting of Head1 during initial homing.
The display model now keeps Prepare running and all heads pending while homing;
mounting/positioning advances to the actual head. This changes neither commands
nor cancellation ownership. Regression assertions cover both highlighted rows.
The correction passes the scrub-flow and native lifecycle regressions. The ARM
build passes with warnings treated as errors; the source-matched reviewed
artifact is `d9733d77382442eb43dd563eee544e40dd8c225101545c87511106b2f0be2e8c`.
Final correction `02c84d0` installed successfully; artifact, GUI and status
synchronization checks passed. Replaying the exact live homing snapshot through
the corrected display model keeps Prepare running, every head pending and the
Homing printer detail visible. No extra homing run was needed for that replay.

Private evidence: `analysis/progress-final-live-20261124/` includes the actual
homing/heating/stopped screenshots, bound backend receipts, pre/post configuration
snapshots and exact factory-font measurements. The subsequent unmodified Vehicles first-layer check accepted the accounting
fix on hardware: Head3's E336.48309 -> Head1's E0 retained total 336.48309;
red extrusion advanced the final total to 365.16270. Cancellation completed,
heaters were off and Head1 was parked beside the scrubber at physical Z125.
Tuning and filament identities compared unchanged.

The actual Preparing print screen showed all six major rows without a scroll
indicator, and probe point1/35 in the right-side detail. Its title and Stop/Close
controls shared the header. The 60,414,444-byte file's processing phase took
approximately 92 seconds before preheat; this is a measured duration, not a claim
that large-file preparation performance has been resolved.
