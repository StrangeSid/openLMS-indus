# SPDX-License-Identifier: GPL-3.0-or-later
"""In-app LMS routes: detail views and every write, served same-origin.

    browser ──► /api/... (this module) ──► api.induslms.com

The LMS only allows CORS from induslms.com and its tokens are origin-bound,
so the browser cannot call it directly; these routes do it with the
student's server-side session. GETs are cached per student for five
minutes (`OPENLMS_DETAIL_TTL`) and retried once after a forced token
refresh on 401. Writes are never retried and drop the caches they affect.
"""

from __future__ import annotations

import json
import re

import lms
import requests
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from openlms import app as server
from openlms import cache as datacache
from openlms.data import (_pool, file_links, sanitize_html, shape_announcement, shape_notification,
                          shape_task, shape_thread, strip_html)

router = APIRouter(prefix="/api")

ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
SHORT_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_FILES = 10
MAX_FILE_BYTES = 25 * 1024 * 1024


# --- plumbing -----------------------------------------------------------------


def _ctx(request: Request):
    s = server.require(request)
    return s, datacache.get_entry(s.sid)


def _check(value: str, pattern: re.Pattern = ID) -> str:
    if not pattern.match(value or ""):
        raise HTTPException(404, "Not found.")
    return value


def _http_error(e: lms.LMSError) -> HTTPException:
    message = str(e)
    if e.status == 401:
        return HTTPException(401, "Your Indus LMS session expired. Sign in again.")
    if e.status >= 500:
        return HTTPException(502, {"message": f"Indus LMS had a problem: {message}", "code": e.code})
    return HTTPException(e.status, {"message": message, "code": e.code})


def upstream(s, fn, *args, write: bool = False, **kwargs):
    """Call an `lms` function with a fresh token (first positional argument).

    Reads retry once after a forced refresh on 401; writes never retry.
    """
    try:
        try:
            return fn(server.fresh(s), *args, **kwargs)
        except lms.LMSError as e:
            if e.status != 401 or write:
                raise
            return fn(server.fresh(s, force=True), *args, **kwargs)
    except lms.LMSError as e:
        raise _http_error(e)
    except ValueError as e:
        raise HTTPException(400, {"message": str(e)})
    except requests.RequestException:
        raise HTTPException(502, {"message": "Couldn't reach Indus LMS. Try again shortly."})


def _memo(entry, key: str, fn, ttl: float | None = None, refresh: bool = False):
    return datacache.memo(entry, key, fn, ttl=ttl, refresh=refresh)


def _optional(fn):
    """Run a detail read where 404 just means 'nothing yet'."""
    try:
        return fn()
    except HTTPException as e:
        if e.status_code == 404:
            return None
        raise


def _uid(s) -> str:
    """The student's LMS user id (older sessions predate storing it)."""
    if not s.uid:
        me = upstream(s, lms.me)
        s.uid = (me or {}).get("id")
        if not s.uid:
            raise HTTPException(502, {"message": "Indus LMS didn't say who you are. Sign in again."})
        server.sessions.save(s)
    return s.uid


def _payload(s) -> dict:
    return server.live_data(s)


def _patch_payload(entry, change) -> None:
    """Apply `change(payload_copy)` to the cached payload without extending its TTL."""
    if entry is None:
        return
    with entry.lock:
        if entry.payload is None:
            return
        patched = json.loads(json.dumps(entry.payload, default=str))
        change(patched)
        datacache.put_payload(entry, patched, keep_age=True)


def _after_write(entry, *prefixes: str, lists: bool = False) -> None:
    datacache.forget(entry, *prefixes)
    if lists:
        datacache.expire_payload(entry)


def _uploads(files: list[UploadFile]) -> list[tuple[str, bytes, str | None]]:
    files = [f for f in files or [] if f and f.filename]
    if len(files) > MAX_FILES:
        raise HTTPException(400, {"message": f"Attach at most {MAX_FILES} files."})
    out = []
    for f in files:
        data = f.file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, {"message": f"{f.filename} is larger than 25 MB."})
        name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", f.filename).strip() or "file"
        out.append((name[:150], data, f.content_type or None))
    return out


def _json_list(raw: str, what: str) -> list:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        raise HTTPException(400, {"message": f"Invalid {what}."})
    if not isinstance(value, list):
        raise HTTPException(400, {"message": f"Invalid {what}."})
    return value


