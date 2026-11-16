# Stock touchscreen caller and side-effect audit

Original review: 30 October 2026. Current source reconciliation: 11 November 2026.
The [current managed-behavior audit](#managed-behavior-conflict-audit--11-november-2026)
supersedes historical descriptions of active hooks below. Firmware focus: stock 1.1.13 client ELF SHA256
`b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715`.
Read-only audit of retained binary-analysis evidence; no printer contact,
activation, service restart or production edits.

## Evidence strength and scope

This document distinguishes an established callback/queue path from a command
literal inventory. A command string in a function is evidence to investigate,
not proof that every invocation executes it. Static reachability is not evidence
that a person clicked a control, or that a queued command completed physically.

The detailed recovery paths below have retained disassembly and independent
control-flow review. Other entries come from a focused function/literal/sender
inventory and deliberately leave their full branch and trigger conditions open.
This is not a claim to have audited every client callback or every constructed
command. It also does not substitute for tracing the selected command through
stock macros, WM+ overrides and openACE wrappers.

Local evidence (ignored analysis artifacts, not redistributed vendor code):

- `analysis/runout-guard-review-20261029/review-and-proposal.md`
- `analysis/runout-guard-review-20261029/recovery-caller-literals.json`
- `analysis/runout-guard-review-20261029/handoff/popup-dispatch-table.json`
- `analysis/runout-guard-review-20261029/handoff/client-motion-inventory.json`
- `analysis/runout-guard-review-20261029/_ZL32auto_purge_after_filament_runoutv.asm`
- `analysis/runout-guard-review-20261029/_ZL17pop_event_handlerP11_lv_event_t.asm`
- `analysis/runout-guard-review-20261029/_Z23resume_printing_preparev.asm`
- `analysis/runout-guard-review-20261029/handoff/filament_check_for_resume.asm`
- `analysis/runout-guard-review-r2-20261029/handoff/incoming-second-worker-evidence.md`

## Proven independent recovery paths

### Popup-triggered runout prime

Established static chain:

```text
popup event handler 0x5303e4
  event code 7 + popup userdata 99
  jump-table target 0x531e94
  event object equals btn_pop_btn0 (global 0x386ebe0)
  construct callback; enqueue_event at 0x531ef0
  auto_purge_after_filament_runout() at 0x5328b4
```

The callback is 1168 bytes. It reads the paused physical-head index and saved
resume temperature, then emits:

```gcode
M109 T<paused physical head> S<saved target>
G28 X Y
G1 X-13 Y80 F6000
M83
G92 E0
G1 E100 F400
G1 F6000
```

The heating request is followed by synchronization in the callback. It does
**not** itself issue RESUME. Its apparent purpose is to prime after runout
replacement before continuation. This purpose is inferred from the function,
state and commands, not an independent vendor specification.

Side effects extend beyond the named purge: heating/waiting, X/Y homing, XY
travel, relative extrusion mode, extruder origin reset, 100 mm requested feed and
feedrate change. This callback contains no explicit Z-clearance move, G90 or
save/restore of motion/extrusion state. Downstream homing overrides and the current
modal state determine actual motion. The literals do not prove a wall-contact
mechanism or whether a particular command physically completed.

The paused checker described next can present popup 99, establishing a route to
the popup. **The source of the popup button event during the recorded incident
remains unknown.** Do not attribute it to operator action. The observed API
sequence matches this callback, including WM+'s physical-heater rewrite; receipt
at Moonraker is not proof of physical completion.

### Automatic paused-state replacement and resume

Established static chain:

```text
state_check paused transition
  queue filament_check_for_resume at 0x641074–0x6410b4
  filament_check_for_resume() at 0x61b2c4
  sleep three seconds; require native state still paused
  check current head + runout/tangle flags
  search a cyclic sequence of alternative heads
  qualifying alternative → replacement branch 0x61bab8
  preparation / remapping / purge → set_print_resume at 0x61c244
  set_print_resume() → RESUME
```

The trigger condition includes
`(detector_enabled[current] && !detected[current]) || tangle_pause || runout_pending`.
A qualifying candidate is detected-present and has matching byte 0, byte 1 and
float 4 in the vendor material table (base `0x384d078`, stride 8). These comparisons
are not openACE material approval or evidence of source provenance. There is no
registered-ACE requirement in this path. A current-head runout flag can admit it
even after the current sensor becomes present again.

The replacement branch clears native fault flags, turns off the original head,
changes/persists stock `box_modify` mappings, heats the replacement, issues a
physical-candidate T command, sets its resume temperature, waits until within ten
degrees of the saved target, travels to X-13/Y80, selects relative extrusion,
resets E, requests 100 mm extrusion and resets feedrate. It then calls
`set_print_resume`, which sends RESUME.

If a nonnegative fault head differs from the current head, the worker presents
popup 99/100 and exits. Other branches also present replacement prompts. Thus
there are two distinct outputs: presentation of a replacement prompt, and an
automatic alternative-head preparation/purge/resume sequence. Guarding only the
popup purge callback does not guard the latter.

The initial pause remains a separate path: `filament_check_for_pause` at
`0x61ab5c` calls `pause_printing_handler` at `0x61aef0` and `0x61b09c`.
The resume checker has no PAUSE sender and does not perform initial sensor
sampling. Suppressing it preserves initial detection/pausing, but intentionally
removes its replacement prompts and continuation behavior. This review does not
claim that this second path ran in the reported wall-contact incident.

### Explicit screen Resume preparation

`resume_printing_prepare()` at `0x51a7b4` has a separate stock preparation path.
Retained literals/control-flow evidence show stock mapping lookup/substitution,
`G28 Y`, `G28 X`, physical tool selection, writes to `box_modify_t<n>` and its
backup, busy/tool/hall checks and eventual RESUME. Failure can terminate before
RESUME; the earlier observed “no mappable identical channel” case is consistent
with this gate. `resume_preheat(int)` at `0x51a344` contains M104/M109 requests.

The detailed upstream UI event dispatch into every Resume variant is not
reconstructed here. The callback identity and its preparation effects are
established; it is not the same function as either automatic path above.
`resume_printing_handler` at `0x51b594` also contains RESUME, while
`pause_printing_handler` at `0x51ba5c` contains PAUSE. These are further entry
points to preserve in a complete call graph, not interchangeable proofs of one
linear path.

## Additional caller inventory requiring branch qualification

These rows are verified function/literal/sender observations in the retained
1.1.13 inventory. Unless explicitly stated above, exact UI event, predicate,
execution order and complete prefix/suffix remain to be traced.

| Function / entry | Observed requests | Side-effect scope and caller gap |
|---|---|---|
| Filament `event_handler` `0x529218` | `LOAD_FILAMENT T=`, `UNLOAD_FILAMENT T=` | Screen filament workflow requests full macros, not arbitrary-distance extrusion. Exact event-to-button branches need qualification. |
| `auto_fila_in` `0x4f9428` | G28; `G0 X-13 Y232 F6000`; `EXTRUDE_FILAMENT T=`; M104 T | Loading helper can home/travel before entering a macro and alter heat afterward. Full caller predicates and dynamic temperatures remain open. |
| `auto_fila_out` `0x4f9808` | `RETRACT_FILAMENT` | Helper delegates to a macro whose actual implementation decides whether this is full unload, shaping and travel. Other dynamic requests may exist. |
| `guide_filament_load` `0x50e83c` | M104 T; G28; G90; `G1 X-13 Y232 F6000`; M109 T; `EXTRUDE_FILAMENT T=` | Wizard has its own heat/homing/travel prefix. Wrapping only final extrusion does not own preparation. |
| `guide_filament_load_retry` `0x50ecf0` | G28; M109 T; `EXTRUDE_FILAMENT T=` | Retry can repeat preparation. Full trigger/duplicate-admission conditions remain open. |
| `start_nozzle_setting` `0x510350` | G28 | Nozzle/setup operation can home; remaining branch effects need review. |
| `fix_position` `0x5133e0` | G28; `G0 X150 Y150 F6000`; G91; `G1 Z10 F1200`; G90 | Explicit homing, center travel, relative Z motion and mode changes. No assertion here about ordering on every branch. |
| `auto_checking` `0x4b7558` | G28; `G1 X150 Y150` | Automated check path includes motion; needs exact caller and checkpoint interpretation. |
| `check_sharper` `0x50a328` | G28 | Calibration/check helper includes homing; name alone does not establish full function. |
| `check_pid` `0x50a7c0` | G28; `G1 X150 Y150` | PID-related helper also has positioning, so is not merely a heater operation. Heating/PID requests need full dynamic extraction. |
| `check_knife_pairing` `0x50aecc` | G28 | Pairing/check workflow can home. |
| `knife_pairing_event_handler` `0x4c6490` | G91; `G0 Z+`; G90; `G0 Z-` | Event branches construct relative Z moves and restore absolute mode. Exact button/step predicates not qualified here. |
| Unresolved `event_handler` `0x4b4768` / `0x4c41a4` | G28 | Do not assign screen names from generic local symbol names. Resolve event registration and widget identity first. |
| Unresolved `event_handler` `0x50c9bc` | M104 T | Physical heater request path; UI event binding remains open. |
| `move` `0x614a0c` | G91 | Relative movement helper. Full axis/distance/feedrate construction and mode restoration require inspection. |
| `set_print_pause` `0x6141c4` / `set_print_resume` `0x614240` | PAUSE / RESUME | Low-level senders with multiple possible callers. Guarding Resume here is too late for callers that already moved/heated. |
| `start_plr_print` `0x62d91c` | G91; G90; G28; M83; G92 E0 | Power-loss recovery has separate motion/modal-state setup; current recovery patch does not prove object-safe paths. |
| `setup_screen_main` `0x51bf8c`; `update_tips_and_btns` `0x51e898` | PAUSE; latter also RESUME | May include labels/state wiring as well as requests. Literal presence alone cannot establish physical dispatch. |

The inventory also reports restart log literals inside static initialization and
logging functions. These are not additional proven service-restart callers.
Only the established `main` startup path below is classified that way.

## Filament onboarding branch follow-up (7 November 2026)

Offline review of the exact 1.1.13 client identifies the wizard event handler
at `0x50c9bc` (1672 bytes). It accepts CLICKED (event 7), then branches on event
user data. This is a separate entry from the normal Filament screen handler.

- Action **0** runs `rm /home/t13dp/need_oobe -f`, then navigates to
  `main_page`. A replacement must preserve intentional setup completion;
  merely redirecting away from the wizard leaves its first-run marker behind.
- Action **1** clears the guide container and draws the next introduction panel.
- Actions **2 and 3** share a branch at `0x50cac0`. If the previous
  `load_extruder_index` (`0x384d8ac`) is nonnegative, it sends `M104 T<index> S0`
  **before** advancing to the next head. For remaining heads it increments the
  index, redraws the guide, and queues `guide_filament_load` through
  `enqueue_event` (`0x655874`) at `0x50cd34`. On the final-head branch it resets
  guide state, requests G-code metadata, and navigates to `filelist_local_page`.
  This branch is not simply a Load button or an immediate print command.
- Action **4** queues `guide_filament_load_retry` through the same queue at
  `0x50ced8`; it does not pass through the normal filament editor.

The workers at `0x50e83c` and `0x50ecf0` contain their own G-code send calls,
including the preparation documented above. Hooking only these workers misses
the event handler's heater command and state changes. Hooking only
`EXTRUDE_FILAMENT` misses both preparation layers.

Evidence is retained in `analysis/validation/2026-11-07-first-run/`:
`guide-region.asm`, `guide-functions.asm`, and `entry-audit.json`.
`tools/inspect_stock_onboarding.py` reproduces the symbol sizes, function hashes,
direct call addresses and navigation literals, rejecting any other client hash.
The disassembly establishes static branch behavior; it does not establish live
event registration, duplicate-click behavior, or successful setup completion.

G03 remains open. Integration must intercept before this event handler's machine
effects, present the shared source/editor/procedure flow, preserve explicit
completion of first-run setup, and prevent a return/retry from replaying old
queued work. Do not install a worker-only redirect or silently mark setup done.

The subsequent local implementation intercepts `guide_filament_page` navigation
and `setup_screen_guide_filament` construction, opening the shared Filament page.
It also replaces the old guide event handler and both queued workers, so neither
the event's prior-head heater-off command nor worker preparation is retained.
These replacement-only entries do not get trampolines: the setup and retry
prologues contain ADRP instructions. All four new entry windows are bound in the
verified 1.1.13 native profile.

FINISH is an explicit shared-screen footer action. It requires fresh idle status
and no unresolved filament/toolhead/owner operation, removes only the known
`need_oobe` marker, then navigates Home. A filesystem failure leaves onboarding
active for retry. Finishing does not require every head to contain filament,
matching the stock wizard's explicit completion/skip path. Native tests cover
stale/hidden/duplicate button events, busy/paused refusal, and completion retry.
This is not yet deployed or live-qualified and does not prove a queued worker
already executing before activation could be interrupted safely; activation must
continue to require an idle printer with no in-flight procedure.

## Service startup is a machine-state operation

The stock native client's `main` at `0x449c60` executes
`systemctl restart klipper` during startup (string at `0x86a350`, referenced at `0x44a438`).
Restarting the touchscreen client therefore cannot be treated as a UI-only refresh.
It can destroy a paused job's live Klipper state. UI activation needs its own idle
and operator-approved restart procedure; source review or dependency validation
is not permission to activate during a paused print.

## WM+ interception boundary and residual coverage

[Current preload documentation](../client-preload/README.md#openace-compatibility)
describes these distinct policies:

- Screen Resume preparation bypasses stock when openACE detection succeeds.
  Existing cached detection can fall back to stock on a failed query. Do not
  generalize the newer strict recovery-callback policy to this older hook.
- Simple client-issued physical `M104/M109` requests with S and T are rewritten
  to an explicit heater, with M109 waiting within ±2.5°C. This changes heater
  interpretation, not ownership of the surrounding movement sequence. Unknown
  parameters/out-of-range heads pass through. Sliced-file commands use a different
  path and retain virtual tool semantics.
- The two whole-callback recovery guards suppress runout purge and paused
  replacement when openACE is present or presence is unknown; fresh definitive
  absence invokes original stock behavior. They do not generate purge receipts,
  clear backend holds, force RESUME or suppress the separate initial pause path.

These are source/documented policies. This audit did not verify the installed
artifact or whether either guard is active on the current process. The historical
first guard report predates the second-worker fix; its statement that the checker
is unguarded must not override the later R2 review/current source.

## Consequences for the new screens and next audit

A new control should issue a reviewed operation intent to the current owner.
Calling a vendor helper because its name resembles the new button can introduce
homing, tool changes, heating, modal resets, purge or automatic continuation.
The owned boundary must precede the earliest such side effect, not merely wrap
the last macro or the eventual RESUME.

Next focused static passes should establish widget/event registrations and all
constructed command strings for the filament handler, auto load/unload helpers,
wizard/retry and Take/Release controls. Trace each resulting command through the
stock macro body, WM+ live override and openACE wrapper. Record unconditional
prefixes separately from state-dependent branches, especially stock mapping
writes, G28, heater T addressing, mode changes and calls that can resume a job.
Keep literal-only leads marked incomplete until that control-flow evidence exists.

## 1.1.13 Nozzle Flow follow-up — 7 November 2026

Offline review of the exact supported client SHA
`b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715`
found another unconverted filament-service caller. Nozzle Flow's event handler
at `0x529218` (784 bytes) handles CLICKED (7): userdata 1–4 selects physical
index 0–3 for Load; userdata 5–8 selects index 0–3 for Unload. Userdata 0 is Back.
Load tests a stock per-head byte before dispatch. The service branches send:

1. `SAVE_VARIABLE VARIABLE=if_check_extruder_status value=0`.
2. `LOAD_FILAMENT T=<index>` or `UNLOAD_FILAMENT T=<index>`.
3. `SAVE_VARIABLE VARIABLE=if_check_extruder_status value=1`.

These are direct calls to the stock G-code sender (`0x614338`); the load command
call is `0x529320`, unload `0x5293e4`. The handler does not enter the new staged
service UI or backend admission. Current live-config source macros still select
an extruder directly and heat to 220 C; LOAD uses the old 100 mm distance. This
is **not** evidence that the new 55 mm feed / purge / wipe flow is used here.
The physical-index argument also reaches a heater macro using logical mapping.

G05 must route or explicitly retire these service actions before acceptance,
including consuming the original event before its status-check-disable prefix.
Preserve Back and unrelated nozzle-flow settings. Do not test these old buttons
on hardware as part of unattended UI navigation.

Evidence: `analysis/validation/2026-11-07-stock-callers/nozzle-flow-event.asm`
and `client-motion-inventory.json`. The inventory is a literal/direct-call aid;
conditional ordering is established by the saved disassembly, and indirect
callers still need review.

### Local Nozzle Flow integration candidate

The new `stock_service_event.hpp` consumes service clicks 1–8 before the vendor
handler. Valid visible Back (0) still delegates to stock. Non-click, unknown,
hidden and deleted-control events cannot reach the original handler. The event
hook's first 16 bytes are stack/register-only and use a reviewed trampoline for
Back; its full entry window is included in the verified 1.1.13 native profile.

The runtime queues head-specific UI navigation only. With fresh ownership it
opens the shared external Load editor or Unload confirmation; ACE-managed Load
keeps the existing instruction to choose a slot. Shared backend admission,
explicit submission, progress and loaded-state tracking remain authoritative.
No direct macro alias or automatic machine command was added. Stale requests
are discarded rather than replayed when status recovers.

Native tests pass for all four physical head indices, Load and Unload routes,
no submission during navigation, stale/no-replay behavior and hidden/deleted
legacy callbacks. The full offline suite passed (32 tests; loopback-only test excluded), the ARM
build succeeded, and all nine package checks passed. UI-only r66 is deployed and ready; live callback navigation verification
is pending. Candidate SHA256:
`e76f1ab665a6cb1ef3eadd697d308b902d740bb6e263224658314ab8f93fad0e`
(build ID `0449c7570c5257f4`).

### r66 live callback verification and service-page follow-up

Normal navigation is General → Maintenance → Feed & Discharge. The Maintenance
entry handler at `0x4b4768`, userdata 7, only navigates to `nozzle_flow_page`;
its calibration START/PROBE branches were not invoked. In-memory inspection
verified that `0x529218` jumps to the loaded `unified_nozzle_flow_event` symbol.
H3 Unload then opened the shared H3 confirmation, including the unknown-Z
prerequisite. CANCEL returned to H3 tool controls. Command history had no new
commands, position and status-check flag were unchanged, all heater targets
stayed zero, and both filament-file hashes matched the baseline.

The old page still disables Load using stock sensor state, which disagrees with
WM+'s distinction between present-at-gears and loaded. The next candidate routes
`nozzle_flow_page` navigation to the shared filament cards directly. This page
has no separate nozzle calibration/settings controls to retain. Other service
and calibration pages keep their own routes. Per-button interception remains a
fallback for any legacy callback. Focused tests, ARM build and nine package checks for that navigation change
passed. Deployed r67 now passes live Maintenance entry navigation: Feed &
Discharge opens shared cards, H1 Load opens the guarded editor, and CANCEL
returns to cards. Before/after command history contains no new G-code command;
position, status-check flag and saved filament files are unchanged, targets
remain zero and no filament operation exists. This verifies navigation only.

Evidence: `activation-stockwidgets-r66/live-service-hook.json`,
`service-navigation-verification.json`, and the `legacy-h3-unload-*.png` captures.

The r67 captures and before/after verification are in
`analysis/unified-ui-native/activation-stockwidgets-r67/`, including
`service-navigation-verification.json` and `service-entry.png`.


### Maintenance preparation admission — local candidate after r67

The exact 1.1.13 event at `0x4b4768` maps userdata 0 to START and userdata 8
to PROBE_CALIBRATE. START sets a worker state and opens `auto_checking_page`.
The probe branch conditionally sends G28 at `0x4b4a10`, then sends logical T0 at
`0x4b4a4c` and PROBE_CALIBRATE at `0x4b4a88`, then opens the probe page. These
commands precede the backend macro guards. Evidence: `auto-check-prepare-event.asm`
and `maintenance-entry-literals.json` under the current stock-callers directory.

The local native candidate wraps this callback before vendor dispatch. START and
probe require fresh known-owner idle status, no local outstanding receipt/review,
and no pending/running/unknown or unrecovered failed operation. Unavailable
admission uses the stock busy popup (62). Back, selections and Feed & Discharge
remain delegated; hidden/deleted/nonclick events are consumed without invoking
admission or dispatch. Exceptions never fall back to the vendor callback.
The profile includes the verified 16-byte entry window; it contains only stack
and register stores and can be copied into the existing trampoline mechanism.

Focused native runtime/lifetime tests passed (2 tests, 32.45 seconds), including
stale, printing, paused, unknown owner, operation conflicts and retained navigation.
This guard is local and not deployed. The probe branch's logical T0 prefix still
requires physical-reference correction; guarding idle entry does not resolve
that mapping defect. G05 remains open.

The ARM build and all nine review-package checks also passed. Candidate SHA256:
`b8799f38f2ba167cfdce54980ce0d0cb33ac8a683e39c111a4106d508c43f6d0`.
Logs: `maintenance-gate-{tests,build,package,package-tests}.log` in the same
evidence directory. The installed printer remains r67.


### Physical probe preparation replacement — local follow-up

After admission, userdata 8 is now consumed and replaced, never delegated to the
vendor G28/T0 prefix. It sends one `_WMP_PROBE_CALIBRATE` command through the
existing stock `run_a_gcode(std::string)` API (`0x614338`) and opens the same
`probe_calibrate_page`. START and nonphysical navigation retain their guarded
stock routes. The verified symbol signature establishes the sender ABI.

The new backend macro rejects printing/paused jobs, toolhead faults and an
unresolved power-recovery homing mode before dispatch. It issues `G28 P0` (the
traditional letter-parameter syntax), making physical T0 the explicit full-home
reference, followed by PROBE_CALIBRATE. This avoids establishing a datum with
one head and then selecting a remapped logical T0. The existing full-homing
selector validates attachment sensors; the manual probe macro remains unchanged.

Validation: **57 recovery-model tests**, **2 native runtime/lifecycle tests**,
ARM build and **9 review-package tests** passed. New model tests cover all four
initial mounted heads with logical T0 mapped to physical Head 3, command ordering,
active-job/fault rejection and power-recovery rejection. Manual probing is an
opaque hardware endpoint in this model; it was not executed on the printer.
Logs/source hashes: `probe-prefix-*.log` and `probe-prefix-candidate-hashes.json`
in the stock-callers directory. UI SHA256:
`f835c162ac77ab09f1a44114ec219c90d98c4bc3ade9bfec5f05bae288dab945`.

This remains local. Deployment must install the matching macros and UI together;
r67 does not contain the new backend command. The probe mapping defect is fixed
in this candidate, while G05's other calibration worker branches and physical
qualification remain open.

## Factory/service residual callers — current r74 audit, 7 November

Exact-client symbol review resolves the previously unnamed callback `0x4c41a4`
as the event handler adjacent to `setup_screen_factory_mode` at `0x4c4c3c`.
`knife_pairing_event_handler` is `0x4c6490`, with its drawer at `0x4c6c44`.
Retained evidence: `factory-callbacks.asm` and `factory-audit.json` in
`analysis/validation/2026-11-07-stock-callers/`. The JSON binds the exact client
and function hashes, direct command-sender calls, and adjacent ADRP/ADD literals.
Literal extraction alone is not button registration or dynamic branch proof.

The factory event has ten direct calls to sender `0x614338`. Its probe sequence
at `0x4c47dc`, `0x4c4818`, `0x4c4854` constructs G28, T0, PROBE_CALIBRATE.
Other command literals include `_LEVELING_TRIGGER`, `_GANTRY_TRIGGER`, stepper
X/Y disable, `CALIBRATE_TOOL_POSITION T=`, and `CALIBRATE_WIPE_POSITION`.
The separate `factory_mode_pass` helper at `0x4c411c` sends `_LEVELING_TRIGGER`
at `0x4c415c`; its name must not be mistaken for a password/access check.
The knife event contains eight direct sends, with relative Z jog, G90, M84 and
`SAVE_VARIABLE VARIABLE=probe_position VALUE=` construction.

These return addresses are absent from r74's `calibration_senders` set in
`stock_maintenance_command.hpp`; the Maintenance event wrapper covers a different
callback (`0x4b4768`). Existing backend macro guards still apply to their named
commands, but that does not establish admission before the factory G28/T0 prefix
or direct jog/save commands. S15 explicitly retains controlled service access,
so these routes cannot be excluded from G05 merely because they are factory UI.

Next qualification must establish entry/event registration and action identities,
then ensure physical-reference preparation and idle/ownership admission precede
these effects. Do not add every factory command to the calibration worker latch
without reviewing its lifecycle: direct jog and persistent probe-position editing
have different completion semantics. No factory screen or command was invoked.

### Factory action registration and executed branch evidence

`tests/test_stock_factory_worker.py` executes the exact vendor ARM instructions
under Unicorn with LVGL/string/sender endpoints modeled; no printer/native client
is run. All 11 cases pass. Factory setup's loop at `0x4c5b60–0x4c5ddc` registers
userdata 9 through 14, event code 7, callback `0x4c41a4`. Thus action 12's probe
branch is wired by the constructor, not merely an unreferenced command literal.
Executing that branch emits G28 only when its condition requests homing, then
always T0 and PROBE_CALIBRATE before calling the probe drawer at `0x4c4874`.
This does not prove downstream physical execution or live factory entry access.

Executed dispatch cases identify factory action 10 at `0x4c46cc`, probe action 12
at `0x4c4794`, tool-position action 13 at `0x4c487c`, and wipe-position action 14
at `0x4c4904`. Knife event dispatch identifies 6/7 as positive/negative Z jog,
8 as panel-close, and 9 as the M84/probe-position persistence branch. Actions 0–5
select a step from the stock float table. The jog handlers update their displayed
position before sending movement, so sender-only command rejection cannot by
itself keep this editor's position/persistence state truthful.


### Knife editor admission — local candidate, 8 November 2026

The candidate now wraps `knife_pairing_event_handler` at `0x4c6490` before
vendor dispatch. Actions 6/7 (Z jog) and 9 (motor disable and probe-position save)
require the same fresh, idle, known-owner admission as Maintenance. Rejection
occurs before the editor mutates its displayed position. Distance selection
0–5 and Close 8 remain available while busy. Hidden, detached, deleted, invalid,
and non-click events are consumed. The generated exact-client profile includes
the new entry; the copied 16-byte prologue contains no PC-relative instructions.

Native lifecycle regression covers admission and unchanged vendor dispatch on
rejection, plus navigation and stale-object cases. Exact ARM dispatch tests
identify the protected actions independently of the wrapper. This does not
prove physical calibration, a queued-command race, or live deployment. Factory
preparation (including its G28/T0 prefix), confirmation callbacks and downstream
probe-editor lifecycle still need coverage. Do not count G05 closed.

Terminology correction: “probe button” in previous progress reports referred to
a stock calibration code path. The factory constructor registers that action,
but its live access path and visible label have not been verified.


### Factory preparation wrapper and probe-editor follow-up — 8 November 2026

The local candidate wraps Factory Mode event `0x4c41a4`. Actions 8/9 (trigger
mode), 10 (knife preparation), 12 (probe), 13 (tool position), and 14 (wipe
position) require fresh idle/known-owner admission before vendor mutation or
commands. The probe action sends `_WMP_PROBE_CALIBRATE` and calls the original
embedded drawer `0x4c80a8` using its original parent `0x3861c68`; it does not
substitute Maintenance page navigation. Both function windows are profile-bound.
Unknown/unused action 11 and stale events are consumed. Other recognized actions
retain their navigation/selection/confirmation behavior; later confirmation
handlers are not claimed to be covered by this event wrapper.

Native lifecycle tests cover rejected/admitted machine actions, navigation,
invalid/hidden/deleted/detached targets, and one-command preparation before the
embedded editor. Exact ARM tests additionally execute the 8/9 dispatch branches.

New disassembly in `analysis/validation/2026-11-08-knife-admission/probe-editors.asm`
identifies both factory (`0x4c76dc`) and Maintenance (`0x53d150`) probe editors.
Actions 0–11 issue TESTZ steps of +/- 1, 0.1, 0.05, 0.025, 0.01, 0.005 after
changing a local display value. Action 12 sends ABORT; action 13 sends ACCEPT
immediately followed by SAVE_CONFIG, without waiting for backend acceptance,
then sleeps/polls inside the UI event callback. The four exact ARM abort/save
regressions stop before the blocking wait and verify command order.

Remaining work must replace that blocking completion and bind editing/saving to
the active backend manual-probe session. Preparation admission alone does not
establish these guarantees. The independent factory_mode_pass trigger and other
factory confirmation handlers also remain under review. No factory motion,
calibration, saving, or printer deployment was performed for this local change.


### Main-track priority correction — 8 November 2026

Per the user, complete the main filament/toolhead track before reporting stock,
factory and other screen conflicts. The local knife/Factory Mode hooks above
were archived in `analysis/deferred/2026-11-08-factory-calibration/` and removed
from active native sources. They were never deployed. Earlier entries describe
that experimental candidate, not current release behavior. Retain the ARM audit
evidence for the later conflict report; do not present probe-editor refactoring
as a prerequisite for validating the agreed filament screens.

### Onboarding completion bypass through Local files — 8 November

The exact 1.1.13 file-browser constructor has another first-run side effect:
`setup_screen_filelist_local` checks `/home/t13dp/need_oobe` at `0x4fd488`,
then constructs `rm /home/t13dp/need_oobe -f` and sends it to the shell helper.
This is independent of the wizard's Finish event. WM+'s shared setup page makes
normal navigation available, so forwarding Local files during setup could clear
the marker without the admitted FINISH callback.

The local correction intercepts `filelist_local_page` navigation while WM+
onboarding is active and requests the shared filament page with a Finish-first
message. It does not invoke completion, shell commands, motion or heating.
Outside onboarding, including after a successful FINISH, the stock route remains
unchanged. The focused native lifecycle test exercises both cases and preserves
the existing busy/stale/failed-completion checks. Firmware evidence is retained
in `2026-11-08-main-track/onboarding-file-navigation/local-files-marker.asm`.

Startup has a separate marker gate in `mks_page_register`: it enters
`guide_language_page` when `need_oobe` exists and
`printer_data/gcodes/USB/factory_update` does not; otherwise it enters Home.
Evidence: `startup-marker.asm` in the same directory. Merely creating the marker
would therefore enter the whole stock wizard, not directly qualify the replaced
filament step. No marker was created, reset invoked, or calibration started.
The inspected General / Other functions menus did not expose a direct filament
wizard entry. This is bounded navigation evidence, not a claim about every
factory menu or a live FINISH/reboot pass.

### First-run route prerequisites — 8 November follow-up

The expanded exact-client inspector now records six preceding wizard handlers,
with symbol-size verification and function hashes. Read the retained disassembly
as control-flow evidence, not a live wizard pass:

- Language handler `0x50f0a4`, action 0: `guide_wifi_page`; choosing a language
  writes the language preference and returns to the language page.
- Wi-Fi handler `0x513c64`: back goes to language; the forward branch at
  `0x513cc4` goes to `guide_unlock_the_heated_bed_page`.
- Bed-unlock handler `0x512fd4`: the first click advances instructions; its next
  action goes to `guide_nozzle_setting_page` at `0x5130a8`. WM+ replaces that
  identification screen, but reaching it does not establish completion.
- Calibration selection handler `0x50b7f8`: the skip branch invokes a shell
  command and goes Home; the start branch chooses a selected calibration index
  and goes to `guide_calibrating_page`. Clearing every selection does not itself
  jump to filament: the same calibrating destination remains.
- Calibration-finish handler `0x50c3fc`, action 0: `guide_filament_page`. This is
  the proven forward entry to the replaced filament step.

There is therefore no established non-reset direct UI route to that final step
in the inspected handlers. Creating `need_oobe` and navigating the ordinary
wizard is not a focused FINISH-only check: it also enters identification and
calibration setup. Do not mark G03 passed using a shared Filament-screen visit,
a marker deletion alone, or a synthetic call that skips the actual entry path.
No marker, live settings, identification or calibration was changed by this audit.
A controlled first-run environment or a separately scoped setup run remains
necessary for end-to-end FINISH/reboot acceptance.

Reproduction: `tools/inspect_stock_onboarding.py <exact-client>`. Evidence:
`analysis/validation/2026-11-08-main-track/onboarding-route/` (entry audit and six
handler disassemblies). The normal printer remains on the accepted r108 runtime.


## Managed-behavior conflict audit — 11 November 2026

Scope: current `feature/standalone-ui` sources following r116, the exact stock
1.1.13 ELF named above, retained ARM branch evidence, and vendor scripts from
that firmware payload. This is a read-only behavior audit: no machine operation,
restart, configuration write, or new physical qualification was performed.
The user's new audit request supersedes the earlier instruction to defer this
report until after main-track validation. Experimental factory hooks remain
archived, not active. Arbitrary administrator G-code is not treated as a security
boundary; the findings concern supported stock workflows that can bypass the
managed UI/backend contracts.

Implementation has progressed since this audit snapshot. See the
[current R20–R27 checklist](ui/standalone-completion.md#current-audit-follow-up--11-november)
for deployed fixes, local prerequisites and remaining acceptance. The findings
below describe the audited stock paths, not a claim that every bypass remains.

### Open conflicts, in recommended order

| ID | Priority | Stock entry / trigger | Conflict with managed ownership | Recommended disposition |
|---|---|---|---|---|
| C01 | High | Completion/stopped popup Re-print | Restores vendor tool mappings and starts the file directly, bypassing a fresh managed source review and `WMP_START_PRINT` admission. | Route Re-print to the managed preview for that file. Revalidate mappings, current loaded identities and file identity before submission. Do not silently replay the previous source selection. |
| C02 | High | Public legacy filament macros | Independent heat/feed/retract sequences bypass operation ownership, loaded-state updates, material-transition policy and structured cancellation/progress. | Replace supported legacy entry points with explicit managed adapters, or reject them with a route to managed Load/Unload. Preserve documented physical-head semantics; do not blindly alias `T` through print mapping. |
| C03 | High | Power-loss Continue | Checkpoint/mesh/offset checks exist, but successful validation delegates to stock recovery. It is not the managed paused-service admission path and does not establish current filament readiness. | Add an early managed recovery admission step before stock preparation, or replace preparation with one owned operation. Preserve checkpoint verification and object-safe recovery geometry. |
| C04 | High | Restore factory settings / topology configuration scripts | Can overwrite macros, sensor callbacks, includes and calibration independently of managed ownership; partial setup can leave the screen/helper active against different macro contracts. | Route reset/topology changes through an idle-only transactional workflow with backups, explicit scope, preservation/migration of calibration and revalidation before controls become available. |
| C05 | Medium–high | Factory Mode, knife/probe editor actions | Preparation, direct jog and persistence paths are outside the current Maintenance worker wrapper. Local editor values can change before a refused command; save queues ACCEPT then SAVE_CONFIG without acknowledged success. | Gate before UI mutation, bind the editor to a backend calibration session, and acknowledge ACCEPT before persistence/restart. Keep navigation and Close usable. |
| C06 | Medium–high | Tool-change / park failure branches other than trapped-dock `-3` | Stock retries clear failure flags and may home/travel before pausing, outside the structured recovery decision. | Review each failure class and stop with a retained fault when attachment is uncertain. Any approved retry should be an explicit managed recovery operation, not a generic retry for all nonzero codes. |
| C07 | Medium–high | Client startup and other restart controls | Starting the stock client restarts Klipper, invalidating a live pause and machine reference. Installer admission protects planned deployments, not every external service restart or stock warning action. | Keep deployment idle checks; audit restart actions against managed running/paused/unknown states, and make restart consequences explicit. Do not automatically restart to clear a recoverable UI error. |

### Evidence and limits for the open conflicts

**C01 — Re-print is a separate start path.** Fresh disassembly of the verified
ELF decodes the popup jump table at `0x87c9b0`: userdata 6 enters `0x5305b0`
(completed), userdata 5 enters `0x530a2c` (stopped). The alternate-button branches
compare against `btn_pop_btn1` at `0x386ebe8`. The completed branch logs Re-print,
sets the stock loading flag, restores mappings/backups and mesh, then calls
`start_printing` at `0x530a1c`; the stopped branch calls it at `0x530ea8`.
`start_printing` (`0x6146b8`) constructs `json_print_a_file` and calls
`WebSocketClient::send`, rather than the hooked G-code command sender. Current
`unified_draw_pop` redirects only 99/100; the installation table does not replace
these popup branches or `start_printing`. Current preview hooks therefore do not
establish ownership of Re-print. This is a confirmed static bypass, not a claim
that a new print was started during this audit. File-local START_PRINT safeguards
still run; they are not equivalent to source/loaded-state admission.

**C02 — the old macro API remains live in the configuration source.**
`config/live/macros.cfg` still defines `LOAD_FILAMENT` (100 mm, hard-coded 220°C)
and `UNLOAD_FILAMENT` (220°C and tip shaping), with direct ACTIVATE_EXTRUDER,
modal changes and motor disable. Neither calls `WMP_FILAMENT_SEQUENCE` nor
updates the managed loaded flag. `EXTRUDE_FILAMENT`, `RETRACT_FILAMENT`,
`filament_insert_gcode` and `filament_insert` are additional legacy entry points.
Their `_WMP_FILAMENT_SERVICE_POSITION` helper requires XYZ homing and moves Z,
unlike the managed XY-only service. Some positioning guards exist, so these are
not all wholly unguarded; they nevertheless do not share the managed operation
contract. Main/Nozzle Flow/wizard redirects protect the replaced UI paths, but do
not retire these public macros or prove that every old caller is unreachable.

**C03 — checkpoint correctness is not filament ownership.**
`client-preload/recovery-fix/wmp_recoveryfix.c::start_recovery` verifies the
checkpoint sidecar/hash, then calls `original_start()`. Current
`_WMP_RECOVERY_BEGIN` validates saved mesh, calibration offsets and mapping;
recovery `M24` verifies file/mesh/probing head and restores mappings before
`M9924`. Only the already-paused standalone branch routes through RESUME and
`WMP_CHECK_RESUME`. After power loss there is no live pause origin to validate.
The stock recovery function has its own heating/tool/motion sequence. Missing
admission therefore concerns current loaded records, changed material/source,
unknown/unfinished operations and ownership before preparation. Existing recovery
fixes must be retained, not described as absent or discarded. Physical PLR and
object clearance were not tested here.

**C04 — direct file writers bypass native command hooks.** The retained vendor
`restore_factory_settings.sh` copies factory `macros.cfg`, `change_macros.cfg`,
extruder/sensor configs, Moonraker config, offsets and `tmt1.ini` over live files.
`canbus_query.py` selects a printer template when the discovered head count
changes and invokes `replace_save_config.sh`; that script copies `printerN.cfg`
and filters saved extruder calibration sections for excluded heads. This is an
independent destructive capability even though WM+ now blocks the known automatic
`unlock_extruder` fault callback and replaces the identification worker. Those
specific fixes are not a global guard on shell script execution. The script
behavior is proven from the retained firmware; not every live menu or update
caller is traced, and this audit does not attribute another PID-loss incident to
a particular invocation. Firmware update/reinstallation can also replace managed
files, but each update path needs its own caller/transaction review before a
specific runtime claim is made.

Additional source-confirmed C04 ordering defects: `replace_save_config.sh` copies
the selected template over live `printer.cfg` **before** checking whether
`save_config.cfg` exists or is readable. A missing input can therefore report
failure after replacing the live configuration. Invalid head counts fall back
to the four-head template. For a smaller count it rewrites `save_config.cfg` to
remove excluded extruder sections, then appends it and deletes the source file.
`restore_factory_settings.sh` has its backup command commented out and performs
sequential copies without a transaction or rollback. These are retained-source
findings, not a reproduced live incident. R23 must test failure before mutation,
recoverable originals and partial-commit recovery using disposable files.

Disposable execution evidence: `tests/test_vendor_config_writer_failures.py`
pins both retained scripts by SHA-256 and relocates only their hardcoded home
prefix. Four tests reproduce overwrite-before-input-validation, invalid-count
fallback, loss of removed-head calibration/source on shrink, and partial factory
restore. The last case also proves that a successful final copy can yield exit
status zero despite earlier failed copies. A shell success code alone is therefore
not a valid postcondition. These characterize stock defects, not managed-fix
acceptance; no printer files were accessed.

Caller trace: retained `canbus_query.py::set_thr_uuid` invokes
`get_save_config.sh`, independently copies the selected printer template, then
invokes `replace_save_config.sh`. Neither subprocess return code gates subsequent
UUID writes. A helper-only replacement therefore cannot close C04. The discovery
caller and its earlier template copy must participate in the same reviewed
transaction. This is source evidence; no live discovery/reset was executed.

Native reset entry evidence (11 November): retained
`restore_factory_settings()` at `0x548078` calls `reset_plr_files` (`0x5480f0`),
`delete_all_jobs` (`0x5480f4`) and `format_gcode_local_with_pop` (`0x5480f8`)
**before its first shell dispatch**, `clear_memory.sh` at `0x54812c`. The later
restore-script dispatch is at `0x5484b8`. Therefore interception of the restore
script, or even all shell commands, is too late to protect recovery/job/file
state. Admission and transaction ownership must begin before this native worker's
first effect, including its non-shell cleanup calls.

`tests/test_stock_factory_reset_boundary.py` executes that pinned ARM prefix in
Unicorn with every external call stubbed and stops at the first shell dispatch.
It confirms the three preceding calls in order. Together with the four disposable
script tests, **5 checks pass**. This is characterization of the retained reset
boundary, not a claim that managed reset is implemented or a live reset test.
Caller follow-up: popup kind **21** dispatches to `0x5313d8`. Its affirmative
branch first calls `draw_pop(22)` at `0x5313f8`, constructs the reset callback
pointer at `0x531404`, then calls `enqueue_event` at `0x53143c`. A worker-only
refusal would leave the stock progress popup behind. The local native event hook
now intercepts only a live affirmative reset click before that prefix, dismisses
its own confirmation and queues the same refusal notice. Cancel still delegates;
stale, hidden, duplicate and non-click events cannot dismiss another popup or
queue work. The direct worker replacement remains necessary for non-popup entry.
Host event tests cover these cases and preserve Re-print/unrelated dispatch.

A local candidate now replaces this profiled worker entry completely and queues
a GUI-thread refusal notice; it never delegates to the old worker. Built ARM
execution verifies only the notice flag write (or no writes without runtime).
Host lifecycle tests verify retained presentation and dismissal without backend
calls. This guard is not deployed and does not intercept external script callers.

The full reset transaction must also specify whether job files/recovery records
are preserved, exported or explicitly discarded; it cannot inherit this silent
prefix while only protecting calibration writes.

The managed `MappingTransaction` avoids vendor template copying but currently
changes only UUID fields. It therefore does not itself establish that PID tuning
follows a physical heater after a permutation. A local pure saved-PID planner now
covers that transformation; effective configuration provenance and joint
UUID/calibration/managed-state publication remain R23 integration requirements.

**C05 — factory/service controls are distinct from Maintenance.**
The exact ARM tests and registration evidence above establish Factory Mode
callback `0x4c41a4`, actions 9–14, including the conditional G28 followed by T0
and PROBE_CALIBRATE for action 12. These sender addresses are absent from current
`stock_maintenance_command.hpp::calibration_senders`; the experimental factory
wrappers are absent from the bootstrap installation table. A logical T0 can
select a remapped physical head, while the intended calibration reference is
physical. Knife actions 6/7 mutate display state then jog Z; action 9 disables
motors and persists probe position. Both probe editors send ACCEPT followed by
SAVE_CONFIG and wait inside their UI callback. Backend macro guards still apply
where present, but do not own the preceding vendor UI mutations or every direct
command. Live menu access/visible labels remain unverified: this report does not
assert that a user-visible control is named “Probe.”

**C06 — some automatic homing retries remain intentional stock behavior.**
`_CHECK_CHANGE_TOOL` rejects `fail_flag == -3`, but for other errors its first
retry clears the flag and re-enters `_CHANGING_TOOL`; after the next failure while
printing, it sends G28 X Y, travel and PAUSE before eventually clearing failure.
`PARK_CURRENT_TOOL_RETRY` likewise rejects -3 but homes and retries other nonzero
flags. The trapped-dock fix remains valid. This is not evidence that every other
failure is unsafe; the conflict is the blanket recovery policy without a managed
assessment of the particular attachment failure. Keep verified normal Take/Dock
behavior and narrow changes to failure branches.

**C07 — restarts are not UI-only.** The verified client startup calls
`systemctl restart klipper`. r116 installation again changed the backend session,
while preserving filament records. A separate stock warning callback at
`0x54c7d4` calls `is_printing` before `firmware_restart`; whether every managed
operation/paused state is covered by that stock predicate remains an open branch
qualification item. Do not label that conditional callback an unconditional
automatic restart. The head-communication guard preserves shutdown and topology;
it does not own every restart source.

### Behaviors already redirected or protected

- Native popup runout purge and automatic replacement/resume are disabled by
  the unified bootstrap transaction (`unified_runout_purge`,
  `unified_resume_check`). The explicit Resume-preparation hook sends only
  RESUME. The old October policy allowing stock fallback when openACE is absent
  is historical and does **not** describe the unified r116 screen.
- Runout/tangle popups 99/100 route to Filaments. Initial fault detection/PAUSE
  remains active; it should not be removed just to eliminate competing recovery.
- Standalone RESUME and paused M24 use `WMP_CHECK_RESUME`. These protect ordinary
  paused continuation; they do not imply PLR or arbitrary internal aliases are
  protected by the same entry contract.
- Sensor insertion cancels delayed checks and reports presence; it no longer
  auto-heats/feeds/parks. Delayed runout checks recheck the physical active head,
  sensor and print/pause state. Managed state distinguishes inserted from loaded.
- Nozzle Flow and first-run filament workers are redirected/retired. Main filament
  controls use managed operations. Calibration sender wrapping and identification
  replacement cover their enumerated paths, not all Factory Mode actions.
- The known communication-fault topology reset callback is blocked. This does
  not globally replace vendor reset/update/configuration scripts.

### Recommended implementation order and qualification

1. Redirect popup Re-print to preview and retire/adapt the legacy filament API.
   Verify no side effects occur before managed admission, including stale maps,
   changed file/identity, missing filament, paused jobs and unknown operations.
2. Give PLR a managed pre-preparation gate. Keep it separate from ordinary RESUME;
   test valid and invalid checkpoint, current filament state and operation journal
   before any heating or motion, then qualify physical recovery separately.
3. Guard reset/topology operations and reconcile persisted configuration before
   re-enabling controls. Test on disposable configurations first; do not factory
   reset the qualification printer merely to demonstrate the script overwrites.
4. Complete factory/editor session ownership and review non--3 retry policies.
   Use the existing exact ARM evidence and target only the changed failure/editor
   behavior, not unrelated stock calibration algorithms.
5. Trace remaining warning/restart, stop/cancel, firmware-update and onboarding
   early-exit callers. These are residual coverage leads, not additional confirmed
   incident causes. In particular, direct stock Cancel should be checked during a
   managed paused service for command ordering and queued follow-up effects.

New disassembly evidence is retained under
`analysis/validation/2026-11-11-stock-conflict-audit/`. No production behavior was
changed by this audit. The conclusions are bounded to these reviewed paths; they
are not a claim that every function in the vendor client has been audited.

### C06 follow-up: coupling retries below the tool-change wrapper

The direct service path also invokes stock `LOCK`. In
`config/live/change_macros.cfg`, that macro performs its initial actuator stroke
and calls `_LOCK_CHECK` four times; each failed sensor check can submit another
actuator stroke. Avoiding `_CHANGE_TOOL` alone therefore does not remove retries.
Managed PLR now has a local single-attempt coupling primitive using the initial
stock stroke, motion drain, actuator disable and strict Hall/lock sensor checks.
It does not clear faults or retry. Dock seating, physical head identity and
clearance must still be established by the enclosing preparation stages before
it can be integrated. Existing filament service is unchanged; no live deployment
or mechanical qualification is claimed.

The lower-level vendor `echelon_stepper.cmd_ECHELON_STEPPER_HOMING` also catches
homing exceptions, logs `UNLOCK TOOL FAILED`, and proceeds to the post-distance
move. Sensor readback is necessary but does not expose that suppressed failure.
Before enabling the managed coupling path, provide an acknowledged actuator path
that propagates homing failure and suppresses the post-distance stroke on failure.
Do not equate the new command-sequence tests with qualification of this vendor
handler; its error propagation is an additional integration requirement.

The local managed actuator adapter now calls `do_homing_move` directly, whose
retained implementation propagates `manual_home` errors. Only successful homing
permits coordinate reset and the optional lock stroke. Cleanup disables the
actuator only while the admitted owner/session still holds; cleanup errors do not
replace the original error. Tests execute the retained vendor homing method with
a simulated homing subsystem. This resolves local error propagation, not physical
qualification or native recovery integration; the stock command is unchanged.

### R27 follow-up: SD error fallback can invoke Cancel movement

`config/live/fluidd.cfg` configures virtual_sdcard.on_error_gcode as CANCEL_PRINT.
The retained vendor virtual_sdcard.work_handler renders and executes this handler
when a dispatched command raises its G-code error type. The CANCEL_PRINT source
in `config/live/macros.cfg` includes E-axis retraction, clearance/wipe, mesh/map
resets and file reset. A recovered command failure can therefore enter additional
movement and discard recovery context before a surrounding worker sees failure.
This confirms a source-level error path, not a newly attributed live incident.

The local private managed recovery worker temporarily supplies heater-only error
cleanup and restores the previous error template when that worker returns. It
records completion, deliberate pause/cancel or an unknown continuation outcome.
The vendor's generic exception branch can report paused without a requested
pause; managed handling treats that as unknown and does not replay the command.
Normal user Cancel and later native Resume workers remain separate R27 coverage
items. This change is undeployed and does not qualify all print error paths.

### R27 follow-up: later Resume creates a new unwrapped worker

The retained 1.1.13 `pause_resume.py:68` calls `v_sd.do_resume()` from
`send_resume_command`; `virtual_sdcard.py:119` registers `self.work_handler`
directly as a fresh reactor timer. `cmd_M24` enters the same `do_resume` method.
The local managed recovery callback calls that vendor worker and restores
`on_error_gcode` in `finally` when it returns, including a deliberate pause.
Consequently a subsequent ordinary Resume/M24 does not inherit that callback's
heater-only error handler or outcome recording. This is confirmed source-level
coverage loss, not evidence of a new live failure.

Required follow-up: retain managed job/attempt ownership across a deliberate
pause and admit the later worker under the same failure/outcome contract. Cover
Resume and paused M24, repeated pause/resume, command failure after resume,
explicit Cancel and changed session/owner. Preserve existing pause-state restore
semantics and do not repeat PLR preparation, priming or accounting restoration.
Do not globally replace the stock error handler for unrelated jobs. Implementation
and qualification remain open; no printer operation was used for this trace.

### R27 later-worker ownership implementation — 11 November (local)

A retained-vendor regression reproduced `G1 X2` followed by stock `CANCEL_PRINT`
after deliberately pausing before dispatch and calling native `do_resume`.
The local fix retains a bound worker wrapper after the initial managed worker
pauses. Resume/M24 still use vendor timer registration and pause-state return;
the scheduled worker reuses managed error/outcome handling. It does not repeat
PLR preparation or reset print accounting. Repeated pauses retain the wrapper;
completion/cancellation results and reset-file release its exact owned handler.

`WMP_CHECK_RESUME` validates the binding before the stock return sequence, and
the worker repeats validation before SD dispatch: session, request, paused
attempt, file object/name, owner, durable job fingerprint and current durable
deposition evidence. Missing/changed evidence stops dispatch. The temporary
heater-only error handler is restored after each worker returns. Unknown
outcomes retain the hold; other jobs must not inherit its worker binding.

Focused retained-vendor checks pass, including the previously failing regression.
The affected backend suite passed 1,066 tests; the strengthened Resume entry-point refusal checks also passed. This is undeployed; direct user Cancel
ordering and physical/owner-specific qualification remain open.

### R27 direct Cancel/service ordering — 11 November (reproduced locally)

`unified_command_sender` forwards stock commands after calibration-specific
rewriting; it has no print-Cancel reactor-intent route. The retained 1.1.13
`GCodeDispatch.run_script` takes the G-code mutex before dispatch. Managed
filament callbacks retain that mutex through heat/insertion waits and feed/wipe.
A queued stock `CANCEL_PRINT` therefore cannot set a cancellation flag while that
service holds the mutex. The separate `wmp/filament/cancel` endpoint records
service STOP intent on the reactor, but neither cancels the print nor fences
other queued requests. Do not claim stock Cancel already uses that endpoint.

The current CANCEL_PRINT template clears saved recovery context before M400,
then retracts, turns heaters off and invokes print-end clearance/wipe before
SDCARD_RESET_FILE/CLEAR_PAUSE. It does this even when wm_material reports unknown
attachment and unknown filament/tool operations. A known guard on Resume or
filament commands does not protect that Cancel prefix.

`tests/test_managed_cancel_ordering.py` reproduces mutex ordering using the
retained ReactorMutex/run_script implementations with a controlled wakeup model,
and renders the current macro with unknown managed state. Both reproductions
pass; these tests establish the defect, not acceptance of cancellation behavior.
The three existing native file-reset/pause-clear tests also pass. No printer
contact or motion was used. These reproductions must change when the managed
Cancel route is implemented; their assertions are not requirements to retain
stock motion or blocking behavior.

Required implementation boundary:

1. Screen print Cancel records explicit, job/session-bound intent without waiting
   for a long service's G-code mutex. Preserve print Cancel versus service STOP
   as separate actions and receipts. Reject stale/duplicate requests without
   cancelling a different print; never replay after a lost acknowledgement.
2. Intent fences new managed operations, pending service callbacks and Resume
   before cleanup acquires command ownership. Signal the current service's
   supported stop checkpoint; queued physical motion is not an immediate abort.
   Do not invent a successful stop for tool/coupling phases without an observed
   boundary. Keep their partial/unknown results durable.
3. After service dispatch yields ownership, drain prior motion and turn heaters
   off. Unknown attachment/service state must not enter stock retract, park,
   wipe, homing, topology changes or retry. Independently attempt heater cleanup
   if draining fails, while retaining uncertainty. Clear/invalidate only the
   matching job; keep service/fault evidence needed for reconciliation.
4. Mark print cancellation complete only after file/worker shutdown, pause-state
   cleanup and heater readback. Partial cleanup or unconfirmed delivery remains
   pending/unknown; a later command cannot silently restart heat or printing.
5. Cover stock-screen dispatch and ordinary console/API CANCEL_PRINT separately:
   the latter is serialized unless an explicit reactor-intent API is used. Its
   eventual cleanup must still respect managed uncertainty. Do not advertise it
   as an emergency stop or bypass another owner's cancellation contract.

Test the changed boundaries with queued callbacks, heat/insertion waits, feed and
wipe checkpoints, cancellation while paused, repeated requests, changed jobs,
lost replies, restart and partial cleanup. Keep unrelated stock Cancel behavior
out of the matrix unless the selected implementation changes it.

### R27 private cancellation core — 11 November (local, not connected)

The backend now has private intent and cleanup primitives. `_begin_print_cancel`
binds a request to the current session, filename and actual open SD handle,
persists pending intent, sets the SD pause flag and signals current standalone
filament service cancellation. A timer waits for both SD dispatch and the G-code
mutex to become idle before acquiring command ownership. Pending/unknown receipt
state fences managed service context, idle settings, print admission and Resume;
the resumed recovery worker also checks it. Duplicate IDs do not schedule again.

`_cancel_print_cleanup` sends no new physical motion: M400, heater shutdown with
all configured heater-target readbacks, matching recovery-context invalidation,
print-body authority clear, native SD cancellation and native pause cleanup.
Native `do_cancel` preserves accounting and reports cancelled, unlike file reset
which reports standby. It retains filament/tool partial records. Failure to drain
or journal a cleanup phase still attempts heater shutdown while the same job owns
cleanup; it does not clear the file or claim completion. Changed ownership/job
prevents cleanup of the replacement job. Lost completion persistence leaves an
unknown result and admission fence even if the physical cleanup finished.

Pending journal state restores as unknown without scheduling or changing the
original bytes. Corrupt records retain a conservative hold. This is not yet a
supported end-user cancellation flow: public reviewed request/receipt transport,
explicit resolution of interrupted/partial cancellation, native Cancel dispatch,
legacy console/API cleanup routing and stale queued-request generations are
still required. No endpoint/protocol is advertised for these private methods.
Do not deploy this core alone as the R27 fix.

### R27 reviewed Cancel API — 11 November (local, undeployed)

`wmp/print/cancel_review` accepts `id`, current `session` and selected `file`.
It returns those fields plus a 60-second one-use `token`; review sends no G-code,
sets no stop flag, writes no journal and schedules no worker. Server-side review
retains the actual open SD file object. Reopening the same filename therefore
cannot transfer the review to a replacement print. Same-request review returns
the same still-valid token; consumed/expired/changed review needs a new ID.
Session capacity is bounded to 1,024 review tickets.

`wmp/print/cancel` consumes the exact reviewed fields/token before entering the
durable intent core. Receipt state remains authoritative if HTTP acknowledgement
is lost. Duplicate delivery cannot schedule cleanup again or overwrite that
receipt. Readiness/owner/job checks occur again before intent; no fallback to
stock CANCEL_PRINT is made. `print_cancel_protocol = 1` advertises these two
backend endpoints. The native loopback transport allows their exact paths and
bounded bodies; it rejects suffix/query variants. Native Cancel UI dispatch is
not connected and no deployment is claimed.

Interrupted-result resolution still needs implementation. Within the same
session, an original live file-object binding can authorize an explicit new
cleanup review; it must not replay the old request automatically. Once the file
is gone, verify native inactivity, cleared pause, heater targets and invalidated
recovery authority before recording cleanup complete without commands. After
restart, filename equality alone cannot prove that an open file is the old job.
If saved recovery authority remains, explicitly review discarding that bound
saved job rather than silently treating an old cancellation ticket as authority
over it. Preserve partial filament/tool evidence throughout. These are distinct
cases; successful API delivery does not close their release gate.

### Design follow-through: interrupted cancellation — 11 November

The [design contract](ui-plan.md#cancellation-and-resumed-worker-findings--11-november)
and current R27 checklist now include independent durable intent, motion-free
cleanup, stale queued-request invalidation and explicit interrupted-result review.
The preceding API entry describes the committed milestone. The working tree now
also contains `wmp/print/cancel_resolve_review` and
`WMP_RESOLVE_PRINT_CANCEL`; these now pass local backend/transport checks, not deployed-screen or physical
qualification. Native/legacy caller
integration and deployment capability checks remain release gates.

### R27 standalone transport boundary — 11 November (local)

The unified standalone backend now captures `command_generation` at submission
and rejects a changed generation before delivery. It prefixes the same G-code
RPC with `WMP_CHECK_COMMAND_GENERATION SESSION=... GENERATION=...`; the retained
vendor dispatcher aborts the remaining script on refusal. This covers manual
heating/extrusion, metadata, service, toolhead and print submissions routed through
that backend; explicit service cleanup captures its own generation. It does not
intercept arbitrary console commands or stock command-sender paths. openACE
commands retain their existing owner path.

Cancellation advances the generation both at intent and before completion, so
commands queued during its hold cannot become eligible when the hold clears.
Candidate backend acceptance now requires the guard protocol and command. Native
Cancel interception and legacy console/API policy remain separate work.

### R27 cancellation progress evidence — 11 November (local)

Cancellation cleanup now records six independent stage outcomes: stop dispatch,
drain motion, shut down heaters, invalidate matching recovery authority, cancel
the SD file, and clear pause. Each stage begins before its work and completes
only after verification. Drain failure does not suppress heater cleanup and
does not become completed merely because cooling was attempted afterward.

Cancellation journal version 2 adds the ordered stage records. Version 1 remains
readable without fabricated stage history. Restart preserves original bytes and
turns running stages into unknown in memory; corrupt stage records retain a hold.
Older helpers do not understand version 2, so rollback must retain these records
and cannot silently clear an interrupted cancellation. Native presentation and
resolution controls remain separate integration work.

### R27 native sender and progress integration — 11 November (local)

The native command sender now consumes standalone `CANCEL_PRINT` lines through
`Runtime::route_print_cancel`, before calling the original command sender. Only a
freshly confirmed openACE owner retains the existing owner route. Unavailable or
stale standalone admission displays refusal rather than falling back to stock
motion. Compound scripts and console/API entry points are not covered by this
exact-command intercept and remain separate work.

Bootstrap allocates a dedicated cancellation HTTP transport. Status observation
and GUI presentation remain independent of delivery. The WM-styled progress panel
has CLOSE in the header, numbered backend stages, gray completed steps, orange
active/failed/unknown stages and white pending steps. Synchronization preserves
widgets and scroll position. Close only dismisses; repeated Cancel while pending
reopens the same result without resubmitting. Interrupted-result review and
confirmation controls, including restoration of their screen after restart, are
not yet connected. Do not deploy this partial integration as completed R27.

### R27 interrupted cancellation controls — 11 November (local)

A separate native resolution worker now performs read-only review and sends
`WMP_RESOLVE_PRINT_CANCEL` only after explicit CONFIRM. Review validates the exact
identity, token, action and selected file. Confirmation requires fresh ownership,
the same helper session and unchanged cancellation record; the backend repeats
its full evidence checks. The four actions remain distinct, including explicit
saved-job discard and command-free completion acknowledgement.

A restored identified unknown cancellation opens its retained progress panel once
per helper session without sending commands. CLOSE dismisses it without replay;
status updates preserve widgets. Exact matching resolution receipts remain
accepted when cleanup changes the original cancellation state. Lost replies cannot
downgrade recorded completion, and duplicate confirmation cannot resend. A helper
restart retires the old volatile ticket; any new cleanup needs another review.

Host worker tests cover changed session/record/owner/freshness/protocol, mismatched
review identity and receipt tokens, blocked/lost replies, duplicate confirmation
and restart without replay. Native lifecycle tests cover restored presentation,
REVIEW then CONFIRM, retained completion and CLOSE. Candidate backend acceptance
now requires `print_cancel_resolution_protocol` and `WMP_RESOLVE_PRINT_CANCEL`.
This remains local integration: compound/console/API routing and deployed-screen
and physical qualification are still open.

### R27 legacy ingress and compound commands — 11 November (local)

The native sender now matches command names using the retained Klipper parsing
rules (case, comments, optional N prefix and command parameters). A standalone
batch containing Cancel is replaced by one managed request; its prefix and suffix
are not forwarded. Mentions in comments or parameters of other commands are not
Cancel. A confirmed other owner retains the original batch.

At Klipper Ready, wm_material wraps `gcode.run_script` before its mutex acquisition.
The standard `pause_resume/cancel` endpoint and console `gcode/script` endpoint
both use this method in retained 1.1.13. Cancel captures the current actual file
object/session and records durable intent immediately. The entire Cancel batch
is superseded. Direct SD lines also use this ingress; cleanup waits for SD
activity/command dispatch to end. Nested macro Cancel lacks this ingress binding
and refuses before stock macro cleanup. openACE/AFC retains the original route.
The installed hook advertises `print_cancel_ingress_protocol`; candidate backend
acceptance requires it. Duplicate readiness does not stack wrappers.

This does not fence arbitrary non-Cancel console scripts that have already
entered the original dispatcher and are waiting for its mutex. Their queue policy
is still an explicit R27 gap. Internal commands such as BASE_CANCEL_PRINT and
SDCARD_RESET_FILE are not promoted as supported alternate cancellation APIs.
The old source/mutex reproductions remain valid for the unwrapped vendor path;
they do not describe the newly wrapped runtime path. No live deployment occurred.

### R27 queued legacy scripts — 11 November (local)

The standalone run_script ingress now captures helper session and cancellation
generation before calling the original mutex-owning dispatcher. It prefixes each
non-comment command with `WMP_CHECK_SCRIPT_GENERATION` using that captured binding.
The retained dispatcher aborts the remainder of the script on guard refusal.
This rejects work queued before cancellation, work queued during a hold that
clears before dispatch, and trailing commands after an earlier command yielded
while cancellation arrived. Fresh requests after verified cleanup remain usable.

During a pending/unknown cancellation, only isolated TURN_OFF_HEATERS and the
explicit reviewed WMP_RESOLVE_PRINT_CANCEL command receive hold permission; adding
another command removes it for the whole batch. Exact M112 keeps its existing
emergency-stop dispatch. Other-owner ingress retains its original contract.
The guard is registered when not Ready so an otherwise admissible restart does
not fail merely because the guard is absent in shutdown. Restart policy remains
R26, and this is not an assertion that arbitrary restart is allowed during a hold.

Candidate acceptance requires `script_generation_protocol` and the guard command.
These checks cover the supported run_script APIs and their command boundaries;
they do not preempt an already executing macro or replace the emergency-stop path.
They do not turn low-level internal dispatcher calls into supported remote APIs.
The prior queue-gap note is superseded for this local implementation; deployed
screen, supported-owner and physical qualification remain open.

### R22/R27 r119 qualification deployment — 11 November

The managed recovery/cancellation code and native receivers are now installed in
source-sealed development qualification r119. Required loaded protocols/commands,
Ready/standby, unchanged calibration/saved variables and H3/H4 loaded identities
were verified. Four idle refusal cases passed without position, heater target or
managed-state changes. Native bootstrap runs and the filament overview renders.
The [current checklist](ui/standalone-completion.md#11-november--r119-installed-live-idle-qualification)
records exact evidence and remaining gates. Earlier local-only entries are
historical; this deployment does not establish successful physical recovery,
active-job cancellation or interrupted-result UI acceptance.


### R23 calibration provenance correction — 11 November

A loaded UUID mapping is not proof that calibration was measured against that
mapping. Identification can repair an incorrect assignment produced by discovery
without the operator physically moving heads. Automatically moving PID/nozzle/
filament records by that old assignment can therefore attach them to the wrong
hardware. The local candidate planner is valid only when its source ownership is
independently established; matching current runtime settings is a consistency
check, not historical calibration provenance.

The local command adapter now refuses a changed observed mapping before any
configuration publication. Unchanged identification can still verify the existing
configuration. This is an interim refusal, not completion of the changed-topology
workflow. The eventual review must distinguish correcting an assignment from
physically moving/replacing heads and establish which calibrations remain valid.

Source-backed field distinctions:

- `config/live/change_macros.cfg` consumes `tN_position` for physical dock travel;
  those locations must remain with the dock.
- `_OFFSET_SET` treats `tN_offset` relative to the selected probe tool. Offsets are
  stored relative to T0, so changing the reference head also affects the datum;
  copying tuples without considering that reference is insufficient.
- `config/live/macros.cfg` resets `probe_tool` to zero at ordinary startup and
  guards default mesh use against probe context. A reference-head change must
  preserve or explicitly invalidate the associated mesh context.
- Saved-variable calibration samples/centers/Z values and pressure/flow values
  require their own provenance policy; a generic `tN_*` permutation is invalid.

No live head movement or historical calibration ownership was inferred from this
source audit. The recently added integration remains undeployed.

### R26 Ready-state backend restart boundary — 11 November (local)

`wm_material` now registers `gcode:request_restart` admission for standalone mode.
The retained vendor dispatcher emits that event before dwell/drain/request_exit
when Ready; tests execute those actual dispatcher methods and verify fresh-state
refusal before side effects. Explicit not-ready restart preserves durable holds
without replay. The focused restart/parser-state suite passes 60 cases.

This does not intercept `systemctl restart klipper` from client startup, establish
other-owner policy, or protect SAVE_CONFIG writes that precede the event. The
warning callback's conditional predicate remains a separate caller qualification
item; its G-code restart reaches this new boundary only when this local code is
installed. No deployment is implied.

### R26 direct SAVE_CONFIG boundary — 12 November, local candidate

The restart event remains too late for direct SAVE_CONFIG callers: the retained
writer has already replaced printer.cfg. SAVE_CONFIG_NO_RESTART has the same
write path without the event. WM+ now wraps both registered commands at Ready and
runs standalone admission before invoking the original writer. This covers native,
remote and nested G-code dispatch; it does not intercept Python code directly
calling a retained method or external shell configuration writers. Pending values
are preserved on refusal, and other-owner policy is unchanged. The managed
calibration's synchronous save remains admissible through its existing _saving
state. 217 affected tests pass, including actual vendor dispatcher/writer execution
on disposable files; both complete plugin initialization orders also pass. Not
installed at the time of local testing; subsequently deployed in combined r132
with registered commands and unchanged files verified. Live active-operation
refusal and external-script writer ownership remain open.

### R23 automatic startup discovery — 12 November, local candidate

The exact 1.1.13 `main()` constructs the CAN discovery command at `0x44a284`
and calls the shell helper at `0x44a2a0` (return address `0x44a2a4`). Its returned
text is logged as `set canbus_uuid:{}`; the following independent shell call reads
`current_thr_number.txt`. Retained `canbus_query.py` queries unassigned nodes,
writes controller UUIDs during responses, then, for a positive head count, writes
the count and calls `set_thr_uuid`. A partial count can therefore replace
printer.cfg and erase other configured head UUIDs before the later startup
restart guard matters. This is a real automatic writer, not merely an unused
script file.

The local unified shell hook now suppresses only this exact startup caller and
command. It returns empty diagnostic output, does not invent discovery results,
and retains commissioned configuration. Explicit managed identification remains
separate. Other shell callers and changed commands retain their existing routes;
this is not a global script sandbox or support for commissioning new hardware.
The entry bytes are added to the native compatibility profile. The final ARM
build passes; 22 startup-boundary checks include executing the actual built
wrapper with exact/mismatched callers, return-value and string-ownership checks.
The combined r132 candidate is installed with exact artifact/Running bootstrap
readback. Nineteen affected configuration/identity files and effective settings
are unchanged across startup; no live discovery or CAN failure was induced.

The same literal-reference audit locates further writers for separate review:
`get_tmt1_ini()` references model-include enable/disable scripts at `0x626d80` and
`0x626df0`; `read_write_nozzle_diameter()` references its read/write script at
`0x52d06c`; `read_write_nozzle_uuid()` references its script at `0x52b28c`.
These references alone do not establish write-mode arguments or an unguarded UI
entry. The head-zero script reference at `0x6340b4` belongs to the already guarded
`unlock_extruder()` communication-fault callback. Startup also runs
`merge_config.py` before discovery; that adds absent factory keys to saved
variables/tmt1.ini, and does not replace printer.cfg. Its ownership policy remains
part of the external-writer inventory. Do not mark all writer coverage complete.

### R23 remaining writer call arguments — 12 November

`tools/inspect_stock_config_writers.py` now records the exact-client SHA, script
literals and eight direct-call mode assignments. It verifies each MOV/BL pair
and refuses any other firmware. Evidence:
`analysis/validation/2026-11-12-managed-audit/stock-config-writer-callers.json`.
This narrows the inventory; it is not live workflow acceptance or an exhaustive
search for indirect callers.

| Path | Verified arguments/effect | WM+ implication |
| --- | --- | --- |
| `get_tmt1_ini()` diameter call `0x626bec` | Mode 0: reads nozzle diameter from printer.cfg | This startup query is not a writer. Preserve it; no new mutation test required. |
| `start_nozzle_setting()` UUID calls `0x5107a0`, `0x510a78`, `0x510bf8` | Mode 0: reads wm_zru_thrN.cfg | Read-only parts of the old identification worker. |
| Same worker, calls `0x510f34`, `0x5110bc` | Mode 1: replaces canbus_uuid in wm_zru_thrN.cfg | Existing hook at worker entry `0x510350` replaces this worker with `unified_retired_identification_worker`; these writes belong to the already retired identification path. Other-owner qualification remains separate. |
| Native nozzle editor callback `0x52bfd0` | Mode 1: writes nozzle_diameter in printer.cfg | WM+ Toolheads uses StockNozzleEditor and the managed save_nozzle route. Any remaining stock entry into this separate callback still needs reachability/admission review; do not infer that replacing the Toolheads editor intercepts every stock editor. |
| `install_firmware()` call `0x659e78` | Mode 1: writes each retained nozzle diameter into printer.cfg | Firmware installation is a distinct external writer, not normal status sync or filament service. Keep it documented; do not perform a firmware-update test as part of UI validation. |
| `get_tmt1_ini()` model branch, shell returns `0x626da8`/`0x626e18` | Executes set_zru_include.sh 1/0; the script comments/uncomments the zru-s.cfg include in printer.cfg using sed -i | Startup does mutate this include. Unlike discovery, this script does not replace the whole config or directly change PID/UUID sections. Model selection provenance and compatibility need review before changing its behavior. |

The diameter and UUID scripts implement separate read/write modes, so suppressing
all invocations would break stock reads. The model-include edit is currently
forwarded by unified_shell; the exact discovery guard does not cover it. No new
guard or printer-side script execution was performed during this audit.

### General nozzle editor bypass — local fix, 12 November

The remaining stock entry is now traced: the General/system event handler
`0x5476cc` calls page_to("nozzle_type_page") at `0x547984`. The page registry
binds that name to setup `0x52c070` and refresh `0x52ce60`. Its event handler
`0x52bce0` writes immediately on a click: userdata 5/6 updates nozzle material
through the INI writer at `0x52bf04`; userdata 7–10 writes diameter through
`read_write_nozzle_diameter` at `0x52bfd0`. There is no separate Save admission.
Thus this is a concrete settings-ownership conflict, not an unrelated stock menu
being added to validation.

The local page hook now routes this exact page name into the existing managed
nozzle draft editor for standalone ownership. It selects the configured mounted
head, or the first configured head when none matches. Opening the editor submits
no command; Save/Cancel retain the existing managed revision/session checks.
Unavailable or unknown ownership never falls through to the immediate writer;
fresh openACE ownership retains its existing stock route. Unrelated page names
are unchanged. The GUI timer consumes the request through the existing stale
navigation check, rather than running LVGL from the page hook.

The native lifecycle harness passes with mounted/fallback head selection,
stale/pending-operation refusal, other-owner delegation, actual managed-editor
construction and no command on opening. Existing draft-only selection and
Save/Cancel checks run in the same harness. This is local evidence; deployment
and a General-entry screen check remain open. It does not intercept arbitrary
external script execution or firmware updates.

Deployed in r133 and accepted through the actual General → Nozzle Type menu.
It selected mounted Head 4; a stainless-steel draft enabled SAVE, and CANCEL
returned to unchanged hardened-steel settings. Configuration hashes and backend
nozzle records were unchanged. Evidence is in the r133 acceptance section of
`docs/ui/standalone-completion.md`. No nozzle setting was saved during this check.

The startup model source is also traced: get_tmt1_ini reads `[printer] model`
from `/home/t13dp/printer_data/config/tmt1.ini` using section::toInt with default
2 at `0x625670`. Values 1/2 set device_type directly; other integer values fall
back to 1. The comparison at `0x626cec` enables zru-s.cfg only for model 2.
This is configured model selection, not CAN-response-derived discovery. Preserve
the normal valid-model path; missing/corrupt/conflicting configuration policy is
still an open review item, not grounds to suppress every stock startup edit.

### R26 exact restart caller characterization — 11 November

Hash-bound tests against retained 1.1.13 now distinguish two routes:

- Startup constructs `systemctl restart klipper` and calls the shell helper at
  `0x64fc84` from `0x44a450`. It does not use command_sender (`0x614338`).
  Intercepting G-code delivery cannot protect this startup side effect.
- Warning callback calls stock `is_printing` at `0x54c858`, conditionally skips
  restart at `0x54c86c`, then calls firmware_restart at `0x54c8d8`. That helper
  sends FIRMWARE_RESTART through command_sender at `0x61645c`. This is a
  conditional user-event route, not evidence of an unconditional timed restart.

`tests/test_stock_restart_boundaries.py`: **2 passed**. These pin the command
boundaries, not the coverage of stock is_printing or live restart admission.
Startup ownership still requires a narrow, profile-verified interception before
main reaches the shell helper; a generic system() replacement would miss this
helper route and would affect unrelated processes. No printer contact occurred.

The local startup interception now hooks the verified shell helper and filters
both the main return address and exact command. The normal shell helper remains
available through its relocated prologue. Eight local tests include execution of
the built ARM wrapper for suppression and pass-through with correct string/return
ownership. Protection requires successful profile-verified WM+ bootstrap; stock
or failed-bootstrap startup remains outside this guarantee. Real reconnect and
installer lifecycle qualification remain pending; r119 is unchanged.

### R24 manual-probe acceptance is not command success — 11 November

Executed the hash-pinned retained vendor ManualProbeHelper ACCEPT/finalize methods
in seven disposable cases. Changed X/Y or Z not lowered from the starting position
reports failure, calls finalize(False) and returns normally. Both failed ACCEPT
and ABORT clear is_active and unregister ACCEPT/NEXT/ABORT/TESTZ. Successful ACCEPT
also clears status before invoking its finalizer with the accepted position; a
finalizer exception therefore leaves is_active false too.

`tests/test_manual_probe_acceptance.py`: **7 passed**. The future editor must bind
its save receipt to the backend session and actual helper instance, require a
non-null position and successful original finalizer completion, and invalidate
that receipt on abort/replacement/restart/failure. HTTP success, inactive status
and previously pending SAVE_CONFIG values cannot establish acceptance. This is
backend evidence for the required lifecycle, not an implemented editor or physical
calibration acceptance. No printer connection or motion occurred.

### R24 remaining native entry boundaries — local source recheck

The current `bootstrap.cpp::unified_maintenance_event` gate 3 still calls
`stock_service_event.hpp::stock_probe_calibration`, which sends
`_WMP_PROBE_CALIBRATE` synchronously before navigating to `probe_calibrate_page`.
It does not invoke `Runtime::begin_probe_editor` or `probe_editor_created`. Thus
the retained managed editor and independent transport are not yet the stock
Maintenance workflow. Replace this entry before qualifying that screen; do not
retain the legacy preparation prefix ahead of managed BEGIN. Reopening an active
result must display its existing request rather than prepare again.

Factory action 12 uses its separate embedded editor path (see the earlier exact
caller audit). It needs its own reviewed interception; Maintenance navigation
cannot stand in for that parent/drawer contract. Both stock editor callbacks must
be prevented from issuing their old ACCEPT/SAVE_CONFIG sequence when managed
ownership is active. Entry refusal must leave the existing screen unchanged and
show a reason; Close must preserve an ongoing operation and permit reopening.

This recheck used local sources only and introduced no live callback activation,
calibration, configuration writes or printer commands.

The subsequent local Maintenance replacement supersedes the synchronous gate-3
route described above: it opens the managed panel without dispatch. Only START
queues BEGIN. Closing/reopening retains the worker request. Factory's embedded
entry and any independent legacy-page ingress remain separate unresolved routes.

### R24 Factory probe entry interception — local candidate

The current candidate hooks `0x4c41a4` and consumes action 12 before its branch
`0x4c4794`. Retained ARM execution confirms this branch otherwise sends optional
G28, logical T0 and PROBE_CALIBRATE before drawing the embedded editor. Its first
16 bytes are stack/frame/register operations without PC-relative operands; the
complete client SHA and 32-byte window are in the generated firmware profile.
Non-probe valid events use the relocated original prologue/trampoline.

Nine offline tests pin dispatch, legacy prefix and the prologue. Native lifecycle
tests cover valid delegation and stale/hidden/deleted/detached refusal. These
prove the local entry contract only. Direct old editor ingress and the other
Factory service/reset paths still require their own coverage.

### R24 direct legacy callback retirement — local candidate

Exact event entries `0x4c76dc` and `0x53d150` now use full replacements, with no
original callback trampoline or fallback. Their 0–11 jog, 12 abort and 13 save
events open managed review only when the target belongs to the active visible
screen. The retained vendor ARM regression demonstrates why this is required:
action 13 sends ACCEPT immediately followed by SAVE_CONFIG in both callbacks.
Direct `probe_calibrate_page` navigation is consumed before the original page
router. The new controls issue commands only through the independent sequenced
editor transport. Live integration and bootstrap-failure policy remain separate
qualification boundaries.

### R24 expected checkpoint error presentation

Retained `GCodeDispatch._process_commands` reports command errors and emits
`gcode:command_error` before rethrowing nested macro exceptions. Probe/air
listeners finish pending probe sessions; gcode_move resets its last position.
Suppressing the event would remove required cleanup. Instead, the managed
preparation scope filters only error presentation for its exact STOP exception,
leaving the event and unrelated failures intact. Nested retained dispatcher
regressions verify no following G28 and no expected-error output while preserving
all cleanup events. This does not suppress generic STOP text or machine faults.

### R24 save command return versus writer completion

The retained dispatcher silently skips its command loop while quick_stop_flag is
set. The retained configfile SAVE_CONFIG implementation replaces printer.cfg and
then requests firmware_restart; it can also return early with no autosave sections.
The managed editor now observes that restart boundary and refuses to call a skipped
save successful. A disposable-file test confirms the writer ordering and backup.
This does not prove that the restarted process loaded the intended value; durable
resolution and loaded-value review remain separate requirements.

### R25 standalone retry boundaries — local candidate

Further source review of `config/live/change_macros.cfg` found that guarding only
`_CHECK_CHANGE_TOOL` is too late for two paths: `LOCK` calls `_LOCK_CHECK` up to
four times, each able to drive another coupling stroke, and `_LOCK_TOOL_FINISH`
issues UNLOCK after recording pickup failure. The local candidate now owns those
failure branches when wm_material is present and neither openACE nor AFC is loaded.

- Existing nonzero flags stop direct LOCK/_LOCK_CHECK before actuator commands.
- A newly absent coupling sensor records -2, then invokes a separate abort macro
  so the saved fault survives the raised error; no additional stroke follows.
- Failed lock completion records -2 and aborts before UNLOCK.
- Outer tool-change/park retry boundaries reject all nonzero flags before clearing
  faults, rehoming, travelling, pausing through the stock route or retrying.
- The existing -3 trapped-dock error remains in place for all owners.

Observed flag meanings in this source: -1 head/dock presence, -2 pickup/coupling,
-3 docking/release, -4 Hall mismatch, -5 head sequence. The -6 branch is retained
stock model-misalignment handling; this audit does not establish an active writer
for -6. Unknown nonzero values also stop under standalone ownership. Successful
travel/feedrate and other-owner recovery paths are unchanged by these guards.
This is local code, not proof of mechanical behavior or complete actuator fault
coverage. The lower-level swallowed homing-failure issue remains separately tracked.

### R25 swallowed actuator error boundary — local standalone route

The retained `EchelonStepper.cmd_ECHELON_STEPPER_HOMING` catches every exception
from do_homing_move, logs a warning, then unconditionally resets position and
issues the requested post-distance. All live config references to that public
command are in LOCK and UNLOCK. Their local standalone branches now invoke
`_WMP_COUPLING_STROKE`, which uses the propagating do_homing_move method and checks
command ownership before each later step. Non-standalone branches retain their
existing command. The helper retains/readbacks -2/-3 after an actual failure,
without retry; failed persistence shuts down. Successful macro motor-disable
timing is preserved. Tests exercise the retained vendor method and guards; this
is not physical qualification. Direct third-party calls to the vendor command
are outside this macro-route replacement.

### R25 remaining direct actuator callers — retained-source audit

An explicit search of the retained 1.1.13 Python payload found another caller in
`klippy/extras/feed_slot.py`: `FeedSlotHelper._note_slot_state` constructs public
ECHELON_STEPPER_HOMING commands for both trans_stepper and feed_stepper on slot
sensor events. This is an optional color_feeder path, not a call through the
managed LOCK/UNLOCK macros. No enabling color_feeder/feed_slot sections were found
in config/live or retained payload configuration files. That establishes a source
compatibility boundary, not the current live loaded-object state. Before supporting
that feeder configuration, establish ownership and intercept its automatic feed
entry before motion; do not replace its distinct feed geometry with head coupling.
Direct external command callers remain outside the macro-route guarantee.

Live contract check, 12 November: effective LOCK/UNLOCK and five related guard
macros match the reviewed source after whitespace/comment normalization;
_WMP_COUPLING_STROKE is registered and the deployed material backend matches
byte-for-byte. The configured trans_stepper implementation matches the retained
vendor source (SHA256 `af95c06c4205a2eac78f3d29d739bb2a9ce8c39e6b9246d463ac2b7897de38ba`)
and has the four required direct methods. No color_feeder/feed_slot sections or
status objects appear in the current effective configuration. The actuator itself
does not export get_status, so its absence from the Moonraker object list is not
used as absence evidence. This check issued no G-code and proves the installed
contract only, not mechanical failure handling. Evidence is
`analysis/validation/2026-11-12-managed-audit/coupling-installed-contract.json`.

The only discovered -6 fail_flag assignment in the live macro and retained stock
versions is commented out. Its model-misalignment reporting branch remains; no
active writer is established by these sources. Unknown nonzero faults still refuse.

The offline macro inventory now classifies _WMP_COUPLING_STROKE as possible homing,
motion and persistent-state effects and propagates those effects to macro callers.
These are conservative possible effects, not proof that every invocation writes a
fault. A focused scanner regression verifies propagation and leaves unrelated
message-only macros unaffected. The inventory does not discover Python callers or
prove effective configuration include order.

### R23/R24 identification versus probe-editor ownership

Head identification previously checked CalibrationCommands.active/failure but not
ProbeEditorCommands.busy(). The managed editor has its own lifecycle, including a
durable save-review hold while no probe helper is active. The local identification
entry now refuses that ownership before setting identification_blocked or creating
an attempt. This leaves the existing editor able to resolve its own evidence.
Migration admission also rechecks the editor at transaction boundaries and fails
closed if its state interface is missing. An explicit new identification request
can proceed after resolution; refusal never starts movement or writes files.

56 affected identification/transaction tests passed, including real editor busy
states (editing, save_review and unknown), missing editor state, unchanged files
and command logs on refusal, later explicit entry after resolution and renewed
admission refusal when the editor becomes busy. This is local integration evidence,
not deployed head-identification or changed-topology qualification.

### R23 identification runtime admission and generation boundaries

The command adapter now passes the full migration admission predicate into every
identification observation, rather than relying only on the older reduced
ready/idle check between commands. This includes managed editor ownership,
print-cancellation/recovery holds, open files, pending operations and both
openACE/AFC owners. Quick-stop also refuses initial/migration admission.

The attempt captures the original material object, session and command generation.
Each command, M400 and failure-mode cleanup checks that ownership before dispatch;
publication uses the same bound admission. A changed owner/generation cannot clear
a newer context's identification flag. If the old attempt cannot confirm clearing
its mode, the existing shutdown path preserves the unresolved result. This does
not preempt an already executing command or replace its internal motion guards.

Runtime regressions inject changes after the first pickup (session, generation,
owner, editor hold, cancellation hold and quick-stop), proving no second pickup or
configuration publication. A separate injection invalidates generation immediately
before publication. The affected suite passed 99 checks; the new publication check
also passed after correcting only its expected error wording (100 checks total).
Physical identification and deployment acceptance remain open.

### R23 identification request results and explicit retry

The previous native controller treated idle status after START as pending forever.
A managed-editor preflight refusal legitimately leaves identification idle, so
that status cannot establish whether its command was delivered or refused.
Identification protocol 2 now requires SESSION/REQUEST on _WMP_IDENTIFY_HEADS.
The backend records request-bound pending/complete/refused/failed results, retains
up to 128 request receipts per backend lifetime and never replays duplicate IDs.
A repeated refused request remains refused even after the blocking editor closes.
Invalid sessions/IDs refuse before creating an attempt.

The native controller sends a new random request on each explicit START. Only a
fresh receipt matching its request and calibration session can settle a refusal,
show its reason and reopen navigation/new START; stale or unrelated results do
not settle delivery. Partial failures remain blocked for inspection. Installation
now requires loaded identification protocol 2 and the registered command, so the
new screen cannot be accepted against the older uncorrelated backend. This changes
only the private setup command; its callers must supply the new identity fields.

Host checks cover matching/unrelated/stale receipts, fresh explicit retry,
duplicate refused/completed/failed delivery and native runtime/lifecycle behavior.
Live screen qualification remains open; no identification motion ran for this work.

### R23 native identification transport and completion correlation

The bootstrap calibration sender forwards the generated command unchanged to the
retained stock command sender; it does not filter away SESSION/REQUEST. Runtime
integration now covers START with those fields, duplicate-tap suppression, a
matching refusal without automatic resubmission, a fresh explicit START and
RESTART only after that request's complete receipt. Completed operation status
alone cannot authorize RESTART while the screen has its own outstanding request.
A reopened screen can still review the backend's completed identification and
explicitly restart it, subject to the existing idle/operation admission.

### R26 firmware restart is not Python module reload

Live r120 acceptance refused identification protocol 1 after changed helpers were
published and firmware restart reached Ready. Retained klippy.py lines 347–362
loop over fresh Printer instances in the same Python process; they do not reload
imported extra modules. Earlier installations implicitly relied on the stock
client's service restart. Once that startup side effect is suppressed, deployment
must request its own Klipper service restart, including rollback activation.
Local installer acceptance now requires a changed positive process ID and stable
Ready/active service samples. It never retries a restart with a lost reply.
161 host checks pass; corrected live lifecycle qualification remains open.

### R26 warning predicate qualification — 11 November, offline

Nine new hash-bound ARM instruction cases execute the retained `is_printing`
decision through its **return-value assignment**, then execute the warning
callback's conditional branch. Static initialization and diagnostic string-cache
operations are substituted; this is caller characterization, not a live warning
or permission to restart. The intermediate condition at `0x5197f8` is inverted
by the return paths at `0x519950` / `0x51999c` and must not be treated as the
function result.

The stock warning selects its restart branch for Ready/standby (unless stock
loading is set), Ready/cancelled, Ready/error, and the tested not-Ready states.
It blocks that branch for Ready/printing, Ready/paused and Ready/complete.
The pre-restart calls are logger construction/output, not configuration writes.
Its predicate contains no WM+ service-operation or durable recovery-result
admission. Thus a stock standby snapshot does not authorize restart during a
managed filament operation, tool operation or unresolved recovery/cancellation.
The installed standalone `wm_material._restart_requested` guard remains the
admission boundary before the vendor dwell/drain/exit sequence; existing backend
coverage includes these holds and fresh-state checks. Other-owner policy and live
warning presentation still require their separately listed qualification.

`tests/test_stock_restart_boundaries.py`: **17 passed**, including nine new
predicate/caller cases and the existing startup/command-boundary checks. No
printer connection, restart, motion, heat or print was used for these tests.


### Managed service entry disabled-state guard — 11 November

The intercepted Nozzle Flow, Maintenance, Factory probe and legacy probe-editor
handlers already rejected hidden/deleted/detached events, but did not reject
LVGL disabled state. They now consume such events on either the target or an
ancestor before managed review, admission callbacks or stock delegation. This
closes a stale/programmatic-event path through disabled controls; it is not a
change to unrelated stock menu actions. The newly used `lv_obj_has_state`
accessor is pinned to retained 1.1.13 address `0x69f084` and exact entry bytes.

Native lifecycle tests exercise disabled target and ancestor cases for all four
routes, including zero service/admission calls and no Back delegation when
disabled. Lifecycle and firmware-profile checks passed (two focused tests).
Candidate deployment and live entry-route qualification remain pending; the
installed printer still runs r124. No printer motion or restart was requested.

ARM candidate build also passed (`/tmp/wmp-disabled-entry-arm.log`).

Deployment follow-up: r125 installed successfully with an applied/closed journal,
matching library hash and native bootstrap Running. Independent before/after
checks preserve configuration, PID, mapping and filament state; the Home screen
renders. Physical route qualification remains separate from this activation.


### R22 missing-job fallback ownership — 11 November

The coordinate-fix module supports an older standalone mode that resumes a
verified coordinate-only checkpoint through stock preparation. Previously,
`WMP_RECOVERY_JOB_REQUIRED` was the only protection against that route when no
managed job sidecar existed. With that environment flag absent/zero, a loaded
WM+ recovery receiver did not itself prevent fallback.

`start_recovery` now resolves the managed receiver once and refuses a legacy
unbound checkpoint whenever that receiver exists. It preserves the records,
sends no managed preparation request, and never calls stock preparation. A
receiver with an unavailable runtime still establishes this boundary. The
coordinate-fix-only installation (no receiver, no required flag, no managed job)
retains its prior behavior; material-bound records never fall back without a
receiver. Explicit disposal/migration and native presentation remain open.

Validation: actual C hook harness and retained-coordinate tests **13 passed**;
new cases cover missing job, absent/zero required flag, unavailable receiver
runtime, legacy-only mode and required-flag refusal. Pinned offline ARM compiler
build passed with warnings treated as errors. This fix is local, not installed;
the printer remains on r125. No printer contact or motion occurred.

R126 activation follow-up: the fallback fix is now installed. Independent
readback binds the staged C source to the worktree, the installed library to its
compiled receipt, and the live client mapping/initialization log to that library.
Configuration/PID/filament preservation passed after the idle service restart.
This supersedes the local-only status above without claiming physical recovery
or legacy-record disposal acceptance.


### R22 startup journal preservation — 11 November, local

Restoring a pending/running recovery or scheduled/started continuation correctly
marks it unknown, but previously overwrote the only exact pre-restart attempt
journal. Startup now publishes the original bytes first as
`wmp_recovery_attempt_original_<sha256>.json` beside the managed profile.
Publication uses a flushed/fsynced temporary file, exclusive hard-link creation,
directory fsync and readback; existing archives must match and are never replaced.
The source journal is rechecked before its interrupted-state rewrite. Failure or
conflict prevents conversion; a newer external journal is preserved. Subsequent
loads of the already-unknown record do not create another archive or replay work.

This is evidence preservation, not migration or disposal. It does not make an
invalid journal valid, acknowledge a recovery result, clear a hold, or execute
recovery stages. Existing cancellation resolution requires a cancellation
receipt and must not be repurposed by inventing one for an orphaned saved job.

Validation: **10 focused startup/preservation tests** and **60 recovery-attempt /
file-binding regressions** passed. The backend change is local and undeployed;
the printer remains on r126. No printer contact, restart or motion occurred.

R127 activation follow-up: original-attempt preservation is installed with exact
backend-byte readback, a new Ready session and unchanged configuration/PID/
filament state. No interrupted attempt was present during deployment; the
failure/concurrency cases are local-test evidence, not live recovery acceptance.

### R20/R27 live popup corrections — 12 November

Actual log/wait-only completion exposed a native ABI error: `cur_page_ui`
(`0x463c500`, symbol size 80) is a character array, not std::string.
`page_to` copies its name at `0x553d68`; the page manager invokes setup/refresh
synchronously. Correcting the adapter and the host fake restored the completed
popup → managed preview handoff. The stopped popup additionally arrives after
stock clears `gcode_print_path`; only fresh terminal-job status may supply the
missing filename. No remembered browser selection is invented for that case.

The native STOP confirmation has a prefix missed by the earlier sender audit.
Popup kind 69 enters `0x530eb8`: affirmative `btn_pop_btn1` calls
`stop_printing_handler` (`0x530f48` → `0x51bf18`) and then `reset_plr_files`
(`0x530f4c` → `0x630fac`). The stop handler first calls `quick_stop`
(`0x51bf24` → `0x616558`) and starts its worker. Only later does that worker
send `CANCEL_PRINT` (`0x51bce0` → `0x614338`) and
`STEPPER_DIAG_DISABLE CHIP="stepper_z"` (`0x51bd1c` → `0x614338`).
The retained vendor webhooks quick-stop handler directly calls
`pause_resume.send_cancel_command`; it can cancel the SD job before managed
CANCEL_PRINT admission and record creation. Live r134 reproduced cancellation
without a managed receipt; this is not an accepted managed cancellation.

The corrected native popup hook routes the live affirmative kind-69 event to
`Runtime::route_print_cancel` before any of that stock prefix. Ordinary dismissal
is preserved, as is fresh openACE ownership. Stale/non-click/foreign events cannot
run stock cleanup. The existing managed worker supplies durable intent and
cleanup; no second cancellation implementation is introduced. Host native event
tests cover interception, duplicate/stale input, dismissal and other ownership.
Device acceptance of the corrected cancellation is recorded in the completion
checklist; the wider interrupted-cancellation matrix remains separate.


### Release scope summary — 12 November

These are the stock entry points that conflict with managed WM+ behavior. They
need an ownership handoff or admission guard; they do not justify rewriting or
retesting every factory screen. Detailed caller evidence remains in the sections
above, and device acceptance is tracked in the standalone completion checklist.

| Stock entry | Conflict with WM+ | Required treatment / remaining boundary |
| --- | --- | --- |
| Print and completed/stopped Re-print | Can start a file without fresh filament mapping and managed preflight | Enter managed preview. Completed-popup handoff and supported standalone stop routes are accepted. The remaining other-owner stopped-popup fallback is deferred with openACE support. |
| Runout and power-loss Continue | Stock preparation can heat, move, select tools or resume before managed recovery admission | Route to the confirmed owner's managed recovery. Native checkpoint continuation through resumed completion accepted r151; failed-attempt abandonment and interrupted-continuation reconciliation are accepted; incompatible-record retirement presentation was accepted on 13 November using the production panel with disconnected sample-data actions. openACE owner cases are deferred to its subsequent release. |
| Original power-loss prompt Cancel | Deletes PLR records and queues PARK_CURRENT_TOOL before managed review | Intercept before deletion/motion. Native review cancellation, confirmed exact-record archival, prompt dismissal and restart persistence accepted r156. |
| STOP confirmation and exclusion of the final object | Native quick-stop and PLR reset execute before its later CANCEL_PRINT command; final-object exclusion has a separate entry to the same stop worker | Intercept before that prefix. Native and remote cancellation passed, including final-object exclusion r169. Genuine interrupted-cancellation acknowledgement and its resolved-stage presentation passed r170. Existing host/native coverage accounts for failure branches; no unspecified additional cleanup matrix is required. openACE owner-specific cases are deferred. |
| Take/Dock and tool-change retries | Direct macro entries and automatic retries can clear retained coupling faults and move again | Preserve faults before any reset and refuse standalone retry. Successful H4 Take/Dock accepted; r140 guards installed. Changed retry/fault behavior has actuator and macro coverage; deliberate mechanical failure and general stock mechanical qualification are not release prerequisites. |
| General nozzle and Maintenance/Factory calibration editors | Direct writers can bypass managed identity, pending-editor ownership or acknowledged save | Use managed admission and receipt-bound completion. Do not treat an editor opening or ACCEPT returning as proof of a successful save. |
| Reset, discovery and head identification | Template/configuration writes can overwrite PID, calibration, mapping, travel or wipe settings | Factory reset deferred; retain the accepted refusal guard. Exact startup discovery is suppressed. Supported unchanged identification and changed-mapping refusal have reviewed transaction/session coverage (R23); unsupported hardware remapping is not claimed. |
| Restart and SAVE_CONFIG callers | Restart/write can interrupt managed service or recovery and invalidate live command context | Check operation ownership before mutation; service/startup paths require separate treatment from G-code commands. |
| Touch input polling | The factory reader collapses queued press/release frames to the final released state, losing short taps during GUI delays | Publish each complete pointer frame through LVGL’s continue-reading contract; retain factory coordinate/keypad handling. This addresses a reproduced interaction failure on managed screens, not unrelated stock menu behavior. See the GUI sync audit for compiled-code and live evidence. |
| Chamber-light getter and startup | The factory getter can export GPIO76 without setting its direction. Managed policy writes then fail if no factory setter has initialized the output | Keep status reads read-only; initialize missing/input GPIO through the factory OFF setter without changing saved preference. Preserve existing output state. This is a reproduced integration failure, not a reason to revalidate unrelated Home controls. See the current light entry in the completion checklist for deployment evidence. |

Unchanged file paging, USB copy, network/video controls and unrelated stock
navigation are not release validation tasks merely because WM+ is installed.
USB/profile import remains deferred. The remote-start stock mapping-backup
notification fix was accepted r141; its earlier local-correction account below
is historical, not a new validation task.


### Remote-start parser mapping writes — local correction, 12 November

The hash-bound 1.1.13 loop calls command_sender at 0x63dc1c, return PC 0x63dc20.
Only its exact identity backup writes for heads 0–3 are suppressed under fresh
standalone ownership. Managed Start owns start mapping; PAUSE already snapshots
actual mappings for RESUME. Other-owner and unknown/stale-owner behavior remains
unchanged, as do nonidentity writes and all other sender call sites. The focused
compiled boundary and ELF BL checks pass. This correction is not yet device
qualified; it addresses the stale remote-start notification noted above without
weakening cancellation admission or suppressing backend errors.


R141 acceptance follow-up: exact installed-module readback passed. One authorized
remote log/wait job and cancellation produced a six-stage complete receipt with
no stock mapping writes or stale-generation errors in its log interval. The
actual Home screen showed no error banner. Other-owner behavior remains a
separate gate; backend admission was not changed by this fix.


### Current Factory and knife admission correction — 12 November

The r141 implementation only handled Factory probe action 12; prior historical
candidate descriptions of wider Factory/knife guards did not match that build.
The current local candidate adds maintenance admission before Factory actions
8/9/10/13/14 and before knife editor actions 6/7/9. Refusal precedes stock display
mutation, jog or persistence. Probe review, distance selection and navigation
remain usable without machine admission. Invalid/disabled ancestors consume the
event before consulting admission or delegating.

The new knife entry 0x4c6490 is bound to the exact profile; its copied 16 bytes
are SUB SP, STP FP/LR, MOV FP,SP and STR X19, with no PC-relative instruction.
The new hook has a relocated trampoline for admitted actions. Fourteen local
native/ARM/profile checks pass, including a Factory regression that failed before
the change. Deployment and native Factory entry acceptance are pending. The
independent factory_mode_pass helper and other confirmation workers remain
separate audit items; this is not a claim of comprehensive factory qualification.


### Factory password-success trigger boundary — 12 November

The only direct factory_mode_pass caller in the examined executable code is
0x54e3b0, after successful text-keyboard password handling. The helper clears the
one-byte need_pass at 0x384ca00, then sends _LEVELING_TRIGGER at 0x4c415c. Exact
ARM execution now pins both effects. A sender-bound admission check at return PC
0x4c4160 blocks the trigger while managed work/status prevents maintenance and
queues a GUI-thread notice. It preserves password behavior and other senders.
The helper itself is not trampolined: its first 16 bytes include PC-relative ADRP.
The source-bound native and ARM checks pass; live qualification remains open.

### R26 warning predicate inputs — 12 November

Further inspection of the hash-pinned 1.1.13 `is_printing` body identifies its
inputs as stock printer state (`0xe645170`), stock job state (`0xe645338`) and
a stock activity byte (`0xe64537b`). Its comparisons reference `ready`,
`standby`, `error` and `cancelled`. It does not consult WM+ operation receipts.
Consequently the warning callback's conditional check is not admission evidence
for a managed filament, coupling, calibration or recovery hold. Its
FIRMWARE_RESTART still needs the installed backend restart admission boundary.

The retained ARM decision test now additionally covers unknown and empty job
states; both refuse the warning restart. With Unicorn available, the focused
checks passed all 12 cases (none skipped), executing the predicate instructions
and caller branch with substituted string helpers. Ready/standby and cancelled
allow the stock restart branch; Ready/printing and paused refuse it. Shutdown
permits that branch even with stock printing state. This qualifies the stock
decision logic, not a physical warning tap, backend admission or owner policy.
No printer restart was issued.

R20 queue clarification: standalone managed cancellation replaces the stock
stop worker and no longer produces its stopped-job popup. The fallback device
check therefore requires a genuine remaining caller/owner route; manufacturing
a popup or reverting managed cancellation would not qualify the released flow.
Completed-job Re-print remains accepted, and stopped-popup device qualification
remains open rather than repeating an unrelated completed-job test.

### Factory Mode entry route — 12 November

The deployed General menu contains Restore Factory Settings, not Factory Mode.
Read-only native navigation confirmed this distinction and returned to Home with
probe editor idle, unchanged backend session and Ready/standby state. Screenshots:
`navigation-r159-general-{review,lower,bottom}.jpg` in the 12 November audit directory.
No maintenance action, configuration save, motion or restart was issued.

The retained About callback at `0x4b0300` uses action 2 for Device taps and action 3
for Version taps. Three Device taps followed by five Version taps call page_to
with `factory_mode_page` at `0x4b048c`; Device taps reset the Version count.
Five hash-bound ARM execution cases verify the exact entry sequence and reject
wrong counts or an interrupted sequence. This establishes the real navigation
route for the pending live Factory entry/admission check. It does not qualify
password-success admission, calibration actions or Factory Reset.

### R26 warning callback and shared overlay — 12 November follow-up

The retained 1.1.13 warning callback at `0x54c7d4` handles a click on its
restart button by calling `is_printing` (`0x519600`), then, if false,
`firmware_restart` at `0x616428`. That helper sends the literal
`FIRMWARE_RESTART` through `run_a_gcode` (`0x614338`); it is not a direct service
restart. The predicate reads `klipper_state`, `current_print_state` and
`is_printing_loading`. It returns false when Klipper is not ready, or when the
print is standby without loading, error, or cancelled. It has no knowledge of
WM+ recovery/cancellation receipts or managed filament/calibration operations.
The installed standalone backend restart boundary therefore remains necessary;
the stock predicate is not sufficient admission. Live warning-click acceptance
and other-owner policy remain open. This trace does not identify the caller of
the earlier externally observed firmware restart.

The warning constructor at `0x54c93c` calls `lv_obj_clean(lv_layer_top())` at
`0x54c9e4`; its close-button path also cleans the shared top layer. This destroys
WM+ recovery panels rather than merely covering them. A new lifecycle regression
reproduces loss of an interrupted-recovery notice after this deletion. The local
fix tracks external deletion separately from explicit CLOSE and re-presents only
an unresolved recovery hold, without issuing a review or mutating command.
Evidence: `warning-restart-disassembly.txt` and `warning-restart-callees.txt` in
the 12 November managed audit directory. This change is newer than packaged r165
and is not device-qualified.

### Startup defaults merger versus active backend — 12 November

The retained 1.1.13 `merge_config.py` reads both INI files, adds absent factory
keys, then opens the destination with `w` and serializes its entire earlier
snapshot. It has no compare-before-write, backend coordination or atomic commit.
`tests/test_stock_merge_config_boundary.py` executes that exact function against
disposable files. An intervening backend save changes `current_extruder` and adds
`wmp_print_context`; adding one absent factory key then restores the stale head
value and removes the new context. The characterization passes and establishes
this conditional writer conflict, not a demonstrated live incident.

This matters when the screen starts while Klipper is already active, including
r167's explicit backend dependency. No write occurs when all factory keys already
exist. Merely making the vendor write atomic would not prevent lost updates.
The managed solution must coordinate default migration with backend startup or
route it through the backend's state owner; screen restarts must not independently
rewrite live saved variables. Preserve required factory defaults and valid-model
selection rather than suppressing all startup configuration work blindly. This
is an open R23/R26 implementation boundary; no vendor script or live configuration
was modified by this audit.

The competing screen-start write is now replaced in installed r168: the exact
`0x44a258` merger call is suppressed under the paired `WMP_DEFAULTS_OWNER=1`
contract, and Klipper ExecStartPre owns journaled defaults migration. Installer
rollback restores the helper and both service overrides together. Live deployment
verified successful helper completion; a screen-only restart retained backend
PID/session and both file hashes. Arbitrary external vendor-script execution and
full OS cold-boot qualification remain separate boundaries.

### Last-object exclusion bypass — local fix, 12 November

A direct-call scan of the retained 1.1.13 executable found a second entry into
`stop_printing_handler`: `exclude_object()` (`0x545924`) calls it at `0x545a94`,
then `reset_plr_files` at `0x545a98`, when `is_last_remaining_object` (`0x545598`)
returns true. This bypasses the existing kind-69 Stop confirmation hook. The
worker's stopped popup is created at `0x51be48`. The other direct stop caller is
`0x530f48`, already intercepted through Stop confirmation. This scan covers direct
calls, not arbitrary indirect invocation.

The new entry hook consults the same last-object predicate before the original
function marks object state, changes pages, quick-stops or deletes recovery data.
Last-object exclusion enters the existing managed cancel owner route. A confirmed
other-owner delegation retains stock behavior; absent runtime consumes the last-
object action. Empty selection and ordinary exclusion are unchanged. The selected
object at `0x4634ef0` is confirmed as std::string by its copy/empty/clear imports.
The first four entry instructions are position-independent and may be copied to
the trampoline. Entry/predicate/call windows are now in the exact profile.

Three focused routing/Re-print tests pass. ARM build is running; this hook is not
installed yet. Native last-object and supported-owner acceptance remain open.
Do not manufacture a stopped popup or label the completed-popup test as coverage.

Deployed as r169. Native SKIP → select the sole object → exclude → Confirm on
a real wait-only virtual-SD job entered managed cancellation and completed all
six stages (`cancel_2560841663951_1`). No motion/heating commands were in the job;
coordinates and zero heater targets remained unchanged. The stock stopped popup
was not invoked. This accepts the second known standalone direct stop-worker
caller; other-owner and indirect-caller coverage are not implied.

### Model-include writer — live consistency audit, 12 November

Read-only inspection after r175 found `[printer] model = 2` in tmt1.ini, an
active `[include zru-s.cfg]` in printer.cfg, and loaded `heater_generic chamber`,
`gcode_button door_button1` and `gcode_button door_button2` objects. Evidence:
`analysis/validation/2026-11-12-managed-audit/model-include-live-audit.json`.
The reviewed startup branch enables the include for model 2, so its intended
output agrees with this commissioned configuration. Combined with the accepted
r174 OS reboot's unchanged printer.cfg bytes, this does not establish a current
model-selection conflict or justify disabling chamber hardware initialization.

The include supplies the chamber heater, its verification/fans, air fan and door
buttons. Changing its activation is a hardware configuration change, not merely
screen layout. Mismatched saved model/include state and explicit model changes
still need a defined ownership/admission policy; the live consistency check does
not close those cases or general external-writer coverage. No model setting,
script, printer configuration or GPIO was changed for this inspection.
The two loaded door objects establish an available signal source for the proposed
door-open screen wake feature; polarity and wake behavior remain unqualified.


### Remaining writer scope — initial standalone release

Exact 1.1.13 caller provenance was rechecked with
`inspect_stock_config_writers.py`; the client hash still matches the reviewed
payload. Separate the following paths instead of treating all script calls as
configuration mutations:

- Startup diameter access is mode 0 (`0x626bec`). The retained
  `read_write_diameter.sh` mode-0 branch only reads; it is not an additional
  writer to intercept or a reason to repeat stock startup testing.
- General nozzle editing and firmware diameter updates use mode 1
  (`0x52bfd0`, `0x659e78`). That script edits `printer.cfg` directly with `sed`;
  the managed nozzle editor must own the former. Firmware updates remain a
  compatibility boundary, not an instruction to flash firmware during UI
  validation.
- Identification reads and writes are distinct modes. Only mode-1 calls mutate
  CAN identity files; their relevant boundary is the managed identification
  transaction, not ordinary status reads.
- `set_zru_include.sh` has actual write behavior even when invoked at startup:
  it enables/disables the chamber-hardware include based on saved model. The
  commissioned printer is consistent (prior live evidence), and the retained writer now has byte-preservation tests against managed
  configuration. Physical model changes remain outside this release qualification. The script does not replace the entire
  configuration with defaults or directly delete saved PID sections. Do not
  attribute the earlier PID loss to this script without separate evidence.

These distinctions narrow the external-writer audit. Factory reset is deferred,
and the current R23 checklist accounts for supported identification and guarded
writers. This does not authorize firmware changes or claim coverage of arbitrary
shell commands invoked by third-party software.

### R25 direct command boundary review — 12 November

The supported managed touchscreen path is `WMP_TOOLHEAD_ACTION`: it admits a
fresh attachment/session, persists intent before scheduling motion, dispatches
`_CHANGE_TOOL` or `PARK_CURRENT_TOOL`, and verifies final attachment and fault
state. This journal is not created by arbitrary remote macro calls.

| Entry | Boundary in the standalone configuration | Limitation |
|---|---|---|
| `T0`–`T3` | Resolve saved logical mapping then call `_CHANGE_TOOL`; existing nonzero fault refuses before resetting it | Logical tools are not physical head numbers; no managed UI operation journal |
| `_CHANGE_TOOL`, `PARK_CURRENT_TOOL` | Reject retained nonzero coupling faults; nested lock/unlock uses managed actuator boundary | Direct invocation does not gain the managed request-ID/attachment admission |
| `LOCK`, `UNLOCK` | `_WMP_COUPLING_STROKE` checks session/generation, cancellation hold, owner, shutdown and saved fault; one actuator attempt propagates failure | Low-level operation; no complete head-selection workflow |
| `_LOCK_CHECK`, `PARK_CURRENT_TOOL_RETRY` | Standalone failure stops instead of retrying or homing | Other-owner branches are deferred, not qualified |
| Vendor `ECHELON_STEPPER`, `ECHELON_STEPPER_HOMING`, `ECHELON_SP`, `ECHELON_STEPPER_DISABLE` | Direct registered vendor actuator commands, outside the managed workflow | A remote client can bypass WM+ by invoking these raw commands; the vendor homing handler catches homing failure and still executes its post-distance |

Sources reviewed: `config/live/change_macros.cfg`,
`klipper_extras/wm_material.py` (`cmd_TOOLHEAD_ACTION`, `cmd_COUPLING_STROKE`,
`_check_command_generation`), and retained 1.1.13
`klippy/extras/echelon_stepper.py`. Existing macro tests cover the single-attempt
route and fault persistence, and actuator tests cover propagated failure. This
review did not issue raw actuator commands or introduce restrictions on unrelated
remote G-code. WM+ is not a general sandbox for arbitrary console commands.
Third-party integrations should use the managed request API for interactive
Take/Dock; scripts that directly invoke vendor actuator commands do not receive
its guarantees. Physical failure qualification remains separate and incomplete.

### Model writer / WM+ configuration compatibility — 12 November

The hash-pinned `set_zru_include.sh` was executed only against a disposable copy
of `config/live/printer.cfg`, including WM+ recovery/material sections and an
additional SAVE_CONFIG PID block. Both include enable/disable, repeated startup
selection and reverse selection preserve every byte except the intended chamber
include line. `tests/test_vendor_config_writer_failures.py`: 6 passed, including
the two new compatibility cases. Only the hardcoded home prefix is relocated;
the script logic is unchanged.

This closes the specific concern that this model writer might erase WM+
configuration or saved calibration in the tested configuration. It is not
physical qualification of changing printer model or chamber hardware, atomic
write/failure qualification, or permission to change the live model. No product
interception is justified by this preservation check alone. Previously verified
commissioned model/include consistency and reboot preservation remain valid.
