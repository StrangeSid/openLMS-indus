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


DETAIL_TTL = int(os.environ.get("OPENLMS_DETAIL_TTL", "300"))


class _Entry:
    __slots__ = ("payload", "built_at", "etag", "files", "files_at", "lock",
                 "crawl_lock", "crawling", "crawl_done", "memo", "memo_lock")

    def __init__(self) -> None:
        self.payload: dict | None = None
        self.built_at: float = 0.0
        self.etag: str | None = None
        self.files: list[dict] | None = None
        self.files_at: float = 0.0
        self.lock = threading.Lock()
        # Background resource crawl (singleflight): data.js never waits on it.
        self.crawl_lock = threading.Lock()
        self.crawling = False
        self.crawl_done = threading.Event()
        self.crawl_done.set()
        # Detail views (/api/fa/..., /api/messages/...): key -> (stored_at, value)
        self.memo: dict[str, tuple[float, object]] = {}
        self.memo_lock = threading.Lock()


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


def put_payload(entry: _Entry, payload: dict, keep_age: bool = False) -> str:
    """Store payload, compute ETag, return it. `keep_age` patches a slice
    (e.g. resources) without extending the rest of the payload's TTL."""
    entry.payload = payload
    if not keep_age:
        entry.built_at = time.time()
    entry.etag = etag_for(payload)
    return entry.etag


def memo(entry: _Entry, key: str, fn, ttl: float | None = None, refresh: bool = False):
    """Per-student cached detail call (5 minutes by default). Errors are not cached."""
    ttl = DETAIL_TTL if ttl is None else ttl
    with entry.memo_lock:
        hit = entry.memo.get(key)
    if hit and not refresh and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    with entry.memo_lock:
        entry.memo[key] = (time.time(), value)
    return value


def forget(entry: _Entry | None, *prefixes: str) -> None:
    """Drop cached detail entries whose key starts with any prefix (after a write)."""
    if entry is None:
        return
    with entry.memo_lock:
        for key in [k for k in entry.memo if k.startswith(prefixes)]:
            del entry.memo[key]


def expire_payload(entry: _Entry | None) -> None:
    """Force the next data.js to rebuild (after a write that changes lists)."""
    if entry is not None:
        entry.built_at = 0.0


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
