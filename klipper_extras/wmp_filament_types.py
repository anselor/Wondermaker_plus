# SPDX-License-Identifier: GPL-3.0-or-later
"""Material identities, stock slot parsing and filament transition policy."""
import re

# Material table hardcoded in the touchscreen binary (client 1.1.04,
# `materials_str` + `fila_extrude_temp`, recovered with Ghidra).
MATERIALS = [
    ("PLA", 220), ("PLA Silk", 220), ("ABS", 250), ("PETG", 250),
    ("PLA Matte", 220), ("PLA Metal", 220), ("ABS Matte", 250),
    ("PETG Matte", 250), ("PVA", 220), ("TPE", 230), ("Marble", 220),
    ("HIPS", 250), ("TPU", 230), ("PET", 300), ("Wood", 220), ("ASA", 260),
    ("PA", 260), ("PC", 270),
    # WM+ additions. Append to preserve stock numeric material indices.
    # Starting service temperatures; spool-specific settings can override loading.
    ("PCTG", 260), ("PA6", 260), ("PA12", 260), ("PP", 240),
]
# Generic starting ranges, not certification for a brand/formulation. Provenance:
# OrcaSlicer e23af6d7b075ab6e317485551c7cbee33d1b4c4b, BBL fdm_filament_*
# presets (PLA inherits common). See docs/ui/standalone-filament-management.md.
GENERIC_NOZZLE_RANGES = {
    "PLA": (190, 240), "PLA SILK": (190, 240), "PLA MATTE": (190, 240),
    "PLA METAL": (190, 240), "ABS": (240, 280), "ABS MATTE": (240, 280),
    "ASA": (240, 280), "PETG": (220, 260), "PETG MATTE": (220, 260),
    "PCTG": (220, 260), "TPU": (200, 250), "PVA": (190, 240),
    "HIPS": (220, 270), "PA": (260, 300), "PA6": (260, 300),
    "PA12": (260, 300), "PC": (260, 290), "PP": (220, 250),
}
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


def material_temperature_range(identity):
    """Use generic swap ranges; spool printing bounds are fallback only."""
    material = identity["material"].upper()
    fallback = GENERIC_NOZZLE_RANGES.get(material) or GENERIC_NOZZLE_RANGES.get(material_family(identity))
    if fallback is not None:
        return fallback[0], fallback[1], "generic"
    if fallback is None:
        recipe = dict((name.upper(), temp) for name, temp in MATERIALS).get(material)
        if recipe is not None:
            fallback = (recipe, recipe)
    low, high = identity.get("nozzle_temp_min", 0), identity.get("nozzle_temp_max", 0)
    explicit = bool(low and high)
    if fallback is not None:
        low, high = low or fallback[0], high or fallback[1]
    if not (0 < low <= high):
        raise ValueError("Set a valid nozzle temperature range for " + identity["material"])
    return low, high, "spool" if explicit else "generic" if material in GENERIC_NOZZLE_RANGES else "recipe-only"


def material_family(identity):
    """Group finish/filler variants without conflating distinct polymers."""
    name = str(identity.get("material", "")).strip().upper()
    return re.split(r"[\s-]+", name, maxsplit=1)[0]


def cross_family_purge(identity, previous):
    # Unknown residue cannot establish that a same-family purge is sufficient.
    incoming = material_family(identity)
    if not incoming or not previous or previous.get("unknown_residue"):
        return True
    residual = previous.get("materials", [])
    return not residual or any(material_family(old) != incoming for old in residual)


def transition_temperature(identity, previous, default_target):
    """Return a target and explanation without inventing missing spool limits."""
    if previous is None:
        return default_target, "Previous nozzle material is unknown; using the incoming filament temperature."
    residual = previous["materials"]
    unknown_note = " Additional previous residue is unknown." if previous.get("unknown_residue") else ""
    # A same-material/color-only reload retains its normal service temperature.
    thermal_keys = ("material", "nozzle_temp", "nozzle_temp_min", "nozzle_temp_max")
    if all(all(old.get(k) == identity.get(k) for k in thermal_keys) for old in residual):
        return default_target, unknown_note.strip()
    ranges = []
    range_sources = set()
    for item in [identity] + residual:
        low, high, source = material_temperature_range(item)
        range_sources.add(source)
        ranges.append((low, high))
    low, high = max(r[0] for r in ranges), min(r[1] for r in ranges)
    if low > high:
        raise ValueError("No shared nozzle temperature range; this material change needs a transition recipe")
    recipes = dict((name.upper(), temp) for name, temp in MATERIALS)
    old_targets = [item.get("nozzle_temp") or recipes.get(item["material"].upper()) for item in residual]
    if any(t is None for t in old_targets):
        target = low  # Residue's required lower bound, not an invented incoming default.
    elif all(t is not None and t > default_target for t in old_targets):
        target = high  # Cooler incoming material: use the upper shared limit.
    elif all(t is not None and t < default_target for t in old_targets):
        target = low   # Hotter incoming material: use the lower shared limit.
    else:
        target = min(high, max(low, default_target))
    defaults_note = " Uses generic material ranges." if "generic" in range_sources else ""
    if "recipe-only" in range_sources:
        defaults_note += " A material has only a service-temperature default."
    return target, ("Material transition: %g C within the shared %g–%g C range." % (target, low, high)) + defaults_note + unknown_note




class FilamentCancelled(Exception):
    pass
