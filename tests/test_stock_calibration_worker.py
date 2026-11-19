"""Characterize exact stock calibration continuation; no printer commands run."""
import hashlib
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


def machine():
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_SP
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    cpu.mem_map(0x4b7000, 0x2000)
    cpu.mem_write(0x4b7000, data[0xb7000:0xb9000])
    for address in (0x385c000, 0x385f000, 0xe645000, 0x5000000):
        cpu.mem_map(address, 0x2000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x5000000)
    return unicorn, cpu


@pytest.mark.parametrize('index,expected', [(0, 0x4b7c84), (3, 0x4b7dcc)])
@pytest.mark.parametrize('wait_result', [0, 1])
def test_pid_continues_regardless_of_wait_result(index, expected, wait_result):
    """Known gap: both wait outcomes advance to next head or PARK construction."""
    unicorn, cpu = machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_PC
    cpu.mem_write(0x500064c, index.to_bytes(4, 'little'))
    cpu.mem_write(0x385c260, (4).to_bytes(4, 'little'))
    reached = []
    def step(machine, address, size, _):
        if address == 0x4b7db8:  # wait_sync: inject either documented return branch
            machine.reg_write(UC_ARM64_REG_X0, wait_result)
            machine.reg_write(UC_ARM64_REG_PC, address+4)
        elif address in (0x4b7c84, 0x4b7dcc):
            reached.append(address)
            machine.emu_stop()
    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x4b7db8, 0, count=100)
    assert reached == [expected]


@pytest.mark.parametrize('failure,selected,expected', [
    (1, 1, 'skip'), (0, 1, 'save'), (0, 0, 'no-save'),
])
def test_final_save_branch_uses_offset_failure_flag(failure, selected, expected):
    """C++ formatting calls stubbed; execute actual branch instructions."""
    unicorn, cpu = machine()
    from unicorn.arm64_const import UC_ARM64_REG_PC
    cpu.mem_write(0xe64572d, bytes([failure]))
    cpu.mem_write(0x385fa88, bytes([selected, 0, 0]))
    reached = []
    def step(machine, address, size, _):
        terminal = {0x4b8bb4: 'skip', 0x4b8698: 'save', 0x4b8700: 'no-save'}
        if address in terminal:
            reached.append(terminal[address])
            machine.emu_stop()
        elif int.from_bytes(machine.mem_read(address, 4), 'little') >> 26 == 0b100101:
            machine.reg_write(UC_ARM64_REG_PC, address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x4b856c, 0, count=200)
    assert reached == [expected]


@pytest.mark.parametrize('pairing_active,expected_failure', [(0, 0), (1, 1)])
def test_error_parser_only_latches_failure_during_knife_pairing(pairing_active, expected_failure):
    """Same accepted error reaches the latch only when knife_pairing_ing is set."""
    unicorn, cpu = machine()
    data = CLIENT.read_bytes()
    cpu.mem_map(0x63b000, 0x1000)
    cpu.mem_write(0x63b000, data[0x23b000:0x23c000])
    cpu.mem_write(0xe64572c, bytes([pairing_active, 0]))
    cpu.emu_start(0x63b828, 0x63b84c, count=20)
    assert bytes(cpu.mem_read(0xe64572d, 1)) == bytes([expected_failure])


SENDER, QUICK_STOP, SLEEP = 0x614338, 0x616558, 0x4471d0
STRING_NE, STRING_EQ = 0x4b3ca0, 0x4b3b94
WAIT_TOOL_CALIBRATE_SYNC, WAIT_SYNC = 0x4b8bc4, 0x6426dc
IDLE_TIMEOUT_STATE, KLIPPER_STATE = 0xe6451b0, 0xe645170
PAIRING_ING, PAIRING_FAILED, WORKER_STATUS = 0xe64572c, 0xe64572d, 0x385fc18
G28_SENT, RAPID_SENT, PARK_SENT, SAVE_SENT = 0x4b7fbc, 0x4b842c, 0x4b847c, 0x4b869c


