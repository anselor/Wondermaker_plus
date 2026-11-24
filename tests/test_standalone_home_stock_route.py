"""Freeze standalone homing command boundaries before adding owned cancellation."""
import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


def stock():
    if not CLIENT.is_file():
        pytest.skip('retained supported vendor client required')
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    return data


@pytest.mark.parametrize('worker,sender,call,literal,command', [
    (0x52810c, 0x614f74, 0x614fa8, 0x3626738, b'G28 X\n'),
    (0x52834c, 0x614ff0, 0x615024, 0x3626740, b'G28 Y\n'),
    (0x528590, 0x614ef8, 0x614f2c, 0x3626728, b'G28 X Y\n'),
    (0x5287e0, 0x61506c, 0x6150a0, 0x3626748, b'G28 Z\n'),
    (0x528a30, 0x614e7c, 0x614eb0, 0x3626720, b'G28\n'),
])
def test_standalone_workers_submit_exact_axis_command(worker, sender, call, literal, command):
    from io import BytesIO
    elf = pytest.importorskip('elftools.elf.elffile').ELFFile(BytesIO(stock()))

    def read(address, size):
        for segment in elf.iter_segments():
            start = segment['p_vaddr']
            if segment['p_type'] == 'PT_LOAD' and start <= address and address + size <= start + segment['p_filesz']:
                return segment.data()[address-start:address-start+size]
        raise AssertionError('address outside file-backed segments')

    def branch_target(address):
        word = int.from_bytes(read(address, 4), 'little')
        assert word >> 26 == 0b100101
        offset = word & 0x3ffffff
        if offset & (1 << 25):
            offset -= 1 << 26
        return address + offset * 4

    assert branch_target(worker + 12) == sender
    assert branch_target(call) == 0x614338
    assert read(literal, len(command) + 1) == command + b'\0'


@pytest.mark.parametrize('action,worker', [(10,0x52810c),(11,0x52834c),(12,0x528590),(13,0x5287e0),(14,0x528a30)])
@pytest.mark.parametrize('printing,ready', [(False, True), (True, True), (False, False)])
def test_actual_home_click_queues_worker_only_when_idle(action, worker, printing, ready):
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X1
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    data = stock()
    cpu.mem_map(0x526000, 0x2000)
    cpu.mem_write(0x526000, data[0x126000:0x128000])
    cpu.mem_map(0x386d000, 0x1000)
    cpu.mem_map(0xe645000, 0x1000)
    cpu.mem_map(0x5000000, 0x2000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x5001000)
    selected, queued, notices = [], [], []

    def step(machine, address, size, unused):
        word = int.from_bytes(machine.mem_read(address, 4), 'little')
        if word >> 26 != 0b100101:
            return
        offset = word & 0x3ffffff
        if offset & (1 << 25): offset -= 1 << 26
        target = address + offset * 4
        result = 0
        if target == 0x6979fc: result = 7  # LV_EVENT_CLICKED
        elif target == 0x697a30: result = action
        elif target == 0x519600: result = int(printing)
        elif target == 0x4b3b94: result = int(ready)  # live webhooks state
        elif target == 0x4b3cd0: selected.append(machine.reg_read(UC_ARM64_REG_X1))
        elif target == 0x655874: queued.append(tuple(selected))
        elif target == 0x5352e0: notices.append(machine.reg_read(UC_ARM64_REG_X0))
        machine.reg_write(UC_ARM64_REG_X0, result)
        machine.reg_write(UC_ARM64_REG_PC, address + 4)

    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x526770, 0x527128, count=1000)
    admitted = not printing and ready
    assert selected == ([worker] if admitted else [])
    assert queued == ([(worker,)] if admitted else [])
    assert len(notices) == int(not admitted)
