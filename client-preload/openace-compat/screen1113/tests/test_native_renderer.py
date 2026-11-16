from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def build_native_renderer():
 binary=ROOT/'build/native-renderer'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/native_renderer.cpp'),'-o',str(binary)],check=True)
 return binary

def test_native_port_lifecycle_layout_and_explicit_context():
 subprocess.run([str(build_native_renderer())],check=True)
