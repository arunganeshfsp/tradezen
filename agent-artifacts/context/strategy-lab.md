# Context: strategy-lab

**Files:**
- `public/strategy_lab.html` — the page (global, not login-gated)
- `ai_engine/main.py` — `_STRATEGIES` registry, `_seed_strategies()`, inventory universe in `_orb_capture_sync`, `require_live_dom` gate, `/strategy/*` endpoints, `strategy` param on `/simulator/state` and square-off
- `ai_engine/core/orb_simulator.py` — no-target handling
- `ai_engine/storage/sqlite_store.py` — `require_live_dom` default
- `routes/stockRoute.js` — `/api/strategy/*` proxies + `strategy` passthrough on `/api/simulator/state`

**Last updated:** 2026-08-09 (added reversal experiment)

---

## 2026-08-08 — Strategy Lab (Strategy 1: Day-Range Breakout)

**What it is**
A paper strategy-experiment page layered on the existing ORB simulator engine. Each experiment is one dedicated **shared ORB session** (its `user_id`) seeded with a fixed config that the background loop auto-captures at its own `entry_window_start`. Built to add more experiments later (add a row to `_STRATEGIES`).

**Strategy 1 — `day_range_breakout`** (session `strat_day_range_breakout`):
- Scans at **10:15**. Bullish (buy% > 55%) reference the day's high, bearish (sell% > 55%) the day's low; a setup activates only when price crosses that level (existing `bench_high`/`bench_low` breakout — no engine rule change).
- **No profit target** (`target_rupees=0`), **manual exit** (per-position Square off) + 15:30 auto square-off, stop-loss configurable.
- Universe = **curated Stock Inventory `favorites`** by default (`inv_favorites`); FnO / Nifty 500 / Nifty 50 also selectable.
- Listens until `entry_window_end=15:15`.

**How it reuses the ORB engine (no new tables/engine)**
- `_STRATEGIES` registry + `_seed_strategies()` (called at startup, before the sim loop) idempotently upsert the session's settings so `orb_list_setting_users` → the loop captures it at 10:15. Admin edits persist (seed only when no rows exist).
- `_orb_capture_sync` gained an **inventory universe branch**: `universe="inv_<source>"` resolves via `stock_universe_get(conn, source)` against `_load_all_eq_stocks()` (mirrors `_inventory_movers_sync`). Capture now builds per-session pools first, then quotes the **union** of tokens once (so curated non-F&O stocks get quotes too).
- **No-target:** `target_levels` returns (0,0) when `target_rupees<=0`; `check_outcome` skips TARGET_HIT when `target_price` is falsy. Backward compatible (>0 unchanged).
- **`require_live_dom`** setting (default `"1"` = existing behavior). Strategy sets `"0"` so it fills on **price breakout alone** (the trigger-time dominance re-check is gated by this flag).

**Endpoints**
- `GET /strategy/list` — registered experiments + today's live counts.
- `GET|POST /strategy/settings?id=` — read / validated write (universe, sl basis/amount, price range, dom, slots, cap) to the strategy session.
- `GET /simulator/state?strategy=<id>` — reuses the whole simulator state builder against the strategy session.
- `POST /simulator/square-off` with body `{trade_id, strategy}` — strategy-scoped manual exit (bypasses the uid ownership check; ownership is the registry).
- Node proxies: `/api/strategy/list`, `/api/strategy/settings` (GET/POST), `strategy` passthrough on `/api/simulator/state`; square-off reuses `/api/simulator/square-off` (body forwards `strategy`).

**Known caveats**
- Global/shared: settings are edited centrally (no per-user scope). No auth on the page or `/strategy/*`.
- If `favorites` is empty the strategy simply captures nothing until stocks are imported at `/mgmt/stock-inventory.html` (Favorites tab, CSV import).
- Curating favorites is **CSV import (replace) only** today — no individual add-symbol UI yet.
- `_NIFTY50_SYMS` (the built-in nifty50 universe) is still an approximate static list; the strategy sidesteps this by using the curated inventory list.
- Sizing still uses `SIM_CAPITAL` (₹1L) like the simulator; scan time / dom% not exposed on the page (fixed via seed), only group / SL / price range are editable per the request.

**Open issues**
- No EOD export on this page yet (the Matrix page has one; could be ported).

---

## 2026-08-09 — Experiment #2: Day-Range Reversal (stop-and-reverse)

**What it is** — `day_range_reversal` (session `strat_day_range_reversal`), a second tab (auto-listed via `/strategy/list`). Same dominance selection + curated universe, but:
- **Scan 09:18 (configurable on the page)**; `entry_mode="reversal"`.
- **Leg 1 — immediate entry at scan** (not a breakout): buy candidate ⇒ long, sell candidate ⇒ short, filled at scan LTP.
- **Leg 2 — stop-and-reverse at the opposite day-extreme:** a long that reaches the day-low is closed (`outcome="REVERSED"`) and a short is opened at that level; a short that reaches the day-high flips to a long. One reversal per stock/day.
- **No target and no stop loss** (`target_rupees=0`, `default_sl_basis="NONE"`) — closes only on manual exit or 15:30 square-off.

**Engine changes (all gated so breakout/other sessions are untouched):**
- New setting `entry_mode` (default `"breakout"`; coercion-free string in `ORB_SETTING_DEFAULTS`).
- `_orb_trigger_poll_sync`: `immediate = entry_mode=="reversal"` skips the breakout gate (fills at ≈scan LTP). `default_sl_basis=="NONE"` ⇒ `sl_price=None, sl_pts=0`, skip `_orb_resolve_sl`/`_orb_sl_pts`.
- `_orb_outcome_poll_sync`: builds `cand_by_key`; for a reversal-session trade where `direction==candidate.side` (leg 1) that crosses the opposite extreme (`bench_low` for a long, `bench_high` for a short), marks it `REVERSED` and inserts an opposite leg-2 trade (no SL/target). **Leg identity is derived (no schema change):** leg 1 = `direction==candidate.side`; leg 2 = opposite, never reverses.
- `orb_simulator.check_outcome`: SL now guarded by truthiness (like target), so `stop_loss_price` None/0 never fires `SL_HIT`.
- `_StrategySettingsBody`: added `entry_window_start` (configurable scan time, validated 09:15–14:00); `strategy_post_settings` allows `default_sl_basis="NONE"`.

**Frontend:** Scan-time field; `None` SL option; `renderRuleChips` branches on `entry_mode`; trades table shows SL "none" when absent and a `REVERSED` badge (amber).

**Caveats**
- Leg 2 is inserted directly in the outcome poll (not gated by `max_slots`, which only caps leg-1 entries); `max_slots=50` covers `candidate_cap` on both sides. `REVERSED` isn't in the summary `counts` buckets but its P/L is in `total_pnl`.
- Reversal candidates flip to TRIGGERED almost instantly (immediate entry), so the "Setups" table mostly shows TRIGGERED; the action is in the Trades table.
- The reverse trigger reads `_orb_ltp_cache` (same source as the engine's SL/target checks). Once all candidates have triggered there are no WAITING rows, so the background trigger poll stops quoting those tokens — open-trade LTP is then refreshed mainly by the state endpoint being polled (page open). Pre-existing simulator characteristic; the reversal detects the day-extreme within a poll of the page being watched, and always resolves at the 15:30 square-off regardless.
- Only breakout + reversal wired; registry + tabs ready for more.
