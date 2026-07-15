# Stock Intraday LIVE Trading — Context

**Page:** `public/stock_intraday.html` (direct URL only — NOT linked in any nav; personal use)
**Status:** active
**Created:** 2026-07-15

## What This Is

A copy of `public/stock_intraday_simulator.html` that adds a **Place Order** button per candidate row to place **real MIS market orders** on Angel One. Everything else (scanning, candidates, simulated trades, settings) is identical to the simulator and shares the same backend state.

## Key Decisions (user-confirmed)

- Market orders only, product MIS (INTRADAY), exchange NSE
- Quantity: same as simulator — `floor(100000 / live_ltp)` via `_orb_pos_size`
- **Entries only.** Exits are manual in the Angel One app (broker auto-squares MIS ~15:20)
- Orders go to a **separate funded Angel One account**, not the market-data account

## Backend (ai_engine)

### `config/credentials.py`
- `LIVE_API_KEY` (falls back to `API_KEY`), `LIVE_CLIENT_ID`, `LIVE_PIN`, `LIVE_TOTP_SECRET` env vars
- `live_credentials_configured()` — True when all three LIVE_* are set
- `get_live_smart_api()` — SmartConnect session for the funded account; raises if unconfigured

### `main.py`
- `_get_live_smart()` (near `_get_smart`, ~line 1200) — cached live session, 8h TTL, returns None (logged) if LIVE_* not set. Used ONLY for order placement; market data stays on `_get_smart()`/provider.
- `_live_tradingsymbol(token)` — token → `SYMBOL-EQ` map from `data/instrument_master.json`, module-cached (`_live_tsym_cache`)
- `_live_place_order_sync()` — LTP via `get_provider().get_ltp` (fallback `_orb_ltp_cache`) → qty → `placeOrder({variety NORMAL, ordertype MARKET, producttype INTRADAY, duration DAY})`. Handles both SDK return shapes (orderid string / full dict). Logs full request+response with `[LIVE-ORDER]` prefix.
- `POST /simulator/live-order` — body `{symbol, token, side}`; wraps sync fn in `run_in_executor`. 503 if creds missing or no LTP, 400 for bad side/qty/symbol, 502 for broker rejection.

## Frontend (`stock_intraday.html`)

- Branding: title "ORB Live Intraday", red LIVE hero tag, `.live-banner` status chip replacing "SIMULATOR · No real orders placed"
- Candidates table: 11th column "Order"; button rendered only for WAITING/TRIGGERED rows
- `placeLiveOrder(symbol, token, side, btn)` — confirm() dialog with qty/price/value estimate → POST `/api/simulator/live-order` → success: green `✓ #orderid` disabled; failure: red + alert + re-enable after 3s
- `_liveOrdersPlaced` object (`"SYMBOL|SIDE"` → order id) keeps buttons in placed state across the 5s state-poll re-renders. **In-memory only — page refresh forgets placed orders (buttons reappear). Broker duplicate protection is the only backstop after refresh.**

## Setup Before First Use (user action)

1. Enable TOTP for the funded account at smartapi.angelbroking.com/enable-totp
2. Add to `ai_engine/.env`: `LIVE_CLIENT_ID`, `LIVE_PIN`, `LIVE_TOTP_SECRET` (optionally `LIVE_API_KEY`)
3. Restart Python server
4. Off-market smoke test: tap Place Order → expect broker "market closed" rejection (proves auth + order path)

## Known Caveats

- `_liveOrdersPlaced` resets on page refresh — duplicate orders possible if user refreshes and taps again
- The simulated trade lifecycle (SL/target resolution) is entirely separate from the real position; the app does not know about fills, rejections after placement, or the real position's P/L
- SEBI language rules don't apply to this page's Place Order action (user's own personal account, own orders), but the page keeps the educational disclaimer footer

## Open Issues

- No order book / fill status display after placement
- No exit button (deliberate — user chose manual exits)
