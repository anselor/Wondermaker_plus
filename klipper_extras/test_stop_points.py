"""Stop points recorded in the cancellation journal."""
import re

import pytest

pytest_plugins = ['test_wm_material']

STOP = {'phase': 'homed', 'label': 'after homing', 'state': 'homed; probe head attached and locked'}


def test_tool_selection_stop_text_preserves_already_mounted_probe_head():
    from wmp_stop_points import StopPoints
    label, state = StopPoints.STOP_POINTS['before_initial_tool']
    assert label == 'before print tool selection'
    assert state == 'homed; probing head remains attached'
    assert StopPoints.STOP_POINTS['initial_tool_ready'] == (
        'after print tool selection', 'print head selected and attached')


def _restore(material):
    material._restore_print_cancel()
    return material._print_cancel


def _write(material, record):
    material._write_recovery_json(material._cancellation()._print_cancel_path(), record)


def _begin(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material = fixture[0]
    material._begin_print_cancel('stop-point-job', binding)
    return material


def test_v3_record_with_stop_point_round_trips(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    material._record_stop_point(**STOP)
    assert material._print_cancel['version'] == 3
    assert len(material._print_cancel['stages']) == 6
    record = _restore(material)
    assert record['version'] == 3 and record['stop_point'] == STOP
    assert record['state'] == 'unknown'


def test_stage_update_keeps_version_3(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    material._record_stop_point(**STOP)
    material._cancellation()._print_cancel_stage('draining')
    assert material._print_cancel['version'] == 3


@pytest.mark.parametrize('bad', [{'phase': 'Homed', 'label': 'x', 'state': 'y'},
    {'phase': 'homed', 'label': 'x'}, {'phase': 'homed', 'label': 'x', 'state': 'y', 'extra': 1},
    'homed', {'phase': 'homed', 'label': 1, 'state': 'y'},
    {'phase': 'homed', 'label': 'x' * 161, 'state': 'y'}])
def test_v3_rejects_malformed_stop_point(managed_cancel_intent, bad):
    material = _begin(managed_cancel_intent)
    _write(material, dict(material._print_cancel, version=3, stop_point=bad))
    record = _restore(material)
    assert record['state'] == 'unknown'
    assert record['message'].startswith('Print cancellation record is unreadable')


def test_v3_without_stop_point_restores(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    _write(material, dict(material._print_cancel, version=3))
    assert 'stop_point' not in _restore(material)
    assert material._print_cancel['version'] == 3


def test_v2_record_still_restores(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    assert material._print_cancel['version'] == 2
    _write(material, dict(material._print_cancel))
    record = _restore(material)
    assert record['version'] == 2 and record['state'] == 'unknown'
    assert len(record['stages']) == 6


def test_v2_record_with_stop_point_is_unreadable(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    _write(material, dict(material._print_cancel, stop_point=dict(STOP)))
    record = _restore(material)
    assert record['state'] == 'unknown'
    assert record['message'].startswith('Print cancellation record is unreadable')


def _cancelled(legacy_cancel_routes):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects = fixture[0], fixture[1]
    objects['gcode'].run_script('CANCEL_PRINT')
    return material, objects, cleanup, handlers


def _point(phase='homed'):
    from test_wm_material import FakeCommand
    return FakeCommand(PHASE=phase)


def test_stop_point_noop_without_request(legacy_cancel_routes):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material = fixture[0]
    before = dict(getattr(material, '_print_cancel', {}))
    command = _point()
    assert handlers['_WMP_STOP_POINT'](command) is None
    assert getattr(material, '_print_cancel', {}) == before
    assert not hasattr(command, 'message')
    assert material.stop_requested() is None


def test_stop_point_raises_and_records_for_bound_job(legacy_cancel_routes):
    material, objects, cleanup, handlers = _cancelled(legacy_cancel_routes)
    assert material.stop_requested()['scope'] == 'print'
    with pytest.raises(ValueError, match='Print cancellation requested; stopped at after homing'):
        handlers['_WMP_STOP_POINT'](_point())
    assert material._print_cancel['stop_point']['phase'] == 'homed'
    assert material._print_cancel['version'] == 3
    assert cleanup == []


@pytest.mark.parametrize('change', ['handle', 'session', 'file', 'openace', 'AFC'])
def test_stop_point_noop_for_other_job_or_owner(legacy_cancel_routes, change):
    import io
    material, objects, cleanup, handlers = _cancelled(legacy_cancel_routes)
    if change == 'handle':
        objects['virtual_sdcard'].current_file = io.StringIO('other job')
    elif change == 'session':
        material.session_id = 'another-session'
    elif change == 'file':
        objects['print_stats'].filename = 'other.gcode'
    else:
        objects[change] = object()
    assert material.stop_requested() is None
    assert handlers['_WMP_STOP_POINT'](_point()) is None
    assert 'stop_point' not in material._print_cancel


@pytest.mark.parametrize('phase', ['nope', 'HOMED', 'a' * 49, ''])
def test_unknown_stop_phase_is_an_error_even_without_request(legacy_cancel_routes, phase):
    handlers = legacy_cancel_routes[3]
    with pytest.raises(ValueError, match='Unknown stop point PHASE='):
        handlers['_WMP_STOP_POINT'](_point(phase))


def test_stop_point_raises_even_when_persist_fails(legacy_cancel_routes, monkeypatch):
    material, objects, cleanup, handlers = _cancelled(legacy_cancel_routes)
    def fail(*args, **kwargs):
        raise OSError('disk')
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', fail)
    with pytest.raises(ValueError, match='Print cancellation requested; stopped at'):
        handlers['_WMP_STOP_POINT'](_point())
    assert material._print_cancel['persistence_error'] == 'disk'


def test_stop_waits_rejects_bad_enable(legacy_cancel_routes):
    from test_wm_material import FakeCommand
    handlers = legacy_cancel_routes[3]
    with pytest.raises(ValueError):
        handlers['_WMP_STOP_WAITS'](FakeCommand(ENABLE='2'))


def test_wait_region_closed_by_handle_change_or_reset(legacy_cancel_routes):
    import io
    from test_wm_material import FakeCommand
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects = fixture[0], fixture[1]
    enable = lambda value: handlers['_WMP_STOP_WAITS'](FakeCommand(ENABLE=value))
    assert material.stop_waits_open() is False
    enable('1')
    assert material.stop_waits_open() is True
    original = objects['virtual_sdcard'].current_file
    objects['virtual_sdcard'].current_file = io.StringIO('new job')
    assert material.stop_waits_open() is False
    objects['virtual_sdcard'].current_file = original
    enable('1')
    enable('0')
    assert material.stop_waits_open() is False
    enable('1')
    objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(ValueError):
        handlers['_WMP_STOP_POINT'](_point())
    assert material.stop_waits_open() is False


def test_stop_requested_none_after_restore(managed_cancel_intent):
    material = _begin(managed_cancel_intent)
    material._restore_print_cancel()
    assert material.stop_requested() is None


def test_reset_file_event_closes_wait_region(tmp_path):
    """Construct the real extra and fire the event the way Klipper sends it (no arguments)."""
    from test_combined_upgrade_lifecycle import Printer, Config
    from wm_material import WMMaterial
    printer = Printer(tmp_path)
    material = WMMaterial(Config(printer, tmp_path))
    handle = object()
    printer.objects['virtual_sdcard'].current_file = handle
    material._stop_waits = {'session': material.session_id, 'handle': handle}
    assert material.stop_waits_open() is True
    for callback in printer.events['virtual_sdcard:reset_file']:
        callback()
    assert material.stop_waits_open() is False


# Interruptible heat waits, driven against the retained vendor PrinterHeaters code.

def _vendor_heaters_class():
    import ast
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/'
              'klipper/klippy/extras/heaters.py')
    if not source.exists():
        pytest.skip('local vendor heater source is not present')
    cls = next(n for n in ast.parse(source.read_text()).body
               if isinstance(n, ast.ClassDef) and n.name == 'PrinterHeaters')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ('cmd_TEMPERATURE_WAIT', '_wait_for_temperature')]
    namespace = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)
    return type('VendorHeaters', (), {m.name: namespace[m.name] for m in methods})


class WaitCommand:
    def __init__(self, **args):
        self.args, self.raw, self.info = args, [], []
    def get(self, key):
        return self.args[key]
    def get_float(self, key, default, above=None):
        value = float(self.args.get(key, default))
        if above is not None and value <= above:
            raise ValueError('above')
        return value
    def error(self, message):
        return ValueError(message)
    def respond_raw(self, message):
        self.raw.append(message)
    def respond_info(self, message):
        self.info.append(message)


class Sensor:
    def __init__(self, readings):
        self.readings = list(readings)
    def get_temp(self, eventtime):
        return (self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]), 0.
    def check_busy(self, eventtime):
        return self.get_temp(eventtime)[0] < 200.


@pytest.fixture
def wait_env(managed_cancel_intent):
    from types import SimpleNamespace as NS
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects = fixture[0], fixture[1]
    printer = material.printer
    printer.quick_stop_flag = False
    printer.is_shutdown = lambda: False
    printer.get_start_args = lambda: {}
    env = NS(material=material, objects=objects, cleanup=cleanup, pauses=[], on_pause=None,
             handlers={}, forwarded=[], original_calls=[])
    def pause(eventtime):
        env.pauses.append(eventtime)
        assert len(env.pauses) < 50, 'runaway wait loop'
        if env.on_pause:
            env.on_pause(len(env.pauses))
        return eventtime + 1.
    printer.get_reactor().pause = pause
    host = _vendor_heaters_class()()
    host.printer, host.available_sensors = printer, ['extruder3', 'heater_bed']
    host.heaters = {'extruder3': Sensor([220.]), 'heater_bed': Sensor([20.])}
    host._get_temp = lambda eventtime: 'T:%d' % len(env.pauses)
    host.get_all_heaters = lambda: ['heater_bed', 'extruder', 'extruder1', 'extruder2', 'extruder3']
    objects['heaters'] = host
    toolhead = objects.setdefault('toolhead', NS())
    toolhead.get_last_move_time = lambda: 0.
    env.host = host
    env.vendor_wait = host.cmd_TEMPERATURE_WAIT
    env.vendor_heat = host._wait_for_temperature
    def spy(gcmd):
        env.original_calls.append(gcmd)
        return env.vendor_wait(gcmd)
    gcode = objects['gcode']
    handlers = env.handlers
    handlers.update(CANCEL_PRINT=lambda command: None, TEMPERATURE_WAIT=spy)
    def register(name, callback, **kwargs):
        old = handlers.pop(name, None)
        if callback is not None:
            handlers[name] = callback
        return old
    gcode.register_command = register
    gcode.run_script = lambda script: env.forwarded.append(script)
    gcode.error = ValueError
    material._cancel_routes_ready()
    return env


def _open(env):
    from test_wm_material import FakeCommand
    env.handlers['_WMP_STOP_WAITS'](FakeCommand(ENABLE='1'))
    assert env.material.stop_waits_open() is True


@pytest.mark.parametrize('readings,minimum,maximum', [([220., 90.], None, 102.5),
                                                      ([90., 220.], 217.5, 222.5),
                                                      ([50., 60., 61.], 59., 61.)])
def test_open_region_wait_matches_vendor_without_request(wait_env, readings, minimum, maximum):
    env = wait_env
    args = {'SENSOR': 'extruder3'}
    if minimum is not None: args['MINIMUM'] = minimum
    if maximum is not None: args['MAXIMUM'] = maximum
    results = []
    for use_wrapper in (False, True):
        if use_wrapper: _open(env)
        env.pauses.clear()
        env.host.heaters['extruder3'] = Sensor(readings)
        command = WaitCommand(**args)
        handler = env.handlers['TEMPERATURE_WAIT'] if use_wrapper else env.vendor_wait
        assert handler(command) is None
        results.append((len(env.pauses), command.raw, command.info))
    assert results[0] == results[1] and results[0][0] >= 1


@pytest.mark.parametrize('args,message', [({'SENSOR': 'nope', 'MINIMUM': 1}, "Unknown sensor 'nope'"),
    ({'SENSOR': 'extruder3'}, 'missing MINIMUM or MAXIMUM'),
    ({'SENSOR': 'extruder3', 'MINIMUM': 5, 'MAXIMUM': 3}, 'above')])
def test_open_region_wait_validation_matches_vendor(wait_env, args, message):
    env = wait_env
    _open(env)
    with pytest.raises(ValueError, match=message):
        env.vendor_wait(WaitCommand(**args))
    with pytest.raises(ValueError, match=message):
        env.handlers['TEMPERATURE_WAIT'](WaitCommand(**args))


@pytest.mark.parametrize('mode', ['debugoutput', 'quick_stop', 'shutdown'])
def test_open_region_wait_exits_match_vendor(wait_env, mode):
    env = wait_env
    printer = env.material.printer
    if mode == 'debugoutput': printer.get_start_args = lambda: {'debugoutput': 'x'}
    elif mode == 'quick_stop': printer.quick_stop_flag = True
    else: printer.is_shutdown = lambda: True
    _open(env)
    results = []
    for handler in (env.vendor_wait, env.handlers['TEMPERATURE_WAIT']):
        command = WaitCommand(SENSOR='extruder3', MAXIMUM=102.5)
        assert handler(command) is None
        results.append((len(env.pauses), command.raw, command.info))
    assert results[0] == results[1] and results[0][0] == 0
    assert results[0][2] == (['quick Stop, break'] if mode == 'quick_stop' else [])


def test_open_region_wait_raises_within_one_iteration(wait_env):
    env = wait_env
    _open(env)
    env.on_pause = lambda count: env.objects['gcode'].run_script('CANCEL_PRINT')
    command = WaitCommand(SENSOR='extruder3', MAXIMUM=102.5)
    with pytest.raises(ValueError, match='^Print cancellation requested; stopped while heating Head 4$'):
        env.handlers['TEMPERATURE_WAIT'](command)
    assert len(env.pauses) == 1
    assert env.material._print_cancel['stop_point']['phase'] == 'heating_extruder3'
    assert env.material._print_cancel['stop_point']['label'] == 'heating Head 4'
    assert env.material._print_cancel['version'] == 3
    assert env.material.stop_waits_open() is False
    assert env.cleanup == []


def test_open_region_wait_raises_on_entry_when_request_pending(wait_env):
    env = wait_env
    _open(env)
    env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(ValueError, match='stopped while heating Head 4'):
        env.handlers['TEMPERATURE_WAIT'](WaitCommand(SENSOR='extruder3', MAXIMUM=102.5))
    assert env.pauses == []


def test_closed_region_wait_ignores_stop_request(wait_env):
    env = wait_env
    env.objects['gcode'].run_script('CANCEL_PRINT')
    assert env.material.stop_requested() is not None and not env.material.stop_waits_open()
    command = WaitCommand(SENSOR='extruder3', MAXIMUM=102.5)
    env.on_pause = lambda count: env.host.heaters['extruder3'].readings.__setitem__(slice(None), [90.])
    env.handlers['TEMPERATURE_WAIT'](command)
    assert env.original_calls == [command]
    assert 'stop_point' not in env.material._print_cancel


def test_wait_wrapper_installs_once(wait_env):
    env = wait_env
    first, heat = env.handlers['TEMPERATURE_WAIT'], env.host._wait_for_temperature
    env.material._install_wait_wrappers()
    assert env.handlers['TEMPERATURE_WAIT'] is first
    assert env.host._wait_for_temperature is heat


@pytest.mark.parametrize('name,phase,label', [('heater_bed', 'heating_heater_bed', 'bed'),
    ('extruder', 'heating_extruder', 'Head 1'), ('extruder1', 'heating_extruder1', 'Head 2'),
    ('heater_generic chamber', 'heating_heater_generic_chamber', 'chamber')])
def test_wait_for_temperature_wrapper_raises_for_heater(wait_env, name, phase, label):
    from types import SimpleNamespace as NS
    env = wait_env
    heater = NS(name=name, check_busy=lambda eventtime: True)
    _open(env)
    env.on_pause = lambda count: env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(ValueError, match='^Print cancellation requested; stopped while heating ' + label + '$'):
        env.host._wait_for_temperature(heater)
    assert len(env.pauses) == 1
    assert env.material._print_cancel['stop_point']['phase'] == phase
    assert env.material.stop_waits_open() is False


def test_wait_for_temperature_prefers_get_name(wait_env):
    from types import SimpleNamespace as NS
    env = wait_env
    heater = NS(name='wrong', get_name=lambda: 'extruder2', check_busy=lambda eventtime: True)
    _open(env)
    env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(ValueError, match='while heating Head 3$'):
        env.host._wait_for_temperature(heater)
    assert env.material._print_cancel['stop_point']['phase'] == 'heating_extruder2'


def test_wait_for_temperature_matches_vendor_without_request(wait_env):
    from types import SimpleNamespace as NS
    env = wait_env
    gcode = env.material.printer.lookup_object('gcode')
    results = []
    for use_wrapper in (False, True):
        if use_wrapper: _open(env)
        env.pauses.clear()
        sensor = Sensor([50., 60., 250.])
        sent = []
        gcode.respond_raw = gcode.respond_info = sent.append
        heater = NS(name='extruder3', check_busy=sensor.check_busy)
        (env.host._wait_for_temperature if use_wrapper else env.vendor_heat)(heater)
        results.append((len(env.pauses), sent))
    assert results[0] == results[1] and results[0][0] == 2


@pytest.mark.parametrize('mode', ['debugoutput', 'quick_stop', 'shutdown'])
def test_wait_for_temperature_exits_match_vendor(wait_env, mode):
    from types import SimpleNamespace as NS
    env = wait_env
    printer = env.material.printer
    if mode == 'debugoutput': printer.get_start_args = lambda: {'debugoutput': 'x'}
    elif mode == 'quick_stop': printer.quick_stop_flag = True
    else: printer.is_shutdown = lambda: True
    _open(env)
    gcode = printer.lookup_object('gcode')
    results = []
    for use_wrapper in (False, True):
        sent = []
        gcode.respond_raw = gcode.respond_info = sent.append
        heater = NS(name='extruder3', check_busy=lambda eventtime: True)
        (env.host._wait_for_temperature if use_wrapper else env.vendor_heat)(heater)
        results.append((len(env.pauses), sent))
    assert results[0] == results[1] and results[0][0] == 0
    assert results[0][1] == (['quick Stop, break'] if mode == 'quick_stop' else [])


def test_closed_region_wait_for_temperature_delegates(wait_env):
    from types import SimpleNamespace as NS
    env = wait_env
    env.objects['gcode'].run_script('CANCEL_PRINT')
    gcode = env.material.printer.lookup_object('gcode')
    gcode.respond_raw = gcode.respond_info = lambda message: None
    sensor = Sensor([50., 250.])
    heater = NS(name='extruder3', check_busy=sensor.check_busy)
    env.host._wait_for_temperature(heater)
    assert len(env.pauses) == 1 and 'stop_point' not in env.material._print_cancel


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_wait_wrappers_inert_with_other_owner(wait_env, owner):
    env = wait_env
    _open(env)
    env.objects['gcode'].run_script('CANCEL_PRINT')
    env.objects[owner] = object()
    env.host.heaters['extruder3'] = Sensor([90.])
    command = WaitCommand(SENSOR='extruder3', MAXIMUM=102.5)
    env.handlers['TEMPERATURE_WAIT'](command)
    assert env.original_calls == [command]


def test_wait_wrappers_skipped_when_vendor_pieces_missing(legacy_cancel_routes):
    handlers = legacy_cancel_routes[3]
    assert 'TEMPERATURE_WAIT' not in handlers



# Bed mesh: the retained vendor ProbePointsHelper loop, stopped before moving to the next point.

PROBE_SOURCE = (__import__('pathlib').Path(__file__).resolve().parents[1] /
                'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/probe.py')
MESH_LABEL = '^Print cancellation requested; stopped during bed mesh, %d of %d points measured$'


def _vendor_points_helper_class():
    """ProbePointsHelper's probing loop and point moves, executed from the retained vendor source."""
    import ast
    from types import SimpleNamespace as NS
    if not PROBE_SOURCE.exists():
        pytest.skip('retained vendor probe unavailable')
    tree = ast.parse(PROBE_SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ProbePointsHelper')
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in
                ('start_probe', '_move', '_raise_tool', '_invoke_callback', '_move_next')]
    namespace = {'manual_probe': NS(verify_no_manual_probe=lambda printer: None)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), str(PROBE_SOURCE), 'exec'),
         namespace)
    return namespace['ProbePointsHelper']


