# Touchscreen fixes

The `preload` component fixes behaviors in the vendor's touchscreen program:
Wi-Fi reconnection, repeated automatic filter-fan requests, saved recovery
coordinates, and head-configuration loss after communication timeouts. It also
connects the screen's case-light button to the saved light preference.

It loads small libraries when `makerbase-client.service` starts. The libraries
patch the running program in memory; the vendor executable on disk stays unchanged.
This loading mechanism is called `LD_PRELOAD`.

## Compatibility

| Patch | Supported System versions |
|---|---|
| `wifi-fix` | 1.1.04, 1.1.08, 1.1.12, 1.1.13 |
| `fan-fix`, `recovery-fix`, `head-config-guard`, `case-light` | 1.1.08, 1.1.12, 1.1.13 |

Each patch checks the executable and the instructions it will replace. Preflight
rejects unsupported clients before installing anything. The installer also makes
the head guard a requirement for stock-screen startup: if that guard cannot apply,
the screen program exits before running vendor startup code. Other patches skip
unknown or unexpectedly modified clients. A loaded library alone does not prove
its patch was applied.
See [head communication recovery](../docs/head-communication-recovery.md) for its
limits; it preserves configuration while retaining Klipper shutdown and manual recovery.

## Install, check, and remove

Run on your computer with the connection settings from the
[project README](../README.md):

```bash
uv run --with paramiko python tools/deploy.py install preload --preflight-only
uv run --with paramiko python tools/deploy.py install preload
uv run --with paramiko python tools/deploy.py status preload
uv run --with paramiko python tools/deploy.py uninstall preload
```

Installation requires SSH and sudo. It uploads C sources to `~/wmp/src/`, compiles
libraries in `~/wmp/lib/`, and sets `LD_PRELOAD` in
`/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf`.
Libraries and the service override are replaced atomically. When config or
material is selected too, those uploads finish before the screen restarts.
Installation refuses running or paused prints, including a print started while
the libraries are compiling.

After restarting the screen, the installer checks the running process's guard
activation log and verifies that the live head-reset callback points into the
installed guard library. Failed verification stops installation. It waits for the
backend to finish starting without issuing another reset; error/shutdown states
still allow configuration repair. The guard is checked again before the final
Klipper restart. `--no-restart` defers that final restart, not screen activation.

After a vendor update, an unsupported screen client will remain stopped until
matching patches are installed or the `preload` component is removed.

Status shows the installed service override, library files, running client, loaded
libraries, and the latest patch log entries for that client process. Read those
entries after each firmware upgrade. Removal deletes the WM+ override and these
built libraries, then restarts the client.

Logs and optional disable switches:

| Patch | Log | Environment variable |
|---|---|---|
| Case light | `/tmp/wmp_case-light.log` | `WMP_CASE_LIGHT_DISABLE` |
| Door wake (part of the case-light patch) | `/tmp/wmp_case-light.log` | `WMP_DOOR_WAKE_DISABLE` |
| Wi-Fi | `/tmp/wmp_wififix.log` | `WMP_WIFIFIX_DISABLE` |
| Fan | `/tmp/wmp_fanfix.log` | `WMP_FANFIX_DISABLE` |
| Recovery | `/tmp/wmp_recoveryfix.log` | `WMP_RECOVERYFIX_DISABLE` |

Door wake reads the two vendor door switches (`gcode_button Door_button1` and
`Door_button2`) from Moonraker twice a second. When a door changes from closed
to open while the screen is asleep, it sends one touch to the top-left corner of
the panel. A sleeping screen is covered by the screen program's own wake layer,
so the touch wakes the screen and reaches no control. Nothing is sent while the
door stays open or when it closes, and the screen sleeps again after its usual
delay. Disabling the case-light patch also disables door wake.

Setting a disable variable in the screen service's environment takes effect on its
next restart. The code checks whether the variable exists, so remove it to re-enable
the patch; setting it to `0` still disables it.

## Case-light preference

