"""Host-only native cancellation transport; no printer requests."""
from pathlib import Path
import subprocess
from test_unified_ui import compile_cpp


def test_calibration_cancel_transport_is_bound_and_does_not_retry(tmp_path):
    root=Path(__file__).resolve().parents[1]
    binary=tmp_path/'calibration-cancel-worker'
    compile_cpp(root/'tests/unified_ui/calibration_cancel_worker.cpp',binary)
    subprocess.run([str(binary)],check=True,timeout=15)