class MeshRig:
    """A vendor ProbePointsHelper owned by bed_mesh, with a recording probe session and toolhead."""
    def __init__(self, printer, objects, gcode, points=5):
        from types import SimpleNamespace as NS
        self.moves, self.probed, self.finalized, self.ended = [], [], [], []
        self.on_probe = None
        helper = _vendor_points_helper_class().__new__(_vendor_points_helper_class())
        helper.printer, helper.gcode = printer, gcode
        helper.probe_points = [(10. * i, 20., 0.) for i in range(points)]
        helper.finalize_callback = lambda offsets, results: self.finalized.append(list(results))
        helper.use_offsets, helper.speed, helper.default_horizontal_move_z = False, 100., 5.
        helper.mcu_probe = NS(home_zero=lambda: None)
        self.helper = helper
        session = NS(pull_probed_results=lambda: list(self.probed),
                     end_probe_session=lambda: self.ended.append(True))
        def run_probe(gcmd):
            self.probed.append(self.moves[-1])
            if self.on_probe:
                self.on_probe(len(self.probed))
        session.run_probe = run_probe
        objects['probe'] = NS(get_probe_params=lambda gcmd: {'lift_speed': 5.},
                              get_offsets=lambda: (0., 0., 0.), start_probe_session=lambda gcmd: session)
        toolhead = objects.setdefault('toolhead', NS())
        toolhead.manual_move = lambda coord, speed: self.moves.append(tuple(coord))
        toolhead.wait_moves = lambda: None
        toolhead.dwell = lambda seconds: None
        toolhead.get_last_move_time = lambda: 0.
        objects['bed_mesh'] = NS(bmc=NS(probe_mgr=NS(probe_helper=helper)))

    def xy_points(self):
        return [move for move in self.moves if move[0] is not None]


