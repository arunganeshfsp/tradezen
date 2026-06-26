"""
NSE F&O Bhavcopy — in-memory downloader using NSE website's internal API.

Uses https://www.nseindia.com/api/historical/foBhavcopy?from=DD-Mon-YYYY&to=DD-Mon-YYYY
which powers the NSE website's own Bhavcopy download page.

One API call covers the full 90-day range (no per-day loops).
Result held in memory; replaced on every new contract search.
"""

import io
import math
import logging
import datetime
import zipfile
import time
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_MONTHS    = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_RISK_FREE = 0.065

_cache: dict = {"key": None, "data": None}
_nse_session = None

# Bhavcopy disk cache — one ZIP per trading date, cleared on each new date-range fetch
_BHAV_CACHE_DIR = Path(tempfile.gettempdir()) / "tradezen_bhavcopy"
_BHAV_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── NSE session ────────────────────────────────────────────────────────────────

def _get_session():
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

    # Warmup sequence — NSE requires cookies from the main site before API calls
    warmup_pages = [
        ("https://www.nseindia.com/",                               "text/html,application/xhtml+xml,*/*"),
        ("https://www.nseindia.com/market-data/fo-bhav-copy",       "text/html,application/xhtml+xml,*/*"),
    ]
    for url, accept in warmup_pages:
        try:
            s.get(url, timeout=15, headers={"Accept": accept})
            time.sleep(0.5)
        except Exception as e:
            log.debug(f"NSE warmup {url}: {e}")

    _nse_session = s
    return s


# ── Fetch the full date range via NSE API ──────────────────────────────────────

def _fetch_range_csv(from_date: datetime.date, to_date: datetime.date) -> Optional[list[str]]:
    """
    Call NSE's /api/historical/foBhavcopy for the full date range.
    Returns list of CSV lines (header + data), or None on failure.
    """
    sess = _get_session()

    # NSE expects "DD-Mon-YYYY" e.g. "01-Jan-2026"
    from_str = from_date.strftime("%d-%b-%Y")
    to_str   = to_date.strftime("%d-%b-%Y")

    url = (f"https://www.nseindia.com/api/historical/foBhavcopy"
           f"?from={from_str}&to={to_str}")

    try:
        resp = sess.get(url, timeout=60, headers={
            "Referer": "https://www.nseindia.com/market-data/fo-bhav-copy",
            "Accept":  "*/*",
            "X-Requested-With": "XMLHttpRequest",
        })
    except Exception as e:
        log.warning(f"NSE foBhavcopy API request failed: {e}")
        return None

    if resp.status_code != 200:
        log.warning(f"NSE foBhavcopy API: HTTP {resp.status_code} for {from_str}–{to_str}")
        return None

    content = resp.content

    # Response is a ZIP file
    if content[:2] == b'PK':
        try:
            zf       = zipfile.ZipFile(io.BytesIO(content))
            csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
            lines    = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
            log.info(f"NSE foBhavcopy API: got {len(lines)} lines (ZIP) for {from_str}–{to_str}")
            return lines
        except Exception as e:
            log.warning(f"NSE foBhavcopy ZIP parse failed: {e}")
            return None

    # Response is plain CSV
    text = resp.text
    if text.strip():
        lines = text.splitlines()
        log.info(f"NSE foBhavcopy API: got {len(lines)} lines (CSV) for {from_str}–{to_str}")
        return lines

    log.warning(f"NSE foBhavcopy API: empty response for {from_str}–{to_str}")
    return None


# ── Parse CSV lines for a specific contract ────────────────────────────────────

def _parse_expiry(s: str) -> str:
    """Try multiple date formats → 'YYYY-MM-DD'."""
    s = s.strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return s


