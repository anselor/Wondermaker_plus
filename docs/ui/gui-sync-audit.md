# GUI data-sync lifetime audit

8 November 2026. Requested rule: update existing widgets during data sync;
preserve touch targets, focus, open selectors, scroll, and unsaved input.

## Scope and evidence

Reviewed the WM+ native screen adapters, renderers, runtime refresh paths,
legacy openACE overlay ports, both HTML front ends, and preload C wrappers.
The source inventory and hashes are in
`analysis/validation/2026-11-08-main-track/gui-sync-audit/source-inventory.json`.
Model JSON regeneration is distinguished from destruction of live UI objects.
The vendor's closed-source screens are outside this source audit; WM+ wrappers
around them are included. Static review is not a physical-touch qualification.

## Required changes

| Priority | Area | Evidence / consequence | Required approach |
|---|---|---|---|
| Fixed in r90 | Preview row freshness/editability | `stock_preview_rows.hpp::update` formerly included admission state in the layout signature, destroying all rows on a stale/fresh transition. Failing-before/passing-after native regression demonstrates this. | Update disabled state on existing buttons and retain callback admission checks. |
| Deployed r91 | Other preview row data changes | Previously the method keyed the complete rows JSON and called `clear()` when any row changed. A changed label, color, usage or eligibility replaced every row's interactive controls. | Reconcile rows by sliced ID. Update labels, colors, enabled state and geometry; add/remove only genuinely added/removed rows. |
| Deployed r91 | Pause/runout invitation | `stock_pause_prompt.hpp::update` calls `close()` when `eligible()` becomes false. Eligibility depends on current paused status, so a transient unavailable snapshot can destroy and later recreate the invitation for the same pause. | Retain the same-origin prompt during uncertainty; disable Load. Retire on a confirmed changed origin, completion, navigation or explicit dismissal. |
| Deployed r91 | Home filament summary | `home_mini.hpp` retains its parent touch target but calls `lv_obj_clean(root_)` when freshness, presence, color or unit data changes. Decorative children are recreated. It is better than replacing the touch target, but still violates the preferred update model. | Retain swatches/status labels by head or unit/slot identity. Update decoration in place. |
| Deferred feature | Profile import | `stock_profile_import.hpp::update` calls `render()` on result/readiness changes; `render()` cleans the whole panel including buttons. Import is currently deferred/disabled. | Keep header/action/status objects and reconcile file choices by path before enabling this feature. |
| Fixed locally; host-tested | Browser layout preview | Previously `preview.html::draw` called `stage.replaceChildren()` for every response, losing focus and pointer targets. | Keep a DOM map keyed by widget ID; update properties and reconcile membership/order. |
| Unused production renderer | Generic full-page surface | `native_renderer.hpp::paint` calls `Surface::clear`; `LvglSurface::clear` cleans the root. Current `Runtime` does not instantiate/call this Renderer; it uses stock adapters. | Convert the frame API to keyed reconciliation before using it for a synced production page. Do not mistake model `widgets_.clear()` for a live-object deletion. |

## Existing paths that retain controls

| Area | Observed behavior / limits |
|---|---|
| Filament overview, ACE slots, external sources, source editor, dryer, unit editor and source picker | `StockAceFilaments` uses a keyed widget registry and `RenderFrame` reconciliation. Its large JSON layout key triggers reconciliation, not automatic wholesale deletion. Same-view refreshes reuse controls; `retire_widgets()` deletes omitted items. View changes clean the pane. Dropdown options change only when their contents change. Position-keyed decorative items still merit reorder tests. |
| Toolhead controls | `StockToolheadView` retains objects by control ID and updates values, selections and readiness. The native filament adapter updates existing stock objects and navigation controls. |
| Load/Unload/Take/Dock progress | `StockFilamentProcedure` updates preallocated step labels, colors, temperatures, captions and enabled states. It deletes the dialog on close, not each status refresh. |
| USB copy progress | `StockUsbPreview` allocates stages at attach and updates existing controls/status. Its close operation retires the preview. |
| Nozzle editor, temperature keypad, text keyboard, identity draft, color picker | Editor state is retained; close/commit/cancel or invalid ownership retires dialogs. Text keyboard layout switching explicitly rebuilds keys in response to choosing another layout, not telemetry. Brand controls retain dropdowns and avoid rewriting options while open. |
| Diagnostics and identification | Existing text/action/step objects are updated. Page destruction clears references. |
| Calibration status overlay | Text updates retain the overlay while it is needed. Returning from an error/unavailable state to the normal stock calibration view removes the overlay. This is an overlay visibility transition, not a full stock-page rebuild. |
| Pause prompt with stable eligible origin | Existing root is retained. The unavailable-status exception is the high-priority finding above. |
| Legacy openACE recovery/manual/setup overlays | Native renderers reuse button/label slots, update text/geometry and hide unused slots. They destroy roots on ownership/display loss, explicit deactivation or damaged object trees. Model `rebuild()` constructs data, not LVGL objects. Fixed-slot action rebinding still requires press/release identity coverage. |
| Remote touchscreen web page | `device/www/index.html` updates a persistent canvas and existing connection/status elements. Short-lived touch-ripple elements are user-event decoration, not synced control replacement. |
| Preload C fixes and lifecycle glue | No periodic full-widget-tree destruction was found in the inspected wrappers. Constructors, failure cleanup, navigation and explicit modal close remain legitimate lifecycle boundaries. |

