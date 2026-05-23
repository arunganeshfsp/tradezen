# Context: swing-trading

**File:** `public/swing_trading.html`  
**Last updated:** 2026-05-23

---

## Purpose

Swing trade setup analyser for individual stocks. Two modes: single-stock deep analysis (5 pillars) and bulk scan across ~120 stocks. Data sourced from yfinance (1-year daily OHLCV). First load is slow (10–90 seconds depending on mode).

---

## Layout

```
nav → hero → tabs: Analyse | Scan | Screener | Review (open positions)
  Analyse tab  → single stock: 5-pillar breakdown + trade plan
  Scan tab     → bulk scan: table of setups across watchlist
  Screener tab → filtered scan by sector/setup type
  Review tab   → open positions tracker (localStorage)
```

---

## Key State

| Variable | Purpose |
|---|---|
| `STOCKS` | Hardcoded watchlist array (~120 symbols) |
| `cfgCapital()` | Returns capital from input (default ₹75,000) |
| `cfgRisk()` | Returns risk % from input (default 2%) |

---

## Key Functions

| Function | What it does |
|---|---|
| `runAnalyse()` | GET `/api/swing/analyse?symbol=&capital=&risk_pct=` → `renderAnalysis(d)` |
| `renderAnalysis(d)` | Renders 5-pillar cards + trade plan + position sizing |
| `switchTab(id, btn)` | Tab switcher (Analyse/Scan/Screener/Review) |
| `updateCfgDisplay()` | Updates max risk and max per-stock exposure display |
| `renderPositions()` | Renders open positions from localStorage |

---

## 5-Pillar Analysis Structure

The `/api/swing/analyse` response has:
```json
{
  "market": { "nifty_trend", "vix_zone" },
  "pillars": {
    "p1": { "trend_valid", "ema_alignment" },
    "p2": { "supertrend_up", "st_value" },
    "p3": { "checks": { "rsi_ok", "volume_ok", "pattern" } },
    "p4": { "setup_id", "setup_name", "setup_desc" },
    "p5": { "entry_zone", "stop_loss", "target_1", "target_2" }
  },
  "trade_plan": { "entry", "sl", "t1", "t2", "rr" },
  "position": { "qty", "capital_required", "max_loss", "max_gain" }
}
```

## Setup Types (from `swing_analyzer.py`)

- **Setup A** (`_setup_a`) — EMA 9 > EMA 21 > EMA 50, Supertrend up, RSI > 50
- **Setup B** (`_setup_b`) — Pullback to EMA 21, Supertrend up, RSI recovering from oversold
- **Setup C** (`_setup_c`) — Breakout above 52-week high with volume

---

## Data Source

All swing data fetched via `yfinance` (not SmartAPI). This means:
- 15-minute delay during market hours
- Works 24/7 (not restricted to market hours)
- First call per symbol is slow (network fetch + compute)
- Subsequent calls hit the Parquet cache (`parquet_store.py`)

---

## Known Caveats

- Warning shown: "First run fetches ~59 days of 5m + 15m + 1H data from yfinance · takes 15–40 sec"
- Scan time: "45–90 seconds — all data fetched live from yfinance for ~120 stocks"
- `STOCKS` array is hardcoded in the HTML — to add/remove stocks, edit that array directly.
- Open positions (Review tab) are stored in `localStorage` — not persisted to server, not shared across devices.
