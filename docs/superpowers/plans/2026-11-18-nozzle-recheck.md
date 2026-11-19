# Nozzle Re-check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After the offset measurement of a wire-brush run, flag heads whose repeat touches disagree and let the user clean those heads and measure again, save anyway, or cancel with the old offsets restored.

**Architecture:** A backend module reads the vendor probe's touch lines from the G-code output stream and publishes per-head flags; the backend also snapshots the stored offsets per attempt and restores them on request. The native scrub flow gains a `Recheck` state entered while the vendor worker is held at its final park send; it reuses the scrub's head states for flagged heads and sends the re-measurement commands itself.

**Tech Stack:** Klipper extras (Python 3), C++11 LVGL screens called by address (`client-preload/unified-ui/native`), pytest, host g++ tests, Unicorn emulation of the vendor worker.

**Spec:** `docs/superpowers/specs/2026-11-18-nozzle-recheck-design.md`. As-built reference for the code this extends: `docs/nozzle-scrub.md`. Conventions: `docs/development.md`.

## Global Constraints

- Branch `feature/brush-nozzle-scrub-r4`. No vendor file is edited (`tools_calibrate_core.py`, `tools_calibrate.py`); probing macro motion is unchanged.
- A flagged head never fails the calibration attempt. No lines from the probe means no flag.
- The failure latch, `fail_flag` handling and the early-save rule are not changed.
- C++11, `-Wall -Wextra -Werror`; no timed wait other than `wait_until` on `std::chrono::system_clock` (glibc floor 2.17).
- Touch targets at least 64 x 110 px, 8 px apart; instruction text at least 22 px; screen texts exactly as in the spec.
- New backend modules are registered in `tools/components/material.py` `HELPERS` and `client-preload/unified-ui/native/runtime_inputs.py` `RUNTIME_INPUTS`; new commands and status protocols in `client-preload/unified-ui/native/backend_contract.json`.
- Documentation states facts only: no change history, no commentary.
- Test command (never with a trailing `.`): `uv run --with pytest --with jinja2 --with unicorn --with capstone python -m pytest -q -p no:cacheprovider <files>`; full suite: `tests klipper_extras --ignore=tests/test_moonraker_http_error_patch.py`.
- Nothing is run against the printer.

## Review Focus

- A printer whose probe output has another format or language: the parser must ignore it and the run must complete as today.
- A `Probe samples exceed tolerance. Retrying...` line inside a group: touches before and after it belong to the same group.
- Status going stale while the worker is held at the park send on the Re-check screen: the existing 120 s stale rule must release the worker and no offsets may be restored or re-measured.
- Klipper restart during a re-clean or re-measurement: the flow stops as it does during the first scrub; the snapshot is gone and nothing is restored.
- Cancel pressed while a flow-sent `RAPID_MODE` is running: the restore must not be sent until that command has finished.

---

### Task 1: Touch-spread detection (backend)

**Files:**
- Create: `klipper_extras/wmp_nozzle_touch.py`, `tests/test_nozzle_touch.py`, `tests/fixtures/toolsetter_clean.log`, `tests/fixtures/toolsetter_residue.log`
- Modify: `klipper_extras/wmp_calibration.py` (compose), `klipper_extras/wmp_calibration_progress.py` (notify on phase change), `klipper_extras/wmp_recovery.py` (config pass, status key), `tools/components/material.py`, `client-preload/unified-ui/native/runtime_inputs.py`, `client-preload/unified-ui/native/backend_contract.json`, `config/README.md`

**Superseded:** the detection rule, status fields, option, fixtures and tests of this task are replaced by the centre rule in the spec (`docs/superpowers/specs/2026-11-18-nozzle-recheck-design.md`, "Detection (backend)": protocol 2, `centres`, `centre_span`, `offset_centre_spread` 0.030 mm). The interface line and steps below describe the replaced per-group rule.

