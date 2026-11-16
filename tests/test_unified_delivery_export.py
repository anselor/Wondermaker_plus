"""Exercise real current artifact export without contacting a printer."""
from pathlib import Path
import shutil

import pytest
from test_deploy import deploy  # Makes the deployment tools importable.
import preload_bundle as bundle
import package_unified_ui_delivery as delivery

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / 'analysis/unified-ui-native'
CLIENT = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'


@pytest.fixture(autouse=True)
def available():
    if not CLIENT.is_file() or not (CANDIDATE / 'manifest.json').is_file():
        pytest.skip('local native build and vendor profile required')


def test_export_is_reproducible_and_passes_installer_verifier(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    a = delivery.export(ROOT, CANDIDATE, CLIENT, first)
    b = delivery.export(ROOT, CANDIDATE, CLIENT, second)
    assert a == b
    assert a['scope'] == 'packaging-control-only'
    bundle.verify_source_binding(first)
    bundle.verify_source_binding(second)
    for name in ('source.tar.gz', 'source-inputs.json', 'bundle.json', 'screen.so'):
        assert (first / bundle.CURRENT_BUNDLE / name).read_bytes() == (second / bundle.CURRENT_BUNDLE / name).read_bytes()
    with pytest.raises(ValueError, match='packaging-control-only'):
        bundle.select_delivery(first, CLIENT)


@pytest.mark.parametrize('reviewed_release', [False, True])
def test_wrong_vendor_profile_never_publishes_output(tmp_path, reviewed_release):
    wrong = tmp_path / 'client'
    wrong.write_bytes(b'wrong profile')
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='compiled native profile'):
        delivery.export(ROOT, CANDIDATE, wrong, output, reviewed_release=reviewed_release)
    assert not output.exists()
    assert not list(tmp_path.glob('.wmp-delivery-*'))


def test_existing_output_is_never_replaced(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    sentinel = output / 'keep'
    sentinel.write_text('previous package')
    with pytest.raises(ValueError, match='already exists'):
        delivery.export(ROOT, CANDIDATE, CLIENT, output)
    assert sentinel.read_text() == 'previous package'


def test_changed_backend_refuses_export(tmp_path):
    source = tmp_path / 'source'
    delivery.export(ROOT, CANDIDATE, CLIENT, source)
    (source / 'klipper_extras/wm_material.py').write_text('changed backend')
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='Build input changed'):
        delivery.export(source, CANDIDATE, CLIENT, output)
    assert not output.exists()


