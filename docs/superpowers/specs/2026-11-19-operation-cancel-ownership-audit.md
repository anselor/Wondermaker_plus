# Operation cancellation ownership audit

Current acceptance policy and results are in
[the consolidated validation plan](../../validation/early-stop-consolidated-plan-2026-11-23.md).
The attended matrix below is historical; do not schedule another physical run
for each start path without first checking that plan's implementation/ownership
equivalence and existing evidence.

Scope: the local `work/r4-print-time-fixes` branch. This audit distinguishes a
request reaching an endpoint from its being observed at the next safe physical
boundary. It does not authorize printer installation or motion testing.

## Current entry points

| Entry point | Owner and intent | Observation / cleanup | Qualification |
| --- | --- | --- | --- |
| Managed print and print preparation | `wmp_print_cancel`, session/job/file/handle-bound review and out-of-band intent | Shared stage/heat/mesh checks and print cleanup; strokes/mandatory retreat stay atomic | Local implementations and prior cold-run tests exist; new cross-operation checks need attended verification |
| Maintenance calibration and setup-guide calibration | Shared `CalibrationCommands`, request/ticket/sequence; dedicated Cancel transport | Shared homing/tool/probe/heat/mesh/PID/vibration checks; owned heater/offset cleanup; completed-type checkpoints | Locally implemented; attended timing, hardware and final-save checks remain |
| Touchscreen Home and otherwise-unowned top-level G28 | Shared Home ticket/Cancel engine | Checks outside native G28 error handlers; drains/holds rather than motor-off or guessed park | Locally implemented; supervised stops remain |
| Filament load/unload | Material operation session/id/head and command-greenlet scope | Shared service/macro boundaries; own target cleanup and held frame; existing endpoint/control | Locally implemented; supervised service/paused tests remain |
| Standalone mount/dock | Material operation session/id/head/action, generation and executing greenlet | Shared motion macros and heat-wait observer; M400/hold without extra coupling or temperature change | Locally implemented (`62dc3a2`); physical qualification remains |
| Probe-editor preparation | `wmp/probe_editor/stop`, session/request | `_WMP_PROBE_PREPARE_CHECK` before/after macro stages; drains and aborts only its bound manual-probe helper | Local between-axis/native-G28, actor isolation and handoff tests pass; physical qualification remains |
| Probe-editor paper adjustment | Editor request/token/sequence, serialized JOG/ABORT/ACCEPT/DISCARD | Jog completes before the next editor command; ABORT addresses its helper | A discrete manual adjustment, not an unbounded command; retained editor semantics |
| PLR preparation | `wmp/recovery/stop`, session/recovery request | Existing runner consumes stop intent during preparation, not after continuation becomes a print | Bound nested XY and early queued-Start Stop locally implemented (12135f0); physical qualification remains |
| Ordinary paused-print Resume | Captured pause/file/head state; print controls own the job | Resume preparation/heat/return flow; service records must reconcile with the paused job | Owned waits and return boundaries locally implemented (8ebb687); physical qualification remains |
| Head identification / explicit assignment repair | `IdentificationCommands` request history and material/session/generation admission | Revalidates before commands and final atomic mapping publication; failure clears its mode without motion only while still owned | Request-bound Cancel, shared boundaries and native UI ingress implemented locally; physical qualification remains |
| Recovery reconciliation, saved-print retirement, settings and calibration save | Reviewed request/token and publication owner | Finite non-motion transaction; do not interrupt a file replacement midway | Reconciliation/atomic publication must finish or report its existing failed/unconfirmed transaction; no synthetic motion Cancel |
| openACE / AFC-owned operations | External manager | Shared standalone observer is deliberately inert | Never steal its request or apply standalone cleanup |

Primary sources: `wmp_stop_points.py`, `wmp_calibration.py`, `wmp_raw_homing.py`,
`wmp_filament_service.py`, `wmp_toolhead_service.py`, `wmp_probe_editor.py`,
`wmp_plr_review.py`, `wmp_paused_service.py`, `wmp_identification.py` and their
registered commands/endpoints in `wm_material.py` and `wmp_recovery.py`.

