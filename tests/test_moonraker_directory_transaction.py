"""Real filesystem publication/recovery checks; no printer or service access."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
import moonraker_directory_transaction as tx
SOURCE = (Path(__file__).parent / 'fixtures/moonraker_directory_compat.py').read_bytes()
TARGET_NAME = 'file_manager.py'


@pytest.fixture(autouse=True, params=('directory', 'http-error'))
def patch_recipe(request, monkeypatch):
    if request.param == 'http-error':
        source = (Path(__file__).parent / 'fixtures/moonraker_http_error_compat.py').read_bytes()
        monkeypatch.setattr(sys.modules[__name__], 'SOURCE', source)
        monkeypatch.setattr(sys.modules[__name__], 'TARGET_NAME', 'application.py')



def setup(tmp_path):
    target = tmp_path / TARGET_NAME
    target.write_bytes(SOURCE)
    target.chmod(0o640)
    return target, tmp_path / 'transaction'


def test_install_reinstall_and_restore_preserve_mode(tmp_path):
    target, state = setup(tmp_path)
    record = tx.prepare(target, state)
    assert tx.status(target, state) == 'original'
    assert tx.transition(target, state)
    assert tx.prepare(target, state) == record
    assert not tx.transition(target, state)
    assert tx.status(target, state) == 'installed'
    assert target.stat().st_mode & 0o777 == 0o640
    assert tx.transition(target, state, restore=True)
    assert not tx.transition(target, state, restore=True)
    assert target.read_bytes() == SOURCE


def test_changed_source_and_corrupt_backup_are_preserved(tmp_path):
    target, state = setup(tmp_path)
    tx.prepare(target, state)
    target.write_bytes(b'operator edit')
    for restore in (False, True):
        with pytest.raises(ValueError, match='changed Moonraker'):
            tx.transition(target, state, restore=restore)
    assert target.read_bytes() == b'operator edit'
    target.write_bytes(SOURCE)
    (state / 'original.py').write_bytes(b'bad backup')
    with pytest.raises(ValueError, match='integrity'):
        tx.transition(target, state)
    assert target.read_bytes() == SOURCE


def test_linked_target_and_foreign_receipt_are_refused(tmp_path):
    target, state = setup(tmp_path)
    linked = tmp_path / 'linked.py'
    linked.symlink_to(target)
    with pytest.raises(ValueError, match='Linked'):
        tx.prepare(linked, state)
    tx.prepare(target, state)
    other = tmp_path / 'other.py'
    other.write_bytes(SOURCE)
    with pytest.raises(ValueError, match='foreign'):
        tx.transition(other, state)
    assert other.read_bytes() == SOURCE


def test_killed_after_publication_recovers_from_fresh_process(tmp_path):
    target, state = setup(tmp_path)
    tx.prepare(target, state)
    marker = tmp_path / 'published'
    script = '''import os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import moonraker_directory_transaction as tx
replace=os.replace
def interrupted(source,destination):
 replace(source,destination)
 if str(destination)==sys.argv[2]:
  Path(sys.argv[4]).write_text('published')
  while True:time.sleep(.1)
os.replace=interrupted
tx.transition(sys.argv[2],sys.argv[3])
'''
    child = subprocess.Popen([sys.executable, '-c', script, str(TOOLS), str(target), str(state), str(marker)])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert marker.exists()
        # A live installer still holds the receipt lock, even after publishing.
        with pytest.raises(BlockingIOError):
            tx.transition(target, state, restore=True)
        child.kill()
        assert child.wait(timeout=5) == -signal.SIGKILL
        recover = 'import sys;sys.path.insert(0,sys.argv[1]);import moonraker_directory_transaction as t;assert t.transition(sys.argv[2],sys.argv[3],restore=True)'
        subprocess.run([sys.executable, '-c', recover, str(TOOLS), str(target), str(state)], check=True)
        assert target.read_bytes() == SOURCE
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_edit_during_staging_is_not_overwritten(tmp_path, monkeypatch):
    target, state = setup(tmp_path)
    tx.prepare(target, state)
    original_fsync = os.fsync
    def editing_fsync(fd):
        if Path('/proc/self/fd/' + str(fd)).readlink().name.startswith('.' + TARGET_NAME + '.wmp-'):
            target.write_bytes(b'operator changed while upload was syncing')
        return original_fsync(fd)
    monkeypatch.setattr(tx.os, 'fsync', editing_fsync)
    with pytest.raises(ValueError, match='changed during publication'):
        tx.transition(target, state)
    assert target.read_bytes() == b'operator changed while upload was syncing'


def test_adopt_reviewed_live_patch_from_original_backup(tmp_path):
    target, state = setup(tmp_path)
    original = tmp_path / 'saved-original.py'
    original.write_bytes(SOURCE)
    target.write_text(tx.reviewed_candidate(target, SOURCE.decode()))
    tx.prepare(target, state, original_backup=original)
    assert tx.status(target, state) == 'installed'
    assert tx.transition(target, state, restore=True)
    assert target.read_bytes() == SOURCE


def test_unrelated_backup_cannot_authorize_source_replacement(tmp_path):
    target, state = setup(tmp_path)
    original = tmp_path / 'wrong-original.py'
    # Supported methods but unrelated module-level code must still be refused.
    original.write_bytes(SOURCE + b'\noperator_value = 42\n')
    with pytest.raises(ValueError, match='does not describe'):
        tx.prepare(target, state, original_backup=original)
    assert target.read_bytes() == SOURCE
    assert not (state / 'receipt.json').exists()


@pytest.mark.parametrize('previously_installed', [False, True])
def test_supported_current_original_gets_new_baseline_preserving_other_edits(tmp_path, previously_installed):
    target,state=setup(tmp_path)
    old=tx.prepare(target,state)
    if previously_installed: tx.transition(target,state)
    updated=SOURCE+b'\n# Unrelated vendor/operator change preserved byte for byte.\n'
    target.write_bytes(updated)
    new=tx.prepare(target,state)
    assert new['old']==tx.digest(updated) and new['old']!=old['old']
    assert target.read_bytes()==updated
    archives=list(state.glob('retired-*'))
    assert len(archives)==1
    assert tx.load_record(target, archives[0])[0]==old
    tx.transition(target,state)
    assert target.read_bytes().endswith(updated.splitlines(keepends=True)[-1])
    tx.transition(target,state,restore=True)
    assert target.read_bytes()==updated


def test_unknown_current_source_never_retires_previous_baseline(tmp_path):
    target,state=setup(tmp_path)
    tx.prepare(target,state)
    before={p.name:p.read_bytes() for p in state.iterdir() if p.is_file()}
    target.write_bytes(b'unknown vendor implementation')
    with pytest.raises((ValueError,SyntaxError)):
        tx.prepare(target,state)
    assert target.read_bytes()==b'unknown vendor implementation'
    assert {p.name:p.read_bytes() for p in state.iterdir() if p.is_file()}==before
    assert not list(state.glob('retired-*'))


def test_interrupted_rebaseline_preserves_archive_and_live_current_source(tmp_path, monkeypatch):
    target,state=setup(tmp_path)
    old=tx.prepare(target,state)
    updated=SOURCE+b'\n# upgraded source\n'
    target.write_bytes(updated)
    write=tx.atomic_write
    def fail(path,*args,**kwargs):
        if path==state/'original.py': raise OSError('interrupted new baseline')
        return write(path,*args,**kwargs)
    monkeypatch.setattr(tx,'atomic_write',fail)
    with pytest.raises(OSError): tx.prepare(target,state)
    assert target.read_bytes()==updated
    assert tx.load_record(target,next(state.glob('retired-*')))[0]==old
    monkeypatch.setattr(tx,'atomic_write',write)
    tx.prepare(target,state)
    tx.transition(target,state)
    tx.transition(target,state,restore=True)
    assert target.read_bytes()==updated
