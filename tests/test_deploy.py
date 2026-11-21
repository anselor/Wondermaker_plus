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
    monkeypatch.setattr(deploy, 'create_install_journal', lambda ctx, components: None)


def historical_package(monkeypatch):
    """Exercise the installer path used when no current screen package exists."""
    import preload_bundle
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.BUNDLE)


def test_http_only_update_never_opens_ssh(monkeypatch):
    historical_package(monkeypatch)
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


def test_config_installs_required_helpers_with_backups_and_idempotence(tmp_path):
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
    for name in ('wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'):
        assert (extras / name).read_bytes() == (Path(config.ROOT) / 'klipper_extras' / name).read_bytes()
    backups = list(extras.glob('wmp_case_light.py.wmp-backup-*'))
    assert len(backups) == 1 and backups[0].read_bytes() == b'previous light helper'
    assert not list(extras.glob('*.wmp-upload-*'))
    assert len(renames) == 3
    config._install_extra(ctx)
    assert len(renames) == 3


def test_sudo_password_uses_stdin_without_shell_interpolation(monkeypatch):
    import io
    from types import SimpleNamespace as NS
    from components import touchscreen
    password = "test '$dollar; characters"
    monkeypatch.setattr(touchscreen, 'PASS', password)
    stdin, stdout = io.StringIO(), io.StringIO('done\n')
    stdin.channel = NS(shutdown_write=lambda: None)
    stdout.channel = NS(recv_exit_status=lambda: 0, exit_status_ready=lambda: True,
                        recv_ready=lambda: stdout.tell() < len(stdout.getvalue()),
                        recv=lambda size: stdout.read(size).encode(),
                        recv_stderr_ready=lambda: False)
    commands = []
    def execute(command, **kwargs):
        commands.append(command)
        return stdin, stdout, io.BytesIO()
    assert touchscreen.run(NS(exec_command=execute), 'true', sudo=True, stream=False) == ('done\n', '', 0)
    assert password not in commands[0]
    assert stdin.getvalue() == password + '\n'


@pytest.mark.parametrize('config_only', [False, True])
def test_install_order_restart_and_push_failure(monkeypatch, config_only):
    historical_package(monkeypatch)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config'] +
                        (['--config-only'] if config_only else []))
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda self: False)
    calls = []
    monkeypatch.setattr(config, '_install_extra', lambda ctx: calls.append('extra'))
    monkeypatch.setattr(config, '_sync', lambda args, env: calls.append(args) or 1)
    assert deploy.main() == 1
    assert calls == ([] if config_only else ['extra']) + [['push', '--yes', '--no-restart']]


def test_http_update_refused_during_print(monkeypatch):
    historical_package(monkeypatch)
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
        return SimpleNamespace(NAME=name, preflight=preflight, install=install, RESTART_AFTER=None,
                               verify_guard=lambda ctx: None)
    names = ['config', 'touchscreen', 'moonraker', 'preload']
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
    monkeypatch.setattr(ctx, 'backend_service_status', lambda: {'ActiveState': 'active', 'MainPID': '11'})
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
    historical_package(monkeypatch)
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


def test_backend_rollback_reverse_order_and_repeatable():
    from types import SimpleNamespace
    events = []
    ctx = SimpleNamespace(printing_now=lambda: False)
    rollback = deploy.BackendRollback(ctx)
    for name in ('config', 'material'):
        component = SimpleNamespace(NAME=name, rollback=lambda ctx, receipt: events.append(receipt))
        rollback.record(component, name)
    rollback()
    rollback()
    assert events == ['material', 'config']


def test_backend_rollback_stops_at_unconfirmed_dependency():
    from types import SimpleNamespace
    events = []
    ctx = SimpleNamespace(printing_now=lambda: False)
    rollback = deploy.BackendRollback(ctx)
    rollback.record(SimpleNamespace(NAME='config', rollback=lambda *a: events.append('unsafe')), 'config')
    def fail(*args):
        raise OSError('concurrent edit')
    rollback.record(SimpleNamespace(NAME='material', rollback=fail), 'material')
    with pytest.raises(OSError, match='concurrent edit'):
        rollback()
    assert not events and len(rollback.pending) == 2


