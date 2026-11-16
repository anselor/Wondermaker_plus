from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_bounded_private_diagnostics_and_gui_has_no_io():
    output = ROOT / 'build/diagnostics-contract'
    subprocess.run([
        'g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-I' + str(ROOT / 'source/client'), '-I' + str(ROOT / 'source/vendor'),
        str(ROOT / 'tests/diagnostics.cpp'), '-Wl,--wrap=open',
        '-Wl,--wrap=write', '-Wl,--wrap=socket', '-o', str(output)], check=True)
    subprocess.run([str(output), str(ROOT / 'fixtures/moonraker_idle_filtered.json')], check=True)
