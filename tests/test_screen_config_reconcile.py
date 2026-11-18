"""Configuration planning against stock files and the exact vendor parser."""
import importlib.util
import json
import shutil
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
from test_deploy import deploy  # Tool import path.
from components.material import HELPERS as MATERIAL_HELPERS
import preload_bundle as bundle
import reconcile_screen_config as reconcile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/configfile.py'


@pytest.fixture(autouse=True)
def offline_owner_admission(monkeypatch):
    # These fixtures exercise config publication without a running Moonraker.
    # Disk-owner refusal is tested below; live-owner admission is in test_preflight.
    import preflight
    monkeypatch.setattr(preflight, 'standalone_owner', lambda ctx: None)


@pytest.fixture
def printer(tmp_path):
    target = tmp_path / 'config'
    shutil.copytree(ROOT / 'config/stock', target)
    # Device-specific values, custom include, runtime data and saved calibration.
    custom = ('[printer]\nmax_velocity: 123\n[tools_calibrate]\n'
              'probe_position: 299, 288, 7, 6, 5\n'
              '[filament_switch_sensor filament2]\nswitch_pin: T2:PC14\nevent_delay: 0.8\n'
              '[gcode_macro RESUME]\nvariable_zhop: 4.2\n'
              '[gcode_macro USER_LIGHT]\ngcode: RESPOND MSG="keep me"\n')
    (target / 'custom.cfg').write_text(custom)
    with (target / 'printer.cfg').open('a') as stream:
        stream.write('\n[include custom.cfg]\n' + reconcile.SAVE_MARKER.decode() + '\n#*# [probe]\n#*# z_offset = 1.234\n')
    (target / 'wmp_filaments.json').write_text('{"h2":{"brand":"Sunlu"}}')
    (target / 'wmp_filament_loaded.json').write_text('{"h2":true}')
    return target


def apply_plan(directory, planned):
    # Test publication only, on disposable files. Production planner never writes.
    for change in planned['changes']:
        (directory / change['file']).write_bytes(change['after'])


@pytest.fixture
def interrupted_publication(printer, monkeypatch):
    planned = reconcile.plan(ROOT, printer)
    original = reconcile._atomic
    destination = planned['changes'][0]['file']

    def power_loss(path, data):
        original(path, data)
        if path == printer / destination:
            # Bypass in-process Exception rollback, as process death would.
            raise SystemExit('simulated process loss after first live rename')

    monkeypatch.setattr(reconcile, '_atomic', power_loss)
    with pytest.raises(SystemExit):
        reconcile.publish(printer, planned)
    monkeypatch.setattr(reconcile, '_atomic', original)
    backups = list(printer.glob('.wmp-config-backup-*'))
    assert len(backups) == 1
    assert json.loads((backups[0] / 'journal.json').read_text())['state'] == 'prepared'
    return planned, backups[0]


def test_restart_recovers_reviewed_bytes_without_replanning(printer, interrupted_publication):
    planned, backup = interrupted_publication
    reconcile.recover_interrupted(printer, backup)
    for change in planned['changes']:
        path = printer / change['file']
        assert (path.read_bytes() if path.exists() else None) == change['before']
    assert json.loads((backup / 'journal.json').read_text())['state'] == 'rolled-back'
    with pytest.raises(ValueError, match='not interrupted'):
        reconcile.recover_interrupted(printer, backup)


def test_remote_restart_recovery_uses_retained_transaction(printer, interrupted_publication):
    planned, backup = interrupted_publication
    script = reconcile.remote_script(ROOT, printer, action='recover', backup=backup)
    result = json.loads(run_remote_script(script))
    assert result == {'state': 'rolled-back', 'backup': str(backup)}
    for change in planned['changes']:
        path = printer / change['file']
        assert (path.read_bytes() if path.exists() else None) == change['before']


def test_remote_restart_recovery_reports_conflict_without_writes(printer, interrupted_publication):
    planned, backup = interrupted_publication
    path = printer / planned['changes'][0]['file']
    path.write_bytes(b'operator edit after interruption')
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    result = json.loads(run_remote_script(
        reconcile.remote_script(ROOT, printer, action='recover', backup=backup)))
    assert result['state'] == 'rollback-unconfirmed'
    assert 'Concurrent edit' in result['error']
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


def test_remote_restart_recovery_requires_explicit_backup():
    with pytest.raises(ValueError, match='Invalid configuration transaction action'):
        reconcile.remote_script(ROOT, '/unused', action='recover')
    with pytest.raises(ValueError, match='Invalid configuration transaction action'):
        reconcile.remote_script(ROOT, '/unused', reviewed={}, action='recover', backup='/unused/backup')


@pytest.mark.parametrize('defect', ['candidate', 'original', 'concurrent', 'linked', 'missing'])
def test_restart_recovery_refuses_conflicts_before_mutation(printer, interrupted_publication, defect):
    planned, backup = interrupted_publication
    name = planned['changes'][0]['file']
    if defect == 'candidate':
        (backup / (name + '.after')).write_bytes(b'not reviewed')
    elif defect == 'original':
        original_name = next(c['file'] for c in planned['changes'] if c['before'] is not None)
        (backup / (original_name + '.before')).write_bytes(b'not original')
    elif defect == 'concurrent':
        (printer / name).write_bytes(b'operator change')
    elif defect == 'linked':
        saved = backup / (name + '.after')
        saved.unlink()
        saved.symlink_to(printer / name)
    else:
        (backup / (name + '.after')).unlink()
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises((ValueError, OSError, reconcile.RollbackUnconfirmed)):
        reconcile.recover_interrupted(printer, backup)
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


