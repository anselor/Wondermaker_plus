"""Preflight validates prerequisites without touching installed components."""
import json
import io
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest
from test_deploy import deploy
import preflight

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('interpreter', [sys.executable, shutil.which('python3.9')])
@pytest.mark.parametrize('sudo', [False, True])
def test_remote_transports_long_utf8_source_without_stdin_tokenizer_failure(interpreter, sudo):
    if interpreter is None:
        pytest.skip('Python 3.9 is not installed')
    source = 'value = ' + repr('文件' * 60000) + '\nprint(len(value))\n'
    stdin, stdout, stderr = io.StringIO(), io.BytesIO(), io.BytesIO()
    result = {}
    password = 'pássword'

    def finish():
        sent = stdin.getvalue()
        if sudo:
            assert sent.startswith(password + '\n')
            sent = sent[len(password) + 1:]
        assert sent.isascii()
        assert max(map(len, sent.splitlines())) <= 80
        completed = subprocess.run([interpreter, '-'], input=sent.encode('ascii'),
                                   capture_output=True)
        result['rc'] = completed.returncode
        stdout.write(completed.stdout)
        stderr.write(completed.stderr)
        stdout.seek(0)
        stderr.seek(0)

    stdin.channel = NS(shutdown_write=finish)
    stdout.channel = NS(recv_exit_status=lambda: result['rc'])

    def execute(command, timeout):
        assert command.endswith(' -')
        assert command.startswith('sudo -S -p "" -- ') == sudo
        assert timeout == 120
        return stdin, stdout, stderr

    ctx = NS(ssh=lambda: NS(exec_command=execute), password=password,
             DeployError=deploy.DeployError)
    assert preflight.remote(ctx, source, sudo=sudo, quiet=True) == '120000\n'


def config_context(files, targets=(), config_only=False, objects=(), recovery=None, collision=False, light=None):
    def api(path):
        if path.startswith('/server/files/list'):
            return json.dumps({'result': [{'path': name} for name in files]})
        if path.startswith('/server/files/config/'):
            return files[path.removeprefix('/server/files/config/')]
        if path == '/printer/objects/list':
            return json.dumps({'result': {'objects': objects}})
        if path == '/printer/objects/query?configfile':
            return json.dumps({'result': {'status': {'configfile': {'settings': {'collision_detect': {}} if collision else {}}}}})
        if path == '/printer/objects/query?wmp_case_light':
            return json.dumps({'result': {'status': {'wmp_case_light': light or {}}}})
        if path.startswith('/printer/objects/query'):
            return json.dumps({'result': {'status': {'wmp_recovery': recovery or {}}}})
        raise AssertionError(path)
    return NS(files=list(targets), config_only=config_only, moonraker=api, DeployError=deploy.DeployError)


def historical_package(monkeypatch):
    """Exercise the installer path used when no current screen package exists."""
    import preload_bundle
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.BUNDLE)


def local_config(monkeypatch, tmp_path, files):
    directory = tmp_path / 'config/live'
    directory.mkdir(parents=True)
    for name, text in files.items():
        (directory / name).write_text(text)
    monkeypatch.setattr(preflight, 'ROOT', tmp_path)


def test_partial_macro_update_requires_recovery_section(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'macros.cfg': '[gcode_macro T0]\ngcode:\n    {% if printer.wmp_recovery.z_reference_valid %}G28{% endif %}\n'})
    ctx = config_context({'printer.cfg': '[include macros.cfg]\n', 'macros.cfg': ''}, ['macros.cfg'])
    with pytest.raises(deploy.DeployError, match='lacks.*wmp_recovery'):
        preflight.config_plan(ctx)


@pytest.mark.parametrize('config_only', [False, True])
def test_invalid_message_blocks_config_before_upload(monkeypatch, tmp_path, config_only):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[include macros.cfg]\n',
        'macros.cfg': '[gcode_macro CHECK]\ngcode:\n    RESPOND MSG="finished; pausing"\n'})
    ctx = config_context({}, config_only=config_only)
    with pytest.raises(deploy.DeployError, match='gcode-arguments'):
        preflight.config(ctx)


