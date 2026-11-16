"""Characterize retained vendor defects, not acceptance of managed replacements.

Only the hardcoded home prefix is relocated; the pinned shell logic runs against
disposable files. No printer connection or production configuration is used.
"""
import hashlib
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/scripts'
HASHES = {
    'set_zru_include.sh': 'f11758b37ee9d8490b4cd4be791dae55f4c76c23bd8c6587336cf1523a9829e7',
    'replace_save_config.sh': '8b2b9345448b48cee724fb0f659ca7fbd1070a2e699d90f1bcd2c831c1019f63',
    'restore_factory_settings.sh': '302b745b63e24ea1096e7fdcc70cb85b4d0aa5581528dedd68fff482e35ce5e9',
}


@pytest.fixture
def machine(tmp_path):
    home = tmp_path / 'home'
    for name in ('printer_data/config', 'TM_T1/other', 'TM_T1/factory_settings'):
        (home / name).mkdir(parents=True)
    config = home / 'printer_data/config'
    (config / 'printer.cfg').write_text('# original calibrated machine\n')
    other = home / 'TM_T1/other'
    (other / 'current_thr_number.txt').write_text('4\n')
    for count in range(1, 5):
        (other / f'printer{count}.cfg').write_text(f'# factory template {count}\n')
    return home


def run_vendor(home, name, *args):
    source = SCRIPTS / name
    if not source.is_file():
        pytest.skip('retained firmware source required')
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == HASHES[name]
    # The scripts contain unquoted paths: reject shell metacharacters in fixture
    # paths instead of silently changing the vendor quoting/command semantics.
    assert all(c.isalnum() or c in '/_-' for c in str(home))
    script = raw.decode().replace('/home/t13dp', str(home))
    assert '/home/t13dp' not in script
    return subprocess.run(['bash', '-c', script, name, *args], cwd=home,
                          capture_output=True, text=True, timeout=10)


def test_missing_saved_input_already_overwrote_live_printer(machine):
    result = run_vendor(machine, 'replace_save_config.sh')
    assert result.returncode == 1
    assert (machine / 'printer_data/config/printer.cfg').read_text() == '# factory template 4\n'


def test_invalid_count_silently_selects_four_head_template(machine):
    (machine / 'TM_T1/other/current_thr_number.txt').write_text('9\n')
    config = machine / 'printer_data/config'
    (config / 'save_config.cfg').write_text('#*# [extruder]\n#*# pid_Kp = 23\n')
    result = run_vendor(machine, 'replace_save_config.sh')
    assert result.returncode == 0
    assert (config / 'printer.cfg').read_text().startswith('# factory template 4\n')
    assert not (config / 'save_config.cfg').exists()


def test_topology_shrink_deletes_removed_head_calibration_source(machine):
    (machine / 'TM_T1/other/current_thr_number.txt').write_text('2\n')
    config = machine / 'printer_data/config'
    (config / 'save_config.cfg').write_text(
        '#*# [extruder1]\n#*# pid_Kp = 21\n'
        '#*# [extruder2]\n#*# pid_Kp = 22\n'
        '#*# [extruder3]\n#*# pid_Kp = 23\n'
        '#*# [probe]\n#*# z_offset = 1.25\n')
    result = run_vendor(machine, 'replace_save_config.sh')
    assert result.returncode == 0
    live = (config / 'printer.cfg').read_text()
    assert 'pid_Kp = 21' in live and 'z_offset = 1.25' in live
    assert 'pid_Kp = 22' not in live and 'pid_Kp = 23' not in live
    assert not (config / 'save_config.cfg').exists()


def test_factory_restore_continues_after_missing_input_without_rollback(machine):
    config = machine / 'printer_data/config'
    factory = machine / 'TM_T1/factory_settings'
    (config / 'moonraker.conf').write_text('original moonraker\n')
    (config / 'macros.cfg').write_text('managed fast wipe\n')
    (factory / 'macros.cfg').write_text('factory wipe\n')
    # Last copy succeeds, hiding earlier failures in the shell exit status.
    (factory / 'wm_zru_thr3.cfg').write_text('factory identity\n')
    result = run_vendor(machine, 'restore_factory_settings.sh')
    assert result.returncode == 0
    assert 'cannot stat' in result.stderr
    assert (config / 'moonraker.conf').read_text() == 'original moonraker\n'
    assert (config / 'macros.cfg').read_text() == 'factory wipe\n'
    assert not list(config.glob('*.bak'))


@pytest.mark.parametrize('enabled', ['0', '1'])
def test_model_writer_preserves_managed_config_and_calibration(machine, enabled):
    # Qualify the WM+ compatibility boundary, not chamber hardware behavior.
    original = (ROOT / 'config/live/printer.cfg').read_text()
    assert original.count('[include zru-s.cfg]') == 1
    assert '[include wm_material*.cfg]' in original
    calibration = '\n#*# [extruder3]\n#*# control = pid\n#*# pid_Kp = 23.125\n'
    original += calibration
    path = machine / 'printer_data/config/printer.cfg'
    path.write_text(original)
    expected = original.replace('[include zru-s.cfg]', '# [include zru-s.cfg]') if enabled == '0' else original
    result = run_vendor(machine, 'set_zru_include.sh', enabled)
    assert result.returncode == 0, result.stderr
    assert path.read_text() == expected
    # Repeated startup and the reverse selection must retain every other byte.
    assert run_vendor(machine, 'set_zru_include.sh', enabled).returncode == 0
    assert path.read_text() == expected
    assert run_vendor(machine, 'set_zru_include.sh', '1').returncode == 0
    assert path.read_text() == original
