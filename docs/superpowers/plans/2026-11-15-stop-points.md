# Stop Points Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A print Cancel during `START_PRINT` takes effect at the next safe stop point or within about one second of a start-print heat wait, instead of after the whole macro.

**Architecture:** `wm_material` exposes `stop_requested()` / `check_stop_point()` on top of the existing pending print-cancel record. `_WMP_STOP_POINT` and `_WMP_STOP_WAITS` are Python G-code commands placed in `START_PRINT` as marked vendor patches. `TEMPERATURE_WAIT` and `_wait_for_temperature` get a managed loop used only while a wait region is open. A stop raises `gcode.error`, which unwinds through the existing nested-Cancel / SD error path into the existing motion-free cleanup.

**Tech Stack:** Python 3 (Klipper extras, retained vendor klippy 1.1.13), Jinja2 Klipper macros, C++ native screen (LVGL panel), pytest.

**Spec:** `docs/superpowers/specs/2026-11-15-stop-points-design.md`

## Global Constraints

- No printer contact. All tests are host-side.
- Test command prefix (pytest is not installed system-wide): `uv run --no-project --with pytest --with jinja2 python -m pytest`
- Vendor reference: `analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy` (the worktree has an untracked `analysis` symlink to the main checkout; never `git add` it).
- Phase names match `[a-z0-9_]{1,48}`.
- Stop error text: `Print cancellation requested; stopped at <label>` and `Print cancellation requested; stopped while heating <heater>`.
- Cancellation journal version 3 adds optional `stop_point = {"phase", "label", "state"}` (all strings); versions 1 and 2 stay readable.
- openACE or AFC present: stop points, wait regions and heat-wait wrappers are inert; vendor behaviour unchanged.
- No new motion anywhere. No `M400` in the new commands.
- Vendor macro edits go inside `# >>> wondermaker+ begin: stop-points` / `# <<< wondermaker+ end: stop-points` markers and must pass `tools/validate_klipper_config.py`.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01B3rq1bWfLSycPKTWYnLuBa
  ```

## Review Focus

1. Cancel arrives while the wait region is open but execution is inside `T{INITIAL_TOOL}`'s `_WAIT_TOOL_TEMPERATURE` — must not raise (region closed around both `T` calls). Test: Task 4 `test_start_print_closes_wait_region_around_each_initial_tool`, Task 3 `test_closed_region_wait_ignores_stop_request`.
2. A stale wait region left open by an aborted job leaking into the next job — must count as closed when the SD handle changes. Test: Task 2 `test_wait_region_closed_by_handle_change_or_reset`.
3. Cancel for a different job (old handle) while a new job runs `START_PRINT` — stop point is a no-op. Test: Task 2 `test_stop_point_noop_for_other_job_or_owner`.
4. Persisting `stop_point` fails (disk error) — the stop still raises, `persistence_error` is set. Test: Task 2 `test_stop_point_raises_even_when_persist_fails`.
5. Restart with a version 3 pending record restores as unknown and `_WMP_STOP_POINT` is a no-op. Tests: Task 1 `test_v3_record_with_stop_point_round_trips`, Task 2 `test_stop_requested_none_after_restore`.

---

### Task 1: Cancellation journal version 3

**Files:**
- Modify: `klipper_extras/wm_material.py:2913-2945` (`_restore_print_cancel`)
- Create: `klipper_extras/test_stop_points.py`

**Interfaces:**
- Produces: `WmMaterial._record_stop_point(phase: str, label: str, state: str) -> None` — sets `self._print_cancel["version"] = 3` and `["stop_point"] = {"phase", "label", "state"}` then calls `_record_print_cancel()` (which already swallows `OSError`/`ValueError` into `persistence_error`).
- `_restore_print_cancel` accepts version 3: key set is the version 2 set plus optional `stop_point`; `stop_point` must be a dict with exactly `{"phase","label","state"}`, each a `str`, `phase` matching `[a-z0-9_]{1,48}`, label/state ≤ 160 chars. Stages validated as for version 2.

`test_stop_points.py` starts with `pytest_plugins = ['test_wm_material']` (same as `test_phase_b_cancel.py`) to reuse `managed_cancel_cleanup`, `managed_cancel_intent`, `legacy_cancel_routes`, `guarded_legacy_dispatch`.

- [ ] **Step 1: Write failing tests**

```python
def test_v3_record_with_stop_point_round_trips(managed_cancel_intent): ...
    # begin cancel, _record_stop_point('homed','after homing','homed; probe head attached and locked'),
    # _restore_print_cancel(); assert record['version'] == 3 and
    # record['stop_point'] == {'phase':'homed','label':'after homing','state':'homed; probe head attached and locked'}
    # and record['state'] == 'unknown' (pending restores as unknown)

