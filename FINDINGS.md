# openLMS-indus — Findings from live Indus LMS audit

Date: 2026-10-07 (initial) + 2026-10-09 (deep audit with live EOL attempt)
Method: Chrome DevTools on logged-in session (`https://induslms.com/studentdashboard`)
  + bundle analysis (`assets/index-Cfwucqr4.js` ~8.9MB, Oct 09)
  + click-through of Assignments → EOL / FA / Learning Task / Messaging
  + live-observed EOL attempt (Economics ECO082, scored 4/5)
  + prior reverse-engineering in `~/induslms-agent` (`lms.py`, `server.py`, `skills/.../endpoints.md`)
Student: Siddhant Rajesh Harsoda, DP 2026-27, 7 subjects.

Goal (updated Oct 09): implement **near-complete LMS functionality directly
in openLMS** — not just an aggregator that redirects to IndusLMS, but
in-app views for results, submissions, feedback, tasks, files, messaging,
calendar, attendance, announcements. Test-taking/submission included as
explicit scope (breaks the old read-only rule — see §8).

---

## 1. Auth & storage (verified live)

- API base: `https://api.induslms.com`, headers `Authorization: Bearer <access>`.
- Login: `POST /api/v1/auth/login/ {email,password}` → `{access, refresh, user}`.
- Frontend keys in `localStorage`: `accessToken`, `refreshToken`, `tenantid`
  (`a118fede-...`), `loginrole=STUDENT`, `loginname`, `user`, `programAcademicYear=2026-27`,
  plus navigation state: `selectedCourseId`, `selectedClassId`, `selectedSubject`,
  `selectedCourseName`, `selectedClassName`, `selectedGrade` (e.g. `11C`),
  `resourcesListGrade`, `programYearId`, `userDomain`, `can_monitor`.
  The EOL/FA/Learning-Task pages read `selectedCourseId`/`selectedClassId`
  from localStorage — the URL slug (`/assignments/test/economics/eol`) is
  cosmetic. A wrapper must set these before rendering a subject view.
- Tenant fallback: `user.roles[0].tenant_id` or `INDUSLMS_TENANT`.
- Silent refresh VERIFIED live Oct 09: `401` on 6 calls →
  `POST https://api.induslms.com/api/token/refresh/ {refresh}` → `200
  {access, refresh}` → all calls retried with new Bearer. `lms.py`
  `refresh_token()` path (`/api/token/refresh/`) is correct.
- Note: CLI token at `~/.induslms_token.json` was expired during both audits
  (Oct 07 + Oct 09 00:48 UTC expiry); browser had auto-refreshed — wrapper
  needs silent refresh on 401, and ideally syncs the fresh tokens back so
  `tools/export.py` keeps working.

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

Live sample Oct 09 — Computer Science (`cid=bdbc1c79-…`, `classId=9801d874-…`):
EOL=5 all submitted 5/5 (the pending "B2 - Searching Algorithms" was submitted
Oct 08), FA=3 graded (STEAM 8/10, SDL 6/10, FA 10/20), SA=0,
Learning Tasks=2 overdue `assigned` ("Theme B - Programming" due 30 Sep,
"Linear & Binary Search Questions" due 06 Oct — `export.py` misses these
entirely), Resources=3 folders.
Global sweep Oct 09: EOL total 25, pending 12 (Economics ×7, English ×2,
French ×1, Business ×1); FA total 21, all graded; SA 0; tasks only in CS.

Economics (`cid=db2caef1-…`): EOL=12 (4 pending with "Take test", 3 attempts
left each; 4 expired; 4 submitted). ECO082 "Government Intervention / Subsidy"
due 22 Oct was attempted live (see §7).

Notifications link into the split:
`{type:eol, title, link:/assignments/test/computer-science/eol, course_id}` — no single inbox.

Cost today: 7 subjects × 4 task-lists = up to **28 page loads** to answer "what's due?".

### Per-leaf calls (corrected Oct 09)

