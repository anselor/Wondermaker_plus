# Use the printer's touchscreen in Fluidd

WM+ shows the physical touchscreen as a live panel in Fluidd. Clicking or dragging
in the panel sends a tap or swipe to the printer, just as touching its screen would.

## Install

Set your connection details as described in the [project README](../README.md).
Run these commands on your computer:

```bash
uv run --with paramiko python tools/deploy.py install touchscreen
uv run --with paramiko python tools/deploy.py status touchscreen
```

Open Fluidd and look for a camera named **Touchscreen**. Select **ALL** in the
camera card to show it beside the print camera, or select **Touchscreen** for a
larger view. The camera's fullscreen control opens a full-size view.

The **Touch on / Touch off** button enables or blocks remote input. Input is real:
a remote tap can stop a print or start one. Access to this panel depends on access
to the printer's network and web server. Blocking touch input leaves viewing enabled.

If the screen is asleep, the bridge wakes it when sending a gesture. Firmware
updates can remove the installation; run the install command again afterward.
Repeating installation updates the files without adding another web-server include.

## Timelapse camera

The vendor's timelapse camera lookup can select the touchscreen panel instead of
the print camera. WM+ installs a small service that sets the timelapse camera to
`camera` at installation and on boot. For a different camera name, set
`WMP_TIMELAPSE_CAMERA` in the printer service's environment. Changing the camera
picker on the physical screen can override the setting again.

## Remove

```bash
uv run --with paramiko python tools/deploy.py uninstall touchscreen
```

Removal deletes the bridge files and services, removes the Touchscreen camera
entry, and restores the backed-up Fluidd web-server configuration. If the backup
is missing, it removes the WM+ include line instead. It does not restore the
previous timelapse camera setting or remove other WM+ components.

## Files changed on the printer

| Path or setting | Change |
|---|---|
| `/opt/wondermaker_plus/` | Bridge, web page, and web-server backup |
| `/etc/systemd/system/wmp-screen.service` | Screen bridge service |
| `/etc/systemd/system/wmp-timelapse-camera.service` | Boot-time camera selection |
| `/etc/nginx/sites-available/fluidd` | One WM+ include line, with a backup before editing |
| Moonraker camera registry | Touchscreen camera entry |
| Timelapse settings | Print-camera selection |

The installer checks the nginx web-server configuration. If nginx rejects its edit,
it restores the original configuration.

## Troubleshooting

If the panel is missing, run `status touchscreen`. Check that `wmp-screen.service`
is active and that `/wmp-screen/` responds through the printer's web server.
If the panel works but does not accept taps, enable **Touch on**. A failed tap or
swipe means the browser could not complete the request; check the connection
before retrying.

`tools/verify_stream.py` checks the streamed frames and writes a PNG.
`tools/u1.py` provides screenshot, tap, swipe, and shell commands over SSH.

## How the bridge works

The vendor screen draws directly to a framebuffer, the memory holding its pixels.
`device/wmp_screen.py` reads those pixels and sends compressed frame updates to the
browser. It writes touch events to the input device. Fluidd displays the page as
an iframe camera, an embedded web page.

The bridge captures at up to 5 frames per second while the screen changes and
2 while quiet. It sends only changed groups of full-width rows, or a full frame
for large changes and new viewers. Hidden or offscreen browser panels disconnect;
when no viewers remain, the bridge stops reading screen pixels.

## HTTP API reference

All paths below are relative to `/wmp-screen/`.

| Request | Purpose |
|---|---|
| `GET /` | Interactive panel |
| `GET /stream.bin` | Compressed frame stream; a zero-length packet is a heartbeat |
| `GET /snapshot.jpg` | Single JPEG screenshot |
| `GET /api/state` | Input enabled, backlight, frame sequence, and viewer count |
| `POST /api/tap` | Tap: `{"x":45,"y":404}` |
| `POST /api/swipe` | Swipe: `{"x1":45,"y1":404,"x2":200,"y2":404}` |
| `POST /api/arm` | Enable or block input: `{"armed":false}` |

For example:

```bash
curl -X POST http://<printer>/wmp-screen/api/tap \
     -H 'Content-Type: application/json' -d '{"x":45,"y":404}'
```
