"""Component: LD_PRELOAD libraries for the touchscreen `client`. Needs SSH + sudo.

Legacy sources: client-preload/<name>/*.c. Exact reviewed1113 may use the
sealed prebuilt compat bundle; older supported profiles retain C-only builds.
All outputs are staged/verified before the known library destinations and
systemd drop-in are published. Failed publication/restart repairs previous files.
The systemd drop-in
/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf with
LD_PRELOAD listing every ~/wmp/lib/libwmp_*.so, then restarts
makerbase-client.service. Deployment explicitly requests a Klipper restart;
legacy stock client startup may also restart Klipper;
this is not a UI-only restart and cannot preserve an active or paused print. uninstall
removes the drop-in and the built libraries and restarts the service.
"""
import glob
import os
import posixpath
import json
import hashlib
import time
import re
from pathlib import Path
import preload_bundle

from .touchscreen import run, shq

NAME = "preload"
DESCRIPTION = "Touchscreen fixes and head-configuration protection"
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None
RESTARTS_BACKEND = True

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "client-preload")
DROPIN = "/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf"
DEFAULTS_DROPIN = "/etc/systemd/system/klipper.service.d/wmp-defaults.conf"
SERVICE = "makerbase-client.service"


def sources():
    out = []
    for d in sorted(glob.glob(os.path.join(SRC, "*", ""))):
        cs = glob.glob(os.path.join(d, "*.c"))
        if len(cs) == 1:
            out.append((os.path.basename(os.path.dirname(d)), cs[0]))
    return out


def _printer_home(ctx):
    return "/home/%s" % ctx.user


def _home(ctx):
    return "/home/%s/wmp" % ctx.user


def _printer_info(ctx):
    info = json.loads(ctx.moonraker('/printer/info'))['result']
    if not isinstance(info, dict):
        raise ValueError('invalid printer information')
    return info


def _restart(ctx, c, expected_guard=True):
    try:
        before = _printer_info(ctx)
    except Exception:
        before = {}
        observe = getattr(ctx, 'backend_service_status', None)
        if observe is not None:
            try:
                service = observe()
                if service.get('LoadState') == 'loaded':
                    pid = int(service['MainPID'])
                    if pid > 0 or (pid == 0 and service.get('ActiveState') in ('inactive', 'failed')):
                        before['process_id'] = pid
            except (OSError, ValueError, KeyError, ctx.DeployError):
                pass
    _checked(ctx, c, "systemctl daemon-reload && systemctl stop %s" % SERVICE, sudo=True)
    # Managed client startup deliberately does not restart Klipper. Deployment
    # owns this explicit process restart, including rollback to the prior generation.
    # FIRMWARE_RESTART only rebuilds Printer in the retained Python process;
    # imported helper modules remain cached and would keep running old code.
    # A lost acknowledgement may follow dispatch: observe, never repeat it.
    try:
        _checked(ctx, c, 'systemctl restart klipper.service', sudo=True)
    except Exception:
        pass
    _checked(ctx, c, "systemctl start %s" % SERVICE, sudo=True)
    if expected_guard is None:
        # Recovery restored these bytes before restarting. Verify that intended
        # service policy, rather than requiring the just-removed candidate guard.
        expected_guard = _helper(ctx, c,
            "p=Path(%r);print('1' if p.exists() and 'libwmp_head-config-guard.so' in p.read_text(encoding='utf-8') else '0')" % DROPIN,
            sudo=True) == '1'
    if expected_guard:
        verify_guard(ctx)
    else:
        verify_stock_client(ctx)
    # Legacy clients may additionally restart Klipper during startup. An old
    # Ready reply or internal startup transition proves no module reload; require a new PID.
    transitioned = False
    deadline = time.monotonic() + 120
    ready_samples = 0
    last = 'waiting for the explicitly requested Klipper restart'
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            out, _, rc = run(c, "systemctl is-active %s" % SERVICE, stream=False, timeout=10)
        except Exception as error:
            # This query is read-only. A lost SSH channel says nothing about
            # whether the already-dispatched restart succeeded. Reconnect only
            # for observation; never resend stop/start/restart here.
            ready_samples = 0
            last = 'service observation unavailable: ' + str(error)
            try:
                c = ctx.reconnect_ssh()
            except Exception as reconnect_error:
                last = 'service observation reconnect failed: ' + str(reconnect_error)
            continue
        if out.strip() == 'failed':
            raise ctx.DeployError("%s failed during startup" % SERVICE)
        try:
            info = _printer_info(ctx)
            state = info.get('state')
            transitioned = transitioned or (
                type(before.get('process_id')) is int and before['process_id'] >= 0
                and type(info.get('process_id')) is int and info['process_id'] > 0
                and before['process_id'] != info['process_id'])
            last = str(info.get('state_message') or state or 'unknown backend state')
            unchanged_error = (state in ('error', 'shutdown') and state == before.get('state')
                               and info.get('state_message') == before.get('state_message'))
            if rc == 0 and out.strip() == 'active' and (state == 'ready' or unchanged_error) and transitioned:
                ready_samples += 1
                if ready_samples >= 2:
                    ctx.preload_backend_ready = state == 'ready'
                    if ctx.preload_backend_ready:
                        print('Touchscreen active and Klipper Ready after process restart')
                    else:
                        print('Touchscreen active and new Klipper process verified; pre-existing backend %s remains: %s. Runtime protocols are not verified.' % (state, last))
                    return
            else:
                ready_samples = 0
        except (ValueError, KeyError, OSError) as error:
            # Loss of observation is not evidence that Klipper restarted.
            # Otherwise two replies from the old Ready process can falsely
            # complete the installer before the client's delayed restart.
            ready_samples = 0
            last = 'backend unavailable: ' + str(error)
    raise ctx.DeployError('Touchscreen restart did not reach verified Klipper Ready: ' + last)


