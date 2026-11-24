# Early-stop hardware qualification — 2026-11-22

Candidate: `work/r4-print-time-fixes`, `e7f97b07a38a058e573e4437ca5ac712920d6dfe`,
plus `f36ea42` and the confirmed-cancellation warning correction described below.
The user authorized cold tests on the clear printer, then explicitly authorized
active heating, probing, vibration and PID cancellation checks. No publication
is authorized by this qualification. openACE remains outside this standalone run.

## Installation and evidence

The matched configuration, material, Moonraker and native screen candidate was
installed together. Initial native screen SHA-256:
`8fa3692ed69dc1806444db6847213bb62687749706e054abfe15dab7594a90d3`.
The subsequently installed warning-corrected screen has SHA-256
`031bdfa61f512686ed6d7034431a5314cebcb287851c8e72cf1b6e04016a568c`.
All 20 hardware/tuning sections and saved tool positions/offsets matched the
pre-install snapshot exactly. Z was referenced by real native bottom homing;
tests did not use FORCE_MOVE, synthetic coordinates, motor disable or emergency
shutdown as ordinary cancellation.

Local raw evidence is in
`analysis/backlog-qualification-20261122/` in the primary repository (ignored).
`results.jsonl` records individual cases, correlated receipts, final positions,
heater targets and holding state. Before/active snapshots accompany the thermal
tests. `preparation-stop-visible.jpg` and `preparation-stop-done.jpg` are actual
800×480 framebuffer captures. Harnesses run from `/tmp`; no diagnostic runtime
module or configuration was installed.

## Observed results

| Case | Live evidence and limits |
| --- | --- |
| Print Stop via API, console and reviewed request | All three close the cold dwell file, finish every cancellation receipt stage, and prevent the trailing marker. Acceptance is separate from cleanup completion. |
| Normal cold completion | Existing five-second dwell file completes without movement. |
| Queued Home, mesh, PID, vibration and offset | Bound cancellation before the first command prevents execution, movement and heating. These cases alone do not qualify active stages. |
| Home during Y motion | The native Y stroke drains, cancellation is observed after Y, and X does not start. Existing Z reference and holding remain. A fresh XY home subsequently completes. |
| Cold motion / bed clearance | Cancellation drains the admitted XY move and limits the requested bed lowering at the valid bottom reference. Z remains enabled. |
| Dock then Stop before pickup | Unlock, required back-off and verification finish before Stop is consumed. All heads remain docked; no next pickup. Sensor-only reconciliation performs no movement. |
| Pickup then Stop before wiping | Head 3 finishes mounting and backing away before Stop. Its attachment is verified; wiping does not start. Reconciliation performs no movement. |
| Queued filament unload and load | Loaded Head 3 unload and empty Head 2 load are separately cancelled before their first service checkpoint. XYZE is unchanged; no heater, docking, feed or purge begins. |
| Actual filament unload heat wait | Mounted, loaded Head 1 enters its 250°C recipe's heat wait. Stop acknowledges in 0.082 s and finishes by 1.155 s, before tip shaping or E movement. Its heater turns off, filament presence is unchanged, the head remains attached, Z is held, and loaded/pending settings are unchanged. |
| Actual touchscreen preparation Stop | The title, STOP and CLOSE share one header row. Pressing STOP on a no-motion preparation-display diagnostic closes its SD job, prevents its tail, completes cleanup, and reaches “Print cancelled” with DONE. The file simulates progress metadata only; it does not qualify real START_PRINT heat/home/mesh stages. |
| Queued identification and assignment repair | Repeated Stop and repeated Start remain retired without movement or saved-variable changes. Active identification and mapping publication are not qualified by these cases. |
| Active PID heat-up | Head 3 is physically mounted before heating. Stop is observed in the real heater wait, owned targets become zero, normal dock/back-off cleanup completes, and loaded, pending and on-disk configuration remain unchanged. PID coefficients are not saved. |
| Active G29 heat wait | Normal Head 1 selection and Z homing complete. Stop during actual bed/nozzle temperature waiting turns owned targets off and completes docking/back-off. No loaded, pending or on-disk configuration changes. |
| Active mesh point | Real G29 reaches probing at 55°C bed / 140°C nozzle. The current point's samples (including a tolerance retry) and lift finish, Stop is consumed between points, and the next XY point is not admitted. No partial mesh or configuration is saved; docking/back-off completes with heaters off and Z held. |
| Active X vibration | Actual oscillation is observed at approximately 85 mm/s live velocity. Stop acknowledgement takes 0.059 s, the boundary is observed by 0.757 s, and normal docking cleanup finishes by 12.638 s. Y testing never starts; input shaping, motion limits and configuration match the pre-run snapshots. This does not qualify calculation-child cancellation. |
| Probe-editor preparation | Stop during native Y homing returns an aborted editor receipt before later preparation. Acknowledgement takes 0.103 s and completion 8.150 s. Z reference/holding and pending configuration remain unchanged. The reported live Y coordinate during native homing is its temporary coordinate frame, not physical overtravel. |
| Captured manual-probe helper | Full real preparation captures an editing helper. Its bound, serialized ABORT ends only that helper, adds no movement, preserves loaded/pending settings and leaves Z held. No paper adjustment, ACCEPT or save is performed. |
| Active scrub preparation | Mounted Head 1 is preheated and its bed-lowering move is observed. The move drains to Z100; Stop is consumed at the shared tool-service boundary before front positioning. Normal dock/back-off completes, the original four tool offsets are restored and heaters are off. No manual brushing or setter contact is claimed. |
| Ordinary Resume heating | A real SD job heats mounted Head 1 to 160°C without extrusion, establishes PAUSE with E=0, cools, then starts RESUME E=0. Stop is observed during the real temperature wait. No XY return or SD tail executes, filament usage remains zero, heaters turn off, Z stays held, and pending configuration is unchanged. Acknowledgement is 0.139 s; cleanup completes by 8.445 s. |
| Native Maintenance Cancel between PID heads | Actual framebuffer captures show Calibration and CANCEL sharing the header during homing and PID. By the click, Head 1 PID had completed: sampling first observes its saved checkpoint at +67.351 s and cancellation at +68.716 s, then the stop boundary at +69.424 s. No API safety fallback was used. The worker stops before docking/changing to the next head; cleanup finishes and the UI shows DONE, “Calibration cancelled. All heads are docked” and the retained Head 1 PID result. This is not a UI heat-wait pass. |

The native UI recorder's 75-second observation limit expired during docking
cleanup, after the real button's cancellation had already been consumed. Its
saved samples and terminal receipt were inspected rather than replaying Start.
The first completed PID checkpoint matched the on-disk hash
`5bd5fe2cededfd35ad76d691f5afd4fb886fcf7cca6ca7d304c70756c870920d`.
The exact original `printer.cfg` was then restored (guarded against concurrent
changes), and reloaded only after real bottom-endstop reference with every head
docked and every heater off. All 20 hardware sections and saved tool geometry
matched the original snapshots; pending calibration settings were empty. Original
configuration SHA-256:
`e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97`.

The initial queued load attempted on already-loaded Head 3 was correctly
refused by admission; it is not counted as a cancellation pass. Two recorder
assumptions were corrected without changing production behavior: calibration
cleanup intentionally docks the head, and G29 reports “temperature wait” rather
than PID's “heater wait”. The completed G29 result was validated from saved
before/active snapshots without replay. One PID repeat with an empty carriage
was rejected by automatic approval review; it was not executed. Head 3 was
mounted and sensor-verified before the recorded repeat.

The focused regression batch passed **185 tests** covering raw Home, axis
boundaries, coupling, calibration ingress/cleanup, resonance restoration,
completed-type checkpoint persistence, Resume preheat and probe-editor workers.
The candidate's earlier complete offline run passed 6,750 tests with no skips;
offline success does not substitute for the live matrix.

## Identification admission defect found during qualification

The active identification attempt was refused before pickup. Read-only
comparison confirmed that every source UUID matches the corresponding active
MCU. Actual Klipper status lowercases these section keys (`mcu t0`), whereas
three identification planning/restart lookups expected only `mcu T0`.
The identification fixtures had used the latter spelling and concealed this
integration error. Four added regressions first failed against the old code.

The fix accepts exactly one case-insensitive section match for each physical
head and rejects ambiguous aliases, even when both aliases carry equal UUIDs.
It covers ordinary migration planning, assignment-repair admission and
post-restart verification without relaxing hardware identity checks. All
209 identification/migration tests passed. The matched package was installed
and the original hardware/tuning snapshots verified again. No refused test is
counted as active identification cancellation coverage.

## Real-dispatcher defect found on the next identification test

With admission corrected, real pickup and required retreat completed, and Stop
was observed before nozzle wiping. However, identification raised its private
`ValueError` cancellation through `_WMP_OPERATION_STOP_POINT`. The retained
G-code dispatcher treats exceptions outside its `CommandError` family as
internal errors and shut Klipper down before identification-mode cleanup could
complete. This case **failed**, and is not ordinary-cancellation success. The
bed was at the verified bottom reference, Head 1 was attached at Y270, heater
targets were zero and no mapping publication had begun.

