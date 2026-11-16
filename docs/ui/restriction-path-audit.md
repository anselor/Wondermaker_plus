# Restriction and caller-path audit

15 November 2026. Offline source review begun at `da3af89` and finalized against `caf459a`,
which includes the stock startup mesh-save correction. No printer changes, motion,
service restarts, or production-source edits were made for this audit.

This complements [the busy-state ledger](busy-state-audit.md): releasing a flag
is insufficient when a legitimate nested caller never satisfies the gate in the
first place. Findings below distinguish source-confirmed behavior from runtime
qualification. This is a restriction-family inventory and traced high-impact
paths, **not certification of every proprietary callback or third-party macro**.

## Findings requiring follow-up

### R1 — AFC-owned resume enters standalone-only admission

**Source-confirmed; AFC installation/runtime reproduction outstanding.**

- `config/live/macros.cfg:302`, `:323`, `:353`, `:383`, `:646` exclude `openace`
  but not `AFC` when emitting capture/resume/extrusion-restoration commands or
  redirecting paused `M24` into `RESUME`.
- `klipper_extras/wm_material.py:3180` (`cmd_CAPTURE_PAUSE`) and `:3319`
  (`cmd_CHECK_RESUME`) likewise bypass only openACE. The latter calls
  `_paused_filament_origin` (`:3238`), which explicitly refuses **either** owner.
  `cmd_RESTORE_RESUME_E` (`:3370`) also refuses either owner.
- Reproducible source path: AFC object present, openACE absent, retained WM
  `PAUSE`/`RESUME` handlers in use; pause completes and captures a context;
  `RESUME` reaches `WMP_CHECK_RESUME`, then fails with “Another manager owns
  paused filament service.” Paused `M24` follows the same path. Even bypassing
  that first refusal leaves the later extrusion-coordinate guard refusing AFC.
- Expected: standalone admission must not capture an AFC-owned continuation;
  the qualified AFC route should retain ownership. Actual: macro caller admits
  a route its own callee categorically rejects.
- Proposed fix: use one explicit owner contract at all pause/resume entry and
  nested boundaries, preserving AFC's actual wrapper chain. Do not simply skip
  all resume validation for unknown owners.
- Regression: execute retained macro expansion and nested commands with the AFC
  object present, both API `RESUME` and paused `M24`; verify no WM standalone
  capture/restore occurs and the AFC/stock continuation runs exactly once.
  Repeat standalone and openACE cases, including owner change after heating.

### R2 — Known pre-SD print failures become unreconcilable screen holds

**Backend behavior reproduced by existing fault-injection tests; combined
backend/native resolution test outstanding.**

- `wm_material.py:6926` (`cmd_START_PRINT`) establishes a pending submission,
  changes preparation settings, runs `G30`/`G31`, revalidates file/profile/mapping,
  and only then dispatches `SDCARD_PRINT_FILE`. Its broad catch at `:6987`
  publishes `unknown` for every error after initial admission, including errors
  that prove the SD dispatch was never reached.
- `client-preload/unified-ui/standalone_backend.hpp:27`, `:47`, `:55` retains
  unknown `start_print` as a machine reservation. The print observation branches
  (`:58`, `:66`) resolve only refused or positively submitted receipts. A new
  backend session changes the result to unknown again. Recovery methods in this
  class target filament or toolhead actions, not print submission.
- Concrete trigger: file/profile changes during preparation, or `G30` fails
  before SD dispatch. The backend knows it never issued the SD command, but the
  screen says inspect the job and retains a hold. Maintenance then refuses via
  `Runtime::stock_maintenance_reason` (`native/runtime.hpp:248`). Mere inspection
  or closing the result cannot reconcile this receipt.
- Expected: preserve uncertainty about actual preparation side effects while
  distinguishing “SD never submitted” from “SD dispatch outcome unknown.” Actual:
  both have the same indefinite UI admission state and no matching resolution.
- Proposed fix: record preparation/SD dispatch boundaries and a terminal
  preparation-failed outcome; retain physical faults independently. For genuinely
  unknown SD dispatch, add explicit reconciliation bound to session, file handle,
  operation and fresh stopped/active evidence. Do not clear unknown solely on a
  timeout, idle status, navigation, or arbitrary restart.
- Regression: fault injection before first preparation side effect, after mapping
  writes, after G30, during file revalidation, before and after SD dispatch; feed
  each receipt into the real native backend and verify the supported resolution.
  Verify an actual running job can never be released by an unrelated idle sample.