BACKEND_CONTRACT_PATH = 'client-preload/unified-ui/native/backend_contract.json'


def backend_contract(root=None):
    """Read the paired delivery contract, never infer optional APIs as required."""
    value = json.loads((Path(ROOT if root is None else root) / BACKEND_CONTRACT_PATH).read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'version', 'required', 'optional',
            'backend_owned_protocols', 'backend_owned_commands'} or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('Invalid delivered backend contract schema')
    for group in ('required', 'optional'):
        expected = {'wm_material', 'wmp_recovery'} | ({'commands'} if group == 'required' else set())
        if not isinstance(value[group], dict) or set(value[group]) != expected:
            raise ValueError('Invalid backend contract ' + group + ' group')
        for owner in ('wm_material', 'wmp_recovery'):
            fields = value[group][owner]
            if not isinstance(fields, dict) or (group == 'required' and not fields) or any(not isinstance(name, str) or
                    not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?', name) or
                    type(version) is not int or version <= 0 for name, version in fields.items()):
                raise ValueError('Invalid backend contract protocol declaration')
            if group == 'optional' and fields.keys() & value['required'][owner].keys():
                raise ValueError('Backend protocol cannot be both required and optional')
    commands = value['required']['commands']
    if not isinstance(commands, list) or not commands or any(not isinstance(name, str) or
            not re.fullmatch(r'[A-Z_][A-Z0-9_]*', name) for name in commands) or len(set(commands)) != len(commands):
        raise ValueError('Invalid backend contract commands')
    for key, declared in (('backend_owned_protocols', value['required']['wm_material']),
                          ('backend_owned_commands', commands)):
        names = value[key]
        if not isinstance(names, list) or any(not isinstance(name, str) or name not in declared for name in names) or len(set(names)) != len(names):
            raise ValueError('Invalid backend-owned contract declarations')
    return value


# Compatibility exports for tooling/tests; the declaration is the only list.
BACKEND_PROTOCOLS = tuple(backend_contract()['required']['wm_material'])
BACKEND_COMMANDS = tuple(backend_contract()['required']['commands'])



