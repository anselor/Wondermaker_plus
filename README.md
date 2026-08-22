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
uv run --with paramiko python tools/deploy.py install
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

The config is tracked as a stock baseline versus a live copy, with every
change marked in-line. Deploy it with **`utils/config_sync.py`**, which
pushes changes to the printer over Moonraker's HTTP API (no SSH needed),
backs up each file it replaces, restarts Klipper, and preserves every
machine-specific calibration — bed mesh, input shapers, probe offsets, CAN
bus IDs, and tool offsets are never overwritten.

```bash
uv run python utils/config_sync.py diff   # what differs from the printer
uv run python utils/config_sync.py push   # deploy changes
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

## Also here

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