| UI leaf | API call(s) |
|---|---|
| Resource | `GET /tenants/{tid}/resources/?course_id={cid}[&class_id={clid}][&grade=11]&page=&page_size=` (class_id/grade params are new) + children via `?parent_resource_id={rid}` |
| EOL | `GET /tenants/{tid}/eol-tests/my/?course_id={cid}` |
| FA | `GET /student/assessments/?assessment_type=FA&course_id={cid}&page=1&page_size=15` + `GET /assessments/sidebar-counts/?assessment_type=FA` + `GET /tenants/{tid}/teachers/` + `GET /api/v2/report-engine/form/?grade=11` + `GET .../objectives/?grade=11&subject=` + `GET /student/requests/summary/?assessment_ids={csv}` + `GET .../me/teacher/units/` → 404 (harmless, teacher-only) |
| SA | same as FA with `assessment_type=SA` (+ `GET /tenants/{tid}/curricula/MYP/assessment-categories` → 403 for DP student, harmless) |
| Learning Task | `GET /tenants/{tid}/assignments/student/list/?course_id={cid}` → detail `GET .../assignments/student/{id}/detail/` |
| Messaging | `GET /tenants/{tid}/messages/threads/` → `[]` for this student (inbox exists, empty) |

## 4. Why students call it bloated

1. No backend `assignments` endpoint — `/assignments?courseId=` is a client-side chooser, not data.
2. Same concept, 4 names: EOL Test / FA / SA / Learning Task, each own manager + table columns.
3. Redundant hierarchy: Programme → grade-group (1 subject) → subject → type-chooser → type.
4. Resources need N+1 folder crawl (`?parent_resource_id=` per folder).
5. Attendance = 2 calls (`/students/me/attendance/` + `.../attendance/day/`), inbox/files live outside LMS (Mail.app / Graph).
6. `export.py` gaps (Oct 09): no Learning Tasks fetch, no `course_id`/`assessment_type`
   params, drops most EOL row fields, no submission/feedback/requests/messaging.

## 5. Detail APIs — everything needed to render in-app (verified Oct 09)

### EOL result view (read-only, safe to embed)
`GET /tenants/{tid}/eol-tests/{testId}/students/{userId}/` →
`{submission_id, score{score,total_marks,percentage,submitted_at},
responses[{question_id,question_text,question_image_url,question_rich_json,
language_code,selected_option,correct_option,is_correct,marks_awarded,
ai_explanation,options{a..d{text,image,rich_json}}}], feedback[]}`.
Verified on COM005 (5/5, 5 questions, one cached `ai_explanation`).
UI: score header + per-question options with your/correct marks + "AI Learning
Note" per question.

### EOL explanations (POST but non-mutating to grades — embed behind a button)
`POST .../eol-tests/{testId}/students/{userId}/question-explanations/
{submission_id,question_id,question_text,options,selected_option,correct_option,is_correct}`
→ `{explanation, cached}`. Fires per question on demand; after submit the app
auto-fires one.

### FA/SA submission + feedback + extension requests (read-only, safe)
- `GET /student/assessments/{id}/submission/` → `{submission_urls,comment,submitted_at,status,answers}`
  (e.g. STEAM_1: `comment="Auto-submitted for manual marking"`, `answers=[]`).
- `GET /student/assessments/{id}/feedback/` → `{total_score,feedback_text,rubric_scores,annotated_files,final_remarks,has_feedback}`.
- `GET /student/requests/summary/?assessment_ids={csv}` → per assessment
  `{effective_due_date,past_due,resubmission_window_open,requests_used/max,can_request{extension,resubmission},latest}`.
- FA list row carries the full `assessment{...course_id,class_year_id,instructions,file_urls,questions,due_date,teacher_name,marking_mode}` — enough for a detail page.

### Learning Task detail (read-only, safe)
List item: `{id,title,instructions,due_date,status,score,grade,feedback_text,
attachments[{name,file_url,size_bytes,content_type}]}` — S3 `file_url`s are
directly downloadable.
`GET .../assignments/student/{id}/detail/` → `{assignment,recipient_status,submission,score,feedback_text}`.

### Messaging (read-only, safe)
`GET /tenants/{tid}/messages/threads/` → `[]` (empty inbox). Thread/message-send
endpoints not yet captured (no conversations to click) — next audit when a
thread exists.

