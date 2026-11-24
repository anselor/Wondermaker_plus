"""Shared tool stages stop only after native home/coupling has returned."""
from types import SimpleNamespace

import pytest

from test_config_macros import ROOT, templates
from test_calibration_commands import setup
from test_calibration_tickets import ticket
from test_calibration_cancel_ingress import Request


def render(name, owner='standalone', unhomed=False):
    p = {'wm_material': {'session_id':'s', 'command_generation':0},
         'wmp_recovery': {'z_reference_valid':True},
         'toolhead': {'homed_axes':'xyz'},
         'print_stats': {'state':'standby'},
         'gcode_move': {'speed_factor':1},
         'save_variables': {'variables': {'current_extruder':2, 'fail_flag':0, 't3_flow_extruder':1}},
         'gcode_macro _WMP_TOOL_RETURN_BEGIN': {'pending':1},
         'gcode_macro _descend_z': {'need_descend':0},
         'gcode_macro _CHECK_CHANGE_TOOL': {'retry':0}}
    if unhomed:
        p['toolhead']['homed_axes']=''
        p['wmp_recovery']['z_reference_valid']=False
    if owner != 'standalone': p[owner] = {}
    script = templates(ROOT / 'config/live')[name].render(
        printer=p, params={'T':'3'}, retry=0,
        action_respond_info=lambda *a:'',
        action_raise_error=lambda message: (_ for _ in ()).throw(RuntimeError(message)))
    return [line.strip() for line in script.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def test_switch_stops_after_home_and_verified_release_before_pickup():
    lines = render('_CHANGING_TOOL')
    home = lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_homed')
    before = lines.index('_WMP_OPERATION_STOP_POINT PHASE=before_tool_dock')
    dock = lines.index('_UNLOCK_TOOL T=2')
    after = lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_docked')
    mount = lines.index('_LOCK_TOOL T=3 DEFER_CHECK=1')
    assert home < before < dock < after < mount
    for index in (home, before, after): assert lines[index-1] == 'M400'


def test_direct_park_checks_before_and_after_complete_dock_macro():
    lines = render('PARK_CURRENT_TOOL')
    before = lines.index('_WMP_OPERATION_STOP_POINT PHASE=before_tool_dock')
    after = lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_docked')
    assert before < lines.index('_UNLOCK_TOOL T=2') < after < lines.index('PARK_CURRENT_TOOL_RETRY')
    assert lines[before-1] == lines[after-1] == 'M400'


def test_wipe_checks_surround_completed_wipe_after_heating():
    lines = render('_CHECK_CHANGE_TOOL')
    before = lines.index('_WMP_OPERATION_STOP_POINT PHASE=before_tool_wipe')
    after = lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_wiped')
    assert lines.index('_WAIT_TOOL_TEMPERATURE') < before < lines.index('WIPE_NOZZLE') < after
    assert lines[before-1] == lines[after-1] == 'M400'


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
@pytest.mark.parametrize('macro', ['_CHANGING_TOOL', 'PARK_CURRENT_TOOL', '_CHECK_CHANGE_TOOL'])
def test_external_owner_retains_original_stage_flow(owner, macro):
    assert not any('_WMP_OPERATION_STOP_POINT' in line for line in render(macro, owner))


@pytest.mark.parametrize('phase', ['tool_homed', 'before_tool_dock', 'tool_docked', 'before_tool_wipe', 'tool_wiped'])
def test_bound_cancel_at_shared_tool_boundary_stops_later_stage(phase):
    p, runner = setup()
    p.objects['wmp_recovery'] = SimpleNamespace(calibration=runner)
    # Exercise real ingress/command dispatch and shared stop observer together.
    boundary = SimpleNamespace(get=lambda key, default='': phase if key=='PHASE' else default, error=RuntimeError)
    observed=[]
    def executing(command):
        runner.handle_cancel(Request(runner))
        observed.append('completed atomic stage')
        runner.cmd_stop_point(boundary)
        pytest.fail('later stage executed after cancellation')
    p.on_run = executing
    with pytest.raises(RuntimeError, match='Calibration cancellation requested'):
        runner.cmd_run(ticket(runner, 'G28', 1))
    assert observed == ['completed atomic stage']
    assert runner.attempt_status()['cancel_phase']
    assert not p.shutdown


@pytest.mark.parametrize('macro', ['LOCK', 'UNLOCK', '_LOCK_CHECK', '_CHECK_AND_LOCK', '_CHECK_AND_UNLOCK'])
def test_coupling_and_immediate_retreat_have_no_new_cancel_point(macro):
    # These scopes include actuator completion and mandatory retreat/sensor
    # bookkeeping. Only their outer completed-service boundaries may stop.
    import configparser
    config = configparser.RawConfigParser()
    config.read(ROOT / 'config/live/change_macros.cfg')
    assert '_WMP_OPERATION_STOP_POINT' not in config.get('gcode_macro ' + macro, 'gcode')


def test_cleanup_owner_can_finish_its_own_dock_after_cancel():
    p, runner = setup()
    p.objects['wmp_recovery'] = SimpleNamespace(calibration=runner)
    def executing(command):
        runner.handle_cancel(Request(runner))
        runner.executing['cancel_cleanup'] = {'state':'running'}
        boundary = SimpleNamespace(get=lambda key, default='': 'tool_docked' if key=='PHASE' else default, error=RuntimeError)
        runner.cmd_stop_point(boundary)
        runner.executing.pop('cancel_cleanup')
    p.on_run = executing
    with pytest.raises(RuntimeError, match='stopped after G28'):
        runner.cmd_run(ticket(runner, 'G28', 1))
    assert not p.shutdown


@pytest.mark.parametrize('owner', [None, 'openace', 'AFC'])
def test_unbound_or_external_tool_boundary_does_not_claim_cancel_ownership(owner):
    p, runner = setup()
    p.objects['wmp_recovery'] = SimpleNamespace(calibration=runner)
    if owner:
        p.objects[owner] = object()
        # A previously admitted standalone Cancel must not cross to a manager
        # that now owns the operation.
        runner.executing = {'cancel_requested':True}
    boundary = SimpleNamespace(get=lambda key, default='': 'before_tool_dock' if key=='PHASE' else default, error=RuntimeError)
    runner.cmd_stop_point(boundary)
    assert not p.sent and not p.shutdown and not runner.attempt_result


def test_nested_tool_homing_uses_shared_xy_helper_after_z_stop_boundary():
    lines=render('_CHANGING_TOOL', unhomed=True)
    bottom=lines.index('_WMP_HOME_Z_BOTTOM')
    stop=lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_z_homed')
    xy=lines.index('_WMP_HOME_XY')
    assert bottom < stop < xy < lines.index('_WMP_OPERATION_STOP_POINT PHASE=tool_homed')
    assert lines[stop-1]=='M400' and 'G28 X Y' not in lines


@pytest.mark.parametrize('owner',['openace','AFC'])
def test_external_nested_home_keeps_vendor_dispatch(owner):
    lines=render('_CHANGING_TOOL', owner, unhomed=True)
    assert 'G28 X Y' in lines and '_WMP_HOME_XY' not in lines
    assert not any('_WMP_OPERATION_STOP_POINT' in line for line in lines)
