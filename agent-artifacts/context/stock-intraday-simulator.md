# Context: stock-intraday-simulator (ORB Simulator)

**Files:**
- `public/stock_intraday_simulator.html` — frontend viewer
- `ai_engine/core/orb_simulator.py` — pure business logic / constants
- `ai_engine/storage/sqlite_store.py` — DB tables + CRUD (orb_candidates, orb_stock_trades)
- `ai_engine/main.py` — background engine + 3 FastAPI endpoints
- `routes/stockRoute.js` — 3 Node proxy routes under `/api/simulator/*`

**Last updated:** 2026-07-07 (day-high/low trigger, % change filter, auto-trigger, periodic rescan, scan-now button)

---

## 2026-07-07 — Periodic Rescan + Day H/L Trigger + % Change Filter

**What changed**
- **Trigger condition:** BUY fires when `ltp > session day_high`; SELL when `ltp < session day_low` (live from Angel One `getMarketData("FULL")` → `high`/`low` fields). Falls back to `bench_high`/`bench_low` if unavailable. This replaces the old "cut bench candle H/L" condition.
- **% change filter:** BUY candidates require `change_pct >= buy_min_chg_pct` (default 1%); SELL require `change_pct <= -sell_min_chg_pct` (default 1%). Configurable in Settings. `_orb_chg_cache` (token → chg%) mirrors `_orb_ltp_cache`; surfaced as `change_pct` column in candidates table.
- **Auto-trigger:** `_orb_auto_trigger_sync(today, now_ist)` runs after every capture/rescan. Enters the top N (default 5) strongest BUY and SELL WAITING candidates at their `ltp_0916` capture price. N = `auto_trigger_count` setting. 0 = disabled.
- **Periodic rescan:** `_orb_capture_sync` gains `rescan=False, now_ist=None` params. When `rescan=True`: uses current-1min candle as bench; skips symbols already WAITING/TRIGGERED (per-session). Engine loop tracks `_last_capture_time` and `_last_capture_today`; triggers rescan every `rescan_interval_min` minutes (default 5) while within `entry_window_end`. Day rollover resets `_last_capture_time`. Server restart with existing candidates anchors timer to "now" (no immediate re-capture). `rescan_interval_min = 0` disables periodic rescan (single scan only).
- **New settings:** `buy_min_chg_pct` (0–20, float), `sell_min_chg_pct` (0–20, float), `auto_trigger_count` (0–20, int), `rescan_interval_min` (0–60, int). All in Settings panel with `data-en`/`data-ta` i18n.

- **Scan Now button:** `POST /simulator/scan-now` endpoint sets global `_orb_force_rescan = True`; consumed by the engine loop on its next 5s tick (triggers an immediate rescan + auto-trigger). Returns 400 if the session's trade count >= max_slots. Node proxy at `POST /api/simulator/scan-now`. Frontend: yellow "⟳ SCAN NOW" button in candidates panel header; visible only on live view; disabled (greyed out) when slots full; shows "⟳ SCANNING…" for 8s then forces a state refresh.

**Known caveats**
- Rescan bench candle: at T minutes, bench = T-1 minute candle (rolling ORB, not fixed 09:15). Existing WAITING candidates retain their original bench.
- `ltp_0916` field stores the capture-time LTP for ALL scans (including rescans at 09:30+). The column name is slightly misleading for rescan rows but the value is correct as the entry reference price.
- `_last_capture_time` is a local variable inside `_orb_simulator_loop`; resets on server restart. If candidates exist on restart, the engine anchors to "now" and waits one full `rescan_interval_min` before the next rescan.
- `_orb_force_rescan` is a module-level global; both the endpoint and the engine loop access it from the asyncio event loop (no threading issue). Scan-now is a "fire and signal" — the endpoint returns immediately, the engine picks up the flag within 5s.

---

## 2026-07-06 (later) — Configurable Windows + Amount-Based SL

**What changed**
- **New per-session settings:** `entry_window_end` (default "10:30"), `square_off_time` (default "15:30"), `sl_amount_rupees` (default 900). Time settings are HH:MM strings, validated server-side (entry 09:17–15:00, square-off 09:30–15:30).
- **Engine:** the loop now calls `_orb_trigger_poll_sync` every cycle until 15:30; the poll gates each session by its own `entry_window_end` and marks that session's WAITING candidates WINDOW_CLOSED itself (`_orb_window_close_sync` deleted). `_orb_outcome_poll_sync` auto-squares-off a session's OPEN trades once IST time ≥ its `square_off_time` (exit at live LTP, remark "Auto square-off at HH:MM") — this also fixes the old EOD gap where trades stayed OPEN. `_orb_window_phase(settings)` is session-aware for the UI phase chip. `_orb_parse_hhmm()` helper parses settings times with fallbacks.
- **New SL basis `AMOUNT`:** `resolve_stop_loss()` in core/orb_simulator.py takes optional `amount`/`quantity`; SL = entry ∓ amount/qty snapped to tick. The bench-range validation is skipped for AMOUNT (₹-risk stop isn't tied to the 09:15 candle); direction + positive-price checks still apply. Trigger poll and backtest now compute qty BEFORE resolving SL. Valid in `default_sl_basis` ("AMOUNT") and the per-candidate sl-basis endpoint.
- **Backtest** honors `entry_window_end` (breakout scan range) and `square_off_time` (outcome scan end + exit fallback candle).
- **Frontend:** settings panel has SL amount ₹ input, two `<input type="time">` fields (entry close / auto square-off), and "Fixed ₹ amount" in both the default-SL select and the per-candidate dropdown (`_slOpts`/`_slLabel`).

**Caveats:** capture time (09:16) is intentionally NOT configurable — it anchors to the 09:15 ORB candle. `in_entry_window`/`in_tracking_window` in core/orb_simulator.py still carry the old hardcoded times but are no longer imported by main.py (only used by old tests). All 61 tests in `test_orb_simulator.py` pass with the extended resolver signature.

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
| `POST /api/simulator/scan-now` | `POST /simulator/scan-now` | POST | Queues immediate rescan; 400 if session at max_slots |
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
| `buy_min_chg_pct` | 1.0 | Min % gain from prev close to qualify as BUY candidate |
| `sell_min_chg_pct` | 1.0 | Min % drop from prev close to qualify as SELL candidate |
| `auto_trigger_count` | 5 | Top N candidates per side auto-entered at capture price; 0 = disabled |
| `rescan_interval_min` | 5 | Re-scan every N minutes within entry window; 0 = single scan only |

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
