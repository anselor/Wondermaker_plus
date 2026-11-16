"""Execute retained pickup macros and actuator homing at the cleanup boundary."""
import ast
import re
import shlex
from pathlib import Path
from types import SimpleNamespace as NS
import jinja2
import pytest

pytest_plugins = ['test_recovery_actuator']


class Command:
    def __init__(self, **values): self.values = values
    def get(self, key, default=None): return self.values.get(key, default)
    def get_int(self, key, default=None, **kwargs): return int(self.get(key, default))
    def get_float(self, key, default=None, **kwargs):
        value = self.get(key, default)
        return float(value) if value is not None else None
    def error(self, message): return ValueError(message)


@pytest.fixture
def pickup(actuator_machine):
    material, objects, calls, faults, unused = actuator_machine
    material.session_id = 'session'
    material._command_generation = 0
    material._print_cancel_active = lambda: False
    saved = dict(fail_flag=0, current_extruder=99, is_nozzle_setting=0,
                 **{'t%d_position' % n: [40. + 60*n, 340.] for n in range(4)})
    pos = [20., 270., 10., 0.]
    states = {'save_variables': {'variables': saved}, 'gcode_move': {'position': pos},
              'custom_hall': {'Raw': 4900.}, 'filament_switch_sensor sensor_b': {'filament_detected': True},
              'filament_switch_sensor docked2': {'filament_detected': True}}
    for name, data in states.items(): objects[name] = NS(get_status=lambda now, data=data: data)
    objects['toolhead'].get_status = lambda now: {'homed_axes': 'xyz'}
    material.printer.get_reactor = lambda: NS(monotonic=lambda: 1.)
    material.printer.is_shutdown = lambda: False
    p = dict(states, toolhead={'homed_axes': 'xyz'},
             wm_material={'session_id': 'session', 'command_generation': 0})
    p['gcode_move'] = {'position': NS(x=pos[0], y=pos[1], z=pos[2])}
    p['gcode_macro _LOCK_CHECK'] = {'retry': 0}
    events = []
    options = dict(dock_after_lock=True, detached=True, cancel_at='', fail_at='', wrong_pose=False,
                   incoming_offset=[0., 0., 0., 0.])
    vendor_path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'
    tree = ast.parse(vendor_path.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'GCodeMove')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'cmd_SET_GCODE_OFFSET')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(vendor_path), 'exec'), namespace)
    frame = NS(base_position=[0., 0., 0., 0.], homing_position=[0., 0., 0., 0.],
               last_position=pos, speed=100., move_with_transform=lambda *args: None)
    path = Path(__file__).resolve().parents[1] / 'config/live/change_macros.cfg'
    env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
    templates = {}
    for part in re.split(r'(?m)^\[gcode_macro ', path.read_text())[1:]:
        name, body = part.split(']', 1)
        script = re.split(r'(?m)^gcode:\s*\n', body)[1]
        templates[name] = env.from_string(script)
    def execute(command):
        words = shlex.split(command.split('#', 1)[0])
        if not words: return
        name = words[0]
        args = dict(w.split('=', 1) for w in words[1:] if '=' in w)
        events.append(command.strip())
        if options['cancel_at'] == name and calls.count('home') >= 2: material._command_generation += 1
        if options['fail_at'] == command: raise ValueError('injected movement failure')
        if name in templates:
            if name == '_LOCK_TOOL_FINISH':
                states['filament_switch_sensor docked2']['filament_detected'] = options['dock_after_lock']
                if options['wrong_pose']: pos[0] += 1
            p['gcode_move']['position'] = NS(x=pos[0], y=pos[1], z=pos[2])
            code = templates[name].render(printer=p, params=args,
                retry=p['gcode_macro _LOCK_CHECK']['retry'], action_respond_info=lambda *a: '',
                action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)))
            for line in code.splitlines(): execute(line.strip())
        elif name == '_WMP_COUPLING_STROKE': material.cmd_COUPLING_STROKE(Command(**args))
        elif name == '_WMP_FAILED_PICKUP_CLEANUP': material.cmd_FAILED_PICKUP_CLEANUP(Command(**args))
        elif name == 'ECHELON_STEPPER_DISABLE': objects['echelon_stepper trans_stepper'].do_enable(False)
        elif name == 'SET_GCODE_VARIABLE': p['gcode_macro '+args['MACRO']][args['VARIABLE']] = int(args['VALUE'])
        elif name == 'SAVE_VARIABLE': saved[args['VARIABLE']] = int(args['VALUE'])
        elif name == 'M400': objects['toolhead'].wait_moves()
        elif name == 'SET_GCODE_OFFSET':
            frame.base_position = list(options['incoming_offset'])
            frame.homing_position = list(options['incoming_offset'])
            namespace['cmd_SET_GCODE_OFFSET'](frame, Command(**args))
        elif name in ('G0', 'G1'):
            for word in words[1:]:
                if word[0] in 'XYZ': pos['XYZ'.index(word[0])] = float(word[1:]) + frame.base_position['XYZ'.index(word[0])]
            if pos[1] == 270. and calls.count('home') >= 2 and options['detached']:
                states['custom_hall']['Raw'] = 5000.
                states['filament_switch_sensor sensor_b']['filament_detected'] = False
    objects['gcode'].run_script_from_command = execute
    return material, saved, states, calls, faults, events, options, execute