## Acceptance rule for the follow-up fixes

For a fixed view and stable logical IDs, synchronize changed temperatures,
colors, labels, availability, operation progress and stale/fresh status without
allocating or deleting controls. Assert object identity and unchanged allocation
counts, retained scroll/focus/drafts, and exactly-once dispatch. Stale state must
still refuse actions; retaining a control never means retaining old permission.

For actual membership changes, remove only missing IDs and create only new IDs.
Do not allow a press begun on one logical item to release onto a newly rebound
item after reorder. Page navigation, explicit dialog closure and ownership loss
may retire the affected subtree. Tests should target these changes rather than
repeat unrelated parser or previously accepted feature checks.

## Current validation

r90 deploys only the first preview admission-state fix. Native lifecycle test
fails before it and passes afterward (`preview-row-stability-before.xml` and
`preview-row-stability-after.xml`). ARM build passed. Deployment preserved 26
other files; live restart readback preserved all loaded identities and states,
with the printer ready/idle and nozzle targets zero. No printing or motion was
commanded. At r90 the remaining findings above were open; the original missed tap's
cause has not been conclusively established.

### Active-screen corrections prepared after r90

Local preview rows now reconcile by sliced ID. Label, color, usage, eligibility
and geometry changes update existing objects; reordering retains each button's
logical ID. Only missing rows are retired and new rows allocate controls. The
first four stock color pairs remain in use; additional pairs are owned by their
rows. Duplicate/empty IDs disable admission without replacing existing rows.

The pause invitation retains its dialog during unavailable status, displays the
unavailability, disables Load and rejects a stale callback. Fresh status restores
controls for the same pause; explicit dismissal and confirmed changed context
still close it. Home retains a bounded decoration registry, hides unused objects,
and updates swatches instead of cleaning the subtree. Its original parent touch
target remains stable.

The focused native lifecycle test passes (`gui-sync-active-screens.xml`). New
assertions cover data changes, row reorder/removal/addition, stable callbacks,
scroll retention, pause stale/fresh transitions, stale Load refusal and Home
child identity/allocation stability. The intermediate row test initially failed
because its insertion fixture created a JSON array instead of an object; fixing
that fixture allowed the reconciliation tests to exercise the intended path.
The ARM build passed (`1c1f3c8ceedc95892109c2d067ae120a19c40aa9baa0315f55639605eef62df3`); r91 deployment passed, preserving 26 other files. Live Home and preview rendering passed visual checks (`r91-home.png`, `r91-preview-row.png`, `r91-row-updated.png`); preview was cancelled. Loaded-state preservation passed (`r91-restart-verification.json`). Pause behavior remains host-tested, not physically qualified during a print. Deferred import,
the unused generic renderer remain open. The development DOM rendering correction is documented below.

### Development browser preview correction

`preview.html` now reconciles nodes by widget ID within the same page/modal.
Data changes update text, styles, enabled state and reasons in place. Reorder
preserves logical callback identity and restores focus when a DOM move displaces
it. Removed nodes cannot dispatch actions; duplicate IDs reject the frame before
changing the existing tree. Navigation and widget type changes remain legitimate
replacement boundaries.

