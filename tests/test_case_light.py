"""Saved light choices are independent of screen/print-driven illumination."""
import ast
import importlib.util
import os
import re
from pathlib import Path
from types import SimpleNamespace as NS

import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wmp_case_light', ROOT / 'klipper_extras/wmp_case_light.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Command:
    error = ValueError

    def __init__(self, **params):
        self.params = params

    def get_float(self, name, minval, maxval):
        try:
            value = float(self.params[name])
        except (KeyError, ValueError):
            raise self.error('Missing or invalid ' + name)
        if value < minval or value > maxval:
            raise self.error('Out of range ' + name)
        return value

    def get(self, name):
        return self.params[name]

    def get_int(self, name, minval, maxval):
        try:
            value = int(self.params[name])
        except (KeyError, ValueError):
            raise self.error('Missing or invalid ' + name)
        if value < minval or value > maxval:
            raise self.error('Out of range ' + name)
        return value


class Reactor:
    NEVER = float('inf')
    NOW = 0.

    def __init__(self):
        self.now = 100.
        self.timers = []

    def monotonic(self):
        return self.now

    def register_timer(self, callback, when=NEVER):
        timer = {'callback': callback, 'when': when}
        self.timers.append(timer)
        return timer

    def update_timer(self, timer, when):
        timer['when'] = when

    def advance(self, when):
        self.now = when
        for timer in self.timers:
            if timer['when'] <= when:
                timer['when'] = timer['callback'](when)


class Saver:
    def __init__(self):
        self.variables = {'other_printer_setting': 42}
        self.writes = []

    def get_status(self, now):
        return {'variables': self.variables}

    def cmd_SAVE_VARIABLE(self, command):
        name, value = command.get('VARIABLE'), ast.literal_eval(command.get('VALUE'))
        self.variables[name] = value
        self.writes.append((name, value))


@pytest.fixture
def light(tmp_path, monkeypatch):
    paths = {name: tmp_path / name for name in ('gpio', 'backlight', 'screen.ini')}
    paths['gpio'].write_text('1\n')
    paths['backlight'].write_text('100\n')
    paths['screen.ini'].write_text('[screen]\nscreen_off_delay=300000\n')
    for name, target in [('gpio', 'LIGHT_VALUE_PATH'), ('backlight', 'BACKLIGHT_PATH'),
                         ('screen.ini', 'SCREEN_CONFIG_PATH')]:
        monkeypatch.setattr(module, target, str(paths[name]))
    mux, commands, events, endpoints = {}, {}, {}, {}
    gcode = NS(
        register_mux_command=lambda cmd, key, value, cb, **kw: mux.setdefault((cmd, key, value), cb),
        register_command=lambda name, cb, **kw: commands.setdefault(name, cb),
        create_gcode_command=lambda name, line, params: Command(**params))
    reactor, saver, state = Reactor(), Saver(), {'state': 'standby'}
    objects = {'gcode': gcode, 'save_variables': saver,
               'webhooks': NS(register_endpoint=lambda name, cb: endpoints.setdefault(name, cb)),
               'print_stats': NS(get_status=lambda now: state)}
    def lookup(name, default=None):
        assert name in objects, 'Unexpected hardware dependency: ' + name
        return objects.get(name, default)
    printer = NS(lookup_object=lookup, get_reactor=lambda: reactor, command_error=ValueError,
                 register_event_handler=lambda name, cb: events.setdefault(name, cb))
    config = NS(get_printer=lambda: printer)
    extra = module.load_config(config)
    def tick(at=None):
        if reactor.timers[0]['when'] == reactor.NEVER:
            events['klippy:ready']()
        reactor.advance(reactor.now + 0.5 if at is None else at)
    return NS(extra=extra, config=config, gpio=paths['gpio'], backlight=paths['backlight'],
              ini=paths['screen.ini'], state=state, saver=saver, reactor=reactor,
              mux=mux, commands=commands, tick=tick,
              endpoints=endpoints,
              value=lambda: int(paths['gpio'].read_text().strip()))


def test_load_leaves_gpio_untouched_until_ready(light):
    assert light.gpio.read_text() == '1\n'
    assert not light.saver.writes
    assert light.extra.timer['when'] == light.reactor.NEVER
    light.tick()
    assert light.extra.enabled is True
    assert light.saver.writes == [('wmp_case_light_enabled', True)]
    light.tick()
    assert len(light.saver.writes) == 1


