"""Preflight validates prerequisites without touching installed components."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS

import pytest
from test_deploy import deploy
import preflight

ROOT = Path(__file__).resolve().parents[1]


def config_context(files, targets=(), config_only=False, objects=(), recovery=None, collision=False):
    def api(path):
        if path.startswith('/server/files/list'):
            return json.dumps({'result': [{'path': name} for name in files]})
        if path.startswith('/server/files/config/'):
            return files[path.removeprefix('/server/files/config/')]
        if path == '/printer/objects/list':
            return json.dumps({'result': {'objects': objects}})
        if path == '/printer/objects/query?configfile':
            return json.dumps({'result': {'status': {'configfile': {'settings': {'collision_detect': {}} if collision else {}}}}})
        if path.startswith('/printer/objects/query'):
            return json.dumps({'result': {'status': {'wmp_recovery': recovery or {}}}})
        raise AssertionError(path)
    return NS(files=list(targets), config_only=config_only, moonraker=api, DeployError=deploy.DeployError)


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


def test_http_config_requires_collision_module_before_upload(monkeypatch, tmp_path):
    local_config(monkeypatch, tmp_path, {'printer.cfg': '[collision_detect]\n'})
    with pytest.raises(deploy.DeployError, match='1.1.13'):
        preflight.config(config_context({}, config_only=True))


def test_every_generated_remote_script_has_valid_python_syntax(monkeypatch):
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
        result = subprocess.run(['python3', '-c', code], capture_output=True, text=True)
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
