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

Exception to the marker rule: the SAVE_CONFIG block at the bottom of
`printer.cfg` cannot contain comments (Klipper rewrites it), so changes
there are documented only in this file.

**`printer.cfg` caveat:** its SAVE_CONFIG block is part runtime state (bed
mesh, probe offsets update as the printer runs). Before pushing
`printer.cfg`, refresh `live/printer.cfg`'s SAVE_CONFIG block from the
printer's current copy (`utils/config_sync.py pull`) so a push never
reverts a newer mesh; only the marked sections above SAVE_CONFIG are ours.

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

## Considered and not imported

- **WonderSync** (`Experimental/wondermaker_mmu.py` in the mods repo): a
  Klipper/Moonraker module exposing touchscreen filament assignments as a
  virtual MMU so Orca's "Sync filaments" button works. Useful but
  experimental and a separate Python module rather than a config change —
  revisit when it matures.
- The mods repo's whitespace/reformat-only differences in `stock_macros.cfg`
  vs `macros.cfg` (their "stock" file is not actually stock).
