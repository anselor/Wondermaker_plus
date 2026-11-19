# Guided Nozzle Scrub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blob-printing clean in the stock Accurate offset calibration with a guided wire-brush scrub, then run the stock rapid probing.

**Architecture:** The preload intercepts Maintenance START when Accurate is selected and shows a native two-column screen. Choosing Wire brush sets the vendor mode byte to rapid; when the vendor worker reaches its offset stage the preload holds that worker thread and sends scrub commands through the existing sequenced calibration wrapper, so the scrub is part of the same backend attempt. The backend gains scrub commands, progress status and a case-light attention signal.

**Tech Stack:** C++11 LVGL preload (`client-preload/unified-ui/native/`), Klipper Python extras (`klipper_extras/`), Klipper macros (`config/live/`), pytest with g++ compiled native tests and Unicorn ARM emulation.

**Spec:** `docs/superpowers/specs/2026-11-15-guided-nozzle-scrub-design.md`

## Global Constraints

- Vendor code is not patched. Only existing hook points and writes to vendor data bytes are used.
- All vendor addresses are for the 1.1.13 client (SHA-256 prefix `b60c96c5`) and are declared in `client-preload/unified-ui/native/profile1113.json`. On any other client the flow is not offered.
- Scrub temperature 160 °C. Scrub position X150 Y2. Scrub height default 100 mm, configurable. Unattended timeout 600 s.
- No automatic retry, re-home or motion after a mount, heating or move failure.
- Screen text is exactly the text in the spec's "User flow" section. No internal state, addresses or identifiers on screen.
- The screen is 800 × 480 on a 5 inch diagonal, about 7.3 px per mm, used by touch at arm's length. Every touch target is at least 64 px high and 110 px wide (about 9 mm), counting any invisible hit area around the visible control, with at least 8 px between adjacent targets. Instruction text is at least 22 px; secondary text is at least 18 px; no text is smaller. Where the client's fixed fonts (`0x26297a0` body, `0xf84928` caption) do not meet this, pick the nearest larger font the client already ships and record the choice in `docs/nozzle-scrub.md`.
- Heating uses `SET_HEATER_TEMPERATURE HEATER=extruder|extruder1|extruder2|extruder3`, never `M104`/`M109`.
- Every new backend command and status protocol is added to `client-preload/unified-ui/native/backend_contract.json`.
- Files and docs use plain technical statements. Commit messages follow the existing imperative style and end with the `Co-Authored-By` line.
- Test command prefix: `uv run --with pytest --with jinja2 --with unicorn --with capstone python -m pytest -q`.
- Vendor-binary tests read `analysis/` relative to the repository root and skip when it is absent. `analysis/` is gitignored and exists only in the main checkout; before Task 1 create the link `ln -s /home/anselor/source/Wondermaker_plus/analysis analysis` in this worktree and confirm `tests/test_stock_calibration_worker.py` runs rather than skips.
- Nothing is sent to the printer by any task except Task 10, which the user runs.

## Review Focus

1. Klipper restarts or the calibration session changes while the worker is held in the scrub: the worker is released, the offset sends are skipped, and the screen shows "Printer restarted. Calibration stopped." with BACK. Test in Task 5.
2. Heater target is cleared from outside the flow (idle timeout) during Heating, before the nozzle reaches temperature: the state becomes Cooled, not a permanent Heating. Test in Task 5.
3. CONFIRM is tapped twice in one state: exactly one command is queued. Test in Task 5.
4. Head count below four (`current_thr_number` 1 to 3): step list, head loop and "Head N of M" text use the real count. Tests in Tasks 5 and 6.
5. Printer status is stale when START is pressed or while Prepare is open: CONFIRM is disabled and nothing is delegated. Tests in Tasks 5 and 7.

## File Structure

| File | Responsibility |
|---|---|
| `klipper_extras/wmp_nozzle_scrub.py` (new) | Scrub commands, scrub status, calibration progress status |
| `klipper_extras/wmp_recovery.py` | Allowlist entries, construction of the scrub object, status keys, early-end save rule |
| `klipper_extras/wmp_case_light.py` | Attention signal and its saved setting |
| `config/live/offset_calibrate.cfg` | Progress phase calls inside the rapid macros |
| `client-preload/unified-ui/native/nozzle_scrub_flow.hpp` (new) | Pure state machine, no LVGL |
| `client-preload/unified-ui/native/stock_nozzle_scrub.hpp` (new) | Two-column LVGL screen |
| `client-preload/unified-ui/native/runtime.hpp`, `bootstrap.cpp`, `projection.hpp`, `profile1113.json` | Start hook, worker hold, status projection, addresses |
| `docs/nozzle-scrub.md` (new) | User-facing description and vendor findings |

---

### Task 1: Characterise how the vendor offset stage ends

Later tasks depend on how the worker behaves when offset-stage sends are withheld. This task produces evidence and a recorded decision, not product code.

