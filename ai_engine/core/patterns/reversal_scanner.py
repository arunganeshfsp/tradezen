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
    "nifty50":    _NIFTY50,
    "midcap100":  _NIFTY_MIDCAP100,
    "smallcap100": _NIFTY_SMALLCAP100,
    "nifty500":   _NIFTY500_PROXY,
}

_SECTORS: dict[str, list[str]] = {
    "banks":     ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "SBIN", "BANKBARODA",
                  "PNB", "CANARABANK", "FEDERALBNK", "IDFCFIRSTB", "INDUSINDBK",
                  "BANDHANBNK", "AUBANK", "RBLBANK", "YESBANK"],
    "it":        ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
                  "COFORGE", "PERSISTENT", "LTTS", "KPITTECH", "TATAELXSI", "OFSS"],
    "pharma":    ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "BIOCON", "AUROPHARMA",
                  "LUPIN", "ZYDUSLIFE", "ALKEM", "TORNTPHARM", "IPCALAB", "GRANULES",
                  "GLENMARK", "ABBOTINDIA"],
    "metals":    ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "SAIL", "NMDC",
                  "JINDALSTEL", "COALINDIA", "NATIONALUM", "MOIL", "HINDZINC",
                  "APLAPOLLO", "RATNAMANI"],
    "auto":      ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "HEROMOTOCO",
                  "EICHERMOT", "TVSMOTOR", "ASHOKLEY", "BALKRISIND", "MRF",
                  "APOLLOTYRE", "CEATLTD", "BOSCHLTD"],
    "fmcg":      ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "GODREJCP",
                  "MARICO", "COLPAL", "EMAMILTD", "TATACONSUM", "VBL", "RADICO",
                  "UBL", "MCDOWELL-N"],
    "energy":    ["RELIANCE", "ONGC", "BPCL", "IOC", "NTPC", "POWERGRID",
                  "ADANIGREEN", "TATAPOWER", "TORNTPOWER", "CESC", "NHPC",
                  "SJVN", "IGL", "MGL"],
    "realty":    ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "BRIGADE",
                  "PHOENIXLTD", "MAHLIFE", "SOBHA", "SUNTECK", "KOLTEPATIL"],
    "infra":     ["LT", "ULTRACEMCO", "SHREECEM", "AMBUJACEMENT", "ACC",
                  "RAMCOCEM", "JKCEMENT", "RITES", "IRB", "KNR"],
    "chemicals": ["PIDILITIND", "SRF", "AARTI", "DEEPAKNTR", "ATUL", "VINATIORG",
                  "FINEORG", "NAVINFLUOR", "CLEAN", "ROSSARI", "TATACHEM"],
}


