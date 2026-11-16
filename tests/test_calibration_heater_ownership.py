"""Observational ownership: cleanup must not turn off another actor's heater."""
import pytest
from test_calibration_commands import module, Printer, Command, AttemptCommand


@pytest.fixture
def tracked():
    p = Printer()
    actor = ['calibration']
    tracker = module.CalibrationHeaterOwnership(p.objects['heaters'].heaters, lambda: actor[0])
    runner = module.CalibrationCommands(p, p)
    runner._heater_ownership = tracker
    return p, runner, tracker, actor


def test_owned_heaters_cleaned_across_stages_unrelated_target_preserved(tracked):
    p, runner, tracker, actor = tracked
    heaters = p.objects['heaters'].heaters
    heaters['extruder2'].set_temp(180)  # User preheat, outside calibration.
    def run(command):
        if command == 'G29':
            heaters['heater_bed'].set_temp(55)
            heaters['extruder'].set_temp(140)
        else:
            raise RuntimeError('later motion failed')
    p.on_run = run
    runner.cmd_run(AttemptCommand(runner, 'G29'))
    with pytest.raises(RuntimeError, match='later motion failed'):
        runner.cmd_run(AttemptCommand(runner, 'G28', sequence=1))
    assert [heaters[n].target_temp for n in ('heater_bed', 'extruder', 'extruder2')] == [0, 0, 180]


@pytest.mark.parametrize('target', [140, 170])
def test_newer_target_even_same_temperature_revokes_cleanup(tracked, target):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    def run(command):
        heater.set_temp(140)
        actor[0] = 'other-reactor-callback'
        heater.set_temp(target)
        actor[0] = 'calibration'
        raise RuntimeError('calibration failed after external write')
    p.on_run = run
    with pytest.raises(RuntimeError): runner.cmd_run(Command('G29'))
    assert heater.target_temp == target and p.off == 0


def test_pid_callback_keeps_ownership_until_external_override(tracked):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    control = object()
    with tracker.executing('attempt'):
        old = heater.set_control(control)
        assert old is not control
        heater.set_temp(220)
        actor[0] = 'sensor-callback'
        heater.alter_target(215)
        actor[0] = 'calibration'
    tracker.cool('attempt')
    assert heater.target_temp == 0
    with tracker.executing('new-attempt'):
        heater.set_control(object())
        heater.set_temp(220)
        actor[0] = 'other-command'
        heater.set_temp(220)
        actor[0] = 'sensor-callback'
        heater.alter_target(215)  # Old control cannot reclaim ownership.
        actor[0] = 'calibration'
    tracker.cool('new-attempt')
    assert heater.target_temp == 215


def test_nested_context_keeps_latest_owner_and_original_return_errors(tracked):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    with tracker.executing('outer'):
        heater.set_temp(140)
        with tracker.executing('inner'):
            heater.set_temp(160)
        tracker.cool('outer')
        assert heater.target_temp == 160
    tracker.cool('inner')
    assert heater.target_temp == 0
    heater.fail_off = True
    with pytest.raises(RuntimeError, match='heater cleanup error'):
        heater.set_temp(0)


def test_missing_tracker_logs_limitation_without_global_heater_off(caplog):
    p = Printer()
    runner = module.CalibrationCommands(p, p)
    heater = p.objects['heaters'].heaters['extruder']
    heater.set_temp(180)
    p.on_run = lambda command: (_ for _ in ()).throw(RuntimeError('motion failed'))
    with pytest.raises(RuntimeError, match='motion failed'): runner.cmd_run(Command('G28'))
    assert heater.target_temp == 180 and p.off == 0
    assert 'cleanup unavailable' in caplog.text


def test_ready_does_not_wrap_twice(tracked, monkeypatch):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    wrapped = heater.set_temp
    runner._initialize_heater_ownership()
    runner._initialize_heater_ownership()
    assert heater.set_temp is wrapped


