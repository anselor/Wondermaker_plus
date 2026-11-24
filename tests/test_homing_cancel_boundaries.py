"""Render real homing macros: stop checks must precede Z work, outside G28."""
import configparser
from pathlib import Path
import jinja2

ROOT=Path(__file__).resolve().parents[1]


def render(section,params=None):
    parser=configparser.RawConfigParser();parser.read(ROOT/'config/live/printer.cfg')
    printer={'save_variables':{'variables':{'fail_flag':0,'current_extruder':2}},
             'gcode_macro Z_HOMING':{'z_raise':1},'wmp_recovery':{'z_reference_valid':True},
             'toolhead':{'homed_axes':'xyz'},'extruder':{'target':0},'custom_hall':{'Raw':0},
             'print_stats':{'state':'standby'}}
    source=jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(parser.get(section,'gcode'))
    text=source.render(printer=printer,params=params or {},z_raise=1)
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]


def test_full_home_checks_between_xy_completion_and_z_macro():
    lines=render('homing_override')
    point=lines.index('_WMP_OPERATION_STOP_POINT PHASE=before_z_homing')
    assert lines.index('_WMP_HOME_XY') < point < lines.index('Z_HOMING')
    assert lines[point-1]=='M400'


def test_explicit_z_checks_before_trigger_and_native_home():
    lines=render('homing_override',{'Z':''})
    point=lines.index('_WMP_OPERATION_STOP_POINT PHASE=before_z_homing')
    assert point < lines.index('_LEVELING_TRIGGER_S') < lines.index('G28 Z')


def test_z_macro_checks_before_offset_or_tool_positioning():
    lines=render('gcode_macro Z_HOMING')
    assert lines[0]=='_WMP_OPERATION_STOP_POINT PHASE=before_z_positioning'
    assert lines.index('G90') < lines.index('G28 Z')
