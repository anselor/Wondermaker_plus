import copy
import pytest
from wm_material import RecoveryAttempt

REQUEST = dict(id='recover-1', session='session-1', execution_hash='a' * 16, file='part.gcode')


def test_attempt_records_before_dispatch_and_requires_completion():
    journal, calls = [], []
    runner = RecoveryAttempt(lambda record: journal.append(record))
    def dispatch():
        assert journal[-1]['state'] == 'running'
        assert journal[-1]['stages'][0]['state'] == 'running'
        calls.append('dispatch')
    result = runner.run(REQUEST, [('prepare', dispatch, lambda: calls.append('verify') or True)])
    assert calls == ['dispatch', 'verify']
    assert result['state'] == journal[-1]['state'] == 'complete'
    assert journal[0]['state'] == 'pending'
    with pytest.raises(ValueError, match='already attempted'):
        runner.run(REQUEST, [('prepare', dispatch, lambda: True)])


@pytest.mark.parametrize('failure', ['dispatch', 'verify', 'persist'])
def test_failure_stops_tail_but_fresh_request_rechecks_after_correction(failure):
    calls, journal = [], []
    def persist(record):
        if failure == 'persist' and record['state'] == 'running':
            raise OSError('disk failed')
        journal.append(record)
    runner = RecoveryAttempt(persist)
    def dispatch():
        calls.append('first')
        if failure == 'dispatch':
            raise RuntimeError('reply lost')
    with pytest.raises((RuntimeError, ValueError, OSError)):
        runner.run(REQUEST, [('first', dispatch, lambda: failure != 'verify'),
                             ('second', lambda: calls.append('second'), lambda: True)])
    assert 'second' not in calls
    assert runner.record['state'] == 'unknown'
    if failure == 'persist':
        assert calls == []
    with pytest.raises(ValueError, match='already attempted'):
        runner.run(REQUEST, [('first', dispatch, lambda: True)])
    # Repair the failed dependency before a new explicit request. The old tail
    # must never be resumed implicitly merely because history was retired.
    failure = None
    result = runner.run(dict(REQUEST, id='new'), [('fresh', lambda: calls.append('fresh'), lambda: True)])
    assert result['state'] == 'complete' and calls[-1] == 'fresh'
    assert 'second' not in calls


@pytest.mark.parametrize('state', ['pending', 'running'])
def test_restart_preserves_uncertainty(state):
    journal = []
    runner = RecoveryAttempt(journal.append)
    runner.run(REQUEST, [('prepare', lambda: None, lambda: True)])
    interrupted = copy.deepcopy(journal[-1])
    interrupted['state'] = state
    restored = RecoveryAttempt(journal.append, interrupted)
    assert restored.record['state'] == journal[-1]['state'] == 'unknown'
    assert interrupted['state'] == state
    assert not restored.busy
    calls = []
    with pytest.raises(ValueError, match='already attempted'):
        restored.run(REQUEST, [('prepare', lambda: calls.append('stale'), lambda: True)])
    result = restored.run(dict(REQUEST, id='new'), [('prepare', lambda: calls.append('fresh'), lambda: True)])
    assert result['state'] == 'complete' and calls == ['fresh']


def test_cancel_stops_before_next_stage():
    calls, journal = [], []
    runner = RecoveryAttempt(journal.append)
    result = runner.run(REQUEST, [('first', lambda: calls.append('first'), lambda: True),
                                 ('second', lambda: calls.append('second'), lambda: True)],
                        cancelled=lambda: bool(calls))
    assert calls == ['first']
    assert result['state'] == 'stopped'
    assert result['stages'][0]['state'] == 'complete'
    assert result['stages'][1]['state'] == 'pending'


def test_nested_attempt_refused_and_request_is_immutable():
    request = dict(REQUEST)
    runner = RecoveryAttempt(lambda record: None)
    def dispatch():
        request['file'] = 'changed.gcode'
        with pytest.raises(ValueError, match='running'):
            runner.run(dict(REQUEST, id='nested'), [('nested', lambda: None, lambda: True)])
    result = runner.run(request, [('prepare', dispatch, lambda: True)])
    assert result['request']['file'] == 'part.gcode'


