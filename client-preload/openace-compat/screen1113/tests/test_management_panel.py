from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_fixed_setup_pages_require_review_and_explicit_apply_and_current_retry():
 binary=ROOT/'build/management-panel'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/management_panel.cpp'),'-o',str(binary)],check=True)
 subprocess.run([str(binary),str(ROOT/'fixtures/management_zero1078.json')],check=True)
