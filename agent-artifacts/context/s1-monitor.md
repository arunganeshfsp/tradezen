# Context: s1-monitor

**Files:** `public/s1_monitor.html`, `public/stock_s1_monitor.html`  
**Last updated:** 2026-05-23

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

## Known Caveats

- Expiry date string is hardcoded in `updateSignalCard()` — update every Thursday.
- Lot size (65) is hardcoded — verify after SEBI lot size revisions.
- The LightweightCharts mini chart is optional — if `s1Chart` fails to init (e.g. container missing), the signal card still works.
- `getSessionStatus()` uses a manual UTC+5:30 offset calculation — not timezone-aware. Will break if server clock drifts.
