# SPDX-License-Identifier: GPL-3.0-or-later
"""Calibration commands, attempts and heater ownership."""
import logging


import re

import uuid


import os


from contextlib import contextmanager


try:
    from . import wmp_calibration_outcome
    from .wmp_calibration_records import CalibrationSaveRecord
    from .wmp_calibration_checkpoint import Checkpoints
    from .wmp_raw_homing import RawHoming
    from .wmp_calibration_progress import CalibrationProgress
    from .wmp_nozzle_scrub import NozzleScrubCommands
    from .wmp_nozzle_touch import NozzleTouch
    from .wmp_offset_snapshot import OffsetSnapshot
    from .wmp_probe_editor import ProbeEditorCommands
except ImportError:
    import wmp_calibration_outcome
    from wmp_calibration_records import CalibrationSaveRecord
    from wmp_calibration_checkpoint import Checkpoints
    from wmp_raw_homing import RawHoming
    from wmp_calibration_progress import CalibrationProgress
    from wmp_nozzle_scrub import NozzleScrubCommands
    from wmp_nozzle_touch import NozzleTouch
    from wmp_offset_snapshot import OffsetSnapshot
    from wmp_probe_editor import ProbeEditorCommands


class CalibrationHeaterOwnership:
    """Observe target mutations without changing heater API semantics.

    A suspended calibration's reactor callbacks do not share its greenlet.
    PID alter_target calls may retain ownership through the current control,
    but an intervening external target write (even the same value) revokes it.
    """
    def __init__(self, heaters, current_actor):
        self.current_actor = current_actor
        self.contexts, self.records = {}, []
        self.enabled = False
        for heater in heaters.values():
            if any(not callable(getattr(heater, method, None))
                   for method in ('set_temp', 'set_control', 'alter_target')):
                raise ValueError('Heater target API is unavailable')
            if getattr(heater, '_wmp_calibration_target_tracker', None) is not None:
                raise ValueError('Heater target API already has a calibration tracker')
        for heater in heaters.values():
            record = {'heater': heater, 'owner': None, 'control_owner': None,
                      'control': None, 'version': 0}
            self.records.append(record)
            for method in ('set_temp', 'set_control', 'alter_target'):
                original = getattr(heater, method)
                setattr(heater, method, self._wrap(record, method, original))
            heater._wmp_calibration_target_tracker = self
        self.enabled = True

    def _wrap(self, record, method, original):
        def observed(*args, **kwargs):
            if not self.enabled:
                return original(*args, **kwargs)
            actor = self.contexts.get(self.current_actor())
            owner = actor
            if (method == 'alter_target' and owner is None
                    and record['owner'] == record['control_owner']
                    and record['control'] is getattr(record['heater'], 'control', None)):
                owner = record['control_owner']
            record['version'] += 1
            version = record['version']
            previous_target = getattr(record['heater'], 'target_temp', None)
            try:
                result = original(*args, **kwargs)
            except Exception:
                # Retain the original error. A setter which changed its target
                # before failing still changed ownership; a clean validation
                # refusal does not steal the prior operation's heater.
                if (record['version'] == version and previous_target !=
                        getattr(record['heater'], 'target_temp', None)):
                    record['owner'] = owner
                raise
            if record['version'] == version:
                record['owner'] = owner
                if method == 'set_control':
                    record['control'] = getattr(record['heater'], 'control', None)
                    record['control_owner'] = owner
            return result
        return observed

    @contextmanager
    def executing(self, owner):
        actor = self.current_actor()
        previous = self.contexts.get(actor)
        self.contexts[actor] = owner
        try:
            yield
        finally:
            if previous is None:
                self.contexts.pop(actor, None)
            else:
                self.contexts[actor] = previous

    def release(self, owner):
        for record in self.records:
            if record['owner'] == owner:
                record['owner'] = None
            if record['control_owner'] == owner:
                record['control_owner'] = None

    def cool(self, owner):
        errors = []
        for record in self.records:
            if record['owner'] != owner:
                continue
            heater = record['heater']
            try:
                if heater.target_temp:
                    heater.set_temp(0.)
            except Exception as error:
                errors.append(str(error))
        self.release(owner)
        if errors:
            raise RuntimeError('Owned calibration heater cleanup failed: ' + '; '.join(errors))


