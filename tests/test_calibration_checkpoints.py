"""Scoped checkpoints use the retained parser and preserve unrelated tuning."""
import copy
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'klipper_extras'))
import wmp_calibration_checkpoint as checkpoints


def retained_config():
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/configfile.py'
    if not path.exists(): pytest.skip('retained factory config parser unavailable')
    spec = importlib.util.spec_from_file_location('retained_checkpoint_config', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Axis:
    def __init__(self, name):
        self.params = NS(axis=name, shaper_type='mzv', shaper_freq=40.)
        self.n, self.A, self.T, self.saved = 2, [.4, .6], [0., .01], None
    def update(self, value):
        self.params.shaper_type, self.params.shaper_freq = value
        self.n, self.A, self.T = 3, [.2, .3, .5], [0., .005, .01]


@pytest.fixture
def env(tmp_path):
    module = retained_config()
    objects = {}
    gcode = NS(error=ValueError, register_command=lambda *args, **kwargs: None)
    objects['gcode'] = gcode
    path = tmp_path / 'printer.cfg'
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_start_args=lambda: {'config_file': str(path)},
                 is_shutdown=lambda: False, quick_stop_flag=False)
    config = module.PrinterConfig(printer)
    config.autosave = config._build_config_wrapper('''[extruder]
rotation_distance = 21.6485
control = pid
pid_kp = 20
pid_ki = 5
pid_kd = 30
[input_shaper]
shaper_type_x = mzv
shaper_freq_x = 40
shaper_type_y = mzv
shaper_freq_y = 40
''', str(path))
    regular = '[printer]\nmax_accel: 5000\n# User comment\n[extruder]\n# PID and calibrated rotation are in autosave\n[input_shaper]\n'
    lines = [('#*# ' + line).strip() for line in config._build_config_string(config.autosave).split('\n')]
    path.write_text(regular + module.AUTOSAVE_HEADER + '\n'.join(lines) + '\n')
    actor = [object()]
    attempt = dict(request='a' * 32, state='pending', next=1)
    tracker = NS(current_actor=lambda: actor[0], enabled=True, contexts={actor[0]: attempt['request']})
    cal = NS(printer=printer, gcode=gcode, active=True, executing=attempt,
             _current_attempt=attempt, _heater_ownership=tracker)
    axes = [Axis('x'), Axis('y')]
    shaper = NS(get_shapers=lambda: axes, updates=[])
    shaper._update_input_shaping = lambda: shaper.updates.append(True)
    objects.update(gcode=gcode, configfile=config, input_shaper=shaper)
    def disk():
        regular, saved = config._find_autosave_data(path.read_text())
        return config._build_config_wrapper(regular + saved, str(path)).fileconfig
    return NS(config=config, cal=cal, attempt=attempt, actor=actor, owned_actor=actor[0],
              path=path, printer=printer, objects=objects, axes=axes, shaper=shaper,
              stage=checkpoints.Checkpoints(cal).stage, disk=disk)


def pid(env, **changes):
    env.config.remove_section('extruder')
    for key, value in dict(control='pid', pid_kp='31', pid_ki='6', pid_kd='35', **changes).items():
        env.config.set('extruder', key, value)


def vibration(env):
    for name, axis in zip('xy', env.axes):
        axis.update(('ei', 55.))
        env.config.set('input_shaper', 'shaper_type_' + name, 'ei')
        env.config.set('input_shaper', 'shaper_freq_' + name, '55.0')


def mesh(env):
    for key, value in dict(version='1', points='0.01, 0.02\n0.03, 0.04',
                           x_count='2', y_count='2', min_x='10', max_x='290', min_y='10', max_y='290').items():
        env.config.set('bed_mesh default', key, value)