# --- overview -----------------------------------------------------------------


@router.get("/today")
def today(request: Request):
    """Everything due, in one fan-out (served from the per-student cache)."""
    s, _ = _ctx(request)
    p = _payload(s)
    return {k: p.get(k) for k in ("student", "unread", "courses", "eol", "assessments", "tasks", "calendar")}


@router.get("/assignments")
def assignments(request: Request):
    s, _ = _ctx(request)
    p = _payload(s)
    return {k: p.get(k) for k in ("courses", "eol", "assessments", "tasks")}


# --- EOL tests ----------------------------------------------------------------


def _options(q: dict) -> list[dict]:
    opts = []
    for key in "abcd":
        text = q.get(f"option_{key}_text")
        image = q.get(f"option_{key}_image_url")
        if text is None and isinstance(q.get("options"), dict):
            o = q["options"].get(key) or {}
            text, image = (o.get("text"), o.get("image")) if isinstance(o, dict) else (o, None)
        if text or image:
            opts.append({"key": key, "html": sanitize_html(text), "image": image})
    return opts


def shape_question(q: dict) -> dict:
    # Attempt questions carry `id`; stored result responses carry `question_id`.
    # The result view's Explain button posts this id back, so map both.
    return {"id": q.get("id") or q.get("question_id"), "html": sanitize_html(q.get("question_text")), "image": q.get("question_image_url"),
            "marks": q.get("marks"), "options": _options(q)}


def shape_result(r: dict | None) -> dict | None:
    if not isinstance(r, dict):
        return None
    score = r.get("score") or {}
    return {
        "submissionId": r.get("submission_id"),
        "score": score.get("score"), "total": score.get("total_marks"),
        "percentage": score.get("percentage"), "submittedAt": score.get("submitted_at"),
        "responses": [{
            **shape_question(x),
            "selected": (x.get("selected_option") or "").lower() or None,
            "correct": (x.get("correct_option") or "").lower() or None,
            "isCorrect": x.get("is_correct"), "awarded": x.get("marks_awarded"),
            "note": x.get("ai_explanation") or None,
        } for x in r.get("responses") or []],
    }


def _eol_row(s, test_id: str) -> dict | None:
    return next((e for e in _payload(s).get("eol") or [] if test_id in (e.get("id"), e.get("testId"))), None)


@router.get("/eol/{test_id}")
def eol_detail(test_id: str, request: Request, refresh: bool = False):
    s, entry = _ctx(request)
    row = _eol_row(s, _check(test_id, SHORT_ID if not ID.match(test_id) else ID))
    if row is None:
        raise HTTPException(404, {"message": "This test isn't in your list."})
    done = bool(row.get("submitted")) or str(row.get("status")).lower() in ("submitted", "graded", "completed")
    out = {"test": row, "result": None, "feedback": []}
    if done and row.get("id"):
        uid = _uid(s)
        result = _optional(lambda: _memo(entry, f"eol:result:{row['id']}",
                                         lambda: upstream(s, lms.eol_result, s.tenant, row["id"], uid), refresh=refresh))
        out["result"] = shape_result(result)
        out["feedback"] = _optional(lambda: _memo(entry, f"eol:feedback:{row['id']}",
                                                  lambda: upstream(s, lms.eol_feedback, s.tenant, row["id"]))) or []
    return out


class EolOpen(BaseModel):
    short_id: str
    passcode: str


@router.post("/eol/open")
def eol_open(body: EolOpen, request: Request):
    """Open a test with its passcode. The passcode is never stored; the page
    keeps it in memory for the submit call."""
    s, _ = _ctx(request)
    _check(body.short_id.strip(), SHORT_ID)
    row = _eol_row(s, body.short_id.strip())
    if row:
        if row.get("suspended"):
            raise HTTPException(409, {"message": "This test was stopped for leaving the page. Contact your teacher.", "code": "proctor_suspended"})
        if row.get("blocked") or (row.get("exits") or 0) >= (row.get("exitMax") or 3):
            raise HTTPException(409, {"message": "All attempts used. Contact your teacher.", "code": "attempts_exceeded"})
        if row.get("expired"):
            raise HTTPException(409, {"message": row.get("expiresMessage") or "This test has expired.", "code": "expired"})
    test = upstream(s, lms.eol_open, s.tenant, body.short_id, body.passcode, write=True)
    return {
        "id": test.get("id"), "shortId": test.get("short_id") or body.short_id.strip(), "title": test.get("title"),
        "subject": test.get("subject"), "topic": test.get("topic"), "total": test.get("total_marks"),
        "alreadySubmitted": bool(test.get("already_submitted")),
        "questions": [shape_question(q) for q in test.get("questions") or []],
    }


