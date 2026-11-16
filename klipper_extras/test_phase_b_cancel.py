"""Cancellation remains available without diagnostic storage or unsafe travel."""
import pytest

pytest_plugins = ['test_wm_material']


def test_nested_cancel_retires_inner_and_outer_macro_tails(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    dispatcher.run_script_from_command = lambda script: vendor.GCodeDispatch.run_script_from_command(dispatcher, script)
    dispatcher.gcode_handlers['INNER'] = lambda command: dispatcher.run_script_from_command('CANCEL_PRINT\nG1 X99')
    dispatcher.gcode_handlers['OUTER'] = lambda command: dispatcher.run_script_from_command('INNER\nM104 S250')
    with pytest.raises(vendor.CommandError, match='remaining macro commands retired'):
        dispatcher.run_script('OUTER\nG1 X100')
    assert objects['virtual_sdcard'].must_pause_work
    assert material._print_cancel['state'] == 'pending'
    assert not set(events).intersection({'move', 'heat', 'stock-cancel'})
    # The retained SD error callback may submit CANCEL_PRINT again; same-job
    # cancellation coalesces rather than becoming a second cleanup operation.
    request = material._print_cancel['id']
    dispatcher.run_script('CANCEL_PRINT')
    assert material._print_cancel['id'] == request


def test_fast_fence_dispatches_only_original_commands(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    dispatcher.gcode_handlers['WMP_CHECK_SCRIPT_GENERATION'] = lambda command: pytest.fail('synthetic guard dispatched')
    dispatcher.run_script('G1 X1\n; comment\nG1 X2')
    assert events == ['move', 'move']


@pytest.mark.parametrize('script', [
    'M118 Idle timeout, all heaters off\nSET_HEATER_TEMPERATURE HEATER=extruder TARGET=0\nSET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=0',
    'M104 S0\nM140 S0',
    'TURN_OFF_HEATERS\nRESPOND MSG="Cooling"',
])
def test_live_cancel_allows_multiline_cooling(guarded_legacy_dispatch, script):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material = fixture[0]
    material._print_cancel = {'state': 'pending'}
    for name in ('M118', 'RESPOND', 'SET_HEATER_TEMPERATURE', 'M104', 'M140'):
        dispatcher.gcode_handlers[name] = lambda command: events.append(command.get_command())
    dispatcher.run_script(script)
    assert len(events) == len(script.splitlines())


@pytest.mark.parametrize('tail', ['G1 X5', 'M104 S200', 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=200',
    'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0 TARGET=200'])
def test_cooling_does_not_authorize_movement_or_heating_tail(guarded_legacy_dispatch, tail):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    fixture[0]._print_cancel = {'state': 'pending'}
    with pytest.raises(vendor.CommandError, match='invalidated'):
        dispatcher.run_script('TURN_OFF_HEATERS\n' + tail)
    assert events == []


def test_diagnostic_disk_failure_still_closes_job_and_clears_pause(managed_cancel_intent, monkeypatch):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    original = material._write_recovery_json
    def fail_receipt(path, value):
        if path == material._print_cancel_path():
            assert objects['virtual_sdcard'].must_pause_work
            raise OSError('diagnostic disk full')
        original(path, value)
    monkeypatch.setattr(material, '_write_recovery_json', fail_receipt)
    material._begin_print_cancel('disk-full-stop', binding)
    worker = timers[-1]
    locked[0] = False
    worker.callback(1.)
    assert material._print_cancel['state'] == 'complete'
    assert material._print_cancel['persistence_error'] == 'diagnostic disk full'
    assert binding['handle'].closed and objects['virtual_sdcard'].current_file is None
    assert not objects['pause_resume'].get_status(1)['is_paused']
    assert all(states[name]['target'] == 0 for name in objects['heaters'].get_all_heaters())
    before = list(cleanup)
    worker.callback(2.)
    assert cleanup == before


def test_partial_cleanup_retires_work_queued_during_stop(guarded_legacy_dispatch, monkeypatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, states, calls, review, request, timers, body, locked = fixture
    locked[0] = False
    dispatcher.run_script('CANCEL_PRINT')
    def fail_cleanup(*args): raise ValueError('physical drain failed')
    monkeypatch.setattr(material, '_cancel_print_cleanup', fail_cleanup)
    waiting[0] = lambda: timers[-1].callback(2.)
    with pytest.raises(vendor.CommandError, match='invalidated'):
        dispatcher.run_script('G1 X5')
    assert material._print_cancel['state'] == 'unknown'
    assert 'move' not in events
    events.clear()
    dispatcher.run_script('G1 X5')  # Fresh explicit action; historical result is not a lock.
    assert events == ['move']


def test_nonmotion_housekeeping_is_restored_without_travel(managed_cancel_cleanup):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material = fixture[0]
    material._cancel_print_cleanup(binding)
    for command in ('M107', 'BED_MESH_CLEAR', 'M220 S100', 'RESET_FLOW_EXTRUDER',
                    'SET_VELOCITY_LIMIT VELOCITY=500 ACCEL=10000', 'SET_IDLE_TIMEOUT TIMEOUT=600',
                    '_WMP_CASE_LIGHT_PRINT_END'):
        assert command in cleanup
    assert not any(command.startswith('SAVE_VARIABLE') for command in cleanup)
    assert 'M84' not in cleanup
    assert not set(command.split()[0] for command in cleanup).intersection(
        {'G0', 'G1', 'G28', 'E_axis_move', 'WIPE_NOZZLE', 'PARK_CURRENT_TOOL'})


def test_cancel_receipt_cache_cannot_disable_stop(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material = fixture[0]
    material._print_cancel_requests = {'previous-%d' % n for n in range(1024)}
    material._begin_print_cancel('fresh-stop', binding)
    assert material._print_cancel['state'] == 'pending'
    assert len(material._print_cancel_requests) <= 1024


def test_cancel_completes_after_retained_sd_error_unwind(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    sd, stats = objects['virtual_sdcard'], objects['print_stats']
    reactor, gcode = material.printer.get_reactor(), objects['gcode']
    failure = 'Command invalidated by cancellation or restart; review again'
    dispatched = []
    def dispatch(line):
        dispatched.append(line)
        material._begin_print_cancel('screen-stop-during-command', binding)
        if line != 'CANCEL_PRINT':
            raise gcode.error(failure)
        # Retained SD on_error submits Cancel again; it coalesces the same job.
    gcode.run_script = dispatch
    locked[0] = False
    sd.do_resume()
    original_worker(reactor.monotonic())
    assert dispatched == ['G1 X2', 'CANCEL_PRINT']
    assert stats.state == 'error' and stats.print_start_time is None
    assert sd.current_file is binding['handle'] and not binding['handle'].closed
    assert not sd.is_active() and not sd.is_cmd_from_sd()

    timers[-1].callback(reactor.monotonic())  # Deferred command-owned cleanup.
    assert material._print_cancel['state'] == 'complete'
    assert {'name': 'cancelling', 'state': 'complete'} in material._print_cancel['stages']
    assert sd.current_file is None and binding['handle'].closed
    assert not sd.is_active() and not sd.is_cmd_from_sd()
    assert not objects['pause_resume'].get_status(1)['is_paused']
    assert stats.state == 'error' and stats.error_message == failure
    assert not set(command.split()[0] for command in cleanup).intersection(
        {'G0', 'G1', 'G28', 'PARK_CURRENT_TOOL', 'UNLOCK', 'LOCK'})


@pytest.mark.parametrize('changed', ['active', 'sd-command', 'replacement', 'printing'])
def test_error_label_does_not_substitute_for_confirmed_sd_stop(managed_cancel_cleanup, changed):
    from io import StringIO
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, locked = fixture
    sd, stats = objects['virtual_sdcard'], objects['print_stats']
    stats.note_error('original print failure')
    original = sd.do_cancel
    replacement = StringIO('G1 X99\n')
    def cancel():
        original()
        if changed == 'active': sd.work_timer = object()
        elif changed == 'sd-command': sd.cmd_from_sd = True
        elif changed == 'replacement': sd.current_file = replacement
        else: stats.state = 'printing'
    sd.do_cancel = cancel
    phases = []
    with pytest.raises(ValueError):
        material._cancel_print_cleanup(binding, lambda *stage: phases.append(stage))
    assert ('cancelling', 'complete') not in phases
    assert ('cancelling', 'failed') in phases
    if changed == 'replacement':
        assert sd.current_file is replacement and not replacement.closed


def test_cancel_resolution_can_finish_original_open_error_file(interrupted_print_cancel):
    from test_wm_material import cancel_resolution_review, confirm_cancel_resolution
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    objects['print_stats'].note_error('cancel interrupted a tool change')
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'finish_cleanup' and not cleanup
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert binding['handle'].closed and objects['virtual_sdcard'].current_file is None
    assert material._print_cancel['state'] == 'complete'
    assert objects['print_stats'].state == 'error'


@pytest.mark.parametrize('change', ['none', 'different-file', 'missing-binding', 'active'])
def test_cancel_resolution_reads_closed_error_only_with_original_binding(interrupted_print_cancel, change):
    from test_wm_material import cancel_resolution_review, confirm_cancel_resolution
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    objects['print_stats'].note_error('cancel interrupted a tool change')
    locked[0] = True
    material._cancel_print_cleanup(binding)
    locked[0] = False
    cleanup.clear()
    if change == 'different-file': objects['print_stats'].filename = 'new-job.gcode'
    elif change == 'missing-binding': material._print_cancel_live_binding = None
    elif change == 'active': objects['virtual_sdcard'].work_timer = object()
    if change != 'none':
        with pytest.raises(ValueError): cancel_resolution_review(material)
        assert not cleanup
        return
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'acknowledge_complete' and not cleanup
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert not cleanup and material._print_cancel['state'] == 'complete'


def test_cancel_resolution_read_refresh_reuses_exact_live_ticket(interrupted_print_cancel):
    from test_wm_material import cancel_resolution_review
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    first = cancel_resolution_review(material)
    expiry = material._print_cancel_resolution_tickets[first['id']]['expires']
    for _ in range(10):
        assert cancel_resolution_review(material) == first
    assert len(material._print_cancel_resolution_tickets) == 1
    assert material._print_cancel_resolution_tickets[first['id']]['expires'] == expiry
    assert not cleanup and not binding['handle'].closed
    states['extruder2']['target'] += 1
    with pytest.raises(ValueError, match='evidence changed'):
        cancel_resolution_review(material)
    assert not cleanup


def test_cancel_resolution_prunes_expired_and_used_without_reviving_token(interrupted_print_cancel):
    from test_wm_material import cancel_resolution_review, confirm_cancel_resolution
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    old = cancel_resolution_review(material)
    original = material._print_cancel_resolution_tickets[old['id']]
    original['expires'] = 0.
    for i in range(1024):
        material._print_cancel_resolution_tickets['previous-%d' % i] = dict(
            original, used=bool(i % 2), expires=1e30 if i % 2 else 0.)
    fresh = cancel_resolution_review(material)  # Same ID, new authority token.
    assert fresh['token'] != old['token']
    assert len(material._print_cancel_resolution_tickets) == 1
    assert not cleanup and not binding['handle'].closed
    locked[0] = True
    with pytest.raises(ValueError, match='stale, changed or already used'):
        confirm_cancel_resolution(material, old)
    assert not cleanup and not binding['handle'].closed
    confirm_cancel_resolution(material, fresh)
    assert material._print_cancel['state'] == 'complete'


@pytest.mark.parametrize('reopen', [False, True])
def test_cancel_review_expiry_never_exhausts_or_revives_old_token(managed_cancel_intent, reopen):
    import io
    from test_wm_material import print_cancel_review, CancelWebRequest
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    before = len(timers)
    first = print_cancel_review(material, binding)
    for number in range(1026):
        material._print_cancel_tickets[first['id']]['expires'] = 0.
        latest = print_cancel_review(material, binding)
        assert latest['token'] != first['token']
        assert len(material._print_cancel_tickets) == 1
    if reopen:
        objects['virtual_sdcard'].current_file = io.StringIO('reopened same filename')
        material._print_cancel_tickets[first['id']]['expires'] = 0.
        latest = print_cancel_review(material, binding)
    with pytest.raises(ValueError, match='stale, changed or already used'):
        material._handle_print_cancel(CancelWebRequest(**first))
    assert not cleanup and len(timers) == before
    assert not material._print_cancel_unresolved()
    material._handle_print_cancel(CancelWebRequest(**latest))
    assert len(timers) == before + 1


def test_cancel_review_prunes_consumed_tokens_but_preserves_execution_fence(managed_cancel_intent):
    from test_wm_material import print_cancel_review, CancelWebRequest
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    old = print_cancel_review(material, binding)
    material._print_cancel_tickets[old['id']]['used'] = True
    material._print_cancel_requests = {old['id']}
    before = len(timers)
    with pytest.raises(ValueError, match='already attempted'):
        print_cancel_review(material, binding)
    assert not material._print_cancel_tickets
    fresh = print_cancel_review(material, binding, request_id='fresh')
    assert len(material._print_cancel_tickets) == 1
    with pytest.raises(ValueError, match='stale, changed or already used'):
        material._handle_print_cancel(CancelWebRequest(**old))
    assert not cleanup and len(timers) == before
    assert not material._print_cancel_unresolved()


def test_cancel_review_capacity_counts_only_live_reviews(managed_cancel_intent):
    from test_wm_material import print_cancel_review
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    before = len(timers)
    for number in range(1024):
        print_cancel_review(material, binding, request_id='live-' + str(number))
    with pytest.raises(ValueError, match='live cancellation reviews; wait for them to expire'):
        print_cancel_review(material, binding, request_id='overflow')
    material._print_cancel_tickets['live-0']['expires'] = 0.
    print_cancel_review(material, binding, request_id='overflow')
    assert len(material._print_cancel_tickets) == 1024
    assert not cleanup and len(timers) == before
