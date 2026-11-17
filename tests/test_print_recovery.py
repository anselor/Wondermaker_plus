"""Execute startup/recovery templates across a simulated persistent restart.

Hardware homing, heater waits and bed probing are stubbed. Actual Jinja
expansion, saved-variable quoting, profile routing and reference selection run.
"""
import ast
import copy
import re
import shlex
from pathlib import Path

import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1]


class Stopped(Exception):
    pass


class RecoveryModel:
    def __init__(self):
        env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
        self.templates, self.defaults = {}, {}
        self.probe_prepare_check = lambda: None
        for name in ('macros.cfg', 'printer.cfg', 'change_macros.cfg'):
            for section in re.split(r'(?m)^\[', (ROOT / 'config/live' / name).read_text())[1:]:
                heading, body = section.split(']', 1)
                if not heading.startswith(('gcode_macro ', 'delayed_gcode ', 'homing_override')):
                    continue
                key = heading.split(' ', 1)[-1].upper()
                code = re.search(r'(?m)^gcode:\s*\n([\s\S]*)', body)
                if not code:
                    continue
                script = '\n'.join(line.split('#', 1)[0] for line in code[1].splitlines())
                self.templates[key] = env.from_string(script)
                self.defaults[key] = {k: ast.literal_eval(v.split('#')[0].strip()) for k, v in
                                     re.findall(r'(?m)^variable_(\w+):\s*([^\n]+)', body)}
        self.p = {
            'save_variables': {'variables': {
                'current_extruder': 0, 'probe_tool': 0, 'fail_flag': 0,
                **{f'box_modify_t{i}': t for i, t in enumerate([2, 1, 0, 3])},
                **{f't{i}_offset': [i * .1, i * .2, i * -.03] for i in range(4)}}},
            'print_stats': {'state': 'printing', 'filename': 'models/Two "tools" and Bob\'s 50% #1;ä*.gcode'},
            'configfile': {'settings': {'printer': {'max_velocity': 600, 'max_accel': 10000},
                                        'stepper_z': {'position_endstop': 300}}},
            'wmp_recovery': {'z_reference_valid': False},
            'gcode_move': {'speed_factor': 1.0},
            'toolhead': {'homed_axes': '', 'position': {'z': 20}},
            'extruder': {'target': 0},
            'query_endstops': {'last_query': {'z': 0}},
            'bed_mesh': {'profiles': {'default': {'points': [[0, .1], [.2, .3]]}}, 'profile_name': ''},
        }
        self.p['custom_hall'] = {'Raw': 4000}
        self.p['filament_switch_sensor sensor_b'] = {'filament_detected': True}
        for i in range(4):
            self.p['filament_switch_sensor docked%d' % i] = {'filament_detected': i != 0}
        self.events, self.in_home, self.shutdown = [], False, False
        self.mesh = None
        self.disk_profiles = copy.deepcopy(self.p['bed_mesh']['profiles'])
        self.reset_macros()

    @property
    def sv(self):
        return self.p['save_variables']['variables']

    def reset_macros(self):
        for name, defaults in self.defaults.items():
            self.p['gcode_macro ' + name] = copy.deepcopy(defaults)

    def stop(self, message):
        self.shutdown = True
        raise Stopped(message)

    def run(self, name, **params):
        name = name.upper()
        if self.shutdown:
            raise Stopped('printer is shut down')
        script = self.templates[name].render(
            printer=copy.deepcopy(self.p), params={k: str(v) for k, v in params.items()},
            rawparams=' '.join(f'{k}={shlex.quote(str(v))}' for k, v in params.items()),
            action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)),
            action_emergency_stop=self.stop, action_respond_info=lambda *a: '',
            **self.p['gcode_macro ' + name])
        for line in script.splitlines():
            words = shlex.split(line)
            if not words:
                continue
            command = words[0].upper()
            args = {k.upper(): v for k, v in (w.split('=', 1) for w in words[1:] if '=' in w)}
            self.events.append((command, args))
            if command == 'SAVE_VARIABLE':
                self.sv[args['VARIABLE']] = ast.literal_eval(args['VALUE'])
            elif command == 'SET_GCODE_VARIABLE':
                self.p.setdefault('gcode_macro ' + args['MACRO'].upper(), {})[args['VARIABLE']] = ast.literal_eval(args['VALUE'])
            elif command == 'BED_MESH_CALIBRATE':
                self.mesh = {'points': [[self.sv['probe_tool'], .5], [.6, .7]]}
                profile = None if args.get('ADAPTIVE') == '1' else args.get('PROFILE', 'default')
                self.p['bed_mesh']['profile_name'] = profile or ''
                if profile:
                    self.p['bed_mesh']['profiles'][profile] = copy.deepcopy(self.mesh)
            elif command == 'BED_MESH_PROFILE_BASE':
                profiles = self.p['bed_mesh']['profiles']
                if 'SAVE' in args:
                    profiles[args['SAVE']] = copy.deepcopy(self.mesh)
                elif 'LOAD' in args:
                    self.mesh = copy.deepcopy(profiles[args['LOAD']])
                    self.p['bed_mesh']['profile_name'] = args['LOAD']
            elif command == 'BED_MESH_CLEAR':
                self.mesh = None
                self.p['bed_mesh']['profile_name'] = ''
            elif command in ('SAVE_CONFIG_NO_RESTART', '_WMP_SAVE_PRINT_MESH'):
                self.disk_profiles = copy.deepcopy(self.p['bed_mesh']['profiles'])
            elif command == 'G28':
                if self.in_home:
                    self.events.append(('NATIVE_HOME', {'axes': words[1:], 'probe': self.sv['probe_tool']}))
                    axes = words[1:] or ['X', 'Y', 'Z']
                    self.p['toolhead']['homed_axes'] = ''.join(sorted(set(self.p['toolhead']['homed_axes']) | {a.lower() for a in axes}))
                    if 'Z' in axes:
                        self.p['toolhead']['position']['z'] = 300
                        self.p['wmp_recovery']['z_reference_valid'] = True
                else:
                    self.in_home = True
                    try:
                        parts = re.split('([A-Z_]+|[A-Z*/])', line.upper())
                        self.run('HOMING_OVERRIDE', **{parts[i]: parts[i+1].strip() for i in range(3, len(parts), 2)})
                    finally:
                        self.in_home = False
            elif command == '_WMP_HOME_XY':
                # Physical helper is exercised in test_xy_homing; this macro
                # interpreter records its native XY-only homing contract.
                for axis in ('Y', 'X', 'Y'):
                    self.events.append(('NATIVE_HOME', {'axes':[axis], 'probe':self.sv['probe_tool']}))
                self.p['toolhead']['homed_axes'] = ''.join(sorted(set(self.p['toolhead']['homed_axes']) | {'x','y'}))
            elif command == '_WMP_HOME_Z_BOTTOM':
                self.events.append(('BOTTOM_HOME', {}))
                self.p['toolhead']['homed_axes'] = ''.join(sorted(set(self.p['toolhead']['homed_axes']) | {'z'}))
                self.p['toolhead']['position']['z'] = 300
                self.p['wmp_recovery']['z_reference_valid'] = True
                self.mesh = None
                self.p['bed_mesh']['profile_name'] = ''
            elif command == '_CHANGE_TOOL' or re.fullmatch(r'T[0-3]', command):
                tool = int(args['T']) if command == '_CHANGE_TOOL' else self.sv['box_modify_t' + command[1:]]
                self.sv['current_extruder'] = tool
                for i in range(4): self.p['filament_switch_sensor docked%d' % i]['filament_detected'] = i != tool
                self.events.append(('PHYSICAL_TOOL', {'tool': tool, 'reference': self.sv['probe_tool']}))
            elif command in ('_WMP_RECOVERY_JOB_BEGIN', '_WMP_RECOVERY_JOB_COMMIT', '_WMP_RECOVERY_JOB_CLEAR'):
                self.material_handlers[command]()
            elif command == '_WMP_PROBE_PREPARE_CHECK':
                self.probe_prepare_check()
            elif command in ('_WMP_CASE_LIGHT_PRINT_START', '_WMP_CASE_LIGHT_PRINT_END',
                             '_WMP_PRINT_PREPARE_BEGIN', '_WMP_PRINT_STAGE', '_WMP_WAIT_CHAMBER'):
                # Python light/timer endpoints are covered in test_case_light;
                # they do not change this model's motion or recovery state.
                pass
            elif command in ('Z_HOMING', 'Z_RISE', '_RAISE_Z', '_DESCEND_Z', '_OFFSET_SET', 'BED_MESH_PROFILE', 'M24') or command.startswith('_WMP_'):
                self.run(command, **args)
            # Other commands perform hardware work outside this model.

    def start(self, **params):
        self.run('START_PRINT', **{'BED': '60', 'EXTRUDER': '220', 'INITIAL_TOOL': '0', **params})

    def restart(self):
        self.reset_macros()
        self.p['print_stats'] = {'state': 'standby', 'filename': ''}
        self.p['toolhead']['homed_axes'] = ''
        self.p['wmp_recovery']['z_reference_valid'] = False
        self.p['bed_mesh'] = {'profiles': copy.deepcopy(self.disk_profiles), 'profile_name': ''}
        self.mesh = None
        self.run('_PROBE_TOOL_STARTUP_RESET')
        self.events.clear()

    def recovery_home(self):
        self.p['gcode_macro Z_HOMING']['z_raise'] = 0
        self.in_home = True
        try:
            self.run('HOMING_OVERRIDE')
        finally:
            self.in_home = False


