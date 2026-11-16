"""Real file/journal writes with modeled systemd, nginx and Moonraker ports."""
import copy
import json
from pathlib import Path
import pytest
from test_deploy import deploy
from test_touchscreen_settings import API
import touchscreen_transaction as tx


class Services:
    def __init__(self, existing=False):
        self.states = {tx.SCREEN: dict(active=existing, enabled=existing),
                       tx.FIXER: dict(active=False, enabled=existing)}
        self.events = []
        self.fail = None

    def __call__(self, action, unit):
        self.events.append((action, unit))
        if action == 'state':
            return copy.deepcopy(self.states[unit])
        if action in ('stop', 'start'):
            self.states[unit]['active'] = action == 'start'
        if action in ('enable', 'disable'):
            self.states[unit]['enabled'] = action == 'enable'
        if (action, unit) == self.fail:
            self.fail = None
            raise OSError('injected service failure after action')


def fixture(tmp_path, existing):
    api, services = API(existing), Services(existing)
    directory = tmp_path/'files'; directory.mkdir()
    old = directory/'nginx'; old.write_bytes(b'previous nginx'); old.chmod(0o640)
    new = directory/'screen.py'
    if existing:
        new.write_bytes(b'previous screen'); new.chmod(0o755)
    before = {p.name: tx.snapshot(p) for p in directory.iterdir()}
    cameras = copy.deepcopy(api.cameras), api.selected
    states = copy.deepcopy(services.states)
    transaction = tx.Transaction(tmp_path/'journal.json', services, api)
    transaction.prepare([(old,b'candidate nginx',0o644),(new,b'candidate screen',0o755)])
    return transaction, api, services, directory, before, cameras, states


@pytest.mark.parametrize('existing',[False,True])
def test_install_then_reload_journal_and_restore_everything(tmp_path,existing):
    transaction,api,services,directory,before,cameras,states=fixture(tmp_path,existing)
    transaction.install()
    assert json.loads(transaction.path.read_text())['state']=='applied'
    recovered=tx.Transaction(transaction.path,services,api)
    recovered.restore()
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before
    assert (api.cameras,api.selected)==cameras and services.states==states
    assert json.loads(transaction.path.read_text())['state']=='restored'


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('failure', [('stop',tx.FIXER),('stop',tx.SCREEN),('check','nginx'),
    ('reload','daemon'),('enable',tx.SCREEN),('enable',tx.FIXER),('start',tx.SCREEN),
    ('reload','nginx'),('check','screen-http')])
def test_each_service_failure_restores_prior_install(tmp_path,existing,failure):
    transaction,api,services,directory,before,cameras,states=fixture(tmp_path,existing)
    services.fail=failure
    with pytest.raises(OSError,match='injected service failure'):
        transaction.install()
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before
    assert (api.cameras,api.selected)==cameras and services.states==states
    assert json.loads(transaction.path.read_text())['state']=='restored'


@pytest.mark.parametrize('path',['/server/webcams/item','/machine/timelapse/settings'])
def test_api_lost_response_recovers_files_services_and_settings(tmp_path,path):
    transaction,api,services,directory,before,cameras,states=fixture(tmp_path,True)
    api.fail=('POST',path)
    with pytest.raises(OSError,match='lost response'):
        transaction.install()
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before
    assert (api.cameras,api.selected)==cameras and services.states==states


def test_operator_file_edit_refuses_before_service_or_api_changes(tmp_path):
    transaction,api,services,directory,*_=fixture(tmp_path,True)
    transaction.install()
    (directory/'screen.py').write_bytes(b'operator update')
    services.events.clear(); api.writes.clear()
    with pytest.raises(ValueError,match='Concurrent'):
        transaction.restore()
    assert (directory/'screen.py').read_bytes()==b'operator update'
    assert not services.events and not api.writes


def test_process_loss_mid_file_publication_recovers_from_disk(tmp_path,monkeypatch):
    transaction,api,services,directory,before,cameras,states=fixture(tmp_path,True)
    replace=tx.replace
    def crash(path,data):
        replace(path,data)
        raise SystemExit('process lost')
    monkeypatch.setattr(tx,'replace',crash)
    with pytest.raises(SystemExit):
        transaction.install()
    monkeypatch.setattr(tx,'replace',replace)
    tx.Transaction(transaction.path,services,api).restore()
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before
    assert (api.cameras,api.selected)==cameras and services.states==states


def test_later_service_edit_is_not_overwritten(tmp_path):
    transaction,api,services,*_=fixture(tmp_path,False)
    transaction.install()
    services.states[tx.SCREEN]['enabled']=False
    api.writes.clear(); services.events.clear()
    with pytest.raises(ValueError,match='service changed after installation'):
        transaction.restore()
    assert not services.states[tx.SCREEN]['enabled']
    assert services.states[tx.SCREEN]['active']
    assert not api.writes and all(action=='state' for action,_ in services.events)


def test_active_camera_fixer_stopped_for_install_and_restored_on_undo(tmp_path):
    api,services=API(),Services()
    services.states[tx.FIXER]['active']=True
    before=copy.deepcopy(services.states)
    transaction=tx.Transaction(tmp_path/'receipt.json',services,api)
    transaction.prepare([])
    assert not api.writes
    transaction.install()
    assert services.events.index(('stop',tx.FIXER)) < services.events.index(('start',tx.SCREEN))
    transaction.restore()
    assert services.states == before


