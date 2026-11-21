# r4 installation lifecycle audit

Audit date: 2026-11-21. Source: `8519032b124b864cc3f647be70eeff740197594e`
(`origin/fw-1.1.13/r4`). Work branch: `fix/r4-install-lifecycle`.

This is an audit and proposed implementation contract, not a claim that the
installer already implements factory restoration. No printer was changed.

## Conclusion and reproduced report

**Current uninstall is not a factory restore.** All six components have an
uninstall entry point, but their semantics differ. A completed invocation can
leave active WM+ macros and their helpers, as well as inactive files and backups.
Per-install rollback journals do not provide a common factory baseline.

A disposable reproduction copied `config/stock`, replaced `macros.cfg` with
`config/live/macros.cfg` to model a previous whole-file WM+ installation, applied
the current configuration plan, then applied the uninstall plan. Result:

- `macros.cfg` was byte-for-byte unchanged.
- 18 active sections named `gcode_macro _WMP_*` remained.
- The removal plan retained `wm_material`, `wmp_recovery`, `wmp_case_light` and
  their callers. Component uninstall consequently retains their modules.

This proves the mechanism behind the report; it does not identify the exact
historical release installed by the reporting user. Current planning tests
mostly start with stock files, so passing them does not prove legacy cleanup.

## Component inventory and gaps

| Component | Installed effects | Current uninstall | Factory/update gap |
|---|---|---|---|
| config | Generated `wmp-screen-runtime.cfg`; final include in `printer.cfg`; all material helpers plus identification/recovery/light helpers installed implicitly | Comments attributable generated sections, removes an empty managed include, removes three recovery/light helpers only if dependencies allow | Does not revert inline legacy changes in `macros.cfg`, `change_macros.cfg`, `offset_calibrate.cfg`, wipe, extruder, light or printer configs. Commented generated files and publication backups remain. Config-only component install installs material helpers whose removal belongs to another component. |
| material | `HELPERS` in `klipper/klippy/extras`; creates `wm_material.cfg` if absent | Disables material section; deletes current helper list if no retained dependencies; keeps configuration and filament data | No persistent original/absent receipt; previous existing helper is deleted rather than restored. Every changed update creates another previous-version backup. Helpers retired from a future `HELPERS` list are invisible to that future uninstaller. |
| moonraker | Directory and HTTP-error source patches; managed receipts under `~/wmp/backups/moonraker-*-managed`; service lifecycle | Restores verified recorded originals via transaction code | Stronger existing model: original, installed and previous generations distinguished, with firmware rebaseline checks. Receipts/archive remain. This is a component baseline, not proof of a complete factory image. |
| preload | `~/wmp/lib/libwmp_*.so`; screen service drop-in; defaults helper and Klipper defaults drop-in; publication stages | Deletes libraries found by the current local `sources()` list, both drop-ins and defaults helper; restarts and verifies stock client | Uninstall does not restore the original recorded service/drop-in bytes. Old library names absent from the new source list can remain. Per-stage previous bytes are rollback evidence, not a durable factory baseline. Stages/logs and directory cleanup are separate. |
| touchscreen | `/opt/wondermaker_plus` payload; bridge/fixer units and states; nginx include/original backup; Moonraker webcam and sometimes timelapse selection | Runs legacy shell removal, deletes webcam by name, removes units/prefix and restores nginx backup or strips marker | Install is transactional but explicit uninstall does not use its camera/service/file receipts. It cannot restore a pre-existing webcam it replaced or original service states; selection changes are not undone by the shell script. API/nginx errors can be printed while removal continues and the script exits successfully. |
| shaper | Six allowlisted Klipper source files; builds C helper; keeps hash-checked stock copies/manifest | Restores recorded stock source and rebuilds helper, waits for Ready | Stronger existing model: recognizes stock/backport/unknown and refuses unknown sources. Keeps baseline evidence/build state. Manifest/backup trust and release migrations still need to be included in the common matrix. |

Sources: `tools/components/{config,material,moonraker,preload,touchscreen,shaper}.py`,
`tools/reconcile_screen_config.py`, `tools/preload_bundle.py`,
`tools/moonraker_directory_transaction.py`, `tools/shaper_backport.py`,
`tools/touchscreen_{runtime,transaction,settings}.py`, `scripts/uninstall.sh`.
Legacy whole-file config updates in `utils/config_sync.py` save a new
`.wmp-backup-TIMESTAMP` on each wave; the latest one can contain WM+ content.

