"""Actual retained macro rendering reports the failed guard without motion."""
import copy
import pytest
from test_config_macros import templates, ROOT


@pytest.fixture(scope='module')
def macros():
    return templates(ROOT / 'config/live')


def refuse(message):
    raise RuntimeError(message)


@pytest.mark.parametrize('raw,sensor', [(4000, False), (5021, True), (4000, True)])
def test_release_failure_reports_actual_post_retreat_sensors(macros, raw, sensor):
    printer = {'custom_hall': {'Raw': raw}, 'filament_switch_sensor sensor_b': {'filament_detected': sensor}}
    script = macros['_WMP_REQUIRE_RELEASE'].render(printer=printer, params={'T': '2'})
    assert 'SAVE_VARIABLE VARIABLE=fail_flag VALUE=-3' in script
    assert '_WMP_ABORT_DOCKING REASON=release_sensors T=2' in script
    with pytest.raises(RuntimeError) as error:
        macros['_WMP_ABORT_DOCKING'].render(printer=printer, params={'REASON': 'release_sensors', 'T': '2'}, action_raise_error=refuse)
    assert 'after retreat' in str(error.value) and str(raw) in str(error.value)
    assert 'sensor_b.filament_detected=' + str(sensor) in str(error.value)


def test_dock_seating_failure_is_distinct_from_release(macros):
    with pytest.raises(RuntimeError, match='docked2.filament_detected=False; expected True before unlocking'):
        macros['_WMP_ABORT_DOCKING'].render(printer={}, params={'REASON': 'dock_sensor', 'T': '2'}, action_raise_error=refuse)


@pytest.mark.parametrize('field,expected', [
    ('version', 'wmp_print_context.version'), ('tool', 'wmp_print_context.tool'),
    ('mesh', 'wmp_print_context.mesh'), ('profiles', 'bed_mesh.profiles'),
    ('offsets', 'saved tool offsets'), ('file_hex', 'wmp_print_context.file_hex'),
    ('mapping_length', 'exactly four heads'), ('mapping_value', 'values outside 0..3'),
])
def test_recovery_combined_gate_reports_exact_mismatch(macros, field, expected):
    offsets = [[0, 0, 0]] * 4
    context = {'version': 2, 'tool': 0, 'mesh': 'wmp_print', 'offsets': offsets,
               'file_hex': 'PRIVATE_FILE', 'mapping': [0, 1, 2, 3]}
    printer = {'save_variables': {'variables': {'wmp_print_context': context,
                 **{'t%d_offset' % i: offsets[i] for i in range(4)}}},
               'bed_mesh': {'profiles': {'wmp_print': {}}}}
    if field == 'profiles': printer['bed_mesh']['profiles'] = {}
    elif field == 'mapping_length': context['mapping'] = [0]
    elif field == 'mapping_value': context['mapping'] = [0, 1, 2, 9]
    elif field == 'offsets': context['offsets'] = [[1, 0, 0]] * 4
    else: context[field] = {'version': 1, 'tool': 9, 'mesh': 'other', 'file_hex': ''}[field]
    stops = []
    with pytest.raises(RuntimeError) as error:
        macros['_WMP_RECOVERY_BEGIN'].render(printer=printer, params={}, action_emergency_stop=lambda text: stops.append(text) or '', action_raise_error=refuse)
    assert expected in str(error.value) and stops == [str(error.value)]
    assert 'PRIVATE_FILE' not in str(error.value)


@pytest.mark.parametrize('flag,current', [(-3, 2), (0, 1)])
def test_offset_save_reports_fault_or_changed_head(macros, flag, current):
    printer = {'save_variables': {'variables': {'fail_flag': flag, 'current_extruder': current}}}
    with pytest.raises(RuntimeError) as error:
        macros['_SAVE_PROBE_POS'].render(printer=printer, params={'T': '2'}, action_raise_error=refuse)
    assert 'fail_flag=%d (expected 0)' % flag in str(error.value)
    assert 'current_extruder=%d (expected 2)' % current in str(error.value)


@pytest.mark.parametrize('field,expected', [('file', 'selected file identity'), ('profile', 'bed_mesh.profile_name'),
    ('tool', 'saved probe_tool'), ('version', 'wmp_print_context.version'),
    ('length', 'exactly four heads'), ('value', 'values outside 0..3')])
def test_recovery_resume_reports_specific_gate_without_file_payload(macros, field, expected):
    context = {'version': 2, 'tool': 0, 'file_hex': 'PRIVATE_FILE'.encode().hex(), 'mapping': [0, 1, 2, 3]}
    sv = {'probe_tool': 0, 'wmp_print_context': context}
    printer = {'save_variables': {'variables': sv}, 'gcode_macro _WMP_RECOVERY_BEGIN': {'active': True},
               'print_stats': {'filename': 'PRIVATE_FILE'}, 'bed_mesh': {'profile_name': 'wmp_print'}}
    if field == 'file': context['file_hex'] = 'changed'
    elif field == 'profile': printer['bed_mesh']['profile_name'] = 'different'
    elif field == 'tool': sv['probe_tool'] = 2
    elif field == 'version': context['version'] = 1
    elif field == 'length': context['mapping'] = [0]
    else: context['mapping'] = [0, 1, 2, 9]
    stops = []
    with pytest.raises(RuntimeError) as error:
        macros['M24'].render(printer=printer, params={}, rawparams='', action_emergency_stop=lambda text: stops.append(text) or '', action_raise_error=refuse)
    assert expected in str(error.value) and stops == [str(error.value)]
    assert 'PRIVATE_FILE' not in str(error.value)
