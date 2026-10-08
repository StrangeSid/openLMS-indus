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

from openlms.data import build
from openlms.sessions import Session, Store

WEB = Path(__file__).resolve().parent.parent / "web"
COOKIE = "openlms_sid"
DEMO_COOKIE = "openlms_demo"
LMS_WEB = "https://induslms.com"
SESSION_IDLE = 12 * 3600
DATA_TTL = int(os.environ.get("OPENLMS_DATA_TTL", "300"))
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


sessions = Store(idle=SESSION_IDLE)
attempts: dict[str, list[float]] = {}
app = FastAPI(title="openLMS", docs_url=None, redoc_url=None, openapi_url=None)


def jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        return float(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["exp"])
    except Exception:
        return 0.0


def fresh(s: Session) -> str:
    """Return a valid access token, refreshing it shortly before expiry."""
    with s.lock:
        if jwt_exp(s.access) - time.time() > 60:
            return s.access
        r = requests.post(f"{lms.API_BASE}/api/token/refresh/", json={"refresh": s.refresh},
                          headers=lms.HEADERS_BASE, timeout=15)
        if not r.ok or "access" not in r.json():
            raise HTTPException(401, "Session expired. Sign in again.")
        body = r.json()
        s.access, s.refresh = body["access"], body.get("refresh", s.refresh)
        try:
            sessions.save(s)
        except Exception:
            pass
        return s.access


def live_data(s: Session, refresh: bool = False) -> dict:
    """Build (or reuse) the student's data; concurrent requests wait for one build."""
    with s.build_lock:
        if refresh or not s.data or time.time() - s.data[0] > DATA_TTL:
            s.data = (time.time(), build(fresh(s), s.tenant, live=True))
        return s.data[1]


def warm(s: Session) -> None:
    if WARM_ON_LOGIN:
        threading.Thread(target=lambda: _quiet(live_data, s), daemon=True).start()


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
        r = requests.post(f"{lms.API_BASE}/api/v1/auth/login/", headers=lms.HEADERS_BASE, timeout=15,
                          json={"email": creds.email.strip(), "password": creds.password})
    except requests.RequestException:
        raise HTTPException(502, "Couldn't reach Indus LMS. Try again shortly.")
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
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
    response.delete_cookie(COOKIE)
    response.delete_cookie(DEMO_COOKIE)
    return {"ok": True}


@app.get("/api/demo")
def demo():
    response = RedirectResponse("../index.html", 303)
    response.set_cookie(DEMO_COOKIE, "1", samesite="lax", max_age=3600)
    return response


@app.get("/api/session")
def session_info(request: Request):
    s = require(request)
    return {"name": s.name, "email": s.email}


@app.get("/data.js")
def data_js(request: Request, refresh: bool = False):
    headers = {"Cache-Control": "no-store"}
    _, s = current(request)
    if not s:
        script = ("window.OPENLMS_DEMO = true;" if request.cookies.get(DEMO_COOKIE)
                  else "location.replace('login.html');")
        return Response(script, media_type="text/javascript", headers=headers)
    return Response("window.LMS = " + json.dumps(live_data(s, refresh), default=str) + ";",
                    media_type="text/javascript", headers=headers)


@app.get("/api/files/{resource_id}/{file_id}")
def file_proxy(resource_id: str, file_id: str, request: Request):
    s = require(request)
    if not (UUIDISH.match(resource_id) and UUIDISH.match(file_id)):
        raise HTTPException(404)
    url = (f"{lms.API_BASE}/api/v1/tenants/{s.tenant}/resources/{resource_id}"
           f"/files/{file_id}/content/?disposition=inline")
    r = requests.get(url, headers=lms.get_auth_headers(fresh(s)), stream=True, timeout=60)
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


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
