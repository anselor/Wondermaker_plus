# Printer configuration: stock vs live

- **`stock/`** — pristine snapshot of the vendor config, captured after installing touchscreen app **System_1.1.04** (2026-08-19).
  OS/Klipper image `KLP_IMG_WM_ZRU_V1.0.26`. The prior 1.0.71 stock is kept
  as `config/stock_1.0.71/` for before/after diffs; analysis in
  `analysis/fw_1.1.04_diff/`. Re-baseline process is documented there.
  `printer.cfg` is the pre-tuning backup, so the SAVE_CONFIG block holds the
  vendor's own calibration values. Never edit this directory.
- **`live/`** — what runs on the printer. Started as an exact copy of
  `stock/`; every deliberate change is wrapped in markers:

  ```
  # >>> wondermaker+ begin: <change-id> (<origin>)
  # Why: <rationale>
  ...
  # <<< wondermaker+ end: <change-id>
  ```

  See all changes at a glance: `diff -r config/stock config/live`
  Deploy / compare against the printer: `utils/config_sync.py` (below).

Excluded from both (runtime state, not configuration): rotating
`printer-*.cfg` backups, `saved_variables.cfg`, `tmt1.ini`,
on-printer `*.wmp-backup*` files.

## Deploying with config_sync.py

`utils/config_sync.py` moves config between this repo and the printer over
**Moonraker's HTTP API** — no SSH or credentials needed. It works while the
rest of the printer keeps running and only restarts Klipper at the end.

```bash
uv run python utils/config_sync.py diff            # show what differs from the printer
uv run python utils/config_sync.py push            # upload changed files, then restart Klipper
uv run python utils/config_sync.py push macros.cfg # push only the named file(s)
uv run python utils/config_sync.py pull DIR        # download the printer's config to inspect
```

On push it:

- backs up each replaced file on the printer as `<name>.wmp-backup-<timestamp>` first,
- firmware-restarts Klipper and confirms it returns to **Ready** (fails loudly if not),
- refuses to run while a print is in progress,
- accepts `--no-restart` (upload only) and `--ssh` (use SFTP if Moonraker is down).

**Your printer-specific calibration is preserved on every push:**

- **Bed mesh, input shapers, probe offsets** — `printer.cfg`'s SAVE_CONFIG
  block is read live from the printer and spliced back onto the pushed file,
  so it is never overwritten.
- **CAN bus UUIDs** (`wm_zru_*.cfg`) — never pushed.
- **Tool offsets and filament settings** (`saved_variables.cfg`, `tmt1.ini`) —
  never touched.

Target the printer with `WMP_PRINTER` (and `WMP_USER` / `WMP_PASS` for `--ssh`).

## Per-machine calibration is NOT in this repo

So the repo is shareable without pushing one machine's calibration onto
another, `config_sync.py` enforces split ownership:

- **`printer.cfg`**: the repo owns the body (macros, limits, marked edits);
  **the printer owns its SAVE_CONFIG block** (bed mesh, input shaper, probe
  offsets). The repo copies are truncated above the block; `push` splices
  the target printer's own SAVE_CONFIG back on, and `diff` compares bodies
  only. Set your shaper values with `utils/resonance.py apply`.
- **`wm_zru_*.cfg`**: unique per machine (CAN bus UUIDs). Kept here only as
  sanitized reference (`REPLACE_WITH_YOUR_UUID`); never diffed or pushed.
- `saved_variables.cfg` (tool offsets etc.) and `tmt1.ini` are never touched.

Note if publishing: git history from before this sanitization contains one
machine's mesh/UUIDs — start public history from the current tree (squash)
if that matters to you.

Exception to the marker rule: the SAVE_CONFIG block of `printer.cfg` cannot
contain comments (Klipper rewrites it), so SAVE_CONFIG-level changes (like
shaper values) are documented only in this file.

## Current modifications

