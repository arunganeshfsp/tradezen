# Context: cpr-monitor

**File:** `public/cpr_monitor.html`  
**Last updated:** 2026-06-19

---

## Purpose

Visualises CPR (Central Pivot Range) and Camarilla levels for NIFTY/BANKNIFTY on a LightweightCharts candlestick chart. Supports daily, weekly, and monthly timeframes. Shows level ladder, CPR type badge (narrow/wide/virgin), and breakout alerts.

---

## Key State

| Variable | Purpose |
|---|---|
| `_chart` | LightweightCharts instance |
| `_candleSerie` | Candlestick series |
| `_symbol` | `'NIFTY'` or `'BANKNIFTY'` |
| `_timeframe` | `'daily'` \| `'weekly'` \| `'monthly'` |
| `_levels` | `{ tc, bc, pp, r1..r3, s1..s3, width, cam:{h3,h4,l3,l4} }` |
| `_prevDay` | `{ high, low, close, date }` |
| `_candles` | Latest candle array |
| `_virginCPR` | Boolean — true if price hasn't touched CPR today |
| `_breakoutDir` | `'bull'` \| `'bear'` \| null — direction of CPR breakout |
| `_allAlerts` | Array of alert events |
| `_filterType` | Alert filter: `'all'` \| `'cpr'` \| `'cam'` |

---

## Key Functions

| Function | What it does |
|---|---|
| `fetchLevels()` | GET `/api/cpr-levels?symbol=&timeframe=` → sets `_levels`, `_prevDay`; calls `renderLadder`, `renderCamLadder`, `renderSignals` |
| `calcCamarilla(H, L, C)` | Computes H3/H4/L3/L4 client-side from prev OHLC |
| `renderLadder(ltp)` | CPR + pivot level ladder with distance from LTP |
| `renderCamLadder(ltp)` | Camarilla level ladder |
| `renderSignals(ltp)` | Breakout/alert cards based on price vs levels |

---

## CPR Type Classification

Computed server-side in Python `/cpr-levels`, based on `width` (TC − BC as % of prev close):
- `narrow` — tight CPR → trending day expected
- `medium` — moderate range
- `wide` — choppy day expected

**Virgin CPR** — if price hasn't tested the CPR zone yet today (`_virginCPR = true`), shown as a purple animated badge.

---

## Camarilla Levels (client-side)

```
H4 = C + (H − L) × 1.1 / 2
H3 = C + (H − L) × 1.1 / 4
L3 = C − (H − L) × 1.1 / 4
L4 = C − (H − L) × 1.1 / 2
```
Computed in `calcCamarilla()` from `_prevDay` — not fetched from server.

---

## Polling

- `_pollTimer` — polls `/api/price` every ~5s for live LTP
- `_levelInterval` — re-fetches levels periodically to catch mid-day updates

---

## Alert Noise Suppression (detectEvents)

The state machine in `detectEvents()` is a single `if/else-if` chain per candle, so at most one CPR event fires per candle (Virgin CPR is a separate one-time `if`). Priority: BREAKOUT > BREAKOUT_FAILURE > REVERSAL > RETEST > Camarilla.

Three rules added 2026-06-09 to kill false/contradictory alerts:

1. **BREAKOUT_FAILURE requires a prior confirmed breakout.** Gated on `_breakoutDir === 'bull'`/`'bear'`. Without this, price merely drifting back below TC (when it opened above TC, never having a body-confirmed breakout) fired phantom "bull trap" failures.
2. **Camarilla H3 (short) / L3 (long) are suppressed against an active breakout.** H3 needs `_breakoutDir !== 'bull'`, L3 needs `_breakoutDir !== 'bear'` — prevents shorting into a bull breakout / longing into a bear breakdown. `_breakoutDir` clears on failure or retest, so mean-reversion re-enables once the breakout resolves.
3. **REVERSAL reason text corrected** — "from above → bearish reversal" (Sell), "from below → bullish reversal" (Buy). Previously swapped.

## Stale OHLC Bug — Fixed 2026-06-16

### Root cause (three layers)

**Layer 1 — yfinance `^NSEI` data lag:** yfinance consistently returns the previous trading day's data one day late for the NSE spot index. On Tuesday June 16, it returns Friday June 12 data instead of Monday June 15.

**Layer 2 — No daily refresh of `trade_flow_data["prev_ohlc"]`:** This dict was fetched once at startup and never refreshed. If the server ran across midnight, the stale startup-day data was served forever.

**Layer 3 — `_cpr_levels_sync` cache poisoning:** Once `_cpr_cache` stored a stale OHLC date under today's key, it was served for the rest of the day with no staleness check — even after the data source was corrected.

### Fixes applied

**`_cpr_levels_sync` (primary fix):**
- Before serving from `_cpr_cache`, checks if the cached OHLC date ≥ `expected_prev` (most recent weekday). If stale, evicts the cache entry and falls through to a fresh fetch.
- After a fresh fetch, only writes to cache if the resulting OHLC date ≥ `expected_prev`. If SmartAPI also failed and yfinance data is still stale, the result is NOT cached — next request will retry.
- SmartAPI fallback now tries 4 combinations: `("NSE", SPOT_TOKEN, "ONE_DAY")`, `("NFO", fut_token, "ONE_DAY")`, `("NSE", SPOT_TOKEN, "ONE_HOUR")`, `("NFO", fut_token, "ONE_HOUR")` — matching the startup logic.
- On success, writes corrected OHLC back to `trade_flow_data["prev_ohlc"]` so WebSocket and trade-flow endpoint also benefit.

