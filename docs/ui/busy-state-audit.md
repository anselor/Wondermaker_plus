# Busy and admission state audit — 14 November 2026

Scope: repository-owned touchscreen controllers/workers, material helpers,
calibration/identification helpers, and live macros. This is a source and host
fault-injection audit, not hardware qualification of every exit. Vendor firmware
and openACE internals are outside this inventory; their ownership/status boundary
is included. The status latency investigation and User2 bottom-Z investigation
are separate workstreams.

## Admission rule

A local draft, preview, file-copy review, or completed-result panel does not own
printer movement. A queued physical request does, even before its HTTP dispatch.
A request known not to have been dispatched is refused and can release admission.
A dispatched request with missing evidence remains unknown until an authoritative
receipt or explicit recovery resolves it. Closing a screen, a timeout, or a
restart is not proof that physical work completed.

## Confirmed gaps corrected

- `Runtime::stock_maintenance_reason` used modal existence as printer ownership.
  Nozzle editing, previews, and terminal result screens now leave admission to
  actual queued/unresolved physical work and current backend state. The earlier
  filament settings change already separated metadata saves from movement.
  `StandaloneBackend::machine_request_pending` excludes metadata transactions.
- `StandaloneBackend::submit` could leave a new queue reserved after command
  validation threw, or lose an older request when a competing submit threw.
  Cleanup now retires only newly staged work. `deliver` includes script building
  in its exception boundary, distinguishes refusal from uncertain delivery, and
  Runtime tracks the real unresolved request rather than a permanent synthetic ID.
- Filament scheduling exceptions now produce a refusal before dispatch, with a
  tombstone even if the scheduler enqueued before throwing. Revalidation failure
  before execution is refused. Paused-filament `serviced` is set at execution,
  not while merely scheduling. Journal failure remains unknown rather than
  advertising a running callback that was never scheduled.
- Profile-import and AFC publisher thread-start errors release their local busy
  flags. Worker completion is retained in a reactor-drained mailbox if callback
  registration fails; a later status/timer tick publishes it and clears busy.
- Probe BEGIN proved not dispatched releases its local request. A new explicit
  BEGIN can retire old local uncertainty only when a fresh replacement backend
  session reports clean idle, no request, sequence -1, valid binding, and no save
  review. Merely observing a restart does not replay or claim success.
- Identification refuses existing competing operations before acquiring its
  calibration latch. Invalid configuration and failures during an actual attempt
  retain the fault. Native request-token construction precedes setting `sent_`,
  so token generation failure cannot reserve an unsent identification request.

## Setter, consumer, and exit ledger

Names below identify the implementation entry points, not just variables whose
name contains “busy”. Rows group fields sharing one lifecycle.

