"""Durable, non-executable receipts for multi-component installation recovery.

An interrupted component is explicitly ambiguous. A journal is not proof that a
remote process stopped, and recovery must not infer completion from its age.
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile


WINDOWS = os.name == 'nt'


COMPONENTS = {'config', 'material', 'touchscreen', 'moonraker', 'preload', 'shaper'}


def encode(value):
    if isinstance(value, bytes):
        return {'type': 'bytes', 'data': base64.b64encode(value).decode('ascii')}
    if isinstance(value, (tuple, list)):
        return {'type': 'list', 'data': [encode(item) for item in value]}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError('Receipt keys must be strings')
        return {'type': 'dict', 'data': {key: encode(item) for key, item in value.items()}}
    if value is None or type(value) in (str, int, bool):
        return {'type': 'value', 'data': value}
    raise ValueError('Unsupported receipt value')


def decode(value):
    if not isinstance(value, dict) or set(value) != {'type', 'data'}:
        raise ValueError('Invalid encoded receipt')
    kind, data = value['type'], value['data']
    if kind == 'bytes' and isinstance(data, str):
        return base64.b64decode(data, validate=True)
    if kind == 'list' and isinstance(data, list):
        return [decode(item) for item in data]
    if kind == 'dict' and isinstance(data, dict):
        return {key: decode(item) for key, item in data.items()}
    if kind == 'value' and (data is None or type(data) in (str, int, bool)):
        return data
    raise ValueError('Unsupported encoded receipt')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_machine_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value) or value == '0' * 32:
        raise ValueError('Printer machine-id must be a nonzero 32-character lowercase hex value')
    return value


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.value = None
        self._lock_fd = None

    def acquire(self):
        if self._lock_fd is not None:
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = Path(str(self.path) + '.lock')
        if lock_path.is_symlink():
            raise OSError('Linked installer journal lock')
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if WINDOWS:
                import msvcrt
                # Windows byte-range locks may extend past EOF. Keep position 0.
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(fd)
            raise ValueError('Installer journal is locked by another process')
        self._lock_fd = fd

    def release(self):
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def save(self):
        if self.path.is_symlink():
            raise ValueError('Linked installer journal')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = dict(record=self.value, sha256=digest(self.value))
        fd, temporary = tempfile.mkstemp(prefix='.wmp-journal-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(json.dumps(payload, sort_keys=True).encode())
                stream.flush()
                if not WINDOWS:
                    os.fchmod(stream.fileno(), 0o600)
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if not WINDOWS:
                parent = os.open(self.path.parent, os.O_RDONLY)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, host, user, components, machine_id=None):
        if self.path.exists() or self.path.is_symlink():
            raise ValueError('Installer journal already exists')
        if not isinstance(host, str) or not host or not isinstance(user, str) or not user:
            raise ValueError('Installer journal needs explicit printer identity')
        if not components or len(set(components)) != len(components) or any(name not in COMPONENTS for name in components):
            raise ValueError('Invalid installation component list')
        self.value = dict(version=1, host=host, user=user, components=list(components),
                          state='installing', inflight=None, completed=[], restored=[])
        if machine_id is not None:
            self.value['machine_id'] = validate_machine_id(machine_id)
        self.save()

    def read_record(self):
        if self.path.is_symlink():
            raise ValueError('Linked installer journal')
        payload = json.loads(self.path.read_text(encoding='utf-8'))
        record = payload['record']
        if payload.get('sha256') != digest(record):
            raise ValueError('Installer journal integrity mismatch')
        if record.get('version') != 1:
            raise ValueError('Installer journal belongs to a different printer or version: mismatched version')
        return record

    def load(self, host, user, machine_id=None):
        record = self.read_record()
        if record.get('user') != user:
            raise ValueError('Installer journal belongs to a different printer or version: mismatched user')
        bound = record.get('machine_id')
        if bound is not None:
            validate_machine_id(bound)
            if machine_id != bound:
                raise ValueError('Installer journal belongs to a different printer: machine-id mismatch; no recovery executed')
        elif record.get('host') != host:
            raise ValueError('Installer journal belongs to a different printer: mismatched host; legacy journal has no machine-id. '
                             'Read /etc/machine-id on the intended printer, then explicitly run rebind-journal all '
                             '--journal PATH --from-host %r --confirm-machine-id HEX with WMP_PRINTER=%r. '
                             'This updates only the local binding; it does not execute recovery.' % (record.get('host'), host))
        self.value = record
        if bound is None and machine_id is not None:
            self.value['machine_id'] = validate_machine_id(machine_id)
            self.save()
        return self

    def rebind(self, host, user, machine_id, previous_host, confirmed_machine_id):
        record = self.read_record()
        validate_machine_id(machine_id)
        if record.get('user') != user or record.get('host') != previous_host:
            raise ValueError('Rebind old destination/user does not match the journal; no binding changed')
        if confirmed_machine_id != machine_id:
            raise ValueError('Rebind confirmation differs from independently read printer machine-id; no binding changed')
        if record.get('machine_id') not in (None, machine_id):
            raise ValueError('Journal already binds a different machine-id; rebind cannot override device identity')
        if not isinstance(host, str) or not host:
            raise ValueError('Rebind requires a destination host')
        record.setdefault('binding_history', []).append(
            dict(host=record['host'], user=record['user'], machine_id=record.get('machine_id')))
        record['host'], record['machine_id'] = host, machine_id
        self.value = record
        self.save()
        return self

    def begin(self, name):
        if self.value['state'] != 'installing' or self.value['inflight'] is not None:
            raise ValueError('An installation operation is already unresolved: '
                             + ('journal.state is not installing' if self.value['state'] != 'installing'
                                else 'journal.inflight is not empty'))
        done = [row['component'] for row in self.value['completed']]
        if len(done) >= len(self.value['components']) or name != self.value['components'][len(done)]:
            raise ValueError('Unexpected installation order')
        self.value['inflight'] = name
        self.save()

    def complete_component(self, name, receipt):
        if self.value['inflight'] != name:
            raise ValueError('Component completion does not match the active operation')
        self.value['completed'].append({'component': name, 'receipt': encode(receipt)})
        self.value['inflight'] = None
        self.value.pop('prepared_receipt', None)
        self.save()

    def prepare_component(self, name, receipt):
        """Persist a complete undo plan before the component's first publication."""
        if self.value['state'] != 'installing' or self.value['inflight'] != name:
            raise ValueError('Undo plan does not match the active operation')
        supported = (name == 'material' and isinstance(receipt, list)) or (
            name == 'touchscreen' and isinstance(receipt, dict)
            and receipt.get('kind') == 'touchscreen-transaction'
            and isinstance(receipt.get('journal'), str)) or (
            name == 'config' and isinstance(receipt, dict)
            and receipt.get('kind') in ('preserved-screen-config', 'config-helpers')) or (
            name == 'moonraker' and isinstance(receipt, dict)
            and receipt.get('kind') == 'moonraker-directory'
            and isinstance(receipt.get('state'), str)
            and receipt.get('before') in ('original', 'installed')) or (
            name == 'moonraker' and isinstance(receipt, dict)
            and set(receipt) == {'kind', 'version', 'patches'}
            and receipt['kind'] == 'moonraker-patches'
            and type(receipt['version']) is int and receipt['version'] == 1
            and isinstance(receipt['patches'], list) and len(receipt['patches']) == 2
            and all(isinstance(entry, dict) and set(entry) == {'patch', 'state', 'before'}
                    and entry['patch'] == patch and isinstance(entry['state'], str)
                    and (entry['before'] in ('original', 'installed')
                         or patch == 'directory' and entry['before'] == 'previous')
                    for entry, patch in zip(receipt['patches'], ('directory', 'http-error')))) or (
            name == 'preload' and isinstance(receipt, dict)
            and receipt.get('kind') == 'preload-stage' and isinstance(receipt.get('stage'), str)) or (
            name == 'shaper' and isinstance(receipt, dict)
            and set(receipt) == {'kind', 'version', 'before'}
            and receipt['kind'] == 'shaper-backport'
            and type(receipt['version']) is int and receipt['version'] == 1
            and receipt['before'] in ('stock', 'installed'))
        if not supported:
            raise ValueError('Unsupported prepared component receipt')
        self.value['prepared_receipt'] = encode(receipt)
        self.save()

    def completed_recovery_receipts(self):
        return [(row['component'], decode(row['receipt']))
                for row in reversed(self.value['completed'])
                if row['component'] not in self.value['restored']]

    def recovery_receipts(self):
        inflight = self.value['inflight']
        prepared = self.value.get('prepared_receipt')
        if inflight is not None and (inflight not in COMPONENTS or prepared is None):
            raise ValueError('Interrupted component outcome is unknown: '+self.value['inflight'])
        if self.value['state'] not in ('installing', 'recovering'):
            raise ValueError('Journal is not eligible for installation recovery')
        return ([(inflight, decode(prepared))] if inflight is not None else []) + self.completed_recovery_receipts()

    def restored_component(self, name, *, retain_inflight=False):
        # The running installer can confirm undo of earlier receipts while a
        # later component's outcome remains unknown. Keep that ambiguity intact.
        if retain_inflight:
            pending = self.completed_recovery_receipts()
        else:
            pending = self.recovery_receipts()
        if not pending or pending[0][0] != name:
            raise ValueError('Unexpected recovery order')
        self.value['state'] = 'recovering'
        if name == self.value['inflight']:
            self.value['inflight'] = None
            self.value.pop('prepared_receipt', None)
        self.value['restored'].append(name)
        self.save()

    def finish(self, recovered=False):
        if recovered:
            if self.recovery_receipts():
                raise ValueError('Component restoration remains incomplete')
            self.value['state'] = 'restored'
        else:
            if (self.value['state'] != 'installing' or self.value['inflight'] is not None
                    or [row['component'] for row in self.value['completed']] != self.value['components']):
                raise ValueError('Installation remains incomplete')
            self.value['state'] = 'applied'
        self.save()