@pytest.mark.parametrize('bad', [{'phase':'Homed','label':'x','state':'y'}, {'phase':'homed','label':'x'},
    {'phase':'homed','label':'x','state':'y','extra':1}, 'homed', {'phase':'homed','label':1,'state':'y'}])
def test_v3_rejects_malformed_stop_point(managed_cancel_intent, bad): ...
    # write record with stop_point=bad; restore -> state 'unknown', message startswith 'Print cancellation record is unreadable'

def test_v2_record_still_restores(managed_cancel_intent): ...
def test_v2_record_with_stop_point_is_unreadable(managed_cancel_intent): ...
```

(The "stop point is inert after restore" half of Review Focus 5 is tested in Task 2 as `test_stop_requested_none_after_restore`, once `stop_requested()` exists.)

Write records through the material's own `_write_recovery_json(material._print_cancel_path(), record)` so the fixture's filesystem is used.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --no-project --with pytest --with jinja2 python -m pytest -q klipper_extras/test_stop_points.py -k "v3 or v2"`
Expected: FAIL (`_record_stop_point` missing; v3 rejected).

- [ ] **Step 3: Implement `_record_stop_point` and v3 acceptance in `_restore_print_cancel`.**

- [ ] **Step 4: Run tests**

Run the Step 2 command plus `klipper_extras/test_phase_b_cancel.py tests/test_cancel_native_pause.py`.
Expected: PASS.

- [ ] **Step 5: Commit** — `git add klipper_extras/wm_material.py klipper_extras/test_stop_points.py && git commit -m "Accept cancellation journal version 3 with a recorded stop point"`

---

### Task 2: Stop-request lookup, `_WMP_STOP_POINT` and `_WMP_STOP_WAITS`

**Files:**
- Modify: `klipper_extras/wm_material.py` (new methods near `_print_cancel_active`, line ~2878; registration in `_cancel_routes_ready`, line ~2461; `virtual_sdcard:reset_file` handler, line ~495; start of `_cancel_print_cleanup`, line ~3069)
- Test: `klipper_extras/test_stop_points.py`

**Interfaces:**
- Consumes: `_record_stop_point` (Task 1).
- Produces:
  - `WmMaterial.stop_requested() -> dict | None` — returns `{"scope": "print", "cancel_id": str}` when `_print_cancel_active()` is true, `_print_cancel_live_binding` is not None, its `session == self.session_id`, `file == print_stats.filename`, `handle is virtual_sdcard.current_file`, and neither `openace` nor `AFC` is loaded. Else `None`. No side effects.
  - `WmMaterial.check_stop_point(phase: str, label: str, state: str) -> None` — if `stop_requested()` is None returns. Otherwise closes the wait region, calls `_record_stop_point` inside `try/except Exception` (logging only), then raises `self.printer.lookup_object("gcode").error("Print cancellation requested; stopped at " + label)`.
  - `WmMaterial.stop_waits_open() -> bool` — true iff `_stop_waits` is `{"session": self.session_id, "handle": sd.current_file}` with `handle is not None` and no openACE/AFC owner.
  - `WmMaterial._STOP_POINTS: dict[str, tuple[str, str]]` — phase → (label, machine state), exactly the non-heating rows of spec §4: `start_admitted`, `before_homing`, `homed`, `before_mesh`, `mesh_saved`, `before_initial_tool`, `initial_tool_ready`, `purged`. Label/state wording is the builder's (spec "Left to the builder").
  - G-code `_WMP_STOP_POINT PHASE=<name>`: unknown or malformed `PHASE` → `gcmd.error("Unknown stop point PHASE=<value>")`, always (also with no stop request). Known phase → `check_stop_point(phase, *self._STOP_POINTS[phase])`. No output when no stop.
  - G-code `_WMP_STOP_WAITS ENABLE=0|1`: `1` sets `_stop_waits = {"session", "handle": sd.current_file}`; `0` sets `None`. Other values → `gcmd.error`. No output.
  - Region is also set to `None` at the start of `_cancel_print_cleanup` and in the `virtual_sdcard:reset_file` handler.

