# SPDX-License-Identifier: GPL-3.0-or-later
"""Durable replacement of private WM+ state files.

Callers own serialization, admission, record schemas, and result handling.
This primitive does not preserve permissions of an existing destination and must
not be used to replace user-owned printer configuration or create-only archives.
"""
import os
import tempfile


def atomic_write(path, payload, prefix):
    """Publish text or bytes, then sync the parent; clean temporary files on error."""
    parent = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=prefix, dir=parent)
    try:
        with os.fdopen(fd, "wb" if isinstance(payload, bytes) else "w") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
