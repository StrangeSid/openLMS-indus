# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

