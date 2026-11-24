# Smooth translucent swatch boundaries

The original checker implementation discarded any cell crossing a circular
boundary. That left a stepped, inset pattern. The correction fills the entire
swatch with checker cells and uses LVGL's rounded-corner clipping to draw the
partial cells at the edge. No whole-cell circle approximation remains.

The existing stock 1.1.13 API lv_obj_set_style_clip_corner is resolved and
profile-window guarded alongside the other native style functions. This adds
no function interception, status polling, or backend/motion changes.

Measured stock assets on the printer:

- Filament card image: 83x83 BGRA, nonzero alpha at (6,6)..(76,76); mask 71x71.
- Preview colour image: 50x50 BGRA, nonzero alpha at (5,5)..(44,44); mask 40x40.

Card and preview masks match those bounds. Home clips using its actual circle;
the editor clips to its existing rounded rectangle. Checker cells and masks
reuse the existing widget pools. Preview row retirement explicitly releases
its mask and children.

Host acceptance exercises complete rectangle coverage including edge cells,
rounded-clip style and radius, 100 stable updates without allocation, Standard
transition hiding, preview mask geometry, and cleanup after row deletion.
Live acceptance checks the smooth card boundary and preservation of the user's
current filament attributes without changing temperature or physical state.
Evidence and screenshots are kept in analysis/appearance-clip-live-20261124/.

No push, release tag or merge is implied by this local refinement.