@pytest.mark.parametrize('unavailable', [False, True])
def test_bridge_without_timelapse_preserves_or_disables_fixer_as_reviewed(tmp_path, unavailable):
    api,services=API(),Services(True)
    api.cameras=[]
    def request(method,path,data):
        if method=='GET' and path=='/machine/timelapse/settings':
            if unavailable: raise OSError('timelapse unavailable')
            return {'enabled':False,'camera':api.selected}
        return api(method,path,data)
    before=copy.deepcopy(services.states)
    transaction=tx.Transaction(tmp_path/'receipt.json',services,request)
    transaction.prepare([])
    transaction.install()
    assert services.states[tx.SCREEN] == {'active':True,'enabled':True}
    assert services.states[tx.FIXER]['enabled'] == unavailable
    assert not any(path=='/machine/timelapse/settings' for _,path,_ in api.writes)
    transaction.restore()
    assert services.states == before


def test_operator_change_during_failed_install_retains_unresolved_journal(tmp_path):
    transaction,api,services,directory,*_=fixture(tmp_path,True)
    service=services.__call__
    def edit_then_fail(action,unit):
        result=service(action,unit)
        if (action,unit)==('check','screen-http'):
            (directory/'screen.py').write_bytes(b'operator data')
            raise OSError('health check failed')
        return result
    transaction.services=edit_then_fail
    with pytest.raises(RuntimeError,match='recovery unconfirmed'):
        transaction.install()
    assert (directory/'screen.py').read_bytes()==b'operator data'
    # Conflict refuses restoration rather than starting the previous service
    # over unconfirmed files. The journal preserves the unresolved transaction.
    assert json.loads(transaction.path.read_text())['state']=='installing'


def test_repeat_restore_does_not_override_later_service_changes(tmp_path):
    transaction,api,services,*_=fixture(tmp_path,False)
    transaction.install();transaction.restore()
    services.states[tx.SCREEN]['enabled']=True
    with pytest.raises(ValueError,match='Service changed after completed'):
        transaction.restore()
    assert services.states[tx.SCREEN]['enabled']


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('loss',['restore_reply','local_checkpoint'])
def test_installer_retries_confirmed_remote_restore_without_repeating_mutations(tmp_path,monkeypatch,existing,loss):
    from types import SimpleNamespace
    from install_journal import Journal
    transaction,api,services,directory,before,cameras,states=fixture(tmp_path,existing)
    transaction.install()
    journal=Journal(tmp_path/'installer.json')
    journal.create('printer','user',['touchscreen']);journal.begin('touchscreen')
    receipt={'kind':'touchscreen-transaction','journal':str(transaction.path)}
    journal.prepare_component('touchscreen',receipt)
    ctx=SimpleNamespace(host='printer',user='user',printing_now=lambda:False)
    attempts=[]
    def rollback(ctx,receipt):
        tx.Transaction(Path(receipt['journal']),services,api).restore()
        attempts.append('restored')
        if loss=='restore_reply' and len(attempts)==1:
            raise OSError('lost remote reply after restore')
    monkeypatch.setattr(deploy.REGISTRY['touchscreen'],'rollback',rollback)
    save=Journal.save
    def checkpoint(self):
        if loss=='local_checkpoint' and self.value['restored']==['touchscreen']:
            raise OSError('local checkpoint unavailable')
        return save(self)
    monkeypatch.setattr(Journal,'save',checkpoint)
    with pytest.raises(OSError):deploy.recover_installation(ctx,journal.path)
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before
    assert (api.cameras,api.selected)==cameras and services.states==states
    assert Journal(journal.path).load('printer','user').value['inflight']=='touchscreen'
    events=len(services.events);writes=len(api.writes)
    monkeypatch.setattr(Journal,'save',save)
    deploy.recover_installation(ctx,journal.path)
    assert all(action=='state' for action,unit in services.events[events:])
    assert len(api.writes)==writes
    assert Journal(journal.path).load('printer','user').value['state']=='restored'
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==before


def test_unknown_timelapse_never_replaces_or_restarts_active_fixer(tmp_path):
    api,services=API(),Services(True)
    services.states[tx.FIXER]['active']=True
    unit=tmp_path/'wmp-timelapse-camera.service'
    script=tmp_path/'timelapse-camera-fix.sh'
    unit.write_bytes(b'operator unit')
    script.write_bytes(b'operator script')
    def request(method,path,data):
        if path=='/machine/timelapse/settings':raise OSError('unknown optional settings')
        return api(method,path,data)
    transaction=tx.Transaction(tmp_path/'receipt.json',services,request)
    transaction.prepare([(unit,b'blind default unit',0o644),(script,b'blind default POST',0o755)])
    assert not transaction.receipt['files']
    services.events.clear()
    transaction.install()
    transaction.restore()
    assert unit.read_bytes()==b'operator unit' and script.read_bytes()==b'operator script'
    assert not any(unit==tx.FIXER and action!='state' for action,unit in services.events)
    assert services.states[tx.FIXER]=={'active':True,'enabled':True}
    assert not any(path=='/machine/timelapse/settings' for _,path,_ in api.writes)
