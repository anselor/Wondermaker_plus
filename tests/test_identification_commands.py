"""Exercise backend command dispatch, sticky results and status publication."""
from types import SimpleNamespace as NS
import configparser
import sys
import uuid
import pytest
from test_identification_transaction import files, module, snapshot
from test_identification_observation import Printer
sys.path.insert(0, str(module.Path(__file__).resolve().parents[1] / 'klipper_extras'))
from wm_material import WMMaterial


@pytest.fixture(autouse=True)
def identification_actor(monkeypatch):
    actor = object()
    monkeypatch.setattr(module.IdentificationCommands, '_current_actor', staticmethod(lambda: actor))


def harness(files, observed_order=None):
    printer = Printer()
    observed_order = list(range(4)) if observed_order is None else observed_order
    printer.data['save_variables']['variables']['thr_number'] = 4
    printer.get_start_args = lambda: {'config_file': str(files / 'printer.cfg')}
    if not (files / 'printer.cfg').exists():
        active, saved = '', '#*# <---------------------- SAVE_CONFIG ---------------------->\n'
        for h in range(4):
            section = 'extruder' + (str(h) if h else '')
            active += '[%s]\nnozzle_diameter: 0.4\n' % section
            saved += '#*# [%s]\n#*# control = pid\n#*# pid_Kp = %d\n#*# pid_Ki = 2\n#*# pid_Kd = 100\n' % (section, 20 + h)
        (files / 'printer.cfg').write_text(active + saved)
        (files / 'tmt1.ini').write_text('[nozzle]\n' + ''.join('type%d=0\n' % h for h in range(4)))
    text = (files / 'printer.cfg').read_text()
    parsed = configparser.ConfigParser()
    parsed.read_string(text)
    parsed.read_string('\n'.join(line[4:] for line in text.splitlines()
                                if line.startswith('#*# ') and 'SAVE_CONFIG' not in line))
    settings = {section: {'control': parsed.get(section, 'control'),
                          **{key: parsed.getfloat(section, key) for key in ('pid_kp', 'pid_ki', 'pid_kd', 'nozzle_diameter')}}
                for section in parsed.sections()}
    for h in range(4):
        settings['mcu T%d' % h] = {'canbus_uuid': module.UUID_LINE.search(
            (files / ('wm_zru_thr%d.cfg' % h)).read_bytes()).group(2).decode().lower()}
    printer.data['configfile'] = {'settings': settings}
    printer.objects['wm_material'] = NS(
        session_id=uuid.uuid4().hex, profile_path=str(files / 'wmp_filaments.json'),
        _validate_identity=WMMaterial._validate_identity,
        _print_cancel_active=lambda: False, _recovery_attempt_active=lambda: False,
        _read_recovery_job=lambda: {}, filament_operation={}, toolhead_operation={})
    material = printer.objects['wm_material']
    material.printer = printer
    material._command_routing = lambda: WMMaterial._command_routing(material)
    material._material_operation_active = lambda name: WMMaterial._material_operation_active(material, name)
    material._attachment = lambda now: {'state': 'empty'}
    material._begin_explicit_physical_action = lambda action: WMMaterial._begin_explicit_physical_action(material, action)
    messages, commands, shutdowns = [], [], []
    printer.objects['toolhead'] = NS(get_status=lambda now: printer.data['toolhead'],
                                      wait_moves=lambda: commands.append('drain'))
    printer.invoke_shutdown = shutdowns.append
    def execute(command):
        commands.append(command)
        if command.startswith('_CHANGE_TOOL T='):
            physical = int(command.split('=')[1])
            printer.data['custom_hall']['Raw'] = 4000
            printer.data['filament_switch_sensor sensor_b']['filament_detected'] = True
            for n in range(4):
                printer.data['filament_switch_sensor docked%d' % n]['filament_detected'] = n != observed_order[physical]
        elif command == 'PARK_CURRENT_TOOL':
            printer.data['custom_hall']['Raw'] = 5000
            printer.data['filament_switch_sensor sensor_b']['filament_detected'] = False
            for n in range(4):
                printer.data['filament_switch_sensor docked%d' % n]['filament_detected'] = True
        elif command.startswith('SAVE_VARIABLE VARIABLE=is_nozzle_setting'):
            printer.data['save_variables']['variables']['is_nozzle_setting'] = int(command[-1])
    operation = module.IdentificationCommands(printer, NS(run_script_from_command=execute), NS(active=False, failure='', session='calibration-session', probe_editor=NS(busy=lambda: False, check_operation_boundary=lambda label: None), check_cancel=lambda label: None))
    fields = {'SESSION': 'calibration-session', 'REQUEST': uuid.uuid4().hex}
    return operation, NS(error=ValueError, respond_info=messages.append, get=lambda k, d=None: fields.get(k, d)), commands, messages, printer


def test_completed_mapping_is_queryable_and_cannot_be_started_again(files):
    operation, cmd, commands, messages, _ = harness(files)
    operation.run(cmd)
    status = operation.get_status()
    assert status['state'] == 'complete' and status['restart_required']
    assert len(status['steps']) == 7 and all(s['state'] == 'complete' for s in status['steps'])
    assert messages and 'Restart Klipper' in messages[-1]
    assert 'FIRMWARE_RESTART' not in commands
    before = list(commands)
    with pytest.raises(ValueError, match='published mapping'):
        operation.run(cmd)
    assert commands == before


@pytest.mark.parametrize('repair', [False, True], ids=['identify', 'repair-assignment'])
def test_lowercase_klipper_status_mcu_sections_identify_and_verify_restart(files, repair):
    operation, cmd, _, _, printer = harness(files)
    settings = printer.data['configfile']['settings']
    printer.data['configfile']['settings'] = {name.lower(): value for name, value in settings.items()}
    operation.dispatch(repair_command(cmd) if repair else cmd)
    assert operation.get_status()['state'] == 'complete'
    fresh, _, commands, _, printer = harness(files)
    settings = printer.data['configfile']['settings']
    printer.data['configfile']['settings'] = {name.lower(): value for name, value in settings.items()}
    fresh.check_startup()
    assert not fresh.get_status()['failure']
    assert not commands


