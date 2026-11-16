"""Execute exact factory dispatch branches offline; no printer or native UI load."""
import hashlib
from pathlib import Path
import pytest

CLIENT=Path(__file__).resolve().parents[1]/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


def machine():
    unicorn=pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_SP
    data=CLIENT.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    cpu=unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM)
    cpu.mem_map(0x4c4000,0x5000);cpu.mem_write(0x4c4000,data[0xc4000:0xc9000])
    cpu.mem_map(0x86f000,0x3000);cpu.mem_write(0x86f000,data[0x46f000:0x472000])
    for address in (0x5000000,0x365a000,0xe645000,0x3861000):cpu.mem_map(address,0x2000)
    cpu.reg_write(UC_ARM64_REG_SP,0x5001000)
    return unicorn,cpu


@pytest.mark.parametrize('entry,action,terminal',[
    (0x4c41a4,8,0x4c45a8),(0x4c41a4,9,0x4c4484),
    (0x4c41a4,10,0x4c46cc),(0x4c41a4,12,0x4c4794),
    (0x4c41a4,13,0x4c487c),(0x4c41a4,14,0x4c4904),
])
def test_factory_action_dispatch(entry,action,terminal):
    unicorn,cpu=machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_PC
    reached=[]
    def step(machine,address,size,_):
        if address==terminal:reached.append(address);machine.emu_stop();return
        word=int.from_bytes(machine.mem_read(address,4),'little')
        if word>>26==0b100101:
            offset=word&0x3ffffff
            if offset&0x2000000:offset-=0x4000000
            target=address+offset*4
            assert target in (0x6979fc,0x697a30),hex(target)
            machine.reg_write(UC_ARM64_REG_X0,7 if target==0x6979fc else action)
            machine.reg_write(UC_ARM64_REG_PC,address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE,step)
    cpu.emu_start(entry,0,count=100)
    assert reached==[terminal]


@pytest.mark.parametrize('needs_home',[False,True])
def test_factory_probe_prefix_and_navigation(needs_home):
    unicorn,cpu=machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_PC
    commands=[];strings=[];navigation=[]
    def step(machine,address,size,_):
        if address==0x4c4874:
            navigation.append('draw_probe_calibrate');machine.emu_stop();return
        word=int.from_bytes(machine.mem_read(address,4),'little')
        if word>>26!=0b100101:return
        offset=word&0x3ffffff
        if offset&0x2000000:offset-=0x4000000
        target=address+offset*4
        if target==0x4b3b94:machine.reg_write(UC_ARM64_REG_X0,int(needs_home))
        elif target==0x446c10:
            pointer=machine.reg_read(UC_ARM64_REG_X1)
            strings.append(bytes(machine.mem_read(pointer,100)).split(b'\0')[0].decode())
        elif target==0x614338:commands.append(strings[-1])
        else:assert target in (0x447050,0x4469f0,0x447720),hex(target)
        machine.reg_write(UC_ARM64_REG_PC,address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE,step)
    cpu.emu_start(0x4c4794,0,count=200)
    assert commands==(['G28'] if needs_home else [])+['T0','PROBE_CALIBRATE']
    assert navigation==['draw_probe_calibrate']



