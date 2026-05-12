"""
NSE F&O Bhavcopy — in-memory downloader, parser, and Black-Scholes engine.

Fetches NSE daily EOD archives, filters for the requested contract only,
and holds the result in a single in-memory cache. The cache is replaced
on every new contract search — nothing is written to disk.

Source: https://archives.nseindia.com/content/historical/DERIVATIVES/
"""

import io
import math
import logging
import datetime
import zipfile
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

_NSE_BASE  = "https://archives.nseindia.com/content/historical/DERIVATIVES"
_MONTHS    = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_RISK_FREE = 0.065   # ~6.5% annualised India risk-free rate

# ── In-memory cache: holds exactly one contract's enriched result ──────────────
_cache: dict = {"key": None, "data": None}


# ── NSE download ───────────────────────────────────────────────────────────────

def _url(date: datetime.date) -> str:
    mon = _MONTHS[date.month - 1]
    return (f"{_NSE_BASE}/{date.year}/{mon}/"
            f"fo_{date.day:02d}{mon}{date.year}_bhav.csv.zip")


def _parse_expiry(s: str) -> str:
    """'29-MAY-2025' → '2025-05-29'"""
    try:
        return datetime.datetime.strptime(s.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except Exception:
        return s.strip()


def _fetch_one_day(
    date: datetime.date,
    symbol: str,
    strike: float,
    expiry: str,
    opt_type: str,
) -> Optional[dict]:
    """
    Download one day's bhavcopy zip, parse it in memory, and return the
    matching row dict — or None if no match / holiday / download error.
    """
    try:
        req = urllib.request.Request(
            _url(date),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
                "Referer":    "https://www.nseindia.com/",
                "Accept":     "*/*",
            }
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
    except Exception as e:
        log.debug(f"bhavcopy {date}: download failed — {e}")
        return None

    try:
        zf       = zipfile.ZipFile(io.BytesIO(raw))
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        lines    = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
    except Exception as e:
        log.debug(f"bhavcopy {date}: unzip failed — {e}")
        return None

    if len(lines) <= 1:
        return None  # holiday

    headers = [h.strip() for h in lines[0].split(",")]

    def _flt(v):
        try:    return float(v.strip()) or None
        except: return None
    def _int(v):
        try:    return int(float(v.strip()))
        except: return 0

    sym_up  = symbol.upper()
    opt_up  = opt_type.upper()

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < len(headers):
            continue
        d = dict(zip(headers, cols))
        if d.get("INSTRUMENT","") not in ("OPTIDX","OPTSTK"):
            continue
        if d.get("SYMBOL","").strip() != sym_up:
            continue
        if d.get("OPTION_TYP","").strip() != opt_up:
            continue
        row_expiry = _parse_expiry(d.get("EXPIRY_DT",""))
        if row_expiry != expiry:
            continue
        row_strike = _flt(d.get("STRIKE_PR","0")) or 0.0
        if abs(row_strike - strike) > 0.5:
            continue
        # Found the matching row
        return {
            "trade_date": date.strftime("%Y-%m-%d"),
            "open":       _flt(d.get("OPEN","")),
            "high":       _flt(d.get("HIGH","")),
            "low":        _flt(d.get("LOW","")),
            "close":      _flt(d.get("CLOSE","")) or _flt(d.get("SETTLE_PR","")),
            "contracts":  _int(d.get("CONTRACTS","0")),
            "open_int":   _int(d.get("OPEN_INT","0")),
            "chg_in_oi":  _int(d.get("CHG_IN_OI","0")),
        }
    return None


# ── Spot price ─────────────────────────────────────────────────────────────────

def _spot_series(symbol: str, from_date: datetime.date, to_date: datetime.date) -> dict[str, float]:
    """Fetch daily closes for the underlying via yfinance. Returns {date_str: close}."""
    import yfinance as yf
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol.upper(), f"{symbol.upper()}.NS")
    try:
        df = yf.Ticker(yf_sym).history(
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
        )
        if df.empty:
            return {}
        df.index = df.index.normalize()
        return {idx.strftime("%Y-%m-%d"): float(row["Close"]) for idx, row in df.iterrows()}
    except Exception as e:
        log.warning(f"spot_series({symbol}): {e}")
        return {}


# ── Black-Scholes engine ───────────────────────────────────────────────────────

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def _bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K) if opt == "CE" else max(0.0, K - S)
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    d2  = d1 - sigma * sqT
    if opt == "CE":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)

