#!/usr/bin/env python3
"""Stable diagnostic identity for native source inputs (not an artifact hash)."""
import hashlib
from pathlib import Path
import sys


def build_id(root):
    inputs = [root / 'client-preload/openace-compat/wmp_openace_compat.c']
    for folder in ('client-preload/unified-ui', 'client-preload/openace-compat/screen1113/source'):
        inputs.extend(p for p in (root / folder).rglob('*')
                      if p.is_file() and p.suffix in ('.hpp', '.cpp', '.h', '.c', '.sh', '.py', '.json'))
    digest = hashlib.sha256()
    for path in sorted(set(inputs)):
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:16]


if __name__ == '__main__':
    print(build_id(Path(sys.argv[1])))
