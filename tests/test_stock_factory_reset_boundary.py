"""Execute the retained reset prefix with every called effect replaced by a stub.

This characterizes the boundary that must be replaced, not managed reset support.
No vendor shell, filesystem mutation, printer connection or native UI is executed.
"""
import hashlib
from pathlib import Path

import pytest

CLIENT = Path(__file__).resolve().parents[1] / (
    'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client')


def install_bounded_string_imports(cpu, artifact, base):
    """Model only string scratch storage and diagnostic imports, never effects.

    All other unresolved imports remain unmapped and fail execution. Heap writes
    stay within a fixed arena; diagnostics are captured for exact assertions.
    """
    import struct
    import subprocess
    import unicorn
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4,
        UC_ARM64_REG_X30, UC_ARM64_REG_PC)
    cpu.mem_map(base, 0x20000)
    allocated, logs, handlers = [], [], {}
    cursor = base + 0x2000
    def allocate(size):
        nonlocal cursor
        assert 0 <= size <= 4096
        pointer = cursor
        cursor += (size + 31) & ~15
        assert cursor < base + 0x20000
        allocated.append(pointer)
        return pointer
    def cstring(pointer):
        value = bytes(cpu.mem_read(pointer, 1024)).split(b'\0')[0]
        assert len(value) < 1024
        return value.decode()
    rows = subprocess.check_output(['readelf', '-Wr', str(artifact)], text=True).splitlines()
    for row in rows:
        words = row.split()
        if 'R_AARCH64_GLOB_DAT' in row and ' stderr@' in row:
            cpu.mem_write(int(words[0], 16), struct.pack('<Q', base + 0x1000))
            cpu.mem_write(base + 0x1000, struct.pack('<Q', base + 0x1100))
        if 'R_AARCH64_JUMP_SLOT' not in row:
            continue
        name = words[4].split('@')[0]
        kind = next((key for key in ('_M_constructIPc', '_M_create', '_M_mutate') if key in name), name)
        if kind not in ('_M_constructIPc', '_M_create', '_M_mutate', '_ZdlPv', 'memcmp', 'fprintf'):
            continue
        address = base + len(handlers)*16
        handlers[address] = kind
        cpu.mem_write(int(words[0], 16), struct.pack('<Q', address))
    def dispatch(machine, address, size, _):
        if address not in handlers:
            return
        kind = handlers[address]
        a, b, c, d, e = [machine.reg_read(reg) for reg in
            (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4)]
        result = 0
        if kind == '_M_constructIPc':
            length = c-b
            assert 0 <= length <= 4096
            pointer = a+16 if length <= 15 else allocate(length+1)
            machine.mem_write(a, struct.pack('<QQ', pointer, length))
            if length > 15:
                machine.mem_write(a+16, struct.pack('<Q', length))
            machine.mem_write(pointer, bytes(machine.mem_read(b, length))+b'\0')
        elif kind == '_M_create':
            capacity = struct.unpack('<Q', machine.mem_read(b, 8))[0]
            result = allocate(capacity+1)
        elif kind == '_M_mutate':
            old, length = struct.unpack('<QQ', machine.mem_read(a, 16))
            assert b <= length and c <= length-b and e <= 4096
            before = bytes(machine.mem_read(old, b))
            after = bytes(machine.mem_read(old+b+c, length-b-c))
            middle = bytes(machine.mem_read(d, e)) if d else bytes(e)
            value = before+middle+after
            capacity = max(32, len(value)*2)
            pointer = allocate(capacity+1)
            machine.mem_write(pointer, value+b'\0')
            # _M_mutate changes capacity/data; caller publishes new length.
            machine.mem_write(a, struct.pack('<Q', pointer))
            machine.mem_write(a+16, struct.pack('<Q', capacity))
        elif kind == '_ZdlPv':
            assert a in allocated
        elif kind == 'memcmp':
            assert c <= 4096
            left, right = bytes(machine.mem_read(a,c)), bytes(machine.mem_read(b,c))
            result = (left > right)-(left < right)
        elif kind == 'fprintf':
            assert a == base+0x1100
            logs.append((cstring(b), cstring(c), cstring(d)))
        machine.reg_write(UC_ARM64_REG_X0, result & ((1<<64)-1))
        machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))
    cpu.hook_add(unicorn.UC_HOOK_CODE, dispatch)
    return logs


def test_factory_reset_has_destructive_prefix_before_first_shell_command():
    unicorn = pytest.importorskip('unicorn')
    elf = pytest.importorskip('elftools.elf.elffile')
    from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_PC,
                                    UC_ARM64_REG_X0, UC_ARM64_REG_X1)
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715')
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    with CLIENT.open('rb') as stream:
        image = elf.ELFFile(stream)
        segments = [s for s in image.iter_segments() if s['p_type'] == 'PT_LOAD']
        start = min(s['p_vaddr'] for s in segments) & ~4095
        end = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
        cpu.mem_map(start, ((end + 4095) & ~4095) - start)
        for segment in segments:
            cpu.mem_write(segment['p_vaddr'], segment.data())
    cpu.mem_map(0x70000000, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x7000f000)
    effects = []
    strings = []
    boundary = []
    # Constructors, logging and destructors are stubs as well as actual effects.
    harmless = {0x447050, 0x446c10, 0x457498, 0x45f754, 0x515d84,
                0x4562c4, 0x4469f0, 0x447720}
    destructive = {0x630fac: 'reset_plr_files', 0x6169dc: 'delete_all_jobs',
                   0x500558: 'format_gcode_local_with_pop'}

    def step(machine, address, size, _):
        word = int.from_bytes(machine.mem_read(address, 4), 'little')
        if word >> 26 != 0b100101:
            return
        offset = word & 0x3ffffff
        if offset & 0x2000000:
            offset -= 0x4000000
        target = address + offset * 4
        if target == 0x64fc84:
            boundary.append(address)
            machine.emu_stop()
            return
        if target in destructive:
            effects.append(destructive[target])
        else:
            assert target in harmless, hex(target)
        if target == 0x446c10:
            pointer = machine.reg_read(UC_ARM64_REG_X1)
            strings.append(bytes(machine.mem_read(pointer, 160)).split(b'\0')[0].decode())
        machine.reg_write(UC_ARM64_REG_X0, 0x70001000)
        machine.reg_write(UC_ARM64_REG_PC, address + 4)

    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x548078, 0, count=400)
    assert boundary == [0x54812c]
    assert effects == ['reset_plr_files', 'delete_all_jobs', 'format_gcode_local_with_pop']
    assert strings[-1] == 'bash /home/t13dp/TM_T1/scripts/clear_memory.sh'


