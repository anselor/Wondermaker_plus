"""Cancellation cleanup restores tuning and only parks a verified machine."""
from types import SimpleNamespace as NS
import pytest
from test_offset_snapshot import machine,OFFSETS
from test_calibration_tickets import ticket
from test_calibration_cancel_ingress import Request


def rig():
    p,gcode,runner,stored,writes=machine()
    stored.update(current_extruder=1,fail_flag=0)
    attachment=lambda now:({'state':'empty','head':''} if stored['current_extruder']==99
                           else {'state':'attached','head':'h1'})
    p.objects['wm_material']=NS(_attachment=attachment)
    p.objects['toolhead'].wait_moves=lambda:None
    def park(cmd):
        stored['current_extruder']=99
    gcode.commands['PARK_CURRENT_TOOL']=park
    runner.cmd_run(ticket(runner,'G28',1))
    return p,gcode,runner,stored,writes


def cancel_stage(runner,gcode,script='RAPID_MODE T=1', error='cancellation requested'):
    original=gcode.run_script_from_command
    def run(command):
        original(command)
        if command==script:runner.handle_cancel(Request(runner))
    gcode.run_script_from_command=run
    command=ticket(runner,script,1,1)
    command.error=runner.printer.command_error  # Klipper GCodeCommand uses this same error class.
    with pytest.raises(runner.printer.command_error,match=error):
        runner.cmd_run(command)
    return runner.attempt_status()['cancel_cleanup']


def test_cancel_restores_all_offsets_then_parks_once():
    p,gcode,runner,stored,writes=rig()
    def change(cmd):stored['t1_offset']=(8.,8.,8.)
    gcode.commands['RAPID_MODE']=change
    result=cancel_stage(runner,gcode)
    assert result=={'state':'complete','offsets':'restored','park':'parked','error':''}
    assert {key:stored[key] for key in OFFSETS}==OFFSETS
    assert [key for key,_ in writes]==list(OFFSETS)
    restore_at=next(i for i,s in enumerate(gcode.sent) if s.startswith('SAVE_VARIABLE'))
    assert restore_at < gcode.sent.index('PARK_CURRENT_TOOL')
    runner._cleanup_cancelled_attempt(runner._current_attempt)
    assert gcode.sent.count('PARK_CURRENT_TOOL')==1 and len(writes)==4
    assert not p.shutdown
    assert runner.nozzle_scrub.phase=='ended'


@pytest.mark.parametrize('condition',['unhomed','z_invalid','fault','unknown_attachment','wrong_head'])
def test_unverified_machine_is_left_in_place_without_homing(condition):
    p,gcode,runner,stored,writes=rig()
    if condition=='unhomed':p.homed='xy'
    elif condition=='z_invalid':p.z_reference_valid=False
    elif condition=='fault':gcode.commands['M400']=lambda cmd:stored.update(fail_flag=-3)
    elif condition=='wrong_head':stored['current_extruder']=2
    else:p.objects['wm_material']._attachment=lambda now:{'state':'unknown','head':''}
    # A simultaneous coupling fault must not be hidden by the Cancel request.
    result=cancel_stage(runner,gcode,'M400', error='Tool change failed' if condition=='fault' else 'cancellation requested')
    assert result['state']=='incomplete' and result['park']=='unconfirmed'
    assert 'PARK_CURRENT_TOOL' not in gcode.sent and gcode.sent.count('G28')==1
    assert not p.shutdown and writes==[]
    assert runner.nozzle_scrub.phase=='failed'


def test_already_docked_requires_no_motion():
    p,gcode,runner,stored,writes=rig();stored['current_extruder']=99
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='complete' and result['park']=='already_docked'
    assert 'PARK_CURRENT_TOOL' not in gcode.sent


def test_failed_offset_restore_does_not_claim_success_but_still_parks():
    p,gcode,runner,stored,writes=rig()
    gcode.commands['SAVE_VARIABLE']=lambda cmd:None
    gcode.commands['RAPID_MODE']=lambda cmd:stored.update(t1_offset=(8.,8.,8.))
    result=cancel_stage(runner,gcode)
    assert result['state']=='incomplete' and result['offsets']=='unconfirmed'
    assert result['park']=='parked' and 'could not be restored' in result['error']
    assert stored['t1_offset']==(8.,8.,8.) and not p.shutdown


