# Context: stock-options

**File:** `public/stock_options.html`  
**Last updated:** 2026-06-15

---

## Purpose

Same option chain analysis as `options-analysis` but scoped to individual stocks (RELIANCE, TCS, INFY, etc.). Adds a "Stock Trade Flow" panel showing CPR/VWAP levels for the selected stock.

---

## Differences from options-analysis.html

| Feature | options-analysis | stock-options |
|---|---|---|
| Default symbol | NIFTY | RELIANCE |
| Stock Trade Flow panel | No | Yes — `stfBox` panel |
| URL params | None | `?symbol=&expiry=&direction=` on load |
| Bhavcopy history | Manual only | Auto-fetch NSE + manual fallback |

---

## Key State

Same as `options-analysis`: `direction`, `chainData`, `analyticsData`.

Additional:
- `window._urlExpiry` — expiry pre-loaded from URL param, applied once expiries dropdown loads

---

## Key Functions

| Function | What it does |
|---|---|
| `initFromParams()` | IIFE — reads `?symbol`, `?expiry`, `?direction` from URL on load |
| `loadStockTradeFlow(symbol)` | GET `/api/psychology/levels?symbol=` — renders CPR/VWAP panel |
| `renderStockTradeFlow(d)` | Renders `stfBox` with BC, TC, PP, VWAP, Supertrend values |
| `fetchContractHistoryNSE()` | Auto-fetch bhavcopy from NSE for the selected contract |
| `loadExpiries()` | Same as options-analysis but defaults to RELIANCE |

---

## URL Deep-link Pattern

```
/stock_options.html?symbol=TCS&expiry=2026-05-29&direction=CE
```
`initFromParams()` reads these and pre-fills the form + triggers analysis after expiries load.

---

## Option Chain Data Source (2026-06-15)

`/options/chain` now fetches from **NSE directly** as the primary source, with SmartAPI as fallback.

- New function: `fetch_chain_nse()` in `option_chain_fetcher.py`
- `_options_chain_sync()` in `main.py` tries NSE first, logs and falls back to SmartAPI on failure
- Why: SmartAPI's `getMarketData` returns stale LTP for thinly-traded far-dated PE contracts (e.g. stock options with 30JUN2026 expiry). NSE's own API reflects current bid/ask and last traded price accurately.
- NSE response field mapping: `lastPrice→ltp`, `openInterest→oi`, `changeinOpenInterest→oi_change`, `totalTradedVolume→volume`, `impliedVolatility→iv`, `bidprice→bid`, `askPrice→ask`
- `depth` is empty `{buy:[], sell:[]}` for NSE source — SmartAPI depth data not available via this path
- NSE session management: module-level `_nse_chain_session`, reset on HTTP failure, re-warmed with homepage + `/option-chain` page visits

---

## Known Caveats

- `window._urlExpiry` is set by `initFromParams()` and consumed once inside `loadExpiries()` — it's a one-shot flag, not reactively bound.
- Stock Trade Flow panel (`stfBox`) uses `/api/psychology/levels` which is the same endpoint as the TradeFun page's CPR levels — it returns BC, TC, PP, S1, R1, VWAP, Supertrend for any symbol.
- Bhavcopy NSE auto-fetch can fail outside market hours or for illiquid contracts — manual upload is the reliable fallback.
- NSE option chain API may be slower (~2–3s warmup on first call) due to cookie warmup. Subsequent calls reuse the cached session.
- Liquidity Gate shows spread_pct as "–" for NSE source — depth data (bid/ask depth levels) not available, only top-of-book bid/ask. Spread_pct could be computed from bid/ask if needed in future.