class MeshCommand:
    def get(self, name, default=None): return default
    def get_float(self, name, default=None, **kwargs): return default
    def respond_info(self, message): pass


@pytest.fixture
def mesh_env(wait_env):
    env = wait_env
    env.objects['gcode'].respond_info = lambda message: None
    env.rig = MeshRig(env.material.printer, env.objects, env.objects['gcode'])
    env.material._install_mesh_stop()
    return env


def test_mesh_without_request_probes_every_point_and_finalizes(mesh_env):
    env = mesh_env
    _open(env)
    env.rig.helper.start_probe(MeshCommand())
    assert len(env.rig.xy_points()) == 5 and len(env.rig.finalized) == 1
    assert env.rig.ended == [True]
    assert env.material.stop_requested() is None


@pytest.mark.parametrize('after', [0, 2, 4])
def test_mesh_stops_before_next_point_without_finalizing(mesh_env, after):
    env = mesh_env
    _open(env)
    if after == 0:
        env.objects['gcode'].run_script('CANCEL_PRINT')
    else:
        env.rig.on_probe = lambda count: count == after and env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(ValueError, match=MESH_LABEL % (after, 5)):
        env.rig.helper.start_probe(MeshCommand())
    # The head was raised after the last point and never moved to the next one.
    assert len(env.rig.xy_points()) == after == len(env.rig.probed)
    assert env.rig.moves[-1] == (None, None, 5.)
    assert env.rig.finalized == []
    point = env.material._print_cancel['stop_point']
    assert point == {'phase': 'mesh_probing',
                     'label': 'bed mesh, %d of 5 points measured' % after,
                     'state': 'homed; probe head attached and raised; bed mesh not saved'}
    assert env.material._print_cancel['version'] == 3
    assert env.material.stop_waits_open() is False
    assert env.cleanup == []


