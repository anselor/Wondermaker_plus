"""UUID mapping transaction for head identification; no motion or service calls.

The workflow must confirm each physical pickup and final docking before commit.
The recovery extra exposes its command adapter; the native setup worker must
explicitly invoke it instead of the vendor identification sequence.
"""
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid


UUID_LINE = re.compile(rb'(?m)^([ \t]*canbus_uuid[ \t]*:[ \t]*)([0-9a-fA-F]{12})([ \t]*(?:[#;][^\r\n]*)?)(\r?\n|$)')


def _verified_permutation(original_ids, observed_ids):
    mappings = []
    for values in (original_ids, observed_ids):
        if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= 4:
            raise ValueError('Expected one to four verified head identities')
        if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-fA-F]{12}', v) for v in values):
            raise ValueError('Invalid verified head identity')
        normalized = [v.lower() for v in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError('Duplicate verified head identity')
        mappings.append(normalized)
    old, new = mappings
    if set(old) != set(new):
        raise ValueError('Migration requires the same verified hardware set')
    return old, new


def plan_filament_state_mapping(records, original_ids, observed_ids, validate_identity):
    """Remap standalone durable filament records; never infer sensor/load state.

    All three known files must be represented, with None for a verified absence.
    The material owner's identity validator remains authoritative. This is a
    read-only planner for the joint topology transaction, not a publication API.
    """
    old, new = _verified_permutation(original_ids, observed_ids)
    names = {'wmp_filaments.json', 'wmp_filament_loaded.json', 'wmp_hotend_materials.json'}
    if not isinstance(records, dict) or set(records) != names or not callable(validate_identity):
        raise ValueError('Complete standalone filament record snapshot is required')

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate filament record key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Invalid JSON constant in filament record')

    result = {}
    for name in sorted(names):
        raw = records[name]
        if raw is None:
            result[name] = None
            continue
        limit = 32768 if name == 'wmp_hotend_materials.json' else 16384
        if not isinstance(raw, bytes) or len(raw) > limit:
            raise ValueError('Invalid filament record size or encoding')
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                              parse_constant=invalid_constant)
        if name == 'wmp_hotend_materials.json':
            if (not isinstance(document, dict) or set(document) != {'version', 'heads'}
                    or type(document['version']) is not int or document['version'] != 1):
                raise ValueError('Invalid hotend material history')
            heads = document['heads']
        else:
            heads = document
        if not isinstance(heads, dict) or not set(heads) <= {'h%d' % h for h in range(len(old))}:
            raise ValueError('Filament record references an unverified head')
        for value in heads.values():
            if name == 'wmp_filaments.json':
                validate_identity(value)
            elif name == 'wmp_filament_loaded.json':
                if type(value) is not bool:
                    raise ValueError('Invalid loaded filament flag')
            else:
                if (not isinstance(value, dict) or set(value) != {'state', 'materials', 'unknown_residue'}
                        or value['state'] not in ('mixed', 'purged')
                        or type(value['unknown_residue']) is not bool
                        or not isinstance(value['materials'], list) or not 1 <= len(value['materials']) <= 8):
                    raise ValueError('Invalid hotend material record')
                if value['state'] == 'purged' and (len(value['materials']) != 1 or value['unknown_residue']):
                    raise ValueError('Invalid purged hotend material record')
                for identity in value['materials']:
                    validate_identity(identity)
        mapped = {'h%d' % destination: heads['h%d' % old.index(identity)]
                  for destination, identity in enumerate(new) if 'h%d' % old.index(identity) in heads}
        if mapped == heads:
            result[name] = raw
        else:
            output = {'version': 1, 'heads': mapped} if name == 'wmp_hotend_materials.json' else mapped
            result[name] = (json.dumps(output, sort_keys=True, ensure_ascii=True, allow_nan=False) + '\n').encode()
            if len(result[name]) > limit:
                raise ValueError('Migrated filament record exceeds owner size limit')
    return result


def plan_saved_pid_mapping(content, original_ids, observed_ids):
    """Plan SAVE_CONFIG PID relocation for a verified, unchanged set of heads.

    Pure bytes transformation; no file writes or claim about active include
    overrides. Callers must verify calibration provenance and publish this with
    the UUID/state migration, never independently. Replacement/shrink/expansion
    requires a separate reviewed policy and is deliberately not inferred here.
    """
    if not isinstance(content, bytes):
        raise ValueError('Saved configuration must be bytes')
    old, new = _verified_permutation(original_ids, observed_ids)
    marker = b'#*# <---------------------- SAVE_CONFIG ---------------------->'
    if content.count(marker) != 1:
        raise ValueError('Expected exactly one SAVE_CONFIG block for PID migration')
    start = content.index(marker) + len(marker)
    sections = list(re.finditer(rb'(?m)^#\*# \[([^\]\r\n]+)\][ \t]*(?:\r?\n|$)', content[start:]))
    rows = {}
    for index, match in enumerate(sections):
        name = match.group(1)
        if not re.fullmatch(rb'extruder(?:[1-3])?', name):
            continue
        head = 0 if name == b'extruder' else int(name[-1:])
        if head >= len(old) or head in rows:
            raise ValueError('Saved PID head set is ambiguous')
        begin = start + match.start()
        end = start + sections[index + 1].start() if index + 1 < len(sections) else len(content)
        body = content[start + match.end():end]
        fields = {}
        for line in body.splitlines():
            if line.strip() in (b'', b'#*#'):
                continue
            option = re.fullmatch(rb'#\*#\s+([a-zA-Z_]+)\s*=\s*(\S+)\s*', line)
            if not option:
                raise ValueError('Unrecognized saved heater calibration line')
            key = option.group(1).lower()
            if key in fields:
                raise ValueError('Duplicate saved heater calibration field')
            fields[key] = option.group(2)
        if set(fields) != {b'control', b'pid_kp', b'pid_ki', b'pid_kd'} or fields[b'control'] != b'pid':
            raise ValueError('Expected complete PID-only saved heater calibration')
        try:
            gains = [float(fields[key]) for key in (b'pid_kp', b'pid_ki', b'pid_kd')]
        except ValueError:
            raise ValueError('Invalid saved PID gains') from None
        if any(not math.isfinite(v) or v < 0 for v in gains):
            raise ValueError('Invalid saved PID gains')
        rows[head] = (begin, end, body, content[begin:start + match.end()])
    # Do not synthesize missing tunes or leave the destination's old tune in
    # place. Incomplete evidence must be resolved before publishing a mapping.
    if set(rows) != set(range(len(old))):
        raise ValueError('Missing saved PID calibration for a verified head')
    replacements = []
    for destination, identity in enumerate(new):
        source = old.index(identity)
        begin, end, _, header = rows[destination]
        replacements.append((begin, end, header + rows[source][2]))
    result = content
    for begin, end, replacement in sorted(replacements, reverse=True):
        result = result[:begin] + replacement + result[end:]
    return result