def test_initial_journal_failure_dispatches_nothing():
    calls = []
    def fail(record):
        raise OSError('read-only filesystem')
    runner = RecoveryAttempt(fail)
    with pytest.raises(OSError):
        runner.run(REQUEST, [('prepare', lambda: calls.append('move'), lambda: True)])
    assert calls == [] and runner.record['state'] == 'unknown'


def test_truthy_result_is_not_completion_evidence():
    runner = RecoveryAttempt(lambda record: None)
    with pytest.raises(ValueError, match='not confirmed'):
        runner.run(REQUEST, [('prepare', lambda: None, lambda: 'submitted')])
    assert runner.record['state'] == 'unknown'


@pytest.mark.parametrize('mutation', ['version', 'request', 'stage', 'order', 'completion'])
def test_malformed_journal_refused(mutation):
    runner = RecoveryAttempt(lambda record: None)
    runner.run(REQUEST, [('first', lambda: None, lambda: True), ('second', lambda: None, lambda: True)])
    record = copy.deepcopy(runner.record)
    if mutation == 'version':
        record['version'] = True
    elif mutation == 'request':
        record['request']['execution_hash'] = 'bad'
    elif mutation == 'stage':
        record['stages'][0]['name'] = 'bad name'
    elif mutation == 'order':
        record['state'] = 'running'
        record['stages'][0]['state'] = 'pending'
    else:
        record['stages'][1]['state'] = 'pending'
    with pytest.raises(ValueError):
        RecoveryAttempt(lambda record: None, record)


def test_stopped_attempt_allows_fresh_explicit_request_without_replaying_old_tail():
    runner = RecoveryAttempt(lambda record: None)
    runner.run(REQUEST, [('prepare', lambda: None, lambda: True)], cancelled=lambda: True)
    calls = []
    result = runner.run(dict(REQUEST, id='retry'), [('prepare', lambda: calls.append('fresh'), lambda: True)])
    assert result['state'] == 'complete' and calls == ['fresh']


@pytest.mark.parametrize('state', ['complete', 'paused', 'cancelled', 'unknown'])
def test_continuation_outcome_survives_journal_restore(state):
    runner = RecoveryAttempt(lambda record: None)
    runner.run(REQUEST, [('start_file', lambda: None, lambda: True)])
    runner._save(state='unknown' if state == 'unknown' else 'complete',
        continuation={'state': state, 'file_position': 123, 'error': 'lost outcome' if state == 'unknown' else ''})
    restored = RecoveryAttempt(lambda record: None, runner.record)
    assert restored.record == runner.record


@pytest.mark.parametrize('field,value', [('state', 'printing'), ('file_position', True),
                                         ('file_position', -1), ('error', None)])
def test_invalid_continuation_outcome_is_not_accepted(field, value):
    runner = RecoveryAttempt(lambda record: None)
    runner.run(REQUEST, [('start_file', lambda: None, lambda: True)])
    record = copy.deepcopy(runner.record)
    record['continuation'] = {'state': 'paused', 'file_position': 123, 'error': ''}
    record['continuation'][field] = value
    with pytest.raises(ValueError, match='continuation'):
        RecoveryAttempt(lambda record: None, record)


@pytest.mark.parametrize('phase', ['scheduled', 'started'])
def test_restart_retains_interrupted_worker_phase_as_unknown(phase):
    runner = RecoveryAttempt(lambda record: None)
    runner.run(REQUEST, [('start_file', lambda: None, lambda: True)])
    runner._save(checkpoint={'job_fingerprint': 'b' * 16, 'file_position': 123},
                 continuation={'state': phase, 'file_position': 123, 'error': ''})
    writes = []
    restored = RecoveryAttempt(writes.append, runner.record)
    assert restored.record['state'] == 'unknown'
    assert restored.record['continuation']['state'] == 'interrupted'
    assert writes[-1] == restored.record
    calls = []
    with pytest.raises(ValueError, match='already attempted'):
        restored.run(REQUEST, [('start_file', lambda: calls.append('stale'), lambda: True)])
    result = restored.run(dict(REQUEST, id='new-request'), [('start_file', lambda: calls.append('fresh'), lambda: True)])
    assert result['state'] == 'complete' and calls == ['fresh']


