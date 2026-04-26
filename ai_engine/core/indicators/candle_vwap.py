"""
Candle-based VWAP (stateless, for historical OHLCV DataFrames).

Separate from core/indicators/vwap.py which is a stateful tick accumulator
for the live Angel One WebSocket feed. This version works on any OHLCV DataFrame
and resets at the start of the passed data — so pass a full session (from 9:15)
for an accurate intraday VWAP.
"""
import pandas as pd


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Compute cumulative session VWAP from an OHLCV DataFrame.
    Expects columns: High, Low, Close, Volume.
    Returns pd.Series of VWAP values aligned to df's index.
    """
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_pv  = (typical * df["Volume"]).cumsum()
    cum_v   = df["Volume"].cumsum().replace(0, float("nan"))
    return cum_pv / cum_v
