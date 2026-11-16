# Native screen candidate activation proposal

Status: the operator authorized idle activation with “proceed.” The reviewed
stock-widget candidate is installed; this does not authorize physical-operation
tests, settings saves or printing. Ordinary `deploy.py install preload` still
selects the sealed bundle, not this development candidate.

## Temporary standalone test — 1 November

openACE is currently disabled via a commented include in the live printer config;
its files remain intact. See native-readiness.md for evidence and restoration.
This is deliberate test-state drift from the repository config, not an uninstall.

## Current installed candidate — 1 November

Installed and verified mapped SHA256:
`5d14c9ad6a748bd3aa51f0b9ffff39b52f5073fd40efd8fce4fa5e6a839e6345`.
The prototype full-page Runtime presentation is removed. Additions use stock
content and retain the stock navigation, status and filament/preview widgets.
The obsolete legacy setup panel is suppressed while its recovery owner remains.

Each activation checked fresh idle state, saved rollback bytes, validated loader
dependencies, and coordinated the client/Klipper restart. Only the UI library
and the exact reviewed removal of post-extrusion PARK_CURRENT_TOOL changed;
other installed dependencies and printer configuration were preserved.
Evidence: local `analysis/unified-ui-native/activation-stockwidgets*`.

Follow-up screenshot feedback also supplies opaque editor/import dialog,
four-head popup, material popup, swatch, separator and filter-toggle evidence.
The editor actions are upper-bar Cancel and Save. Slot menus and labelled
field/value editors have r6 framebuffer evidence. The r7 update applies a
confirmed temperature directly, removes Heat, and provides X for target 0.
The r8 filament dialog uses its unit/slot as title, larger collapsed dropdown
values, a tappable colour swatch plus hex, and native text-only CANCEL/SAVE.
The r9 update hides overview tabs behind modal dialogs and adds per-unit
drying stubs, with humidity/temperature unavailable and Start/Stop disabled
pending the openACE contract. The r10 update tightens the filament/drying
action row and filament field spacing to follow the stock WM layout.
The r11 update restricts Toolhead Load to external heads, retains the selected
source in load dialogs, applies stock action-row styling to procedure dialogs,
and reads stock Home nozzle/temperature data for Toolhead display.
The r12 update groups external heads into slot-width cards ordered by head.
Material/assignment persistence and USB
import remain unavailable; nozzle material and mounting contracts remain gaps.

Stock Home, Toolheads, ACE overview, identity editor, Files, preview, grouped
source selector and enlarged thumbnail have framebuffer evidence. Preview layout was checked on the earlier candidate; this follow-up changes
editor/action-bar and Toolhead controls. Some injected
touches were missed; interaction reliability remains unresolved. Standalone,
physical-operation and full scenario acceptance remain incomplete. See
[native readiness](native-readiness.md) for the scoped validation record.

Historical target states below apply only at their capture times. Any further
activation requires a fresh preflight; no physical actions are authorized here.

For this candidate, capture these comparisons before accepting the presentation:

| View | Required evidence from actual stock client | Reject if |
|---|---|---|
| Home | Original stock status/navigation and temperature panel; head shortcut and grouped ACE mini-view | A replacement header/sidebar or opaque page hides stock content |
| Settings / Filaments, standalone | Original Settings tabs and stock colour/material controls rearranged into four sources | Mock-style replacement cards obscure the original page |
| Settings / Filaments, ACE | Same stock shell; titled, vertically scrollable units and four slots per unit; head filter and External sources | Pagination replaces scrolling, or filtering misrepresents slot ownership |
| Toolheads | Original selected filament widgets, stock-styled head tabs, corner edit, distance/temperature and arrow controls | Text clips, controls overlap, or changing a tab mounts a head |
| Identity / unit details | Stock picker/keyboard integration, retained context, clear draft exits | Mock keyboard replaces the stock one, or preview assignments appear saved |
| File preview | Original thumbnail and preview constructor, source rows and scoped selector/expanded thumbnail | Full-page mock replaces the stock preview or late metadata reopens it |
| Procedure / import previews | Scoped dialog with surrounding stock page visible; honest disabled backend gaps | A preview reports a completed action or hides stock navigation unnecessarily |
| Retained pages / recovery | Original XYZ, Video, Wi-Fi, General, Files and active-print pages; existing recovery owner | New content blocks stock navigation or resurrects the prototype shell |

Capture at native framebuffer resolution, including long labels and the smallest
actual content area. Record candidate/client hashes with captures. Host geometry
and callback tests support this review but do not prove native font rendering,
style inheritance, refresh behavior or touch hit boxes. Standalone and ACE
presentation both require evidence; one cannot qualify the other.