### Bundle-derived (not yet live-fired by a student click)
- FA/SA submit: `POST /student/assessments/{id}/submit-questions/
  {responses[{question_id,selected_option|answer_text}],submission_urls,comment}`,
  `POST .../submit-upload/ {submission_urls,comment,assessment_id}`,
  `POST .../resubmit/ {keep_indexes,base_submitted_at,new_files,comment}`,
  `POST .../{id}/requests/ {request_type,reason,preferred_due_at}`,
  `POST /student/requests/{id}/cancel/`.
- Task submit: `POST /api/v1/s3uploads/get-upload-url/ {tenant_id,
  module:"assignment_submission",entity_id,filename}` → `PUT upload_url` →
  `POST .../assignments/student/{id}/submit/ {submission_text,submission_files}`.
  Upload module for FA/SA is the misspelled `"assesement"`.
- Proctoring constants: `MAX_EOL_MID_TEST_EXITS=3`,
  `PROCTOR_SUSPEND_THRESHOLD=4`, LS key `eol_mid_test_exits:v1:{tid}:{uid}:{testId}`.

## 6. EOL attempt lifecycle — observed live (ECO082, Oct 09 12:21–12:23 UTC)

1. **Take test** → passcode dialog (passcode was `1234` for this test;
   "Do not share your passcode. Contact your teacher if the test will not open.").
2. **Open:** `POST /tenants/{tid}/eol-tests/open/ {test_id:"ECO082",passcode:"1234"}`
   → `200 {id:"6ee61693-…"(uuid),short_id,title,subject,topic,grade,section,
   total_marks,questions[{id,question_text,question_image_url,
   option_a/b/c/d_text,option_*_image_url,*_rich_json,language_code,marks}],
   already_submitted:false,role:"student"}`.
   NOTE: `test_id` in the open call is the **short_id** (`ECO082`), not the uuid.
3. **Answering:** no network per question — pure client state. Dialog shows
   `Question N of 5`, `N answered`, `⚠ Not answered`, radio A–D, Previous/Next,
   Submit disabled until all answered. No exit/proctor calls observed in this
   clean run.
4. **Submit:** `POST /tenants/{tid}/eol-tests/{uuid}/submit/
   {test_id:uuid,passcode,answers:[{question_id,selected_option}×5]}` → `201
   {id(submission),test,student,score:"4.00",total_marks:"5.00",percent:"80.00",submitted_at}`.
   NOTE: submit uses the **uuid** from the open response, and re-sends the passcode.
5. **Post-submit auto-sequence:** `GET .../{uuid}/students/{userId}/` (result),
   `GET .../eol-tests/my/?course_id=` (list refresh), `POST .../question-explanations/`
   (auto AI note). Then the normal result dialog with View results/Feedback.

## 7. openLMS plan: near-complete LMS, not a redirect shell

### IA (keep current pages, add Test/Task detail)
- Home (Upcoming/Done/Late) + Class + Planner + Library + Progress stay.
- NEW `test.html?kind=eol|fa|sa&id=` — renders §5 detail in-app:
  EOL questions/options/your-vs-correct/marks/AI notes + Feedback button;
  FA/SA score + submission files + teacher feedback + request status.
- NEW task detail inline in `class.html?tab=work` — instructions, attachments
  (direct S3 links), submission state, feedback, score.
- Messaging panel in Progress (or Me) reading `messages/threads/`.
- EOL attempt flow in-app (`open → answer → submit → result`) per §6, with
  passcode prompt, exit-count parity (`mid_test_exit_count/max`, LS mirror),
  `can_attempt/is_expired/attempts_blocked` guards, and post-submit auto-refresh.

### Data layer fixes (`tools/export.py` + `lms.py` upstream)
- `eol_tests(tok,tid,course_id)` — add `?course_id=`; keep full row fields
  (`short_id,teacher_id,can_attempt,is_expired,expires_message,opens_message,
  attempt_status,mid_test_exit_*,attempts_*,percentage`).
