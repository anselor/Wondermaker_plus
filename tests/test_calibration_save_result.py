"""Maintenance save receipts confirm saved values, never whole-run completion."""
import configparser
import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_calibration_commands import Command, AttemptCommand, Printer, module, isolate_checkpoint_io


def parser(values):
    result = configparser.RawConfigParser()
    result.read_dict(values)
    return result


class SaveCommand(Command):
    def __init__(self, runner, request='b'*32, text='SAVE_CONFIG', session=None):
        super().__init__(text)
        self.session = runner.session if session is None else session
        self.request = request
    def get(self, key, default=''):
        return {'SESSION': self.session, 'REQUEST': self.request}.get(key, super().get(key, default))


@pytest.fixture
def machine(tmp_path):
    p = Printer()
    p.events = {}
    p.register_event_handler = lambda name, fn: p.events.setdefault(name, []).append(fn)
    path = tmp_path / 'printer.cfg'
    path.write_text(json.dumps({'extruder': {'pid_kp': '20'}}))
    expected = {'extruder': {'pid_kp': '30', 'pid_ki': '6', 'pid_kd': '34'},
                'input_shaper': {'shaper_type_x': 'mzv', 'shaper_freq_x': '40'}}
    config = NS(autosave=NS(fileconfig=parser(expected)), status_raw_config=copy.deepcopy(expected),
                status_save_pending={}, _read_config_file=lambda name: Path(name).read_text(),
                _find_autosave_data=lambda text: ('', text),
                _build_config_wrapper=lambda text, name: NS(fileconfig=parser(json.loads(text))))
    p.objects['configfile'] = config
    p.get_start_args = lambda: {'config_file': str(path)}
    p.restarts = []
    p.request_restart = lambda mode: p.restarts.append(mode)
    def save(command):
        if command == 'SAVE_CONFIG':
            path.write_text(json.dumps(expected))
            p.request_restart('firmware_restart')
    p.on_run = save
    runner = module.CalibrationCommands(p, p)
    isolate_checkpoint_io(runner)
    return p, runner, path, expected


def restore(p):
    runner = module.CalibrationCommands(p, p)
    isolate_checkpoint_io(runner)
    runner._restore_save_result()
    return runner


def test_bound_success_is_confirmed_only_after_restart_and_matching_loaded_values(machine, monkeypatch):
    p, runner, path, expected = machine
    assert runner._restore_save_result in p.events['klippy:ready']
    runner.cmd_run(SaveCommand(runner))
    assert runner.save_result['state'] == 'saved'
    assert p.restarts == ['firmware_restart'] and not runner.failure
    result = restore(p).save_result
    assert result == dict(protocol=1, session=runner.session, request='b'*32, state='confirmed', error='')
    # Same-session status cannot manufacture restart verification.
    runner._restore_save_result()
    assert runner.save_result['state'] == 'unconfirmed'
    # Exercise the actual periodic status entry with filesystem access forbidden.
    bottom = module.BottomZ.__new__(module.BottomZ)
    bottom.printer, bottom.calibration = p, runner
    bottom.valid, bottom.active, bottom.identification = False, False, None
    p.objects['toolhead'] = NS(get_status=lambda now: {'homed_axes': 'xyz'})
    p.get_start_args = lambda: pytest.fail('status must not read files')
    monkeypatch.setattr('builtins.open', lambda *args, **kwargs: pytest.fail('status must not read files'))
    for now in range(10):
        result = bottom.get_status(float(now))['calibration_save_result']
        assert result == runner.save_result and result is not runner.save_result


