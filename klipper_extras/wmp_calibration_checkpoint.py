# SPDX-License-Identifier: GPL-3.0-or-later
"""Scoped completed-type persistence; never restart or replay a calibration."""
import copy
import hashlib
import math
import os
import re
import stat
import tempfile
from contextlib import nullcontext


class Checkpoints:
    def __init__(self, calibration):
        self.calibration = calibration

    def stage(self, command, attempt):
        if attempt is None or any(self.calibration.printer.lookup_object(owner, None) is not None
                                  for owner in ('openace', 'AFC')):
            return nullcontext()  # External owners retain their original persistence policy.
        if command == 'G29':
            scope = ('mesh', 'bed_mesh default', None)
        elif command == 'SHAPER_CALIBRATE':
            scope = ('vibration', 'input_shaper',
                     {'shaper_type_x', 'shaper_freq_x', 'shaper_type_y', 'shaper_freq_y'})
        else:
            pid = re.fullmatch(r'PID_CALIBRATE HEATER=(extruder[1-3]?) TARGET=220', command)
            if pid is None:
                return nullcontext()
            scope = ('pid:' + pid[1], pid[1], {'control', 'pid_kp', 'pid_ki', 'pid_kd'})
        return Stage(self.calibration, attempt, command, scope)


def _snapshot(config):
    return (copy.deepcopy(config.autosave.fileconfig),
            copy.deepcopy(config.status_save_pending), config.save_config_pending)


def _apply(snapshot, event):
    parser, pending, dirty = snapshot
    action, section, option, value, owned = event
    if action == 'set':
        if not parser.has_section(section):
            parser.add_section(section)
        parser.set(section, option, value)
        if pending.get(section) is None:
            pending[section] = {}
        pending.setdefault(section, {})[option] = value
        dirty = True
    elif parser.has_section(section):
        parser.remove_section(section)
        pending[section] = None
        dirty = True
    elif section in pending and pending[section] is not None:
        del pending[section]
        dirty = True
    return parser, pending, dirty


