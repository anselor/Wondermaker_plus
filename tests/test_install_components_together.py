"""Real component publications/undo with modeled SSH and service/API endpoints.

The final component failure is injected before activation. No firmware, printer
or host services are operated. Source sealing is covered by delivery suites.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_deploy import deploy
from test_material_install import SFTP
from test_touchscreen_settings import API
from test_touchscreen_transaction import Services
from components import config, material, touchscreen, preload, moonraker
import preflight
import preload_bundle as bundle
import touchscreen_runtime as runtime
import touchscreen_transaction as transaction
from install_journal import Journal

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('patch_moonraker',[False,True])
@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('conflict',[False,True])
def test_later_component_failure_restores_or_preserves_conflict(tmp_path,monkeypatch,existing,conflict,patch_moonraker):
    printer=tmp_path/'printer'
    directory=printer/'home/printer/printer_data/config'
    shutil.copytree(ROOT/'config/stock',directory)
    extras=printer/'home/printer/klipper/klippy/extras';extras.mkdir(parents=True)
    if existing:
        for name in ('wm_material.py','wmp_recovery.py','wmp_identification.py','wmp_case_light.py','wmp_nozzles.py','wmp_orca_profiles.py'):
            (extras/name).write_bytes(('previous '+name).encode())
        (directory/'wm_material.cfg').write_text('[wm_material]\nload_feed_mm: 57\n')
    for name in ('wmp_filaments.json','wmp_filament_loaded.json','wmp_hotend_materials.json'):
        (directory/name).write_text('{"preserve":"operator state"}')
    nginx=printer/'etc/nginx/sites-available/fluidd';nginx.parent.mkdir(parents=True)
    nginx.write_bytes(b'server {\n listen 80;\n}\n')
    prefix=printer/'opt/wondermaker_plus';prefix.mkdir(parents=True)
    (prefix/'operator.txt').write_bytes(b'custom content')
    if existing:
        (prefix/'wmp_screen.py').write_bytes(b'previous screen implementation')
    home=printer/'home/printer'
    if patch_moonraker:
        components=home/'moonraker/moonraker/components'
        for relative,fixture in [('file_manager/file_manager.py','moonraker_directory_compat.py'),
                                 ('application.py','moonraker_http_error_compat.py')]:
            target=components/relative;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((ROOT/'tests/fixtures'/fixture).read_bytes())
        python=home/'moonraker-env/bin/python';python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
    service_events=tmp_path/'moonraker-events'
    sftp=SFTP(printer)
    ctx=SimpleNamespace(user='printer',files=[],config_only=False,no_restart=False,diff=False,
        qualify_unreleased_screen=False,
        DeployError=deploy.DeployError,ssh=lambda:None,sftp=lambda:sftp,
        moonraker=lambda path: json.dumps({"result":{"status":{"configfile":{"settings":{}}}}}),
        printing_now=lambda:False,close=lambda:None,
        restart_klipper=lambda:pytest.fail('failed installation restarted Klipper'))
    api,services=API(existing),Services(existing)
    camera_before=copy.deepcopy(api.cameras),api.selected
    services_before=copy.deepcopy(services.states)
    def snapshot():
        return {str(p.relative_to(printer)):(str(p.readlink()) if p.is_symlink() else transaction.snapshot(p)) for p in printer.rglob('*')
                if p.is_file() and not any('.wmp-' in part for part in p.relative_to(printer).parts)
                and 'wmp/backups/' not in str(p.relative_to(printer))}
    before=snapshot()
    monkeypatch.setattr(deploy,'Context',lambda args:ctx)
    def journal_factory(ctx,components):
        journal=Journal(tmp_path/'installer.json')
        journal.create('modeled-printer','printer',[component.NAME for component in components])
        return journal
    monkeypatch.setattr(deploy,'create_install_journal',journal_factory)
    # Exercise rollback after every real file publisher. Production ordering
    # activates preload before the optional bridge; dependency order has its
    # own assertion in test_preload_install.py. This fault fixture deliberately
    # postpones its modeled preload failure until all publications have receipts.
    monkeypatch.setattr(deploy,'ORDER',['config','touchscreen','material','moonraker','preload'])
    monkeypatch.setattr(sys,'argv',['deploy.py','install','all'])
    monkeypatch.setattr(bundle,'bundle_relative',lambda root:bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(bundle,'verify_source_binding',lambda root:None)
    monkeypatch.setattr(moonraker,'_enabled',lambda ctx:patch_moonraker)
    monkeypatch.setattr(preflight,'require_paths',lambda *args,**kwargs:None)
    monkeypatch.setattr(config,'preflight',preflight.config_plan)
    for component in (material,touchscreen,preload):
        monkeypatch.setattr(component,'preflight',lambda ctx:None)
    monkeypatch.setattr(touchscreen,'upload',lambda c:'disposable-payload')
    monkeypatch.setattr(touchscreen,'transaction_code',lambda action,source,journal:
                        'TOUCHSCREEN:'+json.dumps([action,journal]))
    journals={}
    def remote(ctx,code,**kwargs):
        if code.startswith('TOUCHSCREEN:'):
            action,journal=json.loads(code.split(':',1)[1])
            local=tmp_path/Path(journal).name
            tx=transaction.Transaction(local,services,api)
            if action=='install':
                tx.prepare(runtime.file_plan(ROOT,printer));tx.install()
                journals[journal]=local
            else:
                tx.restore()
            return touchscreen.RESULT_MARKER+json.dumps({'state':tx.receipt['state'],'journal':journal})
        if 'import moonraker_directory_service as lifecycle' in code:
            # Keep the actual component payload, filesystem transactions and
            # child interpreter. Only remote paths and service I/O are modeled.
            fake = '''
class FakeService:
 def event(self,name):
  with open(%r,'a') as f:f.write(name+'\\n')
 def inspect(self):
  assert not Path(%r).exists()
  self.event('inspect');return {'session':'unchanged'}
 def stop(self):self.event('stop');Path(%r).touch()
 def start(self):self.event('start');Path(%r).unlink(missing_ok=True)
 def verify(self,baseline):
  self.event('verify');assert baseline=={'session':'unchanged'}
MoonrakerService=FakeService
''' % (str(service_events),str(home/'service-stopped'),
                    str(home/'service-stopped'),str(home/'service-stopped'))
            code=code.replace('/home/printer',str(home))
            code=code.replace('target=Path(',fake+'\n'+'target=Path(',1)
        # Execute the real shipped config planner/publisher/restorer in an
        # isolated process, mapping only its printer config directory port.
        code=code.replace("Path('/home/printer/printer_data/config/printer.cfg')",
                          'Path(%r)'%str(directory/'printer.cfg'))
        code=code.replace("directory = pathlib.Path('/home/printer/printer_data/config')",
                          'directory = pathlib.Path(%r)'%str(directory))
        code=code.replace("'/home/printer/printer_data/config/.wmp-config-backup-",
                          "'"+str(directory)+'/.wmp-config-backup-')
        result=subprocess.run([sys.executable,'-I','-'],input=code,text=True,capture_output=True)
        if result.returncode:raise RuntimeError(result.stderr)
        return result.stdout
    monkeypatch.setattr(preflight,'remote',remote)
    def fail_preload(ctx):
        assert (directory/'wmp-screen-runtime.cfg').is_file()
        assert (directory/'wm_material.cfg').is_file()
        assert (prefix/'wmp_screen.py').read_bytes()==(ROOT/'device/wmp_screen.py').read_bytes()
        assert (extras/'wmp_identification.py').read_bytes()==(ROOT/'klipper_extras/wmp_identification.py').read_bytes()
        assert (extras/'wmp_case_light.py').read_bytes()==(ROOT/'klipper_extras/wmp_case_light.py').read_bytes()
        assert api.selected=='camera'
        if patch_moonraker:
            for name in moonraker.PATCHES:
                receipt=home/('wmp/backups/moonraker-'+name+'-managed/receipt.json')
                assert receipt.is_file()
            assert service_events.read_text().splitlines().count('stop')==2
            assert not (home/'service-stopped').exists()
        if conflict:
            (prefix/'wmp_screen.py').write_bytes(b'operator edit after installation')
        raise deploy.DeployError('injected final component rejection')
    monkeypatch.setattr(preload,'install',fail_preload)
    order=[]
    for component in (config,touchscreen,material):
        original=component.rollback
        def rollback(ctx,receipt,original=original,name=component.NAME):
            order.append(name);return original(ctx,receipt)
        monkeypatch.setattr(component,'rollback',rollback)
    assert deploy.main()==1
    saved=Journal(tmp_path/'installer.json').load('modeled-printer','printer')
    assert saved.value['inflight']=='preload'
    with pytest.raises(ValueError,match='outcome is unknown'):
        saved.recovery_receipts()
    if patch_moonraker:
        assert service_events.read_text().splitlines().count('stop')==4
        assert not (home/'service-stopped').exists()
        for relative,fixture in [('file_manager/file_manager.py','moonraker_directory_compat.py'),
                                 ('application.py','moonraker_http_error_compat.py')]:
            assert (components/relative).read_bytes()==(ROOT/'tests/fixtures'/fixture).read_bytes()
    if conflict:
        assert order==['material','touchscreen']
        assert (prefix/'wmp_screen.py').read_bytes()==b'operator edit after installation'
        assert (directory/'wmp-screen-runtime.cfg').is_file()
        assert (extras/'wmp_identification.py').read_bytes()==(ROOT/'klipper_extras/wmp_identification.py').read_bytes()
        assert (extras/'wmp_case_light.py').read_bytes()==(ROOT/'klipper_extras/wmp_case_light.py').read_bytes()
        assert [component.NAME for component,_ in ctx.rollback_backend.pending]==['config','touchscreen']
        for name in ('wmp_filaments.json','wmp_filament_loaded.json','wmp_hotend_materials.json'):
            assert (directory/name).read_text()=='{"preserve":"operator state"}'
        return
    # Config owns a second helper receipt, restored after its include files.
    assert order==['material','touchscreen','config','material']
    assert snapshot()==before
    assert (api.cameras,api.selected)==camera_before and services.states==services_before
    assert journals and all(json.loads(path.read_text())['state']=='restored' for path in journals.values())
    assert not ctx.rollback_backend.pending
    assert saved.value['restored']==['moonraker','material','touchscreen','config']
