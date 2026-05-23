# Context: market-movers

**File:** `public/stock_movers.html`  
**Last updated:** 2026-05-23

---

## Purpose

Displays Top 10 gainers and losers for a selected Nifty index. Auto-refreshes every 30 seconds. Per-stock modal shows entry indicators (EMA 9/21/50/200, VWAP, Supertrend, RSI — 5m and daily).

---

## Layout

```
nav (halo-navbar)
hero
  filter-bar (NIFTY 50 | NIFTY 500 | BANK NIFTY | NIFTY IT | MIDCAP 100 | SMALLCAP 100)
stats-strip (chipTotal | chipAdv | chipDec | chipUnch | chipTime | chipSourceTxt | countdownBadge | Refresh btn)
movers-wrap (2-col grid: gainers panel | losers panel)
indOverlay + indModal (fixed overlay for per-stock indicator modal)
```

---

## Key JavaScript

| Variable / Function | Purpose |
|---|---|
| `_currentIndex` | Currently selected index string, e.g. `'nifty50'` |
| `_rowCache` | `{ [symbol]: rowData }` — avoids JSON in HTML attributes |
| `loadMovers(index, btn)` | Main fetch function — GET `/api/stocks/movers?index=` |
| `_renderData(d)` | Populates stats strip + renders both panels |
| `_renderPanel(rows, isGainer)` | Returns HTML for one panel (gainers or losers) |
| `_renderRows(rows, isGainer)` | Returns table row HTML for each stock |
| `openModal(sym)` | Fetches `/api/stocks/indicators?symbol=` and renders modal |
| `_pollPrices()` | Every 5s — GET `/api/stocks/live-prices?index=` — flashes updated LTP |
| `_updateLtp(sym, newLtp)` | Updates `.ltp-val` cell with flash animation |
| `_startCountdown()` | 30s countdown badge — auto-calls `loadMovers` at 0 |

---

## Fixed Bug (2026-05-22)

**Root cause:** `_renderData()` called `document.getElementById('lastUpdateBadge').textContent = d.index` at line 377, but no element with `id="lastUpdateBadge"` exists in the HTML.

This threw a TypeError inside `_renderData()` after the stats strip was already populated (lines 370–376 ran fine). The error was caught by `loadMovers()`'s `try/catch`, which replaced `moversWrap` with "Failed to load: Cannot set properties of null (setting 'textContent')".

**Symptom:** Stats strip showed correct data (49 stocks, 26 advancing, 23 declining) but the gainers/losers panels were empty.

**Fix:** Added a null guard — `const lastBadge = document.getElementById('lastUpdateBadge'); if (lastBadge) lastBadge.textContent = d.index;`

---

## API Contracts

`GET /api/stocks/movers?index=nifty50` response:
```json
{
  "count": 50, "advancing": 26, "declining": 23, "unchanged": 1,
  "fetched_at": 1234567890,
  "source": "NSE Live",
  "index": "NIFTY 50",
  "gainers": [{ "symbol", "ltp", "prev_close", "change", "pct_change", "high", "low", "volume", "year_high", "year_low" }],
  "losers": [...]
}
```

`GET /api/stocks/indicators?symbol=RELIANCE` response:
```json
{
  "symbol", "ltp", "bias", "bias_color", "score", "max_score",
  "indicators": { "vwap", "ema9", "ema21", "ema50", "ema200", "supertrend", "rsi_5m", "rsi_1d" },
  "checks": { "above_vwap", "above_ema9", "above_ema21", "ema9_above_ema21", "above_ema50", "above_ema200", "supertrend_up", "rsi_5m_bullish", "rsi_1d_bullish" }
}
```

---

## Known Caveats

- `lastUpdateBadge` element does not exist in HTML — the null guard prevents the crash but the index name is never displayed anywhere. If a future task adds a visible index label to the stats strip, add `id="lastUpdateBadge"` to that element and remove the guard.
- Live price polling runs every 5 seconds independently of the 30-second full refresh.
- The modal uses `_rowCache[sym]` for the current LTP/pct shown in the header — stale if the stock moved significantly since last full refresh.
