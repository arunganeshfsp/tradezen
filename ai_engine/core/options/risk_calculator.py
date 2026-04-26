"""
Risk calculator (Module 8).
Pure function — computes position size, P&L levels, and exit prices.
"""

import math
import logging

log = logging.getLogger(__name__)

_DEFAULT_CAPITAL   = 500_000     # ₹5,00,000
_DEFAULT_RISK_PCT  = 0.01        # 1 %
_MIN_LOTS          = 1
_MAX_LOTS          = 50


def calculate(
    *,
    entry_ltp: float,
    lot_size: int,
    direction: str,              # "CE" | "PE"
    capital: float = _DEFAULT_CAPITAL,
    risk_pct: float = _DEFAULT_RISK_PCT,
    stop_pct: float = 0.40,      # exit when option loses 40 % of entry value
    target1_pct: float = 0.60,   # book 50 % at +60 % of entry value
    target2_pct: float = 1.20,   # trail remainder toward +120 %
) -> dict:
    """
    Returns position sizing and P&L plan:
    {
        entry_ltp, lot_size, lots, total_qty, total_premium,
        stop_price, target1_price, target2_price,
        max_loss, potential_profit_t1, potential_profit_t2,
        rr_t1, rr_t2,
        capital, risk_pct,
    }
    """
    if entry_ltp <= 0 or lot_size <= 0:
        return {"error": "Invalid entry_ltp or lot_size"}

    max_loss_budget = capital * risk_pct
    premium_per_lot = entry_ltp * lot_size
    if premium_per_lot <= 0:
        return {"error": "Zero premium per lot"}

    # Number of lots where worst-case loss ≤ budget
    # Worst case: option expires worthless → lose full premium
    lots = math.floor(max_loss_budget / premium_per_lot)
    lots = max(_MIN_LOTS, min(lots, _MAX_LOTS))

    total_qty     = lots * lot_size
    total_premium = round(entry_ltp * total_qty, 2)

    stop_price    = round(entry_ltp * (1 - stop_pct),   2)
    target1_price = round(entry_ltp * (1 + target1_pct), 2)
    target2_price = round(entry_ltp * (1 + target2_pct), 2)

    stop_price    = max(0.05, stop_price)    # floor at tick minimum

    loss_per_lot   = (entry_ltp - stop_price) * lot_size
    profit_t1_lot  = (target1_price - entry_ltp) * lot_size
    profit_t2_lot  = (target2_price - entry_ltp) * lot_size

    max_loss         = round(loss_per_lot   * lots, 2)
    potential_t1     = round(profit_t1_lot  * lots, 2)
    potential_t2     = round(profit_t2_lot  * lots, 2)

    rr_t1 = round(profit_t1_lot / loss_per_lot, 2) if loss_per_lot > 0 else 0
    rr_t2 = round(profit_t2_lot / loss_per_lot, 2) if loss_per_lot > 0 else 0

    return {
        "entry_ltp":         entry_ltp,
        "lot_size":          lot_size,
        "lots":              lots,
        "total_qty":         total_qty,
        "total_premium":     total_premium,
        "stop_price":        stop_price,
        "target1_price":     target1_price,
        "target2_price":     target2_price,
        "max_loss":          max_loss,
        "potential_profit_t1": potential_t1,
        "potential_profit_t2": potential_t2,
        "rr_t1":             rr_t1,
        "rr_t2":             rr_t2,
        "capital":           capital,
        "risk_pct":          risk_pct,
    }
