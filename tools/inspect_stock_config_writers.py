#!/usr/bin/env python3
"""Read-only, exact-firmware provenance for remaining stock configuration callers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from inspect_stock_recovery import CLIENT_SHA

# Each mode assignment is MOV W1, #mode immediately before the head argument
# and BL. These are direct callers, not a claim to enumerate indirect calls.
CALLS = (
    ("identification_read_1", 0x510798, 0, 0x5107a0, 0x52b24c),
    ("identification_read_2", 0x510a70, 0, 0x510a78, 0x52b24c),
    ("identification_read_3", 0x510bf0, 0, 0x510bf8, 0x52b24c),
    ("identification_write_1", 0x510f2c, 1, 0x510f34, 0x52b24c),
    ("identification_write_2", 0x5110b4, 1, 0x5110bc, 0x52b24c),
    ("nozzle_editor_write", 0x52bfc8, 1, 0x52bfd0, 0x52d02c),
    ("startup_diameter_read", 0x626be4, 0, 0x626bec, 0x52d02c),
    ("firmware_diameter_write", 0x659e70, 1, 0x659e78, 0x52d02c),
)
LITERALS = {
    "diameter_script": 0x87be30,
    "identity_script": 0x87bab8,
    "model_enable": 0x3628208,
    "model_disable": 0x3628240,
    "nozzle_editor_page": 0x881160,
    "model_settings_file": 0x870bd8,
    "model_settings_section": 0x3628078,
    "model_settings_key": 0x3628080,
}


def inspect(path):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CLIENT_SHA:
        raise ValueError("Unsupported client; requires exact reviewed 1.1.13 ELF")

    def word(address):
        return struct.unpack_from("<I", data, address - 0x400000)[0]

    calls = {}
    for name, assignment, mode, call, target in CALLS:
        if word(assignment) != 0x52800001 | (mode << 5):
            raise ValueError("Unexpected mode assignment: " + name)
        instruction = word(call)
        immediate = instruction & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if instruction >> 26 != 0b100101 or call + immediate * 4 != target:
            raise ValueError("Unexpected direct call: " + name)
        calls[name] = {"mode": mode, "assignment": hex(assignment),
                       "call": hex(call), "target": hex(target)}
    return {
        "client_sha256": digest,
        "calls": calls,
        "literals": {name: data[a - 0x400000:].split(b"\0", 1)[0].decode()
                     for name, a in LITERALS.items()},
        "model_shell_returns": ["0x626da8", "0x626e18"],
        "model_selection": {
            "read_call": "0x625670", "integer_default": 2,
            "recognized_values": [1, 2], "other_integer_fallback": 1,
            "enable_include_when": 2, "branch": "0x626cec",
        },
        "nozzle_editor": {
            "general_navigation_call": "0x547984",
            "page_registration_call": "0x553924",
            "setup": "0x52c070",
            "event_handler": "0x52bce0",
            "material_click_userdata": [5, 6],
            "material_ini_write_call": "0x52bf04",
            "diameter_click_userdata": [7, 8, 9, 10],
            "diameter_write_call": "0x52bfd0",
            "save_step": False,
        },
        "limit": "Static direct-call provenance only; no claim of live reachability, "
                 "indirect-call completeness, or managed ownership qualification.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", type=Path)
    print(json.dumps(inspect(parser.parse_args().client), indent=2))
