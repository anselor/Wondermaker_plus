"""Pre-unlock support re-read: no actuator/reseat commands from observation."""
import logging
import pytest
from test_pickup_sensor_settle import pickup, material


def execute_unlock_tail(obj, cmd):
    # Actual macro order is independently checked in test_config_macros.
    commands=[]
    obj.cmd_CHECK_DOCK_SUPPORT(cmd)
    commands.append('UNLOCK')
    return commands


def test_positive_support_preserves_immediate_unlock(pickup):
    obj,cmd,clock,sensor,saved,reactor=pickup
    assert execute_unlock_tail(obj,cmd)==['UNLOCK']
    assert clock['waits']==0 and saved=={'fail_flag':0}


def test_delayed_support_arrives_before_unlock(pickup,caplog):
    obj,cmd,clock,sensor,saved,reactor=pickup
    sensor['filament_detected']=False
    pause=reactor.pause
    def delayed(when):
        pause(when)
        if when>=.15:sensor['filament_detected']=True
    reactor.pause=delayed
    with caplog.at_level(logging.INFO):assert execute_unlock_tail(obj,cmd)==['UNLOCK']
    assert .15<=clock['now']<.5 and saved=={'fail_flag':0}
    assert 'initial=False final=True' in caplog.text


@pytest.mark.parametrize('value',[False,None])
def test_persistent_false_or_unknown_never_unlocks(pickup,value):
    obj,cmd,clock,sensor,saved,reactor=pickup
    sensor['filament_detected']=value
    with pytest.raises(ValueError,match='expected True before unlock') as error:
        execute_unlock_tail(obj,cmd)
    assert clock['now']==pytest.approx(.5)
    assert saved=={'fail_flag':-3,'fail_tool':2}
    assert error.value.wmp_toolchange_fault==(-3,'dock_sensor')


@pytest.mark.parametrize('change',['generation','stop','session'])
def test_retired_observation_never_unlocks_or_publishes_failure(pickup,change):
    obj,cmd,clock,sensor,saved,reactor=pickup
    sensor['filament_detected']=False
    pause=reactor.pause
    def retired(when):
        pause(when);sensor['filament_detected']=True
        if change=='generation':obj._command_generation+=1
        elif change=='session':obj.session_id='new-session'
        else:obj.printer.lookup_object('gcode').quick_stop_flag=True
    reactor.pause=retired
    with pytest.raises(ValueError):execute_unlock_tail(obj,cmd)
    assert saved=={'fail_flag':0} and clock['now']==.05


def test_contradictory_support_at_deadline_is_not_treated_as_success(pickup):
    obj,cmd,clock,sensor,saved,reactor=pickup
    sensor['filament_detected']=None
    pause=reactor.pause
    def delayed(when):
        pause(when)
        if when>=.5:sensor['filament_detected']=False
    reactor.pause=delayed
    with pytest.raises(ValueError,match='docked2=False'):execute_unlock_tail(obj,cmd)
    assert saved['fail_flag']==-3


def test_missing_dock_object_is_explicit_unknown_support_refusal(pickup):
    obj,cmd,clock,sensor,saved,reactor=pickup
    lookup=obj.printer.lookup_object
    obj.printer.lookup_object=lambda name,default=None:default if name=='filament_switch_sensor docked2' else lookup(name,default)
    with pytest.raises(ValueError,match='docked2=None.*expected True before unlock'):
        execute_unlock_tail(obj,cmd)
    assert saved['fail_flag']==-3
