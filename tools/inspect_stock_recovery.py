#!/usr/bin/env python3
"""Extract reviewed 1.1.13 recovery selection evidence; never contact the printer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

CLIENT_SHA = 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
SYMBOLS = {
    '_Z14plr_gcode_pathB5cxx11': (0xe644ff8, 32, 'OBJECT'),
    '_Z13plr_load_AorBv': (0x62ac74, 6520, 'FUNC'),
    '_Z15start_plr_printv': (0x62d91c, 6440, 'FUNC'),
    '_Z11if_need_plrv': (0x62aa34, 576, 'FUNC'),
    '_Z26klipper_ready_init_printerv': (0x641b70, 2924, 'FUNC'),
    '_Z8draw_pop13POP_TYPE_ENUM': (0x5352e0, 44, 'FUNC'),
    'plr_fun_status': (0x385c390, 1, 'OBJECT'),
    'current_extruder_backup': (0xe645710, 4, 'OBJECT'),
    'box_modify_t_backup': (0x385c4e8, 16, 'OBJECT'),
}
WINDOWS = {
    'prompt_enabled_gate': (0x62aa48, 20),
    'prompt_interrupted_comparison': (0x62ab88, 36),
    'prompt_ready_gates': (0x6421a4, 52),
    'prompt_draw': (0x642298, 8),
    'prompt_cancel_prefix': (0x5304e4, 96),
    'capture_resume_head': (0x62d94c, 16),
    'identity_map_before_heating': (0x62daa0, 28),
    'restore_backup_map_before_homing': (0x62df24, 44),
    'select_captured_head_after_homing': (0x62e138, 52),
    'assign_selected_file': (0x62ad70, 20),
    'copy_file_for_metadata': (0x62d96c, 28),
    'select_file_later_in_preparation': (0x62e944, 64),
}
LITERALS = {
    'settings_path': 0x3628a80,
    'section': 0x3628588,
    'file_key': 0x36285b0,
    'missing_file_default': 0x36285c0,
    'select_file_prefix': 0x36289b0,
}


def inspect(path):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CLIENT_SHA:
        raise ValueError('Unsupported client; recovery selection evidence requires exact 1.1.13 ELF')
    found = {}
    for line in subprocess.check_output(['readelf', '-Ws', str(path)], text=True).splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[-1] in SYMBOLS:
            found[fields[-1]] = (int(fields[1], 16), int(fields[2]), fields[3])
    if found != SYMBOLS:
        raise ValueError('Recovery symbol layout differs from reviewed client')
    # Decode direct BL sites in execution-address order. Loops and conditional
    # branches still need review; this list is not a runnable command sequence.
    start, size = 0x62d91c, 6440
    command_calls = []
    for address in range(start, start + size, 4):
        word = int.from_bytes(data[address - 0x400000:address - 0x400000 + 4], 'little')
        if word >> 26 != 0b100101:
            continue
        displacement = word & 0x3ffffff
        if displacement & 0x2000000:
            displacement -= 0x4000000
        if address + displacement * 4 == 0x614338:
            command_calls.append(hex(address))
    return {
        'preparation_command_calls': command_calls,
        'cancel_command': data[0x870718 - 0x400000:].split(b'\0', 1)[0].decode(),
        'client_sha256': digest,
        'symbols': {k: {'address': hex(v[0]), 'size': v[1], 'type': v[2]}
                    for k, v in found.items()},
        'literals': {k: data[a - 0x400000:].split(b'\0', 1)[0].decode()
                     for k, a in LITERALS.items()},
        'prompt_literals': {k: data[a - 0x400000:].split(b'\0', 1)[0].decode()
                            for k, a in {'interrupted_key': 0x3628598,
                                         'missing_default': 0x36285a8,
                                         'required_value': 0x879718}.items()},
        'windows': {k: {'address': hex(a), 'bytes': data[a - 0x400000:a - 0x400000 + n].hex()}
                    for k, (a, n) in WINDOWS.items()},
        'limit': 'Static selection provenance only; does not prove runtime ownership or recovery safety.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    print(json.dumps(inspect(parser.parse_args().client), indent=2))
