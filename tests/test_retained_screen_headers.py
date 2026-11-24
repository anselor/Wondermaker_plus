"""Geometry evidence from the pinned factory constructors, not synthetic artwork.

These checks qualify the retained header/body boundaries only. They do not
render assets, prove translated/dynamic text fit, or replace device screenshots.
"""
import hashlib
import json
from pathlib import Path
import struct

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


@pytest.fixture(scope='module')
def factory():
    if not CLIENT.is_file():
        pytest.skip('pinned factory client required for retained constructor audit')
    capstone = pytest.importorskip('capstone')
    data = CLIENT.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest() == profile['client_sha256']
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    loads = [struct.unpack_from('<IIQQQQQQ', data, phoff + index * size)
             for index in range(count)]
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True

    def read(address, length):
        segment = next(s for s in loads if s[0] == 1 and s[3] <= address and address + length <= s[3] + s[5])
        offset = segment[2] + address - segment[3]
        return data[offset:offset + length]

    def arguments(call, target):
        # Execute no code and infer no control flow: assert the exact direct
        # immediate argument setup in the preceding straight-line call window.
        start = call - 24
        segment = next(s for s in loads if s[0] == 1 and s[3] <= start and call + 4 <= s[3] + s[5])
        offset = segment[2] + start - segment[3]
        instructions = list(decoder.disasm(data[offset:offset + 28], start))
        assert instructions[-1].address == call
        assert instructions[-1].mnemonic == 'bl'
        assert instructions[-1].operands[0].imm == target
        result = {}
        for instruction in reversed(instructions[:-1]):
            if instruction.mnemonic == 'bl':
                break
            operands = instruction.operands
            if (instruction.mnemonic == 'mov' and len(operands) == 2
                    and operands[0].type == capstone.arm64.ARM64_OP_REG
                    and operands[1].type == capstone.arm64.ARM64_OP_IMM):
                result.setdefault(instruction.reg_name(operands[0].reg), operands[1].imm)
        return result
    arguments.read = read
    arguments.decode = lambda address, length: list(decoder.disasm(read(address, length), address))
    return arguments


SIZE, POSITION, ALIGN = 0x6a3aa4, 0x6a3318, 0x6a3fdc


def test_factory_content_card_has_one_40_pixel_header(factory):
    assert factory(0x543278, POSITION) == {'w1': 90, 'w2': 55}
    assert factory(0x543288, SIZE) == {'w1': 695, 'w2': 357}
    assert factory(0x5432f0, SIZE) == {'w1': 650, 'w2': 1}
    assert factory(0x543304, ALIGN) == {'w1': 2, 'w2': 0, 'w3': 40}


def test_retained_colour_picker_keeps_back_in_factory_header(factory):
    # 0x27d1 is the retained LVGL content-size sentinel, not pixel width.
    assert factory(0x4f8378, SIZE) == {'w1': 0x27d1, 'w2': 40}
    assert factory(0x4f838c, ALIGN) == {'w1': 3, 'w2': -26, 'w3': 0}
    assert factory(0x4f83f0, ALIGN) == {'w1': 9, 'w2': 0, 'w3': 0}
    assert factory(0x4f84f0, SIZE) == {'w1': 83, 'w2': 83}


def test_retained_text_picker_is_an_entry_above_keys_not_a_second_title(factory):
    assert factory(0x54ec94, SIZE) == {'w1': 800, 'w2': 425}
    assert factory(0x54ecac, POSITION) == {'w1': 0, 'w2': 0}
    assert factory(0x54ed2c, SIZE) == {'w1': 696, 'w2': 357}
    assert factory(0x54ed3c, POSITION) == {'w1': 89, 'w2': 55}
    assert factory(0x54efcc, SIZE) == {'w1': 685, 'w2': 44}
    assert factory(0x54efe4, POSITION) == {'w1': 5, 'w2': 12}
    assert factory(0x54f060, SIZE) == {'w1': 690, 'w2': 280}
    assert factory(0x54f078, POSITION) == {'w1': 6, 'w2': 64}
    assert 12 + 44 <= 64  # Entry ends above the keys, inside the same card.


def test_retained_maintenance_keeps_title_and_back_above_body(factory):
    assert factory(0x4b6550, ALIGN) == {'w1': 1, 'w2': 33, 'w3': 12}
    assert factory(0x4b6624, SIZE) == {'w1': 0x27d1, 'w2': 40}
    assert factory(0x4b6640, ALIGN) == {'w1': 3, 'w2': -26, 'w3': 0}
    assert factory(0x4b66e8, SIZE) == {'w1': 693, 'w2': 314}
    assert factory(0x4b66fc, ALIGN) == {'w1': 2, 'w2': 0, 'w3': 41}


def test_retained_preview_keeps_filename_and_actions_above_thumbnail(factory):
    assert factory(0x5378b0, ALIGN) == {'w1': 1, 'w2': 33, 'w3': 12}
    assert factory(0x5378e8, SIZE) == {'w1': 0x27d1, 'w2': 40}
    assert factory(0x53792c, ALIGN) == {'w1': 3, 'w2': -26, 'w3': 0}
    assert factory(0x537b24, SIZE) == {'w1': 149, 'w2': 149}
    assert factory(0x537b34, POSITION) == {'w1': 60, 'w2': 66}
    # The WM+ informational row occupies y42..66, beneath this 40px header
    # and above the retained thumbnail. Full dynamic text fit is separate.


def test_factory_maintenance_title_is_blank_and_refresh_updates_body_labels(factory):
    instructions = factory.decode(0x4b64a4, 0x34)
    assert [(i.mnemonic, i.op_str) for i in instructions[:6]] == [
        ('ldr', 'x0, [sp, #0x88]'), ('bl', '#0x6d96ac'),
        ('mov', 'x1, x0'), ('adrp', 'x0, #0x385f000'),
        ('add', 'x0, x0, #0xc28'), ('str', 'x1, [x0]')]
    assert factory.read(0x365a4d0, 1) == b'\0'
    refresh = factory.decode(0x4b6c8c, 0x8cc)
    assert not any(i.mnemonic == 'add' and i.op_str == 'x0, x0, #0xc28' for i in refresh)
    assert any(i.mnemonic == 'add' and i.op_str == 'x0, x0, #0xc90' for i in refresh)
