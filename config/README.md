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
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload
```

Full installation copies the required `klipper_extras/wmp_recovery.py` and
`klipper_extras/wmp_case_light.py` helpers into Klipper's extras directory, backs
up and uploads changed configuration, and restarts Klipper. The recovery helper
establishes Z at the bottom before unreferenced tool pickup; the light helper
exposes the stock case light to G-code.

For later updates, HTTP is enough if the matching helpers are already installed:

```bash
uv run --with jinja2 python tools/deploy.py install config --config-only
uv run --with jinja2 python tools/deploy.py install config --config-only --files macros.cfg
```

Use full installation again when a helper changes or vendor firmware removes
it. HTTP checks the running helpers' expected status fields but cannot compare
their source. Add `--no-restart` to defer loading the uploaded configuration.
Installation refuses changes during running or paused prints or when the printer's
state cannot be established. A failure during upload may leave some changes applied.

Power-loss recovery also requires the `preload` component. Before updating an
interrupted print, read the [checkpoint upgrade limits](../client-preload/README.md#upgrading-with-an-interrupted-print).

## Configuration validation

Before proposing configuration changes, run:

```bash
uv run --with jinja2 python tools/validate_klipper_config.py
```

The default audit covers every Klipper `.cfg` in `config/live/` and
`klipper_extras/`, including macros in filament sensors, buttons, idle handlers,
and other `*_gcode` options. To validate a different config tree, pass its path;
include all referenced fragments. Historical `config/stock*` snapshots are
preserved unchanged and can be checked explicitly. Moonraker/crowsnest `.conf`
files use different schemas and are outside this Klipper validator's scope.

Checks cover config-file syntax, Jinja syntax, macro-variable Python literals,
include resolution/cycles, literal extended-command arguments and quotes,
UTF-8/hidden control characters, and suspicious Unicode punctuation in command
syntax. Diagnostics include the file, line, section, and error type; a failed
audit returns nonzero. Valid G-code comments and direct Jinja response messages
can contain semicolons. Quoted extended-command arguments cannot safely contain
`#`, `*`, or `;`: Klipper truncates at those characters before parsing quotes.
Use commas/ordinary words in `RESPOND MSG` strings instead.

The same checks run on the prospective configuration during full and HTTP-only
deployment preflight, before any helper/config upload. Direct `config_sync.py push`
also validates selected files before backing up or uploading them. The material
component's optional Klipper config is also checked. Deployment needs local `jinja2`;
add `--with jinja2` to `uv run`. The GitHub `Validate Klipper configs` workflow
runs the audit and its regression tests for pull requests and pushes to `main`.
Make that check required in branch protection if it should block merging.

This is static validation: it does not execute macros, connect to printer hardware,
validate every third-party option or MCU pin, or prove arbitrary runtime values
are safe. Normal Klipper startup validation and motion/heating tests still apply.

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
head. WM+ resolves the vendor `box_modify_t*` mapping before choosing a probe head.
Tool offsets are applied relative to the head that probed the bed.

Fresh and saved-default starts both save a separate `wmp_print` mesh for recovery.
They preserve the normal `default` calibration. The
[recovery guide](../docs/print-mesh-recovery.md) explains the saved print information
and checks.

### Pause and resume

Before pausing, WM+ saves the current slicer-to-head mapping. Resume restores it,
so a Fluidd pause does not load a different color from stale touchscreen settings.
The screen can still deliberately remap a spool while paused.

Pause parks at Y20 instead of Y1 to leave more front clearance.
`REHOME` requests a deliberate X/Y rehome; it can shift the resumed print's
alignment. The old automatic paused-homing workaround was removed when vendor
1.1.04 changed its resume behavior.

Pause/resume heater restoration uses physical heater names.

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
uv run --with paramiko --with jinja2 python tools/deploy.py install material
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

### Case light preference, screen sleep, and printing

The saved preference uses Klipper's `SAVE_VARIABLE` mechanism, under
`wmp_case_light_enabled` in the existing managed variables file. There are no
manual edits to that file or to the stock `tmt1.ini`. Screen settings are read
from `tmt1.ini` only. Moonraker's database is not required.

Use these commands from Fluidd or print G-code to change the saved preference:

```gcode
SET_PIN PIN=case_light VALUE=1
SET_PIN PIN=case_light VALUE=0
CASE_LIGHT_TOGGLE
```

