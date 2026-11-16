import json
import os
from pathlib import Path

import pytest

from wmp_recovery_retirement import EvidenceStore, fingerprint


@pytest.fixture
def evidence(tmp_path):
    managed, native = tmp_path / 'managed', tmp_path / 'native'
    managed.mkdir()
    native.mkdir()
    (managed / 'wmp_recovery_job.json').write_bytes(b'{broken\xff')
    (managed / 'wmp_recovery_execution.json').write_bytes(b'')
    (native / 'plr_dataA.ini').write_bytes(b'legacy checkpoint\r\n')
    return EvidenceStore(managed, native)


def originals(store):
    return {name: Path(path).read_bytes() if os.path.isfile(path) else None
            for name, (path, _) in store.files.items()}


def test_retired_attempt_does_not_retire_new_job(evidence):
    attempt = Path(evidence.files['attempt'][0])
    attempt.write_bytes(b'{broken attempt')
    evidence.retire(evidence.review(), 'discard-1', 'session-1', lambda: None)
    Path(evidence.files['job'][0]).write_bytes(b'new job')
    assert evidence.retirement()['matches'] is False
    assert evidence.retirement(attempt_only=True)['matches'] is True
    # Even identical content at a replacement inode is new evidence.
    replacement = attempt.with_suffix('.new')
    replacement.write_bytes(attempt.read_bytes())
    replacement.replace(attempt)
    assert evidence.retirement(attempt_only=True)['matches'] is False


def test_archive_preserves_raw_empty_and_missing_records(evidence):
    before = originals(evidence)
    review = evidence.review()
    assert review['fingerprint'] == fingerprint(review['manifest'])
    assert review['manifest']['records']['attempt'] == {'present': False}
    assert review['manifest']['records']['execution']['present'] is True
    admissions = []
    receipt = evidence.archive(review, lambda: admissions.append(True))
    assert len(admissions) == 3
    path = os.path.join(evidence.directory, 'wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')
    with open(path) as stream:
        archive = json.load(stream)
    assert archive['manifest'] == review['manifest']
    assert {k: None if v is None else bytes.fromhex(v) for k, v in archive['records'].items()} == before
    assert originals(evidence) == before
    assert evidence.archive(review, lambda: None) == receipt
    assert not list(Path(evidence.directory).glob('.wmp-retirement-*'))


@pytest.mark.parametrize('kind', ['symlink', 'broken-symlink', 'fifo', 'directory', 'oversized'])
@pytest.mark.parametrize('field', ['attempt', 'offer'])
def test_review_refuses_unsafe_file_types(evidence, kind, tmp_path, field):
    from pathlib import Path
    path = Path(evidence.files[field][0])
    if kind in ('symlink', 'broken-symlink'):
        target = tmp_path / 'other'
        if kind == 'symlink': target.write_bytes(b'{}')
        path.symlink_to(target)
    elif kind == 'fifo': os.mkfifo(path)
    elif kind == 'directory': path.mkdir()
    else: path.write_bytes(b'x' * 65537)
    with pytest.raises((ValueError, OSError)):
        evidence.review()


@pytest.mark.parametrize('change', ['replace-identically', 'edit', 'create-missing', 'remove'])
def test_review_cannot_authorize_changed_evidence(evidence, change):
    from pathlib import Path
    review = evidence.review()
    path = Path(evidence.files['job'][0])
    if change == 'replace-identically':
        replacement = path.with_suffix('.new')
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    elif change == 'edit': path.write_bytes(b'new job')
    elif change == 'create-missing': Path(evidence.files['attempt'][0]).write_bytes(b'{}')
    else: path.unlink()
    before = originals(evidence)
    with pytest.raises(ValueError, match='changed after review'):
        evidence.archive(review, lambda: None)
    assert originals(evidence) == before


