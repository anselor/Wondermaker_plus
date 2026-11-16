"""A running UI service alone does not prove that its Klipper restart succeeded."""
import json
from types import SimpleNamespace as NS

import pytest
from test_deploy import deploy
from components import preload


def restart(monkeypatch, replies, services=None, lost_post=False, backend_service=None):
    monkeypatch.setattr(preload, "verify_guard", lambda ctx: None)
    clock = [0]
    monkeypatch.setattr(preload.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(preload.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    calls = []
    def checked(*args, **kwargs):
        calls.append(args[2])
        if lost_post and args[2] == 'systemctl restart klipper.service':
            raise OSError('lost service restart acknowledgement')
    monkeypatch.setattr(preload, '_checked', checked)
    services = list(services or [('active\n', '', 0)])
    def service(*a, **kw):
        return services.pop(0) if len(services) > 1 else services[0]
    monkeypatch.setattr(preload, 'run', service)
    replies = list(replies)
    def info(path, post=False):
        assert not post  # Firmware restart does not reload Python helper modules.
        assert path == '/printer/info'
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, Exception):
            raise reply
        return json.dumps({'result': reply})
    ctx = NS(moonraker=info, DeployError=deploy.DeployError)
    if backend_service is not None:
        ctx.backend_service_status = lambda: backend_service
    return lambda **kw: preload._restart(ctx, None, **kw), clock, calls


READY = {'state': 'ready', 'process_id': 100}


def test_waits_past_stale_ready_until_restart_and_stable_ready(monkeypatch):
    run, clock, calls = restart(monkeypatch, [READY, READY, READY,
        OSError('disconnect'), {'state': 'startup'}, dict(READY, process_id=101), dict(READY, process_id=101)])
    run()
    assert clock[0] == 12
    assert len(calls) == 3


def test_changed_backend_pid_proves_restart(monkeypatch):
    run, clock, _ = restart(monkeypatch, [READY, dict(READY, process_id=101)])
    run()
    assert clock[0] == 4


@pytest.mark.parametrize('gap', [OSError('network timeout'), ValueError('bad JSON'),
                               {}, {'state': 'unknown'}, []])
def test_query_failure_or_unknown_state_does_not_prove_restart(monkeypatch, gap):
    run, clock, calls = restart(monkeypatch, [READY, gap, READY])
    with pytest.raises(deploy.DeployError, match='did not reach verified'):
        run()
    assert clock[0] == 120 and len(calls) == 3


def test_missing_initial_status_requires_observed_restart(monkeypatch):
    run, _, calls = restart(monkeypatch, [OSError('baseline unavailable'), READY])
    with pytest.raises(deploy.DeployError, match='did not reach verified'):
        run()
    assert len(calls) == 3


@pytest.mark.parametrize('final', [READY, {'state': 'error', 'state_message': 'bad config'},
                                  {'state': 'shutdown'}, OSError('unreachable')])
def test_stale_ready_or_failed_backend_never_reports_success(monkeypatch, final):
    run, clock, _ = restart(monkeypatch, [READY, final])
    with pytest.raises(deploy.DeployError, match='did not reach verified'):
        run()
    assert clock[0] == 120


def test_failed_screen_service_is_failure_even_if_backend_ready(monkeypatch):
    run, _, _ = restart(monkeypatch, [READY], [('failed\n', '', 3)])
    with pytest.raises(deploy.DeployError, match='failed during startup'):
        run()


def test_can_recover_from_initial_backend_error(monkeypatch):
    run, _, _ = restart(monkeypatch, [{'state': 'error', 'process_id':100}, dict(READY, process_id=101)])
    run()


def test_ready_must_be_consecutive_with_active_service(monkeypatch):
    run, clock, _ = restart(monkeypatch, [{'state': 'startup', 'process_id':100}, dict(READY, process_id=101)],
                           [('active\n', '', 0), ('activating\n', '', 3), ('active\n', '', 0)])
    run()
    assert clock[0] == 8


def test_managed_startup_needs_one_explicit_restart_in_order(monkeypatch):
    run, _, calls = restart(monkeypatch, [READY, dict(READY, process_id=101)])
    run()
    assert calls == ['systemctl daemon-reload && systemctl stop makerbase-client.service',
                     'systemctl restart klipper.service', 'systemctl start makerbase-client.service']


def test_lost_restart_acknowledgement_does_not_resubmit(monkeypatch):
    run, _, calls = restart(monkeypatch, [READY, {'state': 'startup'}, dict(READY, process_id=101), dict(READY, process_id=101)], lost_post=True)
    run()
    assert calls.count('systemctl restart klipper.service') == 1


def test_refused_restart_with_old_ready_backend_is_not_success(monkeypatch):
    run, _, calls = restart(monkeypatch, [READY], lost_post=True)
    with pytest.raises(deploy.DeployError, match='did not reach verified'):
        run()
    assert calls.count('systemctl restart klipper.service') == 1


def test_internal_startup_with_same_pid_does_not_prove_module_reload(monkeypatch):
    run, _, calls = restart(monkeypatch, [READY, {'state':'startup', 'process_id':100}, READY])
    with pytest.raises(deploy.DeployError, match='did not reach verified'):
        run()
    assert calls.count('systemctl restart klipper.service') == 1


def test_service_channel_failure_reconnects_only_for_observation(monkeypatch):
    invoke, clock, commands = restart(monkeypatch, [READY, dict(READY, process_id=101)])
    connections = []
    reconnects = []
    connection = object()
    original = preload._restart
    def wrapper(ctx, old):
        ctx.reconnect_ssh = lambda: reconnects.append(True) or connection
        return original(ctx, old)
    monkeypatch.setattr(preload, '_restart', wrapper)
    def service(c, command, **kwargs):
        assert command == 'systemctl is-active makerbase-client.service'
        assert kwargs['timeout'] == 10
        connections.append(c)
        if len(connections) == 1:
            raise OSError('Timeout opening channel')
        assert c is connection
        return 'active\n', '', 0
    monkeypatch.setattr(preload, 'run', service)
    invoke()
    assert reconnects == [True] and len(connections) == 3
    assert commands.count('systemctl restart klipper.service') == 1
    assert len(commands) == 3


@pytest.mark.parametrize('state', ['error', 'shutdown'])
def test_existing_backend_error_does_not_veto_verified_process_activation(monkeypatch, state, capsys):
    initial = {'state': state, 'process_id':100, 'state_message':'existing configuration issue'}
    invoke, clock, _ = restart(monkeypatch, [initial, dict(initial, process_id=101)])
    invoke()
    assert clock[0] == 4
    assert 'Runtime protocols are not verified' in capsys.readouterr().out


def test_new_backend_error_is_not_misreported_as_preexisting(monkeypatch):
    initial = {'state':'error', 'process_id':100, 'state_message':'old error'}
    invoke, _, _ = restart(monkeypatch, [initial, dict(initial, process_id=101, state_message='new error')])
    with pytest.raises(deploy.DeployError, match='did not reach verified'): invoke()


@pytest.mark.parametrize('guard', [False, True])
def test_restart_verifies_intended_restored_screen_policy(monkeypatch, guard):
    invoke, _, _ = restart(monkeypatch, [READY, dict(READY, process_id=101)])
    observed = []
    monkeypatch.setattr(preload, 'verify_guard', lambda ctx: observed.append('guard'))
    monkeypatch.setattr(preload, 'verify_stock_client', lambda ctx: observed.append('stock'))
    invoke(expected_guard=guard)
    assert observed == ['guard' if guard else 'stock']


def test_uninstall_requests_stock_verification(monkeypatch):
    calls = []
    monkeypatch.setattr(preload, 'sources', lambda: [('head-config-guard','source')])
    monkeypatch.setattr(preload, '_checked', lambda *args, **kw: None)
    monkeypatch.setattr(preload, '_restart', lambda ctx, c, **kw: calls.append(kw))
    preload.uninstall(NS(user='test', ssh=lambda: None))
    assert calls == [{'expected_guard': False}]


def test_recovery_derives_restored_policy_instead_of_candidate_guard(monkeypatch):
    calls = []
    monkeypatch.setattr(preload, '_restart', lambda ctx, c, **kw: calls.append(kw))
    preload.finish_recovery(NS(ssh=lambda: None))
    assert calls == [{'expected_guard': None}]


@pytest.mark.parametrize('initial_pid,state', [('0','inactive'), ('0','failed'), ('99','active')])
def test_http_unavailable_baseline_uses_positive_service_observation(monkeypatch, initial_pid, state):
    invoke, _, calls = restart(monkeypatch, [OSError('HTTP unavailable'), READY],
        backend_service={'LoadState':'loaded','ActiveState':state,'MainPID':initial_pid})
    invoke()
    assert calls.count('systemctl restart klipper.service') == 1


def test_absent_service_cannot_invent_a_stopped_baseline(monkeypatch):
    invoke, _, _ = restart(monkeypatch, [OSError('HTTP unavailable'), READY],
        backend_service={'LoadState':'not-found','ActiveState':'inactive','MainPID':'0'})
    with pytest.raises(deploy.DeployError, match='did not reach verified'): invoke()
