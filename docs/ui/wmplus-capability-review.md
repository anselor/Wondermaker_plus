# Independent WM+ capability and workflow gap review

Reviewed 30 October 2026. This is a read-only source and design audit. No printer
connection, native activation, motion or hardware acceptance was performed.

## Decision and evidence boundaries

WM+ has useful native infrastructure and narrow typed openACE adapters already.
The proposed consolidated screens are still HTML mockups. Implement the shared
shell, source/head model and supported adapters now, but do not treat all proposed
operator workflows as ready to enable.

This review independently agrees with [the workflow review](workflow-review.md)
and [the openACE capability review](openace-capability-review.md). The latter
correctly distinguishes missing openACE capabilities from capabilities already
present but not yet integrated by WM+. Existing narrow adapters can be developed
alongside the foundation; the decision is not to postpone all meaningful work.

The current repository native package and a previously installed artifact are
not interchangeable evidence. [Native packaging](../native-screen-packaging.md)
records exact source/artifact binding, target dependency verification and native
acceptance limitations. Reading those sources does not establish which bytes or
widgets are currently active. This audit does not independently verify an
installed artifact or its physical behavior.

## Existing WM+ implementation versus missing work

Paths below are relative to
`client-preload/openace-compat/screen1113/source/client/` unless stated otherwise.

| Area | Implemented WM+ source | WM+ gap | Backend or shared dependency |
|---|---|---|---|
| Native foundation | `native_bootstrap.cpp`, `native1113_port.hpp`, `native1113_windows.hpp`, `native_renderer.hpp`, `native_management.hpp` provide native lifecycle/rendering integration. `main_layout.hpp` validates native protected regions. | Consolidated Home entry points, retained Settings shell, head tabs, grouped sources, editors, popup navigation and touch keyboards. | Native widget/touch/modal/Stop acceptance on exact supported client; no backend feature needed to begin read-only layouts. |
| Status and delivery | `worker_bridge.hpp` polls bounded object replies; current/session checks precede command delivery. Outcomes distinguish NotSent, Replied and Unknown. Completion explicitly means delivery, not physical completion. | One shared presentation model for heads, configured sources, loaded evidence, routes, drafts, operations and job state; preserve it across views. | Agree consumed projection version/freshness and capability semantics with openACE. |
| Discovery/adoption | Management query includes discovery, units and settings. Typed `unit_add`/`unit_accept` commands use expected context and stable identity. | Home alert, multiple-candidate Adopt flow, naming, pending/refusal/unknown/readback and return to unassigned unit details. | Discovery/add/accept exist in openACE; replacement acceptance is distinct from adoption. |
| Rename and simple topology | `management_commands.hpp` supports `unit_rename`, `map_tool`, `unmap_tool`; worker admits only a fixed action vocabulary. | Isolated draft with baseline revision, slot picker, quick-fill, Save/discard on every navigation path, save outcome/readback. | Four-slot atomic batch or explicit partial-result contract, alias preservation and allocation policy remain shared work. |
| Cascade Remove | Native adapter supports existing `unit_remove`. | Confirmation, active/paused/busy refusal presentation, affected-route preview and stale preview invalidation. | Requested delete-associated-tools plus renumber is not the semantics of the existing backend REMOVE. Requires backend transaction. |
| Identity editing | `management_commands.hpp:128–146` addresses head or slot and preserves untouched metadata. Current editable keys are `material`, `nozzle_temp`, `color`; vendor/line values are copied from readback. | Brand editing needs typed adapter extension. Simple palette must preserve custom imported colours. Correctly distinguish configured identity from loaded identity. | Basic openACE identity support exists. Catalogue/default/precedence and unknown-temperature policies need agreement. |
| Paused direct loading | `manual_flow.hpp` validates available manual scope/context and integer procedures; prepare/plan/done derive requests from current backend state. Pending ticket, session and scope changes are tracked. | Reuse this discipline in consolidated recovery and origin-preserving progress views; do not replace it with generic Load/Prime widgets. | Backend paused/direct flow exists. Generic arbitrary-head idle Load and source-selection contract is broader than this native adapter. |
| Material confirmation | `openace_view.hpp` and `native_management.hpp` send context-bound `OPENACE_CONFIRM_CHANGE`; current snapshot controls availability. | Integrate into the reviewed recovery path and return to the same required tool/source context. | Existing backend context and obligations must remain authoritative. |
| Generic Load/Unload | Existing WM config and openACE wrappers provide procedures, but the proposed unified head-card workflow is not implemented by these native panels. | Resolve loaded source for Unload; select eligible source for ambiguous Load; keep operation origin and partial/unknown result. | openACE source selection, direct Load and Unload exist; suitable admission/result contracts must be agreed, not invented in the frontend. |
| Direct Extrude/Retract | Mockup uses a timer and spinner only. Narrow native manual prepare/plan/done is not a generic distance operation API. | Dispatch and busy/failure/unknown state on original head; prevent conflicting operations, preserve navigation without losing operation context. | Exact-distance signed extrusion contract is missing/shared. Feeder retract, vendor purge and full unload are not substitutes. |
| Physical temperature / Take / Dock | Physical macros and heater addressing exist elsewhere in WM+. Existing native management vocabulary does not implement the proposed head-control flow. | Distinct Take and Dock actions, physical head targeting, mounted state and heater result/status. | Owner/job admission and operation completion semantics; virtual T must not be mistaken for physical heater index. |
| Preview / print start | Existing client integration and backend map submission are not a complete implementation of these new preview widgets. | Real metadata/thumbnail, source selector, authoritative T labels, compatibility reasons, stale-map validation, submission and accepted/refused/unknown transitions. | Frozen-map backend exists. Agree authoritative destination/compatibility projection and revision-bound submit handshake. |
| Profile import | No corresponding native profile importer in reviewed vocabulary. Mock USB action is informational. | USB file selection, parse/conflict review, import progress/errors, editor-choice refresh and command upload integration. | New versioned JSON/ZIP format, importer, catalogue persistence and upload contract. Existing AFC lane edits are not profile import. |
| Standalone WM+ | Stock configuration and client workflows remain, but consolidated read/write screens cannot assume openACE APIs. | A WM+-owned adapter for identity, physical actions, loaded/unknown state, progress and print mapping. Share widgets while switching explicit capabilities. | This is primarily WM+ work. Backend absence is different from openACE unavailable/unknown; never fall through on transient loss. |