- `assessments(tok, assessment_type, course_id, page_size=100)` — paginate all.
- NEW `assignment_tasks(tok,tid,course_id)` → list + detail per task.
- NEW `eol_result(tok,tid,testId,userId)`, `eol_open(tok,tid,short_id,passcode)`,
  `eol_submit(tok,tid,uuid,passcode,answers)`, `eol_explain(...)`.
- NEW `fa_submission(tok,id)`, `fa_feedback(tok,id)`, `requests_summary(tok,ids)`.
- NEW `message_threads(tok,tid)`.
- Poll: courses once/session; EOL/FA/SA/tasks per course in parallel; cache 5 min.
  Calendar/Planner reuses the same 4-way parallel fetch the LMS itself does.

Resolved in v0.2.0 (October 2026):

- [x] TODO includes Learning Tasks: yes, alongside EOL, FA and SA. Resources stay in the Library and class pages.
- [x] Grade-group display: dropped. Classes are listed by subject in the sidebar.
- [x] Token refresh: server-side, per-student persistent sessions (`openlms/sessions.py`, SQLite + opaque cookie), refreshed shortly before expiry.
- [x] Navigation speed: per-student server data cache with mixed TTLs (`openlms/cache.py`), `ETag`/`304` + `?sections=` on `/data.js`, JSON `GET /api/data` with files-only partial refresh for in-place Library/class hot-swaps, a browser `localStorage` stale fallback (`web/assets/cache.js`, cleared on logout), and a boot skeleton killing the page-switch flicker (fonts via head `<link>`s, not CSS `@import`). Stale crawls flag `resourcesStale` and pages banner + retry instead of failing.
- [x] Scope v0.2.0: openLMS reads live data; submissions, tests, messaging and mark-read link out to the matching Indus LMS page.

Direction after v0.2.0 (Oct 09 audit): remove the link-outs — implement
submissions, tests, messaging and mark-read **in-app** (§§5–7, §9). The
read-only rule is lifted everywhere including `induslms-agent`: write
functions belong in `lms.py` + CLI + MCP alongside the reads.

### Write-ops risk register (now in scope, handle explicitly)
- `eol open/submit`, `fa submit/resubmit/requests`, task S3-upload+submit are
  **mutating**. Re-implementing them means: passcode handling, proctor
  exit-count parity (3 exits → blocked, 4 → suspended), double-submit guards,
  and honest error mapping (`attempts_exceeded`, `proctor_suspended`,
  `past_due`). Ship detail views first; gate attempt/submit behind an explicit
  confirm, and never auto-retry a submit.
- `question-explanations` POST generates AI content server-side (no grade
  effect observed) — treat as read-ish, fire only on user tap.

## 8. Open items (post-v0.2.0)

- [x] TODO includes Learning Tasks (yes — 2 overdue CS tasks prove it).
- [x] Grade-group display: dropped (v0.2.0).
- [x] Attempt/submit in-app: EOL (§6 + §10C proctoring), FA/SA hand-in/resubmit/requests, task hand-in (Oct 09, `openlms/routes.py`, `web/test.html`).
- [x] Messaging send + thread-detail: verified live Oct 09 (test message `8a3f2ca9-…` to Madhukar A).
- [ ] SA has 0 rows for this student — verify SA detail against a subject that has one, or treat as FA-identical per bundle.
- [ ] Uncaptured live-fires still needed: unsubmitted-FA submit dialog, task-submit PUT dance. Implemented from the bundle (§10C); the first real use should be watched.

---
*Live trace IDs (Oct 09): ECO082 open `6ee61693-1a73-4c2d-93bb-1935cfb7ab5c`,
submission `4a7c271a-db09-46ba-98d2-dc460cdd7c16`, score 4.00/5.00 (80%).*

## 9. Redirect-feature inventory + backend plan (Oct 09)

Standing decision: **nothing stays read-only** — write functions go into
`induslms-agent` (`lms.py` + CLI + MCP) as well as openLMS's own backend.
Keep secrets safe (tokens never logged/committed/returned), but do not block
mutating features. Prompt file for the build: `~/Downloads/UPDATES.md`.

