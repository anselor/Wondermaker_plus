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


@pytest.mark.parametrize('settle_time', [.55, .9, 1.8])
def test_provisional_failure_rechecked_without_pausing_or_repeating_motion(pickup, caplog, settle_time):
    obj, cmd, clock, sensor, saved, reactor = pickup
    original = reactor.pause
    def pause(when):
        original(when)
        if when >= settle_time:
            sensor['filament_detected'] = False
    reactor.pause = pause
    with caplog.at_level(logging.INFO):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert settle_time <= clock['now'] <= 2.
    assert saved['fail_flag'] == 0 and obj._command_generation == 3
    assert 'indication provisional' in caplog.text
    assert 'final=False' in caplog.text


@pytest.mark.parametrize('value', [True, None])
def test_persistent_or_unknown_dock_faults_current_attempt_and_retires_tail(pickup, value):
    obj, cmd, clock, sensor, saved, reactor = pickup
    sensor['filament_detected'] = value
    with pytest.raises(ValueError, match=r'docked2=.*expected False after retreat'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['now'] == pytest.approx(2.)
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


@pytest.fixture
def approach(pickup):
    obj, cmd, clock, sensor, saved, reactor = pickup
    sensors = {'hall': 5000, 'lock': False, 'docks': [True] * 4}
    original = obj.printer.lookup_object
    def lookup(name, default=None):
        if name == 'custom_hall': return NS(get_status=lambda now: {'Raw': sensors['hall']})
        if name == 'filament_switch_sensor sensor_b':
            return NS(get_status=lambda now: {'filament_detected': sensors['lock']})
        if name.startswith('filament_switch_sensor docked'):
            index = int(name[-1])
            return NS(get_status=lambda now: {'filament_detected': sensors['docks'][index]})
        return original(name, default)
    obj.printer.lookup_object = lookup
    cmd.args["DEFER"] = "1"
    return pickup, sensors


def test_confirmed_pickup_does_not_pause_for_one_contradictory_dock_switch(approach, caplog):
    (obj, cmd, clock, sensor, saved, reactor), sensors = approach
    obj.cmd_PICKUP_BEGIN(cmd)
    assert saved['fail_flag'] == 0 and clock['waits'] == 0
    sensors.update(hall=4542, lock=True)  # Actual coupled head, other docks occupied.
    with caplog.at_level(logging.INFO): obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['now'] == pytest.approx(.5)
    assert saved['fail_flag'] == 0 and obj._command_generation == 3
    assert 'empty-to-coupled transition head=2' in caplog.text
    # Evidence is consumed; it cannot bless another attempt.
    assert obj._toolheads()._pickup_observation is None
    with pytest.raises(ValueError, match='pickup not confirmed'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)


@pytest.mark.parametrize('conflict', ['not_empty_before', 'wrong_head_missing', 'unknown_other_dock',
    'unlocked', 'empty_hall', 'unknown_hall', 'unknown_target', 'wrong_attempt', 'new_generation', 'not_deferred', 'final_check'])
def test_conflicting_or_unbound_pickup_evidence_still_pauses(approach, conflict):
    (obj, cmd, clock, sensor, saved, reactor), sensors = approach
    if conflict == 'not_deferred': cmd.args['DEFER'] = '0'
    if conflict == 'final_check': cmd.args['FINAL'] = '1'
    if conflict == 'not_empty_before': sensors.update(hall=4542, lock=True)
    if conflict == 'wrong_attempt': cmd.args['HEAD'] = '1'
    obj.cmd_PICKUP_BEGIN(cmd)
    cmd.args['HEAD'] = '2'
    sensors.update(hall=4542, lock=True)
    if conflict == 'wrong_head_missing': sensors['docks'][1] = False
    if conflict == 'unknown_other_dock': sensors['docks'][1] = None
    if conflict == 'unknown_target': sensors['docks'][2] = None
    if conflict == 'unlocked': sensors['lock'] = False
    if conflict == 'empty_hall': sensors['hall'] = 5000
    if conflict == 'unknown_hall': sensors['hall'] = None
    if conflict == 'new_generation':
        obj._command_generation += 1
        cmd.args['GENERATION'] = '4'
    with pytest.raises(ValueError, match='pickup not confirmed'):
        obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert saved['fail_flag'] == -5 and clock['now'] == pytest.approx(2.)


def test_final_identity_passes_only_after_provisional_switch_clears(approach):
    (obj, cmd, clock, sensor, saved, reactor), sensors = approach
    obj.cmd_PICKUP_BEGIN(cmd)
    sensors.update(hall=4542, lock=True)
    obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert saved['fail_flag'] == 0
    # The normal wipe happens between the two checks; its elapsed time lets
    # delayed MCU observations arrive. The final check cannot reuse the proof.
    sensors['docks'][2] = False
    cmd.args['FINAL'] = '1'
    observed_at = clock['now']
    obj.cmd_CHECK_PICKUP_RELEASE(cmd)
    assert clock['now'] == observed_at and saved['fail_flag'] == 0