class EolSubmit(BaseModel):
    passcode: str
    answers: dict[str, str]


@router.post("/eol/{test_uuid}/submit")
def eol_submit(test_uuid: str, body: EolSubmit, request: Request):
    """Submit once. Never retried: a failure is reported so the student decides."""
    s, entry = _ctx(request)
    _check(test_uuid)
    submission = upstream(s, lms.eol_submit, s.tenant, test_uuid, body.passcode, body.answers, write=True)
    _after_write(entry, f"eol:result:{test_uuid}", f"eol:feedback:{test_uuid}", lists=True)
    result = None
    try:
        result = shape_result(lms.eol_result(server.fresh(s), s.tenant, test_uuid, _uid(s)))
    except Exception:
        pass  # the score below is enough; the result view loads it later
    return {"score": submission.get("score"), "total": submission.get("total_marks"),
            "percent": submission.get("percent"), "submittedAt": submission.get("submitted_at"), "result": result}


class ProctorEvent(BaseModel):
    event_type: str = "document_visibility_hidden"


@router.post("/eol/{test_uuid}/proctor")
def eol_proctor(test_uuid: str, body: ProctorEvent, request: Request):
    s, entry = _ctx(request)
    _check(test_uuid)
    if body.event_type not in ("document_visibility_hidden",):
        raise HTTPException(400, {"message": "Unknown event."})
    out = upstream(s, lms.eol_proctor_event, s.tenant, test_uuid, body.event_type, write=True)
    if out.get("proctor_suspended"):
        _after_write(entry, lists=True)
    return {"violations": out.get("proctor_violation_count"), "threshold": out.get("suspend_threshold") or 4,
            "suspended": bool(out.get("proctor_suspended"))}


class Explain(BaseModel):
    question_id: str


@router.post("/eol/{test_id}/explain")
def eol_explain(test_id: str, body: Explain, request: Request):
    """AI learning note for one answered question (built from the stored result,
    so the page cannot send arbitrary text)."""
    s, entry = _ctx(request)
    _check(test_id)
    uid = _uid(s)
    raw = _memo(entry, f"eol:result:{test_id}", lambda: upstream(s, lms.eol_result, s.tenant, test_id, uid))
    q = next((x for x in (raw or {}).get("responses") or [] if x.get("question_id") == body.question_id), None)
    if q is None:
        raise HTTPException(404, {"message": "Question not found in your result."})
    if q.get("ai_explanation"):
        return {"explanation": q["ai_explanation"], "cached": True}
    options = {o["key"]: strip_html(o["html"]) for o in _options(q)}
    out = upstream(s, lms.eol_explain, s.tenant, test_id, uid, submission_id=raw.get("submission_id"),
                   question_id=q.get("question_id"), question_text=strip_html(q.get("question_text")),
                   options=options, selected_option=q.get("selected_option"), correct_option=q.get("correct_option"),
                   is_correct=q.get("is_correct"), write=True)
    datacache.forget(entry, f"eol:result:{test_id}")
    return {"explanation": out.get("explanation") or out.get("text"), "cached": bool(out.get("cached"))}


# --- FA / SA ------------------------------------------------------------------


def _fa_rows(s, entry, refresh: bool = False) -> list:
    return _memo(entry, "fa:list", lambda: upstream(s, lms.assessments_all), refresh=refresh)


def _fa_row(s, entry, aid: str) -> dict:
    row = next((r for r in _fa_rows(s, entry) if (r.get("assessment") or {}).get("id") == aid), None)
    if row is None:
        row = next((r for r in _fa_rows(s, entry, refresh=True) if (r.get("assessment") or {}).get("id") == aid), None)
    if row is None:
        raise HTTPException(404, {"message": "This assessment isn't in your list."})
    return row


