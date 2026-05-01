"""Candle-based MACD indicator."""
import pandas as pd
from .ema import calculate_ema


def calculate_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Returns dict with keys: macd_line, signal_line, histogram — all pd.Series."""
    ema_fast    = calculate_ema(series, fast)
    ema_slow    = calculate_ema(series, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return {
        "macd_line":   macd_line,
        "signal_line": signal_line,
        "histogram":   histogram,
    }
