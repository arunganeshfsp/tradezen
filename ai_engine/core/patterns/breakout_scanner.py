"""
Consolidation-Breakout Pattern Scanner — OHLCV only.
Framework: 52W High → Decline ≥ N% → Sideways Base → Breakout Watch.
All five accumulation signals are derived purely from price/volume data.
"""
import numpy as np
import pandas as pd
import logging
from typing import Optional, List, Tuple, Dict

log = logging.getLogger(__name__)

# ── Universe lists ────────────────────────────────────────────────────────────
NIFTY50 = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","SBIN","HINDUNILVR",
    "BHARTIARTL","ITC","KOTAKBANK","LT","AXISBANK","BAJFINANCE","WIPRO",
    "MARUTI","NTPC","POWERGRID","SUNPHARMA","HCLTECH","ONGC","TATAMOTORS",
    "TATASTEEL","ADANIENT","ADANIPORTS","ULTRACEMCO","BAJAJFINSV","TITAN",
    "NESTLEIND","TECHM","M&M","DRREDDY","ASIANPAINT","COALINDIA","HDFCLIFE",
    "BRITANNIA","DIVISLAB","CIPLA","GRASIM","INDUSINDBK","SBILIFE",
    "HINDALCO","JSWSTEEL","APOLLOHOSP","BAJAJ-AUTO","BPCL","HEROMOTOCO",
    "TATACONSUM","EICHERMOT","LTIM","VEDL",
]

NIFTY_NEXT50 = [
    "ADANIGREEN","ADANIPOWER","AMBUJACEM","ATGL","BANKBARODA","BEL","BHEL",
    "CANBK","CGPOWER","CHOLAFIN","CONCOR","CUMMINSIND","DMART","GAIL",
    "GODREJCP","HAL","HAVELLS","ICICIPRULI","INDHOTEL","INDUSTOWER","IOC",
    "IRCTC","IRFC","JIOFIN","JSWENERGY","LODHA","LTF","LUPIN","MARICO",
    "MOTHERSON","NAUKRI","NHPC","NMDC","OBEROIRLTY","PAYTM","PFC",
    "PHOENIXLTD","PIDILITIND","PNB","RECLTD","RVNL","SHRIRAMFIN",
    "TATAPOWER","TORNTPHARM","TVSMOTOR","UNIONBANK","VBL","ZOMATO",
]

MIDCAP_EXTRA = [
    "ABCAPITAL","ASTRAL","AUBANK","AUROPHARMA","BALKRISIND","BIOCON",
    "CANFINHOME","DEEPAKNTR","DIXON","FEDERALBNK","GLENMARK","HDFCAMC",
    "IDFCFIRSTB","IRB","KPITTECH","LICHSGFIN","MANAPPURAM","MAXHEALTH",
    "MCX","MPHASIS","MUTHOOTFIN","OFSS","PERSISTENT","POLYCAB","SRF",
    "SUNDARMFIN","SUPREMEIND","TATACOMM","TORNTPOWER","UBL","VOLTAS",
    "ASHOKLEY","APOLLOTYRE","CEATLTD","MRF","TIINDIA","RAMCOCEM","ACC",
    "SHREECEM","DLF","GODREJPROP","PRESTIGE","BRIGADE","HAVELLS","KEI",
    "ABB","SIEMENS","TATACHEM","NAVINFLUOR","ATUL","MANAPPURAM",
]

SECTOR_MAP: Dict[str, List[str]] = {
    "banks":     ["HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK",
                  "BANKBARODA","FEDERALBNK","IDFCFIRSTB","BANDHANBNK","AUBANK","PNB","CANBK"],
    "it":        ["TCS","INFY","WIPRO","HCLTECH","TECHM","LTIM","MPHASIS","OFSS",
                  "PERSISTENT","KPITTECH","COFORGE","TATAELXSI"],
    "pharma":    ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","AUROPHARMA",
                  "BIOCON","TORNTPHARM","ALKEM","ZYDUSLIFE","GLENMARK"],
    "metals":    ["TATASTEEL","JSWSTEEL","HINDALCO","NMDC","COALINDIA","SAIL",
                  "NATIONALUM","HINDZINC","VEDL","MOIL"],
    "auto":      ["MARUTI","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT",
                  "TVSMOTOR","MOTHERSON","BALKRISIND","BOSCHLTD","ASHOKLEY"],
    "fmcg":      ["HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","MARICO",
                  "COLPAL","EMAMILTD","TATACONSUM","UBL"],
    "energy":    ["RELIANCE","ONGC","BPCL","IOC","NTPC","POWERGRID","TATAPOWER",
                  "ADANIGREEN","ADANIPOWER","TORNTPOWER","NHPC","SJVN","GAIL"],
    "realty":    ["DLF","GODREJPROP","OBEROIRLTY","PRESTIGE","BRIGADE","PHOENIXLTD"],
    "infra":     ["LT","BHEL","HAL","BEL","IRB","RVNL","CONCOR","GMRINFRA"],
    "chemicals": ["DEEPAKNTR","SRF","ATUL","TATACHEM","NAVINFLUOR","PIDILITIND"],
}


