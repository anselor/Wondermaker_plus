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


def test_config_installs_both_helpers_with_backups_and_idempotence(tmp_path):
    from types import SimpleNamespace
    extras = tmp_path / 'home/test/klipper/klippy/extras'
    extras.mkdir(parents=True)
    old = extras / 'wmp_case_light.py'
    old.write_bytes(b'previous light helper')
    renames = []
    def mapped(path):
        return tmp_path / path.lstrip('/')
    def rename(source, destination):
        renames.append(destination)
        mapped(source).replace(mapped(destination))
    sftp = SimpleNamespace(open=lambda path, mode: mapped(path).open(mode),
                           posix_rename=rename)
    ctx = SimpleNamespace(user='test', sftp=lambda: sftp)
    config._install_extra(ctx)
    for name in ('wmp_recovery.py', 'wmp_case_light.py'):
        assert (extras / name).read_bytes() == (Path(config.ROOT) / 'klipper_extras' / name).read_bytes()
    backups = list(extras.glob('wmp_case_light.py.wmp-backup-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == b'previous light helper'
    assert not list(extras.glob('*.wmp-upload-*'))
    assert len(renames) == 2
    config._install_extra(ctx)
    assert len(renames) == 2


def test_sudo_password_uses_stdin_without_shell_interpolation(monkeypatch):
    import io
    from types import SimpleNamespace as NS
    from components import touchscreen
    password = "test '$dollar; characters"
    monkeypatch.setattr(touchscreen, 'PASS', password)
    stdin, stdout = io.StringIO(), io.StringIO('done\n')
    stdin.channel = NS(shutdown_write=lambda: None)
    stdout.channel = NS(recv_exit_status=lambda: 0)
    commands = []
    def execute(command, **kwargs):
        commands.append(command)
        return stdin, stdout, io.BytesIO()
    assert touchscreen.run(NS(exec_command=execute), 'true', sudo=True, stream=False) == ('done\n', '', 0)
    assert password not in commands[0]
    assert stdin.getvalue() == password + '\n'


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


@pytest.mark.parametrize('state', ['ready', 'error', 'shutdown'])
def test_screen_startup_wait_preserves_repair_in_error_states(monkeypatch, state):
    import json
    ctx = deploy.Context(type('Args', (), {})())
    responses = iter(['startup', state])
    monkeypatch.setattr(ctx, 'moonraker', lambda path: json.dumps({'result': {'state': next(responses)}}))
    monkeypatch.setattr(deploy.time, 'sleep', lambda delay: None)
    monkeypatch.setattr(ctx, 'restart_klipper', lambda: pytest.fail('startup wait restarted controllers'))
    ctx.wait_for_backend()


def test_screen_startup_wait_stops_on_timeout_without_restart(monkeypatch):
    import json
    ctx = deploy.Context(type('Args', (), {})())
    monkeypatch.setattr(ctx, 'moonraker', lambda path: json.dumps({'result': {'state': 'startup'}}))
    with pytest.raises(deploy.DeployError, match='No additional controller restart'):
        ctx.wait_for_backend(timeout=0)


@pytest.mark.parametrize('state', ['error', 'shutdown'])
def test_repairs_do_not_require_a_preliminary_firmware_restart(monkeypatch, state):
    import json
    ctx = deploy.Context(type('Args', (), {})())
    def reply(path):
        if path.endswith('print_stats'):
            raise OSError('Klipper is not ready')
        return json.dumps({'result': {'state': state}})
    monkeypatch.setattr(ctx, 'moonraker', reply)
    assert ctx.printing_now() is False


@pytest.mark.parametrize('lose_guard', [False, True])
def test_final_controller_restart_requires_fresh_guard_verification(monkeypatch, lose_guard):
    from types import SimpleNamespace as NS
    from components import ORDER
    events = []
    def component(name):
        def install(ctx):
            events.append(name)
            if name == 'preload':
                events.append('activation guard check')
        def verify(ctx):
            events.append('final guard check')
            if lose_guard:
                raise deploy.DeployError('screen restarted without guard')
        return NS(NAME=name, RESTART_AFTER='klipper' if name in ('config', 'material') else None,
                  preflight=lambda ctx: None, install=install, status=lambda ctx: None,
                  verify_guard=verify)
    monkeypatch.setattr(deploy, 'REGISTRY', {name: component(name) for name in ORDER})
    monkeypatch.setattr(deploy, 'ORDER', ORDER)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'all'])
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: False)
    monkeypatch.setattr(deploy.Context, 'restart_klipper', lambda ctx: events.append('controller restart') or True)
    assert deploy.main() == int(lose_guard)
    assert events[:5] == ['config', 'material', 'preload', 'activation guard check', 'touchscreen']
    if lose_guard:
        assert events[-1] == 'final guard check' and 'controller restart' not in events
    else:
        assert events[-2:] == ['final guard check', 'controller restart']
