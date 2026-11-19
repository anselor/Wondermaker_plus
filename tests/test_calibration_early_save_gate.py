"""The early save through the standalone SAVE_CONFIG wrapper and restart gate.

The real ConfigurationSave of klipper_extras/wmp_config_save.py is wired to a
real CalibrationCommands: the wrapper registered over SAVE_CONFIG and the
gcode:request_restart handler both run its _restart_requested.
"""
from types import SimpleNamespace as NS
import pytest
from test_calibration_commands import Command
from test_calibration_save_result import SaveCommand, machine  # noqa: F401 (fixture)
from test_calibration_early_save import stage, stop_offset_stage
import wmp_config_save


class GateError(Exception):
    pass


def install_gate(p, runner):
    """Standalone printer (no openACE, no AFC). Returns the component and the
    console entry points for SAVE_CONFIG and a restart request."""
    p.objects['virtual_sdcard'] = NS(current_file=None, is_active=lambda: False,
                                     is_cmd_from_sd=lambda: False)
    # As wmp_recovery.BottomZ.get_status publishes it.
    p.objects['wmp_recovery'] = NS(calibration=runner, get_status=lambda now: {
        'calibration_active': runner.active or runner.probe_editor.busy()})
    p.command_error = GateError
    handlers = {}
    writer = p.on_run
    handlers['SAVE_CONFIG'] = lambda gcmd: writer('SAVE_CONFIG')
    def register(name, handler, **kwargs):
        previous = handlers.get(name)
        if handler is None:
            handlers.pop(name, None)
        else:
            handlers[name] = handler
        return previous
    p.objects['gcode'] = NS(register_command=register)
    material = NS(printer=p, _print_cancel_active=lambda: False, _recovery_attempt_active=lambda: False,
                  _material_operation_active=lambda name: False, filament_operation={}, toolhead_operation={},
                  _pending_recovery_submission=None, _profile_import_busy=False, profile_import={})
    component = wmp_config_save.ConfigurationSave(material)
    material._restart_requested = component._restart_requested
    p.objects['wm_material'] = material
    component._config_save_routes_ready()
    console_save = lambda: handlers['SAVE_CONFIG'](NS(error=GateError))
    restart = p.request_restart
    def request_restart(mode):
        component._restart_requested(0.)  # the gcode:request_restart event
        restart(mode)
    p.request_restart = request_restart
    def run(command):
        if command == 'SAVE_CONFIG':
            console_save()
        else:
            writer(command)
    p.on_run = run
    return component, console_save, lambda: p.request_restart('firmware_restart')


def test_ordinary_save_passes_the_gate(machine):
    p, runner, path, expected = machine
    install_gate(p, runner)
    stage(runner, 'G28', 0)
    stage(runner, 'G29', 1)
    stage(runner, 'SAVE_CONFIG', 2)
    assert runner.save_result['state'] == 'saved' and p.restarts == ['firmware_restart']
    assert runner.attempt_result['state'] == 'saved' and not runner.failure
    assert not runner.save_admitted()


def test_unbound_and_legacy_bound_saves_pass_the_gate(machine):
    p, runner, path, expected = machine
    install_gate(p, runner)
    runner.cmd_run(Command('SAVE_CONFIG'))
    runner.cmd_run(SaveCommand(runner))
    assert p.restarts == ['firmware_restart'] * 2 and runner.save_result['state'] == 'saved'


@pytest.mark.parametrize('ticket', [None, 1])
def test_early_save_after_scrub_failure_is_written_and_restarts_once(machine, ticket):
    p, runner, path, expected = machine
    install_gate(p, runner)
    sequence = stop_offset_stage(machine, ticket=ticket)
    assert runner.attempt_status()['early_save_available'] is True
    stage(runner, 'SAVE_CONFIG', sequence, ticket)
    assert p.sent[-1] == 'SAVE_CONFIG' and p.restarts == ['firmware_restart']
    assert runner.save_result['state'] == 'saved' and runner.save_result['request'] == 'a' * 32
    assert path.read_text().count('pid_kp') == 1 and '"30"' in path.read_text()
    # The attempt stays failed and the latch stays set.
    assert runner.attempt_result['state'] == 'failed' and runner.failure
    assert not runner.save_admitted()