def plan_head_configuration(snapshot, observed_ids, effective_settings, validate_identity):
    """Build one complete same-hardware migration candidate without writing.

    Snapshot paths are relative to the configuration directory. Publication must
    bind this snapshot and the reviewed runtime owner/session, guard unresolved
    jobs and commit the entire candidate together. This does not authorize it.
    """
    try:
        from . import wmp_nozzles
    except ImportError:
        import wmp_nozzles
    if not isinstance(observed_ids, (list, tuple)) or not 1 <= len(observed_ids) <= 4:
        raise ValueError('Expected one to four observed head identities')
    if not isinstance(snapshot, dict) or not isinstance(effective_settings, dict):
        raise ValueError('Configuration and effective settings snapshots required')
    head_names = ['wm_zru_thr%d.cfg' % h for h in range(len(observed_ids))]
    state_names = {'wmp_filaments.json', 'wmp_filament_loaded.json', 'wmp_hotend_materials.json'}
    if set(snapshot) != set(head_names) | state_names | {'printer.cfg', 'tmt1.ini'}:
        raise ValueError('Incomplete or unsupported head configuration snapshot')
    original_ids = []
    for head, name in enumerate(head_names):
        raw = snapshot[name]
        if not isinstance(raw, bytes) or len(raw) > 2 * 1024 * 1024:
            raise ValueError('Invalid head configuration snapshot')
        matches = list(UUID_LINE.finditer(raw))
        if len(matches) != 1 or len(re.findall(rb'(?m)^[ \t]*canbus_uuid[ \t]*:', raw)) != 1:
            raise ValueError('Expected exactly one valid configured head UUID')
        identity = matches[0].group(2).decode().lower()
        active = effective_settings.get('mcu T%d' % head, {}).get('canbus_uuid')
        if not isinstance(active, str) or active.lower() != identity:
            raise ValueError('Active head identity differs from migration source')
        original_ids.append(identity)
    old, new = _verified_permutation(original_ids, observed_ids)
    for name in ('printer.cfg', 'tmt1.ini'):
        if not isinstance(snapshot[name], bytes) or len(snapshot[name]) > 2 * 1024 * 1024:
            raise ValueError('Invalid configuration snapshot')
    planned = dict(snapshot)
    planned['printer.cfg'] = plan_saved_pid_mapping(snapshot['printer.cfg'], old, new)
    # Validate actual loaded heater tuning against saved evidence before moving
    # it. A different active override/pending edit needs explicit resolution.
    saved = snapshot['printer.cfg'].split(b'#*# <---------------------- SAVE_CONFIG ---------------------->')[1]
    for head in range(len(old)):
        section = 'extruder' + (str(head) if head else '')
        match = re.search(rb'(?ms)^#\*# \[' + section.encode() + rb'\][ \t]*\r?\n(.*?)(?=^#\*# \[|\Z)', saved)
        if match is None:
            raise ValueError('Missing saved PID migration evidence')
        fields = {k.decode().lower(): v.decode() for k, v in re.findall(
            rb'(?m)^#\*#\s+([a-zA-Z_]+)\s*=\s*(\S+)', match.group(1))}
        active = effective_settings.get(section, {})
        if active.get('control') != 'pid':
            raise ValueError('Active heater control differs from migration source')
        for key in ('pid_kp', 'pid_ki', 'pid_kd'):
            value = active.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value != float(fields[key]):
                raise ValueError('Active PID tuning differs from migration source')
    config, ini = wmp_nozzles.plan_head_mapping(
        planned['printer.cfg'].decode('utf-8'), snapshot['tmt1.ini'].decode('utf-8'),
        [old.index(identity) for identity in new], effective_settings)
    planned['printer.cfg'], planned['tmt1.ini'] = config.encode(), ini.encode()
    planned.update(plan_filament_state_mapping(
        {name: snapshot[name] for name in state_names}, old, new, validate_identity))
    for head, name in enumerate(head_names):
        planned[name] = UUID_LINE.sub(
            lambda m: m.group(1) + new[head].encode() + m.group(3) + m.group(4), snapshot[name])
    return planned


def atomic_write(path, content):
    previous = path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix='.wmp-uuid-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o600)
            if previous:
                os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_resolved_journals(directory):
    for journal in Path(directory).glob('.wmp-head-migration-*.json'):
        if journal.is_symlink():
            raise ValueError('Linked head migration journal needs inspection')
        record = json.loads(journal.read_text())
        if (not isinstance(record, dict) or record.get('version') != 1
                or record.get('state') not in ('verified', 'rolled-back')):
            raise ValueError('Resolve head configuration migration before continuing: ' + str(journal))
    for journal in Path(directory).glob('.wmp-identification-*.json'):
        if journal.is_symlink():
            raise ValueError('Linked identification journal needs inspection')
        record = json.loads(journal.read_text())
        if not isinstance(record, dict) or record.get('version') != 1:
            raise ValueError('Invalid identification journal needs inspection: ' + str(journal))
        if record.get('state') not in ('committed', 'rolled-back'):
            raise ValueError('Recover interrupted identification before continuing: ' + str(journal))