@pytest.mark.parametrize('change', ['disk', 'loaded', 'pending', 'corrupt', 'missing', 'path'])
def test_restart_mismatch_does_not_confirm(machine, change):
    p, runner, path, expected = machine
    runner.cmd_run(SaveCommand(runner))
    store, _ = runner._save_store()
    if change == 'disk': path.write_text(json.dumps({'extruder': {'pid_kp': '999'}}))
    elif change == 'loaded': p.objects['configfile'].status_raw_config['extruder']['pid_kp'] = '999'
    elif change == 'pending': p.objects['configfile'].status_save_pending = {'extruder': {'pid_ki': '9'}}
    elif change == 'corrupt': Path(store.path).write_text('broken')
    elif change == 'missing': Path(store.path).unlink()
    else:
        other = path.with_name('other.cfg'); other.write_text(path.read_text())
        p.get_start_args = lambda: {'config_file': str(other)}
    assert restore(p).save_result['state'] == 'unconfirmed'


@pytest.mark.parametrize('fault', ['skip', 'write', 'restart', 'wrong_restart', 'soft_fault', 'after_restart'])
def test_save_errors_never_leave_positive_evidence(machine, monkeypatch, fault):
    p, runner, path, expected = machine
    original = p.on_run
    if fault == 'skip': p.on_run = lambda command: None
    elif fault == 'write': p.on_run = lambda command: (_ for _ in ()).throw(OSError('save failed'))
    elif fault == 'restart': p.request_restart = lambda mode: (_ for _ in ()).throw(ValueError('restart failed'))
    elif fault == 'wrong_restart': p.on_run = lambda command: p.request_restart('restart')
    elif fault in ('soft_fault', 'after_restart'):
        def fail(command):
            original(command)
            if fault == 'soft_fault': p.fail = -3
            else: raise ValueError('writer failed after restart request')
        p.on_run = fail
    with pytest.raises((RuntimeError, OSError, ValueError)):
        runner.cmd_run(SaveCommand(runner))
    assert runner.failure and not runner.active
    assert runner.save_result['state'] == 'unconfirmed'
    assert restore(p).save_result['state'] == 'unconfirmed'


def test_intent_write_failure_warns_but_saves_once(machine, monkeypatch):
    p, runner, path, expected = machine
    monkeypatch.setattr(module.CalibrationSaveRecord, 'write', lambda *args: (_ for _ in ()).throw(OSError('intent failure')))
    runner.cmd_run(SaveCommand(runner))
    assert p.sent == ['SAVE_CONFIG'] and p.restarts == ['firmware_restart']
    assert not runner.failure and not runner.active and not p.off
    assert runner.save_result['state'] == 'unconfirmed'
    assert 'intent failure' in runner.save_result['error']
    with pytest.raises(RuntimeError, match='already attempted'):
        runner.cmd_run(SaveCommand(runner))
    assert p.sent == ['SAVE_CONFIG']
    assert restore(p).save_result['state'] == 'unconfirmed'


def test_interrupted_writer_with_matching_values_is_not_saved_evidence(machine):
    p, runner, path, expected = machine
    def interrupted(command):
        path.write_text(json.dumps(expected))
        p.request_restart('firmware_restart')
        raise KeyboardInterrupt('process loss before successful receipt')
    p.on_run = interrupted
    with pytest.raises(KeyboardInterrupt): runner.cmd_run(SaveCommand(runner))
    assert restore(p).save_result['state'] == 'unconfirmed'


@pytest.mark.parametrize('change', ['session', 'request', 'wrong_command', 'old_failure'])
def test_invalid_binding_and_prior_failure_do_not_save(machine, change):
    p, runner, path, expected = machine
    command = SaveCommand(runner)
    if change == 'session': command.session = 'a'*32
    elif change == 'request': command.request = 'bad'
    elif change == 'wrong_command': command.encoded = 'M400'.encode().hex()
    else: runner.failure = 'prior calibration failed'
    with pytest.raises(RuntimeError): runner.cmd_run(command)
    assert p.sent == [] and p.restarts == []
    assert restore(p).save_result['state'] == 'unconfirmed'


def test_legacy_save_does_not_create_confirmed_receipt(machine):
    p, runner, path, expected = machine
    runner.cmd_run(Command('SAVE_CONFIG'))
    assert restore(p).save_result['state'] == 'unconfirmed'