**Files:**
- Modify: `tests/test_stock_calibration_worker.py`
- Create: `docs/nozzle-scrub.md` (section "Vendor worker findings")

**Interfaces:**
- Produces: a "Decision" paragraph in `docs/nozzle-scrub.md` naming one of mechanism A or B below. Tasks 7 and 8 implement the named mechanism.

Known from the spec and `docs/upstream-command-nonfilament-review.md:378-400`: `knife_pairing_failed` (`0xe64572d`) is set by `parse_gcode_response` (`0x63b828`) on a G-code error while `knife_pairing_ing` (`0xe64572c`) is 1. The wait helpers compare `idle_timeout_state` with `Printing` and `klipper_state` with `ready`. After the `RAPID_MODE` loop the worker sends `PARK_CURRENT_TOOL` (return `0x4b847c`), waits, checks the failed byte at `0x4b8498`, calls `quick_stop()` when set, and in stage 13 skips `SAVE_CONFIG` when set.

- [ ] **Step 1: Add characterisation cases** to `tests/test_stock_calibration_worker.py`, in the file's existing Unicorn style:

  - `test_offset_stage_with_withheld_sends_reaches_save`: with `is_rapid_mode=1`, `auto_check_selected=[1,0,0,1]`, failed byte 0 and the sender stub recording but not acting on sends from `0x4b842c` and `0x4b847c`, the worker reaches the `SAVE_CONFIG` send at `0x4b869c` and never calls `quick_stop`.
  - `test_failed_byte_cleared_at_park_send_avoids_quick_stop`: failed byte set to 1 before the park send and cleared inside the sender stub at return `0x4b847c`; assert `quick_stop` is not called and `SAVE_CONFIG` is sent.
  - `test_failed_byte_left_set_calls_quick_stop_and_skips_save`: baseline of stock behaviour.

- [ ] **Step 2: Run** `… tests/test_stock_calibration_worker.py`. Expected: the three new cases pass and document behaviour. If a case cannot be made to pass, that is a finding; keep the case as an `xfail` with the observed behaviour in its reason.

- [ ] **Step 3: Disassemble and record** in `docs/nozzle-scrub.md`: what `wait_tool_calibrate_sync` and `wait_sync` wait on when no command was sent; what `quick_stop` (callee at `0x4b850c`) sends or sets, and when `printer.quick_stop_flag` clears on the Klipper side (search `klipper_extras/`, `klipper_backport/`, `config/`, `docs/upstream-client-callers.md:1442,1729`).

- [ ] **Step 4: Record the decision.**
  - **Mechanism A (preferred):** after an abnormal scrub end or probing failure, the preload withholds sends from `0x4b842c` and `0x4b847c`, clears `knife_pairing_failed` inside the hook at `0x4b847c`, and the worker's own stage-13 `SAVE_CONFIG` carries the earlier results. Choose A when Steps 1 to 3 show the worker reaches the save without `quick_stop` and the wait helpers return without a send.
  - **Mechanism B:** the worker's failure path runs unchanged and the preload sends a separate bound save after the worker status reaches 14. Choose B only when A is not shown to work, and record what makes the save admissible after `quick_stop`.

- [ ] **Step 5: Commit** `tests/test_stock_calibration_worker.py docs/nozzle-scrub.md` with message "Characterise vendor offset stage end paths".

---

### Task 2: Backend scrub commands and status

**Files:**
- Create: `klipper_extras/wmp_nozzle_scrub.py`, `tests/test_nozzle_scrub_commands.py`
- Modify: `klipper_extras/wmp_recovery.py` (`CalibrationCommands.COMMAND` at ~1395, `__init__` at ~1402, `get_status` at ~68), `client-preload/unified-ui/native/backend_contract.json`

