# Development conventions

Keep factory source and macro changes small and attributable to a specific
compatibility fix. Put new WM+ features in separate modules so future firmware
updates can retain their structure.

Backend features under `klipper_extras/` compose their own command handlers and
state. `wm_material.py` is the material facade; `wmp_component.py` binds its
feature components. Calibration sub-features compose into `CalibrationCommands`
directly. Register installed helper modules in `tools/components/material.py`
(`HELPERS`) and native runtime dependencies in
`client-preload/unified-ui/native/runtime_inputs.py` (`RUNTIME_INPUTS`).

Native screens separate presentation from flow/status and worker logic where
those responsibilities exist. `runtime.hpp` wires the components;
`bootstrap.cpp` contains verified vendor hooks. Display helpers must not submit
printer commands or own a printer activity lock. Use `StockProgressPanel` for
numbered progress and `StockNotice` for confirmations. Use the profiled stock
fonts: Regular 22 for dialog body text, Bold 24 for dialog headings, and Bold 20
for compact header actions. Size captions using font line height; an enlarged
touch target need not enlarge its visible bar or text.

Regenerate `profile1113.hpp` and `profile1113.json` with `make_profile.py` against
the exact supported vendor client. Add symbols to the generator; never patch
only the generated header. Rebuild the native library once a coherent source
batch is ready, then export a matching package. Development exports default to
`packaging-control-only`; `--reviewed-release` is an explicit release decision,
not a way to make an integrity test pass.

Run `python -m pytest` from a prepared test environment to collect `tests/` and
`klipper_extras/`. The README gives the dependency command. ARM artifact tests
use the worktree's sealed package, not a shared `analysis/` development build.
Host UI tests model interactions and widget lifetime; actual font layout and
printer operation still require device verification.

## Shared progress and decisions

`StockProgressPanel::update` accepts `title`, `steps`, `heading`, `instruction`,
`note`, and `value`. Body text uses the stock 22 px font; heading/value use 24 px
bold. Put temperatures in `value` rather than concatenating them into the
instructions. Updates confined to a value with the same number of lines retain
all widget positions and decision targets. Callers must keep each value line
within the available width; real-font fit cases cover the current consumers.

The optional `note` is outside the scroll area, so a hot-nozzle caution remains
visible when instructions overflow. Overflow gets a visible scroll hint.
`content_fits()` is presentation information, never printer admission or a busy
flag. Test a consumer's normal text at its actual dimensions; scrolling is a
fallback for unusually long errors, not a substitute for fitting instructions.

`steps_width` and `title_width` reserve space for instructions and header actions.
For choices, set `decisions` and `choices_height`, and draw caller-owned controls
under the stable `choices_parent()`. `StockOptionRow` supplies full-row targets,
optional selection indicators, and consistent text/spacing. Its callback and
selected value belong to the consumer. USB file selection is a live consumer;
the scrub presentation contract covers two radio rows without importing motion.

Use `stock_header_action` for compact header buttons. Pass a separate touch
height when needed, retaining the 40 px visible bar and its font-sized caption.
Register actions in the owning screen; the helper dispatches no printer work.

`test_progress_panel_real_font_fit` executes the pinned factory LVGL
`lv_txt_get_size` under ARM emulation, including the client's glyph data,
kerning and wrapping. The C++ harness uses those measurements for auto-height
labels, then verifies final bounds, pinned cautions and control sizes. It does
not replace device testing of touch, theme or printer motion.

A finished operation result has one exit: DONE for success, CLOSE for failure.
Do not leave disabled action buttons or a second equivalent exit on that view.
A Progress shortcut is for ongoing work; Recover is for an interrupted operation
that can need explicit repair. Completed results do not need a Result shortcut.
