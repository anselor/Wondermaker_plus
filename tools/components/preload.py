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
import uuid

from .touchscreen import run, shq

NAME = "preload"
DESCRIPTION = "Touchscreen fixes and head-configuration protection"
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
        raise ctx.DeployError('No preload libraries found; screen restart blocked')
    if libdir + '/libwmp_head-config-guard.so' not in libs.split():
        raise ctx.DeployError('The head-config-guard library is missing; screen restart blocked')
    content = ("[Service]\nEnvironment=\"LD_PRELOAD=%s\"\n"
               "Environment=\"WMP_REQUIRE_HEAD_CONFIG_GUARD=1\"\n") % libs
    temporary = DROPIN + '.wmp-upload-' + uuid.uuid4().hex
    _, err, rc = run(c, "mkdir -p %s && printf %%s %s > %s && chmod 0644 %s && mv -f -- %s %s" %
                    (shq(posixpath.dirname(DROPIN)), shq(content), shq(temporary),
                     shq(temporary), shq(temporary), shq(DROPIN)), sudo=True, stream=False)
    if rc:
        raise ctx.DeployError('Could not install the preload override; screen restart blocked: ' + err)
    return libs


def _restart(ctx, c):
    _, err, rc = run(c, "systemctl daemon-reload && systemctl restart %s" % SERVICE,
                    sudo=True, stream=False)
    if rc:
        raise ctx.DeployError('Could not restart %s: %s' % (SERVICE, err))
    _, _, rc = run(c, "sleep 4; systemctl is-active %s" % SERVICE, stream=False)
    if rc != 0:
        raise ctx.DeployError("%s did not start. Check its service log before printing." % SERVICE)


def preflight(ctx):
    import preflight as checks
    checks.preload(ctx)


def verify_guard(ctx):
    import preflight as checks
    from verify_head_guard import guard_profiles
    source = os.path.join(ROOT, 'client-preload/head-config-guard/wmp_head_config_guard.c')
    with open(source) as stream:
        profiles = guard_profiles(stream.read())
    with open(os.path.join(ROOT, 'tools/verify_head_guard.py')) as stream:
        verifier = stream.read()
    checks.remote(ctx, verifier + '\nresult = wait_for_guard(%r, %r)\n'
                  'print("Head guard verified for screen pid %%s (client %%s)" %% '
                  '(result["pid"], result["version"]))\n' %
                  ('/home/' + ctx.user, profiles), sudo=True)


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
        # Never truncate a .so that the running client may still have mapped.
        temporary = lib + '.wmp-upload-' + uuid.uuid4().hex
        out, err, rc = run(c, "gcc -shared -fPIC -O2 -Wall -pthread -o %s %s -ldl" %
                           (shq(temporary), shq(rsrc)), stream=False)
        if rc != 0:
            run(c, "rm -f -- %s" % shq(temporary), stream=False)
            raise ctx.DeployError("build of %s failed:\n%s%s" % (name, out, err))
        _, err, rc = run(c, "mv -f -- %s %s" % (shq(temporary), shq(lib)), stream=False)
        if rc != 0:
            raise ctx.DeployError("Could not activate built library %s: %s" % (name, err))
        print("built %s" % lib)
    libs = _write_dropin(ctx, c)
    print("Screen service override %s: LD_PRELOAD=%s" % (DROPIN, libs))
    if ctx.printing_now():
        raise ctx.DeployError('A print started while building preloads; screen restart blocked')
    _restart(ctx, c)
    verify_guard(ctx)
    ctx.wait_for_backend()
    status(ctx)


def uninstall(ctx):
    c = ctx.ssh()
    for name, _ in sources():
        run(c, "rm -f %s/lib/libwmp_%s.so" % (_home(ctx), name), stream=False)
    run(c, "rm -f %s" % DROPIN, sudo=True, stream=False)
    _restart(ctx, c)
    print("Removed the WM+ screen service override and patch libraries; restarted the screen.")


def status(ctx):
    c = ctx.ssh()
    out, _, _ = run(c, "cat %s 2>/dev/null" % DROPIN, stream=False)
    print("Service override: %s" % (out.strip().replace("\n", " ") if out.strip() else "absent"))
    out, _, _ = run(c, "ls %s/lib/libwmp_*.so 2>/dev/null" % _home(ctx), stream=False)
    print("Library files:    %s" % (out.strip().replace("\n", " ") or "none"))
    pid, _, _ = run(c, "pidof client", stream=False)
    pid = pid.strip().split()[0] if pid.strip() else ""
    print("Screen process:   %s" % ("pid " + pid if pid else "not running"))
    out, _, _ = run(c, "[ -n %s ] && grep -o '/home/[^ ]*libwmp_[^ ]*' /proc/%s/maps | sort -u" %
                    (shq(pid), shq(pid)), sudo=True, stream=False)
    print("Loaded libraries: %s" % (out.strip().replace("\n", " ") or "none"))
    for label, path in (("head-config-guard", "/tmp/wmp_head-config-guard.log"),
                        ("case-light", "/tmp/wmp_case-light.log"),
                        ("wifi-fix", "/tmp/wmp_wififix.log"),
                        ("fan-fix", "/tmp/wmp_fanfix.log"),
                        ("recovery-fix", "/tmp/wmp_recoveryfix.log"),
                        ("openace-compat", "/tmp/wmp_openace_compat.log")):
        if pid:
            command = "grep -F %s %s 2>/dev/null | tail -n 1" % (shq("[pid %s]" % pid), path)
            out, _, _ = run(c, command, stream=False)
        else:
            out = ""
        result = out.strip() or "no log entry for the running screen process; patch application is unconfirmed"
        print(("%-14s" % (label + ":")) + result)
