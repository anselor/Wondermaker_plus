"""Service publication ordering and interrupted lifecycle recovery."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import moonraker_directory_transaction as tx
import moonraker_directory_service as lifecycle

SOURCE = (Path(__file__).parent / 'fixtures/moonraker_directory_compat.py').read_bytes()
TARGET_NAME = 'file_manager.py'


@pytest.fixture(autouse=True, params=('directory', 'http-error'))
def patch_recipe(request, monkeypatch):
    if request.param == 'http-error':
        source = (Path(__file__).parent / 'fixtures/moonraker_http_error_compat.py').read_bytes()
        monkeypatch.setattr(sys.modules[__name__], 'SOURCE', source)
        monkeypatch.setattr(sys.modules[__name__], 'TARGET_NAME', 'application.py')



class Service:
    def __init__(self, target):
        self.target = target
        self.calls = []
        self.running = True
        self.fail_verify = False

    def inspect(self):
        assert self.running
        self.calls.append('inspect')
        return {'klipper_session': 'same-session', 'loaded': ['h2', 'h3']}

    def stop(self):
        self.calls.append('stop')
        self.running = False

    def start(self):
        self.calls.append('start')
        self.running = True

    def verify(self, baseline):
        self.calls.append('verify')
        assert baseline == {'klipper_session': 'same-session', 'loaded': ['h2', 'h3']}
        assert self.running
        if self.fail_verify and self.target.read_bytes() != SOURCE:
            raise RuntimeError('new service failed readiness')


@pytest.fixture
def prepared(tmp_path):
    target, state = tmp_path / TARGET_NAME, tmp_path / 'transaction'
    target.write_bytes(SOURCE)
    tx.prepare(target, state)
    return target, state, Service(target)


def test_service_stopped_at_publication_and_no_klipper_restart(prepared, monkeypatch):
    target, state, service = prepared
    original = tx.publish
    def publish(*args, **kwargs):
        assert not service.running
        # A second process cannot interfere while service is stopped.
        with pytest.raises(BlockingIOError):
            tx.transition(target, state)
        return original(*args, **kwargs)
    monkeypatch.setattr(tx, 'publish', publish)
    assert lifecycle.execute(target, state, service)
    assert service.calls == ['inspect', 'stop', 'start', 'verify']
    assert tx.status(target, state) == 'installed'
    service.calls.clear()
    assert not lifecycle.execute(target, state, service)
    assert service.calls == ['inspect', 'verify']
    assert lifecycle.execute(target, state, service, restore=True)
    assert tx.status(target, state) == 'original'


def test_failed_candidate_recovers_original_and_checks_ready(prepared):
    target, state, service = prepared
    service.fail_verify = True
    with pytest.raises(RuntimeError, match='new service failed'):
        lifecycle.execute(target, state, service)
    assert tx.status(target, state) == 'original'
    assert service.running
    assert service.calls == ['inspect', 'stop', 'start', 'verify', 'stop', 'start', 'verify']
    assert json.loads((state / 'service.json').read_text())['phase'] == 'recovered'


@pytest.mark.parametrize('phase', ['stop', 'publish', 'start'])
def test_interruption_requires_explicit_recovery(prepared, monkeypatch, phase):
    target, state, service = prepared
    owner, method = (tx, 'publish') if phase == 'publish' else (service, phase)
    original = getattr(owner, method)
    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise KeyboardInterrupt('simulated process loss after ' + phase)
    with monkeypatch.context() as patch:
        patch.setattr(owner, method, interrupted)
        with pytest.raises(KeyboardInterrupt):
            lifecycle.execute(target, state, service)
    with pytest.raises(ValueError, match='explicit recovery'):
        lifecycle.execute(target, state, service)
    assert lifecycle.execute(target, state, service, recover=True)
    assert service.running
    assert target.read_bytes() == SOURCE
    assert not lifecycle.execute(target, state, service, recover=True)


def test_concurrent_source_edit_not_overwritten_by_recovery(prepared, monkeypatch):
    target, state, service = prepared
    def changed():
        target.write_bytes(b'operator edit')
        raise RuntimeError('failed start with unrelated edit')
    monkeypatch.setattr(service, 'start', changed)
    with pytest.raises(RuntimeError, match='recovery remains unconfirmed'):
        lifecycle.execute(target, state, service)
    assert target.read_bytes() == b'operator edit'
    assert json.loads((state / 'service.json').read_text())['phase'] == 'restoring'
