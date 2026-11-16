#!/usr/bin/env python3
"""Refresh the source record of the committed screen package.

client-preload/unified-screen1113/ holds the built screen library and the
hashes of every installer and source file it is delivered with. The installer
refuses the package when one of those files has changed. Run this after
editing such a file:

    python3 tools/reseal_screen_package.py
    python3 tools/reseal_screen_package.py --check

It rewrites source-inputs.json, source.tar.gz and the two matching digests in
bundle.json. The library, its target client profile and the delivery scope are
kept. It refuses when a file the library was compiled from has changed; that
needs a rebuild and a new export with tools/package_unified_ui_delivery.py.
--check changes nothing and exits 1 when the package is out of date.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preload_bundle as bundle  # noqa: E402
from package_unified_ui_delivery import archive_bytes  # noqa: E402
from package_unified_ui_review import collect, sha  # noqa: E402

ARTIFACT = 'libwmp_unified_screen_candidate.so'


def is_current(repo):
    try:
        bundle.verify_source_binding(repo)
    except ValueError:
        return False
    return True


def reseal(repo):
    """Rewrite the package's source record. Returns the changed file names."""
    repo = Path(repo)
    directory = repo / bundle.CURRENT_BUNDLE
    descriptor = json.loads((directory / 'bundle.json').read_text(encoding='utf-8'))
    library = directory / descriptor['artifact']['file']
    if sha(library.read_bytes()) != descriptor['artifact']['sha256']:
        raise ValueError('screen library does not match bundle.json')
    old = json.loads((directory / 'source-inputs.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary)
        shutil.copyfile(directory / 'candidate-manifest.json', candidate / 'manifest.json')
        shutil.copyfile(library, candidate / ARTIFACT)
        # Refuses when a compiled or runtime input differs from the build record.
        collect(repo, candidate)
    inputs = {name: (repo / name).read_bytes() for name in bundle.current_source_files(repo)}
    hashes = {name: sha(data) for name, data in sorted(inputs.items())}
    source_manifest = (json.dumps(hashes, indent=2) + '\n').encode()
    source_archive = archive_bytes(inputs)
    descriptor['legacy_c_sha256'] = hashes['client-preload/openace-compat/wmp_openace_compat.c']
    descriptor['source_manifest_sha256'] = sha(source_manifest)
    descriptor['source_archive_sha256'] = sha(source_archive)
    for name, data in (('source-inputs.json', source_manifest),
                       ('source.tar.gz', source_archive),
                       ('bundle.json', (json.dumps(descriptor, indent=2) + '\n').encode())):
        staged = directory / (name + '.new')
        staged.write_bytes(data)
        os.replace(staged, directory / name)
    bundle.verify_source_binding(repo)
    return sorted(name for name in set(old) | set(hashes) if old.get(name) != hashes.get(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--check', action='store_true',
                        help='report whether the package is current; change nothing')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if not (repo / bundle.CURRENT_BUNDLE).is_dir():
        parser.exit(1, 'No screen package in this tree.\n')
    if args.check:
        if is_current(repo):
            print('Screen package is current.')
            return 0
        print('Screen package is out of date; run tools/reseal_screen_package.py.',
              file=sys.stderr)
        return 1
    try:
        changed = reseal(repo)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
    print('Screen package resealed; %d recorded file(s) changed.' % len(changed))
    for name in changed:
        print('  ' + name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
