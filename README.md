# Wondermaker+

Wondermaker+ (WM+) adds printer fixes, better tool changes, and remote touchscreen
control to the Wondermaker U1 / ZR Ultra (`TM-T1`). You can install its components
separately.

The current configuration requires **Wondermaker System 1.1.13**. Local tests
cover this release. The configuration and existing patches were installed on
2026-10-10 and verified with Klipper Ready and four heads; printing and calibration
acceptance remain pending. Earlier releases completed two-color prints and
power-loss recovery tests.
See the [1.1.13 notes](docs/firmware-1.1.13.md) for the changes and remaining checks.

## What you can install

| Component | What it does | Installation needs |
|---|---|---|
| `config` | Improves startup, tool changes, filament handling, and recovery; preserves your printer's calibration | SSH login; later config-only updates can use HTTP |
| `touchscreen` | Shows the printer's screen in Fluidd and lets you click it | SSH login with sudo |
| `material` | Reads the screen's material settings to choose a filament-unload sequence | SSH login |
| `preload` | Fixes touchscreen Wi-Fi, fan requests, recovery, and openACE compatibility; blocks destructive head resets after communication faults | SSH login with sudo |

SSH is the printer's remote shell connection. Sudo allows changes to system files.
Moonraker is the printer's HTTP API; Fluidd is its browser interface. The commands
below run on your computer, using `uv` to provide Python dependencies.

## Connect to your printer

Copy [.env.example](.env.example) to `.env` and fill in:

- `WMP_PRINTER`: printer address or hostname, without `http://`.
- `WMP_USER`: SSH username.
- `WMP_PASS`: SSH password.

Git ignores `.env`. Values you export in your shell override the file.
SSH checks the printer's host key against your known-hosts file. Verify the
printer's key before adding it. `WMP_SSH_AUTO_ADD=1` accepts the first key offered
by that address; use it only if that is how you want to establish trust.

List components or compare your printer's configuration with the repository:

```bash
uv run python tools/deploy.py list
uv run python tools/deploy.py status config --diff
```

## Install or update

Install **vendor firmware 1.1.13 first**. WM+ does not install vendor firmware.
Use the published `fw-1.1.13-r2` tag for this firmware; `fw-1.1.12-r1` remains
available for vendor firmware 1.1.12.
After a firmware update, reapply WM+ configuration and touchscreen patches
before printing.

If a print is waiting for power-loss recovery, read the
[recovery upgrade limits](client-preload/README.md#upgrading-with-an-interrupted-print)
before updating. An older checkpoint may lack the information needed to resume.

Run installation checks without replacing installed files or restarting services:

```bash
uv run --with paramiko python tools/deploy.py install all --preflight-only
```

Then install all components, or choose the ones you need:

```bash
uv run --with paramiko python tools/deploy.py install all
uv run --with paramiko python tools/deploy.py install config preload
uv run --with paramiko python tools/deploy.py install touchscreen
uv run --with paramiko python tools/deploy.py install material
```

Each installation checks every selected component before applying changes. Checks
cover access permissions, required files, configuration syntax, the web server,
and whether the touchscreen patches support the installed client. They use
temporary files on the printer for compilation and web-server checks.

A failed check stops installation before any component is installed. If a failure
occurs during installation, earlier changes may already be applied; they are not
automatically undone. The tool also refuses changes during a running or paused
print, or when it cannot determine the printer's state.

Klipper restarts once after the selected components finish when needed. Use
`--no-restart` to defer that restart. Touchscreen components still restart their
own services during installation.

For later configuration updates, you can use HTTP without SSH:

```bash
uv run python tools/deploy.py install config --config-only
uv run python tools/deploy.py install config --config-only --files macros.cfg
```

This requires the matching `wmp_recovery.py` helper to be installed already.
Run the full `install config` again whenever that helper changes or a firmware
update removes it. The HTTP check confirms the helper's expected status fields;
it cannot inspect the installed Python source.

Check installation or remove an optional component:

```bash
uv run --with paramiko python tools/deploy.py status
uv run --with paramiko python tools/deploy.py uninstall touchscreen
```

Configuration has no automatic uninstall. See the
[configuration guide](config/README.md) before restoring a vendor baseline.

## Printer improvements

The [configuration guide](config/README.md) explains each change and its settings.
The main improvements are:

- **Print startup:** purge along the plate's left edge and, by default, probe with
  the first tool that will print. This can avoid extra tool changes.
- **Tool changes:** wipe the new nozzle, return to the print position with a
  clearance lift, and preserve the slicer's travel speed.
- **Pause and resume:** preserve the mapping between slicer tools and physical
  heads, including intentional remapping while paused.
- **Filament handling:** shape the filament tip during unload, move clear of the
  bed for loading, and avoid the screen's duplicate load/purge sequence.
- **Print end:** lower the bed by up to 50 mm and wipe the nozzle.
- **Power-loss recovery:** establish Z at the bottom before pickup, restore the
  print's bed mesh and tool mapping, and save coordinates without applying mesh
  and tool corrections twice. Requires both `config` and `preload`.

Recovery still uses the vendor's return path with only 3 mm above the saved Z.
It can hit taller objects along that path. Checkpoints also retain the vendor's
sampling and selection limits. Read the [recovery guide](docs/print-mesh-recovery.md)
before relying on recovery for a particular print.

## Touchscreen and calibration tools

The [touchscreen guide](docs/touchscreen.md) covers the clickable panel in Fluidd.
The [touchscreen patch guide](client-preload/README.md) explains the Wi-Fi, fan,
recovery, and openACE fixes. These patches change the running process; they leave
the vendor executable on disk unchanged.

The [resonance tools](utils/README.md) measure vibration, compare belt responses,
and help choose input-shaper settings to reduce ringing. They save measurements
and graphs so you can compare changes. Your own calibration stays on your printer.

The [OrcaSlicer guide](docs/orca-print-dialog-integration.md) explains the print-start
bed-leveling and timelapse options. The [documentation index](docs/README.md) also
links firmware comparisons, test records, and earlier design decisions.

## Local validation

```bash
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

Tests cover macro sequences, recovery checks, configuration migration, and
compiled touchscreen patches. Some checks require extracted vendor files in
ignored `analysis/` directories and skip when those files are absent. Local tests
do not measure physical clearance, heating, or stopping performance.

## Repository layout

| Path | Contents |
|---|---|
| `config/` | Current WM+ configuration, vendor baselines, and configuration guide |
| `device/`, `scripts/` | Touchscreen bridge and printer-side installation scripts |
| `tools/` | Installation, comparison, and remote-control tools |
| `utils/` | Resonance measurements and configuration transfers |
| `client-preload/`, `klipper_extras/` | Touchscreen patches and Klipper extensions |
| `tests/`, `docs/` | Local checks, guides, and investigation records |
| `analysis/` | Local firmware extracts and evidence; ignored by Git |

## License and disclaimer

Project-authored code and documentation use the
[GNU General Public License version 3](LICENSE), matching Klipper.
Files with their own license notices retain those terms. Vendor snapshots and
other third-party material retain their owners' terms; the project license does not
relicense that material.

Read [DISCLAIMER.md](DISCLAIMER.md) for warranty, safety, affiliation, and
third-party-material notices.

## Firmware release tags

Use a firmware-specific tag for repeatable installation: `fw-<version>-r<revision>`.
The first 1.1.12 hotfix is **`fw-1.1.12-r1`**. Its complete configuration targets
System 1.1.12; later firmware configurations will have their own tags. See
[release compatibility and upgrade commands](docs/releases.md).