`tests/unified_ui/preview_dom.cjs` runs the actual inline script in a Node VM with
a DOM lifetime/focus model. It checks stable allocations and node identities,
no moves on ordinary sync, focus after reorder, current callback reasons,
exactly-once dispatch, disabled/retired callback refusal, color clearing,
membership changes and navigation. This is a host model test, not a real-browser
rendering qualification. The pytest entry point is
`test_browser_preview_retains_controls_on_data_sync`. No device deployment is
needed for this development-only page.

The stock file browser arrows are pagination controls, not scroll controls.
Following the user's correction, no arrow controls are being added to scrolling
panes as part of this audit.

### Legacy fixed-slot callback follow-up

The manual overlay now has focused host coverage in
`tests/unified_ui/legacy_sync.cpp` (`gui-legacy-sync.xml`). Twenty unchanged syncs
retain root/buttons without allocations and allow the original held press to
finish once. A changed panel revision/reordered action refuses the held release;
removed/reappearing controls require a new press. Stale admission still refuses
action. The legacy implementation suppresses the overlay on an invalid press;
reopening retains its widgets. This is existing behavior, not a new standalone
interaction requirement.

Source review also confirms management callbacks capture both widget identity and
panel serial on press and compare both on release. Management panel rebuilds
advance serial when rendered actions change. The focused test exercises the
manual native renderer, not the separate management renderer or an actual ACE.
The initial harness selected the wrong same-named header; its include paths were
corrected. An initial expectation that a rejected legacy release leaves the
panel expanded was corrected to assert the existing suppression/reopen path.

The generic full-page renderer remains unused by production Runtime; its clearing
surface API is still a documented prerequisite to any future reuse. Profile
import remains deferred. Neither path is being enabled as part of this audit.

### Closed-preview polling retirement

The native preview retired its GUI session on close but left `selected_file_`
set in Runtime. The status worker consequently continued metadata/roots requests
every five seconds on subsequent pages, including Toolheads. Retirement now
clears that worker selection under the existing mutex. Pending/unknown print
submissions retain their existing reconciliation ownership until resolved.

A native lifecycle regression opens a preview, observes metadata polling, retires
the closed session, advances past the refresh interval, and verifies that only
printer requests remain. It failed before the fix and passed afterward. This
removes unnecessary background traffic; it does not establish the cause of every
reported status dropout or change the two-second freshness admission rule.
Evidence: `analysis/validation/2026-11-08-main-track/r105-preview-retirement/`.

### Status publication before active-preview refresh

Runtime now composes status with the cached preview metadata, publishes that
snapshot, and handles queued commands before performing file lookups. New file
selections show a metadata-loading state until the next poll. Refreshes retain
existing preview data while the request runs. Lookup failure is surfaced as a
file-metadata error on the next poll, without invalidating fresh printer status.

The targeted native regression failed against the previous ordering because
fresh printer evidence was still hidden inside the metadata GET. Coverage also
checks that slow lookup time does not renew the two-second status lifetime,
cached sliced rows remain present during refresh, and a file lookup failure
stays separate from printer availability. No freshness timeout was extended.
Evidence: `analysis/validation/2026-11-08-main-track/r106-status-before-preview/`.

The first live r106 preview check caught an initial-handoff issue: the placeholder
file was admitted to review before metadata arrived, making its first real
revision look like a configuration change. The r107 correction retains the
loading state until metadata is available (or an actual metadata error is known).
The native lifecycle harness now covers placeholder-to-ready handoff in the
retained stock page and rejects the spurious configuration-change message.

### Recovery and cancellation outcome stability — 12 November

Retaining widgets alone does not preserve the user's workflow when delayed
snapshots can replace a terminal outcome. The r144 recovery corrections preserve
recorded resolution results, whole-attempt completion and restored terminal
views for their exact attempt/session. Continuation preparation completion is
projected separately from actual print completion. A new backend session still
requires fresh discovery and review; controls do not retain old authority.

The subsequent cancellation regression reproduced the same issue in its
restored runtime path: a completed cleanup panel reverted to unknown after an
older hold snapshot. Commit `2e0f7a2` retains completion for the exact cancellation
identity and backend session. Native lifecycle coverage failed before the fix
and passes afterward, preserving widget count and command count while checking
that a new backend session re-evaluates the durable record. This correction is
local pending candidate deployment. Physical interruption qualification remains
separate; see the current release table in `standalone-completion.md`.