def test_mesh_with_closed_region_ignores_request(mesh_env):
    env = mesh_env
    env.objects['gcode'].run_script('CANCEL_PRINT')
    assert env.material.stop_requested() is not None and not env.material.stop_waits_open()
    env.rig.helper.start_probe(MeshCommand())
    assert len(env.rig.finalized) == 1
    assert 'stop_point' not in env.material._print_cancel


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_mesh_stop_inert_with_other_owner(mesh_env, owner):
    env = mesh_env
    _open(env)
    env.objects['gcode'].run_script('CANCEL_PRINT')
    env.objects[owner] = object()
    env.rig.helper.start_probe(MeshCommand())
    assert len(env.rig.finalized) == 1


def test_mesh_stop_installs_once(mesh_env):
    env = mesh_env
    first = env.rig.helper._move_next
    env.material._install_mesh_stop()
    assert env.rig.helper._move_next is first


@pytest.mark.parametrize('missing', ['bed_mesh', 'bmc', 'probe_mgr', 'probe_helper', 'move_next'])
def test_mesh_stop_skipped_when_vendor_pieces_missing(wait_env, missing):
    from types import SimpleNamespace as NS
    env = wait_env
    helper = NS(probe_points=[])
    if missing != 'move_next':
        helper._move_next = lambda probe_num: None
    chain = {'bed_mesh': NS(bmc=NS(probe_mgr=NS(probe_helper=helper)))}
    if missing == 'bmc': chain['bed_mesh'] = NS()
    elif missing == 'probe_mgr': chain['bed_mesh'] = NS(bmc=NS())
    elif missing == 'probe_helper': chain['bed_mesh'] = NS(bmc=NS(probe_mgr=NS()))
    if missing != 'bed_mesh':
        env.objects['bed_mesh'] = chain['bed_mesh']
    env.material._install_mesh_stop()
    if missing != 'move_next':
        assert not hasattr(helper._move_next, '__wrapped__')


