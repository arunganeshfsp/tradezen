"""
Market Profile (TPO) engine.

Consumes a 1-min OHLCV DataFrame for a single trading session and produces:
  - TPO profile histogram (price → list of period letters)
  - Volume profile (price → total volume)
  - POC, Value Area High/Low, Initial Balance High/Low
  - Single prints, Poor High/Low detection
  - Naked POC detection (when prior-session profiles are supplied)

Reference: J. Peter Steidlmayer — Market Profile theory
NSE session: 09:15–15:30 IST, 30-minute brackets A through M
"""

import math
import logging
from collections import defaultdict
from datetime import datetime, time

import pandas as pd

from core.indicators.constants import TPO_PERIODS, VALUE_AREA_PCT

log = logging.getLogger(__name__)


def _round_to_tick(price: float, tick_size: float) -> float:
    """Round price to nearest tick bucket (standard TPO convention)."""
    return round(round(price / tick_size) * tick_size, 10)


def _get_tpo_letter(dt_str: str) -> str | None:
    """
    Return the TPO period letter for a given datetime string "YYYY-MM-DD HH:MM".
    Returns None if outside the NSE session.
    """
    try:
        t = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").time()
    except ValueError:
        return None

    for letter, (start_s, end_s) in TPO_PERIODS.items():
        sh, sm = int(start_s[:2]), int(start_s[3:])
        eh, em = int(end_s[:2]), int(end_s[3:])
        start_t = time(sh, sm)
        end_t   = time(eh, em)
        if start_t <= t < end_t:
            return letter

    return None


def build_profile(
    df: pd.DataFrame,
    tick_size: float = 5.0,
    symbol: str = "NIFTY",
    date: str = "",
    prior_pocs: list[float] | None = None,
) -> dict:
    """
    Build a full Market Profile from a 1-min candle DataFrame.

    Parameters
    ----------
    df         : DataFrame with columns DateTime, Open, High, Low, Close, Volume
    tick_size  : price bucket size (5 for NIFTY, 1 for stocks)
    symbol     : symbol name for the output dict
    date       : session date string "YYYY-MM-DD"
    prior_pocs : list of POC prices from prior sessions — used to detect naked POCs

    Returns
    -------
    Full profile dict (structure documented in the module header)
    """
    if df.empty:
        log.warning("build_profile: empty DataFrame")
        return _empty_profile(symbol, date)

    # ── Build TPO histogram ────────────────────────────────────────────────────
    tpo_profile: dict[float, list[str]] = defaultdict(list)   # price → [letters]
    vol_profile: dict[float, int]       = defaultdict(int)     # price → volume

    # Guard: each (price, period) pair is counted at most ONCE.
    # Multiple 1-min candles within the same period can span the same bucket,
    # but the TPO letter must appear only once per period per price level.
    seen_tpo: set[tuple[float, str]] = set()

    for _, row in df.iterrows():
        letter = _get_tpo_letter(str(row["DateTime"]))
        if letter is None:
            continue

        low_bucket  = _round_to_tick(float(row["Low"]),  tick_size)
        high_bucket = _round_to_tick(float(row["High"]), tick_size)
        candle_vol  = int(row.get("Volume", 0))

        price = low_bucket
        n_buckets = 0
        while price <= high_bucket + tick_size * 0.001:
            key = (price, letter)
            if key not in seen_tpo:
                tpo_profile[price].append(letter)
                seen_tpo.add(key)
            n_buckets += 1
            price = round(price + tick_size, 10)

        # Volume distributed across all touched buckets (volume is NOT deduplicated)
        if n_buckets > 0:
            vol_per_bucket = candle_vol // n_buckets
            price = low_bucket
            while price <= high_bucket + tick_size * 0.001:
                vol_profile[price] += vol_per_bucket
                price = round(price + tick_size, 10)

    if not tpo_profile:
        return _empty_profile(symbol, date)

    sorted_prices = sorted(tpo_profile.keys())

    # ── POC — price with highest TPO count ────────────────────────────────────
    poc = max(tpo_profile, key=lambda p: len(tpo_profile[p]))
    total_tpos = sum(len(v) for v in tpo_profile.values())

    # ── Value Area (70% of TPOs expanding from POC) ───────────────────────────
    va_target = math.ceil(total_tpos * VALUE_AREA_PCT)
    vah, val  = _calc_value_area(tpo_profile, sorted_prices, poc, va_target)

    # ── Initial Balance — A + B periods (first 60 minutes) ───────────────────
    ib_high, ib_low = _calc_ib(df)

    # ── Single prints — price levels touched by exactly one TPO letter ────────
    single_prints = [p for p, letters in tpo_profile.items() if len(set(letters)) == 1]

    # ── Poor High / Poor Low detection ────────────────────────────────────────
    # Poor extreme: ≥3 TPOs at the session high/low (unfinished auction — market
    # didn't rotate away cleanly, likely to revisit the extreme)
    session_high = sorted_prices[-1]
    session_low  = sorted_prices[0]
    poor_high = len(tpo_profile[session_high]) >= 3   # already deduplicated
    poor_low  = len(tpo_profile[session_low])  >= 3

    # ── Naked POC — prior-session POCs not yet revisited ──────────────────────
    naked_pocs = []
    if prior_pocs:
        for pp in prior_pocs:
            pp_bucket = _round_to_tick(pp, tick_size)
            if pp_bucket not in tpo_profile:
                naked_pocs.append(round(pp, 2))

    # ── CPR type for the profile ──────────────────────────────────────────────
    va_width = round(vah - val, 2)

    profile = {
        "symbol":         symbol,
        "date":           date,
        "tick_size":      tick_size,
        "tpo_profile":    {round(k, 2): v for k, v in tpo_profile.items()},
        "volume_profile": {round(k, 2): v for k, v in vol_profile.items()},
        "poc":            round(poc, 2),
        "vah":            round(vah, 2),
        "val":            round(val, 2),
        "va_width":       va_width,
        "ib_high":        round(ib_high, 2) if ib_high else None,
        "ib_low":         round(ib_low, 2)  if ib_low  else None,
        "session_high":   round(session_high, 2),
        "session_low":    round(session_low,  2),
        "single_prints":  [round(p, 2) for p in sorted(single_prints)],
        "poor_high":      poor_high,
        "poor_low":       poor_low,
        "naked_pocs":     naked_pocs,
        "tpo_count":      total_tpos,
        "tpo_periods":    _period_summary(tpo_profile),
    }

    log.info(
        f"📊 Profile built: {symbol} {date} | "
        f"POC={profile['poc']} VAH={profile['vah']} VAL={profile['val']} "
        f"IB={profile['ib_low']}–{profile['ib_high']} "
        f"TPOs={total_tpos} Singles={len(single_prints)}"
    )
    return profile