# The native log is emitted by its background worker, never the GUI thread.
# Require a fresh sample from the exact mapped library in the one running client.
SCREEN_OBSERVATION = r"""
import hashlib,json,os,subprocess,time
from pathlib import Path
pids=subprocess.check_output(['pidof','client'],text=True,timeout=5).split()
if len(pids)!=1 or not pids[0].isdigit():raise ValueError('expected one screen process')
pid=pids[0];proc=Path('/proc')/pid
start=(proc/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()[19]
library=Path(LIBRARY);info=library.stat()
mapped=False
for line in (proc/'maps').read_text(encoding='utf-8').splitlines():
 parts=line.split(None,5)
 if len(parts)==6 and parts[5]==str(library):
  major,minor=(int(v,16) for v in parts[3].split(':'))
  mapped=mapped or (int(parts[4])==info.st_ino and
                    (major,minor)==(os.major(info.st_dev),os.minor(info.st_dev)))
log=Path('/tmp/wmp_openace_screen_'+pid+'.log')
with log.open() as stream:lines=stream.read(262145)
if len(lines)>262144:raise ValueError('screen diagnostic log exceeds bound')
last=lines.splitlines()[-1] if lines else ''
fields=dict(part.split('=',1) for part in last.split() if '=' in part)
if start!=(proc/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()[19]:
 raise ValueError('screen process changed during observation')
print(json.dumps({'pid':int(pid),'mapped':mapped,
 'client_sha256':hashlib.sha256((proc/'exe').read_bytes()).hexdigest(),
 'library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
 'now_ms':int(time.monotonic()*1000),'facts':fields}))
"""


def _check_screen_observation(value, bundle):
    if type(value.get('pid')) is not int or value['pid']<=0 or value.get('mapped') is not True:
        raise ValueError('sealed screen library is not mapped in the running client')
    if value.get('client_sha256')!=bundle['profile']['sha256']:
        raise ValueError('running screen executable differs from the reviewed client')
    if value.get('library_sha256')!=bundle['artifact']['sha256']:
        raise ValueError('running screen library differs from the sealed artifact')
    facts=value['facts']
    # Running=11 in the sealed native DiagnosticBootstrap contract.
    if int(facts['bootstrap'])!=11 or int(facts['errno_or_rc'])!=0:
        raise ValueError('native screen bootstrap did not complete')
    if any(int(facts[key])<=0 for key in ('timer_matches','refresh','status_polls')):
        raise ValueError('native GUI, worker or status synchronization has not started')
    age=value['now_ms']-int(facts['at_ms'])
    received=int(facts['status_received_at'])
    # The polling worker can receive a reply after the GUI captured at_ms.
    # Both timestamps must be judged against this observation's monotonic time.
    status_age=value['now_ms']-received
    if received<0 or not 0<=age<=15000 or not 0<=status_age<=10000:
        raise ValueError('native screen diagnostic/status sample is stale')


def _observe_running_screen(ctx):
    code=SCREEN_OBSERVATION.replace('LIBRARY',repr(_home(ctx)+'/lib/libwmp_openace-compat.so'))
    return json.loads(_checked(ctx,ctx.ssh(),'printf %s '+shq(code)+' | python3 -',sudo=True))


def _native_screen_status(ctx, bundle):
    # One observation only: status must never restart or wait for activation.
    try:
        value=_observe_running_screen(ctx)
        _check_screen_observation(value,bundle)
        return 'native GUI and status synchronization verified for pid '+str(value['pid'])
    except (ValueError,KeyError,TypeError,OSError,ctx.DeployError) as error:
        return 'native activation unconfirmed: '+str(error)


def _verify_running_screen(ctx, bundle):
    deadline=time.monotonic()+45
    last='waiting for native screen startup'
    while time.monotonic()<deadline:
        try:
            value=_observe_running_screen(ctx)
            _check_screen_observation(value,bundle)
            print('Running native screen artifact, GUI and status synchronization verified')
            return
        except (ValueError,KeyError,TypeError,OSError,ctx.DeployError) as error:
            last=str(error)
        time.sleep(2)
    raise ctx.DeployError('Native screen activation unconfirmed: '+last)


