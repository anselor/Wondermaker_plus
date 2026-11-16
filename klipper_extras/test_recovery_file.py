"""Recovery handoff uses the retained vendor SD loader, without running a print."""
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial

SOURCE = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/virtual_sdcard.py'


@pytest.fixture
def file_machine(tmp_path):
    if not SOURCE.exists():
        pytest.skip('retained vendor SD loader unavailable')
    spec = importlib.util.spec_from_file_location('recovery_vendor_sd', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = []
    sd = module.VirtualSD.__new__(module.VirtualSD)
    sd.sdcard_dirname = str(tmp_path)
    sd.current_file = sd.work_timer = None
    sd.file_position = sd.file_size = 0
    sd.cmd_from_sd = False
    sd.print_stats = NS(reset=lambda: events.append('reset'),
                        set_current_file=lambda name: events.append(('selected', name)))
    def command(name, line, args):
        return NS(error=lambda message: ValueError(message), respond_raw=lambda msg: events.append(('response', msg)),
                  get_int=lambda key, **kwargs: int(args[key]))
    gcode = NS(get_mutex=lambda: NS(test=lambda: True), create_gcode_command=command,
               error=lambda msg: ValueError(msg))
    objects = {'gcode': gcode, 'virtual_sdcard': sd}
    reactor = NS(monotonic=lambda: 1., pause=lambda when: None)
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_reactor=lambda: reactor, send_event=lambda name: events.append(name))
    sd.printer = printer
    sd.gcode = gcode
    material = WMMaterial.__new__(WMMaterial)
    material.printer = printer
    def make(name='job.gcode'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        prefix = '; café\r\n'.encode()
        content = prefix + b'G1 X1\nG1 X2\n'
        path.write_bytes(content)
        return {'file': {'path': name, 'size': len(content), 'modified': path.stat().st_mtime,
                         'sha256': hashlib.sha256(content).hexdigest()}, 'file_position': len(prefix)}, path
    yield material, sd, objects, events, reactor, make
    if sd.current_file is not None:
        sd.current_file.close()


@pytest.mark.parametrize('name', ['job.gcode', 'models/Part One.gcode', 'models/Grün.gcode'])
def test_recovery_loads_exact_nested_file_and_seeks_without_start(file_machine, name):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make(name)
    assert material._recovery_select_file(execution, lambda: None) == {
        'file': name, 'file_position': execution['file_position']}
    assert sd.current_file.readline() == 'G1 X1\n'
    assert sd.file_position == execution['file_position']
    assert ('selected', name) in events
    assert sd.work_timer is None
    assert not any(event[0] == 'response' for event in events if isinstance(event, tuple))


def test_recovery_silences_only_internal_selection_announcements(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    loader = sd._load_file
    def with_notice(command, filename, **kwargs):
        loader(command, filename, **kwargs)
        command.respond_raw('Unrelated loader notice')
    sd._load_file = with_notice
    material._recovery_select_file(execution, lambda: None)
    assert ('response', 'Unrelated loader notice') in events
    assert [x for x in events if isinstance(x, tuple) and x[0] == 'response'] == [
        ('response', 'Unrelated loader notice')]
    # Ordinary file selection still emits the stock announcements.
    events.clear()
    sd._reset_file()
    command = objects['gcode'].create_gcode_command('M23', 'M23 job.gcode', {})
    loader(command, execution['file']['path'])
    assert ('response', 'File selected') in events
    assert any(x[0] == 'response' and x[1].startswith('File opened:')
               for x in events if isinstance(x, tuple))


@pytest.mark.parametrize('offset', [0, -1, True, 2, 999])
def test_recovery_bad_offset_does_not_reset_or_select(file_machine, offset):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    execution['file_position'] = offset
    with pytest.raises(ValueError): material._recovery_select_file(execution, lambda: None)
    assert events == [] and sd.current_file is None


def test_recovery_file_hash_detects_same_metadata_changed_content(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    before = path.stat()
    path.write_bytes(path.read_bytes().replace(b'X1', b'X9'))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(ValueError, match='content changed'):
        material._recovery_select_file(execution, lambda: None)
    assert events == []


def test_recovery_file_refuses_another_selected_file(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    _, other = make('other.gcode')
    sd.current_file = other.open()
    with pytest.raises(ValueError, match='Another selected file'):
        material._recovery_select_file(execution, lambda: None)
    assert not sd.current_file.closed and events == []


def test_recovery_loader_wrong_descriptor_is_rejected(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    _, other = make('other.gcode')
    original = sd._load_file
    def load(*args, **kwargs):
        original(*args, **kwargs)
        sd.current_file.close()
        sd.current_file = other.open()
    sd._load_file = load
    with pytest.raises(ValueError, match='active file changed'):
        material._recovery_select_file(execution, lambda: None)
    assert sd.work_timer is None and sd.file_position == 0


def test_recovery_ignored_seek_is_rejected(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    sd.cmd_M26 = lambda command: None
    with pytest.raises(ValueError, match='seek was not confirmed'):
        material._recovery_select_file(execution, lambda: None)
    assert sd.work_timer is None


def test_recovery_owner_change_during_hash_prevents_selection(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    changed = [False]
    reactor.pause = lambda when: changed.__setitem__(0, True)
    def guard():
        if changed[0]: raise ValueError('owner changed')
    with pytest.raises(ValueError, match='owner changed'):
        material._recovery_select_file(execution, guard)
    assert events == [] and sd.current_file is None


@pytest.fixture
def accounting_machine(file_machine):
    material, sd, objects, events, reactor, make = file_machine
    execution, path = make()
    material._recovery_select_file(execution, lambda: None)
    source = SOURCE.with_name('print_stats.py')
    spec = importlib.util.spec_from_file_location('recovery_vendor_print_stats', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stats = module.PrintStats.__new__(module.PrintStats)
    clock = [1000.]
    extrusion = [75.]
    reactor.monotonic = lambda: clock[0]
    stats.reactor = reactor
    stats.gcode_move = NS(get_status=lambda now: {'position': NS(e=extrusion[0]), 'extrude_factor': 1.})
    stats.reset()
    stats.set_current_file(execution['file']['path'])
    sd.print_stats = objects['print_stats'] = stats
    execution.update(total_duration=541.5, print_duration=500., filament_used=123., job_fingerprint='b' * 16)
    return material, sd, stats, execution, clock, extrusion


def test_recovery_accounting_preserves_elapsed_pause_and_extrusion(accounting_machine):
    material, sd, stats, execution, clock, extrusion = accounting_machine
    assert material._recovery_start_accounting(execution, lambda: None)
    assert sd.work_timer is None
    assert stats.get_status(clock[0])['total_duration'] == 541.5
    assert stats.get_status(clock[0])['print_duration'] == 500.
    assert stats.get_status(clock[0])['filament_used'] == 123.
    # Actual SD worker calls note_start again. It must not erase recovered time.
    stats.note_start()
    clock[0] += 10.
    extrusion[0] += 4.
    state = stats.get_status(clock[0])
    assert (state['total_duration'], state['print_duration'], state['filament_used']) == (551.5, 510., 127.)
    stats.note_pause()
    clock[0] += 20.
    assert stats.get_status(clock[0])['print_duration'] == 510.
    stats.note_start()
    clock[0] += 5.
    stats.note_complete()
    state = stats.get_status(clock[0])
    assert (state['total_duration'], state['print_duration'], state['filament_used']) == (576.5, 515., 127.)
    assert state['state'] == 'complete'


@pytest.mark.parametrize('key,value', [('total_duration', -1), ('total_duration', float('nan')),
    ('print_duration', 600), ('print_duration', -1), ('print_duration', True), ('filament_used', float('inf'))])
def test_recovery_accounting_rejects_invalid_checkpoint_before_start(accounting_machine, key, value):
    material, sd, stats, execution, clock, extrusion = accounting_machine
    execution[key] = value
    with pytest.raises(ValueError): material._recovery_start_accounting(execution, lambda: None)
    assert stats.state == 'standby' and stats.print_start_time is None


@pytest.mark.parametrize('change', ['filename', 'position', 'active', 'already_started'])
def test_recovery_accounting_requires_exact_idle_file(accounting_machine, change):
    material, sd, stats, execution, clock, extrusion = accounting_machine
    if change == 'filename': stats.filename = 'other.gcode'
    elif change == 'position': sd.file_position += 1
    elif change == 'active': sd.work_timer = object()
    else: stats.note_start()
    with pytest.raises(ValueError, match='selected idle checkpoint'):
        material._recovery_start_accounting(execution, lambda: None)
    assert stats.total_duration == 0.


def test_recovery_accounting_does_not_retry_an_unacknowledged_start(accounting_machine):
    material, sd, stats, execution, clock, extrusion = accounting_machine
    original = stats.note_start
    def start():
        original()
        raise RuntimeError('lost start acknowledgement')
    stats.note_start = start
    with pytest.raises(RuntimeError): material._recovery_start_accounting(execution, lambda: None)
    with pytest.raises(ValueError): material._recovery_start_accounting(execution, lambda: None)
    assert sd.work_timer is None and stats.state == 'printing'


@pytest.fixture
def worker_machine(accounting_machine, tmp_path):
    from wm_material import RecoveryAttempt
    material, sd, stats, execution, clock, extrusion = accounting_machine
    material.session_id = 'current'
    material.profile_path = str(tmp_path / 'profile.ini')
    material._restore_recovery_attempt()
    material._recovery_start_accounting(execution, lambda: None)
    reactor = material.printer.get_reactor()
    reactor.NEVER, reactor.NOW = 1e30, 0.
    timers, events = [], []
    def register(callback, when):
        timer = NS(callback=callback, when=when)
        timers.append(timer)
        events.append('registered')
        return timer
    reactor.register_timer = register
    reactor.update_timer = lambda timer, when: (events.append('activated'), setattr(timer, 'when', when))
    reactor.unregister_timer = lambda timer: events.append('unregistered')
    mutex = [True]
    material.printer.lookup_object('gcode').get_mutex = lambda: NS(test=lambda: mutex[0])
    sd.on_error_gcode = NS(render=lambda: 'CANCEL_PRINT')
    def body(now):
        events.append('body')
        sd.work_timer = None
        stats.state = 'complete'
        return reactor.NEVER
    sd.work_handler = body
    request = dict(id='recover', session='current', file=execution['file']['path'], execution_hash='a' * 16)
    review = {'machine': {'session': 'current'}, 'execution_hash': 'a' * 16, 'execution': execution}
    stages = [('start_file', lambda: material._recovery_queue_worker(execution, lambda: None),
               lambda: sd.work_timer is not None)]
    return material, sd, reactor, timers, events, mutex, request, review, stages


def test_recovery_worker_waits_for_persisted_completion_and_mutex_release(worker_machine):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    original = material._recovery_attempt.persist
    def persist(receipt):
        if timers:
            assert timers[0].callback(1.) == reactor.NEVER
        original(receipt)
    material._recovery_attempt.persist = persist
    receipt = material._run_recovery_stages(request, review, stages)
    assert receipt['state'] == 'complete' and events == ['registered', 'activated']
    assert timers[0].callback(1.) == 1.001 and 'body' not in events
    mutex[0] = False
    assert timers[0].callback(2.) == reactor.NEVER
    assert events == ['registered', 'activated', 'body']


@pytest.mark.parametrize('failure', ['persist', 'activate', 'register_lost_reply', 'verify'])
def test_recovery_worker_handoff_failure_never_executes_body(worker_machine, failure):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    if failure == 'persist':
        original = material._recovery_attempt.persist
        def persist(receipt):
            if receipt['state'] == 'complete': raise OSError('disk failed')
            original(receipt)
        material._recovery_attempt.persist = persist
    elif failure == 'activate':
        original = reactor.update_timer
        def activate(timer, when):
            original(timer, when)
            raise RuntimeError('lost activation reply')
        reactor.update_timer = activate
    elif failure == 'register_lost_reply':
        original = reactor.register_timer
        def register(callback, when):
            original(callback, when)
            raise RuntimeError('lost registration reply')
        reactor.register_timer = register
    else:
        stages[0] = (stages[0][0], stages[0][1], lambda: False)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        material._run_recovery_stages(request, review, stages)
    assert material._recovery_attempt.record['state'] == 'unknown'
    mutex[0] = False
    for timer in timers:
        assert timer.callback(2.) == reactor.NEVER
    assert 'body' not in events and sd.work_timer is None
    assert material._recovery_pending_worker is None


def test_recovery_worker_checks_durable_receipt_not_only_memory(worker_machine):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    original = material._recovery_attempt.persist
    material._recovery_attempt.persist = lambda receipt: original(receipt) if receipt['state'] != 'complete' else None
    with pytest.raises(ValueError, match='not persisted'):
        material._run_recovery_stages(request, review, stages)
    assert 'activated' not in events and sd.work_timer is None


def test_recovery_worker_stop_after_final_stage_prevents_activation(worker_machine):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    checks = iter([False, True])
    with pytest.raises(ValueError, match='stopped before worker activation'):
        material._run_recovery_stages(request, review, stages, lambda: next(checks))
    assert sd.work_timer is None and 'activated' not in events
    assert material._recovery_attempt.record['state'] == 'unknown'


def test_recovery_worker_unregister_failure_still_disarms_callback(worker_machine):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    stages[0] = (stages[0][0], stages[0][1], lambda: False)
    def unregister(timer): raise RuntimeError('unregister failed')
    reactor.unregister_timer = unregister
    with pytest.raises(ValueError): material._run_recovery_stages(request, review, stages)
    mutex[0] = False
    assert timers[0].callback(2.) == reactor.NEVER
    assert material._recovery_attempt.record['cleanup']['state'] == 'unknown'
    assert sd.work_timer is None and 'body' not in events


def test_recovery_duplicate_request_does_not_disarm_accepted_worker(worker_machine):
    material, sd, reactor, timers, events, mutex, request, review, stages = worker_machine
    material._run_recovery_stages(request, review, stages)
    with pytest.raises(ValueError, match='already attempted'):
        material._run_recovery_stages(request, review, stages)
    assert sd.work_timer is timers[0]
    mutex[0] = False
    timers[0].callback(2.)
    assert events.count('body') == 1
