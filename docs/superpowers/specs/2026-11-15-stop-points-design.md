# Stop points for long-running operations — design

Date: 2026-11-15
Branch: `feature/safe-cancel` (based on `fix/gate-correction`; rebases onto the final r4 branch)

## Intent

A Cancel or Stop pressed during a long operation currently takes effect only after
the whole vendor macro that is running has finished. For start-of-print this means
homing, heating, mesh measurement, the initial tool change and the purge all run
before cancellation cleanup begins.

This design adds stop points: named, known-safe positions inside long operations
where a pending stop request is honoured. The request is recorded immediately (this
already happens for print Cancel); the operation stops at its next stop point instead
of at its end.

Scope of this document:

1. The shared mechanism (stop-request lookup, `_WMP_STOP_POINT`, interruptible heat
   waits).
2. Its first consumer: `START_PRINT`, through the existing print Cancel.

Later consumers, each with its own short design: UI Dock/Take, calibration runs, and
a coverage check of the managed filament service (which already has its own
checkpoints and moves onto the shared mechanism).

## Current behaviour

- Print Cancel from Fluidd, Moonraker, the console and the native screen enters
  `wm_material` before the G-code mutex (`_cancel_routes_ready`,
  `klipper_extras/wm_material.py:2461`). `_begin_print_cancel` records durable intent
  (`_print_cancel.state == "pending"`), sets `sd.must_pause_work` and schedules a
  cleanup timer.
- The cleanup timer waits until `sd.is_active()`, `sd.is_cmd_from_sd()` and the G-code
  mutex are all idle. `START_PRINT` is one SD command, so cleanup waits for all of it.
- Cleanup (`_cancel_print_cleanup`) adds no motion: M400, heaters off with readback,
  recovery invalidation, `sd.do_cancel()`, `CLEAR_PAUSE`, non-motion housekeeping.
- A nested `CANCEL_PRINT` inside a macro already unwinds the enclosing macros by
  raising `gcode.error`. The SD worker catches it, runs `on_error_gcode`
  (`CANCEL_PRINT`), which coalesces with the live intent, and stops.
- Vendor heat waits (`heaters._wait_for_temperature`, `cmd_TEMPERATURE_WAIT`) loop on
  `reactor.pause(eventtime + 1.)` and exit early only on shutdown or the vendor
  `printer.quick_stop_flag`.

## Goals

- A print Cancel issued during `START_PRINT` takes effect at the next stop point, at
  most one compiled step plus queued motion later.
- A Cancel during a heat wait inside `START_PRINT` (probe-nozzle preheat, bed wait,
  print-nozzle wait at the purge position) takes effect within about one second.
- Cancelling before the purge means nothing is extruded.
- Each stop records which stop point it used, so the cancellation result states what
  the machine was doing and what state it was left in.

## Non-goals

- Emergency stop. `M112` remains the emergency path and is unchanged.
- Stopping inside `G28` or `BED_MESH_CALIBRATE` in this phase (vendor Python; see
  Later extensions), or inside MCU-timed steps at any phase: homing moves, probe
  moves, lock/unlock strokes, `ECHELON_*` commands. These finish before the next stop
  point is reached.
- Any new cleanup motion. Cleanup after a stop is the existing motion-free cleanup.
- Changing the print Cancel API, receipts, journal semantics or UI flow beyond
  showing the recorded stop point.
- openACE or AFC ownership. When either owner is present, stop points are no-ops and
  those owners keep their existing cancel routes.

## Anti-goals

- Silent skipping. A stop must always raise and be recorded; no command may return
  as if it succeeded when it was skipped (the vendor `quick_stop_flag` behaviour).
- A stop that leaves the head in an unknown state. Stop points are only placed where
  the attachment state is known: no stop point between unlock and lock, between a
  pickup move and its lock confirmation, or inside the purge line.
- A second cancellation implementation. Stop points only shorten the wait before the
  existing cleanup runs.

