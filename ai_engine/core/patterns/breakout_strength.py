"""
Breakout target and stop-loss for Cup & Handle patterns.

Entry  : 0.3% above handle high (breakout confirmation candle)
Stop   : below handle low (handle range acts as support)
Target1: entry + cup_depth   (measured move, 1× projection)
Target2: entry + cup_depth×2 (extended target)
"""


def calculate_targets(
    left_rim_val: float,
    cup_low_val: float,
    handle_high: float,
    handle_low: float,
    current_price: float,
) -> dict:
    cup_depth = left_rim_val - cup_low_val

    entry     = round(handle_high * 1.003, 2)
    stop_loss = round(handle_low * 0.992, 2)   # just below handle low
    target1   = round(entry + cup_depth, 2)
    target2   = round(entry + cup_depth * 2.0, 2)

    risk      = round(entry - stop_loss, 2)
    reward1   = round(target1 - entry, 2)
    rr1       = round(reward1 / risk, 2) if risk > 0 else 0.0
    pct_entry = round((entry - current_price) / current_price * 100, 2)

    return {
        "entry":        entry,
        "stop_loss":    stop_loss,
        "target1":      target1,
        "target2":      target2,
        "risk_pts":     risk,
        "reward_pts":   reward1,
        "rr_ratio":     rr1,
        "pct_to_entry": pct_entry,
        "cup_depth_pts": round(cup_depth, 2),
    }
