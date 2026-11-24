"""Transient reset requires a drained, still-owned, physically known tool state."""
from types import SimpleNamespace as NS
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'klipper_extras'))
from wmp_stop_points import finish_cancelled_toolchange


@pytest.fixture
def machine():
    events, owner = [], [True]
    data = {'save_variables': {'variables': {'changing_tool': 1, 'fail_flag': 0, 'thr_number': 4}},
            'custom_hall': {'Raw': 5000},
            'filament_switch_sensor sensor_b': {'filament_detected': False},
            **{'filament_switch_sensor docked%d' % n: {'filament_detected': True} for n in range(4)}}
    def write(command):
        events.append(command)
        assert command == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0'
        data['save_variables']['variables']['changing_tool'] = 0
    objects = {name: NS(get_status=lambda now, name=name: data[name]) for name in data}
    objects.update(toolhead=NS(wait_moves=lambda: events.append('drain')),
                   gcode=NS(run_script_from_command=write))
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_reactor=lambda: NS(monotonic=lambda: 0), is_shutdown=lambda: False)
    return printer, data, objects, events, owner


@pytest.mark.parametrize('attached', [False, True])
def test_reset_after_drain_for_docked_or_locked_head(machine, attached):
    printer, data, _, events, owner = machine
    if attached:
        data['custom_hall']['Raw'] = 4000
        data['filament_switch_sensor sensor_b']['filament_detected'] = True
        data['filament_switch_sensor docked2']['filament_detected'] = False
    assert finish_cancelled_toolchange(printer, lambda: owner[0]) == 'cleared'
    assert events == ['drain', 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0']


@pytest.mark.parametrize('case', ['before', 'during_drain', 'during_read', 'openace', 'AFC', 'shutdown'])
def test_replaced_owner_never_gets_reset(machine, case):
    printer, _, objects, events, owner = machine
    if case == 'before': owner[0] = False
    elif case == 'during_drain':
        objects['toolhead'].wait_moves = lambda: owner.__setitem__(0, False)
    elif case == 'during_read':
        objects['custom_hall'].get_status = lambda now: (owner.__setitem__(0, False) or {'Raw': 5000})
    elif case in ('openace', 'AFC'): objects[case] = object()
    else: printer.is_shutdown = lambda: True
    with pytest.raises(ValueError, match='ownership'):
        finish_cancelled_toolchange(printer, lambda: owner[0])
    assert not any(event.startswith('SAVE_VARIABLE') for event in events)


@pytest.mark.parametrize('case', ['fault', 'unknown_hall', 'bad_lock', 'two_missing', 'unknown_dock', 'flag_type', 'drain_error', 'readback', 'readback_bool', 'fault_after_sensor_read'])
def test_unconfirmed_state_never_claims_cleanup(machine, case):
    printer, data, objects, events, owner = machine
    if case == 'fault': data['save_variables']['variables']['fail_flag'] = -3
    elif case == 'unknown_hall': data['custom_hall']['Raw'] = float('nan')
    elif case == 'bad_lock': data['filament_switch_sensor sensor_b']['filament_detected'] = True
    elif case == 'two_missing':
        data['custom_hall']['Raw'] = 4000
        data['filament_switch_sensor sensor_b']['filament_detected'] = True
        for n in (0, 1): data['filament_switch_sensor docked%d' % n]['filament_detected'] = False
    elif case == 'unknown_dock': data['filament_switch_sensor docked0']['filament_detected'] = None
    elif case == 'fault_after_sensor_read':
        objects['custom_hall'].get_status = lambda now: (data['save_variables']['variables'].__setitem__('fail_flag', -3) or {'Raw': 5000})
    elif case == 'flag_type': data['save_variables']['variables']['changing_tool'] = True
    elif case == 'drain_error':
        def fail(): raise ValueError('drain failed')
        objects['toolhead'].wait_moves = fail
    elif case == 'readback': objects['gcode'].run_script_from_command = events.append
    else:
        objects['gcode'].run_script_from_command = lambda command: data['save_variables']['variables'].__setitem__('changing_tool', False)
    with pytest.raises(ValueError): finish_cancelled_toolchange(printer, lambda: owner[0])
    if case not in ('readback', 'readback_bool'): assert not any(event.startswith('SAVE_VARIABLE') for event in events)


@pytest.mark.parametrize('flag', [None, 0])
def test_no_transient_flag_needs_no_motion_or_write(machine, flag):
    printer, data, _, events, owner = machine
    data['save_variables']['variables']['changing_tool'] = flag
    assert finish_cancelled_toolchange(printer, lambda: owner[0]) == 'not_needed'
    assert events == []
