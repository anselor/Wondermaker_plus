"""Unified delivery selection, without resealing the historical release."""
import io
import json
from pathlib import Path
import shutil
import tarfile

import pytest
from test_deploy import deploy
import preload_bundle as pb

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path):
    root = tmp_path / 'repo'
    directory = root / pb.CURRENT_BUNDLE
    directory.mkdir(parents=True)
    names = pb.current_source_files(ROOT)
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    # Real AArch64 artifact, still explicitly barred from release activation.
    candidate = ROOT / 'analysis/unified-ui-native/libwmp_unified_screen_candidate.so'
    if not candidate.is_file():
        pytest.skip('native candidate build required')
    artifact = directory / 'screen.so'
    shutil.copyfile(candidate, artifact)
    hashes = {name: pb.digest(root / name) for name in names}
    (directory / 'source-inputs.json').write_text(json.dumps(hashes))
    with tarfile.open(directory / 'source.tar.gz', 'w:gz') as archive:
        for name in names:
            data = (root / name).read_bytes()
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    control = ROOT / 'tests/fixtures/native-screen-control' / pb.BUNDLE / 'bundle.json'
    descriptor = json.loads(control.read_text())
    descriptor.update(source_manifest_sha256=pb.digest(directory / 'source-inputs.json'),
                      source_archive_sha256=pb.digest(directory / 'source.tar.gz'),
                      legacy_c_sha256=pb.digest(root / 'client-preload/openace-compat/wmp_openace_compat.c'))
    descriptor['artifact'] = dict(file='screen.so', sha256=pb.digest(artifact),
                                  size=artifact.stat().st_size, **pb.elf_contract(artifact))
    (directory / 'bundle.json').write_text(json.dumps(descriptor))
    return root, directory


def test_current_package_precedes_historical_and_binds_source_and_backend(package):
    root, _ = package
    legacy = root / pb.BUNDLE
    legacy.mkdir(exist_ok=True, parents=True)
    (legacy / 'bundle.json').write_text('invalid historical descriptor')
    assert pb.bundle_relative(root) == pb.CURRENT_BUNDLE
    bundle = pb.load_bundle(root)
    assert bundle['scope'] == 'packaging-control-only'
    pb.verify_source_binding(root, bundle)
    names = pb.native_source_files(root)
    assert 'klipper_extras/wmp_recovery.py' in names
    assert 'klipper_extras/wmp_recovery_retirement.py' in names
    assert 'config/live/offset_calibrate.cfg' in names
    assert 'client-preload/unified-ui/native/bootstrap.cpp' in names


@pytest.mark.parametrize('missing', ['bundle.json', 'screen.so', 'source-inputs.json', 'source.tar.gz'])
def test_incomplete_current_package_cannot_fall_back(package, missing):
    root, directory = package
    (directory / missing).unlink()
    with pytest.raises((ValueError, OSError)):
        pb.verify_source_binding(root)


@pytest.mark.parametrize('name', ['klipper_extras/wm_material.py', 'config/live/macros.cfg',
                                 'client-preload/unified-ui/native/bootstrap.cpp'])
def test_changed_runtime_or_ui_source_is_rejected(package, name):
    root, _ = package
    (root / name).write_text('changed after packaging')
    with pytest.raises(ValueError, match='source input changed'):
        pb.verify_source_binding(root)


def test_unreviewed_current_package_cannot_activate(package, monkeypatch):
    root, _ = package
    monkeypatch.setattr(pb, 'exact_profile', lambda *args: True)
    monkeypatch.setattr(pb, 'verify_dependencies', lambda *args: pytest.fail('activation reached loader'))
    with pytest.raises(ValueError, match='packaging-control-only'):
        pb.select_delivery(root, 'unused')


def test_remote_preflight_stages_current_package_location(package):
    root, _ = package
    script = pb.preflight_script(root, '/home/test/TM_T1/bin/client')
    compile(script, '<preflight>', 'exec')
    assert pb.CURRENT_BUNDLE + '/bundle.json' in script
    assert 'source delivery unavailable' in script


def test_absent_current_package_keeps_legacy_selection(tmp_path):
    assert pb.bundle_relative(tmp_path) == pb.BUNDLE
    assert pb.load_bundle(tmp_path) is None


