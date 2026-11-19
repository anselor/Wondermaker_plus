# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibration progress phase and head published for the touchscreen."""

PROTOCOL = 1
SETTABLE_PROGRESS_PHASES = ('mounting', 'position', 'height', 'docking')


class CalibrationProgress:
    """Progress of the calibration attempt named by request."""

    def __init__(self, calibration):
        self.calibration = calibration
        self.gcode = calibration.gcode
        self.head, self.phase = -1, 'idle'
        # Request id of the calibration attempt this status belongs to; '' until
        # a bound attempt is admitted.
        self.request = ''
        # Heads whose RAPID_MODE completed for this request; a RAPID_MODE of
        # this request is executing while measuring is True.
        self.measured, self.measuring = set(), False
        self.gcode.register_command('_WMP_CALIBRATION_PHASE', self.cmd_phase,
                                    desc='Set the calibration progress phase')

    def get_status(self):
        return {'protocol': PROTOCOL, 'head': self.head, 'phase': self.phase,
                'request': self.request, 'measured': sorted(self.measured),
                'measuring': self.measuring}

    # Calibration lifecycle hooks.
    def reset(self, request):
        """A new calibration attempt is admitted; status belongs to it from here on."""
        self.idle()
        self.request = request
        self.measured, self.measuring = set(), False

    def idle(self):
        self.head, self.phase = -1, 'idle'

    def set_homing(self):
        self.head, self.phase = -1, 'homing'

    def set_docking(self):
        """The final park follows probing; keep the head being calibrated."""
        if self.head >= 0:
            self.phase = 'docking'

    def measure_started(self, head):
        """A RAPID_MODE of this request starts; the head has no completed measurement."""
        self.measured.discard(head)
        self.measuring = True

    def measure_completed(self, head):
        self.measured.add(head)
        self.measuring = False

    def measure_ended(self):
        """The calibration command ended, however it ended."""
        self.measuring = False

    def cmd_phase(self, gcmd):
        # Called from macros that may also run outside the calibration wrapper:
        # a valid request is ignored there, a malformed one is still an error.
        head = gcmd.get_int('HEAD', minval=0, maxval=3)
        phase = gcmd.get('PHASE')
        if phase not in SETTABLE_PROGRESS_PHASES:
            raise gcmd.error('PHASE must be one of: ' + ', '.join(SETTABLE_PROGRESS_PHASES))
        if self.calibration.active:
            self.head, self.phase = head, phase
            self.calibration.nozzle_touch.phase_changed(head, phase)
