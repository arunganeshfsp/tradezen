# Context: s1-monitor

**Files:** `public/s1_monitor.html`, `public/stock_s1_monitor.html`, `ai_engine/core/s1_monitor.py`, `ai_engine/main.py` (`_s1_monitor_state()`)
**Last updated:** 2026-10-14 (OR accuracy fix, live premium, paper-trading hookup)

---

## 2026-10-14 — OR accuracy, live premium, "Add to Trade Lab"

User reported: "ORB is not accurate. Premiums are not correct." Plus a request to let a fired signal be added to paper trading.

**Bug 1 — OR was a single candle, not the 09:15–09:30 range.** `S1StrategyMonitor.check_s1_setup()` locked `or_high`/`or_low` from `candles.iloc[0]` — just the first 5-min bar (09:15–09:20) — and marked `or_formed = True` immediately, even before 9:30 had elapsed. Also, `main.py::_s1_monitor_state()` instantiates a **new** `S1StrategyMonitor()` on every poll (every 5s from the frontend), so the `or_formed` instance flag never actually persisted across calls anyway — every poll re-derived OR from scratch off that one candle.
Fixed in `core/s1_monitor.py`: OR is now `high.max()`/`low.min()` across all candles with index time `< 09:30` (the real opening-range window), recomputed every call, and `or_formed` is only `True` once the current time has actually reached `OR_COMPLETE_HOUR` (9:30).

**Bug 2 — premium was a synthetic formula, not a market price.** `_estimate_premium()` computed `intrinsic + max(20, 100 - |price-strike|)` — a made-up time-value curve, never touching the actual option chain. Fixed in `main.py::_s1_monitor_state()`: after `check_s1_setup()` returns a signal, it now resolves the real CE/PE contract via `im.get_nearest_expiry()` + a lookup in `im.data` (strike + type match), then overwrites `entry_premium`/`sl`/`t1`/`capital` with the live LTP from `get_provider().get_option_ltp([token])` (same provider path paper trading uses — works for any NFO token on demand, not just WebSocket-subscribed ATM strikes). Also adds `result['option_token']`, `result['option_symbol']`, `result['expiry']`. `_estimate_premium()` in `core/s1_monitor.py` is kept only as the fallback when the live fetch fails (market closed, broker session down, contract not found).
Frontend: the hardcoded `const expiry = '26 May 2026'` in `updateSignalCard()` was replaced with `result.expiry || '—'` — it no longer goes stale every expiry week.

**Feature — "+ ADD TO TRADE LAB" button.** The `✓ TAKE` button was purely cosmetic (just toggled its own label for 3s). It's now wired: `takeTrade()` POSTs to `/api/paper/order` with `{instrument:"OPTION", symbol: option_symbol, side:"BUY", lots:1, lot_size:65, token, underlying:"NIFTY", expiry, strike, option_type}` — omitting `price` when a token is available (so the paper engine fills at a fresh live LTP) and falling back to `entry_premium` as the fill price only when no token was resolved. Requires `tz_learn_token` (same auth as `paper_trading.html`); redirects to `/learn/auth.html` if missing or on a 401. New module-level `lastSignalResult` holds the full last signal object so the handler has strike/token/premium/expiry to send. Renamed the button from "✓ TAKE" to "+ ADD TO TRADE LAB" since it now performs a real action (SEBI language rule: avoid action-directive copy) — `HOLD`/`SKIP` buttons were left as pure UI state (not wired, not renamed — out of scope for this change).

