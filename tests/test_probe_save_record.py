"""Durable calibration evidence: disposable files only, no automatic recovery."""
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe_save_journal', ROOT / 'klipper_extras/wmp_recovery.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

@pytest.fixture
def evidence(tmp_path):
    record = dict(version=1, session='a'*32, request='b'*32,
                  config_path=str(tmp_path / 'printer.cfg'), section='probe', offset='1.500',
                  autosave={'probe': {'z_offset':'1.500'}, 'extruder': {'pid_kp':'25'}},
                  before_sha256='c'*64)
    return module.ProbeSaveRecord(str(tmp_path / 'probe-save.json')), record


def test_record_survives_new_instance_without_automatic_completion(evidence):
    store, record = evidence
    assert store.read() is None
    store.create(record)
    restarted = module.ProbeSaveRecord(store.path)
    assert restarted.read() == record
    result = restarted.review(record['config_path'], record['autosave'], record['autosave'], {})
    assert result['configuration_matches'] and result['outcome'] == 'review_required'
    assert Path(store.path).exists()


@pytest.mark.parametrize('change', ['offset', 'other_calibration', 'loaded', 'pending', 'path'])
def test_changed_configuration_does_not_verify_save(evidence, change):
    store, record = evidence; store.create(record)
    disk = copy.deepcopy(record['autosave']); loaded = copy.deepcopy(disk); pending = {}
    path = record['config_path']
    if change == 'offset': disk['probe']['z_offset'] = '2.000'
    elif change == 'other_calibration': disk['extruder']['pid_kp'] = '26'
    elif change == 'loaded': loaded['probe']['z_offset'] = '2.000'
    elif change == 'pending': pending['probe'] = {'z_offset':'1.600'}
    else: path += '.other'
    if change == 'path':
        with pytest.raises(ValueError, match='different configuration'): store.review(path, disk, loaded, pending)
    else:
        assert not store.review(path, disk, loaded, pending)['configuration_matches']
    assert store.read() == record


def test_existing_and_corrupt_evidence_are_never_overwritten(evidence):
    store, record = evidence; store.create(record)
    original = Path(store.path).read_bytes()
    for raw in (original, b'broken'):
        Path(store.path).write_bytes(raw)
        with pytest.raises((FileExistsError, ValueError)): store.create(record)
        assert Path(store.path).read_bytes() == raw
    assert not list(Path(store.path).parent.glob('.wmp-probe-save-*'))
    with pytest.raises(ValueError): store.read()


def test_changed_payload_checksum_refuses_review(evidence):
    store, record = evidence; store.create(record)
    envelope = json.loads(Path(store.path).read_text())
    envelope['record']['session'] = 'd'*32
    Path(store.path).write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='checksum'): store.read()


@pytest.mark.parametrize('field,value', [('version', True), ('version', 2), ('session','bad'),
    ('offset','nan'), ('offset','2.0'), ('config_path','relative'), ('autosave',[]), ('before_sha256','bad')])
def test_invalid_evidence_refuses_before_publication(evidence, field, value):
    store, record = evidence; record[field] = value
    with pytest.raises(ValueError): store.create(record)
    assert not Path(store.path).exists()


def test_sync_failure_before_publication_leaves_no_record(evidence, monkeypatch):
    store, record = evidence
    def fail(_): raise OSError('sync failed')
    monkeypatch.setattr(module.os, 'fsync', fail)
    with pytest.raises(OSError): store.create(record)
    assert not Path(store.path).exists()
    assert not list(Path(store.path).parent.glob('.wmp-probe-save-*'))


def test_directory_sync_failure_retains_published_evidence(evidence, monkeypatch):
    store, record = evidence; original = module.os.fsync; calls = []
    def fail_second(fd):
        calls.append(fd)
        if len(calls) == 2: raise OSError('directory sync failed')
        original(fd)
    monkeypatch.setattr(module.os, 'fsync', fail_second)
    with pytest.raises(OSError): store.create(record)
    assert store.read() == record
    with pytest.raises(FileExistsError): store.create(record)


def test_acknowledgement_retains_record_and_never_claims_save(evidence):
    store, record = evidence; store.create(record)
    loaded = copy.deepcopy(record['autosave'])
    review = store.review(record['config_path'], record['autosave'], loaded, {})
    assert review['configuration_matches']
    store.acknowledge(record['config_path'], record['autosave'], loaded, {}, review['review'])
    store.acknowledge(record['config_path'], record['autosave'], loaded, {}, review['review'])
    assert store.read() == record
    assert store.review(record['config_path'], record['autosave'], loaded, {})['outcome'] == 'acknowledged'
    assert len(list(Path(store.path).parent.glob('*.ack'))) == 1


def test_stale_acknowledgement_preserves_hold(evidence):
    store, record = evidence; store.create(record)
    review = store.review(record['config_path'], record['autosave'], record['autosave'], {})
    with pytest.raises(ValueError, match='review changed'):
        store.acknowledge(record['config_path'], record['autosave'], {}, {}, review['review'])
    assert not store.acknowledged(record) and store.read() == record


def test_next_save_archives_acknowledged_evidence(evidence):
    store, record = evidence; store.create(record)
    review = store.review(record['config_path'], record['autosave'], record['autosave'], {})
    store.acknowledge(record['config_path'], record['autosave'], record['autosave'], {}, review['review'])
    next_record = copy.deepcopy(record); next_record['request'] = 'd'*32
    store.create(next_record)
    assert store.read() == next_record and not store.acknowledged(next_record)
    archives = list(Path(store.path).parent.glob('*.record'))
    assert len(archives) == 1
    assert module.ProbeSaveRecord(str(archives[0])).read() == record
    assert store.acknowledged(record)


