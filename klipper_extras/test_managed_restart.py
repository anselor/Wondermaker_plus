"""Exercise restart admission inside the retained vendor drain/exit boundary."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from wm_material import WMMaterial


ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'


@pytest.fixture
def restart():
    if not VENDOR.is_file():
        pytest.skip('retained vendor dispatcher required')
    spec = importlib.util.spec_from_file_location('restart_vendor_gcode', VENDOR)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    calls = []
    data = {'print_stats': {'state': 'standby'}, 'pause_resume': {'is_paused': False},
            'wmp_recovery': {'calibration_active': False}}
    sd = NS(current_file=None, is_active=lambda: False, is_cmd_from_sd=lambda: False)
    objects = {'virtual_sdcard': sd, 'toolhead': NS(
        get_last_move_time=lambda: 123, dwell=lambda delay: calls.append('dwell'),
        wait_moves=lambda: calls.append('drain'))}
    def lookup(name, default=None):
        if name in objects:
            return objects[name]
        return NS(get_status=lambda now: data[name]) if name in data else default
    material = WMMaterial.__new__(WMMaterial)
    material.filament_operation = {}
    material.toolhead_operation = {}
    material._print_cancel = {}
    material._recovery_attempt = None
    printer = NS(lookup_object=lookup, get_reactor=lambda: NS(monotonic=lambda: 10),
                 command_error=ValueError, request_exit=lambda reason: calls.append(reason))
    def event(name, print_time):
        assert name == 'gcode:request_restart'
        material._restart_requested(print_time)
    printer.send_event = event
    material.printer = printer
    dispatch = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    dispatch.printer = printer
    dispatch.is_printer_ready = True
    return NS(material=material, dispatch=dispatch, calls=calls, data=data, objects=objects, sd=sd)


@pytest.mark.parametrize('command', ['RESTART', 'FIRMWARE_RESTART'])
def test_idle_restart_retains_vendor_drain_and_exit_order(restart, command):
    getattr(restart.dispatch, 'cmd_' + command)(None)
    assert restart.calls == ['dwell', 'drain', command.lower()]


@pytest.mark.parametrize('condition', [
    'printing', 'paused', 'sd-active', 'sd-command', 'unknown-status',
    'cancel-pending', 'recovery-worker', 'recovery-queued',
    'filament-running', 'tool-running', 'calibration', 'missing-pause', 'pending-submission',
])
def test_ready_restart_refuses_before_drain_and_exit(restart, condition):
    material = restart.material
    if condition == 'printing':
        restart.data['print_stats']['state'] = 'printing'
    elif condition == 'paused':
        restart.data['pause_resume']['is_paused'] = True
    elif condition == 'sd-active':
        restart.sd.is_active = lambda: True
    elif condition == 'sd-command':
        restart.sd.is_cmd_from_sd = lambda: True
    elif condition == 'unknown-status':
        restart.data['print_stats']['state'] = None
    elif condition.startswith('cancel-'):
        material._print_cancel = {'state': condition.split('-')[1]}
    elif condition == 'recovery-worker':
        material._recovery_attempt = NS(busy=True, record={'state': 'running'})
    elif condition == 'recovery-queued':
        material._recovery_pending_worker = object()
    elif condition == 'filament-running':
        material.filament_operation = {'state': 'running'}
    elif condition == 'tool-running':
        material.toolhead_operation = {'state': 'running'}
    elif condition == 'calibration':
        restart.data['wmp_recovery']['calibration_active'] = True
    elif condition == 'missing-pause':
        del restart.data['pause_resume']
    else:
        material._pending_recovery_submission = {'pending': True}
    with pytest.raises(ValueError, match='Restart not admitted'):
        restart.dispatch.cmd_FIRMWARE_RESTART(None)
    assert restart.calls == []


def test_admission_reads_current_state_at_dispatch_not_a_previous_ui_snapshot(restart):
    restart.material._restart_requested(0)
    restart.material.filament_operation = {'state': 'running'}
    with pytest.raises(ValueError, match='filament/tool operation'):
        restart.dispatch.cmd_RESTART(None)
    assert restart.calls == []


def test_not_ready_explicit_restart_preserves_durable_hold(restart):
    restart.dispatch.is_printer_ready = False
    restart.material._print_cancel = {'state': 'unknown', 'id': 'retain'}
    restart.dispatch.cmd_FIRMWARE_RESTART(None)
    assert restart.calls == ['firmware_restart']
    assert restart.material._print_cancel == {'state': 'unknown', 'id': 'retain'}


@pytest.mark.parametrize('missing', ['pause-object', 'print-state'])
def test_unavailable_readiness_explains_existing_explicit_stop_then_restart(restart, missing):
    if missing == 'pause-object':
        del restart.data['pause_resume']
        reason = "'NoneType' object has no attribute 'get_status'"
    else:
        restart.data['print_stats']['state'] = None
        reason = 'print_stats.state=None'
    dispatch = restart.dispatch
    # Use the retained M112 and shutdown handlers, with only the printer event
    # delivery supplied by this fixture. No test-only force restart is added.
    dispatch.base_gcode_handlers = {}
    dispatch.gcode_help = {}
    dispatch._respond_state = lambda state: restart.calls.append(state)
    def shutdown(message):
        restart.calls.append(message)
        dispatch._handle_shutdown()
    dispatch.printer.invoke_shutdown = shutdown

    with pytest.raises(ValueError) as refused:
        dispatch.cmd_FIRMWARE_RESTART(None)
    message = str(refused.value)
    assert reason in message
    assert 'send M112, then send FIRMWARE_RESTART separately' in message
    assert 'interrupts any work and requires rehoming' in message
    assert restart.calls == []  # No shutdown, drain, or exit on refusal.
    assert dispatch.is_printer_ready

    dispatch.cmd_M112(None)  # A separate, deliberate user action.
    assert not dispatch.is_printer_ready
    assert restart.calls == ['Shutdown due to M112 command', 'Shutdown']
    dispatch.cmd_FIRMWARE_RESTART(None)  # A subsequent separate user action.
    assert restart.calls == ['Shutdown due to M112 command', 'Shutdown',
                             'firmware_restart']
    # Missing readiness was not fabricated or repaired to make admission pass.
    assert ('pause_resume' not in restart.data if missing == 'pause-object'
            else restart.data['print_stats']['state'] is None)


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_other_owner_keeps_original_restart_policy_pending_qualification(restart, owner):
    restart.objects[owner] = object()
    restart.data['print_stats']['state'] = 'printing'
    restart.dispatch.cmd_RESTART(None)
    assert restart.calls == ['dwell', 'drain', 'restart']


@pytest.mark.parametrize('saving,failure,permitted', [(True,'',True), (False,'',False), (True,'failed',False)])
def test_only_admitted_calibration_save_can_restart_while_active(restart, saving, failure, permitted):
    restart.objects['wmp_recovery'] = NS(
        get_status=lambda now: {'calibration_active': True},
        calibration=NS(active=True, _saving=saving, failure=failure))
    if permitted:
        restart.dispatch.cmd_FIRMWARE_RESTART(None)
        assert restart.calls == ['dwell', 'drain', 'firmware_restart']
    else:
        with pytest.raises(ValueError, match='calibration'):
            restart.dispatch.cmd_FIRMWARE_RESTART(None)
        assert not restart.calls


@pytest.mark.parametrize('state', ['pending', 'unknown'])
def test_calibration_save_only_conflicts_with_current_cancellation(restart, state):
    restart.objects['wmp_recovery'] = NS(
        get_status=lambda now: {'calibration_active': True},
        calibration=NS(active=True, _saving=True, failure=''))
    restart.material._print_cancel = {'state': state}
    if state == 'pending':
        with pytest.raises(ValueError, match='cancellation'):
            restart.dispatch.cmd_FIRMWARE_RESTART(None)
        assert not restart.calls
    else:
        restart.dispatch.cmd_FIRMWARE_RESTART(None)
        assert restart.calls == ['dwell', 'drain', 'firmware_restart']
    assert restart.material._print_cancel == {'state': state}


@pytest.mark.parametrize('state', ['none', 'unknown', 'pending'])
def test_calibration_save_and_vendor_restart_share_admission(restart, state):
    from wmp_recovery import CalibrationCommands
    printer = restart.material.printer
    printer.is_shutdown = lambda: False
    restart.objects['save_variables'] = NS(get_status=lambda now: {'variables': {'fail_flag': 0}})
    written = []
    def save(command):
        assert command == 'SAVE_CONFIG'
        written.append(command)
        restart.dispatch.cmd_FIRMWARE_RESTART(None)
    gcode = NS(register_command=lambda *args, **kwargs: None, run_script_from_command=save)
    calibration = CalibrationCommands(printer, gcode)
    restart.objects['wm_material'] = restart.material
    restart.objects['wmp_recovery'] = NS(calibration=calibration,
        get_status=lambda now: {'calibration_active': calibration.active})
    command = NS(get=lambda key, default: 'SAVE_CONFIG'.encode().hex() if key == 'HEX' else default,
                 error=ValueError)
    if state != 'none':
        restart.material._print_cancel = {'state': state}
    if state == 'pending':
        with pytest.raises(ValueError, match='cancellation'):
            calibration.cmd_run(command)
        assert written == [] and restart.calls == []
    else:
        calibration.cmd_run(command)
        assert written == ['SAVE_CONFIG']
        assert restart.calls == ['dwell', 'drain', 'firmware_restart']
    assert not calibration.active and not calibration._saving


def test_editor_admission_is_identity_scoped_and_does_not_permit_external_restart(restart):
    editor = object()
    restart.objects['wmp_recovery'] = NS(
        get_status=lambda now: {'calibration_active': True},
        calibration=NS(active=False, probe_editor=editor, _saving=False, failure=''))
    restart.material._restart_requested(None, probe_editor=editor)
    for other in (None, object()):
        with pytest.raises(ValueError, match='calibration'):
            restart.material._restart_requested(None, probe_editor=other)
    restart.objects['wmp_recovery'].calibration.active = True
    with pytest.raises(ValueError, match='calibration'):
        restart.material._restart_requested(None, probe_editor=editor)


@pytest.mark.parametrize('history', ['cancel-unknown', 'tool-unknown', 'recovery-stopped', 'recovery-running'])
def test_restart_does_not_mistake_history_for_a_live_worker(restart, history):
    # A label alone cannot establish live execution: RecoveryAttempt.run owns
    # runner.busy and the deferred command is represented by pending_worker.
    # Restart restoration also converts interrupted running records to unknown.
    if history == 'cancel-unknown':
        restart.material._print_cancel = {'state': 'unknown'}
    elif history == 'tool-unknown':
        restart.material.toolhead_operation = {'state': 'unknown'}
    else:
        restart.material._recovery_attempt = NS(busy=False, record={'state': history.split('-')[1]})
    before = (dict(restart.material._print_cancel), dict(restart.material.toolhead_operation),
              dict(restart.material._recovery_attempt.record) if restart.material._recovery_attempt else None)
    restart.dispatch.cmd_FIRMWARE_RESTART(None)
    assert restart.calls == ['dwell', 'drain', 'firmware_restart']
    after = (restart.material._print_cancel, restart.material.toolhead_operation,
             restart.material._recovery_attempt.record if restart.material._recovery_attempt else None)
    assert after == before


def test_selected_idle_file_does_not_block_explicit_restart(restart):
    restart.sd.current_file = NS(closed=False)
    restart.dispatch.cmd_FIRMWARE_RESTART(None)
    assert restart.calls == ['dwell', 'drain', 'firmware_restart']
