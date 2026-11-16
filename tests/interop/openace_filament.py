"""Opt-in WM+/openACE runtime contract tests; hardware ports are simulated.

Run with openACE's checkout and this repo's klipper_extras on PYTHONPATH.
This filename deliberately avoids automatic discovery: openACE is optional.
"""
import pytest
import json
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.fake_klippy import FakeGCodeCommand
from wm_material import WMMaterial


@pytest.fixture
def adapter(manual_printer, tmp_path, monkeypatch):
    r = manual_printer()
    # Extend the upstream fake hardware ports, not the owner workflow. These
    # are synthetic fixture distances, not calibration for a physical printer.
    r.printer.lookup_object('gcode_macro _OPENACE_ZRU_PURGE').variables['load_mm'] = 30
    r.obj.printer_actions.capture_mm['h2'] = 10
    heaters = r.printer.lookup_object('heaters')
    r.gcode.register_command('SET_HEATER_TEMPERATURE', lambda command:
        heaters.set_temperature(command.get('HEATER'), command.get_float('TARGET')))
    r.prepare_heads(confirm=False)
    native, _ = r.install_print()
    monkeypatch.setattr(native, "get_status", lambda now: {"is_paused": native.is_paused}, raising=False)
    sensor = r.printer.lookup_object('filament_switch_sensor filament2')
    sensor.set(False)
    r.run('OPENACE_RECOVER HEAD=h2')
    wm = WMMaterial.__new__(WMMaterial)
    wm.printer = r.printer
    wm.session_id = 'wmp-contract-test'
    wm.profile_path = str(tmp_path / 'wmp-filaments.json')
    wm._filament_checks = {}
    wm._filament_requests = set()
    wm.filament_operation = {}
    wm.interop_errors = []
    original_run = r.gcode.run_script_from_command
    def run(script):
        try: return original_run(script)
        except Exception as error:
            wm.interop_errors.append((script, str(error)))
            raise
    monkeypatch.setattr(r.gcode, 'run_script_from_command', run)
    reactor = r.printer.get_reactor()
    callbacks = []
    monkeypatch.setattr(reactor, 'register_callback', callbacks.append, raising=False)
    return r, wm, sensor, reactor, callbacks


def submit(adapter, inserted=True):
    r, wm, sensor, reactor, callbacks = adapter
    sensor.set(inserted)
    plans = wm._openace_load_plans(2, reactor.monotonic())
    assert len(plans) == 1
    command = FakeGCodeCommand('WMP_FILAMENT_SEQUENCE', {'ID': 'direct-test', 'HEAD': '2', 'ACTION': 'load', 'TOKEN': plans[0]['token']}, r.gcode)
    wm.cmd_FILAMENT_SEQUENCE(command)
    assert wm.filament_operation['state'] == 'running'
    assert len(callbacks) == 1
    return callbacks.pop()


@pytest.mark.parametrize('inserted', [False, True])
def test_wmp_direct_load(adapter, monkeypatch, inserted):
    r, wm, sensor, reactor, callbacks = adapter
    execute = submit(adapter, inserted)
    original = reactor.pause
    def pause(wake):
        if wm.filament_operation.get('phase') == 'inserting': sensor.set(True)
        return original(wake)
    monkeypatch.setattr(reactor, 'pause', pause)
    execute(reactor.monotonic())
    if wm.filament_operation['state'] != 'complete':
        pytest.fail(json.dumps({'operation': wm.filament_operation, 'errors': wm.interop_errors}))
    load = r.obj.store.loaded.get('h2')
    assert load.verified and load.destination.is_direct
    assert r.unit_calls == []


class StopRequest:
    def __init__(self, wm):
        self.params = {'session': wm.session_id, 'id': 'direct-test', 'head': 'h2'}
        self.response = None
    def get_str(self, name): return self.params[name]
    def error(self, message): return ValueError(message)
    def send(self, response): self.response = response


