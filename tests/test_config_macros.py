"""Render actual macro templates; interpret only heater and variable commands."""
import copy
import re
import shlex
from pathlib import Path
import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('slot', range(4))
def test_runout_delay_message_survives_gcode_comment_parsing(slot):
    source = (ROOT / f'config/live/extruder{slot}.cfg').read_text()
    section = re.search(
        r'(?ms)^\[delayed_gcode delayed_pause%d\].*?(?=^\[|\Z)' % slot,
        source).group()
    command = next(line.strip() for line in section.splitlines()
                   if line.strip().startswith('RESPOND '))
    assert shlex.split(command.split(';', 1)[0]) == [
        'RESPOND', f'MSG=Head {slot + 1} filament is still absent, pausing']
    commands = [line.strip() for line in section.split('gcode:', 1)[1].splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    assert commands[commands.index(command) + 1] == 'PAUSE'
    assert 'not sensor.filament_detected' in section


def test_unload_temperature_message_survives_gcode_comment_parsing():
    model = HeaterModel(ROOT / 'config/live')
    model.p['configfile']['settings']['extruder3'] = {'max_temp': 350}
    script = model.templates['_TIP_SHAPE_RETRACT'].render(
        printer=model.p, params={'MATERIAL': 'PLA', 'DRY_RUN': '1'},
        unload_temp_min=250, unload_temps={'PLA': 250})
    command = next(line.strip() for line in script.splitlines()
                   if 'RESPOND MSG="Unload temperature' in line)
    # Klipper's extended-command parser ends arguments at a comment delimiter,
    # even inside quotes, then passes the remaining arguments to shlex.
    arguments = shlex.split(command.split(';', 1)[0])
    assert arguments == [
        'RESPOND',
        'MSG=Unload temperature for extruder3 (slot T3): 250 C, screen target was 220 C',
    ]
    assert 'M109' not in script  # exercise reporting without heating or movement


def test_openace_include_is_carried_by_managed_printer_config():
    source = (ROOT / 'config/live/printer.cfg').read_text()
    assert '[include openace*.cfg]' in source
    assert '[include openace' not in (ROOT / 'config/live/zru-s.cfg').read_text()


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
                  'pause_resume': {'is_paused': False},
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


@pytest.mark.parametrize('state', ['standby', 'paused'])
@pytest.mark.parametrize('z,expected_lift', [(20, 5), (328, 2), (330, 0)])
def test_filament_service_position_lifts_then_exits_along_edge(state, z, expected_lift):
    m = HeaterModel(ROOT / 'config/live')
    m.p['print_stats']['state'] = state
    m.p['toolhead'].update({'homed_axes': 'xyz', 'position': {'z': z}})
    script = m.templates['_WMP_FILAMENT_SERVICE_POSITION'].render(
        printer=m.p, params={}, hop=5.0, x=-13.0, y=80.0,
        action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)))
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    expected = ['G91']
    if expected_lift:
        expected.append('G1 Z%s F800' % float(expected_lift))
    expected += ['G90', 'G1 X-13.0 F6000', 'G1 Y80.0 F6000']
    assert commands == expected


@pytest.mark.parametrize('state,homed,message', [
    ('printing', 'xyz', 'Pause the print'),
    ('standby', 'xy', 'Home XYZ'),
])
def test_filament_service_position_rejects_unsafe_context(state, homed, message):
    m = HeaterModel(ROOT / 'config/live')
    m.p['print_stats']['state'] = state
    m.p['toolhead'].update({'homed_axes': homed, 'position': {'z': 20}})
    with pytest.raises(ValueError, match=message):
        m.templates['_WMP_FILAMENT_SERVICE_POSITION'].render(
            printer=m.p, params={}, hop=5.0, x=-13.0, y=80.0,
            action_raise_error=lambda text: (_ for _ in ()).throw(ValueError(text)))


@pytest.mark.parametrize('macro,target,maximum', [('NOZZLE_PREPARE',100,102.5), ('POP',102,104.5)])
@pytest.mark.parametrize('slot,physical', [(0,2), (1,1), (2,0), (3,3)])
def test_explicit_cooldowns_set_and_wait_on_same_mapped_heater(macro, target, maximum, slot, physical):
    m = HeaterModel(ROOT / 'config/live')
    m.p['toolhead']['homed_axes'] = 'xyz'
    m.p['save_variables']['variables']['current_extruder'] = 0
    m.p['print_stats']['state'] = 'standby'
    m.run(macro, T=str(slot))
    if macro == 'NOZZLE_PREPARE':
        physical = slot  # Calibration parameters identify physical heads.
    heater = 'extruder' if physical == 0 else f'extruder{physical}'
    # The first heating wait still waits for purge temperature. Only the final
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


def test_start_print_uses_openace_virtual_to_physical_probe_lookup():
    m = HeaterModel(ROOT / 'config/live', mapping=(2, 1, 0, 3))
    m.p['configfile']['settings']['printer'] = {
        'max_velocity': 600, 'max_accel': 10000}
    m.p['openace'] = {'tool_extruder_index': {'0': 3}}
    script = m.templates['START_PRINT'].render(
        printer=m.p,
        params={'BED': '60', 'EXTRUDER': '220', 'INITIAL_TOOL': '0'},
        adaptive_mesh_enable=True,
        action_respond_info=lambda *a: '',
        action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)))
    assert 'SAVE_VARIABLE VARIABLE=probe_tool VALUE=3' in script
    assert 'SET_HEATER_TEMPERATURE HEATER=extruder3 TARGET=140' in script
    assert 'TEMPERATURE_WAIT SENSOR=extruder3 MINIMUM=137.5 MAXIMUM=142.5' in script
    assert 'M109 S140 T0' not in script


def test_start_print_rejects_missing_openace_probe_mapping():
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings']['printer'] = {
        'max_velocity': 600, 'max_accel': 10000}
    m.p['openace'] = {'tool_extruder_index': {}}
    with pytest.raises(ValueError, match='did not publish a physical head'):
        m.templates['START_PRINT'].render(
            printer=m.p,
            params={'BED': '60', 'EXTRUDER': '220', 'INITIAL_TOOL': '0'},
            adaptive_mesh_enable=True,
            action_respond_info=lambda *a: '',
            action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)))


@pytest.mark.parametrize('already_paused', [False, True])
def test_pause_tracks_native_state_and_preserves_original_context_on_repeat(already_paused):
    model = HeaterModel(ROOT / 'config/live')
    model.p['pause_resume']['is_paused'] = already_paused
    model.p['wm_material'] = {}
    script = model.templates['PAUSE'].render(
        printer=model.p, params={}, action_respond_info=lambda *args: '')
    commands = [line.strip() for line in script.splitlines()
                if line.strip() and not line.strip().startswith('#')]
    if already_paused:
        assert commands == []  # no snapshot overwrite, parking or heater changes
    else:
        assert commands.count('BASE_PAUSE') == 1
        assert 'M25' not in commands
        assert commands.index('SAVE_GCODE_STATE NAME=PAUSE') < commands.index('BASE_PAUSE')
        assert commands.index('BASE_PAUSE') < commands.index('SAVE_GCODE_STATE NAME=PAUSEPARK')
        assert commands[-1] == 'WMP_CAPTURE_PAUSE'
        assert 'G28' not in script


def test_vendor_resume_clears_native_pause_state_before_sd_resume():
    source = (ROOT / 'config/live/macros.cfg').read_text()
    section = re.search(
        r'(?ms)^\[gcode_macro RESUME\].*?(?=^\[|\Z)', source).group()
    commands = [line.strip() for line in section.splitlines()]
    assert commands.index('CLEAR_PAUSE') < commands.index('M24')


def render_print_finish(model, macro, bed_drop=150.):
    model.p['gcode_macro PRINT_END'] = {'bed_drop': bed_drop}
    model.p['save_variables']['variables']['current_extruder'] = 0
    script = model.templates[macro].render(printer=model.p, params={})
    helper = '_WMP_PRINT_END_CLEARANCE_AND_WIPE'
    assert script.count(helper) == 1
    assert script.index(helper) < script.index('BED_MESH_CLEAR')
    assert script.index(helper) < script.index('M84')
    script = script.replace(helper, model.templates[helper].render(
        printer=model.p, params={}))
    return script.replace("_WMP_PRINT_LOWER_BED", model.templates["_WMP_PRINT_LOWER_BED"].render(printer=model.p, params={}))


@pytest.mark.parametrize('macro', ['PRINT_END', 'CANCEL_PRINT'])
@pytest.mark.parametrize('physical_z,gcode_z,expected_target', [
    (20., 19.7, 169.7),
    (275., 274.7, 299.7),
    (300., 299.7, None),
    (304., 303.7, None),
    (275., 280., 305.),
])
def test_print_end_bed_drop_is_clamped_to_bottom_endstop(
        macro, physical_z, gcode_z, expected_target):
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings'].update({
        'printer': {'max_velocity': 600, 'max_accel': 10000},
        'stepper_z': {'position_endstop': 300},
    })
    m.p['toolhead'].update({
        'homed_axes': 'xyz',
        'position': {'z': physical_z},
    })
    m.p['gcode_move'] = {
        'gcode_position': {'z': gcode_z},
        'position': {'z': physical_z},
    }
    script = render_print_finish(m, macro)
    z_moves = [line.strip() for line in script.splitlines()
               if re.match(r'\s*G1 Z', line)]
    if expected_target is None:
        assert z_moves == []
    else:
        assert z_moves == [f'G1 Z{expected_target} F3000']
    assert 'WIPE_NOZZLE' in script


