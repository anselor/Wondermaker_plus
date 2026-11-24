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

## R4 refinement update — 24 November 2026

This follow-up targets vendor System **1.1.13** on the moving
`fw-1.1.13/r4` branch, after `ab18e32`. It does not create or move a release tag.
R4 stays untagged while user feedback is collected. After this update, R4 takes
critical bug fixes only; other fixes and enhancements move to R5.

- **Finish and Cancel positioning:** lower toward physical **Z125 mm**, with a
  **50 mm minimum drop**, capped at the bottom endstop. Both values are
  user-configurable. After confirmed clearance, park a confirmed attached head
  beside the left scrubber. Finish retains its wipe; Cancel adds no extrusion,
  wipe, pickup or homing. Cancelling before SD execution adds no cleanup motion.
  Explicit overrides survive upgrades; custom legacy fixed drops remain fixed.
- **Filament appearance:** add Standard, Translucent, Gradient and Co-extrusion
  classifications without changing material recipes, temperatures or load state.
  Translucent swatches use a smoothly clipped checkerboard. Gradient and
  Co-extrusion retain the primary solid colour in R4; multiple colours and
  gradient/radial rendering remain R5 work.
- **Progress:** group small actions under major phases, showing homing,
  positioning, temperatures and probe counts as additional detail. Normal
  filament service, complete print preparation and recovery use at most six
  major rows. Scrub preparation shows homing and keeps Prepare active until
  pickup begins. Stop controls and existing safe cancellation boundaries remain.
- **Filament-used accounting:** sample the outgoing extruder and rebase the
  incoming E coordinate at tool activation. This fixes the retained stock
  counter jumping backward across physical heads; unsupported dispatchers are
  left unchanged. It does not change motor scheduling, pressure advance or input
  shaping.
- **Native UI and lighting:** attach the Home filament panel before its first
  paint and skip the stock filament-only refresh work. Put WonderMaker+ first
  in About, showing the installed tag or branch/commit. Force the chamber light
  on during calibration without changing its saved preference; an open door
  acknowledges attention blinking.
- **Compatibility:** preserve the reviewed recovery contract for the revised
  finish helpers, alongside configuration/tuning preservation on upgrade.

For persistent and temporary bed-position overrides, see the
[configuration guide](../config/README.md#startup-print-end-and-cooling).

### Validation and known limits

The exact reviewed native artifact was installed and verified with Klipper
Ready and the GUI/status bridge synchronized. User tuning and filament
identities were preserved. Attended checks covered bed clearance/parking,
filament progress and native Stop before retraction, scrub preparation and
cancellation before offset measurement, and a two-head Vehicles first layer.
At the black-to-red change, E changed from **336.48 mm to 0** while total usage
stayed **336.48 mm**; subsequent red extrusion increased the total correctly.
The test was stopped, with heaters off and the head parked at physical Z125.

The candidate's final regression and package checks are recorded in the
[refinement release validation](validation/r4-refinement-release-2026-11-24.md).
These checks do not claim that every material, naturally occurring gauge
fault, first-run setup or legacy-permission installation was tested physically.

**Still under investigation:** intermittent extrusion/Z timing symptoms,
print stuttering/CPU attribution and the isolated USB-hub disconnect. This
update does not claim to resolve those causes. The 60 MB Vehicles file spent
about **92 seconds** in visible file preparation before preheat; showing
progress does not eliminate that processing cost. PETG unload, uncommon
calibration/re-check outcomes and the guarded pre-home clearance retain their
separate acceptance scope.

Existing R4 users can update using the idle-printer commands in the next
section. The earlier branch-update validation below describes its original
snapshot; this follow-up adds scrub detail and normal-cancel parking.

## R4 branch update — 24 November 2026

This update targets vendor System **1.1.13** on the moving
`fw-1.1.13/r4` branch. It does not move an existing release tag.

- **Cooperative Stop:** request-bound cancellation for homing, tool and filament
  service, identification, calibration, Resume and power-loss recovery. Stop is
  observed at owned safe boundaries. An admitted lock/unlock and dock back-off
  finishes before cancellation; existing Z holding is preserved.
- **Calibration results:** save completed calibration types before starting the
  next type, discard incomplete results on cancellation, and report confirmed
  Stop locations and expected save/restart progress honestly.
- **Print startup:** show file processing and byte progress before heating or
  homing, allow Stop during pending file processing, and prevent stale scan work
  from dispatching a retired start. Reduce repeated scan parsing and retain
  filament telemetry when optional detail queries fail.
- **Filament controls:** replace unsupported stock special-colour swatches with
  ten ordered colour families, each with six large solid-colour choices. Centre
  radio indicators and use the same material/profile nozzle target for standalone
  Load and Unload. Mixed-material load transition policy remains separate;
  openACE-owned service stays delegated to that backend.
- **Consistency and upgrades:** align progress titles with header actions and
  repair the narrowly identified legacy recovery-marker read permission problem.

The candidate has been installed on the local printer with configuration and
saved tuning preserved. Representative attended cancellation and completed-type
save checks are recorded in [the consolidated validation](validation/early-stop-consolidated-plan-2026-11-23.md).
The Vehicles touchscreen start displayed file-processing progress and its native
Stop cancelled before SD execution, heating or homing. The final colour picker
was checked on-device and approved by the user.

All 6,914 regression cases are covered by passing executions across the main
run and the corrected collection/module check. Exact results are recorded in
[the release validation](validation/r4-backlog-release-2026-11-24.md).
Host tests and representative live tests are distinguished there; a complete
first-run setup, naturally occurring gauge disagreement, and every material's
physical unload behavior are not claimed as hardware-tested.

**Still under investigation:** intermittent extrusion/Z timing symptoms and
print stuttering/CPU attribution. This update does not claim their cause has
been found or fixed. Gauge repeatability and the conditional pre-home dock
clearance retain their separately scoped verification items. Normal-cancel
parking off the bed remains separate work.

For an existing clean R4 checkout, update while the printer is idle:

```bash
git fetch origin
git switch fw-1.1.13/r4
git pull --ff-only origin fw-1.1.13/r4
uv run --with paramiko --with jinja2 python tools/deploy.py install all
```

### Follow-up: deferred filament-service homing

Fixes Load/Unload or tool service rejecting its own X/Y homing after the
admitting command has returned. This was exposed by filament loading with
unhomed axes after a completed print. Homing keeps the executing service's
validated actor/session/generation ownership instead of acquiring a competing
standalone Home attempt. Stale, unrelated and cancelled service contexts retain
their checks. The original homing commands and native screen binary are unchanged.

[Regression and installation evidence](validation/service-owned-homing-2026-11-24.md)
records the deferred callback tests and affected material/motion checks.

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
uv run --with paramiko --with jinja2 python tools/deploy.py install all
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