class CalibrationCommands:
    """Keep separately queued calibration stages within their invocation.

    Sequenced Maintenance attempts can retire a refusal before any execution.
    Failures retire their attempt; a new bound request rechecks live conditions.
    Unbound legacy tails remain stopped until an explicit bound request starts.
    """
    COMMAND = re.compile(
        r'(?:G28|G29|M400|M106 S255|G1 X150 Y150|SHAPER_CALIBRATE|'
        r'PARK_CURRENT_TOOL|SAVE_CONFIG|_WMP_CALIBRATION_TOOL T=[0-3]|'
        r'PID_CALIBRATE HEATER=extruder[1-3]? TARGET=220|'
        r'NOZZLE_PREPARE S=(?:[1-9][0-9]?|[12][0-9]{2}|300) T=[0-3]|'
        r'NOZZLE_CALIBRATE_TOOL_OFFSET T=[0-3]|RAPID_MODE T=[0-3]|'
        r'_WMP_SCRUB_HEAD T=[0-3]|_WMP_SCRUB_HEAT T=[0-3]|_WMP_SCRUB_COOL(?: T=[0-3])?|'
        r'_WMP_SCRUB_END|_WMP_SCRUB_ATTENTION VALUE=[01]|_WMP_OFFSETS_RESTORE)')
    RAPID_MODE = re.compile(r'RAPID_MODE T=([0-3])')

    def __init__(self, printer, gcode, config=None):
        self.printer, self.gcode = printer, gcode
        self.failure = ''
        self.session = uuid.uuid4().hex
        self.checkpoint = ''
        self.active = False
        self._saving = False
        self._early_save_admitted = False
        self.save_result = {'protocol': 1, 'state': 'unconfirmed', 'session': '', 'request': '', 'error': ''}
        self._save_requests = set()
        self._attempts = {}  # Legacy v1 tombstones; never evict replay protection.
        self._ticket_counter = 0
        self._ticket_attempt = None
        self._current_attempt = None
        self._pending_cancel = None  # At most one advertised next-ticket cancellation.
        self.executing = None  # The bound attempt whose command is executing.
        self.checkpoints = Checkpoints(self)
        self.raw_homing = RawHoming(self)
        self.attempt_result = {}
        self._heater_ownership = None
        self._heater_ownership_error = 'heater tracking not initialized'
        register = getattr(printer, 'register_event_handler', None)
        if callable(register):
            register('klippy:ready', self._restore_save_result)
            register('klippy:ready', self._initialize_heater_ownership)
            register('klippy:ready', self.raw_homing.install)
        gcode.register_command('_WMP_CALIBRATION_COMMAND', self.cmd_run,
                               desc='Execute a stock calibration stage with failure latching')
        gcode.register_command('_WMP_HOME_COMMAND', self.cmd_home,
                               desc='Execute one ticket-bound standalone homing request')
        self.progress = CalibrationProgress(self)
        self.nozzle_scrub = NozzleScrubCommands(self, config)
        self.nozzle_touch = NozzleTouch(self, config)
        self.offset_snapshot = OffsetSnapshot(self)
        self.probe_editor = ProbeEditorCommands(self)
        webhooks = self.printer.lookup_object('webhooks', None)
        if webhooks is not None:
            webhooks.register_endpoint('wmp/calibration/cancel', self.handle_cancel)
        gcode.register_command('_WMP_OPERATION_STOP_POINT', self.cmd_stop_point,
                               desc='Observe operation cancellation outside native homing strokes')

    def cmd_stop_point(self, gcmd):
        phase = gcmd.get('PHASE', '')
        labels = {'before_z_homing': 'before Z homing',
                  'before_z_positioning': 'before Z homing positioning',
                  'tool_homed': 'after tool-service homing',
                  'tool_z_homed': 'after tool-service Z reference',
                  'before_tool_dock': 'before tool docking',
                  'tool_docked': 'after verified tool docking',
                  'before_tool_wipe': 'before nozzle wiping',
                  'tool_wiped': 'after nozzle wiping'}
        if phase not in labels:
            raise gcmd.error('Unknown operation stop point PHASE=' + str(phase)[:80])
        try:
            from .wmp_stop_points import check_operation_boundary
        except ImportError:
            from wmp_stop_points import check_operation_boundary
        check_operation_boundary(self.printer, labels[phase], phase)

    def handle_cancel(self, request):
        # Record intent on the reactor. Cleanup belongs to a serialized command
        # owner, including when a brush run is held between commands.
        session, identity, ticket = (request.get_str(key) for key in ('session', 'request', 'ticket'))
        if (session != self.session or not re.fullmatch('[0-9a-f]{32}', identity)
                or not re.fullmatch('[1-9][0-9]{0,255}', ticket)
                or self.printer.lookup_object('openace', None) is not None
                or self.printer.lookup_object('AFC', None) is not None):
            raise request.error('Calibration attempt or owner changed')
        attempt = self._current_attempt
        selected = (session, identity, ticket)
        if (attempt is None or identity != attempt['request'] or ticket != attempt.get('ticket')):
            if (self.active or self._saving or ticket != str(self._ticket_counter + 1)
                    or attempt is not None and identity == attempt['request']
                    or self._pending_cancel not in (None, selected)):
                raise request.error('Calibration attempt or owner changed')
            # The first queued stage still consumes its own ticket, but cannot
            # execute hardware. This slot cannot cancel a different request.
            self._pending_cancel = selected
        else:
            if self._saving or attempt['state'] not in ('pending', 'failed'):
                raise request.error('Calibration attempt is not cancelable')
            if attempt['state'] == 'failed' and not attempt.get('cancel_requested'):
                raise request.error('Calibration attempt already failed')
            attempt['cancel_requested'] = True
            callback = getattr(self.printer.get_reactor(), 'register_callback', None)
            if (not self.active and callable(callback) and attempt['state'] == 'pending'
                    and not attempt.get('cancel_callback_pending', False)):
                attempt['cancel_callback_pending'] = True
                callback(lambda eventtime: self._idle_cancel_callback(selected))
        request.send({'session': session, 'request': identity, 'ticket': ticket, 'state': 'requested'})

    def _cancel_before_execution(self, attempt):
        self._current_attempt = self.attempt_result = attempt
        self.failure = ('Homing' if attempt.get('operation') == 'home' else 'Calibration') + ' cancelled before its first command'
        attempt.update(state='failed', error=self.failure, cancel_phase='before first command',
                       cancel_cleanup={'state': 'complete', 'offsets': 'not_needed',
                                       'park': 'not_moved', 'error': ''})

    def _idle_cancel_callback(self, selected):
        try:
            self._finish_idle_cancel(selected)
        except Exception as error:
            logging.exception('Calibration cancellation callback could not finish')
            attempt = self._current_attempt
            if attempt is not None and selected == (self.session, attempt['request'], attempt.get('ticket')):
                self.failure = 'Calibration cancellation cleanup unconfirmed: ' + str(error)[:256]
                attempt.update(state='failed', error=self.failure,
                               cancel_cleanup={'state': 'incomplete', 'offsets': 'unconfirmed',
                                               'park': 'unconfirmed', 'error': self.failure})
        finally:
            attempt = self._current_attempt
            if attempt is not None and selected == (self.session, attempt['request'], attempt.get('ticket')):
                attempt['cancel_callback_pending'] = False

    def _finish_idle_cancel(self, selected):
        # Called later, not in the webhook. A running command can unwind first;
        # recheck the complete binding after acquiring G-code ownership.
        with self.gcode.get_mutex():
            attempt = self._current_attempt
            if (self.active or attempt is None or attempt['state'] != 'pending'
                    or not attempt.get('cancel_requested')
                    or selected != (self.session, attempt['request'], attempt.get('ticket'))):
                return
            if not attempt['executed']:
                self._cancel_before_execution(attempt)
                return
            if (self.printer.is_shutdown() or getattr(self.printer, 'quick_stop_flag', False)
                    or any(self.printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC'))):
                self.failure = 'Printer state or tool owner changed; cancellation cleanup was not run'
                attempt.update(state='failed', error=self.failure,
                               cancel_cleanup={'state': 'incomplete', 'offsets': 'unconfirmed',
                                               'park': 'not_attempted', 'error': self.failure})
                return
            self.active, self.executing = True, attempt
            self.failure = 'Calibration cancellation requested; stopped between commands'
            wmp_calibration_outcome.fail_attempt(attempt, self.failure)
            try:
                self._cleanup_failed_heaters(attempt['request'])
                self._cleanup_cancelled_attempt(attempt)
            finally:
                self.active, self.executing = False, None
                self.progress.idle()

    def check_cancel(self, label, attempt=None):
        # Call only outside atomic pickup/dock strokes and outside G28's
        # motor-off-on-command-error handler. The wrapper owns cleanup.
        implicit = attempt is None
        attempt = self.executing if implicit else attempt
        if attempt is None or not attempt.get('cancel_requested'):
            return
        if implicit:
            # A reactor callback may run while the command greenlet yields.
            # Its unrelated motion must not consume this operation's stop.
            tracker = self._heater_ownership
            if (tracker is None or not tracker.enabled or
                    tracker.contexts.get(tracker.current_actor()) != attempt['request']):
                return
        if (attempt is self.executing and
                attempt.get('cancel_cleanup', {}).get('state') == 'running'):
            return  # Only the synchronous cleanup owner may finish its park.
        if attempt.get('operation') == 'home':
            self._check()  # A concurrent physical fault takes precedence over Cancel.
        attempt['cancel_phase'] = label[:160]
        error = getattr(self.printer, 'command_error', RuntimeError)
        name = 'Homing' if attempt.get('operation') == 'home' else 'Calibration'
        raise error(name + ' cancellation requested; stopped ' + label[:160])

    def _initialize_heater_ownership(self):
        if self._heater_ownership is not None:
            return  # Ready may be delivered more than once; never wrap twice.
        try:
            import greenlet
            heaters = self.printer.lookup_object('heaters').heaters
            self._heater_ownership = CalibrationHeaterOwnership(heaters, greenlet.getcurrent)
            self._heater_ownership_error = ''
        except Exception as error:
            self._heater_ownership_error = str(error)
            logging.warning('Calibration heater ownership unavailable: %s; selective failure cleanup cannot be confirmed', error)

    @contextmanager
    def _heater_execution(self, owner):
        tracker = self._heater_ownership
        if tracker is None:
            yield
        else:
            with tracker.executing(owner):
                yield

    def _cool_failed_attempt(self, owner):
        if self._heater_ownership is None:
            logging.warning('Calibration failure heater cleanup unavailable: %s; check heater targets', self._heater_ownership_error)
            return
        self._heater_ownership.cool(owner)

    def _cleanup_failed_heaters(self, owner):
        self.nozzle_scrub.attempt_failed(self.failure)
        self.progress.idle()
        try:
            self._cool_failed_attempt(owner)
        except Exception:
            logging.exception('Unable to turn off owned calibration heaters')
            self.printer.invoke_shutdown(
                'Calibration failed and heater cleanup failed. Check the preceding errors before restarting.')

    def _clear_owned_mesh_progress(self, command, attempt):
        """Clear G29's runtime marker when its normal trailing command is skipped."""
        if (command != 'G29' or attempt is None
                or attempt is not self._current_attempt
                or attempt is not self.executing or not self.active
                or any(self.printer.lookup_object(owner, None) is not None
                       for owner in ('openace', 'AFC'))):
            return
        macro = self.printer.lookup_object('gcode_macro G29', None)
        variables = getattr(macro, 'variables', None)
        if isinstance(variables, dict) and 'bed_leveling' in variables:
            # Match SET_GCODE_VARIABLE's copy-on-write semantics. This is not
            # a saved setting or a successful calibration notification.
            macro.variables = dict(variables, bed_leveling=False)

    def _cleanup_cancelled_attempt(self, attempt):
        """No reactor callback calls this. Only the unwound command owner does.

        Never home or force a position for cleanup. A doubtful mount/reference
        leaves the head in place with an explicit incomplete result. No motor
        disable or restart is used, and no unfinished calibration is saved.
        """
        if (attempt is not self._current_attempt or not attempt.get('cancel_requested')
                or attempt.get('cancel_cleanup') is not None):
            return
        result = {'state': 'running', 'offsets': 'not_needed', 'park': 'not_attempted', 'error': ''}
        attempt['cancel_cleanup'] = result
        errors = []
        if attempt.get('cancel_motion_error'):
            errors.append(attempt['cancel_motion_error'])
        if self._heater_ownership is None:
            errors.append('Owned heater cool-down could not be confirmed')
        if attempt.get('offset_stage'):
            snapshot = self.offset_snapshot
            if snapshot.request == attempt['request'] and snapshot.restore():
                result['offsets'] = 'restored'
            else:
                result['offsets'] = 'unconfirmed'
                errors.append('Stored offsets could not be restored; inspect before printing')
        printer = self.printer
        material_owner = printer.lookup_object('wm_material', None)
        material_session = getattr(material_owner, 'session_id', None)
        generation = getattr(material_owner, '_command_generation', 0)
        def finish_toolchange():
            saved = printer.lookup_object('save_variables', None)
            variables = saved.get_status(printer.get_reactor().monotonic()).get('variables', {}) if saved is not None else {}
            if variables.get('changing_tool') is None or variables.get('changing_tool') == 0:
                return
            try:
                from .wmp_stop_points import finish_cancelled_toolchange
            except ImportError:
                from wmp_stop_points import finish_cancelled_toolchange
            result['toolchange'] = 'unconfirmed'
            result['toolchange'] = finish_cancelled_toolchange(printer, lambda:
                attempt is self._current_attempt and attempt is self.executing and self.active
                and getattr(printer.lookup_object('wmp_recovery', None), 'calibration', None) is self
                and printer.lookup_object('wm_material', None) is material_owner
                and getattr(material_owner, 'session_id', None) == material_session
                and getattr(material_owner, '_command_generation', 0) == generation)
        try:
            toolhead = printer.lookup_object('toolhead', None)
            wait = getattr(toolhead, 'wait_moves', None)
            if not callable(wait):
                raise ValueError('Motion completion unavailable; automatic park skipped')
            wait()  # Includes an admitted travel even when every head is docked.
            if attempt.get('operation') == 'home':
                if not attempt.get('cancel_phase'):
                    # A real native G28 fault can disable motors. A concurrent
                    # Cancel alone is not evidence of a safe held boundary.
                    raise ValueError('Homing failed before a confirmed cancellation boundary; motor holding is unconfirmed')
                if printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False):
                    raise ValueError('Printer is stopped; homing hold could not be confirmed')
                if any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC')):
                    raise ValueError('Tool owner changed; homing hold could not be confirmed')
                if errors:
                    raise ValueError('; '.join(errors))
                finish_toolchange()
                result.update(state='complete', park='held', error='')
                return
            if attempt.get('cancel_motion_error'):
                raise ValueError('Vibration cleanup unconfirmed; automatic park skipped')
            if printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False):
                raise ValueError('Printer is stopped; automatic park skipped')
            if any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC')):
                raise ValueError('Tool owner changed; automatic park skipped')
            now = printer.get_reactor().monotonic()
            material = printer.lookup_object('wm_material', None)
            observe = getattr(material, '_attachment', None)
            if not callable(observe):
                raise ValueError('Head attachment unavailable; automatic park skipped')
            attachment = observe(now)
            variables = printer.lookup_object('save_variables').get_status(now)['variables']
            if variables.get('fail_flag', 0) != 0:
                raise ValueError('Coupling fault unresolved; automatic park skipped')
            if attachment == {'state': 'empty', 'head': ''}:
                if variables.get('current_extruder') != 99:
                    raise ValueError('Saved head and attachment disagree; automatic park skipped')
                result['park'] = 'already_docked'
            else:
                toolhead = printer.lookup_object('toolhead')
                if any(axis not in toolhead.get_status(now)['homed_axes'] for axis in 'xyz'):
                    raise ValueError('Homing incomplete; automatic park skipped')
                recovery = printer.lookup_object('wmp_recovery', None)
                if recovery is None or not recovery.get_status(now).get('z_reference_valid', False):
                    raise ValueError('Z reference unverified; automatic park skipped')
                variables = printer.lookup_object('save_variables').get_status(now)['variables']
                head = variables.get('current_extruder')
                if (type(head) is not int or head not in range(4)
                        or attachment != {'state': 'attached', 'head': 'h%d' % head}
                        or variables.get('fail_flag', 0) != 0):
                    raise ValueError('Head attachment or coupling fault unverified; automatic park skipped')
                # The existing shared dock path keeps its guards and atomic
                # lock/unlock strokes. It must not silently home for cleanup.
                self.gcode.run_script_from_command('PARK_CURRENT_TOOL')
                toolhead.wait_moves()
                now = printer.get_reactor().monotonic()
                saved = printer.lookup_object('save_variables').get_status(now)['variables']
                if (observe(now) != {'state': 'empty', 'head': ''}
                        or saved.get('current_extruder') != 99 or saved.get('fail_flag', 0) != 0):
                    raise ValueError('Docking did not confirm an empty carriage and clear coupling state')
                result['park'] = 'parked'
            finish_toolchange()
        except Exception as error:
            result['park'] = 'unconfirmed'
            errors.append(str(error)[:256])
        result['error'] = '; '.join(errors)[:512]
        result['state'] = 'incomplete' if errors else 'complete'
        self.nozzle_scrub.cancel_cleanup_result(attempt['request'], not errors, result['error'])

    def _save_store(self):
        path = os.path.realpath(self.printer.get_start_args()['config_file'])
        return CalibrationSaveRecord(os.path.join(os.path.dirname(path), 'wmp_calibration_save.json')), path

    def _restore_save_result(self):
        # Only on Ready: status polling must never parse configuration files.
        try:
            store, path = self._save_store()
            record = store.read()
            if record is None:
                return
            self.save_result.update(session=record['session'], request=record['request'],
                                    state='unconfirmed', error='Saved values could not be confirmed')
            config = self.printer.lookup_object('configfile')
            _, autosave = config._find_autosave_data(config._read_config_file(path))
            parser = config._build_config_wrapper(autosave, path).fileconfig
            disk = {section: dict(parser.items(section, raw=True)) for section in parser.sections()}
            if (record['session'] != self.session
                    and store.verify(record, path, disk, config.status_raw_config, config.status_save_pending)):
                self.save_result.update(state='confirmed', error='')
        except Exception as error:
            self.save_result.update(state='unconfirmed', error=str(error)[:512])

    def _discard_save_evidence(self, store):
        # Best effort: failure of a diagnostic cleanup must not replace the
        # actual SAVE_CONFIG error or veto a requested configuration write.
        if store is None:
            return ''
        try:
            store.discard()
        except Exception as error:
            logging.warning('Unable to discard calibration save evidence: %s', error)
            return '; previous diagnostic evidence could not be removed: ' + str(error)[:160]
        return ''

    def _save_evidence_warning(self, store, error):
        warning = ('Calibration save evidence unavailable: ' + str(error)[:256]
                   + self._discard_save_evidence(store))
        self.save_result.update(state='unconfirmed', error=warning)
        logging.warning('%s; configuration save result must be checked after restart', warning)

    def _prepare_save(self, gcmd, request):
        # cmd_run calls this only after _attempt validated exact ticket,
        # session, request and sequence; do not expose it as a standalone writer.
        attempt = self._ticket_attempt if gcmd.get('TICKET', None) is not None else None
        if attempt is not None:
            # A consumed ticket is forever ineligible after supersession; its
            # one-shot save marker needs no process-lifetime request set.
            if attempt.get('save_attempted'):
                raise gcmd.error('Calibration save request was already attempted')
            attempt['save_attempted'] = True
        else:
            if request in self._save_requests or len(self._save_requests) >= 1024:
                raise gcmd.error('Calibration save request was already attempted' if request in self._save_requests else
                                 'Legacy calibration save history is full; update the WM+ screen for bounded calibration tickets, or restart Klipper for this older client')
            self._save_requests.add(request)
        self.save_result.update(session=self.session, request=request, state='pending', error='')
        store = record = None
        evidence_ok = False
        try:
            # Path resolution and snapshot extraction are diagnostic work too.
            # Actual SAVE_CONFIG admission and its own writer still run below.
            store, path = self._save_store()
            config = self.printer.lookup_object('configfile')
            parser = config.autosave.fileconfig
            record = {'version': 1, 'session': self.session, 'request': request,
                      'config_path': path, 'state': 'pending',
                      'autosave': {section: dict(parser.items(section, raw=True)) for section in parser.sections()}}
            store.write(record)
            evidence_ok = True
        except Exception as error:
            # Runtime request and stage ownership remain single-use even if
            # diagnostic preparation or storage is unavailable.
            self._save_evidence_warning(store, error)
        return store, record, evidence_ok

    def _save_with_receipt(self, gcmd, store, record, evidence_ok, allow_fail_flag=False):
        original = self.gcode.request_restart
        confirmed = False
        def restart(result):
            nonlocal confirmed
            if result != 'firmware_restart':
                raise gcmd.error('Unexpected calibration save restart type')
            original(result)
            confirmed = True
        self.gcode.request_restart = restart
        try:
            self.gcode.run_script_from_command('SAVE_CONFIG')
            if not confirmed:
                raise gcmd.error('Calibration save writer completion was not confirmed')
            self._check(gcmd, allow_fail_flag=allow_fail_flag)
        except Exception:
            # Includes a writer which changed configuration before failing.
            # Cleanup is diagnostic and must preserve the original exception.
            self._discard_save_evidence(store)
            raise
        finally:
            if self.gcode.request_restart is restart:
                self.gcode.request_restart = original
        if evidence_ok:
            try:
                store.write(dict(record, state='saved'))
            except Exception as error:
                self._save_evidence_warning(store, error)
            else:
                self.save_result.update(state='saved', error='')
        # No positive persisted-result claim after either receipt write fails.
        # The completed writer still completes this attempt; do not run heater
        # failure cleanup or block later actions merely for lost diagnostics.

    def _check(self, gcmd=None, fresh_action=False, allow_fail_flag=False):
        error = gcmd.error if gcmd is not None else getattr(self.printer, 'command_error', RuntimeError)
        if getattr(self, 'identification_blocked', False):
            raise error('Restart Klipper after head identification before calibration')
        now = self.printer.get_reactor().monotonic()
        if self.printer.is_shutdown():
            raise error('Printer is shut down')
        if getattr(self.printer, 'quick_stop_flag', False):
            raise error('Printer quick-stop is active')
        state = self.printer.lookup_object('print_stats').get_status(now)['state']
        paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
        if state in ('printing', 'paused') or paused:
            raise error('Calibration requires an idle printer: ' + ('print_stats.state=' + str(state)[:80] if state in ('printing', 'paused') else 'pause_resume.is_paused=' + repr(paused)[:80]))
        if fresh_action:
            material = self.printer.lookup_object('wm_material', None)
            begin = getattr(material, '_begin_explicit_physical_action', None)
            if begin is not None:
                begin('calibration')
        if allow_fail_flag:
            return  # Early save only; the flag is neither read nor written.
        variables = self.printer.lookup_object('save_variables').get_status(now)['variables']
        if int(variables.get('fail_flag', 0)) != 0:
            raise error('Tool change failed during calibration: fail_flag=%s' % repr(variables.get('fail_flag', 0))[:80])

    def _early_save_available(self, attempt):
        return wmp_calibration_outcome.early_save_available(attempt, self._current_attempt, self.printer)

    def save_admitted(self):
        """True only while this object executes a SAVE_CONFIG it admitted:
        the ordinary save (no failure latched) or the one early save of the
        current failed attempt. The restart gate asks nothing else."""
        return bool(self.active is True and self._saving is True
                    and (self.failure == '' or self._early_save_admitted is True))

    def attempt_status(self):
        return wmp_calibration_outcome.attempt_status(self.attempt_result, self._current_attempt, self.printer)

    def _admit_early_save(self, gcmd, attempt, sequence):
        return wmp_calibration_outcome.admit_early_save(
            gcmd, attempt, sequence, self._current_attempt, self.printer)

    def _attempt(self, gcmd, operation='calibration'):
        if operation == 'home' and any(self.printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC')):
            raise gcmd.error('Standalone homing is owned by another filament manager')
        if operation == 'home' and gcmd.get('TICKET', None) is None:
            raise gcmd.error('Standalone homing requires a ticket-bound request')
        sequence = gcmd.get('SEQUENCE', None)
        ticket = gcmd.get('TICKET', None)
        if (ticket is None and self._ticket_attempt is not None
                and gcmd.get('REQUEST', '') == self._ticket_attempt['request']):
            raise gcmd.error('Known ticket-bound calibration attempt requires its TICKET on every stage and save')
        if ticket is not None and sequence is None:
            raise gcmd.error('Calibration TICKET requires SESSION, REQUEST and ordered SEQUENCE')
        if sequence is None:
            if gcmd.get('REQUEST', '') in self._attempts:
                raise gcmd.error('Known calibration attempt requires an ordered stage binding')
            return None
        session, request = gcmd.get('SESSION', ''), gcmd.get('REQUEST', '')
        if (session != self.session or not re.fullmatch('[0-9a-f]{32}', request)
                or not re.fullmatch('0|[1-9][0-9]{0,5}', str(sequence))):
            reason = ('SESSION differs from current calibration session' if session != self.session else
                      'REQUEST must contain 32 lowercase hexadecimal characters' if not re.fullmatch('[0-9a-f]{32}', request) else
                      'SEQUENCE must be an integer from 0 through 999999 without leading zeroes')
            raise gcmd.error('Invalid calibration attempt binding: ' + reason)
        sequence = int(sequence)
        if ticket is not None:
            if not re.fullmatch('[1-9][0-9]{0,255}', str(ticket)):
                raise gcmd.error('Calibration TICKET must be the positive decimal ticket advertised by current status')
            ticket = int(ticket)
            attempt = self._ticket_attempt
            if ticket == self._ticket_counter:
                if attempt is None or attempt['request'] != request:
                    raise gcmd.error('Calibration ticket belongs to a different attempt; start a new calibration')
            elif ticket == self._ticket_counter + 1:
                if self.active:
                    raise gcmd.error('Calibration command is already running')
                if sequence != 0:
                    raise gcmd.error('New calibration ticket requires SEQUENCE=0; start a new calibration')
                self._ticket_counter = ticket
                attempt = wmp_calibration_outcome.new_attempt(session, request, ticket=str(ticket), operation=operation)
                self._ticket_attempt = attempt
                if self._pending_cancel == (session, request, str(ticket)):
                    attempt['cancel_requested'] = True
                self._pending_cancel = None
            else:
                raise gcmd.error('Calibration ticket is retired or not yet issued; start a new calibration using current status')
        else:
            attempt = self._attempts.get(request)
            if attempt is None:
                if len(self._attempts) >= 1024:
                    raise gcmd.error('Legacy calibration attempt history is full; update the WM+ screen for bounded calibration tickets, or restart Klipper for this older client')
                attempt = wmp_calibration_outcome.new_attempt(session, request)
                self._attempts[request] = attempt
        if attempt.get('operation', 'calibration') != operation:
            raise gcmd.error('Operation kind differs from the admitted request')
        if self.active:
            if attempt is not self._current_attempt:
                attempt.update(state='refused', error='Calibration command is already running')
            # Reentrant/competing requests cannot change the executing attempt
            # or replace its status, including a replay of its sequence zero.
            raise gcmd.error('Calibration command is already running')
        if attempt['state'] != 'pending':
            if self._admit_early_save(gcmd, attempt, sequence):
                # Cleared when cmd_run ends, however it ends.
                self._early_save_admitted = True
                self.attempt_result = attempt
                attempt['next'] = sequence + 1
                return attempt
            raise gcmd.error('Calibration attempt is already stopped: ' + attempt['error'])
        self.attempt_result = attempt
        if sequence != attempt['next']:
            attempt.update(state='refused', error='Calibration stage was missing, repeated, or out of order: SEQUENCE=%s; expected %s' % (sequence, attempt['next']))
            # A missing/replayed stage after execution cannot prove that the
            # partially executed calibration is safe to continue or save.
            # Exception: a gap inside the offset stage still admits the one
            # early save (_admit_early_save); every earlier stage ran in order.
            if attempt['executed']:
                self.failure = attempt['error']
                wmp_calibration_outcome.fail_attempt(attempt, attempt['error'])
            raise gcmd.error(attempt['error'])
        attempt['next'] += 1
        return attempt

    def _note_refused_save(self, gcmd, attempt, error):
        # A bound SAVE_CONFIG refused before its receipt was prepared still
        # names its run, so a screen waiting for that save can stop waiting.
        request = gcmd.get('REQUEST', '')
        if (attempt is None or attempt['request'] != request or gcmd.get('SESSION', '') != self.session
                or gcmd.get('HEX', '').lower() != b'SAVE_CONFIG'.hex()):
            return
        if self.save_result['state'] in ('pending', 'saved'):
            return  # A save is in progress or done; its receipt stands.
        self.save_result.update(session=self.session, request=request, state='unconfirmed',
                                error=str(error)[:512] or 'Calibration save was refused')

    def _reset_owners(self, request):
        """A new attempt is admitted. The scrub's cool-down may refuse the
        command; every owner is still reset, and every published request
        names the new attempt. The first error is raised afterwards."""
        error = None
        for reset in (self.nozzle_scrub.reset, self.progress.reset,
                      self.nozzle_touch.reset, self.offset_snapshot.take):
            try:
                reset(request)
            except Exception as exc:
                if error is None:
                    error = exc
        if error is not None:
            raise error

    def cmd_run(self, gcmd):
        return self._run_operation(gcmd, 'calibration')

    def cmd_home(self, gcmd):
        return self._run_operation(gcmd, 'home')

    def _run_operation(self, gcmd, operation, execute=None, home_axes=None, home_origin='request'):
        try:
            attempt = self._attempt(gcmd, operation)
        except Exception as refusal:
            attempt = self._attempts.get(gcmd.get('REQUEST', '')) if gcmd.get('TICKET', None) is None else self._ticket_attempt
            if (attempt is not None and gcmd.get('TICKET', None) is not None
                    and (attempt['request'] != gcmd.get('REQUEST', '')
                         or attempt['ticket'] != str(gcmd.get('TICKET', None)))):
                attempt = None  # An old ticket cannot clean a newer owner's heaters.
            if (not self.active and attempt is not None
                    and attempt['state'] == 'failed' and attempt['executed']):
                self._cleanup_failed_heaters(attempt['request'])
            self._note_refused_save(gcmd, attempt, refusal)
            raise
        if attempt is not None and attempt.get('cancel_requested') and not attempt['executed']:
            self._cancel_before_execution(attempt)
            return
        # Admitted by _admit_early_save: the one save after a failed offset stage.
        early_save = attempt is not None and attempt['state'] == 'failed'
        if self.failure:
            if attempt is not None and attempt['next'] == 1 and not attempt['executed']:
                self.failure = ''  # Explicit new attempt; recheck live conditions below.
            elif not early_save:
                error = 'Calibration stopped: %s. Start a new calibration attempt after inspecting the printer.' % self.failure
                self._note_refused_save(gcmd, attempt, error)
                raise gcmd.error(error)
        if self.probe_editor.busy() or self.active:
            error = ('Close or resolve the probe editor before another calibration'
                     if self.probe_editor.busy() else 'Calibration command is already running')
            if not self.active:
                self._early_save_admitted = False
            self._note_refused_save(gcmd, attempt, error)
            if attempt is not None:
                if attempt['executed']:
                    wmp_calibration_outcome.fail_attempt(attempt, error)
                    self.failure = error
                    if not self.active:
                        self._cleanup_failed_heaters(attempt['request'])
                else:
                    attempt.update(state='refused', error=error)
            raise gcmd.error(error)
        started = False
        bound_save = False
        command = ''
        try:
            encoded = gcmd.get('HEX', '')
            if not encoded or len(encoded) > 512 or not re.fullmatch('[0-9A-Fa-f]+', encoded):
                raise gcmd.error('Invalid calibration command encoding')
            command = bytes.fromhex(encoded).decode('ascii')
            if operation == 'home':
                if not re.fullmatch(r'G28(?: X| Y| X Y| Z)?', command):
                    raise gcmd.error('Standalone homing accepts only one supported G28 axis command')
            elif not self.COMMAND.fullmatch(command):
                raise gcmd.error('Unsupported calibration command')
            token = gcmd.get('TOKEN', '')
            if token and (command != 'M400' or not re.fullmatch('[0-9a-f]{32}', token)):
                raise gcmd.error('Invalid calibration checkpoint: ' + ('TOKEN only allowed with M400' if command != 'M400' else 'TOKEN must contain 32 lowercase hexadecimal characters'))
            session, request = gcmd.get('SESSION', ''), gcmd.get('REQUEST', '')
            bound_save = command == 'SAVE_CONFIG' and bool(session or request)
            if attempt is None and (session or request) and (command != 'SAVE_CONFIG' or session != self.session
                               or not re.fullmatch('[0-9a-f]{32}', request)):
                raise gcmd.error('Invalid calibration save binding: ' + ('legacy binding only allowed with SAVE_CONFIG' if command != 'SAVE_CONFIG' else 'SESSION differs from calibration session' if session != self.session else 'REQUEST must contain 32 lowercase hexadecimal characters'))
            if attempt is not None and command == 'SAVE_CONFIG' and not attempt['executed']:
                raise gcmd.error('Calibration save requires completed stages from this attempt')
            self._check(gcmd, fresh_action=attempt is not None and not attempt['executed'],
                        allow_fail_flag=early_save)
            if attempt is not None and attempt is not self._current_attempt:
                previous = self._current_attempt
                if previous is not None and previous['state'] == 'pending':
                    previous.update(state='superseded', error='A newer calibration attempt was admitted')
                self._current_attempt = attempt
                self._reset_owners(attempt['request'])
            if not early_save:
                self.check_cancel('before ' + command, attempt)
            save = self._prepare_save(gcmd, request) if bound_save else None
            if command == 'SAVE_CONFIG':
                material = self.printer.lookup_object('wm_material', None)
                if material is not None:
                    # Admit before configfile writes; its later restart event
                    # alone is too late to protect persistent configuration.
                    material._restart_requested(None)
            if attempt is not None:
                if operation == 'home':
                    attempt['home_axes'] = home_axes or '/'.join(axis for axis in 'XYZ' if axis in command.split()[1:]) or 'X/Y/Z'
                    attempt['home_origin'] = home_origin
                attempt['executed'] = True
                wmp_calibration_outcome.note_admitted(attempt, command)
                if command == 'G28' or operation == 'home':
                    self.progress.set_homing()
                elif command == 'PARK_CURRENT_TOOL':
                    self.progress.set_docking()
            self._saving = command == 'SAVE_CONFIG'
            self.active = True
            started = True
            self.executing = attempt
            rapid = self.RAPID_MODE.fullmatch(command) if attempt is not None else None
            if rapid:
                self.progress.measure_started(int(rapid.group(1)))
            with self._heater_execution(attempt['request'] if attempt else 'legacy'):
                with self.checkpoints.stage(command, attempt):
                    if save is not None:
                        self._save_with_receipt(gcmd, *save, allow_fail_flag=early_save)
                    elif execute is not None:
                        execute()  # Raw Home retains the original parsed G28 object.
                    else:
                        self.gcode.run_script_from_command(command)
                    # A soft coupling fault is not a completed measurement.
                    # Check it before the type's atomic checkpoint can publish.
                    if save is None:
                        self._check(gcmd, allow_fail_flag=early_save)
            if attempt is not None and not early_save:
                # A normal, verified return establishes completion. A Cancel
                # delivered immediately afterwards stops the next stage, but
                # must not discard this type's already durable result.
                wmp_calibration_outcome.note_completed(attempt, command)
            if not early_save and command != 'SAVE_CONFIG':
                self.check_cancel('after ' + command, attempt)
            if operation == 'home':
                # One command owns this entire request. It cannot grow into a
                # calibration/save workflow or be replayed after completion.
                attempt.update(state='complete', error='')
                if self._heater_ownership is not None:
                    self._heater_ownership.release(attempt['request'])
                self.progress.idle()
            if token:
                self.checkpoint = token
            if rapid:
                self.progress.measure_completed(int(rapid.group(1)))
            if command == 'SAVE_CONFIG' and not early_save:
                # After an early save the attempt stays failed: its heaters were
                # turned off when it failed and the failure latch stays set.
                if self._heater_ownership is not None:
                    self._heater_ownership.release(attempt['request'] if attempt else 'legacy')
                self.progress.idle()
                if attempt is not None:
                    attempt.update(state='saved', error='')
        except Exception as exc:
            if started:
                self._clear_owned_mesh_progress(command, attempt)
            error = str(exc)[:512] or 'Calibration command failed'
            clean_refusal = attempt is not None and not attempt['executed']
            if clean_refusal:
                attempt.update(state='refused', error=error)
            elif attempt is not None:
                wmp_calibration_outcome.fail_attempt(attempt, error, saving=command == 'SAVE_CONFIG')
            if not clean_refusal:
                self.failure = error
            if bound_save:
                self.save_result.update(state='unconfirmed', error=error)
                self._note_refused_save(gcmd, attempt, error)
            if started or (attempt is not None and attempt['executed']):
                # Includes a later stage refused before dispatch: heaters from
                # earlier stages still belong to this now-stopped attempt.
                self._cleanup_failed_heaters(attempt['request'] if attempt else 'legacy')
                if attempt is not None:
                    self._cleanup_cancelled_attempt(attempt)
            raise
        finally:
            self._saving = False
            self._early_save_admitted = False
            self.active = False
            self.executing = None
            self.progress.measure_ended()


