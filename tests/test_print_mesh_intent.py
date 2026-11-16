"""Mesh-only persistence uses retained serialization without restart policy."""
import copy
from types import SimpleNamespace as NS
import pytest
from test_probe_config_change import config, guarded_config


def prepare(v):
    v.config.autosave.fileconfig.remove_section('probe')
    v.config.status_save_pending = {}
    v.config.set('bed_mesh wmp_print', 'points', '0.1, 0.2\n0.3, 0.4')
    v.objects['configfile'] = v.config
    v.state['bed_mesh'] = {'profile_name': 'wmp_print'}
    v.state['print_stats']['state'] = 'printing'
    messages = []
    return NS(respond_info=messages.append), messages


def test_explicit_mesh_save_during_print_keeps_pending_state(guarded_config):
    v = guarded_config
    command, messages = prepare(v)
    before, pending = v.path.read_bytes(), copy.deepcopy(v.config.status_save_pending)
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert v.material._print_mesh_persisted
    assert not messages and not v.restarts
    assert '#*# [bed_mesh wmp_print]' in v.path.read_text()
    assert next(v.path.parent.glob('printer-mesh-*.cfg')).read_bytes() == before
    assert v.config.status_save_pending == pending
    # Read the published result using the retained parser, not text alone.
    regular, autosave = v.config._find_autosave_data(v.path.read_text())
    parsed = v.config._build_config_wrapper(autosave, str(v.path))
    assert parsed.fileconfig.get('bed_mesh wmp_print', 'points').strip() == '0.1, 0.2\n0.3, 0.4'


def test_other_pending_settings_skip_save_without_losing_edits(guarded_config):
    v = guarded_config
    command, messages = prepare(v)
    v.config.set('probe', 'z_offset', '1.75')
    before, pending = v.path.read_bytes(), copy.deepcopy(v.config.status_save_pending)
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert not v.material._print_mesh_persisted
    assert 'pending config sections' in messages[0]
    assert 'Printing can continue' in messages[0]
    assert v.path.read_bytes() == before and v.config.status_save_pending == pending
    assert not v.restarts


@pytest.mark.parametrize('failure', ['replace', 'fsync'])
def test_failed_mesh_publication_keeps_original_config(guarded_config, monkeypatch, failure):
    import wm_material
    v = guarded_config
    command, messages = prepare(v)
    before = v.path.read_bytes()
    def fail(*args):
        raise OSError('injected storage failure')
    monkeypatch.setattr(wm_material.os, failure, fail)
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert v.path.read_bytes() == before
    assert not v.material._print_mesh_persisted and not v.restarts
    assert 'injected storage failure' in messages[0]
    assert not list(v.path.parent.glob('.wmp-print-mesh-*'))


def test_explicit_whole_set_no_restart_save_is_not_restart_admission(guarded_config):
    v = guarded_config
    v.state['print_stats']['state'] = 'printing'
    v.handlers['SAVE_CONFIG_NO_RESTART'](NS(error=ValueError))
    assert '#*# z_offset = 1.500' in v.path.read_text()
    assert not v.restarts


def test_skipped_mesh_cannot_commit_recovery(guarded_config):
    v = guarded_config
    command, messages = prepare(v)
    v.config.set('probe', 'z_offset', '1.75')
    v.material._pending_recovery_submission = {'record': {'state': 'staged'}}
    v.material._deposition_envelope = object()
    v.material.cmd_SAVE_PRINT_MESH(command)
    v.material.cmd_RECOVERY_JOB_COMMIT(command)
    assert v.material._pending_recovery_submission is None
    assert v.material._deposition_envelope is None
    assert 'Power-loss recovery unavailable' in messages[-1]


def test_failed_directory_sync_never_leaves_config_missing(guarded_config, monkeypatch):
    import wm_material
    v = guarded_config
    command, messages = prepare(v)
    original_sync, calls = wm_material.os.fsync, []
    def sync(fd):
        calls.append(fd)
        if len(calls) == 3:
            raise OSError('directory sync failed after publication')
        original_sync(fd)
    monkeypatch.setattr(wm_material.os, 'fsync', sync)
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert '#*# [bed_mesh wmp_print]' in v.path.read_text()
    assert not v.material._print_mesh_persisted
    assert 'directory sync failed' in messages[0]


def test_unreadable_current_config_skips_optional_mesh_save(guarded_config):
    v = guarded_config
    command, messages = prepare(v)
    v.path.write_text('[include missing.cfg]\n')
    before = v.path.read_bytes()
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert v.path.read_bytes() == before
    assert not v.material._print_mesh_persisted
    assert 'missing.cfg' in messages[0] and 'Printing can continue' in messages[0]
