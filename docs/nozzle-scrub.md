# Nozzle scrub

The guided nozzle scrub is a manual clean for accurate nozzle-offset
calibration. Each head is mounted, heated and moved to the front of the
printer, and the user cleans the nozzle tip with a wire brush. After the last
head the stock rapid probing sequence measures the offsets. When the repeat
touches of a head disagree during that measurement, the user can clean the
flagged heads and measure again (see [Re-check](#re-check)).

Scope: touchscreen client 1.1.13 (SHA-256 prefix `b60c96c5`). On any other
client the clean is not offered and the stock behaviour is unchanged.

## What is stock and what is installed

Stock firmware:

- The Maintenance page, the "Rapid Alignment Mode" / "Accurate Alignment Mode"
  popup, the worker that runs bed level, vibration, PID and offsets in that
  order, and its final `SAVE_CONFIG`.
- The printed-blob clean of Accurate Alignment Mode.

Installed by this project over SSH with `tools/deploy.py`:

| Component | Files | Part of the scrub |
|---|---|---|
| `material` | The backend helper list (`HELPERS` in `tools/components/material.py`). It includes `klipper_extras/wmp_nozzle_scrub.py`, `klipper_extras/wmp_calibration_progress.py`, `klipper_extras/wmp_calibration_outcome.py`, `klipper_extras/wmp_nozzle_touch.py`, `klipper_extras/wmp_tool_probe.py`, `klipper_extras/wmp_offset_snapshot.py` and `klipper_extras/wmp_calibration.py`. | Scrub commands and status, progress status, offset-stage outcome and the earlier-results rule, centre-agreement check, offset snapshot and restore, calibration attempt rules |
| `config` | The same helper list, then `klipper_extras/wmp_identification.py`, `klipper_extras/wmp_recovery.py` and `klipper_extras/wmp_case_light.py`, and `config/live/offset_calibrate.cfg` with the rest of the configuration | The same backend modules; `wmp_recovery.py` publishes their status; light signal; progress phases set by the probing macros |
| `preload` | `client-preload/unified-screen1113/screen.so` | Prepare screen, scrub screens, result text, hooks on the Maintenance START button and on the worker's commands |

The five scrub modules are also listed in
`client-preload/unified-ui/native/runtime_inputs.py`, so the screen package
records their hashes and the `preload` installer compares the installed
copies with them.

Source files:

| File | Content |
|---|---|
| `klipper_extras/wmp_nozzle_scrub.py` | Scrub commands, scrub heaters, light signal requests, `nozzle_scrub` status |
| `klipper_extras/wmp_calibration_progress.py` | `_WMP_CALIBRATION_PHASE` and `calibration_progress` status |
| `klipper_extras/wmp_calibration_outcome.py` | Offset-stage outcome of an attempt and the earlier-results rule |
| `klipper_extras/wmp_nozzle_touch.py` | Centre span per head, `nozzle_touch` status, `offset_centre_spread` option |
| `klipper_extras/wmp_tool_probe.py` | Repeats a tool-setter touch that triggers before the nozzle moves (see [Tool-setter false triggers](#tool-setter-false-triggers)) |
| `klipper_extras/wmp_offset_snapshot.py` | Stored offsets recorded when an attempt is admitted, `_WMP_OFFSETS_RESTORE`, restore outcome |
| `klipper_extras/wmp_calibration.py` | Calibration attempt rules; calls the modules above when an attempt is admitted, fails or is saved |
| `client-preload/unified-ui/native/nozzle_scrub_flow.hpp` | State machine and limits |
| `client-preload/unified-ui/native/nozzle_scrub_view.hpp` | Screen text for each state |
| `client-preload/unified-ui/native/nozzle_scrub_status.hpp` | Validation of the two status objects |
| `client-preload/unified-ui/native/stock_nozzle_scrub.hpp` | The screen: actions and option rows on the shared progress panel (`stock_progress_panel.hpp`) |
| `client-preload/unified-ui/native/nozzle_scrub_vendor.hpp` | The vendor data the scrub reads and writes |
| `client-preload/unified-ui/native/nozzle_scrub_coordinator.hpp` | Connection to Maintenance START, calibration admission, the worker's offset stage and the screen refresh |
| `client-preload/unified-ui/native/stock_calibration_status.hpp` | Result panel |

Vendor code is not patched. The preload library uses its existing hooks and
writes two vendor data bytes: `is_rapid_mode` and `knife_pairing_failed` (see
[Decision](#decision)).

The `preload` installer checks that the running backend registers `_WMP_SCRUB_HEAD`,
`_WMP_SCRUB_HEAT`, `_WMP_SCRUB_COOL`, `_WMP_SCRUB_END`, `_WMP_SCRUB_ATTENTION`,
`_WMP_CALIBRATION_PHASE` and `_WMP_OFFSETS_RESTORE` and reports
`nozzle_scrub.protocol` and `calibration_progress.protocol` as 1 and
`nozzle_touch.protocol` as 2
(`client-preload/unified-ui/native/backend_contract.json`). Each time START is
pressed the screen checks that `nozzle_scrub.protocol` and
`calibration_progress.protocol` are 1; it does not check `nozzle_touch`. A run
whose status carries no `nozzle_touch` for its request has no re-check.

Both status objects carry `request`: the request id of the calibration attempt
they belong to, or an empty string before any attempt. The backend sets it
when it admits the attempt's first command and keeps it until the next attempt
is admitted. The screen requires the key; without it the clean is not offered.
During a wire-brush run the scrub screen uses scrub status, progress and the
attempt state only when they name the run's own request. A change of the
calibration session (Klipper restarted) and stale status are acted on
whatever the request. The result panel has its own rule (see
[Result screen](#result-screen)).

## When it is offered

The Prepare screen opens when START is pressed on the Maintenance page and all
of these hold:

- Extruder Offsets Calibration is ticked and Accurate Alignment Mode was
  chosen in its popup.
- The client is the 1.1.13 build named above.
- Calibration may start (the same checks as a stock START).
- Printer status reports both protocols above.
- The head count is 1 to 4.

In Rapid Alignment Mode, or with the offset row not ticked, START behaves as
stock.

## Screens

Every scrub screen covers the whole display. It is drawn on the progress
panel shared with other screens: the title "Nozzle offset calibration" at the
top left, a numbered step list in the left column and a text column on the
right. The scrub adds its actions at the top right and, on Prepare, two
option rows below the text. The step list is built from the head count, for
four heads:

    1. Prepare
    2. Head 1
    3. Head 2
    4. Head 3
    5. Head 4
    6. Calibrate

Completed steps are grey, the current step is orange, later steps are white.
On the failure screen the step that failed is red.

The text column holds, from the top: the heading (bold, 24 px), the
temperature (Heating only; bold, 24 px) and the instruction (22 px). The
caution (22 px, amber) is at the bottom of the column and stays there when
the text above it has to scroll. Long text wraps. A change of the
temperature rewrites its label only.

Sizes on the 800 x 480 display:

- Title row: 48 px. Step column: 200 px. Text column: 568 px wide,
  starting at x = 224.
- Actions: each touch area is 116 x 64 px at the top edge. CONFIRM and BACK
  are at the right edge, CANCEL is 8 px to the left of CONFIRM. The caption
  (bold, 20 px) is inside the top 40 px. The touch area extends 16 px below
  the title row, over the first line of the text column from x = 560.
  They are made with `stock_header_action`.
- Option rows (`StockOptionRow`): 104 px high, 8 px apart, as wide as the
  text column, text in 22 px. The whole row is the touch area. A 32 px ring
  marks each row; the selected row has an orange dot in it.

CONFIRM is disabled while printer status is stale: its caption is grey and a
tap does nothing.

### Prepare

Nothing has been sent to the printer.

- Text: "How will the nozzles be cleaned?"
- Option row, selected by default: "Wire brush" / "Scrub each heated nozzle
  by hand. Have a wire brush ready."
- Option row: "Printed blob" / "Every head must be loaded with filament."
- Actions: CANCEL, CONFIRM.

| Action | Result |
|---|---|
| CANCEL | The Maintenance page is shown again with the ticked items unchanged. |
| CONFIRM with Printed blob | The stock run starts unchanged in Accurate Alignment Mode. No scrub screen is shown again. |
| CONFIRM with Wire brush | The stock run starts with `is_rapid_mode` set to 1, so the stock clean loop is skipped. The scrub runs when the worker reaches the offset stage. |

The START press is sent to the stock handler again once the choice is made.
If the stock handler does not start a run after Wire brush was confirmed,
`is_rapid_mode` is set back to 0.

### Other selected checks

Bed level, vibration and PID run as stock on the stock progress page, before
the offset stage. The scrub follows them.

### Return prompt

Shown only on a combined run (bed level, vibration or PID also ticked), when
the worker reaches the offset stage. Nothing is heated until CONFIRM.

- Step highlighted: 2. Head 1.
- Text: "Ready to clean the nozzles." / "Press Confirm to start."
- Actions: CANCEL, CONFIRM.
- The case light signal is on until CONFIRM, CANCEL, a touch or a door
  opening (see [Case light signal](#case-light-signal)).

On an offsets-only run the first head is mounted without this prompt.

### Each head

| State | Text | Actions |
|---|---|---|
| Mounting | "Mounting head N..." ("Mounting head 1..." is also shown while the offset-stage homing is still running) | CANCEL; CONFIRM disabled |
| Heating | "Heating head N..." and the temperature line, for example "127 / 160 °C" ("--" for a value that is not known) | CANCEL; CONFIRM disabled |
| Scrub | "Scrub the nozzle on head N" / "Brush the nozzle tip until it is clean, then press Confirm." / "The nozzle is hot." | CANCEL, CONFIRM |
| Cooled | "Head N has cooled." / "Press Confirm to reheat." | CANCEL, CONFIRM |

Sequence for head N:

1. `_WMP_SCRUB_HEAD` first checks, before heating or moving anything, that
   X, Y and Z are homed and `wmp_recovery.z_reference_valid` is true ("The
   printer must be homed first." otherwise) and that `fail_flag` is 0
   ("Head N did not mount." otherwise). The worker homes at the start of the
   offset stage, which makes the Z reference valid. It then sets the heater
   target, zeroes the G-code offsets, lowers the bed to the scrub height
   (`G90`, `G1 Z… F1800`) and mounts the head through the calibration
   tool-change path (`_WMP_CALIBRATION_TOOL`). After the tool change it
   checks `fail_flag` again, zeroes the G-code offsets, runs
   `_WMP_CALIBRATION_CLEARANCE`, repeats `G90` and the Z move, moves X and Y
   with `_WMP_XY_TRAVEL HOT=1` (the shared `hot_travel_speed`) and waits
   with `M400`. A tool change that does not home Z leaves Z at the scrub
   height, so the repeated Z move does not move the bed; a tool change that
   bottom-homes Z (an invalid Z reference) moves Z, and the repeated Z move
   lowers the bed to the scrub height again.
2. When the head is at the scrub position the next head starts heating in its
   dock.
3. The Scrub state starts when the reported nozzle temperature reaches
   158 °C. The temperature is published to the screen in whole degrees. The
   case light signal is requested on entry to Scrub and to Cooled; a touch or
   a door opening releases it (see [Case light signal](#case-light-signal)).
4. CONFIRM on Scrub turns off the heater of head N and mounts head N + 1.
   After the last head the Calibrate state follows.

Values:

- Target temperature: 160 °C (`scrub_temp`). The configured maximum is
  170 °C, below the 175 °C minimum extrusion temperature.
- Position: X150 Y2 Z100 (`scrub_x`, `scrub_y`, `scrub_z`). See
  [Configuration](#configuration).
- Unattended timeout: 10 minutes from the start of the Scrub state. Every
  heater the scrub turned on is switched off, including a head preheating in
  its dock, and the Cooled state is shown. CONFIRM reheats the mounted head
  and returns to Heating.
- A heater target cleared from outside the flow has the same result. The
  printer's `[idle_timeout]` (600 s) clears every extruder target. Either
  the flow's timeout or `[idle_timeout]` can fire first; both lead to the
  Cooled state.

### Calibrate

No actions. The vendor worker sends `RAPID_MODE T=n` for each head and then
parks.

| Progress | Text |
|---|---|
| Homing | "Homing..." |
| Mounting | "Head N of M" / "Mounting head N..." |
| Position | "Head N of M" / "Measuring nozzle position..." |
| Height | "Head N of M" / "Measuring nozzle height..." |
| Parking | "Returning head N to its dock..." |
| Phase not reported, head known | "Measuring head N of M..." |
| Nothing reported | "Measuring nozzle offsets..." |

Below the progress text there is one row per head of the run, in head order,
display only:

| Part | Content |
|---|---|
| Name | "Head N" |
| Mark | Red cross as soon as the head is flagged, also while it is still being measured. Otherwise: none before the head's first centre; orange "…" while the head is being measured; green check once `calibration_progress.measured` lists the head. |
| Span | The head's `centre_span` with three decimals, for example "0.023 mm"; empty before its first centre |

There is no count of centres. The rows come from `wmp_recovery.nozzle_touch.heads`
and `calibration_progress` of the latest fresh status for the run's request;
status of another request leaves every row blank (name only), and stale
status leaves the rows as they are. Heads outside the run are not shown. A
head mounted again for a re-measurement starts from its new readings: the
backend clears its centres and its flag when it is mounted. During a
re-measurement the rows of the other heads show their earlier readings.

Layout: `MyriadPro_Regular_22`, 36 px per row (four rows 144 px), one
column, in the progress panel's choices container below the instruction and
above the caution. Name at x 0 (88 px), mark at x 96 (24 px box), span at
x 136 (140 px). The
client's fonts have no U+2713 or U+2717 glyph, so the check (green
`0xff44cc66`) and the cross (red `0xffff6666`, the panel's failed colour) are
drawn with `lv_line`, 4 px wide. "…" is U+2026, which `MyriadPro_Regular_22`
has; it is drawn in the panel's running colour `0xffff6600`.

"Keep the door closed." is the caution at the bottom of the text column. Sending G-code from another
interface during the scrub or the probing can end the probing without a
message: any error response received while the vendor's offset stage is
active sets the vendor's `knife_pairing_failed` byte, the vendor worker then
skips the remaining probing, and nothing is reported on screen. The worker is
held in the offset stage for the whole scrub, so this applies from the first
scrub screen on. Do not send commands from another interface until the
result is shown.

The scrub screen closes when
the worker returns or the result panel shows an outcome. A failure or refusal
of the attempt during Calibrate does not change this screen; the result
panel reports it.

## Re-check

After the last head is measured, the flow checks whether the measured gauge
centres of any head disagreed. Wire-brush runs only; Rapid Alignment Mode and Printed
blob runs are not checked.

### Detection

The backend (`klipper_extras/wmp_nozzle_touch.py`) reads the vendor's probe
output from the G-code console. `calibrate_xy` touches each gauge of the
tool-setter from both sides and prints the gauge centre of each probing round:

    // Calibrated XY: <cx>, <cy>, dx: <dx>, dy: <dy>, dydx: <ratio>

One head's measurement prints six of these lines (three rounds, two passes).
Every other console line is ignored.

- Centres are attributed to the head and request that progress reports in
  phase `position`. Lines in any other phase, or while no calibration
  command of the request runs, are ignored. A new measurement of a head
  (progress enters `mounting` for it) clears that head's centres and flag.
- Span of a head on one axis: with k centres, k >= 3, the smallest
  (max - min) over every subset of k - 1 centres (for six centres the best
  five of six); with fewer than three centres 0. `centre_span` is the larger
  of the X and Y spans.
- A head is flagged when `offset_centre_spread` is above 0, the head has at
  least three centres and its `centre_span` is above `offset_centre_spread`
  (plus 1e-9 mm). An added centre never lowers the span: for k < 6 the span
  is a lower bound of the final best-five-of-six span, so a head flagged
  early stays flagged. A head with fewer than six centres at the end is
  judged on the centres it has.
- The limit is `offset_centre_spread`, 0.030 mm by default. 0 disables the
  check: no head is flagged.

Measured basis, best five of six, worse axis, mm. The 2026-11-17 runs are
`tests/fixtures/toolsetter_clean.log` and `toolsetter_residue.log`; the
2026-11-19 run is `tests/fixtures/toolsetter_19nov.log`.

| Run | Head 1 | Head 2 | Head 3 | Head 4 | Flagged |
|---|---|---|---|---|---|
| 2026-11-17, all nozzles cleaned | 0.014 | 0.022 | 0.014 | 0.009 | none |
| 2026-11-17, residue on nozzles | 0.783 | 0.050 | 0.033 | 0.011 | 1, 2, 3 |
| 2026-11-19, first measurement | 0.558 | 0.026 | 0.041 | 0.017 | 1, 3 |
| 2026-11-19, re-measurement | 0.008 | 0.023 | | | none |

In the 2026-11-19 re-measurement head 3 has four centres when the log ends.

Limits of the signal:

- Residue that shifts every centre of a head by the same amount is not
  detected and shifts the offset.
- Residue that affects only the Z measurement is not detected.
- The spread of the touches within one probing round is not used.

Status `wmp_recovery.nozzle_touch`:

| Field | Content |
|---|---|
| `protocol` | 2 |
| `request` | The request id of the attempt the status belongs to |
| `heads` | One entry per head mounted for measurement: `head` (0-based), `centres` (count), `centre_span` (mm, rounded to 6 decimals), `flagged` |
| `flagged` | The flagged heads, ascending |
| `restore` | Outcome of `_WMP_OFFSETS_RESTORE`: `none`, `done` or `failed` |

The screen accepts protocol 2 only; other status projects to no
`nozzle_touch`. It projects `heads` entries with `head` (0..3), `centres`
(0 or more), `centre_span` (0 or more) and `flagged`. An entry with any of
these missing or malformed, or with a head already listed, is left out;
`heads` that is not a list projects to an empty list.

A flagged head does not fail the attempt. No `Calibrated XY` lines means no
flag. `flagged` is complete for the request once progress has left the last
measured head's `position` phase and no measurement is running; the screen
decides only on status that shows every head of the pass measured
(`calibration_progress.measured`, `measuring` false).

### Snapshot and restore

When the backend admits an attempt's first command it records `t0_offset` to
`t3_offset` from `save_variables` (`klipper_extras/wmp_offset_snapshot.py`).
The probing macros overwrite them as each head is measured.

`_WMP_OFFSETS_RESTORE` writes the recorded values back with `SAVE_VARIABLE`
for each head. It is a sequenced calibration command, admitted only while a
command of the current pending attempt is executing it. A restore that cannot
write every head, or that has no complete snapshot (a head without a stored
offset), sets `nozzle_touch.restore` to `failed` and does not raise: a raised
error would latch the attempt's failure and refuse the `_WMP_SCRUB_END` that
cools and docks the head. The restore is written to the stored variables
only; it does not reapply the active G-code offset.

### Screen

Entered when the worker reaches its final park send (`offset_park`) on a
wire-brush run, the attempt has not stopped, fresh status for this request
carries `nozzle_touch` and lists flagged heads of this run. The worker is held
there as at the scrub stage; see [Hold at the park send](#hold-at-the-park-send).
If status is stale or the backend does not publish `nozzle_touch`, the worker
is not held and the run completes as without a re-check.

- Step list: flagged heads are red, other heads and Prepare are grey,
  Calibrate is the current step.
- Heading: "Head 2 may not be clean" / "Heads 2 and 4 may not be clean" /
  "Heads 1, 2 and 4 may not be clean".
- Instruction: "Its measurement did not repeat, which usually means residue on
  the nozzle." for one head, "Their measurements did not repeat, which usually
  means residue on the nozzle." for more.
- Per-head rows, below the instruction and above the options: the rows of
  the Calibrate state (name, mark, centre span) for every head of the run,
  from the same status, in two 284 px columns filled column by column (heads
  1 and 2 on the left, 3 and 4 on the right; 36 px per line, 72 px for three
  or four heads, 36 px for one or two). Display only.
- Option row, selected by default: "Clean again" / "Scrub the flagged heads,
  then measure again."
- Option row: "Save anyway" / "Keep the offsets as measured."
- Actions: CANCEL, CONFIRM. Sizes as on Prepare.
- The case light signal is requested when the screen is entered and is
  released on any choice, a touch or a door opening. No heater is on. There is no unattended time limit.

| Choice | Result |
|---|---|
| CONFIRM with Clean again | For each flagged head in ascending order: the Mounting, Heating, Scrub and Cooled states with the commands, limits, cancel and failure handling of the first scrub. Then each head is measured again with one `RAPID_MODE T=n`, sent by the flow. If head 1 was flagged, every head is measured again in the stock order, because head 1 is the reference of every other head; otherwise only the flagged heads. The check then runs on the heads just measured. If any is flagged the Re-check screen is shown again. There is no limit on repeats. |
| CONFIRM with Save anyway | The worker is released to its park and, on a combined run, its `SAVE_CONFIG`. The result page names the flagged heads. |
| CANCEL | The flow sends `_WMP_OFFSETS_RESTORE`, then `_WMP_SCRUB_END`; the run ends as a cancelled scrub (see [Cancel](#cancel)). |

During a re-measurement the Calibrate screen shows progress as in the first
measurement. No CANCEL is shown. A failure or refusal of the attempt during a
re-clean or re-measurement ends the offset stage as in the first pass: no
restore is made and the existing failure texts apply.

### Hold at the park send

The coordinator holds the worker inside the park send (the vendor wait
helpers have no timeout) with the loop used at the scrub stage, in 250 ms
slices. Commands of the re-check leave on the worker thread through the
worker's calibration binding, so they take the attempt's next sequence
numbers. The send hook's own decisions (the failed byte, the 5 s wait, the
withhold, the early save) are made after the hold ends. 120 s of
continuously stale status in the Re-check screen, a repeat scrub or a
re-measurement ends the scrub with `_WMP_SCRUB_END` alone: no restore is sent
and a running `RAPID_MODE` is not waited for. When no failure follows, the
result page then shows the stopped-after-probing texts (see [Result screen](#result-screen)).

While the worker is held at the park send (Re-check screen, the wait for
final status before it, repeat scrub, re-measurement), any G-code error
response sets the vendor's failed byte. When the worker is then released
toward its park (Save anyway, or a re-measurement with no flags), the vendor
takes its `quick_stop` path and does not save. The run ends as a failed
calibration, never with a save. Do not send commands from another interface
during this time.

A shutdown of the screen runtime during a re-measurement withholds the park.
The vendor still sends its ordinary `SAVE_CONFIG` afterwards (the offsets are
already in `save_variables`). The restore is not sent, and the result page
reports that the offsets could not be restored.

## Cancel

- Prepare: see above. Nothing was sent.
- Return prompt, Mounting, Heating, Scrub, Cooled: the screen shows
  "Cancelling..." / "Cooling and returning head N to its dock. Offsets are
  unchanged." with no actions. Queued mount and heat commands are dropped.
  `_WMP_SCRUB_END` switches off every heater the scrub turned on, parks the
  mounted head and releases the light signal. The worker's `RAPID_MODE` and
  park commands are not sent, so no offsets are measured.
- Calibrate has no cancel.
- Re-check: `_WMP_OFFSETS_RESTORE` writes back the offsets every head had when
  the attempt started, then `_WMP_SCRUB_END` runs as above. The screen shows
  "Cancelling..." / "Offsets are unchanged." The outcome is reported as
  stopped with the attempt still pending, so a combined run makes its
  ordinary `SAVE_CONFIG` and an offsets-only run saves nothing.
- Mounting, Heating, Scrub or Cooled of a repeat scrub: the same, after the
  cool-down and docking of the cancel.
- Re-measurement: no CANCEL is shown. The scrub screen being removed while a
  `RAPID_MODE` runs waits for that command to complete and then proceeds as
  above. The flow never sends the restore while its `RAPID_MODE` runs: the
  backend refuses a second wrapper command while one runs ("Calibration
  command is already running"), the refused command's sequence number is not
  admitted, and the run's next command is then refused as out of order, which
  fails the attempt.
- 120 s of stale status in the Re-check screen, a repeat scrub or a
  re-measurement is not handled as CANCEL: `_WMP_SCRUB_END` is sent alone,
  with no restore and no wait for a running `RAPID_MODE`, also when a cancel
  is already waiting for one. Only CANCEL and the scrub screen being removed
  restore the offsets and wait for a running `RAPID_MODE`.
- The scrub screen being removed while the worker waits on it is handled as
  CANCEL.

While the scrub screen shows "Cancelling..." and the calibration result panel
shows an outcome, the scrub screen is closed; the result panel stays through
the save and the restart.

`_WMP_SCRUB_END` runs after the commands already sent, for example the
offset-stage homing and a mount. The run stops with the failure screen when
the backend has not reported the end of the cancel and either limit is
reached:

- 60 s in which the backend was not executing a calibration command. Time
  counts while printer status is stale and while fresh status reports
  `calibration_active` as false. It does not count, and is not reset, while
  fresh status reports `calibration_active` as true.
- 300 s since the cancel began, whatever the status.

Known wording limitation: a cancel from the return prompt reads "returning
head 1 to its dock" although the scrub has not mounted a head.

## Failure

The flow stops and shows one sentence with a BACK action. The failure screen
stays until BACK is pressed. No retry or re-home is made, and no further
command is sent except `_WMP_SCRUB_END` after a scrub command could not be
sent. The `RAPID_MODE` and park commands are not sent.

Motion after the failure screen is up:

- Failure reported by the backend, "Printer restarted. Calibration stopped."
  and "Calibration did not start.": no further motion; the mounted head stays
  where it is.
- "Printer status was lost. Calibration stopped.", and "Calibration stopped.
  Check the printer before trying again." after a cancel reached its 60 s or
  300 s limit: the backend has not confirmed that it stopped. Commands
  already sent stay queued in Klipper and may still run. A running
  `_WMP_SCRUB_HEAD` finishes its mount and its move to the scrub position,
  and a queued `_WMP_SCRUB_END` switches off the scrub heaters and parks the
  head. The head may therefore still move while the failure screen is shown.

Heaters and light signal:

- Failure reported by the backend (the four "Head N" and homing sentences,
  the dock sentence, and a calibration failure seen in fresh status): the
  backend switches off the heaters the scrub turned on and releases the light
  signal.
- "Printer status was lost. Calibration stopped.", and "Calibration stopped.
  Check the printer before trying again." after `_WMP_SCRUB_END` could not be
  sent or a cancel was not confirmed within its limits: the worker is released
  without confirmation from the backend. The heater state is unknown. If
  Klipper is running, `[idle_timeout]` clears every extruder target after at
  most 600 s of inactivity. The light signal is not released by these two
  failures. Unless the backend ran `_WMP_SCRUB_END` or recorded a failure of
  the attempt, it stays on until the next calibration attempt is admitted or
  Klipper restarts.
- "Printer restarted. Calibration stopped.": a Klipper restart clears heater
  targets and the light signal.
- "Calibration did not start.": no command of the attempt ran and the
  backend runs no failure clean-up for it. When the refusal came from a
  failed switch-off of a heater of the previous scrub, that heater may still
  be on. If Klipper is running, `[idle_timeout]` clears every extruder target
  after at most 600 s of inactivity.

Stock failure path: an error response to a scrub command sets the vendor's
`knife_pairing_failed` byte. Unless the earlier-results save applies (see
[Earlier results](#earlier-results)), the byte stays set and the vendor worker
sends its own `printer.quick_stop` request after the withheld park command and
sends no `SAVE_CONFIG`. On an offsets-only run the earlier-results save never
applies, so every scrub failure that set the byte takes this path.
See [`quick_stop`](#quick_stop).

| Sentence | Cause |
|---|---|
| "The printer must be homed first." | An axis was not homed, or the Z reference was not valid, when the head was to be mounted. |
| "Head N could not be heated." | Setting the heater target failed. |
| "Head N did not mount." | The tool change failed or recorded a fault (`fail_flag`). |
| "Head N could not be moved into position." | The clearance move or the move to the scrub position failed. |
| "The head could not be returned to its dock." | The park at the end of a cancel failed. |
| "Calibration did not start." | The backend reports this run's attempt as refused while the worker is held at the offset stage. It refused a command before any command of the attempt ran, for example while `fail_flag` is set, or because switching off a heater of the previous scrub failed when the attempt was admitted. |
| "Printer restarted. Calibration stopped." | Klipper restarted during the run. |
| "Printer status was lost. Calibration stopped." | A cancel was not confirmed within its limits and status was stale. |
| "Calibration stopped. Check the printer before trying again." | Any other failure of the calibration attempt, or a scrub command that could not be sent. |

"The nozzle may still be hot." is the caution at the bottom of the text column when the
failure came after the first scrub command was handed to the worker. With
"Calibration did not start." it is shown when scrub status for this run's
request was seen at any time, and not otherwise: the backend publishes that
status once it has adopted the request, and a heater of the previous scrub
may then still be on.

A refused attempt ends the hold at once: the worker is released and its
`RAPID_MODE` and park commands are not sent.

"Mounting head 1..." is shown while the offset-stage homing is still running.
A failure of that homing is therefore reported from the Mounting screen, as
"Calibration stopped. Check the printer before trying again.".

Limits on holding the worker:

- 120 s of continuously stale printer status in the return prompt, Mounting,
  Heating, Scrub or Cooled state is handled as CANCEL.
- 120 s of continuously stale printer status in the Re-check screen, a repeat
  scrub or a re-measurement ends the scrub with `_WMP_SCRUB_END` alone: no
  restore and no wait for a running `RAPID_MODE` (see [Cancel](#cancel)).
- The wait for final flags at the park send ends after 120 s without status
  in which the flags are final, after 120 s of continuously stale status, or
  when the calibration session changes. The worker is then released and the
  run completes without a re-check; it is not cancelled.
- Run never admitted: when 120 s have passed since the worker reached the
  offset stage and no fresh status has carried scrub status for this run's
  request, the run is handled as CANCEL. This covers refusals the backend
  does not publish as this run's attempt, for example a command refused
  because another calibration command is running or because its ticket is
  not valid.
- A cancel that the backend has not reported as ended stops the run with a
  failure sentence after 60 s without the backend executing a calibration
  command, or after 300 s in total (see [Cancel](#cancel)). The worker is
  released; its `RAPID_MODE` and park commands are not sent.

Starting again after a failure:

- With an ACE (status owner other than standalone) the screen refuses START
  while the backend's calibration failure is set. It is cleared by a Klipper
  restart.
- Without an ACE, START is accepted and the new attempt clears the previous
  failure when the backend admits its first command. The backend refuses that
  command while the saved `fail_flag` is not 0 and reports the attempt as
  refused. A wire-brush run then shows "Calibration did not start." on the
  scrub screen when the worker reaches the offset stage. The result panel
  shows "Calibration did not start." with the reason while fresh status
  reports this run's attempt as refused. Clear the tool-change fault first.

A scrub command that cannot be sent discards the queued commands and sends
`_WMP_SCRUB_END` alone. When the failed command never reached the backend,
that `_WMP_SCRUB_END` is refused as out of sequence; the backend's failure
handling then switches off the scrub heaters and releases the light signal,
and the head is not parked.

## Earlier results

Rule: when the offset stage of a wire-brush run stops, bed level, vibration
and PID results completed earlier in the same run are saved once.

- Scrub cancelled: the attempt has not failed. The worker sends its ordinary
  `SAVE_CONFIG` when bed level, vibration or PID was selected.
- Scrub failure or probing (`RAPID_MODE`) failure: the backend admits one
  `SAVE_CONFIG` for the failed attempt (the early save) when all of these
  hold: the attempt is the current one, its first failure happened in the
  offset stage, at least one of `G29`, `SHAPER_CALIBRATE` or `PID_CALIBRATE`
  completed in the attempt without error, no early save was admitted for it
  before, and the printer is not shut down or quick-stopped. It reports this
  as `calibration_attempt.early_save_available`. Every other command of the
  failed attempt stays refused. A set `fail_flag` does not block this save
  and is not cleared by it. The attempt stays failed and the backend's
  failure text stays set after the save.

The early save is requested only when the screen sees
`early_save_available` in fresh status for this run's attempt at the worker's
withheld park command. It then clears the vendor's `knife_pairing_failed`
byte and the vendor worker sends its `SAVE_CONFIG`.

Admission of the write and of its restart:

- Without an ACE or AFC, `SAVE_CONFIG` and every restart request pass the
  restart gate of `klipper_extras/wmp_config_save.py`. While a calibration
  command is running the gate admits only the save that
  `CalibrationCommands.save_admitted()` reports: the ordinary save (no
  failure set) or the early save admitted for the current failed attempt.
  A `SAVE_CONFIG` or restart request from any other source is refused while
  another calibration command is running. While the admitted save itself
  runs the gate cannot tell a second request apart from it. The gate's other conditions apply to
  the early save as to the ordinary save: no print running or paused, no
  managed print cancellation or recovery in progress, no filament or tool
  operation pending or running, no print submission pending and no profile
  import being saved.
- With an ACE or AFC the gate is not applied, as for the ordinary save.

The same conditions decide the early save with and without an ACE.

Limits:

- The rule covers the offset stage only. A failure in bed level, vibration or
  PID keeps the stock behaviour: nothing is saved.
- After a probing failure the rule applies to wire-brush runs only. A Rapid
  Alignment Mode run or a Printed blob run takes the stock failure path
  (`quick_stop`, no `SAVE_CONFIG`).
- A homing (`G28`) failure at the start of the offset stage does not keep
  earlier results. The backend cannot tell that `G28` from the earlier stages'
  `G28`.
- Nothing is saved when printer status is stale, or does not yet report
  `early_save_available`, at the worker's park command. The stock failure path
  runs. After a probing failure the park command waits up to 5 s for that
  status.
- The early save is admitted once. When it is refused after admission (by the
  gate's other conditions, or by a busy probe editor) or the configuration
  writer fails, nothing more is saved for the attempt and the save is not
  repeated. A refusal by the gate happens before the configuration file is
  written.
- Offsets are stored per head by the probing macros as each head is measured.
  A probing failure on a later head leaves the offsets of earlier heads
  stored.
- An offsets-only run sends no `SAVE_CONFIG`.

## Result screen

The existing calibration result panel reports the outcome on the stock
progress page. Outside the setup guide it covers the factory content card,
including its OK header (700 x 415 px at x 90, y 55 on the 800 x 480
screen), with one background (`0xff3c3f43`) and one header: the title
"Calibration" and one header action. Text is `MyriadPro_Regular_22`. The
action reads DONE on a result once the vendor worker has returned, and BACK
while the panel waits for printer status, shows "Saving calibration
settings..." or the worker still runs (a save can still follow); both leave
the page and send nothing. The save counts as requested once the screen has
sent the run's save (whatever the status freshness or session) or fresh
status of the run's session shows a pending or saved receipt for it. From
then on the saving text stays through stale status, and a restart without a
confirmed save reports the save as not verified.

| Outcome | Text |
|---|---|
| Printer status not yet available | "Waiting for printer status..." |
| Fresh status reports this run's attempt as refused | "Calibration did not start." followed by the backend's reason |
| Offsets-only wire-brush run completed | "Nozzle offsets saved." |
| Offsets-only Rapid Alignment Mode or Printed blob run completed | No panel; the stock completion page is shown |
| Run with other checks completed | "Saving calibration settings..." / "Restarting Klipper..." and, after the restart, "Restarting Klipper... Done." / "Calibration settings saved." |
| Wire-brush offsets-only run released by Save anyway with flagged heads | "Nozzle offsets saved. Head 2 may not be clean." ("Heads 2 and 4 may not be clean.") |
| Wire-brush combined run released by Save anyway with flagged heads | "Saving calibration settings..." / "Restarting Klipper..." and, after the restart, "Restarting Klipper... Done." / "Calibration settings saved. Head 2 may not be clean." |
| Wire-brush offsets-only run, Re-check cancelled | "Offset calibration cancelled. Offsets are unchanged." |
| Wire-brush combined run, Re-check cancelled | "Saving calibration settings..." / "Restarting Klipper..." and, after the restart with a confirmed save, "Restarting Klipper... Done." / "Offset calibration cancelled. Earlier results were saved." |
| Re-check cancelled, offsets not restored, offsets-only run | "Offsets could not be restored. Run the calibration again." |
| Re-check cancelled, offsets not restored, combined run | After the restart with a confirmed save: "Restarting Klipper... Done." / "Earlier results were saved. Offsets could not be restored. Run the calibration again." |
| Wire-brush run, offset stage stopped before probing, no save requested | "Offset calibration stopped. Offsets are unchanged." |
| Wire-brush run, offset stage stopped before probing or after a failure, save requested | "Saving calibration settings..." / "Restarting Klipper..." and, after the restart with a confirmed save, "Restarting Klipper... Done." / "Offset calibration stopped. Earlier results were saved." |
| Wire-brush offsets-only run, offset stage stopped after probing had started, no failure, no cancel (for example 120 s of stale status during the re-check) | "Offset calibration stopped. Offsets were changed and may not be reliable. Run the calibration again." once the worker has returned |
| Wire-brush combined run, offset stage stopped after probing had started, no failure, no cancel | "Saving calibration settings..." / "Restarting Klipper..." and, after the restart with a confirmed save, "Restarting Klipper... Done." / "Offset calibration stopped. Earlier results were saved. Offsets were changed and may not be reliable. Run the calibration again." |
| Wire-brush run, offset stage stopped before probing, save refused or failed | "Offset calibration stopped. Offsets are unchanged. Earlier results were not saved." / "Check the printer before trying again." |
| Wire-brush run, probing failure, no save requested, or save refused or failed | "Calibration stopped." followed by the backend error text and "Inspect the printer before retrying." |
| Rapid Alignment Mode or Printed blob run, failure at any stage | "Calibration stopped." followed by the backend error text and "Inspect the printer before retrying." |
| Restart without a confirmed save | After a save of this run was requested: "Restarting Klipper... Done." / "Saved calibration settings could not be verified." / "Check the saved settings before retrying."; otherwise "Printer restarted. Calibration result could not be confirmed." / "Check the saved settings before retrying."; either followed by "Previous error: " and the error text when a failure was recorded before the restart, and by "Offsets could not be restored. Run the calibration again." when the Re-check was cancelled and the restore was not reported done |

After a failure the "Offset calibration stopped." texts end with "Check
the printer before trying again." The texts with "Offsets were changed and
may not be reliable." are shown only when no failure of the attempt was seen.

The cancelled texts and the restore-failed texts are shown when the Re-check
was cancelled and the restore command was queued (a restore whose send failed
does not count), or a shutdown of the screen runtime left the restore unsent:
during a re-measurement, or in the Re-check screen or a repeat scrub, where
the shutdown queues the restore and nothing more is sent. The restore
counts as failed unless `nozzle_touch.restore` was `done` for this run's
request when last seen; the native result state holds it, because backend
status is lost at the `SAVE_CONFIG` restart. A failed restore is reported in
place of a failure text of the attempt. The flagged heads, the choice made and
the restore outcome are held natively in the same way. A run that failed
(the failure texts above) does not restore and shows those texts.

The "Offset calibration stopped." texts are shown for wire-brush runs
only. A Rapid Alignment Mode or Printed blob run has no scrub screen, so its
result panel shows the stock texts with the backend's error text, also when
the failure happened in the offset stage.

A save is taken as refused or failed when the save result published for this
run's session and request is `unconfirmed` with an error text. No restart
follows, so "Saving calibration settings..." is not shown for a stopped wire-brush run
from then on. The error text shown after "Calibration stopped." is the
attempt's error; a failed save replaces the attempt's earlier error with its
own. The backend publishes that result with the run's session and request
also when it refuses the save before preparing its receipt (early save not
admitted, probe editor open, live checks). A save result of `unconfirmed` with
an error is also published when the save's diagnostic record could not be
written while the save itself proceeds; the restart then follows and the
restart text applies.

"Nozzle offsets saved." is shown when all of these hold: the run was a
wire-brush run, the backend reports the attempt's offsets as measured with no
failure, progress reported for this run's request reached its parking phase
(published when the backend admits the worker's final park command) with
every head of the run measured for this request (`calibration_progress.measured`;
after a partial re-measurement the last probed head can be another one), and
the worker has returned without sending `SAVE_CONFIG`. The panel covers the stock completion page;
BACK returns to the Maintenance page.

The panel of a run started from the Maintenance page is bound to that run's
calibration attempt (its session and request). The backend keeps one failure
text for all attempts (`calibration_failed`) and clears it when it admits the
first command of a new attempt. A bound panel does not read that text: it
shows the error of this run's attempt once that attempt is seen as failed,
and keeps it when another attempt replaces the published record. A retry
therefore does not show the failure the previous run left there. A page that
has no request (the first-run guide) uses the backend's failure text.

Whether the offset stage stopped, whether offsets were measured and whether
probing started are taken only from status for this run's request.

## Configuration

Options of the `[wmp_recovery]` section in `printer.cfg`
(`klipper_extras/wmp_nozzle_scrub.py`). All are optional.

| Option | Default | Limits | Meaning |
|---|---|---|---|
| `scrub_x` | 150 | none | X of the scrub position, mm |
| `scrub_y` | 2 | none | Y of the scrub position, mm |
| `scrub_z` | 100 | 20 to 250 | Z of the scrub position, mm |
| `scrub_temp` | 160 | 0 to 170 | Nozzle target during the scrub, °C |

The option `offset_centre_spread` of the same section is read by
`klipper_extras/wmp_nozzle_touch.py`:

| Option | Default | Limits | Meaning |
|---|---|---|---|
| `offset_centre_spread` | 0.030 | 0 or more; 0 disables | Largest accepted centre span of a head (best five of six measured gauge centres, worse axis) during offset measurement, mm (see [Detection](#detection)) |

Y2 is the front clearance already used by `config/live/offset_calibrate.cfg`.
The Scrub state starts at a reported 158 °C whatever `scrub_temp` is; a
`scrub_temp` below that value never reaches the Scrub state.

## Case light signal

The scrub requests the `wmp_case_light` attention signal
(`_WMP_SCRUB_ATTENTION VALUE=1`) on entry to the return prompt, Scrub, Cooled
and Re-check states, and releases it (`_WMP_SCRUB_ATTENTION VALUE=0`) on
CONFIRM, cancel, a failure the backend recorded and at the start of the next
calibration attempt.

While the signal is on, the first of these also releases it:

- A touch anywhere on the screen, on any page. The coordinator reads the
  display's inactive time (`lv_disp_get_inactive_time`, `0x69725c`) on every
  GUI tick. The client counts it in its LVGL tick, which is based on
  `gettimeofday` (`custom_tick_get`, `0x449b80`). A touch is a decrease of
  that value since the previous GUI tick; it is taken to have happened at
  the previous tick, and it releases the signal when the signal was
  requested no later than that. A touch in the same GUI tick interval in
  which the signal started does not release it. A wall-clock step back
  smaller than the inactive time also reads as a decrease. The touch is
  delivered as usual and may also press a control.
- A door opening: either door switch (`gcode_button Door_button1`,
  `Door_button2`) going from closed (`PRESSED`) to open (`RELEASED`) between
  two fresh status snapshots. The screen projects the door state as `doors`
  (bit n set while door n+1 is open, -1 without door state or while Klipper
  is not ready); an unknown state in between keeps the last known one. A door
  already open when the signal is requested does not release it, and neither
  does a door that opens in the same status snapshot that starts the signal.

The release is queued like the other scrub commands and leaves through the
held vendor worker. The signal is not requested again in the same state; the
next entry to the return prompt, Scrub, Cooled or Re-check requests it
again. In the vendor client `lv_disp_trig_activity` is called only from
`lvgl_init`, so the inactive time is reset only by input. After "Printer status was lost. Calibration stopped." or a failed
`_WMP_SCRUB_END` the backend may not have run a release; the signal then
stays on until the next calibration attempt is admitted or Klipper restarts.
The signal blinks
the case light away from its resting state. It is enabled by default and is
switched with:

```gcode
SET_CASE_LIGHT_ATTENTION ENABLE=0
SET_CASE_LIGHT_ATTENTION ENABLE=1
```

See [Attention signal](../config/README.md#attention-signal).

## Tool-setter false triggers

`klipper_extras/wmp_tool_probe.py` handles a touch of the tool-setter
(load-cell CELL board) that is reported before the probing move has
travelled: a bad load-cell zero or a bad first sample. Such a touch stops
within a few motor steps of its start.

- What it does: it replaces `run_probe` of the vendor's
  `tools_calibrate.probe_multi_axis` with a copy that keeps the vendor
  sampling, tolerance retry and median or mean result. A touch that
  travelled less than 0.1 mm (`MIN_TRAVEL`), or that the vendor reports as
  `Probe triggered prior to movement`, is discarded once per `run_probe`
  call (`MAX_REPEATS` 1): the head returns to the touch start, the sensor is
  zeroed again after 0.75 s and the touch is repeated from the same
  position. A second such touch in the same call is kept as a contact, or,
  without any movement, raises `Probe triggered prior to movement` as the
  vendor does.
- Guard: `install()` replaces the method only when the SHA-256 of
  `inspect.getsource` of the vendor `run_probe` is `STOCK_RUN_PROBE_SHA256`
  (the reviewed 1.1.13 source); otherwise it logs a warning, changes nothing
  and returns False. Without `tools_calibrate` it returns False.
  `BottomZ._connect` in `klipper_extras/wmp_recovery.py` calls it at
  `klippy:connect`; an exception from it is logged and does not reach the
  connect handler. A `[wmp_tool_probe]` section, if configured, calls it as
  well.
- Console line for each discarded touch:
  `WM+: load-cell false trigger after <travel> mm travel; re-zeroing and
  repeating the touch` (travel with four decimals). A discarded touch prints
  no `Probe made contact` line. The centre rule of the re-check
  ([Detection](#detection)) reads only `Calibrated XY` lines and ignores
  this one.

The module is installed with the backend helpers (`HELPERS` in
`tools/components/material.py`) and is a screen package runtime input
(`runtime_inputs.py`). Its tests are `klipper_extras/test_wmp_tool_probe.py`.

## Library requirements

`screen.so` is an AArch64 library with the `NODELETE` flag. It requires no
glibc symbol version other than `GLIBC_2.17` and lists `libstdc++.so.6`,
`libm.so.6`, `libgcc_s.so.1`, `libpthread.so.0`, `libdl.so.2` and `libc.so.6`
as needed libraries. `libm.so.6` is needed for one function, `lround`, which
rounds the temperature to whole degrees. The highest libstdc++ symbol version is
`GLIBCXX_3.4.26`. Timed waits use `pthread_cond_timedwait`.
`tests/test_screen_package_current.py` asserts that `GLIBC_2.17` is the only
glibc symbol version and that the needed libraries are a subset of these
six. The installer checks library and symbol resolution on the printer
before it publishes the library.

## Not yet verified on the printer

No part of this flow has been run on a printer. Everything above is
established by unit tests, emulation of the vendor worker and disassembly.
Specific unknowns:

Runs to make:

- An offsets-only run.
- A combined run with PID.
- Cancel at each state.
- Unattended timeout and reheat.
- Printed blob hand-off.

Loading and screen:

- That the library loads on the printer, whose glibc version is not recorded.
- Rendering and text fit of every screen on the real panel.
  `test_progress_panel_real_font_fit` lays out each state's text
  (`scrub-state-*` in `tests/fixtures/progress_panel_views.json`) with the
  client's own text measurement under emulation; whether the panel renders
  the texts as measured is not known.
- Mis-taps where the CANCEL, CONFIRM and BACK touch areas extend over the
  first line of the text column.
- Whether the re-sent START press behaves like a touch on the START button.
- Whether vendor navigation removes the scrub screen during a run.
- That the Calibrate screen closes when the worker returns.
- "Nozzle offsets saved." covering the stock completion page, and its BACK
  action.
- Whether the calibration result panel can appear over the scrub screen, and
  which of the two is then on top.

Motion and heating:

- The sequence on hardware: mount through `_WMP_CALIBRATION_TOOL`, heat, move
  to the scrub position, and the worker hold after the offset-stage `G28`.
- The scrub height (Z100) and the front clearance at X150 Y2 for brush access.
- Which of the flow's timeout and `[idle_timeout]` fires first, and the
  reheat that follows.
- That `[idle_timeout]` in the installed `printer.cfg` still has a timeout of
  600 s and switches the heaters off. It is the only bound on the scrub
  heaters that does not depend on this project's code or on printer status
  reaching the screen.

Timing limits:

- That 60 s without a running calibration command, and 300 s in total, are
  enough for an ordinary cancel (queued homing and mount, cool, park).
- That 120 s is enough for the backend to admit the run after the worker
  reaches the offset stage.
- That status reporting a probing failure arrives within the 5 s wait at the
  park command.

Earlier results:

- The early save through the standalone restart gate on the printer. It is
  covered by unit tests that run the gate with the calibration commands
  (`tests/test_calibration_early_save_gate.py`); the other managed-operation
  conditions of the gate were not exercised with real state.
- The save on the real client. The `knife_pairing_failed` clear is verified
  in emulation only, and the wait helpers' path with `idle_timeout_state` =
  `Printing` is not covered.
- The vendor's `quick_stop` request after a failed scrub.

Re-check:

- That the console lines of the vendor's probe output reach the G-code output
  handler in the form of the logs the parser was written against. Without
  them no head is flagged.
- The limit of 0.0094 mm on other printers, with other nozzles, and with warm
  nozzles. It rests on two runs on one printer, one of them clean (240
  touches).
- The hold at the park send on hardware, including that no G-code error
  response arrives from another source while the worker is held: such a
  response sets the vendor's failed byte, and the release then ends as a
  failed calibration through `quick_stop` and never saves.
- The restore of the stored offsets on hardware, and the result page after a
  cancelled re-check and its restart.
- That no `CANCEL` is available during a re-measurement.
- The 120 s stale-status limit during the Re-check screen and a
  re-measurement: `_WMP_SCRUB_END` alone while a `RAPID_MODE` may still run,
  and the result page that follows.

Light:

- Visibility of the light signal.
- Release of the signal by a touch on another page and by a door opening.

## Vendor worker findings

Scope: client 1.1.13 (SHA-256 prefix `b60c96c5`), worker `auto_checking`
(`0x4b7558`), offset stage (worker status 11, entry `0x4b7ee8`). Sources:
disassembly of the client, the stock 1.1.13 Klipper sources, and the Unicorn
cases in `tests/test_stock_calibration_worker.py`. Nothing was sent to a printer.

### Offset stage sequence

1. `0x4b7f74`-`0x4b7f8c`: `knife_pairing_ing` (`0xe64572c`) = 1,
   `knife_pairing_failed` (`0xe64572d`) = 0.
2. `G28` send (returns to `0x4b7fbc`). No wait helper follows it.
3. `is_rapid_mode` (`0x384c570`) is read once at `0x4b7fd4`. Value 0 runs the
   accurate per-head loop first (`NOZZLE_PREPARE` send returning to `0x4b80b8`,
   `wait_tool_calibrate_sync`, popup `0x59`, `NOZZLE_CALIBRATE_TOOL_OFFSET` send
   returning to `0x4b82e4`, `wait_tool_calibrate_sync`). A failed byte of 1 after
   the first wait or after the popup leaves that loop for step 4.
4. `RAPID_MODE` loop, heads 0 to `current_thr_number` - 1 (`0x385c260`). At the
   head of each iteration (`0x4b832c`) a failed byte of 1 ends the loop.
   Otherwise `calibrate_tool` (`0xe645734`) = head + 5, `RAPID_MODE T=n` is sent
   (returns to `0x4b842c`) and `wait_tool_calibrate_sync` is called. Its return
   value is not read.
5. `PARK_CURRENT_TOOL` send (returns to `0x4b847c`), then `wait_sync`. Its
   return value is not read.
6. The failed byte is read at `0x4b8498`. Value 1 calls `quick_stop()`
   (`0x4b850c`).
7. `knife_pairing_ing` = 0 (`0x4b8518`), status = 12, `calibrate_tool` = 9.
8. Status 12 (`0x4b8540`): sleep 1 s, status = 13.
9. Status 13 (`0x4b856c`): the failed byte is read at `0x4b8574`. Value 1 clears
   the byte, sets status 14 and sends nothing. Otherwise the byte is cleared
   and, when any of `auto_check_selected[0..2]` (`0x385fa88`) is 1,
   `SAVE_CONFIG` is sent (returns to `0x4b869c`), `has_subscribed_printer_objects`
   (`0xe645169`) is cleared, the worker sleeps 3 s, then polls once per second
   until `klipper_state` equals `ready`, and sets status 14.

The failed byte is written to 1 only by `parse_gcode_response` (`0x63b848`) and
only while `knife_pairing_ing` is 1. Within this worker that window is steps 1
to 7.

### References to the pairing bytes

A scan of the text segment for `ADRP`/`ADD` pairs that form `0xe64572c` or
`0xe64572d` finds the following references. Indirect references are not
excluded by this scan.

| Owner | `knife_pairing_ing` (`0xe64572c`) | `knife_pairing_failed` (`0xe64572d`) |
| --- | --- | --- |
| `auto_checking` (`0x4b7558`) | write 1 at `0x4b7f80`, write 0 at `0x4b8518` | write 0 at `0x4b7f8c`, `0x4b85f0`, `0x4b8610`; read at `0x4b80ec`, `0x4b81fc`, `0x4b832c`, `0x4b8498`, `0x4b8574` |
| `wait_tool_calibrate_sync` (`0x4b8bc4`) | none | read at `0x4b8c50` |
| `check_knife_pairing` (`0x50aecc`), the first-run guide worker | write 1 at `0x50af94`, write 0 at `0x50b104` | write 0 at `0x50afa0`, `0x50b1c8`; read at `0x50afc8`, `0x50b0f4` |
| `parse_gcode_response` (`0x63b3ec`) | read at `0x63b830`, read at `0x63c5dc` | write 1 at `0x63b848` |

`check_knife_pairing` opens its own window in which the failed byte can be
latched. It is a separate worker and is not part of the maintenance run.

The second read in `parse_gcode_response` (`0x63c5dc`) is reached when
`warning_msg` (`0xe6458a8`) contains `ZRU-C015`. With `knife_pairing_ing` = 1:

- `current_extruder` (`0xe64570c`) = `0x63`: an error is logged and the function
  returns 0.
- Otherwise `push_warning` (`0x54b368`) is called with
  `Toolhead <current_extruder + 1> offset calibration failed. Check if hotend or
  nozzle gauge is tilted/damaged.` and the function returns 0.

With `knife_pairing_ing` = 0, or without `ZRU-C015`, control continues at
`0x63c77c` into the general warning handling. That path was not characterised.

### Wait helpers

`wait_tool_calibrate_sync` (`0x4b8bc4`) and `wait_sync` (`0x6426dc`) take no
argument and hold no reference to the preceding send. Both read two client
globals: `idle_timeout_state` (`0xe6451b0`) and `klipper_state` (`0xe645170`).

1. Sleep 1 s.
2. If `idle_timeout_state` is not `Printing`, return 0.
3. Loop: if `idle_timeout_state` is not `Printing`, return 0. Sleep 1 s. If
   `klipper_state` is not `ready`, log and return 1; otherwise repeat.

`wait_tool_calibrate_sync` differs in one condition: in step 3 it also returns 1
when `knife_pairing_failed` is 1.

When no command was sent, the helper returns 0 after the single 1 s sleep,
provided `idle_timeout_state` is not `Printing` at that moment. When another
command is still running (state `Printing`), the helper waits for that command
to finish. Neither helper has a timeout.

### `quick_stop`

`quick_stop()` (`0x616558`) logs `quick_stop`, builds a JSON-RPC request with
method `printer.quick_stop` (`json_quick_stop`, `0x558004`) and sends it with
`WebSocketClient::send` to `ws://localhost:7125/websocket`. It writes no client
state and does not wait.

Stock Klipper 1.1.13 (`klippy/webhooks.py`, `_handle_quick_stop_request`):

- When `print_stats.state` is `printing` or `paused`, it calls
  `pause_resume.send_cancel_command()`.
- When `idle_timeout` state is `Printing`, it sets
  `printer.quick_stop_flag = True`. Otherwise it responds
  `Not Busy, Quick Stop Ignored` and leaves the flag unset.
- The flag is initialised False in `klippy.py` and is cleared by
  `_handle_not_printing`, registered for the `idle_timeout:ready` and
  `idle_timeout:idle` events. It therefore clears when the busy period that was
  running at the request ends, or on a Klipper restart.
- While the flag is set, `gcode.py` `_process_commands` stops processing queued
  lines (`quick Stop, return`), `gcode_move` drops moves, `probe` aborts its
  sample loops and `heaters` leaves its temperature waits.

This project's modules also read the flag: `CalibrationCommands._check`
(`klipper_extras/wmp_calibration.py`) refuses calibration commands with
`Printer quick-stop is active`, and the `SAVE_CONFIG` wrapper in
`klipper_extras/wmp_config_save.py` refuses with
`Configuration save stopped: gcode.quick_stop_flag is set`.

In the worker, `quick_stop()` is called after `wait_sync` has returned, which
happens when the client's `idle_timeout_state` is not `Printing` or its
`klipper_state` is not `ready`.

### Emulated cases

All three cases start `auto_checking` at its entry with status 11,
`is_rapid_mode` = 1, `auto_check_selected` = [1, 0, 0, 1] and four heads, and
run until the worker returns. The worker and both wait helpers execute their own
instructions. The sender (`0x614338`), `quick_stop` and sleep are recorded and
skipped. The string comparisons answer for `idle_timeout_state` = `Ready` and
`klipper_state` = `ready`.

| Case | Sends (return addresses) | `quick_stop` | Final status |
| --- | --- | --- | --- |
| `test_offset_stage_with_withheld_sends_reaches_save`: failed byte stays 0, no send has any effect | `0x4b7fbc`, `0x4b842c` × 4, `0x4b847c`, `0x4b869c` | 0 | 14 |
| `test_failed_byte_cleared_at_park_send_avoids_quick_stop`: failed byte set to 1 at the first `0x4b842c` send, cleared at the `0x4b847c` send | `0x4b7fbc`, `0x4b842c`, `0x4b847c`, `0x4b869c` | 0 | 14 |
| `test_failed_byte_left_set_calls_quick_stop_and_skips_save`: failed byte set to 1 at the first `0x4b842c` send and left set | `0x4b7fbc`, `0x4b842c`, `0x4b847c` | 1 | 14 |

In the first case each wait helper call sleeps once (return addresses
`0x4b8bd8` × 4 and `0x6426f0`) and returns at its first state check. The
worker sleeps 7 s in total between the stage entry and stage 13: 1 s at
`0x4b7f70`, 5 s in the helpers and 1 s in status 12.

Not covered by these cases:

- The accurate branch (`is_rapid_mode` = 0), including popup `0x59`. Its
  description above is from disassembly only.
- An `idle_timeout_state` of `Printing` during a wait helper. Its description
  above is from disassembly only.
- The backend. A `SAVE_CONFIG` sent from `0x4b8698` is still subject to
  `CalibrationCommands` in `klipper_extras/wmp_calibration.py`. It refuses the
  save for a failed attempt and when `fail_flag` is set, except for one save
  after a failure in the offset stage when bed level, vibration or PID
  completed earlier in the attempt and the printer is not shut down and not
  quick-stopped. It reports that case as
  `calibration_attempt.early_save_available`.

### Decision

Mechanism A is used. After an abnormal scrub end or a probing failure in a
wire-brush run, the preload withholds the sends that return to `0x4b842c` and
`0x4b847c`. Inside the hook for the send that returns to `0x4b847c` it clears
`knife_pairing_failed` only when the byte is 1 and fresh status reports
`early_save_available` for the worker's attempt; the worker's own stage-13
`SAVE_CONFIG` (send returning to `0x4b869c`) then carries the earlier results.
When the backend would refuse the save the byte is left at 1 and the worker
takes its stock failure path (`quick_stop`, no `SAVE_CONFIG`). A cancelled
scrub leaves the byte at 0 and the worker sends its ordinary save.

Basis:

- With both sends withheld the worker reaches the `SAVE_CONFIG` send and does
  not call `quick_stop` (first case).
- With the failed byte set before the park send and cleared at `0x4b847c`, the
  worker does not call `quick_stop` and sends `SAVE_CONFIG` (second case).
  Without the clear it calls `quick_stop` and sends no save (third case).
- The wait helpers depend only on `idle_timeout_state`, `klipper_state` and the
  failed byte, and return without a send.
- No `printer.quick_stop` request is issued, so `quick_stop_flag` does not need
  to be cleared before the save.

Conditions on the implementation:

- Between the clear at `0x4b847c` and the read at `0x4b8498` the worker runs
  `wait_sync` (at least 1 s) with `knife_pairing_ing` still 1. A G-code error
  response arriving in that interval sets the failed byte again and restores the
  stock failure path. Requirement: no command that can raise is running when
  the hook at `0x4b847c` clears the byte and returns.
- The hook does not write `knife_pairing_ing`. Writing 0 there would close the
  interval above, but it also changes the `ZRU-C015` branch at `0x63c5dc` (see
  "References to the pairing bytes") from the offset-specific `push_warning`
  to the path at `0x63c77c`, which was not characterised. That write is
  unverified and is not part of mechanism A.
- An error raised by a scrub command while `knife_pairing_ing` is 1 sets the
  failed byte. In rapid mode this only ends the `RAPID_MODE` loop early. It is
  removed by the clear at `0x4b847c` when that clear is made.
- The accurate branch sends `NOZZLE_PREPARE` and `NOZZLE_CALIBRATE_TOOL_OFFSET`
  before the `RAPID_MODE` loop. Withholding only `0x4b842c` and `0x4b847c` does
  not stop those sends.
- The backend latch must admit the worker's `SAVE_CONFIG` for this outcome.
- `SAVE_CONFIG` is sent only when bed level, vibration or PID was selected. An
  offsets-only run sends none.

## Fonts and sizes

Fonts of the 1.1.13 client (`b60c96c5`) that the scrub screen uses. They are
`lv_font_t` objects; pixel sizes are the nominal sizes in the symbol names.

| Address | Symbol | Line height | Use on the scrub screen |
|---|---|---|---|
| `0x2f19bd8` | `MyriadPro_Regular_22` | 28 | Step list, instruction and caution (drawn by the progress panel); option names and descriptions; Calibrate rows |
| `0x1a50440` | `MyriadPro_Bold_24` | 29 | Title, heading and temperature (drawn by the progress panel) |
| `0xf84928` | `MyriadPro_Bold_20` | 25 | CANCEL, CONFIRM, BACK |

22 px is the minimum set for instruction text on this display.

The fonts are symbols in `make_profile.py` (`NAMES`), which writes their
addresses and line heights to `profile1113.hpp`. The scrub screen names one
font itself, `MyriadPro_Regular_22` for the Calibrate rows
(`StockScrubReadings`); the panel, `StockOptionRow` and `stock_header_action`
name the others.

Glyph coverage, read from the font descriptors in the client binary:
`MyriadPro_Regular_16`, `_20`, `_22`, `_24` and `MyriadPro_Bold_20`, `_24`
have U+2026 and U+00D7 but no U+2713, U+2714, U+2717 or U+2718 and no
U+F00C or U+F00D (`LV_SYMBOL_OK`, `LV_SYMBOL_CLOSE`). `lv_font_montserrat_14`
has U+F00C and U+F00D at 14 px.

Other fonts of the same client, not used by the scrub screen:

| Address | Symbol | Line height | Note |
|---|---|---|---|
| `0x26297a0` | `MyriadPro_Regular_16` | 20 | Body font of older screens; below 22 px |
| `0x1476670` | `MyriadPro_Bold_22` | 26 | |
| `0x34b82a8` | `MyriadPro_Regular_24` | 30 | |
| `0x1a57128` | `MyriadPro_Bold_30` | 36 | |
| `0x34b94f0` | `MyriadPro_Regular_44` | not recorded | Has only the glyphs `%` and `0`-`9` |