@pytest.mark.parametrize('exists', [True, False])
def test_linked_current_package_cannot_redirect_or_downgrade(tmp_path, exists):
    directory = tmp_path / pb.CURRENT_BUNDLE
    directory.parent.mkdir(parents=True)
    target = tmp_path / 'elsewhere'
    if exists:
        target.mkdir()
    directory.symlink_to(target, target_is_directory=True)
    assert pb.bundle_relative(tmp_path) == pb.CURRENT_BUNDLE
    with pytest.raises(ValueError, match='symlink'):
        pb.load_bundle(tmp_path)


def installed_backend(package, tmp_path):
    root, _ = package
    home = tmp_path / 'printer-home'
    extras = home / 'klipper/klippy/extras'
    extras.mkdir(parents=True)
    for name in pb.backend_helper_names(root):
        shutil.copyfile(root / 'klipper_extras' / name, extras / name)
    config = home / 'printer_data/config'
    config.mkdir(parents=True)
    (config / 'printer.cfg').write_text('machine-specific calibration')
    (config / 'wmp_filament_loaded.json').write_text('saved filament state')
    return home, extras


def test_matching_backend_gate_leaves_configuration_and_data_untouched(package, tmp_path):
    root, _ = package
    home, _ = installed_backend(package, tmp_path)
    before = {str(p): p.read_bytes() for p in home.rglob('*') if p.is_file()}
    assert set(pb.verify_backend_helpers(root, home)) == set(pb.backend_helper_names(root))
    assert before == {str(p): p.read_bytes() for p in home.rglob('*') if p.is_file()}


@pytest.mark.parametrize('name', pb.backend_helper_names(ROOT))
@pytest.mark.parametrize('missing', [True, False])
def test_missing_or_changed_installed_helper_refuses_activation(package, tmp_path, name, missing):
    root, _ = package
    home, extras = installed_backend(package, tmp_path)
    if missing:
        (extras / name).unlink()
    else:
        (extras / name).write_text('old version')
    with pytest.raises(ValueError, match='screen/backend mismatch: ' + name):
        pb.verify_backend_helpers(root, home)


@pytest.mark.parametrize("failure", ["disk", "runtime"])
def test_installer_backend_mismatch_preserves_previous_install(package, tmp_path, monkeypatch, failure):
    import contextlib
    import subprocess
    from types import SimpleNamespace
    from components import preload
    root, _ = package
    home, extras = installed_backend(package, tmp_path)
    if failure == 'disk':
        (extras / 'wm_material.py').write_text('old backend')
    else:
        _, config = installed_configuration(package, tmp_path)
        shutil.copytree(config, home/'printer_data/config', dirs_exist_ok=True)
    restarts=[]
    wmp = home / 'wmp'
    (wmp / 'lib').mkdir(parents=True)
    # Main's mandatory guard must be present before this fixture can reach
    # the backend-readiness failure it is intended to exercise.
    (wmp / 'lib/libwmp_head-config-guard.so').write_bytes(b'existing guard fixture')
    old = wmp / 'lib/libwmp_openace-compat.so'
    old.write_bytes(b'previous screen')
    dropin = tmp_path / 'service.conf'
    dropin.write_text('previous service configuration')
    monkeypatch.setattr(preload, 'ROOT', str(root))
    monkeypatch.setattr(preload, '_home', lambda ctx: str(wmp))
    monkeypatch.setattr(preload, 'DROPIN', str(dropin))
    monkeypatch.setattr(preload, 'DEFAULTS_DROPIN', str(tmp_path / 'backend-defaults.conf'))
    monkeypatch.setattr(preload, 'sources', lambda: [('openace-compat', str(root / 'client-preload/openace-compat/wmp_openace_compat.c'))])
    def checked(ctx, client, command, **kwargs):
        if command == 'systemctl stop '+preload.SERVICE:
            assert failure == 'runtime'
            return ''  # Service operations are modeled, never run on the host.
        return subprocess.check_output(['bash', '-c', command], text=True).strip()
    monkeypatch.setattr(preload, '_checked', checked)
    def forbidden(*args, **kwargs):
        pytest.fail('mismatched backend reached publication or restart')
    # Run the real installer staging and backend gate against a local fake
    # printer. Firmware/loader selection is isolated, never loading the ELF.
    def helper(ctx, client, body, **kwargs):
        namespace = dict(vars(pb), select_delivery=lambda *args, **kwargs: True,
                         verify_backend_helpers=lambda stage, unused: pb.verify_backend_helpers(stage, home),
                         verify_backend_config=lambda stage, unused: pb.verify_backend_config(stage, home),
                         recovery_environment=lambda unused: pb.recovery_environment(home),
                         publish_stage=forbidden if failure=='disk' else pb.publish_stage)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(body, namespace)
        return output.getvalue().strip()
    monkeypatch.setattr(preload, '_helper', helper)
    monkeypatch.setattr(preload, '_restart', forbidden if failure=='disk' else lambda *args, **kwargs: restarts.append(True))
    ctx = SimpleNamespace(user='test', ssh=lambda: None,
                          sftp=lambda: SimpleNamespace(put=shutil.copyfile),
                          printing_now=lambda: False, DeployError=deploy.DeployError,
                          moonraker=lambda path: json.dumps({'result': {'status': {}}}))
    error, message = (ValueError, 'screen/backend mismatch') if failure=='disk' else (deploy.DeployError, 'Restarted backend')
    with pytest.raises(error, match=message):
        preload.install(ctx)
    assert old.read_bytes() == b'previous screen'
    assert dropin.read_text() == 'previous service configuration'
    assert len(restarts) == (0 if failure=='disk' else 2)