class HeadConfigurationTransaction:
    """Joint same-hardware migration; publication is not restart acceptance.

    The owning backend must supply fresh admission at each boundary. No motion,
    service restart, owner selection or implicit confirmation is performed here.
    """
    def __init__(self, directory, observed_ids, effective_settings, validate_identity, session, current_state_only=False):
        _verified_permutation(observed_ids, observed_ids)
        if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', session):
            raise ValueError('A valid backend session is required')
        self.directory = Path(directory).resolve()
        if not current_state_only:
            require_resolved_journals(self.directory)
        self.validate_identity = validate_identity
        self.session = session
        self.observed_ids = list(observed_ids)
        self.effective_settings = json.loads(json.dumps(effective_settings, allow_nan=False))
        names = ['printer.cfg', 'tmt1.ini'] + ['wm_zru_thr%d.cfg' % h for h in range(len(observed_ids))]
        names += ['wmp_filaments.json', 'wmp_filament_loaded.json', 'wmp_hotend_materials.json']
        self.original = {name: self._read(name) for name in names}
        self.planned = plan_head_configuration(self.original, self.observed_ids,
                                               self.effective_settings, validate_identity)
        self.journal_path = self.directory / ('.wmp-head-migration-' + uuid.uuid4().hex + '.json')
        self.state = 'reviewed'

    def _read(self, name):
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError('Linked head migration destination: ' + name)
        try:
            with path.open('rb') as stream:
                raw = stream.read(2 * 1024 * 1024 + 1)
        except FileNotFoundError:
            return None
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Head migration destination is too large')
        return raw

    def _journal(self, state):
        record = {'version': 1, 'state': state, 'session': self.session,
                  'observed_ids': self.observed_ids, 'effective_settings': self.effective_settings,
                  'files': [{'name': name, 'before': before.hex() if before is not None else None,
                             'after': self.planned[name].hex() if self.planned[name] is not None else None}
                            for name, before in self.original.items()]}
        atomic_write(self.journal_path, (json.dumps(record, sort_keys=True, allow_nan=False) + '\n').encode())
        self.state = state

    def _check(self, expected):
        for name, content in expected.items():
            if self._read(name) != content:
                raise ValueError('Head migration snapshot changed: ' + name)

    def publish(self, admit):
        if self.state != 'reviewed' or not callable(admit) or admit() is not True:
            raise ValueError('Head migration publication is not admitted')
        self._check(self.original)
        self._journal('prepared')
        try:
            self._journal('publishing')
            expected = dict(self.original)
            for name, before in self.original.items():
                if admit() is not True:
                    raise ValueError('Head migration admission changed')
                self._check(expected)
                after = self.planned[name]
                if before != after:
                    # The current same-hardware planner only modifies existing
                    # files. It never invents or deletes an absent state file.
                    atomic_write(self.directory / name, after)
                    expected[name] = after
            self._check(self.planned)
            self._journal('published')
            return self.journal_path
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        if self.state not in ('prepared', 'publishing', 'published', 'restoring', 'rollback-unconfirmed'):
            raise ValueError('Head migration has no unresolved publication')
        # Detect known conflicts across the whole write set before undoing any
        # member; never overwrite a later manual edit to make rollback succeed.
        try:
            for name, before in self.original.items():
                if self._read(name) not in (before, self.planned[name]):
                    raise ValueError('Concurrent edit during head migration: ' + name)
            self._journal('restoring')
            for name, before in reversed(list(self.original.items())):
                current = self._read(name)
                if current == before:
                    continue
                if current != self.planned[name] or before is None:
                    raise ValueError('Concurrent edit during head migration: ' + name)
                atomic_write(self.directory / name, before)
            self._check(self.original)
            self._journal('rolled-back')
        except Exception as error:
            self._journal('rollback-unconfirmed')
            raise RuntimeError('Head migration rollback needs inspection: ' + str(self.journal_path)) from error

    @classmethod
    def reopen(cls, directory, journal, validate_identity):
        """Read durable evidence; never continue an interrupted publication."""
        operation = cls.__new__(cls)
        operation.directory = Path(directory).resolve()
        operation.journal_path = Path(journal).absolute()
        if (operation.journal_path.parent != operation.directory or operation.journal_path.is_symlink()
                or not re.fullmatch(r'\.wmp-head-migration-[0-9a-f]{32}\.json', operation.journal_path.name)):
            raise ValueError('Invalid head migration journal path')
        with operation.journal_path.open('rb') as stream:
            raw = stream.read(40 * 1024 * 1024 + 1)
        if len(raw) > 40 * 1024 * 1024:
            raise ValueError('Head migration journal is too large')
        record = json.loads(raw)
        if (not isinstance(record, dict) or record.get('version') != 1
                or record.get('state') not in ('prepared', 'publishing', 'published', 'restoring', 'rollback-unconfirmed')):
            raise ValueError('Journal does not describe an unresolved head migration')
        operation.state = record['state']
        operation.session = record['session']
        operation.observed_ids = record['observed_ids']
        operation.effective_settings = record['effective_settings']
        operation.validate_identity = validate_identity
        rows = record['files']
        if not isinstance(rows, list) or len(rows) != len({row['name'] for row in rows}):
            raise ValueError('Invalid head migration journal files')
        operation.original = {row['name']: bytes.fromhex(row['before']) if row['before'] is not None else None for row in rows}
        operation.planned = {row['name']: bytes.fromhex(row['after']) if row['after'] is not None else None for row in rows}
        expected = plan_head_configuration(operation.original, operation.observed_ids,
                                           operation.effective_settings, validate_identity)
        if operation.planned != expected:
            raise ValueError('Head migration journal differs from reviewed transformation')
        return operation

    def verify_loaded(self, session, effective_settings, admit):
        if (self.state != 'published' or not isinstance(session, str) or not session
                or session == self.session or not callable(admit) or admit() is not True):
            raise ValueError('Head migration requires fresh post-restart verification')
        self._check(self.planned)
        verified = plan_head_configuration(self.planned, self.observed_ids,
                                            effective_settings, self.validate_identity)
        if verified != self.planned:
            raise ValueError('Loaded head configuration does not match migration')
        self._check(self.planned)
        if admit() is not True:
            raise ValueError('Head migration verification admission changed')
        self._journal('verified')