**Interfaces:**
- Consumes: `CalibrationCommands` (`printer`, `gcode`, `active`, `_heater_execution`), `_WMP_CALIBRATION_TOOL T=n` (`config/live/macros.cfg:494`), `_WMP_CALIBRATION_CLEARANCE` (`config/live/offset_calibrate.cfg:562`).
- Produces:
  - `class NozzleScrubCommands(calibration, config)` with `get_status() -> dict` and `get_progress() -> dict`.
  - G-code commands, valid only while `calibration.active` is true (they are reached through `_WMP_CALIBRATION_COMMAND`):
    - `_WMP_SCRUB_HEAD T=<0-3>`: require X, Y and Z homed; set heater T to `scrub_temp`; mount head T; raise to clearance; move to `scrub_x`, `scrub_y`, `scrub_z` in absolute coordinates with G-code offsets zeroed; wait for moves.
    - `_WMP_SCRUB_HEAT T=<0-3>`: set heater T to `scrub_temp`.
    - `_WMP_SCRUB_COOL` / `_WMP_SCRUB_COOL T=<0-3>`: set to 0 every heater this scrub heated, or only heater T.
    - `_WMP_SCRUB_END`: cool every heater this scrub heated, `PARK_CURRENT_TOOL`, release attention, phase `ended`.
    - `_WMP_SCRUB_ATTENTION VALUE=<0|1>`: request or release the case-light signal (Task 3) with owner `"nozzle_scrub"`; a missing `wmp_case_light` object, or one without `request_attention`, is not an error.
    - `_WMP_CALIBRATION_PHASE HEAD=<0-3> PHASE=<mounting|position|height|docking>`: set progress (used by Task 4).
  - Config options read from the existing `[wmp_recovery]` section: `scrub_x` (150), `scrub_y` (2), `scrub_z` (100, min 20, max 250), `scrub_temp` (160, max 170).
  - Status under `wmp_recovery`:
    - `nozzle_scrub`: `{'protocol': 1, 'head': -1..3, 'phase': 'idle'|'mounting'|'positioning'|'heating'|'ended'|'failed', 'target': 160.0, 'error': ''}`. `heating` means the head is at the scrub position.
    - `calibration_progress`: `{'protocol': 1, 'head': -1..3, 'phase': 'idle'|'homing'|'mounting'|'position'|'height'|'docking'}`. Reset to `idle` when a calibration attempt starts, fails or saves.
  - Allowlist additions to `CalibrationCommands.COMMAND`: `_WMP_SCRUB_HEAD T=[0-3]`, `_WMP_SCRUB_HEAT T=[0-3]`, `_WMP_SCRUB_COOL(?: T=[0-3])?`, `_WMP_SCRUB_END`, `_WMP_SCRUB_ATTENTION VALUE=[01]`.

- [ ] **Step 1: Write failing tests** in `tests/test_nozzle_scrub_commands.py`, using the fakes pattern of `tests/test_calibration_commands.py`:

  - `test_scrub_head_sequence`: `_WMP_SCRUB_HEAD T=1` through `_WMP_CALIBRATION_COMMAND` runs, in order, `SET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=160`, `_WMP_CALIBRATION_TOOL T=1`, a move ending at `X150 Y2 Z100`, `M400`; status ends `{'head': 1, 'phase': 'heating'}`.
  - `test_scrub_head_requires_homing`: with Z unhomed the command errors, no heater is set, phase is `failed` and `error` is non-empty.
  - `test_scrub_commands_refused_outside_calibration`: calling `_WMP_SCRUB_HEAD T=0` directly, not through the wrapper, raises and runs nothing.
  - `test_cool_targets_only_scrub_heaters`: after `_WMP_SCRUB_HEAT T=0` and `T=1`, `_WMP_SCRUB_COOL` zeroes extruder and extruder1 and does not touch extruder2.
  - `test_end_cools_parks_and_releases_attention`.
  - `test_mount_failure_latches_attempt_and_cools`: when `_WMP_CALIBRATION_TOOL` raises, the calibration failure latch is set and heaters the scrub heated are at 0 (existing heater-ownership cleanup).
  - `test_allowlist_rejects_out_of_range`: `_WMP_SCRUB_HEAD T=4` and `_WMP_SCRUB_ATTENTION VALUE=2` are "Unsupported calibration command".
  - `test_scrub_z_config_bounds`: `scrub_z: 10` is a config error.
  - `test_progress_resets_on_new_attempt`.

- [ ] **Step 2: Run** `… tests/test_nozzle_scrub_commands.py`. Expected: FAIL, module missing.
- [ ] **Step 3: Implement** `NozzleScrubCommands` and wire it into `CalibrationCommands.__init__` and `get_status`. Mount, clearance and park run through `gcode.run_script_from_command` so the existing failure latch and heater ownership apply. Add the five scrub commands and `_WMP_CALIBRATION_PHASE` to `backend_contract.json` `required.commands`, and `nozzle_scrub.protocol: 1`, `calibration_progress.protocol: 1` to `required.wmp_recovery`.
- [ ] **Step 4: Run** `… tests/test_nozzle_scrub_commands.py tests/test_calibration_commands.py tests/test_calibration_heater_ownership.py tests/test_calibration_tickets.py`. Expected: PASS.
- [ ] **Step 5: Commit** "Add backend nozzle scrub commands".

---

### Task 3: Case-light attention signal

This task is built and merged separately. It is done on branch
`feature/case-light-attention`, cut from `main` in the worktree
`.claude/worktrees/case-light-attention`, and merged to `main` before the rest of
this plan. `klipper_extras/wmp_case_light.py` and `tests/test_case_light.py` are
identical on `main` and on this branch's base, so the task applies unchanged. The
other tasks reach it when this branch is rebased; until then Task 2's
`_WMP_SCRUB_ATTENTION` treats a `wmp_case_light` object without
`request_attention` as absent. The commit includes a `docs/releases.md` entry and
the `config/README.md` command description, not left to Task 9.

**Files:**
- Modify: `klipper_extras/wmp_case_light.py`, `tests/test_case_light.py`, `config/live/case_light.cfg`

