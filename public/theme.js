(function () {
  // ── Theme ──────────────────────────────────────────────────────────────
  var _theme = localStorage.getItem('tz_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', _theme);

  function _applyIconTheme(mode) {
    document.querySelectorAll('[data-app-logo]').forEach(function (img) {
      img.src = mode === 'light' ? '/favicon-light.svg' : '/favicon.svg';
    });
  }

  window.toggleTheme = function () {
    var cur  = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tz_theme', next);
    document.documentElement.setAttribute('data-theme', next);
    _applyIconTheme(next);
  };

  // ── Language ───────────────────────────────────────────────────────────
  var _lang = localStorage.getItem('tz_lang') || 'en';
  document.documentElement.setAttribute('data-lang', _lang);

  function _applyLang() {
    document.querySelectorAll('[data-ta]').forEach(function (el) {
      if (_lang === 'ta') {
        if (!el.dataset.en) el.dataset.en = el.innerHTML;
        el.innerHTML = el.dataset.ta;
      } else {
        if (el.dataset.en) el.innerHTML = el.dataset.en;
      }
    });
  }

  window.toggleLang = function () {
    _lang = _lang === 'ta' ? 'en' : 'ta';
    localStorage.setItem('tz_lang', _lang);
    document.documentElement.setAttribute('data-lang', _lang);
    _applyLang();
    var btn = document.getElementById('langToggle');
    if (btn) btn.textContent = _lang === 'ta' ? 'EN' : 'தமிழ்';
    if (typeof window.onLangChange === 'function') window.onLangChange(_lang);
  };

  // ── Favicon ────────────────────────────────────────────────────────────
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

  // ── Inject lang button + apply lang on DOMContentLoaded ────────────────
  document.addEventListener('DOMContentLoaded', function () {
    _applyIconTheme(_theme);
    var navR = document.querySelector('.nav-r');
    if (navR && !document.getElementById('langToggle')) {
      var btn = document.createElement('button');
      btn.id          = 'langToggle';
      btn.title       = 'Switch language / மொழி மாற்று';
      btn.textContent = _lang === 'ta' ? 'EN' : 'தமிழ்';
      btn.onclick     = window.toggleLang;
      navR.insertBefore(btn, navR.firstChild);
    }
    if (_lang === 'ta') _applyLang();
  });
})();
