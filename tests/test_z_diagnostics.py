"""Safety boundaries of optional diagnostics; hardware repeatability is untested."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wmp_z_diagnostics', ROOT / 'klipper_extras/wmp_z_diagnostics.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Gcmd:
    error = ValueError

    def __init__(self):
        self.messages = []

    def respond_info(self, message):
        self.messages.append(message)


def harness(state='standby', paused=False, fail_home=False):
    calls = []
    z = {'endstop_pin': 'PD2', 'homing_positive_dir': True,
         'position_endstop': 300., 'homing_retract_dist': 2.}
    settings = {'printer': {'kinematics': 'corexy'}, 'stepper_z': z}
    def status(value):
        return SimpleNamespace(get_status=lambda now: value)
    def native_home(command):
        calls.append(('native_home', command))
        if fail_home:
            raise ValueError('No endstop trigger')
    objects = {
        'gcode': SimpleNamespace(
            register_command=lambda *a, **kw: calls.append(('register', a[0])),
            run_script_from_command=lambda s: calls.append(('script', s)),
            create_gcode_command=lambda *a: a),
        'toolhead': SimpleNamespace(wait_moves=lambda: calls.append(('wait',))),
        'homing': SimpleNamespace(cmd_G28=native_home),
        'print_stats': status({'state': state}),
        'pause_resume': status({'is_paused': paused}),
        'configfile': status({'settings': settings}),
        'output_pin LEVELING': status({'value': 1}),
        'output_pin GANTRY': status({'value': 1}),
    }
    printer = SimpleNamespace(lookup_object=lambda key: objects[key],
                              get_reactor=lambda: SimpleNamespace(monotonic=lambda: 0))
    diag = module.load_config(SimpleNamespace(get_printer=lambda: printer))
    snapshots = iter([
        {'homed_axes': 'xyz', 'z_commanded': 10., 'z_mcu_steps': 100,
         'step_distance': .000625},
        {'homed_axes': 'xyz', 'z_commanded': 300., 'z_mcu_steps': 463900},
    ])
    diag._snapshot = lambda: next(snapshots)
    return diag, calls, objects, settings


def test_loading_and_snapshot_do_not_issue_motion_commands():
    diag, calls, _, _ = harness()
    assert calls == [('register', 'WMP_Z_SNAPSHOT'), ('register', 'WMP_Z_MAX_TEST')]
    diag.cmd_snapshot(Gcmd())
    assert not any(c[0] in ('script', 'native_home') for c in calls)


@pytest.mark.parametrize('state,paused', [('printing', False), ('paused', True), ('standby', True), ('error', False)])
def test_active_or_paused_print_rejected_before_any_commands(state, paused):
    diag, calls, _, _ = harness(state, paused)
    with pytest.raises(ValueError, match='idle printer'):
        diag.cmd_max_test(Gcmd())
    assert all(c[0] == 'register' for c in calls)


def test_native_z_only_bypasses_gpio_pulses_xy_and_tool_macros():
    diag, calls, _, _ = harness()
    diag.cmd_max_test(Gcmd())
    assert [c for c in calls if c[0] in ('script', 'native_home')] == [
        ('script', 'BED_MESH_CLEAR'),
        ('script', 'STEPPER_DIAG_ENABLE CHIP=stepper_z'),
        ('native_home', ('G28', 'G28 Z', {'Z': '0'})),
        ('script', 'STEPPER_DIAG_DISABLE CHIP=stepper_z'),
    ]
    assert diag.phase == 'complete' and not diag.active
    # Reconstruct previous coordinates from step delta, not new Z300 label.
    assert diag.last_result['max_z_in_previous_frame'] == pytest.approx(299.875)


def test_native_home_failure_restores_driver_mode_without_return_motion():
    diag, calls, _, _ = harness(fail_home=True)
    with pytest.raises(ValueError, match='No endstop'):
        diag.cmd_max_test(Gcmd())
    assert calls[-1] == ('script', 'STEPPER_DIAG_DISABLE CHIP=stepper_z')
    assert diag.phase == 'failed' and not diag.active and diag.last_result is None


@pytest.mark.parametrize('field,value', [('endstop_pin', 'probe:z_virtual_endstop'), ('homing_positive_dir', False), ('position_endstop', 0)])
def test_incompatible_homing_configuration_rejected(field, value):
    diag, calls, _, settings = harness()
    settings['stepper_z'][field] = value
    with pytest.raises(ValueError, match='inspected Wondermaker'):
        diag.cmd_max_test(Gcmd())
    assert all(c[0] == 'register' for c in calls)


def test_active_external_leveling_control_rejected_without_changing_pin():
    diag, calls, objects, _ = harness()
    objects['output_pin LEVELING'] = SimpleNamespace(get_status=lambda now: {'value': 0})
    with pytest.raises(ValueError, match='LEVELING'):
        diag.cmd_max_test(Gcmd())
    assert all(c[0] == 'register' for c in calls)
