"""Durable installer receipts, explicit ambiguity, and deterministic recovery."""
import json
import os
import stat
import pytest
from test_deploy import deploy
from install_journal import Journal, encode, decode


def test_binary_receipts_roundtrip_without_executable_serialization(tmp_path):
    path=tmp_path/'install.json';journal=Journal(path)
    journal.create('printer.example','printer',['config','material'])
    receipt={'kind':'config','helpers':[('/home/printer/helper',None,b'old\x00\xff',b'new')],
             'plan':{'changes':[]}}
    journal.begin('config');journal.complete_component('config',receipt)
    journal.begin('material');journal.complete_component('material',[])
    loaded=Journal(path).load('printer.example','printer')
    receipts=loaded.recovery_receipts()
    assert receipts[0]==('material',[])
    assert receipts[1][1]['helpers']==[['/home/printer/helper',None,b'old\x00\xff',b'new']]
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    loaded.restored_component('material')
    loaded=Journal(path).load('printer.example','printer')
    assert len(loaded.recovery_receipts())==1
    loaded.restored_component('config');loaded.finish(recovered=True)
    assert Journal(path).load('printer.example','printer').value['state']=='restored'


def test_interruption_during_component_is_not_guessed_complete(tmp_path):
    path=tmp_path/'install.json';journal=Journal(path)
    journal.create('printer','user',['config','touchscreen'])
    journal.begin('config');journal.complete_component('config',{'backup':'saved'})
    journal.begin('touchscreen')
    recovered=Journal(path).load('printer','user')
    with pytest.raises(ValueError,match='outcome is unknown: touchscreen'):
        recovered.recovery_receipts()
    assert recovered.value['completed'][0]['component']=='config'


@pytest.mark.parametrize('host,user',[('other','user'),('printer','other')])
def test_receipt_cannot_be_replayed_against_another_printer(tmp_path,host,user):
    path=tmp_path/'install.json';Journal(path).create('printer','user',['config'])
    with pytest.raises(ValueError,match='different printer') as error:
        Journal(path).load(host,user)
    assert ('mismatched host' if host == 'other' else 'mismatched user') in str(error.value)


def test_torn_or_modified_receipt_is_rejected(tmp_path):
    path=tmp_path/'install.json';Journal(path).create('printer','user',['config'])
    value=json.loads(path.read_text());value['record']['inflight']='material'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='integrity mismatch'):Journal(path).load('printer','user')


def test_failed_atomic_replace_retains_previous_checkpoint(tmp_path,monkeypatch):
    path=tmp_path/'install.json';journal=Journal(path)
    journal.create('printer','user',['config'])
    def fail(*args):raise OSError('disk unavailable')
    monkeypatch.setattr(os,'replace',fail)
    with pytest.raises(OSError):journal.begin('config')
    loaded=Journal(path).load('printer','user')
    assert loaded.value['inflight'] is None and not loaded.value['completed']
    assert not list(tmp_path.glob('.wmp-journal-*'))


def test_unfinished_install_cannot_be_marked_applied(tmp_path):
    journal=Journal(tmp_path/'install.json');journal.create('printer','user',['config','material'])
    journal.begin('config');journal.complete_component('config',None)
    with pytest.raises(ValueError,match='incomplete'):journal.finish()
    journal.begin('material');journal.complete_component('material',[]);journal.finish()
    with pytest.raises(ValueError,match='not eligible'):journal.recovery_receipts()


def test_wrong_order_does_not_advance_journal(tmp_path):
    journal=Journal(tmp_path/'install.json');journal.create('printer','user',['config','material'])
    with pytest.raises(ValueError):journal.begin('material')
    journal.begin('config')
    with pytest.raises(ValueError):journal.complete_component('material',[])
    journal.complete_component('config',{})
    journal.begin('material');journal.complete_component('material',[])
    with pytest.raises(ValueError):journal.restored_component('config')
    assert not journal.value['restored']


@pytest.mark.parametrize('value',[{'type':'bytes','data':'!invalid'}, {'type':'eval','data':'__import__("os")'},
    {'type':'value','data':1.5}, {'type':'value','data':'x','extra':True}])
def test_bad_encoded_values_are_not_interpreted(value):
    with pytest.raises(ValueError):decode(value)


