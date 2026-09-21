# Printer configuration: stock vs live

- **`stock/`** — latest vendor baseline, **System_1.1.12** (2026-09-21),
  kept as a real directory. Built from the sanitized installed 1.1.08
  snapshot and the verified 1.1.12 door-input delta. Retains the installed
  model's zru-s include and reference files
  absent from the System package. SAVE_CONFIG and CAN UUIDs remain sanitized.
  Previous baselines are archived unchanged in **`stock_1.1.08/`**,
  **`stock_1.1.04/`** and **`stock_1.0.71/`**. Provenance and reconciliation:
  [1.1.12 integration notes](../docs/firmware-1.1.12.md).
  Never put W+ modifications in stock; make those in live with markers.
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

Install the live configuration with:

```bash
uv run --with paramiko python tools/deploy.py install config
```

**Full installation requires SSH.** The config component first installs the required
`klipper_extras/wmp_recovery.py` into Klipper's extras directory, then uploads
configuration over Moonraker and restarts Klipper. The `[wmp_recovery]` section
in printer.cfg cannot load without that module.

For subsequent config updates, deploy over **Moonraker HTTP only**, without SSH
or paramiko:

```bash
uv run python tools/deploy.py install config --config-only
uv run python tools/deploy.py install config --config-only --files macros.cfg
```

The matching `klipper_extras/wmp_recovery.py` must already be installed.
`--config-only` skips installing that module; it does not verify its version.
Run the full SSH installation again when the module changes or a vendor firmware
update removes it. Add `--no-restart` to upload without restarting Klipper.

`utils/config_sync.py` transfers config over **Moonraker's HTTP API**. Diff and
pull need no SSH. Use direct `push` only after the matching required extra has
been installed; it does not install Python modules. The deploy wrapper's
`--config-only` option uses this same HTTP push path.

```bash
uv run python utils/config_sync.py diff            # show what differs from the printer
uv run python utils/config_sync.py diff --patch    # show content differences, printer -> repo
uv run python utils/config_sync.py push            # upload changed files, then restart Klipper
uv run python utils/config_sync.py push macros.cfg # push only the named file(s)
uv run python utils/config_sync.py pull DIR        # download the printer's config to inspect
```

On push it:

- backs up each replaced file on the printer as `<name>.wmp-backup-<timestamp>` first,
- firmware-restarts Klipper and confirms it returns to **Ready** (fails loudly if not),
- refuses to run while a print is in progress,
- accepts `--no-restart` (upload only) and `--ssh` (use SFTP if Moonraker is down).

For the SFTP fallback, put `--ssh` before the subcommand:
`uv run --with paramiko python utils/config_sync.py --ssh push --no-restart`.
Restart and readiness checks still require Moonraker when `--no-restart` is omitted.

**Your printer-specific calibration is preserved on every push:**

- **Bed mesh, input shapers, probe offsets** — `printer.cfg`'s SAVE_CONFIG
  block is read live from the printer and spliced back onto the pushed file,
  so it is never overwritten.
- **CAN bus UUIDs** (`wm_zru_*.cfg`) — never pushed.
- **Tool offsets and filament settings** (`saved_variables.cfg`, `tmt1.ini`) —
  never touched.

Target the printer with `WMP_PRINTER` (and `WMP_USER` / `WMP_PASS` for `--ssh`).

`uv run python tools/deploy.py status config --diff` shows the same content
preview. New files are included; printer.cfg's SAVE_CONFIG and machine-owned
files are excluded using the same ownership rules as push.

## Reviewing future firmware migrations

Archive the current stock as `stock_<old-version>/` before updating `stock/`
with verified vendor changes. Keep the new baseline's provenance separate
from machine-specific preferences. Reconcile W+ edits before deploying.
The community-inspired helper can review that merge:

```sh
uv run python tools/update_config_base.py config/stock_1.1.08 config/stock config/live
uv run python tools/update_config_base.py OLD_STOCK NEW_STOCK LIVE --output /tmp/wmp-candidate
```

It never changes stock or live, and the output directory must be new.
Candidates exclude UUID/runtime files and printer.cfg's SAVE_CONFIG. Review
reported conflicts, added/removed files and lost change markers before
copying reconciled files into live. Exit 1 means review remains; exit 2 means
a tool/input error and no candidate is published. A clean textual merge
does not verify printer motion. The helper does not install firmware or
automatically rotate/promote baselines.

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

