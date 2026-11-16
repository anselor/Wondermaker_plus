# SPDX-License-Identifier: GPL-3.0-or-later
"""Observations shared only within one synchronous status publication."""
import copy
from functools import wraps


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
        return copy.deepcopy(cache[key])
    return observe

