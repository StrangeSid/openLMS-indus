# SPDX-License-Identifier: GPL-3.0-or-later
"""In-app LMS routes: reads, writes, retries and cache effects (stubbed LMS)."""

import base64
import json
import os
import sys
import threading
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
    import lms
    from openlms import app as server
    from openlms import routes


def jwt(exp: float) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'none'})}.{part({'exp': exp})}.sig"


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body
        self.ok = status < 400
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body


UID = "11111111-aaaa-bbbb-cccc-000000000001"
TEACHER = "22222222-aaaa-bbbb-cccc-000000000002"
EOL_ID = "33333333-aaaa-bbbb-cccc-000000000003"
TASK_ID = "44444444-aaaa-bbbb-cccc-000000000004"
FA_ID = "55555555-aaaa-bbbb-cccc-000000000005"
NOTE_ID = "66666666-aaaa-bbbb-cccc-000000000006"
USER = {"id": UID, "full_name": "Test Student", "email": "s@school.test", "roles": [{"tenant_id": "tid"}]}


def eol_row(**over):
    row = {"id": EOL_ID, "testId": "ECO082", "title": "EOL", "subject": "Economics", "status": "assigned",
           "submitted": None, "canAttempt": True, "expired": False, "blocked": False, "suspended": False,
           "exits": 0, "exitMax": 3}
    row.update(over)
    return row


def payload(**over):
    p = {"live": True, "student": "Test Student", "courses": [], "eol": [eol_row()], "assessments": [],
         "tasks": [], "unread": 2, "calendar": [], "attendance": {"percentage": 90},
         "notifications": [{"id": NOTE_ID, "read": False}, {"id": "other", "read": False}],
         "announcements": [{"id": "a1", "title": "Trip", "message": "Bring forms", "by": "T", "subject": "Physics"},
                           {"id": "a2", "title": "Exam", "message": "Room 4", "by": "T", "subject": "Maths"}],
         "resources": []}
    p.update(over)
    return p


