# utils/resonance.py

Reproducible resonance calibration for the U1, distilled from the 2026-08-15
tuning session. Two modes; both talk to the printer defined by
`WMP_PRINTER` / `WMP_USER` / `WMP_PASS` (same defaults as `tools/`).

```bash
# Measure and report (moves the machine: homes, then 4 shaking sweeps, ~8 min)
uv run --with paramiko --with numpy python utils/resonance.py analysis

# Re-analyze previously captured CSVs without touching the printer
uv run --with paramiko --with numpy python utils/resonance.py analysis --offline resonance/2026-08-15

# Preview what apply would change
uv run --with paramiko --with numpy python utils/resonance.py apply --dry-run

# Write best-fit shapers into printer.cfg (backs up, restarts, verifies, rolls
# back if Klipper does not come back). --accel N also sets [printer] max_accel.
uv run --with paramiko --with numpy python utils/resonance.py apply [--accel N] [--yes]
```

## What analysis reports

- **Belt balance** — main resonance peak of each CoreXY belt loop from the
  diagonal tests (`AXIS=1,1` excites one motor's loop, `AXIS=1,-1` the
  other). Flags a gap > 2 Hz; tension scales with frequency squared. On a
  well-tensioned machine the two peaks coincide.
- **Rattle check** — energy in the 60–80 Hz and 115–135 Hz bands relative to
  the belt fundamental. "Elevated"/"severe" flags mean something loose is
  ringing (heuristic thresholds 0.5x / 1.0x of the belt band).
- **Shaper fits** — Klipper's fits per axis with residual vibration and the
  accel ceiling each shaper supports. `apply` picks the lightest shaper
  under 0.5% residual.

Raw CSVs are archived under `resonance/<date>/`; every `apply` also drops a
timestamped `printer.cfg` backup there and on the printer.

## Hardware lessons (learned the hard way)

- The belts are two independent loops stacked vertically, each with its own
  motor and a screw-locked idler-on-a-track tensioner behind the rear panel
  (upper-left and lower-right).
- **Over-tightening the lower-right idler makes Y homing fail**
  (`ZRU-C002`). First home after a boot sometimes fails anyway; the script
  retries once.
- Tightening the upper-left idler can *decrease* overall tension and even
  the loops out — the loops couple through the shared carriage, so always
  re-measure both after any adjustment.
- Adjust tension only with motors disabled, and slide the head around
  afterwards so the loop redistributes before you judge the result.
- Bare spool-holder spindles rattle at 60–80 Hz and pollute every
  measurement (and every print). Foam washers fix it.
- **Do not run the vendor's built-in resonance calibration** — it rewrites
  the same SAVE_CONFIG values with its own (historically worse) picks.

`.klippy_cache/` holds Klipper's GPL analysis modules fetched from the
printer on first run; it is gitignored, delete it to refresh.
