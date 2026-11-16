"""Execute exact vendor identification branches; no printer or filesystem writes."""
import hashlib
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


def machine():
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_SP
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    for address, size in ((0x510000, 0x2000), (0x386c000, 0x1000), (0xe645000, 0x1000), (0x5000000, 0x2000)):
        cpu.mem_map(address, size)
    cpu.mem_write(0x510000, data[0x110000:0x112000])
    cpu.reg_write(UC_ARM64_REG_SP, 0x5001000)
    return unicorn, cpu


@pytest.mark.parametrize('error', [0, 1])
def test_vendor_wait_clears_error_before_waiting(error):
    """Characterizes the lost-early-error gap, not corrected behavior."""
    _, cpu = machine()
    cpu.mem_write(0xe6456e1, bytes([error]))
    cpu.emu_start(0x5117d8, 0x5117f0, count=20)
    assert bytes(cpu.mem_read(0xe6456e1, 1)) == b'\0'


@pytest.mark.parametrize('wait_result', [0, 1])
@pytest.mark.parametrize('error,expected', [(0, 'success'), (1, 'failure')])
def test_pickup_branch_uses_shared_error_flag_not_wait_return(error, expected, wait_result):
    unicorn, cpu = machine()
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0
    reached = []
    def step(machine, address, size, _):
        if address == 0x51096c:
            machine.mem_write(0xe6456e1, bytes([error]))
            machine.reg_write(UC_ARM64_REG_X0, wait_result)
            machine.reg_write(UC_ARM64_REG_PC, address + 4)
        elif address in (0x510984, 0x510aa8):
            reached.append('failure' if address == 0x510984 else 'success')
            machine.emu_stop()
    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x51096c, 0, count=30)
    assert reached == [expected]


@pytest.mark.parametrize('error', [0, 1])
def test_final_dock_continues_to_uuid_commit_even_with_error(error):
    """With no duplicate UUIDs, even a latched final-dock error reaches commit."""
    pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0
    paths = []
    for wait_result in (0, 1):
        unicorn, cpu = machine()
        reached = []
        def step(machine, address, size, _):
            if address == 0x510dc8:
                machine.mem_write(0xe6456e1, bytes([error]))
                machine.reg_write(UC_ARM64_REG_X0, wait_result)
                machine.reg_write(UC_ARM64_REG_PC, address + 4)
            else:
                reached.append(address)
                if len(reached) == 4:
                    machine.emu_stop()
        cpu.hook_add(unicorn.UC_HOOK_CODE, step)
        cpu.emu_start(0x510dc8, 0, count=20)
        paths.append(reached)
    assert paths[0] == paths[1]
    assert paths[0][-1] == 0x510fc8  # beginning of UUID publication loop