## Identification cleanup handoff defect

The existing command fence correctly rejected a barrier or saved-mode write
after the material/session/generation/manager changed. However, the session's
failure handler then called `invoke_shutdown` because that rejected cleanup
could not clear identification mode. Thus a retired request could still disable
the replacement owner's motors. The previous test covered no additional G-code,
but did not check this shutdown side effect.

The strengthened test reproduces that side effect for generation, session and
manager handoff. The fix adds an ownership callback to the session and checks it
before mode cleanup, after the command and readback, and before its shutdown
fallback. The managed adapter includes the exact session operation object in
its command/publication/cleanup authority. Replacement operations are not
rewritten by the old exception handler. Lost/unavailable authority leaves
`mode_cleanup=unconfirmed` and a message requiring inspection; it performs no
mode write, motion, retry, restart or shutdown under the replacement owner.

The original shutdown behavior remains for an owned, genuinely failed mode
clear. This change does not pretend that uncertain sensors or a failed mode
clear are successful cleanup. Tests retain that behavior, check request/object
replacement and loss during readback, and confirm no mapping/configuration
publication after a failed sequence.

Local identification commands/session/observation/transaction/PID-mapping batch:
183 passed. Physical qualification and the matching package proof remain in the
repair tracker. This is a cleanup-authority fix, not new identification Cancel.

## Remaining concrete gaps

### Head identification — locally implemented

The backend now accepts `wmp/identification/cancel` with the exact calibration
session and identification request. It latches intent only. A Stop arriving
before the queued Start is retired in the same bounded 128-request history;
that Start reports its cancelled receipt without running hardware or publishing.
The route is registered once by `BottomZ` and never initializes a controller in
response to a Stop.

An executing request binds the controller, operation, material object/session,
command generation, recovery owner and command greenlet. Shared homing/tool
boundaries observe the request only in that greenlet; unrelated callbacks cannot
consume it. Readiness and real faults precede cancellation. Coupling strokes
remain uninterrupted. After a stop, the request drains and holds rather than
starting another docking operation. If still owned, its identification mode is
cleared through the existing non-motion, verified cleanup. The operation remains
running while draining/clearing; its terminal cancelled receipt is published only
after both finish, so the UI cannot offer another Start during cleanup. A changed owner gets
no old cleanup or shutdown. A failed drain is failed/unconfirmed, never a claimed
successful stop. The existing shutdown behavior on a genuine owned mode-clear
failure is retained as a machine fault, not normal cancellation behavior.

The final pre-publication boundary checks cancellation. Once the finite atomic
mapping publication begins, the endpoint refuses late cancellation; no partial
mapping is published on a prior Stop. Cancelled status is additive to protocol 2,
with `cancel_protocol=1`, retained phase, intent and publication fields.

The native page now changes START to CANCEL while its own request is pending,
including before backend dispatch. It reuses the calibration cancel worker's
independent bounded HTTP connection with a separately validated identification
payload and fixed endpoint. No additional thread, polling loop, G-code fallback
or retry is added. A delivery acknowledgement is not a stopped result: only a
fresh matching backend receipt settles the flow. Unconfirmed delivery stays
visible until status resolves it. The existing WebSocket Start sender remains
unchanged. Header checks cover active, cancelling and cancelled states in both
regular and setup pages. The regular cancelled result uses DONE for the exit;
the mandatory setup page retains START to retry identification rather than
claiming that setup completed. Supervised printer qualification remains pending.

### Probe preparation — locally implemented

Before this change, its out-of-band endpoint recorded `stop_requested`, and
macro checks surrounded stages. `CalibrationCommands.check_cancel()` returned
without an executing calibration attempt, and the shared observer had no
probe-editor adapter. A regression reproduced continuing past the Y boundary
after a pending preparation Stop, both before and after helper registration.

