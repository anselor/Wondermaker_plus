# Status polling latency

The vendor Klipper status query helper generates all subscribed objects on its
250 ms timer. Timing a tiny HTTP query therefore does not isolate the requested
object's generation cost. Idle HTTP requests around 200–300 ms include this
scheduling delay; response size alone was not the main cost found here.

Target measurements on 2026-11-14 found repeated material profile reads and
repeated observation of the same four heads while constructing eight procedures.
The profile helper was called approximately twenty times per publication.

| Warm idle measurement, 200 samples | Before median / p95 | After median / p95 |
| --- | --- | --- |
| Material status CPU | 76.24 / 94.17 ms | 47.47 / 59.55 ms |
| Full subscribed query CPU | 91.87 / 110.91 ms | 63.72 / 78.19 ms |
| Material status wall time | 76.65 / 99.43 ms | 47.66 / 60.75 ms |
| Full subscribed query wall time | 93.00 / 114.77 ms | 63.59 / 79.56 ms |

The same temporary timing instrumentation was used for both samples. No movement
or heating was performed. The exact original helper was restored afterward.
These idle measurements establish reduced reactor work, not proof that every
historical timeout or homing failure had this cause. Hardware calibration with
the rebuilt release remains a separate verification step.

## Cache contract

Filament profiles are loaded on first use and retained for status publication.
Supported filament saves publish the new profile snapshot after the write
commits; failed writes invalidate it. Catalogue data is likewise retained until
an import save invalidates it. The read-only AFC metadata publisher uses this
same loaded-profile view. Explicit command admission still reads profiles and
checks their revision, including external edits that retain size and timestamps.
Such direct reloads also refresh the status snapshot. Polling alone is not a
profile reload operation.

Live attachment and filament presence observations expire after each synchronous
publication. Repeated callers receive isolated copies. The scope is restored in
`finally`, including exceptions and nested publications; no live sensor state is
retained across publications. Regression tests compare complete status output
and verify profile save visibility, explicit reloads, mutation isolation, and
exception cleanup.

## Native polling

A transient transport failure on an established status query immediately marks
status unavailable, but keeps the discovered object list for the next attempt.
This avoids an extra discovery round trip after connection errors, I/O errors,
or deadlines. Schema, session, and ownership failures still force discovery.
Successful recovery still validates the helper session and owner.

The GET deadline allows 1500 ms scheduling margin. The independent 2000 ms
freshness limit and fail-closed action checks remain unchanged. This margin is
not a substitute for reducing status generation work, and unavailable status
never reports a calibration as completed.

## Combined candidate validation

The final material suite passed 1,378 tests with two skips. The native UI suite
passed all 43 tests (the localhost transport test was rerun with socket access
after sandbox denial). Package binding/delivery/export checks passed 82 tests;
bottom-Z, config validation, and Moonraker installer checks passed 78 tests.
All 26 shipped Klipper configs validated. The rebuilt ARM artifact SHA256 is
`45212b578a71bb2226bf3264c2a7419370dd6d67807d77cea7ca3362c3637834`.
These checks establish software/package consistency, not physical calibration
completion or the cause of User2's abrupt Klipper process exits.

Release `253159d` was pushed to main and passed GitHub Actions run
`43637691838`. Local installation completed with journal
`ff9e07070916473696eade4c104a63c1` in state `applied`; the installer reported
zero configuration-file changes, preserved filament data, verified the running
native artifact and status synchronization on screen PID `813441`, and verified
Klipper Ready with the required material/recovery protocols. No physical
calibration was performed during this installation.

## Legacy adoption and deferred cyclic collection

A follow-up GC-disabled soak reproduced a separate memory mechanism. Vendor
Klipper disables automatic cyclic collection and collects during reactor idle
time. `ConfigParser` creates reference cycles. Before profile snapshots, a
missing WM+ profile JSON caused repeated legacy INI parsing during every status
publication, even before the existing parsed-profile cache was checked.

