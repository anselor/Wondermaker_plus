# Firmware release tags

A tag identifies a complete WM+ snapshot for a specific vendor firmware:

```text
fw-<vendor-version>-r<WM+-revision>
fw-1.1.12-r1
fw-1.1.12-r2
fw-1.1.13-r2
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
| Fan and recovery preloads | Reviewed clients 1.1.08 and 1.1.12 |
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
  plus documentation/message cleanup.
- Retains the touchscreen rendering hotfix and fixes verification of quiet streams.

The complete deployment was installed on October 10, 2026. Klipper returned Ready
with four heads; identities and saved settings were preserved. The installed
patches reported successful application, and the guard's live callback jump was
inspected. The updated screen page, JPEG snapshot, and
live binary stream passed checks. Print/tool-change/calibration acceptance and
behavior during a real guarded communication fault remain pending. The final
local project and material-helper suite passed 228 tests; release hygiene checks
and local documentation links also passed.

| Component | Compatibility in this snapshot |
|---|---|
| Full printer configuration | System 1.1.13 |
| Fan, recovery, and head-configuration preloads | Reviewed clients 1.1.08, 1.1.12, and 1.1.13 |
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

## fw-1.1.13-r2 — unload temperature message fix

Fixes an unload failure introduced in `fw-1.1.13-r1`. When tip shaping needs to
change the nozzle temperature, its `RESPOND` message contained a semicolon inside
quotes. Klipper treats that
semicolon as a comment delimiter, leaving an unterminated quote and rejecting
the command. The message now uses a comma. Heating and retraction logic are
unchanged.

The regression test renders the actual temperature-adjustment branch and parses
the message with Klipper's comment-delimiter and quoted-argument behavior. The
test uses `DRY_RUN`, so it does not heat or move hardware. All 229 project and
material-helper tests passed locally. This hotfix has not been deployed to the
maintainer's printer; the installation and hardware limits recorded for `r1`
still apply.

Existing `fw-1.1.13-r1` installations can update only the affected macro file
while idle, from a clean checkout with printer connection settings in `.env`:

```bash
git fetch origin --tags
git switch --detach fw-1.1.13-r2
uv run --with paramiko python tools/deploy.py install config --files macros.cfg
uv run python tools/deploy.py status config
```

This performs config preflight, keeps the recovery helper current, backs up the
replaced macro file, and restarts Klipper. First-time users on vendor firmware
1.1.13 can follow the README for a full installation from this tag. Users on
vendor firmware 1.1.12 should keep using `fw-1.1.12-r1`.

## fw-1.1.13-r3 — case-light preference and print cleanup

Targets **vendor System 1.1.13**.

- Adds a saved case-light preference shared by the stock screen and G-code.
  Use `SET_PIN PIN=case_light VALUE=0|1` or the `CASE_LIGHT_ON`,
  `CASE_LIGHT_OFF` and `CASE_LIGHT_TOGGLE` macros in Fluidd. When enabled,
  the light follows screen activity, stays on during printing and pauses, and
  uses the screen-sleep delay after a print ends. Wake applies the preference
  before enabling the backlight; the screen button displays the preference.
- Fixes semicolons in all four extruder runout-delay messages.
- Shares the bounded bed-clearance and nozzle-wipe sequence between print end
  and cancel, preserving the configurable drop and limiting it to available
  travel. Adapted from [t-ihmels' contribution](https://github.com/t-ihmels/Wondermaker_plus).
- Lets completed SD jobs reach EOF and clears native pause flags on cancel.
- Validates Klipper configuration, Jinja templates and quoted command syntax
  before deployment and in CI. Also fixes the fan-test counter assignment.
- Rewrites the README around the fixes and enhancements over stock firmware.

Install both the updated configuration/helper and screen bridge while idle:

```bash
git fetch origin --tags
git switch --detach fw-1.1.13-r3
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install config preload
uv run --with paramiko python tools/deploy.py status
```

The matching helper and bridge are required for the new light behavior;
`--config-only` does not install them. First-time installations can follow the
README to install all components.

Validation: 304 tests passed locally, with 33 skipped because their optional
fixtures or tools were unavailable. Printer checks on 1.1.13 covered screen and
G-code choices, preference persistence, sleep/wake behavior, active/paused
lighting, print-end/cancel cleanup, replacement of the post-print timer, and
expiry after the configured delay. The screen could change the preference during
a G-code dwell. Wake applied the light with the backlight still off, and the
screen button retained the preference while the physical light slept. These
checks used jobs without heating or motion; physical clearance/wipe moves,
runout and calibration were not exercised.
