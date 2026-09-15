# Chamber-fan cooling experiment — removed

The chamber-fan cooling assistance was removed on 2026-09-14 at the user's
request because repeated nozzle cooldowns showed no benefit with the part
fan already at 100%.

Filament loading now cools at its existing purge position before wiping and
parking. Calibration wiping uses its original travel/wait sequence. Blob
cleaning uses its original front positions and vertical release lifts.
The temporary auxiliary-fan boost, fan-position moves, blob relocation and
presentation helpers, paused-load opt-in, and cancellation cleanup were removed.
Normal part-fan operation and manual chamber-fan control are unchanged.

The independent explicit cooldown waits (SET_HEATER_TEMPERATURE followed by
upper-only TEMPERATURE_WAIT), tool mapping, calibration clearance and idle-only
blob-cleaning guards remain. No touchscreen binary change was needed.

The previous implementation and validation notes are archived in
`analysis/cooling-assist-rollback-20260914T235728Z/`. The successful paused
Load/Resume tests demonstrated functional behavior, but the comparison below
did not justify the extra movement and fan use.

Rollback validation: 125 tests passed. The two changed config files were
deployed and Klipper returned Ready. Live config bytes match the sources,
the removed helpers are absent, and printer.cfg and saved_variables.cfg
match their pre-deployment backups. Heaters and cooling fans are off.

## Cooldown speed comparison — 2026-09-14

Six stationary cooldowns on physical T2 compared the part fan at 100% with
the part and auxiliary fans both at 100%, at logical X-13 Y160 Z60. Each run
used the same 225°C target and 60-second heat soak before switching the heater
off. Timing used interpolated downward nozzle-thermistor crossings from 220°C
to 140°C. Run order was part, both, both, part, part, both.

| Fans | Three cooldowns | Mean |
| --- | --- | --- |
| Part only | 44.14, 43.82, 44.00 s | 43.99 s |
| Part + auxiliary | 44.95, 44.40, 44.46 s | 44.60 s |

Adding the auxiliary fan did not accelerate cooldown in this setup; its mean
was 0.62 seconds (1.4%) longer. The 220→160°C means were also similar: 30.55
and 31.05 seconds respectively. Fan telemetry confirmed approximately 8,000
RPM for the part fan and 3,340 RPM for the auxiliary fan when enabled.
This does not establish a benefit for the added cooling move or auxiliary
fan, nor measure cooling of a filament blob or a different nozzle position.
The user requested removal of the cooling assistance after reviewing these results.

Raw samples, plots, protocol, measurement script and report are retained in
`analysis/cooldown-comparison-20260914T232945Z/`. The initial attempt to hold
within ±2°C was abandoned before measuring any cooldown because the heater
cycles around its target; the six reported runs all use the fixed soak.
The printer finished ready and idle, with heaters and both cooling fans off.