class MappingTransaction:
    def __init__(self, directory, count, current_state_only=False):
        if type(count) is not int or not 1 <= count <= 4:
            raise ValueError('Identification requires one to four heads')
        self.directory = Path(directory).resolve()
        if not current_state_only:
            require_resolved_journals(self.directory)
        self.original = {}
        self.original_ids = set()
        self.staged = {}
        self.failure = ''
        self.committed = False
        self.journal_path = self.directory / ('.wmp-identification-' + uuid.uuid4().hex + '.json')
        for head in range(count):
            name = 'wm_zru_thr%d.cfg' % head
            content = self._read(name)
            matches = list(UUID_LINE.finditer(content))
            if len(matches) != 1 or len(re.findall(rb'(?m)^[ \t]*canbus_uuid[ \t]*:', content)) != 1:
                raise ValueError('Expected exactly one valid canbus_uuid in ' + name)
            identity = matches[0].group(2).decode().lower()
            if identity in self.original_ids:
                raise ValueError('Existing UUID mapping contains duplicates')
            self.original_ids.add(identity)
            self.original[name] = content

    def _read(self, name):
        path = self.directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked head configuration: ' + name)
        return path.read_bytes()

    def fail(self, message):
        # A later stage cannot clear an earlier failure.
        if not self.failure:
            self.failure = str(message) or 'Identification failed'

    def stage(self, head, identity):
        if self.failure or self.committed:
            raise ValueError(self.failure or 'Identification already committed')
        if type(head) is not int or not 0 <= head < len(self.original):
            self.fail('Invalid physical head index')
            raise ValueError(self.failure)
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9a-fA-F]{12}', identity):
            self.fail('Invalid observed UUID')
            raise ValueError(self.failure)
        identity = identity.lower()
        if identity not in self.original_ids:
            self.fail('Observed UUID is not in the connected head set')
        elif head in self.staged and self.staged[head] != identity:
            self.fail('Physical head identity changed during setup')
        elif any(other != head and value == identity for other, value in self.staged.items()):
            self.fail('Two physical heads report the same UUID')
        if self.failure:
            raise ValueError(self.failure)
        self.staged[head] = identity

    def _journal(self, state, replacements, errors=()):
        content = {'version': 1, 'state': state, 'failure': self.failure,
                   'rollback_errors': list(errors), 'files': [
                       {'name': name, 'before': before.hex(), 'after': replacements[name].hex()}
                       for name, before in self.original.items()]}
        atomic_write(self.journal_path, (json.dumps(content, indent=2) + '\n').encode())

    def _restore(self, names, replacements):
        failures = []
        for name in reversed(list(names)):
            try:
                current = self._read(name)
                if current == self.original[name]:
                    continue
                if current != replacements[name]:
                    raise ValueError('Concurrent edit; refusing to overwrite ' + name)
                atomic_write(self.directory / name, self.original[name])
                if self._read(name) != self.original[name]:
                    raise ValueError('UUID rollback readback failed: ' + name)
            except Exception as rollback_error:
                failures.append(str(rollback_error))
        self._journal('rollback-unconfirmed' if failures else 'rolled-back', replacements, failures)
        if failures:
            raise RuntimeError('UUID rollback needs inspection: ' + str(self.journal_path) + ': ' + '; '.join(failures))

    @classmethod
    def recover(cls, directory, journal):
        """Explicitly restore an interrupted transaction; never resume setup."""
        operation = cls.__new__(cls)
        operation.directory = Path(directory).resolve()
        operation.journal_path = Path(journal).absolute()
        if (operation.journal_path.parent != operation.directory or operation.journal_path.is_symlink()
                or not re.fullmatch(r'\.wmp-identification-[0-9a-f]{32}\.json', operation.journal_path.name)):
            raise ValueError('Invalid identification journal path')
        record = json.loads(operation.journal_path.read_text())
        if record.get('version') != 1 or record.get('state') not in ('prepared', 'publishing', 'rollback-unconfirmed'):
            raise ValueError('Journal does not describe an interrupted identification')
        rows = record.get('files', [])
        if not 1 <= len(rows) <= 4 or [row.get('name') for row in rows] != ['wm_zru_thr%d.cfg' % n for n in range(len(rows))]:
            raise ValueError('Invalid journal head set')
        operation.original = {}
        replacements = {}
        before_ids, after_ids = set(), set()
        for row in rows:
            before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
            old, new = list(UUID_LINE.finditer(before)), list(UUID_LINE.finditer(after))
            if (len(old) != 1 or len(new) != 1 or
                    len(re.findall(rb'(?m)^[ \t]*canbus_uuid[ \t]*:', before)) != 1):
                raise ValueError('Invalid journal UUID content')
            expected = before[:old[0].start(2)] + new[0].group(2) + before[old[0].end(2):]
            if after != expected:
                raise ValueError('Journal changes more than the UUID')
            before_ids.add(old[0].group(2).lower())
            after_ids.add(new[0].group(2).lower())
            operation.original[row['name']] = before
            replacements[row['name']] = after
        if len(before_ids) != len(rows) or before_ids != after_ids:
            raise ValueError('Invalid journal UUID permutation')
        operation.failure = 'Interrupted identification restored; start setup again explicitly'
        operation.committed = False
        operation._restore(operation.original, replacements)
        return operation.journal_path

    def commit(self, final_dock_confirmed=False, admit=None):
        if self.failure or self.committed:
            raise ValueError(self.failure or 'Identification already committed')
        if final_dock_confirmed is not True or len(self.staged) != len(self.original):
            self.fail('All heads and final docking must be confirmed before saving')
            raise ValueError(self.failure)
        replacements = {}
        try:
            if admit is not None and admit() is not True:
                raise ValueError('Identification publication ownership changed')
            for head, (name, before) in enumerate(self.original.items()):
                if self._read(name) != before:
                    raise ValueError('Head configuration changed during setup: ' + name)
                replacements[name] = UUID_LINE.sub(lambda m: m.group(1) + self.staged[head].encode() + m.group(3) + m.group(4), before)
            self._journal('prepared', replacements)
        except Exception as error:
            self.fail(str(error))
            raise
        attempted = []
        try:
            self._journal('publishing', replacements)
            for name, before in self.original.items():
                if admit is not None and admit() is not True:
                    raise ValueError('Identification publication ownership changed')
                if self._read(name) != before:
                    raise ValueError('Head configuration changed during publication: ' + name)
                if before == replacements[name]:
                    continue
                attempted.append(name)  # Include committed writes with lost replies.
                atomic_write(self.directory / name, replacements[name])
                if self._read(name) != replacements[name]:
                    raise ValueError('UUID publication readback failed: ' + name)
            self._journal('committed', replacements)
            self.committed = True
            return self.journal_path
        except Exception as error:
            self.fail(str(error))
            self._restore(attempted, replacements)
            raise


