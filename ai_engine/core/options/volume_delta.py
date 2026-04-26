"""
Volume delta tracker (Module 9b).
Candle-based buy/sell volume estimation and cumulative delta.
Pure functions — no I/O.
"""


def candle_delta(candle: dict) -> dict:
    """
    Estimate buy vs. sell volume from a single OHLCV candle.
    Uses the standard approximation:
        buy_vol  = volume × (close − low)  / (high − low)
        sell_vol = volume × (high − close) / (high − low)

    candle: {open, high, low, close, volume}
    Returns: {buy_vol, sell_vol, delta, direction}
    """
    o = float(candle.get("open",  0))
    h = float(candle.get("high",  0))
    l = float(candle.get("low",   0))
    c = float(candle.get("close", 0))
    v = float(candle.get("volume", 0))

    spread = h - l
    if spread <= 0:
        buy_vol = sell_vol = v / 2
    else:
        buy_vol  = v * (c - l) / spread
        sell_vol = v * (h - c) / spread

    buy_vol  = round(buy_vol,  2)
    sell_vol = round(sell_vol, 2)
    delta    = round(buy_vol - sell_vol, 2)

    return {
        "buy_vol":   buy_vol,
        "sell_vol":  sell_vol,
        "delta":     delta,
        "direction": "BUY" if delta > 0 else ("SELL" if delta < 0 else "NEUTRAL"),
    }


def cumulative_delta(candles: list[dict]) -> dict:
    """
    Compute cumulative delta across a list of candles.
    Returns:
    {
        cum_delta,
        trend,        ← "ACCUMULATION" | "DISTRIBUTION" | "NEUTRAL"
        candle_deltas ← list of per-candle delta dicts
    }
    """
    if not candles:
        return {"cum_delta": 0, "trend": "NEUTRAL", "candle_deltas": []}

    deltas = [candle_delta(c) for c in candles]
    cum    = round(sum(d["delta"] for d in deltas), 2)

    if   cum > 0:  trend = "ACCUMULATION"
    elif cum < 0:  trend = "DISTRIBUTION"
    else:          trend = "NEUTRAL"

    return {
        "cum_delta":     cum,
        "trend":         trend,
        "candle_deltas": deltas,
    }
