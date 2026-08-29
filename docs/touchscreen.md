# Fluidd touchscreen integration

Brings the printer's physical LCD into Fluidd as a live, clickable panel. You
see exactly what the screen shows and can drive the vendor UI with a mouse
from anywhere on the network.

The vendor UI draws straight to the framebuffer and reads a touch panel, with
no desktop environment. `wmp_screen.py` captures the framebuffer, streams
changed frames to the browser as compressed images, and injects synthetic
touch events so clicks in the browser become taps on the panel. Fluidd embeds
the page through a Moonraker webcam entry whose service is `iframe`.

## Install

Needs `uv` on the host; nothing is installed there permanently.

```bash
uv run --with paramiko python tools/deploy.py install touchscreen
uv run --with paramiko python tools/deploy.py status touchscreen
uv run --with paramiko python tools/deploy.py uninstall touchscreen
```

Then open Fluidd. The panel appears as a camera named **Touchscreen**.

## What it changes on the printer

All of it is reversed by `uninstall.sh`:

| path | change |
|---|---|
| `/opt/wondermaker_plus/` | created (code, web page, backups) |
| `/etc/systemd/system/wmp-screen.service` | created |
| `/etc/systemd/system/wmp-timelapse-camera.service` | created (timelapse-camera fixer) |
| `/etc/nginx/sites-available/fluidd` | one `include` line added, backed up first |
| Moonraker database | one webcam named `Touchscreen`; timelapse `camera` set to the real webcam |

Install validates nginx and rolls the original config back if it is rejected.

## Timelapse camera

Adding the `Touchscreen` webcam makes the vendor's timelapse component pick
the wrong camera and record the LCD instead of the print. The installer adds
`wmp-timelapse-camera.service`, which forces the timelapse camera back to the
real webcam on every boot. Override the target name with
`WMP_TIMELAPSE_CAMERA`.

## Layout in Fluidd

Fluidd allows exactly one camera card, so the touchscreen shares that card
with any real webcam:

- Leave the card on **ALL** to tile the touchscreen beside the webcam.
- Pick **Touchscreen** in the card selector to give it the full card width.
- Use the per-camera fullscreen control for a full-size view.

## HTTP API

Served under `/wmp-screen/`:

| endpoint | purpose |
|---|---|
| `GET /` | the interactive page |
| `GET /stream.bin` | compressed frame stream (zero length is a heartbeat) |
| `GET /snapshot.jpg` | one-shot JPEG (debug) |
| `GET /api/state` | armed flag, backlight, sequence, viewer count |
| `POST /api/tap` | `{"x":45,"y":404}` |
| `POST /api/swipe` | `{"x1":..,"y1":..,"x2":..,"y2":..}` |
| `POST /api/arm` | `{"armed":false}` to block input |

```bash
curl -X POST http://<printer>/wmp-screen/api/tap \
     -H 'Content-Type: application/json' -d '{"x":45,"y":404}'
```

## Notes

- Taps are real: anyone who can reach the printer can press STOP or start a
  print. Moonraker here has no authentication, so the panel is only as safe as
  the network. Send `POST /api/arm {"armed": false}`, or use the page's
  **Touch on/off** toggle, to block input.
- The first tap after the screen blanks is consumed as a wake event; the
  service handles this automatically.
- A vendor firmware update wipes the nginx edit and systemd units. Re-run the
  installer; it is idempotent.

## Tools

| tool | use |
|---|---|
| `tools/deploy.py` (`touchscreen` component, `tools/components/touchscreen.py`) | push and run install / uninstall / status |
| `tools/verify_stream.py` | pull frames through nginx and write a PNG |
| `tools/u1.py` | ad-hoc `shot` / `tap` / `swipe` / `sh` over SSH |
