"""Read-only native activation checks; no printer or service is operated."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_deploy import deploy
from components import preload

BUNDLE = {'profile': {'sha256': 'client'}, 'artifact': {'sha256': 'library'}}


def observation():
    return {'pid': 123, 'mapped': True, 'client_sha256': 'client',
            'library_sha256': 'library', 'now_ms': 10000,
            'facts': {'gui': '0', 'worker': '0', 'bootstrap': '11', 'errno_or_rc': '0', 'timer_matches': '1', 'refresh': '8', 'status_polls': '2', 'at_ms': '9000',
                      'status_received_at': '8500'}}


def test_running_native_screen_is_accepted():
    preload._check_screen_observation(observation(), BUNDLE)


def test_poll_reply_newer_than_gui_sample_is_still_current():
    current = observation()
    current['facts']['status_received_at'] = '9500'
    preload._check_screen_observation(current, BUNDLE)


@pytest.mark.parametrize('received', ['10001', '0'])
def test_reply_must_be_current_at_observation_time(received):
    current = observation()
    current['now_ms'] = 10001 if received == '0' else 10000
    current['facts']['status_received_at'] = received
    with pytest.raises(ValueError, match='stale'):
        preload._check_screen_observation(current, BUNDLE)


@pytest.mark.parametrize('key,value', [('pid', 0), ('pid', True), ('mapped', False),
    ('client_sha256', 'different'), ('library_sha256', 'different'), ('now_ms', 25001)])
def test_wrong_process_artifact_or_old_sample_refused(key, value):
    current = observation(); current[key] = value
    with pytest.raises(ValueError):
        preload._check_screen_observation(current, BUNDLE)


@pytest.mark.parametrize('key,value', [('bootstrap', '2'), ('errno_or_rc', '1'),
    ('timer_matches', '0'), ('refresh', '0'), ('status_polls', '0'),
    ('status_received_at', '-1'), ('at_ms', '11000'), ('bootstrap', 'broken')])
def test_unstarted_or_stale_native_paths_refused(key, value):
    current = observation(); current['facts'][key] = value
    with pytest.raises(ValueError):
        preload._check_screen_observation(current, BUNDLE)


def test_wait_observes_without_restarting(monkeypatch):
    clock = [0]; calls = []
    monkeypatch.setattr(preload.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(preload.time, 'sleep', lambda s: clock.__setitem__(0, clock[0]+s))
    def checked(ctx, connection, command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise deploy.DeployError('diagnostic log not created yet')
        return json.dumps(observation())
    monkeypatch.setattr(preload, '_checked', checked)
    ctx = SimpleNamespace(user='printer', ssh=lambda: None, DeployError=deploy.DeployError)
    preload._verify_running_screen(ctx, BUNDLE)
    assert clock[0] == 2 and len(calls) == 2
    assert all('systemctl' not in command for command in calls)
    monkeypatch.setattr(preload, '_checked', lambda *a, **k: json.dumps(dict(observation(), mapped=False)))
    with pytest.raises(deploy.DeployError, match='activation unconfirmed'):
        preload._verify_running_screen(ctx, BUNDLE)
    assert clock[0] == 48


def test_observer_reads_real_process_maps_and_diagnostics(tmp_path):
    # Observe this child interpreter with real /proc maps/inodes/executable.
    # Substitute only process discovery and the disposable diagnostic location.
    setup = '''
import os,time,json,hashlib,subprocess
from pathlib import Path
subprocess.check_output=lambda *a,**k:str(os.getpid())
library=next(line.split(None,5)[5] for line in Path('/proc/self/maps').read_text().splitlines()
             if len(line.split(None,5))==6 and 'libc.so' in line)
log=Path(LOGDIR)/('wmp_openace_screen_'+str(os.getpid())+'.log')
now=int(time.monotonic()*1000)
log.write_text('bootstrap=11 errno_or_rc=0 timer_matches=1 refresh=8 status_polls=2 at_ms=%d status_received_at=%d\\n'%(now,now))
'''.replace('LOGDIR', repr(str(tmp_path)))
    code = preload.SCREEN_OBSERVATION.replace('LIBRARY', 'library').replace("'/tmp/wmp_openace_screen_'", repr(str(tmp_path)+'/wmp_openace_screen_'))
    result = subprocess.run([sys.executable, '-I', '-'], input=setup+code,
                            text=True, capture_output=True, check=True)
    value = json.loads(result.stdout)
    assert value['mapped'] is True
    assert value['client_sha256'] and value['library_sha256']
    preload._check_screen_observation(value, {'profile': {'sha256': value['client_sha256']},
                                            'artifact': {'sha256': value['library_sha256']}})


@pytest.mark.parametrize('state', ['ready', 'stale', 'unmapped', 'missing'])
def test_status_uses_one_current_observation_without_wait_or_restart(monkeypatch, state):
    calls=[]
    def observe(ctx):
        calls.append('observe')
        if state=='missing':raise OSError('diagnostic unavailable')
        value=observation()
        if state=='stale':value['now_ms']=30000
        if state=='unmapped':value['mapped']=False
        return value
    monkeypatch.setattr(preload,'_observe_running_screen',observe)
    monkeypatch.setattr(preload.time,'sleep',lambda seconds:pytest.fail('status waited'))
    ctx=SimpleNamespace(DeployError=deploy.DeployError)
    text=preload._native_screen_status(ctx,BUNDLE)
    assert calls==['observe']
    if state=='ready':assert 'verified for pid 123' in text and 'unconfirmed' not in text
    else:assert 'unconfirmed' in text


def test_current_status_does_not_consult_retired_compat_log(monkeypatch, capsys):
    queries=[]
    def run(connection, command, **kwargs):
        queries.append(command)
        if command=='pidof client':return '123\n','',0
        return '', '', 0
    monkeypatch.setattr(preload,'run',run)
    monkeypatch.setattr(preload,'screen_bundle',lambda:dict(BUNDLE,scope='packaging-control-only'))
    monkeypatch.setattr(preload.preload_bundle,'bundle_relative',lambda root:preload.preload_bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(preload,'_helper',lambda *args,**kwargs:'library')
    monkeypatch.setattr(preload,'_observe_running_screen',lambda ctx:observation())
    preload.status(SimpleNamespace(ssh=lambda:None,user='printer',DeployError=deploy.DeployError))
    text=capsys.readouterr().out
    native=next(line for line in text.splitlines() if line.startswith('native-screen:'))
    assert 'installed artifact matches sealed bundle' in native
    assert 'native GUI and status synchronization verified for pid 123' in native
    assert 'unconfirmed' not in native
    assert not any('wmp_openace_compat.log' in command for command in queries)
