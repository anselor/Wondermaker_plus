# Upstream command side effects: homing, calibration, settings and recovery

Read-only source audit, 30 October 2026. No printer connection, navigation, motion,
heating, restart or configuration change was performed. Only this report was added.
`config/stock` is the sanitized System 1.1.13 vendor baseline (per `config/README.md`);
`config/live` is the WM+ candidate. Source sequences establish intended dispatch,
not that every later command executes after an earlier failure.

This is the non-filament portion of the audit. Some calibration commands nevertheless
extrude large amounts. A command's name is not a reliable description of its full
physical or persistent effect. Direct macro callers below are source-proven; client
callers are labeled historical or previously investigated where fresh binary call
tracing was not performed.

## Current caller reconciliation — 12 November 2026

This section supersedes the unresolved implementation tasks in the dated audit
below. It closes G05's source/caller reconciliation for the standalone release,
not every visual or hardware check. The supported exact client is unchanged.

| Affected caller | Current implementation and evidence |
| --- | --- |
| XYZ ALL/XY/X/Y/Z | The five traced senders below reach the current homing override. Mounted-head selection and explicit XY-only service preparation are covered by the retained macro/recovery tests; ordinary Take/Dock acceptance is recorded under C02/R25. No new stock homing campaign is required. |
| Maintenance and first-run calibration workers | `native/stock_maintenance_command.hpp` wraps all 32 profiled direct sender sites; only the two PID tool-selection sites rewrite logical T to physical selection. `test_every_worker_sender_is_profile_bound_and_guarded` independently enumerates the first-run BL instructions and compares the complete sender set and bytes with the profile. `bootstrap.cpp::unified_command_sender` applies the wrapper. |
| Calibration continuation and cleanup | `test_calibration_commands.py::test_failed_stage_blocks_later_heads_dock_and_save` checks exception, soft fault and shutdown: later tool selection, movement, heating, parking and SAVE_CONFIG cannot execute after the latch. Successful commands and checkpoint publication have separate assertions. This replaces reliance on the vendor's knife-only failure byte. |
| First-run page continuation | `Runtime::calibration_navigation` and the native lifecycle tests require a new matching backend checkpoint before navigation. The joined production setup-entry/FINISH test passed in the 12 November checklist entry. G03's native presentation was accepted separately on 13 November using the production layout with disconnected sample-data actions. |
| Bed/probe/offset reference preparation | Current macro tests cover physical reference selection despite nonidentity slicer mapping and G29 reference establishment before heating/mesh. R24's evidence map covers managed editor ownership, persistence and review. No additional physical calibration is inferred or required by this audit. |
| Nozzle Flow and retired filament guide | `bootstrap.cpp::unified_nozzle_flow_event` consumes managed service actions before the vendor prefix; `stock_service_event.hpp` and native lifecycle assertions cover all eight load/unload actions and stale/hidden/disabled input. Both guide workers are retired. R21 tracks the managed service acceptance. |
| Identification, discovery and direct config writers | R23's current evidence map covers retired native workers, unchanged-mapping preservation, changed-mapping refusal, and guarded SAVE_CONFIG. These supersede the old unresolved UUID-writer task; arbitrary hardware remapping remains unsupported. |
| Startup restart and recovery/retry callers | R25/R26 and the stock-client conflict report cover coupling fault retention, exact startup shell suppression, managed restart ownership and accepted persistence. No general restart retest is needed. |

Sources and assertion bodies were inspected for this reconciliation. Existing
accepted results were retained; no tests, printer commands, calibration or
restart were repeated for this documentation update. Factory reset/service
qualification and openACE remain outside the initial release. G03 and R22/R24 native presentation checks were subsequently accepted on
13 November. Physical quick-touch feedback, direct manual-retract observation
and G06 delivery activation remain open in `ui/standalone-completion.md`.

## Current homing reconciliation — 7 November 2026

The tables below are the historical 30 October audit. In particular, their
ordinary-homing description predates the current mounted-head selector and
explicit XY-only branch. Do not use that historical description as the current
filament-service contract.

The exact 1.1.13 stock client dispatch is now traced in
`analysis/validation/2026-11-07-stock-callers/xyz-homing.asm`,
`home-dispatch.asm`, and `home-command-literals.json`:

