# Documentation and message audit

The October 8, 2026 audit covered WM+-maintained documentation, command help,
installation/status output, printer-console messages, patch logs, and the touchscreen
browser panel. It included the pending firmware 1.1.13 work.

## Main changes

| Area | Result |
|---|---|
| Project README | Compatibility, connection settings, installation, and recovery limits come first |
| Configuration and patch guides | Explain what changes, what calibration is preserved, and how to check the result |
| Recovery guides | Explain the reference and checkpoint problem before implementation details; retain dated measurements and evidence paths |
| Firmware records | Separate the current upgrade requirement from historical deployments and test counts |
| Design and experiment records | Identify implemented, deferred, and removed proposals clearly |
| CLI help and installation errors | Use plain action names and give a next step when one is known |
| Printer messages | Improve WM+ errors and translate live macro descriptions; mark edits for baseline comparison |
| Touchscreen panel | Explain remote touch state and display rejected-request errors instead of reporting success |

The audit corrected several misleading statements: deferred chamber heating was
listed as active, touchscreen removal claimed to restore the whole printer to
stock, and old recovery sections still described checks that later trials completed.
Unload fallback documentation now matches the 225–235°C range in the code.

## Text that must stay exact

Vendor stock snapshots, third-party reference macros, and license text retain their
original wording. They are comparison/reference material rather than WM+ prose.

Some console output also serves as an input to the vendor screen. Binary inspection
found strings including `START_PRINT adaptive_mesh`, `START_PRINT default_mesh`,
`Z-axis is homing`, `Nozzle is cleaning`, `GET POSITON ERROR`, and the model-misalignment
warning. Those protocol-related messages retain their wording. Fixing a typo there
requires checking the matching screen parser, not just editing the displayed text.
Command names, API keys, saved-variable keys, patch profiles, and coordinates retain
their meanings.

## Checks

The project and material-helper suites passed 223 tests. Additional checks covered
local documentation links and anchors, Python/JavaScript/shell syntax, rendered
CLI help, and browser API success/error handling. No printer deployment or hardware
validation was performed during this audit.

## Writing future changes

Lead with the behavior a printer owner needs to understand. Explain a technical
term before relying on it. Put commands beside their prerequisites, and error
messages beside a useful next action. Keep current instructions separate from
historical evidence. Qualify test results by firmware, date, and whether they ran
locally or on the printer. Keep addresses and fingerprints in maintainer references.
