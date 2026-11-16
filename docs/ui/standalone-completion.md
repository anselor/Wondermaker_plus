# Standalone UI completion

## Field follow-up — 14 November 2026

Released UI and docking fixes are on main at `dfc8c9b`, following `c3858d2`
(separate metadata request tracking) and `6d1f1a5` (release validation after
retreat and rejected toolhead request retirement). The final commit corrects
the delivery manifest/source archive binding to the changed runtime inputs.

The released package was installed locally with openACE disabled. Installer
journal `8995aed3c4644335a9a6b14ff7fe9bb9` completed; backend protocols and native
activation checks passed. Its final status footer separately reported a stale
diagnostic sample, so this is not evidence that the deferred intermittent
status-availability issue is fixed. Screen build: `e6c9b6fdb0e71411`; binary
SHA256: `32ba1fde9494e93261fe04788644cd513d518950ccbe173483772e30201aeacd`.
The six tracked settings files had identical hashes before and after installation.

A local navigation check changed Head 1's brand to ELEGOO without saving,
then opened General → Maintenance → PROBE_CALIBRATE. The review showed idle
with START enabled, and closed back to Maintenance. No calibration was started
and no physical operation was tested. This checks navigation/admission with an
unsaved filament draft; it does not establish physical calibration success or
the outcome of a pending metadata save. Screenshots and installation hash
comparisons are retained locally in
`analysis/validation/2026-11-14-ui-docking-followup/` in the main checkout.

User1's subsequent logs show calibration refusal at 03:39:40 and
“Docking failure remains unresolved” at 03:40:40. The latter proves saved
`fail_flag == -3` at that time. `CalibrationCommands._check` rejects any nonzero
saved flag before as well as after dispatch; its “Tool change failed during
calibration” wording does not prove that a new tool change ran or failed.
The calibration handler also latches the refusal in memory. Restart clears
that in-memory failure but does not clear the saved docking flag. A retained
earlier fault is consistent with the excerpt; a new failure cannot be excluded
without the preceding events. User1 subsequently reports working homing and
docking/release, with vibration compensation started. The reported release
failure is resolved by operator confirmation; completed calibration remains a
separate verification item.

### Saved docking fault trace at `dfc8c9b`

This is a focused trace of `fail_flag == -3`, not completion of the full
busy-state audit. In the live macros and shipped Python helpers, its writers are:

| Writer | Condition |
|---|---|
| `_CHECK_AND_UNLOCK` | Target dock sensor does not confirm seating, outside nozzle-setting mode |
| `_WMP_REQUIRE_RELEASE` | Hall/presence does not confirm detachment after the retreat |
| `UNLOCK_TOOL_FINISH` | Final Hall/presence check does not confirm detachment |
| `wm_material._prepare_service` | Dock seating or post-retreat detachment check fails |
| `wm_material.cmd_COUPLING_STROKE` | Unlock actuator helper raises while the command guard still permits recording the fault |

The last writer includes actuator API/validation exceptions, not just a measured
mechanical failure. If command ownership or shutdown prevents fault recording,
the original error propagates; if persistence fails, the printer shuts down.
Neither filament draft editing nor `CalibrationCommands` writes this saved flag.

All zero writes in `config/live/change_macros.cfg` occur in `_CHANGE_TOOL`,
`_CHECK_CHANGE_TOOL`, `PARK_CURRENT_TOOL`, or `PARK_CURRENT_TOOL_RETRY`. Each
refuses an existing `-3` before those writes; standalone ownership additionally
refuses any nonzero flag before vendor retry/clear paths. Thus a later successful
sensor reading, a new calibration request, or a restart does not automatically
retire a prior docking fault. Deliberate inspected recovery is required.

Existing regression coverage includes
`test_new_action_cannot_erase_unresolved_docking_failure`,
`test_direct_homing_refuses_unresolved_docking_failure`,
`test_managed_toolchange_faults_never_clear_or_retry`, and
`test_dock_presence_is_checked_only_after_successful_unlock_and_retreat` in
`tests/test_config_macros.py`. These cover the stated macro guards and ordering;
they cannot identify which writer ran on User1's printer from the later generic
calibration message alone.

User2's platform-lowering failure recurred after the latest installation;
`klippy(16).log` contains the homing recurrence. The later `klippy(17).log` and
system journal establish an idle Klipper OOM kill. Release `253159d` rejects
contradictory bottom-Z trigger/halt counters before
the native retract can move farther down. Vendor-code replay confirms this
containment; the underlying scheduling delay remains unresolved. Evidence is
recorded in [the Z investigation](../z-recovery-investigation.md).
The [busy-state audit](busy-state-audit.md) records additional fixes and retained
physical-fault holds; the cancellation timer retention correction now passes
its focused tests and awaits packaging.
The [status optimization](status-polling-latency.md)
reduces measured reactor CPU work and was installed locally; actual
calibration verification remains pending. These measurements do not establish
the cause of User2's timing failures or later Klipper disconnections.

Active objective (2026-11-01): make the new UI fully functional without openACE.
**Initial release scope — user decision, 12 November 2026:** standalone WM+
only. openACE support will be completed in a subsequent release. ACE unit/slot
management, drying, routing, owner adapters and openACE qualification are deferred;
they are not blockers for this release. Existing code is not a support claim.
Keep refusal/ownership guards so an unsupported manager cannot receive standalone
motion commands. openACE is currently disabled on the test printer.

## Current release checklist — standalone WM+, updated 13 November 2026

This table is the current queue. Dated entries below preserve history and may say
“local”, “undeployed” or “open” after later evidence has superseded them. Read the
current table first; reopen an accepted check only for a relevant implementation
change, a new failure, or evidence that the earlier check did not cover it.

### Final acceptance status

| Item | Missing evidence / next action |
|---|---|
| B03/F04 physical touch | Accepted 13 November: user returned to the printer and reported “No missed taps” during the requested quick navigation/selector check. Automated navigation, retained controls, soak and memory checks already passed. |
| C03 manual retract | Accepted 13 November: user confirmed backward movement after the requested additional 10 mm retract on Head 3 at the purge position, 220 C. Command completed; all heater targets verified zero afterward. Earlier dispatch, E-distance/mode preservation and positive extrusion passes retained. |
| G03 first-run presentation | Accepted 13 November: production filament layout with onboarding enabled rendered on the printer using fixed sample data and no action callbacks. FINISH and four cards are visible without clipping. Entry/checkpoint/completion persistence are covered by the joined production-path tests. |
| R22/R24 review presentation | Accepted 13 November: actual native panels rendered with fixed sample data and disconnected actions in a temporary test build; screenshots inspected. Prior functional review/confirmation/persistence evidence remains separate. Production library restored. |
| G06 release activation | Accepted 13 November: reviewed-delivery export installed through the normal installer without the qualification flag. Journal applied; fresh native artifact/GUI/status and backend activation passed. Identities/loaded flags preserved; Ready/standby, all heaters off. |

A02's original startup requirements now have complementary evidence: actual
exported installation into a disposable stock home, all installed backend ready
callbacks, and live empty-metadata startup with four heads and native built-in
selectors. This is not a claim of a factory-reset installation. A factory reset
was explicitly deferred by the user and is not an additional release gate.

Installed delivery: 13 November reviewed release from `0750e9d` (same r196/r198 screen runtime; normal installer activation accepted), screen SHA256
`be6b976f934260139fca6d405a1970a3f2b3c557970bed42daac55d6213da408`.
Factory/knife/password-success gates, cancelled-review response handling, the
remote-start backup-write fix, durable Take/Dock journal, and reconciliation
and recovered-worker persistence-failure holds are installed. Installation/readiness checks support
deployment; they are not substitutes for the functional checks below.

| Requirement | Current evidence | Still required |
|---|---|---|
| F01/G01 paused replacement and runout | r191–r193 genuine H1 runout retained managed invitation, Load, exact XYZ return and one Resume; exposed logical-E bug. r194 correction deployed; r195 paused Unload/Load plus native Resume returned logical E=100 and XYZ exactly, then E101 advanced 1 mm. Paused removal produced no runout warning; service kept Z=17 without homing | Same-head sequence accepted. Cross-head service return/refusal is covered by execution tests (successful Load/Unload, purge failure, return-lock failure and calibration change, no Z motion). r196 tangle callback/Resume correction installed after 1,430 affected tests passed. Supported standalone pause/runout acceptance is complete; no physical cross-head or deliberately induced tangle claim. Do not repeat ordinary same-head Load/Unload |
| R20 Re-print | Real completed-popup handoff to managed preview accepted r134; metadata-free PRINT refusal and CANCEL verified; stopped-filename fallback host-tested and installed | None for the supported standalone routes: both known direct stop-worker callers are intercepted; last-object exclusion accepted r169. Other-owner stopped-popup qualification is deferred |
| R21 Legacy filament API | Standalone managed service and ACE-source owner adapters installed; direct external Load exercised with the owner offline; unsupported owner external Unload refuses before dispatch | None for the standalone legacy adapters. External Unload under openACE and native/live openACE qualification move to the subsequent release; standalone service-interruption validation remains tracked under R27 |
| R22 Power-loss recovery | Local durable execution/attempt handling, preparation through purge/wipe/return/parser restore; optional private continuation through exact-file/routes/accounting and durable worker activation; local runtime outcome handling, job-bound pre-enqueue deposition recording, clearance admission guards, resumed observer restoration, immutable-request Continue command, reactor STOP endpoint and native early selection hook; native receiver, independent transports, numbered progress/STOP panel and explicit resolution review/confirmation connected locally; post-restart recovery API coverage; r149 native Continue, visible stages/temperatures, clearance/home/heat and DISCARD→CONFIRM accepted; exact original bytes verified in archive; r151 native Continue through all stages and actual resumed print completion accepted; r153 native STOP→DISCARD→CONFIRM→restart accepted; r156 original-prompt Cancel→REVIEW→CANCEL and Cancel→REVIEW→DISCARD→restart accepted with exact nine-record archive and no discard motion | r167 native interrupted-resume REVIEW→CONFIRM accepted, recording newer completed position 4924 without motion, heating or print resumption. Both implemented resolution actions have native acceptance: failed-attempt abandon r149 and interrupted-continuation reconcile r167. Native incompatible-record retirement presentation accepted 13 November with the production panel in a sample-data fixture; confirmation behavior is covered by the existing functional tests. Persistence-failure and lost-response branches have host/native-worker coverage, not physical fault injection. openACE owner qualification is deferred. Historical formats cannot safely auto-migrate; their public discard/archive path is host-verified. Do not repeat accepted continuation or discard flows without a relevant change |
| R23 Reset/topology | Joint candidate/journal/rollback and stale-session guards tested; changed mapping refuses without calibration provenance. Reset Confirm refusal, opaque notice and CLOSE accepted r124; r143 reconfirmed refusal with 19 unchanged tracked files | Changed identification and intercepted discovery/config-save contracts reviewed against existing assertions and accepted results (evidence map below); no uncovered functional case identified for the supported unchanged-mapping route and changed-mapping refusal. Factory reset remains deferred with its accepted guard. Hardware remapping without independent calibration provenance remains unsupported; no new physical topology support, model-change qualification, or arbitrary external-shell validation is required for this UI release. |
| R24 Calibration editors | Managed editor installed. Native preparation START→STOP accepted r143 after fixing the actual HTTP route allowlist; terminal aborted, no active helper/pending save or config change. Native ABORT accepted r142. Factory/knife/password-success guards installed r142 and retained; native START→JOG→ACCEPT→DISCARD accepted r155 with unchanged config and no pending save | Changed save/restart and REVIEW/ACK/RETAIN functional coverage reviewed and accounted for (evidence map below); no uncovered functional case identified. Native pixel-layout inspection accepted 13 November: ACK and RETAIN review controls rendered through the production panel in a sample-data fixture on the printer; readable wrapping and header/stage layout were inspected. Functional dispatch remains established by the existing tests. Fresh physical calibration and Factory/Service password access are not prerequisites. No repeat of accepted START/STOP or ACCEPT/DISCARD. |
| R25 Failure retry | Single-attempt coupling guards installed; stale-session refusal verified; direct nonzero-fault action guards deployed r140. Camera-observed H4 Dock and Take both accepted on 12 November | No general mechanical qualification or deliberate physical failure test is required. Changed single-attempt/error-propagation and durable-fault behavior have actuator/macro tests; successful Take/Dock is already accepted. Raw vendor-console bypass is a documented boundary, not a new sandbox requirement. Reopen only for an identified gap in the changed guard or a new failure. |
| R26 Restart ownership | Installed r121 Ready-state guard and unresolved-result hold; exact startup shell restart suppressed and built wrapper tested; installer explicitly restarts the Klipper process and verifies changed PID, loaded protocols and stable readiness; r121 idle activation and preservation passed; r174 controlled OS reboot preserved all six tracked files, identities and loaded flags, with successful defaults migration before Klipper and screen startup | No further generic restart or stock-warning interaction test is required. The changed guard is covered by the joined ARM warning/retained-dispatcher tests; actual restart preservation passed r174 and interrupted Load recovery passed r177. Any remaining gap must name the changed ownership/persistence branch. Configuration-writer coverage is tracked under R23, not another reboot campaign. |
| R27 Cancel/service ordering | Native and remote Cancel accepted with six completed stages; numbered colors, summary and CLOSE accepted through r139. All five active 40 C heater targets cleared by Cancel. r141 remote-start cancellation accepted without backup-write/stale-generation notifications. Native harness verifies disconnect/stale-click, retained widgets, Close/reopen and single confirmed cleanup. r169 genuine pending cancellation interrupted by service stop restored unknown; native REVIEW → CONFIRM acknowledged verified completion without commands, preserving filament state | Changed procedure STOP accepted with one 80 ms native injected tap in r179 on installed r178; interrupted Load RECOVER accepted r177, and interrupted cancellation REVIEW/CONFIRM accepted r169/r170. Physical quick-finger-tap feedback remains relevant to the changed input/refresh code. No unnamed additional interruption matrix or repetition of ordinary Cancel/load/unload is required. |

**Validation scope correction:** use this same checklist; retain prior passes.
Every remaining test must name a changed WM+ function/route and the missing
observable result. Existing host/native integration evidence counts for the
behavior it actually exercises; do not demand a live destructive fault or fresh
physical calibration merely to repeat that coverage. Historical entries below
that request general factory/mechanical qualification are superseded by this
scope correction. This does not convert an unverified changed UI path into a pass.
The earlier request for an operator-assisted fresh calibration is withdrawn as a
release prerequisite; physical quick-touch feedback is still relevant.

Unchanged stock behavior, USB copy and profile importing remain outside this
release validation. No new print or deliberate mechanical fault is authorized by
this table. Genuine recovery/interruption context is required for live recovery
checks; do not manufacture production records to reach a screen.

### Release staging preflight — 13 November

Exported current feature revision `d625068` to
`analysis/validation/2026-11-13-release-staging` with the default
`packaging-control-only` scope. The artifact hash matches the installed r198
screen above. Ran that export's `install config preload
--qualify-unreleased-screen --preflight-only` against the printer: config,
Moonraker and preload requirements passed, exact 1.1.13 dependencies passed,
and configuration preservation reported **0 file changes**. No installation,
service restart, heating or motion was performed. This is package admission
evidence, not normal reviewed-release activation; G06 remains pending.

The user is not yet available for direct Retract observation. C03 remains open;
no repeated load/unload cycle was started. Physical quick-touch feedback also
remains pending. The stock caller report's stale G03/R22/R24 presentation labels
have been reconciled to the accepted 13 November evidence.

### Original feature acceptance reconciliation

The R20–R27 table tracks the later stock-integration work; it is not by itself
a complete inventory of the original standalone UI requirements. The existing
A–G acceptance checklist below remains part of this same document. Its unchecked
items require comparison with subsequent evidence before a release-complete claim.
Do not automatically repeat their tests or discard their requirements.

Reviewed accepted evidence: B01 navigation/focus and card layout; B02 metadata
Save/Cancel/stale-draft including color; B05 per-head nozzle editor round trips;
B06 remote metadata; C01 all-head temperature target/zero/X and keypad behavior.
The shared plan's R07/R08/R12/R13/R14/R18 descriptions now distinguish implemented
standalone behavior from deferred openACE work and remaining acceptance limits.
Reconciled B04/D01/D05/F02 against later evidence on 12 November; their original entries now carry current evidence notes. Next review: A02 and the remaining C/E/F/G entries against their later dated results.
This reconciliation is pending; it is not a new validation checklist.

### Standalone delivery staging — r180, not released

The delivery export suite passes all 20 cases after replacing an obsolete
seven-helper count with the exact current eight-helper contract. The exported
installer is exercised in an isolated temporary stock home, without openACE;
customized configuration and filament/loaded/residual-material files survive
update byte-for-byte. This proves package completeness and preservation in that
fixture, not printer-side physical acceptance. The latest whitespace-preservation
fix is included. The conflict report summary now reflects the explicitly deferred
openACE routes instead of retaining them as standalone release gates.

The latest staging destination is `qualification-export-r180` under the
November 12 audit. Its qualification remains packaging-control-only until the
remaining standalone acceptance gates close; do not publish it as fully validated.
Commit `18e72e0` adds the validated standalone-owner installation boundary.
The installed printer remains on r178. The r180 export contains the matching
`be6b976f934260139fca6d405a1970a3f2b3c557970bed42daac55d6213da408`
artifact and current source-bound installer inputs. Export verification passed;
this is packaging evidence, not a new installation or runtime acceptance pass.

### Recovery queue reconciliation — no repeat of accepted actions

`WMP_RECOVERY_RESOLVE` accepts exactly `abandon` and `reconcile`.
Native failed-attempt abandonment passed r149, and native interrupted-resume
reconciliation passed r167. The older phrase “remaining standalone resolution
flows” did not identify a third implementation path and has been removed from
the current queue. `tests/unified_ui/recovery_resolution.cpp` separately covers
lost acknowledgement, authoritative completion, terminal-result retention,
explicit fresh review after a recorded partial failure, and binding drift.
These are existing evidence, not new live tests. The remaining R22 visual gate is
incompatible-record retirement; its historical/malformed record archive behavior
has host integration coverage. Do not corrupt production recovery records merely
to reach that screen. Service-interruption interactions remain separately in R27.

Retirement rendering follow-up: the native LVGL lifecycle harness now explicitly
checks all three numbered retirement stages and the required white future,
gray completed and orange active-readback colors. It also retains the existing
assertions for REVIEW before DISCARD, unavailable-action refusal, duplicate-tap
suppression, retained widgets and terminal CLOSE. The compiled harness passed;
no production code changed. This verifies render properties through fake LVGL
objects, not pixel layout or physical-touch behavior on the printer; that
limitation remains on the R22 visual check.

### Deferred openACE release work

Standalone packaging boundary audit (12 November): `tools/preflight.py`
`config_plan()` validates preserved configuration and the managed runtime include,
but does not reject an active openACE/AFC configuration. The preload preflight
checks package/client compatibility; `_verify_running_backend()` checks backend
protocols and commands, not the active filament owner. Meanwhile
`wm_material.py` retains openACE load dispatch and declines standalone AFC
metadata command registration when an owner is present. Consequently the scope
statement alone does not prevent installing this unqualified combination.
Before standalone publication, enforce and test the supported-owner boundary for
both paired config/preload and preload-only installation. Detect active ownership
and effective included configuration, not dormant files or commented includes;
refuse before publication without disabling or deleting the other manager.
This is a standalone packaging gate, not a requirement to finish openACE support.

The configuration planner now rejects effective `[openace]` or `[AFC]` sections
before publication. Four new cases cover included-manager refusal with no file
changes and dormant/commented-include preservation for both owners; all 79
configuration reconciliation tests pass. This closes the planned-configuration
check for paired installation, not the complete gate: preload-only admission and
an already-running owner whose configuration was subsequently disabled still
need coverage. This local installer change is not deployed or in r176 staging.

Follow-up: `preflight.standalone_owner()` now checks both the running Klipper
`configfile.settings` and the effective on-disk include tree. Both config and
preload preflight invoke it for the current unified bundle, before publication;
legacy bundles retain their existing behavior. A disabled on-disk manager still
requires a Klipper restart if its section remains loaded. No files are removed
or disabled automatically. Configuration/preflight suites pass 110 tests, and
the two additional entry-point checks pass (seven focused owner tests total).
Reconciliation fixtures isolate the live-owner check because they have no
Moonraker; the actual owner admission has separate mocked API tests. Exported
installer integration and live read-only admission remain to be checked before
restaging. These checks do not qualify openACE operation.

Owner-boundary acceptance: all 20 export tests pass, including actual exported
config planning against a temporary stock home, a simulated loaded openACE
section with no disk section, refusal and byte-for-byte file preservation.
The running-state API is mocked in that export fixture; disk parsing and the
exported installer are real. The live printer also passed the read-only loaded
and disk configuration admission (`standalone-owner-admission.json` in the
November 12 audit). No motion, heating, service restart or printer writes were
performed. The standalone installer ownership gate is now covered; this does
not qualify operation with an owner enabled after installation.

Preserve the design and implementation evidence for a subsequent release:
ACE unit/slot UI and drying; owner-managed loading/unloading and source routing;
the direct external-Unload contract and WM+ adapter; supported-owner recovery,
Re-print, calibration, restart and cancellation qualification. The dependency
handoff remains in `openace-external-unload-handoff.md`. Do not require that work
to release standalone WM+, or describe the existing partial adapters as supported.
This scope decision does not waive standalone recovery/physical validation,
Factory/reset decisions, or pending operator-dependent checks. H1 material/source clarification is resolved in the r177 entry below.

### Inserted-versus-empty follow-up

Source inspection confirms Toolheads already renders “Inserted” for a false
loaded flag with `sensor_present=true`, and “Empty” for a clear sensor.
`tests/unified_ui/native_lifecycle.cpp` explicitly checks both transitions and
keeps Load available in both cases. No product code change or repeat of the
accepted native suite is justified by the test-helper mistake. The follow-up
`wait-r175-service-cooling-status.json` confirms Ready/standby, complete operation,
unchanged parked coordinates and all heater targets zero. Physical filament
validation remains held for H1 identification; it is not an active running test.

### Head 1 ACE-assisted preparation — sensor clearance unresolved

The operator confirmed screen Head 1 (`h0`) contains eSun green PLA and authorized
independent ACE feed/retract calls to simulate manual filament handling. Metadata
now reads eSUN / PLA / saved green `#00A651`. The saved route is ace0 slot 0
(screen slot 1), adapter 5B5F011090. Independent device queries returned ACE 2 Pro
V1.1.31 with idle slots while openACE remained disabled.

Preparation, not standalone unload acceptance: at confirmed XY-homed / mounted
Head 1, the temporary helper moved to X=-13,Y=80 without Z movement, heated to
220 C and split the existing PLA tip-shaping moves around the final pull.
Forward assist was stopped and confirmed idle before rollback assist started.
Both extrusion blocks completed; assist stopped and heater target returned to 0.
The head sensor remained present. One additional bounded ACE retract requested
20 mm; subsequent encoder telemetry reported -18 mm, motor length 19 mm and idle.
The head sensor still remained present. No further pull or Load was dispatched;
operator inspection of physical routing and whether the filament is free of the
gears is pending. This does not establish a cleared inlet or pass R26/R27.

Evidence: `h1-confirmed-esun-identity.json`, `h1-manual-ace-preparation.log`,
retained temporary helper `h1-manual-ace-preparation.py`, and
`wait-h1-after-clear20-status.json` / camera frame in the November 12 audit.
The helper is test equipment only, not installed production code. Head 1 remains
mounted at the purge position; all heater targets were verified zero.

Raw-sensor follow-up: `filament_switch_sensor filament0` itself reports
`filament_detected=true`, matching WM+'s `sensor_present=true`; this is not
evidence of stale UI presence. Head 1 remains attached, standby at X=-13/Y=80,
cooling with target 0 (72.88 C at observation). Its loaded flag is not proof of
successful withdrawal; the manual preparation was not a completed managed
Unload and did not observe a clear sensor. Evidence:
`h1-after-preparation-raw-sensor.json`. Physical inspection remains required
before another pull or an insertion-wait Load test.

### H1 interruption attempt — not accepted; physical identity pending

The attempted insertion-wait test did not create an interruption. Before dispatch,
H1 had `state=empty` (loaded flag false) **and `sensor_present=true`**. The test
helper incorrectly treated the former as physical absence. H1 therefore completed
normal XY home, H4 dock/H1 mount, heating to 220 C, feed/purge/wipe and heater-off;
it correctly skipped waiting for insertion. Camera observations covered positioning
and purge-area travel. No service restart was dispatched. This is not an R26/R27
interruption pass and does not reopen or add a baseline Load acceptance claim.

An attempted STOP omitted required `head` and was rejected; the operation
subsequently completed. All heater targets were verified zero, printer standby,
H1 attached. The test helper now requires literal sensor absence and includes
head in cancellation requests. Production STOP code was not changed by this test.
H3/H4 identities and loaded flags remained unchanged. H1 now has a completed-load
flag; the temporary Generic PLA/gray draft has been changed through the public
metadata API to Generic **Unknown**/gray pending operator identification. Its
actual material, colour and extrusion outcome are unverified; do not infer those
from the test draft or use its recorded hotend-material assumption for another
transition without clarification. The user has been asked what feeds H1.

Evidence: `r175-service-before.json` (including the pre-existing true sensor),
`r175-service-dispatched.json`, `r175-service-current.json`,
`wait-r175-service-after-unexpected-status.json`, camera frames, and
`r175-service-unknown-identity.json` in the November 12 audit. Future insertion-wait
qualification requires `sensor_present == false`, not merely `state == empty`.

### Remaining gate audit — model selection and Factory entry

The model startup writer is consistent on the live printer: saved model 2,
active zru-s.cfg, and loaded chamber/door objects agree. This narrows remaining
writer work to model changes/mismatches and other external writers; it is not a
reason to repeat the accepted reboot. Detailed provenance and limitations are in
`docs/upstream-client-callers.md`, “Model-include writer — live consistency audit”.
The user confirms the Factory/Service code is unavailable; password-success
validation cannot currently be performed. Factory reset support is deferred by
explicit user decision, with the existing guard retained. Physical quick-touch
feedback remains pending. Other calibration and discovery gates are unchanged.

### Calibration command/native integration follow-up

After the ACK persistence correction, 138 probe-command, calibration-admission
and native flow/worker tests pass. The asynchronous worker test previously
covered only ACK; it now also exercises RETAIN through background transport,
matching authoritative receipts and duplicate suppression while pending. Both
native executables pass after that extension. HTTP success alone leaves either
operation pending; only its backend receipt settles it. This is offline
integration evidence, not live SAVE/restart or native REVIEW/ACK/RETAIN acceptance.
No printer operation was repeated for these tests.

### Installer whitespace preservation — local installer correction

The r175 plan exposed an unnecessary printer.cfg rewrite: blank lines after the
already-final managed include moved ahead of it. Reconciliation now preserves
all original bytes when only whitespace follows the owned block before
SAVE_CONFIG. New executable configuration after the block still moves the managed
include last, preserving override precedence and the exact calibration suffix.
Three spacing cases failed before the correction; all 75 reconciliation tests
now pass, including rollback/interrupted publication. An outdated seven-helper
assertion was replaced with the explicit eight-helper publication set (including
recovery retirement). This changes the next installer package only and requires
no running-printer restart. Existing r175 remains installed.

### Probe-save ACK invariant — r175 installed

The command layer already requires matching configuration for ACK, but the
persistent journal accepted a fresh mismatched review token. Its older unit test
explicitly allowed that behavior. The journal now enforces the same invariant:
ACK requires matching recorded/disk/loaded configuration with no pending edits;
an eligible differing probe offset requires explicit RETAIN. Four new regression
cases reproduced acceptance before the fix (offset, PID, loaded-only mismatch,
and pending edits), and now refuse without an acknowledgement or evidence change.
The journal and command/config integration suites pass all 97 tests, including
RETAIN, lost acknowledgement and restart handling. No printer calibration or
configuration was changed. r175 installs the correction. The first preload-only attempt refused the
backend mismatch and rolled back; paired config/preload preflight and installation
then passed. The only printer.cfg difference relocates a blank line around the
managed include. Effective settings, all four PID tunes, saved variables,
filament identities/nozzles/mapping and loaded flags are unchanged. The new
backend session is Ready/standby with zero heater targets. Exact calibration
source readback is `21e33f16d15362817be22f323d674ddfdc3addd5ec95132cba8ab6191ebd0434`;
native bootstrap and mapped module are confirmed. Evidence: `r175-preservation.json`,
`r175-native-readback.json`, and the applied r175 installation journal in the
November 12 audit. This activation check does not close live calibration SAVE,
REVIEW/ACK/RETAIN or other-owner qualification.

### Warning restart boundary — joined offline qualification

Eight focused cases join execution of the actual ARM warning predicate with the
retained Klipper command dispatcher and WM+ restart admission. With a cached idle
screen snapshot, current filament/tool, cancellation, recovery, calibration,
pending-submission and error-state holds all refuse before move draining or
process exit. Genuine idle retains the vendor dwell/drain/restart sequence.
Transport delivery is represented by direct dispatch of the warning's verified
literal command; this is not live warning-popup or other-owner acceptance.
`tests/test_stock_restart_boundaries.py -k warning_allowed`: 8 passed.
Read-only reinspection also confirms the openACE direct-unload contract remains
absent; R21's owner integration dependency is unchanged.

### Controlled OS reboot — r174 accepted

The controlled OS reboot returned Ready/standby with a new boot ID. All six
tracked files (`printer.cfg`, `tmt1.ini`, `saved_variables.cfg`,
`wmp_filaments.json`, `wmp_filament_loaded.json`, and
`wmp_filament_operation.json`) remained byte-for-byte unchanged. Effective
settings, saved variables, filament identities and each head's loaded flag were
preserved. H4 remained attached, all heater targets were zero, and the chamber
light returned enabled/available with physical value 1 and no error. The camera
showed the same parked head and clear bed after startup.

Systemd records defaults migration exiting successfully before Klipper, followed
by screen startup. Monotonic timestamps establish ordering; the stale boot RTC
was subsequently corrected, so wall-clock timestamps are not ordering evidence.
Native readback confirms the installed r174 screen/backend hashes, applied
journal and running mapped module. This is OS reboot/startup acceptance, not a
physical power-cut test or qualification of interrupted-operation branches.

Evidence in the November 12 audit: `r174-osboot-{before,after,dispatched}.json`,
`r174-osboot-services.txt`, `r174-osboot-native-readback.json`,
`r174-osboot-native-diagnostics.log`, and `wait-r174-osboot-camera.jpg`.

### Queued short touches — r174 installed

The factory reader loses a press if both press/release frames are queued before
one GUI poll. This was reproduced by executing the actual ARM bytes offline.
The profile-bound interior hook now publishes each pointer SYN_REPORT and uses
LVGL's continue-reading contract to drain the remaining frames in order. Factory
parsing/clamping and keypad behavior remain unchanged. Seven targeted tests pass,
including compiled ARM execution with two queued taps, 100 drag frames, keypad
parity, existing event hooks and profile windows. See `gui-sync-audit.md` for ABI
and lifetime evidence.

r174 is installed. The original 80 ms DONE tap at (714,125), missed on r173,
closed the existing H4 result on the first attempt. The live hook's jump target
matches the compiled symbol. Settings, PID tunes, saved variables, filament
identities/loaded flags and cancellation receipt were preserved. No motion or
filament service was repeated. Physical finger-touch follow-up has been requested;
this does not claim every previous unresponsive interval is explained.
Evidence: `r174-native-readback.json`, `r174-touch-hook-readback.json`,
`r174-touch-preservation.json`, `r174-preservation.json`, and
`navigation-r174-{home,h4,result,result-done}.*` in the November 12 audit.

### Filament progress no-op refresh — r173 installed

The load/unload/Take/Dock progress panel now skips identical data/local-state
refreshes instead of repeating LVGL text/style/geometry updates. Submission,
receipt, selection/plan and action readiness are part of the cache, so local
changes are not hidden while waiting for the next data sync. The focused native
lifecycle regression failed before this change and passes afterward: unchanged
review/heating refreshes retain text-write count, widgets and scroll; local
receipt changes, temperature updates, stale/fresh status, stage transitions and
close/reopen remain functional. ARM build and delivery verification passed with
screen SHA256 `881e4e66ae01782ad92874f7fb3a9435d2c6e5aa994dc21413fcd929c25b3c08`.
r173 is installed with applied journal and exact native artifact/bootstrap
readback. Effective settings, PID tunes, saved variables, filament identities and
loaded state are preserved. The real H4 completed load result reopened through
Home → Head 4 → Result, showing all eight completed stages gray and CLOSE/DONE.
A short injected DONE tap did not visibly close it; a held touch at the same
position did. This supports timing sensitivity for this observation, not a claim
that all intermittent physical-touch failures are explained or fixed. Neither
interaction changed the operation, position, loaded flags or zero heater targets.
Evidence: `navigation-r173-{home,h4,result,result-done,result-done-held}.*`,
`r173-result-preservation.json`, `r173-preservation.json`, and
`r173-native-readback.json` in the November 12 audit. No filament cycle was repeated.
See `gui-sync-audit.md` for scope.

### Chamber-light initialization investigation — 12 November

Read-only inspection found GPIO76 configured as `in`, value `0`, with its value
attribute owned by the Klipper user. The enabled light policy reports EPERM.
This is a direction problem, not missing value-file ownership. The factory
1.1.13 getter at `0x62529c` exports a missing GPIO and reads its value without
configuring output; the high setter at `0x6250d8` explicitly writes direction
`out`, active_low `0`, then value `1`. This establishes a possible partial
initialization route, not proof of which caller produced the current state.

The bridge fallback now reads the existing value attribute without calling the
factory getter, exporting GPIO, or following a value-file symlink. Startup repairs
a missing/input GPIO with the factory OFF initializer, bypassing preference
persistence; an existing output and its level are untouched. The backend remains
the automatic light-policy owner. All 42 focused bridge/backend tests pass,
including missing/input/output initialization, unexpected direction/symlink
refusal, no preference forwarding during initialization, and a factory-getter
trap for status reads.

Qualification package r172 is installed. The existing input GPIO became `out`,
value `1`; saved ON remained unchanged and the policy's EPERM cleared. The camera
frame visibly shows chamber illumination. The applied journal, exact source and
installed light artifact were checked. Effective configuration, all four PID
tunes, saved variables, filament identities/loaded flags, and the resolved
cancellation record are unchanged. No motion or heating was commanded. This
accepts repair of the observed input-GPIO state, not a full OS cold-boot claim.
Evidence: `r172-light-{status.json,diagnostics.txt,artifact.json}`,
`r172-preservation.json`, `r172-native-readback.json`, and
`wait-r172-light-camera.jpg` in the November 12 audit.

### Interrupted cancellation — native acknowledgement accepted, display fix pending

On r169, a verified wait-only job was cancelled through the reviewed endpoint.
Receipt `interrupt_1794518569409978120` was observed pending at `stopping`
before stopping the screen and Klipper services. After restart, the durable
record restored as unknown and the touchscreen automatically showed numbered
stages with REVIEW. Actual REVIEW → CONFIRM selected `acknowledge_complete`
(no printer commands), then recorded complete. H3/H4 identities and all loaded
flags were preserved. Evidence: `cancel-interrupt-{before,receipt,observed}.json`
and `navigation-cancel-interrupt-{ready,review,confirmed}.*` in the November 12 audit.

This qualifies interrupted-result review and command-free acknowledgement only;
remaining cleanup/service/owner cases stay open. The live result exposed stale
orange/white execution stages after resolution. A local display correction
replaces them with completed review/verification stages, without claiming skipped
execution stages ran, and removes a duplicated result message. The restart-aware display regression passes. r170 is installed with an applied
installer journal and exact artifact/native bootstrap readback. Saved variables,
configuration settings, all four PID tunes, identities, nozzle settings, mapping,
loaded flags and the cancellation record were preserved. Evidence: `r170-preservation.json`
and `r170-native-readback.json`. The post-restart native screen returned to Home;
visual acceptance of the corrected terminal panel remains pending.

### r169 native last-object exclusion accepted

Installed artifact and backend readback passed, with unchanged effective settings,
saved variables, all four PID tunes, filament identities/loaded flags, nozzles and
mapping. Before the next test, the genuine interrupted recovery coupon was
reviewed and explicitly archived through the native UI (archive
`92d470ded8689130f16689512337ef17f82bc164ffca36f791ea1d06b39d7954`).
This was test cleanup, not a repeat claim for the previously accepted discard gate.

The uploaded `WMP_LAST_OBJECT_WAIT.gcode` defines one object and waits 30 seconds;
SHA256 `fdac6c5f20aad5b24952e2c544ff3eb8ab720ece76e59dfe4af95b560ea5c00b`.
It contains no motion, heating, extrusion or print-start macro. The first run
completed before selection and is excluded from acceptance. The second run used
native SKIP → object selection → exclusion → Confirm. It entered managed Cancel
print, then completed all six numbered stages with receipt
`cancel_2560841663951_1`. Final native view shows “Print cancelled”, gray completed
stages and CLOSE. Job is cancelled/unpaused, coordinates unchanged, all five
heater targets zero. Camera frames were inspected but dark exposure limits their
independent visual value; job contents and status comparison support no motion.

Evidence: `navigation-r169-object-second-*`, `navigation-r169-object-confirmed.*`,
`navigation-r169-object-terminal.*`, `wait-r169-before-object-*`,
`wait-r169-after-object-*`, and `r169-preservation.json` in the audit directory.
This closes standalone last-object cancellation acceptance. Other-owner delegation
and a genuine remaining stopped-popup route remain open; do not manufacture the
old popup or repeat ordinary completed Re-print to claim that coverage.

### r169 last-object candidate packaged

ARM build passed with screen SHA256
`9df141c520a91cfe7667d5addee3406c9f3b9dbdb9b880bc02e0d06fe4db2f38`.
The focused exclusion suite passes all three cases, including exact firmware
prologue/call verification and execution of the built ARM wrapper with runtime
absent: last-object action is consumed, non-last exclusion delegates, selected
object text remains intact. The earlier Re-print suite also passed. Verified
package r169 was installed after Ready/standby/zero-target admission. Subsequent
native last-object acceptance is recorded above; this build evidence alone was
not workflow acceptance.

### Last-object exclusion cancellation — local implementation

A second genuine stock stop-worker caller was found in `exclude_object()` when
excluding the final remaining object. It quick-stops and clears recovery files
outside the managed Stop-confirmation route. The new profiled entry hook routes
that case through managed cancellation before stock mutation; ordinary exclusion
and confirmed other-owner delegation retain their behavior. Three focused
routing/Re-print tests passed at this local implementation stage. The later r169
build, deployment, and native standalone last-object acceptance are recorded
above. Other-owner qualification remains open. See the caller audit for addresses
and evidence.

### r168 defaults ownership installed and screen restart accepted

Packaged installer journal `1c40c5b14a8c4b98ac4844bce647f010` is applied with
no inflight component. Running native artifact/backend hashes match the package.
Readback preserves saved variables, effective configuration, all four PID tunes,
nozzle settings, mapping, filament identities and loaded flags. The printer is
Ready/standby with zero heater targets. ExecStartPre reports the installed helper
exited successfully before Klipper activation. Both defaults files had no missing
keys and remained byte-identical.

A single screen-only restart changed client PID 10949→11636 while retaining
Klipper PID and backend session. Both defaults file hashes remained unchanged.
This qualifies the changed restart boundary, not a full OS cold boot or every
external configuration writer. No motion, extrusion or print was requested.
Evidence: `r168-preservation.json`, `r168-native-readback.json`,
`r168-defaults-activation.txt`, `r168-screen-restart-before.json` and
`r168-screen-restart-after.json` in the 12 November audit directory.

### Defaults service ownership integrated locally

The current managed installer now publishes the helper and a Klipper
`ExecStartPre` drop-in in the same publication journal as the screen's
`WMP_DEFAULTS_OWNER=1` contract. The helper checks that Klipper MainPID is zero,
serializes its own invocations, recovers interrupted defaults transactions, then
publishes missing defaults before Klipper loads configuration. The exact native
startup merger return address `0x44a258` is suppressed only with that paired
contract and exact command; unrelated shell calls and legacy installations retain
their behavior. Publication rollback restores helper, backend override and screen
override together. Uninstall removes both helper and override.

Affected installer/current-delivery/rollback/startup tests: 141 passed, 17 skipped
(artifact-dependent checks). Defaults tests including the modeled service entry:
17 passed. The ARM build completed with SHA256
`29538e45c7a91d121746a9bfa5165cff42fd7555dd8177c3bb24cf1938e55a8b`.
All 25 exact-firmware restart-boundary checks pass after adding the new getenv
lookup to the emulator. Package r168 was verified; deployment is in progress.
A read-only preview of both live defaults targets was byte-identical (no additions).
Cold-boot and screen-only-restart qualification remain open. This resolves the
local integration task, not its device acceptance.

### Defaults publication and recovery implemented locally

The defaults helper now retains exact before/factory/candidate bytes in a durable
journal before publication. Each target is atomically replaced with its original
permissions and ownership retained, and file/directory fsync completes each write.
Admission and the whole expected snapshot are rechecked between writes. An
interrupted transaction blocks another publication until explicit recovery;
recovery validates the entire candidate and checks both destinations for unrelated
edits before restoring any member. No startup or motion command is sent by this
helper, and admission does not substitute for caller-held writer exclusion.

Fifteen focused tests pass: planner compatibility, interruptions before/after each
file write, exact rollback, subsequent successful publication, idempotence,
concurrent-edit preservation, changed admission and altered-journal refusal.
Service-start ordering, exact stock-call suppression, installer rollback and live
qualification remain pending. The helper is not deployed.

### Defaults migration planner implemented locally

`tools/factory_defaults.py` now plans both factory-default files before any
publication. Existing keys win; original comments, bytes and line endings remain
intact. Invalid/missing inputs, inherited defaults and ambiguous multiline
additions refuse the complete plan. Saved-variable additions must parse as Python
literals. Applying the planner twice is a byte-identical no-op. Seven planner
tests, including the retained 1.1.13 factory inputs, pass; the vendor race
characterization also passes (8 total).

This is not deployed and does not yet close the writer race. Integration must:

1. Execute under backend-start ownership, before Klipper reads saved variables;
   never publish from an independently restarting screen while Klipper is active.
2. Journal both target snapshots and candidates, preserve concurrent edits and
   recover partial publication before allowing backend startup.
3. Suppress the exact stock startup merger call only when the managed migration
   contract is installed; preserve unrelated callers and older delivery behavior.
4. Package/rollback the helper and service dependency together, then qualify a
   screen-only restart and cold boot with preserved managed records.

### Startup defaults writer conflict — implementation open

A disposable-file execution of the retained vendor merger demonstrates that adding
one missing factory key can overwrite a newer backend save, including managed
print context. See the startup defaults merger section in
`docs/upstream-client-callers.md` and `tests/test_stock_merge_config_boundary.py`
(1 passed). This is newly established R23/R26 scope, not a live failure claim.
Backend-coordinated default migration is still required; atomic replacement alone
cannot resolve a stale-snapshot overwrite. No printer action was performed.

### R23 loaded-runtime mismatch qualification

Sixteen new disposable-file cases cover every head after a published same-hardware
migration: a mismatched loaded UUID, heater control mode, PID gain or nozzle
diameter must prevent post-restart acceptance. Each case leaves the publication
journal and configuration bytes unchanged and keeps the unresolved-operation
hold. The complete transaction suite passes: 39 tests. This verifies the existing
runtime acceptance boundary; it does not complete provenance policy, native
migration workflows or external-writer coverage. No production code, printer
configuration, service state or motion changed for these tests.

### r167 activation and interrupted-resume reconciliation accepted

The packaged installer completed and native readback matches the tested screen
and backend. Configuration, filament identities and loaded flags, mapping,
nozzle settings and all four PID configurations were preserved. The restored
managed recovery panel remained visible. Native REVIEW presented the newer
checkpoint confirmation; CONFIRM completed reconciliation at byte 4924 and
changed continuation to `checkpointed`. The screen shows “Recovery checkpoint
reconciled”. Job state remained standby, coordinates unchanged, all five heater
targets zero. No print was resumed. A fresh camera frame was inspected, but its
dark exposure is insufficient for an independent visual no-motion conclusion;
status comparison supplies that evidence.

Evidence: `navigation-r167-held-view.json`, `navigation-r167-review.jpg`,
`navigation-r167-confirm.jpg`, `navigation-r167-confirm.json`,
`wait-r167-reconciled-status.json`, `r167-native-readback.json`, and
`r167-preservation.json` under the 12 November audit directory.

### Cold boot dependency — r167 installed

The requested power cycle exposed a release-relevant boot regression: Klipper's
factory service is disabled, while the screen and Moonraker start normally.
Suppressing the screen's unconditional restart had also removed the factory's
implicit Klipper startup. Readback confirmed inactive/dead Klipper after boot;
one explicit service start restored Ready without another firmware reset.

Current managed-screen installation now publishes `Wants=klipper.service` and
`After=klipper.service` in its existing journaled screen drop-in. This starts a
disabled backend when the screen starts; it does not restart an already active
backend or globally change Klipper's enablement. Legacy screen deliveries retain
their previous drop-in. Rollback restores the exact prior file. All 117 affected
packaging/current-delivery/rollback tests pass. r167 packages this installer fix
with the unchanged r166 screen artifact. Activation and native recovery review passed. A subsequent cold boot with the
new dependency remains unqualified; installation alone does not prove that gate.
Evidence: `r166-boot-klipper-unit.log`, `r167-before-status.json`.

### Shared overlay deletion — local follow-up to r165

The stock warning constructor and close callback clean the entire LVGL top
layer. A regression reproduces a restored recovery hold disappearing after
this external deletion, independently of the startup-dimensions issue fixed
in r165. The panel now reports external deletion separately from deliberate
CLOSE. Runtime re-presents unresolved recovery and cancellation results after
external deletion, failed initial layout, or an active-screen transition.
No review, confirmation, restart or printer operation is automatically submitted.
Explicit CLOSE remains respected. The native lifecycle suite passes with both
recovery and cancellation regressions. ARM build and delivery package r166 are
complete with screen SHA256
`639784de00107392e29630c3cd47d1ddb5185c7871cf45b974fa33d08ec972d0`.
r166 supersedes r165 as the next candidate; neither is installed. The final
readiness check still reports the same MCU reset error and unchanged backend
session. Device qualification awaits the requested power cycle;
see `docs/upstream-client-callers.md` for the exact warning-callback trace.

### r165 UI candidate — packaged, device blocked by MCU communication

Commit `af72cfa` fixes the reproduced restored-hold startup lifecycle. The final
native lifecycle regression passes; the ARM build and sealed delivery package
are complete. Candidate screen SHA256 is
`a57d2f4a823647fea7f54b9da195e145fac76703d799ce5a6e253348dbb8bd1c`.
It is **not installed**; r164 remains the installed candidate.

The installer passed initial dependency checks, then its first Moonraker
inspection refused because Klipper had entered ZRU-B001 shutdown. No component
publication receipt was prepared or completed and preload installation was not
reached. Preserve installer journal
`qualification-export-r165/.wmp-install-journals/576fd447bb054679b1f898a76b40aa0f.json`
as a pre-publication failure record; do not interpret it as an applied candidate.
The trace points to the read-only `MoonrakerService.inspect` call before
`prepare_component` and before either patch installation loop.

The kernel log records `usb usb2-port1: disabled by hub (EMI?), re-enabling...`
at 04:20:06, disconnecting the CAN adapter and other USB devices. Klipper logs
simultaneous MCU timeouts at 04:20:11. This confirms the transport interruption;
EMI is the kernel suggestion, not a proven root cause. Evidence: `r165-kernel.log`.
One explicit
firmware reset was sent after capture; the resulting state is error with
“Failed automated reset of MCU 'mcu'”. A physical power cycle was requested.
No additional reset, motion, heat, or print was sent. Preserve the interrupted
coupon and recovery records for native REVIEW/CONFIRM qualification after
communication is restored. Evidence: `r165-shutdown.log`, `r165-before-status.json`,
`navigation-r165-reset-ready.json`, and `/tmp/wmp-r165-deploy.log`.

The archived stock B checkpoint has hash `680347d0d187cf10`, while its sidecar
still records `d464d84583ca4ef0`; stock A and its sidecar match. This is a real
interrupted publication and must remain rejected. The newer managed execution
checkpoint is independently retained; do not rewrite sidecars to bypass review.

### r164 resumed-checkpoint interruption — device evidence and UI gap

After camera-confirmed bed clearance, the authorized H4 coupon was interrupted
at completed checkpoint 4912, resumed through the native Continue route, and
interrupted again after the resumed worker published checkpoint 4924. The
one-shot watcher stopped the services successfully. The second checkpoint has
the original job fingerprint and the resumed attempt's session; original job,
execution, envelope and stock A/B evidence were archived before restarting.
Evidence: `r164-resumed-interruption/` and `coupon-evidence-r164-resumed-stopped/`
under the 12 November managed audit directory.

After restart, Ready/standby and all five observed heater targets zero were
confirmed. The backend correctly retained the attempt as unknown with an
interrupted continuation. Native REVIEW/CONFIRM is **not accepted**: the stock
prompt remained visible and the managed review was inaccessible. A regression
reproduces loss of the restored notice when the overlay has no dimensions yet;
the local fix retries failed presentation and re-presents after a startup screen
transition, without reopening after deliberate CLOSE. This is not yet deployed
or device-qualified. The native lifecycle suite passes with the new regression.
Preserve the genuine interrupted records for that check;
do not repeat coupon generation to manufacture another context.

Startup status requests initially timed out, then recovered to Ready without
another reset from this agent. The earlier restart's observed external
FIRMWARE_RESTART caller remains an R26 investigation, not an attributed cause.

### r164 combined owner fixes deployed — 12 November

The additional standalone print/filament mutations and paused-owner validator
are now installed together. r163 was packaged but never activated; r164 supersedes
it. Installer completed with applied journal. Exact backend readback is
`4f72c5595a32e967e43ed8d57d2d658939a1929a6f34a2cffe715e7d368904f7`;
unchanged screen artifact is mapped in process 1481744 with bootstrap 11 confirmed.
Ready/standby and zero heater targets; saved variables, all configuration sections,
filament identities and loaded flags, nozzles, mapping, and all four PID tunes
match the pre-install capture. Evidence: `r164-preservation.json` and
`r164-native-readback.json` under the 12 November managed audit directory.

This supersedes the local/undeployed status below. No print, motion or heating
was commanded. The pre-deployment camera still showed the coupon/purge material;
physical reconciliation remains held for clarification. Installed owner guards
are not a claim of qualified AFC-owned workflows or completed release gates.

### Paused standalone owner validation — local, not deployed

A new regression reproduced reuse of a captured standalone pause after AFC
became present. `_paused_filament_origin` now rejects either external manager.
Its shared validation suppresses the standalone paused editor and causes public
CHECK_RESUME refusal while preserving the pause and saved return positions.
All 115 selected pause/resume cases passed, including the reproduced ownership
transition. The existing openACE passthrough is unchanged; no general AFC resume
adapter was added. This fix is newer than the packaged r163 and installed r162.

Audit interpretation: pause capture only records local evidence; the corrected
validator prevents that evidence authorizing standalone service/resume under AFC.
Recovery material leaf checks are reached through public recovery admission that
already checks both managers, so no new live compatibility claim follows from
those leaf checks. Deferred import and owner-specific adapters remain separate.
Do not deploy r163 as though it contains this later pause correction.

### Remaining owner-path audit boundaries — 12 November

The standalone admission corrections do not establish general AFC support.
`cmd_FILAMENT_SERVICE` and `cmd_FILAMENT_SEQUENCE` obtain their standalone plans
through `_filament_plan`, so its installed AFC refusal covers those paths; the
queued service callback plans again before execution. The openACE direct/slot
adapters intentionally retain their explicit owner contract.

Separate unresolved routes remain: pause capture/resume passthrough currently
names openACE, legacy evidence projection names openACE, and pending recovery
material helpers contain openACE-specific tests. Public recovery admission already
checks both managers, but that is not proof of every nested transition. Review
these against supported-owner policy before claiming complete compatibility.
Profile import remains deferred and was not expanded as part of this audit.
No synthetic owner was injected into the live printer for these checks.

### Remaining AFC admission gaps — local, not deployed

The broader entry-point audit reproduced four additional ownership omissions:
standalone print submission, filament metadata editing, legacy operator evidence,
and the internal extrusion primitive admitted AFC. Each now refuses before
its standalone side effects. Existing openACE-specific adapters are unchanged.
The full backend module run passed 1279 cases with one obsolete error-text
expectation failing; after updating that expectation, the six selected owner
regressions and metadata check passed. No further implementation changes followed
that module run. These additional fixes are not in installed r162. The ARM build and verified
`qualification-export-r163` packaging passed; activation is pending. Physical
owner qualification remains open.

### r162 ownership fixes deployed — 12 November

Installed the Take/Dock, filament planning and nozzle-write AFC ownership fixes.
The install journal is applied, exact backend readback matches SHA256
`b3ac2ddf42f71929161f2302cdfd7cb5227299e7fbcb8f409c2612fd1e2a7216`,
and the unchanged screen artifact is mapped in process 1476998 with native
bootstrap 11 confirmed. Ready/standby, zero heater targets, identical configuration
settings and saved variables, identities/nozzles/mapping, all four loaded flags,
and all four PID configurations were verified after activation.
Evidence: `r162-preservation.json` and `r162-native-readback.json` in
`analysis/validation/2026-11-12-managed-audit/`.

This supersedes the undeployed status of the two ownership entries below.
No motion, heating or print was commanded. Physical recovery reconciliation
remains pending bed-camera clarification; host owner tests are not live
owner qualification. Do not repeat installation verification absent a new change.

### Standalone service/nozzle ownership follow-up — local, not deployed

The adjacent-entry audit reproduced two more AFC omissions: standalone filament
planning could offer Load, and the nozzle setter reached configuration storage.
Filament planning now refuses AFC before creating a standalone procedure (openACE
still uses its existing adapter); nozzle writes refuse either external manager.
Tests cover public sequence refusal without a journal and nozzle refusal before
storage. The affected filament/service/nozzle/toolhead/openACE selection passed
412 tests. This does not establish support for AFC-owned service or substitute
for the openACE external-unload contract. These fixes and the Take/Dock owner fix
are packaged in the verified `qualification-export-r162` staging tree. The ARM
build and packaging checks passed; the screen artifact is unchanged. The printer
remains on r161 until deployment; this is not live acceptance of the new guards.

### R25 standalone Take/Dock owner boundary — local, not deployed

The public Take/Dock command checked openACE ownership but omitted AFC, although
its recovery command and status owner projection recognize both. Four regression
cases reproduced AFC admission and dispatch bypasses for Take and Dock. The shared
context check now refuses either owner, both before scheduling and immediately
before macro dispatch. Eight targeted cases cover both managers and both timing
points; dispatch-time refusal also survives journal restoration. All 61 selected
toolhead tests passed. No machine commands occur on the refused paths.

This is local source evidence only. Installed r161 is unchanged; queue this fix
for the next candidate. It does not qualify owner-managed motion or close R25.
The bed-clear reply was followed by two camera reads still showing the coupon and
purge strand; a clarification is pending and no new physical test was started.

### R23 managed-reset scope decision pending

Read-only review reconfirmed the stock reset has effects beyond configuration:
its native prefix clears recovery records, job history and local G-code storage
before shell dispatch. `clear_memory.sh` additionally deletes configuration
backups (`*.bak`, `printer-*.cfg`), G-code/thumbnails, OTA staging and shell history.
`restore_factory_settings.sh` overwrites Moonraker and screen settings, offsets,
macros, hub/extruder configuration, tool-change macros and all four head files.
The commented-out backup command provides no rollback.

A user scope question is pending: preserve calibration/filament/print data with
separate deletion, preserve factory deletion semantics after explicit review, or
defer the full reset while retaining the guard. No option is selected implicitly;
this is a product/data-deletion policy, not authorization to run reset. Do not
implement deletion or claim full reset complete before that decision. The existing
native reset guard remains installed. No scripts were executed on the printer.

### R23 motion/calibration byte preservation — targeted host evidence

The joint head-configuration transaction fixture now contains actual configured
velocity/acceleration, a wipe macro with its feed rate, per-head XYZ offset values,
and a saved mesh block, rather than only a comment mentioning a custom include.
Two tests publish a mapping change using disposable files, reopen its journal,
then either roll back or verify the loaded PID/UUID mapping in a new session.
Both pass; the protected motion/offset/mesh blocks remain byte-identical, and
rollback restores the complete original snapshot.

This establishes byte preservation for these blocks in this transaction only.
It does not establish that offsets/mesh should follow physically moved hardware,
prove external vendor writers preserve them, or complete full managed reset.
No production code, printer configuration, motion, or deployment changed.

### Immediate validation dependencies and independent work

The r161 camera/status read (`wait-r161-clearance-check-*`) confirms the coupon
and purge material remain on the bed, with the printer Ready/standby and all
heater targets zero. The next native reconciliation run requires bed clearance;
the checkpoint watcher is prepared but not armed. Do not start a replacement
coupon on the occupied bed or treat the earlier user clearance as current.

| Item | Next action / dependency |
|---|---|
| Native interrupted-continuation reconciliation | Clear coupon/purge material, create the next genuine recovery context, arm the watcher during preparation, then verify REVIEW/CONFIRM does not resume printing. |
| Factory password-success admission | Factory entry/EXIT is accepted. Service password remains requested; no guessing or reset invocation. |
| openACE direct external unload | Owner implementation contract is missing; see the external-unload handoff. WM+ adapter and owner qualification follow that contract. |
| Reset/topology preservation | Still independent implementation/audit work under R23; refusal alone is not the required supported transaction. Bed clearance is not a blocker to its source work. |
| Calibration save/restart and interrupted service results | Need legitimate calibration/service state for device acceptance. Do not fabricate pending printer records or save the earlier deliberately artificial probe offset. |
| Existing accepted UI baseline | Do not repeat ordinary load/unload, completed Re-print, cancellation, or current-format discard without a relevant changed path. |

This is not a declaration that all remaining work is blocked on the operator.
It separates external dependencies from independent source work and preserves
the full R20–R27 release scope.

### Discard terminal-write failure — host qualification

Three public `WMP_RECOVERY_RESOLVE` discard cases now cover terminal save failure
before writing, after writing, and persistent storage failure. Each retains an
unknown public result and unresolved attempt across journal restoration, preserves
the exact original job/execution bytes in the immutable archive, and keeps the
job invalidated. After storage recovers, only a fresh explicit discard finishes
cleanup; archive bytes remain identical. No motion/heating commands occur.
All three passed against the existing implementation; no production change or
new deployment is required. This closes this host persistence check, not the
remaining native reconciliation or incompatible-record visual checks.

### Recovered-worker final persistence — installed r161

The terminal-write audit found that discard already restores an unresolved hold
on persistence failure, but a resumed SD worker's final outcome write did not.
A failed write could leave its in-memory attempt resolved. The worker now retains
an unknown outcome and attempts to persist that hold before propagating the
original error. It does not replay SD commands or invoke stock CANCEL_PRINT.

Three completion regressions reproduced the issue before correction (before-write,
after-write, and persistent failure). Expanded coverage applies those failures
to completion, deliberate pause and cancellation: nine cases prove the print body
executes once, the hold remains, and journal restoration remains unresolved.
Twenty-two focused worker/full-chain/reconciliation tests passed. Installed as r161, journal `07b8ddd5218c4248b38501e8fc598fee`.
Exact backend/module readback passed. Ready/standby, zero targets, unchanged
settings and saved variables, all four loaded flags and PID settings preserved.
Evidence: `analysis/validation/2026-11-12-managed-audit/r161-preservation.json`
and `r161-native-readback.json`. Best-effort persistence cannot
guarantee disk rollback if storage fails after replacement and also rejects the
unknown-state write; the in-process hold is retained in that case.

### openACE direct-unload dependency rechecked

The current sibling owner source still explicitly rejects direct-loaded heads in
its unload coordinator; no supported direct-unload capability was found. The
[external unload handoff](openace-external-unload-handoff.md) records the actual
call chain, required owner outcomes, WM+ adapter work and acceptance scope. R21
remains open; no sibling files or printer state were changed.

### Historical recovery format disposal — host integration accepted, 12 November

Seven public-path integration cases now cover execution formats 1, 2 and 3 with
their actual missing historical fields, unsupported newer format 99, missing,
empty and malformed execution records. Each starts from generated completed
execution evidence and stopped-printer admission. Continue refuses; review leaves
all evidence unchanged; separate confirmation archives the exact original bytes
and explicit absence entries, changing only the native offer flag. All other
source records remain untouched. Receipt restoration after a backend session
change remains complete, and the discarded evidence cannot Continue. No machine
commands are emitted. All seven cases passed.

This validates the implemented compatibility policy: explicit retirement with
archival, never synthesizing historical state to auto-migrate a saved print.
The queue now names the remaining native incompatible-record retirement check
instead of implying an automatic migration is still to be implemented. The r156
native discard acceptance used a genuine current-format interrupted print; it
is not relabeled as historical-format visual acceptance. No printer changes or
new deployment were needed for these tests.

### r160 native reconciliation attempt — timing window missed

The authorized coupon created a completed checkpoint, was interrupted, and
returned to the native recovery prompt. Native Continue resumed the real worker
and published newer execution evidence. The short coupon finished before the
second interruption reached it. The interruption helper refused because the job
was no longer printing; no second stop/restart was executed. Readback is Ready,
complete, all five heater targets zero. **Reconciliation remains unvalidated.**

Evidence is under `analysis/validation/2026-11-12-managed-audit/`: the
`coupon-evidence-r160-stopped` and `coupon-evidence-r160-resumed` directories,
`wait-r160-resume-terminal-status.json`, and corresponding camera captures.
The next attempt needs a bounded watcher armed during recovery preparation,
once the native Continue request has an attempt ID, that stops only that resumed
job after a newer durable checkpoint is published. Do not
count this as another required ordinary Continue-to-completion acceptance.
The completed coupon and purge material must be cleared before a new coupon.

Prepared `tools/watch_recovery_checkpoint.py` for that next attempt. It binds the
exact attempt/session/file/hash, requires resumed printing and a strictly newer
completed checkpoint, rechecks status immediately before stopping, captures the
pre-stop evidence, and never retries the stop or restarts services. Read-only is
the default; stopping requires `--stop-services`. Nine host guard tests passed.
The watcher has not been armed on the printer; bed clearance is pending.

### Recovery reconciliation persistence failure — local correction, 12 November

Review before the remaining native reconciliation test found that its terminal
journal write could fail after updating memory to complete, releasing the recovery
hold despite the public operation reporting an unknown result. Reconciliation now
restores the original unresolved receipt in memory and attempts to restore it on
disk before propagating the storage error. It issues no motion or heating commands.

Three new public-command regressions reproduced the defect before the fix: failure
before writing, after writing, and persistent write failure. All three now pass,
including journal restoration after restart; the focused reconciliation/public
resolution suite passed **41 tests**. This does not prove rollback survives every
possible storage failure after a successful replace. The in-process hold remains
unresolved even if rollback also fails.

Deployed as r160 using installer journal
`12c4a00b10b9434980eb37561153e173`. Post-activation readback is Ready/standby,
all targets zero, all four loaded flags and PID settings preserved, identical
saved variables and no changed configuration sections. Evidence:
`analysis/validation/2026-11-12-managed-audit/r160-preservation.json`. Native
reconciliation qualification remains open: it needs a genuinely resumed worker,
a newer completed execution checkpoint, and a subsequent interruption/restart;
an early preparation STOP cannot exercise it. No new print or motion was started
for this inspection.

### Native Factory entry — password boundary reached, 12 November

The verified About → Device three times → Version five times gesture opened the
actual Factory Mode password screen on r159. EXIT returned to Home. Readback
confirmed Ready/standby, unchanged backend session and commanded position,
unchanged saved variables, all heater targets zero and probe editor idle.
No password, calibration, motion, save or restart command was submitted.

Evidence: `navigation-r159-factory-{about,entered,exit}.jpg`, corresponding status
snapshots and `r159-factory-entry-verification.json` in the audit directory.
This accepts only real entry/navigation; password-success admission and Factory
calibration routing remain open. The operator has been asked for the service
password. This dependency does not block independent release work.

### r159 combined activation — 12 November

The durable toolhead record and recovery-session control fix are installed.
Applied installer journal: `b975436044914df496bf29a0a54b2311`.
Exact backend SHA256:
`5ea2bdb8406238042d6ba9d359ccb3d2b9d09abebeb7e4936e6421ee0be5568f`.
Screen PID 1457580 loaded the current artifact and passed native initialization.
All 19 tracked file hashes, effective settings, saved variables, loaded flags,
filament identities, nozzle metadata, mappings and four PID configurations were
preserved. Printer Ready/standby, unpaused, all heater targets zero. No motion or
print was issued; the installer performed its activation restart once.
Evidence: `r159-preservation.json`, `r159-{before,after}-file-hashes.json` and
`r159-native-readback.json` in the 12 November audit directory. This closes
activation only, not live interrupted Take/Dock reconciliation.

### Recovery controls after backend restart — installed r159, 12 November

Integration review of durable Take/Dock exposed an existing UI session bug: after
an accepted recovery request, `recover_sent_` remained true when the same operation
ID was restored in a new backend session. Reopening the result could therefore
leave RECOVER unable to submit. The controller now resets queued/sent recovery
and cancellation state when explicitly binding the restored operation to its new
session/owner/helper session, not just when the operation ID changes. A late
response from the previous binding is ignored.

The regression reproduced the locked control before the fix. Controller cases
cover standalone filament, standalone Take/Dock and openACE helper-session changes,
each with a completed old reply and a late old reply. Reopening sends nothing;
only a fresh explicit RECOVER sends one command using the new session, with
repeated clicks blocked. Existing native recovery-panel lifecycle tests also pass.
Validation: 2 compiled suites passed in 44.04 seconds. This fix and durable
Take/Dock were activated together in r159. Live interruption qualification remains
open; controller/native test results do not substitute for that check.

### Durable Take/Dock operation record — installed r159, 12 November

R25/R26 review found that `toolhead_operation` was only in memory. Restart erased
an uncertain Take/Dock result even though attachment and a stock fault could
remain unresolved. The local change writes `wmp_toolhead_operation.json` before
registering the motion callback, using an atomic replacement and file/directory
fsync. The existing callback persists its result; explicit sensor reconciliation
also persists before acknowledging success.

Startup restores interrupted running/unknown requests as unknown under the new
session, retains the previous session and request ID, and issues no commands.
Completed or explicitly reconciled results remain terminal. Invalid journals
fail initialization rather than silently removing a hold. Failed intent, result
or reconciliation writes retain unknown in memory, remove recovered status and
attempt to record the unresolved result. New Take/Dock remains blocked.

New tests cover queued/in-motion process loss for Take and Dock, terminal
restoration, storage failure before/after replacement or persistently, corruption,
and explicit reconciliation surviving restart. Focused toolhead/filament checks:
149 passed. Full backend run: 1,227 passed, 16 could not run without Jinja2; those
16 passed on a dependency-corrected rerun. No physical actions were performed.
This change is installed in r159. Existing successful Take/Dock acceptance does
not establish this new interruption persistence path.

### Final load/unload result persistence — installed r158, 12 November

The shared `_execute_filament` finalizer had the same admission gap as explicit
cleanup: a failed final journal write left `complete` or resolved `failed` in
memory. Six new regression cases reproduced it for completion and stopped results,
with failures before writing, after writing and throughout storage access.

The finalizer now restores `unknown`, removes the recovered flag, reports the
recording failure and attempts to persist that unresolved state before propagating
the original error. It does not repeat motion, extrusion or the operation body.
The regressions verify blocked new Load admission and restoration from the actual
journal. Focused persistence/recovery checks passed 34 cases; the broader shared
load/unload/filament suite passed 229 cases. This is local fault-injection evidence;
the fix is now installed in r158 (screen binary unchanged).
Exact backend SHA256 is
`e2d84ad8a51d63c39e2e3a5c8d4df8a6f107d48280047699aa03dd1c2b904a18`.
Activation journal `3011db2eb1024c309f2c547baf5c9fcf` is applied; screen
PID 1453076 passed native initialization and mapped-artifact verification.
All 19 tracked files, effective settings, saved variables, filament loaded states,
identities, nozzle metadata, mappings and all four PID configurations were preserved.
Printer Ready/standby, all targets zero. Evidence: `r158-preservation.json`,
`r158-{before,after}-file-hashes.json`, and `r158-native-readback.json` in the
12 November audit directory. The installer performed one activation restart;
no motion or print was issued.
Accepted physical load/unload cycles do not need repeating for this storage-error
path; production storage failure will not be induced to validate it.

### Interrupted filament cleanup persistence — installed r157, 12 November

Review of R27 found that `WMP_RECOVER_FILAMENT` set `state=failed` and
`recovered=True` before persisting its terminal result. A write failure escaped
with that resolved state still in memory, releasing the service hold despite the
failed acknowledgement. The regression reproduced the failure for both present
and absent inlet filament.

The handler now restores `unknown`, removes the recovered flag, keeps the
verification stage active and reports a command error if terminal persistence
fails. It attempts to persist the unresolved result, retaining the in-memory hold
even if storage remains unavailable. Cleanup never replays extrusion or motion.

Focused tests passed: 28 cases, including failure before the terminal write,
after the write, and persistent storage failure; blocked new service admission;
restoration from the actual journal; and explicit cleanup after storage recovers.
Only M400 and the owned heater-off command occur. This is fault-injected host
validation, not live storage-failure qualification. The correction and completed-
discard wording cleanup are installed together in r157. Exact backend/source and
mapped touchscreen hashes were verified after activation (screen PID 1448905,
applied journal eae57523a91440f797b07976519b2512). All 19 tracked files, effective
settings, loaded flags, identities, nozzle metadata, mappings, saved variables and
PID settings were preserved. Printer Ready/Home, all heater targets zero.
Evidence: `r157-preservation.json`, `r157-{before,after}-file-hashes.json`,
`r157-native-readback.json` and `navigation-r157-installed.jpg` in the audit directory.
No motion or print was used; the installer performed its required activation
restart. Accepted physical workflows were not repeated for this failure-path fix.

### Original recovery prompt Cancel interception — installed r156, 12 November

The pinned 1.1.13 popup callback (kind 3) calls `reset_plr_files()` at
0x530500, then queues `PARK_CURRENT_TOOL` at 0x53052c when Cancel is pressed.
This bypassed managed archival and could move the head while discarding recovery.
The replacement consumes that Cancel before the vendor prefix and opens the
managed REVIEW → DISCARD flow. It retains the original prompt underneath the
opaque review; backing out preserves the saved print. Pending or uncertain
retirement cannot expose Continue; explicit readback resolves uncertainty.
Only verified completion dismisses the original popup, bound to its generation
and button identity. Ordinary Continue retains the existing early managed bridge.
No review or status update submits a discard automatically.

Targeted callback/lifecycle tests cover stale taps, no-command review, cancelling
review, duplicate confirmation, pending-close refusal and verified dismissal.
Host checks passed (14 focused tests plus 2 callback ownership tests). The r156
installation preserved all 19 tracked files, loaded flags, filament/nozzle metadata,
PID settings and mappings; journal 0e74987150de4b5ca9aa999a23d8e2f3 is applied.
Native qualification passed on a genuine interrupted coupon:

- Job `wm-1314743389-3310837408-1`, fingerprint `0f5cfa8e61db4e96`,
  completed execution position 6553; stock A/B positions 9368/8610.
- Original Cancel opened the managed three-stage review. REVIEW → CANCEL
  restored the native prompt. All nine records remained byte-for-byte identical.
- A fresh Cancel → REVIEW → DISCARD completed once as
  `discard_295233186936572` with a version-2 retirement receipt.
- Archive `c0dde1e37c504db3949ad910652974ccc8c157dd7edd3acc94b2e168c9c9887a`
  contains all nine original records exactly. Only the live offer flag changed
  from True to False. Closing returned to Home without the recovery prompt.
- No commanded position change or heater target occurred during review/discard.
  Camera monitoring covered coupon preparation, deposition and discard.

Evidence: `r156-raw-*.json`, `r156-raw-discard-verification.json`,
`navigation-r156-{native-cancel,review,review-cancelled,review-2,discard-confirmed,discard-closed}.jpg`,
and `coupon-evidence-r156-interrupted/` under the 12 November audit directory.
Post-discard idle restart also passed: Ready/Home with no recovery prompt, the
archive unchanged, version-2 retirement restored complete and all heater targets
zero. Stock startup changed the disabled offer filename to `hanzao`, but kept
`was_interrupted=False`; the archived original offer remains exact. See
`r156-raw-discard-restart-verification.json` and `navigation-r156-persistence-ready.jpg`.
This raw-discard
path is distinct from the previously accepted valid-attempt STOP → DISCARD flow.
The user subsequently cleared the partial coupon and purge line. A fresh camera
check confirmed the visible bed clear; the printer was Ready/standby, unpaused,
with all five heater targets zero. Evidence: `wait-bed-cleared-r157-camera.jpg`
and `wait-bed-cleared-r157-status.json`. This clearance check issued no motion
or restart and does not constitute another functional acceptance test.

The completed screen retained the pre-review explanatory sentence. A local
presentation-only correction hides that obsolete sentence once retirement is
complete; its retained-native lifecycle check passed (1 test, 35.36 seconds). It
was subsequently installed in r157 and does not reopen the physical discard test.

### Probe reporting corrections — installed r156, 12 November

The editor now displays Z to three decimals, preserving the 0.005 mm adjustment
resolution without raw floating-point noise. A matching fresh session/request/
sequence and running phase confirms command delivery while retaining pending
completion; subsequent transport timeouts cannot replace that receipt with an
unknown-delivery warning. Stale and prior-action status cannot clear uncertainty,
and each new action resets the delivery evidence. ACCEPT that finalizes as aborted
now explains that the position was not accepted and gives adjustment guidance.

Controller, transport worker and retained native UI tests passed (3 tests,
39.98 seconds), including late transport errors, stale/old sequence status,
ACCEPT rejection and rounded rendering without widget recreation. These are
reporting changes; they do not require repeating r155's physical acceptance.

### r155 native probe ACCEPT/DISCARD — accepted, 12 November

The exact r155 screen artifact is installed and running (PID 1433859); journal
`a76e02d0a6f946cf81a9edd3eeeb68c1` is applied. All 19 tracked files, effective
settings, four PID tunes, filament identities/loaded states and mappings were
preserved by activation. The previously disabled probe START became enabled
with the same abandoned recovery record, confirming the admission correction.

Camera-monitored native request `e8694a8d26d86a4fcf645bb8938b50b5` completed
preparation, a -0.1 mm adjustment (4.501875 to 4.401875 mm), ACCEPT and DISCARD.
ACCEPT produced a temporary pending `probe.z_offset = -4.900`; this deliberately
un-calibrated test value was never saved. DISCARD cleared it and the manual
probe. Readback verified identical pending/config/effective settings, unchanged
printer.cfg SHA256 `5c434f7209f5f2a20f9d1f08d9b9603df33af974a588a66bf3ce6b282723ec75`,
unchanged filament data and calibration session, and all five targets zero.
The panel was closed. No SAVE or additional restart occurred during the test.

An earlier request moved +0.1 mm and ACCEPT correctly aborted: the retained
manual-probe helper requires a position below its starting height. That attempt
had no pending configuration and is not counted as ACCEPT/DISCARD acceptance.
The second explicit request corrected the test precondition. No paper-contact
calibration or calibration accuracy claim is made.

Evidence: `probe-r155-before.json`, `probe-r155-accepted-2.json`,
`probe-r155-discarded.json`, `r155-probe-accept-discard-verification.json`, native
screenshots `navigation-r155-probe-*` and camera frames `wait-r155-probe-*` in
the managed-audit directory. R24 SAVE/post-restart review remains separate.
The UI reporting follow-ups observed here are addressed in the local correction
recorded above; deployment is tracked separately from this accepted cycle.

### Post-discard Maintenance admission correction — installed r155, 12 November

The next native ACCEPT/DISCARD check exposed START remaining disabled in the
idle probe editor after the r153 recovery discard. The live backend reported
`abandoned` and no unresolved recovery, but the screen projection shared the
cancellation terminal-state list (`complete`, `failed`) with recovery. This
incorrectly kept the Maintenance hold active after explicit recovery disposal.

The projection now recognizes each protocol's terminal states: recovery uses
`complete`/`abandoned`, cancellation uses `complete`/`failed`. Unknown or
cross-protocol states remain held. The focused projection regression reproduced
the original defect and passed after the correction. The native lifecycle test
also verifies that a stopped receipt blocks Maintenance and resolving a closed
receipt releases it without reopening the panel or sending commands (35.57 s).
The initial lifecycle fixture incorrectly inspected a panel after closing it;
that test sequencing was corrected before this passing run.

No calibration BEGIN was dispatched on r154. The r155 installation and native
ACCEPT/DISCARD outcome are recorded above.

### r154 raw-discard implementation installed — 12 November

Follow-up host validation exercised the screen worker with all nine record
identities/hashes and a version-2 receipt carrying `offer_after`, rather than an
empty manifest. Review, explicit confirmation, lost command reply, result
refresh and restoration passed; only one discard command was dispatched. The
focused compiled test passed (4.46 seconds). This is transport/worker evidence,
not device acceptance of the remaining raw-record UI workflow.

The operator subsequently confirmed the bed cleared. Read-only status showed
Ready/standby, unpaused and all heater targets zero. The camera remains occluded
by the head, so bed clearance is operator-reported, not visually verified.
No restart, motion or print was issued for this follow-up.

Screen SHA256 `ba43cf931afd35fbfb66f3df3d5f981caa4905db07dad0adee49f3cbebc29169`
and retirement-module SHA256
`37dfa3eaa4bc7128f36dd5d15446ac5ab70f4f6b7d5d70d062b2ae0342565664`
match exact readback. Installer journal `17ffb6e7ac054b66be1315910ddac670`
is applied; the current screen maps the expected libraries and native bootstrap
is running. Ready/standby, unpaused and zero heater targets; all 19 tracked files,
effective configuration, PID settings, identities, loaded flags, mappings and
cancellation record are unchanged. Evidence: `r154-preservation.json`,
`r154-native-readback.json` and file hashes in the managed-audit directory.

The installed read-only retirement review returned nine records, including the
native offer (`r154-raw-review.json`). No confirmation was sent. The retained
attempt is already abandoned and its offer disabled, so it is not an enabled
malformed/older-record prompt with which to qualify the new native cleanup.
No production evidence was fabricated and no motion or print was started.
Device acceptance of that separate workflow remains open.

### Raw DISCARD clears the reviewed native offer — local, 12 November

After exact-byte archival, raw retirement now atomically changes only a valid
reviewed native `was_interrupted=True` flag to `False`. A version-2 receipt binds
the original archive and the resulting offer identity/bytes. Other evidence
must remain unchanged throughout publication. Missing/already-disabled offers
need no rewrite; malformed offers are archived but refuse cleanup. An older
archival-only receipt cannot claim a still-enabled prompt was cleared.

Write failures remain uncertain. Before offer replacement, a confirmation may
be retried against unchanged evidence; after replacement but before receipt
publication, the stale confirmation refuses and a fresh explicit review is
required. After receipt publication, readback confirms the result without
repeating cleanup. Immutable original archives survive every tested case. The
screen restores version-1 and version-2 receipts without automatically sending
commands; unknown receipt versions are not adopted.

Validation: 464 recovery/retirement tests passed before final archive-shape
checks; all 47 final store tests and 16 public backend retirement tests passed,
including malformed jobs, concurrent offer replacement and sync failures at
each new publication boundary. The compiled native retirement worker test also
passed (4.46 seconds), including restored version-2 history with zero command
dispatch and rejection of an unknown version. This is local evidence, not installed native
acceptance; r153 remains installed. The valid-attempt r153 physical result is
not being repeated for this separate raw-record path.

### Native offer included in raw-evidence review — local, 12 November

`EvidenceStore` now snapshots and archives `plr.ini` with the other raw records.
A changed offer invalidates confirmation, and its exact bytes are preserved
without requiring malformed job JSON to parse. The same bounded regular-file,
no-symlink and repeated-read checks apply. Earlier eight-record archives remain
readable: their full retirement matches only when no unreviewed offer exists;
their unchanged attempt-only retirement remains scoped to that attempt.

Focused store/backend retirement tests: 42 passed. After adding offer-specific
unsafe-file cases, all 33 store tests passed. This is an archival prerequisite,
not prompt cleanup: raw retirement still needs guarded offer deactivation and
durable partial-write/retry semantics before it can claim that outcome. Local
only; the installed r153 valid-attempt flow is unchanged.

### r153 native discard survives restart — accepted, 12 November

The authorized Head 4 coupon produced genuine completed execution at offset
10911, job `wm-1392533256-333681677-1`, fingerprint `65825acf27bfcf12`.
Original records were captured before restarting the stopped services. Native
Continue entered managed recovery; STOP completed after X/Y homing and before
`machine_frame`, heating or extrusion. Native DISCARD→CONFIRM produced durable
`abandoned` state for attempt `screen_291203372210276` and cleared print context.

Before restart, exact readback verified that only the matching offer's
`was_interrupted=True` changed to `False`; native A/B and coordinate sidecars
were unchanged. Archive
`b6b83738a4c269afde92a24d793a16584748eb1ac55cef60e0f6b5c722e075af`
contains the exact original job, execution and offer bytes. After one deliberate
idle restart, the native screen reached Home without the old recovery prompt;
the offer remained false and the managed attempt remained abandoned. Stock
startup changed `plr_file` to `hanzao` and changed A/B records; sidecars and the
immutable archive remained unchanged. Therefore post-restart acceptance is
prompt retirement and preserved archive, not unchanged stock working files.

Evidence: `r153-discard-verification.json`,
`r153-discard-after-restart-verification.json`,
`navigation-r153-after-discard-ready.jpg`, `wait-r153-final-status.json` and
`coupon-evidence-r153-interrupted` in the managed-audit directory. Final state:
Ready/standby, unpaused, all five heater targets zero, no active sampler. The
partial coupon and purge line must be removed before another print. The camera
is occluded by the head at its post-homing position; no extra movement was sent.

This closes the matching abandoned-job stale prompt check and the tested native
STOP/discard flow. It does not close all R22 migration, failure or owner cases.

### r153 installed; targeted discard qualification started — 12 November

Backend SHA256 `aa310e8a1203080e4b99898260efb4729941ef911ba04031dd06e08294d89d55`
is installed with the unchanged screen binary. Journal
`2f56fbafa796478eb96fac77bb806530` is applied; exact backend/library readback and
native bootstrap passed. All 19 tracked files, effective settings, four PID
configurations, filament identities/loaded flags, mappings and cancellation
record are preserved. Evidence: `r153-preservation.json`,
`r153-native-readback.json` and before/after file hashes in the managed-audit
directory.

After the user's second bed-clear confirmation, the camera showed both the
coupon and purge line removed. The exact previously reviewed 46366-byte coupon
was selected through native preview, mapped to loaded Head 4 and started once.
This run targets interruption→discard→restart prompt retirement; it does not
repeat the accepted full recovery-to-completion baseline. Qualification is
in progress, not accepted. Startup camera/status: `wait-r153-startup-1-*`.

### Recovery startup archive failures retain review access — 12 November

The startup path already preserved malformed records and exposed a review hold,
but an archive or interrupted-state publication failure escaped initialization.
It now retains the saved evidence, reports `Saved recovery requires review`, and
creates no executable attempt. The same unresolved-state guard blocks commands;
startup does not retry the failed write or replay a stage. This keeps the existing
evidence-review path available when storage is unavailable or an external writer
changes the record during startup.

Focused startup/archive/retirement validation: 22 passed, including archive-link
failure, conflicting immutable archive, changed source bytes and failed attempt
publication. Each verifies retained bytes and the command hold. The broader
backend recovery selection also passed: 406 tests in 50.08 seconds. This change
was subsequently installed in r153 above; failure cases were exercised locally,
without injecting storage failures into the printer.

### r152 abandonment-offer cleanup installed — 12 November

Backend SHA256 `b70dafee70f4c004eecee63a68475c810ae759740c976fc7fd65d1114c6fe72e`
is installed; exact source/library readback and native bootstrap passed. The applied
installer journal is recorded in `qualification-export-r152`. Independent readback
shows Ready/standby, unpaused, all heater targets zero, unchanged effective settings,
all four PID configurations, identities, nozzles, loaded flags and physical mapping.
All 19 tracked files and saved variables are unchanged. Evidence:
`r152-preservation.json`, `r152-native-readback.json`, before/after file hashes and
`navigation-r152-ready.jpg` in the 12 November managed-audit directory.

This is deployment/preservation evidence only. A targeted native DISCARD followed
by restart must still prove that the matching prompt stays retired. No motion or
print was started during deployment. The r151 coupon remains on the bed; clearance
has been requested before another physical job. The accepted r151 full continuation
path does not need repetition for this abandonment-only change.

### Matching native recovery offer retired on abandonment — local, 12 November

The exact retained 1.1.13 startup path calls `if_need_plr` (`0x62aa34`), which
reads `[plr_print] was_interrupted` in `TM_T1/bin/plr.ini` and tests for `True`.
Only then does startup load A/B and draw popup 3 (`0x642298`). Managed abandonment
previously invalidated its own job but left this stock offer enabled.

The local backend now reads and binds an enabled offer to the abandoned attempt's
file (exact relative path or its exact SD-root absolute path), preserves the
original INI bytes in the immutable recovery archive, and atomically changes only
`was_interrupted=True` to `False` after managed cleanup. A/B checkpoints and their
sidecars are untouched. Missing/already-disabled offers need no write; conflicting
files or malformed metadata refuse. Changed bytes or failed publication retain an
unknown attempt for explicit retry. Older two-record archives remain readable;
retry upgrades preserve their original bytes in a new immutable archive.

Read-only device inspection confirms the stock file is root-owned mode 0644 but
its containing directory belongs to the Klipper user, allowing atomic replacement
without a new privileged command. No live metadata was changed for this check.
Validation: 406 backend recovery tests passed; after the archive read-bound change,
23 focused abandonment/archive tests passed. Tests cover read-only review, matching
flag cleanup, unchanged checkpoints, original-byte archival, conflicting-file
refusal and publication failure followed by explicit retry. Not deployed or
physically accepted. Generic raw-evidence retirement remains a separate path.

### r151 native recovery through print completion accepted — 12 November

A fresh Head 4 coupon was started through native preview and interrupted after
completed execution publication. The genuine job is `wm-1295074218-3383578307-1`,
fingerprint `1294cfd56d536e1e`, with completed execution at file offset 10290.
Original records were captured in `coupon-evidence-r151-interrupted` before the
single service start. After Ready, native Continue was tapped once.

Attempt `screen_289019079758205` completed all 21 preparation/handoff stages,
including purge, wipe, physical return, exact-file selection, deposition restoration,
routes and accounting. `wait-r151-recovery-4-status.json` captured actual resumed
printing at offset 12538 with mapping `[3,1,2,3]` and a publishing completed-motion
observer. `wait-r151-recovery-5-status.json` records continuation `complete` at
46366 (full file size), no error, print state complete, unpaused and all five heater
targets zero. Native `navigation-r151-resumed.jpg` shows Print Completed. Camera
monitoring continued through startup, interruption, recovery and completion; the
final frame shows the blue-gray coupon and purge line on the bed. The head briefly
occluded the camera during recovery heating, then the view returned at purge.

This accepts the tested standalone native Continue-to-completion path, not all R22
failure/resolution, migration or owner paths. Do not repeat this successful baseline
without a relevant change. The coupon and purge line remain on the bed; obtain bed
clearance before another print. No further motion was issued after completion.

### r151 deployed; fresh recovery test running — 12 November

Installed backend SHA256
`6682a656a45305fb0929756a631a336743371c816a251857c755eaaa57283927`.
Applied installer journal and exact native/backend readback passed. Effective
configuration, all four PID configurations, identities, nozzles, loaded flags and
physical mapping are preserved. Eighteen of nineteen tracked files match; the only
saved-variable difference is startup `probe_tool: 3 -> 0`. The previous attempt was
explicitly abandoned before deployment. The new native coupon start is mapped to
Head 4; actual resumed execution remains unverified. Evidence: `r151-preservation.json`,
`r151-native-readback.json`, and `navigation-r151-print-start.jpg`.

### Recovery file-selection announcement conflict fixed locally — 12 November

The retained exact 1.1.13 client identifies the clearing path: its
`parse_gcode_response` branch matches `File opened:` at `0x63d978`, writes
identity route backups, then calls `reset_plr_files` at `0x63dc48`. The retained
vendor `_load_file` emits this announcement synchronously through its command's
`respond_raw`; the screen processes it asynchronously. This explains why internal
recovery selection succeeded before a later integrity check observed cleared
native checkpoints.

WM+ now filters only the exact expected `File opened:<bound path> Size:<bound size>`
and `File selected` messages on its private recovery loader command. Other
responses/errors and ordinary file selection remain unchanged. The immutable
checkpoint guards remain enabled. The retained vendor-loader tests cover exact
file/seek behavior, no announcements during recovery, unexpected notice forwarding,
and unchanged ordinary file announcements: 35 passed. The broader backend recovery
suite also passed: 401 tests (801 unrelated tests deselected). Not deployed or physically
accepted yet; resumed execution remains open.

### r150 physical preparation passed; continuation refused — 12 November

The fresh interrupted coupon reached and completed purge position, prime, wipe,
return XY/Z, mesh/parser restoration and exact-file selection. Continuation stopped
at `restore_deposition` with `Recovery selection changed before continuation`.
Current readback is Ready/standby, unpaused, file position 9959, all five heater
targets zero. Camera confirms the head remains at the recovered position. Actual
resumed printing is **not accepted**.

Read-only evidence in `coupon-evidence-r150-stopped` shows the committed managed
job and completed execution records remain intact, while both native `plr_data`
files now contain zeroed checkpoints. Their coordinate sidecars still contain the
original hashes. This explains the immutable-selection refusal; the clearing
writer and its timing still need attribution before changing the guard. Do not
weaken the guard or replay this interrupted job after the user's bed-clear report.
Evidence: `wait-r150-current-status.json`, `wait-r150-current-camera.jpg` and the
stopped evidence directory under `analysis/validation/2026-11-12-managed-audit`.

### r150 coordinate fix installed; fresh coupon underway — 12 November

Backend SHA256 `554e771821875aece8a50054b0a2318739f278b413df7c46e5accef796afe155`
is installed from `qualification-export-r150`; screen/recovery libraries remain
at their verified r149 hashes. Journal applied, native bootstrap and loaded module
readback passed. Effective settings, PID, identities, nozzles and loaded flags are
preserved. Eighteen of nineteen tracked files are unchanged; the saved-variable
comparison identifies only `probe_tool: 3 -> 0`, not a calibration-data change.

After managed abandonment and restart, stock still offered its interrupted-print
prompt for the invalidated job. It was dismissed before starting a new job; this
stale-prompt behavior remains a UI integration defect to fix. The original recovery
bytes remain verified in the archive. The user cleared the bed again. A fresh
native PRINT of the same coupon, mapped to Head 4, started; controlled interruption
and continuation qualification are pending. This is a new genuine execution, not
rewritten recovery records.

### r149 native failed-attempt resolution accepted — 12 November

The genuine purge-position failure provided the retained unknown attempt. Native
DISCARD opened a confirmation explanation without changing the attempt. CONFIRM
then reported `abandoned`; the backend resolution completed with all heater
targets zero, standby and no motion. The retired job references archive
`00aad83c10ea01c96882fc420b2bcdee83b9e66629f03ccaee3981e1bc0ffc29`.
Readback verifies its digest and exact original job/execution bytes against the
pre-discard capture. Filament records were not discarded. Evidence:
`navigation-r149-discard-{review,confirm}.jpg/json` and
`r149-discard-archive-verification.json` in the dated validation directory.
This accepts the native failed-preparation abandonment flow, not reconciliation
of an interrupted continuation. r150 is installing the tested coordinate fix;
a new physical test requires a cleared bed and a fresh genuine interrupted job.

### r149 handoff accepted; native coordinate completion defect — 12 November

Commit `1a18b26` is installed from `qualification-export-r149`. Screen SHA256
`61bcf6e6c0c0a710431d91da4ec29c00895e754d703764facdc6b4bdd4bba4ea`;
recovery library SHA256 `4585da7466798566ae38de788b00d5a39022af979032bae98f8b75a466a4c0b4`.
The installation journal is applied and running-module readback matches. All 19
tracked files, effective settings, PID tuning, identities, loaded flags and saved
variables are preserved.

Native Continue now opens the visible managed numbered progress panel and creates
attempt `screen_286575341587619`. Camera/status confirm bed clearance, X/Y homing,
head/frame/mesh restoration and progression into heating (Head 4 target 220 C,
bed 60 C). The panel shows completed stages gray and heating orange with live
temperatures. The attempt then stopped at `purge_position` with “Recovery
completion was not confirmed.” All heater targets were set to zero; camera/status
showed the head at the purge side, bed at bottom, and no continuation started.
The durable unknown attempt is retained for managed resolution, not erased/retried.

The native `toolhead.get_status()` returns a `Coord` namedtuple. Purge, wipe and
return stage checks compared that directly with saved lists, incorrectly rejecting
identical coordinates. A local regression using native coordinate representation
reproduced the exact purge-position failure. Local correction normalizes the
reported sequence to a list for those three exact comparisons. Recovery tests pass (399), and five targeted cases cover native coordinates
through preparation and actual request/continuation with array or tuple calibration.
The correction is not deployed yet. R22 remains open; the native handoff itself is now
physically observed working.

### r148 physical interruption and native handoff findings — 12 November

After the user cleared the bed, the authorized coupon reached body printing and
published a completed execution record. Controlled client/Klipper interruption
preserved job `wm-3580354837-3022823481-1`, execution position 18154, physical Head 4,
the committed mapping `[3,1,2,3]`, and deposition envelope maximum Z 1.0. Native
checkpoint/sidecar records remain bound to the same job. Evidence is in
`analysis/validation/2026-11-12-managed-audit/coupon-evidence-r148-interrupted/`.

The native interrupted-print prompt appeared after reconnect. Continue was tapped
once; the prompt disappeared, but no managed attempt or heating/motion followed.
Fresh status and camera confirmed standby with all heater targets zero. The hook
log confirms a verified checkpoint was loaded. Static inspection found that the
selected filename global exists only in `.symtab`, so the hook's `dlsym` lookup
cannot resolve it. All three supported ELF profiles locate it at `0xe644ff8`.
The native popup also hides the shared overlay, while the managed progress panel
did not reveal that parent. Local fixes bind the filename through the verified
profile and reveal the overlay after constructing the opaque managed panel.
Targeted recovery binding, stock provenance and native lifecycle checks passed
(18 passed, 3 skipped). These fixes are not yet deployed or physically accepted.
R22 remains open.

A reconnection FIRMWARE_RESTART is present in command history. Our guarded reset
request was not sent because its precondition found the printer had already
transitioned. Caller attribution remains to be established; no duplicate reset
was issued.

### r148 tuple calibration correction installed — 12 November

Backend SHA256 `789c2c7466b609fefec46d1b8c998157cf638b12fa0e3e2b1c66622ed9e435d2`
is installed; the unchanged screen and recovery libraries were read back and
verified in the running client. The installation journal is applied. All 19
tracked configuration/filament files are unchanged across installation. All four
PID configurations, filament loaded flags/identities, nozzle settings and mappings
are preserved. The loaded `wmp_print` settings now reflect the last coupon's saved
mesh; the file itself was not changed by deployment. Ready/standby, zero targets.

An initial preflight lacked local `jinja2` and exited before installing any
components; the corrected invocation supplied it and activated r148 once. These
are deployment checks, not physical recovery acceptance. The subsequent bed-clear reply and physical test are recorded above. R22 remains open.

Follow-up local integration coverage runs the actual native-request consumer,
preparation/restore chain and queued continuation with both JSON-array and native
tuple calibration. Both cases reach the exact next SD line (`G1 X2`) and preserve
the original job bytes (2 tests passed). Hardware responses are simulated; no
additional restart or printer motion was used for this check. A fresh camera
frame (`wait-r148-bed-check-camera.jpg`) still shows the coupon and purge line.

### r147 coupon outcome and tuple calibration correction — 12 November

The authorized coupon completed with all heater targets zero; the final camera
frame shows the coupon and purge line. No service interruption or recovery was
attempted because no execution record was published. The new diagnostic reported
`Checkpoint job context, mapping or tool state changed` during the print body.
Evidence: `wait-r147-current-*`, `wait-r147-terminal-*` and
`coupon-evidence-r147-body/` in the dated audit directory. The later
`r147-body-context.json` query was taken around completion and reflects cleanup;
it cannot establish the in-print mapping values.

Readback of saved_variables.cfg confirms all four native offsets are Python
tuples. The committed JSON stores the same coordinates as lists. Local tests
reproduced the exact capture refusal and post-restart evidence refusal before
the fix. The correction normalizes only the offset representation for comparison
at capture, publication, recovery admission and preparation, without rewriting
evidence or relaxing changed-coordinate checks. The recovery/execution suite
passed 500 tests, and 17 focused tuple, malformed-value, drift and preparation
tests passed. The correction is now installed in r148; physical acceptance remains open.
The bed needs clearing before another physical print; no replay has been started.

### r147 execution capture deployment — 12 November

Successful outer-SD boundary capture and natural tail-move timing callbacks are
installed. The full material backend/retained scheduling suite passed 1,182 tests.
All 19 tracked configuration/filament files were unchanged by deployment; all
four PID configurations, loaded flags, identities, nozzle settings and mappings
were preserved. The loaded settings now include the `wmp_print` mesh saved by
the preceding physical test. Screen and backend readback match the tested bundle.
Printer is Ready/standby with zero heater targets. Physical execution-record and
interruption/continuation acceptance remain open. The user confirmed the bed is
clear. This is WM+ managed recovery integration, not a general upstream recovery
repair; no upstream Klipper files were changed by this fix.

### r146 coupon completion and execution-record gap — 12 November

The authorized retry passed the previously failing mesh-save step, committed
its managed H4 job, printed the five-layer coupon and reached `complete` with
all heater targets zero. Camera/status monitoring continued through preparation,
deposition commands and completion. Native A/B checkpoints reached layer Z0.8
and byte positions 12338/12511; the job-bound deposition envelope reached Z1.0.
Evidence: `wait-r146-*` and `coupon-evidence-r146-*` in the dated audit directory.

The execution-state JSON was missing during deposition and after completion.
Consequently the planned deliberate interruption was NOT performed, and no
recovery continuation was attempted. The short job was allowed to finish; no
additional print was replayed. The coupon/purge line need removal before the
next physical print. R22 remains open with execution publication as its next
concrete blocker; startup mesh-save behavior is now physically verified.

Source review identifies a possible sampling gap: the one-second timer skips
while the command mutex is held, and capture additionally requires empty
lookahead. Local diagnostics now distinguish `command_busy`, `refused`, pending
motion and publication without changing motion or forcing a queue flush. A
focused reproduction verifies that repeated busy/unscheduled samples publish
nothing, then publish only after a valid boundary matures (8 tests passed).
This establishes the possible failure mode, not the exact live refusal reason.
Diagnostics are local/undeployed; r146 remains the installed candidate.
A retained SD worker/run_script reproduction now proves a legal starvation
schedule across 1600 commands: command yields hold the mutex and later file-read
yields retain lookahead (1 test passed). The required natural timing-callback
correction is specified in docs/print-mesh-recovery.md. It is now implemented
locally with successful outer-SD dispatch binding and natural tail-move timing
callbacks; focused retained-dispatch/scheduling tests pass. Device qualification
remains outstanding. The complete material backend plus retained SD scheduling
suite passed 1,182 tests in 139.90 seconds.

### Recovery coupon startup finding — 12 November

The user authorized the prepared camera-monitored coupon/interruption test.
The actual managed H4 start reached homing and the 4×4 `wmp_print` bed mesh,
then failed at file position 642 before deposition (filament used 0). All heater
targets returned to zero. No deliberate interruption or recovery continuation
was performed; R22 remains open.

Root cause: the configuration-save wrapper used restart admission for
`SAVE_CONFIG_NO_RESTART`, including the managed startup mesh snapshot. Local
correction permits that retained non-restarting writer only for the current
begun, staged, active SD submission with unchanged file/job identity, selected
`wmp_print` mesh and exclusively that mesh in pending settings. Unrelated saves,
remote calls, paused states and normal restart commands retain their guards.
The retained-writer/restart suite passed 91 tests; the startup/recovery macro
suite passed 101 tests.

Attempted cleanup also exposed that Cancel refused an error-state SD job while
its file handle remained open. The local fix permits error alongside printing
and paused through the existing exact-file/session-bound cancellation review
and cleanup. Focused review/confirmation coverage passed all three states;
49 other cancellation checks passed in the initial focused run. Neither fix is
evidence of physical recovery acceptance. Logs, camera, UI and original records
are preserved in `analysis/validation/2026-11-12-managed-audit/`.

r146 is now installed with these backend fixes (screen bytes unchanged).
The preload-only attempt refused the backend mismatch before activation and
rolled back its recorded publications; installing material + preload succeeded.
All four PID configurations, filament identities, nozzle settings, mappings and
loaded flags were preserved. Of 19 tracked files, only saved_variables.cfg changed:
`probe_tool` reset from 3 to 0 on startup. Loaded configuration sections were
unchanged. Printer is Ready/standby with zero heater targets. This activation
closes neither the physical mesh-save retest nor R22 recovery acceptance.

### Proposed R21 direct-unload contract — not implemented, 12 November

Follow-up against the current openACE working tree (base `e796845`, with
uncommitted owner work) also checked the native macro interception path, not
just registered command names. `_make_filament_macro` routes a manual idle
Unload through `dispatch_vendor_filament_service`; a paused manual intervention
instead runs through the material-change coordinator. Neither is the missing
public direct-unload contract: the printer adapter explicitly says that returning
from a vendor macro supplies no filament identity or completed extrusion proof,
and its terminal event reports only stopped motion. Calling this path from WM+
would not establish the durable unloaded/removal-ready result required here.

The WM+ execution branch was rechecked as well: every `direct` plan currently
selects the Load stages, operation name and `OPENACE_LOAD_DIRECT` commands.
An Unload adapter must therefore change planning **and** action-specific
execution/STOP handling together. Removing the planning refusal alone is not
an implementation. Keep the owner working tree untouched while that work is
in progress; qualify a supported owner command before enabling this UI path.

Source trace: openACE `cmd_UNLOAD` delegates `_unload_head_command` to
`routing.unload(head, to_unit)`. Its automatic recipe depends on a unit/slot,
unit capabilities and path-clear evidence. `OPENACE_LOAD_DIRECT` is separately
implemented with explicit physical head and manual-context ownership. WM+'s
existing `direct` execution branch also assumes Load, so merely removing the
Unload refusal would incorrectly execute OPENACE_LOAD_DIRECT.

Required owner contract before changing that refusal:

- Advertise a versioned direct-unload capability. A proposed command name is
  OPENACE_UNLOAD_DIRECT, not an assertion that the command exists today. It
  addresses a physical HEAD and accepts an immutable operation/context identity;
  it never interprets a virtual T number as the physical head.
- Admit only a verified direct loaded destination, idle or a bound paused-job
  service context, with no competing operation. Revalidate context at yielding
  boundaries. The owner handles mount/park/heat, tip shaping and retract using
  its printer adapter. Do not synthesize ACE slot-clear evidence.
- Publish a request-bound operation receipt with numbered stage data, heater
  current/target, pending/running/terminal state and an explicit removal-ready
  result. A tripped inlet sensor alone must not restore the loaded flag after
  completed retract. Removal observation and filament metadata remain owned by
  openACE, with state persisted through restart.
- STOP applies to that operation identity, stops only owned work, performs its
  heater cleanup and records stopped/uncertain outcomes without automatic replay.
  A delayed response cannot turn a completed stop into running work.
- WM+ adds an action-specific direct-Unload execution branch, capability-gated
  planning, exact context binding, shared numbered progress and owner STOP.
  Direct Load remains unchanged. Unsupported owner versions retain the current
  pre-dispatch refusal; WM+ never repairs the owner's loaded record itself.

Acceptance must include public WM+ Load→Unload in both plugin initialization
orders, wrong head/source and changed-owner refusal before motion, STOP during
heat/retract/removal, missing/lost replies without replay, and restart persistence.
Run the actual owner workflow against simulated hardware ports first, then the
native physical cycle. These requirements define the missing feature; they do
not close R21 or authorize installation of an unimplemented owner operation.

### R21 external Unload evidence correction — 12 November

The current-table statement that the external Unload adapter was implemented
was incorrect. Reinspection found `_openace_unload_plan` explicitly refuses a
direct destination, and the repository history contains the refusal fix
`f8616e1`, not a later direct-unload implementation. The existing public-cycle
interop evidence below already identifies this as an unresolved feature gap.
The current table is corrected; refusal is not completion.

The available openACE checkout is `e79684508d4df5cba9ce72ff905d8f8b40ff85d4`.
Its public registration exposes OPENACE_UNLOAD, with no separate direct-unload
command discovered in the source. WM+ must not call standalone extrusion or
rewrite the owner's loaded record to bypass that contract. The needed operation
and acceptance criteria remain the R21 contract below: owner-managed preparation,
heating, tip shaping, retract/removal, durable loaded-state updates and STOP,
followed by the WM+ public Load/Unload cycle in both initialization orders.

Standalone external Unload is a separate implemented path and is unaffected.
No owner was enabled, no production source was changed and no physical command
was sent. Live owner qualification alone cannot close this implementation gap.

### Warning/restart ownership boundary audit — 12 November

Rechecked the current native sender and backend against retained-binary and
vendor-dispatch tests. The warning callback's command sender ultimately sends
FIRMWARE_RESTART (0x54c8d8 → 0x616428 → 0x614338). This is distinct from the
startup shell `systemctl restart klipper` call, which is suppressed by its exact
caller/command hook. `unified_command_sender` does not itself grant restart;
the Ready vendor dispatcher emits the admission event before drain/exit.

`WMMaterial._restart_requested` checks current print/file/pause state, unresolved
cancellation/recovery, running or unknown filament/tool operations, pending
recovery submission/import and calibration ownership. The existing
`klipper_extras/test_managed_restart.py` executes the retained vendor dispatcher
against this handler, including a state change after an earlier admission check.
`tests/test_stock_restart_boundaries.py` pins and emulates the stock warning's
predicate/branch. These sources were inspected; accepted tests were not rerun.

Limits remain explicit: a not-Ready explicit restart retains the vendor recovery
route and durable hold; openACE/AFC retain their owner's restart policy; external
system-service restarts bypass this event. Thus Ready managed admission is not a
claim that every restart is prevented. R26 still requires the relevant deployed
interruption/warning-path qualification and external-owner/writer work. The next
live check must use genuine interrupted state, not an idle restart repeated as a
proxy. No source change, command, motion or restart resulted from this audit.

### Factory ingress managed-hold integration — host coverage, 12 November

The native harness now connects actual Runtime maintenance admission to factory
machine actions 8/9/10/13/14, knife actions 6/7/9 and the separately hooked
password-success sender at 0x4c4160. A managed-operation hold refuses every
machine entry; releasing it restores admission. Factory probe action 12 still
opens read-only managed review and does not dispatch legacy preparation. The
password refusal reports one notice, rather than delegating its trigger.

The native lifecycle harness passes (31.13 s). The first compile failed because
the added fake event fields were reversed; correcting that test fixture required
no production change. Existing stale/hidden/detached event and stale Runtime
status coverage remains in the same harness. This adds integrated host evidence
for R24/R26 ownership boundaries; it does not qualify live factory mutations or
other owners. No printer command, rebuild or restart occurred; r145 is installed.

### r145 cancellation-view correction installed — 12 November

Fresh pre-install evidence showed Ready/standby, no active procedure, unpaused
and zero heater targets. One installation completed; independent readback
verified the exact r145 hash, screen PID 1289959, current mapped modules, native
bootstrap and matching backend source. All 19 tracked files, effective settings,
four heater PID configurations, saved variables, filament identities, nozzles,
mapping and all four loaded flags were preserved. The printer is Ready/standby,
unpaused and all heater targets remain zero.

Evidence: `analysis/validation/2026-11-12-managed-audit/r145-install.log`,
`r145-native-readback.json`, `r145-preservation.json` and before/after file hashes.
This installs the tested restored cancellation correction from `2e0f7a2`; it
is not live interruption qualification. No print, motion or record fabrication
was used. Physical recovery approval remains pending.

The plan's stale references to separate Heat and manual Extrude/Retract review
were also corrected to the user's established target-entry and immediate-step
behavior. These are documentation corrections, not new scope or UI changes.

### Accepted calibration action admission — host coverage, 12 November

Extended the native ProbeEditorFlow harness with SAVE and DISCARD after ACCEPT,
each against stale freshness, changed owner, restarted calibration session,
missing token and older sequence. Both actions refuse without consuming the
next sequence; transient freshness/ownership loss permits a legitimate later
action, while session replacement remains invalidated. Double taps dispatch
once. Lost delivery waits for its exact result rather than accepting the older
ACCEPT receipt, and late delivery failure cannot downgrade completion.

The focused flow test passes (2.82 s). No production source changed and no
printer operation ran. Backend DISCARD preservation is already covered by
`test_editor_discards_accepted_offset_without_restart_or_unrelated_loss` and
`test_editor_conflicting_discard_retains_both_evidence_and_changed_offset`;
these existing cases were inspected, not redundantly rerun. This adds host
admission evidence to R24; native device ACCEPT/DISCARD and save/restart
qualification remain open. r144 remains installed and r145 is staged.

### Restored cancellation terminal-view regression — local, 12 November

The native lifecycle harness reproduced an older unknown cancellation record
replacing completed cleanup in the restored panel. The resolution worker had
retained its receipt, but the runtime independently rebuilt display data from
the older record. The runtime now retains completed cleanup for the exact
cancellation identity and backend session. A different session re-evaluates the
record after discovery; it does not inherit the prior session's completion.

The regression failed before the fix (31.10 s) and passes afterward (31.69 s).
Coverage includes in-place completion, late unknown status, preserved widgets,
no extra cleanup command or review, and new-session re-evaluation. This is local
native-harness evidence; r144 remains installed. The correction awaits the next
candidate build/deployment and does not close live interruption qualification.
No printer restart, motion or fabricated production state was used.

The ARM build and delivery staging verification subsequently passed. Candidate
r145 is staged at
`analysis/validation/2026-11-12-managed-audit/qualification-export-r145`, SHA256
`55cf23565ed12975b08aca80c51088663bc2d2c32d7978fcff5efa2d2ad42cbd`.
Scope remains development qualification (`packaging-control-only`), not public
release. r145 is not installed; r144 remains active on the printer.

### r144 recovery-state fixes installed — 12 November

Installed the combined terminal-result and restored-view fixes after fresh
Ready/standby, no active procedure, unpaused and zero-heater checks. Installation
completed once; independent readback confirmed screen PID 1286337, the exact
r144 screen hash above, current mapped libraries, native bootstrap 11, matching
backend source and an applied installation journal with no unfinished step.

All 19 tracked configuration/state files are byte-identical. Effective settings,
all four heater PID configurations, saved variables, filament identities, nozzle
metadata, head mapping and every head's loaded state were preserved. The printer
returned Ready/standby, unpaused, with every heater target zero.

Evidence: `analysis/validation/2026-11-12-managed-audit/r144-install.log`,
`r144-native-readback.json`, `r144-preservation.json` and the before/after file
hash records. This is installation/preservation evidence for the already-tested
regressions; it does not close physical recovery, interruption or owner gates.
No print, extrusion, homing or fabricated recovery record was used. The physical
recovery coupon remains awaiting its specific approval.

### r143 probe STOP and current-state reconciliation — 12 November

The real-loopback regression reproduced the omitted probe STOP route before the
fix and passed afterward. Native START followed by one STOP produced request
`f1eb93a0d85f6ef7690040eae6f92595`, acknowledged stop intent and terminal aborted.
Camera was monitored throughout. STOP waits for the current homing checkpoint;
it does not immediately interrupt motion. No adjustment/ACCEPT/SAVE was sent.
Readback confirms no active manual probe, no pending save, unchanged effective
settings and identical printer.cfg. All heater targets remained zero.

Evidence: `analysis/validation/2026-11-12-managed-audit/navigation-r143-probe-*`,
`r143-probe-preservation.json`, `r143-preservation.json`, `r143-native-readback.json`.
The r143 factory-reset refusal reconfirmation changed none of 19 tracked files,
but repeated r124's already accepted test. It closes no additional gate and is
not grounds for further reset testing. The current table now prevents the stale
open entries for active-target cancellation, remote-start notifications, external
Unload implementation and successful Take/Dock from being queued again.

### Interrupted cancellation disconnect/reopen coverage — 12 November

The native Runtime/LVGL harness now exercises a restored unknown cancellation
through REVIEW → CONFIRM visible → printer shutdown → queued stale click →
Ready → CLOSE → periodic status → explicit reopen → double CONFIRM → matching
completion receipt. Assertions verify zero commands while stale, preserved
widget identity through disconnect/reconnect, no automatic reopen, no repeated
review, exactly one cleanup dispatch and in-place terminal completion.

`tests/test_unified_ui.py::test_native_lvgl_lifetimes_and_scroll` passes in
31.61 seconds with these additions. This is isolated native lifecycle evidence,
not a claim of live interrupted-printer recovery acceptance. Production records
were not changed, and no build/deployment/restart/motion was needed. Live R27
interruption and owner-specific acceptance remain open.

### Prepared physical recovery test — approved; outcomes above, 12 November

Local artifact: `analysis/validation/2026-11-12-managed-audit/WMP_RECOVERY_COUPON_20261112.gcode`.
Source: the already used Orca single-coupon slice. Part: 12 × 12 × 1 mm at
X144–156/Y129–141, five layers, 45 seconds and 0.18 g slicer estimates excluding
startup purge. Nozzle/bed: 220/60 C. Map slice T0 to physical H4 (`h3`). Fresh
readback reports H4 Kexcelled PLA Matte, loaded flag, inlet presence and 0.4 mm
hardened nozzle. Camera shows a clear bed; recheck before an approved start.
Only executable-file change: M400 and TURN_OFF_HEATERS before EOF, ensuring
heater shutdown independent of the screen completion worker. SHA256:
`a21e3f9578cb0b958088f7a77a4b12d5619cc2a1f6397daeb7981560a23dfdc3`.
Adjacent `recovery-coupon-plan.json` records source, bounds and layer byte offsets.

Approved sequence (see current outcomes above):

1. Use managed preview/start with T0→H4 and current preflight; retain pre-test
   configuration, filament and recovery evidence. Monitor camera throughout.
2. Observe real deposition and verify the native checkpoint, binding sidecar,
   execution and deposition-envelope records belong to this file. Interrupt only
   with that evidence and visible deposited layers. If the window is missed,
   allow completion; no automatic replay.
3. Deliberately stop touchscreen and Klipper services, then restore them, without
   editing recovery records. Confirm heaters off and camera available. This tests
   process interruption, not electrical power loss.
4. Inspect native recovery review. Continue only if material, calibration, file
   and clearance checks pass; camera-monitor the entire motion sequence. A
   refusal is a finding, never a reason to bypass admission.
5. Verify completion or an explicit stopped result, heater cleanup and preserved
   configuration. Never erase unresolved saved state to make the test pass.

The user subsequently approved this coupon and controlled interruption test.
The initial startup failure and r146 completion are recorded above; interruption
has not yet been performed. This covers R22 native entry and physical
continuation, not every corrupt-record or other-owner case.

### Recovery resolution terminal-result regression — local fix, 12 November

The isolated worker regression reproduced a late matching `pending` snapshot
replacing an already recorded `complete` recovery-resolution result. The native
worker now retains its first recorded terminal result for that request, matching
the existing cancellation-resolution policy. New explicit reviews and changed
backend sessions still reset the binding; an unrecorded lost acknowledgement can
still be resolved by its matching receipt. No command is replayed.

The new regression failed before the fix. Recovery and cancellation resolution
checks pass together (2 tests, 8.03 s), covering late pending/unknown/refused
snapshots, message preservation, acknowledgement loss, exact binding and separate
review/confirmation. ARM build passes with SHA256
`35f1a3461f33c330ddbdc7024646030e2740363e9f0ed0215bde99d9a616e03f`.
This is not deployed: r143 remains installed, and the fix is held for the next
batch. No printer restart or motion occurred. Recovery-coupon approval remains
pending; no print or fabricated recovery record was used for this regression.

### Recovery progress terminal-result regression — local fix, 12 November

The same late-status audit found the main recovery worker could replace a
completed continuation with an older running/preparing receipt and re-enable
STOP. A new regression reproduced the downgrade. Whole-attempt terminal results
(complete, cancelled, abandoned or reconciled) now retain their bound receipt.
Paused, stopped and unknown remain nonterminal for legitimate resume/resolution;
the existing new-session reconciliation path remains available.

Focused recovery progress and resolution checks pass (2 tests, 9.02 s), including
paused→printing, unknown→complete, late pending/running/unknown/stopped snapshots,
STOP remaining unavailable after completion and unchanged command count. No
printer state changed. This joins the prior resolution fix in the pending batch;
r143 remains installed. The combined candidate still needs its batch ARM build
and deployment; the preceding ARM hash covers only the earlier resolution fix.

### Restored recovery runtime regression and r144 batch — local, 12 November

The full Runtime/LVGL regression reproduced a late stopped snapshot restoring
DISCARD after an abandoned result. The restored-view path was bypassing the
worker's retained outcome. It now retains whole-attempt terminal display/receipt
for the same attempt and backend session. A new session still invalidates object
discovery and requires a fresh sync before the new review is available.

Recovery display-state projection is shared between the worker and restored
view. Preparation `complete` with scheduled/started/paused continuation now shows
pending/printing/paused, not a completed print. The harness exercises those
transitions, pause→printing, uncertain continuation, abandonment, late old status,
unchanged widgets/no command dispatch, and new-session rediscovery.

The original terminal-view regression failed before the fix. Focused worker and
resolution checks passed; native lifecycle passed after correcting its expectation
to include the existing required rediscovery cycle (31.47 s). The combined ARM
candidate passes and is staged as r144, SHA256
`c2928e257eb558db2660ad014681a975c46f3aea7c6317e9aae77cc9648a5934`, under
`analysis/validation/2026-11-12-managed-audit/qualification-export-r144`.
This includes 45e735d and 1b2d57a plus the runtime correction. Packaging scope is
qualification only, not a public release. r144 is not installed; r143 remains on
the printer. No restart, motion, print or production recovery-record edit occurred.
Recovery-coupon approval is still pending.

## Dated implementation and validation history

### Independent Factory confirmation sender — local correction, 12 November

Exact-client inspection found one direct caller of factory_mode_pass: password
success in the text keyboard at 0x54e3b0. The helper clears need_pass and sends
_LEVELING_TRIGGER through command_sender at 0x4c415c (return PC 0x4c4160), outside
the Factory event gates. Its prologue contains ADRP, so it must not use the
simple copied-prologue trampoline.

The existing sender hook now checks maintenance admission only for that return
PC. Refusal queues a read-only notice for gui_step; it sends no trigger and does
not manipulate widgets on the sender path. Password/access state remains stock.
Other sender callers are unchanged. Offline ARM execution proves the helper's
state/command behavior, and the compiled native lifecycle test proves caller
isolation, permitted/refused delegation, no-command notice delivery and CLOSE.
Both checks pass (31.00 s). Combined ARM build passed with SHA-256
148572936a43f5c374ac3523d087f6cbab6fec0331a3224250cc9a6452a0221e.
This remains local; no printer state was changed.

### Factory/knife admission gaps — local correction, 12 November

Review of the current r141 sources found that Factory probe action 12 was
intercepted, but actions 8/9/10/13/14 still delegated without managed admission.
The knife-position callback likewise had no active hook; earlier archived
candidate notes did not establish protection in the current build.

Factory trigger-mode, knife-preparation, tool-position and wipe-position actions
now require the existing fresh/idle/known-owner maintenance admission before any
vendor mutation or command. Probe review remains read-only and available.
A hash-bound knife callback hook at 0x4c6490 now applies the same admission to
Z jog (6/7) and motor-disable/probe-position save (9). Distance selection (0–5)
and Close (8) remain available. Both routes reject disabled/hidden/stale targets;
refused machine actions use the existing busy notice without calling stock code.

The Factory no-admission regression failed before the change. Fourteen focused
checks pass (31.98 s): native lifecycle/admission, exact firmware profile,
Factory/knife relocatable prologues and original ARM action dispatch identities.
These are local boundary tests, not physical calibration or device acceptance.
ARM compilation passed (candidate SHA-256
0ee12c9783d03fdda74ef377dc7b8ef0426e1aaae2b403ce72d85c44572e06f6).
The printer remains on r141. Independent factory_mode_pass and other confirmation
callers remain in the audit; this change does not claim full factory coverage.

### r141 activation and remote-start cancellation acceptance — 12 November

Installed combined native candidate
88c3d926c922e78de1d303e53a5d805617829ecdfaeb6cee17d99ee3c618b9a9.
Journal 35a4adc7d7ee41229d87a76c9f1f4eb8 completed applied; independent readback
confirms the current mapped module and Running bootstrap (screen PID 1265167).
All 19 tracked files, effective configuration, PID gains, mappings, identities,
nozzles and loaded-filament flags were preserved. Backend bytes are unchanged.

One authorized existing 180-byte log/wait-only fixture was started remotely and
cancelled. Receipt legacy_cancel_809f56c39da446028f0c2bbc78bee017 completed all six
stages; final job cancelled, unpaused, all targets zero and unchanged position.
Camera frames were viewed before, during and after; no motion or extrusion.
The initial short observation window expired before cleanup completed; subsequent
readback verified the same request, without another cancellation or restart.

The five log entries cover file start, selection, BEGIN and timelapse STOP:
no stock identity-backup SAVE_VARIABLE commands and no cancellation-generation
errors appeared. The actual Home screen has no stale error banner. This closes
the observed remote-start backup-write notification defect. It does not close
interrupted cancellation, owner-specific recovery or stopped-popup Re-print:
the remote cancellation returned to Home without a stopped popup.

Evidence: analysis/validation/2026-11-12-managed-audit/r141-{preservation,native-readback,cancel-status,cancel-gcode}.json,
wait-r141-{before,running,after}-camera.jpg and navigation-r141-after-cancel.jpg.
The cancelled-review response fix is also installed; native recovery-entry
acceptance still requires legitimate saved recovery context.

### Remote-start mapping-backup queue — local fix, 12 November

The exact stock parse_print_stats loop sends identity backup writes through
0x63dc1c (return PC 0x63dc20). In standalone mode these can queue behind the SD
job and later fail the cancellation generation guard, producing stale-command
notifications. The native sender now suppresses only the four exact identity
backup commands from that caller, and only with fresh standalone ownership.
Managed Start still establishes its mappings; PAUSE still snapshots the live
mapping before RESUME. Nonidentity writes, other callers/commands, stale status
and other owners retain their original path. Backend cancellation fences are
unchanged; no errors are swallowed.

The exact-client BL binding and compiled command-boundary regression pass.
Runtime compilation, status projection and retained duplicate-mapping heater/
PAUSE checks passed (6 cases, 14.50 s). Live remote-start/cancel acceptance of this
change remains open. This is a new affected path, not a reason to repeat physical
load/unload or unrelated stock tests.

### Cancelled recovery review response — local fix, 12 November

A new delayed-HTTP regression reproduced a cancelled review returning as a
refused result after CLOSE. The retirement worker now invalidates that request's
presentation revision when the user cancels, ignoring its late success/error.
A fresh explicit review still works; no confirmation or machine command occurs.
The focused native-worker test failed before the fix and passed afterward
(4.06 s), including existing lost-acknowledgement/readback and restart cases.
ARM compilation passed; candidate SHA-256 is
121839564c78c16fa0d4ac77e106471f63efdeffffe0413530931b2bd5d8bd72.
This change is local, not yet installed. Native recovery-entry acceptance remains
open and requires legitimate saved recovery context; no records were fabricated.

### Direct tool-action fault reset bypass deployed in r140 — 12 November

Extending the existing nonzero-fault regression to `_CHANGE_TOOL` and
`PARK_CURRENT_TOOL` reproduced a bypass: both direct entries cleared fail_flag
before downstream guards. Added standalone nonzero-fault refusal before any
reset or tool-return preparation. Existing all-owner trapped-dock -3 refusal
remains first. 221 focused guard cases pass (77.77 s); six additional stock,
openACE and AFC direct-entry cases preserve their existing behavior (2.47 s).
No fault was injected on the printer. Delivered in r140 with an exact backup and
readback of change_macros.cfg. Both loaded macro bodies match the reviewed
configuration and refuse retained standalone faults before resetting fail_flag.
Independent native/module verification passed. Of 19 tracked printer files,
only change_macros.cfg changed, with the expected SHA-256
7a2b14dea2b93880ae7005ce01a928a929d8296f09f7e85b8a6cc486c3e2760f.
PID settings, filament metadata/loaded flags and other configuration were
preserved; the printer returned Ready, unpaused, with all heater targets zero.
Successful Take/Dock observations below remain applicable to unchanged
fault-free behavior; mechanical failure acceptance remains open.
Evidence: analysis/validation/2026-11-12-managed-audit/r140-loaded-guards.json,
r140-preservation.json and r140-{before,after}-file-hashes.json.

### Head 4 managed Take accepted — 12 November

One request `validation_h4_take_20261112` started with empty carriage, XY homed,
Z reference unknown, no faults and zero heater targets. The ordinary tool-change
macro established bottom Z via `_WMP_HOME_Z_BOTTOM` before pickup; camera frames
show downward bed travel. This is not the XY-only filament-service path. The
operation completed with sensor-confirmed Head 4 attached and carriage at
X=-13.71875, Y=275.720313, Z=299.775938; E remained zero and targets stayed zero.
Camera frames were viewed before and during the request. No second request or
failure retry was sent. Successful Take/Dock paths now have device evidence;
this does not prove mechanical failure handling or other-owner qualification.
Evidence: `h4-take-dispatch.json`, `wait-h4-take-*` in the November 12 audit.

### Head 4 managed dock accepted — 12 November

One request `validation_h4_dock_20261112` started with Head 4 attached and XY/Z
unhomed, zero faults, idle standalone ownership and zero heater targets. Viewed
camera frames show XY homing, dock approach, release and carriage separation.
The operation completed with sensor-confirmed empty carriage; Z/E positions
remained zero and no heating was commanded. This verifies the successful changed
release path, not injected actuator failure or Take. No coupling retry submitted.
Evidence: `h4-dock-dispatch.json`, `wait-h4-dock-*` in the November 12 audit.

### Active heater-target cancellation accepted — 12 November

All four extruders and the bed had verified 40 C targets before the authorized
log/wait job. Remote Cancel produced complete receipt
`legacy_cancel_28681f3eb3c6431aae4847732f7916b8`; all six stages completed and
all five targets became zero without fallback TURN_OFF_HEATERS. Final state is
Ready/cancelled/unpaused, unchanged position; viewed camera frames show no motion
or extrusion. This verifies active-target cleanup, not cooling to ambient,
print-temperature behavior, mid-extrusion interruption or failed-heater cleanup.
Evidence: `heater-cancel-{before,targets,printing,after}.json` and
`wait-r139-heater-final-*` in the November 12 audit directory.

### Next validation boundaries — 12 November

Do not repeat ordinary native/remote cancellation or completed Re-print unless
those paths change. Active heater-target cleanup was subsequently accepted (see the current table);
do not queue it again. This does not establish mid-extrusion or interrupted-cleanup
acceptance. Interrupted REVIEW/CONFIRM needs
a genuine interrupted cancellation result, or an isolated native test harness;
do not edit production records to manufacture one. R22 continuation needs a
real compatible saved checkpoint and separate authorization for any printing.
No such checkpoint is established by the log/wait cancellation fixture.
R25 mechanical qualification must exercise the changed single-attempt coupling
path with camera observation, not repeat unrelated load/purge checks.

### r139 summary visual acceptance — 12 November

Actual pending and completed cancellation screens now show the status summary
above all six numbered stages without overlap. Pending message and completed
“Print cancelled” are readable; active/future/completed colors and light header
captions remain correct. CLOSE was exercised after completion. The authorized
log/wait fixture ended cancelled/unpaused with zero targets and unchanged
position; viewed camera frames show no movement or extrusion. No load/unload
retest was needed. This closes the missing-summary defect for cancellation;
heating-temperature and longer recovery-chain presentation remain separate gates.
Evidence: `navigation-r139-progress.jpg`, `navigation-r139-result.jpg`,
`navigation-r139-close.*`, `wait-r139-visual-final-*` in the November 12 audit.

### r139 summary sizing installed — 12 November

Screen SHA256 `7075ca5de574c6e9187549335cf66d21a31d8c29eae1378c4731f6adb4c22d2a`,
PID 1254680, applied journal `2a0320ea987b4c00a0ac551423909e59`.
ARM build/package passed; all 19 tracked files, effective settings, PID tunes,
filament identities/loaded flags and cancellation record preserved. Printer is
Ready/standby, unpaused with zero targets. Summary visual acceptance remains open.
Evidence: `r139-*` in the November 12 audit directory.

### Progress summary sizing corrected locally — 12 November

The missing summary is specific to `StockRecoveryProgress::label`: it passed
height -1 directly to `lv_obj_set_size`. The filament procedure's label helper
already treats negative height as content-sized and sets width only, so it needs
no change or repeat load/unload test. Recovery progress now uses that same native
content-height behavior; existing layout measures the resulting wrapped summary
before positioning stages. Native runtime compile passed (see focused run).
ARM deployment and visual summary/temperature acceptance remain open.

### r138 foreground visually accepted; missing summary found — 12 November

Live `navigation-r138-progress.jpg` and `navigation-r138-result.jpg` show readable
light title/CLOSE captions and unchanged orange/white/gray stage colors. The
log/wait fixture cancelled successfully; final camera/status show stationary
machine, unpaused/cancelled and zero heater targets. This accepts the foreground
fix only. The status summary is absent in both captures despite renderer code
setting it. `summary_` is created with height -1; investigate native sizing before
claiming complete progress presentation. The filament procedure description uses
the same height and needs a scoped check. No unrelated print/load tests repeated.

### r138 foreground fix installed — 12 November

ARM build and package verification passed. Installed screen SHA256
`e899e5b1bf93e015b42a078af673fb13be7813eb63cf9fcd2bfd4fc9f6117ee0`,
PID 1251860, applied journal `fa8ea94312dd47ef843d0280e9c187a2`.
Independent readback verifies native Running, mapped current libraries and
unchanged backend. All 19 tracked files are unchanged; effective settings,
saved variables, four PID tunes, filament metadata/loaded flags and the completed
remote cancellation receipt survived installation. Home renders normally; the
progress-panel foreground itself still requires visual acceptance.
Evidence: `r138-*` and `navigation-r138-installed.*` in the November 12 audit.

### Shared progress foreground fix — 12 November (local)

The r137 cancellation captures show dark title/CLOSE text against the dark panel.
`StockRecoveryProgress::label` set its font but inherited foreground color from
the stock overlay theme; only stage rows and the action caption received explicit
colors. All labels now default to light text, while existing stage/disabled colors
still override that default. This also covers status text and recovery/discard
panels using the same renderer. Native runtime compile check passed (5.44 s).
Not deployed yet; visual acceptance remains open for the next screen build.

### Interrupted-cancel delayed-review race coverage — 12 November

Added host coverage for a review HTTP reply delayed across a session change,
replacement cancel record, owner change, stale status or protocol loss. Each
case rejects the delayed review and sends zero resolution commands; confirmation
cannot revive it. Focused native worker regression passes (1 test, 3.83 s),
including existing lost-reply and receipt-binding scenarios. This adds evidence
for a previously untested in-flight transition; it does not claim physical
interrupted-cancellation acceptance. No printer record or backend was changed.

### Remote Cancel accepted — 12 November

The separately authorized log/wait fixture was started through Moonraker and
cancelled via POST `/printer/print/cancel` while printing. HTTP returned promptly;
backend receipt `legacy_cancel_eb496cc466e449d0a95469d41aea8888` was observed pending
at stopping, then complete with all six stages complete. Final state is Ready,
cancelled and unpaused, position unchanged and all heater targets zero. Viewed
camera frames before/after show no movement or extrusion. This closes ordinary
remote Cancel delivery, not interrupted cleanup or hot-heater qualification.
Evidence: `wait-r137-remote-cancel-*` in the 12 November audit directory.

### Cancellation notification provenance — 12 November

Read-only follow-up captured `wait-r137-cancel-gcode.json`. The last authorized
job queued four `SAVE_VARIABLE VARIABLE=box_modify_tN_backup` commands immediately
after start. At dwell completion, four generation-refusal errors appeared, then
`HYPERLAPSE ACTION=STOP`. This strongly points to queued stock mapping-backup
writes being fenced after cancellation; it does not show cancellation failure.
The producer is confirmed by the retained binary audit in
`client-preload/unified-ui/README.md`: `parse_print_stats` checks
`is_print_from_screen` at 0x63db78 and otherwise sends identity backup writes in
the loop at 0x63dbb8. The test helper uses Moonraker `/printer/print/start`, so it
does not stage WM+ native `PrintContext`. Managed touchscreen submissions already
stage this flag to skip that loop. This is a remote-start compatibility case;
do not generalize it into a managed touchscreen submission failure. The four
queued writes are correctly fenced, but their stock notification outlives the
successful managed cancellation. Any notification change must retain errors
for unrelated or current commands and preserve confirmed other-owner behavior.
`wm_material._cancel_routes_ready` captures generation before the script mutex,
and `_check_command_generation` raises the displayed error to abort stale work.
Do not remove that error or return success: doing so would execute the remainder
of an invalidated batch. Next work is producer/notification ownership, preserving
the generation fence and surfacing real command failures.

### r137 cancellation progress and CLOSE accepted — 12 November

Installed screen SHA256 `958e548090f51aa942cc4b20a2543223cc76ce31534ffd2f730d9c772d16e239`,
PID 1246616, applied journal `92ef45e2eebe41f0b5f6b34f37022b01`;
backend unchanged. All 19 tracked files and effective settings, four PID tunes,
loaded flags and identities were preserved. Native popup regression: 2 passed
(21.22 s); ARM build passed. The old popup child is hidden without hiding the
shared layer containing managed progress.

The authorized log/wait-only job reached managed cancellation through native
STOP → Confirm. Live captures show six numbered stages, orange active/white future
stages, then gray completed stages. Receipt `cancel_257461262964070_1` has all six
stages complete. CLOSE returned to Home. Final state: Ready, cancelled, unpaused,
all heater targets zero, position unchanged; viewed camera frames show no movement
or extrusion. Cancellation waits for already executing work; this is not an
emergency stop. No recovery checkpoint was fabricated or discarded.

One preceding attempt completed before confirmation and is excluded from
cancellation acceptance. Its completion popup navigated to preview. The subsequent
attempt above supplies cancellation evidence. A stale generation-refusal banner
remains visible on Home after CLOSE and is an open notification-polish issue.
Interrupted cleanup, hot-heater cleanup, supported-owner cases and corrected
stopped-popup fallback device acceptance remain open. No accepted filament
load/unload or unrelated stock behavior was retested.

Evidence: `r137-*`, `wait-r137-*`, `navigation-wait-r137-*` under
`analysis/validation/2026-11-12-managed-audit/`; in particular
`navigation-wait-r137-confirm-retry.jpg`, `navigation-wait-r137-cancel-settled.*`
and `navigation-wait-r137-result-close.jpg`.

### r136 managed cancellation completed; progress-layer follow-up — 12 November

Installed SHA256 `bb70641c6adfc4ae78df3bff6d5b7530b86b78e8b95eacde228c6e4a8445fd72`,
PID 1243994, applied journal `3c8d14710fc54a36b7f5990ad77236b7`; backend unchanged.
The same 19-file/settings/loaded-state/PID preservation checks passed. The r135
export was superseded locally by the combined r136 build and was never installed.
Native popup tests pass (21.31 s), including the actual stopped-popup builder with
an empty browser filename, fresh terminal-job fallback, stale/active/path refusal,
Stop interception, ordinary dismissal and fresh openACE routing.

The authorized log-only job was cancelled through STOP → Confirm. Receipt
`cancel_256834208212827_1` reached complete with all six stages complete:
stopping, draining, cooling, invalidating, cancelling and clearing_pause.
Command generation advanced to 2. The job is cancelled, unpaused, targets zero;
camera and position show no movement or extrusion. This closes ordinary native
cancellation receipt/cleanup acceptance for this fixture, not interrupted cleanup,
hot-heater cleanup or physical emergency-stop tests.

The progress panel was invisible because the popup adapter hid the entire shared
overlay layer. The local follow-up hides only the old popup's containing child,
leaving the layer visible for the managed result. Host coverage now asserts this
parent/child distinction. Native visibility acceptance remains open until installed.
The generation-refusal banner seen afterward is retained as an observation; no
claim is made that all stock queued-command notifications are polished.

Stopped Re-print fallback was host-validated; the r134 real stopped popup exposed
its missing browser filename before this correction. That fallback's native-device
acceptance remains open. The corrected standalone cancellation retires the old
stock stop worker, so it does not manufacture another stock stopped popup.

Evidence: `r136-*`, `wait-r136-*`, `navigation-wait-r136-*` under the audit directory.

### r134 completion handoff accepted; native Stop prefix gap found — 12 November

Installed screen SHA256 `61f8e622c1ce72a7a07823c1a84aba8ba30265c8d4f9fd18ad180f26d85e0ea8`,
PID 1236904, applied journal `522a28b15eef4299a16cec3ba5ce7a05`. All 19 tracked
files, effective settings, loaded flags, identities and PID values were preserved.
The corrected firmware-layout regression passes both popup tests (21.06 s).

The repeated log/wait-only job completed. Actual RE-PRINT opened managed preview;
the fixture has no usable print metadata, so PRINT stayed disabled with a visible
metadata error. CANCEL closed preview without starting a job. This accepts the
completed-popup handoff, not printing a sliced model or the stopped-popup case.
Initial taps after restart were not delivered at the intended coordinates because
the kernel retained identical coordinates; both axes changed by one pixel restored
input. Live memory showed the correct file and armed gate throughout. This was
an injector issue, not a remote-job filename or additional UI defect.

The separate cancellation run used native STOP → Confirm at 21 seconds. It became
cancelled with unchanged position and zero targets, but no managed cancellation
receipt. Recent G-code output shows stock quick-stop handling. Exact ELF inspection
shows popup kind 69 calls `stop_printing_handler` at 0x530f48, whose first call
(0x51bf24 → 0x616558) sends quick-stop, and then `reset_plr_files` at 0x530f4c.
Only later does the worker send CANCEL_PRINT at 0x51bce0. Sender interception alone
is too late. R27 remains open; the local fix intercepts the confirmed popup before
both prefixes and routes through the existing managed cancellation worker.
Stale/non-click/foreign events are consumed; ordinary dismissal and confirmed
openACE ownership preserve their existing route. No artificial recovery record
or fault was introduced. Camera views verified no physical movement or extrusion.

Evidence: `r134-*`, `wait-r134-*`, `navigation-wait-r134-*` in the audit directory.

### R20 live completion found a Re-print handoff defect — 12 November

User authorized the log/wait-only virtual-SD job and camera-monitored motion,
not arbitrary model printing. `WMP_UI_WAIT_20261112.gcode` contains only two M118
messages around G4 P30000 (180 bytes, SHA256
`2b529ee4b825412e6d981f9b30d3055a3575863d31ad92f736fb09a120e06f62`).
The job completed with no motion, heat or extrusion, and the genuine native
completion popup appeared. RE-PRINT dismissed it but failed to open preview;
it did not restart the job. R20 remains open. Cancellation has not yet run.

The exact ELF declares `cur_page_ui` at `0x463c500` as char[80]. The adapter
incorrectly read it as std::string; the earlier host fake repeated that error.
Correcting the fake makes the existing native event test fail at preview handoff.
The adapter now uses bounded character comparison. `page_to` calls the manager
synchronously, including page construction/refresh, before copying the page name;
no asynchronous page-construction assumption or timing workaround was added.
Local fixed tests/build and subsequent device qualification are tracked below.
Evidence: `wait-*` and `navigation-wait-*` in the 12 November audit directory.

### r133 installed; General nozzle entry validated — 12 November

The touchscreen-only batch is installed with journal
`efa2086d215b4f6aabc7cd44b7fb58f0` applied and no in-flight component. Screen PID
`1227305` maps SHA256
`f9d223c600823206818b757173304ea955617a358a65501363ca55f429b3beb4`;
native bootstrap is Running. Backend source remains unchanged at
`e362eddd9f87cd5e7d97c9651fc03af94e0f32f7cc3aff41e24c4135bc628097`.

Live acceptance: General → Nozzle Type opens “Head 4 – Nozzle” for the mounted
head with 0.4 mm/hardened-steel settings. Selecting stainless steel changes only
the draft and enables SAVE. CANCEL closes the editor; Toolheads still shows
hardened steel. All 19 tracked configuration/filament files have unchanged hashes
after installation and this interaction; effective settings, identities, loaded
flags, physical mapping and all four PID tunes are preserved. The printer remains
standby, unpaused, targets zero. No Save, heating, motion, print or checkpoint
discard was issued. This closes this specific General-entry/Cancel acceptance,
not all R23 writer coverage or R22 physical recovery qualification.

The first remote tap on the material field produced no visible list; a subsequent
tap on its arrow opened it. Recorded as an observation, not proof of complete
physical-touch responsiveness. The General menu required a slower remote swipe;
stock scrolling behavior was not modified.

Evidence: `analysis/validation/2026-11-12-managed-audit/r133-*`,
`navigation-r133-general-nozzle.*`, `navigation-r133-nozzle-draft.*`,
`navigation-r133-nozzle-cancel.*`. The batch also installs the discard wording
change; actual saved-recovery entry qualification remains open.

### Recovery discard wording — local follow-up, 12 November

The recovery-discard panel incorrectly retained the title “Recover print”. It now
uses “Discard recovery”, and its confirmation explains that the saved print can
no longer be resumed, diagnostic records are archived, and the physical print
remains. The title updates in place when the existing panel changes mode.

Two focused host checks pass (`native_lvgl_lifetimes_and_scroll` and
`recovery_retirement_review_and_readback`): retained widgets and title transitions,
explicit confirmation, duplicate-tap refusal, stale-context refusal and lost-response
readback. This is a local presentation change awaiting the next deployment batch;
r132 remains installed. No printer restart or real checkpoint discard was performed.
Native recovery-entry and physical recovery qualification remain open.

### Remaining configuration writers — static audit, 12 November

Verified eight direct-call argument pairs against the retained exact firmware and
recorded them with script literals in `stock-config-writer-callers.json`. Startup
nozzle-diameter reads are mode 0 and need no write guard. UUID writes belong to the
already retired identification worker. Separate stock nozzle-editor and firmware
update paths do write diameter; the latter is documented rather than added to
physical UI testing. Startup model selection also comments/uncomments the zru-s
include, without replacing the whole config. The stock editor's remaining entry
and model-selection provenance remain open. Details and limits are in
`docs/upstream-client-callers.md` under “R23 remaining writer call arguments”.
The inspector rejects unsupported firmware. No printer commands or restart were
used; this does not close R23's full writer-coverage gate.

Follow-up: the stock General nozzle editor is reachable via page_to and writes
material/diameter immediately on selection. The local navigation hook now opens
the existing WM+ draft editor for standalone ownership, using the mounted or first
configured head. Unknown/stale status does not delegate to the stock writer;
fresh openACE routing is unchanged. The native lifecycle check passes, including
actual managed editor opening without a command, draft/Save/Cancel behavior and
entry refusal cases. Deployment and the General-entry screen check remain open;
startup model-include provenance is still a separate open item.

The ARM build for this local batch passed: candidate SHA256
`f9d223c600823206818b757173304ea955617a358a65501363ca55f429b3beb4`, log
`/tmp/wmp-nozzle-navigation-arm.log`. This includes the discard wording change;
it has not replaced installed r132. Startup model provenance is now traced to
`tmt1.ini` → `[printer] model` (default 2; recognized 1/2). Normal configured-model
behavior remains unchanged; missing/corrupt/conflicting configuration handling
remains open. No additional physical validation was claimed.

### r132 installed; configuration preservation verified — 12 November

The combined r132 candidate is installed. Journal
`05897c2bf4214e9784627f6c5c5c737b` is applied with no in-flight component.
Screen PID `1220219` has the matching native artifact mapped and bootstrap Running.
Screen SHA256: `5f1fe49af5f26a5264558aff7802f9b05fcf1f4b9dd778713e791c4310d41f49`;
backend SHA256: `e362eddd9f87cd5e7d97c9651fc03af94e0f32f7cc3aff41e24c4135bc628097`.
The recovery module and staged C source also match the installation receipt.

This batch installs the blocked-legacy review bridge, marker permissions fix,
direct configuration-save admission and exact startup discovery suppression.
Preflight passed after adding the local validator's missing jinja2 dependency;
the failed initial preflight made no installation changes. One subsequent
installation completed; no additional printer restart was requested.

The targeted startup-preservation check compared 19 files, including controller
UUIDs, configured head count, printer.cfg, macros, calibration, saved variables,
filament records and plr.ini: all hashes match. Effective settings have no changed
sections. All four PID tunes, loaded flags, identities, nozzles and physical mapping
are preserved. SAVE_CONFIG, SAVE_CONFIG_NO_RESTART, _WMP_COUPLING_STROKE and
WMP_RETIRE_RECOVERY are registered after the new backend session reached Ready.
Printer standby, not paused, all heater targets zero; editor/identification idle.
Evidence: `analysis/validation/2026-11-12-managed-audit/r132-*`.

This closes installation and startup preservation for this batch. It does not
claim that a live active-operation SAVE_CONFIG refusal was exercised, that a
legacy recovery panel was opened, or that mechanical recovery is qualified. No
print, discovery, homing, extrusion, deliberate fault or configuration-save
command was used. Previously accepted unaffected tests remain accepted.

### Startup discovery guard and regression follow-up — local, 12 November

The exact native startup call to canbus_query.py can rewrite controller UUIDs,
head count and printer.cfg from a partial unassigned-node response. The local
unified shell hook now suppresses that exact caller/command before launching the
script. It preserves configured identities and returns empty diagnostic output;
explicit managed identification remains separate. This does not guard arbitrary
external invocations, model-include scripts or firmware updates. Native caller
provenance and remaining script inventory are in the stock caller audit.

Compatibility-profile regeneration exposed an existing generator omission:
lv_obj_has_state was manually present in the committed profile but absent from
the generator. Added it to the generator and a disposable-output reproducibility
test, so regeneration retains disabled-input checks. A failed compile caught
this before any deployment. The final native build passed, and all 22 startup-boundary checks passed,
including execution of the built ARM wrapper for exact discovery suppression,
nonmatching caller forwarding, return values and argument ownership. Logs:
`/tmp/wmp-startup-discovery-final-arm.log` and
`/tmp/wmp-startup-discovery-arm-checks.log`.

The combined candidate is staged and packaging-verified at
`analysis/validation/2026-11-12-managed-audit/qualification-export-r132` with screen
SHA256 `5f1fe49af5f26a5264558aff7802f9b05fcf1f4b9dd778713e791c4310d41f49`.
It includes the r131 recovery bridge/marker changes, direct-save admission and
startup discovery guard. This was packaging-only evidence at preparation time; subsequent installation
and preservation results are recorded above. It is not full release qualification.

The backend regression run after direct-save admission completed with 1,165
passes and one failed test (182.72 seconds). The failure was a prior assertion
from df40546 that conflated abandoning a managed attempt with retiring raw
checkpoints. Corrected it to assert restored abandoned state and absence of a
fabricated retirement receipt. All 34 related abandonment/retirement/restoration
checks then passed. No backend implementation change was needed for that failure;
do not report the initial whole-suite run as entirely green or rerun unrelated
physical tests. Logs: `/tmp/wmp-config-save-backend-regression.log` and
`/tmp/wmp-recovery-receipt-regression.log`.

### Direct configuration-save admission — local, 12 November

The stock SAVE_CONFIG writer writes/renames printer.cfg before its restart event;
SAVE_CONFIG_NO_RESTART never reaches that event. Managed calibration already
admitted its saves early, but direct G-code callers could bypass that protection.
The local candidate now wraps both registered writer commands at Ready startup.
Standalone admission runs before the original writer, refusing active/paused
prints, unresolved operations, unknown status and quick-stop/shutdown. Refusal
preserves pending settings and all files. Admitted saves retain the original
writer, backup and restart behavior; openACE/AFC ownership retains its existing
policy. Missing optional SAVE_CONFIG_NO_RESTART is supported; missing primary
SAVE_CONFIG fails initialization without consuming another existing handler.

217 affected tests pass, including retained vendor writer/dispatcher tests on
disposable files, managed calibration/editor flows and restart admission. Both
full-plugin startup orders also pass against the local openACE development tree;
the minimal fake printer needed its absent native SAVE_CONFIG port supplied, and
that port raises if initialization attempts a save. These are local checks, not
live configuration-save acceptance. No printer file was written or service
restarted. This change was newer than the r131 staged export; it was subsequently included
in the combined r132 installation recorded above.

### r130 installed; live legacy-record review finding — 12 November

The combined r130 installation completed with journal
`932208a74f46485e8615d9fe2236c9e5` applied and no in-flight component. Native PID
`1208574` maps the expected screen artifact. Printer ready/standby, all targets
zero; identities, loaded flags, nozzles, physical mapping, saved variables,
configuration sections and all four PID tunes match the pre-install snapshot.
Evidence is under `analysis/validation/2026-11-12-managed-audit/r130-*`.

The first live read-only discard review correctly refused unreadable coordinate
markers: the root screen's `mkstemp` created both sidecars as root-owned 0600.
Changed only those two existing marker modes to 0644 and verified unchanged
contents/hashes. Review then returned HTTP 200 with unchanged position, targets,
print state and discard receipt. No confirmation was sent. The future-writer fix
is local, not installed: publish these format/hash markers with explicit 0644.
Recovery-hook tests pass (10 passed, three unavailable-client cases skipped).

Actual saved evidence is two legacy checkpoints and their coordinate markers;
there is no managed job, execution, attempt or envelope record. Native
`start_recovery` currently emits a notice rather than opening the managed panel
for the missing-job case. Stock preparation remains suppressed. Connecting that
blocked legacy selection to the review panel is still required before native
REVIEW/CANCEL acceptance; successful API review does not close that UI gap.

Local follow-up now connects missing/changed selection and missing managed-job
cases through `wmp_managed_recovery_review(1, reason)`. This bounded callback only
queues presentation; it cannot submit Continue, review HTTP, DISCARD or stock
preparation. Unsupported/unavailable receivers retain the existing notice and
refusal. The native panel offers the already separate explicit REVIEW action.
Actual C-hook tests prove missing-job routing and no stock fallback; native
runtime/lifecycle tests prove no commands on opening, retained widgets and
disabled controls through disconnection. Both native tests pass. This bridge and
the marker writer fix are not installed in r130. ARM compilation passed and the
combined follow-up is staged as `qualification-export-r131`, with screen SHA256
`caa4ca9016a62f26d8501700677746e265a9af181cd50e809e5141d3fddd53da`.
Native device review/CANCEL acceptance remains open; API acceptance and host
callback/panel tests are not substitutes for that observation.

### Native recovery prompt entry — 12 November

Read-only inspection confirms the printer currently has
`plr_print.was_interrupted=False` and `plr_file=hanzao` (the vendor placeholder),
not a selected interrupted print. Evidence:
`analysis/validation/2026-11-12-managed-audit/recovery-prompt-gate.json`.
The exact 1.1.13 binary's ready initialization calls `if_need_plr()`, then
`plr_load_AorB()`, and only draws popup type 3 if both succeed. `if_need_plr()`
requires enabled PLR and the literal recorded value `True`; missing defaults to
`False`. The provenance inspector now records the symbols, literals and branch
windows, with four focused tests passing. This is static entry-path evidence,
not native-panel acceptance.

Do not restart again expecting this existing state to open the recovery panel.
Do not set `was_interrupted`, replace the placeholder filename, or manufacture a
checkpoint merely to reach it. The r131 device review/CANCEL check stays open
until a legitimate recovery entry is available. No printer command, saved-record
mutation, deployment or restart was performed for this investigation. Continue
independent release checks meanwhile; accepted physical filament tests remain
accepted.

### Combined candidate prepared — 12 November

The accumulated local changes through `df40546` compile for AArch64 using the
pinned build container. A single r130 delivery tree is staged at
`analysis/validation/2026-11-12-managed-audit/qualification-export-r130`.
Artifact SHA256: `9d0797737353f5374298fbad2add9fccdcebf1b8c1910cd9e6a6b14310e42669`.
Export verified compiled/runtime source bindings and the vendor client profile;
the archive contains the matching retirement helper, material backend and native
worker. This is a packaging-control-only candidate, not an installed or released
build. The subsequent r130 installation and findings are recorded above.

Next device qualification for this batch is the affected native recovery review,
CANCEL/result/reopen behavior and retained-widget response, with no print or
recovery continuation. Do not discard real printer recovery evidence merely to
prove the confirmation path; the destructive-to-resumability action is already
covered locally using temporary evidence. Confirm the printer's actual saved
recovery context before choosing a device test. Installation/readiness checks
are a prerequisite once per deployment, not feature acceptance. Previously
accepted load/unload, purge/wipe and unchanged stock behavior remain accepted.

This is the current acceptance checklist. Older dated sections below are history,
not a current gap list. Cross-checked against **S01–S15** and applicable **R12–R18**
in [the stock UI plan](../ui-plan.md#5-screen-by-screen-target-disposition), current
native sources, backend admission, and activation evidence through r129.
“Implemented” does not mean physically validated. An unchecked item is not passed.


### Current audit follow-up — 11 November

R21 direct-load adapter follow-up (local, not yet deployed): comparison with
openACE's `OPENACE_LOAD_DIRECT` preparation/DONE contract found that WM+ did not
revalidate the reviewed owner/configuration after preparation or while waiting
for insertion. The adapter now checks the WM+ session/generation and idle
context, openACE session/revision/job/operation, and a copied filament identity
before sending DONE. Error cleanup also refuses to cool a replacement context.
The raw sensor helper already represents presence, so the initially suspected
inserted-versus-loaded wait deadlock was not reproduced.

Direct admission now also accepts an inserted strand when openACE records the
head as empty. Unknown/already-loaded owner state with a present strand still
refuses; an unreadable sensor is not replaced by saved empty state. The reviewed
plan copies/binds the owner's load record so changes before queued preparation
invalidate the review.

Focused adapter tests pass: 49 cases covering existing ACE load/unload plus
direct-load completion, timeout, and context changes during preparation and
insertion (including in-place metadata changes), inserted-strand admission and
owner/sensor refusal cases. No printer action or deployment
was performed for this check. This does not close owner-specific qualification:
openACE-owned STOP and the live end-to-end workflow remain open.

STOP contract finding and local adapter implementation: openACE registers reactor-side `openace/abort`, which
does not wait for the G-code mutex. Its direct-prepare/direct-prime abort paths
have owner-side tests. WM+'s native `can_cancel()` and filament-cancel endpoint
previously required standalone ownership. Simply enabling that button or sending
an abort is insufficient: between prepare and DONE, WM+ owns the insertion wait
and openACE has no active command to abort. The backend now binds cancellation
to the live operation object, owner object, request/head/session and openACE
session/job. During direct preparation/feeding it invokes the same reactor-safe
`abort_operation` method used by openACE's endpoint; during insertion it latches
cancellation locally and prevents DONE. Duplicate requests do not repeat abort.
The binding/capability is removed when the worker exits. Replacement owners are
neither aborted nor fed, even if their status reuses the same session fields.

The native screen and transport now allow STOP only when the matching live
operation advertises direct-load cancellation support. The request uses WM+'s
helper session, not ACE's session; the numbered progress/heating rows use that
same helper session. Stale helper sessions cannot send STOP, and acknowledgement
alone leaves the progress receipt pending.

After cancellation, the worker drains motion, requests heater-off, and checks
fresh owner context, empty abort scopes, no pending device stop and a zero heater
target before reporting stopped. Missing evidence or any cleanup failure keeps
the result unknown. A stopped result does not change openACE's filament record
or imply the head is ready to load; the message explicitly requires checking
owner filament state.

An unresolved direct-load result now retains its original live owner/operation
binding and offers RECOVER to recheck stopped state. This executes only motion
drain, heater-off and owner-state verification, never preparation/feed or
`OPENACE_RECOVER` and never a filament-record write. Numbered cleanup stages are
shown. New Load requests cannot replace this unresolved result. A stale request,
helper/ACE session, command generation or owner is refused, including an owner
replacement while draining. Reopening the result uses WM+'s helper session.
This is same-session stop reconciliation, not migration of openACE recovery
records across restarts or resolution of its separate filament-assessment holds.

ACE-slot load/unload now use the same cancellation and stop-reconciliation
adapter. Abort dispatch is bound to the expected `select T<n>` or `unload h<n>`
operation. All openACE filament requests return a receipt before running in the
queued G-code worker, so a long owner command does not occupy the screen's
status/STOP transport. The worker revalidates the reviewed source under the
command mutex; reviewed loaded state and identity are copied rather than aliased.
Tests verify changed contexts before dispatch, stopping both slot actions,
pending-stop refusal and later explicit reconciliation without replay or
filament-record changes.

132 focused backend tests pass. The unchanged native transport/lifecycle tests
and ARM build from the direct-load reconciliation change remain applicable
(`/tmp/wmp-openace-stop-recovery-arm.log`). These backend changes were exported and deployed in r129 (activation evidence below). Native/live cancellation and result reconciliation
acceptance for both direct and slot sources, and broader owner recovery, remain
open.

Runtime interoperability evidence: six opt-in cases in
`tests/interop/openace_filament.py` pass against openACE's real extra,
coordinator and routing runtime with fake Klipper hardware ports. They exercise
empty/inserted direct loading, STOP during preparation/insertion/feeding, and
reconciliation after heater-off delivery failure without another feed or
filament-record write. WM+ is constructed with its adapter fields; this is not
full dual-plugin startup or physical-printer acceptance. The upstream fixture
is extended with a pause status method, heater G-code port and explicit synthetic
path distances; no owner workflow is stubbed and unit I/O is forbidden.

The inspected openACE checkout was based on
`e79684508d4df5cba9ce72ff905d8f8b40ff85d4` with 143 tracked modified files,
so these results qualify that development worktree, not the unmodified commit
or an openACE release. `klipper/extras/openace.py` SHA256 was
`34453d41fe40aef67ef35ceb708b89cff25b5612010460b73a3e75915235a41f`;
`openace_runtime.py` was
`ab4bdfb0fb57211b60dd638dbf7257fb563981bbaafd942d612a63bbe900ac48`.
No external checkout files or printer settings were changed.

Reproduce explicitly (not part of default standalone test discovery):

```sh
PYTHONPATH=/path/to/openACE:"$PWD/klipper_extras" uv run --with pytest --with jinja2 --with pyserial==3.4 pytest -q tests/interop/openace_filament.py
```

The [managed-behavior audit](../upstream-client-callers.md#managed-behavior-conflict-audit--11-november-2026)
is incorporated as R20–R27 in the [design](../ui-plan.md#8-command-boundaries-and-recovery-ownership).
This snapshot supersedes older implementation-status descriptions below; it does
not supersede their accepted physical observations.

The current evidence table is maintained at the top of this document. Dated notes
below are historical evidence, not an independent queue of outstanding checks.

R22's detailed [integration findings](../print-mesh-recovery.md#implementation-findings-and-remaining-integration--11-november)
include the missing filename in native checkpoint data. The selected file must be
verified explicitly, not inferred from the checkpoint offset. No new print,
power-loss test or reset is authorized by adding these checklist items. USB copy
and profile import remain deferred; unchanged stock behavior stays out of scope.

### Recovery retirement backend — local implementation, 11 November

Added explicit `wmp/recovery/retire_review`, `WMP_RETIRE_RECOVERY` confirmation,
and `wmp/recovery/retire_result` readback. Review binds the current session and
raw evidence; confirmation requires command ownership, idle/settled machinery,
heaters off and unchanged evidence. Completed-execution admission and recovery
review reject an exactly retired checkpoint. Readback verifies the durable
receipt/archive without replaying the action; replaced evidence reports
`superseded`, and corruption refuses. Periodic status only copies the in-memory
result; it performs no retirement filesystem reads.

Thirteen focused backend cases pass, covering confirmation, changed context,
restart readback, corrupt receipts and no machine commands or source writes.
The constructor integration passes in both plugin initialization orders. Package
and rollback checks cover the new installed helper and source dependency; the
delivery run passed 93 cases, then its two corrected fixture cases passed in a
39-case focused run (including completed-execution admission regressions).

Startup handling now preserves invalid records, exposes `recovery_restore_error`,
and blocks normal operations while allowing explicit discard review without a
running attempt. A verified archive can retire the exact old attempt even after
a new job replaces the other evidence; it cannot retire a replacement attempt
or the new job. Native projection retains the unresolved-operation hold when
the journal cannot be parsed. Startup/status never performs discard or motion.

Local validation: 51 retirement/startup cases and 29 existing attempt,
cancellation, resolution and continuation cases passed. The six invalid-journal
cases (including JSON null) and compiled native projection check also passed.
This remains local and undeployed. These tests do not establish physical
recovery acceptance.

The local `RecoveryRetirementWorker` now separates read-only review, explicit
single-send confirmation and durable readback on a background thread. A lost
command acknowledgement triggers readback, never command replay; unavailable or
malformed readback remains unknown and can be explicitly refreshed. Review binds
the backend session; readback after restart retains the original action identity.
Status observations do not enqueue network requests. Fake-HTTP tests cover these
boundaries, and real loopback tests cover the exact added endpoints and bounded
hex command.

Native runtime and existing recovery panel are now connected locally. A blocked
recovery or invalid startup journal offers REVIEW, then CANCEL/DISCARD after
review; unknown delivery offers REFRESH, which only reads the durable result.
Three numbered stages retain their widgets across updates. The filename comes
from the backend's reviewed job evidence, or explicitly remains Unknown. Closing
a reviewed confirmation cancels its ticket; status sync cannot submit it.
The backend advertises protocol 1 in this local build. Native runtime integration
and panel tests cover zero actions on opening/refresh, explicit confirmation,
duplicate taps, result display and widget retention. Worker tests cover cancelled
tickets, stale sessions and lost acknowledgement; 14 focused backend retirement
tests pass. Backend startup now restores the verified receipt into its compact
status; a fresh screen worker adopts that history without HTTP work or command
replay. The blocked-recovery view offers RESULT to open it explicitly, then
REFRESH for current readback. Twenty-one focused restoration/backend/worker
cases pass, including a replacement job reporting superseded and no repeat
command after screen reconstruction. Deployment/native-device qualification
remains open.

### Recovery retirement receipt layer — local implementation, 11 November

The evidence store now publishes a session/request-bound retirement receipt only
after immutable archive verification. Readback verifies the archive hash and
manifest against the current evidence; changed bytes, file identities or missing
entries yield `matches=false`, so a receipt cannot retire a replacement job.
Receipt/archival corruption raises rather than becoming an absent or successful
result. Reusing a request with changed context refuses; an exact retry reads the
existing verified receipt without rewriting it. Reviews bind the prior receipt
identity as well as source evidence, preventing stale review from replacing a
newer receipt.

All 24 temporary-file tests pass. New cases cover restart readback, idempotent
retry, identical-byte replacement, newly created evidence, damaged/missing
archives, corrupt receipts, receipt file/directory fsync failure and a competing
receipt after review. A failure after atomic publication is not reported as
success; readback can identify the durable result without replay. No original
records are altered. These primitive tests do not complete the discard workflow;
the subsequent backend work and remaining gaps are recorded above.

### Recovery retirement evidence layer — local implementation, 11 November

`wmp_recovery_retirement.EvidenceStore` now implements the fixed-file raw review
and immutable archive layer. Manifests include missing entries, exact byte
hashes and file identities; empty/non-JSON evidence remains preservable. Double
collection detects changes across the set, and archive publication rechecks
review/admission before and after durable publication. Archive publication
alone creates no retirement authority and never changes original records.

Fourteen temporary-file tests pass, covering raw/empty/missing preservation,
idempotent archival, symlinks/FIFO/directory/size refusal, identical-content
replacement and other edits, file/directory fsync errors, ownership loss and
source edits during publication. The module is not yet imported into WM+ or
packaged for deployment. Receipt publication/validation, backend admission and
startup integration, native confirmation, further fault cases and live
acceptance remain required. This is an implementation step, not a completed
discard workflow. No printer operation occurred.

### Accumulated frontend regression gate — 11 November

At feature commit `ad1f1ff`, all **41 tests** in `tests/test_unified_ui.py`
passed in **126.11 seconds**. Command:
`uv run --with pytest --with jinja2 pytest -q tests/test_unified_ui.py --tb=short`.
Evidence: `analysis/validation/2026-11-11-managed-audit/frontend-regression-ad1f1ff.log`.
This checks the accumulated frontend transport/review/lifecycle changes against
the broader native UI suite. Together with the backend gate below, the current
batch has passed these local regression suites. Separate Re-print callback and
optional-openACE integration evidence remains described above/below; live and
physical acceptance remains open. No deployment, restart or printer command
was part of this gate. Further unchanged reruns are not needed.

### Accumulated backend regression gate — 11 November

At feature commit `f59002f`, the full `klipper_extras/test_wm_material.py`
regression run passed: **1146 tests, 132.91 seconds**. Command:
`uv run --with pytest --with jinja2 pytest -q klipper_extras/test_wm_material.py --tb=short`.
Evidence: `analysis/validation/2026-11-11-managed-audit/backend-regression-f59002f.log`.
This broader run was warranted by the accumulated shared owner-operation,
STOP/reconciliation and admission changes. It covers local backend behavior;
it does not replace native/live/physical acceptance, qualify an openACE release,
or close external Unload support. No deployment or printer commands occurred.
Do not repeat this gate for documentation-only changes; rerun affected coverage
when further implementation changes justify it.

### External Unload explanation delivery — 11 November

Both full-plugin startup-order tests now inspect WM+'s complete status payload
after the successful direct load: openACE remains the metadata owner, no
unsupported unload plan is advertised, the exact limitation appears under
`filament_procedure_errors["h2:unload"]`, and the successful load receipt is
preserved. Both pass. The targeted native procedure-review test also passes:
it displays that reason, remains unready and refuses submission without a
backend call. Existing projection forwards these errors unchanged; no UI
production change is required. This verifies explanation delivery through
status and review logic, not an on-printer screenshot. External Unload support
itself remains required as described below.

### R21 public-command integration and external Unload gap — 11 November

The complete-plugin tests now submit registered `WMP_FILAMENT_SEQUENCE` through
G-code after both Ready handlers, drain its queued callback, and verify openACE
records a completed direct load. Both startup orders pass. The initial attempt
correctly refused during WM+'s two-second sensor settling period; advancing the
fake reactor through that real interval permits the load. Simulated physical
ports use the same explicit path distances/heater handler as earlier adapter
tests. No production workflow is stubbed.

Attempting Unload after that successful load exposed a real contract mismatch:
WM+ admitted a direct destination but sent `OPENACE_UNLOAD`, whose owner runtime
rejects hand-loaded filament at preflight. Both startup orders reproduced an
unknown WM+ result. No separate direct-unload entry exists in the inspected
openACE checkout. WM+ now refuses that unsupported plan with an explicit reason
before dispatch, preserving the successful load receipt and owner's loaded
record. The two integration cases and 13 ACE unload/cancellation cases pass.
This guard is local, held for the next batch; standalone unload is unchanged.

**Still required, not closed by refusal:** managed external Unload while openACE
owns the head needs an owner-supported direct-unload operation (or an explicit
ownership handoff contract). It must perform mount/heat/tip-shape/retract,
report removal readiness, update owner state from completion/sensors, and
support STOP without competing WM+ motion. Do not bypass ownership by calling
standalone extrusion and writing openACE's loaded record from WM+. Once that
contract exists, connect it to the existing modal and verify the public
load/unload cycle. This is a concrete release compatibility gap, not a request
to revalidate unchanged stock unloading.

### R21 complete-plugin initialization — local, 11 November

Two additional opt-in interoperability cases initialize the complete WM+ and
openACE plugins together, in both constructor orders, before the shared
`klippy:ready` event. Both Ready sequences pass, WM+ declines its standalone
AFC metadata aliases and publishes no standalone lanes while openACE owns them,
and openACE's public head/filament metadata commands still produce verified
owner records. WM+'s execution timer starts and Disconnect stops it. The
upstream fixture forbids physical unit I/O; paths remain in the test temporary
directory. No production workflow is replaced.

The fake Klipper printer supplies a temporary config-file start argument and
the missing reactor NOW constant. The initial failure was that absent fixture
constant. Both cases pass with those hardware-interface additions. This closes
the previous constructor/Ready-order coverage gap for zero-unit openACE;
attached-unit startup, actual printer startup and native/live flows remain
open. Existing six adapter workflow cases were not rerun because this addition
changes only the new test. No printer deployment or restart was performed.

### Runout-to-Resume ownership trace — 11 November

The native hooks retain detection but suppress the old automatic runout purge
and resume-check workers. Popup kinds 99/100 request the managed Filaments
view; the legacy resume-preparation entry emits only `RESUME`. Tracing that
last call against the actual effective macro in `r129-after-status.json`
confirms standalone `WMP_CHECK_RESUME` runs before heating and again after
heating, before mapping writes, wiping, movement or parser restoration.

The installed backend check refuses unresolved cancellation/recovery,
running/unknown toolhead or filament operations, a print not fully paused,
missing or changed pause context, an incomplete replacement, wrong mounted
head or active extruder, and any required head lacking a loaded record.
The second check matters because heating yields. Existing focused backend
and macro-ordering coverage already tests these conditions; it was inspected,
not rerun as a new acceptance claim. This closes the source/effective-config
trace of the standalone stock Resume entry, not physical runout recovery.
The optional openACE branch deliberately delegates ownership and still needs
its separate owner qualification. No printer commands were sent for this audit.

### R20 Re-print callback acceptance — local, 11 November

The native event test now executes the queued completed/stopped Re-print
callback into a real `Runtime`, through managed preview preparation to the
stock drawing boundary. Both popup kinds preserve the filename captured when
clicked even if stock filename storage changes before dispatch, dismiss only
the owned popup, navigate to the local-file page and create a new preview
generation. The fake HTTP and command ports fail on any call, so no direct
print submission is permitted by this test. Existing duplicate-click, stale
popup and ordinary Close behavior checks still pass. Both tests in
`tests/test_native_reprint_gate.py` pass.

The drawing function deliberately stops at that boundary: this adds callback
integration evidence, not live stock-popup rendering or physical print
completion acceptance. Those remaining R20 checks stay open. No production
code, deployment, printer state or accepted load/unload test changed.

### r129 owner filament adapter activation and STOP retry follow-up — 11 November

The accumulated direct/slot Load, Unload, STOP and stop-reconciliation changes
are installed. Journal `cdd795e0044b48908096fef37e3ad1fc` is applied with no
inflight component. Independent readback confirms screen SHA256
`64992ed7b0c41dc4323ff5c43c4003d4be389ddb71454c8e4a60dba448808edb`
and backend SHA256
`f30608f21bd769d139e52819a763f10a9508fd21a83888244c932640f755bcf8`.
The current screen process is 1191592; native bootstrap and the recovery hook
are running. `r129-preservation.json` and `r129-native-readback.json` in the
11 November audit directory confirm Ready/standby, heaters off, and unchanged
configuration, saved variables, PID, filament identities, nozzles, mapping and
loaded flags. openACE remains disabled. This is activation evidence only;
it does not close native/live owner workflow acceptance.

A subsequent local failure-injection test reproduced a STOP retry defect: an
abort dispatch exception left cancellation intent set, causing the next STOP
to acknowledge without retrying delivery. Dispatch success is now tracked
separately in the bound operation. Intent remains latched, failed delivery can
be retried after fresh owner/context checks, and successful delivery is not
repeated. The new regression failed before the fix; 31 related cancellation
tests pass afterward. This follow-up is local and intentionally held for the
next batch, not another immediate deployment.

Deployment policy: batch changes and validate specific affected requirements.
Restart/readback checks are supporting installation evidence, not functional
completion. Previously accepted unchanged load/unload tests remain accepted.

### r128 numbered recovery preflight activation — 11 November

The numbered review/preparation-wait presentation is installed. Journal
`af44214d2afc4389ad7720ead4a6c74b` completed as `applied` with no inflight component.
Independent readback confirms screen SHA256
`414a5e19bfbd833034089ab035327351de6dcdde74491524b3d8aed2c7e121df`, native
bootstrap Running and recovery-hook initialization in screen PID 1178429.
Backend and recovery-module bytes still match their accepted versions.

`r128-preservation.json` and `r128-native-readback.json` under the 11 November
audit directory confirm Ready/standby, heaters off, and unchanged configuration,
saved variables, PID, identities/nozzles/mapping and loaded flags. This closes
activation of the local lifecycle-tested presentation; no recovery attempt was
started, so native recovery-flow visual/physical acceptance remains open.
Unchanged load/unload behavior was not retested.

### r127 original-attempt preservation activation — 11 November

Journal-preservation backend `712405e` is installed. Installer journal
`4c9593b0c91b4c91bf1d26479c3b04db` completed normally as `applied` with no inflight
component. Independent installed backend SHA256 matches the worktree:
`a9bee8dcf30b669c36dc7d6cebaa8313dc1dfa4bc8016b8f422d2ca728050e87`.
The new backend session is Ready/standby; native bootstrap Running and recovery
hook initialization are verified in screen PID 1175360. Configuration, saved
variables, all four PID tunes, identities, nozzles, mapping and loaded flags are
unchanged; heaters are off and the printer is not paused.

Evidence: `r127-install.log`, `r127-preservation.json`, and
`r127-native-readback.json` in the 11 November audit directory. The printer had
no interrupted recovery attempt, so this is deployment/preservation acceptance;
the archive failure/concurrency behavior remains supported by the focused local
tests, not a claim of live interrupted-recovery validation. No motion or print
was requested. Reset/rediscovery release scope is awaiting the user's explicit
decision; existing completion requirements have not been removed.

### r126 recovery fallback protection activation — 11 November

The missing-managed-job fallback fix is installed. Installer journal
`0ef4a94cff5e4009b4931703c825a298` completed as `applied` with no inflight component.
Independent readback confirms the staged recovery C source equals this worktree,
the installed module matches its compiled-output receipt, and screen PID 1171382
maps that module without a deleted-library mapping. The current process logged
recovery-hook initialization and the native UI reports bootstrap Running.

Recovery module SHA256:
`70ce1cc91d1f0c0ad9bd167dab9aeed8599da97dc366ac1eeaa86b0c431bfca4`.
`r126-preservation.json` confirms unchanged effective settings, saved variables,
four PID tunes, identities/nozzles/mapping and loaded flags; Ready/standby,
unpaused and all heater targets zero. `r126-native-readback.json` and the install
log retain the activation evidence under the 11 November audit directory.
This closes deployment of the tested fallback guard, not native legacy-record
resolution, disposal/migration or physical recovery acceptance. No recovery,
motion, extrusion or print was triggered; installation restarted idle services.

### r125 service-control guard activation — 11 November

The disabled-control guard is installed. The installer completed normally;
journal `a06ee58173cb48c4a5cf1b0fe7749124` is `applied` with no inflight component.
Independent readback verifies artifact SHA256
`c58d660faef35d319ba5b3fb8ad64c800166402f792c3a3fc44664799d780c42` and native
bootstrap Running in screen PID 1167507. Recorded status polls advance
119 → 126 → 133 with the cumulative failure count unchanged at 15.
The Home screen renders after restart. This establishes activation, not injected
physical disabled-event coverage or full entry-route acceptance.

`r125-preservation.json` records Ready/standby, no pause, all targets zero,
unchanged effective settings, saved variables, four PID tunes, identities,
nozzles, head mapping and loaded flags. Evidence and diagnostic captures reside
in `analysis/validation/2026-11-11-managed-audit/`. No motion, extrusion or print
was requested; the installer performed its required idle service restart.

### r124 deployed notice acceptance — 11 November

The source-bound r124 install completed normally with journal state `applied`
and no inflight component. Artifact SHA256:
`d61d3a9be04349dc89eff929889075008b15cb9f3b94c8c5ec067471870f7bee`.
Installation readback preserves effective configuration, saved variables, all
four PID tunes, identities, nozzles, mapping and loaded flags. The backend is
Ready, standby, with all heater targets zero.

The corrected reset-refusal panel is opaque and CLOSE is in its top row.
Live dismissal returns to General without changing managed recovery/material
state, saved variables, position or homed axes. Evidence resides under
`analysis/validation/2026-11-11-managed-audit/`: `r124-preservation.json`,
`r124-install.log`, and `navigation-r124-current` / `navigation-r124-reset-close`
screenshots and status captures. Earlier r123 reset interception/file-preservation
acceptance remains valid; this presentation-only change did not warrant repeating
all file checks. Full managed reset and external writer coverage remain open.

### Release validation boundary — 11 November clarification

The release target is the modified UI and its supporting managed backend.
Include stock recovery/runout/restart/reset entry points only where they can
bypass managed ownership, replay actions, or overwrite managed state. Each
remaining check must name that interaction or the changed feature it proves.
Unchanged, unaffected stock GUI behavior is excluded, not awaiting validation.
Do not repeat an accepted check without a relevant code change, failure, or
new evidence. USB copy and profile importing remain deferred.

### Audit closure checks still open

- [x] r123 navigation investigation: live counters advance; the input reader had
  X=0/Y=403 after a requested X=45/Y=403 tap. Changing both coordinates restored
  navigation. No native freeze was established; unchanged absolute coordinates
  retained by the input device across client restart explain the observed miss.
- [x] R23 live reset interception: Confirm shows WM+ refusal and CLOSE dismisses
  it without a reset worker or observed file/state changes (r123).
- [x] R23 refusal presentation: r124 displays an opaque panel with uppercase
  top-row CLOSE; deployed screenshot and dismissal verified. Managed state,
  saved variables, position, homed axes and zero heater targets remain unchanged.
  This closes the presentation correction only, not full managed reset support.

Follow the [required closure evidence](../ui-plan.md#required-audit-closure-evidence)
without repeating accepted unaffected tests. These are pending acceptance gates,
not a claim that all corresponding implementation is missing:

- [x] R20 completed popup: real Re-print enters fresh managed preview (r134),
  with metadata-free PRINT refusal and CANCEL accepted.
- [ ] R20 stopped popup: corrected stopped-filename fallback still needs genuine
  native caller acceptance and supported-owner qualification.
- [ ] R21: qualify legacy adapters under the supported openACE owner.
- [x] R22 native receiver/background delivery and numbered recovery stages with
  heating readout accepted through r149/r151; native STOP→DISCARD→CONFIRM accepted
  r153. Do not repeat these baseline flows.
- [ ] R22 interrupted-result reconciliation remains open. The r160 resumed coupon
  completed before the second interruption; that attempt is not acceptance.
- [x] R22 local numbered preflight: saved-job review is step 1 before an attempt
  receipt exists; a refusal is explicitly marked blocked. Successful review
  turns gray and preparation wait remains numbered until actual backend stages
  arrive. Lifecycle checks verify retained nodes/scroll, colors and heating
  display. ARM build passed; r128 activation is verified. Native recovery-flow
  visual acceptance subsequently passed r149/r151.
- [x] R22 standalone physical clearance and continuation accepted r151 through
  actual resumed print completion.
- [ ] R22 durable incompatible-record native handling and supported-owner recovery
  remain open; successful current-format recovery does not establish either.
- [x] R22 local missing-job fallback guard: a loaded WM+ receiver prevents stock
  preparation even without the required-job environment flag or job sidecar.
  Actual C harness and ARM compile pass; r126 activation/source/module readback
  passed. This does
  not complete older-record disposal or migration.
- [x] R22 local startup evidence preservation: before converting a valid pending,
  running or interrupted-continuation journal to unknown, preserve its exact
  bytes in a content-addressed original archive. Archive failure/conflict or a
  changed source refuses the rewrite. Ten focused cases and 60 attempt/file
  regressions pass. Installed r127 with backend-byte/Ready verification and
  state preservation; broader older-record disposal remains open.
- [x] R22 disposal design: defined explicit raw-evidence review, immutable archive,
  exact-manifest retirement receipt, no original-file deletion, no guessed schema
  migration, and required native/fault acceptance in
  [the recovery design](../print-mesh-recovery.md#explicit-retirement-of-incompatible-evidence--implementation-contract-11-november).
- [x] R22 retirement implementation: raw evidence archive, separate review and
  confirmation, durable receipt/readback, startup/admission and native panel are
  implemented and included in r130/r131 and later deliveries. Local fault tests
  and live read-only API review are recorded below.
- [x] R22 current-format retirement native acceptance: original prompt
  Cancel→REVIEW→CANCEL and Cancel→REVIEW→DISCARD→restart accepted r156, including
  exact nine-record archive and no discard motion.
- [ ] R22 incompatible-record retirement native acceptance remains open. Historical
  format public-path tests do not establish device acceptance; do not fabricate
  production records to reach this screen.
- [ ] R22: qualify native resolution review/confirmation, stale sessions, lost
  acknowledgements and partial cleanup. Confirm no action on status sync and no
  automatic continuation after reconciliation.
- [x] R23/R24 local ownership: identification refuses an active or unresolved
  probe editor before latching setup; transaction admission rechecks the hold.
  Host tests prove no movement/file changes on refusal and later explicit entry.
- [x] R23 local runtime ownership: full admission is checked between identification
  steps; original owner/session/generation fence command delivery, cleanup and
  publication. Injected state changes prevent the next pickup and file writes.
- [x] R23 local identification result: protocol-2 session/request receipts settle
  preflight refusals without trapping the screen on Waiting; duplicate delivery
  never starts a previously refused or partially failed attempt. Fresh explicit
  START is permitted after a refusal; installed protocol acceptance is required.
  Runtime tests also cover sender fields and require the outstanding request's
  completion receipt before RESTART; cached complete status alone is insufficient.
- [ ] R23: qualify identification refusal/retry and interrupted-result presentation
  on the printer, alongside the existing physical setup gates.
- [x] R23 local startup-discovery boundary: exact native startup caller cannot
  launch the topology-writing discovery script; compiled ARM and source/profile
  tests pass. Explicit managed identification remains separate.
- [x] R23 r132 startup-preservation qualification: exact artifact and Running
  bootstrap verified; all 19 affected files, effective settings and filament state
  preserved across the combined installation. Compiled ARM tests establish the
  exact-call suppression; no CAN failure was deliberately induced.
- [ ] R23: inventory remaining supported configuration writers; prove calibration,
  managed state and travel/wipe preservation, rollback and post-restart verification.
- [ ] R23: missing/unreadable saved calibration or templates and invalid head
  counts refuse before any live write; never fall back to a four-head template.
- [ ] R23: topology shrink retains original removed-head calibration; reordering
  or replacement uses verified hardware identity rather than slot-only reuse.
- [x] R23 local joint-transaction fault injection: lost acknowledgements and
  process loss after each of seven changed files, concurrent-edit preservation,
  journal tampering, complete rollback and post-restart mismatch/admission are
  covered by `klipper_extras/test_head_configuration_transaction.py`. Accepted
  in the 11 November 201-test run; unchanged tests were inspected on 12 November,
  not rerun. This is library/disposable-file evidence, not device qualification.
- [ ] R23 integrated recovery: qualify the native interrupted-result controls
  and restore/re-enable them only after loaded configuration/contract verification.
  Do not repeat the accepted disposable-file fault matrix to stand in for this.
- [ ] R23: distinguish assignment repair from physical head movement; establish
  calibration provenance before migration. Keep dock positions fixed and define
  reference-head offsets/mesh and saved calibration/pressure/flow policies.
- [x] R26 offline warning predicate: nine hash-bound ARM cases trace the actual
  return and warning branch. Stock blocks printing/paused but permits standby;
  it does not represent WM+ service/recovery holds. Existing backend admission
  remains necessary. Live warning presentation and other-owner policy stay open.
- [ ] R26: cover service-manager/startup restarts separately from G-code restart.
- [x] R26 local direct-writer admission: guard SAVE_CONFIG and vendor
  SAVE_CONFIG_NO_RESTART before file writes. Retained writer tests prove refused
  commands preserve originals, backups and pending values; admitted calibration
  and other-owner behavior remains covered.
- [x] R26 direct-writer guard deployed in combined r132: exact backend, new Ready
  session, registered save commands and unchanged configuration verified.
- [ ] R26: qualify affected live admission without manufacturing a calibration write;
  installed command names alone do not prove active-operation refusal.
  Opening an editor only shows a draft and does not establish calibration_active;
  pair this check with a genuine managed operation hold, rather than invoking
  SAVE_CONFIG against an idle printer and assuming it will refuse.
- [ ] R24: save only after a session/helper-bound successful finalizer receipt.
  ACCEPT may refuse without raising; inactive manual-probe status is insufficient.
  Cover abort, helper replacement, finalizer failure and lost replies without replay.
- [ ] R24: verify editor admission before mutation/jog and acknowledged save;
  refuse stale sessions while keeping Close/cancellation responsive.
- [x] R24 local backend: bind save to successful original finalization; own the
  staged offset; refuse unrelated pending saves and preserve other edits on discard.
- [x] R24 local native primitives: validate projected receipts and sequence explicit
  actions; sender tests cover blocked HTTP, duplicate taps and late replies.
- [x] R24 local lifecycle: confirmed completion permits a new explicit request;
  duplicate, stale and unresolved requests cannot reopen preparation.
- [x] R24 local panel: retained controls and numbered stages update in place;
  host tests cover disabled/stale/hidden/deleted taps and command-free refresh.
- [x] R24 installed Maintenance navigation: open, CLOSE, reopen and CLOSE the
  idle managed probe panel without START. Numbered stages and uppercase actions
  are visible; 13 navigation observations preserve editor request/sequence,
  position, homed axes, heater targets, saved variables and loaded state. This
  covers the Maintenance entry only, not Factory, active STOP or save review.
- [x] R24 local entry routing: Maintenance, Factory probe action, direct probe-page
  navigation and both legacy editor callbacks open managed review. Explicit START
  alone begins preparation; old callbacks cannot dispatch jog/abort/save.
- [x] R21/R24 local disabled-input guard: intercepted Nozzle Flow, Maintenance,
  Factory probe and legacy probe-editor routes consume clicks on disabled
  controls or disabled ancestors before opening review, checking admission or
  delegating. Native lifecycle cases cover each route and the firmware accessor
  profile matches retained 1.1.13. Installed r125 with exact artifact match and
  native bootstrap Running; live route qualification remains separate.
- [ ] R24: qualify those entry routes on the printer and provide explicit
  review/reset of restart-invalidated sessions.
- [x] R24 local preparation STOP: request-bound reactor latch, checkpoints, direct
  motion drain, independent native delivery and retained STOP control tested.
- [x] R24 local failed-preparation cleanup: helper-bound cleanup-only ABORT and
  no-helper DISCARD revalidate ownership/configuration after direct motion drain;
  no configuration write or inferred acceptance. Host checks passed.
- [x] R24 local action refusals: record pre-action refusal against its request and
  sequence, preserve the editor phase and settle the native request without replay.
- [ ] R24: qualify integrated STOP/notification and failed-preparation cleanup on
  the native screen and printer; local evidence does not close these gates.
- [x] R24 local concurrent-offset review/KEEP: backend and retained native controls
  bind the displayed complete snapshot, preserve newer edits and never save.
- [x] R24 local writer evidence: require the firmware_restart boundary, refuse
  quick-stop and preserve unknown outcomes without retry.
- [x] R24 local durable review: publish intent before writing; restore Ready hold;
  explicit backend REVIEW/ACK binds current configuration and retains and archives evidence.
- [x] R24 local REVIEW/ACK receipts: protocol 2 binds session/request/sequence,
  deduplicates delivery and distinguishes refused from uncertain storage outcomes.
- [x] R24 local native review controls and background transport connected; cached status
  and HTTP delivery must not acknowledge a new review action.
- [x] R24 local restart-invalidated native sessions use explicit review;
  never replay old actions; permit new START after authoritative acknowledgement.
- [x] R24 local offset-only mismatch: explicit snapshot-bound RETAIN preserves
  the loaded/disk-agreed offset and original evidence without writing configuration.
- [ ] R24: define broader mismatch/missing/corrupt-evidence recovery separately from KEEP;
  preserve evidence and holds without inferring save success or retrying SAVE.
- [x] R24 local deployment acceptance: require loaded editor/STOP/save-review
  protocols 1/1/2, matching sessions and valid review status; preserve unresolved holds.
- [x] R24 installed protocols: r121 editor/STOP/save-review/RETAIN 1/1/2/1
  verified after a new Klipper process, with unchanged calibration and filament state.
- [ ] R24: qualify lost replies, native review/ACK,
  notification behavior and post-restart configuration preservation.
- [ ] R24: qualify the integrated editor on the printer and for each supported owner.
- [x] R25 local failure review: outer/nested retry guards preserve all nonzero
  faults; failed pickup cannot trigger another LOCK or UNLOCK.
- [x] R25 local actuator boundary: failed homing cannot reach zero/post-stroke;
  session/generation checks fence later commands, fault writes are read back and
  failed persistence shuts down. Retained vendor-method regressions pass.
- [x] R25 installed contract, 12 November: read effective configuration and command
  registration without G-code. LOCK, UNLOCK, _LOCK_CHECK, _LOCK_TOOL_FINISH,
  _CHECK_CHANGE_TOOL, PARK_CURRENT_TOOL_RETRY and _WMP_ABORT_TOOLCHANGE all match
  the reviewed local templates after whitespace/comment normalization.
  _WMP_COUPLING_STROKE is registered; deployed wm_material.py matches the reviewed
  backend byte-for-byte. The configured trans_stepper source matches the retained
  vendor implementation, including all four required method signatures.
  Evidence: `analysis/validation/2026-11-12-managed-audit/coupling-installed-contract.json`.
- [ ] R25: qualify the changed single-attempt actuator path mechanically; retain
  prior unaffected acceptance. Installed definitions are not mechanical evidence.
- [ ] R25: qualify other-owner recovery and review direct vendor-command bypasses;
  include the optional vendor color_feeder sensor worker if supported. Read-only
  live inspection on 12 November found no color_feeder/feed_slot effective settings
  or exported status objects, so that optional path is not enabled on this test
  configuration. This does not qualify configurations that enable it. The only
  discovered -6 assignment is commented out; no active writer is established.
- [ ] R26: qualify each restart caller against active/paused/unknown operations
  and durable interruption handling.
- [ ] R27: qualify recovered-worker error cleanup and ownership after later native
  Resume; direct stock Cancel/service ordering is already reproduced locally.
- [x] R27 local implementation: exact standalone stock CANCEL_PRINT sender uses
  independent reviewed intent and retained numbered progress; host runtime/lifecycle
  checks pass. Generation fencing retires queued standalone work at admission and
  completion. This is not deployed-screen or physical acceptance.
- [x] R27 local routing: native Cancel batches and legacy script/remote Cancel
  ingress bind managed intent before waiting; nested standalone macro Cancel
  refuses stock cleanup. Owner-specific and live acceptance remain open.
- [x] R27 local queue fence: legacy run_script batches capture their generation
  before waiting and recheck before every command, including after an earlier
  command yields. Scoped heater-off/resolution and exact emergency stop remain
  available. An already executing command is not preempted.
- [x] R27 ordinary native STOP: remote log/wait job cancelled through managed receipt; six stages, colors and CLOSE accepted on r137, with stale queued mapping writes fenced.
- [ ] R27 remaining: interrupted-result controls, managed-service interruption, recovery interaction and supported-owner qualification. Hot-heater cleanup and the remote-start stale backup-write notification fix are accepted (see current status above).
- [ ] R27: validate interrupted-cancellation review/confirmation for original live
  file cleanup, idle cleanup, explicit saved-job discard and command-free completed
  cleanup acknowledgement. Cover restart, changed evidence, lost replies and
  partial failures; preserve unrelated operation uncertainty.
- [x] R27 local deployment contract: candidate acceptance requires cancellation
  and resolution capabilities, including WMP_RESOLVE_PRINT_CANCEL.
- [x] R27 ordinary cancellation screen: numbered pending/completed stages, summary, colors and CLOSE verified on r139.
- [ ] R27 interrupted resolution screen: REVIEW/CONFIRM and retained uncertainty still need device acceptance.

R22/R27 components are installed through development qualification r139. Ordinary
native and remote cancellation, progress/result presentation and preservation have
passed. Successful recovery and interrupted-result screen acceptance remain open. Historical local test counts below
are evidence for those components, not acceptance of these integration gates.

### Attended sequence completed — 9 November

Accepted: physical-touch navigation/menu exclusivity, unload/removal, insertion-
wait STOP, Dock with Z unhomed, automatic mounting through Load, Inserted versus
Loaded, restoration Load/feed/purge/wipe, DONE closure, and H3/H4 filament
identity/loaded-state persistence across operator-confirmed cold boot. Retained
live snapshots and operator confirmations are recorded below. Do not repeat
these checks without a relevant changed behavior or new fault.

Remaining operator observation: physical manual Retract direction. Reuse the
7 November observation that manual +25 mm brought filament out of the nozzle;
positive extrusion is already observed. Backend E deltas, screen dispatch,
position preservation and refusals already passed. Heating/extrusion outside a print must occur at the purge
position. On 10 November the operator approved the two prepared coupon prints
by confirming the bed is clear; paused/runout interventions remain unapproved.

Cold boot is now accepted for the observed H3/H4 loaded identities and sensor
state. This is distinct from prior client/Klipper restart evidence.

Purge-amount calibration belongs to the user in OrcaSlicer, not this checklist.
D02 validates delivery of the selected amount and wipe/completion. D05 temperature
selection remains separate from color-clearing effectiveness. Ask
what the operator has before prescribing a physical sequence. Host coverage of
generic-range selection/refusal remains valid; do not requalify every stock
material family. First-run/clean-stock and changed calibration caller checks need
their own controlled setup. Real print/paused/runout checks still need separate
print authorization. This run sheet does not close those gates.

### Rebase onto fw-1.1.13-r3 — 8 November

The standalone branch is rebased onto main `6dd79d6` (saved case-light control
and print cleanup). The pre-rebase checkpoint is retained as
`backup/standalone-ui-before-r3-rebase` (`18d8238`). Light hooks, bounded print-end
clearance, EOF cleanup, and native-pause cleanup coexist with standalone filament
and runout handling. Unified installation now includes the light helper, bridge,
configuration, and validator in its installation/dependency contract.

Local checks covered macros, recovery, runout callbacks, deployment/preflight,
light controller/bridge, configuration validation/preservation, helper rollback,
and package export. Integration failures from helper counts and runout wording
were corrected; affected checks passed on rerun. Native preflight test scripts
now use stdin instead of exceeding the OS argument-size limit. The preservation
installer validates its generated behavior, leaving unrelated stock/custom macro
validation out of scope. Clean-home exported installation and data preservation
passed with all six backend helpers. The rebased ARM candidate compiled; no
printer deployment or physical acceptance is implied.

Read-only post-LED status: Klipper Ready/standby, openACE absent, Head 3 mounted,
axes unhomed, nozzle targets zero, Head 4's loaded Kexcelled record retained.
Head 3 has sensor presence but is not marked loaded. Read-only file inspection also confirms the deployed screen and material helper
hashes match accepted r96. The LED helper/config and preload entry were removed
by the other agent during restoration. Evidence: `post-rebase-inspection/` in the
8 November validation directory.

Local correction: standalone load/unload no longer requires a Z reference.
Preparation requests G28 X Y when needed, omits the Z clearance lift, and finishes
Load with WIPE_NOZZLE XY_ONLY=1. The wipe option skips idle clearance while
preserving the normal wipe behavior for other callers. The two-file update is now deployed as r98 (r96 UI retained). H3 Load
completed from all axes unhomed in 78 seconds: XY homing, purge-position travel,
220 C heating, 55 mm feed + 50 mm purge, wipe, then target zero. All 63 samples
kept Z unhomed, its reference invalid, and reported Z unchanged. The mounted
head was retained. H3 is now loaded; H4 metadata/loaded state were preserved. The disabled-load screenshot also has Unknown material, which remains
a separate valid reason to require material selection before heating.

The changed backend, wipe-motion model, and homing/recovery suite pass **545
tests** (`xy-only-service.xml`); the ARM candidate also builds successfully.
Live evidence is in `r98-xy-load/`; activation backup/journal is in
`analysis/unified-ui-native/activation-stockwidgets-r98/`. This validates the
changed idle path with an already-mounted H3, not a paused print or a fresh
physical color-transition assessment. The camera confirmed travel/position but
does not resolve actual purge flow at the nozzle. The H1 Load editor no longer
shows Z guidance; Load enables after a valid material is selected even with Z
unhomed. That temporary selection was cancelled without loading/saving.

### Validation scope — user correction, 8 November

Only WM+ changes and demonstrated downstream effects are release gates. Every
remaining test must name the changed code/contract and the behavior it could
break. Retaining a stock screen, sharing a tab bar, or having a feature in the
stock-screen inventory does not make its normal operation a new test requirement.
Unmodified and unaffected stock behavior is out of scope, not failed or passed.
This scope overrides older broad qualification language in the history below.

Examples of in-scope dependencies are stock buttons that call WM+'s changed G28,
physical-head selection, Load/Unload, pause/resume, or recovery entry points.
Their affected command/selection/return behavior needs coverage; unrelated
features on the same screen do not. Reuse existing stock recipe behavior rather
than requiring fresh qualification of every supported polymer.

A checklist entry must identify (1) the WM+ change, (2) the specific behavior at
risk, and (3) the evidence still missing. If no changed dependency can be named,
remove it from current acceptance scope. A stock-screen inventory or an untested
stock feature is not evidence of an impact. Already accepted assertions remain
closed; test only the affected assertion after a relevant change, not the whole
screen or workflow. Deferred work and known input-data limitations are not
unchecked validation failures.

### Remaining coverage, excluding accepted baseline tests

This table controls selection of the next validation action. The longer entries
below retain chronological evidence; phrases such as “remaining” in an older
paragraph do not reopen a check completed by later evidence.

| Area | Accepted evidence to reuse | Actual remaining coverage / next action |
|---|---|---|
| H3 Load/Unload | H3 pink feed/purge/wipe user confirmation; completed unload stages, target-off, unloaded flag with inlet still present; confirmation Cancel | r98 XY-only preparation/wipe passed on mounted H3 with Z unhomed. No unchanged baseline repeat. D02/D05 cover the changed transition/purge behavior, not blanket stock material-family qualification. On 9 November H3 was unloaded for insertion-wait testing, then restored with completed Load; DONE closure passed. |
| Take/Dock | At least three completed cold cycles on every head, correct attachment/extruder/receipts; r102 H1/H2/H4 mounted-label and Dock readback accepted, returned to H3 | Dock with Z unhomed passed on 9 November after r110: operator confirmed clean release, completed receipt, empty carriage and only XY homed. Keep the reported intermittent homing impact as a watch item, not an instruction to repeat accepted dock cycles. r108 targeted H3→H2→H3 check closes the reproduced status dropout: 105 observer requests, maxima 823/878 ms versus r107 1,860/1,944 ms; no new native status failures and no unavailable banner in 53 captured frames. Do not repeat three-cycle counts. This does not guarantee absence of every intermittent fault. |
| Extrude/Retract | Backend +25/+50/-1/+1 E deltas and mode/XYZ preservation; cold/wrong-head refusal; live touchscreen +25/-1/+1 dispatch, final heater-off and unchanged XYZ/offsets/loaded records | Reuse the operator’s 7 November confirmation that an additional manual +25 mm brought filament out of the nozzle. Positive physical extrusion is therefore observed; do not repeat it solely for visual proof. Direct manual-retract direction remains the narrow unobserved case, which can be checked during attended recovery. Command-dispatch/mode/position assertions remain accepted. |
| Editors/navigation/heating | B01/B02/B05/B06/C01 accepted: head focus, exclusive menus, metadata/nozzle edits, remote metadata, per-head targets/off | 9 November physical-finger responsiveness sequence passed by user confirmation. Real H3 clear/present distinction and H3/H4 loaded identity persistence across operator-confirmed cold boot passed on 9 November. Existing round trips are not new gaps. |
| Progress/cancellation | Numbered stages/current-target; completed unload; STOP during heating; r93 process interruption/recovery and r94 retained result | Insertion-wait cancellation passed on 9 November: stopped in inserting phase, target zero, loaded false. Completed-result DONE closure passed by operator confirmation on 9 November. Reuse completed interruption/result evidence; do not repeat it merely because the UI restarts. |
| Preview/mapping | Real single/sparse/multicolor files, units/malformed fixtures, source/file change invalidation, mapping H3/H4, Cancel | E02 metadata presentation and E03 review/mapping are accepted from retained evidence. Missing usage is a source-data limitation; Single and mapped coupon execution/completion passed on 10 November, including five mapped changes, completion/history and target-off cleanup. Deliberate paused/runout recovery remains separate. |
| Status availability during printing | r116 records fixed failure category, stage and poll elapsed time; idle readback increased from 65 to 147 polls with failures unchanged at 21 (startup failures) | No new print-time reproduction after instrumentation. Capture failures during the next authorized physical recovery/print check; idle receipts do not close the print-time gap. Do not relax freshness or replay an accepted print merely to collect logs. |
| GUI synchronization | Active native screens, browser preview and legacy manual overlay have focused lifetime coverage | 9 November attended finger check passed: repeated Toolheads/Filaments navigation, exclusive H3/H4 menus, Edit/CANCEL; user reports “Everything worked.” No further reproduction is currently reported. Deferred import and unused generic renderer remain future-use restrictions. |
| Paused replacement/runout | Host implementation and admission coverage | r114 cross-head service and job-bound affected-head tracking are deployed; matching backend/screen hashes and interception hooks verified. Host load/unload/return/failure tests pass. Physical cross-head paused/runout recovery remains operator-deferred until after self-directed checks. |
| Delivery/recovery | Hash-bound staging export, installer/readiness tests, and actual SIGKILL/retry of preload restoration in temporary directories | Exported upgrade/startup, target loader and live current-version combined SIGKILL/host-journal recovery passed. Clean-stock installation and release promotion remain. Moonraker component live restore/reinstall and actual SIGKILL/host-journal recovery are also accepted. Packaging-control-only export is not release promotion. Do not substitute another passing unit-test run. |
| USB/import | Host copy coverage; local/history navigation | Physical USB copy and profile import are user-deferred, not current completion gates. |
| First-run filament setup (G03 / S12) | Shared filament flow, retired legacy loading workers, durable FINISH filesystem and lifecycle tests; r95 callback deployed | Live onboarding entry and FINISH/reboot persistence remain unqualified. Exact-handler audit confirms the normal route reaches identification/calibration before filament; calibration Skip goes Home, not filament. Use a controlled first-run environment or scoped setup run, not a reset solely to reach FINISH. See onboarding-route evidence. Unchanged language/network behavior is out of scope. |
| Changed calibration callers (G05 / S11/S15) | Exact stock dispatch audit, physical PID-head selection and G29 reference-preparation host tests; r70 changes deployed | Live verification of changed worker/cleanup dispatch and physical-head/reference selection remains. Unchanged calibration measurements and algorithms are out of scope. |
| Stock behavior ownership (R20–R27) | 11 November conflict audit C01–C07 delivered; current hooks and exact-client popup paths reconciled | R20 is installed with completion-popup qualification open; R21 adapters are installed in r118 with eight no-motion refusal checks passed; owner-specific openACE qualification remains open. R22/R27 are installed in development qualification r119 with protocol and idle-preservation checks passed; active recovery/cancellation and native resolution acceptance remain open. Reset/topology transactions, factory editors, failure retries and restart boundaries remain open. The current audit table above governs implementation status. Implement and qualify the affected paths per ui-plan section 8; the report alone does not close them. |

Before a new physical operation, record its specific uncovered assertion and why
existing evidence cannot answer it. Do not perform motion simply to reconcile a
checkbox. User interaction is needed for physical touch, filament repositioning
or a new material. The two prepared coupon jobs are authorized; after H4 reload
and bed clearance, the operator authorized a fresh mapped retry on 10 November.
Deliberate runout/recovery interventions are deferred until the operator is available.

### r104 onboarding guard deployed — 8 November

The normal exported installer activated the onboarding file-navigation guard.
Exact native artifact SHA256:
`36137b54974ec6f32cae9527834c9a9a53b94bed166c2ba3d77b727cc16404bd`.
Client PID 3822454 maps the verified package; restart/readiness and required
backend commands passed. Installer journal
`f3fd20e4aa8944bb87005a46fdb733e0` completed successfully.

Before/after comparison of 128 captured file records shows only the native
screen library changed. All head identities and loaded flags, H3 attachment,
nozzle settings and physical mapping are preserved. Klipper is Ready/standby,
all nozzle targets zero. The first-run marker was confirmed absent before the
normal navigation test. Local files opens and renders normally outside onboarding;
no file was selected or printed. No motion, heating or reset was commanded.

Evidence: `r104-onboarding-activation/`, `qualification-export-r104/` and
`qualification-install-r103/r104-{before,after}/` under the 8 November validation
directory. The intercepted onboarding branch has native lifecycle coverage;
actual first-run FINISH/reboot acceptance remains open. The following local
follow-up describes the discovery before this deployment.

### Onboarding completion bypass correction — local follow-up

Exact firmware tracing found that opening Local files removes `need_oobe`,
independently of the wizard FINISH callback. WM+ now redirects that navigation
back to its shared filament setup page while onboarding is active. Normal file
navigation before setup and after successful FINISH remains unchanged. Native
lifecycle and completion-durability checks pass (2 tests), including no completion
callback on the intercepted file route. See the current addendum in
[the stock caller audit](../upstream-client-callers.md).

The ARM build also passed. This fix is local, not yet deployed. Evidence is
`onboarding-file-navigation.xml` and the corresponding disassembly directory in
the 8 November validation folder. Read-only live navigation inspected Settings,
General and Other functions; no first-run marker, reset, loading or calibration
was invoked. Live onboarding FINISH/reboot acceptance remains open.

### Live combined interruption recovery — 8 November

A fresh export includes the staging-phase recovery fix. The normal installer ran
config → material → Moonraker → preload on the idle printer. After synchronous
remote preload publication completed, a one-shot qualification callback killed
the actual installer process with SIGKILL before it could restart the client.
The parent observed exit 137 and confirmed that installer PID 4076878 no longer
existed. No remote publisher was left running: its synchronous call had already
returned. The host journal retained the publication receipt and all three earlier
component receipts.

A fresh process ran the ordinary exported `recover all --journal ...` command.
It restored/checkpointed preload → Moonraker → material → config, restarted the
client and verified Klipper Ready. Journal `6c5818b3c09b4c9abd641b634104ea59` is
`restored`, with no inflight component or pending restart. All 128 captured file
records match the pre-test baseline. H3/H4 loaded flags and identities, H3
attachment, nozzle settings and mapping are unchanged. All nozzle targets are
zero and the printer is Ready/standby. No printing, motion or heating was issued.

This is live combined process-loss/recovery evidence for the installed version.
Config/material were already current (zero planned configuration changes); it
does not claim a clean-stock install or a downgrade between different backend
generations. File replacement/conflict behavior retains its separate isolated
process-death tests. Evidence: `qualification-combined-recovery/` and
`qualification-install-r103/combined-{before,after}/` under the 8 November
validation directory. The new export is `qualification-export-recovery-r103/`.

### Interrupted preload staging recovery — 8 November

A real subprocess killed with SIGKILL during its first source upload reproduced
an uncovered gap: the host journal had an inflight preload component without a
prepared receipt, so recovery could not undo earlier components. The installer
now saves a staging receipt before upload/compilation and durably changes its
phase to publication before dispatching installed-file writes.

Staging recovery requires the staging directory and absence of a publication
journal; it performs no service stop or preload restoration. Conflicting evidence,
unknown phases and missing publication journals for publication/legacy receipts
still refuse recovery. Thus the change does not reinterpret an ambiguous
publication as an untouched installation.

The real process-death regression now passes. The affected preload/restore/host
journal suites pass 80 tests, with additional staging-conflict and durable
publication-intent checks. Evidence: `staging-recovery-{before,after,guards}.xml`
and `staging-publication-intent.xml` in the 8 November validation directory.
All operations used disposable local files and modeled service ports. No printer
changes occurred; live combined interrupted-install qualification remains open.
The previously exported and installed r103 package predates this installer-only
fix; a fresh export is required to qualify the corrected recovery path.

### Exported installer upgrade/startup qualification — 8 November

The exported r103 package completed `install config material preload
--qualify-unreleased-screen` on the idle printer through the normal component
order and recovery journal. All preflight and post-restart backend protocol and
command checks passed. Journal `5b3af518301941c1851f13fd9a0c2b5e` is `applied`,
with config/material/Moonraker/preload completed and no inflight component.
Client PID 3813790 maps all six expected libraries; the native artifact matches
the sealed r103 package. Actual Settings → Filament navigation renders the WM+
external-head cards with H3 Sunlu pink and H4 Kexcelled blue-gray PLA Matte.

The two reviewed configuration changes add the managed runtime file and its
include before SAVE_CONFIG. They reconcile the rebased light/print-cleanup
behavior into the previously restored pre-LED printer configuration. The
calibration block, nozzle settings, head mapping, identities and loaded flags
are unchanged. H3 remains mounted; H1/H2 remain empty, H3/H4 loaded. All nozzle
targets are zero, Klipper Ready/standby. The before/after file comparison shows changes to existing files confined to
the reviewed include, preload drop-in and the added light preference in
saved_variables; new files are the runtime include and light
helper/library. Existing filament helpers and native screen bytes are unchanged.
No printing, commanded motion or heating was performed.

Evidence: `analysis/validation/2026-11-08-main-track/qualification-install-r103/`
contains the before/after snapshots, comparison, install log, applied journal and
rendered screenshots. `qualification-config-review/` contains the exact plan
and diffs. This closes actual exported **upgrade/startup** qualification. It is
not a clean stock installation or a combined interrupted-install recovery test;
those gates and package promotion remain open. Do not rerun this upgrade merely
to repeat its accepted assertions.

### Explicit unreleased installer qualification — 8 November

The exported current r103 candidate now supports the explicit development option
`--qualify-unreleased-screen`. Ordinary installation still refuses its
`packaging-control-only` descriptor. Qualification requires the current bundle,
exact vendor client, sealed artifact/source inputs and target loader dependencies;
it does not promote the descriptor. Backend/configuration and restart/readiness
checks remain in the installation path.

The affected delivery/deployment suites passed 153 tests. Seven qualification
checks then passed, including execution of the generated preflight with changed
source and propagation of loader failures; the updated export suite passed 20.
The exported installer passed actual printer preflight for config, material,
Moonraker and preload, including the exact 1.1.13 dependency check. The initial
attempt used an obsolete host Python environment and stopped without installation;
the successful attempt used Python 3.12 with Paramiko and Jinja2. No components
were installed and no services restarted in either attempt. Preflight reports two
configuration changes; inspect their exact preservation plan before installation.

Evidence under `analysis/validation/2026-11-08-main-track/`:
`qualification-export-r103/`, `qualification-preflight-r103-python312.log`, and
`qualification-{delivery,guards,export}.xml`. Actual clean-install startup and
combined recovery remain open; this closes the exported preflight/loader check,
not the entire delivery gate.

### Touchscreen manual extrusion dispatch — 8 November

H3 remained mounted with Sunlu pink PLA Matte loaded. It was parked at machine
X=-13/Y=80 with Z unchanged at 299.954063, then heated to 220 C. Actual touchscreen
taps selected 25 mm and pressed Extrude once, then selected 1 mm and pressed
Retract once and Extrude once. Controller extrusion positions read 0 → 25 → 24
→ 25 mm. XYZ, coordinate/extrusion modes, speed/flow factors, head offsets,
attachment and all loaded-filament records remained unchanged through the steps.
The touchscreen X control then set H3's target to zero; all nozzle targets were
verified zero. The printer remains idle with H3 mounted at the purge position.

This closes touchscreen distance/direction **dispatch**, not visual verification
of filament movement or physical touchscreen-finger responsiveness. Camera snapshots
confirmed head travel/position but did not resolve the gears or nozzle output.
The first synthetic Settings tap did not navigate; a second did. Initial backlight
state was not captured, so this cannot distinguish a wake-only tap from input loss.
Subsequent distance/action taps completed. Do not describe that first tap as a
proven new WM+ input defect.

The park-only test setup caught a vendor `RESTORE_GCODE_STATE` limitation: it left
the temporarily cleared homing offsets at zero. Motion had already reached the
correct purge coordinates with Z unchanged. The test stopped before heating,
read the actual state, and restored the original offsets explicitly with MOVE=0;
readback confirmed no physical motion. Production filament-service positioning
already explicitly restores head offsets, so no product code was changed for
this test-harness issue. Evidence: `touch-extrusion/park.json`,
`after-park-inspection.json`, `offset-restored.json`, heating/action snapshots,
controller state captures and `summary.json` in the 8 November validation directory.

### Toolhead transition status investigation — 8 November

r102 mounted-label readback now covers H1/H2/H4: each selected head showed
Mounted and Dock; H4 retained Kexcelled PLA Matte and Unload. Returned to H3.
The 70 recorded samples across those changes stayed Ready/standby, all heater
targets zero, with loaded records unchanged. Evidence: `r102-mounted-*.jsonl`,
`r102-mounted-h1.png`, `r102-mounted-h2.png`, `r102-mounted-h4.png`, and
`r102-mounted-summary.json` in the 8 November validation directory. This closes
label readback, not continuous motion/audio qualification.

The user reports frequent “Printer status unavailable” during those transitions.
Idle measurement of the screen's query shape returned 24 successful samples:
maximum discovery 115 ms, status query 487 ms, approximately 8.5 KB status.
This does not establish query timing during motion. Existing screen logs do not
identify status failure stages, so the exact live trigger remains unconfirmed.

A host regression reproduced one contributing defect: received status was not
published until command delivery returned. Publication now precedes command
waits; original receipt timestamps and two-second expiry remain enforced.
The failing-before/passing-after lifecycle evidence is in
`status-publication-before.xml` and `status-publication-after.xml` (the latter
also covers standalone delivery/readback). Bounded diagnostic counters now record
poll count, failure stage/time, last successful receipt, longest query, and
longest receipt gap. They do not alter freshness or command admission.
r103 deployed successfully with one UI-library replacement and 28 preserved
files; fresh backend session `b92e45caae7940be800a226884d34860`. Bambu Lab is
included in this build. Artifact SHA256:
`eebcc840441b4409e04b5d27c7513167256b8a76f4d7f35f09042a42dd67f0e4`.

Live diagnostics reproduced six new HTTP query-stage failures during H3→H2;
this is not fixed by the publication ordering change. An independent probe on
H2→H3 timed out after three seconds on status and discovery requests. Moonraker's
log reported 4.04 s and 4.96 s event-loop stalls with approximately 98–99% CPU.
A bounded non-blocking 25 Hz CPU profile during a second diagnostic transition
identified synchronous `_handle_directory_request` / `_list_directory` as the
dominant main-thread work (186 sampled stacks). A stationary isolation test of
one config-directory refresh took 1,248 ms and delayed a concurrent minimal
webhooks-status request to 1,297 ms, exceeding the screen's one-second HTTP
limit. The config directory contains 275 entries. This confirms directory
listing can cause the dropout independently of tool motion; the source of the
burst of listing requests is not yet identified. At that diagnostic stage, neither a Moonraker patch nor a longer
freshness timeout had been deployed. User has been asked whether a remote
configuration-file browser is open.

Evidence: `status-poll-motion-timing.jsonl`, `status-directory-isolation.jsonl`,
`status-server/moonraker.log`, `status-server/moonraker-motion.raw`, and
`r99-diagnostics/r103-*.log` in the 8 November validation directory. Both cold
round trips completed, returning to H3. No printing, heating, or extrusion was
performed; these targeted status/profiling checks do not reopen earlier cycle
counts or establish continuous motion/audio acceptance.

### Cooperative Moonraker directory listing — deployed, 8 November

The confirmed stall is corrected in the installed Moonraker file manager without
changing the screen's one-second request bound or two-second freshness gate.
HTTP directory enumeration now yields after each entry. The existing synchronous
`list_dir` and `_list_directory` callers retain their return behavior. File
metadata, reserved-path checks, symlink permissions, and error handling are
unchanged. `tools/moonraker_directory_patch.py` builds the patch only when all
five affected/coupled method fingerprints match the reviewed implementation; it
refuses unknown or already-patched methods and does not itself install anything.

`tests/test_moonraker_directory_patch.py` passes three tests containing 27
compatibility/cancellation cases, unknown-version refusal, and an independent
heartbeat proving that the HTTP handler services other tasks before enumeration
finishes. A first eight-entry chunk passed the single-directory test but failed
the four-request burst (full status up to 1,653 ms); it was superseded by
per-entry yielding. With the installed refinement, the same four simultaneous
config-directory requests returned all 275 files and **16/16 full UI status
queries completed below one second, maximum 581 ms**. This stationary workload
isolates the confirmed cause without repeating mechanical qualification.

Activation changed one Moonraker source file and restarted only Moonraker.
Klipper session `b92e45caae7940be800a226884d34860`, H3 attachment, heater-off state,
and loaded-filament records were preserved. Installed source SHA256:
`4ff76baf6e85e5e33dee26b6acc148472ef3036186b8c8c81295c084312ccbd7`.
Original source SHA256:
`a31117ad65e0f7833df573b3e566a7bb1650bd83e178fba70625e79e51688ace`.
Backup location on the printer:
`/home/t13dp/wmp/backups/moonraker-directory-20261108`.

Evidence under the 8 November validation directory:
`status-server/directory-patch-v2-tests.xml`,
`status-server/activation-v2/`, `status-server/durable-backup.json`, and
`status-directory-burst-v2.jsonl`. The patch builder and compatibility fixture
are tracked. The dedicated installer and managed backup adoption are now implemented
and tested (below), including integration with normal multi-component installation. The deployed native UI remains r103. No printing, heating,
extrusion, or additional motion was needed for these listing tests.


#### Managed directory patch installation and recovery

`tools/moonraker_directory_install.py` now provides prepare/install/restore/recover/status
entry points, backed by a durable original/candidate receipt and a service-operation
journal. The lock spans service stop, publication, startup, and readiness checks.
Source is published only after confirmed Moonraker stop. The adapter never restarts
Klipper; readiness requires the same Klipper process/session, attachment and loaded
filament records. A failed candidate startup restores the previous source. Interrupted
operations require explicit recovery; later source edits are preserved for inspection.

The focused patch/transaction/lifecycle/adapter suite passes 23 tests, including real
SIGKILL between source publication and checkpoint, live-lock exclusion, service-state
ordering, interrupted stop/publication/start, failed-start rollback, adoption integrity,
and refusal to overwrite concurrent edits. The export suite passes 19 tests, including
running the new entry point from an isolated export and source-binding its four modules.
These are host checks, not physical interruption qualification.

The current live patch was adopted using its exact original backup into
`/home/t13dp/wmp/backups/moonraker-directory-managed`. The installer ran successfully
on the printer with source unchanged and no service restart (already installed path).
It compiled the candidate with Moonraker's Python and verified Ready/idle and unchanged
Klipper identity/filament state. Evidence: `status-server/managed-adoption.json` under
the 8 November validation directory. The tools and their hashes are retained there.

Normal deployment now includes a `moonraker` component before unified screen activation.
Implicit selection checks the exact native client and skips legacy C screen profiles.
Host recovery receipts precede preparation/publication; recovery of a stopped Moonraker
does not depend on HTTP being available. Only after its locked service/state recovery
can earlier components be undone. A preexisting patch survives rollback of a later
installation, and uninstall leaves unmanaged legacy sources untouched.

The actual integrated component passed live verification, restore, and reinstall.
The original source was restored, then the per-entry-yield patch reinstalled using
`tools/deploy.py`. Both host installation journals reached `applied`; each service
operation reached `complete`. Klipper PID 3785117, session, attachment and loaded
records remained identical. The final installed hash is the accepted v2 hash above.
No Klipper restart, heating, motion or print occurred. Evidence:
`status-server/managed-restore.json`, `managed-reinstall.json`,
`managed-component-summary.json`, and copied `managed-host-journal-*.json`.

Component tests execute the real remote payload in fresh local processes against
disposable files (service I/O modeled). They cover clean installation, preexisting
patch preservation, lost SSH reply after publication, loss before backup preparation,
foreign receipts, unsupported source, and skipped legacy selections. Routing/journal
checks and export checks cover dependency ordering, HTTP-unavailable recovery,
blocking earlier undo when recovery fails, and source-bound component delivery.

The Moonraker component now also passed a real interrupted-installation check.
A one-shot qualification hook killed the remote installer with SIGKILL immediately
after confirmed Moonraker stop and before its next journal checkpoint. Inspection
confirmed the installer PID was gone, service state inactive/MainPID 0, original
source intact, and the host's prepared receipt retained. Normal `deploy.py recover
all --journal ...` succeeded despite HTTP initially being unavailable: service phase
became `recovered`, host journal became `restored`, and Klipper PID/session, attachment
and loaded records matched the saved baseline. A normal reinstall returned the patch
to its accepted v2 hash. No motion/heating/printing occurred during this test.
Evidence is in `status-server/interrupted-install/` plus
`managed-interruption-recovery.json` and `managed-interruption-reinstalled.json`.
The injection hook is qualification evidence, not a production feature. The recovery
message now accurately reports that Moonraker readiness was verified and does not
ask for an unnecessary Klipper restart.

Remaining: qualify the combined clean installation/loader and full-stack interrupted
installation/recovery path. The live component restore/reinstall is accepted; it does
not claim that whole-system gate. Usage: [directory patch installer](../moonraker-directory-patch.md).

### Work priority — 8 November

The separate LED session has finished. Main's light release is incorporated in
`feature/standalone-ui`; the printer was restored to r96 and subsequently received
the r98 XY-only backend/wipe correction. Old `/tmp/wmp-main-light` coordination
instructions no longer apply.

The diagnostic UI was rebuilt after rebase. A source-delta audit against deployed
r96 confirms its executable changes only add navigation request/page/time,
stale-status/unknown-owner refusal counts, and maximum refresh callback interval
and duration. These are diagnostic observations, not admission inputs or
input-reader timing. No GUI-thread I/O is added. Background logging is limited
to one record per five seconds, 60 initial records and up to 60 additional
navigation-triggered records. Host diagnostics/lifecycle checks passed before
rebase; the rebuilt candidate passes compilation.

The r99 scoped activation completed successfully; its journal is in
`analysis/unified-ui-native/activation-stockwidgets-r99/`; it updates one UI
library and preserves 28 files, including the r98 backend/wipe, loaded flags,
metadata and configuration. This is a controlled diagnostic deployment, not a
full rebased release installation or proof that missed taps are fixed. The full
new-main LED configuration remains absent from the test printer's restored
baseline. The user confirmed intermittent one-to-two-second tap unresponsiveness after
switching screens. The initial diagnostic samples contain no navigation requests
and therefore do not capture that report. A timestamped repeat on the now-active
diagnostic UI is requested. Automated navigation must not be substituted for
physical-touch acceptance. Startup refresh maxima observed so far (196 ms gap,
67 ms callback) do not establish the cause of the reported stall.

Follow-up on r99: the user subsequently reported a burst of taps working normally.
The retained `r99-diagnostics/post-successful-user-taps.log` records 113 navigation
requests, no stale/owner refusals, a maximum refresh gap of 234 ms and maximum
refresh duration of 154 ms. This is a successful observed session, not closure of
an intermittent report. No timestamped failed tap has yet been captured.

Exact-binary emulation (`tests/test_stock_touch_reader.py`, three passing cases;
`r99-diagnostics/vendor-reader.xml`) demonstrates that the stock 1.1.13 evdev
reader drains a queued press and release into a single released state. Separate
polls preserve both states; one or two complete taps queued before a poll are
lost. This establishes a vendor-reader failure mode, not its occurrence during
the user's reported stall. No global input patch or delayed tap replay has been
deployed; replay must not deliver old input to a newly displayed action.

Brand catalogue correction: Orca's custom-preset vendor list reserves/excludes
Bambu and Generic rather than being a complete list of all filament vendors.
Bambu Lab has now been added explicitly alongside Generic and WonderMaker.
This one-name correction is local and is not yet in deployed r102.

Brand catalogue follow-up: OrcaSlicer's 102 vendor names plus Generic and
WonderMaker are bundled from revision `f55615d7488fe570942f5e25548b8ab9b30778d0`.
Saved brands remain available; sorting ignores ASCII case, and case variants
are merged. Native selectors previously pinned Generic/current brand and limited
choices to 32; both paths now use the shared sorted choices without that cap.
r100 deployment completed with fresh Ready/standby and all 28 preserved files
unchanged; the installed UI hash is
`4897410b23501fa4c79b2b6e8ad5ce34582ac4c615d5c5bdf33701e541591fdb`.
It does not import profiles, rewrite saved identities or alter thermal settings.
A subsequent user request replaces the long dropdown with a dedicated brand
grid. The native lifecycle regression (`brand-grid.xml`) verifies all pages
through Zyltech, Previous/Next navigation, draft-only selection, retained controls
on telemetry sync, stale-selection refusal and Cancel back to the load editor
without discarding its state. At 670×340 content size the grid shows 12 brands
in three columns. r101 deployment completed with Ready/standby in a fresh session and all 28
preserved files unchanged. Its UI hash is
`fcae9e17c153a72eda0ac0a1dcf316ae397d76cac4dc9ab27427b6f2a9865537`.
The user confirmed concurrent touchscreen use explained the unexpected material
selector during the visual check. After handover, the grid rendered correctly
with 15 choices on the actual screen (`r101-brand-grid.png`), and both the grid
and parent editor were cancelled without saving. User feedback identified small
Brand field text, the unnecessary arrow, initial-page focus and selected-entry
appearance. The r102 follow-up matches Material's font and left alignment,
removes the arrow, opens the selected brand's page and fills its entry orange.
Targeted lifecycle coverage includes initial selection, orange background and
field alignment. r102 deployment completed with fresh Ready/standby and 28
preserved files unchanged. Live framebuffer checks (`r102-brand-field.png`,
`r102-brand-selected.png`) confirm the matching left-aligned field text, no arrow,
and automatic page 7/7 focus with Sunlu filled orange. Both dialogs were cancelled
without saving. Installed UI hash:
`328eb8c6e8f4890277d8d974a214c57016e695ed424c0d747c01417a9cedbc12`. No automated SAVE,
load/unload, heater or motion command was issued.

r96 compact status is deployed. The previous regular reply was 212,498 bytes:
143,702 bytes of full configuration and 61,986 bytes of saved variables accounted
for nearly all the excess. WM+ now publishes only four heater rows (min/max/
active nozzle diameter) and four physical mappings, and the native query omits
both bulk objects. These values remain current on each status query; no stale
configuration cache or guessed mapping was introduced. The legacy openACE
consumer uses the same response instead of an extra GET, including the full
set of prompt/manual-flow/discovery fields when openACE is present. On failure,
a queued legacy command is settled NotSent rather than held for reconnection.

The live regular reply is 7,167–7,169 bytes (96.6% smaller). Four-sample median
status time was 209 ms versus the prior 423 ms; this is a small diagnostic sample,
not a general latency guarantee. The removed openACE-only request previously
cost 243–309 ms even with no openACE installed. Object discovery remains a
separate roughly 5.7 KB GET; these are compact snapshots, not delta subscriptions.
Evidence: `r95-reconnect/payload-breakdown.json`, `exact-query-timing.json`,
`r96-query-timing.json`, `compact-shared-status.xml` (387 passing checks), and
`shared-status-unsent-{red,green}.xml` (new queued-command failure edge).
ARM build and packaging-control-only export passed. UI SHA256:
`970c2b24b7bcb11b44fbb37f6be86617e25344371530db567a99e8ec3b795789`;
backend SHA256 `a8e006d02ddbadea1b3945e10e28f4dbecad2712f6b709357ae269ad4e1e9070`.
Activation replaced only UI/backend and preserved 26 other files. Post-restart
readback preserved identities, loaded flags and the recovered result, with all
nozzle targets zero and standby (`r96-preservation.json`). No motion or heat was
commanded. This removes measured polling overhead; it does not establish the
cause or resolution of the earlier six-second reconnect delay.


r95 UI-only activation completed for the FINISH persistence fix. Idle preflight,
ARM loader checks and rollback preservation passed; only the touchscreen library
changed. The 27 preserved backend/configuration/state files matched their original
hashes. Post-restart checks confirm Ready/standby, all nozzle targets zero,
unchanged filament identities/loaded flags, and the retained recovered operation
bound to the new session. Home rendered successfully. No motion, heat, wizard
reset or Load/Unload was submitted. H3 remains mounted and unconfirmed/inserted;
axes remain unhomed. Evidence: `activation-stockwidgets-r95/`, `r95-state.json`,
`r95-preservation.json`, and `r95-home.png`. This is startup/preservation evidence,
not a claim of physical first-run wizard or power-cut qualification.


Deployed r94 durability follow-up: loaded-flag and hotend-material writers now fsync
the parent directory after atomic replacement, matching the operation journal.
Their old file-only fsync did not guarantee rename persistence across power loss.
**381 backend tests pass** (`filament-state-durability.xml`), including actual
file/rename/directory ordering and injected directory-fsync failures that prevent
filament dispatch. This is a targeted changed-state persistence check; no claim
of physical power-cut qualification is made. Idle deployment passed with only
`wm_material.py` changed and 27 other files, including the recovery journal,
preserved. A new Klipper session retained the recovered terminal operation,
all identities and loaded flags, with all heater targets zero. Opening Result
in the new UI runtime shows the same three completed recovery stages and the
present-but-unconfirmed message; it does not start another procedure. Evidence:
`r94-state.json`, `r94-preservation.json`, `r94-retained-result.png` and
`activation-stockwidgets-r94/activation.log`. H3 remains unloaded, H4 loaded,
axes unhomed. Insertion-wait cancellation is pending the user's confirmation
that H3's inlet has been physically cleared.


r93 journal installation coverage: `tests/test_material_install.py` now includes
`wmp_filament_operation.json` in preserved runtime state for install, upgrade,
rollback and lost-process recovery. Two added cases change the journal after
publication begins and verify that successful installation and failed-publication
rollback both retain the newer runtime record. **35 targeted tests pass**, zero
failures/skips (`r93-journal-install-preservation.xml`). No installer production
change, printer operation or restart was needed. This tests the new journal's
ownership/preservation, not unrelated stock installation behavior or a complete
clean-printer installation.


r93 changed-code live validation: H3 Load was interrupted by restarting Klipper
at the heating stage, observed at 31.76 C before any feed. The on-disk running
record was checked before restart. Startup restored the same operation ID as
unknown at heating in a new session, with target zero. The first Ready sample
was inside sensor settling and the test's immediate empty assertion failed;
subsequent readback of the same operation confirmed present-but-unloaded. No
sequence was resubmitted. The UI showed completed positioning gray, interrupted
heating orange with current/zero target, and future steps white.

RECOVER was then invoked once through the touchscreen. Its three numbered
stop/heater/sensor stages completed, leaving state failed/recovered (never a
successful Load), with “Stopped. Filament is present; complete Load before
printing.” Coordinates did not change during recovery; all heater targets remain
zero and all identities/loaded states are preserved. H3 is unloaded, H4 loaded;
homing was lost at restart. Evidence: `r93-interruption-live.jsonl`,
`r93-interruption-settled.json`, `r93-recovered-state.json`,
`r93-interruption-verification.json`, and `r93-recovery-{review,complete}.png`.
This covers the newly changed heating-stage process-restart/recovery path, not
power loss during extrusion, insertion-wait cancellation, or paused printing.


Interrupted-process fix (deployed r93): a host process-loss injection during
Unload reproduced loss of the volatile operation while the persisted loaded flag
remained true (`process-loss-unload-red.xml`). `wm_material.py` now writes an
atomic, fsynced `wmp_filament_operation.json` before dispatch and at changed stage
checkpoints. Startup restores unfinished records as unknown in the new session,
retains their original session, and strips old pause authority. It neither resumes
nor replays the sequence. Terminal results survive startup as well. Recovery
updates are persisted. A corrupt journal raises an explicit startup error instead
of silently authorizing service; this behavior needs operator-facing review.
Repeated unchanged wait checkpoints do not rewrite the file. openACE-owned
operations do not overwrite this standalone journal.

All **377 wm_material host tests pass**, zero skips/failures, including the new
process-loss, completed-result, write-failure, corrupt-record, pause-context and
unchanged-checkpoint cases. An explicit Unload now durably clears its loaded
confirmation immediately before withdrawal dispatch, while cancellation during
heating retains it. Load now confirms loaded only after purge/wipe/final checks,
so partial feed or purge cannot persist ready-to-print state. Recovery verifies
stopped/heater state without promoting sensor presence to loaded; its completion
message distinguishes retained loaded state, present-but-unconfirmed and empty.
Existing purge/wipe failure tests were updated from their old premature-loaded
expectation. New process-loss cases verify feed/purge remain unconfirmed across
restart. Existing recovery fault cases now restore the journal
before testing drain/heater/sensor refusal (`filament-journal-host.xml`). r93 deployment passed with a new Klipper session and three consecutive Ready
checks. It changed only `wm_material.py`, preserving 26 other tracked files.
Restart readback preserved all identities and loaded flags (H3 unloaded, H4
loaded); heater targets remain zero. Evidence: `r93-state.json`,
`r93-preservation.json`, and `activation-stockwidgets-r93/activation.log`.
The ARM build and matching `r93-delivery/` staging export passed; its scope is
still packaging-control-only. Live mid-operation process-loss validation remains open;
this is not a claim that F02 is complete. The existing r92 delivery artifact
predates this backend change and must not be represented as containing it.


Retest discipline: H3 load and unload already have successful runtime/UI evidence,
and the user has confirmed physical pink-filament release and subsequent
extrusion/wiping. Do not repeat these baseline operations merely because a broad
checklist item is unchecked. Before any repeat, identify the changed behavior,
failed assertion, or specific uncovered scenario; reuse accepted evidence for
unchanged behavior. The r92 full-unload repeat was started without establishing
such a reason and is redundant, not a newly discovered validation requirement.
It has now completed with the heater target zero, H3 marked unloaded, and
identities/other heads preserved (`r92-unload-summary.json`). H3 now requires
filament repositioning before a future Load; do not reload automatically.

User scope decision: physical USB G-code copy validation is deferred and does
not hold up the current completion track. USB profile importing remains deferred
separately. Keep existing USB behavior; neither deferral is a validation pass.

Installer readiness follow-up: `tools/components/preload.py::_restart` previously
treated a query exception, unknown/missing state, or unavailable initial baseline
as restart evidence. Five regression cases reproduced false success from the old
Ready backend. It now requires an observed startup/new PID, or a known initial
startup/error/shutdown state; observation failures only reset the consecutive
Ready counter. Invalid non-object responses are rejected as well. **90 targeted
readiness/restart/rollback/backend-acceptance tests pass**, with zero skips
(`preload-restart-evidence-{red,green}.xml`). This corrects the production
installer; it does not retroactively change the r92 development activation log.
A new hash-bound r92 staging export at `2026-11-08-main-track/r92-delivery/`
includes this fix and the deployed UI. Scope remains `packaging-control-only`;
G06 clean-install/live-recovery qualification and promotion remain open.
No printer restart or motion was performed for this installer correction.

r92 deployed follow-up: a fresh touchscreen runtime previously
offered Result only for its own in-memory receipt or a backend `unknown`
operation. It could not reopen a completed/cancelled backend result after client
restart. The native runtime now offers read-only terminal results for the selected
head in the current backend session. Fresh standalone status, matching head and
valid action are required; running operations are excluded. Viewing a terminal
result does not adopt a pending receipt or resubmit its command. The native
lifecycle regression passes complete/failed filament and toolhead cases, plus
wrong-head/stale/session/owner rejection (`r92-retained-result.xml`).
ARM build and source/artifact hash verification passed; SHA256
`4ed9a51b42c3c1b24a4e235dc9fe97953153a60857024f9735ab78bbba292668`
(`r92-build-manifest.json`). Idle deployment passed exact-file and target-loader
checks, published only the UI library, and preserved 26 other files. The native
client itself restarted Klipper after the touchscreen-only service restart:
Klipper PID/session changed and its terminal operation record was cleared. The
early deployment readiness receipt preceded this delayed startup restart; a
subsequent fresh readback and Home capture confirm final Ready/standby state.
All loaded flags and filament identities/revision survived; all heater targets
are zero. Homing/reference state is now invalid, so further physical validation
requires preparation. Evidence: `activation-stockwidgets-r92/activate.log`,
`r92-state.json`, `r92-preservation.json`, `r92-ready.png`.
Same-backend-session result restoration remains host-tested, not live-qualified
by this restart. Cross-Klipper-restart operation history is not implemented; do
not confuse preserved loaded state with preserved operation history.
The r91 export below predates
this source change and remains an r91 staging artifact.

Current r91 delivery reconciliation: **256 selected delivery/installer tests
passed, zero failed or skipped** (`r91-delivery-reconciliation.xml`). This is a
targeted regression run, not a new whole-repository result. The matching export
at `analysis/validation/2026-11-08-main-track/r91-delivery/` passes source/archive
binding verification: all 140 source inputs match the current worktree, and its
exported installer runs `list` independently. Evidence:
`r91-delivery-verification.json`. Artifact SHA256:
`1c1f3c8ceedc95892109c2d067ae120a19c40aa9baa0315f55639605eef62df3`.
The older 724-pass/34-failure whole-repository result below is historical; it is
not the current result for these selected suites. The export remains
**packaging-control-only**. Actual clean-printer loader/service installation and
release promotion remain unqualified under A02/G06. No printer operations were
performed for this reconciliation.

r91 bundles the remaining active-screen sync fixes: preview rows reconcile by
filament ID, the same pause prompt survives unavailable status with Load disabled,
and Home retains decorative objects. Focused native lifecycle checks and ARM
build passed; live Home/preview render checks passed. Parser results were not
requalified by this UI check. Pause runtime still needs paused-print validation.
Filament states/identities survived the idle restart. The development browser
preview now retains DOM controls; its focused host model passes. Legacy manual
overlay retention and held-click identity checks also pass. Deferred import and
the unused generic renderer remain follow-ups in the GUI sync audit.

GUI sync audit requested by the user: see [GUI data-sync lifetime audit](gui-sync-audit.md).
r90 fixes preview row recreation on freshness/editability changes. Native
regression failed before and passed after; ARM build and idle deployment passed.
All filament states/identities survived the restart, heaters remain off. The active preview-row, pause-prompt and Home findings were corrected in r91.
Deferred import and the unused generic renderer still have recreation paths
documented in that audit. Do not repeat unrelated acceptance tests for these
interaction-lifetime changes.

Deployed r89 adds persistent hotend-material history and generic-range Load
transition selection. Restart preservation passed for H3/H4 loaded identities;
all heaters remain off. Physical mixed-material transitions and disjoint-range
recipes remain open under G07. See the r89 deployment section below.

The matching r89 staging delivery now exports successfully with source binding.
52 delivery/material/combined-installer tests pass (`r89-delivery-history.xml`),
including the exported installer preserving `wmp_hotend_materials.json` alongside
spool identities and loaded flags. Package: `2026-11-08-main-track/r89-delivery/`.
It remains packaging-control-only: these isolated tests do not qualify actual
clean-printer loader/service startup or promote the release (G06).

r88 missing-usage follow-up: metadata projection now records whether per-tool
usage is available. Without it, preview asks for a source for every **preset**,
not every supposedly used filament. Once mapped, an informational notice retains
that uncertainty without blocking otherwise valid admission; errors take priority.
This does not infer missing weights or identify actual tool use from absent data.
Parser/controller checks and native lifecycle checks passed. The ready-state
notice regression initially used the always-unavailable backend stub; correcting
that test fixture yielded a pass (`r88-usage-ready.xml`). 33 package checks pass
(`r88-package.xml`). ARM artifact:
`b95a6e485949702f7d2e0adbae27c4f578867c96c75a6037da968f6fd991e5e9`.
Activation completed in Ready/standby, preserving 26 other files. Live missing-
usage preview shows the full new prompt and four preset rows without fabricated
usage (`r88-fixture-preview.png`). The comment-only fixture was cancelled,
hash-verified and removed (`r88-fixture-cleanup.json`). Identities/revision,
loaded states and print-submission record were preserved; all targets remain zero
(`r88-state.json`, `r88-preservation.json`). No printing, heating or motion occurred.
Missing data still cannot prove actual tool use; the screen now states that
limitation instead of labelling every preset as a known used filament.

Deployed r87 preview notice layout follow-up: use the full width below the
header instead of only the right column. This preserves mapping panel geometry
and scrolling while giving configuration-change and submission messages enough
space. Native lifecycle checks and 33 package checks passed
(`r87-preview-layout.xml`, `r87-package.xml`). ARM artifact SHA256:
`4609f44850c453aa93d8ef4259d7c7683a75a39361e8ade95d014c2116cd708d`.
Idle preflight passed with all targets zero and 26 non-UI files preserved;
activation completed in Ready/standby. Live normal and configuration-change
messages now fit fully without moving the image or mapping panel. Metadata,
revision, loaded flags, position, heater targets and print-submission record
were preserved after the guarded test change/restoration. Evidence:
`r87-train-preview.png`, `r87-warning-{invalidated,restored}.png`,
`r87-warning-invalidation.json`, `r87-state.json`, `r87-preservation.json`.
The specific configuration-warning clipping defect is closed; broader physical
layout/touch acceptance B03 remains open. No printing, heating or motion occurred.
The r86 delivery export below
is historical validation, not a package containing this later layout change.

Current r86 installer validation: exported the deployed candidate to
`/tmp/wmp-delivery-r86-validation`, verified all 140 source inputs against the
current worktree, and ran the exported installer's `list` command independently.
The export remains **packaging-control-only**, not release-qualified or activated
through the normal installer. The wrong cached client was rejected before export;
the matching 1.1.13 client passed. Evidence: `r86-delivery-verification.json`.
The four config/material/journal/combined-component suites pass **121 tests**
(`r86-installer-preservation.xml`), covering fresh/upgrade file preservation,
concurrent-edit refusal, rollback and interruption receipts. Services/SSH are
modeled in these tests; real clean installation, live interruption recovery and
release promotion remain open under G06. No printer changes or restarts were
performed for this installer validation.

Deployed r86 preview follow-up: live r85 showed PRINT white while admission was blocked.
The stock header caption has its own color, so disabling its parent did not gray
it. Preview control readiness now explicitly updates PRINT/CANCEL caption colors;
PRINT becomes gray both when unavailable and after submission is latched. A
native regression failed before the change and passed afterward, including
ready/disabled transitions and prevention of repeated dispatch. Shortened the
standalone tool-index warning to “Standalone: reslice using tools T0–T3.” so it
fits the preview notice. Controller, preview parser/admission and native lifecycle
checks pass (3 tests; `preview-disabled-red.xml`, `preview-disabled-green.xml`).
ARM build succeeded, SHA256
`5982f3f00a047618f21ea03900d2e8ad839a8c8c8d045b941e5426a9b16aef4b`.
All 33 package/identification/layout checks passed (`r86-package.xml`). UI-only
activation completed in Ready/standby, preserving 26 other files. Readback confirms
identical identities/revision and loaded flags, with all nozzle targets zero
(`r86-state.json`, `r86-preservation.json`). Live five-tool preview shows gray PRINT,
white CANCEL and the full untruncated warning (`r86-five-tool-preview.png`).
No PRINT tap, print submission, heating or motion was performed during this check.
The prior shared-model manual-confirmation route removal is included in r86.

Manual-confirmation follow-up: the installed native toolhead action handler only
opens Load/Unload procedures. Removed the remaining Check/confirm-loaded/empty
route from the alternate shared screen model, so it cannot reintroduce this
workflow. Backend debugging commands remain unchanged. The controller regression
checks that the old event IDs neither open a confirmation modal nor submit a
command, even when the capability is advertised (focused controller test passed).
This source cleanup is included in deployed r86. Corrected the
standalone filament-management document to distinguish presence from the
persistent loaded flag and AFC projection.

Inspected `r85-five-tool-preview.png`: the real five-used-tool cube now displays
PLA and gram usage and reports the standalone T0–T3 limitation before mapping.
The notice is ellipsized at the available width; this screenshot alone does not
prove disabled PRINT dispatch or the fifth row's complete usage display. Those
remain part of E02/E04 validation; no print was submitted by this check.

Deployed r85: reading existing Moonraker file metadata found a real
preview compatibility defect. `TFT Locomotive_PLA_3h35m.gcode` returns material
string `PLA;PLA;PLA;PLA`, array colors and usage, with only sliced IDs 1 and 2
used (50.42 g / 31.62 g). The old parser wrapped the whole string as one entry,
so the used rows became Unknown and could not match PLA sources. Other existing
Cube/Locomotive files use the same cache representation. Evidence:
`r84-file-inventory.json`, `r84-preview-metadata.json`.

The parser now accepts array or semicolon-string metadata, preserves empty
positions and enforces the same 32-entry/128-character bounds. A real-data
regression failed before and passed after (`r85-semicolon-red.xml`,
`r85-semicolon-green.xml`). Native lifecycle and sparse source-mapping checks
passed (2 tests, `r85-preview-regression.xml`); 33 package/identification/layout
checks passed (`r85-package.xml`). ARM build succeeded with SHA256
`dd2a5fdde23b65a9a4b3816ae4b7095ea1bcc1e895892a96686477593a8ccaae`.
Source hashes verified; UI-only deployment completed in Ready/standby and
preserved 26 other files. Identity/revision and loaded flags survived restart.
Live before/after acceptance on the same locomotive file now shows PLA on both
rows, 50.42 g and 31.62 g, correct black/blue swatches, and eligible loaded H4.
Selecting H4 for the first row then CANCEL preserved physical mapping, metadata,
loaded flags, operation/submission records, position and zero heater targets.
Evidence: `activation-stockwidgets-r85/`, `r84-locomotive-preview-before.png`,
`r85-train-*.png`, `r85-preservation.json`, `r85-preview-cancel-verification.json`.
No print was submitted. This validates the real sparse multicolor metadata path;
the broader E02/E03 fixture/admission gates remain open.

Deployed r84: procedure action captions now follow their enabled
state, using gray when unavailable and normal text when actionable. This fixes
the live H4 unload review showing white UNLOAD despite missing Z. The native
lifecycle regression failed before the change; lifecycle and procedure review
checks pass afterward (2 passed, `r84-disabled-header-green.xml`). ARM build
succeeded: `26b39507cee0c3a5f9ddc4982e9876b934a8ee023ae3a4534d7ee46f13fca1ff`.
32 packaging/identification/layout checks passed; one artifact check ran before
build completion and correctly rejected the stale manifest, then passed against
the finished build (`r84-package.xml`, `r84-artifact-recheck.xml`). Source and
artifact hashes are verified. UI-only activation completed in Ready/standby,
preserving 26 other files. Live review now shows gray UNLOAD and white CANCEL
when Z is unavailable; CANCEL returns to the overview. Filament identities,
revision and loaded states survived restart; all targets remain zero. Evidence:
`analysis/unified-ui-native/activation-stockwidgets-r84/`,
`r84-h4-unload-review.png`, `r84-h4-unload-cancelled.png`, `r84-state.json`,
`r84-preservation.json`. No physical unload was performed.

r83 activation completed, preserving all 26 non-UI files. Readback after the
Klipper/client restart confirms identical filament identities/revision and loaded
states (H1–H3 unloaded, H4 loaded), Ready/standby and all targets zero.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r83/`,
`r83-state.json`, `r83-restart-preservation.json`. Live stale-notice acceptance
has passed as recorded below; no motion or printing was performed during activation.

Deployed r83 follow-up:  live stale-draft validation on r82 passed.
With an unsaved eSun brand draft open on H3, a guarded remote color update
invalidated SAVE; tapping SAVE preserved the newer Sunlu/blue identity and its
revision. Cancel remained available. The original identity/revision was then
restored exactly (`r82-stale-validation.json`, `r82-stale-*.png/json`).
The disabled screen still said “Unsaved changes,” so the follow-up replaces
that notice with “Filament settings changed. Cancel and reopen.” when its
context is invalid, and “Printer status unavailable.” when disconnected.
The r82 stability observation completed; r83 activation completed in Ready/standby.
The native lifecycle test and 33 packaging/identification/layout checks pass;
ARM build succeeded (`r83-stale-notice.xml`, `r83-package.xml`).
Final r83 candidate SHA256:
`e753cbc93ef61cb6eb0a1159a671a384ddddcdb6c687732ffdde71483e6ddce5`.
ARM build succeeded; source/dependency hashes verified; 32 UI tests passed
(one real-loopback test excluded), and 33 packaging/identification/layout checks
passed (`r83-ui-regression.xml`, `r83-package-final.xml`). Deployment scripts
were prepared and passed live preflight; activation follows the completed r82 soak.

Local r83 preview follow-up: sparse multicolor fixture coverage now checks
original IDs 1 and 5, paired material/color/grams, invalid negative/string/bool/null
usage, and all-zero usage. The focused parser test passed. A further regression
showed standalone preview asked for mapping before revealing that its existing
submission contract only supports sliced T0–T3. Preview now reports that limitation
early and keeps PRINT unavailable; sparse T0–T3 and openACE higher indices remain
available. The new regression failed before the model change and passed afterward
(`r83-preview-admission-red.xml`, `r83-preview-admission-green.xml`). This does not
add higher-index standalone printing or qualify a real print. Rebuild and broader
UI checks passed as recorded above; r83 is now deployed.

Additional r82 no-print check: the existing Toys for Tots preview shows one
used PLA row and 49.31 g; its source picker dims H1–H3 and enables loaded H4.
Selecting H4 shows the centered two-line Head 4 / External caption and gray-blue
swatch. CANCEL returned to Local; readback confirms standby, no print submission,
unchanged identities/position and zero heater targets. Evidence: `r82-toys-*.png`
and `r82-preview-after-cancel.json`. This is one real-file E02/E03 path, not
acceptance of all malformed/sparse/multicolor fixtures or any print.

Deployed r82: confirmed the editor crash is repeated style
attachment, not evidence that selecting a particular material is invalid.
A new r81 crash during color Save/reopen produced a private core on the printer.
Only code addresses and numeric diagnostic fields were extracted; automatic
review rejected transfer of the full memory dump, and that transfer was not
attempted again. Temporary core settings were restored. The stack is
`StockAceFilaments::render_brand` → `lv_obj_add_style`, with PC `0x6aad88`.
The exact stock binary increments a six-bit style count without deduplicating;
the fault frame shows count **0** and copy index **4294967295**, confirming wrap.
Evidence: `r81-crash-addresses.json`, `r81-crash-symbols.json`,
`r81-crash-style-count.json` in the main-track validation directory.

r82 records each style/selector attached to a retained widget and attaches it
only once (including pressed button styles). A regression runs 128 editor
refreshes and asserts stable style counts; it failed on r81 and passes with the
fix (`r82-styles-red.xml`, `r82-styles-green.xml`). ARM build succeeded;
32 UI tests and 33 package/identification/layout checks passed. One real-loopback
test was excluded. Evidence: `r82-ui-regression.xml`, `r82-package.xml`.
UI-only activation completed in Ready/standby, preserving 26 other files.
Installed SHA256: `317ae4ec0d235cf0ef9e680e938117c3c5ce31de78e5fd668536c7e06ec91f05`.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r82/`.
Live color Save/reopen round trip passed on unloaded H3: pink → blue → pink,
with successful receipts, palette reopening, and backend readbacks. The complete
identity dictionary and revision match the original; loaded flags are preserved,
all extruder targets are zero, and the Klipper session stayed unchanged during
the round trip (`r82-colour-roundtrip.json`, `r82-colour-*.png`,
`r82-blue-state.json`, `r82-restored-state.json`). This validates the previously
crashing path after the counter-overflow fix. The 30-minute PID/RSS/status
observation completed: 91 samples over 1800.4 seconds, all Ready, one client PID
and one Klipper session. RSS increased from 23880 to 26604 KiB during navigation
and temperature tests; all targets ended at zero. Evidence: `r82-soak.jsonl`,
`r82-soak-summary.json`, periodic screenshots. This passes the process/session
observation only; real finger interaction and broader F04 acceptance remain open.
Live stale-draft refusal has also passed as recorded above.

The r81 material UI round trip PLA Matte → ABS Matte → PLA Matte passed with
backend readback and exact final identity/revision restoration. Color selection
and Save reached `#009cde`, but its UI receipt/reopen test crashed, so color UI
acceptance remains failed. Original Sunlu / PLA Matte / pink was restored by a
guarded idle, zero-target metadata command after recovery
(`r81-colour-crash-recovery.json`). No motion/heating/print was requested.

Deployed r81: register the slot mini-menu's deletion
callback, so entering the editor clears its retained pointer. Previously the
menu panel had no callback; after deletion, LVGL could reuse its address and a
later menu tap would hide an unrelated live object. A lifecycle regression
explicitly reuses that deleted address: it fails on r80 because the replacement
is hidden, and passes with the callback fix (`r81-menu-red.xml`,
`r81-menu-green.xml`). The ARM build succeeded; 32 UI tests passed (one loopback test excluded),
and 33 package/identification/layout checks passed (`r81-ui-regression.xml`,
`r81-package.xml`). Live acceptance and the separate crash investigation
remain open until tested; this is not a claim that both failures are resolved.

UI-only r81 activation completed in Ready/standby, preserving the other 26 files.
Installed SHA256: `8c610ce40c7546f2fe7c9967bddc48696ff070f138f825f721e58459b07179c1`.
Deployment evidence: `analysis/unified-ui-native/activation-stockwidgets-r81/`.

Live r81 acceptance for this reproduction passed eight Edit/Cancel cycles (two
passes across all four heads), with the same client PID throughout. All eight
overviews are byte-identical to the visually checked populated four-card frame;
the second pass of editor captures matches the individually inspected first
pass. Evidence: `r81-checked-repeat.json`, `r81-visual-repeat-verification.json`
and `r81-checked-*.png`. `r81-state-comparison.json` confirms preserved identities,
attachment and loaded states, with all four extruder targets zero. This closes
the reproduced stale-menu blank-pane defect, not the earlier material-dropdown
segmentation fault or the broader soak/metadata acceptance gates.

Current r80 fix: a failed filament render no longer leaves the attempted layout
cached as complete. An exception clears the layout cache, retains existing
widgets and restores the intended scroll for the next update. Fault injection
first failed with missing cards, then exposed lost scroll; the final native
lifecycle test verifies full cards and scroll recovery on the same snapshot.
This proves a recovery-path defect, not the root cause of the live segmentation
fault. B02/B03/F04 remain open for the intermittent crash/blank-pane incidents.
Focused validation: one native lifecycle test, two layout tests and 31 package
checks passed; ARM build succeeded. Evidence: `r80-render-retry.xml`,
`r80-render-layout.xml`, `r80-package.xml` in the 8 November main-track directory.
UI-only activation preserved 26 other files, and live editor Cancel returned
to a populated overview (`r80-cancel.png`). `r80-state.json` verifies Ready,
standby, unchanged metadata/nozzles/loaded states/attachment, and zero targets.
Installed UI SHA256: `db52d01225b15d49f9f9b9355e3d7397e508f9d3821a7e900157e7be8c689b61`.
Deployment: `analysis/unified-ui-native/activation-stockwidgets-r80/`.

Follow-up r80 validation: the UI suite passed **32 tests, 1 loopback test
excluded** (`r80-ui-regression.xml`). The first eight-cycle live editor test
**did not pass**: all editor/overview captures were already blank, although the
client PID stayed unchanged. Its `same_pid` values prove process survival only,
not successful navigation. Evidence: `r80-repeat-00..07-{editor,overview}.png`
and `r80-editor-repeat.json`. Do not count those as eight successful cycles.
A fresh capture confirmed the blank pane. Home → Filament restored the cards;
an individually observed Head 1 menu → Edit → Cancel returned correctly
(`r80-recovery-*.png`, `r80-single-*.png`). The blank-pane cause remains unresolved;
r80's exception-retry test does not establish that it fixes this live failure.

The guarded retry started from a visibly populated overview. Head 1 Edit/Cancel
passed; the following Head 2 menu/Edit sequence produced the identical blank
frame, so the script stopped immediately. Evidence: `r80-checked-repeat.json`
and `r80-checked-{00-editor,00-overview,01-editor}.png`. This narrows the next
investigation to switching source menus after an editor round trip; it does not
yet isolate whether the menu tap or Edit tap caused the blank view. No metadata,
heating, motion, or print command was submitted by these navigation tests.

User direction: finish the main filament/toolhead track first, then provide a
report of stock/factory screens needing changes and the concrete conflict with
WM+ if unchanged. Do not expand hidden factory calibration into the main track.
The broader stock-screen plan and unqualified checks remain recorded; they have
not been marked passed or deleted.

The recent local knife/Factory Mode hooks are removed from the active candidate.
Their full source, patch, built candidate and manifest are preserved under
`analysis/deferred/2026-11-08-factory-calibration/`. The running printer is
r82 (the prior fixes plus bounded style attachment described above). Probe-editor
refactoring was investigated but has not been implemented.

Current hardware authorization (8 November): user will be nearby and explicitly
cleared motion and extrusion tests at the purge position, but **no printing**.
Recheck live attachment, homing, operation/fault state before each physical step.
Real print acceptance remains pending separate authorization.

Main-track order: revalidate current standalone sources and installed contracts;
finish remaining no-motion screen/metadata/mapping checks; then attend Load,
Unload, Take/Dock, extrusion, paused replacement/runout and real mapped-print
checks. Keep clean-install/delivery qualification distinct from UI behavior.
The stock-screen conflict report follows this track and must distinguish actual
WM+ incompatibilities from pre-existing stock limitations and optional UX work.

### Main-track validation refresh — 8 November

Mapping-caption UI **r75**, SHA-256
`29e149f1fd61cafef2295e7829e942b703ecab7589fcd456cf772e0aa87f672d`.
The mapping button now fits its Head / External caption on two lines; the live
refreshed mapping view confirms the caption and per-source gram usage fit.
Evidence: `analysis/validation/2026-11-08-main-track/r75-caption-verified.png`
and `analysis/unified-ui-native/activation-stockwidgets-r75/journal.jsonl`.
Head 4 metadata was corrected to Kexcelled PLA Matte, retaining its saved color.
Its initial loaded flag was subsequently reconciled with the user's explicit
loaded observation, with idle/owner/sensor checks and atomic persistence. This is
a one-time test-state correction, not inference from sensor presence; H1–H3 flags
and all metadata were preserved (`h4-initial-loaded-correction.json`).

Operator confirmation is a development/recovery utility, **not a normal UI
workflow or completion gate**. The local r76 utility persistence change was not
deployed and is now archived under `analysis/deferred/2026-11-08-operator-confirmation/`;
the active helper source again matches the installed helper. Normal successful Load sets the persistent flag; successful
Unload or a clear sensor clears it. Sensor-present with a false flag means
inserted, not loaded. The earlier r74 regression evidence below remains historical
and does not certify the later local r76 change.

Physical validation resumed with the user's motion/extrusion authorization:
ordinary `G28` completed with Head 3 still attached, physical probe reference 2,
all axes homed, fault flag zero, ending at X150/Y135/Z7. A separate `G28 X Y`
completed with Z unchanged at 7 mm and the same head attached. The service-position
macro then reached X-13/Y80/Z12 with zero coordinate offsets. These checks validate
idle normal/XY homing and parking; they do **not** establish paused-print safety
or full Load/Unload acceptance. Evidence: `normal-home.jsonl`, `xy-home.jsonl`,
and `purge-position.jsonl` in the main-track validation directory. The parking
script's local summary formatter raised a KeyError after recording the successful
remote response and final state; the motion was not resubmitted.

Manual extrusion: Head 3 heated toward 220 °C, then
`WMP_EXTRUDER_STEP HEAD=2 MM=10` completed at the purge position. The final
heater target is zero, fault flag remains zero, and H3 remains marked loaded.
Evidence: `manual-extrusion.jsonl`. Camera evidence confirms parking but the
nozzle outlet is obscured; actual filament flow is **not visually confirmed**.
This does not pass the full load/purge/wipe or unload sequence gates.

H3 unload was subsequently exercised through the touchscreen. Confirmation
Cancel preserved XYZ/E, all heater targets, loaded state and the empty operation
record. A separately confirmed unload completed its four stages, switched its
target to zero and displayed “Filament unloaded. Please remove filament.”
The effective loaded flag is false **while the inlet sensor remains present**;
this condition no longer produces the old interrupted/failure result. The live
heating screenshot verifies gray completed / orange active / white future
numbered steps and current/target temperature; the final screenshot shows all
completed stages gray. Evidence: `unload-live.jsonl`, `unload-summary.json`,
`unload-confirm.png`, `unload-cancel-state.json`, `unload-heating.png` and
`unload-result.png`. This closes the H3 runtime/UI portions of D03/D04, not their
physical-release or close/reopen/error variants. User physical release check and
refeeding pink filament to the gears were requested for the full Load test.
Readback of the persisted JSON independently confirms H3's flag is false:
`unload-persisted-flags.json`. No restart was needed for this check.

Load cancellation also passed after an unsaved material change from PLA Matte to
ABS Matte: saved Sunlu PLA Matte/pink identity, completed-unload record, XYZ/E and
zero targets were unchanged (`load-unsaved-material.png`, `load-cancel-state.json`).
No actual Load was started while the physical refeed check was pending.

Cold-extrusion guard passed at the Klipper layer: the log explicitly reports
“Heat the selected nozzle before extruding or retracting”; XYZ/E, session and
target remained unchanged. The REST response itself failed: vendor Moonraker
copied the multiline macro error into the HTTP reason phrase and Tornado rejected
the newline. This is a command-response defect, not a printer disconnect. The
request was not repeated. Native transport now submits G-code once via the
installed `/server/jsonrpc` route and normalizes its bounded, ID-checked reply;
there is no REST fallback or automatic retry. A live harmless query and
invalid-head refusal both returned valid HTTP 200 JSON-RPC envelopes
(`rpc-live-probe.jsonl`). Three transport/standalone tests plus 31 ARM/package
checks pass (`r77-transport.xml`, `r77-arm-package.xml`), covering multiline error
bodies, wrong IDs, malformed errors and dropped responses with no retry.
The transport fix is deployed as **r77**, SHA-256
`5355191861ccd454a871f8f43cb8b46b5fa072cbaacb96a2a86e5ceab24c900d`.
Activation changed only the UI library and preserved 26 tracked files, including
metadata and loaded flags (`activation-stockwidgets-r77/journal.jsonl`). Restart
readback is ready/standby with H3 attached, all nozzle targets zero, H3 unloaded,
and its Sunlu PLA Matte identity retained (`r77-state.json`). Homing coordinates
are cleared by the restart; do not reuse the earlier physical position evidence
as authority for another motion command.
The deployed touchscreen's target-zero submission completed with “Heater target
confirmed” (`r77-zero-target-result.png`), exercising the new transport and
backend readback without heating or motion.

The inserted/unloaded wording discrepancy is corrected in deployed **r78**
(`0f20e53e8a3230b0b01b82184111ff0d252e566c1da41796f31a9643b4716234`).
Sensor-present with a false loaded flag now displays “Inserted”, retaining Load;
clear sensor displays “Empty”. Two native/projection regressions and 31 ARM/package
checks pass. Restart readback verifies H3 inserted/unloaded and the user-confirmed
H4 loaded, preserving Kexcelled PLA Matte metadata and color. Evidence:
`r78-state.json`, `r78-toolheads.png`, `r78-filaments.png`, `r78-label.xml`,
`r78-package.xml`, and the r78 activation journal. All nozzle targets are zero.

The rebuilt main candidate matches deployed r74 byte-for-byte
(`af74be596240fa5366d3a97ae537ecada22ff8540a6d301e1a8556f810e54445`);
no deployment or restart was needed. Current standalone backend, nozzle,
UI, layout, runout, pause/cancel, print-recovery and macro regression suites pass:
**802 tests**, plus the separately permitted **one local-loopback transport test**.
No skips are counted as passes. Evidence and source binding:
`analysis/validation/2026-11-08-main-track/result.json`, `regression.xml`,
`loopback.xml`.

Live no-motion checks repeated on r74: four equal external cards in head order;
empty H1/H2/H4 offer Load; H3 pink Sunlu PLA Matte remains loaded and its menu
offers Unload; Toolheads entry focuses mounted H3; brand/material are plain text;
Load/Unload and Take/Dock widths match and captions are centered. Temperature
input accepts 220 directly from its initial zero, and Cancel discards it.
Before/after audits show Ready/standby, all four heater targets zero, no filament
operation, unchanged Klipper session and unchanged loaded/metadata file hashes.
All five helpers and macro contracts match. This is targeted B01/B03/C01 UI
regression evidence, not full acceptance of those gates or physical operation.

The current Maintenance screenshot also verifies the visible stock
PROBE_CALIBRATE row below Feed & Discharge. It was not activated. Stock/factory
conflict analysis remains queued after the main track as requested.

### External card readability — deployed r79, 8 November

External cards now show brand and material on separate lines, replacing the
redundant lower head number. The live H4 card shows both Kexcelled and PLA Matte
without clipping; unloaded H1–H3 cards keep their empty swatch and Load action.
The source-bound ARM artifact is
`d430cbaace2313bb58e0ca64caba9a33defd2d6dd943ca0da36ed415de2d9286`.
One native lifecycle regression and 46 ARM/package/export checks pass, including
exported backend installer execution against a disposable stock home. These are
software/package checks, not a live clean-install pass. Evidence: `r79-card.xml`,
`r79-package.xml`, `r79-filaments.png`, `r79-state.json` and the r79 activation
journal. Only the UI library changed; the 26 preserved files include current
filament metadata and loaded flags. H4 remains loaded; H3 remains inserted but
unloaded. Heaters are off. Physical H3 release/refeed confirmation remains pending.

### Current regression and remote metadata acceptance — r79, 8 November

The current source-bound main regression run passes **803 tests**, with no
failures or skips: 802 main checks plus the separate real-socket transport check.
`r79-main-result.json` records the exact built source/runtime hashes and test
files; this supersedes the earlier r74 run for these software suites. It does not
replace physical or installation qualification.

Live B06 acceptance: AFC-compatible lane data contains exactly the four WM+
logical lanes mapped to physical heads. H3's present-but-unloaded sensor does not
publish a loaded spool; H4 publishes loaded Kexcelled PLA Matte / #7D8A92.
Remote brand, color, material and temperature-range commands updated H3 only,
persisted to disk, and were restored to its exact original Sunlu PLA Matte/pink
profile. Malformed color, inverted temperature range and unknown lane were
refused with no state change. All tests preserved XYZ/E, heater targets, loaded
flags and other heads' identities. Final remote publication matches the original,
with no publisher error or stale ACE lane records. Evidence: `r79-afc-readback.json`,
`r79-afc-range-roundtrip.jsonl`, `r79-afc-identity-roundtrip.jsonl`,
`r79-afc-invalid.jsonl`, and `r79-afc-final.json`.

### Previous progress snapshot — 7 November

**Core standalone screens and backend flows are implemented; release acceptance
is not complete.** Installed printer build: **r74**, including guarded transactional head identification in General/first-run setup, numbered setup progress, restart/startup exclusion, corrected live header placement and action styling, plus first-run command guards, backend-confirmed setup transitions, calibration failure latching and failure/stale status panels, physical PID selection, bed-calibration reference corrections, paused-filament invitation and delayed runout rechecks. Idle restart, active-hook readback, backend acceptance and Maintenance/Filament navigation passed; remaining stock-worker coverage and physical calibration/runout qualification remain open.
Counts below are release-gap categories, not a percentage of features or effort.
**1 of 6 named gaps is closed; 5 remain open.**

| Gap | Current state | What still closes it |
|---|---|---|
| G01 paused/runout | Paused Load/Unload, guarded Resume, native invitation and runout rechecks deployed in r69; offline tests pass | Live paused prompt and attended pause/runout/return-position qualification |
| G02 unhomed service | XY-only preparation and unknown-Z guidance implemented; idle UI checked | Paused-state and physical preparation checks |
| G03 first-run | Shared filament entry/Finish hooks plus r72 checkpoint/error handling deployed | First-run navigation, completion persistence/reboot and attended loading |
| G04 diagnostics | **Closed**; About entry and read-only diagnostics live-checked | Retain regression coverage |
| G05 stock callers | r74 identification lifecycle and screen replacement deployed; exact hooks, idle navigation, backend admission and restart preservation checked; recent local factory work archived separately | Stock-screen conflict report after the main track; existing stock integration/physical qualification remains unpassed |
| G06 delivery | Receipted config/helper/preload recovery and restart checks pass locally; touchscreen upgrade and late-failure rollback passed live; local recovery CLI now handles prepared config/helper/touchscreen/preload receipts and checkpoints the final restart | Live interruption/restart and clean-install qualification, missing-journal resolution, and qualified package promotion |

Recent progress: r67 removed the old Maintenance filament screen; r68
now includes the calibration fixes for physical/logical head confusion, pre-change state
capture, stale Z saves, and the stock probe-calibration code path's logical-T0 prefix. Preparation
admission now precedes vendor commands. Software evidence includes 248 macro/
recovery tests on the initial calibration correction, 91 focused calibration
tests on subsequent save changes, and 57 recovery plus two native tests on the
probe-entry correction. These runs overlap and are **not additive**. See the
individual source-hashed evidence below; none proves physical calibration.

The final-build acceptance matrix A–H remains open where it needs a final-build
repeat or attended operation. Existing live passes are listed as evidence, not
lost or counted as unimplemented. Profile importing remains explicitly deferred.

### r73/r74 activation and live idle review — deployed

The idle/cold activation changed the UI library and three backend helper files,
including the newly installed identification module. All 23 other tracked files
were preserved, including head UUID configurations, calibration and filament
records. Klipper returned Ready in about 44 seconds. Readback verified all eight
reviewed UI hooks and all five helper hashes; identification protocol 1 reported
idle with no failure.

The first live screen review caught a duplicated header and dark action text.
The r74 UI-only correction adjusts the panel for its parent offset and explicitly
styles centered uppercase BACK/START captions. Its native regression and 17
ARM-entry checks passed. Deployment preserved all 26 other tracked files and
returned Ready again. A second live visit showed one readable header; BACK
returned to General, and Filament/Toolheads navigation retained mounted H3,
Sunlu PLA Matte pink, Loaded state and 0.4 mm hardened-steel nozzle details.

Current installed UI SHA256:
`af74be596240fa5366d3a97ae537ecada22ff8540a6d301e1a8556f810e54445`.
Current material helper SHA256:
`e1337d7cedf214eed49af0e8e9ffa922b3403c6b4dd0f87e8d7e32b37f4be73d`.
Current recovery helper SHA256:
`a7120aa97bb50c5901c45204a33ba561ec897116e4b5c3e3c8aa7a8b8b9dfd1b`.
Identification helper SHA256:
`857b19dac9444c0440aedf702635becb19c06f4170d5f1da77106d5b48bdb7b9`.

Final audit: Ready/standby, all nozzle targets zero, no filament operation,
identification idle, no macro-contract mismatches, both persisted filament hashes
unchanged. No START, calibration, motion or heating control was used. The printer
was left on Toolheads with H3 selected. First-run and physical identification,
calibration, paused/runout and clean-install release qualification remain open.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r73/` and
`analysis/unified-ui-native/activation-stockwidgets-r74/`, including exact
preconditions, backups, publication journal, live hook/hash reports and screenshots.

### Identification restart/admission review — local, not installed

Identification now requires the virtual SD worker to report both inactive and
not executing an SD command; absent/unknown SD status and print error state block
admission. The paused filament editor explicitly checks the identification lock
before considering its pause token, closing that alternate admission path.

At `klippy:ready`, the recovery helper inspects identification journals and the
saved setup-mode flag. An interrupted publication, malformed/linked journal or
unresolved setup mode surfaces a failed identification status and blocks managed
operations/calibration. Startup does not move, rewrite files, roll back or resume.
Tests interrupt real transaction writes, construct a fresh adapter and verify
that it blocks without changing files. Explicit rollback followed by a new
session restores admission; the old failed session remains latched. A committed
mapping starts idle in a new session without rerunning identification.

All 469 backend/session/recovery/material cases passed. The ready-event binding
was then exercised through the actual registered callback in the 18-case command
suite. All 53 ARM-entry/export/helper-install/preflight cases also passed.
The rebuilt candidate retains binary SHA256
`eb17d88ab82e9d720defadce1974343e360529632d31994b81c25961d80cf900`;
its manifest now binds the updated Python helpers.

Read-only live audit: Ready/standby, four nozzle targets zero, no filament
operation, no macro-contract mismatches and unchanged persisted filament hashes.
The expected material/recovery helper mismatches confirm those local changes are
not installed. Evidence: `analysis/validation/2026-11-07-identification-startup/`.
Next is guarded activation and idle layout verification, followed by attended
identification; the release gaps remain open.

### Identification exclusion and first-run entry — local, not installed

The first-run identification constructor at `0x50fb98` launches the same vendor
worker from `0x510040`; its refresh routine is separate from General's screen.
The candidate now replaces that constructor with the full-screen WM+ setup view
and retires its refresh routine. Both exact entry windows are profiled. There is
no automatic identification launch and no first-run BACK bypass. General's BACK
is hidden while an attempt is unresolved; navigation is blocked until the result
has been applied through the explicit restart path.

Backend changes reject WM+ filament service, tool actions/settings and print
submission after an identification attempt until restart. Calibration has its own
matching exclusion latch. Tests cover pending, running, complete and failed
identification states and verify that blocked calibration dispatches no commands.

Validation: 396 backend regression cases passed; seven native/projection cases
passed, followed by a focused lifecycle rerun after the hidden-BACK change; all
32 built-ARM/hook/export cases passed. Candidate SHA256:
`eb17d88ab82e9d720defadce1974343e360529632d31994b81c25961d80cf900`.
Evidence: `analysis/validation/2026-11-07-identification-exclusion/`; exact stock
constructor/refresh disassembly is in the stock-callers directory.

Not deployed. Before activation, finish the admission review (including virtual
SD activity), interrupted-publication behavior across restart and paused metadata
edit paths. Then verify live idle layout and attended physical identification.
These local checks do not close G03, G05 or G06.

### Identification screen replacement — local ARM candidate, not installed

Extruder Setup now overlays the vendor controls with a WM-style title/action row
and backend-confirmed numbered stages. Completed stages are gray, the current
stage orange and future stages white. START submits `_WMP_IDENTIFY_HEADS` once;
RESTART appears only after the backend confirms a committed mapping. Restart
requires fresh, idle admission and cannot be submitted twice. Disconnects never
claim completion; an unexpected Klipper session change latches an interruption.
The profiled vendor event and background worker are replaced with return-only
functions, so stale vendor controls cannot run their direct UUID writes.

Validation: 75 backend/session/transaction/recovery cases, seven native lifecycle
and projection cases, and 32 ARM-entry/delivery/export cases passed. The runs
cover stage colors, retained widgets, hidden/deleted-page taps, stale status,
restart during an active print, duplicate submissions, exact constructor entry
bytes, and return-only retired ARM functions. Exported installation includes and
checks all five helpers. These counts are separate runs, not a release percentage.

Candidate SHA256: `e9c9c6d905136a7543e04416058ed27d375d68c16946bb5c58d09bb3be4f81d5`.
Evidence: `analysis/validation/2026-11-07-identification-native/`.
Printer remains on r72. Before deployment, review operation exclusion while setup
is running or awaiting restart, first-run entry coverage, and live idle layout.
Physical identification and failure recovery still require attended validation.
G03/G05/G06 remain open.

### Identification command integration — local, not installed

`wmp_recovery` now registers `_WMP_IDENTIFY_HEADS` and exposes the sequence's
numbered stages, failure and restart-required result under `identification`.
Each Klipper lifetime accepts at most one attempt. Invalid head counts fail before
commands or UUID writes; setup does not restart Klipper automatically. The helper
is included in source binding, matching-backend activation checks, local/remote
syntax preflight and both recovery installation paths. Unified publication and
rollback now cover all five backend helper files.

Validation: 90 identification/recovery/helper-install cases passed, 101 current
package/preflight/configuration-preservation cases passed, and 18 binding/recovery
cases passed (overlapping runs, not additive). Evidence is in
`analysis/validation/2026-11-07-identification-command/`. The binding test invokes
the registered recovery handler and checks its published completion result.

The native Extruder Setup event/worker replacement and progress screen remain
unfinished. The current ARM candidate predates these sources and must be rebuilt;
exported installation has not been requalified. No deployment or hardware action
was performed. G03/G05/G06 remain open.

### Identification sensor adapter — local, not installed

The new `KlipperObservation` adapter reads dock presence, hall/lock agreement,
physical tool-change success, homing state, setup mode, fault and recovery state
from Klipper. Missing sensor or flag values remain unknown; invalid hall values
cannot imply a released carriage. Active or unresolved filament/tool operations,
calibration and openACE ownership block admission. The backend command integration is described above; the existing stock setup
worker must still be replaced before this protection is available on the printer.

All 57 focused observation, session, transaction and exact-stock-worker tests
passed on 7 November. These include 15 new adapter cases; the other 42 are the
existing sequence, UUID publication/recovery and ARM characterization cases.
No printer commands or deployment were performed. G05 remains open.

### Configuration preservation follow-up — local, not installed

`tools/reconcile_screen_config.py` plans a managed behavior include instead of
replacing printer-owned configuration. Tests using the exact vendor parser retain
custom pins, tuning, custom macros, material settings, saved calibration, and
filament JSON files. Publication keeps backups and a journal, checks reviewed
contents and wildcard-include membership, and restores previous files on write
failure, including a successful rename followed by an error. Rollback refuses to
overwrite concurrent operator edits and records that inspection is needed.

The initial 19 reconciliation cases and 52 delivery/export cases passed together
(71 total). The subsequent installer integration passes 115 combined cases,
including isolated execution of the actual generated remote scripts and routing
through the unified package's config component. Planning validates source binding,
runs remotely without installed-file writes, and retains the reviewed plan for
publication. Installation rechecks source binding and publishes that plan instead
of invoking bulk config upload. Unified packages reject HTTP-only/file-selection
options that would bypass preservation; historical packages retain their existing
path. Reconciliation code is included in the source-bound export.

Evidence: `analysis/validation/2026-11-07-config-reconciliation/` and
`analysis/validation/2026-11-07-config-integration/`. The tests do not qualify a
complete remote component installation, service restart, or whole-install rollback.
The next integration run passes 134 combined cases. Unified config installation
now stages all four required helpers first, even when `material` is not separately
selected. Helper writes and backups have readback checks. Configuration publication
returns an explicit outcome: confirmed rollback restores helpers, while a lost
reply or unconfirmed rollback retains matching new helpers and stops without a
restart. Helper rollback handles committed renames with lost replies and refuses
to overwrite concurrent edits while restoring other unchanged destinations.

The exported-code test now runs config planning/publication and helper installation
together over disposable stock files, with real source binding, preserved custom
settings and filament records, and an idempotent repeat. It does not simulate the
SSH daemon, Klipper loading, touchscreen services or physical hardware. Evidence:
`analysis/validation/2026-11-07-helper-integration/`. The package remains
packaging-control-only. No printer files or services changed.

Live follow-up: the first read-only planner run exposed the vendor `timelapse.cfg`
symlink outside the config directory. Read-only included dependencies now retain
their resolved targets and content hashes; publication rejects a changed target,
even with identical contents. Writable `printer.cfg` and managed-file destinations
still reject symlinks. A regression case covers the vendor layout. The combined
suite now passes 135 cases.

The corrected planner ran on the real printer's Python, inspected 24 included
files and proposed **zero changes** to installed r72. A subsequent read-only audit
found all four helper hashes matching, no managed macro mismatches, Ready/standby,
all nozzle targets zero, no filament operation or active calibration, and the
same calibration session and both filament JSON hashes as the r72 activation.
Evidence: `analysis/validation/2026-11-07-live-config-plan/`. This qualifies planning
against the live configuration layout, not live publication or clean installation.

### First-run calibration follow-up — deployed r72

Local follow-up, not deployed: the verified Extruder Setup sender return address
`0x51095c` now selects physical T0–T3 through `_WMP_CALIBRATION_TOOL`. Its call
window is added to the exact-binary profile. Ordinary slicer commands and the
setup worker's other commands remain unchanged. The host routing test covers
all four indices, malformed selections and neighboring/unrelated callers; the
backend model covers duplicate/non-identity mappings with identification active.
The updated maintenance model selection passes 19 cases; 78 ARM routing,
calibration-worker and delivery cases pass. The ARM candidate builds as SHA256
`2b5e2ccafd277c5196b490824e4b9be51bb25c0b5edb7dbd713a261109c6b52d`.
These test runs overlap prior coverage and are not additive. The printer remains
on r72: setup's admission, direct UUID writes and restart/failure lifecycle still
need qualification. Evidence: `analysis/validation/2026-11-07-identification-selection/`.

The subsequent exact ARM characterization confirms that setup's wait clears an
early pickup error, and that a final docking error does not prevent the UUID
publication branch. Eight characterization tests pass; these demonstrate existing
defects rather than acceptance. Setup needs durable operation failure tracking and
guarded UUID publication before its local selection correction is deployed.
Evidence: `analysis/validation/2026-11-07-identification-lifecycle/`.

Local UUID transaction foundation: `klipper_extras/wmp_identification.py` stages
a complete permutation of the known connected UUID set without changing files.
Commit requires all heads and final docking confirmation, preserves non-UUID
bytes, checks source contents and readback, and journals writes with rollback.
Failures remain latched. Interrupted journals block a new setup; explicit recovery
restores only known transaction bytes and refuses to overwrite operator edits.
The 18 transaction/recovery cases and eight exact-vendor characterization cases
pass together (26). This module is **not yet connected to the setup worker or
included as an installed helper**. Admission, command acknowledgement, stage UI,
and runtime/package integration remain required; no hardware validation is claimed.
Evidence: `analysis/validation/2026-11-07-identification-transaction/`.

The local `IdentificationSession` now connects staged pickup observations to that
transaction: it admits only ready/idle, fault-free state with known sensors and
all heads docked, verifies homing if needed, performs physical selection, requires
exactly one observed undocked identity and a successful tool-change result, verifies
final docking, clears setup mode and commits. It reports numbered stages and
retains the failed stage. Failures issue no retry motion or restart; failure to
clear identification mode invokes the supplied shutdown callback. A pause arriving
during a stage prevents subsequent motion. Forty-two sequence, transaction and
exact-vendor characterization tests pass with hardware execution modeled.
The session consumes an explicit backend observation/execution interface; the
Klipper adapter, native UI replacement, helper packaging and attended validation
are still required. It is not deployed. Evidence:
`analysis/validation/2026-11-07-identification-session/`.

The exact 1.1.13 binary audit found four separate first-run workers for bed
leveling, vibration compensation, PID and tool offsets. Their 16 command sends
bypassed the Maintenance-only r71 guard. r72 wraps all 32 audited sends
in the backend failure latch and corrects the second PID loop to select physical
heads. Added call sites are bound to exact-binary profile windows.

First-run transitions now request a uniquely tagged `M400` through the same
stock command transport. The recovery helper publishes `calibration_checkpoint`
only after execution and post-command checks succeed. Navigation waits for a
fresh, matching acknowledgement; old values, missing backend support, busy
status, duplicate requests and a restart during the checkpoint cannot advance
setup. This includes the stock filament-guide constructor/event fallback and
calibration-finish route. A failed first-run flow retains a full-page error and
requires restarting the printer; it cannot expose the Maintenance BACK route or
mark setup complete. Finish independently rejects missing calibration status,
active calibration and failed/unconfirmed continuation. Installation acceptance
now requires the checkpoint status field.

The 108 focused backend, worker, transition-policy, installer, projection and
native UI cases pass. This is software evidence, not physical calibration or
first-run/reboot acceptance. The ARM build passed, as did 43 PID/ARM-wrapper and delivery checks and a final
two-case native rerun after the sender-exception handling change. These overlap
the 108-case run; they are not additional unique feature checks. Evidence is
recorded separately. Files:
`analysis/validation/2026-11-07-stock-callers/guide-calibration-audit.json`,
`guide-calibration-checkpoint-tests.log`,
`guide-calibration-checkpoint-final-native.log`, and
`guide-calibration-checkpoint-build.log`.

G03 and G05 remain open for live first-run/failure-screen checks and attended
calibration. r72 activation passed with the printer idle/cold. The changed UI/helper pair
was read back, all four helper hashes match, active macro contracts match, and
all five audited hooks point into the loaded candidate. Both filament JSON
hashes are unchanged. Home → Settings → Filaments → Toolheads navigation
passed; Head 3 retained pink Sunlu PLA Matte and was selected automatically as
the mounted head. The printer returned ready/standby with heaters off.
No calibration or machine motion was initiated for this audit or these tests.
Activation evidence: `analysis/unified-ui-native/activation-stockwidgets-r72/`.

### Scope and completion rule

Primary release: all four physical heads with **openACE absent**, including clean
installation without openACE files, not merely temporarily disabled openACE.
Keep the stock Home / Files / Settings shell and unrelated stock features.
Profile import is explicitly deferred. Spoolman/profile synchronization is future
scope; replacement power-loss recovery UI remains deferred per S14. Existing
power-loss entry behavior still needs a regression check. ACE-specific acceptance
is a separate suite and is not a prerequisite for standalone completion.

Feature-complete requires closing the implementation gaps below or explicitly
agreeing a scope change. Fully validated additionally requires every applicable
acceptance box to pass on an identified build, with evidence and no unresolved
motion, ownership, state-loss, or duplicate-command defects. Any failure stays
open after a fix until the affected test is repeated on the updated build.

### Confirmed implementation gaps / unresolved plan coverage

- [x] **G07 — Material-transition Load temperature.** Local implementation now
  preserves previous hotend material history independently of spool metadata and
  loaded flags, uses generic old/new ranges, and handles unknown history and
  interrupted purges. Backend regression: 366 tests pass; native editor/projection:
  2 tests pass. Deployed r89; restart preserves all loaded flags and identities. Disjoint ranges still refuse
  automatic Load; physical high/low material transitions remain unqualified. See the pending transition contract in
  [standalone filament management](standalone-filament-management.md).
  User requested this after the successful r88 H3 same-PLA Load; that success
  does not qualify high-to-low or low-to-high temperature transitions.

  **Current evidence:** Current reconciliation (12 November): accepted for the changed range-selection/history contract using the D05 evidence map. Physical compatibility qualification for every material pair is not required; no universal purge-volume claim is made.

- [x] **G01 — Paused filament replacement and runout/tangle recovery (S04/S13).**
  Origin-bound paused Load/Unload and guarded Resume are deployed in r61,
  including the native editors/review and replacement of vendor Resume preparation.
  The native invitation and sensor rechecks are deployed in r69. Qualify the
  paused prompt and whole flow on this identified deployed build. Preserve the required physical tool/return position, avoid Z
  homing and duplicate purge. Legacy prompt retention alone is not completion.
  **Current evidence (12 November):** r191–r193 real runout and managed native invitation/Load/Resume; r195 exact XYZ/logical-E return and 1 mm continuation; r196 deployed tangle admission with actual-vendor queued-callback and Resume tests. Cross-head return and failure branches have execution-test coverage. These establish the supported standalone flow without a deliberate mechanical tangle or another stock recovery campaign.
- [x] **G02 — Startup/unhomed service UX (S05/S06).** XY-only preparation is
  implemented, but Load/Unload refuses unknown Z reference. Deployed UX now
  exposes this prerequisite before Load can save/dispatch: idle users are directed
  to home from XYZ with a clear bed; paused users are told to keep the print paused
  and not home Z over it. X/Y-only automatic preparation remains available with
  a valid Z reference. Host tests and the ARM build pass; r64 live validation confirms the idle
  warning and disabled LOAD before submission. Paused/physical checks remain;
  never silently add full homing to filament service.
  **Current evidence:** Current reconciliation (12 November): accepted; the unknown-Z prerequisite described above is historical and was removed. r110 automatic Load mounting and XY-only preparation reached insertion with Z unhomed, confirmed by the operator. See accepted D01. Filament service does not home Z.

- [x] **G03 — First-run filament entry points (S12).** Trace and qualify every
  stock onboarding filament action into the new flow before any legacy motion
  prefix. The r62+ deployed implementation replaces the guide page/constructor with shared
  filament cards and an explicit FINISH action, retires both old loading workers,
  and consumes the legacy guide event before its heater/queue side effects.
  **Current reconciliation (12 November):** the r197 joined native lifecycle
  test enters through the production bootstrap handler, waits for the matching
  M400 checkpoint, reaches the shared filament page, and completes FINISH through
  the real marker unlink/directory-fsync helper. Retired guide workers dispatch
  no loading commands. Stale/busy admission, failed persistence and single Home
  navigation are covered on this same path. Native
  presentation of the first-run filament page and FINISH control passed on
  13 November using the production layout with fixed sample data and disconnected
  actions on the printer. Do not repeat
  accepted shared Load/Unload, physical calibration, or a generic reboot for G03.
  Historical live-loading/reboot requests below are superseded by this scope.
  Focused 8 November audit found FINISH used an unflushed removal of
  `/home/t13dp/need_oobe`. The local follow-up removes the marker relative to an
  opened parent directory and fsyncs that directory before reporting completion.
  Missing markers still require a successful flush, so retry after a failed fsync
  cannot silently accept an undurable change. Open/unlink/fsync/close failures
  retain the existing retry message instead of navigating Home. Focused filesystem
  tests cover success, absent marker, invalid parent, marker-as-directory, injected
  I/O failures, interrupted fsync and retry after unlink. Existing runtime tests
  cover FINISH admission, callback failure and one-time successful navigation.
  This targets WM+'s replacement FINISH callback only; it does not qualify stock
  onboarding language/network steps or claim live first-run/reboot acceptance.
  Evidence: `setup-completion-durability.xml` (2 tests passed). ARM build passed,
  candidate SHA256 `d5979a54fb75feb474241d8a40a3713e9572c9a3f613298c554ad13759257c25`.
  `setup-completion-delivery/` passed packaging-control-only staging verification;
  this is not release promotion or a physical reboot test. Activation
  completed as r95; the changed callback is installed. Live first-run acceptance
  remains open; no wizard reset or filament operation was performed.
- [x] **G04 — Version/capability/diagnostics entry (S10).** Deployed and
  live-checked through r65. Stock About has a WM+ link; the read-only panel shows
  the matching source build ID, verified client, standalone owner/freshness,
  advertised capabilities and log guidance. Open/scroll/CLOSE preserve stock
  About. Print mapping is reported independently of file selection. Host tests
  cover stale data, both owners, unresolved layout and widget lifetime. This
  acceptance covers diagnostics, not the advertised hardware operations.
- [x] **G05 — Audit affected stock physical-head callers (S05/S11/S15).**
  Reconciled the named XYZ, calibration/cleanup, first-run, Nozzle Flow,
  identification/config-writer and restart/retry paths against current source
  and existing assertions on 12 November. The current evidence map is in
  [the non-filament audit](../upstream-command-nonfilament-review.md#current-caller-reconciliation--12-november-2026).
  All 32 profiled calibration sends enter managed admission; failure blocks later
  movement, heating, parking and save. Legacy filament service enters the managed
  flow, and identification/restart responsibilities are accounted for by R23–R26.
  This closes the caller reconciliation, not G03/R22/R24 live presentation or G06
  delivery qualification. No new physical calibration or untouched factory-screen
  validation is required. Historical requests for those checks are superseded.

- [x] **G06 — Release installer/source binding (A02).**
  **13 November final acceptance:** normal reviewed-delivery installation passed
  without the development qualification flag; see the final activation record.
  The following earlier reconciliation is superseded for remaining-work status.
  **13 November reconciliation:** r198 subsequently passed fresh native
  activation, including mapped artifact identity and current unified counters.
  Metadata-free live startup and selectors passed on 13 November; A02 is now
  accepted alongside the exported stock-home installation checks. Remaining:
  reviewed package export and normal installer activation after acceptance.
  Historical requirements below for a separate full-clean/factory target or
  another generic startup test are superseded; no factory reset is required.
  Historical implementation/evidence follows. Current package
  selection, source verification, helper/config compatibility gates and rollback
  are implemented. The r72 staging export now includes the installer entry points,
  component modules, config-sync utility, optional touchscreen payload and all C
  fixes. These inputs are hash-bound in the source manifest/archive. The export
  excludes credentials, machine-owned CAN configuration and openACE installation
  files. Isolated CLI/helper-install tests pass, including a clean stock home and
  update preservation of material settings and filament records (52 current
  delivery/export cases total; `2026-11-07-clean-delivery/tests.log`).
  This does not qualify a full clean installation: loader/service ports were not
  exercised by the clean-home helper test, and the staging package remains
  `packaging-control-only`. Normal activation remains blocked until promotion.
  **Configuration preservation implementation is now present:** the unified
  branch in `tools/components/config.py` requires its preservation preflight and
  publishes the managed include through `tools/reconcile_screen_config.py`,
  instead of bulk `config_sync.py` upload. Helper/config receipts and guarded
  rollback are implemented, with clean-home, custom-include, concurrent-edit and
  process-loss tests in `tests/test_screen_config_reconcile.py`. The older bulk
  upload concern remains relevant to the legacy branch, not this unified path.
  **12 November normal-preflight coverage:** 79 delivery/export/combined-install
  tests passed in 38.71 s. The exported normal preflight (without qualification
  mode) accepts an isolated reviewed descriptor and rejects changed backend
  source and unresolved loader dependencies. Only target `ldd -r` resolution is
  modeled; this is not live AArch64 activation or package promotion. Combined
  rollback fixtures now supply the current qualification flag and standalone
  owner query, and account for the skipped Moonraker receipt. Actual config,
  helper and touchscreen publication/undo still run against a disposable home,
  including preservation of concurrent operator edits. Moonraker patch service
  transactions were outside that combined fixture's original scope.
  **Follow-up:** expanded the combined fixture to include actual directory and
  HTTP-error patch publications and receipts. All eight clean/update and
  operator-edit combinations passed in 14.32 s. A final preload rejection rolls
  both Moonraker sources back before other component recovery; the simulated
  service is running afterward, operator edits remain intact, and Klipper is
  never restarted. Actual component payloads run in child interpreters against
  disposable files; remote paths and service I/O are modeled. This closes the
  combined-component omission, not real service startup qualification.
  **Native activation admission added, 12 November:** the installer previously
  accepted service/ backend readiness while reporting native hook application as
  unconfirmed. Current `tools/components/preload.py` additionally requires one
  running client with the reviewed executable hash and sealed library mapped by
  device/inode, plus a fresh process-specific diagnostic sample proving native
  bootstrap, GUI, worker and status synchronization. Observation is read-only,
  bounded to 45 seconds and sends no restart; failure enters existing publication
  rollback. 275 affected readiness/backend/screen/bundle/delivery cases passed in
  36.22 s, including actual local `/proc` map/inode/executable observation. This
  installer change is not yet qualified against a fresh printer activation.
  G06 stays open for the full normal-installer clean-install/service qualification
  and package promotion listed in the current gap table; do not equate the
  implemented preservation path with a qualified release installation.

### Runtime package contract — historical pre-r68 candidate

The shared runtime-input contract now binds ten required files, adding
`offset_calibrate.cfg`, `fz-wipe-nozzle.cfg` and `wmp_recovery.py` to the previous
manifest. Review packaging independently requires the complete set and rejects
changed bytes without replacing the prior export. Configuration baselines are
review inputs, **not an overwrite list** for printer-specific configuration.
The normal installer has not yet been switched to this package.

Validation: **23 package tests passed**, including omission of each required
file, changed calibration/wipe/recovery inputs, reproducible export and the
actual native manifest generator. ARM build and review export passed; UI SHA256
`3b155febb6074978ffaf86b300888c2c558d3f6b28b027963ccc3f1dccbdb1f6`.
Evidence: `analysis/validation/2026-11-07-delivery-contract/`. Not deployed.

### Local calibration mapping correction — after r67

The stock calibration macros mixed physical offset indices with remapped logical
tool/heater commands. A local correction now uses physical head selection and
explicit physical heaters throughout preparation, wipe/preheat, rapid-mode
shutdown, and XY/Z offset calibration. It adds per-head parameter validation
and idle-only admission to the per-head and all-head entry macros. This has not
been deployed or physically exercised. The final macro/recovery suite passed
**248 tests** (`2026-11-07-stock-callers/calibration-final-tests.log`). G05 remains open for exact worker
preparation, PID/bed-leveling branches and interrupted cleanup. See the current
calibration correction in the non-filament audit for scope and evidence. A local
follow-up moves Z-result admission into the post-probe nested macro so a
pre-tool-change snapshot cannot suppress a valid result; wrong-head/faulted
results are rejected before recording. The early rapid-mode save now preserves
existing Z (XY only); combined saves require a matching fresh Z result and
measured reference. **91 focused calibration tests passed** for the latest
local source (`calibration-save-tests.log`). These changes remain undeployed.

### Local Maintenance entry guard — after r67

START and PROBE_CALIBRATE now have a local native admission guard before their
vendor preparation commands: fresh known-owner idle status and no unresolved
operation. Navigation stays available; hidden/deleted callbacks are consumed.
Two focused native tests, the ARM build and nine review-package tests passed.
The local follow-up replaces the probe prefix with `_WMP_PROBE_CALIBRATE`,
which rejects busy/fault/recovery state and uses `G28 P0` to establish physical
Head 1 as the datum before manual probing. The recovery suite (57 tests), two
native tests, ARM build and nine package tests pass. This is not deployed; the
matching UI and backend macro must be installed together. See the current client-caller
audit and `maintenance-gate-*.log` evidence. G05 remains open.

### Paused-service implementation audit — 7 November

### Position-prerequisite follow-up — 7 November (after r61)

The candidate exposes `filament_position` for standalone ownership. The Load
editor disables submission and displays the backend prerequisite before saving
metadata or dispatching a procedure. Unload review retains the same prerequisite
through `procedure_errors` and refuses dispatch without a plan. Idle guidance
directs the user to XYZ homing with a clear bed; paused guidance explicitly says
to keep the print paused and not home Z over the print. With valid Z, X/Y-only
automatic preparation is unchanged. This does not qualify physical clearance.

Validation: **341 backend tests**, **68 focused backend/UI tests**, and **1
unload review test** passed (overlapping coverage, not additive). The ARM build
passed with UI SHA256
`773d2fbfb95671b0d3e45c1ea86a8bfabd4363a7b4b01078337c78abc8cb007a`.
Logs: `analysis/validation/2026-11-07-position-guidance/`. This candidate is not
yet deployed; r61 remains the installed version. G02 stays open for live review.

### First-run integration candidate — 7 November (after r61)

The shared-screen onboarding implementation passed **32 offline UI tests**, then
the native lifecycle test passed again with startup-before-status and post-Finish
navigation assertions. **9 review-package tests** passed. ARM candidate SHA256:
`8072ab7d8ba5e0d21881b101340f4e41f319f4cc6f6987e05d8a72ac7f73ee9e`.
The four replacement guide entry windows are included in the verified native
profile. Evidence: `analysis/validation/2026-11-07-first-run/`.
The candidate includes the position-prerequisite follow-up above; it is packaged
but not deployed. G03 remains open for live first-run entry/completion and an
attended Load through that entry. Installer/source binding is still G06.

### About diagnostics candidate — 7 November (after r61)

The native candidate preserves the stock About constructor and adds a WM+ entry
in its header. A read-only, scrollable panel reports a source-derived UI build ID,
the verified stock client version, current filament owner, status freshness,
advertised Load/Unload/Take-Dock/nozzle-edit/print-mapping support, deferred profile
import, and log collection guidance. Stale status reports unknown capabilities
and unavailable ownership. Stock firmware information remains on About. Backend
capability advertisement is explicitly distinguished from hardware validation.

All **32 offline UI tests** passed. The native lifecycle test passed again after
correcting text sizing: diagnostics retains content-driven label height inside
its scroll body; the fixed-size filament editor bounds its position warning to
the space below the fields. Tests cover hidden/deleted pages, Close retaining
stock content, stale capability text and updates without rebuilding widgets.
Evidence: `analysis/validation/2026-11-07-diagnostics/`. The read-only live status
check found ready/standby, no pause or active filament/toolhead operation, and all
heater targets zero. This does not establish live diagnostics layout; the changes
are not deployed. G04 remains open for that check.

Final diagnostics candidate: UI build ID `3a9b51933c1d721f`, ARM SHA256
`37f5cf64f1875100c5c02db238b4284748fd405075b84d6bf0b4cf6a8c506573`.
The build ID is embedded in the artifact and matches the manifest/source input
hash. The review package passed **9 checks**. The r62 activation harness publishes
only the UI and material helper; all other installed files are preservation
checks. A fresh idle/cold preflight is required before activation.

### r62 live activation and diagnostics layout finding

r62 activated successfully on the ready/standby, cold printer. Only the UI and
material helper changed; all 15 preserved files passed hash checks, including
printer configuration, calibration, macros, identities and loaded flags. The
Home display still shows H3 pink and other heads empty. Settings, General and
stock About navigation remain responsive. No motion or heating was commanded.

The WM+ About entry did **not** appear, so G04 is not accepted. A read-only
process-memory object tree established the cause: the About page has both a
full-page 800×425 sidebar wrapper and a 695×357 content panel. The constructor's
minimum-size match considered both eligible and returned without attaching.
The local follow-up excludes full-page-width wrappers and adds that hierarchy to
the native test, which passes. It is not yet rebuilt or deployed. Evidence: `activation-stockwidgets-r62/`
contains activation logs, screenshots and `about-tree.json`.

### r63 live follow-up — 7 November

UI-only r63 activated successfully, with all 16 preserved files unchanged and
printer ready/standby. UI SHA256:
`43cffeb85c49446f7dd5b5ecfa1b91d8fd0f76f2eb1272ae2d6f599353135397`;
build ID `f32e919fc212a2e6`. Nine package tests passed. Home still shows the
persisted pink H3 filament. No machine motion or heating was commanded.

The About entry is **still absent** on the actual screen. G04 is not accepted.
The live object tree confirms the correct inset panel is present after layout;
the next local correction resolves LVGL layout before selecting the content
panel at constructor return. The host fixture now models unresolved geometry.
That correction requires tests, a new build and another live verification.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r63/`.

### r64 live validation — 7 November

The About constructor now resolves LVGL layout before identifying the inset
panel. UI-only r64 activated successfully, preserving the other 16 tracked files.
UI SHA256 `6d3bfef0dce573b784dd7e6bad872b0a621756c60d4f2edc770c048aa1290393`;
build ID `aeb3753e72646b2a`. Nine package checks and the native lifecycle test pass.

Live checks passed: WM+ link visible on About; diagnostics opens with matching
build ID and standalone owner; body scroll reaches log guidance; CLOSE restores
stock About. The panel incorrectly reports Print mapping unavailable before a
file is selected. A local correction reads the owner-specific mapping protocol
instead of the file-preview action capability; standalone/openACE regression
assertions pass. G04 remains open until that correction is deployed and checked.

G02 idle UI check passed: opening Head 1 Load while Z reference is unknown shows
clear-bed/XYZ guidance, explicitly says filament service will not home Z, and
LOAD is disabled. CANCEL returns to the source cards. No load, motion, heating,
or metadata save was submitted. The paused case and physical clearance remain
unqualified. Screenshots and activation records:
`analysis/unified-ui-native/activation-stockwidgets-r64/`.

### r65 diagnostics acceptance — 7 November

UI-only r65 activated successfully; all other 16 tracked files were preserved.
UI SHA256 `494c42fd3ef2f96967a8d29975ce7a1fc6a9153369c5a4cd84263cb1644fe3ad`;
build ID `02862c26e0affa49`. The native lifecycle regression test and nine package
checks passed. Live About entry, opening, correct identity/capabilities (including
Print mapping before file selection), and CLOSE restoring stock About passed.
Scrolling was exercised on r64 with the unchanged layout. H3's loaded pink
filament persisted across the restart. No motion or heating was commanded.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r65/`.

### r66 Nozzle Flow integration — 7 November

UI-only r66 activated successfully on the idle/cold printer, preserving all 16
other tracked files. UI SHA256:
`e76f1ab665a6cb1ef3eadd697d308b902d740bb6e263224658314ab8f93fad0e`;
build ID `0449c7570c5257f4`. Full offline UI suite: 32 passed (loopback test
excluded); review package: nine passed. Native tests cover all eight per-head
service routes opening editor/review without submission, stale/no-replay state,
and hidden/deleted callback suppression.

The Nozzle Flow callback now intercepts Load/Unload before the old
status-check-disable prefix and routes through shared filament UI. Back remains
stock. Live legacy-button-to-new-dialog verification is pending; no physical
Load/Unload has been exercised. G05 remains open for this check and the other
stock callers. Evidence: `analysis/unified-ui-native/activation-stockwidgets-r66/`
and `analysis/validation/2026-11-07-stock-callers/`.

### r66 live service entry validation — 7 November

Maintenance → Feed & Discharge → H3 Unload opened the shared H3 review. CANCEL
returned to H3 tool controls. Before clicking, read-only process inspection
verified the live handler jump to the loaded replacement symbol. Comparison
of status and command history before/after showed no new G-code commands,
no operation, no position or status-check flag change, zero heater targets,
and matching filament-file hashes. This validates navigation, not unloading.

The old page still disabled Load according to vendor sensor logic, so the next
candidate routes Feed & Discharge directly to the shared filament cards. It
keeps the per-button interception as a fallback and does not redirect unrelated
calibration/nozzle-settings pages. Focused lifecycle/runtime tests passed (2);
ARM build and nine package checks passed. This became deployed r67; the live
entry validation below passed. UI SHA256
`b78e6a298d3c5468d49a335d17b796cc9dbda304290a8d7711d192b2af0b3180`
(build ID `f5e31ecc41d2f496`).
Evidence: `activation-stockwidgets-r66/service-navigation-verification.json`,
`live-service-hook.json`, and screenshots. G05 remains open.

### r67 live Maintenance navigation acceptance — 7 November

UI-only r67 activated successfully, preserving the other 16 tracked printer
files. General → Maintenance → Feed & Discharge now opens the shared filament
cards directly. H3 retained its pink Sunlu PLA Matte metadata; empty H1/H2/H4
showed Load. H1 Load opened the shared editor with the unknown-Z prerequisite
and disabled LOAD. CANCEL returned to the filament cards.

Before/after command history and status prove no new G-code command, no filament
operation, unchanged position and stock status-check flag, zero heater targets,
and unchanged persisted filament-file hashes. Evidence is under
`analysis/unified-ui-native/activation-stockwidgets-r67/`: `service-entry.png`,
`h1-load-editor.png`, `h1-load-cancelled.png`, `service-before.json`,
`service-after.json`, and `service-navigation-verification.json` (six checks true).
This accepts this Maintenance navigation path only. G05 remains open for the
remaining physical callers; actual loading/unloading and paused-service motion
still require attended validation.

### Earlier paused-service implementation history (before r62)

Installed sources were read back to
`analysis/validation/2026-11-07-pause-audit/`; active configuration confirms
`PAUSE` renames the native handler to `BASE_PAUSE` and `RESUME` to `BASE_RESUME`.
The installed vendor M25 only stops the SD worker; it never sets native
`pause_resume.is_paused`. The local pending change replaces that call with
`BASE_PAUSE`, preserving WM's separate `PAUSE` return-state snapshot. A repeated
pause is now a no-op, preventing replacement of the original return point,
temperature recipe and backup tool map with parked values. This is a prerequisite,
not completion of paused Load/Unload, and is not yet deployed.

The pending backend now captures the pause origin at the end of the macro:
Klipper session, exact live file object, physical head, deep copies of PAUSE and
PAUSEPARK, mapping backups and resume settings. It binds the byte position only
after the SD worker has fully stopped (an in-file PAUSE finishes its line after
the macro returns). Origin checks reject later drift. Fifteen focused tests pass;
the broader backend/macro run passes **429 tests**, and the earlier macro plus
print-recovery run passes **175 tests** (overlapping coverage, not additive). This
capture/check foundation is now connected locally to backend Load/Unload and
Resume admission. The native UI now has local paused-service admission and
origin-bound metadata requests; dedicated paused UI scenarios and live
qualification remain outstanding.

Backend integration (local, not deployed): plans include the captured pause origin;
service rechecks it after acquiring the G-code mutex and at stage boundaries.
Only the original mounted head is admitted. The original G-code offset is restored
after travel to purge; PAUSE and PAUSEPARK remain untouched. Successful Load marks
service ready only after purge, wipe and heater shutdown. Resume now has a guard
before heating and again after the temperature waits, rejects
unfinished/unloaded/wrong-head service, and skips
the redundant retract/wipe only when completed service reported its wipe. Three
simulated full-load tests cover success, purge failure and changed resume settings;
38 targeted admission/context tests pass. These do not prove physical motion or
all native touchscreen Resume entry points. No new printer motion was commanded.

Paused metadata edits (local, not deployed) require the captured pause token,
original attached head, and unloaded state. Delayed edits after cancellation,
changed jobs, missing/stale tokens, loaded/unknown heads, and unresolved service
are rejected before writing. Ordinary remote metadata commands remain idle-only.
The backend/macro regression run now passes **457 tests**, including ten scoped
paused-edit cases and the post-heating Resume guard ordering. This supersedes the
older overlapping counts above; it is not a hardware validation.

Dedicated native editor/review tests now pass for paused replacement metadata,
Load and Unload review, wrong-head refusal, stale origin/file position/session,
job cancellation, loaded-head refusal, unavailable status, and editor cancellation.
They exposed a gap in StockIdentityEdit: it relied on the broad revision to notice
pause changes. It now captures and compares the job and pause descriptor directly.
Evidence: `analysis/validation/2026-11-07-pause-audit/paused-ui-context-tests.log`.
These are host-side controller tests, not a touchscreen or physical print test.

The Resume caller audit found a remaining standalone preparation bypass:
`client-preload/openace-compat/wmp_openace_compat.c::resume_prepare` calls the
original vendor callback when openACE is absent. As documented in
`docs/upstream-client-callers.md`, that callback can home X/Y, select a tool and
rewrite mapping/backups before eventually issuing RESUME. Thus guarding only the
RESUME macro is insufficient. The unified standalone client must own this entry
before any vendor preparation; the automatic resume/runout callbacks also need
qualification. No candidate containing this incomplete path has been deployed.

The unified candidate now builds the compatibility hooks with
`WMP_UNIFIED_FILAMENT`: explicit screen Resume sends only RESUME, and the two
stock automatic recovery workers cannot substitute heads, purge, or auto-resume.
The legacy compatibility-only build retains its old behavior. Both modes are
compiled and exercised by ownership tests, including unavailable/openACE/absent
presence. Initial runout detection and pause callbacks are unchanged.
Standalone M24 while natively paused routes through RESUME; the final M24 after
CLEAR_PAUSE still follows normal SD/recovery dispatch without recursion. Resume
requires a fully stopped paused job, resolved operations, captured origin, original
head and loaded filament even if replacement service has not yet begun. A serviced
pause additionally requires completed Load/purge/wipe.

Validation: **520 backend/macro/power-loss-recovery/compatibility tests passed**;
a subsequent stricter runout/origin check passed **63 focused pause/resume tests**
(overlapping, not additive). Logs are in the pause-audit evidence directory.
All changes remain local; ARM rebuild, native event integration and physical
qualification are outstanding. Normal M24 startup and power-loss recovery passed
the regression suite. Low-level aliases such as BASE_RESUME/M9924 are not public
UI entry points and must not be used to bypass the guarded macros.

Current local candidate validation (r60, not deployed): the native lifecycle test
now opens the paused external-head Load editor and rejects a changed pause or an
idle transition while it remains open. The save-to-load continuation also binds
its original job and pause descriptor, so a delayed metadata-save completion
cannot start loading into a different print context. **32 native/UI tests passed**,
plus the separately permitted localhost transport test (**1 passed**) and review
package checks (**9 passed**). The complete ARM build succeeded:

- UI SHA256: `2357b4121ec2bcfdb57d013e0e0931d30594c5368cb444615e09dc624b71a2ce`
- Review archive SHA256: `8001d49e79960d85cb1e5c27e08e7e9c106604d455aa69b2ba193b5e6be329b2`

The manifest binds native inputs and runtime dependencies. This is a development
review package, not resolution of G06 or proof of physical paused-print recovery.
The actual delayed save-to-load runtime callback is now covered by the native
lifecycle harness: unchanged context creates exactly one Load receipt; cancellation,
a new pause, changed byte position/session, and missing identity readback create
no procedure or Load receipt. The test uses the production runtime callback and
backend admission with no worker dispatch or printer RPC. Native lifecycle passed
again; evidence is `r60-load-continuation-tests.log` in the pause-audit directory.

**r60 deployment attempt failed and rolled back.** Preflight passed against idle,
zero-target r59. The activation script then incorrectly staged repository
`printer.cfg`, which re-enabled the optional openACE include and omitted the
printer's SAVE_CONFIG calibration block. Readiness failed with "Cancellation
endpoint unavailable"; the activation journal reports all six changed files
restored and services left stopped. The exact printer configuration backup was
also restored explicitly. Recovery verifies every one of the 17 original file
hashes before restarting the known-good r59 client. Restoration completed:
Klipper ready/standby, all heater targets zero, openACE absent, and H3 Sunlu
PLA Matte pink metadata present. No motion was commanded.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r60/activate.log`
and `restore-verification.log`. Do not mark r60 deployed or accepted. Subsequent
staging must publish only UI/backend/macros and preserve printer.cfg, helper
configuration, change macros, calibration and filament JSON as untouched files.

**Corrected r61 activation succeeded** (same tested UI artifact as r60). The
three-file deployment publishes only UI/backend/macros; all 14 other recorded
files, including printer.cfg/SAVE_CONFIG, helper configuration, change macros,
filament metadata and loaded flags, passed exact hash preservation checks.
`activation-stockwidgets-r61/activate.log` records readiness and activation-complete.
Post-restart status confirms standalone ownership, ready/standby, zero nozzle/bed
targets, H3 attached and loaded with Sunlu PLA Matte `#f5b6cd`, and H1/H2/H4 empty
despite their sensors reporting present. No captured pause is correctly offered
while idle. The home screenshot renders normally with only H3's pink indicator.
No print, homing, heating, extrusion, Load/Unload or pause/resume motion test was
performed. G01 remains open for complete native prompt and attended qualification.

Post-deployment navigation initially appeared unresponsive because the evdev test
injector reused coordinates retained by the kernel across the client restart.
A reader captured tracking/BTN_TOUCH/SYN events with **no ABS_X/ABS_Y** for the
repeated tap. Changing both coordinates by one pixel immediately opened Settings.
`tools/u1_tap_remote.py` now primes both axes while released before each contact,
forcing coordinate events for a fresh reader. This was an injection defect, not
proof of a frozen screen. Corrected injection opened Filament: four equal external
cards, empty H1/H2/H4 with Load, and pink Sunlu PLA Matte H3 survived restart.
Screenshots are retained under `activation-stockwidgets-r61/after-*.png`.

Remaining G01 work: qualify the complete native Resume event path and verify
all stock/API/runout entry paths and user-facing replacement prompts;
verify cancellation and runout/reinsert timing; build/deploy the complete candidate
and qualify actual paused replacement with the user. Direct M25 alone is not a
complete WM pause. No new printer motion was commanded.
Installed filament sensors use delayed PAUSE and have automatic runout pause
disabled; insertion currently cancels the timer outside printing without moving.
These details require separate runout/reinsert timing tests.

Local source-picker header now uses the shared uppercase CANCEL action and rule
for both slot selection and ambiguous-route selection. UI lifecycle coverage
includes cancelling without modifying routes or sending a print request. Pending
native candidate has not replaced deployed r59 yet. ARM build, the UI lifecycle
test and all nine review-package tests pass. Pause-related physical behavior still
requires attended qualification.

### Stock-screen traceability

| Plan | Current disposition / acceptance gate |
|---|---|
| S01 Home | New shortcuts/indicators implemented; verify B01, B04 and C01. |
| S02 Files / USB / history | Retained browsing plus new preview/copy; verify E01–E04. |
| S03 Preview / mapping | Implemented; Superbird one-row/49.31 g confirmed; complete E02–E05. |
| S04 Active print controls | Stock controls retained; baseline E05, new paused workflow G01/F01. |
| S05 XYZ / homing / head actions | Implemented paths plus remaining caller audit G05; C01–C04. |
| S06 Filament / toolhead views | Implemented for idle standalone operation; B01–B05, D01–D05; G01/G02 remain. |
| S07 Editors / pickers | Built-in brands/materials and color editor implemented; B02/B03. |
| S08 Camera / video / timelapse | Unchanged stock behavior excluded; only a changed timelapse-option handoff belongs in E05. |
| S09 Wi-Fi / AP | Unchanged join/AP behavior excluded; WM+ connection/status handling remains F03. |
| S10 General settings | Unchanged settings excluded; new diagnostics link accepted under G04. |
| S11 Calibration / nozzle / self-check | Nozzle editor implemented B05; other stock callers G05/H04. |
| S12 First-run | Coverage not established; G03/H05. |
| S13 Runout / tangle / change prompts | Paused/recovery integration deployed; complete live paused/runout qualification remains G01/F01. |
| S14 Power-loss | Only changed recovery dependencies under H06; replacement UI deferred. |
| S15 Factory / topology / service | Only callers of changed commands under G05/H07; no factory requalification. |

### Evidence already established (not a blanket release pass)

- [x] r58 backend + UI suite: **315 passed**; package suite: **9 passed**;
  additional native stage-color/lifecycle regression passed.
- [x] r58 deployed and printer returned ready/standby.
- [x] Superbird live preview corrected from seven presets to one used PLA row,
  **49.31 g**, with CANCEL and centered source caption (r56 framebuffer evidence).
- [x] Head 3 metadata and loaded flag survived r57 and r58 restarts.
- [x] Earlier live identity/nozzle Save/Cancel/restart checks are recorded below.
  They do not substitute for the final-build regression matrix.

### Execution order and pass criteria

Run one attended physical operation at a time. For each item record build/hash,
mode, head/material, initial state, action, expected/actual result, screenshots,
operation ID/logs, and final sensor/heater state. Do not infer nozzle loading
from an inlet sensor or physical completion from HTTP acknowledgement. Do not
provoke a collision, hot USB/CAN reset, or mains cut just to test failure handling;
use simulated faults first and controlled idle disconnects where applicable.

**A — Establish the standalone baseline**

- [x] **A01** Record installed UI/backend/config hashes and backups; verify no
  openACE object, no active/paused job, known attachment, no unresolved operation.
  Passed on r79: activation `before-files.json`, verified backup bytes, `spec.json`
  and successful preservation journal; `r79-state.json` includes the object list
  confirming no openACE/AFC and ready/standby, attached H3, no unresolved operations.
- [x] **A02** Verify clean-install startup without openACE or its saved data;
  four physical heads, built-in catalogue and required helpers are available.
  Current evidence: the exported stock-home installation publishes all eight
  helpers and constructs the installed backend without legacy INI or saved
  filament data; all ready callbacks register successfully. On 13 November the
  real printer also started Ready with WM+ pointed at an empty metadata directory:
  four empty head cards, writable empty identities, built-in brand grid and
  materials (including PCTG/PA6/PA12/PP) were verified. Exact configuration,
  identities and loaded states were restored; all 20 inventoried files match.
  Startup is accepted from these complementary package/backend/live checks;
  normal release activation remains under G06. The live part used the installed
  runtime with isolated metadata, not a factory reinstall. See the dated result.
- [x] **A03** Confirm normal full homing uses the physically mounted head; after
  establishing valid Z, explicit XY homing leaves Z reference and Z motion alone.
  Passed on mounted H3, 8 November: `normal-home.jsonl` and `xy-home.jsonl`;
  live configuration hashes match the inspected XY-only macro, Z remains 7 mm,
  reference remains valid and no head-change fault is reported.

**B — Screens, editing and persistence (no motion required)**

- [x] **B01** Home shortcuts, Filaments/Toolheads navigation, mounted-head default,
  one open slot menu, focused head, equal-width external cards in head order;
  no redundant ACE filters in standalone. Verify all four heads.
  Live r79 navigation pass (8 November): Home filament shortcut opens the
  external overview; all four equal-width cards remain ordered H1–H4 without
  ACE/head filters. Sequentially opening H1/H2/H3/H4 menus leaves only the newest
  menu visible. Each Edit opens its corresponding physical-head title; custom
  H4 Kexcelled and H3 Sunlu metadata remain intact. H1–H3 menus offer Load and
  loaded H4 offers Unload. From H1's open menu, Toolheads focuses mounted H3;
  switching back returns to the overview. Both view-switch buttons occupy the
  bottom-right position. No settings, loaded flags, position or heaters changed.
  Evidence: `analysis/validation/2026-11-08-main-track/navigation-*.png`,
  `navigation-after.json` against `nozzle-three-after.json`. Internal focus
  callback/exclusive-menu assertions also exist in `native_lifecycle.cpp` and
  passed in the recorded r79 regression. Remaining Home head shortcuts passed:
  tapping either temperature or nozzle-info region on each of the four Home
  rows opens Toolheads with that physical head selected. Evidence:
  `home-shortcut-h[1-4].png`, `home-nozzle-shortcut-h[1-4].png` in the same
  directory. This closes the standalone filament/toolhead navigation gate;
  unrelated stock-feature checks remain in section H.
- [x] **B02** Brand/material list selection, color swatch/hex, Save/readback,
  Cancel/discard, stale draft refusal. Preserve custom existing brands/colors;
  empty cards show empty swatch and Load, not stale identity.
  Current follow-up: r81 fixed the retained mini-menu pointer and r82 fixed
  style-count overflow, with failing-then-passing regressions and live Save/reopen
  validation (see Work priority). Color round trip and stale draft refusal passed
  on r82. The earlier crash narrative below is historical; its two reproduced
  causes are fixed. Live r83 acceptance now shows “Filament settings changed.
  Cancel and reopen.” with SAVE disabled. Tapping SAVE leaves the newer remote
  identity/revision unchanged; CANCEL returns to the overview. The original
  identities/revision and loaded-state records were restored exactly; session
  and position stayed unchanged. Evidence: `r83-stale-validation.json`,
  `r83-stale-notice.png`, `r83-stale-save-refused.png`, `r83-stale-cancel.png`.
  Together with the recorded brand/material/color round trips and Cancel checks,
  this closes B02. Physical-touch, power-cycle and reliability gates stay separate.
  Live r79 brand Save round trip passed on unloaded H3: Sunlu → eSun → Sunlu
  through the touchscreen brand selector and SAVE, with successful UI receipts
  and backend readbacks. Only the selected brand changed; PLA Matte / pink,
  other heads (including custom Kexcelled on H4), loaded flags, attachment,
  position and heater targets were preserved. The final identity revision and
  complete metadata dictionary match the original. Evidence in
  `analysis/validation/2026-11-08-main-track/`: `identity-esun-complete.png`,
  `identity-esun-state.json`, `identity-restored-complete.png`, and
  `identity-restored-state.json` against `home-keypad-after.json`.
  Material/color Save round trips and live stale-draft refusal remain before
  closing the whole gate; earlier Cancel checks are recorded separately.
  **Open r79 failure, 8 November:** saving H3 material PLA Matte → ABS Matte
  succeeded (`material-abs-complete.png`, `material-abs-state.json`), but reopening
  the material dropdown was followed by a touchscreen segmentation fault.
  Service journal reports client PID 3459032 exited at printer-local
  14:46:34, followed by automatic client startup at 14:46:35. Klipper also
  restarted (new session in `material-restart-state.json`). No heating/motion
  was requested. Original H3 Sunlu / PLA Matte / #f5b6cd was restored through
  an idle, zero-target, expected-revision guarded metadata command and verified
  in `material-recovery.json`. `material-reopen-initializing.png` captures the
  visible restart. Treat material-selector stability as unresolved; do not
  close B02/B03/F04 based on earlier successful selector checks. A causal
  stack trace or reproducible trigger is still needed; dropdown reopening is
  the observed sequence, not yet a proven root cause.
  Follow-up: the same Save/reopen sequence after a fresh client did not crash
  (`repro-material-*.png`). A bounded repeat attempt instead produced a blank
  Filaments pane with the client PID unchanged; stopped after noticing this,
  so its cycle counters are not successful-operation evidence. Home → Filaments
  recovered the view without restart (`material-blank-pane.png`,
  `material-blank-pane-recovered.png`). A temporary private 512 MiB core limit
  produced no dump, and both the original kernel core pattern and process soft
  limit (zero) were restored. Original H3 metadata was restored and verified
  again (`material-repeat-recovery.json`). Both failures remain open; the
  shared cause, if any, is unproven. No speculative fix has been deployed.
- [x] **B03** Physical-touch pass: centered readable button text, uppercase short
  header actions, WM spacing, opaque modals, no clipping or under-panel bleed;
  popups remain usable during status refresh and repeated taps send once.
  **13 November acceptance:** user reported “No missed taps” in the requested
  quick navigation/selector check, closing the remaining physical-touch item.
  r91 injected-touch menu check passed: opening external H4's menu closes H3's
  menu and restores H3's card. Edit from that menu opens “External - Head 4”
  with Kexcelled / PLA Matte / #7D8A92. CANCEL returns to the overview without
  modifying identities, revision, loaded flags, operations, session, attachment,
  position or heater targets. Evidence: `r91-menu-{h3,h4,h4-editor,cancelled}.png`,
  `r91-menu-after.json`, `r91-menu-verification.json`. This verifies exclusive
  menus and action focus on the standalone screen; physical-finger and ACE-slot
  acceptance remain separate.
- [x] **B04** Loaded-state matrix: successful Load sets flag; Unload or real
  sensor-clear clears it; sensor-present alone does not load it; unknown sensor
  does not erase it. Verify loaded/present-unloaded/empty states across client
  restart, Klipper restart and controlled cold power cycle. Confirm metadata is
  retained independently and card/AFC publication agree with effective state.
  **Current evidence:** Reconciled 12 November: accepted. The r110 real clear/present test shows Inserted without Loaded; r110 completed Load and operator-confirmed cold boot preserve H3/H4 flags and metadata. r174 reboot and r177 interruption add later preservation evidence. `test_loaded_flag_persists_but_present_sensor_does_not_reload` and restart/shutdown sensor-default tests explicitly preserve flags while readings are unavailable and clear them only on valid sensor-clear. This combines physical transitions and persistence-boundary coverage; it does not require repeating a power cycle.

- [x] **B05** Nozzle material/diameter Save and Cancel on each head; Home and
  toolhead views agree, including saved versus active diameter/restart notice.
  Partial live r79 verification (8 November): all four physical-head selectors
  open the corresponding nozzle editor. Changing Hardened steel to Stainless
  steel enables SAVE; CANCEL and reopen restore Hardened steel / 0.4 mm with
  SAVE disabled on every head. Backend nozzle settings/revision, filament
  identities/loaded flags, attachment and position stayed unchanged; all heater
  targets remained zero. Evidence: `analysis/validation/2026-11-08-main-track/`
  `nozzle-h[1-4]-unsaved.png`, `nozzle-h[1-4]-reopened.png`, and
  `nozzle-cancel-state.json` compared with `r79-state.json`. Diameter edits,
  Save round trips and Home agreement remain to be completed; this does not
  close B05.
  Additional live H4 validation: diameter Cancel restored 0.4 mm; saving
  Stainless steel / 0.6 mm completed and read back on H4 only, with active
  diameter still 0.4 mm. The editor and toolhead view both displayed the restart
  requirement. Restoring Hardened steel / 0.4 mm through SAVE completed and
  cleared the notice, without restarting. No motion, heating, metadata or
  loaded-state change occurred. Configuration byte comparison found only H4
  diameter formatting normalized from `0.400000` to `0.4`, explaining why its
  revision did not return to the original hash despite equal settings.
  Evidence in the same directory: `nozzle-h4-diameter-reopened.png`,
  `nozzle-h4-save-complete.png`, `nozzle-h4-saved-toolhead.png`,
  `nozzle-h4-saved-state.json`, `nozzle-h4-restored-complete.png`,
  `nozzle-h4-restored-state.json`, and `nozzle-restored-printer.cfg`.
  Completed remaining scope on H1–H3: diameter Cancel/reopen retained 0.4 mm;
  each head saved Stainless steel / 0.6 mm, with 0.4 mm still active and a
  restart notice on its toolhead view. Each was restored through SAVE to
  Hardened steel / 0.4 mm before testing the next head. Readbacks verified only
  the intended head changed. Home after restoration displays Hardened steel /
  0.4 mm for all four heads, matching the backend and toolhead views.
  Evidence: `nozzle-h[1-3]-full-{cancel-reopened,toolhead-saved}.png`,
  `nozzle-h[1-3]-full-{saved,restored}.json`, `nozzle-three-before.json`,
  `nozzle-three-after.json`, and `nozzle-home-restored.png` in the same directory.
  All nozzle values, filament identities/loaded flags, attachment and position
  matched the initial state after restoration; heater targets stayed zero.
  This validates the restart notice without applying a mismatched physical
  nozzle diameter through a restart.
- [x] **B06** AFC-compatible remote reads and metadata writes in standalone:
  correct physical head, brand/material/color/temperature ranges, persistence,
  invalid-input refusal, and no stale openACE lane records.
  Passed on r79 with live round trips and restored metadata; evidence above.

**C — Heating, homing and head mechanics**

- [x] **C01** Current/target temperatures match Home for each head. Numeric target
  starts heating; X and target zero stop it. Other heaters are unaffected.
  Live r79 keypad regression passed: from target zero, pressing 2, 2, 0 directly
  displays 220 without deleting a leading zero; Cancel leaves all targets zero.
  Evidence: `keypad-initial-zero.png`, `keypad-first-2.png`,
  `keypad-second-2.png`, `keypad-direct-220.png`, `keypad-cancel-220.png`, and
  `home-keypad-after.json` under the 8 November main-track evidence directory.
  Settings, loaded flags, attachment and position were unchanged. This checks
  draft entry and cancellation, not the remaining per-head heating/stop matrix.
  Live r82 H1 heating/stop check passed: entering 50 directly from initial zero
  and SAVE set only extruder target to 50°C; X reset it to zero. Backend readback
  confirmed other heater targets stayed zero, position and identities unchanged.
  Evidence: `r82-temperature-check.json`, `r82-temperature-50-draft.png`,
  `r82-temperature-50-applied.png`, `r82-temperature-x-off.png`. This is H1
  target/X coverage; target-zero entry and remaining heads still need checks.
  Subsequent r82 matrix passed all four heads: SAVE set only the selected heater
  to 50°C; numeric zero and X each reset it to zero. Sixteen readbacks confirm
  unchanged position/identities; final loaded-state records match the baseline.
  All targets ended at zero. Evidence: `r82-temperature-matrix.json` and
  `r82-temperature-matrix-h*-*.png`. Subsequent Home-to-toolhead comparison
  passed all four heads with contemporaneous backend readbacks. H1–H3 display
  the same rounded values (36, 39, 39°C); H4 cools from 45 to 44°C between
  screens, matching readbacks 44.71→44.20°C. All targets are zero. Evidence:
  `r82-home-temperature-comparison.json`, `r82-home-temperature-h*.png`,
  `r82-selected-temperature-h*.png`. This closes C01 at low-temperature idle
  operation; it does not qualify material extrusion or print temperatures.
- [x] **C02** Take/Dock each head, including switching from another mounted head;
  perform three successful cycles per head as an initial repeatability gate.
  Sensors, mounted label, active extruder and completion receipt agree; no belt
  skipping, failed-release departure or unintended retry. Stop on any mismatch.
  **Current reconciliation (12 November):** accepted from the retained r91/r102
  head cycles, r108 H3→H2→H3 status fix, operator-confirmed unhomed-Z Dock after
  r110, and camera-observed H4 Dock/Take on 12 November. The three-cycles wording
  is historical: the user's later scope explicitly excludes repeating unchanged
  mechanical qualification. R25 records current failure/refusal coverage. Existing
  intermittent front homing impact remains a watch item, not another cycle quota.
  r91 H3 backend-dispatched cycle 1 completed on 8 November: normal homing
  restored XYZ with mounted H3, Dock reported empty carriage, then Take reported
  attached H3 with extruder2 active, fail_flag=0 and changing_tool=0. Loaded flags
  and identities were unchanged, all targets zero, final XYZ -13/275/7 mm.
  Evidence: `repeatability-home.jsonl`, `r91-h3-{dock,take}-1.jsonl`, corresponding
  camera snapshots and `r91-h3-cycle-1-summary.json` in the main-track directory.
  Snapshots do not prove absence of belt skipping throughout motion; this was not
  a touchscreen-dispatched or continuously observed/audio-qualified cycle.
  H3 cycle 2 also completed through injected touchscreen Dock/Take taps, with
  matching receipts and three numbered gray completed stages on each result
  screen. Metadata/loaded flags remain unchanged; heaters zero. Evidence:
  `r91-ui-cycle-2-summary.json`, `r91-ui-dock-2.json`, `r91-ui-take-2-final.json`
  and `r91-ui-{dock,take}-2-result.png`. The first Take read caught moving;
  polling the same operation confirmed completion without resubmission.
  H3 cycle 3 completed with matching Dock/Take receipts, attachment, extruder2,
  no fault, and unchanged loaded flags/metadata. All targets remain zero.
  H3 now has three successful backend-confirmed cycles; see
  `r91-h3-{dock,take}-3.jsonl`, corresponding camera images and
  `r91-h3-three-cycles.json`. Other heads, switching and full observation remain
  open; the overall C02 gate is not closed by H3-only evidence.
  Cross-head H3 → H4 → H3 also completed through backend dispatch, with each
  target attachment matching its active extruder and completion receipt. Both
  loaded records and all identities stayed unchanged; final heaters zero and
  H3 attached. See `r91-switch-h3-h4.jsonl`, `r91-switch-h4-h3.jsonl`, corresponding
  camera snapshots and `r91-switch-h3-h4-summary.json`. This adds H4 take/dock
  evidence but does not complete its three-cycle gate.
  H3 → H1 → H2 → H3 subsequently completed with each active extruder matching
  its attached head, no reported fault, no unresolved operation, zero heater
  targets and unchanged identities/loaded flags throughout. Evidence:
  `r91-switch-h3-h1.jsonl`, `r91-switch-h1-h2.jsonl`, `r91-switch-h2-h3.jsonl`,
  corresponding camera images and `r91-switch-h1-h2-summary.json`. This covers
  an initial take/dock of H1/H2 through switching, not their three-cycle gate.
  All four heads now have initial successful mounting evidence in this session;
  Second round H3 → H1 → H2 → H4 → H3 completed with each target attachment,
  active extruder and completion receipt agreeing. No reported faults; loaded
  records/identities unchanged and all targets zero. Final H3 Z matches the
  round's starting Z within 1e-6 mm. H1/H2/H4 each now have two successful
  take/dock cycles via switching; one further round remains. Evidence:
  `r91-round2-*.jsonl`, camera snapshots and `r91-round2-summary.json`.
  Final round H3 → H1 → H2 → H4 → H3 also completed with the same attachment,
  active-extruder, receipt, fault, metadata and heater checks passing. All four
  heads now have at least three completed cold take/dock cycles, including
  switching from another mounted head. Final H3 Z again matches the start.
  Evidence: `r91-round3-*.jsonl`, camera snapshots and `r91-round3-summary.json`.
  The backend repeatability portion of C02 is complete. Keep the overall C02
  gate open for continuous motion/audio observation (snapshots cannot exclude
  belt skipping throughout motion) and mounted-label checks for H1/H2/H4.
  Human physical-touch qualification remains separate.
  The final H3 Z=7.178125 mm was investigated before further cycles. Its
  0.178125 mm increase equals H3 minus H4 calibrated Z offsets: idle wiping
  raises physical/logical clearance to at least 7 mm, and switching back retains
  that clearance. `r91-switch-clearance-explanation.json` records the live
  sequence. Two new actual-macro interpreter cases pass
  (`r91-switch-clearance-model.xml`): three repeated calibrated head sequences
  stay bounded in standby, while printing restores the original logical XYZ
  exactly. This explains the observed idle height; it does not qualify a live
  print or demonstrate real-machine repeatability for the remaining heads.
  Injected taps do not substitute for human physical-touch qualification.
- [x] **C03** On a mounted, appropriately heated head, verify extrusion and
  retraction direction/distances, including 25/50 mm. No XYZ/home/dock movement;
  G-code modes, E origin, flow/speed and unrelated settings remain correct.
  **13 November acceptance:** user confirmed backward filament movement during
  the additional 10 mm H3 retract; all heater targets were verified zero afterward.
  **Prior reconciliation (12 November):** touchscreen distance/direction
  dispatch is already accepted in “Touchscreen manual extrusion dispatch —
  8 November” below: E 0→25→24→25 with unchanged XYZ/modes/loaded records.
  User-confirmed +25 mm output establishes positive physical extrusion. The narrow
  remaining observation was direct manual retract direction (now accepted); do not repeat
  dispatch or request another 25/50 mm extrusion solely to close this checkbox.
  r88 H3 backend step validation passed at X-13/Y80: +25, +50, -1 and
  +1 mm commands each reported the expected E delta, preserved XYZ, G-code modes,
  logical E origin and flow/speed factors. Heater target returned to zero and H3
  remained loaded. This does not measure physical filament travel or exercise
  touchscreen distance-button dispatch; larger retractions remain unqualified.
  Evidence: `h3-step-r88-position.jsonl`, `h3-step-r88.jsonl`,
  `h3-step-r88-summary.json`.
- [x] **C04** Test cold nozzle, contradictory attachment, unknown position,
  disconnected status and busy operation refusals without commanding unsafe motion.
  r91 live cold-extrusion refusal passed through an injected touchscreen tap:
  H3 mounted, 29/0 C, `can_extrude=false`; Extrude reports “Heat the selected
  nozzle first.” Before/after readback preserves physical/logical position,
  attachment, session, operation records, print submission and all filament
  identities/loaded flags; all four targets stay zero. Evidence:
  `r91-cold-extrude-refused.png`, `r91-cold-refusal-{before,after}.json`,
  `r91-cold-refusal-verification.json`. This covers cold Extrude only, not the
  remaining refusal matrix or physical-finger input.
  The initial CLOSE tap on an old completed result did not dismiss it. Home
  navigation worked; reopening Result and tapping CLOSE then worked. Captures
  `r91-cold-controls-settled.png`, `r91-result-reopened.png` and
  `r91-result-close-retry.png` retain this unresolved intermittent observation;
  a successful retry does not establish its cause or qualify B03 touch behavior.
  Additional r91 live check: selecting docked H4 while H3 is mounted, then
  tapping Extrude, reports “Take the selected head first.” Returning through
  Filaments → Toolheads focuses mounted H3 rather than the last selected H4.
  Both view-switch buttons occupy the same bottom-right position. Before/after
  readback preserves attachment, active extruder, physical/logical position,
  homing, session, operation records, print submission and all filament records;
  all heater targets remain zero. Evidence: `r91-unmounted-extrude-refused.png`,
  `r91-focus-{h4,filaments,mounted-return}.png`, `r91-focus-after.json`,
  `r91-focus-verification.json`. This is selected-head mismatch coverage with
  consistent sensors, not a contradictory-sensor test.
  Evidence reconciliation after r95: contradictory attachment inputs are covered
  at the macro-rendering boundary by `test_manual_step_refuses_before_any_commands`
  (17 passing cases in `r79-main-regression.xml`), including hall, mount/dock
  sensor and motor mismatch. Standalone delivery rechecks changed attachment
  before posting (`r81-ui-regression.xml`,
  `test_standalone_heater_delivery_and_readback`). Native controls reject
  synthetic clicks during unknown/pending operations
  (`setup-completion-durability.xml`, native lifecycle test). These are accepted
  host fault checks, not live sensor-fault observations; do not provoke conflicting
  physical attachment merely to repeat them. Unknown-position preparation belongs
  to D01/G02; stale/disconnected-status integration remains F03. No unsafe-motion
  refusal test requires deliberately inducing a mechanical or USB/CAN fault.

**D — Complete external filament service**

  **Current evidence:** Current reconciliation (12 November): accepted from the live cold/mismatched-head refusal plus the explicit macro/native fault assertions listed above. D01/G02 establish current unknown-Z handling and F03 establishes disconnected-status behavior. No conflicting physical sensor state needs to be manufactured.

- [x] **D01** Load modal permits metadata editing and Cancel without movement.
  Preparation homes only XY if needed, mounts the selected head if needed,
  moves to the off-bed service location and heats the right head. Current r98+
  behavior does not require a Z reference. Mounted-H3 XY-only preparation with
  Z unhomed is accepted; automatic mounting through Load remains a distinct
  live branch to cover in the next attended session above.
  The following r83 record is historical and its Z prerequisite is superseded.
  r83 no-motion portion passed on H1: Load opens metadata setup; Sunlu/PCTG
  draft selections work, CANCEL discards them, and reopening restores Generic /
  Unknown. Unknown Z keeps LOAD disabled with an explicit explanation that
  filament service will not home Z. Backend identity/revision, loaded flags,
  operation records, session and position stayed unchanged; all targets zero.
  Evidence: `r83-h1-load-*.png`, `r83-load-cancel-state.json`,
  `r83-load-cancel-verification.json`. The physical preparation portion remains open.
  **Current evidence:** Reconciled 12 November: accepted. r83 covers metadata draft/Cancel without changes. r110-auto-mount-confirmed.json records Load from docked H3 reaching insertion with H3 attached and only XY homed, confirmed by the operator. The older statement below calling automatic mounting open is superseded.

- [x] **D02** Baseline manual PLA load: verify feed, configured purge, nozzle
  wipe, heater-off and loaded-state completion. Accepted physical sequence used
  55 mm feed and the 50 mm fallback purge. User calibrates purge amounts in
  OrcaSlicer; finding a universally sufficient color-transition amount is not a
  WM+ acceptance requirement. Slicer-purge handoff is tracked separately below.
  Live r88 H3 Load completed after the user confirmed pink filament loose above
  the gears and ready. Separate idle homing established XYZ with H3 retained;
  Load then positioned/heated, fed 55 mm, purged 50 mm, wiped and completed with
  all nozzle targets zero. H3 reports loaded; H4 loaded state and all identities
  were preserved. Seven numbered stages render gray after completion; heating
  showed orange current stage and live current/target. Camera confirms service
  positioning but obscures the outlet. The user subsequently confirmed “pink
  extruded and wiped,” closing physical H3 Sunlu PLA Matte feed/purge/wipe
  verification for this run. Full D02 color/material-transition qualification
  remains open: this same-filament reload does not prove a full transition from
  another color or material. Evidence:
  `h3-load-home-r88.jsonl`, `h3-load-r88-live.jsonl`, `h3-load-r88-summary.json`,
  `h3-load-r88-heating.png` and `h3-load-r88-result.png`. No print was started.
- [x] **D03** Unload confirmation Cancel does nothing. Confirmed Unload completes
  tip shaping/retraction, clears loaded flag, turns target off and ends with
  “Filament unloaded. Please remove filament.” Remaining sensor presence must
  mean present-but-unloaded, not failure or automatically loaded again.
  H3 runtime/UI acceptance is already recorded in `unload-live.jsonl`,
  `unload-summary.json`, `unload-heating.png`, `unload-result.png` and
  `unload-persisted-flags.json`: all four stages completed, target zero, loaded
  flag cleared despite inlet presence, and the removal prompt displayed. The user
  also previously confirmed that pink filament fully came free. These baseline
  H3 checks must not be repeated simply to fill this aggregate checkbox.
  r83 confirmation/Cancel portion passed on loaded H4. Its slot menu offers
  Unload, which opens “Unload filament from Head 4?”; CANCEL returns without
  changing metadata/revision, loaded flags, operation records, session, position
  or targets. Evidence: `r83-h4-unload-*.png`, `r83-unload-cancel-state.json`,
  `r83-unload-cancel-verification.json`. The unavailable UNLOAD label remained
  white despite missing Z; local r84 makes disabled procedure headers gray, with
  a native regression reproducing the defect (`r84-disabled-header-red.xml`).
- [x] **D04** Numbered steps: gray completed, orange active, white future; live
  heating current/target. Close/reopen retains the same operation, errors retain
  the failed stage/reason, and future stages are not presented as completed.
  r91 host follow-up passes an explicit Unload navigation/failure scenario using
  the native dialog and current backend stage names. Closing during heating and
  reopening during retraction retains the same operation without submission or
  cancellation. A failed retraction stays orange, the future finish stage stays
  white, the reason survives another close/reopen, and STOPPED cannot dispatch.
  Ordinary progress/failure updates retain the existing labels without allocating
  widgets. Evidence: `r91-unload-progress-reopen.xml` (native lifecycle suite).
  That regression is host-simulated LVGL coverage. Subsequent live r91 validation
  stopped H3 Unload during heating and reopened the result successfully: completed
  positioning stays gray, interrupted heating stays orange with live temperature
  and target zero, and future retraction/finish stay white. The cancellation reason
  and operation ID survive reopening, without restarting the operation. See F02
  and `r91-stop-heat-{active,result,closed,reopened}.png`. Other interruption phases
  belong to F02, not this presentation gate. Accepted from the existing host and
  live stage/temperature/reopen evidence; no new physical run is required.
- [x] **D05** Verify WM+'s per-head dispatch and changed material-transition
  selection. Cover distinct changed branches (low-to-high, high-to-low, overlap
  and disjoint-range refusal) using generic ranges. Reuse accepted head routing
  and stock tip-shaping behavior. Do not require physical load/unload of every
  head/material combination or requalify unchanged stock shaping recipes.
  Any physical transition test must state which changed temperature/feed/purge
  behavior its existing host or live evidence does not establish.
  Source audit now records all 22 built-in names, Load/Unload targets and the
  four shared shaping routines in the [material recipe qualification matrix](standalone-filament-management.md#material-recipe-qualification-matrix--8-november).
  PA/PC/PP/PVA/Marble reuse the stock `pla` routine. That inventory is descriptive,
  not a new stock-polymer qualification gate. Unknown-name/range admission and
  WM+'s changed transition selection remain in scope.

**E — Files, mapping and real prints**

  **Current evidence:** Reconciled 12 November: accepted for changed WM+ selection/dispatch contracts. Existing directional-limit, overlapping/disjoint/missing-range and mixed-residue tests assert the selected temperatures or refusal; the recorded Sunlu PLA/PETG round-trip planning test verifies history, head isolation, feed/purge/wipe settings. Existing all-head routing and baseline feed/wipe evidence remains applicable. This does not claim physical polymer compatibility or universal color-clearing calibration, which the user excluded from this gate.

- [x] **E01 — Current scope:** Local browsing and History selection reach the
  intended preview and CANCEL returns without printing. Physical USB G-code copy,
  numbered copy stages/readback and missing-drive/failure acceptance are deferred
  by the user on 8 November; they are not current completion gates or passed
  checks. Profile import stays hidden and remains separately deferred.
  Live r82 History selection opened the intended `openace_h1_link_window_20261030.gcode`
  preview; CANCEL returned to History. The file reported unavailable metadata
  and showed no mapping rows. PRINT was not pressed. Evidence: `r82-history.png`,
  `r82-history-selected.png`, `r82-history-cancelled.png`. USB copy and failure
  paths remain deferred; this is navigation evidence only.
  Read-only mount inspection on 8 November found no USB storage mounted. A drive
  with a G-code file is no longer requested for this completion track. Host copy tests
  pass success and collision/timeout/wrong-path/wrong-size/overwrite cases,
  changed/disappeared source, no duplicate copy and responsive UI while the
  transport blocks (`preview-usage-usb-validation.xml`). These do not replace
  physical USB mount/copy validation.
- [x] **E02** Preview fixtures: one used filament among seven presets, real
  multicolor, sparse tool indices, length-only metadata, missing/malformed usage;
  correct row count, grams preferred, no reassignment of original sliced IDs.
  Host renderer coverage completed on 8 November: real parsed metadata now feeds
  the native row renderer for sparse IDs 1/3, grams plus length, length-only and
  absent usage. Checks verify exact material/usage captions and selection IDs;
  no grams are fabricated when weight is absent. Missing usage retains preset
  entries without a usage caption; it cannot establish actual used-tool count.
  Existing parser coverage rejects malformed usage and reports all-zero usage.
  Evidence: `preview-usage-usb-validation.xml` (3 passed, including two USB tests).
  Live real-file cases cover Superbird, sparse locomotive and five-tool cube;
  less common metadata cases are host-validated, not live fixture-qualified.
  Live r87 fixture validation passed through the installed Moonraker parser and
  touchscreen: comment-only sparse PETG/ABS fixtures show 0.38/0.75 g when both
  units exist, and 125/250 mm when weight is absent. Invalid negative usage
  produces a metadata warning with no mapping rows and disabled PRINT. Missing
  usage displays the four preset entries with no per-row usage. This cannot prove
  actual used-tool count when the source supplies no usage; that remains a known
  limitation, rather than treating preset count as usage evidence. All four
  previews were cancelled; fixture files were hash-verified and removed.
  Evidence: `preview-fixtures-metadata.json`, `preview-fixture-*.png`,
  `preview-fixture-capture-order.json`, `preview-fixtures-cleanup.json`, and
  `preview-fixtures-verification.json`. Full preview titles identify each capture;
  the original capture filenames were corrected after observing stock sort order.
  Identities/loaded flags/session/operation records/position/targets and print
  submission were unchanged. No test file was executed.
  Accepted from retained parser, renderer and live fixture evidence. The r88
  missing-usage warning checks (`r88-usage-warning.xml`) cover explicit disclosure;
  absent source metadata cannot establish actual usage and does not require
  another preview run.
- [x] **E03** Map sliced rows to different physical heads, including nonidentity
  mappings. Picker colors/labels/eligibility agree; Cancel makes no backend change.
  Metadata/file replacement or changed state invalidates stale review.
  Evidence reconciliation, 8 November: the retained r86/r88 invalidation
  screenshots and r89 H3/H4 mapping screenshots/readbacks cover this navigation
  and review gate. Marked accepted without rerunning previews or submitting a
  print. Actual execution remains E04/E05; intermittent touch responsiveness
  remains B03/F04. This does not qualify every physical-head printing combination.
  Live r86 source-change invalidation passed: locomotive sliced ID 1 was mapped
  to loaded Head 4. A guarded temporary material metadata change to ABS cleared
  that selection and showed the configuration-changed warning. Exact restoration
  to Kexcelled PLA Matte did not silently reapply the old mapping. Identities,
  revision, loaded records, session, position, zero targets and print-submission
  record matched the baseline afterward. Evidence: `r86-mapping-invalidation.json`
  and `r86-mapping-{selected,invalidated,restored}.png`. PRINT was never tapped.
  The configuration-change notice was ellipsized on r86; r87 visual acceptance
  above closes that specific presentation issue. Other physical-head mappings remain unqualified.
  Live r88 file-replacement validation passed: a comment-only fixture mapped to
  H4 was replaced with a same-size file changing usage from 1.00 to 2.00 g. The
  displayed usage refreshed, the selection cleared, PRINT became disabled and
  the review-again notice appeared. CANCEL exited; the fixture was hash-checked
  and removed. Metadata, loaded flags, session, operation/submission records,
  position and zero heater targets were unchanged. Evidence:
  `replacement-mapped.png`, `replacement-invalidated.png`,
  `replacement-fixture-cleanup.json`, `replacement-verification.json`.
  No PRINT action was issued.
  Live r89 follow-up: the real Superbird file shows one used PLA row at 49.31 g.
  H1/H2 are disabled in the picker; loaded H3/H4 have matching identities/colors.
  Selecting H3 shows its pink swatch and Head 3 label; cancelling a subsequent
  picker preserves H3. Selecting H4 replaces the mapping and shows Bluish Gray.
  Preview CANCEL returns to browsing. Session, identities/revision, loaded flags,
  operations/submission, position, homing and zero targets stayed unchanged
  (`r89-mapping-verification.json` and `r89-mapped-h3/h4.png`). No PRINT tap.
  One initial picker tap did not open; the next did. Responsiveness remains an
  unresolved observation under B03/F04, not a fully passed interaction test.
- [x] **E04** Start admission: missing/incompatible source, unavailable head,
  changed file/map and double-tap are handled correctly; uncertain acknowledgement
  never causes a second print submission.
  Host backend validation passed 61 selected tests (`print-admission-host.xml`),
  including unloaded/unknown/missing-head refusal, file/profile/mapping changes,
  paused/active job refusal, one-shot submission and partial/uncertain dispatch
  with no retry. Includes openACE ownership tests, not live openACE validation.
  Native double-tap/disabled dispatch checks passed in r86. Live touchscreen
  submission passed for the single coupon on 10 November; the mapped coupon
  was also accepted once per explicit submission. Its first run was emergency-
  stopped after an operator-reported Y-homing noise; the operator authorized
  a fresh retry after reset. Real print completion is tracked under E05.
  **Current evidence (12 November): accepted.** Reviewed the actual backend
  assertions for pre-dispatch no-side-effect refusal, changed file/profile/map/
  loaded state after preparation, and partial submission at each command boundary.
  They assert no second SD submission. The compiled standalone test verifies one
  HTTP post, matching file/session receipt before success, stale-file refusal
  before context preparation, and unresolved ownership after uncertain delivery.
  Existing native double-tap coverage and accepted real submissions complement
  these fault cases; no deliberate live duplicate print is necessary.

- [x] **E05** Finish a small single-head print and a real multi-head mapped print.
  Validate WM+ mapped submission, first-tool homing, mapped tool/temperature
  routing and purge/wipe handoff. Check changed leveling/timelapse option handoff,
  progress/history integration and Pause/Resume/Cancel interception only. Verify
  no duplicated prime or leftover heater/motion activity. Unmodified stock print
  quality, leveling algorithms, camera recording and history storage are excluded.

  **Current evidence (12 November):** the single-head and mapped-print execution
  portions are accepted from the 10 November completed jobs (including operator
  confirmation/removal of the first coupon, five mapped tool changes, completion/
  history and target-off cleanup). Do not print them again to close this checkbox.
  Changed leveling/timelapse option handoff is covered by the focused passing
  tests in commit `19bad45` (both leveling commands and native true/false option
  handoff). F01/G01 are now accepted through r196, closing this aggregate.
  Retained mapped pid-retry-evidence/summary.json independently records completed
  state and preserved loaded flags across the mapped head sequence. No additional
  coupon print is needed. Print-time status freshness remains separate from
  successful job completion.

**F — Interruption and reliability**

- [x] **F01** After G01 implementation: paused mid-print replacement and real
  runout/tangle prompts keep the intended tool/file context, never home Z, preserve
  the object/clearance, and resume exactly once at the correct position.
  **Current evidence (12 November):** accepted with G01 through r196. r195 proves identical XYZ step counts, logical E=100 after Resume, and exactly 1 mm subsequent absolute extrusion. Service did not home or move Z. Callback ownership and tangle refusal are covered by the 1,430-case affected suite; physical evidence is same-head, with cross-head execution covered in tests.
- [x] **F02** Stop while heating and waiting for insertion; controlled interrupted
  operation recovery verifies stop/heater/sensors without replaying moves. Test
  UI restart/reconnect and stale operation/session IDs; errors remain actionable.
  Live r91 STOP-during-heating passed for H3 Unload. Idle/cold/XYZ-homed preflight
  and camera inspection preceded submission. Preparation moved to X-13/Y80;
  STOP cancelled operation `wm-1594262258-3926203053-3` in phase `heating`, before
  retraction. Backend reports `failed`, `cancelled=true`, all targets zero, and
  preserves all loaded flags/identities, session, attachment and print submission.
  Result close/reopen retains the same cancellation and position without replay.
  Final position: X-13/Y80/Z12.402185, H3 mounted; nozzle cooling with target zero.
  Evidence: `r91-stop-heat-{before,after,reopened}.json`,
  `r91-stop-heat-verification.json` and corresponding framebuffer captures.
  That r91 run did not qualify insertion-wait cancellation, process-loss recovery
  or paused-print behavior. Subsequent r93 process-loss recovery passed
  (`r93-interruption-verification.json`); r94 retained the recovered result.
  Insertion-wait and paused-print coverage remain open; do not repeat the accepted
  heating interruption. No print or filament retraction occurred in that test.
  **Current evidence:** Reconciled 12 November: accepted for standalone service interruption. r91 heating STOP/reopen, operator-confirmed r110 insertion STOP, genuine r177 interrupted Load RECOVER, and r179 single-short-tap STOP cover the remaining named branches. Native lifecycle tests cover stale session/action rejection and retained results without replay. Paused print/runout context stays in F01; physical finger responsiveness stays in B03/F04.

- [x] **F03 — Idle status reconnect.** WM+ disables controls while status is
  unavailable, recovers without navigation or a client/Klipper restart, retains
  focus/filament/operation state, and does not replay commands. Accepted for the
  controlled r96 idle Moonraker outage below. Longer touch/latency soak remains
  F04; physical USB/CAN reliability itself is outside WM+ requalification scope.
  r95 controlled idle Moonraker outage: with standby, zero targets and no active
  operation verified, Moonraker alone was stopped for eight seconds and restored
  with both a finally handler and independent restore timer. At three/eight
  seconds the toolhead screen showed unavailable status and disabled commands;
  selected H3 and layout remained. Backend query readiness returned with the same
  Klipper session and client/Klipper PIDs. Identities, loaded flags, operation
  records, XYZ/homing and zero targets were unchanged. The screen was still stale
  five seconds after query readiness but recovered without navigation/restart in
  the later `settled.png` capture. This accepts eventual idle reconnect and state
  preservation for this outage; recovery latency and continuous oscillation are
  not established by these discrete captures. Do not repeat the outage merely to
  reprove preservation. Evidence: `r95-reconnect/{before,after,verification}.json`,
  `down-3s.png`, `down-8s.png`, `after.png`, `settled.png`, and retained scripts.
  No USB/CAN reset, printer restart, motion, heating or print was commanded.
  Read-only follow-up correlated remote framebuffer mtimes with Moonraker's
  own log: ready at 03:00:56.279 printer-local time; `after.raw` at 03:01:02 still
  shows unavailable status. This establishes roughly six seconds of additional
  visible staleness, not its cause. Runtime has a 700 ms poll gate, 250 ms worker
  sleep, one-second GET deadlines and no reconnect backoff. Earlier watchdog
  event-loop stalls preceded this outage and cannot explain it without further
  evidence. Preserve the latency issue rather than changing timeouts or restarting
  services speculatively. Evidence: `r95-reconnect/moonraker-events.txt` and
  `capture-times.json`; eventual recovery remains established by `settled.png`.
  After the changed r96 polling implementation, one targeted repeat was justified
  to validate that exact change, not to rerun filament service. The eight-second
  idle outage retained disabled controls. The first post-query-ready capture at
  +0.18 s was stale; the +1.33 s capture restored the mounted header and enabled
  controls. Every subsequent sampled capture through +19.03 s stayed recovered.
  Header-region and button-pixel comparisons plus visual inspection confirm H3
  focus/layout retention; sampling does not prove absence of sub-frame flicker.
  Readback preserved client/Klipper PIDs, session, identities, loaded flags,
  operation records, XYZ/homing and zero targets. No motion/heat/printing occurred.
  Evidence: `r96-reconnect/verification.json`, `timeline.json`,
  `ui-recovery-verification.json`, and framebuffer captures. This closes the
  scoped idle-reconnect gate; no further outage repetition is needed absent a
  relevant change or new failure. Actual USB/CAN resets were not induced.
- [x] **F04** Thirty-minute UI/status soak plus real finger interaction on each
  view: retain controls/focus/popups, no reproducible missed presses, no growing
  latency or repeated allocation. Record status latency and missed-tap evidence.
  **13 November acceptance:** user reported “No missed taps”; joined with the
  retained soak and actual UI-process memory evidence below, this closes F04.
  r96 completed a 1,800.43-second idle polling run: 180 successful queries,
  zero query errors, unchanged session/filament state/operations/XYZ/homing,
  all targets zero, and unchanged service process identities. All 1,748 sampled
  framebuffer pixels at the temperature control matched its enabled appearance.
  Median diagnostic-query latency was 251.17 ms. Evidence:
  `r96-soak/summary.json`, `samples.jsonl`, `before.json`, and retained scripts.
  This accepts the unattended idle polling observation, not physical touch or
  full-screen rendering. The recorded 4,912 KB "client" RSS actually belongs to
  the service's `start.sh` shell (PID 3697994); the UI is its child PID 3697997.
  It does not establish UI allocation stability. A separate 600.01-second
  read-only measurement then sampled the actual UI executable 31 times:
  PID/start ticks unchanged, RSS/HWM 22,600 KB throughout, VmSize 1,257,612 KB,
  VmData 397,428 KB, and 24 threads throughout. Evidence:
  `r96-ui-memory/{samples.jsonl,verification.json,remote.py,run.py}`.
  This fills the idle UI-process memory gap only. Physical interaction and
  allocations while changing views remain open; do not repeat accepted
  load/unload or reconnect assertions to cover these gaps.
  Subsequent targeted navigation measurement (`r96-navigation-memory/`) completed
  21 alternating Toolheads/Filaments transitions, each checked against a retained
  header screenshot. UI RSS remained 22,600 KB, VmSize and thread count unchanged;
  VmData reached 397,488 KB by transition 7 and stayed there through transition
  20. This is bounded evidence for these two views, not every editor/modal.
  Before that sequence, the first injected Filaments tap did not navigate even
  in a delayed capture; a second tap succeeded. Retained before/first/delayed/
  second screenshots preserve this unresolved missed-input observation. Do not
  dismiss it as wake behavior without evidence or mark physical-touch acceptance
  complete. Only navigation inputs were sent, ending back on H3 Toolheads.
  Follow-up source/binary inspection narrowed the diagnostic gap: the Toolheads
  navigation widget/callback survives refresh (`StockToolheadView::control`),
  while `Runtime::gui_step` consumes and refuses a navigation request if status
  is stale. The stock 1.1.13 `evdev_read` also drains queued input records before
  returning one state (`0x73cd8c` read loop, `0x73ce30`–`0x73ce44` final state).
  Thus a press and release both queued during a UI-thread delay can collapse to
  released without LVGL seeing the press. Neither mechanism is proven to explain
  this occurrence: no input-reader timing or navigation-admission trace was
  captured with the failed tap. Preserve admission guards and avoid a speculative
  stock input patch; the next diagnostic must correlate input delivery, GUI-loop
  timing and request acceptance on the same failed press.
  During r82 soak, 20 localhost Moonraker object queries measured 150–324 ms
  (median 256 ms), all Ready with the same session (`r82-status-latency.json`).
  This measures backend HTTP query latency, not touchscreen input latency.
  Follow-up interleaved endpoint comparison (8 samples each) measured medians:
  Moonraker server info 27 ms, Klipper webhooks 268 ms, WM+ material 301 ms,
  temperatures 352 ms. Thus the delay is also present in non-WM+ Klipper queries;
  these observations do not isolate a root cause or measure handler CPU time.
  Evidence: `r82-status-latency-comparison.json`.

**H — Stock entry points affected by WM+ (not stock requalification)**

| ID | Scope and impact rationale | Required coverage |
|---|---|---|
| H01 | Camera/video recording/playback: no impact identified in this change set | Out of scope. If WM+ changes the print dialog's timelapse option handoff, verify that handoff under E05; do not requalify recording/playback. |
| H02 | Wi-Fi join/AP/retry: no impact identified | Out of scope. F03 tests WM+ status/reconnect behavior, not stock Wi-Fi setup. |
| H03 | Stock language/sleep/user/FAQ: no impact identified | Out of scope. The added WM+ About/diagnostics entry is covered and accepted under G04. |
| H04 | WM+ changes physical-head selection, G28/calibration dispatch and nozzle editing | G05 tests the specific intercepted callers and their physical-head/context handling; B05 already covers nozzle edits. Do not retest stock calibration algorithms or unrelated self-checks. |
| H05 | WM+ replaces the onboarding filament page and retires legacy loading workers | G03 covers that redirect, no duplicate legacy dispatch, FINISH and setup completion persistence. Stock language/network wizard steps are out of scope. |
| H06 | WM+ changes recovery/head/filament context used by resume paths | Validate only changed admission, stale-context refusal and command handoff against identified callers. Existing unrelated stock power-loss behavior is not a blanket hardware-test gate. |
| H07 | Service/factory callers may reach changed head/homing/filament commands | Source inventory must identify a concrete changed dependency before adding a test. No blanket factory/topology/menu/warning sweep. |

### Separate openACE suite — not a standalone release gate

These remain required for the broader requested combined experience, but do not
hold up the no-openACE release: ownership handover/re-enable and zero-unit mode;
slot assignments/rename/adoption; ACE and mixed external loading; disconnect and
replacement handling; mapped prints; supported manual head actions; atomic unit
removal/renumbering; per-unit humidity/temperature/dryer controls. Drying and
cascade removal are currently disabled placeholders; manual extrusion under
openACE is disabled. Recheck the current openACE contract before implementation.
See [drying handoff](openace-drying-handoff.md). Profile import remains deferred.

### Historical physical-validation prerequisites — r88 (superseded)

This is an old state snapshot, not a current test queue. Use the current remaining
coverage table above; accepted H3 Load/Unload must not be repeated from this list.

**Update:** H3 Load has now completed and the user confirmed pink extrusion and
wiping. H3 and H4 are both persistently loaded, all nozzle targets are zero, and
XYZ is homed. The earlier H3-readiness prerequisite below is resolved. Leave H3
loaded; record any subsequent unloading explicitly. Evidence: `h3-load-r88-summary.json`
and `h3-load-r88-after.json`.

The latest preview-only file-replacement check left the printer Ready/standby,
H3 attached, axes unhomed, all nozzle targets zero, and H4 loaded with Kexcelled
PLA Matte. H3 reports presence but its persistent loaded flag is false. This is
not proof that the filament tip is engaged at the gears. Evidence:
`analysis/validation/2026-11-08-main-track/replacement-after.json` and
`replacement-verification.json`.

| Remaining work | Prerequisite / boundary |
|---|---|
| H3 full Load, purge/wipe, Unload and live stages (D01–D04) | Confirm pink filament is ready at the gears and hands are clear; inspect camera/attachment before motion. Establish a valid Z reference separately with a clear bed; service itself homes XY only. |
| Changed head-routing / transition scenarios (C02/C03/D05) | Identify an uncovered WM+ branch and suitable filament; unchanged stock material recipes do not require qualification. |
| Physical-touch acceptance (B03/F04) | User exercises the touchscreen; injected taps and a successful soak are different evidence. |
| USB copy (E01) | Deferred by the user on 8 November; no drive or physical-copy test needed for the current track. Profile import remains separately deferred. |
| Real prints and paused/runout flows (E05/F01/G01) | Separate print authorization and prepared material/bed. Current authorization explicitly excludes printing. |
| Clean installation / release promotion (A02/G06) | Isolated stock test installation or an agreed recoverable clean-install target; existing helper/config fixtures do not qualify a full live installation. |
| Stock/factory regression and conflict report (G05/H) | Follow the user's requested order: finish the main standalone track first. |

None of these gates is closed by successful preview tests. The current session
has no background test or queued motion waiting to finish. Do not resubmit a
physical operation merely because a status read times out.

### Test result log

Append one row per execution; leave acceptance boxes unchecked until passed.

| Date / build | Test ID / mode / head / material | Result | Evidence / defect / retest |
|---|---|---|---|
| 7 Nov / r58 | Software suite + deployment | PASS (software/startup only) | 315 tests; 9 package checks; `analysis/unified-ui-native/activation-stockwidgets-r58/` |
| 7 Nov / r57–r58 | B04 subset / standalone / H3 / Sunlu PLA Matte | PASS (Klipper restart subset only) | `activation-stockwidgets-r57/after-status.json`, `activation-stockwidgets-r58/after-status.json`; other B04 cases remain open |

### Unattended validation results — 7 November

Evidence directory: `analysis/validation/2026-11-07-standalone-r58/`.
No homing, Take/Dock, heating, extrusion, load/unload, print start, network
reconfiguration, calibration or factory reset was commanded during navigation.
Metadata-only Save was exercised and restored. Live observations apply to r58;
r59 was subsequently deployed and verified for keypad, recovery-stage logic,
print eligibility and PLA Matte compatibility. No physical motion was tested.

| Gate | Unattended result | Remaining limit |
|---|---|---|
| A01 | Installed UI/helper/config hashes match r58; no openACE object; ready/idle, all nozzle targets zero; physical H3 attached | r59 final ready/standby, all nozzle targets zero; metadata and loaded-file hashes unchanged |
| A02 | **FAIL / G06:** final whole-repository run: 724 passed, 34 failed, 3 skipped; remaining failures are sealed delivery/provenance checks | Clean installation is not qualified; skipped gates are not passes |
| B01 | Live four equal external cards in order; H3 pink/loaded, others empty/Load; Toolheads opens on mounted H3; selecting H4 changes focus only | Real finger interaction; mixed ACE menu behavior is separate |
| B02 | Brand/material dropdowns scroll, PCTG selectable; custom Kexcelled retained; swatch opens palette; three-field Cancel discards; brand Save read back in JSON/status/remote lane, then restored | Repeat across remaining heads/fields as needed; stale-draft faults have local test coverage |
| B03 | Opaque editor, compact header and centered toolhead captions confirmed | r59 keypad verified: 0 → 220 without Delete; CANCEL leaves target zero; centered CANCEL/SAVE visible. Physical touch remains open |
| B04/B06 | H3 loaded flag stays true through metadata edits, while other present sensors do not imply loaded; four standalone `lane_data` records, no stale ACE lanes | Cold boot, real sensor transitions and full remote command matrix remain |
| B05/C01 | H3 Home/toolhead nozzle and temperatures agree; nozzle editor and temperature keypad open/Cancel without changes | No heater action or new nozzle Save was performed |
| D01 | Empty H1 opens metadata review and Cancel returns without operation | XY preparation, unknown-Z UX and actual feed remain unqualified |
| D04 | Fault test found recovery advancing past a failed stop/heater-off stage; corrected to retain first failed phase while still attempting heater-off cleanup | Local fault tests pass; physical interruption remains attended |
| H01 | Stock Video gallery opens and shows existing thumbnails; live camera JPEG returned HTTP 200 and was visually inspected | Unmodified stock recording/playback are out of scope; changed option handoff only is covered by E05 |
| H02/H03 | Wi-Fi scan/current connection, General, About and Other functions open normally; settings unchanged | Unmodified stock network/language/sleep behavior is out of scope; WM+ diagnostics were subsequently accepted under G04 |
| G03/G05/H06 | Refreshed static inventory: 153 live macro definitions. Explicit G28 X Y skips z_rise; full G28 uses mounted-head selection | Wizard load/retry have distinct stock heat/home prefixes; current navigation hooks do not establish coverage. Calibration/service and power-loss paths still require caller-specific qualification |

r59 completion evidence: ARM build and review packaging passed; **319 targeted
backend/UI tests passed** (318 in the sandbox plus the socket test separately),
plus **9 review-package integrity tests**. UI artifact SHA256:
`6fc453ebfcfb5f8166e7cd076a975975f691ecd5f90eebd16fb12b98d242379b`.
Backend SHA256:
`4b31c561ec1582c5036668df68950b5bccc604629c2e0f6bc7a6b1c1892ec863`.
Live mapping enables loaded H3 PLA Matte for the PLA Superbird row (49.31 g)
and disables empty H1/H2/H4. No route was selected and no print started.
History opens and lists existing entries. Returned to Home. Persisted metadata
and loaded flags match the pre-validation hashes exactly after restart.

Remaining visual defect found: the mapping source picker's top-right Cancel
still uses a rounded mixed-case button instead of the standard uppercase header
action. B03 remains open until corrected and rechecked.

Additional unattended findings:

- Print mapping previously offered an empty head based only on saved metadata.
  r59 requires an explicit loaded state in both UI eligibility and backend print
  admission, rechecked immediately before dispatch. Present sensor alone is not
  sufficient. Regression tests cover absent/unknown/empty loaded state.
- PLA Matte and PLA now share an explicit compatibility key in both directions;
  display identity remains unchanged. PETG, PCTG, filled PLA and high-temperature
  PLA are not implicitly folded into that family. Empty compatible heads remain
  unavailable. This establishes mapping compatibility, not a guarantee that every
  slicer temperature/speed recipe suits every brand's variant.
- 30-minute idle status soak: 181 samples, zero query errors, all ready, one
  Klipper session; median 283 ms, p95 392 ms, maximum 897 ms. A separate verified
  UI-process sample ran ten minutes: RSS 31,660–33,944 KiB during navigation;
  this short run does not establish absence of a long-term memory leak. The
  first soak's memory fields refer to the service wrapper, not the UI process.
- Kernel logs show a USB serial disconnect/reconnect during the soak, without a
  Klipper session change. Device identity has not been established as CAN.
- Recovery emulation was rerun with the cached Unicorn dependency: all eleven
  tests passed, including the three initially skipped checks.

Full-suite failure triage: the first run was 721 passed / 37 failed / 3 skipped.
Two import failures were the temporary test runner's missing repository path;
one obsolete editor assertion rejected the now-supported standalone source
editor. Corrected the runner and replaced that assertion with successful
source-bound standalone editing checks. The final full run leaves **34 delivery
failures**, not a green release suite. Targeted recovery/UI run passed 316 checks;
its local-socket test passed separately with socket access (317 total). Keypad
lifecycle/runtime checks passed, as did nine review-package integrity tests.

The pre-r59 status soak's first memory field measures the service shell, not the
UI. A first child-process sampling attempt failed because this kernel lacks the
procfs children file. Only `client-memory-verified.jsonl`, which resolves the
actual client using the process table, is valid UI-memory evidence. Neither
failed measurement is counted as a UI failure or a memory pass.

## November 6 scope update

Profile importing is deferred from standalone completion. Its implementation and
stored catalogues are retained for a later release; the Import profiles button
and imported-profile selection are hidden in the current UI. USB acceptance and
import-specific temperature-policy decisions no longer block this release.

Built-in brands: Generic, WonderMaker, Sunlu, eSun, Polymaker. Existing saved
brands remain selectable, including Head 4's Kexcelled identity, without adding
Kexcelled to the default list. All 18 stock materials remain in their original
order, with PCTG, PA6, PA12 and PP appended. Their initial service temperatures
and family recipes require the same attended qualification as other load/unload
operations. Brand selection does not imply a manufacturer-specific preset.

## Evidence and remaining work

| Area | Current implementation | Remaining work / acceptance |
|---|---|---|
| Filament presence | Physical switches drive loaded/empty; empty external cards omit identity | Verify live transitions during attended load/unload |
| Identity editor | Shared brand/material selectors, color swatch, atomic JSON profiles, readback | Head 3 live metadata Save/restart/restoration passed; loaded-head touchscreen changed-value Save, restoration, card and AFC publication passed in r41; intermittent selector taps remain |
| Temperature | Physical heater target command and current/target readback | Attended target/zero tests |
| Extrude/retract | WMP_EXTRUDER_STEP uses physical head and attachment guards | Attended distance/direction and state-restoration tests |
| External load/unload | Sensor-backed async preparation, heating, insertion, feed; Unload confirmation | Stop transport verified in r25; recovery implementation includes screen-restart continuity; attended cancellation/recovery and tip-shaping qualification remain |
| Take/Dock | Stock callbacks traced: crawl() sends T + selected index; release() sends PARK_CURRENT_TOOL | Physical-head wrapper and native UI/receipts connected; sensor reconciliation deployed in r32; attended recovery and hardware qualification remain |
| Nozzle editor | Local draft editor and WMP_SET_NOZZLE backend; physical-head Save/readback, Cancel, stale edits and file recovery tested | Draft/Cancel and palette verified live; same-value Save/readback passed on all heads; r39 changed Head 3 Save, active-diameter restart, restoration and second restart passed |
| USB profile import | Local implementation: bounded USB discovery, async scan/review/save, Orca extraction, compact catalogue, native review dialog and editor Profile selector | r17 installed; live absent-USB scan passed. r18 header/backdrop correction installed and visually verified; deferred from the current release; retain implementation for later USB acceptance |
| AFC compatibility | WM+ lane_data projection and metadata commands | r27 live database/sensor projection and cleanup of stale openACE lanes verified; r32 live empty-head metadata write/readback and exact restoration verified; loaded-head publication passed on Head 4; re-enable handover remains |
| Layout | Home indicators now use sensor state; full-area shortcut verified in r20; native WM header actions; no ACE filter tabs in standalone; single-slot external cards | Final live visual pass including popups and operations |

## Remaining attended acceptance sequence (r42)

The software-only audit is not hardware acceptance. The installed r42 UI has
passed metadata Save/Cancel and nozzle persistence checks; the following gates
remain open. Run one operation at a time with an operator present, capturing the
screen, matching operation receipt, sensor readback and heater targets. Do not
infer successful feeding from a loaded inlet switch alone.

1. **Physical touch:** open the Home filament shortcut and select brand/material
   by hand. Report any ignored taps separately from injected-input misses.
2. **Temperature:** on an identified head with a suitable known filament, set a
   target through the numeric input. Verify the selected physical heater target,
   visible temperature rise, and agreement with Home. Verify X and numeric zero
   each clear the target. Other heads must retain their targets.
3. **Take/Dock:** after confirming the printer's travel/setup prerequisites,
   take a docked physical head and dock it again. Confirm attachment sensors,
   active extruder, completion receipt and state-specific button text agree.
   Do not accept a returned macro alone as success.
4. **Extrude/retract:** with the selected head mounted and suitably heated,
   exercise a small selected distance in both directions. Observe actual feed,
   confirm no XYZ/docking/homing moves, and compare G-code positioning modes,
   flow/speed factors and extrusion origin before/after. Return target to zero.
5. **External Load:** use a sensor-empty head and enter appropriate metadata in
   the loading modal. Verify preparation/mounting, purge travel and heating;
   insert filament only at the prompt. Confirm feeding at the nozzle, successful
   receipt, sensor transition, card identity and AFC lane publication. The load
   procedure must end with its heater target zero.
6. **Unload:** open the loaded card, verify Unload and its confirmation; Cancel
   must leave state unchanged. Confirm Unload with the operator ready to remove
   filament. Observe tip shaping/removal, empty sensor, successful receipt,
   blank card with Load, blank AFC identity and target zero.
7. **Stop/recovery:** stop a supervised load while heating and while waiting for
   insertion. Confirm the matching receipt stops, queued motion drains and the
   heater target reaches zero. Qualify interrupted-operation recovery without
   replaying the action; current sensor state must determine the resulting card.

Use an appropriate manufacturer's temperature range for the actual filament.
Qualification with PLA does not validate PCTG/PA/PP tip-shaping recipes. Keep
those recipe results explicitly unverified until tested with the corresponding
material. No physical operation in this sequence has been performed as part of
the r42 audit. Restoring openACE and checking ownership handover follows the
standalone tests; its separate ACE screens remain outside this goal.

## Deferred import decision

User chose OrcaSlicer filament presets as input. Extract the required fields into
WM+'s own compact format; do not retain the full slicer profile as runtime state.
There is no established WM import format in our evidence. The earlier suggestion
of one was incorrect. Orca sources are available locally at
`/home/anselor/source/OrcaSlicer`; presets may inherit values from parent presets.
Missing inherited values must be surfaced rather than silently guessed.

## Take/Dock integration

Stock 1.1.13 binary evidence: `crawl()` at 0x4f99d4 constructs `T` plus
`choose_filament_index`; `release()` at 0x4f9a8c sends `PARK_CURRENT_TOOL`.
Both call `wait_T_sync()`. Logical T macros apply `box_modify_tN`; the physical
adapter instead uses `_CHANGE_TOOL T=<physical index>`. Dock uses the existing
macro after reconciling current_extruder from physical attachment sensors.
The adapter preserves existing stock travel, homing and retry behavior.

The local `WMP_TOOLHEAD_ACTION` helper returns before dispatch and records a
session/request-specific result. It validates ownership, idle state and captured
attachment again under the G-code mutex. Completion requires sensor agreement;
uncertain motion cannot be silently retried. Candidate r16 connects the helper and native controls. Integrated checks: 158 tests
pass. Hardware tests and unresolved-operation recovery remain. Activation evidence
is in `analysis/unified-ui-native/activation-stockwidgets-r16/`.

ACE drying, ACE assignment transactions and ACE unit management are outside this
standalone goal. They remain separate gaps and must not block standalone delivery.

## Orca import evidence

Local OrcaSlicer source revision `7b1a3d26f29ba65eb2bedc8ab86344f1cefbf743`:
`ConfigBase::save_to_json` writes user presets without a `type` header; the
extractor recognizes filament-specific fields in those files. `Preset::save`
may save only differences from a parent. Parent documents supplied together are
resolved; missing parents are reported, never silently guessed. Plate-specific
bed temperatures are not arbitrarily reduced to a single value.

The real BBL Generic PLA → Generic PLA @base → fdm_filament_pla →
fdm_filament_common chain was parsed locally: Generic / PLA, 220 C, range
190–240 C, with no warnings or errors. The compact store keeps only name,
identity and content-derived ID; slicer G-code and unrelated settings are absent.
20 parser/persistence tests pass; the combined backend/transport verification passed 178 checks. The module is installed on the printer as part of r17.

## USB import integration

`WMP_PROFILE_IMPORT ACTION=scan|review|save ID=...` returns before file I/O;
`wm_material.profile_import` carries the matching result. Review addresses a
scanned file by opaque ID; Save consumes its review token and expected catalogue
revision. Source files and slicer G-code are not copied into active printer
configuration. USB root defaults to the same `~/printer_data/gcodes/USB` path as
the existing native USB adapter and can be configured with `usb_profile_root`.

The native dialog uses CANCEL / REFRESH and CANCEL / SAVE. A Profile selector
appears in standalone filament editors when the catalogue has entries. It copies
metadata into the local draft; normal Save/Load confirmation still applies.
Backend and native tests cover stale tokens, invalid command input, duplicate
Save, absent USB, symlink substitution, catalogue write failure, imported profile
selection and keeping the existing color when an imported preset has no color.

Deferred with importing: use an imported profile's nozzle temperature for both
Load and Unload, or retain separate unload temperatures. Existing unload recipes
can conflict with a profile's declared temperature range; do not silently exceed
that range.

## r17 live import check

The idle standalone printer was updated with the import helper, extractor and
native screen. Exact installed/staged hashes, zero heater targets, no running
filament/toolhead operation, and openACE absence were checked before activation.
Klipper and the client returned ready; all existing unrelated files were preserved.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r17/`.

The live Import dialog completes a USB scan and shows “Insert a USB drive.”
No USB is mounted, so file review/save on the printer remains unverified. The
visual pass exposed inherited button outlines and a lower-page shadow; r18
replaces header buttons with the same text actions as the filament editor and
makes the entire modal backdrop opaque. No physical operations were invoked.

## Nozzle persistence trace

Stock 1.1.13 material selections write `[nozzle] type0..type3` in `tmt1.ini`
(0 = hardened steel, 1 = stainless steel). Diameter selections call
`read_write_nozzle_diameter(physical_head, 1, diameter)`, which invokes
`TM_T1/scripts/read_write_diameter.sh`. That script edits the selected physical
extruder section's `nozzle_diameter` in `printer.cfg`; it does not restart
Klipper or change the active extruder object's diameter. The stock screen also
updates its in-memory record immediately, so visible readback alone does not
prove that Klipper is using the new diameter.

The replacement must distinguish saved configuration from active configuration,
keep changes in a draft until Save, and avoid silently restarting the printer.
A direct call to the old selection callback would not meet those requirements.
Evidence: local firmware payload script and event-handler disassembly at
0x52bce0 (diameter call at 0x52bfd0). No nozzle settings were changed.

The r18 ARM build and targeted LVGL lifecycle/standalone transport checks pass.
r18 is installed and ready; the live import screen has an opaque backdrop,
uppercase text actions and a compact separator row. Screenshots and activation
journal: `analysis/unified-ui-native/activation-stockwidgets-r18/`.

Home mini-view investigation found an explicit fallback in `home_mini.hpp`: it
leaves stock indicators visible whenever no external source has a known material.
That explains the mismatched colors with empty WM+ metadata. This fallback must
be replaced with the same sensor-derived presence/WM+ identity used in the main
filament view; unknown metadata must not revive unrelated stock colors.

## Home indicators correction (r19 installed)

Removed the fallback to vendor colors when WM+ material metadata is absent.
External indicators now use each physical head's projected loaded state and
loaded identity, in head order regardless of source-array order. Loaded heads
without color metadata use gray, empty heads use an outline, and unknown sensor
state uses an outline with a question mark. Sensor-only changes invalidate the
render cache. Stale ACE discoveries cannot show an alert in standalone mode.
The overlay remains within the stock button. Live testing found center taps did not navigate while edge taps did; a full-area navigation target is being added.

The r19 live Home display matches the four physical sensors (Heads 1, 2 and 4
loaded; Head 3 empty). No stale vendor colors remain. Read-only sensor evidence
and screenshots are in `analysis/unified-ui-native/activation-stockwidgets-r19/`.
Touch-area acceptance is not complete: the edge opens Filament but the indicator
center failed in the live test. Native click tests now cover explicit navigation
and rejection of callbacks from hidden pages.

The r20 local correction gives the entire Home indicator area one navigation
callback, with non-clickable circle children and hidden-page rejection. The
render cache excludes heater temperatures/targets so telemetry cannot replace
the touch target mid-gesture. Native lifecycle tests cover both behaviors.

### r20 acceptance

r20 is installed and ready with openACE disabled. The live center tap at (685,
420), directly over a filled Home filament circle, opened the new Filament
screen. Both views showed Heads 1, 2 and 4 loaded and Head 3 empty. Evidence:
`analysis/unified-ui-native/activation-stockwidgets-r20/02-home-live.png` and
`03-center-tap.png`. No physical commands were sent.

## Standalone nozzle editor

The new editor keeps material and diameter selections in a draft until SAVE.
CANCEL performs no settings write. `WMP_SET_NOZZLE` identifies a physical head,
checks the printer session, idle state and file revision, and returns a receipt.
Completion in the UI requires matching saved settings readback. The existing WM
storage locations are retained: nozzle material in `tmt1.ini`, diameter in the
physical extruder section of the main printer configuration. Each file replacement
is atomic; a two-file failure attempts recovery without overwriting another writer.
Diameter changes require a Klipper restart; the saved and active values are both
reported. No automatic restart, heating or movement is part of this operation.

Local validation: 197 Python backend/import tests passed, plus native compilation,
UI lifecycle and command/readback tests. Lifecycle checks include Cancel without
submission, exact physical-head draft submission, duplicate taps, hidden pages,
stale revisions, receipt display and event-binding failure cleanup. Hardware Save
and restart persistence still require acceptance.

Live r21: editor opens on Head 1 with 0.4 mm / Hardened steel. Selecting 0.6 mm
then CANCEL leaves all four heads at 0.4 mm / Hardened steel, no save receipt, and
all heater targets at zero. Evidence is in `activation-stockwidgets-r21`. The live
popup revealed delayed list creation and a sticky transient-status warning; both
were addressed in r22. Live r22 confirms warning recovery, but the selected row
remains blue. The shared style incorrectly targeted LV_PART_KNOB (0x30000);
LVGL 8.3 defines LV_PART_SELECTED as 0x40000 and PRESSED as 0x20. Both
nozzle and filament list styles are corrected locally; rebuild/live acceptance
remains. Reference: https://raw.githubusercontent.com/lvgl/lvgl/v8.3.11/src/core/lv_obj.h

### Next backend work: interruption and recovery

The standalone service currently holds the G-code mutex during its heating and
filament-insertion waits. A queued G-code cancellation cannot reliably interrupt
those waits. Add a request/session-bound cancellation path that can be observed
while waiting, with explicit phase handling and confirmed heater-off/readback.
Do not treat a filament-present sensor as proof that a partial load fully reached
the nozzle. Tool-change and partially fed outcomes need distinct recovery states;
the UI must not simply dismiss an unknown operation as completed.

### Cancellation candidate r24

Adds `/printer/wmp/filament/cancel`, bound to the running operation ID, physical
head and printer session. The endpoint only sets cancellation intent; no hardware
commands are run by the webhook callback. The runner checks at preparation,
heating, insertion, feeding and finishing boundaries. It drains motion with M400,
sets the selected heater target to zero and verifies readback before reporting a
stopped outcome. Failed cleanup remains unknown. Stop does not interrupt an
already queued motion segment; it waits for that segment/phase to return.

The native progress dialog offers STOP for a matching running standalone operation,
then STOPPING after backend acknowledgement. It continues observing the original
receipt; acknowledgement is not completion. Hidden/stale controls and other
operation IDs cannot send Stop. Lost initial delivery can recover to pending from
a matching running backend result without resending the load command.

Local tests: 175 wm_material checks pass (13 new cancellation cases), native
lifecycle and transport checks pass, including lost response, separate cancellation
endpoint, duplicate taps, request correlation, pending acknowledgement, and terminal
readback. r24 built and activated successfully. Its readiness check verified the live endpoint
returns HTTP 400 for a stale session/request, without starting an operation. The
nozzle popup now visibly uses the WM orange selected-row colour (screenshot
`activation-stockwidgets-r24/06-list.png`).
The endpoint has not been exercised against a physical running filament operation.

Additional live observation: immediately after restart, the Home filament summary
continues to show Status unavailable while the Filament page gets valid sensor
state. Investigate status freshness/startup handling and verify Home before
claiming the final visual pass complete.

### Cancellation transport correction r25

An integration audit found that r24's real `UnifiedLoopbackHttp` transport only
allowed G-code POSTs; the cancellation tests used a fake transport and therefore
missed this rejection. r25 explicitly allows `/printer/wmp/filament/cancel` too.
The localhost HTTP regression test exercises the real transport, validates the
request body and HTTP-error parsing, retains the existing G-code route, and
rejects other routes, query variants and oversized bodies. The full
`tests/test_unified_ui.py` run passed.

Native artifact `ae008ea756c06f3970b5864f25893c83baa3291520108f67fb3451ff8ce28ad9`
was activated with unchanged backend dependencies, idle/heater-off guards and
rollback backups. Live readiness passed, including rejection of an intentionally
invalid cancellation session. Evidence: `activation-stockwidgets-r25/`. No
physical operation, heating or motion was started; physical cancellation testing
is still outstanding. Review archive SHA256:
`a293df470ba46ccfd11b9c32ffd44580c150d12ea06b83751bfa6acb9c95b222`.

Home startup follow-up: r25's `01-home.png` showed Status unavailable shortly
after readiness; `02-home-settled.png` then showed the correct three loaded
indicators and empty Head 3 without any intervening navigation or commands.
Thus the observed startup warning recovers automatically; it is not evidence of
a persistent Home data-binding failure. A clearer startup label remains a possible
UI refinement; actual stale/disconnected status must remain distinguishable.

### Finishing-path audit (local, not yet deployed)

The normal standalone completion path previously sent heater-off outside the
protected execution block and did not check target readback. A rejected command
could bypass cleanup, while an ignored command could incorrectly report complete.
Finishing now verifies target zero and the expected physical filament sensor
inside the protected block. Errors drain motion and retry heater-off through the
existing cleanup path; unconfirmed shutdown remains unknown. Cleanup never
replays extrusion or tip shaping.

All 185 `klipper_extras/test_wm_material.py` cases pass, including ten new cases
covering load/unload with successful completion, ignored heater-off, persistent
command failure, transient failure and sensor mismatch. The installed r25 backend
is unchanged; this correction still needs packaging and activation.

Recovery design question pending: after a stopped/failed partial load with filament
detected, offer Unload followed by a fresh Load (recommended), or also guided
finish-loading. Neither option should ask the user to override filament sensors
or infer nozzle loading depth from the presence switch.

### Remote metadata audit

Live `lane_data` contains four `wmplus_tool_*` rows plus five stale
`openace_tool_*` rows while the openACE object is absent. Both publishers currently
remove only their own keys. Ownership handover must reconcile obsolete known-owner
projections while preserving unrelated AFC entries and the canonical metadata.

The local OrcaSlicer `MoonrakerPrinterAgent.cpp` reader (around line 870) consumes
every lane row, and uses nonempty material for `has_filament`, rather than `loaded`.
Consequently, standalone empty-head lane rows must omit saved identity metadata
even if it remains available in WM+'s canonical profile store for future loading.
Current `_lane_data` does not yet enforce that distinction. This is a confirmed
remote-display gap, not just a theoretical schema concern.

Completion fix activation: r26 installed backend
`7ecd684d8656738a973ae17636331e7728eabda9762b69c114ae9ff641787a42`
with the unchanged r25 native artifact. Guarded activation and live readiness
passed; no heat or motion was initiated. Evidence is under
`activation-stockwidgets-r26/`; packaged archive SHA256
`566cbf3ed4842040d302ed9e010532bcf9821534f2923ad79f7363d597578fca`.
This supersedes the preceding local-only deployment status for the finishing fix.

### Sensor-backed lane publication and handover correction

Standalone lane projection now publishes blank identity and zero temperature
metadata unless the physical presence state is loaded. Canonical profiles remain
unchanged and reappear when the sensor detects filament. Regression coverage
includes both empty and unknown sensor observations.

The publisher reads live `wm_material.session_id` and `afc_metadata.owner` through
Moonraker before writing. It rejects stale sessions, unavailable/changed owners,
and nonempty standalone publications when another manager owns the printer.
Each mutation revalidates ownership. It publishes replacement WM+ rows before
retiring obsolete numeric `openace_tool_*` rows, and only does the latter under
standalone ownership. When openACE/AFC owns the printer it removes obsolete WM+
rows only. Other AFC keys and nonstandard prefixed keys are preserved. This
changes cached projections only, not either manager's canonical filament data.

The full backend suite passed with 193 cases; subsequent empty/unknown sensor
parameterization passed all nine focused projection/publisher cases (194 total
collected cases). Database failure leaves publication pending for retry; no failed
publication is recorded as synchronized.

The final full backend run passed all 194 tests. r27 was activated successfully
with helper SHA256
`8d3c12b48b4b3277afdfe724913ff47bc6f3730af8d00aa6d00820c233d981ff`.
Live evidence (`activation-stockwidgets-r27/lane-evidence.json`) confirms exactly
four WM+ rows, no stale openACE rows, matching physical sensor presence, available
metadata commands, standalone ownership and no publisher error. No heating or
motion was initiated. Review archive SHA256:
`583635347a3ff2ad686a824467a750468b03bcd59ad8cbba03841463bb89c787`.

### Remote lane command identifiers (local, not yet deployed)

Metadata commands now accept `LANE=wmplus_tool_N`, `LANE=TN`, `LANE=tN`,
or `LANE=N` for logical tools 0–3, matching the forms supported by openACE.
These resolve through the current `box_modify_tN` mapping; they do not interpret
the logical tool number as a physical head. Foreign openACE keys, physical-head
IDs, out-of-range tools and malformed identifiers are rejected without writing.
All 205 backend tests pass, including remapped-head readback and invalid identifiers.
Installed r27 still accepts only the full `wmplus_tool_N` form.

Remote metadata commands (all idle-only, metadata-only; no motion or heating):

| Command | Fields |
|---|---|
| `SET_COLOR LANE=wmplus_tool_0 COLOR=00FF00` | Six hex digits, without `#` |
| `SET_MATERIAL LANE=wmplus_tool_0 MATERIAL=PLA` | Material; clears the old temperature recipe |
| `WMP_SET_BRAND LANE=wmplus_tool_0 BRAND=Generic` | Brand |
| `AFC_SET_SPOOL_TEMP LANE=wmplus_tool_0 EXTRUDER_TEMP=220 MIN_TEMP=200 MAX_TEMP=230 BED_TEMP=60` | Optional temperature fields, validated together |

Read projected lanes through Moonraker's `lane_data` database namespace. The
`wm_material` printer object exposes physical sensor state and canonical profile
metadata; a blank remote lane for an empty head does not erase its saved profile.
Commands defer to openACE/AFC when either manager is present.

Lane-alias activation: r28 installed helper
`7916abe474e6b8bdf9c83ca1ca4260b2a1334f3a7d276b48339e532219d75ab9`.
Guarded activation and readiness passed. The live command probe sent an invalid
color through `wmplus_tool_2`, `T2`, `t2` and `2`; all four reached color validation
and returned HTTP 400 with the expected validation error. Before/after checks
confirmed unchanged identities/revision, physical sensors, operation records,
session and zero heater targets. Evidence:
`activation-stockwidgets-r28/lane-alias-probe.json`. This proves live alias
routing and rejection, not a successful live metadata write/readback round trip.
The earlier local-only alias status is superseded. Review archive SHA256:
`bbca39167c74b779ff02ed46dc3a9275fe33125f24d01fa79889d8821329b916`.

### Interrupted filament recovery (local, not yet deployed)

`WMP_RECOVER_FILAMENT ID=... SESSION=... HEAD=...` now reconciles an exact
unknown standalone operation. It requires idle ownership and no unresolved
toolhead operation, drains queued motion with M400, attempts selected-heater off
even if draining fails, checks target-zero readback, and verifies attachment and
filament sensors. No extrusion, homing, docking or original-sequence replay occurs.
Any failed check retains unknown. Success marks the original operation failed
with `recovered=true`, rather than claiming the interrupted load completed.
Detected filament leads to an unload-before-loading message; an empty sensor
leads to an empty-head message. No manual sensor-state assertion is offered.

The native current-operation dialog offers RECOVER only for fresh matching
operation/head/session evidence and waits for backend readback. Transport errors
allow explicit recovery retry; accepted RPC is not success. New standalone
load/edit/Take-Dock/extrusion/print admission cannot replace an unknown filament
operation. openACE's own reconciliation remains separate.

Validation: all 226 backend tests pass, including cleanup failure, unavailable
sensors, wrong-session/request/head, active ownership/job changes, duplicate
recovery, and no feed replay. Targeted native runtime compilation, transport
readback and LVGL lifecycle tests pass, including hidden/stale RECOVER controls.
The config/extrusion checks passed in the broader run; its four failures were
backend wording expectations, subsequently corrected and covered by the full
backend rerun.

Before deployment: reconnect recovery UI to an existing backend operation after
a screen-process restart (currently the dialog retains only its own request ID),
then build/package/activate and visually validate. Toolhead-operation reconciliation
is still separate outstanding work. No physical recovery command has been invoked.

Recovery restart continuity is now implemented locally: a fresh native runtime
can reopen an unknown backend load/unload record through the Toolhead Recover
entry, retain its request ID, and reconcile it without dispatching a new load.
Only current-session, fresh standalone records with valid request/head identifiers
are accepted. Existing in-flight requests and unrelated unknown operations are
not silently replaced. A changed printer session disables the control.

Targeted native runtime, transport and lifecycle tests pass for a fresh-screen
reopen, stale/malformed records, duplicate clicks, and lost response handling.
The restart tests caught a null initial receipt, now guarded.

Recovery release r29 activated successfully with unchanged openACE-disabled
ownership and idle/heater-off guards. Native SHA256:
`db0b02a260fb9c1687e23869a52a128a34f93942d757bf48825321ed8dd53b7b`;
helper `6b71e73bae7a768010222caf2475e638c0b8ab3100189410e261994094b8c70f`;
macros `7092f6196b6bd387330a259ed3642e62a1ea43833e89513300ba010d0f291c13`.
Live readiness verified the recovery protocol and rejected an invalid-session
recovery command before any hardware action. Native restart tests and the
extrusion/configuration checks passed. Evidence: `activation-stockwidgets-r29/`.
Review archive: `10a73e102b7995086f508a96009dbf17e7fff354319990cc8cb282ab595e2bf7`.

Live screenshots 02/03 show standalone Filaments and Toolheads opening correctly,
with recovery entry hidden when no interrupted operation exists. The Toolhead
loaded card still has an empty material pill and absent color when metadata is
unknown, unlike the Filament overview's unknown placeholder; visual consistency
remains to fix. Actual recovery of a running/interrupted physical procedure is
not yet hardware-qualified. No heat or motion was initiated.

## Toolhead unknown identity and interrupted-control follow-up

The local native follow-up displays `Unknown` material, `Unknown brand`, and an
outlined question-mark color placeholder when a sensor reports loaded but no
identity exists. It does not manufacture or save a filament identity. Empty
heads retain an empty outline and hide the material widget.

Control availability now includes backend filament and toolhead operations in
`running` or `unknown` state, even without the screen's local busy receipt.
Load/Unload and conflicting controls are visibly disabled; disabled or hidden
buttons reject direct event delivery as well. Lifecycle regression checks cover
both interrupted-operation types, empty versus loaded metadata, blocked clicks,
and resuming normal Unload availability when the operation clears.

The native lifecycle, runtime compilation, standalone transport/readback, and
filament procedure checks passed (4 tests). This follow-up is not yet installed
or visually verified on the printer. Take/Dock unknown-operation reconciliation
and attended physical qualification remain separate incomplete requirements.

ARM build passed for this follow-up. Candidate SHA256:
`76e6f5afd1672efa40f53af3e94d14a8f5547e4a29ea178f8dfd00e26fd7655a`.
The review package was generated successfully. Installed printer release remains
r29; this candidate still requires guarded activation and live visual review.

The r30 follow-up was activated on the idle printer with unchanged dependencies,
openACE disabled, heater targets zero, and no unresolved operations. Live review
confirmed the loaded/empty controls and metadata visibility. It also caught an
incorrectly aligned question mark and black outline. The follow-up uses a separate
positioned question-mark label and a gray outline; lifecycle regression and the
ARM build passed. Screenshots in `activation-stockwidgets-r30/` also establish
that initial unavailable status settles to fresh sensor-backed mounting state.
No heat, extrusion, loading, unloading, or tool-change command was initiated.

Release r31 installed and passed readiness with native SHA256
`ca77e6788fd5989b63b95cf89df7bfa7dde4700d5ec24ac6dce3d89c94097df4`;
helper/macros and other dependencies remain those of r29. Review archive SHA256
`bc517fccce8e2d409d709834ebf3ef150b7e215a2baf7c61a485ad65b9aefe10`.
Live screenshots `activation-stockwidgets-r31/03-toolhead-loaded.png` and
`04-toolhead-empty.png` verify the centered unknown-color marker, gray outline,
loaded Unload, and empty blank-metadata Load states. Actual/target and nozzle
information remain present. The printer is left on Toolheads, Head 3 selected;
selection did not move a head. Physical qualification and Take/Dock recovery
remain outstanding; disabled-event behavior is test evidence, not a live
interrupted-motion exercise.

## Take/Dock reconciliation implementation (local, not installed)

`WMP_RECOVER_TOOLHEAD` accepts only the original physical head, operation ID and
printer session for an unknown Take/Dock result. It requires standalone ownership,
idle state, no unresolved filament operation, coherent attachment sensors, and
explicitly clear stock failure/setup flags. It waits with M400, rechecks those
conditions, and records the observed mounted head or fully docked state. It marks
the original operation stopped/failed with `recovered=true`; it never claims that
the requested action completed, repeats travel, changes heating, or clears a stock
fault. Refusal messages retain the reason for the user.

The native worker supports resuming the original receipt after a screen restart,
separate recovery delivery and readback, and no replay of the original macro.
The existing opaque result modal supplies a Toolhead recovery title and RECOVER
header action. Backend protocol publication and native projection are connected.
Tests cover physical attachment differing from the requested head, stale or
mismatched requests, owners, active jobs, stock faults/setup, unavailable sensors,
changes after M400, lost responses, duplicate recovery clicks and hidden controls.
This remains a local implementation pending final native integration checks,
ARM packaging and guarded deployment; hardware recovery is unqualified.


Release r32 activated successfully while idle, with openACE absent and heater
targets zero. Native SHA256:
`265e7e1086ba9fb678588c11287feb6a1b137457b2f70252d745ca4f1aafc916`;
helper SHA256:
`8117f84399c8c83b83a7d06099ecaa4dbc58f0f22700ed7c79e896f272d50941`.
Review archive SHA256:
`619dc4cd19fe0198bdd02b0995404283b30ed95b6870e80d5d60cf0b5eec3f5a`.
Readiness confirmed the new protocol and rejected an invalid-session
WMP_RECOVER_TOOLHEAD request before commands could run. Rollback backups and
activation evidence are in `activation-stockwidgets-r32/`.

The backend suite plus lifecycle check passed (248 tests), followed by the
30 targeted toolhead cases after refusal-message handling changed. Final native
runtime, transport/readback, projection and lifecycle checks passed; the expanded
runtime restart test subsequently passed for both operation types. ARM build and
packaging passed. No physical tool change, recovery, heating or extrusion was
initiated. Live recovery from a real interrupted tool change remains unqualified.


## Live standalone metadata round trip

On r32, sensor-confirmed empty Head 3 was temporarily configured through
SET_MATERIAL, WMP_SET_BRAND, SET_COLOR and AFC_SET_SPOOL_TEMP using the full lane
key, Tn, numeric and tn forms. Every step matched wm_material canonical identity
readback and the stored JSON. The AFC lane stayed empty with blank material,
brand and color, so saving a future spool did not fabricate loaded filament.
The original profile file was restored byte-for-byte, including its prior
absence if applicable. Identity revision, identities, physical presence,
attachment, session and operation records matched the pre-test snapshot.
Heater targets remained zero; no motion command was used. Evidence:
`activation-stockwidgets-r32/metadata-roundtrip.json`. This proves empty-head
metadata configuration; it does not replace loaded-spool publication acceptance.

Import policy remains unresolved: PLA at an imported 215 C target with a 190–230 C
range can load, but the stock 250 C unload recipe is refused. Unknown material
variants (e.g. PLA-CF, PA6-GF) can be stored but cannot silently inherit a shaping
recipe. Local diagnostics now identify the action/material or required temperature
and conflicting bound. Five focused admission checks pass; these message changes
are not yet installed. No temperature clamping or variant mapping was added.

## Nozzle same-value save verification

A live preflight for four-head Save/readback refused before sending any command:
the old store would normalize `0.400000` to `0.4` even when the diameter did not
change. The local store now compares parsed values first. Unchanged settings
preserve file bytes/revision without writes, and material-only changes leave the
printer.cfg diameter formatting untouched. All 17 store tests and nine targeted
backend/admission checks pass. Live verification awaits installing this change;
this is not evidence of a changed-diameter Save/restart test.


Release r33 activated successfully with unchanged native library
`265e7e1086ba9fb678588c11287feb6a1b137457b2f70252d745ca4f1aafc916`,
wm_material `2a6a0d05b490c9aeaeb87703acca028768c917ac62370e4f6b8541e5ff58e0a7`,
and wmp_nozzles `c33c11f6ca71af76f0e7ca473cffaadae693a80cc569ccbc0390d8d6d7702cc4`.
Package SHA256:
`733b6922c22d43ab262bee852a092152d58464d20441186c6898f9c867be2342`.
The clearer imported-profile diagnostics are now installed; recipe behavior is
unchanged and the unload-temperature question is still pending.

Live same-value WMP_SET_NOZZLE Save/readback succeeded for h0–h3: all remained
0.4 mm Hardened steel, active diameter matched, and restart_required stayed false.
Both printer.cfg and tmt1.ini remained byte-for-byte unchanged, as did session,
identity, physical presence, attachment and operation state. Heater targets stayed
zero. Evidence: `activation-stockwidgets-r33/nozzle-roundtrip.json`. This verifies
command routing, readback and no-op persistence across physical heads; changing a
value and checking persistence after restart remains outstanding.

## Observed versus configured identity in the overview

The local external-source card now uses the loaded head's observed identity,
rather than the source editor's Generic/Unknown/gray defaults. Unknown loaded
identity shows an outlined question-mark swatch and “Unknown filament”; empty
heads retain blank metadata and Load. Valid loaded identity remains visible with
its actual color. The overview layout cache now includes the complete loaded
record, so identity/source changes while the state stays loaded refresh the card.
Native lifecycle checks cover conflicting configured/loaded identities, an
identity-only refresh, and subsequent empty/loaded transitions. Lifecycle and
runtime compilation checks passed; ARM build and live review remain pending.

Release r34 installed and passed readiness on the idle, heater-off printer.
Native SHA256:
`945e115e938f0e1aa3ee031385bff0205f52e6629e59ba7f81bb91e9f8165458`;
review archive SHA256:
`7e2314bdd63cae6ddf2e7f25a06a3ee2f388b28f434e864011a2b63ab441f213`.
All helper dependencies remain r33. Live
`activation-stockwidgets-r34/02-filaments.png` confirms that loaded Heads 1, 2
and 4 show Unknown filament and question-mark swatches, while empty Head 3
shows an empty outline, no identity labels, and Load. No fake Generic brand or
actual-gray color is presented as known metadata. No heating/motion was initiated.

## Direct empty-card Load regression

A live no-motion dialog review on r34 found the empty external card's Load button
was inert. The shared slot-action handler required slot_menu_ to name the source,
but the direct Load button is intentionally outside that menu. The local fix
admits the direct shortcut only for a unique available external source and one
sensor-confirmed empty head with fresh status. Menu actions retain their existing
routing; unavailable direct Load is visibly disabled. Regression checks click the
actual card button without opening a menu and cover unavailable/stale sources.
Initial lifecycle/runtime checks passed. Live reproduction evidence is in
`activation-stockwidgets-r34/03-before-dialog-review.png` through
`05-load-settled.png`. Build/deployment and corrected live interaction remain.

Release r35 installed native SHA256
`057104ccfb6df6729c9f2e5a716c5b797960fa1927397f2a8250ebcac6e01362`.
Live `activation-stockwidgets-r35/03-load-draft.png` and `04-current.png`
confirm that Head 3's direct Load opens the filament configuration modal.
Cancel returns to the overview (`08-cancel-load.png`). Loaded Head 1 offers
Unload (`11-loaded-menu-title.png`), which opens a separate confirmation
(`12-unload-review.png`); Cancel exits it (`13-cancel-unload.png`). Neither
operation was confirmed. `post-dialog-status.json` shows standby, all four
heater targets zero, empty filament/toolhead operation records, and four WM+
lanes matching sensor presence with no stale openACE lanes.

This live review found two additional interaction defects:

- The unknown-color outline intercepts taps instead of opening its card menu.
  Tapping the card title works. The local fix clears the outline's clickable
  flag, matching the existing image swatch. It is not deployed yet.
- The material popup extends to the screen's top and clips an item. A tap on
  visible PC closed the list but left Unknown selected, including after a
  settled screenshot (`05-material-list.png` through `07-draft-settled.png`).
  Popup placement and selection handling still need investigation; this is
  not a successful draft-change/Cancel test.

The unload confirmation also exposed the shared service-context message
“Home XYZ before loading filament”. Local wording now explicitly covers loading
or unloading (and the equivalent Z message). Native lifecycle and all 251
wm_material checks passed together (252 tests). These local changes await the
next build; the selector defect remains open.

## Live selector follow-up

r36 installed the outline tap fix and service-context wording correction.
Native SHA256 `d23589fa00803db775df96070691f8c2ef66e7b7722be4b3916ff1e7f0f374b9`;
wm_material SHA256 `e4843d7b1595eb88fa985a74a8d362a3394886e619d07fa4f162484c0a81c30a`.
`activation-stockwidgets-r36/07-swatch-menu.png` verifies tapping the outline
itself opens the source menu. The same PC selection that failed in r35 worked
in r36 (`05-select.png`), remaining in the draft and enabling LOAD. It was
cancelled (`06-cancel.png`), not executed. The intermittent selection observation
therefore remains unproven as a fixed defect; no selection logic was changed.
Temporary event logging yielded no matching system-journal entries and is removed
from the next candidate.

The next candidate confines open brand/material/profile/assignment lists to the
content rectangle below the modal header. This accounts for the vendor moving
dropdown lists to the screen, outside their original parent. The lifecycle fake
now models a separate screen-parented list and verifies an oversized popup is
contained and stable across cached updates, followed by successful selection.
That regression check and ARM compilation passed. Live placement review remains.

r37 installed native SHA256
`04549c4b52f7711d98512b145931de682401394fb01360e645c388f568aca695`,
archive SHA256 `b0c7d38405747274249d1f497d800e3f7d6febb95aed9debdae0d6a09ea5403c`.
Live `activation-stockwidgets-r37/04-list.png` and `06-reopen-list.png` show the
popup below the modal header instead of covering the tabs. PC and then ASA both
remain selected in the draft (`05-PC.png`, `07-ASA.png`). Cancel followed by
reopening restores Unknown with LOAD disabled (`09-reopen-discarded.png`).
The printer was left on the overview after cancelling again. Final status
(`post-dialog-status.json`) confirms standby, zero nozzle targets, no filament or
toolhead operations, unchanged identity revision and unchanged sensor presence,
source and identity records. Session IDs changed as expected during deployment's
Klipper restart. The initial r35 selection failure did not reproduce in three
subsequent live selections; its cause is not established.

## Nozzle persistence and procedure-description review

The installed nozzle store was exercised on temporary copies of the actual
printer.cfg and tmt1.ini. Each of h0–h3 was independently changed to 0.6 mm /
Stainless steel, then read through a newly constructed store. All four persisted
correctly and left other heads unchanged. Installed files were compared with their
original bytes and remained unchanged. Evidence:
`activation-stockwidgets-r37/nozzle-copy-persistence.json`. This qualifies parsing
and persistence against the printer's real file layout, not live changed-value
Save or Klipper restart/active-diameter acceptance.

Review also found that the shared service plan instructed users to insert
filament even for Unload. Local wording now describes tip shaping and withdrawal
for Unload while retaining the insertion prompt for Load. The 42 selected
service/nozzle/imported-target checks passed. This wording change is not installed
in r37; it awaits the next deployment. Physical sequences were not executed.

r38 installed the description correction in wm_material, SHA256
`90bc10783898c81b7585b6e8c7f7ca1132169c55ea78ded9a1157e47474d9de6`.
The r37 native library was preserved byte-for-byte. Review archive SHA256:
`607afc3e65d95f6d00375ddab9cc54c39fd36fec2cdf3d237727fa2d282ffeee`.
Readiness checks completed and final status confirmed standby, zero nozzle
targets, no filament/toolhead operations, and four WM+ lanes matching physical
presence. Evidence is under `activation-stockwidgets-r38/`.

Outstanding decisions/equipment were requested again after these no-motion
checks: attendance for physical qualification and whether imported Unload should
use preset temperature or retain stock shaping temperatures with range refusal.
Neither answer has arrived at this point. Real USB import also needs a connected
drive/preset. These remain acceptance gaps, not evidence that the goal is complete.

## Changed-value nozzle Save: live ownership defect

A guarded changed-value Save on empty Head 3 failed with EPERM. The original
configuration bytes were restored/verified and all nozzles remained 0.4 mm /
Hardened steel with zero targets. Unlike the temporary copies, installed
tmt1.ini was owned by root:root (0644), while Klipper runs as t13dp:netdev.
printer.cfg belongs to t13dp:netdev; their containing directory is writable by
the service. Atomic replacement could proceed, but preserving root ownership
with fchown could not. This is why copy and same-value tests did not expose it.

The writer now preserves owner/group when permitted and otherwise keeps the
replacement service-owned. File mode is preserved, and no directory permissions
are changed. The regression simulates stock root ownership under the service
user, rejects forbidden chown attempts, and verifies the changed file retains
its 0640 mode. All 18 store tests and 23 selected nozzle checks passed. The
fix is being deployed as r39 before repeating the live Save/restore check.

r39 activated successfully with wmp_nozzles SHA256
`aa30c8bdfe1f918100897051a4ae3e226fa9109641a7d91e1f83fea3cced2855`;
the native UI and wm_material stayed unchanged. Package SHA256:
`6ff0062c23f799e560d2dcc6199c4a97a54b5cee957dd6b106d695af29f004de`.
The repeated live Head 3 Save succeeded: saved 0.6 mm / Stainless steel,
active 0.4 mm, restart_required true. A second real Save restored 0.4 mm /
Hardened steel and cleared restart_required. A guarded restoration then restored
the original file bytes (including diameter formatting), with unchanged identity
revision, sensor presence, attachment and filament/toolhead operation records.
All heater targets remained zero and no restart occurred between the changed and
restored settings. Normal atomic replacement leaves tmt1.ini service-owned rather
than root-owned; file modes and directory permissions are not broadened.
Evidence: `activation-stockwidgets-r39/nozzle-changed-roundtrip.json`.
This closes live changed-value Save/readback; applying a changed diameter through
Klipper restart remains an acceptance gap.


## Nozzle restart acceptance completed

The r39 guarded live test saved empty Head 3 as 0.6 mm / Stainless steel,
restarted the idle services, and verified saved diameter and active diameter
both became 0.6 mm with restart_required false. A second real Save restored
0.4 mm / Hardened steel; exact original file bytes were restored while services
were stopped. After a second restart, saved and active diameter were both 0.4 mm,
restart_required was false, and every other head matched its original settings.
Identity metadata, physical presence and attachment remained unchanged. Heater
targets stayed zero; no heating, extrusion or XYZ motion was requested.

Evidence: `activation-stockwidgets-r39/nozzle-restart-result.json`,
`nozzle-restart-journal.jsonl` and `nozzle-restart.log`. Both restarts reached ready
and the test process exited successfully. This closes the changed-diameter
restart acceptance gap for the tested physical head; the earlier copy checks
covered persistence for all four heads.


## Standalone filament metadata restart acceptance

The r39 live check saved a temporary profile to sensor-empty Head 3 through
WMP_SET_FILAMENT, including brand, material, color, target and temperature range.
After restarting the services, the complete profile was read back unchanged.
The head still reported empty and its AFC lane remained loaded=false with blank
brand/material/color and zero temperatures. Saved metadata therefore did not
invent physical presence during restart.

The test restored the exact original metadata file bytes (or absence), restarted
again, and verified the original metadata revision. Nozzle settings, attachment,
physical presence and operation records remained unchanged; heater targets stayed
zero. Both restarts reached ready and the test process exited successfully.
Evidence: `activation-stockwidgets-r39/metadata-restart-result.json`,
`metadata-restart-journal.jsonl` and `metadata-restart.log`. This proves backend
persistence for the tested empty head, not loaded-head UI Save or an actual
filament load/unload.

## Head 4 identity acceptance and remaining UI checks

User confirmed Head 4 (`h3`) is Kexcelled PLA, “Bluish Gray.” Saved through
`WMP_SET_FILAMENT` with approximate color `#7D8A92`; the current identity schema
stores a hex color, not a color name. Readback and AFC `wmplus_tool_3` publication
match, and the live card shows Kexcelled PLA with the swatch. Targets remained
zero and no physical operation was invoked. Evidence: r39 `head4-saved.json`
and `head4-saved.png`. This was a backend Save, not touchscreen Save acceptance.

The editor brand list currently draws from Generic, existing source identities
and published brands; adding a previously unknown brand directly needs a usable
path. Material-list scrolling during the attempted touchscreen edit unexpectedly
opened the brand list; reproduce and resolve before calling selector acceptance
complete. Home center shortcut taps also failed in this session despite earlier
r20 acceptance; recheck this regression. All placeholder drafts were cancelled
before the real Head 4 metadata was saved.

### r40 installed verification

ARM build, status projection/runtime compilation, native lifecycle checks and
wm_material tests passed. Idle activation completed with openACE disabled.
Live overview has no Import profiles button and retains Head 4's Kexcelled PLA.
Brand list contains all five built-ins plus existing Kexcelled. Selecting Sunlu
and PCTG updated the load draft; PA6, PA12 and PP are also visible. CANCEL
returned to the unchanged overview. No loading, heating or movement was invoked.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r40/`.
One material-field tap did not open the list; tapping its arrow did. The earlier
intermittent touch/selector concern remains unqualified by this limited pass.

## November 6 controller shutdown and readiness correction

After r40 verification, the next live navigation attempt encountered the stock
ZRU-B007 warning. Read-only Moonraker status confirms `webhooks.state=shutdown`
while `print_stats.state=standby`; all four heater targets are zero and no WM+
filament/toolhead operation is recorded. Klipper logs at 14:54:59 report EX_T,
T0–T3 timeouts, followed by mcu, HUB and CELL. The fault needs physical diagnosis;
no restart or warning dismissal was attempted. Live Save/touch acceptance and
physical operation tests remain pending. Evidence: r40 `fault-status.json`.

This exposed a readiness gap: the native poll did not include webhooks and
considered a successful recent status reply actionable even after shutdown.
The r41 local correction explicitly queries webhooks, requires state `ready`
(missing state is unavailable), and gives a clear not-ready refusal in the
standalone command adapter. Regression checks exercise shutdown/error/startup/
unknown states and a request queued while ready then invalidated before dispatch.
The r41 candidate must remain undeployed until the printer fault is resolved.

r41 validation: projection, LVGL lifecycle, runtime compilation, standalone
command delivery/readback and file-preview checks pass; ARM candidate builds.
The candidate is packaged, not installed. Installed version remains r40.

### USB cause confirmed

Read-only topology identifies can0 as gs_usb on USB path 2-1.1, behind the
same hub as the camera. Kernel ring-buffer timestamps correlate the failure:
4069739.632801: usb2-port1 disabled by hub (kernel suggests EMI, not proven);
4069739.637373: CAN USB device disconnected;
4069741.108075: can0 link ready after re-enumeration;
4069743.043601: Klipper EX_T and T0–T3 timeouts, then other controllers.
Thus the fault followed a shared USB hub interruption; the gripper-specific
message does not establish a gripper cable failure. CAN subsequently reports UP,
ERROR-ACTIVE, zero reported bus errors, while Klipper retains shutdown. No firmware
restart or physical operation has been performed during this diagnosis.

## r41 recovery and live Save acceptance

User authorized firmware restart after confirming USB reset history. The initial
preflight found the printer had already changed from shutdown to a failed MCU
automated-reset error; it sent nothing. CAN was up with arriving controller
messages. One explicit firmware restart then returned Klipper ready with all
eight MCU objects present and heater targets zero. r41 was installed through the
ready/idle guarded installer and returned ready again.

Live Home center shortcut succeeded. Through the touchscreen, Head 4's material
was temporarily changed from PLA to PLA Silk and saved, then changed back to PLA
and saved. Both saves were acknowledged onscreen and verified in wm_material
identity and AFC lane publication. Original Kexcelled, PLA and #7D8A92 values are
restored; no physical operation was recorded and heater targets remained zero.
Evidence: r41 firmware-recovery.jsonl, activation journal, ui-save-changed.json,
ui-save-restored.json and screenshots. The overview was left visible.

One list selection tap was missed and succeeded on retry, so touch reliability
is not yet resolved. A new material edit after Save also retained the previous
“Filament settings saved” message; this must change to an unsaved indication.

## r42 material edit notice

Material/profile list changes now replace any previous save-success message with
an unsaved indication when the draft differs from the saved identity. Returning
to the saved material clears the notice. The lifecycle regression covers Save,
new material selection, and reverting that selection; lifecycle and native
runtime compilation checks pass (2 tests). ARM build and review packaging pass.

Intermittent missed remote-injected taps remain under investigation; physical
finger-tap reliability has not been established as affected. Attended heat,
extrude/retract, take/dock and load/unload qualification remains outstanding.

Installed r42 through ready/idle exact-hash guards; activation returned ready.
Live UI verified same-value Save, then a temporary PLA Silk draft displayed
“Unsaved changes” instead of the prior success message. Cancel discarded the
draft and the overview retained Head 4 Kexcelled PLA. Evidence: r42 saved.png,
unsaved.png, final.png and activation journal. All injected taps in this pass
succeeded; this does not establish the earlier intermittent miss is resolved.

## Attended attempt: ACE feeding requested

The user placed Sunlu Matte PLA Pink in ACE slot 3 and requested ACE feeding
because the external spool holders have been removed. Restored only the disabled
openACE include, preserving current printer.cfg changes, with idle/heater-off
checks and rollback. Klipper returned ready with ace0 connected. Topology maps
zero-based slot 2 to h2 (UI slot/head 3, virtual tool 3). The slot reports present
and Head 3 reports no filament. Saved structured vendor Sunlu, material PLA Matte,
color name Pink, approximate display color #F4A3C0, and existing PLA default
220 C. Sensor-only OPENACE_RECOVER HEAD=h2 reconciled its state to empty.

The slot Load menu is visible, but two remote-injected taps did not open a
procedure dialog. A physical tap was requested to distinguish remote-input loss
from UI handling. No load, heating, or motion was dispatched. An unrelated h0
interrupted-path repair record remains untouched. openACE is now enabled; this
ACE-path test cannot qualify standalone hand-fed loading.

## Status flicker investigation (local r43 candidate)

User delegated filament loading and subsequent removal of openACE to the
openACE agent. Read-only checks subsequently found openACE absent from the
Klipper object list; requested openACE fields therefore returned null. This is
an intentional ownership transition, not evidence of a USB disconnect. No
service restart or loading command was issued during this investigation.

The exact stock UI query returned about 198 KB in 381–492 ms (20 samples).
Installed Klipper webhooks.py queues object queries onto a 250 ms refresh timer.
A separate breakdown found even a 125-byte webhooks query takes 143–322 ms,
while Moonraker-only server/info took 19–73 ms. Config settings account for
about 132 KB and saved variables for 62 KB. Scheduling delay is significant;
payload size alone does not explain the latency. The current 500 ms GET deadline
has little margin, but these samples do not prove the original ACE-link flicker
was caused by that deadline.

Local candidate raises only the GET default to 1000 ms; the absolute request
bound and two-second runtime freshness gate remain. A socket regression models
a 650 ms successful status response and a 1700 ms stalled request. This candidate
has not been installed. Avoid deploying while the openACE agent is loading.
Further optimization should separate static configuration from live status,
with explicit invalidation on restart/config changes; do not weaken command
freshness to hide stale data. Evidence: status-latency-r43/*.log.

The r43 candidate runtime compile check passed. The socket regression passed
after allowing its localhost test server outside the filesystem sandbox; the
initial attempt was blocked at socket creation, before exercising transport.

## Retained filament widgets (r43 candidate)

The filament view now reconciles widgets by parent/type/key rather than deleting
all children whenever its status signature changes. Existing cards, menu
buttons, editor fields and dropdowns are updated in place. Removed controls are
retired and navigation to a different editor/view still replaces that view.
Status feedback uses existing headings so a stale poll does not move targets.
Dropdown options are not reset when unchanged; open lists and armed selectors
survive background freshness/connection updates. Callback bindings are reused.
Press/release captures session/routing context and refuses a release after that
context changes. Stale-state admission checks remain in force.

Home retains its full-area navigation target across updates; only noninteractive
decorations are redrawn. Toolhead controls already retain their widgets.
Lifecycle tests cover pointer/allocation stability across fresh/stale and
connection changes, stale-action refusal, open selector preservation and a
routing change between press/release. Lifecycle, runtime compilation and
standalone command transport checks passed; the final lifecycle test including
the context-change assertion also passed. The ARM build and first activation
passed with the printer idle and openACE absent. Live Home navigation,
filament-card menu and editor opening were verified. Live review caught an
empty notice label retaining LVGL's default "Text"; explicit first-text
initialization fixes this, and the lifecycle suite passed again. Final ARM build and activation passed; Klipper returned ready/standby,
with dependencies and configuration preserved. Installed native SHA256:
`6b09ff945a25c567688649df9e93a5bb3b598adbcea7094dedc0e66850aea387`.
Evidence: `activation-stockwidgets-r43-final/activate.log`. Physical touch
reliability under continued use still needs operator observation; status
scheduler latency is unchanged.


## Automatic homing before filament service (r44)

A cold/unhomed standalone head now receives a load/unload plan with a homing
phase rather than a requirement to home manually. The accepted request runs the
installed stock G28 override, waits for motion, checks cancellation, and requires
fresh homed-axis and real Z-reference evidence before service travel. Dock
calibration is checked before dispatch and again after homing; attachment and
clearance are read again because homing may mount the probe head. Already-homed
service keeps its existing path. No synthetic homed flags are introduced.

Backend tests: 262 passed, including unhomed/partial/invalid-reference planning,
homing failure, missing homing readback, changed calibration and cancellation.
Deployed r44 and confirmed Klipper ready/standby. Live plan verification is
blocked by the persisted stock tool-change failure flag `-3` (dock seating or
unlock failure). This guard was not cleared or bypassed. Automatic homing has
passed backend tests but the new physical sequence has not been exercised.


## H2 docking recovery

All four dock sensors were true while the lock sensor was true and Hall was
4577. The saved failure was -3 for physical head index 1. A single isolated
UNLOCK (no XYZ travel) changed the lock sensor to false and Hall to 4817;
all docks remained true and WM+ attachment became empty. With that readback,
saved current_extruder was reconciled to 99 and fail_flag to 0; verified.
The installed echelon_stepper driver catches homing exceptions and logs a
warning instead of propagating the failure. The original failure's root cause
was not established. Evidence: analysis/unified-ui-native/h2-unlock-debug/.


## H3 attended control test and freshness correction (r45)

After the operator fed Sunlu Matte PLA pink to Head 3's gears, its physical
sensor reported loaded. The touchscreen Take action homed and mounted physical
h2, confirmed by dock/lock/Hall sensors and the completed helper receipt. The
numeric target was set to 220 C; only extruder2 heated. The touchscreen 10 mm
Extrude completed, and X set its target to zero. Actual filament motion/output
awaits operator confirmation. This exercises manual control, not a complete
Load sequence from an initially empty head.

Status flicker persisted with retained widgets. Runtime dated each snapshot
from entry to the worker cycle, before legacy polling/list/status requests.
It now dates a snapshot at successful status-reply receipt, before metadata or
command work. The two-second freshness window and failure invalidation remain.
Regression covers a cycle exceeding two seconds, expiry after receipt and
query failure; native lifecycle test passed. ARM build and deployment passed.
Post-deployment navigation and head selection responded on first presses. A
15-second framebuffer sample (30 reads) showed one stable mounted-status
heading, with no unavailable flicker. This is a bounded observation, not proof
against all future transport failures. Head 3 remains mounted, heater target 0.
Evidence: activation-stockwidgets-r45/stability.json.


## Standalone load distance (r46)

At the user's request, the standalone loading feed is now 30 mm at 400 mm/min,
replacing the unmeasured 100 mm default. Updated the procedure description and
execution regression. All 262 wm_material tests passed.

The attended Head 3 test continued with exactly one additional 20 mm step at
220 C (30 mm total including the earlier 10 mm). Attachment/presence, idle state
and session were checked; active extruder was reconciled to physical extruder2
without XYZ travel. The step returned successfully and target 0 was confirmed.
Nozzle output awaits operator observation. ARM build and r46 deployment passed;
Klipper returned ready/standby. Installed wm_material SHA256:
`760f02fe75be0e4fcadc9469a3c4cc21f024737992617854b107da05396ed160`.


## Mounted head versus active extruder (r47 candidate)

The operator reported no filament motion and a contradictory “Mounted - Take
the selected head first” error after r46. Live status confirmed attachment h2,
extruder2 at target 220 C, but logical active extruder was `extruder` after the
Klipper restart. A guarded ACTIVATE_EXTRUDER restored the selection without
XYZ/E movement or changing heater targets. This explains the refused UI request;
it does not establish whether the earlier acknowledged feeds moved filament.

Manual extrusion now validates physical attachment in the frontend and selects
the sensor-confirmed mounted extruder inside the guarded macro before feeding.
A conflicting selection during a paused print remains refused. Regression tests
cover idle restart reconciliation, attachment mismatch, and paused refusal.

ARM build and review packaging succeeded. The macro/frontend regression suite
passed except its loopback socket test was blocked by sandbox permissions; that
case passed when rerun with loopback access. Candidate is not deployed while the
operator is actively testing extrusion with Head 3 target at 220 C. A subsequent
framebuffer read showed “Extruder step completed”; physical motion remains
unconfirmed. Candidate UI SHA256:
`878624a921260f0dbe0453fdf489522b3820f721496a9eea2112ebe8cd092d57`.


## Head 3 homing collision — printer left shut down

The operator confirmed extrusion began after motor selection was corrected,
then used native movement controls because the nozzle was over the wiper.
The unhomed Y jog was refused; the subsequent G28 homed XY and attempted to
switch physical T2 to probe tool T0. G-code history records “The head is not
seated correctly in its dock”, then repeated X-axis homing errors. The stock
_CHECK_CHANGE_TOOL retry clears fail_flag and rehomes XY even after failure -3.
This is consistent with the reported constrained carriage and belt skipping.

Issued Moonraker emergency_stop; printer/info confirmed shutdown, extruder2
power 0 and cooling (cached target remained 220). No recovery motion/restart
was issued. Captured config, klippy log, G-code history and shutdown status in
analysis/unified-ui-native/h3-homing-collision/. Physical inspection is pending.

Local change adds a render-time hard error for failure -3 in both tool-change
and park retries, before clearing the failure or emitting any homing commands.
This prevents the observed automatic retry path; it does not diagnose why the
head failed seating or qualify the mechanism for further movement. Changes
remain undeployed while the printer is shut down for inspection.

Follow-up hardening (local, not activated):
- Wait for the queued dock settling dwell with M400 before reading the switch.
  The log reports docked2 insert 0.65 s after the failed check; this is consistent
  with an early read but does not rule out a seating/calibration problem or a
  switch transition caused by the subsequent retry.
- Abort directly on failed docking, and verify Hall/unlocked switch state while
  stationary before retreating after UNLOCK. Preserve failure -3 and fail_tool.
- Refuse new Home, Take and Park actions while that docking failure is unresolved.
- Apply stationary release verification and sticky failures to standalone
  filament service as well. Tests cover missing dock detection, conflicting
  coupling sensors and non-finite Hall input without retreat or rehoming.

Macro/tool-change/recovery tests passed (three optional fixture skips); all 268
wm_material tests passed. Fresh remote recheck confirmed shutdown, heater power
0, Head 3 cooled to 36.66 C. Candidate installation must preserve the remote
printer.cfg SAVE_CONFIG block and temporary disabled openACE include.

The ARM build and review archive completed. Uploaded all five candidate files
(UI, helper, macros, tool-change macros, and minimally patched live printer.cfg)
to /tmp/wmp-docking-fix-JbsKW8Nh; verified remote SHA256 hashes against payload.json.
No live files were overwritten and no services restarted. The bundle is staged,
not active. The additional successful-release ordering regression also passed.

On-printer staged preflight passed while Klipper remained shut down: its Python
compiled the candidate wm_material.py; ldd -r resolved all UI dependencies with
no missing libraries or undefined symbols. All payload hashes still matched.
Remaining gates are physical inspection/recovery of Head 3, activation of the
prepared bundle, and attended verification of dock release, homing, and the
30 mm standalone loading sequence. No software test establishes those physical
outcomes. The earlier emergency-stop shutdown remains in force.


## Attended Head 3 recovery and r48 activation

Operator confirmed Head 3 seated in its dock with the carriage still attached.
Activated the five-file guarded update from emergency shutdown; exact file
hashes and preserved dependencies/calibration were checked. Klipper returned
ready/standby. Evidence: activation-stockwidgets-r48/activate.log and spec.json.

With ready/idle/cold state, docked2 true, lock true and Hall in the attached
range verified, issued one stationary UNLOCK, settling dwell/M400 and the new
release guard. Fresh readback showed all four docks true, lock false, Hall 4838
and wm_material attachment empty. No XYZ move was part of this release.

Reconciled saved current_extruder to 99 and cleared changing/failure context
only after independent empty-carriage evidence. Sent G28 X Y followed by M400.
It completed successfully; the installed override also established bottom Z.
Readback: ready/standby, homed xyz, position approximately (308.025, 0.9125, 300),
all docks true, lock false, Hall 5114, attachment empty and all heater targets 0.
Operator confirmation of smooth motion is pending; no claim yet that repeated
head pickup/docking or a complete loading procedure has been qualified.


## Normal homing keeps the mounted head (r49 candidate)

Full normal homing now selects its Z reference from Hall/lock/dock-confirmed
attachment before axis movement. An idle mounted head becomes probe_tool; a
truly empty carriage falls back to the existing reference (normally physical
Head 1). Conflicting attachment or a toolhead fault aborts before homing.
START_PRINT passes the physical head explicitly as G28 P<n>, preserving first-print-tool
selection even when START_PRINT is invoked while print_stats is idle. Existing
print/recovery reference behavior remains intact. Automatic filament service
expects the mounted-head datum change while still validating dock calibration
and offsets after homing.

Regression covers each of the four mounted heads, stale saved head state,
relative offsets after normal homing, explicit initial-print tool, empty
carriage fallback and ambiguous-attachment refusal before motion.

Firmware parser verification found that G28 uses traditional letter parameters,
so the final startup wire form is G28 P<n>; the override forwards P to the
selector's extended PROBE_TOOL argument. The recovery test interpreter now
parses G28 with the vendor tokenizer instead of treating it as an extended
command. All homing/recovery and config regressions pass with that tokenizer;
backend tests passed, including intentional versus unexpected datum changes.
The previous r49 intermediate was corrected by r50 before any physical test.

R50 activation passed and Klipper returned ready/standby. Exact deployed hashes
and preserved calibration/configuration are recorded in
activation-stockwidgets-r50/spec.json and activate.log. No physical G28 or
tool-change command was sent during this deployment. Mounted-head homing is
software-tested and installed; attended hardware validation remains pending.


## Physical mounted-head homing test (r50)

At the user's explicit request, mounted physical Head 3 with the guarded Take
operation from a verified empty carriage. Sensors and receipt confirmed pickup.
Then sent ordinary G28 followed by M400, with no explicit probe-head argument.
The command completed; readback confirmed ready/standby, homed xyz, Head 3
still attached, active extruder2, saved current_extruder=2, probe_tool=2 and
position (150,135,7). All nozzle targets remained zero. A mid-operation status
read also reported Head 3 attached. The command-history window has no reported
errors, tool-change message, unlock message or retry. Evidence is saved under
analysis/unified-ui-native/mounted-head-home-test/. This qualifies the tested
normal homing case; it does not qualify every head, docking or filament load.


### Loaded state and unload progress (r51)

Standalone loaded state is persisted per physical head in
`wmp_filament_loaded.json`, separately from spool metadata and live switch
presence. Successful Load sets the flag; successful retraction and a clear
sensor clear it. A present sensor alone never sets it. Unknown sensor readings
retain the saved flag but expose unknown state until readings recover. New
installations without recorded load evidence start unconfirmed/not loaded.
`filament_presence` retains the raw switch observation; `filament_loaded` is
the UI state, with `sensor_present` distinguishing filament awaiting loading.
AFC lane metadata follows the loaded state. openACE remains authoritative for
its loaded state; raw switch presence cannot promote an unloaded ACE head.

The H3 unload reached finishing with a triggered switch after the operator
confirmed that pink filament had fully released. Unload therefore must not
require the switch to clear: successful retraction completes with “Filament
unloaded. Please remove filament.” Load still requires filament detection after
feeding. Heater shutdown remains checked independently, and actual exceptions
are retained instead of being replaced by a generic interruption message.

Progress shows numbered steps, gray completed, orange active, white upcoming,
with live current/target temperature on the heating step. Labels are retained
across updates. Steps are bound to the operation ID, session, and physical head.

Validation: 271 backend tests passed, including persistent flag clearing and
present-but-not-loaded admission; all 33 shared/native UI tests passed (the
loopback transport test was rerun with local socket permission). Nine packaging
tests passed. The ARM candidate hash is
`4e76de19a76365641de3a6ae3f49129ad7f7350cb4196544b4df2e59bcb22edf`.

Deployed r51 with idle/heaters-off preflight and rollback snapshots. Klipper
returned ready and the live screen shows Head 3 offering Load while its sensor
still reports present. No new load/unload motion was used for this verification.
Evidence: `analysis/unified-ui-native/activation-stockwidgets-r51/`.

### Filament service XY-only homing (r52)

Service homes missing X/Y axes with `G28 X Y`, preserving the existing probe
reference. Explicit `G28 X Y` in the WM override skips `z_rise` so it cannot
indirectly bottom-home Z. Full normal/recovery homing remains unchanged.
Service requires a known Z reference for its existing clearance move and
refuses an unknown Z position without dispatching homing or motion. A clearance
move with a known reference is not Z homing. Paused-print filament service is
still blocked; this change does not enable that separate workflow.

### Feed, purge and wipe (r53 candidate, not deployed)

After the operator needed an extra 25 mm beyond the old 30 mm load to reach the
nozzle, standalone Load defaults to 55 mm feed followed by 50 mm purge at
400 mm/min. `[wm_material] load_feed_mm` and `load_purge_mm` independently tune
these lengths. They are included in the validated procedure token. The purge
amount is an initial tuning value, not a guarantee of complete color/material
transition for every combination.

Service Load runs the existing calibrated `WIPE_NOZZLE` after purge and waits
for its moves before heater shutdown and completion. It checks attachment,
active extruder and homed axes again before wiping. Progress has separate Feed,
Purge and Wipe steps. Successful feed establishes the loaded flag; a later
purge/wipe failure keeps that flag and reports the failed stage. A missing wipe
macro refuses the plan before any service motion. Legacy E-only service without
travel support remains E-only; it does not invoke a wipe.

Backend/native lifecycle checks passed, including purge/wipe failure cleanup,
no motion replay, persistent loaded state after a finishing failure, and stale
recipe rejection. Physical purge effectiveness still needs observation. The
XY-only homing change and this load update remain pending deployment while the
operator is using the heated nozzle.

### Layout, focus, and used-filament preview (r54 candidate)

Toolhead controls align at the top/bottom of the main area. Load/Unload share
the Take/Dock width and position; material is a plain label below the brand.
The Toolheads and Filaments / slots view switches share a bottom-right position.
Button captions use centered text across WM+ surfaces, menus, and dialogs.
Field-like selectors are an explicit exception: Brand in the filament editor
uses left-aligned value text matching Material, even though tapping it opens a
dialog. Brand choices inside the selection grid remain centered.
Preview's header action is CANCEL; header actions use uppercase short labels.
Opening a slot menu replaces the previous menu and focuses its assigned head;
entering Toolheads chooses the physically mounted head when known.

The operator's Superbird file contains seven Orca preset entries but only T0 is
used: `filament_used_mm = [16532.5, 0, 0, 0, 0, 0, 0]`, and the only tool command
is T0. Preview now filters unused presets using per-filament length/weight
metadata and preserves original tool indices. Missing usage metadata keeps the
existing conservative preset list; malformed or mismatched usage fails review
rather than silently dropping potentially required tools. Captured evidence is
`analysis/unified-ui-native/superbird-inspect.jsonl`.

Mapping rows also retain each sliced filament's usage estimate and display grams
(two decimal places), falling back to millimetres when weight is absent. These
are slicer estimates per sliced filament, not measured spool inventory or a
physical-head total. Superbird reports 49.31 g for its used T0 entry. Missing
weight is not guessed from length without density data. Native rows expand when
brand, material and usage need three lines.

Validation: full UI suite passed 33 tests before the usage addition; focused
metadata and native widget tests cover sparse indices, weight preference, length
fallback, and the rendered weight label. Deployment remains pending the user's
answer about finishing heated-nozzle work before restarting Klipper.

### Live deployment and preview validation follow-up (r55)

r54 was deployed after confirming standby, completed operations, and all heater
targets at zero. The restart returned ready with Head 3 still physically mounted.
Live preview then exposed the model validator's string-only sliced fields rule:
numeric usage made the snapshot invalid. The validator now explicitly accepts
finite, nonnegative numeric usage fields. An end-to-end metadata-to-App-render
regression verifies the displayed gram estimate. The native cancel control also
needed an explicit width/position to fit CANCEL; its original icon-sized bounds
clipped the new caption. r55 includes both corrections.

Live r55 preview confirmed one Superbird PLA row at 49.31 g and a complete CANCEL
caption. The source button exposed a separate layout timing issue: the shared
caption helper measured new LVGL buttons before layout. r56 forces layout before
measuring caption space; a delayed-dimensions widget regression covers this.
Full UI suite: 33 passed; package checks: 9 passed; final caption lifecycle
regression: passed. Physical feed/purge/wipe behavior remains to be exercised.

r56 activation completed with Klipper ready/standby. Final physical framebuffer
verification shows one Superbird PLA row, 49.31 g, centered Choose source text,
and CANCEL in the header. Evidence:
`analysis/unified-ui-native/activation-stockwidgets-r56/preview.png`.
Installed UI SHA256: b9270230273415effe1f3a30cc757241067622074b96bacee8ee9a3581dc8b6a.
The printer was left on this preview; no print or motion test was started.

### Restart-persistent loaded flags (r57)

After deployment, saved Head 3 metadata remained intact, but its loaded flag was
false. The r54 pre-update snapshot proves Head 3 was loaded before restart; the
other heads were not confirmed loaded. Klipper SwitchSensor starts with
filament_present=False before MCU input arrives. Status/AFC reads could persist
that default as an actual removal. WM+ now reports sensor state unknown until
klippy:ready plus the same two-second settling window used by RunoutHelper, and
again during disconnect/shutdown. Unknown sensor state never clears saved flags.
Real clear readings after initialization still clear the flag; present sensors
still cannot promote an unloaded head to loaded. Backend tests: 282 passed.
Deployment restores only Head 3's previously confirmed flag, with current sensor
presence required, and preserves the metadata file byte-for-byte.

r57 deployed and startup verified: Head 3 remains loaded in both the persisted
file and live filament_loaded status, with Sunlu/PLA Matte/#f5b6cd intact.
Head 4 metadata also remains intact. Klipper returned ready/standby, all targets
zero. Evidence: activation-stockwidgets-r57/after-status.json and activation log.

### Consistent operation stages (r58)

Load/unload already displayed numbered gray/orange/white steps and live heating
temperatures. Take/Dock now opens the same progress dialog, with backend stages
for checking attachment, executing the stock macro, and verifying sensors.
Toolhead and filament recovery publish their own stop/verification stages.
openACE-managed load/unload now publishes the stages WM+ can actually observe;
delegated internal motion is one stage rather than invented substeps. Direct
openACE loading exposes prepare/heat, insertion, feeding and verification.
USB copy shows check, copy and review stages; ACE registration shows registration
and readback followed by assignment review. Profile import remains deferred.
Stages are tied to backend phase/session/request identity, not elapsed time.
Validation: 315 backend/UI tests, 9 package tests, and an additional final native
stage-color test passed. Deployment preserves loaded flags and metadata files.


### G06 material upgrade preservation — local, 7 November

The material installer now retains an existing `wm_material.cfg` instead of
replacing custom settings on each upgrade. Defaults are created only when the
file is absent; unreadable configuration fails installation. Changed Python
helpers are staged before publication, backed up, and individually replaced
with atomic SFTP renames. A publication failure rolls back already-published
files. This is not a filesystem-wide transaction or a guarantee against a lost
SSH connection during rollback; backups remain available for recovery.

Offline verification: **33 tests passed** across material installation and deploy
routing. Cases cover first installation, repeated upgrades, preservation of
custom loading settings and the actual filament JSON/catalogue/INI paths,
upload failure, failure at each publication position, and unreadable settings.
Evidence: `analysis/validation/2026-11-07-material-install/tests.log` and
`hashes.json`. No printer files changed. G06 remains open for current bundle
selection and clean standalone installation acceptance.


### G06 helper preflight coverage — local, 7 November

Material preflight now parses all three installed helpers (`wm_material.py`,
`wmp_orca_profiles.py`, `wmp_nozzles.py`) locally and with the target Klipper
interpreter. Validation does not import helpers or access printer objects.
Seven focused tests pass, including missing/malformed helpers and execution of
the generated parser script. Evidence is under
`analysis/validation/2026-11-07-material-install/` (`material-preflight-tests.log`
and `preflight-hashes.json`).

The broader installer/preflight run still fails three preload tests because the
historical sealed screen bundle does not match current compatibility source.
One test also lacks a `DeployError` stub and obscures that rejection. This is
recorded in `installer-tests.log`; the bundle integrity check has not been
weakened or resealed to hide the delivery gap.


### Current combined regression and isolated rebuild — 7 November

All **286 tests** in `tests/test_config_macros.py` and
`tests/test_print_recovery.py` pass on the latest local calibration/probe changes,
including the later result-save guards. This supersedes the earlier partial
runs as combined software evidence, without adding their counts together.
Logs/source hashes: `analysis/validation/2026-11-07-stock-callers/`
`current-combined-tests.log` and `current-combined-hashes.json`.

The current review archive was extracted into a fresh temporary directory and
rebuilt using only its exported source tree and the pinned offline Docker image.
The rebuilt binary is byte-identical to candidate
`3b155febb6074978ffaf86b300888c2c558d3f6b28b027963ccc3f1dccbdb1f6`.
Source hashes, runtime-dependency hashes, build ID and toolchain identity also
match. Evidence: `analysis/validation/2026-11-07-isolated-rebuild/`.
This proves the current review archive's reproducibility; it does not promote
that archive to an installable release or complete physical acceptance. r67 is
still the installed printer build. G06 remains open for installer integration.


### G06 restart readiness — local, 7 November

Preload installation previously checked only `systemctl is-active` four seconds
after restart. It now polls both service and `/printer/info` for up to 120 seconds.
When the backend was initially Ready, success requires observing its restart
transition or a changed process ID; an old Ready response alone is insufficient.
Two consecutive Ready samples with the screen service active complete the check.
Startup failure raises through the existing publication rollback/recovery path.
No restart was performed on the printer for this change.

The focused readiness/deploy run passed **30 tests**. A broader publication run
also exercised rollback/publication tests, but **eight historical-bundle tests
still fail** at the known sealed compatibility-source mismatch. These failures
remain visible; they are not physical-test failures or successful integration.
Evidence: `analysis/validation/2026-11-07-preload-readiness/integration-tests.log`
and `hashes.json`. Current package selection, matched backend verification and
clean installation acceptance remain outstanding.


### G06 unified package selection — local, 7 November

Installer selection, staging and remote dependency preflight now support a
separate `client-preload/unified-screen1113` package. When present it takes
precedence over the historical screen package; invalid/incomplete new packages
fail rather than downgrade. A missing new package preserves the existing
historical selection. The new location is outside the compiled source tree,
avoiding recursive build-ID/package-manifest dependencies.

Source verification for this package covers the current unified UI, inherited
native sources, compatibility C source, verifier and runtime dependency contract
(including all ten backend/config baseline files). It retains artifact/profile,
ELF, archive-member, source-hash and delivery-scope checks. No historical archive
or descriptor was resealed, and no current release package was published into
the repository's selected package location.

**43 tests passed** across current-package selection/source verification,
readiness and deploy routing. Tests use the actual local AArch64 candidate in a
control-only temporary package, so they do not claim release or hardware
acceptance. Evidence: `analysis/validation/2026-11-07-current-delivery/`.
Remaining G06 work includes package export/promotion, target backend matching,
configuration reconciliation and clean installation acceptance. Printer remains
on r67.


### G06 current delivery exporter — local, 7 November

`tools/package_unified_ui_delivery.py` now exports the verified current candidate
into a separate staging tree, with a descriptor, deterministic source archive,
source-input manifest, candidate provenance and matching backend/config baseline.
It validates the exact vendor client against the compiled profile, refuses
changed build/runtime inputs, and verifies the completed tree using the normal
installer verifier before publishing it. Existing output directories are not
replaced; failed publication removes temporary output.

**18 exporter/selection tests passed.** Two exports produce identical descriptor,
source-manifest, source-archive and artifact bytes. The real current candidate
was exported to `/tmp/wmp-current-delivery-export`; evidence and descriptor copies
are in `analysis/validation/2026-11-07-delivery-export/`.

The exporter intentionally emits a control-only package, which the installer
refuses to activate. It is not a clean-install acceptance result or a release
promotion. Target backend/configuration matching, release installation and
physical qualification remain open. Printer remains on r67.


### G06 installed backend helper matching — local, 7 November

Before publishing a selected unified UI package, the installer now checks the
installed `wm_material.py`, `wmp_orca_profiles.py`, `wmp_nozzles.py` and
`wmp_recovery.py` against the package's digest-validated source manifest.
Missing/mismatched helpers stop activation with an instruction to install the
matching config/material components. The normal component ordering installs
those before preload. This check reads installed code; it does not rewrite
configuration or saved filament data and does not prove loaded-object behavior.

**28 current-delivery/export tests passed**, covering each missing/changed helper,
data preservation, and the actual staging/install path refusing a mismatch
before library publication, service override changes or restart. The install
path test isolates firmware/loader selection and uses a local fake printer; it
does not execute the native library or contact the printer. Evidence:
`analysis/validation/2026-11-07-backend-match/`.

Configuration/macro reconciliation and post-restart runtime acceptance still
need validation. No release scope changed and r67 remains installed.


### G06 active macro/configuration matching — local, 7 November

The installer now stages digest-verified macro/config baselines separately and
checks the printer's active include tree before publishing a unified screen.
The read-only check requires `[wm_material]`, `[wmp_recovery]`, expected macro and
delayed-G-code bodies, homing override, rename/axes options and declared macro
variables. It follows sorted include expansion and linear overrides, so merely
having a current but unincluded macro file cannot satisfy activation.

Hardware settings, calibration, material tuning and existing macro variable
values are retained, not overwritten by this check. Variable presence is checked;
custom variable values and physical behavior still need runtime qualification.
An executable macro difference causes a mismatch instead of silently rewriting
user code. Source baselines are not a whole-printer overwrite list.

**35 current-delivery/export tests passed**, including preservation of tuned
probe position and loading distance, later-include overrides, missing/recursive
includes, missing helper configuration and modified package baselines. A parser
parity test executes the shipped WM 1.1.13 Klipper configuration parser against
the same include/override/comment fixture. Evidence:
`analysis/validation/2026-11-07-config-match/`.

No printer files changed. Full clean installation, post-restart object checks,
release promotion and attended physical acceptance remain open.


### G06 running backend acceptance and rollback — local, 7 November

After restart readiness, current-package installation now queries
`wm_material`, `wmp_recovery` and registered G-code commands before reporting
success. It requires the six material/toolhead/print protocol versions used by
the UI, a material session, four-head presence/loaded-status maps, recovery
booleans and ten required commands including `_WMP_PROBE_CALIBRATE`. This is a
read-only API check; it does not home, heat, move or submit any command. It does
not require homed axes or a legacy INI to accept a fresh standalone installation.
It establishes loaded API capability, not physical sensor or motion correctness.

**81 tests passed** across backend acceptance, restart readiness and current
package delivery. The installer-path test now covers failure after publication:
it restores previous screen-library bytes and the service override, and invokes
the restart recovery path. Tests isolate firmware/loader/service operations and
use a local fake printer; no native ELF is loaded and no printer is contacted.
Evidence: `analysis/validation/2026-11-07-backend-acceptance/`.

Live activation/acceptance of the matched candidate, release package promotion,
clean standalone installation and remaining attended checks are still open.
Printer remains on r67.


### G06 live read-only comparison and include-order correction — 7 November

The printer was queried read-only: Ready/standby, four nozzle targets zero, no
filament operation, all four installed Python helpers matching the current
candidate. Saved loaded-state and filament-metadata hashes still match the r67
baseline. `_WMP_PROBE_CALIBRATE` is not yet loaded, as expected for r67.

This audit exposed a checker defect: the expected baseline was assembled in a
fixed component-file order, while WM intentionally overrides five duplicate
calibration macros through printer.cfg's include order. Baseline comparison now
follows that order too, limited to package-owned contract files. The corrected
live audit removes those five false positives. **78 tests pass**, including a
regression asserting the actual duplicate macro definitions select the later
`change_macros.cfg` version.

The actual configuration delta is ten macros in two files: the new probe entry
in `macros.cfg`, plus nine corrected calibration macros in `offset_calibrate.cfg`.
Exact before/after hashes, review patches, initial/corrected audits and tests are
in `analysis/validation/2026-11-07-live-delivery-audit/`. Parsed non-macro sections
are identical, so this proposed update preserves calibration and hardware
settings. `change_macros.cfg` and `fz-wipe-nozzle.cfg` already match byte-for-byte.
No target files were changed or services restarted in this audit. Matched UI/
macro activation and subsequent live acceptance remain outstanding.


### r68 matched activation and live navigation acceptance — 7 November

Activated native UI SHA256
`3b155febb6074978ffaf86b300888c2c558d3f6b28b027963ccc3f1dccbdb1f6`
with the reviewed `macros.cfg` and `offset_calibrate.cfg` changes. Exact idle/cold
and source-hash checks ran immediately before publication; both services were
stopped before replacing the three files. Klipper returned Ready after about
44 seconds. All 15 preserved files retained their hashes, including printer.cfg,
filament metadata and loaded flags. The new physical-head probe command is
registered. Post-activation audit reports zero active macro mismatches and four
matching helper files. OpenACE remains absent.

Live UI checks: home, Settings, Filament, General, Maintenance, then Feed &
Discharge back to shared filament cards. Head 3 still displays pink Sunlu PLA
Matte and is loaded; other heads display empty circles and Load. Before/after
navigation evidence confirms no new G-code, no position change, zero nozzle
targets, no filament operation and unchanged persisted filament hashes.
No calibration, homing, heating, extrusion or load/unload action was submitted.

Evidence and exact rollback/preflight journal:
`analysis/unified-ui-native/activation-stockwidgets-r68/` (after-audit.json,
navigation-verification.json, screenshots and activation journal). This targeted
activation is not a normal clean installer qualification or physical calibration
pass. G01–G03, G05 physical/worker qualification and G06 release installation remain
open; one of six named release-gap categories remains closed.

### G01 runout callback corrections — local, after r68

The four physical-head runout callbacks now schedule a delayed check only for
the active head during an unpaused print. Reinsertion cancels that timer during
printing as well as at idle. At execution, the delayed callback rechecks print
state, pause state, active physical head, sensor enabled state and filament
absence before invoking the normal PAUSE path. This prevents a stale callback
from pausing after reinsertion, a head change or print termination. It does not
add automatic loading, heating or motion on insertion.

Actual configuration-template tests cover all four heads and these transitions
in `tests/test_runout_sensor_callbacks.py` (68 cases). The existing native
automatic-purge and pause-cancellation guard tests also pass together with them
(78 cases total). These are offline checks, not an attended runout acceptance.

The current delivery source contract now includes all four extruder configuration
files. Configuration acceptance checks their filament sensor callbacks and
`pause_on_runout` as well as delayed macros, while leaving sensor pins and other
machine-specific settings alone. A new build/export is required before delivery;
the installed r68 runtime remains unchanged. Native replacement prompts and
attended pause/runout/return-position validation remain open under G01.

### G01 paused filament invitation — local, after r68

Added a native invitation when a fresh standalone snapshot identifies a fully
paused print, a valid captured pause/head context, and an empty head. CLOSE
dismisses it for that pause; LOAD navigates to the existing shared load review
for the captured physical head. Neither button submits movement, heating or
Resume. The prompt is withheld during existing service operations/editors and
after that pause has already been serviced. It does not take ownership from
openACE. Status refreshes retain the existing objects rather than recreating
the prompt; stale context, resumed printing or changed ownership removes it.

Native lifecycle tests exercise dismissal, review routing to Head 3, repeated
status, stale status, a new pause, changed backend session, resumed printing,
openACE ownership, already loaded/serviced heads, active operations and an event
from an old screen. Runtime compilation and those lifecycle tests passed.
This is local implementation evidence only. Build/export and live visual
acceptance remain pending, as does attended runout/load/resume qualification.

Follow-up validation: all 33 `tests/test_unified_ui.py` cases passed (32 in the
restricted run; the localhost transport case passed separately with socket
access). The ARM candidate built successfully with SHA256
`78cc90ec862a810dc274787568d18d79efed3feed99a2495c5df84a73b3b4e33`.
Review packaging verified its compiled inputs and all 14 runtime dependencies;
archive `/tmp/wmp-r69-review.tar.gz`, SHA256
`0309351c6b7da53ca702197ad47b325478802d975964eba13c5901f5b23cf41b`.
Build and review export are now complete for this candidate; deployment, live
visual acceptance and attended runout/load/resume remain pending. Installed r68
is unchanged.


### r69 matched activation — 7 November

Activated UI SHA256
`78cc90ec862a810dc274787568d18d79efed3feed99a2495c5df84a73b3b4e33`
and the four heads' runout/insert/delayed callbacks. Each configuration payload
was merged into the freshly read live file and parsed to prove that every
unrelated option was unchanged. Five files changed; seventeen tracked files
retained their hashes, including both saved filament JSON files. Klipper returned
Ready after about 44 seconds, idle and cold. No motion/heating command was sent.

The initial audit flagged eight differences caused by comment-derived blank
lines. All twelve sensor callback bodies had identical nonempty lines. The
configuration verifier now ignores only empty lines in these eight fixed sensor/
delayed sections, retaining command order and every nonempty line; other macros
still use exact comparison. Its 37 tests pass, including rejection of changed
conditions, commands and added motion. A repeated live audit reports zero
mismatches and four matching helper files. This comparison change did not require
another printer restart or alter the installed UI artifact.

Evidence: `analysis/unified-ui-native/activation-stockwidgets-r69/`, including
callback-only diffs, before-file copies, exact publication/rollback spec,
activation journal, and both initial and corrected read-only audits. This is a
targeted activation, not clean-installer qualification. Attended paused prompt,
runout, replacement, Resume and physical return-position acceptance remain open.

Live r69 navigation passed Home → Settings → Filament → Toolheads. The
filament page retains pink Sunlu PLA Matte on Head 3; Toolheads defaults to
mounted Head 3 and shows Loaded with the correct nozzle information. Before/
after evidence confirms no new G-code, unchanged position and saved filament
files, zero nozzle targets and no filament operation. Screenshots and
`navigation-verification.json` are in the r69 activation evidence directory.


### G05/G06 follow-up — local, after r69

All 131 current delivery/export/material/readiness/runtime-acceptance tests pass
against the r69 candidate and its 14 runtime dependencies. This does not promote
the package from review-only scope or prove a normal clean installation.

The calibration audit then found and corrected `G29`'s entry-snapshot/axis test:
it could skip Z homing when XY was already homed, or probe with a different
head's established reference. The local candidate now establishes physical Head
1 through `G28 P0` before heating/probing, rejects active prints/tool faults/
recovery, and names the physical nozzle heater explicitly. All 307 macro/recovery
tests pass, including 21 new cases. Evidence: stock-callers
`g29-reference-tests.log` and `g29-reference-test-inputs.json`.

A separate confirmed PID-worker mismatch remains: its `Tn` selection is logical,
while `PID_CALIBRATE HEATER=extruderN` uses the physical loop index. Exact call-site
provenance is in `pid-physical-selection-audit.json` and the non-filament audit.
This is the next G05 correction; PID and physical calibration are not accepted.
The printer remains on r69. The local G29 change is not built or deployed, and
invalidates the prior candidate's source/runtime match until rebuilt.


### G05 physical PID selection — local r70 candidate

The native sender wrapper changes commands only from the exact verified PID
selection call site (BL at `0x4b7cb4`, return at `0x4b7cb8`). Its T0–T3 commands
become `_WMP_CALIBRATION_TOOL T=0..3`; every other command source passes through
unchanged. The backend command validates the physical index and rejects active
prints, tool faults and unresolved recovery before `_CHANGE_TOOL`. It adds no
homing/heating/extrusion. The stock worker retains its subsequent centre move,
physical heater PID request and cleanup. Installer runtime acceptance now requires
the new backend command, preventing a screen/backend mismatch.

Validation: 322 macro/recovery cases, 42 backend acceptance cases, eight PID
routing/profile cases, and two native compile/lifecycle cases pass. Six of the
PID cases emulate the actual built ARM wrapper through its first C++ library
call, proving original-LR routing for valid/invalid PID inputs and other callers.
The exact vendor sender prologue is stack/register-only and its 32-byte window
plus the call site are bound in the native profile. Evidence and input hashes:
`pid-correction-inputs.json`, `pid-sender-wrapper.asm`, `pid-and-calibration-tests.log`,
`pid-native-tests.log`, `pid-native-build.log` under the stock-callers directory.

ARM candidate SHA256:
`f2dc9a6bfa587ba4bd9e94f64af102ecbb7bfa1c865ce4a5c9d56183949b51df`.
It includes the local G29 correction. It is not deployed; printer remains r69.
Live calibration and the remaining full-worker/cleanup audit are still open.


### r70 matched activation — 7 November

Activated UI SHA256
`f2dc9a6bfa587ba4bd9e94f64af102ecbb7bfa1c865ce4a5c9d56183949b51df`
and macros SHA256
`d486d53e40cf7b83ba3c3f1e6c32914bc9ca59b5029897d759b25347845c7129`.
The parsed macro diff contains only the new `_WMP_CALIBRATION_TOOL` section and
G29 changes. Two files changed; twenty tracked files retained their hashes,
including the four extruder configurations and both persisted filament files.
Exact idle/cold/hash checks passed before service shutdown. Klipper returned
Ready after about 42 seconds, with the new calibration command registered.

The post-restart audit reports zero active macro/sensor-callback mismatches and
four matching backend helpers. Read-only process memory inspection confirms the
sender-entry jump at `0x614338` points to `unified_command_sender` in the loaded
r70 library. It neither invokes the function nor starts PID calibration. Heater
targets remain zero, no filament operation is running, and loaded/metadata hashes
are unchanged. Evidence, backups, exact two-file diff and activation journal:
`analysis/unified-ui-native/activation-stockwidgets-r70/`.

This accepts installation and loaded integration only. Physical PID calibration,
bed probing, paused replacement and the remaining worker/cleanup paths are not
claimed as validated. G01–G03, G05 and G06 remain open.

Live r70 navigation passed Home → Settings → Filament → Toolheads. Head 3
retains pink Sunlu PLA Matte, Loaded, and mounted-head selection; nozzle data
remains correct. `navigation-verification.json` confirms no new G-code, no
position change, zero nozzle targets, no filament operation and unchanged saved
filament files. The four screenshots are retained with the activation evidence.


### Local calibration command failure guard — after r70, not deployed

The local ARM candidate now routes all sixteen verified direct calibration-worker
command sends through `_WMP_CALIBRATION_COMMAND`. The existing PID selection
rewrite still resolves physical heads before encoding. Ordinary senders remain
unchanged, and each new call site is included in the exact-client byte profile.

The command is registered by wmp_recovery. It admits only the worker's bounded
command vocabulary, rejects active/paused printing, and checks the tool failure
flag before and after execution. A raised error or reported tool fault latches
failure for this Klipper instance. Subsequent stages, docking and SAVE_CONFIG
are rejected even if another macro clears the vendor flag. An execution failure
turns heaters off without recovery motion. Invalid/unsafe admission does not
change heaters. A restart is required after a latched failure.

Local validation: 123 focused backend, ARM characterization/entry, host routing,
installer acceptance and package/export checks pass. ARM build succeeds with
SHA256 `176567b386b54a462c787984462d60e94ba3e651232fdbf7871d7d8b8f250778`.
Evidence: `analysis/validation/2026-11-07-stock-callers/calibration-guard-*`.
This is not deployed: r70 remains the active printer build. Before deployment,
finish stock screen error/termination behavior review, cleanup-failure handling,
and broader recovery/native regression coverage. No physical calibration has
been run as part of these checks.


### Calibration guard cleanup and status follow-up — local, not deployed

Heater-cleanup failure now invokes Klipper shutdown while preserving the original
calibration exception and failure latch. Invalid encodings and unsafe entry remain
non-dispatching and do not change heater targets. The original stock temperature
preset table was read from the verified ELF: all 18 entries across all four heads
are accepted (72 NOZZLE_PREPARE combinations).

Runtime polling now includes wmp_recovery when available; status projection keeps
calibration_failed/calibration_active for both ownership modes. Maintenance entry
rejects either a running calibration or a retained calibration failure. This does
not yet replace the stock completion screen: its refresh uses auto_checked stage
counters for completion icons/labels, independently of the backend failure latch.
The exact refresh disassembly is saved as calibration-refresh.asm. Correct that
presentation before deployment; do not treat the admission gate alone as the UI fix.

Validation: 37 backend guard cases pass; three native runtime/lifecycle/projection
checks pass; 322 macro/recovery cases pass. Evidence logs and input hashes are
calibration-cleanup-backend-tests.log, calibration-status-native-tests.log,
calibration-guard-recovery-tests.log, calibration-cleanup-status-inputs.json under
the dated stock-callers validation directory. The previous candidate ARM hash
predates these latest edits and must be rebuilt. Printer remains on r70.


### Calibration failure/stale panel — local candidate, not deployed

A verified constructor hook now attaches a read-only status panel to the stock
calibration page. A backend failure covers the vendor progress/completion content
with the cause and restart guidance. BACK navigates to Maintenance, never exposes
the underlying completion ticks by dismissing the panel, and submits no machine
commands. Unavailable/stale status displays that completion cannot be confirmed.

Failures are retained across stale updates and filament ownership changes; only a
fresh, different calibration_session from a new Klipper instance clears them.
The backend now supplies this independent session ID. Runtime polling and installer
acceptance require the corresponding status contract. Parent deletion, screen
changes, repeated updates, stale button events and session changes are exercised
by the native widget harness. The constructor entry's 16 relocated bytes are
profile-bound and verified to contain only stack/register instructions.

Validation: 138 focused backend, exact ARM/profile, installer and packaging cases
pass; native compilation/lifecycle/projection and loopback HTTP checks pass.
Earlier 322 macro/recovery cases remain the backend macro regression evidence.
Current local ARM SHA256:
`13fe359931043595fc4b486c3384ec535cc6081f7a4f12b7a69880b9331e9f80`.
Review archive `/tmp/wmp-calibration-panel-review.tar.gz`, SHA256
`a70bf1333862d0a720e8cad608d12d0ffb505d67af05a34631a9d3c77549a89a`.
Evidence: calibration-panel-* in the dated stock-callers validation directory.

Printer remains on r70. Next: idle/cold deployment with matching helper/UI,
read-only live acceptance and calibration-page navigation without START; retain
attended calibration qualification as open. These checks do not constitute a
successful physical calibration or close G05.


### r71 activation and passive live acceptance — 7 November

Activated the matched calibration guard and status panel after confirming Ready,
standby, no pending operations, all heater targets zero and actual temperatures
26–28°C. Only the native UI library and wmp_recovery.py changed; twenty tracked
configuration/helper/state files were preserved byte-for-byte. Backups and exact
preconditions were checked before publication. Client/Klipper restarted and
returned Ready in approximately 44 seconds.

Installed UI SHA256:
`13fe359931043595fc4b486c3384ec535cc6081f7a4f12b7a69880b9331e9f80`.
Installed recovery helper SHA256:
`fa98e2c1b061a612ce4e16c50c2c27be8b2bbfffcd2298649440cab8ddef8dff`.
Both command-sender and calibration-constructor hooks were read from the live
process and point to the matching loaded library. All four helper hashes match;
active macro/sensor contracts have zero mismatches. The new command is registered,
calibration session is present, failure empty and active false. openACE is absent.

Home → Settings → General → Maintenance → Feed & Discharge → Filaments →
Toolheads passed visually. Mounted Head 3 is selected, with pink Sunlu PLA Matte,
Loaded state and 0.4 mm hardened-steel nozzle retained. Maintenance's lower list
shows PROBE_CALIBRATE beneath Feed & Discharge. Neither START nor PROBE was used.
Position, zero heater targets, both persisted filament hashes and command history
were unchanged through navigation; no filament operation was created.

Evidence: `analysis/unified-ui-native/activation-stockwidgets-r71/`, including
activation journal, live audit, hook readback, screenshots and before/after
navigation verification. This does not live-qualify the new failure panel: doing
so through its normal entry requires a calibration operation. Hardware calibration,
remaining caller coverage and the other checklist gaps remain open. Printer left
idle on Toolheads, Head 3 selected, heaters off, axes unhomed after restart.

### G06 follow-up: configuration restoration after a later component fails

Inspected the normal installer orchestration: all selected components preflight
before publication, but a later component failure currently leaves earlier
successful components installed. Preload restores its own library/drop-in set;
that does not restore configuration and helper changes published before it.
G06 remains open, and this is not a qualified whole-install rollback.

Added a local `reconcile_screen_config.restore` primitive for a successful
configuration publication. It validates the reviewed plan against its retained
journal and backup bytes, limits writes to the two managed destinations, rejects
linked destinations/receipts and concurrent edits, restores in reverse order,
checks readback, and records an explicit unconfirmed state on interrupted
restoration. Retrying a partially completed restoration is supported. It does
not restart services and is not yet wired into cross-component orchestration.
The caller must coordinate helpers, libraries and service recovery before
admitting operations; blindly restarting the old UI over newer configuration
is not sufficient.

Validation: 75 tests passed across `test_screen_config_reconcile.py`,
`test_deploy.py`, and `test_material_install.py`. New cases cover successful and
repeated restoration, absent managed files, bad backups/journals, linked paths,
concurrent changes before/between writes, lost write acknowledgements, retry,
and a no-change publication. All used disposable local files. No printer files,
services, heaters or motion were changed. Deployed runtime remains r74.

### G06 follow-up: configuration component rollback receipt

Unified configuration installation now returns a detached reviewed-plan receipt,
its remote backup location, and the helper publication receipt. Its explicit
rollback executes the self-contained remote configuration restoration first and
only restores the five helpers after a confirmed `rolled-back` response. Lost,
malformed or unconfirmed remote responses retain those helpers. Neither the
restore script nor this component callback restarts a service.

Validation: 82 tests passed across configuration reconciliation, deployment and
material installation. Added isolated subprocess execution of the shipped
restoration script and fresh/upgrade tests using actual helper staging, backup,
rename and restoration on a filesystem-backed SFTP adapter. Both restore exact
original configuration/helper/state bytes and tolerate a repeated rollback.
The tests still model transport and do not exercise printer services.

Cross-component orchestration remains outstanding. Inspection also confirmed
that touchscreen `scripts/install.sh` changes nginx, services, a Moonraker webcam
and the timelapse camera setting; its uninstall explicitly does not restore the
previous timelapse setting. It must not be treated as an adequate rollback
callback. Preload currently restores/restarts its own files inside its exception
handler, so whole-install recovery must coordinate that restart with backend
restoration. No deployment or printer interaction was performed; runtime remains
r74 and G06 is open.

### G06 follow-up: backend recovery coordinated with preload failure

The installer now retains successful configuration/material receipts and restores
them in reverse order when a later install step fails. It stops at an
unconfirmed dependency restoration, defers rollback if a print became active,
and retains helpers when a legacy configuration install has no rollback receipt.
Preload activation failure stops the candidate client before restoring libraries,
then restores earlier backend publications before restarting the old client.
If stopping/restoration/service recovery fails, it retains the journal and blocks
an outer installer fallback from independently rolling back backend files.

Validation: 117 focused tests passed across deployment, preload packaging,
configuration reconciliation and helper installation. New lifecycle cases use
real staged library/drop-in writes with modeled service operations, checking the
stop → library restoration → backend restoration → previous-client restart order
and suppression of restart after backend restoration failure. Routing tests cover
reverse receipt order, dependency failure, print-active refusal, legacy config
admission and a later component failure invoking backend rollback.

The historical preload tests previously paired the sealed historical library
with current edited source files. Their disposable package now obtains all
historical source inputs from the original sealed archive, retaining the original
descriptor/hashes. Tests no longer pass dependency rejection merely because that
unrelated source mismatch causes an earlier failure. No release artifact was
resealed or promoted.

This is not full installer qualification: touchscreen external settings/services,
final standalone Klipper-restart failure recovery, interrupted installer recovery
across process loss, and actual clean-install/upgrade acceptance remain open.
All checks were local. Runtime remains r74; no printer service was restarted.

Follow-up delivery/readiness regression checks: 63 tests passed across
`test_preload_readiness.py`, `test_current_screen_delivery.py`, and
`test_unified_delivery_export.py`. The runtime-mismatch fixture now models the
new service-stop operation alongside its existing modeled restarts; library and
configuration operations remain actual disposable filesystem writes.

### G06 follow-up: final backend restart verification and recovery

Replaced the final installer restart's string search for `"state": "ready"`
with parsed status and explicit restart evidence. An initially ready backend must
show startup or a changed process ID before two consecutive Ready samples count
as success. A network gap is not transition evidence. Lost POST acknowledgements
are observed without resending the restart command. Readiness checks are bounded
by a monotonic 120-second deadline.

A successfully activated preload component already restarts and verifies Klipper,
so the installer no longer schedules a redundant final restart for earlier
configuration/material changes. If a standalone final restart fails and backend
receipts exist, the installer attempts guarded restoration and at most one restart
of the restored backend. Unconfirmed restoration suppresses that recovery
restart. Even successful recovery retains a failed installation result.

Validation: 135 tests passed across deploy, deploy-restart, preload readiness,
preload packaging, config reconciliation and helper installation. A subsequent
47-test routing/readiness run also passed after expanding successful versus
failed recovery-startup coverage; these runs overlap and are not additive.
Cases include unchanged PID/stale Ready, startup transition, changed PID,
compact JSON, network interruption, lost POST reply, existing backend error,
redundant-restart suppression and unconfirmed rollback.

These tests model Moonraker/service responses; no printer commands were sent.
The normal installer still needs touchscreen rollback, process-loss recovery,
and clean-install/upgrade validation on a printer. G06 remains open and runtime
remains r74. The earlier final-restart gap now has a local implementation and
fault-path coverage, not live qualification.

### G06 follow-up: preserve edits during preload restoration

While auditing touchscreen rollback reuse, found that the existing preload
restoration unconditionally copied backups over destinations or deleted new
files. Corrected this before extending that pattern: publication receipts now
record before/after hashes and resolved destinations; restoration validates all
receipts/backups/current files before mutation, rechecks each destination while
restoring, and verifies final bytes. Changed destinations, links, damaged backups,
old journals without verification data, and pre-existing temporary paths refuse
restoration instead of overwriting unrelated edits. A successful restore is
repeatable, including retry after a rename completed but its response was lost.
Publication also checks destination state against its backup before replacement.

Validation: 77 preload/restoration/current-delivery tests passed, followed by
57 restoration/deploy/restart/readiness tests after adding lost-rename-response
coverage. Runs overlap. Tests use disposable files and modeled service calls;
there were no printer interactions. The legacy sealed release remains unchanged.
Touchscreen transaction coverage and the other G06 gates remain outstanding;
this closes a newly identified local rollback overwrite defect, not G06 overall.

### G06 follow-up: touchscreen camera transaction

Read the actual installed Moonraker `webcam.py` and `timelapse.py` over SSH
without executing printer commands or changing settings. Saved the source under
`analysis/validation/2026-11-07-touchscreen-rollback/`. Confirmed that camera
updates accept an existing UUID, reject configuration-owned webcams, and generate
a server UUID for a new camera. Timelapse GET returns its settings and POST can
change only `camera`; other capture/motion options need not be touched.

Added `tools/touchscreen_settings.py` with prepare/apply/restore operations and
required checkpoint callbacks. Existing camera identity and custom extra data are
preserved. A unique ownership token identifies a new webcam after a successful
creation whose response was lost. Restoration compares the full expected camera
and selection before mutation, preserves later edits, restores the original
selection, and supports retry from the last saved checkpoint. It refuses a
missing/ambiguous print camera and configuration-owned Touchscreen entries.

Validation: 15 local API-model tests passed: new/existing camera restoration,
UUID preservation, lost camera/selection responses with process-state loss,
concurrent edits and replacement UUIDs, lost restore responses, checkpoint
failure before mutation and unsupported states. These model the inspected vendor
endpoint behavior; they do not prove a live settings round-trip. The module is
not yet connected to installer mutations: durable receipt storage, file/service
coordination and stopping the boot-time timelapse fixer before restoration still
need integration. The existing installer path remains unchanged by this module.
No printer settings or services changed. G06 remains open.

### G06 follow-up: journaled touchscreen transaction engine

Added `tools/touchscreen_transaction.py`, combining actual atomic file and
journal writes with injectable service/Moonraker ports. Preparation snapshots
file bytes, permissions/ownership, resolved destinations, service states and
camera settings before mutations. Installation stops the bridge/fixer, publishes
files with readback, validates nginx, enables/starts the intended services,
applies camera settings and verifies service/HTTP readiness through adapters.
Failures attempt restoration; unconfirmed recovery retains its journal and
reports the failure. A new process can explicitly restore from that journal.

Recovery validates files before changing anything, stops the camera fixer before
restoring its settings, restores prior files and service enablement/running
states, and verifies results. Later file edits or service changes after a
successful installation refuse automatic undo. A running camera fixer prevents
preparation, avoiding an in-progress settings writer. No arbitrary printer
commands or Klipper restarts belong to this transaction.

Validation: 42 transaction/settings tests passed. The file and journal operations
are real, with simulated systemd/nginx/HTTP ports. Tests exercise fresh/upgrade
restoration, all service-stage failure points, lost API replies, process loss
mid-file publication, later file/service edits and unresolved journal retention.
The engine is not yet used by the production installer: real adapters, staged
payload planning and orchestration wiring remain required. The current script
has not been replaced and these tests do not qualify live installation. No
printer interaction occurred in this follow-up; G06 remains open.

### G06 follow-up: touchscreen adapters and normal installer wiring

Added concrete systemd/nginx/HTTP ports and payload planning in
`tools/touchscreen_runtime.py`. The plan preserves unrelated files and an existing
original-nginx backup, rejects unexpected WM+ nginx markers, and records the
installed firmware/time. HTTP readiness requires a JPEG snapshot and working
nginx screen route. Unsupported/transitional service states refuse admission.
A printer-side file lock serializes transactions; unresolved journals prevent
new installations.

`deploy.py install touchscreen` now uploads to a unique staging directory and
runs the inline journaled transaction, returning a receipt. Later component
failure includes that receipt in reverse-order restoration. The legacy install
script is no longer invoked by this component; explicit uninstall still uses its
legacy removal script. Delivery exports include all three transaction modules.
Lost remote outcomes identify the known journal path rather than claiming that
rollback succeeded. A recovery CLI for process/connection loss remains needed.

Validation: 112 local adapter/transaction/settings/component/deploy/export tests
passed. Added isolated subprocess loading of the inline transaction modules and
component receipt routing. Read-only SSH confirmed the installed systemd reports
screen active/enabled, fixer inactive/enabled, nginx active/enabled, and an absent
service as not-found/inactive with an empty UnitFileState and successful exit.
Evidence: `analysis/validation/2026-11-07-touchscreen-rollback/service-state.json`.
No service, camera setting, printer configuration or motion was changed. Normal
installer hardware qualification and remaining recovery gates are still open.

### G06 follow-up: explicit touchscreen recovery command and live plan audit

Added `deploy.py recover touchscreen --journal <printed-printer-path>`. It
validates the exact generated journal-path format before contacting the printer,
requires idle state, restores the retained transaction without installing a new
candidate or restarting Klipper, and reports unconfirmed recovery as failure.
The README now documents this recovery scope and the receipted rollback behavior.

Validation: 106 local deploy/component/runtime/transaction/settings tests passed,
including command routing, invalid arguments, active-print refusal and recovery
failure reporting. A read-only live plan audit also passed using the actual
service and camera adapters. It produced seven intended file destinations,
recognized the existing nginx include without proposing an nginx-site edit,
recognized the existing database-backed Touchscreen camera, and confirmed the
print camera named `camera` exists and is already selected for timelapse.
Evidence: `analysis/validation/2026-11-07-touchscreen-rollback/plan-audit.json`.
The audit used an automatically removed temporary payload directory; it did not
publish files, change camera settings, or operate services/printer hardware.

Live transaction execution/rollback qualification and whole-installer recovery
across process loss remain open. This command covers only the touchscreen's
journal, not all component journals. G06 remains open; runtime is still r74.

### G06 live touchscreen upgrade and exact restoration — passed

After verifying Ready/idle, all four nozzle targets zero and actual temperatures
below 50°C, ran the normal touchscreen component's preflight and transaction
installation on the printer. It returned applied. Restored it through the same
component's receipt, then compared the before/after snapshots: all eight tracked
files (including the unchanged nginx site), permission/ownership metadata, screen
and fixer/nginx service states, the entire webcam-list hash and the entire
timelapse-settings hash matched exactly. Klipper and native client process IDs
were unchanged throughout. No G-code, heating or motion was requested.

The bridge itself was restarted during the round trip. The installed candidate
passed its real JPEG/proxy readiness check. The separate recovery CLI then
accepted the completed journal idempotently and returned success. The retained
journal is `/opt/wondermaker_plus-transactions/5c8af6bdeaac497783d6381e84bd9edd.json`.

Evidence: `analysis/validation/2026-11-07-touchscreen-rollback/live-roundtrip/`
contains the before/installed/after states, receipt, exact comparison result,
runner and source hashes. This qualifies an upgrade/restoration of the existing
screen bridge on this printer. It does not prove fresh installation, injected
live failure recovery, or whole-installer recovery after process loss. G06 stays
open; the current gap table has been updated to reflect this live pass. Native
WM+ runtime remains r74.

### G06 live late touchscreen failure and automatic rollback — passed

Rechecked Ready/idle, zero nozzle targets and cold nozzles. Injected a single
failure after the candidate bridge's real JPEG/proxy readiness check, after file,
service and camera changes had occurred. The injection lived only in the test
runner's remote process; it did not change shipped implementation files.
The transaction automatically restored itself and recorded `restored` before
returning the original injected failure.

Compared all recorded files and ownership/permission metadata, service states,
full webcam and timelapse settings hashes, and Klipper/native client process IDs:
all matched the baseline exactly. The restored bridge then passed real JPEG and
nginx proxy checks. No explicit recovery call was needed to reach that result,
and no Klipper restart, motion, heating or G-code was requested.

Evidence: `analysis/validation/2026-11-07-touchscreen-rollback/live-failure/`
contains before/after states, injection confirmation, journal receipt, comparison
result, source hashes and runner. This qualifies the late-failure automatic
rollback path for an existing screen-bridge upgrade on this printer. Fresh
installation and the remaining whole-installer/package gates remain open.

### G06 combined component failure-path validation — local

Added an installer-level test using real configuration planning/publication,
helper staging/rename, and touchscreen file/journal/setting transactions together.
SSH transport and services/API are modeled, and the final preload component is
made to reject before activation. This is explicitly not a full firmware install
or a bypass of the production delivery seal.

Fresh and existing-install cases restore the exact original file contents,
permissions/ownership, camera settings and service states, preserving filament
records and unrelated files. Verified undo order: material receipt, touchscreen
receipt, configuration include, then the helpers owned by that configuration
receipt. No Klipper restart occurs after the rejected install.

Conflict cases modify a touchscreen file after publication. Recovery preserves
the edit, stops before undoing the dependency configuration/helpers, retains the
unresolved receipts, and returns failure. It does not claim a completed rollback.

Validation: 116 combined/deploy/config/touchscreen tests passed, followed by four
fresh/upgrade/conflict installer cases after adding conflict coverage. These runs
overlap. Evidence is `tests/test_install_components_together.py`; all mutations
were disposable local files. Whole-installer recovery across process loss and
normal clean-install/release qualification remain open; no printer changes.

### G06 follow-up: durable whole-installer receipt model

Added `tools/install_journal.py` for atomic, mode-0600 installer checkpoints.
It records printer host/user, ordered components, the in-progress component,
completed binary-safe receipts and reverse-order recovery checkpoints. Records
use typed JSON data, not executable serialization. A checksum detects damaged
records; it is not an authentication mechanism. Failed atomic replacement keeps
the prior checkpoint intact.

A journal with an in-progress component explicitly reports an unknown outcome;
it neither assumes the remote process stopped nor claims that component was
installed or rolled back. Completed records can be recovered in reverse order
and checkpointed across a subsequent process loss. Wrong-printer replay,
incorrect completion/recovery order and incomplete success claims are rejected.

Validation: 12 local journal tests passed, including binary receipt round-trip,
process-state loss, partial recovery continuation, wrong printer, damaged record,
failed disk replacement and unsupported encoded values. Production orchestration
and recovery CLI wiring remain outstanding; this module alone does not close the
whole-installer interruption gap. No printer interaction occurred.

### G06 follow-up: production installer journal checkpoints

Wired the durable journal into normal installation after preflight and before
component mutation. The installer prints a unique local journal path, checkpoints
a component before calling it, persists each successful returned receipt, and
marks successful completion only after the final activation/status work. Journal
creation failure stops before installation. In-process rollback also checkpoints
confirmed undo while retaining an unresolved later component in the journal.

Journals are owner-only files under the checkout's ignored
`.wmp-install-journals/` directory and include printer host/user identity. Delivery
exports include the journal implementation but not receipt files. The README
explains the private snapshots and that whole-install recovery CLI wiring is
still outstanding.

Validation: 75 journal/deploy/combined-component/export tests passed. Tests verify
pre-mutation checkpoint visibility, completed install records, process loss
leaving the correct in-flight component, refusal to interpret that ambiguity as
completion, and durable reverse-order undo records for actual combined file
publications. All activity was local; no printer changes. This adds persistence,
not automatic resolution of an interrupted component's remote outcome. G06 stays
open.

### G06 follow-up: completed-component recovery CLI and locking

`deploy.py recover all --journal LOCAL_PATH` now loads the installer's durable
receipts, checks printer identity and recovery eligibility, validates supported
components before mutations, and restores config/material/touchscreen in reverse
order. Every completed restoration is checkpointed. A printer becoming active
between components stops further work; a later invocation resumes the remaining
receipts. The command explicitly leaves backend restart/readiness verification
outstanding. It does not claim an unresolved component completed successfully.

Installation and recovery hold an exclusive lock for the same local journal.
Tests use a separate process to verify lock exclusion/release and reject a linked
lock file. Recovery tests cover reverse order, unsupported receipts, unresolved
in-flight state, wrong printer, interrupted recovery continuation, and actual CLI
routing with and without a held lock.

Validation: 84 tests passed across `test_install_journal.py`, `test_deploy.py`,
`test_install_components_together.py`, and `test_unified_delivery_export.py`.
These are local checks; no printer motion, heating, deployment or restart occurred.
The per-journal lock is not a printer-wide lock across independent installations.
G06 remains open for unresolved in-flight/preload recovery and full clean-install,
failure-path and release-package qualification.

### G06 follow-up: material publication interruption recovery

Material installs now persist a full undo plan after staging/readback and backup
verification, before replacing any destination. `recover all` can restore this
prepared, in-flight material receipt before earlier completed dependencies. It
accepts destinations still at their original bytes as already restored; published
bytes are restored from verified backups. Completing installation removes the
prepared marker in favor of the completed receipt. Nested helper installation
inside config does not mark the enclosing config transaction recoverable.

Local validation: 145 tests passed across installer journal, material install,
deploy routing, combined components, and screen-config reconciliation suites.
Fault injection models process loss before/after publication at positions 1–3,
on fresh and existing installs, then reloads the on-disk journal for recovery.
Additional checks cover checkpoint failure preventing publication, recovery
ordering before config, and removal of the prepared marker after completion.

Limits: this is modeled process loss with real local file replacements, not a
live power-cut test. Interruptions before the material undo checkpoint remain
unresolved; config/preload still lack equivalent whole-component preparation
receipts. No printer changes were made, and G06 remains open.

### G06 follow-up: stop helper recovery on unconfirmed restoration

Helper rollback now validates all destination bytes and required backups before
its first mutation, rechecks each destination immediately before restoration,
and stops at the first failed operation/readback. It no longer continues to
restore other helpers after discovering a conflict. A failed rollback inside a
material installation also blocks outer rollback of earlier component receipts;
those files remain available for inspection instead of downgrading dependencies
under an unconfirmed helper set.

149 local tests passed across material install, installer journal, deploy,
combined component and screen-config reconciliation suites. New fault cases cover
corrupt backups before any restore, concurrent edits between validation and
mutation, a committed restore with a lost reply followed by successful retry,
and prevention of earlier config rollback after an unconfirmed helper restore.
This is failure-path progress within G06, not release qualification. Printer state
was untouched.

### G06 follow-up: touchscreen interruption handoff and idle rechecks

The installer now saves the touchscreen's remote transaction journal path before
remote activation. Recovery can therefore delegate an in-flight touchscreen
operation to the existing remote transaction restore, and advances the local
checkpoint only after confirmed restoration. If the remote journal is missing or
cannot be restored, the in-flight marker remains and earlier components are not
restored. This does not guess that remote activation succeeded.

Automatic rollback now checks printer activity between component restorations,
matching explicit recovery's behavior. If a print starts, remaining receipts are
retained until idle.

105 tests passed across touchscreen component/transaction, installer journal,
deploy and combined installation suites. An additional missing-remote-journal
regression passed in the focused journal/component rerun. Tests also prove that
failure to save the touchscreen checkpoint prevents remote activation. This turn
used modeled transport/services and local files; no printer changes occurred.
Config/preload interruption qualification and attended acceptance remain open.

### G06 follow-up: recovery across lost completion acknowledgements

Added integration coverage joining the local installer journal with the real
local touchscreen file transaction and modeled camera/service endpoints. For both
fresh installs and upgrades, tests inject (a) a lost remote response after full
restoration and (b) failure to save the local completion checkpoint after remote
restoration. In both cases the on-disk local journal remains unresolved, while
the remote transaction has restored all original files, metadata, camera settings
and service state. Retrying loads both journals, verifies the restored state, and
finishes the local checkpoint without further service mutations or camera writes.

59 tests passed across touchscreen transaction/component and installer journal
suites. This strengthens the completed/in-flight touchscreen recovery evidence;
it does not close config/preload interruption recovery or qualify a live power
failure. No printer operations were performed.

### G06 follow-up: configuration publication interruption recovery

Preserved-config installation now chooses a unique backup directory and saves
that identity, the reviewed plan, and helper receipts in the installer journal
before remote configuration publication. The publisher exclusively creates the
selected directory; it refuses an existing destination. A complete remote
`prepared` journal is now eligible for restoration after verification of the
plan, backup bytes, and current destination bytes. This covers process loss during
publication and loss of the successful publication response.

The screen-config reconciliation, combined component, installer journal and deploy
suites passed. New checks exercise fresh/upgrade config+helper restoration after
lost publication responses, process loss before/after a configuration write,
and refusal to reuse an existing backup directory. Test adapters map both remote
configuration and backup paths into temporary directories. No printer changes.

Remaining limits: interruption during config's earlier helper-install phase or
before a complete remote backup journal exists is still unresolved; preload
interruption qualification remains open. G06 is not closed.

### G06 follow-up: configuration helper-phase recovery

Configuration installation now supplies a preparation callback to the helper
publisher. Before any helper replacement, the installer saves a `config-helpers`
receipt containing the complete helper undo plan. Recovery of that phase only
restores helpers and does not invoke the configuration publisher/restorer. After
helper installation returns, the installer replaces the prepared receipt with
the configuration plan, selected backup location and helper receipts before
remote configuration publication begins.

168 local tests passed across config reconciliation, material installation,
installer journal, combined component and deploy suites. New cases model process
loss immediately before/after helper publications 1, 3 and 5, on fresh installs
and upgrades, reload the durable receipt, and recover through the normal installer
recovery function. Configuration and persisted filament data remain unchanged.

This closes the previously identified unjournaled helper-publication phase in
config installs. Missing checkpoints/remote backup journals still require
inspection, preload recovery remains incomplete, and full delivery/attended
qualification is not complete. No printer changes occurred.

### G06 follow-up: durable preload publication evidence

Preload publication now flushes backup files, atomically writes and flushes its
publication journal, then flushes each candidate file before replacement and its
parent directory afterward. Restoration likewise flushes replacement files and
directories. A stage with an existing publication journal cannot be republished,
preventing recovery evidence/backups from being overwritten by a retry.

82 tests passed across preload restoration, bundle and current-screen delivery
suites. New fault cases cover journal-publication failure (no destination changes),
modeled process loss before/after library replacement, restoration from the saved
journal, and refusal to overwrite an existing publication journal. No live power
failure was induced. This strengthens the low-level preload transaction; integrated
whole-installer preload recovery and restart qualification remain outstanding.
No printer changes occurred.

### G06 follow-up: missing preload evidence must not count as recovery

Preload restoration previously returned successfully when `publication.json` was
missing and accepted an empty row list. Both now fail explicitly as unconfirmed
recovery. Truncated journals also fail before destination changes. This prevents
an activation failure from proceeding to backend restoration and restarting a
client whose previous library/drop-in state has not been proved restored.

86 tests passed across preload restoration, bundle and current-screen delivery
suites. A new installer-level failure test removes the recovery journal after
candidate activation fails; recovery stops the client, retains the stage, marks
backend rollback blocked, and performs neither backend restoration nor a second
service restart. Missing, empty and truncated journal tests verify that published
files remain unchanged. Printer state was untouched; full preload interruption
recovery is still open.

### G06 follow-up: integrated preload recovery and restart checkpoint

Preload installation now returns and checkpoints its stage receipt before
publication, and retains the stage when running under the installer journal.
Explicit installer recovery accepts that receipt, stops the client, verifies and
restores preload files, restores earlier components, then restarts the client
through the existing Klipper readiness check. A durable restart-required marker
survives a failed restart so retry can finish without repeating file restores.
Recovery refuses missing journals and invalid stage paths. Standalone component
calls without an installer journal retain their prior cleanup behavior.

104 tests passed across preload bundle, installer journal, deploy and combined
component suites. The new integrated case uses real temporary preload files,
remote-helper execution through the local transport fixture, modeled service
commands, a process loss before restart acknowledgement, ordered backend recovery,
failed restart/readiness, and successful retry of the remaining restart step.
No host system service or printer was restarted. This implements the recovery
route but does not establish live interruption/restart or clean-install release
qualification. G06 remains open.

### G06 follow-up: combined recovery/delivery regression

The combined 18-suite installer/delivery run passed **429 tests in 66.87 seconds**.
JUnit output and tested source hashes are retained under
`analysis/validation/2026-11-07-installer-recovery/`. This covers config/material,
local journals, touchscreen files/settings/services, preload publication/recovery,
restart/readiness, package binding and exports together.

The broader run initially exposed stale historical-package tests: they compared
an older artifact hash and today's evolving source files against the existing
sealed historical descriptor/archive. Tests now bind the historical package to
its archived inputs and the artifact recorded in its descriptor/provenance; no
artifact or descriptor was resealed. Their isolated tool imports were fixed, and
the local installer fixture now models its stop-service command instead of
attempting host systemd access. All failures passed after those corrections.

The current r74 artifact exported successfully to
`/tmp/wmp-delivery-recovery-20261107-01`; its standalone installer `list` command
runs independently. Export scope remains **packaging-control-only**, with artifact
SHA256 `af74be596240fa5366d3a97ae537ecada22ff8540a6d301e1a8556f810e54445`.
This is not clean-install/live interruption qualification or release promotion.
No printer operations were performed.

### Read-only printer baseline after installer recovery work

Fresh SSH/status and process-memory readback confirms all five backend helpers
match current source, checked macro contracts have no mismatches, the printer is
Ready/standby with no material operation, and all four nozzle targets are 0 C.
Both persisted filament files retain their earlier hashes. The eight checked r74
native hook destinations match the running library in client PID 3408691.

The framebuffer capture shows Toolhead management with H3 selected and Mounted,
Sunlu PLA Matte pink marked Loaded, 29/0 C, and 0.4 mm/Hardened steel. Evidence is
saved alongside the local regression results as `live-readback.json`,
`live-hooks.json`, and `live-screen.png` in
`analysis/validation/2026-11-07-installer-recovery/`.

No commands for heating, motion, restart, deployment or screen navigation were
issued. Z reference is currently invalid; this baseline does not establish paused
filament preparation, calibration or homing acceptance. The printer remains at
the same screen, ready for the remaining attended checks.

### G05 follow-up: factory callbacks identified as residual coverage

The current stock-caller audit now identifies the unresolved `0x4c41a4` callback
as Factory Mode and records its ten direct sends. A separate knife-pairing event
has eight sends, including direct Z jog and persistent probe-position save.
Their caller addresses are not in the r74 Maintenance/first-run calibration sender
set. In particular, Factory Mode still constructs its own G28/T0/PROBE_CALIBRATE
sequence; the fixed Maintenance probe entry does not cover that distinct issuer.

Evidence and exact-client/function hashes are saved in `factory-audit.json` and
`factory-callbacks.asm`; see the current factory/service section of
`docs/upstream-client-callers.md`. This makes G05's remaining caller work concrete:
resolve registration/action predicates, then cover factory preparation, jog and
save admission with appropriate lifecycle semantics. It is a static coverage
finding, not a claim that a particular user action executed or a physical test
failed. No printer contact or production code changes occurred this turn.

### G05 follow-up: factory registration and branch execution

11 exact-vendor ARM tests now pass for factory/knife dispatch, conditional probe
homing, and the factory constructor registration loop. Probe is action 12 and is
registered by setup; its logical T0 prefix occurs whether or not G28 is emitted.
Knife jog handlers update the displayed offset before movement dispatch, making
pre-event admission necessary for reliable persistence. These findings determine
where the correction must intercept; no production change or printer operation
was made. See `tests/test_stock_factory_worker.py` and the factory audit addendum.

### 8 November: r89 material transition deployment

Installed native UI `69f8b74f5fdb72f44598cfcb3b02c647fdba8bda2b7edca862cd51a8ba628b5b`
and wm_material `6bcf05f271e2fd875732164ffe7435ee1df30fa20164eafee2da826218362482`.
Preflight and activation passed; 25 other tracked files were preserved.
Post-restart status proves H3 Sunlu PLA Matte pink and H4 Kexcelled PLA Matte
Bluish Gray remain loaded, H1/H2 remain not loaded, and all nozzle targets are
zero. Klipper is ready in a new session. No motion, heating or printing was
commanded. Homing reference is reset by the restart as expected.

Evidence: `activation-stockwidgets-r89/` and
`analysis/validation/2026-11-08-main-track/r89-{after,restart-verification}.json`,
`r89-startup.png`, `generic-swap-policy.xml` (366 backend tests), and
`r89-ui.xml` (2 native lifecycle/projection tests). Material history is recorded
on future feed/purge operations; this deployment does not infer old residue
from editable spool metadata. G07 physical mixed-material qualification remains
open, as do disjoint-range transition recipes.

### Preview row stability follow-up — local candidate after r89

Investigation of the missed selector tap found that `StockPreviewRows` included
freshness/editability in its full layout signature. A stale/fresh transition
therefore deleted every mapping-row button even when the row data was identical.
This is a demonstrated widget-lifetime defect, not proof of the specific live
missed tap's cause. The local correction changes enabled state in place and
retains the existing row bindings; callbacks still reject stale/read-only events.
Actual row-content changes retain the existing rebuild/invalidation behavior.

The new native lifecycle regression fails before the fix at the assertion that
buttons survive stale status, and passes afterward. It checks allocation count,
button identity, disabled state, refusal while stale/read-only, recovery to fresh
status, retained scroll position and successful selection after recovery.
Evidence: `preview-row-stability-before.xml` and `preview-row-stability-after.xml`
in `analysis/validation/2026-11-08-main-track/`. ARM build and live validation are
pending; no claim is made that all missed-touch causes are resolved.

### r90 preview admission-state fix deployed

UI SHA256 `b52a6bb441dbb42f584a00cc69afd323c7fc7a246a956ea458a14138835cb070`.
Activation and live ready-state checks passed; 26 other files were preserved.
`r90-after.json` and `r90-restart-verification.json` prove H3/H4 identities and
loaded flags survived, H1/H2 remained not loaded, and nozzle targets are zero.
The regression is narrow: row controls survive freshness/editability changes;
other sync-driven rebuild findings remain open in the linked audit. No motion,
heating or printing was commanded.


### G06 follow-up: actual process death during preload rollback

A real subprocess killed with SIGKILL after flushing its restoration copy but
before rename left the deterministic `.wmp-restore` file behind. A fresh recovery
process then refused that file forever. The before-fix run fails at that exact
checkpoint; death after rename already recovered successfully.

Restoration now creates an exclusive, uniquely named temporary file for each
attempt and reconstructs it from the verified backup. It does not trust, reuse,
or remove unconfirmed leftovers from killed attempts. Normal error paths remove
the current attempt's temporary file. A destination check immediately before
rename also refuses an edit made while the copy was being prepared.

The focused restore, preload and installer-journal suites pass **74 tests**.
Evidence: `analysis/validation/2026-11-08-main-track/recovery-sigkill-before.xml`
and `recovery-sigkill-after.xml`. New cases kill actual processes before/after
rename and recover in fresh processes, preserve an unknown leftover and refuse
a destination edit during copying. All files and processes were isolated in
temporary directories; no printer service, configuration, motion or heating was
affected. This closes the demonstrated process-loss retry defect, not the
remaining live service/restart or clean-install qualification gates.


### G06 follow-up: reinstall after killed publication

Actual SIGKILL immediately before publication rename exposed the corresponding
install-side defect: rollback completed, but a later installation in a fresh
stage failed because the old `.wmp-new` file still existed. Death after rename
already recovered correctly. Publication now uses an exclusive, uniquely named
copy per attempt, leaves unconfirmed leftovers alone, and rechecks the destination
before rename. Normal exceptions clean up the current attempt's copy.

The regression kills the publisher before/after rename, recovers in a separate
process, performs a new installation from a fresh journal, and rolls that back.
Both paths now pass. Restore, preload and installer-journal suites pass **76
tests**; before/after evidence is `publication-sigkill-before.xml` and
`publication-sigkill-after.xml` under the 2026-11-08 main-track validation folder.
These are actual process-death/file-transaction tests in temporary directories,
not live printer service or clean-install acceptance. The printer was untouched.

### r105 closed-preview polling retirement — 8 November

Closing a print preview now also retires its worker-side file selection. Previously
metadata/roots refreshes continued every five seconds while using Toolheads.
The targeted lifecycle regression failed before the change and passed afterward.
ARM build and exported installer deployment passed; native hooks initialized,
Klipper returned Ready/standby, and comparison of 128 tracked files showed only
the intended native library changed. H3/H4 loaded state, identities, attachment,
nozzles, and mapping were preserved; heaters remain off.

Artifact SHA256: `7f7f2ff8fc8728426a687820472ad002e5025903d8596b804e5c470927edb056`.
Evidence: `r105-preview-retirement/`, `qualification-export-r105/`, and
`qualification-install-r103/r105-{before,after}/` under the 8 November validation
folder. Deployment restart produces expected disconnected samples; this does not
close the remaining status-observation check during head transitions.

### r106/r107 status publication and preview handoff — 8 November

Runtime publishes printer status and handles queued commands before refreshing
preview metadata; the next poll uses the metadata cache. The targeted regression
failed against the old ordering and passed after correction, including expiry
after two seconds, retained cached rows during refresh, and separation of file
lookup failure from printer availability.

The live r106 check exposed an initial metadata placeholder being admitted as a
reviewed preview, causing a false configuration-change message. r107 retains
the initial loading state until metadata arrives (or a real metadata error is
known). Its lifecycle regression passed. Live screenshots confirm Loading then
the normal source-selection prompt. No print was submitted; existing parser and
usage acceptance was reused.

r107 is deployed via the exported installer, artifact SHA256
`c7d4e921a84b5a4ad6522f914a953552b10b7e6bea5dbbe419e7aec02430805b`.
Both deployment comparisons show only the intended native library changed out
of 128 tracked files. H3/H4 loaded records, attachment, identities, nozzles and
mapping remained unchanged; Ready/standby and heaters off verified.

Evidence: `r106-status-before-preview/`, `qualification-export-r106/`,
`qualification-export-r107/`, and `qualification-install-r103/r10{6,7}-{before,after}/`
under the 8 November validation folder. Head-transition status observation
remains open; these targeted checks do not establish that every dropout is fixed.

### r107 remaining transition dropout reproduced — 8 November

A targeted cold H3→H2→H3 round trip completed successfully and preserved loaded
flags, identities and heater-off state. The initial H2 transition established
real bottom Z and XY; the return began already homed. The 56/30 status samples
recorded maxima of 1,860/1,944 ms respectively; the H2 run also had a 1,238 ms
request. These exceed the native one-second request deadline. Captured framebuffer
frames show the unavailable banner during preparation, so the status gap remains
open. This was a status investigation, not another full cycle-count qualification.
The external observation timeout was three seconds; zero observer errors does
not mean the native one-second requests succeeded.

Non-blocking 25 Hz profiles of Klipper and Moonraker during the return found
substantial repeated nozzle-file parsing in WM+ status and stock SAVE_VARIABLE
reparsing its 61,846-byte file. Klipper samples include 178 nozzle-parser and 55
save-variable stack observations; these are sampling evidence, not precise
per-request attribution of the 1.94-second stall. Nozzle content caching is now
implemented locally: every read still checks actual file contents, while unchanged
content reuses validated parsing. Cached dictionaries are copied before the status
adapter adds runtime fields. All 439 nozzle/material tests passed, including
external same-size/same-timestamp edits and malformed/missing files.

Read-only benchmark on the printer's real files: 20 warmed reads took 1,165.26 ms
with the installed code and 71.49 ms with temporary candidate code; results were
identical. This is only nozzle-read cost, not end-to-end status latency. The
candidate helper is **not deployed**; r107 UI/r98 backend remain active. Batch
the backend performance changes after investigating the stock save path rather
than repeatedly restarting for each small optimization.

Evidence: `analysis/validation/2026-11-08-main-track/r107-transition-status/`,
including timestamped observations, framebuffer captures, camera snapshots, both
server profiles, test results and benchmark. Final state: H3 mounted, XYZ homed,
all nozzle targets zero; no extrusion or printing. Camera snapshots do not close
the continuous visual/audio acceptance item.

### r108 backend status stalls fixed and targeted transition accepted — 8 November

Deployed unchanged-content nozzle parsing and a recognized-stock saved-variable
loader cache. Stock saves still read and write the actual file in their original
order. Unchanged literal text reuses validated parsing; nested values are copied
to prevent consumer mutations from contaminating the cache. Custom loaders are
left untouched. During WM+-owned running filament/tool procedures only, each
completed save yields to status timers while retaining the G-code mutex.

The retained openACE state accounts for 59,288 characters of the 61,846-byte
saved-variable file even with openACE disabled. Disposable-copy measurements on
the printer reduced twelve saves from 3,503 to 1,264 ms with the production
cache. No retained data was deleted. The cooperative yield prevents consecutive
saves from monopolizing the reactor; the status freshness/deadline was not relaxed.

Validation: 602 integrated backend/install tests passed. Delivery/export tests
had 79 passing cases and one obsolete six-helper fixture expectation; after
updating it to seven, that case passed separately. The ARM build and source-bound
export passed. Ordinary exported installation restarted the touchscreen/Klipper
and verified Ready; log confirms cache activation. The before/after 129-path
manifest differs only in the candidate library, wm_material, wmp_nozzles and the
new wmp_saved_variables helper. Filament identities/loaded flags persisted; only
the expected runtime session identifiers changed.

A targeted cold H3→H2→H3 round trip completed: 71/34 observer requests, maximum
823/878 ms (previously 1,860/1,944 ms), zero observer errors. OCR found no
unavailable banner in 53 framebuffer captures; the initial frames were also
visually checked. Native status-query maximum was 692 ms with no new failures
after entering Toolheads. Its nineteen earlier failures belong to the restart
window; the last occurred 171 seconds before Toolheads navigation. These results
close this reproduced dropout, not every possible intermittent connection fault
or the pending physical-finger/continuous audio acceptance.

Final state: H3 mounted, H3/H4 loaded identities preserved, all nozzle targets
zero. No extrusion or printing. Evidence and source scripts:
`analysis/validation/2026-11-08-main-track/r108-backend-status/`. Installer journal:
`qualification-export-r108/.wmp-install-journals/5ebb8c7eb31d468b8a45b52470d4a560.json`.
Candidate SHA-256: `7c577817744443361f38dcdac0bfb9aded6da0d182c958455fba787d707c2f0a`.

### Remaining measured metadata parsing cost — local follow-up

The earlier transition profile also showed repeated `_profiles` work. The local
follow-up caches validation and canonical revision hashing for identical complete
file text. Every call still opens/reads the file; same-size/same-timestamp edits,
missing files and malformed replacements remain immediately visible. Each caller
receives its own deep copy, preserving save admission and mutation isolation.

All 422 material tests pass, including new external-edit/stale-save, malformed
replacement, deletion/recreation and caller-mutation cases. A separate read-only
Python process on the printer measured 100 warmed calls: installed 206.35 ms,
candidate 107.01 ms; returned values match and the live metadata file hash stayed
unchanged. This is metadata-read cost, not end-to-end status latency. The change
is **not deployed**; batch it with the next necessary backend delivery. r108 remains
the accepted installed baseline and no physical test was repeated. Evidence:
`r108-backend-status/profile-cache-{tests.xml,benchmark.json,benchmark.py}` under
the 8 November validation directory.

### r109 metadata follow-up delivered — 8 November

Built a fresh source-bound ARM candidate and exported
`qualification-export-r109`; all 70 export/current-delivery tests passed. This
validates the changed source binding and isolated installer payload, not a full
clean-stock physical installation. The candidate touchscreen SHA remains
`7c577817744443361f38dcdac0bfb9aded6da0d182c958455fba787d707c2f0a`: no GUI code
changed. The earlier metadata tests (422 passed) and read-only timing benchmark
remain the behavior evidence; accepted load/unload and transition tests were not
repeated.

Normal exported development-qualification installation completed, journal
`2037911250c14f95b79af0f3b6a1d5b6.json`. Touchscreen PID 3849457 was active and
Klipper Ready after restart. Across 129 before/after file records, only
`klipper/klippy/extras/wm_material.py` changed, matching the local source hash.
Configuration, loaded flags and filament identities persisted (runtime session
IDs changed as expected). H3 remains mounted, H3/H4 loaded, nozzle targets zero;
no motion, extrusion, calibration or printing was commanded. Saved-variable cache
activation was confirmed in the new Klipper session.

Evidence: `analysis/validation/2026-11-08-main-track/r109-delivery/` and
`qualification-install-r103/r109-{before,after}/`. The local metadata follow-up
is now deployed. Package scope remains unreleased/packaging-control-only; physical
acceptance and first-run/clean-stock gates remain open.

### Attended touch check — 9 November

With the printer Ready/standby, H3 mounted, H3/H4 loaded and all nozzle targets
zero, the operator tested repeated Toolheads/Filaments navigation, H3 then H4
menu exclusivity, and Edit/CANCEL. In response to the explicit missed/delayed/wrong
action check, the operator reported “Everything worked.” This closes the remaining
physical-touch sequence, while retaining earlier diagnostic evidence if a new
intermittent fault is reported. No motion or heating was commanded for this check.
Evidence: `analysis/validation/2026-11-09-attended/arrival.json` and
`touch-confirmation.json`. Sensor and insertion-wait checks are next, not passed.

### Attended unload result and XY-only Dock correction — 9 November

The operator completed H3 unload and removed the pink filament. Live status
confirmed the filament sensor clear, loaded flag empty, all heaters off, H3
mounted, and only XY homed. The completed result still displayed the removal
instruction with a disabled DONE button. The candidate now labels result closure
CLOSE and enables DONE for completed operations; neither action resubmits motion.
The native lifecycle regression passes.

The subsequent Dock failed before docking began with ZRU-C010 (home first).
The stock `_UNLOCK_TOOL` cleared nozzle offsets using MOVE=1, which requested Z
travel while Z was unhomed. H3 remained mounted at the purge position. Supported
recovery drained the queue and verified attachment without moving the printer.
The candidate retains MOVE=1 when Z is homed, but uses MOVE=0 otherwise; docking
then follows its existing XY-only path and release checks. All 254 macro tests
pass, including unhomed, XY-homed and XYZ-homed offset-reset cases.

Targeted physical validation of Dock after XY-only filament service is reopened;
previous ordinary tool-change acceptance does not cover this condition. Automatic
mount through Load and insertion-wait STOP remain open. Evidence is under
`analysis/validation/2026-11-09-attended/` (`h3-removed.json`,
`dock-homing.json`, `dock-recovery.json`). Candidate r110 was deployed through the exported config/material/preload installer.
Klipper Ready and the touchscreen active after restart; H3 remains mounted and
empty, H4 loaded, all nozzle targets zero. Journal:
`f68fc09d818c42b3a5c67e92da4c622f.json`. Physical Dock recheck passed: operator confirmed clean release; live receipt complete, carriage empty, only XY homed and all nozzle targets zero.

The operator subsequently reached Insert filament with H3 empty and pressed STOP.
Live status confirmed cancellation in the inserting phase, with all nozzle
targets zero. This closes the attended insertion-wait cancellation check. Evidence:
`insertion-stopped.json`; operator report: “Reached Insert filament and stopped.”

### r110 attended Dock accepted — 9 November

Operator confirmed H3 Dock completed cleanly without manual homing. Live status
reported `Head docked`, operation complete, empty carriage, only XY homed,
H3 empty, H4 still loaded with Kexcelled PLA Matte metadata, and all nozzle
targets zero. Evidence: `analysis/validation/2026-11-09-attended/r110-dock-confirmed.json`.
This closes the unhomed-Z Dock regression. Automatic mounting through Load is
the next distinct check; insertion-wait STOP already passed and need not be
requalified.

### Automatic mounting through Load accepted — 9 November

Starting with H3 docked, the operator started Load and confirmed it automatically
mounted H3 and reached Insert filament. Live evidence confirms H3 attached,
Load running in the inserting phase, only XY homed, sensor clear and loaded
flag empty. H3 target is 220 C while awaiting insertion; H4 loaded metadata
remains intact. Evidence: `analysis/validation/2026-11-09-attended/r110-auto-mount-confirmed.json`.
The D01 automatic-mount branch is accepted. Stop the waiting procedure before
testing sensor-present versus loaded, since insertion during active Load advances
the procedure automatically.

### Inserted versus loaded accepted — 9 November

After stopping Load and closing the result, the operator inserted pink to H3's
inlet/gears and confirmed the card showed Inserted rather than Loaded. Live
status confirms sensor_present=true with the loaded state still empty, cancelled
Load, and all nozzle targets zero. Combined with the preceding real sensor-clear
readings, this accepts the physical presence/loaded distinction. Evidence:
`analysis/validation/2026-11-09-attended/r110-inserted-confirmed.json`.

### Restoration Load and DONE closure accepted — 9 November

Operator confirmed H3 Load completed feed/purge/wipe and DONE closed the progress
screen. Live status confirms completed Load and H3 loaded. This accepts the new
DONE action and restores pink filament after the insertion checks; it is not
additional color/material-transition qualification. Evidence:
`analysis/validation/2026-11-09-attended/r110-load-done-confirmed.json`.

### Attended cold-boot persistence accepted — 9 November

After being asked to power off and back on, the operator confirmed both H3 pink
Sunlu PLA Matte and H4 Kexcelled Bluish Gray remained loaded. Live post-boot
status confirms both loaded flags and identities match the pre-boot snapshot.
This is operator-confirmed physical power-cycle evidence, distinct from prior
client/Klipper restart checks. Evidence:
`analysis/validation/2026-11-09-attended/r110-cold-boot-confirmed.json`.

### Requested Sunlu PLA/PETG simulation — 9 November

The operator proposed treating the actual Sunlu PLA as PETG for testing, then
accepted checking targets without exposing PLA to hotter recipes. A focused
host-side round-trip planning test passed (1 passed, 422 deselected). It exercises
Sunlu PLA Matte history → PETG Load at 220 C → PETG Unload at 235 C → PLA Matte
Load at 240 C → PLA Unload at 250 C. The latter is the existing PLA shaping
recipe, not a new temperature introduced by transition logic. Each Load plan
retains 55 mm feed, 50 mm purge and wipe; simulated completion/unload preserves
residue history for the next plan and leaves H4 history unchanged.

No heater, motion, metadata or loaded-flag commands were sent to the printer.
This validates plan selection and history bookkeeping only. Physical
PLA/PETG material transition and color-clearing effectiveness remain unverified;
pretending the filament is PETG cannot provide those observations. Evidence:
`analysis/validation/2026-11-09-attended/simulated-transition/tests.xml`; focused
regression `test_sunlu_simulated_pla_petg_round_trip_plans`.

### Purge ownership and remaining handoff — 9 November

User direction: purge amounts are calibrated in OrcaSlicer; WM+ should use the
configured purge when available. Do not require physical color-clearing
calibration as a WM+ release gate. Existing feed/purge/wipe execution evidence
remains accepted.

Current manual Load uses `load_purge_mm` from `[wm_material]` (default 50 mm),
separate from the 55 mm gear-to-nozzle feed. No Orca project/transition purge
context currently reaches this path. Therefore configured Orca consumption is
an open implementation gap, not a completed feature or a reason to repeat the
same physical load.

The handoff must use the correct old/new filament and physical-head mapping,
retain volume (mm^3) versus filament length (mm) units, apply any multiplier
exactly once, and bind the selected amount to the reviewed operation. An explicit
zero is distinct from missing data. Do not infer a purge from an unrelated last
preview or duplicate purge already emitted by the sliced file. Manual operation
without applicable slicer context retains the configurable fallback.

Source inspection: Orca `src/libslic3r/GCode.cpp` computes transition wipe volume
from the matrix and multiplier, accounts for purge already allocated, divides
by filament cross-sectional area, and exposes `flush_length` to custom G-code.
This is a per-transition handoff; a global cached matrix number is insufficient.
No printer commands or new purge settings were applied during this review.

### Cross-family purge configuration implemented locally — 9 November

Added `cross_material_purge_mm` with fallback to `load_purge_mm` when omitted.
Known same-family changes retain normal purge; cross-family, mixed-family and
unknown residue select the cross-family amount. Feed distance stays independent.
Plan description and token include the chosen amount. Focused classification and
plan tests plus the full material/install suites passed: 476 tests. Installer
preservation fixtures now include a custom cross-family value. No deployment
or physical purge test was performed; there is no new execution path requiring
repetition of accepted extrusion/wipe behavior. Evidence: `analysis/validation/2026-11-09-attended/r111-delivery/backend-tests.xml`.

User clarified that Orca integration should eventually support G-code-requested
manual swaps with guidance on the incoming filament when present in the G-code.
Recorded the future guided paused-swap requirements and fallback precedence in
`standalone-filament-management.md`; this future integration is not implemented
by the new configuration option.

### r111 delivery preparation and communication preflight — 9 November

The cross-family purge candidate was rebuilt and exported with source binding.
All 70 export/current-delivery checks passed, in addition to the 476 backend and
material-install tests. The touchscreen binary hash is unchanged from r110;
this is a backend/configuration feature. Artifacts and test results are under
`analysis/validation/2026-11-09-attended/r111-delivery/` and
`qualification-export-r111/`.

Idle deployment preflight refused because Klipper was already shutdown with
ZRU-B006 (T3 / physical Head 4). Filtered logs show all other MCUs timing out
about one second later. CAN is currently present; kernel journal access was
denied, so USB reset as the cause is not established. No installation occurred
before that fault. A single firmware restart was requested after confirming
standby, not paused and heater targets zero. Recovery ended in error: Failed
automated reset of MCU mcu. No second reset or installation was attempted.
Operator power-cycle requested; candidate r111 remains undeployed. Evidence:
`r111-restart-state.json`.

### r111 deployed and preserved state verified — 10 November

The operator requested another firmware reset. That attempt reached backend
Ready; the earlier MCU-reset failure no longer blocks delivery. Following a
fresh idle/heaters-off snapshot, the exported material/preload installer completed
with Klipper Ready and the touchscreen active (PID 684514). Journal:
`0303f7a6bc6a460b887af9ecb53feb9c.json`.

Across 129 before/after file records, only `wm_material.py` changed and it matches
the local source hash. All filament loaded flags and identities survived; H3
and H4 remain loaded. Running Klipper settings report feed 55 mm, normal purge
50 mm and cross-material purge 50 mm (inherited default). No calibrated amount
was invented and no motion/heating was commanded. Existing configuration was
preserved. The r110 touchscreen binary is unchanged.

Evidence: `r111-delivery/active-settings.json`, installer log and tests under
`analysis/validation/2026-11-09-attended/`; preservation snapshots
`qualification-install-r103/r111-ready-before/` and `r111-after/` under the
8 November validation directory. Cross-family feature is now deployed; slicer
purge handoff and guided G-code swaps remain future integration work.

### Concrete print-validation jobs prepared offline — 10 November

Prepared two Orca-sliced validation jobs without upload, heating or printer
commands. Single: one 12×12×1 mm coupon, logical tool 0 intended for H3, 0.18 g,
45 s estimated model print time. Mapped: two coupons, logical tools 0/1 intended
for H3/H4, five changes, 0.18 g each, 2m21s estimated model time. Startup time is
additional. Nozzle targets 220 C, textured-plate target 60 C; process acceleration
settings limited to at most 1000 mm/s². Existing machine start/EOF behavior is
retained; the printer's startup macro still controls homing and mesh preparation.

Inputs use resolved WonderMaker ZR Ultra 0.4 mm machine and 0.20 mm process
profiles with matching pink/gray filament colors. Slicer material type is PLA;
WM+ maps those logical sources onto the loaded physical heads during review.
The actual print mapping and submission must be checked at runtime, not inferred
from the filenames. Local checks verified successful slicing, startup targets,
tool indices, and absence of injected pause/reset/configuration-save commands.
This prepares E04/E05; it does not qualify them. No paused/runout intervention is
included in this authorization request.

Reproduction and review: `analysis/validation/2026-11-10-print-preparation/`
contains `prepare.py`, `slice.py`, resolved JSON profiles, coupon STLs, generated
G-code, Orca results and `review.json` hashes. Separate operator approval was
requested because the prior instruction explicitly prohibited printing. Until
that reply arrives, the jobs remain local and printing remains disabled.

### Prepared jobs verified against installed parser and native mapping — 10 November

Copied the installed Moonraker metadata parser read-only (SHA256
`09971c854bc779f24d01ef225a86e73819515bb411387ec0251846f9aef94169`) and ran it
locally against the new coupon files. It returned one and two PLA rows, the
expected pink/gray colors, 58.19 mm / 0.18 g per row, and estimates 45/141 s.
The actual native `project_preview` accepted both files and made both loaded
PLA Matte sources eligible for their PLA rows; logical row indices remain 0/1.
The offline projection kept Start disabled. This validates these newly prepared
inputs, not a repeat of earlier unrelated print-preview acceptance.

Vendor is not exposed by the installed parser even though present in the G-code
footer; do not claim vendor guidance is available through current metadata.
Brand extraction is a future guided-swap handoff requirement. Test inputs,
`check_preview.cpp`, raw metadata and projected results are retained under
`analysis/validation/2026-11-10-print-preparation/`. No upload or print occurred;
operator authorization remains pending.

### Approved coupon execution started — 10 November

The operator confirmed “bed is clear” in response to the concrete two-print
approval request. Both hash-verified jobs were uploaded exclusively (upload
record in `2026-11-10-print-preparation/uploaded.json`). No pause/runout
intervention is included. The bed must be cleared again between these jobs.

The touchscreen single-job preview showed one PLA row, 0.18 g; selecting Head 3
showed the matching pink source and enabled PRINT. Submission was accepted and
`print_stats` reported the correct filename printing. Startup selected physical
`extruder2` and homed XYZ with H3; nozzle preparation target 140 C and bed 60 C.
Live samples are retained in `single/live/`. Completion is not yet accepted.

A separate runtime issue was observed: `wmp_case_light` reports enabled and
print_active, but value 0 and last_error `[Errno 1] Operation not permitted`.
The camera image is dark; do not count it as visual print-quality verification.
The active print has not been restarted or interrupted to investigate the light.

### Single-head coupon completed; mapped job awaits bed clearance — 10 November

The single-head job completed in 342 seconds including heat-up and 4×4 probing.
Runtime samples show physical `extruder2` (H3) for probing and model extrusion,
220 C nozzle / 60 C bed targets during printing, and 77.62 mm total recorded
filament including the startup purge. Final backend status is Ready/complete,
with all nozzle targets and bed target zero; head parked at X−13/Y275/Z51.03.
H3 remains attached and both H3/H4 loaded identities remain intact.

This accepts the observed touchscreen submission, selected physical head,
startup, model execution and EOF cleanup for the single-head case. Operator
confirmation of the physical coupon is pending because the camera is dark.
E05 remains open for the mapped H3/H4 print; it has not started. The operator
was asked to inspect/remove the coupon and purge line and confirm bed clearance
before the second job. No pause/runout behavior was exercised. Evidence:
`single/live/000.json` through `019.json`, and `single/screens/` under the
10 November print-preparation directory.

### Operator cleared first coupon; mapped print started — 10 November

The operator reported the pink square and purge line removed, confirming a
physical coupon was produced and clearing the bed for the second approved job.
The two-row touchscreen preview was mapped explicitly to H3 pink and H4 gray;
PRINT remained disabled until both rows had sources. The mapped job was then
submitted, with runtime monitoring under `mapped/live/`.

Read-only LED diagnosis now shows GPIO76 direction `out`, value `1`, value-file
owner matching Klipper's `t13dp` user, and `wmp_case_light.last_error = null`.
It remains lit during mapped-print startup and the camera view is usable. No
LED fix or permission mutation was applied in this turn; the earlier EPERM
root cause remains unproven. Do not claim it was a persistent ownership issue.

### Mapped print stopped after reported Y-front crunch — 10 November

During startup the operator heard crunching at the front while homing Y, then
reported that it eventually recovered and homed X. Live samples agree: Y was
marked homed, then X, followed by the center/Z-probing move. An emergency-stop
request was sent on the collision report and returned success. Backend shutdown
was confirmed at 71 seconds, with zero filament used in this job. No automatic
restart or second homing attempt was made. The mapped print is NOT accepted.

The running configuration confirms a dedicated Y endstop `PB8`; the virtual
TMC endstop is not configured. Y speeds are 50 mm/s first approach, 5 mm retract,
25 mm/s second approach, matching the retained stock configuration. The initial
sensorless-stall hypothesis was corrected. Eventual homing acceptance does not
explain or clear the reported mechanical impact. Its cause is still unproven;
inspect endstop actuation and physical clearance before another motion trial.

Retained evidence: `mapped/homing-incident/state-and-messages.json`, `klippy.log`,
and `mapped/live/000.json`–`007.json`. The job started from the previous print's
parked position X−13/Y275 with H3 mounted. This differs from the first coupon's
startup state and is relevant to diagnosing clearance; no cause is inferred
solely from this difference. Heater target fields may remain cached after an
emergency shutdown; do not describe those cached values as active heater output.

### Operator authorized continuation after Y-homing observation

The operator requested noting the intermittent Y-front noise and continuing.
Keep this observation open and monitor subsequent homing; stop on renewed
crunching/grinding. PB8 identifies the configured endstop signal, not the physical
sensor technology. No homing sensitivity, speeds, or endstop settings were changed.
The interrupted mapped job extruded nothing; the previously cleared bed remains
available for retry. Recovery from emergency shutdown and retry are authorized.

### Mapped retry reached four tool changes, then H4 runout pause

After operator-authorized reset, Ready was verified and the stale shutdown dialog
was dismissed. H3/H4 loaded records persisted. The same file was explicitly
mapped to H3/H4 and started through the touchscreen. Y/X homing and mesh completed;
no repeated crunch was reported during this retry (not proof the issue is fixed).
The light stayed on with no error throughout the captured run.

Runtime records show H3 model extrusion, H4 selection/heating to 220 C and model
extrusion, return to H3, then H4, then H3: four physical changes. At sample 036,
H4 presence became empty while H4 was still selected; sample 038 was paused with
H3 selected. The screen reports ZRU-M011, Toolhead 4 runout/broken. The operator
was asked to inspect gray filament; no warning acknowledgement or RESUME was
sent. H3 presence remains set, H4 presence/loaded flag are clear. The mapped print
is not complete or accepted. It remains paused pending physical inspection.

A transient “Status unavailable” appeared in the home-screen filament panel
while temperatures/progress and backend status remained live. Capture:
`mapped/retry-screens/wmp-retry-progress.png`; keep this UI observation open.
Evidence: `mapped/retry-live/000.json`–`038.json`, `retry-paused.json`, and camera/
screen captures under `retry-screens/`. No intentional runout intervention was
performed. The unexpected event does not count as guided runout/resume acceptance.

### Confirmed stock recovery escaped the unified guard

Operator confirmed gray filament broke, reinserted it, then reported unsolicited
homing/heating. Only read-only status/screenshot requests had been sent by this
agent at that point. H4 sensor presence returned but its loaded flag remained
empty, as intended. Emergency stop was issued and confirmed; do not resume the
partial print after the stop.

The command log contains stock `M109 T2 S220`, `G28 X Y`, travel to X−13/Y80,
`M83`, `G92 E0`, and `G1 E100 F400`. The compatibility log for the active client
PID says its patches were skipped because the screen was already modified.
Native command_sender and compatibility command_sender claimed the same entry;
compatibility constructor validation consequently rejected ALL its guards.
Helper-level dispatch tests did not cover this combined installation failure.

Candidate fix: install Resume preparation, auto-purge, resume-check and runout/
tangle popup routing in the same verified native hook transaction. The unified
compatibility constructor no longer competes for the command sender. Original
initial fault detection/PAUSE and unrelated popups remain untouched. Explicit
Resume delegates only to backend RESUME admission. Popup 99/100 redirects into
WM+ Filaments instead of promising stock automatic heating/purge.

Remaining recovery gap exposed by this run: H4 lost filament while a queued tool
change completed to H3; the pause origin is H3. Current paused service admits only
that mounted origin head. Cross-head runout service must preserve the affected
head separately and restore the paused head/return context; do not claim this
scenario supported by the interception fix. This partial print is not accepted.

### 2026-11-10 — r112 live hooks and PID recovery

- Installed r112; read `/proc/716591/mem` and confirmed native jump patches at resume preparation (`0x51a7b4`), automatic runout purge (`0x5328b4`), resume worker (`0x61b2c4`), popup dispatch (`0x5352e0`), and command sender (`0x614338`). Initial runout pause entry (`0x61ab5c`) retains stock instructions. This establishes live hook installation; it does not close the cross-head paused recovery gap or validate a new physical recovery cycle.
- Operator confirmed Heads 2–4 retain the September 29 physical heads/heater hardware. Backed up current printer.cfg as `printer.cfg.before-pid-restore-20261110_201515`, restored only extruder1/2/3 PID entries from the September 29 backup, preserving all prior bytes including T0, offsets, and meshes. Corrected an initially inserted blank separator (Klipper requires SAVE_CONFIG prefixes throughout); no heating/motion occurred during correction.
- After idle RESTART and startup completion, all four extruders report `control=pid` with expected gains, target 0, webhooks ready, print state standby. Evidence: `analysis/validation/2026-11-10-print-preparation/pid-recovery/verification.json`; before/after config copies retained alongside it. Partial print was not resumed.

### 2026-11-10 — mapped coupon completed after PID recovery

Operator reloaded H4 blue-gray and confirmed the bed clear, authorizing a fresh
mapped coupon. Deliberate runout recovery is deferred until attended testing.
Touchscreen submission mapped sliced T0 to H3 pink and T1 to H4 gray. The job
completed in 523.82 seconds, with startup H4→H3 selection and all five model
changes H3→H4→H3→H4→H3→H4. All 51 status samples remained Ready; both loaded
identities remained set. Completion popup and Moonraker history both report
completed. After queued cleanup, bed/all nozzle targets are zero, H4 is parked
at X−13.80/Y275.99/Z50.89, and steppers are released. No deliberate pause,
runout, or resume was invoked. Camera shows deposited material but cannot resolve
the low-contrast gray coupon well enough to qualify surface/adhesion quality.
No new print is authorized on the now-occupied bed without clearance.

Evidence: `mapped/pid-retry-live/`, `mapped/pid-retry-evidence/` under the
10 November print-preparation validation directory. The early complete sample
still had targets enabled during queued cleanup; the later captured state confirms
shutdown. Filament-used telemetry changes origin with physical tool selection
and went negative; it is not accepted as aggregate usage (slicer per-slot grams
are separate). Twelve screen status-query failures appeared near completion;
the intermittent freshness issue remains open, despite stable backend samples.

Operator observed slow travel/wiping. The installed WIPE_NOZZLE file exactly
matches the repository: 12000 mm/min (200 mm/s) strokes. Tool return is 200 mm/s,
machine maximum velocity 600 mm/s. The coupon slicer profile leaves acceleration
at 500 mm/s² for the first tool change and 1000 thereafter; current wipe/return
macros do not save/override/restore acceleration. This is a speed interaction,
not evidence of lost wipe-speed settings. No speed changes deployed in this run.

Readback additionally found the installed change_macros.cfg missing the previously
validated XY-only dock offset guard: unconditional MOVE=1 instead of conditional
Z-homed MOVE. This was the only difference from the repository file. Backed up
as `change_macros.cfg.before-xy-guard-20261110`, restored the exact existing guard,
and restarted only after print completion and all heater targets zero. No motion
was run against the occupied bed. Root cause of that configuration drift remains
unproven; do not attribute it to the vendor or installer without evidence.

### 2026-11-10 — service acceleration isolated from sliced motion

Updated WIPE_NOZZLE and tool-change begin/finish helpers to capture the caller's
acceleration, use the existing configured printer acceleration for service motion,
and restore the caller's acceleration at exit. Wipes also use 100% speed override
inside their existing saved G-code state. Tool-change exit restores the caller's
override, feedrate and modes. Machine acceleration remains 5000 mm/s²; wipe and
return feedrates remain 200 mm/s. No higher machine limit was introduced.

Actual-macro execution tests cover slow/fast caller acceleration, success, retry,
failed pickup, standalone printing/paused/idle wipes, XY-only service, and the
following sliced move. The motion suite passes 47 tests. Surrounding macro tests
passed; affected extrusion-test fixtures were updated to include real printer
acceleration settings and then passed. Configuration validation's direct-import
test required the existing `utils` import path; it passed with that path set.
XML artifacts are retained under `analysis/validation/2026-11-10-service-acceleration/`.

Deployed only change_macros.cfg and fz-wipe-nozzle.cfg after hash/idle/zero-target
checks. Printer-side originals are in `.wmp-service-acceleration-20261110`.
The immediate post-Ready preservation assertion ran before the sensor startup
settling interval; subsequent readback confirms H3/H4 identities and loaded flags
unchanged. All four PID controls and live native runout hooks remain intact.
A no-motion live begin/end check changed simulated caller settings from 500 mm/s²
and 60% override to 5000/100%, then restored 500/60% correctly. Original 5000/100%
settings were restored afterward. Position, heater targets and loaded identities
were unchanged. Evidence: `live-context-test.json`, `pid-and-hooks.json`.

This validates configuration load and runtime context restoration, not physical
wipe-speed acceptance. Bed still contains completed coupons; no further print or
movement was initiated. The cross-head paused-recovery implementation gap and
intermittent screen status-query failures remain open. This targeted development
config deployment does not qualify a newly sealed release/export package.

### 2026-11-10: status discovery cache — local validation only

Measured eight idle polls: live status is approximately 8.2 KB; object discovery adds a separate 5.9 KB request and typically 30–45 ms each cycle. Native runtime now caches discovery for 30 seconds while continuing live status polling unchanged. Errors, non-ready state, session changes and ownership mismatches invalidate discovery; status freshness is never extended by the cache. Session comparison supports both WM+ string and openACE integer identifiers.

The native lifecycle test passed, including cached polls, periodic rediscovery, session restart, and standalone-to-openACE ownership changes. `git diff --check` passed. This change is not yet ARM-built or deployed and does not establish the cause of the intermittent status failures near print completion. Evidence: `analysis/validation/2026-11-10-status-poll/baseline.json`; local test result `/tmp/wmp-discovery-cache.xml`. Bed still contains completed coupons; no new print, motion, heating or Z homing was performed for these checks.

### r113 status discovery cache deployed — 10 November

Expanded native lifecycle coverage passed for openACE removal, status transport failure/recovery, and Klipper non-ready/ready transitions as well as initial discovery, regular cached polling, periodic refresh, session changes and openACE addition. ARM build and sealed development export succeeded. Installation journal `f281a4ec40c44b9b9765a457d99f77e8` completed; this remains a qualification package, not release promotion.

Running client PID 739578 maps artifact `fd496c5177e91bdc1b0332b58dd698f5dcd55fbbbe3508c920d008fa8dc5829d`. Live process memory verifies the four runout interception hooks and command sender; stock fault/PAUSE dispatch remains untouched. H3 Sunlu PLA Matte pink and H4 Kexcelled PLA Matte blue-gray remain loaded with their identities preserved across restart. All four heaters retain PID control, with zero targets and printer Ready/standby. Initial diagnostic failures occurred during the required restart; settled polling is assessed separately.

Evidence: `analysis/validation/2026-11-10-status-poll/` contains native test XML, ARM build log, r113 export/install log, before/after state and live artifact/hooks/PID verification. Operator subsequently confirmed the bed cleared. No motion, heating or print was commanded during this update. Physical speed validation and cross-head paused recovery remain open.

Settled r113 observation: 42 additional status polls over 31.6 seconds, no additional failures (counter remained 21 from restart), live receipt continued advancing. This is idle evidence only; intermittent failures under print completion load remain unproven. Evidence: `r113-settled-polling.json`.

### Cross-head runout evidence and Resume guard — local, not deployed

The paused service gap includes a Resume admission hole: only the mounted pause-origin head was checked. WM+ now records confirmed-loaded to sensor-clear transitions during an open printing/paused SD job, keyed to the actual open file object. Capture carries those affected heads into its pause context; later clear transitions add to the same context. Resume requires all recorded heads plus the original mounted head to be loaded. Reinsertion alone cannot satisfy this gate. Old/different/closed jobs, idle observations, unknown sensors, already-unloaded heads and openACE ownership do not introduce affected-head evidence.

Focused pause/recovery tests: 73 passed. Full `test_wm_material.py`: 445 passed. Tests reproduce H4 runout before and after H3 pause capture, refusal after inlet reinsertion, and acceptance after a completed-load flag is established. No printer operation or deployment was performed. Evidence: `analysis/validation/2026-11-10-paused-recovery/`.

This is a prerequisite, not completion of cross-head recovery: service admission/UI selection still restrict to the original head. Controlled mounting of the affected head, preserving pause return coordinates/mapping/file position, and returning the original head before Resume remain to implement and validate. Keep this backend change local until that complete path is ready; deliberate physical runout remains operator-deferred.

### Cross-head paused service implemented locally — not deployed

Recorded runout heads are now admitted alongside the original paused head. The editor saves metadata to the selected affected head rather than the pause-origin head. Load/Unload uses the existing sensor-verified preparation path, retains the captured original nozzle offset (including the existing adjustment), applies the affected head's calibrated offset difference, and adds a numbered “Return original paused head” stage. It switches the physical extruder back and restores the original offset with MOVE=0 before completing. Resume still requires the original head mounted and loaded, every recorded affected head loaded, and the original file/position/mapping/saved PAUSE/PAUSEPARK context intact.

Real preparation code with simulated coupling/dock sensors passed eight flow cases: load and unload, each with successful return, purge/feed failure, return-lock failure, and calibration drift. Assertions cover no Z movement or homing, unchanged saved pause states, correct return offset/extruder, heater-off cleanup, and refusal to Resume on failures or after unload. Full material module: 453 passed, plus the subsequently added selected-head editor case passed. Five native/editor/procedure/projection/lifecycle tests passed. `git diff --check` passed.

ARM build is in progress. No new deployment, motion, heating, print or deliberate runout occurred. Physical interrupted-print acceptance remains pending with the operator. Evidence: `analysis/validation/2026-11-10-paused-recovery/wmp-crosshead-{flow,all,edit,native}.xml`.

ARM build and sealed r114 qualification export succeeded. Artifact: `37d5886cb99bfacba9df3eec5c3c7d5e74cf382f5e8344e7546511544f441ab2`. Export: `analysis/validation/2026-11-10-paused-recovery/qualification-export-r114/`. Still not deployed; r113 remains installed.

### r114 deployed and cold wipe verified — 10 November

The preload-only attempt correctly refused the old material backend and rolled back its earlier component publication. The subsequent combined `material preload` installation completed under journal `e1712ebb28f54521a6d49fb789e1f21a`. Client PID 745222 maps screen SHA256 `37d5886cb99bfacba9df3eec5c3c7d5e74cf382f5e8344e7546511544f441ab2`; installed material SHA256 is `2d28236ab48ee252843932faa2ba9816f47996668496fcce6d4bceb2dce276c1`. H3/H4 loaded identities, all four PID controls and the recovery interception hooks are preserved. This is a development qualification package, not release promotion.

With the operator-confirmed clear bed and existing motion authorization, performed the previously unverified cold wipe execution check. Prerequisite G28 X Y completed in 19.34 s, retained mounted H4, and left Z unhomed at the unchanged position. Verified both live motion macro files exactly matched the local sources before dispatch. WIPE_NOZZLE XY_ONLY=1 plus M400 completed in 4.86 s from the homed position while the caller had ACCEL=500 and M220 S60. Macro readback restored 500 / 0.6, feedrate 1500, coordinate/extrusion modes and flow; test cleanup restored original ACCEL=5000 and override=1. Final position X=-13/Y=275/Z=0, H4 attached, H3/H4 loaded records unchanged, all heater targets zero. No extrusion, Z motion, new print or deliberate runout. Camera confirms the clear bed and carriage at the wipe position. Timing includes approach travel; it is not an independent instantaneous nozzle-speed measurement.

Evidence: `analysis/validation/2026-11-10-paused-recovery/r114-{before,after,live-verification}.json`, `r114-combined-install.log`; and `analysis/validation/2026-11-10-service-acceleration/cold-{home,wipe}.json` plus camera captures. The occasional front-homing impact remains a watch item; these snapshots do not assess sound or exclude intermittent recurrence. The logical motor selection after restart/home remains its Klipper default; existing idle WMP_EXTRUDER_STEP and Load preparation reconcile the selected physical motor after attachment checks, so cold wipe did not change it unnecessarily.

### Cancellation lifecycle follow-up — local, not deployed

Found and reproduced a stale-pause guard: after an unfinished paused filament service was cancelled with its print, a later print could not capture a new pause because the guard considered the old serviced/not-ready record without checking job identity. Four cases failed before the fix. Capture now applies that record's block only to the same open file object and session. Running/unknown filament operations remain unconditional blockers. Eight regression cases cover failed/complete versus running/unknown operations across a new file or session; all 462 material-backend tests pass. r114 remains installed while the corrected package is prepared.

Also reviewed r114 diagnostics from the already-completed cold homing/wipe, without repeating motion: status polls advanced 88→394 with failures unchanged at 22 (all pre-verification restart failures). This is 306 further polls spanning the completed cold motion checks, not proof of print-end behavior or every intermittent condition. Evidence: `r114-motion-diagnostics.log`, `r114-live-verification.json`, and the `wmp-pause-reset-*.xml` files in this directory.

The r115 sealed qualification export is ready at `analysis/validation/2026-11-10-paused-recovery/qualification-export-r115/`. The native artifact is unchanged from r114; the correction is in the matching material backend. r114 remains installed pending the combined update. Operator readiness for deferred runout validation has been requested asynchronously; no answer is assumed.

### Remaining-check scope reconciliation

Reused the operator’s explicit 7 November observation that an additional 25 mm manual extrusion brought filament out of the nozzle. The earlier blanket “visual physical filament travel” entry overstated what was missing; only the direct manual-retract observation remains, not another positive-extrusion baseline. The reported intermittent front-homing impact remains a watch item, not an open-ended requirement to repeat accepted cold dock cycles. No test or machine action was performed for this evidence reconciliation.

### r115 cancellation lifecycle correction deployed

Combined material/preload installation completed under journal `54f64cc08ada458aad2e8617f927d526`. Client PID 749891 maps the unchanged r114 native artifact; material helper SHA256 `548b9898260d8b295d8dfc79d7e7902bcc7dc335655b4d1bb65a339c76b1a80e` matches the tested r115 export. Live hooks, all four PID controllers, Ready/standby, and preserved H3/H4 loaded identities verified. No motion, heating or print was issued in this deployment. Evidence: `r115-combined-install.log`, `r115-live-verification.json`, and `r115-after.json` under `analysis/validation/2026-11-10-paused-recovery/`. Physical cross-head runout remains pending operator availability.

### Print-time status investigation — 10 November, after r115

The retained mapped-coupon diagnostics show the failure count rising from 49
to 61 across approximately 307 seconds. Recorded stages include both object
list discovery (1) and live status query (2); this is not evidence of twelve
query failures confined to PRINT_END. The log aggregates counters and retains
only the latest failure stage, so it cannot classify every individual failure.
r113 subsequently cached object discovery, but no new print has qualified that
change under the same conditions. The accepted r114 cold-motion polling check
is narrower evidence and does not close this gap.

Read-only profiling against the actual installed loader and current variable
file measured stock parsing at 200–287 ms and warm cached loading at 55–61 ms.
A separate process used the installed stock SAVE_VARIABLE method and installed
cache against a disposable copy, executing the five saves in PRINT_END order.
Three batches took 498, 510 and 516 ms. The production variables file SHA256 was
unchanged and the temporary files were removed. No G-code, motion, heat, restart
or print was issued. These measurements demonstrate persistence cost, not a
causal reproduction of the live HTTP timeout: process scheduling and the live
reactor were not part of this isolated benchmark.

Do not broaden cooperative yields or relax freshness/deadline handling on this
evidence alone. The next status investigation should distinguish transport
failure reasons and correlate failures with live phases, rather than treating
all stage-2 failures as saved-variable stalls. Physical runout recovery remains
operator-deferred; bed clearance alone does not satisfy that attendance gate.

Evidence: `analysis/validation/2026-11-10-status-poll/`
`saved-loader-profile.json`, `print-end-save-profile.json` and their retained
profiling scripts; original counters in
`analysis/validation/2026-11-10-print-preparation/mapped/pid-retry-evidence/screen-diagnostics.log`.

### r116 status failure classification deployed — 10 November

The native HTTP transport now supplies fixed failure categories, and the worker
records `status_failure_kind` and `status_failure_poll_ms` alongside the existing
stage and failure timestamp. Codes are 0 other/unclassified, 1 deadline,
2 connection establishment, 3 socket I/O, 4 rejected/incomplete HTTP response.
Elapsed time covers the failed worker poll, including discovery if performed.
Only scalar codes and timings are logged; exception messages and reply bodies
are not. Existing log size/rate bounds and command invalidation remain unchanged.

The real socket test passed with a delayed successful reply, a genuine deadline,
and an HTTP 503 classified as a response failure. The native lifecycle test
passed with a timed-out status request, stale evidence, rejected queued command,
and successful recovery on the next poll. The initial socket test attempt was
blocked by sandbox socket permissions; rerunning with localhost access passed.
This is diagnostic coverage, not a claim that live status stalls are fixed.

The ARM build and package verification passed, followed by the normal exported
preload installation (journal `6417691fef4543c0a6caf7ca0672627f`). Running client
PID 754743 maps artifact
`d52f4818d810f432e80dc8a1600d122172564b71e1a8d8a7b5f143a1a3869749`.
Actual hook bytes and the unchanged material helper hash were verified. All four
heaters still use PID; nozzle targets are zero and the printer is Ready/standby.
The Moonraker dependency step did not restart Klipper, but preload activation did:
only the runtime session fields changed in the before/after loaded records.
H3 Sunlu PLA Matte pink and H4 Kexcelled PLA Matte Bluish Gray remain loaded with
their identities intact. No motion, heat, or print was commanded for this check.

The new fields are present in the live log. A startup failure is classified as
deadline (1), elapsed poll 1003 ms; the sample then has successful later receipts.
Startup failures are not a reproduction of the earlier print-time issue. Do not
claim that issue fixed or reopen accepted physical tests merely for this
instrumentation change. The package remains a development qualification, not a
release promotion. Evidence: `r116-before.json`, `r116-after.json`,
`r116-live-verification.json`, `r116-combined-install.log` in the status-poll folder.

### r116 settled observation and next physical gate

Readback of the same running process (754743) reached 147 status polls with
21 failures, unchanged from the post-install sample at 65 polls. The last failure
remained timestamp 157020186; the latest receipt was 157096499. This is 82 further
polls without a new failure, not proof of behavior during printing.

The normal first-run route still requires identification/calibration before the
filament FINISH step. No direct synthetic entry, marker deletion, or visit to the
ordinary filament page can close that end-to-end gate. Do not reset the printer
solely to reach it. Physical runout recovery is the next focused attended check;
operator readiness has been requested. Leave the printer idle while waiting.

### Stock conflict findings incorporated into the plan — 11 November

The requested audit is recorded in `docs/upstream-client-callers.md` and committed
as `6a1296d`. `docs/ui-plan.md` section 8 and structured requirements R20–R27 now
specify ownership, implementation order and acceptance for the findings. The
workflow review and generated review page share that update. Re-print and legacy
filament adapters come first, followed by recovery/cancellation ownership and
controlled configuration/service/restart work. No production fix or live
qualification is implied by this planning update. Previously accepted baseline
checks remain accepted; USB copy/profile importing remain deferred.

### Re-print request ownership groundwork — 11 November

Added `native/stock_reprint_gate.hpp` and a focused host test for popup/file
generation ownership. Completed and stopped popups can claim one review request;
duplicate taps, invalid context, replaced button identity and superseded queued
requests are consumed. Closing the popup invalidates a queued review. Unrelated
popup kinds remain delegated. The C++11 harness compiled with warnings as errors
and passed (invoked directly through its Python test function; pytest is not
installed in the current system Python).

The local implementation now hooks the actual popup builder (`0x532da8`) and
popup event (`0x5303e4`) through the verified profile/installation transaction.
The outer `draw_pop` only schedules construction, so capture occurs after the
builder has created its buttons. Completed/stopped Re-print clicks are consumed
before the vendor prefix and queue a review through the stock local-file page
and managed preview. Current popup kind, button identity, visible ancestry and
request generation are checked; ordinary Close and unrelated popup kinds retain
their vendor handlers. Navigation invalidates queued Re-print ownership.

Each preview opening also increments a selection generation. Worker metadata
from a previous opening, even at the same pathname or finishing in flight, cannot
seed the new review. This retains the five-second refresh interval within a
single review and does not add metadata to normal status polling.

Host evidence: the actual native event wrapper was compiled and exercised with
fake LVGL events and stock global storage. Both popup kinds queue one review,
do not call the vendor handler or execute its dismissal prefix, consume repeated
and hidden clicks, and allow Close to invalidate the queued callback. The full
native lifecycle harness passes, including same-file reopening within the cache
window and selection changes during a metadata response. Profile/hook binding
checks pass. The existing recovery callback test also passes.

The ARM build passed; candidate SHA256 is
`b377fae1cadcd5c78c734112f5cbfea805fad36b5906ff768a09a4f449fa6143`.
The artifact and all recorded source hashes match the current worktree.

R20 remains open until end-to-end native navigation qualification:
the host event test proves interception/cancellation, not that the actual stock
page constructor successfully opens the managed preview on the printer. No new
print is authorized or needed to check review/cancel. No deployment yet.

### Re-print candidate r117 installed; preview cancellation checked — 11 November

Installed the `16d8e0b` candidate through qualification export r117 while the
printer was ready/standby, with all nozzle targets zero and no active operation.
Installer journal: `68f75fe76cf447cea0f8e82fc250a6e1`. The installer completed;
client PID `957366` maps the expected artifact
`b377fae1cadcd5c78c734112f5cbfea805fad36b5906ff768a09a4f449fa6143`.
Live process memory confirms the popup-builder and popup-event hooks plus the
existing recovery hooks. The original initial-pause entry remains unchanged.
All four heaters retain PID control and zero targets. All four loaded-state
records, including H3/H4 identities, survived restart (session IDs excluded).

The normal managed preview was checked specifically because selection-generation
handling changed: open the single-filament coupon, select H3, CANCEL, reopen the
same file. Reopening showed `Choose source`, with PRINT disabled, and CANCEL
returned to the file list. No PRINT action, heating, extrusion or motion was
requested. Evidence is under `analysis/validation/2026-11-11-reprint/`:
`live-verification.json`, `mapped-preview.png`, `reopened-preview.png`, and
`cancelled.png`.

R20 is **not fully qualified**. The actual completed/stopped popup transition
into managed preview still needs an end-to-end check; installed hooks and normal
file preview do not prove that specific navigation path. No debugger is installed
on the printer, and no fake print completion or new print was triggered for this
check. Retain this gate for an approved print/completion opportunity or a reviewed
GUI-only harness. Continue independent work on R21 rather than repeating accepted
load/unload or print-metadata checks.

### R21 legacy filament command ownership implemented locally — 11 November

`LOAD_FILAMENT HEAD=0..3` and `UNLOAD_FILAMENT HEAD=0..3` now dispatch only
`WMP_FILAMENT_SERVICE`, which obtains a current plan and invokes the same
`WMP_FILAMENT_SEQUENCE` entry used by the screen. This retains managed admission,
request IDs, progress, cancellation, delayed context revalidation and loaded-state
completion. Optional ID supports duplicate detection. HEAD is explicitly physical;
missing HEAD, ambiguous T arguments and old temperature/distance overrides fail
before any macro command is emitted. Print-file invocation is refused because
this console adapter is asynchronous; guided swaps in print G-code remain a
separate feature.

openACE external load selects only the explicit external plan for that head.
ACE-attached load requires selecting a slot in Filaments. Unload delegates to the
current owner's verified destination. Retired `EXTRUDE_FILAMENT`,
`RETRACT_FILAMENT`, `filament_insert` and `filament_insert_gcode` refuse with a
managed alternative instead of independent heat/motion. Prepared standalone manual
steps remain available through `WMP_EXTRUDER_STEP`. Internal tip-shaping recipes
used by managed operations were preserved. The private old XYZ service-position
helper has no remaining callers in the live config; it is not a public service
entry point.

Validation: 814 backend, rendered macro, configuration and material-install tests
passed; all 26 config files passed static validation. An additional focused run
passed 20 tests after extending the existing asynchronous handoff test to the new
public entry. Coverage includes invalid/ambiguous requests, nonidentity mappings,
missing backend, duplicate requests, busy/unknown/printing refusal, ACE owner
unload/readback, refusal to guess an ACE slot, and context changes before the
queued operation obtains the G-code lock. The old test expecting legacy E100
extrusion was replaced with tests of the new ownership contract.

The matching backend/config changes were subsequently deployed together in r118;
registration and no-motion refusal checks passed as recorded below. This does not
close owner-specific openACE qualification. Existing physical load/unload results
remain accepted for the unchanged underlying sequences; this local test evidence
does not claim a new physical cycle or complete openACE qualification.


### R21 r118 deployment and refusal qualification — 11 November

Installer journal `1d015256359146f79a4cfd05ca5acb79` completed successfully;
screen PID 963571. Readback verified the sealed native artifact, active hooks,
unchanged initial PAUSE entry, idle heaters using PID, and retained H3/H4 loaded
identities. The native binary is unchanged from r117; this deployment updates
the paired backend and configuration. Effective configuration comparison changed
only the six intended legacy filament macros. SAVE_CONFIG calibration and
effective unlock, movement and wipe settings were preserved.

Eight live JSON-RPC requests were correctly refused: legacy LOAD/UNLOAD with
ambiguous T, the four retired extrusion/insertion helpers, an unsupported service
action, and Load on already-loaded H3. Position, heater targets, loaded records,
operation state and saved variables remained unchanged. No physical cycle or
print was started. Evidence: `analysis/validation/2026-11-11-legacy-filament/`
(`live-verification.json`, `refusals.json`, `effective-config-changes.json`,
and `r118-install.log`).

The first HTTP refusal attempt exposed a separate vendor Moonraker transport
defect: its error handler puts a multiline Klipper macro error into the HTTP
status reason, causing Tornado's “Newline in header” failure and disconnecting
the client. The server log confirms the macro rejected the request correctly.
Read-only state inspection confirmed idle state before further checks. The
confirmed `/server/jsonrpc` route returned all eight errors normally. Track HTTP
error serialization as an open compatibility issue; these results do not claim
that HTTP clients receive a usable refusal response. Do not automatically retry
an ambiguous disconnected physical-operation request.

### HTTP refusal serialization fix implemented locally — 11 November

The version-checked builder `tools/moonraker_http_error_patch.py` now preserves
the full application error in JSON and resets the HTTP reason to Tornado's
standard phrase before flushing headers. It changes only
`AuthorizedRequestHandler.write_error`; command dispatch, error codes,
authentication, traceback handling and JSON-RPC are unchanged. The builder
refuses altered or already-patched handlers and preserves original line endings.

Local real-HTTP tests reproduce the original stream closure and verify patched
responses for ordinary errors, trailing newlines, CRLF/header-like text, Unicode,
and status codes 400/409/503. Exact-source and duplicate guards also pass:
`uv run --python 3.12 --with pytest --with tornado==6.3.3 python -m pytest
tests/test_moonraker_http_error_patch.py -q` (3 tests). Applying and compiling the
candidate against the available 1.1.08, 1.1.12 and 1.1.13 vendor application sources
changes exactly one line and leaves all other bytes intact.

This is **not deployed** and not yet integrated into the journaled installer.
Next: add a separately tracked application-file transaction, preserve the existing
directory patch's install/rollback behavior, then restart Moonraker only while
idle and repeat the impacted HTTP refusal check. No printer restart or command
was performed for these local tests. Do not mark the HTTP compatibility issue
closed until installation, rollback and live response verification pass.


### HTTP patch journaled installation and live verification — 11 November

The dedicated installer now supports `--patch http-error` with a separate
application.py transaction and backup directory. Both source recipes run through
the existing lifecycle and integrity checks; old directory receipts keep their
schema and validation. The exported source list includes the additional builder.
The normal host component still selects only the directory patch; automatic HTTP
selection and combined host receipt handling remain packaging work.

The transaction, lifecycle, component and HTTP regression run passed 45 tests,
including both patch recipes through process-loss recovery, failed startup,
concurrent edits, file permissions and duplicate installs. A subsequent CLI test
also passed, verifying independent targets and rejection of a foreign receipt
(8 installer-adapter tests in that run).

Applied the HTTP patch while idle using the same transaction/lifecycle code.
The durable service journal at
`/home/t13dp/wmp/backups/moonraker-http-error-managed/service.json` is complete.
Moonraker restarted; Klipper did not: process 963722 and material session
`1181efd74dd442adaa74ff66bfec6cf9` were unchanged. Attachment and all loaded
records also matched. Installed application SHA256:
`6045f46ea467a0388bfcb39d660c7a9b4423b775f5268daba80e50a3a49296cd`.

All eight previously reviewed command refusals now return actual HTTP 400
Bad Request with structured error bodies, rather than disconnecting. Live
checks confirm unchanged position, zero heater targets, loaded records,
operation state and saved variables. Evidence is in
`analysis/validation/2026-11-11-http-errors/` (preflight, installed journal,
and http-refusals JSON). No motion, extrusion or print was started. This closes
the observed live serialization defect; automatic release installation remains
open as noted above. Rollback is tested locally, not claimed as an additional
live restore/reinstall cycle.


### Combined Moonraker host installer completed — 11 November

The normal Moonraker component now preflights and installs both reviewed patches.
It journals both prior states before either publication and retains separate
printer-side source/service receipts. Rollback first recovers interrupted service
operations, then restores each source to its own prior state. This ordering
allows recovery when the first patch stopped Moonraker before the second patch
had any backup. Existing directory-only host receipts remain supported.

The component/deploy/journal run passed 97 tests. After adding persistent modeled
service-stop state and its interruption scenario, all 17 component tests passed;
30 journal tests then passed including five malformed combined-receipt cases.
Coverage includes either patch already installed, failure before/after the second
publication, lost reply, old receipts, foreign second receipt rejection before
mutation, and uninstall of both managed sources. These are local transaction
and service-boundary tests, not a new live rollback cycle.

The normal host command `tools/deploy.py install moonraker --preflight-only`
passed against the printer, followed by successful
`tools/deploy.py install moonraker`. Both patches were already installed;
the installer verified them without requesting a restart. Host journal
`fe25364d18f84f2c93adfda0fd7a56b5` records the combined installation; log:
`analysis/validation/2026-11-11-http-errors/host-install.log`.
The previous automatic-selection packaging gap is closed. This does not promote
the unreleased screen bundle or close the independent R20–R27 qualification work.

### R22 durable job-material staging implemented locally — 11 November

Managed print submission now invalidates the previous recovery-material record
before its first admitted preparation command. Before standalone SD dispatch it
atomically stages `wmp_recovery_job.json` beside the filament settings, with
file SHA256, admitted file metadata, full mapping, the actually used sliced-tool
assignments, and loaded source/identity snapshots only for required heads.
Unused mapped heads do not become filament requirements. The record is fsynced
and atomically replaced; storage failure before invalidation prevents preparation.

Hashing yields between 1 MiB chunks while the G-code lock remains held. Before
publishing the stage, submission rechecks owner/admission, profile revision,
both tool maps, loaded source/identity state and file identity. A file replacement,
sensor-clear transition, owner change or map change during hashing prevents SD
dispatch. openACE submission writes an explicit owner-required marker, never
standalone recovery authority. It continues to delegate print admission to
openACE's existing public start wrapper.

The backend regression suite passed **491 tests**, including new durable-stage,
startup-failure invalidation, failed-storage, missing source identity, unused-head,
duplicate-request and hash-time drift cases. No new physical print was run.

This is **local and undeployed**. The staged record is deliberately not a
recovery authorization and is not yet consumed by Continue. Remaining R22 work:
bind/commit after successful print startup, clear on cancellation/completion,
validate restore and checkpoint context, maintain records for supported managed
mid-print replacements, and implement early single-owner preparation admission.
The existing stock recovery behavior is unchanged by this local staging work;
do not count R22 as complete or deploy it as an admission fix by itself.

### R22 startup commit and record clearing implemented locally — 11 November

The staged material record now has a startup lifecycle. START_PRINT invokes
`_WMP_RECOVERY_JOB_BEGIN` after clearing the old saved print context and before
heater preparation. A current managed submission is bound to the actual open SD
file and backend session. An unrelated direct startup invalidates old material
evidence; restart alone cannot promote an earlier staged record.

After the existing startup/purge sequence saves its version-2 mesh context,
`_WMP_RECOVERY_JOB_COMMIT` verifies the same SD file, staged bytes, loaded sources,
mapping, probing head, offsets and mesh, and refuses pending/unknown material or
tool operations. It persists the committed context and consumes the in-memory
submission. A failed dispatch or commit clears that pending submission so it
cannot be replayed against another job.

The existing print-context clear path now also calls
`_WMP_RECOVERY_JOB_CLEAR`, covering completion, cancellation and explicit context
clearing. The saved mesh context is cleared first. If material-journal storage
fails, the helper reports the failure without interrupting cancellation cleanup;
the missing mesh context remains a mandatory refusal condition for admission.

Validation: 603 backend/recovery-template tests passed. An additional executed
startup/clear macro test verifies helper ordering against actual context writes,
heating and purge commands. All 26 shipped configuration files passed validation.
New cases cover session/file/source/mapping/offset/mesh drift, uncertain operation,
changed staged file, missing BEGIN, non-SD invocation, owner change, restart,
failed SD dispatch and storage failure during clearing.

Still **local and undeployed**. A committed startup record alone is not recovery
authorization. Next: bind coordinate checkpoints to the job record, validate
restored evidence at the early Continue boundary, serialize admission/preparation,
and update evidence for supported mid-print changes. No recovery motion or
additional print was run; R22 remains incomplete.

### R22 native checkpoint/job binding implemented locally — 11 November

The coordinate sidecar writer now captures the job-record fingerprint before
the stock checkpoint write, verifies it again around sidecar publication, and
stores it with the coordinate-record fingerprint in
`WMP-GCODE-XYZ-MATERIAL-2`. A changed job cannot silently acquire an older
checkpoint even when its filename/coordinates match. The loader caches both
bindings; replacing the sidecar or material record requires reloading rather
than reusing cached vendor state.

Missing/changed job records reject bound sidecars. An existing managed record
also rejects coordinate-only legacy markers. Coordinate-only behavior remains
available when no managed record exists; this is compatibility behavior, not
permission for the future managed admission gate to skip missing evidence.
Empty, oversized, nonregular or symlinked job records cannot be stamped.
The hash binds exact bytes; it does not validate JSON state, physical loading,
or ownership and is not an authenticity/signature mechanism.

The native reader defaults to
`/home/t13dp/printer_data/config/wmp_recovery_job.json`, with an absolute
`WMP_RECOVERY_JOB_PATH` override for a nondefault material directory. Matching
this path to the backend configuration remains part of deployment integration;
no custom path may be silently treated as an unmanaged printer by the later gate.

All **12 native recovery tests passed**, including ARM coordinate-load emulation,
reviewed-client fingerprints/prologues, stable/cached material binding, changed
job during the stock writer, deleted records, malformed sidecars and legacy
coordinate compatibility. Tests compile the real C source as both a harness and
shared library with warnings treated as errors.

This remains **local and undeployed**. No live recovery, power cycle, heating or
motion was requested. Early acknowledged backend admission, serialized recovery
preparation, custom-path integration and controlled physical qualification are
still required before R22 can be considered complete.

### R22 restored material evidence validation — 11 November

The local backend now validates committed standalone recovery records against
an explicit native-selected filename, exact used-tool/source set, installed
required heads, persisted print context and calibration, saved mesh availability,
and current loaded identities. An inactive mesh after restart is permitted;
missing saved mesh or cleared context is not. Historical job session evidence
survives a new backend session without becoming a live pause origin.

File verification includes SHA-256, regular-file/path/SD-loader checks and file
identity checks before/after reading. State and record are revalidated after
hashing yields. The helper rejects unfinished or unknown material/tool operations
and changed ownership. It emits no G-code and does not grant recovery admission.

Validation: **528 material-backend tests passed**, including 22 new evidence
cases for restart, inserted-but-unloaded, selected-file mismatch, same-size and
same-mtime content changes, source/schema/context/calibration/mesh changes, and
state/record changes during hashing. The separate native selection audit has two
passing tests. These tests do not prove the still-unimplemented native/backend
admission transaction or physical recovery behavior.

Still local and undeployed. Next integration must bind the actual selected
checkpoint and native filename, admit current machine/fault/setup state, and
hold one recovery owner through preparation. Custom-path wiring and managed
mid-print evidence updates remain open. No printer operation was performed.

### R22 checkpoint-to-material verification — 11 November

The local backend now takes an explicit A/B checkpoint basename and the native
loader's cached coordinate/job fingerprints. It requires the material-bound
sidecar to match both current files and those cached fingerprints, validates the
committed material/file evidence, then rechecks all three evidence files after
hashing yields. A coordinate-only legacy marker cannot authorize this managed
path. Equivalent JSON with changed bytes also requires a fresh native load.

Evidence reads are bounded regular-file reads with no final symlink following,
nonblocking open, and before/after descriptor/path identity checks. The checkpoint
root is backend-configured (`recovery_checkpoint_dir`, default `~/TM_T1/bin`);
requests cannot supply arbitrary paths. Deployment must verify this root matches
the actual native checkpoint directory, alongside the separate job-record path.

**549 backend tests passed**, including 21 new checkpoint/reader cases and known
FNV-1a vectors. Tests cover changed coordinates/job bytes, stale cached hashes,
wrong selection, path traversal, symlink/FIFO, truncation/oversize, malformed or
legacy marker, and changes during hashing. No G-code is emitted by these checks.

Still an undeployed prerequisite: checkpoint numeric/semantic checks, fresh
machine-state admission, attempt ownership and native preparation integration
remain required. No live recovery or printer operation was performed.

### R22 checkpoint value validation — 11 November

The bound-checkpoint helper now parses the reviewed vendor INI schema with no
implicit defaults or interpolation. Missing/duplicate/extra fields, reset records,
nonfinite numbers, out-of-file or non-native-integer file positions, invalid
extrusion/tool-change modes, negative heater targets, nonpositive motion factors,
and fan values outside their stored 0–1 range are rejected. The native leveling
labels `adaptive_mesh` and `default_mesh` are recognized; neither bypasses the
separate committed `wmp_print` context/mesh requirement.

The parser retains signed G-code coordinates and extrusion positions: comparing
these directly to machine limits would ignore saved transforms. It also retains
`last_is_during_T` for explicit admission/recovery handling rather than treating
an interrupted tool change as normal. Current heater limits, transformed travel
limits and fault/attachment admission remain integration work, not guarantees
provided by this parser.

**579 backend tests passed**, followed by two focused tests against retained
vendor-produced A/B checkpoint files. Those retained-file checks establish format
compatibility only, not acceptance of historical coordinate/material evidence.
No live tests or deployment. The next step remains fresh machine-state admission
and one owned native/backend preparation transaction.

### R22 current-machine recovery review — 11 November

The local review now checks the live session and Ready state, standalone ownership
(including refusal of a competing AFC manager), idle SD/print/pause state,
identification/calibration/homing activity, saved fault/setup flags, existing
recovery activity, pending/running/unknown service operations, and consistent
physical attachment evidence. Saved heater targets and current readings must fit
configured limits; a nonzero target for an absent heater is refused.

Readiness and attachment are checked before and after checkpoint/job verification,
which yields while hashing. Missing required services/data return an explicit
unavailable-state refusal. The helper does not create a pause, clear a fault,
change a heater, or send motion. Interrupted tool-change checkpoints currently
receive an explicit refusal requiring a separate attachment recovery plan; that
supported procedure remains unfinished and is not counted as feature completion.

**614 backend tests passed**; the 33 affected review cases passed again after
normalizing missing-state errors. New coverage includes stale session, shutdown,
active/paused/SD-owned jobs, alternate owner, pending operations, setup/faults,
calibration/identification, unknown coupling, invalid/missing thermal limits,
invalid temperatures, and state/attachment changes during hashing.

Still local/undeployed. Review is not authorization: the native/backend transaction
must acquire and hold exclusive attempt ownership before consuming this evidence,
prevent changes to selected file and competing preparation, and reconcile partial
execution. Transformed travel/clearance and interrupted-tool-change recovery also
remain open. No printer operation was performed.

### R22 native preparation dependencies traced — 11 November

The read-only 1.1.13 trace found 41 separate preparation command call sites,
including mapping writes, heating, tool selection and retraction before G28.
The stock sequence captures its resume head from `current_extruder_backup`, not
from the bound coordinate checkpoint; mapping restoration uses a separate native
backup array. Our saved `context.tool` identifies the probing head and cannot be
substituted for the execution head at the checkpoint position.

The [recovery contract](../print-mesh-recovery.md#native-preparation-ownership-findings--11-november)
now requires checkpoint-bound execution-head evidence and an owned preparation
procedure. Preferred direction is one immutable native request consumed by a
backend procedure, with no delegation to the unrestricted stock sequence. The
existing evidence/readiness helpers remain prerequisites, not a complete gate.

The reproducible ELF inspector verifies these globals, instruction windows and
command sites. All three focused provenance tests passed. No live operation.
Next work must capture execution context consistently with checkpoint position
and implement the owned procedure; historical records without that evidence need
an explicit recovery contract. Do not mark R22 complete merely by refusing them.

### R22 coherent execution snapshot reader — 11 November

The retained Klipper SD worker reports `file_position` after command dispatch;
`get_file_position()` instead returns the next position while a command may still
be executing. The local snapshot reader therefore refuses `is_cmd_from_sd()` and
captures public completed-file position, G-code coordinates/modes/origin, current
mapping, physical attachment, active extruder and loaded identity without any
reactor yield. It requires a committed job and completed print startup. The probe
reference and execution head are deliberately different in the positive test.

Parser completion is not physical motion completion. The reader uses read-only
`toolhead.check_busy()` to require empty lookahead and capture scheduled/estimated
MCU print times; it never calls `get_last_move_time()` (which can flush lookahead),
M400 or any other G-code. A snapshot with scheduled time ahead of observed time
is still pending physical execution. It is not persisted as recovery authority.
A subsequent completion/publication mechanism must retain the exact snapshot,
wait for its scheduled motion time, and invalidate it on session/fault changes.

**633 backend tests passed**, then **21 focused snapshot cases passed** after
adding scheduling checks. These cover active SD commands, startup/paused state,
owner/operation/fault/mapping/attachment disagreement, different active extruder,
changed source/file, invalid coordinates/modes, nonempty lookahead and invalid
motion clocks. Tests fail if capture yields, uses next-file position or sends
G-code. No deployment or physical test occurred.

Next: durable publication of completed execution snapshots and the backend-owned
recovery transaction. Native A/B compatibility and current transformed travel
constraints still need integration; this reader does not make R22 complete.

### R22 pending execution snapshot publication — 11 November

A local lifecycle now retains one immutable execution candidate until its scheduled
motion time passes, rather than replacing it with newer buffered state on every
poll. Publication checks the original session, Ready/owner/job state, exact job
bytes, committed context, fault flags, required loaded identities, active file,
non-regressing file position and motion clocks. It writes a completed execution
record atomically with fsync and restrictive permissions. Later parser/head state
does not rewrite the captured historical boundary.

Pending evidence is discarded on failure and on shutdown/disconnect. A failed
atomic replacement preserves the previous record and removes the temporary file.
The new `wmp_recovery_execution.json` is execution evidence only: no timer or API
invokes this lifecycle yet, and the recovery entry does not consume it. Matching
the coordinate/thermal snapshot and native selection, admission ownership and
travel validation remain required before it can authorize recovery.

The full backend run passed 652 tests and exposed one missing disconnect-callback
invalidation, which was corrected. All 19 affected publication/lifecycle tests then
passed, including the added file-rewind case. The initial readiness field had
been initialized correctly but the event callback needed its own invalidation;
the new test exercises the callback directly. No deployment or printer operation.

### R22 self-contained execution state and restore validation — 11 November

Execution capture now includes installed-heater targets, main/auxiliary fan
fractions, optional chamber-filter fan state and elapsed print time in the same
non-yielding snapshot as file position/head/parser state. Fractional temperatures
are preserved; subsequent heater/fan/timer changes do not alter the pending
boundary. Missing required state, invalid fractions, nonfinite values and targets
outside configured heater limits are refused.

The completed-record reader validates its exact schema, historical session/job
identifiers, coordinates/origin, modes, speed factors, motion completion times,
heater/fan fields, execution-head mapping/source, file identity and unfinished
position. It verifies the current committed job fingerprint and loaded material
evidence, then rereads execution/job bytes after file hashing yields. A restart
alone does not invalidate a completed record; current-machine readiness remains
a separate required check before any preparation.

**684 backend tests passed.** New coverage includes thermal capture, optional fan,
later-state isolation, valid restart restore, malformed records, premature
completion times, wrong mapping/head/job, and mutation during verification.
No timer, native entry or public recovery command consumes the completed record
at this stage. No deployment or printer operation occurred. Native selection and
the exclusive backend recovery procedure remain the next integration gates;
records from different positions must never be combined to fill missing fields.


### R22 sampling cost and command exclusion — 11 November

Capture now refuses while the G-code mutex is held, including external commands
which are not marked as SD dispatch. Capture and publication validate the active
open SD descriptor against the committed path/size/modification identity without
recursively enumerating the G-code directory. Initial file selection and recovery
admission retain the exact loader-entry checks and content verification.

All **686 backend tests passed**. New tests explicitly fail if capture/publication
enumerates files and verify a locked command cannot queue a snapshot. Existing
file-replacement, readiness and publication failure coverage remains passing.
No deployment or printer actions. Low-frequency timer wiring, deduplication and
exclusive recovery entry/preparation remain outstanding.


### R22 backend sampler lifecycle — 11 November

A one-second backend timer now captures and publishes execution evidence locally.
It skips idle/non-standalone jobs before reading evidence and skips command-lock
periods. A pending immutable candidate is retained until its motion time matures;
publication records a session/job/file-position key to suppress duplicate writes.
Storage or validation errors clear pending state without killing the timer. Ready
reuses the existing timer handle; disconnect/shutdown stop it and discard pending
state. The durable prior completed record is preserved.

**690 backend tests passed**, including timer reuse/stop, no idle evidence reads,
completion without repeated writes, and recovery after injected storage failure.
No deployment or physical operations. Native admission, owned preparation and
geometry/migration integration remain open; this sampler does not authorize resume.

### R22 completed-record selection and current-machine review — 11 November

The completed execution reader is now composed with current-machine readiness:
review binds the explicitly selected execution fingerprint, verifies historical
job/file/material evidence, then rechecks live session, idle state and attachment
following yielding verification. Heater targets retain fractional values and are
checked against current configured limits and actual temperatures; recorded fans
must still exist. The execution bytes are reread before returning the review.

All **697 backend tests passed**. Added cases cover valid selection, changed
fingerprint, reduced heater limit, missing fan, stale session, and machine/attachment
changes during hashing; every case verifies that no G-code was submitted.
This remains a read-only review helper, not an owned recovery attempt. Native
request integration, serialized preparation and geometry/migration contracts are
still required. No deployment or physical test occurred.

### R22 coordinate evidence and endpoint bounds — 11 November

Source review found that G92 changes the parser base independently of homing
origin. Local execution schema 2 therefore captures both parser and transformed
machine endpoints. Restore validates all four coordinate vectors, and current
review checks the transformed XYZ endpoint against current machine travel bounds.
Mesh restoration consistency and object-aware travel are still unimplemented;
endpoint admission alone does not authorize motion.

**708 backend tests passed.** Added coverage includes G92/extrusion-factor base
reconstruction, distinct mesh-adjusted Z, malformed/missing coordinate evidence,
old schema rejection and reduced/nonfinite/missing machine travel bounds. No
printer deployment or motion occurred.


### R22 installer record location and missing-evidence policy — 11 November

Active configuration now supplies the native recovery record location through the
transactional preload service environment. Managed installations require job
evidence instead of silently downgrading to coordinate-only compatibility when it
is missing. Path resolution runs before publication intent; custom paths, includes,
space/percent escaping and drop-in rollback have offline coverage.

74 native/installer tests passed, followed by 3 focused environment/refusal tests
including a new missing-active-config case. The first run exposed outdated installer
fixtures without active printer configuration; those fixtures now model the actual
read. No live install or service restart occurred. Native request ownership and
backend preparation remain outstanding.

### R22 durable stage runner — 11 November

Added a local RecoveryAttempt runner for the forthcoming owned preparation path.
It snapshots the request, persists pending/running state before any dispatch,
requires a separate explicit completion verifier per stage, and persists stage
completion before advancing. A failed dispatch, verification or journal write
prevents later stages and leaves an unknown outcome. Restored pending/running
journals become unknown; unresolved and duplicate attempts cannot be retried.
Cancellation stops before the next stage without claiming instantaneous motion
cancellation. Nested attempts are refused.

The backend plus initial runner suite passed **716 tests**; all **10 runner tests**
then passed after adding initial-journal failure and truthy-but-unconfirmed result
cases. This is local execution infrastructure only: no registered command invokes
it and no printer commands were added. The integration must hold command ownership,
supply validated immutable evidence, persist via the atomic journal writer, expose
receipts, reconcile cancellation/unknown outcomes, and implement/verify actual
preparation stages before connecting the native recovery entry. No deployment.

### R22 recovery receipt backend lifecycle — 11 November

RecoveryAttempt is now initialized from a bounded, no-symlink journal beside the
material records, using the existing atomic fsync writer. Interrupted receipts
are durably marked unknown on restore. Exact journal/request/stage validation
rejects malformed records, out-of-order stage completion and a completed receipt
with incomplete stages. Backend status exposes a copy of the receipt.

Active or unresolved recovery prevents new managed filament plans (including
openACE-owned plans), toolhead actions via idle admission, print submissions,
filament-settings idle admission and Resume. Tests verify these exclusions after
a simulated restart and ensure changing returned status cannot clear the hold.
This is not yet a global raw-G-code lock or a native recovery entry. The future
command must still retain command ownership, define safe stopped-outcome
reconciliation and execute the reviewed preparation stages.

**726 backend/runner tests passed.** No deployment or physical action. There is
still no public command that creates a recovery attempt, so this receipt lifecycle
does not enable recovery by itself.

### R22 explicit parser-state restoration — 11 November

Added the final parser restore helper without wiring recovery motion. Source
review confirmed vendor RESTORE_GCODE_STATE omits coordinate bases and that
reported feedrate is mm/min. Restoration now uses explicit offset/G92/factor/mode
commands, preserves current physical E after priming, and verifies unchanged pose
and restored readback. It refuses until the commanded transformed/parser XYZ
pose is reached and buffered motion has completed.

The combined backend/runner/parser suite passed **735 tests**; all **11 parser
tests** then passed after adding buffered-motion guards. These use the retained
vendor GCodeMove implementation, covering all absolute/relative combinations,
G92 with extrusion scaling, nonzero mesh Z, no coordinate delta, stale pose,
missing command ownership, malformed input and ignored command detection.
No deployment or physical action. Owned preparation and native handoff remain open.

### R22 initial preparation stages — 11 November

Added an initial stage factory for the durable runner: establish recovery context,
home Z at the existing supported bottom reference, then explicitly home X/Y and
drain motion. Each stage verifies its own context/reference/axes before advancement.
The guard binds the parsed job and fingerprint to one read, retains the admitted
attachment, and rechecks session, owner, Ready/idle state, fault flags, offsets,
committed context, loaded sources and competing service operations at boundaries.
No tool-selection, heater, purge, return or SD-start stage is included yet.

The combined backend/runner/parser suite passed **745 tests**. All **10 focused
reference-stage tests** passed after adding loaded-source/service drift checks and
binding the parsed job to the fingerprinted bytes. Tests model macro outcomes and
prove dispatch order and suppression of later stages; they do not qualify physical
homing. There is no public/native caller and no deployment or printer motion.
A completed initial-stage test is not a completed recovery operation; the final
integration must append and verify all remaining stages before exposing recovery.

### R22 physical heater/fan target stages — 11 November

The initial stage factory now includes heater-target and fan-target restoration
after reference establishment. Heater names are physical extruder/bed objects;
logical M104/M109 addressing is never used. Targets are checked against current
hardware limits before dispatch, and state/ownership/fault guards run before each
command. Stage completion requires matching target/fan readback.

The retained WM M106 macro truncates S to an integer. Main-fan restoration uses
its renamed native M99106 command, whose vendor implementation accepts a float;
auxiliary/optional air fan use named SET_FAN_SPEED commands. This preserves the
captured normalized fan fractions.

**752 backend/runner/parser tests passed.** New cases cover ignored heater/fan
commands, a fault appearing between heater commands, and cold heaters whose
targets are accepted. Target acceptance is explicitly not temperature readiness;
there is no wait/extrusion/return/SD-start stage yet. No native/public caller,
deployment, heating or printer motion occurred. Full preparation and controlled
physical qualification remain required before enabling recovery.

### R22 stable temperature wait — 11 November

Initial preparation now includes a separate heating stage after target restoration.
It requires every nonzero target to remain within ±2 C for two seconds; leaving
that range resets the stability interval. Zero targets do not require cooling to
zero. The loop yields every half second, rechecks target/current temperature and
recovery state, and stops on cancellation, clock regression or a bounded 20-minute
timeout. A final readback is required before the runner advances. Volatile
current/target readings are exposed as recovery_temperatures, without fsync per poll.

**760 backend/runner/parser tests passed.** New simulated-clock cases cover stable
warmup, temperature excursions, changed targets, invalid sensors, faults,
cancellation, clock regression and timeout. No live heating or deployment.
Failure leaves the receipt unknown and prevents continuation; heater cleanup and
stopped-outcome reconciliation still need integration before a public/native
recovery command can be enabled. Tool selection, purge/return, mesh/clearance and
SD continuation remain unfinished.

### R22 failure/cancellation heater cleanup — 11 November

Added the admitted-stage wrapper and heater-only cleanup receipt. A failed or
stopped chain that reached heater-target restoration attempts to turn off each
captured physical heater and checks target readback. Cleanup never submits motion,
retries preparation or clears the original failure. It continues checking other
heaters after an individual command failure, but sends nothing across a changed
printer session/owner or without command ownership. Cancellation before the heater
stage preserves pre-existing manual targets.

Cleanup results are validated and persisted in the attempt journal. Failure to
persist cleanup leaves the attempt unknown; the original exception is retained.
Stopped attempts now also block conflicting managed operations until deliberate
reconciliation, even when heater-off readback succeeds. Cleanup confirmation is
not evidence that earlier physical preparation completed safely.

The combined backend/runner/parser suite passed **766 tests**; all **16 runner
tests** then passed after adding an explicit stopped-attempt retry test. New cases
cover cancellation, a stock fault, lost heater-off acknowledgement, cleanup disk
failure, restart persistence, changed owner and cancellation before heating.
No deployment, live heating or motion. Stop reconciliation, tool selection,
clearance/mesh/purge/return and native continuation remain unfinished.

### R22 explicit stopped-attempt abandonment — 11 November

Added a private abandonment path for an explicitly selected stopped/unknown
attempt in the current printer session. It requires command ownership, Ready/idle
state, no stock fault/setup/calibration/identification or competing service,
zero heater targets, and unambiguous attachment. It drains already queued motion
with M400 and verifies completion; it never homes, moves, heats or retries.

The path binds the attempt to its execution/job evidence, invalidates continuation
before clearing runtime recovery flags, resets only the matching selected SD file,
clears the saved print context, then records an abandoned receipt with the current
session and observed attachment. Loaded flags and filament metadata are untouched.
Changed job/file ownership is refused. Partial failure retains the hold; an explicit
retry may finish the same abandonment, never repeat recovery preparation.

**776 backend/runner/parser tests passed**; all **10 abandonment tests** then passed
after adding the other-selected-file guard. Cases cover successful restart-safe
release, hot heaters, stock fault, ambiguous attachment, unfinished motion, stale
session/request, another job/file, and ignored flag clearing. No live commands or
deployment. The method has no public/native caller; user-facing confirmation,
remaining preparation and live qualification still need integration.

### Design/plan reconciliation — 11 November

Reconciled the stock-conflict audit into the current R20–R27 plan and refreshed
R22 in both the design and structured plan data. Local recovery prerequisites
are distinguished from the still-unwired native handoff and unfinished physical
preparation/continuation. Added explicit requirements for parser versus machine
coordinates, sensor-verified head selection without stock retry/fault clearing,
durable stage outcomes, separate cleanup/abandonment, and numbered UI progress.
Filament service remains XY-only; recovery bottom-Z is a separate operation.

R23–R27 remain open ownership/qualification work, not completed fixes. Validation
stays scoped to changed or impacted behavior; accepted ordinary load/unload
evidence is reused. This reconciliation changes documentation only: no deployment,
printer commands or new physical validation.

### R22 single-attempt coupling prerequisite — 11 November

Found an additional C06 boundary: stock LOCK itself invokes four retry checks,
so bypassing the outer tool-change retry wrapper is insufficient. Added a private
recovery coupling primitive that performs one initial actuator stroke, drains
motion, disables the actuator, then verifies finite Hall and boolean lock-sensor
readings under the caller's ownership guard. It neither retries nor clears faults.

All **790 backend/runner/parser tests passed**, including 13 new coupling cases
covering threshold boundaries, contradictory/invalid sensor readings and ownership
loss after dispatch. The primitive is not yet integrated into physical head
selection; dock seating, clearance and unique head identity remain caller duties.
No deployment or printer motion; existing filament service is unchanged.

### R22 physical head selection and actuator audit — 11 November

Added a private physical-head selection sequence with bottom-reference/axis and
calibrated dock bounds checks. It verifies seating before release, coupling before
departure, unique physical head identity after departure and active extruder
readback. Same-head selection emits no carriage travel; empty-carriage selection
skips release. It neither clears stock faults nor enters stock LOCK retries.
All **804 backend/runner/parser tests passed**, including failure at each physical
boundary and a fault appearing during docking. No deployment or live movement.

This is not yet connected to the initial-stage factory. Further source inspection
found that the vendor ECHELON_STEPPER_HOMING handler suppresses homing exceptions
and still executes its post-distance move. Integrating an error-propagating
actuator path is required before enabling this selection sequence. Simulated
sensor/command tests do not qualify the vendor actuator implementation. Full
mesh/clearance/purge/return and native continuation remain incomplete.

### R22 actuator error propagation — 11 November

The private coupling path now bypasses the vendor command that swallows homing
errors. Its adapter invokes the retained lower-level homing API directly and
allows the post-home lock stroke only after success and renewed ownership checks.
Failure stops the sequence; best-effort actuator disable preserves the original
exception and is withheld if ownership changed. No stock handler was changed.

All **812 backend/runner/parser/actuator tests passed**. Eight actuator tests use
the actual retained vendor `do_homing_move` method with a simulated homing backend:
failed homing cannot reset the actuator position or send the lock stroke, post-move
failure is not retried, cleanup failure preserves the first error, and ownership
loss prevents follow-up commands. Sensor/selection tests model actuator outcomes
separately. Native entry/stage integration and mechanical qualification remain
open; no deployment, heating or printer motion occurred.

### R22 head-selection stage integration — 11 November

Connected physical head selection to the private initial-stage runner after
bottom-Z/XY homing and before heaters. The runner persists selection intent before
dispatch, permits intended attachment transitions only inside that operation,
then binds later guards to the selected head. Calibration is captured at factory
construction and checked against current saved values during selection.

The broad recovery run passed 813 cases and exposed four incorrect new assertions
expecting no cleanup receipt before heating. The wrapper intentionally records a
successful no-op cleanup with no heaters; the assertions now verify that receipt.
All five focused integration cases then passed. They cover a deliberately changed
head, cancellation, stock fault, unconfirmed attachment and coupling exception;
failed selection retains an unknown attempt and emits no heater commands.
No native/public entry, deployment or physical test. Remaining recovery stages
and physical qualification are still required for complete recovery.

### R22 mesh-bound execution and restoration stage — 11 November

Added schema-3 execution evidence binding active mesh interpolation and transform
settings, and a restore_mesh stage before heaters. It validates the restored
fingerprint and transformed saved XYZ before permitting further preparation.
Updated active-print test fixtures to load their mesh after simulated restart;
production checks still refuse capture without an active saved print mesh.

All **826 backend/runner/parser/actuator tests passed**. New cases reject changed
grid/fade/tool offset, inactive mesh, inconsistent transformed endpoint, malformed
or nonfinite grids. These are host tests; physical mesh/return clearance is not
qualified. Prior local execution schemas need an explicit migration route before
release, as do nondefault runtime mesh offsets if required. Native integration,
purge/wipe/return and file continuation remain open. Nothing deployed.

### R22 runtime mesh-offset restoration — 11 November

Extended the local schema-3 record with mesh X/Y/ZFADE offsets and restores those
explicitly after profile load. Fingerprint/endpoint validation still follows;
changed static grid or fade configuration remains a refusal. Invalid recorded
offsets are rejected before dispatch. This removes the previously noted gap for
nonzero runtime mesh offsets.

All **836 backend/runner/parser/actuator/mesh tests passed**. Ten new tests execute
retained vendor BED_MESH_OFFSET, fade-factor and inverse-position methods with
simulated hardware, covering nonzero offsets across the fade range and invalid
inputs. Planned purge/return travel must use an explicit uncompensated machine
frame to avoid bottom-Z compensation overflow, then restore the verified transform
before continuation. Route clearance and the remaining execution stages are still
unfinished. No deployment or physical motion.

### R22 machine-coordinate stage before head selection — 11 November

Added and integrated a verified no-motion machine-coordinate setup stage before
dock travel. It clears mesh/tool offsets and reconciles G92 XYZ to physical XYZ,
while preserving the extrusion base/mode/factor. Ownership, homing and completed
motion are required before any setup command; ignored state changes or unexpected
physical movement prevent advancing to head selection.

All **847 backend/runner/parser/actuator/mesh tests passed**. Eleven new cases use
the retained vendor parser to cover prior G92/tool shifts, relative mode, feed
override, each ignored setup command, unfinished motion, missing reference,
invalid position and ownership loss. Updated the mesh-offset refusal test to
simulate incorrect post-command readback rather than an old offset successfully
replaced by profile loading. No deployment or physical movement. Purge/return
travel, route clearance and final continuation/native integration remain open.

### R22 guarded purge-position travel — 11 November

Connected bottom-reference XY travel to the private recovery stage chain after
warmup. The entire route is bounds-checked before setup; uncompensated machine
coordinates, bottom reference and stable bounds are required throughout. Each
move drains and verifies its endpoint with unchanged Z/E. The path exits X first
and travels along X=-13 to Y80 at 12000 mm/min.

All **856 recovery/backend tests passed**. Nine added cases cover invalid later
waypoints, nonfinite/bool inputs, ignored motion, unexpected Z/E motion, unfinished
motion and cancellation. Failed travel sends no next waypoint, retains unknown
outcome and turns off the attempt's heaters. No extrusion or physical test occurred.
Object-clearance qualification, purge/wipe, return and file/native continuation
remain required; this private stage is not permission to expose recovery yet.

### R22 configurable priming and guarded wipe — 11 November

Integrated separate prime and wipe stages after purge-position travel. Priming
uses recovery_purge_mm (fallback load_purge_mm), physical-head heat/readiness and
bounded E-only moves; each move verifies commanded E advancement and unchanged
XYZ. Wiping uses saved position and configured speed, four 35-mm stroke pairs,
through guarded bottom-reference XY travel. It does not enter the stock wipe
macro's hidden preparation/state-restoration paths.

All **867 backend/runner/parser/actuator/mesh tests passed**. Eleven added cases
cover configured prime/limit splitting, cold state, ignored extrusion, lost reply
after extrusion, changed Z/target, cancellation, configured wipe geometry/speed,
and wipe failures after successful prime. Failures preserve unknown outcome and
clean up heaters; completed priming remains recorded and is never auto-replayed.
Physical filament flow is not established by commanded E readback. No deployment
or physical test. Return clearance, final pose/parser/file continuation and
native/UI integration remain open.

### R22 physical return and final mesh stages — 11 November

Added separate return_xy, return_z and return_mesh stages after wiping. Return XY
stays at bottom Z, moving along the off-bed edge before crossing to the saved X.
The vertical stage requires confirmed saved XY and bottom reference, validates
limits and restores physical Z without changing E. Final mesh restoration follows
verified movement. Priming advancement is preserved, never reset to historical E.

All **874 backend/runner/parser/actuator/mesh tests passed**. Seven new cases cover
ordering, ignored vertical motion, XY/E drift, unfinished motion, cancellation and
final-mesh failure. Failure sends no repeated Z/prime command, retains unknown
outcome and turns off the attempt's heaters. No native continuation is emitted.
These are host simulations: object-clearance admission and physical qualification
remain open, along with parser/file/native/UI continuation. Nothing deployed.

### R22 parser-state integration — 11 November

Connected explicit parser restoration after return_mesh, with ownership checks
around each command. The integration fixture now executes the retained vendor
parser during this stage, including its real G92 and extrusion-base behavior.
Historical logical E is restored while physical E retains the recovery prime.

All **881 recovery/backend tests passed**. Seven added cases cover all coordinate/
extrusion mode combinations with feed/flow overrides, ignored G92, cancellation
and a stock fault during restoration. Failed restoration retains unknown outcome,
cleans up heaters and never submits SD continuation. File selection/seek/start,
object-clearance admission and native/UI integration remain open. No deployment
or physical test. Source review also identified root-only M23 enumeration as a
requirement for the forthcoming exact-file handoff, not a completed fix.

### R22 exact-file selection/seek integration — 11 November

Added select_file after parser restoration in the private durable stage chain.
The exact checkpointed file is hashed and identity-checked, opened with explicit
subdirectory support, and positioned at its validated byte/line boundary. The
opened descriptor, SD offset and actual stream position must agree. No worker
start or print continuation is issued.

All **898 recovery/backend tests passed**. Thirteen retained-vendor-loader cases
cover nested/UTF-8 paths, invalid offsets, changed content, wrong selection and
unacknowledged seek. Four integration cases cover successful positioning, ignored
seek, lost seek reply and owner change after load. Failed handoff retains unknown
outcome with completed preparation stages preserved and no automatic replay.
No deployment or physical test. Elapsed accounting, final worker handoff,
object-clearance admission and native/UI integration remain open.

### R22 elapsed-time and filament accounting — 11 November

Local checkpoint schema 4 retains elapsed time, printing time and signed native
filament usage together. The private final-handoff accounting helper establishes
the current E baseline through vendor note_start and restores historical values.
It does not start the SD worker and is not added to preparation stages. Repeated
or unacknowledged starts are rejected. Native pause/resume and completion retain
the recovered totals; recovery preparation and priming are not counted again.

The full **910 recovery/backend tests passed**, including twelve new accounting
cases using retained vendor PrintStats. Four further reader cases explicitly
reject the old schema and malformed new fields (validated in the focused reader
suite). Final worker acknowledgement/integration and interruption reconciliation
remain required before any public recovery entry. No deployment or physical test.

### R22 durable worker scheduling — 11 November

Added a private dormant-worker handoff to the attempt runner. Scheduling remains
inert until all stages pass and the complete receipt is read back from disk.
Activation occurs under command ownership; the callback waits for its release.
Failure or last-moment Stop disarms the callback, including lost timer replies;
unregister failure does not skip heater cleanup. Rejected duplicate requests do
not disarm an already accepted worker.

The full **922 recovery/backend tests passed**. After adding the duplicate-request
isolation check, all **50 file/accounting/worker/attempt tests passed**. These are
host scheduling tests, not physical continuation evidence. The preparation stage
factory still ends at file selection. Mapping/print-ready and accounting stages,
post-handoff outcomes, native/UI integration and clearance qualification remain
open. No deployment, print or physical recovery was performed.

### R22 private continuation chain — 11 November

The explicit continue_print option now adds verified live/backup route and
print-ready restoration, native accounting restoration and dormant worker
registration to the preparation chain. The attempt runner activates only after
durable completion. Host integration runs the retained vendor SD worker and
confirms exactly the next checkpointed line, nonidentity maps and preserved
elapsed/printing/filament totals after completion.

All **931 recovery/backend tests passed**. Eight new cases cover the complete
chain, ignored route/flag writes, lost accounting/activation replies and Stop
after accounting. A further changed-job cleanup test verifies that another
accounting context is not cancelled; all nine focused continuation cases passed.
Failed owned handoff cancels its idle accounting context and cleans up heaters;
changed ownership/context remains unknown. These are simulated motion tests,
not physical recovery qualification. No deployment or native/public activation.

### R22/R27 recovered-worker error outcomes — 11 November

The recovered worker now records complete, deliberate pause/cancel or unknown
continuation outcomes. Its configured error script is temporarily replaced with
heater-only shutdown, preventing the stock CANCEL_PRINT movement/context-reset
prefix after a failed dispatch. Generic vendor exceptions that surface as an
unrequested pause are treated as unknown. Callbacks are single-use, and the
original error template is restored after the worker returns.

All **935 recovery/backend tests passed**. Three new retained-worker cases cover
command errors, generic exceptions and deliberate pause; failed lines are never
replayed and stock CANCEL_PRINT is never submitted. Eight additional journal
restore/validation cases passed in the **24-test attempt suite**. Broader direct
Cancel, subsequent native Resume worker ownership and crash-window reconciliation
remain open. Source evidence is added to the stock-callers audit. No deployment
or physical test was performed.

### R22 restart-interrupted continuation — 11 November

Scheduled and started worker phases are now durable and bound to the committed
job and starting byte position. On restart they become interrupted/unknown;
preparation completion alone no longer releases the recovery hold. A private
explicit reconciliation path accepts only a new completed checkpoint from the
interrupted session and same job, at or beyond the starting position. It retains
the job and loaded filament records and issues no physical commands. A subsequent
attempt still requires fresh complete admission.

All **952 recovery/backend tests passed**. Nine new cases cover restoring both
worker phases, unchanged/foreign/backwards checkpoint refusal, busy/changed owner,
valid reconciliation and journal mutation during hashing. Missing superseding
evidence retains the hold. Native/UI reconciliation and route-clearance admission
remain open; nothing was deployed or physically tested.

### R22 physical bottom reference versus travel limit — 11 November

Source review found the real Z endstop at 300 mm and travel maximum at 305 mm.
The local recovery checks incorrectly equated these. Dock selection, priming,
XY travel and vertical-return prerequisites now use the configured positive
endstop, while endpoint checks retain the travel limit. The stage factory binds
that reference before dispatch and rejects invalid or changed configuration.
Bottom homing must also confirm physical Z at the endstop before XY homing.

The full **960 recovery/backend tests passed** with unequal endstop/limit fixture
values. After adding the early wrong-position rejection, all **11 focused
reference/continuation tests passed**. No printer configuration or live motion
changed. Printed-object clearance admission remains open and must use the actual
300-mm homed separation, not the 305-mm travel allowance.

### R22 conservative deposition-envelope primitive — 11 November

Added a job/file-bound monotonic physical deposition ceiling, rounded upward and
persisted before a new-height segment can be queued. Positive-extrusion kinematic
segments include both endpoints; travel, retraction and E-only service purge do
not inflate the bound. Failed persistence prevents dispatch and uncertain queue
acceptance prevents replay. Clearance calculation uses actual bottom reference,
required gap and head-offset span.

All **13 focused tests passed** using the retained vendor Move class. They cover
sequential-object height retention, write ordering/count, Z+E deposition,
extrusion-only exclusion, failed writes/queues, restored evidence, descending
segments, record isolation and the 300/305-mm reference distinction. This is a
local primitive only: motion-queue/lifecycle persistence and admission integration
remain next, including shutdown handling if persistence fails after Klipper has
advanced commanded_pos. No deployment or physical motion occurred.

### R22 deposition observer/lifecycle integration — 11 November

The local backend now observes the validated lookahead queue below mesh transforms.
Managed BEGIN creates the bound record before startup motion; COMMIT preserves
it and CLEAR stops recording. Ordinary unmanaged moves pass through unchanged.
New bounds are saved before enqueue. Recording/queue errors and ownership changes
invoke shutdown because vendor commanded_pos has already advanced; they cannot
fall into stock movement from an unexecuted position.

All **984 recovery/backend/envelope tests passed**, including the retained vendor
ToolHead.move ordering, startup/commit/clear lifecycle, restore/new-job isolation,
failed writes, changed owner and replaced-hook refusal. No deployment or physical
test. Durable envelope binding in recovery review, continuation seeding and
configured clearance admission remain next.

### Recovery clearance admission — 11 November (local, undeployed)

Execution review now binds the durable deposition record to the exact job/file,
checks all-head Z offset span against the actual positive-Z endstop and configured
required gap, and retains the envelope hash and clearance calculation. Preparation
rechecks this evidence before dispatch; changed records/settings refuse motion.
A low checkpoint nozzle position cannot hide a taller previously printed object.

Validation: 991 affected backend/recovery tests passed, including seven new cases
for missing/foreign/tall envelopes, actual endstop versus axis maximum, offset span
and post-review changes before first dispatch. Python compilation and diff checks
passed. No deployment or physical recovery occurred. Resumed-envelope observer
restoration, native handoff, UI and physical qualification remain open.

### Resumed deposition recording — 11 November (local, undeployed)

Private recovery continuation now requires a supported queue before preparation,
restores the reviewed envelope without lowering its bound, and checks recorder,
session, queue hook and durable record before SD dispatch. The retained vendor
worker integration test preserves an earlier 80 mm object during lower deposition
and persists 81 mm before higher deposition is queued. Missing/replaced/failed
recording or a changed durable record prevents file-body execution and records an
unknown outcome with heater-only cleanup.

Validation: 996 backend/recovery tests passed before the final durable-record
readback addition; all six focused lifecycle/handoff cases passed afterward,
including that new case. Compilation, diff checks and R22 plan-data consistency
passed. No printer deployment or physical test occurred. Native immutable handoff,
UI, record migration, owner-specific and physical qualification remain open.

### Immutable recovery selection consumer — 11 November (local, undeployed)

Added a private versioned request consumer binding backend session, explicit
standalone owner, selected filename, native checkpoint/job hashes, managed
execution hash and deposition SHA-256. It requires command ownership and checks
current readiness before running the existing managed continuation chain. Native
selection remains checked by preparation guards; resume coordinates and byte
position come solely from the coherent completed managed record. Asynchronous
native samples cannot override individual managed fields.

Validation: 1,012 affected backend/recovery tests passed. New coverage includes
full consumer-to-vendor-worker continuation, wrong/stale selection fields,
duplicate JSON keys, missing mutex, changed checkpoint after review and duplicate
request without repeated preparation. Compilation, diff and plan-data consistency
checks passed. The native callback and public command registration remain pending;
no deployment, heating, motion or physical recovery test occurred.

### Native Continue selection interception — 11 November (local, undeployed)

The managed checkpoint branch now copies the loaded file/checkpoint/hash selection
and calls a versioned unified-screen receiver after releasing its record lock.
It never invokes stock preparation for a managed selection. Missing receiver,
refusal, missing/empty/changed filename and stale checkpoint/job evidence do not
fall back to stock start. Unmanaged coordinate-only behavior remains unchanged.

Validation: 15 native hook/stock-selection tests passed with Unicorn enabled,
including host shared-library compilation, supported-ELF/prologue checks and ARM
coordinate emulation. New harness cases confirm no stock start on managed
selection delivery, missing/refusing receiver or changed/missing filename.
Diff checks passed. Unified receiver/submission and UI are still pending, so this
intermediate candidate was not deployed and no physical test was run.

### Managed Continue / preparation STOP API — 11 November (local, undeployed)

Registered explicit `WMP_RECOVERY_CONTINUE REQUEST=<hex JSON>` and the reactor
`wmp/recovery/stop` endpoint. STOP binds the current session/request/owner and
records intent without taking the G-code mutex or issuing hardware commands.
The worker retains responsibility for cleanup and durable stopped/unknown results.
A scheduled continuation receipt is not reported as proven resumed printing.

Validation: 1,018 affected backend/recovery tests passed. Six new cases cover
command receipt semantics, STOP with the command mutex held, stale/wrong request
and owner refusal, and STOP during heating with zeroed recovery heater targets,
no purge and no SD worker dispatch. Compilation, diff and plan consistency checks
passed. Native receiver and progress/stop screen integration remain pending;
no deployment or physical operation occurred.

### Read-only native selection review — 11 November (local, undeployed)

Added `wmp/recovery/review` to resolve native filename/checkpoint selections into
an immutable backend request, completed execution and clearance details. It
refuses busy command ownership before/after review, stale selection, missing
records and files outside the G-code root; it performs no preparation. The C++
request builder retains native selection and response bindings before producing
the one-shot Continue command. Native receiver/background dispatch/UI wiring is
still outstanding.

Validation: 27 related native-selection/Continue/STOP/review backend cases passed;
after the final ownership-race case, all seven review cases passed. The C++ host
test compiled with warnings as errors and passed binding-change/invalid-selection
cases. Python compilation and diff checks passed. No deployment or motion.

### Background recovery delivery — 11 November (local, undeployed)

Added a runtime-lifetime C++ delivery worker with independent Continue and STOP
transports, fresh owner/session admission, consumed-ID protection and exact
receipt matching. Status can update and STOP can be delivered while command
acknowledgement is blocked. Lost acknowledgements do not replay requests or
replace authoritative results; scheduled continuation remains pending.

Validation: three C++/loopback host tests passed with warnings-as-errors builds.
Coverage includes blocked command acknowledgement plus concurrent STOP/status,
lost acknowledgement, unrelated execution receipt, duplicate ID, session change,
late authoritative completion and bounded recovery-only large command bodies.
Exact review/stop routes pass; route suffix/query variants are refused. No runtime
activation, deployment or physical operation occurred.

Remaining before activation: connect native receiver and progress panel, provide
visible request-bound pre-admission refusal results (without overwriting an
attempted journal), and expose the supported reconciliation/abandonment actions.
Do not leave an operator with an unexplained permanent unknown-delivery hold.

### Recovery refusal reporting — 11 November (local, undeployed)

The Continue command now reports request-bound pre-admission refusals separately
from the durable attempt. New valid tickets are tracked through review; failures
before journal creation report `refused`, while failures after dispatch remain
`attempted` with their durable unknown/stopped outcome. Duplicate/refused tickets
cannot silently retry or overwrite an attempted receipt. The C++ worker accepts
only matching refusal identities and preserves authoritative results across late
HTTP errors.

Validation: 1,028 backend/recovery tests and two C++ request/worker tests passed.
New cases cover known refusal without commands, corrected-payload ticket reuse,
duplicate delivery preserving an attempted journal, post-dispatch failure staying
unknown, unrelated refusal rejection and refusal preservation after lost HTTP
acknowledgement. Python compilation and diff checks passed. Native receiver,
progress panel and explicit reconciliation/abandonment controls remain pending;
no deployment or physical operation occurred.

### Recovery progress panel — 11 November (local, undeployed)

Added the numbered, scrollable recovery panel with gray completed, orange running
and white future stages, current/target heater temperatures and top-row CLOSE /
STOP actions. Updates preserve widget identity and scroll position. Stale status
disables STOP; delivery acknowledgement remains distinct from physical stopping.
Closing the panel does not cancel the operation or reopen it on the next sync.

Validation: the native LVGL lifecycle test passed, including retained widgets,
colors/temperature updates, stale STOP rejection, duplicate-tap suppression,
terminal state updates and parent deletion. This is component acceptance only;
native receiver/runtime wiring and interrupted-result controls remain open.

### Native recovery runtime integration — 11 November (local, undeployed)

The exported native selection receiver now copies bounded filename/checkpoint
arguments into the recovery worker. Bootstrap supplies separate command and STOP
transports; ordinary polling supplies fresh raw helper status. GUI timers open
and update the progress panel without network waits. Repeat selections reopen
the same result, retain an already visible panel and never resend Continue.
Protocol/owner/stale-state refusals occur before a new submission.

The worker distinguishes scheduled, printing, paused, cancelled, complete and
unknown continuation outcomes, retaining continuation errors. Printing/paused/
uncertain attempts cannot be replaced by a new selection. CLOSE only hides the
panel; explicit native selection can reopen it.

Validation: three native runtime/lifecycle/worker tests passed, then the worker
test passed again with explicit continuation-state coverage. All 15 native
recovery interception/ARM-emulation tests passed. ARM candidate build and receiver
export verification are recorded with this change. No deployment, printer motion
or physical recovery occurred. Interrupted-result reconciliation/abandonment UI,
record compatibility, owner-specific and physical qualification remain open.

### Interrupted recovery resolution commands — 11 November (local, undeployed)

Added explicit read-only action review and `WMP_RECOVERY_RESOLVE` for reconcile /
abandon. Tickets bind the current session, original attempt, journal SHA-256 and
execution fingerprint. Review validates action prerequisites without releasing
the hold. Command admission repeats evidence checks; duplicate tickets do not
repeat cleanup or overwrite the original result. Partial cleanup stays unknown;
a fresh explicit review can complete the same abandonment without preparation.

Validation: all 1,050 affected backend/recovery tests passed, including 22 new
cases for public resolution success/refusal, no-motion abandonment, unchanged
loaded records, job-preserving reconciliation, stale journal/execution/session,
owner/mutex changes, invalid payloads, duplicate delivery and read-only review.
Python compilation and diff checks passed. Screen action controls and native
qualification remain pending; no deployment or printer operation occurred.

### Screen controls for recovery resolution — 11 November (local, undeployed)

Connected DISCARD / REVIEW to background action review and a separate CONFIRM
submission. Immutable request validation binds ticket, original attempt, current
session, action and evidence hashes. Status cannot confirm an action. A restored
unknown/stopped attempt opens once without commands; Close preserves it, stale
status disables actions, and explicit Continue reopens the held result. Final
resolution remains visible without recreating the panel on status updates.

An unconfirmed delivery cannot be repeated. A matching backend-recorded partial
failure permits a new explicit review/confirmation; another backend session uses
its durable attempt rather than replaying the old ticket. Exact resolved attempt
identity releases the corresponding local recovery hold. Backend review refusal
messages explain prerequisites such as turning heaters off.

Host coverage includes independent review/confirmation, duplicate taps, stale or
changed bindings, unrelated receipts, lost acknowledgements, recorded partial
failure, restored-hold display, terminal results and preservation of widget
identity. Exact transport route checks and native runtime compilation also pass.
The ARM candidate is built locally; native visual/touch qualification and
controlled physical recovery remain open. No deployment or printer operation.

### Deployment recovery contract — 11 November (local, undeployed)

Post-restart native-screen acceptance now requires the recovery review, Continue,
STOP and resolution protocol versions plus registered `WMP_RECOVERY_CONTINUE`
and `WMP_RECOVERY_RESOLVE` commands. An older loaded helper cannot pass merely by
supporting the filament APIs. Acceptance remains read-only and does not require
homing. Existing rollback restores the previous UI/helper generation without
applying the new candidate's protocol contract to that restored generation.

Validation: all 176 affected deployment/backend-acceptance/readiness/rollback
tests passed. A hash-bound review archive was produced at
`/tmp/wmp-recovery-review.tar.gz` (SHA-256
`f273192615dd60ef5be0b5bf0dad5e64ac55e61a78d8208d356b4cb58d025242`).
The archive is a review artifact, not an activated or installable release.
No printer contact, restart or motion occurred.

Record compatibility remains open: current reads require completed execution
schema 4 and reject older schemas; earlier records lack some required geometry /
mesh / accounting evidence. Rejection alone does not establish a supported
upgrade or migration flow for an interrupted print. Preserve original records;
do not invent missing physical evidence or silently fall back to stock recovery.

### Design reconciliation — 11 November

Updated the authoritative R22 requirement and structured plan together with the
current closure checklist. The latest deployment API checks and local resolution
controls are implementation evidence, not native-screen or physical acceptance.
The [schema-history findings](../print-mesh-recovery.md#saved-execution-compatibility-evidence--11-november-local)
now have an explicit upgrade/disposal closure gate. Specific refusal handling is
still local work; preserving records does not establish a migration path.

R23–R27 remain open: independent configuration writers, calibration editor saves,
nested actuator retries, restart callers, direct Cancel/service ordering and
later Resume workers. Existing guards cover their identified routes only. No
new deployment, machine operation or validation pass is claimed by this update;
accepted unaffected tests remain accepted.

### Recovery-record refusal validation — 11 November (local, undeployed)

Recovery review now explains unsupported execution versions, missing execution
checkpoints, unreadable JSON and missing deposition-clearance records. Format
validation runs before the envelope lookup so an incompatible record is not
hidden by a secondary missing-file error. The native worker preserves the
bounded backend explanation and sends no Continue after review refusal.

The affected backend suite passed 1,057 tests before the final review-ordering
adjustment. After that adjustment, 41 focused backend/native-worker checks
passed, including both new missing-envelope ordering cases, preserved record
bytes and no command/timer dispatch. These results do not qualify migration,
native visual behavior or physical recovery. No printer contact occurred.

The matching ARM candidate built successfully (SHA-256
`58caccbe88a4e12a9fbb5c5c3a32461578dd66c4db0eda09554520fb703fdfe3`).
It remains undeployed. A separate source trace confirmed that later Resume/M24
registers a fresh unwrapped vendor worker; the R27 audit now identifies the exact
boundary and required targeted follow-up.

### R27 later native Resume worker — 11 November (local, undeployed)

A retained-vendor test reproduced the previously traced gap: pause before SD
body dispatch, native `do_resume`, then a command error ran stock `CANCEL_PRINT`.
The regression now passes with a job/attempt/session-bound worker retained across
pauses. Initial and resumed workers share heater-only error cleanup and durable
outcome reporting. Resume/M24 retain vendor pause return/timer semantics;
preparation and accounting initialization are not repeated. Completion or native
file reset restores the exact prior handler.

Binding checks run in `WMP_CHECK_RESUME` before stock return and again before
SD dispatch. A changed session/owner/file/job or missing deposition evidence
cannot dispatch the print body. Repeated pause/resume keeps accounting and
original preparation intact. Unknown dispatch outcomes retain a recovery hold.
Direct Cancel/service/queued-command ordering remains separate unfinished work.

Validation: all 1,066 affected backend/recovery tests passed. Four strengthened
entry-point refusal tests passed after changing their invocation to
`WMP_CHECK_RESUME`. The ARM candidate/manifest build completed successfully;
there was no deployment, printer contact, motion or physical acceptance.

### R27 direct Cancel audit reproduction — 11 November

Five targeted checks passed: two retained-mutex/rendered-macro reproductions and
three existing native reset/pause-clear checks. The reproductions confirm gaps,
not successful managed cancellation: stock Cancel cannot record intent while
service owns the mutex, and its macro still performs retract/wipe with unknown
managed state. The [caller audit](../upstream-client-callers.md#r27-direct-cancelservice-ordering--11-november-reproduced-locally)
now defines the remaining reactor intent, admission fence, owned cleanup and
separate legacy console/API coverage. No implementation/deployment or physical
acceptance is claimed for that remaining route.

### R27 cancellation core — 11 November (local, not connected)

Implemented private durable intent/fence and command-owned cleanup primitives.
The intent path records before scheduling, signals service STOP and waits for SD
and G-code ownership. Cleanup adds no retract/wipe/home/tool-selection movement,
verifies heater targets and clears only its bound print. Partial service records
remain; pending restart state becomes unknown without replay. Phase/final receipt
storage failures cannot falsely report cancellation complete.

All 23 focused cancellation checks passed, including retained-vendor SD cancel,
partial cleanup, changed session/owner/job, mutex and SD-worker waits, duplicate
intent, journal restore and storage failures. The full affected backend/recovery suite passed 1,089 tests, covering the shared
admission gates and existing recovery behavior. Public transport, interrupted-result resolution, native/legacy caller
integration and stale queued-request generations remain open. No deployment,
printer operation or physical acceptance is implied.

### R27 reviewed Cancel transport — 11 November (local, undeployed)

Added separate read-only review and reactor-confirmation endpoints, advertised as
`print_cancel_protocol = 1`. Review retains the real SD handle and returns a
bounded-lifetime one-use token. Confirmation consumes it before scheduling;
changed fields/session/owner/readiness, expiration and same-name reopened files
cannot transfer authority. Lost acknowledgement retains the original receipt;
retries do not resubmit. Exact native loopback routes are allowed with bounded
payloads and suffix/query variants refused.

Eleven focused backend API checks and the real-loopback transport check passed.
All 1,100 affected backend/recovery tests passed, and the ARM candidate built
successfully (SHA-256 `d0df585fbb9159fa2a17259f37db090ab2d45d47032a922bc2c3bdc142d793d4`). Native Cancel dispatch, interrupted
cleanup resolution, old queued-request invalidation and legacy console/API
routing remain open. No printer contact or physical acceptance is implied.

### Design reconciliation: cancellation audit — 11 November

Updated the design, structured R27 requirement and current checklist with the
confirmed SD-error fallback, later Resume worker lifetime and mutex-blocked direct
Cancel findings. Added explicit cancellation intent/cleanup ordering, stale queued
request invalidation and interrupted-result resolution requirements. Local
resolution code is work in progress; this documentation update claims no new
test pass, deployment or physical acceptance. Removed stale descriptions that
called the reproduced direct Cancel ordering an unanswered audit question.

### R27 interrupted cancellation resolution — 11 November (local, undeployed)

Added read-only `wmp/print/cancel_resolve_review` and one-use, request-bound
`WMP_RESOLVE_PRINT_CANCEL` confirmation. Reviews distinguish original live-file
cleanup, remaining idle cleanup, explicit saved-job discard and command-free
acknowledgement of verified completion. Changed evidence/session/owner refuses
confirmation; partial failure retains the cancellation hold. Lost response cannot
replace a completed result. Matching recovered paused continuation is recorded
as cancelled while unrelated uncertain operations retain their evidence.

Validation: 21 focused resolution/cleanup/native-loopback checks passed; all
1,119 affected material/recovery backend tests passed. ARM candidate built with
SHA-256 `f348ad81797fc9de2832308e32f3de86099c2f3ae88e7937ebaf5d1289e71662`.
Logs: `/tmp/wmp-cancel-resolution-tests.log` and
`/tmp/wmp-cancel-resolution-arm.log`. No printer contact or deployment. Native
Cancel and resolution controls, legacy routing, stale queued-request invalidation
and deployment capability acceptance remain open, followed by qualification.

### R27 backend request generations — 11 November (local, undeployed)

Cancellation intent now advances a session-local command generation before its
journal write. Previously admitted toolhead callbacks check both session and
generation under command ownership; filament plans/tokens and delayed service
callbacks retain their admitted generation. Clearing or explicitly resolving
cancellation does not revive earlier requests. New requests use the new
generation. Explicit filament cleanup captures a fresh cleanup admission while
preserving the original operation record, including after restart.

Validation: 490 focused checks passed, followed by 1,124 affected backend tests
including delayed reviewed/public service callbacks after completed cancellation,
retired toolhead callbacks, stale filament tokens and cleanup of an older saved
generation. Log: `/tmp/wmp-cancel-generation-tests.log`. Plan JSON/text consistency
and diff whitespace checks passed. No native code changed and no deployment or
printer contact occurred.

This closes only backend-admitted callback/token lifetime. Touchscreen commands
and console/API commands still waiting upstream of backend admission need
generation-bound delivery/dispatch; native and legacy Cancel routing remain open.

### R27 standalone transport generation guard — 11 November (local, undeployed)

Standalone delivery now checks the captured generation before sending and puts
`WMP_CHECK_COMMAND_GENERATION` before the command in the same RPC script. The
backend rejects changed session/generation, unresolved cancellation or changed
owner. Explicit filament/toolhead cleanup uses its own newly captured admission.
Projection includes generation in the configuration revision; loaded-backend
acceptance requires the new protocol and command. openACE remains on its existing
owner path. Cancellation also advances generation before completing cleanup,
retiring requests captured during the hold as well as before it.

Validation: 1,211 affected backend/deployment acceptance tests passed before the
final hold-release increment; 32 focused tests then passed against that final
change. Retained vendor `run_script` tests prove refusal aborts subsequent heat
and motion lines. Three native delivery/projection/real-loopback checks passed.
ARM build succeeded with SHA-256
`986b7a6d45da5dd2ac843217dec3a62320ab9af691ae423eb7f57c01f03e45a7`.
Evidence logs: `/tmp/wmp-generation-transport-tests.log`,
`/tmp/wmp-generation-release-tests.log`, `/tmp/wmp-generation-native-focused.log`
and `/tmp/wmp-generation-transport-arm.log`. The final backend-only change does
not alter native build inputs. No deployment or printer contact occurred.

Native stock Cancel dispatch, its progress/resolution controls, arbitrary legacy
console/API routing and owner-specific acceptance remain open. This guard does
not globally fence unguarded G-code.

### R27 independent native Cancel delivery — 11 November (local, not wired)

Added `PrintCancelWorker`, with a dedicated HTTP worker independent of filament
command delivery and status polling. It captures session/file/generation, performs
read-only backend review, verifies the exact returned identity/token and rechecks
ownership/freshness before sending one cancellation intent. It never falls back
to stock CANCEL_PRINT. Duplicate pending/uncertain clicks retain the same result.
Matching backend receipts are authoritative; delayed HTTP replies or lost replies
cannot downgrade recorded completion or trigger retransmission.

The new host C++ regression passed under `-Wall -Wextra -Werror`. It exercises
blocked replies with concurrent observation, duplicate clicks, lost replies,
unrelated receipts, changed session/generation/file/owner/freshness during review,
wrong review identity and unavailable protocol/owner/job/held-cancellation states.
Log: `/tmp/wmp-cancel-worker-tests.log`. This component is not yet included in the
runtime or ARM candidate; native button interception, progress/resolution UI and
legacy routing remain open. No backend changes, deployment or printer contact.

### R27 durable cancellation stages — 11 November (local, undeployed)

Cancellation now journals ordered, independent stopping/draining/cooling/
invalidating/cancelling/clearing-pause stages. Verified completion is recorded
separately from starting a stage. Drain failure remains failed even when heater
shutdown succeeds; later authority/file cleanup remains pending. Interrupted
running stages become unknown without rewriting the saved record on startup.
Version 2 adds stages; version 1 remains readable without invented history.
Malformed stage data retains an unresolved hold.

Validation: 101 focused cancellation checks and 1,137 affected backend tests
passed. Evidence: `/tmp/wmp-cancel-stages-tests.log` and
`/tmp/wmp-cancel-stages-all.log`. No native changes, deployment or printer contact.
The native Cancel button and numbered progress/resolution panel still require
integration; this record establishes their authoritative stage data.

### R27 native Cancel route and stage panel — 11 November (local, undeployed)

Connected the independent Cancel worker to runtime status observation, its own
bootstrap HTTP transport and exact stock `CANCEL_PRINT` interception. Fresh
openACE ownership retains its current route; standalone refusal never falls
back to the stock motion macro. Added a cancellation mode to the retained WM
progress panel with numbered stages and CLOSE-only presentation. Duplicate
pending clicks reopen the same receipt without resubmitting. Status updates keep
widgets/scroll position; Close does not cancel or replay cleanup.

Validation: 88 selected native runtime, worker, LVGL lifecycle and loaded-backend
acceptance checks passed. They cover route classification, independent review/
intent, duplicate/reopen behavior, panel dismissal, stage colors and preservation
through stale updates. ARM build passed, SHA-256
`f50e85cc1a8096ed517793ec169c1bc3b3626ca5354d88376601bce2fb52c750`.
Logs: `/tmp/wmp-cancel-native-integration.log`, `/tmp/wmp-cancel-native-arm.log`.
No backend behavior changed, so accepted backend tests were not repeated.

Remaining: native interrupted-result review/confirmation and restored holds,
legacy/compound console/API cancellation routing, owner-specific and physical
qualification. This candidate remains local; no printer contact or deployment.

### 11 November — native interrupted-Cancel resolution (local, undeployed)

Connected a dedicated review/confirmation worker and transport to the retained
Cancel progress panel. Identified restored holds open once without dispatch;
explicit REVIEW shows the backend-selected cleanup consequence, including saved-
job discard, and CONFIRM sends the exact one-use request. Session/owner/record
changes invalidate confirmation. Matching terminal receipts survive lost replies;
duplicate taps cannot replay cleanup. CLOSE only dismisses the panel.

Validation: 94 selected native/runtime/worker/backend-acceptance tests passed.
After adding the restored-hold interaction test and final runtime retention guard,
worker/runtime checks passed and the final native lifecycle rerun passed (including
REVIEW/CONFIRM, duplicate taps, retained completion and widget count). The ARM
candidate built successfully with SHA256
`090bfbf40e0dde071139cd3b82d56f7c491dcae36e94afed27c86cb98b5ac32b`.
Logs: `/tmp/wmp-cancel-resolution-integration.log`,
`/tmp/wmp-cancel-resolution-lifecycle.log`,
`/tmp/wmp-cancel-resolution-lifecycle-final.log`, and
`/tmp/wmp-cancel-resolution-arm.log`. The intermediate lifecycle run exposed a test
lookup of the old button caption after it changed; the final test taps the same
widget twice and passes. No printer contact, deployment, motion or print occurred.
Legacy console/API and compound Cancel routing, native-screen qualification and
physical cancellation/recovery acceptance remain open.

### 11 November — legacy Cancel ingress and native batches (local, undeployed)

Implemented native batch/syntax recognition and a backend pre-mutex Cancel route
for standard remote Cancel, console script requests and direct SD dispatch.
Nested standalone macro Cancel refuses stock cleanup; other owners retain their
route. Cancel batches do not run their prefix/suffix. Existing arbitrary non-
Cancel console queues remain a separate unresolved gate.

Validation: 209 cancellation/deployment-acceptance checks passed; the affected
backend/recovery suite passed 1,151 tests. The final focused run passed 15 tests,
including SD dispatch exit and the retained vendor remote Cancel handler. Native
Cancel worker/routing tests passed. ARM candidate SHA256:
`39e529ca6fd90961e45c6557a05ca70a4cb0d373fd733f90bc561d66faf611f4`.
Logs: `/tmp/wmp-legacy-cancel-tests.log`, `/tmp/wmp-legacy-cancel-backend.log`,
`/tmp/wmp-legacy-cancel-final.log`, `/tmp/wmp-legacy-cancel-arm.log`.
No printer contact, deployment, motion or print occurred. These tests establish
local behavior, not owner-specific or physical cancellation qualification.

### 11 November — legacy script generation fence (local, undeployed)

Legacy run_script batches now capture cancellation generation before the mutex
wait and check it before every non-comment command. A changed session/generation,
changed owner or unresolved cancellation aborts the remaining batch. This includes
cancellation during an earlier yielding command. Isolated heater shutdown and
reviewed cancellation resolution remain available during a hold; adding another
command removes that exemption. Exact M112 keeps its original dispatch semantics.
Already executing commands/macros are not preempted.

Validation: the affected backend/recovery/deployment suite passed 1,265 tests.
After extending the guard to every command boundary, the final cancellation,
queue-ordering and deployment-contract run passed 230 tests. Tests use the retained
vendor dispatcher with controlled mutex release, including actual managed intent
and completion during the wait. Logs: `/tmp/wmp-console-generation-all.log` and
`/tmp/wmp-console-generation-final.log`. The earlier focused fixture lacked the
vendor readiness flag for comment handling; the corrected runs pass.
No native code changed, so no ARM rebuild or repeated physical test was needed.
No printer contact or deployment occurred. R27 now needs deployed/native/remote,
owner-specific and physical qualification rather than another queue implementation.

### 11 November — r119 installed; live idle qualification

The source-sealed development export was installed through the normal combined
config/material/preload installer. Journal
`7d614a6c7dc0419daf51ad59d8b041f9` completed; screen PID 1066139 maps candidate
`39e529ca6fd90961e45c6557a05ca70a4cb0d373fd733f90bc561d66faf611f4`.
This is development qualification, not release promotion. The initial repository
preflight refused the stale legacy bundle without publication; the refreshed
source-bound export passed all checks before installation.

After restart, Klipper is Ready/standby, native bootstrap is Running, required
recovery/cancellation/generation protocols and commands passed installer readback.
Status polling continued after the restart-related failures stopped increasing.
Only wmp-screen-runtime.cfg changed: managed job begin/commit/clear hooks. Effective
settings changed only for those three macros and wm_material defaults. All saved
variables, four heater PID settings, mesh/offset and travel/wipe settings remained
unchanged. H3 Sunlu pink PLA Matte and H4 Kexcelled Bluish Gray PLA Matte retained
their loaded state and identities. The native Filaments framebuffer verifies
those cards after restart.

Four live idle requests refused as intended: cancel review with no open print,
legacy CANCEL_PRINT, a batch containing Cancel, and a stale generation followed
by a harmless log command. Position, targets, print/pause state, filament records,
operation receipts and cancellation generation remained unchanged. The deliberate
stale-command notification was cleared using the stock notification UI. No
homing, motion, heating, extrusion or print was started.

Evidence: `analysis/validation/2026-11-11-managed-cancel/` contains the sealed
r119 export, installer/preflight logs, configuration plan/diff, before/after
snapshots, preservation comparison, idle refusal responses, native diagnostics
and framebuffer captures. A local `cancel-wait-only.gcode` (log / 30-second dwell /
log) is prepared but has not been uploaded or run. Successful active-job Cancel,
interrupted-result screen actions, physical recovery and supported-owner
qualification remain open; idle refusals do not establish those results.


### R23 disposable vendor-writer characterization — 11 November

Four pinned-source tests passed in `tests/test_vendor_config_writer_failures.py`.
They execute the retained shell scripts against temporary directories and prove:

- Missing saved calibration is detected only after live printer replacement.
- An invalid head count selects the four-head template.
- Topology shrink drops excluded-head PID sections and deletes the source file.
- Factory restore continues after failed copies and can return success with a
  mixed configuration when its final copy succeeds.

Command: `uv run --with pytest pytest -q tests/test_vendor_config_writer_failures.py`
— **4 passed**. This changes R23 from source-only evidence to disposable execution
reproduction. The managed transaction, caller integration and preservation/
rollback acceptance remain open. No printer contact, reset or deployment occurred.


### R23 interrupted-publication building block — 11 November (local)

Extended the existing configuration publisher rather than adding a second atomic
write implementation. It now retains reviewed candidate bytes alongside exact
originals in its backup directory. `recover_interrupted()` validates the retained
journal, destination allowlist and both byte hashes before using the existing
compare-before-restore path. It refuses missing/corrupt/linked evidence and
concurrent destination edits. It performs no restart or operation admission and
requires an explicit caller; successful/finished publications are not treated as
interrupted ones.

Validation: `uv run --with pytest --with jinja2 pytest -q
 tests/test_screen_config_reconcile.py tests/test_vendor_config_writer_failures.py`
— **72 passed**, including six new process-loss/recovery cases. The first run
identified one fixture selecting a newly created file instead of an original
backup, and missing Jinja in the test environment; both were corrected for the
successful run.

Scope remains the installer's existing two allowed configuration files. This is
not yet a general factory-reset/topology transaction or a deployed recovery route.
R23 still requires full candidate planning, caller ownership, calibration/identity
migration, complete write-set protection and post-restart admission. In particular,
CAN discovery has an independent template overwrite before the helper script and
continues UUID changes despite failed helpers. No printer changes were made.


### R23 explicit remote recovery transport — 11 November (local)

The existing source-shipping configuration transport now exposes explicit
`action='recover'` with a required backup directory and no reconstructed plan.
It reports `rolled-back` only after verified restoration; conflict or missing
proof yields `rollback-unconfirmed`. No automatic restart, helper rollback or
printer admission is implied. Documented this distinction in `config/README.md`.

The remote script itself was executed against disposable interrupted fixtures,
including a concurrent edit that must remain untouched. Missing backup and mixed
review/recovery requests are rejected. Configuration and vendor characterization
suite: **75 passed**. Factory/topology caller integration remains open; this
transport is a supporting recovery mechanism, not completion of R23. No printer
contact or deployment occurred.


### R23 hardware-bound PID planning — 11 November (local, not publishing)

Source review confirms `MappingTransaction` currently publishes UUID changes only;
it does not migrate the PID calibration associated with the previous identity.
Added pure `plan_saved_pid_mapping()` for a verified permutation of the same
hardware set. Complete saved PID records follow normalized CAN identities while
all non-heater bytes, including mesh and active configuration, remain unchanged.
Missing/partial/duplicate/nonfinite/negative or unrecognized heater records refuse
planning; replacement, expansion and shrink are not inferred from a permutation.

Validation: `uv run --with pytest pytest -q tests/test_identification_pid_mapping.py
 tests/test_identification_transaction.py tests/test_identification_session.py
 tests/test_identification_commands.py` — **91 passed**, including all 24 four-head
permutations, inverse restoration and malformed/ambiguous evidence cases.

This helper is not called by live identification yet and performs no writes. R23
still needs effective-calibration provenance (including active include overrides),
identity-bound per-head state migration and a joint UUID/calibration/state commit.
Publishing PID independently would leave a mixed state on interruption. No printer
contact, tuning, identification or deployment occurred.


### R23 standalone filament-state migration planning — 11 November (local)

Added `plan_filament_state_mapping()` alongside the saved-PID planner. A complete
snapshot explicitly represents presence or absence of `wmp_filaments.json`,
`wmp_filament_loaded.json` and `wmp_hotend_materials.json`. Entries follow the
verified hardware permutation, including mixed residual-material history. Missing
records/flags remain missing; no sensor reading is interpreted as a completed
load. Identity records use the material owner's existing validator. Duplicate
JSON keys, unknown heads, invalid loaded flags/history, unsupported hardware sets
and owner size-limit violations refuse planning. Unchanged records retain exact
bytes; planners do not mutate input snapshots or publish files.

Validation: **128 passed** across the new state-planning tests, all PID
permutations, and identification transaction/session/command regressions. Coverage
includes all 24 four-head permutations, missing state, invalid metadata, corrupt
history and serialization size limits. No printer access or deployment occurred.

Joint publication remains open. The future transaction must also resolve nozzle
settings and effective calibration provenance, bind the owner/session and guard
active or unresolved job/operation records. This planner covers standalone data
only; it must not rewrite ACE-managed sources or authorize recovery of an old job
against a changed topology.


### R23 combined head-configuration candidate — 11 November (local)

`plan_head_configuration()` now composes UUID, saved PID, nozzle diameter/material
and the three standalone filament records into one candidate snapshot. It checks
active MCU identity, heater control/gains and nozzle diameter against source
configuration; pending edits or differing overrides refuse planning. Nozzle
migration reuses the existing field parser/editor, preserves comments and other
settings, and refuses missing/unknown material, duplicate fields or auto-saved
diameter overrides. Source and destination identity sets must match exactly.

Validation: **180 passed** across combined-candidate, PID/state mapping, nozzle
and identification tests. All 24 head permutations verify UUIDs, PID, diameter,
material and sparse loaded flags together; unchanged mappings remain byte-exact.
Tests also cover inconsistent runtime evidence and incomplete snapshots. Mesh,
probe offset and custom motion/include bytes are preserved in the fixtures.

This is a read-only candidate builder, not an activated migration. Remaining:
joint publication/recovery, owner/session and job admission, explicit review,
post-restart contract checks, and integration of vendor reset/discovery callers.
It does not infer topology shrink/replacement or migrate unrelated calibration
values. No deployment or printer operation occurred.


### R23 joint candidate publication and recovery — 11 November (local)

Added `HeadConfigurationTransaction` using the existing durable atomic writer.
Publication checks the complete source set before and between writes and requires
fresh caller admission at every boundary. The journal retains original/candidate
bytes, verified identities and source runtime settings. Ordinary failures roll
back; process interruption leaves an unresolved journal. Explicit reopen
recomputes the reviewed transformation before accepting recovery evidence, and
rollback refuses to overwrite concurrent edits. Absent state files stay absent.

Successful publication remains `published`, not accepted: identification startup
now treats unresolved migration journals as a hold. `verify_loaded()` requires a
different backend session, exact candidate files and matching loaded identity,
PID and nozzle settings before recording `verified`. It does not restart services
or automatically resume interrupted identification.

Validation: **201 passed** across transaction, planner, nozzle and identification
suites. Fault injection covers lost write acknowledgement and process loss after
each of seven changed files, complete restoration, changed admission, concurrent
edits, journal tampering and post-restart mismatch/refusal/acceptance.

The transaction is still a local library, not a callable printer workflow.
Remaining integration must supply owner/session/job admission, explicit review,
all affected calibration policy and runtime verification, and replace the relevant
vendor callers. No printer operation or deployment occurred.


### R23 managed identification integration — 11 November (local, undeployed)

The identification command now constructs a complete candidate before setup motion
and publishes through `ManagedMappingTransaction` after all physical observations
and final docking. Admission binds the material owner and backend session and
refuses openACE/AFC, an open/paused/active job, unresolved cancellation/recovery,
active/unknown filament/tool service, a retained managed job or print context.
Absent prior managed-job records are normal; unreadable/corrupt records refuse.
Custom filament-record directories are not silently ignored.

After a successful publication and restart, startup checks the loaded candidate
and records verification without replaying identification or restarting anything.
Interrupted writes still require explicit recovery. A fake-printer command test
exercises the actual adapter and verifies PID and sparse loaded flags move together
and a fresh loaded session accepts the publication.

Validation: **232 passed, 8 initially skipped** across the affected identification,
planner, transaction and nozzle suites. The eight retained-client emulator tests
were then run with their Unicorn dependency: **8 passed**. No printer contact.

**Deployment remains blocked on remaining calibration scope, not test success.**
The vendor saved-variable store contains `tN_offset`, calibration sample/center/Z
fields, pressure advance and flow values alongside dock `tN_position` values.
These have different physical meanings; moving every `tN_*` field would incorrectly
move dock locations. The current candidate does not yet migrate or validate this
store. Resolve that policy and its full write set before deploying this integration,
then finish vendor reset/discovery routes and physical qualification.


### R23 identification provenance correction — 11 November (local)

Further caller review invalidated an assumption in the preceding integration:
the old UUID assignment may itself be wrong. It cannot independently prove
ownership of existing PID/nozzle/material records. Changed observed mappings now
refuse publication with an explicit calibration/offset review requirement;
unchanged identification still completes and receives post-restart verification.
The pure migration planner and transactional publisher remain available for a
future workflow with independently established source ownership.

The changed-mapping command test confirms observation can complete but no config
or migration journal is published from unproven provenance. **241 tests passed**
across affected suites, including retained-client emulator cases. This supersedes
the previous claim that automatic permutation publication is ready in the command
adapter. It does not close R23: supported changed-topology review, calibration
provenance and reference/dock/mesh policy remain required. No deployment occurred.


### R26 native maintenance restart hold — 11 November (local)

The identification RESTART action previously checked job, filament/tool operation
and calibration state but omitted unresolved print cancellation and PLR results.
Projection now retains a compact `managed_operation_hold` for those outcomes,
including malformed/unknown states. Native maintenance admission checks that hold
before offering or dispatching identification restart. A completed identification
cannot override it merely because the print status is idle.

Host validation: projection checks cover pending/running/unknown/stopped and
malformed results, plus terminal results. Native lifecycle verification confirms
no restart command is emitted while held and that the action becomes available
once the hold is resolved. **2 focused C++ test executables passed** (projection
and native LVGL lifecycle). The ARM candidate also built successfully with
`build-arm.sh` under `-Wall -Wextra -Werror`. No printer contact or deployment.

This closes only the local UI-admission omission. R26 remains open for backend
restart admission, the stock warning callback, the screen startup system-service
restart and durable interruption policy. An action queued before a status change
still requires backend enforcement; the UI check is not that enforcement.

### Design reconciliation — 11 November

Updated R23/R26 in both the design and structured requirements, and refreshed the
current checklist with the configuration-provenance and restart-boundary findings.
The audit decisions now explicitly cover competing recovery entry points, complete
configuration write sequences, session-bound editor saves and failure retries.
Local implementations are not marked deployed or physically accepted. Existing
accepted unaffected tests remain valid; USB/profile import remains deferred.

### R26 backend restart admission — 11 November (local, undeployed)

The Ready-state `gcode:request_restart` event now checks fresh standalone job,
SD-file, pause, managed cancellation/recovery, service and calibration state before
vendor dwell/drain/exit. Idle restart retains that sequence. Explicit isolated
RESTART/FIRMWARE_RESTART after shutdown remains available without clearing durable
holds; a compound script cannot use that exception to execute trailing commands.
Other owners retain their existing route pending separate qualification.

Validation: the broader backend run passed 1055 cases and failed 16 template tests
because Jinja2 was absent from that test environment. A focused rerun with Jinja2
passed 60 restart/parser-state cases, including those 16. These are separate runs,
not a claim of one fully green suite. No printer deployment or motion occurred.

System-service restarts bypass this event. SAVE_CONFIG can write before requesting
restart; configuration-write admission remains R23/R24 work. Stock startup and
warning callers, owner-specific admission and live qualification remain open.

### R26 startup restart interception — 11 November (local, undeployed)

The native candidate hooks retained run_a_shellcmd only after profile verification.
It suppresses exactly main's caller address 0x44a454 with command
`systemctl restart klipper`, returning the empty output string expected for that
successful shell command. Other callers/commands use the original trampoline.
This removes the implicit startup action rather than deciding from stale UI state
whether it may restart. Explicit backend restart retains managed admission.

Four characterization/policy/prologue tests and the full profile-window check
pass. ARM build completes with warnings treated as errors. Built-wrapper ABI
execution and real startup/reconnect/owner qualification remain open. Successful
hook installation is required; this is not protection against an unmodified or
failed-bootstrap stock client or an external service-manager restart. Installed
r119 and deployment's conservative restart assumptions remain unchanged.

### R26 compiled startup wrapper execution — 11 November (local)

Executed the built ARM wrapper under Unicorn with its manifest/source hashes
verified. Only imported C++ compare/delete and the original shell helper were
substituted. The exact startup call returns a valid empty std::string without
calling the shell helper or consuming the caller-owned argument. A neighboring
caller, a short unrelated command and a compound command forward unchanged;
return storage, stack restoration, moved-from input and heap cleanup are checked.

`uv run --with pytest --with unicorn --with pyelftools pytest -q
 tests/test_stock_restart_boundaries.py`: **8 passed**, including four compiled
execution cases. This closes the local wrapper-ABI check, not real startup,
bootstrap failure, other-owner or deployment lifecycle acceptance. No live
printer command or restart was issued.

### R26 deployment-owned backend restart — 11 November (local)

Preload installation/rollback no longer relies on the stock screen's implicit
restart. The restart helper stops the screen, sends one explicit firmware-restart
request, starts the screen and requires observed backend transition/new PID plus
two consecutive Ready observations with the screen active. A lost reply is
observed without resubmission; persistent old Ready responses never count as
success. Existing deployment admission remains required. Legacy screen startup
may still request another restart; this change does not claim to remove that
behavior from previous/unmodified artifacts.

Readiness, one-shot dispatch and actual restart/rollback tests: **32 passed**.
Updated old rollback/service fixtures to model backend observations and explicit
service start; no service command was sent to the printer. Live candidate
installation, reconnect and rollback remain pending qualification.

### R24/R26 calibration SAVE_CONFIG admission — 11 November (local)

The new restart guard exposed an integration conflict: a wrapped calibration
SAVE_CONFIG requests restart while CalibrationCommands is active. Rejecting it
only at restart would occur after configfile had already written. The wrapped
save now calls restart admission before dispatching SAVE_CONFIG, then marks only
that synchronous save as eligible for its own restart. All other managed holds
still apply. The marker clears in finally, including write/restart failures.

Calibration-command and retained-vendor restart tests: **72 passed**. Integrated
cases prove refusal before the simulated write under a cancellation hold and
successful save/restart with idle state. Scope is the existing wrapped calibration
worker; direct factory/probe editor ACCEPT/SAVE_CONFIG paths still require their
session-bound lifecycle and pre-write admission. No calibration or restart was
performed on hardware; this does not close R24 or live R26 acceptance.

### R24 probe-editor result receipt — 11 November (local primitive)

ProbeEditorReceipt wraps one exact manual-probe finalizer and binds it to the
backend session and helper identity supplied by the editor owner. It records an
accepted finite position only after the original finalizer succeeds. Refusal and
ABORT produce no save permission; stale/replaced bindings and finalizer errors
invalidate it. Save requires the matching token, fresh owner admission and another
binding check, then retires permission before invoking persistence. A save error
leaves unknown, never a retryable accepted receipt. Close invalidates permission.

Combined vendor acceptance, receipt, calibration and restart tests: **92 passed**.
This is not yet connected to a public command, status transport or editor. Next:
bind receipt creation to admitted probe preparation, route jog/accept/save through
that owner, and replace blocking vendor callbacks with retained asynchronous UI.
No printer deployment or calibration occurred.

### R24 capture receipt during admitted preparation — 11 November (local)

The receipt primitive can now run admitted preparation under a scoped command
registration observer. It captures the raw bound manual-probe helper before
Klipper wraps ACCEPT in its extended-command lambda, requires the probe-calibrate
finalizer, rejects existing/unexpected helpers, and restores registration on all
exits. Preparation failures invalidate captured results. Command-handler identity
and the accepted shared manual-probe status object detect replacement, including
a later probe that has already completed and unregistered ACCEPT again.

Combined preparation/receipt/vendor acceptance/calibration/restart tests:
**98 passed**. This remains a private integration primitive: public action/status
transport, serialized owner lifetime and native nonblocking editor wiring are
still required. No live preparation, motion or deployment occurred.

### R24 registered probe-editor owner — 11 November (local, undeployed)

`_WMP_PROBE_EDITOR` now owns BEGIN/JOG/ACCEPT/ABORT/SAVE with backend SESSION,
32-hex REQUEST, monotonically increasing SEQ and the captured TOKEN. BEGIN uses
admitted `_WMP_PROBE_CALIBRATE`; JOG permits only the stock signed step sizes.
Identical retries return existing state without repeating motion or persistence;
stale/out-of-order requests refuse. An uncertain jog blocks further motion while
ABORT remains available. SAVE requires successful receipt finalization and fresh
admission, with only its synchronous persistence allowed to request restart.

`wmp_recovery.probe_editor` exposes the receipt/operation status. The editor holds
calibration_active throughout its lifecycle; legacy wrapped calibration refuses
overlap. Self-admission is scoped to the exact editor object and cannot authorize
external restart or bypass another active calibration. Other-owner configurations
currently refuse this new route pending their policy integration.

Combined editor, retained vendor acceptance, calibration, restart and bottom-Z
checks: **118 passed**. Native projection/delivery/editor replacement, responsive
preparation stop, accepted-result discard/pending-config ownership, other-owner
support and live qualification remain open. These commands are not yet used by
the native screens; no deployment or hardware calibration occurred.

### R24 accepted probe offset ownership and discard — 11 November (local)

The editor now snapshots the finalizer's named probe section immediately before
ACCEPT and captures its staged z_offset only after accepted finalization. SAVE
checks that this is the sole pending calibration change and rechecks immediately
before persistence. It cannot silently save pre-existing or newly added unrelated
pending values. DISCARD restores only the owned offset and pending entry, keeps
unrelated changes, and sends no backend command/restart. A changed owned offset
causes an explicit conflict hold; no concurrent value is overwritten.

The vendor configfile.set implementation is exercised for preservation, prior
pending offsets and concurrent edits. Full editor tests cover SAVE refusal,
command-free/idempotent DISCARD and conflict retention. Combined scope:
**125 passed**. Native presentation, preparation stop, other-owner qualification
and live acceptance remain open. Conflict resolution remains explicit future
integration; unknown/discard conflicts are not silently marked completed.

### R24 native editor-status projection — 11 November (local)

The backend now exposes current helper Z position, binding validity and explicit
in-flight jogging/accepting/aborting/saving/discarding stages. Status reads do not
mutate the operation or dispatch commands. New preparation clears the prior
receipt before publishing its new request, avoiding a stale token during startup.

Native projection whitelists editor fields and validates protocol, session,
request/token shape, sequence, states and finite positions. Missing, malformed,
unsupported-owner and changed-session data become explicit unavailable status;
stale helper binding remains visible. No editor control is wired to it yet.

Projection host check: **1 passed**. Combined backend checks before the last new
preparation test: **127 passed**; final editor-specific rerun: **40 passed**.
ARM candidate build completed successfully. Native control/transport wiring
remains open; this is not screen or live qualification.

### R24 native probe-editor action controller — 11 November (local, not wired)

ProbeEditorFlow now builds bounded session/request/sequence/token commands from
explicit actions only. It permits one outstanding action, waits for the matching
backend sequence to settle, ignores older observations and never advances a local
Z estimate. Unknown HTTP delivery is not replayed; a later authoritative receipt
can resolve it, and a late transport error cannot downgrade that receipt. Session
change or external sequence advance invalidates further actions.

Backend/native status now carries the receipt phase separately from the operation
outcome. The controller offers ABORT after an uncertain jog only when the receipt
still identifies an editing helper, not after uncertain save or finalization.
Native action-controller and backend receipt tests: **41 passed**. Independent
transport, retained controls, entry interception, preparation stop and live
qualification remain open. The controller is not yet called by runtime or stock
callbacks; no printer command was sent.


### R24 independent sender and runtime status wiring — 11 November (local)

The probe editor now has its own HTTP worker, connected to runtime status and
status-loss observations. Command delivery never holds the status/GUI mutex while
waiting for HTTP. Freshness and the selected session/request/sequence binding are
rechecked before dispatch; changes refuse delivery. HTTP success is not a receipt,
and uncertain delivery is not replayed. Native stock callbacks remain unchanged.

A confirmed Abort, Save or Discard now permits an explicit new request in the same
screen process. Duplicate requests, stale observations and unresolved operations
cannot reopen preparation. Restart-invalidated sessions still require a separate
review/reset lifecycle; this change does not silently clear them.

Focused native flow, independent-sender and runtime/LVGL lifecycle tests:
**3 passed**. The integrated ARM candidate build also passed. Remaining: retained
editor controls and callback interception,
preparation STOP, failure/conflict resolution and physical qualification. No
printer connection or deployment occurred.


### R24 retained calibration controls — 11 November (local, entry not activated)

A retained probe-editor panel now renders Prepare / Adjust / Review / Save stages,
current backend Z, bounded signed jog buttons and uppercase header actions. Stage
colors follow the agreed gray/orange/white convention; stale or invalidated status
cannot display an active stage. Status updates retain the widgets. Close remains
navigation only, distinct from ABORT and from discarding an accepted offset.

Control availability is derived by a non-dispatching copy of the same action
controller used by the independent worker. Rendering cannot increment the live
sequence or submit commands. Runtime refresh and explicit callbacks are wired;
stock preparation/editor entry points are not yet intercepted. Do not activate
this incomplete route before preparation STOP and result-resolution integration.

Focused native controller, sender and LVGL lifecycle checks passed: **3 tests**.
The final integrated ARM candidate build passed; nothing was deployed.
Preparation still invokes a compound G28/PROBE_CALIBRATE path. Its STOP contract
must distinguish a latched request from completion: check it before subsequent
preparation stages, drain already accepted motion, abort only the captured helper,
and preserve uncertainty if preparation fails without a resolvable helper. Do not
present a responsive HTTP sender as proof that physical preparation can be stopped.


### R24 preparation stop backend — 11 November (local, undeployed)

The reactor endpoint `wmp/probe_editor/stop` validates the current session/request
and standalone owner, then latches intent without issuing a command or waiting on
the G-code mutex. Preparation checkpoints before/after homing and before clearance,
positioning and probing recheck machine faults and stop before the next stage.
Already accepted motion drains through toolhead.wait_moves (the M400 primitive),
so the vendor quick-stop command-skipping path cannot silently bypass it. If
preparation has created a helper,
cleanup aborts the exact captured instance; it does not send an unbound ABORT.
Unknown drain/abort outcomes retain the hold, and unrelated homing failures are
not converted into successful stops. Shared checkpoints do nothing outside a
managed editor. A matching stopped BEGIN receipt now settles the native action.

Backend/macro/calibration checks: **205 passed**. Focused retained-dispatcher,
receipt/projection/controller checks: **54 passed**. Endpoint-registration and
post-restart command-contract checks: **153 passed**. These scopes overlap and
are not a count of unique tests. The retained vendor dispatcher confirms that a
checkpoint error unwinds before the next command without shutdown; it emits the
normal command-error notification. The integrated screen must handle that expected
stop notification without showing a second conflicting recovery flow.

Independent native STOP delivery, the STOP control, failed-preparation resolution,
stock entry interception and physical qualification remain open. No printer
commands, deployment or physical calibration occurred.

Final direct-drain receipt/stop rerun: **52 passed**. The native stop-state ARM
build passed. These remain local checks; native STOP delivery is not yet wired.


### R24 independent STOP delivery and header control — 11 November (local)

Probe preparation STOP now uses a separate connection/thread from BEGIN and other
editor commands. It requires the matching fresh preparation receipt and advertised
stop protocol; its session/request is rechecked immediately before dispatch. A
request is sent at most once. The HTTP acknowledgement means requested, never
stopped; backend receipt status resolves completion or uncertainty. Late replies
cannot replace a terminal result. The retained header uses STOP during preparation
and ABORT during editing, with availability updated in place.

Native projection, retained-control and runtime lifecycle checks: **4 passed**.
Final lost-reply/receipt/backend rerun: **54 passed** (overlapping scope).
No printer connection or deployment occurred. Stock entry interception, expected
stop-notification handling, failed/conflicting-result resolution, restart review,
owner qualification and physical acceptance remain open.

The final integrated ARM candidate build passed. This does not qualify the
printer screen or physical stop behavior.


### R24 cleanup of a helper left by failed preparation — 11 November (local)

Preparation now refuses any existing ACCEPT/NEXT/ABORT/TESTZ handler before it
starts. If preparation creates a helper and then fails, the owner can retain a
cleanup-only receipt tied to that helper, callback and all registered handlers.
Neither managed actions nor a direct legacy ACCEPT can accept/save that result.
Explicit ABORT drains accepted motion and rechecks ownership before calling the
captured helper. Changed handlers, sessions or callbacks refuse cleanup; an
uncertain cleanup remains held and is not replayed. Successful cleanup preserves
the original failure text and does not clear unrelated calibration/machine faults
or write configuration. Native ABORT availability uses the backend cleanup receipt.

Backend receipt/configuration/calibration checks: **110 passed**. Additional
handler-ownership and drain-race checks brought the focused receipt suite to
**63 passed**. Native controller, sender and projection: **3 passed**. The final
ARM candidate build passed. Test scopes overlap. No printer contact or deployment.

Preparation failures without a safely owned helper, uncertain save/cleanup,
concurrent configuration conflicts and restart review still need explicit
resolution. Stock entry activation, expected-stop notification handling and live
qualification remain open; this does not declare the editor complete.


### R24 discard of a failed preparation without a helper — 11 November (local)

BEGIN now snapshots pending/autosave configuration and assigns a request-bound
failure token. A failed attempt without a receipt can advertise DISCARD only if
all probe handlers are absent, manual probe status explicitly reports inactive,
and pending/autosave configuration still matches. Explicit DISCARD checks idle
owner/machine admission, drains accepted motion directly, then rechecks admission
and evidence before releasing the attempt. It writes no configuration and retains
the original failure text. Admission refusals record the action sequence so the
native controller can show the refusal rather than wait indefinitely; failures or
changed evidence after drain retain unknown and are not replayed.

The native controller enables DISCARD only with this backend evidence and token;
SAVE and ABORT cannot substitute for it. Pre-existing unrelated pending settings
are preserved. Backend/configuration/calibration checks: **125 passed**; final
backend/native projection/controller/sender run: **78 passed** (overlapping scopes).
No deployment or printer actions occurred. Unknown save/cleanup and concurrent
configuration conflicts, restart review, expected-stop notifications, stock entry
activation and physical qualification remain open.

The final integrated ARM candidate build passed for this discard path.


### R24 authoritative action refusal receipts — 11 November (local)

Valid session/request/token-bound action preflight refusals now record their
sequence, reason and `action_refused` status before returning an error. No command
is dispatched and the existing editor phase remains intact. The native controller
settles the matching refusal without treating HTTP failure as proof of an unknown
motion or save outcome. A later action uses a new sequence; replaying the refused
request remains a no-op even after the refusal condition disappears.

BEGIN admission failures now record a terminal `rejected` request when preparation
never dispatched, avoiding an unnecessary operation hold. A duplicate rejected
BEGIN cannot start later; an explicit new request is required. Failures after
dispatch still retain the existing failed/unknown cleanup rules. Original fault
and uncertainty boundaries are not bypassed by the new refusal status.

Focused backend/configuration/calibration/native tests: **131 passed**. Coverage
includes refusal followed by ABORT/DISCARD, unrelated-pending SAVE rejection,
duplicate requests after conditions change, and native completion of rejection
receipts. No deployment or printer commands occurred.

The integrated ARM candidate build passed for the refusal-receipt changes.

### R24 concurrent-offset backend review — 11 November (local)

The local backend now exposes accepted/current staged offsets with a review token
bound to the full pending/autosave snapshot. Explicit KEEP rechecks that token,
retires the editor receipt and leaves configuration unchanged. Concurrent changes,
missing parser entries, inconsistent values and non-finite values refuse resolution.
DISCARD preflight now records a known refusal rather than claiming uncertain
execution when a newer offset prevents restoration.

Validation: `tests/test_probe_config_change.py` and
`tests/test_manual_probe_acceptance.py`: **95 passed**. Tests cover whole-snapshot
invalidation, preservation, receipt retirement, duplicate requests and no save or
motion dispatch. Native projection/controller/review controls are not integrated
yet; uncertain SAVE resolution remains separate. No deployment or printer contact.

### R24 native conflict review — 11 November (local)

Native projection validates both finite offsets and the review token. The retained
editor shows accepted/current values and replaces DISCARD with KEEP for a conflict,
explaining that KEEP leaves pending settings unchanged without saving. The tap
carries the displayed token; the controller refuses a changed review and the
delivery worker binds the queued request to the conflict snapshot. Confirmed kept
receipts settle the request and permit a fresh explicit calibration request.

Focused native controller/worker/projection checks: **3 passed**. Retained-widget
lifecycle and native runtime compilation: **2 passed**. This is local integration,
not stock entry activation or printer qualification. No deployment occurred.

ARM candidate build also passed (`/tmp/wmp-probe-conflict-arm.log`); it remains undeployed.

Combined affected regression run: **146 passed, 38 deselected**, covering backend
manual-probe/configuration/calibration commands, native controller and transport,
projection, runtime compilation and retained-widget lifecycle. The added transport
case verifies changed-review refusal, command-free permissions, exact review token
delivery and waiting for the kept receipt rather than trusting HTTP success.
Maintenance/Factory entry boundaries are documented in the source audit and remain
unactivated.

### R24 Maintenance entry replacement — local candidate

Maintenance probe action 8 now opens the managed retained panel. Opening and
reopening send no command. Explicit START uses fresh runtime admission and the
independent sequenced BEGIN transport. Close deletes only the panel, preserving
the operation for reopening; it does not abort or restart preparation. Terminal
results expose a separate START for a new explicit request. The old synchronous
`_WMP_PROBE_CALIBRATE` plus stock-page navigation helper was removed.

Factory's embedded route and direct legacy probe-page/callback coverage remain
open. This candidate is undeployed; native printer layout, touch, notification
behavior and physical calibration qualification are still pending.

Validation: initial controller/worker/runtime/lifecycle selection **4 passed**;
final explicit START/reopen and transport regressions **3 passed**. ARM candidate
build passed (`/tmp/wmp-probe-entry-arm.log`). No printer contact or deployment.

### R24 Factory probe entry — local candidate

Factory action 12 now enters the same managed review panel as Maintenance. The
event hook consumes the probe action before the original G28/logical-T0/probe
prefix or embedded editor creation. START remains a separate admitted action.
Stale, hidden, deleted and detached events cannot open it; other valid Factory
actions delegate to their existing implementation. This narrow hook does not
resolve the other Factory configuration writers or service-editor conflicts.

Validation: native lifecycle/runtime/profile checks **3 passed**; retained ARM
Factory dispatch/prefix and profile-bound relocatable-prologue checks **9 passed**.
Direct legacy probe-page/callback ingress, notification handling and installed
physical/touch acceptance remain open. No printer contact or deployment.

ARM candidate build passed (`/tmp/wmp-factory-probe-arm.log`); undeployed.

### R24 direct legacy probe ingress — local candidate

Direct `probe_calibrate_page` navigation opens managed review. Both old editor
callbacks (Factory `0x4c76dc`, Maintenance `0x53d150`) are fully replaced: valid
legacy taps open the review panel and never perform their former jog, abort or
ACCEPT/SAVE_CONFIG sequence. Malformed/stale/hidden/deleted/detached events do
nothing. Review cannot start preparation or act on an unowned helper; the backend
continues to require its own admitted request and receipt.

These are exact profile-bound hooks after successful WM+ bootstrap, not protection
for an unmodified client or a failed bootstrap. Physical calibration, expected-STOP
notification behavior, restart-invalidated sessions and unknown-result resolution
remain pending. No printer contact or deployment.

Validation: **16 passed, 38 deselected** across retained ARM dispatch/callback
characterization, firmware profile, native runtime and lifecycle checks. ARM
candidate build passed (`/tmp/wmp-legacy-probe-arm.log`); not deployed.

### R24 expected STOP reporting — local backend

Retained dispatcher execution showed that expected checkpoint STOP emits error
notifications at every nested macro boundary before the editor catches it. The
local preparation scope now suppresses only the exact expected exception object
for the same session/request, restoring the original reporter on exit. Cleanup
events remain enabled: stock probe/air handlers end pending probe sessions and
gcode_move resynchronizes its position. Unrelated errors, including identical
message text, remain visible. A different exception raised after the checkpoint
now remains failed instead of being incorrectly acknowledged as stopped.

Validation: **147 passed** across manual-probe, configuration ownership and
calibration-command tests, including direct/nested retained dispatcher execution,
reporter restoration, same-text faults and cleanup-fault preservation. Native
notification behavior and physical STOP qualification remain open. No deployment.

### R24 save completion evidence — local backend

The vendor dispatcher can return normally without executing SAVE_CONFIG under
quick-stop. Calibration now refuses quick-stop before dispatch. Probe save also
requires the retained writer's firmware_restart request to return, rather than
interpreting an ordinary script return as success. Missing/wrong restart requests
or exceptions retain an unknown result and cannot replay the save. The scoped
restart observer is restored on exit; existing restart admission still executes.

Validation: **152 passed** across manual-probe, configuration ownership and
calibration-command tests. A retained vendor SAVE_CONFIG execution on disposable
files verifies the offset and preserved backup before requesting restart. This is
a writer-bound completion observation, not verification of the next loaded
configuration. Durable unknown-save resolution and post-restart review remain
open. No live configuration write, restart or deployment.

### R24 durable save evidence foundation — local, not yet wired

`ProbeSaveRecord` stores the originating session/request, canonical configuration
path, accepted offset, complete autosave snapshot and pre-write configuration
hash. It validates a versioned checksummed payload, bounds reads, fsyncs the file
and parent directory, and publishes exclusively so an existing unresolved or
corrupt record cannot be replaced. Failed publication prevents proceeding; a
directory-sync failure retains the published evidence for review.

Read-only review compares the disk autosave snapshot, loaded values and pending
configuration. Matching data remains `review_required`: it does not prove which
writer succeeded and does not trigger a write, restart or acknowledgement.

Validation: **18 disposable-file tests passed**, including new-instance reads,
changed PID/offset/runtime values, pending edits, path mismatch, corrupt records
and publication failures. This component is not yet called by SAVE or startup.
Remaining: record before write, startup hold/projection, explicit bound review and
acknowledgement, installed configuration preservation and printer qualification.
No live files or printer state were changed.

### R24 save evidence integrated with writer and Ready — local

SAVE now publishes exclusive durable intent before invoking the writer. Journal
creation or sync failures prevent SAVE_CONFIG dispatch; a published record stays
held even if the reply/write outcome is unknown. The Ready handler reads evidence
once, compares the saved autosave and loaded configuration, and enters save_review
without dispatch. Corrupt/missing loaded evidence remains held and original bytes
are preserved. Status reads do not perform file I/O. Native projection displays the
hold and new BEGIN is disabled, including after a same-session saved receipt.

Validation: **174 backend checks passed**, including actual retained vendor writes
and Ready callbacks for matching/mismatching loaded offsets. Explicit review
refresh, acknowledgement/archive and client session reconciliation are not yet
implemented; this is an incomplete, undeployed lifecycle, not release acceptance.

Native controller/worker/projection/lifecycle selection: **4 passed**. ARM build
passed (`/tmp/wmp-save-review-hold-arm.log`); no deployment.

### R24 acknowledgement/archive storage — local component

Save review now has a digest of its complete record/disk/loaded/pending snapshot.
Explicit acknowledgement rejects a changed snapshot and publishes a durable
record-bound acknowledgement; it keeps the original record and does not claim
that SAVE succeeded. A later new save archives acknowledged evidence before
replacing the active record. Original acknowledgement files remain available.
File locking serializes publication/acknowledgement across cooperating processes;
unacknowledged or corrupt evidence cannot authorize replacement, and duplicate
save identities are refused.

Validation: **133 affected tests passed**, including two concurrent new saves,
stale reviews, corrupt acknowledgements, duplicate identities and retained
archives. The corrupt-record exception assertion was updated from publication
failure to validation failure; it still verifies no SAVE dispatch and unchanged
evidence. Backend REVIEW/ACK commands and native controls are not yet wired, so
startup holds remain unresolved until that integration is complete. No deployment.

### R24 backend save REVIEW/ACK — local

`_WMP_PROBE_SAVE_REVIEW` now requires the current backend session and original
save request. Explicit REVIEW obtains a fresh complete snapshot and session-bound
token. ACK must match that explicit review and a newly checked configuration match;
stale sessions/tokens, pending edits and mismatched loaded settings preserve the
hold. Startup observation does not authorize ACK. Neither command moves, heats,
writes printer.cfg nor repeats SAVE_CONFIG.

Successful acknowledgement retains the record, releases the hold and survives
restart. The next distinct save archives the acknowledged record first. A lost ACK
reply is idempotent; repeated storage confirmation re-syncs the directory so an
earlier directory-sync failure cannot be mistaken for durable acknowledgement.
The installer now requires the review command to be registered.

Validation: **282 affected checks passed**, including explicit review before ACK,
stale session/pending-edit refusal, restored acknowledgement, archive/concurrency
checks and missing-command deployment rejection. Native review UI/transport and
mismatch recovery remain incomplete and undeployed.

### Design reconciliation: calibration and save review — 11 November

Consolidated R24 into a current requirement instead of accumulated, contradictory
historical implementation notes. The design now distinguishes finalizer acceptance,
writer completion and loaded-configuration review, and records the remaining
correlated native REVIEW/ACK and restart lifecycle work. Refreshed the current
checklist while retaining dated evidence below it. R20–R27 conflict scope remains
unchanged; local checks do not close deployed or physical acceptance. This update
changes documentation only and does not contact the printer.

### R24 save-review request receipts — local, undeployed

Protocol 2 requires explicit positive sequences for REVIEW/ACK and exposes a
result bound to session, originating save request, sequence and action. Repeated
identical delivery returns the retained result without repeating file operations;
changed or out-of-order identities refuse. Pre-write errors report refused;
acknowledgement storage failures report unknown and retain the hold. A test writes
the acknowledgement marker and then raises: duplicate delivery performs no second
write, while fresh explicit review can reconcile the retained evidence.

Affected backend/installer checks: **282 passed** before adding explicit
session/request fields to the receipt; the configuration-review suite is rerun
for that final field change. Native protocol-2 projection/controls/transport and
deployment acceptance remain pending. No printer contact.

### R24 native save review — local, undeployed

Validated projection now recognizes protocol-2 review results and acknowledged
saves. The controller permits explicit REVIEW of restarted evidence without
replaying the old operation; only a matching session/request/sequence/action
receipt settles REVIEW or ACK. Cached confirmable status and HTTP success are
insufficient. ACK carries the displayed review token. Authoritative acknowledgement
permits a new explicit START. The background worker binds queued commands to the
review snapshot; rendering uses controller copies and dispatches nothing.

The retained header offers REVIEW and ACK during a save hold and displays the
recorded offset/configuration match. Host controller, projection, worker, runtime
and lifecycle selection passed **5 tests**; the added worker and retained-tap
cases then passed **2 affected tests**. ARM build passed
(`/tmp/wmp-probe-review-native-arm.log`). Native layout/notification,
loaded capability acceptance, mismatch recovery and live qualification remain open.
No printer contact or deployment.

### R24 loaded editor contract — local installer

Post-restart acceptance now requires nested probe-editor protocol 1, STOP protocol
1 and sequenced save-review protocol 2, a matching calibration session, typed
review flags and a bounded integer review sequence. Registered command names alone
can no longer admit the older unsequenced backend. A valid review hold remains
acceptable and unchanged: protocol verification does not resolve its evidence.

Validation: **135 read-only backend acceptance tests passed**, including the older
protocol, malformed/missing status, stale session and preserved hold. The verifier
uses only the existing objects query; no heating, movement, acknowledgement or
configuration write. Installed/live verification remains pending.

### R24 review layout — local native candidate

The prior 120-pixel status label could not accommodate save-review and failure
messages above the jog controls. The panel now retains a vertically scrollable
body, keeps numbered stages at the top and anchors jog controls at the bottom
only during adjustment. Review/error states use the remaining full body height.
Hidden jog widgets reject taps; status updates retain widget identity and scroll
position. The Save stage stays active through post-restart review and completes
only after acknowledgement, rather than at writer return.

Validation: native lifecycle and runtime compilation **2 passed**, including long
review text, full-height review body, retained scroll position and retained controls.
ARM build passed (`/tmp/wmp-probe-review-layout-arm.log`). These geometry checks
do not replace live typography/touch
qualification. No printer contact or deployment.

### R24 explicit offset retention — local, undeployed

Fresh save review now distinguishes an offset-only mismatch that can be retained:
disk and loaded offset must agree, all other recorded autosave values must match,
and no pending edits may exist. Explicit RETAIN carries the displayed snapshot
token and uses the same sequenced result protocol as ACK. It writes only a
versioned acknowledgement containing the retained offset; original evidence and
printer configuration remain unchanged. Ready recognizes this durable resolution.
Native projection/controller/worker/header support is gated by save_retain_protocol.
The screen shows recorded/current offsets and explains that RETAIN does not save.

Backend/configuration/storage checks: **138 passed**, including PID differences,
pending edits, disk/runtime disagreement, nonfinite offset rejection, explicit
review/retention, duplicate delivery and restart. Native controller/worker/projection/
lifecycle/runtime selection: **5 passed**; final backend guidance check: **20 passed**.
ARM build passed (`/tmp/wmp-probe-retain-arm.log`). Additional RETAIN tap check: **1 passed**. Broader mismatches, missing/corrupt evidence and live acceptance remain
open. No printer contact or deployment.

### R24 bounded save comparison — local, undeployed

Explicit review now compares recorded autosave values with on-disk and loaded
values, exposing up to eight differing entries and the total count. Missing values
remain explicit; each field is bounded to 128 characters. Pending edits are
reported separately. The native scroll body displays this comparison so a broad
mismatch no longer provides only a generic refusal. Original evidence and settings
remain unchanged; these diagnostics do not authorize ACK or RETAIN. Computation
happens during explicit review, never periodic status/file polling.

Backend/native selection: **53 passed**; final display assertions: **1 passed**.
ARM build passed (`/tmp/wmp-probe-comparison-arm.log`). Broad mismatch correction and
missing/corrupt-evidence resolution remain open; no printer contact or deployment.

### R24 reviewing externally restored evidence — local backend

Found and fixed a recovery dead end: corrupt startup evidence creates a temporary
review request, but a subsequently restored valid record has its original request
identity. The old equality check rejected that record indefinitely. Explicit
read-only REVIEW may now bind the restored source identity while retaining the
live review request for native receipt correlation. Repair alone does not refresh,
acknowledge, replay SAVE or release the hold. A different replacement source is
refused after binding; new BEGIN clears recovery-only identity/confirmation state.

Validation: **141** configuration/storage/acceptance checks passed; after adding
source-replacement rejection and BEGIN reset, **111 affected checks passed**.
Both matching ACK and offset-only RETAIN are exercised after a corrupt startup.
No native changes or printer contact. This supports review after an independently
verified evidence restoration; it does not implement automatic repair or deletion.
Preserve damaged bytes before any external repair. Missing/corrupt-evidence
recovery UI and broader configuration correction remain open.

### R25 standalone retry guards — local, undeployed

Added owner-scoped guards at outer retry and direct/nested coupling boundaries;
new failed coupling persists -2 before a separate abort macro, while existing
faults remain unchanged. Failed pickup no longer invokes stock UNLOCK under
standalone ownership. Other owners and normal successful motion retain their
existing paths. The source audit now distinguishes these branches and flag meanings.
Validation: macro/tool-return suites **377 passed**; final direct/nested fault
guards and owner/success checks **151 passed** after the last source adjustment.
Mechanical behavior, lower-level homing-failure
propagation and other-owner qualification remain open. No printer contact.

### R25 standalone actuator error propagation — local, undeployed

Standalone LOCK/UNLOCK now call `_WMP_COUPLING_STROKE` with the rendered session
and command generation. The helper uses the vendor do_homing_move API below the
public command that swallows errors and still issues PDI. It rechecks owner,
generation, quick-stop/shutdown and existing faults across the actuator sequence.
Successful motor-disable timing remains with the original macros; PLR retains
its existing helper default. A failed stroke records -2 for pickup or -3 for
release and verifies readback. Write failure or silent skipped persistence invokes
shutdown; original actuator failure remains the command error. Generation/owner
changes prevent further actuator or fault-write commands under the old context.

The installer requires the new command, preventing a macro/helper version mismatch.
Validation: **160** actuator/macro/deployment checks and **44** existing toolhead/
recovery checks passed. Retained vendor do_homing_move executes in the tests with
hardware homing stubbed; tests cover failed home, no post-stroke, persistence
failure, skipped write, admission refusal and mid-home generation change. No
printer contact. Installed routing and mechanical qualification remain open.


### 11 November — r120 acceptance refusal and process-restart correction

The source-bound r120 development export passed read-only preflight against the
idle printer. Its reviewed plan changed only wmp-screen-runtime.cfg (probe editor
checkpoints and coupling/retry guards). Installation reached Ready but correctly
refused loaded identification protocol 1 instead of required protocol 2. Earlier
component publications were restored and the screen/backend returned to Ready.
This is **not** an accepted r120 deployment; the recovery journal remains in
recovering state and needs reconciliation before another installation.

The retained klippy.py main loop rebuilds Printer after FIRMWARE_RESTART without
restarting Python, so imported helper modules remain cached. Suppressing the
stock screen's implicit systemctl restart exposed that the new installer's
firmware-restart request was insufficient to activate changed Python modules.
The local installer now explicitly restarts klipper.service and requires a changed
positive process ID plus consecutive Ready/active observations. An internal
startup transition alone is insufficient; lost acknowledgements are observed
without resubmitting restart. 161 readiness/backend acceptance checks passed.
The corrected process-restart path still needs live qualification.

Post-rollback readback: Ready/standby/unpaused, all heater targets zero, every
saved variable and effective configuration section unchanged. All four PID
controllers, nozzle/physical mapping, filament identities and loaded states are
preserved (session IDs changed as expected). No motion, heating or print command
was issued. Evidence is in analysis/validation/2026-11-11-managed-audit/:
preflight.log, install.log, config-review.json/diff, status-before/after.json and
preservation.json. Journal: eca442c1fb474dc68a464e198c272352.


### 11 November — r121 installed; idle acceptance and preservation

The r120 journal recovery first exited with an SSH channel-opening timeout after
restoring files. Its explicit continuation used a fresh connection, verified the
process restart and stable Ready, and finalized journal
`eca442c1fb474dc68a464e198c272352` as restored. No candidate was reapplied during recovery.

The corrected source-bound r121 package then installed successfully. Journal
`f673995ed0aa4da8bb381e87482cc5c1` is applied with no in-flight component. Screen
PID 1132573 maps the sealed artifact
`dbfea3deb016d16774a8eff47e170a8c5afb021c679ba463a8657f94ed1ff553`.
The installer verified a new positive Klipper process ID, consecutive Ready/active
observations and all required loaded backend protocols/commands. Identification
is protocol 2; probe editor/STOP/save-review/RETAIN are 1/1/2/1. This is development
qualification, not release promotion or physical acceptance.

Readback shows Ready/standby/unpaused and zero heater targets. Effective settings
changed only in the nine reviewed probe/coupling/retry macro sections. All saved
variables, four PID controls/gains, nozzle data, physical mapping, filament
identities and loaded states are preserved. Thus mesh/offset/travel/wipe sections
are unchanged too. Session fields changed as expected.

Three live stale-session requests (identification, probe editor BEGIN and coupling)
refused before side effects. Position, homed axes, targets, saved variables,
filament state, command generation and editor/identification state were identical
before/after. No motion, heating, calibration, identification or print was started.
The running native diagnostics show status polls 88→107 with failures unchanged at
15 across four samples; these samples support post-restart polling, not every
intermittent condition or visual/physical acceptance.

Evidence: analysis/validation/2026-11-11-managed-audit/ contains the sealed exports,
recovery.log and recovery-resume.log, r121-install.log, configuration review,
rollback and installed status/preservation comparisons, idle-refusals.json and
native-diagnostics.log. Remaining native-screen/physical gates stay unchecked.

### 11 November — r121 Maintenance probe navigation qualification

Navigated Home → Settings → General → Maintenance → PROBE_CALIBRATE, then
CLOSE, reopen, CLOSE and Home using the touchscreen bridge. The managed panel
shows four numbered stages (Prepare, Adjust, Review, Save), uppercase header
actions and idle state. START was untouched. CLOSE returns to the same scrolled
Maintenance list; reopening does not create a backend request or prepare motion.

All 13 captured observations remained Ready/standby/unpaused. Probe editor state,
request and sequence, position, homed axes, heater targets, saved variables and
per-head loaded state match the pre-navigation snapshot. Evidence is retained as
`navigation-*.jpg`, `navigation-*.json` and `navigation-preservation.json` under
`analysis/validation/2026-11-11-managed-audit/`. The old refusal banner remains
visible in the stock shell; it did not represent a new backend failure.

This qualifies idle Maintenance entry and Close/reopen only. It does not qualify
Factory/direct ingress, active calibration, STOP, save/restart review, stage
colour changes, or physical touch responsiveness. No heating, motion, calibration,
restart or print was requested. Screen left on Home.

### 11 November — R23 native reset boundary characterization

The retained factory-reset worker performs non-shell recovery/job/file cleanup
before invoking any shell command. Its first three effect calls are
`reset_plr_files`, `delete_all_jobs` and `format_gcode_local_with_pop`; only then
does it invoke `clear_memory.sh`, with configuration restore later. This rules
out a shell-only guard as sufficient R23 coverage. The managed reset transaction
must enter before the native worker's first effect and explicitly handle recovery
records and job files as well as calibration/configuration.

Pinned ARM prefix execution with stubbed effects and the four disposable vendor
script checks pass (5 total). Initial emulator setup overlapped scratch memory
with the loaded image; relocating scratch memory resolved that harness error.
No production reset code or printer state was changed. See
`tests/test_stock_factory_reset_boundary.py` and the C04 source audit for addresses
and the exact scope. Implementation and reset acceptance remain open.

### 11 November — R23 native reset guard, local candidate

The profiled native `restore_factory_settings()` entry is now replaced before
its first effect. It never delegates to the old worker. With a runtime it only
queues a notice; without one it returns without effects. The GUI thread renders
“Factory reset is unavailable in WM+. No settings or files were changed.” on the
system layer without unhiding stock popups. Repeated requests/sync retain the
same notice; CLOSE dismisses it. No status change starts a reset.

Validation: native runtime compilation, binary profile check and lifecycle test
pass. ARM build passes. Nine focused offline checks pass, including execution of
the built guard with/without a runtime (one byte written to the notice flag or no
writes), retained stock prefix characterization, disposable script defects and
existing retired-identification return paths. The first lifecycle run exposed
old mixed-case Close expectations; those now match the uppercase caption.

This candidate is **not deployed**. It removes the native worker bypass only;
external shell callers remain outside it. A reviewable, transactional managed
reset with explicit data/calibration preservation or disposal remains required.
The refusal is interim protection, not feature completion. No printer reset,
restart, heating or motion was issued during this work.

### 11 November — R23 reset confirmation before progress, local candidate

The pinned popup dispatcher identifies reset confirmation as kind 21. Its live
confirm branch opens progress popup 22 before enqueueing the reset worker. This
would leave a stuck progress popup even with the worker's destructive prefix
blocked. The native event hook now consumes the live affirmative click before
that prefix, dismisses only its own confirmation and queues the refusal notice.
Cancel retains the ordinary stock dismissal; hidden, non-click, duplicate and
stale events do not delegate, queue work or dismiss another popup. The worker
replacement remains as the boundary for direct native calls.

Both host popup tests pass, including existing Re-print and unrelated-popup
isolation. The exact caller check passes after correcting one transcribed ADRP
byte in the test. ARM build passes; 10 focused artifact/prefix/vendor-script checks
pass on the rebuilt candidate. No reset or other printer action was issued.
Still undeployed; these guards do not implement the managed reset transaction.

### 11 November — r122 reset guards installed; idle qualification

The source-bound r122 export passed preflight and installed through the guarded
installer. Journal `07bab51df9914ab1b3ed0d1622e8874b` is applied with no in-flight
component. Screen PID 1142242 loads artifact
`fef9468de26ecf8348420f0961240dd63f51374ae997b1f1398eb2ab7febc1ae`.
The installer verified the changed Klipper process, Ready state and required
backend protocols. Native diagnostics confirm bootstrap Running (11), with polls
49→70 and failures fixed at 15 over four samples. Those failures precede the
captured stable polling interval; this is not a general responsiveness claim.

Independent pre/post readback shows no effective settings-section changes and
identical saved variables, all four PID gains/control modes, nozzle data, physical
mapping, filament identities and loaded flags. This preserves mesh, offsets and
travel/wipe configuration as well. Sessions changed as expected. Printer remains
Ready/standby/unpaused with all targets zero; captured screen is on Home.

Evidence under `analysis/validation/2026-11-11-managed-audit/`: r122 preflight and
install logs, r122-before-status.json, r122-after-status.json,
r122-preservation.json, r122-native-diagnostics.log and navigation-r122-home.jpg.
The earlier “local/undeployed” reset-guard entries are superseded for deployment
only. No factory-reset action was invoked on the printer. Live refusal/Close
presentation is not qualified by artifact activation; full managed reset and
external script ownership remain open. No heating, motion or print was started.

### 11 November — R22 original evidence archived before abandonment (local)

Explicit recovery abandonment previously replaced the committed job record with
an invalidation marker without preserving its original bytes. It now publishes a
content-addressed archive of the exact original job and execution bytes before
that mutation. File flush, exclusive publication, directory flush and readback
must succeed first. Existing archives are verified, never overwritten; final
symlinks are rejected. The invalidation marker retains the archive digest.

Original execution/job evidence and ownership are checked again after archival.
A partial-cleanup retry reads the preserved archive and verifies its binding to
the original attempt before continuing cleanup. Missing, conflicting, corrupt or
wrong-job archives retain the unresolved hold. Read-only review does not archive.
No coordinates, transforms, material identities or accounting are synthesized.

31 focused abandonment/resolution tests pass, including exact-byte preservation
before invalidation, publication failure, directory flush failure, symlink and
conflict rejection, concurrent execution changes and wrong-job retry binding.
The initial new tests lacked pathlib/os imports; that harness error was corrected.
This backend change is local and undeployed. It does not implement old-version
conversion or the missing/unreadable-record disposal UI. Invalidation markers
created before this archive contract lack the original evidence and require an
explicit compatibility/recovery policy rather than automatic cleanup; that gate
remains open. No printer commands were issued during these tests.

### 11 November — R22 archive prerequisites checked during review and cleanup

An interrupted abandonment now validates the original archive before read-only
resolution review succeeds. Missing files, changed bytes, wrong-job evidence and
older invalidation markers without archive references refuse before M400 or any
cleanup. Review cannot offer confirmation for an already-invalid archive. The
same captured archive is rechecked at each stopped-state checkpoint; deletion
between SDCARD_RESET_FILE and flag cleanup stops the next command and retains the
unresolved attempt. Existing archive/record bytes are never repaired implicitly.

35 focused recovery abandonment, archive and resolution checks pass, including
missing/changed/legacy-marker review refusals with no commands or record writes,
and archive removal during cleanup. Local and undeployed; this improves the
existing attempt workflow but does not complete legacy-record conversion or
reviewed disposal when original evidence is unavailable. No printer actions.

### 11 November — reviewed disposal of pre-archive abandonment markers (local)

A strictly recognized older invalidation marker can now be explicitly abandoned
when its attempt checkpoint and unchanged execution record still bind the job.
Read-only review does not alter records or issue commands. Confirmation archives
the remaining marker and execution bytes before cleanup; it never reconstructs
the missing original job or makes the print resumable. Missing checkpoint,
changed execution, mismatched job fingerprints and extra marker fields refuse
without cleanup. Missing or damaged referenced archives still refuse.

This supersedes the blanket legacy-marker refusal above only for this bound
interrupted-abandonment case. Missing/unreadable execution and legacy records
without an attempt remain open. The review message explains that missing
original data cannot be restored. 40 focused backend/native-worker checks pass.
Local and undeployed; ARM artifact and live presentation qualification remain.
No printer actions were issued.

### 11 November — recovery compatibility candidate built and packaged

The changed confirmation worker, native runtime compilation and retained-client
profile checks pass (3 checks). ARM build completed successfully. The r123
development delivery export verified its compiled inputs, runtime dependencies,
vendor profile and ELF contract:
`analysis/validation/2026-11-11-managed-audit/qualification-export-r123`.
Artifact SHA256:
`bcad3ae967514d5964005d8ccc5513b8e88dffead296a168aaf4477070262083`.
This is a packaging-control-only candidate, not an installed or released build.
r122 remains installed; native recovery presentation/confirmation qualification
is still open. No unmodified stock behavior was retested and no printer actions
were performed.

### 11 November — r123 publication observed; installer completion pending

The first screen-only installation refused the older wm_material.py before
activation; its earlier component publications were restored. Its journal
`f028374faae84ecaaf1446505417c74e` retains recovering/inflight-preload state,
so it is not recorded as a fully closed transaction. Readback after refusal
showed unchanged session, configuration, PID and filament state.

A new installation explicitly includes material and preload. Journal
`c21e6c2a435e4179a15aafd941d93eda` records material/Moonraker complete and
preload in flight. Direct readback finds active Klipper and screen services,
new processes, Ready/standby/unpaused, zero targets and the exact r123 artifact
SHA256 `bcad3ae967514d5964005d8ccc5513b8e88dffead296a168aaf4477070262083`.
The installed material helper matches local SHA256
`783fd53475f2ab5ceb909c16aaef4fd9f218c67b9b63a15f8bc66050758ad8b9`.
Effective settings, saved variables, all four PID values, identities, nozzles,
physical mapping and loaded flags remain unchanged; sessions changed.

The installer remains live without a terminal acknowledgement. Publication
and Ready readback do not close its transaction or qualify recovery UI actions.
Do not start another installer or replay its restart solely because it is slow.
Preserve the running session and journals for investigation. No motion, heat
or print was requested. Evidence: r123-install.log, r123-before/after-status.json,
r123-preservation.json and r123-screen-only-rejected.log in the audit directory.

### 11 November — r123 installer wait diagnosed; observation reconnect fix

The installer was deliberately interrupted locally after independent readback
verified publication and remote process inspection found no pending installer
command. It exited 130; no installation was replayed. Its traceback proves the
first failure was SSH channel opening for the read-only is-active observation
after restart. The rollback handler then stalled opening another channel on the
same connection. The local interrupt occurred in that second channel-open wait,
before its service-stop command was dispatched. This supersedes the earlier
assumption that the installer was simply awaiting a command acknowledgement.

Local installer changes bound the service-query channel-open wait to ten seconds
and reconnect solely for observation. They reset the stable-ready count and do
not repeat restart/start/stop. Tests retain the changed-PID and two-ready-samples
requirements. The r123 exported installer remains immutable and unchanged. Its
journal still needs explicit resolution; active services and matching hashes
do not mark that journal complete. The initial screen-only journal likewise
remains historical unresolved evidence, not permission to roll back over newer
publications. No additional printer restart, motion or heating was issued.

Validation: 84 focused deploy/restart checks plus the added transport-handle
replacement test pass. This is an installer-only change; no ARM rebuild needed.

### 11 November — r123 independently accepted; both journals closed

Read-only reconciliation verified all seven publication targets and their
backups against the retained publication journal, the changed material helper
against its receipt, and every required helper/configuration against the staged
package. Required backend protocols pass. Two Ready observations show backend
PID 1149765; screen PID 1149782 maps the published library without deleted
mappings. Native bootstrap is Running (11), and sampled polls advance with an
unchanged failure count. The snapshot shows Home without an error banner and
zero heater targets. Pre/post preservation evidence remains as recorded above.

With the original installer terminal (exit 130), fresh verification under the
local journal lock completed the existing preload receipt and marked journal
`c21e6c2a435e4179a15aafd941d93eda` applied, inflight null. This did not replay
publication, restart or rollback. The older rejected attempt's staging directory
contains no publication journal; its Moonraker rollback was already receipted.
It is now marked restored, inflight null, without touching the newer deployment.

This supersedes the pending-install status above. r123 is installed and idle
acceptance is complete, including the recovery archive/legacy-marker backend
and updated confirmation text. It does not qualify a physical recovery or the
native resolution workflow. Evidence: r123-reconciliation-final.log,
r123-reconciliation-readback.json, r123-native-diagnostics.log,
r123-preservation.json and navigation-r123-home.jpg/json. No additional
printer restart, movement, heating or print was issued during reconciliation.

### 11 November — live reset guard qualification blocked at navigation

The installed guard's refusal presentation was the next changed-path check.
Remote Settings taps returned HTTP success but did not navigate, including a
300 ms hold through the same device injector. Captures r123-settings,
r123-settings-settled, r123-settings-retry and r123-longtap-result remain on
Home. No reset control was reached, so no factory action was attempted. Backend
remained Ready/standby with zero targets and no probe-editor request.

The client still binds /dev/input/event0, matching the Goodix device. A sampled
main-thread futex wait is not a deadlock diagnosis. Diagnostic log silence also
is not proof of a stall: ScreenDiagnosticLog stops after 60 initial entries
except bounded navigation/failure updates. An initial stall interpretation was
therefore withdrawn. Physical Settings tap feedback has been requested to
distinguish an input-injection problem from native-screen responsiveness.
The installed-file/protocol acceptance remains valid; interactive acceptance
is open. No restart or printer motion was used to mask the symptom.

### 11 November — reset interception qualified; notice layout correction

Direct reads of the known native diagnostic counters showed refresh advancing
12877→12917 and status polls 1704→1709 with failures fixed at 17. The stock
input reader had X=0/Y=403 after remote taps at X=45/Y=403. A tap at X=46/Y=402
opened Settings immediately; General navigation then worked. This narrows the
miss to stale input-coordinate delivery across client restart, not a proven
WM+ deadlock. No physical-touch failure is inferred.

General → Restore Factory Settings → Confirm was intercepted by the installed
guard and showed the managed refusal. CLOSE dismissed it; no stock progress
popup or reset operation followed. All 297 configuration-file hashes and 155
print-file size/mtime records match before/after. Saved variables, wm_material,
wmp_recovery and backend session were identical. Toolhead position/homed state
were identical; only estimated_print_time advanced. No motion/heating/restart.

The live refusal panel lacked an opaque fill, so menu text showed through.
StockNotice now explicitly sets its panel background opaque and puts its
uppercase text CLOSE action in the top row. The transparent input-blocking
backdrop remains outside the panel. Native lifecycle test passes, including
opaque fill, action placement, retained refresh, and closure. ARM build pending.
Evidence: r123-live-counters.log, r123-input-state.log, navigation-r123-coordinate-
check/general/reset-prompt/reset-refused/reset-close.jpg/json and
r123-reset-before/after.json under the managed audit directory.

The notice correction built successfully for ARM and exported as r124
(packaging-control-only), artifact SHA256
`d61d3a9be04349dc89eff929889075008b15cb9f3b94c8c5ec067471870f7bee`.
Its export also contains the tested read-only SSH observation reconnect fix.
r123 remains installed; r124 deployment and visual confirmation are pending.

### r170 native visual follow-up — REVIEW interaction unresolved

A second genuine wait-only cancellation interruption restored the unknown record
on r170. Neither short taps nor a held touch on REVIEW visibly advanced the
panel. CLOSE did dismiss it, and native diagnostics showed continuing fresh
status polls, narrowing this to review interaction/admission rather than a
screen-wide touch freeze. No cleanup confirmation was observed. The durable
unknown cancellation remains held; the panel is currently closed. Investigate
before accepting the terminal rendering. Evidence: `navigation-r170-review-held.*`,
`navigation-r170-close-diagnostic.*`, `r170-touch-diagnostics.txt`, and
`cancel-interrupt-r170-*.json`. This does not invalidate the earlier r169 review
acceptance, but prevents claiming the changed candidate is fully validated.

### r170 terminal rendering accepted; touch-position discrepancy isolated

After a screen-only restart, REVIEW at (712,30) responded. CONFIRM at (738,20)
did not advance; CONFIRM at (712,30) completed the same reviewed acknowledgement.
This narrows the interaction issue to hit testing/input coordinates, not backend
review refusal; the screen restart alone is not established as the cause.
`navigation-r170-resolved-lower.jpg` shows the corrected terminal view: one result
message, two gray completed review/verification stages, no orange active or white
future execution stages. The real cancellation hold is now resolved. Native
visual acceptance of the display correction is complete; the coordinate-dependent
header interaction remains an open defect to investigate.

### Input-reader investigation — timing alternative remains open

Offline inspection of the pinned factory client found `evdev_read` at 0x73ca44.
Its loop at 0x73cd8c reads until the event queue is empty, then publishes only the
last coordinate/state (0x73ce00–0x73ce44). It does not return at SYN_REPORT.
`device/wmp_screen.py` injects an 80 ms tap. The r170 diagnostic captured a
192 ms maximum GUI gap, so a down/up pulse can be drained in one read without
LVGL observing pressed. This is a plausible timing explanation, not proof that
it caused the REVIEW failures; the 250 ms held gesture also failed once.
Do not classify the coordinate-dependent observations as a proven layout defect
or change the button layout until input timing/hit testing is isolated.

### Remote coordinate readback

A harmless tap at (738,20) on the completed panel was read back from the pinned
factory client's `evdev_root_x`, `evdev_root_y`, and pressed state as exactly
(738,20,0). Evidence: `r170-input-coordinates.json` and
`navigation-r170-coordinate-probe.*`. This rules out a coordinate transform for
that observation, but does not prove LVGL saw the intervening pressed state.
The factory queue-drain timing and managed-widget hit testing remain distinct
hypotheses. No factory input behavior has been changed; do not count this as a
confirmed WM+ button-layout regression or repeat printer motion to investigate it.

### r177 standalone Load interruption — accepted; source correction

The user corrected the physical Head 1 source to ACE slot 4 (internal slot 3),
Sunlu PLA gray, and manually removed/retracted it. The earlier eSUN green /
slot 1 preparation identification was incorrect and is superseded; it is not
a successful unload qualification. Raw Head 1 inlet sensor subsequently read
clear. Its identity was corrected to Sunlu PLA gray (#808080).

On the installed r175 candidate, genuine operation `r177-service-interruption-h1`
reached Insert filament with the inlet clear. One controlled client/Klipper
stop/start restored it as unknown at that stage, with all heater targets zero,
Head 1 empty and attached, and Heads 3/4 loaded states preserved. It did not
resume feeding. Native RECOVER completed the three numbered cleanup stages
(wait for motion, heater off, sensor verification), all gray, and displayed
“Stopped. Head is empty.” No subsequent motion or loading was requested.

The first 80 ms remote RECOVER tap did not advance; a held touch did. Keep
physical quick-touch follow-up open; this does not establish its root cause.
Evidence in `analysis/validation/2026-11-12-managed-audit/`: r177-service-*.json,
wait-r177-interruption-restored-status.json, navigation-r177-recover.*,
navigation-r177-recovery-reviewed.*, and navigation-r177-recovery-held.*.
This accepts the standalone insertion-stage interruption/recovery case only,
not every R26/R27 interruption path or openACE integration.

### Procedure action refresh defect — local follow-up to r177

The missed short RECOVER touch prompted source review.
`StockFilamentProcedure::update()` first disabled the main action because the
procedure was already submitted, then enabled it again for STOP/RECOVER/DONE.
Every changed status snapshot could therefore introduce a transient disabled
state even when action availability was unchanged. The native lifecycle
regression reproduced this on a temperature-only refresh (assertion failed
before the fix). The local correction computes final availability and applies
it once, retaining refusal when the operation/session/freshness changes.

This is a confirmed unnecessary state transition, not proof that it caused the
physical or remote missed taps. The native lifecycle harness passes (1 passed, 42 deselected), including stale
context refusal and retained widgets. The pinned offline ARM build passes with
SHA256 `be6b976f934260139fca6d405a1970a3f2b3c557970bed42daac55d6213da408`.
Deployment and live touch acceptance remain pending; r175 remains installed. No printer restart or repeated filament cycle
was performed for this investigation.

### r178 deployment — procedure refresh fix installed

The verified r178 staging export was installed through the normal preload
installer after idle/zero-target admission. The installer performed its required
controlled restart once and completed. The active screen process maps the exact
candidate SHA above; native bootstrap diagnostics report bootstrap=11. Material,
calibration and retirement backends match current sources. The home screen
renders normally. Identities, nozzle metadata, physical mapping and all four
loaded-state records survived, with all heater targets zero.

Evidence: `r178-native-diagnostics.log`, `r178-preservation.json`,
`navigation-r178-home.*`, the applied journal under `qualification-export-r178`,
and `/tmp/wmp-r178-deploy.log`. This is installation acceptance, not confirmation
that the observed missed short RECOVER tap is cured. Physical short-touch and
changed-procedure interaction acceptance remain open. No print, load/unload,
homing or tool motion was requested during this deployment.

### r178 adjacent action-state audit

Reviewed enabled-state writes in the native recovery/cancellation progress,
pause prompt, preview controls, Toolheads, nozzle editor and brand controls.
Those reviewed update paths choose one final enabled state rather than the
procedure's former unconditional disable followed by re-enable. No additional
production change was indicated by this targeted audit; it is not a claim that
every possible input-loss cause has been excluded.

Extended the native lifecycle regression to assert that STOP receives no
disabled-state write during a changed heating-temperature sync, alongside the
RECOVER regression. The harness passes (1 passed, 42 deselected). Existing
stale-status and changed-operation cases still verify refusal. Tests only;
the installed r178 artifact is unchanged and needs no rebuild or restart.

### r179 changed STOP control — native short-tap acceptance

On installed r178, Head 1 was sensor-clear, mounted, and idle. The first
backend-started setup reached insertion but did not open a native progress
panel; it was explicitly cancelled through the bound cancellation endpoint.
That setup is not native-button acceptance. No filament was fed.

The subsequent operation was started through the native Head 1 Load dialog
with Sunlu PLA gray. It reached Insert filament at the service position
X=-13/Y=80, observed through the camera. A single normal 80 ms injected touch
on STOP (714,125) cancelled operation `wm-2957413451-660289668-2`; its heater
target became zero. A later screenshot shows STOPPED and the cancellation
message. No held-touch fallback, second STOP, restart, extrusion, purge or wipe
was used for this native interaction. The setup homed only X/Y as needed.

Evidence: `navigation-r179-native-{start,progress,stop,stopped}.*`,
`wait-r179-native-inserting-*`, and r179-service-* under the November 12 audit.
This accepts the changed control in that live case. It does not prove all
intermittent physical touch loss resolved, nor requalify load/unload distances.

### User scope decision — defer factory reset support

Factory reset / clean return-to-stock support is outside this initial release.
Retain the installed guard; no reset implementation, destructive reset test,
or reset-preservation policy is required to release this scope. This supersedes
earlier entries describing full managed reset as a blocker. It does not defer
automatic discovery/configuration writers that can conflict with normal WM+
operation, nor the managed calibration workflows.

The user also confirms the Factory/Service code is unknown. Record that
password-success route as unverified, not passed; do not keep requesting a code
the user does not have. No printer files or running services changed.

### Model startup writer — narrowed compatibility finding

The retained model include script preserves WM+ recovery/material sections and
SAVE_CONFIG PID bytes when toggling its intended chamber include on a disposable
managed configuration. Enable, disable, repeated and reverse selection cases
pass; the full six-case vendor-writer suite passes. See the corresponding
upstream-client-callers.md entry for scope and limitations. No live model change
or additional reboot was needed. This removes a speculative data-loss concern
for this writer; it does not close all discovery/topology or external-writer
qualification.

### R24 changed-code evidence map — no fresh calibration prerequisite

Reviewed the actual assertions, not merely test names or suite counts. Existing
accepted results cover these changed responsibilities:

| Changed responsibility | Existing evidence |
|---|---|
| Successful finalization required before one save; stale/binding failures refuse | `test_manual_probe_acceptance.py`: receipt/finalizer and editor lifecycle cases |
| Durable intent before writer; failed/wrong restart receipt stays unknown, without replay | Same file: `test_save_intent_precedes_writer_and_survives_unknown_outcome`, `test_save_requires_writer_restart_receipt_and_never_replays`, and journal-failure case |
| Actual retained writer persists offset and backup before requesting restart | `test_probe_config_change.py::test_retained_save_requests_restart_only_after_persisting_offset`, disposable files |
| Ready restores review without commands; explicit review binds current evidence; stale, pending, corrupt or replaced evidence cannot ACK | `test_ready_restores_save_review_without_replay`, including mismatch/repair and lost durable acknowledgement branches |
| ACK requires matching configuration; RETAIN requires reviewed eligible difference | `test_probe_save_record.py` persistence-boundary tests and command integration; r175 correction installed |
| Native worker uses background transport, suppresses duplicates and waits for authoritative receipt | `tests/unified_ui/probe_editor_worker.cpp`, REVIEW plus both ACK/RETAIN branches |
| Native controls retain widgets, hide jog controls during review, show configuration differences, bind action/token and reject stale taps | Probe-editor block in `tests/unified_ui/native_lifecycle.cpp`, plus flow tests |

The accepted 97 backend/journal cases, subsequent 138 command/native integration
cases, and current native lifecycle pass are already recorded above. No code
changed during this evidence review, so those suites were not rerun. These
complementary boundary tests do not pretend to be a single physical end-to-end
calibration. They do establish the changed persistence and control contracts;
a new nozzle-to-bed measurement would not add evidence for those contracts.
Native pixel layout remains explicitly unverified for the saved-review states.

### R23 changed-code evidence map — existing coverage accounted for

This review closes the vague coverage-review task, not support for arbitrary
hardware remapping. The command intentionally refuses changed mapping without
independent calibration ownership. The earlier requirement to implement a new
changed-topology workflow is superseded by the release scope correction above.

| Changed responsibility | Existing evidence inspected |
|---|---|
| Stage without writes; refuse incomplete observations; restore on write failure without overwriting concurrent edits | `tests/test_identification_transaction.py` staging, failed setup, write failure and concurrent-edit assertions |
| Preserve loaded flags and PID for unchanged identification; verify on fresh startup without commands | `tests/test_identification_commands.py::test_confirmed_unchanged_mapping_preserves_loaded_flags_and_pid` |
| Refuse changed identity mapping without provenance, leaving configuration and journals untouched | `test_changed_identification_cannot_infer_calibration_ownership_from_old_uuid` |
| Recheck admission before subsequent pickup and publication | Command tests for mid-operation session/generation/owner/editor/cancel changes and generation change at publication |
| Retire old native identification workers and bind managed results/restart to session | `tests/test_identification_native.py`: compiled flow, exact retained-client addresses and built ARM RET-only entries |
| Suppress only the mutating native startup discovery call; forward other callers | `tests/test_stock_restart_boundaries.py`: exact policy and built ARM wrapper argument/return/forwarding checks; accepted 22-case result and r132 preservation evidence above |
| Refuse direct saves under managed holds before any file write or restart; preserve admitted vendor writer | `tests/test_probe_config_change.py`: both SAVE_CONFIG aliases, actual retained dispatcher/writer, temporary config and backup assertions |
| Admit only the active managed job's mesh-only non-restarting save | Same file: `test_managed_startup_mesh_save_uses_retained_writer`, including wrong job/file/mesh, extra-setting, remote and cancellation refusals |
| Preserve managed data through the model include writer | Previously accepted six-case vendor writer suite; model change itself is not a release qualification task |

Existing accepted identification/transaction, native startup and config-save
results remain valid: this review changes documentation only, so it did not
rerun them or restart the printer. Pure permutation planner tests are not evidence
that the live command supports hardware remapping. No new physical calibration,
configuration mutation or factory-service access is required by this review.

### Remaining visual checks and conflict-report reconciliation

The local browser preview uses the host screen controller rather than the native
`StockProbeEditor` / `StockRecoveryProgress` LVGL implementation. Its screenshots
would not establish pixel layout for R22 retirement or R24 save review. Those
checks remain explicitly open; no synthetic production recovery or calibration
record was created to reach them. Native lifecycle assertions remain the existing
functional/render-property evidence.

The release summary in `docs/upstream-client-callers.md` now agrees with this
checklist: no unspecified cleanup matrix, deliberate mechanical failure, or
factory-reset implementation is a release prerequisite. The report still names
the actual stock entry points and the managed ownership conflicts they cause.
No implementation changed and no printer operation was performed.

### Original checklist reconciliation — persistence and filament service

B04, D01, D05 and F02 now reflect later accepted evidence in their original
checkboxes, with explicit current-evidence notes preserving the historical record.
No test was rerun. The clean-stock-home export test verifies installation and all
eight helper files in a disposable filesystem; it does not boot the native
client/Klipper stack, so A02 is not silently promoted to a live clean-install pass.
Remaining original C/E/F/G entries still need reconciliation before the whole
release can be declared validated.

### Original checklist reconciliation — motion admission and print evidence

C04 and G02/G07 now carry the accepted evidence described above. E05 explicitly
retains both completed coupon results; a repeated single/mapped print is not the
next action. Remaining review must resolve the changed leveling/timelapse option
handoff and E04 admission coverage, not qualify stock recording or print quality.
F01/G01 paused/runout acceptance, G03 first-run native completion, A02/G06 clean
installation/promotion and B03/F04 current physical-touch feedback remain distinct
open items unless later evidence closes their specific requirements. R22/R24
visual review remains separately recorded in the current integration table.

### Print-option handoff — focused missing assertions closed

Source trace: native Runtime binds PrintContext to stock screen-start, selected
timelapse and availability bytes; StandaloneBackend prepares that context before
submission. The JSON request carries leveling to `cmd_START_PRINT`, which chooses
G30 or G31 before the single SD submission. Timelapse is intentionally native
client context, not a missing backend request field.

Added the previously absent standalone leveling-off branch to the existing
submission test: both G30/G31 paths preserve live/backup mappings, send one file
start and refuse repeat submission. Added successful timelapse-enabled handoff
to the compiled PrintContext test, preserving the global availability setting
and accepted selected flag. Existing assertions retain unknown-result ownership
and prevent duplicate starts. Focused results: 2 backend cases passed; 1 compiled
standalone test passed. No production code changed, no printer contact, no repeat
print and no stock camera-recording qualification.

This closes the option-handoff coverage gap identified under E05. Its accepted
single/mapped executions remain valid. Paused/runout acceptance is still F01/G01;
this test does not claim that attended flow has completed.

### First-run FINISH — joined native/persistence coverage

The native lifecycle test now connects Runtime's FINISH callback to the production
`finish_setup()` helper in a disposable directory containing `need_oobe`. All
existing busy/stale/calibration admission refusals remain; callback failure keeps
the marker and prevents Home navigation. Accepted completion removes and fsyncs
the marker through the actual helper before navigating once. The native suite
passed (1 test, 42 deselected). Separate existing filesystem fault tests still
cover unlink/fsync errors. This closes the mock-only callback integration gap;
it does not claim live wizard entry or actual power-loss durability validation.

Attended runout preparation: user is available and authorizes independent ACE
feed/retract as manual assistance. r180 baseline is Ready/standby/unpaused, all
heater targets zero, X=-13/Y=80/Z=0. Camera is too dark to establish bed clearance;
current filament route and bed confirmation requested before motion. No new
print, heater or ACE movement has been commanded.

### r180 ACE-assisted H1 preparation — no load completion

User confirmed Head 1 / ACE slot 4, Sunlu gray, and clear bed. Camera became
usable after setting the light preference ON and closing the old result. Native
Load started `wm-2957413451-660289668-4`, heated H1 to 220 C and reached insertion.
A separate serial helper sent at most sixty 10 mm feed requests to internal
slot 3, with head-sensor checks and a final stop. This is 600 mm requested, not
measured filament travel. Head sensor never became present, so assist mode was
never entered. Helper reached its bound; WM+ independently timed out insertion.
Final Ready/standby snapshot confirms all targets zero and unchanged XYZ at
-13/80/0. ACE readback confirms idle slots. No print or runout recovery occurred.

Latest slot-3 travel record: motor length 9, decoder 0 (defaulted decoder field).
Operator reports filament gripped but no visible movement. Subsequent ACE status
reports slot 3 empty; whether the operator repositioned filament is pending.
Do not infer a blockage or successful feed from command receipts. Independent
serial identity check found the expected single adapter 5B5F011090. No further
feed is justified until the physical/telemetry discrepancy is understood.
Evidence: r180 screen/camera/status snapshots in the November 12 audit; temporary
bounded helper `/tmp/wmp_r180_feed_remote.py`. No WM+ production code changed.

r180 no-motion follow-up: operator confirms gray was gripped but no movement was
visible. Read-only protocol review confirms the helper uses finite forward-feed
mode and mm-valued length; a defaulted zero decoder value is not measured travel.
The temporary helper now checks slot presence and positive encoder movement after
every increment, refusing the next increment on missing/no-motion telemetry. It
has only been syntax-checked, not rerun. The earlier helper's 600 mm request count
must not be described as actual feed. Physical slot-clear discrepancy remains
pending operator clarification. No additional motion, heat or print was sent.

### E04 print admission evidence reconciled

`test_print_refusal_has_no_side_effects`,
`test_partial_print_submission_is_unknown_and_never_retried`,
`test_file_change_during_preparation_prevents_start`, and
`test_prepared_print_rechecks_backend_before_sd_dispatch` cover the named changed
admission boundaries. `tests/unified_ui/standalone.cpp` covers the worker-to-
request mapping, one-shot transport and authoritative outcome matching. Existing
accepted backend results and the just-passed compiled standalone harness apply.
E04 is now checked in its original location; no tests were rerun for this review.

### r180 current-source delivery staging

Created `qualification-export-r180` with the actual packaging command. Source and
artifact verification passed; screen hash equals the installed r178 artifact.
The bundle retains `packaging-control-only` and therefore remains ineligible for
normal release activation. No deployment, restart or publication occurred.
This replaces the obsolete r177 destination in the staging summary; existing
installer test results remain accepted and were not repeated.

### r181 slot 1 substitution — preparation stopped on encoder discrepancy

Operator identified broken filament jammed in slot 4 and directed use of slot 1;
confirmed eSun green PLA and clear path to Head 1. Only internal ACE slot 0 was
commanded. Recorded Head 1 identity eSun/PLA/#00A651 with expected revision and
started `r181-slot1-h1-load`. At insertion/220 C, the bounded helper fed slot 1
with encoder checks. It stopped on insufficient positive travel before H1 sensor
presence, so assist was not entered. Cancel endpoint accepted; final snapshot
shows Ready/standby, all heater targets zero and XYZ unchanged at -13/80/0.
Latest slot-0 telemetry reports motor length 9 mm, decoder 1 mm. This does not
establish the tip location or a successful load. Operator observation requested.
Slot 4 was not commanded. No print/runout acceptance is claimed. Evidence:
`wait-r181-*-status.json` and camera captures in the November 12 audit.

### r182 bounded slot 1 feed — receipt is not filament travel

Following the operator's observation that slot 1 advanced but had not reached
Head 1, issued one further 20 mm feed at 10 mm/s with all heaters off. Camera
inspection preceded the command; printer remained Ready/standby at the purge
position. Sampled motor length rose through 2/9/17 to 19 mm; encoder remained
zero/defaulted throughout, and H1 sensor remained clear. Finally stopped slot 1;
ACE readback shows all slots ready and assist count zero. No assist, heating,
print or runout test was started. Requested visual confirmation of actual tip
movement and distance remaining before further feed. This does not establish a
slot 1 jam or successful load. Slot 4 remains untouched.

Independent checklist review: C03 still explicitly lacks touchscreen distance
dispatch/physical travel acceptance; r88 backend E deltas alone do not close it.
E05 now references the existing option-handoff pass rather than requesting that
test again; its remaining paused/runout portion is the current attended test.

### r183–r185 slot 1 feed continuation

Operator reported tip more than 900 mm from Head 1, then explicitly requested
900 mm feed. The preceding bounded 100 mm request completed with encoder 0–1 mm.
The subsequent 900 mm request completed with motor length 899 mm and encoder
882 mm. A further monitored 30 mm feed measured 30 mm on both motor and encoder.
H1 sensor remained clear throughout; no assist was entered. Both helpers ended
with slot-ready/assist-count-zero readback. Camera monitored the stationary head
at the purge position; all heater targets remained zero. Asked operator for
current tip location before additional feed. Evidence: r184/r185 ACE feed logs
and before/during camera/status captures. This is preparation, not Load or
runout/replacement acceptance; no production code or installed services changed.

### r186/r187 Head 1 preparation completed

Operator estimated another 400–500 mm to head. Bounded 400 mm request stopped
early when H1 sensor became present at reported motor/encoder 309 mm, switched
briefly to assist, then stopped. Started managed `r187-slot1-h1-load` with slot 1
assist maintained through heating/loading/purging/wiping. Backend returned
complete; helper stopped assist and confirmed idle slots. Final snapshot shows
Ready/standby and every heater target zero. Camera captures cover preparation
and final head position. This establishes managed Load completion/readback, not
physical purge quality or the still-pending attended runout/replacement check.
Evidence: r186/r187 ACE helper logs and wait-r187 status/camera captures.

### r188–r190 native paused replacement acceptance (partial F01/G01)

Ran the 509-byte `WMP_PAUSED_REPLACEMENT_20261112.gcode` after idle G28 with
Head 1 mounted. The job moved to the purge position, heated to 220 C, and invoked
PAUSE; no part deposition was included. Native filament menu → H1 Unload →
confirmation completed with numbered four-step result. Pause origin was retained
(id c2e3bf5b285d438f830351d603ddcd63, file position 383). Separate ACE rollback
simulated manual removal: H1 sensor cleared at approximately 55 mm measured
withdrawal. Native Load retained eSun/PLA/green; separate bounded feed followed
by assist supplied filament. Seven-step Load completed with purge/wipe and heater
off. Service snapshots retained paused Z=17 mm; no service Z home was requested.
The runout banner appeared on physical sensor clearance without replacing this
managed flow. Native RESUME was tapped once; G-code store contains one BEGIN,
one RESUMED_ONCE and one END response. Final print state complete, unpaused,
nozzle target zero; ACE assistance stopped.

This accepts same-head paused replacement and single-resume completion. It does
not prove runout-triggered pause from active printing, cross-head replacement,
or exact instantaneous return coordinates: the final snapshot follows completion
cleanup, which moved/disabled axes. Retain those limits rather than checking all
of F01/G01. Evidence: navigation/wait r188–r190 snapshots, r189 helper logs,
r190-observe.log and r190-gcode-store.json in the November 12 audit.

### r191–r193 genuine sensor runout and recovery — extrusion-coordinate gap

After operator cleared bed, idle G28 succeeded. The staged runout job heated and
shaped/withdrew filament at the purge position. Receipt-gated ACE withdrawal
cleared H1 sensor. Logs show detection, 2.5-second recheck, and automatic PAUSE.
Native screen displayed WM+ “Filament needed - Head 1”; LOAD opened the managed
eSun/PLA/green editor. Native Load completed with bounded ACE reinsertion and
assist through purge/wipe; assist stopped afterward. A single native RESUME
completed the remaining job. Final state complete/unpaused with every target zero.

GET_POSITION receipts before loss and after resumed execution match physical and
kinematic XYZ (-13,80,7), including identical XYZ step counts. Exactly one
WMP_RUNOUT_RETURNED_ONCE and END receipt were recorded. However E/base changed
from -10/-10 to 95/200, corresponding to a logical extrusion-coordinate change
from 0 to -105 (factor must also be checked). Do not close F01/G01: investigate
this parser-state discrepancy and its effect on absolute extrusion. Existing
`run_standalone_extrusion_sequence` explicitly compensates for vendor RESTORE
omitting base-position restoration, while RESUME uses RESTORE_GCODE_STATE PAUSE.
This is a lead, not yet a proven root cause. No production fix or retest yet.
Evidence: r191–r193 camera/native/status captures, helper logs and
r193-gcode-store.json.

### r194 local Resume logical-E correction

Confirmed root cause against firmware 1.1.13's actual GCodeMove handlers:
vendor RESTORE leaves base_position unrestored but adds the physical E delta.
After a managed 105 mm Load preserving logical E, the outer PAUSE restore shifts
logical E a second time. Added WMP_RESTORE_RESUME_E after RESTORE and before
CLEAR_PAUSE/M24. It reuses job/owner/service admission, requires restored XYZ and
extrusion factor, and issues G92 for the captured logical E without moving any
axis. The installation command contract now requires this helper.
Actual-vendor regression checks cover absolute/relative E and non-default flow,
including a subsequent 1 mm command with correct physical travel. First focused
run: 18 passed. Admission/refusal checks: 35 passed, including busy context,
foreign owners, wrong return position/factor and missing snapshot metadata.
Changes are local only; installed r178 remains unchanged. A targeted deployment
and live logical-E validation are still required.

### r194 runout notification admission (local validation)

User clarified that runout errors require an active print needing that head.
The vendor RunoutHelper emits its notification before checking printing state.
WM+ now guards only that notification for standalone operation: printing,
unpaused, and the matching mounted head are required. Sensor updates and
callback dispatch remain intact; openACE/AFC ownership keeps its existing path.
Actual-vendor regression coverage includes filament and path sensors, idle,
complete, cancelled, paused, an unrelated head, and the required printing head.
Focused sensor/restart checks: 14 passed. Resume macro and installer contract
suite: 625 passed. These are local results, not physical acceptance. Existing
latched notifications are not cleared by this guard. Paired qualification build
and deployment are pending; no release promotion.

r194 deployment completed through paired config/preload qualification installer.
First attempt refused preflight because local Jinja2 was absent; no components
were installed. Retry with Jinja2 passed checks and installed the reviewed runtime
RESUME override and matching backend. Recovery journal:
`qualification-export-r194/.wmp-install-journals/358a6fbe02194e5d9d41cc281cad3ed1.json`.
Installer verified Klipper Ready, touchscreen active, material/recovery protocols
and required commands after restart. No motion or heating test was performed in
this deployment. The screen binary remains unchanged; native hook application
was unconfirmed in the immediate log check. Physical logical-E Resume acceptance
remains open. This is a qualification installation, not a published release.


### r195 live Resume logical-E correction accepted

Uploaded/verified 485-byte WMP_RESUME_E_20261112.gcode, SHA256
9adc48b84dbba7e5e4a43360fe60b8d5ca6c30842531c70ecbe1f0a79db53bf5.
Camera confirmed clear bed; idle G28 completed with H1 mounted before starting.
Job heated at purge X=-13/Y=80/Z=7, set absolute logical E=100, captured
GET_POSITION, and paused. Managed unload r195-resume-e-unload completed;
independent ACE slot 1 withdrawal stopped when H1 sensor cleared (about 46 mm
encoder travel). No runout error appeared on screen or in this job's G-code
store. Managed load r195-resume-e-load used bounded slot 1 feeding, switching to
assist at head detection; completed feed/purge/wipe with assistance stopped.
Service Z remained 17 mm. Native Resume was tapped once.

Before pause: physical/parser E=0, base=-100 => logical E=100.
After Resume: physical/parser E=-5, base=-105 => logical E=100.
After absolute E101: physical/parser E=-4, base=-105 => logical E=101.
XYZ and XYZ MCU step counts match before pause and immediately after Resume:
X=-13/Y=80/Z=7, stepper_x=-6, stepper_y=8, stepper_z=10879.
RETURNED_ONCE, AFTER_1MM, and END each occur once. Final state complete,
unpaused, all five heater targets zero. This closes the observed Resume E defect
and validates paused notification suppression live. Evidence: r195-gcode-store.json,
r195-feed.log, navigation-r195-removed/before-resume/resume, wait-r195-* captures.
No part was printed; the 1 mm verification extrusion occurred at the purge position.
Same-head pause/service/return is accepted; broader requirements remain explicitly
separate in the current table. No additional ordinary same-head cycle is needed.

### r196 tangle ownership reconciliation — local follow-up

Reviewing G01 against the actual vendor helper found a distinct remaining gap:
`hub.cfg` path sensors have `pause_on_runout: True`, so their callback bypassed
the physical-head admission in the filament runout macros. Notification gating
alone did not stop an unrelated path sensor's queued automatic pause. The managed
Resume check also did not inspect the original head's path sensor after replacing
the vendor Resume preparation/check route.

Local correction wraps only each path sensor's vendor runout callback. It rechecks
printing/unpaused state, mounted head, enabled sensor and still-tripped state at
callback execution. A suppressed callback releases the vendor NEVER gate so later
sensor events are not lost. Foreign openACE/AFC owners keep original dispatch.
Resume checks the original head's enabled path sensor before heating/return and
again through the existing guard sequence; an uncleared/unknown path is refused
with “Untangle filament for Head N before resuming.” Other heads' clear/unclear
paths do not block this resume. Missing optional path sensors retain prior support.

78 focused cases pass, including actual vendor callback dispatch and queued changes
(head changed, sensor cleared/disabled, printer paused), Resume path checks, the
logical-E guards, and existing cross-head service failure/return coverage. The
first new Resume fixture runs failed because its filament-presence default was
empty; the tangle test now explicitly isolates the already-tested loaded-state
input. Read-only live query confirms all four installed path sensors enabled and
clear. Full affected backend/runout suites and qualification deployment pending.
No deliberate physical tangle or ordinary Load/Unload repeat is required to prove
these callback admission branches; existing same-head physical acceptance remains.

r196 affected-suite result: **1,430 passed in 182.74 s** across
`klipper_extras/test_wm_material.py`, `tests/test_runout_sensor_callbacks.py`,
`tests/test_native_runout_ownership.py`, and `tests/test_runout_autopurge_guard.py`.
ARM source-bound build and qualification export succeeded; screen SHA remains
be6b976f934260139fca6d405a1970a3f2b3c557970bed42daac55d6213da408.
Only backend source changed for this follow-up. Installer is running against the
idle printer; heater targets were all zero at admission. Deployment log is
`r196-deploy.log` in the November 12 audit.


r196 paired installation completed successfully. The initial preload-only attempt
refused the new backend hash without activation; the corrected config/preload
entry point installed matching helpers with zero config-file changes. Journal:
`qualification-export-r196/.wmp-install-journals/a72dfddea5394061a99828d6e0fbde49.json`.
Klipper Ready, active touchscreen and running protocol/command contract verified.
Immediate native hook log remains unconfirmed; the screen binary is unchanged.
F01/G01 are reconciled as accepted using the combined physical and execution-test
evidence above, not a claim of live coverage for every physical head or fault.
Other release gates remain open. Deployment log: r196-deploy-paired.log.


### r197 checklist reconciliation — no repeated machine test

Previous goal turn made progress: r196 tangle ownership fix was tested, deployed
and committed. This reconciliation inspected the current checklist, the retained
r102 H4 complete Take receipt, the 10 November mapped completion summary, and
r195 coordinate receipts. C02 and E05 checkboxes were stale relative to accepted
results and later user scope; they are now checked with explicit evidence notes.
C03's later native dispatch pass supersedes its old backend-only description;
physical manual-retract observation remains open. Historical dated limitations
are retained so their original evidence scope is not silently rewritten.
No printer command, restart, motion, heating or new print was issued for r197.
Remaining acceptance work includes C03's narrow observation, B03/F04 physical
input after the input fix, G03 first-run, R22/R24 outstanding presentation checks,
and A02/G06 final delivery. G05's audit reconciliation remains separate until its
named affected callers are mapped to the current R23–R26 evidence.

### r197 first-run entry-to-FINISH integration

The native lifecycle harness now includes the production bootstrap handlers and
enters through `unified_setup_filament_guide`, rather than calling
`begin_onboarding()` directly. Both retired guide worker calls produce no loading
commands. The actual Runtime requests exactly one M400 checkpoint, retains the
setup marker while waiting, and navigates to the shared filament page only after
the matching acknowledgement on the next GUI tick. Existing FINISH admission,
failed-write retention, production `finish_setup()` directory flush and one-time
Home navigation checks then run on the same instance.

The initial joined assertions exposed two harness assumptions, not product
regressions: navigation is queued for the next tick, and a calibration failure
is intentionally latched for the Runtime lifetime. That permanent-failure case
remains covered in the separate earlier guide test and is not cleared to continue
the success case. The actual bootstrap dependency was added to this test's include
paths. Final native lifecycle run: **1 passed, 42 deselected in 36.91 s**.
This closes the direct-entry shortcut in functional coverage. G03's live
presentation evidence is still absent; this is a host native integration result,
not a live wizard/physical calibration/reboot claim. No product source or printer
state was changed, so no deployment or printer restart is required.

### r197 activation qualification deferred by pre-existing MCU outage

Exported the current installer as `qualification-export-r197`; native artifact
remains `be6b976f934260139fca6d405a1970a3f2b3c557970bed42daac55d6213da408`.
The pre-install read found standby/unpaused, all heater targets zero, but Klipper
already shut down with ZRU-B007. Retained log evidence shows simultaneous MCU,
HUB, T0–T3 and CELL communication timeouts. This predates any r197 installation;
it does not establish whether USB, cabling or controller power caused the loss.
One acknowledged FIRMWARE_RESTART progressed through startup and terminated with
`Failed automated reset of MCU 'mcu'`. No r197 installation, motion or heating
was attempted. Asked the operator to check main power/controller lights; do not
repeat resets without new evidence. Evidence: `wait-r197-before-status.json`,
`r197-preexisting-fault.json`, `r197-reset-result.json` in the managed-audit
validation directory. G06 fresh native activation remains unverified, and r196
is still the last successfully installed candidate.

Read-only kernel follow-up (`r197-bus-observation.json`) confirms USB hub
`usb2-port1` was disabled/re-enabled at monotonic times 20130.67 and 20212.33;
its children, including the gs_usb CAN adapter, disconnected and re-enumerated.
The first disconnect preceded the simultaneous MCU timeouts at 20135.32.
CAN subsequently returned UP with zero reported bus errors. The kernel's
`EMI?` text is a hint, not proof of an electrical root cause. This is concrete
USB-disconnect evidence rather than an inferred application status problem.
A single full Klipper process reconnect was then attempted because the interface
had been re-created; no repeated firmware-reset loop or USB configuration change
was introduced.

The full process reconnect reached Ready (`r197-process-reconnect.json`). This
resolved the immediate software connection hold after USB re-enumeration; it
neither fixes nor explains the underlying hub resets. The prepared r197 paired
qualification install then began; its preservation preflight reports zero config
file changes. Do not treat this start as installation success; the installer log
and final journal determine that outcome.

### r197 native activation check corrected after device qualification

The r197 installer passed loader, configuration, service-restart and backend
protocol checks, then rejected native activation and restored its receipted
components. Its recovery restart reached Ready; journal
`f1762ed048e84beb8414175b2f4b8ada` and `r197-deploy-paired.log` record the failure.
The checker incorrectly required legacy `gui`/`worker` counters, which the unified
runtime does not increment. Current source updates `timer_matches`, `refresh` and
`status_polls`; acceptance now requires those instead. Tests retain zero legacy
counters to prevent recurrence. All 17 targeted acceptance cases passed.

Native discovery also timed out during startup, independently of that checker
mistake. After recovery, actual local endpoints responded in 31–82 ms and the
native log showed fresh status, 993 refresh callbacks, 122 polls and 15 historical
failures (no current failure inference from the cumulative count). The corrected
checker accepts `r197-screen-observation.json` against the sealed artifact. This
is a read-only real-process observation, not successful fresh installation of the
corrected installer. No heat or movement occurred. G06 remains open for that
fresh qualification and final normal release activation/promotion.

### r198 corrected native activation qualification — passed

Paired config/preload installation from `qualification-export-r198` completed
successfully. `r198-deploy-paired.log` records exact-client/loader admission,
zero configuration changes, both Moonraker patch checks, a new Ready backend,
required protocols/commands, and the corrected native activation check. Journal
`a40bff300cf34263a6e73e4aa848fa88` is `applied`, with all three components
completed, no inflight component and no rollback. Post-install status is Ready,
standby, unpaused, all five heater targets zero (`wait-r198-after-status.json`).
No motion, extrusion or heating was issued. Runtime behavior and screen artifact
are unchanged from r196; this retry qualifies the corrected installer check.

The trailing generic `status` report still says native application is unconfirmed
because it reads the legacy compatibility log. That historical reporting path
must not override the new explicit native acceptance result; align the status
report with current diagnostics before final delivery. G06 remains open for
normal release promotion/activation and the outstanding clean-install scope;
qualification mode is not a release-support claim. Other accepted motion and
filament tests are not reopened by this installer-only change.

### Native status report aligned with r198 acceptance

`tools/components/preload.py::status` now uses one read-only native observation
for the current bundle, with the same executable/library/counter/freshness
validation as activation. It skips the retired compatibility log for this bundle;
legacy packages retain their existing reporting. Stale/missing diagnostics remain
explicitly unconfirmed rather than being accepted from disk hashes alone. The
status path does not sleep, restart or submit commands. 64 affected acceptance/
bundle cases passed, followed by the added full-output current-bundle regression
(1 passed). This reporting-only change does not reopen r198 activation or any
motion validation. It will be included in the final release export.

### Clean exported backend construction (A02)

The disposable stock-home export test now imports and constructs the actual
installed `wm_material` module, then queries its status with no legacy INI,
filament identities, catalogue, or openACE. Minimal Klipper registration ports
provide no command execution or hardware. The assertions verify standalone
ownership, writable empty identities, an empty optional imported catalogue,
built-in materials including PCTG, four initially unknown sensor projections,
and registration of filament/toolhead commands and cancellation endpoints.
Construction does not create a legacy INI or fabricate filament identities.

All 23 export tests passed. A follow-up extension also runs every registered
ready callback using a command registry with removal/replacement semantics and
captured reactor timers. That focused test passed: managed Cancel/script ingress
and configuration-save wrappers activate, AFC-compatible metadata commands
register, and the execution/AFC timers are scheduled. Command execution is a
test failure; scheduled timer bodies are not run.

This closes constructor/status and ready-registration coverage in the export
fixture, not full clean-service activation: live MCU sensors, timer execution,
native rendering, and the brand selector are outside this check. A02/G06
remain open for their remaining clean-install and release qualification scope.
No printer restart, motion, or heating was needed.

### Remaining live-check baseline and clean-start scope

Read-only capture `navigation-remaining-baseline.json` and camera/status files
`wait-remaining-baseline-*` show Ready/standby/unpaused, H1 attached, no homed
axes, zero heater targets, no calibration save review, and no recovery restore
error. Camera inspection shows a clear bed. These are admission observations,
not new functional passes.

`clean-start-file-inventory.json` records hashes/permissions and INI key names.
The stock `tmt1.ini` includes system, screen and nozzle settings as well as slots;
removing it would broaden this test into unrelated stock behavior. Pending the
user's test-target choice, the narrower proposed live test redirects WM+'s
`ini_path` to an absent INI in an empty test directory, then restores the exact
original WM+ configuration. Original metadata and recovery files stay in place.
This can qualify live metadata-free WM+ startup, not a factory-clean installation
or stock startup with its INI absent. No remote files have been changed.


### 13 November — live startup with no WM+ filament metadata

User authorized use of the sole printer. The test temporarily redirected only
`wm_material.cfg`'s `ini_path` to an absent INI inside a new empty directory.
Original stock INI, filament metadata, calibration and recovery files remained
in place. Services were stopped before each configuration change and restarted
for the test and restoration. No heating, motion, Load or Save was submitted.

Actual startup reached Ready/standby, no openACE owner, four head projections,
writable empty identities and built-in materials. Native screenshots show four
empty external cards; Load opens configuration with Generic/Unknown defaults.
The brand grid opens on page 4/7 with Generic selected in orange. The material
selector includes PCTG, PA6, PA12 and PP without an imported catalogue.

Restoration verified the original `wm_material.cfg` SHA256, original identities
and effective loaded states. All 20 inventoried files retained identical hashes,
permissions and ownership; all heater targets were zero. The temporary directory
was archived locally and removed after restoration verification.

Evidence under `analysis/validation/2026-11-12-managed-audit/`:
`clean-start-{original,isolated,restored}-status.json`,
`navigation-clean-empty-{filaments,load,brands,materials}.jpg`,
`clean-start-config-{backup,restored}.json`,
`clean-start-file-comparison.json`, and `clean-start-test-files/`.
This accepts live metadata-free WM+ startup and native built-in selectors. It
is not a factory-clean package installation or stock startup without its INI;
G06 release installation/promotion and remaining native presentation checks stay
open. Accepted Load/Unload and recovery tests were not repeated.

### Explicit reviewed-release export path

The exporter now accepts `--reviewed-release` as an explicit operator assertion
after acceptance. Default exports remain qualification-only. The new path creates
a separate atomic export with `reviewed-delivery` scope; it preserves candidate,
client, source and installer validation and does not install or publish anything.
The existing normal-preflight test now uses this path instead of editing JSON.
21 export cases passed initially; three normal-preflight cases passed after
removing an erroneous direct AArch64 loader call on the host (the existing
subprocess fixture models target dependency resolution). Those cases retain
tampered-source and missing-library refusal checks.

Only disposable test directories used reviewed scope. No release package was
promoted or installed. G06's remaining acceptance and final activation remain
open; the new flag is a release operation, not an automated acceptance verdict.

### Native review presentation fixture — prepared, not installed

`analysis/native-visual-review/` contains a separate test-only ARM library built
with the pinned toolchain. A generated copy of bootstrap replaces its GUI notify
callback with fixed sample views using the actual `StockRecoveryProgress` and
`StockProbeEditor` classes. No action callbacks are connected; no recovery or
calibration records are created. Production source and candidate library are
unchanged. The fixture is explicitly marked VISUAL TEST on-screen and is not a
release bundle.

The matching host lifecycle harness ran successfully with all three sample
views (retirement, save acknowledgement, retain-current review); repeated updates
retain widgets. ARM compilation passed. `manifest.json` records the generated
inputs and artifact hashes. This is preparation for on-printer pixel inspection,
not visual acceptance or backend execution evidence. No fixture is installed yet.


### 13 November — R22/R24 native review presentation accepted

A temporary test-only library rendered the production review panel classes on
this printer at the native content size (690 × 356). Fixed samples covered the
incompatible-recovery discard confirmation, calibration save acknowledgement,
and retain-current review. Action callbacks were disconnected; no production
recovery/calibration records were created and no operation was submitted.

Inspected `analysis/native-visual-review/{retirement,save-review,save-retain}.jpg`:
header actions are visible and legible, numbered stages retain their colors,
summary text wraps within the panel, and controls/content do not overlap. The
retirement confirmation shows CANCEL/DISCARD and the archive explanation. Save
review shows REVIEW/ACK; the alternative shows RETAIN and its explanation. This
closes the outstanding pixel-presentation checks, not a new end-to-end procedure
or persistence claim; prior functional evidence supplies those checks.

The first capture attempt timed out connecting over the host network. The test
was stopped and production restored; logs show continued GUI/status activity,
not a client crash. A verified SSH-loopback capture path succeeded on retry.
The newly created fixture container initially needed a native layout pass before
opening retirement; switching samples after layout produced the captured panel.
This fixture timing is not claimed as a production-route failure.

Both restorations verified the original library SHA256, identities and loaded
states, with all heater targets zero. `original.jpg` confirms normal Home after
restoration; `attempt2/{before,after,restoration}.json` and `cleanup.json` retain
receipts. Four temporary test/backup library copies were hash-verified and
removed. No source change or new production deployment resulted from this check.


### 13 November — G03 first-run presentation accepted

The separate fixture in `analysis/native-first-run-review/` uses the actual
`StockFilamentNative` layout with onboarding enabled, four empty external
sources, and no load/navigation/completion callbacks. ARM compilation and host
lifecycle checks passed, including visible FINISH and retained widgets on repeat
updates. No stock wizard state or onboarding marker was modified.

Inspected `original.jpg` (the fixture capture): four ordered equal-width cards,
centered Load buttons, FINISH at bottom left and Toolheads at bottom right, all
within the native 690 × 356 content area with no clipping or overlap. Combined
with the existing joined production entry/checkpoint/FINISH/durable-marker tests,
this closes G03. The screenshot does not claim physical loading or a full stock
language/network wizard test, neither of which is required here.

`before.json`, `after.json`, `restoration.json` and `cleanup.json` verify restoration
of the exact production library, original identities and loaded states, and zero
heater targets. The two temporary libraries were hash-verified and removed.
No production code changed and no heating or motion was commanded.

### Attended physical acceptance — 13 November

User reported “No missed taps” for quick Toolheads/Filaments navigation and
selector interaction, then “Yes” / “Move confirmed” for the additional 10 mm
manual Retract on H3. The first observation was inconclusive, not counted as a
pass; the user explicitly requested the additional move. It used
`WMP_EXTRUDER_STEP HEAD=2 MM=-10` at machine X=-13, Y=80, with the
nozzle heated to 220 C. Heater was set to zero immediately after M400.
`wait-attended-retract-repeat-done-status.json` under the November 12 audit
records Ready/standby and all five heater targets zero. Camera monitoring
covered preparation and the final state. Preparation used XY homing followed
by managed Take; that separate Take established the bottom Z reference before
changing heads. This is not evidence that Take is XY-only.

B03/F04 and C03 are closed. G06 normal reviewed-release activation remains.

### Final normal release activation — 13 November

All remaining standalone acceptance gates are closed. The user-facing stock
screen conflict report is the release scope summary in
[upstream client callers](../upstream-client-callers.md#release-scope-summary--12-november).
No publication, tag, merge to main or OpenACE support is implied.

Export: `analysis/validation/2026-11-13-reviewed-release`, from `0750e9d`,
explicit `--reviewed-release`, scope `reviewed-delivery`. Ran its normal
`install config preload` without `--qualify-unreleased-screen`. Configuration
preservation reported zero file changes. Journal
`.wmp-install-journals/ace6ed11b9a6487b93b1f20ae4136dba.json` ended `applied`
with config, Moonraker and preload completed. Installer verified fresh running
material/recovery protocols, required commands, exact native artifact identity,
GUI refresh and status synchronization after restarting services.

The final informational status call reported its native diagnostic sample stale
after the fresh activation check had passed. The bounded diagnostic log is not
a continuous heartbeat; no extra restart was performed to refresh that report.
Post-install direct status was Ready/standby, H3 attached, all heater targets
zero. Before/after comparisons preserved every filament identity and effective
loaded state. Evidence: `reviewed-release-verification.json` and
`wait-reviewed-release-final-status.json` in the November 12 audit directory.
This closes G06; earlier dated open gates remain historical, not a new queue.
