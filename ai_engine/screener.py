"""
screener.py  —  Multi-Year Breakout & Multibagger Screener
Batch-downloads daily OHLCV via yfinance, scores each stock,
and returns the top-10 per requested category.
Called from main.py via asyncio.run_in_executor.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ~120-stock representative Nifty-500 universe  (NSE symbols, no ".NS" suffix)
# ─────────────────────────────────────────────────────────────────────────────
_RAW_UNIVERSE: List[str] = [
    # ── Nifty 50 core ────────────────────────────────────────────────────────
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BAJFINANCE", "LICI", "KOTAKBANK",
    "ITC", "BHARTIARTL", "LT", "AXISBANK", "ASIANPAINT",
    "MARUTI", "SUNPHARMA", "TITAN", "NESTLEIND", "WIPRO",
    "ULTRACEMCO", "TECHM", "ONGC", "POWERGRID", "NTPC",
    "TATAMOTORS", "BAJAJFINSV", "HCLTECH", "JSWSTEEL", "TATASTEEL",
    "COALINDIA", "ADANIENT", "ADANIPORTS", "HINDALCO", "BPCL",
    "DRREDDY", "DIVISLAB", "CIPLA", "APOLLOHOSP", "INDUSINDBK",
    "GRASIM", "TATACONSUM", "BRITANNIA", "EICHERMOT", "BAJAJ-AUTO",
    "HEROMOTOCO", "SHRIRAMFIN", "BEL", "HDFCLIFE", "M&M",
    # ── IT & Tech ────────────────────────────────────────────────────────────
    "LTIM", "MPHASIS", "PERSISTENT", "COFORGE", "KPITTECH",
    "TATAELXSI", "OFSS", "NAUKRI", "ZOMATO", "NYKAA",
    # ── Capital Goods / Infra / Defence ──────────────────────────────────────
    "SIEMENS", "ABB", "CUMMINS", "THERMAX", "HAL",
    "BHEL", "IRFC", "RVNL", "IRCTC", "HUDCO",
    "MAZAGON", "COCHINSHIP", "GRSE",
    # ── Power & Renewables ───────────────────────────────────────────────────
    "NHPC", "SJVN", "CESC", "TORNTPOWER", "TATAPOWER",
    "ADANIGREEN", "ADANIPOWER",
    # ── Metals & Mining ──────────────────────────────────────────────────────
    "VEDL", "HINDZINC", "NMDC", "SAIL", "NATIONALUM",
    # ── Building Materials / Chemicals ───────────────────────────────────────
    "APLAPOLLO", "ASTRAL", "SUPREMEIND", "DEEPAKNTR",
    "PIIND", "UPL", "CHAMBAL", "COROMANDEL",
    # ── Pharma & Healthcare ──────────────────────────────────────────────────
    "LUPIN", "ALKEM", "IPCALAB", "LALPATHLAB",
    # ── FMCG & Consumer ──────────────────────────────────────────────────────
    "MARICO", "GODREJCP", "EMAMI", "COLPAL", "DABUR",
    "MCDOWELL-N", "RADICO",
    # ── Retail / Fashion / Jewellery ─────────────────────────────────────────
    "TRENT", "DMART", "PAGEIND", "KALYANKJIL", "SENCO",
    # ── Auto & Ancillaries ───────────────────────────────────────────────────
    "TVSMOTORS", "ASHOKLEY", "MOTHERSON", "BOSCHLTD", "MRF",
    "EXIDEIND", "MINDA",
    # ── Financials / NBFCs / Insurance ───────────────────────────────────────
    "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM", "PNBHOUSING",
    "LICHSGFIN", "CANFINHOME", "BANDHANBNK", "FEDERALBNK",
    "IDFCFIRSTB", "AUBANK", "PNB", "BANKBARODA", "CANBK",
    "ABCAPITAL",
    # ── Real Estate ──────────────────────────────────────────────────────────
    "DLF", "GODREJPROP", "PRESTIGE", "OBEROIRLTY",
    # ── Cement ───────────────────────────────────────────────────────────────
    "SHREECEM", "AMBUJACEMENT", "ACC", "RAMCOCEM",
    # ── Paints ───────────────────────────────────────────────────────────────
    "BERGER", "KANSAINER",
    # ── QSR / Food ───────────────────────────────────────────────────────────
    "JUBILFOOD", "DEVYANI",
]

# Deduplicate while preserving order
_seen: set = set()
UNIVERSE: List[str] = []
for _s in _RAW_UNIVERSE:
    if _s not in _seen:
        _seen.add(_s)
        UNIVERSE.append(_s)

VALID_CATEGORIES = frozenset({
    "multibagger", "breakout_1y", "breakout_3y",
    "breakout_5y", "breakout_ath", "yearly", "monthly",
})

_CATEGORY_LABELS = {
    "multibagger":  "Multibagger",
    "breakout_1y":  "1Y Breakout",
    "breakout_3y":  "3Y Breakout",
    "breakout_5y":  "5Y Breakout",
    "breakout_ath": "ATH Breakout",
    "yearly":       "Yearly Breakout",
    "monthly":      "Monthly Breakout",
}

_PERIOD_MAP = {
    "multibagger": "1y",
    "breakout_1y": "1y",
    "breakout_3y": "3y",
    "breakout_5y": "max",
    "breakout_ath": "max",
    "yearly":  "1y",
    "monthly": "1y",
}


# ─────────────────────────────────────────────────────────────────────────────
# Scoring engine
# ─────────────────────────────────────────────────────────────────────────────

def _score_stock(
    sym: str,
    closes: np.ndarray,
    volumes: np.ndarray,
    category: str,
) -> Optional[Dict[str, Any]]:
    n = len(closes)
    if n < 30:
        return None

    curr  = float(closes[-1])
    today = datetime.date.today()

    # ── Lookback window ──────────────────────────────────────────────────────
    if category == "breakout_ath":
        lookback = n - 1
    elif category == "breakout_5y":
        lookback = min(252 * 5, n - 1)
    elif category == "breakout_3y":
        lookback = min(252 * 3, n - 1)
    elif category == "breakout_1y":
        lookback = min(252, n - 1)
    elif category == "yearly":
        jan1     = today.replace(month=1, day=1)
        lookback = max((today - jan1).days, 20)
    elif category == "monthly":
        month_start = today.replace(day=1)
        lookback    = max((today - month_start).days, 5)
    elif category == "multibagger":
        lookback = min(252, n - 1)
    else:
        return None

    hist = closes[-(lookback + 1):-1]
    if len(hist) == 0:
        return None

    hist_high = float(np.max(hist))
    hist_low  = float(np.min(hist))

    # ── Volume ratios (5-day avg vs 20-day avg) ──────────────────────────────
    vol_20 = float(np.mean(volumes[-25:-5])) if n >= 25 else float(np.mean(volumes[:-1]))
    vol_5  = float(np.mean(volumes[-5:]))    if n >= 5  else float(volumes[-1])
    vol_20 = max(vol_20, 1)
    vol_ratio = vol_5 / vol_20

    # ── 200-day SMA momentum ─────────────────────────────────────────────────
    sma200       = float(np.mean(closes[-200:])) if n >= 200 else float(np.mean(closes))
    momentum_pct = (curr / sma200 - 1) * 100 if sma200 > 0 else 0

    # ── MULTIBAGGER ──────────────────────────────────────────────────────────
    if category == "multibagger":
        if hist_low <= 0:
            return None
        gain_pct = (curr - hist_low) / hist_low * 100
        if gain_pct < 100:                          # ≥100% gain from 52W low
            return None

        s_gain = min(40, gain_pct / 5)             # 200% gain → 40 pts
        s_vol  = min(30, vol_ratio * 10) if vol_ratio >= 1 else 0
        s_mom  = min(30, max(0, momentum_pct))      # above 200 SMA → up to 30
        score  = round(s_gain + s_vol + s_mom, 1)

        return {
            "symbol":       sym,
            "ltp":          round(curr, 2),
            "score":        score,
            "label":        f"+{gain_pct:.0f}% from 52W low",
            "sub":          f"52W Low ₹{hist_low:,.0f}",
            "vol_ratio":    round(vol_ratio, 2),
            "above_200sma": momentum_pct > 0,
            "tag":          "MULTIBAGGER",
        }

    # ── BREAKOUT ─────────────────────────────────────────────────────────────
    if hist_high <= 0:
        return None

    bo_pct = (curr - hist_high) / hist_high * 100
    if bo_pct < 0.5:        # not broken out (< 0.5% margin → noise)
        return None
    if vol_ratio < 1.5:     # volume must confirm the breakout
        return None

    s_break = min(40, bo_pct * 8)                  # 5% breakout  → 40 pts
    s_vol   = min(35, (vol_ratio - 1.5) * 14)      # 4× volume    → 35 pts
    s_mom   = min(25, max(0, momentum_pct / 2))    # 50% > 200d   → 25 pts
    score   = round(s_break + s_vol + s_mom, 1)

    _period_label = {
        "breakout_ath": "ATH",     "breakout_5y": "5Y High",
        "breakout_3y":  "3Y High", "breakout_1y": "1Y High",
        "yearly":       "YTD High","monthly":     "MTD High",
    }.get(category, "High")

    _tag_map = {
        "breakout_ath": "ATH BREAKOUT",   "breakout_5y": "5Y BREAKOUT",
        "breakout_3y":  "3Y BREAKOUT",    "breakout_1y": "1Y BREAKOUT",
        "yearly":       "YEARLY BREAKOUT","monthly":     "MONTHLY BREAKOUT",
    }

    return {
        "symbol":       sym,
        "ltp":          round(curr, 2),
        "score":        score,
        "label":        f"+{bo_pct:.1f}% above {_period_label}",
        "sub":          f"Prev High ₹{hist_high:,.0f}",
        "vol_ratio":    round(vol_ratio, 2),
        "above_200sma": momentum_pct > 0,
        "tag":          _tag_map.get(category, "BREAKOUT"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_screener(category: str) -> Dict[str, Any]:
    """
    Run the screener for the given category.
    Blocking — call via asyncio.run_in_executor from FastAPI.
    """
    if category not in VALID_CATEGORIES:
        return {"error": f"Unknown category '{category}'", "stocks": [], "screened": 0}

    period  = _PERIOD_MAP[category]
    yf_syms = [f"{s}.NS" for s in UNIVERSE]
    as_of   = datetime.datetime.now().strftime("%d %b %Y  %H:%M IST")

    log.info("[Screener] category=%s  period=%s  universe=%d stocks", category, period, len(yf_syms))

    try:
        raw = yf.download(
            yf_syms,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
            group_by="ticker",
        )
    except Exception as exc:
        log.error("[Screener] yf.download failed: %s", exc)
        return {"error": str(exc), "stocks": [], "screened": 0}

    results: List[Dict] = []
    failed  = 0

    for sym in UNIVERSE:
        yf_sym = f"{sym}.NS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                df = raw[yf_sym].dropna(subset=["Close"])
            else:
                df = raw.dropna(subset=["Close"])

            if df.empty or len(df) < 30:
                continue

            closes  = df["Close"].to_numpy(dtype=float)
            volumes = df["Volume"].to_numpy(dtype=float)
            volumes = np.where(volumes <= 0, 1, volumes)

            hit = _score_stock(sym, closes, volumes, category)
            if hit:
                results.append(hit)

        except Exception as exc:
            failed += 1
            log.debug("[Screener] %s skipped: %s", sym, exc)

    results.sort(key=lambda x: x["score"], reverse=True)
    top10 = results[:10]

    log.info(
        "[Screener] done — qualified=%d  failed=%d  returning=%d",
        len(results), failed, len(top10),
    )
    return {
        "category":  category,
        "label":     _CATEGORY_LABELS.get(category, category),
        "stocks":    top10,
        "screened":  len(UNIVERSE),
        "qualified": len(results),
        "as_of":     as_of,
    }
