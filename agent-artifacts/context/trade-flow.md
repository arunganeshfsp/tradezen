# Context: trade-flow

**File:** `public/trade_flow.html`  
**Last updated:** 2026-07-06

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
| `_trendScore(d)` | Signal alignment score −12…+12: Gap ±2/±1 · CPR position ±2 · ORB: LTP vs orb.high/orb.low ±2 (inside=0) · Fut OI ±1/±2 · PCR ±1 · FII/DII bias ±1 · indicators bull−bear capped ±2 |
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

## Phase 1 Trend Enhancements (2026-07-06)

Four new signals added to the `#trend-panel`:

### 1.4 Event Risk Flag
- **Config:** `ai_engine/config/events.json` — array of `{date, time, label, severity: CAUTION|HIGH}`. Hot-reloaded every 5 min (no restart needed).
- **Endpoint:** `GET /trend/event-risk` → Python `/trend/event-risk`
- **Auto-rule:** last Tuesday of month (holiday-shifted) auto-detected as monthly expiry (HIGH).
- **Frontend:** `#tp-event-badge` in panel header (amber=CAUTION, red=HIGH); `#tp-veto-banner` full-width banner above the card when HIGH.
- **Conviction cap:** HIGH → force NONE; CAUTION → cap at LOW.

### 1.1 Nifty 50 Breadth
- **Config:** `ai_engine/config/nifty50_constituents.json` — 50 symbols as NSE tickers. Review quarterly.
- **Endpoint:** `GET /trend/breadth` (60s TTL lazy cache).
- **Data:** yfinance batch download for `.NS` suffixed tickers; prev-day close vs today's close counts advancing/declining.
- **Classification:** ≥35 one side → strong; 30–34 → moderate; else → mixed.
- **Frontend:** `Breadth` row in `tp-rows`; returns `waiting` pre-9:15.
- **Caveat:** Uses yfinance, which has 15-min delay outside market hours. During market hours (9:15–15:30) it reflects intraday LTP vs prev close.

### 1.2 BNF Alignment
- **Endpoint:** `GET /trend/bnf-alignment` (60s TTL lazy cache).
- **Data:** yfinance `^NSEBANK` — prev day OHLC for BNF CPR, 5m chart for LTP, 1m chart for ORB 9:15–9:30.
- **Logic:** both above TC → aligned; opposite sides → diverging; either inside CPR → neutral.
- **Frontend:** `BNF` row in `tp-rows`; green/red/yellow.
- **Conviction cap:** diverging → cap at MEDIUM.

### 1.3 OI Walls
- **Endpoint:** `GET /trend/oi-walls` (5-min TTL lazy cache).
- **Data:** uses WebSocket-enriched `market_state` via `im.get_option_chain()` for nearest weekly expiry (Tuesday, holiday-shifted), ATM ±10 strikes.
- **Baseline:** locked at 9:20 AM (first time `_oi_walls_baseline` is empty and time ≥ 9:20).
- **Frontend:** `OI Walls` row showing CE wall strike, PE wall strike, ΔOI, and spot % between walls.

### New state variables (frontend)
`eventRiskData`, `breadthData`, `bnfData`, `oiWallsData`, `_breadthStopped`

### New fetch functions (frontend)
`_fetchEventRiskSilent()`, `_fetchBreadthSilent()`, `_fetchBnfSilent()`, `_fetchOiWallsSilent()`

### Polling schedule
- Event risk: once on load (static-ish, hot-reloaded server-side)
- Breadth: load+5s, then every 60s; stops automatically after 9:45 (`_breadthStopped`)
- BNF: load+6s, every 60s
- OI Walls: load+7s, every 5 min

---

## Phase 2 Trend Enhancements (2026-07-06)

### 2.1 Previous Day Type Classification
- **Endpoint:** `GET /trend/day-type` (5-min TTL cache).
- **Logic:** Uses yfinance `^NSEI` 10-day daily history. `iloc[-2]` = yesterday, `iloc[-3]` = day-before. Classify: inside (H<pH, L>pL), outside (H>pH, L<pL), trend (|C-O|/(H-L)≥0.7 and close in top/bottom 25%), else range.
- **CPR pairing:** Reads live `trade_flow_data["prev_ohlc"]` to compute today's CPR width (same formula as `get_trade_flow`): narrow <40 pts, moderate 40-80, wide >80.
- **Frontend:** "Prev Day" row in `tp-rows`. Shows day type + CPR type + abbreviated interpretation (breakout watch, continuation/exhaustion, range-bound likely, etc.).

