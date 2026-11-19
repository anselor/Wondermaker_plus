"""Backend commands and status for the guided nozzle scrub."""
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('recovery_scrub', ROOT / 'klipper_extras/wmp_recovery.py',
                                              submodule_search_locations=None)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ConfigError(Exception):
    pass


class FakeConfig:
    error = ConfigError

    def __init__(self, **values):
        self.values = values

    def getfloat(self, name, default=None, minval=None, maxval=None, **kwargs):
        value = float(self.values.get(name, default))
        if (minval is not None and value < minval) or (maxval is not None and value > maxval):
            raise ConfigError('Option %s out of range' % name)
        return value


class Command:
    error = RuntimeError

    def __init__(self, text, **params):
        self.params = dict(params)
        self.params['HEX'] = text.encode().hex()

    def get(self, key, default=None):
        return self.params.get(key, default)

    _REQUIRED = object()

    def get_int(self, key, default=_REQUIRED, minval=None, maxval=None):
        if key not in self.params:
            if default is self._REQUIRED:
                raise RuntimeError('Missing ' + key)
            return default
        value = int(self.params[key])
        if (minval is not None and value < minval) or (maxval is not None and value > maxval):
            raise RuntimeError('%s out of range' % key)
        return value


class Heater:
    def __init__(self):
        self.target_temp, self.control = 0., object()

    def set_temp(self, target):
        self.target_temp = target

    def set_control(self, control):
        old = self.control
        self.control, self.target_temp = control, 0.
        return old

    def alter_target(self, target):
        self.target_temp = target


class Gcode:
    """Dispatches registered commands like Klipper's gcode object."""
    def __init__(self, printer):
        self.printer, self.commands, self.sent = printer, {}, []
        self.fail_on = None
        self.output_handlers = []

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = handler

    def register_output_handler(self, handler):
        self.output_handlers.append(handler)

    def run_script_from_command(self, script):
        self.sent.append(script)
        if self.fail_on and script.startswith(self.fail_on):
            raise RuntimeError('mount failed')
        match = re.fullmatch(r'SET_HEATER_TEMPERATURE HEATER=(\w+) TARGET=(\d+)', script)
        if match:
            self.printer.heaters[match.group(1)].set_temp(float(match.group(2)))
            return
        name = script.split(' ')[0]
        if name in self.commands:
            params = dict(p.split('=', 1) for p in script.split(' ')[1:] if '=' in p)
            self.commands[name](Command(script, **params))


class Light:
    def __init__(self):
        self.calls = []

    def request_attention(self, owner):
        self.calls.append(('request', owner))

    def release_attention(self, owner):
        self.calls.append(('release', owner))


class CommandError(Exception):
    """Stands for Klipper's gcode.CommandError (printer.command_error)."""


class Printer:
    command_error = CommandError

    def __init__(self):
        self.homed, self.fail, self.light = 'xyz', 0, None
        self.z_reference_valid = True
        self.heaters = {name: Heater() for name in ('extruder', 'extruder1', 'extruder2', 'extruder3')}
        self.shutdown = False
        self.objects = {
            'print_stats': SimpleNamespace(get_status=lambda _: {'state': 'standby'}),
            'pause_resume': SimpleNamespace(get_status=lambda _: {'is_paused': False}),
            'save_variables': SimpleNamespace(get_status=lambda _: {'variables': {'fail_flag': self.fail}}),
            'toolhead': SimpleNamespace(get_status=lambda _: {'homed_axes': self.homed}),
            'heaters': SimpleNamespace(heaters=self.heaters),
            'wmp_recovery': SimpleNamespace(get_status=lambda _: {'z_reference_valid': self.z_reference_valid}),
        }

    def lookup_object(self, name, default=None):
        if name == 'wmp_case_light':
            return self.light if self.light is not None else default
        return self.objects.get(name, default)

    def get_reactor(self):
        return SimpleNamespace(monotonic=lambda: 1)

    def is_shutdown(self):
        return self.shutdown

    def invoke_shutdown(self, message):
        self.shutdown = True


def setup(**config):
    printer = Printer()
    gcode = Gcode(printer)
    runner = module.CalibrationCommands(printer, gcode, FakeConfig(**config))
    runner._heater_ownership = module.CalibrationHeaterOwnership(printer.heaters, lambda: 'test-dispatch')
    return printer, gcode, runner


