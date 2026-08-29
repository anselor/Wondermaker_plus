"""Component: optional wm_material Klipper extra. Needs SSH (no sudo).
install copies klipper_extras/wm_material.py to ~/klipper/klippy/extras/ and
wm_material.cfg to ~/printer_data/config/. uninstall removes both. Klipper
must restart afterwards (deploy.py does this).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "klipper_extras")
EXTRA_DST = "klipper/klippy/extras/wm_material.py"      # relative to the printer user's home
CFG_DST = "printer_data/config/wm_material.cfg"




def exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except IOError:
        return False









NAME = "material"
DESCRIPTION = "wm_material Klipper extra: material-aware unload (reads the touchscreen's tmt1.ini)"
NEEDS_SSH = True
NEEDS_SUDO = False
RESTART_AFTER = "klipper"


def _paths(ctx):
    home = "/home/%s" % ctx.user
    return home + "/" + EXTRA_DST, home + "/" + CFG_DST


def install(ctx):
    sftp = ctx.sftp()
    extra, cfg = _paths(ctx)
    sftp.put(os.path.join(SRC, "wm_material.py"), extra)
    sftp.put(os.path.join(SRC, "wm_material.cfg"), cfg)
    print("installed %s and %s" % (extra, cfg))


def uninstall(ctx):
    sftp = ctx.sftp()
    for p in _paths(ctx):
        if exists(sftp, p):
            sftp.remove(p)
            print("removed %s" % p)


def status(ctx):
    sftp = ctx.sftp()
    extra, cfg = _paths(ctx)
    print("wm_material.py:  %s" % ("installed" if exists(sftp, extra) else "absent"))
    print("wm_material.cfg: %s" % ("installed" if exists(sftp, cfg) else "absent"))
    try:
        q = ctx.moonraker("/printer/objects/query?wm_material")
        print("live object:     %s" % ("present" if '"available"' in q else "absent (restart Klipper after install)"))
    except Exception as e:
        print("live object:     (moonraker unreachable: %s)" % e)