class AssignmentRepairTransaction(MappingTransaction):
    """Explicit UUID assignment repair; all slot settings remain in place.

    The caller must confirm that heads have not moved and that existing slot
    settings are correct. This is not a physical-head relocation planner.
    """
    def __init__(self, directory, count, material, effective_settings, admit):
        super().__init__(directory, count, current_state_only=True)
        self.session, self.admit = material.session_id, admit
        for head, raw in enumerate(self.original.values()):
            identity = UUID_LINE.search(raw).group(2).decode().lower()
            if effective_settings.get('mcu T%d' % head, {}).get('canbus_uuid', '').lower() != identity:
                raise ValueError('Loaded UUID assignment differs from configuration; restart before assignment repair')

    def _journal(self, state, replacements, errors=()):
        content = {'version': 1, 'state': state, 'failure': self.failure,
                   'mode': 'repair_assignment', 'session': self.session,
                   'confirmation': 'unmoved_heads_and_correct_slot_settings',
                   'rollback_errors': list(errors), 'files': [
                       {'name': name, 'before': before.hex(), 'after': replacements[name].hex()}
                       for name, before in self.original.items()]}
        atomic_write(self.journal_path, (json.dumps(content, indent=2) + '\n').encode())

    def commit(self, final_dock_confirmed=False):
        return super().commit(final_dock_confirmed, admit=self.admit)

    @staticmethod
    def verify_loaded(directory, journal, record, session, settings):
        if (record.get('state') != 'committed' or not session
                or session == record.get('session')
                or record.get('confirmation') != 'unmoved_heads_and_correct_slot_settings'):
            raise ValueError('UUID assignment repair needs a fresh Klipper session for verification')
        rows = record.get('files', [])
        if (not isinstance(rows, list) or not 1 <= len(rows) <= 4
                or [row.get('name') for row in rows] != ['wm_zru_thr%d.cfg' % n for n in range(len(rows))]):
            raise ValueError('Invalid UUID assignment repair head set')
        old, new = [], []
        for head, row in enumerate(rows):
            before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
            prior, current = list(UUID_LINE.finditer(before)), list(UUID_LINE.finditer(after))
            if len(prior) != 1 or len(current) != 1:
                raise ValueError('Invalid UUID assignment repair content')
            expected = before[:prior[0].start(2)] + current[0].group(2) + before[prior[0].end(2):]
            if after != expected:
                raise ValueError('Assignment repair journal changes more than UUIDs')
            old.append(prior[0].group(2).decode().lower())
            identity = current[0].group(2).decode().lower()
            new.append(identity)
            path = Path(directory) / row['name']
            if path.is_symlink() or path.read_bytes() != after:
                raise ValueError('UUID assignment repair configuration changed: ' + row['name'])
            if settings.get('mcu T%d' % head, {}).get('canbus_uuid', '').lower() != identity:
                raise ValueError('Loaded UUID assignment does not match repaired configuration')
        _verified_permutation(old, new)
        record = dict(record, verified_session=session)
        atomic_write(journal, (json.dumps(record, indent=2) + '\n').encode())


class ManagedMappingTransaction(MappingTransaction):
    """Identification's staged observations publish the whole head candidate."""
    def __init__(self, directory, count, material, effective_settings, admit):
        # Explicit managed retry validates the current files against the loaded
        # configuration below. Old/corrupt journals remain diagnostic evidence,
        # not authorization to start or a prerequisite for a new attempt.
        super().__init__(directory, count, current_state_only=True)
        if admit() is not True:
            raise ValueError('Managed head identification is not admitted')
        identities = [UUID_LINE.search(raw).group(2).decode().lower() for raw in self.original.values()]
        self.joint = HeadConfigurationTransaction(directory, identities, effective_settings,
                                                  material._validate_identity, material.session_id,
                                                  current_state_only=True)
        self.admit = admit

    def commit(self, final_dock_confirmed=False):
        if self.failure or self.committed:
            raise ValueError(self.failure or 'Identification already committed')
        if final_dock_confirmed is not True or len(self.staged) != len(self.original):
            self.fail('All heads and final docking must be confirmed before saving')
            raise ValueError(self.failure)
        try:
            self.joint.observed_ids = [self.staged[h] for h in range(len(self.original))]
            previous_ids = [UUID_LINE.search(raw).group(2).decode().lower()
                            for raw in self.original.values()]
            if self.joint.observed_ids != previous_ids:
                # Identification can repair a previously wrong UUID assignment;
                # that old assignment is not proof of which heater was tuned.
                # Do not automatically relocate calibration using it as fact.
                # The explicit topology workflow still needs durable calibration
                # provenance, dock/offset policy and reference-mesh handling.
                raise ValueError('Observed head mapping differs; review calibration ownership and tool offsets. If heads have not moved and existing slot settings are correct, explicitly retry _WMP_IDENTIFY_HEADS with the current SESSION and a new REQUEST, MODE=repair_assignment CONFIRM_UNMOVED_SLOT_SETTINGS=1 to change UUIDs only. Physically relocated heads require calibration ownership review; their settings cannot be inferred from the old UUID map. Other printer operations remain available.')
            self.joint.planned = plan_head_configuration(
                self.joint.original, self.joint.observed_ids, self.joint.effective_settings,
                self.joint.validate_identity)
            journal = self.joint.publish(self.admit)
            self.committed = True
            return journal
        except Exception as error:
            self.fail(str(error))
            raise