def wrapped(runner, command):
    runner.cmd_run(Command(command))


def test_scrub_head_sequence():
    printer, gcode, runner = setup()
    wrapped(runner, '_WMP_SCRUB_HEAD T=1')
    inner = gcode.sent[1:]
    # The bed is lowered before the pickup; XY uses the shared hot travel rate.
    assert inner == ['SET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=160',
                     'SET_GCODE_OFFSET X=0 Y=0 Z=0', 'G90', 'G1 Z100 F1800',
                     '_WMP_CALIBRATION_TOOL T=1',
                     'SET_GCODE_OFFSET X=0 Y=0 Z=0', '_WMP_CALIBRATION_CLEARANCE', 'G90', 'G1 Z100 F1800',
                     '_WMP_XY_TRAVEL X=150 Y=2 HOT=1', 'M400']
    status = runner.nozzle_scrub.get_status()
    assert status == {'protocol': 1, 'head': 1, 'phase': 'heating', 'target': 160.0, 'error': '', 'request': ''}
    assert printer.heaters['extruder1'].target_temp == 160.


def test_scrub_head_requires_homing():
    printer, gcode, runner = setup()
    printer.homed = 'xy'
    with pytest.raises(RuntimeError):
        wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    assert not any(c.startswith('SET_HEATER_TEMPERATURE') and 'TARGET=160' in c for c in gcode.sent)
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == 'The printer must be homed first.'
    assert 'homed axes' in runner.failure


def test_scrub_head_requires_a_valid_z_reference():
    printer, gcode, runner = setup()
    printer.z_reference_valid = False
    with pytest.raises(RuntimeError):
        wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    # Nothing is heated or moved.
    assert not any(c.startswith(('SET_HEATER', 'G1', '_WMP_CALIBRATION_TOOL', 'SET_GCODE_OFFSET')) for c in gcode.sent)
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == 'The printer must be homed first.'
    assert 'Z reference' in runner.failure


def test_scrub_head_refused_with_a_recorded_tool_change_fault():
    printer, gcode, runner = setup()
    printer.fail = -2
    # The calibration wrapper refuses the command before it runs.
    with pytest.raises(RuntimeError, match='fail_flag=-2'):
        wrapped(runner, '_WMP_SCRUB_HEAD T=1')
    assert gcode.sent == []
    # The scrub command itself refuses before heating or moving.
    runner.active = True
    with pytest.raises(RuntimeError, match='fail_flag=-2'):
        runner.nozzle_scrub.cmd_head(Command('_WMP_SCRUB_HEAD T=1', T='1'))
    assert gcode.sent == []
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == 'Head 2 did not mount.'


def test_scrub_commands_refused_outside_calibration():
    printer, gcode, runner = setup()
    with pytest.raises(RuntimeError):
        gcode.commands['_WMP_SCRUB_HEAD'](Command('_WMP_SCRUB_HEAD T=0', T='0'))
    assert gcode.sent == []


def test_cool_targets_only_scrub_heaters():
    printer, gcode, runner = setup()
    printer.heaters['extruder2'].set_temp(200.)
    wrapped(runner, '_WMP_SCRUB_HEAT T=0')
    wrapped(runner, '_WMP_SCRUB_HEAT T=1')
    assert printer.heaters['extruder'].target_temp == 160.
    wrapped(runner, '_WMP_SCRUB_COOL')
    assert printer.heaters['extruder'].target_temp == 0.
    assert printer.heaters['extruder1'].target_temp == 0.
    assert printer.heaters['extruder2'].target_temp == 200.
    assert not any('extruder2' in c for c in gcode.sent)


def test_cool_single_head_keeps_other_scrub_heater():
    printer, gcode, runner = setup()
    wrapped(runner, '_WMP_SCRUB_HEAT T=0')
    wrapped(runner, '_WMP_SCRUB_HEAT T=1')
    wrapped(runner, '_WMP_SCRUB_COOL T=0')
    assert printer.heaters['extruder'].target_temp == 0.
    assert printer.heaters['extruder1'].target_temp == 160.
    wrapped(runner, '_WMP_SCRUB_COOL')
    assert printer.heaters['extruder1'].target_temp == 0.


