# Context: stock-intraday-simulator (ORB Simulator)

**Files:**
- `public/stock_intraday_simulator.html` — frontend viewer
- `ai_engine/core/orb_simulator.py` — pure business logic / constants
- `ai_engine/storage/sqlite_store.py` — DB tables + CRUD (orb_candidates, orb_stock_trades)
- `ai_engine/main.py` — background engine + 3 FastAPI endpoints
- `routes/stockRoute.js` — 3 Node proxy routes under `/api/simulator/*`

**Last updated:** 2026-07-06 (per-user sessions, daily trade cap, live LTP, CSV export, live watch)

---

## 2026-07-06 — Per-User Sessions + Fixes

**What changed**
- **Per-user simulator sessions.** `orb_candidates`, `orb_stock_trades`, `orb_settings` all gained a `user_id` column (`''` = shared session). Migration `_migrate_orb_user_scope()` in `sqlite_store.py` rebuilds old tables on first `get_conn()`; existing rows land in the shared session. `orb_candidates` UNIQUE is now `(date, user_id, symbol, side)`; `orb_settings` PK is `(user_id, key)`. All `orb_*` helpers take `user_id` (`None` = all sessions, `''` = shared).
- **Fork model:** a signed-in user stays on the shared session until they first save Settings — that POST copies current shared settings to their user_id and forks them. `_orb_session_id(request)` in main.py resolves the effective session from the `X-User-Id` header. From the next 09:16 capture they get their own candidates/trades (capture + trigger poll iterate `[''] + orb_list_setting_users()`; quotes fetched once for the full universe and filtered per session; 09:15 bench candles fetched once per unique token).
- **Node:** `_simAuth` middleware in stockRoute.js (optional JWT — invalid/absent token falls back to shared) forwards `X-User-Id` on all `/api/simulator/*` routes except trade-verify. Frontend `_hdrs()` sends `Authorization: Bearer tz_learn_token` on every simulator fetch; `#sessBadge` in the status strip shows MY SESSION / SHARED SESSION from `state.session`.
- **Daily trade cap (bug fix):** `max_slots` semantics changed from *max concurrent* to *max trades per day* — resolved trades no longer free a slot. `slots_used` in state = total trades today. Same daily-cap wording used in the backtest.
- **Sticky Square Off column (bug fix):** trades table now has `.trades-tbl` class; last td/th is `position:sticky; right:0` so the button is never clipped on horizontal scroll.
- **Live LTP:** `_orb_ltp_cache` (token → ltp) updated inside `_orb_raw_quotes`; `/simulator/state` merges `live_ltp` into candidates and trades for today only. Shown as columns in both tables (trades: OPEN rows only, direction-aware coloring).
- **CSV export:** both panels have Export CSV buttons (`exportCandidates()` respects the side filter and joins trades by symbol+direction; `exportTrades()` dumps full trade records). Shared `_csvVal`/`_downloadCsv` helpers, UTF-8 BOM, disclaimer footer.
- **Live Watch:** `toggleLiveWatch()` — 5s polling, signal monitor bar with IST clock + phase message, toast on newly-triggered trades. Backtest blocked 09:14–09:18 IST (`_inCaptureWindow()`) so live capture has priority.

**Why** — user reported 6 trades with a 5-slot cap (concurrent semantics surprised them), clipped square-off column, and wanted multi-user tailored settings after realizing two machines share one backend state.

**Known caveats**
- Square-off enforces ownership (403 if trade belongs to another session). trade-verify is unauthenticated (read-only).
- A forked user's session only diverges from the *next* capture; today's shared candidates/trades disappear from their view immediately after forking (their session has no rows for today).
- Backtest is per-session: each user's backtest of the same date stores separate rows.
- Capture cost grows with distinct forked users (candidate persistence + per-session filtering) but quote/candle fetches stay deduplicated.

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
  panel-card: SIMULATED TRADES  ← NOW FIRST
    sim-tbl (11 cols: direction, symbol, fill, invalidation, ref target, qty, investment, R:R, outcome, study P/L, action)
    each trade row is clickable → expands a detail row with:
      Left col: entry time, sim fill, day high/low at entry, VWAP at entry, exit time/price
      Right col: price verification (calls /api/simulator/trade-verify, cached per trade_id)
  panel-card: CANDIDATE STOCKS
    side-tabs: ALL | BULLISH ▲ | BEARISH ▼
    sim-tbl (8 cols: direction, symbol, 09:16 LTP, dominance, bench H/L, SL basis, status)
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
| `_settings` | Cached engine settings from `/api/simulator/settings` |
| `_pollTimer` | `setInterval` handle; paused on `visibilitychange` when hidden |
| `_expandedTrades` | `Set<trade_id>` of currently expanded detail rows; preserved across `renderTrades` calls |
| `_verifyCache` | `{trade_id: verifyResult}` cache; populated on first expand, avoids re-fetching |

---

## API (FastAPI → Node Proxy)

| Node path | FastAPI path | Method | Purpose |
|---|---|---|---|
| `GET /api/simulator/state?date=` | `GET /simulator/state?date=` | GET | Returns `{date, candidates, trades, summary, window}` |
| `POST /api/simulator/sl-basis` | `POST /simulator/sl-basis` | POST | Sets SL basis for a WAITING candidate; body: `{date, symbol, side, basis, custom_price?}` |
| `POST /api/simulator/square-off` | `POST /simulator/square-off` | POST | Squares off an OPEN trade at live LTP; body: `{trade_id}` |
| `GET /api/simulator/settings` | `GET /simulator/settings` | GET | Returns all engine settings (with defaults) |
| `POST /api/simulator/settings` | `POST /simulator/settings` | POST | Updates one or more settings; returns full settings object |
| `GET /api/simulator/trade-verify?trade_id=` | `GET /simulator/trade-verify?trade_id=` | GET | Fetches ONE_MINUTE candles (cached) for the trade's date, verifies if SL/target was actually hit; returns `{sl_hit_at, tgt_hit_at, verified_outcome, recorded_outcome, day_high_at_entry, …}` |

## Engine Settings

Stored in `orb_settings` SQLite table (key-value). Read by the background engine at each capture/trigger cycle — changes take effect from the **next session's 09:16 capture**.

| Setting | Default | Description |
|---|---|---|
| `target_rupees` | 900 | Study P/L target ₹ per trade |
| `max_slots` | 5 | Max concurrent open simulated trades |
| `universe` | nifty500_fno | Stock universe: `nifty500_fno` / `nifty100_fno` / `nifty50` |
| `default_sl_basis` | VWAP | SL basis applied to candidates at capture; per-stock override still possible |
| `price_min` | 700 | Min price filter (₹) |
| `price_max` | 7000 | Max price filter (₹) |
| `dom_min_pct` | 60 | Min order-book dominance % to qualify as candidate |
| `candidate_cap` | 25 | Max candidates kept per side (after sorting by dominance strength) |

Helper functions in `storage/sqlite_store.py`: `orb_get_settings(conn)` (returns typed dict with defaults), `orb_upsert_settings(conn, updates)`.

Universe symbol sets defined as frozen sets in `main.py`: `_NIFTY50_SYMS` (~50), `_NIFTY100_SYMS` (~100). Applied by filtering the Nifty500 F&O stocks at capture time.

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
| `TARGET_HIT` | REF. LEVEL REACHED |
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
