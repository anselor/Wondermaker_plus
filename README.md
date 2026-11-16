# Wondermaker+

Wondermaker+ (WM+) adds improved touchscreen controls, printing fixes and
calibration tools to the Wondermaker U1 / ZR Ultra (`TM-T1`). It runs alongside
the vendor firmware, preserving your printer's configuration files, saved
calibration and hardware identifiers.

## Features

### Toolhead and filament controls

WM+ replaces the stock Filament page with dedicated Filaments and Toolheads
screens:

- Record each head's filament brand, material, colour and loaded state across
  restarts.
- Load and unload filament with automatic head pickup, heating, feeding,
  tip shaping and wiping. Follow the current step or stop the procedure from
  the screen.
- Take or dock a head, set its temperature, and extrude or retract a chosen
  distance.
- Edit nozzle material and diameter for each head. Diameter changes take effect
  after restarting Klipper.
- Review filament colours, materials and head assignments before printing.
- Replace filament during a pause or after runout, then resume the print.

Load and Unload home X/Y when needed without homing Z. The same procedures are
available from the console as `LOAD_FILAMENT HEAD=2` and
`UNLOAD_FILAMENT HEAD=2`, where `HEAD` is the physical head counted from zero.

### Printing and reliability

- **Tool changes:** return to the saved print position after wiping with a
  clearance lift, restore travel speed, and pause recoverable docking or pickup
  failures for inspection, repair and Resume.
- **Print startup:** probe with the first printing head and purge along the
  plate's left edge, away from the front panel.
- **Pause and resume:** preserve tool-to-head assignments and restore nozzle
  temperatures to the correct heads. Runout and tangle pauses allow manual
  movement and filament service before resuming.
- **Print end:** lower the bed by up to 50 mm within its remaining travel and
  wipe the nozzle.
- **Cancel:** stop queued print work, turn off heaters, and clear the state needed
  for the next print.
- **Power Loss Recovery (PLR):** restore the print's bed mesh and tool assignments,
  correct recovery coordinates, and establish Z at the bottom before head pickup.
- **Head-configuration protection:** prevent the screen app from erasing head
  identities after a communication fault. Klipper stays stopped until the fault
  is resolved.
- **Homing and calibration:** use the mounted head for full homing, add motion
  clearance, and stop failed screen calibration before saving results.
- **Filament handling:** load on request instead of triggering a duplicate
  insertion-sensor purge; use material-specific unloading recipes and an
  adjustable wipe speed.
- **Wi-Fi and ventilation:** retry temporary Wi-Fi failures and preserve manual
  filter-fan choices during printing.

### Screen, lighting and vibration tools

- **Touchscreen in Fluidd:** view and control the printer's physical screen from
  your browser while keeping timelapses on the print camera.
- **Case light:** save an On/Off preference shared by the screen, Fluidd and
  G-code. When enabled, the light follows screen activity and stays on during
  printing and pauses.
- **Door wake:** wake a sleeping screen when the door opens.
- **Input shaping:** use newer upstream Klipper input-shaper and resonance-test
  code, including sweeping tests and updated shaper recommendations through the
  screen's Vibration Compensation.
- **Vibration analysis:** measure belt balance and resonance, compare input
  shapers, and verify results during movement.

## Requirements

The current WM+ version requires **vendor System 1.1.13**, installed separately.
For older firmware, choose a matching release from the
[release guide](docs/releases.md).

