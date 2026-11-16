# SPDX-License-Identifier: GPL-3.0-or-later
"""Probe configuration edits and manual-probe finalizer ownership."""

import hashlib

import json

import math

import copy


import uuid


class ProbeConfigChange:
    """Own one unsaved probe offset without reverting unrelated calibration."""
    def __init__(self, configfile, section):
        if not isinstance(section, str) or not section:
            raise ValueError('Missing probe configuration section')
        self.configfile, self.section = configfile, section
        parser = configfile.autosave.fileconfig
        self.had_section = parser.has_section(section)
        self.old_value = parser.get(section, 'z_offset') if parser.has_option(section, 'z_offset') else None
        self.old_pending = copy.deepcopy(configfile.status_save_pending)
        self.old_flag = configfile.save_config_pending
        self.value = None
        self.discarded = False

    def capture(self):
        parser = self.configfile.autosave.fileconfig
        pending = self.configfile.status_save_pending.get(self.section)
        if not isinstance(pending, dict) or not isinstance(pending.get('z_offset'), str):
            raise ValueError('Probe finalizer did not stage an offset')
        value = pending['z_offset']
        if not math.isfinite(float(value)) or parser.get(self.section, 'z_offset') != value:
            raise ValueError('Probe finalizer staged an invalid offset')
        self.value = value

    def _unchanged(self):
        parser = self.configfile.autosave.fileconfig
        pending = self.configfile.status_save_pending.get(self.section)
        if (self.discarded or self.value is None or not parser.has_option(self.section, 'z_offset')
                or parser.get(self.section, 'z_offset') != self.value
                or not isinstance(pending, dict) or pending.get('z_offset') != self.value):
            raise ValueError('Pending probe offset changed; explicit review required')

    def admit_save(self):
        self._unchanged()
        # SAVE_CONFIG writes all pending settings, not just this editor's value.
        if self.old_pending or self.configfile.status_save_pending != {self.section: {'z_offset': self.value}}:
            raise ValueError('Other pending calibration changes require review before saving')

    def _discard_plan(self):
        self._unchanged()
        configfile, section = self.configfile, self.section
        pending = copy.deepcopy(configfile.status_save_pending)
        owned = pending[section]
        previous = self.old_pending.get(section, {})
        if previous is None:
            if set(owned) != {'z_offset'}:
                raise ValueError('Pending probe section changed; explicit review required')
            pending[section] = None
        else:
            if 'z_offset' in previous:
                owned['z_offset'] = previous['z_offset']
            else:
                del owned['z_offset']
            if not owned:
                pending.pop(section)
        return pending

    def admit_discard(self):
        self._discard_plan()

    def conflict_review(self):
        if self.discarded or self.value is None:
            return None
        config = self.configfile
        parser = config.autosave.fileconfig
        pending = config.status_save_pending.get(self.section)
        if not isinstance(pending, dict) or not isinstance(pending.get('z_offset'), str):
            return None
        current = pending['z_offset']
        try:
            if (not parser.has_option(self.section, 'z_offset')
                    or current == self.value or not math.isfinite(float(current))
                    or parser.get(self.section, 'z_offset') != current):
                return None
            snapshot = [self.section, self.value, current, config.status_save_pending,
                        config.save_config_pending, dict(parser.defaults()),
                        {section: dict(parser.items(section, raw=True)) for section in parser.sections()}]
            review = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
        except (KeyError, TypeError, ValueError):
            return None
        return {'accepted_offset': self.value, 'current_offset': current, 'review': review}

    def admit_keep(self, review):
        current = self.conflict_review()
        if current is None or current['review'] != review:
            raise ValueError('Pending calibration changed; review it again before keeping it')

    def keep(self, review):
        self.admit_keep(review)
        # Release ownership only. Do not save, restore, or remove newer values.
        self.discarded = True

    def discard(self):
        pending = self._discard_plan()
        configfile, section = self.configfile, self.section
        parser = configfile.autosave.fileconfig
        if self.old_value is None:
            parser.remove_option(section, 'z_offset')
            if not self.had_section and not parser.options(section):
                parser.remove_section(section)
        else:
            parser.set(section, 'z_offset', self.old_value)
        configfile.status_save_pending = pending
        configfile.save_config_pending = bool(pending) or self.old_flag
        self.discarded = True


