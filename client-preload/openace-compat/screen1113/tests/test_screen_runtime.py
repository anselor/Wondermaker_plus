from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def test_gui_never_does_http_and_worker_never_creates_widgets():
 out=ROOT/'build/screen-runtime'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/screen_runtime.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(ROOT/'fixtures/pending_compact.json')],check=True)