## Approaches

**A. Stop-point lines in vendor macros (chosen).** Add `_WMP_STOP_POINT PHASE=<name>`
lines at safe positions in `START_PRINT` (and later `_CHANGE_TOOL`, calibration
macros), inside `# >>> wondermaker+ begin/end` markers like every other vendor patch.
The command is Python: it checks for a pending stop, records the phase and raises.
Small changes; follows the existing patch convention. The patches depend on vendor
macro structure and are re-checked on each firmware re-baseline with the other
patches.

**B. Python sequencing.** Move each operation's step sequence into Python and call
small vendor macro fragments with checks between them. Puts stop points in one place,
but copies vendor tool-change and start logic, the code most expensive to own and the
first to go stale on a firmware update. Rejected.

**C. Reuse vendor `printer.quick_stop_flag`.** Already checked by vendor heat waits,
probing and `G1`. Rejected: it silently skips every remaining line, applies to the
whole process, is cleared by idle-timeout events, and the vendor `quick_stop` endpoint
cancels the SD job before managed admission (`docs/upstream-client-callers.md`,
native STOP prefix). Its existing behaviour is left unchanged.

## Design

### 1. Stop-request lookup

`wm_material` gains `_stop_request()`, which returns the active stop request for the
current session or `None`. A stop request has a scope and a binding. This phase
implements one scope:

- `print`: `_print_cancel_active()` is true, `_print_cancel_live_binding` matches the
  current session, `print_stats.filename` and the open SD file handle, and no
  openACE/AFC owner is present.

The lookup reads existing state; it adds no new durable record. Restart clears the
in-memory binding, and a restored unknown cancellation is not a live stop request
(`_print_cancel_active()` is already false for unknown).

Later scopes (`toolhead`, `calibration`, `filament`) are added by their own designs
and must use the same lookup.

The lookup is exposed as a stable Python entry point on the `wm_material` object so
that Python code outside macros can honour the same request:

- `stop_requested()` returns the active stop request or `None`; no side effects.
- `check_stop_point(phase, label, state)` records `stop_point` and raises
  `gcode.error` when a stop request is active; otherwise returns. `_WMP_STOP_POINT`
  and the heat-wait wrappers are implemented on top of it.

Callers obtain it with `printer.lookup_object("wm_material", None)` and treat a
missing object as "no stop request", so vendor-code wrappers stay inert when
`wm_material` is not loaded.

### 2. `_WMP_STOP_POINT PHASE=<name>`

Registered by `wm_material` at ready, alongside the cancel routes.

- `PHASE` is required and must match `[a-z0-9_]{1,48}` and a phase in the stop-point
  table for the calling macro (§4). An unknown phase raises a configuration error
  message; it never silently passes.
- No stop request, or openACE/AFC owner present: no-op, no output.
- Stop request present: record `stop_point = {"phase": <name>, "label": <table label>,
  "state": <table machine state>}` on the live cancellation record, persist it, then
  raise `gcode.error("Print cancellation requested; stopped at <label>")`.
- Recording failure must not prevent the raise. The raise is the stop; the record is
  diagnostic.
- The command sends no motion and does not wait (`M400` is not used).

The raise follows the existing nested-Cancel unwinding path: the SD worker catches
the error, runs `on_error_gcode`, which coalesces with the live intent, and exits.
The cleanup timer then proceeds as today.

The SD worker reports that error through `print_stats.note_error()`, which clears
`print_start_time`, so the cleanup's later `note_cancel()` would be a no-op and
Moonraker/Fluidd history would show a failed print. A wrapper on the `print_stats`
instance therefore records `cancelled` instead of `error` when the message starts
with `Print cancellation requested; stopped ` (stop-point and heat-wait texts) and a
live cancel is still bound to the current session, file and handle. Every other
message, and a stop text without such a cancel, reaches the vendor `note_error()`
unchanged; the wrapper is inert with openACE/AFC present.

