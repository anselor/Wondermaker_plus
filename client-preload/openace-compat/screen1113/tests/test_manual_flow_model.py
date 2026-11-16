from pathlib import Path
import subprocess
P=Path(__file__).resolve().parents[1]
def test_ordinary_paused_null_prompt_has_owned_manual_actions():
 out=P/'build/manual-flow-model'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(P/'source/client'),'-I'+str(P/'source/vendor'),str(P/'tests/manual_flow_model.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(P/'fixtures/manual_ordinary1084.json')],check=True)
