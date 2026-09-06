# client-preload: LD_PRELOAD patches for the touchscreen client

Libraries loaded into the vendor touchscreen binary (`client`,
`makerbase-client.service`) at start. The on-disk binary is never modified;
removing the drop-in restores stock behaviour.

| directory | library | what |
|---|---|---|
| `wifi-fix/` | `libwmp_wififix.so` | Keeps wpa_supplicant auto-reconnecting after a failed reconnect (see below) |

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

Conventions for a library: guard on `/proc/self/exe` basename `client`
(`start.sh` and child processes also inherit `LD_PRELOAD`); verify the
expected instruction words before patching (this is the version guard for
client 1.1.04, sha256 `6889c20f…94a8c3`); patch in the constructor, before
the client's threads start.

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

Fix: NOP the three `bl WifiManager::disconnect` sites in `processEvent`
(`0x6604d8` DISCONNECTED/CONN_FAILED/timed out, `0x6605ec` ASSOC-REJECT,
`0x660700` NETWORK-NOT-FOUND). The `WRONG_KEY` site (`0x660850`) is kept.
wpa_supplicant keeps scanning and re-associates by itself; the client's
status returns to `Connected` on `CTRL-EVENT-CONNECTED` as before.
Log: `/tmp/wmp_wififix.log`. `WMP_WIFIFIX_DISABLE=1` in the service
environment disables the patch without uninstalling.

Contributing factors, not changed here: two AP units broadcast the SSID at
near-equal signal on 5200 and 5560 MHz (roaming flaps); 5560 is a DFS
channel and the driver runs in the WORLD regulatory domain
(`regulatory.db` missing), so that channel is passive-scan only and slow to
re-find.
