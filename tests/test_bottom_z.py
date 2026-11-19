"""Production bottom home: native ordering, genuine reference and failure containment."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wmp_recovery', ROOT / 'klipper_extras/wmp_recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def harness(fail_home=False):
    events, calls = {}, []
    th = {'homed_axes': ''}
    settings = {'printer': {'kinematics': 'corexy'}, 'stepper_z': {
        'endstop_pin': 'PD2', 'homing_positive_dir': True,
        'position_endstop': 300., 'homing_retract_dist': 2.}}
    def status(d): return NS(get_status=lambda now: d)
    def home(gcmd):
        calls.append(('native', gcmd))
        events['homing:home_rails_begin'][0](None, [rail('stepper_z')])
        if fail_home: raise ValueError('No endstop trigger')
        events['homing:home_rails_end'][0](None, [rail('stepper_z')])
        th['homed_axes'] = 'z'
    callbacks = []
    objects = {
        'gcode': NS(register_command=lambda *a, **kw: calls.append(('register', a[0])),
                    create_gcode_command=lambda *a: a,
                    run_script_from_command=lambda s: calls.append(('script', s))),
        'toolhead': NS(get_status=lambda now: th, wait_moves=lambda: calls.append(('wait',))),
        'homing': NS(cmd_G28=home),
        'stepper_enable': NS(lookup_enable=lambda name: NS(register_state_callback=callbacks.append)),
        'print_stats': status({'state': 'standby'}), 'pause_resume': status({'is_paused': False}),
        'gcode_macro START_PRINT': status({'print_body_ready': False}),
        'configfile': status({'settings': settings}),
        'output_pin LEVELING': status({'value': 1}), 'output_pin GANTRY': status({'value': 1})}
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 command_error=ValueError,
                 register_event_handler=lambda name, cb: events.setdefault(name, []).append(cb),
                 get_reactor=lambda: NS(monotonic=lambda: 0),
                 invoke_shutdown=lambda why: calls.append(('shutdown', why)))
    extra = module.load_config(NS(get_printer=lambda: printer, getfloat=lambda name, default=None, **kwargs: default))
    gcmd = NS(error=ValueError, respond_info=lambda s: calls.append(('message', s)))
    return extra, gcmd, calls, objects, events, callbacks, th, settings


def rail(name, retract=2.):
    return NS(get_steppers=lambda: [NS(get_name=lambda: name)],
              get_homing_info=lambda: NS(retract_dist=retract))


def test_native_bottom_home_does_not_pulse_gpio_move_xy_or_return_up():
    x, cmd, calls, *_ = harness()
    assert not x.get_status(0)['z_reference_valid']
    assert all(c[0] == 'register' for c in calls)
    x.cmd_home(cmd)
    assert [c for c in calls if c[0] in ('native', 'script')] == [
        ('script', 'BED_MESH_CLEAR'), ('script', 'STEPPER_DIAG_ENABLE CHIP=stepper_z'),
        ('native', ('G28', 'G28 Z', {'Z': '0'})),
        ('script', 'STEPPER_DIAG_DISABLE CHIP=stepper_z')]
    assert x.get_status(0)['z_reference_valid'] and not x.active


def test_real_z_homing_events_and_motor_disable_control_reference_validity():
    x, cmd, calls, objects, events, callbacks, th, _ = harness()
    events['klippy:connect'][0]()
    th['homed_axes'] = 'xyz'  # synthetic coordinate assignment alone
    assert not x.get_status(0)['z_reference_valid']
    events['homing:home_rails_end'][0](None, [rail('stepper_x')])
    assert not x.valid
    events['homing:home_rails_end'][0](None, [rail('stepper_z')])
    assert x.get_status(0)['z_reference_valid']
    callbacks[0](0, False)  # includes individual SET_STEPPER_ENABLE, not just M84
    assert not x.get_status(0)['z_reference_valid']
    callbacks[0](1, True)
    assert not x.valid
    x.cmd_home(cmd)
    events['homing:home_rails_begin'][0](None, [rail('stepper_z')])
    assert not x.valid
    x.cmd_home(cmd)
    th['homed_axes'] = 'xy'
    assert not x.get_status(0)['z_reference_valid']
    events['klippy:shutdown'][0]()
    assert not x.valid
    fresh, *_ = harness()
    assert not fresh.valid


def test_failed_home_cleans_up_driver_and_shuts_down_independent_queued_motion():
    x, cmd, calls, *_ = harness(fail_home=True)
    with pytest.raises(ValueError, match='No endstop'): x.cmd_home(cmd)
    assert [c[0] for c in calls][-2:] == ['script', 'shutdown']
    assert calls[-2] == ('script', 'STEPPER_DIAG_DISABLE CHIP=stepper_z')
    assert not x.valid and not x.active


@pytest.mark.parametrize('bad', ['active_print', 'paused', 'geometry'])
def test_preflight_rejection_does_not_shutdown_or_issue_motion(bad):
    x, cmd, calls, objects, events, callbacks, th, settings = harness()
    if bad == 'active_print':
        objects['print_stats'].get_status(0)['state'] = 'printing'
        objects['gcode_macro START_PRINT'].get_status(0)['print_body_ready'] = True
    elif bad == 'paused': objects['pause_resume'].get_status(0)['is_paused'] = True
    elif bad == 'geometry': settings['stepper_z']['endstop_pin'] = 'probe:z_virtual_endstop'
    else: objects['output_pin ' + bad].get_status(0)['value'] = 0
    with pytest.raises(ValueError): x.cmd_home(cmd)
    assert not any(c[0] in ('native', 'script') for c in calls)
    assert not any(c[0] == 'shutdown' for c in calls)


def test_startup_printing_state_can_establish_z_before_print_body():
    x, cmd, calls, objects, *_ = harness()
    objects['print_stats'].get_status(0)['state'] = 'printing'
    x.cmd_home(cmd)
    assert x.valid


def test_bottom_home_leaves_native_seek_retract_order_to_vendor():
    x, cmd, calls, objects, events, _, th, _ = harness()
    assert 'homing:homing_move_end' not in events
    def native_home(command):
        events['homing:home_rails_begin'][0](None, [rail('stepper_z')])
        calls.extend([('native_seek',), ('native_retract',), ('native_seek',)])
        events['homing:home_rails_end'][0](None, [rail('stepper_z')])
        th['homed_axes'] = 'z'
    objects['homing'].cmd_G28 = native_home
    x.cmd_home(cmd)
    assert [c for c in calls if c[0].startswith('native_')] == [
        ('native_seek',), ('native_retract',), ('native_seek',)]
    assert x.valid and not x.active

@pytest.mark.parametrize('running,state,review,expected', [
    (False, 'idle', False, ''),
    (True, 'idle', False, 'Calibration command is running'),
    (False, 'save_review', True, ''),
    (False, 'editing', False, ''),
    (False, 'unknown', False, ''),
    (False, 'save_acknowledged', False, ''),
    (True, 'save_review', True, 'Calibration command is running'),
])
def test_calibration_active_reason_identifies_actual_flag_without_changing_policy(running, state, review, expected):
    extra, _, calls, *_ = harness()
    extra.calibration.active = running
    editor = extra.calibration.probe_editor
    editor.state, editor.save_review_required = state, review
    editor.error = 'Previous review text'  # Reason describes the gate, not a cached error.
    before = list(calls)
    result = extra.get_status(0)
    assert result['calibration_active'] == (running or editor.busy())
    assert result['calibration_active_reason'] == expected
    assert bool(expected) == result['calibration_active']
    assert calls == before and editor.state == state and editor.save_review_required == review

@pytest.mark.parametrize('state', ['editing', 'failed', 'unknown', 'save_review'])
def test_live_manual_probe_is_machine_active_independently_of_editor_ui_state(state):
    extra, _, _, objects, *_ = harness()
    editor = extra.calibration.probe_editor
    editor.state, editor.save_review_required = state, state == 'save_review'
    objects['manual_probe'] = NS(status={'is_active': True})
    status = extra.get_status(0)
    assert status['calibration_active'] is True
    assert status['calibration_active_reason'] == 'Manual probe calibration is active: state=' + state
    objects['manual_probe'].status['is_active'] = False
    status = extra.get_status(0)
    assert status['calibration_active'] is False and status['calibration_active_reason'] == ''
    assert not editor.busy()  # A finished helper leaves only nonblocking UI history.


def test_reentrant_bottom_home_refusal_preserves_running_owner():
    extra, command, calls, *_ = harness()
    extra.active = True
    with pytest.raises(ValueError, match='already running'):
        extra.cmd_home(command)
    assert extra.active
    assert not any(call[0] in ('shutdown', 'native', 'script') for call in calls)


def test_bottom_home_preflight_preserves_existing_reference():
    extra, command, calls, objects, *_ = harness()
    extra.valid = True
    objects['pause_resume'].get_status(0)['is_paused'] = True
    with pytest.raises(ValueError, match='pause_resume'):
        extra.cmd_home(command)
    assert extra.valid
    assert not extra.active


@pytest.mark.parametrize('endstop,retract', [(295., 1.), (310., 3.)])
def test_native_configured_travel_and_retract_are_not_magic_constants(endstop, retract):
    extra, command, calls, objects, events, callbacks, th, settings = harness()
    settings['stepper_z'].update(position_endstop=endstop, position_max=endstop,
                                 homing_retract_dist=retract)
    extra.cmd_home(command)
    assert extra.valid


@pytest.mark.parametrize('name', ['LEVELING', 'GANTRY'])
@pytest.mark.parametrize('outcome', ['confirmed', 'ignored', 'active_calibration'])
def test_idle_pin_restoration_requires_readback_and_no_other_calibration(name, outcome):
    extra, command, calls, objects, *_ = harness()
    pin = objects['output_pin ' + name].get_status(0)
    pin['value'] = 0
    run = objects['gcode'].run_script_from_command
    def dispatch(script):
        run(script)
        if outcome == 'confirmed' and script == 'SET_PIN PIN=%s VALUE=1' % name:
            pin['value'] = 1
    objects['gcode'].run_script_from_command = dispatch
    if outcome == 'active_calibration': extra.calibration.active = True
    if outcome == 'confirmed':
        extra.cmd_home(command)
        assert extra.valid
    else:
        with pytest.raises(ValueError, match='not confirmed|active calibration'):
            extra.cmd_home(command)
        assert not any(call[0] in ('native', 'shutdown') for call in calls)
    assert not any('VALUE=0' in str(call) for call in calls)


def test_pin_reset_cannot_change_trigger_during_material_operation():
    extra, command, calls, objects, *_ = harness()
    objects['output_pin LEVELING'].get_status(0)['value'] = 0
    objects['wm_material'] = NS(_material_operation_active=lambda name: name == 'toolhead_operation')
    with pytest.raises(ValueError, match='active calibration or material operation'):
        extra.cmd_home(command)
    assert not any(call[0] in ('script', 'native', 'shutdown') for call in calls)


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf'), 400.])
def test_invalid_native_retract_refuses_without_motion_or_shutdown(value):
    extra, command, calls, objects, events, callbacks, th, settings = harness()
    settings['stepper_z']['homing_retract_dist'] = value
    with pytest.raises(ValueError, match='finite native Z bounds'):
        extra.cmd_home(command)
    assert not any(call[0] in ('script', 'native', 'shutdown') for call in calls)


def retained_bottom_machine(deltas=(-10381, -9), fail_pass=None, halt_increments=(50000,50000)):
    """Actual retained homing_move/home_rails; fake only transport and mechanics."""
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/homing.py'
    spec = importlib.util.spec_from_file_location('retained_bottom_homing', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    extra, command, calls, objects, events, _, axes, _ = harness()
    position, counter, phase = [12., 23., 70., 4.], [0], [-1]
    moves, seeks, sets = [], [], []
    step = NS(get_name=lambda: 'stepper_z', get_step_dist=lambda: 1/1600.,
              get_commanded_position=lambda: position[2],
              calc_position_from_coord=lambda p: p[2],
              get_mcu_position=lambda: counter[0],
              get_past_mcu_position=lambda t: counter[0]-deltas[phase[0]])
    def start(*a, **kw):
        phase[0] += 1
        return NS(wait=lambda: True)
    end = NS(get_steppers=lambda: [step], home_zero=lambda: None,
             home_start=start, home_wait=lambda t: 0 if phase[0] == fail_pass else 1.)
    zrail = NS(get_steppers=lambda: [step], get_endstops=lambda: [(end, 'z')],
               get_homing_info=lambda: NS(speed=40., retract_speed=40.,
                                         second_homing_speed=2., retract_dist=2.))
    def set_position(p, **kw):
        position[:] = p; sets.append(list(p))
    def move(p, speed):
        moves.append((list(position), list(p), speed)); position[:] = p
    def drip(p, speed, completion):
        seeks.append((list(position), list(p), speed)); counter[0] += halt_increments[phase[0]]
    def event(name, *args):
        for cb in events.get(name, []): cb(*args)
        if name == 'homing:home_rails_end': axes['homed_axes'] = 'z'
    kin = NS(get_steppers=lambda: [step],
             calc_position=lambda values: [position[0], position[1], values['stepper_z']],
             home=lambda state: state.home_rails([zrail], [None,None,-157.5,None],
                                                 [None,None,300.,None]))
    objects['toolhead'] = NS(get_position=lambda: list(position), set_position=set_position,
        move=move, drip_move=drip, dwell=lambda t: None, flush_step_generation=lambda: None,
        get_kinematics=lambda: kin, get_last_move_time=lambda: 1., wait_moves=lambda: None,
        get_status=lambda t: axes)
    objects['stepper_enable'].motor_off = lambda: calls.append(('motor_off',))
    extra.printer.send_event = event
    extra.printer.get_start_args = lambda: {}
    native = vendor.PrinterHoming.__new__(vendor.PrinterHoming)
    native.printer = extra.printer
    native.test_endstop = end
    objects['homing'] = native
    objects['gcode'].create_gcode_command = lambda *args: NS(get=lambda key, default=None: '0' if key=='Z' else default)
    return extra, command, vendor, native, moves, seeks, sets, position, calls


@pytest.mark.parametrize('negative', [-9, -10381, -19019])
def test_retained_bottom_seeks_retract_away_after_negative_nominal_history(negative):
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine((negative,negative))
    original = vendor.HomingMove
    extra.cmd_home(cmd)
    assert vendor.HomingMove is original
    assert [s[2] for s in seeks] == [40., 2.]
    assert len(moves) == 1 and moves[0][0][2] == 300. and moves[0][1][2] == 298.
    assert pos == [12.,23.,300.,4.]
    assert extra.valid and not extra.active


def test_retained_bottom_preserves_positive_overshoot_and_offsets():
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine((16,8))
    extra.cmd_home(cmd)
    assert moves[0][0][2] == pytest.approx(300.01)
    assert moves[0][1][2] == 298.
    assert pos == [12.,23.,300.005,4.]


@pytest.mark.parametrize('failed', [0,1])
def test_retained_bottom_error_does_not_normalize_or_continue(failed):
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine(fail_pass=failed)
    original = vendor.HomingMove
    with pytest.raises(ValueError, match='Z-axis homing error'):
        extra.cmd_home(cmd)
    assert vendor.HomingMove is original and not extra.active and not extra.valid
    assert len(moves) == failed and len(seeks) == failed+1
    assert pos[2] < 300.  # Failed native return never anchored to nominal.
    assert any(c[0]=='shutdown' for c in calls)


def test_retained_ordinary_homing_is_unmodified_after_scoped_home():
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine((-10381,-9))
    # Outside the managed scope, stock's invalid negative correction is visible.
    native.cmd_G28(NS(get=lambda key, default=None: '0' if key=='Z' else default))
    assert moves[0][0][2] == pytest.approx(293.511875)
    assert moves[0][1][2] == 298.


@pytest.mark.parametrize('mode', ['probe', 'inactive', 'unchecked', 'release'])
def test_scoped_factory_leaves_unrelated_move_semantics_unchanged(mode):
    results=[]
    for scoped in (False, True):
        extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine()
        extra.active = mode != 'inactive'
        kwargs = {'probe_pos': mode=='probe', 'triggered': mode!='release',
                  'check_triggered': mode!='unchecked'}
        def run():
            move=vendor.HomingMove(extra.printer, [(native.test_endstop,'z')])
            result=move.homing_move([12.,23.,300.,4.],40.,**kwargs)
            return list(pos), result, move.stepper_positions[0].trig_pos
        if scoped:
            with extra._native_bottom_reference(native): results.append(run())
        else: results.append(run())
    assert results[0] == results[1]


@pytest.mark.parametrize('increments,expected', [((50000,0),'z'), ((50000,1),None)])
def test_normalized_final_reference_uses_actual_halt_for_no_movement(increments,expected):
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine(halt_increments=increments)
    observed=[]
    original=vendor.HomingMove.check_no_movement
    def check(move):
        answer=original(move)
        observed.append((answer,move.stepper_positions[0]))
        return answer
    vendor.HomingMove.check_no_movement=check
    extra.cmd_home(cmd)
    assert len(observed)==1
    answer,position=observed[0]
    assert answer==expected
    assert position.trig_pos==position.halt_pos
    assert (position.start_pos==position.halt_pos)==(expected=='z')
    # Retained COUNT=0 disables stock retries/refusal on this diagnostic;
    # our correction changes its evidence to actual halt, not that policy.
    assert len(seeks)==2 and len(moves)==1 and extra.valid


def test_native_end_event_error_never_normalizes_failed_move():
    extra, cmd, vendor, native, moves, seeks, sets, pos, calls = retained_bottom_machine()
    original_factory=vendor.HomingMove
    original_event=extra.printer.send_event
    observed=[]
    def event(name,*args):
        original_event(name,*args)
        if name=='homing:homing_move_end':
            observed.append((list(pos),args[0].stepper_positions[0].trig_pos))
            raise ValueError('injected end-event failure')
    extra.printer.send_event=event
    with pytest.raises(ValueError,match='injected end-event failure'):
        extra.cmd_home(cmd)
    assert len(observed)==1 and observed[0][0][2]==pytest.approx(293.511875)
    assert pos==observed[0][0]
    assert observed[0][1]==60381  # raw nominal history, not rewritten to50000 halt
    assert not moves and len(seeks)==1
    assert vendor.HomingMove is original_factory
    assert not extra.valid and not extra.active