@pytest.mark.parametrize('phase', ['preparation', 'insertion', 'feeding'])
def test_wmp_stop_through_real_owner(adapter, monkeypatch, phase):
    r, wm, sensor, reactor, callbacks = adapter
    execute = submit(adapter, phase != 'insertion')
    requests = []
    def stop():
        request = StopRequest(wm)
        wm._handle_filament_cancel(request)
        requests.append(request.response)
    if phase == 'insertion':
        original = reactor.pause
        def pause(wake):
            if wm.filament_operation.get('phase') == 'inserting' and not requests: stop()
            return original(wake)
        monkeypatch.setattr(reactor, 'pause', pause)
    else:
        macro = r.printer.lookup_object('gcode_macro ' + (
            '_OPENACE_ZRU_PARK' if phase == 'preparation' else '_OPENACE_ZRU_EXTRUDE'))
        original = macro.on_call
        def action(command):
            if original is not None: original(command)
            if not requests: stop()
        monkeypatch.setattr(macro, 'on_call', action)
    execute(reactor.monotonic())
    if not requests or wm.filament_operation['state'] != 'failed':
        pytest.fail(json.dumps({'operation': wm.filament_operation, 'errors': wm.interop_errors, 'requests': requests}))
    assert len(requests) == 1 and requests[0]['state'] == 'requested'
    assert wm.filament_operation['stopped'] is True
    assert r.printer.lookup_object('heaters').heater('extruder2').target == 0
    assert r.obj.operation is None and not r.obj.coordinator.has_aborting_operations()
    assert r.unit_calls == []


def test_wmp_reconciles_failed_cleanup_without_replaying_owner(adapter, monkeypatch):
    r, wm, sensor, reactor, callbacks = adapter
    execute = submit(adapter)
    extrude = r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE')
    original_action = extrude.on_call
    requests = []
    def abort(command):
        if original_action is not None: original_action(command)
        request = StopRequest(wm)
        wm._handle_filament_cancel(request)
        requests.append(request.response)
    monkeypatch.setattr(extrude, 'on_call', abort)
    original_run = r.gcode.run_script_from_command
    def failing_cool(script):
        if script.startswith('SET_HEATER_TEMPERATURE'):
            raise ValueError('simulated heater command delivery failure')
        return original_run(script)
    monkeypatch.setattr(r.gcode, 'run_script_from_command', failing_cool)
    execute(reactor.monotonic())
    assert len(requests) == 1
    assert wm.filament_operation['state'] == 'unknown'
    assert wm.filament_operation['openace_recovery_supported'] is True
    prior_load = r.obj.store.loaded.get('h2')
    prior_calls = len(extrude.calls)
    monkeypatch.setattr(r.gcode, 'run_script_from_command', original_run)
    command = FakeGCodeCommand('WMP_RECOVER_FILAMENT', {
        'ID': 'direct-test', 'HEAD': '2', 'SESSION': wm.session_id, 'GENERATION': '0'}, r.gcode)
    with r.gcode.get_mutex(): wm.cmd_RECOVER_FILAMENT(command)
    assert wm.filament_operation['stopped'] is True
    assert wm.filament_operation['state'] == 'failed'
    assert len(extrude.calls) == prior_calls
    assert r.obj.store.loaded.get('h2') == prior_load
    assert r.printer.lookup_object('heaters').heater('extruder2').target == 0


