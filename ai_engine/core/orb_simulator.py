"""
ORB Stock Intraday Simulator — pure business-logic layer.
No I/O, no SmartAPI calls. All time-gated functions accept a `now` arg
for testability; pass None to use live IST time.
"""
import math
import os
from datetime import datetime, time as dt_time, timezone, timedelta

# ── Config constants ──────────────────────────────────────────────────────────
SIM_TARGET_RUPEES = 900       # ₹ target per trade (configurable, not inline)
SIM_CAPITAL       = 100_000   # ₹ max capital per trade
SIM_TICK          = 0.05      # NSE equity minimum tick
SIM_MAX_SLOTS     = 5         # max concurrent open trades
SIM_PRICE_MIN     = 700.0     # ₹ band — inclusive
SIM_PRICE_MAX     = 7_000.0   # ₹ band — inclusive
SIM_DOM_MIN_PCT   = 60.0      # order-book dominance threshold %
SIM_CANDIDATE_CAP = 25        # max candidates per side

_IST = timezone(timedelta(hours=5, minutes=30))

# Set SIM_FORCE_WINDOW=1 in env to bypass all time/weekday gates
_FORCE = os.environ.get("SIM_FORCE_WINDOW", "0") == "1"


def _ist_now() -> datetime:
    return datetime.now(_IST)


# ── Time-window helpers ───────────────────────────────────────────────────────

def in_capture_window(now=None) -> bool:
    """True during the 09:16 capture minute (09:16:00–09:16:59)."""
    if _FORCE:
        return True
    t = (now or _ist_now()).time()
    return dt_time(9, 16) <= t < dt_time(9, 17)


def in_entry_window(now=None) -> bool:
    """True when new entries are allowed: 09:16 to 10:30 inclusive."""
    if _FORCE:
        return True
    now = now or _ist_now()
    if now.weekday() >= 5:        # Saturday / Sunday
        return False
    t = now.time()
    return dt_time(9, 16) <= t <= dt_time(10, 30)


def in_tracking_window(now=None) -> bool:
    """True when outcome tracking is active: 09:16 to 15:30 inclusive."""
    if _FORCE:
        return True
    now = now or _ist_now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt_time(9, 16) <= t <= dt_time(15, 30)


def is_eod(now=None) -> bool:
    """True at exactly or after 15:30 — time to fill close_price on open trades."""
    if _FORCE:
        return False
    t = (now or _ist_now()).time()
    return t >= dt_time(15, 30)


# ── Pure rule functions ───────────────────────────────────────────────────────

def resolve_stop_loss(
    direction: str,
    sl_basis: str,
    bench_high: float,
    bench_low: float,
    vwap: float | None,
    day_high: float | None,
    day_low: float | None,
    custom: float | None,
    entry_price: float,
    amount: float | None = None,
    quantity: int | None = None,
) -> tuple[float | None, str | None]:
    """
    Returns (sl_price, error). sl_price is None on any validation failure.

    Validations:
      1. Structural bases (VWAP/DAY_*/CUSTOM): sl_price must lie within
         [bench_low, bench_high] — the 09:15 candle range. AMOUNT is a ₹-risk
         stop derived from entry price, so the bench-range check does not apply.
      2. BUY: sl must be < entry_price. SELL: sl must be > entry_price.
    """
    if sl_basis == "VWAP":
        sl = vwap
    elif sl_basis == "DAY_HIGH":
        sl = day_high
    elif sl_basis == "DAY_LOW":
        sl = day_low
    elif sl_basis == "CUSTOM":
        if custom is None:
            return None, "Custom SL price required"
        sl = custom
    elif sl_basis == "AMOUNT":
        if not amount or amount <= 0:
            return None, "SL amount (₹) required for amount-based stop"
        if not quantity or quantity <= 0:
            return None, "Quantity required for amount-based stop"
        pts = amount / quantity
        raw = entry_price - pts if direction == "BUY" else entry_price + pts
        sl  = round(round(raw / SIM_TICK) * SIM_TICK, 2)
    else:
        return None, f"Unknown sl_basis '{sl_basis}'"

    if sl is None:
        return None, f"SL basis '{sl_basis}' value is unavailable"

    sl = round(float(sl), 2)

    if sl_basis != "AMOUNT" and not (bench_low <= sl <= bench_high):
        return None, (
            f"SL {sl} is outside benchmark range "
            f"[{bench_low}, {bench_high}]"
        )

    if sl <= 0:
        return None, f"SL {sl} is not a valid price"
    if direction == "BUY" and sl >= entry_price:
        return None, f"SL {sl} must be below entry {entry_price} for BUY"
    if direction == "SELL" and sl <= entry_price:
        return None, f"SL {sl} must be above entry {entry_price} for SELL"

    return sl, None


