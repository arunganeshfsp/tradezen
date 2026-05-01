"""RSI (Relative Strength Index) — Wilder's EWM method."""
import pandas as pd


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta    = series.diff()
    avg_gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = (-delta).where(delta < 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    # avg_loss == 0: pure up-move → RSI 100; used replace so division stays vectorised
    rs  = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    # fillna(100) handles the pure-up case; clip catches any residual float edge cases
    return rsi.clip(0, 100).fillna(100)
