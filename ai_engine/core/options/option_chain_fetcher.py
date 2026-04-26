"""
Option chain fetcher — contract autocomplete search + full chain OI/price via SmartAPI.
Handles Module 2 (contract selector) and Module 4 (option chain engine).
"""

import json
import os
import logging
from datetime import datetime, timedelta
from calendar import monthrange

from storage.sqlite_store import get_conn

log = logging.getLogger(__name__)

_MASTER_PATH = "data/instrument_master.json"   # relative to ai_engine/ CWD
_BATCH_SIZE  = 50                               # SmartAPI getMarketData token limit per call
_raw_cache: list | None = None


# ── Instrument master helpers ──────────────────────────────────────────────────

def _load_raw() -> list:
    global _raw_cache
    if _raw_cache is None:
        with open(_MASTER_PATH, "r") as f:
            _raw_cache = json.load(f)
        log.info(f"Instrument master loaded: {len(_raw_cache):,} records")
    return _raw_cache


def _parse_expiry(s: str):
    try:
        return datetime.strptime(s, "%d%b%Y").date()
    except Exception:
        return None


def _to_strike(raw_val) -> float:
    """Angel One stores strike × 100. Divide back to real price."""
    return round(float(raw_val) / 100, 2)


# ── Public: expiry list ────────────────────────────────────────────────────────

def get_expiries(symbol: str) -> list[str]:
    """Return upcoming expiry strings (DDMMMYYYY) for a symbol, sorted chronologically."""
    raw    = _load_raw()
    today  = datetime.now().date()
    sym_up = symbol.strip().upper()
    seen: dict[str, datetime] = {}

    for item in raw:
        if (item.get("exch_seg") == "NFO"
                and item.get("instrumenttype") in ("OPTSTK", "OPTIDX")
                and item.get("name", "").upper() == sym_up):
            exp_str  = item.get("expiry", "")
            exp_date = _parse_expiry(exp_str)
            if exp_date and exp_date >= today:
                seen[exp_str] = exp_date

    return [s for s, _ in sorted(seen.items(), key=lambda x: x[1])]


# ── Public: autocomplete search ────────────────────────────────────────────────

def search_contracts(query: str, expiry_type: str = "weekly",
                     spot_price: float | None = None) -> list[dict]:
    """
    Return up to 40 NFO option contracts whose underlying name starts with `query`.
    expiry_type: "weekly" → nearest expiry  |  "monthly" → end-of-month expiry
    Marks the ATM strike when spot_price is supplied.
    """
    q = query.strip().upper()
    if len(q) < 2:
        return []

    raw   = _load_raw()
    today = datetime.now().date()

    nfo = [
        i for i in raw
        if i.get("exch_seg") == "NFO"
        and i.get("instrumenttype") in ("OPTSTK", "OPTIDX")
        and i.get("name", "").upper().startswith(q)
    ]
    if not nfo:
        return []

    # Collect future expiries
    expiry_map: dict[str, datetime] = {}
    for item in nfo:
        exp_str  = item.get("expiry", "")
        exp_date = _parse_expiry(exp_str)
        if exp_date and exp_date >= today:
            expiry_map[exp_str] = exp_date

    if not expiry_map:
        return []

    sorted_exp = sorted(expiry_map.items(), key=lambda x: x[1])
    target     = _nearest_monthly(sorted_exp) if expiry_type == "monthly" else sorted_exp[0][0]

    filtered = [i for i in nfo if i.get("expiry") == target]
    filtered.sort(key=lambda i: float(i.get("strike", 0)))

    # ATM detection
    atm_strike_raw: float | None = None
    if spot_price is not None and filtered:
        strikes_raw = sorted(set(float(i.get("strike", 0)) for i in filtered))
        if strikes_raw:
            atm_strike_raw = min(strikes_raw, key=lambda s: abs(_to_strike(s) - spot_price))

    result = []
    for item in filtered[:40]:
        strike_raw = float(item.get("strike", 0))
        result.append({
            "token":     item["token"],
            "symbol":    item["symbol"],
            "name":      item["name"],
            "expiry":    item["expiry"],
            "strike":    _to_strike(strike_raw),
            "type":      "CE" if item["symbol"].endswith("CE") else "PE",
            "lot_size":  int(item.get("lotsize", 1)),
            "tick_size": float(item.get("tick_size", 5)),
            "is_atm":    atm_strike_raw is not None and abs(strike_raw - atm_strike_raw) < 1,
        })
    return result


