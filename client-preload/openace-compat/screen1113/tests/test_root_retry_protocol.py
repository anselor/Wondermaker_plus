from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_original_retry_sequence_with_explicit_delivery_ticket():
 out=ROOT/'build/root-retry-protocol'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/root_retry_protocol.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
