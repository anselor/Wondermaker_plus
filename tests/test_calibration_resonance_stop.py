"""Bound vibration Cancel executes the retained factory/backport loops."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from test_calibration_cancel_cleanup import rig as cleanup_rig, cancel_stage

ROOT = Path(__file__).resolve().parents[1]


def source_classes(backport):
    path = (ROOT / 'klipper_backport/input_shaper/klippy/extras/resonance_tester.py' if backport else
            ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/resonance_tester.py')
    if not path.exists(): pytest.skip('retained factory resonance source unavailable')
    keep = {'TestAxis', 'VibrationPulseTest', 'ResonanceTestExecutor', 'ResonanceTester',
            'JunctionSpeedLimits', '_set_max_accel', '_limit_next_junction_speed'}
    nodes = [node for node in ast.parse(path.read_text()).body
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in keep]
    namespace = {'math': math, 'JUNCTION_V2_UNLIMITED': 999999999.9}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class AxisShaper:
    def __init__(self, disabled=False):
        self.n, self.A, self.T = 2, [0.4, 0.6], [0., .01]
        self.saved = None
        if disabled: self.disable_shaping()
    def disable_shaping(self):
        if self.n and self.saved is None: self.saved = self.n, self.A, self.T
        self.n, self.A, self.T = 0, [], []
    def enable_shaping(self):
        if self.saved is not None:
            self.n, self.A, self.T = self.saved
            self.saved = None


class Toolhead:
    def __init__(self):
        self.max_velocity, self.max_accel, self.minimum_cruise_ratio = 300., 5000., .5
        self.position, self.moves, self.waits = [100., 100., 10., 0.], [], 0
        self.on_move = lambda count: None
        self.lookahead = NS(get_last=lambda: None)
        self.fail_restore = False
    def get_status(self, now):
        return {key: getattr(self, key) for key in ('max_velocity', 'max_accel', 'minimum_cruise_ratio')}
    def get_position(self): return list(self.position)
    def move(self, position, velocity):
        self.position = list(position)
        self.moves.append((list(position), velocity))
        self.on_move(len(self.moves))
    def manual_move(self, position, velocity): self.position[:3] = position[:3]
    def dwell(self, duration): pass
    def wait_moves(self): self.waits += 1
    def get_last_move_time(self): return 0.
    def cmd_M204(self, command): self.max_accel = command['S']
    def _calc_junction_deviation(self): pass
    def limit_next_junction_speed(self, speed): pass


class Client:
    def __init__(self): self.is_finished, self.finishes = False, 0
    def finish_measurements(self): self.is_finished = True; self.finishes += 1
    def has_valid_samples(self): return True


@pytest.fixture(params=[False, True], ids=['factory', 'backport'])
def vibration(request):
    import sys
    sys.path.insert(0, str(ROOT / 'klipper_extras'))
    from wmp_stop_points import StopPoints
    ns = source_classes(request.param)
    backport = request.param
    toolhead = Toolhead()
    attempts = {'request': 'a' * 32, 'state': 'pending', 'cancel_requested': False}
    actor = [object()]
    owned_actor = actor[0]
    tracker = NS(enabled=True, current_actor=lambda: actor[0], contexts={owned_actor: attempts['request']})
    objects = {}
    printer = NS(lookup_object=lambda key, default=None: objects.get(key, default),
                 get_reactor=lambda: NS(monotonic=lambda: 1., pause=lambda now: now),
                 is_shutdown=lambda: False, quick_stop_flag=False)
    gcode = NS(error=ValueError, create_gcode_command=lambda name, line, args: args)
    sent = []
    def script(command):
        sent.append(command)
        for item in command.split()[1:]:
            key, value = item.split('=')
            attr = {'VELOCITY': 'max_velocity', 'ACCEL': 'max_accel',
                    'MINIMUM_CRUISE_RATIO': 'minimum_cruise_ratio'}[key]
            if not toolhead.fail_restore or float(value) != 5000.:
                setattr(toolhead, attr, float(value))
    gcode.run_script_from_command = script
    shapers = [AxisShaper(), AxisShaper(disabled=True)]
    shaper = NS(get_shapers=lambda: shapers, updates=0)
    def update(): shaper.updates += 1
    shaper._update_input_shaping = update
    shaper.disable_shaping = lambda: [axis.disable_shaping() for axis in shapers]
    shaper.enable_shaping = lambda: [axis.enable_shaping() for axis in shapers]
    clients = []
    def start():
        client = Client(); clients.append(client); return client
    chip = NS(name='adxl345', start_internal_client=start)
    tester = ns['ResonanceTester'].__new__(ns['ResonanceTester'])
    tester.printer, tester.move_speed = printer, 50.
    tester.accel_chips = [('xy', chip)]
    if backport:
        sequence = [(0.05, 300., 5.), (.1, -300., 5.), (.15, -300., 6.), (.2, 300., 6.)]
        tester.generator = NS(prepare_test=lambda *args, **kwargs: None, gen_test=lambda: sequence)
        tester.probe_points = [(100., 100., 10.)]
        executor = ns['ResonanceTestExecutor'].__new__(ns['ResonanceTestExecutor'])
        executor.printer, executor.gcode = printer, gcode
        tester.executor = executor
    else:
        pulse = ns['VibrationPulseTest'].__new__(ns['VibrationPulseTest'])
        pulse.printer, pulse.gcode = printer, gcode
        pulse.min_freq, pulse.max_freq, pulse.accel_per_hz, pulse.hz_per_sec = 5., 5.4, 75., 1.
        pulse.probe_points = [(100., 100., 10.)]
        tester.test = pulse
    def check(label, attempt=None):
        if attempts['cancel_requested']:
            attempts['cancel_phase'] = label
            raise ValueError('Calibration cancellation requested; stopped ' + label)
    calibration = NS(printer=printer, active=True, executing=attempts, _current_attempt=attempts,
                     _heater_ownership=tracker, check_cancel=check)
    objects.update(toolhead=toolhead, gcode=gcode, input_shaper=shaper,
                   configfile=NS(), resonance_tester=tester,
                   wmp_recovery=NS(calibration=calibration))
    stops = StopPoints(NS(printer=printer))
    original = tester._run_test
    stops._install_resonance_stop()
    wrapped = tester._run_test
    stops._install_resonance_stop()
    assert tester._run_test is wrapped
    command = NS(get_float=lambda key, default, **kwargs: default,
                 get_int=lambda key, default: default, respond_info=lambda text: None, error=ValueError)
    axes = [ns['TestAxis']('x'), ns['TestAxis']('y')]
    processed = []
    def process(*args): processed.append(args); return NS(add_data=lambda data: None)
    helper = NS(process_accelerometer_data=process)
    tester.get_filename = lambda *args: 'unused'
    def run(use_original=False, selected=None):
        fn = original if use_original else tester._run_test
        args = (command, axes, helper, 'test') if backport else (command, axes, helper)
        return fn(*args, accel_chips=selected)
    return NS(run=run, attempts=attempts, actor=actor, owned_actor=owned_actor, printer=printer,
              calibration=calibration, toolhead=toolhead, shapers=shapers, shaper=shaper,
              objects=objects, chip=chip, clients=clients, processed=processed, sent=sent, tester=tester,
              stops=stops, backport=backport)


@pytest.mark.parametrize('after', [1, 2, 4])
def test_cancel_between_segments_drains_restores_and_closes(vibration, after):
    env = vibration
    import copy
    before = copy.deepcopy([(s.n, s.A, s.T, s.saved) for s in env.shapers])
    env.toolhead.on_move = lambda count: count == after and env.attempts.update(cancel_requested=True)
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.run()
    assert len(env.toolhead.moves) == after
    assert env.toolhead.get_status(1.) == {'max_velocity': 300., 'max_accel': 5000., 'minimum_cruise_ratio': .5}
    assert [(s.n, s.A, s.T, s.saved) for s in env.shapers] == before
    assert env.clients and all(c.is_finished and c.finishes == 1 for c in env.clients)
    assert env.processed == []
    assert 'move' not in vars(env.toolhead) and 'dwell' not in vars(env.toolhead)
    assert not env.attempts.get('cancel_motion_error')
    assert env.toolhead.waits >= 2
    assert all(command.startswith('SET_VELOCITY_LIMIT ') for command in env.sent)


def test_normal_run_keeps_motion_and_results(vibration):
    env = vibration
    result = env.run()
    assert len(result) == 2 and len(env.processed) == 2
    assert all(c.finishes == 1 for c in env.clients)
    assert env.toolhead.max_accel == 5000. and env.toolhead.max_velocity == 300.
    assert env.shapers[1].saved is not None and env.shapers[1].n == 0
    assert not env.attempts.get('cancel_motion_error')


def test_different_greenlet_does_not_see_calibration_cancel(vibration):
    env = vibration
    env.actor[0] = object(); env.attempts['cancel_requested'] = True
    env.run()
    assert len(env.processed) == 2


def test_stale_or_external_owner_stops_before_more_motion(vibration):
    env = vibration
    env.toolhead.on_move = lambda count: env.objects.update(openace=object())
    with pytest.raises(ValueError, match='command owner changed'):
        env.run()
    assert len(env.toolhead.moves) == 1
    assert all(c.is_finished for c in env.clients)


def test_restore_failure_marks_cleanup_unconfirmed(vibration):
    env = vibration
    env.toolhead.fail_restore = True
    env.toolhead.on_move = lambda count: env.attempts.update(cancel_requested=True)
    with pytest.raises(ValueError, match='Vibration cleanup unconfirmed'):
        env.run()
    assert 'restoration was not confirmed' in env.attempts['cancel_motion_error']
    assert env.shapers[0].n == 2
    assert all(c.is_finished for c in env.clients)


def test_unconfirmed_vibration_restore_prevents_automatic_dock():
    p, gcode, runner, stored, writes = cleanup_rig()
    runner._current_attempt['cancel_motion_error'] = 'Vibration motion restoration unconfirmed'
    result = cancel_stage(runner, gcode, 'M400')
    assert result['state'] == 'incomplete'
    assert 'Vibration motion restoration unconfirmed' in result['error']
    assert 'PARK_CURRENT_TOOL' not in gcode.sent


def test_normal_guard_preserves_the_original_move_sequence(vibration):
    import copy
    env = vibration
    state = copy.deepcopy([(s.n, s.A, s.T, s.saved) for s in env.shapers])
    env.run(use_original=True)
    expected = list(env.toolhead.moves)
    env.toolhead.moves.clear(); env.toolhead.position = [100., 100., 10., 0.]
    for shaper, values in zip(env.shapers, state):
        shaper.n, shaper.A, shaper.T, shaper.saved = copy.deepcopy(values)
    env.run()
    assert env.toolhead.moves == expected


def test_explicit_accelerometer_is_closed_on_cancel(vibration):
    env = vibration
    client = Client()
    selected = NS(name='other_adxl', start_internal_client=lambda: client)
    env.toolhead.on_move = lambda count: env.attempts.update(cancel_requested=True)
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.run(selected=[selected])
    assert client.is_finished and client.finishes == 1
    assert env.clients == [] and env.processed == []


def test_recording_close_failure_prevents_success_receipt(vibration):
    env = vibration
    client = Client()
    client.finish_measurements = lambda: (_ for _ in ()).throw(ValueError('ADC close failed'))
    selected = NS(name='other_adxl', start_internal_client=lambda: client)
    env.toolhead.on_move = lambda count: env.attempts.update(cancel_requested=True)
    with pytest.raises(ValueError, match='Vibration recording close failed: ADC close failed'):
        env.run(selected=[selected])
    assert env.toolhead.max_accel == 5000.
    assert env.shapers[0].n == 2
    assert 'ADC close failed' in env.attempts['cancel_motion_error']
    assert env.processed == []


def test_shutdown_does_not_send_restore_commands(vibration):
    env = vibration
    def shutdown(count):
        env.printer.is_shutdown = lambda: True
        env.attempts['cancel_requested'] = True
    env.toolhead.on_move = shutdown
    with pytest.raises(ValueError, match='Vibration cleanup unconfirmed'):
        env.run()
    assert 'Printer stopped' in env.attempts['cancel_motion_error']
    assert len(env.sent) == 1  # Test's admitted setup; no restoration G-code after shutdown.
    assert env.processed == []
    assert all(c.is_finished for c in env.clients)


def test_unrelated_callback_move_does_not_consume_cancel(vibration):
    env = vibration
    called = []
    def callback(count):
        if called: return
        called.append(True)
        env.attempts['cancel_requested'] = True
        env.actor[0] = object()
        try:
            env.toolhead.move([100., 100., 10., 0.], 20.)
        finally:
            env.actor[0] = env.owned_actor
    env.toolhead.on_move = callback
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.run()
    assert len(env.toolhead.moves) == 2
    assert env.processed == []


@pytest.fixture
def fitting(vibration, monkeypatch):
    import multiprocessing
    import sys
    import traceback
    import time
    from wmp_resonance_stop import install_calculation_stop
    env = vibration
    source = (ROOT / 'klipper_backport/input_shaper/klippy/extras/shaper_calibrate.py' if env.backport else
              ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/shaper_calibrate.py')
    if not source.exists(): pytest.skip('retained factory shaper helper unavailable')
    cls = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.ClassDef) and node.name == 'ShaperCalibrate')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'background_process_exec')
    namespace = {'multiprocessing': multiprocessing, 'traceback': traceback}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    helper_class = type('RetainedShaperHelper', (), {'background_process_exec': namespace['background_process_exec']})
    namespace = {'shaper_calibrate': NS(ShaperCalibrate=helper_class)}
    exec('def run(self): pass', namespace)
    anchor = type('TesterAnchor', (), {'_run_test': namespace['run']})()
    original = helper_class.background_process_exec
    install_calculation_stop(anchor._run_test)
    installed = helper_class.background_process_exec
    install_calculation_stop(anchor._run_test)
    assert helper_class.background_process_exec is installed
    helper = helper_class()
    helper.printer, helper.error = env.printer, ValueError
    env.objects['wm_material'] = NS(_stop_points=lambda: env.stops)
    monkeypatch.setitem(sys.modules, 'queuelogger', NS(clear_bg_logging=lambda: None))
    env.polls, env.logs, env.processes = [], [], []
    env.on_pause = lambda count: None
    def pause(now):
        env.polls.append(now)
        assert len(env.polls) < 500, 'calculation wait did not terminate'
        env.on_pause(len(env.polls))
        time.sleep(.005)
        return now
    reactor = NS(monotonic=lambda: 1., pause=pause)
    env.printer.get_reactor = lambda: reactor
    env.objects['gcode'].respond_info = lambda text, **kwargs: env.logs.append(text)
    process_factory = multiprocessing.Process
    def process(*args, **kwargs):
        instance = process_factory(*args, **kwargs)
        env.processes.append(instance)
        return instance
    monkeypatch.setattr(multiprocessing, 'Process', process)
    env.fit = helper.background_process_exec
    env.original_fit = lambda method, args: original(helper, method, args)
    env.helper, env.helper_original = helper, original
    try:
        yield env
    finally:
        for process in env.processes:
            if not process._closed:
                if process.is_alive():
                    process.kill()
                process.join(timeout=1.)
                process.close()


def test_fitting_normal_scalar_list_and_large_results(fitting):
    env = fitting
    for result in (None, 3.5, [1., 2., [3.]], b'x' * (2 * 1024 * 1024)):
        assert env.fit(lambda value: value, (result,)) == result
    assert env.processes and all(p._closed for p in env.processes)
    assert not env.attempts.get('cancel_motion_error')
    assert env.sent == []


def test_fitting_cancel_reaps_child_without_returning_result(fitting):
    import time
    env = fitting
    def work(): time.sleep(10.); return 'must not return'
    env.on_pause = lambda count: env.attempts.update(cancel_requested=True)
    start = time.monotonic()
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.fit(work, ())
    assert time.monotonic() - start < 2.
    assert len(env.processes) == 1 and env.processes[0]._closed
    assert env.attempts['cancel_phase'] == 'during shaper calculations'
    assert env.sent == []


def test_fitting_cancel_before_launch_creates_no_child(fitting):
    env = fitting
    env.attempts['cancel_requested'] = True
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.fit(lambda: None, ())
    assert env.processes == [] and env.sent == []


def test_fitting_remote_error_reaps_child(fitting):
    env = fitting
    def fail(): raise ValueError('bad fit')
    with pytest.raises(ValueError, match='Error in remote calculation:.*') as error:
        env.fit(fail, ())
    assert 'bad fit' in str(error.value)
    assert all(p._closed for p in env.processes)


def test_fitting_child_exit_without_result_does_not_hang(fitting):
    import os
    env = fitting
    with pytest.raises(ValueError, match='ended without a result'):
        env.fit(lambda: os._exit(7), ())
    assert all(p._closed for p in env.processes)


def test_fitting_other_greenlet_uses_original_method(fitting):
    env = fitting
    env.actor[0] = object(); env.attempts['cancel_requested'] = True
    assert env.fit(lambda: 42., ()) == 42.
    # The vendor helper does not close the Process object. Keep test resources
    # tidy and use that difference as proof this call followed its original path.
    assert env.processes and not env.processes[0]._closed
    for process in env.processes: process.close()


def test_fitting_stale_owner_reaps_child(fitting):
    import time
    env = fitting
    env.on_pause = lambda count: setattr(env.calibration, '_current_attempt', dict(env.attempts))
    with pytest.raises(ValueError, match='command owner changed'):
        env.fit(lambda: time.sleep(10.), ())
    assert all(p._closed for p in env.processes)


def test_fitting_installed_through_actual_tester_namespace(fitting):
    env = fitting
    helper_class = type(env.helper)
    helper_class.background_process_exec = env.helper_original
    original_run = env.tester._run_test.original
    original_run.__func__.__globals__['shaper_calibrate'] = NS(ShaperCalibrate=helper_class)
    env.tester._run_test = original_run
    env.stops._install_resonance_stop()
    assert helper_class.background_process_exec._wmp_calculation_stop
    env.attempts['cancel_requested'] = True
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.helper.background_process_exec(lambda: 42., ())
    assert env.processes == []


def test_fitting_failed_terminate_still_kills_and_reaps(fitting):
    import time
    env = fitting
    def cancel(count):
        env.attempts['cancel_requested'] = True
        env.processes[0].terminate = lambda: (_ for _ in ()).throw(OSError('terminate unavailable'))
    env.on_pause = cancel
    with pytest.raises(ValueError, match='Calibration cancellation requested'):
        env.fit(lambda: time.sleep(10.), ())
    assert env.processes[0]._closed
    assert not env.attempts.get('cancel_motion_error')
