#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a version-checked cooperative directory-listing patch; never deploy it."""
import ast
import hashlib
from pathlib import Path

EXPECTED = {
    '_handle_directory_request': 'fa0361d588802e7c4a0f4855183839e438d021fe9e4d2bbdb1b4677085dc8b9e',
    '_list_directory': 'ec182e642d40b20653baea15dd8129593b1cfd943993ea8006bdc9eb8831863a',
    'list_dir': '8858dde8972ee95850215c93fc664516bbfacfdf1f2667a325ffb6c6ab322833',
    'get_path_info': '55e6f184bd5deeec06e7c83632414623905337b96f32a888fc6e64d31b034a80',
    'check_reserved_path': '3cee53e82147c0fa2a8c85a92877b1d2de988bde2005fbc791ce8f99558ab684',
}
WRAPPERS = '''    def _list_directory(self, path, root, is_extended=False):
        # Keep the existing synchronous API for internal callers.
        chunks = self._list_directory_chunks(path, root, is_extended)
        while True:
            try:
                next(chunks)
            except StopIteration as result:
                return result.value

    async def _list_directory_async(self, path, root, is_extended=False):
        # The original synchronous handler admitted one scan at a time. Keep
        # that boundary: overlapping per-entry loops otherwise multiply the
        # work ahead of each status callback. Each waiter reads current files
        # when admitted; no listing result is cached or shared.
        lock = getattr(self, '_wmp_directory_scan_lock', None)
        if lock is None:
            lock = self._wmp_directory_scan_lock = asyncio.Lock()
        async with lock:
            chunks = self._list_directory_chunks(path, root, is_extended)
            while True:
                try:
                    next(chunks)
                except StopIteration as result:
                    return result.value
                await asyncio.sleep(0)

'''


# Immutable previous recipe: receipts must validate exact code-owned bytes,
# not merely accept an arbitrary hash-bearing backup during an upgrade.
LEGACY_WRAPPERS = '''    def _list_directory(self, path, root, is_extended=False):
        # Keep the existing synchronous API for internal callers.
        chunks = self._list_directory_chunks(path, root, is_extended)
        while True:
            try:
                next(chunks)
            except StopIteration as result:
                return result.value

    async def _list_directory_async(self, path, root, is_extended=False):
        # Filesystem work must yield so status/command requests can be serviced.
        chunks = self._list_directory_chunks(path, root, is_extended)
        while True:
            try:
                next(chunks)
            except StopIteration as result:
                return result.value
            await asyncio.sleep(0)

'''


def candidate(source):
    return _candidate(source, WRAPPERS)


def legacy_candidate(source):
    return _candidate(source, LEGACY_WRAPPERS)


def _candidate(source, wrappers):
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FileManager']
    if len(classes) != 1:
        raise ValueError('Expected one FileManager class')
    cls = classes[0]
    methods = {n.name: n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if any(n in methods for n in ('_list_directory_async', '_list_directory_chunks')):
        raise ValueError('Directory patch or conflicting methods already present')
    lines = source.splitlines(keepends=True)
    for name, digest in EXPECTED.items():
        node = methods.get(name)
        if node is None:
            raise ValueError('Missing expected method: ' + name)
        body = ''.join(lines[node.lineno - 1:node.end_lineno])
        if hashlib.sha256(body.encode()).hexdigest() != digest:
            raise ValueError('Unsupported Moonraker method: ' + name)
    if not any(isinstance(n, ast.Import) and any(a.name == 'asyncio' for a in n.names) for n in tree.body):
        raise ValueError('Expected asyncio import')
    old = '            dir_info = self._list_directory(dir_path, root, is_extended)'
    if source.count(old) != 1:
        raise ValueError('Unexpected directory request dispatch')
    source = source.replace(old, '            dir_info = await self._list_directory_async(dir_path, root, is_extended)')
    source = source.replace('    def _list_directory(self,\n', wrappers + '    def _list_directory_chunks(self,\n', 1)
    old = '        for fname in os.listdir(path):\n            full_path = os.path.join(path, fname)'
    if source.count(old) != 1:
        raise ValueError('Unexpected directory iteration')
    source = source.replace(old, '        for fname in os.listdir(path):\n            yield\n            full_path = os.path.join(path, fname)')
    ast.parse(source)
    return source


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = candidate(args.source.read_text())
    with args.output.open('x') as stream:
        stream.write(result)