# End to end: rendered START_PRINT through the retained vendor dispatcher and the SD error path.

STUCK = {'probe_preheat': ('extruder1', 140.), 'bed_wait': ('heater_bed', 60.),
         'purge_wait': ('extruder1', 220.)}


def _render_start_print(params=None):
    import sys
    from pathlib import Path
    tests = str(Path(__file__).resolve().parents[1] / 'tests')
    if tests not in sys.path:
        sys.path.insert(0, tests)
    from test_stop_points_macros import render_start_print
    return render_start_print(params=params)


def _start_print_env(managed_cancel_intent, guarded_legacy_dispatch, stuck=None):
    """Drive START_PRINT through the vendor dispatcher with emulated macros and heaters.

    M190 and M109 expand as config/live/macros.cfg does. TEMPERATURE_WAIT is the
    vendor handler wrapped by an explicit _install_wait_wrappers() call, because the
    fixture's _cancel_routes_ready ran before the vendor heaters existed.
    """
    from types import SimpleNamespace as NS
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, states, calls, review, request, timers, body, locked = fixture
    printer = material.printer
    printer.quick_stop_flag = False
    printer.is_shutdown = lambda: False
    printer.get_start_args = lambda: {}
    env = NS(material=material, objects=objects, dispatcher=dispatcher, vendor=vendor, timers=timers,
             locked=locked, cleanup=managed_cancel_intent[2], ran=[], pauses=[], on_pause=None, targets={})
    def pause(eventtime):
        env.pauses.append(eventtime)
        assert len(env.pauses) < 50, 'runaway wait loop'
        if env.on_pause:
            env.on_pause(len(env.pauses))
        return eventtime + 1.
    printer.get_reactor().pause = pause
    class Heater:
        def __init__(self, name):
            self.name = name
        def get_temp(self, eventtime):
            target = env.targets.get(self.name, 0.)
            return (20. if (self.name, target) == stuck else target), target
    host = _vendor_heaters_class()()
    host.printer = printer
    host.available_sensors = ['heater_bed', 'extruder', 'extruder1', 'extruder2', 'extruder3']
    host.heaters = {name: Heater(name) for name in host.available_sensors}
    host._get_temp = lambda eventtime: 'T:%d' % len(env.pauses)
    host.get_all_heaters = lambda: [name for name in host.available_sensors if name in states]
    objects['heaters'] = host
    objects.setdefault('toolhead', NS()).get_last_move_time = lambda: 0.
    dispatcher.respond_raw = lambda message: None
    dispatcher.register_command('TEMPERATURE_WAIT', host.cmd_TEMPERATURE_WAIT)
    material._wait_wrappers_installed = False
    material._install_wait_wrappers()
    def run(script):
        # The fixture points the instance attribute at the cleanup recorder; use the vendor method.
        vendor.GCodeDispatch.run_script_from_command(dispatcher, script)
    env.run = run
    def record(gcmd):
        if gcmd.get_command():
            env.ran.append(gcmd.get_commandline())
    def set_heater(gcmd):
        record(gcmd)
        args = dict(re.findall(r'(\w+)=(\S+)', gcmd.get_commandline()))
        env.targets[args['HEATER']] = float(args['TARGET'])
    def m140(gcmd):
        record(gcmd)
        env.targets['heater_bed'] = gcmd.get_float('S', 0.)
    def m190(gcmd):
        # [gcode_macro M190]: M140, then TEMPERATURE_WAIT on heater_bed within S +/- 1.
        record(gcmd)
        s = gcmd.get_float('S')
        run('M140 S%g\nTEMPERATURE_WAIT SENSOR=heater_bed MINIMUM=%g MAXIMUM=%g' % (s, s - 1, s + 1))
    def m109(gcmd):
        # [gcode_macro M109]: SET_HEATER_TEMPERATURE, then TEMPERATURE_WAIT within S +/- 2.5.
        record(gcmd)
        s, tool = gcmd.get_float('S'), gcmd.get_int('T')
        heater = 'extruder' if tool == 0 else 'extruder%d' % tool
        run('SET_HEATER_TEMPERATURE HEATER=%s TARGET=%g\nTEMPERATURE_WAIT SENSOR=%s MINIMUM=%g MAXIMUM=%g'
            % (heater, s, heater, s - 2.5, s + 2.5))
    def recorded(handler):
        def call(gcmd):
            record(gcmd)
            return handler(gcmd)
        return call
    handlers = dispatcher.gcode_handlers
    for name in ('TEMPERATURE_WAIT', '_WMP_STOP_POINT', '_WMP_STOP_WAITS'):
        handlers[name] = recorded(handlers[name])
    handlers.update({'SET_HEATER_TEMPERATURE': set_heater, 'M140': m140, 'M190': m190, 'M109': m109,
                     'G1': record, 'M104': record})
    for name in ('G28', 'BED_MESH_CALIBRATE', 'T0', 'T1', 'T2', 'T3'):
        handlers[name] = record
    dispatcher.cmd_default = record
    objects['virtual_sdcard'].cmd_from_sd = True
    env.script = '\n'.join(_render_start_print())
    return env