The correction raises tagged native command errors at shared boundaries,
preserving identification cancellation classification through its owning
session and cleanup. Owner handoff also uses command errors; real machine
faults retain failure classification. Three tests execute the retained real
dispatcher for cancellation, owner replacement and a genuine fault concurrent
with Cancel. The first two reproduced the shutdown before the fix. All 235
affected tests (212 identification tests and 23 factory-default tests) now pass.

Only the failed test's persisted `is_nozzle_setting=1` flag was cleared with
Klipper stopped; all other saved-variable bytes were preserved. The corrected
source-bound package was rebuilt; repair installation and live retry results
are recorded below. The interim full run passed 6,731 tests but omitted the 23
factory-default tests due to a console-launch import-path collection error.
The full rerun used `python -m pytest` and passed **6,757 tests**, with three
existing warnings, in 425.66 seconds.

The same audit found that recovery's shared nested-homing boundary forwarded
its operational `ValueError` through G-code unchanged. Six new tests execute
the actual retained nested G28 dispatcher. Cancellation, frame validation and
generation change reproduced internal-error shutdown before correction; foreign
actors, replacement owners and owned cleanup remain inert. The shared boundary
now converts recovery's validation/unwind errors to native command errors.
All 490 selected recovery tests pass. No recovery journal was fabricated on the
printer, so this does not replace actual PLR hardware acceptance. The final full
run including this correction passed **6,763 tests with no skips**, with three
existing warnings, in 447.19 seconds.

Final repair installation completed successfully. Installed helper hashes are
`1dd575198b227bba0f151163eb276cc7c6e4de08489c22ffa02e6ddcf44529cf`
for identification and
`bb61a78b78b7940ab9d31572cf90dc9603f2308418124f993e22b3a257d76f6c`
for Stop points. The native ARM artifact is unchanged. Hardware/tuning sections,
saved geometry and cleared identification mode were reverified before motion.

The repeated real identification test **passed**: request acknowledgement took
0.377 s and completion 4.009 s. The current pickup/retreat and an already
admitted wipe finished; Stop was consumed **after nozzle wiping**, before the
next head. Klipper stayed Ready, identification mode cleared, static
configuration hashes and saved geometry were unchanged, and Head 1 remained
attached with Z held and all heater targets zero. No mapping publication began.
This positive result does not erase the retained pre-fix shutdown case.

## In progress and remaining

The real native Maintenance PID-only worker was cancelled using the touchscreen
button **during the first head's heater wait**, with no API fallback. Its receipt
reports `during heater wait`; cleanup docked the head and turned all targets off,
Z stayed held, no PID checkpoint was saved, and loaded/pending configuration
matched the before snapshot. The observer initially expected the synonymous
label `temperature wait`; its postcondition was corrected against the same
terminal request and snapshots without replaying the calibration. The retained
screen shows Calibration and CANCEL on the same header row.

A separate raw Home cancellation exposed a UI defect: physical Stop completed
after Y and its DONE result was correct, but a delayed stock warning offered
IGNORE/RESTART for that expected cancellation. This is retained as a failed UI
case. A narrow GUI warning callback correction is under qualification; it must
require fresh matching owned-request evidence, exact normal cancellation text
and successful completed cleanup. Actual faults, incomplete cleanup, stale
status and other owners must keep the stock warning path.

The correction subsequently passed real qualification. The matching screen
artifact SHA-256 is
`031bdfa61f512686ed6d7034431a5314cebcb287851c8e72cf1b6e04016a568c`.
Installation preserved configuration (zero file changes) and reverified all
20 protected hardware sections and saved geometry. A new raw Home stopped
after Y using the actual touchscreen CANCEL, with no API fallback and Z held.
After viewing and dismissing DONE, Settings and General both displayed normally
without the duplicate IGNORE/RESTART popup. Warning history/banner remains
available. Regression coverage exercises the real callback and retains stock
delegation for real faults, stale receipts and replacement ownership: 52 focused
tests and 57 package/loader checks pass. The full final-source run passed
**6,765 tests with no skips**, three existing warnings, in 454.95 seconds.

Both real filament-service heat waits passed: Head 1 unload and empty Head 2
load were cancelled while their heaters were powered, before extrusion or
insertion. Acknowledgements took 0.082/0.099 s; cleanup completed in
1.155/1.150 s. Filament presence and configuration were unchanged, targets
returned to zero, and Z remained held.

Stop during real input-shaper fitting also completed normally, with the head
docked, all targets zero, Klipper Ready, and loaded/pending configuration and
input-shaper settings restored. The original local observer exited with signal
143; a continuation inspected and cancelled the same active attempt without
replaying it or restarting Klipper. Therefore this verifies calculation-phase
Stop and restoration, but does **not** independently verify child-process
reaping. The incomplete result was not saved.

A later full supported `SHAPER_CALIBRATE` run **closed the child-reaping gap**.
After real X/Y sweeps, direct child 1513984 of Klipper 1510033 was observed in
running state `R`. Stop was acknowledged in 0.042 s, its calculation boundary
was observed at 0.637 s, and docking cleanup completed in 10.941 s. The child
was absent from both the parent's children and `/proc`, while Klipper's PID
was unchanged. Input shaping, all motion limits, loaded/pending configuration
and the exact original printer.cfg hash were restored. Z remained held, the
carriage was empty and all targets were zero. An earlier X-only variation was
refused by the existing bound-command whitelist before motion; the successful
test used the supported command without changing that admission rule.

A real **PID → vibration** attempt verified completed-type persistence. Head 1
PID completed and its checkpoint was saved with SHA-256
`29574fd087fbec49fbd63b8782403bce8e4025780ca6b33ee7222be624c36b2c`.
The same bound attempt then ran actual vibration motion. Stop was consumed
between segments (0.054 s acknowledgement, 12.321 s including docking cleanup).
The PID checkpoint and exact saved file survived unchanged; the interrupted
vibration checkpoint remained unconfirmed and was not saved. Input shaping was
restored, all targets were zero, the carriage was empty, and Z remained held.
This uses the backend's permitted PID-first sequence; it does not claim a
native multi-selection screen order test. Original PID tuning was then restored
byte-for-byte (SHA-256
`e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97`).
After a real bottom-reference check and restart, Klipper returned Ready, all
20 protected hardware sections and saved geometry matched their baseline,
pending settings were clear, all targets were zero and the carriage was empty.

Native calibration Cancel display/dispatch is verified between PID heads and
during the first PID heat wait. Vibration calculation-child termination/reaping
is verified. Remaining guided
scrub/offset stages and re-check, other ordinary Resume
boundaries and valid PLR Continue still need direct acceptance evidence. Multi-type
completed-PID persistence through cancellation of the following vibration type
passed; failure of a following type remains a separate case.
Do not mark the whole 12-family matrix passed
from queued or cold UI-only cases.

Ordinary Resume now also has a real wipe-motion Stop receipt. A genuine paused
non-extruding SD job used `PAUSE E=0` and `RESUME E=0`. Stop was accepted while
the nozzle physically wiped at 200 mm/s (acknowledgement 0.150 s). Admitted wipe
and approach motion drained, and cancellation was consumed **before the
paused-position return**. Cleanup completed in 9.009 s; X stayed off-bed at
-13 rather than returning to the paused X150. No SD tail marker ran, recorded
filament use was zero, loaded/pending configuration was unchanged, heaters
were off and Z remained held. No file/position authority was fabricated.

The actual guided wire-brush flow reached its first manual prompt with Head 1
at 160.2°C, at the front scrub position. Its header displayed CANCEL and CONFIRM
and the body retained the hot-nozzle warning. Touchscreen CANCEL was pressed
without acknowledging brushing. Between-command cancellation restored offsets,
docked the head and completed its mandatory retreat; all saved geometry and
G-code offsets matched their baseline, loaded/pending configuration was unchanged,
targets were zero and Z stayed held. No offset measurement or save occurred and
no API fallback was used. This qualifies the held manual prompt; it does not
claim actual brushing, setter contact or the later re-check prompt.
The terminal native screen was also viewed: Calibration and DONE share one
header, and the result confirms all heads docked and previous offsets restored.

A separate progress-label finding was added to the backlog: the scrub screen
said “Mounting head 1” while initial G28 was still running and the backend scrub
phase was idle. It did not prevent Stop. Its stage timing needs a separate UI
consistency correction; it is not counted as a completed repair here.

Unlock/lock completion, required back-off and post-retreat sensor interpretation
form one non-cancellable normal-operation segment. A queued Stop takes effect
after that segment; genuine coupling faults retain their fault handling.
Off-bed print-cancel parking is a separate unimplemented tracker item.

## Late homing and final mesh boundary follow-up

Real full `G28` was stopped after X homing, during final fixed-X Y reference
verification at X298/Y5. Two identical bound Stop requests acknowledged in
0.047/0.043 s. Cleanup completed in 1.628 s, Z never left its previous Z100
reference, Z stayed held and Y was correctly left unverified (`xz` homed axes).
A fresh ordinary XY home then restored `xyz` without changing Z. This observes
the last yielding XY portion before the Z stage, rather than claiming a Stop
could be delivered in the non-yielding instruction gap between XY and Z.

