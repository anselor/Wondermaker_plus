"""Wondermaker bottom-Z reference, shared by unhomed tool changes and recovery.

Native Z rail homing only: no homing_override, LEVELING pulse, XY or return.
See docs/z-recovery-investigation.md for the machine measurements.
"""
import logging
import hashlib
import json
import math
import copy
import configparser
import io
import re
import uuid
import sys
import os
import tempfile
import fcntl
from contextlib import contextmanager


class BottomZ:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.valid = False
        self.active = False
        self.calibration = CalibrationCommands(self.printer, self.gcode)
        self.identification = None
        self.gcode.register_command('_WMP_IDENTIFY_HEADS', self.cmd_identify,
                                    desc='Identify physical heads and atomically save the complete mapping')
        self.printer.register_event_handler('klippy:connect', self._connect)
        self.printer.register_event_handler('klippy:ready', self._identification_ready)
        self.printer.register_event_handler('klippy:shutdown', self._invalidate)
        self.printer.register_event_handler('homing:home_rails_begin', self._home_begin)
        self.printer.register_event_handler('homing:home_rails_end', self._home_end)
        self.gcode.register_command('_WMP_HOME_Z_BOTTOM', self.cmd_home,
                                    desc='Home Z at the bottom endstop before X/Y travel')

    def _connect(self):
        enable = self.printer.lookup_object('stepper_enable').lookup_enable('stepper_z')
        enable.register_state_callback(self._motor_state)

    def _identification_ready(self):
        from .wmp_identification import IdentificationCommands
        self.identification = IdentificationCommands(self.printer, self.gcode, self.calibration)
        self.identification.check_startup()

    def _invalidate(self, *args):
        self.valid = False

    def _motor_state(self, print_time, enabled):
        if not enabled:
            self.valid = False

    @staticmethod
    def _z_rail(rails):
        return any(s.get_name() == 'stepper_z' for r in rails for s in r.get_steppers())

    def _home_begin(self, homing_state, rails):
        if self._z_rail(rails):
            self.valid = False

    def _home_end(self, homing_state, rails):
        if self._z_rail(rails):
            self.valid = True

    def get_status(self, eventtime):
        axes = self.printer.lookup_object('toolhead').get_status(eventtime)['homed_axes']
        editor = self.calibration.probe_editor
        calibration_active = self.calibration.active or editor.busy()
        active_reason = ''
        if self.calibration.active:
            active_reason = 'Calibration command is running'
        elif calibration_active:
            active_reason = 'Manual probe calibration is active: state=' + str(editor.state)[:80]
        return {'z_reference_valid': self.valid and 'z' in axes, 'homing': self.active,
                'calibration_failed': self.calibration.failure,
                'calibration_active': calibration_active,
                'calibration_active_reason': active_reason,
                'probe_editor': self.calibration.probe_editor.get_status(),
                'calibration_session': self.calibration.session,
                'calibration_checkpoint': self.calibration.checkpoint,
                'calibration_save_result': dict(self.calibration.save_result),
                'calibration_attempt_protocol': 1,
                'calibration_ticket_protocol': 1,
                'calibration_next_ticket': str(self.calibration._ticket_counter + 1),
                'calibration_attempt': dict(self.calibration.attempt_result),
                'identification': self.identification.get_status() if self.identification else
                    {'protocol': 2, 'state': 'idle', 'steps': [], 'failure': '', 'restart_required': False}}

    def cmd_identify(self, gcmd):
        if self.identification is None:
            from .wmp_identification import IdentificationCommands
            self.identification = IdentificationCommands(self.printer, self.gcode, self.calibration)
        self.identification.dispatch(gcmd)

    @contextmanager
    def _native_bottom_reference(self, native):
        # Native homing owns both seeks and the retract. Its step history uses
        # nominal times, while this vendor MCU can execute late steps later.
        # Negative overshoot is impossible for this positive-only seek: anchor
        # the successfully stopped physical endstop instead of reversing retract.
        # This references the actual halt, not a reconstructed switch-edge time;
        # physical stopping overshoot remains a qualification limit. It does not
        # repair host scheduling latency. Native slow second seek is retained.
        namespace = getattr(native.cmd_G28, '__globals__', {})
        original = namespace.get('HomingMove')
        if original is None:  # Injected/non-native command providers have no factory.
            yield
            return
        owner = self

        class BottomReferenceMove(original):
            def homing_move(move, movepos, speed, probe_pos=False,
                            triggered=True, check_triggered=True):
                result = super().homing_move(movepos, speed, probe_pos,
                                            triggered, check_triggered)
                # The native end event also runs on error; only a successful
                # return establishes this correction's authority.
                positions = move.stepper_positions
                if (owner.active and move.printer is owner.printer
                        and not probe_pos and triggered and check_triggered
                        and len(positions) == 1 and all(p.stepper_name == 'stepper_z'
                                              and p.endstop_name == 'z' for p in positions)
                        and any(p.halt_pos < p.trig_pos for p in positions)):
                    position = list(move.toolhead.get_position())
                    position[2] = movepos[2]
                    move.toolhead.set_position(position)
                    for p in positions:
                        logging.warning('WMP bottom Z: negative nominal history correction '
                                        'halt=%s trigger=%s; anchor stopped endstop at Z=%s',
                                        p.halt_pos, p.trig_pos, movepos[2])
                        # Final native rail callbacks must use the same actual
                        # stopped reference, not the invalid nominal history.
                        p.trig_pos = p.halt_pos
                return result

        namespace['HomingMove'] = BottomReferenceMove
        try:
            yield
        finally:
            namespace['HomingMove'] = original

    def cmd_home(self, gcmd):
        # A preflight refusal has performed no homing. Only a failed started
        # home invalidates physical position and must retire queued movement.
        entered = started = False
        try:
            now = self.printer.get_reactor().monotonic()
            ps = self.printer.lookup_object('print_stats').get_status(now)
            paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
            body = self.printer.lookup_object('gcode_macro START_PRINT').get_status(now)['print_body_ready']
            if self.active or paused or (ps['state'] == 'printing' and body):
                raise gcmd.error('Cannot home Z at the bottom: ' + ('bottom-Z command already running' if self.active else 'pause_resume.is_paused=%r' % paused if paused else 'print_stats.state=printing and START_PRINT.print_body_ready=%r' % body))
            settings = self.printer.lookup_object('configfile').get_status(now)['settings']
            z = settings['stepper_z']
            if (settings['printer']['kinematics'] != 'corexy'
                    or z['endstop_pin'] != 'PD2' or z['homing_positive_dir'] is not True):
                raise gcmd.error('Bottom-Z homing requires corexy, physical PD2 and positive Z homing')
            # Native Klipper owns the configured endstop and retract distance;
            # differing valid travel values are not a different homing method.
            minimum = z.get('position_min', 0.)
            maximum = z.get('position_max', z['position_endstop'])
            endstop, retract = z['position_endstop'], z['homing_retract_dist']
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (minimum, maximum, endstop, retract))
                    or not minimum < endstop <= maximum or not 0 < retract < maximum - minimum):
                raise gcmd.error('Bottom-Z homing requires finite native Z bounds and retract within travel')
            inactive = []
            for name in ('LEVELING', 'GANTRY'):
                pin = self.printer.lookup_object('output_pin ' + name).get_status(now)
                if pin['value'] != 1:
                    inactive.append(name)
            if inactive:
                material = self.printer.lookup_object('wm_material', None)
                if (self.calibration.active or self.calibration.probe_editor.busy()
                        or (material is not None and any(material._material_operation_active(kind)
                            for kind in ('filament_operation', 'toolhead_operation')))):
                    raise gcmd.error('Cannot reset bottom-Z trigger pins during an active calibration or material operation')
                # Stock load_cell.cfg declares 1 as both idle and shutdown.
                # Restore that level without the stock low trigger pulse.
                for name in inactive:
                    self.gcode.run_script_from_command('SET_PIN PIN=%s VALUE=1' % name)
                    self.printer.lookup_object('toolhead').wait_moves()
                    observed = self.printer.lookup_object('output_pin ' + name).get_status(
                        self.printer.get_reactor().monotonic()).get('value')
                    if observed != 1:
                        raise gcmd.error('%s idle reset was not confirmed: value=%r; expected 1' % (name, observed))
            entered = True
            self.active = True
            self.valid = False
            self.printer.lookup_object('toolhead').wait_moves()
            # Discard compensation without moving. Native home resets the Z
            # base to the retained homing offset; do not erase tool offsets.
            self.gcode.run_script_from_command('BED_MESH_CLEAR')
            self.gcode.run_script_from_command('STEPPER_DIAG_ENABLE CHIP=stepper_z')
            try:
                native = self.printer.lookup_object('homing')
                started = True
                with self._native_bottom_reference(native):
                    native.cmd_G28(self.gcode.create_gcode_command('G28', 'G28 Z', {'Z': '0'}))
                self.printer.lookup_object('toolhead').wait_moves()
            finally:
                self.gcode.run_script_from_command('STEPPER_DIAG_DISABLE CHIP=stepper_z')
            self.valid = True
            logging.info('WMP recovery: native bottom Z home complete; no XY or upward return')
            gcmd.respond_info('WM+: Z homed at the bottom. The bed remains there; X/Y did not move.')
        except Exception:
            if entered:
                self.valid = False
            if started:
                self.printer.invoke_shutdown('Bottom-Z homing failed. Klipper shut down to block further recovery movement; check the preceding error.')
            raise
        finally:
            if entered:
                self.active = False