def test_missing_include_blocks_before_install(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[include missing.cfg]\n'})
    with pytest.raises(deploy.DeployError, match='missing file'):
        preflight.config_plan(config_context({}))


def test_machine_config_and_optional_third_party_includes_resolve(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[include wm_zru_mcu.cfg]\n[include openace*.cfg]\n'})
    texts, active = preflight.config_plan(config_context({'wm_zru_mcu.cfg': '[mcu]\ncanbus_uuid: printer-specific\n'}))
    assert 'wm_zru_mcu.cfg' in texts
    assert 'printer-specific' in active


def test_unincluded_recovery_section_cannot_satisfy_active_macros(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[include macros.cfg]\n',
                                      'macros.cfg': '[gcode_macro T0]\ngcode:\n    {printer.wmp_recovery.z_reference_valid}\n',
                                      'unused.cfg': '[wmp_recovery]\n'})
    with pytest.raises(deploy.DeployError, match='lacks.*wmp_recovery'):
        preflight.config_plan(config_context({}))


def test_http_config_only_requires_running_extra(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[wmp_recovery]\n'})
    ctx = config_context({}, config_only=True)
    with pytest.raises(deploy.DeployError, match='loaded wmp_recovery'):
        preflight.config(ctx)
    ctx = config_context({}, config_only=True, recovery={'z_reference_valid': False, 'homing': False})
    preflight.config(ctx)


def test_http_light_install_requires_loaded_helper(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[wmp_case_light]\n'})
    with pytest.raises(deploy.DeployError, match='loaded wmp_case_light'):
        preflight.config(config_context({}, config_only=True))
    with pytest.raises(deploy.DeployError, match='loaded wmp_case_light'):
        preflight.config(config_context({}, config_only=True,
                                       light={'value': 1, 'available': True}))
    # Availability and loading are distinct; the screen may initialize later.
    preflight.config(config_context({}, config_only=True,
                                    light={'value': None, 'available': False, 'policy_version': 2}))


def test_partial_light_macros_require_active_helper(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'macros.cfg':
        '[gcode_macro CASE_LIGHT_TOGGLE]\ngcode:\n    _WMP_CASE_LIGHT_TOGGLE\n'})
    ctx = config_context({'printer.cfg': '[include macros.cfg]\n', 'macros.cfg': ''}, ['macros.cfg'])
    with pytest.raises(deploy.DeployError, match='lacks.*wmp_case_light'):
        preflight.config_plan(ctx)


def test_light_preflight_checks_gpio_access_without_changing_it(monkeypatch):
    paths, scripts = [], []
    monkeypatch.setattr(preflight, 'config_plan', lambda ctx: (
        {'printer.cfg': '[wmp_case_light]\n'}, '[wmp_case_light]\n'))
    monkeypatch.setattr(preflight, 'require_paths', lambda ctx, **kw: paths.append(kw))
    monkeypatch.setattr(preflight, 'remote', lambda ctx, code, **kw: scripts.append(code))
    ctx = NS(config_only=False, user='test', ssh=lambda: None, sftp=lambda: None)
    preflight.config(ctx)
    assert paths[0]['writable_files'] == ['/sys/class/gpio/gpio76/value']
    assert 'CaseLight' in scripts[0]  # remote syntax-check covers the helper too


def test_http_config_requires_collision_module_before_upload(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[collision_detect]\n'})
    with pytest.raises(deploy.DeployError, match='1.1.13'):
        preflight.config(config_context({}, config_only=True))


def test_every_generated_remote_script_has_valid_python_syntax(monkeypatch):
    historical_package(monkeypatch)
    from components import preload
    # Current delivery tests execute the bundle scripts separately. This test
    # covers component prerequisite scripts without relying on a historical bundle.
    monkeypatch.setattr(preload, 'screen_bundle', lambda: None)
    monkeypatch.setattr(preload, 'screen_preflight', lambda ctx: None)
    scripts = []
    def capture(ctx, code, sudo=False, python=None):
        compile(code, '<remote preflight>', 'exec')
        scripts.append((code, sudo))
        if 'import ast, jinja2' in code:
            assert python == '/home/test/klippy-env/bin/python'
        return ''
    monkeypatch.setattr(preflight, 'remote', capture)
    monkeypatch.setattr(preflight, 'config_plan', lambda ctx: ({'printer.cfg': '[wmp_recovery]\n'}, '[wmp_recovery]\n'))
    ctx = NS(config_only=False, user='test', ssh=lambda: None, sftp=lambda: None,
             moonraker=lambda path: json.dumps({'result': {'webcams': []}}))
    for check in (preflight.config, preflight.material, preflight.touchscreen, preflight.preload):
        check(ctx)
    assert any(sudo for _, sudo in scripts)
    assert any('TemporaryDirectory' in code for code, _ in scripts)


@pytest.mark.parametrize('modified', [False, True])
def test_native_preflight_uses_real_c_guards(monkeypatch, tmp_path, modified):
    historical_package(monkeypatch)
    # This harness emulates only the old C identify port on the local CPU.
    # Bundle selection/dependency checks have separate real-ELF packaging tests.
    from components import preload
    monkeypatch.setattr(preload, 'screen_bundle', lambda: None)
    monkeypatch.setattr(preload, 'screen_preflight', lambda ctx: None)
    elf = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists() or not shutil.which('gcc'):
        pytest.skip('local vendor ELF and gcc required')
    if modified:
        changed = tmp_path / 'changed-client'
        shutil.copyfile(elf, changed)
        with changed.open('r+b') as file:
            file.seek(0x61a9a8 - 0x400000)
            byte = file.read(1)
            file.seek(-1, 1)
            file.write(bytes([byte[0] ^ 1]))
        elf = changed
    monkeypatch.setattr(preflight, 'require_paths', lambda *args, **kwargs: None)
    def run_locally(ctx, code, sudo=False):
        code = code.replace("'/home/test/TM_T1/bin/client'", repr(str(elf)))
        result = subprocess.run(['python3', '-'], input=code, capture_output=True, text=True)
        if result.returncode:
            raise deploy.DeployError(result.stderr)
        return result.stdout
    monkeypatch.setattr(preflight, 'remote', run_locally)
    ctx = NS(user='test', ssh=lambda: None, sftp=lambda: None, DeployError=deploy.DeployError)
    if modified:
        with pytest.raises(deploy.DeployError, match='unsupported or modified client'):
            preflight.preload(ctx)
    else:
        preflight.preload(ctx)


def test_actual_live_configuration_passes_syntax_preflight(monkeypatch):
    historical_package(monkeypatch)
    files = {p.name: p.read_text() for p in (ROOT / 'config/live').iterdir() if p.is_file()}
    files['timelapse.cfg'] = '[timelapse]\n'
    ctx = config_context(files)
    ctx.user = 'test'
    ctx.ssh = lambda: None
    ctx.sftp = lambda: None
    monkeypatch.setattr(preflight, 'require_paths', lambda *args, **kwargs: None)
    monkeypatch.setattr(preflight, 'remote', lambda ctx, code, **kwargs: exec(code, {}))
    preflight.config(ctx)


def test_unchanged_file_selection_blocks_before_extra_install(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[wmp_recovery]\n'})
    ctx = config_context({'printer.cfg': '[wmp_recovery]\n'}, targets=['printer.cfg'])
    with pytest.raises(deploy.DeployError, match='unchanged'):
        preflight.config_plan(ctx)


def test_http_collision_check_uses_loaded_config_not_status_objects(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[collision_detect]\n'})
    # The real detector intentionally has no status object; it is still loaded.
    preflight.config(config_context({}, config_only=True, objects=(), collision=True))


@pytest.mark.parametrize('broken', deploy.REGISTRY['material'].HELPERS)
@pytest.mark.parametrize('missing', [True, False])
def test_material_preflight_checks_all_helpers_before_remote_work(monkeypatch, tmp_path, broken, missing):
    directory = tmp_path / 'klipper_extras'
    directory.mkdir()
    for name in deploy.REGISTRY['material'].HELPERS:
        if missing and name == broken:
            continue
        (directory / name).write_text('invalid python !' if name == broken else 'value = 1\n')
    monkeypatch.setattr(preflight, 'ROOT', tmp_path)
    monkeypatch.setattr(preflight, 'remote', lambda *a, **kw: pytest.fail('remote work before validating sources'))
    ctx = NS(user='test', ssh=lambda: None, sftp=lambda: None)
    with pytest.raises(FileNotFoundError if missing else SyntaxError):
        preflight.material(ctx)


def test_material_preflight_parses_helpers_with_klipper_interpreter(monkeypatch):
    scripts = []
    monkeypatch.setattr(preflight, 'require_paths', lambda *a, **kw: None)
    def capture(ctx, code, python=None):
        scripts.append((code, python))
        # Execute the emitted validation rather than merely inspect strings.
        exec(compile(code, '<material preflight>', 'exec'), {})
    monkeypatch.setattr(preflight, 'remote', capture)
    ctx = NS(user='test', ssh=lambda: None, sftp=lambda: None)
    preflight.material(ctx)
    assert len(scripts) == 1
    code, interpreter = scripts[0]
    assert interpreter == '/home/test/klippy-env/bin/python'
    for name in deploy.REGISTRY['material'].HELPERS:
        assert repr((ROOT / 'klipper_extras' / name).read_text()) in code


@pytest.mark.parametrize('disk,loaded', [(['openace'], {}), (['AFC'], {}), ([], {'openace': {}}), ([], {'AFC': {}})])
def test_standalone_owner_refuses_disk_or_running_manager(monkeypatch, disk, loaded):
    import preload_bundle
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(preflight, 'remote', lambda *args, **kwargs: json.dumps(disk))
    ctx = NS(user='test', ssh=lambda: None, DeployError=deploy.DeployError,
             moonraker=lambda path: json.dumps({'result': {'status': {'configfile': {'settings': loaded}}}}))
    with pytest.raises(deploy.DeployError, match='standalone WM.*unsupported'):
        preflight.standalone_owner(ctx)


def test_standalone_owner_accepts_unrelated_configuration(monkeypatch):
    import preload_bundle
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(preflight, 'remote', lambda *args, **kwargs: json.dumps(['wm_material', 'gcode_macro AFC_STATUS']))
    ctx = NS(user='test', ssh=lambda: None, DeployError=deploy.DeployError,
             moonraker=lambda path: json.dumps({'result': {'status': {'configfile': {'settings': {'wm_material': {}}}}}}))
    preflight.standalone_owner(ctx)


@pytest.mark.parametrize('entry', ['config_plan', 'preload'])
def test_unified_install_routes_check_owner_before_publication(monkeypatch, entry):
    import preload_bundle
    from components import preload
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(preload_bundle, 'verify_source_binding', lambda root: None)
    monkeypatch.setattr(preload, 'screen_bundle', lambda: {})
    def refuse(ctx):
        raise deploy.DeployError('owner admission reached')
    monkeypatch.setattr(preflight, 'standalone_owner', refuse)
    ctx = NS(config_only=False, files=[], DeployError=deploy.DeployError)
    with pytest.raises(deploy.DeployError, match='owner admission reached'):
        getattr(preflight, entry)(ctx)


def test_remote_template_validation_uses_config_option_boundaries(monkeypatch):
    historical_package(monkeypatch)
    files = {p.name: p.read_text() for p in (ROOT / 'config/live').iterdir() if p.is_file()}
    files['timelapse.cfg'] = '''[gcode_macro USER_MACRO]
gcode:
    M118 ready
    ; a config comment containing {} is not a Jinja expression
variable_settings: {}
'''
    ctx = config_context(files)
    ctx.user = 'test'
    ctx.ssh = lambda: None
    ctx.sftp = lambda: None
    monkeypatch.setattr(preflight, 'require_paths', lambda *args, **kwargs: None)
    monkeypatch.setattr(preflight, 'remote', lambda ctx, code, **kwargs: exec(code, {}))
    preflight.config(ctx)


@pytest.mark.parametrize('state,service,allowed', [
    ('error', {}, True), ('shutdown', {}, True),
    (None, {'LoadState': 'loaded', 'ActiveState': 'inactive', 'MainPID': '0'}, True),
    (None, {'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '12'}, False),
    ('ready', {}, False)])
def test_owner_preflight_repair_uses_disk_only_when_backend_stopped(monkeypatch, state, service, allowed):
    import preload_bundle
    monkeypatch.setattr(preload_bundle, 'bundle_relative', lambda root: preload_bundle.CURRENT_BUNDLE)
    sections = ['wm_material']
    monkeypatch.setattr(preflight, 'remote', lambda *args, **kwargs: json.dumps(sections))
    def request(path):
        if path == '/printer/info' and state is not None:
            return json.dumps({'result': {'state': state}})
        raise OSError('No loaded configuration available')
    ctx = NS(user='test', ssh=lambda: None, DeployError=deploy.DeployError,
             moonraker=request, backend_service_status=lambda: service)
    if not allowed:
        with pytest.raises(deploy.DeployError, match='owner is unavailable'):
            preflight.standalone_owner(ctx)
        return
    preflight.standalone_owner(ctx)
    sections.append('openace')
    with pytest.raises(deploy.DeployError, match='standalone WM.*unsupported'):
        preflight.standalone_owner(ctx)
