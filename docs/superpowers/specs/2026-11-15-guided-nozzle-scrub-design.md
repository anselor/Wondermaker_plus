# Guided nozzle scrub for accurate offset calibration

Status: implemented on branch `feature/brush-nozzle-scrub-split`; not validated on a printer.
Firmware: 1.1.13 screen client (AArch64, SHA-256 prefix `b60c96c5`, as recorded in `client-preload/unified-ui/native/profile1113.json`).
Branch: `feature/brush-nozzle-calibration`, cut from `4b78316`. It will be rebased onto the final r4 branch.

## Intent

The stock "Accurate Alignment Mode" cleans each nozzle before measuring offsets by
printing a blob on the bed, cooling it, and asking the user to remove it. This
requires every head to be loaded with filament and depends on the residue on the
nozzle bonding to the loaded material.

This design adds a guided manual clean: each head is mounted, heated and brought to
the front of the printer, and the user scrubs the nozzle with a wire brush. After
the last head, the stock rapid probing sequence measures the offsets. The stock
blob method stays available as an option.

## Goals

- When the user starts a maintenance run with offset calibration in Accurate mode,
  offer the wire-brush clean (default) or the stock printed-blob clean.
- Walk the user through scrubbing every head in sequence with a step list on the
  left and one short instruction on the right.
- After the last head is confirmed, measure offsets with the unchanged stock
  rapid sequence (`RAPID_MODE T=n` per head, sent by the vendor worker).
- Signal that the printer is waiting for the user by blinking the case light,
  controlled by a saved setting that is enabled by default.

## Non-goals

- No change to Rapid Alignment Mode, to the first-run setup calibration
  (`check_knife_pairing`, fixed to rapid), or to the probing macros.
- No change to the stock chooser popup or the Maintenance page layout.
- No general alert mechanism for other screens.
- No sound. No buzzer or audio device was found in the configuration or firmware
  image; this was not checked on the printer.

## Anti-goals

- The nozzle must not be left heated indefinitely with nobody at the printer.
- A cancelled or failed scrub must not change stored offsets.
- The flow must not home, re-home or retry a tool change automatically after a
  coupling failure.
- Screen text must not show internal state, addresses, session identifiers or
  development notes.

## Stock behaviour this builds on

Verified by disassembly of the 1.1.13 client unless marked otherwise.

- Maintenance handler `0x4b4768`: userdata 6 is the offset row. Ticking it opens
  `draw_select_knife_pairing` (`0x4b5538`) with "Rapid Alignment Mode" and
  "Accurate Alignment Mode". The handler (`0x4b5490`) writes `is_rapid_mode`
  (`0x384c570`, one byte, 1 = rapid, 0 = accurate, initial 1) and sets
  `auto_check_selected[3]` (`0x385fa8b`). The byte is not persisted. The popup is
  shown every time the row is ticked.
- Userdata 0 is START. It refuses while printing, sets the worker status from the
  first selected item and navigates to `auto_checking_page`, which enqueues the
  worker `auto_checking` (`0x4b7558`).
- Worker stage order is fixed: bed level, vibration, PID (every nozzle to 220 °C),
  then offsets last.
- Offset stage: `G28` is sent (return address `0x4b7fbc`), then `is_rapid_mode` is
  read once at `0x4b7fd4`.
  - Accurate only, per head: `NOZZLE_PREPARE S=<filament temp> T=n`, popup `0x59`
    ("ensure the button-like purged debris has been manually removed") blocking
    until OK, `NOZZLE_CALIBRATE_TOOL_OFFSET T=n` (heat to 160 °C, wipe on the
    built-in brush).
  - Both modes, per head: `RAPID_MODE T=n` (send return address `0x4b842c`).
  - Then `PARK_CURRENT_TOOL`. If `knife_pairing_failed` is set, `quick_stop()` is
    called and the final `SAVE_CONFIG` is skipped.
- `SAVE_CONFIG` (`0x4b8698`) is sent only when bed level, vibration or PID was
  selected. An offsets-only run sends none; offsets are stored by the macros.