| Stock control | Worker → sender | Command | Current source behavior |
|---|---|---|---|
| ALL | `0x528a30` → `0x614e7c` | `G28` | Ordinary full homing checks attachment sensors and chooses the mounted physical reference; explicit startup reference and recovery are distinct branches. |
| XY | `0x528590` → `0x614ef8` | `G28 X Y` | Explicit XY branch skips `z_rise`, Z homing and tool selection. |
| X | `0x52810c` → `0x614f74` | `G28 X` | Single-axis branch still includes `z_rise`; it is not equivalent to the explicit XY-only service command. |
| Y | `0x52834c` → `0x614ff0` | `G28 Y` | Single-axis branch still includes `z_rise`. |
| Z | `0x5287e0` → `0x61506c` | `G28 Z` | Explicit Z homing includes leveling/diagnostic commands and the Z7 move. It is not used for filament-service preparation. |

All five enter `config/live/printer.cfg`'s homing override, which rejects
`fail_flag == -3` before emitting any homing command. The regression test now
renders each stock parameter combination under this fault and requires an error.
Other recovery tests cover full-home attachment disagreement, mounted-head
reference selection, and XY-only exclusion of Z/tool selection for idle/paused
states with either Z-reference flag.

Validation: `tests/test_config_macros.py` and `tests/test_print_recovery.py`
passed **184 tests** in 60.30 seconds. Log: `r67-homing-tests.log` in the same
evidence directory.

These are binary/source and host-model checks, not physical calibration or
homing acceptance. No homing was issued during this audit. Calibration's exact
current branch sequencing and ownership still need reconciliation, and G05
remains open.

## Physical calibration-head correction — local candidate, 7 November

### Follow-up after r69: bed calibration and PID selection

Current `G29` had a separate reference-timing defect: it selected physical T0
after XY homing, but tested the entry snapshot's **XY** state to decide whether
to home **Z**. An XY-homed/Z-unhomed entry could therefore reach probing without
establishing Z; an already-homed different head could retain the wrong datum.
The local correction uses `G28 P0` before heating/probing, so the existing homing
override selects the physical reference head and establishes its Z datum. It
rejects printing, paused jobs, toolhead faults and unresolved recovery before
any side effect. Heating/waiting/cooldown explicitly name physical `extruder`.
The existing bed 55 °C, nozzle 140 °C, wipe and mesh sequence remain. This is
maintenance calibration; the separate print-start adaptive mesh path is unchanged.

Twenty-one focused recovery-model cases pass: all four starting physical heads
with no axes, XY, Z or XYZ homed, plus active-print/fault/recovery rejection.
Hardware waits, probing and tool movement are modeled endpoints; physical
acceptance remains outstanding. This correction is local, not installed in r69.

The exact 1.1.13 PID branch has another confirmed mismatch. At `0x4b7cb4` it
sends `T` plus the loop index (literal `T` at `0x3630558`), then a centre move
at `0x4b7cf0`. At `0x4b7d8c` it sends `PID_CALIBRATE HEATER=extruder[N]
TARGET=220`, where the same loop index is a physical heater suffix (empty for
zero). Logical T selection can be remapped while the PID heater stays physical.
Cleanup sends `PARK_CURRENT_TOOL` at `0x4b7df4`. Evidence is the existing exact
worker disassembly plus `pid-physical-selection-audit.json` in the stock-callers
evidence directory. This branch still needs correction and tests; the G29 fix
does not establish PID/calibration worker completion.

The subsequent r70 candidate corrects that selection at the verified sender
call site: only caller return address `0x4b7cb8` rewrites T0–T3 to the guarded
physical `_WMP_CALIBRATION_TOOL` macro. Normal print tool commands are unchanged.
The sender entry's four relocated instructions contain only stack/register
operations; its full profile window and the PID call window are verified against
the exact vendor ELF. Eight routing/profile tests pass, including six cases
executing the actual ARM wrapper up to its first C++ string helper. The compiled
disassembly shows original LR compared before any BL. The backend validates
idle state, faults, recovery and physical indices before tool selection; 322
macro/recovery tests and 42 runtime-acceptance tests pass. This candidate is not
deployed in r69 and does not claim a physical PID calibration pass or complete
the remaining worker/cleanup audit.

Current source exposed a standalone mapping defect: offset calibration accepts a
physical head index for saved offsets, but selected `T0`–`T3` and heated through
`M104/M109 T`, which apply the slicer's `box_modify` mapping. A non-identity or
duplicate mapping could therefore select/heat a different head from the requested
calibration index. This is not limited to openACE ownership.

