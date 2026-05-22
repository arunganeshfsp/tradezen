"""
S4 Swing Trading Analyser.
5-Pillar framework: Market Direction | Sector Strength | Stock Quality | Setup | Risk.
All computation is done here — no external AI API required.
5-minute in-memory cache per symbol for speed.
"""

import logging
import time
import datetime as _dt
import pandas as pd
from .indicators.ema import calculate_ema
from .indicators.rsi import calculate_rsi
from .indicators.macd import calculate_macd

log = logging.getLogger(__name__)

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

# ── Stock universe ─────────────────────────────────────────────────────────────

NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK",
    "INFY", "SBIN", "HINDUNILVR", "ITC", "LT",
    "KOTAKBANK", "AXISBANK", "BAJFINANCE", "WIPRO", "HCLTECH",
    "ONGC", "MARUTI", "NTPC", "M&M", "SUNPHARMA",
    "TITAN", "POWERGRID", "TATAMOTORS", "ADANIENT", "ADANIPORTS",
    "ULTRACEMCO", "BAJAJFINSV", "JSWSTEEL", "HINDALCO", "COALINDIA",
    "TATASTEEL", "NESTLEIND", "DIVISLAB", "TECHM", "CIPLA",
    "GRASIM", "ASIANPAINT", "BRITANNIA", "EICHERMOT", "HEROMOTOCO",
    "APOLLOHOSP", "TATACONSUM", "DRREDDY", "BPCL", "SBILIFE",
    "INDUSINDBK", "HDFCLIFE", "BAJAJ-AUTO", "SHRIRAMFIN", "BEL",
]

NIFTY_NEXT50 = [
    "AMBUJACEM", "BANKBARODA", "BERGEPAINT", "BOSCHLTD", "CANBK",
    "CHOLAFIN", "COLPAL", "CONCOR", "DABUR", "DLF",
    "GAIL", "GODREJCP", "HAVELLS", "HINDZINC", "ICICIGI",
    "ICICIPRULI", "INDHOTEL", "INDUSTOWER", "IOC", "IRCTC",
    "JINDALSTEL", "LICI", "LODHA", "LTIM", "LTTS",
    "LUPIN", "NAUKRI", "OBEROIRLTY", "OFSS", "PAGEIND",
    "PERSISTENT", "PIDILITIND", "PIIND", "POLYCAB", "RECLTD",
    "SAIL", "SRF", "TATAPOWER", "TIINDIA", "TORNTPHARM",
    "TORNTPOWER", "TRENT", "UBL", "VBL", "VOLTAS",
    "GODREJPROP", "MPHASIS", "ABBOTINDIA", "ALKEM", "DMART",
]

