"""
Stock symbols management — fetches and caches NSE stocks.
Provides search functionality for autocomplete across the app.
"""

import logging
import time
import io
import requests
from typing import List, Dict

log = logging.getLogger(__name__)

_STOCKS_CACHE: Dict = {}
_CACHE_TTL = 86400  # 24 hours

# NSE Bhavcopy equity master — no cookies needed, has all ~2000 listed stocks
_NSE_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"

# Fallback hardcoded list for when NSE CSV is unavailable
_FALLBACK_STOCKS = [
    ("RELIANCE", "Reliance Industries"), ("TCS", "Tata Consultancy Services"),
    ("HDFCBANK", "HDFC Bank"), ("INFY", "Infosys"), ("ICICIBANK", "ICICI Bank"),
    ("SBIN", "State Bank of India"), ("BHARTIARTL", "Bharti Airtel"),
    ("HINDUNILVR", "Hindustan Unilever"), ("ITC", "ITC"), ("LT", "Larsen & Toubro"),
    ("AXISBANK", "Axis Bank"), ("KOTAKBANK", "Kotak Mahindra Bank"),
    ("BAJFINANCE", "Bajaj Finance"), ("ASIANPAINT", "Asian Paints"),
    ("SUNPHARMA", "Sun Pharmaceutical"), ("WIPRO", "Wipro"),
    ("TECHM", "Tech Mahindra"), ("HCLTECH", "HCL Technologies"),
    ("MARUTI", "Maruti Suzuki"), ("NTPC", "NTPC"), ("POWERGRID", "Power Grid Corp"),
    ("ONGC", "Oil & Natural Gas Corp"), ("BPCL", "Bharat Petroleum"),
    ("COALINDIA", "Coal India"), ("TATASTEEL", "Tata Steel"),
    ("JSWSTEEL", "JSW Steel"), ("HINDALCO", "Hindalco Industries"),
    ("TMPV", "Tata Motors"), ("M&M", "Mahindra & Mahindra"),
    ("HEROMOTOCO", "Hero MotoCorp"), ("EICHERMOT", "Eicher Motors"),
    ("BAJAJ-AUTO", "Bajaj Auto"), ("ULTRACEMCO", "UltraTech Cement"),
    ("AMBUJACEM", "Ambuja Cements"), ("GRASIM", "Grasim Industries"),
    ("BRITANNIA", "Britannia Industries"), ("NESTLEIND", "Nestle India"),
    ("COLPAL", "Colgate-Palmolive India"), ("DABUR", "Dabur India"),
    ("MARICO", "Marico"), ("GODREJCP", "Godrej Consumer Products"),
    ("TATACONSUM", "Tata Consumer Products"), ("CIPLA", "Cipla"),
    ("DRREDDY", "Dr. Reddy's Laboratories"), ("LUPIN", "Lupin"),
    ("DIVISLAB", "Divi's Laboratories"), ("APOLLOHOSP", "Apollo Hospitals"),
    ("HDFCLIFE", "HDFC Life Insurance"), ("SBILIFE", "SBI Life Insurance"),
    ("ICICIPRULI", "ICICI Prudential Life"), ("INDUSINDBK", "IndusInd Bank"),
    ("BANKBARODA", "Bank of Baroda"), ("FEDERALBNK", "Federal Bank"),
    ("IDFCFIRSTB", "IDFC First Bank"), ("ETERNAL", "Zomato (Eternal)"),
    ("NAUKRI", "Info Edge (Naukri)"), ("TRENT", "Trent"),
    ("DMART", "Avenue Supermarts"), ("POLYCAB", "Polycab India"),
    ("HAVELLS", "Havells India"), ("PIDILITIND", "Pidilite Industries"),
    ("ADANIENT", "Adani Enterprises"), ("ADANIPORTS", "Adani Ports"),
    ("HAL", "Hindustan Aeronautics"), ("IRCTC", "Indian Railway Catering"),
    ("IRFC", "Indian Railway Finance"), ("RVNL", "Rail Vikas Nigam"),
    ("GRSE", "Garden Reach Shipbuilders"), ("MAZDOCK", "Mazagon Dock"),
    ("BHEL", "Bharat Heavy Electricals"), ("CONCOR", "Container Corporation"),
    ("DLF", "DLF"), ("LODHA", "Macrotech Developers (Lodha)"),
    ("GODREJPROP", "Godrej Properties"), ("OBEROIRLTY", "Oberoi Realty"),
    ("OFSS", "Oracle Financial Services"), ("PERSISTENT", "Persistent Systems"),
    ("COFORGE", "Coforge"), ("MPHASIS", "Mphasis"),
    ("KPITTECH", "KPIT Technologies"), ("TATAELXSI", "Tata Elxsi"),
    ("CUMMINSIND", "Cummins India"), ("SIEMENS", "Siemens India"),
    ("ABB", "ABB India"), ("BOSCHLTD", "Bosch"), ("THERMAX", "Thermax"),
    ("LICHSGFIN", "LIC Housing Finance"), ("BAJAJFINSV", "Bajaj Finserv"),
    ("SHRIRAMFIN", "Shriram Finance"), ("CHOLAFIN", "Cholamandalam Investment"),
    ("MUTHOOTFIN", "Muthoot Finance"), ("UNOMINDA", "UNO Minda"),
    ("BERGEPAINT", "Berger Paints"), ("JUBLFOOD", "Jubilant Foodworks"),
    ("TVSMOTOR", "TVS Motor Company"), ("UNITDSPR", "United Spirits"),
    ("CHAMBLFERT", "Chambal Fertilisers"), ("EMAMILTD", "Emami"),
    ("NYKAA", "FSN E-Commerce (Nykaa)"), ("PAGEIND", "Page Industries"),
    ("TATACHEM", "Tata Chemicals"), ("JINDALSTEL", "Jindal Steel & Power"),
    ("SAIL", "Steel Authority of India"), ("NMDC", "NMDC"),
    ("HINDZINC", "Hindustan Zinc"), ("VEDL", "Vedanta"),
    ("GAIL", "GAIL India"), ("IOC", "Indian Oil Corporation"),
    ("SJVN", "SJVN"), ("NHPC", "NHPC"), ("TATAPOWER", "Tata Power"),
    ("ADANIGREEN", "Adani Green Energy"), ("ADANIPOWER", "Adani Power"),
    ("TORNTPHARM", "Torrent Pharmaceuticals"), ("ALKEM", "Alkem Laboratories"),
    ("AUROPHARMA", "Aurobindo Pharma"), ("IPCALAB", "IPCA Laboratories"),
    ("LALPATHLAB", "Dr Lal PathLabs"), ("PIIND", "PI Industries"),
    ("UPL", "UPL"), ("COROMANDEL", "Coromandel International"),
    ("DEEPAKNTR", "Deepak Nitrite"), ("ZYDUSLIFE", "Zydus Lifesciences"),
    ("BIOCON", "Biocon"), ("MAXHEALTH", "Max Healthcare"),
    ("FORTIS", "Fortis Healthcare"), ("LICI", "Life Insurance Corporation"),
    ("ASTRAL", "Astral"), ("VOLTAS", "Voltas"), ("SUPREMEIND", "Supreme Industries"),
    ("APLAPOLLO", "APL Apollo Tubes"), ("PNB", "Punjab National Bank"),
    ("CANBK", "Canara Bank"), ("AUBANK", "AU Small Finance Bank"),
    ("BANDHANBNK", "Bandhan Bank"), ("PNBHOUSING", "PNB Housing Finance"),
    ("CANFINHOME", "Can Fin Homes"), ("ABCAPITAL", "Aditya Birla Capital"),
    ("NATIONALUM", "National Aluminium"), ("ASHOKLEY", "Ashok Leyland"),
    ("ACC", "ACC"), ("PRESTIGE", "Prestige Estates"),
    ("INDUSTOWER", "Indus Towers"), ("TORNTPOWER", "Torrent Power"),
]