def run_offset_stage(on_send=None, rapid=1):
    """Run auto_checking from status 11 (offset stage) until it returns.

    The worker and both wait helpers execute their own instructions. The
    sender, quick_stop and sleep are recorded and skipped. The two string
    comparisons answer from fixed states: idle_timeout_state "Ready" and
    klipper_state "ready", the states of an idle printer on which no sent
    command is running. Every other call is C++ formatting or logging and
    is skipped. No send reaches anything; on_send models its side effects.
    """
    unicorn, cpu = machine()
    from unicorn.arm64_const import (UC_ARM64_REG_LR, UC_ARM64_REG_PC, UC_ARM64_REG_SP,
                                     UC_ARM64_REG_X0, UC_ARM64_REG_X1)
    data = CLIENT.read_bytes()
    cpu.mem_map(0x642000, 0x1000)
    cpu.mem_write(0x642000, data[0x242000:0x243000])
    cpu.mem_map(0x384c000, 0x1000)
    cpu.mem_write(0x384c570, bytes([rapid]))                # is_rapid_mode
    cpu.mem_write(0x385fa88, bytes([1, 0, 0, 1]))           # auto_check_selected
    cpu.mem_write(0x385c260, (4).to_bytes(4, 'little'))     # current_thr_number
    cpu.mem_write(WORKER_STATUS, (11).to_bytes(4, 'little'))
    cpu.reg_write(UC_ARM64_REG_SP, 0x5001800)               # frame and callee frames stay mapped
    cpu.reg_write(UC_ARM64_REG_LR, 0x5000000)               # return sentinel
    states = {IDLE_TIMEOUT_STATE: b'Ready', KLIPPER_STATE: b'ready'}
    run = {'sends': [], 'quick_stops': 0, 'sleeps': []}

    def step(machine, address, size, _):
        word = int.from_bytes(machine.mem_read(address, 4), 'little')
        if word >> 26 != 0b100101:
            return
        displacement = word & 0x3ffffff
        if displacement & (1 << 25):
            displacement -= 1 << 26
        target = address + displacement * 4
        if target in (WAIT_TOOL_CALIBRATE_SYNC, WAIT_SYNC):
            return
        if target == SENDER:
            run['sends'].append(address + 4)
            if on_send is not None:
                on_send(machine, address + 4)
        elif target == QUICK_STOP:
            run['quick_stops'] += 1
        elif target == SLEEP:
            run['sleeps'].append(address + 4)
        elif target in (STRING_NE, STRING_EQ):
            literal = machine.reg_read(UC_ARM64_REG_X1) - 0x400000
            equal = states[machine.reg_read(UC_ARM64_REG_X0)] == data[literal:data.index(b'\0', literal)]
            machine.reg_write(UC_ARM64_REG_X0, int(equal == (target == STRING_EQ)))
        machine.reg_write(UC_ARM64_REG_PC, address + 4)
    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x4b7558, 0x5000000, count=20000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == 0x5000000, 'worker did not return'
    run['status'] = int.from_bytes(cpu.mem_read(WORKER_STATUS, 4), 'little')
    run['failed'] = cpu.mem_read(PAIRING_FAILED, 1)[0]
    return run


def test_offset_stage_with_withheld_sends_reaches_save():
    """Nothing acts on RAPID_MODE or PARK_CURRENT_TOOL; the worker still saves."""
    run = run_offset_stage()
    assert run['sends'] == [G28_SENT] + [RAPID_SENT] * 4 + [PARK_SENT, SAVE_SENT]
    assert run['quick_stops'] == 0
    assert run['status'] == 14
    # Each wait helper sleeps once at entry and returns at its first state
    # check; neither reaches its polling-loop sleep (0x4b8c28, 0x642740).
    helper_sleeps = [address for address in run['sleeps'] if not 0x4b7558 <= address < 0x4b8bc4]
    assert helper_sleeps == [0x4b8bd8] * 4 + [0x6426f0]