The executing preparation now carries its session, request, command greenlet,
material/session/generation, manager identities and exact retained receipt to the
shared observer. Idle or foreign greenlets do not consume its Stop. A handoff
unwinds the old stack at its next boundary without old-owner cleanup, including
when an external manager appears. Exact expected-stop reporting remains bound
to the same scope; real faults and same-text replacement exceptions are reported.

Cleanup revalidates before and after the direct motion drain, before helper
abort, and after finalization. An owned helper captured during exception unwind
uses the existing failed-preparation abort method; a normally returned helper
uses its bound editing abort. Neither path dispatches global ABORT, disables
motors or guesses position. Lost ownership cannot rewrite the replacement result.
Retained native G28 tests stop after Y or X outside its motor-off error handler.
Supervised printer qualification remains pending.

### PLR — nested homing implemented; early ingress pending

Recovery preparation now binds its request, command greenlet, material/session,
command generation, controller/submission, runner and exact record, pending
worker and printer owners. The shared boundary observer checks that executing
scope without instantiating idle components. The bundled `G28 X Y` stage supplies
its existing full frame/admission guard to the observer; normal travel and
homing ordering are unchanged. Stop is observed after complete native Y or X
homing, outside native G28's motor-off error handler. An interrupted Y reference
stays unverified and Z stays at the established bottom reference. Partial-stage
recovery remains unknown, rather than claiming that the reference completed.

`RecoveryAttempt.run()` now keeps its own record and immutable request across
callbacks, verification and persistence. A replaced record is neither rewritten
nor persisted by the old stack, and the old stack cannot clear its busy flag.
Lifecycle cleanup checks the same ownership before disarming, accounting,
heater-off commands/readback and cleanup publication. Disarm preserves a
replacement worker/timer; command-result handling preserves a new submission.
On ownership loss the last owned journal remains diagnostic evidence; there is
no old-owner cleanup or synthetic completion. Existing same-owner failures
still retain unknown outcomes and owned heater-only cleanup.

The existing journal schema is unchanged. A stop's phase is retained in the
error message, and the stopped partial record restores without replay. Local
regressions reproduced five failures before this change: nested Y-to-X Stop and
record replacement during dispatch, verification, persistence or exception
unwind. Recovery checks pass (475, two skips); related homing/owner checks pass
(350), with five focused final stop/journal-restoration checks.

Early Continue Stop now uses the existing bounded server review ticket. Before
G-code dispatch, the native worker cancels its local review and never sends
Continue. After dispatch, backends advertising `recovery_early_stop_protocol=1`
accept the exact reviewed ticket while Continue is queued or reviewing, before
physical admission. Existing active legacy Stop remains supported. No new
request ledger, polling timer, worker thread, motion, heating or journal schema
is introduced. Duplicate Stop is idempotent; a superseded/consumed/foreign ticket
cannot cancel another request. A new explicit selection receives a fresh ticket.

Cancelled-before-preparation outcomes are submission results, not fabricated
physical attempt receipts. The previous recovery journal remains unchanged.
Only a matching submission confirms remote early cancellation; a lost command
or Stop acknowledgement is not success and is never automatically retried.
The screen offers STOP during review/early dispatch and DONE for confirmed early
cancellation, without showing preparation as running. Backend recovery checks
pass (482, two skips), plus a separate repeated-Stop/new-selection regression.
Native worker tests cover blocked review/dispatch and lost acknowledgements.

ARM build and matching reviewed delivery export passed; package/material
installer checks passed (248). The screen artifact is
`82da7e1ac044b5b7b2c88d87c9904e62471ad6064702861c793d0a22ae125687`.

**Remaining:** supervised printer qualification and full tool-stage timing
qualification. No installation is implied.

### Ordinary Resume — command-owned heater waits and safe boundaries

