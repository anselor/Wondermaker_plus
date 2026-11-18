# Safe-cancel follow-ups — 2026-11-18

Local R4 was fast-forwarded from `6e5510e` to the qualified `11d5c59`, retaining
seven commits because the follow-up branch was already based on that tip.
Nothing was pushed. Follow-up qualification uses
`qualification/safe-cancel-followups-r4`; the source branches remain unchanged.

## Integrated fixes

- `fix/quick-stop-flag`, source `0d36a18`, integrated as `b289692`.
  The retained vendor `webhooks.py` sets `printer.quick_stop_flag`, and vendor
  G-code dispatch reads that field. The fix corrects guards that read the flag
  from the G-code object instead. The coupling conflict was resolved retaining
  the qualified ordinary-Stop finish-stroke behavior. The newer cancellation
  classification guard and its two test fixtures were also adapted to the
  printer field during integration.
- `feature/safe-cancel-followups`, source `3264372`, integrated as `0561336`.
  The bed-mesh helper checks cancellation before the next XY point, after the
  vendor queues its Z lift. Normal cancellation drains that queued lift before
  cleanup. It does not interrupt a probe touch or wrap G28. Partial results do
  not reach the mesh finalize/save callback. A chamber-wait integration test
  exercises the existing chamber preparation implementation.

These backend-only changes use the existing screen artifact
`935306b2b9ad11722926f00e234389f6e8614b5435a6be3816fe1308bba768f2`.
Compiled source hashes and the artifact hash were verified unchanged before
refreshing runtime dependency hashes and resealing the source-bound package.
There are no new screen layouts.

## Validation

438 targeted tests passed: stop points, retained vendor probe execution,
cancellation outcome classification, coupling, pickup/dock settling and cleanup,
failure retry, tool-change pause, fixed-corner homing, identification and
configuration-save guards. This includes correcting the tests to set the actual
printer quick-stop field. Another 144 delivery/package checks passed.

The backend was installed on the idle printer and Klipper restarted. Guarded
G28 completed in 48.238 seconds with genuine XYZ homing and Head 3 attached.

A temporary non-extruding G-code file opened the managed stop region and ran
`BED_MESH_CALIBRATE` over a bounded 100–200 mm square, using 5×5 points and a
5 mm horizontal move height. Cancellation was requested after the first probe
point began. The final result was:

- Stop recorded as `mesh_probing`, `bed mesh, 1 of 25 points measured`.
- Print history `cancelled`; cancellation cleanup complete; no later command ran.
- No partial profile; saved profile dictionary and `printer.cfg` unchanged.
- Head 3 confirmed attached; fail_flag zero; pause clear.
- Zero extrusion and all heater targets zero throughout.
- Bed lowered to Z155 after probing; total cancellation observation 12.404 s,
  including finishing the probe point, draining queued motion and bed lowering.
- Temporary G-code removed. A previously active mesh profile, if any, restored
  without motion or configuration writes.

Raw evidence is retained locally in the ignored
`analysis/safe-cancel-followups/` directory. No vendor quick-stop request was
sent to moving hardware; that fix was checked against the exact vendor source
and with guard regression tests. Heated chamber behavior was tested on the host,
without heating the physical chamber. Neither follow-up is yet merged into R4.
