"""Component: LD_PRELOAD libraries for the touchscreen `client`. Needs SSH + sudo.

Sources: client-preload/<name>/*.c (one .c per directory). install uploads
each source to ~/wmp/src/<name>/, builds it on the printer with gcc into
~/wmp/lib/libwmp_<name>.so, writes the systemd drop-in
/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf with
LD_PRELOAD listing every ~/wmp/lib/libwmp_*.so, then restarts
makerbase-client.service (the touchscreen UI restarts, ~10 s). uninstall
removes the drop-in and the built libraries and restarts the service.
"""
import glob
import os
import posixpath

from .touchscreen import run, shq

NAME = "preload"
DESCRIPTION = "LD_PRELOAD patches for the touchscreen client: wifi-fix, fan-fix, recovery-fix"
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "client-preload")
DROPIN = "/etc/systemd/system/makerbase-client.service.d/wmp-preload.conf"
SERVICE = "makerbase-client.service"


def sources():
    out = []
    for d in sorted(glob.glob(os.path.join(SRC, "*", ""))):
        cs = glob.glob(os.path.join(d, "*.c"))
        if len(cs) == 1:
            out.append((os.path.basename(os.path.dirname(d)), cs[0]))
    return out


def _home(ctx):
    return "/home/%s/wmp" % ctx.user


def _write_dropin(ctx, c):
    libdir = _home(ctx) + "/lib"
    libs, _, _ = run(c, "ls %s/libwmp_*.so 2>/dev/null" % libdir, stream=False)
    libs = " ".join(sorted(l.strip() for l in libs.splitlines() if l.strip()))
    if not libs:
        run(c, "rm -f %s" % DROPIN, sudo=True, stream=False)
        return ""
    content = "[Service]\nEnvironment=\"LD_PRELOAD=%s\"\n" % libs
    run(c, "mkdir -p %s && printf %%s %s > %s" % (posixpath.dirname(DROPIN), shq(content), DROPIN),
        sudo=True, stream=False)
    return libs


def _restart(ctx, c):
    run(c, "systemctl daemon-reload && systemctl restart %s" % SERVICE, sudo=True, stream=False)
    _, _, rc = run(c, "sleep 4; systemctl is-active %s" % SERVICE, stream=False)
    if rc != 0:
        raise ctx.DeployError("%s is not active after restart" % SERVICE)


def install(ctx):
    c = ctx.ssh()
    sftp = ctx.sftp()
    home = _home(ctx)
    run(c, "mkdir -p %s/src %s/lib" % (home, home), stream=False)
    for name, path in sources():
        rdir = "%s/src/%s" % (home, name)
        run(c, "mkdir -p %s" % rdir, stream=False)
        rsrc = "%s/%s" % (rdir, os.path.basename(path))
        sftp.put(path, rsrc)
        lib = "%s/lib/libwmp_%s.so" % (home, name)
        out, err, rc = run(c, "gcc -shared -fPIC -O2 -Wall -pthread -o %s %s -ldl" % (lib, rsrc), stream=False)
        if rc != 0:
            raise ctx.DeployError("build of %s failed:\n%s%s" % (name, out, err))
        print("built %s" % lib)
    libs = _write_dropin(ctx, c)
    print("drop-in %s: LD_PRELOAD=%s" % (DROPIN, libs))
    _restart(ctx, c)
    status(ctx)


def uninstall(ctx):
    c = ctx.ssh()
    for name, _ in sources():
        run(c, "rm -f %s/lib/libwmp_%s.so" % (_home(ctx), name), stream=False)
    run(c, "rm -f %s" % DROPIN, sudo=True, stream=False)
    _restart(ctx, c)
    print("removed drop-in and built libraries; client restarted without preload")


def status(ctx):
    c = ctx.ssh()
    out, _, _ = run(c, "cat %s 2>/dev/null" % DROPIN, stream=False)
    print("drop-in:  %s" % (out.strip().replace("\n", " ") if out.strip() else "absent"))
    out, _, _ = run(c, "ls %s/lib/libwmp_*.so 2>/dev/null" % _home(ctx), stream=False)
    print("libs:     %s" % (out.strip().replace("\n", " ") or "none"))
    out, _, _ = run(c, "pid=$(pidof client); [ -n \"$pid\" ] && grep -o '/home/[^ ]*libwmp_[^ ]*' /proc/$pid/maps | sort -u",
                    sudo=True, stream=False)
    print("loaded:   %s" % (out.strip().replace("\n", " ") or "none"))
    out, _, _ = run(c, "tail -n 4 /tmp/wmp_wififix.log 2>/dev/null", stream=False)
    if out.strip():
        print("wifi-fix: " + out.strip().replace("\n", "\n          "))

    out, _, _ = run(c, "tail -n 4 /tmp/wmp_fanfix.log 2>/dev/null", stream=False)
    if out.strip():
        print("fan-fix:  " + out.strip().replace("\n", "\n          "))
