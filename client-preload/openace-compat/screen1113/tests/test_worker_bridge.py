from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_worker_selective_status_bounded_queue_and_no_rebound_or_replay():
 binary=ROOT/'build/worker-bridge'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-O1','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/worker_bridge.cpp'),'-o',str(binary)],check=True)
 subprocess.run([str(binary),str(ROOT/'fixtures')],check=True)
