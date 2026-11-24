# SPDX-License-Identifier: GPL-3.0-or-later
"""Print-start progress and slicer-requested chamber stabilization.

Progress is display state only. It is never consulted for machine admission.
The chamber wait consumes existing print-stop requests; it owns no cancel path.
"""
import logging
import math
import uuid


PHASES = (
    ('preheat', 'Preheat probe nozzle'),
    ('homing', 'Mount head and home printer'),
    ('bed', 'Heat bed'),
    ('chamber', 'Heat chamber'),
    ('stabilizing', 'Stabilize temperatures'),
    ('mesh', 'Prepare bed mesh'),
    ('nozzle', 'Heat print nozzle'),
    ('purging', 'Prime nozzle'),
)


class PrintPreparation:
    def __init__(self, material):
        self.material = material
        self.state = {}
        self._job_file = None
        self._submission = None

    @property
    def printer(self):
        return self.material.printer

    def begin_submission(self, submission, total):
        self._submission = submission
        self._job_file = None
        self._file_state(submission['file'], total)
        self.state['scope'] = 'submission'
        self.state['start'] = submission['id']
        return self.state['id']

    def bind_dispatched_submission(self, submission):
        if self._submission is not submission or self.state.get('phase') != 'file':
            return
        sd = self.printer.lookup_object('virtual_sdcard', None)
        now = self.printer.get_reactor().monotonic()
        stats = self.printer.lookup_object('print_stats').get_status(now)
        stream = getattr(sd, 'current_file', None)
        if stream is None or stats.get('filename') != submission['file']:
            return
        self._job_file = stream
        self._submission = None
        self.state.pop('scope', None)
        self.state.pop('start', None)

    def _file_state(self, filename, total):
        self.state = {'protocol': 1, 'id': uuid.uuid4().hex, 'file': filename,
                      'phase': 'file', 'active': True,
                      'steps': [{'phase': 'file', 'label': 'Read/process G-code'}],
                      'file_progress': {'bytes': 0, 'total': total},
                      'instruction': 'Reading the print file and preparing recovery information.',
                      'note': ''}

    def begin_file_scan(self, filename, total):
        """Show bookkeeping only for the actual active SD attempt.

        A pending screen submission has no SD job to cancel yet; do not make it
        look like an active print or borrow the previous job's cancellation.
        """
        now = self.printer.get_reactor().monotonic()
        stats = self.printer.lookup_object('print_stats').get_status(now)
        sd = self.printer.lookup_object('virtual_sdcard', None)
        stream = getattr(sd, 'current_file', None)
        if stats.get('state') != 'printing' or stats.get('filename') != filename or stream is None:
            return None
        self._job_file = stream
        self._submission = None
        self._file_state(filename, total)
        return self.state['id']

    def file_scan_progress(self, attempt, completed):
        if attempt and self.state.get('id') == attempt and self.state.get('phase') == 'file':
            progress = self.state['file_progress']
            progress['bytes'] = min(progress['total'], max(0, completed))

    def cmd_BEGIN(self, gcmd):
        chamber = gcmd.get_float('CHAMBER', 0., minval=0.)
        if not math.isfinite(chamber):
            raise gcmd.error('CHAMBER must be a finite temperature')
        if chamber > 0:
            self.printer.lookup_object('heaters').lookup_heater('chamber')
        filename = self.printer.lookup_object('print_stats').get_status(
            self.printer.get_reactor().monotonic()).get('filename', '')
        sd = self.printer.lookup_object('virtual_sdcard', None)
        stream = getattr(sd, 'current_file', None)
        continued_scan = (self.state.get('phase') == 'file' and self.state.get('file') == filename
                          and stream is not None
                          and (self._job_file is stream
                               or (self._submission is not None
                                   and self._submission is self.material.print_submission
                                   and self._submission.get('state') in ('pending', 'submitted'))))
        attempt = self.state['id'] if continued_scan else uuid.uuid4().hex
        steps = ([{'phase': 'file', 'label': 'Read/process G-code'}] if continued_scan else [])
        steps += [{'phase': key, 'label': label} for key, label in PHASES
                  if chamber > 0 or key not in ('chamber', 'stabilizing')]
        self._job_file = stream
        self._submission = None
        self.state = {'protocol': 1, 'id': attempt,
                      'file': filename, 'phase': 'preheat', 'active': True,
                      'steps': steps,
                      'chamber_target': chamber, 'hold_remaining': 0., 'instruction': '', 'note': ''}

    def cmd_STAGE(self, gcmd):
        phase = gcmd.get('PHASE', '')
        if not self.state:
            return
        if phase == 'printing':
            self.state.update(active=False, phase=phase)
        elif phase in {step['phase'] for step in self.state['steps']}:
            self.state.update(phase=phase, instruction='', note='')
        else:
            logging.warning('Ignored unknown print progress phase: %r', phase)

    def get_status(self, now):
        result = dict(self.state)
        if not result.get('active', False):
            return result
        stats = self.printer.lookup_object('print_stats').get_status(now)
        sd = self.printer.lookup_object('virtual_sdcard', None)
        if result.get('scope') == 'submission':
            result['active'] = (self._submission is self.material.print_submission
                                and self._submission.get('state') == 'pending'
                                and self._submission.get('session') == self.material.session_id
                                and not sd.is_active()
                                and stats.get('state') not in ('printing', 'paused'))
            return result
        result['active'] = (stats.get('state') == 'printing' and stats.get('filename') == result['file']
                            and self._job_file is not None and getattr(sd, 'current_file', None) is self._job_file)
        if result['active']:
            if result.get('phase') == 'mesh':
                progress = self._mesh_progress()
                if progress is not None:
                    result['mesh_progress'] = progress
            result['temperatures'] = {}
            for key, name in (('bed', 'heater_bed'), ('chamber', 'heater_generic chamber')):
                obj = self.printer.lookup_object(name, None)
                if obj is not None:
                    status = obj.get_status(now)
                    result['temperatures'][key] = {'actual': status.get('temperature'), 'target': status.get('target')}
        return result

    def _mesh_progress(self):
        # WM 1.1.13 already records completed mesh points in its probe session.
        # Observe that work; never wrap probing or count individual samples.
        mesh = self.printer.lookup_object('bed_mesh', None)
        calibrate = getattr(mesh, 'bmc', None)
        manager = getattr(calibrate, 'probe_mgr', None)
        helper = getattr(manager, 'probe_helper', None)
        points = getattr(helper, 'probe_points', None)
        probe = self.printer.lookup_object('probe', None)
        session = getattr(probe, 'probe_session', None)
        results = getattr(session, 'results', None)
        if (not getattr(session, 'multi_probe_pending', False)
                or not isinstance(points, (list, tuple)) or not points
                or not isinstance(results, list)):
            return None
        return {'point': min(len(results) + 1, len(points)), 'total': len(points)}

    def _check_stop(self, gcmd):
        # Use the stop-points branch when installed; do not duplicate its
        # request, cleanup, receipt or cancellation implementation.
        requested = getattr(self.material, 'stop_requested', None)
        if callable(requested):
            if requested() is not None:
                self.material.check_stop_point(
                    'chamber_preparation', 'during chamber preparation',
                    'homed; chamber temperature stabilization interrupted')
        elif self.material._print_cancel_active():
            raise gcmd.error('Print cancelled during chamber preparation')
        if self.printer.is_shutdown() or getattr(self.printer, 'quick_stop_flag', False):
            raise gcmd.error('Printer stopped during chamber preparation')

    def cmd_WAIT_CHAMBER(self, gcmd):
        target = gcmd.get_float('TARGET', 0., minval=0.)
        if target == 0:
            return
        hold = gcmd.get_float('HOLD', 60., minval=0.)
        bed_target = gcmd.get_float('BED', 0., minval=0.)
        if not all(math.isfinite(value) for value in (target, hold, bed_target)):
            raise gcmd.error('TARGET, BED and HOLD must be finite numbers')
        heaters = self.printer.lookup_object('heaters')
        chamber = heaters.lookup_heater('chamber')
        bed = heaters.lookup_heater('heater_bed')
        doors = [self.printer.lookup_object('gcode_button Door_button%d' % i, None)
                 for i in (1, 2)]
        available = [door for door in doors if door is not None]
        reactor = self.printer.get_reactor()
        stable_since = None
        while True:
            self._check_stop(gcmd)
            now = reactor.monotonic()
            chamber_temp, _ = chamber.get_temp(now)
            bed_temp, _ = bed.get_temp(now)
            closed = all(door.get_status(now).get('state') == 'PRESSED' for door in available)
            in_range = abs(chamber_temp - target) <= 1. and (bed_target <= 0 or abs(bed_temp - bed_target) <= 2.)
            note = '' if len(available) == 2 else 'Check that the doors are closed; door sensing is incomplete.'
            self.state.update(phase='chamber', instruction='Close the doors to continue.' if not closed else '',
                              note=note, chamber_actual=chamber_temp, bed_actual=bed_temp)
            if closed and in_range:
                if stable_since is None:
                    stable_since = now
                remaining = max(0., hold - (now - stable_since))
                self.state.update(phase='stabilizing', hold_remaining=remaining)
                if remaining == 0:
                    return
            else:
                stable_since = None
                self.state['hold_remaining'] = hold
            reactor.pause(now + .5)
