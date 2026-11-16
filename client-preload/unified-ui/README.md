# Unified WM+ screen implementation

**Presentation correction in progress:** the operator rejected the full-page
renderer as a replacement covering the stock app. The required implementation
must retain and modify stock widgets in place. The functional inventory below
describes the earlier candidate, not completion of that corrected requirement.
See [stock screenshot annotations](../../docs/ui/stock-integration-review.html).
`native/stock_filament_layout.hpp` and the stock page/native adapters now bind
standalone Filament geometry to the original constructor and deletion lifecycle.
Action/edit callback conversion and the other pages remain pending. This
corrected candidate has not been activated.

This directory now contains a **native LVGL integration candidate for the WM
1.1.13 Screen app**, in addition to the shared C++ controller. The operator
authorized activation and a no-motion walkthrough on 2026-10-31. The native
candidate is installed on that printer; the ordinary sealed release bundle has
not been replaced. See `docs/ui/native-readiness.md` for evidence and limits.

## Build the native Screen app candidate

```sh
sh client-preload/unified-ui/native/build-arm.sh
```

The script uses the already-pinned ARM toolchain container with networking
disabled. It writes `analysis/unified-ui-native/libwmp_unified_screen_candidate.so`,
a source/artifact manifest, and ELF dependency information. It does not deploy,
restart services, or overwrite the sealed bundle.

Native integration now implemented:

- Exact 1.1.13 executable and function-window verification.
- Stock Home temperature buttons → physical-head manager.
- Stock Filament navigation → unified Filaments / ACE slots page.
- Actual LVGL widgets, styling, modal input ownership, and **vertical scrolling
  containers** holding all ACE groups (no Previous/Next pagination).
- Stock Home/Files/XYZ/Video/Wi-Fi/General return navigation; always-accessible
  Back to stock controls, including inside WM+ modals.
- Read-only Moonraker projection for heaters, print state, openACE source/loaded
  identities, units, assignments and discovery; explicit standalone ownership.
- Typed brand/colour-edit, rename-only and adoption queue paths with status
  readback; unsupported operations remain disabled/refused.
- Existing material/manual-recovery panels take priority over the new pages.

Still required: native runtime/touch acceptance, Take/Dock procedures, openACE
manual filament operations, and backend-specific recovery
integration. Standalone Load/Unload is connected but requires physical acceptance.
The build is a development
candidate, **not a qualified installation package**.

## Host checks

```sh
python3 -m pytest -q tests/test_unified_ui.py
```

`host.cpp` and the earlier browser harness remain only for controller/layout
regressions. They are not the GUI implementation or the native acceptance path.

## Screens and flow coverage

| Screen / flow | Implemented | Still stubbed or awaiting integration |
|---|---|---|
| Home | Head entry points, grouped ACE mini-view, discovery alert, files/job entries | On-device layout/touch acceptance; stock active-print UI retained |
| Toolheads | Four tabs, loaded/empty/unknown cards, source edit, direct E steps, temperature, persistent loaded state, standalone Load/Unload | Take/Dock, openACE external-load and direct-step adapters; hardware acceptance |
| Filaments / ACE slots | Head highlighting, four slots per unit, connected labels, native scrolling, External sources for heads without ACE assignments | native touch acceptance |
| Unit details | Isolated name/assignment draft, keyboard, quick assignment, per-slot assignment/unassign, Save/discard | Atomic route save; current typed adapter supports rename-only |
| Identity | Source-specific draft, brand selector including Generic, material choices, colour palette retaining custom values | Brand/material policy and profile catalogue; typed adapter supports brand and colour edits of existing identity; material changes and new profiles remain unavailable |
| Adopt | Scrolling candidate selection, observation-bound confirmation, registered-unit readback, automatic Unit details draft | Hardware acceptance |
| Remove | Idle-only entry, impact explanation, confirmation | Exact affected-route preview and atomic cascade/renumber backend |
| Import | USB chooser, review/result entry, command-upload explanation | Enumeration, format, conflict preview, validation/import backend |
| Load/Unload/Take/Dock | Source selection, token-bound procedure review, operation origin; standalone and idle ACE Load/Unload connected | Take/Dock and external preparation adapters |
| Direct Extrude/Retract | Direct dispatch without review, bound signed distance/head, button busy state | Standalone E-only backend connected; openACE operation adapter remains |
| Operations | Original operation, auxiliary Stop/cancel state, complete/refused/failed/partial/unknown; standalone receipt reconciliation | openACE recovery status bridge; hardware acceptance |
| Recovery | Job-bound source/head, phase-allowed Prepare/Prime/Confirm/Resume, return origin | Reuse/bridge existing manual recovery protocols into this projection |
| Files/preview | File list, sliced colour/material/brand, selected colour/authoritative tool label, grouped source popup, stale-map invalidation | Standalone and openACE submission connected locally; hardware acceptance remains |
| Thumbnail | Expand/close modal, bounded PNG cache and native LVGL rendering | On-device decoder/layout acceptance |
| XYZ/Video/Wi-Fi/General | Settings tabs and retained-page destinations | Native handoff implemented; stock pages are retained |