- [ ] **Step 1: Write failing tests**

```python
def test_stop_point_noop_without_request(legacy_cancel_routes): ...
    # handlers['_WMP_STOP_POINT'](FakeCommand(PHASE='homed')) returns None; no record change; no output

def test_stop_point_raises_and_records_for_bound_job(legacy_cancel_routes): ...
    # run_script('CANCEL_PRINT'); then handler raises ValueError matching
    # 'Print cancellation requested; stopped at '; material._print_cancel['stop_point']['phase'] == 'homed';
    # version == 3; cleanup == [] (no cleanup ran synchronously)

@pytest.mark.parametrize('change', ['handle', 'session', 'file', 'openace', 'AFC'])
def test_stop_point_noop_for_other_job_or_owner(legacy_cancel_routes, change): ...

@pytest.mark.parametrize('phase', ['nope', 'HOMED', 'a'*49, ''])
def test_unknown_stop_phase_is_an_error_even_without_request(legacy_cancel_routes, phase): ...

def test_stop_point_raises_even_when_persist_fails(legacy_cancel_routes, monkeypatch): ...
    # monkeypatch material._write_recovery_json to raise OSError('disk'); handler still raises the stop error;
    # material._print_cancel['persistence_error'] == 'disk'

def test_wait_region_closed_by_handle_change_or_reset(legacy_cancel_routes): ...
    # ENABLE=1 -> stop_waits_open() True; replace sd.current_file -> False;
    # ENABLE=1 again, fire reset_file handler -> False; ENABLE=1, stop point raise -> False

def test_stop_requested_none_after_restore(managed_cancel_intent): ...  # Task 1 Review Focus 5
```