def _date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD from NSE bhavcopy filename → 'YYYY-MM-DD'."""
    import re
    m = re.search(r"(\d{8})", filename)
    if m:
        try:
            return datetime.datetime.strptime(m.group(1), "%Y%m%d").strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def _auto_expiry(
    lines: list[str],
    symbol: str,
    strike: float,
    opt_type: str,
    trade_date: Optional[str],
) -> Optional[str]:
    """
    Find the best expiry for the given symbol+strike+opt_type from the CSV.
    Picks the nearest expiry >= trade_date (or the smallest available).
    """
    headers  = [h.strip() for h in lines[0].split(",")]
    is_new   = "TckrSymb" in headers or "XpryDt" in headers
    sym_up   = symbol.upper()
    opt_up   = opt_type.upper()
    expiries = set()

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < len(headers):
            continue
        d = dict(zip(headers, cols))
        if is_new:
            if d.get("TckrSymb", "").strip() != sym_up:
                continue
            if d.get("OptnTp", "").strip() != opt_up:
                continue
            try:
                row_strike = float(d.get("StrkPric", "0").strip())
            except Exception:
                continue
            if abs(row_strike - strike) > 0.5:
                continue
            exp = _parse_expiry(d.get("XpryDt", ""))
        else:
            if d.get("INSTRUMENT", "") not in ("OPTIDX", "OPTSTK"):
                continue
            if d.get("SYMBOL", "").strip() != sym_up:
                continue
            if d.get("OPTION_TYP", "").strip() != opt_up:
                continue
            try:
                row_strike = float(d.get("STRIKE_PR", "0").strip())
            except Exception:
                continue
            if abs(row_strike - strike) > 0.5:
                continue
            exp = _parse_expiry(d.get("EXPIRY_DT", ""))
        if exp:
            expiries.add(exp)

    if not expiries:
        return None
    sorted_exp = sorted(expiries)
    if trade_date:
        future = [e for e in sorted_exp if e >= trade_date]
        return future[0] if future else sorted_exp[0]
    return sorted_exp[0]


def _filter_contract(
    lines:    list[str],
    symbol:   str,
    strike:   float,
    expiry:   Optional[str],
    opt_type: str,
    trade_date_override: Optional[str] = None,
) -> tuple[list[dict], str]:
    """
    Parse CSV lines and return (rows, detected_expiry).
    If expiry is None or empty, auto-detects the nearest expiry from the file.
    Handles both old NSE format (SYMBOL/EXPIRY_DT/STRIKE_PR)
    and new NSE format (TckrSymb/XpryDt/StrkPric).
    """
    if not lines:
        return [], expiry or ""

    headers = [h.strip() for h in lines[0].split(",")]
    is_new  = "TckrSymb" in headers or "XpryDt" in headers

    # Auto-detect expiry if not provided
    resolved_expiry = expiry if expiry else _auto_expiry(
        lines, symbol, strike, opt_type, trade_date_override
    )
    if not resolved_expiry:
        return [], ""

    def _flt(v):
        try:    return float(str(v).strip()) or None
        except: return None
    def _int(v):
        try:    return int(float(str(v).strip()))
        except: return 0

    sym_up = symbol.upper()
    opt_up = opt_type.upper()
    rows   = []

    for line in lines[1:]:
        if not line.strip():
            continue
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < len(headers):
            continue
        d = dict(zip(headers, cols))

        if is_new:
            # ── New NSE format (BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv) ──
            if d.get("TckrSymb", "").strip() != sym_up:
                continue
            if d.get("OptnTp", "").strip() != opt_up:
                continue
            if _parse_expiry(d.get("XpryDt", "")) != resolved_expiry:
                continue
            row_strike = _flt(d.get("StrkPric", "0")) or 0.0
            if abs(row_strike - strike) > 0.5:
                continue
            tdate = _parse_expiry(d.get("TradDt", "")) or trade_date_override or ""
            rows.append({
                "trade_date": tdate,
                "open":       _flt(d.get("OpnPric", "")),
                "high":       _flt(d.get("HghPric", "")),
                "low":        _flt(d.get("LwPric", "")),
                "close":      _flt(d.get("ClsPric", "")) or _flt(d.get("SttlmPric", "")),
                "contracts":  _int(d.get("TtlTradgVol", "0")),
                "open_int":   _int(d.get("OpnIntrst", "0")),
                "chg_in_oi":  _int(d.get("ChngInOpnIntrst", "0")),
                "spot_raw":   _flt(d.get("UndrlyingVal", "")),
            })
        else:
            # ── Old NSE format (fo01MMMYYYY bhav.csv) ──
            if d.get("INSTRUMENT", "") not in ("OPTIDX", "OPTSTK"):
                continue
            if d.get("SYMBOL", "").strip() != sym_up:
                continue
            if d.get("OPTION_TYP", "").strip() != opt_up:
                continue
            if _parse_expiry(d.get("EXPIRY_DT", "")) != resolved_expiry:
                continue
            row_strike = _flt(d.get("STRIKE_PR", "0")) or 0.0
            if abs(row_strike - strike) > 0.5:
                continue
            trade_date = _parse_expiry(d.get("TIMESTAMP", "")) or trade_date_override or ""
            rows.append({
                "trade_date": trade_date,
                "open":       _flt(d.get("OPEN", "")),
                "high":       _flt(d.get("HIGH", "")),
                "low":        _flt(d.get("LOW", "")),
                "close":      _flt(d.get("CLOSE", "")) or _flt(d.get("SETTLE_PR", "")),
                "contracts":  _int(d.get("CONTRACTS", "0")),
                "open_int":   _int(d.get("OPEN_INT", "0")),
                "chg_in_oi":  _int(d.get("CHG_IN_OI", "0")),
            })

    rows.sort(key=lambda r: r["trade_date"])
    return rows, resolved_expiry


# ── Spot price ─────────────────────────────────────────────────────────────────

def _spot_series(symbol: str, from_date: datetime.date, to_date: datetime.date) -> dict[str, float]:
    import yfinance as yf
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol.upper(), f"{symbol.upper()}.NS")
    try:
        df = yf.Ticker(yf_sym).history(
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d", auto_adjust=False,
        )
        if df.empty:
            return {}
        df.index = df.index.normalize()
        return {idx.strftime("%Y-%m-%d"): float(row["Close"]) for idx, row in df.iterrows()}
    except Exception as e:
        log.warning(f"spot_series({symbol}): {e}")
        return {}


# ── Black-Scholes engine ───────────────────────────────────────────────────────

def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _npdf(x):
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
    common   = -(S * sigma * _npdf(d1)) / (2.0 * sqT)
    theta_yr = (common - r * K * math.exp(-r * T) * _ncdf(d2)   if opt == "CE"
                else common + r * K * math.exp(-r * T) * _ncdf(-d2))
    return theta_yr / 365.0

def _bs_delta(S, K, T, r, sigma, opt):
    if T <= 0 or sigma <= 0 or S <= 0:
        return (1.0 if S >= K else 0.0) if opt == "CE" else (-1.0 if S <= K else 0.0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return _ncdf(d1) if opt == "CE" else _ncdf(d1) - 1.0

def _bs_gamma(S, K, T, r, sigma, opt):
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    return _npdf(d1) / (S * sigma * sqT)

def _bs_vega(S, K, T, r, sigma, opt):
    """Vega per 1 % change in IV."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    sqT = math.sqrt(T)
    d1  = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqT)
    return S * _npdf(d1) * sqT * 0.01

