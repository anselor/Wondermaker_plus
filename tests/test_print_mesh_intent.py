"""Mesh-only persistence uses retained serialization without restart policy."""
import copy
from types import SimpleNamespace as NS
import pytest
from test_probe_config_change import change, config, guarded_config


def prepare(v):
    v.config.autosave.fileconfig.remove_section('probe')
    v.config.status_save_pending = {}
    v.config.set('bed_mesh wmp_print', 'points', '\n  0.1, 0.2\n  0.3, 0.4')
    v.objects['configfile'] = v.config
    v.state['bed_mesh'] = {'profile_name': 'wmp_print'}
    v.state['print_stats']['state'] = 'printing'
    messages = []
    return NS(respond_info=messages.append), messages


def test_saved_print_mesh_allows_subsequent_probe_calibration(guarded_config, change):
    v = guarded_config
    command, messages = prepare(v)
    old = v.path.with_name('printer-mesh-6xg6ug_9.cfg')
    old.write_bytes(v.path.read_bytes())
    custom = v.path.with_name('printer-mesh-12345678.cfg')
    custom.write_text('[gcode_macro USER_MACRO]\ngcode: M400\n')
    other = v.path.with_name('printer-20261118_002900.cfg')
    other.write_bytes(b'Klipper backup')
    before = v.path.read_bytes()
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert v.material._print_mesh_persisted
    assert not messages and not v.restarts
    assert v.path.read_bytes() == before
    assert not old.exists()
    assert other.read_bytes() == b'Klipper backup'
    assert list(v.path.parent.glob("printer-mesh-*")) == [custom]
    assert v.config.status_save_pending == {} and not v.config.save_config_pending
    offset = change(v.config, 'probe')
    v.config.set('probe', 'z_offset', '-0.165')
    offset.capture()
    offset.admit_save()
    # Read the published result using the retained parser, not text alone.
    parsed = v.config.read_main_config()
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
    assert '#*# z_offset = -0.145' in v.path.read_text()
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
        if len(calls) == 2:
            raise OSError('directory sync failed after publication')
        original_sync(fd)
    monkeypatch.setattr(wm_material.os, 'fsync', sync)
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert '[bed_mesh wmp_print]' not in v.path.read_text()
    assert not v.material._print_mesh_persisted
    assert 'directory sync failed' in messages[0]
    assert 'bed_mesh wmp_print' in v.config.status_save_pending and v.config.save_config_pending


def test_unreadable_current_config_skips_optional_mesh_save(guarded_config):
    v = guarded_config
    command, messages = prepare(v)
    v.path.write_text('[include missing.cfg]\n')
    before = v.path.read_bytes()
    v.material.cmd_SAVE_PRINT_MESH(command)
    assert v.path.read_bytes() == before
    assert not v.material._print_mesh_persisted
    assert 'missing.cfg' in messages[0] and 'Printing can continue' in messages[0]


def test_print_mesh_save_refuses_existing_positive_probe_offset(guarded_config):
    v = guarded_config
    cmd, messages = prepare(v)
    v.config.status_settings = {'probe': {'z_offset': 2.730}}
    before = v.path.read_bytes()
    v.material.cmd_SAVE_PRINT_MESH(cmd)
    assert not v.material._print_mesh_persisted and v.path.read_bytes() == before
    assert 'zero or less' in messages[0]


def test_retiring_job_removes_only_owned_mesh(guarded_config):
    v = guarded_config
    cmd, messages = prepare(v)
    before = v.path.read_bytes()
    v.material.cmd_SAVE_PRINT_MESH(cmd)
    assert not messages
    mesh = v.path.with_name('wmp-plr-mesh-v1.cfg')
    assert v.config.read_main_config().fileconfig.has_section('bed_mesh wmp_print')
    v.material.profile_path = str(v.path.with_name('wmp_filaments.json'))
    v.material.session_id = 'mesh-test'
    assert v.material.cmd_RECOVERY_JOB_CLEAR(cmd)
    assert not mesh.exists() and v.path.read_bytes() == before
    assert not v.config.read_main_config().fileconfig.has_section('bed_mesh wmp_print')
    mesh.write_text('# user file\n')
    assert not v.material.cmd_RECOVERY_JOB_CLEAR(cmd)
    assert mesh.read_text() == '# user file\n'


def test_vendor_profile_manager_reloads_print_grid_after_restart(guarded_config, monkeypatch):
    from test_probe_config_change import ROOT
    vendor = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'
    monkeypatch.syspath_prepend(str(vendor))
    from extras.bed_mesh import ProfileManager
    v = guarded_config
    cmd, messages = prepare(v)
    fields = dict(version=1, min_x=20., max_x=30., min_y=40., max_y=50.,
                  x_count=2, y_count=2, mesh_x_pps=0, mesh_y_pps=0,
                  algo='lagrange', tension=0.2)
    for key, value in fields.items():
        v.config.set('bed_mesh wmp_print', key, value)
    v.material.cmd_SAVE_PRINT_MESH(cmd)
    assert not messages
    v.gcode.register_command = lambda name, handler, desc: None
    manager = ProfileManager(v.config.read_main_config().getsection('bed_mesh'), None)
    profile = manager.get_profiles()['wmp_print']
    assert [list(row) for row in profile['points']] == [[0.1, 0.2], [0.3, 0.4]]
    assert profile['mesh_params'] == {k: v for k, v in fields.items() if k != 'version'}
