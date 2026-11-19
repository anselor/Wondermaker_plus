# SPDX-License-Identifier: GPL-3.0-or-later
"""Agreement of the measured gauge centres per head during the stock offset measurement.

The vendor's calibrate_xy reports the gauge centre of each probing round on
the console:

    // Calibrated XY: <cx>, <cy>, dx: <dx>, dy: <dy>, dydx: <ratio>

A head's measurement reports six of them (three rounds, two passes). The span
of a head on one axis is, with k >= 3 centres, the smallest max - min over
every k - 1 of them (for six centres the best five of six); with fewer than
three centres it is 0. The head's centre span is the larger of the X and Y
spans. A head is flagged when offset_centre_spread is above 0, it has at least
three centres and its centre span is above offset_centre_spread. Adding a
centre never lowers the span, so a head flagged early stays flagged; a head
with fewer than six centres at the end is judged on the centres it has.
"""
import logging
import re

PROTOCOL = 2
DEFAULT_LIMIT = 0.030  # mm
TOLERANCE = 1e-9  # mm, applied to the limit.

_NUMBER = r'(-?[0-9]+(?:\.[0-9]+)?)'
CALIBRATED = re.compile(r'// Calibrated XY: %s, %s(?:,.*)?' % (_NUMBER, _NUMBER))


def axis_span(values):
    """Smallest max - min over every len(values) - 1 of values; 0 below three values."""
    if len(values) < 3:
        return 0.
    return min(max(values[:i] + values[i + 1:]) - min(values[:i] + values[i + 1:])
               for i in range(len(values)))


class NozzleTouch:
    """Centre span of each head measured in the calibration attempt named by request."""

    def __init__(self, calibration, config):
        self.calibration = calibration
        self.limit = (DEFAULT_LIMIT if config is None else
                      config.getfloat('offset_centre_spread', DEFAULT_LIMIT, minval=0.))
        self.request = ''
        self.heads = {}  # head -> [(cx, cy)] of its current measurement
        register = getattr(calibration.gcode, 'register_output_handler', None)
        if callable(register):
            register(self.observe)

    # Calibration lifecycle hooks.
    def reset(self, request):
        """A new calibration attempt is admitted; status belongs to it from here on."""
        self.request = request
        self.heads = {}

    def phase_changed(self, head, phase):
        """Progress accepted a phase; a new measurement of a head clears its centres."""
        if phase == 'mounting':
            self.heads[head] = []

    def _measuring(self):
        progress = self.calibration.progress
        if (self.calibration.active and progress.phase == 'position'
                and progress.head >= 0 and progress.request == self.request):
            return progress.head
        return None

    def observe(self, message):
        """G-code output handler; never raises."""
        try:
            for line in message.split('\n'):
                self._line(line.strip())
        except Exception:
            logging.exception('Nozzle touch: output line not evaluated')

    def _line(self, line):
        match = CALIBRATED.fullmatch(line)
        if not match:
            return
        head = self._measuring()
        if head is not None:
            self.heads.setdefault(head, []).append((float(match.group(1)), float(match.group(2))))

    @staticmethod
    def centre_span(centres):
        return max(axis_span([x for x, _ in centres]), axis_span([y for _, y in centres]))

    def _flag(self, centres):
        return (self.limit > 0. and len(centres) >= 3
                and self.centre_span(centres) > self.limit + TOLERANCE)

    def flagged(self):
        return [head for head in sorted(self.heads) if self._flag(self.heads[head])]

    def get_status(self):
        heads = [{'head': head, 'centres': len(self.heads[head]),
                  'centre_span': round(self.centre_span(self.heads[head]), 6),
                  'flagged': self._flag(self.heads[head])}
                 for head in sorted(self.heads)]
        return {'protocol': PROTOCOL, 'request': self.request, 'heads': heads,
                'flagged': self.flagged(), 'restore': self.calibration.offset_snapshot.state}
