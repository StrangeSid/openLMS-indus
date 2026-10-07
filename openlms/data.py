# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch a student's LMS data and shape it into the `window.LMS` object the UI renders."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor

import lms


def clean_name(s: str | None) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s or "untitled").strip()[:120]


def strip_html(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def resource_tree(tok: str, tid: str, parent: str | None = None, depth: int = 0) -> list[dict]:
    items, page = [], 1
    while True:
        data = lms.list_resources(tok, tid, None, parent, page, 100)
        results = data.get("results") or []
        if parent is None:
            results = [r for r in results if not r.get("parent_resource_id")] or results
        folders = [r for r in results if r.get("is_folder") and depth < 6]
        with ThreadPoolExecutor(max_workers=8) as pool:
            for r, children in zip(folders, pool.map(lambda f: resource_tree(tok, tid, f["id"], depth + 1), folders)):
                r["children"] = children
        items += results
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


def build(tok: str, tid: str, files: list[dict] | None = None, live: bool = False) -> dict:
    """Return the UI data object. Pass pre-fetched `files` to reuse a resource walk.

    In live mode every file gets a `path` served by the backend's file proxy.
    """
    calls = {
        "courses": lambda: lms.my_courses(tok, tid),
        "me": lambda: lms.me(tok),
        "eol": lambda: lms.eol_tests(tok, tid),
        "assessments": lambda: lms.assessments(tok),
        "notes": lambda: lms.notifications(tok, tid, 100),
        "att": lambda: lms.attendance(tok),
        "announcements": lambda: lms.announcements(tok),
        "calendar": lambda: lms.calendar_events(tok),
    }
    if files is None:
        calls["files"] = lambda: flatten(resource_tree(tok, tid))
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        r = dict(zip(calls, pool.map(lambda f: f(), calls.values())))
    files = r.get("files", files)
    courses_raw, notes, att = r["courses"], r["notes"], r["att"]
    courses = [c for c in courses_raw.get("courses", []) if c.get("title") != "Assembly"]
    grade = next((cl.get("grade") for c in courses for cl in c.get("classes") or [] if cl.get("grade")), "")
    if live:
        for f in files:
            f["path"] = f"api/files/{f['id']}/{f['file_id']}"

    return {
        "live": live,
        "student": r["me"].get("full_name"),
        "programCode": courses_raw.get("program_code") or "DP",
        "program": " · ".join(filter(None, [courses_raw.get("program_code"), grade])),
        "year": courses_raw.get("academic_year"),
        "courses": [{
            "title": c["title"], "level": c.get("subject_level"), "code": c.get("code"),
            "teacher": (c.get("teachers") or [{}])[0].get("full_name"),
        } for c in courses],
        "eol": [{
            "title": e["title"], "subject": e["subject"], "topic": e.get("topic"), "status": e["status"],
            "score": e.get("score"), "total": e.get("total_marks"), "teacher": e.get("teacher_name"),
            "assigned": e.get("assigned_at"), "due": e.get("available_until"), "opens": e.get("available_from"),
            "submitted": e.get("submitted_at"), "availability": e.get("availability_status"),
        } for e in r["eol"].get("results", [])],
        "assessments": [{
            "title": a["assessment"]["title"], "subject": a["assessment"]["subject"],
            "type": a["assessment"].get("assessment_type"), "category": a["assessment"].get("category"),
            "due": a["assessment"].get("due_date"), "status": a["status"], "marks": a.get("marks"),
            "total": a.get("total_marks"), "teacher": a["assessment"].get("teacher_name"),
            "submitted": a.get("submitted_at"), "assigned": a.get("assigned_at"),
        } for a in r["assessments"].get("results", [])],
        "unread": notes.get("unread_count", 0),
        "notifications": [{
            "title": n["title"], "message": n.get("message"), "type": n.get("type"),
            "actor": n.get("actor_name"), "at": n.get("created_at"), "read": n.get("is_read"),
        } for n in notes.get("results", [])[:25]],
        "attendance": {
            **{k: att.get(k) for k in ("total_sessions", "present", "absent", "late", "percentage")},
            "records": [{"date": r["date"], "status": r["status"], "subject": r.get("subject")}
                        for r in att.get("records", []) if not r.get("is_calendar_event")],
        },
        "announcements": [{
            "title": a["title"], "subject": a.get("subject"), "by": (a.get("creator") or {}).get("full_name"),
            "at": a.get("created_at"), "message": strip_html(a.get("message"))[:280], "files": len(a.get("file_urls") or []),
        } for a in r["announcements"]],
        "calendar": sorted(({
            "date": e["date"], "end": e.get("end_date"), "type": e.get("type"), "label": e.get("comment"),
        } for e in r["calendar"].get("events", [])), key=lambda e: e["date"]),
        "resources": [{k: v for k, v in f.items() if k not in ("id", "file_id", "dir")} for f in files],
        "downloaded": live or any("path" in f for f in files),
    }
