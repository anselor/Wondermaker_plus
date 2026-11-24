# Screen header consistency audit

Branch: `work/r4-print-time-fixes`, based on r4 `7c81ada`.

Full-page titles belong in the first content row beside header actions. Reserve
space for every action, render a single title, and start progress content below
that row. A step heading, temperature, or instruction is body content, not a
second screen title. Compact confirmation dialogs can use bottom action rows;
they still need a single, clearly separated title when one is present.

This is a source inventory and verification checklist, not a claim that all
screens have been visually qualified. No live installation during the print.

| Screen / owner | Source finding | Remaining verification |
| --- | --- | --- |
| Preparing print / stock_print_preparation | Fixed: progress panel begins at y=0 beside STOP and CLOSE, with reserved title width; previously began at y=40 | Native geometry and real-font checks passed; later device screenshot |
| Standalone Home / stock_home_status | Title and CANCEL/DONE share y=0 header; common progress body starts below it, with no redundant split; unchanged view is cached | Native control/receipt lifecycle, raw-backend observation and replacement of old results covered; device font/layout and supervised stopping pending |
| Calibration / stock_calibration_status | Retained header CANCEL during active Maintenance; result title y=8 and DONE on the same header; separator y=40, body y=60 | Cancel, unconfirmed delivery, complete/incomplete cleanup, saved-type summaries and restart states covered by native tests; real-font fit checked; device screenshots pending |
| Guided scrub / stock_nozzle_scrub | Panel begins y=0; actions overlay its reserved title row | Prepare/Re-check/Heating/Finished header/action geometry and real fonts checked; remaining phase variants and device screenshots |
| Load/unload/mount/dock / stock_filament_procedure | Full-page title y=2 and actions y=0; compact title top, actions bottom | Normal and compact modes, outcome captions; fresh bound mount/dock Stop covered by native lifecycle checks; physical qualification pending |
| Recovery/cancel/discard / stock_recovery_progress | Full-page title y=4 with actions; compact title top and actions bottom | Expanded state matrix checks recovery choices, cancel and discard, including stale/refused/complete states; USE SAVED now has 116 px caption width for its measured 109 px text |
| Resume / stock_resume_progress | Panel attaches at y=0 in vendor popup | Constructor/title and real-font fit checked; confirm vendor sibling occlusion on device |
| Nozzle editor / stock_nozzle_editor | Title y=10 beside BACK/SAVE y=8 | Title now reserves a 12 px gap before BACK (previous box overlapped it by 4 px); rendered font/geometry checks and all nozzle values |
| Probe calibration / stock_probe_editor | Title y=8 beside controls y=0 | Adjustment and save-review headers with all visible actions pass geometry and factory-font checks; device screenshots |
| Extruder setup / stock_identification | Title y=10 in header | Title now reserves a 12 px gap before BACK (previous box overlapped it by 2 px); rendered setup/normal headers, then running/restart variants |
| USB profile import / stock_profile_import | Title y=4 beside BACK/DONE y=0 | Initial, review, saved, error and busy headers pass geometry/factory-font checks; device screenshots |
| ACE routes/sources/brand/drying/source editor / stock_ace_filaments | Explicit title and header actions in picker/editor modes | Long-name headers, brand/source/route pickers and fresh/stale assignment/removal subroutes covered. First body labels now start at y=48 below 40 px header actions; removal warning follows at y=84. Device screenshots remain |
| Filament and toolhead pages / stock_filament_native, stock_toolhead_view, stock_filament_page | Extend vendor-owned page/content rather than owning a screen header | Verify retained vendor titles and section labels |
| Print preview / stock_preview_page and stock_preview_* | Retained filename now ellipsizes before measured header action bounds; notice stays at y42 below header | Long filenames and PRINT/COPY/COPYING/OPEN FILE covered by native/font checks; device screenshot pending |
| Notices / stock_notice | Message-only modal; no separate screen title; confirmation actions bottom | Plain and confirmation notices have no extra title; action fonts and bounds checked. Long-body scrolling/fit is a separate content audit |
| Runout prompt / stock_pause_prompt | Compact title at top with bottom actions | Head 4 compact title and footer actions pass factory-font/spacing checks; long guidance scrolls in its body; device screenshot |
| Brand/colour/text pickers / stock_brand_controls, stock_colour_picker, stock_text_keyboard[_host] | Brand extends the card; colour and text construct/adopt the original vendor modal, retain its geometry and add no header labels | Vendor/artwork screenshots remain; callback/lifetime behavior covered in native lifecycle |
| Temperature keypad / stock_temperature_keypad | Adopts the stock modal but adds Target temperature (C) at x=89/y=8, 696x24 | Header font/geometry checked against pinned constructor root 800x425 and keypad beginning y=34; original image-key geometry still requires device visual qualification |
| Diagnostics / stock_diagnostics | WM+ diagnostics title y=10 beside CLOSE y=0; scrolling summary below y=45 | Fresh/stale headers pass factory-font and geometry checks; device screenshot |
| Enlarged thumbnail / stock_image_preview | Image-only overlay with CLOSE at top right, no added title | Action font/bounds checked; device image/artwork screenshot |
| Completion/startup/navigation hooks / stock_completed_display, stock_startup_restart, stock_navigation_tabs | Decorate vendor UI; no independent header | Check no injected title duplicates |

