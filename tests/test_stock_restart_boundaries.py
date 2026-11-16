"""Pin distinct retained restart callers; no live restart or policy acceptance."""
import hashlib
import json
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not path.exists():
        pytest.skip('retained vendor client required')
    raw = path.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == profile['client_sha256']
    return raw


def word(raw, address):
    return struct.unpack_from('<I', raw, address - 0x400000)[0]


def call(raw, address):
    instruction = word(raw, address)
    assert instruction >> 26 == 0b100101
    offset = instruction & 0x3ffffff
    if offset & (1 << 25):
        offset -= 1 << 26
    return address + offset * 4


def string(raw, address):
    return raw[address - 0x400000:].split(b'\0', 1)[0]


def test_startup_restart_uses_shell_helper_not_command_sender(client):
    assert string(client, 0x86a350) == b'systemctl restart klipper'
    # ADRP x0, 0x86a000; ADD x1, x0, #0x350 constructs the argument.
    instruction = word(client, 0x44a434)
    assert instruction & 0x9f00001f == 0x90000000  # ADRP x0
    pages = ((instruction >> 5) & 0x7ffff) << 2 | ((instruction >> 29) & 3)
    if pages & (1 << 20):
        pages -= 1 << 21
    assert (0x44a434 & ~0xfff) + pages * 4096 == 0x86a000
    assert word(client, 0x44a438) == 0x910d4001
    assert call(client, 0x44a450) == 0x64fc84
    assert call(client, 0x64fcc4) == 0x446f90  # shell helper's imported call
    assert call(client, 0x44a450) != 0x614338  # managed sender hook cannot catch it


def test_warning_restart_is_conditional_and_uses_command_sender(client):
    assert call(client, 0x54c858) == 0x519600  # stock is_printing predicate
    instruction = word(client, 0x54c86c)
    assert instruction & 0xff00001f == 0x54000000  # B.EQ skips restart
    offset = (instruction >> 5) & 0x7ffff
    assert 0x54c86c + offset * 4 == 0x54c8ec
    assert call(client, 0x54c8d8) == 0x616428
    assert string(client, 0x8771c0).upper() == b'FIRMWARE_RESTART'
    assert call(client, 0x61645c) == 0x614338


def test_startup_policy_preserves_other_commands_and_callers(tmp_path):
    import subprocess
    from test_unified_ui import compile_cpp
    source = tmp_path / 'startup.cpp'
    source.write_text(r'''
#include "native/stock_startup_restart.hpp"
#include <cassert>
using wmp_ui::native::suppress_startup_restart;
int main(){
 assert(suppress_startup_restart(0x44a454,"systemctl restart klipper"));
 for(auto caller:{0,0x44a450,0x44a458,0x54c8dc})
  assert(!suppress_startup_restart(caller,"systemctl restart klipper"));
 for(auto command:{"systemctl restart other","systemctl status klipper",
                   "systemctl restart klipper\nother", "FIRMWARE_RESTART", ""})
  assert(!suppress_startup_restart(0x44a454,command));
}
''')
    binary = tmp_path / 'startup'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_startup_shell_trampoline_has_relocatable_prologue(client):
    # MOV x12,#0x10f0; SUB sp,sp,x12; STP x29,x30,[sp]; MOV x29,sp.
    # No PC-relative addressing in the 16 bytes copied by bootstrap.
    assert client[0x64fc84-0x400000:0x64fc94-0x400000].hex() == (
        '0c1e82d2ff632ccbfd7b00a9fd030091')
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    for name, address in [('startup_shell',0x64fc84),
                          ('startup_restart_argument',0x44a434),
                          ('startup_restart_call',0x44a450)]:
        row = next(r for r in profile['functions'] if r['name']==name)
        assert int(row['address'],16)==address
        assert bytes.fromhex(row['bytes'])==client[address-0x400000:address-0x400000+32]


