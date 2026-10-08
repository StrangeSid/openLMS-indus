// SPDX-License-Identifier: GPL-3.0-or-later
// Persistent browser cache for window.LMS (must load BEFORE data.js).
// Server remains source of truth: this is only a stale fallback when
// data.js is missing/slow, and a head-start for future SWR renders.
(function () {
  var KEY = 'openlms.cache.v1';
  var MAX_AGE = 24 * 3600 * 1000; // 1 day; server TTLs govern freshness
  var MAX_BYTES = 4 * 1024 * 1024;

  function load() {
    if (window.LMS) return true;
    try {
      var raw = localStorage.getItem(KEY);
      if (!raw) return false;
      var wrap = JSON.parse(raw);
      if (!wrap || !wrap.data || (Date.now() - wrap.saved_at) > MAX_AGE) {
        try { localStorage.removeItem(KEY); } catch (e) {}
        return false;
      }
      window.LMS = wrap.data;
      window.OPENLMS_STALE = true;
      return true;
    } catch (e) { return false; }
  }

  function save(data) {
    try {
      if (!data || data.live === false) return;
      if (window.OPENLMS_DEMO) return;
      var raw = JSON.stringify({ saved_at: Date.now(), data: data });
      if (raw.length > MAX_BYTES) return;
      localStorage.setItem(KEY, raw);
    } catch (e) {}
  }

  function clear() {
    try { localStorage.removeItem(KEY); } catch (e) {}
    try { sessionStorage.removeItem(KEY); } catch (e) {}
  }

  window.__lmsLoad = load;
  window.__lmsSave = save;
  window.__lmsClear = clear;
})();