def test_end_cools_parks_and_releases_attention():
    printer, gcode, runner = setup()
    printer.light = Light()
    wrapped(runner, '_WMP_SCRUB_HEAD T=2')
    wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=1')
    wrapped(runner, '_WMP_SCRUB_END')
    assert printer.heaters['extruder2'].target_temp == 0.
    assert 'PARK_CURRENT_TOOL' in gcode.sent
    assert printer.light.calls == [('request', 'nozzle_scrub'), ('release', 'nozzle_scrub')]
    assert runner.nozzle_scrub.get_status()['phase'] == 'ended'
    assert runner.nozzle_scrub.heated == set()


def test_attention_without_case_light_is_not_an_error():
    printer, gcode, runner = setup()
    wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=1')
    printer.light = SimpleNamespace()  # no request_attention
    wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=0')
    assert not runner.failure


def test_mount_failure_latches_attempt_and_cools():
    printer, gcode, runner = setup()
    wrapped(runner, '_WMP_SCRUB_HEAT T=0')  # heater owned by this scrub and attempt
    gcode.fail_on = '_WMP_CALIBRATION_TOOL'
    with pytest.raises(RuntimeError, match='mount failed'):
        wrapped(runner, '_WMP_SCRUB_HEAD T=1')
    assert runner.failure
    assert printer.heaters['extruder'].target_temp == 0.
    assert printer.heaters['extruder1'].target_temp == 0.
    status = runner.nozzle_scrub.get_status()
    assert status == {'protocol': 1, 'head': 1, 'phase': 'failed', 'target': 160.0, 'error': 'Head 2 did not mount.', 'request': ''}
    assert 'mount failed' in runner.failure  # The latch keeps the raw text.
    assert runner.nozzle_scrub.heated == set()
    assert runner.progress.get_status()['phase'] == 'idle'


@pytest.mark.parametrize('command', ['_WMP_SCRUB_HEAD T=4', '_WMP_SCRUB_ATTENTION VALUE=2',
                                     '_WMP_SCRUB_HEAT T=9', '_WMP_SCRUB_COOL T=4'])
def test_allowlist_rejects_out_of_range(command):
    printer, gcode, runner = setup()
    with pytest.raises(RuntimeError, match='Unsupported calibration command'):
        wrapped(runner, command)
    assert gcode.sent == []


@pytest.mark.parametrize('value', [10, 19.9, 251])
def test_scrub_z_config_bounds(value):
    with pytest.raises(ConfigError):
        setup(scrub_z=value)


def test_scrub_temp_config_bound():
    with pytest.raises(ConfigError):
        setup(scrub_temp=171)


def test_config_values_used():
    printer, gcode, runner = setup(scrub_x=120, scrub_y=5, scrub_z=60, scrub_temp=150)
    wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    assert gcode.sent.count('G1 Z60 F1800') == 2
    assert '_WMP_XY_TRAVEL X=120 Y=5 HOT=1' in gcode.sent
    assert 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=150' in gcode.sent
    assert runner.nozzle_scrub.get_status()['target'] == 150.0


def bound(runner, command, request, sequence, ticket=None):
    params = dict(SESSION=runner.session, REQUEST=request * 32, SEQUENCE=str(sequence))
    if ticket is not None:
        params['TICKET'] = str(ticket)
    runner.cmd_run(Command(command, **params))


def test_new_attempt_turns_off_previous_scrub_heater():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    assert printer.heaters['extruder'].target_temp == 160.
    bound(runner, 'M400', 'b', 0)
    assert printer.heaters['extruder'].target_temp == 0.
    assert runner.nozzle_scrub.heated == set()


def test_refused_new_attempt_keeps_current_scrub_state():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    with pytest.raises(RuntimeError, match='Unsupported calibration command'):
        bound(runner, 'M112', 'b', 0)
    assert printer.heaters['extruder'].target_temp == 160.
    assert runner.nozzle_scrub.heated == {'extruder'}


def test_end_after_refused_new_attempt_cools_heater():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    with pytest.raises(RuntimeError):
        bound(runner, 'M112', 'b', 0)
    bound(runner, '_WMP_SCRUB_END', 'a', 1)
    assert printer.heaters['extruder'].target_temp == 0.
    assert runner.nozzle_scrub.get_status()['phase'] == 'ended'


def test_failure_cools_scrub_heaters_without_heater_ownership():
    printer, gcode, runner = setup()
    runner._heater_ownership = None
    wrapped(runner, '_WMP_SCRUB_HEAT T=0')
    gcode.fail_on = 'G28'
    with pytest.raises(RuntimeError):
        wrapped(runner, 'G28')
    assert printer.heaters['extruder'].target_temp == 0.
    assert runner.nozzle_scrub.heated == set()