def test_unconfirmed_dock_is_not_a_complete_cancel():
    p,gcode,runner,stored,writes=rig()
    gcode.commands['PARK_CURRENT_TOOL']=lambda cmd:None
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='incomplete' and 'did not confirm' in result['error']
    assert not p.shutdown


def test_heater_cleanup_without_tracker_is_reported_as_unconfirmed():
    p,gcode,runner,stored,writes=rig();runner._heater_ownership=None
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='incomplete' and 'heater' in result['error']


def test_dock_fault_is_not_hidden_by_empty_attachment():
    p,gcode,runner,stored,writes=rig()
    gcode.commands['PARK_CURRENT_TOOL']=lambda cmd:stored.update(current_extruder=99,fail_flag=-3)
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='incomplete' and result['park']=='unconfirmed'


def test_cleanup_cannot_replay_after_new_attempt():
    p,gcode,runner,stored,writes=rig();cancel_stage(runner,gcode,'M400')
    old=runner._current_attempt
    runner.cmd_run(ticket(runner,'G28',number=2))
    before=list(gcode.sent)
    runner._cleanup_cancelled_attempt(old)
    assert gcode.sent==before


def test_already_docked_cancel_waits_for_admitted_travel():
    p,gcode,runner,stored,writes=rig();stored['current_extruder']=99
    completed=[]
    p.objects['toolhead'].wait_moves=lambda:completed.append('motion completed')
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='complete' and completed==['motion completed']


def test_owner_change_during_motion_wait_prevents_cleanup_park():
    p,gcode,runner,stored,writes=rig()
    p.objects['toolhead'].wait_moves=lambda:p.objects.update(openace=object())
    result=cancel_stage(runner,gcode,'M400')
    assert result['state']=='incomplete' and 'owner changed' in result['error']
    assert 'PARK_CURRENT_TOOL' not in gcode.sent


def test_cancel_while_worker_is_held_finishes_on_serialized_callback():
    import contextlib
    p,gcode,runner,stored,writes=rig()
    callbacks=[]
    p.get_reactor=lambda:NS(monotonic=lambda:1.,register_callback=callbacks.append)
    gcode.get_mutex=lambda:contextlib.nullcontext()
    request=Request(runner);before=list(gcode.sent)
    runner.handle_cancel(request)
    assert gcode.sent==before and len(callbacks)==1
    callbacks[0](1.)
    assert runner.attempt_status()['cancel_cleanup']['state']=='complete'
    assert gcode.sent.count('PARK_CURRENT_TOOL')==1
    callbacks[0](1.)
    assert gcode.sent.count('PARK_CURRENT_TOOL')==1


def test_idle_cancel_callback_cannot_cleanup_a_new_attempt():
    import contextlib
    p,gcode,runner,stored,writes=rig()
    callbacks=[]
    p.get_reactor=lambda:NS(monotonic=lambda:1.,register_callback=callbacks.append)
    gcode.get_mutex=lambda:contextlib.nullcontext()
    runner.handle_cancel(Request(runner));assert len(callbacks)==1
    runner.cmd_run(ticket(runner,'G28',number=2))
    before=list(gcode.sent);callbacks[0](1.)
    assert gcode.sent==before and not runner.attempt_status().get('cancel_cleanup')


def test_idle_callback_owner_change_never_restores_or_parks():
    import contextlib
    p,gcode,runner,stored,writes=rig();callbacks=[]
    p.get_reactor=lambda:NS(monotonic=lambda:1.,register_callback=callbacks.append)
    gcode.get_mutex=lambda:contextlib.nullcontext()
    runner.handle_cancel(Request(runner));p.objects['openace']=object()
    before=list(gcode.sent);callbacks[0](1.)
    assert gcode.sent==before and writes==[]
    assert runner.attempt_status()['cancel_cleanup']['state']=='incomplete'
    assert not p.shutdown