`handlers` comes from the `legacy_cancel_routes` fixture (its `register` captures every `register_command`). Use the existing `FakeCommand` in `test_wm_material.py`; if it lacks `get(name, default)`, extend it there.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --no-project --with pytest --with jinja2 python -m pytest -q klipper_extras/test_stop_points.py`
Expected: FAIL (`_WMP_STOP_POINT` not registered).

- [ ] **Step 3: Implement the interfaces above.** Register both commands inside `_cancel_routes_ready` after the `CANCEL_PRINT` registration, so they share its once-only guard.

- [ ] **Step 4: Run tests**

Run the Step 2 command plus `klipper_extras/test_phase_b_cancel.py` and `klipper_extras/test_wm_material.py -k "cancel"`.
Expected: PASS.

- [ ] **Step 5: Commit** — `"Add stop-point and wait-region commands bound to the pending print cancel"`

---

### Task 3: Interruptible heat waits

**Files:**
- Modify: `klipper_extras/wm_material.py` (install in `_cancel_routes_ready`)
- Test: `klipper_extras/test_stop_points.py`

**Interfaces:**
- Consumes: `stop_requested()`, `stop_waits_open()`, `_record_stop_point` (Tasks 1–2).
- Produces:
  - `TEMPERATURE_WAIT` re-registered via `gcode.register_command("TEMPERATURE_WAIT", None)` → keep `original`, register wrapper. Wrapper: if `not stop_waits_open()` → `return original(gcmd)` unchanged. Otherwise run a managed loop with the vendor semantics of `heaters.py:400-426` (same `SENSOR` validation and errors, `MINIMUM`/`MAXIMUM` parsing with `above=min_temp`, debugoutput early return, `get_temp`, `respond_raw(pheaters._get_temp(eventtime))`, `reactor.pause(eventtime + 1.)`, `quick_stop_flag` and `is_shutdown()` exits, `"quick Stop, break"` message). Before each `reactor.pause` and once on entry, if `stop_requested()` is not None: close the region, `_record_stop_point("heating_" + sensor_name, "while heating " + sensor_name, "<heater> wait interrupted; cleanup turns heaters off")`, raise `gcmd.error("Print cancellation requested; stopped while heating " + sensor_name)`.
  - `PrinterHeaters._wait_for_temperature` wrapped on the `heaters` object instance: closed region → original; open region → managed loop with vendor semantics of `heaters.py:379-392`, same stop check, phase `heating_<heater.name>` (use `heater.get_name()` if present, else `heater.name`).
  - Phase `heating_<sensor>` must satisfy `[a-z0-9_]{1,48}`; `heater_bed`, `extruder`, `extruder1..3` do.

- [ ] **Step 1: Write failing tests**

Load the retained vendor `PrinterHeaters.cmd_TEMPERATURE_WAIT` and `_wait_for_temperature` by AST exactly as `tests/test_config_macros.py:199-236` does (but from `fw_1.1.13_payload`), and use them as `original`.

```python
@pytest.mark.parametrize('readings,minimum,maximum', [([220.,90.], None, 102.5), ([90.,220.], 217.5, 222.5),
                                                      ([50.,60.,61.], 59., 61.)])
def test_open_region_wait_matches_vendor_without_request(..., readings, minimum, maximum): ...
    # same sequence through vendor and through wrapper (region open, no request):
    # identical pause count, identical respond_raw messages, returns normally

def test_open_region_wait_raises_within_one_iteration(...): ...
    # readings never in range; request appears after first pause; wrapper raises
    # 'Print cancellation requested; stopped while heating extruder3' with exactly 1 pause after the request;
    # stop_point.phase == 'heating_extruder3'; stop_waits_open() is False

def test_closed_region_wait_ignores_stop_request(...): ...
    # request pending, region closed: wrapper delegates to vendor original (assert original called with same gcmd)

def test_wait_for_temperature_wrapper_raises_for_bed(...): ...  # phase 'heating_heater_bed'

def test_wait_wrappers_inert_with_openace(...): ...
```

- [ ] **Step 2: Run to verify failure** — `... -k "wait"` → FAIL.

- [ ] **Step 3: Implement the wrappers.** Install them once (guard by an attribute on `self`, as `_cancel_script_wrapper` does).

- [ ] **Step 4: Run tests** — Step 2 command plus `tests/test_config_macros.py -k "wait"`. Expected: PASS.

- [ ] **Step 5: Commit** — `"Interrupt start-print heat waits on a pending print cancel"`

---

### Task 4: START_PRINT stop points and wait regions

**Files:**
- Modify: `config/live/macros.cfg` (`[gcode_macro START_PRINT]`, lines 7–218)
- Test: `tests/test_stop_points_macros.py` (create)

**Interfaces:**
- Consumes: G-code names `_WMP_STOP_POINT PHASE=` and `_WMP_STOP_WAITS ENABLE=` (Task 2); `WmMaterial._STOP_POINTS` keys.
- Produces: rendered `START_PRINT` in this exact relative order (other commands interleaved):
  `_WMP_RECOVERY_JOB_BEGIN` block end → `_WMP_STOP_POINT PHASE=start_admitted` → `_WMP_STOP_WAITS ENABLE=1` → first `SET_HEATER_TEMPERATURE HEATER=heater_bed` → … → `TEMPERATURE_WAIT SENSOR={probe_heater}` → `_WMP_STOP_POINT PHASE=before_homing` → `G28` → `_WMP_STOP_POINT PHASE=homed` → `M190` → `_WMP_STOP_POINT PHASE=before_mesh` → mesh block → `M118 START_PRINT adaptive_mesh` → `_WMP_STOP_POINT PHASE=mesh_saved` → probe heater off → `M400` → `_WMP_STOP_POINT PHASE=before_initial_tool` → `_WMP_STOP_WAITS ENABLE=0` → `T{INITIAL_TOOL}` → `_WMP_STOP_WAITS ENABLE=1` → `_WMP_STOP_POINT PHASE=initial_tool_ready` → `SET_GCODE_OFFSET` … `G1 X0.0 Y70.0` → `M109` → purge lines → `_WMP_STOP_POINT PHASE=purged` → `_WMP_STOP_WAITS ENABLE=0` → second `T{INITIAL_TOOL}` → `_WMP_PRINT_CONTEXT_COMMIT`.
  The new lines are wrapped only when `'wm_material' in printer and 'openace' not in printer and 'AFC' not in printer` (same guard style as the existing `print-mesh-context-start` patch), so openACE/AFC configurations render no new lines.

- [ ] **Step 1: Write failing tests** (use `HeaterModel` / `templates` from `tests/test_config_macros.py`; render with `printer` including `'wm_material': {}` and both mesh modes)

```python
EXPECTED = ['start_admitted','before_homing','homed','before_mesh','mesh_saved',
            'before_initial_tool','initial_tool_ready','purged']