@pytest.mark.parametrize('macro', ['PRINT_END', 'CANCEL_PRINT'])
@pytest.mark.parametrize('homed', ['', 'xy', 'z'])
def test_print_end_skips_wipe_without_all_axes_homed(macro, homed):
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings'].update({
        'printer': {'max_velocity': 600, 'max_accel': 10000},
        'stepper_z': {'position_endstop': 300},
    })
    m.p['toolhead'].update({'homed_axes': homed, 'position': {'z': 20.}})
    m.p['gcode_move'] = {
        'gcode_position': {'z': 20.}, 'position': {'z': 20.}}
    script = render_print_finish(m, macro)
    assert ('G1 Z170.0 F3000' in script) == ('z' in homed)
    assert 'WIPE_NOZZLE' not in script


@pytest.mark.parametrize('macro', ['PRINT_END', 'CANCEL_PRINT'])
@pytest.mark.parametrize('bed_drop,expected_target', [(12.5, 32.5), (0, None), (-5, None)])
def test_print_finish_respects_existing_bed_drop_setting(macro, bed_drop, expected_target):
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings'].update({
        'printer': {'max_velocity': 600, 'max_accel': 10000},
        'stepper_z': {'position_endstop': 300},
    })
    m.p['toolhead'].update({'homed_axes': 'xyz', 'position': {'z': 20.}})
    m.p['gcode_move']['gcode_position'] = {'z': 20.}
    script = render_print_finish(m, macro, bed_drop)
    z_moves = [line.strip() for line in script.splitlines()
               if re.match(r'\s*G1 Z', line)]
    assert z_moves == ([] if expected_target is None else [f'G1 Z{expected_target} F3000'])


@pytest.mark.parametrize('material_class,armed_pull,earlier_pull', [
    ('soft', 'G1 E-27 F2700', None),
    ('petg', 'G1 E-40 F3600', None),
    ('abs', 'G1 E-35 F3300', 'G1 E-35 F3000'),
    ('pla', 'G1 E-35 F3300', 'G1 E-35 F3000'),
])
def test_openace_rollback_assist_arms_at_final_tip_shaping_pull(
        material_class, armed_pull, earlier_pull):
    m = HeaterModel(ROOT / 'config/live')
    m.p['openace'] = {}
    script = m.templates['_TIP_SHAPE_MOVES'].render(
        printer=m.p, params={'CLASS': material_class},
        cooling_moves=3, cooling_len=10,
        cooling_speed_list=[300, 240, 150], stamp_len=35)
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    hook = commands.index('_OPENACE_ROLLBACK_ASSIST_ON')
    assert commands.count('_OPENACE_ROLLBACK_ASSIST_ON') == 1
    assert commands[hook - 1] == 'M400'
    assert commands[hook + 1].startswith(armed_pull)
    off = commands.index('_OPENACE_ROLLBACK_ASSIST_OFF')
    assert commands[off - 1] == 'M400'
    assert hook < off == len(commands) - 1
    assert commands.count('_OPENACE_ROLLBACK_ASSIST_OFF') == 1
    if earlier_pull:
        assert next(i for i, command in enumerate(commands)
                    if command.startswith(earlier_pull)) < hook


@pytest.mark.parametrize('material_class', ['soft', 'petg', 'abs', 'pla'])
def test_tip_shaping_has_no_openace_hook_without_openace(material_class):
    m = HeaterModel(ROOT / 'config/live')
    script = m.templates['_TIP_SHAPE_MOVES'].render(
        printer=m.p, params={'CLASS': material_class},
        cooling_moves=3, cooling_len=10,
        cooling_speed_list=[300, 240, 150], stamp_len=35)
    assert '_OPENACE_ROLLBACK_ASSIST_ON' not in script
    assert '_OPENACE_ROLLBACK_ASSIST_OFF' not in script


@pytest.mark.parametrize('material_class,forward,reverse', [
    ('soft', 5, 62), ('petg', 105, 132), ('abs', 70, 127), ('pla', 70, 180),
    ('unknown-class', 70, 180),  # Existing recipe fallback executes PLA moves.
])
def test_optional_tip_phase_report_preserves_moves_and_barrier_totals(material_class, forward, reverse):
    model = HeaterModel(ROOT / 'config/live')
    model.p['openace'] = {}
    def render(report):
        params = {'CLASS': material_class}
        if report: params['REPORT_ID'] = 'review-action-1'
        return [line.strip() for line in model.templates['_TIP_SHAPE_MOVES'].render(
            printer=model.p, params=params, cooling_moves=3, cooling_len=10,
            cooling_speed_list=[300, 240, 150], stamp_len=35).splitlines() if line.strip()]
    plain, reported = render(False), render(True)
    reports = [line for line in reported if line.startswith('_WMP_TIP_PHASE_REPORT ')]
    assert len(reports) == 3
    assert [line for line in reported if line not in reports] == plain
    assert 'KNOWN=0' in reports[0] and 'PENDING=1' in reports[0]
    assert reported[reported.index(reports[1])-1] == 'M400'
    assert reported[reported.index(reports[2])-1] == 'M400'
    assert f'FORWARD={forward}' in reports[2] and f'REVERSE={reverse}' in reports[2]
    assert 'PHASE=done' in reports[2] and 'PENDING=0' in reports[2]
    moves = [float(re.match(r'G1 E([-0-9.]+)', line)[1]) for line in plain if re.match(r'G1 E([-0-9.]+)', line)]
    assert sum(value for value in moves if value > 0) == pytest.approx(forward)
    assert -sum(value for value in moves if value < 0) == pytest.approx(reverse)
    # The helper only publishes commanded-E evidence; it must not trigger a
    # second movement or treat this as measured ACE feeder travel.
    report = model.templates['_WMP_TIP_PHASE_REPORT'].render(printer=model.p, params={
        'ID':'review-action-1','CLASS':material_class,'SEQ':'2','PHASE':'done',
        'KNOWN':'1','FORWARD':str(forward),'REVERSE':str(reverse),'PENDING':'0'})
    commands = [line.strip() for line in report.splitlines() if line.strip()]
    assert len(commands) == 1 and commands[0].startswith('SET_GCODE_VARIABLE MACRO=_TIP_SHAPE_RETRACT ')
    import ast
    payload = ast.literal_eval(shlex.split(commands[0])[-1].split('=', 1)[1])
    assert payload['invocation'] == 'review-action-1'
    assert payload['completed_e_mm'] == pytest.approx(forward-reverse)


@pytest.mark.parametrize('with_openace', [False, True])
def test_pla_retract_nets_110mm_and_assists_final_pull(with_openace):
    model = HeaterModel(ROOT / 'config/live')
    if with_openace:
        model.p['openace'] = {}
    scripts = {}
    for material_class in ('pla', 'petg', 'abs', 'soft'):
        script = model.templates['_TIP_SHAPE_MOVES'].render(
            printer=model.p, params={'CLASS': material_class},
            cooling_moves=3, cooling_len=10,
            cooling_speed_list=[300, 240, 150], stamp_len=35)
        moves = [float(value) for value in re.findall(r'(?m)^\s*G1 E(-?[\d.]+)', script)]
        assert sum(moves) == {'pla': -110, 'petg': -27, 'abs': -57, 'soft': -57}[material_class]
        scripts[material_class] = script
    commands = [line.split(';', 1)[0].strip() for line in scripts['pla'].splitlines()
                if line.strip()]
    final = commands.index('G1 E-100 F1500')
    if with_openace:
        assert commands.index('_OPENACE_ROLLBACK_ASSIST_ON') < final
        assert commands.index('_OPENACE_ROLLBACK_ASSIST_OFF') > final
        assert commands[final + 1] == 'M400'
    else:
        assert '_OPENACE_ROLLBACK_ASSIST_' not in scripts['pla']


def test_print_end_reaches_sd_eof_without_resetting_its_active_reader():
    """Klipper rejects SDCARD_RESET_FILE inside the SD command it is executing.

    Render the shipped macro without openACE installed. Its cleanup must finish
    and leave EOF to the SD worker, instead of turning a finished print into an
    error before the trailing mapping/probe settings are restored.
    """
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings'].update({
        'printer': {'max_velocity': 600, 'max_accel': 10000},
        'stepper_z': {'position_endstop': 300},
    })
    m.p['toolhead'].update({'homed_axes': 'xyz', 'position': {'z': 2.}})
    m.p['gcode_move'] = {'gcode_position': {'z': 2.}, 'position': {'z': 2.}}
    script = m.templates['PRINT_END'].render(printer=m.p, params={}, bed_drop=50.)
    commands = [line.strip().split('#', 1)[0].strip() for line in script.splitlines()]
    restored, heaters_off = {}, False
    for line in commands:
        if not line:
            continue
        command = line.split()[0]
        if command == 'SDCARD_RESET_FILE':
            raise RuntimeError('SDCARD_RESET_FILE cannot be run from the sdcard')
        if command == 'TURN_OFF_HEATERS':
            heaters_off = True
        if command == 'SAVE_VARIABLE':
            fields = dict(token.split('=', 1) for token in shlex.split(line)[1:])
            restored[fields['VARIABLE']] = int(fields['VALUE'])
    # The worker can now reach EOF; no mock reset or fake completion is needed.
    assert heaters_off
    assert {key: restored[key] for key in ('box_modify_t0', 'box_modify_t1',
                                          'box_modify_t2', 'box_modify_t3', 'probe_tool')} == {
        'box_modify_t0': 0, 'box_modify_t1': 1, 'box_modify_t2': 2,
        'box_modify_t3': 3, 'probe_tool': 0,
    }