> **1.1.08 reconciliation (2026-09-13).** All active W+ changes below are
> retained. Adopted vendor physical-heater waits, M104/M109 selection,
> PAUSE reset-before-shutdown, idle-timeout physical-heater shutdown, and
> disabled door-button registrations. PAUSE keeps our mapping snapshot
> before the reset. Camera settings and parameterized calibration temperatures
> are unchanged. The community XY return now runs after verified success and
> wiping, with logical-coordinate capture and failure/retry handling
> ([sequence](../docs/toolchange-return.md)). Calibration and homed idle tool/
> wipe travel establish a 7 mm minimum; print changes retain their 2 mm lift.
> Hardware acceptance remains in [the integration notes](../docs/firmware-1.1.08.md).
> Deployed 2026-09-13: config matched, Klipper Ready, and client patches loaded.
> Updated 2026-09-14: two-color prints and power-loss recovery passed with
> T0 and T2 probing references and remapped tools. The chamber-fan cooling
> experiment was removed after measurement; the final suite passes 125 tests.

> **1.1.12 reconciliation (2026-09-21).** The only packaged config change
> since 1.1.08 re-enables the empty Door_button1/2 registrations on PA7/PB7.
> Stock and live adopt that explicit vendor reversal. All other W+ config
> changes remain unchanged; the packaged Klipper tree and macro files are
> byte-identical to 1.1.08. See the [1.1.12 analysis](../docs/firmware-1.1.12.md).

