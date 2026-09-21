"""Exercise deploy routing without contacting a printer."""
import importlib.util
import sys
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'tested_deploy', Path(__file__).resolve().parents[1] / 'tools/deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
config = deploy.REGISTRY['config']


def test_http_only_update_never_opens_ssh(monkeypatch):
    monkeypatch.setattr(sys, 'argv', [
        'deploy.py', 'install', 'config', '--config-only', '--no-restart',
        '--files', 'macros.cfg'])
    monkeypatch.setenv('WMP_PRINTER', 'printer.example')
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda self: False)
    def no_ssh(self):
        pytest.fail('HTTP-only update attempted SSH')
    monkeypatch.setattr(deploy.Context, 'ssh', no_ssh)
    calls = []
    monkeypatch.setattr(config, '_sync', lambda args, env: calls.append((args, env)) or 0)
    assert deploy.main() == 0
    assert calls == [(['push', '--yes', '--no-restart', 'macros.cfg'],
                      {'WMP_PRINTER': 'printer.example'})]


@pytest.mark.parametrize('config_only', [False, True])
def test_install_order_restart_and_push_failure(monkeypatch, config_only):
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config'] +
                        (['--config-only'] if config_only else []))
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda self: False)
    calls = []
    monkeypatch.setattr(config, '_install_extra', lambda ctx: calls.append('extra'))
    monkeypatch.setattr(config, '_sync', lambda args, env: calls.append(args) or 1)
    assert deploy.main() == 1
    assert calls == ([] if config_only else ['extra']) + [['push', '--yes']]


def test_http_update_refused_during_print(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config', '--config-only'])
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda self: True)
    monkeypatch.setattr(config, '_sync', lambda *args: pytest.fail('uploaded during print'))
    with pytest.raises(SystemExit, match='print is in progress'):
        deploy.main()


@pytest.mark.parametrize('arguments', [
    ['install', 'all'], ['install', 'material'], ['status', 'config'],
    ['uninstall', 'config'], ['install', 'config', 'preload'], ['list'],
])
def test_config_only_rejects_other_actions_and_components(monkeypatch, arguments):
    monkeypatch.setattr(sys, 'argv', ['deploy.py', *arguments, '--config-only'])
    with pytest.raises(SystemExit) as exc:
        deploy.main()
    assert exc.value.code == 2
