# Plan: Strategy Lab — paper strategy-experiment page (Strategy 1 = "Day-Range Breakout (10:15)")

> Chosen names: page = **Strategy Lab** (`public/strategy_lab.html`); first experiment = **"Day-Range Breakout (10:15)"**; registry id `day_range_breakout`; strategy session id `strat_day_range_breakout`.

> NOTE: this file previously held the **OI Support/Resistance plan**. That plan is preserved in the conversation and will be written to `agent-artifacts/oi-support-resistance-plan.md` when we leave plan mode. This file now holds the Strategy Lab plan.

## Context

The user wants a new **paper-trading strategy tool** on its own page (`public/nifty_strategy.html`), built to host *multiple experiments over time* (Strategy 1 first). Strategy 1:

- **Runs automatically at 10:15 AM every trade day.**
- **Phase 1 — candidate selection:** bullish BUY candidates when order-book **buy% > 55%**, bearish SELL candidates when **sell% > 55%**.
- **Phase 2 — entry rules:** a BUY fills only when price rises **above the day's high** (locked at scan time); a SELL fills only when price falls **below the day's low**. It keeps listening for that breakout **all day until EOD**.
- **Universe:** the user curates the stock list themselves in the admin **Stock Inventory** page (`/mgmt/stock-inventory.html`) — this tool consumes that list.

### Why this is mostly configuration, not a new engine

The existing **ORB simulator engine** already implements Phase 1 + Phase 2 exactly (confirmed by exploration):
- Capture classifies BUY when `buy_pct >= dom_min_pct` / SELL when `sell_pct >= dom_min_pct` (`main.py:8023-8028`); `buy_pct`/`sell_pct` = order-book buy-qty vs sell-qty from the FULL quote (`main.py:7897-7909`). → set `dom_min_pct = 55`.
- Entry fills on `ltp > bench_high` (BUY) / `ltp < bench_low` (SELL) (`main.py:8215`), where `bench_high/bench_low` are the true intraday day-high/low locked at scan (`main.py:8017-8069`). → exactly the spec.
- The loop captures each session at its own `entry_window_start` (`main.py:8482-8507`). → set `10:15`.
- Manual square-off already exists (`POST /simulator/square-off`, `main.py:8746`) but is scoped to the logged-in uid session — needs a strategy-scoped variant.
- Inventory lists resolve via `stock_universe_get(conn, source)`; `_inventory_movers_sync` (`main.py:5494-5517`) shows how to turn inventory symbols → tradable EQ tokens via `_load_all_eq_stocks()`.

So Strategy 1 = the ORB engine pointed at a dedicated **shared strategy session** with: scan 10:15, dom 55%, **no profit target**, **manual exit + EOD square-off 15:30**, universe = a curated inventory group.

### Decisions locked with the user
1. **Paper only** — simulated, no real Angel One orders.
2. **Exits** — **no profit target**; **manual exit** (per-position button) + forced EOD square-off at 15:30. Stop-loss is a user setting.
3. **Settings exposed on the page** — stock group (FnO / Nifty 500 / Nifty 50 / curated inventory), stop loss, price range.
4. **New page**, global/shared auto-run (not login-gated) — the strategy runs once per trade day for everyone; stock list curated centrally in Stock Inventory.
5. **"Trending"** = the >55% buy/sell dominance selection in Phase 1 (no separate momentum layer); the stock pool itself is user-curated in Stock Inventory.

### Flagged for veto
- **Live-dominance re-check at trigger:** ORB currently *also* re-checks that dominance still ≥ threshold at breakout time before filling (`main.py:8205-8213`). The literal spec fills on **price breakout alone**. Plan: add a per-session `require_live_dom` flag, default **off** for the strategy session (pure price breakout), leaving ORB's own behavior unchanged.
- **Default universe** = the curated inventory group (`favorites`); FnO/Nifty500/Nifty50 also selectable.
- **entry_window_end = 15:15** (listen all day, stop just before square-off).

## Files to modify