With a minimal legacy INI and cyclic collection deliberately disabled, 2,000
full publications plus periodic metadata projections retained 107.28 MB in the
original helper. Explicit collection reclaimed 817,245 objects, reducing traced
allocation to about 50 KB. This establishes collectable parser-cycle buildup
when collection cannot run; it does not establish that the affected printer had
that exact missing-file condition or why its reactor was unable to collect.

The initial snapshot optimization still directly parsed legacy INI in the
first-install presence-adoption branch when adoption could not finish. That
branch now reuses the loaded profile snapshot under the same file-absence and
idle guards. A repeated 2,000-publication GC-disabled soak retained 46 KB before
collection, with constant RSS; explicit collection reduced that to 16 KB.
Regression tests cover missing and valid colour metadata, asserting no new
parser instances during repeated status and metadata publications after warmup.
Command admission retains its fresh profile read and revision check.

The same experiment with four stock slots (`material0..3=0`, `color0..3=1`)
retained 273.27 MB and 56,781 `ConfigParser` objects after 2,000 publications in
the original helper. Explicit collection reclaimed 1,873,773 objects, leaving
75 KB traced. The corrected helper retained 54 KB before the diagnostic type
count, with no growth between publication 1,000 and 2,000. This was the production
material status/plan code using the repository's four-head service fixture,
missing profile JSON, full JSON status serialization and an AFC projection every
eight publications. The host was Linux x86-64, CPython 3.11.15, with `tracemalloc`
enabled and cyclic GC deliberately disabled. It was not a firmware/hardware
motion test; target Python and allocator behavior may differ. Explicitly
collecting after the run demonstrates retained collectable cycles rather than
permanently reachable status records.

A separate read-only `/proc` sample on our printer after installing `253159d`
covered 31 samples at ten-second intervals (04:33:09–04:38:12 CST on November 15).
Klippy RSS remained exactly 52,344 KiB, Moonraker 49,388 KiB and touchscreen
22,076 KiB throughout. This idle observation did not reproduce User2's growth;
it was collected before installing the final adoption-cache correction and
cannot substitute for verification of User2's missing-profile state.

User2 subsequently confirmed `wmp_filaments.json` was absent while
`wmp_filament_loaded.json` existed (48 bytes). That matches the repeated legacy
profile-read condition in the original helper. It does not exercise the later
both-files-absent adoption fallback: the profile snapshot in `253159d` addresses
their confirmed file combination. Whether deferred collection caused their
observed OOM still requires memory observations after the update.

Final material regression suite: **1,380 passed, 2 skipped** (169.90 seconds),
including the GC-disabled legacy status cases and existing command revision,
filament adoption and save behavior checks.

User2 supplied two post-update process readings with the same PID `18192` and
RSS `59268` KiB (57.9 MiB). Memory did not grow and the process did not restart
between those samples. Five minutes had been requested, but timestamps were
not supplied, so the exact observation duration is unverified. This supports
the memory correction without establishing long-term stability or successful
homing/calibration.

User2 subsequently confirms homing and docking/mounting work and Fluidd is much
more responsive after the memory fix. This adds successful physical-operation
and responsiveness evidence to the unchanged process readings. It does not
measure long-term uptime or prove absence of status warnings during calibration.

Final audit release `afec705` passed CI run `43639248862` and installed locally
with journal `8dbbb68a3ddd4af394bae510cd28e613` (exit 0), preserving configuration
and filament data. The installer verified Klipper Ready, backend protocols and
screen synchronization on PID `819120`; its later summary sampled stale status.
Subsequent read-only diagnostics showed recovery: status age 376 ms, polls
increased from 68 to 75 while failures stayed at 15, and the last failure was
46 seconds earlier. This confirms current availability, not uninterrupted
availability during calibration. Bed leveling followed by vibration compensation
still requires an observed run. Final cancellation-audit material validation
passed 1,396 tests with two skips; package checks passed 82 tests.

### Local maintenance qualification — 15 November