Ordinary `RESUME`, nested `M24`, and the stock screen's Resume preheat use the
existing command-lifetime observer. A separate StopPoints scope now binds waits
to the executing actor, material object, printer session, command generation,
SD object, exact open handle, stats object and filename. Progress telemetry
remains informational. Tool-change retry and external-manager paths retain their
existing owners. No idle timer, polling thread or admission shortcut is added.

Bed/nozzle waits use the existing interruptible vendor wait loops, and scope
ownership is checked at each poll. The existing same-job print-cancel binding
may stop the scope even though accepted Cancel fences command generations.
Unrelated actor callbacks retain vendor wait semantics. A handoff aborts the old
Resume without applying cleanup to the replacement owner. The scope clears in a
pointer-checked finally block on success, refusal, Cancel or heater failure; a
previous print-start wait region is not overwritten.

The Resume macro observes Stop after heating, before/after wiping, before the
paused-position return and after that return before SD continuation. Buffered
motion may finish; no mid-stroke cancellation, guessed parking, motor disable or
new cleanup path is introduced. Existing post-heating paused-service validation
and E restoration remain in place.

Local tests exercise bed/nozzle Stop within one poll, no continuation after
Stop, changed session/file/handle/generation/manager/material, foreign actors,
heater failure cleanup, normal return, and each macro stop point. Macro rendering
checks cover serviced/unserviced wipe and existing physical heater routing.
Shared stop-point/pause regressions passed (153), each of the five Resume
boundaries passed, rendered Resume macros passed (6), and material Resume/Cancel
regressions passed (290). Matching screen-package/material installer checks
passed (248). Native source hashes and ARM artifact were unchanged; only the
backend/configuration delivery inputs were refreshed. Supervised printer
verification remains required; nothing has been installed.

## Attended cancellation qualification matrix

This is the remaining hardware acceptance plan, not authorization to run it.
The earlier cold print/mesh qualification does not qualify every operation below.
All rows remain pending on a matching backend/configuration/screen installation.
Use cold/non-extruding cases first; heat, vibration and PID are separate runs.
Keep the exact G-code/configuration and collected receipts with each result.

For every run, capture the request identity/session/ticket, intent acknowledgement,
observed boundary, cleanup completion, saved configuration, mounted-head/lock
readback, heater targets and final job/operation state. Record the three times
separately: an accepted Stop is not a completed physical stop. Heater waits must
observe within their next existing poll; motion may finish its admitted move or
mandatory coupling retreat before the next safe boundary. Confirm no later
stage or SD-body marker executes. Observe continued Z holding without commanding
an unreferenced move or disabling a motor. No M84, emergency stop or restart is
an ordinary-cancellation success path. A real fault remains a fault.

