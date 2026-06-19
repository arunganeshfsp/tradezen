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

## Known Caveats

- `halo-tokens.css` and `theme.css` define overlapping CSS variables. On migrated pages, only include `halo-tokens.css` — not both.
- `halo-aurora.js` must load **after** the DOM — place at end of `<body>` or with `defer`.
- The `data-lang` / `data-en` / `data-ta` system only swaps `textContent` — child elements (icons, spans) are preserved via a `keepers` array inside `setLang()`. Safe for mixed text+icon elements.
- `window.onLangChange` is a single callback slot — only one page-level handler at a time.
