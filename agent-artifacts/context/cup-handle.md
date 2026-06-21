# Cup & Handle Pattern Detector

**Status:** active

## What changed

New module `ai_engine/core/patterns/` — 5-file package for deterministic Cup & Handle pattern detection.

### Files created

| File | Purpose |
|---|---|
| `core/patterns/__init__.py` | Package init |
| `core/patterns/pattern_utils.py` | Pivot detection, quadratic fit, volume utils |
| `core/patterns/structure.py` | Cup & handle geometry validation |
| `core/patterns/scoring.py` | 5-pillar confidence score (0-100) |
| `core/patterns/breakout_strength.py` | Entry, stop-loss, T1/T2 targets |
| `core/patterns/cup_handle.py` | Main detector — `analyse(symbol)` + `scan(symbols)` |
| `public/cup_handle.html` | Standalone frontend page |

### main.py additions (after `/swing/prices`)
- `GET /patterns/cup-handle/analyse?symbol=X` — single stock
- `GET /patterns/cup-handle/scan?universe=nifty100` — bulk scan

### routes/stockRoute.js additions (after existing scan)
- `GET /api/patterns/cup-handle/analyse?symbol=X` (30s timeout)
- `GET /api/patterns/cup-handle/scan?universe=nifty100` (180s timeout)

## Detection algorithm

**Data:** yfinance 1-year daily OHLCV (same call as swing_analyzer.py: `period="1y", interval="1d"`). 1-hour in-memory cache (`_CACHE`).

**Stage detection (priority order):**

1. **`complete`** — Cup formed + handle valid (3-15% pullback, 3-35 candles) + score ≥ 25
2. **`handle_forming`** — Cup formed + handle developing (price below 97% of handle high)
3. **`cup_complete`** — Cup formed, handle not started yet (< 3 candles since right rim)
4. **`early_cup`** — Left high set, 10-40% drop, ≥40% recovery, but no complete cup yet

**Cup validation rules (structure.py):**
- Duration: 20-180 trading days
- Depth: 10-40% from left rim to bottom
- Recovery: right rim ≥ 80% and ≤ 112% of left rim
- Shape: quadratic fit (polyfit degree-2) — must have positive curvature (U-shape), curvature_a > 0

**Handle validation rules:**
- Pullback: 3-15% from handle high
- Duration: 3-35 candles
- `near_breakout = True` when current price ≥ 97% of handle high

**Scoring (0-100):**
- Shape (40 pts): depth optimality in 12-30% range + roundness (R² of quadratic) + symmetry
- Handle (25 pts): pullback optimality in 5-10% range + near-breakout bonus; 12.5 if cup complete no handle
- Volume (20 pts): handle vol avg / cup vol avg — lower ratio = better (dry-up signal)
- Prior trend (10 pts): % change in 60 candles before left rim (30% prior rise = full 10 pts)
- Recovery (5 pts): right rim vs left rim — 95-105% = 5 pts

**Breakout targets (breakout_strength.py):**
- Entry: handle_high × 1.003
- Stop-loss: handle_low × 0.992
- T1: entry + cup_depth
- T2: entry + cup_depth × 2

## Key caveats

- Minimum score threshold to report: **25** (avoids spurious early detections on noisy data)
- Scan of 100 stocks at cold cache takes ~2-3 minutes (yfinance rate limiting)
- The pivot detection uses window=10 — may miss pivots near array edges (first/last 10 candles)
- Right rim candidates: only pivot highs where ≤35 candles remain after them (handle zone constraint)
- Cup search per right rim: 20-180 candles back in steps of 5 — O(36) iterations per right rim candidate, up to 10 candidates = ~360 combinations per stock
- Early cup stage only fires if no scored cup was found (score < 25)

## Frontend chart

`cup_handle.html` now renders a Chart.js 4.4.3 price chart inside `.chart-wrap` after each `analyse()` call.

- **`_cupChartInstance`** global — destroyed and recreated on each new analysis
- **`drawCupChart(d)`** — called via `setTimeout(..., 30)` at end of `renderSingle()` to let the canvas DOM settle
- Dataset 1: full close price line (purple, 1.5px, no dots)
- Dataset 2: sparse cup outline — null array with values only at `left_rim_idx`, `bottom_idx`, `right_rim_idx`; draws dashed amber line connecting the 3 points; colored dots: orange (left rim), green (bottom), blue (right rim); `spanGaps: false` so only the pattern segment is connected
- Dataset 3 (conditional): horizontal dashed green line at `targets.entry` (breakout level); fallback to `closes[rri]` if no targets
- Y-axis on right side; X-axis shows `MMM YY` format via `toLocaleDateString`
- Adapts to dark/light theme for grid and tick colors

## Known issues / deferred

- Chart only shows for `analyse()` — scan cards do not have mini-charts
- No SQLite persistence for scan results — each scan re-fetches yfinance
- Scan timeout: 180 seconds in Node proxy; large scans can hit it on slow connections
- The "left rim" detection algorithm looks at max in first portion before cup bottom — can occasionally pick a sub-optimal left rim if the actual left rim is not the global max in that window

## Recent changes (2026-06)

### Scan expansion + Watchlist
- **Universe dropdown** expanded: Nifty 50 / Nifty 100 / Midcap 150 / Smallcap 250 / My Watchlist
- **Sector filter** added: 10 sectors (Banks, IT, Pharma, Metals, Auto, FMCG, Energy, Chemicals, Realty, Infra) — filters within the selected universe or returns sector list when no intersection
- **Watchlist** (`public/watchlist.js`): localStorage-based, `WL.add/remove/toggle/has/count`, fires `tz-wl-change` CustomEvent; star (☆/★) button on every scan card and detail view
- Backend `_get_ch_symbols()` helper resolves final symbol list; NSE live fetch for Midcap150/Smallcap250 with fallback static lists
- Scan endpoint now accepts `sector` and `symbols` params; timeout varies by universe (2–10 min)
- Node proxy route timeout needs increasing for Midcap/Smallcap scans (currently 180s — too short)

### SEBI compliance
- Renamed all user-facing labels: "Entry" → "Reference Level", "Stop-loss" → "Risk Level", "Target 1/2" → "Projection 1/2", "TRADE PLAN" → "PATTERN LEVELS"
- Chart legend: "Breakout Level" → "Reference Level"
- Table headers: ENTRY → REF. LEVEL, STOP → RISK LEVEL, T1 → T1 PROJ.
- Page subtitle: "complete breakout setup" → "pattern complete"
- SEBI disclaimer banner added below page header
- scoring.py: "Look for volume to contract before entering" → "Observe if volume contracts further"

### Cup detection tuning (TATAPOWER fix)
- `_PERIOD_PARAMS["1y"]`: min_cup 20→45, max_cup 180→240
- `_PERIOD_PARAMS["2y"]`: min_cup 20→60, max_cup 180→460
- Prevents micro-cups (< 9 weeks) from scoring above large year-long bases

## Open issues

- Node proxy timeout for `/api/patterns/cup-handle/scan` is 180s — needs increase to 600s for Smallcap 250 scans
- No SQLite caching of scan results — each scan re-fetches yfinance
