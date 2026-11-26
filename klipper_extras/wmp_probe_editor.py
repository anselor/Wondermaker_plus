# SPDX-License-Identifier: GPL-3.0-or-later
"""Serialized probe-editor commands and save/discard workflow."""
import logging

import hashlib


import math

import copy


import re

import uuid

import sys

import os


try:
    from .wmp_calibration_records import ProbeSaveRecord
    from .wmp_probe_state import ProbeConfigChange, ProbeEditorReceipt
except ImportError:
    from wmp_calibration_records import ProbeSaveRecord
    from wmp_probe_state import ProbeConfigChange, ProbeEditorReceipt


class ProbeEditorCommands:
    """Serialized probe editor requests; no commands originate from status reads."""
    STEPS = ('1', '-1', '0.1', '-0.1', '0.05', '-0.05', '0.025', '-0.025',
             '0.01', '-0.01', '0.005', '-0.005')

    def __init__(self, calibration):
        self.calibration = calibration
        self.printer, self.gcode = calibration.printer, calibration.gcode
        self.receipt = None
        self._executing = False
        self._preparation_scope = None
        self._retired_requests = set()
        self.diagnostic_warning = ''
        self.request = ''
        self.config_change = None
        self.preparation_config = None
        self.failure_token = ''
        self.preparation_error = ''
        self.state, self.error = 'idle', ''
        self.sequence = -1
        self.last = None
        self.action_refused = False
        self.stop_requested = False
        self.stop_checkpoint_hit = False
        self.stop_exception = None
        self.save_review_required = False
        self.save_review = None
        self.save_ack_token = ''
        self.save_review_origin_unknown = False
        self.restored_save_request = ''
        self.save_review_confirmable = False
        self.save_review_sequence = 0
        self.save_review_result = None
        self.save_review_last = None
        register = getattr(self.printer, 'register_event_handler', None)
        if register is not None:
            register('klippy:ready', self._restore_save_evidence)
        self.gcode.register_command('_WMP_PROBE_SAVE_REVIEW', self.cmd_save_review,
                                    desc='Review and acknowledge persisted probe save evidence')
        self.gcode.register_command('_WMP_PROBE_PREPARE_CHECK', self.cmd_prepare_check)
        webhooks = self.printer.lookup_object('webhooks', None)
        if webhooks is not None:
            webhooks.register_endpoint('wmp/probe_editor/stop', self.handle_stop)
        self.gcode.register_command('_WMP_PROBE_EDITOR', self.cmd_run,
                                    desc='Run a session-bound manual probe editor action')

    def _save_record_store(self):
        path = os.path.realpath(self.printer.get_start_args()['config_file'])
        return ProbeSaveRecord(os.path.join(os.path.dirname(path), 'wmp_probe_save.json')), path

    def _record_save_intent(self):
        store, path = self._save_record_store()
        with open(path, 'rb') as stream:
            before = stream.read(16 * 1024 * 1024 + 1)
        if len(before) > 16 * 1024 * 1024:
            raise ValueError('Configuration is too large for probe save review')
        self.config_change.admit_save()
        parser = self.config_change.configfile.autosave.fileconfig
        record = {'version': 1, 'session': self.calibration.session, 'request': self.request,
                  'config_path': path, 'section': self.config_change.section,
                  'offset': self.config_change.value, 'before_sha256': hashlib.sha256(before).hexdigest(),
                  'autosave': {section: dict(parser.items(section, raw=True)) for section in parser.sections()}}
        # A partial evidence publication stays reviewable; it never authorizes
        # replay and cannot prevent the explicitly requested configuration save.
        self.save_review_required = True
        store.create(record, replace_history=True)
        self.save_review = {'record': record, 'outcome': 'review_required', 'configuration_matches': False}
        self.config_change.admit_save()

    def _read_save_review(self):
        store, path = self._save_record_store()
        config = self.printer.lookup_object('configfile')
        _, autosave = config._find_autosave_data(config._read_config_file(path))
        disk = config._build_config_wrapper(autosave, path).fileconfig
        disk_values = {section: dict(disk.items(section, raw=True)) for section in disk.sections()}
        loaded, pending = copy.deepcopy(config.status_raw_config), copy.deepcopy(config.status_save_pending)
        review = store.review(path, disk_values, loaded, pending)
        if review is None:
            raise ValueError('Probe save evidence is missing; manual review is required')
        review['token'] = hashlib.sha256((self.calibration.session + ':' + review['review']).encode()).hexdigest()
        return store, path, disk_values, loaded, pending, review

    def _restore_save_evidence(self):
        # Read once on Ready, never from a periodic status update. Retain bytes.
        try:
            store, _ = self._save_record_store()
            record = store.read()
            if record is None:
                return
            self.save_review_required = True
            self.request, self.sequence = record['request'], 0
            self.state = 'save_review'
            if store.acknowledged(record):
                self.state, self.save_review_required = 'save_acknowledged', False
                self.error = 'Previous save review was acknowledged; its evidence is retained.'
                return
            self.save_review = self._read_save_review()[-1]
            self.error = 'Review the saved calibration after restart; no operation was replayed.'
        except Exception as error:
            self.save_review_required = True
            if not self.request:
                self.save_review_origin_unknown = True
                self.request, self.sequence = uuid.uuid4().hex, 0
            self.state, self.error = 'save_review', str(error)[:512]

    def cmd_save_review(self, gcmd):
        session, request = gcmd.get('SESSION', ''), gcmd.get('REQUEST', '')
        action, token = gcmd.get('ACTION', ''), gcmd.get('REVIEW', '')
        if session != self.calibration.session or request != self.request or not request:
            raise gcmd.error('Probe save review session changed: ' + ('SESSION differs from calibration session' if session != self.calibration.session else 'REQUEST differs from editor' if request != self.request else 'REQUEST is empty'))
        if action not in ('REVIEW', 'ACK', 'RETAIN') or (action == 'REVIEW' and token):
            raise gcmd.error('Unsupported probe save review action')
        raw_sequence = gcmd.get('SEQ', '')
        if not isinstance(raw_sequence, str) or not re.fullmatch(r'[1-9][0-9]{0,8}', raw_sequence):
            raise gcmd.error('Probe save review requires a positive sequence')
        sequence = int(raw_sequence)
        identity = (session, request, sequence, action, token)
        if identity == self.save_review_last:
            return  # Return the retained result; never replay a lost reply.
        if sequence != self.save_review_sequence + 1:
            raise gcmd.error('Probe save review sequence changed: SEQ=%s; expected %s' % (sequence, self.save_review_sequence + 1))
        self.save_review_sequence, self.save_review_last = sequence, identity
        self.save_review_result = {'session': session, 'request': request,
                                   'sequence': sequence, 'action': action,
                                   'state': 'pending', 'error': ''}
        try:
            self._run_save_review(gcmd, request, action, token)
        except Exception as error:
            result = self.save_review_result
            if result['state'] != 'unknown':
                result['state'] = 'refused'
            result['error'] = str(error)[:512]
            raise
        self.save_review_result['state'] = 'complete'

    def _run_save_review(self, gcmd, request, action, token):
        if not self.save_review_required or self.state not in ('save_review', 'unknown', 'saved'):
            raise gcmd.error('No completed probe save attempt is available for review')
        # Reviewing evidence never reserves or moves the printer.
        store, path, disk, loaded, pending, review = self._read_save_review()
        source_request = review['record']['request']
        if source_request != request and source_request != self.restored_save_request:
            if (action != 'REVIEW' or not self.save_review_origin_unknown
                    or self.restored_save_request or self.receipt is not None):
                raise gcmd.error('Probe save evidence changed')
            # Startup could not read an identity. Only an explicit read-only
            # review may bind subsequently restored evidence to this review hold.
            # Keep the live request identity stable for native result correlation.
            self.restored_save_request = source_request
        if action == 'REVIEW':
            self.save_review_confirmable = True
            self.save_review = review
            self.state = 'save_review'
            self.error = ('Loaded configuration matches the recorded save. ACK acknowledges this review only.'
                          if review['configuration_matches'] else
                          'Only the probe offset differs. RETAIN keeps the current loaded offset without saving.'
                          if review['retainable'] else
                          'Loaded configuration does not match the recorded save. Keep the evidence for recovery.')
            return
        if (not self.save_review_confirmable or self.save_review is None or self.save_review.get('token') != token
                or review['token'] != token
                or not (review['retainable'] if action == 'RETAIN' else review['configuration_matches'])):
            reason = ('review has not been confirmed' if not self.save_review_confirmable else
                      'review snapshot is unavailable' if self.save_review is None else
                      'REVIEW differs from reviewed token' if self.save_review.get('token') != token else
                      'configuration review token changed' if review['token'] != token else
                      'configuration is not retainable' if action == 'RETAIN' else
                      'loaded configuration does not match saved evidence')
            raise gcmd.error('Probe save review changed or configuration does not match: ' + reason)
        self.save_review_result['state'] = 'unknown'
        if action == 'RETAIN':
            store.acknowledge(path, disk, loaded, pending, review['review'], retain=True)
        else:
            store.acknowledge(path, disk, loaded, pending, review['review'])
        self.save_ack_token = token
        self.save_review = review
        self.save_review['outcome'] = 'acknowledged'
        self.save_review_required = False
        self.state, self.error = 'save_acknowledged', 'Save review acknowledged; original evidence retained.'
        if action == 'RETAIN':
            self.error = 'Current probe offset retained; original save evidence preserved. No configuration was written.'
        if self.receipt is not None:
            self.receipt.invalidate()

    @staticmethod
    def _current_actor():
        from greenlet import getcurrent
        return getcurrent()

    def _capture_preparation_scope(self, gcmd):
        material = self.printer.lookup_object('wm_material', None)
        return {'actor': self._current_actor(), 'session': self.calibration.session,
                'request': self.request, 'gcmd': gcmd, 'material': material,
                'generation': getattr(material, '_command_generation', None),
                'material_session': getattr(material, 'session_id', None),
                'owners': tuple((name, self.printer.lookup_object(name, None))
                                for name in ('wm_material', 'wmp_recovery', 'openace', 'AFC')),
                'receipt': None}

    def _preparation_owned(self, scope):
        return (self._preparation_scope is scope
                and getattr(self.calibration, 'probe_editor', None) is self
                and self.calibration.session == scope['session']
                and self.request == scope['request']
                and getattr(scope['material'], '_command_generation', None) == scope['generation']
                and getattr(scope['material'], 'session_id', None) == scope['material_session']
                and all(self.printer.lookup_object(name, None) is owner
                        for name, owner in scope['owners'])
                and self.receipt is scope['receipt'])

    def _require_preparation_owner(self, scope):
        if not self._preparation_owned(scope):
            raise scope['gcmd'].error('Probe preparation request or owner changed')

    def handle_stop(self, request):
        # Reactor callback: no G-code mutex, motion, or cleanup here.
        scope = self._preparation_scope
        if (scope is None or not self._preparation_owned(scope)
                or request.get_str('session') != scope['session']
                or request.get_str('request') != scope['request']
                or self.state not in ('preparing', 'stopping')
                or self.printer.lookup_object('openace', None) is not None
                or self.printer.lookup_object('AFC', None) is not None):
            raise request.error('Probe preparation request or owner changed')
        self.stop_requested = True
        request.send({'session': scope['session'], 'request': scope['request'],
                      'state': 'requested'})

    def check_operation_boundary(self, label, gcmd=None):
        scope = self._preparation_scope
        # A reactor callback may run while G-code yields. Only its command
        # greenlet may consume this request or unwind the preparation stack.
        if scope is None or scope.get('actor') is not self._current_actor():
            return
        self._require_preparation_owner(scope)
        command = gcmd if gcmd is not None else scope['gcmd']
        self.calibration._check(command)  # Real faults take precedence.
        self._require_preparation_owner(scope)
        if self.state == 'preparing' and self.stop_requested:
            self.stop_checkpoint_hit = True
            self.stop_exception = command.error('Probe preparation stop requested')
            raise self.stop_exception

    def cmd_prepare_check(self, gcmd):
        self.check_operation_boundary('probe preparation stage', gcmd)

    def _prepare_with_stop_reporting(self, prepare):
        # Keep command_error cleanup events and normal fault reporting. Suppress
        # only this request's exact expected unwind exception, never matching text.
        original = getattr(self.gcode, '_respond_error', None)
        if original is None:
            return prepare()
        session, request = self.calibration.session, self.request
        scope = self._preparation_scope
        def report(message):
            if (self.stop_exception is not None
                    and sys.exc_info()[1] is self.stop_exception
                    and self.state == 'preparing' and self.stop_requested
                    and self.calibration.session == session and self.request == request
                    and scope is not None and self._preparation_owned(scope)):
                return
            return original(message)
        self.gcode._respond_error = report
        try:
            return prepare()
        finally:
            if self.gcode._respond_error is report:
                self.gcode._respond_error = original

    def _finish_preparation_stop(self, gcmd, scope):
        self._require_preparation_owner(scope)
        self.state = 'stopping'
        try:
            # Drain directly: vendor quick-stop can silently skip M400.
            self.printer.lookup_object('toolhead').wait_moves()
            self._require_preparation_owner(scope)
            self.calibration._check(gcmd)
            self._require_preparation_owner(scope)
            receipt = scope['receipt']
            if receipt is not None:
                if receipt.state == 'preparation_failed':
                    receipt.abort_failed_preparation(gcmd)
                else:
                    receipt._require('editing')
                    receipt.helper.cmd_ABORT(gcmd)
                self._require_preparation_owner(scope)
                if receipt.state != 'aborted':
                    raise gcmd.error('Probe helper abort was not confirmed')
            elif 'ACCEPT' in self.gcode.ready_gcode_handlers:
                raise gcmd.error('Unresolved probe helper after preparation stop')
            try:
                from .wmp_stop_points import finish_cancelled_toolchange
            except ImportError:
                from wmp_stop_points import finish_cancelled_toolchange
            finish_cancelled_toolchange(self.printer, lambda: self._preparation_owned(scope))
            self.state, self.error = 'aborted', ''
        except Exception as error:
            if self._preparation_owned(scope):
                self.state, self.error = 'unknown', str(error)[:512]
            raise

    def _run_preparation(self, gcmd, session):
        scope = self._capture_preparation_scope(gcmd)
        self._preparation_scope = scope
        started = False
        def admit():
            self._require_preparation_owner(scope)
            self._admit(gcmd)
            self._require_preparation_owner(scope)
        def prepare():
            nonlocal started
            self._require_preparation_owner(scope)
            started = True
            self._prepare_with_stop_reporting(
                lambda: self.gcode.run_script_from_command('_WMP_PROBE_CALIBRATE'))
        def retain(receipt):
            if self._preparation_owned(scope):
                scope['receipt'] = self.receipt = receipt
        try:
            try:
                self._require_preparation_owner(scope)
                self._admit(gcmd, fresh_action=True)
                self._require_preparation_owner(scope)
                self.preparation_config = self._pending_config()
                self._executing = True
                receipt = ProbeEditorReceipt.prepare(session, self.gcode,
                    lambda: self.calibration.session, admit, prepare, failed=retain)
                self._require_preparation_owner(scope)
                scope['receipt'] = self.receipt = receipt
            except Exception as error:
                if not self._preparation_owned(scope):
                    raise
                if self.stop_checkpoint_hit and error is self.stop_exception:
                    self._finish_preparation_stop(gcmd, scope)
                    return
                self.state, self.error = ('failed' if started else 'rejected'), str(error)[:512]
                self.action_refused = not started
                self.preparation_error = self.error
                raise
            if self.stop_requested:
                self._finish_preparation_stop(gcmd, scope)
            else:
                self.state = 'editing'
        finally:
            if self._preparation_scope is scope:
                self._preparation_scope, self._executing = None, False

    def _save_with_restart_receipt(self):
        # The retained SAVE_CONFIG writer requests firmware_restart only after
        # replacing printer.cfg. A normal dispatcher return can instead mean
        # quick-stop skipped the command: require the writer's completion boundary.
        original = self.gcode.request_restart
        confirmed = False
        def restart(result):
            nonlocal confirmed
            if result != 'firmware_restart':
                raise ValueError('Unexpected probe save restart type')
            original(result)
            confirmed = True
        self.gcode.request_restart = restart
        try:
            self.gcode.run_script_from_command('SAVE_CONFIG')
            if not confirmed:
                raise ValueError('Probe save completion was not confirmed; do not retry automatically')
        finally:
            if self.gcode.request_restart is restart:
                self.gcode.request_restart = original

    def _pending_config(self):
        config = self.printer.lookup_object('configfile')
        parser = config.autosave.fileconfig
        return (copy.deepcopy(config.status_save_pending), config.save_config_pending,
                {section: dict(parser.items(section, raw=True)) for section in parser.sections()},
                dict(parser.defaults()))

    def failure_discard_reason(self):
        if self.state not in ('failed', 'discarding', 'unknown'):
            return 'editor state=' + str(self.state)[:80] + '; expected failed, discarding or unknown'
        if self.receipt is not None:
            return 'probe receipt owns pending edits; use its bound Abort or Discard action'
        if self._executing:
            return 'probe editor command is still active'
        probe = self.printer.lookup_object('manual_probe', None)
        if getattr(probe, 'status', {}).get('is_active') is True:
            return 'manual_probe.is_active=True; helper is still active'
        for name in ('ACCEPT', 'NEXT', 'ABORT', 'TESTZ'):
            if name in getattr(self.gcode, 'ready_gcode_handlers', {}):
                return 'manual probe handler is still active: ' + name
        return ''

    def failure_discard_available(self):
        return not self.failure_discard_reason()

    def _discard_preparation_failure(self, gcmd, identity, sequence):
        reason = self.failure_discard_reason()
        if reason:
            raise gcmd.error('Cannot dismiss probe result: ' + reason)
        self.sequence, self.last = sequence, identity
        self.action_refused = False
        # Dismiss only this historical result. Do not drain motion, change pending
        # settings or require physical readiness for a read-only UI exit.
        self.state, self.error = 'discarded', self.preparation_error

    def busy(self):
        # External ACCEPT/ABORT can finish the helper while UI still says editing.
        if self._executing:
            return True
        probe = self.printer.lookup_object('manual_probe', None)
        if getattr(probe, 'status', {}).get('is_active') is True:
            return True
        return any(name in getattr(self.gcode, 'ready_gcode_handlers', {})
                   for name in ('ACCEPT', 'NEXT', 'ABORT', 'TESTZ'))

    def _retire_result(self):
        # Explicit BEGIN replaces history, not current pending configuration.
        # Retired requests keep delayed BEGIN commands from becoming retries.
        if self.request:
            self._retired_requests.add(self.request)
        if self.receipt is not None:
            self.receipt.invalidate()
        self.save_review_required = False
        self.save_review = self.save_review_result = self.save_review_last = None
        self.save_review_sequence = 0
        self.calibration.failure = ''

    def get_status(self):
        result = {'protocol': 1, 'session': self.calibration.session,
                  'request': self.request, 'state': self.state, 'error': self.error,
                  'sequence': self.sequence, 'stop_requested': self.stop_requested,
                  'stop_protocol': 1, 'action_refused': self.action_refused,
                  'save_review_required': self.save_review_required, 'save_review_protocol': 2,
                  'save_review_sequence': self.save_review_sequence, 'save_retain_protocol': 1,
                  'save_review_confirmable': self.save_review_confirmable,
                  'diagnostic_warning': self.diagnostic_warning}
        if self.save_review_result is not None:
            result['save_review_result'] = dict(self.save_review_result)
        if self.save_review is not None and 'token' in self.save_review:
            result['save_review'] = {key: self.save_review[key] for key in ('token', 'configuration_matches', 'outcome', 'loaded_offset', 'retainable',
                                                                                   'differences', 'difference_count', 'pending_changes')}
            result['save_review'].update(section=self.save_review['record']['section'],
                                         offset=self.save_review['record']['offset'])
        result.update(binding_valid=True, z_position=None)
        if self.receipt is None and self.failure_token and self.state in ('failed', 'discarding', 'discarded', 'unknown'):
            result.update(token=self.failure_token,
                          failure_discard_available=self.failure_discard_available())
        if self.state == 'accepted' and self.config_change is not None:
            result['config_conflict'] = self.config_change.conflict_review()
        if self.receipt:
            receipt = self.receipt
            result.update(token=receipt.token, position=receipt.position, receipt_state=receipt.state,
                          cleanup_available=receipt.cleanup_available())
            try:
                session, helper = receipt.current()
                valid = (session == receipt.session and helper is receipt.helper
                    and helper.finalize_callback is receipt.callback
                    and (receipt.state != 'accepted' or
                         helper.manual_probe.status is receipt._accepted_probe_status))
                result['binding_valid'] = valid
                position = helper.manual_probe.status.get('z_position') if valid else None
                if isinstance(position, (int, float)) and not isinstance(position, bool) and math.isfinite(position):
                    result['z_position'] = position
            except (AttributeError, KeyError, TypeError, ValueError):
                result['binding_valid'] = False
        return result

    def _admit(self, gcmd, fresh_action=False):
        if self.calibration.active:
            raise gcmd.error('Calibration command is currently running; stop it before starting another')
        self.calibration._check(gcmd, fresh_action=fresh_action)
        if (self.printer.lookup_object('openace', None) is not None
                or self.printer.lookup_object('AFC', None) is not None):
            raise gcmd.error('Managed probe editor owner is not qualified for this configuration: ' + ('openace is present' if self.printer.lookup_object('openace', None) is not None else 'AFC is present'))
        material = self.printer.lookup_object('wm_material', None)
        if material is None:
            raise gcmd.error('Managed probe editor requires material admission')
        material._restart_requested(None, probe_editor=self)

    def cmd_run(self, gcmd):
        if self._executing:
            raise gcmd.error('Probe editor command is currently running')
        try:
            self._run(gcmd)
        except ValueError as error:
            # Klipper treats a raw validation error as an internal shutdown.
            raise gcmd.error(str(error)) from error

    def _run(self, gcmd):
        session = gcmd.get('SESSION', '')
        request = gcmd.get('REQUEST', '')
        action = gcmd.get('ACTION', '')
        token = gcmd.get('TOKEN', '')
        step = gcmd.get('Z', '')
        review = gcmd.get('REVIEW', '')
        sequence = gcmd.get_int('SEQ', minval=0)
        if session != self.calibration.session or not re.fullmatch('[0-9a-f]{32}', request):
            raise gcmd.error('Stale or invalid probe editor request: ' + ('SESSION differs from current calibration session' if session != self.calibration.session else 'REQUEST must contain 32 lowercase hexadecimal characters'))
        if review and action != 'KEEP':
            raise gcmd.error('Unexpected calibration review token')
        identity = (request, action, token, step, sequence, review)
        if identity == self.last:
            return  # Lost response: never repeat preparation, jog or save.
        if action == 'BEGIN':
            if sequence != 0 or token or step or request == self.request or request in self._retired_requests or self.busy():
                reason = ('SEQ must be zero' if sequence != 0 else
                          'TOKEN must be empty' if token else 'Z must be empty' if step else
                          'REQUEST has already been used; start a new request' if request == self.request or request in self._retired_requests else
                          'a manual probe command or helper is currently active; finish or stop it')
                raise gcmd.error('Probe preparation requires a new idle request: ' + reason)
            self._retire_result()
            self.request, self.sequence, self.last = request, 0, identity
            self.save_review_origin_unknown = False
            self.restored_save_request = ''
            self.save_review_confirmable = False
            self.preparation_config, self.failure_token = None, uuid.uuid4().hex
            self.action_refused = False
            self.receipt, self.config_change = None, None
            self.state, self.error = 'preparing', ''
            self.preparation_error = ''
            self.stop_requested = self.stop_checkpoint_hit = False
            self.stop_exception = None
            return self._run_preparation(gcmd, session)
        if (action == 'DISCARD' and self.state in ('failed', 'unknown') and self.receipt is None
                and request == self.request and token == self.failure_token and token
                and sequence == self.sequence + 1 and not step):
            self._discard_preparation_failure(gcmd, identity, sequence)
            return
        if (request != self.request or self.receipt is None or token != self.receipt.token
                or sequence != self.sequence + 1):
            reason = ('REQUEST differs from active editor' if request != self.request else
                      'probe receipt is missing' if self.receipt is None else
                      'TOKEN differs from active receipt' if token != self.receipt.token else
                      'SEQ=%s; expected %s' % (sequence, self.sequence + 1))
            raise gcmd.error('Stale probe editor action: ' + reason)
        if action not in ('JOG', 'ACCEPT', 'ABORT', 'SAVE', 'DISCARD', 'KEEP') or (step and action != 'JOG'):
            raise gcmd.error('Unsupported probe editor action')
        if action == 'JOG' and step not in self.STEPS:
            raise gcmd.error('Unsupported probe adjustment')
        if action not in ('ABORT', 'DISCARD'):
            if self.state != ('accepted' if action in ('SAVE', 'KEEP') else 'editing'):
                raise gcmd.error('Resolve the current probe editor result: action=%s, state=%s; expected %s' % (action, str(self.state)[:80], 'accepted' if action in ('SAVE', 'KEEP') else 'editing'))
        try:
            if action not in ('ABORT', 'DISCARD'):
                self._admit(gcmd)
            cleanup = action == 'ABORT' and self.state == 'failed' and self.receipt.cleanup_available()
            self.receipt._require('preparation_failed' if cleanup else
                                  'accepted' if action in ('SAVE', 'DISCARD', 'KEEP') else 'editing')
            if action == 'SAVE':
                if self.config_change is None:
                    raise gcmd.error('No owned probe configuration result')
                self.config_change.admit_save()
            if action in ('DISCARD', 'KEEP'):
                if self.config_change is None:
                    raise gcmd.error('No owned probe configuration result')
                if action == 'KEEP': self.config_change.admit_keep(review)
                else: self.config_change.admit_discard()
            if action == 'ACCEPT':
                finalizer_owner = getattr(self.receipt.finalizer, '__self__', None)
                section = getattr(finalizer_owner, 'name', None)
                configfile = self.printer.lookup_object('configfile')
                self.config_change = ProbeConfigChange(configfile, section)
        except Exception as error:
            self.sequence, self.last = sequence, identity
            self.action_refused, self.error = True, str(error)[:512]
            raise
        self.sequence, self.last = sequence, identity
        self.action_refused = False
        self.error = self.preparation_error if cleanup else ''
        self._executing = True
        self.state = {'JOG':'jogging', 'ACCEPT':'accepting', 'ABORT':'aborting',
                      'SAVE':'saving', 'DISCARD':'discarding', 'KEEP':'keeping'}[action]
        try:
            if action == 'KEEP':
                self.config_change.keep(review)
                self.receipt.invalidate()
                self.state = 'kept'
                return
            if cleanup:
                self.printer.lookup_object('toolhead').wait_moves()
                self.receipt.abort_failed_preparation(gcmd)
                self.state = self.receipt.state
                return
            if action == 'DISCARD':
                if self.config_change is None:
                    raise gcmd.error('No owned probe configuration result')
                self.config_change.discard()
                self.receipt.invalidate()
                self.state = 'discarded'
                return
            if action == 'SAVE':
                def persist():
                    self.config_change.admit_save()
                    try:
                        self._record_save_intent()
                    except Exception as error:
                        self.diagnostic_warning = ('Probe save evidence could not be recorded: ' + str(error))[:512]
                        logging.exception(self.diagnostic_warning)
                        respond = getattr(gcmd, 'respond_info', None)
                        if respond is not None:
                            respond(self.diagnostic_warning + '. Continuing the explicit configuration save.')
                        self.save_review_required = False
                    self.config_change.admit_save()
                    self.calibration.active = self.calibration._saving = True
                    try:
                        self._save_with_restart_receipt()
                    finally:
                        self.calibration.active = self.calibration._saving = False
                self.receipt.save(session, token, lambda: self._admit(gcmd), persist)
            else:
                self.gcode.run_script_from_command('TESTZ Z=' + step if action == 'JOG' else action)
            if action == 'ACCEPT' and self.receipt.state == 'accepted':
                self.config_change.capture()
            self.state = self.receipt.state
        except Exception as error:
            self.state, self.error = 'unknown', str(error)[:512]
            raise
        finally:
            self._executing = False


