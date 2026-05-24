"""
Cup & Handle pattern detector — three detection stages.

  "complete"       Cup + valid handle, price near breakout
  "handle_forming" Cup complete, handle developing but not yet near high
  "cup_complete"   Cup fully formed, handle not yet started
  "early_cup"      Cup forming — left high set, 10-40% drop, partial recovery

Data source: yfinance 1-year daily OHLCV (identical path to swing_analyzer.py).
Cache: 1 hour (patterns on daily chart don't change intraday).
"""

import logging
import time

import numpy as np
import pandas as pd

from .pattern_utils import find_pivot_highs, vol_mean, pct
from .structure import validate_cup, validate_handle
from .scoring import score
from .breakout_strength import calculate_targets

log = logging.getLogger(__name__)

_CACHE: dict = {}
_TTL = 3600          # 1-hour cache

MIN_PATTERN_SCORE = 25.0   # minimum score to report a detection


# ──────────────────────────────────────────────────────────────────────────────
# Data fetching
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_daily(symbol: str) -> pd.DataFrame:
    """1-year daily OHLCV from yfinance with in-memory TTL cache."""
    key = f"__ch_{symbol}__"
    cached = _CACHE.get(key)
    if cached and time.time() - cached["ts"] < _TTL:
        return cached["data"]

    import yfinance as yf
    df = yf.Ticker(symbol + ".NS").history(period="1y", interval="1d", auto_adjust=True)
    if df.empty or len(df) < 50:
        raise ValueError(f"Insufficient history for {symbol} ({len(df)} candles)")
    _CACHE[key] = {"ts": time.time(), "data": df}
    return df


# ──────────────────────────────────────────────────────────────────────────────
# Core detector
# ──────────────────────────────────────────────────────────────────────────────