The local `offset_calibrate.cfg` candidate now uses `_CHANGE_TOOL T=<physical>`
for preparation and XY/Z offset calibration, explicit heater names for preparation,
wipe/preheat and rapid-mode shutdown, and matching physical sensor names for
heating/cooling waits. Next-head preheat still targets the next physical head.
Five per-head entry macros validate T=0..3 before emitting commands and reject
printing/paused jobs; both all-head wrappers reject those jobs before their
preparation sequence. POP/blob cleaning is a separate caller and is not changed
by this patch. Existing calibration distances, extrusion and temperature choices
are unchanged.

The exact current client worker `_ZL13auto_checkingv` at `0x4b7558` references
`NOZZLE_PREPARE`, `NOZZLE_CALIBRATE_TOOL_OFFSET` and `RAPID_MODE`, as well as
G29, shaper and PID branches. Literal/call inventory is in
`2026-11-07-stock-callers/calibration-auto-check-literals.json`. That inventory
identifies reachability candidates; it does not prove all branch predicates or
safe sequencing of the entire worker. Its own preparation before the macros,
PID/bed-leveling branches, and interrupted cleanup still require review.

Validation: the final macro/recovery suite passed **248 tests** in 92.73 seconds.
Evidence: `calibration-final-tests.log` and `calibration-candidate-hashes.json`
in the same stock-callers directory.

This correction is local, not deployed in r67, and no calibration has been run.
Host tests exercise every physical head with a duplicate/non-identity slicer
mapping, heater wait ownership, invalid head parameters and active-job rejection.
G05 remains open for the remaining caller chains and physical qualification.

## Z-calibration result timing — local follow-up

`CALIBRATE_TOOL_Z_OFFSET` previously captured `current_extruder` while rendering
its outer template, then emitted the tool change and probe. Its later conditional
still used the old captured value, so requesting a different head could skip
recording a successful probe. The local candidate always schedules
`_SAVE_PROBE_POS T=<requested physical head>` after PROBE/M400. That nested macro
reads current head/fault state at execution and rejects a wrong head or nonzero
tool-change fault before reading the probe result or changing calibration values.
It validates the physical parameter independently. Physical Head 1 (T=0) still
records the reference; other heads record their measured Z value.

Focused tests model old-head→requested-head transitions, empty-carriage entry,
wrong-head and failed-change rejection, invalid parameters and reference-head
recording. **45 focused tests passed**, with log and source hashes in
`2026-11-07-stock-callers/calibration-result-tests.log` and
`calibration-result-candidate-hashes.json`. This follow-up is not deployed and
is not hardware acceptance.

## Partial calibration saves — local follow-up

RAPID_MODE used to call SAVE_TOOL_OFFSET immediately after XY measurement, which
also wrote the previous `z_pos - z0_pos`, then overwrite it again after Z probing.
If Z probing failed, the early write could leave stale Z persisted. The local
candidate marks the first save `AXES=XY`; SAVE_T_OFFSET's existing omitted-axis
semantics preserve the stored Z. Only the post-Z save writes the combined result.

SAVE_TOOL_OFFSET now checks the physical head and fault status. An XYZ save
requires a recorded reference and a Z-result owner matching the requested head;
it consumes that ownership after saving. Starting a new Z calibration clears the
old result owner before tool change/probing, and starting reference-head Z
calibration invalidates the reference until a successful probe records it.
These variables are runtime calibration state and intentionally start invalid
on restart. The all-head sequence measures physical T0 before the other heads.
A standalone nonreference Z save without a reference reports the missing
measurement instead of silently treating zero as a measured datum.

Validation: **91 focused calibration tests passed** in 38.90 seconds, including
XY preservation through SAVE_T_OFFSET, measurement ownership, invalidation and
rapid-mode ordering. Evidence: `calibration-save-tests.log` and
`calibration-save-candidate-hashes.json` in the stock-callers directory.
This is local and undeployed. No calibration, heater or motion command was sent.

## High-impact command families