def test_new_save_replaces_prior_request_evidence(machine):
    p, runner, path, expected = machine
    runner.cmd_run(SaveCommand(runner))
    newer = restore(p)
    newer.cmd_run(SaveCommand(newer, request='c'*32))
    result = restore(p).save_result
    assert result['request'] == 'c'*32 and result['session'] == newer.session
    assert result['state'] == 'confirmed'


def test_failed_new_intent_cannot_reuse_old_confirmed_receipt(machine, monkeypatch):
    p, first, path, expected = machine
    first.cmd_run(SaveCommand(first))
    runner = restore(p)
    assert runner.save_result['state'] == 'confirmed'
    publish = module.CalibrationSaveRecord._publish
    def fail(store, path, payload, replace=False):
        publish(store, path, payload, replace=replace)
        raise OSError('directory sync after publication failed')
    monkeypatch.setattr(module.CalibrationSaveRecord, '_publish', fail)
    before = list(p.sent)
    runner.cmd_run(SaveCommand(runner, request='c'*32))
    assert p.sent == before + ['SAVE_CONFIG']
    assert not runner.failure and runner.save_result['state'] == 'unconfirmed'
    assert restore(p).save_result['state'] == 'unconfirmed'


@pytest.mark.parametrize('sync_number', [1, 2])
def test_intent_fsync_error_does_not_veto_save(machine, monkeypatch, sync_number):
    p, runner, path, expected = machine
    fsync = module.os.fsync
    calls = []
    def fail(fd):
        calls.append(fd)
        if len(calls) == sync_number: raise OSError('sync fault')
        fsync(fd)
    monkeypatch.setattr(module.os, 'fsync', fail)
    runner.cmd_run(SaveCommand(runner))
    assert p.sent == ['SAVE_CONFIG'] and restore(p).save_result['state'] == 'unconfirmed'
    assert not runner.failure and not p.off


@pytest.mark.parametrize('fault', [None, 'event', 'dwell', 'wait', 'exit'])
def test_retained_vendor_save_writer_and_restart_boundary(machine, fault):
    import importlib.util
    from types import MethodType
    root = Path(__file__).resolve().parents[1]
    vendor = root / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'
    if not all((vendor / (name + '.py')).is_file() for name in ('configfile', 'gcode')):
        pytest.skip('Retained WM 1.1.13 configfile/gcode sources are unavailable')
    def load(name):
        spec = importlib.util.spec_from_file_location('save_result_vendor_' + name, vendor / (name + '.py'))
        loaded = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded)
        return loaded
    config_module, gcode_module = load('configfile'), load('gcode')
    p, runner, path, expected = machine
    path.write_text('[printer]\nkinematics: corexy\n[extruder]\npid_Kp: 20\npid_Ki: 2\npid_Kd: 3\n')
    p.objects['gcode'] = p
    config = config_module.PrinterConfig(p)
    config.read_main_config()
    # PID calibrate supplies mixed-case keys; retained parser normalizes them.
    for key, value in [('pid_Kp', '30.716'), ('pid_Ki', '6.826'), ('pid_Kd', '34.556')]:
        config.set('extruder', key, value)
    # Bed mesh supplies indented continuation lines before SAVE_CONFIG. Its
    # real write/reload strips this indentation in both disk and loaded status.
    config.set('bed_mesh default', 'points', '\n  -0.549375, -0.496563\n  -0.506875, -0.454688')
    # Real user config retained an empty heater section after PID changes.
    config.autosave.fileconfig.add_section('heater_bed')
    p.objects['configfile'] = config
    order = []
    def stage(name):
        order.append(name)
        if name == fault: raise RuntimeError(name + ' failed')
    p.printer, p.is_printer_ready, p.error = p, True, RuntimeError
    p.objects['toolhead'] = NS(get_last_move_time=lambda: 12.,
                              dwell=lambda duration: stage('dwell'), wait_moves=lambda: stage('wait'))
    p.send_event = lambda *args: stage('event')
    p.request_exit = lambda mode: stage('exit')
    p.request_restart = MethodType(gcode_module.GCodeDispatch.request_restart, p)
    original_restart = p.request_restart
    p.on_run = lambda command: config.cmd_SAVE_CONFIG(SaveCommand(runner))
    if fault:
        with pytest.raises(RuntimeError): runner.cmd_run(SaveCommand(runner))
    else:
        runner.cmd_run(SaveCommand(runner))
        assert order == ['event', 'dwell', 'wait', 'exit']
        assert runner.save_result['state'] == 'saved'
        record = runner._save_store()[0].read()
        assert record['autosave']['bed_mesh default']['points'].startswith('\n  ')
    assert p.request_restart is original_restart
    assert '#*# pid_kp = 30.716' in path.read_text()
    # Reload using the actual retained parser/status builder, not synthetic data.
    restarted_config = config_module.PrinterConfig(p)
    loaded = restarted_config.read_main_config()
    restarted_config._build_status(loaded)
    p.objects['configfile'] = restarted_config
    result = restore(p).save_result
    assert result['state'] == ('unconfirmed' if fault else 'confirmed')