def test_factory_reset_entry_is_profiled_and_replaced_without_trampoline():
    import json
    root = Path(__file__).resolve().parents[1]
    native = root / 'client-preload/unified-ui/native'
    profile = json.loads((native / 'profile1113.json').read_text())
    row = next(r for r in profile['functions'] if r['name'] == 'factory_reset')
    assert row['address'] == '0x548078'
    assert bytes.fromhex(row['bytes']) == CLIENT.read_bytes()[0x148078:0x148098]
    source = (native / 'bootstrap.cpp').read_text()
    assert '{0x548078,nullptr}' in source
    assert 'reinterpret_cast<std::uintptr_t>(&unified_factory_reset)' in source
    assert 'original_factory_reset' not in source


@pytest.mark.parametrize('runtime_present', [False, True])
def test_built_arm_reset_guard_only_queues_notice(runtime_present):
    import json
    import struct
    unicorn = pytest.importorskip('unicorn')
    elf = pytest.importorskip('elftools.elf.elffile')
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X30
    root = Path(__file__).resolve().parents[1]
    directory = root / 'analysis/unified-ui-native'
    artifact = directory / 'libwmp_unified_screen_candidate.so'
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, digest in manifest['source_inputs'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, 'Rebuild candidate'
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == manifest['artifact']['sha256']
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    with artifact.open('rb') as stream:
        image = elf.ELFFile(stream)
        segments = [s for s in image.iter_segments() if s['p_type'] == 'PT_LOAD']
        end = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
        cpu.mem_map(0, (end + 4095) & ~4095)
        for segment in segments:
            cpu.mem_write(segment['p_vaddr'], segment.data())
        symbols = image.get_section_by_name('.symtab')
        entry = symbols.get_symbol_by_name('unified_factory_reset')[0]['st_value']
        storage = next(s['st_value'] for s in symbols.iter_symbols() if s.name.endswith('runtimeE'))
    obj, stack, sentinel = 0x70000000, 0x71000000, 0x72000000
    cpu.mem_map(obj, 0x100000)
    cpu.mem_map(stack, 0x10000)
    cpu.mem_map(sentinel, 0x1000)
    cpu.mem_write(storage, struct.pack('<Q', obj if runtime_present else 0))
    cpu.reg_write(UC_ARM64_REG_SP, stack + 0xf000)
    cpu.reg_write(UC_ARM64_REG_X30, sentinel)
    logs = install_bounded_string_imports(cpu, artifact, 0x73000000)
    writes = []
    def write(machine, access, address, size, value, data):
        if obj <= address < obj + 0x100000:
            writes.append((size, value))
        else:
            assert (stack <= address and address+size <= stack+0x10000) or (
                0x73000000 <= address and address+size <= 0x73020000), 'Unexpected reset effect'
    cpu.hook_add(unicorn.UC_HOOK_MEM_WRITE, write)
    cpu.emu_start(entry, sentinel, count=10000)
    from unicorn.arm64_const import UC_ARM64_REG_PC
    assert cpu.reg_read(UC_ARM64_REG_PC) == sentinel
    assert writes == ([(1, 1)] if runtime_present else [])
    assert [(scope, reason) for _, scope, reason in logs] == ([(
        "factory reset", "Factory reset is disabled by WM+ policy; no reset command sent.")]
        if runtime_present else [])


def test_reset_confirmation_queues_worker_only_after_progress_popup():
    import struct
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == (
        'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715')
    # Reviewed popup dispatch: kind - 2 indexes signed relative branch words.
    offset = struct.unpack_from('<i', data, 0x47c9b0 + (21 - 2) * 4)[0]
    assert 0x530468 + offset * 4 == 0x5313d8
    def branch(address):
        word = struct.unpack_from('<I', data, address - 0x400000)[0]
        assert word >> 26 == 0b100101
        offset = word & 0x3ffffff
        if offset & 0x2000000:
            offset -= 0x4000000
        return address + offset * 4
    assert branch(0x5313f8) == 0x5352e0  # draw_pop(22), before enqueue
    assert struct.unpack_from('<I', data, 0x1313f4)[0] == 0x528002c0
    # Address of guarded worker passed to the std::function constructor.
    assert data[0x131400:0x131408].hex() == 'a00000f001e00191'
    assert branch(0x53140c) == 0x4b3cd0
    assert branch(0x53143c) == 0x655874  # enqueue_event
