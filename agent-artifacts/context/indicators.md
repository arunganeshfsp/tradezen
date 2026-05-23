# Context: indicators

**Files:** `ai_engine/core/indicators/` (all files), `ai_engine/core/indicators/constants.py`  
**Last updated:** 2026-05-23

---

## Purpose

All Python indicator implementations. Split into two groups: **candle-based** (stateless functions on DataFrames) and **tick-based** (stateful accumulators fed live WebSocket ticks).

---

## Constants (`constants.py`) — single source of truth

All thresholds and tuning values live here. Change here, don't touch individual indicator files.

| Constant | Value | Meaning |
|---|---|---|
| `SPOT_TOKEN` | `"26000"` | NIFTY spot AngelOne token |
| `VWAP_BAND_PCT` | `0.05` | ±0.05% of VWAP = "AT" (neutral) |
| `VWAP_STRONG_PCT` | `0.20` | ≥0.20% from VWAP = full score |
| `VWAP_MIN_TICKS` | `10` | minimum ticks before VWAP is trusted |
| `SIGNAL_ENTRY_CONF` | `62` | score threshold to emit a signal (was 50, raised to cut false fires) |
| `SIGNAL_EXIT_CONF` | `35` | score must drop below this for exit timer |
| `FLIP_CONF` | `75` | score required to flip CE↔PE (was 65) |
| `PCR_BULL_THRESH` | `1.3` | PCR > 1.3 = BULL |
| `PCR_BEAR_THRESH` | `0.7` | PCR < 0.7 = BEAR |
| `VALUE_AREA_PCT` | `0.70` | Market Profile value area encloses 70% of TPOs |
| `TICK_SIZE_INDEX` | `5.0` | Tick bucket size for NIFTY/BANKNIFTY |

TPO_PERIODS dict maps letters A–M to 30-min NSE session brackets (09:15–15:30).

---

## Candle-Based Indicators (stateless, DataFrame → Series/list)

### EMA (`indicators/ema.py`)
```python
calculate_ema(series: pd.Series, period: int) -> pd.Series
```
Uses `pandas.ewm(span=period, adjust=False)`. Standard EMA.

### RSI (`indicators/rsi.py`)
```python
calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series
```
Wilder's EWM method. Handles pure-up-move edge case: `avg_loss = 0 → RSI = 100` via `replace(0, nan)` then `fillna(100)`. Output clipped to `[0, 100]`.

### MACD (`indicators/macd.py`)
```python
calculate_macd(series, fast=12, slow=26, signal=9) -> dict
# keys: macd_line, signal_line, histogram — all pd.Series
```
Built on top of `calculate_ema`.

### Supertrend (`indicators/supertrend.py`)
```python
compute(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> list[dict]
# each dict: { 'value': float | None, 'direction': 'up' | 'down' | 'neutral' }
```
- ATR via Wilder RMA (matches TradingView `ta.atr`)
- `value` = support level when `'up'`, resistance level when `'down'`, `None` until ATR is non-zero
- Returns `'neutral'` for first `period` rows
- Used in `market_psychology` candle analysis and `s1_monitor`

### Market Profile / TPO (`indicators/market_profile.py`)
```python
build_profile(df, tick_size=5.0, symbol="NIFTY", date="", prior_pocs=None) -> dict
```
- Input: 1-min OHLCV DataFrame for one session
- Output: TPO histogram, volume profile, POC, VAH/VAL, IB High/Low, single prints, poor high/low, naked POC flags
- TPO letters A–M map to 30-min NSE brackets (constants.py `TPO_PERIODS`)
- Prices bucketed by `_round_to_tick(price, tick_size)` — tick size 5.0 for index, 1.0 for stocks
- `prior_pocs` list enables naked POC detection across sessions

---

## Tick-Based Indicators (stateful, fed via WebSocket ticks)

These live in `core/indicators/` but are designed to be long-running accumulators inside `SignalEngine`. They use a rolling `TimeWindow` buffer.

### VWAP (`indicators/vwap.py`)

```python
class VWAPCalculator:
    update(price, volume_delta) -> float   # ingest one tick, return current VWAP
    value -> float                          # current VWAP (0.0 if no volume yet)
    tick_count -> int                       # ticks accumulated this session

def compute(spot_data: dict, calculator: VWAPCalculator) -> dict
# returns: { direction, vwap, price, diff_pct, strength }
```

- **Session reset**: `_maybe_reset()` triggers when IST date changes AND clock ≥ 09:15. Pre-market ticks don't start a new session early.
- **Volume delta**: `MarketState` computes the delta from `volume_trade_for_the_day` (cumulative from AngelOne) — `VWAPCalculator` receives the delta, not cumulative.
- **Trust threshold**: `VWAP_MIN_TICKS = 10` — VWAP returns `UNKNOWN` until 10 ticks accumulated (opening-auction burst can skew early VWAP wildly).
- **Direction zones**: `ABOVE` / `BELOW` / `AT` (±0.05% band), `UNKNOWN` if untrusted
- Engine restart mid-session: VWAP restarts from first received tick, converges toward true session VWAP over time.

### PCR (`indicators/pcr.py`)
```python
compute(ce_oi_hist, pe_oi_hist) -> { pcr: float, bias: "BULL"|"BEAR"|"NEUTRAL" }
```
- Uses `.last()` of TimeWindow (most recent tick only — not averaged)
- Returns `NEUTRAL` if either OI is missing (guard against `pe_oi / 0` → infinite BULL)
- Thresholds wider than classic 1.0 midpoint: NIFTY PCR is structurally elevated due to retail hedging

### Volume Spike (`indicators/volume_spike.py`)
- Spike = volume > `mean + 1.5 × std` (STDMULT constant)
- Fallback: if std ≈ 0 (all volumes identical), spike = volume > mean × 1.4

### OI Trend (`indicators/oi_trend.py`)
- OI build: `+0.5%` rise → `"BUILD"`; OI unwind: `−0.5%` fall → `"UNWIND"`

### Bid/Ask Imbalance (`indicators/imbalance.py`)
- CE/PE bid-ask ratio must differ by `1.3×` to fire

### Spot Trend (`indicators/spot_trend.py`)
- EMA fast (5) vs slow (20) on NIFTY spot LTP ticks
- Fires when divergence ≥ 0.05%

### Time Window (`indicators/time_window.py`)
Rolling buffer used by all tick-based indicators. Stores (timestamp, value) pairs; auto-evicts entries older than `WINDOW_SECONDS = 60`.

---

## Candle VWAP (`indicators/candle_vwap.py`)
A separate DataFrame-based VWAP for candle series (different from the tick-based VWAPCalculator). Used by candle-level analysis (not the live WebSocket path).

---

## Known Caveats

- `supertrend.compute()` returns `None` for `value` when ATR = 0 (first row or identical OHLC). Always null-check `value` before using as a price level.
- `VWAPCalculator` is **not thread-safe** — `SignalEngine` owns one instance and updates it synchronously on each tick. Do not share across threads.
- VWAP on engine restart mid-session will be inaccurate until enough ticks accumulate. `VWAP_MIN_TICKS = 10` acts as a gate but the VWAP value itself won't match the true session VWAP from 09:15.
- `PCR` uses only the latest OI snapshot (`TimeWindow.last()`), not a moving average. A single tick with stale/zero OI can briefly flip the signal.
- `calculate_rsi` with short series (< `period` rows) returns noisy values — callers should check `len(series) >= period + 5` before trusting output.
- MACD with default params (12/26/9) requires at least 33 rows for the signal line to stabilise. Used on 5m and 15m candles where this is usually satisfied.
