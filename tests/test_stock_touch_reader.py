"""Characterize the exact 1.1.13 reader, without changing printer input handling.

These tests reproduce vendor behavior; a passing loss test is evidence of a bug,
not acceptance of touch responsiveness or proof of a particular live incident.
"""
import hashlib
import json
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reader():
    unicorn = pytest.importorskip('unicorn')
    from unicorn import arm64_const as reg
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.is_file():
        pytest.skip('exact vendor 1.1.13 client required')
    data = client.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest() == profile['client_sha256']
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    cpu.mem_map(0x73c000, 0x1000)
    cpu.mem_write(0x73c000, data[0x33c000:0x33d000])
    for address, size in ((0x446000, 0x1000), (0x385d000, 0x1000),
                          (0xff50000, 0x1000), (0x5000000, 0x4000)):
        cpu.mem_map(address, size)
    driver, output, display, display_driver = (0x5000000, 0x5000100, 0x5000200, 0x5000300)
    cpu.mem_write(driver, struct.pack('<I', 1))  # LV_INDEV_TYPE_POINTER
    cpu.mem_write(driver + 32, struct.pack('<Q', display))
    cpu.mem_write(display, struct.pack('<Q', display_driver))
    cpu.mem_write(display_driver, struct.pack('<hh', 800, 480))
    queued = []

    def hook(cpu, address, size, _):
        if address != 0x446340:  # read@plt: deterministic Linux input_event source
            return
        assert cpu.reg_read(reg.UC_ARM64_REG_X2) == 24
        if queued:
            cpu.mem_write(cpu.reg_read(reg.UC_ARM64_REG_X1), queued.pop(0))
            cpu.reg_write(reg.UC_ARM64_REG_X0, 24)
        else:
            cpu.reg_write(reg.UC_ARM64_REG_X0, (1 << 64) - 1)  # EAGAIN
        cpu.reg_write(reg.UC_ARM64_REG_PC, cpu.reg_read(reg.UC_ARM64_REG_LR))
    cpu.hook_add(unicorn.UC_HOOK_CODE, hook)

    def read(events):
        queued.extend(struct.pack('<qqHHi', 0, 0, *event) for event in events)
        cpu.mem_write(output, b'\0' * 24)
        cpu.reg_write(reg.UC_ARM64_REG_SP, 0x5003f00)
        cpu.reg_write(reg.UC_ARM64_REG_X0, driver)
        cpu.reg_write(reg.UC_ARM64_REG_X1, output)
        cpu.reg_write(reg.UC_ARM64_REG_LR, 0x5001000)
        cpu.emu_start(0x73ca44, 0x5001000, count=10000)
        assert cpu.reg_read(reg.UC_ARM64_REG_PC) == 0x5001000
        assert not queued
        x, y = struct.unpack('<hh', cpu.mem_read(output, 4))
        pressed, = struct.unpack('<I', cpu.mem_read(output + 16, 4))
        return x, y, pressed
    return read


PRESS = [(3, 0, 685), (3, 1, 441), (1, 330, 1), (0, 0, 0)]
RELEASE = [(1, 330, 0), (0, 0, 0)]


def test_press_and_release_in_separate_polls_are_observable(reader):
    assert reader(PRESS) == (685, 441, 1)
    assert reader(RELEASE) == (685, 441, 0)


def test_queued_complete_tap_is_lost_by_vendor_reader(reader):
    assert reader(PRESS + RELEASE) == (685, 441, 0)
    # No delayed press is returned on the next poll either.
    assert reader([]) == (685, 441, 0)


def test_two_queued_complete_taps_are_both_lost(reader):
    assert reader(PRESS + RELEASE + PRESS + RELEASE) == (685, 441, 0)
    assert reader([]) == (685, 441, 0)