| Entry / caller | Stock effects and conditions | WM+ live difference / implication | Evidence |
|---|---|---|---|
| Any `G28`, including `G28 X Y` | Homing override begins `QUERY_ENDSTOPS`, then `z_rise`. When Z is homed below 3 and queried endstop is clear, relative Z+3; when Z is unhomed and endstop clear, declares Z=3 then relative Z+3. Requested X/Y homing can therefore include Z motion and coordinate declaration. Ends in G90. | WM+ recovery-only bare G28 branch (z_raise=0) instead establishes bottom Z when needed, homes missing XY, restores mesh and offsets, and skips Z_HOMING/LEVELING; ordinary branches still call z_rise. Never assume stock semantics survive unchanged. UI “home XY” must disclose/admit the actual owner sequence. | `config/stock/printer.cfg:298,311`; `config/live/printer.cfg:325` onward |
| Bare `G28` → `Z_HOMING` | Home Y/X, then clear mesh, reset XYZ offsets with MOVE=1, disable tool-return saving and select T0. During printing/paused, calls WIPE_NOZZLE. Moves centre, pulses leveling line, enables stepper diagnostics, homes Z and optionally raises to Z7; disables diagnostics. | Tool selection, wipe and offset motion are real nested effects. WM+ has physical-tool/probe context and recovery modifications; parent audit should trace current branches before reusing Home as a UI helper. | stock `printer.cfg:356` onward |
| `PROBE_CALIBRATE` | Clears mesh; full G28 if not fully homed, else commands absolute Z5; moves X150 Y150 and calls original calibration. | Live replaces fixed Z5 with `_WMP_CALIBRATION_CLEARANCE`, evaluated after homing; helper requires XYZ known, raises only if below 7, checks Z maximum. | stock `macros.cfg:347`; live `macros.cfg:437`; live `offset_calibrate.cfg:488` |
| `G29` | Sets bed-leveling flag, homes XY, starts bed55, selects T0 when original tool differs, conditionally homes Z, centre move, nozzle140, waits for bed/nozzle, wipes, meshes, nozzle off and clears flag. Bed target remains55. Jinja conditions use entry snapshot, not refreshed state after emitted G28. | Live clears print mesh context and selects physical `_CHANGE_TOOL T=0` instead of logical T0. Heating/wiping/mesh remain. | stock `macros.cfg:361`; live `macros.cfg:456` |
| `BED_MESH_CALIBRATE` wrapper | Full G28 if XYZ unhomed; G90, absolute Z7, Y then X move to mesh start; invokes original mesh command. | A request to mesh includes its own preparation motion. WM+ offset clearance/mesh reference work does not make this read-only. | stock `macros.cfg:406`; current live wrapper |
| `CALIBRATE_OFFSET_ALL_FINE_MODE` | Iterates every configured head: NOZZLE_PREPARE at220 → NOZZLE_CALIBRATE_TOOL_OFFSET → RAPID_MODE. | Large extrusion belongs to this calibration chain, even though its public entry is an offset-calibration name. | stock `offset_calibrate.cfg:310` |
| `NOZZLE_PREPARE T=... [S=220]` | Select tool; T0 branch warms140 and homes Z; resets offsets, moves X150 Y1, probes, applies pre-Z offset; raises relatively1; resets E, heats/waits requested S; relative E120 then E-3; fan full, waits/cools100, absolute Z80, fan off. | Live prohibits printing/paused and adds clearance; replaces final bidirectional M109 wait with upper-only cooldown. **Live cooldown still resolves box_modify**, while openACE tool/heater routing is virtual. That interaction requires explicit owner audit before enabling calibration under openACE. | stock `offset_calibrate.cfg:175`; live `:177` onward |
| `NOZZLE_CALIBRATE_TOOL_OFFSET` | Starts selected nozzle160 and, unless last head, preheats next nozzle160. Z10, travels Y240/X-13, waits160; four wipe cycles Y240↔275; selected heater off. | Live adds G90 before moves. Next-head preheat is an intentional secondary heater effect, not a single-head-only operation. | stock `offset_calibrate.cfg:215`; live `:236` onward |
| `CALIBRATE_TOOL_OFFSET` | Disables collision detection before tool selection; clears mesh/offsets; centre probe, Z15, apply pre-offset; moves over sensor; sets collision threshold12/window2/shutdown and enables detection; runs native sensor/tool calibration; disables detection and moves Y250. | Live adds clearance before tool/probe travel. An interrupted sequence may not reach final cleanup; do not claim threshold/detection restoration is exception-safe. | stock `offset_calibrate.cfg:255`; live `:279` |
| `RAPID_MODE` / `CALIBRATE_OFFSET_ALL_RAPID_MODE` | Despite “mode”, performs calibration. Homes Z if unknown, Z10, selected heater off, XY and Z calibration, and offset saves for nonzero tools; ALL starts full G28 and iterates heads. | Configuration-like name conceals motion and persistence. | stock `offset_calibrate.cfg:237,301` |
| `CALIBRATE_TOOL_Z_OFFSET` | Selects tool, clears mesh, applies offsets, then `SET_GCODE_OFFSET Z=0 MOVE=1`; centre probe, conditionally records result, Z10. | Live clearance additions reduce approach risk but do not change ownership requirements. | stock `offset_calibrate.cfg:319`; live corresponding section |
| `CALIBRATE_TOOL_POSITION` | GET_T_POSITION, persist measured position, home XY, move X150 Y200, then M84 (motor disable). | A position-calibration action also leaves steppers disabled; do not treat its return as homed/motion-ready without readback. | stock `offset_calibrate.cfg:366` |
| `_OFFSET_RESET` | `SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=1` physically compensates coordinates. | “Reset” is not a passive metadata clear. | stock `offset_calibrate.cfg:135` |
| `POP T=...` | Turns current heater off even before validating supplied tool. With tool: conditional home, select tool, wait222, move Y2/Z2, E88, fan full, wait102, fan off, Z25. E amount interpretation depends on inherited extrusion mode; no M83 in this macro. | Live prohibits active/paused prints, adds G90 and upper-only cooldown; still uses box_modify for cooldown heater. Remains an extrusion/maintenance operation. | stock `offset_calibrate.cfg:389`; live `:441` |

