# SPDX-License-Identifier: GPL-3.0-or-later
"""Guided nozzle scrub commands, heaters, attention signal and status."""
import logging

PROTOCOL = 1
SCRUB_ATTENTION_OWNER = 'nozzle_scrub'
RUNNING_PHASES = ('mounting', 'positioning', 'heating')


def heater_name(head):
    return 'extruder' if head == 0 else 'extruder%d' % head


class NozzleScrubCommands:
    """Scrub stage of one calibration attempt.

    Commands run inside the sequenced calibration wrapper
    (_WMP_CALIBRATION_COMMAND), so a scrub belongs to one calibration attempt
    and its heaters are turned off by the calibration failure path.
    """

    def __init__(self, calibration, config):
        self.calibration = calibration
        self.printer, self.gcode = calibration.printer, calibration.gcode
        if config is None:
            self.x, self.y, self.z, self.temp = 150., 2., 100., 160.
        else:
            self.x = config.getfloat('scrub_x', 150.)
            self.y = config.getfloat('scrub_y', 2.)
            self.z = config.getfloat('scrub_z', 100., minval=20., maxval=250.)
            self.temp = config.getfloat('scrub_temp', 160., minval=0., maxval=170.)
        self.head, self.phase, self.error = -1, 'idle', ''
        # Request id of the calibration attempt this status belongs to; '' until
        # a bound attempt is admitted.
        self.request = ''
        self.heated = set()  # Heaters this scrub turned on; survives across commands.
        for name, handler, desc in (
                ('_WMP_SCRUB_HEAD', self.cmd_head, 'Mount a head, heat it and move it to the scrub position'),
                ('_WMP_SCRUB_HEAT', self.cmd_heat, 'Heat a head for the scrub'),
                ('_WMP_SCRUB_COOL', self.cmd_cool, 'Turn off the heaters this scrub heated'),
                ('_WMP_SCRUB_END', self.cmd_end, 'Finish the scrub: cool, park, release attention'),
                ('_WMP_SCRUB_ATTENTION', self.cmd_attention, 'Request or release the case-light signal')):
            self.gcode.register_command(name, handler, desc=desc)

    @staticmethod
    def _format(value):
        return ('%f' % value).rstrip('0').rstrip('.')

    def get_status(self):
        return {'protocol': PROTOCOL, 'head': self.head, 'phase': self.phase,
                'target': float(self.temp), 'error': self.error, 'request': self.request}

    def _require_active(self, gcmd):
        if not self.calibration.active:
            raise gcmd.error('Scrub commands only run inside a calibration command')

    def _run(self, script):
        self.gcode.run_script_from_command(script)

    # Calibration lifecycle hooks.
    def _cool_all(self):
        """Turn off every heater this scrub heated; returns the error texts.
        A heater whose write failed stays recorded."""
        errors = []
        for name in sorted(self.heated):
            try:
                self._run('SET_HEATER_TEMPERATURE HEATER=%s TARGET=0' % name)
                self.heated.discard(name)
            except Exception as error:
                # Kept: a later END, failure or reset tries it again.
                errors.append('%s: %s' % (name, error))
        return errors

    def _fail(self, sentence, error):
        """Record a failure. The screen shows the sentence; the raw error is
        logged here and latched by the calibration wrapper."""
        self.phase, self.error = 'failed', sentence
        logging.warning('Nozzle scrub failed: %s', error)

    def _step(self, sentence, *scripts):
        """Run scripts; a failure is reported on screen as sentence."""
        try:
            for script in scripts:
                self._run(script)
        except Exception as error:
            self._fail(sentence, error)
            raise

    def _release_attention(self):
        """A scrub that ends abnormally cannot send the release command."""
        try:
            self._set_attention(False)
        except Exception:
            logging.exception('Unable to release the nozzle scrub attention signal')

    def reset(self, request):
        """A new calibration attempt is admitted; the previous scrub is over.
        Status belongs to the new attempt from here on."""
        self._release_attention()
        errors = self._cool_all()
        self.head, self.phase, self.error = -1, 'idle', ''
        self.request = request
        if errors:
            # A command error refuses the command; any other exception type
            # would shut Klipper down.
            raise self.printer.command_error('Previous scrub heater cool-down failed: ' + '; '.join(errors))

    def attempt_failed(self, error):
        """The attempt failed. Cool this scrub's heaters directly as well as
        through heater ownership, which may be unavailable."""
        self._release_attention()
        errors = self._cool_all()
        if self.phase in RUNNING_PHASES:
            # Another command of the attempt failed: no scrub sentence applies
            # and the raw text is not shown on screen.
            self.phase, self.error = 'failed', ''
        if errors:
            logging.warning('Scrub heater cool-down on failure: %s', '; '.join(errors))

    # Commands.
    def cmd_head(self, gcmd):
        self._require_active(gcmd)
        head = gcmd.get_int('T', minval=0, maxval=3)
        self.head, self.phase, self.error = head, 'mounting', ''
        now = self.printer.get_reactor().monotonic()
        axes = self.printer.lookup_object('toolhead').get_status(now)['homed_axes']
        if any(axis not in axes for axis in 'xyz'):
            error = gcmd.error('Home X, Y and Z before the nozzle scrub: homed axes are "%s"' % axes)
            self._fail('The printer must be homed first.', error)
            raise error
        # The Z move below runs before the tool change, so it needs the guards
        # the tool change would apply: a valid Z reference and no recorded fault.
        recovery = self.printer.lookup_object('wmp_recovery', None)
        if recovery is None or not recovery.get_status(now).get('z_reference_valid', False):
            error = gcmd.error('The Z reference is not valid before the nozzle scrub; home Z first')
            self._fail('The printer must be homed first.', error)
            raise error
        mount = 'Head %d did not mount.' % (head + 1)
        self._check_fail_flag(gcmd, now, mount)
        self._heat(head)
        position = 'Head %d could not be moved into position.' % (head + 1)
        # The bed is lowered before the pickup. A tool change that does not
        # home Z keeps the height; the second lower after the clearance move
        # covers one that does.
        lower = 'G1 Z%s F1800' % self._format(self.z)
        self._step(position, 'SET_GCODE_OFFSET X=0 Y=0 Z=0', 'G90', lower)
        self._step(mount, '_WMP_CALIBRATION_TOOL T=%d' % head)
        # The tool change can record a fault without raising. Nothing moves after it.
        self._check_fail_flag(gcmd, now, mount)
        self.phase = 'positioning'
        self._step(position, 'SET_GCODE_OFFSET X=0 Y=0 Z=0', '_WMP_CALIBRATION_CLEARANCE', 'G90', lower,
                   '_WMP_XY_TRAVEL X=%s Y=%s HOT=1' % (self._format(self.x), self._format(self.y)),
                   'M400')
        self.phase = 'heating'

    def _check_fail_flag(self, gcmd, now, sentence):
        flag = self.printer.lookup_object('save_variables').get_status(now)['variables'].get('fail_flag', 0)
        if int(flag) != 0:
            error = gcmd.error('Tool change failed during the nozzle scrub: fail_flag=%s' % repr(flag)[:80])
            self._fail(sentence, error)
            raise error

    def _heat(self, head):
        name = heater_name(head)
        self.heated.add(name)  # Recorded first: a partial failure must still cool it.
        self._step('Head %d could not be heated.' % (head + 1),
                   'SET_HEATER_TEMPERATURE HEATER=%s TARGET=%s' % (name, self._format(self.temp)))

    def cmd_heat(self, gcmd):
        self._require_active(gcmd)
        self._heat(gcmd.get_int('T', minval=0, maxval=3))

    def _cool(self, gcmd, head=None):
        names = sorted(self.heated) if head is None else [n for n in (heater_name(head),) if n in self.heated]
        errors = []
        for name in names:
            try:
                self._run('SET_HEATER_TEMPERATURE HEATER=%s TARGET=0' % name)
                self.heated.discard(name)
            except Exception as error:
                errors.append('%s: %s' % (name, error))
        if errors:
            raise gcmd.error('Scrub heater cool-down failed: ' + '; '.join(errors))

    def cmd_cool(self, gcmd):
        self._require_active(gcmd)
        head = gcmd.get_int('T', None, minval=0, maxval=3)
        self._cool(gcmd, head)

    def cmd_end(self, gcmd):
        self._require_active(gcmd)
        try:
            self._cool(gcmd)
            self._step('The head could not be returned to its dock.', 'PARK_CURRENT_TOOL')
        finally:
            self._set_attention(False)
        self.head, self.phase, self.error = -1, 'ended', ''

    def _set_attention(self, value):
        light = self.printer.lookup_object('wmp_case_light', None)
        method = getattr(light, 'request_attention' if value else 'release_attention', None)
        if not callable(method):
            return
        method(SCRUB_ATTENTION_OWNER)

    def cmd_attention(self, gcmd):
        self._require_active(gcmd)
        self._set_attention(gcmd.get_int('VALUE', minval=0, maxval=1) == 1)
