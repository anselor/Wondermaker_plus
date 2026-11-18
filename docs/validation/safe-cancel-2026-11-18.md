# Safe-cancel qualification — 2026-11-18

Status: stationary and bounded cold-motion checks passed. Full heated startup and cancellation mid-coupling are not qualified.

Candidate: `qualification/safe-cancel-r4`, based on local R4 `6e5510e`.
The original feature branch `feature/safe-cancel-split` (`21b21d1`) is unchanged.
The candidate includes the committed filament-load changes.
Initial screen SHA256: `1ef58a1c1b337ca2a6cad235aeed538b2dbde6c618e205acd1d44c8347c0c985`.
Follow-up screen SHA256: `935306b2b9ad11722926f00e234389f6e8614b5435a6be3816fe1308bba768f2`.

## Live checks

Sixteen checks passed, without extrusion or XYZ movement:

| Check | Result |
|---|---|
| Eight stop-point handlers | Each recorded its expected phase, completed cancellation cleanup, and skipped commands after the stop. |
| Real `START_PRINT` entry | An already-pending cancel stopped at `start_admitted`, before heating or homing. |
| `TEMPERATURE_WAIT` | Interrupted with the heater target at zero. |
| `M109` and `M190` | Interrupted low-temperature waits, using 45 C targets. |
| No-cancel control | Completed normally with the wait region open, then closed it. |
| Readable heater labels | Repeated nozzle and bed cancellation; recorded `heating Head 4` and `heating bed`. |
| Touchscreen STOP → Confirm | Completed cancellation; shared result panel displayed `Print cancelled.` and `Stopped at: heating bed`, with one DONE button. |

The eight boundary tests used a temporary macro with a three-second dwell and
one stop point. They verify the live handlers and cancellation transport, not
physical execution of all eight startup phases. Host tests verify placement
inside the real startup macro. The entry test called the real `START_PRINT`
only after a guard confirmed cancellation was already pending.

Initial temperature-wait cancellation plus cleanup took 1.407–2.477 seconds.
The readable-label repeats took 1.747 and 2.412 seconds. These measurements
include cleanup and status observation, rather than only wait-loop interruption.
All heater targets were zero after cleanup, pause state was clear, the SD
worker was idle, and print history reported `cancelled`. A repeated cancel
while a boundary test was pending retained the same cancellation identifier.

The UI uses the existing progress panel, existing font sizing, and retained
widgets. The review corrected two labels: tool selection no longer implies
that homing left no head mounted, and physical heads use one-based user names
instead of Klipper object names.

## Host checks

- Feature baseline: 194 stop-point, macro, cancellation-ordering, native-pause,
  and recovery checks passed before rebasing onto the filament commit.
- Rebased stop-point and macro suites: 89 passed before the additional readable
  chamber-label case; eight focused label/wait checks passed afterward.
- Native lifecycle and progress-panel checks passed. One real-font measurement
  was skipped while the new checkout lacked the vendor client fixture; the
  actual touchscreen result was subsequently inspected on the printer.
- Source-bound screen package verified after updating the backend label record.

## Cold mechanical checks

The operator explicitly approved the full home and mechanical tests. Full
`G28` completed in 57.339 seconds, with XYZ homed, a valid physical Z reference,
and Head 4 confirmed mounted. All heaters remained off.

The existing cold tool-change fixture then mounted Head 3 successfully but
received a `PAUSE` before its intended cancellation window. `fail_flag` stayed
zero and the attachment sensors confirmed Head 3. The operator subsequently
identified the factory ZRU-M011 warning and confirmed Head 4 was empty. The
fixture marked the print body ready before switching away from Head 4; the
factory touchscreen has an independent selected-head runout detector which
pushes that warning and sends PAUSE. Existing WM+ hooks replaced recovery,
not this initial detector. This was not a mounting failure or a successful
uninterrupted fixture run. The job was cancelled, rather than
resumed. Paused cancellation completed in 6.022 seconds, cleared pause, left
Head 3 attached, and lowered Z from 160.1675 to the 300 mm bottom coordinate.

