# Consolidated early-Stop validation

This is the current validation plan, following the user's request to consolidate
repeated start-path checks. It supersedes the exhaustive hardware-repeat list in
`2026-11-19-operation-cancel-ownership-audit.md`; that document and
`early-stop-live-2026-11-22.md` retain the original requirements and evidence.
Historical live gaps are not retroactively described as physically tested.

## What constitutes a distinct check

Validate each changed ingress for correct request/session/ticket binding and
delivery. Validate each distinct execution owner, cancellation consumer, physical
boundary and cleanup implementation. A different page or start button does not
require another full hardware run when it reaches the same admitted worker with
the same ownership and cleanup.

Use three complementary evidence levels:

1. Actual verified client instructions and native-runtime tests for entry hooks,
   button actions, command retirement and UI lifetime/terminal behavior.
2. Production backend/flow tests for each distinct cancellation branch, ownership
   change, refused cleanup, pending-result publication and no-replay rule.
3. Representative existing live evidence for physical motion, sensor/attachment
   outcomes, heater cleanup and tuning preservation. Keep separate live cases
   where the physical implementation or owner actually differs.

Host fault injection is labelled host evidence. It is not a fabricated printer
checkpoint, first-run state, brush confirmation or sensor disagreement. A live
repeat is required when a changed hardware command/cleanup implementation lacks
representative evidence, or a specific physical uncertainty remains after host
checks. Do not repeat factory printing/calibration accuracy checks to qualify
unchanged cancellation plumbing.

## Implementation and evidence map

| Changed behavior | Existing representative live evidence | Additional branch/entry evidence and disposition |
| --- | --- | --- |
| Queued request retirement and out-of-band intent | Queued operation Stops; genuine PLR ticket stopped before dispatch, with unchanged journal and no motion/heat | Per-owner wrong/stale/duplicate/replaced ticket tests remain separate because ownership differs. No repeated print per UI alias. |
| Shared native homing boundary dispatcher | Raw Home after X/Y; calibration and genuine PLR after Y; no next axis and held Z | Nested dispatcher tests check actor/generation isolation and that expected cancellation does not trigger the vendor motor-off exception path. Different callers retain their own owner tests, not a full physical Home per caller. |
| Admitted dock/pickup region and mandatory back-off | Current coupling wrapper tested under ordinary SD print, standalone tool service, calibration cleanup and identification final docking | `test_coupling_regions.py` and rendered macro tests cover original-owner continuation, generation changes, foreign actors/managers and fault precedence. These physical owner differences were deliberately retained. |
| Filament heat/feed/purge/unload cleanup | Actual load heat, 55 mm feed, 50 mm purge and unload/tip-shaping Stops; subsequent extrusion absent and heater targets zero | User explicitly accepts finishing the complete tip-shaping sequence before Stop. No internal tip-shaping checkpoint change or further speed qualification is required. |
| Manual probe helper ownership | Real preparation cancellation and captured-helper ABORT | Probe-editor tests distinguish the owned helper from unrelated helpers. Paper-adjustment accuracy and a complete accepted calibration are not Stop gates. |
| Calibration worker, cancellation cleanup and per-type checkpoints | Actual mesh heat/point/final-point Stops, vibration sweep/calculation child Stop, PID Stop, native multi-type mesh→vibration cancellation, save/restart/DONE and restored tuning | Mesh probing, vibration child management and PID control restoration are distinct implementations; their live evidence is retained. Another complete run from each starting screen is unnecessary. |
| Ordinary Resume and native preheat prefix | Actual stock-screen Resume preheat Stop, API temperature waits, wipe/return Stop, fresh cold Resume | Native prefix versus backend Resume are distinct and were both exercised. Unchanged full print completion is not another Stop gate. |
| Identification versus assignment-repair entry/publication | Normal identification cancellation through current physical coupling wrapper, no partial UUID publication, owned flags cleared | Both modes use the same `IdentificationSession` and cancellation path; transaction construction/publication differs. Parameterized host tests must exercise queued Stop, post-pickup Stop, pre-publication Stop and atomic-publication protection in **both** modes. Keep explicit repair confirmation validation. No live repair or UUID reassignment is needed to test the shared physical cancellation again. |
| First-run guide entry | Maintenance worker already physically qualified; no genuine first-run run claimed | Frozen-client tests verify the guide hook and 16 retired sender sites. Native runtime exercises all 15 nonempty selection masks through the shared worker, real Cancel callback binding, late-command suppression and blocked Finish while cleanup is unresolved. No factory reset or synthetic first-run marker is warranted for this adapter check. |
| Brush re-check/reheat orchestration | Operator brushed nozzles; actual setter measurement cancelled; original offsets restored, heads docked, heaters off and DONE shown | A real disagreement did not occur. Host flow/runtime tests exercise flagged re-check, repeat heating/scrub/remeasure, Cancel→restore→end ordering, withheld park/save and restore failure. Reuse the physically verified scrub/end and offset-restore implementations. Do not manufacture a hardware disagreement or require another full measurement run merely to reach this branch. |
| PLR later stages and continuation fencing | Genuine power-loss checkpoint survived; pre-start Stop and fresh nested-Y Stop passed; no later stage or SD continuation | PLR uses its own temperature wait, purge/wipe and return functions, so these need their own backend tests, not an assumption of equivalence with Resume. Verify heater ownership/cleanup, one admitted E chunk only, no following wipe segment/vertical return/file continuation, stale-owner guards and unchanged original evidence. A successful full recovered print is broader product testing, not required for this early-Stop change. |

Source locations supporting the two adapter equivalences:

- `Runtime::begin_guide_calibration` in `native/runtime.hpp` copies the selection
  and navigates to the same admitted `auto_checking_page` worker. The native
  lifecycle test invokes `unified_guide_calibration_event`; frozen-client tests
  independently verify the corresponding actual client instructions.
- `IdentificationCommands::_run` in `wmp_identification.py` chooses
  `AssignmentRepairTransaction` or `ManagedMappingTransaction`, then uses the
  same owned command/drain/identification session. The transaction-specific
  cancellation/publication cases are tested in both modes.

## Autonomous checks for this consolidation

No new printer job, heating, extrusion, movement, restart, forced sensor state or
bed clearing is needed. Existing representative live records are reused, not
replayed. Run:

- Focused entry/orchestration suite: verified guide bridge, native LVGL lifecycle
  (including guide and scrub coordinator), scrub flow/backend commands,
  identification commands/session/dispatcher, recovery dispatcher and coupling
  ownership. Four existing identification cancellation tests are expanded across
  both transaction modes; no production code is changed.
- Production material recovery tests: real coordinator/motion/worker classes
  with deterministic machine fixtures, including late temperature/prime/wipe/
  return cancellation and cleanup failures. This covers distinct late PLR code
  without obtaining another physical power-loss checkpoint for each stage.
- Package seal, evidence hashes and read-only printer state checks. Test-only
  changes do not require a new installed binary or printer restart.

Record exact results and any failures below. Add a test or fix only for a real
coverage gap/failure; do not rerun the full repository suite or repeat hardware
qualification solely because this plan changed.

## Scope of the conclusion

Completion means the consolidated plan is backed by the targeted automated
results and existing representative physical evidence, and all independent work
that needs no bed clearing/operator participation has been completed. It does
not mean every possible factory workflow or every entry has been physically
replayed. Optional genuine first-run presentation, naturally triggered re-check
and full recovered-print quality checks stay explicitly distinguished from the
early-Stop acceptance criteria.

No push or merge is part of this work.

## Results

Completed against the current production source and unchanged installed package:

| Run | Result | What it establishes |
| --- | --- | --- |
| Entry/orchestration selection | **246 passed**, 78.17 s | Actual-client guide instructions; native guide Cancel and re-check lifecycle; scrub backend commands; both identification transaction modes; dispatcher/coupling owner boundaries. |
| `klipper_extras/test_wm_material.py -k recovery` | **450 passed**, 75.46 s | Distinct PLR wait, purge, wipe, return and continuation fencing; request/session/actor ownership; cleanup failures and no replay. |
| Focused scrub-flow rerun after adding repeat-heating case | **1 passed**, 7.21 s | Cancel in the repeat's Heating state discards the next head's queued preheat, restores once and ends, with duplicate Cancel idempotent. |
| `python3 tools/reseal_screen_package.py --check` | **Screen package is current** | Test-only changes have not invalidated the installed source/package contract. No reseal/rebuild/restart required. |
| Read-only printer query | **Ready/idle, empty carriage, heater targets zero, Z300 held** | No calibration active; test recovery remains abandoned. No new printer operation was performed. |
| Evidence hash manifest and `git diff --check` | **Passed** | Historical qualification evidence remains unchanged; current logs and test snapshot retained. |

The four expanded identification tests run in both `identify` and
`repair_assignment` modes. They prove cancellation before queued execution,
after pickup, before publication and refusal once atomic publication has begun.
They use the real mode-selection and transaction classes in temporary fixtures;
they do not provide a repair confirmation or rewrite UUIDs on the real printer.
All original mode/confirmation rejection and transaction rollback tests also pass.

The added C++ repeat-heating case initially expected a redundant attention-off
command, although Clean again had already released it. That assertion was
corrected to require restore/end only; the initial failure log is retained.
Production code did not change. The focused rerun covers the final added case;
the larger suites were not needlessly repeated after a test-only assertion edit.

The guide test executes all 15 nonempty selection masks through the native event
bridge and shared worker. Separate Unicorn tests execute the frozen client's
selection instructions and verify the actual guide-hook prologue and retired
sender calls. This is adapter qualification, not a claim that this printer was
reset into first-run setup.

The scrub tests explicitly enter Re-check in host fixtures, cancel during repeat
heating/scrub/measurement, verify restore/end command ordering and exercise a
failed restore without claiming success. The production scrub/end and original
offset restoration have separate actual hardware evidence. No real disagreement
was induced, and no additional manual brushing is a gate for this code change.

The PLR selection includes
`test_recovery_stop_during_heating_cleans_heaters_without_purge`,
`test_recovery_failure_cleans_heaters_without_resolving_outcome`,
`test_recovery_prime_failure_is_not_repeated`,
`test_recovery_wipe_failure_retains_prime_and_stops` and
`test_recovery_return_failure_prevents_continuation`. These instantiate the
production recovery lifecycle/motion classes and check the resulting command
stream, heater state and durable receipt. They close the distinct late-stage
code paths without another power cycle or deposition on the occupied bed.

Exact run commands, logs, source snapshot, result counts and final readback are
retained under the primary `analysis/backlog-qualification-20261122` evidence
directory with the `consolidated-validation` prefix and verified hash manifest.
The two suites used cached offline Python 3.11 dependencies, pytest-xdist with
four workers and `--dist loadscope`; there were no failed or skipped tests.

**Disposition:** consolidated early-Stop validation is complete using the
explicit evidence levels above. No additional bed-clearing or operator-dependent
test is required for these changes. Genuine first-run appearance, naturally
triggered nozzle disagreement and full recovered-print quality remain optional
broader hardware checks, not unperformed tests represented as passes. Reopen
targeted hardware qualification if its physical command/cleanup implementation
changes or a real discrepancy is reported.
