"""Read-only installation checks; compilation uses disposable remote temp files."""
import ast
import configparser
import fnmatch
import json
import sys
import shlex
from pathlib import Path
import posixpath
import re
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'utils'))
from config_sync import excluded, body_of  # noqa: E402


def remote(ctx, code, sudo=False, python=None):
    """Send code via stdin, never upload it to an installed location."""
    command = ('sudo -S -p "" -- ' if sudo else '') + shlex.quote(python or 'python3') + ' -'
    stdin, stdout, stderr = ctx.ssh().exec_command(command, timeout=120)
    if sudo:
        stdin.write(ctx.password + '\n')
        stdin.flush()
    stdin.write(code)
    stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    rc = stdout.channel.recv_exit_status()
    if rc:
        raise ctx.DeployError(error.strip() or output.strip() or 'remote validation failed')
    if output.strip():
        print(output.strip())
    return output


def require_paths(ctx, directories=(), files=(), commands=(), sudo=False):
    payload = json.dumps(dict(directories=list(directories), files=list(files), commands=list(commands)))
    remote(ctx, r'''import os, shutil
p = %s
for path in p['directories']:
    if not os.path.isdir(path) or not os.access(path, os.W_OK | os.X_OK):
        raise SystemExit('missing or unwritable directory: ' + path)
for path in p['files']:
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        raise SystemExit('missing or unreadable file: ' + path)
for command in p['commands']:
    if not shutil.which(command):
        raise SystemExit('required command not found: ' + command)
''' % payload, sudo=sudo)


def local_python(path):
    ast.parse(Path(path).read_text(), filename=str(path))


def config_plan(ctx):
    """Validate includes against the configuration that this invocation will leave."""
    listing = json.loads(ctx.moonraker('/server/files/list?root=config'))['result']
    names = {item['path'] for item in listing}
    live = ROOT / 'config/live'
    # Match config_sync ownership/exclusion rules rather than pushing machine IDs.
    managed = {p.name: p.read_text() for p in live.iterdir() if p.is_file() and not excluded(p.name)}
    targets = set(ctx.files) if ctx.files else set(managed)
    unknown = targets - managed.keys()
    if unknown:
        raise ctx.DeployError('Unknown or printer-owned configuration files; choose files from config/live that can be uploaded: ' + ', '.join(sorted(unknown)))
    cache = {}
    if ctx.files:
        unchanged = []
        for name in sorted(targets & names):
            current = ctx.moonraker('/server/files/config/' + quote(name, safe='/'))
            cache[name] = current
            if body_of(current.encode()) == body_of(managed[name].encode()):
                unchanged.append(name)
        if unchanged:
            raise ctx.DeployError('Selected configuration files are unchanged; omit them from --files: ' + ', '.join(unchanged))
    def read(name):
        if name in targets:
            return managed[name]
        if name not in cache:
            cache[name] = ctx.moonraker('/server/files/config/' + quote(name, safe='/'))
        return cache[name]
    available = names | targets
    if 'printer.cfg' not in available:
        raise ctx.DeployError('printer.cfg is missing; restore the printer configuration before retrying')
    visited, texts = set(), {}
    def visit(name):
        if name in visited:
            return
        visited.add(name)
        text = body_of(read(name).encode()).decode()
        texts[name] = text
        parser = configparser.RawConfigParser(strict=False)
        parser.read_string(text, source=name)
        for include in re.findall(r'^\s*\[include\s+([^\]]+)\]', text, re.M):
            pattern = posixpath.normpath(posixpath.join(posixpath.dirname(name), include.strip()))
            matches = sorted(n for n in available if fnmatch.fnmatchcase(n, pattern))
            if not matches and not any(c in pattern for c in '*?['):
                raise ctx.DeployError('%s includes missing file %s' % (name, pattern))
            for match in matches:
                visit(match)
    visit('printer.cfg')
    active = '\n'.join(texts.values())
    # Validate uploaded files even when they are not currently included.
    for name in sorted(targets):
        if name.endswith(('.cfg', '.conf')):
            visit(name)
        elif name == '.prettierrc':
            json.loads(read(name))
    # A partial macro-only install must not introduce references to an unloaded extra.
    if 'printer.wmp_recovery' in active and not re.search(r'^\s*\[wmp_recovery\]', active, re.M):
        raise ctx.DeployError('Configuration lacks [wmp_recovery], required by these macros. Include printer.cfg in the update.')
    return texts, active


