"""Stored tool offsets recorded per calibration attempt and restored on request."""
import ast
from types import SimpleNamespace
import pytest
from test_nozzle_scrub_commands import Command, bound, setup

OFFSETS = {'t0_offset': (0.0, 0.0, 0.0), 't1_offset': (0.1, -0.2, 0.05),
           't2_offset': (-1.25, 0.5, -0.0125), 't3_offset': (2.0, 1e-05, 0.3)}


def machine(variables=None, fail_head=None):
    printer, gcode, runner = setup()
    stored = dict(OFFSETS if variables is None else variables)
    printer.objects['save_variables'] = SimpleNamespace(
        allVariables=stored, get_status=lambda _: {'variables': stored})
    writes = []

    def save_variable(gcmd):
        name, value = gcmd.get('VARIABLE'), gcmd.get('VALUE')
        if fail_head is not None and name == 't%d_offset' % fail_head:
            raise RuntimeError('Unable to save variable')
        writes.append((name, value))
        stored[name] = ast.literal_eval(value)
    gcode.commands['SAVE_VARIABLE'] = save_variable
    return printer, gcode, runner, stored, writes


def restore_state(runner):
    return runner.nozzle_touch.get_status()['restore']


def test_snapshot_taken_once_when_the_attempt_is_admitted():
    printer, gcode, runner, stored, writes = machine()
    bound(runner, 'G28', 'a', 0)
    stored['t2_offset'] = (9.0, 9.0, 9.0)
    gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=t1_offset VALUE=7.0,7.0,7.0')
    bound(runner, 'RAPID_MODE T=1', 'a', 1)
    assert runner.offset_snapshot.offsets == OFFSETS


def test_restore_writes_all_four_heads_and_reports_done():
    printer, gcode, runner, stored, writes = machine()
    bound(runner, 'G28', 'a', 0)
    for name in ('t0_offset', 't1_offset', 't2_offset', 't3_offset'):
        stored[name] = (5.0, 5.0, 5.0)
    del writes[:]
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert [name for name, _ in writes] == ['t0_offset', 't1_offset', 't2_offset', 't3_offset']
    assert stored == OFFSETS
    assert gcode.sent[-4:] == ['SAVE_VARIABLE VARIABLE=t%d_offset VALUE=%s' % (head, value) for head, value in
                               enumerate(('0.0,0.0,0.0', '0.1,-0.2,0.05', '-1.25,0.5,-0.0125', '2.0,1e-05,0.3'))]
    assert runner.offset_snapshot.state == 'done'
    assert restore_state(runner) == 'done'


def test_restore_failure_reports_failed_and_does_not_raise():
    printer, gcode, runner, stored, writes = machine(fail_head=2)
    bound(runner, 'G28', 'a', 0)
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert restore_state(runner) == 'failed'
    assert runner.failure == ''
    assert runner.attempt_result['state'] == 'pending'


def test_restore_without_a_snapshot_reports_failed():
    variables = dict(OFFSETS)
    del variables['t3_offset']
    printer, gcode, runner, stored, writes = machine(variables)
    bound(runner, 'G28', 'a', 0)
    stored['t3_offset'] = (1.0, 1.0, 1.0)
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert writes == []
    assert restore_state(runner) == 'failed'
    assert runner.failure == ''


@pytest.mark.parametrize('value', [None, (1.0, 2.0), 'x', (1.0, 'a', 2.0)])
def test_malformed_stored_offset_is_no_snapshot(value):
    variables = dict(OFFSETS, t1_offset=value)
    printer, gcode, runner, stored, writes = machine(variables)
    bound(runner, 'G28', 'a', 0)
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert writes == [] and restore_state(runner) == 'failed'


def test_restore_refused_outside_the_current_attempt():
    printer, gcode, runner, stored, writes = machine()
    bound(runner, 'G28', 'a', 0)
    with pytest.raises(RuntimeError):
        gcode.commands['_WMP_OFFSETS_RESTORE'](Command('_WMP_OFFSETS_RESTORE'))
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('_WMP_OFFSETS_RESTORE'))  # Unbound wrapper call.
    bound(runner, 'G28', 'b', 0)
    with pytest.raises(RuntimeError):
        bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)  # Superseded attempt.
    assert writes == []
    assert restore_state(runner) == 'none'


def test_restore_refused_while_another_command_runs():
    printer, gcode, runner, stored, writes = machine()
    bound(runner, 'G28', 'a', 0)
    seen = []
    # Hold a non-producing command. G29 now also requires the real scoped
    # checkpoint/configuration producer, covered by test_calibration_checkpoints.
    # This test isolates the rule that no in-flight command may restore offsets.
    gcode.commands['M400'] = lambda gcmd: seen.append(
        pytest.raises(RuntimeError, bound, runner, '_WMP_OFFSETS_RESTORE', 'a', 2))
    bound(runner, 'M400', 'a', 1)
    assert seen and writes == []
    assert restore_state(runner) == 'none'


def test_scrub_end_is_admitted_after_a_failed_restore():
    printer, gcode, runner, stored, writes = machine(fail_head=2)
    bound(runner, '_WMP_SCRUB_HEAD T=1', 'a', 0)
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert restore_state(runner) == 'failed'
    bound(runner, '_WMP_SCRUB_END', 'a', 2)
    assert gcode.sent[-1] == 'PARK_CURRENT_TOOL'
    assert printer.heaters['extruder1'].target_temp == 0.
    assert runner.nozzle_scrub.get_status()['phase'] == 'ended'
    assert runner.attempt_result['offsets'] == 'stopped'


def test_new_attempt_clears_the_restore_state():
    printer, gcode, runner, stored, writes = machine(fail_head=2)
    bound(runner, 'G28', 'a', 0)
    bound(runner, '_WMP_OFFSETS_RESTORE', 'a', 1)
    assert restore_state(runner) == 'failed'
    stored['t1_offset'] = (3.0, 3.0, 3.0)
    bound(runner, 'G28', 'b', 0)
    assert restore_state(runner) == 'none'
    assert runner.offset_snapshot.offsets['t1_offset'] == (3.0, 3.0, 3.0)


def test_owner_reset_failure_does_not_skip_the_others():
    printer, gcode, runner, stored, writes = machine()
    runner.nozzle_touch.request = 'old'

    def broken(request):
        raise RuntimeError('progress reset failed')
    runner.progress.reset = broken
    with pytest.raises(RuntimeError, match='progress reset failed'):
        bound(runner, 'G28', 'a', 0)
    assert runner.nozzle_touch.request == 'a' * 32
    assert runner.offset_snapshot.offsets == OFFSETS


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_offset_is_not_a_restorable_snapshot(value):
    printer,gcode,runner,stored,writes=machine(dict(OFFSETS,t1_offset=(value,0.,0.)))
    bound(runner,'G28','a',0)
    bound(runner,'_WMP_OFFSETS_RESTORE','a',1)
    assert runner.offset_snapshot.state=='failed' and writes==[]


def test_restore_requires_actual_value_readback_not_only_command_success():
    printer,gcode,runner,stored,writes=machine()
    bound(runner,'G28','a',0)
    stored['t1_offset']=(5.,5.,5.)
    gcode.commands['SAVE_VARIABLE']=lambda cmd:None
    bound(runner,'_WMP_OFFSETS_RESTORE','a',1)
    assert runner.offset_snapshot.state=='failed'
    assert stored['t1_offset']==(5.,5.,5.)
