"""
Stock Entry Indicators — EMA 9/21 (5-min), EMA 50/200 (daily), VWAP, Supertrend, RSI 14.
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


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _vwap_series(df: pd.DataFrame) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    return (tp * df["Volume"]).cumsum() / df["Volume"].replace(0, pd.NA).cumsum()


def _rsi_zone(val: float) -> str:
    if val >= 70: return "overbought"
    if val >= 50: return "bullish"
    if val >= 30: return "bearish"
    return "oversold"


def fetch_indicators(symbol: str) -> dict:
    """
    Returns EMA 9/21 (5-min intraday), EMA 50/200 (daily),
    session VWAP (5-min), Supertrend (5-min, period=7 mult=3),
    RSI 14 (5-min and daily), plus a 0–9 entry signal score and bias label.
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

    if intra.empty or len(intra) < 15:
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

    rsi_5m_val = _rsi(intra["Close"], 14).iloc[-1]
    rsi_5m     = round(float(rsi_5m_val), 1) if pd.notna(rsi_5m_val) else None

    # ── Daily ─────────────────────────────────────────────────────────────────
    ema50  = round(float(_ema(daily["Close"],  50).iloc[-1]), 2)
    ema200 = round(float(_ema(daily["Close"], 200).iloc[-1]), 2)

    rsi_1d_val = _rsi(daily["Close"], 14).iloc[-1]
    rsi_1d     = round(float(rsi_1d_val), 1) if pd.notna(rsi_1d_val) else None

    # ── Pct distance helper ───────────────────────────────────────────────────
    def _dist(val):
        if val is None or val == 0:
            return None
        return round((ltp - val) / val * 100, 2)

    # ── Signal scoring (0–9) ─────────────────────────────────────────────────
    checks = {
        "above_vwap":       (ltp > vwap)    if vwap  else False,
        "above_ema9":        ltp > ema9,
        "above_ema21":       ltp > ema21,
        "ema9_above_ema21":  ema9 > ema21,
        "above_ema50":       ltp > ema50,
        "above_ema200":      ltp > ema200,
        "supertrend_up":     st_dir == "up",
        "rsi_5m_bullish":    (rsi_5m > 50)  if rsi_5m  is not None else False,
        "rsi_1d_bullish":    (rsi_1d > 50)  if rsi_1d  is not None else False,
    }
    score = sum(checks.values())

    if   score >= 8: bias, bias_color = "STRONG BULLISH", "green"
    elif score >= 7: bias, bias_color = "BULLISH",         "green"
    elif score >= 5: bias, bias_color = "MILDLY BULLISH",  "cyan"
    elif score == 4: bias, bias_color = "NEUTRAL",         "yellow"
    elif score >= 3: bias, bias_color = "MILDLY BEARISH",  "orange"
    elif score >= 2: bias, bias_color = "BEARISH",         "red"
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
            "rsi_5m": {
                "value":     rsi_5m,
                "zone":      _rsi_zone(rsi_5m) if rsi_5m is not None else "neutral",
                "timeframe": "5-min",
            },
            "rsi_1d": {
                "value":     rsi_1d,
                "zone":      _rsi_zone(rsi_1d) if rsi_1d is not None else "neutral",
                "timeframe": "Daily",
            },
        },
        "checks":    checks,
        "score":     score,
        "max_score": 9,
        "bias":      bias,
        "bias_color": bias_color,
        "candles_5m": len(intra),
    }
    _cache[symbol] = {"ts": now, "data": result}
    return result
