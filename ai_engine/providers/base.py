"""
Market data provider abstraction.

All application code should depend on this interface, never on a specific
broker SDK. Swapping providers (Angel One → Zerodha, Upstox, TrueData …)
requires only a new implementation of MarketDataProvider and a one-line
change in registry.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd


@dataclass
class MarketSnapshot:
    """
    Normalised single-instrument market snapshot.
    Fields are provider-agnostic — every provider maps its own response
    keys to these names so the rest of the app never sees broker-specific
    field names like 'totBuyQuan' or 'percentChange'.
    """
    token:      str
    ltp:        float
    open:       float   = 0.0
    high:       float   = 0.0
    low:        float   = 0.0
    prev_close: float   = 0.0
    pct_change: float   = 0.0
    volume:     int     = 0
    buy_qty:    int     = 0
    sell_qty:   int     = 0

    open_interest: int  = 0

    # Derived — computed by the provider from buy_qty + sell_qty
    buy_pct:    float   = 0.0
    sell_pct:   float   = 0.0

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


class MarketDataProvider(ABC):
    """
    Abstract contract for all market data operations.

    Concrete implementations (AngelOneProvider, ZerodhaProvider, …) must
    implement every @abstractmethod. The default implementations of
    get_option_ltp / get_option_market_data delegate to the equity methods
    with exchange="NFO" — override them if your provider needs different logic.
    """

    # ── Core methods ────────────────────────────────────────────────────────────

    @abstractmethod
    def get_ltp(self, tokens: list[str], exchange: str = "NSE") -> dict[str, float]:
        """
        Returns {token: ltp} for the requested tokens.
        Missing tokens are simply absent from the returned dict.
        """

    @abstractmethod
    def get_market_data(self, tokens: list[str], exchange: str = "NSE") -> list[MarketSnapshot]:
        """
        Returns a full market snapshot (price + depth + volume) for each token.
        Tokens with no data are omitted from the list.
        """

    @abstractmethod
    def get_candles(
        self,
        token:    str,
        exchange: str,
        interval: str,
        from_dt:  str,
        to_dt:    str,
    ) -> pd.DataFrame:
        """
        Returns an OHLCV DataFrame with columns:
            datetime, open, high, low, close, volume
        Returns an empty DataFrame on failure.
        interval examples: ONE_MINUTE, FIVE_MINUTE, ONE_DAY
        from_dt / to_dt format: "YYYY-MM-DD HH:MM"
        """

    # ── Convenience methods (default to NFO) ────────────────────────────────────

    def get_option_ltp(self, tokens: list[str]) -> dict[str, float]:
        """LTPs for NFO option tokens. Override if provider needs different logic."""
        return self.get_ltp(tokens, exchange="NFO")

    def get_option_market_data(self, tokens: list[str]) -> list[MarketSnapshot]:
        """Full snapshots for NFO option tokens."""
        return self.get_market_data(tokens, exchange="NFO")