| State / setter | Consumers and normal release | Error, disconnect, restart, navigation |
| --- | --- | --- |
| Runtime UI `active()`; nozzle/identity/procedure/preview/result `show/open` | Owns screen navigation only; close/delete resets local UI | No machine hold from modal existence. Local draft changes do not dispatch. A real queued operation survives closing its panel. |
| Runtime `stock_edit_receipt_` / `stock_edit_operation_` and `filament_settings_`, `settings_block_machine` | Receipt matching retires save; identity metadata has separate tracking | Topology edits can still reserve affected configuration. Identity/nozzle drafts do not reserve motion; identity metadata saves have separate admission. A tool-associated confirmation can briefly retain `tool_receipt_` until refreshed verification. Failed or unknown metadata readback is shown for review, not permission to auto-run Load. |
| Standalone `submit`: `queued_`, `waiting_`, action/request/receipt | `deliver`, `observe`, `finish`; Runtime machine admission only for physical requests | Before-dispatch exception refuses; post-dispatch exception unknown. Retained unknown start/load/unload/take/dock waits for correlated evidence. Step/temperature retain existing bounded timeout/review semantics; no new permanent hold. Older queued requests survive rejected competing submits. |
| Runtime `tool_receipt_` and application operation | Matching refreshed receipt retires; Maintenance checks actual pending operation | Invalid/stale status cannot invent completion. Metadata-only application receipts are excluded from machine admission; a short in-flight tool receipt still serializes the associated action. |
| Cancel and recovery native workers: `select/start`, `queued_`, `busy_`, result | Worker loops clear execution busy after success/catch; matched terminal receipt resolves operation | Delivery unknown is distinct from worker busy. Closing progress does not clear unknown. Recovery resolves matching abandoned/reconciled attempts across backend sessions. Pre-dispatch admission failure refuses. |
| Cancel/recovery resolution and retirement workers | Their worker loops clear busy after catch; review selection and matching result tracked separately | A review is not a physical reservation. Sent mutation with uncertain response remains unknown; changed review/session prevents dispatch. Destructor stops queued work and joins worker. |
| USB copy worker running/queued/result | Completion/catch releases execution flag; UI shows result | File copy uncertainty owns its destination/review, not printer movement. No global machine lock from USB preview. |
| ProbeEditorFlow request/pending/invalidation; ProbeEditorWorker busy and stop busy | Matching session/request/sequence receipt; worker exits clear execution flags | Lost HTTP response stays unknown. Known unsent BEGIN and explicit clean new-session BEGIN handled above. JOG/SAVE/DISCARD uncertainty cannot clear backend ownership merely on Back. |
| Stock calibration flow started/sent/destination/failure | Correlated calibration session/checkpoint controls completion and navigation | Missing status never means success. Failed/uncertain stage retains setup review; explicit setup reset/restart required. Polling latency is tracked separately. |
| Stock identification flow sent/restart_sent/failure | Correlated refusal releases unsent ownership; acknowledged successful mapping requires restart | Unexpected session change remains review-required; deliberate successful restart releases. Token construction cannot leave sent set. |
| `wm_material.cmd_TOOLHEAD_ACTION`: operation running, request ID, scheduled closure | Callback finally records complete/refused/unknown; `cmd_RECOVER_TOOLHEAD` requires physical evidence | Scheduler enqueue-then-throw tombstone prevents later motion. Journal failure retains unknown. Startup restores interrupted intent as unknown, never auto-runs it. |
| `cmd_FILAMENT_SEQUENCE`, `_execute_filament`: operation/phase, pause-origin serviced | Complete/refused/failed receipt; sensor/procedure recovery checks resolve physical failures | Predispatch refusal releases; dispatched failure remains a physical fault. Scheduler failure, journal failure, and delayed callback covered above. Session/generation/owner rechecked before motion. |
| `cmd_PROFILE_IMPORT`: `_profile_import_busy`; `_afc_tick`: `_afc_busy` | Reactor mailbox publishes final result and clears busy | Thread-start failure clears; lost callback wakeup leaves queued completion for status/timer drain. These flags serialize metadata work, not printer movement. |
| `RecoveryAttemptRunner.run/resolve`: `busy`; `cmd_RECOVERY_CONTINUE`: `_recovery_command_active` | `finally` clears execution busy and command-active | Durable pending/running/unknown/stopped attempts intentionally survive errors. `managed_operation_hold` releases only with terminal or explicitly reconciled evidence. |
| Print cancel `_begin_print_cancel`, restore, resolution stage records | Complete/failed cancellation receipt and explicit resolution retire intent | Intent persisted before dispatch; restored pending becomes unknown. Missing/corrupt journal remains fenced. Cleanup attempts shutdown/drain even if journaling fails. Not safe to release in a generic finally. |
| Recovery submission `_pending_recovery_submission`, JOB_BEGIN/COMMIT/CLEAR | Launch exception and validation exceptions clear local submission; job commit/clear owns durable lifecycle | Unknown print submission remains review-required; no automatic replay. Recovery restore error independently blocks admission. |
| Normalized job/owner/operation/calibration fields and `managed_operation_hold` | Derived each snapshot; standby/complete idle policy and known standalone/openACE owner | Freshness loss, unknown owner, malformed receipt, unresolved cancellation/recovery prevent dispatch. These are evidence gates, not flags to clear on UI navigation. |
| `CalibrationCommands.active`, `_saving`; probe cleanup `_cleanup_active` | `finally` on commands/cleanup clears transient execution flags | Calibration failure intentionally stops the rest of a vendor command batch. Backend editor state/save-review remains until explicit finish/discard/ack; startup restores durable save review. |
| Identification `identification_blocked`, operation/failure; saved `is_nozzle_setting` | Preflight refusal does not acquire latch. Session clears mode on success before mapping publication | Mode is marked potentially set before SAVE_VARIABLE; failure attempts cleanup and verifies it, shutting down if cleanup cannot be confirmed. In-progress/configuration fault and completed mapping require inspection/restart. |
| Bottom-Z helper active/valid | `finally` clears active; error/shutdown/disable invalidate reference | No reuse of uncertain reference. User2 movement guard and its hardware evidence belong to the separate Z investigation. |
| Saved `fail_flag=-3` in docking/seat/unlock/service error paths | Homing, toolchange, calibration refuse unresolved docking fault | Deliberately durable. Existing zero writers do not erase -3. Inspection and explicit recovery required; restart alone does not clear saved fault. Release check now follows stock retreat; unlock is checked before retreat. |
| Saved `changing_tool` in live change macros | Compatibility marker set around tool transitions; no repository-owned machine-admission reader found | Macro abort can retain it. It is not a WM+ global busy gate; vendor readers are outside audited source. Do not blindly clear a physical transition marker. |
| `_WMP_TOOL_RETURN_BEGIN.pending/success`, `_descend_z.need_descend` | FINISH consumes return intent; next BEGIN initializes fresh intent | Macro abort may skip FINISH; next transition replaces it. Not a global busy gate; guarded success/printing/homing controls prevent unconditional return motion. |
| `START_PRINT.print_body_ready` | False at startup/end/cancel; true only after startup purge | Failure leaves false, suppressing model-position return. This is a prerequisite, not global busy. |
| `_WMP_RECOVERY_BEGIN.active`, saved print context | BEGIN validates context then sets; M24 verifies/restores mapping then clears; startup/context-clear reset | Failure intentionally retains recovery interpretation and blocks unsafe continuation; restart resets transient macro flag but does not prove durable job resolved. |

