# Context: fno-scanner

**File:** `public/fno_scanner.html`  
**Last updated:** 2026-06-24 (Futures OI)

---

## Purpose

F&O momentum scanner — filters stocks by price range, dominance (buyer/seller), and universe (Nifty50/500). Auto-refreshes. Per-stock modal shows live indicators. Separate "Open Shorts" tab shows OI-based short candidates.

---

## Key State

| Variable | Purpose |
|---|---|
| `intervalSec` | Auto-refresh interval (default 5s) |
| `limitCount` | Max results to show (default 10) |
| `dominanceFilter` | `'all'` \| `'buyer'` \| `'seller'` |
| `universeFilter` | `'all'` \| `'nifty50'` \| `'nifty500'` |
| `autoOn` | Boolean — whether auto-refresh is active |
| `timer` / `cdTimer` | Auto-refresh and countdown timers |

---

## Key Functions

| Function | What it does |
|---|---|
| `fetchScanner()` | GET `/api/fno-scanner?min_price=&max_price=&limit=&dominance=&nifty50=&nifty500=` |
| `setInterval_(val)` | Update refresh interval + restart timer |
| `setLimit(val)` | Update result count + re-fetch |
| `setUniverse(val)` | Filter by index universe + re-fetch |
| `setDominance(val)` | Filter by buyer/seller + re-fetch |
| `toggleAuto()` | Start/stop auto-refresh |
| `openStockRow(stock)` | Calls both `openConfirm` and `openOptSheet` — row click + Analyse button |
| `openConfirm(stock)` | GET `/api/stock-indicators/{symbol}` → render indicator modal |
| `closeModal(e)` | Close overlay on outside click |
| `restartTimer()` | Clears + restarts countdown timer |

---

## Recent Changes (2026-06-24)

- **Removed** Trade column (disabled Buy/Sell buttons) — SEBI compliance: "Buy/Sell" as action directives not allowed
- **Removed** Monitor column ("Monitor →" link to stock_s1_monitor.html)
- **Added** Analyse button (`.analyse-btn`) in place of both removed columns — calls `openStockRow()` same as row click; uses `event.stopPropagation()` so row click doesn't double-fire
- **SEBI compliance pass**: hero tag "Buy / Sell Dominance" → "Buyer · Seller Dominance"; signal labels "BUY CALL ▲" → "BULLISH SETUP ▲", "BUY PUT ▼" → "BEARISH SETUP ▼"; "WAIT" → "OBSERVE"; "avoid" removed from vol warning; "avoid" removed from SKIP reason
- **Added** SEBI disclaimer footer: "For educational purposes only. Not investment advice. Consult a SEBI-registered adviser before trading."
- Table now has 10 columns (was 11)

### Futures OI Confirmation (added same session)
- `_stock_indicators_sync()` in `main.py` now also fetches near-month FUTSTK OI from Angel One via `im.get_stock_futures_token(symbol)` (new method in `instrument_master.py`)
- Returns `fut_oi: {oi, oi_chg, signal, ltp, expiry}` or `null` if not an F&O stock / market closed
- Signal logic: Long Buildup (price↑+OI↑), Short Buildup (price↓+OI↑), Short Covering (price↑+OI↓), Long Unwinding (price↓+OI↓)
- `oi_chg` comes from `netChangeInOI` in Angel One response — may be `null` outside market hours; signal is null when either direction is unknown
- Frontend renders a "Futures OI Confirmation" section at the bottom of the indicator modal

---

## Scanner Response Shape

```json
[{
  "symbol", "ltp", "change_pct",
  "dominance": "BUYER" | "SELLER",
  "volume", "oi", "oi_change",
  "sector"
}]
```

---

## Open Shorts Tab

Separate fetch for OI-based short setups. Uses same `/api/fno-scanner` endpoint with additional `shorts=true` param. Rendered independently from the main scanner table.

---

## Known Caveats

- Price range filter (min/max) defaults to ₹1000–₹2000 — this misses high-priced stocks like MARUTI. Users can change it manually.
- The auto-refresh interval is 5 seconds — aggressive. Reducing to 15–30s would lower API load for production.
- `openConfirm()` uses `/api/stock-indicators/{symbol}` which is the same endpoint as the market-movers modal. The response shape is identical.
- The scanner runs even outside market hours — data will be from last market close (stale).
