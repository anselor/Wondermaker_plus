# R4 refinement release validation — 24 November 2026

## Candidate

Prepared as one squashed update on `release/r4-refinements-20261124`, based on
published `fw-1.1.13/r4` at `ab18e32`. The source is the reviewed final tree of
`work/r4-finish-camera-ui` (`2acfef3`); squashing changes history, not the tested
product files. The release gate adds one eligibility guard: an optional
accounting hook without the stock command multiplexer now declines installation
instead of blocking Ready. Three new cases cover missing/None/foreign dispatcher
shapes. A navigation test now recognizes and validates the intentional guarded
Home tail continuation. The supported stock path and ARM binary are unchanged.
Release notes, policy and this record are the additional documentation.
This is a moving-branch update, not a release tag. The user deferred tagging
until more feedback arrives and limited subsequent R4 work to critical fixes;
non-critical fixes and enhancements go to R5.

Native ARM artifact SHA256:
`d9733d77382442eb43dd563eee544e40dd8c225101545c87511106b2f0be2e8c`.
The sealed binary and its source/runtime manifests are preserved exactly.
The live printer runs functional commit `02c84d0`; later development commits
only record acceptance. The installer verified that artifact, native GUI/status
synchronization and Klipper Ready (screen PID 367478).

## Reviewed changes and evidence

- Configurable physical bed target/minimum drop, bounded finish/cancel parking,
  native Home takeover, About and calibration-light policy:
  [finish/UI validation](r4-finish-camera-ui-2026-11-24.md) and
  [release identity validation](about-release-identity-2026-11-24.md).
- Cosmetic appearance selection and full-boundary checkerboard clipping:
  [appearance acceptance](filament-appearance-2026-11-24.md) and
  [clipping validation](translucent-clipping-2026-11-24.md).
- Major progress phases, actual homing detail, native Stop and exact factory-font
  fit: [progress audit and attended checks](r4-progress-phase-audit-2026-11-24.md).
- Correct retained-stock E-frame accounting with exact combined two-head total:
  [counter regression and live acceptance](filament-tool-frame-accounting-2026-11-24.md).

The short unmodified Vehicles test used Head 3 black and Head 1 red on the first
layer. At activation, outgoing E336.48309 changed to incoming E0 while cumulative
usage stayed at 336.48309. The final total 365.16270 equalled that total plus incoming E28.67961.
Cancellation completed; all heater targets were zero; Head 1 was parked beside
the scrubber at physical Z125. Configuration settings, saved tuning and filament
identities compared unchanged. No live G-code instrumentation was injected.

Private live evidence is in `analysis/progress-final-live-20261124/`.

## Regression gate

The first full run passed 7,012 cases and failed five in 587.75 seconds:
four reduced-dispatcher Ready lifecycle cases and one navigation-binding source
check. The guard/test corrections above passed all 15 targeted cases. This is
not presented as an error-free initial run.

The final full run on the assembled candidate completed with **6,971 passed,
49 skipped, no failures**, and three existing empty-exception-match warnings in
546.72 seconds. It used Python 3.11, four xdist workers (`--dist loadscope`),
Jinja2, Unicorn, Capstone, pyelftools, Paramiko and Tornado 6.3.3.

The isolated worktree initially had only the retained 1.1.13 fixture, so tests
requiring optional 1.1.04/1.1.08/1.1.12 payloads skipped. After supplying those
same read-only retained fixtures, all dependent compatibility modules completed
with **820 passed, no skips or failures** in 305.81 seconds. Their additional
shared-client delivery/restart consumers passed **29 cases, no skips or failures**
in 23.29 seconds. These runs overlap the full suite; counts are not summed as
unique tests. No product code changed between the final run and fixture follow-ups.

Independent candidate release gates passed **74 cases without skips**; config
validation covered **26 files**. The final package freshness and staged-diff
checks pass. Compared with the qualified development source, only the narrowly
scoped optional-dispatcher guard, its tests, the navigation assertion and release
metadata/documentation differ. The native binary remains byte-identical.

Logs: `/tmp/wmp-r4-refinement-release-final-suite.log`,
`/tmp/wmp-r4-refinement-legacy-compatibility.log`,
`/tmp/wmp-r4-refinement-legacy-delivery.log`, and
`/tmp/wmp-r4-refinement-candidate-full-gates.log`.

## Limits

The counter correction does not establish a fix for intermittent physical
extrusion timing, Z symptoms, print stutter/CPU spikes or USB-hub drops.
Visible file preparation took about 92 seconds for the 60,414,444-byte Vehicles
input. That is a measured cost, not proof of a performance improvement.
Physical PETG unload, naturally triggered gauge disagreement/re-check,
first-run setup and affected third-party permission migration remain separately
scoped acceptance. R5 enhancements stay deferred.

No printer reinstall or motion run is needed merely because the tested source
is consolidated into a release commit. The approved moving-branch update is pushed only after its release gates pass;
no release tag is created.
