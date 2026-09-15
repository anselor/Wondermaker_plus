# client-preload: LD_PRELOAD patches for the touchscreen client

Libraries loaded into the vendor touchscreen binary (`client`,
`makerbase-client.service`) at start. The on-disk binary is never modified;
removing the drop-in restores stock behaviour.

| directory | library | what |
|---|---|---|
| `wifi-fix/` | `libwmp_wififix.so` | Keeps wpa_supplicant auto-reconnecting after a failed reconnect (see below) |
| `fan-fix/` | `libwmp_fan-fix.so` | Limits automatic ABS filter-fan requests and honors manual touchscreen choices |
| `recovery-fix/` | `libwmp_recovery-fix.so` | Saves G-code XYZ in 1.1.08 checkpoints and rejects unverified coordinate formats before recovery motion |

## Deploy (SSH + sudo)

```bash
uv run --with paramiko python tools/deploy.py install preload
uv run --with paramiko python tools/deploy.py status preload
uv run --with paramiko python tools/deploy.py uninstall preload
```

`install` uploads each `client-preload/<name>/*.c`, builds it on the printer
(`gcc`, present on the stock image) to `~/wmp/lib/libwmp_<name>.so`, writes
`/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf` with
`LD_PRELOAD` listing every `~/wmp/lib/libwmp_*.so`, and restarts the client
(the screen restarts, about 10 s). Not run during a print.

Adding a library: create `client-preload/<name>/<name>.c` and run `install`.
The drop-in is regenerated from the lib directory, so libraries from other
work (for example the screen injection) coexist by being placed there; do not
add a second drop-in that sets `LD_PRELOAD`, systemd would keep only one.

## Recovery checkpoint coordinates (1.1.08)

`recovery-fix/wmp_recoveryfix.c` fixes the writer at `0x62f4bc`: stock saves
the compensated `toolhead.position` XYZ, then recovery sends those numbers
as ordinary G-code positions with mesh/tool compensation active again. The
patch reads the client's `gcode_move.gcode_position` float vector instead,
converts to double for the existing formatter, and preserves six decimal
places for XY (and the integer-Z formatting branch). The other Z branch
retains the vendor's six significant digits. E, file position, heater/fan
targets and the vendor A/B selection policy are unchanged.

The complete stock ELF size/FNV fingerprint and the loaded writer, loader,
recovery entry and sender prologue are checked before patching. All three
entry trampolines relocate only position-independent stack/register operations.
No new code is written to the client ELF on disk. The library uses libdl for
the native std::string accessor and console message construction.

Each changed A/B file gets a sibling `.wmp-coordinates` sidecar containing
`WMP-GCODE-XYZ-1` and an FNV fingerprint of the entire file. Data is synced
before the marker is atomically published. This fingerprint detects stale or
changed records, not malicious tampering. An unchanged writer call cannot mark
a legacy record. A missing, stale or malformed sidecar blocks recovery before
the vendor start function sends motion; the reason is recorded in
`/tmp/wmp_recoveryfix.log` and reported to the printer console. The loader's
selected-file hash is checked again at Continue, so editing disk records also
requires refreshing the cached recovery state. A power failure between data
and marker publication can leave an unverified checkpoint; the guard rejects
it rather than changing the vendor's A/B choice silently.

Existing pending checkpoints require evidence-based migration before deploying
this component. Back up A/B, `plr.ini`, saved variables and the current preload
installation. Recover logical coordinates from a matching pre-cut snapshot or
a separately validated coordinate conversion; never label raw coordinates as
G-code merely because the library is now installed. Stop the touchscreen
service while installing corrected records and markers, then restart it to
reload. Do not cancel the recovery prompt or change mesh/calibration to mask
a coordinate mismatch. See [the investigation](../docs/print-mesh-recovery.md).

The fix does not synchronize the vendor's separately sampled file position and
motion state, solve every interrupted-tool-change checkpoint, or change its
checkpoint+3 wipe/return sequence. Tests cover real C guard callbacks, corrupted
and stale markers/cached state, ELF guards and emulated AArch64 coordinate
loads. The guard harness also ran on the printer's ARM CPU before deployment.
Run the full suite including ARM emulation with:

