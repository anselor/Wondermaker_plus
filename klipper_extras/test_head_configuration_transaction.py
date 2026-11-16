import json

import pytest

import wmp_identification as migration
from wm_material import WMMaterial
from test_head_configuration_plan import IDS, source


@pytest.fixture
def transaction(tmp_path):
    snapshot, effective = source()
    for name, raw in snapshot.items():
        if raw is not None:
            (tmp_path / name).write_bytes(raw)
    return migration.HeadConfigurationTransaction(
        tmp_path, list(reversed(IDS)), effective, WMMaterial._validate_identity, 'original_session')


def bytes_now(operation):
    return {name: operation._read(name) for name in operation.original}


def reopen(operation):
    return migration.HeadConfigurationTransaction.reopen(
        operation.directory, operation.journal_path, WMMaterial._validate_identity)


def test_publication_stays_blocked_until_new_loaded_settings_are_verified(transaction):
    transaction.publish(lambda: True)
    assert bytes_now(transaction) == transaction.planned
    assert transaction.state == 'published'
    with pytest.raises(ValueError, match='Resolve head configuration'):
        migration.require_resolved_journals(transaction.directory)
    restored = reopen(transaction)
    with pytest.raises(ValueError, match='fresh post-restart'):
        restored.verify_loaded('original_session', {}, lambda: True)
    with pytest.raises(ValueError, match='Active head identity'):
        restored.verify_loaded('new_session', transaction.effective_settings, lambda: True)
    effective = {}
    for head, old in enumerate(reversed(range(4))):
        heater = 'extruder' + (str(head) if head else '')
        old_heater = 'extruder' + (str(old) if old else '')
        effective[heater] = transaction.effective_settings[old_heater]
        effective['mcu T%d' % head] = {'canbus_uuid': IDS[old]}
    restored.verify_loaded('new_session', effective, lambda: True)
    assert json.loads(transaction.journal_path.read_text())['state'] == 'verified'
    migration.require_resolved_journals(transaction.directory)


@pytest.mark.parametrize('name', ['printer.cfg', 'tmt1.ini', 'wm_zru_thr0.cfg', 'wm_zru_thr1.cfg',
                                 'wm_zru_thr2.cfg', 'wm_zru_thr3.cfg', 'wmp_filament_loaded.json'])
@pytest.mark.parametrize('process_loss', [False, True])
def test_failure_after_each_live_rename_recovers_all_members(transaction, monkeypatch, name, process_loss):
    original_write = migration.atomic_write
    failed = False

    def interrupted(path, raw):
        nonlocal failed
        original_write(path, raw)
        if path.name == name and not failed:
            failed = True
            if process_loss:
                raise SystemExit('process lost')
            raise OSError('write acknowledgement lost')

    with monkeypatch.context() as patch:
        patch.setattr(migration, 'atomic_write', interrupted)
        with pytest.raises(SystemExit if process_loss else OSError):
            transaction.publish(lambda: True)
    if process_loss:
        assert bytes_now(transaction) != transaction.original
        with pytest.raises(ValueError, match='Resolve head configuration'):
            migration.require_resolved_journals(transaction.directory)
        reopen(transaction).rollback()
    assert bytes_now(transaction) == transaction.original
    migration.require_resolved_journals(transaction.directory)


def test_concurrent_edit_is_preserved_and_keeps_migration_unresolved(transaction):
    transaction.publish(lambda: True)
    (transaction.directory / 'tmt1.ini').write_bytes(b'operator edit')
    before = bytes_now(transaction)
    with pytest.raises(RuntimeError, match='needs inspection'):
        reopen(transaction).rollback()
    assert bytes_now(transaction) == before
    assert json.loads(transaction.journal_path.read_text())['state'] == 'rollback-unconfirmed'


def test_changed_admission_rolls_back_without_finishing_remaining_members(transaction):
    checks = 0

    def admit():
        nonlocal checks
        checks += 1
        return checks < 4

    with pytest.raises(ValueError, match='admission changed'):
        transaction.publish(admit)
    assert bytes_now(transaction) == transaction.original


@pytest.mark.parametrize('defect', ['path', 'after', 'duplicate'])
def test_recovery_validates_entire_candidate_before_touching_files(transaction, defect):
    transaction.publish(lambda: True)
    record = json.loads(transaction.journal_path.read_text())
    if defect == 'path':
        record['files'][0]['name'] = '../outside'
    elif defect == 'after':
        record['files'][0]['after'] = b'wrong calibration'.hex()
    else:
        record['files'].append(record['files'][0])
    transaction.journal_path.write_text(json.dumps(record))
    before = bytes_now(transaction)
    with pytest.raises(ValueError):
        reopen(transaction)
    assert bytes_now(transaction) == before


