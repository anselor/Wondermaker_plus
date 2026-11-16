"""Final installer restart uses parsed status and proves a new ready state."""
import json
from types import SimpleNamespace
import pytest
from test_deploy import deploy

READY = {'state': 'ready', 'process_id': 10}


def restart(monkeypatch, replies, lost_post=False):
    ctx = deploy.Context(SimpleNamespace())
    clock = [0]
    monkeypatch.setattr(deploy.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0]+seconds))
    calls = []
    replies = list(replies)
    def query(path, post=False):
        calls.append((path, post))
        if post:
            if lost_post:
                raise OSError('lost acknowledgement')
            return '{}'
        item = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(item, Exception):
            raise item
        return json.dumps({'result': item}, separators=(',', ':'))
    ctx.moonraker = query
    return ctx, clock, calls


@pytest.mark.parametrize('transition', [dict(state='startup', process_id=10), dict(READY, process_id=11)])
def test_restart_requires_transition_and_two_ready_samples(monkeypatch, transition):
    ready = dict(READY, process_id=transition['process_id'])
    ctx, clock, calls = restart(monkeypatch, [READY, READY, transition, ready, ready])
    assert ctx.restart_klipper()
    assert clock[0] == (8 if transition['state'] == 'startup' else 6)
    assert sum(post for _, post in calls) == 1


def test_stale_ready_never_proves_restart(monkeypatch):
    ctx, clock, _ = restart(monkeypatch, [READY])
    assert not ctx.restart_klipper()
    assert clock[0] == 120


def test_network_gap_is_not_restart_evidence(monkeypatch):
    ctx, _, _ = restart(monkeypatch, [READY, OSError('network gap'), READY])
    assert not ctx.restart_klipper()


def test_lost_restart_response_does_not_repeat_command(monkeypatch):
    ctx, _, calls = restart(monkeypatch, [READY, {'state': 'startup'}, READY, READY], lost_post=True)
    assert ctx.restart_klipper()
    assert sum(post for _, post in calls) == 1


def test_backend_error_can_recover_but_never_counts_as_ready(monkeypatch):
    ctx, _, _ = restart(monkeypatch, [{'state': 'error'}, {'state': 'startup'}, READY, READY])
    assert ctx.restart_klipper()
    ctx, _, _ = restart(monkeypatch, [READY, {'state': 'error'}])
    assert not ctx.restart_klipper()


@pytest.mark.parametrize('state', ['ready', 'error', 'shutdown'])
def test_helper_install_reloads_python_process_once(monkeypatch, state):
    from components import touchscreen
    before = dict(state=state, process_id=10, state_message='existing problem')
    after = dict(before, process_id=11)
    ctx, _, calls = restart(monkeypatch, [before, before, after, after])
    ctx.installing_components = {'material'}
    ctx.ssh = lambda: object()
    commands = []
    def run(connection, command, **kwargs):
        commands.append(command)
        raise OSError('reply lost after dispatch')
    monkeypatch.setattr(touchscreen, 'run', run)
    assert ctx.restart_klipper()
    assert commands == ['systemctl restart klipper.service']
    assert not any(post for _, post in calls)


def test_helper_reload_rejects_old_pid_even_after_internal_restart(monkeypatch):
    from components import touchscreen
    ctx, _, _ = restart(monkeypatch, [READY, dict(state='startup', process_id=10), READY])
    ctx.installing_components = {'config'}
    ctx.ssh = lambda: object()
    monkeypatch.setattr(touchscreen, 'run', lambda *a, **k: ('', '', 0))
    assert not ctx.restart_klipper()


def test_new_backend_error_is_not_reported_as_successful_activation(monkeypatch):
    from components import touchscreen
    ctx, _, _ = restart(monkeypatch, [READY, dict(state='error', process_id=11, state_message='new error')])
    ctx.installing_components = {'material'}
    ctx.ssh = lambda: object()
    monkeypatch.setattr(touchscreen, 'run', lambda *a, **k: ('', '', 0))
    assert not ctx.restart_klipper()