class ProbeSaveRecord:
    """Durable evidence, never an instruction to replay a configuration write."""
    LIMIT = 1024 * 1024

    def __init__(self, path):
        self.path = os.path.abspath(path)

    @staticmethod
    def _payload(record):
        if (not isinstance(record, dict) or set(record) != {
                'version', 'session', 'request', 'config_path', 'section',
                'offset', 'autosave', 'before_sha256'}
                or type(record['version']) is not int or record['version'] != 1):
            raise ValueError('Invalid probe save evidence')
        for key in ('session', 'request'):
            if not isinstance(record[key], str) or not re.fullmatch('[0-9a-f]{32}', record[key]):
                raise ValueError('Invalid probe save identity')
        if (not isinstance(record['config_path'], str) or not os.path.isabs(record['config_path'])
                or not isinstance(record['section'], str) or not record['section']
                or not isinstance(record['offset'], str)
                or not math.isfinite(float(record['offset']))
                or not isinstance(record['before_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['before_sha256'])):
            raise ValueError('Invalid probe save configuration identity')
        autosave = record['autosave']
        if not isinstance(autosave, dict) or not all(
                isinstance(section, str) and isinstance(values, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in values.items())
                for section, values in autosave.items()):
            raise ValueError('Invalid probe save configuration snapshot')
        if autosave.get(record['section'], {}).get('z_offset') != record['offset']:
            raise ValueError('Probe save offset does not match snapshot')
        return json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()

    def read(self):
        try:
            with open(self.path, 'rb') as stream:
                raw = stream.read(self.LIMIT + 1)
        except FileNotFoundError:
            return None
        if len(raw) > self.LIMIT:
            raise ValueError('Probe save evidence is too large')
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {'record', 'sha256'}:
                raise ValueError('Invalid probe save evidence envelope')
            record = envelope['record']
            payload = self._payload(record)
            if hashlib.sha256(payload).hexdigest() != envelope['sha256']:
                raise ValueError('Probe save evidence checksum mismatch')
            return record
        except (TypeError, KeyError, OverflowError) as error:
            raise ValueError('Invalid probe save evidence') from error

    @contextmanager
    def _lock(self):
        with open(self.path + '.lock', 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @staticmethod
    def _digest(record):
        return hashlib.sha256(ProbeSaveRecord._payload(record)).hexdigest()

    def acknowledged(self, record):
        digest = self._digest(record)
        try:
            with open(self.path + '.' + digest + '.ack', 'rb') as stream:
                raw = stream.read(4097)
        except FileNotFoundError:
            return False
        if len(raw) > 4096:
            raise ValueError('Invalid probe save acknowledgement')
        ack = json.loads(raw)
        retained = isinstance(ack, dict) and ack.get('version') == 2
        keys = {'version', 'record_sha256', 'review'} | ({'retained_offset'} if retained else set())
        if (not isinstance(ack, dict) or set(ack) != keys
                or type(ack['version']) is not int or ack['version'] not in (1, 2)
                or ack['record_sha256'] != digest or not isinstance(ack['review'], str)
                or not re.fullmatch('[0-9a-f]{64}', ack['review'])):
            raise ValueError('Invalid probe save acknowledgement')
        if retained:
            offset = ack['retained_offset']
            if not isinstance(offset, str) or len(offset) > 64 or not math.isfinite(float(offset)):
                raise ValueError('Invalid retained probe offset')
        return True

    def _publish(self, path, payload, replace=False):
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix='.wmp-probe-save-', dir=parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, record, replace_history=False):
        payload = self._payload(record)
        envelope = json.dumps({'record': record, 'sha256': hashlib.sha256(payload).hexdigest()},
                              sort_keys=True, allow_nan=False).encode()
        if len(envelope) > self.LIMIT:
            raise ValueError('Probe save evidence is too large')
        with self._lock():
            if replace_history:
                # Evidence is diagnostic. Preserve the previous bytes if possible,
                # but a missing ACK or damaged record cannot forbid a new save.
                try:
                    with open(self.path, 'rb') as stream:
                        previous_bytes = stream.read(self.LIMIT + 1)
                    archive = self.path + '.' + hashlib.sha256(previous_bytes).hexdigest() + '.record'
                    if not os.path.exists(archive):
                        self._publish(archive, previous_bytes)
                except FileNotFoundError:
                    pass
                except Exception:
                    logging.exception('Unable to archive previous probe save evidence')
                self._publish(self.path, envelope, replace=True)
                return
            previous = self.read()
            if previous is not None:
                if not self.acknowledged(previous):
                    raise FileExistsError('Resolve previous probe save evidence first')
                if previous == record:
                    raise ValueError('A new probe save request is required')
                archive = ProbeSaveRecord(self.path + '.' + self._digest(previous) + '.record')
                archived = archive.read()
                if archived is None:
                    archive.create(previous)
                elif archived != previous:
                    raise ValueError('Probe save archive changed')
                if self.read() != previous:
                    raise ValueError('Probe save evidence changed before publication')
            self._publish(self.path, envelope, replace=previous is not None)

    def acknowledge(self, config_path, disk_autosave, loaded_config, pending, review, retain=False):
        with self._lock():
            current = self.review(config_path, disk_autosave, loaded_config, pending)
            if current is None or current['review'] != review:
                raise ValueError('Probe save review changed; review it again')
            if not retain and not current['configuration_matches']:
                raise ValueError('Current configuration does not match the recorded save')
            if retain and not current['retainable']:
                raise ValueError('Current configuration is not eligible for retention')
            record = current['record']
            if self.acknowledged(record):
                directory = os.open(os.path.dirname(self.path), os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return  # Lost reply: retain and durably confirm the original acknowledgement.
            digest = self._digest(record)
            ack = {'version': 1, 'record_sha256': digest, 'review': review}
            if retain:
                ack.update(version=2, retained_offset=current['loaded_offset'])
            self._publish(self.path + '.' + digest + '.ack', json.dumps(ack, sort_keys=True).encode())

    def review(self, config_path, disk_autosave, loaded_config, pending):
        record = self.read()
        if record is None:
            return None
        if os.path.abspath(config_path) != record['config_path']:
            raise ValueError('Probe save evidence belongs to a different configuration')
        if not isinstance(loaded_config, dict) or not isinstance(pending, dict):
            raise ValueError('Loaded probe configuration evidence is unavailable')
        matches = disk_autosave == record['autosave'] and not pending
        matches = matches and all(
            isinstance(loaded_config.get(section), dict) and loaded_config[section].get(key) == value
            for section, values in record['autosave'].items() for key, value in values.items())
        # An explicit retention choice covers only a changed probe offset. Other
        # calibration changes, pending edits or unloaded disk values remain held.
        loaded_offset = loaded_config.get(record['section'], {}).get('z_offset')
        valid_offset = False
        try:
            valid_offset = isinstance(loaded_offset, str) and len(loaded_offset) <= 64 and math.isfinite(float(loaded_offset))
        except (ValueError, OverflowError):
            pass
        expected = copy.deepcopy(record['autosave'])
        expected[record['section']]['z_offset'] = loaded_offset
        retainable = bool(valid_offset and not pending and loaded_offset != record['offset']
                          and disk_autosave == expected and all(
                              isinstance(loaded_config.get(section), dict)
                              and all(loaded_config[section].get(key) == value for key, value in values.items())
                              for section, values in disk_autosave.items()))
        differences, difference_count = [], 0
        for section in sorted(set(record['autosave']) | set(disk_autosave)):
            recorded_values = record['autosave'].get(section, {})
            disk_values = disk_autosave.get(section, {})
            loaded_values = loaded_config.get(section, {})
            for key in sorted(set(recorded_values) | set(disk_values)):
                recorded, disk = recorded_values.get(key), disk_values.get(key)
                loaded = loaded_values.get(key) if isinstance(loaded_values, dict) else None
                if recorded == disk == loaded:
                    continue
                difference_count += 1
                if len(differences) < 8:
                    differences.append({'section': section[:128], 'key': key[:128],
                                        'recorded': None if recorded is None else str(recorded)[:128],
                                        'disk': None if disk is None else str(disk)[:128],
                                        'loaded': None if loaded is None else str(loaded)[:128]})
        snapshot = [record, config_path, disk_autosave, loaded_config, pending]
        review = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {'record': record, 'configuration_matches': bool(matches), 'review': review,
                'loaded_offset': loaded_offset if valid_offset else None, 'retainable': retainable,
                'differences': differences, 'difference_count': difference_count, 'pending_changes': bool(pending),
                'outcome': 'acknowledged' if self.acknowledged(record) else 'review_required'}


class CalibrationSaveRecord(ProbeSaveRecord):
    """Last bound maintenance save; evidence only, never automatic replay."""
    @staticmethod
    def _payload(record):
        if (not isinstance(record, dict) or set(record) != {
                'version', 'session', 'request', 'config_path', 'autosave', 'state'}
                or type(record['version']) is not int or record['version'] != 1
                or record['state'] not in ('pending', 'saved')):
            raise ValueError('Invalid calibration save evidence')
        for key in ('session', 'request'):
            if not isinstance(record[key], str) or not re.fullmatch('[0-9a-f]{32}', record[key]):
                raise ValueError('Invalid calibration save identity')
        if not isinstance(record['config_path'], str) or not os.path.isabs(record['config_path']):
            raise ValueError('Invalid calibration save path')
        values = record['autosave']
        if (not isinstance(values, dict) or not values or not all(
                isinstance(section, str) and section and isinstance(items, dict) and items
                and all(isinstance(k, str) and isinstance(v, str) for k, v in items.items())
                for section, items in values.items())):
            raise ValueError('Invalid calibration save values')
        return json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()

    def write(self, record):
        payload = self._payload(record)
        envelope = json.dumps({'record': record, 'sha256': hashlib.sha256(payload).hexdigest()},
                              sort_keys=True, allow_nan=False).encode()
        if len(envelope) > self.LIMIT:
            raise ValueError('Calibration save evidence is too large')
        self._publish(self.path, envelope, replace=True)

    def discard(self):
        # A publication may have succeeded before directory fsync raised.
        # Do not leave positive evidence after a reported receipt-write error.
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        directory = os.open(os.path.dirname(self.path), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def verify(self, record, path, disk, loaded, pending):
        self._payload(record)
        # SAVE_CONFIG serializes ConfigParser values and Klipper parses them
        # again on restart. Multiline mesh values lose continuation indentation
        # in that round trip. Compare the expected *loaded* representation,
        # without weakening numerical/value checks or changing journal bytes.
        # This also verifies receipts written before this normalization existed.
        source = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
        source.read_dict(record['autosave'])
        serialized = io.StringIO()
        source.write(serialized)
        parsed = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
        parsed.read_string(serialized.getvalue())
        expected = {section: dict(parsed.items(section, raw=True)) for section in parsed.sections()}
        return (record['state'] == 'saved' and os.path.realpath(path) == record['config_path']
                and not pending and disk == expected
                and all(isinstance(loaded.get(section), dict)
                        and all(loaded[section].get(key) == value for key, value in items.items())
                        for section, items in expected.items()))


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


class ProbeEditorCommands:
    """Serialized probe editor requests; no commands originate from status reads."""
    STEPS = ('1', '-1', '0.1', '-0.1', '0.05', '-0.05', '0.025', '-0.025',
             '0.01', '-0.01', '0.005', '-0.005')

    def __init__(self, calibration):
        self.calibration = calibration
        self.printer, self.gcode = calibration.printer, calibration.gcode
        self.receipt = None
        self._executing = False
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

    def handle_stop(self, request):
        # Reactor callback: no G-code mutex, motion, or cleanup here.
        if (request.get_str('session') != self.calibration.session
                or request.get_str('request') != self.request
                or self.state not in ('preparing', 'stopping')
                or self.printer.lookup_object('openace', None) is not None
                or self.printer.lookup_object('AFC', None) is not None):
            raise request.error('Probe preparation request or owner changed')
        self.stop_requested = True
        request.send({'session': self.calibration.session, 'request': self.request,
                      'state': 'requested'})

    def cmd_prepare_check(self, gcmd):
        # Shared macros retain their existing behavior outside this editor.
        if self.state == 'preparing':
            self.calibration._check(gcmd)
            if self.stop_requested:
                self.stop_checkpoint_hit = True
                self.stop_exception = gcmd.error('Probe preparation stop requested')
                raise self.stop_exception

    def _prepare_with_stop_reporting(self, prepare):
        # Keep command_error cleanup events and normal fault reporting. Suppress
        # only this request's exact expected unwind exception, never matching text.
        original = getattr(self.gcode, '_respond_error', None)
        if original is None:
            return prepare()
        session, request = self.calibration.session, self.request
        def report(message):
            if (self.stop_exception is not None
                    and sys.exc_info()[1] is self.stop_exception
                    and self.state == 'preparing' and self.stop_requested
                    and self.calibration.session == session and self.request == request):
                return
            return original(message)
        self.gcode._respond_error = report
        try:
            return prepare()
        finally:
            if self.gcode._respond_error is report:
                self.gcode._respond_error = original

    def _finish_preparation_stop(self, gcmd):
        self.state = 'stopping'
        was_executing, self._executing = self._executing, True
        try:
            # Call the drain primitive directly: the vendor dispatcher can
            # silently skip a submitted M400 when quick_stop_flag is set.
            self.printer.lookup_object('toolhead').wait_moves()
            self.calibration._check(gcmd)
            if self.receipt is not None:
                self.receipt._require('editing')
                # Do not dispatch an unbound global ABORT handler.
                self.receipt.helper.cmd_ABORT(gcmd)
                if self.receipt.state != 'aborted':
                    raise gcmd.error('Probe helper abort was not confirmed')
            elif 'ACCEPT' in self.gcode.ready_gcode_handlers:
                raise gcmd.error('Unresolved probe helper after preparation stop')
            self.state, self.error = 'aborted', ''
        except Exception as error:
            self.state, self.error = 'unknown', str(error)[:512]
            raise
        finally:
            self._executing = was_executing

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
        self._run(gcmd)

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
            started = False
            def prepare():
                nonlocal started
                started = True
                self._prepare_with_stop_reporting(
                    lambda: self.gcode.run_script_from_command('_WMP_PROBE_CALIBRATE'))
            try:
                self._admit(gcmd, fresh_action=True)
                self.preparation_config = self._pending_config()
                self._executing = True
                self.receipt = ProbeEditorReceipt.prepare(session, self.gcode,
                    lambda: self.calibration.session, lambda: self._admit(gcmd),
                    prepare,
                    failed=lambda receipt: setattr(self, 'receipt', receipt))
            except Exception as error:
                if self.stop_checkpoint_hit and error is self.stop_exception:
                    self._finish_preparation_stop(gcmd)
                    return
                self.state, self.error = ('failed' if started else 'rejected'), str(error)[:512]
                self.action_refused = not started
                self.preparation_error = self.error
                raise
            finally:
                self._executing = False
            if self.stop_requested:
                self._finish_preparation_stop(gcmd)
            else:
                self.state = 'editing'
            return
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
        r'NOZZLE_CALIBRATE_TOOL_OFFSET T=[0-3]|RAPID_MODE T=[0-3])')

    def __init__(self, printer, gcode):
        self.printer, self.gcode = printer, gcode
        self.failure = ''
        self.session = uuid.uuid4().hex
        self.checkpoint = ''
        self.active = False
        self._saving = False
        self.save_result = {'protocol': 1, 'state': 'unconfirmed', 'session': '', 'request': '', 'error': ''}
        self._save_requests = set()
        self._attempts = {}  # Legacy v1 tombstones; never evict replay protection.
        self._ticket_counter = 0
        self._ticket_attempt = None
        self._current_attempt = None
        self.attempt_result = {}
        self._heater_ownership = None
        self._heater_ownership_error = 'heater tracking not initialized'
        register = getattr(printer, 'register_event_handler', None)
        if callable(register):
            register('klippy:ready', self._restore_save_result)
            register('klippy:ready', self._initialize_heater_ownership)
        gcode.register_command('_WMP_CALIBRATION_COMMAND', self.cmd_run,
                               desc='Execute a stock calibration stage with failure latching')
        self.probe_editor = ProbeEditorCommands(self)

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
        try:
            self._cool_failed_attempt(owner)
        except Exception:
            logging.exception('Unable to turn off owned calibration heaters')
            self.printer.invoke_shutdown(
                'Calibration failed and heater cleanup failed. Check the preceding errors before restarting.')

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

    def _save_with_receipt(self, gcmd, store, record, evidence_ok):
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
            self._check(gcmd)
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

    def _check(self, gcmd, fresh_action=False):
        if getattr(self, 'identification_blocked', False):
            raise gcmd.error('Restart Klipper after head identification before calibration')
        now = self.printer.get_reactor().monotonic()
        if self.printer.is_shutdown():
            raise gcmd.error('Printer is shut down')
        if getattr(self.printer, 'quick_stop_flag', False):
            raise gcmd.error('Printer quick-stop is active')
        state = self.printer.lookup_object('print_stats').get_status(now)['state']
        paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
        if state in ('printing', 'paused') or paused:
            raise gcmd.error('Calibration requires an idle printer: ' + ('print_stats.state=' + str(state)[:80] if state in ('printing', 'paused') else 'pause_resume.is_paused=' + repr(paused)[:80]))
        if fresh_action:
            material = self.printer.lookup_object('wm_material', None)
            begin = getattr(material, '_begin_explicit_physical_action', None)
            if begin is not None:
                begin('calibration')
        variables = self.printer.lookup_object('save_variables').get_status(now)['variables']
        if int(variables.get('fail_flag', 0)) != 0:
            raise gcmd.error('Tool change failed during calibration: fail_flag=%s' % repr(variables.get('fail_flag', 0))[:80])

    def _attempt(self, gcmd):
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
                attempt = {'protocol': 1, 'session': session, 'request': request,
                           'ticket': str(ticket), 'state': 'pending', 'error': '',
                           'next': 0, 'executed': False}
                self._ticket_attempt = attempt
            else:
                raise gcmd.error('Calibration ticket is retired or not yet issued; start a new calibration using current status')
        else:
            attempt = self._attempts.get(request)
            if attempt is None:
                if len(self._attempts) >= 1024:
                    raise gcmd.error('Legacy calibration attempt history is full; update the WM+ screen for bounded calibration tickets, or restart Klipper for this older client')
                attempt = {'protocol': 1, 'session': session, 'request': request,
                           'state': 'pending', 'error': '', 'next': 0, 'executed': False}
                self._attempts[request] = attempt
        if self.active:
            if attempt is not self._current_attempt:
                attempt.update(state='refused', error='Calibration command is already running')
            # Reentrant/competing requests cannot change the executing attempt
            # or replace its status, including a replay of its sequence zero.
            raise gcmd.error('Calibration command is already running')
        if attempt['state'] != 'pending':
            raise gcmd.error('Calibration attempt is already stopped: ' + attempt['error'])
        self.attempt_result = attempt
        if sequence != attempt['next']:
            attempt.update(state='refused', error='Calibration stage was missing, repeated, or out of order: SEQUENCE=%s; expected %s' % (sequence, attempt['next']))
            # A missing/replayed stage after execution cannot prove that the
            # partially executed calibration is safe to continue or save.
            if attempt['executed']:
                self.failure = attempt['error']
                attempt['state'] = 'failed'
            raise gcmd.error(attempt['error'])
        attempt['next'] += 1
        return attempt

    def cmd_run(self, gcmd):
        try:
            attempt = self._attempt(gcmd)
        except Exception:
            attempt = self._attempts.get(gcmd.get('REQUEST', '')) if gcmd.get('TICKET', None) is None else self._ticket_attempt
            if (attempt is not None and gcmd.get('TICKET', None) is not None
                    and (attempt['request'] != gcmd.get('REQUEST', '')
                         or attempt['ticket'] != str(gcmd.get('TICKET', None)))):
                attempt = None  # An old ticket cannot clean a newer owner's heaters.
            if (not self.active and attempt is not None
                    and attempt['state'] == 'failed' and attempt['executed']):
                self._cleanup_failed_heaters(attempt['request'])
            raise
        if self.failure:
            if attempt is not None and attempt['next'] == 1 and not attempt['executed']:
                self.failure = ''  # Explicit new attempt; recheck live conditions below.
            else:
                raise gcmd.error('Calibration stopped: %s. Start a new calibration attempt after inspecting the printer.' % self.failure)
        if self.probe_editor.busy() or self.active:
            error = ('Close or resolve the probe editor before another calibration'
                     if self.probe_editor.busy() else 'Calibration command is already running')
            if attempt is not None:
                attempt.update(state='failed' if attempt['executed'] else 'refused', error=error)
                if attempt['executed']:
                    self.failure = error
                    if not self.active:
                        self._cleanup_failed_heaters(attempt['request'])
            raise gcmd.error(error)
        started = False
        bound_save = False
        try:
            encoded = gcmd.get('HEX', '')
            if not encoded or len(encoded) > 512 or not re.fullmatch('[0-9A-Fa-f]+', encoded):
                raise gcmd.error('Invalid calibration command encoding')
            command = bytes.fromhex(encoded).decode('ascii')
            if not self.COMMAND.fullmatch(command):
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
            self._check(gcmd, fresh_action=attempt is not None and not attempt['executed'])
            if attempt is not None and attempt is not self._current_attempt:
                previous = self._current_attempt
                if previous is not None and previous['state'] == 'pending':
                    previous.update(state='superseded', error='A newer calibration attempt was admitted')
                self._current_attempt = attempt
            save = self._prepare_save(gcmd, request) if bound_save else None
            if command == 'SAVE_CONFIG':
                material = self.printer.lookup_object('wm_material', None)
                if material is not None:
                    # Admit before configfile writes; its later restart event
                    # alone is too late to protect persistent configuration.
                    material._restart_requested(None)
            if attempt is not None:
                attempt['executed'] = True
            self._saving = command == 'SAVE_CONFIG'
            self.active = True
            started = True
            with self._heater_execution(attempt['request'] if attempt else 'legacy'):
                if save is not None:
                    self._save_with_receipt(gcmd, *save)
                else:
                    self.gcode.run_script_from_command(command)
            # Some vendor macros signal a tool failure without raising. Never
            # let subsequent PARK clear that flag or SAVE_CONFIG persist results.
            if save is None:
                self._check(gcmd)
            if token:
                self.checkpoint = token
            if command == 'SAVE_CONFIG':
                if self._heater_ownership is not None:
                    self._heater_ownership.release(attempt['request'] if attempt else 'legacy')
                if attempt is not None:
                    attempt.update(state='saved', error='')
        except Exception as exc:
            error = str(exc)[:512] or 'Calibration command failed'
            clean_refusal = attempt is not None and not attempt['executed']
            if attempt is not None:
                attempt.update(state='refused' if clean_refusal else 'failed', error=error)
            if not clean_refusal:
                self.failure = error
            if bound_save:
                self.save_result.update(state='unconfirmed', error=error)
            if started or (attempt is not None and attempt['executed']):
                # Includes a later stage refused before dispatch: heaters from
                # earlier stages still belong to this now-stopped attempt.
                self._cleanup_failed_heaters(attempt['request'] if attempt else 'legacy')
            raise
        finally:
            self._saving = False
            self.active = False


def load_config(config):
    return BottomZ(config)
