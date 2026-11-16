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
