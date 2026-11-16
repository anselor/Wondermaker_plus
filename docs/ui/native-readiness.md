# Native WM+ screen readiness

## Presentation correction — implementation is incomplete

### Standalone live review — 1 November

openACE is temporarily disabled for operator testing by commenting only
`[include openace*.cfg]` in the installed `printer.cfg`. Its configuration and
software are retained. The exact enabled/disabled config copies are on the
printer in `/home/t13dp/wmp/standalone-test-20261101/`. Local toggle runner:
`/tmp/wmp_standalone_toggle.py restore` (uses the cached Paramiko Python).
Restore checks that the current config still equals the disabled copy; if it
has changed, merge the include instead of overwriting other edits. Restart the
client/Klipper together only after an idle preflight. Failure during the mode
switch automatically restores the previous file and services.

Live verification: Klipper ready/standby, openACE absent from object list, four
physical extruders retained, all heater targets zero. No movement, heating,
filament confirmation, profile save or print was performed. Evidence is in
`analysis/standalone-screen-test/`.

Remaining WM+ standalone gaps:

- Filament overview/editor still uses the older stock card/inline editing path;
  migrate it to the new grouped external cards and modal Cancel/Save workflow.
- Attachment reconciliation: saved current head is index 1 (Head 2), hall Raw
  about 4580, lock sensor true and docked1 false, but active Klipper extruder is
  `extruder` (Head 1). The backend consequently reports unknown attachment and
  refuses every load/unload plan. Do not infer that selecting a head in the UI
  fixes this. Establish validated startup reconciliation with physical evidence.
- Take/Dock backend is unimplemented; see standalone-toolhead-procedure.md.
- Nozzle material/diameter display is connected; editing/saving is not.
- Load/unload has an E-only backend, but requires the selected head mounted and
  already at the recipe temperature. Integrate heating/wait/insertion/final
  confirmation into a coherent workflow. Stop/interruption reconciliation is
  unavailable. Physical qualification remains outstanding.
- Standalone identities and filament checks are empty on this printer. Profiles
  can be saved through WM+, and operator checks must agree with enabled sensors,
  but initial configuration/check prompts and restart recovery need a complete
  UI flow. Check-filament text also clips in the Toolhead footer at 800x480.
- USB filament-profile import remains a stub; file format, validation/conflict
  handling and backend import are incomplete. A list of supported material names
  is not a complete profile library.
- Native print preview/physical-head mapping/start admission are implemented,
  but end-to-end standalone print qualification is still outstanding.

Already implemented (not physically exercised during this review): physical
heater target setting, bounded E-only WMP_EXTRUDER_STEP with attachment/hot-nozzle
checks, standalone filament persistence, sensor-consistent operator checks,
source-bound load/unload plans, and standalone print admission. ACE adoption,
slot assignment/removal and drying are inapplicable when ACE is disabled.

### External filament card grouping — 1 November

External sources use the same four-column card geometry as ACE slots, in a
single External group below the units. Cards are ordered by physical Head 1–4,
independent of backend source order; heads with any ACE assignment are excluded.
The overview and print source picker share this layout.
Native lifecycle/runtime checks passed (2 tests). Installed mapped hash:
`5d14c9ad6a748bd3aa51f0b9ffff39b52f5073fd40efd8fce4fa5e6a839e6345`.
Live framebuffer `activation-stockwidgets-r12/05-external.png` under
`analysis/unified-ui-native` verifies Head 4 at single-slot width. Only one
external head exists on this printer; multi-head ordering follows the explicit
physical-head loop. Navigation only; final ready/standby with no operation/job.

### Toolhead load ownership and stock nozzle display — 1 November

Toolhead Load is visible only for a confirmed-empty head without ACE slots,
including when assigned ACE hardware is disconnected. The runtime also rejects
stale/synthetic ACE-head Load events. External loading passes the exact
`external:h<n>` source; ACE slot menus pass the selected slot. A preselected
source no longer renders the generic source chooser. External empty heads retain
the convenience filament edit control. Load/progress uses the WM text action
header, divider and opaque content, without hex codes in source descriptions.

Stock 1.1.13 `update_common_status` at `0x51dc9c` reads per-head current and target
integer arrays at `0xe6453d0` / `0xe6453e0`. It reads `all_filament_info` at
`0x384d078` as four eight-byte records (material byte +2; diameter float +4),
and maps material through the two strings at `0x386db68`. Toolhead display now
reads those same values on the GUI thread, after the existing binary/profile
verification. Material indexes and numeric ranges are checked. Temperature
admission and actual commands still use the backend snapshot; stock display
values never authorize motion/heating. No stock nozzle-setting function is called.

Native lifecycle/runtime checks pass (2 tests). Installed and mapped hash:
`a744084ebd81439e57cc5101d411a29ced568232515e6d8becdf6fa8e1ba0166`.
Live r11 framebuffers verify Home/Toolhead 28 / 0 and Hardened steel / 0.4 mm,
and no Load on confirmed-empty ACE Head 3. External Head 4 has unknown contents,
so no physical load was tested. The ACE slot-dialog walkthrough was incomplete:
automatic approval review rejected a repeated navigation tap as potentially
physical; no further load-menu interaction was attempted. Returned Home; final
state ready/standby, no operation/job. Evidence: `activation-stockwidgets-r11`
under `analysis/unified-ui-native`. Procedure layout/dispatch checks are host
regressions, not a claim of successful live physical loading.

### Compact stock action-row spacing — 1 November

Filament and drying dialogs reduce the action row from 48 to 34 pixels before
the divider, with captions at 2 pixels instead of 10. The first filament field
starts at 44 pixels instead of 64, with subsequent rows on 56-pixel spacing.
Dropdown font size and field height remain unchanged.
Native lifecycle/runtime checks passed (2 tests). Installed and mapped hash
`b9e9cd1702376675edce99b3f8d12f40a0a9b20d30e0a1435b15b5b1b6bc9a4b`
verified. Actual framebuffer: `activation-stockwidgets-r10/06-editor.png` under
`analysis/unified-ui-native`. Navigation only, no setting saves or physical
commands; final state ready/standby with no active job or operation. Injected
taps required retries.

### Modal background and per-unit drying — 1 November

Stock overview head tabs are hidden throughout a modal and restored when it
closes, including after vendor refresh. This removes their visible borders
around the inset editor. A lifecycle regression covers hide, refresh and restore.

Each ACE unit has a neutral sun / “Dryer ?” entry and a native per-unit drying
stub: humidity/current temperature, target/duration, and disabled Start/Stop.
There is no supported environmental/status or drying command contract in the
inspected openACE checkout. Unknown status is explicit; no readings or running
state are fabricated. See [openACE drying hand-off](openace-drying-handoff.md).
Native lifecycle/runtime checks pass (2 tests), including stale-dialog Close,
no command dispatch from disabled dryer actions, and restoring overview tabs.
ARM build: `31df4a6100117f34dca4683a3d474e464631b6cd695069f720ed89fbbeb19332`.
Activation evidence: `analysis/unified-ui-native/activation-stockwidgets-r9`.
Installed and mapped hash verified. Live framebuffers verify the drying stub,
restored overview tabs on Close, and the filament editor without underlying
head-tab borders. Injected taps occasionally needed retry. Navigation only:
no heating, movement or setting saves. Final state was ready/standby, unpaused,
with no active operation or job.

### Filament editor detail correction — 1 November

The filament dialog uses the unit/slot identity as its header title, with no
separate “Filament” title or repeated source subtitle. Its dedicated header has
right-aligned CANCEL/SAVE text actions and a divider; the actions retain large
invisible touch targets. Brand/material collapsed values use the stock 20-pixel
regular font, with a separate symbol font for their dropdown chevrons.
The colour row contains a tappable swatch and its hex value; the redundant
“Choose colour” button is removed. Save/backend capabilities are unchanged.
Native lifecycle and runtime compilation checks passed (2 tests). ARM build
SHA256: `0b8f455519d3b652f14eca5e9b6b2c69206f1c01736baf634c4642cdc43353ec`.
Installed and mapped hash verified. Actual Slot 2 framebuffers verify the title,
font size, hex/swatches, and text-action header; tapping the swatch opens the
stock colour picker. One injected tap needed retry. No colour was selected or
saved. Activation records: `analysis/unified-ui-native/activation-stockwidgets-r8`.

### WM action-bar conventions and reference review — 1 November

Filament and ACE unit editors place Cancel/Save in the upper action bar below the stock Settings tabs. Import Close,
adoption actions, removal confirmation and procedure actions also move up.
Filament editing uses Brand, Material and Colour field/value rows, with a real
colour swatch. Existing unavailable material-save behaviour is unchanged.

Slot taps open a compact Edit/Load/Cancel menu over that slot. Load passes the
exact source ID into the existing backend procedure review; it does not issue
movement while browsing or select a different slot sharing the same head.
The current contract requires a confirmed-empty head. Automatic replacement
(unload existing filament, heat, then load the selected slot) remains a backend
procedure gap; the UI must not synthesize this sequence from vendor macros.

Toolhead temperature is a single current/target button opening the stock numeric
keypad. Confirming the entered value submits it immediately through the typed
heater backend; 0 turns heating off. Heat is removed and an X shortcut also
submits target 0. The display continues to use observed current/target values.
Retract/extrude use stock-font chevrons and retain their existing
busy feedback and command semantics.

Stock 1.1.13 nozzle inspection distinguishes `setup_screen_nozzle_type` at
`0x52c070` from the homing-capable `start_nozzle_setting` at `0x510350`.
The type editor's event handler at `0x52bce0` immediately persists material
through `IniManager::modify` and diameter through `read_write_nozzle_diameter`
at `0x52d02c`. Reusing those handlers directly would violate Cancel/Save semantics.
A draft adapter, physical-head binding, and verified save/readback are still
needed; nozzle information remains read-only in Toolhead management.

openACE's `docs/roadmap.md`, “Supported drying control”, explicitly states that
low-level drying messages are not a supported operator command/UI. Humidity and
dryer state also need a supported projection into the WM screen contract.
The intended UI is per-unit humidity and a sun button opening dryer settings,
with coloured sun only for confirmed enabled state. No synthetic humidity,
enabled dryer control, AMS-style single-outlet topology, or spool-rolling command
has been added.

Validation: native lifecycle and runtime compilation checks pass, including the
slot-menu entry into procedure submission, missing-source refusal, top-bar editor
button placement and non-scrolling filament editor bounds. Temperature checks
cover direct submission of 210 and 0, stale context, heater limits, and duplicate
pending submissions. The final two host checks passed. ARM candidate SHA256:
`e28d7f0a1bfd4813a3f299cb182ea6599b8759872115816658c0b51a65713aaa`.
Actual r6 framebuffers verify the slot popup, field/value editor, swatch, and
upper Cancel/Save actions in the filament and unit dialogs. Final temperature
activation evidence is under `analysis/unified-ui-native/activation-stockwidgets-r7`.
The final candidate is installed and its mapped SHA256 is verified. The actual
Toolhead framebuffer confirms current/target plus X, stock-font arrow controls,
and no Heat button. Startup status took another navigation attempt to settle;
this does not establish complete touch reliability. No heating, movement,
settings save or print test is part of this walkthrough.

### Screenshot feedback correction — 1 November

The follow-up candidate changes filament and unit editing to opaque, bounded
stock-content dialogs. Cancel and Save stay visible. Filament colour is a swatch;
brand and material use popup lists. Material changes remain local previews with
Save disabled until a profile/temperature backend contract exists. Unit slots
use four-head dropdown lists in place, preserving the unit context. The larger
unit name itself opens the stock keyboard, Remove is red, and unsupported
assignment persistence disables Save with a short action-specific status.

The overview drops its heading and makes the selected head filter toggle off.
The verified thin decorative stock separator is hidden. Import is now only a
USB modal with an unavailable file-selection action; fabricated example-file
flows and the Uploaded profiles choice have been removed.

Toolhead controls use aligned columns and centred action captions. Loaded
identity includes ACE unit/slot provenance when reported. Convenience editing
is limited to an empty non-ACE-managed head. Mount state determines Take/Dock
text; unsupported commands stay disabled, and unknown mount state is explicit.
Nozzle diameter is read from Klipper configuration; nozzle material remains
unknown pending a verified data source. This does not establish load/mount
state from configured slot assignments or activate new movement handlers.

