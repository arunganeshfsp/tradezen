/* Stock search via API — autocomplete for all NSE/BSE stocks.
   Fetches from /api/stocks/search?q=<query> with debouncing.
*/

// Debounce helper — delay search while user is still typing
function debounce(fn, delay) {
  let timeout;
  return function(...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  };
}

// Generic autocomplete initializer
function initStockAutocomplete(inputId, acDropdownId, onSelectCallback) {
  const inputEl = document.getElementById(inputId);
  const acEl = document.getElementById(acDropdownId);

  if (!inputEl || !acEl) return;

  // Debounced search function (300ms delay)
  const doSearch = debounce(async (query) => {
    if (query.length < 1) {
      acEl.style.display = 'none';
      return;
    }

    try {
      const resp = await fetch(`/api/stocks/search?q=${encodeURIComponent(query)}&limit=8`);
      const data = await resp.json();
      const results = data.results || [];

      if (results.length === 0) {
        acEl.innerHTML = '<div style="padding:8px;color:var(--muted);font-size:11px">No matches</div>';
        acEl.style.display = 'block';
        return;
      }

      acEl.innerHTML = results.map(s =>
        `<div onclick="selectStockItem('${inputId}', '${acDropdownId}', '${s.code}')" ` +
        `style="padding:8px;cursor:pointer;border-bottom:1px solid var(--border);font-size:12px;transition:background .1s" ` +
        `onmouseover="this.style.background='var(--bg3)'" onmouseout="this.style.background='transparent'">` +
        `<strong>${s.name}</strong> <span style="color:var(--muted);font-size:10px">(${s.code})</span>` +
        `</div>`
      ).join('');
      acEl.style.display = 'block';
    } catch (err) {
      console.error('[Autocomplete] Search failed:', err);
      acEl.innerHTML = '<div style="padding:8px;color:var(--red);font-size:11px">Search error</div>';
      acEl.style.display = 'block';
    }
  }, 300);

  // Listen for input
  inputEl.addEventListener('input', e => {
    const query = e.target.value.trim();
    doSearch(query);
  });

  // Allow Enter to select first result
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      const firstItem = acEl.querySelector('div');
      if (firstItem) firstItem.click();
    }
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', e => {
    if (e.target !== inputEl && !acEl.contains(e.target)) {
      acEl.style.display = 'none';
    }
  });
}

// Called when user selects a stock from dropdown
function selectStockItem(inputId, acDropdownId, code) {
  document.getElementById(inputId).value = code;
  document.getElementById(acDropdownId).style.display = 'none';
  // Dispatch custom event for any listeners
  document.getElementById(inputId).dispatchEvent(new CustomEvent('stock-selected', { detail: { code } }));
}
