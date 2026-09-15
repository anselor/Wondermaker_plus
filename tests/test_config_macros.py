"""Render actual macro templates; interpret only heater and variable commands."""
import copy
import re
from pathlib import Path
import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1]


def templates(directory):
    env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
    out = {}
    for file in ('macros.cfg', 'offset_calibrate.cfg', 'change_macros.cfg', 'printer.cfg'):
        for section in re.split(r'(?m)^\[', (directory / file).read_text())[1:]:
            name, body = section.split(']', 1)
            code = re.search(r'(?m)^gcode\s*[:=]\s*\n([\s\S]*)', body)
            if code and (name.startswith('gcode_macro ') or name == 'idle_timeout'):
                script = '\n'.join(line.split('#', 1)[0] for line in code[1].splitlines())
                out[name.removeprefix('gcode_macro ')] = env.from_string(script)
    return out


class HeaterModel:
    def __init__(self, directory, mapping=(2, 1, 0, 3)):
        self.templates = templates(directory)
        self.p = {'save_variables': {'variables': {'thr_number': 4, **{f'box_modify_t{i}': t for i, t in enumerate(mapping)}}},
                  'toolhead': {'extruder': 'extruder3', 'axis_maximum': {'z': 330}},
                  'print_stats': {'state': 'printing'},
                  'configfile': {'settings': {'idle_timeout': {'timeout': 600}}},
                  'heater_bed': {'temperature': 60}, 'fan': {'speed': 0.5},
                  'fan_generic auxiliary_fan': {'speed': 0}, 'gcode_move': {'position': {'z': 20}}}
        for h in ('extruder', 'extruder1', 'extruder2', 'extruder3'):
            self.p[h] = {'target': 220, 'temperature': 200}
        self.events = []

    def run(self, name, **params):
        script = self.templates[name].render(printer=copy.deepcopy(self.p), params=params, action_respond_info=lambda *a: '')
        for line in script.splitlines():
            words = line.strip().split()
            if not words:
                continue
            command = words[0]
            if command in ('M104', 'M109'):
                self.run(command, **dict(re.findall(r'([A-Z])\s*([-+]?\d+(?:\.\d+)?)', line.strip()[len(command):])))
            elif command in ('SAVE_VARIABLE', 'SET_HEATER_TEMPERATURE', 'TEMPERATURE_WAIT'):
                args = dict(w.split('=', 1) for w in words[1:])
                self.events.append((command, args))
                if command == 'SAVE_VARIABLE':
                    self.p['save_variables']['variables'][args['VARIABLE']] = int(args['VALUE'])
                if command == 'SET_HEATER_TEMPERATURE':
                    self.p[args['HEATER']]['target'] = float(args['TARGET'])


@pytest.mark.parametrize('directory', ['stock', 'live'])
@pytest.mark.parametrize('command', ['PAUSE', 'idle_timeout'])
def test_all_physical_heaters_off_with_duplicate_mapping(directory, command):
    m = HeaterModel(ROOT / 'config' / directory, (0, 3, 0, 3))
    m.run(command)
    assert all(m.p[h]['target'] == 0 for h in ('extruder', 'extruder1', 'extruder2', 'extruder3'))
    if directory == 'live' and command == 'PAUSE':
        assert [m.p['save_variables']['variables'][f'box_modify_t{i}_backup'] for i in range(4)] == [0, 3, 0, 3]


@pytest.mark.parametrize('command', ['M104', 'M109'])
def test_missing_t_uses_active_physical_heater_and_float_target(command):
    m = HeaterModel(ROOT / 'config/live')
    m.run(command, S='215.5')
    assert m.p['extruder3']['target'] == 215.5
    assert m.p['extruder2']['target'] == 220


def test_explicit_t_maps_once_and_s_zero_switches_off():
    m = HeaterModel(ROOT / 'config/live')
    m.run('M109', T='0', S='230')
    assert m.p['extruder2']['target'] == 230
    assert m.events[-1][1]['SENSOR'] == 'extruder2'
    m.events.clear()
    m.run('M109', S='0')
    assert m.p['extruder3']['target'] == 0
    assert all(command != 'TEMPERATURE_WAIT' for command, _ in m.events)


@pytest.mark.parametrize('state,target,wait', [('printing', 220, True), ('paused', 220, True), ('standby', 220, False), ('printing', 0, False)])
def test_tool_wait_never_sets_a_heater(state, target, wait):
    m = HeaterModel(ROOT / 'config/live')
    m.p['print_stats']['state'] = state
    m.p['extruder3']['target'] = target
    m.run('_WAIT_TOOL_TEMPERATURE')
    assert len(m.events) == int(wait)
    if wait:
        assert m.events[0][0] == 'TEMPERATURE_WAIT' and m.events[0][1]['SENSOR'] == 'extruder3'