Rapid Alignment completed through the stock Maintenance menu on all four heads
with the added bottom-Z counter guard removed (`2d4682f`). The result screen
showed completion, saved variables contained the new offsets, and the final
head docked/unlocked. Evidence is in
`analysis/validation/2026-11-14-calibration-menus/` in the main checkout.
An initial retry still used the old imported helper: `FIRMWARE_RESTART` alone
did not reload Python modules. Restarting `klipper.service` loaded the removal;
the subsequent MCU reset restored Ready. Earlier tests after only an internal
restart must not be treated as qualification of newly staged Python code.

The screen still intermittently timed out during calibration tool changes:
active PID 819120 reported stage 2/kind 1 failures at 1502–1503 ms while backend
calibration remained active without a failure. These are request deadlines,
not evidence of calibration failure. The 37059 ms maximum gap includes the
service restart and is not an ongoing calibration latency measurement.

A candidate extends post-save reactor cooperation to active calibration,
which calls stock tool macros without a managed toolhead operation. It yields
only after a fully validated saved-variable load and retains the G-code mutex.
The correlation with tool changes is evidence for this candidate, not proof
that it eliminates every deadline; physical comparison remains required.
A separate native correction binds an existing calibration result page to its
original backend session, so a restart cannot expose a false completion tick.
Maintenance has no persisted success receipt for SAVE_CONFIG restarts, so those
results remain unconfirmed rather than being labeled failed or successful.

Candidate validation: material/saved-variable suites passed 1,400 tests with two
skips; native lifecycle harness passed; ARM build/export and all 82 package
checks passed. These are host/package results; on-printer comparison of the
calibration yield and restart-result overlay is still pending.

The subsequent screen-menu Vibration Compensation run also completed its
frequency sweeps, fitting, SAVE_CONFIG and automatic restart. Readback from
printer.cfg confirmed X `3hump_ei`/94.6 Hz and Y `mzv`/39.0 Hz; Klipper returned
to Ready with no calibration fault. This verifies the menu flow and persisted
result, not an independent assessment of print quality or the fitted model.

Current physical qualification queue:

| Menu action | Observed outcome | Remaining check |
| --- | --- | --- |
| Rapid offsets | All heads completed; offsets persisted; final dock/release passed | None for this local run |
| Vibration Compensation | Sweeps/fitting/save/restart passed | Observe status behavior after polling update |
| Nozzle Temperature Calibration | All four PID stages, final dock/release, save/restart and loaded-value readback passed | Post-restart success presentation needs durable receipt |
| Bed Leveling | All 49 points, save/restart passed; loaded mesh matches | Deploy multiline receipt correction; startup timeout remains |
| PROBE_CALIBRATE | Preparation, +0.1 mm jog away from bed and Abort passed; no pending config or busy latch | Contact check and accept/save/review with operator |
| Remaining lower Maintenance entries | Screen inventory confirms Feed & Discharge and PROBE_CALIBRATE | Feed & Discharge is a material control, not another calibration |

User2's separate Head 2 alignment-contact C015 remains a field follow-up even
though the same local rapid-offset menu completed successfully.

Installed `f9bcd31` locally with journal
`b89652dd118f41848e5d17e7145ae68e` (installer exit 0, screen PID 842313,
Klipper PID 842273). Initial polling recovered after startup. However, the
operator still observed the intermittent status panel during nozzle PID startup.
Diagnostics increased failures from 15 to 16, with a stage-2/kind-1 deadline at
1504 ms (monotonic 171246307); later successful polling continued. Thus the
calibration save-yield change does **not** resolve all status deadlines. Keep the
issue open and investigate the remaining delay rather than treating passing
host tests or one recovered sample as physical acceptance.

Passive loopback timing during PID on the updated build found normal full
status responses (about 12 KB) arriving in 111–169 ms with roughly 1 ms for the
body transfer. Around the Head 2-to-3 transition (06:07:00–03), both the native
query and a smaller read-only status query waited about 969–1054 ms before the
first response byte. That localizes these slow samples upstream of native body
consumption and excludes body transfer size as their dominant cost. It does not
yet identify the blocking backend function or prove every observed deadline has
the same cause. Passive capture continues through later tool changes.

