# Set print-start options from OrcaSlicer

The printer's bed-leveling and timelapse options can be sent as G-code before
`START_PRINT`. OrcaSlicer's normal Moonraker upload-and-print flow needs no change.


## Filament mapping

Standalone WM+ publishes four physical heads as `wmplus_tool_0` through
`wmplus_tool_3`. These lane identities do not change with the last print's mapping.
Use Orca's **Sync from printer** to refresh the inventory before selecting heads.

The send-time mapping commands are supported without openACE or AFC installed:

```gcode
RESET_AFC_MAPPING
SET_MAP LANE=wmplus_tool_2 MAP=T0
SET_MAP LANE=wmplus_tool_3 MAP=T2
SDCARD_PRINT_FILE FILENAME="example.gcode"
```

This example sends sliced T0 to Head 3 and sliced T2 to Head 4. Mapping changes
require an idle printer. On the touchscreen, check the tool-to-head summary in
the print confirmation before pressing **PRINT**.

## Bed leveling

Send one of these before `START_PRINT`, for example in machine start G-code:

```gcode
G30
```

`G30` requests a fresh mesh. Use `G31` instead to load the saved default mesh.
The fresh mesh may use slicer-supplied bounds, native adaptive probing, or the
full configured area. With WM+, both choices keep a separate recovery copy;
see [mesh handling](print-mesh-recovery.md#bed-mesh-and-tool-reference).

## Timelapse

Enable recording at print start:

```gcode
_SET_TIMELAPSE_SETUP ENABLE=True VERBOSE=False PARK_ENABLE=False
HYPERLAPSE ACTION=STOP
```

Add this to OrcaSlicer's layer-change custom G-code:

```gcode
TIMELAPSE_TAKE_FRAME
```

The installed `moonraker-timelapse` component uses layer-macro mode and automatic
rendering at print end. `TIMELAPSE_RENDER` renders on demand. Output is saved under
`~/printer_data/timelapse/`. `HYPERLAPSE ACTION=STOP` clears an earlier interval-based
recording session; the observed screen sequence sends it before starting a print.

To disable recording, use `_SET_TIMELAPSE_SETUP ENABLE=False`.
The screen sends its setup command when the timelapse toggle changes, so set it
explicitly when you want the slicer to choose the behavior.

## Camera selection

The vendor's timelapse lookup expects a camera name, but the screen stores a camera
UUID. The failed lookup falls back to the first webcam, which can be WM+'s
Touchscreen panel. That records the LCD rather than the print.

The WM+ touchscreen installation resets the timelapse camera to the print camera
on boot. You can also set it manually; replace `camera` if your camera has a
different name:

```bash
curl -X POST 'http://<printer>/machine/timelapse/settings?camera=camera'
```

Using the screen's camera picker afterward can override this again. The vendor's
snapshot-URL settings API raised `UnboundLocalError` in the reviewed version, so
changing that URL through the API is not a workaround.

## Observed screen commands

The captured sequence ended with:

```gcode
HYPERLAPSE ACTION=STOP
G30
SDCARD_PRINT_FILE FILENAME="<file>.gcode"
```

The screen's setup also supplied parking coordinates and movement settings, with
parking disabled. Enable parking only if you want a head move for each frame;
those settings belong to `_SET_TIMELAPSE_SETUP`.

`SDCARD_PRINT_FILE` and the Moonraker JSON-RPC `printer.print.start` method both
start the selected file. For ordinary OrcaSlicer use, retain its existing print
request and put the desired options in the file before `START_PRINT`.
