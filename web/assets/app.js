// SPDX-License-Identifier: GPL-3.0-or-later
let D = window.LMS;
const TODAY = new Date();
// Keep fresh server data for instant repeat visits. A copy that was itself
// loaded from storage (stale-while-revalidate) is not re-saved, so it can't
// outlive its age limit.
try { if (!window.OPENLMS_SWR && window.__lmsSave) window.__lmsSave(D, window.LMS_ETAG); } catch (e) {}
// Detail pages, tests, messaging and submissions run in-app when the server
// (or the demo) is there. A static export links to Indus LMS instead.
const IN_APP = !!(D && (D.live || D.demo));

/* ---------- Page lifecycle: render now, revalidate in the background ----------
   Pages call page(render). On a repeat visit cache.js has already put the
   saved copy in window.LMS, so the page paints with zero network wait; then
   revalidate() asks /api/data with If-None-Match. A 304 changes nothing; new
   data re-renders in place (or offers a "Show latest" toast once the student
   has started interacting). Detail pages (`{ detail: true }`) only refresh
   the sidebar and bell, so an open test or conversation is never reset. */
let _pageFn = null, _pageOpts = {}, _shell = null, _chrome = null, _touched = false, _lastSync = Date.now();
let _pageCtl = new AbortController();
const _teardown = [];
const pageSignal = () => _pageCtl.signal;
function onTeardown(fn) { _teardown.push(fn); }
['pointerdown', 'keydown'].forEach(t => addEventListener(t, () => { _touched = true; }, { capture: true, passive: true }));

function page(fn, opts = {}) {
  _pageFn = fn; _pageOpts = opts;
  const host = document.querySelector('.with-side');
  if (host && _shell === null) _shell = host.innerHTML;
  fn();
  resourcesBanner();
  if (window.OPENLMS_SWR) revalidate();
}
function rerender(next) {
  D = window.LMS = next; _assignments = null;
  if (_pageOpts.detail) { refreshChrome(); return; }
  _pageCtl.abort(); _pageCtl = new AbortController();
  _teardown.splice(0).forEach(f => { try { f(); } catch (e) {} });
  document.querySelectorAll('body > nav.side, #inbox-shade, #agenda, #inbox, #resbar, #toasts').forEach(n => n.remove());
  const host = document.querySelector('.with-side');
  if (host && _shell !== null) host.innerHTML = _shell;
  const y = scrollY;
  _pageFn();
  scrollTo(0, y);
  resourcesBanner();
}
function revalidate() {
  if (!D || !D.live) return;
  _lastSync = Date.now();
  const etag = window.__lmsEtag && window.__lmsEtag();
  fetch('api/data', { cache: 'no-store', headers: etag ? { 'If-None-Match': etag } : {} }).then(r => {
    if (r.status === 401) { try { window.__lmsClear && window.__lmsClear(); } catch (e) {} location.replace('login.html'); return; }
    window.OPENLMS_SWR = false;
    if (!r.ok) return; // 304: the copy on screen is current
    const tag = r.headers.get('ETag');
    return r.json().then(next => {
      try { window.__lmsSave && window.__lmsSave(next, tag); } catch (e) {}
      if (!_touched || _pageOpts.detail) rerender(next);
      else toast('Updates from Indus LMS are ready.', 'info', { label: 'Show latest', run: () => rerender(next) });
    });
  }).catch(() => {});
}
// No polling: a tab left open picks up changes when it is looked at again.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && Date.now() - _lastSync > 5 * 60000) revalidate();
});

// Files load in the background on the server (the crawl takes ~10 s cold).
// Pages that show files define window.__lmsRefreshResources to swap them in.
function resourcesBanner() {
  document.getElementById('resbar')?.remove();
  if (!D || !D.live || !(D.resourcesStale || D.resourcesPending) || typeof window.__lmsRefreshResources !== 'function') return;
  const bar = document.createElement('div');
  bar.id = 'resbar';
  bar.setAttribute('role', 'status');
  bar.className = 'resbar';
  bar.textContent = D.resourcesPending ? 'Loading your files…' : 'Updating resources…';
  document.body.insertAdjacentElement('afterbegin', bar);
  window.__lmsRefreshResources().then(ok => {
    if (ok) { bar.textContent = 'Files up to date.'; setTimeout(() => bar.remove(), 2000); }
    else retry('Files may be out of date.');
  }).catch(() => retry('Couldn’t load files.'));
  function retry(msg) {
    bar.innerHTML = `${msg} <button type="button">Retry</button>`;
    bar.querySelector('button').onclick = () => { D.resourcesStale = true; resourcesBanner(); };
  }
}
async function fetchResources() {
  const mode = D.resourcesStale ? 'refresh=1' : 'wait=1';
  const r = await fetch(`api/data?${mode}&sections=resources,resourcesStale,resourcesPending`, { cache: 'no-store' });
  if (!r.ok) return false;
  const data = await r.json();
  Object.assign(D, { resources: data.resources || [], resourcesStale: !!data.resourcesStale, resourcesPending: !!data.resourcesPending });
  try { window.__lmsSave && window.__lmsSave(D, null); } catch (e) {}
  return true;
}