class ProbeEditorReceipt:
    """One manual-probe finalizer and one save, owned by an editor session.

    This primitive does not start probing or register public commands. The editor
    owner must supply current (backend session, helper) and admission callbacks.
    """
    def __init__(self, session, helper, current):
        if not isinstance(session, str) or not session or not callable(helper.finalize_callback):
            raise ValueError('Invalid probe editor binding')
        self.session, self.helper, self.current = session, helper, current
        self.token = uuid.uuid4().hex
        self.state, self.error, self.position = 'editing', '', None
        self._accepted_probe_status = None
        self._cleanup_active = False
        self._cleanup_check = lambda: False
        original = helper.finalize_callback
        self.finalizer = original

        def finalized(position):
            if self._cleanup_active:
                self._require('preparation_failed')
                if position is not None:
                    raise ValueError('Failed preparation cannot accept a probe position')
                self.state = 'aborting'
                try:
                    original(None)
                except Exception:
                    self.state = 'unknown'
                    raise
                self.state = 'aborted'
                return
            self._require('editing')
            if position is None:
                self.state = 'aborted'
                original(None)
                return
            if (not isinstance(position, (tuple, list)) or len(position) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) for v in position)):
                self.state, self.error = 'failed', 'Invalid accepted probe position'
                raise ValueError(self.error)
            self.state = 'finalizing'
            try:
                original(position)
                self._binding()
            except Exception as error:
                self.state, self.error = 'failed', str(error)[:512]
                raise
            self.position = tuple(position)
            self._accepted_probe_status = helper.manual_probe.status
            self.state = 'accepted'

        self.callback = finalized
        helper.finalize_callback = finalized
        try:
            self._binding()
        except Exception:
            helper.finalize_callback = original
            raise

    @classmethod
    def prepare(cls, session, gcode, current_session, admit, prepare, failed=None):
        """Capture the raw helper registration before Klipper wraps ACCEPT.

        Called by the editor owner under command serialization. Restore the
        registration method on every exit; never rediscover helpers by guessing
        closure cells from the dispatcher's extended-command lambda.
        """
        admit()
        if current_session() != session:
            raise ValueError('Probe editor session changed before preparation')
        names = ('ACCEPT', 'NEXT', 'ABORT', 'TESTZ')
        if any(name in gcode.ready_gcode_handlers for name in names):
            raise ValueError('A manual probe is already active')
        original = gcode.register_command
        captured = []
        owned_handlers = {}

        def register(name, callback, *args, **kwargs):
            if name == 'ACCEPT' and callback is not None and callback != 'dummy':
                helper = getattr(callback, '__self__', None)
                finalizer = getattr(helper, 'finalize_callback', None)
                if (captured or getattr(callback, '__name__', '') != 'cmd_ACCEPT'
                        or getattr(finalizer, '__name__', '') != 'probe_calibrate_finalize'):
                    raise ValueError('Unexpected manual-probe helper during preparation')
                receipt = cls(session, helper, lambda: (current_session(), helper))
                captured.append(receipt)
            result = original(name, callback, *args, **kwargs)
            if captured and name in names and callback is not None and callback != 'dummy':
                receipt = captured[0]
                if getattr(callback, '__self__', None) is receipt.helper:
                    owned_handlers[name] = gcode.ready_gcode_handlers.get(name)
            return result

        def cleanup_check():
            if len(captured) != 1 or 'ACCEPT' not in owned_handlers:
                return False
            receipt = captured[0]
            return (current_session() == session
                and receipt.helper.finalize_callback is receipt.callback
                and gcode.ready_gcode_handlers.get('ACCEPT') is owned_handlers['ACCEPT']
                and all(gcode.ready_gcode_handlers.get(name) is owned_handlers.get(name)
                        for name in names))

        gcode.register_command = register
        try:
            prepare()
            if len(captured) != 1 or 'ACCEPT' not in gcode.ready_gcode_handlers:
                raise ValueError('Probe preparation did not create an editor')
            receipt = captured[0]
            receipt._require('editing')
            # Bind the registered command identity as well as helper identity.
            # The vendor unregisters ACCEPT before it calls its finalizer.
            handler = gcode.ready_gcode_handlers['ACCEPT']
            receipt.current = lambda: (current_session(), receipt.helper
                if gcode.ready_gcode_handlers.get('ACCEPT') in (None, handler) else None)
            return receipt
        except Exception:
            for receipt in captured:
                if failed is not None and receipt.state == 'editing' and cleanup_check():
                    handler = owned_handlers['ACCEPT']
                    receipt.current = lambda: (current_session(), receipt.helper
                        if gcode.ready_gcode_handlers.get('ACCEPT') in (None, handler) else None)
                    receipt.state = 'preparation_failed'
                    receipt._cleanup_check = cleanup_check
                    failed(receipt)
                else:
                    receipt.invalidate()
            raise
        finally:
            gcode.register_command = original

    def _binding(self):
        session, helper = self.current()
        if (session != self.session or helper is not self.helper
                or self.helper.finalize_callback is not self.callback
                or (self.state == 'accepted' and
                    self.helper.manual_probe.status is not self._accepted_probe_status)):
            self.state, self.error = 'invalidated', 'Probe editor session changed'
            raise ValueError(self.error)

    def _require(self, state):
        self._binding()
        if self.state != state:
            raise ValueError('Probe editor is ' + self.state)

    def save(self, session, token, admit, persist):
        # Retire before dispatch: a lost reply must not cause a second write.
        if session != self.session or token != self.token:
            raise ValueError('Stale probe editor save request')
        self._require('accepted')
        admit()
        self._require('accepted')
        self.state = 'saving'
        try:
            persist()
        except Exception as error:
            self.state, self.error = 'unknown', str(error)[:512]
            raise
        self.state = 'saved'

    def cleanup_available(self):
        return self.state == 'preparation_failed' and self._cleanup_check()

    def abort_failed_preparation(self, gcmd):
        if not self.cleanup_available():
            raise gcmd.error('Failed probe helper changed; cleanup is unavailable')
        self._require('preparation_failed')
        self._cleanup_active = True
        try:
            self.helper.cmd_ABORT(gcmd)
            if self.state != 'aborted':
                raise gcmd.error('Failed probe helper cleanup was not confirmed')
        except Exception:
            self.state = 'unknown'
            raise
        finally:
            self._cleanup_active = False

    def invalidate(self):
        self.state, self.error = 'invalidated', 'Probe editor closed or replaced'

    def get_status(self):
        return {'session': self.session, 'token': self.token, 'state': self.state,
                'position': self.position, 'error': self.error}