@pytest.mark.parametrize('preference,fresh,tool', [(None, True, 2), (False, True, 0), (True, True, 2), (None, False, 0)])
def test_first_tool_default_and_opt_out(preference, fresh, tool):
    m = RecoveryModel()
    if preference is not None:
        m.sv['probe_with_initial_tool'] = preference
    m.p['gcode_macro START_PRINT']['adaptive_mesh_enable'] = fresh
    m.start()
    assert m.sv['wmp_print_context']['tool'] == tool
    assert m.sv['box_modify_t0'] == 2


@pytest.mark.parametrize('mode', ['bounds', 'adaptive', 'full', 'saved'])
def test_each_start_keeps_default_and_persists_exact_mesh(mode):
    m = RecoveryModel()
    default = copy.deepcopy(m.disk_profiles['default'])
    params = {}
    if mode == 'bounds':
        params = dict(MESH_MIN_X=10, MESH_MIN_Y=20, MESH_MAX_X=90, MESH_MAX_Y=100, PROBE_COUNT_X=4, PROBE_COUNT_Y=4)
    if mode == 'adaptive':
        params = {'ADAPTIVE': 1}
    if mode == 'saved':
        m.p['gcode_macro START_PRINT']['adaptive_mesh_enable'] = False
    m.start(**params)
    assert m.disk_profiles['default'] == default
    assert m.disk_profiles['wmp_print'] == m.mesh
    assert m.p['bed_mesh']['profile_name'] == 'wmp_print'
    saved = copy.deepcopy(m.mesh)
    # Even changing default later cannot change this print's recovery copy.
    m.disk_profiles['default']['points'][0][0] = 99
    filename = m.p['print_stats']['filename']
    m.restart()
    assert m.sv['probe_tool'] == 0
    m.recovery_home()
    assert m.mesh == saved
    assert m.sv['probe_tool'] == (0 if mode == 'saved' else 2)
    assert any(c == 'BOTTOM_HOME' for c, a in m.events)
    assert not any(c == 'PHYSICAL_TOOL' for c, a in m.events)
    assert not any(c == 'NATIVE_HOME' and a['axes'] == ['Z'] for c, a in m.events)
    # Vendor selects one of its legacy names after positioning the tool.
    m.run('BED_MESH_PROFILE', LOAD='default' if mode == 'saved' else 'adaptive_mesh')
    assert m.mesh == saved
    m.p['print_stats']['filename'] = filename
    m.run('M24')
    assert m.events[-1][0] == 'M9924'
    assert not m.p['gcode_macro _WMP_RECOVERY_BEGIN']['active']


