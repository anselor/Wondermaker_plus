# openACE external-head unload integration

**Deferred to the subsequent openACE-support release; not an initial standalone-release blocker.**

R21 remains incomplete for an externally fed head while openACE owns filament
management. Standalone WM+ unload is implemented; this dependency must not be
reported as a missing standalone feature or as completed merely because an older
owner refuses the operation.

## Source findings, 12 November 2026

Read-only inspection of the current sibling openACE worktree found:

- `klipper/extras/openace.py::_register_commands` registers
  `OPENACE_LOAD_DIRECT`, but no direct-unload command.
- `cmd_UNLOAD` calls `_unload_head_command`, which requires a coordinator and
  routing instance, then calls `routing.unload`.
- `klipper/extras/openace_runtime.py::unload` calls
  `coordinator.unload_head`.
- `openace/coordinator/unload_only.py::UnloadOnlyMixin.unload_head` explicitly
  rejects a loaded direct destination before physical work.
- WM+ `WMMaterial._openace_unload_plan` therefore refuses direct unload before
  dispatch. Removing that refusal alone cannot implement the requested behavior.

The sibling worktree is another effort's working source, not a released or
installed compatibility guarantee. No openACE files or printer configuration
were changed during this inspection.

## Required owner behavior

The existing public unload command may be extended, or a separate direct-unload
command supplied. WM+ needs an explicit advertised capability/protocol, not a
version-name guess or optimistic command submission.

The owner must accept an explicit physical head and retain ownership throughout
mounting, positioning, heating, tip shaping/retraction and completion. It must
support a direct-only head without requiring a connected ACE unit. A direct
unload must never issue ACE feeder/assist motion or reinterpret the physical head
as a virtual tool. Use the same source/session/operation admission and durable
physical-action accounting as other owner operations.

Required UI-visible outcomes:

1. Named stages for mount/position, heat, retract, and remove filament; actual and
   target temperatures during heating.
2. Separate completion of extrusion retraction from inlet sensor clearance.
   Once unloading completes, clear the loaded flag even if the inlet still sees
   a loose strand, and show “Filament unloaded. Please remove filament.” Sensor
   clearance settles removal; sensor presence alone must not reassert loaded.
3. An explicit STOP and terminal result bound to the operation, with unresolved
   motion or persistence failures retaining the owner's recovery hold. Status
   polling and reconnect must not repeat motion or implicitly resume a print.
4. No Z homing for filament service. Respect an existing paused print and its
   position/material-change context; head selection, necessary XY homing and
   purge-area travel belong to the owner. Completion must not resume printing.
5. Durable identity and outcome reporting usable by WM+ after client/backend
   restart. A successful command acknowledgement alone is insufficient evidence
   of completed unload or filament removal.

## WM+ work after the owner contract exists

Add capability-gated direct-unload plan construction, bind the owner session and
loaded source, dispatch through that public owner API, and map owner stages and
result to the existing numbered service screen. Keep older-owner refusal until
support is advertised. Do not run the standalone motion path under openACE.

Acceptance must cover direct-only and mixed ACE/external configurations, successful
unload/removal, cancellation, stale owner/session, disconnect, lost acknowledgement,
and restart with an unresolved result. Confirm no ACE feeder movement for the
direct source, no automatic resume, and no lost filament identity. Qualify only
these changed owner interactions; do not repeat unrelated stock UI behavior.
