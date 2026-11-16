#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a reviewed Moonraker HTTP error patch; never deploy it."""
import ast
import hashlib
from pathlib import Path

EXPECTED = 'a85349700224238cc9d27a4099f568bce340d670cd742052133752f9daa7a2a5'


def candidate(source):
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == 'AuthorizedRequestHandler']
    if len(classes) != 1:
        raise ValueError('Expected one AuthorizedRequestHandler class')
    methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef)
               and n.name == 'write_error']
    if len(methods) != 1:
        raise ValueError('Expected one HTTP write_error method')
    node = methods[0]
    lines = source.splitlines(keepends=True)
    body = ''.join(lines[node.lineno - 1:node.end_lineno])
    if hashlib.sha256(body.replace('\r\n', '\n').encode()).hexdigest() != EXPECTED:
        raise ValueError('Unsupported or already patched Moonraker HTTP error handler')
    # Preserve the complete application error in JSON. HTTP status lines must
    # use a protocol-safe reason, not arbitrary (possibly multiline/Unicode)
    # Klipper messages. set_status without a reason selects Tornado's standard.
    anchor = "        err = {'code': status_code, 'message': self._reason}"
    newline = '\r\n' if '\r\n' in body else '\n'
    body = body.replace(anchor, anchor + newline +
                        '        self.set_status(status_code)', 1)
    lines[node.lineno - 1:node.end_lineno] = [body]
    result = ''.join(lines)
    ast.parse(result)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = candidate(args.source.read_bytes().decode())
    with args.output.open('xb') as stream:
        stream.write(result.encode())