Audit the remaining helper modules through their owning screen above. State-only
helpers (`stock_identity_edit`, flow, event, geometry and backend adapters) do not
construct independent screens. Device screenshots and normal/compact font-fit
checks remain necessary before marking this audit complete.

## Rendered header qualification

`tests/unified_ui/screen_header_contract.hpp` renders independent screen owners
through their production widget constructors. `test_screen_headers_with_factory_fonts`
measures the resulting title and action labels using the pinned factory
`lv_txt_get_size` and its actual fonts. It checks one title, one-line fit,
screen bounds, reserved action width, title/action row alignment, and compact
footer separation. It does not substitute text-length estimates or search
results for rendered geometry.

The initial 17-scene baseline found seven defects: title boxes intruded into
BACK by 2 px in Extruder Setup and 4 px in the nozzle editor; ACE source, load,
drying, unit-edit and adoption titles wrapped beyond their allocated height
with long supported names. The measured title heights ranged from 40 to 120 px
inside 25–28 px label boxes. The fixes reserve a gap before BACK and use LVGL's
single-line ellipsis for dynamic ACE header names. Full values and operation IDs
remain unchanged. The editable unit-name header also ends before the first body
row; the unit-name hit area no longer overlaps that row.

The expanded audit covers Home, Resume, normal/setup calibration results,
Prepare/Re-check/Heating/Finished scrub states, load/unload/mount/dock progress,
compact load/unload confirmation, probe adjustment/save review, normal/setup
identification, nozzle editing, USB import, recovery/cancel/discard, and ACE
source/load/drying/unit/adoption/brand/source-picker headers. This is not yet a
complete per-state audit of vendor-owned decorators, pickers, notices and all
ACE subroutes. Those remain open, as do device screenshots.

The follow-up pass rendered quick assignment and removal in both fresh and
stale states. Their first body label began at y=36 inside the 40 px header
action area. It now begins at y=48, with the removal warning moved to y=84
to preserve separation between body rows. The expanded recovery-choice case
also found USE SAVED wrapping into two lines (109 px text in a 98 px box).
Its button is now 128 px wide, with a 116 px caption and non-overlapping
neighboring actions; the title reserves space for the full action row. The unsupported material-preview route cannot currently be
entered (`source-material` is rejected) and is not counted as a verified live
screen.

Local outcome of this pass: all 30 scenes pass the factory-font header contract.
The existing native lifecycle and progress-panel font-fit checks also pass. An
initial expanded run failed only because its expected scene count was 31 rather
than 30; the count was corrected and the final header test passes. The original
baseline failures remain recorded in `analysis/screen-header-audit/baseline.json`,
and current rendered geometry in `analysis/screen-header-audit/final.json`.
The test harness and source inventory are committed; generated local audit
records are retained outside the distributable package.

## State matrix and retained vendor ownership

`tests/fixtures/screen_header_scenarios.json` now names every scenario explicitly;
the harness must produce exactly that set, without duplicates. It includes
running/stopping/complete/refused/failed/recovery states for all four service
actions, the remaining active scrub phases, probe preparation/accept/conflict/
retain/stale states, identification restart/running, import review/save/error,
recovery choices, and fresh/stale ACE subroutes. Header buttons are checked
against each other as well as against the title; selected first body labels
must begin below the action row and cannot overlap the following body label.