**Interfaces:**
- Produces: `NozzleTouch(calibration, config)` with `observe(line: str)`, `phase_changed(head: int, phase: str)`, `reset(request: str)`, `flagged() -> list[int]`, `get_status() -> {'protocol': 1, 'request': str, 'heads': [{'head', 'groups', 'spread_max', 'over', 'flagged'}], 'flagged': [int]}`; `CalibrationCommands.nozzle_touch`; status `wmp_recovery.nozzle_touch`; option `offset_touch_spread` in `[wmp_recovery]` (float, default 0.0094, minval 0, 0 disables).
- Consumes: `CalibrationProgress.head/phase/request`; `gcode.register_output_handler`.

- [ ] **Step 1: Create the fixtures.** Copy from `/home/anselor/source/Wondermaker_plus/.claude/worktrees/loadcell-adc-race/analysis/toolsetter-baseline-2026-11-17/baseline4.log` (clean) and `baseline3.log` (residue) only the lines containing `dir:`, `Probe made contact`, `Retrying` or `Calibrated XY`, keeping the `// ` text after the timestamp and `response` prefix. Read the sources with `python3 -I`; do not modify that directory.

- [ ] **Step 2: Write the failing tests** in `tests/test_nozzle_touch.py`. Each replays a fixture through `observe`, calling `phase_changed(head, 'mounting')` then `phase_changed(head, 'position')` before each head's 24 groups (a head's groups end at its sixth `Calibrated XY`) and `phase_changed(head, 'height')` after.

```python
def test_clean_run_flags_no_head():       # flagged() == []; every head: groups == 24, over == 0, spread_max == pytest.approx(0.00625)
def test_residue_run_flags_every_head():  # flagged() == [0, 1, 2, 3]; over == [6, 7, 3, 1]; head 0 spread_max == pytest.approx(2.34375)
def test_touches_before_a_retry_count():  # group: 301.0, 301.5, Retrying, 301.5, 301.5 -> spread 0.5
def test_groups_are_not_pooled_across_passes_or_samples():  # two groups 0.1 mm apart, each spread 0 -> not flagged
def test_single_touch_group_is_not_judged()
def test_lines_outside_position_phase_are_ignored()         # same lines in phase 'height' -> groups == 0
def test_remeasuring_a_head_discards_its_earlier_groups()   # flagged head, phase_changed(head,'mounting'), clean groups -> not flagged
def test_unrecognised_output_is_ignored()                   # arbitrary text, non-ASCII text, malformed numbers -> no error, no groups
def test_limit_zero_disables()                              # offset_touch_spread=0 -> flagged() == []
def test_reset_names_the_request_and_clears_heads()
def test_spread_exactly_three_steps_is_not_flagged()        # 0.009375 passes; 0.0125 is flagged
```

- [ ] **Step 3: Run** `tests/test_nozzle_touch.py`. Expected: FAIL (module missing).

- [ ] **Step 4: Implement `wmp_nozzle_touch.py`.** Group opens on `// x: <f>, y: <f>, dir: <x+|x-|y+|y->`; a touch is `// Probe made contact at <f>, <f>, <f>` (X for `x±`, Y for `y±`); a group closes on the next group line or `// Calibrated XY:`. Attribute to `progress.head` while `progress.phase == 'position'` and `calibration.active`. A comparison tolerance of 1e-9 mm is applied to the limit. The output handler must never raise.

- [ ] **Step 5: Compose and register.** `CalibrationCommands.__init__`: `self.nozzle_touch = NozzleTouch(self, config)`; `cmd_run` resets it with the attempt where it resets `progress`; `CalibrationProgress.cmd_phase` calls `calibration.nozzle_touch.phase_changed(head, phase)` when it accepts a phase. Add the status key, `HELPERS`, `RUNTIME_INPUTS`, contract protocol `nozzle_touch` 1, and the option row in `config/README.md`.

