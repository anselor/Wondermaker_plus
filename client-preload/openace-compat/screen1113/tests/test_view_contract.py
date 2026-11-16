from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]

def build():
 binary=ROOT/'build/view-contract';binary.parent.mkdir(exist_ok=True)
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-O1','-I'+str(ROOT/'source/vendor'),'-I'+str(ROOT/'source/client'),str(ROOT/'tests/view_contract.cpp'),'-o',str(binary)],check=True)
 return binary

def test_cpp_view_and_explicit_click_contract():
 subprocess.run([str(build()),str(ROOT/'fixtures')],check=True)
