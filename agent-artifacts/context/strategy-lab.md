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

## 2026-08-10 — Nifty 50 group sourced from Stock Inventory

- Both strategies now **default `universe="inv_nifty50"`** (was `inv_favorites`) — the curated Nifty 50 list from `/mgmt/stock-inventory.html` → Nifty 50 tab (`stock_universe_get(conn, "nifty50")`), not the static `_NIFTY50_SYMS`.
- `_STRATEGY_VALID_UNI` now `{all_fno, nifty500_fno, inv_nifty50, inv_favorites}` (dropped static `nifty50`). Strategy Lab group dropdown: "Nifty 50 (Inventory)" = `inv_nifty50`, "Favorites (Inventory)" = `inv_favorites`, plus F&O / Nifty 500. Resolved via the existing `inv_<source>` capture branch against `_load_all_eq_stocks()`.
- Idempotent seeding: existing installs keep their saved universe — pick "Nifty 50 (Inventory)" in each tab's settings, or the new default applies on a fresh seed. Empty inventory ⇒ no candidates until the Nifty 50 list is imported.

## 2026-08-10 — Removed dominance + price-range filters; seed now reconciles engine keys

- Both strategies: **dominance gate off** (`dom_min_pct=0` — every stock in the group is a candidate, side by whichever of buy%/sell% dominates) and **price range off** (`price_min=0`, `price_max=100000000`). The `buy_min_chg_pct` (≥1% move) filter and everything else stay.
- Strategy Lab settings panel: **Price min/max fields removed** (and dropped from the save payload / load). Rule chip shows "Side by buyer/seller dominance" when `dom_min_pct=0`.
- **`_seed_strategies()` reconciliation:** on every startup it now re-applies the registry's *engine-managed* keys to existing sessions, preserving only user knobs `_STRATEGY_USER_KEYS = {universe, default_sl_basis, sl_amount_rupees, entry_window_start}`. So registry default changes (filters, windows, VWAP SL, etc.) propagate on restart without a manual re-seed, while the user's group/SL/scan choices persist. `_StrategySettingsBody` still accepts price/dom keys (harmless) but the UI no longer sends them.

## 2026-08-12 — Trades table: Day High / Day Low (scan) + Unrealized P/L columns

- Frontend-only change to `public/strategy_lab.html` (no backend touched). The Simulated Trades table gained three columns: **Day High**, **Day Low** (green/red), and **Unrealized**. Header + empty-state colspan now `13`.
- **Day High / Day Low = scan-locked range** (`bench_high`/`bench_low`), *not* the trade row's `day_high_at_entry`/`day_low_at_entry` (which are the live session H/L at trigger). Source: `renderState` builds `benchBySym = {symbol → {h,l}}` from `d.candidates` (same `/simulator/state` payload) and passes it to `renderTrades(trades, benchBySym)`. Lets you eyeball that a BULLISH Fill ≥ Day High and a BEARISH Fill ≤ Day Low. Both legs of a reversal share the candidate's bench (correct).
- **Unrealized** column: OPEN trades only, gross mark `(isBuy? live_ltp-trigger : trigger-live_ltp) * qty` via existing `_pnlStr`/`_pnlCls`; closed trades show `—`. The existing **P/L** column now shows `—` for OPEN (was a misleading `+₹0.00`) and the realized value once closed.
- Status-strip "Net P/L" unchanged (still realized-only from backend `summary` — unrealized not folded in).
- **Setups table:** dropped the **Dominance** column (dominance gate is off — `dom_min_pct=0`) and the single "Ref level" column; added explicit **Day High** / **Day Low** (green/red `bench_high`/`bench_low`) for parity with the Trades table. `renderCands` no longer reads `buy_pct`/`sell_pct`/`live_*_pct`. Column count stays 8: `Setup | Symbol | Change | Scan ₹ | Live ₹ | Day High | Day Low | Status`.

## 2026-08-12 — Testing phase: cover the whole Nifty 50 inventory (no 20-cap)

