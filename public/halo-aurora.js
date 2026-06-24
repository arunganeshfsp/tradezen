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

  // ── Theme — light theme disabled pending redesign, always dark ──────────
  function setTheme(mode) {
    root.setAttribute('data-bs-theme', mode);
    root.setAttribute('data-theme', mode);
    try { localStorage.removeItem(LS_THEME); localStorage.removeItem('tz_theme'); } catch (_) {}
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.style.display = 'none';
    });
    document.querySelectorAll('[data-app-logo]').forEach(function (img) {
      img.src = '/favicon.svg';
    });
  }
  setTheme('dark');

  // No-op — light theme disabled pending redesign.
  window.toggleTheme = function () {};

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

  // ── Auth nav ─────────────────────────────────────────────────
  function _tzEsc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  window.tzSignOut = function () {
    try { localStorage.removeItem('tz_learn_token'); localStorage.removeItem('tz_learn_user'); } catch (_) {}
    window.location.href = '/learn/auth.html';
  };

  // ── Compact profile icon (signed in = initial circle, signed out = person icon) ──
  function _renderHaloAuthBtn() {
    var existing = document.getElementById('tz-auth-btn');
    if (existing) existing.remove();

    var token = null, user = null;
    try { token = localStorage.getItem('tz_learn_token'); } catch (_) {}
    try { user  = JSON.parse(localStorage.getItem('tz_learn_user') || 'null'); } catch (_) {}

    var slot = document.createElement('span');
    slot.id = 'tz-auth-btn';

    if (token && user) {
      var initial = _tzEsc((user.display_name || user.email || 'A')[0].toUpperCase());
      var name    = _tzEsc((user.display_name || user.email || 'Account'));
      slot.innerHTML =
        '<button class="tz-profile-btn signed-in" onclick="tzSignOut()" title="' + name + ' — click to sign out">' +
        initial + '</button>';
    } else {
      slot.innerHTML =
        '<a class="tz-profile-btn" href="/learn/auth.html" title="Sign in">' +
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>' +
        '</a>';
    }

    var navActions = document.querySelector('.halo-navbar .d-flex:last-child');
    if (navActions) {
      navActions.appendChild(slot);
    }
  }

  document.addEventListener('DOMContentLoaded', _renderHaloAuthBtn);

  // ── Side drawer navigation ────────────────────────────────────
  var TZ_NAV_PAGES = [
    { icon: '📈', label: 'Trade Flow',    href: '/trade_flow.html' },
    { icon: '📊', label: 'CPR Monitor',   href: '/cpr_monitor.html' },
    { icon: '🔍', label: 'F&O Screener',  href: '/fno_scanner.html' },
    { icon: '⚙️', label: 'Stock Options', href: '/stock_options.html' },
    { icon: '🧠', label: 'Trade Fun',     href: '/market_psychology.html' },
    { icon: '▶️', label: 'Trade Player',  href: '/trade_player.html' },
  ];

  window._tzCloseDrawer = function () {
    var o = document.getElementById('tzDrawerOverlay');
    var d = document.getElementById('tzDrawer');
    if (o) o.classList.remove('open');
    if (d) d.classList.remove('open');
    document.body.style.overflow = '';
  };

  function _tzOpenDrawer() {
    var o = document.getElementById('tzDrawerOverlay');
    var d = document.getElementById('tzDrawer');
    if (o) o.classList.add('open');
    if (d) d.classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function _buildTzDrawer() {
    if (document.getElementById('tzDrawer')) return; // already built

    var curPath = window.location.pathname.replace(/\/$/, '') || '/';

    // Overlay
    var overlay = document.createElement('div');
    overlay.className = 'tz-drawer-overlay';
    overlay.id = 'tzDrawerOverlay';
    overlay.addEventListener('click', window._tzCloseDrawer);

    // Drawer panel
    var drawer = document.createElement('div');
    drawer.className = 'tz-drawer';
    drawer.id = 'tzDrawer';
    drawer.setAttribute('role', 'navigation');
    drawer.setAttribute('aria-label', 'Main menu');

    // Head
    var html = '<div class="tz-drawer-head">' +
      '<a class="tz-drawer-brand" href="/">' +
      '<img src="/app-icon.svg" width="26" height="26" style="border-radius:6px" alt="TradeZen">' +
      'TradeZen</a>' +
      '<button class="tz-drawer-close" onclick="_tzCloseDrawer()" aria-label="Close menu">✕</button>' +
      '</div>';

    // Main tools section
    html += '<nav class="tz-drawer-nav">';
    html += '<div class="tz-drawer-section">';
    html += '<span class="tz-drawer-section-label">Tools</span>';
    TZ_NAV_PAGES.forEach(function (p) {
      var active = curPath === p.href.replace(/\/$/, '');
      html += '<a class="tz-drawer-link' + (active ? ' is-active' : '') + '" href="' + p.href + '">' +
        '<span class="tz-dl-icon">' + p.icon + '</span>' + p.label + '</a>';
    });
    html += '</div>';

    // Learn section
    var learnActive = curPath === '/learn' || curPath.startsWith('/learn/');
    html += '<div class="tz-drawer-section">';
    html += '<span class="tz-drawer-section-label">Learn</span>';
    html += '<a class="tz-drawer-link' + (learnActive ? ' is-active' : '') + '" href="/learn/">' +
      '<span class="tz-dl-icon">📚</span>Learn</a>';
    html += '</div>';
    html += '</nav>';

    // Footer
    html += '<div class="tz-drawer-foot">For educational purposes only. Not investment advice. Consult a SEBI-registered adviser before trading.</div>';

    drawer.innerHTML = html;

    document.body.appendChild(overlay);
    document.body.appendChild(drawer);

    // Close on Escape
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') window._tzCloseDrawer();
    });
  }

  function _renderHaloHamburger() {
    _buildTzDrawer();

    var btn = document.createElement('button');
    btn.className = 'tz-hamburger';
    btn.setAttribute('aria-label', 'Open menu');
    btn.setAttribute('aria-controls', 'tzDrawer');
    btn.innerHTML = '<span></span><span></span><span></span>';
    btn.addEventListener('click', _tzOpenDrawer);

    // Place hamburger at the far left — before the brand
    var brand = document.querySelector('.halo-navbar .navbar-brand');
    var container = brand && brand.parentElement;
    if (container) {
      container.insertBefore(btn, brand);
    }
  }

  document.addEventListener('DOMContentLoaded', _renderHaloHamburger);

  // ── Favicon ───────────────────────────────────────────────────
  if (!document.querySelector('link[rel~="icon"]')) {
    [
      { rel:'icon', type:'image/svg+xml', href:'/favicon.svg',       media:'(prefers-color-scheme: dark)' },
      { rel:'icon', type:'image/svg+xml', href:'/favicon-light.svg', media:'(prefers-color-scheme: light)' },
      { rel:'icon', type:'image/png',     href:'/favicon-32x32.png', sizes:'32x32' },
      { rel:'icon', type:'image/png',     href:'/favicon-16x16.png', sizes:'16x16' },
    ].forEach(function(a) {
      var l = document.createElement('link');
      Object.keys(a).forEach(function(k){ l[k] = a[k]; });
      document.head.appendChild(l);
    });
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
