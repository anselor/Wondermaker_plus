"""Guard activation must be established before installation can restart Klipper."""
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_head_guard as guard
from components import ORDER, preload


class DeployError(RuntimeError):
    pass


def test_dependencies_are_uploaded_before_preload_activation():
    assert ORDER.index('config') < ORDER.index('preload')
    assert ORDER.index('material') < ORDER.index('preload')
    assert ORDER.index('preload') < ORDER.index('touchscreen')


def test_entry_addresses_come_from_the_actual_guard_profiles():
    source = (ROOT / 'client-preload/head-config-guard/wmp_head_config_guard.c').read_text()
    assert guard.guard_profiles(source) == {
        '1.1.08': 0x633c70, '1.1.12': 0x633fd8, '1.1.13': 0x633fc4}
    with pytest.raises(ValueError, match='profiles are missing'):
        guard.guard_profiles('')


@pytest.fixture
def live(tmp_path):
    home = tmp_path / 'home'
    library = home / 'wmp/lib/libwmp_head-config-guard.so'
    library.parent.mkdir(parents=True)
    library.write_bytes(b'installed guard')
    client = home / 'TM_T1/bin/client'
    client.parent.mkdir(parents=True)
    client.write_bytes(b'vendor client')
    proc = tmp_path / 'proc/123'
    proc.mkdir(parents=True)
    (proc / 'exe').symlink_to(client)
    (proc / 'stat').write_text('123 (client) ' + ' '.join(['0'] * 19 + ['456']))
    (proc / 'environ').write_bytes(b'WMP_REQUIRE_HEAD_CONFIG_GUARD=1\0')
    entry, target = 0x1000, 0x8020
    with (proc / 'mem').open('wb') as memory:
        memory.seek(entry)
        memory.write(struct.pack('<IIQ', 0x58000050, 0xd61f0200, target))
    metadata = library.stat()
    device = '%02x:%02x' % (os.major(metadata.st_dev), os.minor(metadata.st_dev))
    mapping = '8000-9000 r-xp 0 %s %s %s\n' % (device, metadata.st_ino, library)
    (proc / 'maps').write_text(mapping)
    log = tmp_path / 'guard.log'
    log.write_text('[pid 123] client 1.1.13: destructive head reset blocked; communication faults keep Klipper stopped\n')
    def verify():
        return guard.verify_once(str(home), {'1.1.13': entry},
                                 proc_root=proc.parent, log_path=log)
    return NS(home=home, proc=proc, library=library, log=log, verify=verify)


def test_live_callback_and_current_library_are_verified(live):
    assert live.verify() == {'pid': 123, 'version': '1.1.13'}


@pytest.mark.parametrize('defect', [
    'stale-log', 'unpatched-entry', 'wrong-target', 'nonexecutable',
    'replaced-library', 'deleted-library', 'not-required', 'multiple-clients'])
def test_logs_or_loaded_library_alone_cannot_pass_verification(live, defect):
    if defect == 'stale-log':
        live.log.write_text(live.log.read_text().replace('[pid 123]', '[pid 122]'))
    elif defect == 'unpatched-entry':
        with (live.proc / 'mem').open('r+b') as memory:
            memory.seek(0x1000); memory.write(b'\0' * 16)
    elif defect == 'wrong-target':
        with (live.proc / 'mem').open('r+b') as memory:
            memory.seek(0x1008); memory.write(struct.pack('<Q', 0xa000))
    elif defect == 'nonexecutable':
        path = live.proc / 'maps'; path.write_text(path.read_text().replace('r-xp', 'r--p'))
    elif defect == 'replaced-library':
        replacement = live.library.with_suffix('.new')
        replacement.write_bytes(b'new guard'); replacement.replace(live.library)
    elif defect == 'deleted-library':
        path = live.proc / 'maps'; path.write_text(path.read_text().rstrip() + ' (deleted)\n')
    elif defect == 'not-required':
        (live.proc / 'environ').write_bytes(b'')
    else:
        other = live.proc.parent / '124'; other.mkdir()
        (other / 'exe').symlink_to(live.home / 'TM_T1/bin/client')
    with pytest.raises(guard.GuardNotReady):
        live.verify()


def test_activation_wait_allows_startup_but_never_restarts(monkeypatch):
    calls = []
    def verify(*args):
        calls.append('check')
        if len(calls) == 1:
            raise FileNotFoundError('client is starting')
        return {'pid': 123}
    monkeypatch.setattr(guard, 'verify_once', verify)
    monkeypatch.setattr(guard.time, 'sleep', lambda delay: None)
    assert guard.wait_for_guard('home', {}) == {'pid': 123}
    assert calls == ['check', 'check']
    monkeypatch.setattr(guard, 'verify_once', lambda *a: (_ for _ in ()).throw(guard.GuardNotReady('unprotected')))
    with pytest.raises(RuntimeError, match='unprotected'):
        guard.wait_for_guard('home', {}, timeout=0)


def test_remote_verifier_is_self_contained(monkeypatch):
    import preflight
    scripts = []
    def capture(ctx, code, sudo=False):
        compile(code, '<guard verification>', 'exec')
        scripts.append((code, sudo))
    monkeypatch.setattr(preflight, 'remote', capture)
    preload.verify_guard(NS(user='test'))
    assert scripts[0][1] is True
    assert "wait_for_guard('/home/test'," in scripts[0][0]


