/* ============================================================
   HALO AURORA · Interaction script
   Drop in AFTER Bootstrap bundle. Vanilla JS, no dependencies.
   Wires:
     · Theme toggle (data-bs-theme attr on <html>) + localStorage
     · Language toggle (EN ↔ தமிழ்) — swaps [data-en] / [data-ta] text
     · Tool grid filter chips
     · CPR timeframe chips
     · Renders any .spark element from a comma-separated data-points string
   ============================================================ */
(function () {
  'use strict';

  const root = document.documentElement;
  const LS_THEME = 'halo-theme';
  const LS_LANG  = 'halo-lang';

  // ── Theme ────────────────────────────────────────────────────
  // Light theme disabled — pending redesign. Always dark.
  function setTheme(mode) {
    root.setAttribute('data-bs-theme', mode);
    try { localStorage.setItem(LS_THEME, mode); } catch (_) {}
    document.querySelectorAll('[data-theme-toggle]').forEach(btn => {
      btn.style.display = 'none';
    });
  }
  try { localStorage.removeItem(LS_THEME); } catch (_) {}
  setTheme('dark');

  // ── Language ─────────────────────────────────────────────────
  function setLang(lang) {
    root.setAttribute('lang', lang);
    try { localStorage.setItem(LS_LANG, lang); } catch (_) {}

    // Swap text on any element that carries both translations
    document.querySelectorAll('[data-en]').forEach(el => {
      const text = lang === 'ta' && el.dataset.ta !== undefined ? el.dataset.ta : el.dataset.en;
      // preserve children with data-keep
      const keepers = Array.from(el.querySelectorAll('[data-keep]'));
      el.textContent = text;
      keepers.forEach(k => el.appendChild(k));
    });

    // Update toggle button state
    document.querySelectorAll('.lang-toggle button').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.lang === lang);
    });
  }
  const savedLang = (() => { try { return localStorage.getItem(LS_LANG); } catch (_) { return null; } })();
  setLang(savedLang || root.getAttribute('lang') || 'en');

  document.addEventListener('click', e => {
    const btn = e.target.closest('.lang-toggle button');
    if (!btn) return;
    setLang(btn.dataset.lang);
  });

  // ── Generic segmented chip groups (.filter-bar, .cpr-tf) ────
  document.addEventListener('click', e => {
    const chip = e.target.closest('.filter-bar button, .cpr-tf span');
    if (!chip) return;
    const group = chip.parentElement;
    group.querySelectorAll('.is-active').forEach(x => x.classList.remove('is-active'));
    chip.classList.add('is-active');
  });

  // ── Sparkline renderer ──────────────────────────────────────
  // Usage: <svg class="spark" data-points="0.4,0.5,0.6,…" data-color="#34d399"></svg>
  function renderSparks() {
    document.querySelectorAll('svg.spark[data-points]').forEach(svg => {
      const pts = svg.dataset.points.split(',').map(parseFloat).filter(v => !isNaN(v));
      if (!pts.length) return;
      const color = svg.dataset.color || 'var(--tz-accent-1)';
      const w = svg.clientWidth || 260;
      const h = svg.clientHeight || 36;
      const stepX = w / (pts.length - 1);
      const coords = pts.map((v, i) => [i * stepX, h - v * (h - 4) - 2]);
      const lineD = coords.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
      const fillD = `${lineD} L${w} ${h} L0 ${h} Z`;
      const gid = 'sg-' + Math.random().toString(36).slice(2, 8);
      svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
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
  window.addEventListener('resize', () => {
    clearTimeout(window.__sparkTO);
    window.__sparkTO = setTimeout(renderSparks, 120);
  });

})();
