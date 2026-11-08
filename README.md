# Wondermaker+

Wondermaker+ (WM+) adds fixes and features to the Wondermaker U1 / ZR Ultra
(`TM-T1`). It runs alongside the stock firmware and keeps your printer's saved
calibration and hardware identifiers.

## What WM+ changes

### Fixes to stock behavior

- **Tool changes:** returns the new head to the saved print position after wiping,
  with a clearance lift. Restores the slicer's travel speed so later moves do not
  crawl at the wipe speed.
- **Pause and resume:** preserves the slicer-to-head mapping and restores nozzle
  temperatures to the correct physical heads. Parks farther from the front limit.
- **Print completion and cancellation:** lets SD prints reach EOF cleanly and
  clears native pause flags after cancellation, so the next print can start.
- **Duplicate filament loading:** removes the insertion sensor's extra load/purge
  sequence. Filament is loaded when you press **Load** on the screen.
- **Wi-Fi reconnection:** keeps retrying temporary connection failures instead of
  giving up. Wrong-password handling remains intact.
- **Filter-fan control:** stops repeated automatic On requests from overriding
  manual fan choices during a print.
- **Head-configuration loss:** blocks the screen app from erasing head identities
  and reducing the printer to one head after a communication timeout. Klipper
  stays stopped until the underlying fault is resolved.
- **Power-loss recovery:** restores the print's mesh, probing head and tool mapping;
  corrects saved coordinates so mesh/tool offsets are not applied twice; establishes
  Z at the bottom before tool pickup.

### Enhancements

- **Touchscreen in Fluidd:** view the physical screen live and send taps/swipes
  from your browser. Keeps timelapses pointed at the print camera.
- **Case-light control:** a saved On/Off preference shared by the screen, Fluidd
  and G-code. When enabled, the light stays on while the screen is awake, during
  printing/pauses, and for the screen-sleep delay after a print ends.
- **Print startup:** probes with the first printing head by default, avoiding
  unnecessary T0 changes. Purges along the plate's left edge, away from the front
  panel.
- **Filament unloading:** shapes the tip using material-specific temperatures and
  pull sequences to reduce blobs and strings. The optional material helper reads
  the screen's material settings.
- **Faster wiping:** adjustable wipe speed, defaulting to 200 mm/s versus the
  stock 50 mm/s.
- **Print end and cancel:** lowers the bed by up to 50 mm, limited by remaining
  travel, and wipes the nozzle.
- **Motion defaults:** caps acceleration at 5,000 mm/s² versus stock 20,000, and
  adds clearance for idle tool changes, filament service and calibration.
- **Vibration tools:** measure belt balance and resonance, compare input shapers,
  and verify the results during movement.

See the [configuration guide](config/README.md),
[screen-patch guide](client-preload/README.md), and
[vibration-tool guide](utils/README.md) for settings and implementation details.

## Compatibility

**Requires vendor System 1.1.13.** See the
[firmware notes](docs/firmware-1.1.13.md) and
[release instructions](docs/releases.md) for firmware compatibility and older versions.

## Install or update

Run these commands **on your computer**, from this checkout, with
[uv installed](https://docs.astral.sh/uv/getting-started/installation/).

Copy [.env.example](.env.example) to `.env` and set:

- `WMP_PRINTER`: printer hostname or IP, without `http://`.
- `WMP_USER`: printer SSH username.
- `WMP_PASS`: printer SSH password.

Git ignores `.env`; exported environment values override it. SSH uses your
known-hosts file. The example explains the optional first-connection trust setting.

While the printer is idle, check prerequisites, install, then check status:

```bash
uv run --with paramiko --with jinja2 python tools/deploy.py install all --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install all
uv run --with paramiko python tools/deploy.py status
```

All selected components must pass preflight before installation starts. The config
component backs up files it replaces and preserves printer-owned identifiers,
calibration and settings. A later installation failure can leave earlier changes applied.
Installation refuses running or paused prints. When `preload` is selected, config
and material uploads finish before the stock screen restarts. The installer
verifies the active head guard before continuing and before the final Klipper
restart. Screen-service restarts can also restart Klipper; `--no-restart` does
not prevent those service restarts.

Choose components instead of `all` if needed:

| Component | Provides |
|---|---|
| `config` | Printer macros, recovery helper and light controller |
| `preload` | Screen-app fixes, head-configuration protection and light-click integration |
| `material` | Screen material settings for the unload macros |
| `touchscreen` | Interactive Fluidd screen panel and timelapse-camera selection |

Install `config preload` together for the core features. `material` and
`touchscreen` are optional. Full installation needs SSH; `preload` and
`touchscreen` also need sudo. Reapply WM+ after vendor firmware updates.

For later config-only updates, with matching helpers already installed:

```bash
uv run --with jinja2 python tools/deploy.py install config --config-only
```

Use full installation when a helper changes. See the
[configuration guide](config/README.md#install-and-compare) for partial updates,
backups and restoring stock configuration, and the
[touchscreen guide](docs/touchscreen.md) for opening or removing the Fluidd panel.

## Development checks

```bash
uv run --with jinja2 python tools/validate_klipper_config.py
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

Some tests require local vendor extracts and skip when those files are absent.
Static validation cannot prove runtime-generated values or physical motion safe.
See [validation scope](config/README.md#configuration-validation) and the
[documentation index](docs/README.md) for the detailed guides and test records.

## License and disclaimer

Project-authored code and documentation use the
[GNU General Public License version 3](LICENSE), matching Klipper.
Files with their own license notices retain those terms. Vendor snapshots and
other third-party material retain their owners' terms; the project license does not
relicense that material.

Read [DISCLAIMER.md](DISCLAIMER.md) for warranty, safety, affiliation, and
third-party-material notices.