PID physical run on f9bcd31 completed all four heads and final dock/unlock,
then SAVE_CONFIG at 06:11:18.503. After restart, both disk and configfile.settings
readback matched all new PID values. The neutral result panel was physically
observed, demonstrating the remaining normal-save UX limitation. A durable
session/request-correlated save receipt is implemented and regression-tested;
its rebuilt package still requires on-printer verification.

The attempted subsequent Bed Leveling start is NOT accepted as a running or
completed test: after the neutral panel's BACK, selecting Bed Leveling and
START briefly exposed the old unconfirmed panel, then the screen was observed
at Home with backend idle/unhomed. Operator navigation versus retained vendor
page/worker lifecycle is being checked before another motion attempt.

Passive capture also proved a freshness violation without transport failure:
last live reply 06:12:17.949; discovery completed 06:12:19.173 (851.8 ms);
next live reply 06:12:20.147 (966.1 ms). The 2197 ms status gap exceeds the
2000 ms freshness bound even though each request met its 1500 ms deadline.
A session-bound discovery cache candidate passes native lifecycle tests;
on-printer verification remains pending.

The retained vendor lifecycle trace adds an important binding constraint:
Maintenance schedules `auto_checking` on a shared FIFO pool of eight persistent
workers. Thread lifetime cannot identify a calibration run. A reservation must
start with admitted START and last through the actual queued worker invocation;
worker-entry binding alone cannot distinguish an older queued task from a newer
START. The native result OK callback clears `auto_checking_status` before
navigating to preparation, whereas the current WM+ panel BACK only navigates.
This cleanup difference is under correction together with run-correlated save
results; do not add UI-draft busy holds or infer run completion between commands.

The receipt/backend regression suite passed 274 tests, including retained
vendor SAVE_CONFIG writer/restart cases. Native lifecycle and C++11 compile
checks passed, as did 13 vendor worker/profile checks. The worker reservation
now spans enqueue through return (including exceptions); BACK mirrors vendor
terminal-state cleanup after return. The result panel confirms only saved
settings matched against the loaded configuration after restart. None of these
checks substitutes for the remaining touchscreen bed-leveling/probe tests.

Combined candidate SHA256 `7bc63e9401bf4875b20534881c06b9d58f54d74fcddb6b05b72ef9f87e389a3e`
built and passed all 82 delivery/package checks. Local installation journal
`181fc6602fd84afc862ad98150569ff6` completed, screen PID 853158. Post-install
readback was Ready/standby, no active or failed calibration, all heater targets
zero; screenshot showed normal Home. Installer activation synchronization passed,
although its final summary reported a stale diagnostic sample. Neither normal
startup nor this readback verifies active-calibration polling or saved-result UI;
those physical checks remain pending.

Local Bed Leveling on candidate 7bc63e94 ran through touchscreen START at
06:35:55 printer time, bottom/XY homing, Head 1 mount, 140C nozzle / 55C bed,
all 49 mesh points, SAVE_CONFIG and Ready after restart. The result receipt
reported unconfirmed: the persisted multiline mesh had identical numbers but
ConfigParser removed leading continuation whitespace. This is a verifier false
negative, under correction; do not repeat the physical calibration to repair it.
BACK returned to Maintenance, and PROBE_CALIBRATE opened idle with Start enabled.
Physical contact/accept/save remains pending operator participation.

Passive capture during heating/probing counted 392 complete native replies,
maximum response 450ms and maximum status gap 1056ms, with zero discovery calls.
After restart, 103 complete replies had maximum response 1423ms and maximum gap
1792ms. No periodic stale gap was captured. One earlier 1503ms timeout at
06:36:36, after tool mounting, remains unresolved; do not claim all polling
latency fixed. Capture logs are /tmp/wmp-bedlevel-session-discovery-packets.log
and /tmp/wmp-bedlevel-session-discovery-completion.log. The expected restart
outage is separate from active-calibration freshness.

Multiline save verification now uses the writer/parser round trip for expected
values. The captured on-printer receipt verifies against captured disk and loaded
config, and 282 backend tests pass, including changed/missing/extra mesh-data
negative cases. Deployment and live receipt verification follow.

