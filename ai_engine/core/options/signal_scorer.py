"""
Signal scorer (Module 6).
Evaluates 11 weighted signals; returns a composite score and label.
Max score = 17: STRONG 14-17 | MODERATE 10-13 | WEAK 6-9 | SKIP 0-5
"""

import datetime
import logging

log = logging.getLogger(__name__)

_SCORE_LABELS = [
    (14, "STRONG"),
    (10, "MODERATE"),
    (6,  "WEAK"),
    (0,  "SKIP"),
]

# Signal weights
_W = {
    "vix_normal":        1,
    "iv_not_spiked":     2,
    "pcr_aligned":       2,
    "oi_wall_clear":     2,
    "oi_change_confirms":2,
    "ema_trend":         2,
    "vwap_position":     1,
    "volume_confirmed":  2,
    "rsi_aligned":       1,
    "time_before_2pm":   1,
    "no_news_risk":      1,
}


def score_signals(
    *,
    direction: str,            # "CE" | "PE"
    context: dict,             # from iv_analyzer.get_context()
    chain_analytics: dict,     # from max_pain.analyze_chain()
    oi_signals: dict,          # from option_chain_fetcher.get_oi_change_signals() → {strike: {ce, pe}}
    target_strike: float | None = None,
    candle_data: dict | None = None,   # {"close": float, "vwap": float, "volume": float,
                                       #  "ema9": float, "ema21": float,
                                       #  "rsi": float | None, "avg_volume": float | None}
    now: datetime.datetime | None = None,
) -> dict:
    """
    Evaluate all signals and return:
    {
        score, max_score, label,
        signals: {name: {earned, max, reason}}
    }
    """
    if now is None:
        IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now = datetime.datetime.now(IST)

    direction = direction.upper()
    signals: dict[str, dict] = {}

    # ── 1. VIX normal (weight 1) ──────────────────────────────────────────────
    vix = context.get("vix")
    if vix is not None and vix < 20:
        signals["vix_normal"] = {"earned": 1, "max": 1, "reason": f"VIX {vix} < 20"}
    else:
        signals["vix_normal"] = {
            "earned": 0, "max": 1,
            "reason": f"VIX {vix} elevated (≥20)" if vix else "VIX unavailable",
        }

    # ── 2. IV not spiked (weight 2) ───────────────────────────────────────────
    # We use the VIX + context bias as a proxy for IV environment
    vix_ok = vix is not None and vix < 25
    signals["iv_not_spiked"] = {
        "earned": _W["iv_not_spiked"] if vix_ok else 0,
        "max": _W["iv_not_spiked"],
        "reason": f"VIX {vix} within acceptable range (<25)" if vix_ok
                  else f"VIX {vix} spike risk",
    }

    # ── 3. PCR aligned (weight 2) ─────────────────────────────────────────────
    pcr_label = chain_analytics.get("pcr_label", "NEUTRAL")
    pcr       = chain_analytics.get("pcr", 1.0)
    aligned   = (direction == "CE" and pcr_label == "BULLISH") or \
                (direction == "PE" and pcr_label == "BEARISH")
    signals["pcr_aligned"] = {
        "earned": _W["pcr_aligned"] if aligned else (1 if pcr_label == "NEUTRAL" else 0),
        "max": _W["pcr_aligned"],
        "reason": f"PCR {pcr:.3f} ({pcr_label}) {'aligns' if aligned else 'conflicts'} with {direction}",
    }

    # ── 4. OI wall clear (weight 2) ──────────────────────────────────────────
    resistance = chain_analytics.get("resistance_wall")
    support    = chain_analytics.get("support_wall")
    spot       = context.get("spot")
    wall_clear = False
    wall_reason = "Wall data unavailable"
    if spot and resistance and support:
        if direction == "CE":
            # Resistance should be at least 1% above spot for CE trades
            wall_clear  = resistance > spot * 1.01
            wall_reason = f"Resistance wall @ {resistance} ({'clear' if wall_clear else 'too close'} to spot {spot})"
        else:
            wall_clear  = support < spot * 0.99
            wall_reason = f"Support wall @ {support} ({'clear' if wall_clear else 'too close'} to spot {spot})"
    signals["oi_wall_clear"] = {
        "earned": _W["oi_wall_clear"] if wall_clear else 0,
        "max": _W["oi_wall_clear"],
        "reason": wall_reason,
    }

    # ── 5. OI change confirms (weight 2) ─────────────────────────────────────
    oi_confirm = False
    oi_reason  = "No OI change data"
    if target_strike and oi_signals:
        sig = oi_signals.get(target_strike, {})
        leg = sig.get("ce" if direction == "CE" else "pe", "unchanged")
        # Long buildup on the bought leg is confirming
        oi_confirm = leg in ("long_buildup", "short_covering")
        oi_reason  = f"Strike {target_strike} {direction} OI signal: {leg}"
    signals["oi_change_confirms"] = {
        "earned": _W["oi_change_confirms"] if oi_confirm else 0,
        "max": _W["oi_change_confirms"],
        "reason": oi_reason,
    }

    # ── 6. EMA trend (weight 2) ───────────────────────────────────────────────
    ema_ok = False
    ema_reason = "EMA data unavailable"
    if candle_data:
        ema9  = candle_data.get("ema9")
        ema21 = candle_data.get("ema21")
        close = candle_data.get("close")
        if ema9 and ema21 and close:
            if direction == "CE":
                ema_ok     = ema9 > ema21 and close > ema9
                ema_reason = f"EMA9({ema9:.1f}) {'>' if ema9>ema21 else '<'} EMA21({ema21:.1f}), price {'above' if close>ema9 else 'below'} EMA9"
            else:
                ema_ok     = ema9 < ema21 and close < ema9
                ema_reason = f"EMA9({ema9:.1f}) {'<' if ema9<ema21 else '>'} EMA21({ema21:.1f}), price {'below' if close<ema9 else 'above'} EMA9"
    signals["ema_trend"] = {
        "earned": _W["ema_trend"] if ema_ok else 0,
        "max": _W["ema_trend"],
        "reason": ema_reason,
    }

    # ── 7. VWAP position (weight 1) ───────────────────────────────────────────
    vwap_ok = False
    vwap_reason = "VWAP data unavailable"
    if candle_data:
        vwap  = candle_data.get("vwap")
        close = candle_data.get("close")
        if vwap and close:
            if direction == "CE":
                vwap_ok     = close > vwap
                vwap_reason = f"Price {close:.2f} {'above' if vwap_ok else 'below'} VWAP {vwap:.2f}"
            else:
                vwap_ok     = close < vwap
                vwap_reason = f"Price {close:.2f} {'below' if vwap_ok else 'above'} VWAP {vwap:.2f}"
    signals["vwap_position"] = {
        "earned": _W["vwap_position"] if vwap_ok else 0,
        "max": _W["vwap_position"],
        "reason": vwap_reason,
    }

    # ── 8. Volume confirmed (weight 2) ────────────────────────────────────────
    vol_ok = False
    vol_reason = "Volume data unavailable"
    if candle_data:
        volume     = candle_data.get("volume")
        avg_volume = candle_data.get("avg_volume")
        if volume and avg_volume and avg_volume > 0:
            vol_ok     = volume >= avg_volume * 0.8
            vol_reason = f"Volume {volume:,.0f} vs avg {avg_volume:,.0f} ({volume/avg_volume*100:.0f}%)"
        elif volume:
            vol_ok     = True          # no avg baseline — accept if volume present
            vol_reason = f"Volume {volume:,.0f} (no baseline)"
    signals["volume_confirmed"] = {
        "earned": _W["volume_confirmed"] if vol_ok else 0,
        "max": _W["volume_confirmed"],
        "reason": vol_reason,
    }

    # ── 9. RSI aligned (weight 1) ─────────────────────────────────────────────
    rsi_ok = False
    rsi_reason = "RSI unavailable"
    if candle_data:
        rsi = candle_data.get("rsi")
        if rsi is not None:
            if direction == "CE":
                rsi_ok     = 45 <= rsi <= 70
                rsi_reason = f"RSI {rsi:.1f} ({'in range 45-70' if rsi_ok else 'out of range'})"
            else:
                rsi_ok     = 30 <= rsi <= 55
                rsi_reason = f"RSI {rsi:.1f} ({'in range 30-55' if rsi_ok else 'out of range'})"
    signals["rsi_aligned"] = {
        "earned": _W["rsi_aligned"] if rsi_ok else 0,
        "max": _W["rsi_aligned"],
        "reason": rsi_reason,
    }

    # ── 10. Time before 2 PM (weight 1) ──────────────────────────────────────
    hour = now.hour + now.minute / 60
    time_ok     = 9.25 <= hour < 14.0      # 9:15 AM – 2:00 PM
    signals["time_before_2pm"] = {
        "earned": _W["time_before_2pm"] if time_ok else 0,
        "max": _W["time_before_2pm"],
        "reason": f"Time {now.strftime('%H:%M')} {'within' if time_ok else 'outside'} 9:15–14:00 window",
    }

    # ── 11. No news risk (weight 1) ───────────────────────────────────────────
    # Simple heuristic: avoid last 30 min (results/events often released late session)
    news_ok     = hour < 14.5
    signals["no_news_risk"] = {
        "earned": _W["no_news_risk"] if news_ok else 0,
        "max": _W["no_news_risk"],
        "reason": "Within safe trading window" if news_ok else "Late session — event risk elevated",
    }

    # ── Aggregate ─────────────────────────────────────────────────────────────
    total   = sum(s["earned"] for s in signals.values())
    max_s   = sum(s["max"]    for s in signals.values())   # should be 17
    label   = _score_label(total)

    return {
        "score":     total,
        "max_score": max_s,
        "label":     label,
        "direction": direction,
        "signals":   signals,
    }


def _score_label(score: int) -> str:
    for threshold, label in _SCORE_LABELS:
        if score >= threshold:
            return label
    return "SKIP"
