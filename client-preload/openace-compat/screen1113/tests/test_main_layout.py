from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_only_proven_printing_or_measured_known_idle_frame_is_usable():
 out=ROOT/'build/main-layout'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/main_layout.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