def _motion_or_tool(lines):
    return [line for line in lines if re.match(r'(T\d|G28|G1\b.*\bE)', line.upper())]


def _finish_sd_error_cancel(env):
    workers = len(env.timers)
    env.objects['gcode'].run_script('CANCEL_PRINT')
    assert len(env.timers) == workers  # The SD error fallback coalesces into the same worker.
    env.objects['virtual_sdcard'].cmd_from_sd = False
    env.objects['print_stats'].state = 'error'
    env.locked[0] = False
    env.timers[-1].callback(5.)
    assert env.material._print_cancel['state'] == 'complete'
    assert _motion_or_tool(env.cleanup) == []
    assert not any(line.startswith('G1') for line in env.cleanup)


@pytest.mark.parametrize('stop_at', ['probe_preheat', 'bed_wait', 'purge_wait'])
def test_cancel_during_start_print_wait_stops_without_tool_change_or_purge(
        managed_cancel_intent, guarded_legacy_dispatch, stop_at):
    sensor, target = STUCK[stop_at]
    env = _start_print_env(managed_cancel_intent, guarded_legacy_dispatch, stuck=STUCK[stop_at])
    mark = []
    def cancel(count):
        if count == 1:
            mark.append(len(env.ran))
            env.objects['gcode'].run_script('CANCEL_PRINT')
    env.on_pause = cancel
    with pytest.raises(env.vendor.CommandError,
                       match='^Print cancellation requested; stopped while heating ' +
                       {'extruder1': 'Head 2', 'heater_bed': 'bed'}.get(sensor, sensor) + '$'):
        env.run(env.script)
    assert len(env.pauses) == 1 and mark
    assert env.ran[mark[0] - 1].startswith('TEMPERATURE_WAIT SENSOR=' + sensor)
    assert env.ran[mark[0]:] == []
    assert env.targets[sensor] == target
    if stop_at == 'probe_preheat':
        assert not any(line.startswith('G28') for line in env.ran)
    if stop_at != 'purge_wait':
        assert not any(re.match(r'T\d', line) for line in env.ran)
    assert [line for line in _motion_or_tool(env.ran) if not line.startswith('G28')] == \
        (['T1'] if stop_at == 'purge_wait' else [])
    point = env.material._print_cancel['stop_point']
    assert point['phase'].startswith('heating_') and point['phase'] == 'heating_' + sensor
    assert env.material.stop_waits_open() is False
    assert env.cleanup == []
    _finish_sd_error_cancel(env)


def test_cancel_between_steps_stops_at_next_stop_point(managed_cancel_intent, guarded_legacy_dispatch):
    env = _start_print_env(managed_cancel_intent, guarded_legacy_dispatch)
    def g28(gcmd):
        env.ran.append(gcmd.get_commandline())
        env.objects['gcode'].run_script('CANCEL_PRINT')
    env.dispatcher.gcode_handlers['G28'] = g28
    with pytest.raises(env.vendor.CommandError, match='^Print cancellation requested; stopped at after homing$'):
        env.run(env.script)
    at = next(i for i, line in enumerate(env.ran) if line.startswith('G28'))
    assert env.ran[at + 1:] == ['_WMP_STOP_POINT PHASE=homed']
    assert not any(line.startswith('M190') for line in env.ran)
    assert env.material._print_cancel['stop_point']['phase'] == 'homed'
    assert env.cleanup == []
    _finish_sd_error_cancel(env)