def vendor_parser(directory):
    if not VENDOR.is_file():
        pytest.skip('exact vendor parser required')
    spec = importlib.util.spec_from_file_location('vendor_config_for_reconcile', VENDOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.PrinterConfig.__new__(module.PrinterConfig)
    parser.printer = None
    main = directory / 'printer.cfg'
    return parser._build_config_wrapper(main.read_text(), str(main)).fileconfig


def test_plan_preserves_all_original_machine_files_and_saved_state(printer):
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    planned = reconcile.plan(ROOT, printer)
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before
    assert {c['file'] for c in planned['changes']} == {'printer.cfg', reconcile.FILENAME}
    apply_plan(printer, planned)
    for name, content in before.items():
        actual = (printer / name).read_bytes()
        assert actual.replace(reconcile.BLOCK.encode(), b'') == content if name == 'printer.cfg' else actual == content
    parsed = vendor_parser(printer)
    assert parsed.has_section('wmp_case_light')
    assert parsed.get('gcode_macro CASE_LIGHT_ON', 'gcode').strip() == 'SET_PIN PIN=case_light VALUE=1'
    assert parsed.get('printer', 'max_velocity') == '123'
    assert parsed.get('tools_calibrate', 'probe_position') == '299, 288, 7, 6, 5'
    assert parsed.get('filament_switch_sensor filament2', 'switch_pin') == 'T2:PC14'
    assert parsed.get('filament_switch_sensor filament2', 'event_delay') == '0.8'
    assert parsed.get('gcode_macro RESUME', 'variable_zhop') == '4.2'
    assert parsed.get('gcode_macro USER_LIGHT', 'gcode') == 'RESPOND MSG="keep me"'
    expected = bundle.read_active_config(ROOT / 'config/live/printer.cfg',
                                       include_paths=[ROOT / name for name in bundle.CONFIG_BASELINES])
    for section in expected.sections():
        for option in reconcile.owned_options(section):
            if expected.has_option(section, option):
                assert bundle.config_contract_value(section, option, parsed.get(section, option)) == bundle.config_contract_value(section, option, expected.get(section, option))
    assert parsed.has_section('wm_material') and parsed.has_section('wmp_recovery')
    assert not any(section.startswith('openace') for section in parsed.sections())
    assert not reconcile.plan(ROOT, printer)['changes']


def test_original_tuning_remains_editable_without_regenerating(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    custom = printer / 'custom.cfg'
    custom.write_text(custom.read_text().replace('variable_zhop: 4.2', 'variable_zhop: 6.5'))
    assert vendor_parser(printer).get('gcode_macro RESUME', 'variable_zhop') == '6.5'
    assert not reconcile.plan(ROOT, printer)['changes']


def test_material_config_can_be_installed_after_plan_and_stays_authoritative(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    material = printer / 'wm_material.cfg'
    material.write_text('[wm_material]\nload_feed_mm: 57\n')
    assert vendor_parser(printer).get('wm_material', 'load_feed_mm') == '57'
    assert not reconcile.plan(ROOT, printer)['changes']
    material.write_text('[wm_material]\nload_feed_mm: 59\n')
    assert vendor_parser(printer).get('wm_material', 'load_feed_mm') == '59'


@pytest.mark.parametrize('case', ['unowned', 'linked', 'marker', 'sensor', 'rename'])
def test_conflicts_refuse_without_changing_any_file(printer, tmp_path, case):
    if case == 'unowned':
        (printer / reconcile.FILENAME).write_text('user content')
    elif case == 'linked':
        (printer / reconcile.FILENAME).symlink_to(tmp_path / 'absent')
    elif case == 'marker':
        with (printer / 'printer.cfg').open('a') as f:
            f.write('\n# >>> WM+ screen runtime include\n')
    elif case == 'sensor':
        for path in printer.glob('*.cfg'):
            path.write_text(path.read_text().replace('switch_pin:', 'not_a_switch_pin:'))
    elif case == 'rename':
        with (printer / 'custom.cfg').open('a') as f:
            f.write('\n[gcode_macro G29]\nrename_existing: OLD_G29\n')
    else:
        apply_plan(printer, reconcile.plan(ROOT, printer))
        with (printer / reconcile.FILENAME).open('a') as f:
            f.write('\n[printer]\nmax_accel: 999\n')
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        reconcile.plan(ROOT, printer)
    assert before == {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}


def test_publish_preserves_files_and_keeps_backup(printer):
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    planned = reconcile.plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    assert json.loads((backup / 'journal.json').read_text())['state'] == 'published'
    assert (backup / 'printer.cfg.before').read_bytes() == before['printer.cfg']
    for name, data in before.items():
        actual = (printer / name).read_bytes()
        assert (actual.replace(reconcile.BLOCK.encode(), b'') if name == 'printer.cfg' else actual) == data
    assert vendor_parser(printer).get('printer', 'max_velocity') == '123'
    assert reconcile.publish(printer, reconcile.plan(ROOT, printer)) is None


@pytest.mark.parametrize('name', ['custom.cfg', 'printer.cfg', reconcile.FILENAME])
def test_publish_refuses_changes_after_review(printer, name):
    planned = reconcile.plan(ROOT, printer)
    with (printer / name).open('ab') as stream:
        stream.write(b'\n# concurrent edit\n')
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match='changed since review'):
        reconcile.publish(printer, planned)
    assert before == {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    assert not list(printer.glob('.wmp-config-backup-*'))


@pytest.mark.parametrize('after_rename', [False, True])
def test_publish_failure_restores_original_configuration(printer, monkeypatch, after_rename):
    planned = reconcile.plan(ROOT, printer)
    before = (printer / 'printer.cfg').read_bytes()
    atomic = reconcile._atomic
    failed = False

    def fail(path, data):
        nonlocal failed
        if path == printer / 'printer.cfg' and not failed:
            failed = True
            if after_rename:
                atomic(path, data)
            raise OSError('injected publication failure')
        return atomic(path, data)

    monkeypatch.setattr(reconcile, '_atomic', fail)
    with pytest.raises(OSError, match='injected'):
        reconcile.publish(printer, planned)
    assert (printer / 'printer.cfg').read_bytes() == before
    assert not (printer / reconcile.FILENAME).exists()
    backup, = printer.glob('.wmp-config-backup-*')
    assert json.loads((backup / 'journal.json').read_text())['state'] == 'rolled-back'


def test_publish_failure_does_not_overwrite_concurrent_edit(printer, monkeypatch):
    planned = reconcile.plan(ROOT, printer)
    atomic = reconcile._atomic
    edited = b'# concurrent operator edit\n'

    def fail(path, data):
        if path == printer / 'printer.cfg':
            (printer / reconcile.FILENAME).write_bytes(edited)
            raise OSError('injected failure')
        return atomic(path, data)

    monkeypatch.setattr(reconcile, '_atomic', fail)
    with pytest.raises(RuntimeError, match='rollback needs inspection'):
        reconcile.publish(printer, planned)
    assert (printer / reconcile.FILENAME).read_bytes() == edited
    backup, = printer.glob('.wmp-config-backup-*')
    journal = json.loads((backup / 'journal.json').read_text())
    assert journal['state'] == 'rollback-unconfirmed'
    assert 'Concurrent edit' in journal['rollback_errors'][0]


def test_upgrade_failure_restores_previous_managed_layer(printer, monkeypatch):
    reconcile.publish(printer, reconcile.plan(ROOT, printer))
    previous = (printer / reconcile.FILENAME).read_bytes()
    main = (printer / 'printer.cfg').read_bytes()
    planned = reconcile.plan(ROOT, printer)
    planned['changes'] = [
        {'file': reconcile.FILENAME, 'before': previous, 'after': previous + b'\n# upgrade\n'},
        {'file': 'printer.cfg', 'before': main, 'after': main + b'\n# upgrade\n'}]
    atomic = reconcile._atomic

    def fail(path, data):
        if path == printer / 'printer.cfg':
            raise OSError('injected upgrade failure')
        return atomic(path, data)

    monkeypatch.setattr(reconcile, '_atomic', fail)
    with pytest.raises(OSError, match='upgrade failure'):
        reconcile.publish(printer, planned)
    assert (printer / reconcile.FILENAME).read_bytes() == previous
    assert (printer / 'printer.cfg').read_bytes() == main


def test_publication_rejects_symlink_substitution(printer, tmp_path):
    planned = reconcile.plan(ROOT, printer)
    custom = printer / 'custom.cfg'
    outside = tmp_path / 'operator.cfg'
    outside.write_bytes(custom.read_bytes())
    custom.unlink()
    custom.symlink_to(outside)
    with pytest.raises(ValueError, match='target changed'):
        reconcile.publish(printer, planned)
    assert not (printer / reconcile.FILENAME).exists()


def test_publication_rejects_new_wildcard_include(printer):
    with (printer / 'printer.cfg').open('a') as stream:
        stream.write('\n[include operator-*.cfg]\n')
    planned = reconcile.plan(ROOT, printer)
    (printer / 'operator-new.cfg').write_text('[printer]\nmax_velocity: 99\n')
    with pytest.raises(ValueError, match='include membership changed'):
        reconcile.publish(printer, planned)
    assert not (printer / reconcile.FILENAME).exists()


def test_vendor_symlink_dependency_is_preserved_and_target_changes_refused(printer, tmp_path):
    dependency = tmp_path / 'vendor-timelapse.cfg'
    dependency.write_bytes((printer / 'timelapse.cfg').read_bytes())
    (printer / 'timelapse.cfg').unlink()
    (printer / 'timelapse.cfg').symlink_to(dependency)
    planned = reconcile.plan(ROOT, printer)
    reconcile.publish(printer, planned)
    assert (printer / 'timelapse.cfg').is_symlink()
    assert (printer / 'timelapse.cfg').resolve() == dependency
    planned = reconcile.plan(ROOT, printer)
    replacement = tmp_path / 'different.cfg'
    replacement.write_bytes(dependency.read_bytes())
    (printer / 'timelapse.cfg').unlink()
    (printer / 'timelapse.cfg').symlink_to(replacement)
    with pytest.raises(ValueError, match='target changed'):
        reconcile.publish(printer, planned)


def run_remote_script(script):
    result = subprocess.run([sys.executable, '-I', '-'], input=script, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def test_remote_planning_and_publication_are_self_contained(printer):
    before = (printer / 'printer.cfg').read_bytes()
    result = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer)))
    assert (printer / 'printer.cfg').read_bytes() == before
    assert '[wmp_recovery]' in result['texts'][reconcile.FILENAME]
    receipt = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer, result['plan'])))
    assert Path(receipt['backup']).is_dir()
    assert vendor_parser(printer).get('printer', 'max_velocity') == '123'
    again = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer)))
    assert not again['plan']['changes']