Remaining latency investigation: wm_material.get_status can synchronously
persist filament-loaded flags on initial adoption or a loaded-to-empty sensor
transition (file fsync, replace, directory fsync). Macro rendering and move
planning are other possible non-yielding spans around the startup wipe. These
are candidates, not a proven cause of the isolated timeout. Use bounded timing
spans to distinguish them before modifying physical motion behavior.

Final candidate `8e22b7fa186a9d61040c831ecf8f18e173e8d726d6f3c8ca3805a03bb396a670`
passed 82 delivery tests and installed successfully (screen PID 860167).
Live readback after actual service reload reports the existing bed-level save
receipt `state: confirmed`, with matching origin session/request and empty
error; printer Ready/standby, no calibration fault and all targets zero.
This verifies live persisted mesh confirmation without rerunning calibration.
A full screen-service restart retires the old run panel, so its confirmed text
is covered by native lifecycle tests rather than a new physical result screenshot.

### Controlled mount follow-up after da3af89

CI 43650632874 passed. A screen-driven dock/mount cycle succeeded physically
but reproduced a native deadline at 07:00:18.539, 1507.6ms with zero response
bytes; last-good to next-good status gap was 2855ms. Tool locked at
07:00:16.541 and pressure advance logged at 07:00:17.832. Filament state/profile
file mtimes were from November 13, so their persistence cannot explain this
November 15 incident. Native transfer/JSON processing is not its measured cost.

The printer's perf command is an unusable wrapper for missing perf_5.10.
A temporary in-process timing overlay therefore sampled wm_material/configfile
status, macro rendering, toolhead.move/_advance_flush_time, bed_mesh.move and
cached gcode_move.move_with_transform. It was not committed or included in the
release. Mock tests (17 passed) cover exception transparency, bounded logs,
clock/logging failures and identity-checked restoration. Source was restored
immediately after each diagnostic startup; wrappers expired after 180 seconds.
The first 50ms trace exhausted its log allowance on routine 50–65ms material
status calls. A second 200ms trace preserved the full mount window and recorded
no individual instrumented call over that threshold.

That second mount succeeded but captured a 1501.8ms no-byte timeout at
07:18:00.437, BEFORE Tool locked at 07:18:07.685. A later post-pressure-advance
reply took 1148.3ms. This disproves treating the observed post-lock timing as a
unique root cause. Several shorter non-yielding operations or a delay elsewhere
in the request path remain possible. Next attribution should distinguish reactor
scheduling gaps from Moonraker/transport queue delay before expanding method
instrumentation; do not change physical motion or freshness thresholds on this
evidence alone.

Both trace runs logged successful restoration with no remaining wrappers or
cleanup errors. Final released helper SHA256 is
2d2f27f7d643e124532d03b733e24c84fd61474cbdee812a303c14de0b7a02f1;
temporary overlay source is absent. Final status: Ready/standby, XYZ homed,
Head 1 attached at the wipe position, all heater targets zero, no calibration
failure. Passive capture processes also exited. Logs remain at
/tmp/wmp-instrumented-mount-packets.log and
/tmp/wmp-instrumented-mount2-packets.log.

Physical probe-editor test: preparation reached manual adjustment at Z4.417mm;
+0.1mm button changed readback to Z4.517mm. ABORT reached state aborted, sequence2,
no calibration_active/failed state, save_config_pending=false and empty pending
items. Start became available again. No ACCEPT or SAVE was issued. Bed was then
lowered50mm through XYZ controls to Z54.517mm for clearance. Final contact-based
accept/save/restart review remains pending operator feedback.

The next temporary request-path trace (19 mock tests, 180-second limit) captured
an idle/pre-dock reactor delay at 07:33:34.957: 1292.680ms wall interval and
1034.525ms thread CPU. A request logged at 07:33:35.044 spent1378.525ms processing
(including waiting for query completion), while socket send buffers were empty
and nonblocking. No QueryStatusHelper._do_query call exceeded150ms. This proves
CPU-heavy reactor delay for at least one event, but other timeouts did not have
an equally large heartbeat delay and must not be assigned the same cause yet.