No Devices, Slot Assignments or Filament Library page has been added.

## Code boundaries

- `model.hpp`: navigation, drafts, admission, operation context, receipts.
- `screens.hpp`: 800×480 layouts and modal flows shared by all renderers.
- `native_renderer.hpp`: owned-surface renderer, stale-event rejection and
  current-action revalidation. `native/lvgl_surface.hpp` implements the port using
  the exact stock LVGL ABI; `native/runtime.hpp` owns its worker/GUI integration.
- `openace_backend.hpp`: calls the existing typed management builder and bounded
  worker queue. Supports context-bound adoption, existing-identity brand/colour edits,
  and rename-only unit saves. It refuses unavailable/ambiguous operations.
- `host.cpp`, `preview.py`, `preview.html`: local fixture runner and renderer.
- `fixture.json`: fictional data, no printer credentials or addresses.

Typed requests are wired into the activated native candidate. Physical action
qualification remains outstanding.
The receipt bridge requires configuration readback; queue acknowledgement alone
does not mean a save completed. Material changes are refused instead of silently retaining an unsafe
old temperature. Route changes are refused instead of partially renaming a unit.

## Normalized snapshot contract

This is a new WM+ presentation contract; **do not assume openACE publishes it**.
`App::update` accepts a full snapshot and invalidates malformed data. The adapter
must also enforce bounded input, freshness deadlines and monotonic observations.

- `owner`: `standalone`, `openace`, or `unknown`. A lost openACE connection never
  becomes standalone. Zero ACE units does not imply absent openACE.
- `session`: stable backend-session identity. `revision`: change token covering
  topology, identity and preview file metadata. Changes invalidate selected maps.
- `fresh`: established by the polling adapter, never by an old cached view.
- `heads`: stable IDs/names, actual/target temperature, and separate `loaded`
  records (`empty`, `loaded`, `unknown`, `loading`, `unloading`). Loaded identity
  does not change merely because configured source identity changes.
- `sources`: stable ID, kind (`ace` / `external`), head association, availability,
  identity. ACE entries also require `unit` and numeric zero-based `slot`.
- `units`: stable ID, display name, connected state, complete assignment map.
- `routes`: backend-issued IDs, T labels, source, eligibility and eligible sliced
  row IDs. Aliases are not silently resolved by array order.
- `capabilities`: **currently admitted actions**, not merely feature existence.
  Recovery also requires `job.allowed_actions` from the current recovery phase.
- `procedures`: action/head/source/revision-bound descriptions and opaque tokens.
  Begin submits that token. Recovery also retains the complete job context and
  refuses a changed context. No generic invented purge length is provided.
- `receipts`: keyed by operation ID, with matching `owner`, `session`, `action`.
  Recognized states are pending/unknown/partial/complete/refused. Other states
  remain unknown. Complete must mean a reconciled effect, not command delivery.
  Configuration completion additionally requires matching normalized readback.
  Stop/cancel requests are tracked separately from the original operation.

The adapter must translate public backend evidence into this contract without
inventing loaded state, measured travel, successful physical work or tool IDs.

## Before native deployment

1. Qualify native page ownership, entry/return hooks, scroll/touch behavior and
   foreign modal priority on the exact client. Complete image/preview integration.
2. Extend and qualify the implemented normalized status projection, especially
   standalone metadata and loaded state. Preserve absence/unavailable distinctions.
3. Verify typed delivery/readback and session-bound receipts on hardware; enable only
   individually qualified capabilities. Retain stubs for missing operations.
4. Qualify native layout/touch/modal lifetimes, then rebuild a separate bound
   artifact and perform attended idle-printer acceptance with approval.

Host tests and browser screenshots do not establish native/hardware acceptance.

## Standalone native controls (development candidate)

