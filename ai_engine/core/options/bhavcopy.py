"""
NSE F&O Bhavcopy — in-memory downloader, parser, and Black-Scholes engine.

Fetches NSE daily EOD archives, filters for the requested contract only,
and holds the result in a single in-memory cache. The cache is replaced
on every new contract search — nothing is written to disk.

NSE requires a valid browser session (cookies) for archive access.
We create one requests.Session, hit the homepage first to get cookies,
then download bhavcopy ZIPs. Multiple URL formats are tried in order.
"""

import io
import math
import logging
import datetime
import zipfile
from typing import Optional

log = logging.getLogger(__name__)

_MONTHS    = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_RISK_FREE = 0.065

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache: dict = {"key": None, "data": None}

# ── Persistent NSE session (reused across days in one search) ──────────────────
_nse_session = None


def _get_session():
    """Return a requests.Session with NSE cookies. Creates one if needed."""
    global _nse_session
    import requests
    if _nse_session is not None:
        return _nse_session

    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    })
    # Hit NSE homepage to acquire session cookies (nsit, nseappid, etc.)
    for warmup in [
        "https://www.nseindia.com/",
        "https://www.nseindia.com/market-data/live-equity-market",
    ]:
        try:
            s.get(warmup, timeout=12, headers={"Accept": "text/html,application/xhtml+xml,*/*"})
        except Exception:
            pass

    _nse_session = s
    return s


def _url_candidates(date: datetime.date) -> list[str]:
    """Return all known URL formats for a date's bhavcopy, best-first."""
    mon = _MONTHS[date.month - 1]
    dd  = f"{date.day:02d}"
    yr  = date.year
    fn  = f"fo_{dd}{mon}{yr}_bhav.csv.zip"
    return [
        # Format 1 — classic archives path (pre-2024)
        f"https://archives.nseindia.com/content/historical/DERIVATIVES/{yr}/{mon}/{fn}",
        # Format 2 — nsearchives subdomain variant
        f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{yr}/{mon}/{fn}",
        # Format 3 — flat BhavCopy folder
        f"https://archives.nseindia.com/content/fo/BhavCopy/{fn}",
        # Format 4 — nsearchives flat folder
        f"https://nsearchives.nseindia.com/content/fo/BhavCopy/{fn}",
    ]


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
) -> tuple[Optional[dict], str]:
    """
    Try every known URL format for this date. Parse the ZIP and return
    (matching_row_or_None, status).
    status: 'ok' | 'no_match' | 'holiday' | 'http_NNN' | 'error:TYPE'
    """
    sess = _get_session()
    raw  = None
    last_status = "error:no_url"

    for url in _url_candidates(date):
        try:
            resp = sess.get(url, timeout=20, headers={"Referer": "https://www.nseindia.com/"})
            if resp.status_code == 200:
                raw = resp.content
                break
            last_status = f"http_{resp.status_code}"
            log.debug(f"bhavcopy {date}: {resp.status_code} — {url}")
        except Exception as e:
            last_status = f"error:{type(e).__name__}"
            log.debug(f"bhavcopy {date}: {e} — {url}")

    if raw is None:
        if not last_status.startswith("http_404"):
            log.warning(f"bhavcopy {date}: all URLs failed, last={last_status}")
        return None, last_status

    try:
        zf       = zipfile.ZipFile(io.BytesIO(raw))
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        lines    = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
    except Exception as e:
        log.warning(f"bhavcopy {date}: unzip failed — {e}")
        return None, f"error:{type(e).__name__}"

    if len(lines) <= 1:
        return None, "holiday"

    headers = [h.strip() for h in lines[0].split(",")]

    def _flt(v):
        try:    return float(v.strip()) or None
        except: return None
    def _int(v):
        try:    return int(float(v.strip()))
        except: return 0

    sym_up = symbol.upper()
    opt_up = opt_type.upper()

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < len(headers):
            continue
        d = dict(zip(headers, cols))
        if d.get("INSTRUMENT", "") not in ("OPTIDX", "OPTSTK"):
            continue
        if d.get("SYMBOL", "").strip() != sym_up:
            continue
        if d.get("OPTION_TYP", "").strip() != opt_up:
            continue
        if _parse_expiry(d.get("EXPIRY_DT", "")) != expiry:
            continue
        row_strike = _flt(d.get("STRIKE_PR", "0")) or 0.0
        if abs(row_strike - strike) > 0.5:
            continue
        return {
            "trade_date": date.strftime("%Y-%m-%d"),
            "open":       _flt(d.get("OPEN", "")),
            "high":       _flt(d.get("HIGH", "")),
            "low":        _flt(d.get("LOW", "")),
            "close":      _flt(d.get("CLOSE", "")) or _flt(d.get("SETTLE_PR", "")),
            "contracts":  _int(d.get("CONTRACTS", "0")),
            "open_int":   _int(d.get("OPEN_INT", "0")),
            "chg_in_oi":  _int(d.get("CHG_IN_OI", "0")),
        }, "ok"

    return None, "no_match"


# ── Spot price ─────────────────────────────────────────────────────────────────

