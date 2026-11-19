"""Guided nozzle scrub flow: states, screen text and queued scrub commands."""
import subprocess
from pathlib import Path
from test_unified_ui import compile_cpp


def test_nozzle_scrub_flow(tmp_path):
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / 'nozzle-scrub-flow'
    compile_cpp(root / 'tests/unified_ui/nozzle_scrub_flow.cpp', binary)
    subprocess.run([str(binary)], check=True, timeout=10)
