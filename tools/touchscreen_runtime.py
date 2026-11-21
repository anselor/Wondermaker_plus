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
import touchscreen_settings as settings


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


def factory_candidate(previous, receipt, generation, migration=False):
    """Carry original snapshots forward; replace only the installed generation."""
    candidate = copy.deepcopy(receipt)
    candidate['state'] = 'applied'
    candidate['generation'] = generation
    candidate.pop('factory_before', None)
    if previous is None:
        return candidate
    if previous.get('version') != 1 or previous.get('state') not in ('applied', 'restored'):
        raise ValueError('Unresolved touchscreen factory baseline')
    rows = {row['path']: copy.deepcopy(row) for row in previous['files']}
    incoming = {row['path'] for row in receipt['files']}
    for name, old in rows.items():
        expected = old['before'] if previous['state']=='restored' else old['after']
        current=transaction.snapshot(name) if name not in incoming else None
        if name not in incoming and current != expected and not (migration and current==old['before']):
            raise ValueError('Retired touchscreen resource changed: ' + name)
    for row in receipt['files']:
        if row['path'] in rows:
            old = rows[row['path']]
            expected = old['before'] if previous['state']=='restored' else old['after']
            if row['before'] != expected:
                raise ValueError('Touchscreen resource changed between updates: ' + row['path'])
            rows[row['path']]['after'] = copy.deepcopy(row['after'])
        else:
            rows[row['path']] = copy.deepcopy(row)
    candidate['files'] = list(rows.values())
    candidate['services'] = copy.deepcopy(previous['services'])
    camera = candidate['camera']
    previous_camera = previous['camera']
    expected_camera = previous_camera['before'] if previous['state']=='restored' else previous_camera['after']
    expected_selection = previous_camera['selected_before'] if previous['state']=='restored' else previous_camera['selected_after']
    if (receipt['camera']['before'] != expected_camera
            or (previous_camera.get('selection_managed', True)
                and receipt['camera']['selected_before'] != expected_selection)):
        raise ValueError('Touchscreen camera changed between updates')
    camera['before'] = copy.deepcopy(previous['camera']['before'])
    camera['selected_before'] = previous['camera']['selected_before']
    camera['selection_managed'] = (camera.get('selection_managed', True)
                                   or previous['camera'].get('selection_managed', True))
    if previous['camera'].get('fixer_policy') != 'preserve' and camera.get('fixer_policy')=='preserve':
        camera['fixer_policy'] = previous['camera']['fixer_policy']
    return candidate


def _factory_read(path):
    if path.is_symlink():
        raise ValueError('Linked touchscreen factory record')
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def commit_factory(directory, tx):
    before = tx.receipt.get('factory_before')
    candidate = factory_candidate(before, tx.receipt, tx.path.name)
    if _factory_read(directory/'factory-baseline') not in (before, candidate):
        raise ValueError('Touchscreen factory baseline changed during update')
    transaction.atomic(directory/'factory-baseline', json.dumps(candidate, sort_keys=True).encode())


def rewind_factory(directory, tx):
    baseline = _factory_read(directory/'factory-baseline')
    before = tx.receipt.get('factory_before')
    if baseline == before:
        return
    if baseline is not None and baseline.get('generation') != tx.path.name:
        raise ValueError('A later touchscreen update owns the factory record')
    if before is None:
        (directory/'factory-baseline').unlink(missing_ok=True)
    else:
        transaction.atomic(directory/'factory-baseline', json.dumps(before,sort_keys=True).encode())


def settle_factory(directory, ports):
    pending_path = directory/'factory-pending'
    pending = _factory_read(pending_path)
    if pending is None:
        return
    name = pending.get('journal')
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json'):
        raise ValueError('Invalid pending touchscreen factory generation')
    tx = transaction.Transaction(directory/name, ports.services, ports.request)
    tx.load()
    if tx.receipt['state']=='applied':
        commit_factory(directory, tx)
    else:
        tx.restore()
        rewind_factory(directory, tx)
    pending_path.unlink()


