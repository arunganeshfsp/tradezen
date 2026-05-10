"""
Supertrend Indicator
====================
ATR-based trend-following indicator (period=10, multiplier=3 standard settings).

Returns direction ('up' / 'down' / 'neutral') and support/resistance level per
candle.  Used by the Market Psychology Engine.

Algorithm:
  1. True Range = max(H-L, |H-Prev_C|, |L-Prev_C|)
  2. ATR = Wilder RMA smoothing of TR (same as TradingView)
  3. Basic Upper = HL2 + mult * ATR  →  Final Upper only moves down
     Basic Lower = HL2 - mult * ATR  →  Final Lower only moves up
  4. Direction:
       - Switches to 'up'   when close > final_upper
       - Switches to 'down' when close < final_lower
       - In 'up'  mode: Supertrend line = final_lower (support)
       - In 'down' mode: Supertrend line = final_upper (resistance)
"""

import numpy as np
import pandas as pd


def compute(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> list:
    """
    Compute Supertrend for a DataFrame with High/Low/Close columns.

    Args:
        df:         DataFrame with columns Open, High, Low, Close, Volume.
        period:     ATR lookback window (default 10).
        multiplier: Band multiplier (default 3.0).

    Returns:
        List of dicts, one per row:
            { 'value': float | None, 'direction': 'up' | 'down' | 'neutral' }
        'value' is the support level when 'up', resistance level when 'down'.
    """
    high  = df["High"].values.astype(float)
    low   = df["Low"].values.astype(float)
    close = df["Close"].values.astype(float)
    n     = len(df)

    if n < period:
        return [{"value": None, "direction": "neutral"}] * n

    # ── True Range ────────────────────────────────────────────────────────────
    tr = np.empty(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i]  - close[i - 1]),
        )

    # ── ATR — Wilder RMA (same as TradingView's ta.atr) ──────────────────────
    atr = np.zeros(n)
    atr[period - 1] = float(np.mean(tr[:period]))
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    # ── Basic bands ───────────────────────────────────────────────────────────
    hl2   = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    # ── Final bands and Supertrend value ─────────────────────────────────────
    f_upper = np.empty(n)
    f_lower = np.empty(n)
    st_val  = np.empty(n)
    dirs    = ["neutral"] * n

    f_upper[0] = upper[0]
    f_lower[0] = lower[0]
    st_val[0]  = lower[0]
    dirs[0]    = "neutral"

    for i in range(1, n):
        # Upper band: tightens only downward (never expands upward)
        f_upper[i] = (
            upper[i]
            if upper[i] < f_upper[i - 1] or close[i - 1] > f_upper[i - 1]
            else f_upper[i - 1]
        )
        # Lower band: tightens only upward (never expands downward)
        f_lower[i] = (
            lower[i]
            if lower[i] > f_lower[i - 1] or close[i - 1] < f_lower[i - 1]
            else f_lower[i - 1]
        )

        if i < period:
            dirs[i]   = "neutral"
            st_val[i] = f_lower[i]
        elif dirs[i - 1] == "down":
            if close[i] > f_upper[i]:
                dirs[i]   = "up"
                st_val[i] = f_lower[i]
            else:
                dirs[i]   = "down"
                st_val[i] = f_upper[i]
        else:  # 'up' or 'neutral'
            if close[i] < f_lower[i]:
                dirs[i]   = "down"
                st_val[i] = f_upper[i]
            else:
                dirs[i]   = "up"
                st_val[i] = f_lower[i]

    return [
        {
            "value":     float(st_val[i]) if atr[i] > 0 else None,
            "direction": dirs[i],
        }
        for i in range(n)
    ]