## Cancellation timer retention correction

Follow-up inspection found `_begin_print_cancel` registers a new cleanup timer
for every admitted cancellation, but its terminal callback paths return `NEVER`
without unregistering. Vendor `klippy/reactor.py` retains those timers in its
`_timers` list; `NEVER` disables scheduling, not ownership. The timer retains its
closure, request ID, binding and file-handle object. Failure of `update_timer`
after registration also retains the timer. Shared helper/printer references are
not a separate copy of the printer per timer.

Growth is bounded by the 1,024 attempted cancellation IDs permitted per helper
session. This is a per-command retention bug, not evidence for rapid memory
growth during idle status polling. The separate legacy parser/disabled-GC issue
is handled by the status workstream and shipped first at `f66623b`.

The follow-up correction unregisters every terminal callback and activation
failure, retaining the timer only while waiting for SD work or the G-code mutex.
It preserves unresolved cancellation receipts and does not retry cleanup.
Current-status exceptions also become unknown and retire their timer. Tests
track registered timers alongside an unrelated baseline timer: completion,
superseded/non-pending request, lost job/owner, status/cleanup/journal exception,
and registration/activation failure return to baseline; pending SD/mutex waits
retain exactly one. Twenty repeated resolved cancellations do not accumulate
timers. Explicit references to the latest binding for recovery review remain
distinct from obsolete timer closures.

Focused cancellation validation passed: 54 tests, 1,344 deselected
(`/tmp/wmp-cancel-timer-tests.log`). Full material validation passed: 1,396 passed,
2 skipped in 173.06 seconds (`/tmp/wmp-cancel-timer-full.log`). The 16 new timer
regressions also passed separately (`/tmp/wmp-cancel-timer-regressions.log`).

## Validation and remaining limits

Host regression suites cover transport refusal/unknown results, queued callback
failure (including enqueue-then-throw), intent/result journal failure, worker
thread-start and callback-wakeup failure, competing ownership, configuration
change before dispatch, and explicit restart-session handling. Native lifecycle
checks verify nozzle drafts and completed cancellation panels leave Maintenance
available while actual queued physical requests still reserve it.

Earlier full UI run: 42 passed, 1 deselected, with the loopback case separately
passing. After modal changes: native lifecycle and standalone cases both passed.
Final material/probe/identification run: 1,424 passed, 2 skipped; one test still
expected a pre-dispatch owner change to be `failed` rather than `refused`. After
correcting that obsolete expectation, the focused openACE direct, scheduler,
thread-start, and completion cases passed (109 passed). Additional calibration,
identification session/transaction, and stock worker suites passed (101 passed).
Native identification session/restart flow passed separately (1 passed).
`git diff --check` passed. Logs: `/tmp/wmp-busy-audit-final-python.log`,
`/tmp/wmp-busy-audit-final-focused.log`,
`/tmp/wmp-busy-audit-final-lifecycle.log`,
`/tmp/wmp-busy-audit-identification-native.log`, and
`/tmp/wmp-busy-audit-modal.log`.
Rebuilt ARM artifact/source-manifest validation is a release step after all agents
finish source changes; the old artifact is necessarily stale during this audit.

Retained limits: no physical fault injection, no verification of proprietary
vendor readers of saved compatibility markers, and no blanket recovery from
process-wide allocation failure or a hung external dependency. A worker blocked
inside an external call requires timeout/cancellation investigation, not clearing
its busy flag while it may still execute. The status-lag workstream owns that
latency measurement. Successful host tests do not establish hardware completion.

### Maintenance worker ownership follow-up — 15 November

Retained 1.1.13 tracing found that Maintenance queues `auto_checking` on eight
reusable worker threads. Its shared native status reaches terminal value 14 only
after the final save/restart wait. Backend `calibration_active` covers individual
commands, so false between-command intervals do not prove this worker returned.
A later START may otherwise overlap an older worker's terminal write and exit
before motion. The candidate must reserve queued/running work from admitted
START through worker return, bind save receipts to that invocation, and release
on every worker exit. A visible result page or editable UI draft must not itself
hold that reservation. Stock OK's terminal cleanup (status 14 to 0) must be
preserved when leaving a finished result; clearing it during an active run is
not permitted. Implementation and native regression validation are complete:
queued/running reservation survives backend restart, worker exceptions and
failed enqueue release it, and repeated pooled invocations retain their own
save bindings. On-printer Bed Leveling completed and BACK returned to the
Maintenance menu. Probe-editor interaction remains a separate physical check.
