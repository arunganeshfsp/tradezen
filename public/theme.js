(function () {
  var t = localStorage.getItem('tz_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);

  window.toggleTheme = function () {
    var cur  = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    localStorage.setItem('tz_theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };
})();
