# SPDX-License-Identifier: GPL-3.0-or-later
"""openLMS server: per-student login to Indus LMS, live data and a file proxy.

    uvicorn openlms.app:app --port 8000

Passwords are forwarded to Indus LMS once and never stored. Each student's
tokens rest server-side in a SQLite file (0600, optional Fernet encryption
via OPENLMS_SECRET_KEY), keyed by a random HttpOnly session cookie, so a
restart no longer signs everyone out.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from pathlib import Path

import lms
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openlms.data import build, flatten, resource_tree, shape_resources
from openlms.sessions import Session, Store
from openlms import cache as datacache

WEB = Path(__file__).resolve().parent.parent / "web"
COOKIE = "openlms_sid"
DEMO_COOKIE = "openlms_demo"
LMS_WEB = "https://induslms.com"
SESSION_IDLE = 12 * 3600
WARM_ON_LOGIN = True
LOGIN_LIMIT = (10, 600)  # attempts per window (seconds), per client IP
UUIDISH = re.compile(r"^[0-9a-fA-F-]{8,64}$")
# Public hostnames the app is served under (e.g. behind Cloudflare/ngrok where
# the Host header seen by the app differs from the browser's Origin).
# Comma-separated extra hosts, e.g. OPENLMS_PUBLIC_HOST=example.com
# lms.sidevv.xyz is always allowed because the Cloudflare Origin Rule rewrites
# Host to the ngrok origin, so Origin/Host can never match without this.
PUBLIC_HOSTS = {"lms.sidevv.xyz"} | {
    h.strip().lower() for h in os.environ.get("OPENLMS_PUBLIC_HOST", "").split(",") if h.strip()
}


# Refresh the access token this many seconds before it expires, so a page
# load never pays a 401 -> refresh -> retry round trip.
REFRESH_MARGIN = 300

sessions = Store(idle=SESSION_IDLE)
attempts: dict[str, list[float]] = {}
# Pooled keep-alive connections to the LMS (shared with induslms-agent).
http = lms.HTTP
app = FastAPI(title="openLMS", docs_url=None, redoc_url=None, openapi_url=None)


def jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except Exception:
        return 0.0


def fresh(s: Session, force: bool = False) -> str:
    """Return a valid access token, refreshing it ahead of expiry (or when `force`d after a 401)."""
    with s.lock:
        if not force and jwt_exp(s.access) - time.time() > REFRESH_MARGIN:
            return s.access
        try:
            r = http.post(f"{lms.API_BASE}/api/token/refresh/", json={"refresh": s.refresh},
                          headers=lms.HEADERS_BASE, timeout=15)
        except requests.RequestException:
            raise HTTPException(502, "Couldn't reach Indus LMS. Try again shortly.")
        try:
            body = r.json()
            refreshed = r.ok and "access" in body
        except Exception:
            refreshed = False  # empty/non-JSON body: treat like a failed refresh
        if not refreshed:
            raise HTTPException(401, "Session expired. Sign in again.")
        s.access, s.refresh = body["access"], body.get("refresh", s.refresh)
        try:
            sessions.save(s)
        except Exception:
            pass
        return s.access


PARTIAL_SECTIONS = {"resources", "resourcesStale", "resourcesPending"}
CRAWL_WAIT = 45  # seconds a files-only request waits for the background crawl


def _spawn(fn) -> None:
    threading.Thread(target=fn, daemon=True).start()


def live_data(s: Session, refresh: bool = False, only: set[str] | None = None,
              wait_files: bool = False) -> dict:
    """Shared cached payload keyed by session id (singleflight).

    The slow resource crawl (~11 s cold, 33 requests) never blocks a page:
    the payload is built from the last known files (or none, flagged
    `resourcesPending`) while the crawl runs in the background and patches
    the cached payload when it finishes. Pages that show files ask for
    `?sections=resources,...&wait=1` to pick the fresh list up in place.
    """
    entry = datacache.get_entry(s.sid)
    if entry is None:  # no sid (tests): direct build, no caching
        return build(fresh(s), s.tenant, live=True)
    if only and only <= PARTIAL_SECTIONS and (refresh or wait_files):
        return _files_only(entry, s, force=refresh)
    with entry.lock:
        payload = datacache.get_payload(entry, refresh=refresh)
        if payload is None:
            fresh_files = None if refresh else datacache.get_files(entry)
            files = fresh_files if fresh_files is not None else datacache.get_files(entry, allow_stale=True)
            token, tenant = fresh(s), s.tenant
            payload = build(token, tenant, files=list(files or []), live=True)
            payload["resourcesStale"] = files is not None and fresh_files is None
            payload["resourcesPending"] = fresh_files is None
            datacache.put_payload(entry, payload)
    if payload.get("resourcesPending"):
        _start_crawl(entry, s)
    return entry.payload or payload


def _start_crawl(entry, s: Session) -> None:
    """Crawl resources in the background (one crawl per student at a time)."""
    with entry.crawl_lock:
        if entry.crawling:
            return
        entry.crawling = True
        entry.crawl_done.clear()
    sid = s.sid

    def run() -> None:
        files = None
        try:
            sess = sessions.get(sid) or s
            files = flatten(resource_tree(fresh(sess), sess.tenant))
        except Exception:
            files = None  # keep whatever we had; the payload is flagged stale
        try:
            with entry.lock:
                if files is not None:
                    datacache.put_files(entry, files)
                base = entry.payload
                if base is not None:
                    current = files if files is not None else datacache.get_files(entry, allow_stale=True) or []
                    patched = dict(base)
                    patched["resources"] = shape_resources(current, live=True)
                    patched["resourcesStale"] = files is None
                    patched["resourcesPending"] = False
                    datacache.put_payload(entry, patched, keep_age=True)
        finally:
            with entry.crawl_lock:
                entry.crawling = False
            entry.crawl_done.set()

    _spawn(run)


def _files_only(entry, s: Session, force: bool) -> dict:
    """Resources slice for in-place hot-swaps: start a crawl when asked (or
    when none has finished yet) and wait for it, never rebuilding the rest."""
    with entry.lock:
        has_files = datacache.get_files(entry) is not None
        cold = entry.payload is None
    if cold:
        live_data(s)
    if force or not has_files or entry.crawling:
        _start_crawl(entry, s)
        entry.crawl_done.wait(CRAWL_WAIT)
    return entry.payload or live_data(s)


def warm(s: Session) -> None:
    if WARM_ON_LOGIN and s.sid:
        sid = s.sid
        def _fill() -> None:
            try:
                sess = sessions.get(sid)
                if sess:
                    _quiet(live_data, sess)
            except Exception:
                pass
        threading.Thread(target=_fill, daemon=True).start()


def _quiet(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:
        pass


def current(request: Request) -> tuple[str | None, Session | None]:
    sid = request.cookies.get(COOKIE)
    return sid, sessions.get(sid)


def require(request: Request) -> Session:
    _, s = current(request)
    if not s:
        raise HTTPException(401, "Not signed in.")
    return s


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/files/"):  # exported personal files are never served to other users
        return PlainTextResponse("Not found", 404)
    if request.method not in ("GET", "HEAD") and path.startswith("/api/"):
        origin = request.headers.get("origin")
        host = (request.headers.get("host") or "").lower()
        forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip().lower()
        origin_host = origin.split("://", 1)[-1].lower() if origin else ""
        if (
            origin
            and origin_host != host
            and origin_host != forwarded_host
            and origin_host not in PUBLIC_HOSTS
        ):
            return JSONResponse({"detail": "Cross-site request blocked."}, 403)
    response = await call_next(request)
    if not path.startswith("/api/") and response.status_code in (200, 304):
        response.headers.setdefault("Cache-Control", "no-cache")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    return response


class Credentials(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(creds: Credentials, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    window = [t for t in attempts.get(ip, []) if time.time() - t < LOGIN_LIMIT[1]]
    if len(window) >= LOGIN_LIMIT[0]:
        raise HTTPException(429, "Too many sign-in attempts. Try again in a few minutes.")
    attempts[ip] = window + [time.time()]

    try:
        r = http.post(f"{lms.API_BASE}/api/v1/auth/login/", headers=lms.HEADERS_BASE, timeout=15,
                      json={"email": creds.email.strip(), "password": creds.password})
    except requests.RequestException:
        raise HTTPException(502, "Couldn't reach Indus LMS. Try again shortly.")
    try:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        raise HTTPException(502, "Indus LMS gave an unreadable reply. Try again shortly.")
    if not r.ok or "access" not in body:
        raise HTTPException(401, "Email or password is incorrect.")

    user = body.get("user") or {}
    roles = user.get("roles") or []
    tenant = (roles[0].get("tenant_id") if roles else None) or os.environ.get("INDUSLMS_TENANT")
    if not tenant:
        raise HTTPException(403, "This account has no school attached.")
    sid = sessions.add(Session(body["access"], body.get("refresh", ""), tenant, user))
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    is_secure = (
        request.url.scheme == "https"
        or forwarded_proto == "https"
        or os.environ.get("OPENLMS_SECURE_COOKIES") == "1"
    )
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_IDLE,
                        secure=is_secure)
    attempts.pop(ip, None)
    response.delete_cookie(DEMO_COOKIE)
    response.headers["Cache-Control"] = "no-store"
    warm(sessions.get(sid))
    return {"name": user.get("full_name")}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    sid, _ = current(request)
    sessions.drop(sid)
    datacache.drop(sid)
    response.delete_cookie(COOKIE)
    response.delete_cookie(DEMO_COOKIE)
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse("/assets/favicon.svg", 301)


@app.get("/api/demo")
def demo():
    response = RedirectResponse("../index.html", 303)
    response.set_cookie(DEMO_COOKIE, "1", samesite="lax", max_age=3600)
    return response


@app.get("/api/session")
def session_info(request: Request):
    s = require(request)
    return {"name": s.name, "email": s.email}


SECTIONS = ("live", "student", "programCode", "program", "year", "courses",
            "eol", "assessments", "tasks", "threads", "unread", "notifications",
            "attendance", "announcements", "calendar", "resources",
            "resourcesStale", "resourcesPending", "downloaded")

CACHE_HEADERS = {"Cache-Control": "private, max-age=60, must-revalidate"}


def _want_sections(sections: str | None) -> set[str] | None:
    if not sections:
        return None
    return {"live"} | {p.strip() for p in sections.split(",") if p.strip() in SECTIONS}


def _slice(payload: dict, want: set[str] | None) -> dict:
    if not want:
        return payload
    return {k: v for k, v in payload.items() if k in want}


def _conditional(request: Request, payload: dict, media_type: str) -> Response:
    etag = datacache.etag_for(payload)
    headers = {"ETag": etag, **CACHE_HEADERS}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if media_type == "text/javascript":
        # LMS_ETAG lets the page revalidate its saved copy later (If-None-Match).
        body = "window.LMS = " + json.dumps(payload, default=str) + ";window.LMS_ETAG = " + json.dumps(etag) + ";"
    else:
        body = json.dumps(payload, default=str)
    return Response(body, media_type=media_type, headers=headers)


@app.get("/data.js")
def data_js(request: Request, refresh: bool = False, sections: str | None = None):
    _, s = current(request)
    if not s:
        headers = {"Cache-Control": "no-store"}
        script = ("window.OPENLMS_DEMO = true;" if request.cookies.get(DEMO_COOKIE)
                  else "location.replace('login.html');")
        return Response(script, media_type="text/javascript", headers=headers)
    want = _want_sections(sections)
    only = (want - {"live"}) if (refresh and want) else None
    return _conditional(request, _slice(live_data(s, refresh, only), want), "text/javascript")


@app.get("/api/data")
def api_data(request: Request, refresh: bool = False, sections: str | None = None, wait: bool = False):
    """JSON sibling of /data.js for in-place refreshes and background
    revalidation. `?sections=resources,resourcesStale,resourcesPending&wait=1`
    waits for the background crawl; with `refresh=1` it forces a new one.
    Neither rebuilds the rest of the payload."""
    s = require(request)
    want = _want_sections(sections)
    only = (want - {"live"}) if ((refresh or wait) and want) else None
    return _conditional(request, _slice(live_data(s, refresh, only, wait_files=wait), want), "application/json")


@app.get("/api/files/{resource_id}/{file_id}")
def file_proxy(resource_id: str, file_id: str, request: Request):
    s = require(request)
    if not (UUIDISH.match(resource_id) and UUIDISH.match(file_id)):
        raise HTTPException(404)
    url = (f"{lms.API_BASE}/api/v1/tenants/{s.tenant}/resources/{resource_id}"
           f"/files/{file_id}/content/?disposition=inline")
    r = http.get(url, headers=lms.get_auth_headers(fresh(s)), stream=True, timeout=60)
    if not r.ok:
        message = ("Your teacher has restricted this file, so it can only be opened on Indus LMS."
                   if r.status_code == 403 else "Indus LMS couldn't send this file right now.")
        return unavailable(message, r.status_code)
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "content-length", "content-disposition")}
    return StreamingResponse(r.iter_content(65536), headers={**keep, "Cache-Control": "private, max-age=600"})


def unavailable(message: str, status: int) -> HTMLResponse:
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>File unavailable · openLMS</title><link rel="stylesheet" href="/assets/app.css">
<body style="display:grid;place-items:center;min-height:100vh;padding:20px">
<div class="card" style="max-width:420px;padding:28px;text-align:center">
<h1 style="font-size:20px;margin-bottom:8px">This file isn't available here</h1>
<p class="muted" style="font-weight:600">{message}</p>
<a class="btn" href="{LMS_WEB}/resources" target="_blank" rel="noopener" style="display:inline-block;margin-top:12px">Open Indus LMS</a>
</div></body>"""
    return HTMLResponse(page, status_code=status)


from openlms.routes import router  # noqa: E402  (routes import this module)

app.include_router(router)
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
