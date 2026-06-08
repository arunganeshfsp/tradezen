"""
S1 Intraday Strategy Monitor
Watches 5-minute candles for OR breakout + EMA cross + RSI confirmation
"""

import math
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any
from .indicators.ema import calculate_ema
from .indicators.rsi import calculate_rsi


class S1StrategyMonitor:

    OR_COMPLETE_HOUR = 9.5   # 9:30 AM IST
    HARD_EXIT_HOUR   = 13    # 1:00 PM IST
    VALID_DAYS       = ['Wednesday', 'Thursday']
    VIX_LIMIT        = 20
    RSI_CE_MIN       = 55
    RSI_PE_MAX       = 45
    LOT_SIZE         = 65
    ALERT_COOLDOWN   = 300   # seconds between repeat signals

    def __init__(self):
        self.or_high = None
        self.or_low  = None
        self.or_formed = False
        self.last_alert_time = {}
        self.session_start_time = None

    def check_s1_setup(self, nifty_price: float, candles: pd.DataFrame,
                       vix: float, current_time: datetime,
                       rsi_override: float = None) -> Dict[str, Any]:
        result = {
            'signal': None,
            'conditions': {
                'vix_ok':         False,
                'time_ok':        False,
                'day_ok':         False,
                'or_formed':      False,
                'price_breakout': False,
                'ema_confirmed':  False,
                'rsi_confirmed':  False,
            },
            'strike': None, 'entry_premium': None, 'sl': None,
            't1': None, 'capital': None, 'gap_analysis': None,
            'indicators': {},
        }

        if candles is None or len(candles) < 5:
            return result

        # ── Always evaluate every condition independently ───────────────────
        # Gate conditions (eligibility for a signal)
        result['conditions']['vix_ok'] = vix is not None and vix < self.VIX_LIMIT

        current_hour = current_time.hour + current_time.minute / 60
        result['conditions']['time_ok'] = (
            self.OR_COMPLETE_HOUR <= current_hour < self.HARD_EXIT_HOUR
        )

        result['conditions']['day_ok'] = current_time.strftime('%A') in self.VALID_DAYS

        # OR Formation — lock from first candle of the session
        if not self.or_formed:
            first = candles.iloc[0]
            self.or_high = float(first['high'])
            self.or_low  = float(first['low'])
            self.or_formed = True
            self.session_start_time = current_time

        result['conditions']['or_formed'] = self.or_formed
        result['indicators']['or_high'] = self.or_high
        result['indicators']['or_low']  = self.or_low

        # Indicators
        try:
            close = candles['close']
            ema9  = float(calculate_ema(close, 9).iloc[-1])
            ema21 = float(calculate_ema(close, 21).iloc[-1])
            # Use caller-supplied RSI when available (pre-computed from 5-day history
            # for Wilder warm-up accuracy); fall back to today-only calculation
            if rsi_override is not None:
                rsi = rsi_override
            else:
                rsi_raw = float(calculate_rsi(close, 14).iloc[-1])
                rsi = None if math.isnan(rsi_raw) else rsi_raw
        except Exception as e:
            print(f"[S1] Indicator calculation failed: {e}")
            return result

        result['indicators'].update({'ema9': ema9, 'ema21': ema21, 'rsi': rsi})

        # Direction-aware condition evaluation (based on price vs OR)
        ce_price = nifty_price > self.or_high
        pe_price = nifty_price < self.or_low
        result['conditions']['price_breakout'] = ce_price or pe_price

        if ce_price:
            result['conditions']['ema_confirmed'] = ema9 > ema21
            result['conditions']['rsi_confirmed'] = rsi is not None and rsi > self.RSI_CE_MIN
        elif pe_price:
            result['conditions']['ema_confirmed'] = ema9 < ema21
            result['conditions']['rsi_confirmed'] = rsi is not None and rsi < self.RSI_PE_MAX

        # ── Signal only fires when all gate conditions pass ─────────────────
        all_gates_pass = (
            result['conditions']['vix_ok'] and
            result['conditions']['time_ok'] and
            result['conditions']['day_ok']
        )

        if not all_gates_pass:
            return result

        if (ce_price and ema9 > ema21 and rsi is not None and rsi > self.RSI_CE_MIN):
            sig = self._build_signal('CE', nifty_price, ema9, ema21, rsi, current_time, result)
            if sig:
                return sig

        if (pe_price and ema9 < ema21 and rsi is not None and rsi < self.RSI_PE_MAX):
            sig = self._build_signal('PE', nifty_price, ema9, ema21, rsi, current_time, result)
            if sig:
                return sig

        return result

    def _build_signal(self, direction: str, price: float, ema9: float, ema21: float,
                      rsi: float, current_time: datetime, base: Dict) -> Optional[Dict]:
        if direction in self.last_alert_time:
            elapsed = (current_time - self.last_alert_time[direction]).total_seconds()
            if elapsed < self.ALERT_COOLDOWN:
                return None

        strike  = int(round(price / 50) * 50)
        premium = self._estimate_premium(strike, direction, price)

        result = dict(base)
        result['conditions']  = dict(base['conditions'])   # avoid shared-dict mutation
        result['indicators']  = dict(base['indicators'])
        result['signal']      = direction
        result['strike']      = strike
        result['entry_premium'] = premium
        result['sl']          = round(premium * 0.65, 2)
        result['t1']          = round(premium * 1.45, 2)
        result['capital']     = round(premium * self.LOT_SIZE, 0)
        result['gap_analysis'] = self._analyze_gap(price)

        self.last_alert_time[direction] = current_time
        return result

    @staticmethod
    def _estimate_premium(strike: int, option_type: str, current_price: float) -> float:
        intrinsic   = max(0, current_price - strike) if option_type == 'CE' else max(0, strike - current_price)
        time_value  = max(20, 100 - abs(current_price - strike))
        return round(intrinsic + time_value, 2)

    def _analyze_gap(self, current_price: float) -> Dict:
        return {
            'current_price': round(current_price, 2),
            'or_high':       round(self.or_high, 2) if self.or_high else None,
            'or_low':        round(self.or_low,  2) if self.or_low  else None,
            'gap_to_high':   round(self.or_high - current_price, 2) if self.or_high else None,
            'gap_to_low':    round(current_price - self.or_low,  2) if self.or_low  else None,
        }

    def reset_daily(self):
        self.or_high = None
        self.or_low  = None
        self.or_formed = False
        self.last_alert_time = {}
        self.session_start_time = None