`standalone_backend.hpp` now connects the native Heat/Off and Extrude/Retract
buttons to the worker. No HTTP calls run on the LVGL thread. The worker discovers
objects, positively establishes openACE absence, queries physical heater limits,
and rechecks the request against its latest observation before sending once.
Heater success requires subsequent target readback. A transport failure produces
an unknown outcome and never an automatic retry.

Distance steps require the installed `WMP_EXTRUDER_STEP` macro, an active selected
physical extruder, sufficient nozzle temperature, and an idle or paused job.
The macro repeats those checks inside Klipper, rejects openACE ownership, limits
each request to 50 mm, and executes only relative E movement at 5 mm/s. It saves
and restores G-code state, compensates for speed/flow overrides without changing
them, and waits for the
move queue with M400. It does not heat, home, change heads, wipe or park. A normal
RPC completion confirms this commanded sequence finished; it does not prove
filament travelled through the gears. Errors remain unknown because execution
may have begun. The native transport permits a bounded 15-second POST for this
sequence while retaining the short status-query deadline.

`native/loopback_http.hpp` extends the frozen transport's query allowlist for the
unified screen's exact status fields. It remains restricted to loopback Moonraker.
The frozen V14 source and sealed bundle are not edited by this transport change.

Load/unload orchestration and standalone loaded-state
tracking, take/dock controls, print submission, and on-printer layout
acceptance remain unfinished. These controls are local candidate work, not a
claim of deployment or hardware qualification.

Standalone filament identity editing now uses `WMP_SET_FILAMENT` from the updated
`wm_material` helper. It stores physical-head records in `wmp_filaments.json`
beside `tmt1.ini`, independently of vendor logical-slot mappings. The protocol is
`HEAD=<0..3> EXPECT=<settings SHA256> PROFILE=<hex UTF-8 JSON>`; the exact JSON
fields are `brand`, `material`, and `color` (`#RRGGBB`). The helper validates the
physical head, idle state and openACE absence, checks the expected revision,
then atomically replaces the settings file. Invalid existing files are reported
and never silently overwritten. No motion or heating occurs during an edit.
Native save completion requires matching identity readback. Configured identity
does not mark a head loaded. Existing vendor material indices remain unchanged;
the forthcoming standalone load/unload workflow must explicitly consume the
physical-head identity when choosing its procedure.

Physical attachment is now projected from `wm_material`: saved physical head,
Hall range, lock sensor, dock sensor, and active extruder must agree. Merely
activating a Klipper extruder is not evidence that the carriage picked it up.
The distance-step macro repeats these checks at execution time. The helper also
publishes a process session ID so a Klipper restart invalidates native requests.

## Native local-file preview handoff

The candidate now intercepts stock 1.1.13 `draw_preview` at `0x537710` (verified
32-byte entry window and PC-independent 16-byte trampoline prefix). Local-file
and history callers populate `gcode_print_path` (`0xe643278`) before this call;
the hook copies that path on the GUI thread and queues the owned preview. The
worker queries Moonraker metadata with a percent-encoded filename. Filament type
and `preset_colours` arrays become sliced rows without dropping index positions;
missing or invalid colours are shown as unknown gray. File metadata changes
invalidate preview mappings. Invalid/missing metadata is a visible error and
never invents a usable mapping. USB selection retains the stock copy workflow.

The handoff is covered by the native LVGL test harness through Runtime polling,
page creation and real rendered label content. This does not validate the hook
on hardware. Thumbnail display and source-route projection are now connected; print submission
remains incomplete and Start stays disabled. No browser page is involved.

Preview source choices now project actual routes: openACE `default_tool_map`
(including `blocked_tools`), or standalone `box_modify_t0..3`. Physical heads,
ACE slots and virtual tool IDs are never treated as interchangeable indices.
Disconnected/unassigned sources and blocked routes cannot be selected. The UI
matches material names case-insensitively, without inventing compatibility
between different materials; colour and brand differences do not prevent a
selection. Unknown material requires correction before selection. This is a
preview filter, not a substitute for backend admission at print submission.

A single eligible route is selected by tapping its source card. Multiple aliases
open a native scrolling tool-route chooser. Connection/routing changes invalidate
existing choices. Start is enabled only with the matching helper protocol and
verified native print-context adapter.

## Native thumbnails

The worker obtains the G-code root from Moonraker `/server/files/roots`, resolves
thumbnail paths relative to the selected file, and requires resolved paths to
stay under that root. Only regular PNG files up to 1 MiB and 800 × 800 pixels are
admitted. Actual PNG header dimensions are checked independently of metadata.
A private immutable copy is made under `/tmp`; the cache retains at most eight
files. LVGL uses its existing PNG decoder and POSIX filesystem driver to render
the copy, scaled to fit with its aspect ratio preserved. The thumbnail button
opens the same image in a larger owned modal with X to close. Missing or rejected
images show an explicit placeholder. Decoder appearance still requires native
hardware acceptance; host tests verify path/bounds/cache and widget dispatch.