def shape_fa_question(q: dict) -> dict:
    kind = str(q.get("question_type") or q.get("type") or "").upper()
    return {"id": q.get("id"), "type": "mcq" if kind == "MCQ" else "text",
            "html": sanitize_html(q.get("question_text") or q.get("text") or q.get("question")),
            "image": q.get("question_image_url") or q.get("image_url"), "marks": q.get("marks"),
            "options": _options(q) or [{"key": str(o.get("key") or o.get("id") or i), "html": sanitize_html(o.get("text") or o.get("label")), "image": None}
                                       for i, o in enumerate(q.get("options") or []) if isinstance(o, dict)]}


def shape_fa(row: dict) -> dict:
    a = row.get("assessment") or {}
    return {
        "id": a.get("id"), "title": a.get("title"), "subject": a.get("subject"), "type": a.get("assessment_type"),
        "category": a.get("category"), "due": a.get("due_date"), "status": row.get("status"),
        "marks": row.get("marks"), "total": row.get("total_marks") or a.get("total_marks"),
        "teacher": a.get("teacher_name"), "assigned": row.get("assigned_at"), "submitted": row.get("submitted_at"),
        "graded": row.get("graded_at"), "instructions": sanitize_html(a.get("instructions")),
        "files": file_links(a.get("file_urls")), "questionFile": file_links([row["question_file"]]) if row.get("question_file") else [],
        "questions": [shape_fa_question(q) for q in a.get("questions") or [] if isinstance(q, dict)],
        "submissionOpen": a.get("submission_open"), "marking": a.get("marking_mode"),
        "awaitingWork": row.get("awaiting_work"), "studentFiles": file_links(row.get("student_submission_files")),
    }


def shape_submission(x: dict | None) -> dict | None:
    if not isinstance(x, dict) or not (x.get("submitted_at") or x.get("submission_urls")):
        return None
    return {"files": file_links(x.get("submission_urls")), "comment": x.get("comment") or "",
            "submittedAt": x.get("submitted_at"), "status": x.get("status"), "answers": x.get("answers") or []}


def shape_feedback(x: dict | None) -> dict | None:
    if not isinstance(x, dict) or not x.get("has_feedback", True):
        return None
    rubric = x.get("rubric_scores") or []
    if isinstance(rubric, dict):
        rubric = [{"criterion": k, "score": v} for k, v in rubric.items()]
    return {"score": x.get("total_score"), "html": sanitize_html(x.get("feedback_text")),
            "remarks": sanitize_html(x.get("final_remarks")), "rubric": rubric,
            "files": file_links(x.get("annotated_files")), "grader": x.get("grader"), "at": x.get("updated_at")}


def _requests(s, entry, aid: str) -> dict:
    data = _memo(entry, f"fa:req:{aid}", lambda: upstream(s, lms.request_summary, [aid]))
    item = (data.get("items") or {}).get(aid) or {}
    return {"enabled": bool(data.get("enabled")), "min": data.get("reason_min_length") or 10,
            "max": data.get("reason_max_length") or 500, **item}


@router.get("/fa/{aid}")
def fa_detail(aid: str, request: Request):
    s, entry = _ctx(request)
    _check(aid)
    row = _fa_row(s, entry, aid)
    ex = _pool()
    sub = ex.submit(lambda: _optional(lambda: _memo(entry, f"fa:sub:{aid}", lambda: upstream(s, lms.assessment_submission, aid))))
    fb = ex.submit(lambda: _optional(lambda: _memo(entry, f"fa:fb:{aid}", lambda: upstream(s, lms.assessment_feedback, aid))))
    req = ex.submit(lambda: _optional(lambda: _requests(s, entry, aid)))
    return {"assessment": shape_fa(row), "submission": shape_submission(sub.result()),
            "feedback": shape_feedback(fb.result()), "requests": req.result()}


@router.get("/fa/{aid}/submission")
def fa_submission(aid: str, request: Request):
    s, entry = _ctx(request)
    _check(aid)
    return shape_submission(_optional(lambda: _memo(entry, f"fa:sub:{aid}", lambda: upstream(s, lms.assessment_submission, aid))))


@router.get("/fa/{aid}/feedback")
def fa_feedback(aid: str, request: Request):
    s, entry = _ctx(request)
    _check(aid)
    return shape_feedback(_optional(lambda: _memo(entry, f"fa:fb:{aid}", lambda: upstream(s, lms.assessment_feedback, aid))))


@router.get("/requests")
def requests_summary(ids: str, request: Request):
    s, entry = _ctx(request)
    wanted = [_check(i.strip()) for i in ids.split(",") if i.strip()][:200]
    return upstream(s, lms.request_summary, wanted)