class Stage:
    def __init__(self, calibration, attempt, command, scope):
        self.calibration, self.attempt, self.command = calibration, attempt, command
        self.kind, self.section, self.options = scope
        self.printer, self.gcode = calibration.printer, calibration.gcode
        self.config = self.printer.lookup_object('configfile')
        self.tracker = calibration._heater_ownership
        self.actor = None if self.tracker is None else self.tracker.current_actor()
        self.events, self.patches = [], []
        self.shaping = None
        self.shape_patches, self.foreign_shaping = [], {}
        self.record = None
        self.base = None

    def _authority(self):
        c, a = self.calibration, self.attempt
        if (not c.active or c.executing is not a or c._current_attempt is not a
                or a['state'] != 'pending' or self.tracker is None or c._heater_ownership is not self.tracker
                or not self.tracker.enabled
                or self.tracker.current_actor() is not self.actor
                or self.tracker.contexts.get(self.actor) != a['request']
                or self.printer.is_shutdown() or getattr(self.printer, 'quick_stop_flag', False)
                or any(self.printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC'))):
            raise self.gcode.error('Calibration checkpoint command owner or printer state changed')

    def _owned(self):
        return (self.tracker.current_actor() is self.actor
                and self.tracker.contexts.get(self.actor) == self.attempt['request']
                and self.calibration.executing is self.attempt
                and self.calibration._current_attempt is self.attempt)

    def _allowed(self, section, option=None):
        return section == self.section and (option is None or self.options is None or option in self.options)

    def _patch(self, name):
        config = self.config
        original = getattr(config, name)
        local = name in vars(config)
        def observed(section, *args):
            option = config.autosave.fileconfig.optionxform(args[0]) if name == 'set' else None
            before = _parser_values(config.autosave.fileconfig)
            def record():
                if name == 'set':
                    parser = config.autosave.fileconfig
                    if parser.has_option(section, option):
                        self.events.append(('set', section, option, parser.get(section, option, raw=True), self._owned()))
                else:
                    self.events.append(('remove', section, None, None, self._owned()))
            try:
                result = original(section, *args)
            except Exception:
                # A clean validation refusal does not transfer ownership.
                if before != _parser_values(config.autosave.fileconfig):
                    record()
                raise
            record()  # Equal-value writes still transfer ownership.
            return result
        # Match the retained public keyword signatures as well as positional
        # calls; unrelated callbacks must not lose normal config API behavior.
        def recording_set(section, option, value):
            return observed(section, option, value)
        def recording_remove(section):
            return observed(section)
        replacement = recording_set if name == 'set' else recording_remove
        setattr(config, name, replacement)
        self.patches.append((name, original, replacement, local))

    def __enter__(self):
        self._authority()
        if self.config is None:
            raise self.gcode.error('Calibration checkpoint configuration is unavailable')
        self.base = _snapshot(self.config)
        self.path = self.printer.get_start_args()['config_file']
        self.disk_before = _read_regular(self.path)  # Refuse unsafe targets before measurement.
        if self.kind == 'vibration':
            shaper = self.printer.lookup_object('input_shaper', None)
            if shaper is not None:
                self.shaping = (shaper, [(axis, copy.deepcopy(vars(axis.params)),
                    copy.deepcopy((axis.n, axis.A, axis.T, axis.saved))) for axis in shaper.get_shapers()])
        self.record = {'type': self.kind, 'command': self.command, 'state': 'pending',
                       'sequence': self.attempt['next'] - 1, 'sha256': '', 'error': ''}
        records = self.attempt.setdefault('checkpoints', [])
        records.append(self.record)
        del records[:-16]
        try:
            self._patch('set')
            self._patch('remove_section')
            if self.shaping is not None:
                for axis, params, values in self.shaping[1]:
                    self._patch_shaper(axis)
        except Exception as error:
            self.record.update(state='unconfirmed', error=str(error)[:512])
            self._unpatch()
            raise
        return self

    def _patch_shaper(self, axis):
        original = axis.update
        local = 'update' in vars(axis)
        def update(*args, **kwargs):
            before = (copy.deepcopy(vars(axis.params)), copy.deepcopy((axis.n, axis.A, axis.T, axis.saved)))
            def observed():
                return (copy.deepcopy(vars(axis.params)), copy.deepcopy((axis.n, axis.A, axis.T, axis.saved)))
            try:
                result = original(*args, **kwargs)
            except Exception:
                if not self._owned() and observed() != before:
                    self.foreign_shaping[id(axis)] = observed()
                raise
            if not self._owned():
                self.foreign_shaping[id(axis)] = observed()
            return result
        axis.update = update
        self.shape_patches.append((axis, original, update, local))

    def _unpatch(self):
        errors = []
        for name, original, observed, local in reversed(self.patches):
            if getattr(self.config, name) is not observed:
                errors.append('configuration ' + name)
            elif local:
                setattr(self.config, name, original)
            else:
                delattr(self.config, name)
        self.patches = []
        for axis, original, observed, local in reversed(self.shape_patches):
            if axis.update is not observed:
                errors.append('input shaper update')
            elif local:
                axis.update = original
            else:
                del axis.update
        self.shape_patches = []
        if errors:
            raise self.gcode.error('Calibration checkpoint hook owner changed: ' + ', '.join(errors))

    def _restore_pending(self, completed, owned_values=None):
        snapshot = copy.deepcopy(self.base)
        for event in self.events:
            action, section, option, value, owned = event
            # A PID remove_section is an intermediate rewrite, not authority to
            # delete unrelated tuning from that heater's autosave section.
            if not owned:
                snapshot = _apply(snapshot, event)
        if completed:
            for option, value in owned_values.items():
                snapshot = _apply(snapshot, ('set', self.section, option, value, True))
        parser, pending, dirty = snapshot
        self.config.autosave.fileconfig = parser
        self.config.status_save_pending = pending
        self.config.save_config_pending = dirty

    def _restore_shaping(self):
        if self.shaping is None:
            return
        shaper, saved = self.shaping
        if (self.printer.is_shutdown() or getattr(self.printer, 'quick_stop_flag', False)
                or self.calibration.executing is not self.attempt
                or self.calibration._current_attempt is not self.attempt
                or shaper is not self.printer.lookup_object('input_shaper', None)):
            raise ValueError('Previous vibration settings cannot be restored on the stopped/changed printer')
        current = list(shaper.get_shapers())
        if len(current) != len(saved) or any(axis is not item[0] for axis, item in zip(current, saved)):
            raise ValueError('Previous vibration shaper axes changed')
        saved = [(axis,) + self.foreign_shaping.get(id(axis), (params, values))
                 for axis, params, values in saved]
        for axis, params, values in saved:
            vars(axis.params).clear()
            vars(axis.params).update(copy.deepcopy(params))
            axis.n, axis.A, axis.T, axis.saved = copy.deepcopy(values)
        shaper._update_input_shaping()
        if any(vars(axis.params) != params or (axis.n, axis.A, axis.T, axis.saved) != values
               for axis, params, values in saved):
            raise ValueError('Previous vibration settings restoration was not confirmed')

    def _values(self):
        values = {}
        if self.foreign_shaping:
            raise ValueError('Another command changed the vibration settings')
        for action, section, option, value, owned in self.events:
            if not owned and self._allowed(section, option):
                raise ValueError('Another command changed this calibration result')
            if owned and not self._allowed(section, option):
                raise ValueError('Calibration changed settings outside its completed type')
            if owned and action == 'remove':
                values.clear()
            elif owned and action == 'set':
                values[option] = value
        required = self.options if self.options is not None else {'version', 'points', 'x_count', 'y_count'}
        if not required.issubset(values):
            raise ValueError('Calibration did not produce a complete owned result')
        if self.kind.startswith('pid:'):
            if (values['control'] != 'pid' or any(not math.isfinite(float(values[key]))
                    or float(values[key]) < 0 for key in ('pid_kp', 'pid_ki', 'pid_kd'))
                    or float(values['pid_kp']) == 0):
                raise ValueError('Completed PID result is invalid')
        elif self.kind == 'vibration':
            for axis in 'xy':
                frequency = float(values['shaper_freq_' + axis])
                if (not math.isfinite(frequency) or frequency <= 0
                        or not re.fullmatch('[a-z0-9_]+', values['shaper_type_' + axis])):
                    raise ValueError('Completed vibration result is invalid')
        elif self.kind == 'mesh':
            x_count, y_count = int(values['x_count']), int(values['y_count'])
            rows = [[float(point.strip()) for point in row.split(',')]
                    for row in values['points'].strip().splitlines()]
            if (x_count < 2 or y_count < 2 or len(rows) != y_count
                    or any(len(row) != x_count or not all(math.isfinite(point) for point in row) for row in rows)):
                raise ValueError('Completed mesh result is invalid')
        return {self.section: values}

    def __exit__(self, error_type, error, tb):
        try:
            self._unpatch()
            if error_type is not None:
                return False
            self._authority()
            values = self._values()
            self._restore_pending(completed=True, owned_values=values[self.section])
            digest = publish(self.config, self.gcode, self.path, values, expected=self.disk_before)
            self._authority()
            self.record.update(state='saved', sha256=digest)
            return False
        except Exception as failed:
            error = failed
            raise
        finally:
            if self.record['state'] != 'saved':
                self.record.update(state='unconfirmed', error=str(error or 'Calibration did not complete')[:512])
                try:
                    self._restore_pending(completed=False)
                    self._restore_shaping()
                except Exception as failed:
                    message = 'Calibration result rollback unconfirmed: ' + str(failed)
                    self.attempt['cancel_motion_error'] = message[:512]
                    raise self.gcode.error(message[:512])


def _parser_values(parser):
    return {section: dict(parser.items(section, raw=True)) for section in parser.sections()}


def _read_regular(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16 * 1024 * 1024:
            raise ValueError('Calibration checkpoint needs a regular bounded configuration file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Calibration checkpoint configuration is too large')
        return data, metadata
    finally:
        os.close(descriptor)


def publish(config, gcode, path, values, expected=None):
    """Merge only this completed result with the on-disk autosave, atomically."""
    original, metadata = _read_regular(path)
    if expected is not None and (original != expected[0] or any(
            getattr(metadata, key) != getattr(expected[1], key)
            for key in ('st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns'))):
        raise ValueError('Printer configuration changed during calibration measurement')
    regular, old_autosave = config._find_autosave_data(original.decode('utf-8').replace('\r\n', '\n'))
    wrapper = config._build_config_wrapper(old_autosave, path)
    for section, options in values.items():
        if not wrapper.fileconfig.has_section(section):
            wrapper.fileconfig.add_section(section)
        for option, value in options.items():
            wrapper.fileconfig.set(section, option, value)
    regular = config._strip_duplicates(regular, wrapper)
    # The retained conflict check must see the scoped disk candidate, not live
    # unrelated pending edits. Other methods keep their retained bound self.
    class Scoped:
        autosave = wrapper
        def __getattr__(self, name):
            return getattr(config, name)
    config._disallow_include_conflicts.__func__(Scoped(), regular, path, gcode)
    header = config.cmd_SAVE_CONFIG_NO_RESTART.__func__.__globals__['AUTOSAVE_HEADER']
    lines = [('#*# ' + line).strip() for line in config._build_config_string(wrapper).split('\n')]
    payload = (regular.rstrip() + '\n' + header.rstrip() + '\n' + '\n'.join(lines) + '\n').encode('utf-8')
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, temporary = tempfile.mkstemp(prefix='.wmp-calibration-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        current, current_metadata = _read_regular(path)
        if (current != original or any(getattr(current_metadata, key) != getattr(metadata, key)
                for key in ('st_dev', 'st_ino', 'st_mtime_ns', 'st_ctime_ns'))):
            raise ValueError('Printer configuration changed during calibration checkpoint')
        os.replace(temporary, path)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        current, saved_metadata = _read_regular(path)
        if current != payload:
            raise ValueError('Calibration checkpoint readback was not confirmed')
        return hashlib.sha256(payload).hexdigest()
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
