# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process per-student data cache with mixed TTLs and singleflight.

Why this exists
---------------
Since persistent SQLite sessions, ``Store.get()`` builds a brand-new
``Session`` (``data=None``) per request, so ``live_data()`` rebuilt the
whole LMS payload on *every* ``GET /data.js``. This module restores a
shared cache keyed by session id:

- ``payload`` — the assembled ``window.LMS`` dict, TTL ``OPENLMS_DATA_TTL``.
- ``files`` — the flattened resource list, TTL ``OPENLMS_FILES_TTL``
  (resources change rarely; the folder crawl is the slowest upstream).

Only one thread builds per sid at a time (singleflight via per-sid
locks); concurrent tabs wait on the same lock instead of stampeding
the LMS. Single process only — a second worker would have its own
cache (correct, just colder). No personal data touches disk here.

Usage:
    entry = get_entry(sid)          # creates or returns shared entry
    payload, etag = get_or_build(sid, builder, refresh=False)
    put_files(sid, files)
    drop(sid)                       # logout
    clear()                         # tests
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict

DATA_TTL = int(os.environ.get("OPENLMS_DATA_TTL", "300"))
FILES_TTL = int(os.environ.get("OPENLMS_FILES_TTL", "3600"))
CACHE_SIZE = int(os.environ.get("OPENLMS_CACHE_SIZE", "200"))


class _Entry:
    __slots__ = ("payload", "built_at", "etag", "files", "files_at", "lock")

    def __init__(self) -> None:
        self.payload: dict | None = None
        self.built_at: float = 0.0
        self.etag: str | None = None
        self.files: list[dict] | None = None
        self.files_at: float = 0.0
        self.lock = threading.Lock()


_entries: OrderedDict[str, _Entry] = OrderedDict()
_entries_lock = threading.Lock()


def _evict_if_needed() -> None:
    while len(_entries) > CACHE_SIZE:
        _entries.popitem(last=False)


def get_entry(sid: str | None) -> _Entry | None:
    """Return the shared entry for sid, creating it. None without sid."""
    if not sid:
        return None
    with _entries_lock:
        entry = _entries.get(sid)
        if entry is None:
            entry = _Entry()
            _entries[sid] = entry
            _evict_if_needed()
        else:
            _entries.move_to_end(sid)
        return entry


def get_payload(entry: _Entry, refresh: bool = False) -> dict | None:
    """Fresh cached payload, or None when missing/stale/forced."""
    if refresh or not entry.payload:
        return None
    if time.time() - entry.built_at > DATA_TTL:
        return None
    return entry.payload


def get_files(entry: _Entry, allow_stale: bool = False) -> list[dict] | None:
    """Fresh cached files list, or None when missing/stale.

    `allow_stale=True` returns the last known list past its TTL — used as
    a fallback when a fresh crawl fails, so the page still renders.
    """
    if not entry.files:
        return None
    if not allow_stale and time.time() - entry.files_at > FILES_TTL:
        return None
    return entry.files


def put_payload(entry: _Entry, payload: dict) -> str:
    """Store payload, compute ETag, return it."""
    entry.payload = payload
    entry.built_at = time.time()
    entry.etag = etag_for(payload)
    return entry.etag


def put_files(entry: _Entry, files: list[dict]) -> None:
    entry.files = files
    entry.files_at = time.time()


def etag_for(payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def drop(sid: str | None) -> None:
    if not sid:
        return
    with _entries_lock:
        _entries.pop(sid, None)


def clear() -> None:
    with _entries_lock:
        _entries.clear()
