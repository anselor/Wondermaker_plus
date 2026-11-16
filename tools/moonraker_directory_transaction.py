# SPDX-License-Identifier: GPL-3.0-or-later
"""Journaled local-file transaction for reviewed Moonraker patches.

Service lifecycle belongs to the caller. These functions never restart services
or infer that an interrupted remote service operation has completed.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from moonraker_directory_patch import candidate, legacy_candidate
from moonraker_http_error_patch import candidate as http_error_candidate


def reviewed_candidate(target, source):
    # Select from code-owned recipes, never executable data in a receipt.
    # Existing directory receipts retain their original schema and validation.
    if Path(target).name == "application.py":
        return http_error_candidate(source)
    return candidate(source)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Expected a regular file with one hard link: ' + str(path))
        return stream.read(), info


def sync_directory(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, data, mode=0o600, owner=None, expected=None):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.wmp-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            if owner is not None:
                os.fchown(stream.fileno(), *owner)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None and read_regular(path)[0] != expected:
            raise ValueError("Moonraker source changed during publication")
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def locked(target, directory):
    target, directory = Path(target).absolute(), Path(directory).absolute()
    if target.resolve() != target or directory.resolve() != directory:
        raise ValueError('Linked transaction path')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(directory / 'lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid transaction lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield target, directory
    finally:
        os.close(fd)


def load_record(target, directory):
    raw, _ = read_regular(directory / 'receipt.json')
    record = json.loads(raw)
    keys = {'version', 'target', 'old', 'new', 'mode', 'uid', 'gid'}
    if (not isinstance(record, dict) or record.get('version') not in (1, 2)
            or set(record) != (keys | {'previous'} if record.get('version') == 2 else keys)
            or record.get('target') != str(target)):
        raise ValueError('Invalid or foreign Moonraker receipt: schema, version or target differs')
    original, _ = read_regular(directory / 'original.py')
    installed, _ = read_regular(installed_path(directory, record))
    if digest(original) != record['old'] or digest(installed) != record['new']:
        raise ValueError('Moonraker backup integrity mismatch: '
                         + ', '.join(name for name, actual, expected in (
                             ('original.py', digest(original), record['old']),
                             ('installed.py', digest(installed), record['new'])) if actual != expected))
    # A receipt is data, not permission to install arbitrary Python source.
    wanted = reviewed_candidate(target, original.decode()).encode()
    legacy = legacy_candidate(original.decode()).encode() if Path(target).name != 'application.py' else None
    if record['version'] == 2:
        previous, _ = read_regular(directory / 'installed.py')
        if installed != wanted or previous != legacy or digest(previous) != record['previous']:
            raise ValueError('Backup does not contain the reviewed patch upgrade')
    elif installed != wanted and installed != legacy:
        raise ValueError('Backup does not contain the reviewed patch')
    for key in ('mode', 'uid', 'gid'):
        if type(record[key]) is not int or record[key] < 0:
            raise ValueError('Invalid saved file metadata')
    if record['mode'] & ~0o777:
        raise ValueError('Unexpected executable privilege bits')
    return record, original, installed


def installed_path(directory, record):
    return directory / ('installed-v2.py' if record['version'] == 2 else 'installed.py')


def source_versions(target, directory):
    record, original, installed = load_record(target, directory)
    sources = {'original': original, 'installed': installed}
    if record['version'] == 2:
        sources['previous'] = read_regular(directory / 'installed.py')[0]
    elif installed != reviewed_candidate(target, original.decode()).encode():
        sources['previous'] = installed
    return sources


def source_state(target, directory, current=None):
    sources = source_versions(target, directory)
    if current is None:
        current = read_regular(target)[0]
    for name in ('original', 'previous', 'installed'):
        if name in sources and current == sources[name]:
            return name
    return 'changed'


def prepare(target, directory, original_backup=None):
    with locked(target, directory) as (target, directory):
        receipt = directory / 'receipt.json'
        if receipt.exists() or receipt.is_symlink():
            record, original, installed = load_record(target, directory)
            current, _ = read_regular(target)
            sources = source_versions(target, directory)
            if current in sources.values():
                wanted = reviewed_candidate(target, original.decode()).encode()
                if installed == wanted:
                    return record
                import moonraker_directory_service as lifecycle
                operation = lifecycle.read_operation(directory)
                if operation and operation['phase'] not in ('complete', 'recovered'):
                    raise ValueError('Interrupted Moonraker service operation requires recovery before recipe upgrade')
                upgraded = dict(record, version=2, previous=digest(installed), new=digest(wanted))
                # Original and previous patch remain untouched. The one receipt
                # replacement commits the new recipe only after its bytes sync.
                atomic_write(directory / 'installed-v2.py', wanted)
                if read_regular(target)[0] != current:
                    raise ValueError('Moonraker source changed during recipe upgrade')
                atomic_write(receipt, (json.dumps(upgraded, sort_keys=True) + '\n').encode())
                return upgraded
            # A vendor update or an unrelated operator edit may leave a new
            # independently supported original. Never restore old source over
            # it. Qualify the actual live methods before retiring old history.
            reviewed_candidate(target, current.decode('utf-8'))
            import moonraker_directory_service as lifecycle
            operation = lifecycle.read_operation(directory)
            if operation and operation['phase'] not in ('complete', 'recovered'):
                raise ValueError('Interrupted Moonraker service operation requires recovery before rebaseline')
            if original_backup is not None:
                raise ValueError('New Moonraker baseline must use the current source, not an older backup')
            archive = Path(tempfile.mkdtemp(prefix='retired-', dir=str(directory)))
            atomic_write(archive / 'original.py', original)
            atomic_write(archive / 'installed.py', read_regular(directory / 'installed.py')[0])
            if record['version'] == 2:
                atomic_write(archive / 'installed-v2.py', installed)
            atomic_write(archive / 'receipt.json', (json.dumps(record, sort_keys=True) + '\n').encode())
            if operation is not None:
                raw, _ = read_regular(directory / 'service.json')
                atomic_write(archive / 'service.json', raw)
            sync_directory(directory)
            # Keep the existing lock inode. Old evidence is durable before the
            # active receipt is retired; interrupted preparation changes no
            # live source and can safely prepare from that source again.
            if read_regular(target)[0] != current:
                raise ValueError('Moonraker source changed during baseline review')
            receipt.unlink()
            if operation is not None:
                (directory / 'service.json').unlink()
            sync_directory(directory)
        current, info = read_regular(target)
        original = current
        if original_backup is not None:
            original, _ = read_regular(Path(original_backup))
        patched = reviewed_candidate(target, original.decode()).encode()
        if current not in (original, patched):
            raise ValueError('Original backup does not describe the installed source')
        record = dict(version=1, target=str(target), old=digest(original), new=digest(patched),
                      mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)
        if record['mode'] & ~0o777:
            raise ValueError('Unexpected executable privilege bits')
        # Receipt publication is the commit point for a complete undo plan.
        atomic_write(directory / 'original.py', original)
        atomic_write(directory / 'installed.py', patched)
        atomic_write(receipt, (json.dumps(record, sort_keys=True) + '\n').encode())
        return record


def publish(target, directory, restore=False, previous=False):
    """Publish while the caller holds the transaction lock."""
    record, original, installed = load_record(target, directory)
    current, _ = read_regular(target)
    sources = source_versions(target, directory)
    desired = 'previous' if previous else 'original' if restore else 'installed'
    if desired not in sources:
        raise ValueError('No verified previous Moonraker patch is available')
    wanted = sources[desired]
    if current == wanted:
        return False
    if current not in sources.values():
        raise ValueError('Refusing to overwrite changed Moonraker source')
    atomic_write(target, wanted, record['mode'], (record['uid'], record['gid']), expected=current)
    if read_regular(target)[0] != wanted:
        raise ValueError('Moonraker publication readback mismatch')
    return True


def transition(target, directory, restore=False):
    with locked(target, directory) as (target, directory):
        return publish(target, directory, restore)


def status(target, directory):
    with locked(target, directory) as (target, directory):
        _, original, installed = load_record(target, directory)
        current, _ = read_regular(target)
        return source_state(target, directory, current)