- Head count is `current_thr_number` (`0x385c260`, default 4).
- Existing preload hooks: `unified_maintenance_event` (`bootstrap.cpp:286`),
  `unified_command_sender` (`bootstrap.cpp:270`), calibration admission and
  `SESSION/REQUEST/SEQUENCE/TICKET` wrapping (`runtime.hpp:238-277`), backend
  `CalibrationCommands` allowlist (`klipper_extras/wmp_recovery.py:1388`).
- Case light: GPIO76 through sysfs, on or off only, policy owned by
  `klipper_extras/wmp_case_light.py`. No dimming.

## User flow

Steps shown on the left, built from the head count:

    1. Prepare
    2. Head 1
    3. Head 2
    4. Head 3
    5. Head 4
    6. Calibrate

Completed steps are grey, the current step is orange, later steps are white
(`stage_color` in `model.hpp`).

### 1. Prepare

Shown when START is pressed with the offset row ticked in Accurate mode. Nothing
has been sent to the printer yet.

- Heading: "How will the nozzles be cleaned?"
- Radio option, selected by default: "Wire brush" / "Scrub each heated nozzle by
  hand. Have a wire brush ready."
- Radio option: "Printed blob" / "Every head must be loaded with filament."
- Actions: CANCEL, CONFIRM.

Outcomes:

- CANCEL: return to the Maintenance page with the ticked items unchanged.
- CONFIRM with Printed blob: start the stock run unchanged in Accurate mode.
- CONFIRM with Wire brush: start the stock run; the scrub stage replaces the
  stock clean loop when the worker reaches the offset stage.

### Other selected checks

Bed level, vibration and PID run as stock, on the stock progress page, before the
offset stage. The scrub happens after them so PID heating cannot foul nozzles that
were already cleaned.

### Return prompt (combined runs only)

When the worker reaches the offset stage after other checks, nothing is heated
until the user confirms they are back.

- Step highlighted: 2. Head 1.
- Text: "Ready to clean the nozzles." / "Press Confirm to start."
- Actions: CANCEL, CONFIRM. Case light blinks.

On an offsets-only run this prompt is skipped.

### 2–5. Each head

Right-hand pane, in order:

| State | Text | Actions |
|---|---|---|
| Mounting | "Mounting head N..." | CANCEL, CONFIRM disabled |
| Heating | "Heating head N..." and "127 / 160 °C" in large digits | CANCEL, CONFIRM disabled |
| Scrub | "Scrub the nozzle on head N" / "Brush the nozzle tip until it is clean, then press Confirm." / "The nozzle is hot." | CANCEL, CONFIRM |
| Cooled | "Head N has cooled." / "Press Confirm to reheat." | CANCEL, CONFIRM |

Behaviour:

- Target temperature is 160 °C, the stock wipe temperature and below the 175 °C
  minimum extrusion temperature.
- Head 1 starts heating when the scrub stage starts, while it is being mounted.
- When head N reaches the scrub position, head N+1 starts heating in its dock.
- Scrub position: X150 Y2, nozzle raised above the bed for brush access. Y2 is the
  existing front-panel clearance (`offset_calibrate.cfg` POP). The height is a
  configurable value, default 100 mm, to be confirmed on the printer.
- CONFIRM on Scrub: head N heater off, head N+1 is mounted. After the last head,
  go to Calibrate.
- If CONFIRM is not pressed within 10 minutes of the Scrub state starting, all
  heaters the flow turned on are switched off and the Cooled state is shown.
  CONFIRM reheats the mounted head and returns to Heating.
- `[idle_timeout]` is 600 s and zeroes extruder targets. A heater target cleared
  from outside the flow is treated the same way: the Cooled state is shown.
- Case light blinks during Scrub and Cooled.

### 6. Calibrate

No actions. The right-hand pane reports progress per head:

| State | Text |
|---|---|
| Homing | "Homing..." |
| Mounting | "Head N of 4" / "Mounting head N..." |
| Measuring position | "Head N of 4" / "Measuring nozzle position..." |
| Measuring height | "Head N of 4" / "Measuring nozzle height..." |
| Finishing | "Returning head N to its dock..." |

"Keep the door closed." is shown below the progress text throughout.

Sources of progress:

- Which head is being measured: the vendor worker sends `RAPID_MODE T=n` per head
  through the wrapped calibration sender, so the backend knows the head at each
  send. The client also exposes it as `calibrate_tool` (5-8 while measuring head
  1-4, 9 when complete).
