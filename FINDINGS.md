# openLMS-indus — Findings from live Indus LMS audit

Date: 2026-10-07
Method: Chrome DevTools on logged-in session (`https://induslms.com/studentdashboard`)
  + bundle analysis (`assets/index-CusXpBbJ.js` ~8.2MB)
  + prior reverse-engineering in `~/induslms-agent` (`lms.py`, `server.py`, `references/endpoints.md`)
Student: Siddhant Rajesh Harsoda, DP 2026-27, 7 subjects, 38 unread notifications.

Goal: wrapper that preserves 100% of current LMS functionality with a
simpler, more pleasant UI/UX. Single **Assignments** header + global **TODO list**.

---

## 1. Auth & storage (verified live)

- API base: `https://api.induslms.com`, headers `Authorization: Bearer <access>`.
- Login: `POST /api/v1/auth/login/ {email,password}` → `{access, refresh, user}`.
- Frontend keys in `localStorage`: `accessToken`, `refreshToken`, `tenantid`
  (`a118fede-...`), `loginrole=STUDENT`, `loginname`, `user`, `programAcademicYear=2026-27`.
- Tenant fallback: `user.roles[0].tenant_id` or `INDUSLMS_TENANT`.
- Note: CLI token at `~/.induslms_token.json` was expired during audit;
  browser had auto-refreshed — wrapper needs silent refresh on 401.

## 2. Dashboard (`/studentdashboard`)

10 tool cards (each a separate page today):
Learning Pathway, Assignments and resources, Progress Report, Messaging,
Announcements, School Policies, Attendance, My Calendar, Help, LMS Support.

Load calls:
- `GET /api/v1/auth/me/`
- `GET /api/v1/profile/me/`
- `GET /api/v1/programs/year-list/?tenant_id={tid}&is_active=true`
- `GET /api/v1/tenants/{tid}/me/student/courses?year=2026-27&include_teachers=true&include_classes=true`
- `GET /api/v1/tenants/{tid}/notifications/?limit=20`
- `GET /api/v1/mini-admin/status/`

Subjects (7): French B, Assembly, English A: Language And Literature,
Mathematics: Analysis And Approaches, Business Management, Computer Science, Economics.

## 3. The Assignments maze (core bloat)

Route tree observed by clicking:

```
/assignments
  → grade groups (11C, Business-G11-C6-Arvind, …) — each "1 subject", 2 clicks for 1 subject
  → /assignments?courseId={cid}&classId={clid}
      → chooser: [Resource | Assignments | Learning Task]
        Resource → /courses/:cid/resources/:slug
        Assignments → /assignments/test/:slug
          → chooser: [EOL Test | FA Test | SA Test]
            EOL → /assignments/test/:slug/eol
            FA  → /assignments/test/:slug/fa
            SA  → /assignments/test/:slug/sa
        Learning Task → /studentassignment?courseId={cid}
```

Network calls per leaf (tid = tenant):

| UI leaf | API call(s) |
|---|---|
| Resource | `GET /tenants/{tid}/resources/?course_id={cid}&page=1&page_size=100` + `GET .../resources/?course_id={cid}&parent_resource_id__isnull=true&page=1&page_size=20` |
| EOL | `GET /tenants/{tid}/eol-tests/my/?course_id={cid}` |
| FA | `GET /student/assessments/?assessment_type=FA&course_id={cid}&page=1&page_size=15` + `GET /assessments/sidebar-counts/?assessment_type=FA` + `GET /tenants/{tid}/teachers/` + `GET /api/v2/report-engine/form/?grade=11` + `GET .../objectives/?grade=11&subject=` |
| SA | same as FA with `assessment_type=SA` (+ `GET /tenants/{tid}/curricula/MYP/assessment-categories` → 403 for DP student, harmless) |
| Learning Task | `GET /tenants/{tid}/assignments/student/list/?course_id={cid}` |

