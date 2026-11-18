"""Recovery uses vendor manual homing without the command's swallowed error."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial

SOURCE = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/echelon_stepper.py'


@pytest.fixture
def actuator_machine():
    if not SOURCE.exists():
        pytest.skip('retained vendor actuator unavailable')
    # Compile the actual vendor method without importing hardware/C dependencies.
    tree = ast.parse(SOURCE.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'EchelonStepper')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'do_homing_move')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    calls, fault = [], {'home': False, 'post': False, 'owner': False, 'disable': False}
    def home(*args):
        calls.append('home')
        assert args[2:] == ([150., 0., 0., 0.], 100., True, 1)
        if fault['home']:
            raise ValueError('endstop not reached')
    def move(*args):
        calls.append('post')
        assert args == (-125., 100., 20., True)
        if fault['post']:
            raise ValueError('post move failed')
    def disable(enabled):
        assert enabled is False
        calls.append('disable')
        if fault['disable']:
            raise ValueError('disable failed')
    objects = {'homing': NS(manual_home=home),
               'gcode': NS(get_mutex=lambda: NS(test=lambda: True)),
               'toolhead': NS(wait_moves=lambda: calls.append('wait'))}
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default))
    actuator = NS(printer=printer, accel=20., rail=NS(get_endstops=lambda: ['endstop']),
                  do_set_position=lambda pos: calls.append('zero'), do_move=move, do_enable=disable)
    actuator.do_homing_move = lambda *args: namespace['do_homing_move'](actuator, *args)
    objects['echelon_stepper trans_stepper'] = actuator
    material = WMMaterial.__new__(WMMaterial)
    material.printer = printer
    def guard():
        if fault['owner'] and calls:
            raise ValueError('owner changed')
    return material, objects, calls, fault, guard


@pytest.mark.parametrize('lock', [True, False])
def test_actuator_uses_one_verified_home_before_optional_lock(actuator_machine, lock):
    material, objects, calls, fault, guard = actuator_machine
    material._recovery_actuator_stroke(lock, guard)
    assert calls == ['home', 'zero'] + (['post'] if lock else []) + ['wait', 'disable']


@pytest.mark.parametrize('lock', [True, False])
def test_failed_homing_never_sends_post_stroke(actuator_machine, lock):
    material, objects, calls, fault, guard = actuator_machine
    fault['home'] = True
    with pytest.raises(ValueError, match='endstop not reached'):
        material._recovery_actuator_stroke(lock, guard)
    assert calls == ['home', 'disable']


def test_post_stroke_failure_is_not_retried(actuator_machine):
    material, objects, calls, fault, guard = actuator_machine
    fault['post'] = True
    with pytest.raises(ValueError, match='post move failed'):
        material._recovery_actuator_stroke(True, guard)
    assert calls == ['home', 'zero', 'post', 'disable']


def test_cleanup_failure_preserves_original_error(actuator_machine):
    material, objects, calls, fault, guard = actuator_machine
    fault.update(home=True, disable=True)
    with pytest.raises(ValueError, match='endstop not reached'):
        material._recovery_actuator_stroke(True, guard)
    assert calls == ['home', 'disable']


def test_owner_change_prevents_post_stroke_and_cleanup_commands(actuator_machine):
    material, objects, calls, fault, guard = actuator_machine
    fault['owner'] = True
    with pytest.raises(ValueError, match='owner changed'):
        material._recovery_actuator_stroke(True, guard)
    assert calls == ['home']


def test_missing_actuator_refuses_without_motion(actuator_machine):
    material, objects, calls, fault, guard = actuator_machine
    del objects['echelon_stepper trans_stepper']
    with pytest.raises(ValueError, match='actuator is unavailable'):
        material._recovery_actuator_stroke(True, guard)
    assert calls == []


def coupling_command(material, objects, calls, lock=True):
    material.session_id='test-session'; material._command_generation=0
    material._cancellation()._print_cancel_unresolved=lambda: False
    material.printer.is_shutdown=lambda: False
    material.printer.get_reactor=lambda: NS(monotonic=lambda: 0.)
    saved={'fail_flag':0}
    objects['save_variables']=NS(get_status=lambda now: {'variables':saved})
    objects['filament_switch_sensor sensor_b']=NS(get_status=lambda now: {'filament_detected':True})
    objects['custom_hall']=NS(get_status=lambda now: {'Raw':4500.})
    def script(value):
        calls.append(value)
        saved['fail_flag']=int(value.rsplit('=',1)[1])
    objects['gcode'].run_script_from_command=script
    material.printer.invoke_shutdown=lambda reason: calls.append('shutdown: '+reason)
    fields={'LOCK':int(lock),'SESSION':material.session_id,'GENERATION':0}
    gcmd=NS(get=lambda name, default=None:fields.get(name,default),
            get_int=lambda name, default=None, **kwargs:fields.get(name, default), error=ValueError)
    return gcmd,saved


@pytest.mark.parametrize('lock', [True,False])
def test_standalone_coupling_command_preserves_successful_disable_timing(actuator_machine,lock):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls,lock)
    material.cmd_COUPLING_STROKE(command)
    assert calls==['home','zero']+(['post'] if lock else [])+['wait']
    assert saved['fail_flag']==0  # Successful LOCK/UNLOCK macro still owns disable.


@pytest.mark.parametrize('lock', [True,False])
def test_standalone_homing_failure_is_live_without_post_stroke(actuator_machine,lock):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls,lock)
    fault['home']=True
    with pytest.raises(ValueError,match='endstop not reached'):
        material.cmd_COUPLING_STROKE(command)
    assert calls==['home','disable']
    assert material._command_generation == 1
    assert saved['fail_flag']==(-2 if lock else -3)


@pytest.mark.parametrize('reason', ['fault','quick_stop','owner','generation'])
@pytest.mark.parametrize('retry', [0, 1])
def test_standalone_coupling_refuses_before_motion(actuator_machine,reason,retry):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls)
    original = command.get_int
    command.get_int = lambda name, default=None, **kw: retry if name == 'RETRY' else original(name, default, **kw)
    if reason=='fault': saved['fail_flag']=-3
    if reason=='quick_stop': material.printer.quick_stop_flag=True
    if reason=='owner': objects['openace']=object()
    if reason=='generation': material._command_generation=1
    with pytest.raises(ValueError): material.cmd_COUPLING_STROKE(command)
    assert calls==[]


def test_standalone_failure_does_not_require_diagnostic_storage(actuator_machine):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls)
    fault['home']=True
    def failed_write(value): raise OSError('disk failed')
    objects['gcode'].run_script_from_command=failed_write
    with pytest.raises(ValueError,match='endstop not reached'):
        material.cmd_COUPLING_STROKE(command)
    assert calls == ['home','disable']
    assert saved['fail_flag'] == -2
    assert 'post' not in calls


def test_standalone_generation_change_during_home_prevents_post_motion(actuator_machine):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls)
    original=objects['homing'].manual_home
    def changed(*args):
        original(*args)
        material._command_generation+=1
    objects['homing'].manual_home=changed
    with pytest.raises(ValueError,match='invalidated'):
        material.cmd_COUPLING_STROKE(command)
    assert calls==['home'] and saved['fail_flag']==0


def test_standalone_fault_authority_does_not_depend_on_disk_readback(actuator_machine):
    material, objects, calls, fault, _=actuator_machine
    command,saved=coupling_command(material,objects,calls)
    fault['home']=True
    objects['gcode'].run_script_from_command=lambda value: None
    with pytest.raises(ValueError,match='endstop not reached'):
        material.cmd_COUPLING_STROKE(command)
    assert saved['fail_flag']==-2
    assert calls==['home','disable']
    assert material._command_generation == 1

@pytest.mark.parametrize('retry', [1, 2, 3, 4])
def test_lock_confirmation_uses_stock_absolute_move(actuator_machine, retry):
    material, objects, calls, fault, _ = actuator_machine
    command, saved = coupling_command(material, objects, calls)
    original = command.get_int
    command.get_int = lambda name, default=None, **kw: retry if name == 'RETRY' else original(name, default, **kw)
    objects['gcode'].run_script_from_command = calls.append
    material.cmd_COUPLING_STROKE(command)
    assert calls == ['ECHELON_STEPPER STEPPER=trans_stepper SPEED=10 MOVE=%d' % (-125-retry*10), 'wait']
    assert saved['fail_flag'] == 0


@pytest.mark.parametrize('disable_fails', [False, True])
def test_lock_confirmation_driver_error_retires_remaining_attempt(actuator_machine, disable_fails):
    material, objects, calls, fault, _ = actuator_machine
    command, saved = coupling_command(material, objects, calls)
    original = command.get_int
    command.get_int = lambda name, default=None, **kw: 1 if name == 'RETRY' else original(name, default, **kw)
    fault['disable'] = disable_fails
    def move(script):
        calls.append(script)
        raise ValueError('driver move failed')
    objects['gcode'].run_script_from_command = move
    with pytest.raises(ValueError, match='driver move failed'):
        material.cmd_COUPLING_STROKE(command)
    assert saved['fail_flag'] == -2 and material._command_generation == 1
    with pytest.raises(ValueError):
        material.cmd_COUPLING_STROKE(command)
    assert len(calls) == 2 and calls[-1] == 'disable'


def test_lock_confirmation_error_after_owner_change_does_not_disable(actuator_machine):
    material, objects, calls, fault, _ = actuator_machine
    command, saved = coupling_command(material, objects, calls)
    original = command.get_int
    command.get_int = lambda name, default=None, **kw: 1 if name == 'RETRY' else original(name, default, **kw)
    def move(script):
        calls.append(script)
        material._command_generation += 1
        raise ValueError('driver move failed')
    objects['gcode'].run_script_from_command = move
    with pytest.raises(ValueError, match='driver move failed'):
        material.cmd_COUPLING_STROKE(command)
    assert len(calls) == 1 and 'disable' not in calls
    assert saved['fail_flag'] == 0 and material._command_generation == 1


@pytest.mark.parametrize('delay', [0., .7, 1.8, None])
def test_lock_report_settles_before_stock_retry_decision(actuator_machine, delay):
    material, objects, calls, fault, unused = actuator_machine
    command, saved = coupling_command(material, objects, calls)
    clock, observations = [0.], []
    def pause(deadline): observations.append(deadline);clock[0]=deadline
    material.printer.get_reactor=lambda: NS(monotonic=lambda:clock[0],pause=pause)
    objects['filament_switch_sensor sensor_b']=NS(get_status=lambda now:{'filament_detected':delay is not None and now+1e-9>=delay})
    material.cmd_COUPLING_STROKE(command)
    assert calls==['home','zero','post','wait']
    assert clock[0]==pytest.approx(2. if delay is None else delay,abs=.051)
    assert saved['fail_flag']==0 and material._command_generation==0
    if delay==0:assert observations==[]
    elif delay is not None:assert len(observations)>1


def test_lock_report_wait_honors_cancel_without_adjustment(actuator_machine):
    material, objects, calls, fault, unused=actuator_machine
    command,saved=coupling_command(material,objects,calls)
    clock=[0.]
    def pause(deadline):clock[0]=deadline;material._command_generation+=1
    material.printer.get_reactor=lambda:NS(monotonic=lambda:clock[0],pause=pause)
    objects['filament_switch_sensor sensor_b']=NS(get_status=lambda now:{'filament_detected':False})
    with pytest.raises(ValueError,match='invalidated'):
        material.cmd_COUPLING_STROKE(command)
    assert calls==['home','zero','post','wait'] and saved['fail_flag']==0


@pytest.mark.parametrize('lock', [True, False])
@pytest.mark.parametrize('extra_fault', [None, 'owner', 'quick_stop', 'shutdown', 'generation'])
def test_admitted_coupling_finishes_on_normal_stop_only(actuator_machine, lock, extra_fault):
    material, objects, calls, fault, _ = actuator_machine
    command, saved = coupling_command(material, objects, calls, lock)
    original = objects['homing'].manual_home
    def cancel(*args):
        original(*args)
        cancellation = material._cancellation()
        cancellation._coupling_finish_generation = material._command_generation
        material._command_generation += 1
        cancellation._print_cancel = {'state': 'pending', 'phase': 'stopping'}
        if extra_fault == 'owner': objects['openace'] = object()
        if extra_fault == 'quick_stop': material.printer.quick_stop_flag = True
        if extra_fault == 'shutdown': material.printer.is_shutdown = lambda: True
        if extra_fault == 'generation': material._command_generation += 1
    objects['homing'].manual_home = cancel
    with pytest.raises(ValueError):
        material.cmd_COUPLING_STROKE(command)
    if extra_fault is None:
        assert calls == ['home', 'zero'] + (['post'] if lock else []) + ['wait', 'disable']
    else:
        assert calls == ['home']
    assert saved['fail_flag'] == 0


def test_stop_during_admitted_lock_adjustment_drains_and_disables(actuator_machine):
    material, objects, calls, fault, _ = actuator_machine
    command, saved = coupling_command(material, objects, calls)
    original = command.get_int
    command.get_int = lambda name, default=None, **kw: 1 if name == 'RETRY' else original(name, default, **kw)
    def move(script):
        calls.append(script)
        cancellation = material._cancellation()
        cancellation._coupling_finish_generation = material._command_generation
        material._command_generation += 1
        cancellation._print_cancel = {'state': 'pending', 'phase': 'stopping'}
    objects['gcode'].run_script_from_command = move
    with pytest.raises(ValueError, match='invalidated'):
        material.cmd_COUPLING_STROKE(command)
    assert calls == ['ECHELON_STEPPER STEPPER=trans_stepper SPEED=10 MOVE=-135', 'wait', 'disable']
    assert saved['fail_flag'] == 0