The source inventory also covers the adapters that retain factory ownership:
colour and text keyboard hosts call/adopt the pinned constructors rather than
create a second header; brand controls are card widgets; preview rows and status
notices decorate the existing preview; Tools/Video are tab captions. Completion,
startup, job-busy, exclude/cancel, service-event, identification/calibration flow,
picker-lifetime, identity-edit and geometry adapters do not create independent
screen headers. Diagnostics and enlarged-image owners, absent from the first
inventory, are now listed and rendered explicitly.

The temperature header is a special case: WM+ adds its descriptive label to the
stock number keyboard. Its test pins the original constructor's instructions
for root size (800x425) and keypad canvas (x=89, y=34, 696x357). The added title
ends at y=32, above the keypad, and fits its 696x24 box in the real font. This
does not claim that synthetic keys reproduce the vendor's image artwork; those
keys keep their original geometry and still need device visual qualification.

This remains a local geometry/font and source-ownership audit, not a completed
physical review of the vendor display. Retained vendor title placement/artwork,
long error-body content and real device screenshots remain explicit follow-up
items. No printer installation is part of this work.

Final local state-matrix result: 102 declared scenarios pass the factory-font
header/action/body-boundary contract. The initial 98-state run reproduced one
recovery caption defect and four fresh/stale ACE body/header overlaps; all five
failures are fixed. Native lifecycle and existing progress-font checks passed
with the production changes. The added keypad fixture initially tried to delete
its modal twice during teardown; that harness lifetime error was corrected, and
the final 102-state rerun passes. Generated state baseline/final records remain
in `analysis/screen-header-audit/`; package proof is recorded in the repair tracker.

## Print preparation Stop

The preparation overlay now keeps STOP beside CLOSE in the header. STOP calls
the existing runtime print-cancel route and dismisses the preparation overlay
so the retained cancellation receipt/progress view can take over. CLOSE only
dismisses the overlay. This adds no G-code, polling, thread or alternate cleanup
path. The existing cancellation worker retains its fresh ownership, reviewed
request and delivery-receipt checks.

Native lifecycle coverage checks both header hit targets, title separation,
Close without cancellation, Stop callback delivery, dismissal and a subsequent
job opening a fresh preparation view. This is local evidence; attended printer
qualification remains pending.

## Identification cancellation states

The existing header action becomes CANCEL during an owned request and remains
visible but disabled while cancellation is pending or publication has begun.
The regular cancelled result offers DONE beside START; setup retains its
mandatory identification retry rather than marking setup complete on a stop.
The factory-font scenario fixture includes active, cancelling and cancelled
states for both entry pages. No second header or additional button row is added.

## Recovery early Stop states

Recovery review and reviewed-but-not-yet-receipted Continue expose STOP beside
CLOSE in the existing header. Confirmed cancellation before preparation uses
DONE and a terminal explanation, without a running preparation step. The worker
supplies action availability from its fresh session/ownership and exact ticket;
receipt-based fallback remains available to older display callers. The added
review, dispatched and cancelled scenes bring local factory-font coverage to
111 scenarios. Attended printer verification remains pending.


## Retained factory constructor audit

`tests/test_retained_screen_headers.py` checks the exact SHA-pinned ARM client
and decodes immediate arguments at the original LVGL call sites. The five tests
cover the shared content card, colour picker, text keyboard, Maintenance header
and print preview. They inspect the actual binary, not synthetic widget artwork.
They do not execute the full constructors or prove translated/dynamic text fit.

- The shared card (`draw_content_bg`, `0x543214`) begins at (90,55), measures
  695x357, and has its separator at local y40. The header/body separation is
  retained by the colour and Maintenance constructors.
- The colour picker (`0x4f82a8`) has BACK in its original 40px header and retains
  83x83 colour tiles. Its action width uses LVGL's `0x27d1` content-size sentinel,
  not a pixel width. It adds no independent WM+ screen title.