### R3 — Stock startup mesh save was intercepted as a general restart

**Confirmed incident; corrected at `caf459a` by the separate mesh workstream.**

`START_PRINT` (`config/live/macros.cfg:3`) runs as an active SD command, creates
`wmp_print`, and calls `SAVE_CONFIG_NO_RESTART` (`:110`). The new config-save
wrapper (`wm_material.py:_config_save_routes_ready`) reused `_restart_requested`,
whose deliberate precondition is no active SD context. The managed-start exception
requires `_pending_recovery_submission`; direct stock SD starts have none.
Consequently a legitimate stock startup was rejected after probing. The correction
adds a narrowly bound stock-start ticket; this audit does not duplicate its fix.

Release regression must exercise **both** direct stock SD and managed SD through
actual nested `START_PRINT`, not just call the save helper in an idle fixture.
External save, later SD lines, changed file/position/session, paused job, unrelated
pending edits, cancellation and replay must remain rejected. The ticket must be
consumed before writer entry even when the writer fails.

### R4 — Calibration admission errors latch beyond the requesting attempt

**Source-confirmed policy consequence; classification/UX decision needed.**

`wmp_recovery.py:1298` (`CalibrationCommands.cmd_run`) places decoding, supported
command validation, `_check`, and save admission inside the same catch that sets
`self.failure`. A malformed request or temporarily non-idle printer therefore
poisons later calibration until restart even when `started` is false. Probe-editor
busy and an already-running command are checked outside this catch and do not.

The latch is necessary for a vendor worker that queues later stages separately:
a rejected stage must not allow its later SAVE_CONFIG to run. The gap is that the
latch is backend-global rather than owned by that invocation. Do not weaken it to
“clear on every error.” Follow-up should bind stages to an attempt and distinguish
preflight refusal from an admitted attempt's aborted continuation. Test separately
queued continuation, unrelated new attempt after a clean refusal, malformed remote
input, and genuine motion failure. Current native worker reservation prevents a
second screen START while the first worker still runs; direct helper invocations
remain a separate caller boundary.

## Caller paths reviewed

| Origin | Nested path that must be preserved | Admission implications |
| --- | --- | --- |
| Direct SD / Fluidd file start | SD worker `run_script(line)` → START_PRINT → home/tool select → mesh → no-restart save → body | Not an idle RPC; R3. All startup-internal calls inherit active SD state. |
| Managed screen print / reprint | preview → WMP_START_PRINT → prepare mapping/G30/G31 → stage recovery → SDCARD_PRINT_FILE → START_PRINT | Request admission is idle; subsequent nested execution is not. R2 and R3. Reprint intentionally returns to review rather than replaying stale mapping. |
| Screen Maintenance | admitted START → queued vendor pool worker → individually guarded commands → SAVE_CONFIG → restart/result | UI reservation spans the entire worker, backend active flag spans each command. Session changes do not prove worker return or successful save. |
| Remote calibration | public macros / native commands, or explicit _WMP_CALIBRATION_COMMAND | Public macros do not automatically acquire the native worker reservation. Encoded helper intentionally restricts commands; R4. |
| Probe editor | BEGIN → preparation/home → native manual-probe helper → TESTZ/ACCEPT → save/discard/keep | Draft editing owns a real probe session, unlike filament metadata. Cleanup ABORT/DISCARD bypass competing admission but retain exact helper/token binding. |
| Home / tool exchange | G28 → homing_override → physical selection / bottom home; Tn/_CHANGE_TOOL → unlock → retreat → detach evidence → pickup | Inner commands may execute during print startup or normal tool change. Physical sensor checks must occur at the correct stage, not be removed wholesale. |
| Filament draft vs save/service | UI draft → atomic WMP_SET_FILAMENT; load/unload → WMP_FILAMENT_SERVICE/SEQUENCE → prepared travel/heat/feed | Draft has no machine ownership. Metadata commit has revision/owner checks; real service retains physical uncertainty. |
| Pause/resume | API or SD PAUSE → parked-state capture; RESUME → admission → heat → re-admission → return/E restore → CLEAR_PAUSE → M24 | Final M24 must not recurse. Alternate owners must be excluded consistently; R1. |
| Cancel/error | API/script cancel → bound file cancellation → stopped SD/mutex boundary → retained cleanup | Vendor SD on_error uses `run_script(on_error_gcode.render())` in the retained baseline, so its direct CANCEL_PRINT reaches ingress. A custom nested macro does not. |
| Restart/save | direct RESTART/FIRMWARE_RESTART, config writer, calibration save, probe save, client startup restart, service restart | These are different callers. Backend event guards cannot constrain systemd; writer admission must occur before persistence, not only at restart. |

