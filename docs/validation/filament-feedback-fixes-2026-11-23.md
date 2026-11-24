# Filament feedback: radio geometry, service temperatures and print startup

These local changes continue the solid-colour picker work in
`solid-colour-picker-2026-11-23.md`. No printer restart, installation, print start,
heater or motion command was issued during this work.

## Radio dot

LVGL positions children from the parent's content origin, which includes its
border. The radio ring has a three-pixel border: placing its 16-pixel dot at
8,8 inside a 32-pixel ring displaced the physical centre by three pixels in
both axes. The corrected child position is 5,5. The shared option-row component
covers calibration and other radio rows. The native test records border widths
and compares physical centres, including the border, rather than asserting the
implementation's position literal.

## Load/unload target

Standalone unload previously used a separate fixed table, including PETG at
235 C, instead of the configured profile target used by Load. The planner now
uses the material default or explicit profile nozzle temperature in either
direction. PETG defaults to 250 C; a configured 260 C profile also unloads at
260 C. Existing observed-identity ownership, profile bounds, configured heater
limits and tip-shaping movement classes remain enforced. Intentional
mixed-material Load transition temperatures retain their separate policy.
The retained console Load/Unload/Extrude/Retract wrappers use this same managed
service. openACE-owned service remains delegated to that backend.

Material validation: **1,677 passed**, with three pre-existing pytest warnings,
in 89.91 seconds. The suite covers observed unload identity, service admission,
heating/movement/write boundaries and profile limits. New PETG default/profile
cases verify the reported target inconsistency.

## Print-start progress and scan work

The active SD recovery scan previously ran before preparation progress existed.
It now publishes an attempt-bound Prepare print file phase with byte progress,
updated before cooperative reactor yields. The normal preparation Begin replaces
that phase. An old callback cannot change a new attempt; a changed SD handle
retires the display. No pending pre-SD submission borrows a previous job's
identity or Stop authority.

Ordinary G0/G1 and comment lines no longer undergo a second decode and tool-name
regex pass after ToolUsage has inspected them. Complete-file hashing, tool
selection handling, continuation handling, source/mapping rechecks and recovery
binding remain intact. Both active-SD and screen-submission scans log their byte
count, duration and reactor yield count once per completed scan. These timings
separate file scanning from the remaining startup work on a real printer.

Startup validation: **63 passed** in 1.21 seconds. This includes actual SD usage
binding, managed print admission, huge comment/movement continuations, prevention
of false tool requirements, progress publication before yielding, attempt
retirement and scan diagnostics. This is host evidence, not a measured reduction
in printer startup time. The pre-dispatch screen path still lacks an active SD
job during its scan; this change does not invent a cancellable job in that phase.

## Filament mini-view dropout

The main status poll obtains current telemetry, then optionally requests detailed
filament editor plans. Previously any optional-detail timeout, parse failure,
not-ready result or session/generation mismatch invalidated the whole successful
main observation. It also caused object rediscovery on the following poll.

Optional failures now discard only the enrichment. The UI keeps the successful
base observation at its original receive timestamp, marks details unready and
publishes no stale/mismatched procedure plans. Genuine main-query failures and
the original two-second expiry still invalidate status. A dedicated
`filament_detail_failures` diagnostic counter separates enrichment failures from
main status failures.

Native validation: **5 passed** in 61.11 seconds, including radio physical
centres, palette integration, factory-font fit and the polling regression.
Coverage includes session/generation mismatches, not-ready details, a delayed
failed request, original timestamp expiry, and successful details recovery.

The user reports the dropout on their printer and other users' printers, on
most starts. Read-only inspection found historical polling failures in multiple
stages and a 33.006-second maximum receive gap. Those records do not establish
which failure coincided with a reported print start. The enrichment bug is a
confirmed code defect; attributing every reported dropout to it still requires
an observed start with the separate counters/timings. No cache is relabelled
fresh and no freshness deadline is extended to conceal a dropout.

## Remaining qualification

- Touchscreen rendering/touch checks for the radio geometry and new palette.
- Supervised service check of the chosen PETG unload temperature.
- Actual screen and Orca starts: compare scan timings, status failure counters,
  optional-detail failure counter, mini-view continuity and preparation onset.
- Keep investigation open if dropouts persist or main-query deadlines increase.

ARM compilation and source/artifact binding are checked for the final local
candidate. No merge or push is part of this feedback work.

Final native candidate SHA256: `c2e28ff775b6ab61f59df0a8a366717dcf7a31e49853f16a80e346626af04d45`. The local installer package
was refreshed from this artifact; normal source/artifact binding checks passed.

The initial local-only status above is superseded by the final installation and
release qualification in `r4-backlog-release-2026-11-24.md`. The final picker has
60 RGB choices; `solid-colour-picker-2026-11-23.md` records its current design.
