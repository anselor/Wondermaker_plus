"""Upgrade an owned legacy recipe without losing either rollback target."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import moonraker_directory_transaction as tx
import moonraker_directory_service as lifecycle
from moonraker_directory_patch import candidate, legacy_candidate

SOURCE = (Path(__file__).parent / 'fixtures/moonraker_directory_compat.py').read_bytes()


@pytest.fixture
def legacy(tmp_path):
    target = tmp_path / 'file_manager.py'
    state = tmp_path / 'transaction'
    state.mkdir()
    old = legacy_candidate(SOURCE.decode()).encode()
    target.write_bytes(old)
    info = target.stat()
    record = dict(version=1, target=str(target), old=tx.digest(SOURCE), new=tx.digest(old),
                  mode=info.st_mode & 0o777, uid=info.st_uid, gid=info.st_gid)
    (state / 'original.py').write_bytes(SOURCE)
    (state / 'installed.py').write_bytes(old)
    (state / 'receipt.json').write_text(json.dumps(record))
    return target, state, old


class Service:
    def __init__(self, target, fail=False):
        self.target, self.fail, self.running = target, fail, True
        self.calls = []
    def inspect(self):
        self.calls.append('inspect')
        return {'pid': 123}
    def stop(self):
        self.calls.append('stop'); self.running = False
    def start(self):
        self.calls.append('start'); self.running = True
    def verify(self, baseline):
        assert baseline == {'pid': 123} and self.running
        self.calls.append('verify')
        if self.fail and self.target.read_bytes() == candidate(SOURCE.decode()).encode():
            raise RuntimeError('new patch verification failed')


def test_owned_recipe_upgrade_install_previous_rollback_and_stock_restore(legacy):
    target, state, old = legacy
    assert tx.status(target, state) == 'previous'
    record = tx.prepare(target, state)
    assert record['version'] == 2 and target.read_bytes() == old
    assert (state/'original.py').read_bytes() == SOURCE
    assert (state/'installed.py').read_bytes() == old
    service = Service(target)
    assert lifecycle.execute(target, state, service)
    assert target.read_bytes() == candidate(SOURCE.decode()).encode()
    assert json.loads((state/'service.json').read_text())['before'] == 'previous'
    assert lifecycle.execute(target, state, service, previous=True)
    assert target.read_bytes() == old
    assert lifecycle.execute(target, state, service, restore=True)
    assert target.read_bytes() == SOURCE
    assert tx.prepare(target, state) == record


def test_upgrade_failed_activation_restores_exact_previous_patch(legacy):
    target, state, old = legacy
    tx.prepare(target, state)
    with pytest.raises(RuntimeError, match='verification failed'):
        lifecycle.execute(target, state, Service(target, fail=True))
    assert target.read_bytes() == old
    assert (state/'original.py').read_bytes() == SOURCE
    assert lifecycle.read_operation(state)['phase'] == 'recovered'


@pytest.mark.parametrize('filename', ['installed-v2.py', 'receipt.json'])
def test_upgrade_preparation_interruption_keeps_complete_receipt_and_original(legacy, monkeypatch, filename):
    target, state, old = legacy
    original = tx.atomic_write
    def interrupted(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path.name == filename:
            raise KeyboardInterrupt('power loss after ' + filename)
    with monkeypatch.context() as patch:
        patch.setattr(tx, 'atomic_write', interrupted)
        with pytest.raises(KeyboardInterrupt):
            tx.prepare(target, state)
    assert target.read_bytes() == old
    assert tx.load_record(target, state)[1] == SOURCE
    assert tx.prepare(target, state)['version'] == 2
    assert tx.status(target, state) == 'previous'


@pytest.mark.parametrize('phase', ['stop', 'publish', 'start'])
def test_upgrade_interrupted_service_recovers_previous_and_can_retry(legacy, monkeypatch, phase):
    target, state, old = legacy
    tx.prepare(target, state)
    service = Service(target)
    owner = tx if phase == 'publish' else service
    actual = getattr(owner, phase)
    def interrupted(*args, **kwargs):
        actual(*args, **kwargs)
        raise KeyboardInterrupt('process loss')
    with monkeypatch.context() as patch:
        patch.setattr(owner, phase, interrupted)
        with pytest.raises(KeyboardInterrupt):
            lifecycle.execute(target, state, service)
    assert lifecycle.execute(target, state, service, recover=True)
    assert target.read_bytes() == old
    assert lifecycle.execute(target, state, service)
    assert tx.status(target, state) == 'installed'


def test_legacy_pending_operation_must_recover_before_recipe_upgrade(legacy):
    target, state, old = legacy
    lifecycle.checkpoint(state, dict(version=1, before='installed', desired='original', baseline={'pid': 123}), 'stopped')
    before = (state/'receipt.json').read_bytes()
    with pytest.raises(ValueError, match='recovery before recipe upgrade'):
        tx.prepare(target, state)
    assert (state/'receipt.json').read_bytes() == before
    assert not (state/'installed-v2.py').exists()
    assert lifecycle.execute(target, state, Service(target), recover=True)
    assert target.read_bytes() == old
    assert tx.prepare(target, state)['version'] == 2


def test_tampered_legacy_recipe_cannot_be_adopted_by_matching_receipt_hash(legacy):
    target, state, old = legacy
    modified = old + b'\n# unreviewed custom edit\n'
    (state/'installed.py').write_bytes(modified)
    target.write_bytes(modified)
    record = json.loads((state/'receipt.json').read_text())
    record['new'] = tx.digest(modified)
    (state/'receipt.json').write_text(json.dumps(record))
    with pytest.raises(ValueError, match='reviewed patch'):
        tx.prepare(target, state)
    assert target.read_bytes() == modified


def test_upgraded_receipt_preserves_both_recipes_when_vendor_baseline_changes(legacy):
    target, state, old = legacy
    record = tx.prepare(target, state)
    current = SOURCE + b'\n# Supported vendor module update outside patched methods\n'
    target.write_bytes(current)
    fresh = tx.prepare(target, state)
    assert fresh['version'] == 1 and target.read_bytes() == current
    archive = next(state.glob('retired-*'))
    archived, original, installed = tx.load_record(target, archive)
    assert archived == record and original == SOURCE
    assert installed == candidate(SOURCE.decode()).encode()
    assert (archive/'installed.py').read_bytes() == old


@pytest.mark.parametrize('artifact', ['original.py', 'installed.py', 'installed-v2.py'])
def test_upgraded_receipt_rejects_tampered_rollback_or_candidate(legacy, artifact):
    target, state, old = legacy
    tx.prepare(target, state)
    with (state/artifact).open('ab') as stream:
        stream.write(b'\n# tampered\n')
    with pytest.raises(ValueError):
        lifecycle.execute(target, state, Service(target))
    assert target.read_bytes() == old
