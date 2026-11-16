"""Install, remove, or check Wondermaker+ components.

Components:
    config       Printer configuration and required recovery/light helpers.
    touchscreen  Clickable printer screen in Fluidd.
    material     Material settings for filament unloading.
    preload      Wi-Fi, fan, recovery, head protection, and light preference.
    shaper       Current upstream Klipper input shaper and resonance test.

Examples (run on your computer):
    uv run python tools/deploy.py list
    uv run python tools/deploy.py status config --diff
    uv run --with paramiko --with jinja2 python tools/deploy.py install all --preflight-only
    uv run --with paramiko --with jinja2 python tools/deploy.py install config preload
    uv run --with jinja2 python tools/deploy.py install config --config-only
    uv run --with paramiko python tools/deploy.py uninstall touchscreen

Set WMP_PRINTER, WMP_USER, and WMP_PASS in .env or your environment.
Full installation uses SSH; touchscreen, preload and shaper also need sudo.
Config-only updates use HTTP and require the matching recovery/light helpers
to be installed already. Config/material validation requires jinja2 locally.
See config/README.md.

Installation checks all selected components first. A running or paused
print blocks changes. Failed installs restore receipted backend changes when
safe; unreceipted legacy changes still need inspection.
The final Klipper restart can be deferred, but preload
installation/removal restarts the stock client, which also restarts Klipper.
It cannot preserve an active or paused print, even with --no-restart.
The touchscreen bridge restarts its own service during installation.
"""
import argparse
import json
import os
import re
import uuid
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from local_env import configure_ssh_client, require  # noqa: E402
from components import REGISTRY, ORDER  # noqa: E402


class DeployError(Exception):
    pass


class BackendRollback:
    """Keep backend publication receipts until the install has succeeded."""
    def __init__(self, ctx):
        self.ctx = ctx
        self.pending = []
        self.blocked = False
        self.untracked_config = False
        self.journal = None
        self.restart_component = None

    def record(self, component, receipt):
        if component.NAME == 'config' and receipt is None:
            self.untracked_config = True
        if component.NAME in ('config', 'material', 'touchscreen', 'moonraker', 'preload', 'shaper') and receipt is not None:
            self.pending.append((component, receipt))

    def __call__(self, *, service_stopped=False):
        if not self.pending and self.restart_component is None:
            return
        if self.blocked:
            raise DeployError('Component recovery is unconfirmed; backend files retained for inspection.')
        if self.untracked_config:
            raise DeployError('Legacy configuration has no rollback receipt; matching helpers retained for inspection.')
        # Validate the whole reverse dependency plan before its first mutation.
        for component, receipt in self.pending:
            if receipt is None or not callable(getattr(component, 'rollback', None)):
                raise DeployError('Automatic recovery unavailable for component: ' + component.NAME)
        if self.journal is not None:
            expected = self.journal.completed_recovery_receipts()
            actual = [(component.NAME, receipt) for component, receipt in reversed(self.pending)]
            from install_journal import encode
            if encode(actual) != encode(expected):
                raise DeployError('Rollback plan differs from recorded reverse component order')
        while self.pending:
            if (self.pending[-1][0].NAME != 'moonraker'
                    and not service_stopped and self.ctx.printing_now()):
                raise DeployError('Printer became active; backend rollback deferred until idle.')
            component, receipt = self.pending[-1]
            if component.NAME == 'preload':
                self.restart_component = component
                if self.journal is not None:
                    self.journal.value['recovery_restart_required'] = True
                    self.journal.save()
            component.rollback(self.ctx, receipt)
            if self.journal is not None:
                self.journal.restored_component(component.NAME, retain_inflight=True)
            self.pending.pop()
        if self.restart_component is not None:
            if not service_stopped and self.ctx.printing_now():
                raise DeployError('Printer became active; restored-service restart deferred.')
            self.restart_component.finish_recovery(self.ctx)
            if self.journal is not None:
                self.journal.value['recovery_restart_required'] = False
                self.journal.save()
            self.restart_component = None
        print('Restored earlier receipted component publications.')


def recover_backend(ctx):
    try:
        ctx.rollback_backend()
        return True
    except Exception as error:
        print('!! Backend rollback unconfirmed: ' + str(error), file=sys.stderr)
        return False