The first screenshot-feedback build was activated after idle preflight. Actual
framebuffers confirm the opaque unit dialog, tappable name, red Remove, four-head
popup, filament swatch/material popup and clean USB-only import dialog. Live
review exposed a remaining vendor separator, whose geometry is now checked
after layout on every refresh. The final host lifecycle/compile run passed
(2 tests), following 41 broader UI/package tests before the final popup changes.
ARM build succeeded with SHA256
`66cef8429b0cc1e7547b150ec4153c72efc144ad7d475342c941f150eba70fba`.
The final candidate is installed and mapped by the running client. Actual
framebuffers confirm the separator is gone and repeat-tapping the selected head
clears all highlights. One injected tap needed a retry; touch reliability is not
fully qualified. Final readback: ready, standby, pause false, no active openACE
job or operation. Returned to stock Home; no settings saves, heating, motion or
print submissions were issued.

Navigation-only evidence and rollback records are under local
`analysis/unified-ui-native/activation-stockwidgets-r4` and `-r5`.

Preview mapping rows no longer rebuild merely because the overall status
revision changes. This preserves button lifetime across unrelated refreshes;
it is a tested mitigation, not yet a hardware root-cause finding for missed taps.


### Authorized stock-widget activation and initial hardware findings — 1 November

The operator approved activation with “proceed.” Fresh checks found Klipper ready,
print standby, pause false, no active openACE job/operation, and the expected
1.1.13 client hash. The only runtime dependency difference was the reviewed
removal of `PARK_CURRENT_TOOL` after extrusion. That exact one-line correction
was applied with the native library; the installed helper, other macros,
printer configuration and other preload libraries were preserved. Each
activation saved rollback bytes and checked loader dependencies before stopping
the client/Klipper, publishing and restarting.

Actual framebuffer evidence now demonstrates the retained stock Home, sidebar,
status area, Settings tabs and File browser. Initial hardware review exposed
black inherited text, a reappearing stock action row, clipped material text and
half-size swatch clipping. Repairs set explicit stock-light label colour, keep
the vendor motion row hidden during refresh, fit the material font and use the
native-size swatches with non-overlapping identity/assignment rows. Host
lifecycle/compile checks and scoped independent review passed; actual repaired
Toolhead and ACE overview captures confirm these fixes. A longer 250ms remote
navigation tap opens the slot identity editor; 80ms injected taps were sometimes
missed by the client.

Local-file preview exposed a further integration gap: optional Knife pairing and
timelapse widgets were incorrectly required by the adapter. Current source
accepts only present, current-page, matching-action optional widgets; primary
Leveling remains required. Rebinding and Start admission remain guarded. Host
coverage checks missing/stale combinations and one-shot dispatch, and scoped
independent review passed. The final layout correction uses the firmware's 50px preview swatch asset and
moves the notice above the mapping rows. Candidate
`e386d49e39167c25947870cae5c059f5d04f44eb70b9a8d6d41e0a3a42c9c957`
is installed and verified mapped by the running client. Final framebuffer
captures confirm the corrected preview and grouped source selector, and return
to stock Home. The preceding candidate also demonstrated local draft selection
and thumbnail expansion. No print was submitted.

The final native lifecycle and compile tests passed (2 tests); scoped independent
review found no blocker in the preview geometry correction. Some injected
250ms touches still missed the preview buttons and slot selection; the selector
opened on retry. Touch reliability remains unresolved, not accepted. Investigate
input delivery and widget recreation on status refresh before attributing it to
hardware or declaring the interaction qualified.

Evidence and per-activation rollback records are ignored local artifacts under
`analysis/unified-ui-native/activation-stockwidgets*`. This review issues no
heating, extrusion, homing, tool selection, settings saves or print submission.
Standalone hardware behavior, physical operations and the remaining screen
walkthrough are not yet qualified. This is not a completed full-scope audit.

### Recovery ownership correction

Source audit found that `legacy_.tick()` recreated the old openACE setup badge
and panel whenever no manual/material recovery was active. Deactivating it only
on navigation did not prevent the next tick from restoring that competing UI.

`NativeScreen` now accepts a management-enabled constructor option, defaulting
to true for its separate legacy consumer. Unified Runtime passes false. Manual
recovery and material confirmation retain their existing owner; the idle branch
deactivates setup instead of creating it. This is a presentation-ownership fix,
not a new recovery protocol or permission to resume a print.

A host regression uses the existing native port fake to verify repeated idle
ticks create no objects, a recovery prompt still exposes and dispatches its
context-bound confirmation, returning idle removes it without setup, and the
legacy default still shows setup. This and native compile/lifecycle checks pass
(3 tests). Independent review caught the shared management-observation flag:
legacy deactivation previously cleared the unified worker's subscription. The
renderer now owns observation only in legacy mode; unified mode leaves that
flag to its worker. A reentrant HTTP regression verifies a GUI tick cannot
revoke observation or discard returned management data. Re-review found no
remaining blocker in this scoped correction. Final ARM rebuild passed. Historical candidate SHA256:
`0655054e4a40dfc5550a15a9dc711bdd095f372651e32b9eb7b34f1a3d73f8ca`. No activation occurred.

### Earlier offline verification

The complete `tests/test_unified_ui.py` and
`tests/test_unified_ui_review_package.py` run passed: 40 tests in 80.03s.
This covers controller/adapters, host native widget lifetimes and event routing,
USB copy binding, metadata/thumbnail handling, native compile/profile checks
and review-export integrity. It does not render the vendor client or establish
physical acceptance. That earlier candidate was unactivated at this checkpoint. Later activation and
remaining limitations are recorded above. See the
[current activation proposal](activation-proposal.md) for the screen-by-screen
stock-widget acceptance criteria and exact candidate hash.

### Filament operation outcomes and result re-entry

The existing stock-content procedure dialog now distinguishes pending,
complete/refused, and partial/failed/unknown outcomes. It retains the original
source and physical-head review context. Pending motion shows a disabled Stop
unavailable control; uncertain/partial failures show a disabled Resolve
unavailable control and explicitly do not invent completed/remaining distances.
The backend has no connected stop/reconciliation contract here.

A compact Result control in Toolheads reopens the retained filament result
without resubmitting a procedure. Its availability is separate from the busy
receipt, so failed and completed outcomes can still be viewed after Close.
Standalone Check filament remains alongside Result for the post-motion check.
Hidden Toolhead pages cannot dispatch these actions. Independent review found
the terminal-result availability gap, which this separation corrects. Final
host lifecycle and native compile regressions passed. Re-review caught an
additional Result/footer overlap at the minimum panel height. Result now fits
between Check filament and the footer's left edge; non-overlap regression covers
640/670-pixel widths and 300/320/340-pixel heights. Stock MyriadPro16 glyph
advances sum to 45.25px for Result; its 56px button now supplies a 48px caption,
with 4px horizontal clearance from both adjacent controls at minimum width.
Final host lifecycle and compile checks passed (2 tests); offline ARM rebuild passed.
Candidate SHA256:
`ae99eef044469ad72826a3c59c328f47730855a0cea42fd7eacad8f48c2c1f35`.
No native activation occurred.

### Import workflow layouts — native preview-only navigation

The profile-import panel now includes source selection, example JSON/ZIP file
selection, a profile summary, conflict comparison/actions, and a result layout.
Each stage remains inside the stock-content dialog, with a vertically scrollable
body and fixed Back/Close controls. A persistent heading says this is a layout
preview and that no files are read or imported. Import and conflict decisions are
disabled and their callbacks cannot dispatch actions. Results use unset counts
and explicitly say that no import occurred. USB/upload buttons navigate these
examples only; this is not the G-code USB copy feature.

The schema, actual file listing, profile validation, conflict policy and importer
remain backend gaps. The implementation demonstrates their intended screen flow
without inventing a working import command. Host lifecycle and native compile
checks passed, including both ownership modes, all stage transitions, return
navigation and disabled-action non-dispatch. This source update is included in the ARM candidate identified above; rendered
layout still needs qualification.

### Toolhead filament edit icon — stock font

The Toolhead identity area now has a small transparent pencil control in its
upper-right corner, using the existing `edit-filament` route. It has no covering
card or separate Edit filament row. The original stock colour/material widgets
remain; the material widget moves down 10 pixels to leave space for the icon.
Busy or stale status disables it, and hidden-page/queued taps are consumed.

The verified 1.1.13 ELF contains `lv_font_montserrat_14` at `0x363b260`; its
second character map includes U+F304 (the edit symbol). The font object is now
included in the generated exact-client profile windows. Host lifecycle and
native compile tests passed the route, transparency, geometry, hidden-page and
busy cases. Offline ARM rebuild passed, including the editor-navigation changes.
Candidate SHA256:
`9f14adaf6385183bbcb8a09b6bdbc7102905a07ebc808ecec371e96259685ee9`.
Actual rendered sizing is unqualified; no printer changes occurred.

### Editor navigation — consistent local discard

ACE filament and unit editors now state that leaving the page discards unsaved
edits. When the stock Filament page becomes hidden or invalid, its tick clears
local source/unit drafts and editor subviews. Returning to a reused stock page
therefore behaves like reconstructing that page. Registration operations and
pending identity receipts are not cleared by this navigation cleanup; leaving
an editor is not cancellation of a submitted backend operation.

The native lifecycle regression passed a hidden/reused-page case: an unsaved
unit rename is discarded and reopening unit details shows the observed name.
This change is included in the Toolhead edit-icon ARM candidate above. Rendered
navigation remains unqualified.

### USB Runtime integration — host candidate

The constructor hook now adopts USB previews as well as local previews. It
suppresses vendor metadata writes and consumes vendor copy/start callbacks for
the managed content, retaining the original constructor and widgets. Runtime
starts source inspection on its dedicated worker using the verified 1.1.13
vendor USB root `/home/t13dp/printer_data/gcodes/USB`. Copy is enabled after a
successful inspection and fresh idle printer status. Submission creates a fresh
random destination directory; copy completion alone causes no navigation.

Review local file is a separate click, gated by the original owner/session/
revision and fresh idle status. It switches the vendor selection to the confirmed
local destination and constructs the existing managed local-file preview, where
metadata, mapping and explicit print admission are reviewed separately. Closing
or navigating away from the USB preview does not cause a completion callback to
reopen it. Unknown copies remain blocked from retry in the worker.

The Runtime host integration test passed actual temporary-file inspection,
fake Moonraker reservation/copy, no automatic review, explicit Review and closed
view non-navigation. The tests do not prove live widget geometry, actual USB
mount behavior, or firmware metadata scheduling. Independent integration review found a missing destination locator: copied and
unknown messages now include the destination, and reopening USB previews retains
an unresolved receipt instead of hiding it or allowing another copy. The final
worker/lifecycle regression passed after this correction. Independent re-review
confirmed receipt retention and identified fixed-height message clipping. The
message now retains LVGL's content-sized label height with a constrained wrapping
width, inside its existing stock panel with vertical scrolling enabled; long
recovery paths are retained in full. Final lifecycle regression and ARM build
passed; independent re-review found no remaining blocker in this scoped change.
Candidate SHA256:
`afd5e788a3b6c6d8e5c0245514ca019ca62a03f335bd0f83bde3a3f41a89f643`.
Actual rendered USB screens and real large-file copies remain unqualified. Nothing was activated.

### USB source inspection — worker integration

The copy worker now accepts a preview-origin-bound inspection request before
Copy. It reads a nonempty regular file beneath the supplied USB root using
descriptor-relative traversal; child symlinks, traversal, missing files and
non-file inputs are rejected. The vendor USB root may itself be a mount symlink.
Inspection records size, device/inode and modification timestamp. Copy for that
origin must match the inspected path and size, and the worker rechecks the
record before any HTTP request, then refreshes printer-context evidence.

Host tests passed inspection-to-copy, mismatched path/size rejection, changed
file rejection before POST, and symlink/FIFO/missing/traversal rejection. These
stat fields are not a content hash and do not eliminate a change during the
subsequent Moonraker copy. Local metadata and print admission remain separate.
Runtime still needs to supply the confirmed USB root and wire this worker to
the stock USB preview adapter. No printer filesystem was accessed.

### USB preview widget adapter — not yet wired to the constructor

