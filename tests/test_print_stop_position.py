"""Exercise the actual finish/cancel position templates and guarded park route."""
import re
import shlex

import pytest
from test_config_macros import ROOT,templates


@pytest.fixture(scope='module')
def macros():return templates(ROOT/'config/live')


def printer(z,minimum=50.,target=125.,homed='xyz'):
    return {'gcode_macro PRINT_END':{'bed_drop_minimum':minimum,'bed_drop_target_z':target},
        'toolhead':{'position':{'z':z},'homed_axes':homed},
        'gcode_move':{'gcode_position':{'z':z-.3}},
        'configfile':{'settings':{'stepper_z':{'position_endstop':300.},'printer':{'max_velocity':600}}},
        'save_variables':{'variables':{'current_extruder':2,'fail_flag':0,'changing_tool':0,'wipe_position':[-13.,240.]}},
        'wm_material':{'attachment':{'state':'attached','head':'h2'}}}


def render(macros,name,p,**params):
    def fail(message):raise ValueError(message)
    return macros[name].render(printer=p,params=params,action_raise_error=fail,action_respond_info=lambda message:'',
        travel_speed=300.,hot_travel_speed=500.)


@pytest.mark.parametrize('z,minimum,target,final',[(2,50,125,125),(100,50,125,150),(275,50,125,300),(300,50,125,None),
    (304,50,125,None),(20,0,125,125),(20,0,0,None),(20,10,5,30),(2,5,500,300)])
def test_physical_target_or_minimum_never_raises_or_crosses_bottom(macros,z,minimum,target,final):
    text=render(macros,'_WMP_PRINT_LOWER_BED',printer(z,minimum,target))
    values=[float(v) for v in re.findall(r'^\s*G1 Z([^ ]+)',text,re.M)]
    assert values==([] if final is None else [pytest.approx(final-.3)])
    assert 'G28' not in text and '_WMP_XY_TRAVEL' not in text and 'MOVE=1' not in text


@pytest.mark.parametrize('value',[-1,float('nan'),float('inf'),'bad'])
@pytest.mark.parametrize('option',['bed_drop_minimum','bed_drop_target_z'])
def test_invalid_controls_are_rejected_before_movement(macros,value,option):
    p=printer(2);p['gcode_macro PRINT_END'][option]=value
    with pytest.raises(ValueError,match='nonnegative finite'):render(macros,'_WMP_PRINT_LOWER_BED',p,PARK='1')


def test_lowering_drains_before_parking_and_passes_real_clearance(macros):
    text=render(macros,'_WMP_PRINT_LOWER_BED',printer(100),PARK='1')
    assert text.index('G1 Z149.7')<text.index('M400')<text.index('_WMP_PRINT_STOP_PARK CLEARANCE=50.0 WIPE=0')


@pytest.mark.parametrize('reason',['unhomed','no_clearance','fault','changing','unknown_attachment','wrong_head','empty'])
def test_unsafe_park_does_not_home_select_or_move(macros,reason):
    p=printer(100);clearance=50
    if reason=='unhomed':p['toolhead']['homed_axes']='z'
    elif reason=='no_clearance':clearance=0
    elif reason=='fault':p['save_variables']['variables']['fail_flag']=-3
    elif reason=='changing':p['save_variables']['variables']['changing_tool']=1
    elif reason=='unknown_attachment':p['wm_material']['attachment']={'state':'unknown'}
    elif reason=='wrong_head':p['wm_material']['attachment']['head']='h1'
    else:p['wm_material']['attachment']={'state':'empty','head':''}
    text=render(macros,'_WMP_PRINT_STOP_PARK',p,CLEARANCE=clearance)
    assert not any(word in text for word in ('G0 ','G1 ','G28','_WMP_XY_TRAVEL','WIPE_NOZZLE','_CHANGE_TOOL','LOCK','EXTRUDE'))


def test_cancel_park_uses_shared_hot_travel_without_extrusion_or_wiping(macros):
    p=printer(100);text=render(macros,'_WMP_PRINT_STOP_PARK',p,CLEARANCE=50)
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    moves=[line for line in lines if line.startswith('_WMP_XY_TRAVEL')]
    assert moves==['_WMP_XY_TRAVEL Y=240.0 HOT=1','_WMP_XY_TRAVEL X=-13.0 HOT=1','_WMP_XY_TRAVEL Y=275.0 HOT=1']
    assert not any(word in text for word in ('G28','WIPE_NOZZLE','_CHANGE_TOOL','EXTRUDE','STEPPER_HOMING','MOVE=1'))
    assert 'SAVE_GCODE_STATE NAME=wmp_print_stop_park' in text and 'RESTORE_GCODE_STATE NAME=wmp_print_stop_park MOVE=0' in text
    for line in moves:
        params=dict(token.split('=',1) for token in shlex.split(line)[1:])
        assert 'F30000.0' in render(macros,'_WMP_XY_TRAVEL',p,**params)


def test_finish_keeps_xy_only_wipe_and_shared_z_policy(macros):
    p=printer(2)
    text=render(macros,'_WMP_PRINT_END_CLEARANCE_AND_WIPE',p)
    assert text.index('BED_MESH_CLEAR')<text.index('_WMP_PRINT_LOWER_BED PARK=1 WIPE=1')
    text=render(macros,'_WMP_PRINT_STOP_PARK',p,CLEARANCE=123,WIPE=1)
    assert 'WIPE_NOZZLE XY_ONLY=1' in text and 'G28' not in text and 'G1 Z' not in text
