"""Only the pinned stock Resume preheat callsites get authoritative routing."""
import hashlib
import struct
import subprocess
from pathlib import Path
from test_unified_ui import compile_cpp

ROOT = Path(__file__).resolve().parents[1]

def test_preheat_routing_does_not_capture_manual_heater_commands(tmp_path):
    source = tmp_path / 'resume.cpp'
    source.write_text(r'''
#include "native/stock_resume_preheat.hpp"
#include <cassert>
int main(){
 using wmp_ui::native::stock_resume_preheat_command;
 const std::string m104="M104 T2 S240";
 const std::string m109="M109 T2 S240";
 const std::string variable="SET_GCODE_VARIABLE MACRO=RESUME VARIABLE=resume_temperature2 VALUE=240";
 assert(stock_resume_preheat_command(0x51a4dc,m104)=="_WMP_SCREEN_RESUME_PREHEAT COMMAND_HEX=4d3130342054322053323430");
 assert(stock_resume_preheat_command(0x51a580,variable).find("_WMP_SCREEN_RESUME_PREHEAT COMMAND_HEX=")==0);
 assert(stock_resume_preheat_command(0x51a644,m109)=="_WMP_SCREEN_RESUME_PREHEAT COMMAND_HEX=4d3130392054322053323430");
 for(auto caller:{0U,0x51b884U,0x51a4d8U,0x51a648U}){
  assert(stock_resume_preheat_command(caller,m104)==m104);
  assert(stock_resume_preheat_command(caller,m109)==m109);
  assert(stock_resume_preheat_command(caller,variable)==variable);
 }
}
''')
    binary = tmp_path / 'resume'
    compile_cpp(source, binary)
    subprocess.run([str(binary)], check=True)


def test_preheat_origins_are_actual_pinned_vendor_sender_calls():
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    binary = path.read_bytes()
    assert hashlib.sha256(binary).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    phoff = struct.unpack_from('<Q', binary, 32)[0]
    size, count = struct.unpack_from('<HH', binary, 54)
    def word(address):
        for i in range(count):
            kind, flags, offset, virtual, physical, length, memory, align = struct.unpack_from('<IIQQQQQQ', binary, phoff + i*size)
            if kind == 1 and virtual <= address < virtual + length:
                return struct.unpack_from('<I', binary, offset + address - virtual)[0]
        raise AssertionError('address not in loadable segment')
    def branch(address, target):
        value = word(address)
        assert value >> 26 == 0b100101
        offset = value & ((1 << 26)-1)
        if offset & (1 << 25): offset -= 1 << 26
        assert address + offset * 4 == target
    for address in (0x51a4d8, 0x51a57c, 0x51a640): branch(address, 0x614338)
    branch(0x51b850, 0x51a344)  # Direct preheat branch before sending RESUME.
    branch(0x51b880, 0x614338)
    bootstrap = (ROOT / 'client-preload/unified-ui/native/bootstrap.cpp').read_text()
    assert 'stock_resume_preheat_command(caller,command)' in bootstrap