def test_unified_installer_uses_preservation_instead_of_bulk_upload(printer, monkeypatch):
    import preflight
    from components import config, material
    monkeypatch.setattr(bundle, 'bundle_relative', lambda root: bundle.CURRENT_BUNDLE)
    # Source-manifest integrity is exercised by the current delivery tests.
    monkeypatch.setattr(bundle, 'verify_source_binding', lambda root: None)
    monkeypatch.setattr(config, '_sync', lambda *a, **kw: pytest.fail('bulk config upload'))
    events = []
    monkeypatch.setattr(material, 'install', lambda ctx, **kwargs: events.append('helper'))

    def remote(ctx, script, **kwargs):
        script = script.replace('/home/test/printer_data/config', str(printer))
        events.append('publish' if '\n    backup = r.publish(' in script else 'plan')
        return run_remote_script(script)

    monkeypatch.setattr(preflight, 'remote', remote)
    ctx = SimpleNamespace(config_only=False, files=[], user='test', ssh=lambda: None,
                          DeployError=deploy.DeployError)
    preflight.config_plan(ctx)
    config.install(ctx)
    assert events == ['plan', 'helper', 'publish']
    assert vendor_parser(printer).get('gcode_macro RESUME', 'variable_zhop') == '4.2'


@pytest.mark.parametrize('config_only,files', [(True, []), (False, ['macros.cfg'])])
def test_unified_installer_rejects_bulk_update_options(monkeypatch, config_only, files):
    import preflight
    monkeypatch.setattr(bundle, 'bundle_relative', lambda root: bundle.CURRENT_BUNDLE)
    ctx = SimpleNamespace(config_only=config_only, files=files, DeployError=deploy.DeployError)
    with pytest.raises(deploy.DeployError, match='preserves configuration through SSH'):
        preflight.config_plan(ctx)


