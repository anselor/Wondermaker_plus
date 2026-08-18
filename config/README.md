# Printer configuration: stock vs live

- **`stock/`** — pristine snapshot of the Klipper config as shipped
  (firmware `KLP_IMG_WM_ZRU_V1.0.26_20251127`), captured 2026-08-16.
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

