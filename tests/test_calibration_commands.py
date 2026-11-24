"""Calibration failure latching across independently queued vendor commands."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location('recovery_calibration', Path(__file__).resolve().parents[1] / 'klipper_extras/wmp_recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Command:
    def __init__(self, text, token=''):
        self.token = token
        self.encoded = text.encode().hex()
    def get(self, key, default):
        return self.encoded if key == 'HEX' else self.token if key == 'TOKEN' else default
    error = RuntimeError


class Heater:
    def __init__(self, printer):
        self.printer, self.target_temp, self.control = printer, 0., object()
        self.fail_off = False
    def set_temp(self, target):
        if not target and self.fail_off:
            raise RuntimeError('heater cleanup error')
        if not target and self.target_temp:
            self.printer.off += 1
        self.target_temp = target
    def set_control(self, control):
        old = self.control
        self.control, self.target_temp = control, 0.
        return old
    def alter_target(self, target):
        self.target_temp = target


class Printer:
    def __init__(self):
        self.state, self.paused, self.shutdown, self.fail = 'standby', False, False, 0
        self.sent, self.off, self.handler = [], 0, None
        self.on_run = lambda command: None
        self.objects = {
            'print_stats': SimpleNamespace(get_status=lambda _: {'state': self.state}),
            'pause_resume': SimpleNamespace(get_status=lambda _: {'is_paused': self.paused}),
            'save_variables': SimpleNamespace(get_status=lambda _: {'variables': {'fail_flag': self.fail}}),
            'heaters': SimpleNamespace(turn_off_all_heaters=self.cool,
                heaters={name: Heater(self) for name in ('extruder', 'extruder2', 'heater_bed')}),
        }
    def cool(self):
        self.off += 1
    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)
    def get_reactor(self):
        return SimpleNamespace(monotonic=lambda: 1)
    def is_shutdown(self):
        return self.shutdown
    def invoke_shutdown(self, message):
        self.shutdown = True
        self.shutdown_message = message
    def register_command(self, name, handler, **kwargs):
        self.handler = handler
    def run_script_from_command(self, command):
        self.sent.append(command)
        self.on_run(command)


def isolate_checkpoint_io(runner):
    # These tests isolate command/ownership behavior. Scoped disk publication
    # and rollback use retained config files in test_calibration_checkpoints.py.
    from contextlib import nullcontext
    runner.checkpoints = SimpleNamespace(stage=lambda command, attempt: nullcontext())


def setup():
    printer = Printer()
    runner = module.CalibrationCommands(printer, printer)
    isolate_checkpoint_io(runner)
    runner._heater_ownership = module.CalibrationHeaterOwnership(
        printer.objects['heaters'].heaters, lambda: 'test-dispatch')
    return printer, runner


@pytest.mark.parametrize('error_mode', ['exception', 'soft-flag', 'shutdown'])
def test_failed_stage_blocks_later_heads_dock_and_save(error_mode):
    p, runner = setup()
    def fail(command):
        p.objects['heaters'].heaters['extruder2'].set_temp(220)
        if error_mode == 'exception':
            raise RuntimeError('PID failed')
        if error_mode == 'soft-flag':
            p.fail = -3
        else:
            p.shutdown = True
    p.on_run = fail
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('PID_CALIBRATE HEATER=extruder2 TARGET=220'))
    assert runner.failure and not runner.active and p.off == 1
    p.on_run = lambda command: None
    p.fail, p.shutdown = 0, False  # cannot erase the operation latch via saved state
    for command in ['_WMP_CALIBRATION_TOOL T=3', 'G1 X150 Y150',
                    'NOZZLE_PREPARE S=220 T=0', 'PARK_CURRENT_TOOL', 'SAVE_CONFIG']:
        with pytest.raises(RuntimeError, match='Calibration stopped'):
            runner.cmd_run(Command(command))
    assert len(p.sent) == 1


@pytest.mark.parametrize('command', ['G28', 'G29', 'M400', 'M106 S255',
    'G1 X150 Y150', 'SHAPER_CALIBRATE', '_WMP_CALIBRATION_TOOL T=3',
    'PID_CALIBRATE HEATER=extruder TARGET=220',
    'PID_CALIBRATE HEATER=extruder3 TARGET=220', 'NOZZLE_PREPARE S=220 T=0',
    'NOZZLE_CALIBRATE_TOOL_OFFSET T=3', 'RAPID_MODE T=2', 'PARK_CURRENT_TOOL', 'SAVE_CONFIG'])
def test_successful_verified_commands_pass(command):
    p, runner = setup()
    runner.cmd_run(Command(command))
    assert p.sent == [command] and not runner.failure and not runner.active and p.off == 0


@pytest.mark.parametrize('command', ['G28\nSAVE_CONFIG', 'G1 X0', 'T0',
    'NOZZLE_PREPARE S=999 T=0', '_WMP_CALIBRATION_TOOL T=4',
    'PID_CALIBRATE HEATER=heater_bed TARGET=220', '', 'M112'])
def test_unexpected_commands_latch_without_dispatch(command):
    p, runner = setup()
    with pytest.raises((RuntimeError, ValueError)):
        runner.cmd_run(Command(command))
    assert runner.failure and p.sent == [] and p.off == 0


@pytest.mark.parametrize('field,value', [('state', 'printing'), ('state', 'paused'),
    ('paused', True), ('shutdown', True), ('fail', -3)])
def test_unsafe_entry_never_dispatches_or_changes_heaters(field, value):
    p, runner = setup()
    setattr(p, field, value)
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('G28'))
    assert runner.failure and not p.sent and not p.off


def test_heater_cleanup_failure_shuts_down_without_masking_original_error():
    p, runner = setup()
    heater = p.objects['heaters'].heaters['heater_bed']
    heater.fail_off = True
    def fail(command):
        heater.set_temp(55)
        raise RuntimeError('original calibration error')
    p.on_run = fail
    with pytest.raises(RuntimeError, match='original calibration error'):
        runner.cmd_run(Command('G29'))
    assert p.shutdown and 'heater cleanup failed' in p.shutdown_message
    assert runner.failure == 'original calibration error' and not runner.active
    with pytest.raises(RuntimeError, match='Calibration stopped'):
        runner.cmd_run(Command('SAVE_CONFIG'))
    assert p.sent == ['G29']


@pytest.mark.parametrize('encoded', ['0', 'gg', 'ff', '00', 'aa'*257])
def test_malformed_encoding_is_latched(encoded):
    p, runner = setup()
    command = Command('G28')
    command.encoded = encoded
    with pytest.raises((RuntimeError, ValueError, UnicodeError)):
        runner.cmd_run(command)
    assert runner.failure and not runner.active and not p.sent and not p.off


def test_all_stock_calibration_temperature_presets_are_accepted():
    import hashlib
    import struct
    client = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.is_file():
        pytest.skip('exact vendor client required')
    data = client.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715'
    address = 0x384d0a8  # fila_extrude_temp, 18 signed integers
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    for index in range(count):
        segment = struct.unpack_from('<IIQQQQQQ', data, phoff+index*size)
        if segment[0] == 1 and segment[3] <= address < address+72 <= segment[3]+segment[5]:
            values = struct.unpack_from('<18i', data, segment[2]+address-segment[3])
            break
    else:
        pytest.fail('Stock calibration preset table is not file backed')
    p, runner = setup()
    for temperature in values:
        for head in range(4):
            runner.cmd_run(Command('NOZZLE_PREPARE S=%d T=%d' % (temperature, head)))
    assert len(p.sent) == 72 and not runner.failure


def test_checkpoint_is_published_only_after_successful_completion():
    p, runner = setup()
    token = 'a' * 32
    p.on_run = lambda _: (runner.checkpoint == '') or pytest.fail('early acknowledgement')
    runner.cmd_run(Command('M400', token))
    assert runner.checkpoint == token
    p.on_run = lambda _: setattr(p, 'fail', -3)
    with pytest.raises(RuntimeError):
        runner.cmd_run(Command('M400', 'b' * 32))
    assert runner.checkpoint == token
    p.fail = 0
    with pytest.raises(RuntimeError, match='Calibration stopped'):
        runner.cmd_run(Command('M400', 'c' * 32))
    assert runner.checkpoint == token


@pytest.mark.parametrize('command,token', [('G28', 'a'*32), ('M400', 'a'*31), ('M400', 'G'*32)])
def test_invalid_checkpoint_never_executes(command, token):
    p, runner = setup()
    with pytest.raises(RuntimeError, match='Invalid calibration checkpoint'):
        runner.cmd_run(Command(command, token))
    assert not p.sent and not runner.checkpoint and runner.failure


def test_identification_blocks_calibration_before_any_dispatch():
    p, runner = setup()
    runner.identification_blocked = True
    with pytest.raises(RuntimeError, match='head identification'):
        runner.cmd_run(Command('G28'))
    assert not p.sent


def test_save_admission_precedes_write_and_restart_permission_is_scoped():
    p, runner = setup()
    observed = []
    def admit(_):
        observed.append('admit')
        assert not runner.active and not runner._saving
    p.objects['wm_material'] = SimpleNamespace(_restart_requested=admit)
    def write(command):
        observed.append(command)
        assert runner.active and runner._saving
    p.on_run = write
    runner.cmd_run(Command('SAVE_CONFIG'))
    assert observed == ['admit', 'SAVE_CONFIG']
    assert not runner.active and not runner._saving


def test_refused_save_never_dispatches_config_write():
    p, runner = setup()
    def refuse(_):
        raise RuntimeError('Resolve managed operation')
    p.objects['wm_material'] = SimpleNamespace(_restart_requested=refuse)
    with pytest.raises(RuntimeError, match='Resolve managed operation'):
        runner.cmd_run(Command('SAVE_CONFIG'))
    assert not p.sent and not runner.active and not runner._saving


def test_failed_save_clears_restart_permission():
    p, runner = setup()
    def fail(_):
        assert runner._saving
        raise RuntimeError('write failed')
    p.on_run = fail
    with pytest.raises(RuntimeError, match='write failed'):
        runner.cmd_run(Command('SAVE_CONFIG'))
    assert not runner.active and not runner._saving and runner.failure


def test_stock_calibration_cannot_overlap_owned_probe_editor():
    p, runner = setup()
    p.objects['manual_probe'] = SimpleNamespace(status={'is_active': True})
    with pytest.raises(RuntimeError, match='probe editor'):
        runner.cmd_run(Command('G28'))
    assert p.sent == [] and not runner.failure


def test_quick_stop_refuses_calibration_before_dispatch():
    printer, runner = setup()
    printer.quick_stop_flag = True
    with pytest.raises(RuntimeError, match='quick-stop'):
        runner.cmd_run(Command('SAVE_CONFIG'))
    assert printer.sent == [] and not runner.active and printer.off == 0


class AttemptCommand(Command):
    def __init__(self, runner, text, request='a' * 32, sequence=0, session=None):
        super().__init__(text)
        self.binding = {'SESSION': runner.session if session is None else session,
                        'REQUEST': request, 'SEQUENCE': str(sequence)}
    def get(self, key, default):
        return self.binding.get(key, super().get(key, default))


@pytest.mark.parametrize('condition', ['malformed', 'unsupported', 'paused', 'quick_stop', 'probe_busy', 'active', 'save_first'])
def test_bound_clean_refusal_retires_only_attempt(condition):
    p, runner = setup()
    command = AttemptCommand(runner, 'SAVE_CONFIG' if condition == 'save_first' else 'G28')
    if condition == 'malformed': command.encoded = 'xyz'
    if condition == 'unsupported': command.encoded = 'G999'.encode().hex()
    if condition == 'paused': p.paused = True
    if condition == 'quick_stop': p.quick_stop_flag = True
    if condition == 'probe_busy': p.objects['manual_probe'] = SimpleNamespace(status={'is_active': True})
    if condition == 'active': runner.active = True
    with pytest.raises(RuntimeError): runner.cmd_run(command)
    assert not p.sent and not runner.failure and p.off == 0
    if condition == 'active':
        assert runner._attempts['a' * 32]['state'] == 'refused'
    else:
        assert runner.attempt_result['state'] == 'refused'
    if condition == 'active': assert runner.active  # Do not clear another running command.
    runner.active = False
    runner.probe_editor.state = 'idle'
    p.objects.pop('manual_probe', None)
    p.paused = p.quick_stop_flag = False
    for seq, text in enumerate(['G28', '_WMP_CALIBRATION_TOOL T=2', 'SAVE_CONFIG'], 1):
        with pytest.raises(RuntimeError, match='already stopped'):
            runner.cmd_run(AttemptCommand(runner, text, sequence=seq))
    assert not p.sent and not runner.failure
    runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert p.sent == ['G28'] and runner.attempt_result['state'] == 'pending'
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=4))
    assert p.sent == ['G28'] and not runner.failure


@pytest.mark.parametrize('sequence', [1, 2, 999])
def test_missing_initial_stage_cannot_admit_tail(sequence):
    p, runner = setup()
    with pytest.raises(RuntimeError, match='missing'):
        runner.cmd_run(AttemptCommand(runner, 'G28', sequence=sequence))
    assert not p.sent and not runner.failure
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_run(AttemptCommand(runner, 'G28'))


@pytest.mark.parametrize('change', ['session', 'request', 'negative', 'leading_zero'])
def test_bad_attempt_binding_does_not_poison_other_attempt(change):
    p, runner = setup()
    command = AttemptCommand(runner, 'G28')
    if change == 'session': command.binding['SESSION'] = 'b' * 32
    if change == 'request': command.binding['REQUEST'] = 'bad'
    if change == 'negative': command.binding['SEQUENCE'] = '-1'
    if change == 'leading_zero': command.binding['SEQUENCE'] = '00'
    with pytest.raises(RuntimeError, match='binding'): runner.cmd_run(command)
    assert not p.sent and not runner.failure and not runner._attempts
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert p.sent == ['G28']


@pytest.mark.parametrize('mode', ['exception', 'soft_flag', 'later_preflight', 'replay', 'gap'])
def test_bound_execution_failure_stops_old_tail_but_allows_explicit_retry(mode):
    p, runner = setup()
    if mode == 'exception': p.on_run = lambda _: (_ for _ in ()).throw(RuntimeError('motion failed'))
    if mode == 'soft_flag': p.on_run = lambda _: setattr(p, 'fail', -3)
    if mode in ('exception', 'soft_flag'):
        with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'G28'))
        assert p.off == 0  # Failed motion did not own a heater.
    else:
        runner.cmd_run(AttemptCommand(runner, 'G28'))
        if mode == 'later_preflight': p.paused = True
        sequence = 0 if mode == 'replay' else 2 if mode == 'gap' else 1
        with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'M400', sequence=sequence))
    assert runner.failure and not runner.active
    p.on_run = lambda _: None
    p.fail, p.paused = 0, False
    with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=3))
    runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert p.sent == ['G28', 'G28'] and not runner.failure
    with pytest.raises(RuntimeError, match='already stopped'):
        runner.cmd_run(AttemptCommand(runner, 'SAVE_CONFIG', sequence=4))


def test_new_idle_attempt_supersedes_old_pending_without_global_hold():
    p, runner = setup()
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    old = runner.attempt_result
    runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert not runner.failure and old['state'] == 'superseded' and old['executed']
    current = runner.attempt_result
    for text in ['M400', 'SAVE_CONFIG']:
        with pytest.raises(RuntimeError, match='already stopped'):
            runner.cmd_run(AttemptCommand(runner, text, sequence=1))
    assert runner.attempt_result is current and p.sent == ['G28', 'G28']


@pytest.mark.parametrize('state', ['refused', 'pending', 'superseded'])
def test_known_attempt_cannot_downgrade_to_legacy_save(state):
    p, runner = setup()
    if state == 'refused':
        p.paused = True
        with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'G28'))
        p.paused = False
    else:
        runner.cmd_run(AttemptCommand(runner, 'G28'))
        if state == 'superseded': runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    count = len(p.sent)
    save = AttemptCommand(runner, 'SAVE_CONFIG')
    del save.binding['SEQUENCE']
    with pytest.raises(RuntimeError, match='ordered stage binding'): runner.cmd_run(save)
    assert len(p.sent) == count and not runner.failure


@pytest.mark.parametrize('same_request', [True, False])
def test_competing_live_sequence_zero_preserves_executing_attempt(same_request):
    p, runner = setup()
    def during(_):
        original = dict(runner.attempt_result)
        competing = AttemptCommand(runner, 'G28', request=('a' if same_request else 'b') * 32)
        with pytest.raises(RuntimeError, match='already running'): runner.cmd_run(competing)
        assert runner.active and runner.attempt_result == original and not runner.failure
    p.on_run = during
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert p.sent == ['G28'] and not runner.active and not runner.failure


def test_invalid_new_attempt_does_not_supersede_pending_attempt():
    p, runner = setup()
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    old = runner.attempt_result
    p.paused = True
    with pytest.raises(RuntimeError): runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert old['state'] == 'pending' and not runner.failure
    p.paused = False
    runner.cmd_run(AttemptCommand(runner, 'M400', sequence=1))
    assert p.sent == ['G28', 'M400']


def test_new_attempt_rechecks_present_fault_instead_of_old_message():
    p, runner = setup()
    runner.failure = 'Physical docking failure'
    p.fail = -3
    with pytest.raises(RuntimeError, match='Tool change failed'):
        runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert runner.attempt_result['state'] == 'refused' and not p.sent
    p.fail = 0
    runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert p.sent == ['G28'] and not runner.failure

@pytest.mark.parametrize('change,detail', [
    ('printing', 'print_stats.state=printing'),
    ('paused', 'pause_resume.is_paused=True'),
    ('fault', 'fail_flag=-3'),
])
def test_calibration_rejection_names_failed_condition_without_dispatch(change, detail):
    p, runner = setup()
    if change == 'printing': p.state = 'printing'
    elif change == 'paused': p.paused = True
    else: p.fail = -3
    with pytest.raises(RuntimeError) as error:
        runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert detail in str(error.value)
    assert not p.sent and not runner.active and not runner.failure


def test_order_rejection_reports_observed_and_expected_stage():
    p, runner = setup()
    with pytest.raises(RuntimeError, match='SEQUENCE=2; expected 0'):
        runner.cmd_run(AttemptCommand(runner, 'G28', sequence=2))
    assert not p.sent and not runner.failure

@pytest.mark.parametrize('state,review', [('save_review', True), ('accepted', False), ('save_acknowledged', False)])
def test_probe_result_ui_does_not_refuse_unrelated_calibration(state, review):
    p, runner = setup()
    editor = runner.probe_editor
    editor.state, editor.save_review_required = state, review
    editor.request = 'e' * 32
    editor.error = 'Review mismatch does not own machine movement'
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert p.sent == ['G28'] and not runner.active and not runner.failure
    assert editor.state == state and editor.save_review_required == review and editor.request == 'e' * 32


def test_physical_calibration_failure_remains_independent_of_probe_review():
    p, runner = setup()
    runner.probe_editor.state = 'save_review'
    runner.probe_editor.save_review_required = True
    runner.failure = 'Homing failed'
    p.fail = -3
    with pytest.raises(RuntimeError, match='fail_flag=-3'):
        runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert not p.sent and not runner.failure


def test_fresh_attempt_retires_history_but_same_attempt_stops_on_new_fault():
    printer, runner = setup()
    retired = []
    def begin(action):
        retired.append(action)
        printer.fail = 0
    printer.objects['wm_material'] = SimpleNamespace(_begin_explicit_physical_action=begin)
    printer.fail = -3
    runner.cmd_run(AttemptCommand(runner, 'G28'))
    assert retired == ['calibration']
    printer.fail = -3
    with pytest.raises(RuntimeError, match='Tool change failed'):
        runner.cmd_run(AttemptCommand(runner, 'M400', sequence=1))
    assert retired == ['calibration']
    runner.cmd_run(AttemptCommand(runner, 'G28', request='b' * 32))
    assert retired == ['calibration', 'calibration']
