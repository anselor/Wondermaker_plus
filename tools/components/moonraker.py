"""Reviewed Moonraker patches with separate backups and combined host recovery."""
import json
from pathlib import Path

import preload_bundle
import preflight as checks

NAME = 'moonraker'
DESCRIPTION = 'Keep status responsive and return reliable HTTP command errors'
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None
ROOT = Path(__file__).resolve().parents[1]
MODULES = ('moonraker_directory_patch', 'moonraker_http_error_patch', 'moonraker_directory_transaction',
           'moonraker_directory_service', 'moonraker_directory_install')


PATCHES = ('directory', 'http-error')


def _paths(ctx, patch='directory'):
    if not ctx.user:
        ctx.ssh()
    home = '/home/' + ctx.user
    if patch not in PATCHES:
        raise ValueError('Unknown Moonraker patch')
    relative = 'file_manager/file_manager.py' if patch == 'directory' else 'application.py'
    return home, home + '/moonraker/moonraker/components/' + relative, home + '/wmp/backups/moonraker-' + patch + '-managed'


def _remote(ctx, body, *, sudo=False, patch='directory'):
    # Execute reviewed local sources through stdin. Recovery never executes a
    # command or Python path supplied by an installer receipt.
    code = 'import sys,types\n'
    for name in MODULES:
        source = (ROOT / (name + '.py')).read_text(encoding='utf-8')
        code += ('m=types.ModuleType(%r);m.__file__=%r;sys.modules[%r]=m;'
                 'exec(compile(%r,m.__file__,"exec"),m.__dict__)\n') % (
                     name, str(ROOT / (name + '.py')), name, source)
    home, target, state = _paths(ctx, patch)
    code += ('from pathlib import Path\nimport json\n'
             'import moonraker_directory_transaction as tx\n'
             'import moonraker_directory_service as lifecycle\n'
             'from moonraker_directory_install import MoonrakerService\n'
             'target=Path(%r);state=Path(%r);home=Path(%r)\n') % (target, state, home)
    output = checks.remote(ctx, code + body, sudo=sudo, quiet=True)
    return json.loads(output)


def _enabled(ctx):
    if not getattr(ctx, 'moonraker_implicit', False):
        return True
    if preload_bundle.bundle_relative(ROOT.parent) != preload_bundle.CURRENT_BUNDLE:
        return False
    bundle = preload_bundle.load_bundle(ROOT.parent)
    code = ('import hashlib,json\nfrom pathlib import Path\n'
            'print(json.dumps(hashlib.sha256(Path(%r).read_bytes()).hexdigest()==%r))\n') % (
                _paths(ctx)[0] + '/TM_T1/bin/client', bundle['profile']['sha256'])
    return json.loads(checks.remote(ctx, code, quiet=True))


INSPECT = '''
unsupported=None
operation=lifecycle.read_operation(state)
if operation and operation['phase'] not in ('complete','recovered'):
    raise ValueError('Interrupted Moonraker operation: run tools/deploy.py recover all --journal LOCAL_JOURNAL before installation')
if (state/'receipt.json').exists():
    _,original,installed=tx.load_record(target,state)
    current,_=tx.read_regular(target)
    if current not in tx.source_versions(target,state).values():
        try:
            tx.reviewed_candidate(target,current.decode('utf-8'))
        except (ValueError,SyntaxError,UnicodeError) as error:
            unsupported=str(error)
        before='original'
    else:
        before=tx.source_state(target,state,current)
else:
    current,_=tx.read_regular(target)
    try:
        tx.reviewed_candidate(target,current.decode('utf-8'))
    except (ValueError,SyntaxError,UnicodeError) as error:
        unsupported=str(error)
    before='original'
if unsupported is not None:
    print(json.dumps({'unsupported':unsupported,'target':str(target)}))
else:
    MoonrakerService().inspect()
    print(json.dumps({'before':before}))
'''


def _inspect_patches(ctx):
    results = {}
    for patch in PATCHES:
        result = _remote(ctx, INSPECT, sudo=True, patch=patch)
        if 'unsupported' in result:
            print('Moonraker patches skipped: unsupported %s source %s: %s. '
                  'No Moonraker patch will be published; directory status stalls '
                  'and multiline HTTP error problems may remain.' %
                  (patch, result['target'], result['unsupported']))
            # Inspect the remaining patch too: a corrupt managed receipt or
            # unresolved service operation is not an unsupported-source skip.
        results[patch] = result
    return results


def preflight(ctx):
    ctx.moonraker_selected = _enabled(ctx)
    if not ctx.moonraker_selected:
        print('Moonraker patches not required for this legacy screen selection')
        return
    results = _inspect_patches(ctx)
    if any('unsupported' in result for result in results.values()):
        ctx.moonraker_selected = False
        return
    checks.require_paths(ctx, commands=('systemctl',),
                         files=(_paths(ctx)[0] + '/moonraker-env/bin/python',), sudo=True)