@pytest.mark.parametrize('same_identity', [True, False], ids=['same-uuid', 'different-uuid'])
def test_ambiguous_mcu_status_aliases_refuse_before_identification(files, same_identity):
    operation, cmd, commands, _, printer = harness(files)
    settings = printer.data['configfile']['settings']
    identity = settings['mcu T0']['canbus_uuid'] if same_identity else 'ffffffffffff'
    settings['mcu t0'] = {'canbus_uuid': identity}
    before = snapshot(files)
    with pytest.raises(ValueError, match='Ambiguous active head MCU'):
        operation.dispatch(cmd)
    assert snapshot(files) == before
    assert not commands


@pytest.mark.parametrize('count', [None, 0, 5, True, '4', 2.5])
def test_invalid_count_refuses_without_motion_and_can_be_corrected(files, count):
    operation, cmd, commands, _, printer = harness(files)
    before = snapshot(files)
    printer.data['save_variables']['variables']['thr_number'] = count
    with pytest.raises(ValueError, match='head count'):
        operation.run(cmd)
    assert operation.get_status()['state'] == 'idle'
    assert not getattr(operation.calibration, 'identification_blocked', False)
    assert snapshot(files) == before and not commands
    printer.data['save_variables']['variables']['thr_number'] = 4
    operation.run(cmd)
    assert operation.get_status()['state'] == 'complete'


def test_sensor_failure_reports_failed_step_and_no_mapping_change(files):
    operation, cmd, commands, _, printer = harness(files)
    before = snapshot(files)
    del printer.data['custom_hall']
    with pytest.raises(ValueError, match='attachment state'):
        operation.run(cmd)
    assert operation.get_status()['steps'][0]['state'] == 'failed'
    assert snapshot(files) == before and not commands


def test_recovery_command_is_registered_and_delegates_to_adapter(files, monkeypatch):
    import sys
    import types
    from test_bottom_z import harness as recovery_harness, module as recovery_module
    operation, cmd, commands, _, _ = harness(files)
    recovery, _, calls, _, events, *_ = recovery_harness()
    assert ('register', '_WMP_IDENTIFY_HEADS') in calls
    # Match Klipper's package-relative helper import, using the real adapter.
    from importlib.machinery import ModuleSpec
    monkeypatch.setattr(recovery_module, '__spec__', ModuleSpec('identification_test_package.recovery', None))
    monkeypatch.setattr(recovery_module, '__package__', 'identification_test_package')
    monkeypatch.setitem(sys.modules, 'identification_test_package', types.ModuleType('identification_test_package'))
    monkeypatch.setitem(sys.modules, 'identification_test_package.wmp_identification',
                        NS(IdentificationCommands=lambda printer, gcode, calibration: operation))
    events['klippy:ready'][0]()
    assert recovery.get_status(0)['identification']['state'] == 'idle'
    assert not commands
    recovery.cmd_identify(cmd)
    assert recovery.get_status(0)['identification']['state'] == 'complete'
    assert commands
    before = list(commands)
    recovery.cmd_identify(cmd)
    assert commands == before


def test_startup_detects_interrupted_publication_without_motion_or_writes(files, monkeypatch):
    from test_identification_transaction import interrupt_commit
    transaction = interrupt_commit(files, monkeypatch)
    operation, cmd, commands, _, _ = harness(files)
    interrupted = snapshot(files)
    operation.check_startup()
    assert operation.get_status()['state'] == 'failed'
    assert 'Recover interrupted' in operation.get_status()['failure']
    assert not getattr(operation.calibration, 'identification_blocked', False)
    assert snapshot(files) == interrupted and not commands
    with pytest.raises(ValueError, match='UUID mapping contains duplicates'):
        operation.run(cmd)
    # A corrected current mapping can be retried; inspection never resumes it.
    module.MappingTransaction.recover(files, transaction.journal_path)
    fresh, _, commands, _, _ = harness(files)
    fresh.check_startup()
    assert fresh.get_status()['state'] == 'idle' and not commands
    assert operation.get_status()['state'] == 'idle'


@pytest.mark.parametrize('record', ['not json', '[]', '{"state":"committed"}', '{"version":1,"state":"publishing"}'])
def test_startup_rejects_untrusted_journal_without_modifying_it(files, record):
    path = files / '.wmp-identification-bad.json'
    path.write_text(record)
    operation, _, commands, _, _ = harness(files)
    operation.check_startup()
    assert operation.get_status()['state'] == 'failed'
    assert path.read_text() == record and not commands


@pytest.mark.parametrize('mode', [1, None, '0'])
def test_startup_rejects_leftover_or_unknown_mode(files, mode):
    operation, _, commands, _, printer = harness(files)
    printer.data['save_variables']['variables']['is_nozzle_setting'] = mode
    operation.check_startup()
    assert operation.get_status()['state'] == 'failed' and not commands


def test_successful_mapping_is_applied_by_new_session_without_restarting_setup(files):
    operation, cmd, _, _, _ = harness(files)
    operation.run(cmd)
    saved = snapshot(files)
    fresh, _, commands, _, _ = harness(files)
    fresh.check_startup()
    assert fresh.get_status()['state'] == 'idle'
    assert snapshot(files) == saved and not commands


@pytest.mark.parametrize('condition', ['openace', 'AFC', 'cancel', 'recovery', 'paused', 'session'])
def test_managed_identification_refuses_competing_ownership_before_motion(files, condition):
    operation, cmd, commands, _, printer = harness(files)
    material = printer.objects['wm_material']
    if condition in ('openace', 'AFC'):
        printer.objects[condition] = object()
    elif condition == 'cancel':
        material._print_cancel_active = lambda: True
    elif condition == 'recovery':
        material._recovery_attempt_active = lambda: True
    elif condition == 'paused':
        printer.data['pause_resume']['is_paused'] = True
    else:
        material.session_id = ''
    before = snapshot(files)
    with pytest.raises(ValueError):
        operation.run(cmd)
    assert not commands and snapshot(files) == before
    assert operation.operation is None and operation.failure == ''
    assert not getattr(operation.calibration, 'identification_blocked', False)


def test_confirmed_unchanged_mapping_preserves_loaded_flags_and_pid(files):
    operation, cmd, _, _, printer = harness(files)
    (files / 'wmp_filament_loaded.json').write_text('{"h0":true,"h1":false}')
    operation.run(cmd)
    import json
    assert json.loads((files / 'wmp_filament_loaded.json').read_text()) == {'h0': True, 'h1': False}
    saved = (files / 'printer.cfg').read_text().split('#*# [extruder]')[1].split('#*# [extruder1]')[0]
    assert 'pid_Kp = 20' in saved
    journal = next(files.glob('.wmp-head-migration-*.json'))
    assert json.loads(journal.read_text())['state'] == 'published'
    fresh, _, commands, _, _ = harness(files)
    fresh.check_startup()
    assert fresh.get_status()['state'] == 'idle' and not commands
    assert json.loads(journal.read_text())['state'] == 'verified'


