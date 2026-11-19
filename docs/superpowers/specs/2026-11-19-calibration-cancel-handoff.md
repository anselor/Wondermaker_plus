# Handoff: prompt cancel for Maintenance calibration

Status: not started. Design input for a later agent. Brainstorm with the owner
and write a spec before building (see "Open decisions").

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

The calibration side (branch `feature/brush-nozzle-scrub-r4`, not merged):

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

## Open decisions (owner)

1. Where the work lands: on `feature/brush-nozzle-scrub-r4`, or in r4's
   safe-cancel work with the scrub branch adding only its own stop points.
2. Whether stop points inside vendor stages other than the offset stage (bed
   mesh, vibration measurement, PID) are in scope now.
3. The text for each stop location on the result page.

## Verification on the printer

- Cancel during XY homing: stops before Z homing.
- Cancel during the scrub's head change: the change completes, the head is
  parked, nothing heats or moves further.
- Cancel during a heat wait: ends within about one second.
- Cancel during offset measurement: stops before the next head; offsets of
  heads already measured follow the existing restore rules.
- Heaters off and the bed not dropped in every case.
