"""A fresh explicit retry retires history, never the failed command's tail."""
from types import SimpleNamespace as NS
import pytest

pytest_plugins = ['test_wm_material']


def historical_fault(material, objects):
    variables = {'fail_flag': -3, 'is_nozzle_setting': 0}
    objects['save_variables'] = NS(get_status=lambda now: {'variables': variables})
    objects['wmp_recovery'] = NS(get_status=lambda now: {'calibration_active': False, 'homing': False})
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h2'}
    return variables


def test_console_retry_retires_history_but_nested_error_aborts_tail(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    variables = historical_fault(material, objects)
    objects['virtual_sdcard'].is_active = lambda: False
    objects['virtual_sdcard'].is_cmd_from_sd = lambda: False
    dispatcher.run_script_from_command = lambda script: vendor.GCodeDispatch.run_script_from_command(dispatcher, script)
    def fail(command):
        variables['fail_flag'] = -3
        raise vendor.CommandError('release still failed')
    dispatcher.gcode_handlers['FAIL'] = fail
    dispatcher.gcode_handlers['G28'] = lambda command: dispatcher.run_script_from_command('FAIL\nG1 X90')
    with pytest.raises(vendor.CommandError, match='release still failed'):
        dispatcher.run_script('G28\nG1 X100')
    assert variables['fail_flag'] == -3
    assert 'move' not in events
    generation = material._command_generation
    # Corrected current hardware, then a distinct user action, no secret reset.
    dispatcher.gcode_handlers['G28'] = lambda command: events.append('homed')
    dispatcher.run_script('G28')
    assert variables['fail_flag'] == 0 and events[-1] == 'homed'
    assert 'move' not in events
    assert material._command_generation == generation


@pytest.mark.parametrize('condition', ['running', 'contradictory', 'shutdown', 'quick_stop'])
def test_fresh_retry_still_checks_current_conditions(guarded_legacy_dispatch, condition):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    variables = historical_fault(material, objects)
    objects['virtual_sdcard'].is_active = lambda: False
    objects['virtual_sdcard'].is_cmd_from_sd = lambda: False
    if condition == 'running': material.toolhead_operation = {'state': 'running'}
    elif condition == 'contradictory': material._material_status()._attachment = lambda now: {'state': 'unknown'}
    elif condition == 'quick_stop': material.printer.quick_stop_flag = True
    else: material.printer.is_shutdown = lambda: True
    with pytest.raises(ValueError): material._begin_explicit_physical_action('console motion')
    assert variables['fail_flag'] == -3 and not events


def test_stationary_unlock_can_address_current_attachment_disagreement(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    variables = historical_fault(material, objects)
    objects['virtual_sdcard'].is_active = lambda: False
    objects['virtual_sdcard'].is_cmd_from_sd = lambda: False
    material._material_status()._attachment = lambda now: {'state': 'unknown'}
    dispatcher.gcode_handlers['UNLOCK'] = lambda command: events.append('unlock')
    dispatcher.run_script('UNLOCK')
    assert variables['fail_flag'] == 0 and events == ['unlock']


def test_sd_begin_only_clears_history_once_for_actual_start_line(recovery_startup):
    from test_wm_material import FakeCommand
    material, objects, request, path = recovery_startup
    variables = objects['save_variables'].values['variables']
    path.write_text('START_PRINT INITIAL_TOOL=0\n_WMP_RECOVERY_JOB_BEGIN\n')
    sd = objects['virtual_sdcard']
    sd.file_position, sd.next_file_position = 0, len('START_PRINT INITIAL_TOOL=0\n')
    objects['gcode_macro START_PRINT'] = NS(get_status=lambda now: {'print_body_ready': False})
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h2'}
    variables['fail_flag'] = -3
    material.printer.is_shutdown = lambda: False
    material._pending_recovery_submission = None
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    assert variables['fail_flag'] == 0
    variables['fail_flag'] = -3  # New failure in this startup, not old history.
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    assert variables['fail_flag'] == -3
    sd.file_position = sd.next_file_position
    sd.next_file_position = path.stat().st_size
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    assert variables['fail_flag'] == -3  # Internal helper on another line is not Start.


@pytest.mark.parametrize('command', ['G28', 'G29', 'PID_CALIBRATE', 'SHAPER_CALIBRATE', 'PROBE_CALIBRATE'])
def test_top_level_calibration_retry_has_fresh_boundary(guarded_legacy_dispatch, command):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    variables = historical_fault(material, objects)
    objects['virtual_sdcard'].is_active = lambda: False
    objects['virtual_sdcard'].is_cmd_from_sd = lambda: False
    dispatcher.gcode_handlers[command] = lambda gcmd: events.append(command)
    dispatcher.run_script(command)
    assert variables['fail_flag'] == 0 and events == [command]


def test_filament_preview_keeps_history_but_strict_execution_context_does_not(service_material):
    material, objects, states = service_material
    states['save_variables']['variables']['fail_flag'] = -3
    plan = material._filament_plan(2, 'load', 1)
    assert plan['head'] == 'h2'
    assert states['save_variables']['variables']['fail_flag'] == -3
    with pytest.raises(ValueError, match='fail_flag'):
        material._service_context(2, 1)


def test_current_console_refusal_is_vendor_command_error(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, *unused = fixture
    historical_fault(material, objects)
    material.toolhead_operation = {'state': 'running'}
    with pytest.raises(vendor.CommandError, match='current physical operation'):
        dispatcher.run_script('G28')
    assert not events


@pytest.mark.parametrize('action', ['take', 'dock'])
def test_fresh_managed_retry_after_repeated_physical_failure(toolhead_material, action):
    from test_wm_material import toolhead_command
    material, objects, states, scripts, callbacks = toolhead_material
    material.printer.is_shutdown = lambda: False
    variables = states['save_variables']['variables']
    variables['fail_flag'] = -3
    fails = [True]
    def dispatch(script):
        scripts.append(script)
        if script in ('_CHANGE_TOOL T=2', 'PARK_CURRENT_TOOL'):
            if fails[0]:
                variables['fail_flag'] = -3
                raise ValueError('release still failed')
            wanted = {'state': 'attached', 'head': 'h2'} if action == 'take' else {'state': 'empty', 'head': ''}
            material._material_status()._attachment = lambda now: wanted
    objects['gcode'].run_script_from_command = dispatch
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION=action))
    callbacks.pop()(1)
    assert material.toolhead_operation['state'] == 'unknown' and variables['fail_flag'] == -3
    fails[0] = False
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION=action, ID='fresh-retry'))
    callbacks.pop()(1)
    assert material.toolhead_operation['state'] == 'complete' and variables['fail_flag'] == 0
    assert scripts.count('_CHANGE_TOOL T=2' if action == 'take' else 'PARK_CURRENT_TOOL') == 2


@pytest.mark.parametrize('history', [-3, -2, None])
def test_recovery_review_reads_history_without_clearing_it(native_recovery_request, history):
    import json
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, unused, timers, body, mutex = fixture
    variables = objects['save_variables'].values['variables']
    if history is None: variables.pop('fail_flag', None)
    else: variables['fail_flag'] = history
    states['wmp_recovery']['calibration_failed'] = 'old calibration failed'
    material._recovery_review_service()._recovery_request_review(json.dumps(request).encode().hex())
    assert variables.get('fail_flag') == history and not calls
    result = material._recovery_review_service()._consume_recovery_request(json.dumps(request).encode().hex())
    assert result['state'] == 'complete' and variables['fail_flag'] == 0


def test_recovery_new_failure_after_admission_is_not_cleared(native_recovery_request):
    import json
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, unused, timers, body, mutex = fixture
    variables = objects['save_variables'].values['variables']
    variables['fail_flag'] = -3
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script == '_WMP_RECOVERY_BEGIN': variables['fail_flag'] = -3
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='fault state changed'):
        material._recovery_review_service()._consume_recovery_request(json.dumps(request).encode().hex())
    assert variables['fail_flag'] == -3
    assert '_WMP_HOME_Z_BOTTOM' not in calls and not body