def config(ctx):
    texts, active = config_plan(ctx)
    needs_recovery = bool(re.search(r'^\s*\[wmp_recovery\]', active, re.M))
    if ctx.config_only:
        # HTTP cannot inspect Klipper source files. Require the running API contract.
        if needs_recovery:
            result = json.loads(ctx.moonraker('/printer/objects/query?wmp_recovery'))['result']['status']
            status = result.get('wmp_recovery', {})
            if not {'z_reference_valid', 'homing'} <= status.keys():
                raise ctx.DeployError('--config-only requires a loaded wmp_recovery helper. Run tools/deploy.py install config with SSH first.')
        if '[collision_detect]' in active:
            # The vendor detector has no get_status(), so Moonraker does not
            # include it in /printer/objects/list. Use the loaded config instead.
            result = json.loads(ctx.moonraker('/printer/objects/query?configfile'))['result']['status']
            settings = result.get('configfile', {}).get('settings', {})
            if 'collision_detect' not in settings:
                raise ctx.DeployError('This configuration requires the 1.1.13 collision detector. Install vendor firmware 1.1.13 first.')
        return
    ctx.ssh()
    ctx.sftp()
    extra = ROOT / 'klipper_extras/wmp_recovery.py'
    local_python(extra)
    home = '/home/' + ctx.user
    required = ['collision_detect.py', 'tools_calibrate_core.py'] if '[collision_detect]' in active else []
    require_paths(ctx, directories=[home + '/klipper/klippy/extras', home + '/printer_data/config'],
                  files=[home + '/klipper/klippy/extras/' + n for n in required], commands=['python3'])
    # Parse with the printer's Python and Jinja, without loading modules or moving hardware.
    remote(ctx, r'''import ast, jinja2, re
ast.parse(%r)
env = jinja2.Environment('{%%', '%%}', '{', '}')
for name, text in %r.items():
    for section in re.split(r'(?m)^\[', text)[1:]:
        body = section.split(']', 1)[1]
        match = re.search(r'(?m)^gcode\s*[:=]\s*\n([\s\S]*)', body)
        if match:
            env.parse('\n'.join(line.split('#', 1)[0] for line in match[1].splitlines()))
''' % (extra.read_text(), texts), python=home + '/klippy-env/bin/python')


def material(ctx):
    ctx.ssh()
    ctx.sftp()
    home = '/home/' + ctx.user
    local_python(ROOT / 'klipper_extras/wm_material.py')
    configparser.RawConfigParser(strict=False).read_string((ROOT / 'klipper_extras/wm_material.cfg').read_text())
    require_paths(ctx, directories=[home + '/klipper/klippy/extras', home + '/printer_data/config'], commands=['python3'])
    remote(ctx, 'import ast; ast.parse(%r)' % (ROOT / 'klipper_extras/wm_material.py').read_text(),
           python=home + '/klippy-env/bin/python')


