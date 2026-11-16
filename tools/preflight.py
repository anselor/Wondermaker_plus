"""Read-only installation checks; compilation uses disposable remote temp files."""
import ast
import base64
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


def remote(ctx, code, sudo=False, python=None, quiet=False):
    """Send code via stdin, never upload it to an installed location."""
    # Python 3.9's stdin tokenizer can split a UTF-8 character in a very long
    # source line (our embedded stock configuration contains such lines).
    # Keep transport lines short and ASCII; compile the original UTF-8 bytes
    # only after the complete payload has arrived.
    encoded = base64.b64encode(code.encode('utf-8')).decode('ascii')
    transport = "import base64\nexec(compile(base64.b64decode(\n" + ''.join(
        repr(encoded[offset:offset + 76]) + '\n'
        for offset in range(0, max(1, len(encoded)), 76)
    ) + "), '<stdin>', 'exec'))\n"
    command = ('sudo -S -p "" -- ' if sudo else '') + shlex.quote(python or 'python3') + ' -'
    stdin, stdout, stderr = ctx.ssh().exec_command(command, timeout=120)
    if sudo:
        stdin.write(ctx.password + '\n')
        stdin.flush()
    stdin.write(transport)
    stdin.flush()
    stdin.channel.shutdown_write()
    output = stdout.read().decode('utf-8', 'replace')
    error = stderr.read().decode('utf-8', 'replace')
    rc = stdout.channel.recv_exit_status()
    if rc:
        raise ctx.DeployError(error.strip() or output.strip() or 'remote validation failed')
    if output.strip() and not quiet:
        print(output.strip())
    return output


def require_paths(ctx, directories=(), files=(), commands=(), sudo=False, writable_files=()):
    payload = json.dumps(dict(directories=list(directories), files=list(files),
                              commands=list(commands), writable_files=list(writable_files)))
    remote(ctx, r'''import os, shutil
p = %s
for path in p['directories']:
    if not os.path.isdir(path) or not os.access(path, os.W_OK | os.X_OK):
        raise SystemExit('missing or unwritable directory: ' + path)
for path in p['files']:
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        raise SystemExit('missing or unreadable file: ' + path)
for path in p['writable_files']:
    if not os.path.isfile(path) or not os.access(path, os.R_OK | os.W_OK):
        raise SystemExit('missing or inaccessible file (read/write required): ' + path)
for command in p['commands']:
    if not shutil.which(command):
        raise SystemExit('required command not found: ' + command)
''' % payload, sudo=sudo)


def local_python(path):
    ast.parse(Path(path).read_text(encoding='utf-8'), filename=str(path))


def validate_klipper(ctx, texts):
    try:
        from validate_klipper_config import validate_sources
    except ImportError as error:
        raise ctx.DeployError('Klipper config validation requires jinja2. Add --with jinja2 to the uv run command.') from error
    errors = validate_sources(texts)
    if errors:
        raise ctx.DeployError('Klipper config validation failed:\n' + '\n'.join(map(str, errors)))


def standalone_owner(ctx):
    """Refuse unsupported managers on disk or in the running Klipper config."""
    import preload_bundle
    if preload_bundle.bundle_relative(ROOT) != preload_bundle.CURRENT_BUNDLE:
        return
    try:
        loaded = json.loads(ctx.moonraker('/printer/objects/query?configfile'))['result']['status']['configfile']['settings']
    except (OSError, ValueError, KeyError, TypeError) as error:
        # A stopped/config-error backend may have no loaded objects. Still inspect
        # disk configuration below; unavailable HTTP alone never implies ownership.
        try:
            state = json.loads(ctx.moonraker('/printer/info'))['result']['state']
        except (OSError, ValueError, KeyError, TypeError):
            state = None
        stopped = False
        if state not in ('error', 'shutdown'):
            try:
                service = ctx.backend_service_status()
                stopped = (service.get('LoadState') == 'loaded'
                           and service.get('ActiveState') in ('inactive', 'failed')
                           and service.get('MainPID') == '0')
            except (OSError, ValueError, AttributeError, ctx.DeployError):
                pass
        if state not in ('error', 'shutdown') and not stopped:
            raise ctx.DeployError('Running filament owner is unavailable; verify Klipper is stopped before repair') from error
        loaded = {}
    if not isinstance(loaded, dict):
        raise ctx.DeployError('Cannot verify the running filament owner')
    owners = set(loaded) & {'openace', 'AFC'}
    ctx.ssh()
    path = '/home/' + ctx.user + '/printer_data/config/printer.cfg'
    script = Path(preload_bundle.__file__).read_text(encoding='utf-8') + '\nprint(json.dumps(read_active_config(Path(%r)).sections()))\n' % path
    sections = json.loads(remote(ctx, script, quiet=True))
    if not isinstance(sections, list) or not all(isinstance(s, str) for s in sections):
        raise ctx.DeployError('Cannot verify the configured filament owner')
    owners.update(set(sections) & {'openace', 'AFC'})
    if owners:
        raise ctx.DeployError('This screen release supports standalone WM+ only; active '
                              + ', '.join(sorted(owners))
                              + ' is unsupported. Disable the manager and restart Klipper before installing.')


