from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_actual_idle_geometry_leaves_room_for_open_panel():
    out=ROOT/'build/actual-main-layout'
    subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/actual_main_layout.cpp'),'-o',str(out)],check=True)
    subprocess.run([str(out),str(ROOT/'fixtures/management_zero1078.json')],check=True)
