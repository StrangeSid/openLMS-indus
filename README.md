<div align="center">

<img src="web/assets/favicon.svg" alt="openLMS logo" width="72" height="72">

# openLMS-indus

**A simpler, read-only student view of Indus LMS. Answers "what's due?" in one click.**

[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](COPYING)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab)](https://www.python.org)
[![No build step](https://img.shields.io/badge/build-none-0F766E)](#getting-started)

[Overview](#overview) • [Features](#features) • [Getting started](#getting-started) • [How it works](#how-it-works) • [Project structure](#project-structure)

<img src="docs/index.png" alt="openLMS home screen with upcoming, done and late assignments" width="860">

</div>

## Overview

Indus LMS spreads a student's work across 10 dashboard cards. A single subject keeps assignments in four separate places (EOL tests, FA, SA and learning tasks), with resources somewhere else. Finding everything that's due can take dozens of page loads. [`FINDINGS.md`](FINDINGS.md) documents the full audit.

openLMS puts all of it on one screen. Every assignment from every class is sorted into **Upcoming**, **Done** and **Late**, and each class gets one page with its posts, work and files.

> [!NOTE]
> openLMS is **read-only by design**. It never submits work, marks notifications as read, or changes school data. It shows what the LMS already exposes to you.

## Features

- **One assignments list.** Lesson checks, FA and SDL tasks are merged into Upcoming, Done and Late, with class filtering, sorting and search.
- **A page for each class.** Each class has a stream of announcements, its assignments split by status, and shared resources grouped by folder.
- **Planner.** A month calendar shows school events and deadlines, coloured by status, plus your attendance.
- **Library.** Every shared file in one place, filterable by subject and type. You can optionally download them so they open offline.
- **Progress.** Graded results, completion per subject, and one feed of notifications and announcements.
- **No build step.** The app is plain HTML, CSS and JavaScript, and works on desktop and phones.

## Getting started

### Try the demo

You only need Python 3. With no data exported, the app loads the synthetic demo data in [`web/assets/data.example.js`](web/assets/data.example.js):

```bash
git clone https://github.com/StrangeSid/openLMS-indus.git
cd openLMS-indus
python3 -m http.server 8000 --directory web
```

Open <http://localhost:8000>.

### Use your own data

1. Install [induslms-agent](https://github.com/StrangeSid/induslms-agent), which does the LMS API access, and log in once:

   ```bash
   pip install induslms-agent
   induslms login you@school.example
   ```

2. Export your data to `web/data.js`. Add `--files` to also download shared files into `web/files/`:

   ```bash
   python3 tools/export.py
   python3 tools/export.py --files
   ```

3. Serve `web/` as above and reload. Run the export again whenever you want fresh data.

> [!IMPORTANT]
> `web/data.js` and `web/files/` contain your personal school data. Both are in `.gitignore`. Never commit them or publish the `web/` folder with them inside.

> [!TIP]
> Some files return `403 Forbidden` during `--files`. These belong to classes you're not in, or teachers have restricted them. The Library marks them "View on LMS only".

## How it works

```
Indus LMS API ──► induslms-agent (lms.py) ──► tools/export.py ──► web/data.js ──► static pages
                  auth + read-only calls      normalise + files    window.LMS      web/*.html
```

`tools/export.py` calls induslms-agent, reduces the responses to the fields the UI needs, and writes them to `web/data.js`. Every page loads that file, falls back to the demo data if it's missing, and renders in the browser. There is no server-side code and nothing is sent anywhere.

The app sorts each assignment into one of three states:

| State | Rule |
|---|---|
| **Upcoming** | Not submitted, and the deadline hasn't passed (or the work hasn't opened yet) |
| **Done** | Submitted or graded. Marked *Late* if it was turned in after the deadline. |
| **Late** | The deadline passed with no submission |

## Project structure

```
web/
  index.html          Home: Upcoming / Done / Late assignments
  class.html          Per-class page (?c=<subject>&tab=stream|work|files)
  planner.html        Calendar, deadlines, attendance
  library.html        All shared files
  progress.html       Results, completion, updates feed
  assets/
    app.js            Shared helpers, sidebar, assignment states
    app.css           Design tokens and layout
    data.example.js   Synthetic demo data
tools/export.py       Export your LMS data to web/data.js
tests/                Unit tests (python3 -m unittest discover -s tests)
FINDINGS.md           Audit of the current LMS: routes, API calls, click depth
```

## Credits

Built on **[StrangeSid/induslms-agent](https://github.com/StrangeSid/induslms-agent)**, which provides the reverse-engineered API client, the endpoint reference and the read-only access patterns. That repo stays the source of truth for the API; this one is the UI layer.

An unofficial student project. Not affiliated with or endorsed by the school or the Indus LMS vendor.