STOCK_INFO: dict[str, dict] = {
    # Nifty 50
    "RELIANCE":   {"name": "Reliance Industries",        "sector": "Energy"},
    "TCS":        {"name": "Tata Consultancy Services",  "sector": "IT"},
    "HDFCBANK":   {"name": "HDFC Bank",                  "sector": "Banking"},
    "BHARTIARTL": {"name": "Bharti Airtel",               "sector": "Telecom"},
    "ICICIBANK":  {"name": "ICICI Bank",                  "sector": "Banking"},
    "INFY":       {"name": "Infosys",                    "sector": "IT"},
    "SBIN":       {"name": "State Bank of India",        "sector": "Banking"},
    "HINDUNILVR": {"name": "Hindustan Unilever",         "sector": "FMCG"},
    "ITC":        {"name": "ITC",                        "sector": "FMCG"},
    "LT":         {"name": "Larsen & Toubro",            "sector": "Capital Goods"},
    "KOTAKBANK":  {"name": "Kotak Mahindra Bank",        "sector": "Banking"},
    "AXISBANK":   {"name": "Axis Bank",                  "sector": "Banking"},
    "BAJFINANCE": {"name": "Bajaj Finance",               "sector": "Financials"},
    "WIPRO":      {"name": "Wipro",                      "sector": "IT"},
    "HCLTECH":    {"name": "HCL Technologies",           "sector": "IT"},
    "ONGC":       {"name": "ONGC",                       "sector": "Energy"},
    "MARUTI":     {"name": "Maruti Suzuki",              "sector": "Auto"},
    "NTPC":       {"name": "NTPC",                       "sector": "Energy"},
    "M&M":        {"name": "Mahindra & Mahindra",        "sector": "Auto"},
    "SUNPHARMA":  {"name": "Sun Pharmaceutical",         "sector": "Pharma"},
    "TITAN":      {"name": "Titan Company",              "sector": "Consumer"},
    "POWERGRID":  {"name": "Power Grid Corp",            "sector": "Energy"},
    "TATAMOTORS": {"name": "Tata Motors",                "sector": "Auto"},
    "ADANIENT":   {"name": "Adani Enterprises",          "sector": "Diversified"},
    "ADANIPORTS": {"name": "Adani Ports",                "sector": "Infrastructure"},
    "ULTRACEMCO": {"name": "UltraTech Cement",           "sector": "Cement"},
    "BAJAJFINSV": {"name": "Bajaj Finserv",              "sector": "Financials"},
    "JSWSTEEL":   {"name": "JSW Steel",                  "sector": "Metal"},
    "HINDALCO":   {"name": "Hindalco",                   "sector": "Metal"},
    "COALINDIA":  {"name": "Coal India",                 "sector": "Energy"},
    "TATASTEEL":  {"name": "Tata Steel",                 "sector": "Metal"},
    "NESTLEIND":  {"name": "Nestle India",               "sector": "FMCG"},
    "DIVISLAB":   {"name": "Divi's Laboratories",        "sector": "Pharma"},
    "TECHM":      {"name": "Tech Mahindra",              "sector": "IT"},
    "CIPLA":      {"name": "Cipla",                      "sector": "Pharma"},
    "GRASIM":     {"name": "Grasim Industries",          "sector": "Cement"},
    "ASIANPAINT": {"name": "Asian Paints",               "sector": "Consumer"},
    "BRITANNIA":  {"name": "Britannia",                  "sector": "FMCG"},
    "EICHERMOT":  {"name": "Eicher Motors",              "sector": "Auto"},
    "HEROMOTOCO": {"name": "Hero MotoCorp",              "sector": "Auto"},
    "APOLLOHOSP": {"name": "Apollo Hospitals",           "sector": "Healthcare"},
    "TATACONSUM": {"name": "Tata Consumer",              "sector": "FMCG"},
    "DRREDDY":    {"name": "Dr. Reddy's Laboratories",  "sector": "Pharma"},
    "BPCL":       {"name": "BPCL",                       "sector": "Energy"},
    "SBILIFE":    {"name": "SBI Life Insurance",         "sector": "Insurance"},
    "INDUSINDBK": {"name": "IndusInd Bank",              "sector": "Banking"},
    "HDFCLIFE":   {"name": "HDFC Life Insurance",        "sector": "Insurance"},
    "BAJAJ-AUTO": {"name": "Bajaj Auto",                 "sector": "Auto"},
    "SHRIRAMFIN": {"name": "Shriram Finance",            "sector": "Financials"},
    "BEL":        {"name": "Bharat Electronics",        "sector": "Defence"},
    # Nifty Next 50
    "AMBUJACEM":  {"name": "Ambuja Cements",             "sector": "Cement"},
    "BANKBARODA": {"name": "Bank of Baroda",             "sector": "Banking"},
    "BERGEPAINT": {"name": "Berger Paints",              "sector": "Consumer"},
    "BOSCHLTD":   {"name": "Bosch",                      "sector": "Auto"},
    "CANBK":      {"name": "Canara Bank",                "sector": "Banking"},
    "CHOLAFIN":   {"name": "Cholamandalam Finance",      "sector": "Financials"},
    "COLPAL":     {"name": "Colgate-Palmolive",          "sector": "FMCG"},
    "CONCOR":     {"name": "Container Corp",             "sector": "Infrastructure"},
    "DABUR":      {"name": "Dabur India",                "sector": "FMCG"},
    "DLF":        {"name": "DLF",                        "sector": "Realty"},
    "GAIL":       {"name": "GAIL India",                 "sector": "Energy"},
    "GODREJCP":   {"name": "Godrej Consumer",            "sector": "FMCG"},
    "HAVELLS":    {"name": "Havells India",              "sector": "Consumer"},
    "HINDZINC":   {"name": "Hindustan Zinc",             "sector": "Metal"},
    "ICICIGI":    {"name": "ICICI General Insurance",    "sector": "Insurance"},
    "ICICIPRULI": {"name": "ICICI Prudential Life",      "sector": "Insurance"},
    "INDHOTEL":   {"name": "Indian Hotels",              "sector": "Consumer"},
    "INDUSTOWER": {"name": "Indus Towers",               "sector": "Telecom"},
    "IOC":        {"name": "Indian Oil Corp",            "sector": "Energy"},
    "IRCTC":      {"name": "IRCTC",                      "sector": "Infrastructure"},
    "JINDALSTEL": {"name": "Jindal Steel",               "sector": "Metal"},
    "LICI":       {"name": "LIC India",                  "sector": "Insurance"},
    "LODHA":      {"name": "Lodha (Macrotech)",          "sector": "Realty"},
    "LTIM":       {"name": "LTIMindtree",                "sector": "IT"},
    "LTTS":       {"name": "L&T Technology Services",   "sector": "IT"},
    "LUPIN":      {"name": "Lupin",                      "sector": "Pharma"},
    "NAUKRI":     {"name": "Info Edge (Naukri)",         "sector": "IT"},
    "OBEROIRLTY": {"name": "Oberoi Realty",              "sector": "Realty"},
    "OFSS":       {"name": "Oracle Financial Services",  "sector": "IT"},
    "PAGEIND":    {"name": "Page Industries",            "sector": "Consumer"},
    "PERSISTENT": {"name": "Persistent Systems",         "sector": "IT"},
    "PIDILITIND": {"name": "Pidilite Industries",        "sector": "Consumer"},
    "PIIND":      {"name": "PI Industries",              "sector": "Pharma"},
    "POLYCAB":    {"name": "Polycab India",              "sector": "Consumer"},
    "RECLTD":     {"name": "REC Limited",                "sector": "Energy"},
    "SAIL":       {"name": "Steel Authority of India",   "sector": "Metal"},
    "SRF":        {"name": "SRF",                        "sector": "Chemicals"},
    "TATAPOWER":  {"name": "Tata Power",                 "sector": "Energy"},
    "TIINDIA":    {"name": "Tube Investments of India",  "sector": "Auto"},
    "TORNTPHARM": {"name": "Torrent Pharma",             "sector": "Pharma"},
    "TORNTPOWER": {"name": "Torrent Power",              "sector": "Energy"},
    "TRENT":      {"name": "Trent",                      "sector": "Consumer"},
    "UBL":        {"name": "United Breweries",           "sector": "Consumer"},
    "VBL":        {"name": "Varun Beverages",            "sector": "FMCG"},
    "VOLTAS":     {"name": "Voltas",                     "sector": "Consumer"},
    "GODREJPROP": {"name": "Godrej Properties",         "sector": "Realty"},
    "MPHASIS":    {"name": "Mphasis",                    "sector": "IT"},
    "ABBOTINDIA": {"name": "Abbott India",               "sector": "Pharma"},
    "ALKEM":      {"name": "Alkem Laboratories",         "sector": "Pharma"},
    "DMART":      {"name": "Avenue Supermarts (D-Mart)", "sector": "Consumer"},
}

