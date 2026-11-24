"""Installed checkout identity is independent of the compiled screen binary."""
import subprocess
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from components.preload import release_identity


def test_checkout_identity_tracks_tag_branch_changes_and_detached_head(tmp_path):
    def git(*args):
        return subprocess.check_output(['git','-C',str(tmp_path),*args],text=True).strip()
    git('init','-b','r4')
    git('config','user.name','Test')
    git('config','user.email','test@example.invalid')
    source=tmp_path/'source';source.write_text('original')
    git('add','source');git('commit','-m','baseline')
    revision=git('rev-parse','--short=8','HEAD')
    assert release_identity(tmp_path)=='r4@'+revision
    archive=tmp_path/'archive';archive.mkdir()
    assert release_identity(archive)==''
    git('tag','r4-test')
    assert release_identity(tmp_path)=='r4-test'
    source.write_text('modified')
    assert release_identity(tmp_path)=='r4-test@'+revision+'+modified'
    git('restore','source');git('tag','-d','r4-test');git('checkout','--detach')
    assert release_identity(tmp_path)=='detached@'+revision


def test_archive_has_no_invented_git_identity(tmp_path):
    assert release_identity(tmp_path)==''