def test_early_save_after_rapid_mode_failure_is_written_and_restarts_once(machine):
    p, runner, path, expected = machine
    install_gate(p, runner)
    sequence = stop_offset_stage(machine, before=('RAPID_MODE T=0',), failing='RAPID_MODE T=1', flag=-2)
    stage(runner, 'SAVE_CONFIG', sequence)
    assert p.sent[-1] == 'SAVE_CONFIG' and p.restarts == ['firmware_restart']
    assert runner.save_result['state'] == 'saved' and runner.failure


def test_second_early_save_is_refused(machine):
    p, runner, path, expected = machine
    install_gate(p, runner)
    sequence = stop_offset_stage(machine)
    stage(runner, 'SAVE_CONFIG', sequence)
    for again in (sequence, sequence + 1):
        with pytest.raises(RuntimeError, match='already stopped'):
            stage(runner, 'SAVE_CONFIG', again)
    assert p.sent.count('SAVE_CONFIG') == 1 and p.restarts == ['firmware_restart']


def test_gate_admits_the_early_save_only_while_it_runs(machine):
    p, runner, path, expected = machine
    component, console_save, restart = install_gate(p, runner)
    sequence = stop_offset_stage(machine)
    stage(runner, 'SAVE_CONFIG', sequence)
    # The same latched state without this command's admission is refused.
    runner.active = runner._saving = True
    try:
        assert runner.failure and not runner.save_admitted()
        with pytest.raises(GateError, match='Finish or stop calibration'):
            component._restart_requested(None)
        with pytest.raises(GateError, match='Finish or stop calibration'):
            console_save()
        with pytest.raises(GateError, match='Finish or stop calibration'):
            restart()
    finally:
        runner.active = runner._saving = False
    assert p.restarts == ['firmware_restart']


@pytest.mark.parametrize('failed_before', [False, True])
def test_console_save_and_restart_are_refused_while_a_stage_runs(machine, failed_before):
    """failed_before: the running stage belongs to a new attempt started after
    a failed one whose early save was never requested."""
    p, runner, path, expected = machine
    component, console_save, restart = install_gate(p, runner)
    request = 'a' * 32
    if failed_before:
        stop_offset_stage(machine)
        request = 'c' * 32
    refusals = []
    stages = p.on_run
    def run(command):
        if command == 'G29':
            for entry in (console_save, restart):
                with pytest.raises(GateError, match='Finish or stop calibration'):
                    entry()
                refusals.append(entry)
        stages(command)
    p.on_run = run
    from test_calibration_commands import AttemptCommand
    runner.cmd_run(AttemptCommand(runner, 'G28', request=request, sequence=0))
    runner.cmd_run(AttemptCommand(runner, 'G29', request=request, sequence=1))
    assert len(refusals) == 2 and p.restarts == [] and 'SAVE_CONFIG' not in p.sent


def test_refused_early_save_does_not_leave_the_admission_set(machine):
    p, runner, path, expected = machine
    component, console_save, restart = install_gate(p, runner)
    sequence = stop_offset_stage(machine)
    runner.probe_editor.busy = lambda: True
    with pytest.raises(RuntimeError, match='probe editor'):
        stage(runner, 'SAVE_CONFIG', sequence)
    runner.probe_editor.busy = lambda: False
    assert 'SAVE_CONFIG' not in p.sent and p.restarts == []
    runner.active = runner._saving = True
    try:
        assert not runner.save_admitted()
        with pytest.raises(GateError, match='Finish or stop calibration'):
            component._restart_requested(None)
    finally:
        runner.active = runner._saving = False


def test_failed_early_save_clears_the_admission(machine):
    p, runner, path, expected = machine
    component, console_save, restart = install_gate(p, runner)
    sequence = stop_offset_stage(machine)
    def refuse(mode):
        raise RuntimeError('writer failed')
    p.request_restart = refuse
    with pytest.raises(RuntimeError, match='writer failed'):
        stage(runner, 'SAVE_CONFIG', sequence)
    assert runner.save_result['state'] == 'unconfirmed' and not runner.save_admitted()
    runner.active = runner._saving = True
    try:
        with pytest.raises(GateError, match='Finish or stop calibration'):
            component._restart_requested(None)
    finally:
        runner.active = runner._saving = False