@pytest.mark.parametrize('failure', [None, 'build', 'guard', 'print'])
def test_install_publishes_libraries_atomically_and_requires_guard(monkeypatch, failure):
    events = []
    ctx = NS(user='test', ssh=lambda: None, printing_now=lambda: failure == 'print',
             wait_for_backend=lambda: events.append('backend settled'), sftp=lambda: NS(put=lambda *a: None), DeployError=DeployError)
    monkeypatch.setattr(preload, 'sources', lambda: [('head-config-guard', '/source/guard.c')])
    def run(c, cmd, **kwargs):
        events.append(cmd)
        if cmd.startswith('gcc '):
            assert '.so.wmp-upload-' in cmd
            if failure == 'build':
                return '', 'compiler error', 1
        return '', '', 0
    monkeypatch.setattr(preload, 'run', run)
    monkeypatch.setattr(preload, '_write_dropin', lambda *a: events.append('override') or 'libs')
    monkeypatch.setattr(preload, '_restart', lambda *a: events.append('screen restart'))
    def verify(ctx):
        events.append('guard check')
        if failure == 'guard':
            raise DeployError('unprotected')
    monkeypatch.setattr(preload, 'verify_guard', verify)
    monkeypatch.setattr(preload, 'status', lambda *a: events.append('status'))
    if failure:
        with pytest.raises(DeployError):
            preload.install(ctx)
        assert 'status' not in events
        assert 'backend settled' not in events
        if failure in ('build', 'print'):
            assert 'screen restart' not in events
        if failure == 'build':
            assert not any(e.startswith('mv ') for e in events)
    else:
        preload.install(ctx)
        assert events[-5:] == ['override', 'screen restart', 'guard check', 'backend settled', 'status']
        assert any(e.startswith('mv ') and '.so.wmp-upload-' in e for e in events)


def test_override_requires_the_guard_on_every_screen_start(monkeypatch):
    commands = []
    def run(c, cmd, **kwargs):
        commands.append(cmd)
        return ('/home/test/wmp/lib/libwmp_head-config-guard.so\n' if cmd.startswith('ls ') else '', '', 0)
    monkeypatch.setattr(preload, 'run', run)
    preload._write_dropin(NS(user='test', DeployError=DeployError), None)
    assert 'WMP_REQUIRE_HEAD_CONFIG_GUARD=1' in commands[-1]
    monkeypatch.setattr(preload, 'run', lambda *a, **k: ('/home/test/wmp/lib/libwmp_wifi-fix.so', '', 0))
    with pytest.raises(DeployError, match='missing'):
        preload._write_dropin(NS(user='test', DeployError=DeployError), None)


@pytest.mark.parametrize('disabled', [False, True])
def test_required_guard_prevents_unprotected_vendor_startup(tmp_path, disabled):
    import shutil
    if not shutil.which('gcc'):
        pytest.skip('gcc required')
    source = ROOT / 'client-preload/head-config-guard/wmp_head_config_guard.c'
    library = tmp_path / 'guard.so'
    client_source = tmp_path / 'client.c'
    client_source.write_text('#include <stdio.h>\nint main(void) { puts("vendor startup"); return 0; }\n')
    client = tmp_path / 'client'
    subprocess.run(['gcc', '-shared', '-fPIC', str(source), '-o', str(library)], check=True)
    subprocess.run(['gcc', str(client_source), '-o', str(client)], check=True)
    env = dict(os.environ, LD_PRELOAD=str(library), WMP_REQUIRE_HEAD_CONFIG_GUARD='1')
    env.pop('WMP_HEAD_CONFIG_GUARD_DISABLE', None)
    if disabled:
        env['WMP_HEAD_CONFIG_GUARD_DISABLE'] = '1'
    # This executable is intentionally unsupported. Its main must never run.
    result = subprocess.run([str(client)], env=env, capture_output=True, text=True)
    assert result.returncode == 78 and 'vendor startup' not in result.stdout
    env.pop('WMP_REQUIRE_HEAD_CONFIG_GUARD')
    result = subprocess.run([str(client)], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and 'vendor startup' in result.stdout


def test_failed_service_restart_is_not_hidden_by_old_active_service(monkeypatch):
    commands = []
    def run(c, cmd, **kwargs):
        commands.append(cmd)
        return '', 'systemd error', 1
    monkeypatch.setattr(preload, 'run', run)
    with pytest.raises(DeployError, match='systemd error'):
        preload._restart(NS(DeployError=DeployError), None)
    assert len(commands) == 1


def test_failed_override_write_stops_before_screen_restart(monkeypatch):
    def run(c, cmd, **kwargs):
        if cmd.startswith('ls '):
            return '/home/test/wmp/lib/libwmp_head-config-guard.so', '', 0
        return '', 'read-only filesystem', 1
    monkeypatch.setattr(preload, 'run', run)
    with pytest.raises(DeployError, match='screen restart blocked'):
        preload._write_dropin(NS(user='test', DeployError=DeployError), None)