def test_idle_callback_error_is_reported_without_shutdown():
    p,gcode,runner,stored,writes=rig();callbacks=[]
    p.get_reactor=lambda:NS(monotonic=lambda:1.,register_callback=callbacks.append)
    def unavailable():raise RuntimeError('mutex unavailable')
    gcode.get_mutex=unavailable
    runner.handle_cancel(Request(runner));callbacks[0](1.)
    assert runner.attempt_status()['cancel_cleanup']['state']=='incomplete'
    assert not p.shutdown


def test_repeated_idle_requests_schedule_only_one_cleanup_callback():
    import contextlib
    p,gcode,runner,stored,writes=rig();callbacks=[]
    p.get_reactor=lambda:NS(monotonic=lambda:1.,register_callback=callbacks.append)
    gcode.get_mutex=lambda:contextlib.nullcontext()
    for _ in range(10):runner.handle_cancel(Request(runner))
    assert len(callbacks)==1
    callbacks[0](1.)
    for _ in range(10):runner.handle_cancel(Request(runner))
    assert len(callbacks)==1 and gcode.sent.count('PARK_CURRENT_TOOL')==1


@pytest.mark.parametrize('failure', ['cancel', 'probe fault'])
def test_owned_mesh_unwind_clears_only_runtime_progress(failure):
    from contextlib import nullcontext
    p,gcode,runner,stored,writes=rig()
    macro=NS(variables={'bed_leveling':False,'unrelated':17})
    p.objects['gcode_macro G29']=macro
    # Isolate operation unwind; scoped producer rollback has separate tests.
    runner.checkpoints.stage=lambda *args:nullcontext()
    def mesh(cmd):
        macro.variables=dict(macro.variables,bed_leveling=True)
        if failure=='cancel':
            runner.handle_cancel(Request(runner))
            runner.check_cancel('before bed mesh finalization',runner.executing)
        raise p.command_error('probe fault')
    gcode.commands['G29']=mesh
    command=ticket(runner,'G29',1,1);command.error=p.command_error
    with pytest.raises(p.command_error,match='cancellation requested' if failure=='cancel' else 'probe fault'):
        runner.cmd_run(command)
    assert macro.variables=={'bed_leveling':False,'unrelated':17}
    assert not p.shutdown


@pytest.mark.parametrize('scope', ['other_command','unbound','replacement','not_executing','inactive','openace','AFC','missing_variable'])
def test_mesh_progress_cleanup_does_not_touch_another_owner(scope):
    p,gcode,runner,stored,writes=rig()
    macro=NS(variables={'bed_leveling':True,'unrelated':17})
    p.objects['gcode_macro G29']=macro
    attempt=runner._current_attempt
    runner.active=True;runner.executing=attempt
    command='G29'
    if scope=='other_command':command='M400'
    elif scope=='unbound':attempt=None
    elif scope=='replacement':attempt=dict(attempt)
    elif scope=='not_executing':runner.executing=None
    elif scope=='inactive':runner.active=False
    elif scope=='missing_variable':macro.variables={'unrelated':17}
    else:p.objects[scope]=object()
    before=macro.variables
    runner._clear_owned_mesh_progress(command,attempt)
    assert macro.variables is before


def test_already_docked_cancel_clears_transient_with_same_live_owner():
    p, gcode, runner, stored, writes = rig()
    stored.update(current_extruder=99, changing_tool=1, thr_number=4)
    p.objects['wm_material'].session_id = 'material-session'
    p.objects['wm_material']._command_generation = 0
    p.objects['wmp_recovery'].calibration = runner
    p.objects['gcode'] = gcode
    data = {'custom_hall': {'Raw': 5000},
            'filament_switch_sensor sensor_b': {'filament_detected': False},
            **{'filament_switch_sensor docked%d' % n: {'filament_detected': True} for n in range(4)}}
    for name, value in data.items(): p.objects[name] = NS(get_status=lambda now, value=value: value)
    result = cancel_stage(runner, gcode)
    assert result['state'] == 'complete' and result['toolchange'] == 'cleared'
    assert stored['changing_tool'] == 0
    assert ('changing_tool', '0') in writes
    assert 'PARK_CURRENT_TOOL' not in gcode.sent
