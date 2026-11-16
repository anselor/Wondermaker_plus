"""Use the real restart function, not a fixture that raises in its place."""
import pytest
from test_deploy import deploy  # establish tools import path for isolated runs
from components import preload
class Context:
    DeployError=RuntimeError

def test_failed_restart_with_previous_client_still_active_is_not_success(monkeypatch):
    calls=[]
    def remote(_connection,command,**kwargs):
        calls.append(command)
        if 'daemon-reload' in command:return '', 'failed to restart: access denied', 1
        return 'active\n','',0
    monkeypatch.setattr(preload,'run',remote)
    with pytest.raises(RuntimeError,match='restart|access denied|failed'):
        preload._restart(Context(),object())
    assert calls and 'daemon-reload' in calls[0]


from test_preload_bundle import local_installer


def test_actual_restart_failure_rolls_back_published_files(tmp_path,monkeypatch,capsys):
    actual_restart=preload._restart
    replies = iter([{'state':'ready','process_id':1}, {'state':'ready','process_id':1},
                    {'state':'ready','process_id':2}, {'state':'ready','process_id':2}])
    monkeypatch.setattr(preload, '_printer_info', lambda ctx: next(replies))
    monkeypatch.setattr(preload.time, 'sleep', lambda seconds: None)
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    verified = []
    monkeypatch.setattr(preload, 'verify_stock_client', lambda context: verified.append('stock'))
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'previous owned library');drop.write_text('previous dropin')
    shell=preload.run;restart_calls=[];active_calls=[]
    def remote(connection,command,**kwargs):
        if 'systemctl daemon-reload' in command:
            restart_calls.append(command)
            if len(restart_calls)==1:return '', 'restart access denied',1
            assert old.read_bytes()==b'previous owned library' and drop.read_text()=='previous dropin'
            return '', '',0
        if command.startswith('systemctl start '):
            return '', '', 0
        if 'systemctl is-active' in command:
            active_calls.append(command);return 'active\n','',0
        return shell(connection,command,**kwargs)
    monkeypatch.setattr(preload,'run',remote);monkeypatch.setattr(preload,'_restart',actual_restart)
    with pytest.raises(ctx.DeployError,match='restart access denied'):preload.install(ctx)
    assert old.read_bytes()==b'previous owned library' and drop.read_text()=='previous dropin'
    assert len(restart_calls)==2 and len(active_calls)==2
    assert verified == ['stock']  # Restored override had no guard, so verify stock process.
    assert not (home/'lib/libwmp_wifi-fix.so').exists()
    assert 'Published verified' not in capsys.readouterr().out


@pytest.mark.parametrize('failed_target',['library','dropin'])
def test_uninstall_failed_removal_does_not_claim_success(tmp_path,monkeypatch,capsys,failed_target):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('override')
    shell=preload.run;failures=[]
    def remote(connection,command,**kwargs):
        target=str(old if failed_target=='library' else drop)
        if command.startswith('rm -f ') and target in command:
            failures.append(command);return '', 'removal denied',1
        return shell(connection,command,**kwargs)
    monkeypatch.setattr(preload,'run',remote)
    with pytest.raises(ctx.DeployError,match='removal denied'):preload.uninstall(ctx)
    assert failures and not restarts
    assert (old if failed_target=='library' else drop).exists()
    assert 'Removed the WM+' not in capsys.readouterr().out


def test_uninstall_removes_libraries_from_privileged_publication(tmp_path, monkeypatch):
    root, home, drop, selected, commands, restarts, ctx = local_installer(tmp_path, monkeypatch)
    library_dir = home / 'lib'
    library_dir.mkdir()
    for name, _ in selected:
        (library_dir / ('libwmp_%s.so' % name)).write_bytes(b'installed library')
    drop.write_text('installed override')
    config = home / 'saved_variables.cfg'
    config.write_text('operator settings')
    shell = preload.run

    def privileged_files(connection, command, **kwargs):
        # Fresh publication creates lib/ as root. Model that permission boundary
        # without needing root or changing ownership on the test host.
        if command.startswith('rm -f ') and not kwargs.get('sudo'):
            return '', 'Permission denied: root-owned preload directory', 1
        return shell(connection, command, **kwargs)

    monkeypatch.setattr(preload, 'run', privileged_files)
    preload.uninstall(ctx)
    assert not list(library_dir.glob('libwmp_*.so'))
    assert not drop.exists()
    assert config.read_text() == 'operator settings'
    assert restarts == [True]


@pytest.mark.parametrize('active_rc',[0,1])
def test_successful_restart_still_requires_final_active_check(monkeypatch,active_rc):
    verified = []
    monkeypatch.setattr(preload, 'verify_guard', lambda context: verified.append('guard'))
    replies = iter([{'state':'ready','process_id':1}, {'state':'ready','process_id':2},
                    {'state':'ready','process_id':2}])
    monkeypatch.setattr(preload, '_printer_info', lambda ctx: next(replies))
    monkeypatch.setattr(preload.time, 'sleep', lambda seconds: None)
    calls=[]
    def remote(connection,command,**kwargs):
        calls.append(command)
        if 'daemon-reload' in command or command.startswith('systemctl start '):return '', '',0
        return ('active\n' if not active_rc else 'failed\n'),'service unavailable',active_rc
    monkeypatch.setattr(preload,'run',remote)
    if active_rc:
        with pytest.raises(RuntimeError,match='failed during startup'):preload._restart(Context(),object())
    else:preload._restart(Context(),object())
    assert len(calls)==(4 if active_rc else 5) and 'is-active' in calls[3]
    assert calls[1] == 'systemctl restart klipper.service'
    assert verified == ['guard']


def test_uninstall_actual_restart_failure_never_claims_completion(tmp_path,monkeypatch,capsys):
    actual_restart=preload._restart
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('override')
    shell=preload.run
    def remote(connection,command,**kwargs):
        if 'daemon-reload' in command:return '', 'restart unavailable',1
        if 'is-active' in command:raise AssertionError('failed restart must not use old active process')
        return shell(connection,command,**kwargs)
    monkeypatch.setattr(preload,'run',remote);monkeypatch.setattr(preload,'_restart',actual_restart)
    with pytest.raises(ctx.DeployError,match='restart unavailable'):preload.uninstall(ctx)
    assert not old.exists() and not drop.exists()
    assert 'Removed the WM+' not in capsys.readouterr().out