- [ ] **Step 6: Run** `tests/test_nozzle_touch.py tests/test_calibration_progress.py tests/test_preload_backend_acceptance.py tests/test_nozzle_scrub_commands.py`. Expected: PASS.

- [ ] **Step 7: Commit** `Detect disagreeing repeat touches per head during offset measurement`.

### Task 2: Offset snapshot, restore and measurement tracking (backend)

**Files:**
- Create: `klipper_extras/wmp_offset_snapshot.py`, `tests/test_offset_snapshot.py`
- Modify: `klipper_extras/wmp_calibration.py` (allowlist, compose, snapshot at admission), `klipper_extras/wmp_calibration_progress.py`, `klipper_extras/wmp_nozzle_touch.py` (status), `tools/components/material.py`, `runtime_inputs.py`, `backend_contract.json`, `tests/test_calibration_progress.py`

**Interfaces:**
- Produces: command `_WMP_OFFSETS_RESTORE` (in `CalibrationCommands.COMMAND`); `OffsetSnapshot(calibration)` with `take(request)`, `restore() -> bool`, `state` in `('none', 'done', 'failed')`; `nozzle_touch` status gains `'restore': state`; `calibration_progress` status gains `'measured': [int]` (heads whose `RAPID_MODE` completed for this request, ascending) and `'measuring': bool` (a `RAPID_MODE` of this request is executing).
- Consumes: `save_variables.allVariables['t0_offset'..'t3_offset']`; `gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=tN_offset VALUE=x,y,z')`.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_offset_snapshot.py
def test_snapshot_taken_once_when_the_attempt_is_admitted()    # later SAVE_VARIABLE changes do not alter it
def test_restore_writes_all_four_heads_and_reports_done()      # four SAVE_VARIABLE scripts with the snapshot values; state == 'done'
def test_restore_failure_reports_failed_and_does_not_raise()   # run_script raises on head 2 -> state 'failed', cmd_run returns, runner.failure == ''
def test_restore_without_a_snapshot_reports_failed()           # variable missing at admission
def test_restore_refused_outside_the_current_attempt()         # unbound call and superseded attempt raise; nothing written
def test_scrub_end_is_admitted_after_a_failed_restore()        # _WMP_SCRUB_END runs after state 'failed'
def test_new_attempt_clears_the_restore_state()
# tests/test_calibration_progress.py
def test_measured_lists_heads_whose_rapid_mode_completed()     # RAPID_MODE T=0, T=2 -> [0, 2]; a RAPID_MODE that raises is not listed
def test_remeasuring_a_head_removes_it_until_it_completes()
def test_measuring_is_true_only_while_a_rapid_mode_runs()
```

- [ ] **Step 2: Run** both files. Expected: FAIL.

- [ ] **Step 3: Implement.** `take` at the point where `cmd_run` resets `progress` for a new attempt. `cmd_run` notifies `progress` before and after a `RAPID_MODE T=n` command (`measuring`, then `measured` on success). `_WMP_OFFSETS_RESTORE` is registered by `OffsetSnapshot`, catches every exception from the writes, logs it and sets `failed`.

- [ ] **Step 4: Run** both files plus `tests/test_calibration_commands.py tests/test_calibration_early_save.py tests/test_preload_backend_acceptance.py`. Expected: PASS.

- [ ] **Step 5: Commit** `Record stored offsets per attempt, restore them on request and track measured heads`.

### Task 3: Status projection (native)

**Files:**
- Modify: `client-preload/unified-ui/native/nozzle_scrub_status.hpp`, `projection.hpp`, `tests/unified_ui/projection.cpp`

**Interfaces:**
- Produces: `out["nozzle_touch"]` = `{protocol:1, request, flagged:[0..3 ascending, unique], restore}` or `Json::object()` when invalid; `out["calibration_progress"]` additionally carries `measured` (validated like `flagged`) and `measuring` (bool).
- Consumes: Task 1 and 2 status.

- [ ] **Step 1: Write failing cases** in `tests/unified_ui/projection.cpp`: valid status projected; `flagged` with a head above 3, a duplicate, a non-integer or more than four entries gives an empty object; unknown `restore` value gives an empty object; a backend without `measured`/`measuring` projects progress as today.
- [ ] **Step 2: Run** `tests/test_unified_ui.py -k projection`. Expected: FAIL.
- [ ] **Step 3: Implement** `nozzle_touch_status(const Json&)` and extend `calibration_progress_status`.
- [ ] **Step 4: Run** the same. Expected: PASS.
- [ ] **Step 5: Commit** `Project nozzle touch flags and measured heads`.

### Task 4: Re-check in the flow and its screen text (native, pure)

**Files:**
- Modify: `client-preload/unified-ui/native/nozzle_scrub_flow.hpp`, `nozzle_scrub_view.hpp`, `tests/unified_ui/nozzle_scrub_flow.cpp`, `tests/fixtures/progress_panel_views.json`

**Interfaces:**
- Produces:
  - `ScrubState::Recheck`, `ScrubState::Remeasure`; `enum class ScrubChoice { Clean, Save }`.
  - `void NozzleScrubFlow::park_reached(double now)`: the worker is at its park send. Enters `Recheck` when the run is a brush run in `Calibrate`, status is fresh and `nozzle_touch` for this request lists flagged heads; otherwise leaves the state and `hold()` false.
  - `void select_recheck(ScrubChoice)`; `confirm(now)` in `Recheck` acts on the selection; `cancel(now)` in `Recheck`, `Remeasure` or a repeat head state queues `_WMP_OFFSETS_RESTORE` (once no `RAPID_MODE` is running) then takes the existing cancel path.
  - Clean: head states run over `flagged` only (`ScrubFacts::head` is the physical head; `ScrubFacts::revisit` is the list); then `Remeasure` queues `RAPID_MODE T=n` one at a time, the next when `calibration_progress.measured` contains the previous and `measuring` is false; heads to measure are all heads when head 0 was flagged, else the flagged heads; then `park_reached` logic is evaluated again.
  - `ScrubFacts` gains `std::vector<unsigned> flagged`, `ScrubChoice choice`, `bool restored_requested`, `bool saved_anyway`.
  - `ScrubOutcome` after Save: `Proceed`; after Cancel: `Skip`.
  - View: `Recheck` heading "Head 2 may not be clean" / "Heads 2 and 4 may not be clean" (list form "Heads 1, 2 and 4"); instruction "Its measurement did not repeat, which usually means residue on the nozzle." / "Their measurements did not repeat, which usually means residue on the nozzle."; option texts "Clean again" / "Scrub the flagged heads, then measure again." and "Save anyway" / "Keep the offsets as measured."; CANCEL and CONFIRM visible; flagged heads' steps `failed`, Calibrate `running`, others `complete`. `Remeasure` uses the Calibrate texts. Attention is requested in `Recheck`.
  - `nozzle_scrub_panel_view`: `decisions` and `choices_height` also in `Recheck`. `ScrubView` gains `option_title[2]`, `option_detail[2]`, `first_selected`.
- Consumes: Task 3 projection.

- [ ] **Step 1: Write failing tests** in `tests/unified_ui/nozzle_scrub_flow.cpp`:

```
recheck_entered_only_with_flags_fresh_status_and_brush_run   // no flags, stale status, other request, blob run -> not held
recheck_save_releases_with_proceed
recheck_cancel_restores_then_ends_and_skips                  // queue: _WMP_OFFSETS_RESTORE, _WMP_SCRUB_END; outcome Skip
recheck_clean_visits_only_flagged_heads                      // flagged {1,3}: HEAD T=1 ... HEAD T=3; no T=0, T=2
recheck_head_one_flagged_remeasures_every_head               // RAPID_MODE T=0..3 in order
recheck_other_head_flagged_remeasures_only_it
remeasure_sends_next_only_after_measured_and_idle
recheck_repeats_when_a_head_is_flagged_again
cancel_during_remeasure_waits_for_the_running_command_then_restores
cancel_during_repeat_scrub_cools_docks_and_restores
stale_status_in_recheck_releases_after_the_limit_without_restore
restart_during_repeat_stops_without_restore
recheck_view_texts_for_one_two_and_four_heads
recheck_requests_attention_and_releases_it_on_each_choice
```

- [ ] **Step 2: Run** `tests/test_nozzle_scrub_flow.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the states, the head list and the view texts.
- [ ] **Step 4: Add the fit case** `scrub-state-11` to `tests/fixtures/progress_panel_views.json` (800 x 480, `scrub_options: true`, heading "Heads 1, 2, 3 and 4 may not be clean", plural instruction, `decisions: true`, `choices_height: 216`, steps `c f f f f r`, `steps_width: 200`, `title_width: 540`). If `progress_ui_contract.hpp` hard-codes the Prepare option texts, parametrise them from the scenario (`option_texts`), keeping the existing cases' output unchanged.
- [ ] **Step 5: Run** `tests/test_nozzle_scrub_flow.py tests/test_unified_ui.py -k "font_fit or lifetimes"`. Expected: PASS, the new case fits.
- [ ] **Step 6: Commit** `Add the re-check and re-measure states to the nozzle scrub flow`.