## Heating, settings and automatic work

| Entry | Surprising or conditional effect | Evidence / current treatment |
|---|---|---|
| `M104/M109 T<n>` | Stock remaps T0..T3 through box_modify; no T uses active extruder. M109 waits inside ±2.5°C for positive target, including cooling waits. | stock `macros.cfg:451,480`. Under openACE T is virtual; physical UI heater actions require explicit physical heater names. |
| `M190` | Sets bed target and waits in ±1°C when S nonzero; can block for cooling, not only heating. | stock `macros.cfg:508`; retained core semantics |
| `M191 S0` | Only emits “Chamber heating cancelled”; **does not set chamber heater target to zero**. Positive S sets chamber and waits±1 if chamber exists. | stock `macros.cfg:547`; corresponding live macro retains behavior. Use explicit physical off for a UI Off action. |
| `M107` | Switches part cooling, auxiliary P2 and optional air P3 off, not merely one active fan. | stock `macros.cfg:534`; live equivalent |
| `_START_PROBE` | If extruder0 target >0: fan full, active-target M104 S0, wait extruder0≤49 when sampled actual>5, fan off, dwell1s. Sensor and active heater can differ. | stock `macros.cfg:428`; caller reachability not established here. Do not infer it is currently active from definition alone. |
| `M221 S... T...` | Changes runtime extrusion factor and saves per-T flow variable. | stock `macros.cfg:705` |
| Automatic `PRINTER_INIT` after5s | Calls RESET_FLOW_EXTRUDER, loops configured head count with M221 S100 Tn, persisting each flow reset. | stock `macros.cfg:1,713`; no user button needed |
| `START_PRINT` → `SAVE_CONFIG_NO_RESTART` | When adaptive leveling enabled, startup can write printer.cfg and its SAVE_CONFIG block. Name avoids restart, not persistence. It also temporarily rewrites box_modify_t0 and later restores it; interruption before restoration matters. | stock `macros.cfg:7–89`; vendor `analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/configfile.py:439` writes temporary config, renames original to dated backup, renames temp to live; restart calls commented out. WM+ startup/mesh context differs. |
| `G30/G31` | Toggle next START_PRINT adaptive_mesh_enable flag only; no homing or leveling immediately. | stock `macros.cfg:397,401` |
| Idle timeout600s | Message says all heaters off, but loops nozzle heaters only. Bed/chamber are not switched off in this config body. | stock `printer.cfg:432`; do not use message wording as proof all heater targets are zero. |
| `_GANTRY_TRIGGER`, `_LEVELING_TRIGGER[_S]` | Pulse output pins with blocking dwell delays; `_LEVELING_TRIGGER_S` is invoked during Z homing. | stock `load_cell.cfg:34–54`; live file identical in audit. Pin consequences depend on connected hardware. |
| `TEST_POWER`, `TEST_XY` etc. | Factory-style tests are real commands: TEST_POWER heats all four nozzles290 and bed70, disables air/aux fans, sets pins, traverses XY. TEST_XY loops toward50000 with persistent counter writes. | stock `test_macro.cfg:16,44`; stock printer.cfg:17 includes test_macro.cfg, so these are registered in that include graph. These are not diagnostic read-only endpoints. |

