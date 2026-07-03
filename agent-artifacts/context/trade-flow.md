# Context: trade-flow

**File:** `public/trade_flow.html`  
**Last updated:** 2026-07-03

---

## Purpose

Pre-market + intraday bias dashboard. Walks traders through a 6-step framework: GIFT Nifty gap → CPR width → scenario → opening price → ORB → live signal. Steps auto-advance based on market phase.

---

## SEBI Compliance Reframe (2026-06-09)

Full educational reframe of all user-facing directive language (English + Tamil). Per CLAUDE.md, this is an educational tool, not advice. Key conventions now used throughout:

- **Buy/Sell/Long/Short directives → descriptive bias:** `Bullish`/`Bearish`/`Watch`. "buy opportunity" → "bullish reference zone"; "Enter Long" / "Long entry" → "bullish trigger" / "bullish setup".
- **Triggers/exits framed as premise, not orders:** "ENTRY NOW" → "TRIGGER ACTIVE — … SETUP"; "STOP LOSS HIT — EXIT NOW" → "INVALIDATION LEVEL REACHED"; "BIAS BROKEN — EXIT" → "PREMISE INVALIDATED"; "FALSE BREAKOUT — EXIT" → "PREMISE FAILED".
- **Risk-management terms:** "SL" → "Invalidation"; "book 50%" → "first reference"; "trail SL/stop → entry" → "trail invalidation to breakeven"; "Entry Zone" → "Reference Zone".
- **Position sizing → conviction:** "FULL/HALF POSITION", "REDUCED SIZE" → "FULL/HALF/LOW CONVICTION"; "NO TRADE" → "NO SETUP"; "SKIP / REDUCE SIZE" → "STAND ASIDE / LOW CONVICTION".
- **Hero title:** "Trade Entry Flow" → "Trade Decision Flow".
- **Disclaimer:** footer now carries the full mandated line.

**Important — `_getCprDirection()` internal enum is unchanged:** it still returns `dir: 'LONG' | 'SHORT' | 'WATCH'`. These tokens drive CSS classes (`.alog-dir.LONG`, `.alog-stat.long`), alert-log storage, filters, and outcome evaluation. A `DIR_LABEL = { LONG:'BULLISH', SHORT:'BEARISH', WATCH:'WATCH' }` map (defined just before `_fireAlert`) converts them to compliant labels at the three display sites only (toast, browser notification, alert-log row). Do NOT rename the enum — it would break CSS/storage/filters. Only the displayed text is mapped.

---

## Layout (Simulator Architecture — 2026-07-03)

Fixed-viewport, no-scroll layout. `body` is `height:100vh, overflow:hidden, flex-column`.

```
nav (56px)
app-topbar (52px)   — live chips | separator | scenario buttons | refresh-note
app-workspace       — flex:1, overflow:hidden
  app-sidebar (236px) — phase heads (collapsible) + step tracker, overflow-y:auto
  app-main (flex:1)   — overflow-y:auto, background:var(--bg)
    trend-panel       — "Today's Trend" at-a-glance card (ALWAYS first, hidden until data loads)
    ohlc-banner       — shown only when CPR data is missing
    detail-area       — step detail cards (detail1..detail6, ind-card, iv-card)
    sec-panel#sec-rules  — rules grid (hidden until Rules tab clicked)
    sec-panel#sec-alerts — alert log (hidden until Alerts tab clicked)
app-bottombar (40px) — Rules tab | Alerts tab | SEBI disclaimer
```

**Panel toggle:** `switchPanel(id)` — clicking a `.btab` toggles `.sec-active` on `.app-main`, which hides `.detail-area` and shows the matching `.sec-panel`. Clicking the active tab again collapses it and restores `.detail-area`.

**Phase collapse:** `.phase-head.ph-collapsed + .steps-wrap{display:none}` — always active (not gated by media query). Phase 1 starts expanded, phases 2 and 3 start collapsed.

---

## Key State

| Variable | Purpose |
|---|---|
| `currentScenario` | `'bull'` \| `'bear'` \| `'conditional_bull'` \| `'conditional_bear'` |
| `currentStep` | Active step (1–6) |
| `flowData` | Latest `/api/trade-flow` response |
| `mpData` | Latest `/api/market-profile/levels` response (prev day levels) |
| `autoScenario` | Scenario computed by server |
| `editingOhlc / editingGift / editingOrb / editingNiftyOpen` | Guards that pause re-renders while user is entering data |
| `giftRefClose` | Reference close for GIFT Nifty gap = GIFT − giftRefClose |
| `lastAutoAdvancePhase` | Prevents re-triggering auto step-advance |
| `fiiDiiData` | FII/DII response cache — set by Phase 3 fetch wiring |
| `indData` | Indicators snapshot cache — set by Phase 3 fetch wiring |