> **Status after the 1.1.04 re-baseline (2026-08-19).** The entries below
> describe each delta's history. On the current 1.1.04 base:
> **active** — accel-cap, input-shaper values, pause-mapping-snapshot,
> pause-park-margin, left-edge-purge (supersedes purge-approach-margin),
> toolchange-feedrate-preserve, toolchange-wipe, u1-tip-shaping, insert-no-autoload, probe-with-initial-tool (off by default), wm-material-include, wipe-speed +
> wipe-feedrate-restore (merged with the vendor's new `wipe_position`),
> REHOME macro.
> **dropped (vendor fixed it in 1.1.04)** — skip-forced-rehome-on-resume
> (binary-verified: the resume path no longer force-homes; keeping our gate
> would block the wanted recovery re-home); load-auto-wipe (1.1.04 wipes
> after the load purge itself); print-end-rewrite (1.1.04's PRINT_END adds
> Z-safety, wiper-park, and the `print_body_ready` UI contract — taken as-is).
> **deferred** — start-print-chamber (speculative; re-add if printing ABS/ASA).
> See `analysis/fw_1.1.04_diff/MERGE-PLAN.md` for the full rationale.

### probe-with-initial-tool — `live/macros.cfg`, `live/printer.cfg`, `live/change_macros.cfg` (ours, 2026-08-30; design: `docs/design-ideas.md` #1)
**Off by default.** Stock `START_PRINT` always grabs T0 to Z-home and mesh,
cools and parks it, then fetches the print's first tool — two extra
toolchanges and a heat cycle per print. Enable per machine with
`PROBE_WITH_INITIAL_TOOL ENABLE=1` (saved variable, survives restarts;
`ENABLE=0` reverts; no argument reports). When on, `START_PRINT` records
the *physical* tool behind `INITIAL_TOOL` (through `box_modify_t*`) in the
`probe_tool` saved variable, heats that extruder directly, `Z_HOMING` grabs
it (`_CHANGE_TOOL T={probe_tool}`), and `_OFFSET_SET` applies
`offset(tool) − offset(probe_tool)`. `probe_tool = 0` reproduces stock
bit-for-bit (`t0_offset` is `(0,0,0)`); it is forced to 0 when the saved
default mesh is loaded (T0 datum), in `G29`, `PRINT_END`, `CANCEL_PRINT`,
and 2 s after every Klipper start. Known limit: power-loss recovery
re-homes with T0 — mixed datums mid-print; not handled.
Verification plan (from the design note): a supervised first layer on a
print starting on T1–T3, and a control print starting on T0.

### u1-tip-shaping — `live/macros.cfg` (ported from Snapmaker U1 firmware 1.6.0, 2026-08-29)
Stock `RETRACT_FILAMENT` (touchscreen auto-unload) and `UNLOAD_FILAMENT`
(manual unload) leave a blobby, stringy filament end. The Snapmaker U1's
1.6.0 firmware unloads with a purge → fast pull → very slow pull (draws a
thin cone) → re-plunge (rounds the tip) → fast + slow pull → extract
sequence (`CONTROL_RETRACT_ACTION`; full source in
`docs/reference/snapmaker-u1-unload-macros.cfg`). Both macros now call
`_TIP_SHAPE_RETRACT`, which picks one of three U1 variants by material
class — `pla` (PLA/PETG/PA/PC), `abs` (ABS/ASA/HIPS/Wood: slower re-plunge),
`soft` (TPU/TPE: no re-plunge), plus `petg` (PETG/PCTG/PET), which is
*not* U1's: its slow pulls draw PETG into a long cone + 15 mm strand. It is
the Prusa Core One / MK4 MMU3 recipe from `PrusaResearch.ini` (`*PETPG*`):
hard ram (17.5 mm/s — our extruder audibly skips a few steps there, accepted;
the final pull carries 10 mm extra margin so the tip still clears the
gears), one 60 mm/s pull with no slow phase, 3 cooling moves
at 5→2.5 mm/s, then 35 mm "stamping" and a second pull, at **235 °C** — PETG wants
cooler, not hotter: PCTG gave 5 mm of string at 250 and a faint wisp at 235 — and runs the moves via `_TIP_SHAPE_MOVES`.
The final pull is lengthened vs U1 so the net retraction stays at stock's
−57 mm. Hotend temperature is still set by the caller (the touchscreen uses
its material table temp); on top of that `_TIP_SHAPE_RETRACT` raises pla/abs
classes to `unload_temp_min` when set (U1 uses 250 °C for PLA/PETG/ABS; TPU
per U1's table: PLA 250, PETG 270, ABS/ASA/HIPS/PA 280, PC/PET 300, TPU 250
— `variable_unload_temps`; `unload_temp_min` is the floor, 0 disables). After
the moves `RETRACT_FILAMENT` does what
the U1 does next — `M104 S0`, fan 100 %, `post_cool_s` (5 s), then
`WIPE_NOZZLE` to snap the cooled hair off the nozzle. Tested: PLA 220 °C
left a 2–3 mm wisp, 250 °C + cool/wipe none; PCTG (as PETG) strung
badly at 250 and 270 with the U1 recipe → the Prusa-style `petg` class, and 235 °C. The unload purge happens
at `X-13 Y80`, the same side spot `EXTRUDE_FILAMENT` uses (stock unloaded
over the wiper at Y232). `_TIP_SHAPE_RETRACT DRY_RUN=1` reports the class it would
use without moving; `MATERIAL=ABS` / `CLASS=soft` override detection.

**Material detection.** The touchscreen never passes the material to the
macro (binary-verified: `auto_fila_out()` heats to its material table
temp, then runs bare `RETRACT_FILAMENT`). Two sources, in order:

1. **`wm_material` Klipper extra** (optional, `klipper_extras/`, installed
   with `uv run --with paramiko python tools/deploy_material.py install`) —
   reads the touchscreen's `tmt1.ini` (`[slot] material0..3`) and exposes
   `printer.wm_material.material0..3` (names from the binary's 18-entry
   table). `WM_MATERIAL_STATUS` prints them. The slot is resolved from the
   physical extruder through the `box_modify_t*` mapping.
2. **Temperature fallback** when the module is absent: the target the
   touchscreen just set — 230 ⇒ soft (TPU/TPE), ≥255 ⇒ abs (ASA, but also
   PA/PC), else pla. PETG vs ABS (both 250) is indistinguishable and
   defaults to pla.

### insert-no-autoload — `live/extruder0-3.cfg` (ours, 2026-08-30)
Each tool's filament-sensor `insert_gcode` ran a full auto-load (pick tool,
purge, wipe, dock). `_ENABLE_SENSOR` enables only the active tool's sensor,
so in practice it fired during the touchscreen's Load flow, which then ran
its own `EXTRUDE_FILAMENT` — purge, dock, undock, purge, dock. (A first
attempt gated on "extruder already heating" failed when filament is
inserted before pressing Load.) The sensor gcode now only prints a hint and
cancels the runout pause; the screen's Load is the single load path.

