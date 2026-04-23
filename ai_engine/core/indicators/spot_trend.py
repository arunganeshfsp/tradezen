"""
NIFTY Spot Trend Indicator
===========================
EMA cross direction on the NIFTY 50 index (token 26000).

Used in two ways inside _aggregate():
  1. Bonus score when underlying confirms the option signal direction.
  2. Dampening gate when underlying strongly opposes the signal direction
     — prevents counter-trend entries when the index is moving hard one way.

Returns gracefully with direction="UNKNOWN" if the spot token is not
subscribed, so the engine degrades rather than failing outright.
"""

from .constants import SPOT_EMA_FAST, SPOT_EMA_SLOW, SPOT_MIN_DIFF_PCT


def compute(spot_price_hist) -> dict:
    """
    Args:
        spot_price_hist: TimeWindow of NIFTY spot prices (token 26000)

    Returns dict with keys:
        direction : "UP" | "DOWN" | "FLAT" | "UNKNOWN"
        strength  : 0 – 2 (how far diverged from threshold)
        price     : latest spot price
        diff_pct  : EMA fast-slow divergence %
    """
    v = spot_price_hist.values()
    if len(v) < 3:
        return {"direction": "UNKNOWN", "strength": 0.0, "price": None, "diff_pct": 0.0}

    fast = spot_price_hist.ema(SPOT_EMA_FAST)
    slow = spot_price_hist.ema(SPOT_EMA_SLOW)

    diff_pct = (fast - slow) / (slow + 0.01) * 100

    if   diff_pct >  SPOT_MIN_DIFF_PCT: direction = "UP"
    elif diff_pct < -SPOT_MIN_DIFF_PCT: direction = "DOWN"
    else:                               direction = "FLAT"

    strength = min(abs(diff_pct) / SPOT_MIN_DIFF_PCT, 2.0)

    return {
        "direction": direction,
        "strength":  round(strength, 2),
        "price":     v[-1],
        "diff_pct":  round(diff_pct, 4),
    }