def test_fresh_identification_retires_history_without_replaying_it(files):
    operation, cmd, commands, _, printer = harness(files)
    material = printer.objects['wm_material']
    material.filament_operation = {'state': 'unknown', 'id': 'old-filament'}
    material.toolhead_operation = {'state': 'unknown', 'id': 'old-tool'}
    material._read_recovery_job = lambda: {'state': 'committed'}
    printer.data['print_stats']['state'] = 'error'
    printer.objects['virtual_sdcard'].current_file = object()
    saved = printer.data['save_variables']['variables']
    saved.update(fail_flag=-5, wmp_print_context={'file': 'old.gcode'})
    operation.calibration.failure = 'old calibration failed'
    assert not operation._migration_admission(material, material.session_id)
    assert saved['fail_flag'] == -5  # Read-only admission never clears history.
    operation.dispatch(cmd)
    assert operation.get_status()['state'] == 'complete'
    assert saved['fail_flag'] == 0 and operation.calibration.failure == ''
    assert material.filament_operation['state'] == 'unknown'
    assert saved['wmp_print_context'] == {'file': 'old.gcode'}
    before = list(commands)
    operation.dispatch(cmd)
    assert commands == before


def test_new_identification_fault_is_not_cleared_by_intermediate_checks(files):
    operation, cmd, commands, _, printer = harness(files)
    execute = operation.gcode.run_script_from_command
    def fail_pickup(command):
        execute(command)
        if command.startswith('_CHANGE_TOOL'):
            printer.data['save_variables']['variables']['fail_flag'] = -5
    operation.gcode.run_script_from_command = fail_pickup
    with pytest.raises(ValueError, match='fail_flag=-5'):
        operation.dispatch(cmd)
    assert printer.data['save_variables']['variables']['fail_flag'] == -5
    assert sum(command.startswith('_CHANGE_TOOL') for command in commands) == 1
    before = list(commands)
    operation.dispatch(cmd)
    assert commands == before


@pytest.mark.parametrize('active', ['sd', 'paused', 'calibration', 'filament', 'cancel', 'recovery'])
def test_live_operation_prevents_identification_from_clearing_old_fault(files, active):
    operation, cmd, commands, _, printer = harness(files)
    material = printer.objects['wm_material']
    printer.data['save_variables']['variables']['fail_flag'] = -5
    if active == 'sd': printer.objects['virtual_sdcard'].is_active = lambda: True
    elif active == 'paused': printer.data['pause_resume']['is_paused'] = True
    elif active == 'calibration': operation.calibration.active = True
    elif active == 'filament': material.filament_operation = {'state': 'running'}
    elif active == 'cancel': material._print_cancel_active = lambda: True
    else: material._recovery_attempt_active = lambda: True
    with pytest.raises(ValueError): operation.dispatch(cmd)
    assert printer.data['save_variables']['variables']['fail_flag'] == -5
    assert not commands


def test_changed_identification_cannot_infer_calibration_ownership_from_old_uuid(files):
    operation, cmd, commands, _, _ = harness(files, list(reversed(range(4))))
    before = snapshot(files)
    with pytest.raises(ValueError, match='review calibration ownership and tool offsets'):
        operation.run(cmd)
    assert any(command.startswith('_CHANGE_TOOL') for command in commands)
    assert snapshot(files) == before
    assert not list(files.glob('.wmp-head-migration-*.json'))
    assert operation.get_status()['state'] == 'failed'
    assert not operation.get_status()['restart_required']


def repair_command(cmd, mode='repair_assignment', confirmation='1'):
    values = {'MODE': mode, 'CONFIRM_UNMOVED_SLOT_SETTINGS': confirmation}
    return NS(error=cmd.error, respond_info=cmd.respond_info,
              get=lambda key, default=None: values.get(key, cmd.get(key, default)))


@pytest.mark.parametrize('mode,confirmation', [('repair_assignment', ''), ('repair_assignment', '0'),
    ('repair_assignment', 'yes'), ('unknown', '1'), ('identify', '1')])
def test_assignment_repair_requires_explicit_unmoved_settings_confirmation(files, mode, confirmation):
    operation, cmd, commands, _, printer = harness(files, list(reversed(range(4))))
    before = snapshot(files)
    printer.data['save_variables']['variables']['fail_flag'] = -5
    with pytest.raises(ValueError):
        operation.dispatch(repair_command(cmd, mode, confirmation))
    assert not commands and snapshot(files) == before
    assert printer.data['save_variables']['variables']['fail_flag'] == -5


def test_explicit_assignment_repair_changes_only_uuid_and_verifies_after_restart(files):
    import json
    operation, cmd, commands, _, printer = harness(files, list(reversed(range(4))))
    for name, content in {
        'saved_variables.cfg': b'[Variables]\nt0_offset = (0,0,0)\nt1_offset = (1,2,3)\nt0_position = (44,340)\n',
        'wmp_filaments.json': b'{"h0":{"material":"PLA","brand":"Pink","color":"#ff00ff"}}',
        'wmp_filament_loaded.json': b'{"h0":true}',
        'wmp_hotend_materials.json': b'{"version":1,"heads":{}}',
    }.items():
        (files / name).write_bytes(content)
    before = {p.name: p.read_bytes() for p in files.iterdir() if p.is_file()}
    operation.dispatch(repair_command(cmd))
    assert operation.get_status()['state'] == 'complete'
    for name, raw in before.items():
        actual = (files / name).read_bytes()
        if name.startswith('wm_zru_thr'):
            head = int(name[len('wm_zru_thr')])
            assert actual == raw.replace(('00000000000%d' % head).encode(),
                                         ('00000000000%d' % (3-head)).encode())
        else:
            assert actual == raw
    journal = next(files.glob('.wmp-identification-*.json'))
    record = json.loads(journal.read_text())
    assert record['state'] == 'committed' and record['mode'] == 'repair_assignment'
    assert not record.get('verified_session')
    with pytest.raises(ValueError, match='fresh Klipper session'):
        module.AssignmentRepairTransaction.verify_loaded(files, journal, record,
            printer.objects['wm_material'].session_id, printer.data['configfile']['settings'])
    fresh, _, fresh_commands, _, fresh_printer = harness(files)
    fresh.check_startup()
    assert fresh.get_status()['state'] == 'idle' and not fresh_commands
    assert json.loads(journal.read_text())['verified_session'] == fresh_printer.objects['wm_material'].session_id