def touchscreen(ctx):
    ctx.ssh()
    ctx.sftp()
    for name in ('device/wmp_screen.py', 'device/nginx-screen.conf', 'device/wmp-screen.service',
                 'device/wmp-timelapse-camera.service', 'device/timelapse-camera-fix.sh',
                 'scripts/install.sh'):
        (ROOT / name).read_text()
    if not (ROOT / 'device/www/index.html').is_file():
        raise ctx.DeployError('Touchscreen web page is missing; restore device/www/index.html in the repository')
    require_paths(ctx, directories=['/opt', '/etc/systemd/system'],
                  files=['/etc/nginx/sites-available/fluidd'],
                  commands=['python3', 'nginx', 'systemctl', 'curl', 'ffmpeg'], sudo=True)
    json.loads(ctx.moonraker('/server/webcams/list'))['result']['webcams']
    remote(ctx, r'''import os, subprocess, ast, socket, tempfile, shutil
ast.parse(%r)
for path, mode in [('/dev/fb0', os.R_OK), ('/dev/input/event0', os.W_OK)]:
    if not os.access(path, mode):
        raise SystemExit('required screen device unavailable: ' + path)
with open('/sys/class/graphics/fb0/virtual_size') as f:
    size = tuple(map(int, f.read().strip().split(',')))
with open('/sys/class/graphics/fb0/bits_per_pixel') as f:
    bpp = int(f.read())
if size[0] != 800 or size[1] < 480 or bpp != 32:
    raise SystemExit('Unsupported screen format: %%r pixels, %%s bits per pixel; expected width 800, height at least 480, and 32 bits per pixel' %% (size, bpp))
result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
                         '-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', '800x480',
                         '-i', 'pipe:0', '-an', '-c:v', 'mjpeg', '-q:v', '3',
                         '-f', 'image2pipe', 'pipe:1'],
                        input=bytes(800 * 480 * 4), capture_output=True, timeout=20)
if result.returncode or not result.stdout.startswith(b'\xff\xd8'):
    raise SystemExit('ffmpeg could not produce a JPEG screenshot; check ffmpeg support on the printer')
site = open('/etc/nginx/sites-available/fluidd').read()
if not site.rstrip().endswith('}'):
    raise SystemExit('The nginx site file has an unexpected layout; review it before adding the screen include')
# Validate the prospective nginx configuration in a disposable copy, including
# the new fragment. Do not edit/reload the running web server during preflight.
with tempfile.TemporaryDirectory(prefix='wmp-nginx-preflight-') as directory:
    tree = os.path.join(directory, 'nginx')
    shutil.copytree('/etc/nginx', tree)
    fragment = os.path.join(directory, 'nginx-screen.conf')
    open(fragment, 'w').write(%r)
    include = '    include ' + fragment + '; # wondermaker_plus\n'
    if '# wondermaker_plus' not in site:
        index = site.rstrip().rfind('}')
        site = site[:index] + include + site[index:]
    for base, _, files in os.walk(tree):
        for name in files:
            path = os.path.join(base, name)
            original = '/etc/nginx/' + os.path.relpath(path, tree)
            try:
                text = site if os.path.realpath(original) == '/etc/nginx/sites-available/fluidd' else open(path).read()
            except UnicodeError:
                continue
            text = text.replace('/etc/nginx/', tree + '/').replace('/opt/wondermaker_plus/nginx-screen.conf', fragment)
            open(path, 'w').write(text)
    # Keep nginx's compiled prefix: relative load_module paths refer to the
    # installed modules, not our disposable configuration directory. Includes
    # above already point at the prospective configuration copy.
    result = subprocess.run(['nginx', '-t', '-c', tree + '/nginx.conf'], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('nginx rejected the proposed screen configuration: ' + result.stderr[-4000:])
active = subprocess.run(['systemctl', 'is-active', '--quiet', 'wmp-screen.service']).returncode == 0
if not active:
    with socket.socket() as sock:
        try: sock.bind(('127.0.0.1', 8975))
        except OSError: raise SystemExit('Screen port 8975 is already in use; identify the listening service before retrying')
''' % ((ROOT / 'device/wmp_screen.py').read_text(), (ROOT / 'device/nginx-screen.conf').read_text()), sudo=True)


def preload(ctx):
    from components.preload import sources
    ctx.ssh()
    ctx.sftp()
    payload = []
    for name, path in sources():
        source = Path(path).read_text()
        # Use the actual C identify() guard, not a parallel firmware-version list.
        call = 'unsigned char code[CODE_SIZE]; const struct profile *p = identify(f, code);' if name == 'wifi-fix' else 'const struct profile *p = identify(f);'
        harness = source + '\nint main(int argc, char **argv) { if(argc != 2) return 2; FILE *f=fopen(argv[1], "rb"); if(!f) return 2; ' + call + ' fclose(f); if(!p) return 3; puts(p->version); return 0; }\n'
        payload.append((name, source, harness))
    if not payload:
        raise ctx.DeployError('No touchscreen patch sources found under client-preload; check the repository files')
    require_paths(ctx, directories=['/etc/systemd/system'], commands=['gcc', 'systemctl'], sudo=True)
    client = '/home/' + ctx.user + '/TM_T1/bin/client'
    require_paths(ctx, directories=['/home/' + ctx.user], files=[client], commands=['gcc', 'python3'])
    remote(ctx, r'''import os, subprocess, tempfile
client = %r
if not os.path.isfile(client):
    raise SystemExit('vendor client not found: ' + client)
with tempfile.TemporaryDirectory(prefix='wmp-preflight-') as directory:
    for name, source, harness in %r:
        binary = os.path.join(directory, 'preflight-check')
        flags = ['gcc', '-x', 'c', '-O2', '-Wall', '-pthread', '-', '-ldl', '-o']
        for text, output, shared in [(source, os.path.join(directory, 'check.so'), ['-shared', '-fPIC']), (harness, binary, [])]:
            result = subprocess.run(flags + [output] + shared, input=text, text=True, capture_output=True)
            if result.returncode:
                raise SystemExit(name + ' build failed: ' + result.stderr[-4000:])
        result = subprocess.run([binary, client], text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(name + ': unsupported or modified client; no components installed')
        print(name + ': supports installed client ' + result.stdout.strip())
''' % (client, payload))
