# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