The case-light bridge forwards explicit screen light clicks to Klipper's
`wmp_case_light/set` endpoint through local Moonraker so a G-code wait cannot
delay the preference. It falls back to `SET_PIN PIN=case_light VALUE=0|1` if
the endpoint is unavailable. The matching `wmp_case_light.py`
helper persists the preference through Klipper's `SAVE_VARIABLE` API and applies
the screen/print lighting policy. The bridge itself never edits settings files.
The LED button reads the saved preference, so automatic screen sleep does not
make it appear switched Off. Before enabling the backlight, the bridge notifies
Klipper to apply that preference immediately. These requests have a short timeout;
the screen can still wake when the backend is unavailable.
The native setters still run for GPIO initialization and manual fallback.
A permission monitor delegates only GPIO76's value file to the stock Klipper
user, so the unprivileged helper can drive the light after export/reboot.
Unknown client fingerprints or changed hook code prevent patch installation.
Install `config preload` together and check the case-light log for the current
screen process. See [case-light behavior](../config/README.md#case-light-preference-screen-sleep-and-printing).

## Wi-Fi reconnection

The observed fault leaves the printer offline after a brief connection failure
until someone opens its Wi-Fi page. The vendor client requests a disconnect after
some failed reconnect attempts, which tells the Wi-Fi service to stop retrying.

WM+ removes that disconnect request for timeout, association rejection, and repeated
network-not-found events. A wrong-password disconnect remains. The Wi-Fi service
can keep scanning and reconnect by itself.

The September 13, 2026 correction fixed an older patch that mistakenly disabled
the wrong-password branch and missed network-not-found. Rebuild and restart the
service to replace that older in-memory patch. Real reconnection and wrong-password
behavior still need confirmation on a newly supported firmware.

The original investigation also found roaming between two access points and slower
rediscovery on a DFS channel. This patch does not change those network conditions.

## Automatic filter-fan requests

The vendor repeatedly asks for full filter-fan speed during ABS printing when
reported speed is zero. If Klipper is busy, stale status can trigger more requests
before the first one runs.

WM+ permits one automatic fan-start request per print. A fan already running uses
that allowance too. Manual touchscreen fan choices take priority, including Off
before the first automatic request. Pause/resume does not renew the allowance;
a known finished/cancelled/error/standby state with Klipper ready prepares the next
print. Slicer fan commands remain unchanged.

The patch also removes a redundant Off request when the filter is absent and its
reported speed is already zero. It does not disable the filter or limit all Klipper
commands. Local tests cover the request policy; a dedicated ABS automatic-start
and manual-override test on the printer remains pending.

## Recovery coordinates

The stock client saves positions that already include bed-mesh and tool-offset
corrections. Recovery treats them as ordinary G-code coordinates and applies those
corrections again, potentially returning at the wrong height or XY position.

WM+ saves the logical G-code XYZ position instead. It leaves extrusion, file
position, heater/fan targets, and the vendor's choice between its two checkpoint
files unchanged. Corrected recovery requires both this patch and the `config`
component's saved mesh, tool mapping, and bottom-Z helper.

Each corrected checkpoint gets a `.wmp-coordinates` companion file containing
`WMP-GCODE-XYZ-1` and a fingerprint of the checkpoint contents. Recovery checks that
marker before motion and checks the cached selected record again when Continue is
pressed. A missing, stale, or malformed marker blocks recovery and reports why.
The fingerprint detects changed files; it is not protection against deliberate
tampering.

Checkpoint data is synced before the marker is published. Power loss between those
steps can leave an unverified checkpoint, which is rejected. The patch does not
silently choose a different checkpoint to bypass that check.

### Upgrading with an interrupted print

Installing the patch does not make an old checkpoint valid. A print started before
the matching WM+ recovery configuration can also lack its saved mesh/tool information.
Do not update expecting such a print to resume automatically.

If preserving a pending print, first back up both A/B checkpoint files, `plr.ini`,
saved variables, and the existing patch installation. Coordinate migration requires
matching pre-cut position evidence or a separately verified conversion. Never add
a marker to old coordinates simply to make recovery accept them.

Stop the touchscreen service while installing corrected records and markers, then
restart it so the client reloads them. Do not cancel the recovery prompt or change
calibration to hide a mismatch. This is an investigation procedure, not a routine
upgrade step; see the [recovery record](../docs/print-mesh-recovery.md).

The vendor's checkpoint sampling and 3 mm recovery-return clearance remain limits.
The patch does not synchronize file position with motion, fix every interrupted
tool change, or make a detached part recoverable.

## openACE compatibility

Resume and heater routing change when Moonraker reports a running Klipper object
named `openace`. Installed files alone do not activate that routing. Detection
for those existing hooks is cached for two seconds; a failed query currently
falls back to their stock path.

With openACE active, screen Resume goes directly to Klipper so openACE can handle
or reject it. Without openACE, the vendor's normal resume preparation runs.

The screen addresses heater T0–T3 as physical heads; openACE uses virtual tool
numbers. WM+ converts simple screen-generated `M104/M109` commands containing
both `S` and `T` to an explicit physical heater command. M109 also waits within
±2.5°C. Commands with unknown parameters or out-of-range heads pass through.
Sliced-file commands do not use this screen dispatcher and keep openACE routing.

The separate stock runout auto-purge callback heats the paused head, homes X/Y,
travels to the purge position, and feeds 100 mm. It does not itself send RESUME.
WM+ suppresses this callback when openACE is present, because openACE owns recovery
preparation. A fresh, complete object-list response confirming openACE is absent
preserves stock behavior. An unavailable or malformed response withholds this
automatic sequence; suppression does not send RESUME or record completed purge.
The separately queued `filament_check_for_resume` worker is guarded by the same
present/unknown/confirmed-absent policy. With openACE present, this intentionally
removes its stock replacement prompts, automatic alternate-head selection,
mapping writes, purge and automatic RESUME. The separate runout/tangle pause
checker and sensor producers remain untouched. Manual standalone filament
controls are a planned GUI feature, not part of these guards.

## Maintainer reference

Adding a patch requires one C file in `client-preload/<name>/`. Installation finds
and builds it automatically. The generated service override includes every
`~/wmp/lib/libwmp_*.so`. Do not add another override setting `LD_PRELOAD`, since one
setting can replace the other.

Each library must identify the `client` executable before using fixed addresses,
check loaded instructions before editing, and patch before client threads start.
The fan and recovery checks use full-file FNV-1a fingerprints; Wi-Fi checks
executable layout and the complete event-handler function. These identify reviewed
builds, not publisher authenticity. Official SHA-256 values are recorded in the
[firmware notes](../docs/README.md#firmware-comparisons).

Recovery writes float G-code coordinates through the vendor's double formatter.
XY and the integer-Z branch keep six decimal places; the other Z branch retains
six significant digits. Hooks preserve verified position-independent entry
instructions and use libdl for C++ string access. Firmware-specific addresses live
in the source profiles and firmware comparison notes.

Run local policy, compatibility, marker, and ARM-emulation tests with:

```bash
uv run --with pytest --with jinja2 --with unicorn --with capstone python -m pytest -q tests
```

Vendor-binary checks need locally extracted files and skip without them. Earlier
libraries built and loaded on the printer's ARM CPU, and the recovery marker tests
also ran there. These results do not replace hardware checks for a new firmware.

## Native openACE screen source

The exact1.1.13 optional native bundle includes readable C++ source, its pinned
build recipe, source archive and portable tests under
[`openace-compat/screen1113/`](openace-compat/screen1113/README.md). It reuses the
existing compat C hooks; older C-only profiles need no native archive or compiler.
Cross-repository backend tests are explicit developer gates and never operator
configuration. Native screen installation/touch/Stop acceptance remains separate
from offline tests and from the current backend deployment.
