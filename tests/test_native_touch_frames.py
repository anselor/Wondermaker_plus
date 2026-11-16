"""Execute the pinned factory reader and compiled ARM hook, without printer I/O."""
import hashlib
import json
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
CANDIDATE = ROOT / 'analysis/unified-ui-native/libwmp_unified_screen_candidate.so'
ENTRY, DISPATCH, READ, EXIT = 0x73ca44, 0x73ca58, 0x446340, 0x900000
DRIVER, DATA = 0x20000000, 0x20000300


def elf_bytes(path, address, size):
    if not path.exists():
        pytest.skip('local firmware/candidate artifact required')
    ELFFile = pytest.importorskip('elftools.elf.elffile').ELFFile
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        segment = next(s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD'
                       and s['p_vaddr'] <= address < s['p_vaddr'] + s['p_filesz'])
        stream.seek(address - segment['p_vaddr'] + segment['p_offset'])
        return stream.read(size)


def event(kind, code, value):
    return struct.pack('<qqHHi', 0, 0, kind, code, value)


def frame(*events):
    return [event(*e) for e in events] + [event(0, 0, 0)]


class Reader:
    def __init__(self, patched=False, device_type=1):
        unicorn = pytest.importorskip('unicorn')
        from unicorn import arm64_const as reg
        if not CLIENT.exists():
            pytest.skip('pinned local factory binary required')
        assert hashlib.sha256(CLIENT.read_bytes()).hexdigest() == (
            'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715')
        self.reg = reg
        self.cpu = cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        for address, size in [(0x73c000, 0x2000), (0x446000, 0x1000),
                              (0x385d000, 0x1000), (0xff50000, 0x1000),
                              (0x10000000, 0x10000), (DRIVER, 0x1000),
                              (EXIT, 0x1000), (0x800000, 0x1000)]:
            cpu.mem_map(address, size)
        cpu.mem_write(ENTRY, elf_bytes(CLIENT, ENTRY, 0x4dc))
        cpu.mem_write(DRIVER, struct.pack('<I', device_type))
        cpu.mem_write(DRIVER + 0x20, struct.pack('<Q', DRIVER + 0x100))
        cpu.mem_write(DRIVER + 0x100, struct.pack('<Q', DRIVER + 0x200))
        cpu.mem_write(DRIVER + 0x200, struct.pack('<hh', 800, 480))
        self.queue = []
        if patched:
            if not CANDIDATE.exists():
                pytest.skip('build ARM candidate before running hook tests')
            ELFFile = pytest.importorskip('elftools.elf.elffile').ELFFile
            with CANDIDATE.open('rb') as stream:
                symbols = ELFFile(stream).get_section_by_name('.symtab')
                symbol = symbols.get_symbol_by_name('unified_evdev_frame')
                assert symbol, 'ARM candidate does not contain the touch-frame hook'
                symbol = symbol[0]
                address, size = symbol['st_value'], symbol['st_size']
            cpu.mem_write(0x800000, elf_bytes(CANDIDATE, address, size))
            # Same 16-byte absolute jump used by install_navigation_hooks.
            cpu.mem_write(DISPATCH, struct.pack('<IIQ', 0x58000050, 0xd61f0200, 0x800000))
        cpu.hook_add(unicorn.UC_HOOK_CODE, self.read)

    def read(self, cpu, address, size, unused):
        if address != READ:
            return
        r = self.reg
        assert cpu.reg_read(r.UC_ARM64_REG_X2) == 24
        if self.queue:
            cpu.mem_write(cpu.reg_read(r.UC_ARM64_REG_X1), self.queue.pop(0))
            result = 24
        else:
            result = (1 << 64) - 1  # nonblocking read: EAGAIN
        cpu.reg_write(r.UC_ARM64_REG_X0, result)
        cpu.reg_write(r.UC_ARM64_REG_PC, cpu.reg_read(r.UC_ARM64_REG_LR))

    def poll(self):
        cpu, r = self.cpu, self.reg
        # _lv_indev_read clears the 24-byte output before each driver invocation.
        cpu.mem_write(DATA, bytes(24))
        cpu.reg_write(r.UC_ARM64_REG_SP, 0x10008000)
        cpu.reg_write(r.UC_ARM64_REG_LR, EXIT)
        cpu.reg_write(r.UC_ARM64_REG_X0, DRIVER)
        cpu.reg_write(r.UC_ARM64_REG_X1, DATA)
        cpu.emu_start(ENTRY, EXIT, count=10000)
        assert cpu.reg_read(r.UC_ARM64_REG_PC) == EXIT
        assert cpu.reg_read(r.UC_ARM64_REG_SP) == 0x10008000
        raw = cpu.mem_read(DATA, 24)
        x, y, key = struct.unpack_from('<hhI', raw)
        state = struct.unpack_from('<I', raw, 16)[0]
        return (x, y, state, key, raw[20])

    def drain(self):
        outputs = []
        for _ in range(1000):
            value = self.poll()
            outputs.append(value)
            if not value[-1]:
                return outputs
        pytest.fail('continue_reading did not terminate')


