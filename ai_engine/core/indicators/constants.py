"""
Tunable constants for all signal indicators.
Change values here — no need to touch individual indicator files.
"""

# ── Rolling window ─────────────────────────────
WINDOW_SECONDS     = 60     # how far back each indicator looks
MIN_WINDOW_POINTS  = 5      # minimum ticks before any indicator fires

# ── OI Trend ───────────────────────────────────
OI_BUILD_THRESH    = 0.005  # 0.5% OI rise  → "BUILD"
OI_UNWIND_THRESH   = -0.005 # 0.5% OI fall  → "UNWIND"

# ── Price Trend (EMA cross) ────────────────────
EMA_FAST_SPAN      = 5      # fast EMA period
EMA_SLOW_SPAN      = 20     # slow EMA period
MIN_PRICE_MOM      = 0.15   # minimum EMA divergence % to count as trending

# ── Volume Spike ───────────────────────────────
VOL_SPIKE_STDMULT  = 1.5    # spike = volume > mean + 1.5 × std
VOL_SPIKE_FALLBACK = 1.4    # fallback multiplier when std ≈ 0

# ── Bid/Ask Imbalance ──────────────────────────
IMBALANCE_THRESH   = 1.3    # CE/PE ratio must differ by 1.3× to fire

# ── PCR ────────────────────────────────────────
PCR_BULL_THRESH    = 1.3    # PCR > 1.3 → BULL
PCR_BEAR_THRESH    = 0.7    # PCR < 0.7 → BEAR

# ── VWAP ───────────────────────────────────
VWAP_BAND_PCT      = 0.05   # price within ±0.05% of VWAP → "AT" (neutral zone)
VWAP_STRONG_PCT    = 0.20   # price ≥ 0.20% from VWAP → full score (max deviation)
VWAP_MIN_TICKS     = 10     # accumulate at least 10 ticks before trusting the VWAP value
# IST = UTC+5:30; VWAP resets at market open (9:15 AM IST) each trading day
VWAP_MARKET_OPEN_HOUR = 9
VWAP_MARKET_OPEN_MIN  = 15

# ── Spot Trend ─────────────────────────────────
SPOT_TOKEN         = "26000"
SPOT_EMA_FAST      = 5
SPOT_EMA_SLOW      = 20
SPOT_MIN_DIFF_PCT  = 0.05   # EMA divergence % to count as directional

# ── Signal state machine ───────────────────────
SIGNAL_ENTRY_CONF    = 62   # score must reach this to emit a new signal
                            # (was 50 — too low, borderline 55-pt scores fired in
                            #  sideways/choppy markets with no real directional edge)
SIGNAL_EXIT_CONF     = 35   # score must drop below this for exit timer
SIGNAL_EXIT_SECS     = 45   # seconds score must stay low before clearing
MIN_SIGNAL_HOLD_SECS = 90   # minimum hold after entry — no exit/flip allowed
FLIP_CONF            = 75   # score required to flip direction (was 65)
PERSISTENCE_TICKS    = 3    # direction must hold this many ticks before emitting
