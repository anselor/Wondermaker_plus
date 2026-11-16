"""Validate the deployment set and regress the actual Klipper parsing hazards."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
import validate_klipper_config as validator


def macro(code):
    return '[gcode_macro CHECK]\ngcode:\n' + '\n'.join('    ' + line for line in code.split('\n')) + '\n'


@pytest.mark.parametrize('code,category', [
    ('RESPOND MSG="Runout finished; pausing now"', 'gcode-arguments'),
    ('RESPOND MSG="temperature #3"', 'gcode-arguments'),
    ('RESPOND MSG="multiply * here"', 'gcode-arguments'),
    ('RESPOND MSG="unclosed', 'gcode-arguments'),
    ('SET_PIN PIN=case_light VALUE=“1”', 'punctuation'),
    ('G1 X−1', 'punctuation'),
    ('SET_PIN\u00a0PIN=case_light VALUE=1', 'whitespace'),
    ('test_fan_counter = 0', 'gcode-arguments'),
    ('{% if True %}\nG1 X1', 'jinja-syntax'),
    ('RESPOND MSG={"bad; value"}', 'emitted-delimiter'),
    ('RESPOND MSG={"bad*value"}', 'emitted-delimiter'),
    ('G1 X1\x00', 'character'),
    ('G1 X1\u200b', 'character'),
    ('G1 X1\rG1 Y1', 'character'),
])
def test_unsafe_syntax_is_rejected(code, category):
    errors = validator.validate_text('bad.cfg', macro(code))
    assert category in {error.code for error in errors}
    assert all(error.path == 'bad.cfg' and error.line >= 3 for error in errors)


@pytest.mark.parametrize('code', [
    'G1 X1 ; normal G-code comment',
    '; comment containing "quotes; and symbols #*',
    '# comment containing "quotes; and symbols',
    'RESPOND MSG="Runout finished, pausing now"',
    'RESPOND MSG="Text with Unicode °C and “quotation marks”"',
    '{action_respond_info("Valid; direct Jinja response")}',
    '{action_raise_error("Valid; direct error response")}',
    '{% set factor = 2 * 3 %}\nG1 X{factor}',
    '{% set factor = 2 %}\n{% if factor %}\nG1 X{factor}\n{% endif %}',
    '_TIP_SHAPE_RETRACT {rawparams}',
    '_PARK {park_x} {park_y}',
    'SAVE_VARIABLE VARIABLE=state VALUE="{ {} }"',
    'M118 Display — text',
    'SET_GCODE_VARIABLE MACRO=OTHER VARIABLE=message VALUE=\'"safe words"\'',
])
def test_legal_comments_jinja_and_runtime_arguments_are_allowed(code):
    assert validator.validate_text('good.cfg', macro(code)) == []


def test_all_managed_klipper_configs_pass():
    sources = {str(path): path.read_text() for path in validator.default_paths()}
    assert len(sources) >= 26
    assert validator.validate_sources(sources) == []


def test_option_literals_and_ini_syntax_are_checked():
    assert validator.validate_text('bad.cfg', '[gcode_macro X]\nvariable_x: not a literal\ngcode:\n G1 X1\n')[0].code == 'variable'
    assert validator.validate_text('bad.cfg', '[broken\nfoo: 1\n')[0].code == 'config-syntax'


def test_every_gcode_option_is_checked_with_original_line_numbers():
    text = '[filament_switch_sensor test]\nrunout_gcode:\n    # blanked comment\n    RESPOND MSG="bad; text"\n'
    errors = validator.validate_text('sensor.cfg', text)
    assert any(error.line == 4 and error.code == 'gcode-arguments' for error in errors)
    assert validator.validate_text('good.cfg', '[x]\npress_gcode: SET_PIN PIN=foo VALUE=1\n') == []


def test_multiline_jinja_strings_do_not_crash_validator():
    errors = validator.validate_text('multiline.cfg', macro('RESPOND MSG={"two\nlines"}'))
    assert isinstance(errors, list)


def test_include_resolution_cycles_wildcards_and_shared_fragments():
    sources = {'printer.cfg': '[include parts/a.cfg]\n[include parts/b.cfg]\n[include optional*.cfg]\n',
               'parts/a.cfg': '[include common.cfg]\n',
               'parts/b.cfg': '[include common.cfg]\n', 'parts/common.cfg': '[respond]\n'}
    assert validator.validate_sources(sources) == []
    sources['parts/common.cfg'] = '[include ../printer.cfg]\n'
    assert any(error.code == 'include-cycle' for error in validator.validate_sources(sources))
    sources['parts/common.cfg'] = '[include missing.cfg]\n'
    assert any(error.code == 'include' for error in validator.validate_sources(sources))


def test_bom_and_non_ascii_indentation_are_rejected_but_crlf_is_allowed():
    assert any(error.code == 'character' for error in validator.validate_text('bom.cfg', '\ufeff[respond]\n'))
    assert any(error.code == 'whitespace' for error in validator.validate_text('space.cfg', macro('\u00a0SET_PIN PIN=x VALUE=1')))
    assert validator.validate_text('crlf.cfg', macro('G1 X1').replace('\n', '\r\n')) == []


def test_cli_has_actionable_errors_and_nonzero_exit_status(tmp_path):
    bad = tmp_path / 'bad.cfg'
    bad.write_text(macro('RESPOND MSG="bad; text"'))
    result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_klipper_config.py'), str(bad)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'bad.cfg:3: gcode-arguments' in result.stderr
    bad.write_bytes(b'[respond]\n\xff')
    result = subprocess.run([sys.executable, str(ROOT / 'tools/validate_klipper_config.py'), str(bad)],
                            capture_output=True, text=True)
    assert result.returncode == 1 and ': read:' in result.stderr


def test_direct_config_push_rejects_bad_message_before_backups_or_upload(tmp_path, monkeypatch):
    from utils import config_sync
    from types import SimpleNamespace as NS
    monkeypatch.setattr(config_sync, 'LIVE', str(tmp_path))
    (tmp_path / 'bad.cfg').write_text(macro('RESPOND MSG="bad; text"'))
    monkeypatch.setattr(config_sync, 'changed_files', lambda transport: ([], ['bad.cfg']))
    def no_mutation(*args):
        pytest.fail('Invalid config reached an upload/backup')
    transport = NS(write=no_mutation, copy=no_mutation)
    with pytest.raises(SystemExit, match='gcode-arguments'):
        config_sync.run(transport, NS(mode='push', files=[], yes=True, no_restart=True))


def test_static_delimiter_checks_match_real_stock_klipper_parser():
    vendor = Path(os.environ.get('WMP_VENDOR_ROOT', str(ROOT / 'analysis')))
    source = vendor / 'fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    if not source.exists():
        pytest.skip('local stock gcode parser required')
    spec = importlib.util.spec_from_file_location('stock_gcode', source)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    dispatch = object.__new__(native.GCodeDispatch)
    from types import SimpleNamespace as NS
    outputs = NS(respond_info=lambda *args: None, respond_raw=lambda *args: None)
    for delimiter in ';#*':
        command = f'RESPOND MSG="before{delimiter}after"'
        gcmd = native.GCodeCommand(outputs, 'RESPOND', command, {}, False)
        with pytest.raises(native.CommandError):
            dispatch._get_extended_params(gcmd)
        assert validator.validate_text('check.cfg', macro(command))
    command = 'RESPOND MSG="before, after"'
    gcmd = native.GCodeCommand(outputs, 'RESPOND', command, {}, False)
    assert dispatch._get_extended_params(gcmd).get('MSG') == 'before, after'