def adopt_legacy_factory(directory, ports, root=Path('/'), dry_run=False):
    """Migrate receipted updates, or the reviewed legacy reserved namespace.

    An nginx original is used only if reinserting our exact line explains the
    current file. API errors and unknown layouts are fatal, never successful
    best-effort removal. Legacy camera selection is retained as a user setting.
    """
    baseline_path=directory/'factory-baseline'
    if baseline_path.exists():
        return _factory_read(baseline_path)
    prefix=root/'opt/wondermaker_plus'
    site=root/'etc/nginx/sites-available/fluidd'
    line=b'    include /opt/wondermaker_plus/nginx-screen.conf; # wondermaker_plus'
    def original_site(snapshot):
        data=bytes.fromhex(snapshot['data'])
        if b'# wondermaker_plus' not in data:
            return snapshot
        backup=transaction.snapshot(prefix/'backup/fluidd.orig')
        if backup is None or b'# wondermaker_plus' in bytes.fromhex(backup['data']):
            raise ValueError('Missing verified original nginx configuration')
        original=bytes.fromhex(backup['data'])
        if data.replace(line+b'\n',b'')!=original:
            raise ValueError('Legacy nginx backup does not explain current configuration')
        return dict(snapshot,data=original.hex())
    histories=[]
    for path in sorted(directory.glob('*.json'),key=lambda p:(p.stat().st_mtime_ns,p.name)):
        receipt=_factory_read(path)
        if receipt.get('state')=='applied':
            histories.append((path,receipt))
    baseline=None
    for path,receipt in histories:
        if baseline is None:
            if receipt.get('factory_before') is not None:
                baseline=factory_candidate(receipt['factory_before'],receipt,path.name,migration=True)
                continue
            baseline=copy.deepcopy(receipt)
            baseline['state']='applied';baseline['generation']=path.name
            baseline.pop('factory_before',None)
            if 'factory_before' in receipt:
                continue
            # Legacy payload/service names are WM+-reserved, not factory files.
            for row in baseline['files']:
                target=Path(row['path'])
                if prefix==target or prefix in target.parents:
                    row['before']=None
                elif target==site:
                    row['before']=original_site(row['before'])
                elif target.parent==root/'etc/systemd/system' and target.name in (transaction.SCREEN,transaction.FIXER):
                    if row['before'] and b'/opt/wondermaker_plus/' not in bytes.fromhex(row['before']['data']):
                        raise ValueError('Unknown legacy touchscreen service original')
                    row['before']=None
            baseline['services']={unit:{'active':False,'enabled':False} for unit in (transaction.SCREEN,transaction.FIXER)}
        else:
            baseline=factory_candidate(baseline,receipt,path.name,migration=True)
    if baseline is None:
        files=[]
        if prefix.is_symlink():
            raise ValueError('Linked legacy touchscreen prefix')
        for path in sorted(prefix.rglob('*')):
            if path.is_symlink():
                raise ValueError('Linked legacy touchscreen payload')
            if path.is_file():
                files.append(dict(path=str(path),resolved=str(path.resolve()),before=None,after=transaction.snapshot(path)))
        for unit in (transaction.SCREEN,transaction.FIXER):
            path=root/'etc/systemd/system'/unit
            after=transaction.snapshot(path)
            if after:
                if b'/opt/wondermaker_plus/' not in bytes.fromhex(after['data']):
                    raise ValueError('Unknown legacy touchscreen service')
                files.append(dict(path=str(path),resolved=str(path.resolve()),before=None,after=after))
        snapshot=transaction.snapshot(site)
        if snapshot and b'# wondermaker_plus' in bytes.fromhex(snapshot['data']):
            files.append(dict(path=str(site),resolved=str(site.resolve()),before=original_site(snapshot),after=snapshot))
        baseline={'version':1,'state':'applied','generation':'legacy-adoption','files':files,
                  'services':{unit:{'active':False,'enabled':False} for unit in (transaction.SCREEN,transaction.FIXER)}}
        before=settings._camera(ports.request)
        baseline['camera']={'version':1,'state':'applied','before':before,'after':copy.deepcopy(before),
                            'selected_before':None,'selected_after':None,'selection_managed':False,
                            'fixer_policy':'enable' if ports.services('state',transaction.FIXER)['enabled'] else 'disable'}
    camera=baseline['camera']
    before=camera['before']
    if before and before.get('stream_url')=='/wmp-screen/':
        camera['before']=None
    # Legacy installation did not record the user's original timelapse choice.
    # Do not fabricate one or overwrite their present selection during migration.
    if histories and 'factory_before' not in histories[0][1]:
        camera['selection_managed']=False
    if not baseline['files'] and camera['after'] is None:
        baseline['state']='restored'
    validate_factory_removal(baseline,ports)
    if dry_run:
        return baseline
    transaction.atomic(baseline_path,json.dumps(baseline,sort_keys=True).encode())
    return baseline


