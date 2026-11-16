# Filament command side-effect audit

## 31 October collision handoff and local correction

The subsequent openACE `wmplus-extrude-review/README.md` handoff correlates the
public `EXTRUDE_FILAMENT T=1` request with a temporarily configured 20 mm feed,
followed by docking failure and `PARK_CURRENT_TOOL_RETRY` issuing `G28 X Y`.
The operator reported front-wall contact. The macro returned `ok` despite two
docking failures; emergency shutdown followed. This supersedes the uncertainty
about that branch in the original audit below; it does not establish a pickup.

The local WM+ override now removes only EXTRUDE_FILAMENT's final
`PARK_CURRENT_TOOL`, leaving the head mounted for standalone and openACE users.
Service travel, extrusion, cooling and wipe remain. This is not an E-only API:
WIPE_NOZZLE's conditional homing and other callers' docking retries remain open
issues, as do physical-head admission and explicit purge-length handling.
The native standalone manual-step controls use WMP_EXTRUDER_STEP instead.

Regression tests render the actual macro routes for known XYZ in idle/paused
states with and without openACE, and refusal with incomplete XYZ. They are not
physical trajectory tests. This correction is local and not installed. The
handoff requires physical inspection and fresh operator approval before any
installation or restart; it does not authorize resuming the affected print.

## Original audit (before the correlated handoff)

30 October 2026. Repository source review following a reported wall contact when
requesting 20 mm extrusion. No printer commands, deployment or restart performed.
The incident's exact submitted command, installed macro expansion and log timeline
have not been correlated. Findings below describe current `config/live` sources,
not independently captured installed behavior.

## Confirmed chain

`EXTRUDE_FILAMENT` in `config/live/macros.cfg` is a service purge:

1. `_WMP_FILAMENT_SERVICE_POSITION` refuses active printing or unhomed XYZ, raises
   Z by up to 5 mm within the configured limit, moves X=-13 then Y=80.
2. Conditional heat, fan off, relative E mode, E origin reset.
3. Extrudes macro variable `extrude_length` (default 100 mm) at F400. It does not
   read a distance parameter such as LENGTH=20. A caller could separately change
   that variable; we have not established what the incident caller submitted.
4. Fan on, wait for 160°C, fan off, wipe.
5. `PARK_CURRENT_TOOL` calls `_UNLOCK_TOOL` to return/release the mounted head.
   This is docking, not merely moving to a service location.
6. `_UNLOCK_TOOL` can home XY if its homing prerequisite is absent;
   `PARK_CURRENT_TOOL_RETRY` explicitly homes XY when `fail_flag != 0`.

The sibling openACE `_purge_head_command` runs the previous vendor macro under
feed assist, after verified-load/operation admission. It does not remove those
macro side effects. Thus openACE guarding a purge does not make it E-only.

The pickup portion of the reported dock→pickup→home sequence and the cause of
wall contact remain unproven. `_CHANGING_TOOL` homes XY if unhomed **or retry=1**,
and may bottom-home Z if its reference is invalid. A subsequent reselection can
therefore add movement, but incident logs are needed to identify the actual path.

## Other commands requiring explicit intent boundaries

| Command/path | Existing effect | Required treatment |
|---|---|---|
| EXTRUDE_FILAMENT | Service travel, long purge, cooling, wipe, docking | Never use for direct distance extrusion. Separate manual E step from explicit purge/finish/dock workflow; audit callers before changing legacy semantics. |
| RETRACT_FILAMENT | Service travel, material tip shaping/extraction, heater/fan changes, wipe | It is unload preparation, not a small negative E jog. |
| LOAD_FILAMENT / UNLOAD_FILAMENT | Physical extruder activation, heating, long feed or tip shaping, heater off, stepper disable | Explicit workflows; activation alone does not prove the corresponding physical head is mounted. |
| PARK_CURRENT_TOOL | Dock/unlock and retry | Name is misleading. Keep explicit docking semantics; do not call to request ordinary service-position travel. |
| PARK_CURRENT_TOOL_RETRY | Rehomes XY after failure | Failure invalidates assumptions: report/refuse or invoke an explicitly owned recovery sequence; do not globally bypass this home on homed_axes alone. |
| WIPE_NOZZLE | Conditional XY home, travel and wipe | Require preparation/clearance at the operation boundary; direct extrusion should not call it. |
| _CHANGING_TOOL / _OFFSET_RESET | Homing for missing position or retry; offset application can move | Distinguish already-mounted target with valid position from unknown/failed latch state. Re-evaluate after asynchronous/check submacros. |
| GET_TOOL_POSITION | GET_T_POSITION, unconditional XY home, then X150 Y200 | Not read-only despite its name; callers must treat it as a calibration/motion procedure. |
| G29 / calibration / print startup | Intentional homing/probing/tool preparation | Audit separately. Required calibration and startup moves cannot be removed solely because axes were previously homed. |
| Client runout callbacks | Independently submitted heat/home/purge sequences | Macro cleanup alone does not cover these. Preserve the separately reviewed callback ownership guards. |

