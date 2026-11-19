# SPDX-License-Identifier: GPL-3.0-or-later
"""Stored tool offsets recorded when a calibration attempt is admitted.

_WMP_OFFSETS_RESTORE writes the recorded t0_offset..t3_offset back with
SAVE_VARIABLE. It runs only as a stage of the attempt that recorded them. A
restore that cannot write every head reports 'failed' and does not raise, so
the attempt's failure is not latched and the following _WMP_SCRUB_END runs.
"""
import logging
import numbers

NAMES = tuple('t%d_offset' % head for head in range(4))


def _offset(value):
    """The stored value as three floats, or None when it is not an offset."""
    if isinstance(value, (str, bytes)):
        return None
    try:
        values = tuple(value)
    except TypeError:
        return None
    if len(values) != 3 or not all(isinstance(v, numbers.Real) and not isinstance(v, bool)
                                   for v in values):
        return None
    return tuple(float(v) for v in values)


class OffsetSnapshot:
    """Offsets of every head as they were when the attempt named by request was admitted."""

    def __init__(self, calibration):
        self.calibration = calibration
        self.request = ''
        self.offsets = None  # name -> (x, y, z); None when a head had no stored offset.
        self.state = 'none'  # 'none', 'done' or 'failed'
        calibration.gcode.register_command('_WMP_OFFSETS_RESTORE', self.cmd_restore,
                                           desc='Write back the tool offsets recorded for this calibration attempt')

    # Calibration lifecycle hook; never raises.
    def take(self, request):
        """A new calibration attempt is admitted; record the stored offsets."""
        self.request, self.offsets, self.state = request, None, 'none'
        try:
            printer = self.calibration.printer
            now = printer.get_reactor().monotonic()
            variables = printer.lookup_object('save_variables').get_status(now)['variables']
            offsets = {name: _offset(variables.get(name)) for name in NAMES}
        except Exception:
            logging.exception('Offset snapshot: stored offsets not readable')
            return
        missing = [name for name in NAMES if offsets[name] is None]
        if missing:
            logging.warning('Offset snapshot: no stored offset for %s; restore is unavailable', ', '.join(missing))
            return
        self.offsets = offsets

    def _current(self):
        calibration = self.calibration
        executing = calibration.executing
        return bool(calibration.active and executing is not None
                    and executing is calibration._current_attempt
                    and executing['state'] == 'pending'
                    and self.request and executing['request'] == self.request)

    @staticmethod
    def _format(values):
        return ','.join(repr(v) for v in values)

    def restore(self):
        """Write every recorded offset back; True when all four were written."""
        if self.offsets is None:
            logging.warning('Offset snapshot: no snapshot for this attempt; offsets not restored')
            self.state = 'failed'
            return False
        try:
            for name in NAMES:
                self.calibration.gcode.run_script_from_command(
                    'SAVE_VARIABLE VARIABLE=%s VALUE=%s' % (name, self._format(self.offsets[name])))
        except Exception:
            logging.exception('Offset snapshot: offsets not restored')
            self.state = 'failed'
            return False
        self.state = 'done'
        return True

    def cmd_restore(self, gcmd):
        if not self._current():
            raise gcmd.error('Offsets are restored only as a stage of the current calibration attempt')
        self.restore()
