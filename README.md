# Wondermaker+

Puts the U1 printer's physical touchscreen into Fluidd as a live, clickable
panel. You see exactly what the LCD shows and can drive the vendor UI with a
mouse from anywhere on the network.

Built for a Wondermaker U1 / `TM-T1` (Rockchip RK3308, Debian 11, Klipper +
Moonraker + Fluidd), firmware `KLP_IMG_WM_ZRU_V1.0.26_20251127_Release`.

## How it works

The vendor UI is a native binary, `/home/t13dp/TM_T1/bin/client`, running as
root. There is no X11 or Wayland: it blits bitmaps straight to `/dev/fb0`
(800x480 XRGB8888) and reads touches from `/dev/input/event0`, a Goodix panel
whose axes map 1:1 to screen pixels. That makes both directions interceptable.

- `wmp_screen.py` polls the framebuffer, and whenever the pixels change,
  publishes the frame to browsers. It also injects synthetic multitouch
  protocol-B events to emulate taps and swipes.
- The browser page inflates each frame and paints it to a canvas, translating
  clicks back into device coordinates.
- Fluidd embeds the page because Moonraker is told about a webcam whose
  `service` is `iframe`. Fluidd's `IframeCamera` renders a plain `<iframe>`
  with no `sandbox` attribute, so it stays fully interactive.

### Why not MJPEG

The obvious design is MJPEG in an `<img>`, and it was tried first. On this
CPU, measured per frame:

| approach | cost |
|---|---|
| ffmpeg spawned per frame | 1800 ms |
| persistent ffmpeg pipe | 179 ms |
| `zlib.compress(level=3)` | 35 ms |

zlib also wins on quality, since the screen is text and flat colour that JPEG
smears, and it removes a subprocess whose rawvideo demuxer holds one frame
back — that lag would have rendered every screen one change stale. Frames go
out as raw BGRA deflated to about 3% of raw (~45 KB) and the browser inflates
them with `DecompressionStream`.

Capture only runs while somebody is watching; a full read-and-compare costs
~29 ms, so idle polling would waste real CPU on a board whose UI process
already wants 40% of a core.

## Install

Needs `uv` on the host; paramiko is fetched per-run, nothing is installed.

```bash
uv run --with paramiko python tools/deploy.py install
uv run --with paramiko python tools/deploy.py status
uv run --with paramiko python tools/deploy.py uninstall
```

Override the target with `WMP_PRINTER`, `WMP_USER`, `WMP_PASS`.

Then open Fluidd. The panel appears as a camera named **Touchscreen**.

### What it touches on the printer

Deliberately small, and all of it reversed by `uninstall.sh`:

| path | change |
|---|---|
| `/opt/wondermaker_plus/` | created (code, www, and the nginx backup) |
| `/etc/systemd/system/wmp-screen.service` | created |
| `/etc/systemd/system/wmp-timelapse-camera.service` | created (boot-time timelapse-camera fixer) |
| `/etc/nginx/sites-available/fluidd` | **one** `include` line added, backed up first |
| Moonraker database | one webcam entry named `Touchscreen`; timelapse `camera` forced to the real webcam |

The nginx edit is a single `include` so that everything else lives in our own
file. Install validates with `nginx -t` and rolls the original back if the
config is rejected. Pristine copies of every file modified on the printer are
committed under `orig/fw_<version>/<path>`.

### Timelapse camera

Registering the `Touchscreen` webcam is what makes the vendor's
`moonraker-timelapse` fall back to the LCD mirror (its camera lookup is by
name, but the screen stores a UUID, so it misses and picks the first webcam).
So the installer also drops in `wmp-timelapse-camera.service`, a boot-time
oneshot that forces the timelapse `camera` back to the real webcam (named
`camera`) — self-healing even if the screen's camera picker is touched.
Override the target with `WMP_TIMELAPSE_CAMERA`.

## Layout in Fluidd

Fluidd calls each dashboard box a **card**, and its card ids are a fixed set
with exactly one `camera-card` — there is no plugin API and `config.json` has
no hook, so the touchscreen cannot become a separate dashboard card without
patching the Fluidd bundle. Practical options:

- Leave the camera card on **ALL** and it tiles beside the webcam (default).
- Pick **Touchscreen** in the card's selector and it gets the full card width.
- Use the per-camera fullscreen control for a full-size view.

Note that deep-linking to `/camera/<uid>` is broken on stock firmware, and not
by anything here: Fluidd's `index.html` references its bundle relatively
(`./assets/...`), so on a nested route the browser asks for
`/camera/assets/...`, which nginx's `try_files` answers with `index.html`.
Strict MIME checking then refuses to execute it and the page renders blank.
In-app navigation is unaffected.

## API

Served under `/wmp-screen/`:

| endpoint | purpose |
|---|---|
| `GET /` | the interactive page |
| `GET /stream.bin` | `WMPF` + uint32 length + zlib BGRA; zero length is a heartbeat |
| `GET /snapshot.jpg` | one-shot JPEG, cached 2s (debug; costs ~1.8s) |
| `GET /api/state` | armed flag, backlight, sequence, viewer count |
| `POST /api/tap` | `{"x":45,"y":404}` |
| `POST /api/swipe` | `{"x1":..,"y1":..,"x2":..,"y2":..}` |
| `POST /api/arm` | `{"armed":false}` to block input |

```bash
curl -X POST http://<printer>/wmp-screen/api/tap \
     -H 'Content-Type: application/json' -d '{"x":45,"y":404}'
```

## Gotchas

- **The first tap after the screen blanks is swallowed** by the vendor UI as a
  wake event. The service detects a zero backlight and sends a throwaway tap
  first, so callers do not have to care.
- **Taps are real.** Anyone who can reach the printer can press STOP or start a
  print. Moonraker here has no authentication, so the panel is only as safe as
  the network it is on. `POST /api/arm {"armed": false}` blocks input, and the
  page has a **Touch on/off** toggle.
- A vendor firmware update will wipe the nginx edit and the systemd unit.
  Re-run the installer; it is idempotent.

## Tools

| tool | use |
|---|---|
| `tools/deploy.py` | push and run install / uninstall / status |
| `tools/verify_stream.py` | pull frames through nginx, inflate, write a PNG |
| `tools/u1.py` | ad-hoc `shot` / `tap` / `swipe` / `sh` over SSH |
