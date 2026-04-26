"""Candle-based MACD (12, 26, 9) indicator."""
import pandas as pd
from .ema import calculate_ema


def calculate_macd(series: pd.Series) -> dict:
    """
    Compute MACD for a price series.
    Returns dict with keys: macd_line, signal_line, histogram — all pd.Series.
    """
    ema_fast    = calculate_ema(series, 12)
    ema_slow    = calculate_ema(series, 26)
    macd_line   = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, 9)
    histogram   = macd_line - signal_line
    return {
        "macd_line":   macd_line,
        "signal_line": signal_line,
        "histogram":   histogram,
    }