def _implied_vol(price, S, K, T, r, opt) -> Optional[float]:
    if T <= 0 or price <= 0 or S <= 0:
        return None
    if price < max(0.0, S - K if opt == "CE" else K - S):
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

def enrich_rows(eod_rows: list[dict], symbol: str, strike: float, expiry: str, opt_type: str) -> dict:
    """Enrich already-filtered EOD rows with spot price, IV, theta, theoretical decay."""
    if not eod_rows:
        return {"error": "No matching rows found for this contract in the uploaded file."}

    try:
        exp_dt = datetime.date.fromisoformat(expiry)
    except Exception:
        return {"error": "Invalid expiry format."}

    # Use UndrlyingVal from file rows when available (new NSE format)
    # Fall back to yfinance only for rows that don't have it
    needs_yf = any(not row.get("spot_raw") for row in eod_rows)
    spots_yf: dict[str, float] = {}
    if needs_yf and eod_rows[0]["trade_date"]:
        spots_yf = _spot_series(
            symbol,
            datetime.date.fromisoformat(eod_rows[0]["trade_date"]),
            exp_dt,
        )

    def _spot(row: dict) -> Optional[float]:
        return row.get("spot_raw") or spots_yf.get(row["trade_date"])

    opt_up = opt_type.upper()
    ivs: list[Optional[float]] = []
    for row in eod_rows:
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = _spot(row)
        T     = (exp_dt - datetime.date.fromisoformat(td)).days / 365.0 if td else 0
        ivs.append(_implied_vol(price, S, strike, T, _RISK_FREE, opt_up) if S and price and T > 0 else None)

    anchor_iv = next((v for v in ivs if v is not None), 0.20)
    enriched  = []
    for i, row in enumerate(eod_rows):
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = _spot(row)
        dte   = (exp_dt - datetime.date.fromisoformat(td)).days if td else 0
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
            "delta":      round(_bs_delta(S, strike, T, _RISK_FREE, eff, opt_up), 4) if S else None,
            "gamma":      round(_bs_gamma(S, strike, T, _RISK_FREE, eff, opt_up), 6) if S else None,
            "vega":       round(_bs_vega(S, strike, T, _RISK_FREE, eff, opt_up), 2)  if S else None,
        })

    return {
        "symbol":    symbol.upper(),
        "strike":    strike,
        "expiry":    expiry,
        "opt_type":  opt_up,
        "anchor_iv": round(anchor_iv * 100, 1),
        "days":      enriched,
    }


