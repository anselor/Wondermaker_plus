"""Component: touchscreen add-on (camera snapshot service, nginx page,
timelapse-camera fixer). Needs SSH and sudo. Uploads device/ and scripts/
to a staging directory and runs scripts/install.sh or uninstall.sh.
"""
import os
import posixpath
import sys
from local_env import require

PASS = os.environ.get("WMP_PASS")
STAGE = "/tmp/wondermaker_plus"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAYLOAD = ["device", "scripts"]



def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def run(c, cmd, sudo=False, stream=True):
    if sudo:
        password = PASS or require("WMP_PASS")
        cmd = "echo %s | sudo -S bash -c %s" % (password, shq(cmd))
    _, out, err = c.exec_command(cmd, timeout=300, get_pty=False)
    body = ""
    for line in iter(out.readline, ""):
        body += line
        if stream:
            sys.stdout.write(line)
            sys.stdout.flush()
    rc = out.channel.recv_exit_status()
    tail = err.read().decode("utf-8", "replace")
    # sudo's password prompt goes to stderr; only surface real errors.
    tail = "\n".join(l for l in tail.splitlines() if "password for" not in l)
    if tail.strip() and stream:
        sys.stderr.write(tail + "\n")
    return body, tail, rc


def mkdirs(sftp, path):
    parts, cur = path.strip("/").split("/"), ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def upload(c):
    sftp = c.open_sftp()
    run(c, "rm -rf %s" % STAGE, stream=False)
    mkdirs(sftp, STAGE)
    n = 0
    for top in PAYLOAD:
        for dirpath, _, files in os.walk(os.path.join(ROOT, top)):
            rel = os.path.relpath(dirpath, ROOT)
            remote_dir = posixpath.join(STAGE, rel.replace(os.sep, "/"))
            mkdirs(sftp, remote_dir)
            for fn in files:
                if fn.endswith((".pyc", ".swp")):
                    continue
                sftp.put(os.path.join(dirpath, fn),
                         posixpath.join(remote_dir, fn))
                n += 1
    sftp.close()
    run(c, "chmod +x %s/scripts/*.sh" % STAGE, stream=False)
    print("uploaded %d files to %s" % (n, STAGE))



NAME = "touchscreen"
DESCRIPTION = "touchscreen add-on: camera snapshot service, nginx page, boot-time timelapse-camera fixer"
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None


def install(ctx):
    c = ctx.ssh()
    upload(c)
    _, _, rc = run(c, "%s/scripts/install.sh" % STAGE, sudo=True)
    if rc != 0:
        raise ctx.DeployError("touchscreen install.sh exited %d" % rc)


def uninstall(ctx):
    c = ctx.ssh()
    upload(c)
    _, _, rc = run(c, "%s/scripts/uninstall.sh" % STAGE, sudo=True)
    if rc != 0:
        raise ctx.DeployError("touchscreen uninstall.sh exited %d" % rc)


def status(ctx):
    c = ctx.ssh()
    run(c, "systemctl status wmp-screen.service --no-pager -n 20 "
           "2>&1 | head -30; echo '--- endpoints ---'; "
           "curl -sf -m5 -o /dev/null -w 'snapshot %{http_code}\\n' "
           "http://127.0.0.1:8975/snapshot.jpg; "
           "curl -sf -m5 -o /dev/null -w 'nginx    %{http_code}\\n' "
           "http://127.0.0.1/wmp-screen/; "
           "curl -sf -m5 http://127.0.0.1:7125/server/webcams/list", sudo=True)
