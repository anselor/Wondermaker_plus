"""Retained backend ACCEPT outcomes; command success/inactive is not acceptance."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/manual_probe.py'


@pytest.fixture
def manual():
    if not VENDOR.exists():
        pytest.skip('retained vendor manual_probe required')
    # Pin source, including original line endings, before executing its methods.
    assert hashlib.sha256(VENDOR.read_bytes()).hexdigest() == 'c39c45bee5109437b201f299c4463a129dafa5dfd36a259a9f44950e1ef0383c'
    spec = importlib.util.spec_from_file_location('retained_manual_probe', VENDOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    status = module.ManualProbe.__new__(module.ManualProbe)
    status.status = {'is_active': True}
    helper = module.ManualProbeHelper.__new__(module.ManualProbeHelper)
    helper.manual_probe = status
    helper.start_position = [10., 20., 5., 0.]
    position = [10., 20., 4., 0.]
    helper.toolhead = NS(get_position=lambda: list(position))
    helper.get_kinematics_pos = lambda: list(position[:3])
    removed, finalized, messages = [], [], []
    helper.gcode = NS(register_command=lambda name, callback: removed.append((name, callback)))
    helper.finalize_callback = lambda value: finalized.append(value)
    return NS(helper=helper, status=status, position=position, removed=removed,
              finalized=finalized, messages=messages, command=NS(respond_info=messages.append))


@pytest.mark.parametrize('position', [[11.,20.,4.,0.], [10.,21.,4.,0.],
                                      [10.,20.,5.,0.], [10.,20.,6.,0.]])
def test_accept_refusal_returns_normally_and_closes_probe(manual, position):
    manual.position[:] = position
    assert manual.helper.cmd_ACCEPT(manual.command) is None
    assert manual.status.get_status(0)['is_active'] is False
    assert manual.finalized == [None]
    assert manual.messages and 'failed' in manual.messages[0]
    assert manual.removed == [(name, None) for name in ('ACCEPT','NEXT','ABORT','TESTZ')]


def test_accepted_probe_delivers_position_to_finalizer(manual):
    assert manual.helper.cmd_ACCEPT(manual.command) is None
    assert manual.status.get_status(0)['is_active'] is False
    assert manual.finalized == [[10.,20.,4.]]
    assert manual.messages == []


def test_abort_has_same_inactive_status_without_accepted_position(manual):
    manual.helper.cmd_ABORT(manual.command)
    assert manual.status.get_status(0)['is_active'] is False
    assert manual.finalized == [None]


def test_finalizer_error_occurs_after_probe_status_is_cleared(manual):
    def fail(position):
        assert position == [10.,20.,4.]
        assert manual.status.get_status(0)['is_active'] is False
        raise RuntimeError('pending config update failed')
    manual.helper.finalize_callback = fail
    with pytest.raises(RuntimeError, match='pending config update failed'):
        manual.helper.cmd_ACCEPT(manual.command)
    assert manual.status.get_status(0)['is_active'] is False
    assert manual.removed == [(name, None) for name in ('ACCEPT','NEXT','ABORT','TESTZ')]


@pytest.fixture
def receipt(manual):
    path = ROOT / 'klipper_extras/wmp_recovery.py'
    spec = importlib.util.spec_from_file_location('receipt_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    binding = ['session-a', manual.helper]
    value = module.ProbeEditorReceipt('session-a', manual.helper, lambda: tuple(binding))
    return value, binding


def test_receipt_requires_successful_vendor_finalize_before_one_save(manual, receipt):
    value, _ = receipt
    calls = []
    with pytest.raises(ValueError, match='editing'):
        value.save(value.session, value.token, lambda: None, lambda: calls.append('write'))
    manual.helper.cmd_ACCEPT(manual.command)
    assert value.state == 'accepted' and value.position == (10.,20.,4.)
    value.save(value.session, value.token, lambda: calls.append('admit'), lambda: calls.append('write'))
    assert calls == ['admit', 'write'] and value.state == 'saved'
    with pytest.raises(ValueError, match='saved'):
        value.save(value.session, value.token, lambda: None, lambda: calls.append('duplicate'))
    assert calls == ['admit', 'write']


@pytest.mark.parametrize('action', ['refuse', 'abort'])
def test_receipt_cannot_save_vendor_nonacceptance(manual, receipt, action):
    value, _ = receipt
    if action == 'refuse':
        manual.position[2] = 5.
        manual.helper.cmd_ACCEPT(manual.command)
    else:
        manual.helper.cmd_ABORT(manual.command)
    assert value.state == 'aborted'
    with pytest.raises(ValueError, match='aborted'):
        value.save(value.session, value.token, lambda: None, lambda: pytest.fail('must not save'))


@pytest.mark.parametrize('change', ['session', 'helper', 'callback'])
def test_receipt_binding_change_blocks_original_finalizer(manual, receipt, change):
    value, binding = receipt
    if change == 'session': binding[0] = 'session-b'
    elif change == 'helper': binding[1] = object()
    else: manual.helper.finalize_callback = lambda _: None
    with pytest.raises(ValueError, match='session changed'):
        value.callback([10.,20.,4.])
    assert not manual.finalized and value.state == 'invalidated'


def test_unknown_save_is_not_replayed(manual, receipt):
    value, _ = receipt
    manual.helper.cmd_ACCEPT(manual.command)
    calls = []
    def persist():
        calls.append('write')
        raise OSError('lost completion')
    with pytest.raises(OSError):
        value.save(value.session, value.token, lambda: None, persist)
    assert value.state == 'unknown'
    with pytest.raises(ValueError, match='unknown'):
        value.save(value.session, value.token, lambda: None, persist)
    assert calls == ['write']


def test_changed_binding_during_admission_blocks_write(manual, receipt):
    value, binding = receipt
    manual.helper.cmd_ACCEPT(manual.command)
    with pytest.raises(ValueError, match='session changed'):
        value.save(value.session, value.token, lambda: binding.__setitem__(0, 'new'),
                   lambda: pytest.fail('must not save'))


def test_finalizer_exception_never_creates_accepted_receipt(manual):
    path = ROOT / 'klipper_extras/wmp_recovery.py'
    spec = importlib.util.spec_from_file_location('receipt_failure', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def fail(_): raise RuntimeError('config set failed')
    manual.helper.finalize_callback = fail
    value = module.ProbeEditorReceipt('s', manual.helper, lambda: ('s', manual.helper))
    with pytest.raises(RuntimeError, match='config set failed'):
        manual.helper.cmd_ACCEPT(manual.command)
    assert value.state == 'failed' and value.position is None


@pytest.mark.parametrize('position', [[1.,2.,float('nan')], [1.,2.], [1.,2.,True]])
def test_malformed_position_cannot_reach_calibration_finalizer(manual, receipt, position):
    value, _ = receipt
    with pytest.raises(ValueError, match='Invalid accepted'):
        value.callback(position)
    assert value.state == 'failed' and not manual.finalized


def test_stale_save_token_and_close_do_not_dispatch(manual, receipt):
    value, _ = receipt
    manual.helper.cmd_ACCEPT(manual.command)
    for session, token in [('old', value.token), (value.session, 'old')]:
        with pytest.raises(ValueError, match='Stale'):
            value.save(session, token, lambda: pytest.fail('admission'), lambda: pytest.fail('write'))
    value.invalidate()
    with pytest.raises(ValueError, match='invalidated'):
        value.save(value.session, value.token, lambda: pytest.fail('admission'), lambda: pytest.fail('write'))


@pytest.fixture
def preparation(manual):
    path = ROOT / 'klipper_extras/wmp_recovery.py'
    spec = importlib.util.spec_from_file_location('receipt_preparation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    handlers = {}
    def register(name, callback, **kwargs):
        if callback is None:
            return handlers.pop(name, None)
        if name in handlers:
            raise ValueError('already registered')
        # Match vendor wrapping: the published handler has no __self__.
        handlers[name] = lambda command: callback(command)
    gcode = NS(register_command=register, ready_gcode_handlers=handlers)
    manual.helper.gcode = gcode
    def probe_calibrate_finalize(position):
        manual.finalized.append(position)
    probe_calibrate_finalize.__self__ = NS(name='probe')
    manual.helper.finalize_callback = probe_calibrate_finalize
    def prepare():
        gcode.register_command('ACCEPT', 'dummy')
        gcode.register_command('ACCEPT', None)
        gcode.register_command('ACCEPT', manual.helper.cmd_ACCEPT)
    return module.ProbeEditorReceipt, gcode, prepare, register


def test_preparation_captures_helper_before_vendor_lambda_and_tracks_replacement(manual, preparation):
    cls, gcode, prepare, register = preparation
    value = cls.prepare('s', gcode, lambda: 's', lambda: None, prepare)
    assert gcode.register_command is register
    assert getattr(gcode.ready_gcode_handlers['ACCEPT'], '__self__', None) is None
    gcode.ready_gcode_handlers['ACCEPT'](manual.command)
    assert value.state == 'accepted' and manual.finalized == [[10.,20.,4.]]
    gcode.register_command('ACCEPT', lambda cmd: None)
    with pytest.raises(ValueError, match='session changed'):
        value.save('s', value.token, lambda: None, lambda: pytest.fail('stale save'))


@pytest.mark.parametrize('fault', ['admission', 'missing', 'exception', 'preexisting'])
def test_preparation_failure_restores_registration_without_receipt(manual, preparation, fault):
    cls, gcode, prepare, register = preparation
    calls = []
    if fault == 'preexisting': gcode.register_command('ACCEPT', lambda cmd: None)
    def admit():
        if fault == 'admission': raise ValueError('busy')
    def run():
        calls.append('prepare')
        if fault == 'missing': return
        prepare()
        raise ValueError('preparation failed')
    with pytest.raises(ValueError):
        cls.prepare('s', gcode, lambda: 's', admit, run)
    assert gcode.register_command is register
    if fault in ('admission', 'preexisting'): assert calls == []


def test_completed_later_probe_invalidates_old_accepted_receipt(manual, receipt):
    value, _ = receipt
    manual.helper.cmd_ACCEPT(manual.command)
    assert value.state == 'accepted'
    # A later helper resets the shared status on completion, even if ACCEPT
    # has already been unregistered again before this old editor saves.
    manual.status.reset_status()
    with pytest.raises(ValueError, match='session changed'):
        value.save(value.session, value.token, lambda: None, lambda: pytest.fail('stale write'))


@pytest.fixture
def editor(manual, preparation, tmp_path, monkeypatch):
    _, gcode, prepare, _ = preparation
    spec = importlib.util.spec_from_file_location('editor_owner', ROOT / 'klipper_extras/wmp_recovery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sent, admitted = [], []
    material = NS(_restart_requested=lambda _, **kw: admitted.append(kw['probe_editor']))
    import configparser
    config = NS(autosave=NS(fileconfig=configparser.RawConfigParser()),
                status_save_pending={}, save_config_pending=False)
    manual.status.status = {'is_active': False}
    original_finalize = manual.helper.finalize_callback
    def probe_calibrate_finalize(position):
        original_finalize(position)
        if position is not None:
            config.autosave.fileconfig.add_section('probe')
            config.autosave.fileconfig.set('probe', 'z_offset', '1.500')
            config.status_save_pending = {'probe': {'z_offset':'1.500'}}
            config.save_config_pending = True
    probe_calibrate_finalize.__self__ = NS(name='probe')
    manual.helper.finalize_callback = probe_calibrate_finalize
    endpoints = {}
    webhooks = NS(register_endpoint=lambda name, callback: endpoints.setdefault(name, callback), endpoints=endpoints)
    objects = {'wm_material': material, 'configfile': config, 'webhooks': webhooks,
               'toolhead': NS(wait_moves=lambda: sent.append('drain')), 'manual_probe': manual.status}
    path = tmp_path / 'printer.cfg'
    path.write_text('[printer]\nkinematics = cartesian\n')
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_start_args=lambda: {'config_file': str(path)})
    calibration = NS(printer=printer, gcode=gcode, session='c'*32, active=False,
                     failure='', _saving=False, _check=lambda command, fresh_action=False: None)
    def run(command):
        sent.append(command)
        if command == '_WMP_PROBE_CALIBRATE':
            manual.status.status = {'is_active': True}
            prepare()
        elif command == 'ACCEPT': manual.helper.cmd_ACCEPT(manual.command)
        elif command == 'ABORT': manual.helper.cmd_ABORT(manual.command)
        elif command.startswith('TESTZ Z='): manual.position[2] += float(command.split('=')[1])
        elif command == 'SAVE_CONFIG':
            assert calibration.active and calibration._saving
            gcode.request_restart('firmware_restart')
        else: pytest.fail('unexpected command ' + command)
    gcode.request_restart = lambda result: None
    gcode.run_script_from_command = run
    actor = object()
    monkeypatch.setattr(module.ProbeEditorCommands, '_current_actor', staticmethod(lambda: actor))
    value = module.ProbeEditorCommands(calibration)
    calibration.probe_editor = value
    def command(action, sequence, **overrides):
        fields = dict(SESSION='c'*32, REQUEST='a'*32, ACTION=action, SEQ=sequence,
                      TOKEN=value.receipt.token if value.receipt and action != 'BEGIN' else '')
        fields.update(overrides)
        return NS(get=lambda key, default: fields.get(key, default),
                  get_int=lambda key, **kwargs: int(fields[key]), error=ValueError)
    return value, command, sent, material


def test_editor_lifecycle_deduplicates_motion_and_save(editor):
    value, command, sent, _ = editor
    begin = command('BEGIN', 0)
    value.cmd_run(begin); value.cmd_run(begin)
    assert value.state == 'editing' and value.busy()
    jog = command('JOG', 1, Z='-0.1')
    value.cmd_run(jog); value.cmd_run(jog)
    accept = command('ACCEPT', 2)
    value.cmd_run(accept); value.cmd_run(accept)
    assert value.state == 'accepted'
    save = command('SAVE', 3)
    value.cmd_run(save); value.cmd_run(save)
    assert value.state == 'saved' and not value.busy()
    assert value.get_status()['save_review_required']
    assert sent == ['_WMP_PROBE_CALIBRATE', 'TESTZ Z=-0.1', 'ACCEPT', 'SAVE_CONFIG']
    for _ in range(5): value.get_status()
    assert len(sent) == 4


@pytest.mark.parametrize('overrides', [dict(SESSION='old'), dict(REQUEST='b'*32),
                                     dict(TOKEN='wrong'), dict(SEQ=4), dict(Z='10')])
def test_editor_rejects_stale_or_unsupported_jog_before_motion(editor, overrides):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    fields = dict(Z='-0.1'); fields.update(overrides)
    with pytest.raises(ValueError): value.cmd_run(command('JOG', 1, **fields))
    assert sent == ['_WMP_PROBE_CALIBRATE']


def test_editor_abort_remains_available_when_admission_is_held(editor):
    value, command, sent, material = editor
    value.cmd_run(command('BEGIN', 0))
    def refuse(*args, **kwargs): raise ValueError('busy')
    material._restart_requested = refuse
    with pytest.raises(ValueError, match='busy'): value.cmd_run(command('JOG', 1, Z='-0.1'))
    assert value.get_status()['action_refused'] and value.sequence == 1
    value.cmd_run(command('ABORT', 2))
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ABORT']
    assert value.state == 'aborted' and not value.busy()


def test_editor_refused_accept_cannot_save(manual, editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    manual.position[2] = 5.
    value.cmd_run(command('ACCEPT', 1))
    assert value.state == 'aborted'
    with pytest.raises(ValueError): value.cmd_run(command('SAVE', 2))
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ACCEPT']


def test_failed_jog_is_unknown_and_only_abort_can_continue(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    original = value.gcode.run_script_from_command
    def fail(text):
        if text.startswith('TESTZ'):
            sent.append(text)
            raise ValueError('movement failed')
        original(text)
    value.gcode.run_script_from_command = fail
    jog = command('JOG', 1, Z='-0.1')
    with pytest.raises(ValueError, match='movement failed'): value.cmd_run(jog)
    assert value.state == 'unknown'
    value.cmd_run(jog)  # same request reports existing state, never moves again
    with pytest.raises(ValueError, match='Resolve'): value.cmd_run(command('JOG', 2, Z='-0.1'))
    value.cmd_run(command('ABORT', 2))
    assert sent == ['_WMP_PROBE_CALIBRATE', 'TESTZ Z=-0.1', 'ABORT']


def test_editor_discards_accepted_offset_without_restart_or_unrelated_loss(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    config = value.printer.lookup_object('configfile')
    config.status_save_pending['extruder'] = {'pid_kp':'25'}
    save = command('SAVE', 2)
    class CommandError(Exception):
        pass
    save.error = CommandError
    with pytest.raises(CommandError, match='Other pending'):
        value.cmd_run(save)
    assert value.state == 'accepted'
    assert value.get_status()['action_refused'] and value.sequence == 2
    discard = command('DISCARD', 3)
    value.cmd_run(discard); value.cmd_run(discard)
    assert value.state == 'discarded' and not value.busy()
    assert config.status_save_pending == {'extruder':{'pid_kp':'25'}}
    assert not config.autosave.fileconfig.has_section('probe')
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ACCEPT']


def test_editor_conflicting_discard_retains_both_evidence_and_changed_offset(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    config = value.printer.lookup_object('configfile')
    config.autosave.fileconfig.set('probe','z_offset','2.000')
    config.status_save_pending['probe']['z_offset'] = '2.000'
    with pytest.raises(ValueError, match='changed'):
        value.cmd_run(command('DISCARD', 2))
    assert value.state == 'accepted' and not value.busy()
    assert value.get_status()['action_refused'] and value.sequence == 2
    assert config.status_save_pending == {'probe':{'z_offset':'2.000'}}
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ACCEPT']


def test_editor_status_reports_position_and_stale_binding_without_commands(editor, manual):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    manual.status.status.update(z_position=4.0)
    assert value.get_status()['z_position'] == 4.0
    assert value.get_status()['binding_valid'] is True
    value.gcode.ready_gcode_handlers['ACCEPT'] = lambda cmd: None
    assert value.get_status()['binding_valid'] is False
    assert value.get_status()['z_position'] is None
    assert value.state == 'editing'  # read-only observation
    assert sent == ['_WMP_PROBE_CALIBRATE']


def test_editor_status_shows_inflight_action(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    original = value.gcode.run_script_from_command
    states=[]
    def run(text):
        states.append(value.get_status()['state'])
        original(text)
    value.gcode.run_script_from_command = run
    value.cmd_run(command('JOG', 1, Z='-0.1'))
    value.cmd_run(command('ACCEPT', 2))
    value.cmd_run(command('SAVE', 3))
    assert states == ['jogging','accepting','saving']


def test_new_preparation_does_not_publish_previous_receipt(editor, manual):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    value.cmd_run(command('ABORT', 1))
    import copy
    manual.helper = copy.copy(manual.helper)
    manual.helper.finalize_callback = value.receipt.finalizer
    original = value.gcode.run_script_from_command
    observed=[]
    def run(text):
        observed.append(value.get_status())
        original(text)
    value.gcode.run_script_from_command = run
    value.cmd_run(command('BEGIN', 0, REQUEST='b'*32))
    assert observed[0]['request'] == 'b'*32
    assert observed[0]['state'] == 'preparing' and 'token' not in observed[0]


def stop_request(value, **overrides):
    fields = {'session': value.calibration.session, 'request': value.request}
    fields.update(overrides)
    replies = []
    return NS(get_str=lambda key: fields[key], error=ValueError, send=replies.append), replies


@pytest.mark.parametrize('after_helper', [False, True])
def test_preparation_stop_latches_without_commands_then_drains_and_aborts(editor, manual, after_helper):
    value, command, sent, _ = editor
    original = value.gcode.run_script_from_command
    def run(script):
        assert script == '_WMP_PROBE_CALIBRATE'
        if after_helper:
            original(script)
        request, replies = stop_request(value)
        before = list(sent)
        value.handle_stop(request)
        value.handle_stop(request)
        assert sent == before and replies[-1]['state'] == 'requested'
        assert value.state == 'preparing'
        if not after_helper:
            value.cmd_prepare_check(command('BEGIN', 0))
    value.gcode.run_script_from_command = run
    value.cmd_run(command('BEGIN', 0))
    assert value.state == 'aborted' and not value.busy()
    assert sent[-1] == 'drain'
    assert manual.finalized == ([None] if after_helper else [])
    assert 'ACCEPT' not in value.gcode.ready_gcode_handlers
    value.cmd_run(command('BEGIN', 0))  # lost BEGIN reply cannot repeat preparation
    assert sent.count('drain') == 1


@pytest.mark.parametrize('fault', ['session', 'request', 'owner', 'idle'])
def test_preparation_stop_rejects_wrong_request_without_side_effects(editor, fault):
    value, _, sent, _ = editor
    value.state, value.request = 'preparing', 'a'*32
    overrides = {fault: 'wrong'} if fault in ('session', 'request') else {}
    if fault == 'idle': value.state = 'idle'
    if fault == 'owner':
        original = value.printer.lookup_object
        value.printer.lookup_object = lambda name, default=None: object() if name == 'openace' else original(name, default)
    request, _ = stop_request(value, **overrides)
    with pytest.raises(ValueError, match='request or owner'):
        value.handle_stop(request)
    assert not value.stop_requested and sent == []


def test_preparation_stop_drain_failure_stays_unknown(editor):
    value, command, sent, _ = editor
    def drain():
        assert value.state == 'stopping'
        sent.append('drain')
        raise ValueError('drain failed')
    value.printer.lookup_object('toolhead').wait_moves = drain
    def run(script):
        sent.append(script)
        request, _ = stop_request(value)
        value.handle_stop(request)
        value.cmd_prepare_check(command('BEGIN', 0))
    value.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='drain failed'):
        value.cmd_run(command('BEGIN', 0))
    assert value.state == 'unknown' and not value.busy()
    assert sent == ['_WMP_PROBE_CALIBRATE', 'drain']


def test_stop_does_not_mask_unrelated_preparation_failure(editor):
    value, command, sent, _ = editor
    def run(script):
        request, _ = stop_request(value)
        value.handle_stop(request)
        raise ValueError('homing failed')
    value.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='homing failed'):
        value.cmd_run(command('BEGIN', 0))
    assert value.state == 'failed' and not value.busy()
    assert sent == []


def test_prepare_checkpoint_does_not_change_legacy_calibration(editor):
    value, command, sent, _ = editor
    value.stop_requested = True
    value.cmd_prepare_check(command('BEGIN', 0))
    assert value.state == 'idle' and not value.stop_checkpoint_hit and sent == []


@pytest.mark.parametrize("nested", [False, True])
def test_stop_checkpoint_unwinds_retained_dispatcher_before_next_command(editor, nested):
    value, _, _, _ = editor
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    spec = importlib.util.spec_from_file_location('probe_stop_vendor_gcode', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    dispatcher = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    events, errors, commands = [], [], []
    dispatcher.printer = NS(quick_stop_flag=False, send_event=events.append,
                            invoke_shutdown=lambda msg: pytest.fail('unexpected shutdown: ' + msg))
    dispatcher.respond_info = dispatcher.respond_raw = lambda message: None
    dispatcher._respond_error = errors.append
    dispatcher.error = vendor.CommandError
    dispatcher.cmd_default = lambda command: pytest.fail('unknown command')
    dispatcher.gcode_handlers = {'_WMP_PROBE_PREPARE_CHECK': value.cmd_prepare_check,
                                'G28': lambda command: commands.append('G28')}
    value.state, value.stop_requested = 'preparing', True
    value._preparation_scope = value._capture_preparation_scope(NS(error=ValueError))
    dispatcher.gcode_handlers['NESTED'] = lambda command: dispatcher.run_script_from_command('_WMP_PROBE_PREPARE_CHECK\nG28')
    script = 'NESTED\nG28' if nested else '_WMP_PROBE_PREPARE_CHECK\nG28'
    levels = 2 if nested else 1
    with pytest.raises(vendor.CommandError, match='stop requested'):
        dispatcher.run_script_from_command(script)
    assert commands == [] and events == ['gcode:command_error'] * levels
    assert errors == ['Probe preparation stop requested'] * levels
    errors.clear();events.clear()
    value.gcode = dispatcher
    original = dispatcher._respond_error
    with pytest.raises(vendor.CommandError, match='stop requested'):
        value._prepare_with_stop_reporting(lambda: dispatcher.run_script_from_command(script))
    assert commands == [] and errors == []
    assert events == ['gcode:command_error'] * levels  # real cleanup handlers still run
    assert dispatcher._respond_error is original


def test_stop_checkpoint_preserves_machine_fault_instead_of_acknowledging_stop(editor):
    value, command, _, _ = editor
    value.state, value.stop_requested = 'preparing', True
    value._preparation_scope = value._capture_preparation_scope(NS(error=ValueError))
    def fault(_): raise ValueError('tool attachment uncertain')
    value.calibration._check = fault
    with pytest.raises(ValueError, match='attachment uncertain'):
        value.cmd_prepare_check(command('BEGIN', 0))
    assert not value.stop_checkpoint_hit


def test_probe_stop_endpoint_is_registered_on_the_reactor_service(editor):
    value, _, _, _ = editor
    assert value.printer.lookup_object('webhooks').endpoints['wmp/probe_editor/stop'] == value.handle_stop


def fail_after_helper(value, command):
    original = value.gcode.run_script_from_command
    def run(script):
        original(script)
        if script == '_WMP_PROBE_CALIBRATE': raise ValueError('preparation failed after registration')
    value.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='after registration'):
        value.cmd_run(command('BEGIN', 0))
    return original


def test_failed_preparation_retains_only_explicit_bound_abort(editor, manual):
    value, command, sent, _ = editor
    fail_after_helper(value, command)
    assert value.state == 'failed' and value.busy()
    status = value.get_status()
    assert status['receipt_state'] == 'preparation_failed' and status['cleanup_available']
    for action, extra in [('ACCEPT', {}), ('SAVE', {}), ('JOG', {'Z':'0.1'})]:
        with pytest.raises(ValueError): value.cmd_run(command(action, 1, **extra))
    assert manual.finalized == [] and sent == ['_WMP_PROBE_CALIBRATE']
    abort = command('ABORT', 1)
    value.cmd_run(abort)
    assert value.state == 'aborted' and not value.busy()
    assert manual.finalized == [None] and sent == ['_WMP_PROBE_CALIBRATE', 'drain']
    assert 'after registration' in value.error  # cleanup does not erase the fault evidence
    value.cmd_run(abort)
    assert manual.finalized == [None] and sent.count('drain') == 1
    assert value.printer.lookup_object('configfile').status_save_pending == {}


@pytest.mark.parametrize('changed', ['session', 'accept', 'other_handler', 'callback'])
def test_failed_preparation_cleanup_refuses_changed_binding(editor, manual, changed):
    value, command, sent, _ = editor
    fail_after_helper(value, command)
    if changed == 'session': value.calibration.session = 'replacement'
    if changed == 'accept': value.gcode.ready_gcode_handlers['ACCEPT'] = lambda _: None
    if changed == 'other_handler': value.gcode.ready_gcode_handlers['TESTZ'] = lambda _: None
    if changed == 'callback': manual.helper.finalize_callback = lambda _: None
    assert not value.get_status()['cleanup_available']
    with pytest.raises(ValueError): value.cmd_run(command('ABORT', 1))
    assert manual.finalized == [] and sent == ['_WMP_PROBE_CALIBRATE']
    assert value.busy()


def test_legacy_accept_cannot_save_failed_preparation(editor, manual):
    value, command, _, _ = editor
    fail_after_helper(value, command)
    with pytest.raises(ValueError, match='preparation_failed'):
        manual.helper.cmd_ACCEPT(manual.command)
    assert manual.finalized == []
    assert value.printer.lookup_object('configfile').status_save_pending == {}
    assert value.state == 'failed' and not value.busy()


def test_failed_preparation_cleanup_failure_is_not_replayed(editor, manual):
    value, command, sent, _ = editor
    fail_after_helper(value, command)
    def failed_drain(): raise ValueError('cannot drain')
    value.printer.lookup_object('toolhead').wait_moves = failed_drain
    abort = command('ABORT', 1)
    with pytest.raises(ValueError, match='cannot drain'): value.cmd_run(abort)
    assert value.state == 'unknown' and value.busy()
    value.cmd_run(abort)
    assert manual.finalized == [] and sent == ['_WMP_PROBE_CALIBRATE']


@pytest.mark.parametrize('name', ['NEXT', 'ABORT', 'TESTZ'])
def test_preparation_refuses_other_existing_probe_handlers(preparation, name):
    cls, gcode, prepare, register = preparation
    handler = lambda _: None
    gcode.register_command(name, handler)
    before = dict(gcode.ready_gcode_handlers)
    with pytest.raises(ValueError, match='already active'):
        cls.prepare('s', gcode, lambda: 's', lambda: None, prepare)
    assert gcode.ready_gcode_handlers == before and gcode.register_command is register


def test_failed_helper_binding_rechecked_after_drain(editor, manual):
    value, command, _, _ = editor
    fail_after_helper(value, command)
    replacement = lambda _: None
    value.printer.lookup_object('toolhead').wait_moves = lambda: value.gcode.ready_gcode_handlers.update(TESTZ=replacement)
    with pytest.raises(ValueError, match='cleanup is unavailable'):
        value.cmd_run(command('ABORT', 1))
    assert manual.finalized == [] and value.state == 'unknown'
    assert value.gcode.ready_gcode_handlers['TESTZ'] is replacement


def fail_without_helper(value, command):
    value.printer.lookup_object('manual_probe').reset_status()
    def fail(script): raise ValueError('preparation unavailable')
    value.gcode.run_script_from_command = fail
    with pytest.raises(ValueError, match='preparation unavailable'):
        value.cmd_run(command('BEGIN', 0))
    return command('DISCARD', 1, TOKEN=value.get_status()['token'])


def test_no_helper_failure_discard_preserves_config_and_error(editor):
    value, command, sent, _ = editor
    config = value.printer.lookup_object('configfile')
    config.status_save_pending = {'other': {'value':'keep'}}
    config.save_config_pending = True
    discard = fail_without_helper(value, command)
    before = value._pending_config()
    assert value.get_status()['failure_discard_available']
    value.cmd_run(discard)
    assert value.state == 'discarded' and not value.busy()
    assert value.error == 'preparation unavailable' and value._pending_config() == before
    value.cmd_run(discard)
    assert sent == []


@pytest.mark.parametrize('change', ['handler', 'active_probe', 'pending_config', 'autosave', 'fault'])
def test_no_helper_dismissal_only_conflicts_with_actual_helper(editor, change):
    value, command, sent, _ = editor
    discard = fail_without_helper(value, command)
    if change == 'handler': value.gcode.ready_gcode_handlers['ABORT'] = lambda _: None
    elif change == 'active_probe': value.printer.lookup_object('manual_probe').status['is_active'] = True
    elif change == 'pending_config': value.printer.lookup_object('configfile').status_save_pending = {'probe': {'z_offset':'9'}}
    elif change == 'autosave': value.printer.lookup_object('configfile').autosave.fileconfig.add_section('new-section')
    else: value.calibration.failure = 'old machine fault'
    before = value._pending_config()
    if change in ('handler', 'active_probe'):
        with pytest.raises(ValueError, match='still active'): value.cmd_run(discard)
        assert value.state == 'failed' and value.busy()
    else:
        value.cmd_run(discard)
        assert value.state == 'discarded' and not value.busy()
    assert value._pending_config() == before and sent == []


@pytest.mark.parametrize('field,value', [('TOKEN', 'f'*32), ('REQUEST', 'b'*32), ('SEQ', 9), ('Z', '0.1')])
def test_no_helper_discard_requires_exact_request_and_token(editor, field, value):
    owner, command, sent, _ = editor
    fail_without_helper(owner, command)
    fields = {'TOKEN': owner.failure_token, field:value}
    with pytest.raises(ValueError): owner.cmd_run(command('DISCARD', fields.pop('SEQ', 1), **fields))
    assert owner.state == 'failed' and owner.sequence == 0 and sent == []


def test_discard_history_does_not_require_physical_readmission(editor):
    value, command, sent, _ = editor
    discard = fail_without_helper(value, command)
    value.calibration.failure = 'old failure'
    value.printer.lookup_object('toolhead').wait_moves = lambda: pytest.fail('UI dismissal must not drain motion')
    value.cmd_run(discard)
    assert value.state == 'discarded' and value.error == 'preparation unavailable'
    assert sent == []


def test_rejected_begin_records_no_motion_and_does_not_hold_idle_owner(editor):
    value, command, sent, material = editor
    original = material._restart_requested
    def refuse(*_, **kw): raise ValueError('printer busy')
    material._restart_requested = refuse
    begin = command('BEGIN', 0)
    with pytest.raises(ValueError, match='printer busy'): value.cmd_run(begin)
    assert value.state == 'rejected' and not value.busy()
    assert value.sequence == 0 and value.action_refused and sent == []
    material._restart_requested = original
    value.cmd_run(begin)  # a duplicated rejected request must not start later
    assert sent == []
    value.cmd_run(command('BEGIN', 0, REQUEST='b'*32))
    assert value.state == 'editing' and not value.action_refused
    assert sent == ['_WMP_PROBE_CALIBRATE']


def test_refused_save_receipt_does_not_retry_after_config_changes(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0));value.cmd_run(command('ACCEPT', 1))
    config = value.printer.lookup_object('configfile')
    config.status_save_pending['other'] = {'value':'preserve'}
    save = command('SAVE', 2)
    with pytest.raises(ValueError, match='Other pending'): value.cmd_run(save)
    assert value.state == 'accepted' and value.sequence == 2 and value.action_refused
    del config.status_save_pending['other']
    value.cmd_run(save)
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ACCEPT']
    value.cmd_run(command('SAVE', 3))
    assert value.state == 'saved' and not value.action_refused and value.error == ''
    assert sent[-1] == 'SAVE_CONFIG'


def test_editor_keep_conflict_requires_fresh_review_and_never_saves(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    config = value.printer.lookup_object('configfile')
    config.autosave.fileconfig.set('probe', 'z_offset', '2.000')
    config.status_save_pending['probe']['z_offset'] = '2.000'
    review = value.get_status()['config_conflict']['review']
    config.status_save_pending['extruder'] = {'pid_kp':'25'}
    with pytest.raises(ValueError, match='review it again'):
        value.cmd_run(command('KEEP', 2, REVIEW=review))
    assert value.state == 'accepted' and value.get_status()['action_refused']
    fresh = value.get_status()['config_conflict']['review']
    keep = command('KEEP', 3, REVIEW=fresh)
    value.cmd_run(keep); value.cmd_run(keep)
    assert value.state == 'kept' and not value.busy()
    assert value.receipt.state == 'invalidated'
    assert config.status_save_pending == {'probe': {'z_offset':'2.000'}, 'extruder':{'pid_kp':'25'}}
    assert config.autosave.fileconfig.get('probe', 'z_offset') == '2.000'
    assert sent == ['_WMP_PROBE_CALIBRATE', 'ACCEPT']


def test_later_fault_after_stop_checkpoint_is_not_masked(editor):
    value, command, sent, _ = editor
    def run(script):
        value.stop_requested = True
        try:
            value.cmd_prepare_check(command('BEGIN', 0))
        except ValueError:
            raise ValueError('cleanup failed after stop checkpoint')
    value.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='cleanup failed'):
        value.cmd_run(command('BEGIN', 0))
    assert value.state == 'failed' and not value.busy()
    assert 'cleanup failed' in value.error and 'drain' not in sent


@pytest.mark.parametrize('fault', ['stop', 'same_text', 'other', 'session', 'owner'])
def test_expected_stop_reporting_is_identity_bound_and_restored(editor, fault):
    value, command, _, _ = editor
    reports = []
    original = reports.append
    value.gcode._respond_error = original
    value.state, value.stop_requested = 'preparing', True
    value._preparation_scope = value._capture_preparation_scope(NS(error=ValueError))
    def prepare():
        try:
            value.cmd_prepare_check(command('BEGIN', 0))
        except ValueError as stop:
            if fault == 'session': value.calibration.session = 'new'
            if fault == 'owner': value.printer.lookup_object('wm_material')._command_generation = 1
            if fault in ('other', 'same_text'):
                try:
                    raise ValueError(str(stop) if fault == 'same_text' else 'real hardware fault')
                except ValueError as error:
                    value.gcode._respond_error(str(error))
                    raise
            value.gcode._respond_error(str(stop))
            raise
    with pytest.raises(ValueError): value._prepare_with_stop_reporting(prepare)
    assert value.gcode._respond_error is original
    assert bool(reports) == (fault != 'stop')


@pytest.mark.parametrize('mode', ['skipped', 'restart_failed', 'wrong_restart'])
def test_save_requires_writer_restart_receipt_and_never_replays(editor, mode):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    original_restart = value.gcode.request_restart
    if mode == 'restart_failed':
        def fail(result): raise ValueError('restart failed after write')
        value.gcode.request_restart = original_restart = fail
    def run(script):
        sent.append(script)
        if mode == 'restart_failed': value.gcode.request_restart('firmware_restart')
        elif mode == 'wrong_restart': value.gcode.request_restart('restart')
    value.gcode.run_script_from_command = run
    save = command('SAVE', 2)
    with pytest.raises(ValueError): value.cmd_run(save)
    assert value.state == 'unknown' and value.receipt.state == 'unknown' and not value.busy()
    assert value.gcode.request_restart is original_restart
    assert not value.calibration.active and not value.calibration._saving
    value.cmd_run(save)
    assert sent.count('SAVE_CONFIG') == 1


def test_corrupt_save_history_does_not_prevent_explicit_save(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    store, _ = value._save_record_store()
    Path(store.path).write_text('corrupt evidence must survive')
    value.cmd_run(command('SAVE', 2))
    assert sent.count('SAVE_CONFIG') == 1 and not value.busy()
    assert any(path.read_text() == 'corrupt evidence must survive'
               for path in Path(store.path).parent.glob('wmp_probe_save.json.*.record'))


def test_save_intent_precedes_writer_and_survives_unknown_outcome(editor):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    def fail(script):
        store, path = value._save_record_store()
        record = store.read()
        assert record['config_path'] == path and record['offset'] == '1.500'
        assert record['session'] == value.calibration.session
        raise ValueError('write outcome unknown')
    value.gcode.run_script_from_command = fail
    with pytest.raises(ValueError, match='write outcome'): value.cmd_run(command('SAVE', 2))
    assert not value.busy() and value.get_status()['save_review_required']
    value.state, value.request, value.sequence = 'idle', '', -1
    value._restore_save_evidence()  # missing loaded evidence must retain the hold too
    assert value.state == 'save_review' and not value.busy()
    assert value._save_record_store()[0].read()['offset'] == '1.500'


@pytest.mark.parametrize('historical', ['save_review', 'unknown', 'failed'])
def test_new_begin_retires_history_without_erasing_pending_settings(editor, historical):
    value, command, sent, _ = editor
    value.request, value.state = 'b'*32, historical
    value.save_review_required = True
    value.calibration.failure = 'old failed calibration'
    store, _ = value._save_record_store()
    Path(store.path).write_text('unreadable old record')
    config = value.printer.lookup_object('configfile')
    config.status_save_pending = {'other': {'setting': 'keep'}}
    config.save_config_pending = True
    before = value._pending_config()
    value.cmd_run(command('BEGIN', 0))
    assert value.state == 'editing' and value.busy()
    assert value._pending_config() == before and not value.calibration.failure
    assert not value.save_review_required
    value.cmd_run(command('ABORT', 1))
    with pytest.raises(ValueError, match='new idle request'):
        value.cmd_run(command('BEGIN', 0, REQUEST='b'*32))
    assert sent.count('_WMP_PROBE_CALIBRATE') == 1


@pytest.mark.parametrize('finish', ['ACCEPT', 'ABORT'])
def test_external_helper_completion_allows_new_begin_but_not_old_commands(editor, manual, finish):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0))
    old_jog = command('JOG', 1, Z='0.1')
    old_save = command('SAVE', 2)
    getattr(manual.helper, 'cmd_' + finish)(manual.command)
    assert value.state == 'editing' and not value.busy()
    pending = value._pending_config()
    # The vendor creates a new helper with the probe's original finalizer.
    import copy
    manual.helper = copy.copy(manual.helper)
    manual.helper.finalize_callback = value.receipt.finalizer
    value.cmd_run(command('BEGIN', 0, REQUEST='b'*32))
    assert value.busy() and value._pending_config() == pending
    for stale in (old_jog, old_save):
        with pytest.raises(ValueError, match='Stale probe editor action'):
            value.cmd_run(stale)
    assert sent == ['_WMP_PROBE_CALIBRATE', '_WMP_PROBE_CALIBRATE']


def test_save_evidence_io_failure_warns_without_stranding_save(editor, monkeypatch):
    value, command, sent, _ = editor
    value.cmd_run(command('BEGIN', 0)); value.cmd_run(command('ACCEPT', 1))
    store, _ = value._save_record_store()
    def failed(*args, **kwargs): raise OSError('disk full for evidence')
    monkeypatch.setattr(type(store), 'create', failed)
    save = command('SAVE', 2)
    value.cmd_run(save)
    assert value.state == 'saved' and not value.busy()
    assert 'disk full' in value.get_status()['diagnostic_warning']
    value.cmd_run(save)
    assert sent.count('SAVE_CONFIG') == 1


def test_probe_review_does_not_require_idle_machine(editor, monkeypatch):
    value, _, sent, _ = editor
    value.state, value.request = 'save_review', 'a'*32
    value.save_review_required = True
    value._admit = lambda _: pytest.fail('read-only review must not acquire printer')
    review = {'record': {'request': value.request}, 'configuration_matches': True}
    monkeypatch.setattr(value, '_read_save_review', lambda: (None, None, None, None, None, review))
    value._run_save_review(NS(error=ValueError), value.request, 'REVIEW', '')
    assert value.save_review_confirmable and not value.busy() and sent == []


@pytest.mark.parametrize('after_helper', [False, True])
def test_shared_boundary_observes_preparation_stop_and_preserves_helper_cleanup(editor, manual, after_helper):
    from wmp_stop_points import check_operation_boundary
    value, command, sent, _ = editor
    original_run = value.gcode.run_script_from_command
    original_lookup = value.printer.lookup_object
    recovery = NS(calibration=value.calibration)
    value.calibration.check_cancel = lambda label: None
    value.printer.lookup_object = lambda name, default=None: recovery if name == 'wmp_recovery' else original_lookup(name, default)
    def run(script):
        if after_helper: original_run(script)
        request, _ = stop_request(value)
        value.handle_stop(request)
        check_operation_boundary(value.printer, 'after Y homing')
        pytest.fail('X homing would run after a pending preparation Stop')
    value.gcode.run_script_from_command = run
    value.cmd_run(command('BEGIN', 0))
    assert value.state == 'aborted' and not value.busy()
    assert sent[-1] == 'drain'
    assert manual.finalized == ([None] if after_helper else [])
    assert 'ACCEPT' not in value.gcode.ready_gcode_handlers


def shared_probe_boundary(value):
    from wmp_stop_points import check_operation_boundary
    original = value.printer.lookup_object
    recovery = NS(calibration=value.calibration)
    value.calibration.check_cancel = lambda label: None
    value.printer.lookup_object = lambda name, default=None: recovery if name == 'wmp_recovery' else original(name, default)
    return lambda: check_operation_boundary(value.printer, 'after Y homing')


def test_preparation_stop_is_not_consumed_by_foreign_greenlet(editor, monkeypatch):
    value, command, sent, _ = editor
    boundary = shared_probe_boundary(value)
    actor = [object()]
    monkeypatch.setattr(value, '_current_actor', lambda: actor[0])
    def run(script):
        owner = actor[0]
        actor[0] = object()  # Out-of-band request is allowed on the reactor.
        value.handle_stop(stop_request(value)[0])
        boundary()  # An unrelated callback cannot unwind this preparation.
        assert not value.stop_checkpoint_hit and sent == []
        actor[0] = owner
        boundary()
        pytest.fail('owned preparation did not observe Stop')
    value.gcode.run_script_from_command = run
    value.cmd_run(command('BEGIN', 0))
    assert value.state == 'aborted' and sent == ['drain']


@pytest.mark.parametrize('change', ['generation', 'material_session', 'session', 'request', 'material', 'scope', 'receipt', 'manager'])
def test_preparation_handoff_cannot_drain_abort_or_rewrite_replacement(editor, manual, change):
    value, command, sent, material = editor
    boundary = shared_probe_boundary(value)
    original_run = value.gcode.run_script_from_command
    original_lookup = value.printer.lookup_object
    def run(script):
        original_run(script)
        value.handle_stop(stop_request(value)[0])
        if change == 'generation': material._command_generation = 1
        elif change == 'material_session': material.session_id = 'new'
        elif change == 'session': value.calibration.session = 'new'
        elif change == 'request': value.request = 'b'*32
        elif change in ('material', 'manager'):
            name = 'wm_material' if change == 'material' else 'openace'
            replacement = object()
            value.printer.lookup_object = lambda key, default=None: replacement if key == name else original_lookup(key, default)
        elif change == 'scope': value._preparation_scope = {'replacement': True}
        else: value.receipt = object()
        value.state, value.error = 'replacement', 'replacement result'
        boundary()
        if change != 'scope': pytest.fail('lost preparation owner continued past the boundary')
    value.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='request or owner changed'):
        value.cmd_run(command('BEGIN', 0))
    assert sent == ['_WMP_PROBE_CALIBRATE']
    assert manual.finalized == []
    assert (value.state, value.error) == ('replacement', 'replacement result')


@pytest.mark.parametrize('change', ['session', 'request', 'receipt', 'scope', 'manager'])
def test_preparation_cleanup_revalidates_after_drain_before_helper_abort(editor, manual, change):
    value, command, sent, _ = editor
    original_run = value.gcode.run_script_from_command
    original_lookup = value.printer.lookup_object
    def run(script):
        original_run(script)
        value.handle_stop(stop_request(value)[0])
    def drain():
        sent.append('drain')
        if change == 'session': value.calibration.session = 'new'
        elif change == 'request': value.request = 'b'*32
        elif change == 'receipt': value.receipt = object()
        elif change == 'scope': value._preparation_scope = {'replacement': True}
        else:
            replacement = object()
            value.printer.lookup_object = lambda key, default=None: replacement if key == 'AFC' else original_lookup(key, default)
        value.state, value.error = 'replacement', 'new result'
    value.gcode.run_script_from_command = run
    value.printer.lookup_object('toolhead').wait_moves = drain
    with pytest.raises(ValueError, match='request or owner changed'):
        value.cmd_run(command('BEGIN', 0))
    assert sent == ['_WMP_PROBE_CALIBRATE', 'drain'] and not manual.finalized
    assert value.state == 'replacement' and value.error == 'new result'


@pytest.mark.parametrize('stop_axis', [1, 0])
def test_probe_preparation_between_axes_uses_retained_native_homing_without_motor_off(editor, stop_axis):
    from wmp_xy_homing import XYHoming
    path = ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/homing.py'
    spec = importlib.util.spec_from_file_location('probe_stop_native_homing', path)
    stock = importlib.util.module_from_spec(spec);spec.loader.exec_module(stock)
    value, command, sent, _ = editor
    shared_probe_boundary(value)
    calls = []
    rails = [NS(get_name=lambda: 'stepper_x', get_homing_info=lambda: NS(positive_dir=True)),
             NS(get_name=lambda: 'stepper_y', get_homing_info=lambda: NS(positive_dir=False))]
    def home(state):
        calls.append(('axis', state.get_axes()))
        if state.get_axes() == [stop_axis]: value.handle_stop(stop_request(value)[0])
    kin = NS(rails=rails, limits=[(0,300), (0,300)], home=home)
    objects = {'toolhead': NS(get_kinematics=lambda: kin, wait_moves=lambda: calls.append(('wait',))),
               'stepper_enable': NS(motor_off=lambda: pytest.fail('normal Stop disabled motors')),
               'gcode': value.gcode}
    native = stock.PrinterHoming.__new__(stock.PrinterHoming);native.printer = value.printer
    objects['homing'] = native
    original_lookup = value.printer.lookup_object
    value.printer.lookup_object = lambda key, default=None: objects[key] if key in objects else original_lookup(key, default)
    value.printer.is_shutdown = lambda: False
    value.printer.command_error = ValueError
    value.gcode.create_gcode_command = lambda name, text, params: NS(get=lambda key, default=None: params.get(key, default))
    xy = XYHoming(value.printer)
    xy_command = command('BEGIN', 0)
    xy_command.respond_info = lambda message: None
    value.gcode.run_script_from_command = lambda script: xy._home(xy_command, stock.Homing, stock.HomingMove)
    value.cmd_run(command('BEGIN', 0))
    expected = [('axis', [1]), ('wait',)]
    if stop_axis == 0: expected += [('axis', [0]), ('wait',)]
    assert calls == expected + [('wait',)]
    assert kin.limits[1] == (1., -1.) and value.state == 'aborted'
    assert sent == []


def test_preparation_stop_clears_owned_toolchange_transient(editor):
    value, command, sent, _ = editor
    variables = {'changing_tool': 0, 'fail_flag': 0, 'thr_number': 4}
    extra = {'save_variables': NS(get_status=lambda now: {'variables': variables}),
             'custom_hall': NS(get_status=lambda now: {'Raw': 5000}),
             'filament_switch_sensor sensor_b': NS(get_status=lambda now: {'filament_detected': False}),
             **{'filament_switch_sensor docked%d' % n: NS(get_status=lambda now: {'filament_detected': True}) for n in range(4)},
             'gcode': value.gcode}
    lookup = value.printer.lookup_object
    value.printer.lookup_object = lambda name, default=None: extra[name] if name in extra else lookup(name, default)
    value.printer.get_reactor = lambda: NS(monotonic=lambda: 0)
    value.printer.is_shutdown = lambda: False
    def run(script):
        sent.append(script)
        if script == '_WMP_PROBE_CALIBRATE':
            variables['changing_tool'] = 1
            value.handle_stop(stop_request(value)[0])
            value.cmd_prepare_check(command('BEGIN', 0))
        else:
            assert script == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0'
            variables['changing_tool'] = 0
    value.gcode.run_script_from_command = run
    value.cmd_run(command('BEGIN', 0))
    assert value.state == 'aborted' and variables['changing_tool'] == 0
    assert sent[-2:] == ['drain', 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0']
