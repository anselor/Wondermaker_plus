# Start-print sequence review — 2026-09-13

This traces the local 1.1.08 candidate through actual sliced-file startup
commands. The correctness fixes below are applied locally. Following review,
first-tool probing became the default and mesh/recovery references were
reconciled; see [print-mesh-recovery.md](print-mesh-recovery.md). Heating,
wiping and cooling sequence optimizations are not implemented or deployed.
No startup timing measurements were taken.

## Sliced-file evidence

Read the first 256 KiB of three files from the printer's Moonraker file API.
Copies are retained under ignored `analysis/start-print-review/*.prefix`.
No printer commands were sent.

| File | START_PRINT arguments | Commands around the macro |
|---|---|---|
| top_bins_Orca_WMZRU_PCTG_3h47m.gcode, line 153 | Nozzle 275°C, bed 80°C, chamber 0, initial tool 0; explicit 4×4 mesh bounds | Before: object definitions, progress, nozzle/auxiliary fans off. After: G90, G21, M83, T0, fans off, extrusion reset/retract and first-layer travel. |
| Articulated_Manta_Black_PLA_11h21m.gcode, line 284 | Nozzle 220°C, bed 55°C, chamber 0, initial tool 0; explicit 6×5 mesh bounds | Same prefix; after the macro also T0 and M109 S220 T0. |
| Cube_PLA_36m1s.gcode, line 220 | Nozzle 220°C, bed 55°C, chamber 0, initial tool 0; explicit 4×4 mesh bounds | Same prefix; after the macro also T0 and M109 S220 T0. |

None of these samples waits for heaters before START_PRINT. Their mesh path
uses explicit bounds/counts, not the separate ADAPTIVE=1 branch. The German
report's M191 S60 before START_PRINT is a different startup example. Current
START_PRINT does not consume CHAMBER; these samples request zero, so they do
not establish behavior for a requested warm chamber.

## Current sequence

Source: `config/live/macros.cfg` START_PRINT; `printer.cfg` homing_override
and Z_HOMING; `change_macros.cfg` tool selection and temperature wait.

| Stage | Work and blocking conditions |
|---|---|
| 1. Initialize | Mark print body not ready, reset motion limits, start bed heating, clear mesh. Temporarily map logical T0 to physical tool 0. |
| 2. Prepare probe temperature | Choose mapped INITIAL_TOOL by default when a fresh mesh is requested; use physical T0 for an explicit opt-out or saved-mesh start. Set that heater to 140°C and wait within 137.5–142.5°C. It may still be docked. Bed heating runs concurrently. |
| 3. Home | Vendor clearance handling, home Y then X, select the probe tool, wipe, move to X150 Y135, home Z and lift to Z7. An actual pickup already wipes in the tool-change success path, so Z_HOMING can wipe a second time. |
| 4. Wait for bed | M190 waits within the requested bed temperature ±1°C. Z homing has already occurred; meshing follows the bed wait. |
| 5. Mesh | Probe the slicer's explicit bounds/counts, native adaptive mesh if requested, or full mesh into a separate per-print profile. If meshing is disabled, load the saved default instead. Snapshot the active mesh as wmp_print and persist it for recovery without replacing default. |
| 6. Select first print tool | Switch off the probe heater target, restore logical T0 mapping, select INITIAL_TOOL. Selection applies offsets, flow and pressure advance and waits for the tool's existing target. A real change also docks/picks up and wipes. |
| 7. Heat and purge | Clear XYZ offsets for the purge, move to Z7 / X0 Y70, then set and wait for the final nozzle target. Purge along the left edge from Y100 to Y150 at Z0.4, then lift/move diagonally. |
| 8. Restore tool setup | Call T{INITIAL_TOOL} again, restoring offsets cleared for the purge and repeating setup/checks/temperature wait. Commit the file/probing-tool/calibration context for recovery, then mark the print body ready. |
| 9. Slicer continuation | Samples issue another T0; two also repeat M109. Continue into prime tower/skirt/model paths according to the file. Same-tool calls do not dock again, but still perform setup and checks. |

The bed and probing-temperature heater already heat in parallel. The main
late heat ramp is from the probing temperature to the final print target.
An additional tool's existing high target can also cause an earlier wait in
stage 6, before START_PRINT assigns its intended final target.

