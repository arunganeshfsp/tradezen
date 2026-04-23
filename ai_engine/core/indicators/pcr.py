"""
Put-Call Ratio (PCR) Indicator
================================
Measures the ratio of total PE open interest to CE open interest.

PCR > 1.3 → BULL  (put writers active = institutions expect upside)
PCR < 0.7 → BEAR  (call writers active = institutions expect downside)
Otherwise  → NEUTRAL

Thresholds are deliberately wider than the classic 1.0 midpoint because
NIFTY's PCR is structurally elevated — retail always holds more puts for
hedging, so a "neutral" raw PCR sits naturally above 1.0.
"""

from .constants import PCR_BULL_THRESH, PCR_BEAR_THRESH


def compute(ce_oi_hist, pe_oi_hist) -> dict:
    """
    Args:
        ce_oi_hist: TimeWindow of CE open interest (uses latest value only)
        pe_oi_hist: TimeWindow of PE open interest (uses latest value only)

    Returns dict with keys:
        pcr  : float — pe_oi / ce_oi
        bias : "BULL" | "BEAR" | "NEUTRAL"
    """
    ce_oi = ce_oi_hist.last()
    pe_oi = pe_oi_hist.last()

    # Both legs must have real OI before computing PCR.
    # Missing OI → pe_oi / 1 could give an enormous PCR → permanent BULL signal.
    if not ce_oi or not pe_oi:
        return {"pcr": 1.0, "bias": "NEUTRAL"}

    pcr = round(pe_oi / ce_oi, 3)

    if   pcr > PCR_BULL_THRESH: bias = "BULL"
    elif pcr < PCR_BEAR_THRESH: bias = "BEAR"
    else:                       bias = "NEUTRAL"

    return {"pcr": pcr, "bias": bias}
