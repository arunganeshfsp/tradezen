"""
Max pain calculator + option chain analytics (Module 4).
Pure functions — no I/O, no external calls.
"""

import logging

log = logging.getLogger(__name__)


def analyze_chain(chain: list[dict], spot_price: float | None = None) -> dict:
    """
    Derive all option chain analytics from a list of strike rows.

    Each row: {strike, ce:{oi, ltp, ...}, pe:{oi, ltp, ...}}

    Returns:
        max_pain        – strike where total option loss is minimised
        resistance_wall – strike with highest CE OI (call writers defending)
        support_wall    – strike with highest PE OI (put writers defending)
        pcr             – total PE OI / total CE OI
        pcr_label       – "BULLISH" | "BEARISH" | "NEUTRAL"
        trading_range   – {low: support_wall, high: resistance_wall}
        total_ce_oi     – aggregate CE open interest
        total_pe_oi     – aggregate PE open interest
    """
    if not chain:
        return _empty()

    valid = [
        s for s in chain
        if s.get("ce", {}).get("oi") is not None
        and s.get("pe", {}).get("oi") is not None
    ]
    if not valid:
        return _empty()

    max_pain     = _max_pain(valid)
    res_wall     = max(valid, key=lambda s: s["ce"].get("oi") or 0)["strike"]
    sup_wall     = max(valid, key=lambda s: s["pe"].get("oi") or 0)["strike"]
    total_ce_oi  = sum(s["ce"].get("oi") or 0 for s in valid)
    total_pe_oi  = sum(s["pe"].get("oi") or 0 for s in valid)
    pcr          = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 1.0
    pcr_label    = _pcr_label(pcr)

    return {
        "max_pain":        max_pain,
        "resistance_wall": res_wall,
        "support_wall":    sup_wall,
        "pcr":             pcr,
        "pcr_label":       pcr_label,
        "trading_range":   {"low": sup_wall, "high": res_wall},
        "total_ce_oi":     total_ce_oi,
        "total_pe_oi":     total_pe_oi,
    }


def _max_pain(chain: list[dict]) -> float:
    """
    Identify the strike at which total option writers' loss is minimised.
    At expiry, if spot closes at strike K:
      CE writers pay max(0, spot − K_strike) × CE_OI for each strike ≤ K
      PE writers pay max(0, K_strike − spot) × PE_OI for each strike ≥ K
    """
    strikes = [s["strike"] for s in chain]
    min_pain = float("inf")
    pain_strike = strikes[0]

    for candidate in strikes:
        ce_loss = sum(
            max(0.0, candidate - s["strike"]) * (s["ce"].get("oi") or 0)
            for s in chain
        )
        pe_loss = sum(
            max(0.0, s["strike"] - candidate) * (s["pe"].get("oi") or 0)
            for s in chain
        )
        total = ce_loss + pe_loss
        if total < min_pain:
            min_pain    = total
            pain_strike = candidate

    return pain_strike


def _pcr_label(pcr: float) -> str:
    if   pcr > 1.3: return "BULLISH"
    elif pcr < 0.7: return "BEARISH"
    else:           return "NEUTRAL"


def _empty() -> dict:
    return {
        "max_pain":        None,
        "resistance_wall": None,
        "support_wall":    None,
        "pcr":             1.0,
        "pcr_label":       "NEUTRAL",
        "trading_range":   {"low": None, "high": None},
        "total_ce_oi":     0,
        "total_pe_oi":     0,
    }
