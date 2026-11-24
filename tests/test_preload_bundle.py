"""Offline packaging; no SSH/native candidate load or service invocation."""
import importlib.util
import json,shutil,subprocess,tarfile
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_deploy import deploy
from components import preload
ROOT=Path(__file__).resolve().parents[1]


def vendor_client(version):
    path=ROOT/('analysis/fw_'+version+'_payload/root/home/t13dp/TM_T1/bin/client')
    if not path.is_file():pytest.skip('local vendor '+version+' client payload not present; actual profile test requires that optional fixture')
    return path


def test_sealed_real_bundle_is_verified_without_gxx_or_loading(tmp_path,monkeypatch):
    monkeypatch.setattr(preload,'ROOT',str(bundle_copy(tmp_path)))
    bundle=preload.screen_bundle()
    assert bundle['profile']['firmware']=='1.1.13'
    assert bundle['artifact']['machine']=='AArch64' and bundle['artifact']['nodelete'] is True
    assert bundle['scope']=='reviewed-delivery'


def test_failed_activation_restores_previous_libraries_and_dropin(tmp_path,monkeypatch):
    home=tmp_path/'wmp';(home/'lib').mkdir(parents=True)
    old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'previous owned compat')
    drop=tmp_path/'wmp-preload.conf';drop.write_text('previous override\n')
    source=tmp_path/'only';source.mkdir();c=source/'one.c';c.write_text('int preserved(void){return 1;}\n')
    monkeypatch.setattr(preload,'screen_bundle',lambda:None)
    monkeypatch.setattr(preload,'sources',lambda:[('openace-compat',str(c))])
    monkeypatch.setattr(preload,'_home',lambda ctx:str(home))
    monkeypatch.setattr(preload,'DROPIN',str(drop))
    monkeypatch.setattr(preload,'status',lambda ctx:None)
    monkeypatch.setattr(preload,'_restart',lambda *a, **kw:(_ for _ in ()).throw(deploy.DeployError('restart failed')))
    def local_run(client,cmd,**kwargs):
        if cmd == 'systemctl stop '+preload.SERVICE:
            return '', '', 0  # Service lifecycle is modeled; files are real.
        out=subprocess.run(['bash','-c',cmd],text=True,capture_output=True)
        return out.stdout,out.stderr,out.returncode
    monkeypatch.setattr(preload,'run',local_run)
    ctx=NS(user='test',printing_now=lambda:False,ssh=lambda:None,sftp=lambda:NS(put=lambda a,b:shutil.copyfile(a,b)),DeployError=deploy.DeployError)
    with pytest.raises(deploy.DeployError):preload.install(ctx)
    assert old.read_bytes()==b'previous owned compat'
    assert drop.read_text()=='previous override\n'


def test_control_artifact_cannot_be_installed_as_final_ui(monkeypatch,tmp_path):
    import preload_bundle as pb
    client=vendor_client('1.1.13')
    def forbidden(*args):raise AssertionError('unreleased bundle cannot reach loader dependency port')
    monkeypatch.setattr(pb,'verify_dependencies',forbidden)
    control=ROOT/'tests/fixtures/native-screen-control'
    assert pb.load_bundle(control)['scope']=='packaging-control-only'
    with pytest.raises(ValueError,match='packaging-control-only'):pb.select_delivery(control,client)
    # Older supported C profiles do not depend on this pending native release.
    old=vendor_client('1.1.12')
    assert pb.select_delivery(control,old) is False


def bundle_copy(tmp_path):
    target=tmp_path/'package'
    # This fixture is the historical package; leave the current one out.
    shutil.copytree(ROOT/'client-preload',target/'client-preload',
                    ignore=shutil.ignore_patterns('unified-screen1113'))
    # The historical artifact must be paired with its sealed historical source,
    # not today's evolving compatibility C file. Never rewrite its descriptor.
    import preload_bundle as pb
    name='client-preload/openace-compat/wmp_openace_compat.c'
    manifest=json.loads((target/pb.BUNDLE/'source-inputs.json').read_text())
    with tarfile.open(target/pb.BUNDLE/'source.tar.gz') as archive:
        for name in set(manifest) | {name}:
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            destination=target/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(archive.extractfile(name).read())
    return target