> **Status after the 1.1.04 re-baseline (2026-08-19).** The entries below
> describe each delta's history. On that historical 1.1.04 base:
> **active** — accel-cap, input-shaper values, pause-mapping-snapshot,
> pause-park-margin, left-edge-purge (supersedes purge-approach-margin),
> toolchange-feedrate-preserve, toolchange-wipe, u1-tip-shaping, insert-no-autoload, probe-with-initial-tool (on by default), wm-material-include, wipe-speed +
> wipe-feedrate-restore (merged with the vendor's new `wipe_position`),
> REHOME macro.
> **dropped (vendor fixed it in 1.1.04)** — skip-forced-rehome-on-resume
> (binary-verified: the resume path no longer force-homes; keeping our gate
> would block the wanted recovery re-home); load-auto-wipe (1.1.04 wipes
> after the load purge itself); print-end-rewrite (1.1.04's PRINT_END adds
> Z-safety, wiper-park, and the `print_body_ready` UI contract — taken as-is).
> **deferred** — start-print-chamber (speculative; re-add if printing ABS/ASA).
> See `analysis/fw_1.1.04_diff/MERGE-PLAN.md` for the full rationale.

### Chamber-fan cooling experiment — removed (2026-09-14)
The cooling detours, blob relocation and temporary auxiliary-fan boost were
removed after three runs per condition showed no cooldown improvement over
the part fan alone. Normal cooling locations and part-fan operation are
restored; the independent temperature-wait fixes remain.
[Measurements and rollback scope](../docs/cooling-assist.md).

### explicit-cooldown-wait — `live/offset_calibrate.cfg` (2026-09-13)
NOZZLE_PREPARE and POP use SET_HEATER_TEMPERATURE plus an upper-only
TEMPERATURE_WAIT for their final cooldowns. Targets remain 100/102°C with
the existing +2.5°C tolerance; both commands address the same mapped heater.
General M109/M190, chamber waits, probing and tool-change bands are unchanged.

### probe-with-initial-tool — `live/macros.cfg`, `live/printer.cfg`, `live/change_macros.cfg` (ours, 2026-08-30)
On by default as of 2026-09-13, following successful testing reported by the
user and other users. Disable per machine with `PROBE_WITH_INITIAL_TOOL ENABLE=0`
(saved variable; `ENABLE=1` re-enables; no argument reports). Existing saved
preferences are preserved, including an explicit False opt-out.

Stock `START_PRINT` homes Z and meshes with T0, parks it, then fetches
`INITIAL_TOOL`. When enabled, `START_PRINT` stores the physical tool behind
`INITIAL_TOOL` (via `box_modify_t*`) in the `probe_tool` saved variable and
heats it; `Z_HOMING` grabs `_CHANGE_TOOL T={probe_tool}`; `_OFFSET_SET`
applies `offset(tool) − offset(probe_tool)`. `probe_tool = 0` is stock
behaviour (`t0_offset` is `(0,0,0)`). `probe_tool` is set to 0 when the
saved default mesh is used (T0 datum), in `G29`, `PRINT_END`,
`CANCEL_PRINT`, and 2 s after Klipper starts.

Fresh per-print meshes use the reserved `wmp_print` profile, preserving
`default`. Saved-default starts also snapshot their mesh to `wmp_print`.
Power-loss recovery restores the recorded physical probing tool and this
snapshot. Missing context or changed calibration stops recovery instead of
guessing a reference. See [print-mesh-recovery](../docs/print-mesh-recovery.md).
Physical testing was reported by users. The default change and recovery
integration were deployed on 2026-09-13 and loaded with Klipper Ready;
the new recovery path still needs physical acceptance.

### u1-tip-shaping — `live/macros.cfg` (2026-08-29)
`RETRACT_FILAMENT` (touchscreen unload) and `UNLOAD_FILAMENT` (manual)
call `_TIP_SHAPE_RETRACT`, which sets the unload temperature, runs
`_TIP_SHAPE_MOVES CLASS=…`, then `M104 S0`, fan 100 %, `post_cool_s` (5 s),
`WIPE_NOZZLE`. Purge position: `X-13 Y80` (same as `EXTRUDE_FILAMENT`).
Net retraction: −57 mm (stock), −67 mm for `petg`.

| class | materials | sequence | source | temp |
|---|---|---|---|---|
| `pla` | PLA, PVA, Marble, PA, PC | purge, fast pull, slow pull, re-plunge, fast pull, slow pull, extract | Snapmaker U1 1.6.0 `CONTROL_RETRACT_ACTION` (`docs/reference/snapmaker-u1-unload-macros.cfg`) | 250 (PA 280, PC 300) |
| `abs` | ABS, ASA, HIPS, Wood | as `pla`, slower re-plunge and last slow pull | U1 | 280 (Wood 250) |
| `soft` | TPU, TPE | small purge, fast pull, slow pull, extract | U1 | 250 |
| `petg` | PETG, PCTG, PET | ram 17.5 mm/s, one 60 mm/s pull, 3 cooling moves 5→2.5 mm/s, stamp 35 mm, pull, extract | Prusa `PrusaResearch.ini` `*PETPG*` (Core One / MK4 MMU3) | 235 |

Temperatures: `variable_unload_temps` in `_TIP_SHAPE_RETRACT`;
`unload_temp_min` is the floor for unlisted materials, 0 disables.
`petg` tuning: `cooling_moves`, `cooling_len`, `cooling_speed_list`,
`stamp_len` in `_TIP_SHAPE_MOVES`. The 17.5 mm/s ram skips a few steps on
this extruder; the extra 10 mm of extraction covers it.

Overrides: `_TIP_SHAPE_RETRACT DRY_RUN=1` reports the class and temperature
without moving; `MATERIAL=ABS`, `CLASS=soft`, `TEMP_MIN=240`.

Material detection, in order:
1. `wm_material` Klipper extra (optional, needs SSH: `tools/deploy.py install
   material`). Reads the touchscreen's `tmt1.ini` (`[slot] material0..3`)
   and exposes `printer.wm_material.material0..3`. `WM_MATERIAL_STATUS`
   prints them. A vendor firmware update removes it; reinstall.
2. Hotend target set by the touchscreen: 230 → `soft`, ≥255 → `abs`, else
   `pla`. PETG and ABS both arrive at 250 and cannot be told apart; PETG
   needs the module (or `MATERIAL=PETG`).

### insert-no-autoload — `live/extruder0-3.cfg` (2026-08-30)
The filament sensor `insert_gcode` no longer runs the stock auto-load (pick
tool, purge, wipe, dock); it prints a hint and cancels the runout pause.
Reason: the sensor is only enabled for the active tool, so it fired during
the touchscreen's Load flow, which then ran its own `EXTRUDE_FILAMENT`
(purge, dock, undock, purge, dock). Load from the screen is the only load
path.

### wm-material-include — `live/printer.cfg` (2026-08-29)
`[include wm_material*.cfg]`. The glob matches nothing when the module is
not installed, so `printer.cfg` works with or without it.

 — `live/macros.cfg` (ours, 2026-08-17)
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


## Native bottom-Z recovery (2026-09-14)

Unhomed tool selection now establishes Z at the bottom before XY homing or
pickup. The required `wmp_recovery` extra tracks actual Z-rail homing and
invalidates its reference when the Z motor is disabled or Klipper restarts.
Synthetic position assignment cannot create this reference. The two previous
synthetic lift paths also use native bottom homing when the reference is invalid.
Recovery G28 reuses that reference, skips normal Z_HOMING, restores the exact
print mesh and reapplies offsets for the mounted tool relative to the saved
probing tool. It retains shutdown protection for invalid recovery contexts.

The touchscreen binary is unchanged. Its later checkpoint-Z-plus-3 lift,
wipe and XY return remain the vendor sequence; this does not guarantee
clearance over every object on a loaded plate. Interrupted-tool-change
checkpoint reconciliation remains separate. See
[recovery details](../docs/print-mesh-recovery.md) and the
[max-Z measurements](../docs/z-recovery-investigation.md).