@pytest.mark.parametrize('adaptive', [True, False])
def test_start_print_stop_points_once_in_order(adaptive): ...
    # phases extracted from rendered lines == EXPECTED; every phase in klipper_extras WmMaterial._STOP_POINTS

def test_start_print_closes_wait_region_around_each_initial_tool(): ...
    # for each line index of 'T{n}' command: the nearest preceding _WMP_STOP_WAITS has ENABLE=0

def test_no_stop_point_inside_purge_line(): ...
    # no _WMP_STOP_POINT between 'G1 Z0.4' and 'G1 Y150.0 E20'

def test_start_print_renders_no_stop_lines_with_openace_or_afc(): ...

def test_stop_point_macro_text_passes_validator(): ...
    # tools/validate_klipper_config.validate_text('macros.cfg', text) == []
```

- [ ] **Step 2: Run to verify failure** — `... -m pytest -q tests/test_stop_points_macros.py` → FAIL.

- [ ] **Step 3: Insert the lines inside `# >>> wondermaker+ begin: stop-points` / `# <<< wondermaker+ end: stop-points` markers** (one marker pair per insertion site is acceptable). Keep existing patches untouched.

- [ ] **Step 4: Run tests** — Step 2 command plus `tests/test_config_macros.py tests/test_klipper_config_validation.py tests/test_managed_cancel_ordering.py`. Expected: PASS.

- [ ] **Step 5: Commit** — `"Place stop points and wait regions in START_PRINT"`

---

### Task 5: End-to-end through the retained dispatcher and SD error path

**Files:**
- Test: `klipper_extras/test_stop_points.py`

**Interfaces:**
- Consumes: Tasks 2–4; fixture `guarded_legacy_dispatch` (retained vendor `GCodeDispatch`).

