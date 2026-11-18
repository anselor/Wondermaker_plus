"""Retained SD/macro dispatch reaches the guarded mesh writer without motion.

Hardware leaf commands are inert. The SD worker, command parser, macro status
snapshots, START_PRINT expansion, WM+ admission and config writer are real.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from test_probe_config_change import ROOT, load, config, guarded_config
from test_print_recovery import RecoveryModel


class Mutex:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def test(self): return False


@pytest.mark.parametrize('blocker', [None, 'other_pending', 'probe_save_review', 'running_calibration'])
def test_retained_stock_sd_startup_mesh_save(guarded_config, blocker):
    v = guarded_config
    vendor = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'
    gc = load('mesh_retained_gcode', vendor / 'gcode.py')
    gm = load('mesh_retained_macro', vendor / 'extras/gcode_macro.py')
    sdmod = load('mesh_retained_sd', vendor / 'extras/virtual_sdcard.py')
    model = RecoveryModel()
    v.state.update(model.p)
    v.state['save_variables']['variables']['box_modify_t0'] = 0
    v.config.get_status = lambda now: model.p['configfile']
    v.state.update({'pause_resume': {'is_paused': False},
        'print_stats': {'state': 'standby', 'filename': 'job.gcode'},
        'wmp_recovery': {'calibration_active': False, 'calibration_failed': '', 'homing': False},
        'wm_material': {}})
    v.objects['configfile'] = v.config
    reactor = NS(monotonic=lambda: 1, mutex=Mutex, pause=lambda when: None,
                 unregister_timer=lambda timer: None, NOW=0, NEVER=999999)
    printer = v.material.printer
    printer.quick_stop_flag = False
    printer.get_reactor = lambda: reactor
    printer.register_event_handler = lambda *args: None
    printer.send_event = lambda *args: None
    printer.command_error = gc.CommandError
    def shutdown(message): raise AssertionError('Unexpected shutdown: ' + message)
    printer.invoke_shutdown = shutdown
    printer.lookup_objects = lambda: list(v.objects.items())
    gcode = gc.GCodeDispatch(printer)
    gcode.request_restart = lambda kind: v.restarts.append(kind)
    v.objects['gcode'] = gcode
    # Unknown hardware/temperature/service leaf commands deliberately do nothing.
    gcode.cmd_default = lambda command: None
    errors, markers, positions = [], [], []
    gcode._respond_error = errors.append
    tracker = gm.PrinterGCodeMacro(NS(get_printer=lambda: printer))
    v.objects['gcode_macro'] = tracker
    source = v.path.parent / 'job.gcode'
    first_line = ('START_PRINT BED=60 EXTRUDER=220 INITIAL_TOOL=0 '
                  'MESH_MIN_X=142 MESH_MIN_Y=127 MESH_MAX_X=158 MESH_MAX_Y=143 '
                  'PROBE_COUNT_X=4 PROBE_COUNT_Y=4')
    source.write_text(first_line + '\nM118 NEXT_SD_LINE\n')
    v.material.session_id = 'retained-stock-start'
    v.material.profile_path = str(v.path.parent / 'wmp_filaments.json')
    v.config.status_save_pending = {}
    v.config.autosave.fileconfig.remove_section('probe')
    if blocker == 'other_pending':
        v.config.set('extruder', 'pid_kp', '25')
    recovery_module = load('sd_real_probe_recovery', ROOT / 'klipper_extras/wmp_recovery.py')
    calibration = recovery_module.CalibrationCommands(printer, gcode)
    recovery = recovery_module.BottomZ.__new__(recovery_module.BottomZ)
    recovery.printer, recovery.calibration = printer, calibration
    recovery.valid, recovery.active, recovery.identification = True, False, None
    v.state['toolhead']['homed_axes'] = 'xyz'
    v.objects['wmp_recovery'] = recovery
    if blocker == 'probe_save_review':
        # User1's saved-result review is still owned by the editor, but the
        # real busy()/BottomZ status contract must not reserve the machine.
        editor = calibration.probe_editor
        editor.state, editor.save_review_required = 'save_review', True
        editor.save_review = {'configuration_matches': True, 'loaded_offset': -0.140, 'differences': []}
        assert editor.save_review_required and not editor.busy()
        status = recovery.get_status(1)
        assert status['calibration_active'] is False
        assert status['probe_editor']['state'] == 'save_review'
        assert status['probe_editor']['save_review_required'] is True
    elif blocker == 'running_calibration':
        calibration.active = True
        assert recovery.get_status(1)['calibration_active'] is True
    before = v.path.read_bytes()
    with source.open() as stream:
        sd = sdmod.VirtualSD.__new__(sdmod.VirtualSD)
        sd.printer, sd.reactor, sd.gcode = printer, reactor, gcode
        sd.work_timer, sd.current_file = object(), stream
        sd.file_position = sd.next_file_position = 0
        sd.file_size = source.stat().st_size
        sd.cmd_from_sd = sd.must_pause_work = False
        sd.on_error_gcode = NS(render=lambda: '')
        sd.print_stats = NS(note_start=lambda: v.state['print_stats'].update(state='printing'),
                           note_error=errors.append, note_pause=lambda: None,
                           note_complete=lambda: v.state['print_stats'].update(state='complete'))
        v.objects['virtual_sdcard'] = sd
        macro = gm.GCodeMacro.__new__(gm.GCodeMacro)
        macro.printer, macro.gcode = printer, gcode
        macro.alias, macro.in_script = 'START_PRINT', False
        macro.variables = dict(model.p['gcode_macro START_PRINT'])
        source_text = (ROOT / 'config/live/macros.cfg').read_text()
        parsed = v.config._build_config_wrapper(source_text, str(ROOT / 'config/live/macros.cfg'))
        body = parsed.fileconfig.get('gcode_macro START_PRINT', 'gcode', raw=True)
        macro.template = gm.TemplateWrapper(printer, tracker.env, 'START_PRINT', body)
        v.objects['gcode_macro START_PRINT'] = macro
        gcode.register_command('START_PRINT', macro.cmd)
        gcode.register_command('SET_GCODE_VARIABLE', lambda c: macro.cmd_SET_GCODE_VARIABLE(c)
                               if c.get('MACRO') == 'START_PRINT' else None)
        def begin(command):
            v.material.cmd_RECOVERY_JOB_BEGIN(command)
            positions.append((sd.file_position, sd.next_file_position, sd.is_active(), sd.is_cmd_from_sd()))
        gcode.register_command('_WMP_RECOVERY_JOB_BEGIN', begin)
        gcode.register_command('_WMP_PRINT_CONTEXT_COMMIT', lambda command: None)
        def measure(command):
            assert command.get('PROFILE') == 'wmp_print'
            assert command.get('PROBE_COUNT') == '4,4'
            v.state['bed_mesh']['profile_name'] = ''
        gcode.register_command('BED_MESH_CALIBRATE', measure)
        def mesh(command):
            if command.get('SAVE', None):
                v.config.set('bed_mesh wmp_print', 'points', '0.1, 0.2\n0.3, 0.4')
            if command.get('LOAD', None):
                v.state['bed_mesh']['profile_name'] = command.get('LOAD')
        gcode.register_command('BED_MESH_PROFILE_BASE', mesh)
        def save(command):
            positions.append((sd.file_position, sd.next_file_position, sd.is_active(), sd.is_cmd_from_sd()))
            v.material.cmd_SAVE_PRINT_MESH(command)
        gcode.register_command('_WMP_SAVE_PRINT_MESH', save)
        gcode.register_command('M118', lambda command: markers.append(command.get_raw_command_parameters()))
        gcode.gcode_handlers = gcode.ready_gcode_handlers
        gcode.is_printer_ready = True
        sd.work_handler(0)
    assert positions == [(0, len(first_line.encode()) + 1, True, True)] * 2, (errors, markers)
    assert v.restarts == []
    assert not errors
    assert 'START_PRINT adaptive_mesh' in markers and 'NEXT_SD_LINE' in markers
    assert macro.variables['print_body_ready'] is True
    if blocker == 'other_pending':
        assert v.path.read_bytes() == before
        assert list(v.path.parent.glob('printer-*.cfg')) == []
        assert not v.material._print_mesh_persisted
        assert set(v.config.status_save_pending) == {'bed_mesh wmp_print', 'extruder'}
    else:
        assert '#*# [bed_mesh wmp_print]' in v.path.read_text()
        assert next(v.path.parent.glob('printer-*.cfg')).read_bytes() == before
        assert v.material._print_mesh_persisted
