# Printer configuration

`config/live/` contains the WM+ configuration you can install.
`config/stock/` contains the vendor baseline used to compare it. The current
baseline is **System 1.1.13** and requires that firmware's calibration modules.
It has passed local checks; printer testing for 1.1.13 is still pending.

Your printer's calibration and hardware identifiers stay on your printer.
The repository contains sanitized reference files, not another machine's
calibration to copy.

## Install and compare

Set connection details using the [project README](../README.md), then run:

```bash
uv run python tools/deploy.py status config --diff
uv run --with paramiko python tools/deploy.py install config --preflight-only
uv run --with paramiko python tools/deploy.py install config
```

Full installation copies the required `klipper_extras/wmp_recovery.py` helper
into Klipper's extras directory, backs up and uploads changed configuration,
and restarts Klipper. The helper establishes Z at the bottom before unreferenced
tool pickup. `printer.cfg` requires it to load.

For later updates, HTTP is enough if the matching helper is already installed:

```bash
uv run python tools/deploy.py install config --config-only
uv run python tools/deploy.py install config --config-only --files macros.cfg
```

Use full installation again when the helper changes or vendor firmware removes
it. HTTP checks the running helper's expected status fields but cannot compare
its source. Add `--no-restart` to defer loading the uploaded configuration.
Installation refuses changes during running or paused prints or when the printer's
state cannot be established. A failure during upload may leave some changes applied.

