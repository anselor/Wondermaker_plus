from pathlib import Path
import subprocess
P=Path(__file__).resolve().parents[1]
def test_physical_delivery_stale_fractional_restart_and_native_stop_boundaries():
 out=P/'build/manual-flow-controls'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(P/'source/client'),'-I'+str(P/'source/vendor'),str(P/'tests/manual_flow_controls.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(P/'fixtures')],check=True)


def test_unchanged_root_cross_head_pending_reply_never_invites_insertion():
 out=P/'build/root-manual-pending-scope'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(P/'source/client'),'-I'+str(P/'source/vendor'),str(P/'tests/root_manual_pending_scope.cpp'),'-o',str(out)],check=True)
 subprocess.run([str(out),str(P/'fixtures/manual_planned1084.json')],check=True)