@router.post("/fa/{aid}/submit")
def fa_submit(aid: str, request: Request, comment: str = Form(""), responses: str = Form("[]"),
              files: list[UploadFile] = File(default=[])):
    """Hand in an FA/SA: answers for question tests, files for upload tests."""
    s, entry = _ctx(request)
    _check(aid)
    row = _fa_row(s, entry, aid)
    questions = (row.get("assessment") or {}).get("questions") or []
    uploads = _uploads(files)
    answers = _json_list(responses, "answers")
    if not questions and not uploads:
        raise HTTPException(400, {"message": "Attach your work before submitting."})
    urls = [f["file_url"] for f in upstream(s, lms.upload_files, s.tenant, lms.ASSESSMENT_UPLOAD_MODULE, uploads, write=True)] if uploads else []
    if questions:
        clean = []
        for a in answers:
            if not isinstance(a, dict) or not a.get("question_id"):
                continue
            item = {"question_id": str(a["question_id"])}
            if "selected_option" in a:
                item["selected_option"] = str(a["selected_option"])
            else:
                item["answer_text"] = str(a.get("answer_text") or "")
            clean.append(item)
        out = upstream(s, lms.assessment_submit_questions, aid, clean, urls, comment, write=True)
    else:
        out = upstream(s, lms.assessment_submit_upload, aid, urls, comment, write=True)
    _after_write(entry, "fa:", lists=True)
    return {"ok": True, "result": out}


@router.post("/fa/{aid}/resubmit")
def fa_resubmit(aid: str, request: Request, keep: str = Form("[]"), comment: str = Form(""),
                base_submitted_at: str = Form(""), files: list[UploadFile] = File(default=[])):
    s, entry = _ctx(request)
    _check(aid)
    keep_indexes = [int(i) for i in _json_list(keep, "files to keep") if str(i).isdigit()]
    uploads = _uploads(files)
    if not keep_indexes and not uploads:
        raise HTTPException(400, {"message": "Keep or attach at least one file."})
    urls = [f["file_url"] for f in upstream(s, lms.upload_files, s.tenant, lms.ASSESSMENT_UPLOAD_MODULE, uploads, write=True)] if uploads else []
    out = upstream(s, lms.assessment_resubmit, aid, keep_indexes, urls, comment, base_submitted_at or None, write=True)
    _after_write(entry, "fa:", lists=True)
    return {"ok": True, "result": out}


class RequestBody(BaseModel):
    request_type: str
    reason: str
    preferred_due_at: str | None = None


@router.post("/fa/{aid}/request")
def fa_request(aid: str, body: RequestBody, request: Request):
    s, entry = _ctx(request)
    _check(aid)
    reason = body.reason.strip()
    if not 10 <= len(reason) <= 500:
        raise HTTPException(400, {"message": "Give a reason between 10 and 500 characters."})
    out = upstream(s, lms.assessment_request, aid, body.request_type, reason, body.preferred_due_at or None, write=True)
    _after_write(entry, f"fa:req:{aid}")
    return {"ok": True, "request": out}


@router.post("/requests/{rid}/cancel")
def request_cancel(rid: str, request: Request):
    s, entry = _ctx(request)
    _check(rid)
    out = upstream(s, lms.request_cancel, rid, write=True)
    _after_write(entry, "fa:req:")
    return {"ok": True, "request": out}


# --- Learning tasks -----------------------------------------------------------


@router.get("/tasks")
def tasks(request: Request, refresh: bool = False):
    s, entry = _ctx(request)
    rows = _memo(entry, "task:list", lambda: upstream(s, lms.learning_tasks, s.tenant), refresh=refresh)
    return [shape_task(t) for t in rows]


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, request: Request):
    s, entry = _ctx(request)
    _check(task_id)
    ex = _pool()
    rows = ex.submit(lambda: _memo(entry, "task:list", lambda: upstream(s, lms.learning_tasks, s.tenant)))
    detail = _memo(entry, f"task:{task_id}", lambda: upstream(s, lms.learning_task_detail, s.tenant, task_id))
    row = next((t for t in rows.result() if t.get("id") == task_id), {})
    a = detail.get("assignment") or {}
    sub = detail.get("submission") if isinstance(detail.get("submission"), dict) else None
    return {
        "id": task_id, "title": a.get("title") or row.get("title"), "subject": a.get("subject") or row.get("subject"),
        "due": a.get("due_date") or row.get("due_date"), "status": detail.get("recipient_status") or row.get("status"),
        "instructions": sanitize_html(row.get("instructions") or a.get("instructions")),
        "attachments": file_links(row.get("attachments") or a.get("attachments")),
        "score": detail.get("score") if detail.get("score") is not None else row.get("score"),
        "grade": detail.get("grade") or row.get("grade") or None,
        "feedback": sanitize_html(detail.get("feedback_text") or row.get("feedback_text")),
        "submission": {"files": file_links(sub.get("submission_files") or sub.get("files")),
                       "text": sub.get("submission_text") or "", "submittedAt": sub.get("submitted_at")} if sub else None,
    }


