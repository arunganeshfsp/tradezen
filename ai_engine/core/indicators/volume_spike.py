"""
Volume Spike Indicator
======================
Dynamic spike detection: volume > mean + 1.5 × std.

Falls back to a fixed multiplier when std ≈ 0 (e.g. mid-afternoon lull
where volume is unusually stable).  Adapts to session volatility rather
than using a fixed threshold that would mis-fire on volatile opens.
"""

from .constants import VOL_SPIKE_STDMULT, VOL_SPIKE_FALLBACK


def compute(ce: dict, pe: dict,
            ce_avg: float, pe_avg: float,
            ce_std: float, pe_std: float) -> dict:
    """
    Args:
        ce, pe         : latest MarketState tick dicts for each leg
        ce_avg, pe_avg : rolling volume mean (captured BEFORE pushing current tick)
        ce_std, pe_std : rolling volume std  (captured BEFORE pushing current tick)

    Returns dict with keys:
        ce_spike, pe_spike : bool — did volume exceed the spike threshold?
        ce_mult,  pe_mult  : current volume as a multiple of the rolling mean
    """
    def _is_spike(vol: float, avg: float, std: float):
        if avg < 1:
            return False, 1.0
        if std > avg * 0.05:                          # std is meaningful
            threshold = avg + VOL_SPIKE_STDMULT * std
        else:                                          # near-zero std → fixed
            threshold = avg * VOL_SPIKE_FALLBACK
        mult = round(vol / avg, 2)
        return vol >= threshold, mult

    ce_spike, ce_mult = _is_spike(ce.get("volume") or 0, ce_avg, ce_std)
    pe_spike, pe_mult = _is_spike(pe.get("volume") or 0, pe_avg, pe_std)

    return {
        "ce_spike": ce_spike, "pe_spike": pe_spike,
        "ce_mult":  ce_mult,  "pe_mult":  pe_mult,
    }
