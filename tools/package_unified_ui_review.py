#!/usr/bin/env python3
"""Package the exact local native candidate for review; never deploy or activate."""
import argparse
import gzip
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


# Load the same contract used by the native manifest generator, independent of
# the candidate's own claims about which dependencies matter.
_contract_path = Path(__file__).resolve().parents[1] / 'client-preload/unified-ui/native/runtime_inputs.py'
_contract_spec = importlib.util.spec_from_file_location('wmp_runtime_inputs', _contract_path)
_contract = importlib.util.module_from_spec(_contract_spec)
_contract_spec.loader.exec_module(_contract)
RUNTIME_INPUTS = _contract.RUNTIME_INPUTS

def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(root, name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')) or '\\' in name:
        raise ValueError('Unsafe manifest path: ' + name)
    candidate = root.joinpath(*path.parts)
    if not candidate.resolve().is_relative_to(root.resolve()) or candidate.is_symlink():
        raise ValueError('Manifest path escapes source root: ' + name)
    return candidate.read_bytes()


def collect(repo, candidate):
    manifest_bytes = (candidate / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get('scope') != 'unified-native-development-candidate' or manifest.get('activated') is not False:
        raise ValueError('Expected an unactivated unified native candidate')
    missing = set(RUNTIME_INPUTS) - set(manifest.get('runtime_dependencies', {}))
    if missing:
        raise ValueError('Missing required runtime dependencies: ' + ', '.join(sorted(missing)))
    files = {'candidate/manifest.json': manifest_bytes}
    artifact = manifest['artifact']
    if artifact['path'] != 'libwmp_unified_screen_candidate.so':
        raise ValueError('Unexpected candidate artifact name')
    data = checked_file(candidate, artifact['path'])
    if sha(data) != artifact['sha256']:
        raise ValueError('Native artifact changed; rebuild before packaging')
    files['candidate/' + artifact['path']] = data
    for group in ('source_inputs', 'runtime_dependencies'):
        if not isinstance(manifest.get(group), dict) or not manifest[group]:
            raise ValueError('Missing ' + group)
        for name, expected in manifest[group].items():
            data = checked_file(repo, name)
            if sha(data) != expected:
                raise ValueError('Build input changed; rebuild before packaging: ' + name)
            files['repo/' + name] = data
    # Review context is identified separately; it is not claimed as compiled input.
    context = ['LICENSE', 'client-preload/unified-ui/README.md',
               'docs/ui/workflow-review.md', 'docs/ui/native-readiness.md', 'docs/ui/backend-integration-decisions.md', 'docs/ui/activation-proposal.md',
               'docs/ui/standalone-toolhead-procedure.md', 'docs/ui/openace-drying-handoff.md',
               'tools/package_unified_ui_review.py',
               'tests/test_unified_ui.py', 'tests/test_unified_ui_review_package.py',
               'klipper_extras/test_wm_material.py',
               'tests/test_config_macros.py', 'tests/test_print_recovery.py',
               'tests/test_stock_pid_selection.py', 'tests/test_runout_sensor_callbacks.py',
               'tests/test_calibration_commands.py', 'tests/test_stock_calibration_worker.py']
    context.extend(p.relative_to(repo).as_posix() for p in sorted((repo / 'tests/unified_ui').glob('*.cpp')))
    for name in context:
        files['repo/' + name] = checked_file(repo, name)
    record = {'scope': 'unified-native-review-only', 'activation_authorized': False,
              'installable_bundle': False, 'hardware_acceptance': 'outstanding',
              'artifact_sha256': artifact['sha256'], 'toolchain_image': manifest['toolchain_image'],
              'review_context': context,
              'files': {name: {'sha256': sha(data), 'size': len(data)} for name, data in sorted(files.items())}}
    files['review-manifest.json'] = (json.dumps(record, indent=2) + '\n').encode()
    files['READ-ME.txt'] = (
        'Native WM+ screen candidate: review only. Not an install bundle.\n'
        'No printer activation or hardware acceptance is claimed.\n'
        'The source manifest binds the ELF, source inputs and runtime dependencies.\n'
        'Review context files are separately identified and hashed.\n'
        'Build from repo/ using client-preload/unified-ui/native/build-arm.sh with\n'
        'the pinned offline Docker image named in candidate/manifest.json.\n'
        'Read repo/client-preload/unified-ui/README.md for connected and stubbed flows.\n'
        'Do not restart the client to preview this: stock startup restarts Klipper.\n'
    ).encode()
    return files


def package(repo, candidate, output):
    # Read and verify once; archive those exact bytes, not a second filesystem read.
    files = collect(repo, candidate)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0) as zipped:
                with tarfile.open(fileobj=zipped, mode='w') as archive:
                    for name, data in sorted(files.items()):
                        item = tarfile.TarInfo(name)
                        item.size = len(data)
                        item.mode = 0o755 if name.endswith('.sh') else 0o644
                        archive.addfile(item, io.BytesIO(data))
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return sha(output.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    candidate = args.candidate or repo / 'analysis/unified-ui-native'
    output = args.output or candidate / 'review.tar.gz'
    try:
        digest = package(repo, candidate, output)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
    print('Review archive:', output)
    print('SHA256:', digest)


if __name__ == '__main__':
    main()
