"""Identification writes only a complete, verified mapping; no hardware used."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('identification_transaction', ROOT / 'klipper_extras/wmp_identification.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
IDS = ['00000000000%d' % i for i in range(4)]


@pytest.fixture
def files(tmp_path):
    for head, identity in enumerate(IDS):
        (tmp_path / ('wm_zru_thr%d.cfg' % head)).write_bytes(
            ('# retain this\r\n[mcu T%d]\r\ncanbus_uuid: %s # hardware\r\nrestart_method: command\r\n' % (head, identity)).encode())
    return tmp_path


def snapshot(directory):
    return {p.name: p.read_bytes() for p in directory.glob('*.cfg')}


def staged(files):
    operation = module.MappingTransaction(files, 4)
    for head, identity in enumerate(reversed(IDS)):
        operation.stage(head, identity)
    return operation


def test_staging_does_not_write_and_commit_preserves_other_bytes(files):
    before = snapshot(files)
    operation = staged(files)
    assert snapshot(files) == before
    journal = operation.commit(final_dock_confirmed=True)
    assert json.loads(journal.read_text())['state'] == 'committed'
    for head in range(4):
        name = 'wm_zru_thr%d.cfg' % head
        assert (files / name).read_bytes() == before[name].replace(IDS[head].encode(), IDS[3-head].encode())


@pytest.mark.parametrize('case', ['missing-head', 'no-dock', 'early-failure', 'duplicate', 'foreign', 'changed-file'])
def test_incomplete_or_failed_setup_never_publishes(files, case):
    operation = module.MappingTransaction(files, 4)
    before = snapshot(files)
    if case == 'early-failure':
        operation.fail('pickup failed')
        operation.fail('later error')
        assert operation.failure == 'pickup failed'
    with pytest.raises(ValueError):
        for head, identity in enumerate(reversed(IDS)):
            if case == 'missing-head' and head == 3:
                break
            if case == 'duplicate' and head == 1:
                identity = IDS[3]
            if case == 'foreign' and head == 1:
                identity = 'abcdefabcdef'
            operation.stage(head, identity)
        if case == 'changed-file':
            (files / 'wm_zru_thr0.cfg').write_bytes(b'# operator edit\n')
            before = snapshot(files)
        operation.commit(final_dock_confirmed=case != 'no-dock')
    assert snapshot(files) == before
    assert not operation.committed


@pytest.mark.parametrize('after_write', [False, True])
def test_write_failure_restores_entire_mapping(files, monkeypatch, after_write):
    operation = staged(files)
    before = snapshot(files)
    original = module.atomic_write
    failed = False
    def write(path, content):
        nonlocal failed
        if path.name == 'wm_zru_thr1.cfg' and not failed:
            failed = True
            if after_write:
                original(path, content)
            raise OSError('injected failure')
        original(path, content)
    monkeypatch.setattr(module, 'atomic_write', write)
    with pytest.raises(OSError, match='injected'):
        operation.commit(final_dock_confirmed=True)
    assert snapshot(files) == before
    assert json.loads(operation.journal_path.read_text())['state'] == 'rolled-back'
    assert not operation.committed


def test_rollback_preserves_concurrent_operator_edit(files, monkeypatch):
    operation = staged(files)
    original = module.atomic_write
    def write(path, content):
        if path.name == 'wm_zru_thr1.cfg':
            (files / 'wm_zru_thr0.cfg').write_bytes(b'# operator edit\n')
            raise OSError('injected failure')
        original(path, content)
    monkeypatch.setattr(module, 'atomic_write', write)
    with pytest.raises(RuntimeError, match='rollback needs inspection'):
        operation.commit(final_dock_confirmed=True)
    assert (files / 'wm_zru_thr0.cfg').read_bytes() == b'# operator edit\n'
    assert json.loads(operation.journal_path.read_text())['state'] == 'rollback-unconfirmed'


@pytest.mark.parametrize('content', [b'canbus_uuid: bad\n', b'canbus_uuid: 000000000000\ncanbus_uuid: bad\n'])
def test_invalid_original_uuid_configuration_is_rejected(files, content):
    (files / 'wm_zru_thr0.cfg').write_bytes(content)
    with pytest.raises(ValueError, match='exactly one valid'):
        module.MappingTransaction(files, 4)


def interrupt_commit(files, monkeypatch):
    operation = staged(files)
    original = module.atomic_write
    def crash(path, content):
        original(path, content)
        if path.name == 'wm_zru_thr1.cfg':
            raise SystemExit('process interrupted')
    with monkeypatch.context() as patch:
        patch.setattr(module, 'atomic_write', crash)
        with pytest.raises(SystemExit, match='interrupted'):
            operation.commit(final_dock_confirmed=True)
    return operation


def test_restart_requires_recovery_and_restores_original_mapping(files, monkeypatch):
    before = snapshot(files)
    operation = interrupt_commit(files, monkeypatch)
    assert snapshot(files) != before
    with pytest.raises(ValueError, match='Recover interrupted'):
        module.MappingTransaction(files, 4)
    module.MappingTransaction.recover(files, operation.journal_path)
    assert snapshot(files) == before
    assert json.loads(operation.journal_path.read_text())['state'] == 'rolled-back'
    # Recovery does not resume setup or commit; a new explicit operation is needed.
    assert module.MappingTransaction(files, 4).staged == {}


@pytest.mark.parametrize('tamper', ['path', 'non-uuid-change', 'duplicate'])
def test_recovery_rejects_invalid_journal_before_any_write(files, monkeypatch, tamper):
    operation = interrupt_commit(files, monkeypatch)
    record = json.loads(operation.journal_path.read_text())
    if tamper == 'path':
        record['files'][0]['name'] = '../printer.cfg'
    elif tamper == 'non-uuid-change':
        record['files'][0]['after'] += b'# unwanted edit\n'.hex()
    else:
        row = record['files'][1]
        row['after'] = bytes.fromhex(row['after']).replace(IDS[2].encode(), IDS[3].encode()).hex()
    operation.journal_path.write_text(json.dumps(record))
    before = snapshot(files)
    with pytest.raises(ValueError):
        module.MappingTransaction.recover(files, operation.journal_path)
    assert snapshot(files) == before


def test_interrupted_recovery_preserves_operator_changes(files, monkeypatch):
    operation = interrupt_commit(files, monkeypatch)
    changed = files / 'wm_zru_thr0.cfg'
    changed.write_bytes(b'# operator edit\n')
    with pytest.raises(RuntimeError, match='rollback needs inspection'):
        module.MappingTransaction.recover(files, operation.journal_path)
    assert changed.read_bytes() == b'# operator edit\n'
    assert json.loads(operation.journal_path.read_text())['state'] == 'rollback-unconfirmed'


def test_read_failure_remains_latched_after_file_returns(files):
    operation = staged(files)
    path = files / 'wm_zru_thr0.cfg'
    content = path.read_bytes()
    path.unlink()
    with pytest.raises(ValueError, match='Missing'):
        operation.commit(final_dock_confirmed=True)
    path.write_bytes(content)
    with pytest.raises(ValueError, match='Missing'):
        operation.commit(final_dock_confirmed=True)
    assert not operation.committed