@router.post("/tasks/{task_id}/submit")
def task_submit(task_id: str, request: Request, text: str = Form(""), files: list[UploadFile] = File(default=[])):
    s, entry = _ctx(request)
    _check(task_id)
    uploads = _uploads(files)
    if not uploads:
        raise HTTPException(400, {"message": "Attach at least one file."})
    uploaded = upstream(s, lms.upload_files, s.tenant, lms.TASK_UPLOAD_MODULE, uploads, write=True)
    out = upstream(s, lms.task_submit, s.tenant, task_id, uploaded, text, write=True)
    _after_write(entry, "task:", lists=True)
    return {"ok": True, "result": out}


# --- Announcements, notifications ---------------------------------------------


@router.get("/announcements")
def announcements(request: Request, q: str = ""):
    s, _ = _ctx(request)
    items = _payload(s).get("announcements") or []
    q = q.strip().lower()
    if q:
        items = [a for a in items if q in " ".join(str(a.get(k) or "") for k in ("title", "message", "by", "subject")).lower()]
    return items


@router.post("/announcements/{ann_id}/read")
def announcement_read(ann_id: str, request: Request):
    s, _ = _ctx(request)
    _check(ann_id)
    out = upstream(s, lms.announcement_read, ann_id, write=True)
    return {"ok": True, "recorded": bool(out.get("recorded", True))}


@router.get("/notifications")
def notifications(request: Request, limit: int = 20, offset: int = 0, filter: str = "all", q: str = ""):
    s, _ = _ctx(request)
    limit, offset = max(1, min(limit, 100)), max(0, offset)
    data = upstream(s, lms.notifications, s.tenant, limit, offset)
    raw = data.get("results") or [] if isinstance(data, dict) else []
    items = [shape_notification(n) for n in raw]
    if filter == "unread":
        items = [n for n in items if not n["read"]]
    elif filter == "read":
        items = [n for n in items if n["read"]]
    q = q.strip().lower()
    if q:
        items = [n for n in items if q in f"{n['title']} {n['message']} {n['actor']}".lower()]
    return {"unread": data.get("unread_count", 0) if isinstance(data, dict) else 0, "items": items,
            "nextOffset": offset + limit if len(raw) == limit else None}


@router.post("/notifications/read-all")
def notifications_read_all(request: Request):
    s, entry = _ctx(request)
    upstream(s, lms.notifications_read_all, s.tenant, write=True)

    def change(p):
        p["unread"] = 0
        for n in p.get("notifications") or []:
            n["read"] = True
    _patch_payload(entry, change)
    return {"ok": True, "unread": 0}


@router.post("/notifications/{nid}/read")
def notification_read(nid: str, request: Request):
    s, entry = _ctx(request)
    _check(nid)
    upstream(s, lms.notification_read, s.tenant, nid, write=True)

    def change(p):
        for n in p.get("notifications") or []:
            if n.get("id") == nid and not n.get("read"):
                n["read"] = True
                p["unread"] = max(0, (p.get("unread") or 0) - 1)
    _patch_payload(entry, change)
    return {"ok": True}


# --- Messaging ----------------------------------------------------------------


def shape_message(m: dict, me: str | None) -> dict:
    return {"id": m.get("id"), "mine": bool(me) and m.get("from_user_id") == me, "from": m.get("from_user_name"),
            "to": m.get("to_user_name"), "text": m.get("text") or "", "at": m.get("sent_at"),
            "read": m.get("read_at"), "status": m.get("status_label") or m.get("status")}