def _get_reversal_symbols(universe: str, sector: str, symbols: str) -> list:
    if universe == "watchlist":
        return [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else []
    base = list(UNIVERSES.get(universe, _NIFTY50))
    if sector and sector in _SECTORS:
        sector_set = set(_SECTORS[sector])
        intersection = [s for s in base if s in sector_set]
        return intersection if intersection else list(_SECTORS[sector])
    return base


def _fib_level(fib_pct: float) -> str:
    if fib_pct >= 100:  return "100%+"
    if fib_pct >= 61.8: return "61.8%"
    if fib_pct >= 50:   return "50%"
    if fib_pct >= 38.2: return "38.2%"
    return "<38.2%"


def _vol_signal(vol_at_trough: float, vol_base: float, vol_recovery: float) -> str:
    capitulation = vol_at_trough > vol_base * 1.3
    expanding    = vol_recovery  > vol_base * 0.85
    if capitulation and expanding: return "strong"
    if capitulation or expanding:  return "moderate"
    return "weak"


def scan_reversals(
    universe:     str   = "nifty50",
    min_decline:  float = 20.0,
    min_recovery: float = 10.0,
    support_type: str   = "single",
    min_days:     int   = 15,
    max_days:     int   = 150,
    min_price:    Optional[float] = None,
    max_price:    Optional[float] = None,
    sector:       str   = "",
    symbols:      str   = "",
) -> dict:
    import yfinance as yf

    sym_list = _get_reversal_symbols(universe, sector, symbols)
    if not sym_list:
        return {"error": "Watchlist is empty. Add stocks from any scanner page first."}

    tickers = [s + ".NS" for s in sym_list]

    try:
        raw = yf.download(
            tickers,
            period="1y",
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

    for sym in sym_list:
        ticker = sym + ".NS"
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close  = raw["Close"][ticker].dropna()
                volume = raw["Volume"][ticker].reindex(close.index).fillna(0)
            else:
                close  = raw["Close"].dropna()
                volume = raw["Volume"].reindex(close.index).fillna(0)

            # Need max_days trough window + 90 peak window + 50 SMA buffer
            min_required = max_days + 60
            if len(close) < min_required:
                continue

            current_price = float(close.iloc[-1])

            if min_price and current_price < min_price:
                continue
            if max_price and current_price > max_price:
                continue

            # ── Trough in the age window ──────────────────────────────────────
            lookback_end   = len(close) - min_days
            lookback_start = max(0, len(close) - max_days)
            lookback = close.iloc[lookback_start:lookback_end]
            if len(lookback) < 5:
                continue

            trough_pos_in_lookback = int(lookback.values.argmin())
            trough_val  = float(lookback.iloc[trough_pos_in_lookback])
            trough_iloc = lookback_start + trough_pos_in_lookback

            # ── Peak: highest close in 90-day window before trough ────────────
            # Bounded to 90 days to avoid ancient peaks inflating decline_pct
            peak_start = max(0, trough_iloc - 90)
            pre_window = close.iloc[peak_start:trough_iloc]
            if len(pre_window) < 5:
                continue
            peak_val = float(pre_window.max())

            # ── Derived metrics ────────────────────────────────────────────────
            decline_pct       = (peak_val - trough_val) / peak_val * 100
            recovery_pct      = (current_price - trough_val) / trough_val * 100
            days_since_trough = len(close) - 1 - trough_iloc

            # Fibonacci retracement: % of peak→trough decline recovered
            decline_pts = peak_val - trough_val
            fib_pct_raw = (current_price - trough_val) / decline_pts * 100 if decline_pts > 0 else 0.0
            fib_pct     = round(min(fib_pct_raw, 120.0), 1)

            # SMAs
            sma20 = float(close.iloc[-20:].mean())
            sma50 = float(close.iloc[-50:].mean()) if len(close) >= 50 else sma20
            sma20_above_sma50 = sma20 >= sma50 * 0.99

            # Volume: capitulation at trough + expansion on recovery
            t_s = max(0, trough_iloc - 2)
            t_e = min(len(volume), trough_iloc + 3)
            vol_at_trough = float(volume.iloc[t_s:t_e].mean()) or 1.0
            vol_base      = float(volume.iloc[max(0, trough_iloc - 30):trough_iloc].mean()) or 1.0
            vol_recovery  = float(volume.iloc[trough_iloc:min(trough_iloc + 20, len(volume))].mean()) or 1.0
            vsig = _vol_signal(vol_at_trough, vol_base, vol_recovery)

            # Post-trough action
            post_trough = close.iloc[trough_iloc:]
            post_min    = float(post_trough.min())

            # Double bottom — tightened to 3% tolerance (was 8%)
            double_pass = False
            if support_type == "double":
                win    = post_trough.iloc[:min(35, len(post_trough))]
                b_peak = float(win.max())
                if b_peak >= trough_val * 1.05:
                    b_idx        = int(win.values.argmax())
                    after_bounce = post_trough.iloc[b_idx:]
                    if len(after_bounce) >= 5:
                        second_low  = float(after_bounce.min())
                        double_pass = second_low <= trough_val * 1.03

            # ── Evaluate all criteria ─────────────────────────────────────────
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
                failures.append({
                    "name":     "Reversal Age",
                    "value":    f"{days_since_trough} days",
                    "required": f"{min_days}–{max_days} days",
                    "gap":      "too old" if days_since_trough > max_days else "too recent",
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
                    "required": "Must hold within 3%",
                    "gap":      f"broke by {((trough_val - post_min) / trough_val * 100):.1f}%",
                })

            # Structural trend: SMA20 > SMA50 only required for well-established
            # reversals (≥70 days). Fresh reversals just need price near SMA20.
            sma20_above_sma50 = sma20 >= sma50 * 0.97
            if days_since_trough >= 70:
                trend_ok = current_price >= sma20 * 0.97 and sma20_above_sma50
            else:
                trend_ok = current_price >= sma20 * 0.97

            if not trend_ok:
                if days_since_trough >= 70 and not sma20_above_sma50:
                    failures.append({
                        "name":     "Uptrend (SMA20 > SMA50)",
                        "value":    f"SMA20 ₹{sma20:.0f} vs SMA50 ₹{sma50:.0f}",
                        "required": "SMA20 must be above SMA50",
                        "gap":      f"{((sma50 - sma20) / sma50 * 100):.1f}% below SMA50",
                    })
                else:
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
                    "required": "Two tests of support within 3%",
                    "gap":      "no confirmed second test",
                })

            # Volume is informational (shown as badge on card) but not a hard gate —
            # yfinance volume data is inconsistent enough that failing valid patterns.
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
                "sma50":             round(sma50, 2),
                "sma20_above_sma50": sma20_above_sma50,
                "fib_pct":           fib_pct,
                "fib_level":         _fib_level(fib_pct),
                "vol_signal":        vsig,
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
        "universe_size": len(sym_list),
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
    hist = tk.history(period="1y", interval="1d", auto_adjust=True)

    if hist.empty or len(hist) < 60:
        return {"error": f"Insufficient price history for '{raw}'. Verify the NSE symbol and try again."}

    close  = hist["Close"].dropna()
    volume = hist["Volume"].reindex(close.index).fillna(0)

    current_price = float(close.iloc[-1])
    n             = len(close)

    # ── Trough in the age window ──────────────────────────────────────────────
    win_end   = max(0, n - min_days)
    win_start = max(0, n - max_days)
    lookback  = close.iloc[win_start:win_end]

    if len(lookback) >= 5:
        tp          = int(lookback.values.argmin())
        trough_val  = float(lookback.iloc[tp])
        trough_iloc = win_start + tp
    else:
        trough_iloc = int(close.values.argmin())
        trough_val  = float(close.iloc[trough_iloc])

    days_since = n - 1 - trough_iloc

    # ── Peak: highest close in 90-day window before trough ────────────────────
    peak_start = max(0, trough_iloc - 90)
    pre_window = close.iloc[peak_start:trough_iloc]
    peak_val   = float(pre_window.max()) if len(pre_window) >= 3 else current_price

    decline_pct  = (peak_val - trough_val) / peak_val * 100  if peak_val  > 0 else 0.0
    recovery_pct = (current_price - trough_val) / trough_val * 100 if trough_val > 0 else 0.0

    # Fibonacci
    decline_pts = peak_val - trough_val
    fib_pct     = round(min((current_price - trough_val) / decline_pts * 100 if decline_pts > 0 else 0.0, 120.0), 1)

    # SMAs
    sma20 = float(close.iloc[-20:].mean())
    sma50 = float(close.iloc[-50:].mean()) if n >= 50 else sma20
    sma20_above_sma50 = sma20 >= sma50 * 0.97

    # Volume
    t_s = max(0, trough_iloc - 2)
    t_e = min(len(volume), trough_iloc + 3)
    vol_at_trough = float(volume.iloc[t_s:t_e].mean()) or 1.0
    vol_base      = float(volume.iloc[max(0, trough_iloc - 30):trough_iloc].mean()) or 1.0
    vol_recovery  = float(volume.iloc[trough_iloc:min(trough_iloc + 20, len(volume))].mean()) or 1.0
    vsig = _vol_signal(vol_at_trough, vol_base, vol_recovery)

    # Post-trough
    post     = close.iloc[trough_iloc:]
    post_min = float(post.min())

    # Double bottom — tightened to 3%
    double_found = False
    if support_type == "double" and len(post) >= 20:
        win    = post.iloc[:min(35, len(post))]
        b_peak = float(win.max())
        if b_peak >= trough_val * 1.05:
            b_idx        = int(win.values.argmax())
            after_bounce = post.iloc[b_idx:]
            if len(after_bounce) >= 5:
                second_low   = float(after_bounce.min())
                double_found = second_low <= trough_val * 1.03

    # ── Criteria checklist ────────────────────────────────────────────────────
    age_pass = min_days <= days_since <= max_days

    if days_since >= 70:
        trend_pass = current_price >= sma20 * 0.97 and sma20_above_sma50
    else:
        trend_pass = current_price >= sma20 * 0.97

    criteria = [
        {
            "name":     "Decline from Peak",
            "passed":   decline_pct >= min_decline,
            "value":    f"{decline_pct:.1f}%",
            "required": f"≥ {min_decline:.0f}%",
            "detail":   f"Fell from ₹{peak_val:.2f} to ₹{trough_val:.2f} (90-day peak window)",
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
            "detail":   f"Bounced from ₹{trough_val:.2f} to ₹{current_price:.2f} · Fibonacci {fib_pct:.1f}% of decline recovered",
        },
        {
            "name":     "Support Still Holding",
            "passed":   post_min >= trough_val * 0.97,
            "value":    "Yes" if post_min >= trough_val * 0.97 else "Broken",
            "required": "Price must not break more than 3% below support",
            "detail":   f"Lowest close after reversal: ₹{post_min:.2f}",
        },
        {
            "name":     "Uptrend Confirmed" if days_since < 70 else "Structural Uptrend (SMA20 > SMA50)",
            "passed":   trend_pass,
            "value":    (f"₹{current_price:.2f} vs SMA20 ₹{sma20:.2f}"
                         if days_since < 70
                         else f"SMA20 ₹{sma20:.2f} vs SMA50 ₹{sma50:.2f}"),
            "required": ("Current price ≥ SMA20"
                         if days_since < 70
                         else "SMA20 above SMA50 and price above SMA20"),
            "detail":   (f"Price is {'above' if current_price >= sma20 else 'below'} its 20-day average"
                         if days_since < 70
                         else f"SMA20 is {'above' if sma20_above_sma50 else 'below'} SMA50 — "
                              f"{'structural uptrend confirmed' if sma20_above_sma50 else 'short-term MA still below long-term MA'}"),
        },
        {
            "name":     "Volume Signal (informational)",
            "passed":   True,
            "value":    vsig.capitalize(),
            "required": "Shown for context — not a hard gate",
            "detail":   (
                "Volume spike at trough and expanding on recovery — strong reversal signal." if vsig == "strong"
                else "Partial volume confirmation — either capitulation or recovery expansion, not both." if vsig == "moderate"
                else "No notable volume at the trough or on the recovery — pattern less reliable."
            ),
        },
    ]

    if support_type == "double":
        criteria.append({
            "name":     "Double Bottom",
            "passed":   double_found,
            "value":    "Detected" if double_found else "Not detected",
            "required": "Two tests of the same level within 3%",
            "detail":   (
                "Price bounced, retested support within 3%, and held"
                if double_found
                else "No confirmed second test within 3% of the support level found"
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
        "sma50":             round(sma50, 2),
        "sma20_above_sma50": sma20_above_sma50,
        "fib_pct":           fib_pct,
        "fib_level":         _fib_level(fib_pct),
        "vol_signal":        vsig,
        "criteria":          criteria,
    }