## Standalone completion priority (2026-10-31)

The native screen must be usable without openACE; this is a completion target,
not a mode intended to remain a collection of stubs. openACE-specific additions
remain conditional on positive backend detection. Unavailable status must not
silently switch ownership to standalone.

| Standalone workflow | Current candidate | Remaining work |
|---|---|---|
| Head temperature | Physical heater commands with target readback | Hardware acceptance |
| Extrude/retract distance | E-only macro, attachment/temperature checks, completion receipt | Hardware acceptance |
| External filament profile | Per-head identity persistence and readback | Hardware acceptance; profile import remains separate |
| Load/unload | Screen flow exists; dispatch disabled | Explicit procedure, material settings, progress, loaded-state evidence |
| Take/dock | Screen flow exists; dispatch disabled | Reviewed movement and failure policy; attachment readback |
| Print preview | Metadata, thumbnail, source selection | Submission with validated mapping and stock print options |
| Home filament shortcut | Native child of stock button | On-device layout/touch acceptance |

Proposed load/unload completion policy for discussion: ask the operator to
confirm filament flowing / filament removed after the procedure. Sensor presence
and a completed extrusion command alone must not claim nozzle-level success.
Configured profile identity is separate from physical loaded state. Restart or
uncertain execution must not preserve a falsely confirmed state or repeat motion.
This policy is not yet implemented or approved by the operator.

Take/dock must not simply invoke the existing broad stock routines under a new
button label: their retry homes, heating and wiping are documented in
`docs/filament-motion-audit.md`. Backend gaps should be reported explicitly while
these procedures are developed. None of this authorizes printer activation.

## Standalone print submission audit (2026-10-31)

Verified against stock 1.1.13 client SHA256
`b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715`:
`start_print_prepare()` at `0x539ec4` waits for file-copy completion, conditionally
sends `SDCARD_RESET_FILE`, then sends `G30` or `G31` according to
`select_leveling`. It iterates four configuration entries, sending
`SAVE_VARIABLE VARIABLE=box_modify_t%d VALUE=%hhd` and the corresponding
`box_modify_t%d_backup` command. An unset destination falls back to that entry's
index. It marks `is_print_from_screen` and passes `gcode_print_path` to
`start_printing()` at `0x6146b8`, which constructs a request through
`json_print_a_file()` at `0x5584cc` and sends it through the existing websocket.

This sequence is evidence for preparation requirements, not authorization to
call that callback with stale stock mapping globals. The native preview owns
its selection and must submit that selection explicitly. The timelapse setting's
complete downstream effect still requires hardware acceptance. The candidate
uses the public backend submission path instead of the stock websocket callback.
Empty or failed metadata also rejects Start in
the controller even if a backend mistakenly advertises submission capability.

A standalone submission adapter must validate the file and physical destinations,
prepare both live and backup mappings, preserve leveling/timelapse semantics,
and obtain evidence of the intended job starting. An uncertain submission must
never auto-retry. openACE submission must instead pass its virtual print map to
its public print boundary; it must not write vendor mappings as routing truth.

Further evidence: `save_timelapse_flag(bool)` at `0x6280e8` writes the `system`
section's `timelapse` key in `tmt1.ini`; direct callers occur at `0x52efa8` and
`0x52f034`. The latter toggles the client `timelapse_flag` global before saving.
Thus merely setting a Klipper timelapse macro variable would not yet establish
parity with this client setting. Its consumers still require tracing.

The bundled Moonraker `klippy_apis.py:start_print` ultimately issues
`SDCARD_PRINT_FILE FILENAME="..."`; its former explicit `PRINT_START` call is
commented out. In live macros, G30 enables START_PRINT's adaptive mesh flag and
G31 disables it. Submission should not inject another START_PRINT invocation.

## Native preview options and stock timelapse consumers

The native file-preview hook now snapshots `select_leveling` (`0x384ea58`),
`select_Time_lapse` (`0x386ee09`) and `timelapse_flag` (`0x386ea54`) from the
hash-verified client on the GUI thread. It passes the snapshot with the selected
file; the screen initializes options once when that preview opens. Status
refreshes do not overwrite subsequent operator choices. A disabled global
timelapse setting disables the preview toggle and explains that Video settings
must enable it first. This is UI staging only; it does not mutate client globals
or start a print.