def create_install_journal(ctx, components):
    from install_journal import Journal
    path = Path(__file__).resolve().parents[1]/'.wmp-install-journals'/(uuid.uuid4().hex+'.json')
    journal = Journal(path)
    journal.acquire()
    try:
        journal.create(ctx.host or require('WMP_PRINTER'),
                       ctx.user or ('http-config-only' if ctx.config_only else require('WMP_USER')),
                       [component.NAME for component in components],
                       machine_id=(ctx.printer_machine_id() if hasattr(ctx, 'printer_machine_id')
                                   and not ctx.config_only else None))
    except Exception:
        journal.release()
        raise
    print('Installer recovery journal: '+str(path))
    return journal


def rebind_install_journal(ctx, path, previous_host, confirmed_machine_id):
    from install_journal import Journal
    identity = ctx.printer_machine_id()
    journal = Journal(path)
    journal.acquire()
    try:
        journal.rebind(ctx.host or require('WMP_PRINTER'), ctx.user or require('WMP_USER'),
                       identity, previous_host, confirmed_machine_id)
    finally:
        journal.release()
    print('Local recovery journal rebound from %s to %s for user %s, machine-id %s. '
          'No printer files, services, or recovery actions changed.' %
          (previous_host, ctx.host, ctx.user, identity))


def recover_installation(ctx, path):
    from install_journal import Journal
    journal = Journal(path)
    journal.acquire()
    try:
        identity = ctx.printer_machine_id() if hasattr(ctx, 'printer_machine_id') else None
        journal.load(ctx.host or require('WMP_PRINTER'), ctx.user or require('WMP_USER'), machine_id=identity)
        pending = journal.recovery_receipts()
        # Refuse unsupported receipts before undoing any earlier dependency.
        for name, receipt in pending:
            if (name not in ('config', 'material', 'touchscreen', 'moonraker', 'preload', 'shaper') or receipt is None
                    or not callable(getattr(REGISTRY[name], 'rollback', None))):
                raise DeployError('Automatic recovery unavailable for component: '+name)
        if any(name == 'preload' for name, _ in pending):
            journal.value['recovery_restart_required'] = True
            journal.save()
        for name, receipt in pending:
            # An interrupted Moonraker stop can make HTTP unavailable. Its
            # locked recovery restores only that service, then enforces the
            # saved Klipper identity/state before any earlier component undo.
            if name != 'moonraker' and ctx.printing_now():
                raise DeployError('Printer became active; remaining recovery deferred')
            REGISTRY[name].rollback(ctx, receipt)
            journal.restored_component(name)
        restarted = bool(journal.value.get('recovery_restart_required'))
        if restarted:
            if ctx.printing_now():
                raise DeployError('Printer became active; recovery restart deferred')
            REGISTRY['preload'].finish_recovery(ctx)
            journal.value['recovery_restart_required'] = False
            journal.save()
        journal.finish(recovered=True)
        if restarted:
            print('Recorded component files/settings restored; client restart and backend state verified.')
        elif journal.value['components'] == ['moonraker']:
            print('Moonraker recovered and Ready verified; Klipper was not restarted.')
        else:
            print('Recorded component files/settings restored. Backend restart/readiness must still be verified before printing.')
    finally:
        journal.release()