### A. Every feature that still redirects (or is a static stub)

| # | Feature | openLMS today | LMS source of truth | Integration shape |
|---|---|---|---|---|
| 1 | Announcements full view | class stream: 280-char snippet, attachment count only | `GET /api/announcements/visible/?academic_year=` → full objects `{creator{full_name,email,subject},target_type class\|school,grade,subject,title,message(HTML),file_urls[{url,type}],created_at}` (16 items); `POST /api/announcements/{id}/read/` → `{recorded:true}` auto-fires on open | new full-body view + attachment links (direct S3) + search + read-recording. NOTE: `lms.py` uses `GET /api/announcements/` — switch exporter to `/visible/` |
| 2 | Notifications center | progress feed: 25 static rows, no pages/search/mark-read | `GET .../notifications/?limit=&offset=` (+`unread_count`); `POST .../notifications/{id}/read/`; `POST .../notifications/read-all/` (bundle; click only deep-links + persists subject context, no auto-read) | paginated inbox All/Unread/Read + search + DISMISS (read) + deep-link to FA/EOL list with `fromNotification` subject context |
| 3 | Messaging | absent | `GET .../messages/contacts/` (29: `{user_id,full_name,role,email,subjects}`); `GET .../messages/threads/`; `GET .../messages/conversation/{uid}/` (client reverses `results`); `POST .../messages/ {to_user_id,text}` → 201. LIVE-TESTED: message `8a3f2ca9-…` to Madhukar A (Maths, `cb384ae9-…`) sent, visible in threads+conversation, `status:sent` | inbox + thread view + compose via contacts + send. No websocket — poll threads/conversation |
| 4 | EOL attempt + result | absent | §6 open/submit/result/explain, all live-verified | `test.html?kind=eol`: passcode dialog → answer pager → submit → result + AI notes + Feedback |
| 5 | FA/SA take + resubmit + extension requests | absent | bundle-mapped: `submit-questions`, `submit-upload`, `resubmit`, `requests`, `requests/cancel` + `requests/summary` (verified read) | replicate Take-Test dialog (questions vs file-upload variants) + request buttons; needs live-fire audit with an unsubmitted FA |
| 6 | Learning Task submit | absent (and list missing from export) | list+detail verified (§5); submit via `s3uploads/get-upload-url` (`module:"assignment_submission"`) + `POST .../submit/` (bundle) | detail first, submit second; uploader does the S3 PUT dance |
| 7 | School Policies | absent | `GET .../academic-years/{pyid}/policies/` × N years → `{title,description,file_url,version,status}` (4 PDFs, `eagle-lms-common-uploads` bucket) | trivial list + open/download links |
| 8 | Learning Pathway | Progress "completion" is a rough stub | client aggregate of courses + FA + SA + `eol-tests/my/?year=` (+ `/learning-pathway/subject-plan/` in bundle, uncaptured) | reuse exporter data for v1 roadmap; capture subject-plan later |
| 9 | Progress Reports | absent | 3 parallel calls, ALL EMPTY for DP: `GET /api/v2/report-engine/student-pdfs/` → `{total:0,pdfs:[]}`; `.../myp/.../my-published/` (pending); `.../pyp/.../my-published/` → `{reports:[],count:0}`. `lms.py` already covers student-pdfs (bare call, no `?student_id=` needed) | empty-state + PDF list/download when present |
| 10 | Help | absent | `GET .../help/?audience=student` → `{count:0,results:[]}` | list or hide when empty |
| 11 | LMS Support tickets | absent | `/api/v1/lms-support/tickets/` + `/super/unlock/` with separate `lms_support_super_token` in LS (bundle only) | deprioritize (admin-ish); capture ticket-create flow later |
| 12 | Attendance detail | Planner ring+heatmap from export | `GET /students/me/attendance/` + `.../attendance/day/` (page stalled on re-audit — API throttling after burst; endpoints already known) | day table + subject filter when API responsive |
| 13 | My Calendar | Planner covers school events + deadlines | `GET /api/v1/school-calendar/events/` + `scope-options` + the 4-way aggregate (tasks+EOL+FA+SA) | already covered; verify personal-deadline diff later |
| — | Presence heartbeat | n/a | `POST /api/v1/presence/heartbeat/` — teacher-only (`loginrole==teacher`) | ignore for student app |

