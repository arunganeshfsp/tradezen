# Wealth Time-Lapse — Module Context

## What this module is

What-If compounding lab (tool #11, `public/wealth_timelapse.html`). User picks any NSE stock, a start year, SIP or lumpsum mode, an amount and an FD rate — then watches an animated "race" of how that money would have grown in the stock vs Nifty 50 vs gold (GOLDBEES ETF proxy) vs a fixed deposit. A "Pain Meter" bar strip below the race shows how far the stock sat below its running peak each month, and the end-of-journey summary gives final values, XIRR per track, deepest fall, longest underwater stretch, and a templated lesson sentence.

Chosen by the user over four other proposed stock-experience ideas (Stock Time Machine, Personality Lab, Crash & Recovery Explorer, Stock Race Arena) — those remain candidate future tools.

## Components

| Layer | File | Role |
|---|---|---|
| API | `ai_engine/main.py` — `_timelapse_sync` + `GET /stock/timelapse/{symbol}?start=` (after `/stock/analyse`) | aligned monthly closes for stock + ^NSEI + GOLDBEES.NS |
| Proxy | `routes/stockRoute.js` — `GET /api/stock/timelapse/:symbol` | 45s timeout |
| Frontend | `public/wealth_timelapse.html` | all SIP/lumpsum/FD/XIRR math + Chart.js animation |

## Design decisions (non-obvious)

- **Backend returns only price series; all investment math is client-side** so sliders (year, amount, FD rate, mode) recompute instantly without refetching.
- Monthly closes via `yf.Ticker(...).history(start=..., interval="1mo", auto_adjust=True)` — adjusted for splits/dividends, so tracks approximate total return. Index keyed as `"YYYY-MM"` strings.
- Gold proxy = GOLDBEES.NS (data from ~2007). Nifty/gold series are aligned to the stock's months; missing months come back as `null` and `buildTrack()` carries the last value forward (no buy on null months).
- XIRR solved by bisection on annual rate over monthly cash flows; lumpsum degenerates to CAGR. FD card shows the input rate, not XIRR.
- Animation = `setInterval` 45ms stepping 1 month/frame (2/frame when >200 months), `chart.update('none')`. On any control change the full picture renders immediately; Play re-animates from the start.
- Pain Meter = price drawdown from running peak (not portfolio-value drawdown — clearer to explain).
- Lesson text is a 3-branch template (stock wins / FD beats stock / nifty-gold wins), SEBI-safe descriptive language.

## Known caveats

- Last month in the series is partial (month-to-date close) — fine for "today's value".
- Yahoo monthly data for ^NSEI starts ~2007; the year slider min is set from the stock's first available month, so a stock with older data than ^NSEI will show null-carried Nifty values at the head rather than clipping.
- Taxes, fees, inflation excluded — stated in the page disclaimer.
- `yf.Ticker(sym).info` call for the company name can be slow/empty; failure is swallowed (company stays null, UI uses symbol).

## Open issues

- None deferred. Possible future: compare two stocks in the same race; share/snapshot button; inflation-adjusted toggle.