- [ ] **Step 1: Write the tests** (no production code expected; if one fails, fix the owning task's code and note it in the commit)

```python
@pytest.mark.parametrize('stop_at', ['probe_preheat', 'bed_wait', 'purge_wait'])
def test_cancel_during_start_print_wait_stops_without_tool_change_or_purge(guarded_legacy_dispatch, stop_at): ...
    # Register in the dispatcher: _WMP_STOP_POINT, _WMP_STOP_WAITS (material handlers), TEMPERATURE_WAIT (Task 3
    # wrapper over a fake sensor that never reaches range), and recording stubs for G28, M190 (macro body
    # expands to M140 + TEMPERATURE_WAIT), BED_MESH_CALIBRATE, T0..T3, G1, M109 (expands to
    # SET_HEATER_TEMPERATURE + TEMPERATURE_WAIT). Feed the rendered START_PRINT script (Task 4 render helper)
    # through dispatcher.run_script_from_command with sd.cmd_from_sd = True.
    # Inject CANCEL_PRINT via objects['gcode'].run_script at the selected wait's first pause.
    # Assert: run raises the stop error; events after the raise contain no 'T*', no 'G1 ... E', no G28 when
    # stop_at == 'probe_preheat'; material._print_cancel['stop_point']['phase'] startswith 'heating_'.
    # Then emulate SD error fallback: run_script('CANCEL_PRINT') coalesces (no second worker),
    # sd.cmd_from_sd = False, print_stats.state = 'error', locked[0] = False, timers[-1].callback(…);
    # assert _print_cancel['state'] == 'complete' and cleanup contains no G1/G28/T*.

def test_cancel_between_steps_stops_at_next_stop_point(guarded_legacy_dispatch): ...
    # CANCEL arrives during G28 stub; next command executed is _WMP_STOP_POINT PHASE=homed, which raises;
    # M190 never dispatched.
```

- [ ] **Step 2: Run** — `... -m pytest -q klipper_extras/test_stop_points.py -k "start_print or between_steps"`. Expected: PASS.

- [ ] **Step 3: Run the full affected suites**

Run: `uv run --no-project --with pytest --with jinja2 python -m pytest -q klipper_extras tests -x`
Expected: PASS (same skips as the baseline on `fix/gate-correction`).

- [ ] **Step 4: Commit** — `"Verify start-print cancellation end to end through the retained dispatcher"`

---

### Task 6: Show the stop point on the native cancel progress panel

**Files:**
- Modify: `client-preload/unified-ui/native/stock_recovery_progress.hpp:~224-262` (summary assembly)
- Test: `tests/unified_ui/native_lifecycle.cpp` (cancel progress block near line 2285), run by `tests/test_unified_ui.py`

**Interfaces:**
- Consumes: receipt JSON field `stop_point.label` (string), present when the backend recorded one (status `print_cancel` is a deep copy of `_print_cancel`, `wm_material.py:875`).
- Produces: when `cancel_mode_` and `receipt["stop_point"]["label"]` is a non-empty string ≤ 160 chars, append `"\nStopped at: " + label` to `summary` once. Non-string or missing → nothing. No new widgets.

- [ ] **Step 1: Write the failing native test** — in `native_lifecycle.cpp`, extend the cancel progress case: receipt with `{"stop_point",{{"phase","homed"},{"label","after homing"},{"state","x"}}}` → `contains("Stopped at: after homing")` is non-null; a receipt with `"stop_point": 5` → no "Stopped at" text; repeated `panel.update` with the same result does not add text writes (reuse the existing `fake::text_writes` check pattern at line 2292).

- [ ] **Step 2: Run to verify failure** — `uv run --no-project --with pytest --with jinja2 python -m pytest -q tests/test_unified_ui.py -k lifecycle` → FAIL.

- [ ] **Step 3: Implement the summary line.**

- [ ] **Step 4: Run** — same command → PASS.

- [ ] **Step 5: Commit** — `"Show where a cancelled operation stopped on the progress panel"`

---

### Task 7: Documentation

**Files:**
- Modify: `config/README.md` (patch inventory: add `stop-points` in `macros.cfg` START_PRINT, with re-baseline note)
- Modify: `docs/upstream-client-callers.md` (append "R27 stop points — <date> (local, undeployed)" entry: what stops early, what still runs to completion — `G28`, `BED_MESH_CALIBRATE`, tool changes — and the journal version 3 rollback rule)

- [ ] **Step 1: Write both entries.** Plain technical style; state that deployment uses the existing SSH config deploy of `macros.cfg` and `wm_material.py` plus the native screen package.
- [ ] **Step 2: Run** `uv run --no-project --with pytest --with jinja2 python -m pytest -q tests/test_host_text_portability.py` → PASS.
- [ ] **Step 3: Commit** — `"Document start-print stop points"`