## Exact payload and target

Use `analysis/unified-ui-native/manifest.json` for the exact artifact, source and
runtime dependency hashes, and `review.tar.gz` for the bound review export.
Rebuilding changes that evidence; review and approve the resulting manifest,
not just a filename. All destination paths below are relative to the configured
printer user's home unless explicitly absolute.

| Payload | Proposed target / treatment |
|---|---|
| `libwmp_unified_screen_candidate.so` | Stage outside `wmp/lib`, then replace the single `wmp/lib/libwmp_openace-compat.so` entry. Do not preload both implementations: both hook the client. |
| `klipper_extras/wm_material.py` | `klipper/klippy/extras/wm_material.py`; exact tested helper required for connected operations. |
| `klipper_extras/wm_material.cfg` | `printer_data/config/wm_material.cfg`; ensure the existing printer configuration includes it exactly once. Preserve third-party includes and SAVE_CONFIG data. |
| `config/live/macros.cfg` | Compare/merge through the config deployment validation path. Needed for standalone E steps/tip shaping and existing WM+ print behavior; do not blindly replace a modified printer snapshot. |

Preserve the other preload entries and their order, notably fan, recovery and
Wi-Fi fixes. The candidate contains compatibility interception and the native
UI; a second compatibility library must not be added alongside it. In particular,
never put `libwmp_unified_screen_candidate.so` into `wmp/lib` for staging:
ordinary installation includes every `libwmp_*.so` there in the preload list.

The candidate binds the 1.1.13 client hash and function windows. A different
firmware or modified executable is a failed preflight, not permission to disable
the guard. The current candidate was built for AArch64 and imports
`libdl.so.2`, `libstdc++.so.6`, `libgcc_s.so.1`, `libpthread.so.0` and `libc.so.6`.
Its recorded maximum versions are GLIBC 2.17, GLIBCXX 3.4.21 and CXXABI 1.3.
Local inspection of the preserved V14 ELF found the same libraries and maxima.
The firmware update payload does not provide a complete OS-library inventory.
Read-only target inspection on 2026-10-31 confirmed AArch64, the expected client
hash, all five required library SONAMEs, and exports for all 157 strong undefined
symbols (including symbol versions) in candidate `1d09297c…`. Evidence is in the
ignored `analysis/unified-ui-native/target-inspection/abi-report.json`, bound to
the candidate and downloaded system-library hashes. This does not execute the
candidate or prove its dynamic lookups, hooks, UI behavior or hardware operation.
Repeat the check if the candidate, client or target OS libraries change.

## Preflight and rollback evidence

Before a concrete activation request, record the current printer's client hash,
installed compatibility/UI library hash, all active preload paths and hashes,
systemd drop-in contents, loaded process mappings, Klipper state, helper version,
configuration includes and relevant macro versions. Read-only inspection on
2026-10-31 found the running client's compatibility-library path contains
`b99a0a26fa4af5568cd2c712ffa2bb78bc9d050ada0c77b7cce84efae9da8779`,
the subsequent recovery-guard build, rather than the historical V14 baseline.
The initial service PID was a shell wrapper; inspection identified the actual
`client` descendant before checking its executable and mappings. This snapshot
is not a substitute for fresh pre-activation evidence or byte-for-byte rollback
backups. The earlier status query found a paused print; activation remains
unauthorized and must not discard that session.

The read-only activation-input capture also found installed tip-shaping phase
reports missing from the repository snapshot. Those optional reports are now
preserved in `config/live/macros.cfg`; they publish invocation-bound commanded-E
prefix/completion data without adding motion. The local/live difference is the
new bounded `WMP_EXTRUDER_STEP` macro, corrected reverse-travel reporting for the
existing unknown-class PLA fallback, and comments. The installed material config
already matches the candidate. Keep the existing material and openACE includes;
there is no need to replace `printer.cfg` for this upgrade. Exact captured bytes
and hashes are under ignored `analysis/unified-ui-native/activation-inputs/`.
They are review evidence, not a promise that live files have remained unchanged.
Compare again immediately before any authorized activation.

The operator-supplied frozen V14 library was verified locally as
`1a8e768a0f99cd4e1ef2b374ee5fbb7769dd4d157c66157ebb4e6754072c2da8`.
Leave its frozen directory untouched. The rollback backup must contain the
actual files displaced during this activation, which may differ from V14.
Include the library, helper, helper config, modified macro/include files and the
preload drop-in. Record both bytes and hashes before publishing replacements.
Do not roll back calibration, material identities or recovery journals merely
because the screen binary is rolled back.

