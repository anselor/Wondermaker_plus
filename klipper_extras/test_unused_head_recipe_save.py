"""Narrow recipe writes only where affected heads are established."""
import json
import pytest
from test_wm_material import material, print_material, FakeCommand, profile_command, start_command


@pytest.mark.parametrize('operation,allowed', [({'state':'running','head':'h1'}, True),
    ({'state':'pending','head':'h2'}, False), ({'state':'running','head':'h2'}, False),
    ({'state':'running'}, False), ({'state':'running','head':'unresolved'}, False)])
def test_idle_recipe_edit_excludes_only_affected_filament_service(material, operation, allowed):
    material.cmd_SET_FILAMENT(profile_command(material))
    material.filament_operation = operation
    identity = dict(material._profiles()[0]['h2'], material='PLA')
    command = profile_command(material, PROFILE=json.dumps(identity).encode().hex())
    if allowed:
        material.cmd_SET_FILAMENT(command)
        assert material._profiles()[0]['h2']['material'] == 'PLA'
    else:
        with pytest.raises(ValueError, match='active filament operation'):
            material.cmd_SET_FILAMENT(command)


def test_unknown_active_print_usage_refuses_recipe_only_without_mutating_job(material):
    material.cmd_SET_FILAMENT(profile_command(material))
    material.printer.state = 'printing'
    material.printer.sd_active = True
    original = material._profiles()[0]['h2']
    with pytest.raises(ValueError, match='Complete active-job head usage is unavailable'):
        material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(dict(original, nozzle_temp=230)).encode().hex()))
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(dict(original, color='#123456')).encode().hex()))
    assert material.printer.state == 'printing' and material.printer.sd_active
    assert material._profiles()[0]['h2']['material'] == original['material']


def test_unused_recipe_edit_during_managed_staging_does_not_invalidate_used_head(print_material):
    obj, objects, request, _ = print_material
    profiles = obj._profiles()[0]
    profiles['h1'] = dict(profiles['h2'])
    with open(obj.profile_path, 'w') as stream: json.dump(profiles, stream)
    request['profile_revision'] = obj._profiles()[1]
    objects['extruder1'] = object()
    before = obj._filament_recipe(profiles['h2'])
    previous_pause = obj.printer.pause
    called = []
    def pause(when):
        if not called:
            identity = dict(obj._profiles()[0]['h1'], material='PLA', nozzle_temp=215)
            obj.cmd_SET_FILAMENT(FakeCommand(HEAD=1, EXPECT=obj._profiles()[1], PROFILE=json.dumps(identity).encode().hex()))
            called.append(True)
        return previous_pause(when)
    obj.printer.pause = pause
    obj.cmd_START_PRINT(start_command(request))
    assert called
    assert objects['gcode'].scripts[-1].startswith('SDCARD_PRINT_FILE')
    assert obj._filament_recipe(obj._profiles()[0]['h2']) == before
    assert set(obj._read_recovery_job()['heads']) == {'h2'}
