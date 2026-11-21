"""Publication restoration must never overwrite a later edit."""
import json
from pathlib import Path
import pytest
from test_deploy import deploy
import preload_bundle as pb


@pytest.fixture
def published(tmp_path):
    stage=tmp_path/'stage'; stage.mkdir()
    lib=tmp_path/'lib'; lib.mkdir()
    old=lib/'libwmp_openace-compat.so'; old.write_bytes(b'previous')
    new=lib/'libwmp_wifi-fix.so'
    drop=tmp_path/'override'; drop.write_bytes(b'old override')
    outputs={}
    for path in (old,new):
        source=stage/path.name; source.write_bytes(b'candidate '+path.name.encode())
        outputs[path.name]={'file':path.name,'sha256':pb.digest(source)}
    (stage/'outputs.json').write_text(json.dumps(outputs))
    pb.publish_stage(stage,lib,drop)
    return stage,old,new,drop


def test_restore_repeatable_and_removes_only_new_file(published):
    stage,old,new,drop=published
    for _ in range(2):
        pb.restore_publication(stage)
        assert old.read_bytes()==b'previous'
        assert not new.exists()
        assert drop.read_bytes()==b'old override'


@pytest.mark.parametrize('index',[1,2,3])
def test_concurrent_edit_refuses_before_any_restore(published,index):
    paths=list(published); stage=paths[0]
    paths[index].write_bytes(b'operator change')
    before={p:p.read_bytes() for p in paths[1:]}
    with pytest.raises(ValueError,match='concurrent edit'):
        pb.restore_publication(stage)
    assert {p:p.read_bytes() for p in paths[1:]}==before


@pytest.mark.parametrize('kind',['backup','destination-link','backup-link','legacy-journal'])
def test_untrusted_restore_inputs_preserve_published_files(published,tmp_path,kind):
    stage,old,new,drop=published
    row=next(row for row in json.loads((stage/'publication.json').read_text()) if row['target']==str(old))
    saved=stage/row['backup']
    if kind=='backup':
        saved.write_bytes(b'damaged')
    elif kind=='legacy-journal':
        (stage/'publication.json').write_text(json.dumps([{'target':str(old),'backup':'previous-0'}]))
    else:
        path=old if kind=='destination-link' else saved
        other=tmp_path/'outside'; other.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(other)
    before={p:p.read_bytes() for p in (old,new,drop)}
    with pytest.raises(ValueError):
        pb.restore_publication(stage)
    assert {p:p.read_bytes() for p in (old,new,drop)}==before


def test_edit_during_restoration_is_preserved(published,monkeypatch):
    stage,old,new,drop=published
    replace=pb.os.replace
    def edit(source,target):
        replace(source,target)
        if Path(target)==drop:
            old.write_bytes(b'concurrent edit')
    monkeypatch.setattr(pb.os,'replace',edit)
    with pytest.raises(ValueError,match='changed during restoration'):
        pb.restore_publication(stage)
    assert old.read_bytes()==b'concurrent edit'


def test_lost_restore_rename_reply_can_be_retried(published,monkeypatch):
    stage,old,new,drop=published
    replace=pb.os.replace
    def lost(source,target):
        replace(source,target)
        if Path(target)==drop:
            raise OSError('lost rename response')
    monkeypatch.setattr(pb.os,'replace',lost)
    with pytest.raises(OSError,match='lost rename response'):
        pb.restore_publication(stage)
    monkeypatch.setattr(pb.os,'replace',replace)
    pb.restore_publication(stage)
    assert old.read_bytes()==b'previous' and not new.exists()
    assert drop.read_bytes()==b'old override'


def test_existing_publication_journal_cannot_be_overwritten(published):
    stage,old,new,drop=published
    before={p:p.read_bytes() for p in stage.iterdir() if p.is_file()}
    with pytest.raises(ValueError,match='journal already exists'):
        pb.publish_stage(stage,old.parent,drop)
    assert {p:p.read_bytes() for p in stage.iterdir() if p.is_file()}==before


@pytest.mark.parametrize('loss',['journal','before_replace','after_replace'])
def test_publication_checkpoint_and_process_loss(tmp_path,monkeypatch,loss):
    stage=tmp_path/'stage';stage.mkdir()
    lib=tmp_path/'lib';lib.mkdir()
    target=lib/'libwmp_wifi-fix.so';target.write_bytes(b'previous library')
    source=stage/target.name;source.write_bytes(b'candidate library')
    drop=tmp_path/'override';drop.write_bytes(b'previous override')
    (stage/'outputs.json').write_text(json.dumps({target.name:{'file':target.name,'sha256':pb.digest(source)}}))
    replace=pb.os.replace
    def interrupted(src,dst):
        dst=Path(dst)
        if loss=='journal' and dst==stage/'publication.json':
            raise OSError('journal publication failed')
        if dst==target:
            assert (stage/'publication.json').is_file()
            rows=json.loads((stage/'publication.json').read_text())
            assert all(row['backup'] is None or pb.digest(stage/row['backup'])==row['before'] for row in rows)
            if loss=='after_replace':replace(src,dst)
            raise SystemExit('publisher process lost')
        return replace(src,dst)
    monkeypatch.setattr(pb.os,'replace',interrupted)
    if loss=='journal':
        with pytest.raises(OSError,match='journal publication failed'):pb.publish_stage(stage,lib,drop)
        assert not (stage/'publication.json').exists()
        assert not list(stage.glob('.publication-*'))
    else:
        with pytest.raises(SystemExit):pb.publish_stage(stage,lib,drop)
        monkeypatch.setattr(pb.os,'replace',replace)
        pb.restore_publication(stage)
    assert target.read_bytes()==b'previous library'
    assert drop.read_bytes()==b'previous override'