@pytest.mark.parametrize('failure', ['lost_write_reply', 'changed_admission'])
def test_assignment_repair_rolls_back_partial_uuid_publication(files, monkeypatch, failure):
    import json
    operation, cmd, commands, _, printer = harness(files, list(reversed(range(4))))
    before = snapshot(files)
    original_write = module.atomic_write
    failed = False
    def write(path, content):
        nonlocal failed
        original_write(path, content)
        if path.name == 'wm_zru_thr0.cfg' and not failed:
            failed = True
            if failure == 'lost_write_reply': raise OSError('lost write reply')
            printer.objects['wm_material']._print_cancel_active = lambda: True
    monkeypatch.setattr(module, 'atomic_write', write)
    with pytest.raises((ValueError, OSError)):
        operation.dispatch(repair_command(cmd))
    assert snapshot(files) == before
    record = json.loads(next(files.glob('.wmp-identification-*.json')).read_text())
    assert record['state'] == 'rolled-back'


def test_assignment_repair_restart_must_load_repaired_uuid(files):
    import json
    operation, cmd, _, _, _ = harness(files, list(reversed(range(4))))
    operation.dispatch(repair_command(cmd))
    fresh, _, commands, _, printer = harness(files)
    printer.data['configfile']['settings']['mcu T0']['canbus_uuid'] = 'ffffffffffff'
    fresh.check_startup()
    assert 'Loaded UUID assignment' in fresh.get_status()['failure']
    assert not commands
    record = json.loads(next(files.glob('.wmp-identification-*.json')).read_text())
    assert not record.get('verified_session')


def test_historical_recovery_record_is_not_an_identification_activity_lock(files):
    operation, _, _, _, printer = harness(files)
    material = printer.objects['wm_material']
    def absent():
        raise FileNotFoundError('no managed job yet')
    material._read_recovery_job = absent
    assert operation._migration_admission(material, material.session_id)
    def corrupt():
        raise ValueError('invalid saved job')
    material._read_recovery_job = corrupt
    assert operation._migration_admission(material, material.session_id)


def test_vendor_quick_stop_refuses_migration_admission(files):
    operation, _, _, _, printer = harness(files)
    material = printer.objects['wm_material']
    assert operation._migration_admission(material, material.session_id)
    # The vendor STOP request sets the flag on the printer (webhooks.py), never on gcode.
    printer.quick_stop_flag = True
    assert not operation._migration_admission(material, material.session_id)
    assert operation.migration_refusal == 'printer.quick_stop_flag is set'


@pytest.mark.parametrize('state', ['editing', 'missing'])
def test_probe_editor_ownership_refuses_identification_without_poisoning_editor(files, state):
    operation, cmd, commands, _, printer = harness(files)
    before = snapshot(files)
    material = printer.objects['wm_material']
    if state == 'missing':
        del operation.calibration.probe_editor
    else:
        # Only physical calibration ownership blocks identification.
        from wmp_recovery import ProbeEditorCommands
        editor = ProbeEditorCommands.__new__(ProbeEditorCommands)
        editor.state = state
        editor._executing = False
        editor.printer = printer
        editor.gcode = operation.gcode
        printer.objects['manual_probe'] = NS(status={'is_active': True})
        editor.save_review_required = state == 'save_review'
        operation.calibration.probe_editor = editor
    assert not operation._migration_admission(material, material.session_id)
    with pytest.raises(ValueError, match='resolve the probe editor'):
        operation.run(cmd)
    assert snapshot(files) == before and commands == []
    assert operation.operation is None and operation.failure == ''
    assert not getattr(operation.calibration, 'identification_blocked', False)
    # Resolving the existing editor permits an explicit new identification request.
    operation.calibration.probe_editor = NS(busy=lambda: False)
    operation.run(cmd)
    assert operation.get_status()['state'] == 'complete'


def test_editor_becoming_busy_revokes_migration_admission(files):
    operation, _, _, _, printer = harness(files)
    material = printer.objects['wm_material']
    assert operation._migration_admission(material, material.session_id)
    operation.calibration.probe_editor.busy = lambda: True
    assert not operation._migration_admission(material, material.session_id)


@pytest.mark.parametrize('change', ['generation', 'session', 'owner', 'editor', 'cancel', 'quick_stop'])
def test_mid_identification_context_change_prevents_next_pickup_and_publication(files, change):
    operation, cmd, commands, _, printer = harness(files)
    shutdowns = []
    printer.invoke_shutdown = shutdowns.append
    material = printer.objects['wm_material']
    before = snapshot(files)
    original = operation.gcode.run_script_from_command
    def changed(command):
        original(command)
        if command != '_CHANGE_TOOL T=0':
            return
        if change == 'generation': material._command_generation = 1
        elif change == 'session': material.session_id = 'replacement-session'
        elif change == 'owner': printer.objects['AFC'] = object()
        elif change == 'editor': operation.calibration.probe_editor.busy = lambda: True
        elif change == 'cancel': material._print_cancel_active = lambda: True
        elif change == 'quick_stop': printer.quick_stop_flag = True
    operation.gcode.run_script_from_command = changed
    with pytest.raises(ValueError):
        operation.run(cmd)
    assert snapshot(files) == before
    assert '_CHANGE_TOOL T=1' not in commands
    assert commands.count('_CHANGE_TOOL T=0') == 1
    assert not list(files.glob('.wmp-head-migration-*.json'))
    assert operation.get_status()['state'] == 'failed'
    if change in ('generation', 'session', 'owner'):
        # No barrier or saved-mode cleanup may run under the replacement owner.
        assert commands[-1] == '_CHANGE_TOOL T=0'
        assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 1
        assert 'unable to clear identification mode' in operation.operation.failure
        assert not shutdowns, 'Retired identification must not shut down the replacement owner'
    else:
        assert commands[-1] == 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0'


def test_quick_stop_refuses_identification_before_motion(files):
    operation, cmd, commands, _, printer = harness(files)
    printer.quick_stop_flag = True
    before = snapshot(files)
    with pytest.raises(ValueError, match='Resolve the active printer operation'):
        operation.run(cmd)
    assert commands == [] and snapshot(files) == before