`CASE_LIGHT_ON` and `CASE_LIGHT_OFF` are also available in Fluidd's macro panel.
On means illumination is allowed when needed; Off keeps the light off regardless
of print/screen state. Toggle changes the **saved preference**, even when an On
preference currently has the physical light off. The stock circuit is digital;
fractional values are rejected. The commands follow Klipper's
[SET_PIN format](https://www.klipper3d.org/G-Codes.html#output_pin).

With the preference On, the physical light stays on whenever:

- A print is active, including paused prints.
- The last print finished less than one screen-sleep delay ago.
- The physical screen backlight is on.

Otherwise it turns off. Waking the screen turns it on again; automatic changes
never overwrite the preference. `START_PRINT` honors the preference and clears
old print grace. `PRINT_END` and `CANCEL_PRINT` start a fresh grace interval after
cleanup. The controller also observes actual print-state transitions, including
errors and jobs started outside these macros. A new print cancels previous grace.

The grace interval uses the current `[screen] screen_off_delay` from the stock
`tmt1.ini`, stored in **milliseconds** (`300000` = 5 minutes). It follows changes
made through the stock Screen Sleep setting. Screen blanking may be disabled;
as long as the backlight stays on, the On preference keeps the light on.

Install both components for screen choices and G-code to share the preference:

```bash
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload
```

The `case-light` screen bridge forwards explicit stock light clicks to
`POST /printer/wmp_case_light/set` through local Moonraker, using the same saved
preference implementation as `SET_PIN`. This bypasses the G-code queue so Off
can take effect during long heater/dwell waits. The bridge falls back to
`SET_PIN` when the direct endpoint is unavailable and preserves the vendor GPIO
setter for initialization/manual fallback.
The screen button displays the saved preference rather than the physical GPIO,
so it stays On during automatic screen sleep. The bridge notifies Klipper before
enabling the backlight, turning on the case light without waiting for the next
poll. Wake never changes the saved preference; Off still wins. These requests
use local Moonraker and fall back to normal screen wake if the backend is down.
This records Off even when the GPIO was already off automatically. The bridge
checks the complete stock executable and all hooked functions before patching;
unknown or modified clients are skipped. Check `status preload` and the current
process log at `/tmp/wmp_case-light.log` after installation. Merely loading a
library does not prove its hooks applied. The preference survives Klipper restart;
post-print grace does not. First installation adopts the existing light state.

The helper uses host GPIO76 rather than an MCU pin; do not add an
`[output_pin case_light]` section. It polls the preference, print state and screen
at 0.5-second intervals. Its `wmp_case_light` status reports `enabled` (preference),
`value` (physical output), `available`, `print_active`, `policy_version`, and
`last_error`. Missing/invalid state prevents automatic writes and is logged
without aborting print startup or cleanup. Manual command failures are reported
as command errors. The helper never exports or resets GPIOs. The root-owned stock screen bridge
delegates ownership of only `/sys/class/gpio/gpio76/value` to the stock Klipper
user (`t13dp`) and restores that permission if the GPIO is re-exported. Direction,
export control, and other GPIOs remain untouched.

Stock 1.1.13 binary inspection identifies GPIO2_B4 at
`/sys/class/gpio/gpio76/value`, active high. The home-page light callback uses
`set_GPIO2_B4_high` / `set_GPIO2_B4_low`. `update_common_status` reads the GPIO
every 50 updates, changes `led_on`, and refreshes the icon, so the icon should
follow physical illumination on its next poll.

On 2026-11-08, printer checks verified screen/G-code preference changes,
persistence across Klipper restart, screen-off/wake behavior, active and paused
print state, timer replacement by a new print, and actual shutoff after 300.2
seconds with the GUI set to five minutes. A screen Off click saved within 0.904
seconds during a 30-second G-code dwell. The original 30-minute sleep setting was
then restored through the GUI. Light-only SD jobs also verified `PRINT_END` reaches
EOF and cancellation clears native pause state. Axes stayed unhomed, positions
unchanged, and heater targets zero. The stock unhomed guard refused pause parking;
physical parking, clearance, wipe, and filament-runout acceptance remain pending.

### Startup, print end, and cooling

The startup purge runs on the plate's left edge at X0, Y100–150. The previous
front-edge position could strike the front panel. The earlier Y2 workaround is
superseded by this left-edge route.

At print end or cancellation, `PRINT_END.variable_bed_drop` defaults to lowering
the bed by up to 50 mm, limited by the bottom endstop. Both paths use the shared
`_WMP_PRINT_END_CLEARANCE_AND_WIPE` helper, which accounts for G-code offsets and
skips the Z move when no downward travel remains. It wipes only while X, Y, and Z
remain homed, then leaves the head over the left brush. `PRINT_END` leaves its SD reader to
reach EOF; cancellation resets the file and explicitly clears native pause flags.

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
uv run --with jinja2 python utils/config_sync.py push
uv run --with jinja2 python utils/config_sync.py push macros.cfg
```

Push backs up replaced files as `<name>.wmp-backup-<timestamp>`, uploads changes,
and checks that Klipper returns to Ready after restarting. `--no-restart` uploads
only. Direct push checks for a running print; use the deploy wrapper for its
stronger paused-print and uncertain-state checks.

If Moonraker is unavailable, SFTP can transfer files:

```bash
uv run --with paramiko --with jinja2 python utils/config_sync.py --ssh push --no-restart
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
