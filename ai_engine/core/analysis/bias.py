"""1H bias check — EMA 9/21 stack + MACD histogram + VWAP."""
import pandas as pd
from core.indicators.ema import calculate_ema
from core.indicators.macd import calculate_macd
from core.indicators.candle_vwap import calculate_vwap


def check_1h_bias(df: pd.DataFrame) -> dict:
    """
    Check all 1H bullish bias conditions on an OHLCV DataFrame.
    Returns a result dict — all_conditions_met = True only when all 4 fire.

    Conditions:
      1. EMA9 > EMA21 (bullish stack)
      2. Both EMAs have positive slope over last 3 candles
      3. MACD histogram is positive (above zero)
      4. Close > VWAP (price above session fair value)
    """
    ema9  = calculate_ema(df["Close"], 9)
    ema21 = calculate_ema(df["Close"], 21)
    macd  = calculate_macd(df["Close"])
    vwap  = calculate_vwap(df)

    last_close = float(df["Close"].iloc[-1])
    last_ema9  = float(ema9.iloc[-1])
    last_ema21 = float(ema21.iloc[-1])
    last_vwap  = float(vwap.iloc[-1])
    last_hist  = float(macd["histogram"].iloc[-1])

    ema_stacked  = last_ema9 > last_ema21
    ema_sloping  = (
        ema9.iloc[-3:].is_monotonic_increasing and
        ema21.iloc[-3:].is_monotonic_increasing
    ) if len(df) >= 3 else False
    macd_positive = last_hist > 0
    above_vwap    = last_close > last_vwap

    all_met = ema_stacked and ema_sloping and macd_positive and above_vwap
    if all_met:
        bias = "BULLISH"
    elif not ema_stacked and not above_vwap:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "bias":               bias,
        "ema_stacked":        ema_stacked,
        "ema_sloping":        ema_sloping,
        "macd_positive":      macd_positive,
        "above_vwap":         above_vwap,
        "all_conditions_met": all_met,
        "ema9":               round(last_ema9, 2),
        "ema21":              round(last_ema21, 2),
        "vwap":               round(last_vwap, 2),
        "close":              round(last_close, 2),
        "macd_hist":          round(last_hist, 4),
    }