def test_changed_source_or_refused_admission_never_publishes(transaction):
    with pytest.raises(ValueError, match='not admitted'):
        transaction.publish(lambda: False)
    assert not transaction.journal_path.exists()
    (transaction.directory / 'printer.cfg').write_bytes(b'new edit')
    before = bytes_now(transaction)
    with pytest.raises(ValueError, match='snapshot changed'):
        transaction.publish(lambda: True)
    assert not transaction.journal_path.exists()
    assert bytes_now(transaction) == before


@pytest.mark.parametrize('finish', ['rollback', 'restart_verify'])
def test_migration_preserves_real_motion_mesh_and_offset_blocks(tmp_path, finish):
    snapshot, effective = source()
    motion = (b'[printer]\r\nmax_velocity: 450\r\nmax_accel: 12000\r\n'
              b'[gcode_macro CLEAN_NOZZLE]\r\nvariable_wipe_speed: 30000\r\n'
              b'gcode:\r\n  G1 X-13 Y80 F{wipe_speed}\r\n'
              b'[gcode_macro TOOL_OFFSETS]\r\nvariable_h3_x: -0.71875\r\n'
              b'variable_h3_y: 0.720313\r\nvariable_h3_z: -0.224062\r\n')
    mesh = (b'#*# [bed_mesh wmp_print]\r\n#*# version = 1\r\n'
            b'#*# points =\r\n#*#   0.021, -0.017, 0.004\r\n'
            b'#*#   0.010, -0.023, 0.013\r\n#*# tension = 0.2\r\n')
    snapshot['printer.cfg'] = motion + snapshot['printer.cfg'] + mesh
    for name, raw in snapshot.items():
        if raw is not None: (tmp_path / name).write_bytes(raw)
    operation = migration.HeadConfigurationTransaction(
        tmp_path, list(reversed(IDS)), effective, WMMaterial._validate_identity, 'original_session')
    operation.publish(lambda: True)
    raw = (tmp_path / 'printer.cfg').read_bytes()
    assert raw.startswith(motion) and raw.endswith(mesh)
    restored = reopen(operation)
    if finish == 'rollback':
        restored.rollback()
        assert bytes_now(restored) == snapshot
    else:
        loaded = {}
        for head, old in enumerate(reversed(range(4))):
            heater = 'extruder' + (str(head) if head else '')
            previous = 'extruder' + (str(old) if old else '')
            loaded[heater] = effective[previous]
            loaded['mcu T%d' % head] = {'canbus_uuid': IDS[old]}
        restored.verify_loaded('new_session', loaded, lambda: True)
        assert bytes_now(restored) == operation.planned
        assert (tmp_path / 'printer.cfg').read_bytes().startswith(motion)
        assert (tmp_path / 'printer.cfg').read_bytes().endswith(mesh)
    migration.require_resolved_journals(tmp_path)


@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('field', ['canbus_uuid', 'control', 'pid_kp', 'nozzle_diameter'])
def test_restart_verification_keeps_hold_for_loaded_hardware_mismatch(transaction, head, field):
    """Correct files are insufficient if the restarted runtime loaded an override."""
    import copy

    transaction.publish(lambda: True)
    effective = {}
    for target, original in enumerate(reversed(range(4))):
        heater = 'extruder' + (str(target) if target else '')
        source_heater = 'extruder' + (str(original) if original else '')
        effective[heater] = copy.deepcopy(transaction.effective_settings[source_heater])
        effective['mcu T%d' % target] = {'canbus_uuid': IDS[original]}
    heater = 'extruder' + (str(head) if head else '')
    if field == 'canbus_uuid':
        effective['mcu T%d' % head][field] = '000000000000'
    elif field == 'control':
        effective[heater][field] = 'watermark'
    else:
        effective[heater][field] += 1
    before = bytes_now(transaction)
    journal = transaction.journal_path.read_bytes()
    restored = reopen(transaction)
    with pytest.raises(ValueError):
        restored.verify_loaded('restarted_session', effective, lambda: True)
    assert restored.state == 'published'
    assert bytes_now(transaction) == before
    assert transaction.journal_path.read_bytes() == journal
    with pytest.raises(ValueError, match='Resolve head configuration'):
        migration.require_resolved_journals(transaction.directory)