### wm-material-include — `live/printer.cfg` (ours, 2026-08-29)
`[include wm_material*.cfg]` after `macros.cfg`. Klipper's glob include
matches nothing when the optional module's cfg is not installed, so the
same `printer.cfg` works with or without it.

### pause-mapping-snapshot — `live/macros.cfg` (ours, 2026-08-17)
Stock `PAUSE` resets the logical→physical tool mapping (`box_modify_t0..3`)
to identity without saving it, and stock `RESUME` restores the mapping from
`box_modify_t*_backup` — variables that only the touchscreen UI binary ever
writes, at unrelated times. Resuming from Fluidd/Moonraker after a filament
runout therefore applied a stale (observed: invalid `0,3,0,3`) mapping and
loaded the wrong physical tool mid-print. The fix snapshots the live mapping
into the backups inside `PAUSE`, before the reset. The touchscreen's
deliberate spool-remap-while-paused flow still works: the UI overwrites the
backups after our snapshot.

### accel-cap — `live/printer.cfg` (ours, 2026-08-16)
`max_accel` 20000 → 5000. Resonance measurements (see
`resonance/2026-08-15/`, tooling in `utils/resonance.py`) show every viable
input shaper on this machine supports at most ~2600–4400 mm/s²; at 20000
visible ringing is guaranteed. Keep slicer wall accelerations ≤ ~2600.

### input shaper values — `live/printer.cfg` SAVE_CONFIG block (ours, 2026-08-16)
X `3hump_ei @ 50.6` → `2hump_ei @ 48.6` (0.4% residual), Y `mzv @ 38.2` →
`ei @ 48.6` (0.1% residual). Measured after equalizing belt tension
(41.8/40.2 Hz) and fixing an idler rattle. **Do not run the vendor's
built-in resonance calibration** — it overwrites these values. Re-tune with
`utils/resonance.py` instead.

### start-print-chamber / -heat / -wait — `live/macros.cfg` (imported from [WonderMaker-ZR-Ultra-S-Mods](https://github.com/…/WonderMaker-ZR-Ultra-S-Mods))
Stock `START_PRINT` ignores the `CHAMBER` parameter OrcaSlicer sends, so the
chamber heater never runs. Adds: parse `CHAMBER`, start the chamber heater
in parallel with bed heating (explicitly 0 when unused), and wait for
chamber temperature after the bed reaches target. Imported as three minimal
marked insertions rather than the mods repo's full START_PRINT rewrite.

