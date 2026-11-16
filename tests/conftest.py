"""Make installed-style Klipper helper imports available to isolated unit tests."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'klipper_extras'))


import json
import shutil
import pytest


@pytest.fixture(scope='session')
def native_candidate(tmp_path_factory):
    """Use this worktree's sealed artifact, never another branch's dev build."""
    package = Path(__file__).resolve().parents[1]/'client-preload/unified-screen1113'
    candidate = tmp_path_factory.mktemp('sealed-native-candidate')
    descriptor = json.loads((package/'bundle.json').read_text())
    manifest = json.loads((package/'candidate-manifest.json').read_text())
    shutil.copyfile(package/'candidate-manifest.json', candidate/'manifest.json')
    shutil.copyfile(package/descriptor['artifact']['file'], candidate/manifest['artifact']['path'])
    return candidate
