# openLMS-indus

A simpler, more pleasant wrapper around the current Indus LMS.
Preserves 100% of functionality — fixes the UX students complain about
(bloated, hard to explain, too many clicks to answer "what's due?").

Status: **findings only, no code yet.** See [`FINDINGS.md`](FINDINGS.md)
for the live audit (routes, API calls, click-depth).

## Credit

Built on top of **[StrangeSid/induslms-agent](https://github.com/StrangeSid/induslms-agent)**
— API reverse-engineering (`lms.py`), endpoint reference, and read-only
access patterns. This repo is the UI/UX layer; the agent repo remains the
API source of truth. Upstream is tracked as `upstream` in git.

## The student problem

- 10 dashboard cards, each a separate page.
- One subject hides work in **4 places**: EOL Test / FA / SA / Learning Task
  (+ Resources separate) — up to 28 page loads across 7 subjects.
- Same concept, 4 names, 4 table layouts, no global due-date view.
- Redundant hierarchy: programme → 1-subject grade groups → subject → type chooser.

## The plan (simple)

4 tabs instead of 10 cards:

1. **Today** — global TODO list. Every pending/upcoming item sorted by due
   date (`Overdue / Due this week / Later`). One row → deep-link to the
   original detail page (nothing re-implemented).
2. **Assignments** — one header merging EOL + FA + SA + Learning Tasks.
   Filters (`All | EOL | FA | SA | Tasks`), subject filter, search.
3. **Subjects & Files** — flat subject list, resources inline with search.
4. **Me** — attendance %, calendar, announcements, reports.

v1 is **read-only**: aggregate + link, never re-implement test-taking,
submission, or mark-read. Stack when approved: Next.js + FastAPI BFF
reusing `induslms-agent` logic.

## License

**GPL-3.0-or-later** — see [COPYING](COPYING).
