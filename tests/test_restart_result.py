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


def published_for_removal(tmp_path, monkeypatch):
    """Create a real publication receipt, not an unowned arbitrary override."""
    import json
    import preload_bundle as pb
    result = local_installer(tmp_path, monkeypatch)
    root, home, drop, selected, commands, restarts, ctx = result
    stage = home/'removal-fixture'; stage.mkdir()
    outputs = {}
    for name, _ in selected:
        filename = 'libwmp_%s.so' % name
        (stage/filename).write_bytes(b'installed library')
        outputs[filename] = {'file':filename, 'sha256':pb.digest(stage/filename)}
    (stage/'outputs.json').write_text(json.dumps(outputs))
    pb.publish_stage(stage, home/'lib', drop)
    monkeypatch.setattr(preload, 'DEFAULTS_DROPIN', str(home/'defaults.conf'))
    return result


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
    root,home,drop,selected,commands,restarts,ctx=published_for_removal(tmp_path,monkeypatch)
    old=home/'lib/libwmp_openace-compat.so'
    target=old if failed_target=='library' else drop
    helper=preload._helper; failures=[]
    def denied(context,connection,body,**kwargs):
        if 'restore_preload_factory(' in body:
            failures.append(True)
            body = ("original_unlink=Path.unlink\n"
                    "def deny_unlink(path,*args,**kwargs):\n"
                    "    if str(path)==%r: raise PermissionError('removal denied')\n"
                    "    return original_unlink(path,*args,**kwargs)\n"
                    "Path.unlink=deny_unlink\n" % str(target)) + body
        return helper(context,connection,body,**kwargs)
    monkeypatch.setattr(preload,'_helper',denied)
    with pytest.raises(ctx.DeployError,match='removal denied'):preload.uninstall(ctx)
    assert failures and not restarts and target.exists()
    assert 'Restored original screen resources' not in capsys.readouterr().out


def test_uninstall_removes_libraries_from_privileged_publication(tmp_path, monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=published_for_removal(tmp_path,monkeypatch)
    library_dir=home/'lib'
    config=home/'saved_variables.cfg'; config.write_text('operator settings')
    shell=preload.run; restores=[]
    def privileged_files(connection, command, **kwargs):
        if 'restore_preload_factory(' in command:
            restores.append(kwargs.get('sudo'))
            if not kwargs.get('sudo'):
                return '', 'Permission denied: root-owned preload directory', 1
        return shell(connection, command, **kwargs)
    monkeypatch.setattr(preload,'run',privileged_files)
    preload.uninstall(ctx)
    assert restores == [True]
    assert not list(library_dir.glob('libwmp_*.so')) and not drop.exists()
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
    root,home,drop,selected,commands,restarts,ctx=published_for_removal(tmp_path,monkeypatch)
    old=home/'lib/libwmp_openace-compat.so'
    shell=preload.run
    def remote(connection,command,**kwargs):
        if 'daemon-reload' in command:return '', 'restart unavailable',1
        if 'is-active' in command:raise AssertionError('failed restart must not use old active process')
        return shell(connection,command,**kwargs)
    monkeypatch.setattr(preload,'run',remote);monkeypatch.setattr(preload,'_restart',actual_restart)
    with pytest.raises(ctx.DeployError,match='restart unavailable'):preload.uninstall(ctx)
    assert not old.exists() and not drop.exists()
    assert 'Restored original screen resources' not in capsys.readouterr().out