def test_publication_failure_cleans_staging(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError('publication failed')
    monkeypatch.setattr(delivery.os, 'rename', fail)
    with pytest.raises(OSError, match='publication failed'):
        delivery.export(ROOT, CANDIDATE, CLIENT, tmp_path / 'output')
    assert list(tmp_path.iterdir()) == []


def test_export_runs_installer_entry_points_without_repository_or_credentials(tmp_path):
    import os
    import subprocess
    import sys
    root = tmp_path / 'export'
    delivery.export(ROOT, CANDIDATE, CLIENT, root)
    env = {key: value for key, value in os.environ.items() if not key.startswith('WMP_') and key != 'PYTHONPATH'}
    for script, argument in [('tools/deploy.py', 'list'), ('utils/config_sync.py', '--help'),
                             ('tools/moonraker_directory_install.py', '--help')]:
        result = subprocess.run([sys.executable, '-I', str(root / script), argument],
                                cwd=tmp_path, env=env, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout
    assert not (root / '.env').exists()
    assert not list((root / 'config/live').glob('wm_zru_*.cfg'))
    assert not list(root.rglob('openace.py'))
    assert not list((root / 'config/live').glob('openace*.cfg'))


def test_exported_backend_installers_work_on_clean_stock_home_and_preserve_data(tmp_path):
    """Real exported component code/file operations; SFTP maps into a disposable home.

    Minimal Klipper registration ports exercise the installed backend constructor.
    This does not qualify service activation, native loading or physical hardware.
    """
    import subprocess
    import sys
    root = tmp_path / 'export'
    delivery.export(ROOT, CANDIDATE, CLIENT, root)
    home = tmp_path / 'printer'
    shutil.copytree(ROOT / 'config/stock', home / 'printer_data/config')
    script = r'''
import sys,json,os,subprocess
from pathlib import Path
from types import SimpleNamespace
root,home=map(Path,sys.argv[1:])
sys.path.insert(0,str(root/'tools'))
from components import config,material
import preload_bundle,preflight
extras=home/'klipper/klippy/extras';extras.mkdir(parents=True)
cfg=home/'printer_data/config'
original={p.name:p.read_bytes() for p in cfg.iterdir() if p.is_file()}
class Files:
 def path(self,path):
  relative=Path(path).relative_to('/home/test')
  assert '..' not in relative.parts
  return home/relative
 def open(self,path,mode):return self.path(path).open(mode)
 def posix_rename(self,source,destination):os.replace(self.path(source),self.path(destination))
 def remove(self,path):self.path(path).unlink()
files=Files();ctx=SimpleNamespace(user='test',sftp=lambda:files,ssh=lambda:None,
 config_only=False,files=[],DeployError=RuntimeError)
loaded_settings={}
def moonraker(path):
 assert path=='/printer/objects/query?configfile'
 return json.dumps({'result':{'status':{'configfile':{'settings':loaded_settings}}}})
ctx.moonraker=moonraker
def remote(ctx,code,**kwargs):
 code=code.replace('/home/test/printer_data/config',str(cfg))
 result=subprocess.run([sys.executable,'-I','-'],input=code,text=True,capture_output=True)
 if result.returncode:raise RuntimeError(result.stderr)
 return result.stdout
preflight.remote=remote
preflight.config_plan(ctx);config.install(ctx);material.install(ctx)
import reconcile_screen_config as reconcile
for name,content in original.items():
 actual=(cfg/name).read_bytes()
 assert (actual.replace(reconcile.BLOCK.encode(),b'') if name=='printer.cfg' else actual)==content
assert (cfg/'wm_material.cfg').read_bytes()==(root/'klipper_extras/wm_material.cfg').read_bytes()
expected_helpers={'wm_material.py','wmp_orca_profiles.py','wmp_nozzles.py','wmp_saved_variables.py','wmp_recovery_retirement.py','wmp_recovery.py','wmp_identification.py','wmp_case_light.py'}
assert set(preload_bundle.verify_backend_helpers(root,home))==expected_helpers
# Import and construct the published backend, not the checkout's module. Missing
# legacy metadata must still allow standalone startup and four sensor projections.
sys.path.insert(0,str(extras))
import wm_material
assert Path(wm_material.__file__).parent==extras
commands={};endpoints={};events={}
def unexpected(*args,**kwargs):raise AssertionError('startup attempted command or motion')
class Gcode:
 run_script=staticmethod(unexpected)
 def register_command(self,name,callback,**kw):
  if callback is None:return commands.pop(name,None)
  assert name not in commands,name
  commands[name]=callback
 def get_status(self,now):return {'commands':dict(commands)}
gcode=Gcode()
for name in ('CANCEL_PRINT','SAVE_CONFIG','SAVE_CONFIG_NO_RESTART'):
 gcode.register_command(name,unexpected)
timers=[]
class Reactor:
 NOW=0.;NEVER=float('inf')
 def monotonic(self):return 1.
 def register_timer(self,callback,when):
  timers.append((callback,when));return callback
reactor=Reactor()
class Printer:
 def lookup_object(self,name,default=None):
  if name=='gcode':return gcode
  if name=='webhooks':return SimpleNamespace(register_endpoint=lambda name,callback:endpoints.setdefault(name,callback))
  return default
 def register_event_handler(self,name,callback):events.setdefault(name,[]).append(callback)
 def get_start_args(self):return {'config_file':str(cfg/'printer.cfg')}
 def get_reactor(self):return reactor
printer=Printer()
class Config:
 def get_printer(self):return printer
 def getfloat(self,name,default,**kw):return default
 def get(self,name,default=None):
  return {'ini_path':str(cfg/'absent.ini'),'recovery_checkpoint_dir':str(home/'checkpoints'),
          'usb_profile_root':str(home/'absent-usb')}.get(name,default)
backend=wm_material.WMMaterial(Config())
status=backend.get_status(1.)
assert status['afc_metadata']['owner']=='standalone'
assert status['identity_writable'] and status['identities']=={}
assert status['filament_catalogue']==[] and 'catalogue_error' not in status
assert {'PLA','PETG','PCTG','PA6','PA12','PP'}<=set(status['filament_materials'])
assert set(status['filament_presence'])=={'h0','h1','h2','h3'}
assert all(record['state']=='unknown' for record in status['filament_presence'].values())
assert {'WMP_FILAMENT_SERVICE','WMP_TOOLHEAD_ACTION','WMP_SET_FILAMENT','WMP_CHECK_RESUME'}<=commands.keys()
assert {'wmp/filament/cancel','wmp/recovery/stop'}<=endpoints.keys()
assert 'klippy:ready' in events
assert not (cfg/'absent.ini').exists() and not (cfg/'wmp_filaments.json').exists()
# Run every registered ready callback: constructor success alone misses command
# ownership hooks and background scheduling. Timers are captured, not executed.
for callback in events['klippy:ready']:callback()
ready=backend.get_status(4.)
assert ready['print_cancel_ingress_protocol']==1
assert ready['script_generation_protocol']==1
assert {'SET_COLOR','SET_MATERIAL','AFC_SET_SPOOL_TEMP','WMP_SET_BRAND'}<=commands.keys()
assert len(timers)==2
assert {callback.__name__ for callback,when in timers}=={'_execution_tick','_afc_tick'}
assert commands['SAVE_CONFIG'] is not unexpected
assert commands['CANCEL_PRINT'] is not unexpected
assert not (cfg/'absent.ini').exists() and not (cfg/'wmp_filaments.json').exists()
# Customized configuration and persistent filament records survive an update.
(cfg/'wm_material.cfg').write_text('[wm_material]\nload_feed_mm: 57\n')
(cfg/'wmp_filaments.json').write_text('{"h2":{"brand":"Sunlu"}}')
(cfg/'wmp_filament_loaded.json').write_text('{"h2":true}')
(cfg/'wmp_hotend_materials.json').write_text(json.dumps({'version':1,'heads':{'h2':{'state':'purged','materials':[{'brand':'Sunlu','material':'PLA Matte','color':'#f5b6cd'}],'unknown_residue':False}}}))
before={p.name:p.read_bytes() for p in cfg.iterdir() if p.is_file()}
preflight.config_plan(ctx);config.install(ctx);material.install(ctx)
assert before=={p.name:p.read_bytes() for p in cfg.iterdir() if p.is_file()}
assert set(preload_bundle.verify_backend_helpers(root,home))==expected_helpers
# A running owner must refuse even if its disk configuration is disabled.
loaded_settings['openace']={}
try:
 preflight.config_plan(ctx)
except RuntimeError as error:
 assert 'standalone WM+' in str(error)
else:raise AssertionError('running manager accepted')
assert before=={p.name:p.read_bytes() for p in cfg.iterdir() if p.is_file()}
loaded_settings.clear()
assert not list(home.rglob('*openace*'))
assert not list(home.rglob('*.wmp-upload-*'))
print(json.dumps({'helpers':len(expected_helpers),'openace_required':False,'preserved_files':sorted(before)}))
'''
    result = subprocess.run([sys.executable, '-I', '-c', script, str(root), str(home)],
                            cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert '"helpers": 8' in result.stdout


@pytest.mark.parametrize('name', ['tools/deploy.py', 'tools/components/material.py',
                                 'klipper_extras/wm_material.cfg', 'utils/config_sync.py',
                                 'tools/components/moonraker.py',
                                 'tools/moonraker_directory_install.py',
                                 'tools/moonraker_directory_transaction.py',
                                 'tools/moonraker_directory_service.py',
                                 'tools/moonraker_directory_patch.py'])
def test_installer_inputs_are_source_bound(tmp_path, name):
    root = tmp_path / 'export'
    delivery.export(ROOT, CANDIDATE, CLIENT, root)
    (root / name).write_text('changed installer input')
    with pytest.raises(ValueError, match='source input changed'):
        bundle.verify_source_binding(root)


@pytest.mark.parametrize('name', ['tools/deploy.py', 'scripts/install.sh', 'device/www/index.html'])
def test_missing_installer_payload_refuses_export_atomically(tmp_path, name):
    source = tmp_path / 'source'
    delivery.export(ROOT, CANDIDATE, CLIENT, source)
    (source / name).unlink()
    output = tmp_path / 'output'
    with pytest.raises(ValueError, match='installer input missing'):
        delivery.export(source, CANDIDATE, CLIENT, output)
    assert not output.exists() and not list(tmp_path.glob('.wmp-delivery-*'))


def test_linked_installer_payload_cannot_collect_outside_file(tmp_path):
    source = tmp_path / 'source'
    delivery.export(ROOT, CANDIDATE, CLIENT, source)
    outside = tmp_path / 'private'
    outside.write_text('not for export')
    script = source / 'tools/deploy.py'
    script.unlink()
    script.symlink_to(outside)
    with pytest.raises(ValueError, match='installer input missing or outside'):
        delivery.export(source, CANDIDATE, CLIENT, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('failure', [None, 'source', 'loader'])
def test_normal_current_preflight_keeps_source_and_loader_gates(tmp_path, failure):
    """Normal path on a disposable reviewed descriptor; not release promotion.

    Execute the exported preflight and exact client/artifact checks. Only ldd's
    target-library resolution is modeled because the host is not AArch64.
    """
    import json
    import os
    import subprocess
    import sys
    root = tmp_path / 'export'
    descriptor = delivery.export(ROOT, CANDIDATE, CLIENT, root, reviewed_release=True)
    assert descriptor['scope'] == 'reviewed-delivery'
    assert 'Ready for normal installer checks' in (root / 'READ-ME.txt').read_text()
    bundle.verify_source_binding(root)
    if failure == 'source':
        with (root / 'klipper_extras/wm_material.py').open('a') as stream:
            stream.write('\n# unreviewed backend change\n')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    loader = bindir / 'ldd'
    dependencies = '\n'.join(name + ' => /lib/' + name + ' (0x123)'
                             for name in descriptor['artifact']['needed'])
    if failure == 'loader':
        dependencies += '\nlibmissing-wmp.so => not found'
    loader.write_text('#!/bin/sh\ntest "$1" = -r || exit 3\ncat <<\'WMP_DEPS\'\n'
                      + dependencies + '\nWMP_DEPS\n')
    loader.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
    script = bundle.preflight_script(root, str(CLIENT))  # no qualification flag
    result = subprocess.run([sys.executable, '-I', '-'], input=script, env=env,
                            text=True, capture_output=True, cwd=tmp_path)
    if failure is None:
        assert result.returncode == 0, result.stderr
        assert 'exact1113 dependency check passed' in result.stdout
    else:
        assert result.returncode != 0
        assert ('native source delivery unavailable' if failure == 'source'
                else 'libmissing-wmp.so') in result.stderr
    # Only the isolated descriptor was reviewed for this test. The candidate
    # remains unpromoted, and no service or installed library was touched.
    assert descriptor['artifact']['sha256'] == delivery.sha(
        (CANDIDATE / 'libwmp_unified_screen_candidate.so').read_bytes())