def _read_lines(file_bytes: bytes, filename: str) -> tuple[list[str], Optional[str]]:
    """Read CSV lines from ZIP or raw CSV bytes. Returns (lines, trade_date)."""
    trade_date = _date_from_filename(filename)
    lines: list[str] = []
    if filename.lower().endswith(".zip") or file_bytes[:2] == b'PK':
        try:
            zf = zipfile.ZipFile(io.BytesIO(file_bytes))
            csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
            if not trade_date:
                trade_date = _date_from_filename(csv_name)
            lines = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
        except Exception as e:
            log.warning(f"ZIP read error {filename}: {e}")
    else:
        try:
            lines = file_bytes.decode("utf-8", errors="ignore").splitlines()
        except Exception as e:
            log.warning(f"CSV read error {filename}: {e}")
    return lines, trade_date


def parse_upload(file_bytes: bytes, filename: str,
                 symbol: str, strike: float, expiry: str, opt_type: str) -> dict:
    """Parse a single uploaded bhavcopy file. Expiry auto-detected when not provided."""
    lines, trade_date = _read_lines(file_bytes, filename)
    if len(lines) <= 1:
        return {"error": "Uploaded file appears to be empty."}
    eod_rows, resolved_expiry = _filter_contract(
        lines, symbol, strike, expiry or None, opt_type, trade_date
    )
    fmt = "new" if lines and "TckrSymb" in lines[0] else "old"
    log.info(f"upload: {symbol} {strike} {opt_type} expiry={resolved_expiry} → "
             f"{len(eod_rows)} rows/{len(lines)} lines fmt={fmt} date={trade_date}")
    if not eod_rows:
        headers = lines[0] if lines else "empty"
        return {"error": f"No matching rows found for {symbol} {strike} {opt_type} in the uploaded file. "
                         f"Detected columns: {headers[:120]}"}
    return enrich_rows(eod_rows, symbol, strike, resolved_expiry, opt_type)


