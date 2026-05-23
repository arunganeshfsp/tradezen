# Context: market-profile

**File:** `public/market_profile.html`  
**Last updated:** 2026-05-23

---

## Purpose

TPO (Time Price Opportunity) and Volume Profile viewer. Supports historical daily profiles and live intraday profile. Shows POC, VAH, VAL, IB range, and prev-day levels overlay.

---

## Key State

| Variable | Purpose |
|---|---|
| `currentProfile` | Last fetched profile data |
| `viewMode` | `'tpo'` \| `'volume'` — display mode |
| `liveActive` | Boolean — live poll running |
| `liveTimer` | setInterval handle for live updates |
| `currentPrice` | Live NIFTY spot price |
| `prevDayLevels` | `{poc, vah, val, ib_high, ib_low}` from prior day |

---

## Key Functions

| Function | What it does |
|---|---|
| `loadProfile()` | Main fetch — routes to `daily` or `live` endpoint based on mode |
| `getParams()` | Reads symbol, token, exchange, date, days from form controls |
| `onSymbolChange()` | Updates token/exchange when symbol dropdown changes |
| `setMode(mode, el)` | Switches between Historical and Live modes |
| `fetchCurrentPrice()` | GET `/api/price` → updates live price display |
| `loadPrevDayLevels(dateStr)` | GET `/api/market-profile/levels` → prev day POC/VAH/VAL |
| `loadLive()` | GET `/api/market-profile/live` → live intraday profile |
| `renderProfile(data)` | Renders TPO or Volume chart from profile data |

---

## Symbol → Token Mapping

The symbol dropdown has values in `"token|exchange"` format:
- `"26000|NSE"` → NIFTY spot
- `"26009|NSE"` → BANKNIFTY spot

`getParams()` splits on `|` to extract `symbol_token` and `exchange` separately for API calls.

`PERIOD_COLORS` object maps time periods (30-min buckets) to distinct colours for TPO display.

---

## API Endpoints

| Endpoint | Used for |
|---|---|
| `GET /api/market-profile/daily?symbol_token=&exchange=&date=&days=` | Historical daily profile |
| `GET /api/market-profile/live?symbol_token=&exchange=` | Live intraday profile |
| `GET /api/market-profile/levels?symbol_token=&exchange=&date=` | POC/VAH/VAL for a specific date |
| `GET /api/market-profile/multi-day?symbol_token=&exchange=&days=` | Multi-day composite profile |
| `GET /api/price` | Live spot price |

---

## Known Caveats

- Live mode uses a polling interval — `liveTimer` must be cleared when switching to historical mode or leaving the page.
- `prevDayLevels` is loaded from the day *before* the selected date — the date arithmetic is done client-side in `loadPrevDayLevels()` by subtracting one day.
- Multi-day profile endpoint is available but not wired to a UI control yet — can be called programmatically.