def test_recovery_lock_excludes_another_process_and_releases(tmp_path):
    import subprocess
    import sys
    path = tmp_path/'install.json'
    journal = Journal(path)
    journal.acquire()
    script = ('from install_journal import Journal; import sys; '
              'j=Journal(sys.argv[1]); j.acquire(); j.release()')
    env = dict(os.environ, PYTHONPATH=str(deploy.Path(deploy.__file__).parent))
    blocked = subprocess.run([sys.executable, '-c', script, str(path)],
                             env=env, capture_output=True, text=True)
    assert blocked.returncode != 0 and 'locked by another process' in blocked.stderr
    journal.release()
    allowed = subprocess.run([sys.executable, '-c', script, str(path)],
                             env=env, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stderr


def test_recovery_lock_refuses_symlink(tmp_path):
    target = tmp_path/'target';target.write_text('untouched')
    (tmp_path/'install.json.lock').symlink_to(target)
    with pytest.raises(OSError):Journal(tmp_path/'install.json').acquire()
    assert target.read_text() == 'untouched'


def recovery_fixture(tmp_path, monkeypatch, names=('config','touchscreen','material')):
    from types import SimpleNamespace
    journal = Journal(tmp_path/'install.json')
    journal.create('printer','user',list(names))
    for name in names:
        journal.begin(name);journal.complete_component(name,{'component':name})
    events=[]
    for name in names:
        monkeypatch.setattr(deploy.REGISTRY[name], 'rollback',
                            lambda ctx, receipt: events.append(receipt['component']))
    ctx=SimpleNamespace(host='printer',user='user',printing_now=lambda:False)
    return journal,ctx,events


def test_recover_completed_components_in_reverse_order(tmp_path,monkeypatch):
    journal,ctx,events=recovery_fixture(tmp_path,monkeypatch)
    deploy.recover_installation(ctx,journal.path)
    assert events==['material','touchscreen','config']
    assert Journal(journal.path).load('printer','user').value['state']=='restored'


@pytest.mark.parametrize('reason',['inflight','unsupported','wrong_printer'])
def test_recovery_refuses_before_any_mutation(tmp_path,monkeypatch,reason):
    journal,ctx,events=recovery_fixture(tmp_path,monkeypatch)
    if reason=='inflight':journal.value['inflight']='preload'
    elif reason=='unsupported':journal.value['completed'][0]['receipt']=encode(None)
    else:ctx.host='other'
    journal.save()
    with pytest.raises((ValueError,deploy.DeployError)):
        deploy.recover_installation(ctx,journal.path)
    assert not events


def test_recovery_checkpoints_and_resumes_after_printer_becomes_active(tmp_path,monkeypatch):
    journal,ctx,events=recovery_fixture(tmp_path,monkeypatch)
    states=iter([False,True]);ctx.printing_now=lambda:next(states)
    with pytest.raises(deploy.DeployError,match='became active'):
        deploy.recover_installation(ctx,journal.path)
    assert events==['material']
    assert Journal(journal.path).load('printer','user').value['restored']==['material']
    ctx.printing_now=lambda:False
    deploy.recover_installation(ctx,journal.path)
    assert events==['material','touchscreen','config']


def test_prepared_material_is_restored_before_completed_dependencies(tmp_path,monkeypatch):
    journal,ctx,events=recovery_fixture(tmp_path,monkeypatch,names=('config',))
    journal.value['components'].append('material');journal.save()
    journal.begin('material');journal.prepare_component('material',[])
    monkeypatch.setattr(deploy.REGISTRY['material'],'rollback',lambda ctx,receipt:events.append('material'))
    deploy.recover_installation(ctx,journal.path)
    assert events==['material','config']
    assert Journal(journal.path).load('printer','user').value['inflight'] is None


def test_material_completion_replaces_prepared_plan(tmp_path):
    journal=Journal(tmp_path/'install.json');journal.create('printer','user',['material'])
    journal.begin('material');journal.prepare_component('material',[])
    journal.complete_component('material',[])
    saved=Journal(journal.path).load('printer','user')
    assert 'prepared_receipt' not in saved.value
    assert saved.recovery_receipts()==[('material',[])]


def test_missing_remote_touchscreen_journal_preserves_earlier_components(tmp_path,monkeypatch):
    journal,ctx,events=recovery_fixture(tmp_path,monkeypatch,names=('config',))
    journal.value['components'].append('touchscreen');journal.save()
    journal.begin('touchscreen')
    journal.prepare_component('touchscreen',{'kind':'touchscreen-transaction',
        'journal':'/opt/wondermaker_plus-transactions/'+'a'*32+'.json'})
    def missing(*args):raise FileNotFoundError('remote journal absent')
    monkeypatch.setattr(deploy.REGISTRY['touchscreen'],'rollback',missing)
    with pytest.raises(FileNotFoundError):deploy.recover_installation(ctx,journal.path)
    assert events==[]
    saved=Journal(journal.path).load('printer','user')
    assert saved.value['inflight']=='touchscreen' and not saved.value['restored']


def test_interrupted_moonraker_recovers_http_before_earlier_components(tmp_path, monkeypatch):
    journal, ctx, events = recovery_fixture(tmp_path, monkeypatch, names=('config',))
    journal.value['components'].append('moonraker'); journal.save()
    journal.begin('moonraker')
    receipt = {'kind': 'moonraker-directory', 'state': '/home/user/wmp/backups/moonraker-directory-managed', 'before': 'original'}
    journal.prepare_component('moonraker', receipt)
    def idle():
        if 'moonraker' not in events:
            raise deploy.DeployError('HTTP stopped by interrupted installation')
        return False
    ctx.printing_now = idle
    monkeypatch.setattr(deploy.REGISTRY['moonraker'], 'rollback', lambda ctx, value: events.append('moonraker'))
    deploy.recover_installation(ctx, journal.path)
    assert events == ['moonraker', 'config']
    assert Journal(journal.path).load('printer', 'user').value['state'] == 'restored'


def test_failed_moonraker_recovery_preserves_earlier_components(tmp_path, monkeypatch):
    journal, ctx, events = recovery_fixture(tmp_path, monkeypatch, names=('config', 'moonraker'))
    def failed(*args):
        raise deploy.DeployError('remote operation still owns lock')
    monkeypatch.setattr(deploy.REGISTRY['moonraker'], 'rollback', failed)
    with pytest.raises(deploy.DeployError, match='still owns lock'):
        deploy.recover_installation(ctx, journal.path)
    assert events == []
    assert Journal(journal.path).load('printer', 'user').value['restored'] == []


def test_moonraker_only_recovery_does_not_request_unnecessary_backend_restart(tmp_path, monkeypatch, capsys):
    journal, ctx, events = recovery_fixture(tmp_path, monkeypatch, names=('moonraker',))
    deploy.recover_installation(ctx, journal.path)
    output = capsys.readouterr().out
    assert 'Moonraker recovered and Ready verified; Klipper was not restarted.' in output
    assert 'must still be verified' not in output


@pytest.mark.parametrize('fault', ['version', 'missing', 'duplicate', 'before', 'extra'])
def test_combined_moonraker_undo_plan_rejects_malformed_receipts(tmp_path, fault):
    journal = Journal(tmp_path/'install.json')
    journal.create('printer', 'user', ['moonraker'])
    journal.begin('moonraker')
    receipt = {'kind': 'moonraker-patches', 'version': 1, 'patches': [
        {'patch': patch, 'state': '/home/user/wmp/backups/moonraker-' + patch + '-managed',
         'before': 'original'} for patch in ('directory', 'http-error')]}
    if fault == 'version':
        receipt['version'] = True
    elif fault == 'missing':
        receipt['patches'].pop()
    elif fault == 'duplicate':
        receipt['patches'][1] = receipt['patches'][0].copy()
    elif fault == 'before':
        receipt['patches'][1]['before'] = 'unknown'
    else:
        receipt['patches'][1]['script'] = 'untrusted'
    before = journal.path.read_bytes()
    with pytest.raises(ValueError, match='Unsupported prepared'):
        journal.prepare_component('moonraker', receipt)
    assert journal.path.read_bytes() == before


def test_windows_journal_lock_and_atomic_checkpoint(tmp_path, monkeypatch):
    import sys
    import types
    import install_journal
    locks = []
    monkeypatch.setattr(install_journal, 'WINDOWS', True)
    monkeypatch.setitem(sys.modules, 'msvcrt', types.SimpleNamespace(
        LK_NBLCK=2, locking=lambda fd, mode, count: locks.append((fd, mode, count))))
    def unix_only(*args):
        raise AssertionError('Unix-only filesystem operation')
    monkeypatch.setattr(os, 'fchmod', unix_only)
    journal = Journal(tmp_path/'install.json')
    journal.acquire()
    try:
        assert locks == [(journal._lock_fd, 2, 1)]
        journal.create('printer', 'user', ['material'])
        journal.begin('material')
        journal.complete_component('material', [b'old', b'new'])
        assert Journal(journal.path).load('printer', 'user').recovery_receipts() == [
            ('material', [b'old', b'new'])]
    finally:
        journal.release()


def test_windows_lock_failure_closes_descriptor(tmp_path, monkeypatch):
    import sys
    import types
    import install_journal
    failed = []
    def busy(fd, mode, count):
        failed.append(fd)
        raise OSError('locked')
    monkeypatch.setattr(install_journal, 'WINDOWS', True)
    monkeypatch.setitem(sys.modules, 'msvcrt', types.SimpleNamespace(LK_NBLCK=2, locking=busy))
    journal = Journal(tmp_path/'install.json')
    with pytest.raises(ValueError, match='locked by another process'):
        journal.acquire()
    assert journal._lock_fd is None
    with pytest.raises(OSError):
        os.fstat(failed[0])


def test_completed_undo_order_includes_preload_before_its_backend_dependencies(tmp_path):
    journal = Journal(tmp_path/'undo.json')
    journal.create('printer', 'user', ['config','material','preload','touchscreen'])
    for name in ('config','material','preload'):
        journal.begin(name)
        journal.complete_component(name, {'test': name})
    journal.begin('touchscreen')
    assert [name for name, _ in journal.completed_recovery_receipts()] == ['preload','material','config']
    before = journal.path.read_bytes()
    with pytest.raises(ValueError, match='Unexpected recovery order'):
        journal.restored_component('material', retain_inflight=True)
    assert journal.path.read_bytes() == before
    journal.restored_component('preload', retain_inflight=True)
    loaded = Journal(journal.path).load('printer','user')
    assert [name for name, _ in loaded.completed_recovery_receipts()] == ['material','config']
    assert loaded.value['inflight'] == 'touchscreen'


MACHINE_ID = '0123456789abcdef0123456789abcdef'
OTHER_MACHINE_ID = 'fedcba9876543210fedcba9876543210'


def test_same_machine_new_address_loads_without_weakening_user_binding(tmp_path):
    path=tmp_path/'install.json'
    Journal(path).create('old-address','user',['config'], machine_id=MACHINE_ID)
    before=path.read_bytes()
    loaded=Journal(path).load('new-address','user',machine_id=MACHINE_ID)
    assert loaded.value['host']=='old-address'
    assert path.read_bytes()==before
    for identity,user in [(OTHER_MACHINE_ID,'user'),(None,'user'),(MACHINE_ID,'other-user')]:
        with pytest.raises(ValueError):Journal(path).load('old-address',user,machine_id=identity)
        assert path.read_bytes()==before


def test_legacy_same_host_can_acquire_verified_identity(tmp_path):
    path=tmp_path/'install.json';Journal(path).create('printer','user',['config'])
    Journal(path).load('printer','user',machine_id=MACHINE_ID)
    assert Journal(path).load('new-address','user',machine_id=MACHINE_ID).value['machine_id']==MACHINE_ID


def test_explicit_legacy_rebind_only_changes_local_binding(tmp_path):
    from types import SimpleNamespace
    path=tmp_path/'install.json';Journal(path).create('old-address','user',['config'])
    old=json.loads(path.read_text())['record']
    ctx=SimpleNamespace(host='new-address',user='user',printer_machine_id=lambda:MACHINE_ID)
    deploy.rebind_install_journal(ctx,path,'old-address',MACHINE_ID)
    record=Journal(path).load('new-address','user',machine_id=MACHINE_ID).value
    assert record['binding_history']==[{'host':'old-address','user':'user','machine_id':None}]
    assert record['host']=='new-address'
    assert {key:record[key] for key in old if key!='host'}=={key:old[key] for key in old if key!='host'}


@pytest.mark.parametrize('old_host,user,confirmed,bound',[
    ('incorrect','user',MACHINE_ID,None),('old','other-user',MACHINE_ID,None),
    ('old','user',OTHER_MACHINE_ID,None),('old','user',MACHINE_ID,OTHER_MACHINE_ID)])
def test_rebind_refusal_never_changes_receipts(tmp_path,old_host,user,confirmed,bound):
    path=tmp_path/'install.json';Journal(path).create('old','user',['config'],machine_id=bound)
    before=path.read_bytes()
    with pytest.raises(ValueError):Journal(path).rebind('new',user,MACHINE_ID,old_host,confirmed)
    assert path.read_bytes()==before


def test_wrong_machine_recovery_never_invokes_component_undo(tmp_path, monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'install.json';journal=Journal(path)
    journal.create('printer','user',['config'],machine_id=MACHINE_ID)
    journal.begin('config');journal.complete_component('config',{})
    before=path.read_bytes()
    ctx=SimpleNamespace(host='printer',user='user',printer_machine_id=lambda:OTHER_MACHINE_ID)
    monkeypatch.setattr(deploy.REGISTRY['config'],'rollback',lambda *args:pytest.fail('wrong-device undo'))
    with pytest.raises(ValueError,match='machine-id mismatch'):deploy.recover_installation(ctx,path)
    assert path.read_bytes()==before


def test_context_machine_identity_is_independent_read_only_ssh(monkeypatch):
    from types import SimpleNamespace
    from components import touchscreen
    ctx=deploy.Context(SimpleNamespace())
    monkeypatch.setattr(ctx,'ssh',lambda:object())
    calls=[]
    def read(connection,command,**kwargs):
        calls.append(command)
        return MACHINE_ID+'\n','',0
    monkeypatch.setattr(touchscreen,'run',read)
    assert ctx.printer_machine_id()==MACHINE_ID
    assert calls==['cat /etc/machine-id']
