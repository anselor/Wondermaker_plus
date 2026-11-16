"""Fault injection for native startup patches; never loads into the printer."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_hook_transaction_restores_every_partial_install(tmp_path):
    executable = tmp_path / 'hook-transaction'
    subprocess.run([
        'g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
        '-I' + str(ROOT / 'client-preload/unified-ui'),
        str(ROOT / 'tests/unified_ui/hook_transaction.cpp'),
        '-o', str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)


def test_bootstrap_arm_transaction_branch_compiles():
    # Syntax-only deliberately checks the ARM-only bootstrap on the host;
    # inline ARM assembly is not assembled/executed.
    source = ROOT / 'client-preload/unified-ui/native/bootstrap.cpp'
    subprocess.run([
        'g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-D__aarch64__', '-fsyntax-only',
        '-I' + str(ROOT / 'client-preload/openace-compat/screen1113/source/client'),
        '-I' + str(ROOT / 'client-preload/openace-compat/screen1113/source/vendor'),
        str(source),
    ], check=True, timeout=120)