The flags have distinct meanings. The preview event handler toggles
`select_Time_lapse` at `0x536a94`. Its consumer in `parse_gcode_move` reads it at
`0x634c5c` and, subject to additional position/state conditions, sends
`TIMELAPSE_TAKE_FRAME` at `0x634d28`. Another consumer reads it at `0x63dd38`,
sends `TIMELAPSE_TAKE_FRAME` at `0x63dd88`, sends `TIMELAPSE_RENDER` at
`0x63dddc`, then clears the selection at `0x63de00`. These strings and addresses
were checked directly against the stock ELF. The containing state-transition
branch and all prerequisites still need review before native submission can
set this flag. No duplicate WM+ frame producer should be added around this
stock behavior.

## Standalone submission backend (not yet connected to native Start)

`wm_material` now registers `WMP_START_PRINT REQUEST=<hex UTF-8 JSON>` and
publishes `print_start_protocol: 1` plus `print_submission`. The strict request
contains `id`, `session`, `profile_revision`, `file` (`path`, `size`, `modified`),
`mapping` (sliced tool string → physical head integer), `expected_mapping`
(the four existing vendor mappings), and boolean `leveling`.

The command requires openACE absence, idle print stats, a non-paused/non-active
SD context, the current helper session, unchanged filament settings and mapping,
installed selected heads with configured filament identities, and an exact
regular file within the SD root matching the preview size/mtime. Filename
characters that can alter the submitted G-code are refused. This is file identity
checking, not cryptographic verification or a guarantee against concurrent file
replacement. Native metadata must still supply and validate every sliced row.

After validation it writes live and backup mappings, sends G30/G31, verifies the
mapping readback, rechecks admission/profile/file identity, then sends the public
SDCARD_PRINT_FILE command once. It does not independently issue START_PRINT,
homing, heating or purge around that command; the selected file and the existing
SD/startup handlers retain their normal effects. A failure after preparation
begins leaves an `unknown` receipt because settings may have changed or the print
may have begun. It does not roll back beneath a possibly running job. Attempted
IDs cannot be reused in that helper session, including after partial failure.
`submitted` means the SD command returned successfully, not that startup or the
print completed. The native adapter must confirm the intended running job.

The existing material component installs this helper file; no additional module
is required. Native request construction, client context coordination and job
admission are implemented below. All validation so far is local. No printer
activation has occurred.

The C++ standalone adapter now builds this request from the selected preview,
resolving physical head indices from authoritative route records rather than
using displayed T aliases. It validates complete sliced-row coverage, source
availability/material eligibility, options, file identity, and the transport
size bound. Each adapter instance uses a random request-ID prefix so a client
restart does not immediately reuse the helper's attempted IDs. Dispatch is
one-shot, and successful HTTP alone does not establish admission: the adapter
requires the matching helper receipt plus that filename in printing, paused or
complete state. Tests cover the serializer, a different active filename, rejected
routes, context refusal and context exceptions.

A native print-context preparation callback is mandatory. Binary review confirms
why it cannot be omitted: `parse_print_stats` reads `is_print_from_screen` at
`0x63db78`. If true, it clears the flag and skips the loop; if false, the loop at
`0x63dbb8` sends `SAVE_VARIABLE VARIABLE=box_modify_t%d_backup VALUE=%hhd` with
identity indices. The new submission's backup mappings could otherwise be
rewritten by the stock parser. The native implementation below stages that
context and retains ownership while a submission outcome is uncertain.
For remote starts, the native sender suppresses the four exact identity-backup
writes only from the verified parser return PC 0x63dc20 and with fresh standalone
ownership. Managed submission owns its backups; PAUSE snapshots the actual live
mapping before RESUME. Other callers, nonidentity writes and other owners retain
the stock path. This prevents redundant writes queuing behind SD work and failing
after cancellation; the backend generation fence remains unchanged.

## Current standalone Start integration

The hash-verified ARM runtime now binds `PrintContext` to the stock screen-start,
per-print timelapse and global timelapse flags. The worker prepares these byte
flags immediately before the one-shot helper request, matching the stock
worker-side start preparation. It does not access LVGL or mutable stock strings.
An outstanding stock screen-start flag or unavailable requested timelapse refuses
preparation without changing either flag.

