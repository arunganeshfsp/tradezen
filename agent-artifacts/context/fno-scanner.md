# Context: fno-scanner

**File:** `public/fno_scanner.html`  
**Last updated:** 2026-05-23

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
| `openConfirm(stock)` | GET `/api/stock-indicators/{symbol}` → render indicator modal |
| `closeModal(e)` | Close overlay on outside click |
| `restartTimer()` | Clears + restarts countdown timer |

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