This run's mount completed with95/95 native replies; maximum response1451ms and
maximum status gap1919ms. Three earlier no-byte timeouts occurred07:33:35.042,
07:33:58.578 and07:34:20.651. The request overlay restored all hooks at07:36:28.828
with zero errors, and its source file was removed; released helper hash unchanged.
Passive capture /tmp/wmp-requesttrace-mount-packets.log exited at07:37:31.
The subsequent idle-only GC observation ran for 180 seconds without changing GC
behavior. All 218 native requests completed; maximum response was 1347.8ms and
maximum status gap was 1738ms. Replies exceeding one second clustered in the
first 32 seconds after Ready; later replies peaked at 835.5ms. No GC collection
exceeded 50ms, so this run does not support long collections as the cause of
the observed startup CPU stalls.

Hooks restored at 07:45:46.335 with zero errors, no remaining wrappers and
gc_observer=False. Passive capture finished at 07:46:31; released helper hash
was independently verified unchanged. Evidence: /tmp/wmp-gc-idle-packets.log
and /tmp/wmp-gc-idle-trace-final.log. Residual status latency remains open.

### Separate field report: print abort after adaptive mesh

User1's supplied klippy.log.txt records successful saving/loading of wmp_print
at 07:37:46, followed by `Restart not admitted: Finish or cancel the print
before restarting` and SD-card exit at position 20204. START_PRINT calls
SAVE_CONFIG_NO_RESTART immediately after loading this mesh. The standalone
writer guard only recognizes managed submissions, so a stock SD startup can
reach the restart refusal despite requesting no restart. This is a confirmed
save-admission failure, distinct from the intermittent status display issue.
The correction grants a stock SD startup a one-use mesh-save permission bound
to the same open file, file identity, SD command positions, session and
cancellation generation. It permits only wmp_print pending settings and consumes
permission before invoking the retained writer, including on writer failure.
No machine-busy state is acquired. Managed-start admission remains intact.

The focused configuration suite passes 102 tests, including rendering the
production START_PRINT template for both stock and managed SD starts through
the post-save marker, with the retained writer and backup behavior. Tests also
cover consecutive starts, unrelated pending settings, remote saves, changed
file/command/session, active operations, failed writes and failed recovery
invalidation. Independent review found no blocking issues. These are software
regressions, not a completed physical print; field launch route is unreported.

### Physical stock-SD coupon verification after caf459a

The rebuilt config/material/preload package installed successfully; running
protocols, source/artifact pairing and native GUI synchronization verified for
screen PID 879934. Release CI 43655504249 passed. Broader material/restart tests
passed 1526 cases (2 skipped); package delivery tests passed 82 cases.

With the operator confirming the plate installed and clear, ordinary Moonraker
`/printer/print/start` launched WMP_STOCK_START_COUPON_20261114.gcode, a separate
copy of the five-layer 12x12x1mm recovery coupon with PRINT_END restored. Head 1
had loaded PLA; settings were 220C nozzle / 60C bed and a 4x4 adaptive mesh.
Bottom homing completed normally. The first mesh point retried its samples and
passed; all points completed. Console evidence then records wmp_print saved,
`START_PRINT adaptive_mesh`, `START_PRINT finished`, and `Done printing file`.

The job reached complete in 327.649 seconds with 77.39011mm reported filament
including purge. SD reached EOF and closed, PRINT_END ran, carriage parked at
X-13 Y275, bed lowered to Z51.035, and all heater targets returned to zero.
Final status was Ready, no calibration failure/active state, Head 1 attached.
This verifies the stock SD startup/save/deposition-command/completion path on
hardware. Camera visibility is insufficient to assess the physical coupon;
operator confirmation of the formed part and quality remains pending.

Evidence under analysis/validation/2026-11-14-calibration-menus:
coupon-full-console.json, coupon-completed-final.json,
coupon-body-progress.json, coupon-completed-screen.jpg and camera snapshots.
