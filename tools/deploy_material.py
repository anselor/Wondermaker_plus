"""Install / remove the optional wm_material Klipper extra on the printer.

    uv run --with paramiko python tools/deploy_material.py install
    uv run --with paramiko python tools/deploy_material.py uninstall
    uv run --with paramiko python tools/deploy_material.py status

install copies klipper_extras/wm_material.py into klippy/extras and
wm_material.cfg next to printer.cfg (picked up by printer.cfg's
`[include wm_material*.cfg]`), then firmware-restarts Klipper unless
--no-restart is given. uninstall removes both and restarts; macros then fall
back to temperature-based material inference. No sudo needed: both targets
are owned by the printer user.
"""
import argparse
import os
import sys
import time
import urllib.request

import paramiko

HOST = os.environ.get("WMP_PRINTER", "printer.local")
USER = os.environ.get("WMP_USER", "t13dp")
PASS = os.environ.get("WMP_PASS", "CHANGE_ME")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "klipper_extras")
EXTRA_DST = "/home/%s/klipper/klippy/extras/wm_material.py" % USER
CFG_DST = "/home/%s/printer_data/config/wm_material.cfg" % USER


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20,
              allow_agent=False, look_for_keys=False)
    return c


def exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except IOError:
        return False


def moonraker(path, post=False):
    req = urllib.request.Request("http://%s:7125%s" % (HOST, path),
                                 method="POST" if post else "GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


def restart_and_wait():
    print("firmware-restarting Klipper...")
    moonraker("/printer/firmware_restart", post=True)
    for _ in range(60):
        time.sleep(2)
        try:
            info = moonraker("/printer/info")
        except Exception:
            continue
        if '"state": "ready"' in info:
            print("Klipper is Ready")
            return True
        if '"state": "error"' in info or '"state": "shutdown"' in info:
            break
    print("Klipper did not return to Ready — check klippy.log", file=sys.stderr)
    return False


def status(sftp):
    print("wm_material.py: %s" % ("installed" if exists(sftp, EXTRA_DST) else "absent"))
    print("wm_material.cfg: %s" % ("installed" if exists(sftp, CFG_DST) else "absent"))
    try:
        q = moonraker("/printer/objects/query?wm_material")
        print("live object: %s" % ("present" if '"available"' in q else "absent"))
    except Exception as e:
        print("live object: (moonraker unreachable: %s)" % e)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["install", "uninstall", "status"])
    ap.add_argument("--no-restart", action="store_true")
    a = ap.parse_args()
    c = connect()
    sftp = c.open_sftp()
    if a.action == "status":
        status(sftp)
        return
    st = moonraker("/printer/objects/query?print_stats")
    if '"state": "printing"' in st:
        sys.exit("refusing to touch the printer while a print is in progress")
    if a.action == "install":
        sftp.put(os.path.join(SRC, "wm_material.py"), EXTRA_DST)
        sftp.put(os.path.join(SRC, "wm_material.cfg"), CFG_DST)
        print("installed %s and %s" % (EXTRA_DST, CFG_DST))
    else:
        for p in (EXTRA_DST, CFG_DST):
            if exists(sftp, p):
                sftp.remove(p)
                print("removed %s" % p)
    status(sftp)
    if not a.no_restart:
        ok = restart_and_wait()
        status(sftp)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
