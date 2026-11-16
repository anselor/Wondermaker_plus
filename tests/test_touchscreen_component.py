"""Installer routing into the transactional path; no SSH or system commands."""
import json
import subprocess
import sys
from types import SimpleNamespace
import pytest
from test_deploy import deploy
from components import touchscreen
import preflight


def test_inline_transaction_modules_load_without_repository_imports():
    script=touchscreen.transaction_code('restore',None,'/opt/wondermaker_plus-transactions/test.json')
    script=script.replace("result = sys.modules['touchscreen_runtime'].execute(",
        "sys.modules['touchscreen_runtime'].execute = lambda *args: {'arguments': args}\nresult = sys.modules['touchscreen_runtime'].execute(")
    result=subprocess.run([sys.executable,'-I','-'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['arguments']==['restore',None,'/opt/wondermaker_plus-transactions/test.json']


def test_install_returns_receipt_and_rollback_uses_same_journal(monkeypatch):
    calls=[]
    monkeypatch.setattr(touchscreen,'upload',lambda client:'/tmp/unique-stage')
    monkeypatch.setattr(touchscreen,'run',lambda *a,**kw:pytest.fail('legacy install script called'))
    def code(action,source,journal):
        calls.append((action,source,journal));return action
    monkeypatch.setattr(touchscreen,'transaction_code',code)
    def remote(ctx,code,**kwargs):
        assert kwargs=={'sudo':True,'quiet':True}
        return json.dumps({'state':'applied' if code=='install' else 'restored','journal':calls[-1][2]})
    monkeypatch.setattr(preflight,'remote',remote)
    ctx=SimpleNamespace(ssh=lambda:None,DeployError=deploy.DeployError)
    receipt=touchscreen.install(ctx)
    touchscreen.rollback(ctx,receipt)
    assert calls[0][:2]==('install','/tmp/unique-stage')
    assert calls[1]==('restore',None,calls[0][2])


def test_lost_install_reply_reports_known_journal(monkeypatch):
    monkeypatch.setattr(touchscreen,'upload',lambda client:'/tmp/stage')
    def fail(*args,**kwargs):raise OSError('connection lost')
    monkeypatch.setattr(preflight,'remote',fail)
    ctx=SimpleNamespace(ssh=lambda:None,DeployError=deploy.DeployError)
    with pytest.raises(deploy.DeployError,match='/opt/wondermaker_plus-transactions/'):
        touchscreen.install(ctx)


def test_lost_process_recovers_touchscreen_from_prepared_installer_receipt(tmp_path,monkeypatch):
    from install_journal import Journal
    journal=Journal(tmp_path/'install.json')
    journal.create('printer','user',['touchscreen']);journal.begin('touchscreen')
    ctx=SimpleNamespace(host='printer',user='user',ssh=lambda:None,
        DeployError=deploy.DeployError,printing_now=lambda:False,
        rollback_backend=SimpleNamespace(journal=journal))
    monkeypatch.setattr(touchscreen,'upload',lambda client:'/tmp/stage')
    monkeypatch.setattr(touchscreen,'transaction_code',lambda action,source,path:(action,path))
    calls=[]
    def remote(ctx,command,**kwargs):
        action,path=command;calls.append(action)
        saved=Journal(journal.path).load('printer','user')
        assert saved.recovery_receipts()==[('touchscreen',{'kind':'touchscreen-transaction','journal':path})]
        if action=='install':raise SystemExit('installer process lost')
        return json.dumps({'state':'restored','journal':path})
    monkeypatch.setattr(preflight,'remote',remote)
    with pytest.raises(SystemExit):touchscreen.install(ctx)
    deploy.recover_installation(ctx,journal.path)
    assert calls==['install','restore']
    assert Journal(journal.path).load('printer','user').value['state']=='restored'


def test_touchscreen_checkpoint_failure_prevents_remote_activation(tmp_path,monkeypatch):
    from install_journal import Journal
    journal=Journal(tmp_path/'install.json')
    journal.create('printer','user',['touchscreen']);journal.begin('touchscreen')
    ctx=SimpleNamespace(ssh=lambda:None,rollback_backend=SimpleNamespace(journal=journal))
    monkeypatch.setattr(touchscreen,'upload',lambda client:'/tmp/stage')
    def fail():raise OSError('checkpoint unavailable')
    monkeypatch.setattr(journal,'save',fail)
    monkeypatch.setattr(preflight,'remote',lambda *a,**kw:pytest.fail('activated without recovery checkpoint'))
    with pytest.raises(OSError,match='checkpoint unavailable'):touchscreen.install(ctx)
