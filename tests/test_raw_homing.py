"""Actual stock dispatch: only a standalone G28 acquires the shared Home owner."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_calibration_commands import setup
from test_calibration_cancel_ingress import Request

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def raw_home():
    path=ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    if not path.is_file():pytest.skip('retained stock dispatcher required')
    spec=importlib.util.spec_from_file_location('stock_raw_home_dispatch',path)
    stock=importlib.util.module_from_spec(spec);spec.loader.exec_module(stock)
    p,runner=setup();p.command_error=stock.CommandError;p.quick_stop_flag=False
    events=[];calls=[]
    p.send_event=lambda name:events.append(name)
    p.invoke_shutdown=lambda message:pytest.fail('unexpected shutdown: '+message)
    p.objects['virtual_sdcard']=SimpleNamespace(is_active=lambda:False,is_cmd_from_sd=lambda:False)
    p.objects['wmp_recovery']=SimpleNamespace(calibration=runner)
    p.objects['toolhead']=SimpleNamespace(wait_moves=lambda:events.append('drained'))
    dispatch=stock.GCodeDispatch.__new__(stock.GCodeDispatch)
    dispatch.printer=p;dispatch.ready_gcode_handlers={};dispatch.base_gcode_handlers={}
    dispatch.gcode_handlers=dispatch.ready_gcode_handlers;dispatch.gcode_help={}
    dispatch._build_status_commands=lambda:None
    dispatch.respond_info=dispatch.respond_raw=dispatch._respond_error=lambda message:None
    dispatch.cmd_default=lambda command:pytest.fail('unexpected command '+command.get_command())
    original=lambda command:calls.append(command)
    dispatch.register_command('G28',original)
    runner.gcode=dispatch;p.objects['gcode']=dispatch
    runner.raw_homing.install()
    assert runner.raw_homing.installed
    return p,runner,dispatch,original,calls,events,stock


@pytest.mark.parametrize('line,expected',[
    ('G28',{}),('G28 P3',{'P':'3'}),('G28 X0',{'X':'0'}),
    ('G28 Y P1',{'Y':'','P':'1'}),('G28 X Y',{'X':'','Y':''}),
    ('G28 Z',{'Z':''}),('G28 X Y Z P0',{'X':'','Y':'','Z':'','P':'0'}),
    ('N7 G28 Y',{'N':'7','G':'28','Y':''}),
])
def test_raw_home_passes_original_command_and_parameters(raw_home,line,expected):
    p,runner,dispatch,original,calls,events,stock=raw_home
    dispatch.run_script_from_command(line)
    assert len(calls)==1 and calls[0].get_commandline()==line
    assert calls[0].get_command_parameters()=={'G':'28',**expected}
    outcome=runner.attempt_status()
    assert outcome['state']=='complete' and outcome['operation']=='home' and outcome['home_origin']=='raw'
    assert runner._ticket_counter==1 and not p.sent


def test_nested_macro_home_retains_caller_and_no_new_ticket(raw_home):
    p,runner,dispatch,original,calls,events,stock=raw_home
    dispatch.gcode_handlers['TEST_ROOT']=lambda command:dispatch.run_script_from_command('G28 P2')
    dispatch.run_script_from_command('TEST_ROOT')
    assert len(calls)==1 and calls[0].get_command_parameters()=={'G':'28','P':'2'}
    assert not runner.attempt_result and runner._ticket_counter==0


def test_recursive_override_home_uses_one_owner_and_original_objects(raw_home):
    p,runner,dispatch,original,calls,events,stock=raw_home
    def override(command):
        calls.append(command)
        if len(calls)==1:dispatch.run_script_from_command('G28 Z')
    runner.raw_homing.original=override
    dispatch.run_script_from_command('G28 P3')
    assert len(calls)==2 and calls[0] is not calls[1]
    assert calls[0].get_command_parameters()=={'G':'28','P':'3'} and calls[1].get_command_parameters()=={'G':'28','Z':''}
    assert runner._ticket_counter==1 and runner.attempt_status()['state']=='complete'


@pytest.mark.parametrize('owner',['openace','AFC','printing','paused','sd_active','from_sd'])
def test_existing_owner_home_is_not_rebound(raw_home,owner):
    p,runner,dispatch,original,calls,events,stock=raw_home
    if owner in ('openace','AFC'):p.objects[owner]=object()
    elif owner in ('printing','paused'):p.state=owner
    else:p.objects['virtual_sdcard']=SimpleNamespace(is_active=lambda:owner=='sd_active',is_cmd_from_sd=lambda:owner=='from_sd')
    dispatch.run_script_from_command('G28 P1')
    assert len(calls)==1 and runner._ticket_counter==0 and not runner.attempt_result


@pytest.mark.parametrize('pending',['active','attempt','cancel','filament','toolhead'])
def test_competing_raw_home_cannot_steal_pending_owner(raw_home,pending):
    p,runner,dispatch,original,calls,events,stock=raw_home
    if pending=='active':runner.active=True
    elif pending=='attempt':runner._current_attempt={'state':'pending'}
    elif pending=='cancel':runner._pending_cancel=(runner.session,'a'*32,'1')
    else:p.objects['wm_material']=SimpleNamespace(_material_operation_active=lambda name:name==pending+'_operation')
    with pytest.raises(stock.CommandError,match='Wait for the current'):
        dispatch.run_script_from_command('G28')
    assert not calls and runner._ticket_counter==0


def test_raw_home_cancel_unwinds_stock_dispatch_and_holds_without_park(raw_home):
    p,runner,dispatch,original,calls,events,stock=raw_home
    def home(command):
        calls.append(command)
        runner.handle_cancel(Request(runner))
        runner.cmd_stop_point(SimpleNamespace(get=lambda key,default='':'before_z_homing',error=stock.CommandError))
        pytest.fail('continued to Z')
    runner.raw_homing.original=home
    with pytest.raises(stock.CommandError,match='Homing cancellation requested'):
        dispatch.run_script_from_command('G28 P3')
    outcome=runner.attempt_status()
    assert len(calls)==1 and outcome['cancel_cleanup']['park']=='held'
    assert outcome['cancel_cleanup']['state']=='complete' and events==['drained','gcode:command_error']
    assert not p.sent


def test_raw_install_is_idempotent_and_restores_handler_on_failure(raw_home,monkeypatch):
    p,runner,dispatch,original,calls,events,stock=raw_home
    installed=dispatch.gcode_handlers['G28'];runner.raw_homing.install()
    assert dispatch.gcode_handlers['G28']==installed
    from wmp_raw_homing import RawHoming
    dispatch.register_command('G28',None);dispatch.register_command('G28',original)
    raw=RawHoming(runner);register=dispatch.register_command
    def fail(name,handler,*args,**kwargs):
        if handler==raw.command:raise RuntimeError('hook registration failed')
        return register(name,handler,*args,**kwargs)
    monkeypatch.setattr(dispatch,'register_command',fail)
    with pytest.raises(RuntimeError,match='registration failed'):raw.install()
    assert dispatch.gcode_handlers['G28'] is original and not raw.installed


def test_older_ui_request_cannot_execute_after_raw_home_claimed_its_ticket(raw_home):
    from test_calibration_tickets import ticket
    p,runner,dispatch,original,calls,events,stock=raw_home
    dispatch.run_script_from_command('G28 P2')
    raw_request=runner.attempt_status()['request']
    old=ticket(runner,'G28 X',1,request='f'*32)
    command=dispatch.create_gcode_command('_WMP_HOME_COMMAND','_WMP_HOME_COMMAND',dict(old.binding,HEX=old.encoded))
    with pytest.raises(stock.CommandError,match='different attempt'):
        runner.cmd_home(command)
    assert len(calls)==1 and runner.attempt_status()['request']==raw_request


def test_raw_home_fault_flag_is_not_relabelled_as_cancel(raw_home):
    p,runner,dispatch,original,calls,events,stock=raw_home
    def home(command):
        calls.append(command);p.fail=-3
        runner.handle_cancel(Request(runner))
        runner.cmd_stop_point(SimpleNamespace(get=lambda key,default='':'before_z_homing',error=stock.CommandError))
    runner.raw_homing.original=home
    with pytest.raises(stock.CommandError,match='Tool change failed.*fail_flag=-3'):
        dispatch.run_script_from_command('G28')
    outcome=runner.attempt_status()
    assert 'cancel_phase' not in outcome and outcome['cancel_cleanup']['state']=='incomplete'
    assert outcome['cancel_cleanup']['park']=='unconfirmed' and p.fail==-3 and len(calls)==1


@pytest.fixture(params=['filament', 'toolhead'])
def deferred_service(raw_home, request):
    from wmp_filament_service import FilamentService
    from wmp_toolhead_service import ToolheadService
    p, runner, dispatch, original, calls, events, stock = raw_home
    material = SimpleNamespace(printer=p, session_id='service-session', _command_generation=1, _print_cancel_active=lambda:False)
    kind = request.param
    name = kind + '_operation'
    operation = dict(id='service-1', session=material.session_id, head='h2', action='load' if kind=='filament' else 'mount', state='running')
    setattr(material, name, operation)
    material._material_operation_active=lambda key: getattr(material,key,{}).get('state') in ('pending','running')
    service=(FilamentService if kind=='filament' else ToolheadService)(material)
    setattr(service,name,operation)
    setattr(material,'_filament_service_component' if kind=='filament' else '_toolhead_service',service)
    actor=object();current=[actor]
    service._current_actor=lambda:current[0]
    service._boundary_scope=dict(operation=operation,id=operation['id'],head=operation['head'],action=operation['action'],
        session=material.session_id,generation=1,owners=(('openace',None),('AFC',None)),actor=actor,current_actor=service._current_actor)
    p.objects['wm_material']=material
    return raw_home,material,service,operation,current


@pytest.mark.parametrize('print_state',['standby','complete'])
def test_deferred_service_homing_keeps_owner_without_outer_dispatch(deferred_service,print_state):
    raw,material,service,operation,current=deferred_service
    p,runner,dispatch,original,calls,events,stock=raw;p.state=print_state
    # Same shape as the reactor callback after WMP_FILAMENT_SEQUENCE returned:
    # no outer WMP/macro dispatcher frame remains on this stack.
    dispatch.run_script_from_command('G28 X Y')
    assert len(calls)==1 and calls[0].get_command_parameters()=={'G':'28','X':'','Y':''}
    assert not runner.attempt_result and runner._ticket_counter==0 and operation['state']=='running'


@pytest.mark.parametrize('change',['actor','session','generation','operation','external_owner','pending'])
def test_deferred_service_does_not_authorize_another_or_stale_owner(deferred_service,change):
    raw,material,service,operation,current=deferred_service
    p,runner,dispatch,original,calls,events,stock=raw
    if change=='actor':current[0]=object()
    elif change=='session':material.session_id='replacement'
    elif change=='generation':material._command_generation+=1
    elif change=='operation':setattr(service,'filament_operation' if hasattr(service,'filament_operation') else 'toolhead_operation',dict(operation))
    elif change=='external_owner':service._boundary_scope['owners']=(('openace',object()),('AFC',None))
    elif change=='pending':operation['state']='pending'
    with pytest.raises(stock.CommandError,match='current physical service'):
        dispatch.run_script_from_command('G28 X Y')
    assert not calls and not runner.attempt_result and runner._ticket_counter==0


def test_deferred_service_cancel_is_seen_before_homing(deferred_service):
    raw,material,service,operation,current=deferred_service
    p,runner,dispatch,original,calls,events,stock=raw;operation['cancel_requested']=True
    with pytest.raises(stock.CommandError,match='cancelled'):
        dispatch.run_script_from_command('G28 X Y')
    assert not calls and not runner.attempt_result
