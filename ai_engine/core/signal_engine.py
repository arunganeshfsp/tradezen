"""
SignalEngine v4 — TradeZen NIFTY Options
=========================================
Orchestrates the 6 decoupled indicators and applies the signal state machine.

Indicators live in core/indicators/ — each is a standalone compute() function.
Tunable constants live in core/indicators/constants.py.

State machine:
  Entry  : score ≥ SIGNAL_ENTRY_CONF + PERSISTENCE_TICKS confirmations
  Hold   : MIN_SIGNAL_HOLD_SECS lock after entry (no exit, no flip)
  Exit   : score < SIGNAL_EXIT_CONF continuously for SIGNAL_EXIT_SECS
  Flip   : score ≥ FLIP_CONF required to change active direction
"""

import time

from core.indicators import (
    oi_trend,
    price_trend,
    volume_spike,
    imbalance,
    pcr,
    spot_trend,
    vwap,
    VWAPCalculator,
    TimeWindow,
    SIGNAL_ENTRY_CONF,
    SIGNAL_EXIT_CONF,
    SIGNAL_EXIT_SECS,
    MIN_SIGNAL_HOLD_SECS,
    FLIP_CONF,
    PERSISTENCE_TICKS,
    SPOT_TOKEN,
    VOL_SPIKE_FALLBACK,
)


# All indicator keys — used as the default "enable everything" set
ALL_INDICATORS = frozenset({"oi_trend", "price_trend", "vol_spike", "imbalance", "pcr", "spot_trend", "vwap"})