## Timelapse is a potential motion caller

`TIMELAPSE_TAKE_FRAME` defaults both `enable` and `park.enable` false. If enabled
and parking enabled, it can retract (if can_extrude), call configurable macro.pause
(default PAUSE), clear XY offsets, park with bounded Z, schedule delayed polling
and request a frame. `_WAIT_TIMELAPSE_TAKE_FRAME` polls while takingframe, then calls
configurable macro.resume (default RESUME), reprimes when extrusion allowed and
restores E/mode/feed factors. HYPERLAPSE can schedule repeated frame requests.

Evidence: stock `timelapse.cfg:234–331` and subsequent HYPERLAPSE loop. The live diff
review showed wording changes; the parked capture/resume mechanism remains. This
must be included in the resume-origin inventory, but **does not prove parking is
enabled on the current printer**. A camera action can be a motion action under
this configuration. Read the effective runtime `park`, `enable`, `macro` values
before drawing conclusions from a screenshot or timelapse option.

## Stock client caller evidence and limits

### Current-profile correction — 7 November 2026

The historical file named `nozzle-cleaning.c` actually decompiles
`start_nozzle_setting()` at `0x510350`. Fresh disassembly of the exact 1.1.13
client (SHA256 `b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715`)
shows **Extruder Setup / head identification**, not nozzle cleaning. The associated
page says to hang extruders on the rear support; the worker identifies UUIDs and
restarts firmware. Its eight direct sender sites are:

| Sender instruction | Command |
|---|---|
| `0x510580` | conditional `G28` |
| `0x5105c0` | `PARK_CURRENT_TOOL` |
| `0x5108bc` | `SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=1` |
| `0x510958` | `T` plus identification-loop index |
| `0x510db4` | `PARK_CURRENT_TOOL` |
| `0x510f98`, `0x511120` | `SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0` |
| `0x5111c4` | `FIRMWARE_RESTART` |

This is a remaining G03/G05 workflow: its T sender return address `0x51095c`
is absent from the r72 physical-head rewrites, while the installed T0–T3 macros
use `box_modify_t*`. Thus non-identity slicer mappings can change the physical
head selected by the identification loop. Review its admission, direct UUID/file
writes, wait/failure handling and physical selection together; wrapping only its
T command would not establish whole-workflow completion. No setup was executed.

Subsequent local correction (not deployed): the verified `0x51095c` caller now
rewrites T0–T3 to `_WMP_CALIBRATION_TOOL T=<physical>`, with malformed input sent
to that macro's rejecting path. Its 32-byte call window is profile-bound. This
uses the existing idle/fault/recovery admission for the selection itself; it does
not put the whole identification worker under the calibration command latch.
Other setup commands, UUID writes, and restart are unchanged. The local ARM build
and 78 routing/worker/delivery tests pass; identification lifecycle disassembly
has been captured for the remaining review. Installed r72 does not contain this
selection correction.

#### Identification failure lifecycle — exact ARM characterization

Eight cases in `tests/test_stock_identification_worker.py` execute the vendor
instructions with host calls stubbed; no commands or UUID writes reach a printer.
They establish two additional defects:

- `wait_T_sync` (`0x5117d8`) clears `tool_check_error` at `0x5117ec` before
  waiting. An error received before the wait begins is therefore discarded.
- After the final `PARK_CURRENT_TOOL`, the continuation at `0x510dcc` reads the
  duplicate-UUID flag on the stack, not `tool_check_error`. With no duplicates,
  both error values enter the UUID publication loop at `0x510fc8`.

The pickup branch at `0x510970` does inspect the shared error flag after its
wait, but that does not recover an error the wait already cleared. The UUID
publication loop calls `read_write_nozzle_uuid` in write mode at `0x5110bc`,
then sends the flag-clear command and `FIRMWARE_RESTART`. That helper invokes
`read_write_can_id.sh`, whose vendor implementation edits `wm_zru_thrN.cfg`
with `sed -i`; its final status check follows `sync`, not the edit. A command-only
backend latch cannot guard those direct file writes.

Required correction: admit setup only from fresh idle/ready state before its
first motion, retain failure across all waits, require confirmed completion of
pickup and final docking, and publish the complete verified UUID mapping as a
guarded transaction. Failed or uncertain setup must preserve the previous mapping,
show the failed stage, and avoid automatic restart. These remain implementation
and acceptance work; the physical-selection correction is only one part.
Evidence: `analysis/validation/2026-11-07-identification-lifecycle/`.

