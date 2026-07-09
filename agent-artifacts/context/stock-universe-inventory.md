# Context: stock-universe-inventory

**Files:**
- `public/mgmt/stock-inventory.html` — management UI
- `ai_engine/storage/sqlite_store.py` — `stock_universe` table DDL + 4 helpers
- `ai_engine/main.py` — 3 FastAPI endpoints
- `routes/stockRoute.js` — 3 Node proxy routes

**Last updated:** 2026-07-09 (initial implementation)

---

## 2026-07-09 — Initial Implementation

**What changed**
- New `stock_universe` table in SQLite: `(symbol TEXT, source TEXT, PRIMARY KEY (symbol, source))`. Source values: `nifty500`, `fno`.
- Helpers in `sqlite_store.py`: `stock_universe_import`, `stock_universe_get`, `stock_universe_counts`, `stock_universe_clear`.
- FastAPI endpoints: `GET /stock-inventory`, `POST /stock-inventory/import?source=`, `DELETE /stock-inventory?source=`.
- Node proxy routes in `stockRoute.js` for all three. File upload uses the raw-pipe pattern (same as `/options/parse-bhavcopy`).
- Management page at `public/mgmt/stock-inventory.html`: two tabs (Nifty 500 / F&O), import button per tab, client-side search, count badges.

**Why**
User wants a managed master list of stock symbols imported from NSE CSV / exchange XLSX files, separate from the Angel One instrument master (which is needed for API tokens and stays in `_load_fno_stocks()`).

**Parsing logic**
- CSV (Nifty 500): `pd.read_csv`, `SYMBOL` column, regex `^[A-Z][A-Z0-9\-&\.]{1,19}$` — automatically excludes "NIFTY 500" aggregate row (space in name fails regex).
- XLSX (F&O): `pd.read_excel(header=None)`, column 0 only, same regex.
- Import is always replace (DELETE + bulk INSERT), not append.

**Known caveats**
- This DB is standalone — `_load_fno_stocks()` and `_fetch_nifty500_symbols()` still use `instrument_master.json` and NSE live fetch respectively. The inventory does not feed the scanner/simulator yet.
- Chips highlighted in amber on the UI indicate symbols present in both Nifty 500 and F&O.
- No auth on the API endpoints; page is admin-accessible via `/mgmt/stock-inventory.html`.
