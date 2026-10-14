# Paper Trading — Module Context

## What this module is

Virtual portfolio simulator (tool #10, `public/paper_trading.html`). User places simulated BUY/SELL orders on NSE stocks or NFO option contracts at live prices, tracks open positions marked to market, and reviews closed-trade history with a cumulative realized P&L chart.

## Components

| Layer | File | Role |
|---|---|---|
| Engine | `ai_engine/execution/paper_trader.py` | DB schema + accounting (no price fetching) |
| API | `ai_engine/main.py` — "Paper Trading" section (before Daily Reports) | `/paper/*` endpoints + LTP resolution |
| Proxy | `routes/stockRoute.js` — `/api/paper/*` block | forwards to Python |
| Proxy helper | `services/aiService.js` `proxy()` | extended with optional `data` body param; now passes Python 4xx errors through (throws with `err.status`) instead of masking them as "unreachable" |
| Frontend | `public/paper_trading.html` | order ticket, positions, history, Chart.js progress chart |

## Other entry points into `/paper/order`

- `public/s1_monitor.html` (added 2026-10-14) — the signal card's "+ ADD TO TRADE LAB" button places a 1-lot BUY on the fired CE/PE at the current strike, using the signal's resolved option token/symbol/expiry (see `agent-artifacts/context/s1-monitor.md`). Falls back to the signal's premium as the fill price only if no token was resolved; otherwise lets `/paper/order` price it live, same as every other caller.

## Endpoints

- `GET /paper/account` — cash, realized P&L, counts
- `GET /paper/positions` — open positions + live LTPs + unrealized P&L (batch lookups)
- `GET /paper/history` — closed trades, newest first
- `GET /paper/quote?instrument=&symbol=&token=` — single LTP preview
- `POST /paper/order` — body `{instrument, symbol, side, qty | lots+lot_size, token?, price?, underlying?, expiry?, strike?, option_type?}`; executes at live LTP when `price` omitted
- `POST /paper/close/{id}` — body `{price?}`
- `POST /paper/reset` — body `{capital?}` (default ₹10,00,000)

## Accounting model (non-obvious)

- Single account row (`paper_account`, id=1), default capital ₹10,00,000.
- BUY (long): place → `cash -= qty*entry`; close → `cash += qty*exit`.
- SELL (short): place → `cash -= qty*entry` (notional blocked as margin — deliberately simple, no real margin model); close → `cash += qty*entry + (entry-exit)*qty`.
- Equity (computed client-side) = cash + Σ(qty×entry of open) + unrealized P&L.
- Option qty is stored in units (`lots × lot_size`); `lots`/`lot_size` kept for display.

## Price sources

- Stocks: `core.swing_analyzer.fetch_swing_prices` (Yahoo quote API, `.NS` suffix).
- Options: `core.options.option_chain_fetcher._batch_market_data` (SmartAPI getMarketData FULL by NFO token) — requires live SmartAPI session (`smart or _get_smart()`).
- Outside market hours / no session → LTP is None; order placement then errors with "Price unavailable" unless user enters a manual price (the UI has an editable Execution Price field for this).

## Known caveats

- **Stale note, corrected 2026-10-14:** this previously said "no per-user accounts — site has no auth on tool pages." That's no longer accurate — `_paper_user_id()` reads `X-User-Id` forwarded by Node after JWT verification (`tz_learn_token`), so accounts are per logged-in user; anonymous requests fall back to a shared `"anonymous"` account. Verify against `main.py` before trusting either description if this drifts again.
- Contract picker uses `/options/search` which only returns the nearest weekly or monthly expiry (existing limitation of `search_contracts`).
- Expired option positions are not auto-settled; user must close manually (LTP will go stale/None after expiry).
- `aiService.proxy()` behavior change affects all callers: Python 4xx now surfaces real error messages via thrown error with `.status`. Existing routes catch and return 500 with the message — an improvement, but note if debugging.
- **Mobile (added 2026-06-12):** below 700px the positions/history tables (`.table-wrap`) are hidden and replaced by stacked `.m-cards` — `renderPositions`/`renderHistory` render both layouts from the same data (`_lastPositions`/`_lastHistory` kept for re-render). Page now has the `T(en, ta)` helper + `window.onLangChange` (same pattern as wealth_timelapse) used for card labels and empty states. Toast messages remain EN-only — known gap if full localization is requested later.

## Open issues

- None deferred at build time. Possible future: order types (limit/SL), per-user portfolios once auth lands, auto square-off at expiry.