/* ---------- Server calls ---------- */
class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}
// JSON call to the openLMS server (same origin; it talks to Indus LMS).
// Demo data answers locally. Writes are sent exactly once.
async function api(path, { method = 'GET', json, form } = {}) {
  if (!D.live) return demoApi(path, method, json, form);
  const opts = { method, cache: 'no-store', headers: {} };
  if (json !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;
  let r;
  try { r = await fetch(`api/${path}`, opts); }
  catch (e) { throw new ApiError('Can’t reach openLMS. Check your connection and try again.', 0); }
  const body = await r.json().catch(() => null);
  if (r.status === 401 && method === 'GET') { location.replace('login.html'); throw new ApiError('Sign in again.', 401); }
  if (!r.ok) {
    const d = body && body.detail;
    throw new ApiError(typeof d === 'string' ? d : (d && d.message) || `Something went wrong (${r.status}).`, r.status, d && d.code);
  }
  return body;
}

/* ---------- Demo mode: the same detail views from demo data ---------- */
const _demo = { proctor: 0 };
function demoApi(path, method, json) {
  const X = D.demoDetail || {}, later = v => new Promise(res => setTimeout(() => res(v), 220));
  const [p, qs] = path.split('?'), q = new URLSearchParams(qs || ''), now = new Date();
  const row = id => D.eol.find(e => e.id === id || e.testId === id);
  const result = (id, answers) => {
    answers = answers || _demo[`answers:${id}`];
    const responses = X.eolQuestions.map((x, i) => {
      const selected = answers ? answers[x.id] : (i === 1 ? 'a' : x.correct);
      return { ...x, selected, correct: x.correct, isCorrect: selected === x.correct, awarded: selected === x.correct ? 1 : 0,
        note: i === 1 && !answers ? 'An inverse undoes the function: add 6, then divide by 3.' : null };
    });
    const score = responses.filter(r => r.isCorrect).length;
    return { submissionId: 'demo', score: score.toFixed(2), total: responses.length.toFixed(2), percentage: Math.round(score / responses.length * 100), submittedAt: now.toISOString(), responses };
  };
  if (!D.live && !D.demo) return Promise.reject(new ApiError('This needs the openLMS server. Open it on Indus LMS instead.', 0));
  if (method !== 'GET') {
    let m;
    if (p === 'eol/open') {
      const r = row(json.short_id);
      if (!r || json.passcode !== '1234') return Promise.reject(new ApiError('Wrong passcode. In the demo every passcode is 1234.', 400));
      return later({ id: r.id, shortId: r.testId, title: r.title, subject: r.subject, total: '3.00', questions: X.eolQuestions.map(({ correct, ...x }) => x) });
    }
    if ((m = p.match(/^eol\/([^/]+)\/submit$/))) {
      _demo[`answers:${m[1]}`] = json.answers;
      const res = result(m[1], json.answers), r = row(m[1]);
      if (r) Object.assign(r, { status: 'graded', submitted: now.toISOString(), score: res.score, total: res.total, canAttempt: false });
      _assignments = null;
      return later({ score: res.score, total: res.total, percent: String(res.percentage), submittedAt: res.submittedAt, result: res });
    }
    if (/^eol\/[^/]+\/proctor$/.test(p)) { _demo.proctor++; return later({ violations: _demo.proctor, threshold: 4, suspended: _demo.proctor >= 4 }); }
    if (/^eol\/[^/]+\/explain$/.test(p)) return later({ explanation: 'Work from the inside out: evaluate g first, then apply f to that result.', cached: false });
    if (p === 'messages') {
      const msg = { id: `m${Date.now()}`, mine: true, text: json.text, at: now.toISOString() };
      ((X.conversations ||= {})[json.to_user_id] ||= []).push(msg);
      return later(msg);
    }
    return later({ ok: true, demo: true });
  }
  let m;
  if ((m = p.match(/^eol\/([^/]+)$/))) {
    const r = row(m[1]);
    if (!r) return Promise.reject(new ApiError('This test isn’t in your list.', 404));
    const done = !!r.submitted;
    return later({ test: r, result: done ? result(r.id) : null, feedback: done ? [{ feedback_text: 'Good work. Review inverse functions before the unit test.', created_at: r.submitted }] : [] });
  }
  if ((m = p.match(/^fa\/([^/]+)$/))) {
    const a = D.assessments.find(x => x.id === m[1]);
    if (!a) return Promise.reject(new ApiError('This assessment isn’t in your list.', 404));
    const graded = /graded/.test(a.status || ''), future = a.due && new Date(a.due) > now;
    return later({
      assessment: { ...a, instructions: `<p>Complete the ${esc(a.title)} task. Show your working and cite any sources.</p>`,
        files: [{ name: 'Task brief.pdf', url: null }], questions: a.questions ? X.faQuestions : [], studentFiles: [] },
      submission: a.submitted ? { files: [{ name: 'my-work.pdf', url: null }], comment: '', submittedAt: a.submitted } : null,
      feedback: graded ? { score: a.marks, html: '<p>Clear structure and accurate analysis. Expand the evaluation section next time.</p>', remarks: '', rubric: [{ criterion: 'Knowledge', score: 6 }, { criterion: 'Application', score: 5 }], files: [] } : null,
      requests: { enabled: true, requests_used: 0, requests_max: 3, min: 10, max: 500,
        can_request: { extension: !a.submitted && future ? { ok: true } : { ok: false, message: 'Asking for more time is not available. Please talk to your teacher.' },
          resubmission: graded ? { ok: true } : { ok: false, message: 'You can ask to resubmit once your work is graded.' } },
        latest: { extension: null, resubmission: null } },
    });
  }
  if ((m = p.match(/^tasks\/([^/]+)$/))) {
    const t = D.tasks.find(x => x.id === m[1]);
    if (!t) return Promise.reject(new ApiError('This task isn’t in your list.', 404));
    return later({ ...t, instructions: `<p>${esc(t.title)}: hand in one PDF.</p>`, attachments: [{ name: 'Instructions.pdf', url: null }],
      feedback: '', submission: t.submitted ? { files: [{ name: 'submission.pdf', url: null }], text: '', submittedAt: t.submitted } : null });
  }
  if (p === 'messages/contacts') return later(X.contacts || []);
  if (p === 'messages/threads') return later(D.threads || []);
  if ((m = p.match(/^messages\/conversation\/(.+)$/))) return later({ messages: (X.conversations || {})[m[1]] || [] });
  if (p === 'notifications') {
    const f = q.get('filter'), needle = (q.get('q') || '').toLowerCase();
    const items = D.notifications.filter(n => (f === 'unread' ? !n.read : f === 'read' ? n.read : true) && (!needle || `${n.title} ${n.message}`.toLowerCase().includes(needle)));
    return later({ unread: D.unread, items, nextOffset: null });
  }
  if (p === 'announcements') return later(D.announcements);
  if (p === 'policies') return later(X.policies || []);
  if (p === 'reports') return later({ total: 0, reports: [] });
  if (p === 'help') return later([]);
  if (p === 'attendance/day') return later({ records: D.attendance.records.map(r => ({ date: r.date, status: r.status, reason: r.status === 'absent' ? 'Sick leave' : '', class: '11C' })) });
  return Promise.reject(new ApiError('Not available in the demo.', 404));
}

/* ---------- Small UI kit: toasts, confirm dialogs, files ---------- */
function toast(message, tone = 'ok', action) {
  let box = document.getElementById('toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; box.className = 'toasts'; box.setAttribute('role', 'status'); document.body.appendChild(box); }
  const t = document.createElement('div');
  t.className = `toast ${tone}`;
  t.innerHTML = `<span>${esc(message)}</span>${action ? `<button type="button">${esc(action.label)}</button>` : ''}`;
  if (action) t.querySelector('button').onclick = () => { t.remove(); action.run(); };
  box.appendChild(t);
  setTimeout(() => t.remove(), action ? 12000 : 4500);
}
// Promise<boolean>. Every write that changes school data goes through one of these.
function confirmDialog({ title, html = '', confirm = 'Confirm', cancel = 'Cancel', danger = false }) {
  return new Promise(resolve => {
    const d = document.createElement('dialog');
    d.className = 'dlg';
    d.innerHTML = `<form method="dialog"><h2>${esc(title)}</h2><div class="dlg-body">${html}</div>
      <div class="dlg-actions"><button class="btn ghost" value="no">${esc(cancel)}</button><button class="btn ${danger ? 'danger' : ''}" value="yes" autofocus>${esc(confirm)}</button></div></form>`;
    document.body.appendChild(d);
    d.addEventListener('close', () => { resolve(d.returnValue === 'yes'); d.remove(); });
    d.showModal();
  });
}
function fileChips(files, empty = '') {
  if (!files || !files.length) return empty;
  return `<div class="filechips">${files.map(f => {
    const k = fileKind(f.name), inner = `<span class="ftype-sm" style="background:${k.color}">${k.label}</span><span>${esc(f.name)}</span>`;
    return f.url ? `<a class="filechip" href="${esc(f.url)}" target="_blank" rel="noopener">${inner}</a>` : `<span class="filechip">${inner}</span>`;
  }).join('')}</div>`;
}
const skeleton = (lines = 4) => `<div class="skel">${Array.from({ length: lines }, (_, i) => `<span style="width:${[92, 76, 84, 60, 70][i % 5]}%"></span>`).join('')}</div>`;
const fmtDateTime = d => d ? new Date(d).toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }) : '—';