The helper now records a matching `refused` receipt for identifiable requests
that fail before preparation; a duplicate attempted ID never replaces its prior
outcome. The adapter can reconcile a late matching refusal/admission even after
an HTTP error. A confirmed refusal restores the prior flags only if they still
match this preparation. Changed/consumed flags are not overwritten. Unknown
outcomes retain context ownership and prevent a second submission. Confirmed
admission leaves flags for the stock parser's normal lifecycle and closes the
owned overlay once, exposing the existing running-print UI.

Runtime enables Start only when this verified context adapter and the appropriate
standalone/openACE helper protocol are present. This is a local
candidate implementation, not a hardware qualification. Refusal restoration,
unknown outcomes, delayed receipt matching, and route serialization are covered
by host tests; actual stock transition timing still requires printer acceptance.

## Physical destinations in standalone preview

Standalone preview now offers one `head:hN` destination per installed physical
head, labeled `Head N · External`. It no longer limits choices to heads that
happen to appear in the previous print's `box_modify` map, or asks the operator
to choose among duplicate aliases for the same head. The saved four-entry map
remains an explicit submission expectation and part of the configuration revision;
a change invalidates pending preview selections. Submission resolves each sliced
row to the chosen physical head and prepares the new map through the helper.

openACE preview still uses its authoritative T routes. Multiple virtual aliases
for one ACE slot still open the explicit alias chooser. Tests cover a standalone
head absent from the old map, physical destination serialization, map drift, and
retained openACE alias selection.

## Standalone filament state and debugging

Normal UI workflows do not ask the operator to confirm loaded/empty. The head
card displays state; Load and Unload execute the corresponding procedures.
Successful Load sets the persistent per-head loaded flag. Successful Unload or
a clear sensor clears it. Sensor presence with a false flag means inserted,
not loaded. Klipper restart preserves the flag and reconciles sensor readings.

`WMP_CONFIRM_FILAMENT HEAD=N STATE=loaded|empty SESSION=... EXPECT=...` is a
legacy development/recovery utility, not a normal UI action or acceptance gate.
It records only an in-memory operator check with idle, ownership, configuration
and sensor-consistency checks. It does not heat, move, or set the persistent
loaded flag. Do not use it as a substitute for Load or Unload.

## Standalone completion boundary

Temperature controls, bounded extrusion, filament metadata, Load/Unload,
Take/Dock and preview/mapping have implementations. Implementation and host
checks do not establish physical acceptance. The current release and remaining
hardware gates are tracked in
[the standalone completion checklist](../../docs/ui/standalone-completion.md).
No-openACE acceptance is separate from openACE acceptance. Profile importing is
deferred; built-in brands/materials and manual metadata editing are the current
scope.

## Standalone Load/Unload procedure

The external Load dialog offers filament metadata editing and CANCEL / LOAD.
Preparation handles required XY homing, head pickup, purge positioning and
heating; it must not home Z. The current load recipe feeds 55 mm, performs a
50 mm initial purge, then wipes. Those distances still require material/color
transition qualification and are not a guarantee for every material.

Unload uses the loaded identity and material recipe. Successful completion
clears the loaded flag and asks the user to remove filament. A still-present
sensor alone must not restore the loaded flag. Both flows display numbered
stages and heating temperatures. Follow
[the current filament-management contract](../../docs/ui/standalone-filament-management.md)
for persistence, ownership and service behavior.

The native adapter submits once and reconciles operation receipts. A transport
timeout does not cause a resend or prove failure. Unresolved operations remain
unresolved until backend evidence establishes their outcome; manual operator
confirmation is not a routine recovery step.

Brand and USB profile-file selectors now use native scrolling panes like the
ACE/source and route selectors. USB enumeration/import remains a visible backend
stub; the list layout supports all reported entries without Next/Previous paging.

## Native navigation and unsaved drafts

Home, Files and the retained XYZ/Video/Wi-Fi/General destinations now pass through
the shared controller before the native runtime closes its overlay. Dirty edits
show Keep editing / Discard changes. Keeping the draft cancels the pending stock
handoff; discarding completes it. Home explicitly navigates to `main_page`, so
it does not accidentally reveal an underlying Settings or preview page.
Native lifecycle tests exercise real touch callbacks for each destination,
including keeping a draft and subsequently discarding it. Recovery overlays and
external stock ownership changes retain their existing priority behavior.

## Adoption completion

A matching adoption receipt must be accompanied by the new logical unit in
status before the controller marks it complete. While the operator remains on
the operation page, completion opens that unit's setup draft with a return path
to Filaments. This happens once: repeated receipts cannot overwrite assignment
edits. A late completion does not steal navigation from another screen. The
candidate chooser uses one scrolling viewport, including discoveries beyond the
first three units; its children retain consistent sizing below the viewport.