Reviewing the retained vendor mesh helper found a missing final-point boundary:
after the last lift it calls `_invoke_callback()` before ever returning through
the existing `_move_next()` Stop hook. Two retained-helper regressions reproduced
that both print Stop and calibration Stop allowed finalization after the last
sample. The fix also guards `_invoke_callback()` before publishing a mesh.
Normal completion, closed print regions, other actors and external owners retain
the original callback. The initial Stop-point run passed 145 tests; the current
mesh-specific batch, including the additional missing-finalizer case, passed
31 tests. The matched helper SHA-256 is
`3be99dc4d24a4f267bf023679b51a76f75313eea9c25a392af6d4f4fc57d4359`.
It was installed with zero configuration changes; a new Klipper PID and the
on-printer helper hash were verified before motion. The native screen artifact
is unchanged. The complete final-source run passed **6,774 tests with no skips**,
three existing warnings, in 455.27 seconds.

The real 49-point G29 acceptance **passed**. Stop was requested during point 49
(index 48), acknowledged in 0.039 s, and consumed at `before bed mesh finalization`
after the last probe/lift. Cleanup finished in 14.080 s with the head docked,
targets zero and Z held. No mesh checkpoint was saved; the active mesh, all
profiles, loaded/pending configuration and exact original printer.cfg hash
were unchanged.

The last-point test also exposed a post-cancellation metadata defect: the legacy
`gcode_macro G29.bed_leveling` flag stays true because the interrupted macro's
final reset does not execute. This flag is not a tuning value or a saved mesh.
The physical cancellation and publication checks passed. The follow-up below
subsequently closes the legacy progress-marker and native terminal UI defect.

Follow-up verified: an owned G29 unwind now clears only its runtime
`bed_leveling` marker, using the macro's copy-on-write variable semantics.
Cancellation and genuine probe-fault regressions first failed on the stale
marker, then passed after the fix. Unbound, replaced, inactive and external
owners, other commands and macros without that variable remain untouched.
The cancellation/ingress/checkpoint batch passed 81 tests. This does not emit
a successful-calibration message or write tuning. The matched-package full suite passed **6,784 tests**, with no skips and three
existing warnings, in 514.82 seconds. The installed calibration helper hash is
`9fe06ef499841bce468e9d32f07b0de17c563aafb41481e29517087fadfd23db`.

The actual Maintenance Bed Leveling flow passed: after real probing began,
three native Cancel presses produced one owned cancellation between mesh
points. Cleanup completed in 16.121 seconds, docked the head, set all heater
targets to zero and held Z. The runtime marker was false; active mesh, profiles,
loaded and pending configuration were unchanged. No checkpoint was published.
The actual terminal screen displayed “Calibration cancelled. All heads are
docked.” and a single **DONE** action, with the title in the header. Evidence:
`native-mesh-marker-before.json`, `native-mesh-marker-active.json`,
`native-mesh-marker-after.json`, `native-mesh-marker-cancelled-done.jpg` and
`/tmp/wmp-mesh-marker-full-suite.log`.

## Scope audit after active checks

The original twelve-family matrix remains the acceptance scope. The checks
above are evidence for specific boundaries, not blanket completion of a family.

| Family | Remaining acceptance evidence |
| --- | --- |
| Home | Parameter-specific combinations and dialog reconnect/coexistence; the non-yielding XY-to-Z instruction gap is not claimed as a physical interrupt. |
| Standalone mount/dock | Actual unlock, retreat and attachment checks passed; the full parameter/paused-operation combinations are not all exercised. |
| Filament service | Heat-wait and queued Stop passed; actual feed/purge cancellation is unverified and would involve extrusion. |
| Probe editor | Preparation Stop and captured-helper ABORT passed; paper adjustment and ACCEPT/save were not performed. |
| Guided scrub/offset | Preparation and first hot brushing-prompt Cancel passed. Actual brushing, later setter/re-check/reheat require the operator; no brushing was falsely acknowledged. |
| Bed mesh | Heat wait, between points, final-point publication guard and native repeated Cancel/DONE passed. Normal completion after the new guard subsequently passed through a real 49-point START_PRINT mesh; full native Maintenance final save/restart remains unqualified. |
| Vibration | Active segment and live calculation-child Stop passed; later axes are correctly prevented. |
| PID | Heater/control-loop cancellation and completed first-head checkpoint retention passed. |
| Identification/repair | Queued Stop and real identification pickup/retreat/wipe Stop passed; active explicit repair and immediate pre-publication boundaries remain unqualified. |
| PLR Continue | Real interrupted-print journal and physical acceptance remain open; no journal was fabricated. Awaiting authorization for the controlled real-print interruption. |
| Ordinary Resume | Actual nozzle heat wait and post-wipe/pre-return Stop passed; stock-screen preheat and bed wait remain unverified. A fresh cold normal Resume after Stop subsequently passed as described below. |
| Multi-type calibration | Completed PID survives next-type vibration Stop. Final normal save/restart and full setup-guide acceptance remain open. |

The screen result must also identify the physical Stop boundary. The native
panel regression reproduced its missing location; a display-only correction is
verified below. Unknown internal labels are omitted instead of being
presented as physical evidence. No new motion command or endpoint is added.

## Confirmed Stop location and fresh Resume follow-up

The native calibration result regression first failed because the confirmed
cancellation text omitted its physical boundary. The correction translates known
backend boundaries into concise physical sentences, only for a fresh matching
attempt with completed cleanup. Unknown internal labels are omitted. A foreign
request cannot supply a location. The real native panel and existing warning
checks passed three tests; the final matched-package suite passed **6,784 tests**,
no skips, three existing warnings, in 519.62 seconds. Screen artifact SHA-256:
`81053b99e426cbf991cfb201a572f5cca194c64f5d8ab993a70e7a9e68a85f99`.

The actual Maintenance Bed Leveling Cancel was consumed `during temperature
wait`. Cleanup completed in 12.788 seconds, docked the head, turned off all owned
heater targets and kept Z held. The active mesh, profiles, loaded and pending
configuration remained unchanged, and the legacy progress marker was false.
The actual framebuffer displays “Calibration cancelled. All heads are docked.”,
“Stopped while heating.” and a single **DONE** header action. Evidence:
`native-cancel-location-before.json`, `native-cancel-location-active.json`,
`native-cancel-location-after.json`, `native-cancel-location-done.jpg` and
`/tmp/wmp-cancel-location-full-suite.log`.

A separate fresh cold SD job also resumed normally after cancellation of its
first paused run, without restarting Klipper or changing session. `RESUME E=0`
returned to the job and its continuation marker ran exactly once. Filament use
and heater targets were zero, and configuration was unchanged. The initial
observer incorrectly required Z holding after **normal completion**: stock
`PRINT_END` disables motors. That failed observation is retained, and acceptance
was corrected from the same run's terminal state and G-code records without
replay. This does not claim held Z after normal completion or change PRINT_END.
Real bottom/XY homing subsequently restored references and holding. Evidence:
`normal-resume-after-stop-failed-observation.json`, the initial/corrected harnesses
and the `normal_resume_after_previous_stop` record in `results.jsonl`.

## Resume bed wait and genuine START_PRINT follow-up

The real paused job's captured bed temperature was 54.03°C. The bed was allowed
to cool, then `RESUME E=0` entered its real temperature wait at 51.52°C toward
54.03°C. Reviewed Stop completed every cleanup stage, with no XY return or SD
tail, zero extrusion, all heater targets zero and Z held. Loaded/pending
configuration was unchanged. The original observer expected the generic
`heating bed` label, while this owned Resume wait correctly records
`resume_boundary` / `during temperature wait`. That assertion was corrected
against the same saved active and terminal records without replay. Evidence:
`resume-bed-paused-before.json`, `resume-bed-active.json`,
`resume-bed-after-stop.json`, original/corrected harnesses and
`/tmp/wmp-resume-bed-stop.log`.

A genuine START_PRINT file was then tested with `BED=55 EXTRUDER=0 INITIAL_TOOL=0`
and no extrusion instructions in its body. Configured minimum extrusion
temperatures were verified above probe preheat, so an unsuccessful Stop could
not authorize cold extrusion. This is not a printed-body/purge test.

The actual preparation overlay displayed probe preheat with native STOP/CLOSE.
STOP completed heater shutdown and held Z, and the file tail did not run.
However, this is retained as a **failed acceptance case**: the receipt was still
version 2 with no stop-point location, and the SD job ended as `XY homing
interrupted`. Y homing had been admitted by the time Stop arrived; its stroke
drained and X never started. The new cancellation increments command generation,
and XY's stale-generation check ran before the matching print Stop observer.
Normal subsequent XY homing restored the correctly unverified Y reference.

