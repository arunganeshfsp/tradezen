"""
Depth ratio analyzer (Module 9a).
Computes bid/ask quantity ratio from SmartAPI depth data.
Pure function — no I/O.
"""


def analyze(depth: dict) -> dict:
    """
    depth = {"buy": [{price, quantity},...], "sell": [{price, quantity},...]}

    Returns:
    {
        bid_qty, ask_qty, ratio,
        pressure,   ← "BUY" | "SELL" | "NEUTRAL"
        top_bid, top_ask,
    }
    """
    buy_levels  = depth.get("buy",  []) or []
    sell_levels = depth.get("sell", []) or []

    bid_qty = sum(int(level.get("quantity", 0)) for level in buy_levels)
    ask_qty = sum(int(level.get("quantity", 0)) for level in sell_levels)

    top_bid = float(buy_levels[0].get("price",  0)) if buy_levels  else 0.0
    top_ask = float(sell_levels[0].get("price", 0)) if sell_levels else 0.0

    total = bid_qty + ask_qty
    ratio = round(bid_qty / ask_qty, 3) if ask_qty > 0 else (999.0 if bid_qty > 0 else 1.0)

    if   ratio >= 1.5:  pressure = "BUY"
    elif ratio <= 0.67: pressure = "SELL"
    else:               pressure = "NEUTRAL"

    return {
        "bid_qty":  bid_qty,
        "ask_qty":  ask_qty,
        "ratio":    ratio,
        "pressure": pressure,
        "top_bid":  top_bid,
        "top_ask":  top_ask,
    }


def chain_depth_summary(chain: list[dict], near_strikes: int = 5,
                        spot_price: float | None = None) -> dict:
    """
    Aggregate depth ratio across the strikes nearest to spot.
    Returns overall buy_pressure / sell_pressure for CE and PE legs.
    """
    if spot_price and chain:
        sorted_chain = sorted(chain, key=lambda s: abs(s["strike"] - spot_price))
        subset = sorted_chain[:near_strikes]
    else:
        subset = chain[:near_strikes]

    ce_bid = ce_ask = pe_bid = pe_ask = 0
    for s in subset:
        ce_depth = s.get("ce", {}).get("depth", {})
        pe_depth = s.get("pe", {}).get("depth", {})
        r_ce = analyze(ce_depth)
        r_pe = analyze(pe_depth)
        ce_bid += r_ce["bid_qty"];  ce_ask += r_ce["ask_qty"]
        pe_bid += r_pe["bid_qty"];  pe_ask += r_pe["ask_qty"]

    def _ratio(b, a): return round(b / a, 3) if a > 0 else (999.0 if b > 0 else 1.0)
    def _pressure(r): return "BUY" if r >= 1.5 else ("SELL" if r <= 0.67 else "NEUTRAL")

    ce_r = _ratio(ce_bid, ce_ask)
    pe_r = _ratio(pe_bid, pe_ask)
    return {
        "ce": {"bid_qty": ce_bid, "ask_qty": ce_ask, "ratio": ce_r, "pressure": _pressure(ce_r)},
        "pe": {"bid_qty": pe_bid, "ask_qty": pe_ask, "ratio": pe_r, "pressure": _pressure(pe_r)},
    }
