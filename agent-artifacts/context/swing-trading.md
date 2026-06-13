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

## Reversal Radar tab (added 2026-06-13)

A 5th tab — **mean-reversion** counterpart to the trend-following 5-pillar engine. Built because the S4 engine *rejects* fallen stocks (it requires price > EMA50, RSI 50–70, 15%+ above 52w low), so it could never surface "quality leader down 30% and turning" (the user's TCS example). Spec: `spec-kit/specs/reversal-radar.md`.

- **Backend:** `ai_engine/core/reversal_analyzer.py` (new) — `analyse_reversal()` (single) + `scan_reversals()` (batch). Reuses `swing_analyzer` helpers (`STOCK_INFO`, `_fetch_*`, `_atr14`, `_position_size`, `_vix_zone`, `_CACHE`). Adds `MIDCAP_INFO`/`MIDCAP_SELECT` (~30 quality midcaps). Endpoints in `main.py`: `GET /swing/reversal/analyse`, `GET /swing/reversal/scan`. Node proxy: `/api/swing/reversal/*` (180s timeout on scan).
- **Strategy (fixed "Confirmed turn", strict):** drawdown 15–65% off 52w high → at support (200-DMA / 52w-low band / prior pivot demand) → **confirmed = higher-low AND 20-DMA reclaim AND (RSI-turn OR MACD-up) AND volume confirmation**. Bonus: bullish RSI divergence, reversal candle. Buckets: `candidate` / `watching` / `rejected` / `not_fallen`.
- **Fake-reversal rejections** (each surfaced as a teaching reason): still lower lows = knife; weak-volume bounce = dead-cat; below 20-DMA; >65% = structural; VIX ≥ 25 = stand aside.
- **Fundamental gate (user-requested):** `_fetch_fundamentals()` via yfinance `.info` (ROE/D-E/earnings/margin → Strong/Healthy/Mixed/Caution), cached 1h. Runs only on the **top 12** chart candidates (the slow part). A confirmed chart turn in an unsound company is **demoted** candidate→watching ("possible value trap").
- **Reversal Score (0–100):** confirmation 40 · support 20 · volume 15 · fundamentals 15 · sector 10.
- **SEBI framing:** levels labelled *reference reversal* / *structure invalidation* / *prior supply*, never entry/exit. Disclaimer in the tab. Position size shown as "hypothetical study size".
- **i18n note:** this page predates the `T()`/`data-ta` JS-string i18n pattern; its dynamic tab content (Analyse/Scan) is English-only. The Reversal tab matches that (English dynamic strings; `data-en/data-ta` only on the static tab button) for consistency, rather than bolting a bilingual layer onto one tab.
- **Validated 2026-06-13:** synthetic happy-path (28.9% fall + higher-low + reclaim → candidate, score 86.7, all 6 checks pass) and live yfinance (TCS −36.5% → `rejected` because the turn isn't confirmed; HINDUNILVR −20.5% → `watching`). Real fundamentals/sector/drawdown map correctly.

## Known Caveats

- Warning shown: "First run fetches ~59 days of 5m + 15m + 1H data from yfinance · takes 15–40 sec"
- Scan time: "45–90 seconds — all data fetched live from yfinance for ~120 stocks"
- `STOCKS` array is hardcoded in the HTML — to add/remove stocks, edit that array directly.
- Open positions (Review tab) are stored in `localStorage` — not persisted to server, not shared across devices.