**Interfaces:**
- Produces on the `wmp_case_light` object:
  - `request_attention(owner: str) -> None`, `release_attention(owner: str) -> None`.
  - `ATTENTION_PATTERN = ((True, 0.5), (False, 0.5), (True, 0.5), (False, 1.0))`, where `True` means the opposite of the resting state and the second value is seconds.
  - Saved variable `case_light_attention` (bool, default true), loaded the same way as the existing preference variable.
  - G-code `SET_CASE_LIGHT_ATTENTION ENABLE=<0|1>`.
  - Status keys `attention_enabled: bool`, `attention_active: bool`.
- Resting state is `_desired(eventtime)` evaluated at each pattern step.

- [ ] **Step 1: Write failing tests** in `tests/test_case_light.py`:

  - `test_attention_pattern_from_on`: preference on and screen on; after `request_attention('x')` the GPIO writes over 2.5 s are `0, 1, 0, 1` at 0.0, 0.5, 1.0, 1.5 s and the pattern repeats at 2.5 s.
  - `test_attention_pattern_from_off`: preference off; writes are `1, 0, 1, 0`.
  - `test_release_restores_policy`: after release the next write equals `_desired`, and the saved on/off preference is unchanged.
  - `test_attention_disabled_setting_ignores_requests`: `SET_CASE_LIGHT_ATTENTION ENABLE=0` persists `case_light_attention=False`; a request causes no pattern writes.
  - `test_attention_setting_defaults_enabled`: with the variable absent, status reports `attention_enabled` true.
  - `test_two_owners`: the pattern continues until both owners release.
  - `test_gpio_error_during_pattern_is_logged_once_and_does_not_raise`.

- [ ] **Step 2: Run** `… tests/test_case_light.py`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** with a reactor timer separate from the existing policy timer; the policy `_apply` does not write while a pattern step holds the opposite state. Add a `SET_CASE_LIGHT_ATTENTION` description line to `config/live/case_light.cfg` comments only if that file documents the other commands.
- [ ] **Step 4: Run** `… tests/test_case_light.py tests/test_case_light_bridge.py`. Expected: PASS.
- [ ] **Step 5: Commit** "Add case-light attention signal".

---

### Task 4: Progress phases in the rapid macros

**Files:**
- Modify: `config/live/offset_calibrate.cfg` (`RAPID_MODE` :277, `CALIBRATE_TOOL_OFFSET` :304, `CALIBRATE_TOOL_Z_OFFSET` :395), `tests/test_config_macros.py`

**Interfaces:**
- Consumes: `_WMP_CALIBRATION_PHASE HEAD=n PHASE=…` from Task 2.
- Produces: `wmp_recovery.calibration_progress` advancing `mounting` → `position` → `height` during each `RAPID_MODE T=n`.

- [ ] **Step 1: Write failing tests** in `tests/test_config_macros.py`:
  - `test_rapid_mode_reports_phases`: rendering `RAPID_MODE T=2` yields `_WMP_CALIBRATION_PHASE HEAD=2 PHASE=mounting` before the tool change, `PHASE=position` before `TOOL_CALIBRATE_TOOL_OFFSET` (or `TOOL_LOCATE_SENSOR` for T0), and `PHASE=height` before the Z probe.
  - `test_phase_calls_are_inside_marked_blocks`: each added line sits in a `# >>> wondermaker+ begin:` / `# <<< wondermaker+ end:` block named `calibration-progress`.
- [ ] **Step 2: Run** `… tests/test_config_macros.py -k "phase"`. Expected: FAIL.
- [ ] **Step 3: Add the phase calls.** `CALIBRATE_TOOL_OFFSET` and `CALIBRATE_TOOL_Z_OFFSET` take their head from the same parameter they already use. The fine-mode macros (`NOZZLE_PREPARE`, `NOZZLE_CALIBRATE_TOOL_OFFSET`) are not changed.
- [ ] **Step 4: Run** `… tests/test_config_macros.py` and `uv run --with jinja2 python tools/validate_klipper_config.py`. Expected: PASS.
- [ ] **Step 5: Commit** "Report calibration progress from rapid offset macros".

---

### Task 5: Native flow state machine

**Files:**
- Create: `client-preload/unified-ui/native/nozzle_scrub_flow.hpp`, `tests/unified_ui/nozzle_scrub_flow.cpp`, `tests/test_nozzle_scrub_flow.py` (compile-and-run wrapper copied from `tests/test_probe_editor_flow.py`)
- Modify: `client-preload/unified-ui/native/projection.hpp`, `tests/unified_ui/projection.cpp`

**Interfaces:**
- Consumes: projected snapshot keys `fresh`, `calibration_session`, `calibration_failed`, `heads[i].actual`, `heads[i].target`, and new projected keys `nozzle_scrub` and `calibration_progress` (same shapes as Task 2; absent or wrong protocol projects to `phase: "unavailable"`).
- Produces, in namespace `wmp_ui::native`:

```cpp
enum class ScrubState { Idle, Prepare, StockChecks, ReturnPrompt, Mounting, Heating,
                        Scrub, Cooled, Cancelling, Failed, Calibrate, Finished };
enum class ScrubOutcome { None, Proceed, Skip };   // Skip: withhold offset-stage sends
struct ScrubView {
  ScrubState state; unsigned head, heads;          // head is 0-based
  bool brush, confirm_visible, confirm_enabled, cancel_visible, back_visible;
  std::string heading, body, note;                 // exact spec text
  double actual, target;                           // shown only in Heating
};
class NozzleScrubFlow {
 public:
  void open(unsigned heads, bool combined, const std::string& session); // -> Prepare
  void select(bool brush);
  bool confirm(double now);       // true when the caller must start the stock run (Prepare)
  void cancel(double now);
  void offset_stage_reached(double now);            // worker thread, under the runtime mutex
  void observe(const Json& snapshot, double now);
  bool next_command(std::string& command);          // inner command for the worker to send
  bool hold() const;                                // worker must stay blocked
  ScrubOutcome outcome() const;
  bool brush() const;
  ScrubView view() const;
  void close();                                     // -> Idle
};
```

- Behaviour pinned here:
  - Commands queued per transition: entering Mounting for head h queues `_WMP_SCRUB_HEAD T=h`; reaching `nozzle_scrub.phase == "heating"` for head h with h+1 < heads queues `_WMP_SCRUB_HEAT T=h+1`; entering ReturnPrompt, Scrub or Cooled queues `_WMP_SCRUB_ATTENTION VALUE=1`; leaving them queues `VALUE=0`; CONFIRM in Scrub queues `_WMP_SCRUB_COOL T=h`; the 600 s timeout queues `_WMP_SCRUB_COOL`; CONFIRM in Cooled queues `_WMP_SCRUB_HEAT T=h`; cancel after the scrub started queues `_WMP_SCRUB_END`.
  - Heating becomes Scrub when `heads[h].actual >= 157.5`.
  - Heating or Scrub becomes Cooled when `heads[h].target == 0` in a fresh snapshot taken after the heat command was acknowledged by `nozzle_scrub.head == h`.
  - On an offsets-only run `offset_stage_reached` goes straight to Mounting head 0; on a combined run it goes to ReturnPrompt.
  - Printed blob: `confirm` in Prepare returns true, `brush()` is false, the flow goes to Idle and never holds the worker.
  - After the last head is confirmed: outcome `Proceed`, state Calibrate, `hold()` false.
  - Cancel or failure after the scrub started: outcome `Skip`, `hold()` false once `nozzle_scrub.phase` is `ended` or `failed`, or the session changed.
  - Calibrate text comes from `calibration_progress`; with phase `unavailable` or `idle` and a known head it is "Measuring head N of M...".

- [ ] **Step 1: Write failing tests** in `tests/unified_ui/nozzle_scrub_flow.cpp` (plain `assert` style of `probe_editor_flow.cpp`):
  - `prepare_defaults_to_brush_and_exact_text`: view heading is "How will the nozzles be cleaned?", `brush` true, CONFIRM enabled only when the snapshot is fresh.
  - `blob_choice_never_holds`.
  - `offsets_only_run_skips_return_prompt` and `combined_run_shows_return_prompt` ("Ready to clean the nozzles." / "Press Confirm to start.").
  - `head_sequence_commands`: full four-head pass yields exactly `_WMP_SCRUB_HEAD T=0`, `_WMP_SCRUB_HEAT T=1`, attention on/off pairs, `_WMP_SCRUB_COOL T=0`, `_WMP_SCRUB_HEAD T=1`, and so on, ending with `_WMP_SCRUB_COOL T=3`, outcome `Proceed`.
  - `heating_shows_temperature` (actual 127, target 160) and `scrub_at_157_5`.
  - `timeout_after_600_seconds_cools_and_offers_reheat` ("Head 2 has cooled." / "Press Confirm to reheat.").
  - `external_target_clear_during_heating_becomes_cooled` (Review Focus 2).
  - `double_confirm_queues_one_command` (Review Focus 3).
  - `three_heads` : steps and loop stop at head 3, Calibrate text "Head 1 of 3" (Review Focus 4).
  - `stale_status_disables_confirm` (Review Focus 5).
  - `session_change_while_held_releases_with_skip`: view body "Printer restarted. Calibration stopped.", BACK visible (Review Focus 1).
  - `cancel_mid_scrub_queues_end_and_skips`: Cancelling text "Cooling and returning head 2 to its dock. Offsets are unchanged."
  - `backend_failure_shows_one_sentence_and_back`: `nozzle_scrub.error` "Head 2 did not mount." is shown as the body; outcome `Skip`.
  - `calibrate_progress_text`: phases map to "Mounting head 2...", "Measuring nozzle position...", "Measuring nozzle height...", "Returning head 4 to its dock..."; note is "Keep the door closed."
  - Projection: `nozzle_scrub` and `calibration_progress` project unchanged when valid and to `unavailable` when malformed.