def test_generation_change_at_publication_refuses_configuration_write(files, monkeypatch):
    operation, cmd, commands, _, printer = harness(files)
    material = printer.objects['wm_material']
    before = snapshot(files)
    publish = module.HeadConfigurationTransaction.publish
    def invalidated(transaction, admit):
        material._command_generation = 1
        return publish(transaction, admit)
    monkeypatch.setattr(module.HeadConfigurationTransaction, 'publish', invalidated)
    with pytest.raises(ValueError, match='publication is not admitted'):
        operation.run(cmd)
    assert snapshot(files) == before
    assert operation.get_status()['state'] == 'failed'
    assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 0


def test_correlated_preflight_refusal_is_retained_without_replay(files):
    operation, cmd, commands, _, _ = harness(files)
    operation.calibration.probe_editor.busy = lambda: True
    with pytest.raises(ValueError, match='probe editor'):
        operation.dispatch(cmd)
    result = operation.get_status()['request_result']
    assert result == {'session': cmd.get('SESSION'), 'request': cmd.get('REQUEST'),
                      'state': 'refused', 'error': 'Close or resolve the probe editor before head identification'}
    assert operation.get_status()['state'] == 'idle' and commands == []
    operation.calibration.probe_editor.busy = lambda: False
    operation.dispatch(cmd)  # Lost refusal reply cannot turn into motion later.
    assert commands == [] and operation.get_status()['request_result'] == result
    fields = {'SESSION': cmd.get('SESSION'), 'REQUEST': uuid.uuid4().hex}
    fresh = NS(error=ValueError, respond_info=lambda text: None, get=lambda k,d=None: fields.get(k,d))
    operation.dispatch(fresh)
    assert operation.get_status()['request_result']['state'] == 'complete'
    before = list(commands)
    operation.dispatch(fresh)
    assert commands == before


@pytest.mark.parametrize('fields', [{}, {'SESSION':'old', 'REQUEST':'a'*32},
                                   {'SESSION':'calibration-session', 'REQUEST':'bad'}])
def test_invalid_dispatch_identity_cannot_create_attempt(files, fields):
    operation, _, commands, _, _ = harness(files)
    cmd = NS(error=ValueError, respond_info=lambda text: None,
             get=lambda k,d=None: fields.get(k,d))
    with pytest.raises(ValueError, match='invalid identification request'):
        operation.dispatch(cmd)
    assert commands == [] and operation.request_result is None and not operation.requests


def test_failed_dispatch_receipt_does_not_replay_partial_identification(files):
    operation, cmd, commands, _, printer = harness(files)
    original = operation.gcode.run_script_from_command
    def failed(command):
        original(command)
        if command == '_CHANGE_TOOL T=0':
            raise ValueError('pickup interrupted')
    operation.gcode.run_script_from_command = failed
    with pytest.raises(ValueError, match='pickup interrupted'):
        operation.dispatch(cmd)
    assert operation.get_status()['request_result']['state'] == 'failed'
    before = list(commands)
    operation.dispatch(cmd)
    assert commands == before


@pytest.mark.parametrize('record', ['not json', '{"version":1,"state":"publishing"}'])
def test_fresh_identification_uses_current_configuration_not_old_journal(files, record):
    path = files / '.wmp-identification-old.json'
    path.write_text(record)
    operation, cmd, commands, _, _ = harness(files)
    operation.check_startup()
    assert operation.failure and not getattr(operation.calibration, 'identification_blocked', False)
    operation.dispatch(cmd)
    assert operation.get_status()['request_result']['state'] == 'complete'
    assert commands and path.read_text() == record


def test_old_journal_cannot_hide_current_loaded_mapping_mismatch(files):
    operation, cmd, commands, _, printer = harness(files)
    (files / '.wmp-identification-old.json').write_text('corrupt')
    printer.data['configfile']['settings']['mcu T0']['canbus_uuid'] = 'badbadbadbad'
    before = snapshot(files)
    with pytest.raises(ValueError, match='Active head identity differs'):
        operation.dispatch(cmd)
    assert operation.get_status()['request_result']['state'] == 'refused'
    assert not commands and snapshot(files) == before
    assert not getattr(operation.calibration, 'identification_blocked', False)


def test_failed_identification_can_retry_with_new_request_without_replaying_old_one(files):
    operation, cmd, commands, _, _ = harness(files)
    original = operation.gcode.run_script_from_command
    def fail(command):
        original(command)
        if command == 'PARK_CURRENT_TOOL': raise ValueError('dock failed')
    operation.gcode.run_script_from_command = fail
    with pytest.raises(ValueError, match='dock failed'): operation.dispatch(cmd)
    old = operation.get_status()['request_result']
    count = len(commands)
    operation.gcode.run_script_from_command = original
    operation.dispatch(cmd)
    assert len(commands) == count and operation.get_status()['request_result'] == old
    fields = {'SESSION': cmd.get('SESSION'), 'REQUEST': uuid.uuid4().hex}
    fresh = NS(error=ValueError, respond_info=lambda _: None, get=lambda k,d=None: fields.get(k,d))
    operation.dispatch(fresh)
    assert operation.get_status()['request_result']['state'] == 'complete'
    assert operation.requests[cmd.get('REQUEST')]['state'] == 'failed'

@pytest.mark.parametrize('change,detail', [
    ('paused', 'pause_resume.is_paused=True'),
    ('owner', 'AFC owns filament control'),
    ('filament', 'filament_operation.state=running'),
])
def test_identification_rejection_exposes_first_failed_gate(files, change, detail, caplog):
    operation, cmd, commands, messages, printer = harness(files)
    if change == 'paused': printer.data['pause_resume']['is_paused'] = True
    elif change == 'owner': printer.objects['AFC'] = object()
    elif change == 'filament': printer.objects['wm_material'].filament_operation = {'state': 'running'}
    with pytest.raises(ValueError) as error:
        operation.run(cmd)
    assert detail in str(error.value)
    assert not caplog.text  # Observation does not log; the action error carries its reason.
    assert not commands and not operation.failure
    assert not getattr(operation.calibration, 'identification_blocked', False)


@pytest.mark.parametrize('fault', [0, -3])
def test_explicit_identification_retry_clears_interrupted_mode_before_movement(files, fault):
    operation, cmd, commands, _, printer = harness(files)
    printer.objects['gcode'] = operation.gcode
    saved = printer.data['save_variables']['variables']
    saved.update(is_nozzle_setting=1, fail_flag=fault)
    operation.check_startup()
    assert operation.get_status()['state'] == 'failed' and commands == []
    operation.run(cmd)
    assert commands[0] == 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0'
    assert operation.get_status()['state'] == 'complete'
    assert saved['is_nozzle_setting'] == 0 and saved['fail_flag'] == 0


