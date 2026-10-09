// SPDX-License-Identifier: GPL-3.0-or-later
const D = window.LMS;
const TODAY = new Date();
// Persist for offline/stale fallback (server stays source of truth).
try { window.__lmsSave && window.__lmsSave(D); } catch (e) {}

// Stale-resources banner: the server sets D.resourcesStale when the file
// crawl failed and the page rendered reused/empty resources. Keep the stale
// files visible under a thin banner. Pages showing files (Library, class)
// expose window.__lmsRefreshResources to hot-swap fresh files in place;
// other pages fall back to one background refresh + reload, then manual
// retry, so a long LMS outage can't trap the page in a reload loop.
// Runs on DOMContentLoaded so page hooks (defined after this file) exist.
(function () {
  function run() {
    if (!D || !D.resourcesStale || !D.live) return;
    var KEY = 'openlms.res-retry';
    var bar = document.createElement('div');
    bar.setAttribute('role', 'status');
    bar.style.cssText = 'position:sticky;top:0;z-index:50;display:flex;align-items:center;justify-content:center;gap:8px;padding:6px 12px;font-size:12px;font-weight:700;background:var(--accent-soft,#FDF1DC);color:#9A6514;border-bottom:1px solid var(--line,#e5e7eb)';
    document.body.insertAdjacentElement('afterbegin', bar);
    function showRetry(msg) {
      bar.innerHTML = msg + ' <button id="resretry" style="font:inherit;text-decoration:underline;background:none;border:0;color:inherit;cursor:pointer">Retry</button>';
      var b = document.getElementById('resretry');
      if (b) b.onclick = function () {
        try { sessionStorage.removeItem(KEY); } catch (x) {}
        location.reload();
      };
    }
    if (typeof window.__lmsRefreshResources === 'function') {
      bar.textContent = 'Updating resources…';
      window.__lmsRefreshResources().then(function (ok) {
        if (ok) {
          bar.textContent = 'Resources updated.';
          setTimeout(function () { bar.remove(); }, 2500);
        } else showRetry('Resources may be outdated.');
      }).catch(function () { showRetry('Couldn’t update resources.'); });
      return;
    }
    var retried = false;
    try { retried = sessionStorage.getItem(KEY) === '1'; } catch (e) {}
    if (!retried) {
      bar.textContent = 'Updating resources…';
      try { sessionStorage.setItem(KEY, '1'); } catch (e) {}
      fetch('data.js?refresh=1', { cache: 'no-store' }).then(function () {
        location.reload();
      }).catch(function () { showRetry('Couldn’t update resources.'); });
    } else showRetry('Resources may be outdated.');
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();

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
};
function icon(name, size = 20, extra = '') {
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${extra}>${ICONS[name]}</svg>`;
}

// Actions (submitting, tests, messaging) happen on the real LMS; openLMS links to the exact page.
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
// Notification links from the LMS API look like
// `/assignments/test/<slug>/<eol|fa|sa>` with no course context, so opening
// them raw hits the same stale-storage trap as the old test links. Resolve to
// the subject hub when the course is known (by id or by slug in the link).
function notifLinkFor(n) {
  const raw = n.link || '';
  const m = raw.match(/^\/?assignments\/test\/([^/?#]+)(?:\/([^/?#]+))?/i);
  const type = (m?.[2] || m?.[1] || '').toLowerCase();
  const isTest = ['eol', 'fa', 'sa'].includes(type);
  let course = (n.courseId && D.courses.find(c => c.id === n.courseId))
    || (n.course_id && D.courses.find(c => c.id === n.course_id));
  if (!course && m?.[1] && !['eol', 'fa', 'sa'].includes(m[1].toLowerCase())) {
    const slug = m[1].toLowerCase();
    course = D.courses.find(c => slugify(c.title) === slug);
  }
  if (!course && n.subject) course = courseFor(n.subject);
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
  // filter by localStorage-selected course instead, so a direct
  // /assignments/test/eol?subject=&course_id= link shows 0 tests whenever
  // storage holds another subject (verified live). Link to the subject hub
  // instead — it reads ?courseId=&classId= from the URL, repairs storage,
  // and is one click from the EOL/FA/SA lists.
  if (course?.id) return lmsUrl(`/assignments${qs}`);
  // Unknown subject: fall back to the test hub, keeping ?subject= for the
  // client-side subject filter (works when the server returns the full list).
  const s = (subject && subject.toLowerCase() !== 'general') ? subject : '';
  return lmsUrl(s ? `/assignments/test/${kind}?subject=${encodeURIComponent(s)}` : `/assignments/test/${kind}`);
}
const extLink = (href, label, cls = 'btn ghost') =>
  `<a class="${cls} ext" href="${esc(href)}" target="_blank" rel="noopener">${label} ${icon('external', 13)}</a>`;
function actionFor(a) {
  if (a.state === 'done') return extLink(a.link, 'View');
  if (a.type === 'eol') return extLink(a.link, a.state === 'late' ? 'Open' : 'Take test', a.state === 'late' ? 'btn ghost' : 'btn');
  return extLink(a.link, a.state === 'late' ? 'Open' : 'Submit', a.state === 'late' ? 'btn ghost' : 'btn');
}

const LOGO = `<svg width="32" height="32" viewBox="0 0 32 32"><rect width="32" height="32" rx="9" fill="#E8A33D"/>
  <path d="M7 11c3-3 6 3 9 0s6 3 9 0M7 16c3-3 6 3 9 0s6 3 9 0M7 21c3-3 6 3 9 0s6 3 9 0" fill="none" stroke="#12302D" stroke-width="2.2" stroke-linecap="round"/></svg>`;

function sidebar(active, activeClass) {
  const open = assignments().filter(a => a.state !== 'done').length;
  const nav = [['home', 'Home', 'index.html', open], ['calendar', 'Planner', 'planner.html'], ['files', 'Library', 'library.html'], ['progress', 'Progress', 'progress.html']];
  return `<nav class="side"><a class="brand" href="index.html">${LOGO}<div>openLMS<small>${esc(D.program)} · ${esc(D.year)}</small></div></a>
    ${nav.map(([i, l, h, n]) => `<a href="${h}" class="nav ${active === i ? 'on' : ''}">${icon(i)}${l}${n ? `<span class="count">${n}</span>` : ''}</a>`).join('')}
    <h5>Classes</h5>
    ${D.courses.map(c => { const s = subj(c.title); return `<a class="cls ${activeClass === s.key ? 'on' : ''}" href="class.html?c=${s.key}" title="${esc(c.title)}"><i style="background:${s.c1}"></i><span>${esc(c.title)}</span></a>`; }).join('')}
    <h5>On Indus LMS</h5>
    ${LMS_PAGES.map(([i, l, p]) => `<a class="cls lmslink" href="${lmsUrl(p)}" target="_blank" rel="noopener">${icon(i, 16)}<span>${l}</span>${icon('external', 12)}</a>`).join('')}
    ${D.live ? `<button class="nav signout" onclick="signOut()">${icon('logout')}Sign out</button>`
      : window.OPENLMS_DEMO ? `<button class="nav signout" onclick="signOut()">${icon('logout')}Exit demo</button>` : ''}
  </nav>`;
}
function topbar(placeholder = 'Search assignments, classes, files…') {
  return `<header class="topbar"><button class="menu-btn" onclick="document.body.classList.toggle('menu-open')" aria-label="Menu">${icon('menu')}</button>
    <label class="search">${icon('search', 16)}<input placeholder="${placeholder}" id="q"></label><div style="flex:1"></div>
    <button class="agenda-btn" id="agenda-btn" onclick="toggleAgenda(true)" aria-haspopup="dialog" aria-controls="agenda">${icon('agenda', 17)}<span>Academic Agenda</span>${outstanding().length ? `<b>${outstanding().length}</b>` : ''}</button>
    <button class="bell" id="bell" onclick="toggleInbox(true)" aria-label="Open inbox" aria-haspopup="dialog" aria-controls="inbox">${icon('bell')}${D.unread ? `<b>${D.unread > 99 ? '99+' : D.unread}</b>` : ''}</button><span class="avatar" title="${esc(D.student)}">${initials(D.student)}</span></header>`;
}
async function signOut() {
  try { window.__lmsClear && window.__lmsClear(); } catch (e) {}
  await fetch('api/logout', { method: 'POST' }).catch(() => {});
  location.replace('login.html');
}
function mountChrome(active, activeClass, placeholder) {
  const boot = document.getElementById('boot'); if (boot) boot.remove();
  const fav = document.createElement('link'); fav.rel = 'icon'; fav.href = 'data:image/svg+xml,' + encodeURIComponent(LOGO.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" '));
  document.head.appendChild(fav);
  document.body.insertAdjacentHTML('afterbegin', sidebar(active, activeClass));
  document.querySelector('.with-side').insertAdjacentHTML('afterbegin', topbar(placeholder));
  document.body.insertAdjacentHTML('beforeend', `<div class="inbox-shade" id="inbox-shade" onclick="closeDrawers()"></div>
    <aside class="inbox agenda" id="agenda" role="dialog" aria-modal="true" aria-labelledby="agenda-title" hidden>
      <header><div><h2 id="agenda-title">Academic Agenda</h2><p class="agenda-sub" id="agenda-sub"></p></div><button class="x" onclick="toggleAgenda(false)" aria-label="Close agenda">×</button></header>
      <div class="agenda-progress"><span id="agenda-bar"></span></div>
      <nav class="inbox-tabs" id="agenda-tabs" role="tablist"></nav>
      <div class="inbox-list" id="agenda-list"></div>
      <footer><p class="agenda-note">Ticks are saved on this device only. Hand in work on Indus LMS.</p></footer>
    </aside>
    <aside class="inbox" id="inbox" role="dialog" aria-modal="true" aria-labelledby="inbox-title" hidden>
      <header><h2 id="inbox-title">Inbox</h2><button class="x" onclick="toggleInbox(false)" aria-label="Close inbox">×</button></header>
      <nav class="inbox-tabs" id="inbox-tabs" role="tablist"></nav>
      <div class="inbox-list" id="inbox-list"></div>
      <footer>${extLink(lmsUrl('/messaging'), 'Messages on Indus LMS', 'btn')}${extLink(lmsUrl('/announcement'), 'All announcements')}</footer>
    </aside>`);
  document.getElementById('inbox-tabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) renderInbox(b.dataset.tab); };
  document.getElementById('agenda-tabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) renderAgenda(b.dataset.tab); };
  document.getElementById('agenda-list').onchange = e => {
    const box = e.target.closest('input[data-key]'); if (!box) return;
    const done = ticked(); box.checked ? done.add(box.dataset.key) : done.delete(box.dataset.key);
    saveTicked(done); renderAgenda(agendaTab);
  };
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawers(); });
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
    at: a.at, href: lmsUrl('/announcement'),
  }));
  const upd = D.notifications.map(n => ({
    kind: 'upd', icon: /fa|sa|eol|test|assess/.test(n.type || '') ? 'tasks' : 'bell', title: n.title, text: n.message, by: n.actor,
    at: n.at, unread: !n.read, href: lmsUrl(n.link || '/notification'),
  }));
  const msg = (D.threads || []).map(t => ({
    kind: 'msg', title: t.name, role: t.role, text: t.last, at: t.at, href: lmsUrl('/messaging'),
  }));
  return { ann, upd, msg, all: [...ann, ...upd, ...msg].sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0)) };
}
function renderInbox(tab = 'all') {
  const items = inboxItems();
  const tabs = [['all', 'All'], ['ann', 'Announcements'], ['upd', 'Updates'], ['msg', 'Messages']];
  document.getElementById('inbox-tabs').innerHTML = tabs.map(([k, l]) =>
    `<button role="tab" data-tab="${k}" aria-selected="${tab === k}" class="${tab === k ? 'on' : ''}">${l}<span>${items[k].length}</span></button>`).join('');
  const row = x => `<a class="inbox-item ${x.unread ? 'unread' : ''}" href="${esc(x.href)}" target="_blank" rel="noopener">
      ${x.kind === 'msg' ? `<span class="avatar">${initials(x.title)}</span>` : `<span class="inbox-ic ${x.kind}">${icon(x.icon, 16)}</span>`}
      <div><b>${esc(x.title)}${x.role ? ` <span class="pill grey">${esc(titleCase(String(x.role).toLowerCase()))}</span>` : ''}</b>
      ${x.text ? `<p>${esc(x.text)}</p>` : ''}<small>${x.kind === 'msg' ? 'Message' : esc(x.by || '')}${x.at ? ' · ' + ago(x.at) : ''}</small></div></a>`;
  const empty = { all: 'Nothing new.', ann: 'No announcements.', upd: 'No updates.', msg: 'No messages yet. Start a chat with a teacher on Indus LMS.' };
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
  const m = Math.round((TODAY - new Date(d)) / 60000);
  if (m < 60) return `${Math.max(m, 1)}m ago`;
  if (m < 1440) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}
const daysUntil = d => Math.ceil((new Date(d) - TODAY) / 86400000);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
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
    type: 'eol', kind: 'Lesson check', title: e.topic && e.topic !== e.title ? `${e.title} · ${e.topic}` : e.title, subject: e.subject,
    status: e.status, due: has(e.due) ? e.due : null, opens: e.opens, assigned: e.assigned, submitted: has(e.submitted) ? e.submitted : null,
    score: e.score, total: e.total, teacher: e.teacher, scheduled: e.availability === 'scheduled', testId: has(e.testId) ? e.testId : null,
  }));
  const tests = D.assessments.map(a => ({
    type: (a.type || 'fa').toLowerCase() === 'sa' ? 'sa' : 'fa', kind: [a.type, a.category].filter(has).join(' · ') || 'Task', title: a.title, subject: a.subject,
    status: a.status, due: has(a.due) ? a.due : null, assigned: a.assigned, submitted: has(a.submitted) ? a.submitted : null,
    score: a.marks, total: a.total, teacher: a.teacher,
  }));
  const learning = (D.tasks || []).map(t => ({
    type: 'task', kind: 'Learning task', title: t.title, subject: t.subject, status: t.status,
    due: has(t.due) ? t.due : null, assigned: t.assigned, submitted: has(t.submitted) ? t.submitted : null, teacher: t.teacher,
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
