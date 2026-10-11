"""Install, remove, or check Wondermaker+ components.

Components:
    config       Printer configuration and required recovery helper.
    touchscreen  Clickable printer screen in Fluidd.
    material     Material settings for filament unloading.
    preload      Wi-Fi, fan, recovery, openACE, and head-configuration protection.

Examples (run on your computer):
    uv run python tools/deploy.py list
    uv run python tools/deploy.py status config --diff
    uv run --with paramiko python tools/deploy.py install all --preflight-only
    uv run --with paramiko python tools/deploy.py install config preload
    uv run python tools/deploy.py install config --config-only
    uv run --with paramiko python tools/deploy.py uninstall touchscreen

Set WMP_PRINTER, WMP_USER, and WMP_PASS in .env or your environment.
Full installation uses SSH; touchscreen and preload also need sudo.
Config-only updates use HTTP and require the matching wmp_recovery.py
helper to be installed already. See config/README.md.

Installation checks all selected components first. A running or paused
print blocks changes. Earlier applied changes are not undone if a later
installation step fails. Klipper restarts once at the end when needed;
touchscreen components restart their own services during installation.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from local_env import configure_ssh_client, require  # noqa: E402
from components import REGISTRY, ORDER  # noqa: E402


class DeployError(Exception):
    pass


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

    def printing_now(self):
        try:
            status = json.loads(self.moonraker("/printer/objects/query?print_stats"))
            state = status['result']['status']['print_stats']['state']
            if state not in ('standby', 'complete', 'cancelled', 'error', 'printing', 'paused'):
                raise ValueError('unknown print state')
            return state in ('printing', 'paused')
        except Exception as exc:
            # Config repair is possible with Klipper stopped, but an unreachable
            # or ambiguous API must never be treated as evidence of an idle printer.
            try:
                state = json.loads(self.moonraker('/printer/info'))['result']['state']
            except Exception:
                state = None
            if state in ('error', 'shutdown'):
                return False
            raise DeployError('cannot establish that the printer is idle; further changes are blocked. Check the printer connection and status, then retry.') from exc

    def restart_klipper(self):
        print("Restarting Klipper and its controllers...")
        self.moonraker("/printer/firmware_restart", post=True)
        for _ in range(60):
            time.sleep(2)
            try:
                info = self.moonraker("/printer/info")
            except Exception:
                continue
            if '"state": "ready"' in info:
                print("Klipper is Ready")
                return True
            if '"state": "error"' in info or '"state": "shutdown"' in info:
                break
        print("Klipper did not return to Ready. Check klippy.log before printing.", file=sys.stderr)
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
    ap.add_argument("action", choices=["status", "install", "uninstall", "list"])
    ap.add_argument("components", nargs="*",
                    help="components to act on, or all; status defaults to all")
    ap.add_argument("--no-restart", action="store_true", help="defer the final Klipper restart; touchscreen services may still restart")
    ap.add_argument("--files", nargs="*", default=[], help="install config: upload only the named configuration files")
    ap.add_argument("--config-only", action="store_true",
                    help="install config via Moonraker HTTP only; requires the matching "
                         "wmp_recovery.py helper to be installed already")
    ap.add_argument("--diff", action="store_true",
                    help="status config: show changed lines as well as filenames")
    ap.add_argument("--preflight-only", action="store_true",
                    help="check installation requirements without installing or restarting services")
    args = ap.parse_args()
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
    comps = resolve(args.components)
    rc = 0
    try:
        try:
            if args.action != "status" and ctx.printing_now():
                sys.exit("A print is in progress or paused. Finish or cancel it before changing the installation.")
        except DeployError as exc:
            print("!! Installation check: %s" % exc, file=sys.stderr)
            return 1
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
        need_restart = False
        for m in comps:
            print("=== %s: %s" % (m.NAME, args.action))
            try:
                if args.action == "install" and ctx.printing_now():
                    raise DeployError("A print started or paused after the checks. Finish or cancel it before retrying installation.")
                getattr(m, args.action)(ctx)
                if args.action != "status" and m.RESTART_AFTER == "klipper":
                    need_restart = True
            except DeployError as e:
                print("!! %s: %s" % (m.NAME, e), file=sys.stderr)
                rc = 1
                if args.action == 'install':
                    print('Installation stopped. Earlier changes were not undone; check component status before printing.', file=sys.stderr)
                    return rc
            except Exception as exc:
                if args.action != 'install':
                    raise
                print('!! %s: %s' % (m.NAME, exc), file=sys.stderr)
                print('Installation stopped. Earlier changes were not undone; check component status before printing.', file=sys.stderr)
                return 1
        if need_restart and not ctx.no_restart:
            try:
                if ctx.printing_now():
                    raise DeployError('The printer became active. Files are uploaded, but Klipper was not restarted. Restart it after the print finishes.')
            except DeployError as exc:
                print('!! %s' % exc, file=sys.stderr)
                return 1
            if not ctx.restart_klipper():
                rc = 1
            for m in comps:
                if m.RESTART_AFTER == "klipper":
                    print("=== %s: status" % m.NAME)
                    m.status(ctx)
    finally:
        ctx.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
