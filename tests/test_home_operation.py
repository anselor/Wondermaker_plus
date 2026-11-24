"""Standalone Home reuses bound ingress; it never saves or parks on Cancel."""
from types import SimpleNamespace

import pytest

from test_calibration_commands import setup, Command
from test_calibration_tickets import ticket
from test_calibration_cancel_ingress import Request


@pytest.mark.parametrize('command', ['G28', 'G28 X', 'G28 Y', 'G28 X Y', 'G28 Z'])
def test_one_home_command_completes_its_shared_ticket(command):
    p, runner = setup()
    request = ticket(runner, command)
    runner.cmd_home(request)
    assert p.sent == [command]
    assert runner.attempt_status()['state'] == 'complete'
    assert runner.attempt_status()['operation'] == 'home'
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_home(request)
    assert p.sent == [command]


@pytest.mark.parametrize('command', ['SAVE_CONFIG', 'G29', 'G28\nSAVE_CONFIG', 'G28 P3', 'G28 X Z', 'M400'])
def test_home_cannot_grow_into_calibration_or_arbitrary_motion(command):
    p, runner = setup()
    with pytest.raises(RuntimeError, match='accepts only'):
        runner.cmd_home(ticket(runner, command))
    assert not p.sent and runner.attempt_status()['state'] == 'refused'


def test_home_requires_current_shared_ticket():
    p, runner = setup()
    with pytest.raises(RuntimeError, match='ticket-bound'):
        runner.cmd_home(Command('G28'))
    assert not p.sent and not runner.attempt_result


def test_calibration_request_cannot_be_retyped_as_home():
    p, runner = setup()
    runner.cmd_run(ticket(runner, 'M400', 1))
    before = runner.attempt_status()
    with pytest.raises(RuntimeError, match='kind differs'):
        runner.cmd_home(ticket(runner, 'G28', 1, 1))
    assert runner.attempt_status() == before
    assert p.sent == ['M400']


def test_home_cannot_be_retyped_as_calibration_save():
    p, runner = setup()
    runner.cmd_home(ticket(runner, 'G28', 1))
    with pytest.raises(RuntimeError, match='kind differs'):
        runner.cmd_run(ticket(runner, 'SAVE_CONFIG', 1, 1))
    assert p.sent == ['G28'] and runner.attempt_status()['state'] == 'complete'


@pytest.mark.parametrize('phase', ['before_z_homing', 'tool_homed', 'tool_docked'])
def test_cancelled_home_holds_without_docking_or_disabling_motors(phase):
    p, runner = setup()
    p.objects['wmp_recovery'] = SimpleNamespace(calibration=runner)
    waited=[]
    p.objects['toolhead'] = SimpleNamespace(wait_moves=lambda: waited.append('drained'))
    def executing(command):
        runner.handle_cancel(Request(runner))
        runner.cmd_stop_point(SimpleNamespace(get=lambda key, default='':phase, error=RuntimeError))
        pytest.fail('home continued beyond boundary')
    p.on_run = executing
    with pytest.raises(RuntimeError, match='Homing cancellation requested'):
        runner.cmd_home(ticket(runner, 'G28', 1))
    result = runner.attempt_status()
    assert result['cancel_cleanup'] == {'state':'complete','offsets':'not_needed','park':'held','error':''}
    assert p.sent == ['G28'] and waited == ['drained'] and not p.shutdown


def test_early_cancel_consumes_ticket_without_homing():
    p, runner = setup()
    args={'session':runner.session,'request':'0'*31+'1','ticket':'1'}
    request=SimpleNamespace(get_str=lambda key:args[key],send=lambda reply:None,error=RuntimeError)
    runner.handle_cancel(request)
    runner.cmd_home(ticket(runner,'G28',1))
    assert not p.sent and runner.attempt_status()['cancel_cleanup']['park']=='not_moved'


def test_cancelled_home_with_unconfirmed_drain_stays_incomplete():
    p, runner = setup()
    def executing(command): runner.handle_cancel(Request(runner))
    p.on_run = executing
    with pytest.raises(RuntimeError, match='Homing cancellation requested'):
        runner.cmd_home(ticket(runner,'G28',1))
    assert runner.attempt_status()['cancel_cleanup']['state']=='incomplete'
    assert p.sent==['G28'] and not p.shutdown