The current command-reference scan finds `NOZZLE_PREPARE S=` in the already
guarded Maintenance worker at `0x4b7558`. It did not find a direct `POP T=...`
command literal in the scanned symbol-backed code; `POP_*` matches in the popup
handler are log messages, not evidence of blob-cleaning dispatch. This scan is
not proof that dynamically constructed commands are unreachable.

Evidence is in `analysis/validation/2026-11-07-stock-callers/`:
`nozzle-setting-current-audit.json`, the four `*nozzle_setting*.asm` files,
and `client-cleaning-command-inventory.json`. The six blob-cleaning model tests
pass after correcting the test to distinguish the explicit heating wait from
the later cooling-only wait; they still require only the expected vertical lift
after cooldown. This is software evidence, not physical cleaning qualification.

| Client origin | Evidence strength | Consequence |
|---|---|---|
| Auto-check calibration workflow | Historical 1.1.08 decompilation `analysis/fw_1.1.08_diff/implementation/ghidra/nozzle-auto-check-strings.c:184,274,349,394,406,496` emits G28, G29, NOZZLE_PREPARE S= and RAPID_MODE T=. Calibration entry also emits G28 (`calibration-entry-strings.c:25`). | Confirms these macros are reachable from a stock GUI workflow in that version; exact 1.1.13 event/callback equality is not established by this report. |
| Historically labeled nozzle cleaning | Corrected above: `start_nozzle_setting` is Extruder Setup / head identification. | Its homing, UUID writes and restart must be reviewed as a setup workflow. |
| Communication error → `unlock_extruder` | Existing 1.1.13 binary/incident analysis in `docs/firmware-1.1.13.md:179,195` and `docs/head-communication-recovery.md`. | Callback cleared UUIDs1–3, replaced printer config with one-head template, removed excluded-head calibration and persisted head counts. WM+ head-config guard intercepts the whole callback; it does not suppress MCU safety shutdown or imply successful communication recovery. |
| Touchscreen client startup | Previously established in the active handoff: client startup restarts Klipper. Not freshly re-decompiled in this scoped review. | UI service restart is not safe as a “UI-only” refresh during a paused print. Parent client audit must cite exact current binary location before its final call graph. |
| File/slicer/user commands → macro chain | Direct source evidence above. | Even without GUI auto-callbacks, any issuer of G28/G29/calibration/timelapse inherits these nested effects. Caller identity matters when deciding whether action was explicitly requested. |

## Findings to carry into the UI implementation

1. Classify each control by the *expanded command sequence*, including conditional
   homing, tool selection, heat/wait, extrusion, persistence and motor-disable effects.
2. Keep calibration as explicit idle maintenance. Retaining a stock calibration
   page does not establish safe openACE routing: the remaining box_modify-dependent
   cooldown and virtual T command use need a deliberate physical-head policy.
3. “Home XY”, “calibrate”, “reset”, “camera frame”, “heater off” and “restart UI”
   cannot be treated as uniformly narrow primitives on stock firmware.
4. Separate deliberate requested sequences from autonomous callers: startup delayed
   work, timeout behavior, timelapse polling and communication-recovery callback.
   No global G28/G1 filtering is justified by this audit.
5. Current-profile client origin mapping remains incomplete for calibration and
   cleaning. Mark that gap rather than promoting historical string matches to
   proven 1.1.13 call paths. No new guards or macro edits were made in this review.

### Calibration worker continuation audit — 7 November, after r70

Exact client 1.1.13 worker `_ZL13auto_checkingv` still needs failure-propagation
qualification. New `tests/test_stock_calibration_worker.py` executes its ARM
branch instructions in Unicorn, with external C++ formatting calls stubbed and
wait outcomes injected; seven characterization cases pass. These tests document
existing behavior, **not successful calibration or a correction**.

- PID loop calls `wait_sync` at `0x4b7db8`, then increments the physical index
  unconditionally. Both return values 0 and 1 reach the next selection's string
  construction (`0x4b7c84`), or PARK_CURRENT_TOOL construction (`0x4b7dcc`) after
  the final head. The caller does not check the wait result.
- `wait_sync` (`0x6426dc`, 316 bytes) can return 1 through its printer-state exit;
  `wait_T_sync` (`0x5117d8`, 364 bytes) similarly has early exits. Disassembly is
  saved in `analysis/validation/2026-11-07-stock-callers/calibration-sync-helpers.asm`.
  Neither helper's name is proof of successful command completion.