A regression now reproduces that missing ordinary-cancellation boundary while
retaining rejection for replaced file handles/files/SD or stats objects,
sessions/material owners, later generations, wrong fences, genuine faults,
quick Stop, non-SD calls and external managers. The narrowly scoped correction
records the completed axis for only the exact current print's ordinary Stop
fence; it never admits another move across the fence. Matched installation and
real retry remain pending. Evidence: `real-start-stop-before.json`,
`real-start-stop-active.json`, `real-start-stop-visible.jpg`,
`real-start-stop-after-observation.json`, `/tmp/wmp-real-start-stop.log` and
`/tmp/wmp-xy-print-stop-fence-red.log` (1 failed, 8 passed before the fix).

The matched correction subsequently **passed** real qualification. Installed XY
helper SHA-256:
`72d395623aa7b4fbc25982b2ff92fa8f0240c259ea7f41284fa0d4e0237b8f2f`,
Klipper PID 1548577, with the unchanged native screen artifact
`81053b99e426cbf991cfb201a572f5cca194c64f5d8ab993a70e7a9e68a85f99`.
The installer preserved all configuration (zero file changes), and original
hardware sections, geometry and exact printer.cfg hash were reverified.

On the genuine START_PRINT retry, the native STOP was pressed during observed
XY homing. Its version-3 receipt recorded `xy_homing` / `after Y homing`; the
SD job ended **cancelled**, not error. The actual screen shows “Print cancelled.
Stopped at: after Y homing” and DONE. The admitted Y stroke finished; X, mesh,
purge and the file tail did not start. All heater targets were zero, extrusion
was zero, Z remained held, and loaded/pending configuration was unchanged.
Normal XY homing then restored the unverified Y reference before normal docking.
The initial failed case above remains retained and is not overwritten.

The final focused batch passed 203 checks. The complete final-source,
matched-package suite passed **6,799 tests**, no skips, three existing warnings,
in 537.15 seconds. Evidence: `real-start-stop-retry-before.json`,
`real-start-stop-retry-preheat.json`, `real-start-stop-retry-homing.json`,
`real-start-stop-retry-after.json`, `real-start-stop-retry-preparing.jpg`,
`real-start-stop-retry-done.jpg`, `/tmp/wmp-real-start-stop-retry.log`,
`/tmp/wmp-xy-print-stop-fence-final-focused.log` and
`/tmp/wmp-xy-print-stop-fence-full-suite.log`.

## Genuine START_PRINT mesh Stop

The next non-extruding file invoked the real START_PRINT with bed 55°C,
print-nozzle target zero and physical Head 1. The actual settings had fresh
meshing enabled. All four existing profiles (`default`, `adaptive_mesh`,
`default_cold`, `wmp_print`) and the active mesh state were preserved;
the check compares the complete before/after bed_mesh status, not only a mesh
name. The configured minimum extrusion temperatures exceed probe preheat, so
this run cannot authorize cold extrusion if Stop fails.

After actual mesh probing began, the observer pressed the same native STOP
button. The admitted first point and lift finished. Its version-3 receipt
reported `mesh_probing`, “bed mesh, 1 of 49 points measured”; the SD job ended
cancelled. No point started after the Stop boundary, no partial mesh/profile or
configuration was published, and mesh-save/purge/file-tail stages never ran.
Cleanup completed in 10.770 seconds, all heater targets were zero, extrusion was
zero and Z stayed held. The actual terminal screen displays the same physical
location and a single DONE action. Normal docking and physical bottom homing
followed; no firmware restart was needed.

Evidence: `real-start-mesh-stop-before.json`,
`real-start-mesh-stop-active.json`, `real-start-mesh-stop-after.json`,
`real-start-mesh-stop-preparing.jpg`, `real-start-mesh-stop-done.jpg`,
`harnesses/wmp-real-start-mesh-stop.py`, `/tmp/wmp-real-start-mesh-stop.log`
and the corresponding receipts in `results.jsonl`. No production source changed;
the 6,799-test final-source suite remains the matching code/package result.

## Genuine START_PRINT bed and final nozzle heater waits

Native STOP during the real startup bed wait passed. The observed bed was
55.15°C toward 60°C; the version-3 receipt recorded `heating_heater_bed` /
“heating bed”. Cleanup completed in 17.225 seconds. Mesh, purge and file tail
never started. The job ended cancelled, all targets were zero, extrusion was
zero, Z stayed held, and the complete configuration/profile snapshot matched
its baseline. The actual terminal screen shows the physical location and DONE.
Evidence: `real-start-bed-stop-before.json`, `real-start-bed-stop-active.json`,
`real-start-bed-stop-after.json`, `real-start-bed-stop-done.jpg`,
`harnesses/wmp-real-start-bed-stop.py` and `/tmp/wmp-real-start-bed-stop.log`.

The next real startup completed all 49 mesh points normally before native STOP
was pressed in its final print-nozzle temperature wait. Its 160°C target was
below the verified 170°C configured extrusion minimum; the observer captured
139.76°C immediately before the click. The pre-established observer connection
read real status and pressed the existing control; it did not inject G-code,
temperatures, procedure flags or journals. The version-3 receipt records
`heating_extruder` / “heating Head 1”. The job ended cancelled at X0/Y70, before
the purge approach, with zero extrusion and no file tail. Heaters were off and
Z stayed held. The actual terminal screen displays the same location and DONE.

This is also positive live evidence for normal mesh finalization after the Stop
hooks: the completed private `wmp_print` profile has 7×7 points and was persisted
before the nozzle wait. All other profiles, all other autosave sections, the
20 protected hardware sections and saved head geometry remained unchanged.
The initial observer incorrectly expected an active mesh after cancellation;
normal cancellation explicitly calls `BED_MESH_CLEAR`. That failed observation
is retained. Acceptance was corrected from the same run's complete saved profile,
on-disk autosave parser and terminal receipt, without replaying the test. It is
not a full Maintenance calibration/save or setup-guide acceptance.

The test-derived private profile changed printer.cfg to
`a04444956a439cf2f9c9e7ceb0e74e252d6bd48c0acbe291d91181c10e7f0001`.
After normal docking, physical bottom homing and endstop confirmation, the exact
original configuration was restored under an unchanged-file hash/metadata guard.
Only then was Klipper restarted. All four original profiles matched again;
20 hardware sections and saved geometry had no differences, pending settings
were clear, and exact original SHA-256 was restored:
`e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97`.
The single new test backup `printer-mesh-hz6onno0.cfg` was removed only after
verifying its exact content against the original already preserved off printer.
Pre-existing backups were untouched. Real bottom/XY homing subsequently restored
XYZ and holding, with all heads docked and targets zero.

Evidence: `real-start-nozzle-stop-before.json`,
`real-start-nozzle-stop-late-mesh.json`, `real-start-nozzle-stop-active.json`,
`real-start-nozzle-stop-after.json`, `real-start-nozzle-stop-done.jpg`, the
initial/corrected observer and restore harnesses, `/tmp/wmp-real-start-nozzle-stop.log`,
`/tmp/wmp-restore-after-nozzle-stop.log` and correlated `results.jsonl` records.
No production source changed. The matching 6,799-test suite remains current,
and `tools/reseal_screen_package.py --check` passed after these live checks.


### Normal backend calibration save and restart

A genuine full 49-point G29 completed and checkpointed its default mesh. The
same bound attempt then parked the tool and issued SAVE_CONFIG once, after
normal bottom homing and endstop confirmation. Klipper restarted and reported
that exact request confirmed; the new mesh loaded and pending settings cleared.
The 20 protected hardware sections and other profiles remained unchanged.
This qualifies the backend save/restart path, not the complete native Maintenance
or setup-guide presentation.

Cleanup restored the exact pre-test printer.cfg and prior save-receipt bytes,
including ownership and mode. All four original profiles and tuning match.
An initial cleanup observer refused before writing because it expected a flat
receipt; the corrected observer validated the real checksum envelope. Both
observations are retained. Only the uniquely identified new timestamped backup
was removed after matching its preserved checkpoint. Pre-existing backups were
untouched. Final read-only verification found Ready/idle, all heads docked,
all heater targets zero, XYZ referenced, Z held and no pending configuration.

Evidence: normal-calibration-save-before.json, checkpoint.json and checkpoint.cfg,
normal-calibration-save-after-restart.json, persisted.cfg,
normal-calibration-save-original-restored.json and correlated results.jsonl
under analysis/backlog-qualification-20261122. No production code changed;
the existing 6,799-test result remains applicable. Full native final-save UI,
setup guide and operator-dependent cases remain open.


### Late identification check exposed consumed completion flag

The attempted final-dock Stop did not reach its target boundary. A genuine
identification run failed after its first Head 1 pickup with “Pickup of Head 1
was not confirmed”. Readback showed Hall 4621, lock asserted, only dock 0 empty,
material attachment h0, fail_flag zero and identification mode cleared. No
mapping publication started; static configuration hashes remained unchanged.
The head was subsequently docked through the normal verified toolhead action.
This is retained as a failed qualification, not a passed final-dock Stop.

