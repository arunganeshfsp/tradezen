"""
Stock Options Strategy Monitor
Adapts S1 strategy for individual F&O stocks:
OR breakout + EMA 9/21 cross + RSI + Volume spike
No day/time restrictions (full session monitoring)
"""

import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any
from .indicators.ema import calculate_ema
from .indicators.rsi import calculate_rsi


# NSE F&O lot sizes for common stocks
LOT_SIZE_MAP = {
    'RELIANCE': 250, 'TCS': 150, 'INFY': 300, 'HDFCBANK': 550,
    'ICICIBANK': 700, 'SBIN': 1500, 'AXISBANK': 625, 'WIPRO': 1500,
    'HINDUNILVR': 300, 'ITC': 3200, 'BAJFINANCE': 125, 'KOTAKBANK': 400,
    'LT': 175, 'MARUTI': 100, 'TITAN': 375, 'ASIANPAINT': 300,
    'ULTRACEMCO': 100, 'NESTLEIND': 50, 'ADANIENT': 625,
    'TATAMOTORS': 1425, 'TATASTEEL': 5500, 'HCLTECH': 700,
    'TECHM': 600, 'SUNPHARMA': 700, 'DRREDDY': 125,
    'ONGC': 3850, 'NTPC': 4500, 'POWERGRID': 4700,
    'BHARTIARTL': 950, 'JSWSTEEL': 1350, 'HINDALCO': 2175,
    'COALINDIA': 4200, 'GRASIM': 475, 'BPCL': 2600,
    'DIVISLAB': 150, 'BAJAJFINSV': 125, 'M&M': 700,
    'HEROMOTOCO': 300, 'EICHERMOT': 150, 'CIPLA': 650,
}


