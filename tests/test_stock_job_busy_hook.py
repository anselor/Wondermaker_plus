"""Compare the busy-check trampoline with the exact vendor ARM prologue."""
from pathlib import Path
import subprocess
import pytest
ROOT = Path(__file__).resolve().parents[1]


def test_busy_check_prologue_preserves_stack_and_page_address(tmp_path):
    unicorn = pytest.importorskip('unicorn')
    arm = pytest.importorskip('unicorn.arm64_const')
    elf = ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('exact 1.1.13 client required')
    raw = elf.read_bytes()[0x519600-0x400000:0x519610-0x400000]
    source = tmp_path/'hook.cpp'
    source.write_text('''#include "stock_job_busy_hook.hpp"
#include <cstdio>
int main(){unsigned char input[16],output[40];
if(std::fread(input,1,16,stdin)!=16)return 1;
wmp_ui::native::stock_job_busy_trampoline(output,input);
return std::fwrite(output,1,40,stdout)==40?0:1;}
''')
    exe = tmp_path/'hook'
    subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror',
                    '-I'+str(ROOT/'client-preload/unified-ui/native'),str(source),'-o',str(exe)],check=True)
    relocated = subprocess.run([str(exe)],input=raw,stdout=subprocess.PIPE,check=True).stdout
    def execute(address, code, stop):
        u = unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM)
        u.mem_map(0x519000,0x1000);u.mem_map(0x100000,0x1000);u.mem_map(0x200000,0x2000)
        u.mem_write(address,code)
        for reg,value in [(arm.UC_ARM64_REG_SP,0x201000),(arm.UC_ARM64_REG_X19,19),
                          (arm.UC_ARM64_REG_X20,20),(arm.UC_ARM64_REG_X29,29),
                          (arm.UC_ARM64_REG_X30,30),(arm.UC_ARM64_REG_X0,42)]:
            u.reg_write(reg,value)
        u.emu_start(address,stop,count=20)
        return ([u.reg_read(r) for r in (arm.UC_ARM64_REG_SP,arm.UC_ARM64_REG_X0,
                arm.UC_ARM64_REG_X19,arm.UC_ARM64_REG_X20,arm.UC_ARM64_REG_X29,
                arm.UC_ARM64_REG_X30,arm.UC_ARM64_REG_PC)],bytes(u.mem_read(0x200f80,128)))
    assert execute(0x519600,raw,0x519610)==execute(0x100000,relocated,0x519610)