@pytest.mark.parametrize('change',['bytes','source','machine','nodelete','needed','profile'])
def test_sealed_integrity_and_elf_contract_tampering_refuses(tmp_path,change):
    import preload_bundle as pb
    target=bundle_copy(tmp_path);directory=target/pb.BUNDLE;p=directory/'bundle.json';v=json.loads(p.read_text())
    if change=='bytes':
        artifact=directory/v['artifact']['file'];artifact.write_bytes(artifact.read_bytes()+b'x')
    elif change=='source':(directory/'source-inputs.json').write_text('{}')
    elif change=='profile':v['profile']['firmware']='1.1.12';p.write_text(json.dumps(v))
    else:
        v['artifact'][change]={'machine':'x86_64','nodelete':False,'needed':[]}[change];p.write_text(json.dumps(v))
    with pytest.raises(ValueError):pb.load_bundle(target)


@pytest.mark.parametrize('code,text',[(1,'loader failed'),(0,'libstdc++.so.6 => not found'),(0,'undefined symbol: wrong_version'),(0,'')])
def test_missing_runtime_or_symbol_version_refuses_before_activation(code,text,tmp_path):
    import preload_bundle as pb
    with pytest.raises(ValueError):pb.validate_dependencies(pb.load_bundle(bundle_copy(tmp_path)),code,text)


def test_exact_profile_and_real_staged_artifact_dependency_port(tmp_path,monkeypatch):
    import preload_bundle as pb
    target=bundle_copy(tmp_path);calls=[]
    client=vendor_client('1.1.13')
    def deps(bundle,artifact):
        calls.append(str(artifact));assert pb.digest(artifact)==bundle['artifact']['sha256']
        pb.validate_dependencies(bundle,0,'\n'.join(name+' => /lib/'+name+' (0x123)' for name in bundle['artifact']['needed']))
    monkeypatch.setattr(pb,'verify_dependencies',deps)
    assert pb.verify_staged(target,client) and len(calls)==1
    changed=tmp_path/'modified';changed.write_bytes(client.read_bytes()+b'x')
    assert not pb.verify_staged(target,changed) and len(calls)==1


def test_publication_has_one_compat_library_and_preserves_other_entries(tmp_path):
    import preload_bundle as pb
    stage=tmp_path/'stage';stage.mkdir();lib=tmp_path/'lib';lib.mkdir();drop=tmp_path/'override'
    (lib/'libwmp_wifi-fix.so').write_bytes(b'wifi');(lib/'libwmp_openace-compat.so').write_bytes(b'old')
    (stage/'screen.so').write_bytes(b'staged verified test bytes')
    (stage/'outputs.json').write_text(json.dumps({'libwmp_openace-compat.so':dict(file='screen.so',sha256=pb.digest(stage/'screen.so'))}))
    libs=pb.publish_stage(stage,lib,drop)
    assert len([p for p in libs if 'openace' in p])==1
    assert 'libwmp_wifi-fix.so' not in drop.read_text()
    assert (lib/'libwmp_wifi-fix.so').read_bytes()==b'wifi'
    pb.restore_publication(stage)
    assert (lib/'libwmp_openace-compat.so').read_bytes()==b'old' and not drop.exists()


@pytest.mark.parametrize('managed', [False, True])
def test_managed_screen_boot_dependency_is_transactional(tmp_path, managed):
    import preload_bundle as pb
    stage=tmp_path/'stage';stage.mkdir();lib=tmp_path/'lib';drop=tmp_path/'override'
    previous='[Service]\nEnvironment="OLD=1"\n';drop.write_text(previous)
    (stage/'test.so').write_bytes(b'test')
    (stage/'outputs.json').write_text(json.dumps({'libwmp_openace-compat.so':
        dict(file='test.so',sha256=pb.digest(stage/'test.so'))}))
    pb.publish_stage(stage,lib,drop,start_backend=managed)
    text=drop.read_text()
    assert ('Wants=klipper.service\nAfter=klipper.service' in text) == managed
    assert 'ExecStart' not in text and 'restart' not in text
    pb.restore_publication(stage)
    assert drop.read_text()==previous


