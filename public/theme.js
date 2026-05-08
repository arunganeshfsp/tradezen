(function () {
  var t = localStorage.getItem('tz_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);

  window.toggleTheme = function () {
    var cur  = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tz_theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };

  // Inject SVG favicon on every page
  if (!document.querySelector('link[rel~="icon"]')) {
    var lnk = document.createElement('link');
    lnk.rel  = 'icon';
    lnk.type = 'image/svg+xml';
    lnk.href = '/favicon.svg';
    document.head.appendChild(lnk);
  }
})();
