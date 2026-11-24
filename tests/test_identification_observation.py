"""Exercise the Klipper status adapter with missing and contradictory inputs."""
from types import SimpleNamespace
import pytest
from test_identification_transaction import module


class Printer:
    def __init__(self):
        self.data = {
            'save_variables': {'variables': {'fail_flag': 0, 'is_nozzle_setting': 0}},
            'print_stats': {'state': 'standby'}, 'pause_resume': {'is_paused': False},
            'custom_hall': {'Raw': 5000},
            'filament_switch_sensor sensor_b': {'filament_detected': False},
            'gcode_macro Z_HOMING': {'z_raise': 1},
            'gcode_macro _WMP_TOOL_RETURN_BEGIN': {'success': 0, 'completed_success': 1},
            'toolhead': {'homed_axes': 'xyz'},
            **{'filament_switch_sensor docked%d' % n: {'filament_detected': True} for n in range(4)}}
        self.objects = {'virtual_sdcard': SimpleNamespace(is_active=lambda: False, is_cmd_from_sd=lambda: False)}
        self.shutdown = False

    def get_reactor(self):
        return SimpleNamespace(monotonic=lambda: 123)

    def is_shutdown(self):
        return self.shutdown

    def lookup_object(self, name, default=None):
        if name in self.objects:
            return self.objects[name]
        if name in self.data:
            return SimpleNamespace(get_status=lambda now: self.data[name])
        return default


def observer(printer):
    return module.KlipperObservation(printer, 4, SimpleNamespace(active=False, failure=''))


def test_released_and_attached_require_matching_live_sensors():
    printer = Printer()
    assert observer(printer)()['mounted'] is False
    printer.data['custom_hall']['Raw'] = 4000
    assert observer(printer)()['mounted'] is None
    printer.data['filament_switch_sensor sensor_b']['filament_detected'] = True
    assert observer(printer)()['mounted'] is True


@pytest.mark.parametrize('name,field', [
    ('save_variables', 'fault'), ('pause_resume', 'paused'),
    ('custom_hall', 'mounted'), ('filament_switch_sensor sensor_b', 'mounted')])
def test_missing_sensor_or_flag_stays_unknown(name, field):
    printer = Printer()
    del printer.data[name]
    assert observer(printer)()[field] is None


@pytest.mark.parametrize('hall', [True, None, float('nan'), 0, 7000])
def test_invalid_hall_never_becomes_released(hall):
    printer = Printer()
    printer.data['custom_hall']['Raw'] = hall
    assert observer(printer)()['mounted'] is None


@pytest.mark.parametrize('name', ['filament_operation', 'toolhead_operation'])
@pytest.mark.parametrize('state', ['pending', 'running'])
def test_material_operation_blocks_identification(name, state):
    printer = Printer()
    printer.objects['wm_material'] = SimpleNamespace(**{name: {'state': state}})
    assert not observer(printer)()['idle']


def test_ace_and_calibration_and_recovery_guards():
    printer = Printer()
    read = observer(printer)
    assert read()['idle'] and read()['recovery_ready']
    printer.objects['openace'] = object()
    assert not read()['idle']
    del printer.objects['openace']
    read.calibration.active = True
    assert not read()['idle']
    read.calibration.active = False
    read.calibration.failure = 'stopped'
    assert read()['idle']
    del printer.data['gcode_macro Z_HOMING']
    assert not read()['recovery_ready']


@pytest.mark.parametrize('case', ['active', 'from_sd', 'missing', 'unknown'])
def test_sd_activity_or_unavailable_sd_state_blocks_setup(case):
    printer = Printer()
    if case == 'missing':
        del printer.objects['virtual_sdcard']
    else:
        printer.objects['virtual_sdcard'] = SimpleNamespace(
            is_active=lambda: None if case == 'unknown' else case == 'active',
            is_cmd_from_sd=lambda: case == 'from_sd')
    assert not observer(printer)()['idle']


@pytest.mark.parametrize('values,expected', [
    ({'success': 0, 'completed_success': 1}, True),
    ({'success': 1, 'completed_success': 0}, False),
    ({'success': 1}, False), ({}, False)])
def test_identification_reads_completed_result_after_return_consumes_success(values, expected):
    printer = Printer()
    printer.data['gcode_macro _WMP_TOOL_RETURN_BEGIN'] = values
    assert observer(printer)()['toolchange_success'] is expected