class Context:
    DeployError = DeployError

    def __init__(self, args):
        self.host = os.environ.get("WMP_PRINTER")
        self.user = os.environ.get("WMP_USER")
        self.password = os.environ.get("WMP_PASS")
        self.no_restart = getattr(args, "no_restart", False)
        self.diff = getattr(args, "diff", False)
        self.files = getattr(args, "files", []) or []
        self.config_only = getattr(args, "config_only", False)
        self.preflight_only = getattr(args, "preflight_only", False)
        self.qualify_unreleased_screen = getattr(args, "qualify_unreleased_screen", False)
        self._ssh = None
        self._sftp = None

    def ssh(self):
        if self._ssh is None:
            self.host = self.host or require("WMP_PRINTER")
            self.user = self.user or require("WMP_USER")
            self.password = self.password or require("WMP_PASS")
            try:
                import paramiko
            except ImportError:
                sys.exit("this component needs SSH: run with `uv run --with paramiko python tools/deploy.py ...`")
            c = paramiko.SSHClient()
            configure_ssh_client(c)
            c.connect(self.host, username=self.user, password=self.password,
                      timeout=20, allow_agent=False, look_for_keys=False)
            self._ssh = c
        return self._ssh

    def reconnect_ssh(self):
        """Replace a failed observation transport; never replay its command."""
        self.close()
        self._sftp = self._ssh = None
        return self.ssh()

    def sftp(self):
        if self._sftp is None:
            self._sftp = self.ssh().open_sftp()
        return self._sftp

    def close(self):
        if self._sftp:
            self._sftp.close()
        if self._ssh:
            self._ssh.close()

    def moonraker(self, path, post=False):
        self.host = self.host or require("WMP_PRINTER")
        req = urllib.request.Request("http://%s:7125%s" % (self.host, path),
                                     method="POST" if post else "GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def printer_machine_id(self):
        from components.touchscreen import run
        from install_journal import validate_machine_id
        out, err, rc = run(self.ssh(), 'cat /etc/machine-id', stream=False, timeout=10)
        if rc:
            raise DeployError('Cannot read printer identity: ' + err.strip())
        return validate_machine_id(out.strip())

    def backend_service_status(self):
        from components.touchscreen import run
        out, err, rc = run(self.ssh(),
            'systemctl show klipper.service --property=LoadState --property=ActiveState '
            '--property=MainPID --property=ExecMainStartTimestampMonotonic',
            stream=False, timeout=10)
        if rc:
            raise DeployError('Cannot observe Klipper service: ' + err.strip())
        return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)

    def printing_now(self):
        try:
            status = json.loads(self.moonraker("/printer/objects/query?print_stats&pause_resume&virtual_sdcard"))
            state = status['result']['status']['print_stats']['state']
            if state not in ('standby', 'complete', 'cancelled', 'error', 'printing', 'paused'):
                raise ValueError('print_stats.state is unsupported')
            objects = status['result']['status']
            self.print_admission_reason = ('print_stats.state=%s, pause_resume.is_paused=%r, virtual_sdcard.is_active=%r'
                % (state, objects.get('pause_resume', {}).get('is_paused'), objects.get('virtual_sdcard', {}).get('is_active')))
            return (state in ('printing', 'paused')
                    or objects.get('pause_resume', {}).get('is_paused') is True
                    or objects.get('virtual_sdcard', {}).get('is_active') is True)
        except Exception as exc:
            # Config repair is possible with Klipper stopped, but an unreachable
            # or ambiguous API must never be treated as evidence of an idle printer.
            try:
                state = json.loads(self.moonraker('/printer/info'))['result']['state']
            except Exception:
                state = None
            if state in ('error', 'shutdown'):
                return False
            try:
                service = self.backend_service_status()
                if (service.get('LoadState') == 'loaded'
                        and service.get('ActiveState') in ('inactive', 'failed')
                        and service.get('MainPID') == '0'):
                    return False
            except Exception:
                pass
            detail = ('missing status field ' + str(exc) if isinstance(exc, KeyError)
                      else 'print_stats response is not valid JSON' if isinstance(exc, json.JSONDecodeError)
                      else 'print_stats.state is unsupported' if isinstance(exc, ValueError)
                      else 'print_stats response has an invalid object structure' if isinstance(exc, TypeError)
                      else 'print_stats query failed: ' + type(exc).__name__)
            backend = state if state in ('ready', 'startup', 'disconnected') else 'unavailable or unsupported'
            raise DeployError('cannot establish that the printer is idle: %s; printer/info.state=%s; '
                              'SSH did not confirm a stopped Klipper service. Check the service before repair.'
                              % (detail, backend)) from exc

    def wait_for_backend(self, timeout=90.):
        """Allow the stock screen's startup restart to finish without retrying it."""
        deadline = time.monotonic() + timeout
        detail = 'backend is starting'
        while True:
            try:
                state = json.loads(self.moonraker('/printer/info'))['result']['state']
                # Error/shutdown permit repairs; Ready is not a prerequisite.
                if state in ('ready', 'error', 'shutdown'):
                    print('Backend state after screen restart: %s' % state)
                    return
                detail = 'backend state is %s' % state
            except (OSError, ValueError, KeyError) as error:
                detail = str(error)
            if time.monotonic() >= deadline:
                raise DeployError('Backend did not finish starting after the screen restart: %s. '
                                  'No additional controller restart was attempted.' % detail)
            time.sleep(1.)

    def restart_klipper(self):
        reload_modules = (not self.config_only and bool(
            {'config', 'material', 'shaper'} & set(getattr(self, 'installing_components', ()))))
        print('Restarting Klipper process...' if reload_modules else 'Restarting Klipper and its controllers...')
        try:
            before = json.loads(self.moonraker('/printer/info'))['result']
            if not isinstance(before, dict):
                before = {}
        except Exception:
            before = {}
        if reload_modules and type(before.get('process_id')) is not int:
            try:
                service = self.backend_service_status()
                if service.get('LoadState') == 'loaded':
                    before['process_id'] = int(service['MainPID'])
            except Exception:
                pass
        try:
            if reload_modules:
                from components.touchscreen import run
                run(self.ssh(), 'systemctl restart klipper.service', sudo=True, stream=False, timeout=45)
            else:
                self.moonraker("/printer/firmware_restart", post=True)
        except Exception:
            # A lost response can follow a successful dispatch. Observe that
            # attempt rather than sending a second restart command.
            pass
        transitioned = not reload_modules and before.get('state') in ('error', 'shutdown', 'startup')
        deadline = time.monotonic() + 120
        ready_samples = 0
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                info = json.loads(self.moonraker('/printer/info'))['result']
                state = info['state']
            except Exception:
                ready_samples = 0
                continue
            transitioned = transitioned or (not reload_modules and state == 'startup') or (
                before.get('process_id') is not None and info.get('process_id') is not None
                and before['process_id'] != info['process_id'])
            same_error = (type(before.get('process_id')) is int
                          and type(info.get('process_id')) is int
                          and info['process_id'] != before['process_id']
                          and state in ('error', 'shutdown') and state == before.get('state')
                          and info.get('state_message') == before.get('state_message'))
            if transitioned and (state == 'ready' or same_error):
                ready_samples += 1
                if ready_samples >= 2:
                    if state == 'ready':
                        print("Klipper is Ready after verified restart")
                    else:
                        print('Klipper restarted; existing backend %s remains: %s. '
                              'Files are activated, but printing requires correcting this error.'
                              % (state, info.get('state_message', 'see klippy.log')))
                    return True
            else:
                ready_samples = 0
        print("Klipper restart did not reach verified Ready. Check klippy.log before printing.", file=sys.stderr)
        return False