@pytest.mark.parametrize('damage',['missing','empty','truncated'])
def test_missing_or_incomplete_journal_never_claims_restoration(published,damage):
    stage,old,new,drop=published
    journal=stage/'publication.json'
    if damage=='missing':journal.unlink()
    elif damage=='empty':journal.write_text('[]')
    else:journal.write_text('[{"target":')
    before={p:p.read_bytes() for p in (old,new,drop)}
    with pytest.raises(ValueError):pb.restore_publication(stage)
    assert {p:p.read_bytes() for p in (old,new,drop)}==before


@pytest.mark.parametrize('checkpoint', ['file_synced', 'renamed'])
def test_killed_recovery_process_can_resume(published, checkpoint):
    """SIGKILL bypasses finally/exception recovery; retry uses a fresh process."""
    import signal
    import subprocess
    import sys
    stage, old, new, drop = published
    setup = 'import sys; sys.path.insert(0, %r); import preload_bundle as pb\n' % str(Path(pb.__file__).parent)
    crash = setup + '''
import os, signal
from pathlib import Path
checkpoint = sys.argv[2]
original_sync = pb._sync_publication_file
original_replace = pb.os.replace
def sync(path):
    original_sync(path)
    if checkpoint == 'file_synced':
        os.kill(os.getpid(), signal.SIGKILL)
def replace(source, target):
    original_replace(source, target)
    if checkpoint == 'renamed':
        os.kill(os.getpid(), signal.SIGKILL)
pb._sync_publication_file = sync
pb.os.replace = replace
pb.restore_publication(sys.argv[1])
'''
    killed = subprocess.run([sys.executable, '-c', crash, str(stage), checkpoint], capture_output=True, timeout=10)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    retried = subprocess.run([sys.executable, '-c', setup + 'pb.restore_publication(sys.argv[1])', str(stage)], capture_output=True, timeout=10)
    assert retried.returncode == 0, retried.stderr.decode()
    assert old.read_bytes() == b'previous' and not new.exists()
    assert drop.read_bytes() == b'old override'


def test_restore_leaves_unconfirmed_temporary_files_alone(published):
    stage, old, new, drop = published
    leftover = drop.with_name(drop.name + '.wmp-restore')
    leftover.write_bytes(b'unconfirmed partial copy')
    pb.restore_publication(stage)
    assert leftover.read_bytes() == b'unconfirmed partial copy'
    assert old.read_bytes() == b'previous' and not new.exists()
    assert drop.read_bytes() == b'old override'


def test_edit_while_copying_restore_is_preserved(published, monkeypatch):
    stage, old, new, drop = published
    original = pb._sync_publication_file
    def edited(path):
        original(path)
        drop.write_bytes(b'operator change during copy')
    monkeypatch.setattr(pb, '_sync_publication_file', edited)
    with pytest.raises(ValueError, match='changed during restoration'):
        pb.restore_publication(stage)
    assert drop.read_bytes() == b'operator change during copy'
    assert not list(drop.parent.glob('.override.wmp-restore-*'))


@pytest.mark.parametrize('checkpoint', ['before_rename', 'after_rename'])
def test_killed_publication_can_rollback_then_install_again(published, tmp_path, checkpoint):
    import signal
    import shutil
    import subprocess
    import sys
    stage, old, new, drop = published
    pb.restore_publication(stage)
    def fresh_stage(name):
        target = tmp_path / name
        target.mkdir()
        shutil.copy2(stage / 'outputs.json', target / 'outputs.json')
        for row in json.loads((stage / 'outputs.json').read_text()).values():
            shutil.copy2(stage / row['file'], target / row['file'])
        return target
    interrupted = fresh_stage('interrupted')
    setup = 'import sys; sys.path.insert(0, %r); import preload_bundle as pb\n' % str(Path(pb.__file__).parent)
    crash = setup + '''
import os, signal
from pathlib import Path
replace = pb.os.replace
def interrupted_replace(source, target):
    if Path(target) == Path(sys.argv[4]):
        if sys.argv[5] == 'after_rename':
            replace(source, target)
        os.kill(os.getpid(), signal.SIGKILL)
    return replace(source, target)
pb.os.replace = interrupted_replace
pb.publish_stage(sys.argv[1], sys.argv[2], sys.argv[3])
'''
    killed = subprocess.run([sys.executable, '-c', crash, str(interrupted), str(old.parent), str(drop), str(old), checkpoint], capture_output=True, timeout=10)
    assert killed.returncode == -signal.SIGKILL, killed.stderr
    recovered = subprocess.run([sys.executable, '-c', setup + 'pb.restore_publication(sys.argv[1])', str(interrupted)], capture_output=True, timeout=10)
    assert recovered.returncode == 0, recovered.stderr.decode()
    assert old.read_bytes() == b'previous' and not new.exists()
    assert drop.read_bytes() == b'old override'
    retry = fresh_stage('retry')
    pb.publish_stage(retry, old.parent, drop)
    assert old.read_bytes() == (retry / old.name).read_bytes()
    assert new.read_bytes() == (retry / new.name).read_bytes()
    pb.restore_publication(retry)
    assert old.read_bytes() == b'previous' and not new.exists()
    assert drop.read_bytes() == b'old override'
