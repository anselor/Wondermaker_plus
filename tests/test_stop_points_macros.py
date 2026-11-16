"""Render START_PRINT and check stop point and wait region placement."""
import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import validate_klipper_config as validator
from test_config_macros import HeaterModel

EXPECTED = ['start_admitted', 'before_homing', 'homed', 'before_mesh', 'mesh_saved',
            'before_initial_tool', 'initial_tool_ready', 'purged']
MACROS = ROOT / 'config/live/macros.cfg'


def render_start_print(printer_overrides=None, params=None):
    """Return rendered, non-empty, stripped START_PRINT lines."""
    model = HeaterModel(ROOT / 'config/live')
    model.p['configfile']['settings']['printer'] = {'max_velocity': 600, 'max_accel': 10000}
    model.p['wm_material'] = {}
    model.p.update(printer_overrides or {})
    merged = {'BED': '60', 'EXTRUDER': '220', 'INITIAL_TOOL': '1'}
    merged.update(params or {})
    script = model.templates['START_PRINT'].render(
        printer=model.p, params=merged, adaptive_mesh_enable=True,
        action_respond_info=lambda *a: '',
        action_raise_error=lambda message: (_ for _ in ()).throw(ValueError(message)))
    return [line.strip() for line in script.splitlines() if line.strip()]


def adaptive_params(adaptive):
    if not adaptive:
        return {}
    return {'MESH_MIN_X': '10', 'MESH_MIN_Y': '10', 'MESH_MAX_X': '100',
            'MESH_MAX_Y': '100', 'PROBE_COUNT_X': '4', 'PROBE_COUNT_Y': '4'}


def phases(lines):
    return [m.group(1) for line in lines
            if (m := re.fullmatch(r'_WMP_STOP_POINT PHASE=(\w+)', line))]


def stop_point_keys():
    tree = ast.parse((ROOT / 'klipper_extras/wmp_stop_points.py').read_text())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(getattr(t, 'id', None) == 'STOP_POINTS' for t in node.targets)):
            return [k.value for k in node.value.keys]
    raise AssertionError('STOP_POINTS not found')


@pytest.mark.parametrize('adaptive', [True, False])
def test_start_print_stop_points_once_in_order(adaptive):
    lines = render_start_print(params=adaptive_params(adaptive))
    assert phases(lines) == EXPECTED
    assert set(phases(lines)) == set(stop_point_keys())


def test_start_print_key_command_order():
    lines = render_start_print(params=adaptive_params(True))

    def at(text):
        return next(i for i, line in enumerate(lines) if line.startswith(text))
    admitted = at('_WMP_STOP_POINT PHASE=start_admitted')
    assert at('_WMP_RECOVERY_JOB_BEGIN') < admitted
    assert lines[admitted + 1] == '_WMP_STOP_WAITS ENABLE=1'
    assert admitted < at('M118 START_PRINT begin')
    assert admitted < at('SET_HEATER_TEMPERATURE HEATER=heater_bed')
    assert at('TEMPERATURE_WAIT') < at('_WMP_STOP_POINT PHASE=before_homing') < at('G28')
    assert at('G28') < at('_WMP_STOP_POINT PHASE=homed') < at('M190')
    assert at('M190') < at('_WMP_STOP_POINT PHASE=before_mesh') < at('BED_MESH_CALIBRATE')
    assert at('M118 START_PRINT adaptive_mesh') < at('_WMP_STOP_POINT PHASE=mesh_saved')
    assert at('M400') < at('_WMP_STOP_POINT PHASE=before_initial_tool')
    assert at('M109') < at('_WMP_STOP_POINT PHASE=purged') < at('_WMP_PRINT_CONTEXT_COMMIT')


def test_start_print_closes_wait_region_around_each_initial_tool():
    lines = render_start_print()
    tool_lines = [i for i, line in enumerate(lines) if re.fullmatch(r'T\d', line)]
    assert len(tool_lines) == 2
    for index in tool_lines:
        nearest = next(lines[i] for i in range(index, -1, -1)
                       if lines[i].startswith('_WMP_STOP_WAITS'))
        assert nearest == '_WMP_STOP_WAITS ENABLE=0'
    first, second = tool_lines
    assert lines[first + 1] == '_WMP_STOP_WAITS ENABLE=1'
    assert lines[first + 2] == '_WMP_STOP_POINT PHASE=initial_tool_ready'
    # the purge heat wait runs inside an enabled region
    heat = next(i for i, line in enumerate(lines) if line.startswith('M109'))
    nearest = next(lines[i] for i in range(heat, -1, -1)
                   if lines[i].startswith('_WMP_STOP_WAITS'))
    assert nearest == '_WMP_STOP_WAITS ENABLE=1'


def test_no_stop_point_inside_purge_line():
    lines = render_start_print()
    start = lines.index('G1 Z0.4 F5000.0')
    end = next(i for i, line in enumerate(lines) if line.startswith('G1 Y150.0 E20'))
    assert not [line for line in lines[start:end + 1] if line.startswith('_WMP_STOP_POINT')]


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_start_print_renders_no_stop_lines_with_openace_or_afc(owner):
    overrides = {owner: {'tool_extruder_index': {'1': 1}}}
    lines = render_start_print(printer_overrides=overrides)
    assert not [line for line in lines if line.startswith(('_WMP_STOP_POINT', '_WMP_STOP_WAITS'))]


def test_no_stop_lines_without_wm_material():
    model = HeaterModel(ROOT / 'config/live')
    model.p['configfile']['settings']['printer'] = {'max_velocity': 600, 'max_accel': 10000}
    script = model.templates['START_PRINT'].render(
        printer=model.p, params={'BED': '60', 'EXTRUDER': '220', 'INITIAL_TOOL': '1'},
        adaptive_mesh_enable=True, action_respond_info=lambda *a: '')
    assert '_WMP_STOP_' not in script


def test_stop_point_macro_text_passes_validator():
    text = MACROS.read_text()
    assert '_WMP_STOP_POINT' in text
    assert validator.validate_text('macros.cfg', text) == []
