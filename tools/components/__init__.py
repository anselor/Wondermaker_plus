"""Components for tools/deploy.py. Each module exposes:
    NAME, DESCRIPTION, NEEDS_SSH (bool), NEEDS_SUDO (bool)
    install(ctx)   -> None   (raise DeployError on failure)
    uninstall(ctx) -> None
    status(ctx)    -> None   (prints)
    RESTART_AFTER  -> "klipper" | None   # deploy.py restarts once at the end
ctx is a tools.deploy.Context: ssh(), sftp(), moonraker(), host, user, no_restart, files.
"""
from . import config, material, touchscreen

REGISTRY = {m.NAME: m for m in (config, touchscreen, material)}
ORDER = [config.NAME, touchscreen.NAME, material.NAME]
