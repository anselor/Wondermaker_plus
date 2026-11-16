"""Concrete port contracts and payload planning without host service changes."""
import json
from pathlib import Path
import shutil
import pytest
from test_deploy import deploy
import touchscreen_runtime as runtime

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('load,active,enabled,expected',[
    ('loaded','active','enabled',{'active':True,'enabled':True}),
    ('loaded','inactive','disabled',{'active':False,'enabled':False}),
    ('not-found','inactive','',{'active':False,'enabled':False}),
    ('loaded','activating','enabled',None),('loaded','failed','enabled',None),
    ('masked','inactive','masked',None),('loaded','active','enabled-runtime',None)])
def test_service_state_is_explicit(monkeypatch,load,active,enabled,expected):
    ports=runtime.Ports()
    monkeypatch.setattr(ports,'command',lambda args:f'LoadState={load}\nActiveState={active}\nUnitFileState={enabled}\n')
    if expected is None:
        with pytest.raises(ValueError) as error: ports.state('wmp-screen.service')
        for key, value, allowed in [('LoadState', load, ('loaded',)),
                                    ('ActiveState', active, ('active', 'inactive')),
                                    ('UnitFileState', enabled, ('enabled', 'disabled'))]:
            assert (key + '=' in str(error.value)) == (value not in allowed)
    else:
        assert ports.state('wmp-screen.service')==expected


@pytest.mark.parametrize('action',['stop','disable'])
def test_absent_service_is_not_an_error(monkeypatch,action):
    ports=runtime.Ports();calls=[]
    monkeypatch.setattr(ports,'command',lambda args:calls.append(args) or 'LoadState=not-found\n')
    ports.services(action,'wmp-screen.service')
    assert len(calls)==1 and calls[0][1]=='show'


def test_plan_preserves_unrelated_files_and_existing_backup(tmp_path):
    root=tmp_path/'printer';site=root/'etc/nginx/sites-available/fluidd';site.parent.mkdir(parents=True)
    site.write_bytes(b'server {\n    listen 80;\n}\n');site.chmod(0o640)
    backup=root/'opt/wondermaker_plus/backup/fluidd.orig';backup.parent.mkdir(parents=True)
    backup.write_bytes(b'original vendor site')
    custom=backup.parent.parent/'operator.txt';custom.write_bytes(b'keep')
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    plan=runtime.file_plan(ROOT,root)
    assert {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}==before
    assert backup not in [p for p,_,_ in plan] and custom not in [p for p,_,_ in plan]
    updated,mode=next((data,mode) for p,data,mode in plan if p==site)
    assert mode==0o640 and updated.count(b'# wondermaker_plus')==1
    site.write_bytes(updated)
    assert site not in [p for p,_,_ in runtime.file_plan(ROOT,root)]


def test_plan_creates_original_nginx_backup_on_first_install(tmp_path):
    site=tmp_path/'etc/nginx/sites-available/fluidd';site.parent.mkdir(parents=True);site.write_bytes(b'server {\n}\n')
    plan=runtime.file_plan(ROOT,tmp_path)
    assert next(data for p,data,_ in plan if p.name=='fluidd.orig')==site.read_bytes()


@pytest.mark.parametrize('data',[b'not a server',b'server {\n include /other; # wondermaker_plus\n}\n'])
def test_ambiguous_nginx_edit_refuses(tmp_path,data):
    site=tmp_path/'etc/nginx/sites-available/fluidd';site.parent.mkdir(parents=True);site.write_bytes(data)
    with pytest.raises(ValueError):runtime.file_plan(ROOT,tmp_path)
    assert site.read_bytes()==data


@pytest.mark.parametrize('state',['prepared','installing','restoring','nonsense'])
def test_unresolved_journal_prevents_new_install(tmp_path,state):
    (tmp_path/'prior.json').write_text(json.dumps({'version':1,'state':state}))
    with pytest.raises(ValueError,match='Unresolved'):runtime.pending(tmp_path)


def test_completed_journals_allow_new_install(tmp_path):
    for state in ('applied','restored'):
        (tmp_path/(state+'.json')).write_text(json.dumps({'version':1,'state':state}))
    runtime.pending(tmp_path)


def test_request_uses_json_post_and_encoded_delete(monkeypatch):
    requests=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return b'{"result":{"ok":true}}'
    def urlopen(req,timeout):
        requests.append(req); assert timeout==10; return Response()
    monkeypatch.setattr(runtime,'urlopen',urlopen)
    ports=runtime.Ports()
    assert ports.request('POST','/machine/timelapse/settings',{'camera':'name with spaces'})=={'ok':True}
    assert json.loads(requests[-1].data)=={'camera':'name with spaces'}
    ports.request('DELETE','/server/webcams/item',{'uid':'a/b'})
    assert requests[-1].get_method()=='DELETE' and requests[-1].full_url.endswith('?uid=a%2Fb')


