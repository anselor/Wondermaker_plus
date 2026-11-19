# Nozzle re-check after offset measurement: design

Extends the guided nozzle scrub (`2026-11-15-guided-nozzle-scrub-design.md`,
as built: `docs/nozzle-scrub.md`). Base: `feature/brush-nozzle-scrub-r4`.

## Intent

Residue left on a nozzle shifts the measured tool offsets and the stock
checks do not detect it. The offset measurement already produces a signal:
the gauge centres it measures for one head stop agreeing with each other.
After the last head is measured, the flow names the heads whose centres
disagree and lets the user clean those heads and measure again, keep the
result, or cancel.

## Measured basis

The tool-setter has an X gauge and a Y gauge. `calibrate_xy` in the vendor's
`tools_calibrate_core.py` touches each gauge from both sides and takes the
midpoints as the nozzle centre. Each probing round prints that centre:

    // Calibrated XY: <cx>, <cy>, dx: <dx>, dy: <dy>, dydx: <ratio>

One head's measurement (`CALIBRATE_TOOL_OFFSET`) is three rounds of two
passes: six centres.

The span of a head on one axis is the smallest (max - min) over every five
of its six centres (best five of six); `centre_span` is the larger of the X
and Y spans.

Runs on the owner's printer, best five of six, worse axis, mm:

| Run | Head 1 | Head 2 | Head 3 | Head 4 |
|---|---|---|---|---|
| 2026-11-17, all nozzles cleaned | 0.014 | 0.022 | 0.014 | 0.009 |
| 2026-11-17, residue on nozzles | 0.783 | 0.050 | 0.033 | 0.011 |
| 2026-11-19, first measurement | 0.558 | 0.026 | 0.041 | 0.017 |
| 2026-11-19, re-measurement | 0.008 | 0.023 | | |

The 2026-11-17 logs are `tests/fixtures/toolsetter_clean.log` and
`toolsetter_residue.log`; the 2026-11-19 log is
`tests/fixtures/toolsetter_19nov.log`. With a limit of 0.030 mm the clean
run flags no head, the residue run flags heads 1 to 3, the 2026-11-19 first
measurement flags heads 1 and 3, and its re-measurement of head 2 (0.023 mm)
is not flagged.

Limits of this signal, from the same data:

- The clean values come from three runs on one printer. The largest clean
  span is 0.026 mm; the smallest flagged residue span is 0.033 mm.
- Residue that shifts every centre of a head by the same amount does not
  change the span; it is not detected and shifts the offset. Head 4 of the
  2026-11-17 residue run had residue and a span of 0.011 mm.

The distance between the two sides of a gauge (`dx`, `dy`) separates the two
2026-11-17 runs by 0.9 mm or more, but depends on nozzle diameter and shape.
It is not used, by the owner's decision, so that mixed nozzles need no
per-nozzle data.

## Goals

- Detect a head whose measured centres disagree, per head, during the stock
  measurement, without changing vendor files and without any data about the
  nozzle (diameter, shape, earlier measurements).
- Offer three outcomes when any head is flagged: clean again and re-measure,
  save anyway, cancel.
- Re-clean only the flagged heads.
- Cancel leaves every head's stored offset as it was before the run.

## Non-goals

- No check in Rapid Alignment Mode or Printed blob runs. They have no scrub
  screen; the stock flow is unchanged.
- No change to `tools_calibrate_core.py`, `tools_calibrate.py` or the probing
  macros' motion.
- No detection of residue that affects only the Z measurement, or of
  residue that shifts every centre of a head by the same amount.
- No change to the number of touches or rounds of the vendor measurement
  (`samples` in `[tools_calibrate]`).
- No automatic retry. Every repeat is the user's choice.

## Anti-goals

- A flagged head must not fail the calibration attempt. A failure latch would
  end the run and discard the choice.
- The check must not block or delay a run on a printer where the console
  lines are absent or have another format. No lines means no flag.
- Cancel must not leave a mixture of old and new offsets.

## User flow

Applies to wire-brush runs only. Steps 1 to 6 of the scrub flow are
unchanged.

### 7. Re-check (only when a head is flagged)

Shown after the last head's measurement, before the vendor worker's final
park. The worker is held as at the scrub stage.

- Step list: flagged heads are red ("failed" state), other heads and Prepare
  are grey, Calibrate is the current step.
- Heading: "Head 2 may not be clean" / "Heads 2 and 4 may not be clean".
- Instruction: "Their measurements did not repeat, which usually means
  residue on the nozzle." (singular form for one head).
- Two option rows, as on Prepare:
  - "Clean again" — "Scrub the flagged heads, then measure again." Selected by
    default.
  - "Save anyway" — "Keep the offsets as measured."
- Actions: CANCEL and CONFIRM, as on Prepare.
- The case-light attention signal is requested while this screen waits and
  released on any choice.
- No heater is on. There is no unattended time limit.

### Clean again