@pytest.mark.parametrize('failure', ['write', 'unchanged', 'boolean', 'string'])
def test_interrupted_mode_clear_failure_stops_before_identification_motion(files, failure):
    operation, cmd, commands, _, printer = harness(files)
    saved = printer.data['save_variables']['variables']
    saved.update(is_nozzle_setting=1, fail_flag=-3)
    shutdowns = []
    printer.invoke_shutdown = shutdowns.append
    def clear(command):
        commands.append(command)
        if failure == 'write': raise OSError('settings file is read-only')
        if failure == 'boolean': saved['is_nozzle_setting'] = False
        if failure == 'string': saved['is_nozzle_setting'] = '0'
    printer.objects['gcode'] = NS(run_script_from_command=clear)
    with pytest.raises(ValueError, match='retry Head identification'):
        operation.run(cmd)
    assert commands == ['SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0']
    assert saved['fail_flag'] == -3
    assert not shutdowns and operation.operation is None
    assert not getattr(operation.calibration, 'identification_blocked', False)
    # A separate corrected explicit attempt is possible without secret resets.
    saved['is_nozzle_setting'] = 1
    printer.objects['gcode'] = operation.gcode
    commands.clear()
    operation.run(cmd)
    assert operation.get_status()['state'] == 'complete'


@pytest.mark.parametrize('active', ['filament', 'toolhead', 'print', 'pause', 'calibration', 'homing', 'identification'])
def test_interrupted_mode_retry_never_clears_live_owner(files, active):
    operation, cmd, commands, _, printer = harness(files)
    printer.objects['gcode'] = operation.gcode
    saved = printer.data['save_variables']['variables']
    saved['is_nozzle_setting'] = 1
    material = printer.objects['wm_material']
    if active in ('filament', 'toolhead'):
        setattr(material, active + '_operation', {'state': 'running'})
    elif active == 'print': printer.objects['virtual_sdcard'].is_active = lambda: True
    elif active == 'pause': printer.data['pause_resume']['is_paused'] = True
    elif active == 'calibration': operation.calibration.active = True
    else:
        printer.objects['wmp_recovery'] = NS(get_status=lambda now: {
            'homing': active == 'homing', 'identification': {'state': 'running' if active == 'identification' else 'idle'}})
    with pytest.raises(ValueError): operation.run(cmd)
    assert commands == [] and saved['is_nozzle_setting'] == 1


def test_interrupted_mode_requires_coherent_attachment_before_clear(files):
    operation, cmd, commands, _, printer = harness(files)
    printer.objects['gcode'] = operation.gcode
    printer.data['save_variables']['variables']['is_nozzle_setting'] = 1
    printer.objects['wm_material']._attachment = lambda now: {'state': 'unknown'}
    with pytest.raises(ValueError, match='attachment sensors disagree'):
        operation.run(cmd)
    assert commands == []



def test_interrupted_mode_clear_uses_reloaded_saved_variable_dictionary(files):
    operation, cmd, commands, _, printer = harness(files)
    original = printer.data['save_variables']['variables']
    original.update(is_nozzle_setting=1, fail_flag=-3)
    def clear(command):
        commands.append(command)
        # Retained SaveVariables.loadVariables replaces allVariables.
        printer.data['save_variables']['variables'] = dict(original, is_nozzle_setting=0)
    printer.objects['gcode'] = NS(run_script_from_command=clear)
    operation.run(cmd)
    assert operation.get_status()['state'] == 'complete'
    assert printer.data['save_variables']['variables']['fail_flag'] == 0
    assert original['fail_flag'] == -3


def test_interrupted_mode_clear_executes_retained_save_variables(files):
    import importlib.util
    operation, _, commands, _, printer = harness(files)
    root = module.Path(__file__).resolve().parents[1]
    source = root / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/save_variables.py'
    spec = importlib.util.spec_from_file_location('identification_retained_save_variables', source)
    retained = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retained)
    saved = retained.SaveVariables.__new__(retained.SaveVariables)
    saved.printer = printer
    saved.filename = str(files / 'retained_variables.cfg')
    saved.allVariables = dict(printer.data['save_variables']['variables'], is_nozzle_setting=1, fail_flag=-3)
    old = saved.allVariables
    printer.command_error = ValueError
    printer.objects['save_variables'] = saved
    def execute(command):
        commands.append(command)
        params = dict(item.split('=', 1) for item in command.split()[1:])
        saved.cmd_SAVE_VARIABLE(NS(get=lambda key: params[key], error=ValueError))
    printer.objects['gcode'] = NS(run_script_from_command=execute)
    material = printer.objects['wm_material']
    material._begin_explicit_physical_action('head identification')
    assert commands == ['SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0']
    assert old is not saved.allVariables
    assert saved.allVariables['is_nozzle_setting'] == 0
    assert saved.allVariables['fail_flag'] == 0
    saved.loadVariables()
    assert saved.allVariables['is_nozzle_setting'] == 0  # Mode restoration is durable.


@pytest.mark.parametrize('replacement', ['material', 'operation'])
def test_replaced_identification_owner_is_not_stopped_or_rewritten(files, replacement):
    operation, cmd, commands, _, printer = harness(files)
    shutdowns = [];printer.invoke_shutdown = shutdowns.append
    before = snapshot(files);original = operation.gcode.run_script_from_command
    replacement_operation = NS(state='running', failure='new request')
    old_operation = []
    def changed(command):
        original(command)
        if command == '_CHANGE_TOOL T=0':
            old_operation.append(operation.operation)
            if replacement == 'material': printer.objects['wm_material'] = NS(session_id='new')
            else: operation.operation = replacement_operation
    operation.gcode.run_script_from_command = changed
    with pytest.raises(ValueError, match='ownership changed'): operation.run(cmd)
    assert commands[-1] == '_CHANGE_TOOL T=0'
    assert snapshot(files) == before and not shutdowns
    assert old_operation[0].status()['mode_cleanup'] == 'unconfirmed'
    if replacement == 'operation':
        assert operation.operation is replacement_operation
        assert replacement_operation.failure == 'new request'
        assert operation.failure == ''


def cancel_request(operation, identity, session=None):
    fields = {'session': operation.calibration.session if session is None else session,
              'request': identity}
    replies = []
    return NS(get_str=lambda key: fields[key], error=ValueError, send=replies.append), replies