def config_plan(ctx):
    """Validate includes against the configuration that this invocation will leave."""
    import preload_bundle
    if preload_bundle.bundle_relative(ROOT) == preload_bundle.CURRENT_BUNDLE:
        if ctx.config_only or ctx.files:
            raise ctx.DeployError('The unified screen installer preserves configuration through SSH; --config-only and --files are not supported for this package.')
        preload_bundle.verify_source_binding(ROOT)
        standalone_owner(ctx)
        import reconcile_screen_config
        ctx.ssh()
        directory = '/home/' + ctx.user + '/printer_data/config'
        result = json.loads(remote(ctx, reconcile_screen_config.remote_script(ROOT, directory), quiet=True))
        ctx.screen_config_plan = result['plan']
        print('Reviewed configuration preservation: %d file changes' % len(result['plan']['changes']))
        for warning in result['plan'].get('warnings', []):
            print('Configuration note: ' + warning)
        texts = result['texts']
        # Validate the behavior we publish, not untouched factory/custom macros.
        validate_klipper(ctx, {reconcile_screen_config.FILENAME:
                               texts[reconcile_screen_config.FILENAME]})
        return texts, '\n'.join(texts.values())
    listing = json.loads(ctx.moonraker('/server/files/list?root=config'))['result']
    names = {item['path'] for item in listing}
    live = ROOT / 'config/live'
    # Match config_sync ownership/exclusion rules rather than pushing machine IDs.
    managed = {p.name: p.read_text(encoding='utf-8') for p in live.iterdir() if p.is_file() and not excluded(p.name)}
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
    if '_WMP_CASE_LIGHT_' in active and not re.search(r'^\s*\[wmp_case_light\]', active, re.M):
        raise ctx.DeployError('Configuration lacks [wmp_case_light], required by the light macros. Include case_light.cfg in the update.')
    validate_klipper(ctx, texts)
    return texts, active


def config(ctx):
    texts, active = config_plan(ctx)
    needs_recovery = bool(re.search(r'^\s*\[wmp_recovery\]', active, re.M))
    needs_light = bool(re.search(r'^\s*\[wmp_case_light\]', active, re.M))
    if ctx.config_only:
        # HTTP cannot inspect Klipper source files. Require the running API contract.
        if needs_recovery:
            result = json.loads(ctx.moonraker('/printer/objects/query?wmp_recovery'))['result']['status']
            status = result.get('wmp_recovery', {})
            if not {'z_reference_valid', 'homing'} <= status.keys():
                raise ctx.DeployError('--config-only requires a loaded wmp_recovery helper. Run tools/deploy.py install config with SSH first.')
        if needs_light:
            result = json.loads(ctx.moonraker('/printer/objects/query?wmp_case_light'))['result']['status']
            light = result.get('wmp_case_light', {})
            if light.get('policy_version') != 2:
                raise ctx.DeployError('--config-only requires a loaded wmp_case_light helper. Run tools/deploy.py install config with SSH first.')
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
    extras = [ROOT / 'klipper_extras/wmp_identification.py',
              ROOT / 'klipper_extras/wmp_recovery.py']
    if needs_light:
        extras.append(ROOT / 'klipper_extras/wmp_case_light.py')
    for extra in extras:
        local_python(extra)
    home = '/home/' + ctx.user
    required = ['collision_detect.py', 'tools_calibrate_core.py'] if '[collision_detect]' in active else []
    required_files = [home + '/klipper/klippy/extras/' + n for n in required]
    if needs_light:
        required_files += [home + '/printer_data/config/tmt1.ini',
                           '/sys/class/backlight/backlight/brightness',
                           '/sys/class/gpio/gpio76/value']
        if 'preload' not in getattr(ctx, 'installing_components', set()):
            required_files.append(home + '/wmp/lib/libwmp_case-light.so')
    require_paths(ctx, directories=[home + '/klipper/klippy/extras', home + '/printer_data/config'],
                  files=required_files, commands=['python3'],
                  writable_files=['/sys/class/gpio/gpio76/value']
                  if needs_light and 'preload' not in getattr(ctx, 'installing_components', set()) else [])
    # Extract actual config options, rather than treating the rest of a section
    # (including subsequent settings and comments) as executable Jinja.
    from validate_klipper_config import options
    templates = [(name, section, option, line, source)
                 for name, text in texts.items()
                 for section, option, line, source in options(text)
                 if option == 'gcode' or option.endswith('_gcode')]
    # Use the printer's Python/Jinja without importing extras or moving hardware.
    remote(ctx, r'''import ast, jinja2
for source in %r:
    ast.parse(source)
env = jinja2.Environment('{%%', '%%}', '{', '}')
for name, section, option, line, source in %r:
    try:
        env.parse(source)
    except jinja2.TemplateSyntaxError as error:
        raise SystemExit('%%s:%%d: [%%s] %%s: %%s' %% (
            name, line + error.lineno - 1, section, option, error.message))
''' % ([extra.read_text(encoding='utf-8') for extra in extras], templates), python=home + '/klippy-env/bin/python')