def latch_failure_at_first_rapid_send(machine, returns_to):
    # What parse_gcode_response does on a G-code error during the offset stage.
    if returns_to == RAPID_SENT:
        assert machine.mem_read(PAIRING_ING, 1)[0] == 1
        machine.mem_write(PAIRING_FAILED, bytes([1]))


def test_failed_byte_cleared_at_park_send_avoids_quick_stop():
    def on_send(machine, returns_to):
        latch_failure_at_first_rapid_send(machine, returns_to)
        if returns_to == PARK_SENT:
            assert machine.mem_read(PAIRING_FAILED, 1)[0] == 1
            machine.mem_write(PAIRING_FAILED, bytes([0]))
    run = run_offset_stage(on_send)
    # The latched failure ends the RAPID_MODE loop after the first head.
    assert run['sends'] == [G28_SENT, RAPID_SENT, PARK_SENT, SAVE_SENT]
    assert run['quick_stops'] == 0
    assert run['status'] == 14


def test_failed_byte_left_set_calls_quick_stop_and_skips_save():
    """Stock behaviour: PARK_CURRENT_TOOL is sent, then quick_stop, and no save."""
    run = run_offset_stage(latch_failure_at_first_rapid_send)
    assert run['sends'] == [G28_SENT, RAPID_SENT, PARK_SENT]
    assert run['quick_stops'] == 1
    assert (run['status'], run['failed']) == (14, 0)


def test_worker_held_inside_the_park_send_then_parks_and_saves():
    """The re-check holds the worker inside the send that returns to 0x4b847c.

    Inside that send the worker is in the pairing window (knife_pairing_ing
    1), its status is 11 and the failed byte is 0. Returning from the send, it
    parks and sends SAVE_CONFIG without quick_stop.
    """
    inside = []

    def on_send(machine, returns_to):
        if returns_to == PARK_SENT:
            inside.append((machine.mem_read(PAIRING_ING, 1)[0], machine.mem_read(PAIRING_FAILED, 1)[0],
                           int.from_bytes(machine.mem_read(WORKER_STATUS, 4), 'little')))
    run = run_offset_stage(on_send)
    assert inside == [(1, 0, 11)]
    assert run['sends'] == [G28_SENT] + [RAPID_SENT] * 4 + [PARK_SENT, SAVE_SENT]
    assert run['quick_stops'] == 0
    assert (run['status'], run['failed']) == (14, 0)


def test_brush_run_reads_rapid_and_skips_fine_loop():
    """is_rapid_mode set to 1 inside the G28 send hook selects the rapid branch.

    The run starts in Accurate mode (0). The preload writes the byte before the
    worker's send that returns to 0x4b7fbc comes back; the worker reads it once
    after that return.
    """
    def on_send(machine, returns_to):
        if returns_to == G28_SENT:
            assert machine.mem_read(0x384c570, 1)[0] == 0
            machine.mem_write(0x384c570, bytes([1]))
    run = run_offset_stage(on_send, rapid=0)
    assert 0x4b80b8 not in run['sends'] and 0x4b82e4 not in run['sends']  # NOZZLE_PREPARE, NOZZLE_CALIBRATE_TOOL_OFFSET
    assert run['sends'] == [G28_SENT] + [RAPID_SENT] * 4 + [PARK_SENT, SAVE_SENT]
    assert run['quick_stops'] == 0 and run['status'] == 14