def test_pid_checkpoint_preserves_tuning_and_unrelated_pending_edits(env):
    env.config.set('extruder', 'rotation_distance', '21.999')
    env.config.set('printer', 'max_accel', '10000')
    env.path.chmod(0o640)
    with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
        pid(env)
    disk = env.disk()
    assert disk.get('extruder', 'rotation_distance') == '21.6485'
    assert disk.get('printer', 'max_accel') == '5000'
    assert disk.get('extruder', 'pid_kp') == '31'
    assert env.config.autosave.fileconfig.get('extruder', 'rotation_distance') == '21.999'
    assert env.config.status_save_pending['printer']['max_accel'] == '10000'
    assert env.path.stat().st_mode & 0o777 == 0o640
    assert '# User comment' in env.path.read_text()
    record = env.attempt['checkpoints'][-1]
    assert record['state'] == 'saved' and len(record['sha256']) == 64
    assert not list(env.path.parent.glob('.wmp-calibration-*'))
    assert len(list(env.path.parent.iterdir())) == 1  # No backup proliferation.


def test_completed_mesh_survives_later_failed_pid(env):
    with env.stage('G29', env.attempt): mesh(env)
    saved = env.path.read_bytes()
    with pytest.raises(ValueError, match='PID failed'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pid(env)
            raise ValueError('PID failed')
    assert env.path.read_bytes() == saved
    assert env.disk().has_section('bed_mesh default')
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'
    assert env.attempt['checkpoints'][0]['state'] == 'saved'
    assert env.attempt['checkpoints'][1]['state'] == 'unconfirmed'


def test_second_axis_failure_restores_runtime_and_pending_shapers(env):
    before = copy.deepcopy([(vars(axis.params), axis.n, axis.A, axis.T, axis.saved) for axis in env.axes])
    raw, pending = env.path.read_bytes(), copy.deepcopy(env.config.status_save_pending)
    with pytest.raises(ValueError, match='second axis cancelled'):
        with env.stage('SHAPER_CALIBRATE', env.attempt):
            env.axes[0].update(('ei', 55.))
            env.config.set('input_shaper', 'shaper_freq_x', '55.0')
            raise ValueError('second axis cancelled')
    assert [(vars(axis.params), axis.n, axis.A, axis.T, axis.saved) for axis in env.axes] == before
    assert env.config.status_save_pending == pending and env.path.read_bytes() == raw
    assert env.shaper.updates == [True]
    assert 'update' not in vars(env.axes[0]) and 'set' not in vars(env.config)


def test_completed_vibration_is_durable_without_restart(env):
    with env.stage('SHAPER_CALIBRATE', env.attempt): vibration(env)
    assert env.disk().getfloat('input_shaper', 'shaper_freq_y') == 55.
    assert env.axes[0].params.shaper_freq == 55.
    assert env.shaper.updates == []  # No rollback or redundant update on success.


def test_foreign_equal_value_write_revokes_checkpoint_authority(env):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError, match='Another command changed'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pid(env)
            env.actor[0] = object()
            env.config.set('extruder', 'pid_kp', '31')
            env.actor[0] = env.owned_actor
    assert env.path.read_bytes() == raw
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '31'
    assert env.config.autosave.fileconfig.get('extruder', 'pid_ki') == '5'


def test_foreign_unrelated_write_is_preserved_but_not_saved(env):
    with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
        pid(env)
        env.actor[0] = object()
        env.config.set('extruder', 'rotation_distance', '22.1')
        env.actor[0] = env.owned_actor
    assert env.disk().get('extruder', 'rotation_distance') == '21.6485'
    assert env.config.autosave.fileconfig.get('extruder', 'rotation_distance') == '22.1'


def test_foreign_shaper_update_is_preserved_on_failed_type(env):
    with pytest.raises(ValueError, match='Another command changed the vibration'):
        with env.stage('SHAPER_CALIBRATE', env.attempt):
            vibration(env)
            env.actor[0] = object()
            env.axes[0].update(('zvd', 42.))
            env.actor[0] = env.owned_actor
            env.axes[0].update(('ei', 60.))
    assert env.axes[0].params.shaper_type == 'zvd'
    assert env.axes[0].params.shaper_freq == 42.
    assert env.axes[1].params.shaper_freq == 40.
    assert env.disk().getfloat('input_shaper', 'shaper_freq_x') == 40.


@pytest.mark.parametrize('fault', ['missing', 'unexpected', 'invalid'])
def test_incomplete_or_out_of_scope_results_never_publish(env, fault):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            if fault == 'missing': env.config.set('extruder', 'pid_kp', '31')
            else:
                pid(env)
                if fault == 'unexpected': env.config.set('extruder', 'rotation_distance', '22')
                else: env.config.set('extruder', 'pid_ki', 'nan')
    assert env.path.read_bytes() == raw
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'


def test_manual_disk_edit_during_measurement_is_not_overwritten(env):
    with pytest.raises(ValueError, match='changed during calibration measurement'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pid(env)
            env.path.write_text(env.path.read_text().replace('max_accel: 5000', 'max_accel: 6000'))
    assert env.disk().get('printer', 'max_accel') == '6000'
    assert env.disk().get('extruder', 'pid_kp') == '20'


@pytest.mark.parametrize('fault', ['fsync', 'replace', 'readback'])
def test_publication_failures_are_explicit_and_leave_complete_files(env, monkeypatch, fault):
    raw = env.path.read_bytes()
    if fault == 'fsync':
        monkeypatch.setattr(checkpoints.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('fsync failed')))
    elif fault == 'replace':
        monkeypatch.setattr(checkpoints.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('replace failed')))
    else:
        original = checkpoints._read_regular
        calls = []
        def read(path):
            result = original(path); calls.append(True)
            return (b'changed after replace', result[1]) if len(calls) == 4 else result
        monkeypatch.setattr(checkpoints, '_read_regular', read)
    with pytest.raises((ValueError, OSError)):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt): pid(env)
    assert env.path.exists() and env.attempt['checkpoints'][-1]['state'] == 'unconfirmed'
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'
    assert env.disk().get('extruder', 'pid_kp') == ('31' if fault == 'readback' else '20')
    if fault != 'readback': assert env.path.read_bytes() == raw
    assert not list(env.path.parent.glob('.wmp-calibration-*'))


