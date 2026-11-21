"""Execute the read-only factory verification script with modeled /proc/API."""
import hashlib,io,json,os,time,subprocess,urllib.request
from pathlib import Path
import pytest
from test_deploy import deploy
import verify_factory_state as verify


def inspect(tmp_path,monkeypatch,fault=None):
    root=tmp_path/'klipper/klippy';(root/'chelper').mkdir(parents=True)
    files={}
    for name in ('toolhead.py','chelper/kin_shaper.c'):
        path=root/name;path.write_bytes(b'factory source\n');os.utime(path,(time.time()-3,)*2)
        files[name]=hashlib.sha256(path.read_bytes()).hexdigest()
    helper=root/'chelper/c_helper.so';helper.write_bytes(b'compiled helper')
    client=tmp_path/'TM_T1/bin/client';client.parent.mkdir(parents=True);client.write_bytes(b'stock client')
    manifest={'version':1,'source':'test firmware fixture','files':files,
              'stock_client_sha256':hashlib.sha256(client.read_bytes()).hexdigest()}
    if fault=='source':(root/'toolhead.py').write_bytes(b'modified source')
    if fault=='helper':os.utime(helper,(time.time()-10,)*2)
    if fault=='missing_helper':helper.unlink()
    settings={'printer':{'kinematics':'corexy'}}
    if fault=='config':settings['wm_material']={}
    if fault=='saved_mesh':settings['bed_mesh wmp_print']={'points':'0.01, 0.02'}
    if fault=='callback':settings['filament_switch_sensor custom']={'runout_gcode':'WMP_STOP'}
    status={'webhooks':{'state':'ready'},'configfile':{'settings':settings},
            'print_stats':{'state':'standby'},'pause_resume':{'is_paused':False},'virtual_sdcard':{'is_active':False}}
    def request(url,timeout):
        assert url.startswith('http://127.0.0.1:7125/printer/objects/query?')
        return io.BytesIO(json.dumps({'result':{'status':status}}).encode())
    monkeypatch.setattr(urllib.request,'urlopen',request)
    commands=[]
    def command(args,text):
        commands.append(args)
        assert args[0:2]==['systemctl','show']
        assert args[-2:]==['--property=MainPID','--value']
        return '123' if args[2]=='klipper.service' else '456'
    monkeypatch.setattr(subprocess,'check_output',command)
    original=Path.read_text
    def read(path,*args,**kwargs):
        if str(path)=='/proc/123/maps':
            inode=helper.stat().st_ino if helper.exists() else 0
            return '0-1 r-xp 0000 00:00 '+str(inode)+' '+str(helper)+(' (deleted)' if fault=='mapping' else '')
        if str(path)=='/proc/456/maps':return 'libwmp_test.so' if fault=='screen' else 'stock screen mapping'
        if str(path)=='/proc/123/stat':
            fields=['S']+['0']*18+[str((990 if fault=='restart' else 999)*os.sysconf('SC_CLK_TCK'))]
            return '123 (python) '+' '.join(fields)
        if str(path)=='/proc/uptime':return '1000 0'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    import contextlib
    output=io.StringIO()
    with contextlib.redirect_stdout(output):exec(verify.inspection_script(manifest,str(tmp_path)),{})
    assert len(commands)==2  # No G-code or mutating system command.
    return json.loads(output.getvalue())


def test_verified_factory_sources_and_live_helper(tmp_path,monkeypatch):
    assert inspect(tmp_path,monkeypatch)['verified']


def test_saved_mesh_is_preserved_user_data(tmp_path,monkeypatch):
    assert inspect(tmp_path,monkeypatch,'saved_mesh')['verified']


def test_executable_callback_is_still_rejected(tmp_path,monkeypatch):
    assert not inspect(tmp_path,monkeypatch,'callback')['verified']


@pytest.mark.parametrize('fault',['source','helper','missing_helper','config','mapping','screen','restart'])
def test_factory_claim_refused_when_any_layer_differs(tmp_path,monkeypatch,fault):
    assert not inspect(tmp_path,monkeypatch,fault)['verified']


@pytest.mark.parametrize('name',['../../outside.py','/outside.py','command.sh'])
def test_manifest_cannot_expand_inspection_to_arbitrary_paths(name):
    with pytest.raises(ValueError,match='Unsafe factory'):
        verify.inspection_script({'version':1,'files':{name:'a'*64}},'/home/printer')
