"""
Provider registry — single source of truth for which MarketDataProvider
the application uses.

Usage:
    from providers.registry import get_provider

    snaps = get_provider().get_market_data(tokens)

To switch providers (e.g. during testing or vendor migration):
    from providers.registry import set_provider
    from providers.zerodha import ZerodhaProvider   # future
    set_provider(ZerodhaProvider())

Nothing outside this file should instantiate a provider directly.
"""

from __future__ import annotations
from .base import MarketDataProvider

_provider: MarketDataProvider | None = None


def get_provider() -> MarketDataProvider:
    """Return the active provider, initialising Angel One on first call."""
    global _provider
    if _provider is None:
        from .angel_one import AngelOneProvider
        _provider = AngelOneProvider()
        import logging
        logging.getLogger(__name__).info("[registry] AngelOneProvider initialised")
    return _provider


def set_provider(p: MarketDataProvider) -> None:
    """
    Replace the active provider.
    Call this at startup (config-driven) or in tests (mock provider).
    """
    global _provider
    _provider = p
    import logging
    logging.getLogger(__name__).info(f"[registry] provider set to {type(p).__name__}")