@pytest.mark.parametrize('fault', ['missing_context', 'missing_mesh', 'offsets', 'invalid_tool', 'old_context', 'missing_mapping', 'bad_mapping'])
def test_invalid_recovery_stops_before_homing_and_blocks_later_commands(fault):
    m = RecoveryModel()
    m.start()
    m.restart()
    if fault == 'missing_context': m.sv.pop('wmp_print_context')
    if fault == 'missing_mesh': m.p['bed_mesh']['profiles'].pop('wmp_print')
    if fault == 'offsets': m.sv['t2_offset'][2] += .2
    if fault == 'invalid_tool': m.sv['wmp_print_context']['tool'] = 99
    if fault == 'old_context': m.sv['wmp_print_context']['version'] = 1
    if fault == 'missing_mapping': m.sv['wmp_print_context'].pop('mapping')
    if fault == 'bad_mapping': m.sv['wmp_print_context']['mapping'] = [0, 99, 2, 3]
    with pytest.raises(Stopped):
        m.recovery_home()
    assert not any(c in ('NATIVE_HOME', 'PHYSICAL_TOOL') for c, _ in m.events)
    with pytest.raises(Stopped):
        m.run('M24')


def test_wrong_recovery_file_cannot_resume():
    m = RecoveryModel()
    m.start()
    m.restart()
    m.recovery_home()
    m.p['print_stats']['filename'] = 'another.gcode'
    with pytest.raises(Stopped):
        m.run('M24')
    assert not any(c == 'M9924' for c, _ in m.events)