def _verify_running_backend(ctx):
    """Read-only post-restart acceptance; never submits any G-code."""
    try:
        contract = backend_contract()
        response=json.loads(ctx.moonraker('/printer/objects/query?wm_material&wmp_recovery&gcode'))
        status=response['result']['status']
        material=status['wm_material']
        recovery=status['wmp_recovery']
        commands=status['gcode']['commands']
        if not isinstance(material,dict) or not isinstance(recovery,dict) or not isinstance(commands,dict):
            raise ValueError('invalid backend status objects')
        if not isinstance(material.get('session_id'),str) or not material['session_id']:
            raise ValueError('missing material session')
        for owner in ('wm_material', 'wmp_recovery'):
            for path, version in contract['required'][owner].items():
                actual = status[owner]
                for key in path.split('.'):
                    actual = actual.get(key) if isinstance(actual, dict) else None
                if type(actual) is not int or actual != version:
                    raise ValueError('unsupported ' + (path if owner == 'wm_material' else owner + '.' + path))
        for name in ('z_reference_valid','homing','calibration_active'):
            if type(recovery.get(name)) is not bool:
                raise ValueError('missing recovery status: '+name)
        if not isinstance(recovery.get('calibration_session'),str) or not recovery['calibration_session']:
            raise ValueError('missing calibration session')
        ticket = recovery.get('calibration_next_ticket')
        if (not isinstance(ticket, str) or not ticket or len(ticket) > 256
                or ticket[0] == '0' or any(c not in '0123456789' for c in ticket)):
            raise ValueError('invalid calibration_next_ticket')
        if not isinstance(recovery.get('calibration_checkpoint'),str):
            raise ValueError('missing calibration checkpoint status')
        if not isinstance(recovery.get('calibration_failed'),str):
            raise ValueError('missing calibration failure status')
        editor = recovery.get('probe_editor')
        if not isinstance(editor, dict):
            raise ValueError('missing probe_editor status')
        if editor.get('session') != recovery['calibration_session']:
            raise ValueError('probe_editor session does not match calibration session')
        for name in ('save_review_required', 'save_review_confirmable', 'binding_valid'):
            if type(editor.get(name)) is not bool:
                raise ValueError('missing probe_editor.' + name)
        sequence = editor.get('save_review_sequence')
        if type(sequence) is not int or not 0 <= sequence <= 999999999:
            raise ValueError('invalid probe_editor.save_review_sequence')
        for name in ('filament_presence','filament_loaded'):
            heads=material.get(name)
            if not isinstance(heads,dict) or not all(isinstance(heads.get('h%d'%n),dict) for n in range(4)):
                raise ValueError('missing four-head status: '+name)
        for name in contract['required']['commands']:
            if name not in commands:raise ValueError('command not registered: '+name)
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise ctx.DeployError('Restarted backend does not support the installed screen: '+str(error)) from error
    print('Running material/recovery protocols and required commands verified')


def preflight(ctx):
    import preflight as checks
    checks.preload(ctx)


def screen_bundle():
    return preload_bundle.load_bundle(ROOT)


def _client(ctx):
    return '/home/'+ctx.user+'/TM_T1/bin/client'


def screen_preflight(ctx):
    script=preload_bundle.preflight_script(ROOT,_client(ctx),qualify=getattr(ctx,'qualify_unreleased_screen',False))
    if script:
        import preflight as checks
        checks.remote(ctx,script)


def _checked(ctx,c,command,**kwargs):
    out,err,code=run(c,command,stream=False,**kwargs)
    if code:raise ctx.DeployError(err or out or 'preload staging command failed')
    return out.strip()


def _helper(ctx,c,body,sudo=False):
    code=Path(preload_bundle.__file__).read_text(encoding='utf-8')+'\n'+body
    return _checked(ctx,c,'printf %s '+shq(code)+' | python3 -',sudo=sudo)


def verify_guard(ctx):
    import preflight as checks
    from verify_head_guard import guard_profiles
    source = os.path.join(ROOT, 'client-preload/head-config-guard/wmp_head_config_guard.c')
    with open(source, encoding='utf-8') as stream:
        profiles = guard_profiles(stream.read())
    with open(os.path.join(ROOT, 'tools/verify_head_guard.py'), encoding='utf-8') as stream:
        verifier = stream.read()
    checks.remote(ctx, verifier + '\nresult = wait_for_guard(%r, %r)\n'
                  'print("Head guard verified for screen pid %%s (client %%s)" %% '
                  '(result["pid"], result["version"]))\n' %
                  ('/home/' + ctx.user, profiles), sudo=True)