class IdentificationCommands:
    """Explicit attempts with queryable results and no automatic replay."""
    def __init__(self, printer, gcode, calibration):
        self.printer, self.gcode, self.calibration = printer, gcode, calibration
        self.operation = None
        self.failure = ''
        self.requests = {}
        self.request_result = None

    def _migration_admission(self, material, session, fresh_action=False):
        """Fresh owner/job admission; retain the first failed condition for callers."""
        self.migration_refusal = ''
        def refuse(reason):
            self.migration_refusal = reason[:256]
            return False
        try:
            now = self.printer.get_reactor().monotonic()
            if self.printer.is_shutdown(): return refuse('printer is shut down')
            if getattr(self.gcode, 'quick_stop_flag', False): return refuse('gcode.quick_stop_flag is set')
            if self.printer.lookup_object('wm_material', None) is not material: return refuse('wm_material owner object changed')
            if material.session_id != session: return refuse('material session changed')
            if self.calibration.active: return refuse('calibration.active=True')
            if self.calibration.probe_editor.busy() is not False: return refuse('probe editor is busy or its state is unavailable')
            if self.printer.lookup_object('openace', None) is not None: return refuse('openace owns filament control')
            if self.printer.lookup_object('AFC', None) is not None: return refuse('AFC owns filament control')
            status = lambda name: self.printer.lookup_object(name).get_status(now)
            sd = self.printer.lookup_object('virtual_sdcard')
            state = status('print_stats').get('state')
            if state not in ('standby', 'complete', 'cancelled', 'error'): return refuse('print_stats.state=' + repr(state)[:80])
            paused = status('pause_resume').get('is_paused')
            if paused is not False: return refuse('pause_resume.is_paused=' + repr(paused)[:80])
            if sd.is_active() is not False: return refuse('virtual_sdcard is active or activity is unavailable')
            if sd.is_cmd_from_sd() is not False: return refuse('command originates from virtual_sdcard or origin is unavailable')
            if material._print_cancel_active() is not False: return refuse('print cancellation is active')
            if material._recovery_attempt_active() is not False: return refuse('print recovery attempt is active')
            for name in ('filament_operation', 'toolhead_operation'):
                state = getattr(material, name).get('state')
                if state in ('pending', 'running'): return refuse(name + '.state=' + state)
            # A stopped file, recovery record or old result is not execution.
            # Publication still validates the complete current configuration;
            # admission must not turn diagnostic history into a machine lock.
            variables = status('save_variables').get('variables', {})
            if not fresh_action and variables.get('fail_flag') != 0: return refuse('saved fail_flag=' + repr(variables.get('fail_flag'))[:80])
            return True
        except (AttributeError, KeyError, TypeError, ValueError, OSError) as error:
            return refuse('admission evidence unavailable: ' + type(error).__name__ + ': ' + str(error)[:160])

    def check_startup(self):
        """Verify a completed publication; interrupted setup is never resumed."""
        try:
            directory = Path(self.printer.get_start_args()['config_file']).resolve().parent
            now = self.printer.get_reactor().monotonic()
            saved = self.printer.lookup_object('save_variables').get_status(now)['variables']
            if saved.get('is_nozzle_setting') != 0:
                raise ValueError('Previous head identification mode is unresolved; inspect the printer, then retry Head identification to restore normal sensor checks')
            # Successful publication may be accepted only after the restarted
            # backend proves the exact candidate was loaded. Interrupted writes
            # are never replayed or automatically rolled back here.
            material = self.printer.lookup_object('wm_material', None)
            for journal in directory.glob('.wmp-head-migration-*.json'):
                if journal.is_symlink():
                    raise ValueError('Linked head migration journal needs inspection')
                record = json.loads(journal.read_text())
                if isinstance(record, dict) and record.get('state') == 'published':
                    if material is None:
                        raise ValueError('Managed filament owner unavailable for migration verification')
                    transaction = HeadConfigurationTransaction.reopen(directory, journal, material._validate_identity)
                    session = material.session_id
                    settings = self.printer.lookup_object('configfile').get_status(
                        self.printer.get_reactor().monotonic())['settings']
                    transaction.verify_loaded(session, settings, lambda: self._migration_admission(material, session))
            require_resolved_journals(directory)
            for journal in directory.glob('.wmp-identification-*.json'):
                record = json.loads(journal.read_text())
                if (record.get('mode') == 'repair_assignment' and record.get('state') == 'committed'
                        and not record.get('verified_session')):
                    if material is None:
                        raise ValueError('Material session unavailable for UUID assignment verification')
                    settings = self.printer.lookup_object('configfile').get_status(now)['settings']
                    AssignmentRepairTransaction.verify_loaded(
                        directory, journal, record, material.session_id, settings)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Historical evidence is a warning, not a global movement lock.
            # Each new identification still validates its current configuration.
            self.failure = str(error)

    def get_status(self):
        result = self.operation.status() if self.operation else {
            'state': 'failed' if self.failure else 'idle', 'steps': [], 'failure': self.failure}
        result['protocol'] = 2
        if self.request_result is not None:
            result['request_result'] = dict(self.request_result)
        result['restart_required'] = result['state'] == 'complete'
        return result

    def dispatch(self, gcmd):
        session, request = gcmd.get('SESSION', ''), gcmd.get('REQUEST', '')
        if session != self.calibration.session or not re.fullmatch(r'[0-9a-f]{32}', request):
            raise gcmd.error('Stale or invalid identification request: ' + ('SESSION differs from calibration session' if session != self.calibration.session else 'REQUEST must contain 32 lowercase hexadecimal characters'))
        if request in self.requests:
            self.request_result = self.requests[request]
            gcmd.respond_info('Identification request already recorded; inspect its result')
            return
        if len(self.requests) >= 128:
            raise gcmd.error('Identification request history is full; inspect before restarting')
        result = dict(session=session, request=request, state='pending', error='')
        self.requests[request] = self.request_result = result
        try:
            self.run(gcmd)
        except Exception as error:
            result.update(state='failed' if self.operation is not None or self.failure else 'refused',
                          error=str(error)[:512])
            raise
        result['state'] = 'complete'

    def run(self, gcmd):
        if self.operation is not None and self.operation.state in ('pending', 'running', 'complete'):
            raise gcmd.error('Head identification is running or its published mapping needs a Klipper restart')
        mode = gcmd.get('MODE', 'identify')
        if mode not in ('identify', 'repair_assignment'):
            raise gcmd.error('Identification MODE must be identify or repair_assignment')
        confirmation = gcmd.get('CONFIRM_UNMOVED_SLOT_SETTINGS', '')
        if mode == 'repair_assignment' and confirmation != '1':
            raise gcmd.error('Assignment repair requires CONFIRM_UNMOVED_SLOT_SETTINGS=1: confirm heads have not moved and existing per-slot calibration, nozzle and filament settings are correct')
        if mode == 'identify' and confirmation != '':
            raise gcmd.error('CONFIRM_UNMOVED_SLOT_SETTINGS is valid only with MODE=repair_assignment')
        # A fresh explicit request retries against present conditions. Keep the
        # old correlated receipt in requests; never replay its partial sequence.
        self.operation, self.failure = None, ''
        # Refuse competing editor ownership before latching identification mode.
        # Completed review and failed results do not reserve the printer.
        try:
            editor_idle = self.calibration.probe_editor.busy() is False
        except (AttributeError, TypeError, ValueError):
            editor_idle = False
        if not editor_idle:
            raise gcmd.error('Close or resolve the probe editor before head identification')
        material = self.printer.lookup_object('wm_material', None)
        if material is not None and (not material.session_id or not self._migration_admission(material, material.session_id, fresh_action=True)):
            # Ordinary competing work is a refusal, not a partially executed
            # identification. It must not poison later calibration after the
            # existing job/recovery/owner resolves. Recheck inside the admitted
            # transaction as well, before any command or configuration write.
            raise gcmd.error('Resolve the active printer operation before head identification: ' + ('material session is unavailable' if not material.session_id else self.migration_refusal))
        try:
            if material is not None:
                material._begin_explicit_physical_action('head identification')
            self.calibration.failure = ''
            now = self.printer.get_reactor().monotonic()
            saved = self.printer.lookup_object('save_variables').get_status(now)['variables']
            count = saved.get('thr_number')
            # Do not silently truncate malformed configuration values.
            if type(count) is not int or not 1 <= count <= 4:
                raise ValueError('Configured head count is unavailable or invalid')
            directory = Path(self.printer.get_start_args()['config_file']).resolve().parent
            material = self.printer.lookup_object('wm_material', None)
            if material is None:
                raise ValueError('Managed filament owner required for head identification')
            session = material.session_id
            if Path(material.profile_path).resolve().parent != directory:
                raise ValueError('Head migration requires filament records in the configuration directory')
            settings = self.printer.lookup_object('configfile').get_status(now)['settings']
            generation = getattr(material, '_command_generation', 0)
            def owned():
                return (self.printer.lookup_object('wm_material', None) is material
                        and material.session_id == session
                        and getattr(material, '_command_generation', 0) == generation
                        and self.printer.lookup_object('openace', None) is None
                        and self.printer.lookup_object('AFC', None) is None)
            def admitted():
                if not owned():
                    self.migration_refusal = 'Identification command ownership changed'
                    return False
                return self._migration_admission(material, session)
            transaction_type = AssignmentRepairTransaction if mode == 'repair_assignment' else ManagedMappingTransaction
            transaction = transaction_type(
                directory, count, material, settings, admitted)
            def execute_owned(command):
                # Also fence M400 and failure cleanup. Never let an old attempt
                # clear a newer owner's identification mode after cancellation.
                if not owned():
                    raise ValueError('Identification command ownership changed; inspect before recovery')
                self.gcode.run_script_from_command(command)
            self.operation = IdentificationSession(
                transaction, KlipperObservation(
                    self.printer, count, self.calibration,
                    admitted, lambda: self.migration_refusal),
                execute_owned, self.printer.invoke_shutdown)
            self.operation.run()
            self.calibration.identification_blocked = True
            gcmd.respond_info('Head identification complete. Restart Klipper to apply the head mapping.')
        except Exception as error:
            message = str(error) or 'Head identification failed'
            # Structural validation never started an operation and cannot create
            # a physical-failure latch. Retain a correlated refused response.
            if self.operation is not None:
                self.failure = message
            raise gcmd.error(message)