def _bs_theta(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Theta per calendar day (negative = daily decay)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    d2  = d1 - sigma * sqT
    common = -(S * sigma * _npdf(d1)) / (2.0 * sqT)
    if opt == "CE":
        theta_yr = common - r * K * math.exp(-r * T) * _ncdf(d2)
    else:
        theta_yr = common + r * K * math.exp(-r * T) * _ncdf(-d2)
    return theta_yr / 365.0

def _implied_vol(price: float, S: float, K: float, T: float, r: float, opt: str) -> Optional[float]:
    """Bisection IV solver."""
    if T <= 0 or price <= 0 or S <= 0:
        return None
    intrinsic = max(0.0, S - K) if opt == "CE" else max(0.0, K - S)
    if price < intrinsic:
        return None
    lo, hi = 0.001, 8.0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        p   = _bs_price(S, K, T, r, mid, opt)
        if abs(p - price) < 0.01:
            return mid
        if p < price:
            lo = mid
        else:
            hi = mid
    mid = (lo + hi) / 2.0
    return mid if abs(_bs_price(S, K, T, r, mid, opt) - price) < 1.0 else None


# ── Public API ─────────────────────────────────────────────────────────────────

def build_history(
    symbol:   str,
    strike:   float,
    expiry:   str,      # ISO "2025-05-29"
    opt_type: str,      # "CE" | "PE"
) -> dict:
    """
    Download EOD data for the contract from NSE bhavcopy, enrich with
    spot price / IV / theta, and return. Result is held in memory;
    calling with a different contract replaces the cache.
    """
    global _cache
    cache_key = (symbol.upper(), strike, expiry, opt_type.upper())

    if _cache["key"] == cache_key and _cache["data"] is not None:
        log.info(f"bhavcopy cache hit: {cache_key}")
        return _cache["data"]

    # Clear old cache immediately
    _cache = {"key": cache_key, "data": None}

    try:
        exp_dt  = datetime.date.fromisoformat(expiry)
    except Exception:
        return {"error": "Invalid expiry format. Use YYYY-MM-DD."}

    from_dt = exp_dt - datetime.timedelta(days=90)
    to_dt   = min(exp_dt, datetime.date.today())

    # Download each weekday and collect matching rows
    eod_rows: list[dict] = []
    cur = from_dt
    while cur <= to_dt:
        if cur.weekday() < 5:
            row = _fetch_one_day(cur, symbol, strike, expiry, opt_type)
            if row:
                eod_rows.append(row)
        cur += datetime.timedelta(days=1)

    if not eod_rows:
        return {"error": "No data found. This contract may not have traded in the selected period."}

    # Fetch underlying spot prices for the date range
    spots = _spot_series(
        symbol,
        datetime.date.fromisoformat(eod_rows[0]["trade_date"]),
        exp_dt,
    )

    opt_up = opt_type.upper()

    # First pass: compute per-day IV
    ivs: list[Optional[float]] = []
    for row in eod_rows:
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = spots.get(td)
        dte   = (exp_dt - datetime.date.fromisoformat(td)).days
        T     = dte / 365.0
        ivs.append(_implied_vol(price, S, strike, T, _RISK_FREE, opt_up) if S and price else None)

    # Anchor IV: first valid value (used for pure theta-decay curve)
    anchor_iv = next((v for v in ivs if v is not None), 0.20)

    enriched: list[dict] = []
    for i, row in enumerate(eod_rows):
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = spots.get(td)
        dte   = (exp_dt - datetime.date.fromisoformat(td)).days
        T     = dte / 365.0
        iv    = ivs[i]
        eff_iv = iv or anchor_iv

        theo  = round(_bs_price(S, strike, T, _RISK_FREE, anchor_iv, opt_up), 2) if S else None
        theta = round(_bs_theta(S, strike, T, _RISK_FREE, eff_iv,   opt_up), 2) if S else None

        enriched.append({
            "date":       td,
            "open":       row["open"],
            "high":       row["high"],
            "low":        row["low"],
            "close":      round(price, 2),
            "open_int":   row["open_int"],
            "chg_in_oi":  row["chg_in_oi"],
            "contracts":  row["contracts"],
            "spot":       round(S, 2) if S else None,
            "dte":        dte,
            "iv_pct":     round(iv * 100, 1) if iv else None,
            "theo_price": theo,
            "theta":      theta,
        })

    result = {
        "symbol":    symbol.upper(),
        "strike":    strike,
        "expiry":    expiry,
        "opt_type":  opt_up,
        "anchor_iv": round(anchor_iv * 100, 1),
        "days":      enriched,
    }
    _cache["data"] = result
    return result
