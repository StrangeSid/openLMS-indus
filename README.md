<div align="center">

<img src="web/assets/favicon.svg" alt="openLMS logo" width="72" height="72">

# openLMS-indus

**A student wrapper for Indus LMS.** Sign in with your school account and see everything that's due in one click.

[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](COPYING)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org)
[![No build step](https://img.shields.io/badge/build-none-0F766E)](#getting-started)

[Overview](#overview) • [Features](#features) • [Getting started](#getting-started) • [How it works](#how-it-works) • [Roadmap](#roadmap)

<img src="docs/index.png" alt="openLMS home screen with upcoming, done and late assignments" width="860">

</div>

## Overview

Indus LMS spreads a student's work across 10 dashboard cards. A single subject keeps assignments in four separate places (EOL tests, FA, SA and learning tasks), with resources somewhere else. Finding everything that's due can take dozens of page loads. [`FINDINGS.md`](FINDINGS.md) documents the full audit.

openLMS puts all of it on one screen. Every assignment from every class is sorted into **Upcoming**, **Done** and **Late**, and each class gets one page with its posts, work and files.

openLMS signs in to Indus LMS as you and works with your data live: you can take lesson-check tests, hand in work, ask for extensions, message teachers, read full announcements and clear notifications without opening Indus LMS.

> [!NOTE]
> openLMS is an unofficial client. Your password is passed to Indus LMS once to sign you in and is never stored.

## Features

- **One assignments list.** Lesson checks, FA and SA tests, and learning tasks are merged into Upcoming, Done and Late, with class filtering, sorting and search.
- **Tests and hand-ins in the app.** Every assignment opens its own page (`test.html`): lesson checks (EOL) with passcode entry, a one-question-at-a-time attempt, the same proctoring rules as Indus LMS and a results view with your answer vs the correct one and AI learning notes; FA/SA tests with instructions, answers or file hand-in, resubmission, teacher feedback and rubric scores, and extension/resubmission requests; learning tasks with attachments and file hand-in. Every write asks first and is sent once.
- **Messages.** Conversations with teachers, a contact picker and a composer. It checks for replies only while a conversation is open and visible.
- **Updates.** A notification centre with All/Unread/Read, search, paging, *Dismiss* and *Mark all read*. Each notification opens the test or the subject's work list. Announcements show in full with attachments and are marked read when opened.
- **School.** Policies (PDFs), progress reports and help in one page; attendance day by day on the Planner; a learning-pathway roadmap on Progress.
- **A page for each class.** Each class has a stream of announcements, its assignments split by status, and shared resources grouped by folder.
- **Planner.** A month calendar shows school events and deadlines, coloured by status, plus your attendance.
- **Library.** Every shared file in one place, filterable by subject and type. You can optionally download them so they open offline.
- **Progress.** Graded results, completion per subject, and one feed of notifications and announcements.
- **Live, per-student sessions.** Each student signs in with their own account. Tokens refresh automatically, sessions survive server restarts, and files stream straight from the LMS.
- **Fast first load, instant reopen.** Pages render from the last copy saved in the browser and refresh it in the background (`If-None-Match` → usually `304`), so reopening openLMS paints in tens of milliseconds. A cold load waits only for one parallel fan-out over pooled connections; the slow resource crawl runs in the background and the Library swaps files in when it finishes. See [Performance](#performance).
- **Demo mode.** *Explore with demo data* on the sign-in page shows the full app with made-up data, which is handy for presentations.
- **No build step.** The front end is plain HTML, CSS and JavaScript, and works on desktop and phones.

## Getting started

### Try the demo

You only need Python 3. With no data exported, the app loads the synthetic demo data in [`web/assets/data.example.js`](web/assets/data.example.js):

```bash
git clone https://github.com/StrangeSid/openLMS-indus.git
cd openLMS-indus
python3 -m http.server 8000 --directory web
```

Open <http://localhost:8000>.

### Run the server

The server signs students in and serves live data. You need Python 3.10+:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn openlms.app:app --port 8000
```

Open <http://localhost:8000> and sign in with your Indus LMS account, or choose **Explore with demo data**.

| Environment variable | Purpose |
|---|---|
| `OPENLMS_DATA_TTL` | Seconds to cache each student's data (default `300`) |
| `OPENLMS_FILES_TTL` | Seconds to reuse the slow resource crawl (default `3600`) |
| `OPENLMS_DETAIL_TTL` | Seconds to cache detail views such as results, feedback and policies (default `300`) |
| `OPENLMS_ACADEMIC_YEAR` | Override the academic year used for announcements (default: derived from today, e.g. `2026-27`) |
| `OPENLMS_CACHE_SIZE` | Max students held in the in-process data cache (default `200`) |
| `OPENLMS_POOL_WORKERS` | Shared upstream fetch threads (default `16`) |
| `OPENLMS_SECURE_COOKIES=1` | Force `Secure` cookies when TLS ends at a proxy |
| `OPENLMS_SESSION_FILE` | SQLite session store path (default `.openlms-sessions.db`). Sessions survive restarts; `:memory:` disables persistence |
| `OPENLMS_SECRET_KEY` | Optional passphrase/Fernet key to encrypt tokens at rest. Without it they rest as plaintext in a `0600` file |
| `OPENLMS_PUBLIC_HOST` | Comma-separated public hostname(s) allowed past the CSRF Origin check behind a proxy (e.g. Cloudflare/ngrok) |
| `INDUSLMS_TENANT` | Fallback tenant ID if an account has none |

### Offline snapshot (no server)

1. Install the dependencies (they include [induslms-agent](https://github.com/StrangeSid/induslms-agent) 0.4.0 or later, which does the LMS API access; until 0.4.0 is on PyPI, install it from a checkout with `pip install -e ../induslms-agent`) and log in once:

   ```bash
   pip install -r requirements.txt
   induslms login you@school.example
   ```

2. Export your data to `web/data.js` (every assignment type including learning tasks, full announcements and notifications; an expired token is refreshed automatically). Add `--files` to also download shared files into `web/files/`:

   ```bash
   python3 tools/export.py
   python3 tools/export.py --files
   ```

3. Serve `web/` with `python3 -m http.server 8000 --directory web` and reload. Run the export again whenever you want fresh data.

> [!IMPORTANT]
> `web/data.js` and `web/files/` contain your personal school data. Both are in `.gitignore`. Never commit them or publish the `web/` folder with them inside.

> [!TIP]
> Some files return `403 Forbidden`. These belong to classes you're not in, or teachers have restricted them. openLMS links those to Indus LMS instead.

## How it works

```
Browser ──► openlms/app.py + routes.py ──────────► Indus LMS API
web/*.html   sign-in, sessions, data.js/api/data     api.induslms.com
   │         (ETag/304), file proxy, every write      (pooled keep-alive
   │               │                                  connections via
   │               ├─ openlms/cache.py: payload (DATA_TTL), files     induslms-agent)
   │               │  (FILES_TTL, crawled in the background),
   │               │  detail views (DETAIL_TTL), singleflight
   │               └─ openlms/data.py: parallel fan-out + shaping,
   │                  HTML sanitizer for teacher-written content
   └── assets/cache.js: last copy in localStorage, rendered first
```

The browser can't call Indus LMS directly: the API only allows CORS from `induslms.com` and the tokens are tied to that origin. So every call goes through the openLMS server on the same origin, which holds each student's tokens server-side and refreshes them five minutes before they expire.

Every page renders from `window.LMS`. On a repeat visit, `cache.js` puts the last saved copy there and the page paints immediately; `app.js` then asks `GET /api/data` with `If-None-Match` and re-renders only if something changed (detail pages just update their counts). With no saved copy, the page loads `data.js`, which the server answers from the per-student cache or one parallel fan-out. The resource crawl never blocks it: the payload says `resourcesPending`, and the Library and class pages fetch `?sections=resources,resourcesStale,resourcesPending&wait=1` to swap files in when the crawl finishes. `?refresh=1` forces a rebuild. Without the server (the offline snapshot or the static demo), `data.js` is a static file or the demo data; demo mode answers the detail views from `data.example.js`, and a static export links out to Indus LMS for actions.

Detail views and writes live under `/api/` (`openlms/routes.py`): `eol/{id}`, `eol/open`, `eol/{id}/submit|proctor|explain`, `fa/{id}` (+ `submit`, `resubmit`, `request`), `requests/{id}/cancel`, `tasks/{id}` (+ `submit`), `announcements` (+ `{id}/read`), `notifications` (+ `{id}/read`, `read-all`), `messages/contacts|threads|conversation/{id}`, `POST messages`, `policies`, `reports`, `help`, `attendance/day`, `today`, `assignments`, `calendar`. Reads are cached for five minutes and retried once after a token refresh on `401`; writes are sent once, never retried, and drop the caches they change. File uploads go to the LMS's S3 bucket from the server.

The app sorts each assignment into one of three states:

| State | Rule |
|---|---|
| **Upcoming** | Not submitted, and the deadline hasn't passed (or the work hasn't opened yet) |
| **Done** | Submitted or graded. Marked *Late* if it was turned in after the deadline. |
| **Late** | The deadline passed with no submission |

## Performance

Students said Indus LMS is slow, worst on the first load after closing the tab. Measured on Oct 9, 2026 from India with a student account (details in [FINDINGS.md §10](FINDINGS.md#10-performance-measured-oct-09--corrections)):

| What | Indus LMS / openLMS 0.2 | openLMS now |
|---|---|---|
| One API request | ~1,050 ms (new TLS connection every call) | ~280 ms (pooled keep-alive) |
| Reopening after the access token expired | 6 calls fail with `401`, then refresh, then retry: 5.7 s vs 1.3 s | refreshed 5 minutes ahead on the server, no `401`s |
| Cold first load of the data (openLMS) | 17.5 s median (resource crawl, then fan-out) | 3.3 s median (fan-out only; crawl in the background) |
| Repeat visit | waits for `data.js` | first paint from the saved copy at ~30 ms, then a `304` |
| Indus web app bundle | 8.9 MB JS (2.95 MB gzipped), `max-age=0` | ~48 KB shared JS + the page's own script (under 100 KB per page), no build step |

## Project structure

```
openlms/
  app.py              FastAPI server: sign-in, sessions, live data, file proxy, demo mode
  routes.py           In-app LMS routes: results, feedback, tasks, messages, notifications, policies and every write
  sessions.py         Persistent server-side sessions (SQLite, opaque HttpOnly cookie, optional Fernet)
  cache.py            In-process per-student data cache (mixed TTLs, singleflight, ETags)
  data.py             Fetch and shape LMS data (shared with the exporter), HTML sanitizer
web/
  login.html          Sign-in page (server mode)
  index.html          Home: Upcoming / Done / Late assignments
  class.html          Per-class page (?c=<subject>&tab=stream|work|files)
  planner.html        Calendar, deadlines, attendance
  library.html        All shared files
  progress.html       Results, completion, learning pathway, updates feed
  test.html           One assignment: EOL attempt + results, FA/SA hand-in + feedback + requests, learning tasks
  messages.html       Conversations with teachers
  updates.html        Notification centre and full announcements
  school.html         Policies, progress reports, help
  assets/
    app.js            Shared helpers, sidebar, assignment states, page lifecycle and revalidation, api() + demo answers
    cache.js          Saved copy of window.LMS: renders repeat visits instantly (cleared on logout)
    app.css           Design tokens and layout
    data.example.js   Synthetic demo data
tools/export.py       Offline snapshot to web/data.js
tests/                Unit tests (app, routes, sessions, cache, background crawl, sanitizer, exporter)
docs/                 README screenshot
FINDINGS.md           Audit of the current LMS: routes, API calls, click depth
```

Run the tests with:

```bash
pip install -r requirements-dev.txt
python3 -m unittest discover -s tests
```

## Roadmap

- [x] Assignments (lesson checks, FA and SA tests, learning tasks), classes, resources, announcements, calendar, attendance, notifications
- [x] Live sign-in with per-student sessions and a file proxy
- [x] Per-student data cache (mixed TTLs, ETag/304) and browser stale fallback for fast navigation
- [x] Tests, hand-ins, extension requests, messaging, mark-read, policies, reports and help inside openLMS
- [x] Instant reopen (saved copy + background revalidation), background resource crawl, pooled connections
- [ ] Live-capture the FA question hand-in and task upload against a real unsubmitted item (paths and payloads come from the Indus bundle)
- [ ] Learning pathway from `/learning-pathway/subject-plan/`; LMS Support tickets

## Credits

Frontend Developer: Arnav V. Reddy  
Backend Developer: Siddhant Harsoda

Built on **[StrangeSid/induslms-agent](https://github.com/StrangeSid/induslms-agent)**, which provides the reverse-engineered API client and endpoint reference.

An unofficial student project. Not affiliated with or endorsed by the Indus Trust or Indus International School.
