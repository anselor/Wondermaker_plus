"""Offset-stage outcome and the one early save of earlier calibration results."""
import pytest
from test_calibration_commands import Command, AttemptCommand
from test_calibration_save_result import SaveCommand, machine, restore


# Offset stage stopped: results of bed level, vibration and PID completed
# earlier in the same attempt are saved once.
def stage(runner, text, sequence, ticket=None):
    command = AttemptCommand(runner, text, sequence=sequence)
    if ticket is not None:
        command.binding['TICKET'] = str(ticket)
    runner.cmd_run(command)


def stop_offset_stage_from(machine, sequence, failing='_WMP_SCRUB_HEAD T=0'):
    """After G28 at sequence 0: G29, then a failed scrub command."""
    p, runner, path, expected = machine
    writer = p.on_run
    def run(command):
        if command == failing:
            raise RuntimeError('stage failed')
        writer(command)
    p.on_run = run
    stage(runner, 'G29', sequence)
    with pytest.raises(RuntimeError, match='stage failed'):
        stage(runner, failing, sequence + 1)
    return sequence + 2


def stop_offset_stage(machine, earlier=('G29',), failing='_WMP_SCRUB_HEAD T=0', flag=0, before=(), ticket=None):
    """Runs earlier stages, then fails one command. Returns the next sequence."""
    p, runner, path, expected = machine
    writer = p.on_run
    def run(command):
        if command == failing:
            p.fail = flag
            raise RuntimeError('stage failed')
        writer(command)
    p.on_run = run
    sequence = 0
    for text in ('G28',) + tuple(earlier) + tuple(before):
        stage(runner, text, sequence, ticket)
        sequence += 1
    with pytest.raises(RuntimeError, match='stage failed'):
        stage(runner, failing, sequence, ticket)
    assert runner.failure and runner.attempt_result['state'] == 'failed'
    return sequence + 1


@pytest.mark.parametrize('ticket', [None, 1])
@pytest.mark.parametrize('earlier', [('G29',), ('SHAPER_CALIBRATE',), ('PID_CALIBRATE HEATER=extruder TARGET=220',)])
def test_save_admitted_after_scrub_failure_with_earlier_results(machine, earlier, ticket):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine, earlier=earlier, ticket=ticket)
    assert runner.attempt_result['earlier_results'] and runner.attempt_result['offset_stage']
    assert runner.attempt_result['offsets'] == 'stopped'
    stage(runner, 'SAVE_CONFIG', sequence, ticket)
    assert p.sent[-1] == 'SAVE_CONFIG' and p.restarts == ['firmware_restart']
    assert runner.save_result['state'] == 'saved' and runner.save_result['request'] == 'a' * 32
    # The attempt stays failed and the operation latch stays set.
    assert runner.attempt_result['state'] == 'failed' and runner.failure
    assert runner.attempt_result['offsets'] == 'stopped'
    assert restore(p).save_result['state'] == 'confirmed'


def test_save_admitted_after_rapid_mode_failure_with_earlier_results(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine, before=('RAPID_MODE T=0',), failing='RAPID_MODE T=1', flag=-2)
    assert runner.attempt_result['offsets'] == 'stopped'
    stage(runner, 'SAVE_CONFIG', sequence)
    assert p.sent[-1] == 'SAVE_CONFIG' and runner.save_result['state'] == 'saved'


@pytest.mark.parametrize('mode', ['exception', 'soft-flag'])
def test_save_refused_after_pid_failure(machine, mode):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    writer = p.on_run
    def run(command):
        if mode == 'exception':
            raise RuntimeError('PID failed')
        p.fail = -3
    p.on_run = run
    with pytest.raises(RuntimeError):
        stage(runner, 'PID_CALIBRATE HEATER=extruder TARGET=220', 2)
    p.on_run, p.fail = writer, 0
    assert not runner.attempt_result['offset_stage'] and runner.attempt_result['offsets'] == 'none'
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', 3)
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []


@pytest.mark.parametrize('earlier', [(), ('M400',)])
def test_save_refused_after_offset_failure_without_earlier_results(machine, earlier):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine, earlier=earlier)
    assert not runner.attempt_result['earlier_results'] and runner.attempt_result['offsets'] == 'stopped'
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []


def test_earlier_result_that_failed_softly_is_not_an_earlier_result(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    p.on_run = lambda command: setattr(p, 'fail', -3)
    with pytest.raises(RuntimeError):
        stage(runner, 'G29', 1)
    assert not runner.attempt_result['earlier_results']


@pytest.mark.parametrize('ticket', [None, 1])
def test_second_save_after_failure_refused(machine, ticket):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine, ticket=ticket)
    stage(runner, 'SAVE_CONFIG', sequence, ticket)
    for again in (sequence, sequence + 1):
        with pytest.raises(RuntimeError, match='already stopped'):
            stage(runner, 'SAVE_CONFIG', again, ticket)
    assert p.sent.count('SAVE_CONFIG') == 1 and p.restarts == ['firmware_restart']


def test_failed_early_save_is_not_repeated(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    p.on_run = lambda command: (_ for _ in ()).throw(RuntimeError('writer failed'))
    with pytest.raises(RuntimeError, match='writer failed'):
        stage(runner, 'SAVE_CONFIG', sequence)
    p.on_run = lambda command: None
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence + 1)
    assert p.sent.count('SAVE_CONFIG') == 1 and runner.save_result['state'] == 'unconfirmed'


def test_fail_flag_survives_early_save(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine, before=('_WMP_SCRUB_HEAD T=0',), failing='RAPID_MODE T=0', flag=-2)
    before = list(p.sent)
    stage(runner, 'SAVE_CONFIG', sequence)
    # Only the configuration writer ran: nothing rewrote saved variables.
    assert p.sent == before + ['SAVE_CONFIG']
    assert p.lookup_object('save_variables').get_status(0)['variables']['fail_flag'] == -2
    # The flag still refuses the next attempt.
    with pytest.raises(RuntimeError, match='fail_flag'):
        runner.cmd_run(AttemptCommand(runner, 'G28', request='c' * 32))
    assert p.sent == before + ['SAVE_CONFIG']


def test_early_save_refused_when_shut_down(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    p.shutdown = True
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []
    # The refusal does not use up the one save.
    p.shutdown = False
    stage(runner, 'SAVE_CONFIG', sequence)
    assert p.sent.count('SAVE_CONFIG') == 1


def test_early_save_refused_while_quick_stop_is_active(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    p.quick_stop_flag = True
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []
    assert not runner.attempt_status()['early_save_available']


@pytest.mark.parametrize('command', ['G28', 'M400', 'PARK_CURRENT_TOOL', 'RAPID_MODE T=1', '_WMP_SCRUB_HEAD T=1',
                                     '_WMP_SCRUB_END', '_WMP_SCRUB_ATTENTION VALUE=0', 'G29'])
def test_other_commands_still_refused_after_failure(machine, command):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    before = list(p.sent)
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, command, sequence)
    assert p.sent == before
    # Unbound and differently bound saves stay refused as well.
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('SAVE_CONFIG'))
    with pytest.raises(RuntimeError):
        runner.cmd_run(SaveCommand(runner))
    with pytest.raises(RuntimeError):
        runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', request='c' * 32))
    assert p.sent == before and p.restarts == []


@pytest.mark.parametrize('command', ['G28', 'PARK_CURRENT_TOOL', 'RAPID_MODE T=1', '_WMP_SCRUB_END', 'SAVE_CONFIG'])
def test_commands_still_refused_after_the_early_save(machine, command):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    stage(runner, 'SAVE_CONFIG', sequence)
    before = list(p.sent)
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, command, sequence + 1)
    with pytest.raises(RuntimeError, match='Calibration stopped'):
        runner.cmd_run(Command(command))
    assert p.sent == before and p.restarts == ['firmware_restart']


def test_early_save_admitted_with_a_later_sequence(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    stage(runner, 'SAVE_CONFIG', sequence + 3)
    assert p.sent.count('SAVE_CONFIG') == 1 and runner.save_result['state'] == 'saved'
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence + 4)
    assert p.sent.count('SAVE_CONFIG') == 1


def test_sequence_gap_in_offset_stage_admits_one_save(machine):
    # A scrub send that failed in the client used a sequence number the
    # backend never saw: the next command arrives with a gap.
    p, runner, path, expected = machine
    for sequence, text in enumerate(('G28', 'G29', '_WMP_SCRUB_HEAD T=0')):
        stage(runner, text, sequence)
    with pytest.raises(RuntimeError, match='out of order'):
        stage(runner, '_WMP_SCRUB_END', 4)
    assert runner.attempt_result['state'] == 'failed' and runner.attempt_result['offsets'] == 'stopped'
    assert runner.failure and '_WMP_SCRUB_END' not in p.sent
    stage(runner, 'SAVE_CONFIG', 5)
    assert p.sent[-1] == 'SAVE_CONFIG' and p.restarts == ['firmware_restart']
    before = list(p.sent)
    for command in ('M400', 'SAVE_CONFIG', '_WMP_SCRUB_END'):
        with pytest.raises(RuntimeError, match='already stopped'):
            stage(runner, command, 6)
    assert p.sent == before and p.restarts == ['firmware_restart']