A second cold run, with Head 3 already attached, requested cancellation after
mount confirmation but before the final XY motion drain. It completed in
10.745 seconds, including draining queued motion and lowering Z from 150.1675
to 300 mm. Later tool-change markers and the file tail did not run. Every
cleanup stage completed, all heater targets were zero, `filament_used` was
zero, pause was clear, and `fail_flag` remained zero. No sensor or head-check
settings were bypassed. Only a dwell was shortened and an observation marker
added to the reused fixture; its physical moves were unchanged.

The cold fixture's temporary `save_position=1` macro flag was restored to zero.
Temporary fixture copies were removed; the original uploaded files were not
changed. Z UART PC1, 64 microsteps, the saved probe offset, extruder calibration,
and acceleration were verified unchanged after testing.

## Follow-up: runout ownership and final cold repeat

The verified factory `filament_check_for_pause()` at `0x61ab5c` independently
checks the selected head and `print_body_ready`, pushes a ZRU warning and calls
PAUSE. Recovery hooks alone did not intercept that initial action. The new
entry hook delegates detection only when fresh standalone status explicitly
advertises all eight guarded sensor paths. Missing/stale capability or another
owner retains the original implementation. The ARM fallback prologue was
executed in emulation against the original instructions. Backend notifications
use ordinary guidance while retaining guarded runout/tangle pause callbacks.

A first repeat demonstrated the handoff without M011 or a pause, but the
shortened one-second observation dwell expired before cancellation arrived.
The next tool change had begun and stopped at its generation fence, leaving
Head 3 locked at its own dock. Cleanup completed but history recorded an error.
Camera and raw hall/lock/dock readings were inspected; a slow straight retreat
along the stock Y310 path restored confirmed Head 3 attachment. No actuator
stroke or homing was used for that recovery. This is not counted as a passed
cold cancellation fixture.

An exact same-job cancellation fence now unwinds as cancellation rather than a
print fault; changed session/file handle/owner, unrelated invalidation, shutdown
and quick stop remain errors. Seven focused cases verify that distinction.

The final repeat retained the original 30-second observation dwell and added
a two-second dwell while empty Head 4 was selected and the print body was
marked ready. It then mounted Head 3 without M011 or a pause and cancelled at
the intended boundary. All later tool changes and the file tail were skipped.
Cancellation and every cleanup stage completed; history reported `cancelled`
with no error message. Head 3 remained confirmed attached, fail_flag stayed
zero, pause cleared, heaters stayed off, extrusion stayed zero, and Z lowered
from 150 to 300 mm. Cleanup took 36.488 seconds including draining the
intentional 30-second G4 dwell; this is not a heat-wait interruption latency.

Verification: 1,722 backend/sensor/actuator checks passed with two skipped before
the final classification adjustment; afterward 143 stop-point/macro/actuator
and 55 cancellation/generation checks passed. Four native compile/projection/
profile/emulation checks and 144 delivery checks passed. The final package
was resealed after the backend-only adjustment with compiled inputs and artifact
hash independently unchanged.

## Limits and remaining work

No cancellation was injected mid-lock/unlock on the printer. The operator's
required behavior is to finish an admitted stroke before ordinary cancellation.
The follow-up correction permits only the exact generation fence created by
that cancellation, only during its stopping phase, and only inside the already
admitted coupling handler. The completed stroke disables its motor before
rejecting the cancelled macro tail. Session/owner changes, shutdown, quick stop,
physical faults and unrelated generation changes retain their refusal behavior.
The actuator suite passes 46 checks, including normal Stop during lock/unlock
and failures that must still prevent further motion. The shared PLR actuator
implementation is unchanged; this exception belongs to normal coupling only.

Do not interpret these results as qualification of cancellation inside
homing, probing, docking, mounting, or purge motion. The live boundary tests
and host macro tests establish the startup stop points; real heated startup
and the complete startup-to-purge path remain unverified. The factory runout pause
in the first cold fixture is resolved by the ownership interception and final
repeat above.

Temporary qualification G-code files and the macro/include were removed.
Raw evidence and screenshots are retained off-printer in the qualification
worktree's ignored `analysis/safe-cancel-qualification/` directory.
Safe cancel has not been merged into R4 or pushed.