def test_corrupt_acknowledgement_never_authorizes_replacement(evidence):
    store, record = evidence; store.create(record)
    Path(store.path + '.' + store._digest(record) + '.ack').write_text('{}')
    with pytest.raises(ValueError, match='acknowledgement'): store.create(record)
    assert store.read() == record


def test_acknowledged_request_cannot_be_reused(evidence):
    store, record = evidence; store.create(record)
    review = store.review(record['config_path'], record['autosave'], record['autosave'], {})
    store.acknowledge(record['config_path'], record['autosave'], record['autosave'], {}, review['review'])
    with pytest.raises(ValueError, match='new probe save request'): store.create(record)
    assert store.read() == record


def test_concurrent_new_saves_cannot_overwrite_each_other(evidence):
    from concurrent.futures import ThreadPoolExecutor
    store, record = evidence; store.create(record)
    review = store.review(record['config_path'], record['autosave'], record['autosave'], {})
    store.acknowledge(record['config_path'], record['autosave'], record['autosave'], {}, review['review'])
    def publish(identity):
        item = copy.deepcopy(record); item['request'] = identity * 32
        try:
            module.ProbeSaveRecord(store.path).create(item)
            return identity
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(publish, ('d', 'e')))
    winners = [identity for identity in result if identity]
    assert len(winners) == 1 and store.read()['request'] == winners[0] * 32
    assert len(list(Path(store.path).parent.glob('*.record'))) == 1


@pytest.mark.parametrize('change', ['offset', 'pid', 'pending', 'unloaded', 'invalid'])
def test_explicit_retention_only_accepts_reviewed_offset_change(evidence, change):
    store, record = evidence; store.create(record)
    disk = copy.deepcopy(record['autosave']); disk['probe']['z_offset'] = '2.000'
    loaded = copy.deepcopy(disk); pending = {}
    if change == 'pid': disk['extruder']['pid_kp'] = loaded['extruder']['pid_kp'] = '26'
    if change == 'pending': pending = {'probe': {'z_offset':'3.0'}}
    if change == 'unloaded': loaded['probe']['z_offset'] = '1.500'
    if change == 'invalid': disk['probe']['z_offset'] = loaded['probe']['z_offset'] = 'nan'
    review = store.review(record['config_path'], disk, loaded, pending)
    assert review['retainable'] is (change == 'offset')
    original = Path(store.path).read_bytes()
    if change == 'offset':
        store.acknowledge(record['config_path'], disk, loaded, pending, review['review'], retain=True)
        assert store.acknowledged(record)
        marker = json.loads(Path(store.path + '.' + store._digest(record) + '.ack').read_text())
        assert marker['version'] == 2 and marker['retained_offset'] == '2.000'
    else:
        with pytest.raises(ValueError):
            store.acknowledge(record['config_path'], disk, loaded, pending, review['review'], retain=True)
        assert not store.acknowledged(record)
    assert Path(store.path).read_bytes() == original


def test_review_compares_recorded_disk_and_loaded_values_with_bounded_output(evidence):
    store, record = evidence; store.create(record)
    disk = copy.deepcopy(record['autosave']); loaded = copy.deepcopy(disk)
    disk['probe']['z_offset'] = '2.0'
    loaded['probe']['z_offset'] = '3.0'
    review = store.review(record['config_path'], disk, loaded, {})
    assert review['differences'] == [{'section':'probe', 'key':'z_offset',
        'recorded':'1.500', 'disk':'2.0', 'loaded':'3.0'}]
    assert review['difference_count'] == 1 and not review['pending_changes']
    disk['extra'] = {'field%02d'%n: 'x'*500 for n in range(20)}
    review = store.review(record['config_path'], disk, loaded, {'probe': {'z_offset':'4.0'}})
    assert review['difference_count'] == 21 and len(review['differences']) == 8
    assert review['pending_changes']
    assert all(len(entry['disk']) == 128 and entry['recorded'] is None
               and entry['loaded'] is None for entry in review['differences'])
    assert store.read() == record and not store.acknowledged(record)


@pytest.mark.parametrize('change', ['offset', 'pid', 'loaded', 'pending'])
def test_ack_requires_matching_configuration_at_persistence_boundary(evidence, change):
    store, record = evidence
    store.create(record)
    disk = copy.deepcopy(record['autosave'])
    loaded = copy.deepcopy(disk)
    pending = {}
    if change == 'offset':
        disk['probe']['z_offset'] = loaded['probe']['z_offset'] = '2.000'
    elif change == 'pid':
        disk['extruder']['pid_kp'] = loaded['extruder']['pid_kp'] = '26'
    elif change == 'loaded':
        loaded['probe']['z_offset'] = '2.000'
    else:
        pending = {'probe': {'z_offset': '2.000'}}
    review = store.review(record['config_path'], disk, loaded, pending)
    assert not review['configuration_matches']
    before = Path(store.path).read_bytes()
    with pytest.raises(ValueError, match='does not match'):
        store.acknowledge(record['config_path'], disk, loaded, pending, review['review'])
    assert not store.acknowledged(record)
    assert Path(store.path).read_bytes() == before
