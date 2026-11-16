"""Deposition evidence uses retained vendor Move geometry, before queue dispatch."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import RecoveryDepositionEnvelope


@pytest.fixture
def move():
    source = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/toolhead.py'
    tree = ast.parse(source.read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Move')
    namespace = {'math': math}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(source), 'exec'), namespace)
    head = NS(max_accel=1000., junction_deviation=.02, max_velocity=300., max_accel_to_decel=500.)
    return lambda start, end: namespace['Move'](head, start, end, 10.)


def test_envelope_is_saved_before_new_height_can_be_queued(move):
    events = []
    envelope = RecoveryDepositionEnvelope(lambda r: events.append(('save', r['max_z'])), 'job', 'a' * 64)
    for z in (.2, .4, .9, 1.01, .2, 8.1, 2.):
        envelope.enqueue(move([0, 0, z, 0], [10, 0, z, 1]), lambda m: events.append(('queue', m.end_pos[2])))
    assert [e for e in events if e[0] == 'save'] == [('save', 0.), ('save', 1.), ('save', 2.), ('save', 9.)]
    assert events.index(('save', 9.)) < events.index(('queue', 8.1))
    assert envelope.record['max_z'] == 9.  # Returning to a shorter object cannot lower it.


def test_envelope_excludes_retractions_travel_and_extrude_only_service(move):
    envelope = RecoveryDepositionEnvelope(lambda r: None, 'job', 'a' * 64)
    for start, end in [([0, 0, 300, 0], [10, 0, 300, 0]),
                       ([0, 0, 300, 0], [10, 0, 300, -1]),
                       ([0, 0, 300, 0], [0, 0, 300, 50])]:
        envelope.enqueue(move(start, end), lambda m: None)
    assert envelope.record['max_z'] == 0.
    envelope.enqueue(move([1, 1, 2, 0], [1, 1, 3.2, 1]), lambda m: None)
    assert envelope.record['max_z'] == 4.  # Z+E deposition is included.


def test_envelope_persistence_failure_prevents_move_and_retry(move):
    writes, queued = [], []
    def persist(record):
        if record['max_z'] > 0: raise OSError('disk failed')
        writes.append(record)
    envelope = RecoveryDepositionEnvelope(persist, 'job', 'a' * 64)
    command = move([0, 0, .2, 0], [1, 0, .2, 1])
    with pytest.raises(OSError): envelope.enqueue(command, queued.append)
    with pytest.raises(ValueError): envelope.enqueue(command, queued.append)
    assert not queued and envelope.record['max_z'] == 0.


def test_envelope_queue_failure_keeps_conservative_height_and_blocks_replay(move):
    envelope = RecoveryDepositionEnvelope(lambda r: None, 'job', 'a' * 64)
    def fail(command): raise RuntimeError('partial queue acceptance')
    with pytest.raises(RuntimeError): envelope.enqueue(move([0, 0, 4.1, 0], [1, 0, 4.2, 1]), fail)
    assert envelope.record['max_z'] == 5.
    with pytest.raises(ValueError): envelope.clearance(300., 10.)


def test_envelope_restore_and_clearance_use_actual_endstop(move):
    envelope = RecoveryDepositionEnvelope(lambda r: None, 'job', 'a' * 64)
    envelope.enqueue(move([0, 0, 291, 0], [1, 0, 291, 1]), lambda m: None)
    restored = RecoveryDepositionEnvelope(lambda r: pytest.fail('restore wrote evidence'), 'job', 'a' * 64, envelope.record)
    with pytest.raises(ValueError, match='insufficient'): restored.clearance(300., 10.)
    assert restored.clearance(305., 10.)['available_gap'] == 14.  # Wrong endstop would falsely pass.
    with pytest.raises(ValueError): restored.clearance(305., 10., 5.)


@pytest.mark.parametrize('field,value', [('job_id', 'other'), ('file_sha256', 'b' * 64),
    ('max_z', -1), ('max_z', float('nan')), ('max_z', True), ('version', True)])
def test_envelope_rejects_foreign_or_invalid_evidence(field, value):
    record = {'version': 1, 'job_id': 'job', 'file_sha256': 'a' * 64, 'max_z': 20.}
    record[field] = value
    with pytest.raises(ValueError): RecoveryDepositionEnvelope(lambda r: None, 'job', 'a' * 64, record)


def test_envelope_counts_high_start_of_descending_deposition(move):
    envelope = RecoveryDepositionEnvelope(lambda r: None, 'job', 'a' * 64)
    envelope.enqueue(move([0, 0, 11.2, 0], [1, 0, 2., 1]), lambda m: None)
    assert envelope.record['max_z'] == 12.


def test_envelope_returned_records_cannot_mutate_saved_evidence(move):
    writes = []
    envelope = RecoveryDepositionEnvelope(writes.append, 'job', 'a' * 64)
    envelope.enqueue(move([0, 0, 2.1, 0], [1, 0, 2.1, 1]), lambda m: None)
    writes[-1]['max_z'] = 0.
    assert envelope.record['max_z'] == 3.


@pytest.fixture
def adapter(tmp_path):
    from wm_material import WMMaterial
    material = WMMaterial.__new__(WMMaterial)
    events = []
    queue = NS(add_move=lambda move: events.append(('queue', move.end_pos[2])))
    objects = {'toolhead': NS(lookahead=queue)}
    material.printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                          invoke_shutdown=lambda reason: events.append(('shutdown', reason)))
    material.profile_path = str(tmp_path / 'profiles.ini')
    material.session_id = 'session'
    record = {'id': 'job', 'file': {'sha256': 'a' * 64}}
    return material, queue, objects, events, record


def test_deposition_adapter_passes_unmanaged_motion_and_installs_once(adapter, move):
    material, queue, objects, events, record = adapter
    assert material._install_deposition_observer()
    installed = queue.add_move
    assert material._install_deposition_observer() and queue.add_move is installed
    queue.add_move(move([0, 0, 2, 0], [1, 0, 2, 1]))
    assert events == [('queue', 2)]
    assert not Path(material._deposition_envelope_path()).exists()


def test_deposition_adapter_persists_before_queue_and_survives_restore(adapter, move):
    import json
    material, queue, objects, events, record = adapter
    assert material._begin_deposition_envelope(record)
    queue.add_move(move([0, 0, 8.2, 0], [1, 0, 8.2, 1]))
    saved = json.loads(Path(material._deposition_envelope_path()).read_text())
    assert saved['max_z'] == 9.
    assert material._begin_deposition_envelope(record, saved)
    queue.add_move(move([0, 0, .2, 0], [1, 0, .2, 1]))
    assert material._deposition_envelope.record['max_z'] == 9.


def test_deposition_adapter_failed_write_disables_recovery_but_queues_once(adapter, move):
    material, queue, objects, events, record = adapter
    assert material._begin_deposition_envelope(record)
    def fail(path, value): raise OSError('disk failure')
    material._recovery_storage()._write_recovery_json = fail
    queue.add_move(move([0, 0, 2, 0], [1, 0, 2, 1]))
    assert events == [('queue', 2)]
    assert material._deposition_envelope is None
    assert 'disk failure' in material._print_recovery_error
    assert not Path(material._deposition_envelope_path()).exists()


@pytest.mark.parametrize('owner', ['openace', 'AFC', 'session'])
def test_deposition_adapter_changed_owner_disables_recording_without_blocking_queue(adapter, move, owner):
    material, queue, objects, events, record = adapter
    assert material._begin_deposition_envelope(record)
    if owner == 'session': material.session_id = 'new-session'
    else: objects[owner] = object()
    queue.add_move(move([0, 0, 2, 0], [1, 0, 2, 1]))
    assert events == [('queue', 2)]
    assert material._deposition_envelope is None
    assert 'ownership' in material._print_recovery_error


def test_deposition_adapter_replaced_hook_is_not_silently_wrapped(adapter):
    material, queue, objects, events, record = adapter
    material._install_deposition_observer()
    queue.add_move = lambda move: None
    with pytest.raises(ValueError, match='replaced'): material._install_deposition_observer()


def test_deposition_adapter_new_job_does_not_inherit_old_height(adapter, move):
    material, queue, objects, events, record = adapter
    material._begin_deposition_envelope(record)
    queue.add_move(move([0, 0, 20, 0], [1, 0, 20, 1]))
    material._begin_deposition_envelope({'id': 'next-job', 'file': {'sha256': 'b' * 64}})
    assert material._deposition_envelope.record['max_z'] == 0.


def test_vendor_advanced_position_still_reaches_queue_on_record_failure(adapter, move):
    material, queue, objects, events, record = adapter
    material._begin_deposition_envelope(record)
    source = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/toolhead.py'
    tree = ast.parse(source.read_text())
    toolhead_cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ToolHead')
    method = next(node for node in toolhead_cls.body if isinstance(node, ast.FunctionDef) and node.name == 'move')
    namespace = {'Move': type(move([0, 0, 0, 0], [1, 0, 0, 1]))}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    head = objects['toolhead']
    head.commanded_pos = [0., 0., 2., 0.]
    head.max_accel, head.junction_deviation, head.max_velocity, head.max_accel_to_decel = 1000., .02, 300., 500.
    head.kin = head.extruder = NS(check_move=lambda move: None)
    head.print_time, head.need_check_pause = 0., float('inf')
    def fail(path, value): raise OSError('disk failure')
    material._recovery_storage()._write_recovery_json = fail
    namespace['move'](head, [1., 0., 2., 1.], 10.)
    assert head.commanded_pos == [1., 0., 2., 1.]  # Vendor updates this before enqueue.
    assert events == [('queue', 2.)]
    assert material._deposition_envelope is None


def test_adapter_does_not_retry_or_swallow_genuine_queue_failure(adapter, move):
    material, queue, objects, events, record = adapter
    def fail(command):
        events.append(('partial queue', command.end_pos[2]))
        raise RuntimeError('queue failed')
    queue.add_move = fail
    material._begin_deposition_envelope(record)
    with pytest.raises(RuntimeError, match='queue failed'):
        queue.add_move(move([0, 0, 2, 0], [1, 0, 2, 1]))
    assert events == [('partial queue', 2)]
    assert not getattr(material, '_print_recovery_error', '')
