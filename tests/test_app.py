# SPDX-License-Identifier: GPL-3.0-or-later
import base64
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from fastapi.testclient import TestClient
except ImportError:  # server dependencies not installed
    TestClient = None

if TestClient:
    from openlms import app as server


def jwt(exp: float) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


class FakeResponse:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code, self._body, self._content = status, body, content
        self.ok = status < 400
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._body

    def iter_content(self, size):
        yield self._content


USER = {"full_name": "Test Student", "email": "s@school.test", "roles": [{"tenant_id": "tid"}]}


@unittest.skipUnless(TestClient, "server dependencies not installed")
class AppTest(unittest.TestCase):
    def setUp(self):
        server.sessions = server.Store()
        server.attempts.clear()
        self.client = TestClient(server.app, base_url="https://testserver")
        self.build = mock.patch.object(server, "build", side_effect=lambda tok, tid, live: {"live": live, "tok": tok}).start()
        self.post = mock.patch.object(server.requests, "post").start()
        self.get = mock.patch.object(server.requests, "get").start()
        self.addCleanup(mock.patch.stopall)

    def sign_in(self, access=None):
        self.post.return_value = FakeResponse(200, {"access": access or jwt(time.time() + 3600), "refresh": "r", "user": USER})
        return self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def test_data_redirects_when_signed_out(self):
        r = self.client.get("/data.js")
        self.assertIn("login.html", r.text)
        self.build.assert_not_called()

    def test_login_and_live_data(self):
        r = self.sign_in()
        self.assertEqual(r.json(), {"name": "Test Student"})
        cookie = r.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("secure", cookie)
        self.assertEqual(self.post.call_args.kwargs["json"], {"email": "s@school.test", "password": "pw"})

        data = self.client.get("/data.js")
        self.assertTrue(data.text.startswith("window.LMS = "))
        self.assertIn('"live": true', data.text)
        self.assertEqual(data.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/api/session").json()["name"], "Test Student")

    def test_bad_password(self):
        self.post.return_value = FakeResponse(401, {"detail": "No active account"})
        r = self.client.post("/api/login", json={"email": "s@school.test", "password": "nope"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("set-cookie", r.headers)

    def test_login_rate_limited(self):
        self.post.return_value = FakeResponse(401, {})
        codes = [self.client.post("/api/login", json={"email": "a@b.c", "password": "x"}).status_code for _ in range(11)]
        self.assertEqual(codes[-1], 429)

    def test_refreshes_expiring_token(self):
        self.sign_in(access=jwt(time.time() + 10))
        self.post.return_value = FakeResponse(200, {"access": "new-token"})
        self.client.get("/data.js")
        self.assertEqual(self.post.call_args.args[0], f"{server.lms.API_BASE}/api/token/refresh/")
        self.assertEqual(self.build.call_args.args[0], "new-token")

    def test_failed_refresh_requires_sign_in(self):
        self.sign_in(access=jwt(time.time() - 1))
        self.post.return_value = FakeResponse(401, {"detail": "token_not_valid"})
        self.assertEqual(self.client.get("/data.js").status_code, 401)

    def test_logout(self):
        self.sign_in()
        self.client.post("/api/logout")
        self.assertIn("login.html", self.client.get("/data.js").text)

    def test_cross_site_post_blocked(self):
        r = self.client.post("/api/logout", headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_exported_files_not_served(self):
        self.assertEqual(self.client.get("/files/Physics/notes.pdf").status_code, 404)

    def test_file_proxy(self):
        self.assertEqual(self.client.get("/api/files/abcdef12/abcdef34").status_code, 401)
        self.sign_in()
        self.assertEqual(self.client.get("/api/files/..%2F..%2Fetc/abcdef34").status_code, 404)
        self.get.return_value = FakeResponse(200, content=b"%PDF", headers={"content-type": "application/pdf", "x-secret": "1"})
        r = self.client.get("/api/files/abcdef12/abcdef34")
        self.assertEqual(r.content, b"%PDF")
        self.assertEqual(r.headers["content-type"], "application/pdf")
        self.assertNotIn("x-secret", r.headers)
        self.get.return_value = FakeResponse(403)
        self.assertEqual(self.client.get("/api/files/abcdef12/abcdef34").status_code, 403)


if __name__ == "__main__":
    unittest.main()