@pytest.mark.parametrize('changed', ['request', 'actor', 'shutdown', 'openace'])
def test_changed_owner_cannot_publish(env, changed):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError, match='owner or printer state changed'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pid(env)
            if changed == 'request': env.cal._current_attempt = dict(env.attempt)
            elif changed == 'actor': env.actor[0] = object()
            elif changed == 'shutdown': env.printer.is_shutdown = lambda: True
            else: env.objects['openace'] = object()
    assert env.path.read_bytes() == raw


@pytest.fixture
def bound(env):
    from test_calibration_commands import setup
    p, runner = setup()
    runner.checkpoints = checkpoints.Checkpoints(runner)  # Actual publisher, not the command unit-test stub.
    p.error = RuntimeError
    p.get_start_args = lambda: {'config_file': str(env.path)}
    p.objects.update(configfile=env.config, input_shaper=env.shaper)
    env.config.printer = p
    runner._heater_ownership.current_actor = lambda: env.actor[0]
    env.p, env.runner = p, runner
    return env


def test_bound_mesh_saved_before_later_pid_failure(bound):
    from test_calibration_tickets import ticket
    env = bound
    def run(command):
        if command == 'G29': mesh(env)
        else:
            pid(env)
            raise RuntimeError('PID failed')
    env.p.on_run = run
    env.runner.cmd_run(ticket(env.runner, 'G29', 1))
    saved = env.path.read_bytes()
    assert env.runner.attempt_status()['earlier_results']
    with pytest.raises(RuntimeError, match='PID failed'):
        env.runner.cmd_run(ticket(env.runner, 'PID_CALIBRATE HEATER=extruder TARGET=220', 1, 1))
    assert env.path.read_bytes() == saved and env.disk().has_section('bed_mesh default')
    assert env.disk().get('extruder', 'pid_kp') == '20'
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'
    assert not any(command.startswith('SAVE_CONFIG') for command in env.p.sent)