def test_cancel_during_start_print_bed_mesh_stops_before_next_point(managed_cancel_intent, guarded_legacy_dispatch):
    env = _start_print_env(managed_cancel_intent, guarded_legacy_dispatch)
    events = guarded_legacy_dispatch[2]
    rig = MeshRig(env.material.printer, env.objects, env.dispatcher)
    env.material._install_mesh_stop()
    def calibrate(gcmd):
        env.ran.append(gcmd.get_commandline())
        rig.helper.start_probe(gcmd)
    env.dispatcher.gcode_handlers['BED_MESH_CALIBRATE'] = calibrate
    rig.on_probe = lambda count: count == 2 and env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(env.vendor.CommandError, match=MESH_LABEL % (2, 5)):
        env.run(env.script)
    # The macro unwinds at BED_MESH_CALIBRATE: no mesh profile save or later step runs.
    assert env.ran[-1].startswith('BED_MESH_CALIBRATE PROFILE=wmp_print')
    assert rig.finalized == [] and len(rig.xy_points()) == 2
    # The vendor dispatcher reports the gcode error, which ends the probe session (probe.py).
    assert 'gcode:command_error' in events
    assert not any(re.match(r'T\d', line) for line in env.ran)
    assert env.material._print_cancel['stop_point']['phase'] == 'mesh_probing'
    assert env.material.stop_waits_open() is False
    assert env.cleanup == []
    _finish_sd_error_cancel(env)


def test_cancel_during_start_print_chamber_wait_uses_real_stop_points(managed_cancel_intent, guarded_legacy_dispatch):
    """r4's _WMP_WAIT_CHAMBER (wmp_print_preparation) consumes the real stop request."""
    env = _start_print_env(managed_cancel_intent, guarded_legacy_dispatch)
    env.script = '\n'.join(_render_start_print(params={'CHAMBER': '45'}))
    assert '_WMP_WAIT_CHAMBER TARGET=45.0 BED=60 HOLD=60.0' in env.script.splitlines()
    class Chamber:
        def get_temp(self, eventtime):
            return 20., 45.
    heaters = env.objects['heaters']
    heaters.lookup_heater = lambda name: Chamber() if name == 'chamber' else heaters.heaters[name]
    def wait_chamber(gcmd):
        env.ran.append(gcmd.get_commandline())
        env.material.cmd_WAIT_CHAMBER(env.dispatcher._get_extended_params(gcmd))
    env.dispatcher.gcode_handlers['_WMP_WAIT_CHAMBER'] = wait_chamber
    env.on_pause = lambda count: count == 2 and env.objects['gcode'].run_script('CANCEL_PRINT')
    with pytest.raises(env.vendor.CommandError,
                       match='^Print cancellation requested; stopped at during chamber preparation$'):
        env.run(env.script)
    assert env.ran[-1].startswith('_WMP_WAIT_CHAMBER')
    assert not any(line.startswith('BED_MESH_CALIBRATE') or re.match(r'T\d', line) for line in env.ran)
    assert env.material._print_cancel['stop_point'] == {
        'phase': 'chamber_preparation', 'label': 'during chamber preparation',
        'state': 'homed; chamber temperature stabilization interrupted'}
    assert env.material._print_cancel['version'] == 3
    assert env.cleanup == []
    _finish_sd_error_cancel(env)


# A stopped START_PRINT ends as print_stats "cancelled", not "error", through the vendor SD worker.

def _sd_print(managed_cancel_intent, guarded_legacy_dispatch, handler=None, stuck=None):
    """Run the retained VirtualSD.work_handler over a one-line file whose START_PRINT runs `handler`."""
    import io
    env = _start_print_env(managed_cancel_intent, guarded_legacy_dispatch, stuck=stuck)
    sd, stats = env.objects['virtual_sdcard'], env.objects['print_stats']
    env.handle = io.StringIO('START_PRINT\n')
    sd.current_file, sd.file_position, sd.file_size = env.handle, 0, 12
    sd.must_pause_work, sd.cmd_from_sd, sd.work_timer = False, False, object()
    sd.gcode = env.dispatcher
    env.dispatcher.gcode_handlers['START_PRINT'] = handler or (lambda gcmd: env.run(env.script))
    env.locked[0] = False
    env.scripts = []
    managed = env.dispatcher.run_script
    def run_script(script):
        before = len(env.timers)
        try:
            return managed(script)
        finally:
            env.scripts.append((script, before, len(env.timers)))
    env.dispatcher.run_script = run_script
    env.start = lambda: managed_cancel_intent[3](1.)  # vendor work_handler bound to this sd
    return env, sd, stats


def _complete_cleanup(env, stats):
    env.timers[-1].callback(5.)
    record = env.material._print_cancel
    assert record['state'] == 'complete'
    assert {stage['name']: stage['state'] for stage in record['stages']}['cancelling'] == 'complete'
    assert env.handle.closed and env.objects['virtual_sdcard'].current_file is None
    assert _motion_or_tool(env.cleanup) == []


def test_stopped_start_print_ends_cancelled_through_vendor_worker(managed_cancel_intent, guarded_legacy_dispatch):
    env, sd, stats = _sd_print(managed_cancel_intent, guarded_legacy_dispatch)
    def g28(gcmd):
        env.ran.append(gcmd.get_commandline())
        env.objects['gcode'].run_script('CANCEL_PRINT')
    env.dispatcher.gcode_handlers['G28'] = g28
    env.start()
    assert env.material._print_cancel['stop_point']['phase'] == 'homed'
    # The nested Cancel opened the worker; on_error_gcode CANCEL_PRINT coalesced into it.
    assert [script for script, before, after in env.scripts] == ['CANCEL_PRINT', 'START_PRINT', 'CANCEL_PRINT']
    assert env.scripts[0][2] == env.scripts[0][1] + 1
    assert env.scripts[2][1] == env.scripts[2][2] == env.scripts[0][2]
    assert stats.state == 'cancelled' and stats.error_message == ''
    assert stats.print_start_time is None and env.cleanup == []
    _complete_cleanup(env, stats)
    assert stats.state == 'cancelled' and stats.error_message == ''