## Filament choices

The native material control opens a full-width scrolling selector. Standalone
status publishes the helper's 18 supported material names, including variants
such as PLA Silk and PETG Matte; it no longer restricts the screen to five small
buttons. A configured custom material remains visible and selected even when it
is absent from the catalogue. Selection changes the local draft only.

Generic is always present in the brand selector. Other configured source brands
are enumerated without claiming an imported profile library exists. The openACE
editor supports brand and colour changes to existing profiles. Material changes
and new profiles still require a profile-temperature policy. Standalone identity
persistence remains connected.

The candidate-only `typed_management.hpp` extension validates brand edits both
when queued and when the worker rebuilds the command against fresh status. It
preserves existing profile fields and rejects changed preserved values before
delivery. Colour-only edits preserve the original vendor value. The sealed
native source and installed bundle are not modified by this extension.

## Save completion and return paths

A successful configuration receipt alone does not dismiss an editor. Unit name
and assignments, or filament identity, must match backend readback. Once they do,
Save & exit returns from the operation screen to the originating Filaments or
Toolheads screen and clears only the submitted draft. Returning to edit during
an outstanding save preserves any newer changes and keeps that editor open when
the older save completes. Repeated receipts do not replay navigation.

## Preview chooser revision boundary

An open source/route chooser is bound to the preview revision at opening. A file
or routing revision change clears the assignments, closes that chooser and asks
the operator to reopen it. Queued selection events from the old chooser cannot
accept a route in the new context. Unknown sliced-row IDs and stale status also
refuse selection. This complements the file identity and mapping checks at print
submission; it is a UI context boundary, not a replacement for backend validation.

## Review export

After building, run `python3 tools/package_unified_ui_review.py` to create
`analysis/unified-ui-native/review.tar.gz`. This does not replace the sealed
install bundle or touch a printer. It rejects changed artifact/source/runtime
bytes before replacing an existing export, and archives the exact bytes it
verified. The archive contains the candidate manifest and ELF, repository-relative
build inputs, helper/macros, GPL license, workflow notes and regression tests.
Review context is distinguished from compiled inputs in `review-manifest.json`.

The deterministic archive has its own printed SHA256. It is explicitly marked
non-installable, activation unauthorized, and hardware acceptance outstanding.
The pinned offline build recipe is included under `repo/`; rebuilding requires
that Docker image locally. This export supports independent review, not a claim
that outstanding Take/Dock, openACE distance-step or import backends have
been implemented. It contains no stock firmware binary or local credentials.

## Independent native-flow review fixes

The native surface Back control bypasses only the renderer target lookup (it is
not an App-rendered widget); it still uses App navigation and draft policy.
Normal button clicks retain generation/target checks. Scroll offsets are stored
by page/modal context and widget ID so returning from a unit editor restores the
Filaments list position without sharing it with a source-picker dialog.

Discovery labels show observed USB serial/path separately from the internal
observation token. Stale Home data now retains an opaque “Status unavailable”
overlay instead of exposing vendor filament icons under openACE. Toolheads show
Mounted, Not mounted, No head mounted or Attachment unknown. For either owner,
`active` requires helper attachment evidence as well as the selected physical
extruder; missing evidence is not treated as mounted. The helper is queried in
both modes. These remain local implementation findings, not hardware acceptance.

See `docs/ui/native-readiness.md` for the complete screen/backend inventory and
remaining acceptance boundaries.

## Physical temperature in openACE mode

The native backend routes temperature actions through the same physical heater
transport in both modes. This does not route M104/M109 virtual tools or select a
head. The request retains its actual owner/session/revision and confirms the
reported heater target after delivery. Configured heater limits apply in both
modes. In openACE mode, the current implementation requires an idle/completed
print and explicit `operation: null` evidence; missing or busy operation status
refuses the request. Delivery rechecks those conditions. Other standalone
actions remain unavailable under openACE ownership.

The idle check is observational, not an atomic backend interlock: another client
can start an openACE operation between the last status query and the heater
command. This is ordinary operator heater control, not a guarantee of exclusion
from concurrent ACE work. Strict exclusion would require an ACE-aware command
that validates state at execution time. Independent review found no ownership or
standalone-action bypass in this path and called out this concurrency limit.

This connection is host-tested and compiled, not physically accepted.

## openACE print submission preparation