### 2.2 Weighted Alignment Score
- **Module:** `public/js/trend-scoring.js` — pure UMD module, no DOM/fetch. `computeTrendScore(signals, weights)` returns `{score, conviction, contributions[]}`.
- **Weights config:** `ai_engine/config/trend_weights.json` — signals + conviction_thresholds + iv_premium_thresholds. Served hot-reload by `GET /trend/weights`.
- **Signal adapter:** `_buildSignalInputs(d)` in `trade_flow.html` assembles the signal dict from all page-state caches (flowData, breadthData, bnfData, indData, openingVolData).
- **Score → conviction mapping:** `HIGH ≥7`, `MODERATE ≥4`, `LOW ≥2`, `NONE` in −2..+2 zone. Bearish mirror with `_BEAR` suffix. Phase 1 caps applied on top: event HIGH → NONE, CAUTION → cap LOW, BNF diverging → cap MEDIUM.
- **Breakdown toggle:** Clicking the conviction label in `tp-header-right` toggles `_breakdownOpen`. When open, a `#tp-breakdown-area` div below the conviction label shows per-signal weighted contributions sorted by magnitude, plus the total score.
- **Volume discount:** If `volRatio < 0.8`, ORB weight is halved inside `computeTrendScore`; contribution shown as "ORB (vol-discounted)".
- **Unit tests:** `test/trend-scoring.test.js` — 10 tests covering all-bullish, all-bearish, null/NaN safety, vol discount, custom weights, sorting, thresholds. Run `node test/trend-scoring.test.js`.

### 2.3 IV / VIX Reconciliation
- **No new endpoint** — computed client-side from `ivData.avg_iv` (already fetched by `_fetchIvSilent`) and `flowData.india_vix`.
- **Formula:** `ivPremium = avg_iv − india_vix`. Classified: <3 normal, 3–6 elevated, >6 event priced. Thresholds read from `trendWeights.iv_premium_thresholds` (configurable via JSON, fallback hardcoded).
- **Topbar chip (`#chip-iv`):** Now shows combined `IV 18.1% · VIX 11.8 · +6.3 event priced` when VIX is available; falls back to `IV XX% · STATUS` if VIX missing. Title attribute explains IV premium.
- **Trend panel row:** "IV/VIX" row shows the same combined data with classification color. Separate VIX-only row removed; the standalone VIX row in `tp-rows` kept for risk context.

### 2.4 Opening Volume Filter
- **Endpoint:** `GET /trend/opening-volume` (2-min TTL). Returns `{vol_ratio, classification, volume, avg10}`.
- **Data:** SmartAPI 1-min candles for nearest NIFTY futures token (`im.get_nifty_futures_token()`), 09:15–09:29 window. yfinance has no good fallback — returns `{"error": ...}` if SmartAPI fails.
- **Persistence:** SQLite table `opening_volume(date TEXT PRIMARY KEY, volume REAL)` in `tradezen.db`. Created lazily on first call. 10-day rolling average from prior rows.
- **Classification:** `≥1.3 strong`, `0.8–1.3 normal`, `<0.8 weak`.
- **Frontend:** "Open Vol" row. When `volRatio < 0.8`, suffix "· ORB discounted" shown. Score engine sees this via `vol_ratio` signal input.
- **Lazy:** Data only fetched/stored after 9:30. Pre-9:30 returns `{status: "waiting"}`.

### New state variables (Phase 2 frontend)
`dayTypeData`, `openingVolData`, `trendWeights`, `_breakdownOpen`

### New fetch functions (Phase 2 frontend)
`_fetchDayTypeSilent()`, `_fetchOpeningVolSilent()`, `_fetchTrendWeights()`

### Polling schedule (additions)
- Weights: once on load (static config)
- Day type: load+8s, then every 5 min
- Opening volume: load+9s, then every 2 min

---

## Phase 3 Trend Enhancements (2026-07-06)

### 3.1 Historical Conviction Accuracy Log
- **SQLite table:** `trend_log(date PK, conviction_label, weighted_score, signal_snapshot JSON, actual_day_type, orb_breakout_result, kingfisher_trade_taken, trade_result)` in `tradezen.db`.
- **Snapshot endpoint:** `POST /trend/log-snapshot` — idempotent per date (INSERT OR IGNORE); also guards via `localStorage('tz_snapshot_date')` on the frontend.
- **Frontend call:** `_sendSnapshotIfNeeded(d)` fires once per session after 9:30 AM, inside `fetchFlowData`. Page flag `_snapshotSentToday` + localStorage date prevent duplicates.
- **Accuracy endpoint:** `GET /trend/accuracy?days=60` — lazily backfills `actual_day_type` (yfinance daily) and `orb_breakout_result` (yfinance 5m intraday) for past logged dates. Returns `{rows, hit_rate}`. `&format=csv` returns `text/csv` attachment.
- **Frontend UI:** `#accuracy-section` collapsible below `#trend-panel`. Clicking expands `#accuracy-body` and calls `_fetchAccuracy()`. Renders a per-signal hit-rate summary and paginated table (30 rows), plus a "Download CSV" link.
- **Open issue:** `kingfisher_trade_taken` and `trade_result` have no UI to set them — nullable columns for future manual entry.