def test_late_cancel_keeps_completed_bound_type(bound):
    from test_calibration_tickets import ticket
    from test_calibration_cancel_ingress import Request
    env = bound
    def complete(command):
        mesh(env)
        env.runner.handle_cancel(Request(env.runner))
    env.p.on_run = complete
    with pytest.raises(RuntimeError, match='cancellation requested; stopped after G29'):
        env.runner.cmd_run(ticket(env.runner, 'G29', 1))
    attempt = env.runner.attempt_status()
    assert attempt['earlier_results'] and attempt['checkpoints'][0]['state'] == 'saved'
    assert env.disk().has_section('bed_mesh default')
    with pytest.raises(RuntimeError):
        env.runner.cmd_run(ticket(env.runner, 'SHAPER_CALIBRATE', 1, 1))
    assert env.p.sent == ['G29']


def test_cancel_inside_bound_type_discards_partial_result(bound):
    from test_calibration_tickets import ticket
    from test_calibration_cancel_ingress import Request
    env = bound
    raw = env.path.read_bytes()
    def partial(command):
        mesh(env)
        env.runner.handle_cancel(Request(env.runner))
        env.runner.check_cancel('before another mesh point')
    env.p.on_run = partial
    with pytest.raises(RuntimeError, match='before another mesh point'):
        env.runner.cmd_run(ticket(env.runner, 'G29', 1))
    assert env.path.read_bytes() == raw
    assert not env.runner.attempt_status()['earlier_results']
    assert not env.config.autosave.fileconfig.has_section('bed_mesh default')


def test_soft_fault_after_bound_return_cannot_checkpoint(bound):
    from test_calibration_tickets import ticket
    env = bound
    raw = env.path.read_bytes()
    def faulty(command):
        pid(env)
        env.p.fail = -3
    env.p.on_run = faulty
    with pytest.raises(RuntimeError):
        env.runner.cmd_run(ticket(env.runner, 'PID_CALIBRATE HEATER=extruder TARGET=220', 1))
    assert env.path.read_bytes() == raw
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'
    assert env.runner.attempt_status()['checkpoints'][0]['state'] == 'unconfirmed'


def test_pending_second_axis_is_restored_through_bound_failure(bound):
    from test_calibration_tickets import ticket
    env = bound
    def faulty(command):
        env.axes[0].update(('ei', 55.))
        env.config.set('input_shaper', 'shaper_type_x', 'ei')
        env.config.set('input_shaper', 'shaper_freq_x', '55')
        raise RuntimeError('second axis cancelled')
    env.p.on_run = faulty
    with pytest.raises(RuntimeError, match='second axis cancelled'):
        env.runner.cmd_run(ticket(env.runner, 'SHAPER_CALIBRATE', 1))
    assert env.axes[0].params.shaper_freq == 40.
    assert env.config.autosave.fileconfig.get('input_shaper', 'shaper_freq_x') == '40'
    assert env.disk().get('input_shaper', 'shaper_freq_x') == '40'


def test_owned_result_removed_before_return_is_not_checkpointed(env):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError, match='complete owned result'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pid(env)
            env.config.remove_section('extruder')
    assert env.path.read_bytes() == raw


@pytest.mark.parametrize('points', ['nan, 0\n0, 0', '0, 0', '0, 0, 0\n0, 0, 0'])
def test_invalid_mesh_is_not_saved(env, points):
    raw = env.path.read_bytes()
    with pytest.raises(ValueError, match='mesh result is invalid'):
        with env.stage('G29', env.attempt):
            mesh(env)
            env.config.set('bed_mesh default', 'points', points)
    assert env.path.read_bytes() == raw


def test_directory_fsync_failure_never_claims_confirmed_save(env, monkeypatch):
    original = checkpoints.os.fsync
    calls = []
    def fsync(fd):
        calls.append(fd)
        if len(calls) == 2: raise OSError('directory fsync failed')
        original(fd)
    monkeypatch.setattr(checkpoints.os, 'fsync', fsync)
    with pytest.raises(OSError, match='directory fsync failed'):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt): pid(env)
    assert env.disk().get('extruder', 'pid_kp') == '31'  # Complete candidate, durability unconfirmed.
    assert env.attempt['checkpoints'][-1]['state'] == 'unconfirmed'
    assert env.config.autosave.fileconfig.get('extruder', 'pid_kp') == '20'


