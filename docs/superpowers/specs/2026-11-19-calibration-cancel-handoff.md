# Handoff: prompt cancel for Maintenance calibration

Status: requested local implementation is present on `work/r4-print-time-fixes`,
based on r4; attended qualification is pending.
The owner has confirmed the scope below. Backend ingress and safe command/scrub,
XY-axis, pre-Z and between-touch boundaries are implemented locally. UI
delivery is implemented locally for the shared ticket-bound Maintenance and
setup-guide worker, including measurement and held scrub/re-check states.
Heat/mesh/PID/shaper boundaries and durable completed-type checkpoints are
locally implemented. Shared tool-service macro boundaries now stop after
homing, before/after complete docking and around wiping. Touchscreen Home now uses the same bound owner/Cancel transport and a
homing-specific hold outcome. Active filament load/unload now participates in
the same boundary observer through its existing Cancel endpoint, with
head/frame-consistent service stops. Otherwise-unowned top-level G28 now uses
the same Home owner and dialog; nested commands keep their existing owner.
Standalone mount/dock now uses the shared observer and procedure Stop control
(see `2026-11-19-standalone-toolhead-cancel.md`). Attended physical qualification remains open. No printer installation while
the nine-hour print is active.

## Problem

The owner pressed CANCEL early in a wire-brush offset calibration (Maintenance
page, Accurate Alignment Mode, Wire brush). The printer then completed XY
homing and Z homing, docked head 3, picked up head 1, heated it, moved it to
the scrub position at the front, returned head 1 to its dock, and only then
stopped.

Owner requirement, verbatim: "XY and Z homing can definitely stop between
them. And every stage of the calibration could have stopped as well."

## Evidence (printer klippy.log, 2026-11-19, printer clock CST)

| Time | Event |
|---|---|
| 14:04:32 | XY homing starts ("XY homing: preliminary Y home, then X home") |
| ~14:04:31 | A screen `gcode/script` request is queued; Moonraker logs it pending 60 s at 14:05:31 and 14:05:34 |
| 14:04:58-14:05:06 | Head 3 re-picked during homing |
| 14:05:11-14:05:25 | Z homing (stall sensor) |
| 14:05:26 | Head 1 heater to 160 °C: start of `_WMP_SCRUB_HEAD T=0` |
| 14:05:43-14:05:51 | Head 3 unlocked, head 1 picked up |
| ~14:05:52 | Move to the scrub position |
| 14:06:00-14:06:03 | Head 1 returned to its dock (`_WMP_SCRUB_END` park); run stops |

## Causes

1. The screen sends its cancel as G-code. Klipper runs G-code commands one at
   a time, so the cancel waits behind every command already running or queued
   (homing, then `_WMP_SCRUB_HEAD`).
2. Nothing checks for a cancel at the natural boundaries:
   - between XY and Z homing;
   - between the steps of `_WMP_SCRUB_HEAD`, a single command that heats,
     lowers the bed, changes the head and moves to the front
     (`klipper_extras/wmp_nozzle_scrub.py`, `cmd_head`);
   - between the vendor worker's stages (bed level, vibration, PID, offsets)
     and between heads of `RAPID_MODE` / `CALIBRATE_OFFSET_ALL_RAPID_MODE`
     (`config/live/offset_calibrate.cfg`);
   - between touches of the tool-setter probe loop
     (`klipper_extras/wmp_tool_probe.py`, `run_probe`).

## Existing building blocks

Upstream r4 has a stop mechanism for print cancel:

- `klipper_extras/wmp_stop_points.py`: `_WMP_STOP_POINT PHASE=<name>` raises a
  G-code error at safe places when a stop is requested; `_WMP_STOP_WAITS
  ENABLE=0|1` makes vendor heat waits end within one poll; a bed-mesh hook
  stops mesh probing. Used in `config/live/macros.cfg` (START_PRINT phases).
- `klipper_extras/wmp_print_cancel.py`: the print cancel request and its
  binding to the open job (`stop_requested()` reads it).
- `klipper_extras/wm_material.py`: webhooks endpoints
  (`register_endpoint("wmp/print/cancel_review", ...)` and others). A webhooks
  request is handled by the reactor while a G-code command waits on motion or
  a dwell, so a flag set through an endpoint is visible to a running command at
  its next check.

The calibration side (merged into local r4 before this work):

- Native flow: `client-preload/unified-ui/native/nozzle_scrub_flow.hpp`
  (`cancel()`, held states, `_WMP_SCRUB_END` queued as G-code; a restore before
  END in Recheck, Remeasure and a repeat scrub).
- The flow holds the vendor worker at its final park send (hook at 0x4b847c,
  `nozzle_scrub_coordinator.hpp`, `bootstrap.cpp`); the worker's other sends
  pass through the same sender hook.