`StockUsbPreview` adopts the existing vendor preview controls. The stock title,
thumbnail, content and footer remain; source swatches are hidden during copy
review and explanatory text is added inside their stock parent. The original
Start button becomes Copy to printer, then Copying, then Review local file.
Review is a separate operator action and never sends a print command. Options
and mapping callbacks are disabled/consumed in this mode. Close remains usable
during copying and explains that it does not cancel the copy.

The native lifecycle test passed copy-only callback gating, one-shot Copy and
Review actions, readiness gating and retained page ownership after Close.

The adapter is not yet connected to `unified_draw_preview` or Runtime. Source
size capture and a correlated worker-to-local-preview handoff are still needed.
This does not change the installed/vendor USB path or complete USB support.

### USB copy worker — not yet connected to the screen

`UsbCopyWorker` runs the existing reservation/copy adapter on a dedicated thread.
The UI submits a reviewed source and monotonic preview origin, then reads a
copied result under a short mutex. Network requests run outside that mutex.
Status observations remain independent, and the worker rejects missing/stale or
changed printer context before dispatch. Repeated origins cannot resubmit;
unknown copy outcomes block further submissions even from a newer preview.
No result triggers navigation, print admission, or printer motion by itself.

The worker and transport are intended to live for the Runtime's lifetime, with
thread join only during shutdown, never when a preview closes. The host test
passed blocked-copy responsiveness, wrong-origin isolation, repeated-tap and
unknown-outcome rejection, changed-session rejection and missing-status
rejection. Independent review found no worker concurrency/lifetime blocker. It
noted that status is checked before the operation, not between mkdir and copy;
a later status change does not cancel copying and cannot authorize print
admission. Receipt validation proves path/size, not content identity. Aged-status
and in-flight shutdown coverage remain to be added. `UsbCopyHttp` is the dedicated
transport; the normal status/G-code transport intentionally rejects file POSTs.
Runtime construction,
source-size capture, the Copy button and confirmed local-preview handoff remain
unimplemented; this is not completed USB screen support.

### Scoped dialog backdrops — local source change

Explanation and profile-import dialogs now leave the retained stock page visible
around their dialog panels. Their content-sized input blocker is transparent,
borderless and non-scrolling; it remains clickable to prevent taps reaching
underlying controls. The actual dialog panel continues to use vendor styling.
No stock widgets are deleted or replaced by the backdrop. Rendered appearance
and physical touch behavior still require qualification.

Take/Dock remains unconnected: the current native backend supports temperature,
step extrusion, identity, filament procedures and print admission, but has no
physical head-movement adapter. It must not be connected to virtual `T<n>` or a
vendor macro merely because the labels appear similar.

### Material selector preview inside the stock filament pane

The ACE identity editor's Material control now opens a selector preview in its
existing scrolling stock-content pane. It displays the current material and
clearly labelled example choices, using vendor button styles and font. All
choices are disabled and their callbacks are consumed without backend dispatch.
Back returns to the same filament draft, retaining unsaved brand/colour changes;
it remains available after status becomes stale. No new app shell is created.

The native lifecycle test passed preview entry, disabled-choice non-dispatch,
draft preservation and stale-status Back. Material profile/temperature policy is
still a backend gap, so these example choices cannot be saved. Actual rendered
appearance remains unverified.

Offline ARM build passed for this selector and the distance-style correction.
Candidate SHA256:
`2a50bef515ec9783f7d7eb0dca49b262e8c0eea2cc436562cf51230df69959d3`.
No printer access or activation occurred.

### Stock selection treatment — local source verification

Toolhead distance choices now use the same vendor selected/unselected style
objects as the head tabs. The numeric caption stays unchanged instead of using
brackets to indicate selection. Controls remain children of the stock content
object; this change adds no panel or replacement screen. The native lifecycle
test checks selection transfer from 25 mm to 10 mm and preserves existing
stock-widget ownership checks. That test and the USB copy adapter host test
passed (2 tests). These are host checks, not rendered visual acceptance; this
source change has not been rebuilt into an ARM review artifact or activated.

### USB preview boundary — offline evidence

USB preview remains on the vendor path; it is not yet integrated with WM+ source
mapping. The exact 1.1.13 client review establishes a separate copy boundary:

- `copy_to_local()` at `0x53a2e0` snapshots `gcode_print_path`, checks the USB
  source file size/local space, and submits a copy request at `0x53a620`.
- The request arguments are **source `gcodes/USB/<selected path>`**, destination
  **`gcodes/<selected path>`**. This is a copy out of the USB area, not into it.
- `copy_a_file_or_directory()` at `0x6145ac` constructs JSON through
  `json_copy_a_file_or_directory()` at `0x559098`, with `source`/`dest` fields,
  and sends it through the client's websocket.
- Completion is tracked with shared `current_copying_file_name` and
  `copying_file_result`; USB disappearance/timeouts produce failure. This shared
  state is not an immutable WM+ file/operation receipt.
- `start_print_prepare()` is separate; its call to `start_printing()` is at
  `0x53a1f8`. Completing a copy must not automatically authorize mapped printing.

`tools/inspect_stock_ui.py` now validates the exact client SHA, exports the USB
symbols/globals, checks the four direct ARM call targets, and verifies the copy
field/path literals. It passed against the local firmware binary. Offline
assembly evidence is under `analysis/stock-widget-integration/usb-*.asm`; no
printer access, runtime pointer access, or binary patch was performed.

Integration must first bind an explicit copy request/result to the selected USB
file and destination, resolve same-name local-file conflicts, then fetch/review
the confirmed local file through the existing unified preview. The bundled Moonraker file manager confirms that an existing file destination
is overwritten using `shutil.copy2` and reported as `modify_file`. Its directory
POST uses atomic `os.mkdir`, so WM+'s copy adapter reserves a fresh directory
before copying and accepts only an exact `create_file` receipt with matching size.
The vendor completion callback's correlation remains unverified. Merely removing the USB exclusion from `unified_draw_preview` would
skip this boundary. USB UI behavior remains unchanged: the adapter is not yet attached to the
preview. A dedicated `UsbCopyHttp` transport now permits only directory reservation
and copies from `gcodes/USB/` into a `gcodes/WM_USB_<32 hex characters>/` directory
with the same basename. It rejects printer commands, arbitrary destinations,
extra request fields and traversal paths. It shares bounded loopback HTTP framing
with the native transport; status polling still uses its original allowlist.
A dedicated copy worker, explicit Copy action, source-size capture and local-file
review handoff still need integration. The copy adapter alone is not USB support.

### Mounting status and removal impact — validation in progress

Toolhead management now displays the selected head's projected mounting evidence
in the existing stock header label. The label is placed above the head tabs;
there is no new covering panel. Supported values are Mounted, Not mounted and
No head mounted. Missing, duplicate or unrecognized head evidence displays
Attachment unknown, and stale page status displays Printer status unavailable.
Filament loaded state does not imply mounting.

The native ACE removal preview now lists current tool routes joined by exact
source ID to the selected unit's slots, including physical heads. Other units'
routes are excluded. Stale observations are labelled last-known. Route changes
participate in the pane redraw signature. The preview explicitly says removal
and resulting tool numbers are unavailable; no new T numbers are guessed.
Confirm removal is disabled and its callback is consumed without dispatch,
including queued/programmatic taps. Cancel preserves the unit draft.

Focused native lifecycle runs passed removal impact/exclusion, non-dispatch and
mounting-state checks. Independent review confirmed the removal scope and header
geometry, but found persistent operation notices could hide mounting state. The
header now preserves mounting alongside notices and head selection clears old
notices. Final native lifecycle regression and ARM rebuild passed; independent
re-review confirmed the correction. Candidate SHA256:
`8fbf725263f276e83d1637e1be4ca1fc75c0594a393d128e70ce5403409b7e91`. No printer access or activation occurred. Visual qualification and the
larger remaining flows are still incomplete.

### Adoption setup and identity return flows — review candidate

Completed adoption now offers Review slots. It opens the exact new logical unit
only after the receipt is complete, owner/session still match, status is fresh,
and exactly one registered unit with that ID is present. Receipt acknowledgement
alone does not enable setup. The transition submits no command; Back returns to
the prior overview scroll position.

Toolhead-origin ACE identity editing captures its originating physical head.
Back returns to that Toolhead and explicitly indicates local edits are discarded.
If status becomes stale, its label becomes plain Back / discard and it stays in
the existing overview; it neither requests nor defers an unavailable head route.
Entering from Filaments retains the overview return behavior. Stock-sidebar
navigation still needs consistent dirty-draft treatment, independently of this
explicit Back action.

The focused native lifecycle test passed initial exact-unit/setup and
head-return coverage. Independent source review confirmed navigation-only
behavior and supported-width geometry, and identified the stale-label case
corrected above. Final focused test and offline ARM build passed.
Candidate SHA256:
`88fc7f5fe31a51809de8bcb99b6e075348e68c2379ce852bdfa59e032ade2bfd`. No printer
access or activation occurred. The independent broader review and remaining
screen gaps are recorded in [workflow-review.md](workflow-review.md).

### Retired full-screen fallback — validation in progress

Runtime no longer instantiates the prototype Renderer or opens its opaque
full-screen shell. The obsolete `request_preview` entry point and request-8
render path have been removed. Navigation now accepts only stock-integrated
routes (close, four Toolheads, Filament, and four identity entries); unexpected
IDs are ignored and cannot overwrite an already queued valid route.

Print preview remains on `prepare_stock_preview` plus the original stock
constructor/widget attachment. Its metadata, mapping, thumbnail and backend
admission paths remain intact. The existing recovery integration still receives
status updates. Standalone model/prototype renderer tests remain useful offline,
but the production Runtime no longer uses them to render screens.

Tests now assert that retired/malformed navigation requests allocate no new
widgets and issue no guessed stock navigation. Actual stock-preview tests retain
checks for the original sidebar/content hierarchy and six mapped rows. The full
host UI/layout run passed 30 tests; the native lifecycle test exposed shared
fixture initialization previously buried in the removed prototype test. That
setup is now explicit and the native lifecycle rerun passed. The offline ARM
build passed. Candidate SHA256:
`37d7ece74f9b06ca36550b3df50d7fe174f00caf6aeae38943077b71bb751ff0`. This removes a possible
regression route; it does not prove the appearance or completeness of all native
screens. No printer access or activation was performed.

### Toolhead → ACE identity editor — integration in progress

The Toolhead filament information now routes into the existing ACE identity
editor using the stock Filament page constructor. Previously this entry point
reported integration pending even though slot editing was available elsewhere.
A loaded head uses its exact backend-reported source ID, with a matching physical
head and unique source. An empty head opens directly only when exactly one
source is assigned. Multiple assignments, unknown loaded state or missing source
evidence leave the head-filtered slot overview open for explicit selection.
Stale ownership/status does not navigate or schedule a delayed request.

This navigation sends no filament or configuration command. Existing editor
brand/colour drafts and typed Save/readback remain in use. Material changes are
still a preview stub pending a temperature/profile policy; their message now
states that specific limitation rather than claiming all identity integration
is absent. The standalone editor route is retained.

The initial native lifecycle run passed, including exact loaded-source selection
when two ACE slots share a head, ambiguous empty-head selection and unique-source
empty-head entry. The final native lifecycle rerun also passed unknown loaded-state and stale-status
cases. The offline ARM rebuild passed. Candidate SHA256:
`acdd8059557e9282ff265c454e092f391a30147991ac7ece3361389c09165fb3`. No printer access or
activation occurred. Visual/hardware acceptance remains outstanding.

### Stock filament artwork — review in progress

The stock Filament constructor explicitly sizes its colour image buttons to
83×83 (`filament-setup.asm`, 0x4f77a8–0x4f77b0). Our previous 70×70 geometry
could clip those assets. Standalone columns, the standalone identity editor and
Toolhead management now preserve the original 83×83 image bounds, with matching
spacing before material controls. Stock objects and parents remain intact.

ACE overview and print-source selector cards now use the same stock white
filament asset with RGB tint and preserved transparency instead of a flat
rectangular colour bar. ACE swatches are displayed at half scale within the
compact scrolling cards. This adds images within the existing stock Filament
content; it does not replace navigation or status widgets. Missing/invalid
colour identity displays a question mark. Slot selection and exact source-ID
routing are unchanged.

