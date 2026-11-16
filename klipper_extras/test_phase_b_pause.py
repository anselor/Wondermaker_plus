"""Behavioral pause/presence regressions; no printer I/O."""
import io
from types import SimpleNamespace as NS
import pytest
from test_wm_material import (material, sequence_material, service_material,
                             paused_origin_material, filament_check, FakeCommand)


def test_brief_sensor_empty_does_not_revoke_confirmed_load(filament_check):
    obj, sensor, _ = filament_check
    sensor.detected = False
    assert obj._loaded_filament_status(10.)['h2']['state'] == 'empty'
    sensor.detected = True
    assert obj._loaded_filament_status(10.1)['h2']['state'] == 'loaded'
    sensor.detected = False
    obj._loaded_filament_status(11.)
    obj._loaded_filament_status(11.3)
    sensor.detected = True
    assert obj._loaded_filament_status(11.4)['h2']['state'] == 'empty'


def test_existing_profile_missing_presence_is_adopted_once(service_material):
    obj, objects, state = service_material
    state['filament_switch_sensor filament2']['filament_detected'] = True
    assert obj._loaded_filament_status(1)['h2']['state'] == 'loaded'
    obj._set_filament_loaded('h2', False)
    assert obj._loaded_filament_status(2)['h2']['state'] == 'empty'


def test_presence_write_failure_keeps_observation_without_poll_retries(filament_check, monkeypatch):
    obj, sensor, _ = filament_check
    calls = []
    def fail(flags):
        calls.append(flags)
        raise OSError('full disk')
    monkeypatch.setattr(obj, '_write_filament_flags', fail)
    sensor.detected = False
    for now in (10, 10.3, 11, 12): obj._loaded_filament_status(now)
    assert len(calls) == 1 and obj._load_filament_flags()['h2'] is False
    assert obj._filament_presence_error == 'full disk'


def test_prepared_resume_correction_does_not_repeat_admission_after_return(paused_origin_material):
    obj, objects, state = paused_origin_material
    obj._pause_origin.update(serviced=True, ready=True)
    saved = obj._pause_origin['states']['PAUSE']
    saved.update(base_position=[0, 0, 0, 2], extrude_factor=.8)
    objects['gcode_move'].saved_states['PAUSE'].update(saved)
    obj.cmd_CHECK_RESUME = lambda command: None
    calls = []
    objects['gcode'] = NS(run_script_from_command=calls.append)
    obj.cmd_PREPARE_RESUME_E(FakeCommand())
    def fail(command): raise AssertionError('Post-return admission must not run')
    obj.cmd_CHECK_RESUME = fail
    obj.cmd_RESTORE_RESUME_E(FakeCommand())
    obj.cmd_RESTORE_RESUME_E(FakeCommand())
    assert calls == ['G92 E50']


@pytest.mark.parametrize('change', ['mount', 'clear', 'replace', 'pause'])
def test_deferred_tangle_is_scoped_and_delivered_once(material, change):
    timers, calls = [], []
    file = io.StringIO('print')
    sd = NS(current_file=file, is_active=lambda: True)
    state = {'head': 'h1', 'job': 'printing'}
    reactor = NS(NEVER=float('inf'), monotonic=lambda: 1., register_timer=lambda cb, when: timers.append(cb))
    objects = {'virtual_sdcard': sd, 'print_stats': NS(get_status=lambda now: {'state': state['job']}),
               'pause_resume': NS(get_status=lambda now: {'is_paused': False})}
    material.printer = NS(get_reactor=lambda: reactor, lookup_object=lambda name, default=None: objects.get(name, default))
    material._attachment = lambda now: {'state': 'attached', 'head': state['head']}
    helper = NS(sensor_enabled=True, filament_present=False)
    material._defer_path_runout(helper, 2, calls.append)
    material._defer_path_runout(helper, 2, calls.append)
    assert len(timers) == 1 and timers[0](1.25) == 1.5
    if change == 'mount': state['head'] = 'h2'
    elif change == 'clear': helper.filament_present = True
    elif change == 'replace': sd.current_file = io.StringIO('new print')
    else: state['job'] = 'paused'
    assert timers[0](1.5) == reactor.NEVER
    assert timers[0](2.) == reactor.NEVER
    assert calls == ([1.5] if change == 'mount' else [])


def test_tangle_stale_pause_flag_cannot_suppress_active_sd(material):
    objects = {'virtual_sdcard': NS(is_active=lambda: True)}
    material.printer = NS(lookup_object=lambda name, default=None: objects.get(name, default))
    assert material._runout_pause_needed({'is_paused': True})
    objects['virtual_sdcard'].is_active = lambda: False
    assert not material._runout_pause_needed({'is_paused': True})


def test_transition_unknown_recipe_uses_residue_lower_bound():
    from wm_material import transition_temperature
    identity = {'material': 'PCTG', 'nozzle_temp': 255}
    previous = {'materials': [{'material': 'Custom', 'nozzle_temp_min': 245, 'nozzle_temp_max': 260}],
                'unknown_residue': False}
    target, note = transition_temperature(identity, previous, 255)
    assert target == 245 and '245' in note