@pytest.mark.parametrize('distance', [-50, -20, -1, 1, 20, 50])
@pytest.mark.parametrize("helper_protocol", [None, 0, 1])
def test_manual_step_is_only_extrusion(distance, helper_protocol):
    template = templates(ROOT / 'config/live')['WMP_EXTRUDER_STEP']
    printer = {'toolhead': {'extruder': 'extruder2'},
               'extruder2': {'can_extrude': True},
               'gcode_move': {'extrude_factor': 1.0, 'speed_factor': 1.0},
               'save_variables': {'variables': {'current_extruder': 2}},
               'custom_hall': {'Raw': 4000},
               'filament_switch_sensor sensor_b': {'filament_detected': True},
               'filament_switch_sensor docked2': {'filament_detected': False},
               'print_stats': {'state': 'paused'}}
    if helper_protocol is not None:
        printer["wm_material"] = {"filament_check_protocol": helper_protocol}
    def error(message):
        raise RuntimeError(message)
    script = template.render(printer=printer, params={'HEAD': '2', 'MM': str(distance)}, action_raise_error=error)
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    prefix = ['WMP_FORGET_FILAMENT HEAD=2'] if helper_protocol == 1 else []
    assert commands == prefix + ['SAVE_GCODE_STATE NAME=WMP_MANUAL_STEP',
                        'M83', f'G1 E{float(distance)} F300.0',
                        'M400', 'RESTORE_GCODE_STATE NAME=WMP_MANUAL_STEP MOVE=0']


@pytest.mark.parametrize('state', ['standby', 'complete', 'cancelled'])
def test_manual_step_selects_sensor_confirmed_mounted_head_after_restart(state):
    printer = {'toolhead': {'extruder': 'extruder'},
               'extruder2': {'can_extrude': True},
               'gcode_move': {'extrude_factor': 1.0, 'speed_factor': 1.0},
               'wm_material': {'attachment': {'state': 'attached', 'head': 'h2'},
                               'filament_operation': {}},
               'print_stats': {'state': state}}
    def error(message):
        raise RuntimeError(message)
    template = templates(ROOT / 'config/live')['WMP_EXTRUDER_STEP']
    script = template.render(printer=printer, params={'HEAD': '2', 'MM': '30'}, action_raise_error=error)
    assert script.index('ACTIVATE_EXTRUDER EXTRUDER=extruder2') < script.index('G1 E30.0')
    for attachment in [{'state': 'unknown'}, {'state': 'empty'}, {'state': 'attached', 'head': 'h1'}]:
        printer['wm_material']['attachment'] = attachment
        with pytest.raises(RuntimeError):
            template.render(printer=printer, params={'HEAD': '2', 'MM': '30'}, action_raise_error=error)


@pytest.mark.parametrize('change,params', [
    ({'openace': {}}, {}),
    ({'print_stats': {'state': 'printing'}}, {}),
    ({'print_stats': {'state': 'error'}}, {}),
    ({'toolhead': {'extruder': 'extruder1'}}, {}),
    ({'extruder2': {'can_extrude': False}}, {}),
    ({'save_variables': {'variables': {'current_extruder': 99}}}, {}),
    ({'custom_hall': {'Raw': 5000}}, {}),
    ({'custom_hall': {'Raw': 0}}, {}),
    ({'filament_switch_sensor sensor_b': {'filament_detected': False}}, {}),
    ({'filament_switch_sensor docked2': {'filament_detected': True}}, {}),
    ({'gcode_move': {'extrude_factor': 0, 'speed_factor': 1}}, {}),
    ({}, {'HEAD': '3'}), ({}, {'MM': '0'}), ({}, {'MM': '51'}),
    ({}, {'MM': '-51'}), ({}, {'MM': 'nan'}), ({}, {'MM': 'inf'}),
])
def test_manual_step_refuses_before_any_commands(change, params):
    template = templates(ROOT / 'config/live')['WMP_EXTRUDER_STEP']
    printer = {'toolhead': {'extruder': 'extruder2'},
               'extruder2': {'can_extrude': True},
               'gcode_move': {'extrude_factor': 1.0, 'speed_factor': 1.0},
               'save_variables': {'variables': {'current_extruder': 2}},
               'custom_hall': {'Raw': 4000},
               'filament_switch_sensor sensor_b': {'filament_detected': True},
               'filament_switch_sensor docked2': {'filament_detected': False},
               'print_stats': {'state': 'paused'}}
    printer.update(change)
    def error(message):
        raise RuntimeError(message)
    with pytest.raises(RuntimeError):
        template.render(printer=printer, params={'HEAD': '2', 'MM': '20', **params}, action_raise_error=error)


