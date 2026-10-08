# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for persistent server-side sessions (survive restarts)."""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openlms.sessions import Session, Store


def make_session(access="a1", refresh="r1"):
    return Session(access, refresh, "tid", {"full_name": "Test", "email": "s@school.test"})


class SessionStoreTest(unittest.TestCase):
    def test_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "sess.db")
            s1 = Store(db)
            sid = s1.add(make_session())
            # Simulate a server restart: new Store on the same file.
            s2 = Store(db)
            got = s2.get(sid)
            self.assertIsNotNone(got)
            self.assertEqual(got.access, "a1")
            self.assertEqual(got.refresh, "r1")
            self.assertEqual(got.tenant, "tid")
            self.assertIsNone(got.data)  # page cache is never persisted
            s1.close()
            s2.close()

    def test_save_persists_refresh(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "sess.db")
            s1 = Store(db)
            sid = s1.add(make_session())
            loaded = s1.get(sid)
            loaded.access, loaded.refresh = "a2", "r2"
            s1.save(loaded)
            s2 = Store(db)
            self.assertEqual(s2.get(sid).access, "a2")
            s1.close()
            s2.close()

    def test_drop_revokes(self):
        store = Store(":memory:")
        sid = store.add(make_session())
        store.drop(sid)
        self.assertIsNone(store.get(sid))
        self.assertIsNone(Store(":memory:").get(sid))
        store.close()

    def test_expired_sessions_purged(self):
        store = Store(":memory:", idle=-1)
        sid = store.add(make_session())
        self.assertIsNone(store.get(sid))
        store.close()

    def test_encrypted_roundtrip(self):
        try:
            from cryptography.fernet import Fernet  # noqa
        except ImportError:
            self.skipTest("cryptography not installed")
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "sess.db")
            with mock.patch.dict(os.environ, {"OPENLMS_SECRET_KEY": "test-secret-123"}):
                s1 = Store(db)
                sid = s1.add(make_session("tok-access", "tok-refresh"))
                raw = s1._db.execute("SELECT access FROM sessions WHERE sid=?", (sid,)).fetchone()[0]
                self.assertNotIn("tok-access", raw)
                s1.close()
                s2 = Store(db)
                got = s2.get(sid)
                self.assertEqual(got.access, "tok-access")
                self.assertEqual(got.refresh, "tok-refresh")
                s2.close()
            # Wrong secret -> treated as expired, forces re-login.
            with mock.patch.dict(os.environ, {"OPENLMS_SECRET_KEY": "other-secret"}):
                s3 = Store(db)
                self.assertIsNone(s3.get(sid))
                s3.close()

    def test_plaintext_file_is_0600(self):
        with tempfile.TemporaryDirectory() as d:
            db = str(Path(d) / "sess.db")
            store = Store(db)
            store.add(make_session())
            mode = oct(Path(db).stat().st_mode & 0o777)
            self.assertEqual(mode, "0o600")
            store.close()


if __name__ == "__main__":
    unittest.main()
