# Plan: OI Support/Resistance Levels — horizontal OI bars on a price chart

> Status: **planned, not yet built** (deferred). Saved 2026-08-08.

## Context

Replicate a TradingView-style overlay where each option **strike** is drawn as a horizontal bar on the right of a Nifty candlestick chart, encoding Open Interest so support/resistance walls are readable at a glance (hover tooltip: Strike, Call OI, Chng Call OI, Put OI, Chng Put OI).

No new data provider and no new chart library are needed:
- **OI data** — `GET /api/options/chain?symbol=&expiry=` returns per-strike `ce.oi`, `ce.oi_change`, `pe.oi`, `pe.oi_change` plus `spot` and `analytics{max_pain,pcr,total_ce_oi,total_pe_oi}` (`ai_engine/main.py:5045` → `_options_chain_sync` `:5001`). Trims to ATM ±5 via `_trim_chain_atm` (`:5036`).
- **Candles** — `GET /api/psychology/candles?symbol=&interval=5` returns symbol-aware 5-min OHLCV (`stockRoute.js:779` → `main.py:4225`).
- **Chart + overlay pattern** — TradingView Lightweight Charts v4.x. `market_psychology.html` positions floating DOM labels at price levels using `_candleSeries.priceToCoordinate(price)` (`:1546-1558`), re-run on `subscribeVisibleLogicalRangeChange` (`:1192`) and resize. The OI bars generalize this.
- **Selectors** — `/api/options/search` (`stockRoute.js:461`) and `/api/options/expiries` (`:450`).

### Decisions locked with the user
1. **Location** — new dedicated page `public/nifty_oi_levels.html`; add a **link from `market_psychology.html`**.
2. **Bar meaning** — Call/Put split: strikes ≥ spot show Call OI bars = resistance, strikes < spot show Put OI bars = support; bar length ∝ OI and colour intensity ∝ OI magnitude (high OI vivid, low faint). Largest CE/PE strikes get a "wall" tag. (User deferred; flagged for veto.)
3. **Symbols** — selectable contract: symbol search (default NIFTY) + expiry dropdown, any F&O underlying.
4. **Data** — ±10 strike ladder; tooltip shows all four fields. (User deferred; flagged for veto.)

## Files to modify
1. `ai_engine/main.py` — add `trim_n: int = 5` param to `_options_chain_sync` (used in the `_trim_chain_atm(chain, spot, n=5)` call at `:5027`); add `strikes: int = 5` query param to `options_chain` (`:5045`), clamp 3..15. Default 5 keeps all existing callers unchanged.
2. `routes/stockRoute.js` — in `/api/options/chain` (`:475`) add `if (req.query.strikes) params.set("strikes", req.query.strikes);`.
3. `public/nifty_oi_levels.html` (NEW) — Lightweight Charts candlestick fed from `/api/psychology/candles`; DOM overlay of horizontal bars positioned by `priceToCoordinate(strike)`, right-anchored, length ∝ OI, intensity ∝ OI; hover tooltip (Strike/Call OI/ΔCall/Put OI/ΔPut); Max Pain/PCR/Total OI summary; ~45s polling; SEBI disclaimer; symbol+expiry selectors.
4. `public/market_psychology.html` — header link to `/nifty_oi_levels.html`.
5. SDD: `agent-artifacts/context/nifty-oi-levels.md` + index row.

## Verification
- `python -m py_compile ai_engine/main.py`; `node --check routes/stockRoute.js`.
- `/nifty_oi_levels.html`: candles render, OI bars at strikes on the right, hover tooltip shows 4 fields, symbol/expiry switch works, `?strikes=10` returns ~21 rows while omitting it returns ±5, disclaimer present, link from market psychology works.