@pytest.mark.parametrize('blocked,active,stopped', [(True, False, True), (False, True, False)])
def test_backend_rollback_refuses_unconfirmed_or_active_printer(blocked, active, stopped):
    from types import SimpleNamespace
    ctx = SimpleNamespace(printing_now=lambda: active)
    rollback = deploy.BackendRollback(ctx)
    rollback.blocked = blocked
    rollback.record(SimpleNamespace(NAME='material', rollback=lambda *a: pytest.fail('unsafe rollback')), [])
    with pytest.raises(deploy.DeployError):
        rollback(service_stopped=stopped)


def test_install_failure_calls_backend_rollback(monkeypatch):
    events = []
    components_for_test(monkeypatch, events, fail_install='preload')
    component = deploy.REGISTRY['config']
    component.install = lambda ctx: 'configuration receipt'
    component.rollback = lambda ctx, receipt: events.append(('restored', receipt))
    assert deploy.main() == 1
    assert events[-1] == ('restored', 'configuration receipt')


def test_legacy_config_without_receipt_prevents_helper_downgrade():
    from types import SimpleNamespace
    rollback = deploy.BackendRollback(SimpleNamespace(printing_now=lambda: False))
    rollback.record(SimpleNamespace(NAME='config'), None)
    rollback.record(SimpleNamespace(NAME='material', rollback=lambda *a: pytest.fail('unsafe downgrade')), [])
    with pytest.raises(deploy.DeployError, match='Legacy configuration'):
        rollback(service_stopped=True)


def test_successful_preload_does_not_restart_backend_twice(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    deploy.REGISTRY['config'].RESTART_AFTER = 'klipper'
    deploy.REGISTRY['preload'].RESTARTS_BACKEND = True
    monkeypatch.setattr(deploy.Context, 'restart_klipper', lambda ctx: pytest.fail('redundant restart'))
    assert deploy.main() == 0


@pytest.mark.parametrize('rollback_fails', [False, True])
@pytest.mark.parametrize('recovery_ready', [False, True])
def test_final_restart_failure_restores_backend_before_one_recovery_attempt(monkeypatch, rollback_fails, recovery_ready):
    events = []
    components_for_test(monkeypatch, events)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'config'])
    component = deploy.REGISTRY['config']
    component.install = lambda ctx: 'receipt'
    component.RESTART_AFTER = 'klipper'
    component.status = lambda ctx: None
    def rollback(ctx, receipt):
        events.append('restore')
        if rollback_fails:
            raise OSError('concurrent edit')
    component.rollback = rollback
    def restart(ctx):
        events.append('restart')
        return recovery_ready and events.count('restart') == 2
    monkeypatch.setattr(deploy.Context, 'restart_klipper', restart)
    assert deploy.main() == 1
    assert [e for e in events if isinstance(e, str)] == ['restart', 'restore'] + ([] if rollback_fails else ['restart'])


@pytest.mark.parametrize('fails',[False,True])
def test_explicit_touchscreen_recovery_uses_receipt_without_install(monkeypatch,fails):
    journal='/opt/wondermaker_plus-transactions/'+'a'*32+'.json'
    monkeypatch.setattr(sys,'argv',['deploy.py','recover','touchscreen','--journal',journal])
    monkeypatch.setattr(deploy.Context,'printing_now',lambda ctx:False)
    events=[]
    def rollback(ctx,receipt):
        events.append(receipt)
        if fails:raise OSError('concurrent edit')
    component=deploy.REGISTRY['touchscreen']
    monkeypatch.setattr(component,'rollback',rollback)
    monkeypatch.setattr(component,'install',lambda ctx:pytest.fail('recovery installed a candidate'))
    monkeypatch.setattr(component,'preflight',lambda ctx:pytest.fail('recovery used installation preflight'))
    monkeypatch.setattr(deploy.Context,'restart_klipper',lambda ctx:pytest.fail('recovery restarted Klipper'))
    assert deploy.main()==int(fails)
    assert events==[{'kind':'touchscreen-transaction','journal':journal}]


@pytest.mark.parametrize('args',[
    ['recover','all'], ['recover','config'], ['recover','touchscreen'],
    ['recover','touchscreen','--journal','/tmp/arbitrary.json'],
    ['status','touchscreen','--journal','unused'],
    ['recover','touchscreen','--journal','/opt/wondermaker_plus-transactions/'+'a'*32+'.json','--no-restart'],
])
def test_recovery_rejects_bad_arguments_before_contact(monkeypatch,args):
    monkeypatch.setattr(sys,'argv',['deploy.py',*args])
    monkeypatch.setattr(deploy.Context,'printing_now',lambda ctx:pytest.fail('invalid command contacted printer'))
    with pytest.raises(SystemExit) as error:deploy.main()
    assert error.value.code==2