const SUBJECTS = [
  { key: 'math', match: /math/i, short: 'Maths', c1: '#5B4FCF', c2: '#ECEAFB', glyph: 'Σ' },
  { key: 'phys', match: /physics/i, short: 'Physics', c1: '#2276B8', c2: '#E3EFF8', glyph: 'atom' },
  { key: 'cs', match: /computer/i, short: 'Comp Sci', c1: '#2E8B57', c2: '#E2F3E9', glyph: '</>' },
  { key: 'eng', match: /english/i, short: 'English', c1: '#B5476B', c2: '#F7E6EC', glyph: 'Aa' },
  { key: 'bm', match: /business/i, short: 'Business', c1: '#C7811F', c2: '#FBF0DE', glyph: 'chart' },
  { key: 'ger', match: /german/i, short: 'German', c1: '#36414D', c2: '#E9ECEF', glyph: 'Ä' },
  { key: 'econ', match: /econ/i, short: 'Economics', c1: '#0F766E', c2: '#E3F2EF', glyph: '₹' },
  { key: 'chem', match: /chem/i, short: 'Chemistry', c1: '#A2468F', c2: '#F5E6F2', glyph: 'flask' },
  { key: 'bio', match: /bio/i, short: 'Biology', c1: '#5B8C2A', c2: '#ECF3E3', glyph: 'leaf' },
  { key: 'hist', match: /history/i, short: 'History', c1: '#8C5A2B', c2: '#F3EBE2', glyph: '§' },
  { key: 'ess', match: /environment/i, short: 'ESS', c1: '#3A8A5C', c2: '#E4F1E9', glyph: 'leaf' },
  { key: 'french', match: /french/i, short: 'French', c1: '#3B6FD8', c2: '#E5EDFB', glyph: 'Fr' },
];
const FALLBACK = { key: 'other', short: 'General', c1: '#84909C', c2: '#EEF1F3', glyph: '•' };
function subj(name) { return SUBJECTS.find(s => s.match.test(name || '')) || { ...FALLBACK, short: name || 'General' }; }

