"""Review export integrity, independently of printer activation or ARM execution."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('review_package', ROOT / 'tools/package_unified_ui_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


@pytest.fixture
def inputs(tmp_path):
    repo, candidate = tmp_path / 'repo', tmp_path / 'candidate'
    candidate.mkdir()
    paths = ['LICENSE', 'client-preload/unified-ui/README.md', 'docs/ui/workflow-review.md',
             'docs/ui/native-readiness.md', 'docs/ui/backend-integration-decisions.md', 'docs/ui/activation-proposal.md',
             'docs/ui/standalone-toolhead-procedure.md', 'docs/ui/openace-drying-handoff.md',
             'tools/package_unified_ui_review.py', 'tests/test_unified_ui.py',
             'tests/test_unified_ui_review_package.py',
             'klipper_extras/test_wm_material.py', 'tests/test_config_macros.py',
             'tests/test_print_recovery.py', 'tests/test_stock_pid_selection.py',
             'tests/test_runout_sensor_callbacks.py',
             'tests/test_calibration_commands.py', 'tests/test_stock_calibration_worker.py',
             'client-preload/unified-ui/model.hpp', 'klipper_extras/wm_material.py']
    paths.extend(review.RUNTIME_INPUTS)
    for path in set(paths):
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text('review fixture: ' + path)
    artifact = candidate / 'libwmp_unified_screen_candidate.so'
    artifact.write_bytes(b'test artifact, not an executable')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'scope': 'unified-native-development-candidate', 'activated': False,
                'toolchain_image': 'sha256:test-image',
                'artifact': {'path': artifact.name, 'sha256': digest(artifact)},
                'source_inputs': {'client-preload/unified-ui/model.hpp': digest(repo / 'client-preload/unified-ui/model.hpp')},
                'runtime_dependencies': {name: digest(repo / name) for name in review.RUNTIME_INPUTS}}
    (candidate / 'manifest.json').write_text(json.dumps(manifest))
    return repo, candidate, tmp_path / 'review.tar.gz'


def test_archive_is_reproducible_and_hash_bound(inputs):
    repo, candidate, output = inputs
    first = review.package(repo, candidate, output)
    assert review.package(repo, candidate, output) == first
    with tarfile.open(output) as archive:
        record = json.load(archive.extractfile('review-manifest.json'))
        assert record['activation_authorized'] is False
        assert record['installable_bundle'] is False
        for name, entry in record['files'].items():
            data = archive.extractfile(name).read()
            assert len(data) == entry['size']
            assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert archive.extractfile('repo/klipper_extras/wm_material.py').read() == (repo / 'klipper_extras/wm_material.py').read_bytes()
        for name in ('test_print_recovery.py','test_stock_pid_selection.py','test_runout_sensor_callbacks.py','test_calibration_commands.py','test_stock_calibration_worker.py'):
            assert archive.extractfile('repo/tests/'+name).read() == (repo/'tests'/name).read_bytes()
        assert all(member.isfile() and not member.name.startswith('/') and '..' not in member.name.split('/') for member in archive.getmembers())


@pytest.mark.parametrize('kind', ['artifact', 'source', 'runtime'])
def test_changed_bytes_refuse_without_replacing_previous_export(inputs, kind):
    repo, candidate, output = inputs
    review.package(repo, candidate, output)
    previous = output.read_bytes()
    target = {'artifact': candidate / 'libwmp_unified_screen_candidate.so',
              'source': repo / 'client-preload/unified-ui/model.hpp',
              'runtime': repo / 'klipper_extras/wm_material.py'}[kind]
    target.write_text('changed after build')
    with pytest.raises(ValueError, match='changed'):
        review.package(repo, candidate, output)
    assert output.read_bytes() == previous


@pytest.mark.parametrize('name', ['../outside', '/outside', 'folder/../outside', 'folder\\outside', 'folder//outside'])
def test_manifest_paths_cannot_escape(inputs, name):
    repo, candidate, output = inputs
    path = candidate / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['source_inputs'] = {name: '0' * 64}
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe manifest path'):
        review.package(repo, candidate, output)
    assert not output.exists()


@pytest.mark.parametrize('missing', review.RUNTIME_INPUTS)
def test_incomplete_runtime_manifest_refuses_without_replacing_export(inputs, missing):
    repo, candidate, output = inputs
    review.package(repo, candidate, output)
    previous = output.read_bytes()
    path = candidate / 'manifest.json'
    manifest = json.loads(path.read_text())
    del manifest['runtime_dependencies'][missing]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Missing required runtime dependencies'):
        review.package(repo, candidate, output)
    assert output.read_bytes() == previous


@pytest.mark.parametrize('name', ['config/live/offset_calibrate.cfg',
                                 'config/live/fz-wipe-nozzle.cfg',
                                 'klipper_extras/wmp_recovery.py'])
def test_calibration_wipe_and_recovery_changes_invalidate_export(inputs, name):
    repo, candidate, output = inputs
    review.package(repo, candidate, output)
    previous = output.read_bytes()
    (repo / name).write_text('changed runtime dependency')
    with pytest.raises(ValueError, match='Build input changed'):
        review.package(repo, candidate, output)
    assert output.read_bytes() == previous


def test_native_manifest_generator_uses_the_same_complete_runtime_contract(tmp_path):
    import subprocess
    import sys
    artifact = tmp_path / 'libwmp_unified_screen_candidate.so'
    artifact.write_bytes(b'manifest-generation fixture; no ELF execution')
    subprocess.run([sys.executable, str(ROOT / 'client-preload/unified-ui/native/manifest.py'),
                    str(ROOT), str(tmp_path), 'sha256:test-image'], check=True, capture_output=True)
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert set(manifest['runtime_dependencies']) == set(review.RUNTIME_INPUTS)
    for name, digest in manifest['runtime_dependencies'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    assert 'client-preload/unified-ui/native/runtime_inputs.py' in manifest['source_inputs']