### print-end-rewrite — `live/macros.cfg` (imported from WonderMaker-ZR-Ultra-S-Mods, adapted)
Stock `PRINT_END` can execute twice (slicer end-gcode + vendor UI) and moves
without checking which tool is physically attached or whether axes are
homed — it can crash the carriage into a docked tool. The imported version
adds a duplicate-call guard (`already_ran`, re-armed by START_PRINT),
detects the physically attached tool via `_check_current_extruder_value`,
parks it with `PARK_CURRENT_TOOL`, skips motion on unhomed axes, and runs
`M84` last (it clears Klipper's homed state). Deviation from the mods repo:
we kept stock's `SDCARD_RESET_FILE` call, which their version dropped
without explanation.

### toolchange-wipe — `live/change_macros.cfg` (imported from WonderMaker-ZR-Ultra-S-Mods)
After a successful T0–T3 toolchange, wipe the freshly picked-up nozzle
(it oozed while parked) before returning control to the slicer.

### skip-forced-rehome-on-resume — `live/printer.cfg` homing_override (ours, 2026-08-17)
The touchscreen UI's resume handler unconditionally sends `G28 Y` + `G28 X`
before `RESUME` (hardcoded in `TM_T1/bin/client`; the binary even ships a
"Model misalignment alert" message acknowledging the resulting shift). Each
re-home lands within endstop repeatability of the original datum, shifting
the resumed layers. Since every G28 routes through `[homing_override]`, the
override now skips XY homing while the printer is paused *and* the axis is
still homed. If homing was genuinely lost (motors disabled, power cycle),
`homed_axes` is empty and homing proceeds; printing-state re-homes
(toolchange retry recovery) are untouched.

### toolchange-feedrate-preserve — `live/change_macros.cfg` T0–T3 (ours, 2026-08-18)
Gcode feedrate is modal; toolchange internals (dock moves, wipe) leave it
polluted and slicers omit F when they believe speed is unchanged, so
post-toolchange travels crawled (5–50 mm/s). T macros capture the slicer's
feedrate on entry and re-assert it on exit (feedrate only — a full
RESTORE_GCODE_STATE would revert the new tool's XY offset).

### wipe-feedrate-restore / wipe-speed — `live/fz-wipe-nozzle.cfg` (ours, 2026-08-17/18)
WIPE_NOZZLE brackets itself with SAVE/RESTORE_GCODE_STATE and strokes at a
tunable 200 mm/s (`wipe_speed`, stock: hardcoded 50 mm/s).

### load-auto-wipe — `live/macros.cfg` EXTRUDE_FILAMENT (ours, 2026-08-18)
Auto-wipe after the load purge; the screen's "clean nozzle manually" dialog
becomes a formality.

### pause-park-margin + rehome-escape — `live/macros.cfg`, `live/printer.cfg` (ours, 2026-08-18)
Pause park moved Y1 → Y20 (1 mm front margin invited strikes); `REHOME`
macro forces a real XY re-home while paused (the homing gate otherwise
blocks all paused-state G28s, including deliberate recovery).

### left-edge-purge — `live/macros.cfg` START_PRINT (ours, 2026-08-19; supersedes purge-approach-margin)
Purge line moved from the bed front to the plate's left edge (X0,
Y100→150, outside printable X): same on-bed priming drag, zero front
geometry exposure, zero printable-area cost, no stripe in the print area.

### purge-approach-margin — superseded (ours, 2026-08-18) — ROOT CAUSE FIX
At the stock purge position Y-1 the toolhead shroud strikes the front panel
on every print start (bang), occasionally gripping and stealing ~1.5 mm of
Y — the source of mysteriously shifted prints. Proven with stepper-counter
checkpoints inside START_PRINT (zero loss through home/mesh/toolchange/purge
even during an audible slam ⇒ the panel yields, not the belts). Purge start
moved to Y2 on the bed's front edge. Every other suspect (docks, endstop
repeatability hot+cold, mesh probing, top cover, Z) instrumented and
acquitted along the way.

## Vendor touchscreen landmines (from binary analysis of TM_T1/bin/client)

- **Toolhead-count switch replaces `printer.cfg` wholesale** with a factory
  template (and blanks `wm_zru_thr*.cfg` CAN UUIDs). Re-deploy from
  `config/live/` after ever using that screen flow.
- **Screen calibration flows (resonance/PID/leveling) end in SAVE_CONFIG**,
  overwriting our shaper values and shifting the SAVE_CONFIG block. Use
  `utils/resonance.py` instead; run `utils/config_sync.py diff` after any
  screen calibration.
- The tool-offset calibration flow disables X/Y steppers (homing is
  legitimately lost; a re-home after those flows is expected).
- UI-resume overrides the RESUME macro's saved temperatures and (before our
  homing_override gate) forced `G28 Y` + `G28 X` before every resume.
- OTA firmware fetches over plain HTTP (`po.wondermaker3d.com`); a
  `boot.img` on a USB stick triggers an unattended boot-partition update;
  the internet check fetches a developer's personal Gitee repo.

## Considered and not imported

- **WonderSync** (`Experimental/wondermaker_mmu.py` in the mods repo): a
  Klipper/Moonraker module exposing touchscreen filament assignments as a
  virtual MMU so Orca's "Sync filaments" button works. Useful but
  experimental and a separate Python module rather than a config change —
  revisit when it matures.
- The mods repo's whitespace/reformat-only differences in `stock_macros.cfg`
  vs `macros.cfg` (their "stock" file is not actually stock).

