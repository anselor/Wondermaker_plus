"""Component: touchscreen add-on (camera snapshot service, nginx page,
timelapse-camera fixer). Needs SSH and sudo. Uploads device/ and scripts/
to a unique staging directory. Installation uses a journaled file/service/camera
transaction; explicit uninstall retains the legacy removal script.
"""
import os
import posixpath
import sys
import json
import uuid
import time
import codecs
from pathlib import Path
from local_env import require

PASS = os.environ.get("WMP_PASS")
STAGE = "/tmp/wondermaker_plus"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PAYLOAD = ["device", "scripts"]



def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def run(c, cmd, sudo=False, stream=True, timeout=300):
    if sudo:
        password = PASS or require("WMP_PASS")
        cmd = "sudo -S -p '' -- bash -c %s" % shq(cmd)
    deadline = time.monotonic() + timeout
    stdin, out, err = c.exec_command(cmd, timeout=timeout, get_pty=False)
    channel = out.channel
    if sudo:
        stdin.write(password + '\n')
        stdin.flush()
        stdin.channel.shutdown_write()
    # ChannelFile.readline can wait indefinitely on continuing partial output,
    # and recv_exit_status ignores the channel timeout. Drain both streams so
    # stderr cannot fill the SSH window while stdout waits for command exit.
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    chunks, errors = [], []
    while True:
        if time.monotonic() >= deadline:
            channel.close()
            raise TimeoutError(
                "SSH command observation timed out after %ss waiting for output/exit status; "
                "command outcome is unconfirmed and was not retried" % timeout)
        received = False
        if channel.recv_ready():
            text = decoder.decode(channel.recv(32768))
            chunks.append(text)
            if stream:
                sys.stdout.write(text)
                sys.stdout.flush()
            received = True
        if channel.recv_stderr_ready():
            errors.append(channel.recv_stderr(32768))
            received = True
        if (channel.exit_status_ready() and not channel.recv_ready()
                and not channel.recv_stderr_ready()):
            rc = channel.recv_exit_status()
            break
        if not received:
            time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    final = decoder.decode(b"", final=True)
    chunks.append(final)
    if stream and final:
        sys.stdout.write(final)
        sys.stdout.flush()
    body = "".join(chunks)
    tail = b"".join(errors).decode("utf-8", "replace")
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
    stage = STAGE + "-" + uuid.uuid4().hex
    sftp = c.open_sftp()
    mkdirs(sftp, stage)
    n = 0
    for top in PAYLOAD:
        for dirpath, _, files in os.walk(os.path.join(ROOT, top)):
            rel = os.path.relpath(dirpath, ROOT)
            remote_dir = posixpath.join(stage, rel.replace(os.sep, "/"))
            mkdirs(sftp, remote_dir)
            for fn in files:
                if fn.endswith((".pyc", ".swp")):
                    continue
                sftp.put(os.path.join(dirpath, fn),
                         posixpath.join(remote_dir, fn))
                n += 1
    sftp.close()
    run(c, "chmod +x %s/scripts/*.sh" % stage, stream=False)
    print("uploaded %d files to %s" % (n, stage))
    return stage



NAME = "touchscreen"
DESCRIPTION = "Clickable touchscreen in Fluidd and timelapse camera setting"
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None


def preflight(ctx):
    import preflight as checks
    checks.touchscreen(ctx)


def transaction_code(action, source, journal):
    modules = {name: (Path(ROOT)/'tools'/(name+'.py')).read_text(encoding='utf-8')
               for name in ('touchscreen_settings', 'touchscreen_transaction', 'touchscreen_runtime')}
    return """import json, sys, types
for name, source in %r.items():
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name+'.py', 'exec'), module.__dict__)
result = sys.modules['touchscreen_runtime'].execute(%r, %r, %r)
print(json.dumps(result))
""" % (modules, action, source, journal)


def install(ctx):
    import preflight as checks
    stage = upload(ctx.ssh())
    journal = '/opt/wondermaker_plus-transactions/'+uuid.uuid4().hex+'.json'
    print('Touchscreen transaction journal: '+journal)
    receipt = {'kind': 'touchscreen-transaction', 'journal': journal}
    installer = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
    if installer is not None:
        installer.prepare_component(NAME, receipt)
    try:
        result = json.loads(checks.remote(ctx, transaction_code('install', stage, journal), sudo=True, quiet=True))
    except Exception as error:
        raise ctx.DeployError('Touchscreen installation failed or its outcome is unknown; inspect retained journal '+journal+': '+str(error)) from error
    if result.get('state') != 'applied' or result.get('journal') != journal:
        raise ctx.DeployError('Touchscreen activation unconfirmed; inspect '+journal)
    return receipt


def rollback(ctx, receipt):
    import preflight as checks
    if receipt.get('kind') != 'touchscreen-transaction':
        raise ctx.DeployError('Invalid touchscreen rollback receipt')
    result = json.loads(checks.remote(ctx, transaction_code('restore', None, receipt['journal']), sudo=True, quiet=True))
    if result.get('state') != 'restored' or result.get('journal') != receipt['journal']:
        raise ctx.DeployError('Touchscreen restoration unconfirmed; inspect '+receipt['journal'])


def uninstall(ctx):
    c = ctx.ssh()
    stage = upload(c)
    _, _, rc = run(c, "%s/scripts/uninstall.sh" % stage, sudo=True)
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