| Operation | Stop opportunities to exercise | Local evidence to retain | Attended acceptance still pending |
| --- | --- | --- | --- |
| Home / otherwise-unowned G28 | Queued Start; after Y reference, between XY and Z, before Z positioning; repeat Stop | `test_raw_homing.py`, `test_homing_cancel_boundaries.py`, `test_xy_homing.py`; stop is outside native G28's motor-off exception handler | No next axis/stage after its boundary; no guessed reference/park; Z remains held; completed stroke drains |
| Standalone mount and dock | Before homing, before docking, after verified docking, before mounting/wiping, after mounting/wiping | Toolhead-service tests in `test_wm_material.py`; shared operation macro/homing checks | Same reference used for dock/mount; coupling and required retreat finish; attachment/lock outcome is verified; no extra tool change |
| Filament load/unload | Queued request, homing/dock/mount boundaries, heater wait, feed/purge boundaries | Filament-service scope tests in `test_wm_material.py`; vendor wait tests in `test_stop_points.py` | Only owned heater cleanup; no continued extrusion, stale recipe or new service after Stop; mounted/locked head and held frame reported |
| Probe-editor preparation | Before/after each preparation macro; between native home axes; manual-helper capture | `test_probe_editor_flow.py`, probe preparation tests in `test_wm_material.py` | Only its manual helper is aborted; no later positioning; ABORT/ACCEPT in paper adjustment remains a discrete serialized action |
| Guided scrub / offset calibration | Queued worker, each selected head's home/dock/mount/preheat/scrub/probe/retreat, re-check prompt and reheat | `test_calibration_cancel_ingress.py`, `test_calibration_cancel_cleanup.py`, brush handoff spec and owned heater/offset tests | CANCEL stays available while cancellable; correct head/lock/targets after Stop; saved prior offsets retained; partial offsets not published; timeout/restore failure remains unconfirmed |
| Bed mesh calibration | Heat wait, between completed probe points, before finalize | `test_bound_calibration_mesh_cancel_retracts_and_never_finalizes`; retained probe helper regression | Admitted lift drains before stopping; no next XY probe; no partial mesh saved; earlier completed calibration types retained |
| Vibration calibration | Between axes/sweeps and during calculation wait | `test_calibration_resonance_stop.py` | No later sweep; calculation child is terminated/reaped when owned; partial shaper result not saved; earlier completed types retained |
| PID calibration | Preheat and retained PID control loop; before result publication | `test_vendor_pid_cancel_restores_control_and_does_not_write_results`, PID mapping tests | Prior control restored, owned heater targets cleaned up; incomplete PID not saved; completed earlier types retained |
| Head identification / repair | Before queued Start; each shared motion boundary; before final publication | Identification command/session/native tests; 128-request retirement history | No partial mapping publish; identification mode cleared only while owned; no replacement-owner shutdown; atomic publication finishes once admitted |
| PLR Continue | Local review, dispatched/queued ticket, consumed-ticket review, nested XY, each preparation stage | `test_recovery_attempt.py`, recovery tests in `test_wm_material.py`, native recovery-worker tests | Early Stop moves/heats nothing and leaves prior journal unchanged; active Stop has no continuation replay; after SD continuation use ordinary print controls |
| Ordinary Resume | Stock-screen preheat, bed/nozzle waits, after heating, before/after wipe, before/after paused return | Resume tests in `test_stop_points.py`, `test_resume_progress.py`, rendered `RESUME` macro tests | No return/SD continuation beyond observed Stop; frame remains held; full filename/job binding retained; normal subsequent Resume requires fresh valid paused state |
| Multi-type calibration | Complete one type, cancel/fail the next; cancel within a type; final normal save/restart | `test_calibration_checkpoints.py`, early-save/result tests | Every completed type is durably saved between types; incomplete type discarded/restored; expected restart shows progress and durable receipt, not a false failed-save result |

Cross-cutting host regressions already cover wrong/stale identities, duplicates,
replaced requests/sessions/material managers, actor isolation, lost delivery
acknowledgements, and cleanup ownership. Attended checks must additionally cover
rapid repeated button presses, visible disabled/cancelling/terminal states, and
correct DONE/CLOSE behavior. External openACE/AFC ownership must retain its own
workflow; the standalone observer cannot steal its operation.

A row passes only with its requested boundary observed, final physical state
confirmed and saved-result comparison recorded. If the boundary cannot be reached
or the outcome is ambiguous, record that case as unverified, not passed. Keep
unrelated USB disconnect and intermittent extrusion timing investigations outside
this cancellation acceptance result.

## Combined-suite harness follow-up

The first combined regression exposed two legacy test-harness assumptions:

- The offset-snapshot busy-command test used G29 solely to keep a command active.
  G29 now also requires an actual mesh checkpoint/configuration producer, which
  that small fixture does not provide. It now holds M400 instead, preserving
  the assertion that nested offset restore is refused while another command
  executes. The real mesh checkpoint producer remains tested separately.
- The persistent print-recovery template interpreter did not recognize
  `_WMP_OPERATION_STOP_POINT`, so it tried to render a nonexistent macro. It now
  exposes an explicit boundary callback, analogous to its existing probe-prepare
  callback. Added tests inject stops before Z homing and positioning and assert
  no later command and no synthetic printer shutdown.

