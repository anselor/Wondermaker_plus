# Native screen backend integration decisions

Review date: 2026-10-31. This is a source review of the adjacent openACE
checkout, not evidence of the version installed on the printer. No commands were
sent and no printer state was changed.

## Controls and responsibility

| Screen control | Existing implementation | Remaining work and owner |
|---|---|---|
| Physical-head temperature | Klipper physical `SET_HEATER_TEMPERATURE` avoids virtual T routing; standalone WM+ already uses it. | Connected in the native candidate: physical addressing, configured limits, owner/session/revision revalidation, matching target readback. openACE mode currently requires idle print and explicit null operation evidence. No new openACE command is required for ordinary manual heating; strict exclusion from concurrently starting ACE operations would require an execution-time backend guard. |
| Distance-only Extrude/Retract | Standalone `WMP_EXTRUDER_STEP` is connected. openACE's `_purge_head_command` wraps the preserved vendor purge with assist and verified-load checks. | A vendor purge is not a distance-only step. Define an openACE-owned public step operation with head/distance binding, assist, completion and interruption semantics; then connect WM+. Do not call private `_OPENACE_ZRU_*` macros directly from the GUI. |
| ACE Load | `OPENACE_SELECT TOOL=` resolves and prepares a routed source. | Connected for idle ACE sources: source-specific review selects a named eligible virtual tool; helper token binds source and profile; completion requires verified matching destination/material/colour. External hand-fed sources remain a separate flow. |
| ACE Unload | `OPENACE_UNLOAD HEAD=`, optionally `TO_UNIT=1`, exists. | Idle ACE unload is connected through a reviewed helper token and the public owner command. It does not request eject-to-unit. Completion requires the same ACE session, idle operation and empty-head readback; paused recovery remains separate. |
| External Load with openACE present | `OPENACE_LOAD_DIRECT HEAD=` prepares/selects/parks/heats; `DONE=1` confirms and primes. | WM+ needs the multi-stage flow and its current context/receipt contract. A single generic Load request cannot represent both stages. Standalone Load remains a different procedure. |
| Take / Dock | Stock macros exist, but can home or retry homing; selecting a virtual tool also changes filament state. | WM+ motion implementation gap. Provide explicit physical-head procedures with attachment and position preconditions before connecting these buttons. Neither a T command nor a stock purge is a substitute. |
| Print Start | openACE supports frozen per-print mapping through its print submission wrapper. | Connected in the local candidate through the WM+ helper, preserving preview file/session/configuration binding and native context. Matching helper receipt plus active frozen job file/pairs/revision confirms admission. Hardware acceptance remains. |
| Slot assignment Save | `OPENACE_MAP_TOOL` and `OPENACE_UNMAP_TOOL` edit individual routes. | Backend transaction gap for the approved multi-slot Save semantics, plus WM+ adapter work. Replaying several commands can leave a partially changed topology. |
| Remove ACE | `OPENACE_UNIT_REMOVE` delegates to the unit settings editor; documented behavior requires every referencing tool to be unmapped first. | Backend gap for atomic removal plus renumbering and affected-route preview. Keep the existing WM+ confirmation stub; do not silently substitute remove-only or a series of destructive edits. |
| Filament brand/colour | Existing addressed identity command supports VENDOR and COLOR; candidate typed extension preserves other fields and revalidates at delivery. | Connected for existing profiles. |
| Material changes / new profiles | Addressed identity command requires temperature/profile fields. | Shared product policy gap: define material defaults or imported profile values. Carrying the old material's temperature into a different material is not a complete implementation. |
| USB/profile upload import | Requested filament format and conflict semantics remain undecided. | Shared format/backend gap. Calibration/relative-recipe import commands concern engineering data and must not be presented as filament-profile import. |

## Verified behavior behind the extrusion distinction

`OpenACE._purge_head_command` checks the print and operation state and requires a
verified loaded destination. It then calls
`coordinator.run_with_assist(load.destination, lambda: prev(gcmd))`. The `prev`
handler is the preserved vendor implementation. The wrapper therefore adds
ownership checks and assist, but does not itself remove that handler's docking,
homing, parking or extrusion behavior. This corroborates the need to avoid
wiring the distance buttons to `EXTRUDE_FILAMENT`.

The registered `OPENACE_ACE_RETRACT` is explicitly ACE-only maintenance travel;
it is also not a substitute for retracting filament through the selected head.
The registration descriptions distinguish these operations, and the screen must
retain that distinction.

## Next integration order

1. Physical temperature and mapped print admission are now connected with
   delivery/readback tests; qualify these paths on hardware before release.
2. Connect source-bound Load/Unload using the backend's actual procedure and
   operation state, including the external two-stage load path.
3. Agree the public bounded-step and topology transaction contracts. Leave those
   controls unavailable until the relevant contract exists.
4. Implement physical Take/Dock separately from filament selection, then qualify
   the procedure on the printer with explicit operator authorization.

Source inspection is not physical acceptance. Existing standalone operations,
these proposed integrations, and all native touch/layout paths still require
on-device acceptance. This document does not authorize activation.

## External Load: verified integration gap

The inspected `klipper/extras/openace.py` matches the previously downloaded
installed source: SHA256
`279c731606c318fc651c6647ba12fcdce7387915f7626a1b1e86fc19063d8a6a`.
`cmd_LOAD_DIRECT` delegates to two distinct operations: preparation (select,
park, heat), followed by an operator insertion and `DONE=1` (sensor check,
target-defined priming, loaded evidence and standby temperature). WM+ must not
substitute the generic single-stage Load adapter or invent a universal distance.

`material_change.manual_flow()` is explicitly scoped to a captured paused direct
tool. Its idle result has `available=False`; `prepare_completion` is explicitly
`not_recorded`. `manual_context(EXPECT_CONTEXT)` requires that paused scope;
omitting the argument bypasses that context check. Therefore the existing paused
flow cannot serve as an idle preparation/result protocol.

The local unified UI now has an idle External Load preview showing preparation,
insertion and priming, with Prepare disabled and no generic Begin action. It is
used only when no actual source-bound procedure is available. Standalone and
existing verified procedures remain unchanged; paused recovery stays with its
existing owner UI. This preview does not establish physical state.

To connect it, agree an idle owner contract binding head, direct route, identity,
session and configuration to preparation, and a published result permitting
insertion/completion. It must distinguish returned, prepared, held, partial and
unknown outcomes; define whether an interrupted preparation can be newly
requested; and preserve completed priming rather than replaying it. WM+ then
needs a two-stage adapter with explicit operator confirmation between stages.

The [standalone Take/Dock contract](standalone-toolhead-procedure.md) records the
audited stock call chain and the required replacement. Checking `homed_axes`
before calling the vendor macros is insufficient: retries, offset-induced
travel, coupling behavior and successful-pickup side effects also need explicit
handling. Clearance, coupling retries and per-head flow remain decisions before
the new physical procedure can be enabled.

## Inspected source fingerprints

These hashes identify the evidence reviewed, not a deployment requirement:

- `klipper/extras/openace.py`: `279c731606c318fc651c6647ba12fcdce7387915f7626a1b1e86fc19063d8a6a`
- `docs/commands.md`: `dc43ddd952b47ee68cd89897a23da900841c1ce41b7e32948adf2b242249d8f3`
- `openace/binding/commands.py`: `379a78dda2072e4552660388c92613b26a7a9fc8f45a9ffc2a0960458c070c81`