def validate_factory_removal(receipt,ports):
    """Read-only conflict checks shared by preflight and explicit uninstall."""
    if receipt.get('state') not in ('applied','restoring','restored'):
        raise ValueError('Unresolved touchscreen factory restoration')
    view=transaction.Transaction(Path('/unused'),ports.services,ports.request)
    view.receipt=receipt
    view.validate_restore()
    if receipt['state']=='restored':
        if any(view.current(row)!=row['before'] for row in receipt['files']):
            raise ValueError('Touchscreen files changed after completed removal')
    camera=receipt['camera'];current=settings._camera(ports.request)
    if current!=camera['before'] and not settings._owned(current,camera):
        raise ValueError('Concurrent webcam edit; factory restoration refused')
    if current!=camera['before'] and current is not None and current.get('source')!='database':
        raise ValueError('Configuration-owned webcam requires explicit config migration')
    if camera.get('selection_managed',True):
        selected=settings._selected(ports.request)
        if selected not in (camera['selected_before'],camera['selected_after']):
            raise ValueError('Concurrent timelapse selection edit')


def execute(action, source, journal):
    """Serialize printer-side mutations and keep recoverable journals."""
    import fcntl
    journal = Path(journal)
    directory = Path('/opt/wondermaker_plus-transactions')
    if journal.parent != directory or journal.suffix != '.json':
        raise ValueError('Invalid touchscreen transaction location')
    if action=='check-uninstall':
        if directory.is_symlink():
            raise ValueError('Linked touchscreen transaction directory')
        if (directory/'factory-pending').exists():
            raise ValueError('Pending touchscreen inventory update requires recovery')
        pending(directory)
        ports=Ports()
        receipt=_factory_read(directory/'factory-baseline')
        if receipt is None:
            receipt=adopt_legacy_factory(directory,ports,dry_run=True)
        validate_factory_removal(receipt,ports)
        return {'state':'checked','journal':str(journal)}
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError('Linked touchscreen transaction directory')
    lock_path = directory/'lock'
    if lock_path.is_symlink():
        raise ValueError('Linked touchscreen transaction lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ports = Ports()
        settle_factory(directory, ports)
        tx = transaction.Transaction(journal, ports.services, ports.request)
        if action == 'install':
            pending(directory, ports)
            if not (directory/'factory-baseline').exists() and Path('/opt/wondermaker_plus').exists():
                adopt_legacy_factory(directory,ports)
            if not ports.state('nginx')['active']:
                raise ValueError('Nginx must be running before touchscreen installation')
            tx.prepare(file_plan(source))
            tx.receipt['factory_before'] = _factory_read(directory/'factory-baseline')
            # Validate update continuity before writing any live resource.
            factory_candidate(tx.receipt['factory_before'], tx.receipt, journal.name)
            tx.save()
            transaction.atomic(directory/'factory-pending', json.dumps({'journal':journal.name}).encode())
            try:
                tx.install()
                commit_factory(directory, tx)
            except Exception:
                tx.restore()
                rewind_factory(directory, tx)
                (directory/'factory-pending').unlink()
                raise
            (directory/'factory-pending').unlink()
        elif action == 'restore':
            tx.load()
            baseline = _factory_read(directory/'factory-baseline')
            if baseline is not None and baseline.get('generation') != journal.name:
                raise ValueError('A later touchscreen update owns the factory record')
            tx.restore()
            rewind_factory(directory, tx)
        elif action == 'uninstall':
            baseline_path = directory/'factory-baseline'
            if not baseline_path.exists():
                pending(directory,ports)
                adopt_legacy_factory(directory,ports)
            tx = transaction.Transaction(baseline_path, ports.services, ports.request)
            tx.load()
            validate_factory_removal(tx.receipt,ports)
            if tx.receipt['state']=='applied':
                # Explicit removal may stop an already-disabled owned service.
                # Strict post-install service matching belongs to update undo.
                tx.receipt['state']='restoring';tx.save()
            tx.restore()
        else:
            raise ValueError('Unknown touchscreen transaction action')
        return {'state': tx.receipt['state'], 'journal': str(journal)}
