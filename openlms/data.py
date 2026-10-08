# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch a student's LMS data and shape it into the `window.LMS` object the UI renders."""

from __future__ import annotations

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor

import lms

# Shared pools: one for the top-level section fan-out, one for the
# resource folder crawl. Previously each /data.js hit built a pool per
# call and resource_tree() built a pool per page per level.
_POOL_WORKERS = int(os.environ.get("OPENLMS_POOL_WORKERS", "16"))
_POOL: ThreadPoolExecutor | None = None
_POOL_LOCK = None


def _pool() -> ThreadPoolExecutor:
    global _POOL, _POOL_LOCK
    import threading

    if _POOL is None:
        if _POOL_LOCK is None:
            _POOL_LOCK = threading.Lock()
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = ThreadPoolExecutor(max_workers=_POOL_WORKERS, thread_name_prefix="openlms")
    return _POOL


def clean_name(s: str | None) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s or "untitled").strip()[:120]


def strip_html(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _resource_page(tok: str, tid: str, parent: str | None, page: int) -> dict:
    return lms.list_resources(tok, tid, None, parent, page, 100)


def _walk(tok: str, tid: str, folder_id: str, depth: int, ex: ThreadPoolExecutor) -> list[dict]:
    """Fetch one folder's children (single page loop), recursing via shared pool."""
    items, page = [], 1
    while True:
        data = _resource_page(tok, tid, folder_id, page)
        batch = data.get("results") or []
        sub = [r for r in batch if r.get("is_folder") and depth < 6]
        if sub:
            children = list(ex.map(lambda f: _walk(tok, tid, f["id"], depth + 1, ex), sub))
            for r, c in zip(sub, children):
                r["children"] = c
        items += batch
        if not data.get("next"):
            return items
        page += 1


def resource_tree(tok: str, tid: str, parent: str | None = None, depth: int = 0) -> list[dict]:
    """Full resource tree. One shared pool for the whole crawl (was: a pool
    per page per level). Top-level keeps the parent-less filter."""
    ex = _pool()
    items, page = [], 1
    while True:
        data = _resource_page(tok, tid, parent, page)
        batch = data.get("results") or []
        if parent is None:
            batch = [r for r in batch if not r.get("parent_resource_id")] or batch
        folders = [r for r in batch if r.get("is_folder") and depth < 6]
        if folders:
            children = list(ex.map(lambda f: _walk(tok, tid, f["id"], depth + 1, ex), folders))
            for r, c in zip(folders, children):
                r["children"] = c
        items += batch
        if not data.get("next"):
            return items
        page += 1


def flatten(items: list[dict], folders: tuple[str, ...] = ()) -> list[dict]:
    out = []
    for r in items:
        if r.get("is_folder"):
            out += flatten(r.get("children") or [], folders + (r.get("title"),))
            continue
        for f in r.get("file_urls") or []:
            out.append({
                "id": r["id"],
                "file_id": f.get("id") or f.get("file_id"),
                "title": r.get("title"),
                "name": f.get("name"),
                "subject": r.get("subject"),
                "teacher": r.get("teacher_name"),
                "folder": folders[-1] if folders else None,
                "dir": [clean_name(r.get("subject") or "Other"), *map(clean_name, folders)],
            })
    return out


def results(data) -> list:
    if isinstance(data, list):
        return data
    return (data or {}).get("results") or [] if isinstance(data, dict) else []


def assessments(tok: str, kind: str) -> list[dict]:
    items = []
    for page in range(1, 26):
        data = lms.assessments(tok, {"assessment_type": kind, "page": page, "page_size": 100})
        batch = results(data)
        items += batch
        if isinstance(data, list) or len(batch) < 100 or len(items) >= (data.get("count") or 0):
            return items
    return items


def safe(fn, default):
    """Run one LMS call; a failing section shouldn't take the whole page down."""
    try:
        out = fn()
    except Exception:
        return default
    failed = isinstance(out, dict) and (isinstance(out.get("status"), int) and out["status"] >= 400 or "detail" in out and len(out) <= 2)
    return default if failed else out


def build(tok: str, tid: str, files: list[dict] | None = None, live: bool = False) -> dict:
    """Return the UI data object. Pass pre-fetched `files` to reuse a resource walk.

    In live mode every file gets a `path` served by the backend's file proxy.
    """
    calls = {
        "courses": (lambda: lms.my_courses(tok, tid), {}),
        "me": (lambda: lms.me(tok), {}),
        "eol": (lambda: lms.eol_tests(tok, tid), {}),
        "fa": (lambda: assessments(tok, "FA"), []),
        "sa": (lambda: assessments(tok, "SA"), []),
        "tasks": (lambda: lms.api_get_json(tok, f"/api/v1/tenants/{tid}/assignments/student/list/"), []),
        "notes": (lambda: lms.notifications(tok, tid, 100), {}),
        "att": (lambda: lms.attendance(tok), {}),
        "announcements": (lambda: lms.announcements(tok), []),
        "calendar": (lambda: lms.calendar_events(tok), {}),
    }
    if files is None:
        calls["files"] = (lambda: flatten(resource_tree(tok, tid)), [])
    ex = _pool()
    r = dict(zip(calls, ex.map(lambda c: safe(*c), calls.values())))
    files = r.get("files", files)
    courses_raw, notes, att = r["courses"] or {}, r["notes"] or {}, r["att"] or {}
    courses = [c for c in courses_raw.get("courses", []) if c.get("title") != "Assembly"]
    grade = next((cl.get("grade") for c in courses for cl in c.get("classes") or [] if cl.get("grade")), "")
    if live:
        for f in files:
            f["path"] = f"api/files/{f['id']}/{f['file_id']}"

    return {
        "live": live,
        "student": (r["me"] or {}).get("full_name"),
        "programCode": courses_raw.get("program_code") or "DP",
        "program": " · ".join(filter(None, [courses_raw.get("program_code"), grade])),
        "year": courses_raw.get("academic_year"),
        "courses": [{
            "id": c.get("course_id"), "subject": c.get("subject"),
            "classId": next((cl.get("class_id") for cl in c.get("classes") or [] if cl.get("class_id")), None),
            "title": c["title"], "level": c.get("subject_level"), "code": c.get("code"),
            "teacher": (c.get("teachers") or [{}])[0].get("full_name"),
        } for c in courses],
        "eol": [{
            "title": e["title"], "subject": e["subject"], "topic": e.get("topic"), "status": e["status"],
            "score": e.get("score"), "total": e.get("total_marks"), "teacher": e.get("teacher_name"),
            "assigned": e.get("assigned_at"), "due": e.get("available_until"), "opens": e.get("available_from"),
            "submitted": e.get("submitted_at"), "availability": e.get("availability_status"),
            "testId": e.get("short_id"),
        } for e in results(r["eol"])],
        "assessments": [{
            "title": a["assessment"]["title"], "subject": a["assessment"]["subject"],
            "type": a["assessment"].get("assessment_type") or kind, "category": a["assessment"].get("category"),
            "due": a["assessment"].get("due_date"), "status": a.get("status"), "marks": a.get("marks"),
            "total": a.get("total_marks"), "teacher": a["assessment"].get("teacher_name"),
            "submitted": a.get("submitted_at"), "assigned": a.get("assigned_at"),
        } for kind in ("FA", "SA") for a in r[kind.lower()] if isinstance(a.get("assessment"), dict)],
        "tasks": [{
            "title": t.get("title") or "Assignment", "subject": t.get("subject") or t.get("course_title"),
            "due": t.get("due_date"), "status": t.get("status"), "submitted": t.get("submitted_at"),
            "assigned": t.get("created_at") or t.get("assigned_at"), "teacher": t.get("teacher_name"),
        } for t in results(r["tasks"])],
        "unread": notes.get("unread_count", 0),
        "notifications": [{
            "title": n["title"], "message": n.get("message"), "type": n.get("type"),
            "actor": n.get("actor_name"), "at": n.get("created_at"), "read": n.get("is_read"), "link": n.get("link"),
            "courseId": n.get("course_id"),
        } for n in results(notes)[:25]],
        "attendance": {
            **{k: att.get(k) for k in ("total_sessions", "present", "absent", "late", "percentage")},
            "records": [{"date": r["date"], "status": r["status"], "subject": r.get("subject")}
                        for r in att.get("records", []) if not r.get("is_calendar_event")],
        },
        "announcements": [{
            "title": a["title"], "subject": a.get("subject"), "by": (a.get("creator") or {}).get("full_name"),
            "at": a.get("created_at"), "message": strip_html(a.get("message"))[:280], "files": len(a.get("file_urls") or []),
        } for a in results(r["announcements"])],
        "calendar": sorted(({
            "date": e["date"], "end": e.get("end_date"), "type": e.get("type"), "label": e.get("comment"),
        } for e in (r["calendar"] or {}).get("events", [])), key=lambda e: e["date"]),
        "resources": [{k: v for k, v in f.items() if k not in ("id", "file_id", "dir")} for f in files],
        "downloaded": live or any("path" in f for f in files),
    }