def installed_configuration(package, tmp_path):
    import configparser
    root, _ = package
    home = tmp_path / 'configured-printer'
    directory = home / 'printer_data/config'
    directory.mkdir(parents=True)
    parser = pb.read_active_config(root/'config/live/printer.cfg',
                                   include_paths=[root/name for name in pb.CONFIG_BASELINES])
    for section in parser.sections():
        if section.startswith('include '):
            parser.remove_section(section)
    if not parser.has_section('wm_material'):
        parser.add_section('wm_material')
    # Real machine-specific values differ from the repository baseline.
    parser.set('tools_calibrate', 'probe_position', '298, 289, 8, 6, 5')
    parser.set('wm_material', 'load_feed_mm', '57')
    with (directory/'macros.cfg').open('w') as stream:
        parser.write(stream)
    (directory/'printer.cfg').write_text('[include macros.cfg]\n[include optional-*.cfg]\n#*# saved calibration\n')
    return home, directory


def test_configuration_gate_preserves_tuning_and_calibration(package, tmp_path):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    before = {p.name:p.read_bytes() for p in directory.iterdir()}
    checked = pb.verify_backend_config(root, home)
    assert 'gcode_macro _WMP_PROBE_CALIBRATE' in checked
    assert 'homing_override' in checked
    assert before == {p.name:p.read_bytes() for p in directory.iterdir()}


def test_later_include_override_cannot_hide_outdated_macro(package, tmp_path):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    with (directory/'printer.cfg').open('a') as stream:
        stream.write('[include overrides.cfg]\n')
    (directory/'overrides.cfg').write_text('[gcode_macro _WMP_PROBE_CALIBRATE]\ngcode: T0\n')
    with pytest.raises(ValueError, match='screen/macro mismatch'):
        pb.verify_backend_config(root, home)


@pytest.mark.parametrize('option,value', [
    ('runout_gcode', 'PAUSE'), ('insert_gcode', 'G28'),
    ('pause_on_runout', 'True'),
])
def test_configuration_gate_rejects_stale_sensor_callbacks(package, tmp_path, option, value):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    with (directory/'printer.cfg').open('a') as stream:
        stream.write('[include overrides.cfg]\n')
    (directory/'overrides.cfg').write_text(
        f'[filament_switch_sensor filament2]\n{option}: {value}\n')
    with pytest.raises(ValueError, match='screen/macro mismatch: filament_switch_sensor filament2'):
        pb.verify_backend_config(root, home)


def test_configuration_gate_accepts_printer_specific_sensor_pin(package, tmp_path):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    with (directory/'printer.cfg').open('a') as stream:
        stream.write('[include overrides.cfg]\n')
    (directory/'overrides.cfg').write_text(
        '[filament_switch_sensor filament2]\nswitch_pin: ^custom:PA1\n')
    assert 'filament_switch_sensor filament2' in pb.verify_backend_config(root, home)


def test_sensor_contract_ignores_only_empty_lines():
    section='filament_switch_sensor filament2'
    source='\n{% if ready %}\n\nPAUSE\n{% endif %}\n'
    compact='{% if ready %}\nPAUSE\n{% endif %}'
    assert pb.config_contract_value(section,'runout_gcode',source)==compact
    assert pb.config_contract_value('delayed_gcode delayed_pause2','gcode',source)==compact
    for changed in (compact.replace('PAUSE','RESUME'),compact.replace('if ready','if true'),compact+'\nG28'):
        assert pb.config_contract_value(section,'runout_gcode',changed)!=compact
    assert pb.config_contract_value('gcode_macro OTHER','gcode',source)!=compact