## Restriction-family inventory

Locations below name executable entry points; each row groups related checks with
one purpose. Supporting error/parser/type checks remain part of that contract.
“Unverified” means the path still needs integration or hardware evidence.

| Gate / source | Preconditions, legitimate callers, and exit behavior | Review result / remaining verification |
| --- | --- | --- |
| Native fresh/Ready/owner/protocol projection (`native/projection.hpp:149`, runtime worker polling) | Screen actions require current Ready snapshot and recognized owner/protocol. Missing optional calibration fields default idle, not a fabricated fault. HTTP failure marks stale; discovery cache follows backend session. | Correct distinction between unavailable evidence and operation failure. A stale banner is not completion. Remaining latency investigation is documented separately; no larger timeout is proposed as proof. |
| Native Maintenance admission (`runtime.hpp:248`) | Physical queued/unknown requests, calibration fault/session, job state, owner and backend operations checked. UI modal presence excluded. Queued vendor worker reservation survives backend restart. | Filament/nozzle drafts and finished panels no longer hold movement. R2 still creates a real but unreconcilable local reservation. AFC owner is unsupported here; qualification needed rather than silently treating it as standalone. |
| Native callback/caller-address checks (`native/bootstrap.cpp`, `stock_maintenance_command.hpp`) | Verified visible event/callsite only; wraps maintenance commands rather than arbitrary command_sender traffic. Exact profile bytes required. | Prevents accidentally guarding generic motion as calibration. Vendor pool entry/return and exception exits covered by prior native tests; unrecognized firmware must not partially activate hooks. |
| Calibration worker result (`stock_calibration_status.hpp`, `stock_calibration_flow.hpp`) | Origin session/request and confirmed save receipt; previous failure dominates. Backend restart without matching receipt remains unconfirmed. | Normal SAVE_CONFIG must pass durable saved-value verification; this is not proof every physical stage completed. New admitted START resets prior panel, BACK preserves vendor terminal cleanup. |
| Probe ownership (`wmp_recovery.py:1035–1183`) | Standalone only; Ready/idle/no competing operation, exact native helper identity, sequence/token, pending-config revision. ABORT/DISCARD bypass ordinary competing admission but not helper identity. | openACE/AFC probe editor deliberately unqualified; do not advertise it as available to those owners. No automatic retry of uncertain JOG/SAVE. Replacement-session BEGIN only under explicit clean-state evidence. |
| Calibration command wrapper (`wmp_recovery.py:1190–1375`) | Whitelisted encoded command, idle/unpaused, fail_flag zero, no identification/probe hold; active finally clears. | R4. Genuine stage error intentionally retains failure and turns heaters off; never auto-home as cleanup. |
| Identification (`wmp_identification.py:701–784`) | Session/request, bounded history, no probe/managed operation; mapping transaction must retain owner and configuration. Successful mapping requires restart. | Competing preflight moved before latch. Invalid configuration after latch still requires restart despite no motion; distinguish diagnostic preflight from genuine transaction in future UX. Rollback/cleanup failure remains inspectable, not silently cleared. |
| Bottom-Z helper (`wmp_recovery.py:85–134`) | Supported physical configuration, no paused/printing-body state, inactive leveling/gantry pins. Startup while printing/body-not-ready is intentionally allowed. | All exceptions invoke shutdown to stop independently queued vendor continuation. Preflight refusal therefore has broad effects; tests must distinguish wrong external invocation from interrupted recovery. Counter overshoot guard was removed; no claim hardware homing is fully qualified by this audit. |
| Homing override (`config/live/printer.cfg:328`, `_WMP_SELECT_HOME_TOOL:410`) | Saved docking fault blocks homing; unique attachment/physical probe selection required. | Prevents guessing a datum after coupling failure. Direct X/Y and startup G28 must retain vendor semantics; User2 failure is not established as an uncleared UI flag. |
| Dock/unlock/pickup macros (`change_macros.cfg:110`, `:394`, `:899`, `:918`) | Unlock before retreat; detached-head evidence after stock retreat; persistent fail_flag on physical failure. | Prior pre-retreat detach check was a false rejection and has been corrected. tX_position remains source for dock travel. Sensor disagreement must not be “fixed” by blindly clearing fail_flag. Automatic retries after failed coupling remain intentionally blocked. |
| Print return/clearance (`change_macros.cfg:985–1055`, `offset_calibrate.cfg:559`) | Known homing, available Z travel, print-body readiness, physical tool/reference offsets; return intent only consumed on success. | Entry during startup must not be confused with printing body. Failed return stays faulted; no unconditional upward/downward cleanup. Hardware limit cases unverified here. |
| Public calibration macros (`macros.cfg:452–525`, `offset_calibrate.cfg`) | Idle physical-head calibration, no tool/recovery fault; fresh Z measurements required before XYZ offsets saved. | G29 maintenance is distinct from START_PRINT's active-SD mesh path. Direct console, screen rapid/precise XY/XYZ and cleanup callers must remain in integration matrix. |
| Mesh namespace/reference guards (`macros.cfg:624–639`, `:685`) | Default profile requires T0 reference; `wmp_print` reserved; recovery restores its exact mesh via retained BASE handler. | Internal callers use BASE intentionally. User manual LOAD/SAVE/REMOVE wmp_print is unsupported by design. Recovery active latch must not redirect unrelated later loads after failed recovery without explicit resolution. |
| Save/restart wrappers (`wm_material.py:_config_save_routes_ready`, `_restart_requested`) | Standalone general saves/restarts require stopped SD, no paused/managed active work. Calibration/probe own-save exceptions narrow. openACE/AFC delegate. | R3. `print_stats=error` alone is not admitted; stopped/error cleanup and cancellation must give operator a reachable route. Not-ready isolated firmware restart allowed by script ingress. System service restart bypass is explicit. |
| Toolhead admission/reconciliation (`wm_material.py:998–1155`) | Idle, correct owner/session/attachment, no saved physical fault. Revalidate under mutex before macro. Completion checks sensors after M400. | Predispatch refusal releases; postdispatch unknown requires reconciliation. Recovery itself requires fail_flag already resolved; UI must explain physical-fault workflow rather than suggest endless retry. No automatic physical retry. |
| Filament service (`wm_material.py:_filament_plan`, cmd_FILAMENT_SERVICE/SEQUENCE) | Identity/procedure revision, actual presence, correct head/temp/owner, idle or captured paused job; generation recheck before scheduled work. | Valid empty/loaded condition matters by action. No automatic loading on insertion. Scheduling errors retire queued closure; unknown journal outcome deliberately holds. Optional recovery helper selects legacy fixed-position contract, not guessed travel. |
| Filament metadata/nozzles (`wm_material.py:3031`, `:3402`, `:3423`) | Atomic revision-checked saves; physical head installed, owner valid. Paused metadata edits require captured unloaded head. Nozzle mutation has independent config/restart contract. | Editing a draft must not hit these gates or reserve printer. Metadata commits may refuse active work; loaded identity is not automatically a new completed load. In-session external file edits/status-cache refresh need separate tests. |
| Pause/resume integrity (`wm_material.py:3180–3392`, `macros.cfg:205–390`, `:641`) | Same open SD file, saved state/mapping, original mounted head, loaded required heads, no active service, E origin repaired only after physical return. | R1. Runout/tangle and deliberately paused jobs must share this route; direct M24 guarded. Custom pause macros that bypass capture are not qualified and will refuse resume. |
| Direct extrusion/autoload replacement (`macros.cfg:960–1023`, `:1210–1275`) | Standalone small bounded extrusion requires hot confirmed head; legacy EXTRUDE/RETRACT and sensor auto-feed are replaced with explicit service/step entry. | Intentional compatibility break; vendor screen hooks and external macros invoking old names require trace tests. openACE purge assist calling old handler is especially sensitive; do not assume lexical command replacement covers its private aliases. |
| Script cancellation ingress (`wm_material.py:1982–2065`) | Top-level CANCEL_PRINT captures exact file before mutex; nested direct command handler refuses. Entire batch containing CANCEL replaced by cancel. Other scripts get per-line session/generation fences. | Retained SD on_error reaches top-level run_script (baseline virtual_sdcard.py:277). Custom macro→CANCEL_PRINT is intentionally rejected but may leave requested cleanup undone; document supported cancellation API and test actual on_error chain. |
| Cancellation holds (`wm_material.py:_begin_print_cancel`, resolution endpoints) | File handle/session binding, stop intent persisted, generation increments before cleanup; only exact M112/heater-off/resolution and not-ready restart exceptions. | Unknown cleanup cannot be released by idle/closed screen. Timer lifecycle fixed separately. Keep resolution usable during the hold; batch prefixes must not reject its own cleanup. |
| Managed print start (`wm_material.py:_print_admission`, `_print_plan`, cmd_START_PRINT) | Idle, correct owner, current file identity/profile/mapping, loaded used heads; revalidate after preparation. | R2. Direct stock start has different admission and cannot be required to carry managed tickets except where explicitly created. Filename restrictions are user-visible compatibility constraints, not evidence of motion failure. |
| Recovery preview/continue/resolve/retire (`wm_material.py:_recovery_machine_state`, cmd_RECOVERY_CONTINUE/RESOLVE/RETIRE_RECOVERY; recovery modules) | Durable exact file/checkpoint/calibration/owner evidence; bounded physical plan and explicit stop; retirement distinct from cancellation. | Corrupt/missing journals hold rather than invent completion. Restart/session/ownership handover paths must offer resolution without replay. Full recovery graph not re-qualified here; see existing recovery suites and busy ledger. |
| Native preview/reprint/USB/retirement gates (`stock_preview_event_gate.hpp`, `stock_reprint_gate.hpp`, bootstrap) | Correct live widget/file/request; reprint opens review; stale async metadata cannot change newer selection; copied file verified before selection. | UI-only review is not physical ownership. Refused stale callback should leave usable navigation; exact firmware widget coverage remains bounded by profile. |
| Vendor automatic/destructive routes (`head-config-guard/wmp_head_config_guard.c`, recovery-fix, openace-compat) | Exact ELF/profile; blocks destructive head reconfiguration after communication failure and qualified autonomous filament/recovery routes. | Legitimate unsupported firmware cannot use partial hook set. Physical shutdown stays intact. Third-party private wrapper order/autonomous callbacks remain unverified unless covered by retained callsite evidence. |
| Package/source seals (`tools/preload_bundle.py:60–197`, package_unified_ui_delivery.py) | Reviewed ELF, source-input hashes, dependencies/profile and paired macro/backend delivery must match before install. | Earlier runtime.hpp/change_macros mismatch was packaging inconsistency, not printer busy. Rebuild/export/reseal together; never instruct users to bypass the seal. Locally modified tracked source requires deliberate reconciliation. |
| Installer transaction/service gates (`tools/install_journal.py`, `moonraker_directory_install.py:34–100`, moonraker_directory_service.py) | Printer identity/order/lock/known source; Moonraker restart requires Ready idle/unpaused and coherent helper baseline. | Factory absent helper now checked via objects/list, legacy schema supported. Installed-but-unavailable helper stays blocked. Interrupted journals require explicit recovery. Ready/idle is not by itself proof no calibration is running; installer/standalone service entry coverage needs review. |