@pytest.mark.parametrize("wm_first", [False, True])
def test_both_plugins_initialize_before_ready(manual_printer, tmp_path, monkeypatch, wm_first):
    """Use complete constructors and the shared Ready/Disconnect event sequence."""
    from tests.klipper.fake_klippy import FakeConfig, FakePrinter, FakeReactor
    monkeypatch.setattr(FakeReactor, 'NOW', 0., raising=False)
    original_event = FakePrinter.send_event
    material = []
    config_path = tmp_path / 'printer.cfg'
    config_path.write_text('[printer]\nkinematics: corexy\n')
    monkeypatch.setattr(FakePrinter, 'get_start_args', lambda self: {'config_file': str(config_path)})

    def install(printer):
        # The owner's minimal fake printer omits Klipper's configfile command.
        # Supply the native port, but fail if startup actually attempts a save.
        def unexpected_save(command):
            raise AssertionError('Plugin initialization must not save configuration')
        printer.lookup_object('gcode').register_command('SAVE_CONFIG', unexpected_save)
        wm = WMMaterial(FakeConfig(printer, 'wm_material', {
            'ini_path': str(tmp_path / 'setting.ini'),
            'recovery_checkpoint_dir': str(tmp_path / 'checkpoints'),
            'usb_profile_root': str(tmp_path / 'usb'),
        }, {}))
        printer.add_object('wm_material', wm)
        material.append(wm)

    def event(printer, name, *args):
        if name == 'klippy:ready' and not material:
            install(printer)
        return original_event(printer, name, *args)
    monkeypatch.setattr(FakePrinter, 'send_event', event)
    if wm_first:
        from tests.klipper import test_zero_unit_runtime as upstream
        original_factory = upstream.make_printer
        def factory(*args, **kwargs):
            printer, config = original_factory(*args, **kwargs)
            install(printer)
            return printer, config
        monkeypatch.setattr(upstream, 'make_printer', factory)
    r = manual_printer()
    wm, = material
    assert r.printer.lookup_object('wm_material') is wm
    assert r.obj.coordinator is not None
    assert wm._lane_data(r.printer.get_reactor().monotonic()) == {}
    assert wm._afc_declined == ['SET_COLOR', 'SET_MATERIAL', 'AFC_SET_SPOOL_TEMP', 'WMP_SET_BRAND']
    r.prepare_heads()  # Public owner metadata commands still work after both Ready handlers.
    assert r.obj.store.loaded.get('h2').verified
    assert wm._execution_timer is not None
    assert not wm._execution_stopped
    # Exercise registered WM+ command dispatch after both Ready handlers,
    # rather than invoking methods on the adapter-only fixture above.
    native, _ = r.install_print()
    monkeypatch.setattr(native, 'get_status', lambda now: {'is_paused': native.is_paused}, raising=False)
    r.printer.lookup_object('gcode_macro _OPENACE_ZRU_PURGE').variables['load_mm'] = 30
    r.obj.printer_actions.capture_mm['h2'] = 10
    heaters = r.printer.lookup_object('heaters')
    r.gcode.register_command('SET_HEATER_TEMPERATURE', lambda command:
        heaters.set_temperature(command.get('HEATER'), command.get_float('TARGET')))
    sensor = r.printer.lookup_object('filament_switch_sensor filament2')
    sensor.set(False)
    r.run('OPENACE_RECOVER HEAD=h2')
    sensor.set(True)
    reactor = r.printer.get_reactor()
    queued = []
    monkeypatch.setattr(reactor, 'register_callback', queued.append, raising=False)
    with pytest.raises(ValueError, match='Head must be empty'):
        wm._openace_load_plans(2, reactor.monotonic())
    reactor.advance(2.1)  # Real startup sensor settling, not a saved-state override.
    plans = wm._openace_load_plans(2, reactor.monotonic())
    assert len(plans) == 1
    r.run('WMP_FILAMENT_SEQUENCE ID=full-startup HEAD=2 ACTION=load TOKEN=' + plans[0]['token'])
    assert wm.filament_operation['state'] == 'running'
    assert len(queued) == 1
    queued.pop()(reactor.monotonic())
    assert wm.filament_operation['state'] == 'complete', json.dumps(wm.filament_operation)
    assert r.obj.store.loaded.get('h2').verified
    assert r.obj.store.loaded.get('h2').destination.is_direct
    before_load = r.obj.store.loaded.get('h2')
    before_operation = dict(wm.filament_operation)
    with pytest.raises(ValueError, match='does not support managed unloading'):
        wm._filament_plan(2, 'unload', reactor.monotonic())
    assert queued == []
    assert wm.filament_operation == before_operation
    assert r.obj.store.loaded.get('h2') == before_load
    status = wm.get_status(reactor.monotonic())
    assert status['afc_metadata']['owner'] == 'openace'
    assert 'does not support managed unloading' in status['filament_procedure_errors']['h2:unload']
    assert not any(p['head'] == 'h2' and p['action'] == 'unload'
                   for p in status['filament_procedures'])
    assert status['filament_operation']['state'] == 'complete'
    r.close()
    assert wm._execution_stopped
    assert r.unit_calls == []