def interrupted_fixture(tmp_path):
    from test_touchscreen_transaction import fixture
    from types import SimpleNamespace
    tx, api, services, directory, before, cameras, states = fixture(tmp_path, False)
    tx.receipt['state'] = 'installing'
    tx.save()
    # Lost process after one published file, before camera/service completion.
    runtime.transaction.replace(tx.receipt['files'][0]['path'], tx.receipt['files'][0]['after'])
    ports = SimpleNamespace(services=services, request=api)
    return tx, ports, directory, before


def test_pending_reconciles_partial_owned_writes_then_new_install_undo(tmp_path):
    tx, ports, directory, before = interrupted_fixture(tmp_path)
    evidence=tx.path.read_bytes()
    runtime.pending(tmp_path, ports)
    assert tx.path.with_suffix('.retired').read_bytes()==evidence
    assert {p.name:runtime.transaction.snapshot(p) for p in directory.iterdir()}==before
    fresh=runtime.transaction.Transaction(tmp_path/'fresh.json',ports.services,ports.request)
    fresh.prepare([(directory/'screen.py',b'new screen',0o755)])
    fresh.install()
    fresh.restore()
    assert {p.name:runtime.transaction.snapshot(p) for p in directory.iterdir()}==before


def test_reconciliation_preserves_thirdparty_file_camera_and_selection(tmp_path):
    tx, ports, directory, _ = interrupted_fixture(tmp_path)
    (directory/'nginx').write_bytes(b'operator changed nginx')
    ports.request.cameras.append(dict(runtime.transaction.settings.SCREEN, uid='operator', source='database', target_fps=4))
    ports.request.selected='operator selected camera'
    cameras=__import__('copy').deepcopy(ports.request.cameras)
    runtime.pending(tmp_path,ports)
    assert (directory/'nginx').read_bytes()==b'operator changed nginx'
    assert ports.request.cameras==cameras
    assert ports.request.selected=='operator selected camera'
    plan=json.loads(tx.path.with_suffix('.reconcile').read_text())
    assert plan['state']=='restored'
    assert set(plan['preserved_operator_edits'])=={str(directory/'nginx'),'Touchscreen webcam','timelapse selection'}


@pytest.mark.parametrize('point', ['plan', 'undo', 'archive'])
def test_interrupted_reconciliation_resumes_same_plan_without_losing_evidence(tmp_path, monkeypatch, point):
    tx,ports,directory,before=interrupted_fixture(tmp_path)
    evidence=tx.path.read_bytes()
    atomic=runtime.transaction.atomic
    replace=runtime.transaction.replace
    rename=Path.rename
    fired=[]
    def fault_atomic(path,*args,**kwargs):
        result=atomic(path,*args,**kwargs)
        if point=='plan' and Path(path).suffix=='.reconcile' and not fired:
            fired.append(True); raise OSError('lost plan acknowledgement')
        return result
    def fault_replace(path,*args,**kwargs):
        result=replace(path,*args,**kwargs)
        if point=='undo' and not fired:
            fired.append(True); raise OSError('lost undo acknowledgement')
        return result
    def fault_rename(path,target):
        if point=='archive' and path==tx.path and not fired:
            fired.append(True); raise OSError('interrupted before archive')
        return rename(path,target)
    monkeypatch.setattr(runtime.transaction,'atomic',fault_atomic)
    monkeypatch.setattr(runtime.transaction,'replace',fault_replace)
    monkeypatch.setattr(Path,'rename',fault_rename)
    with pytest.raises(OSError):runtime.pending(tmp_path,ports)
    assert tx.path.read_bytes()==evidence
    runtime.pending(tmp_path,ports)
    assert tx.path.with_suffix('.retired').read_bytes()==evidence
    assert {p.name:runtime.transaction.snapshot(p) for p in directory.iterdir()}==before


def test_reconciliation_invalid_current_config_retains_original_and_plan(tmp_path):
    tx,ports,directory,_=interrupted_fixture(tmp_path)
    evidence=tx.path.read_bytes()
    (directory/'nginx').write_bytes(b'invalid custom configuration')
    ports.services.fail=('check','nginx')
    with pytest.raises(OSError):runtime.pending(tmp_path,ports)
    assert tx.path.read_bytes()==evidence and not tx.path.with_suffix('.retired').exists()
    assert (directory/'nginx').read_bytes()==b'invalid custom configuration'