class SignalEngine:
    def __init__(self, ce_token: str, pe_token: str, market_state,
                 enabled: set = None):
        """
        Args:
            ce_token, pe_token : AngelOne NFO tokens for the ATM CE/PE legs
            market_state       : shared MarketState instance
            enabled            : set of indicator keys to use, e.g.
                                 {"oi_trend", "pcr", "spot_trend"}
                                 Defaults to ALL_INDICATORS (all 6 active).
        """
        self.ce_token = ce_token
        self.pe_token = pe_token
        self.market   = market_state
        self.enabled  = frozenset(enabled) if enabled is not None else ALL_INDICATORS

        # Per-leg rolling windows
        self.ce_price_hist   = TimeWindow()
        self.pe_price_hist   = TimeWindow()
        self.ce_oi_hist      = TimeWindow()
        self.pe_oi_hist      = TimeWindow()
        self.ce_vol_hist     = TimeWindow()
        self.pe_vol_hist     = TimeWindow()
        self.spot_price_hist = TimeWindow()

        # VWAP accumulator — one per engine instance, resets at 9:15 AM IST each day
        self.spot_vwap = VWAPCalculator()

        # Signal state machine
        self._last_raw_signal    = None
        self._persist_count      = 0
        self._emitted_signal     = None
        self._emitted_confidence = 0
        self._low_score_since    = None
        self._signal_emitted_at  = None

        self.tick_count = 0

    # ─────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────
    def generate(self) -> dict:
        ce = self.market.get(self.ce_token)
        pe = self.market.get(self.pe_token)

        if not ce or not pe:
            return self._out("WAIT", 0, "No data yet")

        self.tick_count += 1

        # Capture vol stats BEFORE pushing (avoids self-inflation of the spike check)
        ce_vol_avg_pre = self.ce_vol_hist.avg() or 1
        pe_vol_avg_pre = self.pe_vol_hist.avg() or 1
        ce_vol_std_pre = self.ce_vol_hist.std()
        pe_vol_std_pre = self.pe_vol_hist.std()

        # Push current tick to all windows
        self.ce_price_hist.push(ce["price"] or 0)
        self.pe_price_hist.push(pe["price"] or 0)
        self.ce_oi_hist.push(ce["oi"]    or 0)
        self.pe_oi_hist.push(pe["oi"]    or 0)
        self.ce_vol_hist.push(ce["volume"] or 0)
        self.pe_vol_hist.push(pe["volume"] or 0)

        spot_data = self.market.get(SPOT_TOKEN)
        if spot_data and spot_data.get("price"):
            self.spot_price_hist.push(spot_data["price"])

        n_pts = len(self.ce_price_hist.values())
        if not self.ce_price_hist.full():
            return self._out("WAIT", 0, f"Warming up ({n_pts}/5 data points)")

        # ── Compute all indicator scores ───────────────────────────────────
        scores = self._compute_scores(ce, pe,
                                      ce_vol_avg_pre, pe_vol_avg_pre,
                                      ce_vol_std_pre, pe_vol_std_pre,
                                      spot_data)

        # ── Aggregate into bull / bear / sideways ──────────────────────────
        bull_score, bear_score, sideways_score = self._aggregate(scores)
        max_score = max(bull_score, bear_score, sideways_score)

        now = time.time()

        # ── Minimum hold ───────────────────────────────────────────────────
        in_min_hold = (
            self._emitted_signal is not None
            and self._signal_emitted_at is not None
            and (now - self._signal_emitted_at) < MIN_SIGNAL_HOLD_SECS
        )
        min_hold_remaining = (
            int(MIN_SIGNAL_HOLD_SECS - (now - self._signal_emitted_at))
            if in_min_hold else 0
        )

        # ── Hysteresis exit (only outside minimum hold) ────────────────────
        if not in_min_hold:
            if max_score < SIGNAL_EXIT_CONF:
                if self._low_score_since is None:
                    self._low_score_since = now
                elif (now - self._low_score_since) >= SIGNAL_EXIT_SECS:
                    self._emitted_signal     = None
                    self._emitted_confidence = 0
                    self._low_score_since    = None
                    self._signal_emitted_at  = None
            else:
                self._low_score_since = None

        # ── Raw signal direction ───────────────────────────────────────────
        if max_score < SIGNAL_ENTRY_CONF:
            raw_signal = "WAIT"
        elif bull_score > bear_score and bull_score >= sideways_score:
            raw_signal = "BUY CALL"
        elif bear_score > bull_score and bear_score >= sideways_score:
            raw_signal = "BUY PUT"
        elif sideways_score >= bull_score and sideways_score >= bear_score:
            raw_signal = "SIDEWAYS"
        else:
            raw_signal = "WAIT"

        # ── Persistence filter ─────────────────────────────────────────────
        if raw_signal == self._last_raw_signal:
            self._persist_count += 1
        else:
            self._last_raw_signal = raw_signal
            self._persist_count   = 1

        # ── Emit / update signal ───────────────────────────────────────────
        if self._persist_count >= PERSISTENCE_TICKS and raw_signal != "WAIT":
            if self._emitted_signal == raw_signal:
                self._emitted_confidence = int(max_score)
            elif not in_min_hold:
                if self._emitted_signal is not None:
                    if max_score >= FLIP_CONF:
                        self._signal_emitted_at  = now
                        self._emitted_signal     = raw_signal
                        self._emitted_confidence = int(max_score)
                else:
                    self._signal_emitted_at  = now
                    self._emitted_signal     = raw_signal
                    self._emitted_confidence = int(max_score)

        # ── Final output ───────────────────────────────────────────────────
        if in_min_hold:
            final_signal = self._emitted_signal
            confidence   = self._emitted_confidence
        elif raw_signal != "WAIT" and self._persist_count >= PERSISTENCE_TICKS:
            final_signal = raw_signal
            confidence   = int(max_score)
        elif self._emitted_signal:
            final_signal = self._emitted_signal
            confidence   = self._emitted_confidence
        else:
            final_signal = "WAIT"
            confidence   = int(max_score)

        is_held = (
            self._emitted_signal is not None
            and final_signal == self._emitted_signal
            and raw_signal != self._emitted_signal
        )

        secs_held    = round(now - self._low_score_since) if self._low_score_since else 0
        exit_in_secs = (
            max(0, SIGNAL_EXIT_SECS - secs_held)
            if (is_held and not in_min_hold and self._low_score_since)
            else None
        )

        diagnostic = {
            "raw_signal":         raw_signal,
            "persist_count":      self._persist_count,
            "bull":               int(bull_score),
            "bear":               int(bear_score),
            "side":               int(sideways_score),
            "entry_needed":       SIGNAL_ENTRY_CONF,
            "flip_conf":          FLIP_CONF,
            "exit_at":            SIGNAL_EXIT_CONF,
            "exit_in_secs":       exit_in_secs,
            "held":               is_held,
            "in_min_hold":        in_min_hold,
            "min_hold_remaining": min_hold_remaining,
            "spot_dir":           scores["spot_trend"].get("direction", "UNKNOWN"),
            "enabled_indicators": sorted(self.enabled),
        }

        return self._out(
            signal     = final_signal,
            confidence = confidence,
            reason     = self._reason(scores),
            scores     = scores,
            ce         = ce,
            pe         = pe,
            pcr        = round(self._live_pcr(), 3),
            diagnostic = diagnostic,
        )

    # ─────────────────────────────────────────
    # COMPUTE ALL INDICATOR SCORES
    # ─────────────────────────────────────────
    # Neutral return values used when an indicator is disabled.
    # _aggregate() treats these as "no contribution" without needing
    # special-case logic — it just reads neutral/zero fields.
    _NEUTRAL = {
        "oi_trend":    {"ce_dir": "NEUTRAL", "pe_dir": "NEUTRAL",
                        "ce_str": 0.0, "pe_str": 0.0,
                        "ce_chg": 0.0, "pe_chg": 0.0},
        "price_trend": {"ce_up": False, "pe_up": False,
                        "ce_mom": 0.0, "pe_mom": 0.0},
        "vol_spike":   {"ce_spike": False, "pe_spike": False,
                        "ce_mult": 1.0, "pe_mult": 1.0},
        "imbalance":   {"ce_ratio": 1.0, "pe_ratio": 1.0,
                        "ce_bull": False, "pe_bull": False},
        "pcr":         {"pcr": 1.0, "bias": "NEUTRAL"},
        "spot_trend":  {"direction": "UNKNOWN", "strength": 0.0,
                        "price": None, "diff_pct": 0.0},
        # VWAP neutral — direction UNKNOWN contributes 0 to any bucket
        "vwap":        {"direction": "UNKNOWN", "vwap": None,
                        "price": None, "diff_pct": 0.0, "strength": 0.0},
    }

    def _compute_scores(self, ce, pe,
                        ce_vol_avg, pe_vol_avg,
                        ce_vol_std, pe_vol_std,
                        spot_data=None) -> dict:
        on = self.enabled   # shorthand

        return {
            "oi_trend":    oi_trend.compute(self.ce_oi_hist, self.pe_oi_hist)
                           if "oi_trend" in on
                           else self._NEUTRAL["oi_trend"],

            "price_trend": price_trend.compute(self.ce_price_hist, self.pe_price_hist)
                           if "price_trend" in on
                           else self._NEUTRAL["price_trend"],

            "vol_spike":   volume_spike.compute(ce, pe,
                                                ce_vol_avg, pe_vol_avg,
                                                ce_vol_std, pe_vol_std)
                           if "vol_spike" in on
                           else self._NEUTRAL["vol_spike"],

            "imbalance":   imbalance.compute(ce, pe)
                           if "imbalance" in on
                           else self._NEUTRAL["imbalance"],

            "pcr":         pcr.compute(self.ce_oi_hist, self.pe_oi_hist)
                           if "pcr" in on
                           else self._NEUTRAL["pcr"],

            "spot_trend":  spot_trend.compute(self.spot_price_hist)
                           if "spot_trend" in on
                           else self._NEUTRAL["spot_trend"],

            # VWAP needs the live spot tick (price + volume_change) plus the
            # stateful VWAPCalculator that accumulates across ticks.
            "vwap":        vwap.compute(spot_data, self.spot_vwap)
                           if "vwap" in on
                           else self._NEUTRAL["vwap"],
        }

    # ─────────────────────────────────────────
    # AGGREGATE SCORES → bull / bear / side
    # ─────────────────────────────────────────
    def _aggregate(self, scores: dict):
        bull = 0.0
        bear = 0.0
        side = 0.0

        oi   = scores["oi_trend"]
        pt   = scores["price_trend"]
        vol  = scores["vol_spike"]
        imb  = scores["imbalance"]
        pcrv = scores["pcr"]
        spot = scores["spot_trend"]
        vwapv = scores["vwap"]

        # OI build + price confirmation — scaled by strength (max 40 per leg)
        if pt["ce_up"] and oi["ce_dir"] == "BUILD":
            bull += 20 * min(oi["ce_str"], 2.0)
        if pt["pe_up"] and oi["pe_dir"] == "BUILD":
            bear += 20 * min(oi["pe_str"], 2.0)

        # Both sides building simultaneously → sideways / consolidation.
        # Also triggers when both sides are building even if one leg has price
        # trending, because equal bilateral OI accumulation means neither side
        # has a clear edge — directional scores from those legs are cancelled.
        both_building = (oi["ce_dir"] == "BUILD" and oi["pe_dir"] == "BUILD")
        if both_building:
            side += 20
            # Cancel the directional scores already added above — they're
            # unreliable when both sides are absorbing positions equally.
            bull = max(0.0, bull - 20 * min(oi["ce_str"], 2.0))
            bear = max(0.0, bear - 20 * min(oi["pe_str"], 2.0))

        # Short covering (max 15 per leg)
        if oi["ce_dir"] == "UNWIND" and pt["ce_up"]:
            bull += 15
        if oi["pe_dir"] == "UNWIND" and pt["pe_up"]:
            bear += 15

        # Volume conviction — scaled by multiplier (max 20 per leg)
        if vol["ce_spike"] and pt["ce_up"]:
            bull += 10 * min(vol["ce_mult"] / VOL_SPIKE_FALLBACK, 2.0)
        if vol["pe_spike"] and pt["pe_up"]:
            bear += 10 * min(vol["pe_mult"] / VOL_SPIKE_FALLBACK, 2.0)

        # Bid/ask relative pressure (max 15 per leg)
        if imb["ce_bull"]:
            bull += 15
        if imb["pe_bull"]:
            bear += 15

        # PCR bias (max 15)
        if   pcrv["bias"] == "BULL": bull += 15
        elif pcrv["bias"] == "BEAR": bear += 15
        else:                        side += 10

        # NIFTY Spot direction bonus (max 15)
        s_dir = spot.get("direction", "UNKNOWN")
        s_str = spot.get("strength",  0.0)
        if   s_dir == "UP":   bull += min(10 * s_str, 15)
        elif s_dir == "DOWN": bear += min(10 * s_str, 15)
        elif s_dir == "FLAT": side += 5

        # Spot dampening gate — strong opposing trend penalises that direction
        if s_dir == "DOWN" and s_str >= 1.2:
            factor = max(0.4, 1.0 - (s_str - 1.2) * 0.25)
            bull *= factor
        elif s_dir == "UP" and s_str >= 1.2:
            factor = max(0.4, 1.0 - (s_str - 1.2) * 0.25)
            bear *= factor

        # VWAP session bias (max VWAP_MAX_SCORE per direction, scaled by strength)
        # Price above VWAP → bullish session context; below → bearish.
        # "AT" adds a small sideways nudge (indecision, no clear bias).
        v_dir = vwapv.get("direction", "UNKNOWN")
        v_str = vwapv.get("strength",  0.0)
        if   v_dir == "ABOVE": bull += vwap.VWAP_MAX_SCORE * v_str
        elif v_dir == "BELOW": bear += vwap.VWAP_MAX_SCORE * v_str
        elif v_dir == "AT":    side += 5

        return bull, bear, side

    # ─────────────────────────────────────────
    # HUMAN-READABLE REASON STRING
    # ─────────────────────────────────────────
    def _reason(self, scores: dict) -> str:
        parts = []
        oi    = scores["oi_trend"]
        vol   = scores["vol_spike"]
        imb   = scores["imbalance"]
        pcrv  = scores["pcr"]
        pt    = scores["price_trend"]
        spot  = scores["spot_trend"]
        vwapv = scores["vwap"]

        if oi["ce_dir"] == "BUILD":
            parts.append(f"CE OI build ({oi['ce_chg']:+.1f}%) + CE {'▲' if pt['ce_up'] else '▼'} EMA {pt['ce_mom']:+.2f}%")
        if oi["pe_dir"] == "BUILD":
            parts.append(f"PE OI build ({oi['pe_chg']:+.1f}%) + PE {'▲' if pt['pe_up'] else '▼'} EMA {pt['pe_mom']:+.2f}%")
        if oi["ce_dir"] == "UNWIND":
            parts.append(f"CE short cover ({oi['ce_chg']:+.1f}%)")
        if oi["pe_dir"] == "UNWIND":
            parts.append(f"PE short cover ({oi['pe_chg']:+.1f}%)")
        if vol["ce_spike"]:
            parts.append(f"CE vol ×{vol['ce_mult']} (spike)")
        if vol["pe_spike"]:
            parts.append(f"PE vol ×{vol['pe_mult']} (spike)")
        if imb["ce_bull"]:
            parts.append(f"CE bid pressure {imb['ce_ratio']}× vs PE {imb['pe_ratio']}×")
        if imb["pe_bull"]:
            parts.append(f"PE bid pressure {imb['pe_ratio']}× vs CE {imb['ce_ratio']}×")
        if spot["direction"] in ("UP", "DOWN"):
            parts.append(f"NIFTY spot {spot['direction']} ({spot['diff_pct']:+.3f}%)")
        parts.append(f"PCR {pcrv['pcr']} ({pcrv['bias']})")
        if vwapv["direction"] in ("ABOVE", "BELOW"):
            parts.append(f"VWAP {vwapv['direction']} ({vwapv['diff_pct']:+.3f}%)")

        return " | ".join(parts) if parts else "No strong signals this tick"

    # ─────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────
    def _live_pcr(self) -> float:
        ce_oi = self.ce_oi_hist.last()
        pe_oi = self.pe_oi_hist.last()
        if not ce_oi or not pe_oi:
            return 1.0
        return pe_oi / ce_oi

    def _out(self, signal, confidence, reason="",
             scores=None, ce=None, pe=None, pcr=None, diagnostic=None) -> dict:
        result = {
            "signal":     signal,
            "confidence": confidence,
            "reason":     reason,
            "timestamp":  int(time.time() * 1000),
        }
        if scores is not None:
            result["factors"] = {
                "oi_trend":    scores.get("oi_trend",    {}),
                "price_trend": scores.get("price_trend", {}),
                "vol_spike":   scores.get("vol_spike",   {}),
                "imbalance":   scores.get("imbalance",   {}),
                "pcr":         scores.get("pcr",         {}),
                "spot_trend":  scores.get("spot_trend",  {}),
                "vwap":        scores.get("vwap",        {}),
            }
        if ce  is not None: result["ce"]         = ce
        if pe  is not None: result["pe"]         = pe
        if pcr is not None: result["pcr"]        = pcr
        if diagnostic:      result["diagnostic"] = diagnostic
        return result