### Task 5: Re-check on the screen (native)

**Files:**
- Modify: `client-preload/unified-ui/native/stock_nozzle_scrub.hpp`, `tests/unified_ui/nozzle_scrub_lifecycle.hpp`

**Interfaces:**
- Consumes: `ScrubView` option fields from Task 4.
- Produces: option rows shown in `Prepare` and `Recheck` with the view's texts; `on_select(bool first)` reports the first or second row; no widget is created after `created()`.

- [ ] **Step 1: Write failing cases:** `nozzle_scrub_recheck_layout` (texts, selection mark follows the view, CANCEL/CONFIRM present, BACK absent, flagged step colour `0xffff6666`), `nozzle_scrub_recheck_touch_targets` (four targets, sizes and spacing as on Prepare), extend `nozzle_scrub_update_is_idempotent` with Prepare → Recheck → Prepare (node count unchanged, row texts follow).
- [ ] **Step 2: Run** `tests/test_unified_ui.py -k lifetimes`. Expected: FAIL.
- [ ] **Step 3: Implement** (row labels rewritten through `StockOptionRow::label` when the view's texts change).
- [ ] **Step 4: Run** the same. Expected: PASS.
- [ ] **Step 5: Commit** `Show the re-check choices on the nozzle scrub screen`.

### Task 6: Hold at the park send (native coordinator)

**Files:**
- Modify: `client-preload/unified-ui/native/nozzle_scrub_coordinator.hpp`, `runtime.hpp` (wiring only), `tests/unified_ui/nozzle_scrub_lifecycle.hpp`, `tests/test_stock_calibration_worker.py`, `client-preload/unified-ui/native/make_profile.py` only if a new address is needed

**Interfaces:**
- Consumes: `flow.park_reached`, `flow.hold()`, `flow.next_command`, existing `send` callback and hold loop.
- Produces: in `withhold_offset_send` for the park caller: `park_reached`, then the hold loop (commands sent on the worker thread through the binding), and only after the hold ends the existing failed-byte wait, withhold and early-save decisions. `result_*_locked()` accessors for Task 7: `flagged_heads`, `saved_anyway`, `cancelled`, `restore_failed`, kept for the result request as `result_heads_` is.

- [ ] **Step 1: Write failing lifecycle cases:**

```
park_send_holds_worker_while_recheck_is_shown
save_anyway_forwards_the_park_and_the_save
clean_again_sends_scrub_and_rapid_commands_in_sequence_then_parks   // sequence numbers continue the attempt's
recheck_cancel_sends_restore_and_end_then_withholds_the_park
no_flags_no_hold                                                     // park forwarded at once, as today
stale_status_at_park_does_not_hold
backend_without_nozzle_touch_does_not_hold
recheck_released_when_runtime_stops_or_screen_is_torn_down
failed_byte_decision_is_made_after_the_hold                          // byte set during a re-measure failure -> existing early-save path
```

- [ ] **Step 2: Write the failing emulation case** in `tests/test_stock_calibration_worker.py`: `test_worker_held_inside_the_park_send_then_parks_and_saves` (hook blocks at `0x4b847c`'s send, extra sends are made, the worker then reaches `SAVE_CONFIG` with status 14).
- [ ] **Step 3: Run** `tests/test_unified_ui.py -k lifetimes tests/test_stock_calibration_worker.py`. Expected: FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run** the same, then under ThreadSanitizer the lifecycle binary as `docs/nozzle-scrub.md` describes for the scrub cases. Expected: PASS, no report in scrub cases.
- [ ] **Step 6: Commit** `Hold the calibration worker at its park send for the nozzle re-check`.

### Task 7: Result page

**Files:**
- Modify: `client-preload/unified-ui/native/stock_calibration_status.hpp`, `runtime.hpp` (`update_stock_calibration` data), `tests/unified_ui/nozzle_scrub_lifecycle.hpp`

**Interfaces:**
- Consumes: Task 6 accessors as `data["maintenance_flagged_heads"]` (array), `["maintenance_saved_anyway"]`, `["maintenance_recheck_cancelled"]`, `["maintenance_restore_failed"]`; `calibration_progress.measured`.
- Produces texts:
  - Save anyway: "Nozzle offsets saved. Head 2 may not be clean." / "Calibration settings saved. Heads 2 and 4 may not be clean."
  - Cancel: "Offset calibration cancelled. Offsets are unchanged."; combined run after a confirmed save: "Offset calibration cancelled. Earlier results were saved."
  - Restore failed: "Offsets could not be restored. Run the calibration again." (combined run after a confirmed save: preceded by "Earlier results were saved.").
  - "Nozzle offsets saved." condition: brush run, attempt offsets `measured` and pending, `measured` contains every head of the run, progress phase `docking`, worker returned.

- [ ] **Step 1: Write failing cases:** one per text above for offsets-only and combined runs; `offsets_saved_after_partial_remeasure` (last probed head is not the last head); `cancelled_text_survives_the_restart` (attempt status gone, native facts kept); existing result cases unchanged.
- [ ] **Step 2: Run** `tests/test_unified_ui.py -k lifetimes`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same. Expected: PASS.
- [ ] **Step 5: Commit** `Report the re-check outcome on the calibration result page`.

### Task 8: Documentation and package

**Files:**
- Modify: `docs/nozzle-scrub.md`, `config/README.md`, `client-preload/unified-screen1113/*`

- [ ] **Step 1: Document** in `docs/nozzle-scrub.md`: the Re-check screen and its three outcomes, detection (what is compared, the limit, its measured basis and limits), the snapshot and restore, new commands and status, new result texts, and the additions to "Not yet verified on the printer" (console line format reaching the handler, the limit on other printers and warm nozzles, the hold at the park send, restore on hardware).
- [ ] **Step 2: Run the full suite.** Expected: no failures.
- [ ] **Step 3: Rebuild the package** from a `git archive` export of the committed tree with the unmodified `client-preload/unified-ui/native/build-arm.sh`, package with `tools/package_unified_ui_delivery.py` (no `--reviewed-release`), copy the five files, `python3 tools/reseal_screen_package.py --check` → `Screen package is current.` Build a second export and confirm the same `screen.so` SHA-256.
- [ ] **Step 4: Run** `tests/test_screen_package_current.py`. Expected: PASS.
- [ ] **Step 5: Commit** documentation and package separately.
