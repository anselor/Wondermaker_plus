"""Startup errors must never persist a temporary logical-tool mapping."""
import pytest
from test_print_recovery import RecoveryModel


class StartupFailure(RuntimeError):
    pass


@pytest.mark.parametrize('initial', [0, 2, 3])
@pytest.mark.parametrize('first_tool', [False, True])
@pytest.mark.parametrize('failure', [None, 'TEMPERATURE_WAIT', 'G28',
                                     'BED_MESH_CALIBRATE', 'SAVE_CONFIG_NO_RESTART'])
def test_mapping_survives_startup_and_interruption(initial, first_tool, failure):
    model = RecoveryModel()
    mapping = [3, 1, 0, 2]
    model.sv.update({'box_modify_t%d' % i: head for i, head in enumerate(mapping)})
    model.sv['probe_with_initial_tool'] = first_tool
    expected_probe = mapping[initial] if first_tool else 0

    class Events(list):
        def append(self, event):
            super().append(event)
            # Every command boundary, including failed ones, preserves the
            # user's persisted mapping. This also exercises nested G28 macros.
            assert [model.sv['box_modify_t%d' % i] for i in range(4)] == mapping
            if event[0] == failure:
                raise StartupFailure(failure)

    model.events = Events()
    if failure:
        with pytest.raises(StartupFailure):
            model.start(INITIAL_TOOL=initial)
    else:
        model.start(INITIAL_TOOL=initial)
        tools = [event[1]['tool'] for event in model.events if event[0] == 'PHYSICAL_TOOL']
        assert tools[0] == expected_probe
        assert tools[-1] == mapping[initial]
        heater = 'extruder' + (str(expected_probe) if expected_probe else '')
        assert ('SET_HEATER_TEMPERATURE', {'HEATER': heater, 'TARGET': '140'}) in model.events
    assert [model.sv['box_modify_t%d' % i] for i in range(4)] == mapping
    model.restart()
    assert [model.sv['box_modify_t%d' % i] for i in range(4)] == mapping


@pytest.mark.parametrize('first_tool', [False, True])
def test_saved_mesh_start_without_default_measures_full_mesh_and_continues(first_tool):
    model = RecoveryModel()
    model.sv['probe_with_initial_tool'] = first_tool
    model.p['bed_mesh']['profiles'].pop('default')
    model.disk_profiles.pop('default')
    model.run('G31')
    model.start(INITIAL_TOOL=3, ADAPTIVE=1)
    probes = [args for command, args in model.events if command == 'BED_MESH_CALIBRATE']
    assert len(probes) == 1 and probes[0].get('PROFILE') == 'wmp_print'
    assert 'ADAPTIVE' not in probes[0]
    assert model.p['bed_mesh']['profile_name'] == 'wmp_print'
    assert model.p['gcode_macro START_PRINT']['print_body_ready'] is True
    assert model.sv['probe_tool'] == (3 if first_tool else 0)
    assert not any(command == 'BED_MESH_PROFILE_BASE' and args.get('LOAD') == 'default'
                   for command, args in model.events)


def test_saved_default_still_loads_without_unrequested_reprobe():
    model = RecoveryModel()
    model.run('G31')
    model.start(INITIAL_TOOL=3)
    assert not any(command == 'BED_MESH_CALIBRATE' for command, args in model.events)
    assert any(command == 'BED_MESH_PROFILE_BASE' and args.get('LOAD') == 'default'
               for command, args in model.events)
    assert model.sv['probe_tool'] == 0