@pytest.mark.parametrize('caller,command,suppressed', [
    (0x44a454, 'systemctl restart klipper', True),
    (0x44a2a4, '/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/canbus_query.py can0 2>&1', True),
    (0x44a2a8, '/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/canbus_query.py can0 2>&1', False),
    (0x44a458, 'systemctl restart klipper', False),
    (0x44a454, 'echo ok', False),
    (0x44a454, 'systemctl restart klipper\nother', False),
])
def test_built_arm_shell_wrapper_return_and_forwarding(caller, command, suppressed):
    """Execute built wrapper, substituting only C++ library calls and original shell."""
    unicorn = pytest.importorskip('unicorn')
    elf = pytest.importorskip('elftools.elf.elffile')
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X8, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PC)
    directory = ROOT / 'analysis/unified-ui-native'
    artifact = directory / 'libwmp_unified_screen_candidate.so'
    if not artifact.exists():
        pytest.skip('built ARM candidate required')
    manifest = json.loads((directory / 'manifest.json').read_text())
    for name, digest in manifest['source_inputs'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, 'Rebuild candidate'
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
        entry = symbols.get_symbol_by_name('unified_shell')[0]['st_value']
        storage = next(s['st_value'] for s in symbols.iter_symbols() if s.name.endswith('original_shellE'))
        relocations = image.get_section_by_name('.rela.plt')
        dynamic = image.get_section(relocations['sh_link'])
        plt = image.get_section_by_name('.plt')['sh_addr']
        imports = {plt + 32 + i * 16: dynamic.get_symbol(r['r_info_sym']).name
                   for i, r in enumerate(relocations.iter_relocations())}
    cpu.mem_map(0x5000000, 0x30000)
    cpu.mem_map(caller & ~4095, 4096)  # mapped return sentinel
    original, argument, buffer, result = 0x5000100, 0x5001000, 0x5001100, 0x5002000
    cpu.mem_write(storage, struct.pack('<Q', original))
    short = len(command) <= 15
    data_address = argument + 16 if short else buffer
    cpu.mem_write(argument, struct.pack('<QQQ', data_address, len(command), len(command)))
    cpu.mem_write(data_address, command.encode() + b'\0')
    cpu.reg_write(UC_ARM64_REG_SP, 0x502f000)
    cpu.reg_write(UC_ARM64_REG_X0, argument)
    cpu.reg_write(UC_ARM64_REG_X8, result)
    cpu.reg_write(UC_ARM64_REG_X30, caller)
    forwarded, freed = [], []

    def read_string(address):
        pointer, length = struct.unpack('<QQ', cpu.mem_read(address, 16))
        return bytes(cpu.mem_read(pointer, length))

    def intercept(machine, address, length, _):
        if address == caller:
            machine.emu_stop()
            return
        if address == original:
            forwarded.append(read_string(machine.reg_read(UC_ARM64_REG_X0)))
            output = machine.reg_read(UC_ARM64_REG_X8)
            assert output == result
            machine.mem_write(output, struct.pack('<QQ', output + 16, 2) + b'ok\0')
        elif address in imports:
            name = imports[address]
            if name.endswith('7compareEPKc'):
                target = machine.reg_read(UC_ARM64_REG_X1)
                expected = bytes(machine.mem_read(target, 128)).split(b'\0', 1)[0]
                machine.reg_write(UC_ARM64_REG_X0, int(read_string(machine.reg_read(UC_ARM64_REG_X0)) != expected))
            elif name == 'getenv':
                # These cases exercise legacy forwarding without ownership.
                machine.reg_write(UC_ARM64_REG_X0, 0)
            elif name == '_ZdlPv':
                freed.append(machine.reg_read(UC_ARM64_REG_X0))
            else:
                pytest.fail('Unexpected external call: ' + name)
        else:
            return
        machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(unicorn.UC_HOOK_CODE, intercept)
    cpu.emu_start(entry, 0, count=1000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == caller
    assert cpu.reg_read(UC_ARM64_REG_SP) == 0x502f000
    assert read_string(result) == (b'' if suppressed else b'ok')
    assert forwarded == ([] if suppressed else [command.encode()])
    assert freed == ([] if suppressed or short else [buffer])
    assert read_string(argument) == (command.encode() if suppressed else b'')


@pytest.mark.parametrize('klipper,state,loading,restart', [
    ('ready', 'standby', False, True),
    ('ready', 'standby', True, False),
    ('ready', 'printing', False, False),
    ('ready', 'paused', False, False),
    ('ready', 'complete', False, False),
    ('ready', 'cancelled', False, True),
    ('ready', 'error', False, True),
    ('ready', 'unknown', False, False),
    ('ready', '', False, False),
    ('shutdown', 'printing', False, True),
    ('startup', 'standby', False, True),
])
def test_warning_predicate_selects_actual_restart_branch(client, klipper, state, loading, restart):
    """Execute the retained decision instructions, not a translation of their policy.

    String comparisons/copies are substituted; cached values are equal to current
    values to avoid diagnostic logging. Execute through the actual return-value
    assignment, then the caller branch. This does not grant backend permission.
    """
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1,
        UC_ARM64_REG_X30, UC_ARM64_REG_PC)
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    for address in (0x519000, 0x54c000, 0x4b3000, 0xe645000,
                    0x386d000, 0x501000, 0x447000):
        cpu.mem_map(address, 4096)
        if address not in (0xe645000, 0x386d000):
            cpu.mem_write(address, client[address - 0x400000:address - 0x400000 + 4096])
    cpu.mem_write(0xe64537b, bytes([loading]))
    cpu.mem_write(0x386d660, bytes([loading]))
    values = {0xe645170: klipper, 0xe645338: state}

    def compare(machine, address, size, _):
        if address in (0x5015c4, 0x447570):
            machine.reg_write(UC_ARM64_REG_X0, 0)  # unchanged cache / assignment
            machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))
            return
        if address not in (0x4b3b94, 0x4b3ca0):
            return
        actual = values[machine.reg_read(UC_ARM64_REG_X0)]
        expected = string(client, machine.reg_read(UC_ARM64_REG_X1)).decode()
        equal = actual == expected
        machine.reg_write(UC_ARM64_REG_X0, int(equal if address == 0x4b3b94 else not equal))
        machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(unicorn.UC_HOOK_CODE, compare)
    # Start after static initialization; stop at the epilogue after assigning return.
    cpu.emu_start(0x51974c, 0x519a28, count=200)
    assert cpu.reg_read(UC_ARM64_REG_PC) == 0x519a28
    predicate = cpu.reg_read(UC_ARM64_REG_X0)
    # Continue the caller immediately after its is_printing() call, stopping at
    # either the logging/restart branch or the stock refusal-popup branch.
    reached = []
    def branch(machine, address, size, _):
        if address in (0x54c870, 0x54c8ec):
            reached.append(address)
            machine.emu_stop()
    cpu.hook_add(unicorn.UC_HOOK_CODE, branch)
    cpu.reg_write(UC_ARM64_REG_X0, predicate)
    cpu.emu_start(0x54c85c, 0, count=30)
    assert reached == ([0x54c870] if restart else [0x54c8ec])