@pytest.mark.parametrize('later', [4, 5, 9])
def test_sequence_gap_before_offset_stage_refuses_save(machine, later):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    with pytest.raises(RuntimeError, match='out of order'):
        stage(runner, 'SHAPER_CALIBRATE', 3)
    assert runner.attempt_result['earlier_results'] and runner.attempt_result['offsets'] == 'none'
    assert not runner.attempt_status()['early_save_available']
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', later)
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []


@pytest.mark.parametrize('below', [0, 1, 2])
def test_early_save_with_sequence_below_next_refused(machine, below):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)  # G28, G29, failed scrub command: next is 3
    assert sequence == 3 and runner.attempt_result['next'] == 3
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', below)
    assert 'SAVE_CONFIG' not in p.sent and runner.attempt_status()['early_save_available']


def test_early_save_available_tracks_admission(machine):
    p, runner, path, expected = machine
    assert 'early_save_available' not in runner.attempt_status()  # no attempt yet
    stage(runner, 'G28', 0)
    assert runner.attempt_status()['early_save_available'] is False
    sequence = stop_offset_stage_from(machine, 1)
    assert runner.attempt_status()['early_save_available'] is True
    p.shutdown = True
    assert runner.attempt_status()['early_save_available'] is False
    p.shutdown = False
    # Status and admission use one predicate.
    assert runner._early_save_available(runner.attempt_result) is True
    stage(runner, 'SAVE_CONFIG', sequence)
    assert runner.attempt_status()['early_save_available'] is False
    assert 'early_save_available' not in runner.attempt_result  # computed, not stored