def test_offset_stage_profile_entries_match_the_worker():
    """Data and send-return entries added for the scrub are the vendor's."""
    import json
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert {row['name']: int(row['address'], 16) for row in profile['data']} == {
        'is_rapid_mode': 0x384c570, 'auto_check_selected': 0x385fa88,
        'current_thr_number': 0x385c260, 'knife_pairing_failed': PAIRING_FAILED}
    assert {row['name']: int(row['address'], 16) for row in profile['sender_returns']} == {
        'offset_home': G28_SENT, 'offset_rapid': RAPID_SENT, 'offset_park': PARK_SENT}
    calls = {row['name']: int(row['address'], 16) for row in profile['functions']}
    for row in profile['sender_returns']:
        assert int(row['address'], 16) == calls[row['call']] + 4
    header = (ROOT / 'client-preload/unified-ui/native/profile1113.hpp').read_text()
    for group in ('functions', 'data', 'sender_returns'):
        for row in profile[group]:
            assert header.count('constexpr std::uintptr_t %s = %s;' % (row['name'], row['address'])) == 1


def test_every_worker_sender_is_profile_bound_and_guarded(tmp_path):
    import json
    import struct
    import subprocess
    from test_unified_ui import compile_cpp
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    calls = []
    # Independently enumerate the guide and four calibration workers directly
    # from the exact vendor binary; no ignored analysis inventory is required.
    for start, size in ((0x4b7558,5740),(0x509ef0,1080),(0x50a328,1176),(0x50a7c0,1804),(0x50aecc,1304)):
        for address in range(start,start+size,4):
            word = struct.unpack_from('<I', data, address-0x400000)[0]
            if word >> 26 != 0b100101:
                continue
            displacement = word & 0x3ffffff
            if displacement & (1 << 25):
                displacement -= 1 << 26
            if address + displacement*4 == 0x614338:
                calls.append(address)
    assert len(calls) == 32
    windows = [row for row in profile['functions'] if row['name'].startswith(('calibration_sender_', 'guide_calibration_sender_'))]
    assert {int(row['address'], 16) for row in windows} == set(calls)
    for row in windows:
        address = int(row['address'], 16)
        assert bytes.fromhex(row['bytes']) == data[address-0x400000:address-0x400000+32]
        word = struct.unpack_from('<I', data, address-0x400000)[0]
        assert word >> 26 == 0b100101
        displacement = word & 0x3ffffff
        if displacement & (1 << 25):
            displacement -= 1 << 26
        assert address + displacement*4 == 0x614338
    source = tmp_path / 'guard.cpp'
    source.write_text('''
#include "native/stock_maintenance_command.hpp"
#include <cassert>
using namespace wmp_ui::native;
int main(){
 for(auto caller:calibration_senders){
  const auto result=stock_calibration_command(caller,"T0");
  assert(result.find("_WMP_CALIBRATION_COMMAND HEX=")==0);
  if(caller==0x4b7cb8||caller==0x50a968)assert(result=="_WMP_CALIBRATION_COMMAND HEX=5f574d505f43414c4942524154494f4e5f544f4f4c20543d30");
  else assert(result=="_WMP_CALIBRATION_COMMAND HEX=5430");
  assert(stock_calibration_command(caller+1,"SAVE_CONFIG")=="SAVE_CONFIG");
 }
 assert(stock_calibration_command(0,"G28")=="G28");
 assert(stock_calibration_command(0x4b7828,std::string(257,'a'))=="_WMP_CALIBRATION_COMMAND HEX=");
}
'''.replace(' for(auto caller:calibration_senders){',
        ' const std::uintptr_t expected[]={' + ','.join(hex(a+4) for a in sorted(calls)) + '};\n'
        ' std::vector<std::uintptr_t> actual(std::begin(calibration_senders),std::end(calibration_senders));\n'
        ' std::sort(actual.begin(),actual.end());\n'
        ' assert(actual==std::vector<std::uintptr_t>(std::begin(expected),std::end(expected)));\n'
        ' for(auto caller:calibration_senders){').replace('#include <cassert>', '#include <cassert>\n#include <vector>\n#include <algorithm>'))
    binary = tmp_path / 'guard'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_calibration_constructor_hook_has_relocatable_profiled_entry():
    import json
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    row = next(row for row in profile['functions'] if row['name'] == 'setup_calibration')
    address = int(row['address'], 16)
    assert address == 0x4b6470
    assert bytes.fromhex(row['bytes']) == data[address-0x400000:address-0x400000+32]
    # STP frame/LR, MOV frame pointer, STR saved register, STR argument.
    # No ADRP, literal load, branch or other PC-relative relocation.
    assert data[address-0x400000:address-0x400000+16].hex() == 'fd7bb6a9fd030091f30b00f9e01700f9'