function glyphSvg(g, color, x, y, size) {
  const s = size;
  if (g === 'atom') return `<g transform="translate(${x},${y})" fill="none" stroke="${color}" stroke-width="${s/14}"><ellipse rx="${s/2}" ry="${s/5}"/><ellipse rx="${s/2}" ry="${s/5}" transform="rotate(60)"/><ellipse rx="${s/2}" ry="${s/5}" transform="rotate(-60)"/><circle r="${s/12}" fill="${color}"/></g>`;
  if (g === 'chart') return `<g transform="translate(${x - s/2},${y - s/2})" fill="${color}"><rect x="0" y="${s*.55}" width="${s*.22}" height="${s*.45}" rx="3"/><rect x="${s*.39}" y="${s*.3}" width="${s*.22}" height="${s*.7}" rx="3"/><rect x="${s*.78}" y="0" width="${s*.22}" height="${s}" rx="3"/></g>`;
  if (g === 'flask') return `<g transform="translate(${x - s/2},${y - s/2})" fill="${color}"><path d="M${s*.35} 0h${s*.3}v${s*.35}l${s*.3} ${s*.55}a${s*.08} ${s*.08} 0 0 1-${s*.07} ${s*.1}h-${s*.76}a${s*.08} ${s*.08} 0 0 1-${s*.07}-${s*.1}l${s*.3}-${s*.55}z"/></g>`;
  if (g === 'leaf') return `<g transform="translate(${x},${y}) rotate(-35)" fill="${color}"><path d="M0 ${-s/2} C ${s/2} ${-s/4}, ${s/2} ${s/4}, 0 ${s/2} C ${-s/2} ${s/4}, ${-s/2} ${-s/4}, 0 ${-s/2}z"/></g>`;
  return `<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" font-family="Manrope, sans-serif" font-weight="800" font-size="${s}" fill="${color}">${g.replace('<', '&lt;').replace('>', '&gt;')}</text>`;
}

function cover(name, w = 320, h = 120) {
  const s = subj(name);
  let seed = [...(name || 'x')].reduce((a, c) => a + c.charCodeAt(0), 0);
  const rnd = () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
  const off = rnd() * 60;
  const stripes = Array.from({ length: 6 }, (_, i) => {
    const x = off + i * (w / 5);
    return `<path d="M${x} ${h} L${x + h * .9} 0 L${x + h * .9 + 18 + rnd() * 26} 0 L${x + 18 + rnd() * 26} ${h}Z" fill="${s.c1}" opacity="${0.05 + rnd() * 0.08}"/>`;
  }).join('');
  const grid = Array.from({ length: Math.ceil(w / 24) }, (_, i) => `<line x1="${i * 24}" y1="0" x2="${i * 24}" y2="${h}" stroke="${s.c1}" stroke-opacity=".06"/>`).join('');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" style="display:block;width:100%;height:100%">
    <rect width="${w}" height="${h}" fill="${s.c2}"/>${grid}${stripes}
    <rect x="${w - 58 - h * .3}" y="${h / 2 - h * .3}" width="${h * .6}" height="${h * .6}" rx="${h * .14}" fill="#fff" opacity=".95"/>
    ${glyphSvg(s.glyph, s.c1, w - 58, h / 2, h * .28)}
  </svg>`;
}

const ICONS = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  tasks: '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  files: '<path d="M4 6a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>',
  progress: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  bell: '<path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 0 0 4 0"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-5-5"/>',
  file: '<path d="M6 2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M14 2v6h6"/>',
  megaphone: '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1zM17 8a5 5 0 0 1 0 8"/>',
  check: '<path d="M5 12l5 5L20 7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16.5v.5"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  sparkle: '<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  message: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  route: '<circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M8 19h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7"/>',
  report: '<path d="M6 2h8l6 6v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/><path d="M9 15v2M12 12v5M15 9v8"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M12 17v.5"/>',
  agenda: '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 3v2M16 3v2M8 10l1.5 1.5L12 9M8 16l1.5 1.5L12 15M14.5 10.5H17M14.5 16.5H17"/>',
  send: '<path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  school: '<path d="M3 10l9-5 9 5-9 5zM7 12.5V17c0 1.5 2.5 3 5 3s5-1.5 5-3v-4.5"/>',
  note: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.3 1 2.3h6c0-1 .4-1.8 1-2.3A7 7 0 0 0 12 2z"/>',
};
function icon(name, size = 20, extra = '') {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${extra}>${ICONS[name]}</svg>`;
}

