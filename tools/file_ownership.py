"""Immutable originals and shared ownership for WM+ Klipper helper files.

Pure planning: transport and publication use the component's existing journaled
transaction. The inventory is data, never a source of executable commands.
"""
import copy
import hashlib
import json

OWNERS = {'config', 'material'}
FILENAME = '.wmp-helper-ownership.json'


def digest(data):
    return None if data is None else hashlib.sha256(data).hexdigest()


def load(raw, allowed):
    value = json.loads(raw) if raw is not None else {'version': 1, 'files': {}}
    if not isinstance(value, dict) or set(value) != {'version', 'files'} or value['version'] != 1 or not isinstance(value['files'], dict):
        raise ValueError('Invalid helper ownership inventory')
    for name, row in value['files'].items():
        if name not in allowed or not isinstance(row, dict) or set(row) != {'original', 'original_hash', 'metadata', 'installed', 'previous', 'owners', 'provenance'}:
            raise ValueError('Unexpected owned helper: ' + str(name))
        original = None if row['original'] is None else bytes.fromhex(row['original'])
        if digest(original) != row['original_hash'] or row['provenance'] not in ('absent', 'legacy-wmp', 'preexisting'):
            raise ValueError('Invalid helper original: ' + name)
        if not isinstance(row['owners'], list) or not set(row['owners']) <= OWNERS or len(row['owners']) != len(set(row['owners'])):
            raise ValueError('Invalid helper owners: ' + name)
        if not isinstance(row['installed'], str) or len(row['installed']) != 64 or any(c not in '0123456789abcdef' for c in row['installed']):
            raise ValueError('Invalid helper installed digest: ' + name)
        if row['previous'] is not None and (not isinstance(row['previous'],str) or len(row['previous'])!=64 or any(c not in '0123456789abcdef' for c in row['previous'])):
            raise ValueError('Invalid previous helper digest')
        metadata=row['metadata']
        if metadata is not None and (not isinstance(metadata,dict) or set(metadata)!={'mode','uid','gid'}
                or any(type(v) is not int or v<0 for v in metadata.values()) or metadata['mode'] & ~0o777):
            raise ValueError('Invalid helper metadata')
    return value


def install(value, name, before, after, owner, known, metadata=None):
    if owner not in OWNERS:
        raise ValueError('Unknown helper owner')
    row = value['files'].get(name)
    if row is None:
        legacy = before is not None and digest(before) in known.get(name, [])
        original = None if legacy else before
        row = {'original': None if original is None else original.hex(),
               'original_hash': digest(original), 'metadata':metadata if original is not None else None, 'installed': digest(after),
               'previous': digest(before), 'owners': [], 'provenance': 'legacy-wmp' if legacy else 'absent' if before is None else 'preexisting'}
        value['files'][name] = row
    elif digest(before) not in (row['installed'], row['previous'], row['original_hash'], digest(after)):
        raise ValueError('Owned helper changed outside installer: ' + name)
    if row['installed'] != digest(after) or digest(before) != digest(after):
        row['previous'] = digest(before)
    row['installed'] = digest(after)
    row['owners'] = sorted(set(row['owners']) | {owner})


def removal(value, owner, current):
    """Preflight the full release before changing anything; return restore bytes."""
    result, changes = copy.deepcopy(value), {}
    for name, row in result['files'].items():
        if owner not in row['owners']:
            continue
        row['owners'].remove(owner)
        if row['owners']:
            continue
        before = current(name)
        if digest(before) not in (row['installed'], row['previous'], row['original_hash']):
            raise ValueError('Owned helper changed before removal: ' + name)
        original = None if row['original'] is None else bytes.fromhex(row['original'])
        if before != original:
            changes[name] = original
    return result, changes


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
