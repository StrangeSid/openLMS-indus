# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent server-side sessions for openLMS.

Design (why not tokens-in-cookies):
  - The browser keeps only an opaque, random session id in an
    HttpOnly + SameSite=Lax (+ Secure on HTTPS) cookie.
  - LMS access/refresh tokens stay server-side in a SQLite file with
    0600 permissions, so a restart no longer signs everyone out.
  - Stateless encrypted-cookie sessions were rejected: they cannot be
    revoked server-side (logout only clears the browser copy) and they
    push ~1-2KB of tokens into every request. An opaque id revokes
    instantly via ``drop()`` and keeps cookies tiny.
  - The rendered-page cache (``Session.data``) is never persisted;
    it is rebuilt on demand after a restart via token refresh.

Encryption at rest (optional but recommended for shared hosting):
  - Set ``OPENLMS_SECRET_KEY`` to any passphrase or a Fernet key.
    Access/refresh tokens are then Fernet-encrypted before SQLite.
  - Without it, tokens rest as plaintext in a 0600 file. The threat
    model is the same host that held them in memory before, so this
    is no worse — just keep backups private and gitignore the file.
  - Changing the secret makes old rows undecryptable; they are treated
    as expired and the student signs in again.

Usage:
    sessions = Store()  # path from OPENLMS_SESSION_FILE or repo default
    sid = sessions.add(Session(...))
    s = sessions.get(sid)  # None when missing/expired/undecryptable
    sessions.save(s)       # after a token refresh
    sessions.drop(sid)     # logout / revoke
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent.parent / ".openlms-sessions.db"
SESSION_FILE = os.environ.get("OPENLMS_SESSION_FILE", str(DEFAULT_FILE))


def _fernet():
    """Return a Fernet instance when OPENLMS_SECRET_KEY is set, else None."""
    secret = os.environ.get("OPENLMS_SECRET_KEY", "")
    if not secret:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "OPENLMS_SECRET_KEY is set but the 'cryptography' package is "
            "not installed. Run: pip install cryptography"
        ) from e
    raw = secret.strip().encode()
    try:
        # Accept a real Fernet key directly.
        return Fernet(raw)
    except Exception:
        # Accept any passphrase by deriving a stable Fernet key.
        digest = hashlib.sha256(raw).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


class Session:
    def __init__(self, access: str, refresh: str, tenant: str, user: dict):
        self.access, self.refresh, self.tenant = access, refresh, tenant
        self.name = user.get("full_name") or user.get("email")
        self.email = user.get("email")
        self.seen = time.time()
        self.created = self.seen
        self.sid: str | None = None
        self.data: tuple[float, dict] | None = None
        self.lock = threading.Lock()
        self.build_lock = threading.Lock()


class Store:
    """SQLite-backed session store. Pass path=':memory:' for tests/ephemeral."""

    def __init__(self, path: str | Path | None = None, idle: float = 12 * 3600):
        self.path = str(path if path is not None else SESSION_FILE)
        self.idle = idle
        self._lock = threading.Lock()
        self._memory = self.path == ":memory:"
        self._db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        try:
            self._db.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS sessions
               (sid TEXT PRIMARY KEY, access TEXT NOT NULL, refresh TEXT NOT NULL,
                tenant TEXT NOT NULL, name TEXT, email TEXT,
                seen REAL NOT NULL, created REAL NOT NULL)"""
        )
        self._db.commit()
        self.purge()
        if not self._memory:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def _enc(self, value: str) -> str:
        f = _fernet()
        if not f:
            return value
        return f.encrypt(value.encode()).decode()

    def _dec(self, value: str) -> str | None:
        f = _fernet()
        if not f:
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            return None

    def purge(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE seen < ?", (time.time() - self.idle,))
            self._db.commit()

    def add(self, s: Session) -> str:
        sid = secrets.token_urlsafe(32)
        s.sid = sid
        s.seen = time.time()
        if not s.created:
            s.created = s.seen
        with self._lock:
            self._db.execute(
                "INSERT INTO sessions (sid, access, refresh, tenant, name, email, seen, created)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, self._enc(s.access), self._enc(s.refresh), s.tenant,
                 s.name, s.email, s.seen, s.created),
            )
            self._db.commit()
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT sid, access, refresh, tenant, name, email, seen, created"
                " FROM sessions WHERE sid = ?", (sid,),
            ).fetchone()
            if not row:
                return None
            _, enc_access, enc_refresh, tenant, name, email, seen, created = row
            if time.time() - (seen or 0) > self.idle:
                self._db.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
                self._db.commit()
                return None
        access = self._dec(enc_access)
        refresh = self._dec(enc_refresh)
        if access is None or refresh is None:
            # Secret rotated or row tampered: force re-login.
            self.drop(sid)
            return None
        s = Session(access, refresh, tenant, {"full_name": name, "email": email})
        s.sid = sid
        s.seen = time.time()
        s.created = created or s.seen
        with self._lock:
            self._db.execute("UPDATE sessions SET seen = ? WHERE sid = ?", (s.seen, sid))
            self._db.commit()
        return s

    def save(self, s: Session) -> None:
        """Persist token changes (e.g. after a refresh). No-op without sid."""
        if not getattr(s, "sid", None):
            return
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET access = ?, refresh = ?, tenant = ?,"
                " name = ?, email = ?, seen = ? WHERE sid = ?",
                (self._enc(s.access), self._enc(s.refresh), s.tenant,
                 s.name, s.email, s.seen, s.sid),
            )
            self._db.commit()

    def drop(self, sid: str | None) -> None:
        if not sid:
            return
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()