### B. Backend: why the static app cannot do any of the above live

- **CORS blocks direct browser calls.** Every API response carries
  `access-control-allow-origin: https://induslms.com` (+ `allow-credentials`).
  A fetch from openLMS's origin (`localhost:8000`, `file://`, any hosting)
  fails preflight. A "live mode" in pure static JS is **not viable**.
- **Tokens are origin-bound.** `accessToken/refreshToken` live in
  `induslms.com` localStorage; no other origin can read them.
- **Therefore: a same-origin BFF — already exists as `openlms/` (v0.2.0:
  FastAPI `app.py` + `sessions.py` + `cache.py` + `data.py`, `web/login.html`).**
  Extend it with the write functions below instead of scaffolding something new:
  browser → `openlms/` (same origin, no CORS) → `api.induslms.com`.
  Static JS tries BFF first (live: `/api/data`, `?sections=`, `ETag`/`304`),
  falls back to `window.LMS`/`data.js` (export/offline/demo) and the
  `localStorage` stale snapshot (`web/assets/cache.js`).
- **BFF surface (v1):** `GET /api/today /api/assignments /api/eol/:id/result
  /api/fa/:id/{submission,feedback} /api/tasks /api/tasks/:id
  /api/announcements /api/notifications /api/messages/{contacts,threads,conversation/:uid}
  /api/policies /api/reports /api/help /api/attendance* /api/calendar`;
  `POST /api/eol/{open,submit,explain} /api/fa/:id/{submit,resubmit,request}
  /api/tasks/:id/submit /api/announcements/:id/read
  /api/notifications/{:id/read,read-all} /api/messages`.
  S3 PUT dance for task/FA file uploads runs server-side.
- **BFF auth:** per-student sessions in `openlms/sessions.py` (v0.2.0), silent
  refresh before expiry exactly like the browser; tokens never reach the
  frontend.
- **Boundary:** no read-only boundary anymore — mirror each POST in `lms.py`
  (agent) and expose it through the BFF routes above.

### C. Sequencing
P0 read-path embeds on the existing BFF (announcements full+read, notifications
center+read, policies, reports empty-state, messages read+send, EOL/FA result
views, task detail) → P1 EOL attempt → P2 FA/task submits + extension requests →
P3 pathway roadmap, support tickets. Uncaptured live-fires still needed:
unsubmitted-FA submit dialog, task submit PUT dance, SA detail (0 rows for
this student).

## 10. Performance (measured Oct 09) + corrections

Account: a second DP student (7 courses), from India, Oct 09 evening. Scripts
kept out of the repo; numbers are medians unless noted.

### A. Where the time goes

| Measurement | Result |
|---|---|
| Network to `api.induslms.com` | DNS 14 ms, TCP connect 254 ms (≈1 RTT), TLS 536 ms |
| One request, new connection each time (`requests.get`, what `lms.py` ≤0.3.1 did) | ~1,050 ms |
| Same request on a pooled keep-alive session | ~280 ms (first one ~1,200 ms) |
| Indus dashboard after the access token expired while the tab was closed | 6/6 calls `401` (~1.2 s), refresh 1.0 s, retry ~3.4 s: **5.7 s** vs **1.3 s** with a fresh token |
| openLMS cold `data.js` (old path: resource crawl, then fan-out) | crawl 11.3 s / 33 requests (first top-level page alone 5.4 s) + fan-out 3.7 s = **15 s**; A/B 3 rounds: 17.5 s median (12.7–21.0) |
| openLMS cold `data.js` (new path: pooled fan-out, crawl in background) | **3.3 s** median (3.2–4.5); live browser check 3.7 s |
| openLMS repeat visit (saved copy + `If-None-Match`) | DOMContentLoaded **29 ms**; revalidation `304` in 3 ms |
| Slowest single endpoints (server time) | `eol-tests/my/` 2–3.4 s, `students/me/attendance/` 2.4–2.7 s, `notifications/?limit=100` 3.7 s (vs ~1.3 s at 20) |
| Indus bundle | `index-Cfwucqr4.js` 8.92 MB (2.95 MB gzipped), `cache-control: public, max-age=0` (revalidated every load), ~0.5 s download + ~0.2 s parse/eval on a fast Mac (expect several times that on school laptops/phones) |