def test_recovery_refuses_active_print(monkeypatch):
    monkeypatch.setattr(sys,'argv',['deploy.py','recover','touchscreen','--journal',
        '/opt/wondermaker_plus-transactions/'+'a'*32+'.json'])
    monkeypatch.setattr(deploy.Context,'printing_now',lambda ctx:True)
    monkeypatch.setattr(deploy.REGISTRY['touchscreen'],'rollback',lambda *a:pytest.fail('active print recovery'))
    with pytest.raises(SystemExit,match='print is in progress'):deploy.main()


def test_journal_failure_prevents_first_component_install(monkeypatch):
    events=[];components_for_test(monkeypatch,events)
    def fail(*args):raise OSError('journal disk unavailable')
    monkeypatch.setattr(deploy,'create_install_journal',fail)
    assert deploy.main()==1
    assert not any(event[0]=='install' for event in events)


def test_normal_install_checkpoints_all_components(tmp_path,monkeypatch):
    from install_journal import Journal
    events=[];components_for_test(monkeypatch,events)
    def create(ctx,components):
        journal=Journal(tmp_path/'install.json')
        journal.create('printer','user',[m.NAME for m in components]);return journal
    monkeypatch.setattr(deploy,'create_install_journal',create)
    for component in deploy.REGISTRY.values():
        original=component.install
        def install(ctx,original=original,name=component.NAME):
            saved=Journal(tmp_path/'install.json').load('printer','user')
            assert saved.value['inflight']==name
            return original(ctx)
        component.install=install
    assert deploy.main()==0
    saved=Journal(tmp_path/'install.json').load('printer','user')
    assert saved.value['state']=='applied'
    assert [row['component'] for row in saved.value['completed']]==deploy.ORDER


def test_process_loss_leaves_inflight_component_checkpoint(tmp_path,monkeypatch):
    from install_journal import Journal
    events=[];components_for_test(monkeypatch,events)
    def create(ctx,components):
        journal=Journal(tmp_path/'install.json')
        journal.create('printer','user',[m.NAME for m in components]);return journal
    monkeypatch.setattr(deploy,'create_install_journal',create)
    def interrupt(ctx):raise SystemExit('simulated process loss')
    deploy.REGISTRY['touchscreen'].install=interrupt
    with pytest.raises(SystemExit,match='process loss'):deploy.main()
    saved=Journal(tmp_path/'install.json').load('printer','user')
    assert saved.value['inflight']=='touchscreen'
    assert [row['component'] for row in saved.value['completed']]==['config']
    with pytest.raises(ValueError,match='unknown'):saved.recovery_receipts()


@pytest.mark.parametrize('locked',[False,True])
def test_all_recovery_cli_uses_saved_receipts_and_honors_lock(tmp_path,monkeypatch,locked):
    monkeypatch.setattr(deploy.Context, 'printer_machine_id', lambda self: '0123456789abcdef0123456789abcdef')
    from install_journal import Journal
    path=tmp_path/'install.json';journal=Journal(path)
    journal.create('printer','user',['config','material'])
    for name in ('config','material'):
        journal.begin(name);journal.complete_component(name,{'name':name})
    monkeypatch.setenv('WMP_PRINTER','printer');monkeypatch.setenv('WMP_USER','user')
    monkeypatch.setattr(sys,'argv',['deploy.py','recover','all','--journal',str(path)])
    monkeypatch.setattr(deploy.Context,'printing_now',lambda ctx:False)
    monkeypatch.setattr(deploy.Context,'restart_klipper',lambda ctx:pytest.fail('unexpected restart'))
    events=[]
    for name in ('config','material'):
        monkeypatch.setattr(deploy.REGISTRY[name],'rollback',lambda ctx,receipt:events.append(receipt['name']))
    if locked:journal.acquire()
    try:
        assert deploy.main()==int(locked)
        assert events==([] if locked else ['material','config'])
        assert Journal(path).load('printer','user',machine_id=None if locked else '0123456789abcdef0123456789abcdef').value['state']==('installing' if locked else 'restored')
    finally:journal.release()