@pytest.mark.parametrize('value', ['0', '1', '0.0', '1.0'])
def test_set_pin_saves_preference_through_klipper(light, value):
    light.mux['SET_PIN', 'PIN', 'case_light'](Command(VALUE=value))
    assert light.value() == int(float(value))
    assert light.saver.variables['wmp_case_light_enabled'] is bool(float(value))
    assert light.saver.variables['other_printer_setting'] == 42


@pytest.mark.parametrize('value', [None, '-1', '2', '0.5', 'nan', 'inf', 'wrong'])
def test_invalid_values_never_write(light, value):
    with pytest.raises(ValueError):
        light.extra.cmd_SET_PIN(Command(**({} if value is None else {'VALUE': value})))
    assert not light.saver.writes
    assert light.gpio.read_text() == '1\n'


def test_screen_sleep_and_wake_preserve_preference(light):
    light.tick()
    light.backlight.write_text('0\n')
    light.tick()
    assert light.value() == 0
    assert light.extra.enabled is True
    assert len(light.saver.writes) == 1
    light.backlight.write_text('80\n')
    light.tick()
    assert light.value() == 1
    assert len(light.saver.writes) == 1


@pytest.mark.parametrize('state', ['printing', 'paused'])
def test_active_or_paused_print_keeps_light_on_with_screen_off(light, state):
    light.backlight.write_text('0\n')
    light.state['state'] = state
    light.tick()
    assert light.value() == 1
    light.tick(10000)
    assert light.value() == 1


@pytest.mark.parametrize('terminal', ['complete', 'cancelled', 'error'])
def test_print_stops_then_same_screen_delay_expires(light, terminal):
    light.backlight.write_text('0\n')
    light.state['state'] = 'printing'
    light.tick(100)
    light.state['state'] = terminal
    light.tick(200)
    light.tick(499.5)
    assert light.value() == 1
    light.tick(500)
    assert light.value() == 0
    assert light.extra.enabled is True


def test_screen_on_keeps_light_on_beyond_print_grace(light):
    light.state['state'] = 'printing'
    light.tick(100)
    light.state['state'] = 'complete'
    light.tick(200)
    light.tick(1000)
    assert light.value() == 1
    light.backlight.write_text('0')
    light.tick()
    assert light.value() == 0


def test_new_print_clears_old_grace(light):
    light.backlight.write_text('0')
    light.state['state'] = 'printing'
    light.tick(100)
    light.state['state'] = 'complete'
    light.tick(200)
    light.state['state'] = 'printing'
    light.extra.cmd_print_start(Command())
    light.tick(400)
    assert light.extra.finished_at is None
    light.tick(600)
    assert light.value() == 1
    light.state['state'] = 'complete'
    light.extra.cmd_print_end(Command())
    light.tick(899.5)
    assert light.value() == 1
    light.tick(900)
    assert light.value() == 0


@pytest.mark.parametrize('state', ['standby', 'printing', 'paused'])
def test_off_preference_wins_over_wake_and_print_start(light, state):
    light.extra.cmd_SET_PIN(Command(VALUE='0'))
    light.state['state'] = state
    light.extra.cmd_print_start(Command())
    light.tick()
    light.backlight.write_text('0')
    light.tick()
    light.backlight.write_text('100')
    light.tick()
    assert light.value() == 0
    assert light.saver.variables['wmp_case_light_enabled'] is False


def test_toggle_changes_saved_preference_even_when_physical_light_is_off(light):
    light.tick()
    light.backlight.write_text('0')
    light.tick()
    assert light.value() == 0 and light.extra.enabled is True
    light.extra.cmd_toggle(Command())
    assert light.extra.enabled is False  # toggle preference, not actual GPIO
    light.backlight.write_text('100')
    light.tick()
    assert light.value() == 0
    light.extra.cmd_toggle(Command())
    assert light.value() == 1 and light.extra.enabled is True


def test_saved_preference_survives_reload(light):
    light.extra.cmd_SET_PIN(Command(VALUE='0'))
    fresh = module.load_config(light.config)
    fresh._tick(light.reactor.now)
    assert fresh.enabled is False and light.value() == 0
    assert len(light.saver.writes) == 2  # initial adoption and explicit Off


