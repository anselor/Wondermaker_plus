# Early print-file preparation progress

## What the live observation established

The Vehicles file was `TFT 2026 Vehicles Orca_ZRU_PLA_9h0m.gcode`,
60,414,444 bytes. It was selected through the real touchscreen preview. Both
sliced colours were temporarily mapped to the only loaded source, Head 1.
Original physical and backup mappings were restored afterward. No candidate
software was installed and Klipper was not restarted for these observations.

Printer-side timestamps show two different confirmed start requests:

| Request | Request time (printer epoch) | SD file opened | Interval |
| --- | --- | --- | --- |
| `print_1` | 1795483649.185477 | 1795483706.5522425 | 57.367 s |
| `print_2` | 1795483751.8915684 | 1795483804.8749065 | 52.983 s |

These are request-to-open intervals, not a profiler attribution of every second
to file parsing. The user confirmed explicitly starting the second run; this is
not evidence of a cancelled job spontaneously restarting. The user observed that
the filament mini-panel did not show its earlier error during these starts, while
the lengthy wait with little progress remained apparent.

The first cancellation stopped before Y homing. The second execution was
cancelled during mesh probing, with 8 of 35 points measured. Both used existing
installed cancellation behavior. Final inspection verified an inactive SD job,
completed cancellation, zero heater targets and zero recorded filament use.
Head 1 remained attached; no additional motion was commanded to restore it.

The local capture/guard process unexpectedly exited with status 143 during the
long wait for confirmation/startup. Consequently the promised automatic
pre-homing cancellation was **not qualified**; the test did not remain within
that boundary. The second execution was explicitly stopped once discovered.
Do not count either run as a passed automated pre-homing guard test.

An earlier 30-second dwell file was inadequate startup coverage: it omitted
START_PRINT and the file-preparation work. Its natural completion also triggered
the installed normal PRINT_END park, despite the file itself containing no moves.

Private evidence is under
`analysis/vehicles-screen-start-20261123-202447-853b02/`, including captured frames,
status events, original/restored mappings and printer command-store timestamps.
The shorter baseline is under `analysis/cold-start-watch-20261123-201709-f4e95e/`.

## Local implementation

- The touchscreen leaves preview for Home when a standalone start is queued,
  preserving the in-flight receipt. Navigation does not submit another start.
- Backend admission publishes **Preparing print / Read/process G-code** before
  its full-file scan. Byte progress is updated at cooperative yields. The phase
  binds the exact pending submission, rather than an old print_stats filename.
- The display transfers to the actual opened SD handle and normal preparation
  without losing its attempt identity. The file-processing step stays in the
  completed list. Replacing the SD handle retires the old display.
- A fresh, matching backend `pending` result remains positive evidence during a
  long scan. It no longer becomes unknown after ten polls or resends a start.
- Stop during this pre-SD phase has a reviewed token binding the start ID,
  submission object, session, generation and previous idle SD context. Changed,
  expired, replaced, replayed or cross-owner reviews are refused.
- Pending Stop retires dispatch generation before acknowledging completion.
  No SD execution or physical work has been dispatched in this phase. The
  existing cancellation record stores the completed data-only stop; it does not
  introduce an unresolved physical-cleanup state across restart.
- Ordinary CANCEL_PRINT ingress also retires a current pending standalone start.
  Existing active-job cancellation retains its separate exact SD-handle binding.
- Both pending and active SD scans check the generation at cooperative yields
  and before final scan publication. Obsolete work cannot open SD or publish a
  completed usage proof after a Stop.

This covers the long screen-submission phase as well as the active-SD scan
already addressed in the preceding feedback commit. It does not infer that all
reported filament dropouts have the same cause, and does not extend freshness
or label cached telemetry as current.

## Qualification boundary

Host tests cover pending Stop, real cooperative scan interruption, review drift,
replay and durable receipt restoration, immediate Home handoff without duplicate
submission, forty consecutive matched-pending observations, and factory-font
fit for file processing and the seven-step continuation. The matching ARM
artifact and installer package are rebuilt and checked locally.

The new early progress and pre-SD Stop path still require an explicitly scoped
on-printer check. No further print was started after the observed second run was
stopped. No merge or push is authorized by this work.


Final local validation:

- Broader material/admission/cancellation batch: 1,751 passed (three pre-existing
  pytest warnings). Final focused preparation/scan/cancel batch: 79 passed.
- Native lifecycle, early navigation, cancellation worker, admission transport
  and factory-font layout: five passed.
- Matching screen package: seven checks passed; source/artifact binding current.
- ARM candidate SHA256:
  `5905e3ca6aff86361d7ef96241fd6fbea6cfcb4f253c1efba20d1e8452a316c7`.

These test groups overlap and are not an aggregate unique-test count. The
candidate is local and has not been installed on the printer.