def parse_upload_multi(files: list[tuple[bytes, str]],
                       symbol: str, strike: float, expiry: str, opt_type: str) -> dict:
    """
    Parse multiple uploaded bhavcopy files (one per trading day) and combine
    into a single enriched history for the theta decay chart.
    """
    all_rows: list[dict] = []
    resolved_expiry: Optional[str] = expiry or None

    for file_bytes, filename in files:
        lines, trade_date = _read_lines(file_bytes, filename)
        if len(lines) <= 1:
            continue
        rows, exp = _filter_contract(lines, symbol, strike, resolved_expiry, opt_type, trade_date)
        if exp and not resolved_expiry:
            resolved_expiry = exp
        all_rows.extend(rows)

    if not all_rows:
        return {"error": f"No matching rows found for {symbol} {strike} {opt_type} in any uploaded file."}

    # Deduplicate by trade_date — keep last seen per date
    by_date: dict[str, dict] = {}
    for row in all_rows:
        by_date[row["trade_date"]] = row
    combined = sorted(by_date.values(), key=lambda r: r["trade_date"])

    log.info(f"upload_multi: {symbol} {strike} {opt_type} expiry={resolved_expiry} → "
             f"{len(combined)} unique days from {len(files)} files")
    return enrich_rows(combined, symbol, strike, resolved_expiry or "", opt_type)


def build_history(symbol: str, strike: float, expiry: str, opt_type: str) -> dict:
    global _cache, _nse_session

    cache_key = (symbol.upper(), strike, expiry, opt_type.upper())
    if _cache["key"] == cache_key and _cache["data"] is not None:
        log.info(f"bhavcopy cache hit: {cache_key}")
        return _cache["data"]

    # New search — reset session for fresh cookies
    _nse_session = None
    _cache = {"key": cache_key, "data": None}

    try:
        exp_dt = datetime.date.fromisoformat(expiry)
    except Exception:
        return {"error": "Invalid expiry format. Use YYYY-MM-DD."}

    from_dt = exp_dt - datetime.timedelta(days=90)
    to_dt   = min(exp_dt, datetime.date.today())

    # Single API call for the full date range
    lines = _fetch_range_csv(from_dt, to_dt)
    if lines is None:
        return {
            "error": (
                "Could not fetch data from NSE. "
                "NSE's bhavcopy API requires an active browser session — "
                "the server's plain HTTP request is being blocked. "
                "Try refreshing, or wait a few minutes and retry."
            )
        }

    eod_rows, expiry = _filter_contract(lines, symbol, strike, expiry, opt_type)
    log.info(f"bhavcopy filter: {symbol} {strike} {opt_type} {expiry} → {len(eod_rows)} rows from {len(lines)} total")

    if not eod_rows:
        return {
            "error": (
                f"API returned data but no rows matched "
                f"{symbol} {strike} {opt_type} expiry {expiry}. "
                "Verify the strike and expiry date are correct."
            )
        }

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
        T     = (exp_dt - datetime.date.fromisoformat(td)).days / 365.0 if td else 0
        ivs.append(_implied_vol(price, S, strike, T, _RISK_FREE, opt_up) if S and price and T > 0 else None)

    anchor_iv = next((v for v in ivs if v is not None), 0.20)

    enriched = []
    for i, row in enumerate(eod_rows):
        td    = row["trade_date"]
        price = row["close"] or 0.0
        S     = spots.get(td)
        dte   = (exp_dt - datetime.date.fromisoformat(td)).days if td else 0
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
            "delta":      round(_bs_delta(S, strike, T, _RISK_FREE, eff, opt_up), 4) if S else None,
            "gamma":      round(_bs_gamma(S, strike, T, _RISK_FREE, eff, opt_up), 6) if S else None,
            "vega":       round(_bs_vega(S, strike, T, _RISK_FREE, eff, opt_up), 2)  if S else None,
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


def _purge_cache_outside_range(start: datetime.date, end: datetime.date):
    """Delete cached bhavcopy ZIPs that fall outside the requested date range."""
    for f in _BHAV_CACHE_DIR.glob("bhavcopy_*.zip"):
        try:
            d = datetime.datetime.strptime(f.stem.replace("bhavcopy_", ""), "%Y%m%d").date()
            if d < start or d > end:
                f.unlink()
                log.debug(f"Cleared out-of-range cache: {f.name}")
        except Exception:
            pass