These are test-only changes, not relaxed backend checks. Offset/checkpoint tests
pass (57); print-recovery/homing tests pass (104, two skips). The combined run's
original failures are retained for an honest final disposition. A separate
missing factory-settings fixture was restored from the existing local 1.1.13
extraction and its test passed; no printer or production-code change was needed.
The full combined regression remains in progress at this checkpoint.

Further combined-suite assertions were updated without changing production:

- The exact calibration-profile data set now includes the already introduced
  setup-guide selection and worker-status symbols, retaining exhaustive
  profile/header checks.
- The START_PRINT phase-order test now checks its own phase family. A new actual
  RESUME rendering test requires the exact five Resume boundaries and proves
  that Start and Resume together cover every registered macro Stop phase.
- Startup mapping tests inherit the corrected persistent-recovery interpreter;
  no mapping assertion was removed.

The follow-up startup/profile/retained merger/Stop-macro batch passes (45).
The isolated worktree also lacked the retained vendor merger script and older
firmware fixtures; existing local extractions were made available, without
fetching firmware or accessing the printer. The initial combined run used a
newer Tornado than the README's factory-test pin. The cached 6.3.3 package passes
all three HTTP compatibility tests; the final combined run must use that pin.
Original full-run failures/skips remain recorded rather than relabelled passed.


## Recovery effects-contract integration correction

The combined suite exposed a production regression introduced by the local
safe-cancel macro edits: `_CHANGING_TOOL`, `_CHECK_CHANGE_TOOL` and `_UNLOCK_TOOL`
no longer matched their reviewed file-effects fingerprints. All three matched
their earlier reviewed bodies at branch base `7c81ada`. The strict refusal was
working, but current delivered installations could consequently lose optional
file-derived recovery and proof of unused-head recipe eligibility. Managed
printing itself remains admitted when this optional evidence is unavailable.

The full diffs were reviewed before changing the three fingerprints. They add
M400/drained cooperative Stop observations around complete stages, and call the
same fixed-corner XY helper directly instead of entering native G28's motor-off
exception handler through the override. They do not change the completed
operation's mapping/frame/return effects. A Stop aborts before later phases;
it does not authorize a different continuation or permit arbitrary macro edits.
Existing XY helper tests separately establish that it changes neither Z nor tools.

Only those exact delivered macro digests were updated. Installed transform
hashes, whole-file binding, macro canonicalization and refusal behavior remain
unchanged. Tests now mutate each of the three newly reviewed bodies with an
extra Z/extrusion move and require rejection. Active-recipe and file-envelope
regressions pass (58). The changed proof hash intentionally does not bless older
file-derived contexts; existing proof mismatch handling remains authoritative.
Related service-geometry/native-runout regressions pass (17), and matching
delivery/package/material installer checks pass (248). Native source and artifact
hashes were verified unchanged before refreshing backend delivery inputs. The
corrected combined regression remains pending.

The original serial combined run completed with 6349 passed, 104 failed,
55 skipped and 13 setup errors in 2015.66 seconds. Its log is retained; it is
not a passing integration result. Diagnosed failures include the effects-contract
regression above, missing retained input files, and stale test fixtures/assertions.

The final recovery-worker/Resume groups also needed their small simulated
printers to register the real material object and carry the current filename.
Their synchronous command harnesses now inject explicit actor identities instead
of importing Klipper's absent host greenlet dependency. No production ownership
check was weakened. These three complete test modules pass (93).

The corrected full run will use cached Tornado 6.3.3 and existing local vendor
inputs. A four-worker temporary-file/loopback/native-worker probe passes (11);
module-scoped parallel scheduling will keep shared test fixtures together while
reducing serial compilation time. The tests use temporary localhost servers; they do not contact the printer
or operate its services. Final combined success remains unproven until its
terminal result and skip dispositions have been reviewed.