Validation: native lifecycle and stock-layout tests passed (3 tests). Coverage
checks intrinsic stock swatch bounds, separation from material controls,
stock-asset use, tint opacity, non-intercepting image children, and existing
slot/editor navigation. The offline asset inspector also verified all 16 solid
swatches against the compiled palette (83×83 BGRA assets); the five textured
swatches still need richer profile support. The offline ARM rebuild passed.
Candidate SHA256:
`99282f75d78710a9d1193207d278b3fe022ccf4e6c7636cb18f7706d887ae513`.
Hardware rendering remains
unqualified. No printer changes were made.

### Toolhead stock-widget correction — in progress

Toolhead management now retains the selected head's original stock filament
card, colour image button, material button and material label. It no longer
hides those widgets behind a replacement identity text button. Original objects
remain under their original parents so vendor refresh references remain valid.
Separate stock-styled head tabs select which original card is visible; no tool
pickup or movement is submitted by selection. Brand and loaded-state labels are
additions, alongside the existing WM+ distance/temperature/operation controls.

Identity comes from the selected head's loaded identity, or its configured
external source only when confirmed empty. Unknown colour is hidden instead of
showing a previous stock colour. The real stock white circle asset is tinted for
known RGB identities on ARM. Stock material/colour taps route to the existing
WM+ filament editor; stale, hidden and modal-blocked interactions are withheld.

This is a partial presentation correction, not visual acceptance of the complete
UI. Head tabs and missing operations are still new native widgets. ACE unit
panes, nested editors and preview composition still need a visual comparison
against the stock application. No printer access or activation was performed.
The candidate hash in the older milestone below is superseded by this work;
the complete host run passed 30 tests and exposed a hidden-content tap bug in
the lifecycle test. After fixing visibility and updating the ACE dropdown
assertion, that lifecycle test passed on rerun. Final offline ARM rebuild passed.
Candidate SHA256:
`216f92494e1f6bd583bc5418be09cfaa3ddfc281e7fba4349c3c8082ee152b14`.
Hardware rendering and interaction qualification remain outstanding.

### Load/unload and standalone filament checks — review candidate

Load and Unload now open `StockFilamentProcedure` inside stock content. The
review captures a physical head, source and the exact backend-supplied plan;
opening/selecting sends nothing. Begin requires fresh idle status, unchanged
owner/session/revision, loaded state and source identity, and a unique matching
plan with a description and token. Multiple load sources require selection;
labels include ACE unit identity/slot so repeated slot names are distinguishable.
Runtime checks the selected head and pending global operations again before
submitting through the existing typed backend. No vendor motion wrapper is used.

The dialog shows receipt progress. Close dismisses it without cancelling or
repeating the operation. Pending and unknown load/unload receipts prevent a new
procedure. An exception without a receipt ID leaves an unknown-submission latch
for explicit reconciliation. Extrude/retract still use their direct step path.

Standalone Toolhead management now exposes Check filament, including when loaded
state is unknown. Its scoped dialog records an explicit Loaded or Empty operator
observation through `WMP_CONFIRM_FILAMENT`; it does not move or heat. Context,
identity revision and captured loaded state must still match. The backend also
requires sensor agreement and an idle printer, and the UI waits for readback.
Procedure completion alone never declares filament loaded. The check control is
hidden for openACE, which retains ownership of filament evidence.

Validation: all 31 UI/layout tests and the offline ARM build passed. Tests cover
both-owner procedure validation, explicit source selection, duplicate Begin,
stale/context/source/plan changes, dialog lifetime, Runtime queue wiring, unknown
receipt retention, standalone confirmation, and real backend command/readback.
Independent review found a Check filament/footer overlap at shorter supported
heights. The control was moved beneath temperature controls; the final focused
native test checks non-overlap at heights 300, 320 and 340 and passed. The final
ARM rebuild passed, and independent re-review confirmed the fix with no remaining
blocker in this scope. Physical motion, actual font/layout and backend behavior
on the printer remain unqualified.
No printer actions were performed.

Current candidate SHA256:
`4a559d60def99bd5819e83968938c552055ab270b8aec86cb76d0bbb5bc9ea78`.
The review archive is regenerated from this candidate.

### Profile import — integrated layout stub

Both Filament modes now expose an Import profiles button inside the stock content
footer beside Toolheads. It opens a scoped stock-styled preview with disabled USB
drive and Uploaded profiles choices and an explicit unavailable explanation.
There is no file scan, upload, backend request, or persistence. Close returns to
the same filament screen. The screen is available for layout review even when
status is stale because it is entirely read-only.

Stock filament callbacks, Toolheads navigation, brand-editor entry/save and ACE
pane actions are blocked while the modal is open. The tick derives ACE blocking
from modal liveness, so external modal deletion cannot leave controls blocked.
Both ownership modes have host coverage for entry, blocked edits, stale status,
dismissal and parent/external modal deletion. All 30 UI/layout tests passed.
Independent source review found no concrete blocker. Actual font fit and touch
geometry still require visual qualification.

Import milestone ARM build SHA256 (superseded above):
`6457c3959d6516e0609fb7c3b99a709e0cb70186b4656428d12abc3a893a0133`.
The review archive is regenerated from this build. This supersedes the thumbnail
candidate below; no candidate has been activated during this work.

### Stock thumbnail expansion — integrated review candidate

The preview inventory captures the existing stock thumbnail only when it finds
one image-class child in the constructor's direct 149×149 content panel. It
checks ancestry, class and child count. Missing or ambiguous discovery leaves
enlargement unavailable without invalidating the other preview controls.

Tapping that widget opens a stock-styled image view within the existing preview
content. It reuses the displayed file source, validates dimensions with the stock
decoder and fits the image to the available width and height. The original widget
is not moved or replaced. `X Close` deletes only the enlarged view. The stock
sidebar and preview selections remain intact. Background options, source mapping
and Start are blocked while the image is open. The vendor fallback icon and
failed image decoding open a scoped “no preview image” explanation instead.

Focused host coverage passes for preserved parentage, fitted geometry, blocked
background actions, unchanged options, Close, fallback/decoder failure, parent
deletion and event-binding failure. Binary profile checks passed for the added
LVGL functions. These do not establish visual or decoder behavior on hardware.
The full UI/layout suite passed (30 tests), including the scroll-disable
adjustment. The offline ARM build passed and independent source review found no
concrete blocker. Thumbnail milestone candidate SHA256 (superseded above):
`c40a3fd8cc5d685d4c5727ce70e806e1b3987f89f23dfe14260cf0ffa25d7620`.
The review archive is refreshed from this candidate. Hardware visual and decoder
qualification remain outstanding; no activation has occurred.

Offline evidence: the constructor creates the panel at `0x537afc`, sizes it at
`0x537b24`, and creates the local image at `0x537b3c`. `display_img_V2`
(`0x5550d0`) validates a thumbnail filename using `lv_img_decoder_get_info`,
sets its source and zoom; its caller uses the stock fallback asset on failure.
No printer changes were made.

### ACE rename: stock keyboard and typed save integration

The unit-name action uses the original stock text keyboard constructor, retaining
its image keys, geometry and textarea. The host borrows and restores the stock
keyboard globals synchronously, refuses to replace an active Wi-Fi keyboard,
and replaces vendor key handlers with local draft editing. Layout changes also
use the original stock key constructor. Enter edits only the local draft.

Save & exit submits the existing typed `OPENACE_RENAME_UNIT` backend command.
Changed slot assignments are refused without partially applying the name. Save
requires the captured unit context and an idle printer, and cannot replace an
unresolved operation. The editor closes only after status confirms the exact
unit name and assignments in the same session. Command acknowledgement alone
is insufficient. Unknown delivery remains latched to prevent an automatic repeat.
A completed save does not discard a different editor or a newer local draft.

Validation: all 30 tests in `tests/test_unified_ui.py` and
`tests/test_stock_filament_layout.py` passed. Native tests cover keyboard editing,
layout/global restoration, Wi-Fi refusal, constructor failure, duplicate Save,
acknowledgement without readback, mismatched assignments, paused-print refusal,
uncertain delivery and changed sessions. These use a fake widget tree, not a
physical display. They do not prove appearance or the completeness of the
reverse-engineered keyboard-global inventory.

The rename milestone ARM build passed with SHA256
`c59fad191e8ebe00d5a2b39a669e45bf8272fc7983cab4cf67002da34f544dce`;
it is superseded by the thumbnail candidate above.
Independent source review found no new concrete blocker in keyboard ownership,
global restoration or rename/readback handling. Hardware qualification remains
outstanding. The review archive is regenerated from the current candidate by
`tools/package_unified_ui_review.py`. No activation or physical-screen acceptance
has occurred.

### ACE unit editor: explicit quick-assignment target

“All slots to one head” now opens a head selector inside the existing unit
content pane. Its target is independent of the head selected on the overview.
Choosing a head changes the local assignment draft and returns to the four slot
cards; individual slot assignments remain editable afterward. Cancel preserves
the draft, restores the unit-detail scroll position, and works with stale data.
Stale context cannot apply a head choice. Auto-distribute remains the other
quick-assignment action. Neither quick action submits a backend command.
The native lifecycle test and ARM build pass for this change.

Current unit-editor gaps remain explicit: rename edits a local draft using the
stock text keyboard, and rename-only saves use the typed backend.
Save & exit does not persist assignments, and removal confirmation
does not remove a unit. Remove is unavailable during a print. These are not
claimed as working backend operations. Offline inspection locates the stock text
keyboard constructor at `0x54ec48` and its key construction helper at `0x54e654`;
reusing it for rename requires isolating the original Wi-Fi save handlers first.

### Stock preview explanation stub

The original knife-pairing control now opens an explanation within the stock
preview content, using stock panel/button styles and font. It remains off and
does not invoke the vendor callback or a backend command. The dialog blocks
background option and mapping edits and has a Close action that works without
fresh backend data. Closing it retains the preview and its selections.
`StockNotice` retires when its parent is deleted and cleans up if event binding
fails; it does not clear the stock global top layer or create another app shell.
Host lifecycle checks cover no command dispatch, unchanged options, blocked
background edits, dismissal, parent deletion and failed binding. The focused
lifecycle test and ARM build pass with this change. Visual placement
on the actual display remains unverified.

### Acceptance criteria: extend the stock app

The mockups specify information hierarchy, approximate placement and workflow;
they are not a replacement visual design. Running inside the stock process or
using LVGL alone does **not** satisfy integration.

- Retain the real stock sidebar, status area and Settings tabs. Do not redraw
  these as WM+ controls or cover them with an opaque WM+ page.
- Reuse and reposition existing stock widgets and their styles, fonts and assets
  where they provide the required function. Add missing controls within the
  relevant stock content container, in the same visual language.
- Home's head-temperature region opens toolhead management; its filament mini
  view opens filament/ACE management. Preserve the surrounding Home screen.
- Toolhead management uses four head tabs, filament information on the left,
  distance/temperature controls alongside it, and up/down retract/extrude
  controls on the right. These are layout requirements, not instructions to
  reproduce the mock's rectangular panels.
- Filament management retains the real Settings shell. Standalone profiles run
  left to right; ACE units occupy a scrolling content pane. Additional unit,
  profile and selection workflows use stock-styled content or scoped modals.
- Presence of openACE progressively changes the same integrated UI. Unknown
  presence must not select standalone command behavior.
- Visual acceptance requires comparison with the actual stock screen, including
  navigation, touch targets, scrolling and modal dismissal. Host tests and an
  ARM build are necessary evidence but do not prove visual acceptance.

Current source contains both stock-widget adapters and the older generic
`Renderer` / `LvglSurface` replacement path in `Runtime::gui_step`. The latter is
not an accepted final screen implementation. The source now routes the managed
local preview through the original constructor and `StockPreviewPage`, but that
new Runtime wiring is not in the last packaged candidate described below and
still needs metadata-refresh, lifecycle and visual qualification. Descriptions
below of Runtime wiring as outstanding refer to the earlier component milestone;
they must not be read as proof that the current wiring is complete or accepted.

### Print preview conversion — stock widget inventory

Current local ARM candidate:
`212fd6f860fa3a048263b350cf602d3c05bdbf8023550be8d680c3f570e7d122`.
This includes the Runtime handoff, mapping/chooser adapters, scoped loading
popup suppression, generation-bound metadata queue and corrected async data
ownership and the read-only knife-pairing explanation described here. It supersedes the earlier component build
hashes below for source coverage, not hardware acceptance. It is unactivated;
thumbnail expansion, remaining screen
conversions and visual qualification are still outstanding.
Local validation: `tests/test_unified_ui.py` and
`tests/test_stock_filament_layout.py`: **30 passed**. These exercise host models,
fake-LVGL lifetimes, Runtime handoff and binary profile binding; they do not
exercise the live stock constructor or establish visual acceptance.