def test_first_run_checkpoint_transition_policy(tmp_path):
    import subprocess
    from test_unified_ui import compile_cpp
    source = tmp_path / 'flow.cpp'
    source.write_text(r'''
#include "native/stock_calibration_flow.hpp"
#include <cassert>
using namespace wmp_ui;using namespace wmp_ui::native;
int main(){
 Json ready={{"fresh",true},{"calibration_session","session"},{"calibration_active",false},{"calibration_failed",""},{"calibration_checkpoint","old"}};
 StockCalibrationFlow flow;
 assert(!flow.request("main_page","token"));
 assert(flow.request("guide_calibrating_page","new"));
 assert(!flow.request("guide_filament_page","replace"));
 auto stale=ready;stale["fresh"]=false;
 assert(!flow.needs_checkpoint(stale));assert(flow.needs_checkpoint(ready));
 flow.sent(ready);assert(!flow.needs_checkpoint(ready)&&flow.complete(ready).empty());
 ready["calibration_checkpoint"]="new";
 stale=ready;stale["fresh"]=false;assert(flow.complete(stale).empty());
 auto active=ready;active["calibration_active"]=true;assert(flow.complete(active).empty());
 assert(flow.complete(ready)=="guide_calibrating_page");assert(flow.complete(ready).empty());
 assert(flow.request("guide_filament_page","next"));flow.sent(ready);
 auto restarted=ready;restarted["calibration_session"]="other";restarted["calibration_checkpoint"]="next";
 assert(flow.complete(restarted).empty()&&flow.blocked());
 assert(!flow.request("guide_filament_page","again"));
 assert(flow.message().find("restarted")!=std::string::npos);
 StockCalibrationFlow failed;failed.request("guide_filament_page","check");failed.sent(ready);
 ready["calibration_failed"]="PID failed";ready["calibration_checkpoint"]="check";
 assert(failed.complete(ready).empty());ready["calibration_failed"]="";
 assert(failed.complete(ready).empty()&&failed.message().find("PID failed")!=std::string::npos);
 StockCalibrationFlow unsent;unsent.request("guide_filament_page","last");unsent.send_failed();
 assert(unsent.blocked()&&!unsent.needs_checkpoint(ready)&&unsent.complete(ready).empty());
}
''')
    binary = tmp_path / 'flow'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_maintenance_worker_entry_and_terminal_cleanup_are_profile_bound():
    import json
    if not CLIENT.is_file():
        pytest.skip('exact vendor client required')
    data = CLIENT.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    row = next(row for row in profile['functions'] if row['name'] == 'maintenance_calibration_worker')
    assert int(row['address'], 16) == 0x4b7558
    assert bytes.fromhex(row['bytes']) == data[0xb7558:0xb7578]
    # Only these sixteen relocatable stack/register instructions are copied.
    assert bytes.fromhex(row['bytes'])[:16].hex() == 'ff4319d1fd7b00a9fd030091f35301a9'
    # Exact final save call (return address used for receipt binding).
    word = int.from_bytes(data[0xb8698:0xb869c], 'little')
    displacement = word & 0x3ffffff
    if displacement & (1 << 25):
        displacement -= 1 << 26
    assert word >> 26 == 0b100101 and 0x4b8698 + displacement * 4 == 0x614338
