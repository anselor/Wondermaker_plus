"""Proof against copied actual executable; no live patch/GUI invocation."""
from pathlib import Path
import struct
import capstone
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_SP,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X29,UC_ARM64_REG_X30
ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT.parents[2]/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
ADDRESS=0x6cf084

def elf_bytes(address,length):
 data=BINARY.read_bytes();assert data[:6]==b'\x7fELF\x02\x01'
 phoff=struct.unpack_from('<Q',data,32)[0]
 entsize,count=struct.unpack_from('<HH',data,54)
 for i in range(count):
  kind,flags,offset,vaddr,_,filesz,_,_=struct.unpack_from('<IIQQQQQQ',data,phoff+i*entsize)
  if kind==1 and vaddr<=address and address+length<=vaddr+filesz:
   assert flags&1
   return data[offset+address-vaddr:offset+address-vaddr+length]
 raise AssertionError('address outside executable load segment')

def test_actual_timer_prologue_is_position_independent_and_relocated_stack_arguments_match(native_client_elf):
 code=elf_bytes(ADDRESS,16)
 dis=list(capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM).disasm(code,ADDRESS))
 assert [(i.mnemonic,i.op_str) for i in dis]==[
  ('stp','x29, x30, [sp, #-0x40]!'),('mov','x29, sp'),
  ('str','x0, [sp, #0x28]'),('str','w1, [sp, #0x24]')]
 # Same exact jump stub as existing reviewed preload; x16 scratch is not argument state.
 jump=struct.pack('<IIQ',0x58000050,0xd61f0200,ADDRESS+16)
 def run(start,relocated):
  cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
  for base in (0x600000,0x1000000,0x2000000):cpu.mem_map(base,0x100000)
  cpu.mem_write(ADDRESS,code)
  cpu.mem_write(0x1000000,code+jump)
  cpu.reg_write(UC_ARM64_REG_SP,0x20ff000)
  cpu.reg_write(UC_ARM64_REG_X0,0xabc123)
  cpu.reg_write(UC_ARM64_REG_X1,100)
  cpu.reg_write(UC_ARM64_REG_X29,0x12345)
  cpu.reg_write(UC_ARM64_REG_X30,0x54321)
  cpu.emu_start(start,ADDRESS+16,count=6 if relocated else 4)
  return tuple(cpu.reg_read(r) for r in (UC_ARM64_REG_SP,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X29,UC_ARM64_REG_X30)),bytes(cpu.mem_read(0x20fefc0,64))
 assert run(ADDRESS,False)==run(0x1000000,True)