def material(ctx):
    ctx.ssh()
    ctx.sftp()
    home = '/home/' + ctx.user
    from components.material import HELPERS
    sources = {name: ROOT / 'klipper_extras' / name for name in HELPERS}
    for source in sources.values():
        local_python(source)
    validate_klipper(ctx, {str(ROOT / 'klipper_extras/wm_material.cfg'):
                           (ROOT / 'klipper_extras/wm_material.cfg').read_text(encoding='utf-8')})
    configparser.RawConfigParser(strict=False).read_string((ROOT / 'klipper_extras/wm_material.cfg').read_text(encoding='utf-8'))
    require_paths(ctx, directories=[home + '/klipper/klippy/extras', home + '/printer_data/config'], commands=['python3'])
    # Parse every shipped helper with Klipper's interpreter, without importing
    # modules or touching running printer objects. Host Python may be newer.
    payload = {name: path.read_text(encoding='utf-8') for name, path in sources.items()}
    remote(ctx, 'import ast\nfor name, source in %r.items():\n    ast.parse(source, filename=name)\n' % payload,
           python=home + '/klippy-env/bin/python')


def touchscreen(ctx):
    ctx.ssh()
    ctx.sftp()
    for name in ('device/wmp_screen.py', 'device/nginx-screen.conf', 'device/wmp-screen.service',
                 'device/wmp-timelapse-camera.service', 'device/timelapse-camera-fix.sh',
                 'scripts/install.sh'):
        (ROOT / name).read_text(encoding='utf-8')
    for name in ('touchscreen_settings', 'touchscreen_transaction', 'touchscreen_runtime'):
        local_python(ROOT / 'tools' / (name+'.py'))
    if not (ROOT / 'device/www/index.html').is_file():
        raise ctx.DeployError('Touchscreen web page is missing; restore device/www/index.html in the repository')
    require_paths(ctx, directories=['/opt', '/etc/systemd/system'],
                  files=['/etc/nginx/sites-available/fluidd'],
                  commands=['python3', 'nginx', 'systemctl', 'curl', 'ffmpeg'], sudo=True)
    import touchscreen_settings
    def camera_read(method, path, params):
        assert method == 'GET' and not params
        try:
            return json.loads(ctx.moonraker(path))['result']
        except ctx.DeployError as error:
            raise OSError(str(error)) from error
    camera_plan = touchscreen_settings.prepare(camera_read)
    if camera_plan.get('selection_note'):
        print(camera_plan['selection_note'])
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
''' % ((ROOT / 'device/wmp_screen.py').read_text(encoding='utf-8'), (ROOT / 'device/nginx-screen.conf').read_text(encoding='utf-8')), sudo=True)


def preload(ctx):
    from components.preload import sources, screen_bundle, screen_preflight
    try:screen_bundle()  # Verify package integrity without loading its native code.
    except (ValueError,OSError) as error:raise ctx.DeployError('invalid screen bundle: '+str(error)) from error
    standalone_owner(ctx)
    ctx.ssh()
    ctx.sftp()
    payload = []
    for name, path in sources():
        source = Path(path).read_text(encoding='utf-8')
        # Use the actual C identify() guard, not a parallel firmware-version list.
        call = 'unsigned char code[CODE_SIZE]; const struct profile *p = identify(f, code);' if name == 'wifi-fix' else 'const struct profile *p = identify(f);'
        harness = source + '\nint main(int argc, char **argv) { if(argc != 2) return 2; FILE *f=fopen(argv[1], "rb"); if(!f) return 2; ' + call + ' fclose(f); if(!p) return 3; puts(p->version); return 0; }\n'
        payload.append((name, source, harness))
    if not any(name == 'head-config-guard' for name, _, _ in payload):
        raise ctx.DeployError('The head-config-guard source is required for preload installation; restore client-preload/head-config-guard before retrying')
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
    screen_preflight(ctx)
