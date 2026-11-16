from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_typed_nonmoving_management_request_is_revalidated_once_by_worker():
 out=ROOT/'build/management-delivery'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/management_delivery.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(ROOT/'fixtures/management_zero1078.json')],check=True)