def test_linked_config_is_refused_before_measurement(env):
    target = env.path.with_name('real.cfg')
    env.path.rename(target); env.path.symlink_to(target)
    raw = target.read_bytes()
    with pytest.raises(OSError):
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
            pytest.fail('measurement admitted for linked config')
    assert target.read_bytes() == raw


def test_runtime_rollback_failure_blocks_automatic_motion_cleanup(env):
    def fail(): raise ValueError('shaper update failed')
    env.shaper._update_input_shaping = fail
    with pytest.raises(ValueError, match='rollback unconfirmed'):
        with env.stage('SHAPER_CALIBRATE', env.attempt):
            vibration(env)
            raise ValueError('measurement failed')
    assert 'shaper update failed' in env.attempt['cancel_motion_error']
    assert env.attempt['checkpoints'][-1]['state'] == 'unconfirmed'


def test_checkpoint_status_and_files_stay_bounded(env):
    for index in range(25):
        env.attempt['next'] = index + 1
        with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt): pid(env)
    assert len(env.attempt['checkpoints']) == 16
    assert env.attempt['checkpoints'][-1]['sequence'] == 24
    assert all(item['state'] == 'saved' for item in env.attempt['checkpoints'])
    assert len(list(env.path.parent.iterdir())) == 1


def test_stale_ticket_cannot_checkpoint_again(bound):
    from test_calibration_tickets import ticket
    env = bound
    env.p.on_run = lambda command: mesh(env) if command == 'G29' else None
    old = ticket(env.runner, 'G29', 1)
    env.runner.cmd_run(old)
    env.runner.cmd_run(ticket(env.runner, 'M400', 2))
    raw = env.path.read_bytes()
    with pytest.raises(RuntimeError, match='retired'):
        env.runner.cmd_run(old)
    assert env.path.read_bytes() == raw
    assert env.runner._current_attempt['request'] != old.binding['REQUEST']


def test_factory_pid_producer_preserves_unrelated_autosave_tuning(env):
    import ast
    import logging
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/pid_calibrate.py'
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'PIDCalibrate')
    tune = NS(check_busy=lambda *args: False, calc_final_pid=lambda: (31., 6., 35.))
    namespace = {'logging': logging, 'ControlAutoTune': lambda *args: tune}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
    heater = NS(control=object(), get_name=lambda: 'extruder')
    def set_control(value):
        old = heater.control; heater.control = value; return old
    heater.set_control = set_control
    env.objects.update(toolhead=NS(get_last_move_time=lambda: 0.),
        heaters=NS(lookup_heater=lambda name: heater, set_temperature=lambda *args: None))
    env.printer.config_error, env.printer.command_error = ValueError, ValueError
    runner = namespace['PIDCalibrate'].__new__(namespace['PIDCalibrate']); runner.printer = env.printer
    command = NS(get=lambda key: 'extruder', get_float=lambda key: 220.,
                 get_int=lambda key, default: default, respond_info=lambda value: None, error=ValueError)
    with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
        runner.cmd_PID_CALIBRATE(command)
    assert env.disk().get('extruder', 'rotation_distance') == '21.6485'
    assert env.disk().get('extruder', 'pid_kp') == '31.000'
    assert env.config.autosave.fileconfig.get('extruder', 'rotation_distance') == '21.6485'


@pytest.mark.parametrize('backport', [False, True], ids=['factory', 'backport'])
def test_retained_shaper_producer_matches_checkpoint_scope(env, backport):
    import ast
    path = (ROOT / 'klipper_backport/input_shaper/klippy/extras/shaper_calibrate.py' if backport else
            ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/shaper_calibrate.py')
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'ShaperCalibrate')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'save_params')
    namespace = {}; exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    helper = type('RetainedShaperWriter', (), {'save_params': namespace['save_params']})()
    with env.stage('SHAPER_CALIBRATE', env.attempt):
        for name in 'xy': helper.save_params(env.config, name, 'ei', 55.)
    assert env.disk().get('input_shaper', 'shaper_freq_x') == '55.0'
    assert env.disk().get('input_shaper', 'shaper_freq_y') == '55.0'


