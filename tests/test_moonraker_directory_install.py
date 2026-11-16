"""Restart admission uses present print activity and process continuity."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from moonraker_directory_install import MoonrakerService


def request(path):
    if path == '/printer/info':
        return {'state': 'ready', 'process_id': 1234}
    if path == '/server/info':
        return {'klippy_connected': True}
    assert path == '/printer/objects/query?print_stats&pause_resume&virtual_sdcard'
    return {'status': {'print_stats': {'state': 'standby'},
                       'pause_resume': {'is_paused': False},
                       'virtual_sdcard': {'is_active': False}}}


@pytest.mark.parametrize('field,value', [('job', 'printing'), ('job', 'paused'),
                                        ('pause', True), ('sd', True), ('job', 'unknown')])
def test_active_printer_is_refused(field, value):
    def changed(path):
        data = request(path)
        if 'status' in data:
            status = data['status']
            if field == 'job': status['print_stats']['state'] = value
            elif field == 'pause': status['pause_resume']['is_paused'] = value
            else: status['virtual_sdcard']['is_active'] = value
        return data
    with pytest.raises(ValueError, match='idle and not paused'):
        MoonrakerService(request=changed).inspect()


@pytest.mark.parametrize('material', [None, {}, {'available': True},
    {'session_id': 'old', 'toolhead_operation': {'state': 'unknown'}},
    {'filament_operation': {'state': 'failed', 'recovered': False}}])
def test_material_schema_and_history_do_not_reserve_moonraker(material):
    def changed(path):
        data = request(path)
        if 'status' in data: data['status']['wm_material'] = material
        return data
    service = MoonrakerService(request=changed)
    baseline = service.inspect()
    service.request = request
    service.verify(baseline)
    assert 'material' not in baseline


@pytest.mark.parametrize('state', ['error', 'shutdown'])
def test_backend_error_allows_repair_without_object_query(state):
    def changed(path):
        if path == '/server/info': return {'klippy_connected': True}
        assert path == '/printer/info'
        return {'state': state, 'process_id': 1234}
    service = MoonrakerService(request=changed)
    service.verify(service.inspect())


def test_stop_requires_inactive_and_no_pid():
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='ActiveState=active\nMainPID=123\n')
    service = MoonrakerService(request=request, run=run)
    with pytest.raises(RuntimeError, match='stop is unconfirmed'):
        service.stop()
    assert all('moonraker.service' in args for args in calls)


def test_restart_requires_same_backend_process():
    service = MoonrakerService(request=request)
    baseline = service.inspect()
    service.verify(baseline)
    with pytest.raises(RuntimeError, match='identity changed'):
        service.verify(dict(baseline, process_id=999))


@pytest.mark.parametrize('active,pid,loaded,allowed', [
    ('inactive', '0', 'loaded', True), ('failed', '0', 'loaded', True),
    ('active', '123', 'loaded', False), ('inactive', '123', 'loaded', False),
    ('inactive', '0', 'not-found', False), ('activating', '0', 'loaded', False)])
def test_http_unavailable_requires_positive_stopped_service(active, pid, loaded, allowed):
    def offline(path): raise OSError('offline')
    commands = []
    def run(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(stdout='LoadState=%s\nActiveState=%s\nMainPID=%s\n' % (loaded, active, pid))
    service = MoonrakerService(request=offline, run=run)
    if allowed: assert service.inspect() == {'process_id': 0, 'stopped': True}
    else:
        with pytest.raises(ValueError, match='not confirmed stopped'): service.inspect()
    assert all(args[:2] == ['systemctl', 'show'] for args in commands)


def test_stopped_backend_is_not_proof_moonraker_restarted():
    clock = [0]
    def unavailable(path): raise OSError('temporarily disconnected')
    def sleep(seconds): clock[0] += seconds
    def run(args, **kwargs):
        assert args[:2] == ['systemctl', 'show']
        return SimpleNamespace(stdout='LoadState=loaded\nActiveState=inactive\nMainPID=0\n')
    service = MoonrakerService(request=unavailable, run=run, sleep=sleep, clock=lambda: clock[0])
    baseline = service.inspect()
    with pytest.raises(RuntimeError, match='deadline'): service.verify(baseline)
    assert clock[0] == 90


def test_stopped_backend_repair_verifies_moonraker_returned():
    def stopped(path):
        if path == '/server/info': return {'klippy_connected': False}
        raise OSError('Klipper stopped')
    def run(args, **kwargs):
        return SimpleNamespace(stdout='LoadState=loaded\nActiveState=inactive\nMainPID=0\n')
    service = MoonrakerService(request=stopped, run=run)
    service.verify(service.inspect())


def test_http_cli_uses_independent_target_and_refuses_directory_receipt(tmp_path):
    from moonraker_directory_install import main
    home = tmp_path / 'printer'
    components = home / 'moonraker/moonraker/components'
    components.mkdir(parents=True)
    fixtures = Path(__file__).parent / 'fixtures'
    app = components / 'application.py'
    app.write_bytes((fixtures / 'moonraker_http_error_compat.py').read_bytes())
    manager = components / 'file_manager/file_manager.py'
    manager.parent.mkdir()
    manager.write_bytes((fixtures / 'moonraker_directory_compat.py').read_bytes())
    python = home / 'moonraker-env/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    directory_state, http_state = tmp_path / 'directory', tmp_path / 'http'
    main(['prepare', '--home', str(home), '--state', str(directory_state)])
    main(['prepare', '--patch', 'http-error', '--home', str(home), '--state', str(http_state)])
    import json
    assert json.loads((http_state / 'receipt.json').read_text())['target'] == str(app)
    assert json.loads((directory_state / 'receipt.json').read_text())['target'] == str(manager)
    # A caller cannot accidentally use the existing directory undo plan for HTTP.
    with pytest.raises(SystemExit) as error:
        main(['prepare', '--patch', 'http-error', '--home', str(home), '--state', str(directory_state)])
    assert error.value.code == 1
    assert app.read_bytes() == (fixtures / 'moonraker_http_error_compat.py').read_bytes()
    assert manager.read_bytes() == (fixtures / 'moonraker_directory_compat.py').read_bytes()



def test_legacy_restart_receipt_does_not_require_old_filament_metadata():
    service = MoonrakerService(request=request)
    baseline = service.inspect()
    baseline['material'] = {'session_id': 'previous', 'attachment': {'head': 'h0'}}
    service.verify(baseline)
