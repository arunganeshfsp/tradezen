# Context: market-movers

**File:** `public/stock_movers.html`
**Backend:** `ai_engine/main.py` (`/stocks/movers`, `_nifty500_movers_sync`), `ai_engine/core/movers.py` (`fetch_movers`)
**Last updated:** 2026-07-01

---

## Purpose

Displays Top 10 gainers and losers for a selected Nifty index (NIFTY 50 / 500 / BANK NIFTY / IT / MIDCAP 100 / SMALLCAP 100), with buy/sell depth dominance per stock. Tapping any row opens `stock-analyser.html?symbol=` in a new tab. Educational only — no buy/sell calls.

---

## Layout

```
nav (halo-navbar)
hero
  filter-bar (index buttons) + filter-bar (price min/max, min-change toggles, Scan Now)
stats-strip (chipTotal | chipAdv | chipDec | chipUnch | chipTime | chipSourceTxt)
movers-wrap (2-col grid: gainers panel | losers panel)
```

---

## Key JavaScript

| Variable / Function | Purpose |
|---|---|
| `_currentIndex` | Selected index string, e.g. `'nifty50'` |
| `_filterMinChg` | Min % change filter (0/1/3/5) |
| `_fnoOnly` / `toggleFno()` | "F&O ONLY" toggle CTA → adds `fno=true` to the query |
| `_rowCache` | `{ [symbol]: rowData }` — avoids JSON in HTML attributes |
| `selectIndex(index, btn)` | Sets `_currentIndex`, toggles active button (does NOT fetch) |
| `_buildParams()` | Builds the `/api/stocks/movers` query from current index + filters |
| `_fetchAndRender(showLoading)` | Core fetch+render; `showLoading` toggles the spinner/error takeover |
| `scanNow()` | Manual scan (spinner) then starts the auto-refresh timer |
| `_startAutoRefresh()` | 60s `setInterval` → silent `_fetchAndRender(false)`; skips when tab hidden |
| `_renderData(d)` | Populates stats strip + renders both panels |
| `_renderPanel/_renderRows/_depthCell` | Panel/row/depth-bar HTML |

**Refresh model (2026-07-01):** first data load requires tapping **Scan Now**; after that the page auto-refreshes every 60s. Auto-refresh is silent (no spinner, keeps last data on failure) and pauses while the tab is hidden (`document.visibilityState`), with an immediate re-sync on `visibilitychange` back to visible.

---

## Backend caching & ranking

- Both movers paths cache for **60s**: `core/movers.py` `_CACHE_TTL = 60`; `main.py` `_nifty500_movers_sync` `_TTL = 60` (`_STALE_OK = 1800` for serving stale on provider failure). Lowered from 300s on 2026-07-01 so the frontend's 60s refresh actually gets fresh ticks.
- `_volume_rank(rows, is_gainer)` returns **only volume-confirmed movers**: gainers must have `buy_pct >= 50`, losers `sell_pct >= 50`; order-book-opposed stocks are excluded entirely, then sorted by `_composite_score` (`abs(pct_change) * max(0.1, dom_pct/50)`). If fewer than 10 pass, a shorter list is correct. The `/stocks/movers` nifty500 path widens the candidate pool before ranking to help surface enough confirmed names.

---

## API Contract

`GET /api/stocks/movers?index=nifty50&min_price=&max_price=&min_change=&fno=` response:

`fno=true` restricts `all_rows` (and thus gainers/losers) to F&O-eligible symbols. The F&O universe comes from `_load_fno_stocks()` (NFO `OPTSTK`/`FUTSTK` names mapped to NSE `-EQ` tokens in `data/instrument_master.json`, 24h cache) — the same source the F&O scanner uses. Symbols matched case-insensitively.


```json
{
  "count": 50, "advancing": 26, "declining": 23, "unchanged": 1,
  "fetched_at": 1234567890, "source": "Live", "index": "NIFTY 500",
  "gainers": [{ "symbol","ltp","prev_close","change","pct_change","high","low","volume","buy_qty","sell_qty","buy_pct","sell_pct","year_high","year_low" }],
  "losers": [...],
  "all_rows": [...]
}
```

---

## Known Caveats

- Price/min-change filters are applied server-side over `all_rows`; they only take effect on the next fetch (Scan Now or the 60s tick), not instantly on toggle.
- Changing the index without tapping Scan Now leaves the old panel until the next auto-refresh tick, which then loads the newly selected index (`_buildParams` reads `_currentIndex` live).
- Real staleness floor is now ~60s (backend cache) + up to 60s (frontend tick). Going lower increases load on the single-account market-data provider — see [[project-data-provider-migration]].
- Data source is still AngelOne SmartAPI (single account). See the migration note before raising refresh frequency further.