@pytest.mark.parametrize('outcome,restores', [('failed-confirmed', True), ('failed-unknown', False), ('lost-reply', False)])
def test_config_failure_restores_helpers_only_with_confirmed_rollback(monkeypatch, outcome, restores):
    import preflight
    from components import config, material
    monkeypatch.setattr(bundle, 'bundle_relative', lambda root: bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(bundle, 'verify_source_binding', lambda root: None)
    receipt = object()
    monkeypatch.setattr(material, 'install', lambda ctx, **kw: receipt)
    rolled_back = []
    monkeypatch.setattr(material, 'rollback', lambda ctx, changes: rolled_back.append(changes))
    def remote(*args, **kwargs):
        if outcome == 'lost-reply':
            raise OSError('connection lost')
        return json.dumps({'state': 'failed', 'rollback_confirmed': outcome == 'failed-confirmed', 'error': 'injected'})
    monkeypatch.setattr(preflight, 'remote', remote)
    ctx = SimpleNamespace(config_only=False, files=[], user='test', screen_config_plan={}, DeployError=deploy.DeployError)
    with pytest.raises(deploy.DeployError):
        config.install(ctx)
    assert rolled_back == ([receipt] if restores else [])


def test_restore_successful_publication_is_repeatable_and_preserves_state(printer):
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    planned = reconcile.plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    for _ in range(2):
        reconcile.restore(printer, planned, backup)
        assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before
        assert json.loads((backup/'journal.json').read_text())['state'] == 'rolled-back'


@pytest.mark.parametrize('name', ['printer.cfg', reconcile.FILENAME])
def test_restore_refuses_concurrent_edit_before_any_restoration(printer, name):
    planned = reconcile.plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    (printer/name).write_bytes(b'# operator edit\n')
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises(reconcile.RollbackUnconfirmed, match='Concurrent edit'):
        reconcile.restore(printer, planned, backup)
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('case', ['backup', 'journal', 'symlink', 'duplicate'])
def test_restore_rejects_bad_receipt_without_changes(printer, tmp_path, case):
    planned = reconcile.plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    if case == 'backup':
        (backup/'printer.cfg.before').write_bytes(b'corrupt')
    elif case == 'journal':
        journal = json.loads((backup/'journal.json').read_text())
        journal['files'][0]['after'] = 'invalid'
        (backup/'journal.json').write_text(json.dumps(journal))
    elif case == 'duplicate':
        planned['changes'].append(planned['changes'][0])
    else:
        path = printer/reconcile.FILENAME
        outside = tmp_path/'outside.cfg'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        reconcile.restore(printer, planned, backup)
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('after_write', [False, True])
def test_restore_write_failure_is_explicit_and_retryable(printer, monkeypatch, after_write):
    planned = reconcile.plan(ROOT, printer)
    original = (printer/'printer.cfg').read_bytes()
    backup = reconcile.publish(printer, planned)
    atomic = reconcile._atomic
    def fail(path, data):
        if path == printer/'printer.cfg':
            if after_write:
                atomic(path, data)
            raise OSError('lost write acknowledgement')
        atomic(path, data)
    monkeypatch.setattr(reconcile, '_atomic', fail)
    with pytest.raises(reconcile.RollbackUnconfirmed):
        reconcile.restore(printer, planned, backup)
    assert json.loads((backup/'journal.json').read_text())['state'] == 'rollback-unconfirmed'
    monkeypatch.setattr(reconcile, '_atomic', atomic)
    reconcile.restore(printer, planned, backup)
    assert (printer/'printer.cfg').read_bytes() == original
    assert not (printer/reconcile.FILENAME).exists()


def test_restore_detects_edit_between_restoration_writes(printer, monkeypatch):
    planned = reconcile.plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    atomic = reconcile._atomic
    def edit_after_restore(path, data):
        atomic(path, data)
        if path == printer/'printer.cfg':
            # The next restoration operation must see the changed sibling.
            (printer/reconcile.FILENAME).write_bytes(b'# concurrent edit\n')
    monkeypatch.setattr(reconcile, '_atomic', edit_after_restore)
    with pytest.raises(reconcile.RollbackUnconfirmed):
        reconcile.restore(printer, planned, backup)
    assert (printer/reconcile.FILENAME).read_bytes() == b'# concurrent edit\n'
    assert json.loads((backup/'journal.json').read_text())['state'] == 'rollback-unconfirmed'


def test_restore_no_changes_needs_no_backup(printer):
    reconcile.publish(printer, reconcile.plan(ROOT, printer))
    planned = reconcile.plan(ROOT, printer)
    assert not planned['changes']
    reconcile.restore(printer, planned, None)


def test_remote_restore_is_self_contained(printer):
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    plan = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer)))['plan']
    receipt = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer, plan)))
    result = json.loads(run_remote_script(reconcile.remote_script(
        ROOT, printer, plan, action='restore', backup=receipt['backup'])))
    assert result == {'state': 'rolled-back'}
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


