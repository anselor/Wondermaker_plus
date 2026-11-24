"""Execute real pre-home macros with sensor changes only after drained retreat."""
import pytest
from test_print_recovery import RecoveryModel


def parked(head=2, offset=0., speed=1., settle=True):
    m = RecoveryModel()
    m.p['print_stats']['state'] = 'standby'
    m.sv.update(current_extruder=99, **{'t%d_position' % i: [44.375 + 62*i, 340.4] for i in range(4)})
    m.p['toolhead'].update(homed_axes='xyz', position={'x':44.375+62*head,'y':340.8,'z':7.})
    m.p['gcode_move'].update(speed_factor=speed, gcode_position={'x':0.,'y':340.8+offset,'z':7.})
    m.p['custom_hall']['Raw'] = 4681.
    m.p['filament_switch_sensor sensor_b']['filament_detected'] = False
    for i in range(4):m.p['filament_switch_sensor docked%d' % i]['filament_detected'] = True
    moved = []
    def hardware(command, args):
        if command == 'G1':
            assert set(args) == {'Y','F'}
            moved.append(dict(args))
            m.p['toolhead']['position']['y'] = float(args['Y'])-offset
        if command == 'M400' and moved and settle:
            m.p['custom_hall']['Raw'] = 4900.
    m.hardware_command = hardware
    return m, moved


@pytest.mark.parametrize('head',range(4))
@pytest.mark.parametrize('offset,speed',[(0.,1.),(80.,.5),(-23.,2.)])
def test_retreats_in_existing_frame_then_resamples_before_selecting(head,offset,speed):
    m,moved=parked(head,offset,speed)
    m.run('_WMP_SELECT_HOME_TOOL',PROBE_TOOL=1)
    assert len(moved) == 1
    assert {k:float(v) for k,v in moved[0].items()} == pytest.approx({'Y':310.+offset,'F':3000./speed})
    assert m.sv['current_extruder']==99 and m.sv['probe_tool']==1
    names=[cmd for cmd,args in m.events]
    assert names.index('M400') < names.index('G1') < names.index('_WMP_SELECT_HOME_TOOL_SETTLED')
    retreat=names.index('G1')
    assert names[retreat+1:retreat+4]==['M400','G4','M400']
    assert next(args for cmd,args in m.events if cmd=='RESTORE_GCODE_STATE')['MOVE']=='0'
    assert not any(cmd in ['G28','UNLOCK','LOCK','ACTIVATE_EXTRUDER'] for cmd,args in m.events)


@pytest.mark.parametrize('fault',['unhomed','wrong_x','wrong_y','locked','missing_dock','saved_fault','stale_head','bad_hall','bad_dock','two_matches'])
def test_uncertain_start_does_not_retreat_or_publish_selection(fault):
    m,moved=parked()
    if fault=='unhomed':m.p['toolhead']['homed_axes']='z'
    elif fault=='wrong_x':m.p['toolhead']['position']['x']+=3
    elif fault=='wrong_y':m.p['toolhead']['position']['y']=320.
    elif fault=='locked':m.p['filament_switch_sensor sensor_b']['filament_detected']=True
    elif fault=='missing_dock':m.p['filament_switch_sensor docked1']['filament_detected']=False
    elif fault=='saved_fault':m.sv['fail_flag']=-3
    elif fault=='stale_head':m.sv['current_extruder']=0
    elif fault=='bad_hall':m.p['custom_hall']['Raw']=0.
    elif fault=='bad_dock':m.sv['t2_position']=[168.375,float('nan')]
    else:m.sv['t1_position']=list(m.sv['t2_position'])
    before=dict(m.sv)
    with pytest.raises(ValueError):m.run('_WMP_SELECT_HOME_TOOL')
    assert m.sv==before
    assert not moved
    assert not any(cmd in ['G28','LOCK','UNLOCK'] for cmd,args in m.events)


def test_failed_post_retreat_read_still_refuses_without_homing_or_selection():
    m,moved=parked(settle=False);before=dict(m.sv)
    with pytest.raises(ValueError,match='sensors disagree'):m.run('_WMP_SELECT_HOME_TOOL')
    assert len(moved)==1 and m.sv==before
    assert not any(cmd in ['G28','LOCK','UNLOCK'] for cmd,args in m.events)


@pytest.mark.parametrize('tool',['99','wrong'])
def test_invalid_probe_selection_never_moves(tool):
    m,moved=parked()
    with pytest.raises(ValueError,match='Invalid physical probe'):m.run('_WMP_SELECT_HOME_TOOL',PROBE_TOOL=tool)
    assert not moved


def test_bad_speed_override_refuses_before_movement():
    m,moved=parked(speed=0.)
    with pytest.raises(ValueError,match='speed override'):m.run('_WMP_SELECT_HOME_TOOL')
    assert not moved


def test_fluctuating_hall_does_not_skip_clearance_when_it_reads_empty():
    m,moved=parked()
    m.p['custom_hall']['Raw']=4735.
    m.run('_WMP_SELECT_HOME_TOOL')
    assert len(moved)==1
    assert m.p['toolhead']['position']['y']==pytest.approx(310.)
    assert m.sv['current_extruder']==99
