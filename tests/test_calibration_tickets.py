"""Bounded maintenance history without resurrecting retired commands."""
import pytest
from test_calibration_commands import AttemptCommand, setup, module
from test_calibration_save_result import machine


def ticket(runner, text='M400', number=None, sequence=0, request=None):
    number = runner._ticket_counter + 1 if number is None else number
    command = AttemptCommand(runner, text, request=request or ('%032x' % number), sequence=sequence)
    command.binding['TICKET'] = str(number)
    return command


def test_more_than_1024_attempts_and_saves_keep_bounded_history(machine):
    p, runner, path, expected = machine
    original_session, editor = runner.session, runner.probe_editor
    editor.state = 'save_review'
    first = None
    for number in range(1, 1101):
        command = ticket(runner, number=number)
        if first is None: first = command
        runner.cmd_run(command)
        runner.cmd_run(ticket(runner, 'SAVE_CONFIG', number, 1))
        assert runner._ticket_counter == number
        assert not runner._attempts and not runner._save_requests
        assert runner._current_attempt is runner._ticket_attempt
        assert runner._ticket_attempt['state'] == 'saved'
    assert runner.session == original_session and runner.probe_editor is editor
    assert editor.state == 'save_review'
    before = list(p.sent)
    for command in (first, ticket(runner, number=1, sequence=1), ticket(runner, 'SAVE_CONFIG', 1, 2)):
        with pytest.raises(RuntimeError, match='retired'):
            runner.cmd_run(command)
    assert p.sent == before and runner._ticket_attempt['state'] == 'saved'


def test_old_ticket_cannot_clean_or_change_current_attempt():
    p, runner = setup()
    runner.cmd_run(ticket(runner, number=1))
    runner.cmd_run(ticket(runner, number=2))
    current = runner._ticket_attempt.copy()
    for text, seq in [('M400', 0), ('G28', 1), ('SAVE_CONFIG', 2)]:
        with pytest.raises(RuntimeError, match='retired'):
            runner.cmd_run(ticket(runner, text, 1, seq))
    assert runner._ticket_attempt == current and not runner.failure and p.off == 0
    runner.cmd_run(ticket(runner, number=2, sequence=1))


def test_running_command_cannot_consume_next_ticket_or_replace_current():
    p, runner = setup()
    def nested(command):
        attempt = runner._ticket_attempt
        with pytest.raises(RuntimeError, match='already running'):
            runner.cmd_run(ticket(runner, number=2))
        assert runner._ticket_counter == 1 and runner._ticket_attempt is attempt
    p.on_run = nested
    runner.cmd_run(ticket(runner, number=1))
    p.on_run = lambda command: None
    runner.cmd_run(ticket(runner, number=2))


@pytest.mark.parametrize('change', ['session', 'request', 'sequence', 'future', 'missing-sequence', 'malformed'])
def test_ticket_requires_exact_current_session_request_and_order(change):
    p, runner = setup()
    runner.cmd_run(ticket(runner, number=1))
    command = ticket(runner, number=1, sequence=1)
    if change == 'session': command.binding['SESSION'] = 'b' * 32
    elif change == 'request': command.binding['REQUEST'] = 'b' * 32
    elif change == 'sequence': command.binding['SEQUENCE'] = '0'
    elif change == 'future': command.binding['TICKET'] = '3'
    elif change == 'missing-sequence': del command.binding['SEQUENCE']
    else: command.binding['TICKET'] = '01'
    before = list(p.sent)
    with pytest.raises(RuntimeError): runner.cmd_run(command)
    assert p.sent == before


def test_failed_save_stays_single_use_and_fresh_ticket_recovers(machine):
    p, runner, path, expected = machine
    runner.cmd_run(ticket(runner, number=1))
    p.on_run = lambda command: (_ for _ in ()).throw(RuntimeError('writer failed'))
    with pytest.raises(RuntimeError, match='writer failed'):
        runner.cmd_run(ticket(runner, 'SAVE_CONFIG', 1, 1))
    before = list(p.sent)
    with pytest.raises(RuntimeError): runner.cmd_run(ticket(runner, 'SAVE_CONFIG', 1, 2))
    assert p.sent == before
    p.on_run = lambda command: None
    runner.cmd_run(ticket(runner, number=2))
    assert not runner.failure


def test_legacy_history_retained_and_full_does_not_block_updated_client():
    p, runner = setup()
    for number in range(1024):
        runner.cmd_run(AttemptCommand(runner, 'M400', request='%032x' % number))
    with pytest.raises(RuntimeError, match='update the WM\\+ screen'):
        runner.cmd_run(AttemptCommand(runner, 'M400', request='f' * 32))
    runner.cmd_run(ticket(runner))
    assert len(runner._attempts) == 1024 and runner._ticket_counter == 1
    with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'M400', request='0' * 32))


def test_backend_restart_rejects_ticket_without_rotating_probe_session_in_process():
    p, runner = setup()
    old = ticket(runner)
    runner.cmd_run(old)
    replacement = module.CalibrationCommands(p, p)
    with pytest.raises(RuntimeError, match='SESSION differs'):
        replacement.cmd_run(old)
    assert replacement._ticket_counter == 0


@pytest.mark.parametrize('text', ['M400', 'SAVE_CONFIG'])
@pytest.mark.parametrize('sequenced', [False, True])
def test_current_ticket_cannot_downgrade_to_legacy(text, sequenced):
    p, runner = setup()
    runner.cmd_run(ticket(runner, number=1))
    command = ticket(runner, text, 1, 1)
    del command.binding['TICKET']
    if not sequenced: del command.binding['SEQUENCE']
    before, attempt = list(p.sent), dict(runner._ticket_attempt)
    with pytest.raises(RuntimeError, match='requires its TICKET'):
        runner.cmd_run(command)
    assert p.sent == before and runner._ticket_attempt == attempt
    assert not runner._attempts and not runner._save_requests
