# Standalone physical Take / Dock

Source audit: 2026-10-31. This is the implementation contract for the native
Toolhead screen's remaining physical-head controls. The standalone load/unload
service now implements guarded docking and mounting as described in
[standalone filament management](standalone-filament-management.md). Physical
qualification remains outstanding. Separate Take / Dock controls are now connected
through `WMP_TOOLHEAD_ACTION`; see the current implementation and acceptance
status in [standalone completion](standalone-completion.md). The design below
records the original contract and is not evidence of hardware qualification.

## Why the stock wrappers are insufficient

The current `config/live/change_macros.cfg` contains these behaviors:

| Entry / stage | Behavior relevant to a manual control |
|---|---|
| `_CHANGING_TOOL` | Establishes bottom Z if the recovery reference is invalid; homes XY if unhomed or retrying, even before the same-head branch. |
| `_UNLOCK_TOOL` | Can home XY; clears XYZ offsets with `MOVE=1`; travels through Y270/Y310 to saved dock coordinates; seats and releases the head. |
| `PARK_CURRENT_TOOL` | Clears the existing failure flag, attempts release, then calls a retry that can home XY and try again. |
| `_LOCK_TOOL` | Can home XY; clears XYZ offsets with `MOVE=1`; approaches the dock, locks, leaves the dock and checks tool order. |
| `LOCK` | Homes the coupling stepper and permits four additional lock attempts. This is distinct from homing Cartesian axes. |
| `_LOCK_TOOL_FINISH` | On failed lock evidence, calls `UNLOCK`; continuing away from the dock is therefore a separate failure-state decision. |
| `_CHECK_CHANGE_TOOL` | Can clear a failure and repeat the change; its success branch saves current head, applies offsets with motion, restores flow, enables the filament sensor, activates the extruder and sets PA to 0.04. It may wait for temperature during a print and wipe after changing heads. |
| `_check_current_extruder_value` | Can infer and rewrite current head from hall/dock readings. This is not a substitute for rejecting contradictory attachment evidence. |

Calling a stock wrapper after checking `homed_axes` does not exclude retries,
offset-induced travel, wiping, or material-setting changes. The native control
must not use a logical `T<n>` command as a physical-head command. Under openACE
that namespace also owns filament selection.

## User-visible contract

- Browsing a head tab does not take a head.
- **Take head** selects the named physical head. If a different head is mounted,
  the reviewed procedure explicitly includes returning that head first.
- **Dock head** returns the selected head only if that exact head is mounted.
  Selecting another tab must not silently dock whichever head happens to be on
  the carriage.
- Taking the already mounted head, or docking an already docked head, reports
  that state without homing or movement.
- The procedure review names the head(s), Z clearance, dock travel, coupling
  action, and final parked position. It does not imply that filament is loaded
  or unloaded.
- Unhomed axes, invalid physical Z reference, contradictory attachment evidence,
  an active/paused print, or an unresolved operation prevent Begin. A separate
  explicit homing flow is required; Take/Dock must not invoke it implicitly.
- No automatic Cartesian homing, XY retry, extrusion, temperature change,
  temperature wait, wipe, or print resume is part of these controls.

## Backend requirements

The backend needs a dedicated operation, rather than a sequence assembled by
the screen. The screen passes physical head, intent, request ID, session, and a
review token. The token binds the complete plan and calibration inputs. It must
be recomputed against fresh state before execution; delivery is one-shot.

Admission must establish all of the following:

1. openACE is definitively absent. An ACE-aware physical operation requires its
   own ownership contract; this standalone implementation must not bypass it.
2. Print state is idle, the pause flag is false, virtual SD is inactive and the
   request is not executing from an SD file. No unresolved motion operation is
   present. A single apparently idle status field is insufficient.
3. XYZ are homed and `wmp_recovery.z_reference_valid` is true. The current
   position and axis bounds are finite and consistent.
