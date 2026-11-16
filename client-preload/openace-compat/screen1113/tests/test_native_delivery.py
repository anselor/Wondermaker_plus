from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_exact_ticket_settlement_and_new_status_allow_one_deliberate_retry():
 out=ROOT/'build/native-delivery'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/native_delivery.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(ROOT/'fixtures/pending_compact.json')],check=True)