## Concrete mockup defects to resolve before using it as a specification

All references below are in `docs/ui/mockups.js`; these are offline-model defects,
not evidence that an installed native implementation has these defects.

1. **Identity aliasing:** `initial`, `unitSlots`, `tools`, `externalBox` and
   `save-simple-slot` share `state.slots` for ACE 1, per-head identity and External.
   A head edit can change an unrelated ACE slot. Separate the domain records.
2. **Draft leakage:** `assign-head`, quick-fill and rename mutate live objects.
   Back has a limited rollback, while sidebar navigation bypasses it. Unit 3
   rollback uses unit 2 fields. Explicit save boundaries need real isolation.
3. **Routing synthesis:** `choose-source` derives T numbers from display order,
   includes unassigned slots and counts ACE entries even in standalone mode.
   Store backend source/tool IDs and revisions, not generated labels.
4. **Stale preview:** selected entries copy colour/label/head. Later identity or
   route changes can leave them stale. Revalidate the complete map before Start.
5. **Load ambiguity:** a multi-source head has no Load source chooser. Review
   displays an invented generic procedure instead of a named current source.
6. **Lost operation origin:** load/unload review and progress return to Filaments
   regardless of origin. Recovery operations must return to their frozen context.
7. **Partial result action:** progress “Review remaining” dispatches generic
   Extrude, now a direct action. Partial Load/Unload/Prime must expose only the
   backend-permitted continuation, never a guessed generic motion.
8. **Incomplete recovery:** fixed T4/head4 identity, simultaneous phase buttons,
   render-time pause mutation, confirmation that only dismisses a dialog and
   Resume that always reports held do not form a complete recovery state machine.
9. **Incomplete lifecycle:** boolean discovery, fixed adoption ID, no registered
   disconnect/replacement/conflict states, and counts separate from actual units.
10. **Incomplete outcomes:** fixed busy timer, canned partial progress, no working
    Start submission, no real Take/Dock action and import placeholder. These must
    remain visibly illustrative until complete state transitions exist.

## Required acceptance paths

For each slice cover successful completion, refusal, stale snapshot, lost reply,
unknown/partial outcome, repeated taps, navigation away/back and owner changes.
Use standalone, openACE with zero units, multiple units, disconnected sources and
active/paused job fixtures. Specifically verify:

- Editing an ACE slot never changes another slot, External identity or loaded
  evidence; editing a loaded identity has an explicit backend meaning.
- Unit draft cancel discards on all exits; Save has current revision/readback.
- One-to-many head routing requires explicit Load source selection.
- Direct manual motion needs no review dialog, but its busy/result state follows
  the original operation and never disappears merely because of elapsed time.
- Partial/unknown operation cannot replay the full original physical request.
- Preview selections remain bound to stable source/tool identities and fail
  revalidation after relevant topology changes.
- Recovery returns to the same frozen job/tool/source and retains prior prime
  receipts when a later readiness check refuses Resume.
- Removing a unit is blocked while active/paused or otherwise backend-ineligible;
  successful cascade returns the old/new tool map and invalidates stale selections.

## Consensus and implementation sequence

The independent workflow, UX and backend conclusions are compatible:

1. Begin native shell/navigation, shared domain model, read-only projections,
   capability adapters and reusable touch/input components now.
2. Implement already-supported typed discovery/rename/identity adapters as
   complete small journeys with context, draft and readback handling.
3. Agree missing shared action/progress and routing contracts before enabling
   generic Load/Unload, direct extrusion, Take/Dock, preview/start or recovery.
4. Treat cascading removal/renumber and profile import as backend features plus
   UI integration, not frontend-only tasks.
5. Build and qualify the standalone WM+ adapter explicitly. openACE functionality
   does not eliminate this responsibility.
6. Preserve existing session/delivery protections and exact native package
   provenance; perform native and hardware acceptance separately from HTML checks.

There is enough in place to start a scoped implementation program. There is not
sufficient definition or backend coverage to implement and enable every proposed
screen/action as one finished release.
