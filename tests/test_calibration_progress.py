"""Calibration progress phase command and lifecycle."""
import pytest
from test_calibration_early_save import stage
from test_calibration_save_result import machine  # noqa: F401  Fixture.
from test_nozzle_scrub_commands import Command, bound, setup, wrapped


def test_phase_records_progress_inside_calibration():
    printer, gcode, runner = setup()
    runner.active = True
    runner.progress.cmd_phase(Command('', HEAD='2', PHASE='height'))
    assert runner.progress.get_status() == {'protocol': 1, 'head': 2, 'phase': 'height', 'request': '', 'measured': [], 'measuring': False}


def test_phase_outside_calibration_is_ignored():
    printer, gcode, runner = setup()
    runner.progress.cmd_phase(Command('', HEAD='2', PHASE='docking'))
    assert runner.progress.get_status() == {'protocol': 1, 'head': -1, 'phase': 'idle', 'request': '', 'measured': [], 'measuring': False}


@pytest.mark.parametrize('params', [{'HEAD': '2', 'PHASE': 'bogus'}, {'HEAD': '2', 'PHASE': 'idle'},
                                    {'HEAD': '4', 'PHASE': 'height'}, {'PHASE': 'height'}, {'HEAD': '1'}])
@pytest.mark.parametrize('active', [True, False])
def test_phase_rejects_unknown_values(params, active):
    printer, gcode, runner = setup()
    runner.active = active
    with pytest.raises(RuntimeError):
        runner.progress.cmd_phase(Command('', **params))
    assert runner.progress.get_status()['phase'] == 'idle'


def test_g28_sets_homing_progress():
    printer, gcode, runner = setup()
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append(dict(runner.progress.get_status())), original(script))[1]
    bound(runner, 'G28', 'a', 0)
    assert seen[0] == {'protocol': 1, 'head': -1, 'phase': 'homing', 'request': 'a' * 32, 'measured': [], 'measuring': False}


def test_park_after_probing_sets_docking_progress():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    runner.active = True
    runner.progress.cmd_phase(Command('', HEAD='3', PHASE='height'))
    runner.active = False
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append(dict(runner.progress.get_status())), original(script))[1]
    bound(runner, 'PARK_CURRENT_TOOL', 'a', 1)
    assert seen[0] == {'protocol': 1, 'head': 3, 'phase': 'docking', 'request': 'a' * 32, 'measured': [], 'measuring': False}


def test_park_without_probing_leaves_progress():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    runner.progress.head, runner.progress.phase = -1, 'homing'
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append(dict(runner.progress.get_status())), original(script))[1]
    bound(runner, 'PARK_CURRENT_TOOL', 'a', 1)
    assert seen[0] == {'protocol': 1, 'head': -1, 'phase': 'homing', 'request': 'a' * 32, 'measured': [], 'measuring': False}


def test_progress_resets_on_new_attempt():
    printer, gcode, runner = setup()
    runner.progress.head, runner.progress.phase = 3, 'docking'
    runner.nozzle_scrub.phase, runner.nozzle_scrub.head = 'ended', 2
    request = 'a' * 32
    runner.cmd_run(Command('M400', SESSION=runner.session, REQUEST=request, SEQUENCE='0', TICKET='1'))
    assert runner.progress.get_status() == {'protocol': 1, 'head': -1, 'phase': 'idle', 'request': request, 'measured': [], 'measuring': False}
    assert runner.nozzle_scrub.get_status()['phase'] == 'idle'


def test_progress_resets_on_failure():
    printer, gcode, runner = setup()
    runner.progress.head, runner.progress.phase = 1, 'position'
    gcode.fail_on = 'G28'
    with pytest.raises(RuntimeError):
        wrapped(runner, 'G28')
    assert runner.progress.get_status()['phase'] == 'idle'


def test_progress_resets_on_save():
    printer, gcode, runner = setup()
    runner.progress.head, runner.progress.phase = 1, 'docking'
    runner.progress.idle()
    assert runner.progress.get_status() == {'protocol': 1, 'head': -1, 'phase': 'idle', 'request': '', 'measured': [], 'measuring': False}


def test_successful_bound_save_leaves_progress_idle(machine):  # noqa: F811
    p, runner, path, expected = machine
    writer = p.on_run
    def run(command):
        if command == 'RAPID_MODE T=2':
            runner.progress.cmd_phase(Command('', HEAD='2', PHASE='height'))
        writer(command)
    p.on_run = run
    stage(runner, 'G28', 0)
    stage(runner, 'RAPID_MODE T=2', 1)
    stage(runner, 'PARK_CURRENT_TOOL', 2)
    assert runner.progress.get_status() == {'protocol': 1, 'head': 2, 'phase': 'docking', 'request': 'a' * 32, 'measured': [2], 'measuring': False}
    stage(runner, 'SAVE_CONFIG', 3)
    assert runner.attempt_result['state'] == 'saved'
    assert runner.progress.get_status() == {'protocol': 1, 'head': -1, 'phase': 'idle', 'request': 'a' * 32, 'measured': [2], 'measuring': False}


def measure(runner, head, sequence):
    bound(runner, 'RAPID_MODE T=%d' % head, 'a', sequence)


def test_measured_lists_heads_whose_rapid_mode_completed():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    measure(runner, 2, 1)
    measure(runner, 0, 2)
    assert runner.progress.get_status()['measured'] == [0, 2]
    gcode.fail_on = 'RAPID_MODE T=1'
    with pytest.raises(RuntimeError):
        measure(runner, 1, 3)
    assert runner.progress.get_status()['measured'] == [0, 2]


def test_remeasuring_a_head_removes_it_until_it_completes():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    measure(runner, 1, 1)
    measure(runner, 3, 2)
    assert runner.progress.get_status()['measured'] == [1, 3]
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append(runner.progress.get_status()['measured']), original(script))[1]
    measure(runner, 1, 3)
    assert seen[0] == [3]
    assert runner.progress.get_status()['measured'] == [1, 3]


def test_measuring_is_true_only_while_a_rapid_mode_runs():
    printer, gcode, runner = setup()
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append((script, runner.progress.get_status()['measuring'])), original(script))[1]
    bound(runner, 'G28', 'a', 0)
    assert runner.progress.get_status()['measuring'] is False
    measure(runner, 2, 1)
    assert runner.progress.get_status()['measuring'] is False
    gcode.fail_on = 'RAPID_MODE T=3'
    with pytest.raises(RuntimeError):
        measure(runner, 3, 2)
    assert runner.progress.get_status()['measuring'] is False
    assert seen == [('G28', False), ('RAPID_MODE T=2', True), ('RAPID_MODE T=3', True)]


def test_unbound_rapid_mode_is_not_tracked():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    wrapped(runner, 'RAPID_MODE T=1')
    assert runner.progress.get_status()['measured'] == []


def test_new_attempt_clears_measured_heads():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0)
    measure(runner, 1, 1)
    bound(runner, 'G28', 'b', 0)
    assert runner.progress.get_status()['measured'] == []
