"""Pre-SD progress and Stop bind an admitted start, never an older open job."""
import copy
from types import SimpleNamespace as NS
import pytest
from test_wm_material import material, print_material, start_command, CancelWebRequest


@pytest.fixture
def pending(print_material):
    obj, objects, request, path = print_material
    objects['webhooks'] = NS(get_status=lambda now: {'state': 'ready'})
    obj.printer.is_shutdown = lambda: False
    obj._command_generation = 0
    submission = dict(id=request['id'], session=obj.session_id, file=path.name, state='pending')
    obj.print_submission = submission
    return obj, objects, request, path, submission


def review(pending, identity='pending-stop'):
    obj, objects, request, path, submission = pending
    web = CancelWebRequest(id=identity, session=obj.session_id, file=path.name, start=submission['id'])
    obj._handle_print_cancel_review(web)
    return web.response['request']


def test_pending_review_is_read_only_and_stop_retires_dispatch_generation(pending):
    obj, objects, request, path, submission = pending
    before = list(objects['gcode'].scripts)
    original = copy.deepcopy(submission)
    reviewed = review(pending)
    assert review(pending) == reviewed
    assert obj._command_generation == 0 and submission == original
    assert objects['gcode'].scripts == before
    web = CancelWebRequest(**reviewed)
    obj._handle_print_cancel(web)
    assert web.response['state'] == 'complete'
    assert web.response['stop_point']['phase'] == 'file_preparation'
    assert obj._command_generation == 1 and submission['state'] == 'not_started'
    assert objects['gcode'].scripts == before
    assert all(stage['state'] == 'complete' for stage in web.response['stages'])
    with pytest.raises(ValueError, match='was used'):
        obj._handle_print_cancel(CancelWebRequest(**reviewed))
    # A completed pre-SD receipt remains a valid, nonblocking durable record.
    obj._cancellation()._restore_print_cancel()
    assert obj._print_cancel['state'] == 'complete'
    assert not obj._print_cancel_active()


@pytest.mark.parametrize('change', ['generation', 'start', 'replacement', 'session', 'file', 'active', 'handle', 'owner', 'shutdown', 'expired'])
def test_pending_stop_rejects_replaced_or_changed_attempt(pending, change):
    obj, objects, request, path, submission = pending
    reviewed = review(pending)
    if change == 'generation': obj._command_generation += 1
    elif change == 'start': submission['id'] = 'another-start'
    elif change == 'replacement': obj.print_submission = dict(submission)
    elif change == 'session': obj.session_id = 'new-session'
    elif change == 'file': submission['file'] = 'another.gcode'
    elif change == 'active': objects['virtual_sdcard'].active = True
    elif change == 'handle': objects['virtual_sdcard'].current_file = object()
    elif change == 'owner': objects['openace'] = object()
    elif change == 'shutdown': obj.printer.is_shutdown = lambda: True
    elif change == 'expired': obj.printer.monotonic = lambda: 100.
    generation = obj._command_generation
    before = list(objects['gcode'].scripts)
    with pytest.raises(ValueError): obj._handle_print_cancel(CancelWebRequest(**reviewed))
    assert obj._command_generation == generation
    assert objects['gcode'].scripts == before
    assert not getattr(obj._cancellation(), '_print_cancel', {})


def test_stop_during_preparation_prevents_sd_dispatch_and_progress_closes(print_material):
    obj, objects, request, path = print_material
    objects['webhooks'] = NS(get_status=lambda now: {'state': 'ready'})
    obj.printer.is_shutdown = lambda: False
    obj._command_generation = 0
    def stop(*unused):
        progress = obj._print_preparation().get_status(1.)
        assert progress['active'] and progress['phase'] == 'file'
        assert progress['file_progress']['total'] == path.stat().st_size
        web = CancelWebRequest(id='stop-before-sd', session=obj.session_id, file=path.name, start=request['id'])
        obj._handle_print_cancel_review(web)
        obj._handle_print_cancel(CancelWebRequest(**web.response['request']))
        assert not obj._print_preparation().get_status(1.)['active']
    obj._recovery_jobs()._stage_recovery_job = stop
    with pytest.raises(ValueError, match='retired during preparation'):
        obj.cmd_START_PRINT(start_command(request))
    assert obj.print_submission['state'] == 'not_started'
    assert obj.print_submission['error'] == 'Cancelled by user'
    assert not any('SDCARD_PRINT_FILE' in line for line in objects['gcode'].scripts)
    assert not any(line.startswith(('G28', 'M109', 'SET_HEATER_TEMPERATURE')) for line in objects['gcode'].scripts)


def test_real_cooperative_scan_stop_aborts_before_sd_or_staged_evidence(print_material):
    obj, objects, request, path = print_material
    objects['webhooks'] = NS(get_status=lambda now: {'state': 'ready'})
    obj.printer.is_shutdown = lambda: False
    obj._command_generation = 0
    path.write_bytes(b'G1 X1 Y1\n' * 10000)
    request['file'].update(size=path.stat().st_size, modified=path.stat().st_mtime)
    stops = []
    def pause(when):
        if not stops:
            web = CancelWebRequest(id='scan-stop', session=obj.session_id, file=path.name, start=request['id'])
            obj._handle_print_cancel_review(web)
            obj._handle_print_cancel(CancelWebRequest(**web.response['request']))
            stops.append(web.response)
        return when
    obj.printer.pause = pause
    with pytest.raises(ValueError, match='retired during preparation'):
        obj.cmd_START_PRINT(start_command(request))
    assert len(stops) == 1 and obj._print_cancel['state'] == 'complete'
    assert obj.print_submission['state'] == 'not_started'
    assert not any('SDCARD_PRINT_FILE' in script for script in objects['gcode'].scripts)
    assert obj._read_recovery_job()['state'] != 'staged'


def test_ordinary_stop_can_retire_the_current_pending_start(pending):
    obj, objects, request, path, submission = pending
    receipt = obj._print_service().cancel_current_pending_start()
    assert receipt['state'] == 'complete' and receipt['file'] == path.name
    assert obj._command_generation == 1 and submission['state'] == 'not_started'
    assert obj._print_service().cancel_current_pending_start() is None
    assert not objects['gcode'].scripts