def test_duplicate_compat_candidate_is_retired_without_loading_it(tmp_path):
    import preload_bundle as pb
    stage=tmp_path/'stage';stage.mkdir();lib=tmp_path/'lib';lib.mkdir();drop=tmp_path/'override';drop.write_text('old')
    (lib/'libwmp_openace-compat.so').write_bytes(b'old');(lib/'libwmp_openace_screen_candidate.so').write_bytes(b'duplicate')
    (stage/'screen.so').write_bytes(b'new');(stage/'outputs.json').write_text(json.dumps({'libwmp_openace-compat.so':dict(file='screen.so',sha256=pb.digest(stage/'screen.so'))}))
    pb.publish_stage(stage,lib,drop)
    assert 'openace_screen_candidate' not in drop.read_text()
    pb.restore_preload_factory(lib,drop)
    assert not (lib/'libwmp_openace_screen_candidate.so').exists()
    assert drop.read_text()=='old'


def test_ldd_relocation_check_never_runs_candidate_constructors(tmp_path):
    import preload_bundle as pb
    marker=tmp_path/'executed';c=tmp_path/'safe.c';so=tmp_path/'safe.so'
    c.write_text('#include <stdio.h>\n__attribute__((constructor)) static void init(void){FILE*f=fopen("'+str(marker)+'","w");if(f)fclose(f);}\n')
    subprocess.run(['gcc','-shared','-fPIC',str(c),'-o',str(so)],check=True)
    out=subprocess.run(['ldd','-r',str(so)],text=True,capture_output=True)
    assert out.returncode==0 and not marker.exists()


def local_installer(tmp_path,monkeypatch,*,exact=False):
    """Real shell/file ports on disposable paths; ldd target response is modeled.

    The copied fixture retains the actual independently reviewed UI121 descriptor
    and bytes. Target dependency output remains an explicit modeled remote port.
    """
    import preload_bundle as pb
    root=bundle_copy(tmp_path);directory=root/pb.BUNDLE
    descriptor=directory/'bundle.json';v=json.loads(descriptor.read_text());assert v['scope']=='reviewed-delivery'
    home=tmp_path/'home';home.mkdir();drop=tmp_path/'service.conf'
    config=home/'printer_data/config';config.mkdir(parents=True)
    (config/'printer.cfg').write_text('[wm_material]\nini_path: ~/custom/tmt1.ini\n')
    monkeypatch.setattr(preload,'_printer_home',lambda ctx:str(home))
    client=vendor_client('1.1.13' if exact else '1.1.12')
    (root/'client-preload/wifi.c').write_text('int wifi_kept(void){return 1;}\n')
    (root/'client-preload/guard.c').write_text('int guard_fixture(void){return 1;}\n')
    selected=[('head-config-guard',str(root/'client-preload/guard.c')),('openace-compat',str(root/'client-preload/openace-compat/wmp_openace_compat.c')),('wifi-fix',str(root/'client-preload/wifi.c'))]
    monkeypatch.setattr(preload,'ROOT',str(root));monkeypatch.setattr(preload,'sources',lambda:selected)
    monkeypatch.setattr(preload,'_client',lambda ctx:str(client));monkeypatch.setattr(preload,'_home',lambda ctx:str(home));monkeypatch.setattr(preload,'DROPIN',str(drop))
    monkeypatch.setattr(preload,'status',lambda ctx:None)
    binpath=tmp_path/'bin';binpath.mkdir();ldd=binpath/'ldd';lines='\n'.join(name+' => /lib/'+name+' (0x123)' for name in v['artifact']['needed'])
    ldd.write_text('#!/bin/sh\ntest "$1" = -r || exit 3\nprintf "%s\\n" '+"'"+lines+"'"+'\n');ldd.chmod(0o755)
    monkeypatch.setenv('PATH',str(binpath)+':'+__import__('os').environ['PATH'])
    commands=[];restarts=[]
    def local_run(client,cmd,**kwargs):
        if cmd.startswith('systemctl '):
            assert cmd == 'systemctl stop '+preload.SERVICE, 'unmodeled service command'
            commands.append(cmd)
            return '', '', 0
        commands.append(cmd);out=subprocess.run(['bash','-c',cmd],text=True,capture_output=True)
        return out.stdout,out.stderr,out.returncode
    monkeypatch.setattr(preload,'run',local_run);monkeypatch.setattr(preload,'_restart',lambda *args, **kwargs:restarts.append(True))
    ctx=NS(user='test',printing_now=lambda:False,ssh=lambda:None,sftp=lambda:NS(put=lambda a,b:shutil.copyfile(a,b)),DeployError=deploy.DeployError)
    return root,home,drop,selected,commands,restarts,ctx