// In-app pages. A static export (no server) links to the matching Indus LMS page instead.
const LMS = 'https://induslms.com';
const LMS_PAGES = [
  ['message', 'Messaging', '/messaging'],
  ['shield', 'School policies', '/school-policies'],
  ['route', 'Learning pathway', '/student-learning-pathway'],
  ['report', 'Progress report', '/studentprogressreport'],
  ['help', 'Help & support', '/help'],
];
const lmsUrl = path => LMS + (path?.startsWith('/') ? path : '/' + (path || ''));
function courseFor(subject) {
  const key = subj(subject).key;
  return D.courses.find(c => subj(c.title).key === key);
}
// Mirrors Indus LMS `toSubjectSlug`: lowercase, spaces to dashes, strip
// anything outside [a-z0-9-]. Used for /courses/:id/resources/:slug links,
// which need the slug (slug-less URLs render a Network Error on Indus).
const slugify = s => (s || '').toLowerCase().trim().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-');
function hubQs(course) {
  const q = new URLSearchParams();
  if (course?.id) q.set('courseId', course.id);
  if (course?.classId) q.set('classId', course.classId);
  return q.toString() ? `?${q}` : '';
}
// Subject hub: reads ?courseId=&classId= from the URL and repairs Indus
// localStorage, so it never shows the wrong subject. One click from EOL/FA/SA.
function hubLinkFor(subject) {
  const course = typeof subject === 'object' ? subject : courseFor(subject);
  return lmsUrl(`/assignments${hubQs(course)}`);
}
// Resource library: course id comes from the path, so it works cross-origin,
// but the trailing :slug segment is required.
function resourceLinkFor(subject) {
  const course = courseFor(subject);
  if (!course?.id) return lmsUrl('/resources');
  const slug = slugify(course.title);
  return lmsUrl(slug ? `/courses/${course.id}/resources/${slug}` : `/courses/${course.id}/resources`);
}
// The course a notification is about: by id, by the slug in its LMS link, or by subject.
function notifCourse(n) {
  const raw = n.link || '';
  const m = raw.match(/^\/?assignments\/test\/([^/?#]+)(?:\/([^/?#]+))?/i);
  let course = (n.courseId && D.courses.find(c => c.id === n.courseId)) || (n.course_id && D.courses.find(c => c.id === n.course_id));
  if (!course && m?.[1] && !['eol', 'fa', 'sa'].includes(m[1].toLowerCase())) course = D.courses.find(c => slugify(c.title) === m[1].toLowerCase());
  if (!course && n.subject) course = courseFor(n.subject);
  return { course, raw, m };
}
// Notification links from the LMS API look like `/assignments/test/<slug>/<eol|fa|sa>`
// with no course context. In-app they open the item itself when the
// notification names it, else that subject's work list.
function notifLinkFor(n) {
  const { course, raw, m } = notifCourse(n);
  const type = (m?.[2] || m?.[1] || n.type || '').toLowerCase();
  if (IN_APP) {
    const a = n.refId && assignments().find(x => x.id === n.refId);
    if (a) return detailHref(a);
    if (course && (m || /eol|fa|sa|task|assign|result|grade/.test(type))) return `class.html?c=${subj(course.title).key}&tab=work`;
    if (/resource/.test(type) || raw.startsWith('/courses/')) return course ? `class.html?c=${subj(course.title).key}&tab=files` : 'library.html';
    return n.id ? `updates.html#n-${encodeURIComponent(n.id)}` : 'updates.html';
  }
  const isTest = ['eol', 'fa', 'sa'].includes(type);
  if (course?.id && (isTest || !m)) return lmsUrl(`/assignments${hubQs(course)}`);
  if (course?.id && raw.startsWith('/courses/')) return resourceLinkFor(course.title);
  return lmsUrl(raw || '/notification');
}
function lmsLinkFor(kind, subject) {
  const course = courseFor(subject);
  const q = new URLSearchParams();
  if (course?.id) q.set('courseId', course.id);
  if (course?.classId) q.set('classId', course.classId);
  const qs = q.toString() ? `?${q}` : '';
  // Learning tasks: /studentassignment reads ?courseId= (camelCase) from the
  // URL, so a direct deep link works.
  if (kind === 'task') {
    const tq = new URLSearchParams();
    if (course?.id) tq.set('courseId', course.id);
    return lmsUrl(`/studentassignment${tq.toString() ? `?${tq}` : ''}`);
  }
  // EOL/FA/SA: the test pages ignore ?course_id=/courseId= in the URL and
  // filter by localStorage-selected course instead, so link to the subject
  // hub — it reads ?courseId=&classId= from the URL and repairs storage.
  if (course?.id) return lmsUrl(`/assignments${qs}`);
  const s = (subject && subject.toLowerCase() !== 'general') ? subject : '';
  return lmsUrl(s ? `/assignments/test/${kind}?subject=${encodeURIComponent(s)}` : `/assignments/test/${kind}`);
}
const extLink = (href, label, cls = 'btn ghost') =>
  `<a class="${cls} ext" href="${esc(href)}" target="_blank" rel="noopener">${label} ${icon('external', 13)}</a>`;
const detailHref = a => `test.html?kind=${a.type}&id=${encodeURIComponent(a.id)}`;
function actionFor(a) {
  if (!IN_APP || !a.id) {
    if (a.state === 'done') return extLink(a.link, 'View');
    if (a.type === 'eol') return extLink(a.link, a.state === 'late' ? 'Open' : 'Take test', a.state === 'late' ? 'btn ghost' : 'btn');
    return extLink(a.link, a.state === 'late' ? 'Open' : 'Submit', a.state === 'late' ? 'btn ghost' : 'btn');
  }
  const go = (label, primary) => `<a class="btn ${primary ? '' : 'ghost'} ext" href="${detailHref(a)}">${label}</a>`;
  if (a.state === 'done') return go('View', false);
  if (a.type === 'eol') return a.canAttempt && !a.blocked ? go('Take test', true) : go('Open', false);
  return a.state === 'late' ? go('Open', false) : go('Submit', true);
}

const LOGO = `<svg width="32" height="32" viewBox="0 0 32 32"><rect width="32" height="32" rx="9" fill="#E8A33D"/>
  <path d="M7 11c3-3 6 3 9 0s6 3 9 0M7 16c3-3 6 3 9 0s6 3 9 0M7 21c3-3 6 3 9 0s6 3 9 0" fill="none" stroke="#12302D" stroke-width="2.2" stroke-linecap="round"/></svg>`;

function sidebar(active, activeClass) {
  const open = assignments().filter(a => a.state !== 'done').length;
  const nav = [['home', 'Home', 'index.html', open], ['calendar', 'Planner', 'planner.html'], ['files', 'Library', 'library.html'], ['progress', 'Progress', 'progress.html']];
  if (IN_APP) nav.push(['message', 'Messages', 'messages.html'], ['bell', 'Updates', 'updates.html', D.unread], ['school', 'School', 'school.html']);
  return `<nav class="side"><a class="brand" href="index.html">${LOGO}<div>openLMS<small>${esc(D.program)} · ${esc(D.year)}</small></div></a>
    ${nav.map(([i, l, h, n]) => `<a href="${h}" class="nav ${active === i ? 'on' : ''}" ${active === i ? 'aria-current="page"' : ''}>${icon(i)}${l}${n ? `<span class="count">${n > 99 ? '99+' : n}</span>` : ''}</a>`).join('')}
    <h5>Classes</h5>
    ${D.courses.map(c => { const s = subj(c.title); return `<a class="cls ${activeClass === s.key ? 'on' : ''}" href="class.html?c=${s.key}" title="${esc(c.title)}"><i style="background:${s.c1}"></i><span>${esc(c.title)}</span></a>`; }).join('')}
    ${IN_APP ? '' : `<h5>On Indus LMS</h5>
    ${LMS_PAGES.map(([i, l, p]) => `<a class="cls lmslink" href="${lmsUrl(p)}" target="_blank" rel="noopener">${icon(i, 16)}<span>${l}</span>${icon('external', 12)}</a>`).join('')}`}
    ${D.live ? `<button class="nav signout" onclick="signOut()">${icon('logout')}Sign out</button>`
      : window.OPENLMS_DEMO ? `<button class="nav signout" onclick="signOut()">${icon('logout')}Exit demo</button>` : ''}
  </nav>`;
}
const badge = n => n ? `<b>${n > 99 ? '99+' : n}</b>` : '';
function topbar(placeholder = 'Search assignments, classes, files…') {
  return `<header class="topbar"><button class="menu-btn" onclick="document.body.classList.toggle('menu-open')" aria-label="Menu">${icon('menu')}</button>
    <label class="search">${icon('search', 16)}<input placeholder="${placeholder}" id="q"></label><div style="flex:1"></div>
    <button class="agenda-btn" id="agenda-btn" onclick="toggleAgenda(true)" aria-haspopup="dialog" aria-controls="agenda">${icon('agenda', 17)}<span>Academic Agenda</span>${badge(outstanding().length)}</button>
    <button class="bell" id="bell" onclick="toggleInbox(true)" aria-label="Open inbox" aria-haspopup="dialog" aria-controls="inbox">${icon('bell')}${badge(D.unread)}</button><span class="avatar" title="${esc(D.student)}">${initials(D.student)}</span></header>`;
}
// Detail pages keep their content when fresh data arrives; only counts change.
function refreshChrome() {
  const side = document.querySelector('nav.side');
  if (side && _chrome) side.outerHTML = sidebar(_chrome.active, _chrome.activeClass);
  const bell = document.getElementById('bell');
  if (bell) bell.innerHTML = icon('bell') + badge(D.unread);
  const ag = document.getElementById('agenda-btn');
  if (ag) ag.innerHTML = `${icon('agenda', 17)}<span>Academic Agenda</span>${badge(outstanding().length)}`;
}
async function signOut() {
  try { window.__lmsClear && window.__lmsClear(); } catch (e) {}
  await fetch('api/logout', { method: 'POST' }).catch(() => {});
  location.replace('login.html');
}
function mountChrome(active, activeClass, placeholder) {
  _chrome = { active, activeClass };
  const boot = document.getElementById('boot'); if (boot) boot.remove();
  if (!document.querySelector('link[data-logo]')) {
    const fav = document.createElement('link'); fav.rel = 'icon'; fav.dataset.logo = '1';
    fav.href = 'data:image/svg+xml,' + encodeURIComponent(LOGO.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" '));
    document.head.appendChild(fav);
  }
  document.body.insertAdjacentHTML('afterbegin', sidebar(active, activeClass));
  document.querySelector('.with-side').insertAdjacentHTML('afterbegin', topbar(placeholder));
  document.body.insertAdjacentHTML('beforeend', `<div class="inbox-shade" id="inbox-shade" onclick="closeDrawers()"></div>
    <aside class="inbox agenda" id="agenda" role="dialog" aria-modal="true" aria-labelledby="agenda-title" hidden>
      <header><div><h2 id="agenda-title">Academic Agenda</h2><p class="agenda-sub" id="agenda-sub"></p></div><button class="x" onclick="toggleAgenda(false)" aria-label="Close agenda">×</button></header>
      <div class="agenda-progress"><span id="agenda-bar"></span></div>
      <nav class="inbox-tabs" id="agenda-tabs" role="tablist"></nav>
      <div class="inbox-list" id="agenda-list"></div>
      <footer><p class="agenda-note">Ticks are saved on this device only.</p></footer>
    </aside>
    <aside class="inbox" id="inbox" role="dialog" aria-modal="true" aria-labelledby="inbox-title" hidden>
      <header><h2 id="inbox-title">Inbox</h2><button class="x" onclick="toggleInbox(false)" aria-label="Close inbox">×</button></header>
      <nav class="inbox-tabs" id="inbox-tabs" role="tablist"></nav>
      <div class="inbox-list" id="inbox-list"></div>
      <footer>${IN_APP ? `<a class="btn" href="messages.html">Messages</a><a class="btn ghost" href="updates.html">All updates</a>`
        : `${extLink(lmsUrl('/messaging'), 'Messages on Indus LMS', 'btn')}${extLink(lmsUrl('/announcement'), 'All announcements')}`}</footer>
    </aside>`);
  document.getElementById('inbox-tabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) renderInbox(b.dataset.tab); };
  document.getElementById('agenda-tabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) renderAgenda(b.dataset.tab); };
  document.getElementById('agenda-list').onchange = e => {
    const box = e.target.closest('input[data-key]'); if (!box) return;
    const done = ticked(); box.checked ? done.add(box.dataset.key) : done.delete(box.dataset.key);
    saveTicked(done); renderAgenda(agendaTab);
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawers(); }, { signal: pageSignal() });
}
function closeDrawers() { toggleInbox(false); toggleAgenda(false); }

// Academic Agenda: everything still to do, with personal ticks kept in this browser.
const outstanding = () => assignments().filter(a => a.state !== 'done');
const agendaKey = a => [a.type, a.subject, a.title, a.due || ''].join('|');
function ticked() { try { return new Set(JSON.parse(localStorage.getItem('agenda.ticked') || '[]')); } catch { return new Set(); } }
function saveTicked(set) { try { localStorage.setItem('agenda.ticked', JSON.stringify([...set])); } catch {} }
let agendaTab = 'all';
function agendaGroup(a) {
  if (a.state === 'late') return 'Overdue';
  if (!a.due) return 'No deadline';
  const n = daysUntil(a.due);
  return n <= 0 ? 'Today' : n === 1 ? 'Tomorrow' : n <= 7 ? 'This week' : 'Later';
}
function renderAgenda(tab = agendaTab) {
  agendaTab = tab;
  const all = outstanding(), done = ticked();
  const order = ['Overdue', 'Today', 'Tomorrow', 'This week', 'Later', 'No deadline'];
  const items = all.filter(a => tab === 'all' || (tab === 'late' ? a.state === 'late' : a.state === 'upcoming' && a.due && daysUntil(a.due) <= 7))
    .sort((a, b) => order.indexOf(agendaGroup(a)) - order.indexOf(agendaGroup(b)) || new Date(a.due || 8.64e15) - new Date(b.due || 8.64e15));
  const tickedCount = all.filter(a => done.has(agendaKey(a))).length;
  document.getElementById('agenda-sub').textContent = `${all.length} to do, ${tickedCount} ticked off`;
  document.getElementById('agenda-bar').style.width = `${all.length ? Math.round(tickedCount / all.length * 100) : 0}%`;
  const week = all.filter(a => a.state === 'upcoming' && a.due && daysUntil(a.due) <= 7).length;
  document.getElementById('agenda-tabs').innerHTML = [['all', 'Everything', all.length], ['late', 'Overdue', all.filter(a => a.state === 'late').length], ['week', 'Next 7 days', week]]
    .map(([k, l, n]) => `<button role="tab" data-tab="${k}" aria-selected="${tab === k}" class="${tab === k ? 'on' : ''}">${l}<span>${n}</span></button>`).join('');
  let html = '', last = null;
  for (const a of items) {
    const g = agendaGroup(a), s = subj(a.subject), key = agendaKey(a), on = done.has(key);
    if (g !== last) { html += `<h3 class="agenda-group ${g === 'Overdue' ? 'late' : ''}">${g}</h3>`; last = g; }
    const when = a.state === 'late' ? `Missed ${fmtDate(a.due, { day: 'numeric', month: 'short' })}`
      : a.due ? `Due ${fmtDate(a.due, { weekday: 'short', day: 'numeric', month: 'short' })}, ${fmtTime(a.due)}` : 'No deadline set';
    html += `<div class="agenda-item ${on ? 'ticked' : ''}">
      <label class="tick"><input type="checkbox" data-key="${esc(key)}" ${on ? 'checked' : ''} aria-label="Tick off ${esc(a.title)}"><span></span></label>
      <div><b>${esc(a.title)}</b><small><span style="color:${s.c1}">${esc(s.short)}</span> ${esc(a.kind)}. ${when}</small></div>
      ${actionFor(a)}</div>`;
  }
  document.getElementById('agenda-list').innerHTML = html || `<p class="inbox-empty">${tab === 'late' ? 'Nothing overdue.' : 'Nothing to do here. Enjoy the break.'}</p>`;
}
function toggleAgenda(open) {
  const box = document.getElementById('agenda');
  if (!box || open === !box.hidden) return;
  if (open) { toggleInbox(false); renderAgenda(); }
  box.hidden = !open;
  document.body.classList.toggle('agenda-open', open);
  (open ? box.querySelector('.x') : document.getElementById('agenda-btn'))?.focus();
}

function inboxItems() {
  const ann = D.announcements.map(a => ({
    kind: 'ann', icon: 'megaphone', title: a.title, text: a.message, by: [a.by, titleCase(a.subject)].filter(Boolean).join(' · '),
    at: a.at, href: IN_APP && a.id ? `updates.html?tab=ann#ann-${encodeURIComponent(a.id)}` : lmsUrl('/announcement'),
  }));
  const upd = D.notifications.map(n => ({
    kind: 'upd', icon: /fa|sa|eol|test|assess/.test(n.type || '') ? 'tasks' : 'bell', title: n.title, text: n.message, by: n.actor,
    at: n.at, unread: !n.read, href: IN_APP ? notifLinkFor(n) : lmsUrl(n.link || '/notification'),
  }));
  const msg = (D.threads || []).map(t => ({
    kind: 'msg', title: t.name, role: t.role, text: t.last, at: t.at,
    href: IN_APP ? `messages.html${t.userId ? `?u=${encodeURIComponent(t.userId)}` : ''}` : lmsUrl('/messaging'),
  }));
  return { ann, upd, msg, all: [...ann, ...upd, ...msg].sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0)) };
}
function renderInbox(tab = 'all') {
  const items = inboxItems();
  const tabs = [['all', 'All'], ['ann', 'Announcements'], ['upd', 'Updates'], ['msg', 'Messages']];
  document.getElementById('inbox-tabs').innerHTML = tabs.map(([k, l]) =>
    `<button role="tab" data-tab="${k}" aria-selected="${tab === k}" class="${tab === k ? 'on' : ''}">${l}<span>${items[k].length}</span></button>`).join('');
  const row = x => `<a class="inbox-item ${x.unread ? 'unread' : ''}" href="${esc(x.href)}" ${IN_APP ? '' : 'target="_blank" rel="noopener"'}>
      ${x.kind === 'msg' ? `<span class="avatar">${initials(x.title)}</span>` : `<span class="inbox-ic ${x.kind}">${icon(x.icon, 16)}</span>`}
      <div><b>${esc(x.title)}${x.role ? ` <span class="pill grey">${esc(titleCase(String(x.role).toLowerCase().replace(/_/g, ' ')))}</span>` : ''}</b>
      ${x.text ? `<p>${esc(x.text)}</p>` : ''}<small>${x.kind === 'msg' ? 'Message' : esc(x.by || '')}${x.at ? ' · ' + ago(x.at) : ''}</small></div></a>`;
  const empty = { all: 'Nothing new.', ann: 'No announcements.', upd: 'No updates.', msg: IN_APP ? 'No messages yet. Start one from Messages.' : 'No messages yet. Start a chat with a teacher on Indus LMS.' };
  document.getElementById('inbox-list').innerHTML = items[tab].slice(0, 40).map(row).join('') || `<p class="inbox-empty">${empty[tab]}</p>`;
}
function toggleInbox(open) {
  const box = document.getElementById('inbox');
  if (!box || open === !box.hidden) return;
  if (open) { toggleAgenda(false); renderInbox(); }
  box.hidden = !open;
  document.body.classList.toggle('inbox-open', open);
  (open ? box.querySelector('.x') : document.getElementById('bell'))?.focus();
}

const initials = n => (n || '?').split(/\s+/).map(p => p[0]).slice(0, 2).join('').toUpperCase();
const fmtDate = (d, opts = { day: 'numeric', month: 'short' }) => d ? new Date(d).toLocaleDateString('en-IN', opts) : '—';
const fmtTime = d => d ? new Date(d).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }) : '';
function ago(d) {
  const m = Math.round((Date.now() - new Date(d)) / 60000);
  if (m < 60) return `${Math.max(m, 1)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}
const daysUntil = d => Math.ceil((new Date(d) - TODAY) / 86400000);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const titleCase = s => (s || '').replace(/\b\w/g, c => c.toUpperCase()).replace(/\bAnd\b/g, 'and');
const has = v => v != null && v !== 'None' && v !== '';
function fileKind(name) {
  const ext = (name || '').split('.').pop().toLowerCase();
  if (ext === 'pdf') return { label: 'PDF', color: '#D64545' };
  if (['doc', 'docx'].includes(ext)) return { label: 'DOC', color: '#3B6FD8' };
  if (['ppt', 'pptx'].includes(ext)) return { label: 'PPT', color: '#C7811F' };
  if (['xls', 'xlsx', 'csv'].includes(ext)) return { label: 'XLS', color: '#2E8B57' };
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'heic'].includes(ext)) return { label: 'IMG', color: '#5B4FCF' };
  if (['mp4', 'mov'].includes(ext)) return { label: 'VID', color: '#A2468F' };
  return { label: (ext || 'FILE').slice(0, 4).toUpperCase(), color: '#84909C' };
}

// Lesson checks, FA/SA tests and learning tasks, each classified as:
//   done      submitted or graded (`lateSubmit` if after the deadline)
//   late      deadline passed with no submission
//   upcoming  open or not yet open
let _assignments;
function assignments() {
  if (_assignments) return _assignments;
  const eol = D.eol.map(e => ({
    type: 'eol', id: e.id, kind: 'Lesson check', title: e.topic && e.topic !== e.title ? `${e.title} · ${e.topic}` : e.title, subject: e.subject,
    status: e.status, due: has(e.due) ? e.due : null, opens: e.opens, assigned: e.assigned, submitted: has(e.submitted) ? e.submitted : null,
    score: e.score, total: e.total, teacher: e.teacher, scheduled: e.availability === 'scheduled', testId: has(e.testId) ? e.testId : null,
    canAttempt: e.canAttempt, blocked: !!(e.blocked || e.suspended || (e.exitMax && e.exits >= e.exitMax)),
  }));
  const tests = D.assessments.map(a => ({
    type: (a.type || 'fa').toLowerCase() === 'sa' ? 'sa' : 'fa', id: a.id, kind: [a.type, a.category].filter(has).join(' · ') || 'Task', title: a.title, subject: a.subject,
    status: a.status, due: has(a.due) ? a.due : null, assigned: a.assigned, submitted: has(a.submitted) ? a.submitted : null,
    score: a.marks, total: a.total, teacher: a.teacher,
  }));
  const learning = (D.tasks || []).map(t => ({
    type: 'task', id: t.id, kind: 'Learning task', title: t.title, subject: t.subject, status: t.status,
    due: has(t.due) ? t.due : null, assigned: t.assigned, submitted: has(t.submitted) ? t.submitted : null, teacher: t.teacher,
    score: t.score,
  }));
  _assignments = [...tests, ...learning, ...eol].map(a => {
    a.link = lmsLinkFor(a.type, a.subject);
    const done = !!a.submitted || /graded|submitted|completed|evaluated/i.test(a.status || '');
    const pastDue = a.due && new Date(a.due) < TODAY;
    a.state = done ? 'done' : pastDue ? 'late' : 'upcoming';
    a.lateSubmit = done && a.due && a.submitted && new Date(a.submitted) > new Date(a.due);
    a.graded = /graded|evaluated/i.test(a.status || '') && has(a.score);
    return a;
  });
  return _assignments;
}
const isDone = t => t.state === 'done';
function statusPill(t) {
  if (t.state === 'done') {
    const base = t.graded ? `<span class="pill green">${icon('check', 12)} ${+t.score}/${+t.total}</span>` : `<span class="pill cyan">${icon('check', 12)} Turned in</span>`;
    return t.lateSubmit ? `${base} <span class="pill red">Late</span>` : base;
  }
  if (t.state === 'late') return `<span class="pill red">${icon('alert', 12)} Missed · ${fmtDate(t.due)}</span>`;
  if (t.scheduled) return `<span class="pill violet">Opens ${fmtDate(t.opens)}</span>`;
  if (t.due) {
    const n = daysUntil(t.due);
    return `<span class="pill ${n <= 2 ? 'red' : 'amber'}">${icon('clock', 12)} Due ${n <= 0 ? 'today' : n === 1 ? 'tomorrow' : fmtDate(t.due)}</span>`;
  }
  return `<span class="pill amber">To do</span>`;
}
