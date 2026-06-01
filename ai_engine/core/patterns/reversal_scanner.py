"""
Price reversal screener.

Pattern: Peak → significant decline → support touch → 2+ month sustained recovery.

Uses yfinance batch download (single API call per scan) so Nifty50 runs in ~10s
and the Nifty500 proxy (~250 stocks) in ~30s.
"""

import logging
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

from core.movers import (
    _NIFTY50,
    _NIFTY_MIDCAP100,
    _NIFTY_SMALLCAP100,
)

_NIFTY500_PROXY = list(dict.fromkeys(_NIFTY50 + _NIFTY_MIDCAP100 + _NIFTY_SMALLCAP100))

UNIVERSES: dict[str, list] = {
    "nifty50":  _NIFTY50,
    "nifty500": _NIFTY500_PROXY,
}


def scan_reversals(
    universe: str = "nifty50",
    min_decline: float = 30.0,
    min_recovery: float = 10.0,
    support_type: str = "single",
    min_days: int = 40,
    max_days: int = 130,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
) -> dict:
    import yfinance as yf

    symbols = UNIVERSES.get(universe, _NIFTY50)
    tickers = [s + ".NS" for s in symbols]

    try:
        raw = yf.download(
            tickers,
            period="9mo",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        log.error(f"[REVERSAL-SCAN] batch download failed: {exc}")
        return {"error": "Failed to fetch market data. Try again in a moment."}

    results = []

    for sym in symbols:
        ticker = sym + ".NS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"][ticker].dropna()
            else:
                close = raw["Close"].dropna()

            min_required = max_days + 25
            if len(close) < min_required:
                continue

            current_price = float(close.iloc[-1])

            if min_price and current_price < min_price:
                continue
            if max_price and current_price > max_price:
                continue

            # ── Find the trough in the age window ──────────────────────────
            # The reversal low must have occurred between min_days and max_days
            # trading sessions ago (counting back from today).
            lookback_end   = len(close) - min_days
            lookback_start = max(0, len(close) - max_days)
            lookback = close.iloc[lookback_start:lookback_end]

            if len(lookback) < 5:
                continue

            trough_pos_in_lookback = int(lookback.values.argmin())
            trough_val  = float(lookback.iloc[trough_pos_in_lookback])
            trough_iloc = lookback_start + trough_pos_in_lookback

            # ── Peak: highest close before the trough ──────────────────────
            pre_trough = close.iloc[:trough_iloc]
            if len(pre_trough) < 5:
                continue
            peak_val = float(pre_trough.max())

            # ── Decline filter ─────────────────────────────────────────────
            decline_pct = (peak_val - trough_val) / peak_val * 100
            if decline_pct < min_decline:
                continue

            # ── Recovery filter ────────────────────────────────────────────
            recovery_pct = (current_price - trough_val) / trough_val * 100
            if recovery_pct < min_recovery:
                continue

            # ── Support must still be holding ──────────────────────────────
            # Price must not have broken back below support after the reversal.
            post_trough = close.iloc[trough_iloc:]
            post_trough_min = float(post_trough.min())
            if post_trough_min < trough_val * 0.97:
                continue

            # ── Trend confirmation: price > 20-day SMA ─────────────────────
            sma20 = float(close.iloc[-20:].mean())
            if current_price < sma20 * 0.97:
                continue

            # ── Double bottom check ────────────────────────────────────────
            if support_type == "double":
                window = post_trough.iloc[:min(35, len(post_trough))]
                bounce_peak = float(window.max())
                if bounce_peak < trough_val * 1.05:
                    continue

                bounce_peak_idx = int(window.values.argmax())
                after_bounce    = post_trough.iloc[bounce_peak_idx:]
                if len(after_bounce) < 5:
                    continue

                second_low = float(after_bounce.min())
                if second_low > trough_val * 1.08:
                    continue

            days_since_trough = len(close) - 1 - trough_iloc

            results.append({
                "symbol":            sym,
                "current_price":     round(current_price, 2),
                "peak":              round(peak_val, 2),
                "support":           round(trough_val, 2),
                "decline_pct":       round(decline_pct, 1),
                "recovery_pct":      round(recovery_pct, 1),
                "days_since_trough": int(days_since_trough),
                "sma20":             round(sma20, 2),
            })

        except Exception:
            continue

    results.sort(key=lambda x: x["recovery_pct"], reverse=True)

    return {
        "universe":      universe,
        "universe_size": len(symbols),
        "matched":       len(results),
        "filters": {
            "min_decline":   min_decline,
            "min_recovery":  min_recovery,
            "support_type":  support_type,
            "min_days":      min_days,
            "max_days":      max_days,
            "min_price":     min_price,
            "max_price":     max_price,
        },
        "results": results,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Single-stock reversal check — same criteria, detailed pass/fail per criterion
# ─────────────────────────────────────────────────────────────────────────────

def check_single_stock(
    symbol:       str,
    min_decline:  float = 30.0,
    min_recovery: float = 10.0,
    support_type: str   = "single",
    min_days:     int   = 40,
    max_days:     int   = 130,
) -> dict:
    import yfinance as yf

    raw = symbol.upper().strip()
    ticker_sym = raw if raw.endswith(".NS") or raw.endswith(".BO") else raw + ".NS"

    tk   = yf.Ticker(ticker_sym)
    hist = tk.history(period="9mo", interval="1d", auto_adjust=True)

    if hist.empty or len(hist) < 60:
        return {"error": f"Insufficient price history for '{raw}'. Verify the NSE symbol and try again."}

    close         = hist["Close"].dropna()
    current_price = float(close.iloc[-1])
    n             = len(close)

    # ── Find best trough in the age window ───────────────────────────────────
    win_end   = max(0, n - min_days)
    win_start = max(0, n - max_days)
    lookback  = close.iloc[win_start:win_end]

    if len(lookback) >= 5:
        tp          = int(lookback.values.argmin())
        trough_val  = float(lookback.iloc[tp])
        trough_iloc = win_start + tp
    else:
        # Age window too narrow — use global trough so other criteria still show
        trough_iloc = int(close.values.argmin())
        trough_val  = float(close.iloc[trough_iloc])

    days_since = n - 1 - trough_iloc

    # Peak: highest close before the trough
    pre       = close.iloc[:trough_iloc]
    peak_val  = float(pre.max()) if len(pre) >= 3 else current_price

    decline_pct  = (peak_val - trough_val) / peak_val * 100  if peak_val  > 0 else 0.0
    recovery_pct = (current_price - trough_val) / trough_val * 100 if trough_val > 0 else 0.0

    # Post-trough price action
    post     = close.iloc[trough_iloc:]
    post_min = float(post.min())

    # 20-day SMA
    sma20 = float(close.iloc[-20:].mean())

    # Double bottom
    double_found = False
    if support_type == "double" and len(post) >= 20:
        win      = post.iloc[:min(35, len(post))]
        b_peak   = float(win.max())
        if b_peak >= trough_val * 1.05:
            b_idx        = int(win.values.argmax())
            after_bounce = post.iloc[b_idx:]
            if len(after_bounce) >= 5:
                second_low   = float(after_bounce.min())
                double_found = second_low <= trough_val * 1.08

    # ── Build criteria checklist ──────────────────────────────────────────────
    age_pass = min_days <= days_since <= max_days

    criteria = [
        {
            "name":     "Decline from Peak",
            "passed":   decline_pct >= min_decline,
            "value":    f"{decline_pct:.1f}%",
            "required": f"≥ {min_decline:.0f}%",
            "detail":   f"Fell from ₹{peak_val:.2f} to ₹{trough_val:.2f}",
        },
        {
            "name":     "Reversal Age",
            "passed":   age_pass,
            "value":    f"{days_since} trading days ago",
            "required": f"{min_days}–{max_days} trading days",
            "detail":   (
                f"Support formed {days_since} days ago — within your filter"
                if age_pass
                else f"Support formed {days_since} days ago — outside your {min_days}–{max_days} day window"
            ),
        },
        {
            "name":     "Recovery from Support",
            "passed":   recovery_pct >= min_recovery,
            "value":    f"+{recovery_pct:.1f}%",
            "required": f"≥ {min_recovery:.0f}%",
            "detail":   f"Bounced from ₹{trough_val:.2f} to current ₹{current_price:.2f}",
        },
        {
            "name":     "Support Still Holding",
            "passed":   post_min >= trough_val * 0.97,
            "value":    "Yes" if post_min >= trough_val * 0.97 else "Broken",
            "required": "Price must not break back below support",
            "detail":   f"Lowest price after reversal: ₹{post_min:.2f}",
        },
        {
            "name":     "Uptrend Confirmed",
            "passed":   current_price >= sma20 * 0.97,
            "value":    f"₹{current_price:.2f} vs SMA20 ₹{sma20:.2f}",
            "required": "Current price ≥ 20-day SMA",
            "detail":   f"Price is {'above' if current_price >= sma20 else 'below'} its 20-day average",
        },
    ]

    if support_type == "double":
        criteria.append({
            "name":     "Double Bottom",
            "passed":   double_found,
            "value":    "Detected" if double_found else "Not detected",
            "required": "Two tests of the same support level",
            "detail":   (
                "Price bounced, retested support, and held"
                if double_found
                else "No confirmed second test of the support level found"
            ),
        })

    passed = all(c["passed"] for c in criteria)

    return {
        "symbol":            raw,
        "passed":            passed,
        "current_price":     round(current_price, 2),
        "peak":              round(peak_val, 2),
        "support":           round(trough_val, 2),
        "decline_pct":       round(decline_pct, 1),
        "recovery_pct":      round(recovery_pct, 1),
        "days_since_trough": int(days_since),
        "sma20":             round(sma20, 2),
        "criteria":          criteria,
    }