### 1. `ai_engine/main.py` — engine reuse + strategy layer
- **Strategy registry** (module constant) — a dict of experiments, e.g. `_STRATEGIES = {"day_range_breakout": {"session": "strat_day_range_breakout", "label": "Day-Range Breakout (10:15)", "defaults": {...}}}`. Keeps the page extensible (add rows for future experiments).
- **Seed on startup** (near the sim-loop start, `main.py:551`): for each registered strategy, if no settings rows exist for its session, `orb_upsert_settings(conn, defaults, user_id=session)`. Defaults: `entry_window_start="10:15"`, `entry_window_end="15:15"`, `square_off_time="15:30"`, `dom_min_pct="55"`, `target_rupees="0"` (no target), `universe="inv_favorites"`, `default_sl_basis="DAY_SMART"`, `price_min`/`price_max`, `require_live_dom="0"`. Idempotent so admin edits persist. This makes the background loop (`orb_list_setting_users`) auto-capture it at 10:15 with **no loop change**.
- **Inventory-backed universe** in `_orb_capture_sync` universe filter (`main.py:7958-7987`): add branch for `universe` values like `"inv_favorites"` / `"inv_nifty500"` → `pool = [s for s in _load_all_eq_stocks() if s["symbol"].upper() in set(stock_universe_get(conn, source))]` (mirror `_inventory_movers_sync:5509-5510`). Add these keys to `_ORB_VALID_UNI` (`main.py:7838`). Existing `all_fno/nifty500_fno/nifty50` still work for the group selector.
- **No-target mode:** where target is computed at entry (`_orb_trigger_poll_sync:8254-8256`) and checked at outcome (`_orb_outcome_poll_sync` + `_orb_check_out`), treat `target_rupees <= 0` as "no target" — don't set/serve a `target_price` and skip the TARGET_HIT branch. Position sizing (`floor(capital/price)`) is unaffected. SL and square-off still apply.
- **`require_live_dom` flag:** gate the trigger-time dominance re-check (`main.py:8205-8213`) behind `st.get("require_live_dom")`; default preserves current ORB behavior for the `""`/user sessions, off for the strategy session.
- **Strategy endpoints** (thin wrappers over existing builders, resolving `sess` from `_STRATEGIES[id]["session"]` instead of the uid):
  - `GET /strategy/list` → registered experiments + live counts.
  - `GET /strategy/state?id=` → reuse the existing `/simulator/state` candidate/trade/summary builder with the fixed session id.
  - `GET/POST /strategy/settings?id=` → `orb_get_settings` / validated `orb_upsert_settings` limited to the exposed keys (universe, sl basis/amount, price_min/max, and optionally scan time & dom_min_pct).
  - `POST /strategy/square-off` (body `{id, trade_id}`) → same square-off logic as `main.py:8746` but session = the strategy session (no uid ownership check).

### 2. `routes/stockRoute.js` — proxy the new routes
Add proxies mirroring the `/api/simulator/*` ones: `GET /api/strategy/list`, `GET /api/strategy/state`, `GET|POST /api/strategy/settings`, `POST /api/strategy/square-off`. No auth needed (global/shared), forwarding query/body straight through (pattern: the existing `/api/simulator/*` routes).

### 3. `public/nifty_strategy.html` — new page
Mirror `stock_intraday_simulator.html`'s dark theme, layout, and render functions (candidate table + trades table + P/L summary + phase strip), trimmed for this strategy.
- **Header**: title "Nifty Strategy Lab", strategy selector (one entry now, built for more), refresh, SEBI disclaimer line.
- **Settings panel** (the three the user asked for): **Stock group** dropdown (FnO / Nifty 500 / Nifty 50 / Curated Inventory), **Stop loss** (basis: DAY_SMART / VWAP / Flat ₹ + amount field shown when Flat — reuse the matrix's `_toggleSlAmount` fix), **Price range** (min/max). Read-only info chips for the fixed rules (Scan 10:15 · Buy/Sell dominance > 55% · No target · Manual exit · Square-off 15:30). "Save settings" → `POST /strategy/settings`.
- **Candidates**: WAITING (watching for day-high/low breakout) vs TRIGGERED, with side, ltp, bench_high/bench_low, buy%/sell%. SEBI-safe labels ("Bullish setup"/"Bearish setup", "reference level").
- **Trades**: OPEN positions each with a **"Square off"** button → `POST /strategy/square-off`; closed rows show P/L.
- **Polling** ~7s; pause on `document.hidden`. EOD state after 15:30.
- SEBI: no buy/sell/entry directives in copy; one-line disclaimer.

### 4. `public/mgmt/stock-inventory.html` — (verify only)
Confirm the user can add their curated symbols to the `favorites` source there. If the page lacks a `favorites` tab/import, add one (import uses the existing `POST /api/stock-inventory/import?source=favorites`). *(Confirm during implementation; may be zero-change.)*

### 5. SDD context (mandatory)
Create `agent-artifacts/context/nifty-strategy-lab.md` (engine reuse, strategy registry, inventory universe, no-target + manual-exit, session model) and add a row to `agent-artifacts/context/index.md` (Status `active`).

## Out of scope
- No real/live orders (paper only).
- No new charting.
- No change to the existing ORB simulator's behavior for the `""`/user sessions (new flags default to current behavior).
- No automated sector-exclusion — the user curates the list in Stock Inventory.
- Only one experiment wired now; the registry/page are structured to add more later.

## Verification
1. `python -m py_compile ai_engine/main.py`; `node --check routes/stockRoute.js` (from repo root).
2. Restart Python + Node (or `pm2 restart tradezen-python tradezen-node`).
3. In `/mgmt/stock-inventory.html`, import a handful of symbols into `favorites`.
4. With `SIM_FORCE_WINDOW=1` (bypasses time gates), open `/nifty_strategy.html`:
   - Confirm the strategy captures candidates from the curated list; BUY candidates show `bench_high` above ltp, SELL show `bench_low` below.
   - Confirm a candidate fills only after ltp crosses its `bench_high`/`bench_low` (log line `[ORB-SIM] … (strat_breakout_1015)`), with **no target** on the resulting trade.
   - Click **Square off** on an open trade → it closes at live LTP with P/L.
   - Change Stock group / Stop loss / Price range in settings → `POST /strategy/settings` persists and next capture reflects it.
5. Confirm the existing `stock_intraday_simulator.html` and Matrix pages are unchanged (their sessions don't see the new flags/universe).
6. Confirm `target_rupees=0` path serves no `target_price` and never marks TARGET_HIT.
