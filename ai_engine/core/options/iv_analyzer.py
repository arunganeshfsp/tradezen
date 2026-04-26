"""
Pre-market context builder (Module 3).
Fetches India VIX, previous day OHLC, weekly range, and derives a bias label.
Uses yfinance — no SmartAPI auth needed.
"""

import logging
import datetime as _dt

log = logging.getLogger(__name__)

# Symbols that map to NSE index tickers in yfinance
_YF_INDEX_MAP = {
    "NIFTY":      "^NSEI",
    "BANKNIFTY":  "^NSEBANK",
    "NIFTYBANK":  "^NSEBANK",
    "FINNIFTY":   "^NSEI",      # approximation — no direct yfinance ticker
    "MIDCPNIFTY": "^NSEI",
}

VIX_LEVELS = [
    (14,  "Low",     "green"),
    (20,  "Normal",  "yellow"),
    (30,  "High",    "orange"),
    (999, "Extreme", "red"),
]


def _yf_ticker(symbol: str) -> str:
    s = symbol.strip().upper()
    return _YF_INDEX_MAP.get(s, f"{s}.NS")


def get_context(symbol: str) -> dict:
    """
    Return pre-market context for the given underlying symbol.
    {vix, vix_label, vix_color, prev_close, pdh, pdl,
     weekly_high, weekly_low, bias, gap_estimate, spot}
    """
    import yfinance as yf
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

    # ── India VIX ─────────────────────────────────────────────────────────────
    vix = None
    vix_label = "Unknown"
    vix_color = "grey"
    try:
        vix_hist = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d")
        if not vix_hist.empty:
            vix = round(float(vix_hist.iloc[-1]["Close"]), 2)
            for thresh, label, color in VIX_LEVELS:
                if vix < thresh:
                    vix_label, vix_color = label, color
                    break
    except Exception as e:
        log.warning(f"VIX fetch error: {e}")

    # ── Underlying OHLC ───────────────────────────────────────────────────────
    ticker_sym = _yf_ticker(symbol)
    pdh = pdl = prev_close = spot = weekly_high = weekly_low = None
    gap_estimate = None
    bias = "NEUTRAL"

    try:
        hist = yf.Ticker(ticker_sym).history(period="10d", interval="1d")
        if not hist.empty:
            today     = _dt.datetime.now(IST).date()
            past      = hist[hist.index.date < today] if hasattr(hist.index, "date") else hist[hist.index.normalize().date < today]
            # simpler approach
            hist.index = hist.index.normalize()
            past = hist[hist.index.date < today]

            if len(past) >= 1:
                prev      = past.iloc[-1]
                pdh       = round(float(prev["High"]),  2)
                pdl       = round(float(prev["Low"]),   2)
                prev_close= round(float(prev["Close"]), 2)

            if len(past) >= 5:
                week = past.iloc[-5:]
                weekly_high = round(float(week["High"].max()),  2)
                weekly_low  = round(float(week["Low"].min()),   2)

            # Current spot (latest available)
            spot = round(float(hist.iloc[-1]["Close"]), 2)

            # Gap estimate: how much above/below prev_close today opened
            if prev_close and spot:
                gap_estimate = round(spot - prev_close, 2)

            # Simple bias
            if prev_close and spot:
                if spot > prev_close * 1.005:
                    bias = "BULLISH"
                elif spot < prev_close * 0.995:
                    bias = "BEARISH"
                else:
                    bias = "NEUTRAL"
    except Exception as e:
        log.warning(f"Underlying OHLC fetch error ({ticker_sym}): {e}")

    return {
        "symbol":       symbol.upper(),
        "vix":          vix,
        "vix_label":    vix_label,
        "vix_color":    vix_color,
        "prev_close":   prev_close,
        "pdh":          pdh,
        "pdl":          pdl,
        "weekly_high":  weekly_high,
        "weekly_low":   weekly_low,
        "spot":         spot,
        "bias":         bias,
        "gap_estimate": gap_estimate,
    }