@pytest.mark.parametrize('change', [None, 'numeric', 'missing_row', 'extra_row',
                                  'loaded_numeric', 'pending', 'missing_section', 'extra_key'])
def test_mesh_roundtrip_only_normalizes_parser_formatting(machine, change):
    p, runner, path, expected = machine
    store, _ = runner._save_store()
    points = '\n  -0.549375, -0.496563\n  -0.506875, -0.454688'
    record = dict(version=1, session=runner.session, request='b'*32,
                  config_path=str(path), state='saved',
                  autosave={'bed_mesh default': {'points': points, 'x_count': '2'}})
    # Preserve the old receipt representation/checksum; no record rewrite.
    store.write(record)
    before = Path(store.path).read_bytes()
    disk = {'bed_mesh default': {'points': '\n-0.549375, -0.496563\n-0.506875, -0.454688', 'x_count': '2'}}
    loaded = copy.deepcopy(disk)
    pending = {}
    if change == 'numeric': disk['bed_mesh default']['points'] = disk['bed_mesh default']['points'].replace('-0.549375', '-0.549376')
    elif change == 'missing_row': disk['bed_mesh default']['points'] = '\n-0.549375, -0.496563'
    elif change == 'extra_row': disk['bed_mesh default']['points'] += '\n-0.506875, -0.454688'
    elif change == 'loaded_numeric': loaded['bed_mesh default']['x_count'] = '3'
    elif change == 'pending': pending = {'bed_mesh default': {'points': points}}
    elif change == 'missing_section': disk = {}
    elif change == 'extra_key': disk['bed_mesh default']['y_count'] = '2'
    assert store.verify(store.read(), str(path), disk, loaded, pending) is (change is None)
    assert Path(store.path).read_bytes() == before


def test_sequenced_stages_bind_final_save_to_same_attempt(machine):
    p, runner, path, config = machine
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    runner.cmd_run(AttemptCommand(runner, 'M400', sequence=1))
    runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=2))
    assert runner.save_result['state'] == 'saved'
    assert runner.save_result['request'] == 'a' * 32
    assert runner.attempt_result['state'] == 'saved'
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=3))


@pytest.mark.parametrize('published', [False, True])
def test_post_save_receipt_failure_does_not_fail_completed_calibration(machine, monkeypatch, published):
    p, runner, path, expected = machine
    write = module.CalibrationSaveRecord.write
    def fail(store, record):
        if record['state'] == 'saved':
            if published: write(store, record)
            raise OSError('receipt publication failed')
        write(store, record)
    monkeypatch.setattr(module.CalibrationSaveRecord, 'write', fail)
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=1))
    assert p.sent == ['G28', 'SAVE_CONFIG'] and p.restarts == ['firmware_restart']
    assert runner.attempt_result['state'] == 'saved'  # Actual writer completed.
    assert runner.save_result['state'] == 'unconfirmed'  # Durable receipt did not.
    assert 'receipt publication failed' in runner.save_result['error']
    assert not runner.failure and not runner.active and not p.off
    assert restore(p).save_result['state'] == 'unconfirmed'
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=2))
    assert p.sent == ['G28', 'SAVE_CONFIG']