@pytest.mark.parametrize('case', ['missing_include', 'recursive', 'missing_material', 'changed_baseline'])
def test_configuration_gate_refuses_incomplete_or_invalid_setup(package, tmp_path, case):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    if case == 'missing_include':
        (directory/'printer.cfg').write_text('[include missing.cfg]\n')
    elif case == 'recursive':
        (directory/'printer.cfg').write_text('[include printer.cfg]\n')
    elif case == 'missing_material':
        p=directory/'macros.cfg'
        p.write_text(p.read_text().replace('[wm_material]', '[unrelated]'))
    else:
        (root/'config/live/macros.cfg').write_text('changed package baseline')
    with pytest.raises(ValueError):
        pb.verify_backend_config(root, home)


def test_include_parser_matches_vendor_klipper_order_and_comments(tmp_path):
    import importlib.util
    source=ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/configfile.py'
    if not source.is_file():
        pytest.skip('vendor configuration parser fixture required')
    spec=importlib.util.spec_from_file_location('vendor_config_parity', source)
    vendor=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    printer=tmp_path/'printer.cfg'
    printer.write_text('[gcode_macro TEST]\nvariable_value: 1\ngcode: OLD\n'
                       '[include parts/*.cfg]\n'
                       '[gcode_macro TEST]\nvariable_value: 4\n'
                       '[include optional-*.cfg]\n')
    (tmp_path/'parts').mkdir()
    (tmp_path/'parts/a.cfg').write_text('[gcode_macro TEST] # header\nvariable_value: 2\ngcode:\n  G1 X1 # comment\n  M400\n')
    (tmp_path/'parts/b.cfg').write_text('[gcode_macro TEST]\nvariable_value: 3 ; trailing\n')
    instance=object.__new__(vendor.PrinterConfig)
    instance.printer=None
    expected=instance._build_config_wrapper(printer.read_text(),str(printer)).fileconfig
    actual=pb.read_active_config(printer)
    assert {s:dict(actual.items(s)) for s in actual.sections()} == {s:dict(expected.items(s)) for s in expected.sections()}


def test_baseline_contract_uses_printer_include_order(package, tmp_path):
    root, _ = package
    parser=pb.read_active_config(root/'config/live/printer.cfg',
                                include_paths=[root/name for name in pb.CONFIG_BASELINES])
    # These names intentionally occur in both files; change_macros is later.
    later=pb.read_active_config(root/'config/live/change_macros.cfg')
    earlier=pb.read_active_config(root/'config/live/offset_calibrate.cfg')
    section='gcode_macro SAVE_T_POSITON'
    assert parser.get(section,'gcode') == later.get(section,'gcode')
    assert parser.get(section,'gcode') != earlier.get(section,'gcode')
    home, _ = installed_configuration(package, tmp_path)
    assert section in pb.verify_backend_config(root,home)


def test_explicit_qualification_checks_dependencies_without_promoting_package(package, monkeypatch):
    root, directory = package
    before = (directory / 'bundle.json').read_bytes()
    monkeypatch.setattr(pb, 'exact_profile', lambda *args: True)
    checked = []
    monkeypatch.setattr(pb, 'verify_dependencies', lambda bundle, artifact: checked.append(artifact))
    pb.verify_source_binding(root)
    assert pb.select_delivery(root, 'exact-client', qualify=True)
    assert checked == [directory / 'screen.so']
    assert (directory / 'bundle.json').read_bytes() == before
    assert pb.load_bundle(root)['scope'] == 'packaging-control-only'
    with pytest.raises(ValueError, match='packaging-control-only'):
        pb.select_delivery(root, 'exact-client')


def test_qualification_cannot_fall_back_to_legacy_client(package, monkeypatch):
    root, _ = package
    monkeypatch.setattr(pb, 'exact_profile', lambda *args: False)
    monkeypatch.setattr(pb, 'verify_dependencies', lambda *args: pytest.fail('wrong client reached loader'))
    with pytest.raises(ValueError, match='exact supported client'):
        pb.select_delivery(root, 'wrong-client', qualify=True)


