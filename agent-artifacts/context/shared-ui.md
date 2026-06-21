# Context: shared-ui

**Files:** `public/css/halo-tokens.css`, `public/css/halo-aurora.css`, `public/css/light-theme.css`, `public/halo-aurora.js`, `public/theme.js`, `public/theme.css`, `public/tradezen.css`  
**Last updated:** 2026-06-19

---

## Design System — Two Generations

### Current (halo-aurora) — use for all new/updated pages

| File | Purpose |
|---|---|
| `css/halo-tokens.css` | CSS custom properties — all colours, radius, shadows, spacing |
| `css/halo-aurora.css` | Component styles — `.halo-navbar`, `.btn-aurora`, `.lang-toggle`, cards, badges |
| `halo-aurora.js` | Runtime — theme toggle, language toggle (EN/தமிழ்), sparklines |

### Legacy (theme) — do not expand, migrate when touching a page

| File | Purpose |
|---|---|
| `theme.js` | Old theme toggle — `window.toggleTheme()` |
| `theme.css` | Old CSS variables — duplicates halo-tokens |
| `tradezen.css` | Old base layout — used by legacy pages |

---

## Theme System (halo-aurora.js)

- Stored in `localStorage['halo-theme']` → `'dark'` \| `'light'`
- Applied as `data-bs-theme` attribute on `<html>`
- Button: any element with `[data-theme-toggle]` attribute triggers toggle
- SVG icons: `[data-icon="dark"]` / `[data-icon="light"]` — swapped on toggle
- Backward compat: `window.toggleTheme()` shim for legacy pages

---

## Language Toggle (halo-aurora.js)

- Stored in `localStorage['halo-lang']` and `localStorage['tz_lang']` (old key kept in sync)
- Applied as `lang` and `data-lang` attributes on `<html>`
- Button: `.lang-toggle button[data-lang]` — click sets that lang
- **Halo style**: elements with `data-en="English text" data-ta="தமிழ் text"` — JS swaps `.textContent`
- **Legacy style**: elements with only `data-ta` — JS swaps `.innerHTML` (raw HTML swap)
- Hook: `window.onLangChange(lang)` — pages can register a callback for dynamic content
- Backward compat: `window.toggleLang()` for pages using `onclick="toggleLang()"`

---

## Sparklines (halo-aurora.js)

Any `<svg class="spark" data-points="10,20,15,30">` is auto-rendered as a polyline. Runs on `DOMContentLoaded` and `resize`.

---

## Nav Pattern (halo-aurora)

Every new page must include:
```html
<link rel="stylesheet" href="css/halo-tokens.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
<link rel="stylesheet" href="css/halo-aurora.css">
...
<nav class="halo-navbar">
  <div class="container-fluid d-flex align-items-center justify-content-between px-4">
    <a class="navbar-brand" href="/">...</a>
    <ul class="navbar-nav d-none d-lg-flex flex-row align-items-center mb-0">
      <!-- nav links with class="nav-link" and is-active on current page -->
    </ul>
    <div class="d-flex align-items-center gap-2">
      <div class="lang-toggle" role="group">
        <button type="button" data-lang="en" class="is-active">EN</button>
        <button type="button" data-lang="ta">தமிழ்</button>
      </div>
      <button type="button" class="btn-icon" data-theme-toggle aria-label="Toggle theme">
        <!-- dark/light SVG icons -->
      </button>
      <a href="/" class="btn btn-aurora btn-sm">Home</a>
    </div>
  </div>
</nav>
<script src="halo-aurora.js"></script>
```

---

## Shared Light Theme (`css/light-theme.css`)

For **old pages** using the `--bg/--accent` private variable system (not `--tz-*` tokens), a shared light-mode baseline is in `css/light-theme.css`. It provides:
- CSS variable overrides (`--bg`, `--border`, `--accent`, `--text`, `--green`, `--red`, etc.)
- Nav + footer overrides (same markup across all pages)
- Inline `color:#fff` safety guard for JS-generated HTML

**How to add light mode to an old page:**
1. Add `<link rel="stylesheet" href="/css/light-theme.css">` in `<head>`.
2. Delete (or skip writing) the variable block and nav/footer sections from the page's own `:root[data-theme="light"]` block.
3. Keep page-specific component overrides (chips, modals, tables) in the page's own `<style>`.
4. For JS-set inline styles, use `!important` on the specific element IDs.

Currently applied to: `trade_flow.html` (POC).

---

## Migration Rule

When touching a legacy page (uses `theme.js` + `theme.css`): migrate the nav to `halo-navbar` pattern but do not change the rest of the page unless it's part of the task. Half-migrated pages are acceptable.

---

## Symbol Autocomplete Pattern

A **reusable NSE symbol autocomplete** already exists — do not reinvent it.

### Where it lives