- Phase within a head: `RAPID_MODE`, `CALIBRATE_TOOL_OFFSET` and
  `CALIBRATE_TOOL_Z_OFFSET` in `config/live/offset_calibrate.cfg` are repository
  macros and publish the current phase to backend status. If a phase cannot be
  published reliably, the head-level text "Measuring head N of 4..." is shown
  instead.

When the worker finishes, the existing calibration result screen
(`stock_calibration_status.hpp`) is shown.

### Cancel during the head steps

- Text: "Cancelling..." / "Cooling and returning head N to its dock. Offsets are
  unchanged."
- All heaters the flow turned on are switched off, the mounted head is docked,
  and the run ends without measuring offsets.
- Earlier results from the same run are kept (see "Earlier results").

### Failure during the head steps

On a mount, heating or move failure the flow stops, heaters the flow turned on are
switched off, and the screen states what failed in one sentence with a BACK
action. No retry, re-home or further motion is attempted. The run ends without
measuring offsets.

Earlier results from the same run are kept (see "Earlier results").

The unattended timeout is not a failure; it leads to the Cooled state.

### Earlier results

Rule: an offset stage that fails or is cancelled never discards bed level,
vibration or PID results completed earlier in the same run.

Stock behaviour: the worker sends one `SAVE_CONFIG` in its final stage and skips
it when the offset stage failed, and the existing backend failure latch
(`CalibrationCommands.cmd_run` and `_check` in `wmp_recovery.py`) refuses
`SAVE_CONFIG` for a failed attempt. `SAVE_CONFIG` restarts Klipper, so it cannot
run between items.

Required behaviour: when the offset stage ends by scrub cancel, scrub failure or
probing (`RAPID_MODE`) failure, and bed level, vibration or PID was selected in
the run, heaters are switched off and then the earlier results are saved once.
The offset stage is always last, so every pending value at that point comes from
a completed item. Stored offsets are written per head by the probing macros and
are not affected by this save. A coupling fault flag (`fail_flag`) is kept in
saved variables and must still be set after the restart.

The result screen distinguishes the outcome, for example "Offset calibration
stopped. Earlier results were saved."

Failures in bed level, vibration or PID keep their existing behaviour. Extending
the rule to every item is separate follow-up work.

## Design

### Native screen

A new screen component in `client-preload/unified-ui/native/` with:

- title "Nozzle offset calibration" at top left, actions right-aligned in the top
  bar (CANCEL then CONFIRM, uppercase, rightmost is primary), 1 px rule below,
  following `docs/ui/native-readiness.md:132-151`;
- a left column (about 230 px of 800) with the numbered step list;
- a right pane with the instruction text, radio options and temperature.

No existing screen has this split. The step list with all steps visible exists
only in ACE adoption (`stock_ace_filaments.hpp:541-549`); the header action helper
there (`header_action`) and the layout of `stock_calibration_status.hpp` are the
closest patterns.

The screen is a projection of backend state. Mount, heat, position and cool-down
phases, temperatures and failure text come from polled status, as in
`stock_filament_procedure.hpp`.

### Start hook

In `unified_maintenance_event`, on START, after the existing admission checks pass:
if `auto_check_selected[3] == 1` and `is_rapid_mode == 0`, show Prepare instead of
delegating. On CONFIRM, delegate the original START event to the stock handler
without re-entering `auto_check_prepare_page` (its setup zeroes the selection
bytes). For Wire brush, first set `is_rapid_mode = 1` and mark the scrub as
pending for this calibration attempt.

`is_rapid_mode` does not need restoring: the stock chooser rewrites it every time
the offset row is ticked, and nothing else reads it.

### Scrub stage hook

The scrub stage runs on the vendor worker thread at the offset-stage `G28` send
(return address `0x4b7fbc`), after forwarding `G28` and before returning to the
worker, which then reads `is_rapid_mode` and proceeds to the `RAPID_MODE` loop.
The worker is held in the hook until the scrub stage completes, in the same way
the stock flow holds it on popup `0x59`.

### Backend

A new backend command set drives the scrub stage, modelled on the probe editor
(`ProbeEditorCommands`, `wmp_recovery.py:750`): explicit start, per-head confirm,
reheat, and stop, each bound to the session and request of the active calibration
attempt.