class KlipperObservation:
    """Read the setup preconditions without motion or inferred sensor defaults."""
    def __init__(self, printer, count, calibration, admit=None, refusal_reason=None):
        self.printer, self.count, self.calibration = printer, count, calibration
        self.admit = admit
        self.refusal_reason = refusal_reason

    def __call__(self):
        now = self.printer.get_reactor().monotonic()

        def status(name):
            obj = self.printer.lookup_object(name, None)
            return obj.get_status(now) if obj is not None else {}

        saved = status('save_variables').get('variables', {})
        docks = [status('filament_switch_sensor docked%d' % n).get('filament_detected')
                 for n in range(self.count)]
        hall = status('custom_hall').get('Raw')
        lock = status('filament_switch_sensor sensor_b').get('filament_detected')
        mounted = None
        if type(hall) in (int, float) and 3450 <= hall <= 6000:
            if hall < 4700 and lock is True:
                mounted = True
            elif hall >= 4700 and lock is False:
                mounted = False
        material = self.printer.lookup_object('wm_material', None)
        busy_reason = ''
        for name in ('filament_operation', 'toolhead_operation'):
            operation_state = getattr(material, name, {}).get('state')
            if operation_state in ('pending', 'running'):
                busy_reason = name + '.state=' + operation_state
                break
        busy = bool(busy_reason)
        # Identification has no ACE coordination protocol yet. Refuse instead
        # of racing the other controller's source or tool operations.
        if not busy and self.printer.lookup_object('openace', None) is not None:
            busy, busy_reason = True, 'openace is present'
        sd = self.printer.lookup_object('virtual_sdcard', None)
        try:
            sd_reason = ('virtual_sdcard.is_active is not False' if sd.is_active() is not False else
                         'virtual_sdcard.is_cmd_from_sd is not False' if sd.is_cmd_from_sd() is not False else '')
            sd_idle = not sd_reason
        except (AttributeError, TypeError, ValueError) as error:
            sd_idle = False
            sd_reason = 'virtual_sdcard evidence unavailable: ' + type(error).__name__
        mode = saved.get('is_nozzle_setting')
        idle_reason = []
        def idle():
            state = status('print_stats').get('state')
            if state not in ('standby', 'complete', 'cancelled', 'error'):
                idle_reason.append('print_stats.state=' + repr(state)[:80])
            elif not sd_idle:
                idle_reason.append(sd_reason)
            elif busy:
                idle_reason.append(busy_reason)
            elif self.calibration.active:
                idle_reason.append('calibration.active=True')
            elif self.admit is not None and self.admit() is not True:
                idle_reason.append('migration admission refused: ' +
                                   (str(self.refusal_reason())[:160] if self.refusal_reason else 'current migration admission changed'))
            return not idle_reason
        return dict(
            ready=not self.printer.is_shutdown(),
            idle=idle(), idle_reason=idle_reason[0] if idle_reason else '',
            paused=status('pause_resume').get('is_paused'),
            fault=saved.get('fail_flag'),
            recovery_ready=status('gcode_macro Z_HOMING').get('z_raise') == 1,
            docked=docks, mounted=mounted,
            homed_axes=status('toolhead').get('homed_axes', ''),
            identifying=(mode == 1) if type(mode) in (int, float) and mode in (0, 1) else None,
            toolchange_success=status('gcode_macro _WMP_TOOL_RETURN_BEGIN').get('success') == 1)