def test_early_save_unavailable_after_pid_failure(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    p.on_run = lambda command: (_ for _ in ()).throw(RuntimeError('PID failed'))
    with pytest.raises(RuntimeError):
        stage(runner, 'PID_CALIBRATE HEATER=extruder TARGET=220', 2)
    assert runner.attempt_status()['state'] == 'failed'
    assert runner.attempt_status()['early_save_available'] is False


def test_early_save_unavailable_for_a_superseded_attempt_status(machine):
    p, runner, path, expected = machine
    stop_offset_stage(machine)
    with pytest.raises(RuntimeError):
        runner.cmd_run(AttemptCommand(runner, 'M112', request='c' * 32))
    # Status now shows the refused new attempt, which has nothing to save.
    assert runner.attempt_status()['request'] == 'c' * 32
    assert runner.attempt_status()['early_save_available'] is False


def test_failed_ordinary_save_keeps_offsets_measured_and_admits_no_early_save(machine):
    p, runner, path, expected = machine
    for sequence, text in enumerate(('G28', 'G29', 'RAPID_MODE T=0', 'PARK_CURRENT_TOOL')):
        stage(runner, text, sequence)
    assert runner.attempt_result['offsets'] == 'measured'
    p.on_run = lambda command: (_ for _ in ()).throw(RuntimeError('writer failed'))
    with pytest.raises(RuntimeError, match='writer failed'):
        stage(runner, 'SAVE_CONFIG', 4)
    assert runner.attempt_result['state'] == 'failed' and runner.attempt_result['offsets'] == 'measured'
    assert not runner.attempt_result.get('offset_stage_failure')
    assert runner.attempt_status()['early_save_available'] is False
    assert not runner._admit_early_save(AttemptCommand(runner, 'SAVE_CONFIG', sequence=5), runner.attempt_result, 5)
    p.on_run = lambda command: None
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', 5)
    assert p.sent.count('SAVE_CONFIG') == 1


def test_early_save_rejects_a_replayed_sequence(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence - 1)
    assert 'SAVE_CONFIG' not in p.sent


def test_early_save_refused_for_a_superseded_attempt(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    runner.cmd_run(AttemptCommand(runner, 'G28', request='c' * 32))
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert 'SAVE_CONFIG' not in p.sent


def test_cancelled_scrub_saves_normally(machine):
    p, runner, path, expected = machine
    for sequence, text in enumerate(('G28', 'G29', 'G28', '_WMP_SCRUB_HEAD T=0', '_WMP_SCRUB_END')):
        stage(runner, text, sequence)
    assert runner.attempt_result['state'] == 'pending' and runner.attempt_result['offsets'] == 'stopped'
    assert not runner.failure
    stage(runner, 'SAVE_CONFIG', 5)
    assert runner.attempt_result['state'] == 'saved' and runner.attempt_result['offsets'] == 'stopped'
    assert runner.save_result['state'] == 'saved' and p.restarts == ['firmware_restart']


def test_offsets_only_cancel_sends_no_save(machine):
    # The vendor worker sends no SAVE_CONFIG on an offsets-only run. One sent
    # anyway after a cancel is the ordinary save of a run that did not fail.
    p, runner, path, expected = machine
    for sequence, text in enumerate(('G28', '_WMP_SCRUB_HEAD T=0', '_WMP_SCRUB_END')):
        stage(runner, text, sequence)
    assert p.sent == ['G28', '_WMP_SCRUB_HEAD T=0', '_WMP_SCRUB_END'] and p.restarts == []
    assert runner.attempt_result['state'] == 'pending' and runner.attempt_result['offsets'] == 'stopped'
    assert not runner.attempt_result['earlier_results'] and runner.save_result['state'] == 'unconfirmed'


def test_offsets_measured_after_completed_rapid_mode(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    assert runner.attempt_result['offsets'] == 'none'
    stage(runner, 'RAPID_MODE T=0', 1)
    stage(runner, 'PARK_CURRENT_TOOL', 2)
    assert runner.attempt_result['offsets'] == 'measured' and runner.attempt_result['offset_stage']


# A bound save refused before its receipt is prepared still names its run, so
# the result page stops waiting for a restart.
def refused_receipt(runner, session, request):
    result = runner.save_result
    return (result['state'] == 'unconfirmed' and result['session'] == session
            and result['request'] == request and bool(result['error']))


def test_refused_early_save_publishes_a_receipt_for_its_run(machine):
    p, runner, path, expected = machine
    sequence = stop_offset_stage(machine)
    request = runner.attempt_result['request']
    p.shutdown = True
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert refused_receipt(runner, runner.session, request)
    # Another command refused the same way is not a save and publishes nothing.
    runner.save_result.update(session='', request='', error='')
    with pytest.raises(RuntimeError, match='already stopped'):
        stage(runner, 'G29', sequence)
    assert runner.save_result['request'] == ''
    # The admitted save replaces the refusal.
    p.shutdown = False
    stage(runner, 'SAVE_CONFIG', sequence)
    assert runner.save_result['request'] == request and runner.save_result['state'] != 'unconfirmed'


def test_save_refused_by_an_open_probe_editor_publishes_a_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    request = runner.attempt_result['request']
    runner.probe_editor.busy = lambda: True
    with pytest.raises(RuntimeError, match='probe editor'):
        stage(runner, 'SAVE_CONFIG', 2)
    assert refused_receipt(runner, runner.session, request)


def test_save_refused_by_the_live_check_publishes_a_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    request = runner.attempt_result['request']
    p.shutdown = True
    with pytest.raises(RuntimeError):
        stage(runner, 'SAVE_CONFIG', 2)
    assert 'SAVE_CONFIG' not in p.sent and refused_receipt(runner, runner.session, request)


def test_refused_save_of_another_run_does_not_replace_a_pending_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    runner.save_result.update(session=runner.session, request='f' * 32, state='pending', error='')
    command = AttemptCommand(runner, 'SAVE_CONFIG', sequence=7)
    with pytest.raises(RuntimeError):
        runner.cmd_run(command)
    assert runner.save_result['request'] == 'f' * 32 and runner.save_result['state'] == 'pending'


def test_replayed_save_does_not_replace_a_saved_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    stage(runner, 'SAVE_CONFIG', 2)
    assert runner.save_result['state'] == 'saved'
    with pytest.raises(RuntimeError):
        stage(runner, 'SAVE_CONFIG', 3)
    assert runner.save_result['state'] == 'saved'


def test_nested_save_does_not_replace_the_pending_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    writer = p.on_run
    seen = {}
    def run(command):
        if command == 'SAVE_CONFIG' and not seen:
            with pytest.raises(RuntimeError):
                stage(runner, 'SAVE_CONFIG', 3)
            seen['state'] = runner.save_result['state']
        writer(command)
    p.on_run = run
    stage(runner, 'SAVE_CONFIG', 2)
    assert seen['state'] == 'pending'


def test_save_refused_by_a_failure_from_an_unbound_command_publishes_a_receipt(machine):
    p, runner, path, expected = machine
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    stage(runner, '_WMP_SCRUB_END', 2)
    request = runner.attempt_result['request']
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('G999'))
    assert runner.failure
    with pytest.raises(RuntimeError, match='Calibration stopped'):
        stage(runner, 'SAVE_CONFIG', 3)
    assert refused_receipt(runner, runner.session, request)