def verify_stock_client(ctx):
    import preflight as checks
    code = """import os, subprocess, time
from pathlib import Path
home = HOME
for attempt in range(30):
    pids = subprocess.run(['pidof', 'client'], stdout=subprocess.PIPE, text=True, timeout=5).stdout.split()
    if len(pids) == 1 and pids[0].isdigit():
        proc = Path('/proc') / pids[0]
        try:
            start = (proc/'stat').read_text().rsplit(')',1)[1].split()[19]
            executable = os.path.realpath(proc/'exe')
            mappings = (proc/'maps').read_text()
            if executable != home + '/TM_T1/bin/client':
                raise ValueError('Restored screen executable differs from installed client')
            if home + '/wmp/lib/libwmp_' in mappings:
                raise ValueError('Removed WM+ libraries remain mapped in restored screen')
            if start == (proc/'stat').read_text().rsplit(')',1)[1].split()[19]:
                print('Restored stock screen process verified: ' + pids[0])
                break
        except FileNotFoundError:
            pass
    time.sleep(1)
else:
    raise ValueError('Restored stock screen process did not stabilize')
""".replace('HOME', repr(_printer_home(ctx)))
    checks.remote(ctx, code, sudo=True)


def install(ctx):
    try:bundle=screen_bundle()  # Validate local sealed bytes BEFORE any remote mutation.
    except (ValueError,OSError) as error:raise ctx.DeployError('invalid screen bundle: '+str(error)) from error
    qualify=getattr(ctx,'qualify_unreleased_screen',False)
    if qualify and (bundle is None or preload_bundle.bundle_relative(ROOT)!=preload_bundle.CURRENT_BUNDLE
                    or bundle['scope']!='packaging-control-only'):
        raise ctx.DeployError('qualification requires the current packaging-control-only screen bundle')
    c=ctx.ssh();sftp=ctx.sftp();home=_home(ctx)
    _checked(ctx,c,'mkdir -p '+shq(home))
    stage=_checked(ctx,c,'mktemp -d '+shq(home+'/preload-stage-XXXXXX'))
    journal=getattr(getattr(ctx,'rollback_backend',None),'journal',None)
    receipt={'kind':'preload-stage','stage':stage,'phase':'staging'}
    if journal is not None:journal.prepare_component(NAME,receipt)
    completed=False;screen_selected=False;publication_attempted=False;restart_attempted=False
    try:
        outputs={}
        for name,path in sources():
            relative='client-preload/%s/%s'%(name,os.path.basename(path))
            remote=stage+'/'+relative
            _checked(ctx,c,'mkdir -p '+shq(posixpath.dirname(remote)))
            sftp.put(path,remote)
            _helper(ctx,c,"assert digest(%r)==%r, 'staged C source changed'"%(remote,hashlib.sha256(Path(path).read_bytes()).hexdigest()))
            lib='libwmp_%s.so'%name;output=stage+'/'+lib
            use_screen=False
            if name=='openace-compat' and bundle is not None:
                location=preload_bundle.bundle_relative(ROOT)
                directory=Path(ROOT)/location
                _checked(ctx,c,'mkdir -p '+shq(stage+'/'+location))
                for filename in ('bundle.json','source-inputs.json',bundle['artifact']['file']):
                    sftp.put(str(directory/filename),stage+'/'+location+'/'+filename)
                use_screen=_helper(ctx,c,"print('1' if select_delivery(%r,%r,qualify=%r) else '0')"%(stage,_client(ctx),qualify))=='1'
            if use_screen:
                try:preload_bundle.verify_source_binding(ROOT,bundle)
                except (ValueError,OSError) as error:
                    raise ctx.DeployError('native source delivery unavailable: '+str(error)) from error
                if location==preload_bundle.CURRENT_BUNDLE:
                    for relative in preload_bundle.CONFIG_BASELINES + ('client-preload/unified-ui/native/runtime_inputs.py',):
                        _checked(ctx,c,'mkdir -p '+shq(posixpath.dirname(stage+'/'+relative)))
                        sftp.put(str(Path(ROOT)/relative),stage+'/'+relative)
                screen_selected=True
                _checked(ctx,c,'cp '+shq(stage+'/'+location+'/'+bundle['artifact']['file'])+' '+shq(output))
                _helper(ctx,c,"assert digest(%r)==%r, 'staged output hash changed'"%(output,bundle['artifact']['sha256']))
            else:
                _checked(ctx,c,'gcc -shared -fPIC -O2 -Wall -pthread -o '+shq(output)+' '+shq(remote)+' -ldl')
            outputs[lib]=dict(file=lib,sha256=_helper(ctx,c,'print(digest(%r))'%output))
        _helper(ctx,c,"Path(%r).write_text(%r)"%(stage+'/outputs.json',json.dumps(outputs)))
        if ctx.printing_now():raise ctx.DeployError('A print started or paused during staging; no preload files were activated')
        if screen_selected:
            _helper(ctx,c,"verify_backend_helpers(%r,%r)"%(stage,'/home/'+ctx.user))
            _helper(ctx,c,"verify_backend_config(%r,%r)"%(stage,'/home/'+ctx.user))
        recovery_env = json.loads(_helper(ctx,c,"print(json.dumps(recovery_environment(%r)))" % _printer_home(ctx)))
        # Commit the publication intent before sending any installed-file write.
        # A staging receipt therefore proves publication was never dispatched.
        receipt=dict(receipt,phase='publication')
        if journal is not None:journal.prepare_component(NAME,receipt)
        publication_attempted=True
        start_backend = screen_selected and location == preload_bundle.CURRENT_BUNDLE
        defaults_paths = None
        if start_backend:
            defaults_source = Path(ROOT) / 'tools/factory_defaults.py'
            sftp.put(str(defaults_source), stage + '/factory_defaults.py')
            _helper(ctx,c,"assert digest(%r)==%r, 'staged defaults helper changed'" %
                    (stage + '/factory_defaults.py', hashlib.sha256(defaults_source.read_bytes()).hexdigest()))
            defaults_paths = {'helper': home + '/factory_defaults.py',
                              'dropin': DEFAULTS_DROPIN,
                              'home': _printer_home(ctx)}
        _helper(ctx,c,"print(json.dumps(publish_stage(%r,%r,%r,%r,start_backend=%r,defaults_paths=%r,require_guard=True)))"%(stage,home+'/lib',DROPIN,recovery_env,start_backend,defaults_paths),sudo=True)
        restart_attempted=True
        _restart(ctx,c)
        if screen_selected and location==preload_bundle.CURRENT_BUNDLE:
            if getattr(ctx, 'preload_backend_ready', True):
                _verify_running_backend(ctx)
                _verify_running_screen(ctx,bundle)
            else:
                print('Installed screen/backend files; runtime protocol and status synchronization checks deferred until the existing backend error is corrected.')
        completed=True
        if qualify:print('Unreleased screen qualification installation; package remains packaging-control-only')
        print('Published verified preload set; screen bundle scope: '+(bundle['scope'] if screen_selected else 'legacy C'))
        status(ctx)
        return receipt
    except Exception as original:
        completed=False
        if publication_attempted:
            try:
                # A candidate client may already be running. Keep it stopped
                # while restoring the matching UI and backend generations.
                if restart_attempted:
                    _checked(ctx,c,'systemctl stop '+SERVICE,sudo=True)
                _helper(ctx,c,'restore_publication(%r)'%stage,sudo=True)
                rollback_backend = getattr(ctx, 'rollback_backend', None)
                if rollback_backend is not None:
                    rollback_backend(service_stopped=restart_attempted)
                if restart_attempted:_restart(ctx,c,expected_guard=None)
            except Exception as repair:
                rollback_backend = getattr(ctx, 'rollback_backend', None)
                if rollback_backend is not None:
                    rollback_backend.blocked = True
                raise ctx.DeployError(str(original)+'; rollback/service recovery unconfirmed; retained journal '+stage+': '+str(repair)) from original
        raise
    finally:
        # A failed publication repairs itself in the remote helper. Keep journal
        # evidence if repair itself failed; cleanup only ordinary completed runs.
        if completed and journal is None:_checked(ctx,c,'rm -rf -- '+shq(stage))