@pytest.mark.parametrize('mode', ['identify', 'repair_assignment'])
def test_fast_identification_cancel_retires_queued_start_without_motion(files, mode):
    operation, command, commands, _, printer = harness(files)
    if mode == 'repair_assignment': command = repair_command(command)
    identity = command.get('REQUEST')
    before = snapshot(files)
    request, replies = cancel_request(operation, identity)
    operation.handle_cancel(request)
    operation.dispatch(command)
    assert commands == [] and snapshot(files) == before
    assert replies == [{'session': operation.calibration.session, 'request': identity, 'state': 'requested'}]
    assert operation.get_status()['request_result']['state'] == 'cancelled'
    assert operation.get_status()['cancel_protocol'] == 1


@pytest.mark.parametrize('mode', ['identify', 'repair_assignment'])
def test_identification_cancel_after_pickup_holds_without_publishing_or_parking_again(files, mode):
    operation, command, commands, _, printer = harness(files, [3, 2, 1, 0])
    if mode == 'repair_assignment': command = repair_command(command)
    records = {
        'wmp_filaments.json': b'{"h0":{"material":"PLA","brand":"Pink","color":"#ff00ff"}}',
        'wmp_filament_loaded.json': b'{"h0":true}',
        'wmp_hotend_materials.json': b'{"version":1,"heads":{}}',
    }
    for name, content in records.items(): (files/name).write_bytes(content)
    before = {p.name: p.read_bytes() for p in files.iterdir() if p.is_file()}
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0': operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
    operation.gcode.run_script_from_command = run
    operation.dispatch(command)
    assert operation.get_status()['state'] == 'cancelled'
    assert operation.get_status()['request_result']['state'] == 'cancelled'
    assert commands.count('PARK_CURRENT_TOOL') == 1  # Initial preparation only.
    assert '_CHANGE_TOOL T=1' not in commands
    assert commands[-1] == 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0'
    assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 0
    assert {p.name: p.read_bytes() for p in files.iterdir() if p.is_file()} == before


@pytest.mark.parametrize('field', ['session', 'request', 'openace', 'AFC'])
def test_identification_cancel_rejects_foreign_binding_without_side_effects(files, field):
    operation, command, commands, _, printer = harness(files)
    identity = 'invalid' if field == 'request' else command.get('REQUEST')
    if field in ('openace', 'AFC'): printer.objects[field] = object()
    request, replies = cancel_request(operation, identity, 'old' if field == 'session' else None)
    with pytest.raises(ValueError, match='request or owner changed'): operation.handle_cancel(request)
    assert not operation.requests and commands == [] and replies == []


def test_identification_fast_cancel_is_idempotent_and_history_is_bounded(files):
    operation, command, commands, _, _ = harness(files)
    request, replies = cancel_request(operation, command.get('REQUEST'))
    operation.handle_cancel(request);operation.handle_cancel(request)
    assert len(operation.requests) == 1 and len(replies) == 2
    for n in range(1,128): operation.handle_cancel(cancel_request(operation, format(n, '032x'))[0])
    with pytest.raises(ValueError, match='cannot retire'):
        operation.handle_cancel(cancel_request(operation, 'f'*32)[0])
    assert len(operation.requests) == 128 and not commands


@pytest.mark.parametrize('mode', ['identify', 'repair_assignment'])
def test_identification_cancel_cannot_interrupt_atomic_publication(files, monkeypatch, mode):
    operation, command, commands, _, _ = harness(files)
    transaction_type = module.ManagedMappingTransaction
    if mode == 'repair_assignment':
        command = repair_command(command)
        transaction_type = module.AssignmentRepairTransaction
    commit = transaction_type.commit
    def committing(transaction, *args, **kwargs):
        assert operation.get_status()['publication_started'] is True
        with pytest.raises(ValueError, match='publication has started'):
            operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
        return commit(transaction, *args, **kwargs)
    monkeypatch.setattr(transaction_type, 'commit', committing)
    operation.dispatch(command)
    assert operation.get_status()['state'] == 'complete'
    assert operation.get_status()['publication_started'] is True
    assert operation.get_status()['request_result']['state'] == 'complete'
    assert 'drain' not in commands


@pytest.mark.parametrize('change', ['generation', 'material_session', 'session', 'operation', 'manager', 'controller'])
def test_identification_cancel_drain_handoff_never_clears_new_owners_mode(files, change):
    operation, command, commands, _, printer = harness(files)
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0': operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
    material = printer.objects['wm_material']
    replacement = NS(state='running', status=lambda: {'state':'running'}, failure='replacement')
    printer.objects['wmp_recovery'] = NS(identification=operation, calibration=operation.calibration)
    def drain():
        commands.append('drain')
        if change == 'generation': material._command_generation = 1
        elif change == 'material_session': material.session_id = 'new'
        elif change == 'session': operation.calibration.session = 'new'
        elif change == 'operation': operation.operation = replacement
        elif change == 'controller': printer.objects['wmp_recovery'].identification = object()
        else: printer.objects['openace'] = object()
    printer.objects['toolhead'].wait_moves = drain
    operation.gcode.run_script_from_command = run
    before = snapshot(files)
    with pytest.raises(ValueError, match='owner changed|ownership changed'):
        operation.dispatch(command)
    assert commands[-1] == 'drain'
    assert 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0' not in commands
    assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 1
    assert snapshot(files) == before
    if change == 'operation': assert operation.operation is replacement and replacement.failure == 'replacement'