def test_foreign_keyword_config_calls_retain_their_api(env):
    with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
        pid(env)
        env.actor[0] = object()
        env.config.set(section='printer', option='max_accel', value='10000')
        env.config.remove_section(section='unused')
        env.actor[0] = env.owned_actor
    assert env.config.status_save_pending['printer']['max_accel'] == '10000'
    assert env.disk().get('printer', 'max_accel') == '5000'


def test_checkpointed_types_keep_final_factory_restart_receipt(bound):
    from test_calibration_tickets import ticket
    from test_calibration_commands import module
    env = bound
    env.p.objects['gcode'] = env.p
    env.p.restarts = []
    env.p.request_restart = env.p.restarts.append
    def run(command):
        if command == 'G29': mesh(env)
        elif command == 'PID_CALIBRATE HEATER=extruder TARGET=220': pid(env)
        elif command == 'SAVE_CONFIG': env.config.cmd_SAVE_CONFIG(NS())
    env.p.on_run = run
    env.runner.cmd_run(ticket(env.runner, 'G29', 1))
    env.runner.cmd_run(ticket(env.runner, 'PID_CALIBRATE HEATER=extruder TARGET=220', 1, 1))
    assert env.p.restarts == []
    env.runner.cmd_run(ticket(env.runner, 'SAVE_CONFIG', 1, 2))
    assert env.p.restarts == ['firmware_restart']
    assert env.runner.save_result['state'] == 'saved'
    loaded = env.disk()
    env.config.status_raw_config = {section: dict(loaded.items(section, raw=True)) for section in loaded.sections()}
    env.config.status_save_pending = {}
    env.config.save_config_pending = False
    fresh = module.CalibrationCommands(env.p, env.p)
    fresh._restore_save_result()
    assert fresh.save_result['state'] == 'confirmed'


def test_checkpointed_mesh_keeps_one_early_save_after_offset_failure(bound):
    from test_calibration_tickets import ticket
    env = bound
    env.p.objects['gcode'] = env.p
    env.p.restarts = []
    env.p.request_restart = env.p.restarts.append
    def run(command):
        if command == 'G29': mesh(env)
        elif command == '_WMP_SCRUB_HEAD T=0': raise RuntimeError('offset stage failed')
        elif command == 'SAVE_CONFIG': env.config.cmd_SAVE_CONFIG(NS())
    env.p.on_run = run
    env.runner.cmd_run(ticket(env.runner, 'G29', 1))
    with pytest.raises(RuntimeError, match='offset stage failed'):
        env.runner.cmd_run(ticket(env.runner, '_WMP_SCRUB_HEAD T=0', 1, 1))
    assert env.runner.attempt_status()['early_save_available']
    assert env.disk().has_section('bed_mesh default')
    env.runner.cmd_run(ticket(env.runner, 'SAVE_CONFIG', 1, 2))
    assert env.p.restarts == ['firmware_restart']
    assert env.runner.save_result['state'] == 'saved'
    assert env.runner.attempt_status()['state'] == 'failed'
    with pytest.raises(RuntimeError):
        env.runner.cmd_run(ticket(env.runner, 'SAVE_CONFIG', 1, 3))
    assert env.p.restarts == ['firmware_restart']


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_external_owner_keeps_original_persistence_policy(env, owner):
    env.objects[owner] = object()
    raw = env.path.read_bytes()
    with env.stage('PID_CALIBRATE HEATER=extruder TARGET=220', env.attempt):
        pid(env)
    assert env.path.read_bytes() == raw and 'checkpoints' not in env.attempt
    assert 'set' not in vars(env.config) and 'remove_section' not in vars(env.config)