@pytest.mark.parametrize('failure', ['file-sync', 'directory-sync', 'admission', 'edit-during-sync'])
def test_archive_failure_does_not_retire_or_rewrite(evidence, monkeypatch, failure):
    from pathlib import Path
    review = evidence.review()
    before = originals(evidence)
    sync, counts = os.fsync, [0, 0]
    def fsync(fd):
        counts[0] += 1
        if counts[0] == (1 if failure == 'file-sync' else 2) and failure.endswith('sync') and failure != 'edit-during-sync':
            raise OSError('sync failure')
        if failure == 'edit-during-sync' and counts[0] == 2:
            Path(evidence.files['job'][0]).write_bytes(b'new evidence')
        return sync(fd)
    def admit():
        counts[1] += 1
        if failure == 'admission' and counts[1] == 2:
            raise ValueError('ownership changed')
    monkeypatch.setattr(os, 'fsync', fsync)
    with pytest.raises((OSError, ValueError)):
        evidence.archive(review, admit)
    after = originals(evidence)
    if failure == 'edit-during-sync':
        assert after.pop('job') == b'new evidence'
        before.pop('job')
    assert after == before
    # An immutable orphan archive is harmless; no retirement authority exists.
    assert not list(Path(evidence.directory).glob('.wmp-retirement-*'))
    assert not (Path(evidence.directory) / 'wmp_recovery_retirement.json').exists()


def test_retirement_survives_restart_and_retries_without_rewriting(evidence):
    before = originals(evidence)
    review = evidence.review()
    receipt = evidence.retire(review, 'discard-1', 'session-1', lambda: None)
    assert receipt['matches'] is True
    stat_before = os.stat(evidence.receipt_path)
    assert evidence.retire(review, 'discard-1', 'session-1', lambda: None) == receipt
    assert os.stat(evidence.receipt_path).st_mtime_ns == stat_before.st_mtime_ns
    restarted = EvidenceStore(evidence.directory, Path(evidence.files['checkpoint_A'][0]).parent)
    assert restarted.retirement() == receipt
    assert originals(evidence) == before


@pytest.mark.parametrize('change', ['edited', 'identical-replacement', 'missing-created'])
def test_retirement_never_applies_to_replaced_evidence(evidence, change):
    review = evidence.review()
    evidence.retire(review, 'discard-1', 'session-1', lambda: None)
    path = Path(evidence.files['job'][0])
    if change == 'edited': path.write_bytes(b'new job')
    elif change == 'missing-created': Path(evidence.files['attempt'][0]).write_bytes(b'{}')
    else:
        other = path.with_suffix('.new')
        other.write_bytes(path.read_bytes())
        other.replace(path)
    assert evidence.retirement()['matches'] is False
    with pytest.raises(ValueError, match='identity was reused'):
        evidence.retire(review, 'discard-1', 'session-1', lambda: None)


@pytest.mark.parametrize('damage', ['receipt', 'archive', 'missing-archive'])
def test_damaged_retirement_never_counts_as_authority(evidence, damage):
    receipt = evidence.retire(evidence.review(), 'discard-1', 'session-1', lambda: None)
    archive = Path(evidence.directory) / ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')
    if damage == 'receipt': Path(evidence.receipt_path).write_text('{}')
    elif damage == 'archive': archive.write_text('{}')
    else: archive.unlink()
    with pytest.raises(ValueError): evidence.retirement()


@pytest.mark.parametrize('stage', [3, 4])
def test_receipt_sync_failure_is_not_reported_as_success(evidence, monkeypatch, stage):
    before = originals(evidence)
    sync, calls = os.fsync, []
    def fail(fd):
        calls.append(fd)
        if len(calls) == stage: raise OSError('receipt sync failed')
        return sync(fd)
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError, match='receipt sync failed'):
        evidence.retire(evidence.review(), 'discard-1', 'session-1', lambda: None)
    assert originals(evidence) == before
    # Before replace there is no receipt. After replace it may be durable;
    # the caller must query its identity instead of replaying the operation.
    if stage == 3: assert evidence.retirement() is None
    else: assert evidence.retirement()['id'] == 'discard-1'


def test_another_receipt_invalidates_old_review(evidence):
    review = evidence.review()
    evidence.retire(review, 'discard-1', 'session-1', lambda: None)
    with pytest.raises(ValueError, match='changed after review'):
        evidence.retire(review, 'discard-2', 'session-1', lambda: None)
    assert evidence.retirement()['id'] == 'discard-1'