---

## Key Functions

| Function | What it does |
|---|---|
| `switchPanel(id)` | Toggles secondary panel (rules/alerts); adds `.sec-active` to `.app-main` which hides detail-area |
| `showStep(n)` | Reveals step n detail panel, updates step nav status |
| `setScenario(sc, fromAuto)` | Sets scenario + controls conditional bear/bull visibility |
| `renderStep1(d)` | GIFT Nifty gap card — shows gap label + bull/bear/neutral box |
| `renderStep2(d)` | CPR card — width, type (narrow/medium/wide), prev OHLC edit form |
| `autoFetchGiftNifty()` | POST `/api/fetch-gift-nifty` to get live GIFT Nifty price |
| `fmt(n)` | Locale-formatted number (en-IN, 0–2 decimal places) |
| `_gapPts(d)` | Computes gap points: pre-market uses `d.gift_nifty − prev.close`; after open uses `d.nifty_open.price − prev.close`; returns null if data missing |
| `_trendScore(d)` | Signal alignment score −10…+10: Gap ±2/±1 · CPR position ±2 · ORB vs_cpr ±2 · Fut OI signal ±1/±2 · PCR ±1 |
| `renderTrendPanel(d)` | Renders `#trend-panel` card with verdict, conviction, alignment meter, and 8 signal rows (Gap/CPR/ORB/FutOI/PCR/FII-DII/TrendInd/VIX). Called from `fetchFlowData()` on every 30s poll, also from `_fetchFiiDiiSilent()` and `_fetchIndSilent()` when those caches update. |
| `_fetchFiiDiiSilent()` | Silent fetch of `/api/fii-dii` → `fiiDiiData`. On load after 2s + every 30 min. |
| `_fetchIndSilent()` | Silent fetch of `/api/indicators/snapshot` → `indData` + `renderIndicators(d)`. On load after 4s + every 5 min. Keeps the existing ind-card UI in sync alongside the trend panel row. |

---

## API Dependencies

| Endpoint | Used for |
|---|---|
| `GET /api/trade-flow` | Main data: phase, CPR, prev OHLC, GIFT Nifty, ORB, VIX |
| `GET /api/cpr-levels` | CPR + Camarilla level values |
| `GET /api/market-profile/levels` | Prev day POC/VAH/VAL/IB |
| `GET /api/fetch-gift-nifty` | Auto-fetch GIFT Nifty from external source |
| `POST /api/set-gift-nifty` | User override GIFT Nifty price |
| `POST /api/set-prev-ohlc` | User override previous OHLC |
| `POST /api/set-nifty-open` | Set opening price at 9:15 |
| `POST /api/set-orb` | Set ORB high/low after 9:30 |
| `GET /api/fii-dii` | FII/DII daily provisional cash-market flows — auto-fetched on load + every 30 min |
| `GET /api/indicators/snapshot` | Indicators snapshot (VWAP/EMA/MACD/RSI) — auto-fetched on load + every 5 min |

---

## Market Phase Logic

The server returns `d.phase` which drives auto step-advance:
- `pre_market` → show Step 1 (GIFT Nifty)
- `market_open` → show Step 3 (opening price)
- `orb_window` → show Step 5 (ORB)
- `live` → show Step 6 (signal)

---

## Trend Panel — CSS Tokens

`.tp-card` · `.tp-header` · `.tp-label-tag` · `.tp-verdict` · `.tp-verdict-bull/bear/skip/cond` · `.tp-meter-rail` · `.tp-meter-dot` · `.tp-rows` · `.tp-row` · `.tp-row-icon/name/val` · `.tp-row-val.tp-bull/bear/neutral/caution`.

Light theme overrides live in the same `:root[data-theme="light"]` block. Mobile (≤900px): `.tp-header` becomes column layout.

---

## Known Caveats

- The 6 editing flags (`editingOhlc`, etc.) must be checked before re-rendering to avoid clearing in-progress user input on poll cycles.
- `giftRefClose` is null until the page fetches trade-flow data — GIFT gap calculation falls back to `prev.close` if not yet set.
- Steps 1–6 use IDs `s1-status` … `s6-status` and `detail1` … `detail6` — these are hardcoded in `showStep()`.
- Light theme applied via `/css/light-theme.css` (shared) + page-specific `:root[data-theme="light"]` block for chips, scenario buttons, step items, tables, etc. JS-set inline colors on `#chip-vix`, `#chip-iv`, `#chip-alerts`, `#pcr-chip` need `!important` in CSS overrides.
- The hero section and standalone `scenario-bar` div have been removed — chips now live in `app-topbar`, which is always visible. The `#refresh-note` element moved to the topbar right edge.
- Footer removed; SEBI disclaimer is in the `.bbar-disclaimer` span inside `.app-bottombar`.