def rollback(ctx, receipt):
    """Restore preload files with the client stopped; caller restores backend next."""
    import re
    stage=receipt.get('stage') if isinstance(receipt,dict) else None
    if (not isinstance(stage,str) or receipt.get('kind')!='preload-stage'
            or not re.fullmatch(re.escape(_home(ctx))+r'/preload-stage-[A-Za-z0-9]+',stage)):
        raise ctx.DeployError('Invalid preload recovery stage')
    phase=receipt.get('phase','publication')  # Legacy receipts require full recovery.
    if phase not in ('staging','publication'):
        raise ctx.DeployError('Invalid preload recovery phase')
    c=ctx.ssh()
    if phase=='staging':
        _helper(ctx,c,"p=Path(%r);assert p.is_dir() and not p.is_symlink(), 'invalid preload staging directory';j=p/'publication.json';assert not j.exists() and not j.is_symlink(), 'staging receipt conflicts with publication journal'"%stage,sudo=True)
        return
    _helper(ctx,c,"assert (Path(%r)/'publication.json').is_file(), 'preload recovery journal missing'"%stage,sudo=True)
    _checked(ctx,c,'systemctl stop '+SERVICE,sudo=True)
    _helper(ctx,c,'restore_publication(%r)'%stage,sudo=True)