Validate all staged payload bytes against the reviewed manifest before replacing
anything. Preflight must also verify the required config objects and prevent a
partial activation when the helper/config half cannot load. Ordinarily, recheck
idle state before shutdown/publication. An active or paused print, unresolved
recovery, or uncertain printer state prevents automatic activation. The only
alternative for the currently paused test is explicit operator approval to
abandon that test through coordinated service shutdown, as described below.

When openACE is installed, record its actual extension/version hashes and verify
its public status and command contracts without issuing physical commands. The
candidate manifest does not pin this external backend. Required evidence includes
session/configuration revision, job/operation state, loaded destination/identity,
inventory and device connectivity, plus the public SELECT, UNLOAD and mapped
print-submission interfaces. Missing or incompatible contracts leave their
controls unavailable; do not manufacture compatible status for acceptance.

Read-only inspection on 2026-10-31 captured 11 installed openACE extension files
and their hashes, live status and the command registry under ignored
`analysis/unified-ui-native/target-inspection/`. The public SELECT, UNLOAD,
SDCARD_PRINT_FILE, UNIT_ACCEPT, RENAME_UNIT and SET_FILAMENT commands are present.
Management capabilities report version 1 with context-bound registration and
acceptance, effective settings and identity settings. Session/configuration
revisions are integers. The observed operation is null, with a paused job.
These are interface/preflight observations, not physical-command acceptance or
proof of every dependency in the separately installed openACE core package.

## Activation sequence requiring explicit approval

1. Obtain approval for the exact reviewed manifest and for losing any current
   client/Klipper session. Starting the stock screen client restarts Klipper;
   this is not a UI-only restart and cannot preserve a paused print.
   Prefer that the operator ends the test first. If the operator instead
   explicitly approves abandoning the paused test by service shutdown, record
   that choice and the current job/operation evidence. Do not implicitly call
   CANCEL_PRINT, RESUME, or a recovery command to make the status look idle.
2. Capture rollback evidence and stage all payloads without selecting them.
3. Validate staged hashes, target libraries, firmware binding, config includes,
   macro dependencies and continued idle state across all components. For an
   explicitly approved paused-test abandonment, require no active motion
   operation and verify the observed job has not changed before shutdown.
4. Stop the client and Klipper for a coordinated file publication. Publish the
   reviewed files only after confirming both services and their processes are
   stopped. Retain the existing preload list with a single UI owner.
   These service/file actions are part of the approval, not implied by review.
5. Start the client in the agreed sequence, accounting for its own Klipper
   restart. Wait for final Klipper readiness, then inspect errors and actual
   loaded library paths/hashes. Confirm the helper protocols from live status.
6. Perform the no-motion screen walkthrough below. Do not begin physical
   acceptance merely because navigation works.

If startup or preflight fails after publication, stop the client before restoring
exact displaced files/drop-in. Restart in the same coordinated manner, verify
loaded hashes and Klipper readiness, and report the failure. Restoration does
not restore a print session. An activation tool implementing this transaction
and the live-target preflight still needs qualification; this document is not an
executable deployment package.

## Initial native-screen walkthrough

Use the real display and remote framebuffer. Confirm Home head buttons open
Toolheads and the mini filament view opens Filaments. Walk Home, Files, stock
settings tabs, each head tab, filament editor, unit editor, discovery/adoption views, removal stub, import stub, preview mapping selector and enlarged thumbnail. Check Back,
Cancel, Save/discard, vertical touch scrolling, text clipping and stock-page
return paths. Opening these views should not heat, home, feed or select a head.
Do not press Heat/Off, Extrude/Retract, Begin, Start, Adopt, Remove, Save, Import
or print-cancellation actions in this walkthrough. Adoption is connected, not a
stub. Keep edits as local drafts and discard them. Open only existing local
G-code previews; leave USB-copy and settings-changing actions for a separately
approved test.

Exercise both standalone and openACE presentation with appropriately configured
test installations; do not disable openACE on a live printer just to imitate
absence. Offline fixture tests cover multiple/disconnected ACE units, but do not
substitute for actual pixel/touch checks. Review unavailable controls for clear
explanations and ensure no hidden vendor movement callback is reached.

Physical acceptance is a separate operator-approved session covering each
connected operation, cancellation/failure and uncertain response handling.
Take/Dock, external hand-fed loading under openACE, ACE distance steps, atomic
route changes/removal and profile import remain explicit backend gaps.