def test_failed_setter_does_not_change_return_or_error_and_revokes_ambiguous_owner():
    class Partial:
        target_temp = 0
        control = None
        def set_temp(self, value):
            self.target_temp = value
            raise ValueError('original setter failure')
        def set_control(self, control): return 'unchanged return'
        def alter_target(self, value): return value + 1
    heater = Partial()
    tracker = module.CalibrationHeaterOwnership({'test': heater}, lambda: 1)
    assert heater.set_control(None) == 'unchanged return'
    assert heater.alter_target(2) == 3
    with pytest.raises(ValueError, match='original setter failure'):
        with tracker.executing('attempt'): heater.set_temp(100)
    assert heater.target_temp == 100


def test_reentrant_original_setter_cannot_reclaim_newer_write():
    p = Printer()
    heater = p.objects['heaters'].heaters['extruder']
    actor = ['calibration']
    base = heater.set_temp
    def reentrant(target):
        base(target)
        if target == 140:
            actor[0] = 'new-command'
            heater.set_temp(170)
            actor[0] = 'calibration'
        return 'original return'
    heater.set_temp = reentrant
    tracker = module.CalibrationHeaterOwnership({'extruder': heater}, lambda: actor[0])
    with tracker.executing('attempt'):
        assert heater.set_temp(140) == 'original return'
    tracker.cool('attempt')
    assert heater.target_temp == 170 and p.off == 0


def test_clean_setter_refusal_preserves_prior_ownership_and_partial_failure_is_tracked():
    p = Printer()
    heater = p.objects['heaters'].heaters['extruder']
    actor = ['calibration']
    base = heater.set_temp
    def fail(target):
        if target == 999:
            raise ValueError('invalid target')
        base(target)
        if target == 150:
            raise ValueError('failed after target change')
    heater.set_temp = fail
    tracker = module.CalibrationHeaterOwnership({'extruder': heater}, lambda: actor[0])
    with tracker.executing('attempt'):
        heater.set_temp(140)
    actor[0] = 'external-command'
    with pytest.raises(ValueError, match='invalid target'): heater.set_temp(999)
    tracker.cool('attempt')
    assert heater.target_temp == 0
    actor[0] = 'calibration'
    with pytest.raises(ValueError, match='after target change'):
        with tracker.executing('next-attempt'): heater.set_temp(150)
    tracker.cool('next-attempt')
    assert heater.target_temp == 0


@pytest.mark.parametrize('failure', ['missing_stage', 'later_preflight'])
def test_earlier_owned_heat_is_cleaned_on_later_stage_refusal(tracked, failure):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    p.on_run = lambda command: heater.set_temp(140)
    runner.cmd_run(AttemptCommand(runner, 'G29'))
    if failure == 'later_preflight': p.paused = True
    with pytest.raises(RuntimeError):
        runner.cmd_run(AttemptCommand(runner, 'M400', sequence=2 if failure == 'missing_stage' else 1))
    assert heater.target_temp == 0 and p.off == 1


def test_reentrant_competing_calibration_does_not_cool_running_owner(tracked):
    p, runner, tracker, actor = tracked
    heater = p.objects['heaters'].heaters['extruder']
    def running(command):
        heater.set_temp(140)
        with pytest.raises(RuntimeError, match='already running'):
            runner.cmd_run(AttemptCommand(runner, 'M400', request='b'*32))
        assert heater.target_temp == 140 and p.off == 0
    p.on_run = running
    runner.cmd_run(AttemptCommand(runner, 'G29'))
    assert heater.target_temp == 140 and p.off == 0


def test_live_probe_refuses_later_stage_and_cools_only_old_attempt(tracked):
    p, runner, tracker, actor = tracked
    heaters = p.objects['heaters'].heaters
    p.on_run = lambda command: heaters['extruder'].set_temp(140)
    runner.cmd_run(AttemptCommand(runner, 'G29'))
    heaters['extruder2'].set_temp(180)  # Another actor's target.
    runner.probe_editor.busy = lambda: True
    with pytest.raises(RuntimeError, match='probe editor'):
        runner.cmd_run(AttemptCommand(runner, 'M400', sequence=1))
    assert heaters['extruder'].target_temp == 0
    assert heaters['extruder2'].target_temp == 180
    assert runner.attempt_result['state'] == 'failed'
