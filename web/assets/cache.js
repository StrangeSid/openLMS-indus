// SPDX-License-Identifier: GPL-3.0-or-later
// Saved copy of window.LMS (must load BEFORE data.js).
//
// Stale-while-revalidate: reopening openLMS after closing the tab used to
// wait for the server to rebuild every section (seconds when the 5-minute
// cache had expired). Now __lmsBoot() renders the last copy at once and
// app.js revalidates it in the background with If-None-Match, so the
// network is never on the critical path of a repeat visit. With no copy,
// data.js loads as before. The server stays the source of truth; the copy
// is cleared on sign-out and ignored after a day.
(function () {
  var KEY = 'openlms.cache.v1';
  var MAX_AGE = 24 * 3600 * 1000;
  var MAX_BYTES = 4 * 1024 * 1024;

  function read() {
    try {
      var wrap = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!wrap || !wrap.data || (Date.now() - wrap.saved_at) > MAX_AGE) {
        if (wrap) localStorage.removeItem(KEY);
        return null;
      }
      return wrap;
    } catch (e) { return null; }
  }

  function load() {
    if (window.LMS) return true;
    var wrap = read();
    if (!wrap) return false;
    window.LMS = wrap.data;
    window.OPENLMS_STALE = true;
    return true;
  }

  function save(data, etag) {
    try {
      if (!data || data.live !== true) return; // never demo or offline exports
      if (window.OPENLMS_DEMO) return;
      var raw = JSON.stringify({ saved_at: Date.now(), etag: etag || null, data: data });
      if (raw.length > MAX_BYTES) return;
      localStorage.setItem(KEY, raw);
    } catch (e) {}
  }

  function etag() {
    if (window.LMS_ETAG && !window.OPENLMS_SWR) return window.LMS_ETAG;
    var wrap = read();
    return wrap && wrap.etag;
  }

  function clear() {
    try { localStorage.removeItem(KEY); } catch (e) {}
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  }

  // Called inline where pages used to have <script src="data.js">.
  function boot() {
    if (window.LMS) return;
    if (load()) { window.OPENLMS_SWR = true; return; }
    document.write('<script src="data.js"><\/script>');
  }

  window.__lmsLoad = load;
  window.__lmsSave = save;
  window.__lmsEtag = etag;
  window.__lmsClear = clear;
  window.__lmsBoot = boot;
})();

// Boot skeleton: kills the page-switch flicker. The real sidebar/topbar
// are injected by mountChrome() only after data.js + app.js run, leaving an
// empty 248px gutter and a missing topbar on first paint. This runs
// synchronously before data.js and paints neutral shells with identical
// geometry (.side 248px fixed, .topbar 58px sticky, same <=860px rules),
// so swapping in the real chrome causes no layout shift. mountChrome()
// removes #boot first thing.
(function () {
  try {
    if (!document.querySelector('.with-side') || document.querySelector('.side')) return;
    var css = '#boot-side{position:fixed;inset:0 auto 0 0;width:248px;background:#12302D;padding:18px 12px;z-index:5}'
      + '#boot-side .b-brand{height:32px;border-radius:8px;background:rgba(255,255,255,.16);margin:2px 8px 18px}'
      + '#boot-side .b-row{height:34px;border-radius:8px;background:rgba(255,255,255,.08);margin:2px 0;animation:bootsh 1.2s ease-in-out infinite}'
      + '#boot-side .b-gap{height:22px}'
      + '#boot-top{height:58px;margin-left:248px;background:#fff;border-bottom:1px solid #E6EAEE;display:flex;align-items:center;padding:0 28px}'
      + '#boot-top .b-search{flex:1;max-width:420px;height:34px;border-radius:8px;background:#F4F6F5;border:1px solid #E6EAEE;animation:bootsh 1.2s ease-in-out infinite}'
      + '@keyframes bootsh{0%,100%{opacity:1}50%{opacity:.55}}'
      + '@media (max-width:860px){#boot-side{transform:translateX(-100%)}#boot-top{margin-left:0;padding:0 16px}}';
    var style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
    var boot = document.createElement('div');
    boot.id = 'boot';
    boot.setAttribute('aria-hidden', 'true');
    boot.innerHTML = '<div id="boot-side"><div class="b-brand"></div>'
      + '<div class="b-row"></div><div class="b-row"></div><div class="b-row"></div><div class="b-row"></div>'
      + '<div class="b-gap"></div>'
      + '<div class="b-row"></div><div class="b-row"></div><div class="b-row"></div><div class="b-row"></div></div>'
      + '<div id="boot-top"><div class="b-search"></div></div>';
    document.body.insertAdjacentElement('afterbegin', boot);
  } catch (e) {}
})();