### 3. Interruptible heat waits

While a stop request exists and an interruptible-wait region is open, heat waits
raise within one wait-loop iteration (about one second) instead of waiting for the
target. Outside an open region, heat waits behave exactly as today, including the
tool-change wait in `_WAIT_TOOL_TEMPERATURE` (`config/live/change_macros.cfg:739`)
during `T{INITIAL_TOOL}` and mid-print tool changes. Tool-change waits are covered by
the Dock/Take design.

- Region control: `_WMP_STOP_WAITS ENABLE=1|0`, registered with `_WMP_STOP_POINT`.
  The open region is in-memory, bound to the current session and open SD file handle,
  and counts as closed if either changes. It is also closed by any stop-point raise,
  by cleanup, by SD reset and by restart. No motion, no output.
- Covered waits: `TEMPERATURE_WAIT` (used by the `M109` macro and the probe-nozzle
  preheat) and `heaters._wait_for_temperature` (used by `M190` and vendor `M99109`).
- On a stop request the wait raises
  `gcode.error("Print cancellation requested; stopped while heating <heater>")` and
  records `stop_point` with phase `heating_<heater>`.
- Without a stop request, behaviour is identical to the retained vendor loops,
  including shutdown and vendor `quick_stop_flag` exits and the temperature reports.
- With openACE/AFC present, the wrappers defer entirely to the vendor implementation.

### 4. START_PRINT stop points

Positions refer to `config/live/macros.cfg` `[gcode_macro START_PRINT]`.

| Phase | Position | Machine state when stopped |
|---|---|---|
| `start_admitted` | after `_WMP_RECOVERY_JOB_BEGIN` block, before the first heater target | nothing moved or heated |
| `heating_<probe heater>` | inside `TEMPERATURE_WAIT` probe preheat | not homed by this job; heaters turned off by cleanup |
| `before_homing` | before `G28 P{probe_tool}` | not homed by this job |
| `homed` | after `G28`, before `M190` | homed; probe head attached and locked |
| `heating_heater_bed` | inside the `M190` wait | as `homed` |
| `before_mesh` | after `M190`, before the mesh block | as `homed` |
| `mesh_saved` | after `M118 START_PRINT adaptive_mesh` (mesh saved) | homed; mesh for this job saved; probe head attached |
| `before_initial_tool` | after `M400`, before `T{INITIAL_TOOL}` | as `mesh_saved`; no tool change started |
| `initial_tool_ready` | after `T{INITIAL_TOOL}`, before the purge travel | initial head attached and locked |
| `heating_<print heater>` | inside `M109` at the purge position | initial head at X0 Y70 Z7; nothing extruded |
| `purged` | after the purge block, before `_WMP_PRINT_CONTEXT_COMMIT` | purge line extruded; print body not started |

No stop point is placed between `G1 Z0.4` and the end of the purge line, or inside
`T{INITIAL_TOOL}` (tool-change stop points belong to the Dock/Take design).

Interruptible-wait regions in `START_PRINT`:

- `_WMP_STOP_WAITS ENABLE=1` immediately after the `start_admitted` stop point.
- `_WMP_STOP_WAITS ENABLE=0` immediately before the first `T{INITIAL_TOOL}`;
  `ENABLE=1` immediately after it (covers `M109` at the purge position).
- `_WMP_STOP_WAITS ENABLE=0` before the second `T{INITIAL_TOOL}` (after the purge)
  and it stays closed for the rest of the job.

`G28` and `BED_MESH_CALIBRATE` lie inside the open region but contain no covered
wait; in this phase they run to completion (see Later extensions).

Stopping before `_WMP_PRINT_CONTEXT_COMMIT` leaves the recovery context uncommitted;
the existing cleanup invalidation handles uncommitted context.

### 5. Result reporting

The cancellation record carries the optional `stop_point` field. The native
cancellation progress panel shows its label as a single line under the completed
"stopping" stage ("Stopped at: <label>"). No other UI change.