- Both strategies: `candidate_cap` 20 → **50** (per side) and breakout `max_slots` 20 → **50** (reversal was already 50). With the dominance gate off, every stock in the group becomes a candidate on one side, so 50/50 lets the full Nifty 50 inventory through instead of the top 20. Validation ceilings already allow it (`candidate_cap` 5–100, strategy `max_slots` 1–50).
- Engine-managed keys, so `_seed_strategies()` reconciles them onto existing sessions on restart (not `_STRATEGY_USER_KEYS`). Reversal leg-2 trades are still inserted directly in the outcome poll (not counted against `max_slots`).

## 2026-08-12 — EOD CSV export on the Trades card

- Frontend-only (`public/strategy_lab.html`). Added a **↓ Export CSV** button on the Simulated Trades card header (`exportTrades()`), ported from `stock_intraday_simulator.html`'s pattern with `_csvVal`/`_downloadCsv` (UTF-8 BOM, educational-disclaimer footer). Works any time; intended for EOD capture.
- Exports the current per-strategy `/simulator/state` payload — cached in new module var `_lastState` (set in `renderState`). Columns: Date, Strategy, Symbol, Direction, **Day High/Day Low (scan)** (joined from `d.candidates` `bench_*`), Entry Time, Fill, SL Basis/Price, Target, Qty, Investment, Outcome, Live/Exit, Exit Time, **Realized P/L** (blank while OPEN), **Unrealized P/L** (live mark for OPEN), Return Amount, Remarks. Filename `strategy_lab_<id>_<date>.csv`.
- No open-slot cap on export; empty-trades alerts instead of downloading.

## 2026-08-12 — Outcome poll self-refreshes open-position prices (no page dependency)

- `_orb_outcome_poll_sync` now fetches fresh quotes for the union of OPEN-trade tokens (`_orb_raw_quotes(smart_s, open_toks)`, which updates `_orb_ltp_cache` as a side effect) **before** the resolution loop. Runs every 5s in the sim loop's executor thread.
- **Fixes the documented reversal caveat:** once every candidate flips to TRIGGERED the trigger poll no longer quotes those tokens, so previously `_orb_ltp_cache` only refreshed while `/simulator/state` was polled (page open). Now reversal flips, SL/target, and trailing SL are all detected server-side regardless of any open page. Both breakout and reversal benefit.
- Load: ≤ the group size (≤50 tokens) per 5s; net API use is comparable since the trigger poll stops quoting the same tokens once they trigger. No-op when `_get_smart()` is unavailable. Validated by `validate_tabs.py` (gate/fill/reverse invariants, 30/30 pass) — logic unchanged, only price freshness improved.

## 2026-08-12 — Breakout reshaped into an opening-range model (09:20 lock → watch all 50 → 10:15 close)

- **Breakout strategy only** (reversal untouched). Registry defaults changed: `entry_window_start` 10:15 → **09:20** (opening-range lock — day high/low frozen from the 09:15–09:20 candles via the existing 1-min correction), `entry_window_end` 15:15 → **10:15** (selection window closes; no new entries after — open trades still ride to manual/15:30 via the outcome poll, which runs until 15:30), and added **`buy_min_chg_pct: "0"`** so the ≥1% pre-move gate is off and the **whole Nifty 50 is captured as WAITING candidates** at 09:20. The only capture filter left is price range (also off). Blurb + hero copy rewritten to describe the ORB model.
- **Seeding nuance:** `entry_window_end` and `buy_min_chg_pct` are engine-managed → `_seed_strategies()` reconciles them on `pm2 restart tradezen-python`. **`entry_window_start` is a `_STRATEGY_USER_KEY`** (preserved), so an existing install keeps its saved 10:15 — the user must set **Scan time = 09:20** in the Breakout tab once (fresh seeds get 09:20). No migration shim added (per conventions).
- **Frontend (`strategy_lab.html`):** rule chips now show `Lock range <09:20>` + `Select until <10:15>` for breakout (reused the former reversal-only null slot); reversal still shows `Scan` + `Reverses…`. Setups empty-state message is now generic (reads `_settings.entry_window_start`, no hard-coded 10:15). The Setups table (Day High/Day Low columns from the earlier change) now lists all ~50 stocks.

## 2026-08-12 — Third experiment: Day-Range Breakout (10:15) as a separate strategy

