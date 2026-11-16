from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_exact_native_profile_unknown_host_and_never_call_addresses(tmp_path,native_client_elf):
 binary=ROOT/'build/native1113-port'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-O1','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/native1113_port.cpp'),'-o',str(binary)],check=True)
 wrong=tmp_path/'unknown';wrong.write_bytes(b'not the native client')
 actual=native_client_elf
 subprocess.run([str(binary),str(actual),str(wrong)],check=True)
