"""Release checks for local configuration and tracked environment details."""
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def tracked_files():
    names = subprocess.check_output(
        ['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    return [ROOT / name.decode() for name in names if name]


def test_local_environment_is_ignored_and_example_is_safe():
    ignored = subprocess.run(
        ['git', 'check-ignore', '-q', '.env'], cwd=ROOT).returncode == 0
    assert ignored
    example = (ROOT / '.env.example').read_text()
    assert 'WMP_PRINTER=' in example
    assert 'WMP_USER=' in example
    assert 'WMP_PASS=' in example
    assert '192.168.' not in example


def test_project_declares_klipper_compatible_license():
    license_text = (ROOT / 'LICENSE').read_text()
    readme = (ROOT / 'README.md').read_text()
    assert 'GNU GENERAL PUBLIC LICENSE' in license_text
    assert 'Version 3, 29 June 2007' in license_text
    assert '[GNU General Public License version 3](LICENSE)' in readme
    assert 'does not\nrelicense that material' in readme


def test_tracked_host_tools_have_no_private_address_or_stock_password():
    private_address = b'.'.join((b'192', b'168', b'40', b'83'))
    stock_password = b''.join((b'TM', b'888', b'88'))
    forbidden = [re.compile(re.escape(private_address)),
                 re.compile(re.escape(stock_password))]
    offenders = []
    for path in tracked_files():
        if not path.exists():  # staged/working-tree deletion
            continue
        data = path.read_bytes()
        for pattern in forbidden:
            if pattern.search(data):
                offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, 'local connection details in tracked files: %s' % offenders


def test_local_env_does_not_override_explicit_environment(tmp_path, monkeypatch):
    from tools import local_env
    path = tmp_path / '.env'
    path.write_text('WMP_PRINTER=file-value\nQUOTED="hello world"\n')
    monkeypatch.setenv('WMP_PRINTER', 'process-value')
    monkeypatch.delenv('QUOTED', raising=False)
    local_env.load_local_env(path)
    assert os.environ['WMP_PRINTER'] == 'process-value'
    assert os.environ['QUOTED'] == 'hello world'


def test_missing_connection_setting_has_actionable_error(tmp_path):
    source = (ROOT / 'tools/local_env.py').read_text()
    (tmp_path / 'local_env.py').write_text(source)
    run = subprocess.run(
        ['python3', '-c',
         'import os; os.environ.pop("WMP_PRINTER", None); '
         'import local_env; local_env.require("WMP_PRINTER")'],
        cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode != 0
    assert 'copy .env.example to .env' in run.stderr


def test_ssh_host_keys_are_verified_by_default(monkeypatch):
    from tools import local_env
    calls = []
    class Client:
        def load_system_host_keys(self): calls.append('system')
        def load_host_keys(self, path): calls.append(('file', path))
        def set_missing_host_key_policy(self, policy): calls.append('auto-add')
    monkeypatch.delenv('WMP_SSH_AUTO_ADD', raising=False)
    monkeypatch.delenv('WMP_SSH_KNOWN_HOSTS', raising=False)
    local_env.configure_ssh_client(Client())
    assert calls == ['system']