def test_heat_wait_stop_ends_cancelled_through_vendor_worker(managed_cancel_intent, guarded_legacy_dispatch):
    env, sd, stats = _sd_print(managed_cancel_intent, guarded_legacy_dispatch, stuck=STUCK['bed_wait'])
    def cancel(count):
        if (env.material.stop_requested() is None
                and any(line.startswith('TEMPERATURE_WAIT SENSOR=heater_bed') for line in env.ran)):
            env.objects['gcode'].run_script('CANCEL_PRINT')
    env.on_pause = cancel
    env.start()
    assert env.material._print_cancel['stop_point']['phase'] == 'heating_heater_bed'
    assert stats.state == 'cancelled' and stats.error_message == ''
    _complete_cleanup(env, stats)
    assert stats.state == 'cancelled'


def test_other_gcode_error_still_ends_error_through_vendor_worker(managed_cancel_intent, guarded_legacy_dispatch):
    env = None
    def fail(gcmd):
        raise env.vendor.CommandError('Heater extruder not heating at expected rate')
    env, sd, stats = _sd_print(managed_cancel_intent, guarded_legacy_dispatch, handler=fail)
    env.start()
    # on_error_gcode CANCEL_PRINT opened a cancel bound to this job; only the message decides.
    assert env.material._print_cancel['state'] == 'pending'
    assert stats.state == 'error'
    assert stats.error_message == 'Heater extruder not heating at expected rate'
    _complete_cleanup(env, stats)
    assert stats.state == 'error'


STOP_TEXTS = ['Print cancellation requested; stopped at after homing',
              'Print cancellation requested; stopped while heating extruder1',
              'Print cancellation requested; stopped during bed mesh, 2 of 5 points measured']


def _printing(legacy_cancel_routes):
    fixture = legacy_cancel_routes[0]
    material, objects = fixture[0], fixture[1]
    objects['print_stats'].note_start()
    return material, objects, objects['print_stats']


@pytest.mark.parametrize('message', STOP_TEXTS)
@pytest.mark.parametrize('change', ['no_cancel', 'handle', 'session', 'file', 'openace', 'AFC'])
def test_stop_text_without_matching_cancel_stays_error(legacy_cancel_routes, message, change):
    import io
    material, objects, stats = _printing(legacy_cancel_routes)
    if change != 'no_cancel':
        objects['gcode'].run_script('CANCEL_PRINT')
        assert material._print_cancel['state'] == 'pending'
    if change == 'handle':
        objects['virtual_sdcard'].current_file = io.StringIO('other job')
    elif change == 'session':
        material.session_id = 'another-session'
    elif change == 'file':
        material._cancellation()._print_cancel_live_binding['file'] = 'other.gcode'
    elif change in ('openace', 'AFC'):
        objects[change] = object()
    stats.note_error(message)
    assert stats.state == 'error' and stats.error_message == message


@pytest.mark.parametrize('message', STOP_TEXTS)
def test_stop_text_with_bound_cancel_records_cancelled(legacy_cancel_routes, message):
    material, objects, stats = _printing(legacy_cancel_routes)
    objects['gcode'].run_script('CANCEL_PRINT')
    stats.note_error(message)
    assert stats.state == 'cancelled' and stats.error_message == ''


@pytest.mark.parametrize('message', ['Print cancellation requested; remaining macro commands retired',
                                     'Print cancellation requested; stopped',
                                     'Must home axis first'])
def test_other_messages_with_bound_cancel_stay_error(legacy_cancel_routes, message):
    material, objects, stats = _printing(legacy_cancel_routes)
    objects['gcode'].run_script('CANCEL_PRINT')
    stats.note_error(message)
    assert stats.state == 'error' and stats.error_message == message


def test_note_error_wrapper_installs_once_on_the_instance(legacy_cancel_routes):
    material, objects, stats = _printing(legacy_cancel_routes)
    first = stats.note_error
    assert 'note_error' in vars(stats)
    material._cancel_routes_ready()
    assert stats.note_error is first


@pytest.mark.parametrize('phase', ['start_admitted', 'before_homing'])
def test_pre_homing_state_text_does_not_claim_axes_unhomed(phase):
    from wm_material import WMMaterial
    label, state = WMMaterial._STOP_POINTS[phase]
    assert state.startswith('not homed by this job')


@pytest.mark.parametrize('change', [None, 'generation', 'session', 'handle', 'openace', 'quick_stop', 'shutdown'])
def test_cancel_generation_unwind_is_only_cancelled_for_its_bound_job(legacy_cancel_routes, change):
    import io
    from test_wm_material import FakeCommand
    material, objects, stats = _printing(legacy_cancel_routes)
    command = FakeCommand(SESSION=material.session_id, GENERATION=getattr(material, "_command_generation", 0))
    objects['gcode'].run_script('CANCEL_PRINT')
    if change == 'generation': material._command_generation += 1
    if change == 'session': material.session_id = 'new-session'
    if change == 'handle': objects['virtual_sdcard'].current_file = io.StringIO('other')
    if change == 'openace': objects[change] = object()
    if change == 'quick_stop': objects['gcode'].quick_stop_flag = True
    if change == 'shutdown': material.printer.is_shutdown = lambda: True
    with pytest.raises(Exception) as failure:
        material._check_command_generation(command)
    message = str(failure.value)
    stats.note_error(message)
    assert stats.state == ('cancelled' if change is None else 'error')
    assert message.startswith('Print cancellation requested; stopped ') is (change is None)