def test_factory_reader_loses_queued_short_tap():
    reader = Reader()
    down = frame((3, 0, 714), (3, 1, 125), (1, 330, 1))
    up = frame((1, 330, 0))
    reader.queue = down.copy()
    assert reader.poll()[2] == 1
    reader.queue = up.copy()
    assert reader.poll()[2] == 0
    reader.queue = down + up
    assert reader.poll()[2] == 0
    assert not reader.queue  # Press was consumed without being published.


def test_compiled_hook_preserves_queued_taps_and_drains_without_backlog():
    reader = Reader(patched=True)
    down = frame((3, 0, 714), (3, 1, 125), (1, 330, 1))
    up = frame((1, 330, 0))
    reader.queue = down + up + down + up
    outputs = reader.drain()
    assert [v[2] for v in outputs] == [1, 0, 1, 0, 0]
    assert all(v[:2] == (714, 125) for v in outputs)
    assert not reader.queue
    reader.queue = down + sum((frame((3, 0, x)) for x in range(100)), []) + up
    outputs = reader.drain()
    assert len(outputs) == 103 and not reader.queue
    assert [v[0] for v in outputs[1:101]] == list(range(100))
    assert [v[2] for v in outputs[-2:]] == [0, 0]


def test_compiled_hook_keeps_factory_pointer_parsing_and_keypad_behavior():
    original, patched = Reader(), Reader(patched=True)
    for packet in [frame((3, 0, -10), (3, 1, 900), (1, 272, 1)),
                   frame((3, 53, 300), (3, 54, 250), (3, 57, 0)),
                   frame((2, 0, 5), (2, 1, -10)), frame((3, 57, -1)),
                   frame((0, 2, 0), (4, 4, 9)), frame((1, 272, 0))]:
        original.queue, patched.queue = packet.copy(), packet.copy()
        assert original.poll()[:4] == patched.poll()[:4]
        assert not original.queue and not patched.queue
    original, patched = Reader(device_type=2), Reader(patched=True, device_type=2)
    original.queue = frame((1, 28, 1)) + frame((1, 28, 0))
    patched.queue = original.queue.copy()
    for _ in range(4):
        assert original.poll() == patched.poll()
        assert original.queue == patched.queue


def test_hook_and_lvgl_abi_windows_are_profile_guarded():
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    rows = {r['name']: r for r in profile['functions']}
    for name, address in {'evdev_frame_dispatch': DISPATCH, 'evdev_frame_finish': 0x73cdac,
                          'indev_read_zero': 0x6c4398, 'indev_continue_capture': 0x698f90,
                          'indev_continue_loop': 0x699124}.items():
        assert int(rows[name]['address'], 16) == address
        assert bytes.fromhex(rows[name]['bytes']) == elf_bytes(CLIENT, address, 32)
    source = (ROOT / 'client-preload/unified-ui/native/bootstrap.cpp').read_text()
    assert '{0x73ca58,nullptr}' in source
    assert 'reinterpret_cast<std::uintptr_t>(&unified_evdev_frame)' in source