### 6. Firmware re-baseline

The `START_PRINT` stop-point lines are vendor-macro patches. They are listed with the
other `config/live` patches and re-checked on each firmware re-baseline. A test
asserts that each phase in the table appears exactly once in the rendered macro and in
the table order.

## Later extensions (not built in this phase)

Homing and mesh probing are retained vendor Python (`klippy/extras/homing.py`,
`klippy/extras/probe.py`), not compiled modules. A later step can call
`check_stop_point` from wrappers at these boundaries:

- Mesh probing: between probe points in the probe-points loop (where the vendor
  already checks `quick_stop_flag`, `probe.py:481`) and between samples
  (`probe.py:344`). The head is raised to `horizontal_move_z`, attached and at a known
  position.
- Homing: between axes and between homing phases of `G28 P…`. Not inside a homing
  move, which waits for an MCU endstop or probe trigger.

Requirements for that step: a stop inside `BED_MESH_CALIBRATE` must not save a
partial mesh as the job mesh; a stop inside homing leaves the axis unhomed and records
that. These need their own stop-point tables and tests, and must be re-checked on
each firmware re-baseline because they wrap vendor Python.

## Constraints

- Retained vendor 1.1.13 dispatcher, SD worker and heater implementations under
  `analysis/fw_1.1.13_payload` are the reference for behaviour and tests.
- Cancellation journal version 3 adds the optional `stop_point` field. The reader
  (`_restore_print_cancel`, `klipper_extras/wm_material.py:2919`) requires an exact
  key set per version, so an extra key in version 2 would make the record unreadable.
  Versions 1 and 2 stay readable. After a rollback to r4, a version 3 record reads as
  unreadable and remains a hold; this matches the version 2 rollback rule.
- Macro text must pass `tools/validate_klipper_config.py` (see
  `memory: wondermaker-macro-gotchas`: `#` stripping, stale sub-macro variables).
- No printer contact for development or testing. Tests use the existing host models:
  `HeaterModel` template rendering (`tests/test_config_macros.py`) and the fake-reactor
  `wm_material` fixtures (`legacy_cancel_routes`, `guarded_legacy_dispatch`,
  `managed_cancel_cleanup`).

## Tests required

- Rendered `START_PRINT` contains every stop point once, in table order, and none in
  the excluded ranges.
- `_WMP_STOP_POINT` with no stop request: no output, no state change.
- With a pending print cancel bound to the running job: raises, records `stop_point`,
  and the retained dispatcher executes no later line of the script.
- Stop request for a different file handle, session, or with openACE/AFC present:
  no-op.
- Unknown `PHASE`: error, not a pass.
- Heat waits: stop request raised during the wait exits within one iteration and
  records `heating_<heater>`; without a request, temperature reports and exit
  conditions match the vendor loop.
- Heat waits outside an open region (including `_WAIT_TOOL_TEMPERATURE` inside
  `T{INITIAL_TOOL}` and a mid-print `Tn`) do not raise with a stop request pending.
- Region state does not survive a changed SD file handle, session, SD reset or
  restart; rendered `START_PRINT` closes the region around both `T{INITIAL_TOOL}`.
- End to end with the retained SD worker: cancel during the probe preheat, during the
  `M190` wait, and during the print-nozzle `M109`. In each case the SD error path
  coalesces with the live intent, cleanup runs once with no added motion, and no
  `T{INITIAL_TOOL}` or purge command is dispatched.
- Restart with a pending record restores unknown and `_WMP_STOP_POINT` is a no-op.

## Left to the builder

- How the heat-wait wrappers are installed (command re-registration versus wrapping
  `PrinterHeaters._wait_for_temperature`), provided the vendor behaviour is preserved
  without a stop request.
- Exact wording of the labels in the stop-point table.
- Whether `start_admitted` sits before or after `_WMP_CASE_LIGHT_PRINT_START`.