# Sector index symbols for yfinance (sector 1-month performance vs Nifty)
SECTOR_INDICES: dict[str, str] = {
    "IT":             "^CNXIT",
    "Banking":        "^NSEBANK",
    "Pharma":         "^CNXPHARMA",
    "Auto":           "^CNXAUTO",
    "FMCG":           "^CNXFMCG",
    "Metal":          "^CNXMETAL",
    "Realty":         "^CNXREALTY",
    "Energy":         "^CNXENERGY",
    "Financials":     "^CNXFIN",
    "Consumer":       "^CNXCONSUM",
    "Healthcare":     "^CNXPHARMA",
    "Cement":         "^CNXINFRA",
    "Capital Goods":  "^CNXINFRA",
    "Infrastructure": "^CNXINFRA",
    "Insurance":      "^CNXFIN",
    "Telecom":        "^CNXIT",
    "Defence":        "^CNXINFRA",
    "Chemicals":      "^CNXPHARMA",
    "Diversified":    "^NSEI",
    "Realty":         "^CNXREALTY",
}

_CACHE: dict = {}
_CACHE_TTL_STOCK = 300    # 5 min per stock
_CACHE_TTL_MARKET = 600   # 10 min for Nifty / VIX / sector data


# ── Indicator helpers ──────────────────────────────────────────────────────────