- The text keyboard (`0x54ec48`) has an 800x425 overlay and 696x357 card at
  (89,55). Its entry is 685x44 at local (5,12); the key area is 690x280 at (6,64).
  The entry ends at y56, above the keys. It is editable content, not a duplicate
  screen title. Keyboard artwork and translated key captions still need device
  review; these binary checks do not render those assets.
- Maintenance (`0x4b6470`) places its retained title at local (33,12), its
  original action in the 40px header, and the 693x314 body at y41. The existing
  WM+ result overlay already replaces the full card/header rather than layering
  another header over the original OK row. The active header was blank; the follow-up below reuses that label and
  covers its title/CANCEL geometry. Device occlusion/artwork remains pending.
- Preview (`0x537710`) puts its filename at (33,12), above the 149x149 thumbnail
  at (60,66). The WM+ informational row occupies y42..66. However, the constructor
  does not constrain the filename label before aligning it; the earlier WM+
  preview adapters also left that width unconstrained. A legal 246-character
  filename (`W` repeated 240 times plus `.gcode`) measures 3649px in its pinned
  Regular16 font against a 695px card. Long filenames can exceed the header
  and overlap actions in the unmodified constructor. The WM+ shared preview
  control now constrains that retained label against measured header action
  bounds, with a 12px gap and one-line ellipsis. The underlying filename and
  routing identity remain unchanged.

The header is fitted on attachment and when an action caption/geometry changes,
not on each shared status refresh. Print preview initializes its CANCEL caption
and geometry once; USB copy caches its caption/body text, reserves 128px for
COPY/COPYING/OPEN FILE and refits only when the caption changes. Existing widget
identities, callbacks, parentage and fonts are retained. This introduces no new
widgets or polling. Native lifecycle checks verify the complete retained filename,
header bounds and unchanged layout-update counts on repeated readiness/USB
status. Four added preview scenarios exercise the shared production header fitter
with real factory-font measurement; device screenshots remain pending.
No installation or printer access occurred.


Preview overflow fix verification: native lifecycle and all 115 named
factory-font header scenarios pass. The tests retain the 246-character filename,
verify ellipsis sizing with a 12px action gap, cover PRINT/COPY/COPYING/OPEN FILE,
and assert no extra header/button layout updates on unchanged readiness or USB
status. The first lifecycle run caught a regression in the existing altered-button
Cancel guard for externally owned admission; that guard was restored and the
final combined rerun passed. The five retained binary geometry checks also pass.
ARM build and matching reviewed delivery export passed. Screen-package/material
installer checks passed (248). Artifact SHA256:
`b95caebaa4ab22211980f84886f51eb83324a959ccc520cf090a2e8bc51efa5a`.
Device review remains pending.


## Active Maintenance title

The retained Maintenance constructor (`0x4b6470`) creates a title label, stores it
at `0x385fc28`, initializes it with the empty string, and places it at local
(33,12). Its active refresh (`0x4b6c8c`) updates body labels from the separate
array at `0x385fc90`; it does not populate that header label. Thus the active
view had a CANCEL action but no visible screen title. The earlier concern about
a changing header instruction was not borne out by the pinned binary.

After the original constructor returns, the normal Maintenance adapter now
passes that factory label to the existing calibration-status owner. It verifies
that the object is a label beneath this exact page, sets “Calibration”, and
reserves header action space with a 20px single-line ellipsis box. The original
position/font and widget identity remain. This runs once on construction, not
on status refresh, and adds no widget. Foreign/stale labels, non-label objects
and setup-guide titles are not adopted. The opaque result overlay continues to
cover the complete original card/header when it presents a result.

The binary audit now checks the actual title creation/global/blank initializer
and distinguishes body refresh from header state. Native lifecycle checks cover
reuse without allocating a label, unchanged refresh layout count, invalid label
rejection and preservation of setup titles. A new active Maintenance scene adds
its title/CANCEL geometry to the real-font matrix. Device screenshots remain
pending; local test/build results are recorded in the repair tracker.


Active Maintenance follow-up results: six retained constructor checks pass;
native lifecycle and all 116 factory-font header scenarios pass; ARM build and
matching reviewed delivery export pass; screen-package/material installer checks
pass (248). The screen artifact is
`8fa3692ed69dc1806444db6847213bb62687749706e054abfe15dab7594a90d3`.
No printer installation, service restart, motion or remote push occurred.