1. For each flagged head in ascending order: the existing Mounting, Heating
   and Scrub states, with the same commands, limits, cancel and failure
   handling as the first scrub.
2. Re-measurement. If head 1 was flagged, every head is measured again in the
   stock order, because head 1 is the reference for every other head.
   Otherwise only the flagged heads are measured. Each is one
   `RAPID_MODE T=n`, sent through the sequenced calibration wrapper.
3. The Calibrate screen shows progress as in the first measurement.
4. The check runs again on the heads just measured. If any is flagged, the
   Re-check screen is shown again. There is no limit on repeats.

### Save anyway

The worker is released to its park and, on a combined run, its save. The
result page names the flagged heads:

- Offsets-only run: "Nozzle offsets saved. Head 2 may not be clean."
- Combined run: "Calibration settings saved. Head 2 may not be clean."

### Cancel

1. The backend writes back the offsets every head had when the attempt
   started.
2. The run ends as a cancelled scrub does today: on a combined run the earlier
   results are saved; on an offsets-only run nothing is saved.
3. Result page: "Offset calibration cancelled. Offsets are unchanged." On a
   combined run after the restart: "Offset calibration cancelled. Earlier
   results were saved."

Cancel during a re-clean (from Mounting, Heating or Scrub of a repeat) does
the same after the existing cool-down and docking.

### Failures

- A failure during a re-clean or a re-measurement is handled as the same
  failure in the first pass. Offsets are not restored: the attempt has failed
  and the existing failure texts apply.
- If the old offsets cannot be written back on Cancel, the head is still
  cooled and docked and the result page says so: "Offsets could not be
  restored. Run the calibration again."

## Design

### Detection (backend)

- A module, `klipper_extras/wmp_nozzle_touch.py`, composed into
  `CalibrationCommands` like the scrub and progress modules.
- It registers a G-code output handler. Each line
  `// Calibrated XY: <cx>, <cy>, dx: …, dy: …, dydx: …` (one per probing
  round; six per head: three rounds, two passes) adds the centre
  `(cx, cy)` to the head and request the progress module reports in phase
  `position`. Lines outside that phase and every other line are ignored.
- Span of a head on one axis: with k centres, k >= 3, the smallest
  (max - min) over every subset of k - 1 centres (k = 6: the best five of
  six); k < 3: 0. `centre_span` is the larger of the X and Y spans.
- A head is flagged when `offset_centre_spread` > 0, k >= 3 and
  `centre_span` > `offset_centre_spread` + 1e-9. For k < 6 the span is a
  lower bound of the final best-five-of-six span (the final five contain at
  least k - 1 of the first k centres), so a head flagged early stays
  flagged. A head with fewer than six centres at the end is judged on the
  centres it has.
- A new measurement of a head (progress enters `mounting` for it) clears
  that head's centres and flag.
- Option in `[wmp_recovery]`: `offset_centre_spread`, default 0.030 mm,
  0 or more; 0 disables the check.
- Status `wmp_recovery.nozzle_touch`, protocol 2: `{protocol, request,
  heads: [{head, centres, centre_span, flagged}], flagged: [head…],
  restore}`. `centre_span` is rounded to 6 decimals. `flagged` is complete
  for the request once progress has left the last head's `position` phase.
- Reference figures (best five of six, worse axis, mm): 2026-11-17 residue
  run 0.783, 0.050, 0.033, 0.011 (heads 1 to 3 flagged); 2026-11-17 clean
  run 0.014, 0.022, 0.014, 0.009 (none flagged); 2026-11-19 first
  measurement 0.558, 0.026, 0.041, 0.017 (heads 1 and 3 flagged), its
  re-measurement of head 2 0.023 (not flagged).

### Offset snapshot and restore (backend)

- When a new attempt's first command is admitted, the backend records
  `t0_offset` to `t3_offset` from `save_variables`.
- `_WMP_OFFSETS_RESTORE` writes the recorded values back with `SAVE_VARIABLE`
  for each head and reports the outcome in status (`nozzle_touch.restore`:
  `none`, `done`, `failed`). It is a sequenced calibration command (added to
  the wrapper's allowlist), admitted only for the current attempt.
- A restore that cannot write every head reports `failed` and does not raise:
  a raised error would latch the attempt's failure and refuse the
  `_WMP_SCRUB_END` that cools and docks the head.

### Flow (native)

- New flow state `Recheck`, entered from Calibrate when the worker reaches its
  park send (`offset_park`) on a brush run and fresh status for this request
  lists flagged heads. The coordinator holds the worker inside that send hook
  with a hold loop like the scrub stage's (the vendor wait helpers have no
  timeout). The hook's existing decisions (failed byte, 5 s wait, withhold,
  early save) are made after the hold ends, not at entry.
- Commands sent during the hold go out on the worker thread through the
  worker's calibration binding, as the scrub commands do, so they take the
  attempt's next sequence numbers.
- A `RAPID_MODE` sent by the flow has no vendor wait behind it. The flow needs
  a "measurement finished" signal from status; the backend publishes one (for
  example the attempt's next sequence with `calibration_active` false, or a
  field of `nozzle_touch`).
