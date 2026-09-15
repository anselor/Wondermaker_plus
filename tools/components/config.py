"""Component: Klipper config and required bottom-Z extra. Install needs SSH;
config transfer/status use Moonraker. Install extra before config can restart.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

NAME = "config"
DESCRIPTION = "Klipper config and required wmp_recovery native bottom-Z extra"
NEEDS_SSH = True
NEEDS_SUDO = False
RESTART_AFTER = None  # config_sync restarts Klipper itself

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYNC = os.path.join(ROOT, "utils", "config_sync.py")


def _sync(args, env_extra=None):
    sys.stdout.flush()
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.call([sys.executable, SYNC] + args, env=env)


def install(ctx):
    # This extra is required by [wmp_recovery] in printer.cfg. A config-only
    # update must install it before config_sync can reload the new section.
    source = os.path.join(ROOT, 'klipper_extras', 'wmp_recovery.py')
    destination = '/home/%s/klipper/klippy/extras/wmp_recovery.py' % ctx.user
    sftp = ctx.sftp()
    with open(source, 'rb') as f:
        content = f.read()
    try:
        with sftp.open(destination, 'rb') as f:
            previous = f.read()
    except FileNotFoundError:
        previous = None
    if previous != content:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        if previous is not None:
            with sftp.open(destination + '.wmp-backup-' + stamp, 'wb') as f:
                f.write(previous)
        temporary = destination + '.wmp-upload-' + stamp
        with sftp.open(temporary, 'wb') as f:
            f.write(content)
        sftp.posix_rename(temporary, destination)
        print('installed required extra: %s' % destination)
    args = ["push", "--yes"]
    if ctx.no_restart:
        args.append("--no-restart")
    args += ctx.files
    if _sync(args, {"WMP_PRINTER": ctx.host}) != 0:
        raise ctx.DeployError("config push failed")


def uninstall(ctx):
    raise ctx.DeployError("config has no uninstall; push config/stock instead if you "
                          "want vendor behaviour (see config/README.md)")


def status(ctx):
    args = ["diff"] + (["--patch"] if ctx.diff else [])
    _sync(args, {"WMP_PRINTER": ctx.host})
