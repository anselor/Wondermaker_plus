# Design ideas (documented, not yet implemented)

Status log for improvements we've analyzed but deliberately not built yet.
Context and evidence live in the 2026-08 tuning sessions; supporting
verification tooling: `utils/resonance.py`, `utils/config_sync.py`, and the
GET_POSITION checkpoint technique (see git history of `config/live/macros.cfg`).

---

## 1. Probe with the print's initial tool instead of T0

**Problem:** every print start grabs T0, heats it to 140, Z-homes and meshes
with it, cools it, parks it, then fetches the actual first tool — two extra
toolchanges and a wasted heat cycle (~2 min/print, plus dock and heater wear).

**Proposal:** probe with `INITIAL_TOOL`.
- `START_PRINT` records `probe_tool = INITIAL_TOOL` (saved variable) and
  heats that tool to 140 instead of T0.
- `Z_HOMING` grabs `T{probe_tool}` instead of the hardcoded `T0`.
- `_OFFSET_SET` applies `offset(tool) − offset(probe_tool)` instead of
  `offset(tool)`. With `probe_tool = 0` this is bit-for-bit stock behavior —
  the design's key safety property.
- `probe_tool` forced to 0 whenever the saved default mesh is loaded (datum
  consistency: the default mesh was probed with T0 via G29), and reset in
  `PRINT_END` / `CANCEL_PRINT`.

**Confidence assessment (2026-08-18):**
- ~85% the math works first try. Evidence: per-tool offsets verified exact
  and repeatable (±0.006 mm across dozens of instrumented toolchanges); the
  Z offsets were measured through the same load-cell probe the scheme uses,
  so no new systematic; the probe is bed-side and tool-agnostic; docking is
  positionally byte-clean on all four docks.
- ~70% no vendor-coupling surprise (`Z_HOMING`'s `_LEVELING_TRIGGER_S` /
  `STEPPER_DIAG_ENABLE` neighborhood — vendor code has repeatedly surprised).
- Failure mode is a visible first-layer error on opted-in prints, caught by
  supervision; not catastrophic.
- Known incompatibility: power-loss recovery re-homes with T0 and would mix
  datums mid-print — document, don't fix.

**Rollout plan:** implement behind a toggle (default off = stock). Verify
with (a) a supervised first layer on a print starting T2, (b) an
instrumented control print on T0 (must be identical to stock), (c) the
GET_POSITION checkpoint technique through the modified start.

---

## 2. Purge off the left bed edge instead of the front

**Problem:** the start purge line occupies the bed's front edge. Stock put
it at Y-1 where the toolhead shroud strikes the front panel (root cause of
the shifted-print saga); our fix moved it to Y2, which is safe but consumes
~2 mm of printable front Y and leaves a stripe on the plate.

**Proposal:** purge into the machine's existing left-side service area
(off-bed at negative X), like the vendor's own filament-load flow:
- `START_PRINT` purge becomes: move to ~X-13/Y80 (the exact spot
  `EXTRUDE_FILAMENT` already purges), extrude the priming volume, then
  `WIPE_NOZZLE` (X-13 column, strokes at Y240–275) to shear the blob, then
  proceed to print.
- Frees the entire bed front; eliminates front-geometry risk categorically;
  no purge stripe to peel; debris lands where the vendor's own load flow
  already drops it.

**Trade-offs:** loses the visual first-extrusion stripe and the bed-drag
tip clean — the wiper covers the latter; the former is a minor diagnostic.
Verify the X-13/Y80 area actually has clearance/waste handling for a
priming-line-sized purge (~20 mm of filament), not just load blobs, and
that the purge amount doesn't string across the bed corner en route to the
print's first move.

**Synergy:** combines naturally with idea 1 — the initial tool is already
mounted and hot; purge-left + wipe + straight to first layer is the minimal
possible start sequence (zero extra toolchanges, zero bed footprint).

**Rollout plan:** marked change to START_PRINT's purge block; verify with
one watched print (blob shears cleanly, no stringing to first layer, purge
volume adequate for good first-layer prime).
