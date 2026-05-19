"""
Signal scorer (Module 6).
Evaluates 11 weighted signals; returns a composite score and label.
Max score = 17: STRONG 14-17 | MODERATE 10-13 | WEAK 6-9 | SKIP 0-5

Missing-data policy:
  - Signals backed by unavailable data are marked earned=0 but ALSO excluded
    from the effective max so they don't drag the score unfairly.
  - A data_quality dict is returned so the UI can warn the user.
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
    oi_signals: dict,          # from option_chain_fetcher.get_oi_change_signals()
    target_strike: float | None = None,
    candle_data: dict | None = None,
    now: datetime.datetime | None = None,
) -> dict:
    if now is None:
        IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now = datetime.datetime.now(IST)

    direction = direction.upper()
    signals: dict[str, dict] = {}
    missing_data: list[str]  = []   # signals that had no data input

    # ── 1. VIX normal (weight 1) ──────────────────────────────────────────────
    vix = context.get("vix")
    if vix is None:
        # Don't penalise for missing data — exclude from effective max
        signals["vix_normal"] = {"earned": 0, "max": 1, "reason": "VIX unavailable — excluded from score", "no_data": True}
        missing_data.append("vix_normal")
    elif vix < 20:
        signals["vix_normal"] = {"earned": 1, "max": 1, "reason": f"VIX {vix} < 20 ✓"}
    else:
        signals["vix_normal"] = {"earned": 0, "max": 1, "reason": f"VIX {vix} elevated (≥20)"}

    # ── 2. IV not spiked (weight 2) ───────────────────────────────────────────
    if vix is None:
        signals["iv_not_spiked"] = {"earned": 0, "max": 2, "reason": "VIX unavailable — excluded from score", "no_data": True}
        missing_data.append("iv_not_spiked")
    else:
        vix_ok = vix < 25
        signals["iv_not_spiked"] = {
            "earned": _W["iv_not_spiked"] if vix_ok else 0,
            "max": _W["iv_not_spiked"],
            "reason": f"VIX {vix} within range (<25) ✓" if vix_ok else f"VIX {vix} spike risk",
        }

    # ── 3. PCR aligned (weight 2) ─────────────────────────────────────────────
    pcr_label = chain_analytics.get("pcr_label", "NEUTRAL")
    pcr       = chain_analytics.get("pcr", 1.0)
    # If chain data is the hard-coded default (pcr exactly 1.0, no resistance/support),
    # treat as missing rather than NEUTRAL so it doesn't quietly give 1 partial point.
    chain_missing = (
        chain_analytics.get("resistance_wall") is None and
        chain_analytics.get("support_wall")    is None and
        pcr == 1.0
    )
    if chain_missing:
        signals["pcr_aligned"] = {"earned": 0, "max": 2, "reason": "Chain data unavailable — excluded from score", "no_data": True}
        missing_data.append("pcr_aligned")
    else:
        aligned = (direction == "CE" and pcr_label == "BULLISH") or \
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
    if chain_missing or not spot or (resistance is None and support is None):
        signals["oi_wall_clear"] = {"earned": 0, "max": 2, "reason": "OI wall data unavailable — excluded from score", "no_data": True}
        missing_data.append("oi_wall_clear")
    else:
        if direction == "CE":
            wall_clear  = resistance is None or resistance > spot * 1.01
            wall_reason = f"Resistance wall @ {resistance} ({'clear' if wall_clear else 'too close'} to spot {spot})" if resistance else f"No CE wall detected above spot {spot}"
        else:
            wall_clear  = support is None or support < spot * 0.99
            wall_reason = f"Support wall @ {support} ({'clear' if wall_clear else 'too close'} to spot {spot})" if support else f"No PE wall detected below spot {spot}"
        signals["oi_wall_clear"] = {"earned": _W["oi_wall_clear"] if wall_clear else 0, "max": _W["oi_wall_clear"], "reason": wall_reason}

    # ── 5. OI change confirms (weight 2) ─────────────────────────────────────
    if not target_strike or not oi_signals:
        signals["oi_change_confirms"] = {"earned": 0, "max": 2, "reason": "OI change data unavailable — excluded from score", "no_data": True}
        missing_data.append("oi_change_confirms")
    else:
        sig        = oi_signals.get(target_strike, {})
        leg        = sig.get("ce" if direction == "CE" else "pe", "unchanged")
        oi_confirm = leg in ("long_buildup", "short_covering")
        signals["oi_change_confirms"] = {
            "earned": _W["oi_change_confirms"] if oi_confirm else 0,
            "max": _W["oi_change_confirms"],
            "reason": f"Strike {target_strike} {direction} OI: {leg}",
        }

    # ── 6. EMA trend (weight 2) ───────────────────────────────────────────────
    if not candle_data:
        signals["ema_trend"] = {"earned": 0, "max": 2, "reason": "Candle data unavailable — excluded from score", "no_data": True}
        missing_data.append("ema_trend")
    else:
        ema9  = candle_data.get("ema9")
        ema21 = candle_data.get("ema21")
        close = candle_data.get("close")
        if ema9 and ema21 and close:
            if direction == "CE":
                ema_ok     = ema9 > ema21 and close > ema9
                ema_reason = f"EMA9({ema9:.0f}) {'>' if ema9>ema21 else '<'} EMA21({ema21:.0f}), price {'above' if close>ema9 else 'below'} EMA9"
            else:
                ema_ok     = ema9 < ema21 and close < ema9
                ema_reason = f"EMA9({ema9:.0f}) {'<' if ema9<ema21 else '>'} EMA21({ema21:.0f}), price {'below' if close<ema9 else 'above'} EMA9"
            signals["ema_trend"] = {"earned": _W["ema_trend"] if ema_ok else 0, "max": _W["ema_trend"], "reason": ema_reason}
        else:
            signals["ema_trend"] = {"earned": 0, "max": 2, "reason": "EMA values missing in candle data", "no_data": True}
            missing_data.append("ema_trend")

    # ── 7. VWAP position (weight 1) ───────────────────────────────────────────
    if not candle_data:
        signals["vwap_position"] = {"earned": 0, "max": 1, "reason": "Candle data unavailable — excluded from score", "no_data": True}
        missing_data.append("vwap_position")
    else:
        vwap  = candle_data.get("vwap")
        close = candle_data.get("close")
        if vwap and close:
            if direction == "CE":
                vwap_ok     = close > vwap
                vwap_reason = f"Price {close:.0f} {'above' if vwap_ok else 'below'} VWAP {vwap:.0f}"
            else:
                vwap_ok     = close < vwap
                vwap_reason = f"Price {close:.0f} {'below' if vwap_ok else 'above'} VWAP {vwap:.0f}"
            signals["vwap_position"] = {"earned": _W["vwap_position"] if vwap_ok else 0, "max": _W["vwap_position"], "reason": vwap_reason}
        else:
            signals["vwap_position"] = {"earned": 0, "max": 1, "reason": "VWAP missing in candle data", "no_data": True}
            missing_data.append("vwap_position")

    # ── 8. Volume confirmed (weight 2) ────────────────────────────────────────
    if not candle_data:
        signals["volume_confirmed"] = {"earned": 0, "max": 2, "reason": "Candle data unavailable — excluded from score", "no_data": True}
        missing_data.append("volume_confirmed")
    else:
        volume     = candle_data.get("volume")
        avg_volume = candle_data.get("avg_volume")
        if volume and avg_volume and avg_volume > 0:
            vol_ok     = volume >= avg_volume * 0.8
            vol_reason = f"Vol {volume:,.0f} vs avg {avg_volume:,.0f} ({volume/avg_volume*100:.0f}%)"
        elif volume:
            vol_ok     = True
            vol_reason = f"Volume {volume:,.0f} (no baseline)"
        else:
            vol_ok, vol_reason = False, "Volume zero or missing"
        signals["volume_confirmed"] = {"earned": _W["volume_confirmed"] if vol_ok else 0, "max": _W["volume_confirmed"], "reason": vol_reason}

    # ── 9. RSI aligned (weight 1) ─────────────────────────────────────────────
    # CE: RSI >= 45 (bullish momentum; no upper cap — strong rally RSI >70 is still bullish)
    # PE: RSI <= 55 (bearish momentum; no lower cap)
    if not candle_data:
        signals["rsi_aligned"] = {"earned": 0, "max": 1, "reason": "Candle data unavailable — excluded from score", "no_data": True}
        missing_data.append("rsi_aligned")
    else:
        rsi = candle_data.get("rsi")
        if rsi is not None:
            if direction == "CE":
                rsi_ok     = rsi >= 45
                rsi_reason = f"RSI {rsi:.1f} {'≥45 bullish ✓' if rsi_ok else '<45 weak momentum'}"
                if rsi > 75:
                    rsi_reason += " (overbought — caution on entry)"
            else:
                rsi_ok     = rsi <= 55
                rsi_reason = f"RSI {rsi:.1f} {'≤55 bearish ✓' if rsi_ok else '>55 weak momentum'}"
                if rsi < 25:
                    rsi_reason += " (oversold — caution on entry)"
            signals["rsi_aligned"] = {"earned": _W["rsi_aligned"] if rsi_ok else 0, "max": _W["rsi_aligned"], "reason": rsi_reason}
        else:
            signals["rsi_aligned"] = {"earned": 0, "max": 1, "reason": "RSI unavailable — excluded from score", "no_data": True}
            missing_data.append("rsi_aligned")

    # ── 10. Time before 2 PM (weight 1) ──────────────────────────────────────
    hour     = now.hour + now.minute / 60
    time_ok  = 9.25 <= hour < 14.0
    signals["time_before_2pm"] = {
        "earned": _W["time_before_2pm"] if time_ok else 0,
        "max": _W["time_before_2pm"],
        "reason": f"Time {now.strftime('%H:%M')} {'within' if time_ok else 'outside'} 9:15–14:00 window",
    }

    # ── 11. No news risk (weight 1) ───────────────────────────────────────────
    news_ok  = hour < 14.5
    signals["no_news_risk"] = {
        "earned": _W["no_news_risk"] if news_ok else 0,
        "max": _W["no_news_risk"],
        "reason": "Within safe trading window" if news_ok else "Late session — event risk elevated",
    }

    # ── Aggregate (exclude missing-data signals from max_score) ──────────────
    total     = sum(s["earned"] for s in signals.values())
    # Effective max = full max minus weight of missing signals
    missing_weight = sum(_W.get(k, 0) for k in missing_data)
    eff_max   = sum(_W.values()) - missing_weight   # max reachable with available data
    label     = _score_label_pct(total, eff_max)

    return {
        "score":         total,
        "max_score":     sum(_W.values()),   # always 17 for UI display
        "eff_max":       eff_max,            # what's actually reachable
        "label":         label,
        "direction":     direction,
        "signals":       signals,
        "missing_count": len(missing_data),
        "missing_data":  missing_data,
    }


def _score_label_pct(score: int, eff_max: int) -> str:
    """Label based on % of available score, not raw number."""
    if eff_max <= 0:
        return "NO DATA"
    pct = score / eff_max
    if pct >= 0.82: return "STRONG"
    if pct >= 0.59: return "MODERATE"
    if pct >= 0.35: return "WEAK"
    return "SKIP"
