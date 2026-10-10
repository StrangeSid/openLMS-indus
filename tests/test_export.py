# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

fake = types.ModuleType("lms")
fake.load_token = lambda: {"access": "t", "user": {"roles": [{"tenant_id": "tid"}]}}
fake.ensure_fresh_token = fake.load_token
fake.me = lambda tok: {"full_name": "Test Student"}
fake.my_courses = lambda tok, tid: {
    "program_code": "DP", "academic_year": "2026-27",
    "courses": [
        {"title": "Assembly", "classes": [], "teachers": []},
        {"title": "Physics", "subject_level": "HL", "code": "PHY", "classes": [{"grade": "Grade XI"}],
         "teachers": [{"full_name": "T. Teacher"}]},
    ],
}
fake.eol_tests = lambda tok, tid: {"results": [{
    "id": "e-uuid", "short_id": "PHY001", "can_attempt": True, "is_expired": False, "mid_test_exit_count": 1,
    "mid_test_exit_max": 3, "attempts_blocked": False, "attempts_exceeded": False, "proctor_suspended": False,
    "title": "EOL1", "subject": "Physics", "topic": "Motion", "status": "assigned", "score": None,
    "total_marks": "5", "teacher_name": "T. Teacher", "assigned_at": "2026-10-01T00:00:00Z",
    "available_until": "2026-10-09T00:00:00Z", "available_from": "2026-10-01T00:00:00Z",
    "submitted_at": None, "availability_status": "active"}]}
fake.assessments_all = lambda tok, kind=None, course_id=None: [] if kind == "SA" else [{
    "status": "graded", "marks": "8", "total_marks": "10", "submitted_at": "2026-10-02T00:00:00Z",
    "assigned_at": "2026-10-01T00:00:00Z",
    "assessment": {"id": "a-uuid", "title": "FA1", "subject": "Physics", "assessment_type": "FA", "category": None,
                   "due_date": "2026-10-03T00:00:00Z", "teacher_name": "T. Teacher", "questions": []}}]
fake.learning_tasks = lambda tok, tid, course_id=None: [
    {"id": "t1", "title": "Lab report", "subject": "Physics", "due_date": "2026-10-12T00:00:00Z", "status": "assigned",
     "attachments": [{"name": "brief.pdf", "file_url": "https://s3.test/brief.pdf"}]}]
fake.message_threads = lambda tok, tid: [
    {"contact_user_id": "u1", "contact_user_name": "T. Teacher", "contact_user_role": "TEACHER",
     "last_message": "See you in class", "last_updated": "2026-10-06T10:00:00Z", "status": "sent"}]
fake.notifications = lambda tok, tid, limit: {"unread_count": 1, "results": [
    {"id": "n1", "title": "N", "message": "m", "type": "fa", "actor_name": "T", "created_at": "2026-10-01",
     "is_read": False, "meta": {"subject": "Physics"}}]}
fake.attendance = lambda tok: {"total_sessions": 2, "present": 1, "absent": 1, "late": 0, "percentage": 50.0,
                               "records": [{"date": "2026-10-01", "status": "present"},
                                           {"date": "2026-10-02", "status": "no_school", "is_calendar_event": True}]}
fake.announcements_visible = lambda tok, year=None: [{
    "id": "an1", "title": "A", "subject": "Physics", "creator": {"full_name": "T"}, "created_at": "2026-10-01",
    "message": "<p onclick=\"x()\">Hi <b>all</b></p><script>bad()</script>",
    "file_urls": [{"url": "https://s3.test/sheet.pdf", "type": "file"}]}]
fake.calendar_events = lambda tok: {"events": [{"date": "2026-10-05", "end_date": "2026-10-05",
                                                "type": "holiday", "comment": "Break"}]}
fake.list_resources = lambda tok, tid, course, parent, page, size: {"results": [] if parent else [
    {"id": "f1", "is_folder": True, "title": "Unit 1", "subject": "Physics", "parent_resource_id": None},
    {"id": "r1", "is_folder": False, "title": "Notes", "subject": "Physics", "teacher_name": "T",
     "parent_resource_id": None, "file_urls": [{"id": "x", "name": "notes.pdf"}]},
]}

sys.modules.setdefault("lms", fake)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import export  # noqa: E402
from openlms import data as lmsdata  # noqa: E402


class ExportTest(unittest.TestCase):
    def test_writes_data_js(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "data.js"
            with mock.patch.object(sys, "argv", ["export.py", "--out", str(out)]), \
                    mock.patch.object(export, "lms", fake), mock.patch.object(lmsdata, "lms", fake):
                export.main()
            text = out.read_text()
            self.assertTrue(text.startswith("window.LMS = "))
            data = json.loads(text[len("window.LMS = "):].rstrip().rstrip(";"))

        self.assertEqual(data["program"], "DP · Grade XI")
        self.assertEqual([c["title"] for c in data["courses"]], ["Physics"])
        self.assertEqual(data["eol"][0]["due"], "2026-10-09T00:00:00Z")
        self.assertEqual(data["assessments"][0]["submitted"], "2026-10-02T00:00:00Z")
        self.assertEqual(data["assessments"][0]["type"], "FA")
        self.assertEqual(data["tasks"][0]["title"], "Lab report")
        self.assertEqual(data["tasks"][0]["due"], "2026-10-12T00:00:00Z")
        self.assertEqual(data["tasks"][0]["id"], "t1")
        self.assertEqual(data["tasks"][0]["attachments"], 1)
        self.assertEqual(data["courses"][0]["id"], None)
        self.assertEqual(data["threads"], [{"userId": "u1", "name": "T. Teacher", "role": "TEACHER",
                                            "last": "See you in class", "at": "2026-10-06T10:00:00Z", "status": "sent"}])
        self.assertEqual(len(data["attendance"]["records"]), 1)
        eol = data["eol"][0]
        self.assertEqual((eol["id"], eol["testId"], eol["canAttempt"], eol["exits"], eol["exitMax"]),
                         ("e-uuid", "PHY001", True, 1, 3))
        self.assertEqual(data["assessments"][0]["id"], "a-uuid")
        ann = data["announcements"][0]
        self.assertEqual(ann["message"], "Hi all")
        self.assertEqual(ann["html"], "<p>Hi <b>all</b></p>")
        self.assertEqual(ann["files"], [{"name": "sheet.pdf", "url": "https://s3.test/sheet.pdf", "type": "file", "size": None}])
        self.assertEqual(data["notifications"][0]["subject"], "Physics")
        self.assertEqual(data["resources"], [{"title": "Notes", "name": "notes.pdf", "subject": "Physics",
                                              "teacher": "T", "folder": None}])

    def test_failed_section_does_not_break_build(self):
        self.assertEqual(lmsdata.safe(lambda: {"detail": "Not found."}, []), [])
        self.assertEqual(lmsdata.safe(lambda: {"status": 500, "text": "oops"}, {}), {})
        self.assertEqual(lmsdata.safe(lambda: 1 / 0, []), [])
        self.assertEqual(lmsdata.safe(lambda: {"status": "ok", "results": [1]}, []), {"status": "ok", "results": [1]})
        self.assertEqual(lmsdata.results({"results": [1, 2]}), [1, 2])
        self.assertEqual(lmsdata.results([3]), [3])
        self.assertEqual(lmsdata.results(None), [])

    def test_clean_name(self):
        self.assertEqual(lmsdata.clean_name('a/b:c?'), "a_b_c_")
        self.assertEqual(lmsdata.clean_name(None), "untitled")


if __name__ == "__main__":
    unittest.main()
