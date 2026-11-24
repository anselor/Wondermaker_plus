"""Identification Stop must unwind the retained dispatcher without shutdown."""
import importlib.util
from types import SimpleNamespace as NS

import pytest

from test_identification_commands import harness, identification_actor
from test_identification_transaction import ROOT, files, snapshot


@pytest.mark.parametrize('interrupt', ['cancel', 'owner-change', 'fault-with-cancel'])
def test_shared_boundary_uses_real_command_error_and_preserves_owner(files, interrupt):
    operation, command, commands, _, printer = harness(files)
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    assert path.is_file(), 'retained factory dispatcher required'
    spec = importlib.util.spec_from_file_location('identification_stock_dispatch', path)
    stock = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stock)
    from wmp_stop_points import check_operation_boundary

    shutdowns, events = [], []
    printer.quick_stop_flag = False
    printer.command_error = stock.CommandError
    printer.invoke_shutdown = shutdowns.append
    printer.send_event = events.append
    dispatch = stock.GCodeDispatch.__new__(stock.GCodeDispatch)
    dispatch.printer = printer
    dispatch.ready_gcode_handlers, dispatch.base_gcode_handlers = {}, {}
    dispatch.gcode_handlers = dispatch.ready_gcode_handlers
    dispatch.gcode_help = {}
    dispatch._build_status_commands = lambda: None
    dispatch.respond_info = dispatch.respond_raw = dispatch._respond_error = lambda message: None
    dispatch.cmd_default = lambda gcmd: pytest.fail('unexpected command ' + gcmd.get_command())
    original = operation.gcode.run_script_from_command
    printer.objects['gcode'] = operation.gcode = dispatch
    printer.objects['wmp_recovery'] = NS(calibration=operation.calibration, identification=operation)
    before = snapshot(files)

    def execute(gcmd):
        line = gcmd.get_commandline()
        original(line)
        if line != '_CHANGE_TOOL T=0':
            return
        if interrupt in ('cancel', 'fault-with-cancel'):
            fields = {'session': operation.calibration.session, 'request': command.get('REQUEST')}
            operation.handle_cancel(NS(get_str=fields.__getitem__, send=lambda reply: None, error=ValueError))
            if interrupt == 'fault-with-cancel':
                printer.data['save_variables']['variables']['fail_flag'] = -2
        else:
            printer.objects['wm_material'] = NS(session_id='replacement-owner')
        # Lock and the mandatory retreat complete before the shared Stop point.
        commands.append('coupling and retreat completed')
        dispatch.run_script_from_command('_WMP_OPERATION_STOP_POINT PHASE=before_tool_wipe')

    for name in ('M400', 'PARK_CURRENT_TOOL', 'SAVE_VARIABLE', '_CHANGE_TOOL'):
        dispatch.register_command(name, execute)
    dispatch.register_command('_WMP_OPERATION_STOP_POINT',
                              lambda gcmd: check_operation_boundary(printer, 'before nozzle wiping'))
    if interrupt == 'cancel':
        operation.dispatch(command)
        assert operation.get_status()['state'] == 'cancelled'
        assert operation.get_status()['mode_cleanup'] == 'cleared'
        assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 0
    elif interrupt == 'owner-change':
        with pytest.raises(ValueError, match='ownership changed'):
            operation.dispatch(command)
        assert operation.get_status()['mode_cleanup'] == 'unconfirmed'
        assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 1
        assert commands[-1] == 'coupling and retreat completed'
    else:
        with pytest.raises(ValueError, match='saved fail_flag=-2'):
            operation.dispatch(command)
        assert operation.get_status()['state'] == 'failed'
        assert operation.get_status()['mode_cleanup'] == 'cleared'
        assert printer.data['save_variables']['variables']['fail_flag'] == -2
    assert not shutdowns
    assert 'gcode:command_error' in events
    assert '_CHANGE_TOOL T=1' not in commands
    assert snapshot(files) == before