- Calibration attempt and progress: `klipper_extras/wmp_calibration.py`,
  `wmp_calibration_progress.py` (phases `homing`, `mounting`, `position`,
  `height`, `docking`).
- As-built reference: `docs/nozzle-scrub.md`. Spec of the re-check:
  `docs/superpowers/specs/2026-11-18-nozzle-recheck-design.md`.

## Required behaviour

- CANCEL takes effect at the next safe boundary, not after the queued work.
- Boundaries at least: between XY and Z homing; before each step of the scrub
  head command (heat, bed lowering, head change, move to the scrub position);
  between vendor stages; between heads of the offset measurement; between
  touches of the probe loop; heat waits end within one poll.
- A stop never interrupts a head change in progress (pickup/dock macros are
  atomic). A head left attached is parked; every heater the run turned on is
  turned off.
- Offsets: the existing rules hold (snapshot restore in Recheck, Remeasure and
  a repeat scrub; earlier-stage results of a combined run are saved as today).
- Once a cancel is requested, no further vendor worker command is forwarded;
  the worker ends on its failure path (quick_stop, no SAVE_CONFIG unless the
  early-save rule already applies).
- The result page states where the run stopped (r4 has stop-point labels for
  print cancel in `wmp_stop_points.py` `STOP_POINTS`).

## Constraints

- Do not edit vendor files (`tools_calibrate_core.py`, `tools_calibrate.py`).
- Never disable motors as a stop action: with the bed raised, M84, an e-stop
  or a Klipper restart drops the bed about 290 mm.
- Never send the CELL board a Katapult/bootloader request.
- C++11, `-Wall -Wextra -Werror` for native code; screen sizing rules in
  `docs/nozzle-scrub.md` (touch targets at least 64 x 110 px, text at least
  22 px).
- New commands, endpoints and status fields are registered in
  `client-preload/unified-ui/native/backend_contract.json`; new backend
  modules in `tools/components/material.py` `HELPERS` and
  `client-preload/unified-ui/native/runtime_inputs.py`; the sealed screen
  package is rebuilt (`docs/native-screen-packaging.md`).

## Confirmed scope

- Work lands on `work/r4-print-time-fixes` for later review and integration to r4.
- General homing, offset calibration, bed mesh, vibration, PID and shared tool
  service operations are in scope. Check between physical operations, including
  between axis homing stages; ordinary Cancel must not disable motors.
- Coupling/lock/unlock strokes finish before Cancel. A full multi-operation tool
  change should not be treated as one indivisible operation indefinitely.
- Completed calibration types must be durably retained before the next type;
  incomplete results are not marked complete or saved as successful.
- Use concise physical stop locations on the result page. Exact labels can be
  resolved during implementation against the real motion sequence.

## Local backend foundation

`wmp/calibration/cancel` accepts `session`, `request`, and decimal-string `ticket`
for the currently admitted ticket-bound attempt. It records intent on the
reactor; it does not acquire G-code ownership or issue hardware commands.
Repeated requests are idempotent. Stale bindings, other filament owners, a save
in progress and non-cancelled failed attempts are refused.

The sequenced command wrapper checks before dispatch and after the running
command returns. Scrub checks before each constituent script and after each
phase. Existing tool-selection scripts finish before the following check;
owned-heater failure cleanup and the queued-stage failure latch are retained.
The pre-existing single early save after a failed offset stage is retained;
cancellation does not authorize saving an incomplete type as successful.
The optional `calibration_cancel_protocol=2` advertises pre-admission intent,
serialized cleanup for held runs and the matching UI receipt semantics. The
native UI uses a dedicated bounded HTTP worker/connection for cancellation,
without adding polling, retrying or falling back to queued G-code. The header
CANCEL remains available while the Maintenance worker owns a cancelable run,
including nozzle measurement. Once requested, subsequent worker stages are
withheld. Its final SAVE_CONFIG is only forwarded when fresh, bound backend
status confirms complete cleanup and the existing early-save permission for
completed earlier types; uncertain delivery never permits an ordinary save.
Bound Maintenance runs now checkpoint completed mesh, vibration and PID
results between types; see `2026-11-19-calibration-checkpoints.md`. Setup-guide Start now shares that same worker and checkpoint owner; physical
qualification remains open (see `2026-11-19-setup-shared-calibration.md`).
The first stage is still allowed to consume a
pre-cancelled ticket without executing hardware. The reviewed park send clears
the vendor pairing-failed byte to avoid its quick-stop branch; the backend's
failure, cleanup result and save restrictions remain authoritative. Existing
worker emulation verifies that park-branch behavior.

A matching complete cleanup receipt, not HTTP acceptance or worker return,
permits the result to say cancelled. Incomplete cleanup reports its reason;
unknown delivery waits for status. DONE waits for the worker to return. A fresh
new Klipper session retires an unconfirmed old cancellation for retry purposes.
Prepare-screen cancellation remains local and sends no request.

