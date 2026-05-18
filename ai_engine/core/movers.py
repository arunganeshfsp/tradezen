"""
Market Movers — top/bottom performing stocks across NSE indices.
Primary: NSE equity-stockIndices API (live, session-gated).
Fallback: yfinance (15-min delayed).
5-minute in-memory cache per index.
"""

import time
import logging
import urllib.parse
import requests

log = logging.getLogger(__name__)

# ── Fallback symbol lists ─────────────────────────────────────────────────────

_NIFTY50 = [
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
    "BAJAJ-AUTO","BAJAJFINSV","BAJFINANCE","BHARTIARTL","BPCL",
    "BRITANNIA","CIPLA","COALINDIA","DIVISLAB","DRREDDY",
    "EICHERMOT","ETERNAL","GRASIM","HCLTECH","HDFCBANK",
    "HDFCLIFE","HEROMOTOCO","HINDALCO","HINDUNILVR","ICICIBANK",
    "INDUSINDBK","INFY","ITC","JSWSTEEL","KOTAKBANK",
    "LT","M&M","MARUTI","NESTLEIND","NTPC",
    "ONGC","POWERGRID","RELIANCE","SBILIFE","SBIN",
    "SHRIRAMFIN","SUNPHARMA","TATACONSUM","TATAMOTORS","TATASTEEL",
    "TCS","TECHM","TITAN","TRENT","ULTRACEMCO",
]

_NIFTY_BANK = [
    "AXISBANK","BANDHANBNK","FEDERALBNK","HDFCBANK","ICICIBANK",
    "IDFCFIRSTB","INDUSINDBK","KOTAKBANK","PNB","SBIN",
    "AUBANK","BANKBARODA",
]

_NIFTY_IT = [
    "INFY","TCS","HCLTECH","WIPRO","TECHM",
    "PERSISTENT","LTIM","COFORGE","MPHASIS","OFSS",
]

_NSE_INDEX_MAP = {
    "nifty50":    "NIFTY 50",
    "nifty500":   "NIFTY 500",
    "banknifty":  "NIFTY BANK",
    "niftyit":    "NIFTY IT",
    "midcap100":  "NIFTY MIDCAP 100",
    "smallcap":   "NIFTY SMALLCAP 100",
}

_FALLBACK_SYMBOLS = {
    "nifty50":   _NIFTY50,
    "nifty500":  _NIFTY50,      # best-effort; NSE API preferred for full 500
    "banknifty": _NIFTY_BANK,
    "niftyit":   _NIFTY_IT,
    "midcap100": _NIFTY50,
    "smallcap":  _NIFTY50,
}

# ── NSE session ───────────────────────────────────────────────────────────────

_nse_session = None


def _get_session():
    global _nse_session
    if _nse_session:
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
        "Connection": "keep-alive",
    })
    for url in [
        "https://www.nseindia.com/",
        "https://www.nseindia.com/market-data/live-equity-market",
    ]:
        try:
            s.get(url, timeout=10, headers={"Accept": "text/html,*/*"})
            time.sleep(0.4)
        except Exception as e:
            log.debug(f"NSE equity warmup {url}: {e}")
    _nse_session = s
    return s


# ── NSE live fetch ────────────────────────────────────────────────────────────

