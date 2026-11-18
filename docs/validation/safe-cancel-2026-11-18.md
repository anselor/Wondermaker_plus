# Safe-cancel qualification — 2026-11-18

Status: stationary and bounded cold-motion checks passed. Full heated startup and cancellation mid-coupling are not qualified.

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

## Cold mechanical checks

The operator explicitly approved the full home and mechanical tests. Full
`G28` completed in 57.339 seconds, with XYZ homed, a valid physical Z reference,
and Head 4 confirmed mounted. All heaters remained off.

The existing cold tool-change fixture then mounted Head 3 successfully but
received a `PAUSE` before its intended cancellation window. `fail_flag` stayed
zero and the attachment sensors confirmed Head 3. The source of that pause was
not established; it must not be reported as a mounting failure or a fully
successful uninterrupted fixture run. The job was cancelled, rather than
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

## Limits and remaining work

No cancellation was injected mid-lock/unlock. Existing R4 command-generation
checks can reject continuation during a coupling stroke; they do not guarantee
completion of the entire mechanical sequence after a cancel request. The
35 actuator checks pass, including tests that deliberately prevent the
post-homing stroke or confirmation adjustment after invalidation. AST comparison
confirmed that `_check_command_generation`, `cmd_COUPLING_STROKE`, and
`_recovery_actuator_stroke` are unchanged from R4. Review that existing behavior
before claiming a general finish-the-current-coupling guarantee.

Do not interpret these results as qualification of cancellation inside
homing, probing, docking, mounting, or purge motion. The live boundary tests
and host macro tests establish the startup stop points; real heated startup
and the complete startup-to-purge path remain unverified. The unexplained pause
in the first cold fixture also remains an observation requiring follow-up.

Temporary qualification G-code files and the macro/include were removed.
Raw evidence and screenshots are retained off-printer in the qualification
worktree's ignored `analysis/safe-cancel-qualification/` directory.
Safe cancel has not been merged into R4 or pushed.