The source reads _WMP_TOOL_RETURN_BEGIN.success after _CHANGE_TOOL returns,
but _WMP_TOOL_RETURN_FINISH intentionally consumes that flag. The candidate fix
adds a distinct completed_success result, reset at each BEGIN and copied only
at the normal checked FINISH before consuming success. Identification reads
that completed result; missing result remains a refusal. Seven of eight new
regression cases failed before the fix. Installation and a live repeat remain
required; the preceding 6,799-test result does not qualify this new change.

Evidence: identification-final-dock-before.json,
identification-final-dock-refused.json, /tmp/wmp-identification-final-dock.log,
and results.jsonl entries identification_final_dock_not_reached and
identification_refusal_normal_dock_cleanup.

The corrected completion contract passed 669 focused macro, observation,
identification-session and configuration regressions (330.59 s). Matching ARM
build completed; screen binary SHA-256 remains 81053b99e426cbf991cfb201a572f5cca194c64f5d8ab993a70e7a9e68a85f99.
The runtime source package was regenerated and its binding check passed.
The full suite, installation and live final-dock repeat are still pending.

The first full run ended with 6,784 passed, 10 failures and 13 errors (487.71 s).
All failures/errors traced to the recovery effect contract still pinning the
old BEGIN/FINISH macro bodies. Its refusal was valid. Only those two reviewed
hashes were updated: stripping the new completed_success assignments reproduces
the prior canonical bodies exactly. Added checks retain rejection of changed
BEGIN/FINISH motion and preserve that bookkeeping-only proof. Recovery-envelope
and active-recipe regressions then passed (62 tests, 1.16 s). The first matched
installation completed, registered completed_success=0 and restarted Klipper
(PID 1577334); the printer remains Ready/idle/cool with all heads docked. A
source-bound package including the corrected recovery identities, final full
suite and live repeat are still required. No identification mapping was saved.


### Final-dock repeat: physical Stop passes; transient cleanup gap remains

Final matched installation verified actual loaded macro contract
1f00d4810e76b2cf595db52a93cd2a636a366fa79b4e33e9bdb659318829e083,
helper hashes and new Klipper PID 1581784. All 20 hardware sections and saved
tuning remained unchanged. Real bottom/XY homing restored XYZ and held Z300.
The final full suite passed: 6,811 tests, three existing warnings, 478.73 s.

The real repeat scanned all four heads, then accepted Stop during final docking
at X230.375/Y339.98125. Receipt: “after verified tool docking”. Unlock and
mandatory back-off finished at Y310; all heads were docked, Z held, targets zero,
identification mode cleared and publication_started=false. Configuration hashes
and loaded/pending configuration were unchanged. Acknowledgement took 0.092 s;
physical completion took 8.578 s. The initial refusal evidence remains separate.

Final inspection nevertheless found saved changing_tool=1: cancellation skipped
PARK_CURRENT_TOOL's trailing reset. Factory exclude_object.py reads this flag to
bypass exclusion during tool changes. Therefore the physical boundary passed,
but complete transient cleanup is NOT accepted yet. The flag has not been
silently reset and the result must not be treated as full-family acceptance.
The install-only verifier also incorrectly expected completed_success=0 after
an actual successful scan; a retained 1 is intentional until the next BEGIN.
That observer assumption is separate from the real changing_tool cleanup gap.

Evidence: identification-final-dock-repeat-before.json and -after.json,
/tmp/wmp-identification-final-dock-repeat.log,
/tmp/wmp-identification-completion-contract-full-suite.log and correlated
results.jsonl. The pending work is an owned, drained transient-reset fix and
another live repeat, followed by the previously recorded operator-dependent cases.


### Owned transient-reset candidate (not yet installed)

A shared finish_cancelled_toolchange cleanup now covers identification,
standalone toolhead/filament service, calibration/Home cleanup, probe-editor
preparation, managed print cancellation and cancelled PLR preparation. It is
called only by the unwound command owner. It drains admitted motion, rechecks
ownership, faults and physically consistent Hall/lock/dock sensors, then clears
only changing_tool and confirms integer-zero readback. Identification uses
physical sensors rather than its unpublished UUID mapping. No extra coupling,
position override, heater command or driver disable is introduced.

The reset is inert when the transient flag is absent/zero. Its first broad
integration exposed nine filament fixture regressions from unnecessary readiness
checks in that no-marker case; the check order was corrected. All 13 exact
filament cancellation regressions then passed. A separate late-fault test failed
before final saved-state revalidation and passed after adding it: a newly
reported coupling fault cannot be hidden during sensor readback.

Final focused owner/probe/recovery batch: 333 passed (3.01 s). Four explicit
caller tests passed for toolhead, print, filament and calibration reset order;
the new probe preparation reset test also passed. The current matching ARM/source
package build is running. Packaging, final full suite, installation and the live
four-head final-dock repeat with changing_tool==0 remain required. The installed
printer still has the previously observed flag; it has not been manually hidden.

Matching ARM build and delivery export subsequently completed; source binding
check passed. Full-suite run and matched installer transaction started. Physical
bottom endstop, Ready/idle, empty carriage and zero heater targets were checked
before activation. These running checks are not yet a live acceptance result.


### Shared transient cleanup: three live owners pass; SD coupling fence fails

Candidate 5d785c3 was installed as a matched package and all nine helper hashes
and loaded macro contract verified under new Klipper PID 1590538. The final full
suite passed: 6,837 tests, three existing warnings, 462.39 s. Real bottom/XY
homing restored XYZ; all 20 protected hardware sections and tuning matched.

Actual identification scanned all four heads and stopped after final verified
docking/back-off, clearing both identification mode and changing_tool. Actual
standalone dock and pickup cancellations also cleared changing_tool; subsequent
sensor-only reconciliation added no movement. Real G29 preparation from mounted
Head 3 stopped after docking, before target pickup/Z probing/mesh; its cleanup
reports toolchange=cleared and all saved profiles/settings were unchanged.

A distinct actual cold SD `_CHANGE_TOOL` test FAILED. The print generation fence
unwound before unlock/back-off, leaving the locked head pressed at its exact dock.
The transient helper correctly refused ambiguous attachment. The file closed,
heaters were zero, Z stayed held and the tail did not execute. This invalidates
blanket acceptance of SD coupling Stop despite the passing host suite and other
owners. Required follow-up and exact evidence are in
`docs/superpowers/specs/2026-11-23-print-coupling-stop-handoff.md`.

The printer was subsequently recovered with a fresh generation-guarded native
support/unlock/back-off/release sequence, then a fresh reviewed no-motion cleanup
acknowledgement. All heads are docked, changing_tool=0 and Z remained held. The
failed Stop evidence remains failed and is retained separately from recovery.
An initial correction observer refused before any command because it expected
an empty path rather than the actual null closed-file path; this was corrected.


### Admitted coupling region: cold SD dock/pickup and calibration Stop pass

The invocation-bound coupling region is implemented and installed as a matched
ARM/source package (screen SHA256
7023ea0a12ee854c909a965ab114c59692d3940ee878513f05f02c9146edaeda).
Klipper PID 1609487 loaded the verified helper hashes and actual macro contract
95e9c7d16f1de898414b3cc431401c065118c8017efebdde8803a9a3fc4a68b3.
All 20 protected hardware/tuning sections matched; pending configuration was clear.

The full suite reported 6,882 passed and one outdated macro-tail assertion
(three existing warnings, 461.28 s). That assertion expected pickup's sensor
check to be the final command; it now explicitly requires the following owned
END boundary for standalone operation and no BEGIN/END for openACE/AFC. The
corrected assertion plus all coupling integration tests passed: 35 in 2.96 s.
Production sources were unchanged after the full run. Delivery/installer tests
also passed: 362. Retained vendor-dispatcher tests execute actual nested dock
macro templates for Stop during approach, stroke and retreat.

Real cold SD dock Stop: WMP_COUPLING_REGION_DOCK_ae76e3fa753f.gcode,
request legacy_cancel_c2ae9a8a8e84456a853ec31bf8b46b80. Stop at
X168.36875/Y340.40625 finished native unlock and retreat to Y310 before unwind.
All cancellation stages completed; acknowledgement 0.164 s, completion 7.032 s.
Carriage empty, current_extruder=99, changing_tool=0, no fault, heaters zero,
Z held, configuration unchanged and no tail marker. This is a new passed repeat;
the earlier failed trace remains retained as failed.

Real cold SD pickup Stop: WMP_COUPLING_REGION_PICKUP_67002e44efaa.gcode,
request legacy_cancel_540f675a9c3941c1ad26867d733d14de. Stop at
X44.375/Y340.8 finished locking and retreat to Y270, adopted verified Head 1
and its frame without travel, then unwound before wiping/file tail. All stages
completed; acknowledgement 0.134 s, completion 6.972 s. Head 1 attached,
active extruder and saved current_extruder=0 agree, changing_tool=0, no fault,
heaters zero, Z held and configuration unchanged.

Real calibration-owned G29 dock preparation: request
7c37e4d8563f4ec4ae60cf042a208ae8, ticket 2. Stop after verified docking completed
cleanup with park=already_docked and toolchange=cleared, before target pickup,
Z probing or mesh. X168.36875/Y340.40625 retreated to Y310; acknowledgement
0.078 s, completion 5.844 s. All saved profiles/configuration were unchanged,
carriage empty, changing_tool=0, heaters zero and Z held.

