# Context: delta-matrix

**Page:** `public/delta_matrix.html` (direct URL only; not linked from nav or home)
**Files:** `ai_engine/core/indicators/delta_matrix.py`, `ai_engine/main.py` (Delta Matrix section after `/stocks/search`), `routes/stockRoute.js` (`GET /api/delta-matrix`), `ai_engine/test/test_delta_matrix.py`
**Created:** 2026-09-22

---

## What this is

A TradingView-style "Delta Matrix" table: one column per candle (5/15/30/60 min), with these rows: Close, Delta, Max Δ (Candle), Min Δ (Candle), Cum Delta, Delta/Vol %, Session Δ and Volume. It covers NIFTY futures (near month, NFO) and NSE equities. Phase 1 is candle-based. A live-tick delta (quote rule against best bid/ask) is deferred.

## How it computes (`core/indicators/delta_matrix.py`, no I/O)

- The input is **1-minute candles**. Every column is built from the 1-min bars inside it. That is what makes Max/Min Δ possible: they are the running delta's peak and trough across the intrabars.
- Columns are anchored to **09:15**, so a 60-min grid is 09:15 … 15:15, and the last bucket holds 15 minutes. Bars outside 09:15–15:29 are dropped.
- Each 1-min bar's volume is split into buyer- and seller-initiated volume. There is no aggressor side in the AngelOne data.
  - `updown` (default): the whole bar goes to the side it closed toward (close vs open, then close vs previous close, then the previous side). This is the same rule as TradingView intrabar up/down volume.
  - `clv`: the volume is split by where the close sits in the high-low range. It reuses `core/options/volume_delta.candle_delta`.
- Max/Min Δ track the running value **after** each intrabar and do not start from 0. A one-sided column can therefore have a positive Min Δ.
- **Cum Delta** runs from the first loaded bar, so its level depends on the lookback. **Session Δ** resets each date.
- **Delta/Vol %** is `|delta| / volume`.
- **Volume spike** means volume is at least 1.5× the mean of the previous 20 columns (`VOL_SPIKE_RATIO`, `VOL_SPIKE_LOOKBACK`).
- **Live** means the column contains `now` (a naive IST datetime).

## Endpoint (`GET /delta-matrix?symbol=&tf=&cols=&method=`)

- `symbol=NIFTY` (or `NIFTY FUT`) resolves to `im.get_nifty_futures_token()`. The result is cached per day in `_dm_fut_tok`, because that lookup parses the whole 36 MB master on every call. Any other symbol is matched against `_load_all_eq_stocks()` on the NSE segment.
- `cols` is clamped to 4–60. `lookback_days(tf, cols)` sets how many calendar days of 1-min history to fetch; one getCandleData call covers it.
- The data comes in two parts:
  - **Past sessions** are fetched once with `use_cache=False`, keyed `(token, exch, from, to)` in `_dm_past`. They are in-memory and FIFO-capped at 64 entries. They are written to SQLite because they are complete.
  - **Today** is refetched after a 15 s TTL during market hours (600 s otherwise), with `use_cache=False, write_cache=False`.
- **Never read the SQLite candle cache here.** It treats partial ranges as hits, which would freeze today's columns.
- **Never write today to SQLite.** The ORB backtest reads whole days with `use_cache=True`.
- Responses: 400 for a bad tf or method, 404 for an unknown symbol, 503 when there is no SmartAPI session.

## Frontend

- Halo navbar page with page-local `--bg*` vars. The dark var block is `:root:not([data-bs-theme="light"])` so that halo-aurora's light block could win. Light theme is currently disabled app-wide in `halo-aurora.js`.
- Cards use `dm-card*` class names, because Bootstrap's `.card` forces its own text colour.
- Symbol autocomplete: NIFTY FUT is pinned, and stocks come from `/api/stocks/search`, debounced, with a sequence guard against stale responses.
- Auto-refresh runs every 15 s only while `market_open`. It skips hidden tabs, and a tab becoming visible reloads only when the data is more than 15 s old. Requests carry a sequence id, so a slow response for an old symbol is dropped.
- Prefs are stored in `localStorage['tz_delta_matrix']`. `?symbol=&tf=` URL params override them.
- CSV export dumps all returned columns.
- Colours follow the reference screenshot:
  - Delta, Max and Min are shaded green or red, scaled to the largest value in their row.
  - Session Δ is blue or red.
  - Cum Δ is tinted by that column's delta sign.
  - Delta/Vol % is amber at 50% or more and light amber at 30–50%.
  - Volume is amber when it spikes.
- Carries the SEBI disclaimer. Copy uses "buyer-/seller-initiated" wording and no directives.

## Known caveats

- The split is an **estimate**, not true order flow. The legend says so.
- After a NIFTY monthly expiry the near-month token switches. Earlier sessions of the new contract show lighter volume, and the past-cache key changes, so there is one refetch.
- Stocks outside the EQ series (BE and others) are missing from `_load_all_eq_stocks()` and return 404.
- There are no Tamil (`data-ta`) strings yet, so the language toggle leaves this page in English.
- Tested offline with a harness that stubs `fetch_candles` and `_get_smart` using synthetic 1-min candles. It has **not yet been run against live AngelOne data**. The local global Python also lacks `python-multipart`, which main.py needs.

## Open issues

- Phase 2: live tick delta for the forming column (WebSocket mode 3, quote rule), which needs `data/tick_buffer.py` (still a stub).
- BANKNIFTY/FINNIFTY futures: `_dm_resolve` only special-cases NIFTY.