Power-loss recovery also requires the `preload` component. Before updating an
interrupted print, read the [checkpoint upgrade limits](../client-preload/README.md#upgrading-with-an-interrupted-print).

## What stays on your printer

| Data | How it is preserved |
|---|---|
| Bed mesh, input shapers, probe offsets | The target printer's `SAVE_CONFIG` block is retained when uploading `printer.cfg` |
| CAN bus identifiers in `wm_zru_*.cfg` | These files are excluded from comparison and upload |
| Tool offsets in `saved_variables.cfg` | Runtime file is excluded |
| Filament settings in `tmt1.ini` | Runtime file is excluded |
| Backups and recovery state | Runtime files and existing WM+ backups are excluded |

The repository owns the body of `printer.cfg`, above `SAVE_CONFIG`.
Comparison ignores the printer-owned block. Upload joins the new body with the
printer's existing block. Set input-shaper values using
[the resonance tools](../utils/README.md), not a reference copy of `printer.cfg`.

Earlier Git history contains one machine's calibration and identifiers. If creating
a sanitized public history, start from the current tree rather than assuming that
older commits are sanitized too.

## Current changes

### Probe with the first print tool

Enabled by default, this homes Z and measures a fresh bed mesh with the physical
head that will print first. It can avoid fetching and returning T0 unnecessarily.
The choice is saved per printer:

```gcode
PROBE_WITH_INITIAL_TOOL ENABLE=0
PROBE_WITH_INITIAL_TOOL ENABLE=1
PROBE_WITH_INITIAL_TOOL
```

The last command reports the setting. Existing opt-outs remain effective.
A saved-default mesh still uses physical T0, the head used to calibrate it.
`G29` explicitly selects physical T0 even if slicer T0 is mapped to another head.

A **logical tool** is a slicer's T0–T3 selection; a **physical tool** is a printer
head. WM+ resolves the mapping before choosing a probe head. With openACE it uses
`tool_extruder_index`; otherwise it uses the vendor `box_modify_t*` variables.
Missing openACE mapping data stops startup rather than selecting a guessed head.
Tool offsets are applied relative to the head that probed the bed.

Fresh and saved-default starts both save a separate `wmp_print` mesh for recovery.
They preserve the normal `default` calibration. The
[recovery guide](../docs/print-mesh-recovery.md) explains the saved print information
and checks.

### Pause, resume, and openACE

Before pausing, WM+ saves the current slicer-to-head mapping. Resume restores it,
so a Fluidd pause does not load a different color from stale touchscreen settings.
The screen can still deliberately remap a spool while paused.

Pause parks at Y20 instead of Y1 to leave more front clearance.
`REHOME` requests a deliberate X/Y rehome; it can shift the resumed print's
alignment. The old automatic paused-homing workaround was removed when vendor
1.1.04 changed its resume behavior.

`[include openace*.cfg]` keeps optional openACE configuration connected when WM+
replaces `printer.cfg`. It matches nothing on printers without openACE.
The [compatibility preload](../client-preload/README.md#openace-compatibility)
lets openACE handle the screen's Resume request and routes screen heater commands
to physical heads. Pause/resume heater restoration also uses physical heater names.

### Tool changes and wiping

Successful tool changes wipe the new nozzle, then return to the saved print
position at 200 mm/s with a 2 mm lift before lowering to the printing height.
Startup, idle selection, paused changes, same-tool selection, and changes without
position saving do not use that print-return path. A failed change does not wipe
or return. See [the sequence and tests](../docs/toolchange-return.md).

T0–T3 calls preserve the slicer's feedrate so docking or wiping does not slow later
moves. The wipe saves and restores its local motion state. `wipe_speed` in
`live/fz-wipe-nozzle.cfg` controls wipe speed; the WM+ default is 200 mm/s.

Calibration and homed idle tool/wipe travel establish at least 7 mm clearance in
both G-code and physical coordinates, without lowering a higher position.
Print tool changes retain their separate 2 mm lift. These values follow the
existing printer geometry; they are not a guarantee of clearance for every part.
Firmware 1.1.13's collision monitor remains enabled around tool-alignment probing.

### Filament loading and unloading

Use **Load** on the screen to feed inserted filament. The insertion sensor reports
that filament is present rather than starting a second automatic load/purge cycle.

Load and unload moves require homed X, Y, and Z. During a running print, pause
first. The service move raises clearance by up to 5 mm within Z travel, exits
along X, and travels along the left side to X-13 Y80. Paused runout changes remain
supported.

Unloading shapes the filament tip to reduce blobs and strings, then turns off the
heater, runs the part fan, waits five seconds, and wipes. Material determines the
sequence and temperature:

| Class | Materials | Temperature (°C) | Sequence source |
|---|---|---|---|
| `pla` | PLA, PVA, Marble, PA, PC | 250; PA 280; PC 300 | Snapmaker U1 1.6.0 |
| `abs` | ABS, ASA, HIPS, Wood | 280; Wood 250 | Snapmaker U1 1.6.0 |
| `soft` | TPU, TPE | 250 | Snapmaker U1 1.6.0 |
| `petg` | PETG, PCTG, PET | 235 for PETG/PET; unlisted names use the configured floor | Prusa MMU3 PETPG profiles |

PLA/ABS sequences alternate fast pulls, slower pulls, and reinsertion. Soft
filament uses a shorter sequence. PETG uses a push, fast pull, three cooling
moves, reinsertion, and extraction. Net retraction is 57 mm, or 67 mm for PETG.
The PETG push skipped some extruder steps on the test machine; its extra extraction
length accounted for that observation.

Install `material` to read the screen's slot materials:

```bash
uv run --with paramiko python tools/deploy.py install material
```

`WM_MATERIAL_STATUS` reports them. Without that helper, unload guesses from the
hotend target: 225–235°C selects `soft`, at least 255°C selects `abs`, and other
targets select `pla`. PETG and ABS can both arrive at 250°C, so temperature alone
cannot distinguish them. Use the helper or an explicit `MATERIAL=PETG`.

Advanced controls in `_TIP_SHAPE_RETRACT` include `unload_temps`,
`unload_temp_min`, `MATERIAL=`, and `TEMP_MIN=`. A floor of zero disables temperature
adjustment. `_TIP_SHAPE_RETRACT DRY_RUN=1` reports its choice without movement.
`CLASS=pla|abs|soft|petg` goes directly to the movement sequence, skipping material
and temperature selection; use it only with the head prepared at temperature.
PETG movement controls are `cooling_moves`, `cooling_len`, `cooling_speed_list`,
and `stamp_len` in `_TIP_SHAPE_MOVES`.

During openACE unload, WM+ enables rollback assist just before the fast withdrawal
so the ACE takes up filament rather than pushing it against the head cover.
It turns assist off after the last pull, before cooling: an ACE 2 was observed
to error about one second after pulling stopped while assist remained active.
The hooks do nothing outside an openACE unload.

### Startup, print end, and cooling

The startup purge runs on the plate's left edge at X0, Y100–150. The previous
front-edge position could strike the front panel. The earlier Y2 workaround is
superseded by this left-edge route.

At print end, `PRINT_END.variable_bed_drop` defaults to lowering the bed by up to
50 mm, limited by the bottom endstop. It wipes only while X, Y, and Z remain homed,
then leaves the head over the left brush.

Final cooldowns in `NOZZLE_PREPARE` and `POP` wait only until temperature falls
below their upper limits (102.5°C and 104.5°C). An undershoot does not require
reheating. Other heating, probing, and wipe-temperature waits retain their bands.

The auxiliary-fan cooling detour was removed after measurements found no benefit
over the part fan alone. See [the experiment](../docs/cooling-assist.md).
The proposed `START_PRINT CHAMBER` heating changes remain deferred: current startup
does not use that parameter. Separate `M141`/`M191` chamber commands remain available.

### Motion limits and bottom-Z recovery

The WM+ maximum acceleration is 5,000 mm/s², reduced from the vendor's 20,000.
The test printer's shaper fits suggested roughly 2,600–4,400 mm/s² limits; those
results are specific to that machine. Its historical X/Y shaper values are not
installed on other printers because saved calibration is preserved.

The required `wmp_recovery` helper tracks actual Z homing. It invalidates that
reference when the Z motor is disabled or Klipper restarts. Assigning software
coordinates cannot mark Z as physically homed. Tool selection with no valid Z
reference homes the bed to the bottom before X/Y homing and pickup.

Recovery restores the exact print mesh, probing head, offsets, and tool mapping.
It shuts Klipper down if required saved information is missing or mismatched,
blocking later touchscreen motion requests. The vendor's later return still has
clearance and checkpoint limits; see the [recovery guide](../docs/print-mesh-recovery.md).

## Direct configuration transfers

Prefer `tools/deploy.py install config`, which also checks required helpers.
`utils/config_sync.py` is the lower-level transfer tool and does not install Python
modules or run the deploy tool's full installation checks:

```bash
uv run python utils/config_sync.py diff
uv run python utils/config_sync.py diff --patch
uv run python utils/config_sync.py pull /tmp/printer-config
uv run python utils/config_sync.py push
uv run python utils/config_sync.py push macros.cfg
```

Push backs up replaced files as `<name>.wmp-backup-<timestamp>`, uploads changes,
and checks that Klipper returns to Ready after restarting. `--no-restart` uploads
only. Direct push checks for a running print; use the deploy wrapper for its
stronger paused-print and uncertain-state checks.

If Moonraker is unavailable, SFTP can transfer files:

```bash
uv run --with paramiko python utils/config_sync.py --ssh push --no-restart
```

Put `--ssh` before the subcommand. Restart and readiness checks still need
Moonraker. Review the target state yourself before using this fallback.

## Firmware updates and baseline maintenance

The baseline is a sanitized installed-model snapshot with verified vendor changes
applied. It preserves model-specific includes and reference files absent from
factory packages. Earlier baselines remain in `stock_1.1.12/`, `stock_1.1.08/`,
`stock_1.1.04/`, and `stock_1.0.71/`.

For a future update, archive the old stock directory, compare the vendor package,
then merge verified changes into stock and WM+ live configuration. Keep WM+ edits
in live with markers:

```text
# >>> wondermaker+ begin: <change-id> (<origin>)
# Why: <reason>
...
# <<< wondermaker+ end: <change-id>
```

Compare changes with `diff -r config/stock config/live`. Klipper rewrites
`SAVE_CONFIG`, so saved calibration cannot use these comment markers.

The migration helper creates a candidate for review:

```bash
uv run python tools/update_config_base.py OLD_STOCK NEW_STOCK LIVE --output /tmp/wmp-candidate
```

The output directory must be new. The tool excludes machine-owned data and reports
conflicts, file additions/removals, and lost change markers. It does not modify
stock/live or install firmware. Exit 1 means review remains; exit 2 means an input
or tool error and no candidate is published. A clean text merge does not verify
printer motion.

Firmware records: [1.1.13](../docs/firmware-1.1.13.md),
[1.1.12](../docs/firmware-1.1.12.md), [1.1.08](../docs/firmware-1.1.08.md).

## Touchscreen actions that can replace settings

The vendor's toolhead-count setup replaces `printer.cfg` with a factory template
and blanks tool-board CAN identifiers. Restore your own identifiers and calibration
from backups before reapplying WM+; its sanitized references cannot recover them.

Screen resonance calibration replaces saved input-shaper values. Other calibration
flows also rewrite `SAVE_CONFIG`; compare configuration afterward.
Tool-offset calibration disables X/Y motors, so those axes need homing again.
The screen's resume flow can override saved nozzle temperatures.

Firmware analysis also found plain-HTTP update downloads, an unattended boot-image
update triggered by USB `boot.img`, and a connectivity check to a personal Gitee
repository. These are vendor behaviors, not WM+ configuration changes.

## Earlier contributions and proposals

The vendor has incorporated the older load-wipe and print-end changes, and changed
the resume behavior that required the old paused-homing gate. WM+ retains the later
print-end clearance/wipe improvement described above.

The community WonderSync filament-sync module remains separate and experimental;
it was not imported. Historical proposals and decisions are in
[the design record](../docs/design-ideas.md).