Evidence is in coupling-region-*-before/after.json, archived unique harnesses
and correlated results.jsonl under the primary qualification directory. Logs:
/tmp/wmp-coupling-region-full-suite.log,
/tmp/wmp-coupling-region-print-dock-stop.log,
/tmp/wmp-coupling-region-print-pickup-stop.log,
/tmp/wmp-coupling-region-calibration-dock-stop.log and
/tmp/wmp-coupling-region-final-safe-state.log.

The SD coupling defect is qualified by these actual repeats. This does not close
the entire twelve-family matrix: actual filament feed/purge, manual brushing and
setter/re-check, genuine interrupted-print PLR, and the remaining native final
Save/setup-guide cases still require their separately recorded checks. No
extrusion, brushing acknowledgement or synthetic recovery journal was used here.


### Native Maintenance mesh completion, save/restart and DONE

On installed a66499e, a real touchscreen Maintenance run selected only Bed
Leveling and pressed its actual START. Request 70812c8af5bcfe74387123903c07a99f,
session 45618b30683542a080a33c8c05bdd5dc, ticket 3 completed all 49 mesh points.
Its CANCEL remained in the header during probing. The native worker issued its
own final SAVE_CONFIG; after restart the backend confirmed that exact request,
the newly measured default mesh loaded, and pending settings cleared. All 20
protected hardware sections and all other mesh profiles were unchanged.

This test included a separate safety batch queued under the retained dispatcher's
FIFO G-code mutex during probing: generation guard, heater shutdown, normal
PARK_CURRENT_TOOL, real bottom-Z homing, M400 and QUERY_ENDSTOPS. It finished
after G29's checkpoint and before the worker's subsequent SAVE_CONFIG could
execute. The executed response marker and fresh readback proved an empty
carriage at Z300, bottom endstop=1 and heaters zero before restart. This qualifies
the actual native save/restart presentation with that explicit safety batch;
it does not claim that the unmodified stock worker performs those safety moves.
No extrusion, offset calibration or synthetic journal was involved.

The first observer mistakenly matched the queued command text rather than the
executed M118 response, and refused while the mesh was still probing. Its log
is retained. A corrected read-only observer attached to the same live request
and accepted only the exact response marker. No calibration or motion command
was replayed. It captured the actual completed checkpoint and physical bottom
before the same native save/restart. The original command handle subsequently
retired; the authoritative operation/receipt, not that failed observer, proves
the calibration result.

The real screen was captured during save showing:
“Saving calibration settings... Restarting Klipper...”, then after confirmed
restart showing “Restarting Klipper... Done. Calibration settings saved.” with
DONE in the header. The result was dismissed through that native control.
This closes the previously unqualified normal Maintenance final-save UI case;
it does not qualify the separate setup-guide workflow.

Cleanup re-established the real bottom reference and restored exact original
printer.cfg and prior calibration-save receipt bytes, ownership and mode under
unchanged-file checks. Original hashes:
printer.cfg e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97;
receipt 830bab598bfcd14ff156893bec053f09f3294a0f17dc140f08c4c363f9fc9bb4.
After the controlled restart, all four original profiles and tuning matched and
pending settings cleared. The one test-created printer-20261123_124752.cfg was
archived off printer and removed only after verifying its exact test-checkpoint
hash. Every pre-existing backup was left untouched. Real bottom/XY homing then
restored XYZ and Z holding; all heads docked and heaters zero.

Evidence under analysis/backlog-qualification-20261122: native-maintenance-save-*
baseline/probing/checkpoint/bottom/after-restart/restored JSON and config files;
selection, progress, restarting and done JPGs; archived original/corrected/restore
harnesses and results.jsonl. Logs: /tmp/wmp-native-maintenance-save.log,
/tmp/wmp-native-maintenance-save-corrected-observer.log,
/tmp/wmp-restore-after-native-maintenance-save.log,
/tmp/wmp-native-maintenance-backup-cleanup.log and
/tmp/wmp-native-maintenance-save-final-state.log. No production source changed;
the installed package and existing host qualification remain applicable.


### Additional cold boundaries: wiping, paused service, X homing and native Resume

No production source changed in this qualification. The installed a66499e
candidate and sealed screen artifact remain current.

Standalone mount Stop during actual nozzle wiping passed: toolhead_1,
“after nozzle wiping”, 1.769 s through completion. The observer saw physical
live XY (-13,273.969), then the completed wipe held at (-13,275,300). Head 1
remained attached, heaters zero, changing_tool cleared, return pending/success/
completed_success all zero, and loaded/pending configuration unchanged.
Sensor-only WMP_RECOVER_TOOLHEAD reconciled without movement. A fresh normal
Dock subsequently completed, proving old Stop intent did not poison a new action.

A real cold paused SD job, WMP_PAUSED_DOCK_STOP_78f79db971ad.gcode, then stopped
a Head 1 dock at its verified back-off. toolhead_4 remained cancelled/held,
carriage empty at X44.375/Y310/Z102, unchanged paused homing origin and Z,
zero filament used and no file tail. Acknowledgement 0.079 s; completion 5.835 s.
The idle-only reconciliation endpoint refused while paused, with no movement.
The whole cold job was subsequently cancelled and reconciled normally.

That refusal was initially overinterpreted as blocking all paused repair.
Source review shows unknown historical results are not active standalone
operations; a fresh paused Take uses its own captured-file/frame admission.
A separate real job, WMP_PAUSED_DOCK_FRESH_TAKE_c6aedb866c88.gcode, verified it:
toolhead_6 stopped after docking (0.116 s acknowledgement, 5.475 s completion),
then fresh toolhead_7 mounted the original Head 1 and restored the paused frame.
The historical cancelled operation was not replayed or relabelled complete.
RESUME E=0 completed that same cold file, ran its tail exactly once and used
zero filament. Its tail lowered Z to the physical bottom before completion.
Configuration was unchanged. This verifies the existing supported lifecycle;
no reconciliation-admission patch was needed. It is not an extrusion test.

Normal completion later released motors through stock housekeeping. The final
dock itself completed, but a final observer's Z-enabled assertion failed. Fresh
readback found the head docked, no fault/transient, homed XY and Z disabled.
The real bottom switch was confirmed and native bottom homing restored XYZ/Z
holding. No M84, guessed position, coupling retry or cancellation success was
inferred from that observer failure. The cancellations themselves kept Z held.

A raw G28 X Y Stop during actual X homing also passed: request
2aa6ecef737c46f093d7cb8581eecaac, ticket 2, session
fe5b549f1b394ceca08481840ef1e99e. Its receipt says “after X homing”, with
complete held cleanup, Z unchanged at 300, no pickup and no fixed-corner Y
reread after Stop. Acknowledgement 0.065 s; completion 7.413 s. The native
homing motion report uses its internal homing coordinate frame; its reported
negative X is not a claim that the carriage physically exceeded the frame.
A fresh normal XY home then completed, keeping Z held and heaters off.

#### Real touchscreen Resume preheat prefix

The first zero-target cold fixture resumed directly and never entered preheat.
Its observer correctly refused to qualify that path when the job completed;
a cleanup observer also found no same-file cancel receipt because the job had
already completed. The trace is retained, not counted as preheat Stop success.
The stock resume_preheat(int) code at 0x51a344 shows the condition: with the
selected temperature <=174 C, its saved per-head temperature must exceed 174 C
or the prefix returns without sending heat commands. No file-metadata guess or
runtime flag was used to bypass that condition.

A new real cold job WMP_NATIVE_RESUME_WARM_TARGET_77a35e03574b.gcode briefly
set the actual Head 1 target to 175 immediately before PAUSE E=0 Z=0 turned
it off. The nozzle stayed cold; PAUSE genuinely captured 175. Pressing the
actual native RESUME control then issued the intercepted stock commands:
M104 T0 S175, SET_GCODE_VARIABLE MACRO=RESUME VARIABLE=resume_temperature0
VALUE=175, and M109 T0 S175. The same-job observer requested ordinary print
Stop while actual resume_progress.phase was preheating, at 37.01 C/175 C.

Receipt legacy_cancel_c6743bc19cf34217a6999261c7419304 completed every stage and
records resume_boundary / “during temperature wait”. Acknowledgement 0.134 s.
The recorded 23.696 s end-to-end interval includes the subsequent 40-sample
stability observation; it is not the physical-stop latency. There was no late
reheat, no file tail, no extrusion, no resumed motion and no session/configuration
change. Heaters zero, resume progress cleared, Z held. The native popup retired
back to the idle print-files screen; its actual screen capture is retained.
The agent did not send RESUME E=0 in place of this native preheat path.

Fresh normal docking afterwards left all heads docked at Y310/Z300, with the
real bottom switch tripped, XYZ referenced and Z held. All 52 installed material
helpers match the current source; manifest digest
63239b858237a980120575d626c4998e4e7044bfc6d564990a53d1f878f52a9a,
Klipper PID 1609487. Configuration/tuning remain unchanged.

