"""
Bid/Ask Imbalance Indicator
============================
Relative depth imbalance using top-5 bid/ask levels when available.

Why relative (CE vs PE) rather than absolute?
  Indian retail structurally buys more CALL options than PUT options.
  An absolute buy/sell ratio of 1.5× on CE is meaningless on its own;
  but if CE shows 1.5× while PE shows 0.8×, the divergence is a real signal.

Why top-5 depth?
  Spoofing concentrates at the best bid/ask.  Summing 5 levels dilutes
  a single large phantom order so it cannot single-handedly trigger a signal.
"""

from .constants import IMBALANCE_THRESH


def compute(ce: dict, pe: dict) -> dict:
    """
    Args:
        ce, pe : latest MarketState tick dicts (must include depth_buy/sell_qty
                 or total_buy/sell_quantity as fallback)

    Returns dict with keys:
        ce_ratio, pe_ratio : bid/ask ratio for each leg
        ce_bull            : True if CE ratio dominates (bullish pressure)
        pe_bull            : True if PE ratio dominates (bearish pressure)
    """
    def _depth_ratio(d: dict) -> float:
        buy  = d.get("depth_buy_qty")  or d.get("buy_qty",  0) or 0
        sell = d.get("depth_sell_qty") or d.get("sell_qty", 0) or 1
        return round(buy / sell, 3)

    ce_ratio = _depth_ratio(ce)
    pe_ratio = _depth_ratio(pe)

    pe_floor = pe_ratio or 0.01
    ce_floor = ce_ratio or 0.01

    return {
        "ce_ratio": ce_ratio,
        "pe_ratio": pe_ratio,
        "ce_bull":  ce_ratio >= pe_floor * IMBALANCE_THRESH,
        "pe_bull":  pe_ratio >= ce_floor * IMBALANCE_THRESH,
    }