Live sample — Computer Science (`cid=bdbc1c79-…`, `classId=9801d874-…`):
EOL=5 (4× 5/5 submitted, 1× pending due 11 Oct 6PM: "B2 - Searching Algorithms"),
FA=0, SA=0, Learning Tasks=0, Resources=3 folders.
English/French: assessments exist (`SDL_3`, `SDL_1`) — same split applies.

Notifications link into the split:
`{type:eol, title, link:/assignments/test/computer-science/eol, course_id}` — 38 unread, no single inbox.

Cost today: 7 subjects × 4 task-lists = up to **28 page loads** to answer "what's due?".

## 4. Why students call it bloated

1. No backend `assignments` endpoint — `/assignments?courseId=` is a client-side chooser, not data.
2. Same concept, 4 names: EOL Test / FA / SA / Learning Task, each own manager + table columns.
3. Redundant hierarchy: Programme → grade-group (1 subject) → subject → type-chooser → type.
4. Resources need N+1 folder crawl (`?parent_resource_id=` per folder).
5. Attendance = 2 calls (`/students/me/attendance/` + `.../attendance/day/`), inbox/files live outside LMS (Mail.app / Graph).

## 5. Wrapper plan: one Assignments + TODO list

### IA (4 tabs, not 10 cards)

```
Today (= TODO) | Assignments | Subjects & Files | Me
```

- **Today**: every pending/upcoming item sorted by due date, grouped `Overdue / Due this week / Later`. One checkbox-feel row → deep-link to original detail page (preserves functionality).
- **Assignments**: full filterable list `[All | EOL | FA | SA | Learning Tasks] + subject filter + search`. Same rows as Today minus date grouping.
- **Subjects & Files**: flat subject list (no 1-subject grade groups), resources inline with search across `file_urls[].name`.
- **Me**: attendance % (merged sessions+days), progress reports, calendar, announcements.

### TODO list spec

Sources merged client-side (later FastAPI BFF):
- EOL: `eol-tests/my/` → due=`available_until`, state=`Pending|Submitted|Expired|Terminated`, score=`score/total_marks`.
- FA/SA: `student/assessments/?assessment_type={FA,SA}` → due=`assessment.due_date`, state=`status`, teacher=`assessment.teacher_name`.
- Learning Tasks: `assignments/student/list/?course_id=` → due=`due_date`, state=`status`, files=`assignment_files`, feedback.

Sort: overdue first, then due asc, then no-date last. Row shows:
`title | subject chip + type chip (EOL/FA/SA/Task) | due (relative: "in 2d") | status/score | [Open →]`.

Poll strategy: courses once per session, EOL once + per-subject `course_id` filter, assessments with `assessment_type` param (frontend already does this — `lms.py` currently omits params, fix in wrapper), tasks per course in parallel, cache 5 min.

### BFF mapping (Next.js + FastAPI, when approved)

```
GET /api/today → merged TODO (auth, tenant, refresh handled server-side)
GET /api/assignments?type=&subject=&q=
GET /api/subjects/{id}/files?q=
GET /api/attendance → merged sessions+days
```

Frontend keeps original detail URLs underneath every row — wrapper never re-implements test-taking/submission, only navigation + aggregation.

## 6. Open items before build

Resolved in v0.2.0 (October 2026):

- [x] TODO includes Learning Tasks: yes, alongside EOL, FA and SA. Resources stay in the Library and class pages.
- [x] Grade-group display: dropped. Classes are listed by subject in the sidebar.
- [x] Token refresh: server-side, per-student persistent sessions (`openlms/sessions.py`, SQLite + opaque cookie), refreshed shortly before expiry.
- [x] Navigation speed: per-student server data cache with mixed TTLs (`openlms/cache.py`), `ETag`/`304` + `?sections=` on `/data.js`, and a browser `localStorage` stale fallback (`web/assets/cache.js`, cleared on logout).
- [x] Scope: openLMS reads live data; submissions, tests, messaging and mark-read link out to the matching Indus LMS page.

---
*Built as `openlms/` (FastAPI) + `web/` (static pages) reusing induslms-agent's `lms.py`. See the README.*
