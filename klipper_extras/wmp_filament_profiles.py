# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone filament profile storage. No printer commands or motion ownership."""
import configparser
import copy
import hashlib
import json
import math
import re

try:
    from .wmp_persistence import atomic_write
    from .wmp_filament_types import MATERIALS, material_name
except ImportError:
    from wmp_persistence import atomic_write
    from wmp_filament_types import MATERIALS, material_name


def validate_identity(identity):
    if not isinstance(identity, dict) or (not {"brand", "material", "color"}.issubset(identity) or set(identity) - {"brand", "material", "color", "nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"}):
        raise ValueError("Filament needs brand, material and color")
    for key in ("nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"):
        if key in identity and (type(identity[key]) not in (int, float) or not math.isfinite(identity[key]) or not 0 <= identity[key] <= (150 if key == "bed_temp" else 350)):
            raise ValueError("Invalid filament temperature")
    if identity.get("nozzle_temp_min", 0) > identity.get("nozzle_temp_max", 350):
        raise ValueError("Filament temperature minimum exceeds maximum")
    for field in ("brand", "material"):
        value = identity[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid filament " + field)
    if not isinstance(identity["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", identity["color"]):
        raise ValueError("Color must be #RRGGBB")


def read_legacy(path, read_variables):
    """Project stock logical slots onto unambiguous physical heads."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as stream:
            text = stream.read(65537)
    except FileNotFoundError:
        return {}
    if len(text) > 65536:
        raise ValueError("Stock filament settings file is too large")
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read_string(text)
    except configparser.Error as error:
        raise ValueError("Invalid stock filament settings: " + str(error))
    if not ini.has_section("slot"):
        return {}
    variables = read_variables()
    colours = ("#ffffff", "#e7ceb5", "#714623", "#97999b", "#0c0809", "#49c5b1",
               "#009cde", "#03257e", "#00b140", "#265b31", "#fce300", "#fe5000",
               "#f5b6cd", "#e10098", "#cd001a", "#5f249f")
    custom_colours = {}
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
        match = re.fullmatch(r";\s*orca-color([0-3])\s*=\s*(#[0-9a-fA-F]{6})", line)
        if section == "slot" and match:
            custom_colours[int(match[1])] = match[2]
    profiles, ambiguous = {}, set()
    for slot in range(4):
        head = variables.get("box_modify_t%d" % slot, slot)
        if type(head) is not int or not 0 <= head < 4:
            continue
        key = "h%d" % head
        try:
            material = ini.getint("slot", "material%d" % slot)
            colour = ini.getint("slot", "color%d" % slot)
        except (ValueError, configparser.Error):
            continue
        rgb = custom_colours.get(slot, colours[colour] if 0 <= colour < len(colours) else None)
        if not 0 <= material < len(MATERIALS) or rgb is None:
            continue
        identity = {"brand": "Generic", "material": material_name(material), "color": rgb}
        if key in profiles and profiles[key] != identity:
            ambiguous.add(key)
        profiles[key] = identity
    return {key: value for key, value in profiles.items() if key not in ambiguous}


class ProfileStore:
    def __init__(self, path):
        self.path = path
        self.raw = {}
        self.errors = {}

    def read(self, legacy, validate):
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                text = stream.read(16385)
            if len(text) > 16384:
                raise ValueError("Filament settings file is too large")
        except FileNotFoundError:
            text = None
        legacy = legacy() if text is None else None
        cache_key = (text, legacy)
        # Read every time: external edits must invalidate admission revisions,
        # including same-size edits with unchanged timestamps. Cache only the
        # validation/serialization work, never the file or mutable caller data.
        cached = getattr(self, "_cache", None)
        if cached is not None and cached[0] == cache_key:
            self.raw = copy.deepcopy(cached[3])
            self.errors = copy.deepcopy(cached[4])
            return copy.deepcopy(cached[1]), cached[2]
        raw = legacy or {}
        if text is not None:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("Invalid filament settings file")
        profiles, errors = {}, {}
        for head, identity in raw.items():
            try:
                if head not in ("h0", "h1", "h2", "h3"):
                    raise ValueError("Invalid physical head in settings")
                validate(identity)
            except ValueError as error:
                errors[head] = "%s: %s (entry preserved)" % (head, error)
            else:
                profiles[head] = identity
        # Bind Save to every entry, including unreadable entries. An unrelated
        # save must preserve those entries instead of silently dropping them.
        revision = hashlib.sha256(json.dumps(raw, sort_keys=True,
                                            ensure_ascii=True).encode()).hexdigest()
        self.raw = copy.deepcopy(raw)
        self.errors = errors
        self._cache = (copy.deepcopy(cache_key), copy.deepcopy(profiles), revision,
                                copy.deepcopy(raw), copy.deepcopy(errors))
        return profiles, revision


    def write(self, profiles):
        payload = json.dumps(profiles, sort_keys=True, ensure_ascii=True) + "\n"
        atomic_write(self.path, payload, ".wmp-filaments-")
