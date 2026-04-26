"""Candle-based EMA calculator for OHLCV DataFrames."""
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average using pandas ewm (adjust=False)."""
    return series.ewm(span=period, adjust=False).mean()
