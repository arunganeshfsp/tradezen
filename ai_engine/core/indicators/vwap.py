"""
VWAP (Volume Weighted Average Price) Indicator
===============================================
VWAP = Σ(Price × VolumeDelta) / Σ(VolumeDelta)  — accumulated since session open.

Why VWAP instead of (or alongside) EMA?
  • EMA reacts only to price — it can trend upward while smart money is
    actually selling into a rally at above-average prices.
  • VWAP is anchored to traded volume.  A price above VWAP means buyers
    have been willing to pay more than the session average → bullish bias.
  • Together: EMA (short-term momentum) + VWAP (session fair value) give
    two orthogonal views of trend.

How we use it here:
  • We track VWAP on the NIFTY Spot index (token 26000).
  • Price > VWAP  → market trading above fair value → bullish session bias.
  • Price < VWAP  → market trading below fair value → bearish session bias.
  • Price ≈ VWAP  → indecision, no strong directional bias.

Session handling:
  • VWAP resets to zero at 9:15 AM IST each trading day.
  • The AngelOne WebSocket provides `volume_trade_for_the_day` (cumulative).
    MarketState derives `volume_change` (tick delta) from it.
    We accumulate these deltas.
  • On engine restart mid-session the VWAP starts fresh from the first
    received tick, so it converges toward the true session VWAP over time.
    VWAP_MIN_TICKS guards against acting on an unreliable early estimate.

Score contribution in _aggregate():
  • ABOVE VWAP: bull += up to VWAP_MAX_SCORE (scaled by distance)
  • BELOW VWAP: bear += up to VWAP_MAX_SCORE (scaled by distance)
  • AT VWAP   : side += 5 (no clear direction)
"""

from datetime import datetime, timedelta

from .constants import (
    VWAP_BAND_PCT,
    VWAP_STRONG_PCT,
    VWAP_MIN_TICKS,
    VWAP_MARKET_OPEN_HOUR,
    VWAP_MARKET_OPEN_MIN,
)

# Maximum score this indicator can contribute to bull or bear
VWAP_MAX_SCORE = 12


# ──────────────────────────────────────────────
# Helper — current IST time without requiring pytz / zoneinfo
# ──────────────────────────────────────────────
def _ist_now() -> datetime:
    """Return current datetime in IST (UTC+5:30)."""
    return datetime.utcnow() + timedelta(hours=5, minutes=30)


# ──────────────────────────────────────────────
# Stateful VWAP accumulator
# ──────────────────────────────────────────────
class VWAPCalculator:
    """
    Session VWAP accumulator.

    The engine creates one instance per contract and calls update() on
    every spot tick.  The class owns the session reset logic so the
    calling code never needs to think about it.

    Attributes (read-only, for diagnostics):
        value      : current VWAP price (0.0 until first tick)
        tick_count : number of ticks accumulated this session
    """

    def __init__(self):
        self._cum_pv    = 0.0   # Σ(price × volume_delta) for the session
        self._cum_v     = 0.0   # Σ(volume_delta) for the session
        self._ticks     = 0     # number of ticks accumulated
        self._session_date = None  # IST calendar date of the current session

    # ── Public API ──────────────────────────────────────────────────────
    def update(self, price: float, volume_delta: float) -> float:
        """
        Ingest one tick and return the updated VWAP.

        Args:
            price        : NIFTY spot LTP for this tick
            volume_delta : traded volume for this tick
                           (volume_trade_for_the_day delta from MarketState)

        Returns:
            Current session VWAP, or `price` itself if no volume accumulated yet.
        """
        self._maybe_reset()

        # Only accumulate when real volume was traded this tick.
        # volume_delta can be zero (duplicate tick) or negative (data glitch).
        if volume_delta > 0:
            self._cum_pv += price * volume_delta
            self._cum_v  += volume_delta

        self._ticks += 1

        return self.value if self._cum_v > 0 else price

    @property
    def value(self) -> float:
        """Current VWAP (0.0 if no volume accumulated yet)."""
        if self._cum_v <= 0:
            return 0.0
        return self._cum_pv / self._cum_v

    @property
    def tick_count(self) -> int:
        """Number of ticks accumulated this session."""
        return self._ticks

    # ── Internal ────────────────────────────────────────────────────────
    def _maybe_reset(self):
        """
        Reset accumulators at the start of each new trading session.

        Condition: IST date has changed AND the clock is at/past 9:15 AM.
        We wait for 9:15 so that pre-market ticks (if any) don't start
        a new session accumulation before market open.
        """
        now   = _ist_now()
        today = now.date()

        is_new_day      = self._session_date != today
        is_market_open  = (now.hour > VWAP_MARKET_OPEN_HOUR or
                           (now.hour == VWAP_MARKET_OPEN_HOUR
                            and now.minute >= VWAP_MARKET_OPEN_MIN))

        if is_new_day and is_market_open:
            self._cum_pv       = 0.0
            self._cum_v        = 0.0
            self._ticks        = 0
            self._session_date = today


# ──────────────────────────────────────────────
# Stateless compute function (called by SignalEngine)
# ──────────────────────────────────────────────
def _neutral() -> dict:
    return {
        "direction": "UNKNOWN",
        "vwap":      None,
        "price":     None,
        "diff_pct":  0.0,
        "strength":  0.0,
    }


def compute(spot_data: dict, calculator: VWAPCalculator) -> dict:
    """
    Update the VWAP accumulator and return the current direction signal.

    Args:
        spot_data  : MarketState tick dict for token 26000 (NIFTY spot).
                     Must contain "price" and "volume_change".
        calculator : VWAPCalculator instance owned by SignalEngine.
                     It is mutated on every call — pass the same instance
                     across all ticks (do NOT create a new one per call).

    Returns dict with keys:
        direction : "ABOVE" | "BELOW" | "AT" | "UNKNOWN"
        vwap      : current session VWAP price (float | None)
        price     : spot price used for this tick (float | None)
        diff_pct  : (price − vwap) / vwap × 100 (positive = above)
        strength  : 0–1 normalised distance from VWAP band edge
                    (0 = at VWAP, 1 = at or beyond VWAP_STRONG_PCT)
    """
    if not spot_data:
        return _neutral()

    price        = spot_data.get("price")        or 0.0
    volume_delta = spot_data.get("volume_change") or 0.0

    if price <= 0:
        return _neutral()

    # Update accumulator and get current VWAP
    vwap = calculator.update(price, volume_delta)

    # Don't trust VWAP until enough ticks have accumulated this session.
    # An early VWAP computed from 2–3 ticks can be wildly off if those
    # ticks had very uneven volume (e.g. the opening auction burst).
    if calculator.tick_count < VWAP_MIN_TICKS or vwap <= 0:
        return _neutral()

    # Distance from VWAP as a percentage
    diff_pct = (price - vwap) / vwap * 100

    # Determine direction
    if   diff_pct >  VWAP_BAND_PCT:  direction = "ABOVE"
    elif diff_pct < -VWAP_BAND_PCT:  direction = "BELOW"
    else:                             direction = "AT"

    # Normalised strength: 0 at the band edge, 1.0 at VWAP_STRONG_PCT
    # Capped at 1.0 so the score contribution is bounded.
    band_excess = max(0.0, abs(diff_pct) - VWAP_BAND_PCT)
    strength    = min(band_excess / (VWAP_STRONG_PCT - VWAP_BAND_PCT), 1.0)

    return {
        "direction": direction,
        "vwap":      round(vwap, 2),
        "price":     round(price, 2),
        "diff_pct":  round(diff_pct, 4),
        "strength":  round(strength, 3),
    }