def _detect(df: pd.DataFrame) -> dict:
    close  = df["Close"].reset_index(drop=True)
    volume = df["Volume"].reset_index(drop=True)
    n      = len(close)

    if n < 50:
        return {"stage": None, "reason": "Insufficient data (< 50 candles)"}

    # Pivot highs (window=10) as right-rim candidates
    pivot_highs = find_pivot_highs(close, window=10)
    if len(pivot_highs) < 2:
        return {"stage": None, "reason": "Not enough pivot highs for cup detection"}

    # Most recent pivots (up to 10) where the handle can still fit (≤35 candles remain)
    candidates = [p for p in pivot_highs if n - 1 - p <= 35 and n - 1 - p >= 0]
    candidates = sorted(candidates, reverse=True)[:10]

    best_result = None
    best_total  = -1.0

    for right_idx in candidates:
        right_val  = float(close.iloc[right_idx])
        handle_len = (n - 1) - right_idx     # candles between right rim and today

        # ── Cup search: 20-180 candles before right rim ────────────────────
        cup_range_lo = 20
        cup_range_hi = min(180, right_idx)

        for cup_span in range(cup_range_lo, cup_range_hi + 1, 5):
            left_boundary = right_idx - cup_span
            if left_boundary < 0:
                break

            # Cup bottom: min in the middle 60% of [left_boundary, right_idx]
            margin     = max(1, cup_span // 5)
            bot_start  = left_boundary + margin
            bot_end    = right_idx - margin
            if bot_end <= bot_start:
                continue

            bot_rel   = int(close.iloc[bot_start:bot_end].values.argmin())
            bot_idx   = bot_start + bot_rel
            bot_val   = float(close.iloc[bot_idx])

            # Left rim: max in [left_boundary, bot_idx - 5]
            lr_end    = max(left_boundary + 1, bot_idx - 5)
            lr_rel    = int(close.iloc[left_boundary:lr_end].values.argmax())
            left_idx  = left_boundary + lr_rel
            left_val  = float(close.iloc[left_idx])

            # Validate cup geometry
            cup_res = validate_cup(close, left_idx, bot_idx, right_idx)
            if not cup_res["valid"]:
                continue

            # Validate handle
            if handle_len >= 3:
                hdl_res = validate_handle(close, right_idx, n - 1)
            else:
                hdl_res = None

            # Volume analysis
            cup_vol  = vol_mean(volume, left_idx, right_idx)
            hdl_vol  = vol_mean(volume, right_idx, n) if handle_len >= 3 else cup_vol
            dry_ratio = hdl_vol / cup_vol if cup_vol > 0 else 1.0

            # Prior uptrend: % change in 60d before left rim
            prior_start = max(0, left_idx - 60)
            prior_trend = pct(float(close.iloc[prior_start]), left_val) if prior_start < left_idx else 0.0

            # Score
            score_dict = score(cup_res, hdl_res, dry_ratio, prior_trend)
            total      = score_dict["total"]

            if total <= best_total:
                continue

            # Determine stage
            if hdl_res and hdl_res.get("valid"):
                stage = "complete"
                stage_desc = ("Cup & Handle complete — near breakout"
                              if hdl_res.get("near_breakout")
                              else "Cup & Handle complete")
            elif handle_len >= 3:
                pull = hdl_res.get("pullback_pct", 0.0) if hdl_res else 0.0
                stage = "handle_forming"
                stage_desc = f"Handle forming ({handle_len}d, {pull:.1f}% pullback)"
            else:
                stage = "cup_complete"
                stage_desc = "Cup complete — handle not yet started"

            # Targets
            h_high = hdl_res.get("high", right_val) if hdl_res else right_val
            h_low  = hdl_res.get("low",  right_val * 0.95) if hdl_res else right_val * 0.95
            cur_px = float(close.iloc[-1])
            targets = calculate_targets(left_val, bot_val, h_high, h_low, cur_px)

            best_total  = total
            best_result = {
                "stage":      stage,
                "stage_desc": stage_desc,
                "score":      score_dict,
                "cup": {
                    "left_rim_idx":  int(left_idx),
                    "left_rim":      round(left_val, 2),
                    "bottom_idx":    int(bot_idx),
                    "bottom":        round(bot_val, 2),
                    "right_rim_idx": int(right_idx),
                    "right_rim":     round(right_val, 2),
                    "depth_pct":     cup_res["depth_pct"],
                    "recovery_pct":  cup_res["recovery_pct"],
                    "roundness":     cup_res["roundness"],
                    "symmetry":      cup_res["symmetry"],
                    "len_days":      cup_res["cup_len"],
                },
                "handle": {
                    "high":        hdl_res.get("high") if hdl_res else None,
                    "low":         hdl_res.get("low")  if hdl_res else None,
                    "pullback_pct":hdl_res.get("pullback_pct") if hdl_res else None,
                    "len_days":    handle_len,
                    "valid":       bool(hdl_res.get("valid")) if hdl_res else False,
                    "near_breakout": bool(hdl_res.get("near_breakout")) if hdl_res else False,
                },
                "volume": {
                    "dry_ratio": round(dry_ratio, 3),
                    "is_dry":    dry_ratio < 0.85,
                },
                "targets":         targets,
                "prior_trend_pct": round(prior_trend, 2),
                "current_price":   round(cur_px, 2),
                "total_candles":   n,
            }

    if best_result and best_total >= MIN_PATTERN_SCORE:
        return best_result

    return _detect_early(close, n)


def _detect_early(close: pd.Series, n: int) -> dict:
    """
    Fallback: detect early cup formation.
    Requires: a prior high, ≥10% drop from it, ≥40% recovery of that drop.
    """
    if n < 40:
        return {"stage": None, "reason": "Insufficient data"}

    # Look for a left high in candles [n-120 .. n-30]
    search_s = max(0, n - 120)
    search_e = max(search_s + 1, n - 30)
    left_zone_e = search_s + max(1, (search_e - search_s) // 3)

    left_val = float(close.iloc[search_s:left_zone_e].max())
    left_idx = search_s + int(close.iloc[search_s:left_zone_e].values.argmax())

    cup_low_val = float(close.iloc[left_idx:].min())
    cur_px      = float(close.iloc[-1])
    drop_pct    = pct(left_val, cup_low_val) * -1

    if drop_pct < 10.0:
        return {"stage": None, "reason": f"No significant drop from recent high ({drop_pct:.1f}%)"}

    rec_of_drop = pct(cup_low_val, cur_px) / drop_pct * 100 if drop_pct > 0 else 0.0

    if rec_of_drop < 40.0:
        return {
            "stage": None,
            "reason": (f"Too early: {drop_pct:.1f}% drop, only "
                       f"{rec_of_drop:.0f}% recovered"),
        }

    return {
        "stage":      "early_cup",
        "stage_desc": f"Early cup: {drop_pct:.1f}% drop, {rec_of_drop:.0f}% recovered",
        "score":      {"total": 15.0, "shape": 10.0, "handle": 0.0,
                       "volume": 5.0,  "trend": 0.0,  "recovery": 0.0},
        "cup": {
            "left_rim_idx":  int(left_idx),
            "left_rim":      round(left_val, 2),
            "bottom_idx":    None,
            "bottom":        round(cup_low_val, 2),
            "right_rim_idx": None,
            "right_rim":     None,
            "depth_pct":     round(drop_pct, 2),
            "recovery_pct":  round(rec_of_drop, 2),
            "roundness":     0.0,
            "symmetry":      0.0,
            "len_days":      n - left_idx,
        },
        "handle":          None,
        "volume":          {"dry_ratio": 1.0, "is_dry": False},
        "targets":         None,
        "prior_trend_pct": 0.0,
        "current_price":   round(cur_px, 2),
        "total_candles":   n,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

_STAGE_ORDER = {"complete": 0, "handle_forming": 1, "cup_complete": 2, "early_cup": 3}


def analyse(symbol: str) -> dict:
    """Analyse a single stock for Cup & Handle.  Returns result dict."""
    try:
        df = _fetch_daily(symbol)
        result = _detect(df)
        result["symbol"] = symbol.upper()
        return result
    except Exception as exc:
        log.warning("[CupHandle] %s: %s", symbol, exc)
        return {"symbol": symbol.upper(), "stage": None, "reason": str(exc)}


def scan(symbols: list[str]) -> list[dict]:
    """
    Scan a list of NSE symbols.
    Returns only detected patterns, sorted by stage then score (desc).
    """
    results = []
    for sym in symbols:
        r = analyse(sym)
        if r.get("stage"):
            results.append(r)

    results.sort(key=lambda x: (
        _STAGE_ORDER.get(x.get("stage"), 9),
        -(x.get("score") or {}).get("total", 0),
    ))
    return results