Evidence under the primary analysis/backlog-qualification-20261122 directory:
standalone-after-wipe-stop-*, paused-dock-stop-*, paused-dock-fresh-take-*,
home-x-stop-*, native-resume-preheat-* (initial unqualified fixture),
native-resume-warm-target-*, all-material-helpers-after-cold-boundaries.json
and correlated results.jsonl. Unique harnesses and initial observer failures
are archived; existing harness hashes were verified before extending their
manifest. Logs: /tmp/wmp-standalone-after-wipe-stop.log,
/tmp/wmp-paused-dock-stop.log, /tmp/wmp-paused-dock-fresh-take.log,
/tmp/wmp-home-x-stop.log, /tmp/wmp-native-resume-preheat-stop-watch.log,
/tmp/wmp-native-resume-warm-target-stop-watch.log,
/tmp/wmp-resume-preheat-final-dock.log and
/tmp/wmp-all-material-helper-hashes.log.

Remaining acceptance is still explicit: a real native multi-type selection
with a completed mesh followed by vibration Stop; explicit assignment-repair
cancellation needs the requested unmoved-head/correct-slot-settings confirmation;
actual filament feed/purge needs its separate approval; manual brush/setter/
re-check needs the operator; genuine PLR needs the requested real interruption;
and first-run guide qualification needs its genuine setup flow. No confirmation,
brushing, first-run flags, physical journal or completed calibration was fabricated.

## Native multi-type mesh then vibration cancellation — 2026-11-23

Selected Bed Leveling and Vibration Compensation on the actual Maintenance UI.
Request 200c77868900ddfd398215ff8564964a (ticket 5) completed all 49 mesh
points before entering the real X vibration sweep. Native CANCEL stopped it
between vibration segments, before any Y sweep. Cleanup docked all heads,
cleared heater targets and held Z. The UI displayed Calibration cancelled,
Saved: bed mesh, and DONE. No API fallback or synthetic completion was used.

The initial observer failed with NameError before issuing Cancel. A corrected
observer attached to that same active request and pressed native CANCEL; no
calibration was replayed. Both observers and the original failure log are retained.
Touch transport took 4.625 s; intent was observed at 4.770 s and cleanup finished
at 14.899 s. These include SSH transport, not solely backend acknowledgement.

The mesh checkpoint remained saved with disk SHA256
e1be42b9aa7d9b1a4a8d147128dad7e235329d3ced154065d2b90f0a1708f785.
Vibration stayed unconfirmed and partial results were discarded. After actual
bottom homing, one controlled firmware restart loaded the new 7x7 mesh, proving
durability without SAVE_CONFIG. Original shaper settings and the prior receipt
were unchanged. The exact original printer.cfg was then restored under hash
and ownership guards, followed by a controlled restart from the physical bottom.
All four original mesh profiles, 20 protected hardware sections and tuning match.

Final checks: original printer.cfg SHA256
e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97;
prior receipt SHA256
830bab598bfcd14ff156893bec053f09f3294a0f17dc140f08c4c363f9fc9bb4.
No extra printer backup files remain. All 52 installed helpers match source,
manifest 63239b858237a980120575d626c4998e4e7044bfc6d564990a53d1f878f52a9a.
Final state: Ready/idle, empty carriage, all heater targets zero, XYZ referenced,
Z300 held. Production source and r4 were unchanged.

Evidence: native-multitype-* and all-material-helpers-after-native-multitype.json
in analysis/backlog-qualification-20261122; unique harnesses and failure logs
are archived with verified historical hashes. Remaining acceptance still includes
operator-dependent brushing/setter/re-check, actual filament feed/purge, genuine
PLR and first-run flow, plus assignment repair requiring the pending confirmation.

## Identification final dock with current coupling wrapper — 2026-11-23

Repeated the real cold identification final-dock Stop on the current a66499e
production source, closing the earlier result's pre-wrapper version gap. Request
901a2e3975904e92b1087215fcb5c2d5, calibration session
33560bf5d49c4e4aa5806b26633110d5, scanned all four heads before Stop during
the final dock. Acknowledgement 0.091 s; verified docking/retreat and cleanup
completed in 8.612 s. Observed X230.375/Y339.98125/Z300 became
X230.375/Y310/Z300 with empty carriage. The admitted unlock and mandatory
back-off completed before the cancellation boundary.

The result is cancelled after verified tool docking, publication_started=false,
restart_required=false, mode_cleanup=cleared and toolchange_cleanup=cleared.
No mapping publication, extrusion or restart occurred. All heater targets remain
zero, Z is held, changing_tool and is_nozzle_setting are zero. Static config
hashes, loaded/pending configuration and per-head offsets/positions are unchanged.
This used ordinary identification, not assignment repair; no pending user
confirmation was fabricated. Evidence: identification-coupling-region-final-dock-*
and correlated results.jsonl, with the unique harness and log archived and hashed.

All remaining live cases require additional user participation or authorization:
actual filament feed/purge; manual brush/setter/re-check; genuine interrupted-print
recovery; genuine first-run setup; and assignment repair with explicit confirmation
of unmoved heads and correct slot settings. These remain unqualified.

## Actual Head 3 filament feed Stop — 2026-11-23

With the user present and the plate clear, Head 3 was actually unloaded before
this load test. Normal WMP_FILAMENT_SERVICE HEAD=2 ACTION=load admitted
filament_2 in session 07f16caa06a0422f8ef737b547f4eec0. At the real purge
position X-13/Y80/Z300 it heated to 220 C and waited for operator insertion.
The observer requested cancellation during actual feeding: live E velocity
6.6667 mm/s. Acknowledgement took 0.085 s. The admitted 55 mm G-code feed
finished, then the purging checkpoint consumed Stop before purge/wipe dispatch.
This qualifies cancellation between instructions, not interruption of an E move.

The terminal result is failed/cancelled with inspect-filament guidance, rather
than a falsely completed load. Head 3 remains attached, all heater targets zero,
Z held and configuration unchanged. Twelve post-stop samples confirmed no
continued E motion. The recorded 15.104 s includes polling and the subsequent
stability observation; it is not an instantaneous motion-stop latency. Later
readback confirmed Ready/idle, cooling nozzle and stopped motion. No restart,
synthetic loaded confirmation, purge or wipe was sent by the observer.

Evidence: live-filament-feed-stop-before.json, -trace.json, -after.json and
results.jsonl in the primary qualification directory; harness/log archived with
verified historical hashes. This closes actual load-feed cancellation; purge
and unload/tip-shaping boundaries remain distinct acceptance cases.

## Actual Head 3 purge-boundary Stop — 2026-11-23

Fresh normal load retry filament_3, same material session, was accepted with
filament still present but the prior load unconfirmed. No loaded flag or sensor
was fabricated. Normal heating/feed completed; the observer requested Stop in
phase purging. Acknowledgement 0.082 s. The sampled live velocity was zero at
the purge's dispatch boundary, so this is not evidence of observing the motor
mid-purge. The admitted 50 mm purge subsequently drained (live E approximately
0 to 50), then the wiping checkpoint consumed cancellation before wipe travel.

Result failed/cancelled with inspect-filament guidance; Head 3 attached at
X-13/Y80/Z300, all heater targets zero, Z held, configuration unchanged. Twelve
post-stop samples confirmed no continued extrusion. The 14.646 s completion
measurement includes polling/stability samples. No restart or manual confirmation
was used. This proves admitted purge drain and next-boundary Stop, not mid-move
interruption. Evidence live-filament-purge-stop-{before,trace,after}.json and
results.jsonl; unique harness/log archived with historical hashes verified.

Unload/tip-shaping, operator brush/setter/re-check, genuine PLR/first-run and
confirmed assignment repair remain separate unqualified acceptance cases.

## Actual unload/tip-shaping cancellation — 2026-11-23

A legitimate normal load filament_4 completed first, including purge/wipe and
loaded confirmation. No readiness flags were fabricated to admit unload. Fresh
unload filament_5 then heated Head 3 to its normal unload temperature and entered
_TIP_SHAPE_MOVES CLASS=pla. Stop was requested while actual E motion was
6.6667 mm/s; acknowledgement 0.108 s. The entire tip-shaping macro drained
before cancellation at the finishing checkpoint. Net physical withdrawal was
110 mm. Receipt failed/cancelled, inspect-filament guidance, heaters zero,
Head 3 attached, Z held, configuration unchanged and 12 stable E samples.

The recorded 35.115 s includes stability observation; physical sequence drain
was approximately 32 s. This proves cleanup after the admitted tip-shaping
sequence, NOT fast cancellation between its internal E instructions. The macro
has no internal Stop checkpoints. That responsiveness limitation remains open
for review; do not report this as mid-sequence/fast-stop acceptance.

Evidence: live-filament-unload-stop-{completed-load,before,trace,after,final-readback}.json,
results.jsonl and archived unique harness/log with verified historical hashes.

## Operator brush and real setter measurement Stop — 2026-11-23