## Optimization candidates, in order

1. **Assign final print temperature earlier.** If the first print tool is
   also the probe tool, retain 140°C through meshing, then set its final
   target immediately after the mesh and overlap heating with subsequent
   motion. Avoid the intervening target-off command. If it is another tool,
   preheating during bed wait/meshing could overlap more work, with docked
   ooze and a subsequent wipe accounted for. Resolve logical-to-physical
   mapping explicitly and avoid waiting for a stale target during pickup.

2. **Give one startup step responsibility for wiping.** Remove the duplicate
   wipe when Z_HOMING actually changes tools, while retaining a wipe when
   the required tool was already attached. Preserve nozzle preparation
   before contact probing. The final T call cannot simply be deleted:
   its offset restoration is required after the purge's zero-offset move.
   A dedicated post-purge setup could avoid repeating the entire selection
   path. The slicer's additional T/M109 calls offer smaller savings because
   the selected nozzle should already be at temperature.

3. **Assist an actual pre-probe cooldown at the side fan.** For an already
   homed machine with the chosen probe tool attached, move to the midpoint
   between purge and wiper (default X-13 Y160), assist cooling to the same
   140°C band, restore fan speed, then wipe and probe. The existing helper
   excludes printing, and START_PRINT already has that state; add explicit
   startup scope rather than opening the helper to arbitrary print moves.
   Tool pickup's internal temperature wait must also be coordinated so it
   cannot block before reaching the fan. An unhomed start requires separate
   clearance/homing design; vendor SET_KINEMATIC_POSITION in z_rise is not
   evidence of a measured Z position. Do not home Z hot merely to reach the
   fan. The current stationary wait remains until that case is resolved.

4. **First-tool probing is now enabled by default.** The user confirmed
   successful testing by themselves and others after this review. It can
   avoid visiting T0 when another tool will print first, saving up to two
   swaps depending on the initially attached tool. It offers no such
   advantage when the sampled logical initial tool 0 maps to physical T0. Keep saved-mesh datum
   compatibility and tool-specific probing offsets in the validation scope.

5. **Retain mesh persistence for power-loss recovery.** The subsequent review
   established that the touchscreen reloads a saved mesh after re-homing.
   Per-print meshes now use wmp_print; the default calibration remains
   separate. SAVE_CONFIG_NO_RESTART still rewrites configuration and creates
   a backup each time, including for a saved-default start's recovery copy.
   Removing duplicate bed-target commands is minor cleanup, not a major
   time saving.

6. **Review the post-wipe travel speed before Z homing.** During the
   two-color cube validation on September 13, the user reported slow XY
   movement and confirmed it was the startup trip from the wiper toward
   the bed center. Z_HOMING explicitly commands `G1 X150 Y135 F3000`
   (50 mm/s), unchanged from stock 1.1.04 and 1.1.08; the wipe uses
   200 mm/s. The live speed override was 100%. This move precedes Z
   homing, so assess its clearance conditions before increasing speed.
   It is separate from the 200 mm/s return after an in-print tool change.
   No motion settings were changed during this validation print.

An optimized sequence would start bed/probe heating together, establish
safe homing and tool attachment, assist cooling when applicable, wipe once,
home Z, wait for the bed and mesh, start final nozzle heating immediately,
finish tool setup/travel, wait and purge, then restore offsets and continue.
Separate phase macros should evaluate live state after preceding actions;
a single Jinja template sees the state from before its generated commands
execute.

## Correctness fixes applied during review

- Cast `params.ADAPTIVE` to int before comparing with 1. Klipper supplies
  string parameters; the previous comparison silently chose a full mesh
  for ADAPTIVE=1. Explicit slicer bounds in the sampled files are unaffected.
- Require START_PRINT.print_body_ready before capturing an in-print XY
  return. print_stats already says printing during startup; without this
  gate, a post-mesh toolchange could return to the last mesh point.

Validation: **79 offline tests passed**, including regression cases for
string ADAPTIVE=1/0 and a startup toolchange that must not return to the last
mesh point. Hardware contacts and thermal behavior remain outside the
offline motion model. Compare phase timestamps on a normal cold start and
an already-homed warm restart when implementing performance changes; no
speedup in seconds is claimed here.
