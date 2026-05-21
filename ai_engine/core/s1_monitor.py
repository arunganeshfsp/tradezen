"""
S1 Intraday Strategy Monitor
Watches 5-minute candles for OR breakout + EMA cross + RSI confirmation
Reuses existing indicators from core/indicators/
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from indicators.ema import calculate_ema
from indicators.rsi import calculate_rsi


class S1StrategyMonitor:
    """Real-time S1 intraday options trading strategy monitor"""

    # ══════════════════════════════════════════════════════════════════════════
    # CONFIGURATION
    # ══════════════════════════════════════════════════════════════════════════

    # Time gates (IST)
    MARKET_OPEN_HOUR = 9
    OR_COMPLETE_HOUR = 9.5  # 9:30 AM (5-min candle closes)
    HARD_EXIT_HOUR = 13     # 1:00 PM

    # Valid trading days
    VALID_DAYS = ['Wednesday', 'Thursday']

    # Risk gates
    VIX_LIMIT = 20

    # Indicator thresholds
    RSI_CE_MIN = 55      # CE: RSI > 55
    RSI_PE_MAX = 45      # PE: RSI < 45

    # Trade sizing
    LOT_SIZE = 65
    CAPITAL_PER_TRADE = 10000

    # Rate limiting (min seconds between same signal type)
    ALERT_COOLDOWN = 300  # 5 minutes

    def __init__(self):
        """Initialize state machine"""
        # OR formation (locked at 9:30 AM)
        self.or_high = None
        self.or_low = None
        self.or_formed = False

        # Last alert timestamps (for rate limiting)
        self.last_alert_time = {}

        # Session state
        self.session_start_time = None

    def check_s1_setup(self,
                      nifty_price: float,
                      candles: pd.DataFrame,  # 5-min OHLC candles (oldest first)
                      vix: float,
                      current_time: datetime) -> Dict[str, Any]:
        """
        Check S1 setup conditions in real-time

        Args:
            nifty_price: Current NIFTY spot price
            candles: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
                    (must have at least 5 rows for EMA/RSI calculation)
            vix: Current India VIX value
            current_time: Current time (datetime object)

        Returns:
            {
                'signal': 'CE' | 'PE' | None,
                'conditions': {
                    'vix_ok': bool,
                    'time_ok': bool,
                    'day_ok': bool,
                    'or_formed': bool,
                    'price_breakout': bool,
                    'ema_confirmed': bool,
                    'rsi_confirmed': bool
                },
                'strike': int,
                'entry_premium': float,
                'sl': float,
                't1': float,
                'capital': float,
                'gap_analysis': {...},
                'indicators': {
                    'ema9': float,
                    'ema21': float,
                    'rsi': float,
                    'or_high': float,
                    'or_low': float
                }
            }
        """

        result = {
            'signal': None,
            'conditions': {
                'vix_ok': False,
                'time_ok': False,
                'day_ok': False,
                'or_formed': False,
                'price_breakout': False,
                'ema_confirmed': False,
                'rsi_confirmed': False
            },
            'strike': None,
            'entry_premium': None,
            'sl': None,
            't1': None,
            'capital': None,
            'gap_analysis': None,
            'indicators': {}
        }

        # Validate input
        if candles is None or len(candles) < 5:
            return result

        close = candles['close']

        # ────────────────────────────────────────────────────────────────────────
        # GATE 1: VIX Check
        # ────────────────────────────────────────────────────────────────────────
        if vix is None or vix >= self.VIX_LIMIT:
            return result
        result['conditions']['vix_ok'] = True

        # ────────────────────────────────────────────────────────────────────────
        # GATE 2: Time Check
        # ────────────────────────────────────────────────────────────────────────
        current_hour = current_time.hour + current_time.minute / 60
        if not (self.OR_COMPLETE_HOUR <= current_hour < self.HARD_EXIT_HOUR):
            return result
        result['conditions']['time_ok'] = True

        # ────────────────────────────────────────────────────────────────────────
        # GATE 3: Day Check
        # ────────────────────────────────────────────────────────────────────────
        day_name = current_time.strftime('%A')
        if day_name not in self.VALID_DAYS:
            return result
        result['conditions']['day_ok'] = True

        # ────────────────────────────────────────────────────────────────────────
        # GATE 4: OR Formation (Lock at 9:30 AM)
        # ────────────────────────────────────────────────────────────────────────
        if not self.or_formed:
            # First 5-min candle (9:15-9:20) sets OR
            if len(candles) > 0:
                first_candle = candles.iloc[0]
                self.or_high = float(first_candle['high'])
                self.or_low = float(first_candle['low'])
                self.or_formed = True
                self.session_start_time = current_time

        if not self.or_formed or self.or_high is None or self.or_low is None:
            return result
        result['conditions']['or_formed'] = True

        # ────────────────────────────────────────────────────────────────────────
        # Calculate Indicators (reuse core/indicators/ modules)
        # ────────────────────────────────────────────────────────────────────────
        try:
            ema9 = float(calculate_ema(close, 9).iloc[-1])
            ema21 = float(calculate_ema(close, 21).iloc[-1])
            rsi = float(calculate_rsi(close, 14).iloc[-1])
        except Exception as e:
            print(f"[S1] Indicator calculation failed: {e}")
            return result

        result['indicators'] = {
            'ema9': ema9,
            'ema21': ema21,
            'rsi': rsi,
            'or_high': self.or_high,
            'or_low': self.or_low
        }

        # ────────────────────────────────────────────────────────────────────────
        # GATE 5: Check CE Setup
        # ────────────────────────────────────────────────────────────────────────
        ce_signal = self._check_ce(nifty_price, ema9, ema21, rsi, current_time, result)
        if ce_signal:
            return ce_signal

        # ────────────────────────────────────────────────────────────────────────
        # GATE 6: Check PE Setup
        # ────────────────────────────────────────────────────────────────────────
        pe_signal = self._check_pe(nifty_price, ema9, ema21, rsi, current_time, result)
        if pe_signal:
            return pe_signal

        return result

    def _check_ce(self, price: float, ema9: float, ema21: float, rsi: float,
                  current_time: datetime, base_result: Dict) -> Optional[Dict]:
        """Check CALL entry conditions"""

        # Rate limit
        if 'CE' in self.last_alert_time:
            time_since_last = (current_time - self.last_alert_time['CE']).total_seconds()
            if time_since_last < self.ALERT_COOLDOWN:
                return None

        # Condition 1: Price above OR High
        if price <= self.or_high:
            return None
        base_result['conditions']['price_breakout'] = True

        # Condition 2: EMA 9 > EMA 21
        if ema9 <= ema21:
            return None
        base_result['conditions']['ema_confirmed'] = True

        # Condition 3: RSI > 55
        if rsi <= self.RSI_CE_MIN:
            return None
        base_result['conditions']['rsi_confirmed'] = True

        # All conditions met — calculate trade setup
        strike = self._get_strike(price, 'CE')
        entry_premium = self._estimate_premium(strike, 'CE', price)

        result = base_result.copy()
        result['signal'] = 'CE'
        result['strike'] = strike
        result['entry_premium'] = entry_premium
        result['sl'] = self._calc_sl(entry_premium)
        result['t1'] = self._calc_t1(entry_premium)
        result['capital'] = self._calc_capital(entry_premium)
        result['gap_analysis'] = self._analyze_gap(price)

        self.last_alert_time['CE'] = current_time
        return result

    def _check_pe(self, price: float, ema9: float, ema21: float, rsi: float,
                  current_time: datetime, base_result: Dict) -> Optional[Dict]:
        """Check PUT entry conditions"""

        # Rate limit
        if 'PE' in self.last_alert_time:
            time_since_last = (current_time - self.last_alert_time['PE']).total_seconds()
            if time_since_last < self.ALERT_COOLDOWN:
                return None

        # Condition 1: Price below OR Low
        if price >= self.or_low:
            return None
        base_result['conditions']['price_breakout'] = True

        # Condition 2: EMA 9 < EMA 21
        if ema9 >= ema21:
            return None
        base_result['conditions']['ema_confirmed'] = True

        # Condition 3: RSI < 45
        if rsi >= self.RSI_PE_MAX:
            return None
        base_result['conditions']['rsi_confirmed'] = True

        # All conditions met
        strike = self._get_strike(price, 'PE')
        entry_premium = self._estimate_premium(strike, 'PE', price)

        result = base_result.copy()
        result['signal'] = 'PE'
        result['strike'] = strike
        result['entry_premium'] = entry_premium
        result['sl'] = self._calc_sl(entry_premium)
        result['t1'] = self._calc_t1(entry_premium)
        result['capital'] = self._calc_capital(entry_premium)
        result['gap_analysis'] = self._analyze_gap(price)

        self.last_alert_time['PE'] = current_time
        return result

    @staticmethod
    def _calc_sl(entry_premium: float) -> float:
        """SL = Entry × 0.65"""
        return round(entry_premium * 0.65, 2)

    @staticmethod
    def _calc_t1(entry_premium: float) -> float:
        """T1 = Entry × 1.45"""
        return round(entry_premium * 1.45, 2)

    @staticmethod
    def _calc_capital(entry_premium: float) -> float:
        """Capital = Entry × 65 (1 lot)"""
        return round(entry_premium * 65, 0)

    @staticmethod
    def _get_strike(price: float, option_type: str) -> int:
        """Get ATM strike (round to nearest 50)"""
        atm = round(price / 50) * 50
        return int(atm)

    @staticmethod
    def _estimate_premium(strike: int, option_type: str, current_price: float) -> float:
        """Rough premium estimate (use actual Angel One prices when available)"""
        distance = abs(current_price - strike)

        if option_type == 'CE':
            intrinsic = max(0, current_price - strike)
        else:
            intrinsic = max(0, strike - current_price)

        # Time value estimate (decreases with distance)
        time_value = max(20, 100 - distance)
        return round(intrinsic + time_value, 2)

    def _analyze_gap(self, current_price: float) -> Dict[str, float]:
        """Analyze gap between current price and OR levels"""
        return {
            'current_price': round(current_price, 2),
            'or_high': round(self.or_high, 2) if self.or_high else None,
            'or_low': round(self.or_low, 2) if self.or_low else None,
            'gap_to_high': round(self.or_high - current_price, 2) if self.or_high else None,
            'gap_to_low': round(current_price - self.or_low, 2) if self.or_low else None
        }

    def reset_daily(self):
        """Reset state for new trading day (call at market close)"""
        self.or_high = None
        self.or_low = None
        self.or_formed = False
        self.last_alert_time = {}
        self.session_start_time = None