def test_normal_m24_and_default_load_do_not_enter_recovery():
    m = RecoveryModel()
    m.run('M24')
    assert m.events[-1][0] == 'M9924'
    m.run('BED_MESH_PROFILE', LOAD='default')
    m.sv['probe_tool'] = 2
    with pytest.raises(ValueError, match='T0 probing reference'):
        m.run('BED_MESH_PROFILE', LOAD='default')


@pytest.mark.parametrize('mapping', [[0, 2, 2, 3], [2, 1, 0, 3]])
def test_recovery_restores_mapping_after_vendor_identity_writes_before_next_sliced_tool(mapping):
    m = RecoveryModel()
    m.sv.update({f'box_modify_t{i}': t for i, t in enumerate(mapping)})
    m.start()
    filename = m.p['print_stats']['filename']
    assert m.sv['wmp_print_context']['mapping'] == mapping
    m.restart()
    # Real client overwrites live mappings at boot/recovery, and again after
    # recovery G28. Merely persisting save_variables or restoring at G28 fails.
    def vendor_identity():
        m.sv.update({f'box_modify_t{i}': i for i in range(4)})
        m.sv.update({f'box_modify_t{i}_backup': i for i in range(4)})
    vendor_identity()
    m.recovery_home()
    vendor_identity()
    m.p['print_stats']['filename'] = filename
    m.run('M24')
    assert [m.sv[f'box_modify_t{i}'] for i in range(4)] == mapping
    resume_index = next(i for i, (c, _) in enumerate(m.events) if c == 'M9924')
    for i, physical in enumerate(mapping):
        assert ('SAVE_VARIABLE', {'VARIABLE': f'box_modify_t{i}', 'VALUE': str(physical)}) in m.events[:resume_index]
    # The client also writes stale pause backups after M24. Those must not
    # affect subsequent sliced T1 dispatch or the independent recovery record.
    m.sv.update({f'box_modify_t{i}_backup': i for i in range(4)})
    m.templates['SLICED_NEXT_TOOL'] = jinja2.Template('T1')
    m.p['gcode_macro SLICED_NEXT_TOOL'] = {}
    m.run('SLICED_NEXT_TOOL')
    assert m.sv['current_extruder'] == mapping[1]
    assert m.sv['wmp_print_context']['mapping'] == mapping


def test_intentional_mapping_change_on_normal_resume_survives_next_power_cut():
    m = RecoveryModel()
    m.start()
    filename = m.p['print_stats']['filename']
    m.sv['box_modify_t1'] = 3  # mapping restored by ordinary RESUME after user remap
    m.run('M24')
    assert m.sv['wmp_print_context']['mapping'] == [2, 3, 0, 3]
    m.restart()
    m.recovery_home()
    m.sv.update({f'box_modify_t{i}': i for i in range(4)})
    m.p['print_stats']['filename'] = filename
    m.run('M24')
    assert m.sv['box_modify_t1'] == 3


def test_mapping_corruption_after_recovery_home_stops_before_sd_resume():
    m = RecoveryModel()
    m.start()
    filename = m.p['print_stats']['filename']
    m.restart()
    m.recovery_home()
    m.p['print_stats']['filename'] = filename
    m.sv['wmp_print_context']['mapping'] = [0, 1]
    with pytest.raises(Stopped):
        m.run('M24')
    assert not any(c == 'M9924' for c, _ in m.events)


def test_context_is_invalidated_before_new_start_and_explicit_clear():
    m = RecoveryModel()
    m.start()
    m.events.clear()
    m.start(INITIAL_TOOL='3')
    writes = [ast.literal_eval(a['VALUE']) for c, a in m.events if c == 'SAVE_VARIABLE' and a['VARIABLE'] == 'wmp_print_context']
    assert writes[0] == {} and writes[-1]['tool'] == 3
    m.run('_WMP_PRINT_CONTEXT_CLEAR')
    assert m.sv['wmp_print_context'] == {}


def test_default_calibration_rejects_nonzero_reference_before_moving():
    m = RecoveryModel()
    m.sv['probe_tool'] = 2
    with pytest.raises(ValueError, match='T0 reference'):
        m.run('BED_MESH_CALIBRATE')
    assert not m.events


