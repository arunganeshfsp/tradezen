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
from typing import Optional

log = logging.getLogger(__name__)

_MONTHS    = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
_RISK_FREE = 0.065

_cache: dict = {"key": None, "data": None}
_nse_session = None


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


def fetch_contract_history_nse(
    symbol: str,
    strike: float,
    expiry: str,
    opt_type: str,
    from_date: str,
    to_date: str,
) -> dict:
    """
    Fetch contract history directly from NSE's historical derivatives API.
    Dates in DD-MMM-YYYY format (e.g., "08-May-2026").
    """
    sess = _get_session()

    # Determine instrument type based on symbol
    inst_type = "OPTIDX" if symbol.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY"] else "OPTSTK"

    url = (f"https://www.nseindia.com/api/historical/fo/derivatives"
           f"?instrumentType={inst_type}"
           f"&symbol={symbol.upper()}"
           f"&expiryDate={expiry}"
           f"&optionType={opt_type.upper()}"
           f"&strikePrice={strike}"
           f"&fromDate={from_date}"
           f"&toDate={to_date}")

    try:
        resp = sess.get(url, timeout=30, headers={
            "Referer": "https://www.nseindia.com/market-data/derivatives",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        })
    except Exception as e:
        log.warning(f"NSE derivatives API request failed: {e}")
        return {"error": f"NSE API request failed: {str(e)}"}

    if resp.status_code != 200:
        log.warning(f"NSE derivatives API: HTTP {resp.status_code}")
        return {"error": f"NSE API returned HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except Exception as e:
        log.warning(f"NSE derivatives API JSON parse failed: {e}")
        return {"error": "NSE API response parse failed"}

    rows = data.get("data", [])
    if not rows:
        return {"error": f"No data found for {symbol} {strike} {opt_type} expiry {expiry}"}

    # Convert NSE API response to enrich_rows format
    # NSE API response rows should be in chronological order
    start_dt = datetime.datetime.strptime(from_date, "%d-%b-%Y").date()
    eod_rows = []
    current_dt = start_dt
    for row in rows:
        eod_rows.append({
            "trade_date": current_dt.isoformat(),
            "open": float(row.get("openPrice") or 0),
            "high": float(row.get("highPrice") or 0),
            "low": float(row.get("lowPrice") or 0),
            "close": float(row.get("closePrice") or 0),
            "open_int": int(row.get("openInterest") or 0),
            "chg_in_oi": 0,  # NSE API doesn't provide this
            "contracts": int(row.get("contracts") or 0),
            "spot_raw": None,  # Will use yfinance fallback
        })
        current_dt += datetime.timedelta(days=1)

    if not eod_rows:
        return {"error": "No matching contract data from NSE"}

    # Enrich with Greeks (same logic as file upload)
    exp_dt = datetime.datetime.strptime(expiry, "%d-%b-%Y").date()
    spots = _spot_series(symbol, eod_rows[0]["trade_date"][:10], exp_dt)

    opt_up = opt_type.upper()
    ivs: list[Optional[float]] = []
    for row in eod_rows:
        td = row["trade_date"]
        price = row["close"] or 0.0
        S = spots.get(td)
        T = (exp_dt - datetime.date.fromisoformat(td)).days / 365.0 if td else 0
        ivs.append(_implied_vol(price, S, strike, T, _RISK_FREE, opt_up) if S and price and T > 0 else None)

    anchor_iv = next((v for v in ivs if v is not None), 0.20)

    enriched = []
    for i, row in enumerate(eod_rows):
        td = row["trade_date"]
        price = row["close"] or 0.0
        S = spots.get(td)
        dte = (exp_dt - datetime.date.fromisoformat(td)).days if td else 0
        T = dte / 365.0
        iv = ivs[i]
        eff = iv or anchor_iv
        enriched.append({
            "date": td,
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": round(price, 2),
            "open_int": row["open_int"],
            "chg_in_oi": row["chg_in_oi"],
            "contracts": row["contracts"],
            "spot": round(S, 2) if S else None,
            "dte": dte,
            "iv_pct": round(iv * 100, 1) if iv else None,
            "theo_price": round(_bs_price(S, strike, T, _RISK_FREE, anchor_iv, opt_up), 2) if S else None,
            "theta": round(_bs_theta(S, strike, T, _RISK_FREE, eff, opt_up), 2) if S else None,
        })

    return {
        "symbol": symbol.upper(),
        "strike": strike,
        "expiry": expiry,
        "opt_type": opt_up,
        "anchor_iv": round(anchor_iv * 100, 1),
        "days": enriched,
    }