The production bootstrap source now calls the original preview constructor,
captures its widgets, and attaches `StockPreviewPage` through Runtime. A host
Runtime regression supplies delayed metadata after attachment and verifies six
mapping rows, preserved option choices, unchanged stock sidebar/content parentage,
and no generic replacement surface. Closing the preview prevents late metadata
from reopening it. Once closed, Runtime releases the preview session unless a
submission remains pending/unknown and still needs receipt reconciliation.
This is source/test evidence, not an updated ARM package or visual acceptance.

Offline disassembly confirms
`set_gcode_color()` (`0x539474`) queues `set_gcode_color_cb()` (`0x538c7c`) through
`lv_async_call`; that callback rewrites the mapping widgets and calls
`click_refresh()`. The new callback guard suppresses this writer for managed
preview roots. Stock loading UI is separately queued by `draw_loading_pop()`
(`0x535958`); `async_close_popup()` (`0x535674`) queues a callback that clears the
entire stock top layer. The colour callback itself queues `draw_pop(0x4c)` or
`draw_pop(0x43)`, replacing the loading presentation. Suppressing that writer
without changing loading would leave a popup whose normal successor never runs.

The managed preview now suppresses `draw_loading_pop` only during the original
preview constructor call, using a thread-local RAII scope. USB construction and
all other calls retain the original function. Scope restoration also covers
exceptions and nested unmanaged construction. The new hook's first 16 bytes are
`stp`, `mov`, `str`, `ldr`, with no PC-relative instruction; its 32-byte window is
bound to the supported binary profile. Loading status appears in the retained
preview content and Start stays unavailable until metadata/admission readiness.
No global top-layer cleanup is added. Host lifecycle tests cover the scope and
inline loading state; on-device popup/navigation behavior remains unverified.

Independent review identified that checking the current global preview inside
the delayed colour callback loses its origin. The follow-up source fix intercepts
the scheduler at `0x539474`: managed previews do not queue the vendor writer;
USB callbacks capture their original content root and generation. Execution
requires both still to match. New preview construction or deletion invalidates
the captured authority, including construction failure. Legacy callbacks lacking
this context are dropped. Focused host tests cover USB acceptance, managed
rejection, root mismatch and generation invalidation. This binds the queued GUI
callback; it does not add file/request correlation to the vendor's upstream
metadata-response parser.

The scheduler has both a GUI async caller (`0x63e948`, queued at `0x640150`)
and another caller at `0x682334`. It therefore reads a mutex-protected immutable
origin snapshot only; it does not inspect LVGL or the gate's entry list off the
GUI thread. Preview construction invalidates the snapshot, successful USB
attachment publishes it, and deletion retires it. The eventual GUI callback
checks current content and generation before calling the vendor writer.

Binary review also verified the actual `lv_async_call` convention: success is
**1** (`0x6c7d70`), allocation/timer failure is **0** (`0x6c7d10`, `0x6c7d44`).
`stock_async.hpp` transfers callback-data ownership only on success. The host
regression checks that queued data remains alive until callback consumption and
that failure frees it immediately. Intermediate candidate
`67c4013dd6a9dc36851812ddd7e3bbaed744a4b532a5aa67052a7acd89ca4990`
predates this correction and must not be activated.
Focused lifecycle/profile checks after these corrections: **2 passed**; the ARM
build also passed. Independent follow-up review found no new blocker in the
scoped ownership/thread fixes, while retaining the upstream request-correlation
limitation. The 30-test result above predates the final scheduler changes.

Offline review of the supported 1.1.13 binary identifies the original preview
constructor (`0x537710`), content (`0x386ee38`), filename label (`0x386ee40`),
three option buttons and four source/destination colour widgets. Start and Cancel
have no dedicated pointer globals: they are identified by the original callback
at `0x536958` with user data 4 and 3 respectively. The verified
`lv_obj_get_event_user_data` accessor permits discovery without translated labels
or hard-coded child positions.

`native/stock_preview_widgets.hpp` now captures and validates this inventory.
It verifies parentage and unique widget identities, bounds tree traversal, and
rejects missing/duplicate action buttons or deleted objects. It is read-only:
no new root, control, callback replacement or command is created. Host lifecycle
coverage verifies successful discovery and these refusal cases. The offline
symbol inspector now checks every expected global by address as well as name,
which matters because the binary has several unrelated `current_screen` and
`label_tips` symbols.

`native/stock_preview_controls.hpp` now provides the callback adapter for these
same widgets. It preserves geometry/styles, detaches all matching vendor control
registrations and the content refresh callback, and binds captured actions to the
current preview lifetime. Start is disabled until admission readiness is supplied;
a click latches it until explicit terminal reconciliation, including across
ordinary readiness refreshes. Cancel remains available while waiting. Hidden,
retired and deleted pages cannot dispatch. Host checks cover duplicate callback
removal, pending Start, hidden/retired pages, old-page deletion after replacement,
and attachment failures. On a failed inventory with a verified content parent,
only that preview content is closed. If even the root/parentage cannot be
verified, attachment returns false without touching foreign objects: Runtime must
keep its construction-time Start guard in place and must never fall back to the
vendor Start callback. The bootstrap now hooks the original preview callback
at `0x536958` and begins guarding before constructor/handoff. Captured content
roots retain their own ownership: later USB navigation does not release old WM+
callbacks. Failed capture remains guarded. USB destination chooser popups are
captured separately from their verified originating USB controls because stock
creates them as siblings of preview content. Host tests cover managed/USB roots,
failed capture, popup ancestry and DELETE retirement. The new hook's first 16
bytes are a non-PC-relative prologue and its 32-byte profile window matches the
supported binary. The hook builds successfully in local ARM candidate
`ef90cf89daa61911f8471dc0dfffb1998bc344c8cf0f07bdaecf33d064c651d4`.
Independent review found no remaining blocker in the guard and USB-popup scope.
It has not been activated or visually qualified on the printer.

The mapping content adapter is now implemented in `stock_preview_rows.hpp`.
It uses the existing mapping panel (validated as a child of stock preview content)
and retains the first four source/destination colour objects. Extra rows, material
captions and destination buttons extend that panel; the filename, thumbnail,
options and footer are outside its mutation scope. Up to 32 sliced filaments
scroll vertically, with scroll offset retained across data updates. Hidden/stale
rows do not dispatch. Editing also requires explicit model readiness: fresh
known ownership, an idle/completed job, and no unresolved operation. Selected
routes that lose eligibility are visibly marked Unavailable; row allocation or
callback-binding failure disables dispatch and permits a later rebuild. Panel deletion retires pointers before child teardown.
`App::preview_state()` exposes semantic rows, selected routes and source identities,
options and admission readiness from the existing command model; it does not
reuse mock-screen coordinates or maintain another mapping store. Host tests
exercise six rows, original-object reuse, unchanged-state allocation stability,
scroll retention, stale input, deletion, and selected-route consistency. These
source changes are not yet connected to Runtime or in the last packaged ARM
candidate; their appearance remains unverified on the printer.

The destination chooser now reuses `StockAceFilaments` in picker mode: unit
boxes and four slot cards retain the same stock styling, while adoption, unit
editing and filament editing actions are omitted. A uniquely eligible route
selects that exact route; aliases require an explicit tool-route choice. External
profiles occupy four columns, and explicit standalone ownership ignores stale ACE
unit records when arranging the chooser. The model provides eligible choices
through `source_picker_state()` and refuses map/choose edits during unresolved
operations or non-idle jobs. Host callbacks are connected to the real mapping
model in tests for direct choice, alias selection and stale input. Cancel and
Back to slots remain available with stale status; entering route choices resets
scroll to the top, and Back restores the slot overview offset. The native
preview modal host/Runtime wiring is still outstanding.

`stock_preview_page.hpp` now coordinates these adapters with the real `App`
controller. The original Start/option/close buttons drive controller actions;
mapping rows open the reused unit-card chooser as a modal inside stock content.
Option icons use the original selected/unselected assets decoded from the stock
refresh routine. The close button explicitly reads **Close preview**; pending or
unknown submission remains visible and is not represented as a cancelled print.
Knife pairing remains a backend stub. Its retained control opens a stock-styled
read-only explanation and its icon remains off; it cannot submit a command. Runtime attachment, metadata-refresh coordination, thumbnail expansion
and hardware/visual qualification remain outstanding. This coordinator is not
part of the last packaged ARM candidate.

The constructor resets leveling, creates a stock thumbnail, initializes four
mapping rows, requests metadata and opens its loading popup. Content event 30
calls stock `click_refresh()` at `0x53953c`, which updates colour, visibility and
opacity. Integration must coordinate with that refresh rather than assume the
constructor is the last writer. The existing replacement preview route is still
active in the candidate; this inventory is not yet attached to Runtime. Remaining
work includes capturing the thumbnail, connecting the control and mapping adapters, stock-styled source selection, and preserving
backend admission checks. The inventory/adapter sources accompany the guard candidate above; they are
not yet used by Runtime and do not constitute visual or on-device acceptance.

### Stock colour picker wiring — source work, not release evidence

The ACE source editor now calls the original Wondermaker colour-picker
constructor (`0x4f82a8`) and uses the existing captured-modal event hooks. It
keeps the selected colour local until **Save filament**, then uses the typed
identity adapter with the captured source ID. This increment is included in local ARM candidate
`e47c19ebad8b908642610a0508b318765f72aeab5ce5195646448a9a7d3e6a52`;
it has not been visually qualified on the printer or activated.
Brand/material controls in this editor remain placeholders.

Closing a reopened picker preserves the earlier ACE colour draft; unsupported
textured swatches also leave that draft saveable. The native lifecycle regression
checks this cancellation behavior without printer RPCs. The native lifecycle test now follows a stock-page slot click through the
original-picker entry and typed save queue, checks exact UNIT/SLOT addressing
when two sources share a head, and requires matching identity readback before
settlement. It also injects a failed lifetime binding: only the newly created
owned modal is deleted; an unrelated dialog survives. These are host simulations,
not on-device visual or transport acceptance. Independent review identified and verified two further fixes: Save becomes
unavailable after submission/refusal until another colour is selected, and
pending/unknown ACE adoption blocks colour entry/save so its receipt cannot be
displaced. The broader host suite passed 30 checks before these final guards;
the native lifecycle regression passed again afterward. These checks do not
qualify the whole screen set for deployment; print preview still needs stock
widget integration and several controls remain explicit stubs. Review noted a remaining wording
improvement: asynchronous refusals should also explicitly invite reopening the
colour picker, as immediate refusals already do.

### ACE content conversion in progress

`native/stock_ace_filaments.hpp` now provides a stock-styled content component
for the existing Filament panel. It creates a vertically scrolling pane below
stock head tabs, with a titled box and four source cards per ACE unit. Selection
fades unrelated slots without hiding them; updates preserve scroll position.
Cards carry exact source IDs, unit editors carry exact unit IDs, and discovery
entries carry candidate IDs. External profiles appear only for heads without ACE
sources. Freshness and hidden-parent checks inhibit stale clicks; generation and
DELETE bindings retire old panes and controls. Host coverage checks stock-content
parentage, eight-slot layout, fading, stable refresh allocation, scroll retention,
source IDs, hidden/stale click rejection and deletion.

Runtime ACE navigation now invokes the original Filament page constructor. Its
four existing head cards become selector tabs above this pane; the original
stock motion action row is hidden and intercepted. The stock Settings shell
remains owned by the vendor page. A reserved footer contains Toolheads, returning
to the selected physical head. Navigation requires a fresh, explicitly identified
standalone/openACE owner; unknown ownership is not treated as ACE presence.
The old full-page ACE renderer is no longer the destination of this route.
Leaving print preview for Filament also hands off to the stock page.
When that page is visible, a definitive fresh ownership change reconstructs it
through the stock constructor in the appropriate mode. Stale/unknown status does
not imply openACE removal. Hidden Filament pages do not trigger navigation away
from another stock screen. A mode change cancels captured identity drafts and
closes only WM+-owned pickers/keypads; outstanding adoption outcomes remain
retained. Native lifecycle coverage exercises both ownership directions, stale
observations, hidden pages, stable refresh, and owned-versus-unrelated dialogs.
This ownership-transition increment is included in the ARM candidate identified above.