class StockOptionsMonitor:
    """Stock Options Strategy Monitor — S1 adapted for individual F&O stocks"""

    RSI_CE_MIN = 55
    RSI_PE_MAX = 45
    VOLUME_SPIKE_RATIO = 1.5  # current volume > 1.5x average to confirm spike

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self.lot_size = LOT_SIZE_MAP.get(self.symbol, 500)
        self.or_high = None
        self.or_low = None
        self.or_formed = False
        self.last_alert_time = {}

    def check_setup(self, price: float, candles: pd.DataFrame,
                    current_time: datetime) -> Dict[str, Any]:

        result = {
            'signal': None,
            'conditions': {
                'or_formed': False,
                'price_breakout': False,
                'ema_confirmed': False,
                'rsi_confirmed': False,
                'volume_spike': False,
            },
            'strike': None,
            'entry_premium': None,
            'sl': None,
            't1': None,
            'capital': None,
            'gap_analysis': None,
            'indicators': {},
            'symbol': self.symbol,
            'lot_size': self.lot_size,
        }

        if candles is None or len(candles) < 5:
            return result

        close = candles['close']
        volume = candles['volume']

        # ── OR Formation (first 5-min candle) ──────────────────────────────
        if not self.or_formed and len(candles) > 0:
            first = candles.iloc[0]
            self.or_high = float(first['high'])
            self.or_low = float(first['low'])
            self.or_formed = True

        if not self.or_formed:
            return result
        result['conditions']['or_formed'] = True

        # ── Indicators ─────────────────────────────────────────────────────
        try:
            ema9 = float(calculate_ema(close, 9).iloc[-1])
            ema21 = float(calculate_ema(close, 21).iloc[-1])
            rsi = float(calculate_rsi(close, 14).iloc[-1])
        except Exception as e:
            print(f"[StockMonitor] Indicator error: {e}")
            return result

        # Volume spike: current candle volume vs rolling average
        avg_volume = float(volume.rolling(10).mean().iloc[-1]) if len(volume) >= 10 else float(volume.mean())
        current_volume = float(volume.iloc[-1])
        vol_spike = current_volume >= avg_volume * self.VOLUME_SPIKE_RATIO

        result['indicators'] = {
            'ema9': ema9, 'ema21': ema21, 'rsi': rsi,
            'or_high': self.or_high, 'or_low': self.or_low,
            'current_volume': round(current_volume),
            'avg_volume': round(avg_volume),
            'vol_spike': vol_spike,
        }

        # ── Directional bias (visible before full signal fires) ────────────
        ce_pts = int(ema9 > ema21) + int(rsi > 55) + int(price > self.or_high)
        pe_pts = int(ema9 < ema21) + int(rsi < 45) + int(price < self.or_low)
        if ce_pts >= 2 and ce_pts > pe_pts:
            direction = 'CE'
        elif pe_pts >= 2 and pe_pts > ce_pts:
            direction = 'PE'
        else:
            direction = None
        result['direction'] = direction
        result['direction_scores'] = {'ce': ce_pts, 'pe': pe_pts}

        # ── CE Check ───────────────────────────────────────────────────────
        ce = self._check_ce(price, ema9, ema21, rsi, vol_spike, current_time, result)
        if ce:
            return ce

        # ── PE Check ───────────────────────────────────────────────────────
        pe = self._check_pe(price, ema9, ema21, rsi, vol_spike, current_time, result)
        if pe:
            return pe

        return result

    def _check_ce(self, price, ema9, ema21, rsi, vol_spike, current_time, base):
        if 'CE' in self.last_alert_time:
            if (current_time - self.last_alert_time['CE']).total_seconds() < 300:
                return None

        if price <= self.or_high:
            return None
        base['conditions']['price_breakout'] = True

        if ema9 <= ema21:
            return None
        base['conditions']['ema_confirmed'] = True

        if rsi <= self.RSI_CE_MIN:
            return None
        base['conditions']['rsi_confirmed'] = True

        base['conditions']['volume_spike'] = vol_spike

        strike = self._get_strike(price, 'CE')
        premium = self._estimate_premium(strike, 'CE', price)
        r = base.copy()
        r['signal'] = 'CE'
        r['strike'] = strike
        r['entry_premium'] = premium
        r['sl'] = round(premium * 0.65, 2)
        r['t1'] = round(premium * 1.45, 2)
        r['capital'] = round(premium * self.lot_size, 0)
        r['gap_analysis'] = self._gap(price)
        self.last_alert_time['CE'] = current_time
        return r

    def _check_pe(self, price, ema9, ema21, rsi, vol_spike, current_time, base):
        if 'PE' in self.last_alert_time:
            if (current_time - self.last_alert_time['PE']).total_seconds() < 300:
                return None

        if price >= self.or_low:
            return None
        base['conditions']['price_breakout'] = True

        if ema9 >= ema21:
            return None
        base['conditions']['ema_confirmed'] = True

        if rsi >= self.RSI_PE_MAX:
            return None
        base['conditions']['rsi_confirmed'] = True

        base['conditions']['volume_spike'] = vol_spike

        strike = self._get_strike(price, 'PE')
        premium = self._estimate_premium(strike, 'PE', price)
        r = base.copy()
        r['signal'] = 'PE'
        r['strike'] = strike
        r['entry_premium'] = premium
        r['sl'] = round(premium * 0.65, 2)
        r['t1'] = round(premium * 1.45, 2)
        r['capital'] = round(premium * self.lot_size, 0)
        r['gap_analysis'] = self._gap(price)
        self.last_alert_time['PE'] = current_time
        return r

    def _get_strike(self, price: float, option_type: str) -> int:
        """Round to nearest strike interval based on stock price"""
        if price < 100:
            interval = 2.5
        elif price < 500:
            interval = 5
        elif price < 1000:
            interval = 10
        elif price < 5000:
            interval = 50
        else:
            interval = 100
        return int(round(price / interval) * interval)

    def _estimate_premium(self, strike: int, option_type: str, price: float) -> float:
        distance = abs(price - strike)
        intrinsic = max(0, price - strike) if option_type == 'CE' else max(0, strike - price)
        time_value = max(5, 50 - distance * 0.1)
        return round(intrinsic + time_value, 2)

    def _gap(self, price: float) -> Dict:
        return {
            'current_price': round(price, 2),
            'or_high': round(self.or_high, 2),
            'or_low': round(self.or_low, 2),
            'gap_to_high': round(self.or_high - price, 2),
            'gap_to_low': round(price - self.or_low, 2),
        }
