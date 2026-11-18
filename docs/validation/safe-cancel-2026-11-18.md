# Safe-cancel qualification — 2026-11-18

Status: stationary qualification passed; mechanical qualification pending.

Candidate: `qualification/safe-cancel-r4`, based on local R4 `6e5510e`.
The original feature branch `feature/safe-cancel-split` (`21b21d1`) is unchanged.
The candidate includes the committed filament-load changes.
Installed screen SHA256: `1ef58a1c1b337ca2a6cad235aeed538b2dbde6c618e205acd1d44c8347c0c985`.

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

## Limits and remaining work

A fresh full home and the existing cold tool-change/cancel file have not run on
this candidate. Automatic approval review blocked the full `G28` because of the
earlier Z incident; explicit operator permission was requested. No rejected
motion command was executed. Z's corrected UART is PC1, and the earlier
measured five-millimetre movement passed.

Do not interpret these results as qualification of cancel inside homing,
probing, docking, mounting, or purge motion. This feature deliberately waits
for the current atomic sequence to finish before stopping at a boundary.
Real heated startup and the complete startup-to-purge path remain unverified.

Temporary qualification G-code files and the macro/include were removed.
Raw evidence and screenshots are retained off-printer in the qualification
worktree's ignored `analysis/safe-cancel-qualification/` directory.
Safe cancel has not been merged into R4 or pushed.