- [ ] **Step 2: Run** `… tests/test_nozzle_scrub_flow.py tests/test_unified_ui.py -k projection`. Expected: FAIL to compile.
- [ ] **Step 3: Implement** `NozzleScrubFlow` and the projection keys. The class holds no locks and calls nothing outside itself.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** "Add nozzle scrub flow state machine".

---

### Task 6: Two-column screen

**Files:**
- Create: `client-preload/unified-ui/native/stock_nozzle_scrub.hpp`
- Modify: `tests/unified_ui/native_lifecycle.cpp`

**Interfaces:**
- Consumes: `ScrubView` from Task 5; `stock_dialog_backdrop`, `center_button_caption`, `stage_color` (`model.hpp:136`); the header pattern in `stock_calibration_status.hpp:104-114`.
- Produces:

```cpp
class StockNozzleScrub {
 public:
  std::function<void()> on_confirm, on_cancel, on_back;
  std::function<void(bool brush)> on_select;
  void created(void* page);          // nullptr dismisses
  void update(const ScrubView& view); // no widget work when the view is unchanged
  bool visible() const;
};
```

- Layout on 800 × 480: title "Nozzle offset calibration" at top left; top-bar actions right-aligned, 116 px wide, order CANCEL then CONFIRM (BACK alone in Failed); 1 px rule at y = 40; left column x 0 to 230 with one row per step ("1. Prepare", "2. Head 1" … "N. Calibrate"), 46 px row pitch; 1 px vertical rule at x = 230; right pane from x = 231. Prepare shows two radio rows, each a full-width touch target of at least 72 px height with a radio mark at least 28 px across. Top-bar actions keep the 40 px visible height of the existing screens and extend their hit area downward to at least 64 px. Heating shows "`<actual>` / `<target>` °C" with whole-degree values in the large font. Step colours: complete `0xff888888`, current `0xffff6600`, later `0xffeeeeee`. Disabled CONFIRM uses LVGL state 128 and caption colour `0xff888888`.

- [ ] **Step 1: Write failing tests** in `native_lifecycle.cpp` beside the `StockCalibrationStatus` cases (:1645):
  - `nozzle_scrub_prepare_layout`: labels "1. Prepare" … "6. Calibrate" exist; the first is orange; both radio rows exist; tapping the second calls `on_select(false)`.
  - `nozzle_scrub_three_heads_has_five_steps`.
  - `nozzle_scrub_touch_targets_meet_minimum`: CANCEL, CONFIRM, BACK and both radio rows each have a clickable area at least 64 px high and 110 px wide, and no two clickable areas overlap or sit closer than 8 px.
  - `nozzle_scrub_text_fits`: in every state, with four heads and the longest spec text, no label's text is clipped by its width and height at the chosen fonts.
  - `nozzle_scrub_heating_text` is "127 / 160 °C" and CONFIRM is disabled.
  - `nozzle_scrub_calibrate_has_no_actions`.
  - `nozzle_scrub_failed_shows_back_only`.
  - `nozzle_scrub_update_is_idempotent`: a repeated identical view creates no widgets.
  - `nozzle_scrub_dismiss_releases_widgets`: `created(nullptr)` then a tap calls nothing.
- [ ] **Step 2: Run** `… tests/test_unified_ui.py`. Expected: FAIL.
- [ ] **Step 3: Implement** the screen as a panel on the given page, preallocating labels as `StockRecoveryProgress` does.
- [ ] **Step 4: Run** `… tests/test_unified_ui.py`. Expected: PASS.
- [ ] **Step 5: Commit** "Add nozzle scrub screen".

---

### Task 7: Start hook, worker hold and command path

**Files:**
- Modify: `client-preload/unified-ui/native/runtime.hpp`, `bootstrap.cpp`, `profile1113.json` (and `profile1113.hpp` through `make_profile.py`), `stock_service_event.hpp`, `tests/unified_ui/native_lifecycle.cpp`, `tests/test_stock_calibration_worker.py`

**Interfaces:**
- Consumes: Tasks 5 and 6; `Runtime::begin_stock_calibration`, `stock_calibration_command_for_worker` (`runtime.hpp:238-277`); `unified_maintenance_event`, `unified_command_sender` (`bootstrap.cpp:270-301`).
- Produces:
  - Profile data entries: `is_rapid_mode` `0x384c570`, `auto_check_selected` `0x385fa88`, `current_thr_number` `0x385c260`, `knife_pairing_failed` `0xe64572d`; sender return addresses `offset_home` `0x4b7fbc`, `offset_rapid` `0x4b842c`, `offset_park` `0x4b847c`.
  - `bool Runtime::offer_nozzle_scrub(void* start_button)`: on the GUI thread; true when `auto_check_selected[3] == 1`, `is_rapid_mode == 0` and `stock_maintenance_allowed()`; opens the Prepare screen and remembers the START button.
  - `void Runtime::nozzle_scrub_at_offset_stage(const std::function<void(const std::string& inner)>& send)`: on the vendor worker thread; returns immediately when no brush scrub is bound to the running calibration request; otherwise blocks, calling `send` for each `NozzleScrubFlow::next_command`, until `hold()` is false.
  - `bool Runtime::withhold_offset_send(std::uintptr_t caller)`: true for `offset_rapid` and `offset_park` when the flow outcome is `Skip` (used fully in Task 8).