def test_status_exposed_by_recovery_object():
    printer, gcode, _ = setup()
    printer.objects['gcode'] = gcode
    printer.register_event_handler = lambda name, handler: None
    config = FakeConfig(scrub_z=80)
    config.get_printer = lambda: printer
    status = module.BottomZ(config).get_status(0.)
    assert status['nozzle_scrub'] == {'protocol': 1, 'head': -1, 'phase': 'idle', 'target': 160.0, 'error': '', 'request': ''}
    assert status['calibration_progress'] == {'protocol': 1, 'head': -1, 'phase': 'idle', 'request': '',
                                             'measured': [], 'measuring': False}
    assert status['nozzle_touch'] == {'protocol': 2, 'request': '', 'heads': [], 'flagged': [], 'restore': 'none'}


# Failure text for the screen: one plain sentence, no command names. The raw
# error stays in the calibration latch and the Klipper log.
@pytest.mark.parametrize('fail_on, command, sentence', [
    ('_WMP_CALIBRATION_TOOL', '_WMP_SCRUB_HEAD T=1', 'Head 2 did not mount.'),
    ('_WMP_CALIBRATION_CLEARANCE', '_WMP_SCRUB_HEAD T=2', 'Head 3 could not be moved into position.'),
    ('SET_GCODE_OFFSET', '_WMP_SCRUB_HEAD T=0', 'Head 1 could not be moved into position.'),
    ('G1 ', '_WMP_SCRUB_HEAD T=3', 'Head 4 could not be moved into position.'),
    ('_WMP_XY_TRAVEL', '_WMP_SCRUB_HEAD T=3', 'Head 4 could not be moved into position.'),
    ('M400', '_WMP_SCRUB_HEAD T=3', 'Head 4 could not be moved into position.'),
    ('SET_HEATER_TEMPERATURE HEATER=extruder1 TARGET=160', '_WMP_SCRUB_HEAD T=1', 'Head 2 could not be heated.'),
    ('SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=160', '_WMP_SCRUB_HEAT T=2', 'Head 3 could not be heated.'),
])
def test_failure_sentences(fail_on, command, sentence, caplog):
    printer, gcode, runner = setup()
    if command.startswith('_WMP_SCRUB_HEAT'):
        wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    gcode.fail_on = fail_on
    with caplog.at_level('WARNING'), pytest.raises(RuntimeError, match='mount failed'):
        wrapped(runner, command)
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == sentence
    assert 'mount failed' in runner.failure and 'mount failed' in caplog.text
    assert all(heater.target_temp == 0. for heater in printer.heaters.values())


def test_end_park_failure_sentence():
    printer, gcode, runner = setup()
    printer.light = Light()
    wrapped(runner, '_WMP_SCRUB_HEAD T=1')
    wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=1')
    gcode.fail_on = 'PARK_CURRENT_TOOL'
    with pytest.raises(RuntimeError, match='mount failed'):
        wrapped(runner, '_WMP_SCRUB_END')
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == 'The head could not be returned to its dock.'
    assert 'mount failed' in runner.failure
    assert printer.heaters['extruder1'].target_temp == 0.
    assert printer.light.calls[-1] == ('release', 'nozzle_scrub')


def test_soft_tool_failure_after_head_reports_mount_sentence():
    # The tool macros can set fail_flag without raising.
    printer, gcode, runner = setup()
    original = gcode.run_script_from_command
    def run(script):
        original(script)
        if script.startswith('_WMP_CALIBRATION_TOOL'):
            printer.fail = -2
    gcode.run_script_from_command = run
    with pytest.raises(RuntimeError, match='fail_flag'):
        wrapped(runner, '_WMP_SCRUB_HEAD T=1')
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == 'Head 2 did not mount.'
    # Nothing moved after the failed mount.
    after = gcode.sent[gcode.sent.index('_WMP_CALIBRATION_TOOL T=1') + 1:]
    assert not any(c.startswith(('G1 ', '_WMP_XY_TRAVEL')) or c == '_WMP_CALIBRATION_CLEARANCE' for c in after)
    assert printer.heaters['extruder1'].target_temp == 0.


