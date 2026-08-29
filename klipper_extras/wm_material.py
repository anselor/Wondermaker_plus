# wm_material: expose the WonderMaker touchscreen's per-slot filament material
# to Klipper macros.
#
# The touchscreen app (client) keeps the material of each of the four slots in
# its own ini file (`[slot] material0..3 = <index>`), and never passes it to
# the unload macros. This module reads that file and publishes it as a printer
# object so Jinja can do `printer.wm_material.material1` -> "PETG".
#
# Optional: printer.cfg includes `wm_material*.cfg` with a glob, so when this
# module (and its cfg) are not installed nothing references it and macros fall
# back to inferring the material from the hotend temperature.
#
# Install with `tools/deploy_material.py install` (copies this file into
# klippy/extras and drops wm_material.cfg into the config dir).
#
# Copyright (C) 2026  Wondermaker+ contributors
# This file may be distributed under the terms of the GNU GPLv3 license.
import os

# Material table hardcoded in the touchscreen binary (client 1.1.04,
# `materials_str` + `fila_extrude_temp`, recovered with Ghidra).
MATERIALS = [
    ("PLA", 220), ("PLA Silk", 220), ("ABS", 250), ("PETG", 250),
    ("PLA Matte", 220), ("PLA Metal", 220), ("ABS Matte", 250),
    ("PETG Matte", 250), ("PVA", 220), ("TPE", 230), ("Marble", 220),
    ("HIPS", 250), ("TPU", 230), ("PET", 300), ("Wood", 220), ("ASA", 260),
    ("PA", 260), ("PC", 270),
]
SLOTS = 4
DEFAULT_INI = "~/printer_data/config/tmt1.ini"


def parse_slot_materials(text):
    """Return {slot: material_index} from the `[slot]` section of tmt1.ini.

    Tolerant of comments (`;`/`#`), blank lines and unknown keys. Slots that
    are missing or unparsable are omitted.
    """
    result = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in ";#":
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        if section != "slot" or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        if not key.startswith("material"):
            continue
        try:
            slot = int(key[len("material"):])
            result[slot] = int(value.strip())
        except ValueError:
            continue
    return result


def material_name(index):
    if 0 <= index < len(MATERIALS):
        return MATERIALS[index][0]
    return "Unknown"


def material_temp(index):
    if 0 <= index < len(MATERIALS):
        return MATERIALS[index][1]
    return 0


class WMMaterial:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.ini_path = os.path.expanduser(
            config.get("ini_path", DEFAULT_INI))
        self._mtime = None
        self._slots = {}
        self.printer.register_event_handler("klippy:ready", self._refresh)
        gcode = self.printer.lookup_object("gcode")
        gcode.register_command("WM_MATERIAL_STATUS", self.cmd_STATUS,
                               desc=self.cmd_STATUS_help)

    def _refresh(self, eventtime=None):
        try:
            mtime = os.path.getmtime(self.ini_path)
        except OSError:
            self._mtime, self._slots = None, {}
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.ini_path, "r", errors="replace") as f:
                self._slots = parse_slot_materials(f.read())
            self._mtime = mtime
        except OSError:
            self._mtime, self._slots = None, {}

    def get_status(self, eventtime):
        self._refresh()
        status = {"available": self._mtime is not None,
                  "ini_path": self.ini_path}
        for slot in range(SLOTS):
            idx = self._slots.get(slot, -1)
            status["index%d" % slot] = idx
            status["material%d" % slot] = material_name(idx)
            status["temp%d" % slot] = material_temp(idx)
        return status

    cmd_STATUS_help = "Report the touchscreen's per-slot filament material"

    def cmd_STATUS(self, gcmd):
        st = self.get_status(None)
        if not st["available"]:
            gcmd.respond_info("wm_material: %s not readable" % self.ini_path)
            return
        gcmd.respond_info("wm_material: " + ", ".join(
            "T%d=%s(%d)" % (s, st["material%d" % s], st["index%d" % s])
            for s in range(SLOTS)))


def load_config(config):
    return WMMaterial(config)
