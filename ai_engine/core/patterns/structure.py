"""
Cup geometry validation: depth, recovery, roundness, symmetry.
"""

import numpy as np
import pandas as pd

from .pattern_utils import quadratic_fit, pct

MIN_DEPTH = 10.0
MAX_DEPTH = 40.0
MIN_RECOVERY = 80.0    # right_rim / left_rim  (%)
MAX_RECOVERY = 112.0   # right rim can slightly exceed left rim
MIN_CUP_DAYS = 20
MAX_CUP_DAYS = 180


def validate_cup(
    close: pd.Series,
    left_idx: int,
    bottom_idx: int,
    right_idx: int,
    min_days: int = MIN_CUP_DAYS,
    max_days: int = MAX_CUP_DAYS,
) -> dict:
    """
    Validate geometric properties of a potential cup.
    All indices are positional (0-based) in `close`.

    Returns dict with 'valid' bool and metric fields.
    """
    left_val   = float(close.iloc[left_idx])
    bottom_val = float(close.iloc[bottom_idx])
    right_val  = float(close.iloc[right_idx])
    cup_len    = right_idx - left_idx

    if cup_len < min_days:
        return {"valid": False, "reason": f"Cup too short ({cup_len}d, min {min_days})"}
    if cup_len > max_days:
        return {"valid": False, "reason": f"Cup too long ({cup_len}d, max {max_days})"}

    depth_pct = pct(left_val, bottom_val) * -1          # positive = drop
    if not (MIN_DEPTH <= depth_pct <= MAX_DEPTH):
        return {"valid": False, "reason": f"Depth {depth_pct:.1f}% outside 10-40% range"}

    recovery_pct = right_val / left_val * 100
    if recovery_pct < MIN_RECOVERY:
        return {"valid": False, "reason": f"Recovery {recovery_pct:.1f}% < 80% (right rim too low)"}
    if recovery_pct > MAX_RECOVERY:
        return {"valid": False, "reason": f"Right rim {recovery_pct:.1f}% too far above left rim"}

    # Roundness: quadratic fit on normalised cup body
    cup_arr = close.iloc[left_idx: right_idx + 1].values.astype(float)
    c_min, c_max = cup_arr.min(), cup_arr.max()
    normed = (cup_arr - c_min) / (c_max - c_min) if c_max > c_min else cup_arr - cup_arr[0]
    curvature_a, r2 = quadratic_fit(normed)

    if curvature_a <= 0:
        return {"valid": False, "reason": "Cup is not U-shaped (concave or flat)"}

    # Symmetry: cup bottom should sit in the middle 20–80% of the cup range
    bottom_rel = (bottom_idx - left_idx) / cup_len if cup_len > 0 else 0.5
    symmetry = max(0.0, 1.0 - abs(bottom_rel - 0.50) * 2.5)

    roundness = max(0.0, min(1.0, float(r2)))

    return {
        "valid":          True,
        "reason":         f"Cup {depth_pct:.1f}% depth, {recovery_pct:.1f}% recovery, {cup_len}d",
        "depth_pct":      round(depth_pct, 2),
        "recovery_pct":   round(recovery_pct, 2),
        "symmetry":       round(symmetry, 3),
        "roundness":      round(roundness, 3),
        "curvature_a":    round(curvature_a, 4),
        "r2":             round(r2, 3),
        "left_val":       round(left_val, 2),
        "bottom_val":     round(bottom_val, 2),
        "right_val":      round(right_val, 2),
        "cup_len":        cup_len,
    }


def validate_handle(
    close: pd.Series,
    right_idx: int,
    current_idx: int,
) -> dict:
    """
    Validate handle: 3-15% pullback, length 3-35 candles,
    stays in upper half of cup, current price near handle high.
    """
    seg    = close.iloc[right_idx: current_idx + 1]
    h_len  = len(seg) - 1          # candles since right rim

    if h_len < 3:
        return {"valid": False, "reason": f"Handle too short ({h_len}d)"}
    if h_len > 35:
        return {"valid": False, "reason": f"Handle too long ({h_len}d)"}

    h_high   = float(seg.max())
    h_low    = float(seg.min())
    h_close  = float(close.iloc[current_idx])

    if h_high <= 0:
        return {"valid": False, "reason": "Invalid handle high"}

    pullback = pct(h_high, h_low) * -1          # positive = drop from high

    if pullback < 3.0:
        return {"valid": False, "reason": f"Handle pullback too shallow ({pullback:.1f}% < 3%)"}
    if pullback > 15.0:
        return {"valid": False, "reason": f"Handle pullback too deep ({pullback:.1f}% > 15%)"}

    near_breakout = h_close >= h_high * 0.97

    return {
        "valid":         True,
        "reason":        f"Handle {pullback:.1f}% pullback over {h_len}d",
        "high":          round(h_high, 2),
        "low":           round(h_low, 2),
        "pullback_pct":  round(pullback, 2),
        "near_breakout": near_breakout,
        "len_days":      h_len,
    }