4. The requested head is installed. For a mounted head, attachment agrees across
   saved current head, hall value, lock sensor, dock sensor and active extruder.
   An empty carriage may retain the previous active extruder; that is not a
   contradiction. An already-docked no-op also requires positive occupancy of
   the requested dock, not merely an empty carriage. Unknown or inconsistent
   evidence produces refusal, not an inferred correction.
5. Saved dock positions, offsets and relevant machine geometry are present,
   finite and in range. Do not assume a four-head default calibration or use
   nominal coordinates in place of this printer's calibration.
6. The full carriage path, offset transitions and final clearance position fit
   the physical limits. A fixed 2 mm lift is not object clearance. Idle does not
   prove that the plate is empty after a completed print. The reviewed operation
   needs an explicit clearance policy before it can be enabled.

Motion must be staged with fresh sensor checks between physical phases:

1. Establish the reviewed Z clearance without reducing it during XY travel.
2. Approach the currently mounted head's dock, if a return is needed.
3. Verify seating, release, then verify empty carriage and dock occupancy before
   beginning a pickup. Failure stops the procedure at the current stage.
4. Approach the requested dock and verify seating before coupling.
5. Verify coupling before departing; verify target dock becomes empty after
   departure. Do not continue the normal departure path after an unconfirmed lock.
6. Commit physical-head bookkeeping only after matching physical evidence.
   Preserve calibrated offset semantics and activate the physical extruder and
   appropriate sensor without silently replacing pressure advance or unrelated
   material settings. Define how stored per-head flow is applied explicitly.
7. Remain at the reviewed final position and clearance. Do not return to an old
   print XY/Z or lower the bed clearance automatically.

Use phase-specific raw sensor predicates for seating, coupling, release and dock
occupancy. `wm_material._attachment()` is a settled-state predicate: it also
requires saved current head and active-extruder agreement, and the mounted head's
dock to be empty. It cannot verify coupling while still seated in the dock or
before bookkeeping is committed. Changing bookkeeping early just to satisfy
that helper would make the evidence circular.

Preserving G-code modes/feedrate must not restore obsolete physical-head offsets
or issue return motion. The implementation must account for the vendor's actual
G-code state restoration, rather than assuming upstream Klipper semantics.

On any partial failure retain stage, head and sensor evidence. Do not erase a
failure flag to make a retry appear successful. A lost response reconciles with
the original receipt and attachment evidence; it never repeats the move. A UI
Stop button must not promise interruption of an already queued motion sequence
unless the backend implements that operation.

## Decisions still required

- **Clearance:** use verified object-aware clearance when available; otherwise
  require an explicit clear-bed condition or a reviewed move to a known safe Z.
  Neither is currently established by the standalone UI.
- **Coupling retries:** distinguish intentional coupling-stepper homing from
  XY homing, and decide whether bounded coupling adjustment is part of the
  reviewed operation. Do not inherit four stock retries accidentally.
- **Per-head flow:** determine whether manual Take applies the stored head flow
  or preserves the current multiplier; display/document that choice. PA should
  not be reset to the stock hardcoded 0.04 by a physical pickup.

## Acceptance evidence required

Host tests must cover same-head no-ops; wrong selected head on Dock; state/session
changes after review; missing/contradictory sensors; invalid or changed dock
calibration; axis/offset limits; insufficient clearance; every failure stage;
lost delivery and duplicate requests. Recorded command traces must demonstrate
the absence of Cartesian homing, extrusion, heater changes, wipe and resume.

Native tests must cover the exact review, refusal, busy, partial/unknown and
completion flows, including switching head tabs while an operation is pending.
Attended printer qualification must then verify the carriage path, attachment
sensors, coupling, final offsets and subsequent physical extrusion on each head.
Compiling the UI or passing a mocked command trace does not provide that evidence.

Independent source review confirmed the macro audit and identified the
phase-specific evidence requirement above. This is source-level agreement on the
contract, not approval of an implemented motion procedure.
