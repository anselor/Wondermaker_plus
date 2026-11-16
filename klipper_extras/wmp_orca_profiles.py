# Copyright (C) 2026 Wondermaker+ contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract a compact WM+ catalogue from Orca JSON presets and export bundles.

No slicer G-code or tuning settings are retained or executed. Archive entries are
read in memory, never extracted to the filesystem. This module has no Klipper
or Moonraker dependencies, so parsing can run outside the G-code thread.
"""
import hashlib
import io
import json
import math
import os
import re
import zipfile

try:
    from .wmp_persistence import atomic_write
except ImportError:
    from wmp_persistence import atomic_write

MAX_FILE = 2 * 1024 * 1024
MAX_BUNDLE = 20 * 1024 * 1024
MAX_ENTRIES = 256
FIELDS = {
    'filament_vendor': 'brand', 'filament_type': 'material',
    'nozzle_temperature': 'nozzle_temp',
    'nozzle_temperature_range_low': 'nozzle_temp_min',
    'nozzle_temperature_range_high': 'nozzle_temp_max',
}


def _json(raw):
    if len(raw) > MAX_FILE:
        raise ValueError('Preset exceeds 2 MiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result
    result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs)
    if not isinstance(result, dict):
        raise ValueError('Preset must be a JSON object')
    return result


def read_documents(raw):
    """Return named JSON documents from one preset or a ZIP export bundle."""
    if len(raw) > MAX_BUNDLE:
        raise ValueError('Import exceeds 20 MiB')
    stream = io.BytesIO(raw)
    if not zipfile.is_zipfile(stream):
        return [_json(raw)]
    documents = []
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES or sum(e.file_size for e in entries) > MAX_BUNDLE:
            raise ValueError('Export bundle exceeds import limits')
        names = set()
        for entry in entries:
            if entry.filename in names:
                raise ValueError('Duplicate archive entry')
            names.add(entry.filename)
            if not entry.filename.lower().endswith('.json') or entry.is_dir():
                continue
            if entry.file_size > MAX_FILE or entry.flag_bits & 1:
                raise ValueError('Oversized or encrypted preset')
            documents.append(_json(archive.read(entry)))
    return documents


def _scalar(value, field):
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError(field + ' must describe one filament')
        value = value[0]
    return value


def _text(value, field, limit=64):
    value = _scalar(value, field)
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid ' + field)
    return value.strip()


def extract_profiles(documents):
    """Resolve supplied parents, then return profiles, warnings and errors.

    A missing parent is reported even when explicit fields suffice. Templates
    can provide inheritance but are not offered as selectable profiles. Bed
    temperatures are plate-specific in Orca and are intentionally not collapsed
    into a fabricated single bed temperature.
    """
    if len(documents) > MAX_ENTRIES:
        raise ValueError('Too many presets')
    index, errors = {}, []
    for document in documents:
        kind = document.get('type')
        # Orca ConfigBase::save_to_json exports user presets without a type
        # header. Identify those using filament-specific configuration keys.
        if kind != 'filament' and not (kind is None and any(key in document for key in
                ('filament_settings_id', 'filament_id', 'filament_type', 'filament_vendor'))):
            continue
        try:
            name = _text(document.get('name'), 'preset name', 160)
            if name in index and index[name] != document:
                raise ValueError('Conflicting presets named ' + name)
            index[name] = document
        except ValueError as error:
            errors.append(str(error))
    # Conflicting names must not resolve to whichever archive entry came first.
    if any(e.startswith('Conflicting presets') for e in errors):
        return {'profiles': [], 'warnings': [], 'errors': errors}
    cache = {}
    def resolve(name, trail=()):
        if name in trail or len(trail) >= 32:
            raise ValueError('Cyclic or excessive inheritance: ' + name)
        if name in cache:
            return cache[name]
        document = index[name]
        parent = document.get('inherits', '')
        if not isinstance(parent, str):
            raise ValueError('Invalid parent preset: ' + name)
        values, warnings = {}, []
        if parent:
            if parent in index:
                inherited, warnings = resolve(parent, trail + (name,))
                values.update(inherited)
                warnings = list(warnings)
            else:
                warnings.append('Missing parent "' + parent + '"; only explicit values are available')
        values.update(document)
        cache[name] = values, warnings
        return values, warnings
    profiles, warnings = [], []
    for name, document in index.items():
        if document.get('instantiation') in ('false', False):
            continue
        try:
            values, notices = resolve(name)
            identity = {}
            for key, field in FIELDS.items():
                if key not in values:
                    if field in ('brand', 'material', 'nozzle_temp'):
                        raise ValueError('Missing ' + field + ' (include its parent preset)')
                    continue
                value = _scalar(values[key], key)
                if field in ('brand', 'material'):
                    identity[field] = _text(value, field)
                else:
                    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                        raise ValueError('Invalid ' + field)
                    temperature = float(value)
                    if not math.isfinite(temperature) or not 0 < temperature <= 350:
                        raise ValueError('Invalid ' + field)
                    identity[field] = temperature
            low, high = identity.get('nozzle_temp_min', 0), identity.get('nozzle_temp_max', 350)
            if not low <= identity['nozzle_temp'] <= high:
                raise ValueError('Nozzle temperature is outside its range')
            for field in ('default_filament_colour', 'filament_colour'):
                if field not in values:
                    continue
                colour = _scalar(values[field], field)
                if colour == '':
                    continue
                if not isinstance(colour, str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', colour):
                    raise ValueError('Invalid filament colour')
                identity['color'] = colour.upper()
                break
            record = {'name': name, 'identity': identity}
            digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
            record['id'] = digest
            profiles.append(record)
            warnings.extend(name + ': ' + notice for notice in notices)
        except (ValueError, TypeError, OverflowError) as error:
            errors.append(name + ': ' + str(error))
    if not index:
        errors.append('No Orca filament presets found')
    return {'profiles': profiles, 'warnings': warnings, 'errors': errors}


def import_bytes(raw):
    return extract_profiles(read_documents(raw))


def catalogue_revision(profiles):
    return hashlib.sha256(json.dumps(profiles, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def read_catalogue(path):
    """Read only WM+ metadata; corrupt stores are never silently replaced."""
    try:
        with open(path, 'rb') as stream:
            raw = stream.read(MAX_FILE + 1)
    except FileNotFoundError:
        return {}, catalogue_revision({})
    data = _json(raw)
    if data.get('version') != 1 or set(data) != {'version', 'profiles'}:
        raise ValueError('Unsupported filament catalogue')
    profiles = data['profiles']
    if not isinstance(profiles, dict) or len(profiles) > MAX_ENTRIES:
        raise ValueError('Invalid filament catalogue')
    for key, profile in profiles.items():
        _validate_record(profile)
        if key != profile['id']:
            raise ValueError('Invalid catalogue profile key')
    return profiles, catalogue_revision(profiles)


def _validate_record(profile):
    if not isinstance(profile, dict) or set(profile) != {'id', 'name', 'identity'}:
        raise ValueError('Invalid catalogue profile')
    _text(profile['name'], 'preset name', 160)
    identity = profile['identity']
    if not isinstance(identity, dict) or not {'brand', 'material', 'nozzle_temp'} <= set(identity) or set(identity) - {'brand', 'material', 'color', 'nozzle_temp', 'nozzle_temp_min', 'nozzle_temp_max'}:
        raise ValueError('Invalid catalogue identity')
    _text(identity['brand'], 'brand'); _text(identity['material'], 'material')
    for field in ('nozzle_temp', 'nozzle_temp_min', 'nozzle_temp_max'):
        if field in identity and (type(identity[field]) not in (int, float) or not math.isfinite(identity[field]) or not 0 < identity[field] <= 350):
            raise ValueError('Invalid catalogue temperature')
    if not identity.get('nozzle_temp_min', 0) <= identity['nozzle_temp'] <= identity.get('nozzle_temp_max', 350):
        raise ValueError('Invalid catalogue temperature range')
    if 'color' in identity and (not isinstance(identity['color'], str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}', identity['color'])):
        raise ValueError('Invalid catalogue color')
    record = {'name': profile['name'], 'identity': identity}
    if profile['id'] != hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=True).encode()).hexdigest():
        raise ValueError('Catalogue profile content changed')


def save_catalogue(path, selected, expected_revision):
    """Merge confirmed records atomically. Caller serializes writers."""
    profiles, revision = read_catalogue(path)
    if revision != expected_revision:
        raise ValueError('Filament catalogue changed; review again')
    if not isinstance(selected, list) or not selected:
        raise ValueError('Select at least one profile')
    for profile in selected:
        _validate_record(profile)
        profiles[profile['id']] = profile
    if len(profiles) > MAX_ENTRIES:
        raise ValueError('Filament catalogue is full')
    raw = json.dumps({'version': 1, 'profiles': profiles}, sort_keys=True, ensure_ascii=True).encode()
    if len(raw) > MAX_FILE:
        raise ValueError('Filament catalogue is too large')
    atomic_write(os.path.abspath(path), raw, '.wmp-catalogue-')
    return profiles, catalogue_revision(profiles)


class UsbProfileImport:
    """Bounded USB discovery and immutable review tokens; caller serializes use."""
    EXTENSIONS = ('.json', '.zip', '.orca_filament', '.orca_printer')

    def __init__(self, usb_root, catalogue_path):
        import os
        self.usb_root = os.path.abspath(usb_root)
        self.catalogue_path = catalogue_path
        self.files = {}
        self.reviewed = None

    def scan(self):
        import os
        import stat
        self.files = {}
        self.reviewed = None
        if not os.path.isdir(self.usb_root):
            return {'state': 'files', 'files': [], 'message': 'Insert a USB drive'}
        root = os.path.realpath(self.usb_root)
        count = 0
        for directory, children, names in os.walk(root, followlinks=False):
            children[:] = sorted(d for d in children if not os.path.islink(os.path.join(directory, d)))
            if os.path.relpath(directory, root).count(os.sep) >= 4:
                children[:] = []
            for name in sorted(names):
                count += 1
                if count > 4096:
                    raise ValueError('Too many USB files; use a smaller profile folder')
                if not name.lower().endswith(self.EXTENSIONS):
                    continue
                path = os.path.join(directory, name)
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BUNDLE:
                    continue
                relative = os.path.relpath(path, root)
                if len(relative) > 512 or any(ord(c) < 32 for c in relative):
                    continue
                key = hashlib.sha256(relative.encode()).hexdigest()
                self.files[key] = {'id': key, 'name': relative, 'size': info.st_size}
                if len(self.files) > MAX_ENTRIES:
                    raise ValueError('Too many profile files on USB')
        self.scanned_root = root
        return {'state': 'files', 'files': sorted(self.files.values(), key=lambda f: f['name']),
                'message': '' if self.files else 'No Orca profile files found'}

    def _read(self, entry):
        import os
        import stat
        root = os.path.realpath(self.usb_root)
        if root != self.scanned_root:
            raise ValueError('USB drive changed; refresh the file list')
        # Walk with directory descriptors: reject substituted symlinks at every
        # level, including a symlink swapped in after discovery.
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            parts = entry['name'].split(os.sep)
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory); directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BUNDLE:
                    raise ValueError('USB profile is not a supported file')
                raw = stream.read(MAX_BUNDLE + 1)
                if len(raw) > MAX_BUNDLE:
                    raise ValueError('USB profile exceeds import limit')
                return raw
        finally:
            os.close(directory)

    def review(self, file_id):
        import secrets
        self.reviewed = None
        if file_id not in self.files:
            raise ValueError('USB file selection changed; refresh')
        entry = self.files[file_id]
        result = import_bytes(self._read(entry))
        _, revision = read_catalogue(self.catalogue_path)
        token = secrets.token_hex(24)
        self.reviewed = {'token': token, 'revision': revision, 'profiles': result['profiles']}
        return dict(result, state='review', name=entry['name'], token=token,
                    catalogue_revision=revision)

    def save(self, token):
        review = self.reviewed
        if review is None or not isinstance(token, str) or token != review['token']:
            raise ValueError('Import review expired; select the file again')
        # Consume before persistence: uncertain writes are inspected by readback,
        # never replayed implicitly by reconnect or another button press.
        self.reviewed = None
        profiles, revision = save_catalogue(self.catalogue_path, review['profiles'], review['revision'])
        return {'state': 'saved', 'count': len(review['profiles']),
                'catalogue_revision': revision}
