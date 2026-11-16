"""Concrete printer-side ports and file plan for the touchscreen transaction."""
import json
import copy
import hashlib
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import touchscreen_transaction as transaction


class Ports:
    def __init__(self, moonraker='http://127.0.0.1:7125'):
        self.moonraker = moonraker

    def request(self, method, path, params):
        data = None
        if method == 'POST':
            data = json.dumps(params).encode()
        elif params:
            path += '?' + urlencode(params)
        req = Request(self.moonraker+path, data=data, method=method,
                      headers={'Content-Type': 'application/json'})
        with urlopen(req, timeout=10) as response:
            value = json.loads(response.read())
        if not isinstance(value, dict) or 'result' not in value or 'error' in value:
            raise ValueError('Unconfirmed Moonraker settings response')
        return value['result']

    def command(self, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Service command failed: '+ ' '.join(argv)+': '+result.stderr.strip())
        return result.stdout

    def state(self, unit):
        value = self.command(['systemctl', 'show', unit, '--property=LoadState',
                              '--property=ActiveState', '--property=UnitFileState'])
        fields = dict(line.split('=', 1) for line in value.splitlines() if '=' in line)
        if fields.get('LoadState') == 'not-found' and fields.get('ActiveState') == 'inactive':
            return {'active': False, 'enabled': False}
        if (fields.get('LoadState') != 'loaded' or fields.get('ActiveState') not in ('active', 'inactive')
                or fields.get('UnitFileState') not in ('enabled', 'disabled')):
            raise ValueError('Unsupported or transitional service state: '+unit+'; '
                             + ', '.join(key+'='+repr(fields.get(key, '<missing>'))[:80]
                                         for key, allowed in (('LoadState', ('loaded',)),
                                            ('ActiveState', ('active', 'inactive')),
                                            ('UnitFileState', ('enabled', 'disabled')))
                                         if fields.get(key) not in allowed))
        return {'active': fields['ActiveState'] == 'active', 'enabled': fields['UnitFileState'] == 'enabled'}

    def services(self, action, unit):
        if unit not in (transaction.SCREEN, transaction.FIXER, 'daemon', 'nginx', 'screen-http'):
            raise ValueError('Unexpected touchscreen service')
        if action == 'state':
            return self.state(unit)
        if (action, unit) == ('reload', 'daemon'):
            return self.command(['systemctl', 'daemon-reload'])
        if (action, unit) == ('check', 'nginx'):
            return self.command(['nginx', '-t'])
        if (action, unit) == ('check', 'screen-http'):
            deadline = time.monotonic()+20
            while True:
                try:
                    with urlopen('http://127.0.0.1:8975/snapshot.jpg', timeout=3) as response:
                        if response.status != 200 or response.read(2) != b'\xff\xd8':
                            raise ValueError('Screen snapshot is not a JPEG')
                    with urlopen('http://127.0.0.1/wmp-screen/', timeout=3) as response:
                        if response.status != 200:
                            raise ValueError('Screen proxy unavailable')
                    return
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        if action in ('stop', 'disable') and unit in (transaction.SCREEN, transaction.FIXER):
            # Missing services are normal on a first install or after undo.
            output = self.command(['systemctl', 'show', unit, '--property=LoadState'])
            if output.strip() == 'LoadState=not-found':
                return
        if action not in ('start', 'stop', 'enable', 'disable', 'reload'):
            raise ValueError('Unexpected touchscreen service action')
        return self.command(['systemctl', action, unit])


def file_plan(source, root=Path('/')):
    source, root = Path(source), Path(root)
    prefix = root/'opt/wondermaker_plus'
    device = source/'device'
    files = []
    for name, mode in [('wmp_screen.py', 0o644), ('nginx-screen.conf', 0o644),
                       ('timelapse-camera-fix.sh', 0o755)]:
        files.append((prefix/name, (device/name).read_bytes(), mode))
    for path in sorted((device/'www').rglob('*')):
        if path.is_symlink():
            raise ValueError('Linked touchscreen web asset')
        if path.is_file():
            files.append((prefix/'www'/path.relative_to(device/'www'), path.read_bytes(), 0o644))
    if not (device/'www/index.html').is_file():
        raise ValueError('Missing touchscreen web page')
    for name in (transaction.SCREEN, transaction.FIXER):
        files.append((root/'etc/systemd/system'/name, (device/name).read_bytes(), 0o644))
    version_path = root/'home/t13dp/iso_version.txt'
    version = version_path.read_text().splitlines()[0] if version_path.is_file() and version_path.stat().st_size else 'unknown'
    stamp = time.strftime('installed %Y-%m-%dT%H:%M:%SZ', time.gmtime())
    files.append((prefix/'installed-against.txt', (version+'\n'+stamp+'\n').encode(), 0o644))
    site = root/'etc/nginx/sites-available/fluidd'
    old = transaction.snapshot(site)
    if old is None:
        raise ValueError('Missing Fluidd nginx configuration')
    data = bytes.fromhex(old['data'])
    line = b'    include /opt/wondermaker_plus/nginx-screen.conf; # wondermaker_plus'
    marked = [row for row in data.splitlines() if b'# wondermaker_plus' in row]
    if marked and marked != [line]:
        raise ValueError('Unexpected existing touchscreen nginx include')
    if not marked:
        index = data.rstrip().rfind(b'}')
        if index < 0:
            raise ValueError('Fluidd nginx server closing brace missing')
        files.append((site, data[:index]+line+b'\n'+data[index:], old['mode']))
        backup = prefix/'backup/fluidd.orig'
        if not backup.exists():
            files.append((backup, data, old['mode']))
    return files


def reconcile_pending(path, ports):
    """Undo owned partial writes while retaining later operator edits.

    Original evidence is never rewritten. A separate durable plan makes an
    interrupted reconciliation resume the same decisions instead of adopting
    its own half-completed undo as a new baseline.
    """
    original = path.read_bytes()
    fingerprint = hashlib.sha256(original).hexdigest()
    recovery_path = path.with_suffix('.reconcile')
    recovery = transaction.Transaction(recovery_path, ports.services, ports.request)
    if recovery_path.exists() or recovery_path.is_symlink():
        recovery.load()
        if recovery.receipt.get('reconciliation_original_sha256') != fingerprint:
            raise ValueError('Touchscreen journal changed after reconciliation planning: ' + str(path))
    else:
        old = transaction.Transaction(path, ports.services, ports.request)
        old.load()
        if old.receipt.get('state') not in ('prepared', 'installing', 'restoring'):
            raise ValueError('Unsupported unresolved touchscreen state: ' + str(path))
        receipt = copy.deepcopy(old.receipt)
        preserved = []
        for row in receipt['files']:
            current = old.current(row)
            if current not in (row['before'], row['after']):
                row['before'] = row['after'] = current
                preserved.append(row['path'])
        camera = receipt['camera']
        current = transaction.settings._camera(ports.request)
        if current != camera['before'] and not transaction.settings._owned(current, camera):
            camera['before'] = camera['after'] = current
            preserved.append('Touchscreen webcam')
        if camera.get('selection_managed', True):
            selected = transaction.settings._selected(ports.request)
            if selected not in (camera['selected_before'], camera['selected_after']):
                camera['selected_before'] = camera['selected_after'] = selected
                preserved.append('timelapse selection')
        for unit, before in receipt['services'].items():
            current = ports.services('state', unit)
            if current not in (before, old.installed_service_state(unit)):
                receipt['services'][unit] = current
                preserved.append(unit)
        receipt['state'] = 'restoring'
        receipt['reconciliation_original_sha256'] = fingerprint
        receipt['preserved_operator_edits'] = preserved
        recovery.receipt = receipt
        recovery.save()
    recovery.restore()
    if path.read_bytes() != original:
        raise ValueError('Touchscreen journal changed during reconciliation: ' + str(path))
    # Archive only after the verified undo; keep both original and plan.
    retired = path.with_suffix('.retired')
    if retired.exists() or retired.is_symlink():
        raise ValueError('Touchscreen reconciliation archive already exists: ' + str(retired))
    path.rename(retired)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print('Reconciled interrupted touchscreen install; preserved operator edits: ' +
          ', '.join(recovery.receipt.get('preserved_operator_edits', [])))


def pending(directory, ports=None):
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Linked touchscreen transaction directory')
    for path in sorted(directory.glob('*.json')):
        if path.is_symlink():
            raise ValueError('Linked touchscreen journal')
        value = json.loads(path.read_text())
        if value.get('version') != 1 or value.get('state') not in ('applied', 'restored'):
            if ports is None:
                raise ValueError('Unresolved touchscreen transaction: '+str(path))
            reconcile_pending(path, ports)


def execute(action, source, journal):
    """Serialize printer-side mutations and keep recoverable journals."""
    import fcntl
    journal = Path(journal)
    directory = Path('/opt/wondermaker_plus-transactions')
    if journal.parent != directory or journal.suffix != '.json':
        raise ValueError('Invalid touchscreen transaction location')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError('Linked touchscreen transaction directory')
    lock_path = directory/'lock'
    if lock_path.is_symlink():
        raise ValueError('Linked touchscreen transaction lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ports = Ports()
        tx = transaction.Transaction(journal, ports.services, ports.request)
        if action == 'install':
            pending(directory, ports)
            if not ports.state('nginx')['active']:
                raise ValueError('Nginx must be running before touchscreen installation')
            tx.prepare(file_plan(source))
            tx.install()
        elif action == 'restore':
            tx.restore()
        else:
            raise ValueError('Unknown touchscreen transaction action')
        return {'state': tx.receipt['state'], 'journal': str(journal)}
