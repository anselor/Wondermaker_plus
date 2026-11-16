from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_exact_refresh_association_and_native_exception_boundary():
 binary=ROOT/'build/refresh-bridge'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'source/client'),str(ROOT/'tests/refresh_bridge.cpp'),'-o',str(binary)],check=True)
 subprocess.run([str(binary)],check=True)
