# Context: ema-scenario

**File:** `public/ema_scenario.html`  
**Last updated:** 2026-05-23

---

## Purpose

EMA 9/21 crossover scenario tool. Two modes: **Simulation** (synthetic candles) and **Live** (real NIFTY data from yfinance). Shows a 4-step analysis: bias → setup → entry → exit. Includes a backtest tab.

---

## Key State

| Variable | Purpose |
|---|---|
| `currentMode` | `'sim'` \| `'live'` |

---

## Key Functions

| Function | What it does |
|---|---|
| `setMode(m)` | Switches sim/live, updates description text |
| `runAnalysis()` | GET `/api/ema-scenario?mode=` → renders 4 step cards + summary |
| `setStatus(state, text)` | Updates status bar (loading / success / error) |
| `renderStep1(bias)` | Bias card — all_conditions_met + EMA alignment |
| `renderStep2(setup)` | Setup card — crossover valid, crossover candle index |
| `renderStep3(entry)` | Entry card — entry triggered, EMA9 + VWAP at entry |
| `renderStep4(entry, mode)` | Exit card — SL hit or target hit |
| `renderPlan(plan)` | Trade plan card — entry/SL/T1/T2 prices |
| `renderSummary(summary, plan, mode)` | Overall summary — all_ok + chips |
| `cond(ok, label, val)` | Returns a styled condition row (✅/❌) |

---

## Analysis Response Shape

```json
{
  "bias":    { "all_conditions_met": bool, "ema_alignment": "bullish|bearish|mixed" },
  "setup":   { "setup_valid": bool, "crossover_candle_idx": int | null },
  "entry":   { "entry_triggered": bool, "ema9_at_entry": float, "vwap_at_entry": float,
               "sl_hit": bool, "target_hit": bool },
  "plan":    { "entry": float, "sl": float, "t1": float, "t2": float, "rr": float },
  "summary": { "all_ok": bool }
}
```

---

## Data Source

- **Sim mode** — synthetic candles generated server-side in `ai_engine/data/generate.py`
- **Live mode** — real NIFTY 5m + 15m + 1H data from yfinance (15-min delayed)
  - First run: 15–40 seconds (fetches ~59 days)
  - Subsequent runs: faster (Parquet cache)

---

## Backtest Tab

Separate fetch: `GET /api/ema-scenario/backtest`  
Runs the same setup detection across historical data and returns win rate, avg R:R, trade list.

---

## Known Caveats

- Live mode works best during market hours — outside hours data is end-of-day delayed.
- First live run is slow: the page shows "First run fetches ~59 days of 5m + 15m + 1H data from yfinance · takes 15–40 sec".
- Backtest results are not cached — every run re-computes across 59 days of 5m data. Can take 30+ seconds.
- `fmt` helper returns `'—'` for null/NaN — always check for this in rendered output.