@pytest.mark.parametrize('when', ['dispatch', 'verify', 'persist'])
def test_replaced_attempt_record_is_never_modified_or_persisted_by_old_run(when):
    writes, calls, replacement = [], [], []
    runner = None
    def replace():
        value = copy.deepcopy(runner.record)
        value['request']['id'] = 'replacement'
        replacement.append((value, copy.deepcopy(value)))
        runner.record = value
    def persist(value):
        writes.append(copy.deepcopy(value))
        if when == 'persist' and value['state'] == 'running' and not replacement: replace()
    runner = RecoveryAttempt(persist)
    def dispatch():
        calls.append('dispatch')
        if when == 'dispatch': replace()
    def verify():
        calls.append('verify')
        if when == 'verify': replace()
        return True
    with pytest.raises(ValueError, match='ownership changed'):
        runner.run(REQUEST, [('first', dispatch, verify), ('second', lambda: calls.append('tail'), lambda: True)])
    value, before = replacement[0]
    assert runner.record is value and value == before and runner.busy is True
    assert 'tail' not in calls
    assert all(row['request']['id'] != 'replacement' for row in writes)


def test_old_attempt_exception_does_not_rewrite_a_replacement_receipt():
    writes = []
    runner = RecoveryAttempt(lambda value: writes.append(copy.deepcopy(value)))
    replacement = []
    def dispatch():
        value = copy.deepcopy(runner.record);value['request']['id'] = 'replacement'
        runner.record = value;replacement.append(copy.deepcopy(value))
        raise RuntimeError('original stage failed')
    with pytest.raises(RuntimeError, match='original stage failed'):
        runner.run(REQUEST, [('first', dispatch, lambda: True)])
    assert runner.record == replacement[0] and runner.busy is True
    assert all(row['request']['id'] != 'replacement' for row in writes)


@pytest.mark.parametrize('lost', ['false', 'error'])
def test_attempt_owner_loss_stops_without_old_journal_cleanup(lost):
    journal, calls, ownership = [], [], [True]
    runner = RecoveryAttempt(lambda value: journal.append(copy.deepcopy(value)))
    def owner():
        if ownership[0] is False and lost == 'error': raise ValueError('owner evidence unavailable')
        return ownership[0]
    def dispatch():
        calls.append('first');ownership[0] = False
    with pytest.raises(ValueError, match='ownership changed'):
        runner.run(REQUEST, [('first', dispatch, lambda: calls.append('verify') or True),
                             ('tail', lambda: calls.append('tail'), lambda: True)], owner=owner)
    assert calls == ['first'] and not runner.busy
    assert runner.record['state'] == journal[-1]['state'] == 'running'
    assert runner.record['error'] == ''


def test_attempt_record_is_bound_before_initial_persistence():
    bound = []
    runner = None
    def persist(record):
        assert bound == [runner.record] and bound[0]['request'] == REQUEST
    runner = RecoveryAttempt(persist)
    result = runner.run(REQUEST, [('first', lambda: None, lambda: True)], started=bound.append)
    assert result['state'] == 'complete'


def test_owner_callback_cannot_replace_receipt_while_returning_true():
    runner = RecoveryAttempt(lambda value: None)
    replace, replacement = [False], []
    def owner():
        if replace[0] and not replacement:
            record = copy.deepcopy(runner.record);record['request']['id'] = 'replacement'
            runner.record = record;replacement.append(copy.deepcopy(record))
        return True
    with pytest.raises(ValueError, match='ownership changed'):
        runner.run(REQUEST, [('first', lambda: replace.__setitem__(0, True), lambda: True)], owner=owner)
    assert runner.record == replacement[0] and runner.busy is True
