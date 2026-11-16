# Independent openACE capability and WM+ gap review

Reviewed 30 October 2026. Read-only source/document audit; no printer operations,
deployment or hardware tests were performed. This is a source-presence and contract
review, not a declaration that every local feature is installed or qualified.

## Evidence precedence

The sibling openACE checkout contains newer implementation and acceptance reports
than the historical September command audit. `../openACE/docs/commands.md` labels
itself historical; its command descriptions are useful but its deployment claims
must not override the current code, roadmap or dated acceptance register.

Primary current evidence:

- `../openACE/klipper/extras/openace.py`: registration, management projection,
  command admission, direct loading, vendor macro wrappers and AFC facade.
- `../openACE/openace/binding/unit_settings.py`: persisted registration removal.
- `../openACE/docs/analysis/2026-10-29-non-ui-completion.md`: latest supplied
  software/deployment/hardware distinctions (includes a 30 October receipt).
- `../openACE/docs/roadmap.md`: implemented features versus qualification/deferred work.
- `../openACE/docs/reference/manual-reload.md`: direct-head and paused screen flow;
  some embedded hardware-status paragraphs are older than the non-UI completion report.
- WM+ `client-preload/openace-compat/screen1113/source/client/`: typed native
  adapters, delivery bookkeeping, session/context validation and manual flow.
- WM+ `docs/native-screen-packaging.md`: exact artifact/source binding and pending
  native widget/touch/Stop acceptance. The document's candidate is not proof of the
  currently installed V14 artifact.

## Capability matrix

“Implemented” below means present in the reviewed source. Qualification is separate.

| Requested capability | openACE implemented surface | Remaining openACE/shared contract | WM+ implementation gap |
|---|---|---|---|
| Presence, topology and status | Native `openace` object; head/source identities, default and active tool maps, loaded evidence, units/devices, operation, job and alerts. `openace.py` management projection at ~1072 and status assembly at ~1880. | Version each consumed projection; agree freshness, session invalidation and allowed-action semantics. Do not treat a sensor or configured identity as a verified load. | Build a shared presentation model and subscriptions; distinguish absent, unavailable, stale, unconfigured and unknown-loaded states. |
| New-unit discovery and adoption | `OPENACE_UNIT_SCAN`, `OPENACE_UNIT_ADD`; management `add_candidates` carries `expect_context`. Existing native adapter verifies context and uses stable USB identity. | Replacement identity acceptance is a different operation from new registration. Registered-but-unavailable and save-success/activation-failure require explicit outcomes. | Consolidated Adopt notification, home alert, candidate selection, name entry, waiting/result state and readback. Discovery does not create slot mappings. |
| Rename | `OPENACE_RENAME_UNIT`; fixed native command vocabulary supports rename. | Stale-context and persistence failures must be surfaced; use immutable unit ID, never display name as address. | Unit draft, save/readback, validation and keyboard. |
| Slot-to-head mapping | `OPENACE_MAP_TOOL` / `OPENACE_UNMAP_TOOL` (`openace.py` ~2158). Route is a tool destination. A slot cannot fork across heads; multiple tools may share one source. | One save for four edited slots needs a batch transaction or explicit partial-result protocol, conflict revision and tool-number allocation policy. | Quick-fill UI is feasible, but must preserve tool aliases and unrelated mappings. Never derive T numbers from display order. |
| Remove + delete associated tools + renumber | Existing `OPENACE_UNIT_REMOVE` explicitly refuses mapped units (`binding/unit_settings.py:252` onward). | **Not implemented as requested.** Need backend atomic cascade/renumber transaction, idle/paused admission, loaded/held resource refusal, old/new map, persistence and failure/readback behavior. | Confirmation can be built now; cannot wire it to current REMOVE and claim requested semantics. Invalidate preview routes after successful mutation. |
| Filament brand/material/colour | `OPENACE_SET_FILAMENT` supports addressed source identity, vendor/product/material/colour/temperature and other metadata. AFC field edits preserve unrelated values. | Material-only changes need a clear temperature/profile/default policy; unknown temperature must remain unknown. Profile catalogue and precedence remain undefined. | Current native `management_commands.hpp:136` admits only `material`, `nozzle_temp`, `color`; it preserves vendor/line instead of editing them. Brand control requires an adapter extension, not just a new widget. |
| External filament | Direct-head identities and manual tools exist; zero ACE is supported. A head may offer both direct and ACE tools. | User's simplified “External only when no ACE slot” display policy must not erase or silently hide a valid existing direct tool/loaded source. | Render actual direct sources and loaded evidence; separately show fallback empty manual configuration. Never use slot array index as head identity. |
| ACE Load / source selection | `OPENACE_SELECT TOOL`, virtual T commands and vendor LOAD wrapper exist. `_load_head_command` explicitly demands TOOL when several candidates exist (~2868). | Choose an existing routed source/tool, admit current head/job state, then monitor full preparation. Exact generic UI Load contract still needs agreement. | Empty-head Load needs source choice when ambiguous; selected head alone is insufficient. |
| Manual Load | `OPENACE_LOAD_DIRECT HEAD` preparation then `DONE=1 PRIME=` completion; reviewed paused flow has context, purge receipts and partial/unknown semantics. | Existing paused native surface is not a universal idle/active arbitrary-head API. Working temperature and actual source evidence matter. | Implement prepare → insertion → explicit prime → result/held state, preserving source/head/job context. Never convert an HTTP reply into physical success. |
| Unload | `OPENACE_UNLOAD HEAD [TO_UNIT]`, vendor unload routing and recovery machinery exist. | Direct-head versus ACE unload, retained tail/holds, completion and operation stop need context-specific capabilities. | Loaded head card must dispatch based on loaded source, not its default assignment. Show partial/unknown results and correction instructions. |
| Direct Extrude/Retract distance buttons | Vendor `EXTRUDE_FILAMENT` is guarded purge-with-assist, not a general distance API. `RETRACT_FILAMENT` may mean full unload. `OPENACE_ACE_RETRACT` moves feeder only. | **Missing shared exact-distance operation contract.** Need target/route, sign/distance/speed, admission, operation ID, progress/completion/unknown outcome and overlapping-request policy. | No review dialog is fine, but busy spinner must follow backend lifecycle. Do not use timer completion, LOAD_DIRECT DONE, vendor purge or feeder retract as substitutes. |
| Temperature and Take/Dock | Physical heater commands and target-specific head macros exist outside this screen contract. openACE routes M104/M109 T as virtual. | Owner-aware physical-head control, active-print override rules and mounted/homed state admission need agreement. | Use physical heater addressing. Take/Dock require explicit distinct commands and result state; no opaque stock prefixes. |
| Print preview and start | Frozen per-print `OPENACE_MAP` on submission, standard command wrappers, material requirements and source/routing state exist. | Frontend projection must expose usable destinations, actual T aliases and compatibility reasons; stale revision and start admission need a defined handshake. | Real file metadata, thumbnail, slot picker, optional brand, colour comparison, destination selection, backend validation and actual submission remain to be implemented. Keep active map separate from default configuration. |
| Recovery and RESUME | Shared operations, persistent repair episodes, stop confirmation, manual changes, runout and same-job RESUME exist. Latest report distinguishes deployed thermal correction from remaining hardware gates. | Per-case permitted corrections and current receipts; no universal Reset/Retry/Abort. Fractional native manual procedures are explicitly unsupported. | Integrate owned recovery views; maintain required tool/source and exact context across navigation. Generic operation screens cannot replace this machinery. |
| AFC/Orca interop | `lane_data`, `SET_COLOR`, `SET_MATERIAL` implemented (`openace.py` ~5412); lanes correspond to virtual tools. | This is lane metadata interop, not arbitrary filament profile import. | Adapter may reuse field-edit vocabulary but must not claim full profile transfer. |
| USB JSON/ZIP and command profile upload | No matching filament-profile importer found in registered commands. Existing calibration/relative-recipe imports are unrelated. | **New feature:** format/version, inheritance, archive limits, supported fields, validation, duplicate/conflict policy, catalogue persistence, upload command and readback. Raw Orca format remains undecided. | USB picker, upload integration, import review/progress/errors and editor catalogue choices. |
| PA/profile details | Reviewed native identity adapter does not expose PA; no matching profile/PA command contract found in registration audit. | Storage, applicability, precedence and timing remain TBD. | Keep advanced controls out of touchscreen scope until remote contract exists. |