@unittest.skipUnless(TestClient, "server dependencies not installed")
class RoutesTest(unittest.TestCase):
    def setUp(self):
        server.sessions = server.Store(":memory:")
        server.datacache.clear()
        server.attempts.clear()
        server.WARM_ON_LOGIN = False
        self.client = TestClient(server.app, base_url="https://testserver")
        self.payload = payload()
        self.build = mock.patch.object(server, "build", side_effect=lambda tok, tid, live=True, files=None: json.loads(json.dumps(self.payload))).start()
        mock.patch.object(server, "resource_tree", return_value=[]).start()
        mock.patch.object(server, "_spawn", lambda fn: fn()).start()
        self.post = mock.patch.object(server.http, "post").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(server.sessions.close)
        self.post.return_value = FakeResponse(200, {"access": jwt(time.time() + 3600), "refresh": "r", "user": USER})
        self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def lms(self, name, **kw):
        return mock.patch.object(lms, name, **kw).start()

    # --- auth, validation ----------------------------------------------------

    def test_requires_sign_in(self):
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/messages/threads").status_code, 401)
        self.assertEqual(self.client.post("/api/messages", json={"to_user_id": TEACHER, "text": "hi"}).status_code, 401)

    def test_ids_are_validated_before_reaching_the_lms(self):
        detail = self.lms("learning_task_detail")
        self.assertEqual(self.client.get("/api/tasks/not-an-id!").status_code, 404)
        self.assertEqual(self.client.get("/api/tasks/..").status_code, 404)
        detail.assert_not_called()

    def test_cross_site_write_blocked(self):
        send = self.lms("send_message")
        r = self.client.post("/api/messages", json={"to_user_id": TEACHER, "text": "hi"},
                             headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)
        send.assert_not_called()

    # --- retries -------------------------------------------------------------

    def test_read_retries_once_after_401_with_a_forced_refresh(self):
        threads = self.lms("message_threads", side_effect=[lms.LMSError(401, {"detail": "token_not_valid"}),
                                                          [{"contact_user_id": TEACHER, "contact_user_name": "Ms T"}]])
        self.post.reset_mock()
        self.post.return_value = FakeResponse(200, {"access": jwt(time.time() + 3600)})
        r = self.client.get("/api/messages/threads")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["userId"], TEACHER)
        self.assertEqual(threads.call_count, 2)
        self.assertIn("/api/token/refresh/", self.post.call_args.args[0])

    def test_writes_never_retry(self):
        send = self.lms("send_message", side_effect=lms.LMSError(401, {"detail": "token_not_valid"}))
        r = self.client.post("/api/messages", json={"to_user_id": TEACHER, "text": "hi"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(send.call_count, 1)

    def test_lms_errors_keep_their_message_and_code(self):
        self.lms("eol_open", side_effect=lms.LMSError(400, {"code": "bad_passcode", "message": "Wrong passcode."}))
        r = self.client.post("/api/eol/open", json={"short_id": "ECO082", "passcode": "0000"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], {"message": "Wrong passcode.", "code": "bad_passcode"})

    # --- EOL -----------------------------------------------------------------

    def test_eol_open_and_submit(self):
        opened = self.lms("eol_open", return_value={"id": EOL_ID, "short_id": "ECO082", "title": "Subsidy", "total_marks": "5.00",
                                                    "questions": [{"id": "q1", "question_text": "<p>Pick <b>one</b><script>x</script></p>",
                                                                   "option_a_text": "A", "option_b_text": "B", "marks": "1.00"}]})
        r = self.client.post("/api/eol/open", json={"short_id": "ECO082", "passcode": "1234"})
        self.assertEqual(r.status_code, 200)
        test = r.json()
        self.assertEqual(opened.call_args.args[1:], ("tid", "ECO082", "1234"))
        self.assertEqual(test["questions"][0]["html"], "<p>Pick <b>one</b></p>")
        self.assertEqual([o["key"] for o in test["questions"][0]["options"]], ["a", "b"])

        submit = self.lms("eol_submit", return_value={"score": "4.00", "total_marks": "5.00", "percent": "80.00"})
        self.lms("eol_result", return_value={"submission_id": "s1", "score": {"score": "4.00", "total_marks": "5.00"},
                                             "responses": [{"question_id": "q1", "question_text": "Q", "selected_option": "a",
                                                            "correct_option": "B", "is_correct": False,
                                                            "options": {"a": {"text": "A"}, "b": {"text": "B"}}}]})
        builds = self.build.call_count
        r = self.client.post(f"/api/eol/{EOL_ID}/submit", json={"passcode": "1234", "answers": {"q1": "a"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["score"], "4.00")
        self.assertEqual(r.json()["result"]["responses"][0]["correct"], "b")
        self.assertEqual(submit.call_args.args[1:], ("tid", EOL_ID, "1234", {"q1": "a"}))
        self.client.get("/data.js")
        self.assertEqual(self.build.call_count, builds + 1, "lists rebuild after a submit")

    def test_failed_submit_is_reported_not_retried(self):
        submit = self.lms("eol_submit", side_effect=lms.LMSError(403, {"code": "attempts_exceeded", "message": "No attempts left."}))
        r = self.client.post(f"/api/eol/{EOL_ID}/submit", json={"passcode": "1234", "answers": {"q1": "a"}})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"]["code"], "attempts_exceeded")
        self.assertEqual(submit.call_count, 1)

    def test_open_refused_when_exits_used_or_suspended(self):
        opened = self.lms("eol_open")
        for row in (eol_row(exits=3), eol_row(blocked=True), eol_row(suspended=True)):
            self.payload["eol"] = [row]
            self.client.get("/data.js?refresh=1")
            r = self.client.post("/api/eol/open", json={"short_id": "ECO082", "passcode": "1234"})
            self.assertEqual(r.status_code, 409)
        opened.assert_not_called()

    def test_eol_result_view_and_explain_built_server_side(self):
        self.payload["eol"] = [eol_row(status="submitted", submitted="2026-10-09T12:23:00Z")]
        self.lms("eol_feedback", return_value=[{"text": "Good"}])
        result = self.lms("eol_result", return_value={
            "submission_id": "s1", "score": {"score": "4.00", "total_marks": "5.00", "percentage": 80},
            "responses": [{"question_id": "q1", "question_text": "<p>Why?</p>", "selected_option": "a", "correct_option": "b",
                           "is_correct": False, "options": {"a": {"text": "Because"}, "b": {"text": "<i>Supply</i>"}}}]})
        r = self.client.get(f"/api/eol/{EOL_ID}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["result"]["percentage"], 80)
        self.assertEqual(body["result"]["responses"][0]["id"], "q1")
        self.assertEqual(body["feedback"], [{"text": "Good"}])
        self.assertEqual(result.call_args.args[1:], ("tid", EOL_ID, UID))

        explain = self.lms("eol_explain", return_value={"explanation": "Supply shifts.", "cached": False})
        r = self.client.post(f"/api/eol/{EOL_ID}/explain", json={"question_id": "q1"})
        self.assertEqual(r.json(), {"explanation": "Supply shifts.", "cached": False})
        kw = explain.call_args.kwargs
        self.assertEqual((kw["submission_id"], kw["selected_option"], kw["correct_option"]), ("s1", "a", "b"))
        self.assertEqual(kw["options"], {"a": "Because", "b": "Supply"})
        self.assertEqual(self.client.post(f"/api/eol/{EOL_ID}/explain", json={"question_id": "nope"}).status_code, 404)

    def test_proctor_event_reports_suspension(self):
        self.lms("eol_proctor_event", return_value={"proctor_violation_count": 4, "suspend_threshold": 4, "proctor_suspended": True})
        r = self.client.post(f"/api/eol/{EOL_ID}/proctor", json={"event_type": "document_visibility_hidden"})
        self.assertEqual(r.json(), {"violations": 4, "threshold": 4, "suspended": True})
        self.assertEqual(self.client.post(f"/api/eol/{EOL_ID}/proctor", json={"event_type": "other"}).status_code, 400)

    # --- FA / SA -------------------------------------------------------------

    def fa_rows(self, questions=()):
        return [{"status": "assigned", "assessment": {"id": FA_ID, "title": "FA2", "instructions": "<p>Do it</p>",
                                                     "file_urls": [{"url": "https://s3.test/brief.pdf", "type": "file"}],
                                                     "questions": list(questions), "submission_open": True}}]

    def test_fa_detail_combines_row_submission_feedback_requests(self):
        self.lms("assessments_all", return_value=self.fa_rows())
        self.lms("assessment_submission", side_effect=lms.LMSError(404, {"message": "No submission"}))
        self.lms("assessment_feedback", return_value={"has_feedback": False})
        self.lms("request_summary", return_value={"enabled": True, "items": {FA_ID: {"requests_used": 1, "requests_max": 3,
                                                                                    "can_request": {"extension": True}}}})
        r = self.client.get(f"/api/fa/{FA_ID}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["assessment"]["instructions"], "<p>Do it</p>")
        self.assertEqual(body["assessment"]["files"][0]["name"], "brief.pdf")
        self.assertIsNone(body["submission"])
        self.assertIsNone(body["feedback"])
        self.assertEqual(body["requests"]["requests_used"], 1)

    def test_fa_upload_submit(self):
        self.lms("assessments_all", return_value=self.fa_rows())
        upload = self.lms("upload_files", return_value=[{"file_url": "https://s3.test/work.pdf"}])
        submit = self.lms("assessment_submit_upload", return_value={"ok": True})
        r = self.client.post(f"/api/fa/{FA_ID}/submit", data={"comment": "Final"},
                             files=[("files", ("work.pdf", b"%PDF", "application/pdf"))])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(upload.call_args.args[2], "assesement")
        self.assertEqual(upload.call_args.args[3], [("work.pdf", b"%PDF", "application/pdf")])
        self.assertEqual(submit.call_args.args[1:], (FA_ID, ["https://s3.test/work.pdf"], "Final"))
        self.assertEqual(self.client.post(f"/api/fa/{FA_ID}/submit", data={"comment": "x"}).status_code, 400)

    def test_fa_question_submit(self):
        self.lms("assessments_all", return_value=self.fa_rows([{"id": "q1", "question_type": "MCQ"}, {"id": "q2"}]))
        submit = self.lms("assessment_submit_questions", return_value={"ok": True})
        answers = [{"question_id": "q1", "selected_option": "b"}, {"question_id": "q2", "answer_text": "42"}]
        r = self.client.post(f"/api/fa/{FA_ID}/submit", data={"responses": json.dumps(answers)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(submit.call_args.args[2], answers)

    def test_extension_request_validation_and_cancel(self):
        req = self.lms("assessment_request", return_value={"id": "77777777-aaaa"})
        self.assertEqual(self.client.post(f"/api/fa/{FA_ID}/request", json={"request_type": "extension", "reason": "short"}).status_code, 400)
        r = self.client.post(f"/api/fa/{FA_ID}/request", json={"request_type": "extension", "reason": "I was ill on Monday",
                                                              "preferred_due_at": "2026-10-20T10:00:00Z"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(req.call_args.args[1:], (FA_ID, "extension", "I was ill on Monday", "2026-10-20T10:00:00Z"))
        cancel = self.lms("request_cancel", return_value={})
        self.assertEqual(self.client.post("/api/requests/77777777-aaaa/cancel").status_code, 200)
        cancel.assert_called_once()

    # --- Tasks ---------------------------------------------------------------

    def test_task_detail_and_submit(self):
        self.lms("learning_tasks", return_value=[{"id": TASK_ID, "title": "Theme B", "instructions": "Read <b>ch 4</b>",
                                                  "attachments": [{"name": "b.pdf", "file_url": "https://s3.test/b.pdf"}]}])
        self.lms("learning_task_detail", return_value={"assignment": {"id": TASK_ID, "title": "Theme B", "due_date": "2026-09-30"},
                                                       "recipient_status": "assigned", "submission": None})
        body = self.client.get(f"/api/tasks/{TASK_ID}").json()
        self.assertEqual(body["instructions"], "Read <b>ch 4</b>")
        self.assertEqual(body["attachments"][0]["url"], "https://s3.test/b.pdf")
        self.assertIsNone(body["submission"])

        self.assertEqual(self.client.post(f"/api/tasks/{TASK_ID}/submit", data={"text": "x"}).status_code, 400)
        upload = self.lms("upload_files", return_value=[{"file_url": "https://s3.test/w.pdf", "name": "w.pdf"}])
        submit = self.lms("task_submit", return_value={"ok": True})
        r = self.client.post(f"/api/tasks/{TASK_ID}/submit", files=[("files", ("w.pdf", b"%PDF", "application/pdf"))])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(upload.call_args.args[2], "assignment_submission")
        self.assertEqual(submit.call_args.args[1:3], ("tid", TASK_ID))

    def test_upload_limits(self):
        with mock.patch.object(routes, "MAX_FILE_BYTES", 3):
            r = self.client.post(f"/api/tasks/{TASK_ID}/submit", files=[("files", ("big.pdf", b"%PDF", "application/pdf"))])
        self.assertEqual(r.status_code, 413)

    # --- Notifications, announcements, messages -------------------------------

    def test_mark_read_updates_bell_without_rebuilding(self):
        read = self.lms("notification_read", return_value={})
        self.client.get("/data.js")
        builds = self.build.call_count
        self.assertEqual(self.client.post(f"/api/notifications/{NOTE_ID}/read").status_code, 200)
        read.assert_called_once()
        data = self.client.get("/api/data", params={"sections": "unread,notifications"}).json()
        self.assertEqual(data["unread"], 1)
        self.assertTrue(data["notifications"][0]["read"])
        self.lms("notifications_read_all", return_value={})
        self.client.post("/api/notifications/read-all")
        self.assertEqual(self.client.get("/api/data", params={"sections": "unread"}).json()["unread"], 0)
        self.assertEqual(self.build.call_count, builds)

    def test_notification_pages_and_filters(self):
        self.lms("notifications", return_value={"unread_count": 1, "results": [
            {"id": "n1", "title": "FA graded", "is_read": False}, {"id": "n2", "title": "EOL set", "is_read": True}]})
        body = self.client.get("/api/notifications", params={"limit": 2, "filter": "unread"}).json()
        self.assertEqual([n["id"] for n in body["items"]], ["n1"])
        self.assertEqual(body["nextOffset"], 2)
        body = self.client.get("/api/notifications", params={"limit": 20, "q": "eol"}).json()
        self.assertEqual([n["id"] for n in body["items"]], ["n2"])
        self.assertIsNone(body["nextOffset"])

    def test_announcement_search_and_read(self):
        self.assertEqual([a["id"] for a in self.client.get("/api/announcements", params={"q": "room"}).json()], ["a2"])
        read = self.lms("announcement_read", return_value={"recorded": True})
        self.assertEqual(self.client.post("/api/announcements/a1b2c3d4e5/read").json(), {"ok": True, "recorded": True})
        read.assert_called_once()

    def test_conversation_and_send(self):
        self.lms("message_conversation", return_value={"results": [
            {"id": "m1", "from_user_id": TEACHER, "text": "Hello"}, {"id": "m2", "from_user_id": UID, "text": "Hi!"}]})
        msgs = self.client.get(f"/api/messages/conversation/{TEACHER}").json()["messages"]
        self.assertEqual([m["mine"] for m in msgs], [False, True])
        send = self.lms("send_message", return_value={"id": "m3", "from_user_id": UID, "text": "Thanks"})
        r = self.client.post("/api/messages", json={"to_user_id": TEACHER, "text": "  Thanks  "})
        self.assertEqual(r.json()["mine"], True)
        self.assertEqual(send.call_args.args[1:], ("tid", TEACHER, "Thanks"))
        self.assertEqual(self.client.post("/api/messages", json={"to_user_id": TEACHER, "text": "   "}).status_code, 400)

    def test_school_pages_are_cached(self):
        pol = self.lms("policies", return_value=[{"title": "Uniform", "file_url": "https://s3.test/u.pdf", "version": 2}])
        self.assertEqual(self.client.get("/api/policies").json()[0]["url"], "https://s3.test/u.pdf")
        self.client.get("/api/policies")
        pol.assert_called_once()
        self.lms("progress_reports", return_value={"total": 0, "pdfs": []})
        self.assertEqual(self.client.get("/api/reports").json(), {"total": 0, "reports": []})


@unittest.skipUnless(TestClient, "server dependencies not installed")
class BackgroundCrawlTest(unittest.TestCase):
    """data.js must not wait for the resource crawl (it took ~11 s cold)."""

    def setUp(self):
        server.sessions = server.Store(":memory:")
        server.datacache.clear()
        server.attempts.clear()
        server.WARM_ON_LOGIN = False
        self.client = TestClient(server.app, base_url="https://testserver")
        mock.patch.object(server, "build", side_effect=lambda tok, tid, live=True, files=None: {"live": True, "resources": []}).start()
        self.release = threading.Event()

        def slow_tree(tok, tid):
            self.release.wait(5)
            return [{"id": "r1", "is_folder": False, "title": "Notes", "subject": "Physics",
                     "file_urls": [{"id": "f1", "name": "notes.pdf"}]}]
        mock.patch.object(server, "resource_tree", side_effect=slow_tree).start()
        self.post = mock.patch.object(server.http, "post").start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.release.set)
        self.post.return_value = FakeResponse(200, {"access": jwt(time.time() + 3600), "refresh": "r", "user": USER})
        self.client.post("/api/login", json={"email": "s@school.test", "password": "pw"})

    def test_page_data_returns_while_crawl_runs_then_files_hot_swap(self):
        started = time.time()
        first = self.client.get("/api/data").json()
        self.assertLess(time.time() - started, 2, "data must not wait for the crawl")
        self.assertTrue(first["resourcesPending"])
        self.assertEqual(first["resources"], [])
        self.release.set()
        files = self.client.get("/api/data", params={"sections": "resources,resourcesStale,resourcesPending", "wait": 1}).json()
        self.assertFalse(files["resourcesPending"])
        self.assertFalse(files["resourcesStale"])
        self.assertEqual(files["resources"][0]["path"], "api/files/r1/f1")


@unittest.skipUnless(TestClient, "server dependencies not installed")
class RefreshAheadTest(unittest.TestCase):
    def test_token_refreshed_five_minutes_before_expiry(self):
        s = server.Session(jwt(time.time() + 240), "r", "tid", USER)
        with mock.patch.object(server.http, "post", return_value=FakeResponse(200, {"access": "new"})) as post:
            self.assertEqual(server.fresh(s), "new")
            post.assert_called_once()
        s = server.Session(jwt(time.time() + 3600), "r", "tid", USER)
        with mock.patch.object(server.http, "post") as post:
            server.fresh(s)
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
