# Backlog candidate: local completion review

Scope: `work/r4-print-time-fixes`. This review covers local implementation and
offline evidence, not an installation, a release, or physical qualification.
The user deferred printer debugging until morning. Do not install, restart,
home, move, heat, probe, or push as part of this review.

## Requirements and evidence

| Requirement | Current implementation and local proof | Still requires the printer |
| --- | --- | --- |
| Put screen titles beside header actions; avoid duplicate body titles | Production widget constructors and retained factory constructors are audited in `docs/ui-audit/screen-headers.md`. The 116 named scenarios in `tests/fixtures/screen_header_scenarios.json` are checked by `test_screen_headers_with_factory_fonts`; retained geometry is checked by `tests/test_retained_screen_headers.py`. Dynamic headings reserve action width, including STOP/CLOSE in print preparation. | Device screenshots, artwork/occlusion, and touch interaction. |
| Make print-preparation Stop available | `stock_print_preparation.hpp` uses the existing independent print-cancel worker; lifecycle and transport tests cover its request/receipt behavior. | Stop during actual homing, mesh and heating. |
| Repair legacy recovery-sidecar access without broad filesystem changes | `tools/preload_bundle.py` validates exact A/B marker names through no-follow directory descriptors before permission changes. `tools/components/preload.py` stops the screen before repair and backend restart. `tests/test_recovery_marker_permissions.py` and `tests/test_preload_bundle.py` cover contents/inode/ownership preservation, rejection, publication and recovery order. | Upgrade on an affected installation; the reported directory ownership issue remains unproven. |
| Reduce large-G-code startup bookkeeping and permit reactor progress | `ToolUsage` in `wmp_recovery_file_envelope.py` validates common short moves without coordinate parsing; unusual syntax retains the full parser. `_ScanCooperator` in `wmp_plr_jobs.py` bounds chunks and yields by byte/time budget. Differential parser and `test_startup_scan_schedule.py` tests cover syntax and revalidation. `docs/performance/startup-scan.md` distinguishes synthetic timings from printer evidence. | Large-file startup duration and UI responsiveness on device. |
| Cancel outside the G-code queue at safe operation boundaries | Independent endpoints latch owner-bound intent. `wmp_stop_points.py` observes it between operations; native Home unwinds outside factory motor-off handling. Maintenance/setup guide, Home/raw G28, filament, tool service, probe preparation, identification, PLR and ordinary Resume owners are enumerated in the operation audit. | The 12-family attended acceptance matrix in `2026-11-19-operation-cancel-ownership-audit.md`. |
| Keep coupling strokes and required retreats atomic | Shared dock/mount macros check around complete strokes; service cleanup holds/drains only while its request, frame and attachment authority remain valid. Macro, service and ownership tests exercise Stop and actor replacement. | Real sensor settling, hold torque and physical outcomes. |
| Stop mesh/PID/vibration and offset probing safely | Mesh stops after admitted retract; retained PID restores its controller; both resonance executors and fitting-child cleanup are exercised. Offset samples finish/retract before the next boundary. See `test_stop_points.py`, `test_calibration_resonance_stop.py`, `test_wmp_tool_probe.py` and the cancellation handoff. | Hardware cancellation latency, controller restoration and no subsequent motion. |
| Retain each completed calibration type before starting another | `wmp_calibration_checkpoint.py` publishes scoped mesh/shaper/PID results atomically without restarting. It preserves unrelated tuning and foreign writes, rolls back incomplete type state, and reports unconfirmed publication honestly. `tests/test_calibration_checkpoints.py` exercises retained writers, late Stop, failures and ownership. Setup guide uses the same owner. | Multi-type failure/Stop/restart and saved-result comparison. |
| Deliver matching backend/configuration/native screen | `tests/test_screen_package_current.py` checks source binding, package freshness and the artifact; current ARM artifact is `8fa3692ed69dc1806444db6847213bb62687749706e054abfe15dab7594a90d3`. Backend-only follow-ups do not claim a new screen binary. | Authorized matching installation and attended qualification. |

## Combined regression disposition

The original serial run was not green: 6,349 passed, 104 failed, 55 skipped and
13 setup errors. The correction history remains in the operation audit; it
includes a real macro-effects fingerprint integration fix as well as restored
retained inputs and ownership-aware test fixtures.

The next combined run finished with 6,517 passed, one failed, nine skipped and
three warnings. Its only remaining failure occurred before the intended process
loss: the restart test double rejected the added `repair_markers` keyword.
Commit `73b6b68` accepts and asserts that argument, preserving the SystemExit and
recovery-order assertions. The complete preload-bundle module then passed all
43 tests. Package, journal and marker-permissions checks passed all 56 tests.
These focused passes do not retroactively turn that combined run green.

A final combined run on the current source, including the later pre-home
clearance fix, finished with **6,533 passed, 21 skipped, no failures and three
warnings** in 589.61 seconds. It used Python 3.11, pytest/xdist with four
module-scoped workers, Jinja2, Unicorn, Capstone and factory-pinned Tornado 6.3.3.
The complete delivery/configuration module separately passed 150 tests; all 26
Klipper configuration files validate.

The full run did not include the optional ELF parser. All five modules using
that parser subsequently passed **71 tests with no skips** under pyelftools,
against the exact packaged ARM artifact. The development command now includes
that dependency and prints skip reasons. Existing local vendor writer scripts,
checkpoint examples and the 1.1.04 binary were also restored into this isolated
worktree with SHA256 identity checks. The retained writer/Wi-Fi/checkpoint batch
passed **13 tests with no skips**. These are supplemental results, not a claim
that the full run itself had zero skips. The repair tracker retains the full
run, supplemental logs and input provenance.

Skip accounting was checked explicitly: under the original full-run environment
those five modules produce 52 passes and 19 skips, all naming the missing ELF
parser. With that parser they produce 71 passes and no skips. The other two
full-run skips were the retained A/B checkpoint examples, both covered by the
passing restored-input batch. Thus all 21 skipped cases have subsequent local
execution evidence; none is being relabelled as a pass within the full-run log.

An earlier current-head invocation omitted Jinja2 and binary-emulation
dependencies. It was explicitly interrupted and is not qualification evidence.

The earlier nine skips were two unavailable retained vendor checkpoint cases,
six optional retained firmware-source cases and one absent 1.1.04 Wi-Fi binary.
They are not hardware passes. The three existing warnings concern an empty
exception-message match in admission tests, not a claimed production failure.

## Separate unresolved printer investigations

Extrusion deposition misbehavior and Vehicles print pauses remain separate.
Neither local cancellation tests nor the startup scanner benchmark proves their
cause or repair. CPU contention is a hypothesis for the observed planner gaps.
Negative filament-used accounting was reproduced in retained stock code from
per-tool E-coordinate changes; it is telemetry evidence, not physical retraction.

The last reported belt skip invalidates confidence in physical XY position.
Head 3's dock-support guard refused to unlock, and Z-driver overtemperature
warnings were logged. These are morning printer investigations, not reasons to
run unattended recovery or change timing/driver settings in this candidate.