def _atr14(df: pd.DataFrame) -> float:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    prev_close = cl.shift(1)
    tr = pd.concat([
        hi - lo,
        (hi - prev_close).abs(),
        (lo - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.ewm(span=14, adjust=False).mean().iloc[-1])


# ── Market & sector data fetchers ──────────────────────────────────────────────

def _fetch_nifty_data() -> tuple:
    """(nifty_close, nifty_weekly_ema50, nifty_1m_chg) — 10-min cache."""
    key = "__nifty__"
    c = _CACHE.get(key)
    if c and time.time() - c["ts"] < _CACHE_TTL_MARKET:
        return c["data"]

    import yfinance as yf
    daily  = yf.Ticker("^NSEI").history(period="1y",  interval="1d",  auto_adjust=True)
    weekly = yf.Ticker("^NSEI").history(period="2y",  interval="1wk", auto_adjust=True)

    if daily.empty or weekly.empty:
        raise ValueError("Failed to fetch Nifty data")

    nifty_close  = float(daily["Close"].iloc[-1])
    ema50_weekly = float(calculate_ema(weekly["Close"], 50).iloc[-1])
    ref_idx      = -22 if len(daily) >= 22 else 0
    nifty_1m_chg = round((nifty_close - float(daily["Close"].iloc[ref_idx])) /
                          float(daily["Close"].iloc[ref_idx]) * 100, 2)

    result = (nifty_close, ema50_weekly, nifty_1m_chg)
    _CACHE[key] = {"ts": time.time(), "data": result}
    return result


def _fetch_vix() -> float | None:
    key = "__vix__"
    c = _CACHE.get(key)
    if c and time.time() - c["ts"] < _CACHE_TTL_MARKET:
        return c["data"]

    import yfinance as yf
    try:
        hist = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d")
        vix  = float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        vix = None

    _CACHE[key] = {"ts": time.time(), "data": vix}
    return vix


def _fetch_sector_1m(sector: str) -> float:
    key = f"__sec_{sector}__"
    c = _CACHE.get(key)
    if c and time.time() - c["ts"] < _CACHE_TTL_MARKET:
        return c["data"]

    idx_sym = SECTOR_INDICES.get(sector, "^NSEI")
    import yfinance as yf
    try:
        hist = yf.Ticker(idx_sym).history(period="2mo", interval="1d", auto_adjust=True)
        if len(hist) >= 22:
            chg = round((float(hist["Close"].iloc[-1]) - float(hist["Close"].iloc[-22])) /
                         float(hist["Close"].iloc[-22]) * 100, 2)
        else:
            chg = 0.0
    except Exception:
        chg = 0.0

    _CACHE[key] = {"ts": time.time(), "data": chg}
    return chg


def _fetch_stock_daily(symbol: str) -> tuple:
    """(df_daily, mcap_cr) — 5-min cache."""
    key = f"__s_{symbol}__"
    c = _CACHE.get(key)
    if c and time.time() - c["ts"] < _CACHE_TTL_STOCK:
        return c["data"]

    import yfinance as yf
    yf_sym = symbol + ".NS"
    ticker = yf.Ticker(yf_sym)
    daily  = ticker.history(period="1y", interval="1d", auto_adjust=True)

    if daily.empty or len(daily) < 50:
        raise ValueError(f"Insufficient data for {symbol}")

    # Market cap in Crores (INR). fast_info is lightweight.
    mcap_cr = 99999.0
    try:
        fi = ticker.fast_info
        raw = getattr(fi, "market_cap", None) or 0
        if raw > 0:
            mcap_cr = round(raw / 1e7, 0)  # USD → INR ~8.3 already factored by Yahoo
    except Exception:
        pass

    result = (daily, mcap_cr)
    _CACHE[key] = {"ts": time.time(), "data": result}
    return result


# ── Setup detection ────────────────────────────────────────────────────────────

def _setup_a(df: pd.DataFrame) -> tuple[bool, str]:
    """EMA Pullback: uptrend + pullback to EMA21 + volume dry + bounce."""
    close  = df["Close"]
    volume = df["Volume"]
    ema21  = calculate_ema(close, 21)
    ema50  = calculate_ema(close, 50)

    if not (float(close.iloc[-1]) > float(ema21.iloc[-1]) > float(ema50.iloc[-1])):
        return False, "Not in EMA21 > EMA50 uptrend"

    recent_low   = float(df["Low"].iloc[-8:-1].min())
    ema21_avg    = float(ema21.iloc[-8:-1].mean())
    near_ema21   = abs(recent_low - ema21_avg) / ema21_avg <= 0.018

    vol_avg20    = float(volume.iloc[-25:-5].mean()) if len(volume) >= 25 else float(volume.mean())
    vol_pullback = float(volume.iloc[-6:-1].mean())
    vol_dry      = vol_pullback < vol_avg20 * 0.90

    bounce = float(close.iloc[-1]) > float(close.iloc[-2])

    if near_ema21 and bounce:
        extra = " with drying volume" if vol_dry else " (volume not fully dry yet)"
        return True, f"Pullback to EMA21 ({ema21.iloc[-1]:.0f}){extra}, bounce confirmed"

    return False, "No EMA pullback setup"


def _setup_b(df: pd.DataFrame) -> tuple[bool, str]:
    """Consolidation Breakout: tight range + volume surge on breakout."""
    close  = df["Close"]
    volume = df["Volume"]
    high   = df["High"]
    low    = df["Low"]

    consol_h = float(high.iloc[-20:-1].max())
    consol_l = float(low.iloc[-20:-1].min())
    if consol_l <= 0:
        return False, "Invalid price data"

    range_pct = (consol_h - consol_l) / consol_l * 100
    if range_pct > 8:
        return False, f"Range too wide ({range_pct:.1f}%) — not a consolidation"

    vol_avg20   = float(volume.iloc[-21:].mean())
    vol_today   = float(volume.iloc[-1])
    today_close = float(close.iloc[-1])

    breakout    = today_close > consol_h * 1.001
    vol_surge   = vol_today >= vol_avg20 * 1.5
    near_break  = today_close >= consol_h * 0.985

    if breakout and vol_surge:
        return True, (f"Breakout above ₹{consol_h:.0f} consolidation "
                      f"with {vol_today/vol_avg20*100:.0f}% volume surge")
    if near_break and range_pct <= 6:
        return True, (f"Tight range ₹{consol_l:.0f}–₹{consol_h:.0f} "
                      f"({range_pct:.1f}%), coiling near breakout zone")

    return False, f"No breakout (range {range_pct:.1f}%, needs volume surge)"


def _setup_c(df: pd.DataFrame) -> tuple[bool, str]:
    """Cup & Handle (simplified): U-shape recovery + shallow handle < 15%."""
    close  = df["Close"]
    volume = df["Volume"]

    if len(close) < 60:
        return False, "Insufficient data for cup pattern"

    cup = close.iloc[-60:]
    left_high   = float(cup.iloc[:15].max())
    cup_low     = float(cup.iloc[10:45].min())
    right_high  = float(cup.iloc[45:55].max())

    if left_high <= 0:
        return False, "No cup pattern"

    depth_pct   = (left_high - cup_low) / left_high * 100
    recovery    = right_high / left_high * 100

    if not (10 <= depth_pct <= 40 and recovery >= 80):
        return False, "No cup-and-handle shape"

    handle_data = close.iloc[-15:]
    h_high      = float(handle_data.max())
    h_low       = float(handle_data.min())
    if h_high <= 0:
        return False, "No handle"
    h_depth     = (h_high - h_low) / h_high * 100

    if h_depth > 15:
        return False, f"Handle too deep ({h_depth:.0f}%)"

    vol_handle  = float(volume.iloc[-10:].mean())
    vol_cup_avg = float(volume.iloc[-40:-10].mean())
    vol_dry     = vol_handle <= vol_cup_avg

    current = float(close.iloc[-1])
    if current >= h_high * 0.97:
        dry_note = " with volume dry-up" if vol_dry else ""
        return True, (f"Cup ({depth_pct:.0f}% depth, {recovery:.0f}% recovered) + "
                      f"Handle ({h_depth:.0f}% depth){dry_note} — near breakout")

    return False, "Cup & Handle incomplete"


def _detect_setup(df: pd.DataFrame) -> tuple[str | None, str]:
    for sid, fn in [("A", _setup_a), ("B", _setup_b), ("C", _setup_c)]:
        ok, desc = fn(df)
        if ok:
            return sid, desc
    return None, "No valid setup (A, B, or C) detected"


# ── Trade plan & position sizing ───────────────────────────────────────────────

def _trade_plan(df: pd.DataFrame, setup_id: str | None) -> dict:
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    ema21  = calculate_ema(close, 21)
    ema50  = calculate_ema(close, 50)

    current   = round(float(close.iloc[-1]), 2)
    ema21_val = round(float(ema21.iloc[-1]), 2)
    ema50_val = round(float(ema50.iloc[-1]), 2)
    atr       = round(_atr14(df), 2)

    if setup_id == "A":
        entry  = round(current * 1.002, 2)
        sl     = round(ema21_val * 0.978, 2)
        t1     = round(float(high.iloc[-20:].max()), 2)
        t2     = round(entry + (t1 - entry) * 1.5, 2)
    elif setup_id == "B":
        rng_h  = round(float(high.iloc[-21:-1].max()), 2)
        rng_l  = round(float(low.iloc[-21:-1].min()), 2)
        rng_sz = rng_h - rng_l
        entry  = round(rng_h * 1.005, 2)
        sl     = round(rng_l * 0.995, 2)
        t1     = round(entry + rng_sz, 2)
        t2     = round(entry + rng_sz * 2, 2)
    elif setup_id == "C":
        h_high  = round(float(high.iloc[-15:].max()), 2)
        cup_dep = float(close.iloc[-60]) - float(low.iloc[-60:].min())
        entry   = round(h_high * 1.005, 2)
        sl      = round(float(low.iloc[-15:].min()) * 0.995, 2)
        t1      = round(entry + cup_dep * 0.7, 2)
        t2      = round(entry + cup_dep, 2)
    else:
        entry = current
        sl    = round(current - atr * 2, 2)
        t1    = round(current + atr * 2, 2)
        t2    = round(current + atr * 3, 2)

    sl_dist = max(entry - sl, 0.01)
    rr      = round((t1 - entry) / sl_dist, 2)

    return {
        "entry":   entry,
        "sl":      sl,
        "t1":      t1,
        "t2":      t2,
        "rr":      rr,
        "sl_pct":  round(sl_dist / entry * 100, 2),
        "t1_pct":  round((t1 - entry) / entry * 100, 2),
        "t2_pct":  round((t2 - entry) / entry * 100, 2),
        "atr":     atr,
    }


def _position_size(entry: float, sl: float, capital: float, risk_pct: float) -> dict:
    max_risk  = round(capital * risk_pct / 100, 2)
    sl_dist   = round(entry - sl, 2)
    if sl_dist <= 0:
        return {"qty": 0, "investment": 0, "max_risk": max_risk, "sl_distance": 0}

    qty       = max(1, int(max_risk / sl_dist))
    investment = round(qty * entry, 2)

    # Cap at 1/3 of capital
    max_per   = capital / 3
    if investment > max_per:
        qty        = max(1, int(max_per / entry))
        investment = round(qty * entry, 2)

    return {
        "qty":         qty,
        "investment":  investment,
        "max_risk":    max_risk,
        "sl_distance": sl_dist,
    }


# ── VIX zone ───────────────────────────────────────────────────────────────────

def _vix_zone(vix: float) -> tuple[str, str]:
    if vix < 13:   return "LOW", "green"
    if vix < 16:   return "NORMAL", "green"
    if vix < 20:   return "CAUTION", "yellow"
    if vix < 25:   return "HIGH", "orange"
    return "EXTREME", "red"


# ── Single-stock full analysis ─────────────────────────────────────────────────

def analyse_stock(symbol: str, capital: float = 75000, risk_pct: float = 2) -> dict:
    """Full S4 5-pillar analysis for one NSE stock."""
    try:
        nifty_close, nifty_ema50_w, nifty_1m_chg = _fetch_nifty_data()
        vix   = _fetch_vix() or 15.0
        df, mcap_cr = _fetch_stock_daily(symbol)

        close  = df["Close"]
        volume = df["Volume"]
        info   = STOCK_INFO.get(symbol, {"name": symbol, "sector": "Unknown"})
        sector = info["sector"]

        # Indicators
        ema21_s   = calculate_ema(close, 21)
        ema50_s   = calculate_ema(close, 50)
        rsi_s     = calculate_rsi(close, 14)
        _macd_out = calculate_macd(close)
        macd_v    = float(_macd_out["macd_line"].iloc[-1])
        sig_v     = float(_macd_out["signal_line"].iloc[-1])

        ltp       = round(float(close.iloc[-1]), 2)
        ema21_val = round(float(ema21_s.iloc[-1]), 2)
        ema50_val = round(float(ema50_s.iloc[-1]), 2)
        rsi_val   = round(float(rsi_s.iloc[-1]), 1)
        atr_val   = round(_atr14(df), 2)

        high_52w  = round(float(df["High"].max()), 2)
        low_52w   = round(float(df["Low"].min()), 2)

        vol_today   = int(volume.iloc[-1])
        vol_avg_20d = max(1, int(volume.iloc[-21:].mean()))
        vol_ratio   = round(vol_today / vol_avg_20d * 100, 0)

        ref_idx      = -22 if len(close) >= 22 else 0
        stock_1m_chg = round((ltp - float(close.iloc[ref_idx])) /
                              float(close.iloc[ref_idx]) * 100, 2)

        pct_above_52w_low  = round((ltp - low_52w) / low_52w * 100, 1)
        pct_below_52w_high = round((high_52w - ltp) / high_52w * 100, 1)

        sector_1m_chg    = _fetch_sector_1m(sector)
        sector_vs_nifty  = "Outperforming" if sector_1m_chg > nifty_1m_chg else "Underperforming"

        # ── Pillar 1: Market Direction ─────────────────────────────────────────
        vix_zone_name, vix_color = _vix_zone(vix)
        nifty_vs_ema50 = "ABOVE" if nifty_close > nifty_ema50_w else "BELOW"

        if vix >= 25:
            p1_verdict, p1_reason = "FAIL", f"VIX {vix:.1f} ≥ 25 — All cash, no trades"
        elif vix >= 20:
            p1_verdict, p1_reason = "FAIL", f"VIX {vix:.1f} ≥ 20 — No new swing trades"
        elif nifty_close < nifty_ema50_w:
            p1_verdict, p1_reason = "FAIL", (
                f"Nifty ({nifty_close:.0f}) below weekly EMA50 ({nifty_ema50_w:.0f}) — Downtrend")
        else:
            diff_pct = abs(nifty_close - nifty_ema50_w) / nifty_ema50_w * 100
            if diff_pct < 1:
                p1_verdict, p1_reason = "CAUTION", (
                    f"Nifty within 1% of weekly EMA50 — Sideways, trade half size only")
            else:
                p1_verdict, p1_reason = "PASS", (
                    f"Nifty {nifty_close:.0f} above weekly EMA50 {nifty_ema50_w:.0f} ✓")

        # ── Pillar 2: Sector Strength ──────────────────────────────────────────
        p2_pass    = sector_1m_chg > nifty_1m_chg
        p2_verdict = "PASS" if p2_pass else "FAIL"
        p2_reason  = (f"{sector} {sector_1m_chg:+.1f}% vs Nifty {nifty_1m_chg:+.1f}% — "
                      f"{sector_vs_nifty}")

        # ── Pillar 3: Stock Quality (7 checks) ────────────────────────────────
        q = {
            "trend": {
                "pass":  ltp > ema50_val,
                "label": "Price > Daily EMA50",
                "value": f"₹{ltp} {'>' if ltp > ema50_val else '<'} EMA50 ₹{ema50_val}",
            },
            "rsi": {
                "pass":  50 <= rsi_val <= 70,
                "label": "RSI 14 in 50–70",
                "value": (f"RSI {rsi_val} — "
                          f"{'sweet spot ✓' if 50 <= rsi_val <= 70 else ('< 50 weak momentum' if rsi_val < 50 else '> 70 overbought')}"),
            },
            "volume": {
                "pass":  vol_today >= vol_avg_20d * 0.8,
                "label": "Volume ≥ 20-day avg",
                "value": f"{vol_today:,} vs avg {vol_avg_20d:,} ({vol_ratio:.0f}%)",
            },
            "rel_str": {
                "pass":  stock_1m_chg > nifty_1m_chg,
                "label": "Beating Nifty (1-month)",
                "value": f"Stock {stock_1m_chg:+.1f}% vs Nifty {nifty_1m_chg:+.1f}%",
            },
            "mcap": {
                "pass":  mcap_cr >= 5000,
                "label": "Market Cap ≥ ₹5,000 Cr",
                "value": f"₹{mcap_cr:,.0f} Cr",
            },
            "liquidity": {
                "pass":  vol_avg_20d >= 500_000,
                "label": "Avg volume ≥ 5 lakh/day",
                "value": f"{vol_avg_20d:,} shares/day",
            },
            "w52pos": {
                "pass":  pct_above_52w_low >= 15,
                "label": "15%+ above 52W low",
                "value": f"{pct_above_52w_low:.1f}% above 52W low (₹{low_52w})",
            },
        }
        all_7_pass = all(v["pass"] for v in q.values())
        p3_verdict = "PASS" if all_7_pass else "FAIL"

        # ── Pillar 4: Entry Setup ──────────────────────────────────────────────
        setup_id, setup_desc = _detect_setup(df)
        p4_pass    = setup_id is not None
        p4_verdict = "PASS" if p4_pass else "FAIL"

        plan = _trade_plan(df, setup_id)

        # ── Pillar 5: Risk/Reward ──────────────────────────────────────────────
        rr         = plan["rr"]
        p5_pass    = rr >= 1.5
        p5_verdict = "PASS" if p5_pass else "FAIL"
        p5_reason  = f"R:R = 1:{rr:.1f} {'✓' if p5_pass else '— minimum 1:1.5 required'}"

        # ── Overall verdict ────────────────────────────────────────────────────
        half_size = p1_verdict == "CAUTION"

        if p1_verdict == "FAIL":
            verdict, confidence, reason = "NO_TRADE", "LOW", p1_reason
        elif not p2_pass:
            verdict, confidence, reason = "NO_TRADE", "LOW", f"Sector weak — {p2_reason}"
        elif not all_7_pass:
            failed = [k for k, v in q.items() if not v["pass"]]
            verdict, confidence = "NO_TRADE", "LOW"
            reason = "Quality check failed: " + ", ".join(failed)
        elif not p4_pass:
            verdict, confidence, reason = "NO_TRADE", "LOW", "No valid entry setup (A, B, or C)"
        elif not p5_pass:
            verdict, confidence, reason = "NO_TRADE", "LOW", p5_reason
        else:
            borderline = sum([
                not (55 <= rsi_val <= 65),
                vol_today < vol_avg_20d * 1.2,
                sector_1m_chg - nifty_1m_chg < 1.0,
            ])
            if half_size:
                verdict, confidence = "TRADE_HALF", "MEDIUM"
                reason = "Sideways market — enter at 50% position size"
            elif borderline >= 2:
                verdict, confidence = "TRADE_HALF", "MEDIUM"
                reason = "Setup valid but borderline signals — reduced size recommended"
            else:
                verdict, confidence = "TRADE", "HIGH"
                reason = f"Setup {setup_id} confirmed — all 5 pillars pass"

        # Position sizing
        pos = _position_size(plan["entry"], plan["sl"], capital, risk_pct)
        if half_size:
            pos["qty"]        = max(1, pos["qty"] // 2)
            pos["investment"] = round(pos["qty"] * plan["entry"], 2)

        today     = _dt.datetime.now(IST).date()
        exit_date = today + _dt.timedelta(days=20)
        rev_date  = today + _dt.timedelta(days=10)

        return {
            "symbol":   symbol,
            "name":     info["name"],
            "sector":   sector,
            "date":     str(today),

            "market": {
                "nifty_close":    round(nifty_close, 2),
                "nifty_ema50_w":  round(nifty_ema50_w, 2),
                "nifty_vs_ema50": nifty_vs_ema50,
                "nifty_1m_chg":   nifty_1m_chg,
                "vix":            round(vix, 2),
                "vix_zone":       vix_zone_name,
                "vix_color":      vix_color,
            },

            "indicators": {
                "ltp":             ltp,
                "ema21":           ema21_val,
                "ema50":           ema50_val,
                "rsi":             rsi_val,
                "macd_line":       round(macd_v, 2),
                "macd_signal":     round(sig_v, 2),
                "atr":             atr_val,
                "high_52w":        high_52w,
                "low_52w":         low_52w,
                "vol_today":       vol_today,
                "vol_avg_20d":     vol_avg_20d,
                "vol_ratio_pct":   vol_ratio,
                "stock_1m_chg":    stock_1m_chg,
                "sector_1m_chg":   sector_1m_chg,
                "mcap_cr":         round(mcap_cr, 0),
                "pct_above_52w_low":  pct_above_52w_low,
                "pct_below_52w_high": pct_below_52w_high,
            },

            "pillars": {
                "p1": {"verdict": p1_verdict, "reason": p1_reason},
                "p2": {"verdict": p2_verdict, "reason": p2_reason},
                "p3": {"verdict": p3_verdict, "checks": q},
                "p4": {"verdict": p4_verdict, "setup": setup_id, "description": setup_desc},
                "p5": {"verdict": p5_verdict, "reason": p5_reason},
            },

            "trade_plan": plan,
            "position":   pos,

            "verdict":    verdict,
            "confidence": confidence,
            "reason":     reason,

            "exit_rules": {
                "hard_exit_date": str(exit_date),
                "review_date":    str(rev_date),
            },
        }

    except Exception as e:
        log.error(f"swing analyse error for {symbol}: {e}", exc_info=True)
        return {"error": str(e), "symbol": symbol}


# ── Batch scan ─────────────────────────────────────────────────────────────────

def scan_stocks(symbols: list[str], capital: float = 75000, risk_pct: float = 2) -> dict:
    """Quick-filter 100 stocks via S4 and rank the best opportunities."""
    import yfinance as yf

    try:
        nifty_close, nifty_ema50_w, nifty_1m_chg = _fetch_nifty_data()
        vix = _fetch_vix() or 15.0
    except Exception as e:
        return {"error": f"Market data unavailable: {e}"}

    vix_zone_name, vix_color = _vix_zone(vix)
    market_status = ("GO" if nifty_close > nifty_ema50_w and vix < 16
                     else "CAUTION" if vix < 20
                     else "STOP")

    if vix >= 25:
        return {
            "market_status": "STOP",
            "reason": f"VIX {vix:.1f} ≥ 25 — All cash, no trading",
            "vix": vix, "recommendations": [], "rejected": [],
        }

    # Build yfinance-compatible symbols (special chars handled by yfinance)
    yf_syms = [s + ".NS" for s in symbols]

    log.info(f"[SwingScan] batch-downloading {len(yf_syms)} symbols…")
    try:
        raw = yf.download(yf_syms, period="1y", interval="1d",
                          auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        return {"error": f"Batch download failed: {e}"}

    # Helper to extract a per-stock Series from MultiIndex download
    def _col(field: str, sym: str) -> pd.Series:
        try:
            s = raw[field][sym] if (field, sym) in raw.columns or isinstance(raw.columns, pd.MultiIndex) else raw[field]
            return s.dropna()
        except Exception:
            return pd.Series(dtype=float)

    results: list[dict] = []

    for sym in symbols:
        yf_sym = sym + ".NS"
        try:
            close  = _col("Close",  yf_sym)
            volume = _col("Volume", yf_sym)
            high   = _col("High",   yf_sym)
            low    = _col("Low",    yf_sym)

            if len(close) < 50:
                results.append({"symbol": sym, "name": STOCK_INFO.get(sym, {}).get("name", sym),
                                 "rejected": True, "reason": "Insufficient data"})
                continue

            ltp       = float(close.iloc[-1])
            ema50_val = float(calculate_ema(close, 50).iloc[-1])
            rsi_val   = float(calculate_rsi(close, 14).iloc[-1])
            vol_avg20 = max(1, int(volume.iloc[-21:].mean()))
            vol_today = int(volume.iloc[-1])

            ref_idx      = -22 if len(close) >= 22 else 0
            stock_1m_chg = (ltp - float(close.iloc[ref_idx])) / float(close.iloc[ref_idx]) * 100
            low_52w      = float(low.min())
            pct_above_low = (ltp - low_52w) / low_52w * 100 if low_52w > 0 else 100

            info      = STOCK_INFO.get(sym, {"name": sym, "sector": "Unknown"})
            sector    = info["sector"]
            sector_1m = _fetch_sector_1m(sector)

            # Quick-filter checks
            rejects: list[str] = []
            if vix >= 20:
                rejects.append(f"VIX {vix:.1f} ≥ 20 — avoid new swing positions")
            if ltp <= ema50_val:
                rejects.append(f"Price ₹{ltp:.0f} below EMA50 ₹{ema50_val:.0f}")
            if rsi_val < 50:
                rejects.append(f"RSI {rsi_val:.0f} < 50 (weak momentum)")
            elif rsi_val > 70:
                rejects.append(f"RSI {rsi_val:.0f} > 70 (overbought)")
            if stock_1m_chg < nifty_1m_chg - 0.5:
                rejects.append(f"Stock {stock_1m_chg:+.1f}% underperforms Nifty {nifty_1m_chg:+.1f}%")
            if sector_1m < nifty_1m_chg - 0.5:
                rejects.append(f"Sector {sector} weak ({sector_1m:+.1f}%)")
            if vol_avg20 < 500_000:
                rejects.append(f"Low liquidity ({vol_avg20:,}/day)")
            if pct_above_low < 15:
                rejects.append(f"Only {pct_above_low:.0f}% above 52W low")

            if rejects:
                results.append({"symbol": sym, "name": info["name"],
                                 "rejected": True, "reason": rejects[0],
                                 "ltp": round(ltp, 2), "rsi": round(rsi_val, 1)})
                continue

            # Setup detection
            df_min   = pd.DataFrame({"Close": close, "High": high, "Low": low, "Volume": volume})
            setup_id, setup_desc = _detect_setup(df_min)

            if not setup_id:
                results.append({"symbol": sym, "name": info["name"],
                                 "rejected": True, "reason": "No valid setup (A/B/C)",
                                 "ltp": round(ltp, 2), "rsi": round(rsi_val, 1)})
                continue

            plan = _trade_plan(df_min, setup_id)
            if plan["rr"] < 1.5:
                results.append({"symbol": sym, "name": info["name"],
                                 "rejected": True, "reason": f"Poor R:R (1:{plan['rr']:.1f})",
                                 "ltp": round(ltp, 2), "rsi": round(rsi_val, 1)})
                continue

            # Ranking score
            rank = 0
            if 55 <= rsi_val <= 62:          rank += 3
            elif 50 <= rsi_val <= 70:        rank += 1
            if vol_today >= vol_avg20 * 1.5: rank += 2
            if setup_id == "A":              rank += 2
            if sector_1m - nifty_1m_chg > 3: rank += 2
            if plan["rr"] >= 2.0:            rank += 2

            pos = _position_size(plan["entry"], plan["sl"], capital, risk_pct)

            # In CAUTION market (Nifty below EMA50) halve position size
            caution_market = nifty_close <= nifty_ema50_w
            if caution_market:
                pos["qty"]        = max(1, pos["qty"] // 2)
                pos["investment"] = round(pos["qty"] * plan["entry"], 2)
                rank = max(0, rank - 2)

            results.append({
                "symbol":     sym,
                "name":       info["name"],
                "sector":     sector,
                "rejected":   False,
                "rank_score": rank,
                "caution_market": caution_market,
                "ltp":        round(ltp, 2),
                "rsi":        round(rsi_val, 1),
                "ema50":      round(ema50_val, 2),
                "setup":      setup_id,
                "setup_desc": setup_desc,
                "trade_plan": plan,
                "position":   pos,
                "stock_1m":   round(stock_1m_chg, 2),
                "sector_1m":  round(sector_1m, 2),
            })

        except Exception as e:
            log.warning(f"[SwingScan] {sym}: {e}")
            results.append({"symbol": sym, "name": STOCK_INFO.get(sym, {}).get("name", sym),
                             "rejected": True, "reason": f"Data error: {e}"})

    passing  = sorted([r for r in results if not r["rejected"]],
                      key=lambda x: x["rank_score"], reverse=True)
    rejected = [r for r in results if r["rejected"]]

    today = _dt.datetime.now(IST).date()
    return {
        "scan_date":      str(today),
        "total_scanned":  len(results),
        "passing_count":  len(passing),
        "market": {
            "nifty_close":    round(nifty_close, 2),
            "nifty_ema50_w":  round(nifty_ema50_w, 2),
            "nifty_vs_ema50": "ABOVE" if nifty_close > nifty_ema50_w else "BELOW",
            "nifty_1m_chg":   nifty_1m_chg,
            "vix":            round(vix, 2),
            "vix_zone":       vix_zone_name,
            "vix_color":      vix_color,
            "market_status":  market_status,
        },
        "recommendations": passing[:3],
        "watchlist":       passing[3:6],
        "rejected":        rejected,
    }


# ── Live prices for portfolio review ──────────────────────────────────────────

def fetch_swing_prices(symbols: list[str]) -> dict:
    """Get current LTPs for a list of NSE symbols (for portfolio review tab)."""
    import yfinance as yf
    import requests

    yf_syms = ",".join(s + ".NS" for s in symbols)
    prices: dict[str, float] = {}

    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v7/finance/quote",
            params={"symbols": yf_syms,
                    "fields": "regularMarketPrice"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        for item in r.json().get("quoteResponse", {}).get("result", []):
            sym = item.get("symbol", "").replace(".NS", "")
            ltp = item.get("regularMarketPrice")
            if sym and ltp is not None:
                prices[sym] = round(float(ltp), 2)
    except Exception as e:
        log.warning(f"swing prices fetch failed: {e}")

    return {"prices": prices}