def position_size(entry_price: float, capital: float = SIM_CAPITAL) -> int:
    """FLOOR(capital / entry_price). Returns 0 for entry_price ≤ 0 or when qty rounds to 0."""
    if entry_price <= 0:
        return 0
    return math.floor(capital / entry_price)


def target_levels(
    direction: str,
    entry_price: float,
    quantity: int,
    target_rupees: float = SIM_TARGET_RUPEES,
) -> tuple[float, float]:
    """
    Returns (target_points, target_price).
    target_points: rounded to 2 decimal places.
    target_price: snapped to nearest ₹0.05 tick.
    Caller must ensure quantity > 0.
    """
    if quantity <= 0:
        return 0.0, 0.0
    target_points = round(target_rupees / quantity, 2)
    if direction == "BUY":
        raw = entry_price + target_points
    else:
        raw = entry_price - target_points
    # Snap to ₹0.05 tick — use integer arithmetic to avoid float drift
    target_price = round(round(raw / SIM_TICK) * SIM_TICK, 2)
    return target_points, target_price


def sl_points_for(direction: str, entry_price: float, sl_price: float) -> float:
    """Always returns a positive number."""
    if direction == "BUY":
        return round(entry_price - sl_price, 2)
    return round(sl_price - entry_price, 2)


def risk_reward(target_points: float, sl_pts: float) -> float:
    if sl_pts <= 0:
        return 0.0
    return round(target_points / sl_pts, 2)


def check_outcome(
    direction: str,
    ltp: float,
    target_price: float,
    stop_loss_price: float,
) -> str | None:
    """
    Returns 'TARGET_HIT', 'SL_HIT', or None (still open).
    SL is checked before target — conservative tie-break on the same poll tick.
    """
    if direction == "BUY":
        if ltp <= stop_loss_price:
            return "SL_HIT"
        if ltp >= target_price:
            return "TARGET_HIT"
    else:  # SELL
        if ltp >= stop_loss_price:
            return "SL_HIT"
        if ltp <= target_price:
            return "TARGET_HIT"
    return None


def pnl_for(
    outcome: str,
    direction: str,
    entry_price: float,
    exit_price: float | None,
    quantity: int,
    target_points: float,
    sl_pts: float,
) -> float:
    """Returns study P/L in ₹. 0 for NO_TRADE or unknown outcome."""
    if outcome == "TARGET_HIT":
        return round(target_points * quantity, 2)
    if outcome == "SL_HIT":
        return round(-sl_pts * quantity, 2)
    if outcome == "SQUARE_OFF" and exit_price is not None:
        if direction == "BUY":
            return round((exit_price - entry_price) * quantity, 2)
        return round((entry_price - exit_price) * quantity, 2)
    return 0.0


def in_price_band(ltp: float) -> bool:
    return SIM_PRICE_MIN <= ltp <= SIM_PRICE_MAX


def passes_volume_filter(side: str, buy_pct: float, sell_pct: float) -> bool:
    """side: 'BUY' | 'SELL'. Checks the ≥60% dominance rule."""
    if side == "BUY":
        return buy_pct >= SIM_DOM_MIN_PCT
    return sell_pct >= SIM_DOM_MIN_PCT
