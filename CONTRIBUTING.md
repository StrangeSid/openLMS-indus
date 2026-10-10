# Contributing to openLMS-indus

Thanks for helping make the LMS easier for students. Bug reports, fixes and UI improvements are all welcome.

## Ground rules

- **Writes are explicit.** openLMS submits work, runs EOL tests, sends messages and marks things read through `openlms/routes.py`. Every write needs a confirm step in the UI (`confirmDialog`), is sent exactly once (never retried), and drops the caches it affects. Keep EOL proctoring parity (tab-hide reports, exit counting). Never store passwords or passcodes, and never let a token reach the browser.
- **Teacher HTML is untrusted.** Render announcement bodies, instructions and questions only from `sanitize_html()` output (`openlms/data.py`); everything else goes through `esc()`.
- **No personal data in git.** Never commit `web/data.js`, `web/files/`, tokens, `.env` files, or screenshots and logs showing real names, emails or IDs. Use the demo data (`web/assets/data.example.js`) for screenshots, examples and tests. Both data paths are already in `.gitignore`; leave them there.
- **API changes belong upstream.** Endpoints and auth live in [induslms-agent](https://github.com/StrangeSid/induslms-agent). If you need a new endpoint, add it there first, then use it from `tools/export.py`.
- **Keep it build-free.** The web app is plain HTML, CSS and JavaScript with no bundler or framework. Talk about it in an issue before adding dependencies.

## Development setup

```bash
git clone https://github.com/StrangeSid/openLMS-indus.git
cd openLMS-indus
python3 -m http.server 8000 --directory web   # demo data at http://localhost:8000

# or the full server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn openlms.app:app --reload --port 8000
```

To work with your own data, see [Use your own data](README.md#use-your-own-data) in the README.

## Making changes

1. Fork the repo and create a branch from `main`, for example `feat/attendance-filters` or `fix/planner-overflow`.
2. Keep changes focused. One feature or fix per pull request.
3. Follow the existing style:
   - Shared helpers and assignment logic go in `web/assets/app.js` (the saved copy and `__lmsBoot()` live in `web/assets/cache.js`, which loads first). Page-specific code stays in its page's `<script>`, wrapped in `page(() => { ... })` so it can re-render when fresh data arrives; register document/window listeners with `{ signal: pageSignal() }`. Detail pages pass `{ detail: true }`.
   - Server calls from pages use `api()`, which also answers from the demo data, so new views work in demo mode.
   - Colours and spacing come from the CSS variables in `web/assets/app.css`.
   - Escape any LMS text with `esc()` before inserting it into HTML.
   - Python targets 3.10+. Server code lives in `openlms/` and uses FastAPI, induslms-agent, stdlib SQLite for sessions, and optional `cryptography` for token encryption.
4. Check your change on desktop and at phone width (about 375px), in demo mode.
5. Run the tests:

   ```bash
   python3 -m unittest discover -s tests
   ```

6. Add an entry under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md).

## Commit messages

Use short, imperative subjects with a [Conventional Commits](https://www.conventionalcommits.org/) prefix:

```
feat(planner): show attendance per week
fix(home): keep late tab selected after reload
docs: explain --files restrictions
```

## Reporting issues

Open an issue with steps to reproduce, what you expected, and your browser. Redact names, emails and IDs from screenshots and logs.

## License

By contributing, you agree your contributions are licensed under [GPL-3.0-or-later](COPYING), the same as the rest of the project. New source files should start with an SPDX header:

```
SPDX-License-Identifier: GPL-3.0-or-later
```