- New registry entry **`day_range_breakout_1015`** (session `strat_day_range_breakout_1015`, label "Day-Range Breakout (10:15)") — a clone of the 09:20 breakout but **locks the range at 10:15 and listens until 11:30** (`entry_window_start=10:15`, `entry_window_end=11:30`). Same everything else: whole Nifty 50 (`buy_min_chg_pct=0`, `candidate_cap`/`max_slots=50`, `inv_nifty50`), VWAP SL, no target, manual/15:30 square-off, `entry_mode=breakout`.
- The **existing 09:20 breakout was left untouched** and only **relabelled to "Day-Range Breakout (09:20)"** (was "(10:15)") so the two don't get confused — same id/session, no data migration.
- Zero plumbing changes: `_seed_strategies`, `/strategy/list`, `/strategy/settings`, `/simulator/state`, the capture/trigger/outcome loop, and the frontend tabs are all `_STRATEGIES`-driven, so the new tab appears and auto-captures at 10:15 on its own. Each session captures at its own `entry_window_start`. Now three tabs total.
- Hero copy on `strategy_lab.html` generalised (no longer pins to one strategy) so it doesn't go stale as experiments are added.

## 2026-08-12 — Status-strip P/L fixed to live book + positive/negative range

- **Bug:** the header "Net P/L" used the backend `summary.total_net_pnl`, which is `Σ(pnl − transaction_cost)`. Open trades store `pnl=0`, so it booked round-trip brokerage+STT on every still-open position while ignoring their unrealized gains → a book that was well in profit showed a large negative (e.g. −₹2,027 with 22 open trades mostly green).
- **Fix (frontend `renderState`):** the header is now computed from `d.trades` directly — OPEN positions mark to `live_ltp` (unrealized `(isBuy?live-fill:fill-live)*qty`), closed use realized `t.pnl`. So it matches the Unrealized column exactly. Relabelled **"Net P/L" → "P/L"** (it's gross live book, not net-of-cost).
- **Added the +/- range:** `▲ +₹<gains>` and `▼ −₹<losses>` = sum of every trade currently in profit vs. in loss (same per-trade figure), for at-a-glance tracking.
- Backend `summary` untouched (only the strategy page consumed `total_net_pnl`; the CSV export already uses per-trade realized/unrealized, not the summary). `win_rate` still realized/TARGET_HIT-based → shows 0% for these no-target strategies (pre-existing, not in scope).

## 2026-08-12 — ▲/▼ range redefined as intraday P/L high/low water mark (server-tracked)

- The ▲/▼ next to P/L now shows the **day's peak profit and max drawdown** (running max/min of the total P/L equity curve, both seeded at 0) — not the earlier sum-of-positive / sum-of-negative snapshot. Requested model: start at 0/0, ratchet `day_high` up when total P/L exceeds it, `day_low` down when it drops below.
- **Persistence:** new table **`orb_pnl_hwm(user_id, date, pnl_high, pnl_low)`** + helpers `orb_pnl_hwm_get` / `orb_pnl_hwm_update` (`sqlite_store.py`). The **outcome poll** (`_orb_outcome_poll_sync`, every 5s server-side) computes each session's live total P/L (open marked to the refreshed `_orb_ltp_cache` + realized on closed) and folds it into the marks — so peak/trough persist across page reloads and update even with no page open. Date-keyed → auto-resets daily. A `pm2 restart` mid-day keeps them (DB-persisted, not in-memory).
- `simulator_state` reads the marks into `summary.pnl_day_high` / `pnl_day_low` (short-lived conn, since the main conn closes early). Frontend `renderState` displays `▲ +₹<high>` / `▼ −₹<low>`, **bracketed by the live total** (`Math.max/min(mark, liveTotal, 0)`) so the current P/L always sits within the shown range even if the 5s mark lags the page's fresher fetch.

## 2026-08-12 — Day-summary block prepended to the CSV export

- User wanted the P/L figures captured at EOD via the **existing ↓ Export CSV** (explicitly *not* a dedicated page / not `reports.html`). `exportTrades()` now computes the same day figures as the strip and passes `summaryLines` to `_downloadCsv(headers, rows, filename, summaryLines)`, which prepends a `DAY SUMMARY` block then a `TRADES` header before the per-trade table (UTF-8 BOM + disclaimer footer unchanged).
- Summary rows: Strategy, Date, Total P/L, Day's peak P/L, Day's lowest P/L (both bracketed by live total, same as the strip), Total gains, Total losses, Trades / Open / Closed counts. `pnl_day_high/low` come from `d.summary` (the hwm table). Frontend-only; export is still user-triggered (click at EOD after square-off for the settled numbers).

## 2026-08-13 — 09:18 tab converted from Reversal to Breakout

- User re-flagged the 09:18 tab firing entries **inside** the locked range (bearish short filling above the day low, bullish long below the day high). This was the **reversal** strategy behaving as designed (immediate entry at scan + stop-and-reverse), but the user wants its **first entry to follow the same trigger rule as the 10:15 tab** — fill only when price breaks the locked range.
- **Change (registry only, `_STRATEGIES["day_range_reversal"]`):** `entry_mode` `"reversal" → "breakout"`; relabelled **"Day-Range Reversal (09:18)" → "Day-Range Breakout (09:18)"**; blurb rewritten to the breakout description. Kept the id/session (`day_range_reversal` / `strat_day_range_reversal`) and `entry_window_end=15:15`, `default_sl_basis=NONE` (no SL) so today's captured data and the user's preserved knobs stay intact.
- `entry_mode` is **engine-managed** (not in `_STRATEGY_USER_KEYS`), so `_seed_strategies()` reconciles it to `breakout` on `pm2 restart tradezen-python` — no manual DB edit. The two gate points (`immediate = entry_mode=='reversal'` at the trigger loop, and the stop-and-reverse leg at the outcome poll) both go inert for this session automatically.
- Frontend needs no per-tab edit: the rule chips key off `s.entry_mode` (`strategy_lab.html:313`), so the tab now renders the breakout chips (Lock range / Select until, Entry above day-high / below day-low). Hero copy dropped the stale "stop-and-reverse" mention.
- **Caveat:** the reversal engine path (immediate entry + stop-and-reverse, `main.py:8313` & `:8490`) is retained as a setting-driven capability but no strategy now uses it. Trades already filled today under the old immediate mode stay open until manual close / 15:30 square-off; only new triggers use the breakout gate.

## 2026-08-13 (corrected) — 09:18 tab = Break & Reverse (breakout first entry + one-time reversal)

- Superseded the earlier same-day "convert 09:18 to pure Breakout" note. User wants to **keep the reversal**, but the **first entry must be a breakout** (not the old immediate-at-scan fill). Confirmed logic: freeze day high/low at 09:18 → long when price breaks **above** day high / short when it breaks **below** day low → if that leg later reaches the **opposite** extreme, flip **once** (one reversal per stock/day), no target, no SL, exit manual/15:30.
- This is a third `entry_mode`: **`breakout_reverse`** on `_STRATEGIES["day_range_reversal"]` (label now "Day-Range Break & Reverse (09:18)"). It reuses the two existing gate points without new engine logic:
  - **First-entry gate** (`main.py:8346`): `immediate` stays `entry_mode=='reversal'` only, so `breakout_reverse` falls through to the breakout condition `(BUY & ltp>bench_high) | (SELL & ltp<bench_low)` — waits for the level.
  - **Reverse leg** (`main.py:8490`): condition widened to `entry_mode in ("reversal","breakout_reverse")`. Leg-1 (`direction==cand.side`) reverses at the opposite bench extreme; leg-2 (`direction!=cand.side`) never reverses → "once and done". Candidate is marked TRIGGERED on leg-1 fill so the trigger loop can't re-fire it; only the outcome poll creates the reverse leg.
- The three entry_mode combos now: `breakout` (breakout entry, no reverse — 09:20 & 10:15), `breakout_reverse` (breakout entry + reverse — 09:18), `reversal` (immediate entry + reverse — engine capability, no strategy uses it now).
- Frontend `renderRuleChips` (`strategy_lab.html:313`) split the single `reversal` flag into `immediate` (scan-entry copy) and `reverses` (shows "Reverses once at opposite day-extreme"); `breakout_reverse` shows breakout-entry chip + reverses chip. Hero copy restored to "breakout and break-and-reverse studies".
- `entry_mode` is engine-managed (reconciled by `_seed_strategies` on `pm2 restart tradezen-python`). Trades already open today under the old immediate mode stay until manual/square-off; new triggers use the breakout gate.
