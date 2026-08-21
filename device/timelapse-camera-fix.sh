#!/bin/sh
# Wondermaker+ : force the moonraker-timelapse camera to the real webcam.
#
# Installing the Wondermaker+ touchscreen panel registers a "Touchscreen"
# webcam. The vendor timelapse component looks its configured camera up by
# NAME, but the screen stores a UUID, so the lookup misses and it falls back
# to the FIRST webcam — now the "Touchscreen" LCD mirror. Result: timelapses
# record the screen instead of the print. This forces the setting back to the
# webcam named "camera" after every boot, self-healing even if the screen's
# camera picker is touched. Override the target with WMP_TIMELAPSE_CAMERA.
set -eu
CAM="${WMP_TIMELAPSE_CAMERA:-camera}"
MOONRAKER="${WMP_MOONRAKER:-http://127.0.0.1:7125}"
i=0
while [ "$i" -lt 60 ]; do
    if curl -sf -m 3 "$MOONRAKER/server/info" >/dev/null 2>&1; then break; fi
    i=$((i+1)); sleep 2
done
curl -sf -m 5 -X POST "$MOONRAKER/machine/timelapse/settings?camera=$CAM" \
    >/dev/null 2>&1 && echo "wmp-timelapse-camera: timelapse camera -> $CAM" \
    || echo "wmp-timelapse-camera: failed to set camera (Moonraker unreachable?)"
