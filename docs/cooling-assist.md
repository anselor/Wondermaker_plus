# Cooling experiment: removed

WM+ no longer moves the nozzle to the auxiliary fan for cooling. On September 14,
2026, three measurements per condition found no speed benefit over the part fan
alone, so the extra movement and fan boost were removed.

Loading, calibration, and blob cleaning use their original cooling locations again.
Normal part-fan use and manual chamber-fan control remain. The separate cooldown
waits, tool mapping, calibration clearance, and idle-only blob-cleaning checks remain.

## Measurements

Physical T2 was held at 225°C for 60 seconds, then its heater was switched off.
All six runs were stationary at logical X-13 Y160 Z60. Timing used interpolated
nozzle-temperature crossings from 220°C down to 140°C. Run order was part, both,
both, part, part, both.

| Fans at 100% | Three cooldowns | Mean |
|---|---|---|
| Part fan | 44.14, 43.82, 44.00 s | 43.99 s |
| Part and auxiliary fans | 44.95, 44.40, 44.46 s | 44.60 s |

Both fans averaged 0.62 seconds (1.4%) longer. The 220–160°C interval was also
similar: 30.55 seconds with the part fan, 31.05 with both. Reported speeds were
about 8,000 RPM for the part fan and 3,340 RPM for the auxiliary fan.

This comparison does not measure blob cooling or other nozzle positions. Earlier
paused Load/Resume tests established that the detour worked, but did not show that
it improved cooling. An initial attempt to stabilize within ±2°C was abandoned
before cooldown measurement; all reported runs used the fixed heat soak.

## Removal and evidence

The removal deleted the fan-position moves, temporary boost, blob relocation,
presentation helpers, paused-load opt-in, and associated cancellation cleanup.
No touchscreen binary change was required.

The two changed configuration files were uploaded and Klipper returned to Ready.
Checks confirmed that live files matched the sources, removed helpers were absent,
and `printer.cfg` and saved variables matched the backups. Heaters and fans were
off. The local suite at that point passed 125 tests.

Local evidence, absent from a normal checkout:

- `analysis/cooldown-comparison-20260914T232945Z/`: samples, plots, protocol,
  measurement script, and report.
- `analysis/cooling-assist-rollback-20260914T235728Z/`: earlier implementation
  and removal checks.
