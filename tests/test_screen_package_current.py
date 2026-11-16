"""The committed screen package matches this tree and can be resealed."""
import json
import shutil
from pathlib import Path

import pytest
from test_deploy import deploy  # noqa: F401  Makes the deployment tools importable.
import preload_bundle as bundle
import reseal_screen_package as reseal
from package_unified_ui_review import collect

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / bundle.CURRENT_BUNDLE


def test_committed_package_is_selected_and_matches_this_tree():
    assert bundle.bundle_relative(ROOT) == bundle.CURRENT_BUNDLE
    descriptor = bundle.load_bundle(ROOT)
    assert descriptor['scope'] == 'reviewed-delivery'
    # A failure here means an installer or source file changed after the
    # package was sealed: run tools/reseal_screen_package.py.
    bundle.verify_source_binding(ROOT)
    assert reseal.is_current(ROOT)


def test_package_records_the_shaper_component():
    recorded = json.loads((PACKAGE / 'source-inputs.json').read_text())
    for name in ('tools/components/shaper.py', 'tools/shaper_backport.py',
                 'klipper_backport/input_shaper/klippy/chelper/kin_shaper.c'):
        assert name in recorded


@pytest.fixture
def tree(tmp_path):
    """A copy of the files the package records or was built from."""
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    shutil.copyfile(PACKAGE / 'candidate-manifest.json', candidate / 'manifest.json')
    descriptor = json.loads((PACKAGE / 'bundle.json').read_text())
    shutil.copyfile(PACKAGE / descriptor['artifact']['file'], candidate / reseal.ARTIFACT)
    names = {name[len('repo/'):] for name in collect(ROOT, candidate) if name.startswith('repo/')}
    names.update(bundle.current_source_files(ROOT))
    names.update(str(path.relative_to(ROOT)) for path in PACKAGE.iterdir())
    names.update(('tools/package_unified_ui_delivery.py', 'tools/package_unified_ui_review.py'))
    root = tmp_path / 'tree'
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return root


def test_reseal_of_an_unchanged_tree_changes_nothing(tree):
    before = {path.name: path.read_bytes() for path in (tree / bundle.CURRENT_BUNDLE).iterdir()}
    assert reseal.reseal(tree) == []
    after = {path.name: path.read_bytes() for path in (tree / bundle.CURRENT_BUNDLE).iterdir()}
    assert after == before


def test_changed_installer_file_is_detected_and_resealed(tree):
    package = tree / bundle.CURRENT_BUNDLE
    before = json.loads((package / 'bundle.json').read_text())
    library = (package / before['artifact']['file']).read_bytes()
    with open(tree / 'tools/deploy.py', 'a') as stream:
        stream.write('# changed\n')
    assert not reseal.is_current(tree)
    with pytest.raises(ValueError, match='native source input changed'):
        bundle.verify_source_binding(tree)
    assert reseal.reseal(tree) == ['tools/deploy.py']
    assert reseal.is_current(tree)
    after = json.loads((package / 'bundle.json').read_text())
    assert (package / after['artifact']['file']).read_bytes() == library
    for key in ('version', 'scope', 'profile', 'artifact', 'legacy_c_sha256'):
        assert after[key] == before[key]
    assert after['source_manifest_sha256'] != before['source_manifest_sha256']
    assert bundle.load_bundle(tree) == after


def test_changed_compiled_input_requires_a_rebuild(tree):
    package = tree / bundle.CURRENT_BUNDLE
    manifest = json.loads((package / 'candidate-manifest.json').read_text())
    name = sorted(manifest['source_inputs'])[0]
    before = {path.name: path.read_bytes() for path in package.iterdir()}
    with open(tree / name, 'a') as stream:
        stream.write('\n')
    with pytest.raises(ValueError, match='rebuild before packaging'):
        reseal.reseal(tree)
    assert {path.name: path.read_bytes() for path in package.iterdir()} == before