## WM+ policy and implementation boundary

- A manual signed E step targets an already mounted physical head at an admitted
  temperature. It changes E only, preserves caller G-code modes/feedrate, and
  does not heat, home, pick up, dock, wipe, change fan or reset a print context as
  an unannounced side effect. It may refuse if prerequisites are not satisfied.
- With openACE present, use its agreed operation/assist/loaded-source ownership.
  Do not bypass it with a raw macro to get a quick fix. Standalone WM+ needs its
  own equivalent physical-head admission and progress reporting.
- Service purge, load, unload, wipe, pickup, dock, home and recovery remain distinct
  intents. Preparation is performed only where the requested intent needs it.
- Skip pickup/docking only when mounted-head/latch evidence actually establishes
  the desired state. Skip homing only with valid axis/reference evidence and no
  failure condition requiring recovery. Saved `current_extruder` and homed axes
  alone are not universal proof after a failed exchange or collision.
- No global G28/G1 filter. No unconditional replacement of all command bodies.
  Preserve stock snapshots; place reviewed behavior in WM+ live overrides.
- A real collision can invalidate coordinates even if software still reports
  homed. Do not use this audit to authorize continuation of the affected print.

## Next concrete change set

1. Correlate the incident command/logs and installed macro definitions, including
   any client or wrapper commands before/after the purge. Determine the source of
   pickup and homing, not just the macro containing the docking call.
2. Inventory all callers of the affected public commands; distinguish UI manual
   step, purge/load workflow, print-start and recovery dependencies.
3. Implement the shared signed-E operation contract identified in the UI review,
   with head/temperature/owner admission and operation completion/unknown result.
   Point manual UI controls at it. Do not alias it to EXTRUDE_FILAMENT or
   RETRACT_FILAMENT.
4. Refactor legacy purge finishing into explicit wipe/dock decisions after caller
   review. Audit retry paths as recovery policy, rather than dropping their homes.
5. Verify generated command traces: admitted manual step contains no XYZ move,
   homing, latch change or heater/fan mutation; refusal emits no physical prefix.
   Include mounted/unmounted/wrong-head, valid/invalid position, paused/printing,
   cold/hot, standalone/openACE, and uncertain previous operation cases.
6. Obtain independent review and separately authorized idle hardware acceptance
   before deployment. Keep prior native UI/guard artifact provenance intact.

This audit does not change production macros. The confirmed unnecessary finish
sequence for a *manual extrusion request* is avoided by a correct manual-operation
entry point; changing legacy purge semantics also requires its caller inventory.

## Native standalone controls: additional firmware findings (2026-10-31)

The new GUI must not treat the stock `PARK_CURRENT_TOOL` and `_CHANGE_TOOL`
routines as simple synchronous take/dock operations. `PARK_CURRENT_TOOL_RETRY`
issues `G28 X Y` after a release failure. `_CHECK_CHANGE_TOOL` invokes a second
`_CHANGING_TOOL` attempt with `retry == 1`, which forces XY homing even when the
axes were already homed. Its success branch also restores offsets and flow,
sets pressure advance, waits for temperature and can wipe. Those actions need
an explicit reviewed procedure and trustworthy final state before native
Take/Dock controls can be enabled. The new screen does not dispatch them yet.

The local 1.1.13 `gcode_move.py` also differs from upstream: its
`RESTORE_GCODE_STATE` leaves `base_position` and `homing_position` unrestored.
Temporarily changing M221 for a manual extrusion can therefore leave an E
coordinate discrepancy. `WMP_EXTRUDER_STEP` instead divides its requested E
distance by the current extrusion factor and its feed by the speed override,
leaving both factors unchanged. Tests run the rendered command through the
actual local firmware G-code implementation with non-default overrides and
verify physical E displacement, unchanged XYZ, speed and logical E continuity.

Active extruder selection alone is also insufficient attachment evidence.
The helper and step macro require agreement between the saved physical head,
Hall reading, lock sensor, head dock sensor and active extruder. Sensor evidence
about attachment must not be confused with filament loaded-state evidence.
