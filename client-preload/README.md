# Touchscreen fixes

The `preload` component fixes behaviors in the vendor's touchscreen program:
Wi-Fi reconnection, repeated automatic filter-fan requests, saved recovery
coordinates, and openACE compatibility. A new locally tested head-configuration
guard blocks the vendor's destructive response to communication timeouts.

It loads small libraries when `makerbase-client.service` starts. The libraries
patch the running program in memory; the vendor executable on disk stays unchanged.
This loading mechanism is called `LD_PRELOAD`.

## Compatibility

| Patch | Supported System versions |
|---|---|
| `wifi-fix` | 1.1.04, 1.1.08, 1.1.12, 1.1.13 |
| `fan-fix`, `recovery-fix`, `openace-compat`, `head-config-guard` | 1.1.08, 1.1.12, 1.1.13 |

Each patch checks the executable and the instructions it will replace. Unknown or
unexpectedly modified clients are skipped. A library appearing in the process's
loaded-library list does not prove its patch was applied; check its current log.
On 2026-10-10, the 1.1.13 configuration and four existing patches were installed
and verified with Klipper Ready and four heads. Printing and calibration acceptance
remain pending. `head-config-guard` was subsequently deployed on the same date;
its current-process log and live callback jump were verified. Its behavior during
a real communication fault has not yet been observed.
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
The screen service restarts to load them, usually taking about ten seconds.
Installation refuses running or paused prints.

Status shows the installed service override, library files, running client, loaded
libraries, and the latest patch log entries for that client process. Read those
entries after each firmware upgrade. Removal deletes the WM+ override and these
built libraries, then restarts the client.

Logs and optional disable switches:

| Patch | Log | Environment variable |
|---|---|---|
| Wi-Fi | `/tmp/wmp_wififix.log` | `WMP_WIFIFIX_DISABLE` |
| Fan | `/tmp/wmp_fanfix.log` | `WMP_FANFIX_DISABLE` |
| Recovery | `/tmp/wmp_recoveryfix.log` | `WMP_RECOVERYFIX_DISABLE` |
| openACE | `/tmp/wmp_openace_compat.log` | `WMP_OPENACE_COMPAT_DISABLE` |

Setting a disable variable in the screen service's environment takes effect on its
next restart. The code checks whether the variable exists, so remove it to re-enable
the patch; setting it to `0` still disables it.

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

This patch acts only when Moonraker reports a running Klipper object named `openace`.
Installed files alone do not activate it. Detection is cached for two seconds;
a failed query is treated as openACE absent.

With openACE active, screen Resume goes directly to Klipper so openACE can handle
or reject it. Without openACE, the vendor's normal resume preparation runs.

The screen addresses heater T0–T3 as physical heads; openACE uses virtual tool
numbers. WM+ converts simple screen-generated `M104/M109` commands containing
both `S` and `T` to an explicit physical heater command. M109 also waits within
±2.5°C. Commands with unknown parameters or out-of-range heads pass through.
Sliced-file commands do not use this screen dispatcher and keep openACE routing.

## Maintainer reference

Adding a patch requires one C file in `client-preload/<name>/`. Installation finds
and builds it automatically. The generated service override includes every
`~/wmp/lib/libwmp_*.so`. Do not add another override setting `LD_PRELOAD`, since one
setting can replace the other.

Each library must identify the `client` executable before using fixed addresses,
check loaded instructions before editing, and patch before client threads start.
The fan, recovery, and openACE checks use full-file FNV-1a fingerprints; Wi-Fi checks
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
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

Vendor-binary checks need locally extracted files and skip without them. Earlier
libraries built and loaded on the printer's ARM CPU, and the recovery marker tests
also ran there. These results do not replace hardware checks for a new firmware.
