# Context: ai-signal

**File:** `public/ai_signal.html`  
**Last updated:** 2026-05-23

---

## Purpose

Minimal live signal dashboard — shows BUY CE / BUY PE / WAIT with confidence score, recommended strike, and a readiness checklist. Designed for quick intraday decision support. Polls `/api/ai-signal` every few seconds.

---

## Layout

```
nav → signal card (BIG: signal label + confidence %) → readiness checklist → strike + premium → log list
```

Notably simpler than the other pages — single fetch, no tabs, no charts.

---

## Key State

| Variable | Purpose |
|---|---|
| `lastSignal` | Previous signal response — used for change detection |
| `s1Chart` / `s1CandleSeries` / `s1Ema9Series` / `s1Ema21Series` / `s1RsiSeries` | LightweightCharts instances (mini chart in signal card) |
| `logs` | Array of signal log entries |

---

## Key Functions

| Function | What it does |
|---|---|
| `getSignal()` | GET `/api/ai-signal` → updates signal card |
| `updateSignalCard(result)` | Renders signal label, confidence, strike, premium, SL/T1 |
| `updateReadinessScore(result)` | Updates checklist items from `result.conditions` |
| `addLog(time, signal, strike, premium, ema9, ema21, rsi)` | Appends to signal log list |
| `setCheck(id, pass)` | Sets green/red icon on a checklist item |
| `getSessionStatus()` | Returns market session phase based on IST time |
| `updateSessionStatus()` | Updates session banner (Pre-market / Live / Closed) |

---

## Session Time Logic

All time calculations done in IST (UTC+5:30):
```javascript
PRE_MARKET_START = 9:00 IST
PRE_MARKET_END   = 9:15 IST
LIVE_START       = 9:15 IST
LIVE_END         = 13:00 IST   // NOTE: ends at 1 PM, not 3:30 PM
```

The LIVE_END at 13:00 (not 15:30) is intentional — the S1 strategy the signal is based on is primarily a morning trade.

---

## Signal Response Shape

```json
{
  "signal": "CE" | "PE" | "WAIT",
  "confidence": 0-100,
  "entry_premium": float,
  "sl": float,
  "t1": float,
  "capital": float,
  "conditions": {
    "ema_aligned": bool,
    "supertrend_up": bool,
    "vwap_above": bool,
    "rsi_ok": bool,
    "volume_ok": bool
  }
}
```

---

## Known Caveats

- Expiry date is **hardcoded** in `updateSignalCard()` as a string literal (`'26 May 2026'`). Must be updated manually each week.
- `ai_widget.js` exports a lightweight version of the signal for embedding in other pages — keep the two in sync if the signal response shape changes.
- This page is intentionally minimal — do not add complex features here; use `options-analysis.html` for full option analysis.
