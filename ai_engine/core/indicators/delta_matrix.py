"""
Delta Matrix — per-column buy/sell volume estimate built from 1-minute intrabars.

AngelOne data carries no trade-aggressor side, so each 1-minute bar's volume is
split into buyer- and seller-initiated volume by one of two methods:
    updown : whole bar volume goes to the side the bar closed toward
             (close vs open, then close vs previous close, then previous side) —
             the same rule TradingView uses for intrabar up/down volume
    clv    : volume split by where the close sits inside the high-low range
Columns are anchored to the 09:15 NSE open, so a 60-min grid is 09:15, 10:15 … 15:15.
Pure functions — no I/O.
"""

from datetime import datetime, time, timedelta

from core.options.volume_delta import candle_delta

TIMEFRAMES = (5, 15, 30, 60)
METHODS    = ("updown", "clv")

SESSION_OPEN    = time(9, 15)
SESSION_CLOSE   = time(15, 30)
SESSION_MINUTES = 375

VOL_SPIKE_RATIO    = 1.5
VOL_SPIKE_LOOKBACK = 20


def bars_per_session(tf: int) -> int:
    return -(-SESSION_MINUTES // tf)


def lookback_days(tf: int, cols: int) -> int:
    """Calendar days of 1-min history needed to fill `cols` columns (+1 session, weekend/holiday slack)."""
    sessions = -(-cols // bars_per_session(tf)) + 1
    return sessions * 7 // 5 + 4


def _column_start(dt: datetime, tf: int) -> datetime | None:
    if not (SESSION_OPEN <= dt.time() < SESSION_CLOSE):
        return None
    open_dt = datetime.combine(dt.date(), SESSION_OPEN)
    mins = int((dt - open_dt).total_seconds() // 60)
    return open_dt + timedelta(minutes=(mins // tf) * tf)


def _updown_split(o, c, v, prev_close, prev_side):
    if c > o:
        side = 1
    elif c < o:
        side = -1
    elif prev_close is not None and c != prev_close:
        side = 1 if c > prev_close else -1
    else:
        side = prev_side
    if side > 0:
        return v, 0.0, side
    if side < 0:
        return 0.0, v, side
    return v / 2, v / 2, side


def build_matrix(candles, tf: int, method: str = "updown", now: datetime | None = None) -> list[dict]:
    """
    candles: iterable of (datetime_str "YYYY-MM-DD HH:MM", open, high, low, close, volume),
             1-minute bars sorted ascending (the candle_fetcher row shape).
    now:     naive IST datetime; marks the column still forming as live.

    Returns one dict per column, oldest first. Cum delta runs across every
    session passed in; session delta resets at each new trading date.
    """
    if tf not in TIMEFRAMES:
        raise ValueError(f"tf must be one of {TIMEFRAMES}")
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")

    cols: list[dict] = []
    cur = None
    prev_close, prev_side = None, 0

    for dt_str, o, h, l, c, v in candles:
        dt = datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M")
        start = _column_start(dt, tf)
        if start is None:
            continue
        o, h, l, c, v = float(o), float(h), float(l), float(c), float(v)

        if method == "updown":
            buy, sell, prev_side = _updown_split(o, c, v, prev_close, prev_side)
        else:
            split = candle_delta({"open": o, "high": h, "low": l, "close": c, "volume": v})
            buy, sell = split["buy_vol"], split["sell_vol"]
        prev_close = c

        if cur is None or cur["start"] != start:
            cur = {"start": start, "open": o, "high": h, "low": l, "close": c,
                   "volume": 0.0, "buy": 0.0, "sell": 0.0,
                   "running": 0.0, "max": None, "min": None}
            cols.append(cur)

        cur["high"]    = max(cur["high"], h)
        cur["low"]     = min(cur["low"], l)
        cur["close"]   = c
        cur["volume"] += v
        cur["buy"]    += buy
        cur["sell"]   += sell
        cur["running"] += buy - sell
        cur["max"] = cur["running"] if cur["max"] is None else max(cur["max"], cur["running"])
        cur["min"] = cur["running"] if cur["min"] is None else min(cur["min"], cur["running"])

    out: list[dict] = []
    cum = session = 0.0
    session_date = None
    for i, col in enumerate(cols):
        start = col["start"]
        new_session = start.date() != session_date
        if new_session:
            session, session_date = 0.0, start.date()
        delta = col["running"]
        cum += delta
        session += delta

        prior = [p["volume"] for p in cols[max(0, i - VOL_SPIKE_LOOKBACK):i]]
        avg_vol = sum(prior) / len(prior) if prior else 0.0
        vol_ratio = col["volume"] / avg_vol if avg_vol else None

        end = min(start + timedelta(minutes=tf), datetime.combine(start.date(), SESSION_CLOSE))
        out.append({
            "time":          start.strftime("%Y-%m-%d %H:%M"),
            "date":          start.strftime("%Y-%m-%d"),
            "label":         start.strftime("%H:%M"),
            "session_start": new_session,
            "live":          now is not None and start <= now < end,
            "open":          round(col["open"], 2),
            "high":          round(col["high"], 2),
            "low":           round(col["low"], 2),
            "close":         round(col["close"], 2),
            "volume":        round(col["volume"]),
            "buy_vol":       round(col["buy"]),
            "sell_vol":      round(col["sell"]),
            "delta":         round(delta),
            "max_delta":     round(col["max"]),
            "min_delta":     round(col["min"]),
            "cum_delta":     round(cum),
            "session_delta": round(session),
            "delta_pct":     round(abs(delta) / col["volume"] * 100, 1) if col["volume"] else 0.0,
            "vol_ratio":     round(vol_ratio, 2) if vol_ratio is not None else None,
            "vol_spike":     vol_ratio is not None and vol_ratio >= VOL_SPIKE_RATIO,
        })
    return out