def test_config_receipt_restores_config_before_helpers(printer, monkeypatch):
    import preflight
    from components import config, material
    monkeypatch.setattr(bundle, 'bundle_relative', lambda root: bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(bundle, 'verify_source_binding', lambda root: None)
    before = (printer/'printer.cfg').read_bytes()
    helper_receipt = object()
    monkeypatch.setattr(material, 'install', lambda ctx, **kw: helper_receipt)
    restored = []
    def restore_helpers(ctx, receipt):
        assert (printer/'printer.cfg').read_bytes() == before
        assert not (printer/reconcile.FILENAME).exists()
        restored.append(receipt)
    monkeypatch.setattr(material, 'rollback', restore_helpers)
    monkeypatch.setattr(preflight, 'remote', lambda ctx, script, **kw:
                        run_remote_script(script.replace('/home/test/printer_data/config', str(printer))))
    ctx = SimpleNamespace(config_only=False, files=[], user='test', ssh=lambda: None,
                          DeployError=deploy.DeployError)
    preflight.config_plan(ctx)
    receipt = config.install(ctx)
    assert receipt['helpers'] is helper_receipt
    ctx.screen_config_plan.clear()  # Receipt must not alias a later preflight.
    config.rollback(ctx, receipt)
    assert restored == [helper_receipt]


@pytest.mark.parametrize('outcome', ['lost-reply', 'malformed', 'unconfirmed'])
def test_config_rollback_retains_helpers_when_config_restore_unknown(monkeypatch, outcome):
    import preflight
    from components import config, material
    def remote(*args, **kw):
        if outcome == 'lost-reply':
            raise OSError('connection lost')
        if outcome == 'malformed':
            return 'not JSON'
        return json.dumps({'state': 'rollback-unconfirmed', 'error': 'concurrent edit'})
    monkeypatch.setattr(preflight, 'remote', remote)
    monkeypatch.setattr(material, 'rollback', lambda *a: pytest.fail('unsafe helper restoration'))
    ctx = SimpleNamespace(user='test', DeployError=deploy.DeployError)
    receipt = dict(kind='preserved-screen-config', plan={'changes': []}, backup=None, helpers=[])
    with pytest.raises(deploy.DeployError, match='retained matching helpers'):
        config.rollback(ctx, receipt)


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('lost_reply', [False, True])
def test_config_install_and_rollback_with_real_helper_publication(printer, tmp_path, monkeypatch, existing, lost_reply):
    import preflight
    from components import config
    from test_material_install import setup
    ctx, sftp, extra, cfg = setup(tmp_path/'remote', existing=existing)
    directory = sftp.path(cfg).parent
    shutil.copytree(printer, directory, dirs_exist_ok=True)
    ctx.config_only = False
    ctx.files = []
    ctx.ssh = lambda: None
    ctx.DeployError = deploy.DeployError
    monkeypatch.setattr(bundle, 'bundle_relative', lambda root: bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(bundle, 'verify_source_binding', lambda root: None)
    def remote(ctx, script, **kw):
        script=script.replace("directory = pathlib.Path('/home/printer/printer_data/config')",
                              'directory = pathlib.Path(%r)' % str(directory))
        script=script.replace("'/home/printer/printer_data/config/.wmp-config-backup-",
                              "'"+str(directory)+'/.wmp-config-backup-')
        result=run_remote_script(script)
        if lost_reply and json.loads(result).get('state')=='published':
            raise SystemExit('lost installer after configuration publication')
        return result
    monkeypatch.setattr(preflight, 'remote', remote)
    def snapshot():
        return {str(p.relative_to(sftp.root)): p.read_bytes() for p in sftp.root.rglob('*')
                if p.is_file() and not any('.wmp-' in part for part in p.relative_to(sftp.root).parts)}
    before = snapshot()
    preflight.config_plan(ctx)
    if lost_reply:
        from install_journal import Journal
        journal=Journal(tmp_path/'installer.json')
        journal.create('printer','printer',['config']);journal.begin('config')
        ctx.rollback_backend=SimpleNamespace(journal=journal)
        ctx.host='printer';ctx.printing_now=lambda:False
        with pytest.raises(SystemExit):config.install(ctx)
        assert Journal(journal.path).load('printer','printer').value['inflight']=='config'
        deploy.recover_installation(ctx,journal.path)
        assert snapshot()==before
        assert Journal(journal.path).load('printer','printer').value['state']=='restored'
        return
    receipt = config.install(ctx)
    assert {Path(row[0]).name for row in receipt['helpers']} == set(MATERIAL_HELPERS) | {
        'wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'}
    assert (directory/reconcile.FILENAME).is_file()
    for name in MATERIAL_HELPERS + ('wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'):
        assert sftp.path(extra).with_name(name).read_bytes() == (ROOT/'klipper_extras'/name).read_bytes()
    config.rollback(ctx, receipt)
    assert snapshot() == before
    config.rollback(ctx, receipt)
    assert snapshot() == before


@pytest.mark.parametrize('after_write',[False,True])
def test_named_backup_recovers_process_loss_during_publication(printer,monkeypatch,after_write):
    planned=reconcile.plan(ROOT,printer)
    before={change['file']:change['before'] for change in planned['changes']}
    backup=printer/'.wmp-config-backup-preselected'
    atomic=reconcile._atomic
    def interrupted(path,data):
        if path==printer/reconcile.FILENAME:
            if after_write:atomic(path,data)
            raise SystemExit('process lost during publish')
        return atomic(path,data)
    monkeypatch.setattr(reconcile,'_atomic',interrupted)
    with pytest.raises(SystemExit):reconcile.publish(printer,planned,backup)
    assert (backup/'journal.json').is_file()
    monkeypatch.setattr(reconcile,'_atomic',atomic)
    reconcile.restore(printer,planned,backup)
    for name,expected in before.items():
        path=printer/name
        assert (path.read_bytes() if path.exists() else None)==expected


def test_named_backup_never_reuses_existing_directory(printer):
    planned=reconcile.plan(ROOT,printer)
    backup=printer/'.wmp-config-backup-preselected';backup.mkdir()
    (backup/'operator.txt').write_text('keep')
    before=(printer/'printer.cfg').read_bytes()
    with pytest.raises(FileExistsError):reconcile.publish(printer,planned,backup)
    assert (backup/'operator.txt').read_text()=='keep'
    assert (printer/'printer.cfg').read_bytes()==before


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('position',[1,3,5])
@pytest.mark.parametrize('after_rename',[False,True])
def test_config_helper_phase_process_loss_is_recoverable(tmp_path,monkeypatch,existing,position,after_rename):
    import preflight
    from components import config
    from install_journal import Journal
    from test_material_install import setup,snapshot
    ctx,sftp,extra,cfg=setup(tmp_path/'remote',existing=existing)
    ctx.config_only=False;ctx.files=[];ctx.screen_config_plan={'changes':[]}
    ctx.DeployError=deploy.DeployError;ctx.host='printer';ctx.printing_now=lambda:False
    journal=Journal(tmp_path/'install.json')
    journal.create('printer','printer',['config']);journal.begin('config')
    ctx.rollback_backend=SimpleNamespace(journal=journal)
    monkeypatch.setattr(bundle,'bundle_relative',lambda root:bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(bundle,'verify_source_binding',lambda root:None)
    monkeypatch.setattr(preflight,'remote',lambda *args,**kw:pytest.fail('config touched during helper phase'))
    before=snapshot(tmp_path/'remote')
    rename=sftp.posix_rename;attempts=[]
    def interrupted(source,destination):
        attempts.append(destination)
        if len(attempts)!=position:return rename(source,destination)
        if after_rename:rename(source,destination)
        raise SystemExit('helper process lost')
    monkeypatch.setattr(sftp,'posix_rename',interrupted)
    with pytest.raises(SystemExit):config.install(ctx)
    saved=Journal(journal.path).load('printer','printer')
    assert saved.recovery_receipts()[0][1]['kind']=='config-helpers'
    monkeypatch.setattr(sftp,'posix_rename',rename)
    deploy.recover_installation(ctx,journal.path)
    assert snapshot(tmp_path/'remote')==before
    assert Journal(journal.path).load('printer','printer').value['state']=='restored'


@pytest.mark.parametrize('spacing', ['\n', '\n\n', ' \t\n'])
def test_existing_last_include_preserves_spacing_before_saved_calibration(printer, spacing):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    path = printer / 'printer.cfg'
    raw = path.read_bytes().replace(reconcile.SAVE_MARKER,
                                   spacing.encode() + reconcile.SAVE_MARKER)
    path.write_bytes(raw)
    planned = reconcile.plan(ROOT, printer)
    assert planned['changes'] == []
    assert path.read_bytes() == raw


def test_existing_include_moves_after_new_executable_configuration(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    path = printer / 'printer.cfg'
    raw = path.read_bytes().replace(reconcile.SAVE_MARKER,
        b'[gcode_macro USER_ADDED]\ngcode: M400\n' + reconcile.SAVE_MARKER)
    path.write_bytes(raw)
    planned = reconcile.plan(ROOT, printer)
    change = next(row for row in planned['changes'] if row['file'] == 'printer.cfg')
    assert change['after'].index(b'[gcode_macro USER_ADDED]') < change['after'].index(reconcile.BLOCK.encode())
    assert change['after'].partition(reconcile.SAVE_MARKER)[2] == raw.partition(reconcile.SAVE_MARKER)[2]
    apply_plan(printer, planned)
    assert reconcile.plan(ROOT, printer)['changes'] == []


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_standalone_plan_refuses_included_manager_without_writes(printer, owner):
    manager = printer / 'optional-manager.cfg'
    manager.write_text('[' + owner + ']\n')
    main = printer / 'printer.cfg'
    main.write_text('[include optional-manager.cfg]\n' + main.read_text())
    before = {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()}
    with pytest.raises(ValueError, match='standalone WM.*active ' + owner):
        reconcile.plan(ROOT, printer)
    assert {p.name: p.read_bytes() for p in printer.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_standalone_plan_preserves_disabled_manager(printer, owner):
    manager = printer / 'optional-manager.cfg'
    manager.write_text('[' + owner + ']\n')
    main = printer / 'printer.cfg'
    main.write_text('# [include optional-manager.cfg]\n' + main.read_text())
    planned = reconcile.plan(ROOT, printer)
    assert 'optional-manager.cfg' not in planned['read_hashes']
    assert manager.read_text() == '[' + owner + ']\n'


def test_exported_plan_roundtrips_utf8_on_ascii_host(printer, tmp_path, monkeypatch):
    # Simulate a Windows/non-UTF8 host when exporting both Python and config.
    exported = tmp_path / 'exported'
    for name in ('tools/preload_bundle.py', 'tools/reconcile_screen_config.py', *bundle.CONFIG_BASELINES):
        target = exported / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes() + '\n# café 日本\n'.encode('utf-8'))
    custom = printer / 'custom.cfg'
    custom.write_bytes(custom.read_bytes() + '\n# café 日本\n'.encode('utf-8'))
    original = Path.read_text
    def ascii_default(path, encoding=None, errors=None):
        return original(path, encoding=encoding or 'ascii', errors=errors)
    monkeypatch.setattr(Path, 'read_text', ascii_default)
    script = reconcile.remote_script(exported, printer)
    # Apply the same default to the exported remote reader/writer, exercising
    # the complete generated script rather than inspecting its source text.
    prelude = """from pathlib import Path
_read = Path.read_text
_write = Path.write_text
def read(path, encoding=None, errors=None):
    return _read(path, encoding=encoding or 'ascii', errors=errors)
def write(path, data, encoding=None, errors=None):
    return _write(path, data, encoding=encoding or 'ascii', errors=errors)
Path.read_text = read
Path.write_text = write
"""
    result = json.loads(run_remote_script(prelude + script))
    assert 'café 日本' in result['texts']['custom.cfg']
    assert result['plan']['changes']


def test_removal_preserves_machine_calibration_and_custom_sections(printer):
    original = (printer/'printer.cfg').read_bytes()
    apply_plan(printer, reconcile.plan(ROOT, printer))
    runtime = printer/reconcile.FILENAME
    with runtime.open('a') as stream:
        stream.write('\n[gcode_macro USER_AFTER_INSTALL]\ngcode: RESPOND MSG="café"\n')
    planned = reconcile.removal_plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    actual = bundle.read_active_config(printer/'printer.cfg')
    assert actual.get('gcode_macro USER_AFTER_INSTALL', 'gcode') == 'RESPOND MSG="café"'
    assert actual.get('gcode_macro USER_LIGHT', 'gcode') == 'RESPOND MSG="keep me"'
    assert not actual.has_section('wmp_recovery')
    assert not actual.has_section('wm_material')
    assert not planned['retained_dependencies']
    assert (printer/'printer.cfg').read_bytes().partition(reconcile.SAVE_MARKER)[2] == original.partition(reconcile.SAVE_MARKER)[2]
    assert (printer/'wmp_filaments.json').read_text() == '{"h2":{"brand":"Sunlu"}}'
    assert backup.exists()
    assert reconcile.removal_plan(ROOT, printer)['changes'] == []


def test_removal_retains_edited_macro_and_its_helpers(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    runtime = printer/reconcile.FILENAME
    text = runtime.read_text()
    text = text.replace('WMP_CHECK_RESUME', 'WMP_CHECK_RESUME\n\tRESPOND MSG="my edit"')
    runtime.write_text(text)
    planned = reconcile.removal_plan(ROOT, printer)
    reconcile.publish(printer, planned)
    actual = bundle.read_active_config(printer/'printer.cfg')
    assert 'my edit' in runtime.read_text()
    assert planned['retained_dependencies']
    assert actual.has_section('wm_material')


def test_material_removal_preserves_unrelated_cfg_sections_without_receipt(printer):
    with (printer/'printer.cfg').open('a') as stream: stream.write('\n[include wm_material.cfg]\n')
    (printer/'wm_material.cfg').write_text('[wm_material]\nload_feed_mm: 55\n\n[gcode_macro USER]\ngcode: M118 keep\n')
    planned = reconcile.removal_plan(ROOT, printer, material_only=True)
    assert not planned['retained_dependencies']
    reconcile.publish(printer, planned)
    actual = bundle.read_active_config(printer/'printer.cfg')
    assert not actual.has_section('wm_material')
    assert actual.get('gcode_macro USER', 'gcode') == 'M118 keep'
    assert 'load_feed_mm: 55' in (printer/'wm_material.cfg').read_text()


def test_removal_remote_plan_roundtrips_utf8(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    script = reconcile.remote_script(ROOT, str(printer), action='remove-plan')
    result = subprocess.run([sys.executable, '-'], input=script, text=True, capture_output=True, check=True)
    planned = json.loads(result.stdout)['plan']
    assert planned['changes'] and not planned['retained_dependencies']


@pytest.mark.parametrize('component', ['config', 'material'])
def test_uninstall_entrypoint_disables_config_before_deleting_helpers(printer, monkeypatch, component):
    from components import config, material
    import preflight
    apply_plan(printer, reconcile.plan(ROOT, printer))
    # Config removal precedes material removal in a full uninstall.
    if component == 'material':
        reconcile.publish(printer, reconcile.removal_plan(ROOT, printer))
    calls = []
    original = reconcile.remote_script
    monkeypatch.setattr(reconcile, 'remote_script',
        lambda root, directory, *args, **kwargs: original(root, printer, *args, **kwargs))
    def remote(ctx, script, **kwargs):
        result = subprocess.run([sys.executable, '-'], input=script, text=True,
                                capture_output=True, check=True)
        return result.stdout
    monkeypatch.setattr(preflight, 'remote', remote)
    class SFTP:
        def open(self, path, mode):
            import io
            return io.BytesIO(b'installed helper')
        def remove(self, path):
            active = bundle.read_active_config(printer/'printer.cfg')
            assert not set(active.sections()) & {'wm_material','wmp_recovery','wmp_case_light'}
            calls.append(path)
    ctx = SimpleNamespace(user='printer', sftp=lambda: SFTP(), DeployError=RuntimeError)
    (config if component == 'config' else material).uninstall(ctx)
    assert calls
    assert all(path.endswith('.py') for path in calls)


def test_material_uninstall_retains_helpers_for_remaining_user_macro(printer, monkeypatch):
    from components import material
    import preflight
    with (printer/'printer.cfg').open('a') as stream:
        stream.write('\n[include wm_material.cfg]\n[gcode_macro USER_LOAD]\ngcode: WMP_FILAMENT_SEQUENCE\n')
    (printer/'wm_material.cfg').write_text('[wm_material]\nload_feed_mm: 55\n')
    original = reconcile.remote_script
    monkeypatch.setattr(reconcile, 'remote_script',
        lambda root, directory, *args, **kwargs: original(root, printer, *args, **kwargs))
    monkeypatch.setattr(preflight, 'remote', lambda ctx, script, **kw:
        subprocess.run([sys.executable,'-'], input=script, text=True, capture_output=True, check=True).stdout)
    ctx = SimpleNamespace(user='printer', sftp=lambda: pytest.fail('must retain referenced helpers'), DeployError=RuntimeError)
    material.uninstall(ctx)
    assert bundle.read_active_config(printer/'printer.cfg').has_section('wm_material')


def test_lost_removal_publication_reply_never_deletes_helpers(printer, monkeypatch):
    from components import config
    import preflight
    apply_plan(printer, reconcile.plan(ROOT, printer))
    original = reconcile.remote_script
    monkeypatch.setattr(reconcile, 'remote_script',
        lambda root, directory, *args, **kwargs: original(root, printer, *args, **kwargs))
    calls = []
    def remote(ctx, script, **kwargs):
        result = subprocess.run([sys.executable,'-'], input=script, text=True, capture_output=True, check=True)
        calls.append(True)
        if len(calls) == 2: raise OSError('lost publication acknowledgement')
        return result.stdout
    monkeypatch.setattr(preflight, 'remote', remote)
    ctx = SimpleNamespace(user='printer', sftp=lambda: pytest.fail('unconfirmed removal retains helpers'), DeployError=RuntimeError)
    with pytest.raises(RuntimeError, match='helper modules retained.*lost publication'): config.uninstall(ctx)
    assert not bundle.read_active_config(printer/'printer.cfg').has_section('wmp_recovery')
    # Retry replans from actual bytes without replaying an old snapshot.
    assert reconcile.removal_plan(ROOT, printer)['changes'] == []


@pytest.mark.parametrize('command', ['WMP_TOOLHEAD_ACTION', 'wmp_toolhead_action'])
def test_removal_retains_helpers_used_by_custom_command_case(printer, command):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    runtime = printer / reconcile.FILENAME
    with runtime.open('a', encoding='utf-8') as stream:
        stream.write('\n[gcode_macro USER_SERVICE]\ngcode: %s HEAD=2 ACTION=dock\n' % command)
    planned = reconcile.removal_plan(ROOT, printer)
    assert 'gcode_macro USER_SERVICE' in planned['retained_dependencies']
    apply_plan(printer, planned)
    assert bundle.read_active_config(printer / 'printer.cfg').has_section('wm_material')


def test_removal_preserves_edited_toolchange_macro_dependency_closure(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    runtime = printer / reconcile.FILENAME
    runtime.write_text(runtime.read_text(encoding='utf-8').replace(
        '_WMP_TOOL_RETURN_BEGIN T={params.T|int}',
        '_WMP_TOOL_RETURN_BEGIN T={params.T|int}\n\tRESPOND MSG="my café tool change"'), encoding='utf-8')
    before = bundle.read_active_config(printer / 'printer.cfg')
    planned = reconcile.removal_plan(ROOT, printer)
    apply_plan(printer, planned)
    after = bundle.read_active_config(printer / 'printer.cfg')
    assert after.get('gcode_macro _CHANGE_TOOL', 'gcode') == before.get('gcode_macro _CHANGE_TOOL', 'gcode')
    for name in ('_WMP_TOOL_RETURN_BEGIN', '_WMP_TOOL_RETURN_FINISH', '_WMP_CALIBRATION_CLEARANCE'):
        section = 'gcode_macro ' + name
        assert after.get(section, 'gcode') == before.get(section, 'gcode')
        assert section in planned['retained_sections']
    assert after.has_section('wm_material')


@pytest.mark.parametrize('body', [
    '_wmp_require_release T=2',
    '{% if params.RUN %}_wmp_require_release T=2{% endif %}',
    'SET_GCODE_VARIABLE MACRO=_WMP_TOOL_RETURN_BEGIN VARIABLE=pending VALUE=0',
    '{params.COMMAND}',
    'UPDATE_DELAYED_GCODE ID={params.TIMER} DURATION=1',
])
def test_removal_preserves_custom_macro_targets_without_rewriting(printer, body):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    custom = printer / 'custom.cfg'
    with custom.open('a', encoding='utf-8') as stream:
        stream.write('\n[gcode_macro USER_SERVICE]\ngcode: ' + body + '\n')
    before = custom.read_bytes()
    planned = reconcile.removal_plan(ROOT, printer)
    apply_plan(printer, planned)
    active = bundle.read_active_config(printer / 'printer.cfg')
    assert custom.read_bytes() == before
    assert active.get('gcode_macro USER_SERVICE', 'gcode') == body
    if '{params.' in body:
        assert any('USER_SERVICE (dynamic command target' in row for row in planned['retained_dependencies'])
        assert active.has_section('gcode_macro _WMP_TOOL_RETURN_BEGIN')
        assert active.has_section('gcode_macro _WMP_REQUIRE_RELEASE')
    elif 'require_release' in body:
        assert active.has_section('gcode_macro _WMP_REQUIRE_RELEASE')
        assert active.has_section('gcode_macro _WMP_ABORT_DOCKING')
    else:
        assert active.has_section('gcode_macro _WMP_TOOL_RETURN_BEGIN')


def test_remote_removal_preserves_custom_dynamic_targets(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    with (printer / 'custom.cfg').open('a', encoding='utf-8') as stream:
        stream.write('\n[gcode_macro USER_DYNAMIC]\ngcode: {params.COMMAND}\n')
    result = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer, action='remove-plan')))
    planned = result['plan']
    assert any('USER_DYNAMIC (dynamic command target' in row for row in planned['retained_dependencies'])
    assert 'gcode_macro _WMP_REQUIRE_RELEASE' in planned['retained_sections']


def test_managed_user_addition_survives_upgrade(printer):
    apply_plan(printer, reconcile.plan(ROOT, printer))
    with (printer / reconcile.FILENAME).open('a') as stream:
        stream.write('\n[printer]\nmax_accel: 999\n')
    planned = reconcile.plan(ROOT, printer)
    assert any('printer / max_accel' in warning for warning in planned['warnings'])
    apply_plan(printer, planned)
    assert vendor_parser(printer).get('printer', 'max_accel') == '999'
    assert not reconcile.plan(ROOT, printer)['changes']


@pytest.mark.parametrize('edited', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_obsolete_generated_option_three_way(printer, monkeypatch, edited, legacy):
    read = bundle.read_active_config
    def old_release(path, **kwargs):
        parsed = read(path, **kwargs)
        if Path(path) == ROOT/'config/live/printer.cfg':
            parsed.set('gcode_macro G29', 'variable_retired_test', '1')
        return parsed
    with monkeypatch.context() as patch:
        patch.setattr(bundle, 'read_active_config', old_release)
        planned = reconcile.plan(ROOT, printer)
        if legacy:
            for change in planned['changes']:
                if change['file'] == reconcile.FILENAME:
                    change['after'] = b''.join(line for line in change['after'].splitlines(keepends=True) if not line.startswith(reconcile.OWNERSHIP.encode()))
        reconcile.publish(printer, planned)
    managed = printer/reconcile.FILENAME
    if edited:
        managed.write_bytes(managed.read_bytes().replace(b'variable_retired_test = 1', b'variable_retired_test = 2'))
    apply_plan(printer, reconcile.plan(ROOT, printer))
    parsed = vendor_parser(printer)
    # Legacy artifacts cannot prove whether a variable came from the factory
    # or was carried through from user configuration. Preserve that ambiguity.
    assert parsed.has_option('gcode_macro G29', 'variable_retired_test') == (edited or legacy)
    if edited or legacy:
        assert parsed.get('gcode_macro G29', 'variable_retired_test') == ('2' if edited else '1')


@pytest.mark.parametrize('missing', [1, 2, 3, 4])
def test_optional_sensor_absence_omits_only_dependent_hooks(printer, missing):
    import re
    for path in printer.glob('*.cfg'):
        text = path.read_text()
        for head in range(missing):
            text = re.sub(r'(?ms)^\[filament_switch_sensor filament%d\].*?(?=^\[|\Z)' % head, '', text)
        path.write_text(text)
    planned = reconcile.plan(ROOT, printer)
    assert len([warning for warning in planned['warnings'] if 'Omitted optional' in warning]) == missing
    generated = next(change['after'].decode() for change in planned['changes'] if change['file'] == reconcile.FILENAME)
    for head in range(missing):
        assert '[filament_switch_sensor filament%d]' % head not in generated
        assert '[delayed_gcode delayed_pause%d]' % head not in generated
    apply_plan(printer, planned)
    vendor_parser(printer)


def test_missing_sensor_with_custom_consumer_still_requires_repair(printer):
    import re
    path = printer/'extruder0.cfg'
    path.write_text(re.sub(r'(?ms)^\[filament_switch_sensor filament0\].*?(?=^\[|\Z)', '', path.read_text()))
    with (printer/'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro CUSTOM_RUNOUT]\ngcode: UPDATE_DELAYED_GCODE ID=delayed_pause0 DURATION=1\n')
    with pytest.raises(ValueError, match='required by retained configuration'):
        reconcile.plan(ROOT, printer)


def test_legacy_artifact_distinguishes_package_body_from_user_default(printer, monkeypatch):
    read = bundle.read_active_config
    with (printer/'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro G29]\nvariable_user_origin: 77\n[gcode_macro USER_CARRIED]\ngcode: RESPOND MSG=user\n')
    def old_release(path, **kwargs):
        parsed = read(path, **kwargs)
        if Path(path) == ROOT/'config/live/printer.cfg':
            parsed.add_section('gcode_macro OLD_PACKAGE_HOOK')
            parsed.set('gcode_macro OLD_PACKAGE_HOOK', 'gcode', 'RESPOND MSG=old_package')
        return parsed
    with monkeypatch.context() as patch:
        patch.setattr(bundle, 'read_active_config', old_release)
        planned = reconcile.plan(ROOT, printer)
        for change in planned['changes']:
            if change['file'] == reconcile.FILENAME:
                change['after'] = b''.join(line for line in change['after'].splitlines(keepends=True) if not line.startswith(reconcile.OWNERSHIP.encode()))
                # Older output could carry a user/default variable into generated
                # config. Its published artifact hash is not ownership evidence.
                change['after'] += b'\n[gcode_macro USER_CARRIED]\nvariable_setting = 77\n'
        reconcile.publish(printer, planned)
    planned = reconcile.plan(ROOT, printer)
    apply_plan(printer, planned)
    parsed = vendor_parser(printer)
    assert not parsed.has_section('gcode_macro OLD_PACKAGE_HOOK')
    assert parsed.get('gcode_macro USER_CARRIED', 'variable_setting') == '77'
    assert any('USER_CARRIED' in warning for warning in planned['warnings'])


def test_legacy_provenance_is_not_an_active_include(printer):
    planned = reconcile.plan(ROOT, printer)
    for change in planned['changes']:
        if change['file'] == reconcile.FILENAME:
            change['after'] = b''.join(line for line in change['after'].splitlines(keepends=True) if not line.startswith(reconcile.OWNERSHIP.encode()))
    reconcile.publish(printer, planned)
    result = json.loads(run_remote_script(reconcile.remote_script(ROOT, printer)))
    provenance = result['plan']['provenance_files']
    assert provenance and all(name in result['plan']['read_hashes'] for name in provenance)
    assert all(name not in result['texts'] for name in provenance)
    assert all('.wmp-config-backup-' not in pattern for pattern in result['plan']['include_matches'])


@pytest.mark.parametrize('distance,expected', [('50.0', 150.), ('80.0', 80.), ('0', 0.)])
def test_finish_bed_drop_upgrade_migrates_old_default_only(printer, distance, expected):
    with (printer / 'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro PRINT_END]\nvariable_bed_drop: ' + distance + '\n')
    for _ in range(3):
        apply_plan(printer, reconcile.plan(ROOT, printer))
        current = bundle.read_active_config(printer / 'printer.cfg')
        assert current.getfloat('gcode_macro PRINT_END', 'variable_bed_drop') == expected


def test_install_and_upgrade_preserve_all_extruder_rotation_distances(printer):
    import re
    values = {'extruder': 21.6485, 'extruder1': 21.6485,
              'extruder2': 21.6485, 'extruder3': 21.7441}
    path = printer / 'printer.cfg'
    text = path.read_text()
    for section, value in values.items():
        pattern = r'(?ms)(^\[' + re.escape(section) + r'\]\n.*?^rotation_distance\s*[:=])[^\n]*'
        text, count = re.subn(pattern, lambda match: match[1] + str(value), text)
        assert count == 1
    path.write_text(text)
    for _ in range(2):  # First installation and subsequent upgrade.
        apply_plan(printer, reconcile.plan(ROOT, printer))
        actual = vendor_parser(printer)
        assert {section: actual.getfloat(section, 'rotation_distance')
                for section in values} == values
        managed = (printer / reconcile.FILENAME).read_text()
        assert 'rotation_distance' not in managed


@pytest.mark.parametrize('rate,expected', [('200.0',500.),('300.0',300.),('350.0',350.),('500.0',500.)])
def test_print_return_upgrade_migrates_old_default_only(printer, rate, expected):
    with (printer / 'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro _WMP_TOOL_RETURN_BEGIN]\nvariable_return_speed: ' + rate + '\n')
    original = (printer / 'custom.cfg').read_bytes()
    for _ in range(2):
        apply_plan(printer, reconcile.plan(ROOT, printer))
        current = vendor_parser(printer)
        assert current.getfloat('gcode_macro _WMP_XY_TRAVEL', 'variable_hot_travel_speed') == expected
        assert (printer / 'custom.cfg').read_bytes() == original


def test_shared_travel_settings_override_legacy_and_survive_upgrade(printer):
    with (printer / 'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro _WMP_TOOL_RETURN_BEGIN]\nvariable_return_speed: 350\n'
                     '[gcode_macro _WMP_XY_TRAVEL]\nvariable_travel_speed: 225\nvariable_hot_travel_speed: 475\n')
    original = (printer / 'custom.cfg').read_bytes()
    for _ in range(2):
        apply_plan(printer, reconcile.plan(ROOT, printer))
        current = vendor_parser(printer)
        assert current.getfloat('gcode_macro _WMP_XY_TRAVEL', 'variable_travel_speed') == 225
        assert current.getfloat('gcode_macro _WMP_XY_TRAVEL', 'variable_hot_travel_speed') == 475
        assert (printer / 'custom.cfg').read_bytes() == original