def test_evidence_cleanup_failure_does_not_mask_writer_failure(machine, monkeypatch):
    p, runner, path, expected = machine
    def discard(store): raise OSError('diagnostic unlink failed')
    def writer(command): raise RuntimeError('actual writer failed')
    monkeypatch.setattr(module.CalibrationSaveRecord, 'discard', discard)
    p.on_run = writer
    with pytest.raises(RuntimeError, match='actual writer failed'):
        runner.cmd_run(SaveCommand(runner))
    assert 'actual writer failed' in runner.failure
    assert runner.save_result['state'] == 'unconfirmed'


def test_failed_evidence_write_and_cleanup_still_allow_writer(machine, monkeypatch, caplog):
    p, runner, path, expected = machine
    def fail(*args): raise OSError('diagnostic storage unavailable')
    monkeypatch.setattr(module.CalibrationSaveRecord, 'write', fail)
    monkeypatch.setattr(module.CalibrationSaveRecord, 'discard', fail)
    runner.cmd_run(SaveCommand(runner))
    assert p.sent == ['SAVE_CONFIG'] and p.restarts == ['firmware_restart']
    assert not runner.failure and not p.off
    assert runner.save_result['state'] == 'unconfirmed'
    assert 'could not be removed' in runner.save_result['error']
    assert 'configuration save result must be checked' in caplog.text


@pytest.mark.parametrize('failure', ['store', 'snapshot'])
def test_diagnostic_preparation_failure_does_not_veto_valid_writer(machine, monkeypatch, failure):
    p, runner, path, expected = machine
    def fail(*args, **kwargs): raise OSError('diagnostic ' + failure + ' unavailable')
    if failure == 'store':
        monkeypatch.setattr(runner, '_save_store', fail)
    else:
        monkeypatch.setattr(p.objects['configfile'].autosave.fileconfig, 'items', fail)
    runner.cmd_run(SaveCommand(runner))
    assert json.loads(path.read_text()) == expected
    assert p.sent == ['SAVE_CONFIG'] and p.restarts == ['firmware_restart']
    assert not runner.failure and not runner.active and not p.off
    assert runner.save_result['state'] == 'unconfirmed'
    assert 'diagnostic ' + failure + ' unavailable' in runner.save_result['error']


@pytest.mark.parametrize('change', [None, 'disk_value', 'loaded_value', 'pending'])
def test_shaper_save_with_empty_heater_section_is_verified(machine, change):
    p, runner, path, expected = machine
    expected['heater_bed'] = {}
    expected['input_shaper'] = {'shaper_type_x': '3hump_ei', 'shaper_freq_x': '107.2',
                               'shaper_type_y': 'mzv', 'shaper_freq_y': '34.8'}
    config = p.objects['configfile']
    config.autosave.fileconfig = parser(expected)
    config.status_raw_config = copy.deepcopy(expected)
    runner.cmd_run(SaveCommand(runner))
    assert runner.save_result['state'] == 'saved'
    assert runner._save_store()[0].read()['autosave']['heater_bed'] == {}
    if change == 'disk_value':
        altered = copy.deepcopy(expected)
        altered['input_shaper']['shaper_freq_x'] = '99'
        path.write_text(json.dumps(altered))
    elif change == 'loaded_value': config.status_raw_config['input_shaper']['shaper_freq_x'] = '99'
    elif change == 'pending': config.status_save_pending = {'input_shaper': {'shaper_freq_x': '99'}}
    assert restore(p).save_result['state'] == ('confirmed' if change is None else 'unconfirmed')


def test_only_empty_sections_do_not_claim_calibration_values(machine):
    p, runner, path, expected = machine
    p.objects['configfile'].autosave.fileconfig = parser({'heater_bed': {}})
    runner.cmd_run(SaveCommand(runner))
    assert runner.save_result['state'] == 'unconfirmed'
    assert restore(p).save_result['state'] == 'unconfirmed'
