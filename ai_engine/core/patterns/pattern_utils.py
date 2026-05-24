"""
Shared low-level utilities for pattern detection.
"""

import numpy as np
import pandas as pd


def find_pivot_highs(series: pd.Series, window: int = 10) -> list[int]:
    """Return positional indices (0-based) of local maxima with given half-window."""
    vals = series.values
    n = len(vals)
    highs = []
    for i in range(window, n - window):
        seg = vals[i - window: i + window + 1]
        if vals[i] >= seg.max():
            highs.append(i)
    return highs


def find_pivot_lows(series: pd.Series, window: int = 10) -> list[int]:
    """Return positional indices of local minima."""
    vals = series.values
    n = len(vals)
    lows = []
    for i in range(window, n - window):
        seg = vals[i - window: i + window + 1]
        if vals[i] <= seg.min():
            lows.append(i)
    return lows


def quadratic_fit(y: np.ndarray) -> tuple[float, float]:
    """
    Fit degree-2 polynomial to y (normalised [0,1] range expected).
    Returns (curvature_a, r_squared).  Positive 'a' = U-shape (convex).
    """
    if len(y) < 6:
        return 0.0, 0.0
    x = np.linspace(0.0, 1.0, len(y))
    coeffs = np.polyfit(x, y, 2)
    a = float(coeffs[0])
    y_fit = np.polyval(coeffs, x)
    ss_res = float(np.sum((y - y_fit) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return a, float(r2)


def vol_mean(volume: pd.Series, start: int, end: int) -> float:
    """Mean volume in slice [start, end)."""
    seg = volume.iloc[start:end]
    return float(seg.mean()) if len(seg) > 0 else 0.0


def pct(a: float, b: float) -> float:
    """Percentage change: (b - a) / a * 100.  Returns 0 if a == 0."""
    return (b - a) / a * 100.0 if a > 0 else 0.0
