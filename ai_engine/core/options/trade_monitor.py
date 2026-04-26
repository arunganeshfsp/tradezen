"""
Trade monitor (Module 10).
Tracks live option P&L and evaluates exit conditions.
Pure functions — no I/O.
"""

import datetime
import logging

log = logging.getLogger(__name__)

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_MARKET_CLOSE_HOUR = 15
_MARKET_CLOSE_MIN  = 25    # force-exit 5 min before 3:30 PM


def evaluate(position: dict, current_ltp: float,
             now: datetime.datetime | None = None) -> dict:
    """
    Evaluate a live option position against exit conditions.

    position = {
        direction,        ← "CE" | "PE"
        entry_ltp,
        stop_price,
        target1_price,
        target2_price,
        lots,
        lot_size,
        t1_hit,           ← bool, default False
        entry_time,       ← ISO string (optional)
    }

    Returns:
    {
        action,           ← "HOLD" | "EXIT_STOP" | "EXIT_T1" | "EXIT_T2" | "EXIT_EOD" | "TRAIL"
        pnl,              ← current unrealised P&L (₹)
        pnl_pct,          ← as % of entry value
        current_ltp,
        reason,
    }
    """
    if now is None:
        now = datetime.datetime.now(_IST)

    entry   = float(position["entry_ltp"])
    stop    = float(position["stop_price"])
    t1      = float(position["target1_price"])
    t2      = float(position["target2_price"])
    lots    = int(position.get("lots", 1))
    lot_sz  = int(position.get("lot_size", 1))
    t1_hit  = bool(position.get("t1_hit", False))
    total_qty = lots * lot_sz

    pnl       = round((current_ltp - entry) * total_qty, 2)
    pnl_pct   = round((current_ltp - entry) / entry * 100, 2) if entry > 0 else 0

    # ── Force exit before market close ───────────────────────────────────────
    if (now.hour > _MARKET_CLOSE_HOUR or
            (now.hour == _MARKET_CLOSE_HOUR and now.minute >= _MARKET_CLOSE_MIN)):
        return _result("EXIT_EOD", pnl, pnl_pct, current_ltp,
                       f"Market closing — forced exit at {current_ltp:.2f}")

    # ── Stop loss ─────────────────────────────────────────────────────────────
    if current_ltp <= stop:
        return _result("EXIT_STOP", pnl, pnl_pct, current_ltp,
                       f"Stop hit: LTP {current_ltp:.2f} ≤ stop {stop:.2f}")

    # ── Target 2 ─────────────────────────────────────────────────────────────
    if current_ltp >= t2:
        return _result("EXIT_T2", pnl, pnl_pct, current_ltp,
                       f"Target 2 hit: LTP {current_ltp:.2f} ≥ T2 {t2:.2f}")

    # ── Target 1 ─────────────────────────────────────────────────────────────
    if not t1_hit and current_ltp >= t1:
        return _result("EXIT_T1", pnl, pnl_pct, current_ltp,
                       f"Target 1 hit: LTP {current_ltp:.2f} ≥ T1 {t1:.2f} — book 50 %, trail rest")

    # ── Trail suggestion after T1 ─────────────────────────────────────────────
    if t1_hit:
        return _result("TRAIL", pnl, pnl_pct, current_ltp,
                       f"T1 booked — trailing toward T2 {t2:.2f}")

    return _result("HOLD", pnl, pnl_pct, current_ltp, "Within range — no action")


def update_position(position: dict, action: str, current_ltp: float) -> dict:
    """
    Return an updated copy of the position dict after an action.
    Handles T1 partial exit: marks t1_hit, raises stop to break-even.
    """
    pos = dict(position)
    if action == "EXIT_T1":
        pos["t1_hit"]    = True
        pos["stop_price"] = pos["entry_ltp"]   # move stop to break-even
        log.info(f"T1 hit — stop moved to break-even {pos['entry_ltp']:.2f}")
    return pos


def _result(action: str, pnl: float, pnl_pct: float,
            ltp: float, reason: str) -> dict:
    return {
        "action":      action,
        "pnl":         pnl,
        "pnl_pct":     pnl_pct,
        "current_ltp": ltp,
        "reason":      reason,
    }
