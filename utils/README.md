# Measure vibration and tune input shaping

Input shaping adjusts motion to reduce ringing in printed surfaces. These tools
measure the printer's vibration, compare candidate settings, and check the settings
during real movement. Run them on your computer with the connection details from
the [project README](../README.md).

## Measure and report

```bash
uv run --with paramiko --with numpy python utils/resonance.py analysis
```

This homes the printer and runs four vibration sweeps, taking about eight minutes.
The report includes:

- **Belt balance:** compares the main peaks for the two CoreXY belt loops. A gap
  greater than 2 Hz is flagged. Frequency squared gives an estimate of relative
  tension; the result is a comparison, not a direct tension measurement.
- **Possible rattles:** compares vibration energy in the 60–80 Hz and 115–135 Hz
  bands with the main belt band. The warning thresholds are heuristics; inspect
  the mechanics before treating the result as a diagnosis.
- **Input-shaper fits:** lists predicted remaining vibration and acceleration
  limits for each shaper. The apply command chooses the least complex option
  below 0.5% predicted remaining vibration.

Measurements are saved under `resonance/<date>/`. To analyze saved CSV files
without connecting to the printer:

```bash
uv run --with paramiko --with numpy python utils/resonance.py analysis --offline resonance/2026-08-15
```

The tool downloads Klipper's analysis modules from the printer into ignored
`utils/.klippy_cache/`. Delete that cache to fetch them again.

## Preview and apply settings

```bash
uv run --with paramiko --with numpy python utils/resonance.py apply --dry-run
uv run --with paramiko --with numpy python utils/resonance.py apply
```

Apply backs up `printer.cfg` locally and on the printer, writes the chosen shapers,
restarts Klipper, and checks the loaded values. If Klipper does not return, it
restores the backup. `--accel N` also sets maximum acceleration in mm/s²;
`--yes` skips the confirmation prompt. Without `--accel`, the existing limit stays.

The vendor's touchscreen resonance calibration writes the same saved settings.
Running it later will replace your choices. Re-measure after mechanical changes
rather than copying another printer's shaper values.

## Verify during movement

```bash
uv run --with paramiko --with numpy --with matplotlib python utils/verify_shaper.py
```

This moves the printer through X, Y, diagonal, square, and triangle patterns,
comparing vibration with input shaping enabled and disabled at printing
accelerations. It helps answer whether a frequency-based fit also works during
these movements.

Results go to `resonance/<date>/movement-test/`:

| File | Contents |
|---|---|
| `report.txt` | Measurements and comparisons |
| `spectra.png` | Vibration by frequency for each pattern |
| `summary.png` | Vibration energy with shaping on and off |

A diagonal with unusually high vibration may indicate a rattle on that belt path.
Options include `--accels`, `--patterns`, `--vel`, `--cycles`, and `--out`;
use `--help` for their values. `--vel` is feedrate in mm/min.

The tool resets accelerometer recording before starting and retries short captures.
This avoids using an incomplete recording left by an earlier interrupted run.

## Observations from the test printer

The August 2026 tuning session found two independent, vertically stacked belt
loops with tensioners behind the rear panel. Over-tightening the lower-right
idler caused Y-homing error `ZRU-C002`. Adjusting one loop affected the other,
so both needed remeasurement after each change. Bare spool-holder spindles also
added a 60–80 Hz rattle; foam washers reduced it on that machine.

These observations may help an investigation, but they are not calibration values
or guaranteed causes for another printer. Disable motors before adjusting belts,
then move the head to let tension redistribute before measuring again.

## Configuration transfers

`utils/config_sync.py` compares, uploads, and downloads printer configuration.
It backs up replaced files and preserves machine-specific calibration.
See the [configuration guide](../config/README.md) for installation requirements
and commands.
