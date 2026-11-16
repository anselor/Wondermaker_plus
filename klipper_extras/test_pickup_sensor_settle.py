import logging
from types import SimpleNamespace as NS
import pytest
from test_wm_material import material, FakeCommand


@pytest.fixture
def pickup(material):
    clock = {'now': 0., 'waits': 0}
    sensor = {'filament_detected': True}
    saved = {'fail_flag': 0}
    def pause(when):
        clock.update(now=when, waits=clock['waits'] + 1)
        return when
    reactor = NS(monotonic=lambda: clock['now'], pause=pause)
    original = material.printer.lookup_object
    objects = {'gcode': NS(quick_stop_flag=False),
               'save_variables': NS(get_status=lambda now: {'variables': saved}),
               'filament_switch_sensor docked2': NS(get_status=lambda now: sensor),
               'custom_hall': NS(get_status=lambda now: {'Raw': 4544}),
               'filament_switch_sensor sensor_b': NS(get_status=lambda now: {'filament_detected': True})}
    material.printer.lookup_object = lambda name, default=None: objects.get(name, original(name, default))
    material.printer.get_reactor = lambda: reactor
    material.printer.is_shutdown = lambda: False
    material._command_generation = 3
    command = FakeCommand(HEAD='2', SESSION=material.session_id, GENERATION='3')
    return material, command, clock, sensor, saved, reactor


def test_clear_dock_passes_without_wait_or_new_gates(pickup, caplog):
    obj, cmd, clock, sensor, saved, reactor = pickup
    sensor['filament_detected'] = False
    with caplog.at_level(logging.INFO): obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['waits'] == 0
    assert saved['fail_flag'] == 0 and obj._command_generation == 3
    assert 'initial=False final=False elapsed=0.000s' in caplog.text


def test_delayed_dock_callback_passes_stationary_observation(pickup, caplog):
    obj, cmd, clock, sensor, saved, reactor = pickup
    original = reactor.pause
    def pause(when):
        original(when)
        if when >= .15: sensor['filament_detected'] = False
    reactor.pause = pause
    with caplog.at_level(logging.INFO): obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert .15 <= clock['now'] < .5
    assert saved['fail_flag'] == 0 and obj._command_generation == 3
    assert 'initial=True final=False' in caplog.text


@pytest.mark.parametrize('value', [True, None])
def test_persistent_or_unknown_dock_faults_current_attempt_and_retires_tail(pickup, value):
    obj, cmd, clock, sensor, saved, reactor = pickup
    sensor['filament_detected'] = value
    with pytest.raises(ValueError, match=r'docked2=.*expected False after retreat'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['now'] == pytest.approx(.5)
    assert saved['fail_flag'] == -5 and obj._command_generation == 4


def test_cancel_during_observation_does_not_publish_old_attempt_fault(pickup):
    obj, cmd, clock, sensor, saved, reactor = pickup
    original = reactor.pause
    def pause(when):
        original(when)
        obj._command_generation += 1
    reactor.pause = pause
    with pytest.raises(ValueError, match='invalidated by cancellation'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['now'] == .05
    assert saved['fail_flag'] == 0 and obj._command_generation == 4


def test_existing_fault_is_not_cleared_or_replaced(pickup):
    obj, cmd, clock, sensor, saved, reactor = pickup
    saved['fail_flag'] = -3
    with pytest.raises(ValueError, match='current fail_flag=-3'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert saved['fail_flag'] == -3 and clock['waits'] == 0


def test_target_clear_does_not_add_hall_lock_or_other_dock_admission(pickup):
    obj, cmd, clock, sensor, saved, reactor = pickup
    sensor['filament_detected'] = False
    lookup = obj.printer.lookup_object
    def current(name, default=None):
        if name == 'custom_hall': return NS(get_status=lambda now: {'Raw': None})
        if name == 'filament_switch_sensor sensor_b':
            return NS(get_status=lambda now: {'filament_detected': False})
        if name.startswith('filament_switch_sensor docked') and name != 'filament_switch_sensor docked2':
            pytest.fail('Added another dock predicate')
        return lookup(name, default)
    obj.printer.lookup_object = current
    obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert saved['fail_flag'] == 0 and clock['waits'] == 0
