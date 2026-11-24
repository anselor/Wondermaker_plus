# Shared tool-service cancellation boundaries

Local implementation on `work/r4-print-time-fixes`; physical qualification pending.
Touchscreen Home ownership is documented in `2026-11-19-standalone-home-cancel.md`.
Active filament service ownership is documented in
`2026-11-19-filament-service-cancel-boundaries.md`. Standalone mount/dock Cancel
admission, execution and UI are documented in `2026-11-19-standalone-toolhead-cancel.md`. Raw top-level G28 ownership is covered by
`2026-11-19-raw-home-ownership.md`.

The shared change macros now observe the existing bound operation cancellation
at these points, after draining accepted moves with M400:

- After tool-service homing completes, before clearance/docking work.
- Before the current head's dock approach.
- After `_UNLOCK_TOOL` completes its unlock, retreat, release verification and
  `current_extruder=99` bookkeeping, before the next pickup.
- Before nozzle wiping, after attachment bookkeeping and the heater wait.
- After the complete nozzle-wipe macro returns.

Direct `PARK_CURRENT_TOOL` uses the same before-dock and completed-dock checks.
The checks call the existing `_WMP_OPERATION_STOP_POINT` command, which delegates
to the shared calibration/managed-print/filament/toolhead observer. No queued cancel command,
independent mount/dock implementation or global cancellation flag is added.
No observation is inserted into LOCK, UNLOCK, their confirmation macros, or
between unlock and the mandatory release retreat. Existing atomic actuator
semantics and sensor order are retained.

The macros omit the new checks for openACE/AFC. For standalone operation without
an executing calibration, managed-print, Home, filament or toolhead binding, the observer stays inert.
The calibration cleanup owner ignores its own pending Cancel while performing
its already-guarded park; a cleanup dock therefore does not cancel itself.
Doubtful attachment, invalid homing/Z reference or retained coupling faults
continue to prevent automatic cleanup motion.

Tests render the real macros, verify service ordering and M400 barriers,
exercise real bound calibration ingress/dispatch through each new stop label,
and check that coupling scopes contain no new stop instruction. Supervised
physical tests remain outstanding. Standalone service Cancel admission/UI now
share these same macro boundaries, as documented separately.

Local qualification: the final focused batch passed 23 tests; the matching
screen package passed 7 tests and its source seal is current. ARM candidate
build completed; native UI bytes remain identical because this change is in
the bound backend/config sources. The broader macro/calibration ingress/cleanup run finished with 591 passed,
2 skipped and 3 failures in the new wipe fixture (missing saved flow settings).
That fixture was corrected; the final 23-test focused run includes all three
formerly failing cases and passes. No production regression failed. No printer
installation or push.