@router.get("/messages/contacts")
def message_contacts(request: Request):
    s, entry = _ctx(request)
    rows = _memo(entry, "msg:contacts", lambda: upstream(s, lms.message_contacts, s.tenant), ttl=3600)
    return sorted(({"userId": c.get("user_id"), "name": c.get("full_name"), "role": c.get("role"),
                    "email": c.get("email"), "subjects": c.get("subject_label") or ", ".join(c.get("subjects") or [])}
                   for c in rows), key=lambda c: (c["name"] or "").lower())


@router.get("/messages/threads")
def message_threads(request: Request):
    s, entry = _ctx(request)
    rows = _memo(entry, "msg:threads", lambda: upstream(s, lms.message_threads, s.tenant), ttl=10)
    return sorted((shape_thread(t) for t in rows), key=lambda t: t["at"] or "", reverse=True)


@router.get("/messages/conversation/{user_id}")
def message_conversation(user_id: str, request: Request):
    s, entry = _ctx(request)
    _check(user_id)
    me = _uid(s)
    data = _memo(entry, f"msg:conv:{user_id}", lambda: upstream(s, lms.message_conversation, s.tenant, user_id), ttl=5)
    return {"messages": [shape_message(m, me) for m in (data or {}).get("results") or []]}


class Message(BaseModel):
    to_user_id: str
    text: str


@router.post("/messages")
def send_message(body: Message, request: Request):
    s, entry = _ctx(request)
    _check(body.to_user_id)
    text = body.text.strip()
    if not text or len(text) > 4000:
        raise HTTPException(400, {"message": "Write a message (up to 4000 characters)."})
    out = upstream(s, lms.send_message, s.tenant, body.to_user_id, text, write=True)
    _after_write(entry, "msg:threads", f"msg:conv:{body.to_user_id}")
    return shape_message(out, _uid(s))


# --- School: policies, reports, help, attendance, calendar ---------------------


@router.get("/policies")
def policies(request: Request):
    s, entry = _ctx(request)
    rows = _memo(entry, "school:policies", lambda: upstream(s, lms.policies, s.tenant), ttl=3600)
    return [{"id": p.get("id"), "title": p.get("title"), "description": p.get("description"),
             "url": p.get("file_url"), "version": p.get("version"), "status": p.get("status"),
             "updated": p.get("updated_at") or p.get("created_at")} for p in rows]


@router.get("/reports")
def reports(request: Request):
    s, entry = _ctx(request)
    data = _memo(entry, "school:reports", lambda: upstream(s, lms.progress_reports, s.tenant), ttl=3600)
    pdfs = (data or {}).get("pdfs") or [] if isinstance(data, dict) else []
    return {"total": len(pdfs), "reports": [{
        "title": p.get("title") or p.get("name") or p.get("term") or "Report",
        "url": p.get("pdf_url") or p.get("file_url") or p.get("url"),
        "term": p.get("term") or p.get("report_type"), "at": p.get("published_at") or p.get("created_at"),
    } for p in pdfs if isinstance(p, dict)]}


@router.get("/help")
def help_articles(request: Request):
    s, entry = _ctx(request)
    rows = _memo(entry, "school:help", lambda: upstream(s, lms.help_articles, s.tenant), ttl=3600)
    return [{"id": h.get("id"), "title": h.get("title"), "html": sanitize_html(h.get("content") or h.get("body") or h.get("description")),
             "url": h.get("video_url") or h.get("file_url") or h.get("url")} for h in rows]


@router.get("/attendance")
def attendance(request: Request):
    s, _ = _ctx(request)
    return _payload(s).get("attendance") or {}


@router.get("/attendance/day")
def attendance_day(request: Request):
    s, entry = _ctx(request)
    data = _memo(entry, "school:attendance-day", lambda: upstream(s, lms.attendance_day, s.tenant))
    if not isinstance(data, dict):
        return {"records": []}
    keys = ("total_working_days", "present_days", "absent_days", "late_days", "leave_days", "excused_days",
            "half_day_days", "attendance_percentage", "from_date", "to_date")
    return {**{k: data.get(k) for k in keys},
            "records": [{"date": r.get("date"), "status": r.get("status"), "reason": r.get("reason"),
                         "class": r.get("class") or r.get("class_name")} for r in data.get("records") or []]}


@router.get("/calendar")
def calendar(request: Request):
    s, _ = _ctx(request)
    return _payload(s).get("calendar") or []