@pytest.mark.parametrize('macro,target,maximum', [('NOZZLE_PREPARE',100,102.5), ('POP',102,104.5)])
@pytest.mark.parametrize('slot,physical', [(0,2), (1,1), (2,0), (3,3)])
def test_explicit_cooldowns_set_and_wait_on_same_mapped_heater(macro, target, maximum, slot, physical):
    m = HeaterModel(ROOT / 'config/live')
    m.p['toolhead']['homed_axes'] = 'xyz'
    m.p['save_variables']['variables']['current_extruder'] = 0
    m.p['print_stats']['state'] = 'standby'
    m.run(macro, T=str(slot))
    heater = 'extruder' if physical == 0 else f'extruder{physical}'
    # The first M109 still waits for purge temperature. Only the final
    # cooldown changes to an upper threshold, with the existing tolerance.
    waits = [args for command,args in m.events if command == 'TEMPERATURE_WAIT']
    assert len(waits) == 2
    assert 'MINIMUM' in waits[0] and 'MAXIMUM' in waits[0]
    assert m.events[-2:] == [
        ('SET_HEATER_TEMPERATURE', {'HEATER': heater, 'TARGET': str(target)}),
        ('TEMPERATURE_WAIT', {'SENSOR': heater, 'MAXIMUM': str(maximum)})]
    assert m.p[heater]['target'] == target


@pytest.mark.parametrize('temperature', [90,100,220])
def test_m109_retains_band_wait_even_when_already_above_or_below_target(temperature):
    m = HeaterModel(ROOT / 'config/live')
    m.p['extruder3']['temperature'] = temperature
    m.run('M109', S='100')
    assert m.events[-1] == ('TEMPERATURE_WAIT', {
        'SENSOR': 'extruder3', 'MINIMUM': '97.5', 'MAXIMUM': '102.5'})


@pytest.mark.parametrize('cooled_temperature', [90.,100.])
def test_vendor_wait_limits_do_not_persist_into_next_heating_wait(cooled_temperature):
    """Execute the bundled wait handler twice on the same heater/host objects."""
    import ast
    from types import SimpleNamespace
    source = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/klipper/klippy/extras/heaters.py'
    if not source.exists():
        pytest.skip('local vendor heater source is not present')
    cls = next(n for n in ast.parse(source.read_text()).body
               if isinstance(n, ast.ClassDef) and n.name == 'PrinterHeaters')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                  and n.name == 'cmd_TEMPERATURE_WAIT')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    readings, pauses = [], []
    def pause(eventtime):
        pauses.append(eventtime)
        return eventtime
    class Command(dict):
        def get_float(self, key, default, **kwargs): return float(self.get(key, default))
        def respond_raw(self, message): pass
    sensor = SimpleNamespace(get_temp=lambda eventtime: (readings.pop(0), 0))
    reactor = SimpleNamespace(monotonic=lambda: 0., pause=pause)
    printer = SimpleNamespace(quick_stop_flag=False, is_shutdown=lambda: False,
        get_start_args=lambda: {}, get_reactor=lambda: reactor,
        lookup_object=lambda name: SimpleNamespace(get_last_move_time=lambda: 0.))
    host = SimpleNamespace(available_sensors=['extruder'], heaters={'extruder':sensor},
                           printer=printer, _get_temp=lambda eventtime:'')
    wait = namespace['cmd_TEMPERATURE_WAIT']
    readings[:] = [220.,cooled_temperature]
    wait(host, Command(SENSOR='extruder', MAXIMUM=102.5))
    assert not readings and len(pauses) == 1
    readings[:] = [cooled_temperature,220.]
    wait(host, Command(SENSOR='extruder', MINIMUM=217.5, MAXIMUM=222.5))
    assert not readings and len(pauses) == 2


@pytest.mark.parametrize('adaptive,expected', [('1','BED_MESH_CALIBRATE PROFILE=wmp_print ADAPTIVE=1'), ('0','BED_MESH_CALIBRATE PROFILE=wmp_print')])
def test_start_print_respects_string_adaptive_parameter(adaptive,expected):
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings']['printer'] = {'max_velocity':600,'max_accel':10000}
    script = m.templates['START_PRINT'].render(printer=m.p,
        params={'BED':'60','EXTRUDER':'220','INITIAL_TOOL':'1','ADAPTIVE':adaptive},
        adaptive_mesh_enable=True, action_respond_info=lambda *a:'')
    commands = [line.strip() for line in script.splitlines() if line.strip().startswith('BED_MESH_CALIBRATE')]
    assert commands == [expected]
