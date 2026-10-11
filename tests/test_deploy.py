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


@pytest.fixture(autouse=True)
def stub_config_preflight(monkeypatch):
    # These routing tests isolate preflight; prerequisite checks have their own tests.
    monkeypatch.setattr(config, 'preflight', lambda ctx: None)


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
    assert calls == ([] if config_only else ['extra']) + [['push', '--yes', '--no-restart']]


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


def components_for_test(monkeypatch, events, fail_preflight=None, fail_install=None):
    from types import SimpleNamespace
    def component(name):
        def preflight(ctx):
            events.append(('check', name))
            if name == fail_preflight:
                raise deploy.DeployError('unsupported client')
        def install(ctx):
            events.append(('install', name))
            if name == fail_install:
                raise deploy.DeployError('upload failed')
        return SimpleNamespace(NAME=name, preflight=preflight, install=install, RESTART_AFTER=None)
    names = ['config', 'touchscreen', 'preload']
    monkeypatch.setattr(deploy, 'ORDER', names)
    monkeypatch.setattr(deploy, 'REGISTRY', {n: component(n) for n in names})
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: False)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'all'])


def test_late_preflight_failure_prevents_every_install(monkeypatch):
    events = []
    components_for_test(monkeypatch, events, fail_preflight='preload')
    assert deploy.main() == 1
    assert events == [('check', n) for n in deploy.ORDER]


def test_all_checks_finish_before_first_mutation(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    assert deploy.main() == 0
    assert events == [('check', n) for n in deploy.ORDER] + [('install', n) for n in deploy.ORDER]


def test_preflight_only_never_installs(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    sys.argv.append('--preflight-only')
    assert deploy.main() == 0
    assert events == [('check', n) for n in deploy.ORDER]


def test_apply_failure_stops_later_components(monkeypatch):
    events = []
    components_for_test(monkeypatch, events, fail_install='touchscreen')
    assert deploy.main() == 1
    assert ('install', 'preload') not in events


@pytest.mark.parametrize('state,blocked', [('paused', True), ('printing', True), ('standby', False)])
def test_print_state_parsed_independent_of_json_whitespace(monkeypatch, state, blocked):
    import json
    ctx = deploy.Context(type('Args', (), {})())
    monkeypatch.setattr(ctx, 'moonraker', lambda path: json.dumps({'result': {'status': {'print_stats': {'state': state}}}}, separators=(',', ':')))
    assert ctx.printing_now() == blocked


def test_unreachable_printer_does_not_count_as_idle(monkeypatch):
    ctx = deploy.Context(type('Args', (), {})())
    def fail(path):
        raise OSError('offline')
    monkeypatch.setattr(ctx, 'moonraker', fail)
    with pytest.raises(deploy.DeployError, match='cannot establish'):
        ctx.printing_now()


def test_print_started_during_preflight_prevents_install(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    states = iter([False, True])
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: next(states))
    assert deploy.main() == 1
    assert events == [('check', n) for n in deploy.ORDER]


def test_config_and_material_activate_together_after_uploads(monkeypatch):
    from types import SimpleNamespace
    events = []
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config', 'material'])
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: False)
    monkeypatch.setattr(config, '_install_extra', lambda ctx: events.append('extra'))
    def sync(args, env=None):
        assert args == ['push', '--yes', '--no-restart']
        events.append('config files')
        return 0
    monkeypatch.setattr(config, '_sync', sync)
    monkeypatch.setattr(config, 'status', lambda ctx: None)
    material = SimpleNamespace(NAME='material', RESTART_AFTER='klipper',
                               preflight=lambda ctx: None, install=lambda ctx: events.append('material'),
                               status=lambda ctx: None)
    monkeypatch.setitem(deploy.REGISTRY, 'material', material)
    monkeypatch.setattr(deploy.Context, 'restart_klipper', lambda ctx: events.append('restart') or True)
    assert deploy.main() == 0
    assert events == ['extra', 'config files', 'material', 'restart']


def test_print_started_after_upload_defers_restart(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config'])
    states = iter([False, False, True])
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: next(states))
    monkeypatch.setattr(config, '_install_extra', lambda ctx: None)
    monkeypatch.setattr(config, '_sync', lambda *args: 0)
    monkeypatch.setattr(deploy.Context, 'restart_klipper', lambda ctx: pytest.fail('restarted during print'))
    assert deploy.main() == 1