User completed the real guided manual-brush prompts and reported measurement
in progress. Actual offset request f63b995f237a3e89bb807a9b50abb23a, ticket 2,
session 33560bf5d49c4e4aa5806b26633110d5 completed Head 1 RAPID_MODE.
Six real centre readings had span 0.010938 mm, no flagged disagreement. Native
CANCEL stopped after the following verified docking/back-off, before Head 2
measurements. measured=[0], no later head measurements and no save/restart.

Initial observer had the stock-panel Cancel coordinate [717,130]; the inspected
scrub overlay actually uses [617,20]. A same-request observer pressed the correct
native button. Initial verifier then rejected valid park=already_docked because
it expected parked. Both original failures/corrections are retained. Fresh readback
verified cleanup complete, offsets restored, park already_docked, toolchange cleared;
all original per-head offsets/positions and loaded/pending configuration match.
All heads docked, targets zero, Z held, Ready/idle. No replay or API failsafe.
The real terminal screen says Calibration cancelled, All heads are docked,
Previous nozzle offsets were restored, Stopped after verified docking, and DONE.

This qualifies actual manual brushing plus setter measurement cancellation and
restoration. It does not qualify the disagreement re-check/reheat path: no real
reading was flagged, and none was fabricated. Evidence operator-brush-* JSON/JPG,
results.jsonl, and archived unique observers/logs with verified historical hashes.

## Accepted tip-shaping Stop policy — 2026-11-23

After reviewing the measured unload delay, the user explicitly chose to let tip
shaping finish unchanged before honoring Stop. The approximately 32-second drain
is accepted sequence-level behavior; no internal tip-shaping checkpoint change
is planned. The completed live unload test qualifies that requested policy and
cleanup, without claiming mid-sequence interruption.

## Genuine PLR print, software interruption not qualified — 2026-11-23

User authorized a real small print and interruption test. Head 1 red PLA printed
two layers from WMP_PLR_REAL_f6151afcd89e.gcode (SHA256
12697fc80faf7f07ab735cbe1763dd388569d3e7faae245ed28624f7ac3940b0).
Normal START_PRINT and a 3x3 mesh ran. Actual native PLR A/B sidecars bound
to committed job sd_c79cfbb85efb4f6a9867706593d78974, fingerprint
efa4c933a6c55996; backend execution v4 was completed at a real command boundary
with 37.5 mm filament used. Deposition envelope came from real moves. No recovery
journal, loaded flag, interrupted-offer flag or calibration result was fabricated.

The bottom wait G1 Z300 was mesh-compensated to machine Z299.521562. Observer
correctly refused its exact-bottom assumption. PAUSE E=0 Z=0 preserved the job;
stock Pause retained bed heat, so TURN_OFF_HEATERS was sent explicitly. The
normal bottom-home helper refused paused state without motion. With a valid XYZ
reference and zero offsets, clearing mesh then ordinary G1 Z300 F120 moved only
the remaining referenced distance. The physical bottom switch still read open.
No forced coordinates, limit extension or extra downward travel was used. User
visually confirmed approximately 1–2 mm above the bottom.

The firmware-restart guard refused the paused print and explicitly prescribed
M112 followed by a separate FIRMWARE_RESTART for deliberate interruption. Used
that supported path only to create the test interruption, NOT as a passing ordinary
Stop. Klipper returned Ready in session 7884a03d5d6245bf87bcd190eb9a8ae8,
Head 1 attached, heaters zero, no recovery restore error. However, after this
simulation both native A/B checkpoints were reset and plr.ini was not interrupted.
The backend record remained committed/completed, so native/backend binding review
correctly failed. The precise writer of the reset has not been attributed here.
No recovery preparation ran; this is NOT a PLR Stop qualification. Archived
records were not restored to manufacture an accepted selection.

Real power interruption is required for a further attempt; operator availability
requested. Original tuning/configuration bytes and initial recovery evidence are
preserved off printer. Test mesh and temporary T0→Head 1 mapping still require
restoration after the test sequence. Unique harnesses, initial upload error,
observer assumption failures and all genuine before/after records are retained
in the primary qualification evidence directory.

## Genuine power-loss recovery: pre-start and nested-Y Stop — 2026-11-23

User cleared the plate, then WMP_PLR_POWER_8d79e52f34b5.gcode printed two
real layers with Head 1 red PLA. File SHA256
033bc3737b3b9c777b847e02c63e442ba61e30ca5cc449cb73e0b61fba374cb7.
Normal startup/3x3 mesh ran; admitted print used 37.5 mm including startup purge.
It then waited at G-code Z300 / machine Z299.51875. Actual native checkpoints
and sidecars matched committed job sd_e5ba2629a8294b02b3810d069a6bf8c8,
fingerprint 2d57f4c2b08ba914, and a completed backend execution checkpoint.
The user cut mains power only after the stationary near-bottom/checkpoint cue,
then booted again. No software shutdown, synthetic journal or archived-record
restoration was used for this successful selection.

Post-power-loss review accepted native plr_dataB.ini fingerprint
5703e7fbbf03ed4b, job fingerprint above, execution fa63bff2e06ee226 and
deposition SHA256 3020918f727d219910eeb3eabbbdafcbfd75eea1f2b29b8ae6ad50185b253cdd.
The completed execution position was file byte 1541, Head 1, G-code Z300.

First server-issued ticket (sequence suffix 753) was stopped before preparation
and then dispatched normally. Acknowledgement 0.0386 s. Result cancelled with
before_execution=true: no motion/heat, no new attempt journal, unchanged loaded
configuration and byte-identical original recovery records.

Fresh reviewed ticket (suffix 754) then ran actual recovery context and bottom-Z
homing. Out-of-band Stop during home_xy took effect after the completed Y stroke,
before X. Every subsequent stage stayed pending: machine-frame restoration, head
selection, mesh/heat/fans, purge/prime/wipe, return, parser/file/accounting and
continuation. Heaters remained zero, E did not move, Z300 remained held and no SD
continuation ran. Original native/job/execution/envelope records were unchanged.

The initial observer expected state=stopped and rejected the actual unknown state.
Source and existing test_recovery_nested_xy_stop_does_not_continue_into_the_next_axis
explicitly require unknown for a partially completed combined XY stage with
cleanup=complete, preserving the no-replay rule. Fresh readback verified that
exact contract and error Recovery preparation stopped after Y homing. No source
fix or replay was needed. The corrected scope is successful physical boundary
and cleanup, not a claim that XY completed. No active-Stop acknowledgement time
was retained outside the initial observer; none is inferred here. The initial
verification helper contained a tautological optional config comparison; it is
not used as configuration-preservation evidence. Full restored-settings comparison
below is independent. Executed/corrected observer sources and failure log retained.

Supported reviewed WMP_RECOVERY_RESOLVE action=abandon archived the exact stopped
test evidence and retired its continuation authority. Normal physical bottom and
XY references were re-established; Head 1 docked normally, physical Z switch=1.
Mapping was restored from the authoritative pre-first-print snapshot (T0→Head 1,
not an assumed earlier mapping). The exact original printer.cfg was atomically
restored preserving UID1001/GID111/mode0644; save receipt was never rewritten.
A controlled normal restart from verified physical bottom loaded all original
settings exactly, all four original mesh profiles, matching offsets/positions/
mapping and no pending config. Original file SHA256
e690a9f4b8663762381b09e6b2e8020114dd7fcb73d9a7599d4d713218d82a97;
receipt SHA256 830bab598bfcd14ff156893bec053f09f3294a0f17dc140f08c4c363f9fc9bb4.

Final real references: XYZ, Z300 held, empty carriage/all heads docked, heaters
zero, Ready/idle. All 52 installed helpers match source manifest
63239b858237a980120575d626c4998e4e7044bfc6d564990a53d1f878f52a9a.
Klipper PID1329, material session 757ad79db99b427d92fcc38dfab32d98.
Evidence plr-power-*, plr-real initial originals, all-material-helpers-after-genuine-plr.json
and results.jsonl in the primary qualification directory. Unique harnesses/logs
archived after verifying all historical hashes. No production source or r4 change.

These are real pre-start and nested-Y PLR acceptance cases, not qualification of
every later recovery preparation stage or successful print continuation. Remaining
original scope includes those later boundaries, genuine first-run/assignment-repair
confirmation and a real disagreement-triggered brush re-check/reheat.

## Consolidation following user scope clarification — 2026-11-23

The user explicitly requested validation by distinct changed code, ownership and
cleanup rather than repeated full hardware runs from every entry. The current
acceptance plan is [early-stop-consolidated-plan-2026-11-23.md](early-stop-consolidated-plan-2026-11-23.md).
The physical gaps above remain historically accurate; they are not new claimed
hardware passes. Guide and assignment-repair adapters are covered by verified
client/native-runtime and both-mode transaction tests, reusing the live shared
worker/identification evidence. Distinct brush re-check and later PLR stage code
is exercised directly in production-class host fixtures, combined with the
existing physical cleanup/boundary evidence. The focused suites passed 246 and
450 tests respectively. No new printer motion, heat, extrusion, restart, setup
marker, repair confirmation or recovery checkpoint was created for consolidation.
Original tuning remains restored and the final read-only query confirms idle,
heads docked, heater targets zero and Z held.