def test_native_offer_is_preserved_exactly_and_bound_to_review(evidence):
    offer = Path(evidence.files['offer'][0])
    original = b'[plr_print]\r\nwas_interrupted=True\r\nplr_file=old.gcode\r\n'
    offer.write_bytes(original)
    review = evidence.review()
    receipt = evidence.archive(review, lambda: None)
    archive = json.loads((Path(evidence.directory) /
        ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')).read_bytes())
    assert bytes.fromhex(archive['records']['offer']) == original
    assert offer.read_bytes() == original
    offer.write_bytes(original.replace(b'old.gcode', b'new.gcode'))
    with pytest.raises(ValueError, match='changed after review'):
        evidence.retire(review, 'discard-offer', 'session-1', lambda: None)
    assert not Path(evidence.receipt_path).exists()


@pytest.mark.parametrize('present', [False, True])
def test_older_retirement_receipt_cannot_retire_unreviewed_native_offer(evidence, present):
    import hashlib
    from wmp_recovery_retirement import canonical
    offer_path, _ = evidence.files['offer']
    attempt = Path(evidence.files['attempt'][0])
    attempt.write_bytes(b'{legacy attempt')
    manifest, data = evidence.snapshot()
    del manifest['records']['offer']
    del data['offer']
    archive = canonical({'version': 1, 'manifest': manifest,
        'records': {k: None if v is None else v.hex() for k, v in data.items()}})
    digest = hashlib.sha256(archive).hexdigest()
    (Path(evidence.directory) / ('wmp_recovery_retirement_archive_' + digest + '.json')).write_bytes(archive)
    receipt = dict(version=1, id='old-discard', session='old-session',
                   archive=digest, fingerprint=fingerprint(manifest))
    Path(evidence.receipt_path).write_bytes(canonical(receipt))
    raw_receipt = Path(evidence.receipt_path).read_bytes()
    if present:
        Path(offer_path).write_bytes(b'[plr_print]\nwas_interrupted=True\nplr_file=old.gcode\n')
    current = EvidenceStore(evidence.directory, Path(offer_path).parent)
    assert current.retirement()['matches'] is (not present)
    assert current.retirement(attempt_only=True)['matches'] is True
    assert Path(evidence.receipt_path).read_bytes() == raw_receipt
    assert current.retirement()['archive'] == receipt['archive']


def native_offer(evidence):
    path = Path(evidence.files['offer'][0])
    path.write_bytes(b'[plr_print]\r\nwas_interrupted=True\r\nplr_file=old.gcode\r\n')
    return path


def test_raw_retirement_clears_only_reviewed_offer_and_survives_restart(evidence):
    offer = native_offer(evidence)
    before = originals(evidence)
    review = evidence.review()
    receipt = evidence.retire(review, 'discard', 'session', lambda: None)
    assert receipt['version'] == 2 and receipt['matches'] is True
    assert originals(evidence) == dict(before, offer=before['offer'].replace(b'True', b'False'))
    archive = json.loads((Path(evidence.directory) /
        ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')).read_bytes())
    assert {k: None if v is None else bytes.fromhex(v) for k, v in archive['records'].items()} == before
    restarted = EvidenceStore(evidence.directory, offer.parent)
    assert restarted.retirement() == receipt
    stamp = offer.stat().st_mtime_ns
    assert restarted.retire(review, 'discard', 'session', lambda: None) == receipt
    assert offer.stat().st_mtime_ns == stamp
    offer.write_bytes(b'[plr_print]\nwas_interrupted=True\nplr_file=new.gcode\n')
    assert restarted.retirement()['matches'] is False


def test_archival_only_receipt_does_not_claim_native_offer_was_cleared(evidence):
    from wmp_recovery_retirement import canonical
    offer = native_offer(evidence)
    review = evidence.review()
    archived = evidence.archive(review, lambda: None)
    Path(evidence.receipt_path).write_bytes(canonical(dict(archived, version=1,
        id='old-discard', session='old-session')))
    assert evidence.retirement()['matches'] is False
    assert b'was_interrupted=True' in offer.read_bytes()
    receipt = evidence.retire(evidence.review(), 'new-review', 'session', lambda: None)
    assert receipt['version'] == 2 and receipt['matches'] is True


@pytest.mark.parametrize('stage', [3, 4, 5, 6])
def test_raw_retirement_partial_offer_write_requires_explicit_readback_or_review(evidence, monkeypatch, stage):
    offer = native_offer(evidence)
    before = originals(evidence)
    review = evidence.review()
    sync, calls = os.fsync, []
    def fail(fd):
        calls.append(fd)
        if len(calls) == stage:
            raise OSError('publication interrupted')
        return sync(fd)
    monkeypatch.setattr(os, 'fsync', fail)
    with pytest.raises(OSError, match='publication interrupted'):
        evidence.retire(review, 'discard', 'session', lambda: None)
    monkeypatch.setattr(os, 'fsync', sync)
    archives = list(Path(evidence.directory).glob('wmp_recovery_retirement_archive_*'))
    assert len(archives) == 1
    original_archive = archives[0].read_bytes()
    assert bytes.fromhex(json.loads(original_archive)['records']['offer']) == before['offer']
    if stage == 6:  # Receipt rename happened: read back, never repeat cleanup.
        result = evidence.retirement()
        assert result['matches'] is True
        assert evidence.retire(review, 'discard', 'session', lambda: None) == result
    else:
        assert evidence.retirement() is None
        if stage > 3:
            with pytest.raises(ValueError, match='changed after review'):
                evidence.retire(review, 'discard', 'session', lambda: None)
        result = evidence.retire(evidence.review(), 'reviewed-retry', 'session', lambda: None)
        assert result['matches'] is True
    assert offer.read_bytes() == before['offer'].replace(b'True', b'False')
    assert archives[0].read_bytes() == original_archive
    assert not list(offer.parent.glob('.wmp-retirement-offer-*'))


@pytest.mark.parametrize('raw', [b'', b'[plr_print]\nwas_interrupted=maybe\n',
    b'[plr_print]\nwas_interrupted=True\nwas_interrupted=False\nplr_file=old.gcode\n'])
def test_unrecognized_offer_is_archived_but_never_rewritten(evidence, raw):
    Path(evidence.files['offer'][0]).write_bytes(raw)
    before = originals(evidence)
    with pytest.raises(ValueError, match='native recovery offer'):
        evidence.retire(evidence.review(), 'discard', 'session', lambda: None)
    assert originals(evidence) == before
    assert evidence.retirement() is None
    assert len(list(Path(evidence.directory).glob('wmp_recovery_retirement_archive_*'))) == 1


@pytest.mark.parametrize('stage', [3, 5])
def test_replacement_offer_during_discard_is_never_retired(evidence, monkeypatch, stage):
    offer = native_offer(evidence)
    original = offer.read_bytes()
    replacement = b'[plr_print]\nwas_interrupted=True\nplr_file=another.gcode\n'
    review = evidence.review()
    sync, calls = os.fsync, []
    def replace(fd):
        calls.append(fd)
        if len(calls) == stage:
            offer.write_bytes(replacement)
        return sync(fd)
    monkeypatch.setattr(os, 'fsync', replace)
    with pytest.raises(ValueError, match='changed'):
        evidence.retire(review, 'discard', 'session', lambda: None)
    assert offer.read_bytes() == replacement
    assert evidence.retirement() is None
    archive = next(Path(evidence.directory).glob('wmp_recovery_retirement_archive_*'))
    assert bytes.fromhex(json.loads(archive.read_bytes())['records']['offer']) == original


@pytest.mark.parametrize('damage', ['missing', 'null', 'invalid-hex'])
def test_new_receipt_requires_valid_original_offer_bytes(evidence, damage):
    import hashlib
    from wmp_recovery_retirement import canonical
    native_offer(evidence)
    receipt = evidence.retire(evidence.review(), 'discard', 'session', lambda: None)
    receipt.pop('matches')
    archive = json.loads((Path(evidence.directory) /
        ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')).read_bytes())
    if damage == 'missing':
        del archive['records']['offer']
        del archive['manifest']['records']['offer']
    else:
        archive['records']['offer'] = None if damage == 'null' else 'zz'
    payload = canonical(archive)
    receipt.update(archive=hashlib.sha256(payload).hexdigest(), fingerprint=fingerprint(archive['manifest']))
    (Path(evidence.directory) / ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')).write_bytes(payload)
    Path(evidence.receipt_path).write_bytes(canonical(receipt))
    with pytest.raises(ValueError):
        evidence.retirement()

@pytest.mark.parametrize('offer', [False, True])
def test_archive_failure_retirement_is_truthful_and_bound(evidence, monkeypatch, offer):
    if offer:
        Path(evidence.files['offer'][0]).write_text('[plr_print]\nwas_interrupted=True\nplr_file=part.gcode\n')
    def fail(*args): raise OSError('archive unavailable')
    monkeypatch.setattr(evidence, 'archive', fail)
    result = evidence.retire(evidence.review(), 'discard-no-archive', 'session-1', lambda: None)
    assert result['version'] == 3 and result['matches']
    assert 'archive' not in result and result['archive_warning'] == 'archive unavailable'
    assert evidence.retirement() == result
    if offer:
        assert b'was_interrupted=False' in Path(evidence.files['offer'][0]).read_bytes()
    Path(evidence.files['job'][0]).write_bytes(b'replacement job')
    assert not evidence.retirement()['matches']


def test_archive_failure_does_not_hide_required_receipt_failure(evidence, monkeypatch):
    def fail(*args): raise OSError('storage unavailable')
    monkeypatch.setattr(evidence, 'archive', fail)
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='storage unavailable'):
        evidence.retire(evidence.review(), 'discard-no-archive', 'session-1', lambda: None)
    assert evidence.retirement() is None


def test_conflicting_diagnostic_archive_does_not_veto_discard(evidence):
    archived = evidence.archive(evidence.review(), lambda: None)
    path = Path(evidence.directory) / ('wmp_recovery_retirement_archive_' + archived['archive'] + '.json')
    path.write_bytes(b'corrupt historical archive')
    result = evidence.retire(evidence.review(), 'discard-conflict', 'session-1', lambda: None)
    assert result['version'] == 3 and result['matches']
    assert 'conflicts' in result['archive_warning']
    assert path.read_bytes() == b'corrupt historical archive'


@pytest.mark.parametrize('manifest', ['manifest', 'retired_manifest'])
def test_unarchived_receipt_present_record_requires_complete_binding(evidence, monkeypatch, manifest):
    def fail(*args): raise OSError('archive unavailable')
    monkeypatch.setattr(evidence, 'archive', fail)
    evidence.retire(evidence.review(), 'discard-no-archive', 'session-1', lambda: None)
    path = Path(evidence.receipt_path)
    receipt = json.loads(path.read_bytes())
    receipt[manifest]['records']['job'] = {'present': True}
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='Invalid unarchived retirement record binding'):
        evidence.retirement()


def test_runtime_path_upgrade_preserves_retired_legacy_identity(evidence):
    evidence.retire(evidence.review(), 'discard-legacy', 'session-1', lambda: None)
    before=evidence.snapshot()
    native=Path(evidence.files['checkpoint_A'][0]).parent
    upgraded=EvidenceStore(evidence.directory,native,runtime_directory=native)
    assert upgraded.snapshot()==before
    assert upgraded.retirement()['matches']
    assert upgraded.files['execution']==evidence.files['execution']


def test_runtime_retirement_uses_runtime_authority_not_legacy(evidence):
    native=Path(evidence.files['checkpoint_A'][0]).parent
    runtime=native/'wmp_recovery_execution.json'
    runtime.write_bytes(b'new runtime evidence')
    upgraded=EvidenceStore(evidence.directory,native,runtime_directory=native)
    assert Path(upgraded.files['execution'][0])==runtime
    upgraded.retire(upgraded.review(),'discard-runtime','session-1',lambda:None)
    Path(evidence.files['execution'][0]).write_bytes(b'legacy remains irrelevant')
    assert EvidenceStore(evidence.directory,native,runtime_directory=native).retirement()['matches']


def test_existing_invalid_runtime_never_falls_back_to_legacy(evidence,tmp_path):
    native=Path(evidence.files['checkpoint_A'][0]).parent
    (native/'wmp_recovery_execution.json').symlink_to(tmp_path/'missing')
    upgraded=EvidenceStore(evidence.directory,native,runtime_directory=native)
    with pytest.raises(OSError): upgraded.snapshot()



def test_unreadable_runtime_does_not_select_older_legacy(evidence,monkeypatch):
    from wmp_recovery_retirement import runtime_evidence_path
    legacy=evidence.files['execution'][0]
    native=Path(evidence.files['checkpoint_A'][0]).parent
    runtime=str(native/'wmp_recovery_execution.json')
    actual=os.lstat
    def blocked(path,*args,**kwargs):
        if str(path)==runtime: raise PermissionError('runtime inaccessible')
        return actual(path,*args,**kwargs)
    monkeypatch.setattr(os,'lstat',blocked)
    with pytest.raises(PermissionError,match='runtime inaccessible'):
        runtime_evidence_path(legacy,runtime)
    with pytest.raises(PermissionError,match='runtime inaccessible'):
        EvidenceStore(evidence.directory,native,runtime_directory=native)