- Clean again: the flow re-enters the head states with the flagged heads as
  its head list, then sends the `RAPID_MODE` commands itself and returns to
  Calibrate; at the end it evaluates the flags again before releasing the
  worker.
- Save anyway: the worker is released; the park and save proceed.
- Cancel: the flow sends `_WMP_OFFSETS_RESTORE`, then `_WMP_SCRUB_END` as a
  cancelled scrub does. The backend then reports the offsets outcome as
  "stopped" with the attempt still pending, so a combined run makes its
  ordinary save; the early-save rule is not involved.
- If status is stale at the park hook, or the backend does not publish
  `nozzle_touch`, the worker is not held and the run completes as today.
- The existing limits apply: 120 s of stale status in the Re-check screen, a
  repeat scrub or a re-measurement ends the scrub with `_WMP_SCRUB_END` alone,
  without a restore; the hold loop keeps its 250 ms slices.

### Screen (native)

- The Re-check screen is one more `ScrubView` on `StockNozzleScrub`: the same
  two `StockOptionRow`s with other texts, CANCEL and CONFIRM. Step state
  `failed` marks the flagged heads.
- A fit case for the Re-check view (four heads flagged, longest heading) is
  added to `tests/fixtures/progress_panel_views.json`.

### Result page

- `stock_calibration_status.hpp` appends "Head N may not be clean." to the two
  success texts when the run was a brush run released by Save anyway.
- The cancelled texts are new branches: today a stopped run whose probing had
  started shows no "stopped" text on an offsets-only run.
- A wire-brush run whose offset stage stopped after probing had started, with
  no failure, no cancel and no save requested (for example stale status for
  120 s during the re-check), shows "Offset calibration stopped. Offsets were
  changed and may not be reliable. Run the calibration again." once the worker
  has returned; a combined run, after the restart with a confirmed save,
  shows "Offset calibration stopped. Earlier results were saved. Offsets were
  changed and may not be reliable. Run the calibration again."
- The flagged heads, the choice made and the restore outcome are passed to the
  result page natively (as `maintenance_scrub_heads` is), because backend
  status is lost at the `SAVE_CONFIG` restart.
- "Nozzle offsets saved." today requires progress to report the last head in
  phase `docking`. After a partial re-measurement the last probed head is
  another one. The condition becomes: every head of the run has a completed
  measurement for this request and the final park was admitted.

## Constraints

- All constraints of the scrub design apply: C++11, glibc floor 2.17, profile
  generated by `make_profile.py`, touch targets at least 64 x 110 px and 8 px
  apart, instruction text at least 22 px, plain-language texts.
- Backend modules are registered in `material.HELPERS` and
  `runtime_inputs.RUNTIME_INPUTS`; new commands and the new status protocol go
  into `backend_contract.json`.
- The failure latch, `fail_flag` handling and the early-save rule are not
  changed.

## Testing

- Backend: parsing of the `Calibrated XY` lines (the three logged runs as
  fixtures, with the spans and flags in the table above); early flag at
  three centres; one stray centre of six not flagged; worse axis counts;
  span at the limit not flagged; other console lines, including the
  tool-setter helper's false-trigger line, ignored; attribution by head and
  request; centres cleared on re-measurement; no lines means no flag; limit
  0 disables; snapshot taken once per attempt;
  restore writes all four values; restore refused outside the current attempt
  and while a command runs.
- Flow: Recheck entered only on a brush run with flags and fresh status;
  each of the three choices; head 1 flagged re-measures all heads; another
  head flagged re-measures only it; repeat after a second flag; cancel during
  a re-clean restores; stale status releases the worker.
- Emulation: the worker held at the park send resumes to park and save.
- Screen: lifecycle and touch-target cases for the Re-check view; real-font
  fit case.
- Not testable off the printer: that the console lines reach the output
  handler in the form logged, the limit on other printers and with warm
  nozzles, the hold at
  the park send on hardware.

## Left to the builder

- Whether the output handler or a wrapper around the vendor probe call is the
  more reliable way to read the centres, provided no vendor file is edited.
- How the flow represents a head list that is a subset of the heads.
- Exact status field names beyond those listed.
- Whether `_WMP_OFFSETS_RESTORE` must also reapply the active G-code offset.

## Decisions made without explicit user direction

- The limit of 0.030 mm (`offset_centre_spread`). It comes from three runs
  on one printer and is to be re-checked against more clean runs.
- A head is flagged when it has at least three centres and its centre span
  (best all but one, worse axis) is above the limit (owner decision).
- Head 1 flagged means every head is re-measured.
- The options are two rows with CONFIRM, plus CANCEL in the header, as on
  Prepare.
- "Save anyway" names the flagged heads on the result page.
- A failure during a repeat does not restore offsets.
- A failed restore is reported, not raised; on a combined run the earlier
  results are still saved.
- Rapid Alignment Mode and Printed blob runs are not checked.