def _nearest_monthly(sorted_expiries: list) -> str:
    """Return the nearest expiry that falls on the last Thursday of its month."""
    for exp_str, exp_date in sorted_expiries:
        last_day = monthrange(exp_date.year, exp_date.month)[1]
        d = exp_date.replace(day=last_day)
        while d.weekday() != 3:        # 3 = Thursday
            d -= timedelta(days=1)
        if exp_date == d:
            return exp_str
    return sorted_expiries[-1][0]      # fallback: last available expiry


# ── Public: full option chain ──────────────────────────────────────────────────

def fetch_chain(smart, symbol: str, expiry: str,
                spot_price: float | None = None) -> dict:
    """
    Fetch full option chain for symbol+expiry with OI, LTP, IV/greeks, depth.
    Returns:
        {symbol, expiry, spot, chain: [{strike, ce:{...}, pe:{...}}], fetched_at}
    """
    instruments = _tokens_for(symbol, expiry)
    if not instruments:
        return {"error": f"No instruments found for {symbol} {expiry}", "chain": []}

    # Group by strike, keep only complete pairs
    by_strike: dict[float, dict] = {}
    for inst in instruments:
        s = inst["strike"]
        by_strike.setdefault(s, {})[inst["type"]] = inst

    valid = {s: v for s, v in by_strike.items() if "CE" in v and "PE" in v}
    if not valid:
        return {"error": "No complete CE/PE pairs found", "chain": []}

    # Batch-fetch market data
    all_tokens = []
    for v in valid.values():
        all_tokens += [v["CE"]["token"], v["PE"]["token"]]
    mdata = _batch_market_data(smart, all_tokens)

    def _leg(inst: dict) -> dict:
        d = mdata.get(str(inst["token"]), {})
        return {
            "token":        inst["token"],
            "symbol":       inst["symbol"],
            "lot_size":     inst["lot_size"],
            "ltp":          d.get("ltp"),
            "oi":           d.get("opnInterest"),
            "oi_change":    d.get("netchangeInOI"),
            "volume":       d.get("volume"),
            "iv":           d.get("impliedVolatility"),
            "delta":        d.get("delta"),
            "bid":          d.get("depth", {}).get("buy",  [{}])[0].get("price"),
            "ask":          d.get("depth", {}).get("sell", [{}])[0].get("price"),
            "depth": {
                "buy":  d.get("depth", {}).get("buy",  []),
                "sell": d.get("depth", {}).get("sell", []),
            },
        }

    chain = [
        {"strike": s, "ce": _leg(valid[s]["CE"]), "pe": _leg(valid[s]["PE"])}
        for s in sorted(valid)
    ]

    _save_oi_snapshot(symbol, expiry, chain)

    return {
        "symbol":     symbol.upper(),
        "expiry":     expiry.upper(),
        "spot":       spot_price,
        "chain":      chain,
        "fetched_at": datetime.now().strftime("%H:%M:%S"),
    }


def _tokens_for(symbol: str, expiry: str) -> list[dict]:
    """All option instruments for a symbol+expiry from the master file."""
    raw    = _load_raw()
    sym_up = symbol.strip().upper()
    exp_up = expiry.strip().upper()
    result = []
    for item in raw:
        if (item.get("exch_seg") == "NFO"
                and item.get("instrumenttype") in ("OPTSTK", "OPTIDX")
                and item.get("name", "").upper()   == sym_up
                and item.get("expiry", "").upper()  == exp_up):
            result.append({
                "token":     item["token"],
                "symbol":    item["symbol"],
                "strike":    _to_strike(item.get("strike", 0)),
                "type":      "CE" if item["symbol"].endswith("CE") else "PE",
                "lot_size":  int(item.get("lotsize", 1)),
                "tick_size": float(item.get("tick_size", 5)),
            })
    result.sort(key=lambda x: (x["strike"], x["type"]))
    return result


