"""
Chart generator — saves dark-theme candlestick PNG charts for each timeframe.
Requires: pip install matplotlib
"""
from pathlib import Path
import pandas as pd

try:
    import matplotlib
    matplotlib.use("Agg")   # non-interactive backend — safe in CLI and servers
    import matplotlib.pyplot as plt
    _MPL_OK = True
except ImportError:
    _MPL_OK = False

from core.indicators.ema import calculate_ema
from core.indicators.candle_vwap import calculate_vwap

_CHART_DIR = Path(__file__).resolve().parent


def _draw_candles(ax, df: pd.DataFrame) -> None:
    """Draw OHLC candlestick bars on ax."""
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        color = "#26a69a" if c >= o else "#ef5350"
        # Body (rectangle from open to close)
        body_bot = min(o, c)
        body_h   = max(abs(c - o), 0.5)   # min height so doji candles are visible
        ax.bar(i, body_h, bottom=body_bot, color=color, width=0.6, zorder=2)
        # High-low wick
        ax.plot([i, i], [l, h], color=color, linewidth=0.8, zorder=1)


def _x_labels(ax, df: pd.DataFrame) -> None:
    """Set x-axis tick labels to HH:MM from the DataFrame index."""
    n      = len(df)
    ticks  = list(range(0, n, max(1, n // 6)))
    labels = [str(df.index[i])[-8:-3] for i in ticks]   # "HH:MM" from timestamp
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=7, color="#e0e0e0")


def _style(ax, title: str) -> None:
    ax.set_title(title, color="#e0e0e0", fontsize=10, pad=8)
    ax.set_facecolor("#1e1e1e")
    ax.tick_params(axis="y", labelsize=7, colors="#e0e0e0")
    ax.spines[:].set_color("#444444")
    ax.legend(fontsize=6, loc="upper left", framealpha=0.25)


def _chart_1h(df: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    _draw_candles(ax, df)

    xs    = range(len(df))
    ema9  = calculate_ema(df["Close"], 9)
    ema21 = calculate_ema(df["Close"], 21)
    vwap  = calculate_vwap(df)

    ax.plot(xs, ema9,  color="#2196f3",  linewidth=1.2, label="EMA 9")
    ax.plot(xs, ema21, color="#ff9800",  linewidth=1.2, linestyle="--", label="EMA 21")
    ax.plot(xs, vwap,  color="#ce93d8",  linewidth=1.0, linestyle=":",  label="VWAP")

    _x_labels(ax, df)
    _style(ax, "NIFTY 1H — EMA + VWAP Bias Check")
    fig.patch.set_facecolor("#121212")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


def _chart_15m(df: pd.DataFrame, crossover_idx: int | None, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    _draw_candles(ax, df)

    xs    = range(len(df))
    ema9  = calculate_ema(df["Close"], 9)
    ema21 = calculate_ema(df["Close"], 21)
    vwap  = calculate_vwap(df)

    ax.plot(xs, ema9,  color="#2196f3",  linewidth=1.2, label="EMA 9")
    ax.plot(xs, ema21, color="#ff9800",  linewidth=1.2, linestyle="--", label="EMA 21")
    ax.plot(xs, vwap,  color="#ce93d8",  linewidth=1.0, linestyle=":",  label="VWAP")

    if crossover_idx is not None:
        ax.axvline(x=crossover_idx, color="#ffeb3b", linewidth=1.0,
                   linestyle="--", alpha=0.7, label=f"EMA crossover [{crossover_idx}]")

    _x_labels(ax, df)
    _style(ax, "NIFTY 15m — EMA Crossover Setup")
    fig.patch.set_facecolor("#121212")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


def _chart_5m(
    df:        pd.DataFrame,
    entry_idx: int | None,
    levels:    dict,
    out:       Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    _draw_candles(ax, df)

    xs   = range(len(df))
    ema9 = calculate_ema(df["Close"], 9)
    vwap = calculate_vwap(df)

    ax.plot(xs, ema9, color="#2196f3", linewidth=1.2, label="EMA 9")
    ax.plot(xs, vwap, color="#ce93d8", linewidth=1.0, linestyle=":", label="VWAP")

    # Entry dot
    if entry_idx is not None:
        ep = float(df["Close"].iloc[entry_idx])
        ax.scatter([entry_idx], [ep], color="#00e676", s=90, zorder=5, label="Entry trigger")

    # Horizontal dashed levels
    level_styles = {
        "Entry":   ("#9e9e9e", "--"),
        "Stop":    ("#ef5350", "--"),
        "Target1": ("#4caf50", "--"),
        "Target2": ("#00bcd4", "--"),
    }
    n = len(df)
    for name, price in levels.items():
        color, ls = level_styles.get(name, ("#ffffff", "-"))
        ax.axhline(y=price, color=color, linewidth=0.8, linestyle=ls, alpha=0.8)
        ax.text(n - 0.4, price, f"  {name} {price:,.0f}",
                color=color, fontsize=7, va="center")

    _x_labels(ax, df)
    _style(ax, "NIFTY 5m — Entry Trigger")
    fig.patch.set_facecolor("#121212")
    plt.tight_layout()
    plt.savefig(out, dpi=120)
    plt.close()


def save_charts(
    df_1h:  pd.DataFrame,
    df_15m: pd.DataFrame,
    df_5m:  pd.DataFrame,
    indicators_1h:  dict,
    indicators_15m: dict,
    indicators_5m:  dict,
) -> None:
    """Save 1h_chart.png, 15m_chart.png, 5m_chart.png into charts/."""
    if not _MPL_OK:
        raise ImportError("matplotlib not installed — run: pip install matplotlib")

    plt.style.use("dark_background")
    _CHART_DIR.mkdir(parents=True, exist_ok=True)

    # Slice each DataFrame to its display window (chart_start_idx, if set)
    def _disp(df: pd.DataFrame) -> pd.DataFrame:
        idx = df.attrs.get("chart_start_idx")
        return df.iloc[idx:].copy() if idx else df.copy()

    disp_1h  = _disp(df_1h)
    disp_15m = _disp(df_15m)
    disp_5m  = _disp(df_5m)

    # 1H chart
    _chart_1h(disp_1h, _CHART_DIR / "1h_chart.png")

    # 15m chart — adjust crossover index relative to display slice
    crossover_raw = indicators_15m.get("setup", {}).get("crossover_candle_idx")
    start_15m     = df_15m.attrs.get("chart_start_idx", 0)
    crossover_disp = None
    if crossover_raw is not None:
        adj = crossover_raw - start_15m
        if 0 <= adj < len(disp_15m):
            crossover_disp = adj

    _chart_15m(disp_15m, crossover_disp, _CHART_DIR / "15m_chart.png")

    # 5m chart — adjust entry index relative to display slice
    entry_raw = indicators_5m.get("entry", {}).get("entry_candle_idx")
    start_5m  = df_5m.attrs.get("chart_start_idx", 0)
    entry_disp = None
    if entry_raw is not None:
        adj = entry_raw - start_5m
        if 0 <= adj < len(disp_5m):
            entry_disp = adj

    plan   = indicators_5m.get("plan", {})
    levels = {}
    if plan.get("entry", 0) > 0:
        levels = {
            "Entry":   plan["entry"],
            "Stop":    plan["stop"],
            "Target1": plan["target1"],
            "Target2": plan["target2"],
        }

    _chart_5m(disp_5m, entry_disp, levels, _CHART_DIR / "5m_chart.png")
