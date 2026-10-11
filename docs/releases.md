# Firmware release tags

A tag identifies a complete WM+ snapshot for a specific vendor firmware:

```text
fw-<vendor-version>-r<WM+-revision>
fw-1.1.12-r1
fw-1.1.12-r2
fw-1.1.13-r1
```

Revisions start at 1 for each firmware and increase for fixes or improvements.
Published tags are immutable. A candidate uses `-rc1`, `-rc2`, etc., for example
`fw-1.1.13-r1-rc1`; mark candidate releases as prereleases. The firmware part
states the full configuration's target, not a claim that every individual
component only works on that firmware. Release notes identify any broader
component support and distinguish local tests from printer validation.

Do not assume the moving `main` branch supports your installed firmware.
Choose the corresponding tag and keep local connection details in ignored `.env`.

## fw-1.1.12-r1 — touchscreen rendering fix

This release fixes a blank interactive touchscreen when JPEG snapshots and touch
input still work. The binary frame header puts BGRA pixels at a byte offset that
is not aligned for JavaScript `Uint32Array`. The renderer now uses `DataView` with
explicit little-endian reads. Frame-decoding errors also appear in the browser
console and panel instead of being silently discarded.

The regression test runs the actual JavaScript renderer against full and changed-row
packets encoded by the Python bridge, checking both colors and frame updates.
All 173 tests in this release snapshot passed locally, including the browser
regression and material-helper suites. Confirmation on the reporting printer is pending.
The printer configuration and preload patch behavior are unchanged in this hotfix.

| Component | Compatibility in this snapshot |
|---|---|
| Full printer configuration | System 1.1.12 |
| Touchscreen | Compatible with the existing 1.1.12 screen bridge; no new vendor module required |
| Fan, recovery, and openACE preloads | Reviewed clients 1.1.08 and 1.1.12 |
| Wi-Fi preload | Reviewed clients 1.1.04, 1.1.08, and 1.1.12 |

### Update only the touchscreen on 1.1.12

From an existing WM+ checkout with a clean working tree, run:

```bash
git fetch origin --tags
git switch --detach fw-1.1.12-r1
uv run --with paramiko python tools/deploy.py install touchscreen
```

Run installation while the printer is idle. This command updates the screen bridge,
web page, nginx integration, and webcam registration. It does not upload printer
configuration or preload libraries. Afterwards, hard-refresh the screen page or
close and reopen the Fluidd camera iframe to discard the cached JavaScript.

First-time users can check out this same tag and follow the main README for a
full installation on vendor firmware 1.1.12. This release does not contain the
pending 1.1.13 configuration or installer-preflight changes.

## fw-1.1.13-r1 — firmware support and head-configuration protection

The full configuration targets **vendor System 1.1.13**. Install that vendor
firmware first; this release requires its collision-detection and calibration
modules. For vendor 1.1.12, keep using `fw-1.1.12-r1`.

This release:

- Incorporates vendor 1.1.13 calibration collision monitoring while retaining
  WM+ clearance moves, and adds verified 1.1.13 profiles to the client patches.
- Blocks the vendor client's destructive automatic head reset after communication
  timeouts. Klipper remains stopped; fix the fault and recover manually. This
  does not repair USB/CAN faults or protect every vendor discovery/installer path.
- Validates all selected components before installation, including required
  helpers, effective configuration includes, nginx, and native binary guards.
  Failed preflight installs nothing; later runtime failures do not automatically
  undo earlier changes. Running and paused prints block installation.
- Includes the previously unpublished bounded print-end bed drop and nozzle wipe,
  openACE rollback assistance during tip shaping, and documentation/message cleanup.
  openACE-specific routing and rollback behavior still requires openACE detection.
- Retains the touchscreen rendering hotfix and fixes verification of quiet streams.

The complete deployment was installed on October 10, 2026. Klipper returned Ready
with four heads; identities, saved settings, and openACE configuration were
preserved. All five patches reported successful application, and the guard's
live callback jump was inspected. The updated screen page, JPEG snapshot, and
live binary stream passed checks. Print/tool-change/calibration acceptance and
behavior during a real guarded communication fault remain pending. The final
local project and material-helper suite passed 228 tests; release hygiene checks
and local documentation links also passed.

| Component | Compatibility in this snapshot |
|---|---|
| Full printer configuration | System 1.1.13 |
| Fan, recovery, openACE, and head-configuration preloads | Reviewed clients 1.1.08, 1.1.12, and 1.1.13 |
| Wi-Fi preload | Reviewed clients 1.1.04, 1.1.08, 1.1.12, and 1.1.13 |
| Touchscreen bridge | No new vendor calibration module required |

From an existing checkout with a clean working tree:

```bash
git fetch origin --tags
git switch --detach fw-1.1.13-r1
uv run --with paramiko python tools/deploy.py install all --preflight-only
uv run --with paramiko python tools/deploy.py install all
uv run --with paramiko python tools/deploy.py status
```

Set your printer connection in ignored `.env`, and install only while idle.
Hard-refresh the touchscreen page after updating. Read the
[1.1.13 analysis](firmware-1.1.13.md) and
[head-configuration guard limits](head-communication-recovery.md) for details.
