# Context: data-layer

**Files:** `ai_engine/data/websocket_client.py`, `ai_engine/data/tick_buffer.py`, `ai_engine/data/candle_fetcher.py`, `ai_engine/data/instrument_master.py`, `ai_engine/storage/sqlite_store.py`, `ai_engine/storage/parquet_store.py`, `ai_engine/config/credentials.py`  
**Last updated:** 2026-05-23

---

## Purpose

Handles all data ingestion: live WebSocket ticks from AngelOne SmartAPI, historical candle fetch (with SQLite caching), instrument master (option chain tokens), and report/profile persistence.

---

## Credentials (`config/credentials.py`)

```python
get_smart_api()  # Returns authenticated SmartConnect instance
```

- Reads `API_KEY`, `CLIENT_ID`, `PIN`, `TOTP_SECRET` from `ai_engine/.env`
- Generates TOTP automatically via `pyotp`
- Raises `ValueError` at import time if any env var is missing
- Called in `main.py` lifespan startup — if `.env` is missing, the entire API server fails to start

---

## WebSocket Client (`data/websocket_client.py`)

```python
start_websocket(smart, tokens, market_state)
```

- Subscribes two feeds on `SmartWebSocketV2`:
  - **NFO options** — mode 3 (full quote: price, OI, volume, top-5 depth), `exchangeType: 2`
  - **NIFTY spot** — mode 1 (LTP only), `exchangeType: 1`, token `26000`
- All ticks route to `market_state.update(message)` — MarketState owns all parsing
- Auto-reconnects on close: recursive `start_websocket()` call after 3-second sleep
- `tokens` list is built from `InstrumentMaster` at startup — ATM CE+PE tokens for the nearest expiry

---

## Tick Buffer (`data/tick_buffer.py`)

File is nearly empty (1 line). Tick buffering/aggregation logic lives in `core/market_state.py` instead.

---

## Candle Fetcher (`data/candle_fetcher.py`)

```python
fetch_candles(smart, symbol_token, exchange, interval, from_date, to_date, use_cache=True) -> pd.DataFrame
```

Returns DataFrame with columns: `DateTime, Open, High, Low, Close, Volume` sorted ascending.

**Pagination** — AngelOne `getCandleData` has hard row limits per call:

| Interval | Max days per call |
|---|---|
| ONE_MINUTE | 30 |
| FIVE_MINUTE | 100 |
| FIFTEEN_MINUTE | 200 |
| ONE_HOUR | 400 |
| ONE_DAY | 2000 |

Auto-paginates with overlapping chunk deduplication by `DateTime` string.

**Cache flow:**
1. Check SQLite `candle_cache` — if hit, return immediately (no API call)
2. If miss, call API with pagination, write to SQLite, return DataFrame
3. `INSERT OR REPLACE` — repeated fetches for the same candle overwrite cleanly

**Timestamp format:** Angel One returns ISO timestamps (`2025-04-23T09:15:00+05:30`); fetcher strips to `"YYYY-MM-DD HH:MM"` (IST string, no timezone info).

---

## Instrument Master (`data/instrument_master.py`)

```python
class InstrumentMaster:
    load()                          # downloads or loads from file cache
    reload()                        # force re-download ignoring cache
    get_nearest_expiry()            # nearest future expiry string
    get_upcoming_expiries(n=4)      # next n expiry strings
    get_atm_options(ltp)            # {expiry, atm_strike, ce, pe} dicts
    get_atm_tokens(smart)           # returns (ce_token, pe_token) strings
    get_option_chain(ltp, range_size=5, expiry=None)  # list of {strike, ce, pe}
    get_nifty_futures_token()       # nearest NIFTY FUTIDX token (reads raw JSON)
```

- Source: `https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json`
- Cached to `data/instrument_master.json` — redownloaded if file is from a previous calendar day
- After load, filters to NIFTY OPTIDX NFO only — `self.data` contains only NIFTY options
- Strike prices: raw JSON stores `strike * 100` (integer paise); `.normalize()` divides by 100
- Expiry format: `DDMMMYYYY` uppercase (`"22MAY2025"`) — sort by `datetime.strptime`, never lexicographic
- `get_nifty_futures_token()` reads the raw unfiltered JSON (because `self.data` only has OPTIDX)

---

## SQLite Store (`storage/sqlite_store.py`)

DB path: `storage/tradezen.db` (relative to `sqlite_store.py`)

**Tables:**

| Table | Key | Purpose |
|---|---|---|
| `candle_cache` | `(symbol_token, exchange, interval, datetime)` UNIQUE | OHLCV candle cache |
| `daily_reports` | `date` PRIMARY KEY | Trade reports (one per day) |
| `market_profile_cache` | `(symbol_token, exchange, date, tick_size)` UNIQUE | Computed TPO profiles |

**Key functions:**

```python
get_conn() -> sqlite3.Connection          # opens DB, creates tables if needed
get_cached_candles(conn, ...)             # SELECT by range, returns Row objects
insert_candles(conn, ..., rows)           # INSERT OR REPLACE, commits
upsert_report(conn, date, data: dict)     # INSERT OR REPLACE daily_reports; returns generated_at
delete_report(conn, date) -> bool         # DELETE by date; returns True if row existed
list_reports(conn)                        # SELECT all, ordered by date DESC
get_report(conn, date)                    # SELECT single report by date
get_cached_profile(conn, ...)             # SELECT profile_json → json.loads
upsert_profile(conn, ...)                 # INSERT OR REPLACE market_profile_cache
```

**Report data:** stored as JSON blob in `data` column. `list_reports` and `get_report` `**json.loads(row["data"])` onto the returned dict.

**Generating a report for the same date overwrites** — `INSERT OR REPLACE` semantics. No history of regenerations is kept.

---

## Parquet Store (`storage/parquet_store.py`)

File is nearly empty (1 line). Parquet storage was planned but not implemented — yfinance data is used directly from memory in `swing_analyzer.py` and `ema_scenario` routes.

---

## Known Caveats

- `candle_fetcher.py` cache uses string range matching (`datetime >= from_date`) — partial cache hits are not detected. If you request a wider range than what's cached, the full range is re-fetched from the API.
- `InstrumentMaster.get_upcoming_expiries()` uses string lexicographic sort — **BUG if not fixed**: `"01MAY2026" < "24APR2026"` lexicographically. The code comment warns about this and uses `datetime.strptime` sort key.
- `tick_buffer.py` and `parquet_store.py` are stub files — don't reference them for actual logic.
- TOTP regenerates on every `get_smart_api()` call. Sessions are not cached — each startup logs in fresh.
- SQLite `get_conn()` calls `_ensure_tables()` on every connection open — safe but slightly redundant at high call rates.
