"""
OI Trend Indicator
==================
Measures open interest build-up and unwinding over the rolling window.

BUILD  → fresh positions being added  (supports direction)
UNWIND → existing positions being closed  (short covering)
NEUTRAL → no significant OI movement
"""

from .constants import OI_BUILD_THRESH, OI_UNWIND_THRESH


def compute(ce_oi_hist, pe_oi_hist) -> dict:
    """
    Args:
        ce_oi_hist: TimeWindow of CE open interest values
        pe_oi_hist: TimeWindow of PE open interest values

    Returns dict with keys:
        ce_dir, pe_dir : "BUILD" | "UNWIND" | "NEUTRAL"
        ce_str, pe_str : strength multiplier (0 – 3)
        ce_chg, pe_chg : % change over window (rounded, for display)
    """
    ce_oi = ce_oi_hist.values()
    pe_oi = pe_oi_hist.values()

    if not ce_oi or not pe_oi:
        return {
            "ce_dir": "NEUTRAL", "pe_dir": "NEUTRAL",
            "ce_str": 0.0,       "pe_str": 0.0,
            "ce_chg": 0.0,       "pe_chg": 0.0,
        }

    ce_chg = (ce_oi[-1] - ce_oi[0]) / (ce_oi[0] + 1)
    pe_chg = (pe_oi[-1] - pe_oi[0]) / (pe_oi[0] + 1)

    def _dir_and_strength(chg: float):
        if chg > OI_BUILD_THRESH:
            return "BUILD",  min(chg / OI_BUILD_THRESH, 3.0)
        if chg < OI_UNWIND_THRESH:
            return "UNWIND", min(abs(chg) / abs(OI_UNWIND_THRESH), 3.0)
        return "NEUTRAL", 0.0

    ce_dir, ce_str = _dir_and_strength(ce_chg)
    pe_dir, pe_str = _dir_and_strength(pe_chg)

    return {
        "ce_dir": ce_dir, "pe_dir": pe_dir,
        "ce_str": ce_str, "pe_str": pe_str,
        "ce_chg": round(ce_chg * 100, 2),
        "pe_chg": round(pe_chg * 100, 2),
    }