def test_backend_rollback_rechecks_printer_between_components():
    from types import SimpleNamespace
    states=iter([False,True]);events=[]
    ctx=SimpleNamespace(printing_now=lambda:next(states))
    rollback=deploy.BackendRollback(ctx)
    for name in ('config','material'):
        component=SimpleNamespace(NAME=name,rollback=lambda ctx,receipt:events.append(receipt))
        rollback.record(component,name)
    with pytest.raises(deploy.DeployError,match='became active'):
        rollback()
    assert events==['material']
    assert [component.NAME for component,_ in rollback.pending]==['config']
    ctx.printing_now=lambda:False
    rollback()
    assert events==['material','config']
    assert not rollback.pending


def test_preload_install_adds_moonraker_dependency_before_activation(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'preload'])
    assert deploy.main() == 0
    assert events == [('check', 'config'), ('check', 'moonraker'), ('check', 'preload'),
                      ('install', 'config'), ('install', 'moonraker'), ('install', 'preload')]


def test_recover_all_reaches_receipt_recovery_without_http_precheck(tmp_path, monkeypatch):
    path = tmp_path / 'existing-journal.json'
    path.write_text('{}')
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'recover', 'all', '--journal', str(path)])
    def unavailable(ctx):
        pytest.fail('Outer HTTP gate would prevent recovery of stopped Moonraker')
    monkeypatch.setattr(deploy.Context, 'printing_now', unavailable)
    called = []
    monkeypatch.setattr(deploy, 'recover_installation', lambda ctx, value: called.append(value))
    assert deploy.main() == 0
    assert called == [str(path)]


@pytest.mark.parametrize('args', [['status', 'preload'], ['install', 'config'], ['uninstall', 'preload'], ['recover', 'all']])
def test_unreleased_qualification_is_restricted_to_screen_installation(monkeypatch, args):
    monkeypatch.setattr(sys, 'argv', ['deploy.py', *args, '--qualify-unreleased-screen'])
    with pytest.raises(SystemExit) as error:
        deploy.main()
    assert error.value.code == 2


def test_qualification_flag_reaches_preflight_and_install(monkeypatch):
    events = []
    components_for_test(monkeypatch, events)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'install', 'preload', '--qualify-unreleased-screen'])
    flags = []
    component = deploy.REGISTRY['preload']
    component.preflight = lambda ctx: flags.append(('preflight', ctx.qualify_unreleased_screen))
    component.install = lambda ctx: flags.append(('install', ctx.qualify_unreleased_screen))
    assert deploy.main() == 0
    assert flags == [('preflight', True), ('install', True)]


def test_observation_reconnect_discards_both_old_handles(monkeypatch):
    from types import SimpleNamespace as NS
    ctx = deploy.Context(NS())
    closed = []
    ctx._ssh = NS(close=lambda: closed.append('ssh'))
    ctx._sftp = NS(close=lambda: closed.append('sftp'))
    replacement = object()
    def connect():
        assert ctx._ssh is None and ctx._sftp is None
        ctx._ssh = replacement
        return replacement
    monkeypatch.setattr(ctx, 'ssh', connect)
    assert ctx.reconnect_ssh() is replacement
    assert closed == ['sftp', 'ssh']

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
        if path.startswith('/printer/objects/query'):
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
    assert events[:7] == ['config', 'material', 'moonraker', 'preload', 'activation guard check', 'touchscreen', 'shaper']
    if lose_guard:
        assert events[-1] == 'final guard check' and 'controller restart' not in events
    else:
        assert events[-2:] == ['final guard check', 'controller restart']


@pytest.mark.parametrize('active,pid,loaded,allowed', [
    ('inactive', '0', 'loaded', True), ('failed', '0', 'loaded', True),
    ('active', '10', 'loaded', False), ('inactive', '10', 'loaded', False),
    ('inactive', '0', 'not-found', False)])
def test_repair_http_offline_requires_stopped_service(monkeypatch, active, pid, loaded, allowed):
    ctx = deploy.Context(type('Args', (), {})())
    def offline(path): raise OSError('HTTP offline')
    monkeypatch.setattr(ctx, 'moonraker', offline)
    monkeypatch.setattr(ctx, 'backend_service_status', lambda: {
        'LoadState': loaded, 'ActiveState': active, 'MainPID': pid})
    if allowed: assert ctx.printing_now() is False
    else:
        with pytest.raises(deploy.DeployError, match='cannot establish'): ctx.printing_now()


