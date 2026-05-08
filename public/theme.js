(function () {
  // ── Theme ──────────────────────────────────────────────────────────────
  var _theme = localStorage.getItem('tz_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', _theme);

  window.toggleTheme = function () {
    var cur  = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tz_theme', next);
    document.documentElement.setAttribute('data-theme', next);
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
    var lnk = document.createElement('link');
    lnk.rel  = 'icon';
    lnk.type = 'image/png';
    lnk.href = '/favicon.png';
    document.head.appendChild(lnk);
  }

  // ── Inject lang button + apply lang on DOMContentLoaded ────────────────
  document.addEventListener('DOMContentLoaded', function () {
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