- Behaviour:
  - In `unified_maintenance_event`, on START with gate 0: if the scrub has not been decided for this press and `offer_nozzle_scrub` returns true, consume the event.
  - CONFIRM on Prepare: for Wire brush write `is_rapid_mode = 1` and bind the scrub to the request created by the next `begin_stock_calibration`; then re-send the click to the remembered START button (`lv_event_send(button, 7, nullptr)`, already declared in `profile1113.hpp`) with the decided flag set, after checking `lv_obj_is_valid`. The normal admission path then runs. The Maintenance page is not re-entered.
  - CANCEL on Prepare: dismiss the screen; nothing else changes.
  - In `unified_command_sender`: after the wrapped `G28` from `offset_home` has been passed to the original sender, call `nozzle_scrub_at_offset_stage` with a lambda that sends `stock_calibration_command_for_worker(offset_home, inner)` through the original sender. Inner commands therefore carry the same `SESSION`, `REQUEST`, `TICKET` and the next `SEQUENCE`.
  - The worker waits on a condition variable with a 250 ms timed wait; GUI-thread polling (`runtime.hpp:614-695`) feeds `observe` and notifies. The wait ends unconditionally when the runtime is shutting down.
  - The scrub screen is created on the GUI thread on the current stock page when the flow leaves `StockChecks`, and stays through Calibrate until the existing result overlay is shown or the worker status reaches 14.
  - If the binding is lost (admission refused, worker never enqueued), the flow is closed and `is_rapid_mode` is left at 1; the stock chooser rewrites it on the next selection.

- [ ] **Step 1: Write failing tests.**
  - `native_lifecycle.cpp`: `maintenance_start_in_accurate_mode_opens_prepare` (START consumed, stock handler not called); `prepare_blob_delegates_start_unchanged` (`is_rapid_mode` stays 0); `prepare_brush_sets_rapid_and_delegates_once`; `prepare_cancel_changes_nothing`; `rapid_mode_start_is_untouched`; `stale_status_keeps_confirm_disabled` (Review Focus 5); `worker_hold_sends_sequenced_scrub_commands` (inner commands leave as `_WMP_CALIBRATION_COMMAND HEX=… SEQUENCE=n` with consecutive n following the `G28`); `worker_released_on_session_change` (Review Focus 1); `unsupported_profile_never_offers`.
  - `tests/test_stock_calibration_worker.py`: `test_brush_run_reads_rapid_and_skips_fine_loop`: with `is_rapid_mode` written to 1 before the `0x4b7fbc` send returns, no `NOZZLE_PREPARE` is sent and four `RAPID_MODE` sends follow.