def test_exact1113_installs_real_sealed_bytes_once_not_gxx_or_compat_rebuild(tmp_path,monkeypatch):
    import preload_bundle as pb
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    preload.install(ctx)
    assert pb.digest(home/'lib/libwmp_openace-compat.so')==pb.load_bundle(root)['artifact']['sha256']
    assert (home/'lib/libwmp_wifi-fix.so').is_file() and len(restarts)==1
    assert drop.read_text().count('libwmp_openace-compat.so')==1
    assert not any(command.startswith('gcc ') and 'wmp_openace_compat.c' in command for command in commands)
    assert not list(home.glob('preload-stage-*'))


def test_older_supported_profile_keeps_old_c_compilation(tmp_path,monkeypatch):
    import preload_bundle as pb
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    preload.install(ctx)
    assert pb.digest(home/'lib/libwmp_openace-compat.so')!=pb.load_bundle(root)['artifact']['sha256']
    assert any(command.startswith('gcc ') and 'wmp_openace_compat.c' in command for command in commands)
    assert len(restarts)==1


def test_later_compile_failure_never_publishes_first_component(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('old override')
    Path(selected[1][1]).write_text('this is deliberately invalid C')
    with pytest.raises(deploy.DeployError):preload.install(ctx)
    assert old.read_bytes()==b'old' and drop.read_text()=='old override' and not restarts


def test_staged_upload_corruption_refuses_before_old_library_or_override(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('old override')
    def put(source,target):
        shutil.copyfile(source,target)
        if target.endswith('/screen.so'):Path(target).write_bytes(b'corrupt upload')
    ctx.sftp=lambda:NS(put=put)
    with pytest.raises(deploy.DeployError,match='sealed descriptor'):preload.install(ctx)
    assert old.read_bytes()==b'old' and drop.read_text()=='old override' and not restarts


def test_publication_written_then_lost_reply_repairs_current_owned_files(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('old override')
    original=preload.run;lost=[]
    def missing_reply(client,command,**kwargs):
        result=original(client,command,**kwargs)
        if 'print(json.dumps(publish_stage(' in command and not lost:
            assert old.read_bytes()!=b'old';lost.append(True)
            return '', 'connection lost after publication', 255
        return result
    monkeypatch.setattr(preload,'run',missing_reply)
    with pytest.raises(deploy.DeployError,match='connection lost'):preload.install(ctx)
    assert lost and old.read_bytes()==b'old' and drop.read_text()=='old override'
    assert not (home/'lib/libwmp_wifi-fix.so').exists() and not restarts


def test_print_start_during_staging_refuses_before_publication(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('old override')
    ctx.printing_now=lambda:True
    with pytest.raises(deploy.DeployError,match='print started'):preload.install(ctx)
    assert old.read_bytes()==b'old' and drop.read_text()=='old override' and not restarts


def test_target_dependency_refusal_preserves_installed_files(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'old');drop.write_text('old override')
    (tmp_path/'bin/ldd').write_text('#!/bin/sh\necho "libstdc++.so.6 => not found"\n')
    with pytest.raises(deploy.DeployError,match='dependencies'):preload.install(ctx)
    assert old.read_bytes()==b'old' and drop.read_text()=='old override' and not restarts


def test_mid_publication_file_error_restores_all_prior_outputs(tmp_path,monkeypatch):
    import preload_bundle as pb
    stage=tmp_path/'stage';stage.mkdir();lib=tmp_path/'lib';lib.mkdir();drop=tmp_path/'override';drop.write_text('old override')
    outputs={}
    for name in ('openace-compat','wifi-fix'):
        fn='libwmp_'+name+'.so';(lib/fn).write_bytes(('old '+name).encode());(stage/fn).write_bytes(('new '+name).encode())
        outputs[fn]=dict(file=fn,sha256=pb.digest(stage/fn))
    (stage/'outputs.json').write_text(json.dumps(outputs));replace=pb.os.replace;failed=[]
    def once(a,b):
        if str(b).endswith('libwmp_wifi-fix.so') and not failed:
            failed.append(True);raise OSError('publication filesystem unavailable')
        return replace(a,b)
    monkeypatch.setattr(pb.os,'replace',once)
    with pytest.raises(OSError,match='filesystem'):pb.publish_stage(stage,lib,drop)
    assert failed and drop.read_text()=='old override'
    for name in ('openace-compat','wifi-fix'):assert (lib/('libwmp_'+name+'.so')).read_bytes()==('old '+name).encode()


def test_combined_uninstall_preserves_configuration_and_clears_one_owned_name(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    preload.install(ctx);config=home/'saved_variables.cfg';config.write_text('operator state unchanged')
    preload.uninstall(ctx)
    assert not drop.exists() and not list((home/'lib').glob('libwmp_*.so'))
    assert config.read_text()=='operator state unchanged' and len(restarts)==2


def test_status_reports_exact_disk_bytes_but_never_calls_them_applied(tmp_path,monkeypatch,capsys):
    real_status=preload.status
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    preload.install(ctx);capsys.readouterr();run=preload.run;queries=[]
    def observed(client,command,**kwargs):
        queries.append(command)
        if command=='pidof client':return '123\n','',0
        if command.startswith('grep -F '):
            assert '[pid 123]' in command
            return '[pid 123] original compat guard applied\n','',0
        if '/proc/' in command:return str(home/'lib/libwmp_openace-compat.so'),' ',0
        return run(client,command,**kwargs)
    monkeypatch.setattr(preload,'run',observed);real_status(ctx);text=capsys.readouterr().out
    assert 'installed artifact matches sealed bundle' in text
    assert 'native hook/backend application unconfirmed' in text
    assert 'pid 123' in text and any('grep -F ' in q for q in queries)


@pytest.mark.parametrize('backend_failure', [False, True])
def test_activation_failure_restores_backend_before_previous_service(tmp_path, monkeypatch, backend_failure):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    old=home/'lib/libwmp_openace-compat.so';old.parent.mkdir();old.write_bytes(b'old library')
    drop.write_text('old override')
    events=[]
    checked=preload._checked
    def check(ctx,c,cmd,**kw):
        if cmd == 'systemctl stop '+preload.SERVICE:
            events.append('stop')
            return ''
        return checked(ctx,c,cmd,**kw)
    monkeypatch.setattr(preload,'_checked',check)
    def restart(*args, **kwargs):
        events.append('restart')
        if events == ['restart']:
            raise deploy.DeployError('candidate failed readiness')
        assert old.read_bytes() == b'old library'
        assert events[-2] == 'backend'
    monkeypatch.setattr(preload,'_restart',restart)
    def backend(*,service_stopped):
        assert service_stopped
        assert old.read_bytes() == b'old library' and drop.read_text() == 'old override'
        events.append('backend')
        if backend_failure:
            raise OSError('backend restore unconfirmed')
    ctx.rollback_backend=backend
    with pytest.raises(deploy.DeployError):
        preload.install(ctx)
    assert events == ['restart','stop','backend'] + ([] if backend_failure else ['restart'])
    assert bool(getattr(backend,'blocked',False)) == backend_failure


def test_missing_recovery_journal_prevents_backend_rollback_and_service_restart(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    old=home/'lib/libwmp_openace-compat.so';old.parent.mkdir();old.write_bytes(b'old library')
    drop.write_text('old override')
    events=[];checked=preload._checked
    def check(ctx,c,cmd,**kw):
        if cmd=='systemctl stop '+preload.SERVICE:
            events.append('stop');return ''
        return checked(ctx,c,cmd,**kw)
    monkeypatch.setattr(preload,'_checked',check)
    def restart(*args, **kwargs):
        events.append('restart')
        journals=list(home.glob('preload-stage-*/publication.json'))
        assert len(journals)==1
        journals[0].unlink()
        raise deploy.DeployError('candidate failed readiness')
    monkeypatch.setattr(preload,'_restart',restart)
    def backend(**kwargs):pytest.fail('restored backend after unconfirmed preload restore')
    ctx.rollback_backend=backend
    with pytest.raises(deploy.DeployError,match='rollback/service recovery unconfirmed'):
        preload.install(ctx)
    assert events==['restart','stop']
    assert backend.blocked
    assert list(home.glob('preload-stage-*'))


def test_process_loss_recovery_restores_preload_then_backend_then_restarts(tmp_path,monkeypatch):
    from install_journal import Journal
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    old=home/'lib/libwmp_openace-compat.so';old.parent.mkdir();old.write_bytes(b'previous library')
    drop.write_bytes(b'previous override')
    journal=Journal(tmp_path/'installer.json')
    journal.create('printer','test',['config','preload'])
    journal.begin('config');journal.complete_component('config',{'kind':'test-backend'})
    journal.begin('preload');ctx.rollback_backend=NS(journal=journal);ctx.host='printer'
    def lost(*args, repair_markers=False, **kwargs):
        assert repair_markers is True
        raise SystemExit('installer lost before restart acknowledgement')
    monkeypatch.setattr(preload,'_restart',lost)
    with pytest.raises(SystemExit):preload.install(ctx)
    saved=Journal(journal.path).load('printer','test')
    assert saved.recovery_receipts()[0][0]=='preload'
    stage=Path(saved.recovery_receipts()[0][1]['stage'])
    assert (stage/'publication.json').is_file()
    events=[];checked=preload._checked
    def check(ctx,c,cmd,**kwargs):
        if cmd=='systemctl stop '+preload.SERVICE:
            events.append('stop');return ''
        return checked(ctx,c,cmd,**kwargs)
    monkeypatch.setattr(preload,'_checked',check)
    def backend(ctx,receipt):
        assert old.read_bytes()==b'previous library' and drop.read_bytes()==b'previous override'
        assert events==['stop'];events.append('backend')
    monkeypatch.setattr(deploy.REGISTRY['config'],'rollback',backend)
    def restart(*args, **kwargs):
        assert events[-1]=='backend';events.append('restart failed')
        raise deploy.DeployError('readiness failed')
    monkeypatch.setattr(preload,'_restart',restart)
    with pytest.raises(deploy.DeployError,match='readiness failed'):
        deploy.recover_installation(ctx,journal.path)
    saved=Journal(journal.path).load('printer','test')
    assert saved.value['recovery_restart_required'] and not saved.recovery_receipts()
    monkeypatch.setattr(preload,'_restart',lambda *args, **kwargs:events.append('restart ready'))
    deploy.recover_installation(ctx,journal.path)
    assert events==['stop','backend','restart failed','restart ready']
    assert Journal(journal.path).load('printer','test').value['state']=='restored'
    assert stage.is_dir()


def test_killed_staging_has_recoverable_receipt_without_publication(tmp_path, monkeypatch):
    """Kill a real installer process during upload, before any installed write."""
    import os, signal, sys
    from install_journal import Journal
    home=tmp_path/'home';home.mkdir()
    source=tmp_path/'source.c';source.write_text('int test(void){return 1;}')
    script=r'''
import os,signal,sys,subprocess
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,sys.argv[1])
from components import preload
from install_journal import Journal
home=Path(sys.argv[2]);source=Path(sys.argv[3]);journal=Journal(home/'install.json')
journal.acquire();journal.create('printer','test',['preload']);journal.begin('preload')
preload.screen_bundle=lambda:None
preload._home=lambda ctx:str(home)
preload.sources=lambda:[('test',str(source))]
preload._checked=lambda ctx,c,cmd,**kw:subprocess.check_output(['bash','-c',cmd],text=True).strip()
def die(*args):os.kill(os.getpid(),signal.SIGKILL)
ctx=NS(ssh=lambda:None,sftp=lambda:NS(put=die),rollback_backend=NS(journal=journal))
preload.install(ctx)
'''
    killed=subprocess.run([sys.executable,'-c',script,str(ROOT/'tools'),str(home),str(source)],capture_output=True,timeout=15)
    assert killed.returncode == -signal.SIGKILL, killed.stderr.decode()
    journal=Journal(home/'install.json');journal.acquire()
    try:
        journal.load('printer','test')
        receipts=journal.recovery_receipts()
        assert receipts[0][1]['phase']=='staging'
        stage=Path(receipts[0][1]['stage'])
        assert not (stage/'publication.json').exists()
        monkeypatch.setattr(preload,'_home',lambda ctx:str(home))
        def helper(ctx,c,body,**kwargs):
            exec(body,{'Path':Path})
        monkeypatch.setattr(preload,'_helper',helper)
        monkeypatch.setattr(preload,'_checked',lambda *args,**kwargs:pytest.fail('unpublished stage stopped service'))
        preload.rollback(NS(ssh=lambda:None,DeployError=deploy.DeployError),receipts[0][1])
    finally:journal.release()


@pytest.mark.parametrize('phase,journal_file', [('staging',True),('publication',False),(None,False),('unknown',False)])
def test_staging_recovery_never_hides_ambiguous_publication(tmp_path,monkeypatch,phase,journal_file):
    home=tmp_path/'home';stage=home/'preload-stage-test';stage.mkdir(parents=True)
    if journal_file:(stage/'publication.json').write_text('[]')
    receipt={'kind':'preload-stage','stage':str(stage)}
    if phase is not None:receipt['phase']=phase
    monkeypatch.setattr(preload,'_home',lambda ctx:str(home))
    monkeypatch.setattr(preload,'_helper',lambda ctx,c,body,**kw:exec(body,{'Path':Path}))
    monkeypatch.setattr(preload,'_checked',lambda *args,**kwargs:pytest.fail('ambiguous phase stopped service'))
    with pytest.raises((AssertionError,deploy.DeployError)):
        preload.rollback(NS(ssh=lambda:None,DeployError=deploy.DeployError),receipt)


def test_publication_intent_is_durable_before_remote_publication(tmp_path,monkeypatch):
    from install_journal import Journal,decode
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    journal=Journal(home/'install.json');journal.create('printer','test',['preload']);journal.begin('preload')
    ctx.rollback_backend=NS(journal=journal)
    original=preload._helper
    observed=[]
    def checked(ctx,c,body,**kwargs):
        phase=decode(Journal(journal.path).load('printer','test').value['prepared_receipt'])['phase']
        if 'publish_stage(' in body:
            assert phase=='publication'
            observed.append('publication')
        elif not observed:
            assert phase=='staging'
        return original(ctx,c,body,**kwargs)
    monkeypatch.setattr(preload,'_helper',checked)
    receipt=preload.install(ctx)
    assert observed==['publication'] and receipt['phase']=='publication'


def test_recovery_environment_uses_active_material_path(tmp_path):
    import preload_bundle as pb
    config = tmp_path/'printer_data/config'
    config.mkdir(parents=True)
    (config/'printer.cfg').write_text('[include material.cfg]\n')
    (config/'material.cfg').write_text('[wm_material]\nini_path: ~/custom profiles/tmt1.ini\n')
    assert pb.recovery_environment(tmp_path) == {
        'WMP_RECOVERY_JOB_PATH': str(tmp_path/'custom profiles/wmp_recovery_job.json'),
        'WMP_RECOVERY_JOB_REQUIRED': '1'}
    (config/'material.cfg').write_text('[wm_material]\nini_path: relative.ini\n')
    with pytest.raises(ValueError, match='absolute'):
        pb.recovery_environment(tmp_path)
    (config/'material.cfg').write_text('[printer]\nkinematics: corexy\n')
    assert pb.recovery_environment(tmp_path) == {}


def test_recovery_environment_is_published_and_rolled_back(tmp_path):
    import preload_bundle as pb
    stage=tmp_path/'stage';stage.mkdir();lib=tmp_path/'lib';drop=tmp_path/'override'
    drop.write_text('previous configuration')
    (stage/'test.so').write_bytes(b'test')
    (stage/'outputs.json').write_text(json.dumps({'libwmp_recovery-fix.so':
        dict(file='test.so',sha256=pb.digest(stage/'test.so'))}))
    pb.publish_stage(stage,lib,drop,{'WMP_RECOVERY_JOB_PATH':'/home/test/50% profiles/job.json',
                                   'WMP_RECOVERY_JOB_REQUIRED':'1',
                                   'WMP_RELEASE_IDENTITY':'r4@12345678'})
    assert 'Environment="WMP_RECOVERY_JOB_PATH=/home/test/50%% profiles/job.json"' in drop.read_text()
    assert 'Environment="WMP_RECOVERY_JOB_REQUIRED=1"' in drop.read_text()
    assert 'Environment="WMP_RELEASE_IDENTITY=r4@12345678"' in drop.read_text()
    pb.restore_publication(stage)
    assert drop.read_text() == 'previous configuration'


def test_missing_recovery_configuration_fails_before_publication(tmp_path, monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch)
    (home/'printer_data/config/printer.cfg').unlink()
    with pytest.raises(deploy.DeployError, match='printer.cfg'):
        preload.install(ctx)
    assert not drop.exists() and not restarts
    assert not any('print(json.dumps(publish_stage(' in command for command in commands)
    assert not any('restore_publication(' in command.splitlines()[-1] for command in commands)


def test_defaults_service_and_owner_contract_roll_back_together(tmp_path):
    import preload_bundle as pb
    stage = tmp_path / 'stage'
    stage.mkdir()
    (stage / 'test.so').write_bytes(b'test')
    (stage / 'factory_defaults.py').write_bytes(b'# staged helper\n')
    (stage / 'outputs.json').write_text(json.dumps({'libwmp_openace-compat.so':
        dict(file='test.so', sha256=pb.digest(stage / 'test.so'))}))
    helper, backend, screen = (tmp_path / n for n in ('helper.py', 'backend.conf', 'screen.conf'))
    helper.write_bytes(b'old helper')
    backend.write_bytes(b'old backend override')
    paths = {'helper': str(helper), 'dropin': str(backend), 'home': str(tmp_path)}
    pb.publish_stage(stage, tmp_path / 'lib', screen, start_backend=True, defaults_paths=paths)
    assert helper.read_bytes() == b'# staged helper\n'
    assert 'ExecStartPre=/usr/bin/python3' in backend.read_text()
    assert 'WMP_DEFAULTS_OWNER=1' in screen.read_text()
    pb.restore_publication(stage)
    assert helper.read_bytes() == b'old helper'
    assert backend.read_bytes() == b'old backend override'
    assert not screen.exists()