```bash
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

Conventions for a library: guard on `/proc/self/exe` basename `client`
(`start.sh` and child processes also inherit `LD_PRELOAD`); identify the
reviewed executable before dereferencing fixed addresses, verify the loaded
instructions before any edits, and patch in the constructor before the
client's threads start. wifi-fix supports the official **1.1.04 and 1.1.08**
clients. It checks ELF architecture/type/layout, file size and a fingerprint
of the complete processEvent function, then compares its loaded instructions
against that file. Only already-applied intended NOPs are accepted as changes.
Unknown binaries or unexpected edits cause the whole patch to be skipped.
The FNV-1a function fingerprint detects version mismatches; it is not an
authenticity/signature check. Full vendor SHA-256 hashes are recorded in
[the integration notes](../docs/firmware-1.1.08.md).

## wifi-fix

Symptom: the printer drops off Wi-Fi and stays off until the Wi-Fi page is
opened on the screen; the boot itself connects fine.

Cause (client 1.1.04, from `client_log.txt` and the binary): after a roam or
short drop, the client's `WifiManager::checkAndRecoverConnection` issues one
reconnect. If it fails (`Connect_failed`, typically 4 s later),
`WifiManager::processEvent` calls `WifiManager::disconnect()`, which sends
`DISCONNECT` to wpa_supplicant. wpa_supplicant then stops all automatic
reconnection until it receives `RECONNECT`/`REASSOCIATE`/`SELECT_NETWORK`,
which only the Wi-Fi page sends. Observed 2026-09-01 15:04 to 2026-09-07
05:33 (six days offline).

Fix: NOP three `bl WifiManager::disconnect` sites in `processEvent`:

| Branch | 1.1.04 | 1.1.08 | Action |
|---|---|---|---|
| CONN_FAILED / timed out | `0x6604d8` | `0x660cb4` | NOP |
| WRONG_KEY | `0x6605ec` | `0x660dc8` | Preserve |
| ASSOC-REJECT | `0x660700` | `0x660edc` | NOP |
| NETWORK-NOT-FOUND after >3 events | `0x660850` | `0x66102c` | NOP |

**Correction (2026-09-13):** Ghidra decompilation and event-string references
showed that the original 1.1.04 patch mislabeled the last three branches.
It patched WRONG_KEY and left NETWORK-NOT-FOUND unchanged. Both supported
profiles now use the corrected sites above. The network-not-found retry
counter/threshold and configuration restoration remain intact.

wpa_supplicant keeps scanning and re-associates by itself; the client's
status returns to `Connected` on `CTRL-EVENT-CONNECTED` as before.
Log: `/tmp/wmp_wififix.log`. `WMP_WIFIFIX_DISABLE=1` in the service
environment disables the patch without uninstalling.

The guard and instruction choices are checked locally against both ELF
files; real reconnect and wrong-password behavior still need confirmation
after installing on 1.1.08. An already-running process needs the normal
service restart to load the rebuilt library; do not layer it over the old
incorrect in-memory patch.

Contributing factors, not changed here: two AP units broadcast the SSID at
near-equal signal on 5200 and 5560 MHz (roaming flaps); 5560 is a DFS
channel and the driver runs in the WORLD regulatory domain
(`regulatory.db` missing), so that channel is passive-scan only and slow to
re-find.

## fan-fix (1.1.08)

Prevents automatic ABS filter requests from accumulating while Klipper is
busy. The vendor periodically asks for 100% whenever reported speed is zero;
stale reports can repeatedly trigger this path before the first request runs.

The replacement permits one automatic fan-on request per print. It consumes
that allowance before sending (or if the fan is already running), so later
manual OFF stays effective. Pause/resume does not re-arm. Explicit touchscreen
fan commands during a print suppress automation immediately and still execute
the unchanged vendor sender, preserving user speed choices even before the
first automatic check. Slicer fan control is unchanged. A host that is not
ready receives no automatic requests. Known terminal print states re-arm for
the next print once the host is ready.

Also removes a redundant OFF request from the status parser when reported
speed is already zero and the filter is absent. The filter installed flag
and Klipper fan driver are unchanged. This fixes the automatic sender; it
does not impose a global Klipper queue limit.

The complete official 1.1.08 ELF fingerprint and loaded function bytes must
match before patching. Other versions are skipped. The sender wrapper uses
a trampoline containing its four verified position-independent prologue
instructions. Full address/provenance and acceptance details are in
[the integration notes](../docs/firmware-1.1.08.md).

The existing preload installer discovers/builds this library automatically.
Status includes `/tmp/wmp_fanfix.log`. Set `WMP_FANFIX_DISABLE=1` to disable
it on the next client restart. Local C policy/guard tests pass, and the library
was built and loaded on the printer. Dedicated ABS automatic-start/manual-override
hardware acceptance remains outstanding.
