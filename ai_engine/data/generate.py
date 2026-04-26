"""
Synthetic OHLCV candle data generator for the EMA + MACD + VWAP scenario simulation.

Price levels mirror the textbook Nifty 50 long-trade example:
  Entry: 19,850  |  Stop: 19,780  |  T1: 19,990  |  T2: 20,110

The 5m DataFrame covers the full session from 9:15 (for accurate VWAP seeding).
df.attrs["chart_start_idx"] marks where the visible chart window begins.
"""
import random
import pandas as pd

# Scenario trade levels (from CLAUDE.md)
ENTRY_PRICE = 19_850.0
STOP_LOSS   = 19_780.0
TARGET_1    = 19_990.0
TARGET_2    = 20_110.0

SCENARIO = {
    "direction": "LONG",
    "entry":     ENTRY_PRICE,
    "stop":      STOP_LOSS,
    "target1":   TARGET_1,
    "target2":   TARGET_2,
}


def _c(ts: str, o: float, h: float, l: float, c: float, v: int | None = None) -> dict:
    return {
        "timestamp": ts,
        "Open":   float(o), "High": float(h),
        "Low":    float(l), "Close": float(c),
        "Volume": v if v is not None else random.randint(50_000, 200_000),
    }


def generate_1h() -> pd.DataFrame:
    """
    9 hourly candles — Monday 9 AM → Tuesday 11 AM, range 19,580–19,920.
    Consistently bullish trend so all 4 bias conditions fire.
    """
    candles = [
        _c("2025-04-21 09:00", 19_580, 19_650, 19_575, 19_625),
        _c("2025-04-21 10:00", 19_625, 19_710, 19_615, 19_692),
        _c("2025-04-21 11:00", 19_692, 19_758, 19_678, 19_745),
        _c("2025-04-21 12:00", 19_745, 19_805, 19_732, 19_785),
        _c("2025-04-21 13:00", 19_785, 19_835, 19_770, 19_818),
        _c("2025-04-21 14:00", 19_818, 19_858, 19_805, 19_843),
        _c("2025-04-21 15:00", 19_843, 19_878, 19_832, 19_865),
        _c("2025-04-22 09:00", 19_865, 19_908, 19_858, 19_892),
        _c("2025-04-22 10:00", 19_892, 19_920, 19_880, 19_912),
    ]
    df = pd.DataFrame(candles).set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    return df


def generate_15m() -> pd.DataFrame:
    """
    8 main candles — Tuesday 9:15–11:00, range 19,780–19,980.

    5 seed candles (8:00–9:00) prime the VWAP and EMAs so the crossover
    detected at candle index 8 (10:15) is above a meaningful VWAP.
    chart_start_idx = 5 → only the 8 main candles appear in the chart.

    Design: bearish open → recovery → EMA crossover at 10:15 above VWAP
            MACD histogram goes negative→positive at same point.
    """
    seed = [
        _c("2025-04-22 08:00", 19_790, 19_808, 19_782, 19_795, 8_000),
        _c("2025-04-22 08:15", 19_795, 19_812, 19_787, 19_800, 8_000),
        _c("2025-04-22 08:30", 19_800, 19_815, 19_792, 19_805, 8_000),
        _c("2025-04-22 08:45", 19_805, 19_818, 19_798, 19_808, 8_000),
        _c("2025-04-22 09:00", 19_808, 19_820, 19_800, 19_810, 8_000),
    ]
    main = [
        _c("2025-04-22 09:15", 19_810, 19_845, 19_780, 19_792, 125_000),  # bearish open
        _c("2025-04-22 09:30", 19_792, 19_822, 19_778, 19_788, 105_000),  # continuation bear
        _c("2025-04-22 09:45", 19_788, 19_835, 19_780, 19_822, 92_000),   # recovery
        _c("2025-04-22 10:00", 19_822, 19_875, 19_815, 19_858, 132_000),  # bullish push
        _c("2025-04-22 10:15", 19_858, 19_915, 19_850, 19_898, 155_000),  # EMA crossover + MACD flip
        _c("2025-04-22 10:30", 19_898, 19_942, 19_888, 19_928, 142_000),  # continuation
        _c("2025-04-22 10:45", 19_928, 19_962, 19_918, 19_950, 122_000),
        _c("2025-04-22 11:00", 19_950, 19_980, 19_940, 19_968, 112_000),
    ]
    df = pd.DataFrame(seed + main).set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    df.attrs["chart_start_idx"] = len(seed)
    return df


def generate_5m() -> pd.DataFrame:
    """
    Full 5m session from 9:15 to 10:25 (15 candles, range 19,780–19,945).

    Starting from 9:15 is essential: VWAP accumulates from the low open
    so that by the time price pulls back to 19,870 the VWAP (≈19,850) is
    below the close — confirming the held-above-VWAP condition.

    chart_start_idx = 7 → chart shows from 09:50 onward (last 8 candles).

    Entry trigger fires at index 13 (10:20):
      - EMA9 ≈ 19,873, close = 19,872 → within 0.15% ✓
      - VWAP ≈ 19,848 → close > VWAP ✓
      - Bullish candle (19,862 → 19,872) ✓
    """
    candles = [
        # Full session for VWAP seed — low prices keep VWAP anchored below pullback
        _c("2025-04-22 09:15", 19_780, 19_838, 19_775, 19_812, 182_000),  # idx 0
        _c("2025-04-22 09:20", 19_812, 19_850, 19_802, 19_838, 122_000),  # idx 1
        _c("2025-04-22 09:25", 19_838, 19_862, 19_828, 19_850, 102_000),  # idx 2
        _c("2025-04-22 09:30", 19_850, 19_878, 19_840, 19_865, 97_000),   # idx 3
        _c("2025-04-22 09:35", 19_865, 19_895, 19_858, 19_880, 92_000),   # idx 4
        _c("2025-04-22 09:40", 19_880, 19_910, 19_872, 19_898, 87_000),   # idx 5
        _c("2025-04-22 09:45", 19_898, 19_928, 19_888, 19_915, 82_000),   # idx 6
        # Chart visible from here (chart_start_idx = 7)
        _c("2025-04-22 09:50", 19_915, 19_942, 19_908, 19_930, 78_000),   # idx 7
        _c("2025-04-22 09:55", 19_930, 19_945, 19_920, 19_940, 72_000),   # idx 8
        _c("2025-04-22 10:00", 19_940, 19_945, 19_922, 19_932, 67_000),   # idx 9
        _c("2025-04-22 10:05", 19_932, 19_938, 19_898, 19_905, 88_000),   # idx 10 pullback start
        _c("2025-04-22 10:10", 19_905, 19_920, 19_888, 19_895, 92_000),   # idx 11
        _c("2025-04-22 10:15", 19_895, 19_902, 19_860, 19_862, 102_000),  # idx 12 deep pullback
        _c("2025-04-22 10:20", 19_862, 19_888, 19_858, 19_872, 112_000),  # idx 13 ← entry candle
        _c("2025-04-22 10:25", 19_872, 19_900, 19_865, 19_890, 97_000),   # idx 14 continuation
    ]
    df = pd.DataFrame(candles).set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    df.attrs["chart_start_idx"] = 7
    return df


def generate_all() -> dict:
    """Return all three synthetic OHLCV DataFrames."""
    return {"1h": generate_1h(), "15m": generate_15m(), "5m": generate_5m()}