- Final stage 13 checks byte `0xe64572d` at `0x4b8574`. Value 1 skips SAVE_CONFIG
  and terminates. Otherwise, any selected option among the three bytes beginning
  at `0x385fa88` reaches SAVE_CONFIG's sender at `0x4b8698`; no selected option
  skips that send. The failure-byte writers and general command-error handling
  still need tracing before this can be treated as a complete failure guard.
- Offset cleanup dispatches PARK_CURRENT_TOOL at `0x4b8478` **before** checking
  that failure byte at `0x4b8498`. Current backend PARK_CURRENT_TOOL rejects
  unresolved docking failure -3, but clears other fail_flag values on entry.

Next: trace the failure-byte writers and command-response path, then implement
and test an operation-wide failure guard if errors can fall through. Do not
infer that r70's corrected physical PID selection fixed worker continuation.
No printer commands were issued for this audit.

### Failure flag ownership resolved — 7 November, after worker audit

The exact vendor symbol table names `0xe64572c` **knife_pairing_ing** and
`0xe64572d` **knife_pairing_failed**. They are not general calibration-success
state. `parse_gcode_response` at `0x63b828` checks pairing_ing == 1 before writing
pairing_failed = 1 (`0x63b848`). Two additional ARM execution cases run this
actual error-latch branch with pairing inactive/active; the inactive case leaves
failure zero, and the active case sets it. All nine worker characterization
cases pass; log: `calibration-worker-tests.log`.

The offset stage initializes pairing_ing=1 and pairing_failed=0 at
`0x4b7f74–0x4b7f8c`, after the PID stage. Therefore the final SAVE_CONFIG check
cannot be considered an operation-wide PID failure latch. The worker's initial
PID G28, per-head selection, centre movement and heater calibration sends have
no command-result admission between them. The wait helper reads
idle_timeout_state against `Printing` and klipper_state against `ready`; it does
not itself prove success of the preceding individual command.

Reference windows and owning symbols are captured in
`calibration-failure-flag-refs.json`; these are direct ADRP/ADD references found
in the scanned text interval, not a claim to exclude all possible indirect
writers. The correction should provide explicit success/error tracking for the
calibration sequence and stop later motion/heating/save after an error. Merely
setting knife_pairing_failed in the PID path is insufficient: the later offset
stage resets it. Existing dock-failure guards remain necessary but do not prove
that the whole calibration sequence succeeds or stops correctly.

### First-run calibration workers (7 November, local follow-up)

Exact client SHA b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715:
`check_auto_level` 0x509ef0/1080 bytes, `check_sharper` 0x50a328/1176,
`check_pid` 0x50a7c0/1804 and `check_knife_pairing` 0x50aecc/1304
contain another 16 direct calls to sender 0x614338. The first-run PID logical
T call is 0x50a964 (return address 0x50a968). Local guard/profile coverage
now includes all of these; caller-specific physical selection remains isolated
from print-file tools. Disassembly and extracted literals are in
`analysis/validation/2026-11-07-stock-callers/guide-calibration-audit.json`
and corresponding `check_*.asm` files.

Workers advance via `async_page_to` 0x553dc0 after waiting; the knife worker
reaches guide_filament_page at 0x50b268. Command rejection alone does not prove
correct first-run completion behavior. Failure-aware continuation and panel
routing remain required, and this local change is not deployed.

#### First-run continuation checkpoint (local candidate)

`async_page_to` schedules the already-hooked `page_to` on the GUI thread. The
three audited first-run destination names are now consumed there before stock
navigation starts the next worker. WM+ sends a tagged M400 using the original
sender and waits for `wmp_recovery.calibration_checkpoint` to echo that token.
Backend publication follows both execution and post-check, so the existing
failure latch also rejects the checkpoint. Local GUI state retains a detected
error even if Klipper restarts; a changed backend session during an outstanding
checkpoint is an interruption, not successful completion. Successful SAVE_CONFIG
restarts occur in the vendor worker before it requests the next-page checkpoint.

The first-run panel covers the full screen and offers no Maintenance BACK route.
The shared explicit Finish remains the only completion-file removal path used
by the replacement filament guide, and it now checks calibration status too.
Native fallback constructor and event routes also pass through the checkpoint.
This supersedes the unresolved navigation implementation note above, but does
not claim live first-run or physical calibration qualification.