**`_daily_instrument_refresh` task (8:30 AM IST on weekdays):**
- Now also refreshes `prev_ohlc` with the same yfinance → SmartAPI fallback pattern.
- Resets `nifty_open` and `orb` (intraday accumulators) so they are clean for the new day.
- Does NOT reset `gift_nifty` — that is manually entered by the user pre-market and must survive the 8:30 AM task.

**`get_trade_flow()` staleness check — REMOVED (risk audit):**
- An initial version added a staleness check inside `get_trade_flow()` that called `_yf_prev_ohlc()` on the first request each day. This was removed because it could overwrite a correct SmartAPI-sourced `prev_ohlc` with stale yfinance data if called before `/cpr-levels` had a chance to correct it.

### Expected log output when fix is active
- `[CPR] Cache has stale OHLC 2026-06-12 (want 2026-06-15) — evicting, re-fetching`
- `[CPR] yfinance returned 2026-06-12, expected 2026-06-15 — trying SmartAPI`
- `[CPR] SmartAPI OHLC (NFO/ONE_DAY): H=... L=... C=... [2026-06-15]` ← success
- OR: `[CPR] OHLC still stale (2026-06-12, want 2026-06-15) — skipping cache, will retry next request` ← SmartAPI failing, keeps retrying

### What is NOT affected
- `psychology/levels` endpoint — does its own fresh yfinance fetch on every call, no shared cache.
- Weekly / monthly CPR timeframes — no staleness check applied (their data lags are expected and harmless).

---

## Option Contract CPR — Added 2026-06-17

Enter a contract like `NIFTY24000CE` in the new Option input in the selector bar. The CPR is computed from the **option's own prev-day OHLC** (the premium), not the underlying NIFTY.

**Data flow:**
- `_parse_option_symbol(sym)` — regex `(NIFTY|BANKNIFTY)\d+(CE|PE)`, returns `(underlying, strike, type)` or `None`
- `_cpr_levels_option_sync` — looks up token via `im.get_option_token(strike, type)` (nearest expiry), fetches prev-day ONE_DAY candle from SmartAPI NFO, calculates CPR. ATR = `max(close × 0.20, 5)` (rough premium ATR).
- `_candles_for_cpr_option_sync` — fetches today's FIVE_MINUTE candles from SmartAPI NFO for the intraday chart. Live LTP comes from `last.close` of the candle poll (every 30s).
- Both `_cpr_levels_sync` and `_candles_for_cpr_sync` check `_parse_option_symbol` first and delegate to the option-specific functions.
- `im.get_option_token(strike, type)` added to `InstrumentMaster` — searches `self.data` (NIFTY OPTIDX only) for nearest expiry match.

**Caveats:**
- Only NIFTY options supported (InstrumentMaster filters for `name == "NIFTY"`)
- Option must have traded on the previous day — OTM options with no trades return `"No prev-day OHLC"` error
- Weekly/monthly timeframe buttons still show but use the same daily CPR (option weekly CPR not implemented)
- `ltp` in the levels response is always `None` for options — the candles endpoint provides live price
- CPR cache key uses the full symbol string (`NIFTY24000CE`) so separate from the NIFTY cache

---

## Layout (Simulator Architecture — 2026-06-19)

Same fixed-viewport pattern as `trade_flow.html`:

```
nav (56px)
app-topbar (52px)  — live-dot + LTP + zone-pill + bias-pill + cpr-type-badge + virgin-badge
                      | PP/TC/BC/Width stat chips | pause-btn + alert-count | selInfo (right)
app-workspace (flex:1)
  app-sidebar (292px) — selectors (symbol/option/period) + heroSub info + candle stats
                         virgin-banner + Price Levels panel + Camarilla panel
  app-main (flex:1)  — chart + Active Signals (always visible in .main-content)
                        sec-panel#sec-plan (Trade Plan)
                        sec-panel#sec-alerts (Alert Feed)
app-bottombar (40px) — Trade Plan tab | Alerts tab | SEBI disclaimer
```

Light theme: `/css/light-theme.css` + page-specific overrides. Variable block removed (covered by shared file).

`switchPanel(id)` — same pattern as trade_flow: toggles `.sec-active` on `.app-main`, hides `.main-content`, shows matching `.sec-panel`.

## Known Caveats

- Camarilla H4/L4 are the key S1-monitor trigger levels — computed identically in both pages.
- `_virginCPR` is determined client-side by checking if any fetched candle has high ≥ TC or low ≤ BC.
- Weekly/monthly timeframes use daily candles (not intraday) — `_candles` array content changes accordingly.
- Side effect of rule 1: a gap-up open above TC that later falls back fires no BREAKOUT_FAILURE — intentional, there was no breakout to fail.
- SEBI compliance (2026-06-09): all user-facing directive language removed across the page.
  - Alert `direction` values: `'Bullish'`/`'Bearish'`/`'Watch'` (was Buy/Sell). CSS classes `dir-buy`/`dir-sell` kept for green/red styling — internal names only.
  - Active Signals: Mean Reversion status `BULLISH EDGE`/`BEARISH EDGE` (was BUY/SELL ZONE); level chips `Lower edge`/`Upper edge` (was Buy/Sell); Camarilla msgs use "bullish/bearish reference, invalidation …" (was "buy/sell with SL …").
  - Reason strings: "bullish/bearish continuation setup", "bullish/bearish mean-reversion setup", "strong bullish/bearish trend continuation" (was long/short).
  - Trade Plan: "Reference Zone" label + "… retest reference" notes (was "Entry Zone" / "… breakout entry").
  - Disclaimer added at the bottom of `.alert-section` (was missing — mandatory per CLAUDE.md).
  - Internal JS identifiers `entry`/`entryVal`/`entryNote` retained — not rendered.