def test_native_save_variables_preserves_other_settings_and_reloads(light, tmp_path, monkeypatch):
    vendor = Path(os.environ.get('WMP_VENDOR_ROOT', str(ROOT / 'analysis')))
    path = vendor / 'fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/save_variables.py'
    if not path.exists():
        pytest.skip('local stock save_variables source required')
    spec = importlib.util.spec_from_file_location('stock_save_variables', path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    saved = tmp_path / 'saved_variables.cfg'
    saved.write_text('[Variables]\nother_printer_setting = 42\n')
    printer = light.config.get_printer()
    config = NS(get_printer=lambda: printer, get=lambda name: str(saved), error=ValueError)
    saver = native.load_config(config)
    original_lookup = printer.lookup_object
    monkeypatch.setattr(printer, 'lookup_object',
                        lambda name, *args: saver if name == 'save_variables' else original_lookup(name, *args))
    stock_ini = light.ini.read_bytes()
    light.extra.cmd_SET_PIN(Command(VALUE='0'))
    reloaded = native.load_config(config)
    assert reloaded.get_status(0)['variables'] == {
        'other_printer_setting': 42, 'wmp_case_light_enabled': False}
    assert light.ini.read_bytes() == stock_ini


def test_screen_choices_use_same_command_and_save_even_when_gpio_matches(light):
    light.tick()
    light.backlight.write_text('0')
    light.tick()
    assert light.value() == 0
    # The screen bridge must send an explicit OFF even though GPIO is already 0.
    light.extra.cmd_SET_PIN(Command(VALUE='0'))
    light.backlight.write_text('100')
    light.tick()
    assert light.value() == 0 and light.extra.enabled is False


def test_direct_screen_api_saves_without_gcode_dispatch(light):
    results = []
    request = NS(get_int=lambda name: 0, error=ValueError, send=results.append)
    light.endpoints['wmp_case_light/set'](request)
    assert light.saver.variables['wmp_case_light_enabled'] is False
    assert results == [{'enabled': False, 'value': 0.}]
    bad = NS(get_int=lambda name: 2, error=ValueError, send=results.append)
    with pytest.raises(ValueError, match='enabled must be'):
        light.endpoints['wmp_case_light/set'](bad)


def test_timeout_changes_use_milliseconds_and_current_screen_setting(light):
    light.state['state'] = 'printing'
    light.backlight.write_text('0')
    light.tick(100)
    light.state['state'] = 'complete'
    light.tick(200)
    light.ini.write_text('[screen]\nscreen_off_delay=2500\n')
    light.tick(202)
    assert light.value() == 1
    light.tick(202.5)
    assert light.value() == 0


@pytest.mark.parametrize('failure', ['gpio', 'backlight', 'screen-config', 'save'])
def test_failures_do_not_crash_polling_or_recreate_missing_files(light, failure, caplog):
    light.tick()
    if failure == 'gpio':
        light.gpio.unlink()
    elif failure == 'backlight':
        light.backlight.write_text('bad')
    elif failure == 'screen-config':
        light.backlight.write_text('0')
        light.extra.finished_at = light.reactor.now
        light.ini.write_text('[screen]\nscreen_off_delay=nan\n')
    else:
        light.saver.variables.pop('wmp_case_light_enabled')
        def fail(cmd):
            raise ValueError('Unable to save variable')
        light.saver.cmd_SAVE_VARIABLE = fail
    light.tick()
    assert 'Case-light policy unavailable' in caplog.text
    assert light.extra.last_error
    assert light.extra.timer['when'] != light.reactor.NEVER
    if failure == 'gpio':
        assert not light.gpio.exists()


def test_fluidd_macros_and_print_hooks(light):
    source = (ROOT / 'config/live/case_light.cfg').read_text()
    env = jinja2.Environment('{%', '%}', '{', '}')
    for section in source.split('[gcode_macro ')[1:]:
        name, body = section.split(']', 1)
        script = env.from_string(body.split('gcode:', 1)[1]).render()
        lines = [line.strip() for line in script.splitlines()
                 if line.strip() and not line.lstrip().startswith('#')]
        assert len(lines) == 1
        if name == 'CASE_LIGHT_TOGGLE':
            light.commands[lines[0]](Command())
        else:
            command, pin, value = lines[0].split()
            light.mux[command, 'PIN', pin.split('=')[1]](Command(VALUE=value.split('=')[1]))
    source = (ROOT / 'config/live/macros.cfg').read_text()
    for name in ('START_PRINT', 'PRINT_END', 'CANCEL_PRINT'):
        section = re.search(r'(?ms)^\[gcode_macro %s\].*?(?=^\[|\Z)' % name, source).group()
        commands = [line.split('#', 1)[0].strip() for line in section.split('gcode:', 1)[1].splitlines()
                    if line.split('#', 1)[0].strip()]
        if name == 'START_PRINT':
            assert commands[0] == '_WMP_CASE_LIGHT_PRINT_START'
        else:
            assert commands[-1] == '_WMP_CASE_LIGHT_PRINT_END'


@pytest.mark.parametrize('enabled', [True, False])
def test_wake_applies_preference_before_backlight_without_saving_or_latching(light, enabled):
    light.saver.variables['wmp_case_light_enabled'] = enabled
    light.backlight.write_text('0')
    light.tick()
    assert light.value() == 0
    results = []
    request = NS(error=ValueError, send=results.append)
    light.endpoints['wmp_case_light/wake'](request)
    assert light.value() == int(enabled)
    assert results == [{'enabled': enabled}]
    assert light.backlight.read_text() == '0'
    assert not light.saver.writes
    # A failed screen wake must not permanently override the real backlight.
    light.tick()
    assert light.value() == 0


def test_screen_status_reports_preference_while_physical_light_sleeps(light):
    light.saver.variables['wmp_case_light_enabled'] = True
    light.backlight.write_text('0')
    light.tick()
    results = []
    light.endpoints['wmp_case_light/status'](NS(error=ValueError, send=results.append))
    assert results == [{'enabled': True}]
    assert light.value() == 0
    assert not light.saver.writes


def attention_samples(light, offsets):
    start = light.reactor.now
    values = []
    for offset in offsets:
        light.reactor.advance(start + offset)
        values.append(light.value())
    return values


PATTERN_OFFSETS = (0.01, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)


def test_attention_pattern_from_on(light):
    light.tick()
    assert light.value() == 1
    light.extra.request_attention('scrub')
    assert attention_samples(light, PATTERN_OFFSETS) == [0, 1, 0, 1, 1, 0, 1]
    assert light.extra.get_status(light.reactor.now)['attention_active'] is True


def test_attention_pattern_from_off(light):
    light.tick()
    light.mux[('SET_PIN', 'PIN', 'case_light')](Command(VALUE='0'))
    assert light.value() == 0
    light.extra.request_attention('scrub')
    assert attention_samples(light, PATTERN_OFFSETS) == [1, 0, 1, 0, 0, 1, 0]


def test_attention_follows_resting_state_changes(light):
    light.tick()
    light.extra.request_attention('scrub')
    attention_samples(light, (0.01, 0.5))
    light.backlight.write_text('0\n')  # screen sleeps: resting state becomes off
    assert attention_samples(light, (0.5,)) == [1]
    assert attention_samples(light, (0.5,)) == [0]


def test_release_restores_policy_and_keeps_preference(light):
    light.tick()
    writes = list(light.saver.writes)
    light.extra.request_attention('scrub')
    assert attention_samples(light, (0.01,)) == [0]
    light.extra.release_attention('scrub')
    assert light.value() == 1
    assert attention_samples(light, (0.5, 1.0, 1.5)) == [1, 1, 1]
    assert light.saver.writes == writes
    assert light.extra.get_status(light.reactor.now)['attention_active'] is False


def test_attention_continues_until_every_owner_releases(light):
    light.tick()
    light.extra.request_attention('a')
    light.extra.request_attention('b')
    attention_samples(light, (0.01,))
    light.extra.release_attention('a')
    assert light.value() == 0
    light.extra.release_attention('b')
    assert light.value() == 1
    light.extra.release_attention('b')  # releasing twice is harmless


def test_attention_setting_defaults_enabled(light):
    light.tick()
    assert light.extra.get_status(light.reactor.now)['attention_enabled'] is True
    assert 'wmp_case_light_attention' not in light.saver.variables


def test_attention_disabled_setting_is_saved_and_ignores_requests(light):
    light.tick()
    light.commands['SET_CASE_LIGHT_ATTENTION'](Command(ENABLE='0'))
    assert light.saver.variables['wmp_case_light_attention'] is False
    light.extra.request_attention('scrub')
    assert attention_samples(light, PATTERN_OFFSETS) == [1] * len(PATTERN_OFFSETS)
    status = light.extra.get_status(light.reactor.now)
    assert status['attention_enabled'] is False and status['attention_active'] is False


def test_disabling_attention_stops_a_running_pattern(light):
    light.tick()
    light.extra.request_attention('scrub')
    assert attention_samples(light, (0.01,)) == [0]
    light.commands['SET_CASE_LIGHT_ATTENTION'](Command(ENABLE='0'))
    assert light.value() == 1
    assert attention_samples(light, (0.5, 1.0)) == [1, 1]


def test_enabling_attention_starts_a_pending_request(light):
    light.tick()
    light.commands['SET_CASE_LIGHT_ATTENTION'](Command(ENABLE='0'))
    light.extra.request_attention('scrub')
    light.commands['SET_CASE_LIGHT_ATTENTION'](Command(ENABLE='1'))
    assert light.saver.variables['wmp_case_light_attention'] is True
    assert attention_samples(light, (0.01, 0.5)) == [0, 1]


def test_saved_attention_setting_survives_reload(light):
    light.tick()
    light.commands['SET_CASE_LIGHT_ATTENTION'](Command(ENABLE='0'))
    reloaded = module.load_config(light.config)
    reloaded.request_attention('scrub')
    assert reloaded.get_status(light.reactor.now)['attention_enabled'] is False


@pytest.mark.parametrize('value', ['2', '-1', 'on', None])
def test_invalid_attention_setting_is_refused(light, value):
    light.tick()
    command = Command() if value is None else Command(ENABLE=value)
    with pytest.raises(ValueError):
        light.commands['SET_CASE_LIGHT_ATTENTION'](command)
    assert 'wmp_case_light_attention' not in light.saver.variables


def test_gpio_error_during_pattern_is_logged_once_and_does_not_raise(light, caplog):
    light.tick()
    light.extra.request_attention('scrub')
    attention_samples(light, (0.01,))
    light.gpio.unlink()
    start = light.reactor.now
    for offset in (0.5, 1.0, 1.5):
        light.reactor.advance(start + offset)
    assert caplog.text.count('Case-light policy unavailable') == 1
    assert not light.gpio.exists()


def test_malformed_attention_setting_does_not_stop_the_light_policy(light):
    light.tick()
    light.saver.variables['wmp_case_light_attention'] = 'yes'
    light.backlight.write_text('0\n')
    light.tick()
    assert light.value() == 0  # the normal policy still follows the screen
    light.extra.request_attention('scrub')
    assert attention_samples(light, (0.01, 0.5, 1.0)) == [0, 0, 0]
    assert light.extra.get_status(light.reactor.now)['attention_active'] is False


def test_release_stops_pattern_when_saved_setting_became_malformed(light):
    light.tick()
    light.extra.request_attention('scrub')
    assert attention_samples(light, (0.01,)) == [0]
    light.saver.variables['wmp_case_light_attention'] = 0
    light.extra.release_attention('scrub')
    assert light.value() == 1
    assert attention_samples(light, (0.5, 1.0, 1.5)) == [1, 1, 1]
    assert light.extra.get_status(light.reactor.now)['attention_active'] is False


def test_pattern_does_not_reset_policy_error_reporting(light, caplog):
    light.tick()
    light.extra.request_attention('scrub')
    light.state['state'] = 'unrecognised'
    start = light.reactor.now
    for step in range(1, 9):
        light.reactor.advance(start + step * 0.5)
    assert caplog.text.count('Case-light policy unavailable') == 1
    assert light.extra.last_error


def test_request_before_first_load_does_not_change_adopted_preference(light):
    light.gpio.write_text('0\n')
    light.extra.request_attention('early')
    assert light.value() == 0  # nothing is written before the preference is known
    light.tick()
    assert light.saver.writes == [('wmp_case_light_enabled', False)]
    assert light.extra.get_status(light.reactor.now)['attention_active'] is True
    assert light.value() == 1  # the pattern starts once the preference is loaded
