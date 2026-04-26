"""15m setup detection — EMA 9/21 crossover + VWAP confirmation + MACD zero cross."""
import pandas as pd
from core.indicators.ema import calculate_ema
from core.indicators.macd import calculate_macd
from core.indicators.candle_vwap import calculate_vwap


def check_15m_setup(df: pd.DataFrame) -> dict:
    """
    Detect a valid 15m long setup. Scans the last 3 candles for each condition.

    Conditions:
      1. EMA9 crossed above EMA21 within the last 3 candles
      2. Crossover candle closed above VWAP
      3. MACD histogram crossed above zero line within last 3 candles
    """
    ema9  = calculate_ema(df["Close"], 9)
    ema21 = calculate_ema(df["Close"], 21)
    macd  = calculate_macd(df["Close"])
    vwap  = calculate_vwap(df)

    n = len(df)

    # Scan last 3 candles for EMA 9 cross above EMA 21
    crossover_idx: int | None = None
    for i in range(n - 1, max(n - 4, 0), -1):
        if i > 0:
            prev_diff = float(ema9.iloc[i-1]) - float(ema21.iloc[i-1])
            curr_diff = float(ema9.iloc[i])   - float(ema21.iloc[i])
            if prev_diff < 0 and curr_diff > 0:
                crossover_idx = i
                break

    ema_crossover_found  = crossover_idx is not None
    crossover_above_vwap = False
    if ema_crossover_found:
        crossover_above_vwap = (
            float(df["Close"].iloc[crossover_idx]) > float(vwap.iloc[crossover_idx])
        )

    # Scan last 3 candles for MACD histogram crossing zero (negative → positive)
    macd_zero_cross = False
    for i in range(n - 1, max(n - 4, 0), -1):
        if i > 0:
            if float(macd["histogram"].iloc[i-1]) < 0 and \
               float(macd["histogram"].iloc[i])   > 0:
                macd_zero_cross = True
                break

    return {
        "setup_valid":          ema_crossover_found and crossover_above_vwap and macd_zero_cross,
        "ema_crossover_found":  ema_crossover_found,
        "crossover_above_vwap": crossover_above_vwap,
        "macd_zero_cross":      macd_zero_cross,
        "crossover_candle_idx": crossover_idx,
    }
