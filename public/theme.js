(function () {
  document.documentElement.setAttribute('data-theme', 'dark');
  window.toggleTheme = function () {};

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

  // ── Auth nav ───────────────────────────────────────────────────────────
  function _tzEsc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  window.tzSignOut = function () {
    try { localStorage.removeItem('tz_learn_token'); localStorage.removeItem('tz_learn_user'); } catch (_) {}
    window.location.href = '/learn/auth.html';
  };

  function _renderAuthBtn(slot) {
    var token = null, user = null;
    try { token = localStorage.getItem('tz_learn_token'); } catch (_) {}
    try { user  = JSON.parse(localStorage.getItem('tz_learn_user') || 'null'); } catch (_) {}

    var base = 'font-family:JetBrains Mono,monospace;font-size:10px;letter-spacing:.1em;';
    if (token && user) {
      var name = _tzEsc((user.display_name || user.email || 'Account').split(' ')[0]);
      slot.innerHTML =
        '<span style="' + base + 'color:var(--dim);display:flex;align-items:center;gap:6px">' +
          '<span>👤 ' + name + '</span>' +
          '<button onclick="tzSignOut()" style="' + base + 'color:var(--dim);background:none;border:1px solid var(--border);border-radius:6px;padding:3px 8px;cursor:pointer">Sign Out</button>' +
        '</span>';
    } else {
      slot.innerHTML =
        '<a href="/learn/auth.html" style="' + base + 'color:var(--dim);text-decoration:none;border:1px solid var(--border);border-radius:6px;padding:3px 10px;white-space:nowrap">Sign In</a>';
    }
  }

  // ── Inject lang button + apply lang on DOMContentLoaded ────────────────
  document.addEventListener('DOMContentLoaded', function () {
    var themeBtn = document.getElementById('themeToggle');
    if (themeBtn) themeBtn.style.display = 'none';
    var navR = document.querySelector('.nav-r');
    if (navR) {
      if (!document.getElementById('langToggle')) {
        var btn = document.createElement('button');
        btn.id          = 'langToggle';
        btn.title       = 'Switch language / மொழி மாற்று';
        btn.textContent = _lang === 'ta' ? 'EN' : 'தமிழ்';
        btn.onclick     = window.toggleLang;
        navR.insertBefore(btn, navR.firstChild);
      }
      if (!document.getElementById('tz-auth-btn')) {
        var slot = document.createElement('span');
        slot.id = 'tz-auth-btn';
        slot.style.cssText = 'display:flex;align-items:center;margin-right:6px';
        navR.insertBefore(slot, navR.firstChild);
        _renderAuthBtn(slot);
      }
    }
    if (_lang === 'ta') _applyLang();
  });
})();
