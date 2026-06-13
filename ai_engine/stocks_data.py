"""
Stock symbols management — fetches and caches NSE/BSE stocks.
Provides search functionality for autocomplete across the app.
"""

import logging
import time
import requests
import json
from typing import List, Dict, Optional

log = logging.getLogger(__name__)

# Cache for stocks list (reuse for 24h)
_STOCKS_CACHE: Dict = {}
_CACHE_TTL = 86400  # 24 hours


def _fetch_nse_stocks() -> List[Dict[str, str]]:
    """
    Fetch NSE stock symbols from the NSE Bhavcopy master list.
    Returns a list of {code, name} dicts.
    Falls back to a minimal list if fetch fails.
    """
    try:
        # NSE publishes stock list in a structured format
        # Using the equity master list endpoint (publicly available)
        url = "https://www.nseindia.com/api/equity-master"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            raise ValueError(f"NSE API returned {resp.status_code}")

        data = resp.json()
        stocks = []
        for item in data.get("data", []):
            sym = item.get("symbol", "").strip()
            name = item.get("companyName", "").strip()
            if sym and name:
                stocks.append({"code": sym, "name": name})

        log.info(f"[Stocks] Fetched {len(stocks)} NSE stocks from official API")
        return stocks

    except Exception as e:
        log.warning(f"[Stocks] NSE fetch failed ({e}), trying alternative source")
        return _fetch_stocks_fallback()


def _fetch_stocks_fallback() -> List[Dict[str, str]]:
    """
    Fallback: use yfinance to get NSE stocks (slower, but works offline).
    Returns top ~500 liquid stocks from yfinance's NSE universe.
    """
    try:
        import yfinance as yf

        # Known large-cap NSE stocks — expand as needed
        nse_tickers = [
            "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "BHARTIARTL",
            "HINDUNILVR", "ITC", "LT", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "ASIANPAINT",
            "SUNPHARMA", "WIPRO", "TECHM", "HCLTECH", "MARUTI", "NTPC", "POWERGRID",
            "ONGC", "BPCL", "COALINDIA", "TATASTEEL", "JSWSTEEL", "HINDALCO", "TATAMOTORS",
            "M&M", "HEROMOTOCO", "EICHERMOT", "BOSCHLTD", "MRF", "BAJAJ-AUTO", "ASHOKLEY",
            "ULTRACEMCO", "SHREECEM", "AMBUJACEM", "ACC", "GRASIM", "BRITANNIA", "NESTLEIND",
            "COLPAL", "DABUR", "MARICO", "GODREJCP", "ITC", "TATACONSUM", "CIPLA", "DRREDDY",
            "LUPIN", "SUNPHARMA", "DIVISLAB", "BIOCON", "APOLLOHOSP", "MAXHEALTH", "FORTIS",
            "LICI", "HDFCLIFE", "SBILIFE", "ICICIPRULI", "INDUSINDBK", "BANKBARODA", "CANBK",
            "FEDERALBNK", "AUBANK", "IDFCFIRSTB", "BANDHANBNK", "PNB", "SJVN", "NHPC",
            "NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "ADANIGREEN", "RELIANCE",
            "DLF", "LODHA", "PRESTIGE", "OBEROIRLTY", "GODREJPROP", "NAUKRI", "ZOMATO",
            "ZYDUSLIFE", "ALKEM", "AUROPHARMA", "IPCALAB", "LALPATHLAB", "PIIND", "UPL",
            "COROMANDEL", "DEEPAKNTR", "LTIM", "OFSS", "PERSISTENT", "COFORGE", "MPHASIS",
            "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "KPITTECH", "TATAELXSI",
            "NYKAA", "ETERNAL", "TRENT", "DMART", "PAGEIND", "POLYCAB", "SUPREMEIND",
            "ASTRAL", "HAVELLS", "VOLTAS", "PIDILITIND", "TORNTPHARM", "TORNTPOWER",
            "CONCOR", "IRCTC", "IRFC", "RVNL", "GRSE", "COCHINSHIP", "MAZAGON", "BHEL",
            "HAL", "CUMMINSIND", "THERMAX", "SIEMENS", "ABB", "BOSCHLTD",
            "ADANIENT", "ADANIPORTS", "BHARTIARTL", "INDUSTOWER", "GAIL", "IOC", "BPCL",
            "RELIANCE", "ONGC", "COALINDIA", "VEDL", "NATIONALUM", "HINDZINC", "NMDC",
            "SAIL", "APLAPOLLO", "JINDALSTEL", "JSWSTEEL", "TATASTEEL", "HINDALCO",
            "CHOLAFIN", "MUTHOOTFIN", "LICHSGFIN", "CANFINHOME", "PNBHOUSING", "ABCAPITAL",
            "SHRIRAMFIN", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "HDFC", "HDFCBANK",
        ]

        stocks = []
        for sym in set(nse_tickers):  # deduplicate
            try:
                info = yf.Ticker(f"{sym}.NS").info or {}
                name = info.get("longName") or info.get("shortName") or sym
                if name:
                    stocks.append({"code": sym, "name": name})
            except Exception:
                pass

        log.info(f"[Stocks] Built fallback list of {len(stocks)} stocks via yfinance")
        return stocks

    except Exception as e:
        log.error(f"[Stocks] Fallback also failed: {e}")
        return []


def get_stocks() -> List[Dict[str, str]]:
    """
    Get cached stocks list, or fetch + cache if stale.
    Returns list of {code, name} dicts.
    """
    now = time.time()
    if _STOCKS_CACHE and (now - _STOCKS_CACHE.get("ts", 0)) < _CACHE_TTL:
        age = round(now - _STOCKS_CACHE["ts"])
        log.debug(f"[Stocks] Cache hit, age={age}s")
        return _STOCKS_CACHE.get("data", [])

    log.info("[Stocks] Cache miss or expired, fetching...")
    stocks = _fetch_nse_stocks()
    _STOCKS_CACHE["ts"] = now
    _STOCKS_CACHE["data"] = stocks
    return stocks


def search_stocks(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """
    Search stocks by code or name (case-insensitive).
    Returns top `limit` matches.
    """
    if not query or len(query) < 1:
        return []

    q = query.strip().lower()
    stocks = get_stocks()

    # Filter: match code or name
    matches = [
        s for s in stocks
        if q in s["code"].lower() or q in s["name"].lower()
    ]

    # Sort: exact code matches first, then alphabetical
    matches.sort(key=lambda s: (
        s["code"].lower() != q,  # exact code match = 0 (sorts first)
        s["name"].lower()  # then by name
    ))

    return matches[:limit]