def _spot_series(symbol: str, from_date: datetime.date, to_date: datetime.date) -> dict[str, float]:
    import yfinance as yf
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol.upper(), f"{symbol.upper()}.NS")
    try:
        df = yf.Ticker(yf_sym).history(
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d", auto_adjust=True,
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

def _bs_price(S, K, T, r, sigma, opt):
    if T <= 0 or sigma <= 0 or S <= 0:
        return max(0.0, S - K) if opt == "CE" else max(0.0, K - S)
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    d2  = d1 - sigma * sqT
    if opt == "CE":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)

def _bs_theta(S, K, T, r, sigma, opt):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    d2  = d1 - sigma * sqT
    common = -(S * sigma * _npdf(d1)) / (2.0 * sqT)
    theta_yr = (common - r * K * math.exp(-r * T) * _ncdf(d2)  if opt == "CE"
                else common + r * K * math.exp(-r * T) * _ncdf(-d2))
    return theta_yr / 365.0

def _implied_vol(price, S, K, T, r, opt) -> Optional[float]:
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
        if p < price: lo = mid
        else:         hi = mid
    mid = (lo + hi) / 2.0
    return mid if abs(_bs_price(S, K, T, r, mid, opt) - price) < 1.0 else None


# ── Public API ─────────────────────────────────────────────────────────────────

def build_history(symbol: str, strike: float, expiry: str, opt_type: str) -> dict:
    """
    Download EOD data for the contract from NSE bhavcopy, enrich with
    spot / IV / theta, cache in memory. New contract search replaces cache.
    """
    global _cache, _nse_session
    cache_key = (symbol.upper(), strike, expiry, opt_type.upper())

    if _cache["key"] == cache_key and _cache["data"] is not None:
        log.info(f"bhavcopy cache hit: {cache_key}")
        return _cache["data"]

    # New search — reset session so fresh cookies are fetched
    _nse_session = None
    _cache = {"key": cache_key, "data": None}

    try:
        exp_dt  = datetime.date.fromisoformat(expiry)
    except Exception:
        return {"error": "Invalid expiry format. Use YYYY-MM-DD."}

    from_dt = exp_dt - datetime.timedelta(days=90)
    to_dt   = min(exp_dt, datetime.date.today())

    eod_rows: list[dict] = []
    stats: dict[str, int] = {}
    cur = from_dt
    while cur <= to_dt:
        if cur.weekday() < 5:
            row, status = _fetch_one_day(cur, symbol, strike, expiry, opt_type)
            stats[status] = stats.get(status, 0) + 1
            if row:
                eod_rows.append(row)
        cur += datetime.timedelta(days=1)

    log.info(f"bhavcopy {symbol} {strike} {opt_type} {expiry}: stats={stats} rows={len(eod_rows)}")

    if not eod_rows:
        http_err = {k: v for k, v in stats.items() if k.startswith("http_") and k != "http_404"}
        net_err  = {k: v for k, v in stats.items() if k.startswith("error:")}
        if http_err:
            codes = ", ".join(f"{k.split('_')[1]} ({v}x)" for k, v in http_err.items())
            return {"error": f"NSE archive returned HTTP errors: {codes}. Try again later."}
        if net_err:
            kinds = ", ".join(f"{k.split(':')[1]} ({v}x)" for k, v in net_err.items())
            return {"error": f"Network errors: {kinds}. Check internet connectivity."}
        no_match = stats.get("no_match", 0)
        holidays = stats.get("holiday", 0)
        all_404  = all(k == "http_404" for k in stats)
        if all_404:
            return {"error": (
                f"NSE archive returned 404 for all {sum(stats.values())} dates. "
                "NSE may have changed their archive URL structure. "
                "This feature relies on the public NSE bhavcopy archive which can change."
            )}
        return {"error": (
            f"No data for {symbol} {strike} {opt_type} expiry {expiry}. "
            f"({no_match} trading days had no row, {holidays} holidays). "
            "Verify strike and expiry are correct."
        )}

    spots = _spot_series(
        symbol,
        datetime.date.fromisoformat(eod_rows[0]["trade_date"]),
        exp_dt,
    )

    opt_up = opt_type.upper()
    ivs: list[Optional[float]] = []
    for row in eod_rows:
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = spots.get(td)
        T     = (exp_dt - datetime.date.fromisoformat(td)).days / 365.0
        ivs.append(_implied_vol(price, S, strike, T, _RISK_FREE, opt_up) if S and price else None)

    anchor_iv = next((v for v in ivs if v is not None), 0.20)

    enriched = []
    for i, row in enumerate(eod_rows):
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = spots.get(td)
        dte   = (exp_dt - datetime.date.fromisoformat(td)).days
        T     = dte / 365.0
        iv    = ivs[i]
        eff   = iv or anchor_iv
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
            "theo_price": round(_bs_price(S, strike, T, _RISK_FREE, anchor_iv, opt_up), 2) if S else None,
            "theta":      round(_bs_theta(S, strike, T, _RISK_FREE, eff, opt_up), 2) if S else None,
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