def test_identification_cancel_in_foreign_callback_latches_but_does_not_unwind(files, monkeypatch):
    from wmp_stop_points import check_operation_boundary
    operation, command, commands, _, printer = harness(files)
    printer.objects['wmp_recovery'] = NS(identification=operation, calibration=operation.calibration)
    actor = [object()];monkeypatch.setattr(operation, '_current_actor', lambda: actor[0])
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0':
            owner = actor[0];actor[0] = object()
            operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
            check_operation_boundary(printer, 'foreign callback')
            assert operation.get_status()['cancel_phase'] == ''
            actor[0] = owner
            check_operation_boundary(printer, 'completed pickup')
            pytest.fail('owned command failed to observe cancellation')
    operation.gcode.run_script_from_command = run
    operation.dispatch(command)
    assert operation.get_status()['state'] == 'cancelled'
    assert operation.get_status()['cancel_phase'] == 'completed pickup'
    assert commands[-2:] == ['drain', 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0']


@pytest.mark.parametrize('stop_axis', [1, 0])
def test_identification_cancel_after_native_axis_never_disables_motors(files, stop_axis):
    import importlib.util
    from pathlib import Path
    from wmp_xy_homing import XYHoming
    path = Path(__file__).resolve().parents[1]/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/homing.py'
    spec = importlib.util.spec_from_file_location('identification_cancel_native_homing', path)
    native = importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    operation, command, commands, _, printer = harness(files)
    printer.objects['wmp_recovery'] = NS(identification=operation, calibration=operation.calibration)
    printer.command_error = ValueError
    printer.data['toolhead']['homed_axes'] = ''
    rails = [NS(get_name=lambda: 'stepper_x', get_homing_info=lambda: NS(positive_dir=True)),
             NS(get_name=lambda: 'stepper_y', get_homing_info=lambda: NS(positive_dir=False))]
    axes = []
    def home(state):
        axes.append(state.get_axes())
        if state.get_axes() == [stop_axis]: operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
    kin = NS(rails=rails, home=home, limits=[(0,300), (0,300)])
    printer.objects['toolhead'].get_kinematics = lambda: kin
    printer.objects['stepper_enable'] = NS(motor_off=lambda: pytest.fail('normal identification Cancel disabled motors'))
    homing = native.PrinterHoming.__new__(native.PrinterHoming);homing.printer = printer
    printer.objects['homing'] = homing
    operation.gcode.register_command = lambda *args, **kwargs: None
    operation.gcode.create_gcode_command = lambda name, text, params: NS(get=lambda key, default=None: params.get(key, default))
    printer.objects['gcode'] = operation.gcode
    xy = XYHoming(printer)
    execute = operation.gcode.run_script_from_command
    gcmd = NS(error=ValueError, respond_info=lambda message: None)
    def run(text):
        if text == 'G28': xy._home(gcmd, native.Homing, native.HomingMove)
        else: execute(text)
    operation.gcode.run_script_from_command = run
    before = snapshot(files)
    operation.dispatch(command)
    assert axes == ([[1]] if stop_axis == 1 else [[1], [0]])
    assert operation.get_status()['state'] == 'cancelled'
    assert commands[-1] == 'drain' and 'PARK_CURRENT_TOOL' not in commands
    assert kin.limits[1] == (1., -1.) and snapshot(files) == before


def test_real_identification_fault_wins_over_simultaneous_cancel(files):
    operation, command, commands, _, printer = harness(files)
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0':
            operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
            printer.data['save_variables']['variables']['fail_flag'] = 17
    operation.gcode.run_script_from_command = run
    before = snapshot(files)
    with pytest.raises(ValueError, match='fault|fail_flag'):
        operation.dispatch(command)
    assert operation.get_status()['state'] == 'failed'
    assert operation.get_status()['request_result']['state'] == 'failed'
    assert 'drain' not in commands and snapshot(files) == before


def test_cancel_drain_failure_keeps_identification_failed_without_motion_retry(files):
    operation, command, commands, _, printer = harness(files)
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0': operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
    def fail_drain():
        commands.append('drain')
        raise ValueError('drain failed')
    printer.objects['toolhead'].wait_moves = fail_drain
    operation.gcode.run_script_from_command = run
    with pytest.raises(ValueError, match='drain failed'): operation.dispatch(command)
    assert commands[-1] == 'drain' and '_CHANGE_TOOL T=1' not in commands
    assert operation.get_status()['state'] == 'failed'
    assert printer.data['save_variables']['variables']['is_nozzle_setting'] == 1


@pytest.mark.parametrize('mode', ['identify', 'repair_assignment'])
def test_cancel_before_publication_does_not_replace_mapping(files, monkeypatch, mode):
    operation, command, commands, _, _ = harness(files)
    if mode == 'repair_assignment': command = repair_command(command)
    begin = operation._begin_publication
    def stop_before_publication():
        operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
        begin()
    monkeypatch.setattr(operation, '_begin_publication', stop_before_publication)
    before = snapshot(files)
    operation.dispatch(command)
    assert snapshot(files) == before
    assert operation.get_status()['state'] == 'cancelled'
    assert operation.get_status()['publication_started'] is False
    assert not list(files.glob('.wmp-head-migration-*.json'))


def test_identification_cancel_endpoint_delegate_never_initializes_a_controller(files):
    from wmp_recovery import BottomZ
    request = NS(error=ValueError)
    owner = NS(identification=None)
    with pytest.raises(ValueError, match='not available'):
        BottomZ.handle_identification_cancel(owner, request)
    calls = []
    owner.identification = NS(handle_cancel=calls.append)
    BottomZ.handle_identification_cancel(owner, request)
    assert calls == [request]


def test_identification_remains_running_until_cancel_drain_and_cleanup_finish(files):
    operation, command, commands, _, printer = harness(files)
    execute = operation.gcode.run_script_from_command
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0': operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
    def drain():
        status = operation.get_status()
        assert status['state'] == 'running' and status['request_result']['state'] == 'pending'
        assert status['cancel_requested'] and status['mode_cleanup'] == 'not_needed'
        commands.append('drain')
    printer.objects['toolhead'].wait_moves = drain
    operation.gcode.run_script_from_command = run
    operation.dispatch(command)
    status = operation.get_status()
    assert status['state'] == status['request_result']['state'] == 'cancelled'
    assert status['mode_cleanup'] == 'cleared' and status['request_result']['error']


def test_cancel_clears_owned_toolchange_marker_after_draining_before_mode_clear(files):
    operation, command, commands, _, printer = harness(files)
    printer.objects['gcode'] = operation.gcode
    execute = operation.gcode.run_script_from_command
    variables = printer.data['save_variables']['variables']
    def run(text):
        execute(text)
        if text == '_CHANGE_TOOL T=0':
            variables['changing_tool'] = 1
            operation.handle_cancel(cancel_request(operation, command.get('REQUEST'))[0])
        elif text == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0':
            variables['changing_tool'] = 0
    operation.gcode.run_script_from_command = run
    operation.dispatch(command)
    assert operation.get_status()['state'] == 'cancelled'
    assert operation.get_status()['toolchange_cleanup'] == 'cleared'
    assert variables['changing_tool'] == 0 and variables['is_nozzle_setting'] == 0
    assert commands[-3:] == ['drain', 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0',
                             'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0']
    assert '_CHANGE_TOOL T=1' not in commands