def test_failure_of_another_command_carries_no_raw_text():
    printer, gcode, runner = setup()
    wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    gcode.fail_on = 'G28'
    with pytest.raises(RuntimeError, match='mount failed'):
        wrapped(runner, 'G28')
    status = runner.nozzle_scrub.get_status()
    assert status['phase'] == 'failed' and status['error'] == ''
    assert 'mount failed' in runner.failure


def test_failure_releases_attention():
    printer, gcode, runner = setup()
    printer.light = Light()
    wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=1')
    gcode.fail_on = '_WMP_CALIBRATION_TOOL'
    with pytest.raises(RuntimeError):
        wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    assert printer.light.calls == [('request', 'nozzle_scrub'), ('release', 'nozzle_scrub')]
    # The failed attempt refuses the release command itself.
    with pytest.raises(RuntimeError, match='Calibration stopped'):
        wrapped(runner, '_WMP_SCRUB_ATTENTION VALUE=0')


def test_new_attempt_releases_attention():
    printer, gcode, runner = setup()
    printer.light = Light()
    bound(runner, '_WMP_SCRUB_ATTENTION VALUE=1', 'a', 0)
    assert printer.light.calls[-1] == ('request', 'nozzle_scrub')
    bound(runner, 'M400', 'b', 0)
    assert printer.light.calls[-1] == ('release', 'nozzle_scrub')


def test_attention_release_failure_does_not_mask_the_failure():
    printer, gcode, runner = setup()
    printer.light = SimpleNamespace(request_attention=lambda owner: None,
                                    release_attention=lambda owner: (_ for _ in ()).throw(OSError('gpio')))
    gcode.fail_on = '_WMP_CALIBRATION_TOOL'
    with pytest.raises(RuntimeError, match='mount failed'):
        wrapped(runner, '_WMP_SCRUB_HEAD T=0')
    assert printer.heaters['extruder'].target_temp == 0. and 'mount failed' in runner.failure


def published_requests(runner):
    return runner.nozzle_scrub.get_status()['request'], runner.progress.get_status()['request']


def test_status_request_is_empty_before_any_attempt():
    printer, gcode, runner = setup()
    assert published_requests(runner) == ('', '')
    wrapped(runner, 'G28')  # A command without an attempt binding publishes no request.
    assert published_requests(runner) == ('', '')


def test_status_request_switches_when_the_attempt_is_admitted():
    printer, gcode, runner = setup()
    seen = []
    original = gcode.run_script_from_command
    gcode.run_script_from_command = lambda script: (seen.append(published_requests(runner)), original(script))[1]
    bound(runner, 'G28', 'a', 0)
    # Published before the attempt's first command runs.
    assert seen[0] == ('a' * 32, 'a' * 32)
    bound(runner, '_WMP_SCRUB_HEAD T=0', 'a', 1)
    assert published_requests(runner) == ('a' * 32, 'a' * 32)
    gcode.fail_on = '_WMP_CALIBRATION_TOOL'
    with pytest.raises(RuntimeError):
        bound(runner, '_WMP_SCRUB_HEAD T=1', 'a', 2)
    gcode.fail_on = None
    # The failed attempt keeps its status and its request.
    assert runner.nozzle_scrub.get_status()['phase'] == 'failed'
    assert published_requests(runner) == ('a' * 32, 'a' * 32)
    # A refused new attempt changes nothing.
    with pytest.raises(RuntimeError, match='Unsupported calibration command'):
        bound(runner, 'M112', 'b', 0)
    assert published_requests(runner) == ('a' * 32, 'a' * 32)
    assert runner.nozzle_scrub.get_status()['error'] == 'Head 2 did not mount.'
    del seen[:]
    bound(runner, 'G28', 'c', 0)
    assert seen[0] == ('c' * 32, 'c' * 32)
    assert runner.nozzle_scrub.get_status()['phase'] == 'idle'
    assert runner.nozzle_scrub.get_status()['error'] == ''
    assert runner.failure == ''


def test_status_request_with_ticket_attempts():
    printer, gcode, runner = setup()
    bound(runner, 'G28', 'a', 0, ticket=1)
    assert published_requests(runner) == ('a' * 32, 'a' * 32)
    bound(runner, 'G28', 'b', 0, ticket=2)
    assert published_requests(runner) == ('b' * 32, 'b' * 32)