- [ ] **Step 2: Run** `… tests/test_unified_ui.py tests/test_stock_calibration_worker.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Vendor memory is read and written only through profile-declared addresses and compiled out under `WMP_NATIVE_TEST` behind test seams, as `leave_stock_calibration` does.
- [ ] **Step 4: Run** the same command, then the full `… tests`. Expected: PASS.
- [ ] **Step 5: Commit** "Run guided nozzle scrub from Maintenance start".

---

### Task 8: End the offset stage early and keep earlier results

Implements the spec section "Earlier results" using the mechanism recorded in Task 1. The steps below are written for mechanism A; if Task 1 recorded B, replace the native part with a bound save sent after worker status 14 and keep the backend rule and tests.

**Files:**
- Modify: `klipper_extras/wmp_recovery.py` (`cmd_run`, `_check`, attempt records), `tests/test_calibration_save_result.py`, `tests/test_calibration_commands.py`, `client-preload/unified-ui/native/runtime.hpp`, `bootstrap.cpp`, `stock_calibration_status.hpp`, `tests/unified_ui/native_lifecycle.cpp`

**Interfaces:**
- Produces:
  - Attempt record fields `earlier_results: bool` (true once `G29`, `SHAPER_CALIBRATE` or a `PID_CALIBRATE` completed without error) and `offset_stage: bool` (true once a scrub command, `NOZZLE_PREPARE` or `RAPID_MODE` was admitted).
  - Backend rule: `SAVE_CONFIG` bound to an attempt in state `failed` is admitted exactly once when `offset_stage` and `earlier_results` are both true, the printer is not shut down, and the failure was recorded while `offset_stage` was true. Every other command of a failed attempt stays refused. A non-zero `fail_flag` does not block this save and is not cleared by it.
  - `calibration_attempt` status gains `'offsets': 'measured'|'stopped'|'none'`.
  - Native: when `withhold_offset_send` is true the sends from `offset_rapid` and `offset_park` are not forwarded; at `offset_park` the `knife_pairing_failed` byte is written to 0. A probing failure (backend `calibration_failed` set while `calibration_progress.head >= 0`) sets the same `Skip` outcome.
  - Result text in `stock_calibration_status.hpp`, by priority after the existing refusal case: offsets stopped and save confirmed → "Offset calibration stopped. Earlier results were saved."; offsets stopped and nothing to save → "Offset calibration stopped. Offsets are unchanged."

- [ ] **Step 1: Write failing tests.**
  - Backend: `test_save_admitted_after_scrub_failure_with_earlier_results`; `test_save_admitted_after_rapid_mode_failure_with_earlier_results`; `test_save_refused_after_pid_failure` (existing behaviour kept); `test_save_refused_after_offset_failure_without_earlier_results`; `test_second_save_after_failure_refused`; `test_fail_flag_survives_early_save` (value still non-zero in saved variables after the save); `test_other_commands_still_refused_after_failure`; `test_cancelled_scrub_saves_normally` (`_WMP_SCRUB_END` then `SAVE_CONFIG`, attempt not failed, `offsets == 'stopped'`); `test_offsets_only_cancel_sends_no_save`.
  - Native: `skip_outcome_withholds_rapid_and_park_sends`; `failed_byte_cleared_at_park_only_when_skipping`; `result_text_offsets_stopped_saved`; `result_text_offsets_stopped_nothing_saved`; `successful_run_text_unchanged` ("Calibration settings saved.").
- [ ] **Step 2: Run** `… tests/test_calibration_save_result.py tests/test_calibration_commands.py tests/test_unified_ui.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep the existing comment at the `_check` call that explains the latch and add one line stating the offset-stage exception and its three conditions.
- [ ] **Step 4: Run** the full `… tests`. Expected: PASS.
- [ ] **Step 5: Commit** "Keep earlier maintenance results when the offset stage stops".

---

### Task 9: Offsets-only result, documentation and packaging

**Files:**
- Modify: `client-preload/unified-ui/native/stock_calibration_status.hpp`, `tests/unified_ui/native_lifecycle.cpp`, `docs/nozzle-scrub.md`, `README.md` or `docs/README.md` index, `docs/releases.md` (unreleased entry), `config/README.md` (new scrub options), screen package manifest per `docs/native-screen-packaging.md`

- [ ] **Step 1: Write failing test** `result_text_offsets_only_success`: after an offsets-only brush run with every `RAPID_MODE` acknowledged and no client `SAVE_CONFIG`, the result screen shows "Nozzle offsets saved." and not "Saving calibration...". First confirm in `tests/unified_ui/native_lifecycle.cpp:1645-1814` what the screen shows today for that case; if it already reports success, record that in `docs/nozzle-scrub.md` and keep the test as a regression test with the existing text.
- [ ] **Step 2: Run** `… tests/test_unified_ui.py -k result`. Expected: FAIL (or PASS in the already-correct case).
- [ ] **Step 3: Implement** using `calibration_attempt.offsets == 'measured'`.
- [ ] **Step 4: Write `docs/nozzle-scrub.md`:** what the flow does, the two cleaning choices, each screen state, cancel and failure behaviour, the earlier-results rule, the `[wmp_recovery]` options `scrub_x`, `scrub_y`, `scrub_z`, `scrub_temp`, the `SET_CASE_LIGHT_ATTENTION` command, which parts are stock firmware and which are installed by `tools/deploy.py`, and the vendor findings from Task 1.
- [ ] **Step 5: Rebuild and reseal** the native screen package as `docs/native-screen-packaging.md` describes, then run the full `… tests` and `uv run --with jinja2 python tools/validate_klipper_config.py`. Expected: PASS, including `tests/test_screen_package_current.py`.
- [ ] **Step 6: Commit** "Document guided nozzle scrub and reseal screen package".

---

### Task 10: Printer validation (run by the user)

Not automated. Requires deployment to the printer, which needs the user's go-ahead.

- [ ] Confirm the scrub height: at X150 Y2 Z100 a wire brush reaches the nozzle and the head clears the front panel and door. Adjust `scrub_z` if not.
- [ ] Offsets-only brush run: four heads, offsets saved, result text correct.
- [ ] Combined run with PID: return prompt appears after PID, light blinks, scrub and probing complete, one save.
- [ ] Cancel in each of Prepare, ReturnPrompt, Heating, Scrub: heaters off, head docked, earlier results saved on a combined run, stored offsets unchanged.
- [ ] Leave a Scrub step for 10 minutes: Cooled state, reheat works.
- [ ] Printed blob choice runs the stock Accurate flow.
- [ ] Rapid mode and first-run setup behave as before.
- [ ] Light pattern from both light-on and light-off states; `SET_CASE_LIGHT_ATTENTION ENABLE=0` silences it across a restart.
- [ ] Record results in `docs/nozzle-scrub.md`.