class IdentificationSession:
    """Setup sequence with explicit sensor postconditions and sticky failure.

    observe() supplies fresh backend state; execute() must synchronously run the
    command or raise. The Klipper/UI adapter is separate. shutdown() is required
    when the identification-mode flag cannot be cleared after a failed stage.
    """
    def __init__(self, transaction, observe, execute, shutdown):
        self.transaction = transaction
        self.observe = observe
        self.execute = execute
        self.shutdown = shutdown
        self.count = len(transaction.original)
        self.identities = [UUID_LINE.search(content).group(2).decode().lower()
                           for content in transaction.original.values()]
        self.steps = ['Prepare printer'] + ['Identify Head %d' % (n + 1) for n in range(self.count)] + ['Dock head', 'Save head mapping']
        self.completed = 0
        self.state = 'pending'
        self.failure = ''
        self.mode_may_be_set = False

    def status(self):
        return {'state': self.state, 'failure': self.failure,
                'steps': [{'number': n + 1, 'label': label,
                           'state': 'complete' if n < self.completed else
                           ('failed' if self.state == 'failed' else 'active') if n == self.completed and self.state != 'pending' else 'pending'}
                          for n, label in enumerate(self.steps)]}

    def _check(self):
        state = self.observe()
        if state.get('ready') is not True or state.get('idle') is not True or state.get('paused') is not False:
            raise ValueError('Identification requires a ready, idle printer: ' + ('ready=' + repr(state.get('ready'))[:80] if state.get('ready') is not True else 'idle=False; ' + str(state.get('idle_reason', 'inspect print, SD, owner and calibration state'))[:160] if state.get('idle') is not True else 'paused=' + repr(state.get('paused'))[:80]))
        if state.get('fault') != 0 or state.get('recovery_ready') is not True:
            raise ValueError('Resolve the toolhead fault or print recovery before identification: ' + ('fail_flag=' + repr(state.get('fault'))[:80] if state.get('fault') != 0 else 'Z_HOMING.z_raise is not 1'))
        docked = state.get('docked')
        if not isinstance(docked, list) or len(docked) != self.count or any(type(value) is not bool for value in docked):
            raise ValueError('Head dock sensor state is unavailable')
        if type(state.get('mounted')) is not bool:
            raise ValueError('Carriage attachment state is unavailable')
        return state

    def _command(self, command):
        self._check()
        self.execute(command)
        self.execute('M400')
        return self._check()

    def _docked(self, state):
        if state['mounted'] or not all(state['docked']):
            raise ValueError('All heads must be seated and the carriage released')

    def run(self):
        if self.state != 'pending':
            raise ValueError('Identification cannot be resumed or repeated')
        self.state = 'running'
        try:
            state = self._check()
            if state.get('identifying') is not False:
                raise ValueError('Previous identification mode is unresolved')
            self._docked(state)
            if not set('xyz').issubset(state.get('homed_axes', '')):
                state = self._command('G28')
                if not set('xyz').issubset(state.get('homed_axes', '')):
                    raise ValueError('Homing completion was not confirmed')
            self._docked(self._command('PARK_CURRENT_TOOL'))
            # Set before dispatch so a lost/failed command reply still cleans up.
            self.mode_may_be_set = True
            if self._command('SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=1').get('identifying') is not True:
                raise ValueError('Identification mode was not confirmed')
            self.completed += 1
            for physical in range(self.count):
                state = self._command('_CHANGE_TOOL T=%d' % physical)
                missing = [n for n, present in enumerate(state['docked']) if not present]
                if not state['mounted'] or len(missing) != 1 or state.get('toolchange_success') is not True:
                    raise ValueError('Pickup of Head %d was not confirmed' % (physical + 1))
                self.transaction.stage(physical, self.identities[missing[0]])
                self.completed += 1
            self._docked(self._command('PARK_CURRENT_TOOL'))
            if self._command('SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0').get('identifying') is not False:
                raise ValueError('Identification mode did not clear')
            self.mode_may_be_set = False
            self.completed += 1
            self._docked(self._check())
            journal = self.transaction.commit(final_dock_confirmed=True)
            self.completed += 1
            self.state = 'complete'
            return journal
        except Exception as error:
            self.failure = str(error) or 'Identification failed'
            self.state = 'failed'
            self.transaction.fail(self.failure)
            if self.mode_may_be_set:
                try:
                    # No motion, retry, UUID write or firmware restart on failure.
                    self.execute('SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0')
                    if self.observe().get('identifying') is not False:
                        raise ValueError('Identification mode is still active or unknown')
                    self.mode_may_be_set = False
                except Exception as cleanup_error:
                    self.failure += '; unable to clear identification mode: ' + str(cleanup_error)
                    self.shutdown(self.failure)
            raise
