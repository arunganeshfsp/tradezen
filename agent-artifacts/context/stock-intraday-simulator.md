# Context: stock-intraday-simulator (ORB Simulator)

**Files:**
- `public/stock_intraday_simulator.html` — frontend viewer
- `ai_engine/core/orb_simulator.py` — pure business logic / constants
- `ai_engine/storage/sqlite_store.py` — DB tables + CRUD (orb_candidates, orb_stock_trades)
- `ai_engine/main.py` — background engine + 3 FastAPI endpoints
- `routes/stockRoute.js` — 3 Node proxy routes under `/api/simulator/*`

**Last updated:** 2026-07-05

---

## What This Module Does

Rule-based paper-trading simulator for Opening-Range Breakout/Breakdown (ORB) on Nifty 500 F&O cash stocks. No real broker orders are placed. Runs a background engine in Python that:

1. **09:16** — Captures the ORB anchor candle (09:15 ONE_MINUTE H/L as bench_high/bench_low) for every Nifty 500 F&O stock. Filters by price band ₹700–₹7000, dominant order-book side (≥60%), volume filter. Stores top 25 BUY + 25 SELL candidates in `orb_candidates`.
2. **09:16–10:30 (ENTRY_WINDOW)** — Polls every 5s. When price breaks above bench_high (BUY) or below bench_low (SELL), triggers a paper trade: computes SL from locked basis (VWAP/DAY_HIGH/DAY_LOW/CUSTOM), sizes to ₹900 target with FLOOR qty, stores in `orb_stock_trades`. Max 5 concurrent slots.
3. **10:30 (window close)** — Remaining WAITING candidates → WINDOW_CLOSED.
4. **15:30 (EOD)** — OPEN trades → SQUARE_OFF at stored `close_price`.

---

## Layout (stock_intraday_simulator.html)

```
nav.halo-navbar
hero (htag + h1 + sub)
ctrl-bar (date picker + live status dot)
main-wrap (max-width 1260px)
  status-strip (phase-chip + slots bar 5 pips + sim-banner)
  panel-card: CANDIDATE STOCKS
    side-tabs: ALL | BULLISH ▲ | BEARISH ▼
    sim-tbl (8 cols: direction, symbol, 09:16 LTP, dominance, bench H/L, SL basis, status)
  panel-card: SIMULATED TRADES
    sim-tbl (11 cols: direction, symbol, fill, invalidation, ref target, qty, investment, R:R, outcome, study P/L, action)
  summary-strip (total P/L | open investment | win rate | open | target | SL | squared)
disclaimer (SEBI one-liner)
scripts: bootstrap, halo-aurora.js, inline JS
```

---

## Key JavaScript State

| Variable | Purpose |
|---|---|
| `_currentDate` | ISO date string being viewed (IST today or selected past date) |
| `_todayDate` | Today's IST date, computed once on load |
| `_isLive` | `_currentDate === _todayDate`; controls polling, interactive controls |
| `_candFilter` | `'ALL'` \| `'BUY'` \| `'SELL'`; filters candidates table |
| `_stateData` | Last fetched state from `/api/simulator/state` |
| `_pollTimer` | `setInterval` handle; paused on `visibilitychange` when hidden |

---

## API (FastAPI → Node Proxy)

| Node path | FastAPI path | Method | Purpose |
|---|---|---|---|
| `GET /api/simulator/state?date=` | `GET /simulator/state?date=` | GET | Returns `{date, candidates, trades, summary, window}` |
| `POST /api/simulator/sl-basis` | `POST /simulator/sl-basis` | POST | Sets SL basis for a WAITING candidate; body: `{date, symbol, side, basis, custom_price?}` |
| `POST /api/simulator/square-off` | `POST /simulator/square-off` | POST | Squares off an OPEN trade at live LTP; body: `{trade_id}` |

---

## SEBI Display Mapping (applied at render sites only)

| Internal value | Display label |
|---|---|
| `BUY` | `BULLISH ▲ (SIM)` |
| `SELL` | `BEARISH ▼ (SIM)` |
| `trigger_price` | Sim. Fill |
| `stop_loss_price` | Invalidation |
| `target_price` | Ref. Target |
| `SL_HIT` | INVALIDATION HIT |
| `TARGET_HIT` | TARGET REACHED |
| `pnl` | Study P/L |
| `SQUARE_OFF` | SQUARED OFF |

---

## Background Engine Constants (core/orb_simulator.py)

```python
SIM_TARGET_RUPEES = 900     # target rupees per trade
SIM_CAPITAL = 100_000       # nominal capital for sizing
SIM_TICK = 0.05             # price tick rounding
SIM_MAX_SLOTS = 5           # concurrent open trades
SIM_CANDIDATE_CAP = 25      # max candidates per side
SIM_PRICE_MIN = 700         # filter: min price
SIM_PRICE_MAX = 7000        # filter: max price
SIM_DOM_MIN_PCT = 60        # filter: min dominant-side order-book %
```

---

## Known Caveats

- **Time handling:** All time comparisons use naive IST (`datetime.utcnow() + timedelta(hours=5, minutes=30)`). The `_IST` timezone in `core/orb_simulator.py` exists but the background loop uses naive datetimes for consistency with the rest of codebase.
- **`SIM_FORCE_WINDOW=1`** env var bypasses all time/weekday gates for testing. Set before starting the server.
- **VWAP at trigger:** Uses `getMarketData("FULL")` → `averageTradePrice`. Not available from `MarketSnapshot`; raw API call is made in `_orb_raw_quotes`.
- **Token lookup in outcome poll:** `orb_stock_trades` table has no `token` column. Outcome poll builds a `sym_to_token` dict by joining with `orb_candidates` at start of each poll tick.
- **One trade per stock per day:** A symbol that has already resolved (TARGET_HIT, SL_HIT, SQUARE_OFF) frees its slot, but a new trade for the same symbol is not started again.
- **Past-date view:** The date picker defaults to today (IST). Selecting a past date renders history in read-only mode (polling stops, SL dropdowns disabled, square-off buttons hidden).
- **Rate limits:** 50-token batches for `getMarketData` with 150ms between batches; ~0.35s sleep between `getCandleData` calls.
- **`cup_handle.md`** — separate module, unrelated to this simulator despite "breakout" overlap.

---

## Open Issues

- EOD square-off uses the stored `close_price` field (set at 15:30 poll). If server restarts between 15:20–15:30, some OPEN trades may miss the close price; `square-off` endpoint falls back to live LTP fetch which would fail post-market.
- No SMS/push notification when a trade triggers. Future: integrate with a notification hook.
- Historical capture: only today's session is run by the engine. Past date data is only queryable if the server was running on that date.