def _fetch_nse_csv() -> List[Dict[str, str]]:
    """
    Fetch all NSE-listed equities from NSE's public Bhavcopy CSV.
    No cookies required. Has ~2000 stocks.
    CSV columns: SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,...
    Only picks EQ series to avoid duplicates (BE, BL, etc.).
    """
    try:
        resp = requests.get(_NSE_CSV_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()

        stocks = []
        seen = set()
        lines = resp.text.splitlines()
        for line in lines[1:]:  # skip header
            parts = line.split(",")
            if len(parts) < 3:
                continue
            sym = parts[0].strip().strip('"')
            name = parts[1].strip().strip('"')
            series = parts[2].strip().strip('"')
            if not sym or not name:
                continue
            if series != "EQ":  # skip BE, BL, GB etc. to avoid duplicates
                continue
            if sym in seen:
                continue
            seen.add(sym)
            stocks.append({"code": sym, "name": name})

        log.info(f"[Stocks] Fetched {len(stocks)} NSE EQ stocks from Bhavcopy CSV")
        return stocks

    except Exception as e:
        log.warning(f"[Stocks] NSE CSV fetch failed ({e}), using fallback list")
        return [{"code": s[0], "name": s[1]} for s in _FALLBACK_STOCKS]


def get_stocks() -> List[Dict[str, str]]:
    """Get cached stocks list, refresh if older than 24h."""
    now = time.time()
    if _STOCKS_CACHE and (now - _STOCKS_CACHE.get("ts", 0)) < _CACHE_TTL:
        return _STOCKS_CACHE.get("data", [])

    log.info("[Stocks] Cache miss or expired, fetching...")
    stocks = _fetch_nse_csv()
    _STOCKS_CACHE["ts"] = now
    _STOCKS_CACHE["data"] = stocks
    return stocks


def search_stocks(query: str, limit: int = 8) -> List[Dict[str, str]]:
    """Search stocks by code or name (case-insensitive). Exact code match first."""
    if not query or len(query.strip()) < 1:
        return []

    q = query.strip().lower()
    stocks = get_stocks()

    matches = [
        s for s in stocks
        if q in s["code"].lower() or q in s["name"].lower()
    ]

    matches.sort(key=lambda s: (
        0 if s["code"].lower() == q else (1 if s["code"].lower().startswith(q) else 2),
        s["name"].lower()
    ))

    return matches[:limit]
