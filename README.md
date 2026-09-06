# Wondermaker+

Enhancements for the Wondermaker U1 / ZR Ultra (`TM-T1`) toolchanger — a
CoreXY printer running Klipper, Moonraker, and Fluidd on a Rockchip RK3308.

Three independent parts. Use any of them on their own:

1. **Fluidd touchscreen integration** — the printer's LCD, live and clickable, inside Fluidd.
2. **Printer config and macro improvements** — fixes and upgrades over the stock Klipper config.
3. **Resonance testing and analysis** — command-line tools to measure ringing and set input shapers.

## Fluidd touchscreen integration

Mirrors the physical touchscreen into Fluidd as a live panel you can click
with a mouse from anywhere on the network. Installs cleanly and uninstalls
completely, and includes a fix so timelapses record the print rather than the
LCD.

```bash
uv run --with paramiko python tools/deploy.py install touchscreen
```

Full details: [`docs/touchscreen.md`](docs/touchscreen.md).

## Printer config and macro improvements

A curated set of Klipper config and macro changes over the stock firmware.
Highlights:

- **Left-edge purge** — the start purge runs off the printable area instead of
  the bed front, avoiding a toolhead-vs-panel strike and freeing bed space.
- **Correct filament on resume** — pausing and resuming (including from Fluidd)
  keeps the right tool-to-slot mapping instead of loading the wrong color.
- **Safer pausing** — the paused park position has real clearance from the
  frame, and a `REHOME` command is available for deliberate re-homes.
- **Faster, cleaner toolchanges** — travel speed is preserved across a
  toolchange (no more slow crawls), the nozzle wipe is quicker and tunable, and
  a freshly picked-up tool is wiped before printing.
- **Tuned motion** — acceleration is capped to what the machine can print
  without ringing, with input-shaper values to match.
- **Adopted upstream fixes** — chamber-temperature support, a guarded
  print-end sequence, and the vendor's toolhead-swap and runout improvements.
- **Clean filament unload** — tip-shaping unload sequences ported from the
  Snapmaker U1 (PLA/ABS/TPU) and Prusa MMU3 profiles (PETG), selected by
  material with per-material unload temperatures, then cool and wipe.
  Material comes from the optional `wm_material` Klipper extra
  (`klipper_extras/`, reads the touchscreen's slot settings; SSH install) or,
  without it, from the hotend temperature.
- **Single-purge load** — loading from the screen no longer purges, docks,
  undocks and purges again.
- **Wi-Fi stays connected** — the touchscreen client tells wpa_supplicant to
  stop reconnecting after one failed reconnect, leaving the printer offline
  until the Wi-Fi page is opened. `client-preload/wifi-fix` patches that out
  in memory (`tools/deploy.py install preload`, SSH).
- **Home with the first tool** (off by default) — `START_PRINT` can Z-home and
  mesh with the print's first tool instead of always fetching T0, with tool
  offsets applied relative to it. `PROBE_WITH_INITIAL_TOOL ENABLE=1`.

The config is tracked as a stock baseline versus a live copy, with every
change marked in-line. Deploy it with `tools/deploy.py install config` (or
`utils/config_sync.py` directly): Moonraker HTTP, no SSH; backs up each
replaced file, restarts Klipper, and never overwrites machine calibration
(bed mesh, input shapers, probe offsets, CAN bus IDs, tool offsets).

```bash
uv run python tools/deploy.py status config    # what differs from the printer
uv run python tools/deploy.py install config   # deploy changes
```

Full details, deployment, and the list of changes: [`config/README.md`](config/README.md).

## Resonance testing and analysis

Command-line replacements for the touchscreen's built-in calibration, with
saved data and graphs:

- **`utils/resonance.py`** — runs the accelerometer sweeps, reports belt
  balance, rattle bands, and per-axis shaper fits, and can apply the best
  shaper to the printer (with backup and verification).
- **`utils/verify_shaper.py`** — drives real movement patterns with the shaper
  active and measures the ringing that actually reaches the part, so you can
  confirm a calibration and spot direction-specific mechanical problems.

Full details: [`utils/README.md`](utils/README.md). (Config deployment lives
with the config area above, under `utils/config_sync.py`.)

## Deploying

`tools/deploy.py` installs, removes, and reports each component:

| component | what | needs |
|---|---|---|
| `config` | Klipper config from `config/live` (`utils/config_sync.py`) | Moonraker HTTP only — works on a stock printer |
| `touchscreen` | camera snapshot service, nginx page, timelapse-camera fixer | SSH login + sudo |
| `material` | `wm_material` Klipper extra (material-aware unload) | SSH login |
| `preload` | LD_PRELOAD patches for the touchscreen client (`client-preload/`): Wi-Fi reconnect fix | SSH login + sudo |

```bash
uv run python tools/deploy.py install config                      # no SSH
uv run --with paramiko python tools/deploy.py install all
uv run --with paramiko python tools/deploy.py install material
uv run --with paramiko python tools/deploy.py status
uv run python tools/deploy.py list
```

Klipper is restarted once at the end when needed (`--no-restart` to skip).
Refuses to run during a print. Credentials: `WMP_PRINTER`, `WMP_USER`,
`WMP_PASS`. New components: add a module with `install/uninstall/status` to
`tools/components/` and register it in `components/__init__.py`.



- [`docs/orca-print-dialog-integration.md`](docs/orca-print-dialog-integration.md)
  — how to drive the timelapse and bed-leveling toggles from OrcaSlicer.
- `analysis/` — firmware-format notes and tooling.

## Connecting to the printer

The tools default to `t13dp@printer.local`. Override with the environment
variables `WMP_PRINTER`, `WMP_USER`, and `WMP_PASS`.

## Repo layout

| path | contents |
|---|---|
| `device/`, `tools/`, `scripts/` | touchscreen bridge code, host tools, install scripts |
| `config/` | stock vs live Klipper config, and the deploy tool |
| `utils/` | resonance, verification, and config-sync utilities |
| `docs/` | touchscreen, OrcaSlicer, and design notes |
| `analysis/` | firmware analysis |
