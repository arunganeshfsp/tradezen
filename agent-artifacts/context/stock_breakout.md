---
module: stock_breakout
status: active
last_updated: 2026-06-28
---

## What this module does
Consolidation-Breakout scanner. Finds stocks that (1) declined ≥N% from their 52-week high, (2) spent 4–12 weeks in a tight sideways base (range ≤10%), (3) are now approaching or breaking above the top of that base.

## Files

| File | Role |
|---|---|
| `ai_engine/core/patterns/breakout_scanner.py` | All scan logic — base detection, accumulation scoring, verdict |
| `ai_engine/main.py` | `GET /stock/breakout-scan` + `GET /stock/breakout-check/{symbol}` endpoints (added at end of file) |
| `routes/stockRoute.js` | Node proxy routes added between reversal routes and Paper Trading section |
| `public/stock_breakout.html` | Full page with filters, presets, single-check, result cards, chart modal |

## Algorithm (5 steps)

1. **Prior high + decline** — `prices.argmax()` gives the high; `post_peak_low` is the minimum after that peak. If decline < `min_decline`, skip.
2. **Base detection** — `_find_base()` scans backward from most recent bar; tries widths from `max_w` down to `min_w` (weeks). Base is valid if `(hi-lo)/lo*100 ≤ max_range`. Returns `(start_idx, end_idx, base_lo, base_hi)`.
3. **Accumulation score (0–5)** — higher lows, declining volume, RSI 38–68, MACD above signal, stock outperforming Nifty 50 during base.
4. **Breakout readiness** — `distance_pct = (base_hi - cur) / base_hi * 100`. Negative = above base. `vol_confirmed = cur > base_hi AND last_vol ≥ 1.5× avg20`.
5. **Verdict** — STRONG (breakout + volume + score≥3 + market not adverse) / MODERATE (near or above + score≥2 + ≤1 flag) / WEAK (near or above, lower score) / BUILDING (valid base, not near).

## Key functions

- `_find_base(prices, min_w, max_w, max_range)` → `Optional[Tuple[si,ei,lo,hi]]`
- `_higher_lows(prices, order)` → scans for any consecutive ascending trough pair
- `_vol_trend(vols)` → compares first-half vs second-half average, returns "declining"/"rising"/"mixed"
- `_analyse_one(sym, close, volume, nifty, ...)` → returns full result dict or None
- `scan_breakouts(universe, min_decline, min_w, max_w, max_range, near_res, sector, symbols)` → batch scan
- `check_single_breakout(symbol, ...)` → single stock, downloads its own yfinance data + ^NSEI

## API params

Both endpoints share:
- `min_decline` (default 20%) — minimum % fall from 52W high
- `min_w` / `max_w` (default 4/12) — base duration in weeks
- `max_range` (default 10%) — tightest acceptable base hi-lo range
- `near_res` (default 5%) — distance from resistance to count as "near breakout"

Scan-only: `universe`, `sector`, `symbols`.

## Frontend presets

- Relaxed: decline 15%, base 3–14w, range 12%, near 8%
- Balanced: decline 20%, base 4–12w, range 10%, near 5%
- Strict: decline 25%, base 6–10w, range 7%, near 3%

## Caveats

- `_find_base` always uses the most recent qualifying window. If price broke up out of an old base and then stalled, it may pick up the new stall period. This is intentional — most recent base is most relevant.
- Nifty alignment uses `close.index.intersection(nifty.index)` for the single-stock path (exact date alignment). In batch mode, the download returns a shared date index, so alignment is natural.
- `_higher_lows` uses `order=max(2, len(bp)//8)` — adapts trough-detection sensitivity to base length.
- Chart data covers last 120 bars. `base_start_idx` in the chart is relative to that 120-bar window.
- SEBI disclaimer appears in sebi-bar at top AND footer text on every result.
- Language: uses "reference level / base zone" — never "entry/exit point / buy/sell".

## Open issues

- Sector filter combines hardcoded SECTOR_MAP with whatever universe is requested; if a symbol is in the sector list but not in the universe list, it may still scan (sector list is used as `symbols` override). This is acceptable — sector scan replaces universe.
- No intraday data — all 1y daily candles from yfinance. Scan results lag by one trading day.
