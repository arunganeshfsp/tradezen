# Context: momentum-index

**Files:**
- `services/nseMomentumIndex.js` — Node.js service; fetches + caches constituent lists
- `routes/stockRoute.js` — `GET /api/momentum-index/:indexName` route (before `module.exports`)
- `public/trade_flow.html` — collapsible "Momentum Index Stocks" section inside `app-main`

**Last updated:** 2026-07-10 (initial implementation)

---

## 2026-07-10 — Initial Implementation

**What changed**
- New `services/nseMomentumIndex.js`: singleton class, dual-layer cache (in-memory dict + `cache/momentum-index.json`), 24h TTL.
- Fetches constituent list for 3 indices: `NIFTY200_MOMENTUM_30`, `NIFTY500_MOMENTUM_50`, `NIFTYMIDCAP150_MOMENTUM_50`.
- Primary source: CSV download from niftyindices.com (browser-like headers + Referer).
- Fallback: NSE API — GET nseindia.com home page for session cookies, then GET `/api/equity-stockIndices?index=`.
- If both fail: returns stale cache with `stale: true`; if no cache at all, returns empty array.
- New Express route: `GET /api/momentum-index/:indexName` in `stockRoute.js`, validated against allowlist.
- New collapsible section in `trade_flow.html` (after `#accuracy-section`, before `#ohlc-banner`): toggle pattern mirrors `#accuracy-section`. Lazy fetch — data loads only when user opens the panel.
- CSS `.mtab`, `.mchip`, `.mchip-skel` appended to `trade_flow.html` style block; uses existing tokens (`--bg2`, `--bg3`, `--border`, `--border2`, `--dim`, `--accent`, `--muted`).
- JS: `_toggleMomentum`, `_switchMomentumTab`, `_fetchMomentumIndex`, `_renderMomentumChips` added before the Kingfisher section.

**Why**
User wants to see which stocks are in NSE's momentum indices while reviewing today's trend in the Trade Decision Flow page.

**Known caveats**
- niftyindices.com may block the CSV request intermittently (anti-bot). The fallback to NSE API (with cookie acquisition) compensates, but NSE API also uses Imperva protection and may occasionally return 403 outside market hours. If both fail, cached data (up to 24h stale) is returned with a `stale` amber badge.
- NSE API's `data[0]` is always the index itself (e.g., "NIFTY200 MOMENTUM 30") — the regex `^[A-Z][A-Z0-9...]` excludes it because index names contain spaces, so no manual skip needed.
- Momentum index rebalancing is semi-annual (Jan and Jul), so the 24h cache is conservative.
- The `cache/` directory is created automatically by `fs.mkdirSync(…, { recursive: true })` on first write.
- SEBI disclaimer is included in the collapsible footer.
