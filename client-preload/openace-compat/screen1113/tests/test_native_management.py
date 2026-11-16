from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_native_fixed_setup_buttons_require_review_apply_and_preserve_material_priority():
 out=ROOT/'build/native-management'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/native_management.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(ROOT/'fixtures/management_zero1078.json')],check=True)