def _fetch_nse(nse_index: str) -> list[dict]:
    sess = _get_session()
    url  = (f"https://www.nseindia.com/api/equity-stockIndices"
            f"?index={urllib.parse.quote(nse_index)}")
    try:
        resp = sess.get(url, timeout=20, headers={
            "Referer":            "https://www.nseindia.com/market-data/live-equity-market",
            "Accept":             "application/json",
            "X-Requested-With":   "XMLHttpRequest",
        })
        if resp.status_code != 200:
            log.warning(f"NSE equity API: HTTP {resp.status_code} for {nse_index}")
            return []
        rows = []
        for item in resp.json().get("data", []):
            sym = item.get("symbol", "").strip()
            if not sym or sym == nse_index:
                continue
            def _f(k):
                try: return round(float(item.get(k, 0) or 0), 2)
                except: return 0.0
            rows.append({
                "symbol":     sym,
                "ltp":        _f("lastPrice"),
                "prev_close": _f("previousClose"),
                "change":     _f("change"),
                "pct_change": _f("pChange"),
                "open":       _f("open"),
                "high":       _f("dayHigh"),
                "low":        _f("dayLow"),
                "volume":     int(float(item.get("totalTradedVolume", 0) or 0)),
                "year_high":  _f("52WH"),
                "year_low":   _f("52WL"),
            })
        return rows
    except Exception as e:
        log.warning(f"NSE equity API exception: {e}")
        return []


# ── yfinance fallback ─────────────────────────────────────────────────────────

def _fetch_yfinance(symbols: list[str]) -> list[dict]:
    import yfinance as yf
    import pandas as pd

    yf_syms = [s + ".NS" for s in symbols]
    try:
        df = yf.download(
            tickers=yf_syms, period="5d", interval="1d",
            auto_adjust=True, progress=False, group_by="ticker",
        )
        if df.empty:
            return []
        rows = []
        for sym, yf_sym in zip(symbols, yf_syms):
            try:
                hist = df[yf_sym] if yf_sym in df else (
                    df.xs(yf_sym, axis=1, level=1) if isinstance(df.columns, pd.MultiIndex) else None
                )
                if hist is None:
                    continue
                hist = hist.dropna()
                if len(hist) < 2:
                    continue
                prev = hist.iloc[-2]
                curr = hist.iloc[-1]
                pc   = float(prev["Close"])
                ltp  = float(curr["Close"])
                chg  = ltp - pc
                pct  = (chg / pc * 100) if pc else 0.0
                rows.append({
                    "symbol":     sym,
                    "ltp":        round(ltp, 2),
                    "prev_close": round(pc, 2),
                    "change":     round(chg, 2),
                    "pct_change": round(pct, 2),
                    "open":       round(float(curr["Open"]), 2),
                    "high":       round(float(curr["High"]), 2),
                    "low":        round(float(curr["Low"]),  2),
                    "volume":     int(float(curr["Volume"])),
                    "year_high":  None,
                    "year_low":   None,
                })
            except Exception:
                continue
        return rows
    except Exception as e:
        log.error(f"yfinance movers fallback failed: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

_cache: dict = {}
_CACHE_TTL   = 300  # 5 minutes


def fetch_movers(index: str = "nifty50") -> dict:
    """Return top/bottom 10 movers. NSE API primary, yfinance fallback, 5-min cache."""
    now    = time.time()
    cached = _cache.get(index)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    nse_index = _NSE_INDEX_MAP.get(index, "NIFTY 50")
    rows   = _fetch_nse(nse_index)
    source = "NSE Live"

    if not rows:
        log.info(f"NSE API unavailable for {nse_index}, using yfinance fallback")
        rows   = _fetch_yfinance(_FALLBACK_SYMBOLS.get(index, _NIFTY50))
        source = "yfinance (15-min delay)"

    if not rows:
        return {"error": f"No data available for {nse_index}"}

    rows.sort(key=lambda r: r["pct_change"], reverse=True)

    advancing = sum(1 for r in rows if r["pct_change"] > 0)
    declining = sum(1 for r in rows if r["pct_change"] < 0)
    unchanged = len(rows) - advancing - declining

    result = {
        "index":      nse_index,
        "source":     source,
        "count":      len(rows),
        "advancing":  advancing,
        "declining":  declining,
        "unchanged":  unchanged,
        "gainers":    rows[:10],
        "losers":     list(reversed(rows[-10:])),
        "fetched_at": int(now),
    }
    _cache[index] = {"ts": now, "data": result}
    return result
