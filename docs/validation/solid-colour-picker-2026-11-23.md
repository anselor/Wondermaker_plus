# Solid-colour filament picker

The stock picker offers five textured swatches that cannot be represented by the
current single-RGB filament identity field. WM+ now opens its own 48-colour solid
palette from direct standalone head edits and the shared standalone/openACE source
editor. The old stock constructor wrapper is removed. The verified stock palette
lookup remains for legacy colour callbacks and existing stock swatch rendering.

The palette includes neutrals, pastels, saturated and dark colours. Matching RGB
values receive an orange outline. An existing custom RGB value is preserved on
Cancel, whether or not the palette contains it. The title and Cancel action are
on one header row. No placeholder RGB value is invented for multicolour material.
Two/three-colour, rainbow and gradient appearances remain future model work.

Selection retains the caller's existing persistence rules. Direct standalone
head edits submit the typed settings receipt. Source editor selection updates the
filament draft and waits for Save. Cancel submits no settings change and preserves
a previously edited source draft. Picker events from hidden pages or obsolete
widgets do not dispatch selections; deletion of the parent retires the modal.

## Validation

Five focused tests passed in 69.87 seconds:

- Native LVGL lifecycle/integration: all 48 entries are unique valid RGB colours,
  are selectable, and fit a 640 x 360 content area; hidden-page events, Cancel,
  parent deletion, standalone typed save and openACE save/readback are covered.
- Actual factory-font header fit, including the new Filament colour header.
- Existing progress panel factory-font fit.
- Existing filament widget layout.
- Existing identity/source/revision preservation.

The font test caught and corrected a Cancel-caption font/height mismatch before
this validation passed. The standalone fixture explicitly enables identity
persistence and supplies a valid identity revision, as the real backend requires.

Native ARM compilation passed; the candidate/source binding check passed. Candidate
SHA256: `268c024df51e3fcacbbec4fe5be36f88d09e8a856e0a8530ba5dd0d9f1002b4f`. This work
has not been installed on the printer or published. On-device visual/touch review
remains outstanding. The earlier radio-centering and load/unload-temperature
changes in the working tree are separate feedback fixes; this validation does not
claim that the full four-item feedback batch is complete.

The initial palette-only candidate above is superseded by the combined feedback
candidate recorded in `filament-feedback-fixes-2026-11-23.md`.