@pytest.mark.parametrize('name,address,stack_word', [
    ('factory_event', 0x4c41a4, 0xd10c43ff),
    ('knife_event', 0x4c6490, 0xd11243ff),
])
def test_factory_hook_prologue_is_relocatable_and_profile_bound(name, address, stack_word):
    import json
    import struct
    root = Path(__file__).resolve().parents[1]
    data = CLIENT.read_bytes()
    profile = json.loads((root / 'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest() == profile['client_sha256']
    window = next(row for row in profile['functions'] if row['name'] == name)
    assert int(window['address'], 16) == address
    assert data[address-0x400000:address-0x400000+32].hex() == window['bytes']
    # SUB SP; STP FP/LR; MOV FP,SP; STR X19: no PC-relative operands.
    assert struct.unpack_from('<4I', data, address-0x400000) == (stack_word, 0xa9007bfd, 0x910003fd, 0xf9000bf3)


@pytest.mark.parametrize('entry,action,terminal,expected',[
    (0x4c76dc,12,0x4c7e74,['ABORT']),
    (0x4c76dc,13,0x4c7e10,['ACCEPT','SAVE_CONFIG']),
    (0x53d150,12,0x53d8e0,['ABORT']),
    (0x53d150,13,0x53d880,['ACCEPT','SAVE_CONFIG']),
])
def test_probe_editors_abort_and_save_dispatch(entry,action,terminal,expected):
    unicorn,cpu=machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_PC
    data=CLIENT.read_bytes()
    cpu.mem_map(0x53d000,0x2000);cpu.mem_write(0x53d000,data[0x13d000:0x13f000])
    commands=[];strings=[];finished=[]
    def step(machine,address,size,_):
        if address==terminal:finished.append(True);machine.emu_stop();return
        word=int.from_bytes(machine.mem_read(address,4),'little')
        if word>>26!=0b100101:return
        offset=word&0x3ffffff
        if offset&0x2000000:offset-=0x4000000
        target=address+offset*4
        if target==0x6979fc:machine.reg_write(UC_ARM64_REG_X0,7)
        elif target==0x697a30:machine.reg_write(UC_ARM64_REG_X0,action)
        elif target==0x446c10:
            pointer=machine.reg_read(UC_ARM64_REG_X1)
            strings.append(bytes(machine.mem_read(pointer,100)).split(b'\0')[0].decode())
        elif target==0x614338:commands.append(strings[-1])
        else:assert target in (0x447050,0x4469f0,0x447720,0x6aef1c,0x553b6c),hex(target)
        machine.reg_write(UC_ARM64_REG_PC,address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE,step)
    cpu.emu_start(entry,0,count=500)
    assert finished and commands==expected


def test_factory_password_success_helper_has_separate_trigger_sender():
    unicorn, cpu = machine()
    from unicorn.arm64_const import UC_ARM64_REG_X1, UC_ARM64_REG_PC
    # This helper also clears need_pass. Observe it without changing real UI.
    cpu.mem_map(0x384c000, 0x1000)
    cpu.mem_write(0x384ca00, b'\x01')
    commands, strings = [], []
    def step(machine, address, size, _):
        if address == 0x4c4198:
            machine.emu_stop()
            return
        word = int.from_bytes(machine.mem_read(address, 4), 'little')
        if word >> 26 != 0b100101:
            return
        offset = word & 0x3ffffff
        if offset & 0x2000000:
            offset -= 0x4000000
        target = address + offset * 4
        if target == 0x446c10:
            pointer = machine.reg_read(UC_ARM64_REG_X1)
            strings.append(bytes(machine.mem_read(pointer, 100)).split(b'\0')[0].decode())
        elif target == 0x614338:
            commands.append((address+4, strings[-1]))
        else:
            assert target in (0x447050, 0x4469f0, 0x447720)
        machine.reg_write(UC_ARM64_REG_PC, address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE, step)
    cpu.emu_start(0x4c411c, 0, count=100)
    assert bytes(cpu.mem_read(0x384ca00, 1)) == b'\0'
    assert commands == [(0x4c4160, '_LEVELING_TRIGGER')]


@pytest.mark.parametrize('actions,opens', [
    ([2]*3+[3]*5, True),
    ([2]*2+[3]*5, False),
    ([2]*4+[3]*5, False),
    ([2]*3+[3]*4, False),
    ([2]*3+[3]*2+[2]+[3]*5, False),
])
def test_about_factory_entry_uses_device_then_version_gesture(actions, opens):
    unicorn, cpu = machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X30, UC_ARM64_REG_PC
    raw = CLIENT.read_bytes()
    for address in (0x4b0000, 0x385f000, 0x446000, 0x553000):
        cpu.mem_map(address, 4096)
        if address != 0x385f000:
            cpu.mem_write(address, raw[address-0x400000:address-0x400000+4096])
    pages = []
    def calls(machine, address, size, _):
        if address not in (0x4463c0, 0x553b6c):
            return
        if address == 0x553b6c:
            pointer = machine.reg_read(UC_ARM64_REG_X0)
            pages.append(bytes(machine.mem_read(pointer, 32)).split(b'\0')[0])
        machine.reg_write(UC_ARM64_REG_PC, machine.reg_read(UC_ARM64_REG_X30))
    cpu.hook_add(unicorn.UC_HOOK_CODE, calls)
    for action in actions:
        cpu.emu_start(0x4b03bc if action == 2 else 0x4b0408, 0x4b04c0, count=100)
        assert cpu.reg_read(UC_ARM64_REG_PC) == 0x4b04c0
    assert pages == ([b'factory_mode_page'] if opens else [])
