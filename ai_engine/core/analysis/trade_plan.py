"""Risk/reward trade plan calculator."""
import math


def calculate_trade_plan(
    entry: float, stop: float, t1: float, t2: float
) -> dict:
    """
    Compute full trade plan from entry, stop, and two targets.
    Position sizing assumes ₹5,00,000 capital with 1% max risk per trade.
    """
    risk_pts  = round(entry - stop, 2)
    reward_t1 = round(t1 - entry, 2)
    reward_t2 = round(t2 - entry, 2)
    rr_t1     = round(reward_t1 / risk_pts, 2) if risk_pts else 0.0
    rr_t2     = round(reward_t2 / risk_pts, 2) if risk_pts else 0.0
    capital   = 500_000
    max_loss  = capital * 0.01
    qty       = math.floor(max_loss / risk_pts) if risk_pts > 0 else 0

    return {
        "entry":         entry,
        "stop":          stop,
        "target1":       t1,
        "target2":       t2,
        "risk_pts":      risk_pts,
        "reward_t1":     reward_t1,
        "reward_t2":     reward_t2,
        "rr_t1":         rr_t1,
        "rr_t2":         rr_t2,
        "capital":       capital,
        "max_loss":      max_loss,
        "suggested_qty": qty,
    }
