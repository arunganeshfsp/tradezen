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
- Orders go to the **same Angel One account** as market data (user initially planned a separate funded account, then confirmed both client IDs are the same). The shared `_get_smart()` session is used for `placeOrder` — deliberately avoids a second session for the same client+key, which can invalidate tokens.

## Backend (`ai_engine/main.py`)

- `_live_tradingsymbol(token)` — token → `SYMBOL-EQ` map from `data/instrument_master.json`, module-cached (`_live_tsym_cache`)
- `_live_place_order_sync()` — LTP via `get_provider().get_ltp` (fallback `_orb_ltp_cache`) → qty → `smart.placeOrder({variety NORMAL, ordertype MARKET, producttype INTRADAY, duration DAY})` on the shared `_get_smart()` session. Handles both SDK return shapes (orderid string / full dict). Logs full request+response with `[LIVE-ORDER]` prefix.
- `POST /simulator/live-order` — body `{symbol, token, side}`; wraps sync fn in `run_in_executor`. 503 if session/LTP unavailable, 400 for bad side/qty/symbol, 502 for broker rejection.
- Node proxy: route explicitly registered in `routes/stockRoute.js` (`POST /api/simulator/live-order`, 20s timeout) — the Node server whitelists each simulator route individually; without this the request falls through to static HTML.

No changes to `config/credentials.py` — the existing `.env` (API_KEY, CLIENT_ID, PIN, TOTP_SECRET) is all that's needed. The account must have funds/margin for MIS orders.

## Frontend (`stock_intraday.html`)

- Branding: title "ORB Live Intraday", red LIVE hero tag, `.live-banner` status chip replacing "SIMULATOR · No real orders placed"
- **SIMULATED TRADES table** (not candidates): Place Order button in the last cell (beside Square Off) for OPEN trades when `_isLive`. Mirrors what the algo actually entered.
- `placeLiveOrder(symbol, side, btn)` — resolves token from `_stateData.candidates` by symbol, LTP from the open trade — confirm() dialog with qty/price/value estimate → POST `/api/simulator/live-order` → success: green `✓ #orderid` disabled; failure: red + alert + re-enable after 3s
- `_liveOrdersPlaced` object (`"SYMBOL|SIDE"` → order id) keeps buttons in placed state across the 5s state-poll re-renders. **In-memory only — page refresh forgets placed orders (buttons reappear). Broker duplicate protection is the only backstop after refresh.**

## Setup Before First Use (user action)

1. Load funds into the Angel One account (MIS ₹1L position needs ~₹20K margin)
2. Off-market smoke test: tap Place Order → expect broker "market closed" rejection (proves order path end-to-end)

## Known Caveats

- `_liveOrdersPlaced` resets on page refresh — duplicate orders possible if user refreshes and taps again
- The simulated trade lifecycle (SL/target resolution) is entirely separate from the real position; the app does not know about fills, rejections after placement, or the real position's P/L
- SmartAPI key must be a "Trading API" app type for placeOrder to work (unverified until first order attempt)

## Open Issues

- No order book / fill status display after placement
- No exit button (deliberate — user chose manual exits)