`openace_print_request` builds the public `SDCARD_PRINT_FILE` command with a
quoted `OPENACE_MAP` of sliced-to-virtual pairs. It does not resolve those pairs
to physical heads or write `box_modify`. It requires fresh openACE ownership,
an idle/completed job, complete file identity, one eligible source per sliced
filament, compatible material choices, and available sources/heads. It rejects
ambiguous routes, unsafe filenames and noncanonical tool indices. Up to 32
sliced filaments are supported, with pairs ordered numerically.

The result carries the reviewed file identity, session, revision and print
options for delivery revalidation. The pure builder sends nothing. The native
worker now submits a bounded hex-encoded `WMP_START_PRINT` request through the
helper's `openace_print_start_protocol: 1` path. This checks both helper and ACE
sessions, ACE configuration revision, idle state, virtual pairs and the actual
file before preparation; then rechecks after G30/G31. It never writes vendor
mappings. The public `SDCARD_PRINT_FILE ... OPENACE_MAP=...` boundary retains
openACE's own preflight and frozen-map authority.

The exact helper request is frozen at the Start tap and compared again before
any flag staging or dispatch. Native flags are staged once. A matching helper
receipt alone is insufficient:
admission requires the intended printing/paused file and an active override job
with matching pairs and configuration revision. Uncertain responses are never
retried and can reconcile later from matching evidence. Helper restart invalidates
the preview revision. This is local implementation evidence, not hardware
acceptance.

## Idle ACE Unload

With `openace_unload_protocol: 1`, the helper publishes a reviewable unload plan
only for a verified ACE-loaded head while the printer and openACE are idle. The
token includes helper/ACE sessions, configuration revision and the complete
loaded record. Dispatch rebuilds that plan before sending exactly
`OPENACE_UNLOAD HEAD=hN`. The review describes possible head selection/parking,
heating, tip shaping and assisted retraction. It is not a distance-only retract.

WM+ adds no purge, eject-to-unit, resume or retry. Completion requires the same
ACE session, an idle operation and empty-head readback. Errors or unconfirmed
outcomes remain unknown and do not release another operation. Matching helper
receipts reconcile delayed responses. Paused replacement continues through the
existing owner recovery flow; this control is idle-only. External loading under openACE still needs its separate multi-stage adapter.

## Idle ACE Load

`openace_load_protocol: 1` exposes source-specific plans for an empty head. Only
connected ACE slots with recorded identities and eligible virtual routes are
offered. The review names the chosen slot and Tool T<n> and describes possible
head selection/parking, heating, feeding and priming. When several tool aliases
resolve to the same source/head, the lowest eligible tool is named explicitly;
changing that choice invalidates the review token.

Dispatch regenerates plans from fresh owner state, matches the reviewed token
and sends exactly `OPENACE_SELECT TOOL=n`. The token includes the loaded state,
source identity, destination, virtual tool, helper/ACE sessions and configuration
revision. No additional homing, purge or resume is queued by WM+. Completion
requires the same ACE session, idle operation, verified loaded destination and
matching material/colour. A successful command return alone is insufficient.
An uncertain outcome stays unresolved and is never automatically replayed.

This path requires explicit inactive openACE job-map evidence as well as idle
printer/operation state, so selection cannot use a frozen print map. It does not
replace paused recovery or the two-stage
external hand-fed load procedure. Hardware acceptance is outstanding.

## Procedure reviews after Print Preview

File metadata contributes to the displayed snapshot revision. Procedure plans
are rebound to that final revision after preview composition, so returning to
Toolheads can open a valid fresh Load/Unload review. This changes only the UI
revision, never the backend approval token. Changing the file while a review is
open still invalidates that review.

Opening a procedure modal captures the exact current plan. Begin requires that
same plan and an open procedure modal. A changed token, description, head, source
or context cannot be substituted silently, even if the screen revision happens
to remain unchanged. The operator must close and review the new procedure.


### Delivery staging export

After building the native candidate, export a new, verified staging directory:

```sh
python3 tools/package_unified_ui_delivery.py \
  --client analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client \
  --output /tmp/wmp-delivery-staging
```

The output must not already exist. The exporter checks the exact vendor profile,
compiled artifact, source inputs and runtime dependencies, creates a deterministic
source archive, and runs the installer verifier before publishing the directory.
It uses `client-preload/unified-screen1113`, separate from the historical package.

This staging tree is marked `packaging-control-only`; it is not a released
installer and cannot be activated by `deploy.py`. Do not change that marker to
bypass pending acceptance. Configuration files describe the matching baseline;
they must be reconciled with machine-specific settings and calibration rather
than copied wholesale to a printer. Existing filament data must be retained.