def _batch_market_data(smart, tokens: list[str], exchange: str = "NFO") -> dict:
    """
    Call SmartAPI getMarketData FULL for up to _BATCH_SIZE tokens at a time.
    Returns {token_str: row_dict}.
    """
    result = {}
    for i in range(0, len(tokens), _BATCH_SIZE):
        batch = tokens[i:i + _BATCH_SIZE]
        try:
            resp    = smart.getMarketData({"mode": "FULL", "exchangeTokens": {exchange: batch}})
            fetched = (resp or {}).get("data", {}).get("fetched") or []
            for row in fetched:
                result[str(row.get("symbolToken", ""))] = row
        except Exception as e:
            log.warning(f"getMarketData batch error (tokens {i}–{i+len(batch)}): {e}")
    return result


# ── OI snapshot (SQLite) ───────────────────────────────────────────────────────

def _ensure_oi_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS oi_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT NOT NULL,
            expiry     TEXT NOT NULL,
            strike     REAL NOT NULL,
            ce_oi      INTEGER,
            pe_oi      INTEGER,
            ce_ltp     REAL,
            pe_ltp     REAL,
            timestamp  TEXT NOT NULL
        )
    """)
    conn.commit()


def _save_oi_snapshot(symbol: str, expiry: str, chain: list):
    try:
        conn = get_conn()
        _ensure_oi_table(conn)
        now  = datetime.utcnow().isoformat()
        rows = [
            (symbol.upper(), expiry.upper(), s["strike"],
             s["ce"].get("oi"), s["pe"].get("oi"),
             s["ce"].get("ltp"), s["pe"].get("ltp"), now)
            for s in chain
        ]
        conn.executemany(
            "INSERT INTO oi_snapshots"
            " (symbol,expiry,strike,ce_oi,pe_oi,ce_ltp,pe_ltp,timestamp)"
            " VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        conn.close()
        log.debug(f"OI snapshot saved: {symbol} {expiry} ({len(rows)} strikes)")
    except Exception as e:
        log.warning(f"OI snapshot save error: {e}")


def get_oi_change_signals(symbol: str, expiry: str, chain: list) -> dict[float, dict]:
    """
    Compare current OI/LTP against the snapshot from 30–55 min ago.
    Returns {strike: {ce_signal, pe_signal}} using the 4-quadrant model:
      long_buildup  = price ↑ + OI ↑   (fresh long positions)
      short_buildup = price ↓ + OI ↑   (fresh short positions)
      short_covering= price ↑ + OI ↓   (shorts exiting)
      long_unwinding= price ↓ + OI ↓   (longs exiting)
    """
    signals: dict[float, dict] = {}
    try:
        conn     = get_conn()
        _ensure_oi_table(conn)
        now_utc  = datetime.utcnow()
        cutoff_hi = (now_utc - timedelta(minutes=30)).isoformat()
        cutoff_lo = (now_utc - timedelta(minutes=55)).isoformat()

        cur = conn.execute(
            """SELECT strike, ce_oi, pe_oi, ce_ltp, pe_ltp
               FROM oi_snapshots
               WHERE symbol=? AND expiry=? AND timestamp BETWEEN ? AND ?
               ORDER BY timestamp DESC""",
            (symbol.upper(), expiry.upper(), cutoff_lo, cutoff_hi),
        )
        prev = {float(row["strike"]): row for row in cur.fetchall()}
        conn.close()

        def _quad(price_up: bool, oi_up: bool) -> str:
            if price_up  and oi_up:  return "long_buildup"
            if not price_up and oi_up:   return "short_buildup"
            if price_up  and not oi_up:  return "short_covering"
            return "long_unwinding"

        for s in chain:
            strike = s["strike"]
            p      = prev.get(strike)
            if not p:
                signals[strike] = {"ce": "unchanged", "pe": "unchanged"}
                continue
            signals[strike] = {
                "ce": _quad(
                    (s["ce"].get("ltp") or 0) > (p["ce_ltp"] or 0),
                    (s["ce"].get("oi")  or 0) > (p["ce_oi"]  or 0),
                ),
                "pe": _quad(
                    (s["pe"].get("ltp") or 0) > (p["pe_ltp"] or 0),
                    (s["pe"].get("oi")  or 0) > (p["pe_oi"]  or 0),
                ),
            }
    except Exception as e:
        log.warning(f"OI change signal error: {e}")
    return signals