**Known related issue (not fixed — out of scope):** `core/stock_monitor.py` (`stock_s1_monitor.html`'s backend) has the identical single-candle OR bug and its own `_estimate_premium()` synthetic formula. Not touched because the user's report named only `s1_monitor.html`. Fix the same way if reported there too.

**Stale doc note:** the "SEBI Changes (2026-06-24)" section below describes a renaming pass (Entry Premium → Reference Premium, TAKE → TRACK, etc.) that does **not** match the live file as of this update — the file still had "Entry Premium", "CALL ENTRY (CE)", "TAKE/HOLD/SKIP" before today's change. Either that pass was reverted or never landed on this file. Only the TAKE button was renamed today (see above); the rest of that stale SEBI pass was left as-is since re-doing a full compliance pass wasn't part of this request.

---

## Purpose

Monitors the S1 Camarilla strategy in real-time. Entry condition: price trades below/above S1 level, then reverses with EMA + RSI confirmation. Shows a mini LightweightCharts chart with EMA 9/21 overlaid.

---

## Key State

| Variable | Purpose |
|---|---|
| `lastSignal` | Previous signal — for change detection / log dedup |
| `s1Chart` | LightweightCharts instance |
| `s1CandleSeries` / `s1Ema9Series` / `s1Ema21Series` / `s1RsiSeries` | Chart series |
| `logs` | Array of signal log entries |

---

## Session Windows (hardcoded in JS)

```javascript
PRE_MARKET_START = 9:00 IST   (9 * 60)
PRE_MARKET_END   = 9:15 IST   (9 * 60 + 15)
LIVE_START       = 9:15 IST   (9 * 60 + 15)
LIVE_END         = 13:00 IST  (13 * 60)
```

The strategy only fires in the live window (9:15–13:00). After 13:00 the monitor goes quiet.

---

## Key Functions

| Function | What it does |
|---|---|
| `getSessionStatus()` | Returns session phase + countdown |
| `calculateCountdown(target, current)` | Minutes remaining to a time boundary |
| `updateSignalCard(result)` | Renders CE/PE/WAIT card with strike + premium + SL/T1 |
| `updateReadinessScore(result)` | Checklist: EMA aligned, Supertrend, VWAP, RSI, volume |
| `addLog(...)` | Appends to signal log |
| `setCheck(id, pass)` | Sets checkmark/cross on a readiness item |

---

## API Endpoints

| Endpoint | Used for |
|---|---|
| `GET /api/s1-monitor` | Index NIFTY S1 signal |
| `GET /api/stock-monitor` | Stock-level S1 signal (`stock_s1_monitor.html`) |

---

## Trade Plan Calculation (client-side)

```javascript
const premium = result.entry_premium || 0;
const sl  = result.sl  || (premium * 0.65);   // 35% SL
const t1  = result.t1  || (premium * 1.45);   // 45% target
const maxLoss         = (premium - sl) * 65;   // 1 lot = 65 qty
const potentialProfit = (t1 - premium) * 65;
```

Lot size is hardcoded as 65 — Nifty lot size. **Must be updated if SEBI changes Nifty lot size.**

---

## Stock S1 Monitor Differences

`stock_s1_monitor.html` uses `/api/stock-monitor` instead of `/api/s1-monitor`. Accepts a stock symbol parameter. Otherwise identical layout and logic.

---

## Layout (2026-06-24 redesign)

- **4-panel symmetric grid** at top (Setup Conditions | Opening Range | Readiness Score | EMA & RSI) — collapses to 2-col at 1100px, 1-col at 580px
- **Score ring**: SVG circle with `stroke-dasharray` updated in JS via `id="scoreRing"`; label via `id="scoreLabel"` (INCOMPLETE / FORMING / SETUP READY)
- **Signal card** is hidden by default; `.waiting-card` shows until signal fires
- **Bottom grid**: signal card (3fr) + alert log (2fr) side by side, stacks on mobile
- `scorePercent` element retained (hidden) so JS doesn't throw on the old assignment
- CSS uses local variables (`--bg`, `--bg2`, etc.) for compatibility with theme.css — same palette as before but cleaner layout classes

## SEBI Changes (2026-06-24)

- "CALL ENTRY (CE)" → "CALL SETUP (CE)"
- "PUT ENTRY (PE)" → "PUT SETUP (PE)"
- "Entry Details" → "Setup Details"
- "Entry Premium" → "Reference Premium"
- "Entry Time" → "Alert Time"
- "Risk Management" → "Risk Parameters"
- "Capital Required" → "Capital Reference"
- "Max Loss" → "Max Notional Loss"; "Potential Profit" → "Notional Gain Ref"
- Action buttons: TAKE → TRACK, HOLD → WATCH, SKIP → PASS
- Hero sub text: removed "entry signals" → "live setup conditions monitoring"
- Disclaimer added at bottom
- EMA/RSI status text: removed emoji flags (🟢/🔴), plain descriptive text only

## Known Caveats

- ~~Expiry date string is hardcoded in `updateSignalCard()`~~ — fixed 2026-10-14, now reads `result.expiry` from the backend (nearest-expiry lookup).
- Lot size (65) is hardcoded — verify after SEBI lot size revisions.
- The LightweightCharts mini chart is optional — if `s1Chart` fails to init (e.g. container missing), the signal card still works.
- `getSessionStatus()` uses a manual UTC+5:30 offset calculation — not timezone-aware. Will break if server clock drifts.
- Live premium fetch (2026-10-14) adds one `get_option_ltp()` broker round-trip per poll while a signal is active (every ~5s) — acceptable at current traffic; would need caching if this page gets heavy concurrent use.
- `core/stock_monitor.py` (stock_s1_monitor.html) still has the pre-fix single-candle OR bug and synthetic premium formula — not fixed in this pass, see 2026-10-14 entry above.
