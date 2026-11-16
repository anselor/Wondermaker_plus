from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def build_native_management_command():
 out=ROOT/'build/native-management-command'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(ROOT/'source/client'),'-I'+str(ROOT/'source/vendor'),str(ROOT/'tests/native_management_command.cpp'),'-o',str(out)],check=True)
 return out
def test_initial_assignment_is_a_complete_native_draft_before_first_apply():
 out=build_native_management_command()
 command=subprocess.check_output([str(out),str(ROOT/'fixtures/management_zero1078.json'),'set_filament','0','PLA','210','112233'],text=True)
 assert command.startswith('OPENACE_SET_FILAMENT HEAD="h0" MATERIAL="PLA" TEMP=210 COLOR=112233')
