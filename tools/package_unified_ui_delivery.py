#!/usr/bin/env python3
"""Export a verified unified screen delivery staging tree; never activate it."""
import argparse
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

import preload_bundle as bundle
from package_unified_ui_review import checked_file, collect, sha


def archive_bytes(files):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as archive:
            for name, data in sorted(files.items()):
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                entry.mode = 0o755 if name.endswith('.sh') else 0o644
                archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def export(repo, candidate, client, output, *, reviewed_release=False):
    repo, candidate, client, output = map(Path, (repo, candidate, client, output))
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; use a new staging directory')
    # collect validates the artifact and every compiled/runtime input first.
    reviewed = collect(repo, candidate)
    profile = json.loads(reviewed['repo/client-preload/unified-ui/native/profile1113.json'])
    client_data = client.read_bytes()
    if sha(client_data) != profile['client_sha256']:
        raise ValueError('Vendor client does not match the compiled native profile')
    manifest = json.loads(reviewed['candidate/manifest.json'])
    files = {name.removeprefix('repo/'): data for name, data in reviewed.items() if name.startswith('repo/')}
    for name in bundle.installer_source_files(repo):
        files[name] = checked_file(repo, name)
    files['tools/preload_bundle.py'] = (repo / 'tools/preload_bundle.py').read_bytes()
    files['tools/factory_defaults.py'] = (repo / 'tools/factory_defaults.py').read_bytes()
    # Exporter/provenance are review context, not compiled binary inputs.
    files['tools/package_unified_ui_delivery.py'] = Path(__file__).read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.wmp-delivery-', dir=output.parent))
    try:
        for name, data in files.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        directory = temporary / bundle.CURRENT_BUNDLE
        directory.mkdir(parents=True)
        artifact = directory / 'screen.so'
        artifact.write_bytes(reviewed['candidate/' + manifest['artifact']['path']])
        inputs = {name: files[name] for name in bundle.current_source_files(temporary)}
        hashes = {name: sha(data) for name, data in sorted(inputs.items())}
        source_manifest = (json.dumps(hashes, indent=2) + '\n').encode()
        source_archive = archive_bytes(inputs)
        (directory / 'source-inputs.json').write_bytes(source_manifest)
        (directory / 'source.tar.gz').write_bytes(source_archive)
        descriptor = {
            'version': 1, 'scope': 'reviewed-delivery' if reviewed_release else 'packaging-control-only',
            'profile': {'firmware': '1.1.13', 'sha256': sha(client_data), 'size': len(client_data)},
            'artifact': dict(file=artifact.name, sha256=sha(artifact.read_bytes()),
                             size=artifact.stat().st_size, **bundle.elf_contract(artifact)),
            'legacy_c_sha256': hashes['client-preload/openace-compat/wmp_openace_compat.c'],
            'source_manifest_sha256': sha(source_manifest),
            'source_archive_sha256': sha(source_archive),
        }
        (directory / 'bundle.json').write_text(json.dumps(descriptor, indent=2) + '\n')
        (directory / 'candidate-manifest.json').write_bytes(reviewed['candidate/manifest.json'])
        (temporary / 'READ-ME.txt').write_text(
            ('Unified WM+ reviewed delivery. Ready for normal installer checks.\n'
             'Release review was explicitly asserted by the exporter operator.\n'
             'This export does not publish or install the package.\n'
             if reviewed_release else
            'Unified WM+ delivery staging tree. Not a released installer.\n'
            'Normal installation rejects this packaging-control-only package.\n'
            'Development qualification requires install preload --qualify-unreleased-screen.\n') +
            'Client, source, loader and backend checks remain required.\n'
            'Installer sources and payload are included for isolated clean-install validation.\n'
            'Runtime config files are matching baselines, not a printer configuration overwrite list.\n'
            'Preserve machine-specific configuration, calibration and filament data.\n')
        bundle.verify_source_binding(temporary)
        os.rename(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, default=Path('analysis/unified-ui-native'))
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewed-release', action='store_true',
                        help='Assert completed release review and export for normal installation; does not publish or install')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        descriptor = export(repo, args.candidate, args.client, args.output,
                            reviewed_release=args.reviewed_release)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
    print('Verified delivery staging tree:', args.output)
    print('Artifact SHA256:', descriptor['artifact']['sha256'])
    print('Scope:', descriptor['scope'])


if __name__ == '__main__':
    main()