def test_context_survives_actual_vendor_save_variables_roundtrip(tmp_path):
    import importlib.util
    path = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/klipper/klippy/extras/save_variables.py'
    if not path.exists():
        pytest.skip('local vendor source unavailable')
    spec = importlib.util.spec_from_file_location('vendor_save_variables', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    m = RecoveryModel()
    m.start()
    saved = vendor.SaveVariables.__new__(vendor.SaveVariables)
    saved.filename, saved.allVariables = str(tmp_path / 'saved_variables.cfg'), {}
    class Gcmd:
        def get(self, key):
            return {'VARIABLE': 'wmp_print_context', 'VALUE': repr(m.sv['wmp_print_context'])}[key]
        def error(self, message):
            return ValueError(message)
    saved.cmd_SAVE_VARIABLE(Gcmd())
    saved.allVariables = {}
    saved.loadVariables()
    context = saved.allVariables['wmp_print_context']
    assert context == m.sv['wmp_print_context']
    assert bytes.fromhex(context['file_hex']).decode() == m.p['print_stats']['filename']


def test_recovery_command_renames_match_vendor_command_types():
    path = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/klipper/klippy/gcode.py'
    if not path.exists():
        pytest.skip('local vendor source unavailable')
    tree = ast.parse(path.read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'is_traditional_gcode')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    source = (ROOT / 'config/live/macros.cfg').read_text()
    for name in ('M24', 'BED_MESH_PROFILE'):
        rename = re.search(r'\[gcode_macro ' + name + r'\]\nrename_existing: (\w+)', source)[1]
        assert namespace['is_traditional_gcode'](None, name) == namespace['is_traditional_gcode'](None, rename)


@pytest.mark.parametrize('fake_homed', [False, True])
def test_recovery_fallback_bottom_home_precedes_xy_and_skips_vendor_z(fake_homed):
    m = RecoveryModel(); m.start(); m.restart()
    if fake_homed:
        m.p['toolhead']['homed_axes'] = 'z'  # SET_KINEMATIC_POSITION without endstop
    m.recovery_home()
    names = [c for c, _ in m.events]
    assert names.index('BOTTOM_HOME') < names.index('NATIVE_HOME')
    assert not any(c in ('Z_HOMING', '_LEVELING_TRIGGER_S', 'PHYSICAL_TOOL', 'Z_RISE') for c in names)
    assert m.p['gcode_macro Z_HOMING']['z_raise'] == 1


def test_early_pickup_reference_is_reused_and_invalid_context_still_shuts_down():
    m = RecoveryModel(); m.start(); m.restart()
    m.p['toolhead']['homed_axes'] = 'xyz'
    m.p['toolhead']['position']['z'] = 300
    m.p['wmp_recovery']['z_reference_valid'] = True
    m.recovery_home()
    assert not any(c in ('BOTTOM_HOME', 'NATIVE_HOME', 'Z_HOMING', 'PHYSICAL_TOOL') for c, _ in m.events)
    m.sv['wmp_print_context'] = {}
    with pytest.raises(Stopped): m.recovery_home()
    assert m.shutdown and m.p['toolhead']['homed_axes'] == 'xyz'


@pytest.mark.parametrize('same_tool,fake_homed', [(False, False), (True, False), (True, True)])
def test_tool_guard_homes_bottom_before_xy_even_for_mounted_tool(same_tool, fake_homed):
    m = RecoveryModel(); m.p['print_stats']['state'] = 'standby'
    m.p['gcode_macro _descend_z'] = m.p['gcode_macro _DESCEND_Z']
    if fake_homed: m.p['toolhead']['homed_axes'] = 'z'
    m.run('_CHANGING_TOOL', T=0 if same_tool else 1)
    names = [c for c, _ in m.events]
    assert names.index('BOTTOM_HOME') < names.index('NATIVE_HOME')
    assert names.count('BOTTOM_HOME') == 1
    assert not any(c == 'SET_KINEMATIC_POSITION' for c in names)


def test_manual_xy_home_leaves_unknown_z_untouched():
    m = RecoveryModel(); m.p['print_stats']['state'] = 'standby'
    m.in_home = True
    m.run('HOMING_OVERRIDE', X='', Y='')
    names = [c for c, _ in m.events]
    assert 'BOTTOM_HOME' not in names
    assert 'SET_KINEMATIC_POSITION' not in names
    assert not m.p['wmp_recovery']['z_reference_valid']
    assert m.p['toolhead']['homed_axes'] == 'xy'
    assert m.p['toolhead']['position']['z'] == 20


def test_real_commit_preserves_native_tuple_offsets_through_recovery():
    # Saved-variable tuples become lists over Moonraker JSON. Build the record
    # with the real commit template, as START_PRINT does, preserving its types.
    m = RecoveryModel()
    for i in range(4): m.sv[f't{i}_offset'] = tuple(m.sv[f't{i}_offset'])
    m.start()
    context = ast.literal_eval(repr(m.sv['wmp_print_context']))
    assert all(isinstance(row, tuple) for row in context['offsets'])
    m.sv['wmp_print_context'] = context
    filename = m.p['print_stats']['filename']
    m.restart(); m.recovery_home()
    m.p['print_stats']['filename'] = filename
    m.run('M24')
    assert m.events[-1][0] == 'M9924'


@pytest.mark.parametrize('mounted', range(4))
def test_normal_full_home_keeps_sensor_confirmed_head_and_sets_datum(mounted):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.sv['current_extruder'] = 0  # Stale selection cannot override sensors.
    m.sv['probe_tool'] = 0
    for i in range(4): m.p['filament_switch_sensor docked%d' % i]['filament_detected'] = i != mounted
    m.run('HOMING_OVERRIDE')
    assert m.sv['current_extruder'] == mounted
    assert m.sv['probe_tool'] == mounted
    changes = [args['tool'] for cmd, args in m.events if cmd == 'PHYSICAL_TOOL']
    assert changes == [mounted]
    # Subsequent tool offsets must be relative to the head that actually homed.
    m.sv['current_extruder'] = (mounted + 1) % 4
    m.run('_OFFSET_SET')
    offsets = [args for cmd, args in m.events if cmd == 'SET_GCODE_OFFSET'][-1]
    reference = m.sv['t%d_offset' % mounted]
    target = m.sv['t%d_offset' % ((mounted + 1) % 4)]
    for axis, index in zip('XYZ', range(3)):
        assert float(offsets[axis]) == pytest.approx(target[index] - reference[index])


def test_idle_start_print_still_uses_explicit_first_tool():
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.start(INITIAL_TOOL='0')  # Mapping T0 -> physical Head 3.
    assert m.sv['probe_tool'] == 2
    assert any(cmd == 'PHYSICAL_TOOL' and args['tool'] == 2 for cmd, args in m.events)


@pytest.mark.parametrize('fault', ['locked_in_dock', 'two_missing', 'hall', 'saved_fault'])
def test_normal_home_refuses_ambiguous_attachment_before_motion(fault):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    if fault == 'locked_in_dock': m.p['filament_switch_sensor docked0']['filament_detected'] = True
    elif fault == 'two_missing': m.p['filament_switch_sensor docked1']['filament_detected'] = False
    elif fault == 'hall': m.p['custom_hall']['Raw'] = 0
    else: m.sv['fail_flag'] = -3
    with pytest.raises(ValueError, match='sensors disagree|failure remains unresolved'): m.run('HOMING_OVERRIDE')
    assert not any(cmd in ('NATIVE_HOME', 'BOTTOM_HOME', 'PHYSICAL_TOOL') for cmd, _ in m.events)


def test_normal_home_empty_carriage_uses_existing_default_reference():
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.p['custom_hall']['Raw'] = 4900
    m.p['filament_switch_sensor sensor_b']['filament_detected'] = False
    for i in range(4): m.p['filament_switch_sensor docked%d' % i]['filament_detected'] = True
    m.run('HOMING_OVERRIDE')
    assert m.sv['probe_tool'] == 0
    assert any(cmd == 'PHYSICAL_TOOL' and args['tool'] == 0 for cmd, args in m.events)


@pytest.mark.parametrize('reference', [False, True])
@pytest.mark.parametrize('paused', [False, True])
def test_explicit_xy_homing_never_invokes_z_or_tool_selection(reference, paused):
    model = RecoveryModel()
    model.p['wmp_recovery']['z_reference_valid'] = reference
    model.p['print_stats']['state'] = 'paused' if paused else 'standby'
    script = model.templates['HOMING_OVERRIDE'].render(
        printer=model.p, params={'X': '', 'Y': ''}, action_raise_error=model.stop)
    lines = [line.strip() for line in script.splitlines() if line.strip()]
    assert '_WMP_HOME_XY' in lines
    assert not any('z_rise' in line or 'Z_HOMING' in line or 'HOME_Z' in line
                   or '_WMP_SELECT_HOME_TOOL' in line or re.search(r'G[0128]+\s+Z', line)
                   for line in lines)


def test_normal_full_homing_keeps_z_preparation():
    model = RecoveryModel()
    model.p['gcode_macro Z_HOMING']['z_raise'] = 1
    script = model.templates['HOMING_OVERRIDE'].render(
        printer=model.p, params={}, action_raise_error=model.stop)
    assert 'z_rise' in script and 'Z_HOMING' in script


@pytest.mark.parametrize('mounted', range(4))
def test_stock_probe_calibration_uses_physical_reference_despite_mapping(mounted):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    # The fixture remaps logical T0 to physical Head 3.
    assert m.sv['box_modify_t0'] == 2
    m.sv['current_extruder'] = mounted
    for i in range(4):
        m.p['filament_switch_sensor docked%d' % i]['filament_detected'] = i != mounted
    m.run('_WMP_PROBE_CALIBRATE')
    assert m.sv['probe_tool'] == 0
    assert m.sv['current_extruder'] == 0
    changes = [args['tool'] for cmd, args in m.events if cmd == 'PHYSICAL_TOOL']
    assert changes and all(head == 0 for head in changes)
    commands = [cmd for cmd, _ in m.events]
    assert 'T0' not in commands
    # The hardware/manual probe command is an opaque endpoint in this model.
    assert commands.index('Z_HOMING') < commands.index('PROBE_CALIBRATE')
    assert m.p['toolhead']['homed_axes'] == 'xyz'


@pytest.mark.parametrize('state,fault', [('printing', 0), ('paused', 0), ('standby', -3), ('standby', 1)])
def test_stock_probe_calibration_rejects_before_preparation(state, fault):
    m = RecoveryModel()
    m.p['print_stats']['state'] = state
    m.sv['fail_flag'] = fault
    with pytest.raises(ValueError, match='idle maintenance|toolhead fault'):
        m.run('_WMP_PROBE_CALIBRATE')
    assert not m.events


def test_stock_probe_calibration_cannot_enter_power_recovery_homing_branch():
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.p['gcode_macro Z_HOMING']['z_raise'] = 0
    with pytest.raises(ValueError, match='Resolve print recovery'):
        m.run('_WMP_PROBE_CALIBRATE')
    assert not m.events


@pytest.mark.parametrize('mounted', range(4))
@pytest.mark.parametrize('axes', ['', 'xy', 'z', 'xyz'])
def test_bed_calibration_establishes_physical_reference_before_heating_and_mesh(mounted, axes):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.p['toolhead']['homed_axes'] = axes
    m.sv['current_extruder'] = mounted
    m.sv['probe_tool'] = mounted
    for i in range(4):
        m.p[f'filament_switch_sensor docked{i}']['filament_detected'] = i != mounted
    m.run('G29')
    assert m.sv['current_extruder'] == m.sv['probe_tool'] == 0
    assert m.p['toolhead']['homed_axes'] == 'xyz'
    assert m.p['wmp_recovery']['z_reference_valid']
    commands = [cmd for cmd, _ in m.events]
    assert commands.index('Z_HOMING') < commands.index('M140') < commands.index('BED_MESH_CALIBRATE')
    assert 'T0' not in commands  # logical T0 is mapped to physical Head 3
    heaters = [args for cmd, args in m.events if cmd == 'SET_HEATER_TEMPERATURE']
    assert heaters == [{'HEATER': 'extruder', 'TARGET': '140'},
                       {'HEATER': 'extruder', 'TARGET': '0'}]
    assert ('TEMPERATURE_WAIT', {'SENSOR': 'extruder', 'MINIMUM': '140', 'MAXIMUM': '143'}) in m.events
    assert m.mesh['points'][0][0] == 0
    assert m.p['gcode_macro G29']['bed_leveling'] is False


@pytest.mark.parametrize('state,fault,recovering', [
    ('printing', 0, False), ('paused', 0, False),
    ('standby', -3, False), ('standby', 1, False),
    ('standby', 0, True),
])
def test_bed_calibration_rejects_unsafe_entry_before_any_side_effect(state, fault, recovering):
    m = RecoveryModel()
    m.p['print_stats']['state'] = state
    m.sv['fail_flag'] = fault
    if recovering:
        m.p['gcode_macro Z_HOMING']['z_raise'] = 0
    before = copy.deepcopy(m.sv)
    with pytest.raises(ValueError, match='idle maintenance|toolhead fault|print recovery'):
        m.run('G29')
    assert not m.events
    assert m.sv == before


@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('identification,mapping', [(False, [2, 1, 0, 3]), (True, [3, 3, 0, 0])])
def test_maintenance_physical_selection_bypasses_logical_mapping(head, identification, mapping):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.sv['is_nozzle_setting'] = int(identification)
    m.sv.update({f'box_modify_t{i}': target for i, target in enumerate(mapping)})
    m.run('_WMP_CALIBRATION_TOOL', T=head)
    assert m.sv['current_extruder'] == head
    assert [args['tool'] for cmd, args in m.events if cmd == 'PHYSICAL_TOOL'] == [head]
    assert not any(cmd in ('T0', 'T1', 'T2', 'T3', 'G28', 'SET_HEATER_TEMPERATURE') for cmd, _ in m.events)


@pytest.mark.parametrize('head', ['', '-1', '4', '0.5', '00', 'bad'])
def test_maintenance_pid_selection_rejects_invalid_head_before_motion(head):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    with pytest.raises(ValueError, match='physical head index'):
        m.run('_WMP_CALIBRATION_TOOL', T=head)
    assert not m.events


@pytest.mark.parametrize('state,fault,recovering', [
    ('printing', 0, False), ('paused', 0, False),
    ('standby', -3, False), ('standby', 1, False), ('standby', 0, True),
])
def test_maintenance_pid_selection_rejects_unsafe_context(state, fault, recovering):
    m = RecoveryModel()
    m.p['print_stats']['state'] = state
    m.sv['fail_flag'] = fault
    if recovering:
        m.p['gcode_macro Z_HOMING']['z_raise'] = 0
    with pytest.raises(ValueError, match='idle maintenance|toolhead fault|print recovery'):
        m.run('_WMP_CALIBRATION_TOOL', T=2)
    assert not m.events


def test_managed_material_hooks_own_context_writes():
    m = RecoveryModel()
    m.p['wm_material'] = {}
    observations = []
    def observe(stage):
        # The standalone backend now owns optional publication. Simulate its
        # effects here; the real backend is covered by test_wm_material.
        if stage == 'begin':
            m.sv['wmp_print_context'] = {}
        elif stage == 'commit':
            m.sv['wmp_print_context'] = {
                'version': 2, 'tool': m.sv['probe_tool'], 'mesh': 'wmp_print',
                'mapping': [m.sv['box_modify_t%d' % i] for i in range(4)],
                'offsets': [copy.deepcopy(m.sv['t%d_offset' % i]) for i in range(4)],
                'file_hex': m.p['print_stats']['filename'].encode().hex()}
        observations.append((stage, copy.deepcopy(m.sv.get('wmp_print_context')),
                             len(m.events)))
    m.material_handlers = {
        '_WMP_RECOVERY_JOB_BEGIN': lambda: observe('begin'),
        '_WMP_RECOVERY_JOB_COMMIT': lambda: observe('commit'),
        '_WMP_RECOVERY_JOB_CLEAR': lambda: observe('clear')}
    m.start()
    assert [stage for stage, context, index in observations] == ['begin', 'commit']
    assert observations[0][1] == {}
    assert observations[1][1] == m.sv['wmp_print_context']
    commands = [command for command, args in m.events]
    assert commands.index('_WMP_RECOVERY_JOB_BEGIN') < commands.index('SET_HEATER_TEMPERATURE')
    assert commands.index('_WMP_RECOVERY_JOB_COMMIT') > max(i for i, command in enumerate(commands) if command == 'G1')
    m.run('_WMP_PRINT_CONTEXT_CLEAR')
    assert observations[-1][0:2] == ('clear', {})


@pytest.mark.parametrize('checkpoint', [1, 2])
def test_probe_preparation_stops_before_next_macro_stage(checkpoint):
    model = RecoveryModel()
    model.p['print_stats']['state'] = 'standby'
    checks = []
    def check():
        checks.append(True)
        if len(checks) == checkpoint:
            raise ValueError('stop requested')
    model.probe_prepare_check = check
    with pytest.raises(ValueError, match='stop requested'):
        model.run('_WMP_PROBE_CALIBRATE')
    commands = [cmd for cmd, _ in model.events]
    assert 'PROBE_CALIBRATE' not in commands
    assert ('G28' in commands) == (checkpoint == 2)


def test_probe_positioning_and_probe_start_each_have_stop_boundary():
    model = RecoveryModel()
    model.p['toolhead']['homed_axes'] = 'xyz'
    script = model.templates['PROBE_CALIBRATE'].render(printer=model.p, params={})
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    for stage in ('BED_MESH_CLEAR', '_WMP_CALIBRATION_CLEARANCE', 'G1 X150 Y150 F3000', 'PROBE_CALIBRATE_BASE'):
        assert commands[commands.index(stage)-1] == '_WMP_PROBE_PREPARE_CHECK'
