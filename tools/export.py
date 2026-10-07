#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Export your Indus LMS data to web/data.js (read-only).

Requires induslms-agent (`pip install induslms-agent`) and a token from
`induslms login you@school.example`.

    python3 tools/export.py                # write web/data.js
    python3 tools/export.py --files        # also download shared files to web/files/
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

try:
    import lms
except ImportError:
    sys.exit("induslms-agent is not installed. Run: pip install induslms-agent")

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def clean_name(s: str | None) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s or "untitled").strip()[:120]


def strip_html(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def session() -> tuple[str, str]:
    token = lms.load_token()
    if not token or not token.get("access"):
        sys.exit("No LMS token. Run: induslms login you@school.example")
    roles = (token.get("user") or {}).get("roles") or []
    tenant = (roles[0].get("tenant_id") if roles else None) or os.environ.get("INDUSLMS_TENANT")
    if not tenant:
        sys.exit("No tenant ID. Set INDUSLMS_TENANT or log in again.")
    return token["access"], tenant


def resource_tree(tok: str, tid: str, parent: str | None = None, depth: int = 0) -> list[dict]:
    items, page = [], 1
    while True:
        data = lms.list_resources(tok, tid, None, parent, page, 100)
        results = data.get("results") or []
        if parent is None:
            results = [r for r in results if not r.get("parent_resource_id")] or results
        for r in results:
            if r.get("is_folder") and depth < 6:
                r["children"] = resource_tree(tok, tid, r["id"], depth + 1)
            items.append(r)
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


def download(tok: str, tid: str, files: list[dict], dest: Path) -> None:
    ok = failed = 0
    for f in files:
        out = dest.joinpath(*f["dir"])
        existing = out / clean_name(f["name"])
        try:
            path = existing if existing.exists() else Path(
                lms.download_resource_file(tok, tid, f["id"], f["file_id"], out_dir=str(out))["path"])
            f["path"] = path.relative_to(WEB).as_posix()
            ok += 1
        except Exception as e:  # 403 = restricted by the teacher or another class
            failed += 1
            print(f"  skipped {f['title']}: {str(e)[:60]}", file=sys.stderr)
    print(f"files: {ok} downloaded, {failed} unavailable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", action="store_true", help="download shared files to web/files/")
    ap.add_argument("--out", default=str(WEB / "data.js"), help="output path (default: web/data.js)")
    args = ap.parse_args()

    tok, tid = session()
    me = lms.me(tok)
    courses_raw = lms.my_courses(tok, tid)
    courses = [c for c in courses_raw.get("courses", []) if c.get("title") != "Assembly"]
    grade = next((cl.get("grade") for c in courses for cl in c.get("classes") or [] if cl.get("grade")), "")

    eol = lms.eol_tests(tok, tid).get("results", [])
    assessments = lms.assessments(tok).get("results", [])
    notes = lms.notifications(tok, tid, 100)
    att = lms.attendance(tok)
    files = flatten(resource_tree(tok, tid))
    if args.files:
        download(tok, tid, files, WEB / "files")

    data = {
        "student": me.get("full_name"),
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
        } for e in eol],
        "assessments": [{
            "title": a["assessment"]["title"], "subject": a["assessment"]["subject"],
            "type": a["assessment"].get("assessment_type"), "category": a["assessment"].get("category"),
            "due": a["assessment"].get("due_date"), "status": a["status"], "marks": a.get("marks"),
            "total": a.get("total_marks"), "teacher": a["assessment"].get("teacher_name"),
            "submitted": a.get("submitted_at"), "assigned": a.get("assigned_at"),
        } for a in assessments],
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
        } for a in lms.announcements(tok)],
        "calendar": sorted(({
            "date": e["date"], "end": e.get("end_date"), "type": e.get("type"), "label": e.get("comment"),
        } for e in lms.calendar_events(tok).get("events", [])), key=lambda e: e["date"]),
        "resources": [{k: v for k, v in f.items() if k not in ("id", "file_id", "dir")} for f in files],
        "downloaded": args.files,
    }
    Path(args.out).write_text("window.LMS = " + json.dumps(data, default=str) + ";\n")
    print(f"wrote {args.out}: {len(data['courses'])} classes, "
          f"{len(data['eol']) + len(data['assessments'])} assignments, {len(files)} files")


if __name__ == "__main__":
    main()
