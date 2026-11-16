import json
from pathlib import Path
import pytest
from test_wm_material import material, print_material, FakeCommand


@pytest.fixture
def paused_evidence(print_material):
    obj, objects, request, path = print_material
    objects['virtual_sdcard'].current_file = path.open('r')
    objects['pause_resume'].values['is_paused'] = True
    obj.printer.state = 'paused'
    for tool in range(4):
        objects['save_variables'].values['variables']['box_modify_t%d_backup' % tool] = tool
    record = {'version': 1, 'state': 'committed', 'owner': 'standalone',
              'file': request['file'], 'mapping': [0, 1, 2, 3],
              'heads': {'h2': {key: value for key, value in obj._loaded_filament_status(0)['h2'].items()
                               if key in ('identity', 'source')}}}
    obj._write_recovery_job(record)
    execution = Path(obj._recovery_execution_path())
    envelope = Path(obj._deposition_envelope_path())
    execution.write_text('{"old": "durable-execution"}')
    envelope.write_text('{"old": "durable-envelope"}')
    yield obj, objects, record, execution, envelope
    objects['virtual_sdcard'].current_file.close()


@pytest.mark.parametrize('change', ['mapping', 'identity'])
def test_resume_permitted_but_proven_recipe_edit_retires_old_authority(paused_evidence, change):
    obj, objects, record, execution, envelope = paused_evidence
    if change == 'mapping':
        objects['save_variables'].values['variables']['box_modify_t0_backup'] = 2
    else:
        loaded = obj._loaded_filament_status(0)
        loaded['h2']['identity'] = dict(loaded['h2']['identity'], material='ABS')
        obj._filament_state()._loaded_filament_status = lambda now: loaded
    command = FakeCommand()
    obj.cmd_CHECK_RESUME(command)
    assert obj._read_recovery_job()['state'] == 'invalidated'
    assert not execution.exists() and not envelope.exists()
    assert 'Printing can continue' in command.message
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('condition', ['unchanged', 'transient_current_mapping', 'unknown_sensor', 'other_file'])
def test_resume_preserves_authority_without_proven_same_job_recipe_edit(paused_evidence, condition):
    obj, objects, record, execution, envelope = paused_evidence
    if condition == 'transient_current_mapping':
        objects['save_variables'].values['variables']['box_modify_t0'] = 2
    elif condition == 'unknown_sensor':
        obj._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'unknown'}}
    elif condition == 'other_file':
        objects['save_variables'].values['variables']['box_modify_t0_backup'] = 2
        obj._recovery_storage()._recovery_active_file = lambda *args: (_ for _ in ()).throw(ValueError('other file'))
    obj.cmd_CHECK_RESUME(FakeCommand())
    assert obj._read_recovery_job() == record
    assert execution.exists() and envelope.exists()
