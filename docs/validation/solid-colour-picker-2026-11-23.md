# Solid-colour filament picker

The stock picker offers five textured swatches that cannot be represented by the
current single-RGB filament identity field. WM+ opens its own RGB picker from
standalone head edits and the shared standalone/openACE source editor. The
verified stock palette lookup remains for legacy callbacks and stock rendering.
Two/three-colour, rainbow and gradient appearances remain future model work.

## Final layout

The user selected a colour-family-and-shade design with larger touch targets.
The two family rows are:

| Neutral | Brown / beige | Red | Orange | Yellow |
| --- | --- | --- | --- | --- |
| Green | Teal | Blue | Violet | Pink / magenta |

Every family has six shades, for 60 unique RGB choices. Red includes deep
burgundy and Blue includes dark navy. Violet runs from pale lilac to deep
purple; Pink / magenta runs from pale rose to dark magenta. All 48 choices from
the preceding family picker remain available.

A family tap updates the shade row without saving. A matching existing colour
opens its family and receives an orange outline. Shade targets are at least
90 by 52 pixels at the tested 640 by 360 content size, and larger on the normal
screen. Brown / beige and Pink / magenta captions use two lines. Cancel uses the
shared borderless stock_header_action helper in the title row.

Selection retains the caller's existing persistence rules. Direct standalone
head edits submit the typed settings receipt. Source-editor selection updates
the filament draft and waits for Save. Cancel submits no settings change and
preserves arbitrary custom RGB values and previously edited source drafts.
Events from hidden pages or obsolete widgets do not dispatch selections;
deletion of the parent retires the picker.

## Validation and installation

- Final native lifecycle/integration and factory-font header checks: **2 passed**.
  All 60 entries are unique valid RGB colours, selectable, and fit the smallest
  tested content area with exactly six visible shade targets per family.
  Coverage includes family navigation without a save, violet/magenta separation,
  transparent borderless Cancel, hidden-page events, parent deletion, standalone
  typed settings and openACE save/readback.
- Family captions were separately measured with the exact factory font at the
  minimum supported width, including border/content allowances.
- Final sealed-package checks: **7 passed**. ARM compilation and source/artifact
  binding passed. These checks overlap with the release suite; their counts
  are not an aggregate unique-test count.
- Final candidate SHA256:
  `d23fb96bea5346cbcf66119c08ed0b3c0cbefd03f94fa9b81f93ed10a2ff4129`.
- Installation verified the loaded package, GUI/status synchronization and
  Klipper Ready (PID 130877), with zero configuration file changes.
- Live screens confirmed the ten-family layout, standard Cancel and six shades
  in Yellow, Red and Blue, including burgundy and navy. Earlier live checks
  covered Violet/Pink family navigation and Cancel without saving. The user
  approved the final appearance. No colour was selected or saved by these checks.

Private screenshot evidence: analysis/picker-sixty-live-20261124/ and the earlier
picker-ten-live-20261124/ directory. Logs: /tmp/wmp-picker-sixty-tests.log,
/tmp/wmp-picker-sixty-package-tests.log and /tmp/wmp-picker-sixty-install.log.