def test_completed_preload_is_undone_before_earlier_helpers(tmp_path):
    from types import SimpleNamespace
    from install_journal import Journal
    events = []
    ctx = SimpleNamespace(printing_now=lambda: False)
    rollback = deploy.BackendRollback(ctx)
    journal = Journal(tmp_path / 'install.json')
    journal.create('printer', 'user', ['config', 'material', 'preload', 'touchscreen'])
    rollback.journal = journal
    for name in ('config', 'material', 'preload'):
        component = SimpleNamespace(NAME=name,
            rollback=lambda ctx, receipt: events.append(receipt['name']),
            finish_recovery=lambda ctx: events.append('restart restored'))
        receipt = {'name': name}
        journal.begin(name); journal.complete_component(name, receipt)
        rollback.record(component, receipt)
    journal.begin('touchscreen')
    rollback()
    rollback()
    assert events == ['preload', 'material', 'config', 'restart restored']
    assert journal.value['restored'] == ['preload', 'material', 'config']
    assert journal.value['inflight'] == 'touchscreen'
    assert not journal.value['recovery_restart_required']


def test_rollback_checks_all_handlers_before_first_undo():
    from types import SimpleNamespace
    events = []
    rollback = deploy.BackendRollback(SimpleNamespace(printing_now=lambda: False))
    rollback.record(SimpleNamespace(NAME='config'), {})
    rollback.record(SimpleNamespace(NAME='material', rollback=lambda *a: events.append('undo')), {})
    with pytest.raises(deploy.DeployError, match='component: config'): rollback()
    assert not events


@pytest.mark.parametrize('field,value', [('pause_resume', {'is_paused': True}),
                                        ('virtual_sdcard', {'is_active': True})])
def test_error_label_does_not_hide_current_print_activity(monkeypatch, field, value):
    import json
    ctx = deploy.Context(type('Args', (), {})())
    status = {'print_stats': {'state': 'error'}, field: value}
    monkeypatch.setattr(ctx, 'moonraker', lambda path: json.dumps({'result': {'status': status}}))
    assert ctx.printing_now()


def test_uninstall_orders_consumers_before_configuration_and_helpers(monkeypatch):
    from types import SimpleNamespace
    events = []
    names = ['config', 'material', 'moonraker', 'preload', 'touchscreen', 'shaper']
    registry = {name: SimpleNamespace(NAME=name, RESTART_AFTER=None,
        uninstall=lambda ctx, name=name: events.append(name)) for name in names}
    monkeypatch.setattr(deploy, 'ORDER', names)
    monkeypatch.setattr(deploy, 'REGISTRY', registry)
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: False)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'uninstall', 'all'])
    assert deploy.main() == 0
    assert events == ['touchscreen', 'shaper', 'config', 'material', 'preload', 'moonraker']


def test_uninstall_failure_retains_later_dependencies(monkeypatch):
    from types import SimpleNamespace
    events = []
    def failed(ctx):
        events.append('config')
        raise deploy.DeployError('configuration publication unconfirmed')
    registry = {
        'config': SimpleNamespace(NAME='config', RESTART_AFTER=None, uninstall=failed),
        'material': SimpleNamespace(NAME='material', RESTART_AFTER=None,
                                    uninstall=lambda ctx: events.append('removed helpers'))}
    monkeypatch.setattr(deploy, 'ORDER', ['config', 'material'])
    monkeypatch.setattr(deploy, 'REGISTRY', registry)
    monkeypatch.setattr(deploy.Context, 'printing_now', lambda ctx: False)
    monkeypatch.setattr(sys, 'argv', ['deploy.py', 'uninstall', 'all'])
    assert deploy.main() == 1
    assert events == ['config']


def test_legacy_rebind_cli_only_updates_local_identity(tmp_path, monkeypatch):
    from install_journal import Journal
    identity='0123456789abcdef0123456789abcdef'
    path=tmp_path/'legacy.json';Journal(path).create('previous-address','printer-user',['config'])
    monkeypatch.setenv('WMP_PRINTER','new-address')
    monkeypatch.setenv('WMP_USER','printer-user')
    monkeypatch.setattr(sys,'argv',['deploy.py','rebind-journal','all','--journal',str(path),
        '--from-host','previous-address','--confirm-machine-id',identity])
    monkeypatch.setattr(deploy.Context,'printer_machine_id',lambda self:identity)
    monkeypatch.setattr(deploy.Context,'printing_now',lambda self:pytest.fail('No printer operation admitted'))
    monkeypatch.setattr(deploy,'recover_installation',lambda *args:pytest.fail('Rebind must not recover'))
    assert deploy.main()==0
    assert Journal(path).load('new-address','printer-user',machine_id=identity).value['inflight'] is None
