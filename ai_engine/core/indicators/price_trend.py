"""
Price Trend Indicator
=====================
EMA cross-based trend detection on option LTP.
Fast EMA > Slow EMA → upward momentum.

Filters out bid-ask bounce that makes raw LTP[-1] > LTP[0]
on single-tick noise — only sustained divergence counts.
"""

from .constants import EMA_FAST_SPAN, EMA_SLOW_SPAN, MIN_PRICE_MOM


def compute(ce_price_hist, pe_price_hist) -> dict:
    """
    Args:
        ce_price_hist: TimeWindow of CE LTP values
        pe_price_hist: TimeWindow of PE LTP values

    Returns dict with keys:
        ce_up, pe_up  : bool — is this leg in an uptrend?
        ce_mom, pe_mom: EMA divergence % (positive = bullish for that leg)
        ce_ema_fast, pe_ema_fast: fast EMA value (for diagnostics)
    """
    ce_v = ce_price_hist.values()
    pe_v = pe_price_hist.values()

    if not ce_v or not pe_v:
        return {
            "ce_up": False, "pe_up": False,
            "ce_mom": 0.0,  "pe_mom": 0.0,
        }

    ce_fast = ce_price_hist.ema(EMA_FAST_SPAN)
    ce_slow = ce_price_hist.ema(EMA_SLOW_SPAN)
    pe_fast = pe_price_hist.ema(EMA_FAST_SPAN)
    pe_slow = pe_price_hist.ema(EMA_SLOW_SPAN)

    ce_mom = round((ce_fast - ce_slow) / (ce_slow + 0.01) * 100, 2)
    pe_mom = round((pe_fast - pe_slow) / (pe_slow + 0.01) * 100, 2)

    return {
        "ce_up":      ce_mom > MIN_PRICE_MOM,
        "pe_up":      pe_mom > MIN_PRICE_MOM,
        "ce_mom":     ce_mom,
        "pe_mom":     pe_mom,
        "ce_ema_fast": round(ce_fast, 2),
        "pe_ema_fast": round(pe_fast, 2),
    }
