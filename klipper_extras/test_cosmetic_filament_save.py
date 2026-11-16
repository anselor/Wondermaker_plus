"""Labels may change without changing physical material admission."""
import copy
import json
import pytest
from test_wm_material import (material, print_material, sequence_material, service_material,
                              FakeCommand, profile_command, start_command)


def save_identity(obj, **changes):
    identity = dict(obj._profiles()[0]['h2'], **changes)
    obj.cmd_SET_FILAMENT(profile_command(obj, PROFILE=json.dumps(identity).encode().hex()))


@pytest.mark.parametrize('busy', ['printing', 'paused', 'toolhead', 'filament'])
def test_cosmetic_save_does_not_require_idle_or_empty_head(material, busy):
    material.cmd_SET_FILAMENT(profile_command(material))
    before = material._profile_recipes()
    if busy == 'printing': material.printer.state = 'printing'; material.printer.sd_active = True
    if busy == 'paused': material.printer.paused = True
    if busy == 'toolhead': material.toolhead_operation = {'state': 'running'}
    if busy == 'filament': material.filament_operation = {'state': 'running', 'head': 'h2'}
    save_identity(material, brand='New display brand', color='#123456')
    assert material._profile_recipes() == before
    assert material._profiles()[0]['h2']['color'] == '#123456'
    assert not hasattr(material, '_loaded_flags')
    if busy == 'toolhead':
        # Coupling motion does not consume a filament recipe.
        save_identity(material, material='PLA', nozzle_temp=230)
    else:
        with pytest.raises(ValueError): save_identity(material, material='PLA')
        with pytest.raises(ValueError): save_identity(material, nozzle_temp=230)


def test_cosmetic_save_preserves_cas_and_identification_exclusion(material):
    material.cmd_SET_FILAMENT(profile_command(material))
    old = profile_command(material)
    save_identity(material, color='#123456')
    with pytest.raises(ValueError, match='changed'): material.cmd_SET_FILAMENT(old)
    material._material_settings()._identification_pending = lambda now: True
    with pytest.raises(ValueError, match='identification'): save_identity(material, brand='new')


@pytest.mark.parametrize('change,allowed', [({'color':'#112233'}, True), ({'brand':'new'}, True),
                                           ({'material':'PLA'}, False), ({'nozzle_temp':230}, False)])
def test_print_submission_pins_recipe_across_staging_yield(print_material, change, allowed):
    obj, objects, request, path = print_material
    original_pause = obj.printer.pause
    modified = []
    def pause(when):
        if not modified:
            # Model another admitted metadata command at a reactor yield.
            save_identity(obj, **change)
            modified.append(True)
        return original_pause(when)
    obj.printer.pause = pause
    if allowed:
        obj.cmd_START_PRINT(start_command(request))
        assert objects['gcode'].scripts[-1] == 'SDCARD_PRINT_FILE FILENAME="part.gcode"'
    else:
        with pytest.raises(ValueError, match='recipe changed'):
            obj.cmd_START_PRINT(start_command(request))
        assert not any(script.startswith('SDCARD_PRINT_FILE') for script in objects['gcode'].scripts)
    assert modified


@pytest.mark.parametrize('change,allowed', [({'color':'#112233'}, True), ({'brand':'new'}, True),
                                           ({'material':'PLA'}, False), ({'nozzle_temp':230}, False)])
def test_loaded_source_comparison_preserves_recipe_and_immutable_evidence(material, change, allowed):
    saved = {'source':'external:h2', 'identity':{'brand':'old','color':'#ffffff','material':'PETG'}}
    before = copy.deepcopy(saved)
    current = dict(saved, state='loaded', identity=dict(saved['identity'], **change))
    assert material._loaded_source_matches(current, saved) is allowed
    assert saved == before
    assert not material._loaded_source_matches(dict(current, source='external:h3'), saved)
    assert not material._loaded_source_matches(dict(current, state='empty'), saved)


def test_active_service_plan_keeps_recipe_and_load_evidence(service_material):
    obj, _, _ = service_material
    plan = obj._filament_plan(2, 'load', 1)
    physical = {key: copy.deepcopy(plan[key]) for key in ('target','class','feed_mm','purge_mm','previous_material')}
    flags = copy.deepcopy(obj._filament_state()._load_filament_flags())
    obj.filament_operation = {'state':'running','head':'h2'}
    save_identity(obj, color='#123456', brand='new')
    assert {key: plan[key] for key in physical} == physical
    assert obj._filament_state()._load_filament_flags() == flags
    assert obj._filament_context_valid(plan, 1)

from test_wm_material import (recovery_startup, committed_recovery, bound_recovery,
                              recovery_machine, execution_snapshot_machine)


def test_cosmetic_change_preserves_checkpoint_capture_publication_and_saved_bytes(execution_snapshot_machine):
    from pathlib import Path
    obj, objects, states = execution_snapshot_machine
    path = Path(obj._recovery_job_path())
    original = path.read_bytes()
    save_identity(obj, color='#123456')
    assert obj._execution_evidence()._queue_recovery_execution()
    save_identity(obj, brand='new')
    objects['toolhead'].check_busy = lambda now: (100., 100., False)
    assert obj._execution_evidence()._publish_recovery_execution()
    assert path.read_bytes() == original
    assert not obj._retire_changed_print_recovery()


def test_cosmetic_change_preserves_restart_recovery_evidence(committed_recovery):
    from pathlib import Path
    obj, _, _, path = committed_recovery
    evidence = Path(obj._recovery_job_path())
    original = evidence.read_bytes()
    save_identity(obj, brand='new', color='#123456')
    assert obj._recovery_material_evidence(path.name)
    assert evidence.read_bytes() == original


def test_cosmetic_change_between_mesh_and_commit_keeps_recovery(recovery_startup):
    obj, _, _, _ = recovery_startup
    obj.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    save_identity(obj, color='#123456')
    obj._print_mesh_persisted = True
    obj.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    assert obj._read_recovery_job()['state'] == 'committed'
