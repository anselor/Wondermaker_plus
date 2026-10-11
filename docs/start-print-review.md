# Print-start review: September 13, 2026

Startup already heats the bed and probe nozzle together. The main possible savings
come from starting final nozzle heating sooner and avoiding repeated wiping/setup.
No startup timing measurements were taken, and the proposed heating and wiping
optimizations below were not implemented by this review.

The review fixed two correctness issues: string handling for `ADAPTIVE=1`, and
a startup tool change accidentally returning to a mesh point. First-tool probing
later became enabled by default, and the print's mesh/tool reference was made
persistent for recovery. See [the recovery guide](print-mesh-recovery.md).

## Sampled print files

The first 256 KiB of three sliced files were read from Moonraker without sending
printer commands. Local copies are under `analysis/start-print-review/*.prefix`.

| File | START_PRINT arguments | Commands around the macro |
|---|---|---|
| top_bins_Orca_WMZRU_PCTG_3h47m.gcode, line 153 | Nozzle 275°C, bed 80°C, chamber 0, initial tool 0; explicit 4×4 mesh bounds | Before: object definitions, progress, nozzle/auxiliary fans off. After: G90, G21, M83, T0, fans off, extrusion reset/retract and first-layer travel. |
| Articulated_Manta_Black_PLA_11h21m.gcode, line 284 | Nozzle 220°C, bed 55°C, chamber 0, initial tool 0; explicit 6×5 mesh bounds | Same prefix; after the macro also T0 and M109 S220 T0. |
| Cube_PLA_36m1s.gcode, line 220 | Nozzle 220°C, bed 55°C, chamber 0, initial tool 0; explicit 4×4 mesh bounds | Same prefix; after the macro also T0 and M109 S220 T0. |

None waits for heaters before `START_PRINT`. These samples use explicit mesh bounds,
not `ADAPTIVE=1`, and request zero chamber temperature. They do not show what happens
with a heated-chamber request. Current `START_PRINT` does not consume `CHAMBER`.
An external report using `M191 S60` before startup describes a different sequence.

## Sequence at the time of review

Sources: `live/macros.cfg` START_PRINT, `live/printer.cfg` homing, and
`live/change_macros.cfg` tool selection.

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

The late temperature rise is from probing temperature to print temperature.
Selecting another head can also wait for an earlier high target before startup
sets the intended final target.

## Changes worth measuring

1. **Start final heating after meshing.** Keep a shared probe/print head at 140°C
   until probing finishes, then heat while setup/travel continues. For a different
   print head, earlier heating could overlap more work, but needs a plan for docked
   ooze and wiping. Resolve head mapping explicitly and avoid waiting for a stale
   target during pickup.
2. **Wipe once where preparation requires it.** Actual pickup already wipes;
   `Z_HOMING` can wipe again. Keep a preparation wipe when the head was already
   attached. The post-purge T call restores cleared offsets, so it cannot simply
   be deleted; a dedicated setup command could reduce repeated work.
3. **Treat fan-assisted cooling as an experiment.** The proposed pre-probe detour
   required homed coordinates, startup-specific checks, and coordinated pickup
   temperature waits. Unhomed travel could not rely on synthetic Z coordinates.
   Later auxiliary-fan measurements found no benefit and the detour was removed;
   see [the cooling record](cooling-assist.md).
4. **Use first-tool probing where it avoids swaps.** This was subsequently enabled
   by default after reported tests. It can save up to two swaps depending on the
   initially attached head; samples already starting with physical T0 gain no such
   benefit. Saved-default mesh compatibility still needs the T0 reference.
5. **Keep the recovery mesh snapshot.** It records the exact mesh rather than
   letting recovery load a later default. `SAVE_CONFIG_NO_RESTART` rewrites config
   and creates a backup even for the recovery copy of a saved-default start.
6. **Assess the slow trip before Z homing.** The wiper-to-center move uses
   `G1 X150 Y135 F3000` (50 mm/s), unchanged from stock 1.1.04/1.1.08.
   The user identified it as slow during the two-color trial. Check clearance
   before changing it; it is separate from the 200 mm/s in-print tool return.

A proposed sequence would overlap heating, prepare and wipe the probe head once,
home Z, wait for the bed, mesh, begin final nozzle heating, finish travel/setup,
then wait, purge, and restore offsets. Any implementation should measure normal
cold startup and an already-homed warm restart before claiming a time saving.

Klipper renders a macro before executing its generated commands. Separate phase
macros are needed when later decisions must see state changed by earlier commands.

## Correctness checks

Klipper parameters are strings. Casting `params.ADAPTIVE` to an integer fixes the
comparison with 1, which previously chose a full mesh. Explicit slicer bounds are
unaffected. `START_PRINT.print_body_ready` now prevents print-return capture during
startup, when `print_stats` already says printing.

The recorded review passed 79 offline tests, including both regressions. Hardware
contact and thermal behavior were outside the simulated model. No motion setting
was changed during the validation print, and no speedup in seconds was measured.
