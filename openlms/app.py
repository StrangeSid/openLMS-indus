# SPDX-License-Identifier: GPL-3.0-or-later
"""openLMS server: per-student login to Indus LMS, live data and a file proxy.

    uvicorn openlms.app:app --port 8000

Passwords are forwarded to Indus LMS once and never stored. Each student's
tokens live only in this process's memory, keyed by a random session cookie.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

import lms
import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from openlms.data import build

WEB = Path(__file__).resolve().parent.parent / "web"
COOKIE = "openlms_sid"
SESSION_IDLE = 12 * 3600
DATA_TTL = int(os.environ.get("OPENLMS_DATA_TTL", "300"))
LOGIN_LIMIT = (10, 600)  # attempts per window (seconds), per client IP
UUIDISH = re.compile(r"^[0-9a-fA-F-]{8,64}$")


class Session:
    def __init__(self, access: str, refresh: str, tenant: str, user: dict):
        self.access, self.refresh, self.tenant = access, refresh, tenant
        self.name = user.get("full_name") or user.get("email")
        self.email = user.get("email")
        self.seen = time.time()
        self.data: tuple[float, dict] | None = None
        self.lock = threading.Lock()


class Store:
    def __init__(self):
        self._s: dict[str, Session] = {}
        self._lock = threading.Lock()

    def add(self, s: Session) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._s[sid] = s
        return sid

    def get(self, sid: str | None) -> Session | None:
        with self._lock:
            now = time.time()
            for k in [k for k, v in self._s.items() if now - v.seen > SESSION_IDLE]:
                del self._s[k]
            s = self._s.get(sid or "")
            if s:
                s.seen = now
            return s

    def drop(self, sid: str | None) -> None:
        with self._lock:
            self._s.pop(sid or "", None)


sessions = Store()
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
        return s.access


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
        if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
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
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=SESSION_IDLE,
                        secure=request.url.scheme == "https" or os.environ.get("OPENLMS_SECURE_COOKIES") == "1")
    attempts.pop(ip, None)
    return {"name": user.get("full_name")}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    sid, _ = current(request)
    sessions.drop(sid)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/session")
def session_info(request: Request):
    s = require(request)
    return {"name": s.name, "email": s.email}


@app.get("/data.js")
def data_js(request: Request, refresh: bool = False):
    headers = {"Cache-Control": "no-store"}
    _, s = current(request)
    if not s:
        return Response("location.replace('login.html');", media_type="text/javascript", headers=headers)
    if refresh or not s.data or time.time() - s.data[0] > DATA_TTL:
        s.data = (time.time(), build(fresh(s), s.tenant, live=True))
    return Response("window.LMS = " + json.dumps(s.data[1], default=str) + ";",
                    media_type="text/javascript", headers=headers)


@app.get("/api/files/{resource_id}/{file_id}")
def file_proxy(resource_id: str, file_id: str, request: Request):
    s = require(request)
    if not (UUIDISH.match(resource_id) and UUIDISH.match(file_id)):
        raise HTTPException(404)
    url = (f"{lms.API_BASE}/api/v1/tenants/{s.tenant}/resources/{resource_id}"
           f"/files/{file_id}/content/?disposition=inline")
    r = requests.get(url, headers=lms.get_auth_headers(fresh(s)), stream=True, timeout=60)
    if r.status_code == 403:
        raise HTTPException(403, "Your teacher hasn't made this file downloadable.")
    if not r.ok:
        raise HTTPException(r.status_code, "Couldn't fetch this file from Indus LMS.")
    keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type", "content-length", "content-disposition")}
    return StreamingResponse(r.iter_content(65536), headers={**keep, "Cache-Control": "private, max-age=600"})


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
