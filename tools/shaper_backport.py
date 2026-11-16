#!/usr/bin/env python3
"""Install, remove, or check the input shaper backport.

Replaces six unmodified upstream Klipper files on the printer with the
versions in klipper_backport/input_shaper/. See that directory's README.md.

Usage (run on your computer):
    uv run --with paramiko python tools/shaper_backport.py status
    uv run --with paramiko python tools/shaper_backport.py install
    uv run --with paramiko python tools/shaper_backport.py uninstall

Needs SSH and sudo (the Klipper service is restarted; a FIRMWARE_RESTART does
not reload Python modules or rebuild the C helper). Set WMP_PRINTER, WMP_USER,
and WMP_PASS in .env or your environment.

install refuses to run unless every target file is either the known stock
file or already the backport, the printer is idle, and Klipper is ready.
The C helper is built on the printer, in a staging directory, with the
printer's gcc and the vendor build command before any file is replaced. A
failed build changes nothing. Stock files are kept on the printer in
~/wmp-shaper-backport/. If Klipper does not return to ready after the
restart, the stock files are restored.

tools/deploy.py installs the same files as its "shaper" component.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from local_env import configure_ssh_client, load_local_env, require  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY = os.path.join(REPO, 'klipper_backport', 'input_shaper', 'klippy')
CACHE = os.path.join(REPO, 'utils', '.klippy_cache')
STATE_DIR = 'wmp-shaper-backport'          # relative to the printer user's home
KLIPPY = 'klipper/klippy'
C_SOURCE = 'chelper/kin_shaper.c'
SERVICE = 'klipper.service'
HELPER = 'chelper/c_helper.so'
PYTHON = 'klippy-env/bin/python'
READY_TIMEOUT = 420                        # allows for a C helper rebuild
BUILD_TIMEOUT = 900

# Runs on the printer. Copies the vendor C helper sources to a staging
# directory, substitutes the backport kin_shaper.c, and builds and loads the
# library with the vendor chelper module. An unchanged input set reuses the
# previous build.
BUILD_SCRIPT = """set -e
S=%(stage)s
K=%(chelper)s
rm -rf "$S.new"
mkdir -p "$S.new/chelper"
cp "$K"/*.c "$K"/*.h "$K"/__init__.py "$S.new/chelper/"
cp %(source)s "$S.new/chelper/kin_shaper.c"
key=$(cd "$S.new/chelper" && cat *.c *.h __init__.py | sha256sum | cut -d' ' -f1)
if [ -f "$S/key" ] && [ "$(cat "$S/key")" = "$key" ] \\
        && [ -f "$S/chelper/c_helper.so" ]; then
    rm -rf "$S.new"
    echo reused
    exit 0
fi
rm -rf "$S"
mv "$S.new" "$S"
cd "$S"
%(python)s -c 'import chelper
ffi, lib = chelper.get_ffi()
for name in %(symbols)s:
    getattr(lib, name)'
echo "$key" > "$S/key"
echo built
"""

# sha256 of the stock files with LF line endings (Klipper v0.12.0-276,
# commit ca815f52c). The vendor ships some of them with CRLF endings.
STOCK_SHA256 = {
    'mathutil.py':
        '1f25d3e6e2940999418f488ff3c8655358a826aef276cc5f461ee40602dc56c2',
    'chelper/kin_shaper.c':
        'c13515af5b5bcc6d63180cc729e21788c551058d1d0842fe0b6b1031523ca595',
    'extras/input_shaper.py':
        'e77bb456152765245368767c31c315c1b709e39d94f679473edef6e83f84be25',
    'extras/resonance_tester.py':
        '46f5560f409acdf4e71e8c38729f1521ae138d22e375f40601d821195f48f1c1',
    'extras/shaper_calibrate.py':
        '30f8d96d0654c77c8783b32ef2bdb89adddddd760ec4fef0ba270a72972d9353',
    'extras/shaper_defs.py':
        '59f04ab16a4fb28bd35851e42cb2e408b349df1e7142fafde3bd10da85092e8c',
}
FILES = sorted(STOCK_SHA256)

# Vendor-side interfaces the backport calls. Checked before installation so
# a vendor Klipper rebase is detected instead of failing at runtime.
REQUIRED_SYMBOLS = {
    'toolhead.py': (
        'def note_step_generation_scan_time(', 'def _calc_junction_deviation(',
        'def calc_junction(self, prev_move)', 'self.max_smoothed_v2',
        'def get_last(self)', "'minimum_cruise_ratio'"),
    'chelper/__init__.py': (
        'input_shaper_get_step_generation_window', 'input_shaper_set_sk',
        'input_shaper_set_shaper_params'),
}


class BackportError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalize(data):
    return data.replace(b'\r\n', b'\n')


def overlay_bytes(rel):
    with open(os.path.join(OVERLAY, rel), 'rb') as stream:
        return stream.read()


def classify(rel, data):
    """Return 'backport', 'stock', 'missing', or 'unknown' for remote bytes."""
    if data is None:
        return 'missing'
    if data == overlay_bytes(rel):
        return 'backport'
    if sha256(normalize(data)) == STOCK_SHA256[rel]:
        return 'stock'
    return 'unknown'


def missing_symbols(rel, data):
    text = (data or b'').decode('utf-8', 'replace')
    return [symbol for symbol in REQUIRED_SYMBOLS[rel] if symbol not in text]


class Printer:
    def __init__(self):
        load_local_env()
        self.host = require('WMP_PRINTER')
        self.user = require('WMP_USER')
        self.password = require('WMP_PASS')
        self.home = '/home/%s' % self.user
        self._ssh = self._sftp = None

    def ssh(self):
        if self._ssh is None:
            try:
                import paramiko
            except ImportError:
                sys.exit('needs SSH: run with `uv run --with paramiko python '
                         'tools/shaper_backport.py ...`')
            client = paramiko.SSHClient()
            configure_ssh_client(client)
            client.connect(self.host, username=self.user,
                           password=self.password, timeout=20,
                           allow_agent=False, look_for_keys=False)
            self._ssh = client
        return self._ssh

    def sftp(self):
        if self._sftp is None:
            self._sftp = self.ssh().open_sftp()
        return self._sftp

    def close(self):
        if self._sftp:
            self._sftp.close()
        if self._ssh:
            self._ssh.close()
        self._sftp = self._ssh = None

    def run(self, command, sudo=False, timeout=60):
        if sudo:
            command = "sudo -S -p '' " + command
        stdin, stdout, stderr = self.ssh().exec_command(command,
                                                        timeout=timeout)
        if sudo:
            stdin.write(self.password + '\n')
            stdin.flush()
        out = stdout.read().decode('utf-8', 'replace')
        rc = stdout.channel.recv_exit_status()
        return rc, out, stderr.read().decode('utf-8', 'replace')

    def read(self, path):
        try:
            with self.sftp().open(path, 'rb') as stream:
                return stream.read()
        except IOError:
            return None

    def write(self, path, data):
        staged = '%s.wmp-upload-%d' % (path, os.getpid())
        with self.sftp().open(staged, 'wb') as stream:
            stream.write(data)
        if self.read(staged) != data:
            raise BackportError('Upload readback mismatch: ' + path)
        self.sftp().posix_rename(staged, path)
        if self.read(path) != data:
            raise BackportError('Publication readback mismatch: ' + path)

    def klippy(self, rel):
        return '%s/%s/%s' % (self.home, KLIPPY, rel)

    def state(self, rel=''):
        return '%s/%s/%s' % (self.home, STATE_DIR, rel)

    def moonraker(self, path, post=False, timeout=10):
        request = urllib.request.Request(
            'http://%s:7125%s' % (self.host, path),
            method='POST' if post else 'GET')
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())['result']

    def klippy_state(self):
        try:
            return self.moonraker('/printer/info').get('state')
        except Exception:
            return None

    def klippy_pid(self):
        try:
            return self.moonraker('/printer/info').get('process_id')
        except Exception:
            return None

    def print_state(self):
        result = self.moonraker('/printer/objects/query?print_stats')
        return result['status']['print_stats']['state']


def survey(printer):
    return {rel: classify(rel, printer.read(printer.klippy(rel)))
            for rel in FILES}


def describe(states):
    kinds = set(states.values())
    if kinds == {'backport'}:
        return 'installed'
    if kinds == {'stock'}:
        return 'stock'
    if kinds <= {'stock', 'backport'}:
        return 'partial'
    return 'unknown'


def require_no_live_print(printer):
    """Staging does not require a healthy Klipper configuration.

    Unavailable HTTP is not idle: only an explicitly stopped service is a
    fallback. Actual publication retains its separate restart/readiness policy.
    """
    try:
        printing = printer.print_state()
    except Exception:
        printing = None
    if printing in ('printing', 'paused'):
        raise BackportError('A print is %s; no changes made.' % printing)
    if printing in ('standby', 'complete', 'cancelled', 'error'):
        return
    rc, out, _ = printer.run(
        'systemctl show klipper.service --property=LoadState,ActiveState,MainPID')
    fields = dict(line.split('=', 1) for line in out.splitlines() if '=' in line)
    if (rc == 0 and fields.get('LoadState') == 'loaded'
            and fields.get('ActiveState') in ('inactive', 'failed')
            and fields.get('MainPID') == '0'):
        return
    raise BackportError('Cannot establish no active print for input shaper staging: '
                        'print state=%r; Klipper service is not confirmed stopped' % printing)


def require_idle_ready(printer):
    state = printer.klippy_state()
    if state != 'ready':
        raise BackportError('Klipper state is %r, not ready; resolve that '
                            'first.' % (state,))
    try:
        printing = printer.print_state()
    except Exception as error:
        raise BackportError('Cannot establish that the printer is idle: %s'
                            % (error,))
    if printing in ('printing', 'paused'):
        raise BackportError('A print is %s; no changes made.' % printing)


def restart_and_wait(printer):
    """Restart the Klipper service; True when the new process reaches ready."""
    old_pid = printer.klippy_pid()
    rc, out, err = printer.run('systemctl restart ' + SERVICE, sudo=True,
                               timeout=120)
    if rc != 0:
        raise BackportError('systemctl restart failed: %s' % (err or out))
    print('Klipper service restarted; waiting for ready...')
    deadline = time.monotonic() + READY_TIMEOUT
    ready = failed = 0
    while time.monotonic() < deadline:
        time.sleep(3)
        state = printer.klippy_state()
        pid = printer.klippy_pid()
        if old_pid is not None and pid == old_pid:
            # Moonraker still reports the process that was stopped
            continue
        if state == 'ready':
            ready += 1
            if ready >= 2:
                return True
            continue
        ready = 0
        failed = failed + 1 if state in ('error', 'shutdown') else 0
        if failed >= 3:
            return False
    return False


def helper_is_current(printer):
    """The compiled helper must be newer than the C source it was built from."""
    rc, out, _ = printer.run(
        'stat -c %%Y %s %s' % (printer.klippy('chelper/c_helper.so'),
                               printer.klippy(C_SOURCE)))
    if rc != 0:
        return False
    built, source = [int(v) for v in out.split()[:2]]
    return built >= source


def build_helper(printer):
    """Build c_helper.so with the backport C source in a staging directory."""
    source = printer.state('kin_shaper.c.backport')
    printer.write(source, overlay_bytes(C_SOURCE))
    script = BUILD_SCRIPT % {
        'stage': printer.state('build'),
        'chelper': printer.klippy('chelper'),
        'source': source,
        'python': '%s/%s' % (printer.home, PYTHON),
        'symbols': json.dumps(list(REQUIRED_SYMBOLS['chelper/__init__.py']))}
    printer.write(printer.state('build.sh'), script.encode())
    print('Building the C helper on the printer (about two minutes unless '
          'an identical build exists)...')
    rc, out, err = printer.run('bash ' + printer.state('build.sh'),
                               timeout=BUILD_TIMEOUT)
    if rc != 0:
        raise BackportError('The C helper did not build on the printer; no '
                            'files were replaced.\n%s'
                            % (err or out).strip()[-1500:])


def publish_helper(printer):
    """Install the staged library after the sources, so it is the newest."""
    target = printer.klippy(HELPER)
    rc, out, err = printer.run(
        'cp %s %s.wmp-new && mv -f %s.wmp-new %s'
        % (printer.state('build/' + HELPER), target, target, target))
    if rc != 0:
        raise BackportError('Could not install the built C helper: %s'
                            % (err or out))


def clear_local_cache():
    """Drop utils/.klippy_cache so offline analysis refetches from the printer."""
    if os.path.isdir(CACHE):
        shutil.rmtree(CACHE)


def cmd_status(printer, args):
    states = survey(printer)
    for rel in FILES:
        print('%-28s %s' % (rel, states[rel]))
    overall = describe(states)
    print('Input shaper backport: %s' % overall)
    manifest = printer.read(printer.state('manifest.json'))
    print('Stock copies on printer: %s'
          % ('present' if manifest else 'absent'))
    if overall == 'installed' and not helper_is_current(printer):
        print('WARNING: c_helper.so is older than kin_shaper.c; restart the '
              'Klipper service.')
    return 0 if overall in ('installed', 'stock') else 1


def restore(printer, manifest):
    for rel, entry in sorted(manifest['files'].items()):
        data = printer.read(printer.state(entry['backup']))
        if data is None or sha256(data) != entry['sha256']:
            raise BackportError('Stock copy of %s is missing or altered; '
                                'restore it from the vendor firmware package.'
                                % rel)
        printer.write(printer.klippy(rel), data)
    # Force a rebuild: the restored source is older than the compiled helper.
    rc, out, err = printer.run('touch ' + printer.klippy(C_SOURCE))
    if rc != 0:
        raise BackportError('touch failed: %s' % (err or out))


def check(printer):
    """Verify install preconditions. Returns (file bytes, file states)."""
    require_no_live_print(printer)
    rc, _, _ = printer.run('command -v gcc')
    if rc != 0:
        raise BackportError('gcc is not installed on the printer; the C '
                            'helper cannot be built.')
    for rel in sorted(REQUIRED_SYMBOLS):
        missing = missing_symbols(rel, printer.read(printer.klippy(rel)))
        if missing:
            raise BackportError(
                'Vendor %s lacks %s; this Klipper base is not the one the '
                'backport was written for.' % (rel, ', '.join(missing)))
    current = {rel: printer.read(printer.klippy(rel)) for rel in FILES}
    states = {rel: classify(rel, data) for rel, data in current.items()}
    bad = [rel for rel in FILES if states[rel] not in ('stock', 'backport')]
    if bad:
        raise BackportError('Not the known stock file, refusing to replace: '
                            + ', '.join(bad))
    return current, states


def record_stock(printer, current, states):
    """Keep the stock files on the printer. Returns the manifest."""
    old = printer.read(printer.state('manifest.json'))
    manifest = json.loads(old.decode()) if old else {'files': {}}
    printer.run('mkdir -p ' + printer.state())
    for rel in FILES:
        if states[rel] != 'stock':
            if rel not in manifest['files']:
                raise BackportError('%s is already the backport but no stock '
                                    'copy is recorded.' % rel)
            continue
        digest = sha256(current[rel])
        backup = '%s.%s' % (rel.replace('/', '__'), digest[:12])
        printer.write(printer.state(backup), current[rel])
        manifest['files'][rel] = {'backup': backup, 'sha256': digest}
    manifest['klipper_base'] = 'v0.12.0-276-gca815f52c'
    printer.write(printer.state('manifest.json'),
                  json.dumps(manifest, indent=1, sort_keys=True).encode())
    return manifest


def is_installed(printer, states):
    return describe(states) == 'installed' and helper_is_current(printer)


def prepare(printer):
    """Run every check, keep stock copies and build the helper.

    Replaces no Klipper file. Returns (states, manifest); manifest is None
    when the backport is already installed.
    """
    current, states = check(printer)
    if is_installed(printer, states):
        return states, None
    manifest = record_stock(printer, current, states)
    build_helper(printer)
    return states, manifest


def install(printer, dry_run=False):
    states, manifest = prepare(printer)
    if manifest is None:
        print('Input shaper backport already installed.')
        return 0
    if dry_run:
        print('Preflight passed; stock copies recorded and the C helper '
              'built. No files replaced.')
        return 0
    require_idle_ready(printer)
    for rel in FILES:
        if states[rel] == 'stock':
            printer.write(printer.klippy(rel), overlay_bytes(rel))
            print('replaced %s' % rel)
    publish_helper(printer)
    ok = restart_and_wait(printer) and helper_is_current(printer)
    if ok and describe(survey(printer)) == 'installed':
        clear_local_cache()
        print('Input shaper backport installed; Klipper is ready.')
        print('Existing ei/2hump_ei/3hump_ei settings now use the updated '
              'definitions: recalibrate before relying on them.')
        return 0
    print('Klipper did not reach ready with the backport (state %r); '
          'restoring stock files.' % (printer.klippy_state(),),
          file=sys.stderr)
    restore(printer, manifest)
    if restart_and_wait(printer):
        print('Stock files restored; Klipper is ready.', file=sys.stderr)
    else:
        print('Stock files restored but Klipper is not ready. Check '
              'klippy.log.', file=sys.stderr)
    return 2


def cmd_install(printer, args):
    return install(printer, dry_run=args.dry_run)


def cmd_uninstall(printer, args):
    states = survey(printer)
    if describe(states) == 'stock':
        print('Stock input shaper files already in place.')
        return 0
    if 'unknown' in states.values() or 'missing' in states.values():
        raise BackportError('Target files were changed by something else; '
                            'no changes made.')
    raw = printer.read(printer.state('manifest.json'))
    if raw is None:
        raise BackportError('No stock copies recorded on the printer.')
    state = printer.klippy_state()
    if state == 'ready' and printer.print_state() in ('printing', 'paused'):
        raise BackportError('A print is active; no changes made.')
    restore(printer, json.loads(raw.decode()))
    clear_local_cache()
    if not restart_and_wait(printer):
        print('Stock files restored but Klipper is not ready. Check '
              'klippy.log.', file=sys.stderr)
        return 2
    print('Stock input shaper files restored; Klipper is ready.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    install = sub.add_parser('install')
    install.add_argument('--dry-run', action='store_true',
                         help='run all checks, record stock copies and build '
                              'the C helper, but replace nothing and do not '
                              'restart')
    sub.add_parser('uninstall')
    args = parser.parse_args(argv)
    printer = Printer()
    try:
        handler = {'status': cmd_status, 'install': cmd_install,
                   'uninstall': cmd_uninstall}[args.command]
        return handler(printer, args)
    except BackportError as error:
        print('error: %s' % error, file=sys.stderr)
        return 1
    finally:
        printer.close()


if __name__ == '__main__':
    sys.exit(main())