def test_normal_home_fault_stays_primary_even_if_cancel_arrives():
    p, runner = setup()
    p.objects['toolhead']=SimpleNamespace(wait_moves=lambda:None)
    def executing(command):
        runner.handle_cancel(Request(runner))
        raise RuntimeError('endstop failed')
    p.on_run=executing
    with pytest.raises(RuntimeError, match='endstop failed'):
        runner.cmd_home(ticket(runner,'G28',1))
    assert runner.attempt_status()['error']=='endstop failed'
    assert runner.attempt_status()['cancel_cleanup']['state']=='incomplete'
    assert runner.attempt_status()['cancel_cleanup']['park']=='unconfirmed'
    assert p.sent==['G28'] and not p.shutdown


def test_foreign_reactor_context_cannot_consume_home_boundary():
    p, runner = setup()
    p.objects['wmp_recovery']=SimpleNamespace(calibration=runner)
    actor=['command'];runner._heater_ownership.current_actor=lambda:actor[0]
    p.objects['toolhead']=SimpleNamespace(wait_moves=lambda:None)
    def executing(command):
        runner.handle_cancel(Request(runner))
        boundary=SimpleNamespace(get=lambda key, default='':'before_z_homing',error=RuntimeError)
        actor[0]='reactor callback'
        runner.cmd_stop_point(boundary)
        assert 'cancel_phase' not in runner.executing
        actor[0]='command'
        runner.cmd_stop_point(boundary)
        pytest.fail('bound home did not stop')
    p.on_run=executing
    with pytest.raises(RuntimeError,match='Homing cancellation requested'):
        runner.cmd_home(ticket(runner,'G28',1))
    assert runner.attempt_status()['cancel_phase']=='before Z homing'


@pytest.mark.parametrize('owner',['openace','AFC'])
def test_external_manager_cannot_receive_standalone_home_ticket(owner):
    p, runner=setup();p.objects[owner]=object()
    with pytest.raises(RuntimeError,match='owned by another'):
        runner.cmd_home(ticket(runner,'G28',1))
    assert not p.sent and not runner.attempt_result and runner._ticket_counter==0


@pytest.mark.parametrize('stop_axis',[1,0])
def test_xy_boundary_cancel_never_enters_stock_motor_off_error_handler(stop_axis):
    import importlib.util
    from pathlib import Path
    from wmp_xy_homing import XYHoming
    path=Path(__file__).resolve().parents[1]/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/homing.py'
    if not path.is_file(): pytest.skip('retained stock homing implementation required')
    spec=importlib.util.spec_from_file_location('stock_home_cancel_boundary',path)
    stock=importlib.util.module_from_spec(spec);spec.loader.exec_module(stock)
    p,runner=setup();p.command_error=RuntimeError;p.objects['gcode']=p
    p.objects['wmp_recovery']=SimpleNamespace(calibration=runner)
    calls=[]
    rails=[SimpleNamespace(get_name=lambda:'stepper_x',get_homing_info=lambda:SimpleNamespace(positive_dir=True)),
           SimpleNamespace(get_name=lambda:'stepper_y',get_homing_info=lambda:SimpleNamespace(positive_dir=False))]
    def home_axis(state):
        calls.append(('native axis',state.get_axes()))
        if state.get_axes()==[stop_axis]: runner.handle_cancel(Request(runner))
    kin=SimpleNamespace(rails=rails,limits=[(0,300),(0,300)],home=home_axis)
    p.objects['toolhead']=SimpleNamespace(get_kinematics=lambda:kin,wait_moves=lambda:calls.append(('wait',)))
    p.objects['stepper_enable']=SimpleNamespace(motor_off=lambda:calls.append(('motor_off',)))
    native=stock.PrinterHoming.__new__(stock.PrinterHoming);native.printer=p;p.objects['homing']=native
    p.create_gcode_command=lambda name,text,params:SimpleNamespace(get=lambda key,default=None:params.get(key,default))
    xy=XYHoming(p)
    gcmd=SimpleNamespace(error=RuntimeError,respond_info=lambda message:None)
    p.on_run=lambda command:xy._home(gcmd,stock.Homing,stock.HomingMove)
    axis='Y' if stop_axis==1 else 'X'
    with pytest.raises(RuntimeError,match='Homing cancellation requested; stopped after '+axis+' homing'):
        runner.cmd_home(ticket(runner,'G28 X Y',1))
    expected=[('native axis',[1]),('wait',)]
    if stop_axis==0: expected += [('native axis',[0]),('wait',)]
    assert calls==expected+[('wait',)]
    assert kin.limits[1]==(1.,-1.) and not p.shutdown
