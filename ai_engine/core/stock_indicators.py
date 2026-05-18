"""
Stock Entry Indicators — EMA 9/21 (5-min), EMA 50/200 (daily), VWAP, Supertrend.
Uses yfinance for candle data. 3-minute in-memory cache per symbol.
"""

import time
import logging
import pandas as pd
from typing import Optional

from core.indicators.supertrend import compute as _supertrend_compute

log = logging.getLogger(__name__)

_cache: dict = {}
_CACHE_TTL   = 180  # 3 minutes


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _vwap_series(df: pd.DataFrame) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    return (tp * df["Volume"]).cumsum() / df["Volume"].replace(0, pd.NA).cumsum()


def fetch_indicators(symbol: str) -> dict:
    """
    Returns EMA 9/21 (5-min intraday), EMA 50/200 (daily),
    session VWAP (5-min), Supertrend (5-min, period=7 mult=3),
    plus a 0–7 entry signal score and bias label.
    """
    now    = time.time()
    cached = _cache.get(symbol)
    if cached and now - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol + ".NS")
        intra  = ticker.history(period="1d",   interval="5m",  auto_adjust=True)
        daily  = ticker.history(period="250d",  interval="1d",  auto_adjust=True)
    except Exception as e:
        return {"error": f"Data fetch failed: {e}"}

    if intra.empty or len(intra) < 10:
        return {"error": "Not enough intraday data (market may be closed)"}
    if daily.empty or len(daily) < 50:
        return {"error": "Not enough daily data"}

    # ── Intraday (5-min) ──────────────────────────────────────────────────────
    ltp   = round(float(intra["Close"].iloc[-1]), 2)
    ema9  = round(float(_ema(intra["Close"],  9).iloc[-1]), 2)
    ema21 = round(float(_ema(intra["Close"], 21).iloc[-1]), 2)

    vwap_s = _vwap_series(intra)
    vwap   = round(float(vwap_s.iloc[-1]), 2) if not vwap_s.isna().all() else None

    st_rows = _supertrend_compute(intra, period=7, multiplier=3.0)
    st_last = st_rows[-1]
    st_val  = round(float(st_last["value"]), 2) if st_last["value"] is not None else None
    st_dir  = st_last["direction"]   # "up" / "down" / "neutral"

    # ── Daily ─────────────────────────────────────────────────────────────────
    ema50  = round(float(_ema(daily["Close"],  50).iloc[-1]), 2)
    ema200 = round(float(_ema(daily["Close"], 200).iloc[-1]), 2)

    # ── Pct distance helper ───────────────────────────────────────────────────
    def _dist(val):
        if val is None or val == 0:
            return None
        return round((ltp - val) / val * 100, 2)

    # ── Signal scoring (0–7) ─────────────────────────────────────────────────
    checks = {
        "above_vwap":       (ltp > vwap)    if vwap  else False,
        "above_ema9":        ltp > ema9,
        "above_ema21":       ltp > ema21,
        "ema9_above_ema21":  ema9 > ema21,
        "above_ema50":       ltp > ema50,
        "above_ema200":      ltp > ema200,
        "supertrend_up":     st_dir == "up",
    }
    score = sum(checks.values())

    if   score >= 6: bias, bias_color = "STRONG BULLISH", "green"
    elif score >= 5: bias, bias_color = "BULLISH",         "green"
    elif score >= 4: bias, bias_color = "MILDLY BULLISH",  "cyan"
    elif score == 3: bias, bias_color = "NEUTRAL",         "yellow"
    elif score >= 2: bias, bias_color = "MILDLY BEARISH",  "orange"
    elif score >= 1: bias, bias_color = "BEARISH",         "red"
    else:            bias, bias_color = "STRONG BEARISH",  "red"

    result = {
        "symbol":  symbol,
        "ltp":     ltp,
        "indicators": {
            "vwap":   {"value": vwap,  "dist_pct": _dist(vwap),  "timeframe": "Today"},
            "ema9":   {"value": ema9,  "dist_pct": _dist(ema9),  "timeframe": "5-min"},
            "ema21":  {"value": ema21, "dist_pct": _dist(ema21), "timeframe": "5-min"},
            "ema50":  {"value": ema50, "dist_pct": _dist(ema50), "timeframe": "Daily"},
            "ema200": {"value": ema200,"dist_pct": _dist(ema200),"timeframe": "Daily"},
            "supertrend": {
                "value":     st_val,
                "dist_pct":  _dist(st_val),
                "direction": st_dir,
                "timeframe": "5-min",
            },
        },
        "checks":    checks,
        "score":     score,
        "max_score": 7,
        "bias":      bias,
        "bias_color": bias_color,
        "candles_5m": len(intra),
    }
    _cache[symbol] = {"ts": now, "data": result}
    return result
