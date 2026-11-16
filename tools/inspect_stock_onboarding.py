#!/usr/bin/env python3
"""Capture the verified stock filament wizard's entry points for offline review.

This does not patch the client, emulate instructions, or contact a printer.
The byte windows are evidence for branch review, not proof of runtime behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CLIENT_SHA = 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
ENTRIES = {
    'language_event': (0x50f0a4, 596),
    'wifi_event': (0x513c64, 468),
    'bed_unlock_event': (0x512fd4, 244),
    'identification_event': (0x50fb24, 116),
    'calibration_selection_event': (0x50b7f8, 468),
    'calibration_finish_event': (0x50c3fc, 88),
    'filament_event': (0x50c9bc, 1672),
    'setup_filament_guide': (0x50d044, 56),
    'refresh_filament_guide': (0x50e520, 796),
    'load_worker': (0x50e83c, 1204),
    'retry_worker': (0x50ecf0, 596),
}
LITERALS = {
    'wifi_destination': 0x876ad0,
    'bed_unlock_destination': 0x877c18,
    'identification_destination': 0x877658,
    'calibrating_destination': 0x8759a0,
    'filament_destination': 0x8759b8,
    'finish_marker_command': 0x874e38,
    'finish_destination': 0x871778,
    'all_heads_destination': 0x876498,
    'load_event_name': 0x876468,
    'retry_event_name': 0x8764b0,
    'heater_prefix': 0x873f68,
    'heater_off_suffix': 0x873f70,
}


def inspect(path):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CLIENT_SHA:
        raise ValueError('Unsupported client; onboarding addresses are specific to 1.1.13')
    symbols = {}
    for line in subprocess.check_output(['readelf', '-Ws', str(path)], text=True).splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[3] == 'FUNC' and int(fields[2]):
            symbols[int(fields[1], 16)] = (int(fields[2]), fields[-1])
    entries = {}
    for label, (address, size) in ENTRIES.items():
        actual = symbols.get(address)
        if not actual or actual[0] != size:
            raise ValueError('Entry symbol/size mismatch: ' + label)
        raw = data[address - 0x400000:address - 0x400000 + size]
        # Decode direct AArch64 BL targets only. Indirect/queued callbacks and
        # conditional ordering still require instruction-level review.
        calls = []
        for offset in range(0, len(raw), 4):
            instruction = int.from_bytes(raw[offset:offset + 4], 'little')
            if instruction >> 26 != 0b100101:
                continue
            displacement = instruction & 0x3ffffff
            if displacement & 0x2000000:
                displacement -= 0x4000000
            target = address + offset + displacement * 4
            calls.append({'at': hex(address + offset), 'target': hex(target),
                          'symbol': symbols.get(target, (0, None))[1]})
        entries[label] = {'address': hex(address), 'size': size, 'symbol': actual[1],
                          'sha256': hashlib.sha256(raw).hexdigest(),
                          'entry_bytes': raw[:32].hex(), 'direct_calls': calls}
    return {'client_sha256': digest, 'entries': entries,
            'literals': {name: data[address - 0x400000:].split(b'\0', 1)[0].decode()
                         for name, address in LITERALS.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.client), indent=2))
