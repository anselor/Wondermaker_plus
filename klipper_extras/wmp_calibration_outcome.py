# SPDX-License-Identifier: GPL-3.0-or-later
"""Offset-stage outcome of a calibration attempt and the early-save rule."""
import re

EARLIER_RESULT = re.compile(r'G29|SHAPER_CALIBRATE|PID_CALIBRATE .*')
OFFSET_STAGE = re.compile(r'_WMP_SCRUB_.*|NOZZLE_PREPARE .*|RAPID_MODE .*')


def new_attempt(session, request, **fields):
    # earlier_results: bed level, vibration or a PID run completed without
    # error. offset_stage: a scrub command, NOZZLE_PREPARE or RAPID_MODE was
    # admitted. offsets: 'none', 'measured' or 'stopped'.
    return dict({'protocol': 1, 'session': session, 'request': request,
                 'state': 'pending', 'error': '', 'next': 0, 'executed': False,
                 'earlier_results': False, 'offset_stage': False, 'offsets': 'none'}, **fields)


def fail_attempt(attempt, error, saving=False):
    attempt.update(state='failed', error=error)
    # Only the first failure decides whether the offset stage had begun.
    # A failed SAVE_CONFIG is not an offset-stage failure: the stage ended.
    if attempt.setdefault('offset_stage_failure', attempt['offset_stage'] and not saving):
        attempt['offsets'] = 'stopped'


def note_admitted(attempt, command):
    """The command was admitted and is about to run."""
    if OFFSET_STAGE.fullmatch(command):
        attempt['offset_stage'] = True
        if command == '_WMP_SCRUB_END':
            attempt['offsets'] = 'stopped'  # The scrub was cancelled.


def note_completed(attempt, command):
    """The command ran without error. Not called for the early save."""
    if EARLIER_RESULT.fullmatch(command):
        attempt['earlier_results'] = True
    elif command.startswith('RAPID_MODE ') and attempt['offsets'] == 'none':
        attempt['offsets'] = 'measured'


def early_save_available(attempt, current, printer):
    """The one predicate for the early save: used for admission and
    published as calibration_attempt.early_save_available."""
    return bool(attempt is current and attempt['state'] == 'failed'
                and attempt.get('offset_stage_failure') and attempt['earlier_results']
                and not attempt.get('early_save') and not printer.is_shutdown()
                and not getattr(printer, 'quick_stop_flag', False))


def attempt_status(attempt, current, printer):
    if not attempt:
        return {}
    return dict(attempt, early_save_available=early_save_available(attempt, current, printer))


def admit_early_save(gcmd, attempt, sequence, current, printer):
    """True once for the SAVE_CONFIG that keeps bed level, vibration and
    PID results after the offset stage of the current attempt failed."""
    try:
        command = bytes.fromhex(gcmd.get('HEX', '')).decode('ascii')
    except ValueError:
        return False
    if (command != 'SAVE_CONFIG' or sequence < attempt['next']
            or not early_save_available(attempt, current, printer)):
        return False
    attempt['early_save'] = True
    return True
