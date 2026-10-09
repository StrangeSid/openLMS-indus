# SPDX-License-Identifier: GPL-3.0-or-later
"""One bad LMS listing must degrade, never 500 /data.js.

Regression cover for a live crash: the LMS answered a resource folder
listing with an empty/non-JSON body, `list_resources().json()` raised
`JSONDecodeError` inside the crawl, and it escaped `safe()` because
`live_data` crawls outside `build()`.
"""

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
from openlms import data as lmsdata


def _boom(*args, **kwargs):
    raise json.JSONDecodeError("Expecting value", "", 0)


FOLDER = {"id": "f1", "is_folder": True, "title": "Unit 1", "subject": "Physics"}
FILE = {"id": "r1", "is_folder": False, "title": "Notes", "subject": "Physics",
        "teacher_name": "T", "file_urls": [{"id": "x", "name": "notes.pdf"}]}


def _flaky_listing(tok, tid, course, parent, page, size):
    if parent is None:
        return {"results": [dict(FOLDER), dict(FILE)], "next": None}
    raise json.JSONDecodeError("Expecting value", "", 0)


class CrawlUnitTest(unittest.TestCase):
    def test_non_json_top_page_is_empty(self):
        with mock.patch.object(lmsdata.lms, "list_resources", side_effect=_boom):
            self.assertEqual(lmsdata.resource_tree("t", "tid"), [])

    def test_bad_subtree_keeps_siblings(self):
        with mock.patch.object(lmsdata.lms, "list_resources", side_effect=_flaky_listing):
            tree = lmsdata.resource_tree("t", "tid")
        self.assertEqual(len(tree), 2)
        folder = next(r for r in tree if r["id"] == "f1")
        self.assertEqual(folder["children"], [])
        files = lmsdata.flatten(tree)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "notes.pdf")

    def test_stale_files_fallback(self):
        entry = datacache._Entry()
        datacache.put_files(entry, [{"id": "r1"}])
        entry.files_at = time.time() - datacache.FILES_TTL - 1
        self.assertIsNone(datacache.get_files(entry))
        self.assertEqual(datacache.get_files(entry, allow_stale=True), [{"id": "r1"}])


def _jwt(exp: float) -> str:
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
class DataJsResilienceTest(unittest.TestCase):
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
            "access": _jwt(time.time() + 3600), "refresh": "r", "user": USER})
        return self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def payload_of(self, response):
        body = response.text[len("window.LMS = "):].rstrip().rstrip(";")
        return json.loads(body)

    def test_crawl_blowup_still_200(self):
        self.sign_in()
        with mock.patch.object(server, "resource_tree", side_effect=Exception("LMS hiccup")):
            r = self.client.get("/data.js")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.text.startswith("window.LMS = "))

    def test_fresh_crawl_marks_resources_current(self):
        self.sign_in()
        data = self.payload_of(self.client.get("/data.js"))
        self.assertIs(data["resourcesStale"], False)

    def test_failed_crawl_marks_resources_stale(self):
        self.sign_in()
        with mock.patch.object(server, "resource_tree", side_effect=Exception("LMS hiccup")):
            data = self.payload_of(self.client.get("/data.js"))
        self.assertIs(data["resourcesStale"], True)


if __name__ == "__main__":
    unittest.main()
