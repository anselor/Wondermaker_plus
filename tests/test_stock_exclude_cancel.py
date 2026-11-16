import subprocess
from test_unified_ui import compile_cpp


def test_last_object_enters_managed_cancel_before_stock_mutations(tmp_path):
    source = tmp_path / 'exclude.cpp'
    source.write_text(r'''
#include "native/stock_exclude_cancel.hpp"
#include <cassert>
using wmp_ui::native::exclude_with_managed_cancel;
int main(){
 for(bool last:{false,true})for(bool managed:{false,true}){
  int queried=0,cancelled=0,stock=0;
  exclude_with_managed_cancel("object",[&](const std::string&){++queried;return last;},
   [&]{assert(stock==0);++cancelled;return managed;},[&]{++stock;});
  assert(queried==1);assert(cancelled==int(last));assert(stock==int(!(last&&managed)));
 }
 int stock=0;
 exclude_with_managed_cancel("",[](const std::string&)->bool{assert(false);return false;},
  []()->bool{assert(false);return true;},[&]{++stock;});
 assert(stock==1);
}
''')
    binary = tmp_path / 'exclude'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_profile_pins_safe_exclusion_entry_and_destructive_branch():
    import hashlib
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    raw = (root / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client').read_bytes()
    profile = json.loads((root / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == profile['client_sha256']
    rows = {r['name']: r for r in profile['functions']}
    for name in ('exclude_object', 'is_last_remaining_object', 'exclude_stop_call'):
        row = rows[name]
        offset = int(row['address'], 16) - 0x400000
        assert raw[offset:offset + 32].hex() == row['bytes']
    # STP/MOV/STR/ADD only: no PC-relative instruction in the copied prologue.
    assert raw[0x145924:0x145934].hex() == 'fd7bb4a9fd030091f30b00f9e2c30091'
    for call, target in ((0x545a94, 0x51bf18), (0x545a98, 0x630fac)):
        word = int.from_bytes(raw[call - 0x400000:call - 0x400000 + 4], 'little')
        immediate = word & 0x3ffffff
        if immediate & (1 << 25):
            immediate -= 1 << 26
        assert word >> 26 == 0b100101 and call + immediate * 4 == target


def test_built_arm_exclusion_consumes_last_object_without_runtime():
    import hashlib
    import json
    import struct
    from pathlib import Path
    import pytest
    unicorn = pytest.importorskip('unicorn')
    elf = pytest.importorskip('elftools.elf.elffile')
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC
    root = Path(__file__).resolve().parents[1]
    directory = root / 'analysis/unified-ui-native'
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, digest in manifest['source_inputs'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    artifact = directory / 'libwmp_unified_screen_candidate.so'
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == manifest['artifact']['sha256']
    for last in (False, True):
        cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        with artifact.open('rb') as stream:
            image = elf.ELFFile(stream)
            segments = [s for s in image.iter_segments() if s['p_type'] == 'PT_LOAD']
            end = max(s['p_vaddr'] + s['p_memsz'] for s in segments)
            cpu.mem_map(0, (end + 4095) & ~4095)
            for segment in segments:
                cpu.mem_write(segment['p_vaddr'], segment.data())
            symbols = image.get_section_by_name('.symtab')
            entry = symbols.get_symbol_by_name('unified_exclude_object')[0]['st_value']
            original = next(s['st_value'] for s in symbols.iter_symbols() if s.name.endswith('original_exclude_objectE'))
        for address, size in ((0x4634000, 4096), (0x545000, 4096), (0x5000000, 0x20000)):
            cpu.mem_map(address, size)
        selected = 0x4634ef0
        cpu.mem_write(selected, struct.pack('<QQ', selected + 16, 6) + b'object\0')
        callback, done = 0x5000100, 0x5000200
        cpu.mem_write(original, struct.pack('<Q', callback))
        cpu.reg_write(UC_ARM64_REG_SP, 0x501f000)
        cpu.reg_write(UC_ARM64_REG_X30, done)
        calls = []
        def intercept(machine, address, length, data):
            if address == done:
                machine.emu_stop()
            elif address in (0x545598, callback):
                calls.append(address)
                if address == 0x545598:
                    assert machine.reg_read(UC_ARM64_REG_X0) == selected
                    machine.reg_write(UC_ARM64_REG_X0, int(last))
                machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))
        cpu.hook_add(unicorn.UC_HOOK_CODE, intercept)
        cpu.emu_start(entry, 0, count=1000)
        assert cpu.reg_read(UC_ARM64_REG_PC) == done
        assert calls == ([0x545598] if last else [0x545598, callback])
        assert bytes(cpu.mem_read(selected + 16, 7)) == b'object\0'