The legacy full-file surface is larger than the current ten behavior baselines:
`config_sync` can publish eligible files throughout `config/live`, including
`crowsnest.conf`, `moonraker.conf`, `fluidd.cfg`, `timelapse.cfg`, topology and
board configuration. The current config uninstall does not revert those legacy
changes either. Migration must inventory the actual recorded file set, not only
`macros.cfg` or the current generated include.

Preload's startup defaults helper can also add missing keys to
`saved_variables.cfg` and `tmt1.ini` and records `.wmp-defaults-*.json` journals.
Removing its service drop-in does not undo those additions. These files contain
user state, so provenance must be per added key, never a blind whole-file reset.
The touchscreen journals in `/opt/wondermaker_plus-transactions` survive removal
of `/opt/wondermaker_plus`; they are separate from the nginx original backup.

Runtime-created records also need explicit disposition: filament profiles and
loaded/material history; nozzle and calibration records; operation/cancel and
recovery records; PLR sidecars such as `.wmp-coordinates`; screen preferences;
logs, staging directories, publication journals and compiled Python caches.
These are not all installer payloads, and deleting a name prefix is not a safe
ownership policy. G-code retention remains independent.

## Partial install findings

There are three different concepts currently called partial installation:

1. **Selected components:** the CLI accepts subsets. `preload` adds Moonraker
   implicitly, but needs matching helper and configuration contracts. A screen
   update cannot safely be independent when those contracts change. Config also
   installs material helpers implicitly, without a shared uninstall ownership
   record. The selection list is not a complete description of installed effects.
2. **Selected config files (`--files`):** explicitly rejected by unified-package
   `preflight.config_plan` and `components.config.install`. This is a confirmed
   current restriction, not an upload/permissions failure.
3. **HTTP config-only (`--config-only`):** also explicitly rejected for unified
   delivery, although CLI help/list still advertises it. Legacy tests exercise a
   different package path and do not establish unified support.

Both rejected options were reproduced locally before network access. The exact
command/error from the user's component-subset failure is still needed to tie
that separate report to a specific gate. Do not bypass backend/package checks
or reinterpret `--files` as permission to overwrite whole machine files.

A separate legacy usability issue: `config_sync` rejects a selected file that
already matches as “unchanged or unavailable”; a repeated partial update should
be a successful no-op for a valid, unchanged selection.

## Required forward lifecycle contract

The requested target is **factory software and managed behavior on uninstall**.
Whether calibration/tuning survives separately or resets too remains an explicit
policy decision; current audit does not authorize erasing tuning.

### Provenance, not backup filename guessing

Introduce a versioned, device-bound inventory on the printer, outside directories
that component uninstall removes. Reuse the proven shaper/Moonraker ideas rather
than treating the checkout-local `.wmp-install-journals` as the inventory.

For each allowlisted resource record its component owners, firmware baseline,
resource type, original presence/absence, original content digest and metadata,
verified baseline blob, installed generation/digest, and transaction state.
Record API objects/service enablement too, not only files. Preserve original
absence explicitly so WM+-created resources can be removed.

Classify a target before changing it:

| Classification | Install/update action | Uninstall action |
|---|---|---|
| Verified factory original, no baseline recorded | Capture and verify baseline once before publication | Restore that verified factory resource |
| Known WM+ generation with valid baseline | Replace/update; never promote this generation to original | Restore factory baseline, not previous WM+ generation |
| User-custom factory configuration | Preserve machine settings; manage executable behavior separately; record provenance for changed fields | Restore factory executable behavior while applying the chosen tuning policy |
| WM+ legacy generation with no baseline | Migrate only with exact historical release/hash evidence and a matching factory source | Use verified vendor factory content; never label an arbitrary backup factory |
| Unknown/edited resource or unprovable original | Report the specific conflict and prepare a reviewable migration; do not silently call it factory | Do not silently retain active WM+ and report complete; return incomplete with named resources |

A firmware upgrade starts a distinct verified baseline generation. It must not
restore old vendor source over a newer firmware. Archive old evidence, confirm
no pending transaction, and explicitly rebaseline, as Moonraker already does.
Never infer factory provenance merely because a file lacks a WM+ marker.

### Separate update rollback from uninstall

- Update rollback restores the immediately preceding working generation.
- Uninstall restores the verified factory generation.
- Keep one content-addressed immutable baseline per resource/firmware generation;
  do not create an endless chain of factory-looking backups on every update.
