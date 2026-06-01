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

    results     = []
    near_misses = []

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

            # ── Trough in the age window (data quality guard — not a criterion) ──
            lookback_end   = len(close) - min_days
            lookback_start = max(0, len(close) - max_days)
            lookback = close.iloc[lookback_start:lookback_end]
            if len(lookback) < 5:
                continue

            trough_pos_in_lookback = int(lookback.values.argmin())
            trough_val  = float(lookback.iloc[trough_pos_in_lookback])
            trough_iloc = lookback_start + trough_pos_in_lookback

            pre_trough = close.iloc[:trough_iloc]
            if len(pre_trough) < 5:
                continue
            peak_val = float(pre_trough.max())

            # ── Derived metrics ────────────────────────────────────────────────
            decline_pct       = (peak_val - trough_val) / peak_val * 100
            recovery_pct      = (current_price - trough_val) / trough_val * 100
            days_since_trough = len(close) - 1 - trough_iloc
            sma20             = float(close.iloc[-20:].mean())
            post_trough       = close.iloc[trough_iloc:]
            post_min          = float(post_trough.min())

            double_pass = False
            if support_type == "double":
                win = post_trough.iloc[:min(35, len(post_trough))]
                b_peak = float(win.max())
                if b_peak >= trough_val * 1.05:
                    b_idx = int(win.values.argmax())
                    after_bounce = post_trough.iloc[b_idx:]
                    if len(after_bounce) >= 5:
                        second_low = float(after_bounce.min())
                        double_pass = second_low <= trough_val * 1.08

            # ── Evaluate all criteria, collect failures ────────────────────────
            failures = []

            if decline_pct < min_decline:
                failures.append({
                    "name":     "Decline from Peak",
                    "value":    f"{decline_pct:.1f}%",
                    "required": f"≥ {min_decline:.0f}%",
                    "gap":      f"{min_decline - decline_pct:.1f}% short",
                })

            age_ok = min_days <= days_since_trough <= max_days
            if not age_ok:
                direction = "too old" if days_since_trough > max_days else "too recent"
                failures.append({
                    "name":     "Reversal Age",
                    "value":    f"{days_since_trough} days",
                    "required": f"{min_days}–{max_days} days",
                    "gap":      direction,
                })

            if recovery_pct < min_recovery:
                failures.append({
                    "name":     "Recovery",
                    "value":    f"+{recovery_pct:.1f}%",
                    "required": f"≥ {min_recovery:.0f}%",
                    "gap":      f"{min_recovery - recovery_pct:.1f}% short",
                })

            if post_min < trough_val * 0.97:
                failures.append({
                    "name":     "Support Holding",
                    "value":    "Broken",
                    "required": "Must hold",
                    "gap":      f"broke by {((trough_val - post_min) / trough_val * 100):.1f}%",
                })

            if current_price < sma20 * 0.97:
                failures.append({
                    "name":     "Uptrend (SMA20)",
                    "value":    f"₹{current_price:.0f}",
                    "required": f"≥ SMA20 ₹{sma20:.0f}",
                    "gap":      f"{((sma20 - current_price) / sma20 * 100):.1f}% below SMA20",
                })

            if support_type == "double" and not double_pass:
                failures.append({
                    "name":     "Double Bottom",
                    "value":    "Not found",
                    "required": "Two tests of support",
                    "gap":      "no confirmed second test",
                })

            # ── Categorise ─────────────────────────────────────────────────────
            stock_data = {
                "symbol":            sym,
                "current_price":     round(current_price, 2),
                "peak":              round(peak_val, 2),
                "support":           round(trough_val, 2),
                "decline_pct":       round(decline_pct, 1),
                "recovery_pct":      round(recovery_pct, 1),
                "days_since_trough": int(days_since_trough),
                "sma20":             round(sma20, 2),
            }

            if len(failures) == 0:
                results.append(stock_data)
            elif len(failures) == 1:
                near_misses.append({**stock_data, "failed_criterion": failures[0]})

        except Exception:
            continue

    results.sort(    key=lambda x: x["recovery_pct"], reverse=True)
    near_misses.sort(key=lambda x: x["recovery_pct"], reverse=True)

    return {
        "universe":      universe,
        "universe_size": len(symbols),
        "matched":       len(results),
        "near_misses":   near_misses,
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
