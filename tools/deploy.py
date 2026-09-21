"""Deploy tool for everything this repo puts on the printer.

Components (tools/components/):
    config       Klipper config + bottom-Z extra (SSH), or --config-only (HTTP).
    touchscreen  camera snapshot service, nginx page, timelapse fixer. SSH + sudo.
    material     wm_material Klipper extra. SSH.
    preload      LD_PRELOAD patches for the touchscreen client (client-preload/). SSH + sudo.

    uv run --with paramiko python tools/deploy.py install config [--files macros.cfg ...]
    uv run python tools/deploy.py install config --config-only [--files macros.cfg ...]
    uv run python tools/deploy.py status config
    uv run --with paramiko python tools/deploy.py install all
    uv run --with paramiko python tools/deploy.py install material
    uv run --with paramiko python tools/deploy.py uninstall touchscreen
    uv run --with paramiko python tools/deploy.py status
    uv run python tools/deploy.py list

Klipper is restarted once at the end if an installed component needs it
(--no-restart to skip). Refuses to run during a print.
Env: WMP_PRINTER (default printer.local), WMP_USER (t13dp), WMP_PASS.
--config-only requires the matching wmp_recovery.py extra already installed.
"""
import argparse
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from components import REGISTRY, ORDER  # noqa: E402


class DeployError(Exception):
    pass


class Context:
    DeployError = DeployError

    def __init__(self, args):
        self.host = os.environ.get("WMP_PRINTER", "printer.local")
        self.user = os.environ.get("WMP_USER", "t13dp")
        self.password = os.environ.get("WMP_PASS", "CHANGE_ME")
        self.no_restart = getattr(args, "no_restart", False)
        self.diff = getattr(args, "diff", False)
        self.files = getattr(args, "files", []) or []
        self.config_only = getattr(args, "config_only", False)
        self._ssh = None
        self._sftp = None

    def ssh(self):
        if self._ssh is None:
            try:
                import paramiko
            except ImportError:
                sys.exit("this component needs SSH: run with `uv run --with paramiko python tools/deploy.py ...`")
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
        req = urllib.request.Request("http://%s:7125%s" % (self.host, path),
                                     method="POST" if post else "GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def printing_now(self):
        try:
            return '"state": "printing"' in self.moonraker("/printer/objects/query?print_stats")
        except Exception:
            return False

    def restart_klipper(self):
        print("firmware-restarting Klipper...")
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
        print("Klipper did not return to Ready - check klippy.log", file=sys.stderr)
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
                                 epilog=__doc__)
    ap.add_argument("action", choices=["status", "install", "uninstall", "list"])
    ap.add_argument("components", nargs="*",
                    help="component names, or 'all' (default: all for status; required for install/uninstall)")
    ap.add_argument("--no-restart", action="store_true", help="do not restart Klipper at the end")
    ap.add_argument("--files", nargs="*", default=[], help="config component: only push these files")
    ap.add_argument("--config-only", action="store_true",
                    help="install config via Moonraker HTTP only; requires the matching "
                         "wmp_recovery.py extra already installed")
    ap.add_argument("--diff", action="store_true",
                    help="config component status: show unified diff content, not just filenames")
    args = ap.parse_args()
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
        sys.exit("say which components (or 'all'): %s" % ", ".join(ORDER))

    ctx = Context(args)
    comps = resolve(args.components)
    rc = 0
    try:
        if args.action != "status" and ctx.printing_now():
            sys.exit("refusing to touch the printer while a print is in progress")
        need_restart = False
        for m in comps:
            print("=== %s: %s" % (m.NAME, args.action))
            try:
                getattr(m, args.action)(ctx)
                if args.action != "status" and m.RESTART_AFTER == "klipper":
                    need_restart = True
            except DeployError as e:
                print("!! %s: %s" % (m.NAME, e), file=sys.stderr)
                rc = 1
        if need_restart and not ctx.no_restart:
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