- Update installed ownership after successful readback. A prepared transaction
  must survive process loss before/after each rename or API write.
- Retain the existing hash, symlink, include-membership, concurrent edit and
  machine-identity checks. Never overwrite a user edit during rollback.
- Historical backups without provenance are evidence for review, not automatic
  restoration targets. The migration cannot manufacture missing history.

### Shared ownership and partial selections

Compute and show the dependency closure before mutation. Install prerequisites
when selected, or accept already installed prerequisites only after compatibility
checks. Refuse an incompatible selection before publishing anything, with a
concrete command to install the required closure.

Persist requested and implicit owners. Removing config must release its implicit
helpers; material/preload owners keep shared files while needed. Track retired
files from previous generations so cleanup does not depend solely on today's
source tree. Component uninstall must refuse removal that would break a retained
consumer, or include the required consumer removal in the reviewed closure.

Define file-level behavior explicitly: either support named behavior scopes with
validated dependencies and provenance, or remove the unsupported current-package
advertising and document component-scoped updates. HTTP-only mode must not be
advertised as supported without its own equivalent integrity/dependency contract.
Valid repeated selections should be no-ops, not failures.

### Full removal and completion verification

Prepare one removal plan for the complete selected dependency closure before
removing the first consumer. Restore factory executable configurations before
removing their helper dependencies. Preserve hardware IDs, geometry and tuning
according to policy, rather than copying another printer's full `printer.cfg`.

Verify resulting active include tree and macros contain no managed behavior,
removed libraries are unmapped, services/API records match their baseline, and
Klipper is Ready after the necessary activation. Report retained user data,
archives and conflicts separately. A retained active WM+ dependency means
**incomplete uninstall**, not successful factory restoration.

Only retire staging/backup evidence after successful verification and after any
required off-printer archive. Do not recursively delete generic backup globs or
user files. Uninstallation is idempotent; rerunning after interruption must
continue the same durable plan.

## Acceptance matrix before implementation can be called complete

Cover fresh factory -> install -> uninstall; two r4 updates -> uninstall;
verified r3 -> r4 -> uninstall; missing/untrusted legacy baseline; custom tuning;
new vendor firmware; all component subsets and their dependency closures;
unchanged selection; old retired payload; pre-existing service/API resources;
partial failure/process loss at each publication/removal boundary; concurrent
edit and linked dependency; reinstall after uninstall; repeated uninstall.

Assertions must compare restored bytes/metadata and active configuration to the
verified factory/tuning contract, not merely check that an entry point returned.
Exercise the actual explicit uninstall path as well as transaction rollback.
Local fixtures cannot establish physical homing or print quality; no motion test
is needed to reproduce the lifecycle defects reported here.

## Implementation priorities

1. Durable baseline/ownership inventory and migration classifier; distinguish
   unknown legacy state from factory before promising full restoration.
2. Config legacy cleanup using verified factory behavior, and shared helper
   ownership. Do not fix leftovers by blindly deleting referenced macros.
3. Receipt-based touchscreen explicit uninstall and accurate incomplete outcomes.
4. Preload original restoration/retired payload cleanup; material original/absent
   restoration and runtime-data policy.
5. Partial-selection contract, accurate CLI/docs, closure validation and matrix.
6. End-to-end install/update/uninstall verification and archive retirement.

Existing component rollback tests are useful evidence but do not close these
items. Implementation and release remain outstanding; nothing has been pushed.

## Validation performed

470 existing checks passed across configuration reconciliation, CLI orchestration,
preflight, shaper, touchscreen transactions/runtime and Moonraker transactions.
The initial run had eight fixture skips; after restoring the retained vendor
parser/ELF evidence, those cases were rerun successfully. This is existing test
coverage, not a claim that the acceptance matrix above is implemented.

The disposable legacy install/uninstall reproduction and both unified partial
option refusals were also executed against this checkout. No printer connection,
service restart, motion, install or uninstall was used for this audit.

## Implementation follow-up

Work now proceeds on `fix/r4-install-lifecycle`, still based on `8519032`.
See [the implemented lifecycle contract](installation-lifecycle.md) and
[the factory timing comparison plan](validation/factory-timing-comparison.md).
The findings above describe the audited released revision; branch changes are
not yet released or deployed. Local validation and the printer's read-only
removal preflight must pass before restoration or print testing.
