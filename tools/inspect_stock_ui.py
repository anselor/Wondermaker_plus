#!/usr/bin/env python3
"""Export named stock UI symbols for offline in-place integration review.

No printer connection, binary modification, or runtime pointer dereference.
Names/addresses are review evidence, not permission to call or patch functions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct

CLIENT_SHA = 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
CXX_STRING = "std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >"
FUNCTIONS = (
    "copy_to_local()", "start_print_prepare()",
    f"copy_a_file_or_directory({CXX_STRING}, {CXX_STRING})",
    f"json_copy_a_file_or_directory({CXX_STRING}, {CXX_STRING})",
    f"start_printing({CXX_STRING})",
    'setup_screen_filament(_lv_obj_t*)', 'screen_filament_refresh()',
    'color_select_event_handler(_lv_event_t*)', 'draw_choose_color(_lv_obj_t*)',
    'materials_select_event_handler(_lv_event_t*)', 'draw_choose_materials(_lv_obj_t*)',
    'draw_sidebar(_lv_obj_t*, unsigned char)',
    'draw_setting_menu(_lv_obj_t*, unsigned char)', 'draw_content_bg(_lv_obj_t*)',
    'setup_screen_main(_lv_obj_t*)', 'draw_preview(_lv_obj_t*)',
    'lvgl_style_init()', 'lv_obj_align', 'lv_obj_set_size',
    'lv_obj_remove_event_cb_with_user_data', 'lv_obj_get_event_user_data',
    'draw_number_keyboard(_lv_obj_t*)',
)
GLOBALS = {
    0xe643270: "if_usb_path", 0xe643278: "gcode_print_path[abi:cxx11]",
    0xe6497d8: "current_copying_file_name[abi:cxx11]",
    0x386ee1c: "copying_file_result",
    0x386ee30: 'current_screen', 0x386ee38: 'content_bg',
    0x386ee40: 'label_tips', 0x386ee48: 'btn_leveling',
    0x386ee58: 'btn_Knife_pairing', 0x386ee68: 'btn_Time_lapse',
    0x386eeb8: 'gcode_color', 0x386ef58: 'local_color',
    0x3862b08: 'current_screen', 0x3862b10: 'label_tips',
    0x3862b18: 'btn_group', 0x3862b20: 'obj',
    0x3862b40: 'img_number_icon', 0x3862b60: 'btn_current_color',
    0x3862b80: 'btn_current_materials', 0x3862ba0: 'label_current_materials',
    0x3862f58: 'filament_screen_bg',
    0x3862bc0: 'background_edit', 0x3862f60: 'edit_filament_info',
    0x3862f68: 'edit_index',
    0x463c8d8: 'background_style', 0x463c8e8: 'btn_style',
    0x463c8f8: 'click_style', 0x463c908: 'obj_style_re',
    0x463c918: 'obj_style_pr', 0x26297a0: 'MyriadPro_Regular_16',
    0x386dc68: 'g_mask', 0x386dc70: 'keyboard_textarea',
    0x463c8d0: 'keyboard_edit_type',
}
CALLBACKS = {
    0x536958: 'event_handler(_lv_event_t*)',
    0x519a34: 'event_handler(_lv_event_t*)',
    0x52da0c: 'btn_event_handler(_lv_event_t*)',
    0x52db58: 'textarea_event_handler(_lv_event_t*)',
}

def inspect(path):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != CLIENT_SHA:
        raise ValueError('Unsupported stock client; no symbol map emitted')
    rows = []
    for line in subprocess.check_output(['nm', '-n', '-C', '-S', str(path)], text=True).splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) != 4:
            continue
        try:
            address, size = int(fields[0], 16), int(fields[1], 16)
        except ValueError:
            continue
        name = fields[3]
        if name in FUNCTIONS or GLOBALS.get(address) == name or CALLBACKS.get(address) == name:
            rows.append(dict(name=name, address=hex(address), size=size, type=fields[2]))
    found = {r['name'] for r in rows}
    missing = set(FUNCTIONS).union(GLOBALS.values()) - found
    if missing:
        raise ValueError('Missing expected stock symbols: ' + ', '.join(sorted(missing)))
    for address, name in {**GLOBALS, **CALLBACKS}.items():
        if not any(r['address'] == hex(address) and r['name'] == name for r in rows):
            raise ValueError('Missing address-specific stock symbol: ' + hex(address))
    # Exact-client RX mapping is VA - 0x400000. Verify direct call evidence
    # rather than treating nearby function names as proof of the copy path.
    calls = []
    for site, target in ((0x53a620, 0x6145ac), (0x6145f4, 0x559098),
                         (0x614630, 0x5809c8), (0x53a1f8, 0x6146b8)):
        instruction = struct.unpack_from('<I', data, site - 0x400000)[0]
        displacement = instruction & 0x3ffffff
        if displacement & (1 << 25):
            displacement -= 1 << 26
        if instruction >> 26 != 0b100101 or site + displacement * 4 != target:
            raise ValueError(f'Unexpected USB/start call at {site:#x}')
        calls.append(dict(site=hex(site), target=hex(target)))
    for address, expected in ((0x36120c8, b'source'), (0x36120d0, b'dest'),
                              (0x874f78, b'gcodes/USB/'), (0x874f70, b'gcodes/')):
        offset = address - 0x400000
        if data[offset:offset + len(expected) + 1] != expected + b'\0':
            raise ValueError(f'Unexpected USB copy field/path at {address:#x}')
    usb_copy = dict(calls=calls, source_prefix='gcodes/USB/', dest_prefix='gcodes/',
                    confirmation='current_copying_file_name compared by copy_to_local',
                    limitations=['Filename collision policy is not established.',
                                 'Copy acknowledgement is not print admission.',
                                 'No USB-to-unified-preview adapter is activated.'])
    return dict(client_sha256=digest, scope='offline-review-only', symbols=rows, usb_copy=usb_copy,
                limitations=['Symbol presence does not prove runtime object lifetime or parentage.',
                              'Callbacks and stock refresh writers require separate review.',
                              'No executable hooks or activation included.'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = inspect(args.client)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('Verified stock UI symbol map:', args.output)
