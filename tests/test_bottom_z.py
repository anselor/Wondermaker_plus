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
        if fail_home: raise ValueError('No endstop trigger')
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
    printer = NS(lookup_object=lambda name: objects[name],
                 register_event_handler=lambda name, cb: events.setdefault(name, []).append(cb),
                 get_reactor=lambda: NS(monotonic=lambda: 0),
                 invoke_shutdown=lambda why: calls.append(('shutdown', why)))
    extra = module.load_config(NS(get_printer=lambda: printer))
    gcmd = NS(error=ValueError, respond_info=lambda s: calls.append(('message', s)))
    return extra, gcmd, calls, objects, events, callbacks, th, settings


def rail(name): return NS(get_steppers=lambda: [NS(get_name=lambda: name)])


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


@pytest.mark.parametrize('bad', ['active_print', 'paused', 'geometry', 'LEVELING', 'GANTRY'])
def test_rejection_shuts_down_before_any_motion(bad):
    x, cmd, calls, objects, events, callbacks, th, settings = harness()
    if bad == 'active_print':
        objects['print_stats'].get_status(0)['state'] = 'printing'
        objects['gcode_macro START_PRINT'].get_status(0)['print_body_ready'] = True
    elif bad == 'paused': objects['pause_resume'].get_status(0)['is_paused'] = True
    elif bad == 'geometry': settings['stepper_z']['endstop_pin'] = 'probe:z_virtual_endstop'
    else: objects['output_pin ' + bad].get_status(0)['value'] = 0
    with pytest.raises(ValueError): x.cmd_home(cmd)
    assert not any(c[0] in ('native', 'script') for c in calls)
    assert calls[-1][0] == 'shutdown'


def test_startup_printing_state_can_establish_z_before_print_body():
    x, cmd, calls, objects, *_ = harness()
    objects['print_stats'].get_status(0)['state'] = 'printing'
    x.cmd_home(cmd)
    assert x.valid