| Page | Input ID | Dropdown ID | Pick function |
|---|---|---|---|
| `public/stock_options.html` | `symbolInput` | `symDropdown` | `_pickSym(s)` → calls `loadExpiries()` |
| `public/cup_handle.html` | `symInput` | `chSymDropdown` | `_chPickSym(s)` → fills input only |

### How to add to a new page

**1. HTML** — wrap the input in `.sym-wrap`, add `.sym-dropdown` sibling:
```html
<div class="sym-wrap">
  <input id="myInput" autocomplete="off"
         oninput="_mySymInput(event)" onkeydown="_mySymKeydown(event)">
  <div class="sym-dropdown" id="myDropdown"></div>
</div>
```

**2. CSS** — paste once per page (or centralise in a shared CSS file if migrating many pages):
```css
.sym-wrap { position: relative; }
.sym-dropdown { position: absolute; top: calc(100% + 4px); left: 0; min-width: 180px;
  background: var(--bg3); border: 1px solid var(--border2); border-radius: var(--r);
  z-index: 400; max-height: 240px; overflow-y: auto; display: none;
  box-shadow: 0 8px 24px rgba(0,0,0,.5); }
.sym-dropdown.open { display: block; }
.sym-item { padding: 8px 13px; font-family: 'JetBrains Mono',monospace; font-size: 12px;
  color: var(--dim); cursor: pointer; border-bottom: 1px solid var(--border); }
.sym-item:last-child { border: none; }
.sym-item:hover, .sym-item.ac-active { background: rgba(124,106,247,0.12); color: var(--text); }
```
> For halo-aurora pages use `--tz-surface-2`, `--tz-border` instead of `--bg3`, `--border2`.

**3. Symbol list** — reuse `SYMBOLS_FO` from `stock_options.html` (≈100 F&O stocks) or `_CH_SYMBOLS` from `cup_handle.html` (≈250 stocks incl. midcap/smallcap). Copy the relevant list into the new page or extract to a shared `nse-symbols.js` if needed on 3+ pages.

**4. JS** — the three functions (prefix them uniquely per page to avoid collisions):
```js
let _myAcIdx = -1;
function _mySymInput(e) {
  const q = (e.target.value || '').toUpperCase().trim();
  const dd = document.getElementById('myDropdown');
  if (!q) { dd.classList.remove('open'); return; }
  const matches = MY_SYMBOLS.filter(s => s.startsWith(q)).slice(0, 10);
  if (!matches.length) { dd.classList.remove('open'); return; }
  dd.innerHTML = matches.map(s =>
    `<div class="sym-item" data-val="${s}" onmousedown="event.preventDefault();_myPickSym('${s}')">${s}</div>`
  ).join('');
  dd.classList.add('open'); _myAcIdx = -1;
}
function _mySymKeydown(e) {
  const dd = document.getElementById('myDropdown');
  const items = dd.querySelectorAll('.sym-item');
  if (!items.length) return;
  if (e.key === 'ArrowDown')  { e.preventDefault(); _myAcIdx = Math.min(_myAcIdx+1, items.length-1); items.forEach((el,i) => el.classList.toggle('ac-active', i===_myAcIdx)); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); _myAcIdx = Math.max(_myAcIdx-1, 0); items.forEach((el,i) => el.classList.toggle('ac-active', i===_myAcIdx)); }
  else if (e.key === 'Enter' && _myAcIdx >= 0) { e.preventDefault(); _myPickSym(items[_myAcIdx].dataset.val); }
  else if (e.key === 'Escape') { dd.classList.remove('open'); }
}
function _myPickSym(s) {
  document.getElementById('myInput').value = s;
  document.getElementById('myDropdown').classList.remove('open');
  // call whatever function loads data for the chosen symbol here
}
document.addEventListener('click', e => {
  if (!e.target.closest('.sym-wrap')) document.getElementById('myDropdown').classList.remove('open');
});
```

**5. Enter-key guard** — if the input also fires a load on Enter, add `e.preventDefault()` inside `_mySymKeydown` when a dropdown item is selected (already done in cup_handle.html) so it doesn't double-fire.

### Key behaviours
- Filters by **symbol prefix** only (startsWith) — keeps it fast and predictable
- Max 10 results shown
- Arrow ↑↓ to navigate, Enter to pick, Escape to dismiss
- `onmousedown` + `preventDefault()` on items prevents the input losing focus before the click registers

---

## Known Caveats

- `halo-tokens.css` and `theme.css` define overlapping CSS variables. On migrated pages, only include `halo-tokens.css` — not both.
- `halo-aurora.js` must load **after** the DOM — place at end of `<body>` or with `defer`.
- The `data-lang` / `data-en` / `data-ta` system only swaps `textContent` — child elements (icons, spans) are preserved via a `keepers` array inside `setLang()`. Safe for mixed text+icon elements.
- `window.onLangChange` is a single callback slot — only one page-level handler at a time.
