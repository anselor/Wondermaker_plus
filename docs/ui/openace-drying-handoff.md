# openACE hand-off: per-unit ACE environment and drying

Operator-approved requirement (1 November): each ACE unit has independent target
temperature and duration, Start/Stop, and live humidity/current temperature.
Use a sun icon: orange means confirmed enabled/drying, gray means confirmed off.
Unknown or stale status must be explicit, never presented as confirmed off.
This applies to each unit independently of slot-to-head assignments.

## Current boundary

WM+ has a per-unit native dialog stub. Its humidity/temperature are unavailable,
Start/Stop and target/duration controls are disabled, and it sends no dryer
commands. The neutral sun plus question mark indicates unknown status.

The inspected openACE checkout has low-level `drying` and `drying_stop` codecs
(`openace/protocol/v2.py`), a hardware `UnitCapabilities.dryer` declaration,
and drying among configuration methods in `openace/drivers/runtime.py`.
These are not a public operator-control contract. `docs/roadmap.md`, Supported
drying control, explicitly identifies that gap. The public `_device_status`
path in `klipper/extras/openace.py` and unit `describe()` in
`klipper/extras/openace_runtime.py` do not publish the required environmental
readings or dryer state. WM+ must not bypass the coordinator to call codecs.

## Backend contract needed

- Per registered unit: humidity percent, actual chamber temperature in C,
  confirmed dryer enabled/running state, target temperature, requested duration,
  and remaining time where available. Use null/unavailable for unsupported data.
- Identify hardware capability separately from currently permissible actions.
  Publish validated temperature/duration limits and units; WM+ must not invent
  limits or assume all ACE generations have identical support.
- Include connection/session identity and observation freshness so a stale
  reading or replaced/reconnected device cannot look like confirmed running/off.
- Provide supported per-unit start and stop operations with request identity,
  explicit accepted/refused/outcome state, and status readback. A submitted
  request alone must not change the icon to orange or gray.
- Backend owns interlocks with printing, active slot operations, disconnects,
  faults, and drying completion. Stop must remain available according to its
  own backend policy, rather than being blindly gated by the start policy.
- Drying must not implicitly roll spools or retract filament. Existing codec
  work and `docs/analysis/2026-10-27-drying-motion-policy.md` require review by the
  openACE owner before exposing a product-level control.

Command names and status schema remain to be agreed with openACE; no proposed
name in this document should be treated as an implemented API. Once supported,
WM+ can bind the existing per-unit entry/dialog, keypad fields and icon colours
to that contract and validate readback on real hardware.