## Required integration matrix and limits

For each shared wrapper, test the caller's **actual state at the inner command**:
idle API, direct active SD startup, managed active SD startup, printing body,
paused SD, active calibration, calibration SAVE_CONFIG, helper unavailable,
openACE, AFC, owner/session change, cancelled/error job, and interrupted recovery.
Run both normal completion and error-before-dispatch/error-after-dispatch paths.
Assertions should include the intended downstream handler and cleanup, not only
an error string or a boolean admission predicate.

Priority follow-up: R3 release independently; R2 usable print-failure resolution;
R1 consistent alternate-owner resume; R4 attempt-scoped calibration admission.
Remaining integration gaps include third-party macro aliases, proprietary
independent command queues, service entry during calibration, and every actual
remote/client callback under an ownership transition. These are **unverified**,
not automatically defects and not evidence that all gates are safe.

This audit reused retained stock configuration, the vendor SD worker source,
existing caller analysis in [upstream-command-audit.md](../upstream-command-audit.md),
and current production branches. No new hardware tests were run. Existing tests
are evidence for their named scenarios only; their pass counts are not a blanket
qualification of this matrix.

## Focused validation performed for this audit

Ten existing material regressions passed in 0.47 seconds (1,388 deselected):
`test_partial_print_submission_is_unknown_and_never_retried` (four injections),
`test_file_change_during_preparation_prevents_start`,
`test_prepared_print_rechecks_backend_before_sd_dispatch` (four changes), and
`test_afc_cannot_reuse_standalone_pause_for_resume_or_editor`.
The first nine explicitly reproduce the unknown result, including assertions
that SD dispatch did not occur. The AFC test establishes the callee refusal for
owner handover; it does not qualify the AFC-owned macro chain described in R1.
Log: `/tmp/wmp-restriction-audit-focused.log`. `git diff --check` passed.
No production/test files were changed by this audit; only this document was added.