ACE unit details now open inside the same stock pane. Identity/name, four slot
assignments, all-to-selected-head and auto-distribute are visible; tapping a slot
opens a head chooser with Unassigned and Cancel. Assignment changes are expressly
labelled local previews and never update observed mappings or send requests.
Context/session/revision drift invalidates the preview. Overview/detail scroll
positions are restored across navigation, and cancelling a chooser preserves the
preview. Back/discard remains available when status is stale. Remove opens a
confirmation stub and is disabled during active or unknown print states; the
confirmation explicitly says nothing will be removed. Save and rename remain
explicit integration stubs. Tapping an ACE/External source now opens a stock-styled filament-settings view
inside the same pane, showing the exact unit/slot or External head identity and
brand, material and colour fields. Head assignment is deliberately absent from
this editor. Back restores the overview scroll position. Its colour picker/save wiring is described above; brand and material controls
remain explicit integration placeholders. Opening this view does not save data.
The shared stock-picker state now supports `begin_source` for openACE: it captures
an exact source ID instead of resolving a slot from a physical head. Tests cover
two slots feeding one head, duplicate IDs, source reassignment, stale ownership,
session/configuration/identity revisions, and External sources under openACE.
Standalone editing retains its existing head-based entry. The colour path now connects to the stock picker and management receipts;
brand/material picker integration remains unfinished. Existing typed save
support permits brand/colour updates on existing profiles; material changes stay
refused until a temperature/profile policy is defined. These source-editor increments are included in that candidate. Adoption now
opens a native confirmation with the readable device identity and registration
result. The real typed `unit_add` adapter is connected: confirmation captures the
candidate/session/configuration, Runtime rechecks current idle ownership and the
exact observation, and the existing worker revalidates `EXPECT_CONTEXT` before
delivery. Confirmation is one-shot. Completion requires a post-delivery reply
and registered-unit readback, not a timer or acknowledgement alone. Pending or
unknown operations survive navigation and are reconciled on every GUI tick;
unknown outcomes are not automatically retried. The operator can return to the
unit overview while pending/unknown; a persistent registration-status button
reopens the result. Dismissing the view does not clear the unresolved operation.
Completion readback checks the logical unit name. The normalized unit record does
not expose the candidate hardware identity, so this is not independent hardware
identity verification. Host tests cover the confirmation
flow, duplicate clicks, readback requirement, actual Runtime-to-typed-queue
routing, and paused-print/configuration-drift refusal without printer access. Backend transactions and the stock rename keyboard are
not connected to unit details yet. The latest offline ARM candidate includes unit previews and typed adoption;
host tests cover them, not hardware or visual acceptance. Runtime tests now
assert stock handoff instead of the rejected ACE overlay; adapter tests exercise
the reused head cards and scroll pane together. The older controller and generic
renderer tests remain separate evidence, not proof of stock-page integration.
All 30 UI/layout tests pass after the ACE navigation conversion. The subsequent
readable discovery-label change passes the focused native lifecycle test,
including two candidates with distinct device labels. Independent read-only
review found no blocker for this read-only/stub increment. The ARM candidate
build succeeds with these sources. No corrected ACE page has been deployed or
visually qualified on the printer.

### Toolhead conversion: verified stock entry points

Offline analysis of the exact supported 1.1.13 binary establishes the next
integration boundary. Home head-temperature clicks (event IDs 1–4 in
`event_handler` at `0x519a34`) set `keyboard_edit_type` at `0x463c8d0` to the
same number and call `draw_number_keyboard` (`0x52e418`). There is no separate
stock temperature-management page behind these entries. The keypad creates its
own stock modal (`g_mask`, pointer at `0x386dc68`) and textarea (`0x386dc70`).

The keypad button handler at `0x52da0c` handles digit entry, `del`, `dot`,
`minus`, `enter` and `back`. Enter emits event 31 (READY) to the textarea;
its handler at `0x52db58` reads the global keyboard mode and dispatches the
action. Modes 1–4 already use explicit physical commands:
`SET_HEATER_TEMPERATURE HEATER=extruder[1–3] TARGET=...` (head zero uses
`extruder`). Modes for the bed/chamber and flow also share this handler.
Those shared modes must retain their behavior when a WM+ Toolhead edit is not
active. The original keypad is suitable for visual reuse, but calling its
original confirmation handler after WM+ submission would duplicate the action.

Implementation boundary for the temperature editor: retain the stock shell;
use the stock keypad constructor for target entry; capture physical head and
modal identity when opened; confirm a requested target locally and use the
existing typed temperature adapter only when Heat is pressed. Keep actual and
confirmed-target readback separate from this requested target. The original stock constructor now supplies the keypad images and
textarea. WM+ removes both registrations of the original textarea handler
(CLICKED and READY), and replaces the thirteen key callbacks with captured-dialog
callbacks. Confirmation checks fresh ownership/session/configuration, the
captured physical head and its configured heater limits, then updates only that
head's local target. Heat is still a separate explicit action. Back cancels;
navigation closes the owned keypad. Missing expected vendor callbacks fail
closed by deleting the new modal. Host coverage exercises entry, cancellation,
limit refusal and detachment of both original textarea callbacks. Native capture
and on-printer appearance remain unqualified. The verified symbol
inspection tool now records the keypad constructor, globals and address-specific
callbacks so this work does not rely on matching ambiguous local symbol names.

The first Toolhead content conversion now routes Home head entries through the
original stock Filament constructor. It preserves the stock shell and repositions
the existing four head cards as tabs, hiding their filament-only children. New
controls for the missing Toolhead workflow are direct children of stock content,
using the vendor button styles and font; no screen-sized replacement root is
created. Physical head selection, distance choices, actual/confirmed-target
readback and configured/loaded identity text are displayed. Standalone manual
steps and explicit physical Heat/Off submit through the typed backend; openACE
temperature retains its idle checks and ACE steps remain refused without an
adapter. A pending receipt prevents another request until its result is observed.
The originating motion button displays `Extruding...` or `Retracting...` while
pending; extrusion and heater buttons are disabled until the result is observed.
The busy state is tied to the operation's head even if another head tab is chosen.
Head tabs now explicitly apply stock selected/unselected styles, avoiding the
vendor's older selection highlight. Confirmed loaded state shows Unload, empty
state shows Load, and uncertain state shows neither with an explicit check-needed
message. Missing loaded identity is reported as unknown rather than substituted
with the configured spool identity. Host assertions cover these transitions.
Both manual-control and identity-save receipts are reconciled before navigation
on every GUI tick, and before a new edit/control submission. This matters because
the shared backend publishes only its latest receipt: a hidden view must consume
its terminal result before another operation replaces it. A Runtime regression
injects worker observations across Toolheads/Filaments navigation and successive
step/identity operations; both pending owners settle. The test exercises Runtime
navigation and reconciliation, not actual printer RPCs.
Admission is shared too: either unconsumed manual or identity receipt blocks both
consumers' next submission. This covers the interval where backend completion has
unlocked its queue but the worker has not yet published the terminal receipt.
Independent review accepted this scoped fix; the Runtime regression includes an
unpublished-terminal/opposite-owner refusal case. Other screen conversions and
on-device acceptance remain outstanding.

This is intentionally incomplete: requested targets initially default to 220 C
and use the stock keypad for editing; Load/Unload
review and Take/Dock explain their unconnected UI/backend paths. No vendor
load/purge/homing sequence is invoked by these placeholders. The source swatch and full review/progress flows still need conversion.
Tapping Toolhead filament information now opens a selected-head standalone
profile view using that head's existing stock card, colour/material pickers and
WM+ brand selector. Other head cards are hidden, their delayed colour/material
clicks are consumed, and Toolheads returns to the selected head. This edits the
External filament profile; it does not assert a physical load or change routing.
The openACE route explicitly reports pending editor integration instead of
editing an External source on an ACE-owned head. Host lifecycle coverage checks
this route and stock-object reuse. Requests for a no-longer-configured head are
refused before opening the editor. New page construction retires old brand
dropdown bindings so a retained old page cannot begin another edit. Independent
review found no wrong-source/lifetime blocker in the focus route; the missing-head
check addresses its defensive UX recommendation. The offline ARM candidate includes this selected-head editor increment. The standalone
Filament page now has a stock-styled Toolheads shortcut in its reserved bottom
margin. It opens the selected physical head through the same navigation route
as Home; it does not issue a motion command. The callback checks the captured
page generation, current visibility and fresh status. Host coverage checks
parentage, stock styles, selected-head routing, stable widget allocation, and
refusal of stale or hidden-page clicks. This shortcut is not yet qualified on
the printer. The offline ARM candidate includes this shortcut and the temperature keypad. The current Filaments button returns to standalone stock
Filaments or the stock-integrated ACE list. Host lifecycle coverage checks
stock parentage, reused head cards, click dispatch, stable refresh allocations
and deletion; it is not physical or visual acceptance.

Offline picker integration work now confirms that the original colour callback
(`0x4f8020`) and material callback (`0x4f86b8`) commit immediately on CLICKED:
they update the eight-byte stock filament record, write an INI setting and delete
the stock picker. These are not draft-only callbacks and must not run after a
WM+ persistence request. The verified symbol inspector now includes both picker
constructors, their handlers and the stock edit-state globals.

`native/stock_identity_edit.hpp` adds the source-bound edit state for reusing
these pickers. It captures the External source, ownership/session/configuration
and identity revisions when opened, preserves the other identity fields and
submits one `save_identity` request through the existing backend interface.
Host tests cover changed ownership, revisions, session, source/head, stale
status, active print, duplicate sources, cancellation and duplicate clicks.
Both stock layout/picker tests pass. The standalone material picker is now wired
through its original stock constructor and a profile-verified selection hook.
The selection uses the stock material-name table, submits through the existing
typed backend and closes the original dialog without executing its vendor INI
write. The existing stock tips label shows pending/result messages; material
labels on the existing cards are refreshed from backend identity readback.
Closing the picker cancels its captured draft; duplicate selection callbacks do
not resubmit or replace a pending receipt. Host adapter tests cover material
entry admission and updates to existing stock labels without allocating widgets.
Native callback/global-table behavior still needs hardware qualification.

Independent review found that source capture alone did not bind a delayed event
to its originating dialog. The native path now captures the actual stock modal
after constructor return and checks selection/close event ancestry against that
modal. It closes the captured object, not whichever object the mutable vendor
global currently names. DELETE callbacks carry generations, so an older modal's
deletion does not retire the newer binding. Host lifecycle coverage exercises old
choices, old-modal deletion, cancellation and replacement. These are local fixes;
the native event path still requires on-device qualification.

Colour selection now uses the same captured-source persistence bridge through
the existing stock picker. The 16 solid RGB values were recovered from its BGRA
assets; `tools/inspect_stock_palette.py` checks the compiled table against those
assets and records their hashes. The five textured swatches show an unavailable
message without writing a substitute RGB value. Confirmed matching solid colours
reuse the existing stock image-button objects and stock asset paths (both released
and pressed states). Card labels and swatches are changed after backend readback,
not optimistically when a picker choice is tapped.

Custom RGB readback now reuses the stock white circle with LVGL image recolouring,
retaining the stock image transparency and widget geometry. Default and pressed
states receive the same colour; returning to a stock palette entry resets both
recolour opacities. Parsing accepts upper/lowercase six-digit RGB, including black,
and rejects malformed values. The three targeted layout/edit/lifecycle tests pass,
covering custom tint, pressed state and removal of tint without adding widgets.
On-device appearance remains unverified.

Brand selection now adds one dropdown inside each existing stock card, using
the vendor button/default/pressed styles and Myriad font. Choices include Generic,
the source's configured brand and the other current External brands, with at most
32 options. This is not yet an imported-profile catalogue. The source/revision
is captured when the list opens; the options remain fixed until it closes.
Selection uses the same typed identity backend. Stale selectors are disabled,
duplicate choice events do not resubmit, and deletion of the stock card retires
the selector's callback state. The material control was shortened to leave room
for the brand control even at the minimum supported panel height.
The exact stock card style sets zero padding and a one-pixel border. The adapter
also checks measured card content height before exposing the brand selector:
below 212 pixels it hides the selector rather than overlapping the material
control. Host coverage includes border insets and an unexpectedly padded card.
Smaller/padded layouts that hit this limit need further layout work before they
can offer brand editing; this is not a claim of support for arbitrary dimensions.

