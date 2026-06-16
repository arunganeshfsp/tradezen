# Context: cpr-monitor

**File:** `public/cpr_monitor.html`  
**Last updated:** 2026-06-16

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

**Root cause:** `trade_flow_data["prev_ohlc"]` (in `main.py`) was fetched once at startup and never refreshed. If the server stayed running across a weekend/holiday, it served the startup-day's previous trading day forever (e.g. started Saturday → showed Friday's data indefinitely into the following week).

**Fixes applied (`main.py`):**
1. `_daily_instrument_refresh` task (8:30 AM IST on weekdays) now also refreshes `prev_ohlc` via `_yf_prev_ohlc()` and resets `nifty_open` + `orb` fields so intraday state is clean for the new day.
2. `_ohlc_last_fetched_ist_date` module variable — tracks which IST date the OHLC was last fetched.
3. `get_trade_flow()` checks this variable on every call — if today's IST date differs from the last fetch date, it calls `_yf_prev_ohlc()` and updates the cache. This is a safety net for any case where the daily task didn't fire (holiday, missed window, etc.). Only fires once per day (tracker updated after refresh).

The `psychology/levels` endpoint is NOT affected — it does its own live yfinance fetch on every call.

---

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
