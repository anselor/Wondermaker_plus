# SPDX-License-Identifier: GPL-3.0-or-later
"""Observations shared only within one synchronous status publication."""
import copy
from functools import wraps

_ATOMIC = frozenset((str, int, float, bool, type(None)))


def copy_status(value):
    """Copy JSON-shaped status trees without deepcopy's object reconstruction.

    These observations contain acyclic records, lists and scalar values. Keep
    tuple metadata intact and defer unfamiliar objects to their copy protocol.
    Command-side snapshots continue to use deepcopy where aliasing can matter.
    """
    kind = type(value)
    if kind in _ATOMIC:
        return value
    if kind is dict:
        return {key: copy_status(item) for key, item in value.items()}
    if kind is list:
        return [copy_status(item) for item in value]
    if kind is tuple:
        return tuple(copy_status(item) for item in value)
    return copy.deepcopy(value)


def _status_observation(method):
    """Reuse an observation only within one synchronous status publication.

    A status contains four heads and eight possible procedures. Re-reading the
    same files and sensors for every branch blocks Klipper's reactor, even when
    all values are unchanged. Live observations expire after the publication;
    loaded profiles have their own save-invalidated snapshot. Command admission
    re-reads profiles, including edits preserving file size and timestamps.
    """
    @wraps(method)
    def observe(self, *args, **kwargs):
        owner = getattr(self, 'material', self)
        cache = getattr(owner, '_status_observation_cache', None)
        if cache is None:
            return method(self, *args, **kwargs)
        key = (method.__name__, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = method(self, *args, **kwargs)
        # Callers may enrich returned records or build an edited profile draft.
        # Neither must mutate the shared observation within this publication.
        return copy_status(cache[key])
    return observe