def test_qualification_does_not_bypass_artifact_hash(package, monkeypatch):
    root, directory = package
    (directory / 'screen.so').write_bytes(b'changed artifact')
    monkeypatch.setattr(pb, 'exact_profile', lambda *args: True)
    monkeypatch.setattr(pb, 'verify_dependencies', lambda *args: pytest.fail('changed artifact reached loader'))
    with pytest.raises(ValueError, match='sealed descriptor'):
        pb.select_delivery(root, 'exact-client', qualify=True)


def test_qualification_rejects_missing_bundle_and_implicit_truthy_value(tmp_path, package):
    with pytest.raises(ValueError, match='current packaging-control-only'):
        pb.select_delivery(tmp_path, 'client', qualify=True)
    with pytest.raises(ValueError, match='current screen bundle'):
        pb.preflight_script(tmp_path, 'client', qualify=True)
    root, _ = package
    with pytest.raises(ValueError, match='explicit boolean'):
        pb.select_delivery(root, 'client', qualify='yes')


def test_remote_preflight_qualification_is_explicit_and_keeps_source_check(package):
    root, _ = package
    script = pb.preflight_script(root, '/home/test/client', qualify=True)
    compile(script, '<qualification>', 'exec')
    assert "enabled=select_delivery(temporary,'/home/test/client',qualify=True)" in script
    assert 'native source delivery unavailable' in script
    ordinary = pb.preflight_script(root, '/home/test/client')
    assert "enabled=select_delivery(temporary,'/home/test/client',qualify=False)" in ordinary


def test_qualification_propagates_loader_failure(package, monkeypatch):
    root, _ = package
    monkeypatch.setattr(pb, 'exact_profile', lambda *args: True)
    def incompatible(*args):
        raise ValueError('required symbol missing')
    monkeypatch.setattr(pb, 'verify_dependencies', incompatible)
    with pytest.raises(ValueError, match='required symbol missing'):
        pb.select_delivery(root, 'exact-client', qualify=True)


def test_qualification_remote_preflight_refuses_changed_source(package):
    root, _ = package
    (root / 'klipper_extras/wm_material.py').write_text('changed after sealing')
    script = pb.preflight_script(root, 'exact-client', qualify=True)
    # Model only the remote client identity; execute the actual generated source
    # admission before any loader or installation operation can be reached.
    script = script.replace('\nimport tempfile\nwith tempfile.TemporaryDirectory',
                            '\nexact_profile = lambda *args: True\nimport tempfile\nwith tempfile.TemporaryDirectory')
    with pytest.raises(ValueError, match='native source delivery unavailable:.*source input changed'):
        exec(script, {'__name__': 'qualification_preflight'})


def test_source_manifest_paths_are_portable_to_windows(monkeypatch):
    from pathlib import PureWindowsPath
    expected = pb.current_source_files(ROOT)
    original = type(ROOT).relative_to
    def windows_relative(self, *other):
        return PureWindowsPath(*original(self, *other).parts)
    # Keep real file enumeration/validation; model Windows' relative path
    # representation, which must not leak backslashes into archive identifiers.
    monkeypatch.setattr(type(ROOT), 'relative_to', windows_relative)
    actual = pb.current_source_files(ROOT)
    assert actual == expected
    assert all('\\' not in name for name in actual)


@pytest.mark.parametrize('missing', [1, 2, 3, 4])
def test_config_verifier_accepts_only_optional_absent_sensor_hooks(package, tmp_path, missing):
    root, _ = package
    home, directory = installed_configuration(package, tmp_path)
    parsed = pb.read_active_config(directory/'printer.cfg')
    for section in list(parsed.sections()):
        if section.startswith('include '):
            parsed.remove_section(section)
    for head in range(missing):
        parsed.remove_section('filament_switch_sensor filament%d' % head)
        parsed.remove_section('delayed_gcode delayed_pause%d' % head)
    with (directory/'macros.cfg').open('w') as stream:
        parsed.write(stream)
    checked = pb.verify_backend_config(root, home)
    assert 'homing_override' in checked
    for head in range(missing):
        assert 'filament_switch_sensor filament%d' % head not in checked
        assert 'delayed_gcode delayed_pause%d' % head not in checked
    # A retained feature that explicitly schedules the missing sensor callback
    # is a real dependency. It cannot be waived as an optional sensor omission.
    with (directory/'macros.cfg').open('a') as stream:
        stream.write('\n[gcode_macro CUSTOM_RUNOUT]\ngcode: UPDATE_DELAYED_GCODE ID=delayed_pause0 DURATION=1\n')
    with pytest.raises(ValueError, match='required by retained configuration'):
        pb.verify_backend_config(root, home)
