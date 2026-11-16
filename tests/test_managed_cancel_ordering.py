"""Retained vendor ordering evidence for the R27 print-cancel boundary.

These are audit reproductions, not acceptance of managed print cancellation.
The reactor model controls only wakeup order; the mutex and run_script methods
are the retained 1.1.13 implementations.
"""
import ast
import importlib.util
from types import SimpleNamespace

from test_config_macros import ROOT, HeaterModel


VENDOR = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'


def test_stock_cancel_cannot_record_intent_until_service_releases_mutex():
    module = ast.parse((VENDOR / 'reactor.py').read_text())
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'ReactorMutex')
    waiter = SimpleNamespace(timer=object())
    namespace = {'greenlet': SimpleNamespace(getcurrent=lambda: waiter)}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), 'vendor_reactor_mutex', 'exec'), namespace)
    events = []
    class Reactor:
        NOW, NEVER = 0., 1e30
        def pause(self, when):
            assert when == self.NEVER
            assert mutex.test() and mutex.queue == [waiter]
            assert 'cancel-dispatched' not in events
            events.append('service-still-owns-mutex')
            # The service returns only now; the waiting Cancel has performed no
            # dispatch and could not have set the service cancellation flag.
            events.append('service-returned')
            mutex.__exit__()
        def update_timer(self, timer, when):
            assert timer is waiter.timer and when == self.NOW
    mutex = namespace['ReactorMutex'](Reactor(), True)
    spec = importlib.util.spec_from_file_location('cancel_vendor_gcode', VENDOR / 'gcode.py')
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    gcode = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    gcode.mutex = mutex
    def process(commands, need_ack):
        assert commands == ['CANCEL_PRINT'] and need_ack is False
        events.append('cancel-dispatched')
    gcode._process_commands = process
    gcode.run_script('CANCEL_PRINT')
    assert events == ['service-still-owns-mutex', 'service-returned', 'cancel-dispatched']
    assert not mutex.test()


def test_stock_cancel_renders_motion_even_with_unknown_managed_service():
    model = HeaterModel(ROOT / 'config/live')
    model.p['configfile']['settings'].update({
        'printer': {'max_velocity': 600, 'max_accel': 10000},
        'stepper_z': {'position_endstop': 300},
    })
    model.p['save_variables']['variables']['current_extruder'] = 3
    model.p['toolhead']['homed_axes'] = 'xyz'
    model.p['wm_material'] = {
        'filament_operation': {'state': 'unknown'},
        'toolhead_operation': {'state': 'unknown'},
        'attachment': {'state': 'unknown', 'head': ''},
    }
    script = model.templates['CANCEL_PRINT'].render(printer=model.p, params={})
    commands = [line.strip().split()[0] for line in script.splitlines()
                if line.strip() and not line.lstrip().startswith('#')]
    assert commands.index('_WMP_PRINT_CONTEXT_CLEAR') < commands.index('M400')
    assert commands.index('E_axis_move') < commands.index('TURN_OFF_HEATERS')
    assert commands.index('_WMP_PRINT_END_CLEARANCE_AND_WIPE') < commands.index('SDCARD_RESET_FILE')