@pytest.mark.parametrize('distance', [-20, 20])
def test_manual_step_preserves_vendor_gcode_state_with_overrides(distance):
    # Exercise the real firmware implementation: its restore intentionally omits
    # restoring base_position, unlike upstream Klipper. Local firmware is not shipped.
    import importlib.util
    from types import SimpleNamespace
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'
    if not path.exists():
        pytest.skip('local firmware analysis source is not distributed')
    spec = importlib.util.spec_from_file_location('vendor_gcode_move_step', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    move = module.GCodeMove.__new__(module.GCodeMove)
    move.absolute_coord = move.absolute_extrude = True
    move.base_position = [0., 0., 0., 20.]
    move.last_position = [50., 60., 10., 100.]
    move.homing_position = [0., 0., 0., 0.]
    move.speed, move.speed_factor, move.extrude_factor = 35., 1.5 / 60., .8
    move.saved_states = {}
    sent = []
    move.move_with_transform = lambda pos, speed: sent.append((list(pos), speed))
    objects = {
        'custom_hall': SimpleNamespace(last_adc_value_raw=4000),
        'toolhead': SimpleNamespace(get_status=lambda now: {'extruder': 'extruder2'}),
        'save_variables': SimpleNamespace(allVariables={'current_extruder': 2}),
    }
    move.printer = SimpleNamespace(quick_stop_flag=False,
        get_reactor=lambda: SimpleNamespace(monotonic=lambda: 1.),
        lookup_object=lambda key: objects[key])
    printer = {'toolhead': {'extruder': 'extruder2'},
               'extruder2': {'can_extrude': True},
               'gcode_move': {'extrude_factor': .8, 'speed_factor': 1.5},
               'save_variables': {'variables': {'current_extruder': 2}},
               'custom_hall': {'Raw': 4000},
               'filament_switch_sensor sensor_b': {'filament_detected': True},
               'filament_switch_sensor docked2': {'filament_detected': False},
               'print_stats': {'state': 'paused'}}
    def error(message):
        raise RuntimeError(message)
    script = templates(ROOT / 'config/live')['WMP_EXTRUDER_STEP'].render(
        printer=printer, params={'HEAD': '2', 'MM': str(distance)}, action_raise_error=error)
    class Command:
        def __init__(self, args): self.args = args
        def get(self, name, default=None): return self.args.get(name, default)
        def get_int(self, name, default=0): return int(self.get(name, default))
        def get_command_parameters(self): return self.args
        def error(self, message): return RuntimeError(message)
    for line in script.splitlines():
        words = line.strip().split()
        if not words: continue
        command = words[0]
        if command == 'M400': continue
        args = dict(re.findall(r'([EF])([-+0-9.]+)', line)) if command == 'G1' else dict(word.split('=', 1) for word in words[1:])
        getattr(move, 'cmd_' + command)(Command(args))
    assert len(sent) == 1
    assert sent[0][0] == [50., 60., 10., 100. + distance]
    assert sent[0][1] == pytest.approx(5.)
    assert move.absolute_coord and move.absolute_extrude
    assert move.extrude_factor == .8 and move.speed_factor == 1.5 / 60.
    assert move.speed == 35.
    assert (move.last_position[3] - move.base_position[3]) / move.extrude_factor == pytest.approx(100.)


@pytest.mark.parametrize('macro', ['_CHECK_CHANGE_TOOL', 'PARK_CURRENT_TOOL_RETRY'])
@pytest.mark.parametrize('retry', [0, 1])
@pytest.mark.parametrize('state', ['standby', 'printing', 'paused'])
def test_docking_failure_aborts_before_retry_homing(macro, retry, state):
    printer = {'print_stats': {'state': state},
               'save_variables': {'variables': {'current_extruder': 2,
                                                'fail_tool': 2, 'fail_flag': -3}}}
    def error(message):
        raise RuntimeError(message)
    with pytest.raises(RuntimeError, match='automatic homing is blocked'):
        templates(ROOT / 'config/live')[macro].render(
            printer=printer, params={'T': '0'}, retry=retry, action_raise_error=error)
    assert printer['save_variables']['variables']['fail_flag'] == -3


@pytest.mark.parametrize('seated,raw,locked', [
    (False, 4500, True), (True, 4500, True), (True, 4900, True),
    (True, 4500, False), (True, float('nan'), False),
])
def test_failed_docking_stops_after_stock_retreat_without_rehoming(seated, raw, locked):
    # Expand the actual nested templates in execution order. Hardware UNLOCK
    # is stubbed with the observed coupling state; SAVE_VARIABLE is real state.
    ts = templates(ROOT / 'config/live')
    p = {'save_variables': {'variables': {'is_nozzle_setting': 0, 'fail_flag': 0,
                                         'current_extruder': 2}},
         'custom_hall': {'Raw': raw},
         'filament_switch_sensor sensor_b': {'filament_detected': locked},
         'filament_switch_sensor docked2': {'filament_detected': seated}}
    commands = []
    def error(message): raise RuntimeError(message)
    def run(name, params):
        script = ts[name].render(printer=copy.deepcopy(p), params=params,
                                action_raise_error=error, action_respond_info=lambda *a: '')
        for line in script.splitlines():
            words = shlex.split(line)
            if not words: continue
            cmd = words[0]
            args = dict(w.split('=', 1) for w in words[1:] if '=' in w)
            commands.append(cmd)
            if cmd == 'SAVE_VARIABLE':
                p['save_variables']['variables'][args['VARIABLE']] = int(args['VALUE'])
            elif cmd in ts and cmd != 'UNLOCK':
                run(cmd, args)
    with pytest.raises(RuntimeError, match='automatic homing is blocked'):
        run('_CHECK_AND_UNLOCK', {'T': '2'})
    assert p['save_variables']['variables']['fail_flag'] == -3
    assert p['save_variables']['variables']['fail_tool'] == 2
    assert not set(commands) & {'G1', 'G28'}
    assert commands.count('G0') == int(seated)
    assert ('UNLOCK' in commands) == seated


def test_dock_settling_wait_finishes_before_sensor_check():
    text = (ROOT / 'config/live/change_macros.cfg').read_text()
    block = text.split('[gcode_macro _UNLOCK_TOOL]', 1)[1].split('[gcode_macro ', 1)[0]
    commands = [l.strip() for l in block.splitlines() if l.strip() and not l.lstrip().startswith('#')]
    dwell = commands.index('G4 P1000')
    assert commands[dwell + 1] == 'M400'
    assert commands[dwell + 2] == '_CHECK_AND_UNLOCK T={current_extruder}'


@pytest.mark.parametrize('axes', ['', 'xy', 'xyz'])
def test_dock_offset_reset_does_not_move_unhomed_z(axes):
    printer = {
        'save_variables': {'variables': dict(fail_flag=0, current_extruder=2,
            **{'t%d_position' % i: [40 + i * 60, 340] for i in range(4)})},
        'toolhead': {'homed_axes': axes},
        'gcode_move': {'position': {'y': 80}},
    }
    script = templates(ROOT / 'config/live')['_UNLOCK_TOOL'].render(
        printer=printer, params={'T': '2'})
    commands = [line.strip() for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    reset = next(line for line in commands if line.startswith('SET_GCODE_OFFSET'))
    assert reset.endswith('MOVE=%d' % ('z' in axes))
    assert ('G28 X Y' in commands) == ('xy' not in axes)
    assert not any(line.startswith(('G0 Z', 'G1 Z', 'G28 Z')) for line in commands)
    assert '_CHECK_AND_UNLOCK T=2' in commands


@pytest.mark.parametrize('macro', ['_CHANGE_TOOL', 'PARK_CURRENT_TOOL'])
def test_new_action_cannot_erase_unresolved_docking_failure(macro):
    def error(message): raise RuntimeError(message)
    with pytest.raises(RuntimeError, match='remains unresolved'):
        templates(ROOT / 'config/live')[macro].render(
            printer={'save_variables': {'variables': {'fail_flag': -3}}},
            params={'T': '0'}, action_raise_error=error)


@pytest.mark.parametrize('params', [{}, {'X': ''}, {'Y': ''}, {'Z': ''}, {'X': '', 'Y': ''}],
                         ids=['all', 'x', 'y', 'z', 'xy'])
def test_direct_homing_refuses_unresolved_docking_failure(params):
    text = (ROOT / 'config/live/printer.cfg').read_text()
    block = text.split('[homing_override]', 1)[1].split('[gcode_macro ', 1)[0].split('gcode:', 1)[1]
    env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
    def error(message): raise RuntimeError(message)
    with pytest.raises(RuntimeError, match='before homing'):
        env.from_string(block).render(printer={'save_variables': {'variables': {'fail_flag': -3}}},
                                      params=params, action_raise_error=error)


def test_verified_release_permits_existing_retreat_sequence():
    ts = templates(ROOT / 'config/live')
    printer = {'save_variables': {'variables': {'is_nozzle_setting': 0}},
               'custom_hall': {'Raw': 4900},
               'filament_switch_sensor sensor_b': {'filament_detected': False},
               'filament_switch_sensor docked2': {'filament_detected': True}}
    def error(message): raise RuntimeError(message)
    release = ts['_WMP_REQUIRE_RELEASE'].render(printer=printer, params={'T': '2'}, action_raise_error=error)
    assert not release.strip()
    script = ts['_CHECK_AND_UNLOCK'].render(printer=printer, params={'T': '2'})
    commands = [line.strip() for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    assert commands == ['UNLOCK', 'G0 Y310 F6000',
                        'M400', 'UNLOCK_TOOL_FINISH']


@pytest.mark.parametrize('managed', [False, True])
def test_release_retires_orphan_delay_but_preserves_actuator_and_retreat_barriers(managed):
    ts = templates(ROOT / 'config/live')
    printer = {'save_variables': {'variables': {'is_nozzle_setting': 0}},
               'filament_switch_sensor docked2': {'filament_detected': True}}
    if managed:
        printer['wm_material'] = {'session_id': 'session-a', 'command_generation': 7}
    def commands(script):
        return [line.strip() for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    unlock = commands(ts['UNLOCK'].render(printer=printer, params={}))
    assert unlock == [
        '_WMP_COUPLING_STROKE LOCK=0 SESSION=session-a GENERATION=7' if managed else
        'ECHELON_STEPPER_HOMING STEPPER=trans_stepper MOVE=150 SPEED=100 PDI=0',
        'ECHELON_STEPPER_DISABLE STEPPER=trans_stepper',
        'M400']
    current = commands(ts['_CHECK_AND_UNLOCK'].render(printer=printer, params={'T': '2'}))
    stock = commands(templates(ROOT / 'config/stock')['_CHECK_AND_UNLOCK'].render(
        printer=printer, params={'T': '2'}))
    assert stock == ['UNLOCK', 'G0 Y310 F6000', 'M400', 'UNLOCK_TOOL_FINISH']
    assert current == (['_WMP_CHECK_DOCK_SUPPORT HEAD=2 SESSION=session-a GENERATION=7'] if managed else []) + stock


@pytest.mark.parametrize('unlock_fails', [False, True])
def test_dock_presence_is_checked_only_after_successful_unlock_and_retreat(unlock_fails):
    ts = templates(ROOT / 'config/live')
    printer = {'save_variables': {'variables': {'is_nozzle_setting': 0, 'fail_flag': 0}},
               'custom_hall': {'Raw': 4000},
               'filament_switch_sensor sensor_b': {'filament_detected': True},
               'filament_switch_sensor docked2': {'filament_detected': True}}
    script = ts['_CHECK_AND_UNLOCK'].render(printer=printer, params={'T': '2'})
    commands = []
    def error(message): raise RuntimeError(message)
    def execute():
        for line in script.splitlines():
            words = shlex.split(line)
            if not words or words[0].startswith('#'): continue
            commands.append(words[0])
            if words[0] == 'UNLOCK' and unlock_fails:
                raise RuntimeError('unlock actuator failed')
            if words[0] == 'G0':
                assert line.strip() == 'G0 Y310 F6000'
                printer['custom_hall']['Raw'] = 5021
                printer['filament_switch_sensor sensor_b']['filament_detected'] = False
            if words[0] == 'UNLOCK_TOOL_FINISH':
                result = ts[words[0]].render(printer=printer, params={'T': '2'},
                                             action_raise_error=error, action_respond_info=lambda *a: '')
                assert 'SAVE_VARIABLE VARIABLE=current_extruder VALUE=99' in result
    if unlock_fails:
        with pytest.raises(RuntimeError, match='actuator failed'): execute()
        assert commands == ['UNLOCK']
    else:
        execute()
        assert commands.index('UNLOCK') < commands.index('G0') < commands.index('UNLOCK_TOOL_FINISH')


@pytest.mark.parametrize('wiped', [False, True])
def test_resume_checks_service_before_heat_and_does_not_repeat_completed_wipe(wiped):
    model = HeaterModel(ROOT / 'config/live')
    model.p['wm_material'] = {'paused_filament': {'wipe_completed': wiped}}
    model.p['heater_bed']['target'] = 60
    for i in range(4): model.p['save_variables']['variables']['box_modify_t%d_backup' % i] = i
    script = model.templates['RESUME'].render(printer=model.p, params={}, resume_bed=60,
        resume_temperature0=220, resume_temperature1=0, resume_temperature2=0,
        resume_temperature3=0, fan=128, afan=0, airfan=0)
    commands = [line.strip() for line in script.splitlines() if line.strip() and not line.strip().startswith('#')]
    assert commands[0] == 'WMP_CHECK_RESUME'
    checks = [i for i, command in enumerate(commands) if command in ('WMP_CHECK_RESUME', 'WMP_PREPARE_RESUME_E')]
    assert len(checks) == 2
    assert checks[1] > max(i for i, command in enumerate(commands) if command.startswith('TEMPERATURE_WAIT'))
    assert checks[1] < commands.index('G0 Y200 F12000')
    heated = commands.index('_WMP_STOP_POINT PHASE=resume_heated')
    wiped_boundary = commands.index('_WMP_STOP_POINT PHASE=resume_wiped')
    return_boundary = commands.index('_WMP_STOP_POINT PHASE=resume_return_ready')
    returned = commands.index('_WMP_STOP_POINT PHASE=resume_returned')
    assert max(i for i, c in enumerate(commands) if c.startswith('TEMPERATURE_WAIT')) < heated < checks[1]
    wipe_ready = commands.index('_WMP_STOP_POINT PHASE=resume_wipe_ready')
    assert checks[1] < wipe_ready < wiped_boundary
    if not wiped: assert wipe_ready < commands.index('WIPE_NOZZLE') < wiped_boundary
    assert wiped_boundary < commands.index('G0 Y200 F12000') < return_boundary
    assert return_boundary < commands.index('RESTORE_GCODE_STATE NAME=PAUSE MOVE=1 MOVE_SPEED=60') < returned
    assert returned < commands.index('CLEAR_PAUSE') < commands.index('M24')
    assert ('WIPE_NOZZLE' in commands) == (not wiped)
    assert any(c.startswith('E_axis_move') for c in commands) == (not wiped)
    assert 'RESTORE_GCODE_STATE NAME=PAUSE MOVE=1 MOVE_SPEED=60' in commands
    assert commands.index('RESTORE_GCODE_STATE NAME=PAUSE MOVE=1 MOVE_SPEED=60') < commands.index('WMP_RESTORE_RESUME_E') < commands.index('CLEAR_PAUSE')
    assert commands.index('CLEAR_PAUSE') < commands.index('M24')


@pytest.mark.parametrize('owner,paused,routed', [('standalone', True, True),
    ('standalone', False, False), ('openace', True, False)])
def test_m24_paused_standalone_routes_through_guarded_resume(owner, paused, routed):
    model = HeaterModel(ROOT / 'config/live')
    model.p.update(wm_material={}, pause_resume={'is_paused': paused},
        print_stats={'filename': 'part.gcode', 'state': 'paused' if paused else 'standby'},
        virtual_sdcard={'is_active': False})
    model.p['gcode_macro _WMP_RECOVERY_BEGIN'] = {'active': False}
    if owner == 'openace': model.p['openace'] = {}
    script = model.templates['M24'].render(printer=model.p, params={}, rawparams='')
    commands = [line.strip() for line in script.splitlines()
                if line.strip() and not line.strip().startswith('#')]
    assert commands == (['RESUME'] if routed else ['M9924'])


CALIBRATION_HEAD_MACROS = ('NOZZLE_PREPARE', 'NOZZLE_CALIBRATE_TOOL_OFFSET',
                           'RAPID_MODE', 'CALIBRATE_TOOL_OFFSET', 'CALIBRATE_TOOL_Z_OFFSET')

@pytest.mark.parametrize('macro', CALIBRATION_HEAD_MACROS +
                         ('CALIBRATE_OFFSET_ALL_RAPID_MODE', 'CALIBRATE_OFFSET_ALL_FINE_MODE'))
@pytest.mark.parametrize('state', ['printing', 'paused'])
def test_calibration_rejects_active_job_before_emitting_commands(macro, state):
    def error(message): raise RuntimeError(message)
    with pytest.raises(RuntimeError, match='idle maintenance'):
        templates(ROOT / 'config/live')[macro].render(
            printer={'print_stats': {'state': state}}, params={'T': '2'}, action_raise_error=error)

@pytest.mark.parametrize('macro', CALIBRATION_HEAD_MACROS + ('_SAVE_PROBE_POS',))
@pytest.mark.parametrize('tool', [None, '-1', '4', '99', 'banana', '1.5'])
def test_calibration_rejects_invalid_physical_head(macro, tool):
    def error(message): raise RuntimeError(message)
    with pytest.raises(RuntimeError, match='physical calibration head'):
        templates(ROOT / 'config/live')[macro].render(
            printer={}, params={} if tool is None else {'T': tool}, action_raise_error=error)

@pytest.mark.parametrize('macro', CALIBRATION_HEAD_MACROS)
@pytest.mark.parametrize('tool', range(4))
def test_calibration_keeps_physical_head_despite_slicer_mapping(macro, tool):
    m = HeaterModel(ROOT / 'config/live', mapping=(3, 3, 0, 1))
    m.p['print_stats']['state'] = 'standby'
    m.p['toolhead']['homed_axes'] = 'xyz'
    m.p['save_variables']['variables'].update(current_extruder=tool,
                                             probe_position=(299, 290, 8.5, 6.9, 5.8))
    script = m.templates[macro].render(printer=m.p, params={'T': str(tool)},
                                       action_respond_info=lambda *a: '')
    commands = [line.strip().split(';', 1)[0].strip() for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith(('#', ';'))]
    assert not any(re.match(r'T[0-3](?:\s|$)|M10[49]\s', line) for line in commands)
    if macro in ('NOZZLE_PREPARE', 'CALIBRATE_TOOL_OFFSET', 'CALIBRATE_TOOL_Z_OFFSET'):
        assert f'_CHANGE_TOOL T={tool}' in commands
    heater = 'extruder' if tool == 0 else f'extruder{tool}'
    for line in commands:
        if line.startswith('TEMPERATURE_WAIT'):
            assert f'SENSOR={heater} ' in line
    if macro == 'NOZZLE_CALIBRATE_TOOL_OFFSET':
        expected = [heater] + ([f'extruder{tool + 1}'] if tool < 3 else [])
        actual = {re.search(r'HEATER=(\S+)', line)[1] for line in commands
                  if line.startswith('SET_HEATER_TEMPERATURE')}
        assert actual == set(expected)


@pytest.mark.parametrize('previous', [0, 1, 3, 99])
def test_z_calibration_records_after_tool_change_not_from_entry_snapshot(previous):
    ts = templates(ROOT / 'config/live')
    printer = {'print_stats': {'state': 'standby'},
               'save_variables': {'variables': {'current_extruder': previous, 'fail_flag': 0}}}
    script = ts['CALIBRATE_TOOL_Z_OFFSET'].render(printer=printer, params={'T': '2'})
    commands = [line.strip() for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    assert commands.index('_CHANGE_TOOL T=2') < commands.index('probe')
    assert commands.index('probe') < commands.index('M400') < commands.index('_SAVE_PROBE_POS T=2')
    # The nested macro receives fresh state, after selection and probing.
    printer['save_variables']['variables']['current_extruder'] = 2
    printer['probe'] = {'last_z_result': 1.23456789}
    saved = ts['_SAVE_PROBE_POS'].render(printer=printer, params={'T': '2'})
    assert 'VARIABLE=z_pos VALUE=1.234568' in saved
    assert 'VARIABLE=z0_pos' not in saved

@pytest.mark.parametrize('current,fault', [(0, 0), (99, 0), (2, -3), (2, 1)])
def test_probe_result_refuses_wrong_head_or_failed_change(current, fault):
    def error(message): raise RuntimeError(message)
    # No probe data supplied: rejection must happen before consuming any result.
    with pytest.raises(RuntimeError, match='not recorded'):
        templates(ROOT / 'config/live')['_SAVE_PROBE_POS'].render(
            printer={'save_variables': {'variables': {'current_extruder': current, 'fail_flag': fault}}},
            params={'T': '2'}, action_raise_error=error)

def test_physical_head_zero_records_calibration_reference():
    script = templates(ROOT / 'config/live')['_SAVE_PROBE_POS'].render(
        printer={'save_variables': {'variables': {'current_extruder': 0, 'fail_flag': 0}},
                 'probe': {'last_z_result': 2.125}}, params={'T': '0'})
    assert 'VARIABLE=z0_pos VALUE=2.125' in script
    assert 'VARIABLE=z_pos VALUE=0' in script


def calibration_save_script(axes='XYZ', current=2, fault=0, z_tool=2, reference=1):
    def error(message): raise RuntimeError(message)
    return templates(ROOT / 'config/live')['SAVE_TOOL_OFFSET'].render(
        printer={'save_variables': {'variables': {'current_extruder': current, 'fail_flag': fault}},
                 'tools_calibrate': {'last_result': (0.12, -0.25, 9)}},
        params={'T': '2', 'AXES': axes}, z_tool=z_tool, reference_valid=reference,
        z_pos=1.75, z0_pos=1.5, action_raise_error=error)


def test_xy_calibration_save_preserves_existing_z_without_z_measurement():
    script = calibration_save_script(axes='XY', z_tool=99, reference=0)
    command = next(line.strip() for line in script.splitlines() if line.strip().startswith('SAVE_T_OFFSET'))
    assert command == 'SAVE_T_OFFSET T=2 X=0.12 Y=-0.25'
    saved = templates(ROOT / 'config/live')['SAVE_T_OFFSET'].render(
        printer={'save_variables': {'variables': {'t2_offset': (1, 2, 0.375)}}},
        params={'T': '2', 'X': '0.12', 'Y': '-0.25'}, action_respond_info=lambda *a: '')
    assert 'VALUE=0.12,-0.25,0.375' in saved


@pytest.mark.parametrize('z_tool,reference', [(99, 1), (1, 1), (2, 0)])
def test_final_calibration_save_requires_this_head_and_reference_measurements(z_tool, reference):
    with pytest.raises(RuntimeError, match='Fresh Z measurements'):
        calibration_save_script(z_tool=z_tool, reference=reference)


def test_final_calibration_save_consumes_the_matching_z_measurement():
    script = calibration_save_script()
    assert 'SAVE_T_OFFSET T=2 X=0.12 Y=-0.25 Z=0.25' in script
    assert script.index('SAVE_T_OFFSET') < script.index('VARIABLE=z_tool VALUE=99')


@pytest.mark.parametrize('axes', ['XY', 'XYZ'])
@pytest.mark.parametrize('current,fault', [(0, 0), (99, 0), (2, -3)])
def test_calibration_offset_save_rejects_changed_or_faulted_head(axes, current, fault):
    with pytest.raises(RuntimeError, match='Offsets were not saved'):
        calibration_save_script(axes=axes, current=current, fault=fault)


@pytest.mark.parametrize('tool', [0, 2])
def test_z_measurement_invalidated_before_change_and_probe(tool):
    script = templates(ROOT / 'config/live')['CALIBRATE_TOOL_Z_OFFSET'].render(
        printer={'print_stats': {'state': 'standby'}}, params={'T': str(tool)})
    assert script.index('VARIABLE=z_tool VALUE=99') < script.index('_CHANGE_TOOL') < script.index('\n    probe')
    assert ('VARIABLE=reference_valid VALUE=0' in script) == (tool == 0)


def test_rapid_calibration_saves_xy_before_z_then_saves_combined_result():
    script = templates(ROOT / 'config/live')['RAPID_MODE'].render(
        printer={'print_stats': {'state': 'standby'}, 'toolhead': {'homed_axes': 'xyz'}}, params={'T': '2'})
    commands = [line.strip() for line in script.splitlines() if line.strip().startswith(('CALIBRATE_', 'SAVE_TOOL_OFFSET'))]
    assert commands == ['CALIBRATE_TOOL_OFFSET   T=2', 'SAVE_TOOL_OFFSET        T=2 AXES=XY',
                        'CALIBRATE_TOOL_Z_OFFSET T=2', 'SAVE_TOOL_OFFSET        T=2']


def calibration_commands(macro, tool):
    m = HeaterModel(ROOT / 'config/live')
    m.p['print_stats']['state'] = 'standby'
    m.p['toolhead']['homed_axes'] = 'xyz'
    m.p['save_variables']['variables'].update(probe_position=(299, 290, 8.5, 6.9, 5.8))
    script = m.templates[macro].render(printer=m.p, params={'T': str(tool)}, action_respond_info=lambda *a: '')
    return [line.strip() for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')]


@pytest.mark.parametrize('tool', range(4))
def test_rapid_mode_reports_phases(tool):
    offset = calibration_commands('CALIBRATE_TOOL_OFFSET', tool)
    height = calibration_commands('CALIBRATE_TOOL_Z_OFFSET', tool)
    phase = lambda name: f'_WMP_CALIBRATION_PHASE HEAD={tool} PHASE={name}'
    sensor = 'TOOL_LOCATE_SENSOR' if tool == 0 else 'TOOL_CALIBRATE_TOOL_OFFSET'
    assert offset.index(phase('mounting')) < offset.index(f'_CHANGE_TOOL T={tool}')
    assert offset.index(phase('position')) < offset.index(sensor)
    assert height.index(phase('height')) < height.index('probe')
    assert offset.count(phase('mounting')) == offset.count(phase('position')) == height.count(phase('height')) == 1


def test_phase_calls_are_inside_marked_blocks():
    text = (ROOT / 'config/live/offset_calibrate.cfg').read_text()
    lines = text.splitlines()
    found = [i for i, line in enumerate(lines) if '_WMP_CALIBRATION_PHASE' in line]
    assert len(found) == 3
    for i in found:
        begin = max(j for j in range(i) if lines[j].strip().startswith('# >>> wondermaker+ begin:'))
        assert lines[begin].strip() == '# >>> wondermaker+ begin: calibration-progress'
        assert not any(lines[j].strip().startswith('# <<< wondermaker+ end:') for j in range(begin, i))
        assert lines[i + 1].strip() == '# <<< wondermaker+ end: calibration-progress'


def test_print_end_reaches_sd_eof_and_finishes_cleanup_without_resetting_reader():
    m = HeaterModel(ROOT / 'config/live')
    m.p['configfile']['settings']['printer'] = {'max_velocity': 600, 'max_accel': 10000}
    script = m.templates['PRINT_END'].render(printer=m.p, params={})
    commands = [line.split('#', 1)[0].strip() for line in script.splitlines()]
    restored = {}
    for line in commands:
        if not line:
            continue
        command = line.split()[0]
        if command == 'SDCARD_RESET_FILE':
            raise RuntimeError('SDCARD_RESET_FILE cannot be run from the sdcard')
        if command == 'SAVE_VARIABLE':
            fields = dict(token.split('=', 1) for token in shlex.split(line)[1:])
            restored[fields['VARIABLE']] = int(fields['VALUE'])
    assert {key: restored[key] for key in ('box_modify_t0', 'box_modify_t1',
                                          'box_modify_t2', 'box_modify_t3', 'probe_tool')} == {
        'box_modify_t0': 0, 'box_modify_t1': 1, 'box_modify_t2': 2, 'box_modify_t3': 3, 'probe_tool': 0}
    assert commands.index('TURN_OFF_HEATERS') < commands.index('_WMP_CASE_LIGHT_PRINT_END')


@pytest.mark.parametrize('macro', ['_CHANGE_TOOL', 'PARK_CURRENT_TOOL', '_CHECK_CHANGE_TOOL', 'PARK_CURRENT_TOOL_RETRY', 'LOCK', '_LOCK_CHECK'])
@pytest.mark.parametrize('flag', [-1, -2, -4, -5, -6, 7])
@pytest.mark.parametrize('retry', [0, 1])
@pytest.mark.parametrize('state', ['standby', 'printing', 'paused'])
def test_managed_toolchange_faults_never_clear_or_retry(macro, flag, retry, state):
    printer = {'wm_material': {}, 'print_stats': {'state': state},
               'save_variables': {'variables': {'current_extruder': 2, 'fail_flag': flag}}}
    before = copy.deepcopy(printer)
    def error(message): raise RuntimeError(message)
    if macro == '_CHECK_CHANGE_TOOL':
        script = templates(ROOT / 'config/live')[macro].render(
            printer=printer, params={'T':'0'}, retry=retry, action_raise_error=error)
        assert [line.strip() for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')] == ['_WMP_TOOLCHANGE_FAULT REASON=toolchange']
    else:
        with pytest.raises(RuntimeError, match='automatic retry is blocked'):
            templates(ROOT / 'config/live')[macro].render(
                printer=printer, params={'T':'0'}, retry=retry, action_raise_error=error)
    assert printer == before


@pytest.mark.parametrize('owner', ['stock', 'openace', 'AFC'])
def test_retry_guard_does_not_take_over_other_owners(owner):
    printer = {'print_stats': {'state':'standby'},
               'save_variables': {'variables': {'current_extruder': 2, 'fail_flag': -2}}}
    if owner != 'stock': printer.update(wm_material={}, **{owner: {}})
    def error(message): raise RuntimeError(message)
    script = templates(ROOT / 'config/live')['_CHECK_CHANGE_TOOL'].render(
        printer=printer, params={'T':'0'}, retry=0, action_raise_error=error)
    assert 'SAVE_VARIABLE VARIABLE=fail_flag VALUE=0' in script
    assert '_CHANGING_TOOL T=0' in script


@pytest.mark.parametrize('entry,locked,raw', [('_LOCK_TOOL_FINISH',True,4900),
                                            ('_LOCK_TOOL_FINISH',False,4500)])
def test_failed_confirmation_dispatches_supported_cleanup_without_preset_fault(entry, locked, raw):
    ts = templates(ROOT / 'config/live')
    p = {'wm_material': {'session_id':'s','command_generation':0}, 'custom_hall': {'Raw':raw},
         'filament_switch_sensor sensor_b': {'filament_detected':locked},
         'save_variables': {'variables': {'fail_flag':0}}}
    commands=[]; variables={'retry':0}
    def error(message): raise RuntimeError(message)
    def run(name, params):
        script=ts[name].render(printer=copy.deepcopy(p), params=params, **variables,
                              action_raise_error=error, action_respond_info=lambda *a: '')
        for line in script.splitlines():
            words=shlex.split(line)
            if not words: continue
            cmd=words[0]; args=dict(w.split('=',1) for w in words[1:] if '=' in w)
            commands.append(cmd)
            if cmd=='SAVE_VARIABLE': p['save_variables']['variables'][args['VARIABLE']]=int(args['VALUE'])
            elif cmd=='SET_GCODE_VARIABLE': variables[args['VARIABLE']]=int(args['VALUE'])
            elif cmd == '_WMP_FAILED_PICKUP_CLEANUP':
                assert p['save_variables']['variables']['fail_flag'] == 0
                assert args == {'HEAD': '2', 'SESSION': 's', 'GENERATION': '0'}
                p['save_variables']['variables']['fail_flag'] = -2
                raise RuntimeError('typed toolchange fault')
            elif cmd == '_WMP_TOOLCHANGE_FAULT': raise RuntimeError('typed toolchange fault')
            elif cmd in ts: run(cmd,args)
    with pytest.raises(RuntimeError, match='typed toolchange fault'):
        run(entry,{'T':'2'})
    assert p['save_variables']['variables']['fail_flag']==-2
    assert not set(commands)&{'ECHELON_STEPPER','UNLOCK','G28','G0','G1'}
    assert commands.count('_WMP_COUPLING_STROKE')==(1 if entry=='LOCK' else 0)
    assert 'ECHELON_STEPPER_HOMING' not in commands
    assert commands[-1]=='_WMP_FAILED_PICKUP_CLEANUP'


def test_successful_lock_finish_is_identical_under_managed_ownership():
    ts=templates(ROOT / 'config/live')
    p={'save_variables': {'variables': {'fail_flag':0}}, 'custom_hall': {'Raw':4500},
       'filament_switch_sensor sensor_b': {'filament_detected':True}}
    def render(printer):
        return ts['_LOCK_TOOL_FINISH'].render(printer=printer,params={'T':'2'},action_respond_info=lambda *a:'')
    assert render(p)==render(dict(p,wm_material={}))


@pytest.mark.parametrize('name,lock', [('LOCK',1),('UNLOCK',0)])
def test_standalone_coupling_routes_below_swallowed_vendor_exception(name,lock):
    printer={'wm_material': {'session_id':'session-a','command_generation':7},
             'save_variables': {'variables': {'fail_flag':0}}}
    script=templates(ROOT / 'config/live')[name].render(printer=printer,params={})
    assert '_WMP_COUPLING_STROKE LOCK=%d SESSION=session-a GENERATION=7'%lock in script
    assert 'ECHELON_STEPPER_HOMING' not in script
    script=templates(ROOT / 'config/live')[name].render(printer=dict(printer,openace={}),params={})
    assert 'ECHELON_STEPPER_HOMING' in script and '_WMP_COUPLING_STROKE' not in script


@pytest.mark.parametrize('macro', ['_CHANGE_TOOL', 'PARK_CURRENT_TOOL'])
@pytest.mark.parametrize('owner', ['stock', 'openace', 'AFC'])
def test_direct_tool_fault_guard_preserves_other_owner_entry(macro, owner):
    printer = {'save_variables': {'variables': {'current_extruder': 2, 'fail_flag': -2}}}
    if owner != 'stock':
        printer.update(wm_material={}, **{owner: {}})
    def error(message):
        raise RuntimeError(message)
    script = templates(ROOT / 'config/live')[macro].render(
        printer=printer, params={'T': '0'}, action_raise_error=error)
    assert 'SAVE_VARIABLE VARIABLE=fail_flag VALUE=0' in script


def test_pickup_sensor_wait_is_after_retreat_and_preserves_other_owner_route():
    source = (ROOT / 'config/live/change_macros.cfg').read_text()
    lock = source.split('[gcode_macro _LOCK_TOOL]', 1)[1].split('[gcode_macro ', 1)[0]
    assert lock.index('G0 Y310 F9600') < lock.rindex('_WMP_XY_TRAVEL Y=270') < lock.rindex('M400') < lock.index('_CHECK_T_SEQUENCE')
    check = templates(ROOT / 'config/live')['_CHECK_T_SEQUENCE']
    printer = {'save_variables': {'variables': {'fail_flag': 0, 'is_nozzle_setting': 0}},
               'wm_material': {'session_id': 'session', 'command_generation': 4},
               'filament_switch_sensor docked2': {'filament_detected': True}}
    def render():
        return check.render(printer=printer, params={'T': '2'}, action_respond_info=lambda *args: '')
    script = render()
    assert '_WMP_CHECK_PICKUP_RELEASE HEAD=2 SESSION=session GENERATION=4' in script
    assert 'SAVE_VARIABLE VARIABLE=fail_flag' not in script
    printer['openace'] = {}
    script = render()
    assert '_WMP_CHECK_PICKUP_RELEASE' not in script
    assert 'SAVE_VARIABLE VARIABLE=fail_flag VALUE=-5' in script
    del printer['openace']
    printer['save_variables']['variables']['is_nozzle_setting'] = 1
    assert '_WMP_CHECK_PICKUP_RELEASE' not in render()

@pytest.mark.parametrize('switches, expected', [([False]*4, [1,2,3,4]), ([False,True,True,True], [1]), ([True]*4, [])])
def test_lock_confirmation_retains_stock_bounded_sensor_sequence(switches, expected):
    t = templates(ROOT / 'config/live')
    printer = {'wm_material': {'session_id':'session', 'command_generation':0},
               'save_variables': {'variables': {'fail_flag':0}},
               'filament_switch_sensor sensor_b': {'filament_detected':False}}
    lock = t['LOCK'].render(printer=printer, params={})
    commands = [line.strip().split('#',1)[0].strip() for line in lock.splitlines() if line.strip() and not line.strip().startswith('#')]
    assert commands[0].startswith('_WMP_COUPLING_STROKE LOCK=1 SESSION=')
    assert commands[-2:] == ['ECHELON_STEPPER_DISABLE STEPPER=trans_stepper', 'M400']
    assert commands.count('_LOCK_CHECK') == 4
    attempts = []
    for retry, detected in enumerate(switches, 1):
        printer['filament_switch_sensor sensor_b']['filament_detected'] = detected
        script = t['_LOCK_CHECK'].render(printer=printer, params={}, retry=retry, action_respond_info=lambda msg: '')
        strokes = [line.strip() for line in script.splitlines() if line.strip().startswith('_WMP_COUPLING_STROKE')]
        if strokes:
            assert strokes == ['_WMP_COUPLING_STROKE LOCK=1 RETRY=%d SESSION=session GENERATION=0' % retry]
            attempts.append(retry)
        assert '_WMP_ABORT_TOOLCHANGE' not in script
    assert attempts == expected


def test_missing_optional_auxiliary_fan_command_is_reported_and_skipped():
    model = HeaterModel(ROOT / 'config/live')
    model.p.pop('fan_generic auxiliary_fan', None)
    script = model.templates['M106'].render(printer=model.p, params={'P':'2','S':'128'})
    assert 'SET_FAN_SPEED' not in script
    assert 'M118 Auxiliary cooling fan is not installed, fan command skipped.' in script


def test_pause_without_optional_auxiliary_still_stops_all_heaters():
    model = HeaterModel(ROOT / 'config/live')
    model.p.pop('fan_generic auxiliary_fan', None)
    script = model.templates['PAUSE'].render(printer=model.p, params={})
    assert 'MACRO=RESUME VARIABLE=afan VALUE=0' in script
    model.run('PAUSE')
    assert all(model.p[name]['target'] == 0 for name in ('extruder','extruder1','extruder2','extruder3'))


def test_pre_unlock_dock_support_recheck_precedes_stock_unlock_and_retreat():
    macro=templates(ROOT/'config/live')['_CHECK_AND_UNLOCK']
    p={'save_variables':{'variables':{'is_nozzle_setting':0}},
       'filament_switch_sensor docked2':{'filament_detected':False},
       'wm_material':{'session_id':'session','command_generation':3}}
    script=macro.render(printer=p,params={'T':'2'},action_respond_info=lambda *args:'')
    assert script.index('_WMP_CHECK_DOCK_SUPPORT HEAD=2')<script.index('\n        UNLOCK')<script.index('G0 Y310')<script.index('UNLOCK_TOOL_FINISH')
    assert 'SAVE_VARIABLE VARIABLE=fail_flag' not in script
    p['openace']={}
    script=macro.render(printer=p,params={'T':'2'},action_respond_info=lambda *args:'')
    assert '_WMP_CHECK_DOCK_SUPPORT' not in script and '_WMP_ABORT_DOCKING REASON=dock_sensor' in script


@pytest.mark.parametrize('job', ['standby', 'paused'])
@pytest.mark.parametrize('operation', ['unknown', 'failed', 'pending', 'running'])
@pytest.mark.parametrize('distance', [-20, 20])
def test_manual_step_repairs_historical_filament_result_but_not_live_operation(job, operation, distance):
    template = templates(ROOT / 'config/live')['WMP_EXTRUDER_STEP']
    printer = {'toolhead': {'extruder': 'extruder2'},
               'extruder2': {'can_extrude': True},
               'gcode_move': {'extrude_factor': 1.0, 'speed_factor': 1.0},
               'print_stats': {'state': job},
               'wm_material': {'attachment': {'state': 'attached', 'head': 'h2'},
                               'filament_operation': {'state': operation}}}
    def error(message):
        raise RuntimeError(message)
    def render():
        return template.render(printer=printer, params={'HEAD': '2', 'MM': str(distance)}, action_raise_error=error)
    if operation in ('pending', 'running'):
        with pytest.raises(RuntimeError, match='Finish the filament operation'):
            render()
        return
    commands = [line.strip() for line in render().splitlines() if line.strip()]
    assert commands == ['SAVE_GCODE_STATE NAME=WMP_MANUAL_STEP', 'M83',
                        f'G1 E{float(distance)} F300.0', 'M400',
                        'RESTORE_GCODE_STATE NAME=WMP_MANUAL_STEP MOVE=0']
    for attachment in ({'state': 'unknown'}, {'state': 'empty'}, {'state': 'attached', 'head': 'h3'}):
        printer['wm_material']['attachment'] = attachment
        with pytest.raises(RuntimeError, match='attachment is not confirmed'):
            render()
    printer['wm_material']['attachment'] = {'state': 'attached', 'head': 'h2'}
    printer['extruder2']['can_extrude'] = False
    with pytest.raises(RuntimeError, match='Heat the selected nozzle'):
        render()
    printer['extruder2']['can_extrude'] = True
    if job == 'paused':
        printer['toolhead']['extruder'] = 'extruder3'
        with pytest.raises(RuntimeError, match='Active extruder differs'):
            render()
        printer['toolhead']['extruder'] = 'extruder2'
    if operation == 'unknown':
        printer['AFC'] = {}
        with pytest.raises(RuntimeError, match='Finish the filament operation'):
            render()


@pytest.mark.parametrize('owner', ['standalone', 'openace', 'AFC'])
def test_pickup_observation_precedes_approach_without_changing_other_owners(owner):
    printer = {'save_variables': {'variables': {'fail_flag': 0, 'current_extruder': 99,
        **{'t%d_position' % i: [50. + i * 60, 335.] for i in range(4)}}},
        'toolhead': {'homed_axes': 'xyz'}, 'gcode_move': {'position': {'y': 270.}},
        'wm_material': {'session_id': 'session', 'command_generation': 4}}
    if owner != 'standalone': printer[owner] = {}
    script = templates(ROOT / 'config/live')['_LOCK_TOOL'].render(printer=printer, params={'T': '2'})
    commands = [line.strip() for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    observation = '_WMP_PICKUP_BEGIN HEAD=2 SESSION=session GENERATION=4 DEFER=0'
    if owner == 'standalone':
        index = commands.index(observation)
        assert commands[index - 1] == 'M400'
        assert index < next(i for i, line in enumerate(commands) if line.startswith(('G0 X', '_WMP_XY_TRAVEL X=')))
        assert commands[index + 1] == '_WMP_COUPLING_BEGIN KIND=pickup HEAD=2 SESSION=session GENERATION=4'
        assert commands[-2:] == ['_CHECK_T_SEQUENCE T=2',
            '_WMP_COUPLING_END KIND=pickup HEAD=2 SESSION=session GENERATION=4']
    else:
        assert observation not in commands
        assert not any(line.startswith('_WMP_COUPLING_') for line in commands)
        assert commands[-1] == '_CHECK_T_SEQUENCE T=2'


def test_normal_toolchange_rechecks_pickup_after_nested_wipe_before_model_return():
    printer = {'save_variables': {'variables': {'fail_flag': 0, 'current_extruder': 2}},
               'wm_material': {'session_id': 'session', 'command_generation': 4}}
    script = templates(ROOT / 'config/live')['_CHANGE_TOOL'].render(
        printer=printer, params={'T': '3'})
    checked = '_CHECK_CHANGE_TOOL T=3'
    final = '_WMP_CHECK_PICKUP_RELEASE HEAD=3 FINAL=1 SESSION=session GENERATION=4'
    assert script.index(checked) < script.index(final) < script.index('_WMP_TOOL_RETURN_FINISH')
    printer['openace'] = {}
    other = templates(ROOT / 'config/live')['_CHANGE_TOOL'].render(printer=printer, params={'T': '3'})
    assert final not in other


@pytest.mark.parametrize("homed,physical_z,gcode_z,target", [
    ("xyz", 20., 19.7, 169.7), ("z", 275., 280., 305.),
    ("xyz", 300., 300., None), ("xy", 20., 20., None),
])
def test_cancel_bed_lowering_is_z_only_and_preserves_gcode_state(homed, physical_z, gcode_z, target):
    m = HeaterModel(ROOT / 'config/live')
    m.p['gcode_macro PRINT_END'] = {'bed_drop': 150.}
    m.p['configfile']['settings']['stepper_z'] = {'position_endstop': 300}
    m.p['toolhead'].update(homed_axes=homed, position={'z': physical_z})
    m.p['gcode_move']['gcode_position'] = {'z': gcode_z}
    script = m.templates['_WMP_PRINT_LOWER_BED'].render(printer=m.p, params={})
    moves = [line.strip() for line in script.splitlines() if line.strip().startswith('G1 ')]
    assert moves == ([] if target is None else [f'G1 Z{target} F3000'])
    assert 'WIPE_NOZZLE' not in script and 'G28' not in script
    if 'z' in homed:
        assert 'RESTORE_GCODE_STATE NAME=wmp_print_lower_bed MOVE=0' in script

def test_default_finish_bed_drop_is_150_mm():
    source = (ROOT / 'config/live/macros.cfg').read_text()
    assert 'variable_bed_drop: 150.0' in source


@pytest.mark.parametrize('chamber,hold', [('0',None),('45',None),('45','90'),('45','0')])
def test_chamber_preparation_uses_slicer_target_before_mesh(chamber,hold):
    model=HeaterModel(ROOT/'config/live')
    model.p['wm_material']={}
    model.p['configfile']['settings']['printer']={'max_velocity':600,'max_accel':10000}
    params={'BED':'100','EXTRUDER':'250','INITIAL_TOOL':'2','CHAMBER':chamber}
    if hold is not None:params['CHAMBER_HOLD']=hold
    script=model.templates['START_PRINT'].render(printer=model.p,params=params,
        adaptive_mesh_enable=True,action_respond_info=lambda *args:'')
    assert '_WMP_PRINT_PREPARE_BEGIN CHAMBER='+str(float(chamber)) in script
    assert 'M141 S'+str(float(chamber)) in script
    if float(chamber)>0:
        command='_WMP_WAIT_CHAMBER TARGET=45.0 BED=100 HOLD='+str(float(hold or 60))
        assert command in script
        assert script.index('M190 S100')<script.index(command)<script.index('BED_MESH_CALIBRATE PROFILE=wmp_print')
    else:assert '_WMP_WAIT_CHAMBER' not in script
    assert script.index('VARIABLE=print_body_ready VALUE=True')<script.index('_WMP_PRINT_STAGE PHASE=printing')


def test_chamber_preparation_does_not_change_other_filament_owners():
    model=HeaterModel(ROOT/'config/live')
    model.p['wm_material']={};model.p['AFC']={}
    model.p['configfile']['settings']['printer']={'max_velocity':600,'max_accel':10000}
    script=model.templates['START_PRINT'].render(printer=model.p,
        params={'BED':'60','EXTRUDER':'220','INITIAL_TOOL':'2','CHAMBER':'45'},
        adaptive_mesh_enable=True,action_respond_info=lambda *args:'')
    assert '_WMP_WAIT_CHAMBER' not in script and '_WMP_PRINT_PREPARE_BEGIN' not in script


@pytest.mark.parametrize('entry', ['_UNLOCK_TOOL', '_LOCK_TOOL'])
@pytest.mark.parametrize('service', [False, True])
def test_shared_dock_mount_service_preserves_bed_height(entry, service):
    printer = {'save_variables': {'variables': {'fail_flag': 0, 'current_extruder': 2,
        **{'t%d_position' % i: [50 + i * 60, 335] for i in range(4)}}},
        'toolhead': {'homed_axes': 'xyz'}, 'gcode_move': {'position': {'y': 80}},
        'wm_material': {'session_id': 'session', 'command_generation': 4}}
    script = templates(ROOT / 'config/live')[entry].render(
        printer=printer, params={'T': '2', 'SERVICE': str(int(service))})
    reset = next(line.strip() for line in script.splitlines() if 'SET_GCODE_OFFSET' in line)
    assert reset.endswith('MOVE=%d' % (not service))
    assert not any(line.strip().startswith(('G0 Z', 'G1 Z', 'G28 Z')) for line in script.splitlines())
    if entry == '_LOCK_TOOL':
        assert script.index('G0 Y310 F9600') < script.index('_CHECK_T_SEQUENCE T=2')
        assert '_WMP_XY_TRAVEL X=170 Y=310' in script
        assert 'G0 Y335.4 F9600' in script  # Controlled dock entry retained.
        assert '_WMP_XY_TRAVEL Y=270' in script
    else:
        assert '_WMP_XY_TRAVEL X=170 Y=270' in script and '_WMP_XY_TRAVEL Y=310' in script
        assert 'G0 Y320 F8000' in script and 'G0 Y335 F1000' in script


@pytest.mark.parametrize('owner', ['standalone', 'openace', 'AFC'])
@pytest.mark.parametrize('recovery', [False, True])
def test_shared_mount_plr_keeps_one_actuator_attempt(owner, recovery):
    printer = {'save_variables': {'variables': {'is_nozzle_setting': 0}},
        'filament_switch_sensor docked2': {'filament_detected': True},
        'wm_material': {'session_id': 'session', 'command_generation': 4}}
    if owner != 'standalone': printer[owner] = {}
    script = templates(ROOT / 'config/live')['_CHECK_AND_LOCK'].render(
        printer=printer, params={'T': '2', 'RECOVERY': str(int(recovery))})
    commands = [line.strip() for line in script.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    single = owner == 'standalone' and recovery
    assert ('LOCK' in commands) is not single
    assert sum(line.startswith('_WMP_COUPLING_STROKE ') for line in commands) == int(single)
    assert commands[-1] == '_LOCK_TOOL_FINISH T=2'


@pytest.mark.parametrize('params,expected', [({'Y':''},1),({'X':'','Y':''},1),({},1),({'X':''},0),({'Z':''},0)])
def test_y_homing_routes_through_fixed_corner_helper(params,expected):
    text=(ROOT/'config/live/printer.cfg').read_text()
    block=text.split('[homing_override]',1)[1].split('[gcode_macro ',1)[0].split('gcode:',1)[1]
    env=jinja2.Environment('{%','%}','{','}',undefined=jinja2.StrictUndefined)
    p={'save_variables':{'variables':{'fail_flag':0,'current_extruder':3}},
       'gcode_macro Z_HOMING':{'z_raise':1},'toolhead':{'homed_axes':'xyz'},'extruder':{'target':0}}
    rendered=env.from_string(block).render(printer=p,params=params)
    commands=[line.strip() for line in rendered.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    assert commands.count('_WMP_HOME_XY')==expected
    assert 'G28 Y' not in commands and 'G28  Y' not in commands


@pytest.mark.parametrize('state', ['printing', 'paused', 'standby'])
@pytest.mark.parametrize('raise_z', [0, 1])
def test_homing_center_travel_preserves_cleaning_and_z_sequence(state, raise_z):
    script = templates(ROOT / 'config/live')['Z_HOMING'].render(
        printer={'print_stats': {'state': state},
                 'save_variables': {'variables': {'probe_tool': 2}}}, z_raise=raise_z)
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    center = '_WMP_XY_TRAVEL X=150 Y=135'
    assert commands.index('_CHANGE_TOOL T=2') < commands.index(center)
    assert ('WIPE_NOZZLE' in commands) is (state in ('printing', 'paused'))
    if 'WIPE_NOZZLE' in commands:
        assert commands.index('WIPE_NOZZLE') < commands.index(center)
    assert commands.index(center) < commands.index('_LEVELING_TRIGGER_S') < commands.index('M400') < commands.index('G28 Z')
    assert ('G1 Z7 F9600' in commands) is bool(raise_z)
    assert commands.index('G28 Z') < commands.index('STEPPER_DIAG_DISABLE CHIP="stepper_z"')
