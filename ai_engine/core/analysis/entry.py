"""5m entry trigger — pullback to EMA9 + VWAP hold + MACD histogram + bullish candle."""
import pandas as pd
from core.indicators.ema import calculate_ema
from core.indicators.macd import calculate_macd
from core.indicators.candle_vwap import calculate_vwap

PULLBACK_THRESHOLD = 0.0015  # 0.15% distance from EMA9


def check_5m_entry(df: pd.DataFrame) -> dict:
    """
    Scan the last 6 candles for a valid 5m long entry trigger.

    Entry requires (all three must fire):
      - Price pulled back to within 0.15% of EMA9
      - Close above VWAP (pullback held above session fair value)
      - Bullish candle (close > open)

    MACD histogram turning positive is an additional confirmation signal
    (reported separately — not required for the trigger itself).

    Pass a full session DataFrame (from 9:15) for an accurate VWAP.
    """
    ema9 = calculate_ema(df["Close"], 9)
    macd = calculate_macd(df["Close"])
    vwap = calculate_vwap(df)

    n = len(df)
    entry_candle_idx: int | None = None

    for i in range(n - 1, max(n - 7, -1), -1):
        close = float(df["Close"].iloc[i])
        open_ = float(df["Open"].iloc[i])
        e9    = float(ema9.iloc[i])
        vw    = float(vwap.iloc[i])

        near_ema9  = (abs(close - e9) / e9 <= PULLBACK_THRESHOLD) if e9 > 0 else False
        above_vwap = (close > vw) if not pd.isna(vw) else False
        bullish    = close > open_

        if near_ema9 and above_vwap and bullish:
            entry_candle_idx = i
            break

    # Evaluate all 4 conditions for the found entry candle (or last candle for display)
    idx   = entry_candle_idx if entry_candle_idx is not None else n - 1
    close = float(df["Close"].iloc[idx])
    open_ = float(df["Open"].iloc[idx])
    e9    = float(ema9.iloc[idx])
    vw    = float(vwap.iloc[idx])

    pullback_to_ema9 = (abs(close - e9) / e9 <= PULLBACK_THRESHOLD) if e9 > 0 else False
    held_above_vwap  = (close > vw) if not pd.isna(vw) else False
    bullish_candle   = close > open_
    macd_hist_rising = False
    if idx > 0:
        macd_hist_rising = (
            float(macd["histogram"].iloc[idx - 1]) < 0 and
            float(macd["histogram"].iloc[idx])     > 0
        )

    triggered = entry_candle_idx is not None

    return {
        "entry_triggered":       triggered,
        "entry_price":           round(close, 2) if triggered else None,
        "pullback_to_ema9":      pullback_to_ema9,
        "held_above_vwap":       held_above_vwap,
        "macd_histogram_rising": macd_hist_rising,
        "bullish_candle":        bullish_candle,
        "entry_candle_idx":      entry_candle_idx,
        "ema9_at_entry":         round(e9, 2),
        "vwap_at_entry":         round(vw, 2) if not pd.isna(vw) else None,
    }
