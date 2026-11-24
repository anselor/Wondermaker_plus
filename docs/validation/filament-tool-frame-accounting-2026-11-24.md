# Filament usage across tool frames — 2026-11-24

The retained factory 1.1.13 `PrintStats` subtracts a single `last_epos` from
`gcode_move.position.e`. Each physical extruder has its own E position. A switch
from outgoing E361 to incoming E0 can therefore change reported usage from
11 mm to -350 mm without an extrusion or retraction.

The correction observes the registered, retained `ACTIVATE_EXTRUDER` handlers:

1. During an active, unpaused print, sample outgoing usage with the stock
   `_update_filament_usage` implementation.
2. Call the original activation handler unchanged. It retains its existing
   step-generation flush, tool selection and `extruder:activate_extruder` event.
3. Rebase `last_epos` after `gcode_move` adopts the incoming frame.

Already-active and failed activations preserve stock behavior and exceptions.
Paused/idle service extrusion is excluded; stock resume rebases as before.
Restored PLR totals are not replaced. Stock flow-factor and net-retraction
semantics remain intact: this does not clamp counters or discard negative
physical extrusion. Custom activation owners are left unchanged. Installation
is idempotent, and the helper is included in material install/remove inventory.

There are no new timers, polling requests, per-line dispatcher hooks, movement
commands, waits, PA changes, shaper changes or MCU scheduling changes. This is
an accounting fix, not a proposed fix for the unresolved physical extrusion
or stutter investigations.

Six local tests execute retained stock statistics and activation code. They
cover the unmodified failure, repeated switches without status polls, stock
flush count, pause/service/resume, restored totals, flow factors, retractions,
already-active selection, reset, activation errors and custom-owner refusal.
Live acceptance passed on `TFT 2026 Vehicles Orca_ZRU_PLA_9h0m.gcode`,
with its existing identity mapping and unmodified G-code. Black used Head3;
red used Head1. At the change, the outgoing E coordinate was 336.48309 mm and
the incoming coordinate was 0. Reported usage stayed at 336.48309 mm (delta
0), then increased with red extrusion. Final reported usage was 365.16270 mm,
matching 336.48309 + the incoming head's 28.67961 mm to within 0.001 mm.

The temporary monitor sampled lightweight status, with no per-line G-code
logging or file modification. It cancelled after a short first-layer red
section. The cancellation receipt completed, all heater targets reached zero,
and the printer remained Ready. Head1 remained attached and parked beside the
scrubber; physical Z was 125 mm. User tuning and filament identities were
unchanged. Evidence: `analysis/progress-final-live-20261124/`.

This qualifies the counter correction; it does not resolve the independent
extrusion-timing/stutter investigations.
