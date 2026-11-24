"""Execute the frozen Home refresh with its filament-only tail replaced."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
CLIENT=ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


@pytest.fixture(scope='module')
def stock():
    if not CLIENT.is_file():pytest.skip('retained stock client required')
    capstone=pytest.importorskip('capstone');pytest.importorskip('unicorn')
    data=CLIENT.read_bytes();profile=json.loads((ROOT/'client-preload/unified-ui/native/profile1113.json').read_text())
    assert hashlib.sha256(data).hexdigest()==profile['client_sha256']
    symbols={p[2]:int(p[0],16) for row in subprocess.check_output(['nm','-n',str(CLIENT)],text=True).splitlines() if len(p:=row.split())==3}
    rows={r['name']:int(r['address'],16) for r in profile['functions']}
    headers=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
    loads=[s for i in range(count) if (s:=struct.unpack_from('<IIQQQQQQ',data,headers+i*size))[0]==1]
    start=rows['main_update_common'];end=rows['main_common_return']+12
    decoder=capstone.Cs(capstone.CS_ARCH_ARM64,0);decoder.detail=True
    instructions=list(decoder.disasm(data[start-0x400000:end-0x400000],start))
    calls={i.address:i.operands[0].imm for i in instructions if i.mnemonic=='bl'}
    assert rows['main_filament_updates']==0x51df74 and rows['main_common_return']==0x51e168
    assert next(i for i in instructions if i.address==rows['main_common_return']).mnemonic=='ldr'
    return data,loads,symbols,rows,calls


def execute(stock,patched,selected,loaded,counter):
    import unicorn
    from unicorn import arm64_const as r
    data,loads,symbols,rows,calls=stock
    emu=unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM)
    emu.mem_map(0x400000,((max(s[3]+s[6] for s in loads)+4095)&~4095)-0x400000)
    for _,_,offset,address,_,length,_,_ in loads:emu.mem_write(address,data[offset:offset+length])
    emu.mem_map(0x20000000,0x200000)
    def integer(name,value):emu.mem_write(symbols[name],struct.pack('<i',value))
    integer('current_thr_number',4);integer('current_extruder',selected);integer('device_type',2)
    integer('_ZZL20update_common_statusvE3cnt',counter)
    emu.mem_write(symbols['filament_detected'],bytes([loaded]*4))
    for i in range(4):emu.mem_write(symbols['_ZL12img_filament']+8*i,struct.pack('<Q',0x100+i))
    emu.mem_write(symbols['_ZL7img_led'],struct.pack('<Q',0x200));emu.mem_write(symbols['_ZL7img_fan'],struct.pack('<Q',0x201))
    emu.mem_write(symbols['fan_speed'],bytes([1,0,0]));emu.mem_write(symbols['led_on'],b'\x01')
    if patched:emu.mem_write(rows['main_filament_updates'],struct.pack('<IIQ',0x58000050,0xd61f0200,rows['main_common_return']))
    events=[]
    def hook(uc,address,size,_):
        if address not in calls:return
        target=calls[address];x0=uc.reg_read(r.UC_ARM64_REG_X0);x1=uc.reg_read(r.UC_ARM64_REG_X1)
        events.append((address,target,x0,x1))
        result=1 if target==symbols['_Z18get_GPIO2_B4_valuev'] else 0x20101000 if target in (0x445860,rows['lv_i18n_get_text']) else 0
        uc.reg_write(r.UC_ARM64_REG_X0,result);uc.reg_write(r.UC_ARM64_REG_X30,address+4);uc.reg_write(r.UC_ARM64_REG_PC,address+4)
    emu.hook_add(unicorn.UC_HOOK_CODE,hook)
    sp=0x200ff000;stop=0x201ff000;sentinels={getattr(r,'UC_ARM64_REG_X'+str(i)):0x100000+i for i in range(19,30)}
    for register,value in sentinels.items():emu.reg_write(register,value)
    emu.reg_write(r.UC_ARM64_REG_SP,sp);emu.reg_write(r.UC_ARM64_REG_X30,stop)
    emu.emu_start(rows['main_update_common'],stop,timeout=5000000,count=1000000)
    assert emu.reg_read(r.UC_ARM64_REG_PC)==stop and emu.reg_read(r.UC_ARM64_REG_SP)==sp
    assert all(emu.reg_read(register)==value for register,value in sentinels.items())
    count=struct.unpack('<i',emu.mem_read(symbols['_ZZL20update_common_statusvE3cnt'],4))[0]
    return events,count,bytes(emu.mem_read(symbols['led_on'],1))


@pytest.mark.parametrize('selected',[0,2,99])
@pytest.mark.parametrize('loaded',[0,1])
@pytest.mark.parametrize('counter',[0,49])
def test_home_replacement_keeps_temperature_light_fan_and_frame(stock,selected,loaded,counter):
    before,count,led=execute(stock,False,selected,loaded,counter)
    after,new_count,new_led=execute(stock,True,selected,loaded,counter)
    rows=stock[3];site=rows['main_filament_updates'];image=rows['lv_img_set_src']
    assert after==[call for call in before if call[0]<site]
    assert len([call for call in before if call[1]==image and call[2] in range(0x100,0x104)])==4
    assert not any(call[1]==image and call[2] in range(0x100,0x104) for call in after)
    assert {call[2] for call in after if call[1]==image}=={0x200,0x201}
    assert (count,led)==(new_count,new_led)