## Completed software is not completed qualification

The latest non-UI completion report records implemented shared operations, accounting,
persisted repair episodes, stop confirmation, source identity and pause/RESUME. It
also records a deployed RESUME thermal correction after software review. It explicitly
keeps the next distinct ACE fault/correction/continuation hardware test open.

It reports implemented zero-unit/manual-head setup and public unload/load/RESUME
integration, plus a real same-file manual replacement reaching EOF. That hardware
case needed two RESUMEs before the later thermal fix; it is not a claim that every
recovery domain or every supported hardware configuration is qualified.

Actual missing openACE feature: verification-triggered bounded unload/reload. Current
low/inconclusive activity is `unverified`, not a qualified physical negative; the
agreed outer retry loop is not active. Ordinary contact/no-arrival retries already
exist and should not be reimplemented by WM+.

Remaining hardware/delivery work includes shared-hub fault recovery, unload/capture/link
loss correction, actual ACE/manual runout, different-colour replacement, all-manual
hardware acceptance and supported slicer packaging. Automatic feeder-datum measurement,
additional clog/tangle treatments and other hardware families remain separate later
work. These are not all prerequisites for read-only screen implementation, but they
limit the operations the UI can truthfully advertise as qualified.

## Implementation decision

Start the native shell, navigation, status projection, read-only identity/source
views and contract adapters now. Basic discovery/adoption/rename and identity adapters
can be developed against existing typed commands with fixtures; do not claim a complete
accepted operator workflow until readback, keyboard and stale-context handling pass.

Do not attempt to finish all operational screens merely by wiring mockup buttons to
existing strings. First agree and implement these slices:

1. Shared owner/capability/freshness/job and identity/source model (WM+ + openACE).
2. Load-source selection and direct/manual operation progress/receipts (shared).
3. Exact-distance Extrude/Retract and physical-head control admission (backend + WM+).
4. Authoritative preview destinations, compatibility and print submission (shared).
5. Batched mapping and cascade removal/renumber transactions (openACE-owned).
6. Profile import/catalogue/precedence (new shared backend and WM+ UI work).
7. Standalone WM+ equivalents (WM+-owned; openACE absence is a supported mode).

Retain the current native delivery/session/context protections. Attended native
layout/touch/Stop/modal acceptance and exact artifact/source binding remain deployment
gates, distinct from HTML browser checks. This review agrees with the independent UX
review that foundations can start, but the complete operational screen suite is not
implementation-ready as a single finished scope.