def finish_recovery(ctx):
    _restart(ctx,ctx.ssh(),expected_guard=None)


def uninstall(ctx):
    c = ctx.ssh()
    for name, _ in sources():
        # Fresh publication creates lib/ as root; removal needs the same access.
        _checked(ctx, c, "rm -f -- " + shq(_home(ctx) + "/lib/libwmp_%s.so" % name), sudo=True)
    _checked(ctx, c, "rm -f -- " + shq(DROPIN), sudo=True)
    _checked(ctx, c, "rm -f -- " + shq(DEFAULTS_DROPIN) + " " + shq(_home(ctx) + "/factory_defaults.py"), sudo=True)
    _restart(ctx, c, expected_guard=False)
    print("Removed the WM+ screen service override and patch libraries; restarted the screen.")


def status(ctx):
    c = ctx.ssh()
    out, _, _ = run(c, "cat %s 2>/dev/null" % DROPIN, stream=False)
    print("Service override: %s" % (out.strip().replace("\n", " ") if out.strip() else "absent"))
    out, _, _ = run(c, "ls %s/lib/libwmp_*.so 2>/dev/null" % _home(ctx), stream=False)
    print("Library files:    %s" % (out.strip().replace("\n", " ") or "none"))
    pid, _, _ = run(c, "pidof client", stream=False)
    pid = pid.strip().split()[0] if pid.strip() else ""
    print("Screen process:   %s" % ("pid " + pid if pid else "not running"))
    out, _, _ = run(c, "[ -n %s ] && grep -o '/home/[^ ]*libwmp_[^ ]*' /proc/%s/maps | sort -u" %
                    (shq(pid), shq(pid)), sudo=True, stream=False)
    print("Loaded libraries: %s" % (out.strip().replace("\n", " ") or "none"))
    try:bundle=screen_bundle()
    except (ValueError,OSError) as error:
        print('native-screen: invalid local package; application unconfirmed: '+str(error));bundle=None
    if bundle is not None:
        installed=_helper(ctx,c,"p=Path(%r);print(digest(p) if p.is_file() else 'absent')"%(_home(ctx)+'/lib/libwmp_openace-compat.so'))
        current=preload_bundle.bundle_relative(ROOT)==preload_bundle.CURRENT_BUNDLE
        observation=_native_screen_status(ctx,bundle) if current else 'native hook/backend application unconfirmed'
        print('native-screen: local scope '+bundle['scope']+'; installed artifact '+('matches sealed bundle' if installed==bundle['artifact']['sha256'] else 'absent/different (legacy C or unverified)')+'; '+observation)
    for label, path in (("head-config-guard", "/tmp/wmp_head-config-guard.log"),
                        ("case-light", "/tmp/wmp_case-light.log"),
                        ("wifi-fix", "/tmp/wmp_wififix.log"),
                        ("fan-fix", "/tmp/wmp_fanfix.log"),
                        ("recovery-fix", "/tmp/wmp_recoveryfix.log"),
                        ("openace-compat", "/tmp/wmp_openace_compat.log")):
        if label=='openace-compat' and bundle is not None and preload_bundle.bundle_relative(ROOT)==preload_bundle.CURRENT_BUNDLE:
            continue  # Unified runtime uses the process-specific native log above.
        if pid:
            command = "grep -F %s %s 2>/dev/null | tail -n 1" % (shq("[pid %s]" % pid), path)
            out, _, _ = run(c, command, stream=False)
        else:
            out = ""
        result = out.strip() or "no log entry for the running screen process; patch application is unconfirmed"
        print(("%-14s" % (label + ":")) + result)