### 3.2 Gap Fill Tracker (client-side)
- **State var:** `_gapState` — `'holding' | 'filled' | null`. Updated by `_updateGapState(d)` called in every `fetchFlowData` cycle.
- **Logic:** gap-up is "filling" if LTP drops below prev close; "holding" if at 9:45 LTP is above 50% of the gap. Mirrored for gap-down. Small gaps (<5 pts) leave state null.
- **Scoring integration:** `gapState` is passed into `_buildSignalInputs` → `signal_snapshot.gapState`. In `trend-scoring.js`, `filled` → gap extractor returns 0; `holding` with a mid-range gap → raw += 0.5 (capped ±1).
- **Gap chip suffix:** `+36 pts · gap-up · holding ✓` or `filling ✗`.

### 3.3 GIFT Nifty Deviation Log
- **SQLite table:** `gift_deviation(date PK, gift_implied_open, actual_open, deviation)` in `tradezen.db`.
- **Lazy write:** `GET /trend/gift-deviation` writes today's row when `trade_flow_data["gift_nifty"]` and `trade_flow_data["nifty_open"]` are both set and it's ≥ 9:15.
- **Rolling metric:** 20-day mean absolute deviation. Thresholds: ≤25 pts → "reliable", ≤40 → "moderate", else "noisy".
- **Frontend:** `#gift-dev-footnote` div injected inside `detail1` (GIFT Nifty card). Fetched by `_fetchGiftDeviationSilent()` on load+10s, then every 5 min.

### 3.4 Kingfisher Window Countdown (client-side)
- **Chip:** `#chip-kingfisher` in `app-topbar`. Visible Wed/Thu only between 9:30 and 13:00 IST, showing `Kingfisher window: Xh Ym left`.
- **Update:** `_updateKingfisherChip()` runs every 30s (polled via `setInterval`), plus immediately on load.
- **T−15 alert:** `_kfAlertFired` flag prevents repeated toasts. Fires `_showToast(…)` + browser notification (if granted) when `diffMs ≤ 15 min`.
- **Label:** "Kingfisher" kept as-is (user's strategy name). Copy is descriptive ("window closes in…"), not directive.

### New state variables (Phase 3 frontend)
`giftDeviationData`, `accuracyData`, `_accuracyOpen`, `_snapshotSentToday`, `_gapState`, `_gapStateLockedAt`, `_kfAlertFired`

### New fetch functions (Phase 3 frontend)
`_fetchGiftDeviationSilent()`, `_fetchAccuracy()`, `_sendSnapshotIfNeeded(d)`, `_updateKingfisherChip()`, `_updateGapState(d)`, `window._toggleAccuracy()`

### New Node proxy routes (stockRoute.js)
- `POST /api/trend/log-snapshot` → Python `POST /trend/log-snapshot`
- `GET /api/trend/accuracy` (+ `?format=csv`) → Python `GET /trend/accuracy`
- `GET /api/trend/gift-deviation` → Python `GET /trend/gift-deviation`

### Polling schedule (additions)
- GIFT deviation: load+10s, then every 5 min
- Kingfisher chip: immediate + every 30s
- Accuracy: on-demand (when user expands the panel)

---

## Known Caveats

- The 6 editing flags (`editingOhlc`, etc.) must be checked before re-rendering to avoid clearing in-progress user input on poll cycles.
- `giftRefClose` is null until the page fetches trade-flow data — GIFT gap calculation falls back to `prev.close` if not yet set.
- Steps 1–6 use IDs `s1-status` … `s6-status` and `detail1` … `detail6` — these are hardcoded in `showStep()`.
- Light theme applied via `/css/light-theme.css` (shared) + page-specific `:root[data-theme="light"]` block for chips, scenario buttons, step items, tables, etc. JS-set inline colors on `#chip-vix`, `#chip-iv`, `#chip-alerts`, `#pcr-chip` need `!important` in CSS overrides.
- The hero section and standalone `scenario-bar` div have been removed — chips now live in `app-topbar`, which is always visible. The `#refresh-note` element moved to the topbar right edge.
- Footer removed; SEBI disclaimer is in the `.bbar-disclaimer` span inside `.app-bottombar`.
- Breadth endpoint uses yfinance batch download which is slow (~5–10s) — the 60s TTL means the first post-9:15 call blocks the executor thread briefly. Acceptable for a single daily-use tool.
- OI Walls data comes from the WebSocket-subscribed `chain_map` via `market_state`. Outside market hours (or if WebSocket dropped) OI values will be zero/stale. The endpoint returns `{"error": "..."}` gracefully, frontend shows "unavailable".
- `_capConv` function is defined inside `renderTrendPanel` (no outer scope needed). Re-defined on every render — fine for this use.
- Tamil i18n (`data-en`/`data-ta`) is not implemented in `trade_flow.html` — no Tamil strings added for new rows (consistent with existing page behavior).