Installation runs from your computer and requires
[uv](https://docs.astral.sh/uv/getting-started/installation/), SSH access to the
printer, and sudo for the screen patches, Moonraker fixes, browser screen bridge
and input-shaper backport.

The installer runs from Windows, Linux or macOS; Linux service commands and C
compilation run on the printer over SSH. Keep repository files in their original
UTF-8 encoding and LF line endings: the supplied `.gitattributes` preserves these
for Git checkouts, and source verification intentionally rejects modified package
inputs. Native screen development builds still require the documented Linux/Docker
toolchain; installing the supplied screen package does not.

## Install or update

From a local checkout of this repository, copy [.env.example](.env.example) to
`.env` and set:

- `WMP_PRINTER`: printer hostname or IP, without `http://`.
- `WMP_USER`: printer SSH username.
- `WMP_PASS`: printer SSH password.

Git ignores `.env`; exported environment values override it. SSH uses your
known-hosts file. The example explains the optional first-connection trust setting.

With the printer idle, check prerequisites, install, then check status:

```bash
uv run --with paramiko --with jinja2 python tools/deploy.py install all --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install all
uv run --with paramiko python tools/deploy.py status
```

The installer checks all selected components before applying changes. It refuses
installation during a running or paused print, or when printer state cannot be
determined. A failed prerequisite check installs nothing.

Installation restarts the affected services, including the screen program and
Klipper. `--no-restart` defers only the final configuration restart; component
service restarts still occur.

If installation fails, the tool attempts to restore changed components and
reports anything it cannot confirm. Recovery journals are saved under
`.wmp-install-journals/`. Follow the [recovery guide](docs/installation-recovery.md)
if installation is interrupted or rollback is unconfirmed.

### Components

Use component names in place of `all` to select what to install:

| Component | Provides |
|---|---|
| `config` | Printer macros and Klipper helpers, added through a separate configuration include |
| `material` | Filament records and material settings for loading and unloading |
| `preload` | Screen fixes, head-configuration protection, light control, and the Toolheads and Filaments screens |
| `moonraker` | Moonraker fixes required by the new screens; included automatically with `preload` |
| `touchscreen` | Interactive Fluidd screen panel and timelapse-camera selection |
| `shaper` | Updated Klipper input shaping, calibration and resonance testing |

Install `config material preload` together for the printing fixes and new screens.
The Fluidd panel and input-shaper backport are optional; `all` includes both.

The `shaper` component replaces six vendor Klipper files, keeps their originals
on the printer, and builds Klipper's C helper there. **Run Vibration Compensation
again after installing it:** the `ei`, `2hump_ei` and `3hump_ei` shapers change
behaviour. See the [input-shaper guide](klipper_backport/input_shaper/README.md).

Reapply WM+ after a vendor firmware update. The screen program may remain stopped
until the `preload` component is reinstalled or removed. Before updating a printer
with an interrupted print, read the
[recovery checkpoint limits](client-preload/README.md#upgrading-with-an-interrupted-print).

## Uninstall or return to an earlier release

With no print running or paused, use the checkout that installed the current
version to remove WM+:

```bash
uv run --with paramiko --with jinja2 python tools/deploy.py uninstall all
uv run --with paramiko python tools/deploy.py status
```

Removal handles the screen before its backend dependencies and restarts affected
services. If a component cannot be removed, it stops and retains later
dependencies; resolve the reported error before continuing. Removing WM+ is not
a factory reset. For an interrupted installation, use the printed installer
journal and the [recovery guide](docs/installation-recovery.md) instead.

To downgrade, finish removal first, then choose a complete earlier release that
supports the printer's installed vendor firmware, as described in the
[release guide](docs/releases.md). Run that release's installation instructions.
Do not mix its screen binary with newer macros or backend helpers. Keep the
current checkout and its recovery journal until removal and the replacement
installation are verified. Restoring an earlier WM+ release does not downgrade
the vendor firmware or restore earlier calibration values.

## Documentation

| Guide | Covers |
|---|---|
| [Configuration](config/README.md) | Macro settings, configuration preservation, backups and restoration |
| [Screen patches](client-preload/README.md) | Screen fixes, lighting and firmware compatibility |
| [Touchscreen in Fluidd](docs/touchscreen.md) | Opening or removing the browser panel |
| [Input shaping](klipper_backport/input_shaper/README.md) | Backport behaviour, compatibility and recalibration |
| [Vibration tools](utils/README.md) | Measuring resonance and choosing shaper settings |
| [OrcaSlicer options](docs/orca-print-dialog-integration.md) | Print-start bed leveling and timelapse |
| [Troubleshooting](docs/troubleshooting.md) | Recovering from an MCU reset failure |
| [Documentation index](docs/README.md) | Additional guides and technical records |

## Development

Run configuration validation and the local test suite:

```bash
uv run --with jinja2 python tools/validate_klipper_config.py
uv run --with pytest --with jinja2 --with unicorn --with capstone python -m pytest -q tests
```

Some tests need local vendor extracts or optional packages and skip without them.
Static checks do not establish physical motion safety; see the
[validation scope](config/README.md#configuration-validation).

Prebuilt screen binaries are included in the checkout and verified against their
source and installer files. Changes to those files require resealing the package
or rebuilding the screens; see the [packaging guide](docs/native-screen-packaging.md).

## License and disclaimer

Project-authored code and documentation use the
[GNU General Public License version 3](LICENSE), matching Klipper.
Files with their own license notices retain those terms. Vendor snapshots and
other third-party material retain their owners' terms.

Read [DISCLAIMER.md](DISCLAIMER.md) for warranty, safety, affiliation and
third-party-material notices.
