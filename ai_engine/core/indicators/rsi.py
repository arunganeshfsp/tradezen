"""RSI (Relative Strength Index) — Wilder's method with simple-average seed."""
import numpy as np
import pandas as pd


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff().values
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    n = len(gain)

    avg_gain = np.full(n, np.nan)
    avg_loss = np.full(n, np.nan)

    if n > period:
        # Seed: simple average of first `period` changes (Wilder's canonical init)
        avg_gain[period] = gain[1:period + 1].mean()
        avg_loss[period] = loss[1:period + 1].mean()
        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period

    with np.errstate(divide='ignore', invalid='ignore'):
        rs = avg_gain / avg_loss  # inf when avg_loss==0 (pure up-move → RSI 100)
    rsi = np.clip(100.0 - (100.0 / (1.0 + rs)), 0, 100)
    return pd.Series(rsi, index=series.index)