def test_reset_cooldown_failure_is_a_command_error():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    gcode.fail_on = 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0'
    # Klipper shuts down on any exception that is not its command error.
    with pytest.raises(CommandError, match='Previous scrub heater cool-down failed'):
        bound(runner, 'M400', 'b', 0)
    assert not printer.shutdown
    assert runner.attempt_status()['request'] == 'b' * 32
    assert runner.attempt_status()['state'] == 'refused'
    assert not runner.active
    with pytest.raises(RuntimeError, match='already stopped'):
        bound(runner, 'M400', 'b', 1)


def test_reset_cooldown_failure_switches_both_published_requests():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    assert published_requests(runner) == ('a' * 32, 'a' * 32)
    gcode.fail_on = 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0'
    with pytest.raises(CommandError, match='Previous scrub heater cool-down failed'):
        bound(runner, 'M400', 'b', 0)
    # Scrub status and calibration progress name the same attempt.
    assert published_requests(runner) == ('b' * 32, 'b' * 32)
    assert runner.progress.get_status()['phase'] == 'idle'


def test_reset_keeps_heater_whose_cooldown_failed_for_the_next_attempt():
    printer, gcode, runner = setup()
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    bound(runner, '_WMP_SCRUB_HEAT T=1', 'a', 1)
    gcode.fail_on = 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0'
    with pytest.raises(CommandError, match='Previous scrub heater cool-down failed'):
        bound(runner, 'M400', 'b', 0)
    # The heater that was turned off is forgotten; the other is tried again.
    assert runner.nozzle_scrub.heated == {'extruder'}
    assert printer.heaters['extruder'].target_temp == 160.
    assert printer.heaters['extruder1'].target_temp == 0.
    gcode.fail_on = None
    bound(runner, 'M400', 'c', 0)
    assert printer.heaters['extruder'].target_temp == 0.
    assert runner.nozzle_scrub.heated == set()


def test_failure_keeps_heater_whose_cooldown_failed_for_a_later_reset():
    printer, gcode, runner = setup()
    runner._heater_ownership = None
    bound(runner, '_WMP_SCRUB_HEAT T=0', 'a', 0)
    bound(runner, '_WMP_SCRUB_HEAT T=1', 'a', 1)
    gcode.fail_on = 'SET_HEATER_TEMPERATURE HEATER=extruder TARGET=0'
    with pytest.raises(RuntimeError, match='out of order'):
        bound(runner, 'M400', 'a', 5)
    assert runner.attempt_status()['state'] == 'failed'
    assert runner.nozzle_scrub.heated == {'extruder'}
    assert printer.heaters['extruder'].target_temp == 160.
    assert printer.heaters['extruder1'].target_temp == 0.
    gcode.fail_on = None
    bound(runner, 'M400', 'b', 0)
    assert printer.heaters['extruder'].target_temp == 0.
    assert runner.nozzle_scrub.heated == set()


def connected_recovery(monkeypatch, install):
    """BottomZ with its klippy:connect handler run; install replaces wmp_tool_probe.install."""
    printer, gcode, _ = setup()
    printer.objects['gcode'] = gcode
    handlers = {}
    printer.register_event_handler = lambda name, handler: handlers.setdefault(name, handler)
    callbacks = []
    enable = SimpleNamespace(register_state_callback=callbacks.append)
    printer.objects['stepper_enable'] = SimpleNamespace(lookup_enable=lambda name: enable)
    monkeypatch.setattr(module.wmp_tool_probe, 'install', install)
    config = FakeConfig()
    config.get_printer = lambda: printer
    recovery = module.BottomZ(config)
    handlers['klippy:connect']()
    return printer, recovery, callbacks


def test_connect_installs_the_tool_probe_helper(monkeypatch):
    calls = []
    printer, recovery, callbacks = connected_recovery(monkeypatch, lambda printer: calls.append(printer) or True)
    assert calls == [printer]
    assert callbacks == [recovery._motor_state]


def test_tool_probe_helper_failure_never_reaches_connect(monkeypatch):
    def broken(printer):
        raise RuntimeError('lookup failed')
    printer, recovery, callbacks = connected_recovery(monkeypatch, broken)
    assert callbacks == [recovery._motor_state]


def test_tool_probe_helper_without_vendor_probe_is_not_installed(monkeypatch):
    printer, recovery, callbacks = connected_recovery(monkeypatch, module.wmp_tool_probe.install)
    assert printer.lookup_object('tools_calibrate') is None
    assert module.wmp_tool_probe.install(printer) is False
    assert callbacks == [recovery._motor_state]
