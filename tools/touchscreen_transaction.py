"""Printer-side touchscreen install transaction with injectable service/API ports.

A journal survives process loss. Recovery is explicit; it never sends G-code or
restarts Klipper. Paths are supplied by the trusted installer, not API clients.
"""
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import touchscreen_settings as settings

SCREEN = 'wmp-screen.service'
FIXER = 'wmp-timelapse-camera.service'


def atomic(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.wmp-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def snapshot(path):
    path = Path(path)
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError('Refuse non-regular touchscreen destination: ' + str(path))
    if not path.exists():
        return None
    metadata = path.stat()
    return dict(data=path.read_bytes().hex(), mode=stat.S_IMODE(metadata.st_mode),
                uid=metadata.st_uid, gid=metadata.st_gid)


def replace(path, value):
    path = Path(path)
    if value is None:
        path.unlink()
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        atomic(path, bytes.fromhex(value['data']), value['mode'])
        os.chown(path, value['uid'], value['gid'])


class Transaction:
    """services supports state/stop/start/restart/enable/disable/reload/check.

    check('nginx') validates configuration; check('screen-http') verifies bridge
    endpoints. state(unit) returns {active: bool, enabled: bool}. The adapter
    must reject unsupported/transitional states rather than guessing defaults.
    """
    def __init__(self, journal, services, request):
        self.path = Path(journal)
        self.services = services
        self.request = request
        self.receipt = None

    def save(self):
        atomic(self.path, json.dumps(self.receipt, sort_keys=True).encode())

    def load(self):
        if self.path.is_symlink():
            raise ValueError('Linked touchscreen journal')
        self.receipt = json.loads(self.path.read_text())
        if self.receipt.get('version') != 1:
            raise ValueError('Unsupported touchscreen journal')

    def prepare(self, files):
        if self.path.exists() or self.path.is_symlink():
            raise ValueError('Touchscreen journal already exists')
        rows = []
        seen = set()
        for path, data, mode in files:
            path = Path(path).absolute()
            if str(path) in seen:
                raise ValueError('Duplicate touchscreen destination')
            seen.add(str(path))
            before = snapshot(path)
            rows.append(dict(path=str(path), resolved=str(path.resolve()), before=before,
                             after=dict(data=data.hex(), mode=mode,
                                        uid=before['uid'] if before else os.geteuid(),
                                        gid=before['gid'] if before else os.getegid())))
        service_states = {unit: self.services('state', unit) for unit in (SCREEN, FIXER)}
        for state in service_states.values():
            if (not isinstance(state, dict) or set(state) != {'active', 'enabled'}
                    or any(type(value) is not bool for value in state.values())):
                raise ValueError('Unconfirmed touchscreen service state')
        camera = settings.prepare(self.request)
        if camera.get('fixer_policy') == 'preserve':
            # Unknown optional settings are not permission to replace or run
            # the boot fixer, which can itself POST a camera selection.
            rows = [row for row in rows if Path(row['path']).name not in
                    ('wmp-timelapse-camera.service', 'timelapse-camera-fix.sh')]
        self.receipt = dict(version=1, state='prepared', files=rows,
                            services=copy.deepcopy(service_states), camera=camera)
        self.save()

    def managed_services(self):
        return (SCREEN,) if self.receipt['camera'].get('fixer_policy') == 'preserve' else (SCREEN, FIXER)

    def installed_service_state(self, unit):
        if unit == SCREEN:
            return {'active': True, 'enabled': True}
        policy = self.receipt['camera'].get('fixer_policy', 'enable')
        if policy == 'preserve':
            return self.receipt['services'][FIXER]
        return {'active': False, 'enabled': policy == 'enable'}

    def current(self, row):
        path = Path(row['path'])
        if str(path.resolve()) != row['resolved']:
            raise ValueError('Touchscreen destination link changed: ' + str(path))
        return snapshot(path)

    def validate_restore(self):
        for row in self.receipt['files']:
            if self.current(row) not in (row['before'], row['after']):
                raise ValueError('Concurrent touchscreen file edit: ' + row['path'])

    def checkpoint_camera(self, camera):
        self.receipt['camera'] = camera
        self.save()

    def install(self):
        if self.receipt is None or self.receipt['state'] != 'prepared':
            raise ValueError('Touchscreen install requires a prepared transaction')
        for row in self.receipt['files']:
            if self.current(row) != row['before']:
                raise ValueError('Touchscreen files changed since preparation')
        for unit, state in self.receipt['services'].items():
            if unit not in self.managed_services():
                continue
            if self.services('state', unit) != state:
                raise ValueError('Touchscreen service changed since preparation: ' + unit)
        self.receipt['state'] = 'installing'
        self.save()
        try:
            if FIXER in self.managed_services():
                self.services('stop', FIXER)
            self.services('stop', SCREEN)
            for row in self.receipt['files']:
                if self.current(row) != row['before']:
                    raise ValueError('Touchscreen file changed during publication')
                replace(row['path'], row['after'])
                if self.current(row) != row['after']:
                    raise ValueError('Touchscreen file publication readback mismatch')
            self.services('check', 'nginx')
            self.services('reload', 'daemon')
            self.services('enable', SCREEN)
            fixer_state = self.installed_service_state(FIXER)
            if FIXER in self.managed_services():
                self.services('enable' if fixer_state['enabled'] else 'disable', FIXER)
            if self.receipt['camera'].get('selection_note'):
                print(self.receipt['camera']['selection_note'])
            self.services('start', SCREEN)
            self.services('reload', 'nginx')
            settings.apply(self.request, self.receipt['camera'], self.checkpoint_camera)
            if FIXER in self.managed_services() and fixer_state['active']:
                self.services('start', FIXER)
            self.services('check', 'screen-http')
            for unit in self.managed_services():
                expected = self.installed_service_state(unit)
                if self.services('state', unit) != expected:
                    raise ValueError('Touchscreen service activation readback mismatch: ' + unit)
            self.receipt['state'] = 'applied'
            self.save()
        except Exception as error:
            try:
                self.restore()
            except Exception as repair:
                raise RuntimeError('Touchscreen recovery unconfirmed; retained journal ' + str(self.path) + ': ' + str(repair)) from error
            raise

    def restore(self):
        if self.receipt is None:
            self.load()
        if self.receipt['state'] not in ('prepared', 'installing', 'applied', 'restoring', 'restored'):
            raise ValueError('Unsupported touchscreen recovery state')
        self.validate_restore()
        if self.receipt['state'] == 'restored':
            if any(self.current(row) != row['before'] for row in self.receipt['files']):
                raise ValueError('Files changed after completed touchscreen restoration')
            for unit, state in self.receipt['services'].items():
                if unit not in self.managed_services():
                    continue
                if self.services('state', unit) != state:
                    raise ValueError('Service changed after completed touchscreen restoration')
            settings.restore(self.request, self.receipt['camera'], self.checkpoint_camera)
            return
        if self.receipt['state'] == 'applied':
            for unit in self.managed_services():
                expected = self.installed_service_state(unit)
                if self.services('state', unit) != expected:
                    raise ValueError('Touchscreen service changed after installation: ' + unit)
        self.receipt['state'] = 'restoring'
        self.save()
        # Prevent the boot-time fixer from changing the selection during undo.
        if FIXER in self.managed_services():
            self.services('stop', FIXER)
        self.services('stop', SCREEN)
        settings.restore(self.request, self.receipt['camera'], self.checkpoint_camera)
        for row in reversed(self.receipt['files']):
            current = self.current(row)
            if current == row['before']:
                continue
            if current != row['after']:
                raise ValueError('Touchscreen file changed during restoration')
            replace(row['path'], row['before'])
        if any(self.current(row) != row['before'] for row in self.receipt['files']):
            raise ValueError('Touchscreen restoration readback mismatch')
        self.services('check', 'nginx')
        self.services('reload', 'daemon')
        for unit, state in self.receipt['services'].items():
            if unit not in self.managed_services():
                continue
            self.services('enable' if state['enabled'] else 'disable', unit)
            if state['active']:
                self.services('start', unit)
        self.services('reload', 'nginx')
        for unit, state in self.receipt['services'].items():
            if unit not in self.managed_services():
                continue
            if self.services('state', unit) != state:
                raise ValueError('Touchscreen service restoration unconfirmed: ' + unit)
        self.receipt['state'] = 'restored'
        self.save()
