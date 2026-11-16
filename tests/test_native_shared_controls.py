"""Shared controls can be included directly by a new consumer."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT/'client-preload/unified-ui'


@pytest.mark.parametrize('header', [
    'stock_option_row.hpp', 'stock_header_action.hpp', 'stock_progress_panel.hpp', 'stock_navigation_tabs.hpp'])
def test_shared_control_headers_are_self_contained(tmp_path, header):
    source = tmp_path/'consumer.cpp'
    source.write_text('#include "native/'+header+'"\nint main(){return 0;}\n')
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                    '-fsyntax-only', '-I'+str(UI),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/vendor'),
                    str(source)], check=True)
