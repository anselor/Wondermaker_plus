"""Component: Klipper config (config/live -> printer). Moonraker HTTP only;
works on a stock printer. install == utils/config_sync.py push, status == diff.
"""
import os
import subprocess
import sys

NAME = "config"
DESCRIPTION = "Klipper config from config/live (utils/config_sync.py)"
NEEDS_SSH = False
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
    _sync(["diff"], {"WMP_PRINTER": ctx.host})
