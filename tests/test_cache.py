# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the per-sid data cache (navigation speed)."""

import base64
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OPENLMS_SESSION_FILE", ":memory:")

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None

if TestClient:
    from openlms import app as server
    from openlms import cache as datacache


def jwt(exp: float) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


USER = {"full_name": "Test Student", "email": "s@school.test", "roles": [{"tenant_id": "tid"}]}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body
        self.ok = status < 400
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


@unittest.skipUnless(TestClient, "server dependencies not installed")
class DataCacheTest(unittest.TestCase):
    def setUp(self):
        server.sessions = server.Store(":memory:")
        server.datacache.clear()
        server.attempts.clear()
        server.WARM_ON_LOGIN = False
        self.client = TestClient(server.app, base_url="https://testserver")
        self.build = mock.patch.object(
            server, "build",
            side_effect=lambda tok, tid, live=True, files=None: {"live": live, "tok": tok},
        ).start()
        self.tree = mock.patch.object(server, "resource_tree", return_value=[]).start()
        self.post = mock.patch.object(server.requests, "post").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(server.sessions.close)

    def sign_in(self):
        self.post.return_value = FakeResponse(200, {
            "access": jwt(time.time() + 3600), "refresh": "r", "user": USER})
        return self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def test_second_hit_served_from_cache(self):
        self.sign_in()
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, 1)
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, 1, "navigation should not rebuild")

    def test_refresh_forces_rebuild(self):
        self.sign_in()
        self.client.get("/data.js")
        self.client.get("/data.js", params={"refresh": "true"})
        self.assertEqual(self.build.call_count, 2)

    def test_etag_304(self):
        self.sign_in()
        first = self.client.get("/data.js")
        etag = first.headers.get("etag")
        self.assertTrue(etag)
        self.assertIn("private", first.headers["cache-control"])
        second = self.client.get("/data.js", headers={"if-none-match": etag})
        self.assertEqual(second.status_code, 304)
        self.assertEqual(self.build.call_count, 1)

    def test_sections_filter(self):
        self.sign_in()
        r = self.client.get("/data.js", params={"sections": "calendar"})
        body = r.text[len("window.LMS = "):].rstrip().rstrip(";")
        data = json.loads(body)
        self.assertIn("live", data)
        self.assertNotIn("tok", data)

    def test_logout_drops_cache(self):
        self.sign_in()
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, 1)
        self.client.post("/api/logout")
        self.sign_in()
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, 2)


class CacheUnitTest(unittest.TestCase):
    def test_files_ttl_reuse(self):
        entry = datacache._Entry()
        datacache.put_files(entry, [{"id": "r1"}])
        self.assertEqual(datacache.get_files(entry), [{"id": "r1"}])
        entry.files_at = time.time() - datacache.FILES_TTL - 1
        self.assertIsNone(datacache.get_files(entry))

    def test_payload_ttl(self):
        entry = datacache._Entry()
        datacache.put_payload(entry, {"live": True})
        self.assertIsNotNone(datacache.get_payload(entry))
        entry.built_at = time.time() - datacache.DATA_TTL - 1
        self.assertIsNone(datacache.get_payload(entry))


if __name__ == "__main__":
    unittest.main()