No corrected picker has been deployed. This is a picker increment, not completion
of the remaining screen conversions. On-device dropdown appearance, scroll-list
placement and the original stock constructor/global bindings remain unverified.
The native/layout suite passed 30 tests including the brand-control cases. The
subsequent modal-binding/content-size fixes passed three targeted tests and
independent review; full native callback and visual qualification remain pending.
The offline ARM build succeeded with
SHA256 `871f895922f2ae5f7fb3f697218986c610e62a2218330142999125ce68fce501`.

Latest adoption verification: the full 30-test UI/layout suite passed before the
unknown-outcome navigation refinement. The focused native lifecycle test passed
again afterward, including retained unknown status, overview return and blocked
repeat adoption. Independent review accepted that fix. The source-bound ARM
candidate and review archive include these changes; neither is deployed.

Latest keypad/shortcut verification: all 30 UI/layout tests passed. After adding
an instruction/refusal label above the original keypad panel, the native
lifecycle test passed again. Independent read-only review found no blocker in
callback removal, captured-dialog lifetimes or per-head target admission. It
did not exercise the live stock constructor or printer. The review archive is
regenerated from the source-bound ARM manifest; it is not an activation package.

The operator rejected the full-page WM+ renderer on 31 October 2026. The mocks
were placement guidance for changes to stock widgets, not a replacement visual
shell. The installed candidate creates an opaque root over the stock page and
recreates its navigation; being native LVGL does not make that the requested
integration. Earlier completion/review claims below are superseded on this point.

Required correction: retain the stock sidebar, status area, Settings tabs,
typography, icons and widget styling; rearrange and extend existing page objects
in place. New views are appropriate only for missing workflows and must use the
stock visual language. Backend adapters remain reusable. No corrected UI has
been installed, and the previous collision-related activation restriction remains.

First in-place candidate increment: standalone Filament navigation now invokes
the original stock constructor. A verified setup hook captures the stock content
and its card/number/colour/material objects; geometry updates only those existing
objects. Per-construction generations and DELETE callbacks retire old bindings.
Fresh standalone ownership, visible page ancestry and matching object parentage
are required before applying the layout. It creates no replacement root or styles.
Host coverage includes rejected stale/ACE ownership, incomplete/reparented/aliased
widgets, pointer reuse, and a native runtime handoff that creates no covering root.
The ARM candidate built successfully; 29 native/layout tests and the subsequent
standalone navigation regression passed. This increment has not been activated.

Independent review identified a stale-status fallback into the rejected renderer;
that fallback is removed. A Filament request with missing/stale status leaves
the current page in place without replaying the request. A stock-styled status
explanation remains to be added. Targeted lifecycle/layout regressions pass after
the correction. Host tests do not exercise AArch64 global-pointer capture or
prove visual layout on the printer.

This is not the full correction: ACE groups, Toolheads, editors and print preview
still require conversion. Material and solid-colour selection have the new
persistence bridge described above; other stock action/edit routes remain unfinished.

The next increment hides the actual stock TAKE/RELEASE/UNLOAD/LOAD container at
attachment time and adds a profile-verified, page-scoped handler guard for its
motion callback IDs 0–3. It does not filter G-code or other pages. Card selection
and colour/material editor entry IDs 4–15 require a current standalone observation
and applied layout; the stock editors themselves remain unchanged. This is not
yet WM+ guarded profile persistence, and does not claim that an already-open
stock editor's save callbacks have been converted. Those edits and the Toolheads
navigation/control conversion remain required before activation.

The host LVGL harness now invokes the actual native adapter's attach, tick,
interception and DELETE callbacks with fake stock objects. It verifies that no
replacement widgets are allocated, the motion row is hidden before the first
timer, queued motion clicks are consumed, and unrelated/non-click events pass
through. Actual AArch64 global-pointer capture and on-device appearance remain
unverified by that harness.

This increment passed the 29-test native/layout suite and rebuilt for ARM.
Independent review accepted the successfully attached-page lifecycle and scoped
guard, but noted that failed attachment still leaves stock callbacks available.
This is not a globally fail-closed migration. Failed-attachment behavior and
already-open stock editor save callbacks remain activation blockers for this
conversion, along with the unfinished screens described above.

For an expandable navigation graph, per-screen layouts, command bindings and
standalone/openACE scenario coverage, open [the screen flow reference](screen-flow.html).

## Latest state after the collision handoff

The framebuffer walkthrough and ready/standby observations below are historical,
before the subsequent openACE extrusion collision report. They are not evidence
of current printer readiness. That handoff reports emergency shutdown and requires
physical inspection and fresh approval before installation or restart.

The local correction removes only EXTRUDE_FILAMENT's final implicit docking call;
see [the updated motion audit](../filament-motion-audit.md). The native UI library
rebuild remains byte-identical to the walkthrough library. Its review manifest
now binds the corrected local macros, which have not been installed. The native
standalone distance buttons continue to use WMP_EXTRUDER_STEP, not that purge
macro. No collision recovery or physical qualification is implied by screen
implementation completion.

The final local macro/helper/pause/package validation passed 262 tests. The narrow
fix also received independent review. Full source and artifact fingerprints and
the exact incremental patch are preserved locally under
`analysis/extrude-no-dock-review/`.

This inventory describes the unified native candidate. On 2026-10-31 the operator
authorized ending the paused test and activating it for a no-motion touchscreen
walkthrough. See the activation evidence below; installation is not full hardware
acceptance. It supersedes historical mockup implementation claims.
The existing candidate contains the functional views, backend adapters and
previews described below, but its presentation must be integrated into stock
widgets before the screen objective is complete. Standalone operation is also
not fully qualified while Take/Dock and attended motion testing remain outstanding.

## Screen inventory and backend boundary

| Required screen/flow | Native implementation | Connected behavior / remaining gap |
|---|---|---|
| Stock Home entry points | Profile-checked hooks and `HomeMini` overlay | Head area opens Toolheads; filament area opens sources. Mini-view groups ACE slot colours and discovery alert. Home entry points and the installed single-unit mini-view were checked on device; discovery/multiple-unit cases have host coverage. |
| Toolheads | Head tabs, filament card/edit, distance steps, arrow buttons, temperature keypad and separate live target readback | Physical temperature controls are connected in both modes (openACE requires idle print/operation evidence). Standalone E steps, operator checks and explicit Load/Unload are connected. Idle ACE Load/Unload are connected through public owner commands; Take/Dock, external loading under openACE, and ACE distance-step adapters remain unavailable. Mounted/not-mounted/unknown status is derived from helper attachment evidence, not the selected extruder alone. |
| Filaments / ACE slots | Standalone: four equal External cards without head filters; openACE: scrollable unit groups, head filtering and External sources | Reads live source identities; no separate Devices or Slot Assignments screen. ACE units/discovery are gated by detected owner. |
| Unit details / assignments | Name keyboard, per-slot head chooser, Unassigned, two quick-fill actions | Rename connected through typed openACE path. Saving routing changes remains unavailable pending a transaction contract. |
| Filament settings | Brand/material selectors, palette, custom-value retention | Standalone persistence connected. openACE existing-profile brand and colour updates connected; material changes and new identities remain unavailable. |
| Adoption | Scrolling candidates, observed-context confirmation | Typed backend command; matching receipt plus unit readback opens Unit details once. |
| Removal | Idle-only confirmation and impact explanation | Review lists the selected unit and its current associated tool routes. Atomic removal and the future renumbering plan remain unavailable; no removal command is sent. |
| Import | USB chooser, review and upload explanation | Enumeration, file format, conflict handling and import command remain stubs. |
| Stock Files / native preview | Stock browser handoff; native metadata rows and grouped source chooser | Standalone and openACE mapped submission connected through distinct helper protocols, with native option staging and matching admission readback. USB copy flow retains stock behavior. |
| Expanded thumbnail | Native image widget and close control | Bounded PNG cache implemented; actual preview decoding, expansion and close were checked on device. |
| Operation status | Bound head/action, receipts, return path, Stop/cancel placeholders | Standalone reconciliation connected. Unknown delivery never retries motion; confirmed drained failures allow operator checks. openACE unified recovery controls remain unavailable. |
| Print / recovery | Retained stock print screens and existing native recovery panels | These are the integrated flows. Generic unified Job/Recovery layouts are development-only and have no native entry; a new recovery projection/action bridge remains incomplete. |
| XYZ / Video / Wi-Fi / General | Native navigation to retained stock screens | Dirty drafts must be kept or discarded before handoff. Home explicitly returns to stock `main_page`. |

The screen also contains the required name keyboard, temperature keypad, brand,
material, source, route and head selectors; load/unload procedure review;
filament-state check; cancellation confirmation; and draft-discard dialog.
Unsupported backend actions remain unavailable. Layout previews and disabled
controls are not evidence that those backend operations exist.

## Evidence and limits

- `client-preload/unified-ui/screens.hpp` and `model.hpp`: screen contents,
  drafts, navigation, selection binding and operation state handling.
- `native/bootstrap.cpp`, `native/profile1113.*`, `native/runtime.hpp`: exact
  firmware binding, stock navigation interception and GUI/worker separation.
- `native/lvgl_surface.hpp`, `native/home_mini.hpp`: actual native LVGL calls,
  owned roots, scroll containers, callback lifetime and stock-modal handling.
- `standalone_backend.hpp`, `klipper_extras/wm_material.py`,
  `config/live/macros.cfg`: standalone request validation and execution.
- `openace_backend.hpp`: currently supported typed openACE management operations;
  it intentionally refuses unsupported routing/material/action changes.
- `tests/unified_ui/`: controller, adapter, projection, metadata, thumbnail and
  native callback/lifetime tests. The LVGL harness is a host fake; it cannot
  prove actual pixel layout or hardware timing.
- `klipper_extras/test_wm_material.py`, `tests/test_config_macros.py`: helper
  validation, failure behavior and local vendor G-code state-handler tests.
- `analysis/unified-ui-native/manifest.json`: current artifact/input hashes.
  `review.tar.gz` is an independently hash-bound review export, not an install
  bundle or approval to activate it.

The [backend integration decisions](backend-integration-decisions.md) distinguish
existing openACE commands awaiting WM+ adapters from missing transaction or
manual-step contracts, with fingerprints of the inspected source.

The [activation proposal](activation-proposal.md) identifies payload targets,
rollback evidence, live-target preflight and the initial no-motion walkthrough.
It is not an activation authorization or an executable installer.

## Remaining acceptance work

1. Resolve independent review findings against the exact source/artifact inputs.
2. Review the backend stubs above with openACE's current command contracts;
   connect supported operations without inventing physical completion evidence.
3. Qualify candidate packaging/dependencies for the actual printer, preserving
   the original installed native UI and rollback inputs. The ordinary sealed
   installation bundle has not been replaced by this review archive.
4. Preserve the explicit activation scope. The operator authorized the initial
   activation and no-motion review; physical testing needs separate authorization.
   Stock client startup restarts Klipper.
5. Attend a no-motion navigation/layout/touch walkthrough in standalone and
   openACE modes, including stale/disconnected/empty and multiple-unit states.
6. Separately authorize and perform physical acceptance of connected controls;
   check cancellation, completion, partial failure and lost-response behavior.

No printer restart, motion, deployment, publication or push is authorized by this
inventory. Independent review may add requirements or identify implementation
faults; no consensus or hardware qualification is claimed here.

## Independent review disposition

A separate read-only reviewer identified five concrete native-flow issues: modal
Back escape, loss of scroll position when returning from editors, opaque discovery
labels, stale Home falling through to vendor indicators, and absent/insufficient
physical-attachment presentation. All five fixes were re-reviewed and accepted.
Tests exercise callback escapes, scoped scroll restoration, identity/token
separation, stale overlay retention and attachment-evidence projection. The
review also identified disappearing-discovery confirmation feedback; the Adopt
control now disables when its observation is gone.

This is consensus on those findings, not full UI/hardware acceptance. The reviewer
also accepted the candidate-only brand-edit extension: enqueue and delivery use
the same typed serializer, fresh-status revalidation remains intact, and sealed
source inputs remain untouched. Host tests cover actual worker delivery, unsafe
brand rejection and refusal when preserved profile temperatures change. Material
changes and new openACE identities remain integration gaps.