def _fetch_archive_day(date: datetime.date) -> Optional[list[str]]:
    """
    Return CSV lines for a single trading day's F&O bhavcopy.
    Serves from disk cache when available; downloads from NSE archive otherwise.
    Cache lives in {tempdir}/tradezen_bhavcopy/ and is purged after 5 days.
    """
    import requests
    date_str  = date.strftime("%Y%m%d")
    cache_path = _BHAV_CACHE_DIR / f"bhavcopy_{date_str}.zip"

    # ── Serve from cache ───────────────────────────────────────────────────────
    if cache_path.exists():
        try:
            zf       = zipfile.ZipFile(cache_path)
            csv_name = next((n for n in zf.namelist() if n.endswith(".csv")), None)
            if csv_name:
                lines = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
                log.debug(f"Bhavcopy cache hit: {date_str}")
                return lines
        except Exception as e:
            log.debug(f"Bhavcopy cache read error {date_str}: {e}")
            cache_path.unlink(missing_ok=True)

    # ── Download from NSE archive ──────────────────────────────────────────────
    url = (f"https://nsearchives.nseindia.com/content/fo/"
           f"BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip")
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/124.0.0.0 Safari/537.36"),
        })
        if resp.status_code != 200:
            log.debug(f"Archive bhavcopy {date_str}: HTTP {resp.status_code}")
            return None
        if resp.content[:2] != b'PK':
            log.debug(f"Archive bhavcopy {date_str}: not a ZIP")
            return None

        # Save to cache before parsing
        cache_path.write_bytes(resp.content)

        zf       = zipfile.ZipFile(io.BytesIO(resp.content))
        csv_name = next((n for n in zf.namelist() if n.endswith(".csv")), None)
        if not csv_name:
            return None
        lines = zf.read(csv_name).decode("utf-8", errors="ignore").splitlines()
        log.info(f"Archive bhavcopy {date_str}: downloaded {len(lines)} lines, cached to disk")
        return lines
    except Exception as e:
        log.debug(f"Archive bhavcopy {date_str}: {e}")
        return None


def fetch_contract_history_nse(
    symbol: str,
    strike: float,
    expiry: str,
    opt_type: str,
    from_date: str,
    to_date: str,
) -> dict:
    """
    Fetch contract history from NSE daily bhavcopy archives (public CDN, no session needed).
    Downloads one ZIP per trading day, filters for the requested contract, enriches with Greeks.
    Dates in DD-MMM-YYYY format (e.g., "08-May-2026").
    """
    try:
        start_dt = datetime.datetime.strptime(from_date, "%d-%b-%Y").date()
        end_dt   = datetime.datetime.strptime(to_date,   "%d-%b-%Y").date()
        exp_dt   = datetime.datetime.strptime(expiry,    "%d-%b-%Y").date()
    except ValueError as e:
        return {"error": f"Invalid date format: {e}. Use DD-MMM-YYYY (e.g., 08-May-2026)"}

    exp_iso = exp_dt.strftime("%Y-%m-%d")

    _purge_cache_outside_range(start_dt, end_dt)  # drop ZIPs from previous queries

    all_rows: list[dict] = []
    current_dt = start_dt
    while current_dt <= end_dt:
        if current_dt.weekday() < 5:  # skip weekends
            lines = _fetch_archive_day(current_dt)
            if lines and len(lines) > 1:
                rows, _ = _filter_contract(
                    lines, symbol, strike, exp_iso, opt_type,
                    trade_date_override=current_dt.isoformat(),
                )
                for r in rows:
                    if not r.get("trade_date"):
                        r["trade_date"] = current_dt.isoformat()
                all_rows.extend(rows)
        current_dt += datetime.timedelta(days=1)

    if not all_rows:
        return {"error": (f"No data found for {symbol} {strike:.0f} {opt_type} "
                          f"expiry {expiry} from {from_date} to {to_date}. "
                          f"Verify symbol, strike, and expiry are correct.")}

    all_rows.sort(key=lambda r: r["trade_date"])
    return enrich_rows(all_rows, symbol, strike, exp_iso, opt_type)
