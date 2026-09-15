"""Design checks using actual vendor state methods, without moving a printer.

These document why enabling the dormant RESTORE is not the complete fix.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def vendor_methods():
    path = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'
    if not path.exists():
        pytest.skip('local vendor 1.1.08 source is not present')
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GCodeMove')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
               ('cmd_SAVE_GCODE_STATE', 'cmd_RESTORE_GCODE_STATE', 'cmd_SET_GCODE_OFFSET')]
    namespace = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


class Command:
    def __init__(self, **values): self.values = values
    def get(self, key, default=None): return self.values.get(key, default)
    def get_int(self, key, default=None): return int(self.get(key, default))
    def get_float(self, key, default=None, **kwargs):
        value = self.get(key, default)
        return float(value) if value is not None else None


def state():
    return SimpleNamespace(saved_states={}, absolute_coord=True, absolute_extrude=False,
                           base_position=[1., 2., .3, 0.], homing_position=[1., 2., .3, 0.],
                           last_position=[101., 152., 12.3, 0.], speed=100., speed_factor=1/60,
                           extrude_factor=1.2, move_with_transform=lambda *args: None)


@pytest.mark.parametrize('restore_after_offsets', [False, True])
def test_raw_saved_position_is_not_a_tool_independent_print_position(vendor_methods, restore_after_offsets):
    s = state()
    vendor_methods['cmd_SAVE_GCODE_STATE'](s, Command(NAME='park'))
    vendor_methods['cmd_SET_GCODE_OFFSET'](s, Command(X=0, Y=0, Z=0, MOVE=1))
    if restore_after_offsets:
        vendor_methods['cmd_SET_GCODE_OFFSET'](s, Command(X=3, Y=4, Z=.1, MOVE=1))
    vendor_methods['cmd_RESTORE_GCODE_STATE'](s, Command(NAME='park', MOVE=1, MOVE_SPEED=200))
    if not restore_after_offsets:
        vendor_methods['cmd_SET_GCODE_OFFSET'](s, Command(X=3, Y=4, Z=.1, MOVE=1))
    logical = [s.last_position[i] - s.base_position[i] for i in range(3)]
    assert logical[0] == (98 if restore_after_offsets else 101)
    assert logical != pytest.approx([100, 150, 12])


def test_full_state_restore_overwrites_new_tool_flow_factor(vendor_methods):
    s = state()
    vendor_methods['cmd_SAVE_GCODE_STATE'](s, Command(NAME='park'))
    s.extrude_factor = .9  # New tool's M221 applied on the success path.
    vendor_methods['cmd_RESTORE_GCODE_STATE'](s, Command(NAME='park', MOVE=0))
    assert s.extrude_factor == 1.2


# This interpreter expands the actual macros at execution time. Only hardware
# contact/heater waits are stubbed; ordering, variables, offsets and moves run.
import copy
import re
import shlex
import jinja2


class MotionModel:
    def __init__(self, outcomes=(0,), state='printing', save=1, current=0,
                 absolute=False, override=.6, z=12):
        self.templates, self.defaults = {}, {}
        env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
        for filename in ('offset_calibrate.cfg', 'change_macros.cfg', 'fz-wipe-nozzle.cfg'):
            for section in re.split(r'(?m)^\[', (ROOT / 'config/live' / filename).read_text())[1:]:
                heading, body = section.split(']', 1)
                if not heading.startswith('gcode_macro '): continue
                name = heading.split(' ', 1)[1].upper()
                code = re.search(r'(?m)^gcode:\s*\n([\s\S]*)', body)
                if not code: continue
                script = '\n'.join(line.split('#', 1)[0] for line in code[1].splitlines())
                self.templates[name] = env.from_string(script)
                self.defaults[name] = {k: ast.literal_eval(v.split('#')[0].strip()) for k, v in
                                       re.findall(r'(?m)^variable_(\w+):\s*([^\n]+)', body)}
        self.p = {
            'save_variables': {'variables': {'current_extruder': current, 'fail_flag': 0,
                'probe_tool': 0, 't0_offset': [0, 0, 0], 't1_offset': [3, 4, -.2],
                't0_flow_extruder': 120, 't1_flow_extruder': 90,
                **{f'box_modify_t{i}': i for i in range(4)}}},
            'wmp_recovery': {'z_reference_valid': True},
            'toolhead': {'homed_axes': 'xyz', 'position': {'z': z+.3},
                         'axis_maximum': {'z': 330}, 'extruder': 'extruder'},
            'gcode_move': {'gcode_position': {'x': 100., 'y': 150., 'z': z},
                'position': {'x': 101., 'y': 152., 'z': z+.3},
                'homing_origin': {'x': 1., 'y': 2., 'z': .3}, 'speed': 3600.,
                'speed_factor': override, 'extrude_factor': 1.2,
                'absolute_coordinates': absolute, 'absolute_extrude': False},
            'configfile': {'settings': {'stepper_z': {'position_endstop': 330}}},
            'print_stats': {'state': state}, 'pause_resume': {'is_paused': False},
            'gcode_macro START_PRINT': {'print_body_ready': True}}
        for name, values in self.defaults.items(): self.p['gcode_macro ' + name] = values.copy()
        # Klipper object names retain the section spelling for these two macros.
        self.p['gcode_macro _descend_z'] = self.p['gcode_macro _DESCEND_Z']
        self.p['gcode_macro _CHANGE_TOOL']['save_position'] = save
        self.events, self.states = [], {}
        self.outcomes = iter(outcomes)

    def run(self, name, **params):
        name = name.upper()
        self.events.append((name, params.copy()))
        if name in ('_CHECK_CURRENT_EXTRUDER_VALUE', '_CHECK_HALL_SENSOR', '_CHECK_TOOL_EXIST',
                    '_ENABLE_SENSOR', '_WAIT_TOOL_TEMPERATURE'): return
        gm = self.p['gcode_move']; sv = self.p['save_variables']['variables']
        if name == '_UNLOCK_TOOL':
            self.command('SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=1')
            sv['current_extruder'] = 99
            return
        if name == '_LOCK_TOOL':
            self.command('G90'); self.command('G1 X250 Y270 F1000')
            sv['fail_flag'] = next(self.outcomes)
            if sv['fail_flag'] == -5: self.p['gcode_macro _CHECK_CHANGE_TOOL']['retry'] = 1
            return
        def error(message): raise ValueError(message)
        script = self.templates[name].render(printer=copy.deepcopy(self.p), params=params,
            **self.p['gcode_macro ' + name], action_respond_info=lambda *a: '', action_raise_error=error)
        for line in script.splitlines():
            if line.strip(): self.command(line.strip())

    def command(self, line):
        words = shlex.split(line.split(';')[0])
        if not words: return
        name = words[0].upper()
        if name in self.templates or name in ('_CHECK_CURRENT_EXTRUDER_VALUE', '_CHECK_HALL_SENSOR', '_CHECK_TOOL_EXIST'):
            return self.run(name, **dict(w.split('=', 1) for w in words[1:]))
        args = {k.upper(): v for k, v in (w.split('=', 1) for w in words[1:] if '=' in w)}
        self.events.append((name, args.copy() if args else line))
        gm = self.p['gcode_move']; sv = self.p['save_variables']['variables']
        if name in ('G0', 'G1', 'M220', 'M221'):
            args = {k: float(v) for k,v in re.findall(r'([XYZEFSM])([-+0-9.e]+)', line[len(name):])}
        if name in ('G0', 'G1'):
            for axis in 'xyz':
                if axis.upper() in args:
                    v = args[axis.upper()]
                    if gm['absolute_coordinates']: v += gm['homing_origin'][axis]
                    else: v += gm['position'][axis]
                    gm['position'][axis] = v
                    gm['gcode_position'][axis] = v - gm['homing_origin'][axis]
            if 'F' in args: gm['speed'] = args['F']
            self.p['toolhead']['position']['z'] = gm['position']['z']
            self.events.append(('MOVE', copy.deepcopy(gm)))
        elif name == 'SET_GCODE_OFFSET':
            for axis in 'xyz':
                if axis.upper() not in args: continue
                v = float(args[axis.upper()]); delta = v - gm['homing_origin'][axis]
                gm['homing_origin'][axis] = v
                if args.get('MOVE') == '1': gm['position'][axis] += delta
                gm['gcode_position'][axis] = gm['position'][axis] - v
            self.p['toolhead']['position']['z'] = gm['position']['z']
        elif name == 'M220': gm['speed_factor'] = args['S'] / 100
        elif name == 'M221': gm['extrude_factor'] = args['S'] / 100
        elif name in ('G90', 'G91'): gm['absolute_coordinates'] = name == 'G90'
        elif name in ('M82', 'M83'): gm['absolute_extrude'] = name == 'M82'
        elif name == 'SAVE_VARIABLE': sv[args['VARIABLE']] = ast.literal_eval(args['VALUE'])
        elif name == 'SET_GCODE_VARIABLE':
            self.p['gcode_macro ' + args['MACRO']][args['VARIABLE']] = ast.literal_eval(args['VALUE'])
        elif name == 'ACTIVATE_EXTRUDER': self.p['toolhead']['extruder'] = args['EXTRUDER']
        elif name == 'PAUSE': self.p['pause_resume']['is_paused'] = True; self.p['print_stats']['state'] = 'paused'
        elif name == 'SAVE_GCODE_STATE': self.states[args['NAME']] = copy.deepcopy(gm)
        elif name == 'RESTORE_GCODE_STATE':
            for key in ('speed', 'speed_factor', 'extrude_factor', 'absolute_coordinates', 'absolute_extrude'):
                gm[key] = self.states[args['NAME']][key]


@pytest.mark.parametrize('outcomes', [(0,), (-2, 0)])
@pytest.mark.parametrize('absolute,override', [(True, 1.5), (False, .6)])
def test_return_after_wipe_uses_original_logical_position_and_new_tool_state(outcomes, absolute, override):
    m = MotionModel(outcomes, absolute=absolute, override=override)
    m.run('T1')
    gm = m.p['gcode_move']
    assert gm['gcode_position'] == pytest.approx(dict(x=100, y=150, z=12))
    assert gm['position'] == pytest.approx(dict(x=103, y=154, z=11.8))
    assert gm['extrude_factor'] == .9 and gm['speed_factor'] == override and gm['speed'] == 3600
    assert gm['absolute_coordinates'] == absolute and not gm['absolute_extrude']
    assert m.p['toolhead']['extruder'] == 'extruder1'
    names = [n for n,_ in m.events]
    assert names.count('_WMP_TOOL_RETURN_BEGIN') == 1
    assert names.count('_RAISE_Z') == 1
    assert names.count('WIPE_NOZZLE') == 1
    assert names.index('WIPE_NOZZLE') < names.index('_WMP_TOOL_RETURN_FINISH')
    finish = names.index('_WMP_TOOL_RETURN_FINISH')
    moves = [v for n,v in m.events[finish:] if n == 'MOVE']
    assert moves[1]['gcode_position'] == pytest.approx(dict(x=100, y=150, z=14))
    assert moves[1]['speed'] == 12000 and moves[1]['speed_factor'] == 1
    assert not m.p['gcode_macro _WMP_TOOL_RETURN_BEGIN']['pending']


@pytest.mark.parametrize('outcomes', [(-2, -2), (-5,)])
def test_failed_pickup_never_wipes_or_returns_even_after_vendor_clears_fail_flag(outcomes):
    m = MotionModel(outcomes)
    m.run('T1')
    assert m.p['save_variables']['variables']['fail_flag'] == 0
    assert m.p['pause_resume']['is_paused']
    assert all(n != 'WIPE_NOZZLE' for n,_ in m.events)
    assert m.p['gcode_move']['gcode_position']['z'] == 14
    assert not m.p['gcode_macro _WMP_TOOL_RETURN_BEGIN']['pending']


@pytest.mark.parametrize('state,save,current', [('paused',1,0), ('standby',1,0), ('printing',0,0), ('printing',1,1)])
def test_nonreturn_paths_do_not_travel_back_to_print(state, save, current):
    m = MotionModel(state=state, save=save, current=current)
    m.run('T1')
    names = [n for n,_ in m.events]; finish = names.index('_WMP_TOOL_RETURN_FINISH')
    moves = [v for n,v in m.events[finish:] if n == 'MOVE']
    assert all(v['gcode_position']['x'] != 100 for v in moves) if current != 1 else True
    assert not m.p['gcode_macro _WMP_TOOL_RETURN_BEGIN']['pending']


def test_missing_homing_and_z_limit_reject_before_docking():
    for unhomed in (True, False):
        m = MotionModel(z=329 if not unhomed else 12)
        if unhomed: m.p['toolhead']['homed_axes'] = 'xy'
        with pytest.raises(ValueError, match='homed XYZ|Insufficient Z'):
            m.run('T1')
        assert all(n != '_UNLOCK_TOOL' for n,_ in m.events)


def test_failed_return_is_not_reused_by_next_change():
    m = MotionModel((-2,-2,0)); m.run('T1')
    m.p['print_stats']['state'] = 'printing'; m.p['pause_resume']['is_paused'] = False
    m.command('G90'); m.command('G1 X50 Y60 Z20')
    m.run('T1')
    assert m.p['gcode_move']['gcode_position'] == pytest.approx(dict(x=50,y=60,z=20))


@pytest.mark.parametrize('z', [0, 3, 7, 20])
def test_calibration_clearance_is_z_only_and_never_lowers(z):
    m = MotionModel(z=z, absolute=False)
    m.run('_WMP_CALIBRATION_CLEARANCE')
    position = m.p['gcode_move']['gcode_position']
    assert position == pytest.approx(dict(x=100, y=150, z=max(7, z)))
    assert m.p['gcode_move']['absolute_coordinates']


def test_calibration_requires_real_homing_and_checks_z_limit():
    m = MotionModel(); m.p['toolhead']['homed_axes'] = 'xy'
    with pytest.raises(ValueError, match='Home XYZ'):
        m.run('_WMP_CALIBRATION_CLEARANCE')
    m = MotionModel(z=1); m.p['toolhead']['axis_maximum']['z'] = 5
    with pytest.raises(ValueError, match='Insufficient Z'):
        m.run('_WMP_CALIBRATION_CLEARANCE')


def test_idle_wipe_raises_before_xy_even_with_same_tool():
    m = MotionModel(state='standby', z=0)
    m.run('WIPE_NOZZLE')
    moves = [v for n,v in m.events if n == 'MOVE']
    assert moves[0]['gcode_position'] == pytest.approx(dict(x=100,y=150,z=7))
    assert all(v['gcode_position']['z'] >= 7 for v in moves)



def test_idle_same_tool_establishes_clearance_before_offset_move():
    m = MotionModel(state='standby', z=0)
    m.run('T0')
    names = [n for n,_ in m.events]
    assert names.index('_WMP_CALIBRATION_CLEARANCE') < names.index('_OFFSET_SET')
    assert m.p['gcode_move']['gcode_position']['z'] == 7
    assert '_UNLOCK_TOOL' not in names



def test_startup_toolchange_does_not_return_to_last_mesh_point():
    m = MotionModel()
    m.p['gcode_macro START_PRINT']['print_body_ready'] = False
    m.run('T1')
    assert m.p['gcode_move']['gcode_position']['x'] == -13
    assert m.p['gcode_move']['gcode_position']['z'] == 12
    assert not m.p['gcode_macro _WMP_TOOL_RETURN_BEGIN']['pending']
