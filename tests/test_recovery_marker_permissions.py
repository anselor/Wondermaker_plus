"""Legacy accessibility upgrades preserve evidence and never grant directory writes."""
import os
from pathlib import Path
import stat
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from preload_bundle import repair_recovery_marker_access


@pytest.fixture
def legacy(tmp_path):
    home=tmp_path/'printer';directory=home/'TM_T1/bin';directory.mkdir(parents=True)
    marker=directory/'plr_dataB.ini.wmp-coordinates'
    marker.write_bytes(b'WMP-PLR-XYZ-1 0123456789abcdef\n');marker.chmod(0o600)
    return home,directory,marker


def test_upgrade_preserves_bytes_inode_ownership_and_directory(legacy):
    home,directory,marker=legacy
    before=marker.stat();payload=marker.read_bytes();parent=directory.stat()
    assert repair_recovery_marker_access(home)==[str(marker)]
    after=marker.stat()
    assert marker.read_bytes()==payload
    assert (before.st_ino,before.st_uid,before.st_gid)==(after.st_ino,after.st_uid,after.st_gid)
    assert stat.S_IMODE(after.st_mode)==0o644
    assert directory.stat().st_mode==parent.st_mode
    assert repair_recovery_marker_access(home)==[]


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo','oversized'])
def test_refuses_untrusted_marker_before_changing_other_marker(legacy,kind):
    home,directory,marker=legacy
    other=directory/'plr_dataA.ini.wmp-coordinates'
    if kind=='symlink':other.symlink_to(marker)
    elif kind=='hardlink':os.link(marker,other)
    elif kind=='fifo':os.mkfifo(other)
    else:other.write_bytes(b'x'*257)
    with pytest.raises((OSError,ValueError)):repair_recovery_marker_access(home)
    assert stat.S_IMODE(marker.stat().st_mode)==0o600


def test_refuses_linked_directory(legacy,tmp_path):
    home,directory,marker=legacy
    alternate=tmp_path/'alternate';directory.rename(alternate);directory.symlink_to(alternate)
    with pytest.raises(OSError):repair_recovery_marker_access(home)
    assert stat.S_IMODE(marker.stat().st_mode)==0o600


def test_missing_markers_are_not_created(legacy):
    home,directory,marker=legacy;marker.unlink()
    assert repair_recovery_marker_access(home)==[]
    assert list(directory.iterdir())==[]
