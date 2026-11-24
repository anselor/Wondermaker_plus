# Verification tracker reconciliation

The dashboard still listed 24 verification items after the umbrella cooperative
Cancel qualification was completed. Its child statuses and top-level banner had
not been reconciled with the later physical evidence and consolidated plan.
This correction does not run new tests or change release/push status.

## Covered items moved to completed

The authoritative records are
[the consolidated plan](early-stop-consolidated-plan-2026-11-23.md) and
[the chronological live evidence](early-stop-live-2026-11-22.md). They distinguish
actual physical tests from host-only adapter/branch qualification.

| Item | Evidence closing its remaining verification |
| --- | --- |
| SAFE-CANCEL-OPERATION-INGRESS | Owned operation ingress and queued Stops; representative physical workers plus per-owner host binding/cleanup tests. |
| HOMING-CANCEL-BOUNDARIES | Real raw/native X/Y boundaries and held Z; nested dispatcher, actor/generation and no-motor-off tests. |
| CALIBRATION-CANCEL-CONTROLS | Actual native mesh/PID/vibration and brushed-offset Cancel/DONE; native guide adapter uses the same admitted worker. |
| OFFSET-CANCEL-BOUNDARIES | Actual brushed setter measurement followed by native Cancel, completed mandatory docking and exact original offset restoration; re-check orchestration tested on host. |
| CALIBRATION-CANCEL-OTHER-STAGES | Actual mesh, vibration/fitting-child and PID Stops; normal native mesh save/restart and final DONE. |
| TOOL-SERVICE-CANCEL-BOUNDARIES | Actual dock/pickup/back-off, wipe, paused service and fresh Take/Resume; current coupling wrapper exercised under distinct owners. |
| SETUP-RETRY-FLOW-REVIEW | Verified actual-client hook/senders and native guide selection, Cancel, late-command suppression, handoff and unresolved-cleanup Finish gates. No factory reset or physical first-run run claimed. |
| CAL-RETRY-RESULT | Current-attempt/error/retry native tests; physically distinct cancelled attempts followed by normal native completion/save, with original tuning restored. Shared guide adapter verified separately. |
| CALIBRATION-PARTIAL-SAVE | Actual native mesh→vibration cancellation, durable saved mesh after restart, partial vibration discarded; completed PID retained across next-type cancellation. |
| PROBE-PREP-CANCEL-BOUNDARIES | Actual preparation Stop and bound manual-helper ABORT; native UI/owner/helper host tests. Paper-adjustment accuracy remains outside Stop qualification. |
| IDENTIFICATION-CANCEL-OWNERSHIP | Current-wrapper actual final-dock Stop with no publication; both identification/repair modes tested before execution, after pickup, before publication and inside atomic publication. |
| PLR-CANCEL-BOUNDARIES | Genuine mains-loss record accepted; Stop after native Y and no later preparation/continuation; distinct later PLR stage code covered by 450 recovery host cases. |
| PLR-EARLY-CANCEL-INGRESS | Genuine reviewed ticket cancelled before preparation, then dispatched: no motion/heat/new journal, original records unchanged; native ingress races tested on host. |
| RESUME-HEAT-CANCEL | Actual native-screen preheat and bed/nozzle waits, wipe/return boundary and fresh cold Resume. |
| RECOVERY-MACRO-EFFECTS-CONTRACT | Actual generated job/context uses current macro contract `95e9c7d…`; genuine post-power-loss file/native/backend review accepted without fallback or migrated proof. Strict-change rejection retains host regression evidence. |
| EARLY-STOP-DISPATCH-ERRORS | Actual identification and genuine recovery expected Stop unwinds remain Ready, preserve Z holding and complete owned cleanup; retained dispatcher fault/owner isolation tests pass. |

These sixteen are not additional unfinished hardware runs. The original scope
is preserved through implementation/ownership evidence, not by claiming every
start path was physically replayed.

## Five independent items still needing verification

- **LARGE-GCODE-STARTUP-SCAN:** real large-file startup timing/responsiveness.
- **INSTALL-RECOVERY-PERMISSIONS:** upgrade on an affected legacy-permission installation.
- **OFFSET-GAUGE-REPEATABILITY:** bounded false-trigger behavior and repeatability;
  clean real touches alone do not prove every gauge issue repaired.
- **UI-SCREEN-HEADER-AUDIT:** broader device/artwork/translation presentation checks;
  these extend beyond the Stop headers already exercised.
- **PREHOME-DOCK-CLEARANCE:** the exact conditional pre-home empty-carriage
  clearance branch; normal startup and generic coupling retreat are not identical
  evidence for that branch.

## Three investigations, not ready-to-verify fixes

- **PA-Z-MOTION-TRACE:** the captured run did not explain the reported physical drop.
- **EXTRUSION-TIMING-INTERMITTENT:** cause of the intermittent symptom remains unproven.
- **PRINT-STUTTER-CPU:** responsible callback/process and CPU-versus-I/O attribution remain unproven.

Move those three from `verify` to `todo` rather than implying a completed fix
awaits acceptance. Existing diagnostics and uncertainty remain intact. The
dashboard's stale overnight-access and pending-Cancel banners are also replaced.
No unrelated task is completed, and nothing is installed, pushed or merged.