Variance is high: the same build took 2.6–11.7 s across runs minutes apart,
consistent with server-side throttling after bursts.

### B. What openLMS changed

1. `lms.HTTP`: one pooled `requests.Session` (induslms-agent 0.4.0). Every upstream call reuses connections.
2. `data.js` no longer waits for the resource crawl. The payload ships with the last known files (or none, `resourcesPending`), the crawl runs in a background thread (singleflight per student) and patches the cached payload; file pages ask `?wait=1`.
3. Tokens are refreshed 5 minutes before expiry (was 60 s), on the pooled connection; reads retry once after a forced refresh on `401`, writes never retry.
4. Browser: stale-while-revalidate. `cache.js` renders the last copy, `app.js` revalidates with the payload `ETag` (`window.LMS_ETAG` in `data.js`). No polling: a visible tab revalidates when it's been 5+ minutes; messages poll only while a conversation is open and visible (15 s, backing off to 2 min).
5. Notifications in the payload capped at 30 (the centre pages the rest); Google Fonts no longer block first paint.
6. Detail views cached per student for 5 minutes (`OPENLMS_DETAIL_TTL`); writes invalidate what they touch.

### C. Corrections and new facts (probes + bundle, Oct 09)

- EOL rows carry `id` == `test_id` (uuid) and `short_id`; the global `eol-tests/my/` list (19 rows) is a superset of the per-course lists (9 rows summed): tests from courses outside the student's course list only appear globally. Keep the global list.
- FA/SA `submission/` and `feedback/` take `assessment.id`; the wrapper `assignment_id` 404s.
- `requests/summary` items: `can_request.{extension,resubmission}` is `{ok, code, message}` (not a boolean) and `latest` is `{extension, resubmission}`, each null or a request.
- Notification `ref_id` is the assessment id (titles keep the name at publish time; teachers rename assessments later). `meta` carries `subject`, `assessment_type`.
- Learning tasks: the global `assignments/student/list/` already returns them (same 2 rows as per-course); rows include `attachments[{name, file_url}]`.
- Proctoring: on `visibilitychange` → hidden during an attempt the web app sends `POST /tenants/{tid}/eol-tests/{uuid}/proctoring/ {event_type: "document_visibility_hidden"}` → `{proctor_violation_count, suspend_threshold, proctor_suspended}`; warning `n/(threshold-1)`, terminate at the threshold. Mid-test exits are counted only in localStorage (`eol_mid_test_exits:v1:{tid}:{uid}:{uuid}`, max 3), combined with the row's `mid_test_exit_count`. Copy/paste is blocked. Unanswered questions are sent as `"a"` by the web app; openLMS requires every answer instead.
- Uploads: `POST /api/v1/s3uploads/get-upload-url/ {tenant_id, module, entity_id, filename, content_type}` → `{upload_url, file_url, upload_id, method}`; tasks use a fresh `entity_id` per hand-in and send `submission_files[{file_url, name, content_type, size_bytes}]` with `submission_text: ""` (the web app requires at least one file). FA/SA upload with module `assesement` and send `submission_urls` as plain `file_url` strings; MCQ answers send `selected_option`, others `answer_text`.
- Policies: `GET /api/v1/tenants/{tid}/academic-years/{program_year_id}/policies/` for every programme year (DP, MYP, PYP all answer), deduped by title. Help: `GET /api/v1/tenants/{tid}/help/?audience=student`. EOL teacher feedback: `GET .../eol-tests/{uuid}/feedback/` → `{feedbacks}`.
- Conversation messages: `{id, from_user_id, from_user_name, to_user_id, text, sent_at, read_at, status, status_label}`; contacts `{user_id, full_name, role, email, subjects, subject_label}`.

