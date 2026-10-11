"""Calibration safety integration and optional checks of the local vendor payload."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_config_macros import templates

ROOT = Path(__file__).resolve().parents[1]
EXTRAS = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras'


def vendor_module(name):
    path = EXTRAS / (name + '.py')
    if not path.exists():
        pytest.skip('local vendor 1.1.13 payload not present')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('directory', ['stock', 'live'])
@pytest.mark.parametrize('tool', [0, 2])
def test_calibration_guards_surround_probing_and_keep_live_clearance(directory, tool):
    printer = {'save_variables': {'variables': {'probe_position': [299, 290, 8.5, 6.9, 5.8]}}}
    script = templates(ROOT / 'config' / directory)['CALIBRATE_TOOL_OFFSET'].render(
        printer=printer, params={'T': tool}, action_respond_info=lambda *args: '')
    commands = [line.strip() for line in script.splitlines() if line.strip()]
    probe_command = 'TOOL_LOCATE_SENSOR' if tool == 0 else 'TOOL_CALIBRATE_TOOL_OFFSET'
    assert commands.index('COLLISION_DETECT_DISABLE') < commands.index(f'T{tool}')
    assert commands.index('G0 Y290 F9600') < commands.index('M400')
    threshold = next(c for c in commands if c.startswith('SET_COLLISION_THRESHOLD '))
    assert 'THRESHOLD=12.0' in threshold and 'ACTION=shutdown' in threshold
    assert commands.index('M400') < commands.index(threshold) < commands.index('COLLISION_DETECT_ENABLE')
    assert commands.index('COLLISION_DETECT_ENABLE') < commands.index(probe_command)
    assert commands.index(probe_command) < len(commands) - 2
    assert commands[-2:] == ['COLLISION_DETECT_DISABLE', 'G0 Y250 F9600']
    if directory == 'live':
        assert commands[0] == '_WMP_CALIBRATION_CLEARANCE'
        assert commands[commands.index('G1 X150 Y135 F9600') - 1] == '_WMP_CALIBRATION_CLEARANCE'


def test_vendor_collision_trigger_requires_consecutive_impacts_and_disables_sensor():
    module = vendor_module('collision_detect')
    callbacks, shutdowns = [], []
    batch = NS(client_cbs=[], add_client=lambda cb: batch.client_cbs.append(cb),
               _stop=lambda: callbacks.append('stopped'))
    reactor = NS(monotonic=lambda: 10.0, register_callback=lambda cb: callbacks.append(cb))
    gcode = NS(register_command=lambda *args: None)
    printer = NS(lookup_object=lambda name, default=None: {'gcode': gcode, 'lis2dw': NS(batch_bulk=batch)}.get(name, default),
                 get_reactor=lambda: reactor, register_event_handler=lambda *args: None,
                 invoke_shutdown=shutdowns.append)
    config = NS(get_printer=lambda: printer, getfloat=lambda name, default, **kw: default,
                getint=lambda name, default, **kw: default, get=lambda name, default: default)
    detector = module.load_config(config)
    detector._handle_ready()
    assert not detector.is_monitoring and batch.client_cbs == []
    detector.cmd_enable()
    reactor.monotonic = lambda: 10.3
    # Magnitudes 0,20,20: an isolated impact does not trigger.
    detector._handle_sensor_batch({'data': [(0, 0, 0, z) for z in (0, 20000, 20000)]})
    assert callbacks == []
    # Magnitudes 0,20 now produce two consecutive differences above 15.
    detector._handle_sensor_batch({'data': [(0, 0, 0, z) for z in (0, 20000)]})
    assert len(callbacks) == 1 and callable(callbacks[0])
    callbacks[0](10.3)
    assert len(shutdowns) == 1
    assert not detector.is_monitoring and batch.client_cbs == []
    assert callbacks[-1] == 'stopped'


@pytest.mark.parametrize('command', ['cmd_TOOL_LOCATE_SENSOR', 'cmd_TOOL_CALIBRATE_TOOL_OFFSET'])
def test_vendor_failed_calibration_releases_collision_monitor(command):
    module = vendor_module('tools_calibrate_core')
    obj = module.ToolsCalibrate.__new__(module.ToolsCalibrate)
    def fail(*args):
        raise ValueError('probe already triggered')
    events = []
    obj.sample_count, obj.samples_result = 1, 'median'
    obj.sensor_location = [299, 290, 8.5]
    obj.locate_sensor = fail
    obj.printer = NS(lookup_object=lambda *args: NS(cmd_disable=lambda: events.append('disabled')))
    obj.gcode = NS(respond_info=lambda *args: None)
    with pytest.raises(ValueError, match='probe already triggered'):
        getattr(obj, command)(NS(get=lambda name, default: default))
    assert events == ['disabled']


def test_vendor_triggered_probe_prevents_travel():
    module = vendor_module('tools_calibrate_core')
    probe = module.PrinterProbeMultiAxis.__new__(module.PrinterProbeMultiAxis)
    probe.mcu_probe = [NS(query_endstop=lambda t: False), NS(query_endstop=lambda t: True)]
    probe.printer = NS(lookup_object=lambda name: NS(get_last_move_time=lambda: 10.0), command_error=ValueError)
    obj = module.ToolsCalibrate.__new__(module.ToolsCalibrate)
    obj.probe_multi_axis = probe
    moves = []
    with pytest.raises(ValueError, match='already TRIGGERED'):
        obj._safe_move(NS(manual_move=lambda *args: moves.append(args)), [100, 100, None], 20)
    assert moves == []
