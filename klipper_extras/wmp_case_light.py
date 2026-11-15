"""Saved case-light preference, gated by screen activity and print state.

The stock light is active-high GPIO76. The companion screen preload routes
explicit light choices through SET_PIN. SAVE_VARIABLE persists the preference;
automatic GPIO writes never change it.

Other features can request an attention signal. While requested, the light is
toggled away from its resting state in ATTENTION_PATTERN and returns to the
normal policy on release. The signal has its own saved on/off setting.
"""
import configparser
import logging
import math

LIGHT_VALUE_PATH = '/sys/class/gpio/gpio76/value'
BACKLIGHT_PATH = '/sys/class/backlight/backlight/brightness'
SCREEN_CONFIG_PATH = '/home/t13dp/printer_data/config/tmt1.ini'
PREFERENCE_VARIABLE = 'wmp_case_light_enabled'
ATTENTION_VARIABLE = 'wmp_case_light_attention'
POLL_SECONDS = 0.5
# (opposite of the resting state, seconds): two half-second toggles, then rest.
ATTENTION_PATTERN = ((True, 0.5), (False, 0.5), (True, 0.5), (False, 1.0))


class CaseLight:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.enabled = None
        self.print_active = False
        self.finished_at = None
        self.last_error = None
        self.timer = self.reactor.register_timer(self._tick)
        self.attention_enabled = True
        self.attention_usable = True
        self.attention_owners = set()
        self.attention_step = None  # Index into ATTENTION_PATTERN while signalling.
        self.attention_timer = self.reactor.register_timer(self._attention_tick)
        self.printer.register_event_handler('klippy:ready', self._ready)
        self.printer.lookup_object('webhooks').register_endpoint(
            'wmp_case_light/set', self._web_set_preference)
        self.printer.lookup_object('webhooks').register_endpoint(
            'wmp_case_light/status', self._web_status)
        self.printer.lookup_object('webhooks').register_endpoint(
            'wmp_case_light/wake', self._web_wake)
        gcode = self.gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command('SET_PIN', 'PIN', 'case_light', self.cmd_SET_PIN,
                                   desc='Set the value of an output pin')
        gcode.register_command('_WMP_CASE_LIGHT_TOGGLE', self.cmd_toggle)
        gcode.register_command('_WMP_CASE_LIGHT_PRINT_START', self.cmd_print_start)
        gcode.register_command('_WMP_CASE_LIGHT_PRINT_END', self.cmd_print_end)
        gcode.register_command('SET_CASE_LIGHT_ATTENTION', self.cmd_attention,
                               desc='Enable or disable the case-light attention signal')

    @staticmethod
    def _read_bit(path):
        with open(path) as stream:
            value = stream.read().strip()
        if value not in ('0', '1'):
            raise ValueError('%s did not report 0 or 1' % path)
        return int(value)

    def _load_preference(self):
        variables = self.printer.lookup_object('save_variables').get_status(
            self.reactor.monotonic())['variables']
        if PREFERENCE_VARIABLE not in variables:
            # First installation adopts the existing light choice once.
            self._save_preference(bool(self._read_bit(LIGHT_VALUE_PATH)))
        else:
            value = variables[PREFERENCE_VARIABLE]
            if type(value) is not bool:
                raise ValueError('Saved case-light preference must be True or False')
            self.enabled = value

    def _save_preference(self, enabled):
        saver = self.printer.lookup_object('save_variables')
        variables = saver.get_status(self.reactor.monotonic())['variables']
        if variables.get(PREFERENCE_VARIABLE) is bool(enabled):
            self.enabled = bool(enabled)
            return
        command = self.gcode.create_gcode_command('SAVE_VARIABLE', 'SAVE_VARIABLE', {
            'VARIABLE': PREFERENCE_VARIABLE, 'VALUE': repr(bool(enabled))})
        saver.cmd_SAVE_VARIABLE(command)
        self.enabled = bool(enabled)

    def _load_attention(self):
        self.attention_usable = False
        variables = self.printer.lookup_object('save_variables').get_status(
            self.reactor.monotonic())['variables']
        value = variables.get(ATTENTION_VARIABLE, True)
        if type(value) is not bool:
            raise ValueError('Saved case-light attention setting must be True or False')
        self.attention_enabled = value
        self.attention_usable = True

    def _attention_opposite(self):
        return self.attention_step is not None and ATTENTION_PATTERN[self.attention_step][0]

    def _attention_sync(self, eventtime):
        """Start or stop the pattern to match the owners and the saved setting.

        The pattern never starts before the light preference is known: on a
        first installation that preference is adopted from the GPIO level.
        """
        wanted = (bool(self.attention_owners) and self.attention_usable
                  and self.attention_enabled and self.enabled is not None)
        if wanted and self.attention_step is None:
            self.attention_step = 0
            self.reactor.update_timer(self.attention_timer,
                                      eventtime + ATTENTION_PATTERN[0][1])
            self._apply(eventtime)
        elif not wanted and self.attention_step is not None:
            self.attention_step = None
            self.reactor.update_timer(self.attention_timer, self.reactor.NEVER)
            self._apply(eventtime)

    def _attention_update(self):
        # A setting that cannot be read stops the pattern; it never keeps one running.
        self._automatic(self._load_attention, clear=False)
        self._automatic(lambda: self._attention_sync(self.reactor.monotonic()), clear=False)

    def _attention_tick(self, eventtime):
        if self.attention_step is None:
            return self.reactor.NEVER
        self.attention_step = (self.attention_step + 1) % len(ATTENTION_PATTERN)
        self._automatic(lambda: self._apply(eventtime), clear=False)
        return eventtime + ATTENTION_PATTERN[self.attention_step][1]

    def request_attention(self, owner):
        self.attention_owners.add(owner)
        self._attention_update()

    def release_attention(self, owner):
        self.attention_owners.discard(owner)
        self._attention_update()

    def cmd_attention(self, gcmd):
        enabled = bool(gcmd.get_int('ENABLE', minval=0, maxval=1))
        try:
            saver = self.printer.lookup_object('save_variables')
            command = self.gcode.create_gcode_command('SAVE_VARIABLE', 'SAVE_VARIABLE', {
                'VARIABLE': ATTENTION_VARIABLE, 'VALUE': repr(enabled)})
            saver.cmd_SAVE_VARIABLE(command)
        except (OSError, ValueError, self.printer.command_error) as error:
            raise gcmd.error('Case-light attention setting unavailable: %s' % error)
        self._attention_update()

    def _screen_on(self):
        with open(BACKLIGHT_PATH) as stream:
            value = int(stream.read().strip())
        if value < 0:
            raise ValueError('Invalid screen brightness')
        return value > 0

    def _screen_delay(self):
        parser = configparser.RawConfigParser()
        with open(SCREEN_CONFIG_PATH) as stream:
            parser.read_file(stream)
        milliseconds = parser.getfloat('screen', 'screen_off_delay')
        if not math.isfinite(milliseconds) or milliseconds < 0:
            raise ValueError('Invalid screen_off_delay')
        return milliseconds / 1000.

    def _update_print(self, eventtime):
        stats = self.printer.lookup_object('print_stats').get_status(eventtime)
        state = stats['state']
        if state not in ('printing', 'paused', 'complete', 'cancelled', 'error', 'standby'):
            raise ValueError('Unknown print state: %s' % state)
        active = state in ('printing', 'paused')
        if active:
            self.finished_at = None
        elif self.print_active:
            self.finished_at = eventtime
        self.print_active = active

    def _desired(self, eventtime, waking=False):
        if not self.enabled:
            return 0
        if self.print_active or waking or self._screen_on():
            return 1
        return int(self.finished_at is not None
                   and eventtime < self.finished_at + self._screen_delay())

    def _apply(self, eventtime, waking=False):
        value = self._desired(eventtime, waking=waking)
        if self._attention_opposite():
            value = 1 - value
        # Do not export, reset, or recreate GPIOs owned by the stock screen.
        with open(LIGHT_VALUE_PATH, 'r+') as stream:
            current = stream.read().strip()
            if current not in ('0', '1'):
                raise ValueError('GPIO76 did not report 0 or 1')
            if int(current) != value:
                stream.seek(0)
                stream.write(str(value))

    def _automatic(self, callback, clear=True):
        # Attention paths pass clear=False: their success says nothing about
        # the policy tick, so it must not reset that tick's error reporting.
        try:
            callback()
            if clear:
                self.last_error = None
        except (OSError, ValueError, configparser.Error, self.printer.command_error) as error:
            message = str(error)
            if message != self.last_error:
                logging.warning('Case-light policy unavailable: %s', error)
            self.last_error = message

    def _ready(self):
        self.reactor.update_timer(self.timer, self.reactor.NOW)
        # A malformed attention setting must not stop the normal light policy,
        # so it is read here and on each request, never in the policy tick.
        self._automatic(self._load_attention, clear=False)

    def _tick(self, eventtime):
        def update():
            self._load_preference()
            self._update_print(eventtime)
            self._attention_sync(eventtime)
            self._apply(eventtime)
        self._automatic(update)
        return eventtime + POLL_SECONDS

    def get_status(self, eventtime):
        try:
            value = float(self._read_bit(LIGHT_VALUE_PATH))
        except (OSError, ValueError):
            value = None
        return {'value': value, 'available': value is not None,
                'enabled': self.enabled, 'print_active': self.print_active,
                'policy_version': 2, 'last_error': self.last_error,
                'attention_enabled': self.attention_enabled and self.attention_usable,
                'attention_active': self.attention_step is not None}

    def _set_preference(self, gcmd, toggle=False):
        value = None if toggle else gcmd.get_float('VALUE', minval=0., maxval=1.)
        if not toggle and value not in (0., 1.):
            raise gcmd.error('case_light is an on/off preference; VALUE must be 0 or 1')
        try:
            self._load_preference()
            self._save_preference(not self.enabled if toggle else bool(value))
            now = self.reactor.monotonic()
            if self.enabled:
                self._update_print(now)
            self._apply(now)
        except (OSError, ValueError, configparser.Error, self.printer.command_error) as error:
            raise gcmd.error('Case-light preference/control unavailable: %s' % error)

    def cmd_SET_PIN(self, gcmd):
        self._set_preference(gcmd)

    def _web_set_preference(self, request):
        # A screen click must not wait behind a motion/heater G-code mutex.
        # SAVE_VARIABLE is synchronous in the supported stock Klipper builds,
        # so this reactor callback uses the same managed API without queuing
        # a G-code script or introducing a second file/database writer.
        value = request.get_int('enabled')
        if value not in (0, 1):
            raise request.error('enabled must be 0 or 1')
        command = self.gcode.create_gcode_command('SET_PIN', 'SET_PIN', {'VALUE': str(value)})
        try:
            self._set_preference(command)
        except self.printer.command_error as error:
            raise request.error(str(error))
        request.send({'enabled': self.enabled,
                      'value': self.get_status(self.reactor.monotonic())['value']})

    def _web_status(self, request):
        try:
            self._load_preference()
        except (OSError, ValueError, self.printer.command_error) as error:
            raise request.error(str(error))
        request.send({'enabled': self.enabled})

    def _web_wake(self, request):
        # Called before the screen enables its backlight. This one-shot hint
        # lights the case now; subsequent ticks read the real backlight again.
        try:
            self._load_preference()
            self._update_print(self.reactor.monotonic())
            self._apply(self.reactor.monotonic(), waking=True)
        except (OSError, ValueError, configparser.Error, self.printer.command_error) as error:
            raise request.error(str(error))
        request.send({'enabled': self.enabled})

    def cmd_toggle(self, gcmd):
        self._set_preference(gcmd, toggle=True)

    def cmd_print_start(self, gcmd):
        # Automatic activation honors OFF and never changes the saved choice.
        self.print_active = True
        self.finished_at = None
        def update():
            self._load_preference()
            self._apply(self.reactor.monotonic())
        self._automatic(update)

    def cmd_print_end(self, gcmd):
        self.print_active = False
        self.finished_at = self.reactor.monotonic()
        def update():
            self._load_preference()
            self._apply(self.finished_at)
        self._automatic(update)


def load_config(config):
    return CaseLight(config)