INSTALL = """
tx.prepare(target,state)
import subprocess
subprocess.run([str(home/'moonraker-env/bin/python'),'-c',
    'import pathlib,sys;compile(pathlib.Path(sys.argv[1]).read_bytes(),sys.argv[1],"exec")',
    str(tx.installed_path(state,tx.load_record(target,state)[0]))],check=True,timeout=15)
lifecycle.execute(target,state,MoonrakerService())
print(json.dumps({'source':tx.status(target,state)}))
"""


def install(ctx):
    selected = getattr(ctx, 'moonraker_selected', None)
    if selected is None:
        selected = _enabled(ctx)
    if not selected:
        return {'kind': 'moonraker-directory', 'skipped': True}
    results = _inspect_patches(ctx)
    if any('unsupported' in result for result in results.values()):
        return {'kind': 'moonraker-directory', 'skipped': True}
    entries = []
    for patch in PATCHES:
        result = results[patch]
        entries.append({'patch': patch, 'state': _paths(ctx, patch)[2],
                        'before': result['before']})
    receipt = {'kind': 'moonraker-patches', 'version': 1, 'patches': entries}
    journal = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
    if journal is not None:
        # Snapshot BOTH prior states before even the first backup is prepared.
        journal.prepare_component(NAME, receipt)
    try:
        for patch in PATCHES:
            _remote(ctx, INSTALL, sudo=True, patch=patch)
    except Exception:
        try:
            rollback(ctx, receipt)
        except Exception:
            backend = getattr(ctx, 'rollback_backend', None)
            if backend is not None:
                backend.blocked = True
            raise
        raise
    print('Moonraker directory and HTTP error patches verified; Klipper was not restarted')
    return receipt


def _receipt_entries(ctx, receipt):
    if receipt == {'kind': 'moonraker-directory', 'skipped': True}:
        return []
    # Continue to recover journals created by the directory-only installer.
    if (isinstance(receipt, dict) and set(receipt) == {'kind', 'state', 'before'}
            and receipt['kind'] == 'moonraker-directory'):
        entries = [dict(patch='directory', state=receipt['state'], before=receipt['before'])]
    elif (isinstance(receipt, dict) and set(receipt) == {'kind', 'version', 'patches'}
            and type(receipt['version']) is int and receipt['version'] == 1
            and receipt['kind'] == 'moonraker-patches'):
        entries = receipt['patches']
    else:
        raise ctx.DeployError('Invalid Moonraker component recovery receipt')
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(PATCHES):
        raise ctx.DeployError('Invalid Moonraker component recovery receipt')
    seen = set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'patch', 'state', 'before'}
                or entry['patch'] not in PATCHES or entry['patch'] in seen
                or entry['state'] != _paths(ctx, entry['patch'])[2]
                or entry['before'] not in ('original', 'installed', 'previous')
                or entry['before'] == 'previous' and entry['patch'] != 'directory'):
            raise ctx.DeployError('Invalid Moonraker component recovery receipt')
        seen.add(entry['patch'])
    return entries


def rollback(ctx, receipt):
    entries = _receipt_entries(ctx, receipt)
    # Recover any interrupted stop/publication before inspecting current HTTP
    # state for another patch. A live remote installer retains its file lock.
    for entry in entries:
        _remote(ctx, """
if not (state/'receipt.json').exists():
    if %r != 'original':raise ValueError('Missing Moonraker backup receipt')
    tx.reviewed_candidate(target,tx.read_regular(target)[0].decode())
else:
    _,original,installed=tx.load_record(target,state)
    current,_=tx.read_regular(target)
    if current not in tx.source_versions(target,state).values() and %r == 'original':
        # A fresh install may die before preparing its newly reviewed vendor
        # baseline. Rebaseline without restoring old source over that update.
        tx.prepare(target,state)
    lifecycle.execute(target,state,MoonrakerService(),recover=True)
print(json.dumps({'recovered':True}))
""" % (entry['before'], entry['before']), sudo=True, patch=entry['patch'])
    for entry in reversed(entries):
        _remote(ctx, """
service=MoonrakerService()
if (state/'receipt.json').exists():
    lifecycle.execute(target,state,service,restore=%r,previous=%r)
    result=tx.status(target,state)
else:
    tx.reviewed_candidate(target,tx.read_regular(target)[0].decode())
    service.verify(service.inspect())
    result='original'
print(json.dumps({'source':result}))
""" % (entry['before'] == 'original', entry['before'] == 'previous'), sudo=True, patch=entry['patch'])


def uninstall(ctx):
    entries = []
    for patch in PATCHES:
        managed = _remote(ctx, "print(json.dumps((state/'receipt.json').exists()))\n",
                          sudo=True, patch=patch)
        if managed:
            entries.append({'patch': patch, 'state': _paths(ctx, patch)[2], 'before': 'original'})
    if not entries:
        print('Moonraker sources are unmanaged; nothing to remove')
        return
    rollback(ctx, {'kind': 'moonraker-patches', 'version': 1, 'patches': entries})
    print('Original managed Moonraker implementations restored')


def status(ctx):
    for patch in PATCHES:
        result = _remote(ctx, """
print(json.dumps({'source':tx.status(target,state) if (state/'receipt.json').exists() else 'unmanaged'}))
""", sudo=True, patch=patch)
        print('Moonraker ' + patch + ' patch: ' + result['source'])