def resolve(names):
    if not names or names == ["all"]:
        return [REGISTRY[n] for n in ORDER]
    out = []
    for n in names:
        if n not in REGISTRY:
            sys.exit("unknown component %r (known: %s)" % (n, ", ".join(ORDER)))
        out.append(REGISTRY[n])
    return sorted(out, key=lambda m: ORDER.index(m.NAME))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 1)[1].strip())
    ap.add_argument("action", choices=["status", "install", "uninstall", "list", "recover", "rebind-journal"])
    ap.add_argument('--from-host', help='rebind-journal: exact previous journal destination')
    ap.add_argument('--confirm-machine-id', help='rebind-journal: independently checked destination /etc/machine-id')
    ap.add_argument('--journal', help='recover touchscreen: printer-side path; recover all: local installer journal path')
    ap.add_argument("components", nargs="*",
                    help="components to act on, or all; status defaults to all")
    ap.add_argument("--no-restart", action="store_true", help="defer only the final Klipper restart; preload and moonraker component service restarts still run")
    ap.add_argument("--files", nargs="*", default=[], help="install config: upload only the named configuration files")
    ap.add_argument("--config-only", action="store_true",
                    help="install config via Moonraker HTTP only; requires the matching "
                         "recovery/light helpers to be installed already")
    ap.add_argument("--diff", action="store_true",
                    help="status config: show changed lines as well as filenames")
    ap.add_argument("--preflight-only", action="store_true",
                    help="check installation requirements without installing or restarting services")
    ap.add_argument('--qualify-unreleased-screen', action='store_true',
                    help='development qualification only: allow the source-bound current packaging-control-only screen on its exact client; does not promote a release')
    args = ap.parse_args()
    if args.qualify_unreleased_screen and (args.action != 'install'
            or not ('preload' in args.components or args.components == ['all'])):
        ap.error('--qualify-unreleased-screen requires install preload (or all)')
    if args.action == 'rebind-journal':
        if args.components != ['all'] or not args.journal or not Path(args.journal).is_file() or not args.from_host or not args.confirm_machine_id:
            ap.error('Rebinding requires rebind-journal all --journal PATH --from-host OLD --confirm-machine-id HEX')
        if args.no_restart or args.files or args.diff or args.config_only or args.preflight_only:
            ap.error('Rebinding cannot be combined with installation options')
    elif args.from_host or args.confirm_machine_id:
        ap.error('--from-host and --confirm-machine-id are only valid for rebind-journal')
    if args.action == 'recover':
        if args.components not in (['touchscreen'], ['all']) or not args.journal:
            ap.error('Recovery requires recover touchscreen or recover all, with --journal PATH')
        if args.components == ['touchscreen'] and not re.fullmatch(r'/opt/wondermaker_plus-transactions/[0-9a-f]{32}\.json', args.journal):
            ap.error('Expected the touchscreen journal path printed by the installer')
        if args.components == ['all'] and not Path(args.journal).is_file():
            ap.error('The local installer journal does not exist')
        if args.no_restart or args.files or args.diff or args.config_only or args.preflight_only:
            ap.error('Recovery cannot be combined with installation or diff options')
    elif args.journal and args.action != 'rebind-journal':
        ap.error('--journal is only valid with recovery')
    if args.preflight_only and args.action != "install":
        ap.error("--preflight-only is only valid with install")
    if args.config_only and (args.action != "install" or args.components != ["config"]):
        ap.error("--config-only is only valid with 'install config'")

    if args.action == "list":
        for n in ORDER:
            m = REGISTRY[n]
            need = "SSH + sudo" if m.NEEDS_SUDO else ("SSH" if m.NEEDS_SSH else "Moonraker HTTP (stock printer)")
            if n == "config":
                need = "SSH; --config-only: HTTP"
            print("%-12s %-30s %s" % (n, need, m.DESCRIPTION))
        return 0
    if args.action in ("install", "uninstall") and not args.components:
        sys.exit("Choose components to %s, or use all. Available: %s" % (args.action, ", ".join(ORDER)))

    ctx = Context(args)
    ctx.rollback_backend = BackendRollback(ctx)
    comps = resolve(args.components)
    if args.action == 'uninstall':
        # Remove screen consumers first, then configuration before its helpers.
        removal_order = ('touchscreen', 'shaper', 'preload', 'config', 'material', 'moonraker')
        comps.sort(key=lambda component: removal_order.index(component.NAME))
    if ctx.qualify_unreleased_screen:
        print('Development qualification: unreleased screen, exact client and source checks required; service restart remains mandatory.')
    ctx.moonraker_implicit = 'moonraker' not in args.components
    if args.action == 'install' and any(c.NAME == 'preload' for c in comps):
        if not any(c.NAME == 'moonraker' for c in comps):
            comps.append(REGISTRY['moonraker'])
            comps.sort(key=lambda c: ORDER.index(c.NAME))
    ctx.installing_components = {component.NAME for component in comps} if args.action == 'install' else set()
    rc = 0
    try:
        try:
            if (args.action not in ("status", "rebind-journal") and not (args.action == "recover" and args.components == ["all"])
                    and ctx.printing_now()):
                sys.exit("A print is in progress or paused. Finish or cancel it before changing the installation. "
                         + getattr(ctx, "print_admission_reason", "print_stats.state is printing or paused"))
        except DeployError as exc:
            print("!! Installation check: %s" % exc, file=sys.stderr)
            return 1
        if args.action == 'rebind-journal':
            try:
                rebind_install_journal(ctx, args.journal, args.from_host, args.confirm_machine_id)
            except Exception as error:
                print('!! Journal rebinding refused: ' + str(error), file=sys.stderr)
                return 1
            return 0
        if args.action == 'recover':
            try:
                if args.components == ['all']:
                    recover_installation(ctx, args.journal)
                else:
                    REGISTRY['touchscreen'].rollback(ctx, {'kind': 'touchscreen-transaction', 'journal': args.journal})
            except Exception as error:
                print('!! Installation recovery unconfirmed: '+str(error), file=sys.stderr)
                return 1
            print('Recovery completed from '+args.journal)
            return 0
        if args.action == 'install':
            failures = []
            for component in comps:
                print('=== %s: checking installation requirements' % component.NAME)
                try:
                    component.preflight(ctx)
                except Exception as exc:
                    failures.append(component.NAME)
                    print('!! %s: %s' % (component.NAME, exc), file=sys.stderr)
            if failures:
                print('Installation checks failed; no components installed. Fix the reported issue and retry.', file=sys.stderr)
                return 1
            print('All selected components passed installation checks.')
            if args.preflight_only:
                return 0
            try:
                ctx.rollback_backend.journal = create_install_journal(ctx, comps)
            except Exception as error:
                print('Cannot save installation recovery journal: '+str(error), file=sys.stderr)
                return 1
        need_restart = False
        for m in comps:
            print("=== %s: %s" % (m.NAME, args.action))
            try:
                if args.action == "install" and ctx.printing_now():
                    raise DeployError("A print started or paused after the checks. Finish or cancel it before retrying installation. "
                                      + getattr(ctx, "print_admission_reason", "print_stats.state is printing or paused"))
                journal = ctx.rollback_backend.journal
                if args.action == 'install' and journal is not None:
                    journal.begin(m.NAME)
                receipt = getattr(m, args.action)(ctx)
                if args.action == 'install':
                    ctx.rollback_backend.record(m, receipt)
                    if journal is not None:
                        journal.complete_component(m.NAME, receipt)
                if args.action != "status" and m.RESTART_AFTER == "klipper":
                    need_restart = True
                if args.action == 'install' and getattr(m, 'RESTARTS_BACKEND', False):
                    need_restart = False
            except DeployError as e:
                print("!! %s: %s" % (m.NAME, e), file=sys.stderr)
                rc = 1
                if args.action == 'uninstall':
                    print('Removal stopped; later dependencies were retained.', file=sys.stderr)
                    return rc
                if args.action == 'install':
                    recover_backend(ctx)
                    print('Installation stopped. Check component status before printing; non-backend changes may remain.', file=sys.stderr)
                    return rc
            except Exception as exc:
                if args.action != 'install':
                    raise
                print('!! %s: %s' % (m.NAME, exc), file=sys.stderr)
                recover_backend(ctx)
                print('Installation stopped. Check component status before printing; non-backend changes may remain.', file=sys.stderr)
                return 1
        if need_restart and not ctx.no_restart:
            if 'preload' in ctx.installing_components:
                try:
                    REGISTRY['preload'].verify_guard(ctx)
                except Exception as exc:
                    print('!! Final Klipper restart blocked: %s' % exc, file=sys.stderr)
                    return 1
            try:
                if ctx.printing_now():
                    raise DeployError('The printer became active. Files are uploaded, but Klipper was not restarted. Restart it after the print finishes.')
            except DeployError as exc:
                print('!! %s' % exc, file=sys.stderr)
                return 1
            if not ctx.restart_klipper():
                rc = 1
                if ctx.rollback_backend.pending and recover_backend(ctx):
                    print('Retrying startup once with the restored backend files.')
                    if not ctx.restart_klipper():
                        print('Previous backend startup remains unconfirmed; inspect the printer before use.', file=sys.stderr)
            for m in comps:
                if m.RESTART_AFTER == "klipper":
                    print("=== %s: status" % m.NAME)
                    m.status(ctx)
        if args.action == 'install' and rc == 0 and ctx.rollback_backend.journal is not None:
            try:
                ctx.rollback_backend.journal.finish()
            except Exception as error:
                print('Installation completed but its final journal checkpoint is unconfirmed: '+str(error), file=sys.stderr)
                return 1
    finally:
        if ctx.rollback_backend.journal is not None:
            ctx.rollback_backend.journal.release()
        ctx.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