def test_startup_discovery_is_mutating_shell_call_with_logging_only_result(client):
    assert string(client, 0x86a288) == b'/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/canbus_query.py can0 2>&1'
    assert word(client, 0x44a284) == 0x90002100  # ADRP x0,0x86a000
    assert word(client, 0x44a288) == 0x910a2001  # ADD x1,x0,#0x288
    assert call(client, 0x44a2a0) == 0x64fc84
    assert string(client, 0x86a2e0) == b'set canbus_uuid:{}'
    assert call(client, 0x44a314) == 0x460468  # logger receives command output
    # Next shell command reads the existing count; no count is synthesized.
    assert string(client, 0x86a2f8) == b'cat /home/t13dp/TM_T1/other/current_thr_number.txt'
    assert call(client, 0x44a348) == 0x64fc84
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    entry = next(x for x in profile['functions'] if x['name'] == 'startup_discovery_argument')
    address = int(entry['address'], 16)
    assert client[address-0x400000:address-0x400000+32].hex() == entry['bytes']


def test_startup_discovery_policy_is_exact_and_preserves_other_calls(tmp_path):
    import subprocess
    from test_unified_ui import compile_cpp
    source = tmp_path / 'discovery.cpp'
    source.write_text(r'''
#include "native/stock_startup_restart.hpp"
#include <cassert>
using wmp_ui::native::suppress_startup_discovery;
int main(){
 const std::string command="/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/canbus_query.py can0 2>&1";
 assert(suppress_startup_discovery(0x44a2a4,command));
 for(auto caller:{0,0x44a2a0,0x44a2a8,0x44a454})
  assert(!suppress_startup_discovery(caller,command));
 for(auto other:{std::string(""),command+"\nother",std::string("systemctl restart klipper"),
                 std::string("cat /home/t13dp/TM_T1/other/current_thr_number.txt")})
  assert(!suppress_startup_discovery(0x44a2a4,other));
}
''')
    binary = tmp_path / 'discovery'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_native_profile_regeneration_preserves_all_checked_symbols(client, tmp_path):
    import subprocess
    import sys
    native = ROOT / 'client-preload/unified-ui/native'
    generator = tmp_path / 'make_profile.py'
    generator.write_bytes((native / 'make_profile.py').read_bytes())
    subprocess.run([sys.executable, str(generator), str(ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client')], check=True)
    for name in ('profile1113.json', 'profile1113.hpp'):
        assert (tmp_path / name).read_bytes() == (native / name).read_bytes()


def test_defaults_startup_call_requires_paired_service_contract(tmp_path, client):
    import subprocess
    from test_unified_ui import compile_cpp
    # Exact retained call constructs the merger string then calls the shell.
    data = client
    assert data[0x46a238:].split(b'\0', 1)[0] == b'/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/merge_config.py'
    instruction = int.from_bytes(data[0x4a254:0x4a258], 'little')
    assert instruction >> 26 == 0b100101
    assert 0x44a254 + (instruction & 0x3ffffff) * 4 == 0x64fc84
    source = tmp_path / 'defaults.cpp'
    source.write_text(r'''
#include "native/stock_startup_restart.hpp"
#include <cassert>
using wmp_ui::native::suppress_startup_defaults;
int main(){
 const std::string command="/home/t13dp/klippy-env/bin/python /home/t13dp/TM_T1/scripts/merge_config.py";
 assert(suppress_startup_defaults(0x44a258,command,true));
 assert(!suppress_startup_defaults(0x44a258,command,false));
 assert(!suppress_startup_defaults(0x44a254,command,true));
 assert(!suppress_startup_defaults(0x44a258,command+" extra",true));
}
''')
    binary = tmp_path / 'defaults'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


@pytest.fixture
def managed_warning_restart():
    # Reuse the actual retained vendor dispatcher fixture; no printer I/O.
    import importlib.util
    import sys
    directory = str(ROOT / 'klipper_extras')
    sys.path.insert(0, directory)
    try:
        spec = importlib.util.spec_from_file_location(
            'warning_backend_restart_tests', ROOT / 'klipper_extras/test_managed_restart.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module.restart.__wrapped__()
    finally:
        sys.path.remove(directory)


@pytest.mark.parametrize('hold', ['none', 'filament', 'tool', 'cancel', 'recovery',
                                  'tool-running', 'cancel-pending', 'recovery-worker',
                                  'recovery-queued', 'calibration', 'pending-submit',
                                  'status-error', 'status-error-sd'])
def test_warning_allowed_branch_still_obeys_current_backend_owner(client, managed_warning_restart, hold):
    """Join the real ARM warning decision to retained Klipper restart dispatch.

    The screen's cached standby status admits every case here. WM+ must evaluate
    the current backend state before the vendor drains moves or exits. Transport
    delivery is represented by calling the literal command's retained handler;
    this does not claim live warning-popup acceptance.
    """
    from types import SimpleNamespace
    backend = managed_warning_restart
    test_warning_predicate_selects_actual_restart_branch(
        client, 'ready', 'standby', False, True)
    if hold == 'filament':
        backend.material.filament_operation = {'state': 'running'}
    elif hold == 'tool':
        backend.material.toolhead_operation = {'state': 'unknown'}
    elif hold == 'cancel':
        backend.material._print_cancel = {'state': 'unknown'}
    elif hold == 'recovery':
        backend.material._recovery_attempt = SimpleNamespace(
            busy=False, record={'state': 'stopped'})
    elif hold == 'tool-running':
        backend.material.toolhead_operation = {'state': 'running'}
    elif hold == 'cancel-pending':
        backend.material._print_cancel = {'state': 'pending'}
    elif hold == 'recovery-worker':
        backend.material._recovery_attempt = SimpleNamespace(busy=True, record={'state': 'running'})
    elif hold == 'recovery-queued':
        backend.material._recovery_pending_worker = object()
    elif hold == 'calibration':
        backend.data['wmp_recovery']['calibration_active'] = True
    elif hold == 'pending-submit':
        backend.material._pending_recovery_submission = {'pending': True}
    elif hold in ('status-error', 'status-error-sd'):
        backend.data['print_stats']['state'] = 'error'
        if hold == 'status-error-sd':
            backend.sd.is_active = lambda: True
    # Historical uncertainty and a stopped/error print are not current work.
    # Restart is the explicit recovery action; no old receipt is cleared here.
    if hold in ('none', 'tool', 'cancel', 'recovery', 'status-error'):
        backend.dispatch.cmd_FIRMWARE_RESTART(None)
        assert backend.calls == ['dwell', 'drain', 'firmware_restart']
    else:
        with pytest.raises(ValueError, match='Restart not admitted'):
            backend.dispatch.cmd_FIRMWARE_RESTART(None)
        assert backend.calls == []


def test_file_browser_completion_uses_exact_existing_shell_call(client):
    assert string(client, 0x874e20) == b'/home/t13dp/need_oobe'
    assert string(client, 0x874e38) == b'rm /home/t13dp/need_oobe -f'
    assert call(client, 0x4fd488) == 0x446e40  # access, not the shell call
    assert word(client, 0x4fd4b4) == 0xf0001ba0  # ADRP x0, 0x874000
    assert word(client, 0x4fd4b8) == 0x9138e001  # ADD x1,x0,#0xe38
    assert call(client, 0x4fd4d0) == 0x64fc84
    source = (ROOT / 'client-preload/unified-ui/native/bootstrap.cpp').read_text()
    assert 'suppress_file_setup_completion(caller,command,screen&&screen->onboarding_active())' in source
