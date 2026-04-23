"""
TradeZen Signal Indicators
===========================
Each indicator is a pure function:  compute(...) -> dict

Usage from signal_engine.py:
    from core.indicators import oi_trend, price_trend, volume_spike
    from core.indicators import imbalance, pcr, spot_trend

    scores = {
        "oi_trend":   oi_trend.compute(ce_oi_hist, pe_oi_hist),
        "price_trend": price_trend.compute(ce_price_hist, pe_price_hist),
        ...
    }

To add a new indicator:
    1. Create core/indicators/my_indicator.py with a compute() function
    2. Import and call it in signal_engine._compute_scores()
    3. Add its score contribution to signal_engine._aggregate()
    4. Add it to the frontend INDICATORS array in fno_signal.html
"""

from . import oi_trend
from . import price_trend
from . import volume_spike
from . import imbalance
from . import pcr
from . import spot_trend
from . import vwap
from .vwap import VWAPCalculator

from .time_window import TimeWindow
from .constants import (
    WINDOW_SECONDS,
    MIN_WINDOW_POINTS,
    SIGNAL_ENTRY_CONF,
    SIGNAL_EXIT_CONF,
    SIGNAL_EXIT_SECS,
    MIN_SIGNAL_HOLD_SECS,
    FLIP_CONF,
    PERSISTENCE_TICKS,
    SPOT_TOKEN,
    VOL_SPIKE_FALLBACK,
)

__all__ = [
    "oi_trend",
    "price_trend",
    "volume_spike",
    "imbalance",
    "pcr",
    "spot_trend",
    "vwap",
    "VWAPCalculator",
    "TimeWindow",
    # constants needed by signal_engine
    "WINDOW_SECONDS",
    "MIN_WINDOW_POINTS",
    "SIGNAL_ENTRY_CONF",
    "SIGNAL_EXIT_CONF",
    "SIGNAL_EXIT_SECS",
    "MIN_SIGNAL_HOLD_SECS",
    "FLIP_CONF",
    "PERSISTENCE_TICKS",
    "SPOT_TOKEN",
    "VOL_SPIKE_FALLBACK",
]
