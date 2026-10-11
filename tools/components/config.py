"""Component: Klipper config and required bottom-Z extra. Full install needs SSH;
--config-only and status use Moonraker. Install extra before config can restart.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone

NAME = "config"
DESCRIPTION = "Printer configuration and required recovery helper"
NEEDS_SSH = True
NEEDS_SUDO = False
RESTART_AFTER = "klipper"  # activate only after every selected component is installed

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYNC = os.path.join(ROOT, "utils", "config_sync.py")


def _sync(args, env_extra=None):
    sys.stdout.flush()
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.call([sys.executable, SYNC] + args, env=env)


def _install_extra(ctx):
    # This extra is required by [wmp_recovery] in printer.cfg.
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
        print('Installed recovery helper: %s' % destination)


def preflight(ctx):
    import preflight as checks
    checks.config(ctx)


def install(ctx):
    if getattr(ctx, "config_only", False):
        print('Updating configuration over HTTP; '
              'the matching wmp_recovery.py helper must already be installed')
    else:
        _install_extra(ctx)
    args = ["push", "--yes", "--no-restart"]
    args += ctx.files
    if _sync(args, {"WMP_PRINTER": ctx.host}) != 0:
        raise ctx.DeployError("Configuration upload failed. Check the preceding error and the printer backups before retrying.")


def uninstall(ctx):
    raise ctx.DeployError("Configuration has no automatic uninstall. To restore vendor configuration, "
                          "review config/README.md before using config/stock.")


def status(ctx):
    args = ["diff"] + (["--patch"] if ctx.diff else [])
    _sync(args, {"WMP_PRINTER": ctx.host})