def _get_breakout_symbols(universe: str, sector: str, symbols: str) -> List[str]:
    if symbols:
        return [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if sector and sector in SECTOR_MAP:
        return SECTOR_MAP[sector]
    if universe == "nifty50":
        return list(NIFTY50)
    if universe == "nifty100":
        return list(dict.fromkeys(NIFTY50 + NIFTY_NEXT50))
    if universe == "midcap100":
        return list(dict.fromkeys(NIFTY_NEXT50 + MIDCAP_EXTRA))
    if universe == "nifty500":
        return list(dict.fromkeys(NIFTY50 + NIFTY_NEXT50 + MIDCAP_EXTRA))
    return list(NIFTY50)


# ── Technical helpers ─────────────────────────────────────────────────────────

def _rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    d = np.diff(prices[-(period + 1):])
    up = d[d > 0].mean() if d[d > 0].size else 0.0
    dn = -d[d < 0].mean() if d[d < 0].size else 1e-9
    return round(100 - 100 / (1 + up / dn), 1)


def _macd_above_signal(prices: np.ndarray) -> bool:
    if len(prices) < 35:
        return False
    s = pd.Series(prices, dtype=float)
    macd = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    sig  = macd.ewm(span=9, adjust=False).mean()
    return bool(macd.iloc[-1] > sig.iloc[-1])


def _higher_lows(prices: np.ndarray, order: int = 2) -> bool:
    """Return True if at least one consecutive higher trough pair found."""
    troughs = []
    for i in range(order, len(prices) - order):
        window = prices[max(0, i - order): i + order + 1]
        if prices[i] == window.min():
            troughs.append(prices[i])
    if len(troughs) < 2:
        return False
    return any(troughs[i] > troughs[i - 1] for i in range(1, len(troughs)))


def _vol_trend(vols: np.ndarray) -> str:
    if len(vols) < 6:
        return "mixed"
    mid = len(vols) // 2
    f = vols[:mid].mean()
    s = vols[mid:].mean()
    if f == 0:
        return "mixed"
    r = s / f
    if r < 0.85:
        return "declining"
    if r > 1.15:
        return "rising"
    return "mixed"


def _has_distribution(closes: np.ndarray, vols: np.ndarray) -> bool:
    """True if any high-volume red day is found (≥1.5× avg vol, price down)."""
    if len(vols) < 3:
        return False
    avg = vols.mean()
    for i in range(1, len(closes)):
        if closes[i] < closes[i - 1] and vols[i] > 1.5 * avg:
            return True
    return False


def _find_base(
    prices: np.ndarray, min_w: int, max_w: int, max_range: float
) -> Optional[Tuple[int, int, float, float]]:
    """
    Scan backward from the most recent bar. Return the widest valid base window
    (in weeks) whose high-low range is ≤ max_range %.
    Returns (start_idx, end_idx, base_low, base_high) or None.
    """
    n = len(prices)
    for w in range(max_w, min_w - 1, -1):
        bars = w * 5
        si = n - bars
        if si < 0:
            continue
        sub = prices[si:]
        hi = float(sub.max())
        lo = float(sub.min())
        if lo == 0:
            continue
        if (hi - lo) / lo * 100 <= max_range:
            return si, n - 1, lo, hi
    return None


# ── Per-stock analysis ────────────────────────────────────────────────────────

def _analyse_one(
    sym:         str,
    close:       pd.Series,
    volume:      pd.Series,
    nifty:       Optional[pd.Series],
    min_decline: float,
    min_w:       int,
    max_w:       int,
    max_range:   float,
    near_res:    float,
) -> Optional[Dict]:

    prices = close.values.astype(float)
    vols   = volume.reindex(close.index).fillna(0).values.astype(float)
    n      = len(prices)
    cur    = prices[-1]

    if n < max_w * 5 + 30:
        return None

    # ── Step 1: Prior high & decline ────────────────────────────────────────
    prior_high_idx  = int(prices.argmax())
    prior_high      = prices[prior_high_idx]
    prior_high_date = close.index[prior_high_idx].strftime("%Y-%m-%d")

    # Stock must not currently be AT its 52W high (no setup)
    if prior_high_idx >= n - 3:
        return None

    post_peak_low  = float(prices[prior_high_idx:].min())
    decline_pct    = (prior_high - post_peak_low) / prior_high * 100
    if decline_pct < min_decline:
        return None

    # ── Step 2: Base detection ───────────────────────────────────────────────
    base = _find_base(prices, min_w, max_w, max_range)
    if base is None:
        return None
    si, ei, base_lo, base_hi = base

    # Base must sit below the prior high with meaningful distance (≥5%)
    if base_hi >= prior_high * 0.97:
        return None

    base_weeks     = max(1, round((ei - si + 1) / 5))
    base_range_pct = round((base_hi - base_lo) / base_lo * 100, 1)

    bp = prices[si:]
    bv = vols[si:]
    vol_trend  = _vol_trend(bv)
    hl         = _higher_lows(bp, order=max(2, len(bp) // 8))
    has_dist   = _has_distribution(bp, bv)

    # ── Step 3: Accumulation score (OHLCV only) ─────────────────────────────
    score   = 0
    signals = []

    if hl:
        score += 1
        signals.append("Higher lows forming in base")

    if vol_trend == "declining":
        score += 1
        signals.append("Volume declining in base (seller exhaustion)")

    rsi = _rsi(prices)
    if 38 <= rsi <= 68:
        score += 1
        signals.append(f"RSI {rsi:.0f} — constructive (not overbought)")

    if _macd_above_signal(prices):
        score += 1
        signals.append("MACD above signal line (momentum building)")

    # Relative strength vs Nifty during base period
    if nifty is not None:
        try:
            common = close.index.intersection(nifty.index)
            if len(common) >= 5:
                base_start_date = close.index[si]
                base_common = common[common >= base_start_date]
                if len(base_common) >= 5:
                    stock_ret = (close.loc[base_common[-1]] - close.loc[base_common[0]]) / close.loc[base_common[0]] * 100
                    nifty_ret = (nifty.loc[base_common[-1]] - nifty.loc[base_common[0]]) / nifty.loc[base_common[0]] * 100
                    if stock_ret > nifty_ret:
                        score += 1
                        signals.append(f"Outperforming Nifty in base ({stock_ret:+.1f}% vs {nifty_ret:+.1f}%)")
        except Exception:
            pass

    # ── Step 4: Breakout readiness ───────────────────────────────────────────
    resistance   = base_hi
    dist_pct     = round((resistance - cur) / resistance * 100, 1)
    breakout_now = cur > resistance
    avg20_vol    = vols[-20:].mean() if n >= 20 else vols.mean()
    vol_ok       = bool(breakout_now and vols[-1] >= 1.5 * avg20_vol)

    market_cond = "neutral"
    if nifty is not None and len(nifty) >= 200:
        nv = nifty.values.astype(float)
        sma200 = nv[-200:].mean()
        if nv[-1] > sma200 * 1.01:
            market_cond = "supportive"
        elif nv[-1] < sma200 * 0.99:
            market_cond = "adverse"

    # ── Step 5: Risk flags ───────────────────────────────────────────────────
    flags = []
    if breakout_now and not vol_ok:
        flags.append("Breakout on below-average volume — unconfirmed")
    if market_cond == "adverse":
        flags.append("Nifty below 200 DMA — adverse market conditions")
    if rsi > 75:
        flags.append(f"RSI {rsi:.0f} — overbought at current price")
    if vol_trend == "rising":
        flags.append("Volume rising in base — possible distribution")
    if has_dist:
        flags.append("High-volume red candles detected inside base")

    # ── Verdict ──────────────────────────────────────────────────────────────
    if breakout_now and vol_ok and score >= 3 and market_cond != "adverse":
        verdict = "STRONG"
    elif (dist_pct <= near_res or breakout_now) and score >= 2 and len(flags) <= 1:
        verdict = "MODERATE"
    elif dist_pct <= near_res * 2 or breakout_now:
        verdict = "WEAK"
    else:
        verdict = "BUILDING"

    # ── Chart data — last 120 bars ────────────────────────────────────────────
    cs = max(0, n - 120)
    sma20_series = close.rolling(20).mean().iloc[cs:]
    chart = {
        "dates":           [d.strftime("%Y-%m-%d") for d in close.index[cs:]],
        "closes":          [round(float(v), 2) for v in prices[cs:]],
        "sma20":           [round(float(v), 2) if pd.notna(v) else None for v in sma20_series.values],
        "prior_high":      round(float(prior_high), 2),
        "base_lo":         round(base_lo, 2),
        "base_hi":         round(base_hi, 2),
        "base_start_idx":  max(0, si - cs),
    }

    return {
        "symbol":          sym,
        "current_price":   round(float(cur), 2),
        "prior_high":      round(float(prior_high), 2),
        "prior_high_date": prior_high_date,
        "decline_pct":     round(float(decline_pct), 1),
        "base_low":        round(base_lo, 2),
        "base_high":       round(base_hi, 2),
        "base_weeks":      base_weeks,
        "base_range_pct":  base_range_pct,
        "volume_trend":    vol_trend,
        "higher_lows":     hl,
        "has_distribution": has_dist,
        "accum_score":     score,
        "accum_signals":   signals,
        "rsi":             rsi,
        "resistance":      round(base_hi, 2),
        "distance_pct":    dist_pct,
        "breakout_now":    breakout_now,
        "vol_confirmed":   vol_ok,
        "market_condition": market_cond,
        "risk_flags":      flags,
        "verdict":         verdict,
        "chart":           chart,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def scan_breakouts(
    universe:    str   = "nifty50",
    min_decline: float = 20.0,
    min_w:       int   = 4,
    max_w:       int   = 12,
    max_range:   float = 10.0,
    near_res:    float = 5.0,
    sector:      str   = "",
    symbols:     str   = "",
) -> dict:
    import yfinance as yf

    sym_list = _get_breakout_symbols(universe, sector, symbols)
    if not sym_list:
        return {"error": "No symbols to scan."}

    tickers = [s + ".NS" for s in sym_list] + ["^NSEI"]

    try:
        raw = yf.download(
            tickers,
            period="1y",
            interval="1d",
            group_by="column",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.error(f"[BREAKOUT-SCAN] download failed: {e}")
        return {"error": "Failed to fetch market data. Try again."}

    # Extract Nifty series (aligned by date)
    nifty: Optional[pd.Series] = None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            nifty = raw["Close"]["^NSEI"].dropna()
        else:
            nifty = raw["Close"].dropna()
    except Exception:
        pass

    results = []

    for sym in sym_list:
        ticker = sym + ".NS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close  = raw["Close"][ticker].dropna()
                volume = raw["Volume"][ticker].reindex(close.index).fillna(0)
            else:
                close  = raw["Close"].dropna()
                volume = raw["Volume"].reindex(close.index).fillna(0)

            if len(close) < max_w * 5 + 30:
                continue

            r = _analyse_one(sym, close, volume, nifty,
                             min_decline, min_w, max_w, max_range, near_res)
            if r:
                results.append(r)

        except Exception:
            continue

    _ORDER = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "BUILDING": 3}
    results.sort(key=lambda x: (_ORDER.get(x["verdict"], 4), -x["accum_score"], x["distance_pct"]))

    return {
        "universe":      universe,
        "universe_size": len(sym_list),
        "matched":       len(results),
        "results":       results,
    }


def check_single_breakout(
    symbol:      str,
    min_decline: float = 20.0,
    min_w:       int   = 4,
    max_w:       int   = 12,
    max_range:   float = 10.0,
    near_res:    float = 5.0,
) -> dict:
    import yfinance as yf

    raw_sym = symbol.upper().strip()
    ticker  = raw_sym if raw_sym.endswith(".NS") or raw_sym.endswith(".BO") else raw_sym + ".NS"

    tk   = yf.Ticker(ticker)
    hist = tk.history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 60:
        return {"error": f"Insufficient data for '{raw_sym}'. Verify the NSE symbol."}

    nifty: Optional[pd.Series] = None
    try:
        ni_hist = yf.Ticker("^NSEI").history(period="1y", interval="1d", auto_adjust=True)
        if not ni_hist.empty:
            nifty = ni_hist["Close"].dropna()
    except Exception:
        pass

    close  = hist["Close"].dropna()
    volume = hist["Volume"].reindex(close.index).fillna(0)
    prices = close.values.astype(float)

    r = _analyse_one(raw_sym, close, volume, nifty,
                     min_decline, min_w, max_w, max_range, near_res)

    if r is None:
        prior_high  = float(prices.max())
        phi         = int(prices.argmax())
        post_low    = float(prices[phi:].min())
        decline_pct = round((prior_high - post_low) / prior_high * 100, 1)
        return {
            "symbol":        raw_sym,
            "current_price": round(float(prices[-1]), 2),
            "prior_high":    round(prior_high, 2),
            "decline_pct":   decline_pct,
            "passed":        False,
            "verdict":       "NO_SETUP",
            "reason": (
                f"Decline of {decline_pct:.1f}% is below the {min_decline:.0f}% threshold"
                if decline_pct < min_decline
                else f"No {min_w}–{max_w} week base with range ≤ {max_range:.0f}% found near current price"
            ),
        }

    r["passed"] = r["verdict"] in ("STRONG", "MODERATE")
    return r
