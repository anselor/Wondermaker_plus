"""In-place stock widget layout contract; no printer activation."""
from pathlib import Path
import subprocess

def test_existing_widgets_reflow_without_touching_stock_shell(tmp_path):
    root = Path(__file__).resolve().parents[1]
    executable = tmp_path / 'stock-layout'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'client-preload/unified-ui'),
                    str(root / 'tests/unified_ui/stock_filament_layout.cpp'),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)

def test_stock_picker_keeps_source_and_revision_until_save(tmp_path):
    root = Path(__file__).resolve().parents[1]
    executable = tmp_path / 'stock-identity'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'client-preload/unified-ui'),
                    '-I' + str(root / 'client-preload/openace-compat/screen1113/source/vendor'),
                    str(root / 'tests/unified_ui/stock_identity_edit.cpp'),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