def _calc_value_area(
    tpo_profile: dict,
    sorted_prices: list,
    poc: float,
    target: int,
) -> tuple[float, float]:
    """
    Expand from POC using CME/Steidlmayer standard: compare the next 2 rows
    above vs next 2 rows below each step, add the side with more TPOs.
    Tie goes to upside.
    """
    poc_idx = sorted_prices.index(poc)
    hi_idx  = poc_idx
    lo_idx  = poc_idx
    count   = len(tpo_profile[poc])

    def tpos_at(idx):
        if idx < 0 or idx >= len(sorted_prices):
            return 0
        return len(tpo_profile[sorted_prices[idx]])

    while count < target:
        can_go_up   = hi_idx + 1 < len(sorted_prices)
        can_go_down = lo_idx - 1 >= 0

        if not can_go_up and not can_go_down:
            break

        # Sum the next 2 rows on each side (standard 2-row comparison)
        hi_2 = tpos_at(hi_idx + 1) + tpos_at(hi_idx + 2)
        lo_2 = tpos_at(lo_idx - 1) + tpos_at(lo_idx - 2)

        if not can_go_down or (can_go_up and hi_2 >= lo_2):
            hi_idx += 1
            count  += tpos_at(hi_idx)
        else:
            lo_idx -= 1
            count  += tpos_at(lo_idx)

    return sorted_prices[hi_idx], sorted_prices[lo_idx]


def _calc_ib(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """
    Initial Balance = high/low of the A+B periods (09:15–10:15 IST).
    """
    ib_df = df[df["DateTime"].apply(
        lambda dt: _get_tpo_letter(str(dt)) in ("A", "B")
    )]
    if ib_df.empty:
        return None, None
    return float(ib_df["High"].max()), float(ib_df["Low"].min())


def _period_summary(tpo_profile: dict) -> dict:
    """Return {letter: count} — how many price levels each period covers."""
    counts: dict[str, int] = defaultdict(int)
    for letters in tpo_profile.values():
        for l in set(letters):   # count unique letter per price level
            counts[l] += 1
    return dict(sorted(counts.items()))


def _empty_profile(symbol, date):
    return {
        "symbol": symbol, "date": date, "tick_size": 5,
        "tpo_profile": {}, "volume_profile": {},
        "poc": None, "vah": None, "val": None, "va_width": None,
        "ib_high": None, "ib_low": None,
        "session_high": None, "session_low": None,
        "single_prints": [], "poor_high": False, "poor_low": False,
        "naked_pocs": [], "tpo_count": 0, "tpo_periods": {},
    }