- The scrub runs inside an active stock calibration attempt. It must be admitted
  under that attempt's session, request and sequence rather than as an independent
  maintenance operation, and must not break the ordered `SEQUENCE` of the vendor
  worker's wrapped commands.
- Heaters the scrub turns on are recorded with the attempt's heater ownership so
  the existing failure path cools them.
- Mounting uses the calibration tool-change path (`_WMP_CALIBRATION_TOOL`).
  Heating uses `SET_HEATER_TEMPERATURE` on physical heater names, not `M104/M109`.
  Moves use absolute coordinates with G-code offsets zeroed.
- It publishes status for the screen: current head, phase, temperatures, timeout
  state, failure text.
- New commands are added to `native/backend_contract.json`.

### Case light

`wmp_case_light` gains an attention signal. While requested, the light is toggled
away from its resting state in a repeating pattern:

    opposite 0.5 s, resting 0.5 s, opposite 0.5 s, resting 1.0 s, repeat

The resting state is whatever the normal light policy gives at that moment, so a
light that is on blinks off and a light that is off blinks on. The saved on/off
preference is not changed, and the light returns to its normal policy when the
signal is released.

The scrub backend requests the signal for the return prompt, Scrub and Cooled
states and releases it on confirm, cancel, failure, and Klipper restart.

The signal has its own saved setting, enabled by default, stored alongside the
existing case-light preference and changed with a G-code command. When disabled,
requests are ignored. It is not exposed on the touchscreen in this work.

## Constraints

- The touchscreen is 800 × 480 on a 5 inch diagonal. Text must be readable and
  controls usable by touch at that size: touch targets of about 9 mm (64 px) or
  more, and no instruction text below about 3 mm (22 px).
- Vendor code is not patched; behaviour is changed only through existing hook
  points and writes to `is_rapid_mode`.
- All addresses are specific to the 1.1.13 client and belong in the firmware
  profile. On an unrecognised client the flow is not offered and stock behaviour
  is unchanged.
- Native source changes require the screen package to be rebuilt and resealed
  (`docs/native-screen-packaging.md`).
- Documentation follows the repository's plain technical style.

## Testing

- Native: screen lifecycle and layout in `tests/unified_ui/native_lifecycle.cpp`;
  flow state machine as a compiled unit test in the style of
  `tests/test_probe_editor_flow.py`.
- Backend: admission, sequencing, heater ownership, timeout, cancel and failure
  paths, saving of earlier results after each way the offset stage can stop, alongside `tests/test_calibration_*.py`.
- Macros: any new macro covered in `tests/test_config_macros.py`.
- Case light: signal pattern from both resting states, the saved setting, and
  restoration, in the `wmp_case_light` tests.
- Hook behaviour against the vendor worker where the existing ARM emulation tests
  (`tests/test_stock_calibration_worker.py`) can cover it.
- On the printer: offsets-only run, combined run with PID, cancel at each state,
  timeout and reheat, Printed blob hand-off, and confirmation of the scrub height.

## Left to the builder

- How the offset stage is ended early and the earlier results saved. The vendor
  worker's own failure path (`knife_pairing_failed`) calls `quick_stop()` and
  skips its `SAVE_CONFIG`, and the backend latch refuses the save. The required
  outcome is in "Earlier results": no emergency stop on cancel, earlier results
  saved once. The mechanism, and the exception to the backend latch, need
  investigation and a safety review of saving after a coupling fault.
- What the existing result screen shows after an offsets-only run, given that no
  client `SAVE_CONFIG` is sent, and any adjustment needed so it reports success.
- Whether the stock progress page needs hiding while the native screen is up, and
  how the native Calibrate state tracks worker completion.
- Exact widget geometry, fonts and touch-target sizes.
- Structure of the backend status object and command names, and how the
  calibration macros publish their phase.

## Decisions made without explicit user direction

- Wording of every screen beyond the user's outline, including "Keep the door
  closed."
- No Cancel during the Calibrate step.
- Return prompt before heating on combined runs.
- 10 minute unattended timeout and the Cooled/reheat state.
- Scrub position X150 Y2 and default height 100 mm.
- Failure handling: stop, cool, report, no retry.
- Result-screen wording for a stopped offset stage.