Heater and TEMPERATURE_WAIT loops now observe bound calibration cancellation
at the existing one-second poll. Only the executing command greenlet is eligible;
unrelated callbacks, replaced attempts and cleanup retain vendor behavior.
Mesh cancellation is checked after horizontal retraction, before the next point,
so the mesh finalize/save callback cannot publish a partial mesh. Retained vendor
PID code restores its prior controller when the wait raises a command error;
local tests cover that path and verify no PID result publication. Printer timing,
controller restoration and cleanup still require attended qualification.

Vibration calibration now uses a command-bound guard around the retained factory
or backported `_run_test`. It checks before travel, dwell and each queued motion
segment, and before/after recording completion so cancellation at the final move
does not publish calibration results. Already queued motion drains normally;
no emergency stop, motor disable or forced coordinate is used. The guard closes
unfinished accelerometer clients, restores prior velocity/acceleration/cruise
limits with readback, and restores the exact prior per-axis shaping state,
including an axis that was disabled before the test. Its temporary hooks are
removed on every exit, and other greenlets retain their original calls. Unknown
restoration or recording teardown produces incomplete cleanup and prevents an
automatic dock. Both executor versions are exercised from their actual source
in local tests; device cancellation latency and motion remain unqualified.
The post-measurement fitting helper now uses a bound child-process owner for
both factory and backport. It checks cancellation at the existing 100 ms wait
poll, reads a ready result before waiting for child exit (including large pipe
payloads), and checks again before returning it. Cancellation terminates and
reaps the child, with kill fallback, and closes both pipe ends; unknown teardown
marks cleanup incomplete. CLI and other-greenlet calls retain the original
helper. It creates no polling or fitting work while idle. Local tests exercise
actual child processes, remote errors, a child exiting without a result,
large/list/scalar results and a failed terminate request. Physical/UI latency
remains unqualified. Bound Maintenance stages now roll back failed-type pending
config and partial runtime shaper axes through the checkpoint owner. A partial
vibration type is not marked completed or persisted; foreign edits retain their
ownership.

The operation-entry inventory and its explicit exclusions are maintained in
`2026-11-19-operation-cancel-ownership-audit.md`; do not interpret an unbound
console calibration as a ticket-bound Maintenance attempt. Attended physical
qualification remains open. Standalone mount/dock request ownership/UI is documented in
`2026-11-19-standalone-toolhead-cancel.md`. Top-level G28 is
covered by `2026-11-19-raw-home-ownership.md`.
Setup-guide Start now enters the shared ticket-bound Maintenance worker; its
legacy workers are withheld. General operation ownership and cross-operation races
remain part of that qualification; do not infer full coverage from the new
Maintenance controls alone.

Cancellation cleanup now belongs to the unwound command owner. It cools the
owned heaters, restores the attempt's initial stored offsets when the offset
stage began, verifies their readback, and waits for admitted motion to complete.
It only calls the shared PARK_CURRENT_TOOL path when XYZ and Z reference are
valid, physical attachment agrees with the saved head, and coupling faults are
clear. After docking it verifies both an empty carriage and the saved coupling
state. It never homes, forces coordinates, disables motors, or restarts for
cleanup. Unknown state leaves the head in place and publishes an incomplete
result with the reason. Repeated requests cannot replay cleanup; a later attempt
cannot consume an earlier cleanup. An unchanged/empty carriage still waits for
any admitted travel. `calibration_attempt.cancel_cleanup` reports state, offsets,
park and error; the scrub status ends only for complete cleanup. UI interpretation
is implemented for ticket-bound Maintenance; attended verification remains required.

`check_operation_boundary` shares the live owner checks between calibration and
print operations. XY checks run before and after native Y/X homing returns and
between reference travel/confirmation moves. Interrupted XY leaves Y unverified
and preserves Z. `_WMP_OPERATION_STOP_POINT` runs before full/explicit Z homing
and before the Z macro's positioning, outside the native G28 error handler.
Tool-setter probes check before starting and before each sample. An in-flight
sample finishes and retracts before a pending stop is observed at the next
sample; the open multi-probe session ends once. Real device behavior still needs
attended verification.
In particular, do not add a command error inside the stock G28 handler: it calls
`stepper_enable.motor_off()` on command errors. General homing needs a separate
cooperative unwind design that preserves the bed's holding torque.

## Verification on the printer

- Cancel during XY homing: stops before Z homing.
- Cancel during the scrub's head change: the change completes, the head is
  parked, nothing heats or moves further.
- Cancel during a heat wait: ends within about one second.
- Cancel during offset measurement: stops before the next head; offsets of
  heads already measured follow the existing restore rules.
- Heaters off and the bed not dropped in every case.
