# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Persistent server-side sessions (`openlms/sessions.py`): opaque HttpOnly session cookie + SQLite store (0600, `OPENLMS_SESSION_FILE`, `:memory:` for ephemeral). Restarts no longer sign everyone out. Optional `OPENLMS_SECRET_KEY` Fernet-encrypts tokens at rest; rotated secrets force re-login. Refreshed tokens are saved back to disk.
- Persistent data cache (`openlms/cache.py` + `web/assets/cache.js`): per-student in-process payload cache with singleflight (navigation no longer rebuilds on every click), mixed TTLs (`OPENLMS_DATA_TTL` + `OPENLMS_FILES_TTL` for the slow resource crawl), shared fetch pool, `ETag`/`304` with `private` HTTP caching, `?sections=` slices and `?refresh=` escape hatch, browser `localStorage` stale fallback cleared on logout, livelier login progress messages.

### Fixed

- CSRF guard now honours `OPENLMS_PUBLIC_HOST` (comma-separated): POSTs whose Origin matches a configured public hostname are allowed even when the Host header seen by the app differs (Cloudflare/ngrok Host rewrite). Evil origins are still blocked.
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