The mapped-print helper and native delivery path were independently reviewed.
The exact helper payload is frozen when Start is tapped and compared before
staging flags or dispatch. Tests cover file changes in both modes, stale ACE
session/configuration, active operations, changes after leveling setup, one-shot
delivery, wrong frozen-job evidence, and late admission after a lost response.
The reviewer accepted the final change with no remaining blocking finding. The
combined native/helper suite passed 123 tests; hardware acceptance is outstanding.

Idle ACE Unload was independently reviewed with no blocking findings. Tests
cover source/session/configuration changes, paused/busy refusal, one-shot owner
dispatch, required empty-head readback and helper-session receipt matching.
Status publication shares one ACE snapshot across head plans; command dispatch
always obtains fresh evidence. The 26 native UI tests and 105 helper tests pass.
No hardware unload has been attempted with this candidate.

Idle ACE Load now has source-bound helper/transport coverage. Independent review
accepted the token and completion checks, including the explicit inactive
openACE job-map guard. The final helper suite passes 121 tests; the unchanged
native transport/controller suite passes 26 tests. External hand-fed loading
under openACE and hardware acceptance remain outstanding.

Cross-screen regression coverage now exercises Print Preview -> Toolheads ->
Load, file-metadata invalidation, explicit re-review, token changes without a
revision change, and a stale Begin event after closing the procedure modal.
Procedure plans use the composed display revision while retaining the backend
token; an open review retains its exact plan until accepted or abandoned.

Standalone filament settings, operator confirmations and Load/Unload admission
now require agreement between print state, pause state and virtual SD activity,
including whether a command is executing from the SD file. Contradictory or
missing state invalidates prior operator assertions; clearing the conflict does
not resurrect them. The helper suite passes 130 tests, including real-Klipper-style
missing-object lookup behavior. This does not change installed printer behavior
until the candidate helper is activated.

Read-only live-status replay on 2026-10-31 exercised 20 native C++ widget-model
frames across four heads, one ACE unit and eight source records, including unit
and identity editors. Projection and navigation completed without exceptions.
The replay used a stub backend and did not execute LVGL or dispatch printer
commands. Hash-bound input/output evidence is in ignored
`analysis/unified-ui-native/target-inspection/native-replay-summary.json`.
That replay alone did not establish pixel, touch or ARM runtime acceptance.

## Approved native activation and touchscreen review — 2026-10-31

The approved activation stopped the stock client and Klipper to end the paused
test, installed the candidate UI, `wm_material.py` and merged `macros.cfg`, then
started the client and waited for Klipper readiness. The old library, helper and
macros were backed up; `printer.cfg`, calibration, ACE configuration, the preload
drop-in and other preload libraries were preserved. No motion, heating, print
start, recovery command or configuration-editor save was issued in this review.

Actual framebuffer captures and touch navigation verified Home -> Filaments,
Home head -> Toolheads, head filtering, native vertical scrolling to External,
Unit details -> slot/head chooser, source profile editor and brand selector,
temperature keypad draft display/cancellation, import stub, stock file browser
handoff, real file preview, expanded thumbnail and grouped source picker.
Unknown loaded/attachment evidence remains visibly unknown; it is not inferred
from the head tab selection. Standalone mode has host coverage but has not been
physically exercised by disabling openACE on this printer.

The first hardware walkthrough found issues not caught by the host LVGL fake:

- The stock top layer is hidden on Home. Native pages now belong to the active
  screen, and modal detection ignores children of hidden stock layers while
  still yielding to visible top/system dialogs.
- Compact settings layout enlarged swatches over filament names. Identity text
  and colour bars now have separate geometry.
- Stock font lacks several UI glyphs; native text uses readable ASCII fallbacks.
- Informational cards need their own label child, including keypad input text.

Each renderer correction received targeted regression coverage and independent
review. Activation logs, exact payload hashes and framebuffer images are local
under `analysis/unified-ui-native/activation-run` and `activation-repair*`.
These artifacts contain printer-specific evidence and remain ignored.

Final installed UI SHA256:
`b3076dbe93d682bdde8a6558b924ea5e080263fcbe2b50a8f0ba99304ad7ab85`.
The running client maps that exact library; final Klipper state was ready,
print state standby and pause false. The printer was left on stock Home.
The native suite passed 27 tests; subsequent card-text regression and nine
review-package tests passed. The final review archive was regenerated from the
matching build inputs. Preview metadata now has an explicit loading state; navigating away cancels
the pending handoff so a late reply cannot reopen it. Host regression coverage
checks both behaviors.

Remaining acceptance includes actual physical controls, standalone hardware
behavior, print submission, live discovery/removal states and
multiple ACE units. Backend stubs in the inventory remain stubs; this activation
does not make those capabilities available. No publication or push was performed.

Follow-up independent review corrected empty ACE-fed head editing to offer only
its assigned ACE slots rather than the synthesized External record. Standalone
editing remains direct. Assignment changes remain preview-only, with a visible
notice and disabled/guarded Save; unchanged assignments still permit renaming.
The actual touchscreen verified preview changes, disabled Save and discard back
to Home without a configuration write. Existing UTF-8 unit names now lose one
whole character per Backspace rather than one byte. The 27-test native suite
passes with dedicated source-routing, Unicode and assignment refusal coverage.

The subsequent local candidate adds an idle openACE External Load preview with
preparation, insertion and priming stages. Prepare is explicitly disabled; no
generic Begin can dispatch from that modal. Existing standalone procedures and
paused owner flows are retained. Controller and native lifecycle checks pass;
entry-path checks cover its 800×480 geometry. This addition is included in the final activated candidate. The idle context/result contract is documented in
[backend integration decisions](backend-integration-decisions.md).


## Historical implementation audit — presentation conclusion superseded

The earlier independent audit incorrectly accepted the full-page presentation
as stock integration. Its functional coverage inventory is retained below for
reuse; it does not prove the corrected visual/in-place integration requirement:

| Requirement | Authoritative evidence | Disposition |
|---|---|---|
| Actual WM app; stock Home shortcuts and Settings shell | Native profile/bootstrap hooks, LVGL surface, actual framebuffer/touch walkthrough | Integrated; no web page is used as the printer GUI |
| Head tabs, loaded/empty/unknown card, corner edit, distance and temperature controls | Controller/render code, standalone/ACE adapters, native callback tests, Toolhead/keypad captures | Implemented; supported operations connected; unsupported actions explain why |
| Four External sources without ACE; grouped scrollable ACE slots with head filter | Projection, fixture mode tests, native scroll/lifetime tests and actual scroll capture | Implemented; openACE behavior is presence-gated |
| Unit name, slot chooser, quick assignments and custom overrides | Isolated draft model, native editors, callback/discard tests | Rename connected; assignments preview-only until transaction support |
| Detection/adoption and removal confirmation | Typed adoption serializer/readback tests; discovery fixtures; current-route removal list | Adoption connected; atomic removal/renumbering explicitly unavailable |
| Generic brand, material and colour; no head assignment in identity editor | Controller selectors, source binding tests, actual editor/brand captures | Standalone persistence connected; ACE existing brand/colour connected; material/profile policy gaps disclosed |
| USB/command profile import | Native import/file/review views and disabled-dispatch tests | Explicit stub; no fabricated catalogue or import success |
| Print preview colours, destination chooser and expanded thumbnail | Native metadata and mapping adapters, command/readback tests, actual file/thumbnail/source picker captures | Integrated; physical submission not exercised |
| Correct return paths, dirty drafts, async loading and unavailable reasons | Controller and actual native callback tests, hardware discard and nested-help walkthrough | Implemented; unavailable controls use a read-only help route |
| Current print, recovery, XYZ, Video, Wi-Fi and General | Retained stock handlers, existing recovery owner panels, native navigation tests | Deliberately retained; generic Job/Recovery layouts are not claimed integrated |
| External loading while ACE is present | Owner command/paused-context source review and disabled native staged preview | Stub pending idle preparation/result contract; standalone loading unchanged |

The final native suite passed 28 tests. Targeted checks cover the subsequent
completed-print removal admission adjustment. Independent review accepted the
read-only help routing and current-route removal review. On-device checks show
unavailable Retract opening help without dispatch, the correct four associated
tools in removal review, and nested help returning to that review. Snapshot
requests intermittently timed out; framebuffer reads were retried before further
navigation, without replaying physical commands or restarting services.

This audit does not assert unperformed physical acceptance, import support,
atomic route/removal support, or a new unified recovery backend. Those limits are
explicit in the UI and backend inventory. The standard release bundle remains
unchanged; publication was not requested or performed.

## 2026-11-01 standalone r14 follow-up

Standalone overview hides head-filter buttons when no ACE units are present and
reclaims their vertical space. Native lifecycle and runtime compilation checks
passed (2 tests). Candidate SHA256: `5c73f7e85efd575e573968a70d4f3a0d2fa75e16b2cb79a20fa61724a23072f6`.
The sensor-backed standalone backend suite passed 147 tests. Hardware loading,
heating and mounting have not been exercised; openACE remains disabled for testing.
See `analysis/unified-ui-native/activation-stockwidgets-r14/` for activation evidence.

## 2026-11-01 r15 loaded-source menu

Loaded sources now offer Unload in the slot menu. Selection opens a confirmation
with CANCEL / UNLOAD; no command is dispatched until confirmation. The current
loaded source is revalidated before opening and before dispatch. Native runtime
and lifecycle checks passed, including a loaded external slot menu regression.
Candidate SHA256: `9dd3d0174654209eaea8532ff607a25c2ec8765c290a4e030677492fb6afbc11`.
No physical unload was performed for this UI change.

## 2026-11-01 r16 standalone Take/Dock

Physical-head Take/Dock now uses WMP_TOOLHEAD_ACTION with session, request ID
and captured attachment. Native controls follow sensor-derived mounting state;
protocol absence, stale status and unresolved operations disable dispatch.
The helper reuses _CHANGE_TOOL T=<physical index> and PARK_CURRENT_TOOL with
sensor-confirmed completion. Existing stock macro homing/retry behavior remains.
Integrated backend/native checks: 158 passed. No physical Take/Dock was exercised.
Candidate: `5c69b6e6443de83a8eebe7ae299a4309464b679d5405163a56e115b7ba06f789`.

### Standalone Orca profile import — r17/r18

Installed the bounded Orca extractor, atomic compact catalogue and asynchronous
USB scan/review/save helper. Native review requires explicit Save; imported
metadata is available as a Profile selection in standalone filament drafts.
Combined backend/transport checks passed 178 cases; after the live visual
correction, native LVGL lifecycle and standalone transport checks passed again.
ARM artifact: `ab7af13ee5858cd75c8d9a5ccc3659ac4844b406ed273c929a3ef09d28e7208b`.

Idle activation succeeded with openACE disabled and heaters off. Live absent-USB
scan completed. The final dialog uses stock text actions and a fully opaque
backdrop; no underlying shadows remain. Evidence lives under
`analysis/unified-ui-native/activation-stockwidgets-r18/`. Actual USB file import
and physical filament actions are not yet hardware-qualified.

### Standalone Home indicators — r19/r20

Home no longer falls back to vendor filament colors when WM+ lacks material
metadata. It uses projected physical sensor state and loaded identity, showing
an outline for empty heads and a question mark for unknown state. The r19 live
view matched sensor readback: Heads 1, 2 and 4 loaded, Head 3 empty.

r20 adds a single navigation target over the original Home filament button and
excludes heater telemetry from the rendering cache key. Native tests verify
loaded/empty/unknown rendering, head order, color provenance, sensor changes,
no repaint on temperature-only changes, and hidden-page click rejection.
ARM build and idle activation passed. r20 artifact:
`b51b1b6b268907e4d3d2739b8617ef2a705c7759850b73a48267ed260bd88629`.
Live center-tap qualification is recorded separately below.

Live center-tap qualification passed: tapping (685, 420) on a Home filament
circle opens the new Filament view. Home and Filament agree on loaded/empty
state. Screenshots: `activation-stockwidgets-r20/02-home-live.png` and
`activation-stockwidgets-r20/03-center-tap.png` under the native analysis folder.
No heater, extrusion or tool-change commands were sent.
