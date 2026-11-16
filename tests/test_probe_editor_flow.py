"""Native action controller emits only explicit, session-bound requests."""
import subprocess
from pathlib import Path
from test_unified_ui import compile_cpp


def test_probe_editor_flow(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / 'probe-editor-flow'
    compile_cpp(root / 'tests/unified_ui/probe_editor_flow.cpp', binary)
    subprocess.run([str(binary)], check=True, timeout=10)


def test_probe_editor_worker(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / 'probe-editor-worker'
    compile_cpp(root / 'tests/unified_ui/probe_editor_worker.cpp', binary)
    subprocess.run([str(binary)], check=True, timeout=15)
