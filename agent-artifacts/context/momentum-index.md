# Context: momentum-index

**Files:**
- `ai_engine/main.py` — `GET /momentum-constituents/{index_name}` FastAPI endpoint; 24h in-memory cache; uses `_fetch_nse()` from `core/movers.py` for NSE session-gated API
- `services/nseMomentumIndex.js` — Node.js service file (no longer used by route; route proxies directly to Python)
- `routes/stockRoute.js` — `GET /api/momentum-index/:indexName` proxies to Python via `aiService.proxy()`
- `public/trade_flow.html` — collapsible "Momentum Index Stocks" section inside `app-main`

**Last updated:** 2026-07-10 (DB-based fix)

---

## 2026-07-10 — Initial Implementation

**What changed — initial (2026-07-10)**
- New collapsible "Momentum Index Stocks" section in `trade_flow.html` (after `#accuracy-section`, before `#ohlc-banner`).
- CSS `.mtab`, `.mchip`, `.mchip-skel` using existing page tokens.
- JS: `_toggleMomentum`, `_switchMomentumTab`, `_fetchMomentumIndex`, `_renderMomentumChips` (lazy load on panel open).
- `services/nseMomentumIndex.js` created (Node-side fetcher — superseded by Python approach below).

**What changed — fix (2026-07-10)**
- Both original fetch sources failed: niftyindices.com CSV URLs return 404 (path changed); NSE website API blocked by Imperva JS challenge at HTTP level.
- Added `GET /momentum-constituents/{index_name}` to Python `main.py`. Uses `_fetch_nse()` from `core/movers.py` which has a proper NSE session warmup (visits home page + market-data page first, accumulates cookies in a persistent `requests.Session`).
- `_MOMENTUM_INDEX_MAP` in `main.py` maps `NIFTY200_MOMENTUM_30` → `"NIFTY200 MOMENTUM 30"` (NSE parameter name).
- `_momentum_cache` dict in `main.py` provides 24h in-memory cache on the Python side.
- Node route now proxies directly to Python via `aiService.proxy()` — `nseMomentumIndex.js` is no longer called.

**Why**
User wants to see which stocks are in NSE's momentum indices while reviewing today's trend in the Trade Decision Flow page.

## 2026-07-10 — DB-based fix (replaces NSE fetch)

**What changed**
- `_MOMENTUM_INDEX_MAP` in `main.py` now maps to `(db_source, label)` — e.g., `NIFTY200_MOMENTUM_30 → ("m200_30", "NIFTY200 Momentum 30")`.
- `/momentum-constituents/{index_name}` endpoint now reads from `stock_universe` DB via `stock_universe_get(conn, db_source)`. No more `_fetch_nse()` call. Returns `stale: True` only when DB is empty (user hasn't imported yet).
- `/stock-inventory` GET "all" response now includes `m200_30`, `m500_50`, `mmid150_50` lists and their counts.
- `/stock-inventory/import` and `/stock-inventory` DELETE now accept `m200_30`, `m500_50`, `mmid150_50` as valid source values.
- `public/mgmt/stock-inventory.html` — 3 new tabs (NF200 M30, NF500 M50, MidCap M50) with count badges, import/clear UI. JS refactored to use `_SRC` map (eliminates hardcoded source→ID ternaries).

**Why**
NSE website blocks DigitalOcean IP ranges via Imperva JS challenge; niftyindices.com CSV URLs return 404. Server-side fetch is not viable from cloud. User can download CSVs locally from NSE and import via admin UI.

**How to import momentum stocks**
1. Go to nseindia.com → Equity → Indices → select the momentum index → Download CSV
2. Open `/mgmt/stock-inventory.html`, click the relevant momentum tab, upload the CSV.
3. The momentum panel in `trade_flow.html` will immediately start showing stocks (no server restart needed).

**Known caveats**
- Stocks are only as fresh as the last manual import. Momentum index rebalancing is semi-annual (Jan and Jul), so one import per half-year is sufficient.
- SEBI disclaimer is included in the collapsible footer in `trade_flow.html`.
- `services/nseMomentumIndex.js` still exists in the codebase but is unused — route proxies to Python only.