### Unchanged progress synchronization — 12 November follow-up

The recovery/cancellation progress panel retained its widgets but still rewrote
captions, labels, colors and geometry on every identical GUI refresh. A local
change now checks screen lifetime and operation identity first, then skips an
identical result. Opening a new panel resets the render cache. Freshness and
operation changes still repaint and re-evaluate controls. The native lifecycle
regression verifies 100 identical updates produce zero text writes and preserve
widget count and scroll, followed by stale and terminal transitions. It passes.
This reduces redundant GUI work; it is not proof of the missed remote-tap cause.
ARM build and delivery verification passed. Installed r171 contains this change;
configuration, PID tuning, filament state and the cancellation record were
preserved (`r171-preservation.json`). Native bootstrap/artifact readback is
recorded in `r171-native-readback.json`. No motion or filament cycle was repeated.

The probe editor already skips an unchanged serialized view.

### Filament procedure synchronization — 12 November follow-up

The load/unload/Take/Dock procedure renderer also repeated text, style, flag and
geometry setters on identical refreshes. Its cache now compares synced data and
local submission/receipt, request, review selection/plan/reason and action
readiness. Close resets the cache; a new panel always renders. Incoming freshness,
operation identity and temperatures still invalidate it. Including local state is
necessary: a receipt or selection may change before the next backend snapshot.

The native lifecycle regression failed on the previous renderer's repeated text
writes, then passed with this change. It checks 100 identical review updates and
100 identical heating updates produce no text writes, preserve widget identity
and scroll, and still repaint a local pending→failed→pending receipt transition
without new synced data. Stale status disables STOP and fresh status restores it;
existing temperature, stage, owner/session, close/reopen and dispatch checks pass.
This is a rendering optimization, not proof of the intermittent touch cause.
Installed r173; the existing H4 completed result reopened with eight gray stages.
DONE closed it using a held touch after a short injected tap was missed. The
original operation and loaded state remained unchanged, with zero heater targets
and no position change (`r173-result-preservation.json`). This live check did not
repeat loading. The short/held distinction remains a touch-timing investigation;
it is not counted as a fixed physical-touch issue.


### Queued touch-frame loss — 12 November

Offline execution of the actual pinned 1.1.13 `evdev_read` bytes reproduces a
specific lost-tap mechanism: press and release in separate polls publish 1 then
0, while both queued before one poll are consumed and only state 0 is published.
This explains how a short touch can disappear during a GUI delay; it does not
establish that every reported unresponsive interval has this cause.

The narrow interior hook at `0x73ca58` publishes each pointer SYN_REPORT before
reading the next frame. It sets LVGL's continue-reading byte so LVGL processes
all queued frames in order during the same poll rather than accumulating a drag
backlog. The original coordinate parser/clamping, non-SYN events and keypad
behavior remain in place. The hook reproduces its displaced instructions and
uses the existing factory stack. The exact image fingerprint and additional
windows guard the hook, finish path, output initialization, and LVGL repeat loop.

The compiled ARM hook is executed with the actual factory reader in Unicorn.
Tests cover the original loss, two queued taps, 100 drag frames without backlog,
absolute/relative/MT coordinates, clamping, button state, unknown events, keypad
parity and stack restoration. The profile test and existing native popup/event
suite also pass: seven targeted tests total. No printer I/O occurs in these
tests. r174 is installed; exact artifact/bootstrap and the live interior jump target
were read back. The same original 80 ms tap at (714,125) now closed H4's retained
completed result on its first attempt. Home → H4 → Result also responded to short
taps. The existing operation, position, loaded flags and zero targets were
unchanged. This accepts the reproduced queued-frame defect and the observed
native interaction; physical finger-touch follow-up remains pending.
Evidence: `r174-touch-hook-readback.json`, `navigation-r174-*`,
`r174-touch-preservation.json`, and `r174-preservation.json` in the November 12
audit. No load/unload or motion was repeated.
Evidence: `r173-touch-reader-reproduction.json` in the November 12 audit and
`tests/test_native_touch_frames.py`. The remote injector remains at its original
80 ms duration so the live comparison does not mask the defect with a longer tap.
