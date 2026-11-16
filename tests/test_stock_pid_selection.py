"""Exact vendor PID selection and narrow native command routing, no hardware."""
import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest
from test_unified_ui import compile_cpp

ROOT = Path(__file__).resolve().parents[1]


def test_only_verified_maintenance_selection_uses_physical_head_command(tmp_path):
    source = tmp_path / 'pid.cpp'
    source.write_text(r'''
#include "native/stock_maintenance_command.hpp"
#include <cassert>
using wmp_ui::native::stock_maintenance_command;
int main() {
 for(int head=0;head<4;++head) {
  const auto command="T"+std::to_string(head);
  for(auto caller:{0x4b7cb8,0x50a968,0x51095c})
   assert(stock_maintenance_command(caller,command)=="_WMP_CALIBRATION_TOOL T="+std::to_string(head));
  assert(wmp_ui::native::stock_calibration_command(0x51095c,command)=="_WMP_CALIBRATION_TOOL T="+std::to_string(head));
  for(auto caller:{0x4b7cb4,0x4b7cbc,0x4b7d90,0x50a964,0x50a96c,0x510958,0x510960,0,0x51a800})
   assert(stock_maintenance_command(caller,command)==command);
 }
 for(const auto&command:{"T4","T-1","T0\nG28","T0 S1","","T00","G28"})
  for(auto caller:{0x4b7cb8,0x50a968,0x51095c})
   assert(stock_maintenance_command(caller,command)=="_WMP_CALIBRATION_TOOL T=-1");
 for(const auto&command:{"G28","PAUSE","RESUME","M104 S220","PID_CALIBRATE HEATER=extruder2 TARGET=220"})
  assert(stock_maintenance_command(0x4b7d90,command)==command);
 for(auto caller:{0x510584,0x5105c4,0x5108c0,0x510db8,0x510f9c,0x511124,0x5111c8})
  assert(wmp_ui::native::stock_calibration_command(caller,"FIRMWARE_RESTART")=="FIRMWARE_RESTART");
}
''')
    binary = tmp_path / 'pid'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_verified_pid_callsite_and_sender_prologue_match_profile():
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.is_file():
        pytest.skip('exact vendor client required')
    data = client.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest() == profile['client_sha256']
    for name, address in [('command_sender', 0x614338), ('pid_tool_sender_call', 0x4b7cb4), ('identification_tool_sender_call', 0x510958)]:
        window = next(row for row in profile['functions'] if row['name'] == name)
        assert int(window['address'], 16) == address
        assert bytes.fromhex(window['bytes']) == data[address-0x400000:address-0x400000+32]
    instruction = struct.unpack_from('<I', data, 0x4b7cb4-0x400000)[0]
    assert instruction >> 26 == 0b100101  # BL; LR identifies precisely this caller
    displacement = instruction & 0x3ffffff
    if displacement & (1 << 25):
        displacement -= 1 << 26
    assert 0x4b7cb4 + 4 * displacement == 0x614338
    # Four relocatable stack/register instructions, no PC-relative operands.
    assert data[0x614338-0x400000:0x614348-0x400000].hex() == 'fd7bb2a9fd030091f30b00f9e01700f9'


@pytest.mark.parametrize('caller,command', [
    (0x4b7cb8, 'T0'), (0x4b7cb8, 'T3'),
    (0x4b7cb8, 'T4'), (0x4b7cb8, 'G28'),
    (0x50a968, 'T0'), (0x50a968, 'T3'), (0x50a968, 'T4'),
    (0x51095c, 'T0'), (0x51095c, 'T3'), (0x51095c, 'T4'),
    (0x4b7cbc, 'T0'), (0x4b7d90, 'T3'),
])
def test_built_arm_wrapper_passes_original_caller_to_guard(caller, command):
    """Run actual ARM entry; verify preserved caller and original string at dispatch."""
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC
    candidate = ROOT / 'analysis/unified-ui-native'
    artifact = candidate / 'libwmp_unified_screen_candidate.so'
    if not artifact.is_file():
        pytest.skip('ARM candidate required')
    manifest = json.loads((candidate/'manifest.json').read_text())
    for name, digest in manifest['source_inputs'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, 'Rebuild stale ARM candidate'
    data = artifact.read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest['artifact']['sha256']
    symbols = subprocess.check_output(['readelf', '-Ws', str(artifact)], text=True).splitlines()
    entry = int(next(line.split()[1] for line in symbols if line.endswith(' unified_command_sender')), 16)
    storage = int(next(line.split()[1] for line in symbols if 'original_command_senderE' in line), 16)
    guard = int(next(line.split()[1] for line in symbols if 'stock_calibration_command' in line), 16)
    relocations = subprocess.check_output(['readelf', '-Wr', str(artifact)], text=True).splitlines()
    def slot(name):
        return int(next(line.split()[0] for line in relocations
                        if 'R_AARCH64_JUMP_SLOT' in line and name in line), 16)
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff+i*phsize) for i in range(phnum)]
    segments = [s for s in segments if s[0] == 1]
    size = (max(s[3]+s[6] for s in segments)+4095) & ~4095
    emu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    emu.mem_map(0, size)
    for _, _, offset, address, _, length, _, _ in segments:
        emu.mem_write(address, data[offset:offset+length])
    emu.mem_map(0x5000000, 0x20000)
    emu.mem_map(0x6000000, 0x1000)
    emu.mem_write(slot('stock_script_has_cancel'), struct.pack('<Q', 0x6000000))
    emu.mem_write(slot('stock_calibration_command'), struct.pack('<Q', guard))
    emu.mem_write(storage, struct.pack('<Q', 0x6000000))  # non-null original sender
    string, buffer = 0x5001000, 0x5001100
    emu.mem_write(string, struct.pack('<QQ', buffer, len(command)))
    emu.mem_write(buffer, command.encode()+b'\0')
    emu.reg_write(UC_ARM64_REG_SP, 0x501f000)
    emu.reg_write(UC_ARM64_REG_X0, string)
    emu.reg_write(UC_ARM64_REG_X30, caller)
    from test_stock_factory_reset_boundary import install_bounded_string_imports
    install_bounded_string_imports(emu, artifact, 0x7000000)
    observed = []
    def at_instruction(cpu, address, length, _):
        if address == 0x6000000:
            # Calibration commands contain no CANCEL_PRINT. The cancellation
            # check now precedes calibration routing; it is not the guard.
            assert cpu.reg_read(UC_ARM64_REG_X0) == string
            cpu.reg_write(UC_ARM64_REG_X0, 0)
            cpu.reg_write(UC_ARM64_REG_PC, cpu.reg_read(UC_ARM64_REG_X30))
        elif address == guard:
            observed.append(tuple(cpu.reg_read(reg) for reg in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2)))
            cpu.emu_stop()
    emu.hook_add(unicorn.UC_HOOK_CODE, at_instruction)
    emu.emu_start(entry, entry+0x1000, count=1000)
    assert len(observed) == 1
    x0, x1, x2 = observed[0]
    # Resolve the actual guard, rather than assuming it is the first call.
    # Its host execution tests cover
    # command routing; this ARM check establishes that instrumentation does not
    # replace the original return address before passing it to that guard.
    assert x0 == caller
    pointer, length = struct.unpack("<QQ", emu.mem_read(x1, 16))
    assert bytes(emu.mem_read(pointer, length)).decode() == command