def test_supported_failed_pickup_unlocks_then_retreats_and_retires_outer_tail(pickup):
    material, saved, states, calls, faults, events, options, execute = pickup
    with pytest.raises(ValueError, match='released in its dock') as failure:
        execute('_LOCK_TOOL T=2')
    assert failure.value.wmp_toolchange_fault == (-2, 'pickup_cleanup')
    assert calls.count('home') == 2  # Retained LOCK then protective UNLOCK.
    assert calls.count('post') == 1  # Never another lock stroke.
    assert saved['current_extruder'] == 99 and saved['fail_flag'] == -2
    assert events.count('G0 Y310 F9600') == 1
    assert events.count('G0 Y270 F12000') == 1
    assert not any('_CHECK_T_SEQUENCE' in e or 'WIPE' in e or e.startswith('G28') for e in events)


@pytest.mark.parametrize('defect', ['unsupported', 'missing', 'wrong_pose'])
def test_failed_pickup_without_current_support_never_unlocks_or_retreats(pickup, defect):
    material, saved, states, calls, faults, events, options, execute = pickup
    if defect == 'wrong_pose': options['wrong_pose'] = True
    else: options['dock_after_lock'] = False if defect == 'unsupported' else None
    with pytest.raises(ValueError, match='dock support'):
        execute('_LOCK_TOOL T=2')
    assert calls.count('home') == 1
    assert 'G0 Y310 F9600' not in events


def test_failed_actual_lock_stroke_does_not_enter_protective_cleanup(pickup):
    material, saved, states, calls, faults, events, options, execute = pickup
    faults['home'] = True
    with pytest.raises(ValueError, match='endstop not reached'):
        execute('_LOCK_TOOL T=2')
    assert calls.count('home') == 1
    assert not any('_WMP_FAILED_PICKUP_CLEANUP' in e for e in events)
    assert 'G0 Y310 F9600' not in events


def test_cleanup_unlock_failure_does_not_retreat(pickup):
    material, saved, states, calls, faults, events, options, execute = pickup
    actuator = material.printer.lookup_object('echelon_stepper trans_stepper')
    original = actuator.do_homing_move
    def home(*args):
        if calls.count('home') == 1: faults['home'] = True
        return original(*args)
    actuator.do_homing_move = home
    with pytest.raises(ValueError, match='unlock: endstop not reached'):
        execute('_LOCK_TOOL T=2')
    assert 'G0 Y310 F9600' not in events


@pytest.mark.parametrize('defect', ['attached_after_retreat', 'retreat_error', 'cancel'])
def test_failed_cleanup_never_continues_outer_pickup_tail(pickup, defect):
    material, saved, states, calls, faults, events, options, execute = pickup
    saved['current_extruder'] = 2  # Must not claim empty unless proved.
    if defect == 'attached_after_retreat': options['detached'] = False
    elif defect == 'retreat_error': options['fail_at'] = 'G0 Y310 F9600'
    else: options['cancel_at'] = 'G90'
    with pytest.raises(ValueError): execute('_LOCK_TOOL T=2')
    assert saved['current_extruder'] == 2
    assert not any('_CHECK_T_SEQUENCE' in e for e in events)
    if defect == 'cancel':
        assert calls.count('home') == 2
        assert 'G0 Y310 F9600' not in events  # No move after ownership changed.
        assert saved['fail_flag'] == 0  # Do not publish fault into the new owner.


@pytest.mark.parametrize('offset', [[3., -4., -.2, 0.], [-.115625, .08125, -.377813, 0.]])
def test_cleanup_dock_pose_uses_cleared_nonzero_tool_offset(pickup, offset):
    material, saved, states, calls, faults, events, options, execute = pickup
    options['incoming_offset'] = offset
    with pytest.raises(ValueError, match='released in its dock'):
        execute('_LOCK_TOOL T=2')
    assert calls.count('home') == 2
    assert saved['fail_flag'] == -2 and saved['current_extruder'] == 99
