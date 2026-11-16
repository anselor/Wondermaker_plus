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
    (0x4c6490,6,0x4c65c0),(0x4c6490,7,0x4c66b0),
    (0x4c6490,8,0x4c67a0),(0x4c6490,9,0x4c67b4),
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


def test_factory_setup_registers_probe_and_other_service_actions():
    unicorn,cpu=machine()
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_PC
    registrations=[];finished=[]
    def step(machine,address,size,_):
        if address==0x4c5ddc:finished.append(True);machine.emu_stop();return
        word=int.from_bytes(machine.mem_read(address,4),'little')
        if word>>26!=0b100101:return
        offset=word&0x3ffffff
        if offset&0x2000000:offset-=0x4000000
        if address+offset*4==0x697b38:
            registrations.append(tuple(machine.reg_read(reg) for reg in
                (UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3)))
        machine.reg_write(UC_ARM64_REG_X0,0x5001800)  # modeled LVGL result, never dereferenced
        machine.reg_write(UC_ARM64_REG_PC,address+4)
    cpu.hook_add(unicorn.UC_HOOK_CODE,step)
    cpu.emu_start(0x4c5b60,0,count=3000)
    assert finished
    assert registrations==[(0x4c41a4,7,action) for action in range(9,15)]


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
