(function () {
  'use strict';

  var CHAPTERS = [
    { n: 1,  id: 'ta_1',  name: 'Price Action Fundamentals' },
    { n: 2,  id: 'ta_2',  name: 'Candlestick Patterns' },
    { n: 3,  id: 'ta_3',  name: 'Support & Resistance' },
    { n: 4,  id: 'ta_4',  name: 'Volume Analysis' },
    { n: 5,  id: 'ta_5',  name: 'CPR — Central Pivot Range' },
    { n: 6,  id: 'ta_6',  name: 'VWAP in Practice' },
    { n: 7,  id: 'ta_7',  name: 'EMA Strategies' },
    { n: 8,  id: 'ta_8',  name: 'RSI — Reading Momentum' },
    { n: 9,  id: 'ta_9',  name: 'Options Chain Basics' },
    { n: 10, id: 'ta_10', name: 'Psychology & Risk Management' },
  ];

  function getCurrentN() {
    var m = window.location.pathname.match(/learn_ch_ta_(\d+)/);
    return m ? +m[1] : 0;
  }

  function getProgress() {
    try { return JSON.parse(localStorage.getItem('tz_learn') || '{}'); } catch (e) { return {}; }
  }

  function isCollapsedPref() {
    var saved = localStorage.getItem('tz_lsb_collapsed');
    if (saved !== null) return saved === '1';
    return window.innerWidth < 1080;
  }

  // ── Inject CSS immediately (before DOMContentLoaded) ────────────────────────
  var style = document.createElement('style');
  style.textContent = [
    /* layout wrapper */
    '.lsb-wrap{display:flex;align-items:flex-start}',
    '.lsb-main{flex:1;min-width:0;overflow-x:hidden}',

    /* sidebar panel */
    '.lsb-sb{width:224px;min-width:224px;position:sticky;top:100px;',
    'max-height:calc(100vh - 100px);overflow-y:auto;overflow-x:hidden;',
    'background:var(--bg1);border-right:1px solid var(--border);',
    'display:flex;flex-direction:column;flex-shrink:0;',
    'transition:width .2s ease,min-width .2s ease;scrollbar-width:thin}',

    '.lsb-sb.lsb-col{width:52px;min-width:52px}',

    /* header */
    '.lsb-hdr{display:flex;align-items:center;justify-content:space-between;',
    'padding:12px 12px 10px;border-bottom:1px solid var(--border);flex-shrink:0}',
    '.lsb-label{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;',
    'color:var(--muted);white-space:nowrap;overflow:hidden;opacity:1;transition:opacity .15s}',
    '.lsb-col .lsb-label{opacity:0;pointer-events:none}',

    /* toggle button */
    '.lsb-tog{background:none;border:none;cursor:pointer;color:var(--dim);padding:4px;',
    'border-radius:4px;display:flex;align-items:center;justify-content:center;flex-shrink:0;',
    'transition:color .15s,background .15s}',
    '.lsb-tog:hover{color:var(--text);background:var(--bg3)}',
    '.lsb-tog svg{display:block;transition:transform .2s ease}',
    '.lsb-col .lsb-tog svg{transform:rotate(180deg)}',

    /* chapter list */
    '.lsb-list{flex:1;overflow-y:auto;overflow-x:hidden;padding:6px 0;scrollbar-width:thin}',
    '.lsb-ch{display:flex;align-items:center;gap:9px;padding:7px 12px;text-decoration:none;',
    'color:var(--dim);font-size:12.5px;font-weight:450;line-height:1.3;min-height:36px;',
    'position:relative;transition:background .1s,color .1s;white-space:nowrap;overflow:hidden}',
    '.lsb-ch:hover{background:var(--bg2);color:var(--text)}',
    '.lsb-ch.lsb-cur{color:var(--accent);font-weight:600;background:rgba(124,106,247,.07)}',
    '.lsb-ch.lsb-cur::after{content:"";position:absolute;right:0;top:5px;bottom:5px;',
    'width:2px;background:var(--accent);border-radius:2px 0 0 2px}',
    '.lsb-ch.lsb-done{color:var(--green)}',

    /* badge circle */
    '.lsb-badge{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;',
    'justify-content:center;font-size:10px;font-weight:700;font-family:"JetBrains Mono",monospace;',
    'flex-shrink:0;background:var(--bg3);color:var(--muted);transition:background .15s,color .15s}',
    '.lsb-ch.lsb-cur  .lsb-badge{background:var(--accent);color:#fff}',
    '.lsb-ch.lsb-done .lsb-badge{background:var(--green-bg);color:var(--green)}',

    /* chapter name */
    '.lsb-cname{overflow:hidden;text-overflow:ellipsis;flex:1;transition:opacity .15s}',
    '.lsb-col .lsb-cname{opacity:0;width:0;overflow:hidden}',

    /* footer */
    '.lsb-foot{padding:9px 12px;border-top:1px solid var(--border);flex-shrink:0;transition:opacity .15s}',
    '.lsb-col .lsb-foot{opacity:0;pointer-events:none}',
    '.lsb-ftext{font-size:11px;color:var(--muted);white-space:nowrap}',
    '.lsb-bar{height:3px;background:var(--bg3);border-radius:3px;margin-top:5px;overflow:hidden}',
    '.lsb-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--green));',
    'border-radius:3px;transition:width .3s ease}',

    /* mobile: hide sidebar, keep content full width */
    '@media(max-width:768px){.lsb-wrap{display:block}.lsb-sb{display:none}}'
  ].join('');
  document.head.appendChild(style);

  // ── Build and inject sidebar on DOMContentLoaded ─────────────────────────────
  function init() {
    var curN     = getCurrentN();
    var p        = getProgress();
    var done     = p.chapters_done || [];
    var doneCount= CHAPTERS.filter(function(c){ return done.indexOf(c.id) > -1; }).length;
    var pct      = Math.round(doneCount / CHAPTERS.length * 100);
    var collapsed= isCollapsedPref();

    // Build sidebar element
    var sb = document.createElement('div');
    sb.className = 'lsb-sb' + (collapsed ? ' lsb-col' : '');
    sb.id = 'lsbPanel';

    var chevronSVG = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
      '<path d="M9 2L4 7L9 12" stroke="currentColor" stroke-width="1.6" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';

    var items = CHAPTERS.map(function (ch) {
      var isDone = done.indexOf(ch.id) > -1;
      var isCur  = ch.n === curN;
      var cls    = isCur ? ' lsb-cur' : isDone ? ' lsb-done' : '';
      var badge  = isDone ? '✓' : ch.n;
      return '<a href="/learn_ch_ta_' + ch.n + '.html" class="lsb-ch' + cls + '" ' +
        'title="Ch ' + ch.n + ': ' + ch.name + '">' +
        '<span class="lsb-badge">' + badge + '</span>' +
        '<span class="lsb-cname">Ch ' + ch.n + '. ' + ch.name + '</span>' +
        '</a>';
    }).join('');

    sb.innerHTML =
      '<div class="lsb-hdr">' +
        '<span class="lsb-label">TA Course</span>' +
        '<button class="lsb-tog" id="lsbTog" title="Toggle sidebar">' + chevronSVG + '</button>' +
      '</div>' +
      '<div class="lsb-list">' + items + '</div>' +
      '<div class="lsb-foot">' +
        '<div class="lsb-ftext">' + doneCount + ' / ' + CHAPTERS.length + ' complete</div>' +
        '<div class="lsb-bar"><div class="lsb-fill" style="width:' + pct + '%"></div></div>' +
      '</div>';

    // Restructure DOM: wrap everything after .ch-bar in flex layout
    var chBar = document.querySelector('.ch-bar');
    if (!chBar) return;

    var wrap = document.createElement('div');
    wrap.className = 'lsb-wrap';

    var main = document.createElement('div');
    main.className = 'lsb-main';

    var toMove = [];
    var node = chBar.nextElementSibling;
    while (node) { toMove.push(node); node = node.nextElementSibling; }
    toMove.forEach(function (el) { main.appendChild(el); });

    wrap.appendChild(sb);
    wrap.appendChild(main);
    chBar.insertAdjacentElement('afterend', wrap);

    // Toggle collapse
    document.getElementById('lsbTog').addEventListener('click', function () {
      var panel = document.getElementById('lsbPanel');
      var nowCol = panel.classList.toggle('lsb-col');
      localStorage.setItem('tz_lsb_collapsed', nowCol ? '1' : '0');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
