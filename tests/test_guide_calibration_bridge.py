"""Frozen stock selection/entry evidence for the shared guide worker bridge."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


def client():
    if not CLIENT.is_file(): pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    return data


@pytest.mark.parametrize('mask', range(1, 16))
def test_shared_status_choice_matches_actual_maintenance_start_branch(mask):
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_SP
    data = client()
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    cpu.mem_map(0x4b4000, 0x1000)
    cpu.mem_write(0x4b4000, data[0xb4000:0xb5000])
    cpu.mem_map(0x385f000, 0x2000)
    cpu.mem_map(0x5000000, 0x2000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x5001000)
    cpu.mem_write(0x385fa88, bytes((mask >> index) & 1 for index in range(4)))
    cpu.emu_start(0x4b4830, 0x4b490c, count=200)
    observed = int.from_bytes(cpu.mem_read(0x385fc18, 4), 'little')
    first = next(index for index in range(4) if mask & (1 << index))
    assert observed == 1 + 3 * first


def test_guide_selection_hook_has_a_relocatable_verified_prologue():
    data = client()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    entry = next(row for row in profile['functions'] if row['name'] == 'guide_calibration_event')
    assert entry['address'] == '0x50b7f8'
    prologue = data[0x10b7f8:0x10b808]
    assert prologue == bytes.fromhex(entry['bytes'])[:16]
    # stp x29/x30,[sp,#-144]!; mov x29,sp; str x19,[sp,#16]; str x0,[sp,#40]
    assert [int.from_bytes(prologue[i:i+4], 'little') for i in range(0,16,4)] == [
        0xa9b77bfd, 0x910003fd, 0xf9000bf3, 0xf90017e0]


def test_all_retired_guide_command_sites_are_actual_stock_sender_calls():
    data = client()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    calls = [row for row in profile['functions'] if row['name'].startswith('guide_calibration_sender_')]
    assert len(calls) == 16
    for row in calls:
        address = int(row['address'], 16)
        word = int.from_bytes(data[address-0x400000:address-0x400000+4], 'little')
        assert word >> 26 == 0b100101
        offset = word & 0x3ffffff
        if offset & (1 << 25): offset -= 1 << 26
        assert address + offset * 4 == 0x614338
