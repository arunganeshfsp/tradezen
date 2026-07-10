# De-AI Polish — Make TradeZen's Homepage Visually Ownable

**Status:** planned, not executed
**Created:** 2026-07-10
**Scope:** `public/index.html` + additive utilities in `public/css/halo-aurora.css`

---

## Context

A competitor site (TrueTrendView) looks nearly identical to TradeZen: same near-black navy background, same purple gradient accent (~#7c6af7), same *italic-gradient hero word*, same eyebrow pills, same rounded stat cards. Both follow the default "AI dark SaaS landing page" formula, so TradeZen doesn't stand out.

Approved direction: **De-AI polish** — keep the layout, remove the AI tells, replace them with ownable design signatures. Homepage first; new utilities go into shared `halo-aurora.css` so other pages can adopt the pattern later. No breaking changes to other pages.

**The five AI tells to remove and their replacements:**

| AI tell (current) | Replacement (ownable) |
|---|---|
| Italic gradient-clipped words (6 spots on homepage) | DM Serif Display italic in solid ink — serif/sans contrast is the signature |
| Purple radial glow hero background | Faint chart-grid "graph paper" texture + CPR-line motif (dashed TC/PIVOT/BC rules) |
| Bordered pill eyebrows | Plain mono "kicker" with a thin accent rule line (`─── TOOLS · LIVE`) |
| Gradient button + purple glow shadow on hover | Flat accent button, no glow |
| Radial-gradient hover glows on strategy cards | Chart-axis corner ticks + mono index numerals (01, 02…) |

**What TradeZen has that no lookalike can copy** (lean into these):
- Live data on the homepage (pulse cards, sector chips, movers, news) — competitors' heroes are static marketing copy
- Tamil bilingual identity (தமிழ்/EN toggle) — rare; Tamil script can be a visual signature
- 11 working tools — show the product, don't describe it
- DM Serif Display already loaded in `halo-tokens.css` as `--tz-font-display` but almost unused — zero new font requests needed

---

## Files to Modify

### 1. `public/css/halo-aurora.css` — add new utilities (additive only, nothing removed)

Add after the existing `.text-gradient` block (~line 75):

```css
/* Serif accent — replaces gradient-clip words */
.text-serif {
  font-family: var(--tz-font-display);
  font-weight: 400;
  font-style: italic;
  letter-spacing: -0.01em;
  color: var(--tz-fg-1);
}

/* Kicker — replaces pill eyebrows */
.kicker {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-family: var(--tz-font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--tz-fg-3);
}
.kicker::before {
  content: '';
  width: 28px;
  height: 1px;
  background: var(--tz-accent-1);
}
```

Do NOT remove `.text-gradient` / `.eyebrow` — other pages still use them.

### 2. `public/index.html` — markup + inline CSS changes

**A. Hero (`.title-panel`, CSS ~line 96, HTML ~line 584)**

- `.title-panel` background: replace the purple radial glow with a chart-grid texture:
```css
background:
  repeating-linear-gradient(to right,  rgba(255,255,255,.022) 0 1px, transparent 1px 44px),
  repeating-linear-gradient(to bottom, rgba(255,255,255,.022) 0 1px, transparent 1px 44px);
```
- `.title-panel h1 em`: remove gradient clip; use `font-family: var(--tz-font-display); font-style: italic; font-weight: 400; color: var(--tz-fg-1);` and bump size slightly (`font-size: 1.06em`) since serif renders smaller.
- `.title-panel-eyebrow`: restyle to kicker treatment — drop `background`, `border`, `border-radius`, `padding`; add the accent rule via flanking `::before`/`::after` lines (centered layout).
- Add a **CPR-line motif** under the CTA — a trader-specific signature no generic SaaS page has:
```html
<div class="cpr-motif" aria-hidden="true">
  <span class="cpr-line"><i>TC</i></span>
  <span class="cpr-line cpr-mid"><i>PIVOT</i></span>
  <span class="cpr-line"><i>BC</i></span>
</div>
```
```css
.cpr-motif { max-width: 280px; margin: 28px auto 0; display: flex; flex-direction: column; gap: 7px; opacity: .55; }
.cpr-line { position: relative; border-top: 1px dashed var(--tz-border-strong); }
.cpr-line.cpr-mid { border-top-color: rgba(var(--tz-accent-rgb), .6); }
.cpr-line i { position: absolute; right: -30px; top: -7px; font-family: var(--tz-font-mono); font-style: normal; font-size: 8px; letter-spacing: .1em; color: var(--tz-fg-3); }
```

**B. Replace the 5 `text-gradient fst-italic` spans** (lines ~759, 1064, 1141, 1195, 1266) with `text-serif`:
```html
<span class="text-serif" data-en=" One workspace." …>
```
Keep all `data-en`/`data-ta` attributes untouched (Tamil toggle unaffected).

**C. Section eyebrows** — the `<span class="eyebrow">` instances on the homepage (TOOLS, STRATEGIES, LEARN, FAQ sections): swap class to `kicker`, keep inner SVG/text.

**D. Section `<h2>`s** — set headline font to serif for section titles via one homepage rule:
```css
section .section-header h2, .strat-section h2 { font-family: var(--tz-font-display); font-weight: 400; letter-spacing: -.01em; }
```
(Verify the actual h2 wrapper classes during implementation; apply to the homepage's section headings only.)

**E. Buttons** — homepage override to kill the glow:
```css
.btn-aurora, .btn-aurora:hover, .btn-aurora:focus { box-shadow: none; background: var(--tz-accent-1); }
```

**F. Strategy hero cards (`.strategy-card`, CSS ~line 27)**
- Remove the 5 `::before` radial-gradient glow variants (`.kf-card::before`, `.orca-card::before`, `.osprey-card::before`, `.cup-card::before`, `.rev-card::before`) and the `:hover::before` opacity rule.
- Replace with chart-axis corner ticks on hover:
```css
.strategy-card::before, .strategy-card::after {
  content: ''; position: absolute; width: 14px; height: 14px; opacity: 0;
  transition: opacity .18s var(--tz-ease-out); pointer-events: none;
}
.strategy-card::before { top: 10px; left: 10px; border-top: 1.5px solid var(--tz-accent-1); border-left: 1.5px solid var(--tz-accent-1); }
.strategy-card::after  { bottom: 10px; right: 10px; border-bottom: 1.5px solid var(--tz-accent-1); border-right: 1.5px solid var(--tz-accent-1); }
.strategy-card:hover::before, .strategy-card:hover::after { opacity: .7; }
```
- Add mono index numeral to `.strategy-eyebrow` content where present (e.g., `01 · S1 KINGFISHER`) — text-only change.

**G. Big numbers** — ensure `.pulse-ltp` and trending `.t-ltp` use `font-variant-numeric: tabular-nums` (add if missing).

---

## Explicitly Out of Scope

- No palette change (purple stays for now — full brand refresh was declined)
- No layout restructuring (trading-desk homepage was declined)
- Other pages (`learn_home`, tool pages) — they adopt `.text-serif`/`.kicker` later, page by page
- `halo-tokens.css` — untouched

---

## Verification (when executed)

1. Open `http://localhost:3000/` — hero shows serif italic "market-grade tools." in solid ivory, no gradient text anywhere on the page.
2. Hero background shows faint graph-paper grid, no purple glow; CPR motif (3 dashed lines, TC/PIVOT/BC labels) renders under the CTA buttons.
3. Eyebrows render as `─── TEXT` kickers, no pill borders.
4. Strategy cards: hover shows corner ticks, no radial glow.
5. Tamil toggle (தமிழ்/EN) still switches all hero/section text — `data-ta` attributes intact.
6. Check responsive at 375px width — kicker rules and CPR motif don't overflow.
7. Other pages spot-check (`/learn_home.html`, `/trade_flow.html`) — unchanged, since `.text-gradient`/`.eyebrow` were left in place and only additive utilities went into the shared CSS.
