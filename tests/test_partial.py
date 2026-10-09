# SPDX-License-Identifier: GPL-3.0-or-later
"""Files-only partial refresh + JSON /api/data (Library hot-swap)."""

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

from openlms import data as lmsdata


def _jwt(exp: float) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


USER = {"full_name": "Test Student", "email": "s@school.test", "roles": [{"tenant_id": "tid"}]}

RAW_NEW = {"id": "r9", "is_folder": False, "title": "T9", "subject": "Physics",
           "teacher_name": "T", "file_urls": [{"id": "y", "name": "new.pdf"}]}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body
        self.ok = status < 400
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


FLAT_NEW = {"id": "r9", "file_id": "y", "title": "T9", "name": "new.pdf",
            "subject": "Physics", "teacher": "T", "folder": None, "dir": ["Physics"]}


class ShapeTest(unittest.TestCase):
    def test_shape_strips_ids_and_adds_path_when_live(self):
        files = [dict(FLAT_NEW)]
        out = lmsdata.shape_resources(files, live=True)
        self.assertEqual(out, [{"title": "T9", "name": "new.pdf", "subject": "Physics",
                                "teacher": "T", "folder": None,
                                "path": "api/files/r9/y"}])
        self.assertIn("path", files[0])

    def test_shape_offline_has_no_path(self):
        out = lmsdata.shape_resources([dict(FLAT_NEW)], live=False)
        self.assertNotIn("path", out[0])
        self.assertNotIn("id", out[0])
        self.assertNotIn("file_id", out[0])
        self.assertNotIn("dir", out[0])


@unittest.skipUnless(TestClient, "server dependencies not installed")
class PartialRefreshTest(unittest.TestCase):
    def setUp(self):
        server.sessions = server.Store(":memory:")
        server.datacache.clear()
        server.attempts.clear()
        server.WARM_ON_LOGIN = False
        self.client = TestClient(server.app, base_url="https://testserver")
        self.build = mock.patch.object(
            server, "build",
            side_effect=lambda tok, tid, live=True, files=None: {
                "live": live, "tok": tok, "resources": [{"title": "Old"}]},
        ).start()
        self.tree = mock.patch.object(server, "resource_tree", return_value=[]).start()
        self.post = mock.patch.object(server.requests, "post").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(server.sessions.close)

    def sign_in(self):
        self.post.return_value = FakeResponse(200, {
            "access": _jwt(time.time() + 3600), "refresh": "r", "user": USER})
        return self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def test_partial_refresh_skips_full_build(self):
        self.sign_in()
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, 1)
        self.tree.return_value = [dict(RAW_NEW)]
        r = self.client.get("/api/data", params={"refresh": "true",
                                                 "sections": "resources,resourcesStale"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/json")
        self.assertEqual(self.build.call_count, 1, "files-only refresh must not rebuild")
        data = r.json()
        self.assertEqual(data["resources"],
                         [{"title": "T9", "name": "new.pdf", "subject": "Physics",
                           "teacher": "T", "folder": None, "path": "api/files/r9/y"}])
        self.assertIs(data["resourcesStale"], False)
        self.assertNotIn("tok", data)

    def test_partial_refresh_failure_flags_stale(self):
        self.sign_in()
        self.client.get("/data.js")
        self.tree.side_effect = Exception("LMS hiccup")
        r = self.client.get("/api/data", params={"refresh": "true",
                                                 "sections": "resources,resourcesStale"})
        self.assertEqual(r.status_code, 200)
        self.assertIs(r.json()["resourcesStale"], True)

    def test_api_data_requires_sign_in(self):
        self.assertEqual(self.client.get("/api/data").status_code, 401)

    def test_api_data_slice_and_304(self):
        self.sign_in()
        first = self.client.get("/api/data", params={"sections": "calendar"})
        self.assertEqual(set(first.json()), {"live"})  # mocked build has no calendar key
        etag = first.headers.get("etag")
        self.assertTrue(etag)
        self.assertEqual(
            self.client.get("/api/data", params={"sections": "calendar"},
                            headers={"if-none-match": etag}).status_code, 304)


if __name__ == "__main__":
    unittest.main()
