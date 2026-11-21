"""Explicit removal restores the first baseline across multiple UI updates."""
import copy
import json
import pytest
from test_touchscreen_transaction import fixture, Services
import touchscreen_transaction as tx
import touchscreen_runtime as runtime


@pytest.mark.parametrize('existing',[False,True])
def test_two_updates_restore_original_files_camera_and_services(tmp_path, existing):
    first, api, services, directory, original, camera, states = fixture(tmp_path,existing)
    first.receipt['factory_before']=None
    first.save();first.install()
    runtime.commit_factory(tmp_path,first)
    baseline=json.loads((tmp_path/'factory-baseline').read_text())
    second=tx.Transaction(tmp_path/'second.json',services,api)
    second.prepare([(directory/'screen.py',b'screen version two',0o755)])
    second.receipt['factory_before']=copy.deepcopy(baseline)
    second.save();second.install()
    runtime.commit_factory(tmp_path,second)
    removal=tx.Transaction(tmp_path/'factory-baseline',services,api)
    removal.restore()
    assert {p.name:tx.snapshot(p) for p in directory.iterdir()}==original
    assert (api.cameras,api.selected)==camera
    assert services.states==states
    removal.restore()  # Idempotent explicit removal.


def test_rollback_of_update_restores_previous_factory_inventory(tmp_path):
    first, api, services, directory, _, _, _=fixture(tmp_path,False)
    first.receipt['factory_before']=None
    first.save();first.install();runtime.commit_factory(tmp_path,first)
    before=json.loads((tmp_path/'factory-baseline').read_text())
    second=tx.Transaction(tmp_path/'second.json',services,api)
    second.prepare([(directory/'screen.py',b'screen two',0o644)])
    second.receipt['factory_before']=before
    second.save();second.install();runtime.commit_factory(tmp_path,second)
    second.restore();runtime.rewind_factory(tmp_path,second)
    assert json.loads((tmp_path/'factory-baseline').read_text())==before
    tx.Transaction(tmp_path/'factory-baseline',services,api).restore()


def test_interrupted_inventory_commit_is_completed_from_applied_receipt(tmp_path):
    first, api, services, _, _, _, _=fixture(tmp_path,False)
    first.receipt['factory_before']=None;first.save();first.install()
    (tmp_path/'factory-pending').write_text(json.dumps({'journal':first.path.name}))
    ports=type('Ports',(),{'services':services,'request':api})
    runtime.settle_factory(tmp_path,ports)
    assert not (tmp_path/'factory-pending').exists()
    assert json.loads((tmp_path/'factory-baseline').read_text())['generation']==first.path.name


def test_unknown_edit_blocks_factory_restore(tmp_path):
    first, _, _, directory, _, _, _=fixture(tmp_path,False)
    first.receipt['factory_before']=None;first.save();first.install()
    runtime.commit_factory(tmp_path,first)
    (directory/'screen.py').write_bytes(b'operator edit')
    with pytest.raises(ValueError,match='Concurrent touchscreen file edit'):
        tx.Transaction(tmp_path/'factory-baseline',first.services,first.request).restore()
    assert (directory/'nginx').read_bytes()==b'candidate nginx'


def legacy_fixture(tmp_path):
    from test_touchscreen_settings import API
    root=tmp_path/'printer'
    prefix=root/'opt/wondermaker_plus'
    (prefix/'backup').mkdir(parents=True)
    original=b'server {\n}\n'
    (prefix/'backup/fluidd.orig').write_bytes(original)
    (prefix/'wmp_screen.py').write_bytes(b'legacy screen')
    site=root/'etc/nginx/sites-available/fluidd';site.parent.mkdir(parents=True)
    site.write_bytes(b'server {\n    include /opt/wondermaker_plus/nginx-screen.conf; # wondermaker_plus\n}\n')
    units=root/'etc/systemd/system';units.mkdir(parents=True)
    for unit in (tx.SCREEN,tx.FIXER):
        (units/unit).write_bytes(b'[Service]\nExecStart=/opt/wondermaker_plus/wmp_screen.py\n')
    services=Services(True)
    api=API(False)
    import touchscreen_settings as settings
    receipt=settings.prepare(api);settings.apply(api,receipt,lambda _:None)
    ports=type('Ports',(),{'services':services,'request':api})
    directory=tmp_path/'transactions';directory.mkdir()
    return directory,ports,root,site,original


def test_legacy_script_install_migrates_before_explicit_restore(tmp_path):
    directory,ports,root,site,original=legacy_fixture(tmp_path)
    runtime.adopt_legacy_factory(directory,ports,root)
    removal=tx.Transaction(directory/'factory-baseline',ports.services,ports.request)
    removal.restore()
    assert site.read_bytes()==original
    assert not (root/'opt/wondermaker_plus/wmp_screen.py').exists()
    assert [camera['name'] for camera in ports.request.cameras]==['camera']
    assert not ports.services.states[tx.SCREEN]['enabled']


def test_unknown_legacy_nginx_edit_is_not_overwritten(tmp_path):
    directory,ports,root,site,_=legacy_fixture(tmp_path)
    site.write_bytes(site.read_bytes()+b'unknown additional directive\n')
    before=site.read_bytes()
    with pytest.raises(ValueError,match='does not explain current'):
        runtime.adopt_legacy_factory(directory,ports,root)
    assert site.read_bytes()==before
    assert not (directory/'factory-baseline').exists()
