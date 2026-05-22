/* ============================================================
   TradeZen · halo-aurora.js
   Unified interaction script — replaces theme.js for new pages.
   Wires:
     · Theme toggle (data-bs-theme + legacy data-theme) + localStorage
     · Language toggle (EN ↔ தமிழ்) — data-en / data-ta attributes
     · Legacy window.toggleTheme / window.toggleLang shims
     · Filter-bar + CPR timeframe chip groups
     · Favicon injection if missing
     · Sparkline SVG renderer
   ============================================================ */
(function () {
  'use strict';

  const root     = document.documentElement;
  const LS_THEME = 'halo-theme';
  const LS_LANG  = 'halo-lang';

  // ── Theme ────────────────────────────────────────────────────
  function setTheme(mode) {
    root.setAttribute('data-bs-theme', mode);
    root.setAttribute('data-theme', mode);         // backward compat with theme.css
    try {
      localStorage.setItem(LS_THEME, mode);
      localStorage.setItem('tz_theme', mode);      // keep old key in sync
    } catch (_) {}
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.querySelectorAll('[data-icon]').forEach(function (i) {
        i.style.display = i.dataset.icon === mode ? 'none' : 'inline-flex';
      });
      btn.setAttribute('aria-label', mode === 'dark' ? 'Switch to light' : 'Switch to dark');
    });
  }

  var savedTheme = (function () {
    try { return localStorage.getItem(LS_THEME) || localStorage.getItem('tz_theme'); } catch (_) { return null; }
  })();
  setTheme(savedTheme || 'dark');

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-theme-toggle]');
    if (!btn) return;
    var cur = root.getAttribute('data-bs-theme') || 'dark';
    setTheme(cur === 'dark' ? 'light' : 'dark');
  });

  // Backward compat: pages using onclick="toggleTheme()"
  window.toggleTheme = function () {
    var cur = root.getAttribute('data-bs-theme') || root.getAttribute('data-theme') || 'dark';
    setTheme(cur === 'dark' ? 'light' : 'dark');
  };

  // ── Language ─────────────────────────────────────────────────
  function setLang(lang) {
    root.setAttribute('lang', lang);
    root.setAttribute('data-lang', lang);
    try {
      localStorage.setItem(LS_LANG, lang);
      localStorage.setItem('tz_lang', lang);       // keep old key in sync
    } catch (_) {}

    // Halo Aurora style: elements with data-en (and optionally data-ta)
    document.querySelectorAll('[data-en]').forEach(function (el) {
      var text = lang === 'ta' && el.dataset.ta ? el.dataset.ta : el.dataset.en;
      var keepers = Array.from(el.querySelectorAll('[data-keep]'));
      el.textContent = text;
      keepers.forEach(function (k) { el.appendChild(k); });
    });

    // Legacy style: elements with only data-ta (innerHTML swap)
    document.querySelectorAll('[data-ta]:not([data-en])').forEach(function (el) {
      if (lang === 'ta') {
        if (!el.dataset.enFallback) el.dataset.enFallback = el.innerHTML;
        el.innerHTML = el.dataset.ta;
      } else {
        if (el.dataset.enFallback) el.innerHTML = el.dataset.enFallback;
      }
    });

    document.querySelectorAll('.lang-toggle button').forEach(function (btn) {
      btn.classList.toggle('is-active', btn.dataset.lang === lang);
    });

    var legacyBtn = document.getElementById('langToggle');
    if (legacyBtn) legacyBtn.textContent = lang === 'ta' ? 'EN' : 'தமிழ்';

    if (typeof window.onLangChange === 'function') window.onLangChange(lang);
  }

  var savedLang = (function () {
    try { return localStorage.getItem(LS_LANG) || localStorage.getItem('tz_lang'); } catch (_) { return null; }
  })();

  setLang(savedLang || root.getAttribute('lang') || 'en');

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.lang-toggle button');
    if (!btn) return;
    setLang(btn.dataset.lang);
  });

  // Backward compat: pages using onclick="toggleLang()"
  window.toggleLang = function () {
    var cur = root.getAttribute('lang') || 'en';
    setLang(cur === 'ta' ? 'en' : 'ta');
  };

  // ── Generic segmented chip groups (.filter-bar, .cpr-tf) ────
  document.addEventListener('click', function (e) {
    var chip = e.target.closest('.filter-bar button, .cpr-tf span');
    if (!chip) return;
    var group = chip.parentElement;
    group.querySelectorAll('.is-active').forEach(function (x) { x.classList.remove('is-active'); });
    chip.classList.add('is-active');
  });

  // ── Favicon ───────────────────────────────────────────────────
  if (!document.querySelector('link[rel~="icon"]')) {
    var lnk = document.createElement('link');
    lnk.rel = 'icon'; lnk.type = 'image/png'; lnk.href = '/favicon.png';
    document.head.appendChild(lnk);
  }

  // ── Sparkline renderer ──────────────────────────────────────
  // Usage: <svg class="spark" data-points="0.4,0.5,0.6,…" data-color="#34d399"></svg>
  function renderSparks() {
    document.querySelectorAll('svg.spark[data-points]').forEach(function (svg) {
      var pts = svg.dataset.points.split(',').map(parseFloat).filter(function (v) { return !isNaN(v); });
      if (!pts.length) return;
      var color  = svg.dataset.color || 'var(--tz-accent-1)';
      var w      = svg.clientWidth  || 260;
      var h      = svg.clientHeight || 36;
      var stepX  = w / (pts.length - 1);
      var coords = pts.map(function (v, i) { return [i * stepX, h - v * (h - 4) - 2]; });
      var lineD  = coords.map(function (p, i) {
        return (i === 0 ? 'M' : 'L') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
      }).join(' ');
      var fillD = lineD + ' L' + w + ' ' + h + ' L0 ' + h + ' Z';
      var gid   = 'sg-' + Math.random().toString(36).slice(2, 8);
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      svg.setAttribute('preserveAspectRatio', 'none');
      svg.innerHTML =
        '<defs><linearGradient id="' + gid + '" x1="0" y1="0" x2="0" y2="1">' +
          '<stop offset="0%"   stop-color="' + color + '" stop-opacity="0.22"/>' +
          '<stop offset="100%" stop-color="' + color + '" stop-opacity="0"/>' +
        '</linearGradient></defs>' +
        '<path d="' + fillD + '" fill="url(#' + gid + ')"/>' +
        '<path class="line" d="' + lineD + '" stroke="' + color + '"/>';
    });
  }

  renderSparks();
  window.renderSparks = renderSparks;   // allow pages to retrigger after data-points update

  window.addEventListener('resize', function () {
    clearTimeout(window.__sparkTO);
    window.__sparkTO = setTimeout(renderSparks, 120);
  });

})();
