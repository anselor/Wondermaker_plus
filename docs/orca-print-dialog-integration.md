# Adding the touchscreen's print-start options to OrcaSlicer

Captured live from the WonderMaker U1 touchscreen (`TM_T1/bin/client`)
starting a print over its Moonraker websocket, 2026-08-18. Everything below
is plain Moonraker API / gcode — Orca can reproduce it with its existing
"send gcode on print start" hooks or a post-processing script.

## What the screen sends when you press "start print"

```
_SET_TIMELAPSE_SETUP ENABLE=True VERBOSE=False PARK_ENABLE=False PARK_POS=back_left
                     CUSTOM_POS_X=10.0 CUSTOM_POS_Y=10.0 CUSTOM_POS_DZ=0.0
                     TRAVEL_SPEED=100 RETRACT_SPEED=15 EXTRUDE_SPEED=15 RETRACT_DI...
HYPERLAPSE ACTION=STOP          # clear any stale hyperlapse session
G30                             # leveling toggle ON  (G31 = OFF)
SDCARD_PRINT_FILE FILENAME="<file>.gcode"
```

(The `_SET_TIMELAPSE_SETUP` line is actually sent whenever the timelapse
toggle changes, not only at start.)

## The two toggles

### Bed leveling toggle -> `G30` / `G31`
Vendor macros (in stock `macros.cfg`): `G30` sets
`adaptive_mesh_enable=True` so `START_PRINT` probes a fresh (adaptive) mesh;
`G31` sets it False so START_PRINT loads the saved default mesh instead.
Orca integration: emit `G30` or `G31` as the first line of the print (or via
machine start gcode with a user toggle), before `START_PRINT` runs.

### Timelapse toggle -> moonraker-timelapse component
Standard `moonraker-timelapse` is installed (`[timelapse]` in
moonraker.conf), configured in **layermacro** mode with `autorender: true`.
Frames are taken whenever the `TIMELAPSE_TAKE_FRAME` macro runs; the vendor
UI fires it over the API on its own layer tracking. For Orca the standard
integration is simpler and independent of the UI:

- Enable: `_SET_TIMELAPSE_SETUP ENABLE=True ...` at print start (or once,
  via `POST /machine/timelapse/settings?enabled=true`).
- Put `TIMELAPSE_TAKE_FRAME` in Orca's layer-change custom gcode.
- Rendering happens automatically at print end (`autorender`), or on demand
  with `TIMELAPSE_RENDER`. Output lands in `~/printer_data/timelapse/`.

## Gotcha: the timelapse camera selection is broken on stock

The vendor's `timelapse.py` looks the camera up by NAME in the webcam
registry, but the touchscreen stores a UUID -> lookup always misses and
falls back to the FIRST webcam. With the Wondermaker+ touchscreen panel
installed, that first entry is the "Touchscreen" camera, so timelapses
record screenshots of the LCD instead of the print. Fix (survives until
someone touches the screen's camera picker again):

```
curl -X POST "http://<printer>/machine/timelapse/settings?camera=camera"
```

Also: `snapshoturl` cannot be set via the settings API (vendor bug:
UnboundLocalError), and `SET_TIMELAPSE_SETUP`'s park options are available
if head-parking per frame is ever wanted (screen sends PARK_ENABLE=False).

## Print start itself

The screen uses the gcode form `SDCARD_PRINT_FILE FILENAME="..."`; the
JSON-RPC equivalent `printer.print.start` works identically. Orca's normal
Moonraker upload-and-print flow needs no change.
