"""Factory behavior restoration after legacy whole-file and repeated installs."""
import json
import shutil
from pathlib import Path

import pytest
from test_screen_config_reconcile import printer, apply_plan, ROOT
import reconcile_screen_config as reconcile
import preload_bundle as bundle


def legacy_bytes(name):
    """Pinned published code, independent of the candidate's new macros."""
    import gzip, hashlib
    directory = ROOT/'tests/fixtures/config-r4-16bc1f9'
    evidence = json.loads((directory/'source.json').read_text())
    raw = gzip.decompress((directory/(name+'.gz')).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == evidence['sha256'][name]
    return raw


def test_legacy_inline_macros_are_restored_before_helpers_removed(printer):
    (printer/'macros.cfg').write_bytes(legacy_bytes('macros.cfg'))
    original = (printer/'printer.cfg').read_bytes()
    for _ in range(2):
        apply_plan(printer, reconcile.plan(ROOT, printer))
    planned = reconcile.removal_plan(ROOT, printer)
    assert not planned['retained_dependencies']
    backup = reconcile.publish(printer, planned)
    active = bundle.read_active_config(printer/'printer.cfg')
    stock = bundle.read_active_config(ROOT/'config/stock/printer.cfg')
    assert not any(s.startswith('gcode_macro _WMP_') for s in active.sections())
    assert active.get('gcode_macro START_PRINT', 'gcode') == stock.get('gcode_macro START_PRINT', 'gcode')
    assert active.get('printer', 'max_velocity') == '123'
    assert (printer/'printer.cfg').read_bytes().partition(reconcile.SAVE_MARKER)[2] == original.partition(reconcile.SAVE_MARKER)[2]
    assert (backup/'macros.cfg.before').read_bytes() == legacy_bytes('macros.cfg')
    assert reconcile.removal_plan(ROOT, printer)['changes'] == []


def test_legacy_behavior_removal_has_recoverable_multi_file_rollback(printer):
    for name in ('macros.cfg', 'change_macros.cfg', 'offset_calibrate.cfg'):
        (printer/name).write_bytes(legacy_bytes(name))
    apply_plan(printer, reconcile.plan(ROOT, printer))
    planned = reconcile.removal_plan(ROOT, printer)
    backup = reconcile.publish(printer, planned)
    reconcile.restore(printer, planned, backup)
    for change in planned['changes']:
        assert (printer/change['file']).read_bytes() == change['before']


def test_factory_files_are_byte_identical_after_removal(printer):
    before = {p.name:p.read_bytes() for p in printer.iterdir() if p.is_file()}
    apply_plan(printer, reconcile.plan(ROOT, printer))
    reconcile.publish(printer, reconcile.removal_plan(ROOT, printer))
    for name, content in before.items():
        assert (printer/name).read_bytes() == content


def test_unknown_legacy_code_is_retained_and_reported(printer):
    text = legacy_bytes('macros.cfg').decode('utf-8').replace(
        'WMP_CHECK_RESUME', 'WMP_CHECK_RESUME\n    RESPOND MSG="operator edit"')
    assert 'operator edit' in text
    (printer/'macros.cfg').write_text(text)
    planned = reconcile.removal_plan(ROOT, printer)
    assert planned['retained_dependencies']
    target = next(c['after'] for c in planned['changes'] if c['file']=='macros.cfg')
    assert b'operator edit' in target


def test_removal_remote_script_includes_legacy_catalog(printer):
    import subprocess, sys
    (printer/'macros.cfg').write_bytes(legacy_bytes('macros.cfg'))
    script = reconcile.remote_script(ROOT, printer, action='remove-plan')
    result = subprocess.run([sys.executable, '-I', '-'], input=script,
                            text=True, capture_output=True, check=True)
    planned = json.loads(result.stdout)['plan']
    assert not planned['retained_dependencies']
    assert any(c['file']=='macros.cfg' for c in planned['changes'])


def test_published_r3_then_two_r4_updates_restore_factory(printer):
    import gzip,hashlib
    raw=gzip.decompress((ROOT/'tests/fixtures/config-r3/macros.cfg.gz').read_bytes())
    evidence=json.loads((ROOT/'tests/fixtures/config-r3/source.json').read_text())
    assert hashlib.sha256(raw).hexdigest()==evidence['sha256']
    (printer/'macros.cfg').write_bytes(raw)
    for _ in range(2):
        apply_plan(printer,reconcile.plan(ROOT,printer))
    planned=reconcile.removal_plan(ROOT,printer)
    assert not planned['retained_dependencies']
    reconcile.publish(printer,planned)
    active=bundle.read_active_config(printer/'printer.cfg')
    factory=bundle.read_active_config(ROOT/'config/stock/printer.cfg')
    assert active.get('gcode_macro START_PRINT','gcode')==factory.get('gcode_macro START_PRINT','gcode')
    assert not any(s.startswith('gcode_macro _WMP_') for s in active.sections())


def test_full_inline_legacy_behavior_restores_without_changing_geometry(printer):
    names=('printer.cfg','macros.cfg','change_macros.cfg','offset_calibrate.cfg',
           'fz-wipe-nozzle.cfg','case_light.cfg','extruder0.cfg','extruder1.cfg','extruder2.cfg','extruder3.cfg')
    for name in names:
        (printer/name).write_bytes(legacy_bytes(name))
    target=printer/'extruder2.cfg'
    target.write_text(target.read_text().replace('rotation_distance: 21.018','rotation_distance: 21.6485'))
    before=bundle.read_active_config(printer/'printer.cfg')
    planned=reconcile.removal_plan(ROOT,printer)
    assert not planned['retained_dependencies']
    reconcile.publish(printer,planned)
    active=bundle.read_active_config(printer/'printer.cfg')
    for section in ('stepper_x','stepper_y','stepper_z','extruder','extruder2','printer'):
        assert dict(active.items(section))==dict(before.items(section))
    assert not set(active.sections()) & {'wm_material','wmp_recovery','wmp_case_light'}
    assert not any(s.startswith('gcode_macro _WMP_') for s in active.sections())


def test_custom_command_rename_is_not_mixed_with_factory_body(printer):
    text=legacy_bytes('macros.cfg').decode('utf-8')
    import re
    section=re.search(r'(?ms)^\[gcode_macro PAUSE\].*?(?=^\[|\Z)',text).group()
    assert 'rename_existing:' in section
    changed=re.sub(r'(?m)^rename_existing:.*$', 'rename_existing: OPERATOR_PAUSE',section)
    (printer/'macros.cfg').write_text(text.replace(section,changed))
    planned=reconcile.removal_plan(ROOT,printer)
    assert planned['retained_dependencies']
    result=next(c['after'] for c in planned['changes'] if c['file']=='macros.cfg').decode()
    assert changed in result


def test_private_generated_files_are_removed_and_uninstall_is_recoverable(printer,monkeypatch):
    (printer/'wm_material.cfg').write_text('[wm_material]\nload_feed_mm: 57\n')
    apply_plan(printer,reconcile.plan(ROOT,printer))
    planned=reconcile.removal_plan(ROOT,printer)
    assert {c['file'] for c in planned['changes'] if c['after'] is None}=={reconcile.FILENAME,'wm_material.cfg'}
    original=Path.unlink
    def loss(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if path==printer/reconcile.FILENAME:raise SystemExit('power loss after removal')
        return result
    monkeypatch.setattr(Path,'unlink',loss)
    with pytest.raises(SystemExit):reconcile.publish(printer,planned)
    monkeypatch.setattr(Path,'unlink',original)
    backup=next(printer.glob('.wmp-config-backup-*'))
    reconcile.recover_interrupted(printer,backup)
    for change in planned['changes']:
        assert (printer/change['file']).read_bytes()==change['before']
    reconcile.publish(printer,reconcile.removal_plan(ROOT,printer))
    assert not (printer/reconcile.FILENAME).exists()
    assert not (printer/'wm_material.cfg').exists()
    assert not reconcile.removal_plan(ROOT,printer)['changes']


def test_known_legacy_daemon_configuration_returns_to_factory(printer):
    for name in ('crowsnest.conf','moonraker.conf'):
        (printer/name).write_bytes(legacy_bytes(name))
    planned=reconcile.removal_plan(ROOT,printer)
    reconcile.publish(printer,planned)
    for name in ('crowsnest.conf','moonraker.conf'):
        assert (printer/name).read_bytes()==(ROOT/'config/stock'/name).read_bytes()


def test_vendor_factory_reset_variant_does_not_retain_all_wmp_definitions(printer):
    # Vendor factory_settings and the shipped active config contain distinct,
    # valid NOZZLE_PREPARE bodies. Its T{T} call must not be mistaken for an
    # unknown user command requiring every managed definition to be retained.
    with (printer/'offset_calibrate.cfg').open('a') as stream:
        stream.write('\n'+(ROOT/'tests/fixtures/vendor-1.1.13-nozzle-prepare.cfg').read_text())
    apply_plan(printer,reconcile.plan(ROOT,printer))
    planned=reconcile.removal_plan(ROOT,printer)
    assert not planned['retained_dependencies']
    reconcile.publish(printer,planned)
    assert not (printer/reconcile.FILENAME).exists()


def test_user_call_to_nonprefixed_legacy_command_blocks_removal(printer):
    (printer/'macros.cfg').write_bytes(legacy_bytes('macros.cfg'))
    with (printer/'custom.cfg').open('a') as stream:
        stream.write('\n[gcode_macro USER_PROBE]\ngcode: PROBE_WITH_INITIAL_TOOL\n')
    before={p.name:p.read_bytes() for p in printer.iterdir() if p.is_file()}
    planned=reconcile.removal_plan(ROOT,printer)
    assert planned['legacy_conflicts']==['gcode_macro USER_PROBE requires removed legacy command PROBE_WITH_INITIAL_TOOL']
    with pytest.raises(ValueError,match='Unresolved legacy command dependencies'):
        reconcile.publish(printer,planned)
    assert {p.name:p.read_bytes() for p in printer.iterdir() if p.is_file()}==before


def test_unpublished_inline_behavior_is_not_blessed_by_candidate_sources(printer):
    text = legacy_bytes('macros.cfg').decode('utf-8')
    text = text.replace('WMP_CHECK_RESUME', 'WMP_CHECK_RESUME\n    RESPOND MSG="unpublished behavior"')
    assert 'unpublished behavior' in text
    (printer/'macros.cfg').write_text(text)
    plan = reconcile.removal_plan(ROOT, printer)
    assert plan['retained_dependencies']
    change = next(c for c in plan['changes'] if c['file'] == 'macros.cfg')
    assert b'unpublished behavior' in change['after']
