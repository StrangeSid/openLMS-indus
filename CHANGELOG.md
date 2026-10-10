# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Everything in-app, nothing read-only.** New `openlms/routes.py` (the route table in FINDINGS §9B) and pages:
  - `test.html?kind=eol|fa|sa|task&id=`: EOL passcode → one-question-at-a-time attempt → submit → results with your answer vs the correct one, AI learning notes on tap and teacher feedback; proctoring parity with Indus LMS (tab-hide reports to `/proctoring/`, warnings, termination at the threshold, 3 mid-test exits counted locally and from the server row, copy/paste blocked). FA/SA instructions, attachments, MCQ/written answers or file hand-in, resubmission (keep/add files), feedback with rubric scores, extension/resubmission requests and withdrawal. Learning tasks with attachments and file hand-in (server-side S3 upload).
  - `messages.html`: conversations, contact picker, composer; polls only while a conversation is open and visible.
  - `updates.html`: notification centre (All/Unread/Read, search, paging, Dismiss, Mark all read, deep links to the item or the subject's work list) and full announcements (sanitized HTML, attachments, search, read recorded on open).
  - `school.html`: policies, progress reports (empty state), help. Planner: attendance day by day. Progress: learning-pathway roadmap.
  - Every write asks for confirmation, is sent once and is never retried; affected caches are dropped and the bell/sidebar counts update in place.
- Demo mode answers every new view from `data.example.js` (try EOL passcode `1234`).
- `sanitize_html()` allowlist for teacher-written HTML; previews are derived from the sanitized text.
- Payload: ids and attempt flags on EOL rows, assessment ids, task ids/attachments, full announcements (`html`, `files`), notification ids/`refId`/subject, thread user ids.
- Exporter: learning tasks, full announcements from `/announcements/visible/`, all assessment pages, auto-refreshing CLI token.
- Tests: `tests/test_routes.py` (reads, writes, no-retry, 401 refresh, validation, uploads, cache effects, background crawl, refresh-ahead) and `tests/test_sanitize.py`.
- Persistent server-side sessions (`openlms/sessions.py`): opaque HttpOnly session cookie + SQLite store (0600, `OPENLMS_SESSION_FILE`, `:memory:` for ephemeral). Restarts no longer sign everyone out. Optional `OPENLMS_SECRET_KEY` Fernet-encrypts tokens at rest; rotated secrets force re-login. Refreshed tokens are saved back to disk.
- Persistent data cache (`openlms/cache.py` + `web/assets/cache.js`): per-student in-process payload cache with singleflight (navigation no longer rebuilds on every click), mixed TTLs (`OPENLMS_DATA_TTL` + `OPENLMS_FILES_TTL` for the slow resource crawl), shared fetch pool, `ETag`/`304` with `private` HTTP caching, `?sections=` slices and `?refresh=` escape hatch, browser `localStorage` stale fallback cleared on logout, livelier login progress messages.
- JSON `GET /api/data` mirroring `/data.js` (same `sections`/`refresh`/`ETag` semantics) plus files-only partial refresh: `?refresh=1&sections=resources,resourcesStale` recrawls just the files and patches the cached payload, so the Library and class file lists hot-swap in place with an "Updating resources…" banner instead of reloading.

### Changed

- **Performance** (measured, FINDINGS §10): cold `data.js` 17.5 s → 3.3 s median. The resource crawl runs in the background (`resourcesPending` + `?wait=1` hot-swap), every upstream call uses pooled keep-alive connections (induslms-agent 0.4.0 `lms.HTTP`, ~1 s → ~0.28 s per request), tokens refresh 5 minutes ahead, the payload carries 30 notifications instead of 100, and Google Fonts no longer block first paint.
- **Instant reopen**: pages render from the saved copy and revalidate with `If-None-Match` (usually `304`); detail pages keep their state and only refresh counts. A tab left open revalidates when looked at after 5 minutes; nothing polls.
- Sidebar: Messages, Updates (unread count) and School replace the "On Indus LMS" links; inbox rows open in-app. Static exports (no server) still link out.
- Requires induslms-agent ≥ 0.4.0 and `python-multipart`. Sessions store the LMS user id (migrated in place).

### Fixed

- CSRF guard now honours `OPENLMS_PUBLIC_HOST` (comma-separated): POSTs whose Origin matches a configured public hostname are allowed even when the Host header seen by the app differs (Cloudflare/ngrok Host rewrite). Evil origins are still blocked.
- Resource crawl no longer 500s `/data.js` when the LMS answers a folder listing (or token refresh / login) with an empty/non-JSON body: bad pages degrade to partial/empty resources with stale fallback instead of crashing the page. `/data.js` now carries `resourcesStale`, and pages show an "Updating resources…" banner with a one-shot background retry instead of silently rendering old files.
- Page-switch flicker removed: a boot skeleton matching the sidebar/topbar geometry paints synchronously before `data.js` (swapped out with no layout shift), and the Manrope font loads via head `<link>`s instead of a render-blocking CSS `@import`.
- Indus LMS deep links: EOL/FA/SA buttons now open the subject hub (`/assignments?courseId=&classId=`) instead of `/assignments/test/<kind>?subject=&course_id=`. The test pages ignore course params in the URL and filter by the localStorage-selected course, so the old links showed 0 tests whenever storage held another subject. The hub reads the course from the URL and is one click from the test lists.
- Learning-task links use `?courseId=` (camelCase), which `/studentassignment` actually reads.
- Notification links resolve to the subject hub when the course is known (by id or link slug) instead of opening raw `/assignments/test/<slug>/<kind>` links.
- Resource links include the required subject slug (`/courses/:id/resources/:slug`); slug-less URLs render a Network Error on Indus.
- Notifications payload now carries `courseId` for link resolution.

## [0.2.0] - 2026-10-07

### Added

- FastAPI server (`openlms/app.py`): sign in with an Indus LMS account, per-student in-memory sessions, automatic token refresh, live `data.js`, and a file proxy so Library files open without downloading first.
- Sign-in page (`web/login.html`) and a Sign out button in live mode.
- SA tests and learning tasks in the assignments lists.
- Submit / Take test / View buttons that open the matching Indus LMS page, with EOL test IDs shown; an "On Indus LMS" sidebar section for messaging, policies, learning pathway, progress report and help.
- Demo mode on the sign-in page, a loading screen after sign-in, and a friendly page for files a teacher has restricted.
- Server tests with a stubbed LMS, covering sign-in, refresh, logout, rate limiting, cross-site blocking, the file proxy and demo mode.

### Changed

- Actions that change school data (submitting, uploading, tests, messaging) stay on Indus LMS. openLMS links to the exact page instead of performing them.
- A failing LMS section no longer breaks the whole page.
- Data shaping moved to `openlms/data.py`, shared by the server and `tools/export.py`, with LMS requests now made in parallel.
- README, CONTRIBUTING and FINDINGS updated for the server and the link-out approach.

## [0.1.0] - 2026-10-07

### Added

- Static student web app in `web/`:
  - **Home**: every assignment sorted into Upcoming, Done and Late, with class filter, sorting and search.
  - **Class pages**: stream, assignments by status and resources grouped by folder, opened from the sidebar class list.
  - **Planner**: month calendar of school events and status-coloured deadlines, plus attendance.
  - **Library**: all shared files with subject and type filters, grid and list views.
  - **Progress**: graded results, completion per subject, and a notifications and announcements feed.
- `tools/export.py` exports LMS data to `web/data.js` through induslms-agent, and with `--files` downloads shared files.
- Synthetic demo data (`web/assets/data.example.js`), so the app runs without an account.
- Unit tests for the exporter.
- `.gitignore` entries that keep exported personal data out of git.
- `CONTRIBUTING.md` and this changelog.

### Changed

- README rewritten with setup, architecture and project structure.

## [0.0.1] - 2026-10-07

### Added

- `FINDINGS.md`: audit of the current Indus LMS (API endpoints, auth, UI structure, click depth).
- README with the overhaul plan and credit to induslms-agent.
- GPL-3.0-or-later license.

