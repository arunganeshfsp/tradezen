"""
Angel One SmartAPI implementation of MarketDataProvider.

Responsibilities owned here (not in callers):
  - Session lifecycle: auth, 8-hour TTL proactive refresh, auth-error invalidation
  - Batching: 50 tokens per getMarketData call, 150 ms gap between batches
  - Timeout: 12-second hard limit on every Angel One HTTP call
  - Normalisation: maps Angel One field names → MarketSnapshot
"""

from __future__ import annotations

import time
import threading
import logging

import pandas as pd
import requests as _req

from .base import MarketDataProvider, MarketSnapshot
from config.credentials import get_smart_api
from data.candle_fetcher import fetch_candles

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_TOKEN_TTL   = 8 * 3600      # re-auth every 8 h (tokens valid 24 h)
_BATCH_SIZE  = 50
_BATCH_SLEEP = 0.15          # seconds between batches
_HTTP_TIMEOUT = 12           # seconds — applied to every Angel One HTTP call

_AUTH_ERR_CODES = {"AB1010", "AG8001", "AB8050", "AB1011", "AB8051"}

# ── Global requests timeout ───────────────────────────────────────────────────
# SmartApi uses requests internally with no timeout configured, so calls can
# block forever on a network stall. Patch Session.request once at import time.
_orig_request = _req.Session.request

def _request_with_timeout(self, method, url, **kwargs):
    if "timeout" not in kwargs:
        kwargs["timeout"] = _HTTP_TIMEOUT
    return _orig_request(self, method, url, **kwargs)

_req.Session.request = _request_with_timeout


class AngelOneProvider(MarketDataProvider):
    """
    Concrete MarketDataProvider backed by Angel One SmartAPI.
    Each instance manages its own authenticated session independently —
    no dependency on main.py globals.
    """

    def __init__(self):
        self._smart   = None
        self._auth_ts = 0.0
        self._lock    = threading.Lock()

    # ── Session management ───────────────────────────────────────────────────

    def _session(self, force: bool = False):
        """Return a live SmartAPI session; re-auth when TTL expires."""
        now = time.time()
        if not force and self._smart and (now - self._auth_ts) < _TOKEN_TTL:
            return self._smart
        with self._lock:
            now = time.time()
            if not force and self._smart and (now - self._auth_ts) < _TOKEN_TTL:
                return self._smart
            try:
                self._smart   = get_smart_api()
                self._auth_ts = now
                log.info("[AngelOne] session refreshed")
                return self._smart
            except Exception as e:
                log.warning(f"[AngelOne] auth failed: {e}")
                return None

    def get_session(self):
        """Return a live SmartAPI session for endpoints that need raw Angel One access."""
        return self._session()

    def _check_auth_err(self, resp: dict | None):
        """Drop cached session on Angel One auth-failure response codes."""
        if resp and resp.get("status") is False:
            code = str(resp.get("errorcode", ""))
            if code in _AUTH_ERR_CODES:
                log.warning(f"[AngelOne] auth error {code} — session invalidated")
                self._smart = None

    # ── MarketDataProvider implementation ────────────────────────────────────

    def get_ltp(self, tokens: list[str], exchange: str = "NSE") -> dict[str, float]:
        s = self._session()
        if not s:
            return {}
        out: dict[str, float] = {}
        for i in range(0, len(tokens), _BATCH_SIZE):
            if i:
                time.sleep(_BATCH_SLEEP)
            batch = tokens[i: i + _BATCH_SIZE]
            try:
                resp = s.getMarketData("LTP", {exchange: batch})
                self._check_auth_err(resp)
                for item in (resp or {}).get("data", {}).get("fetched") or []:
                    tok = str(item.get("symbolToken", ""))
                    ltp = item.get("ltp")
                    if tok and ltp is not None:
                        out[tok] = round(float(ltp), 2)
            except Exception as e:
                log.warning(f"[AngelOne] get_ltp batch {i}: {e}")
        return out

    def get_market_data(
        self, tokens: list[str], exchange: str = "NSE"
    ) -> list[MarketSnapshot]:
        s = self._session()
        if not s:
            return []
        out: list[MarketSnapshot] = []
        for i in range(0, len(tokens), _BATCH_SIZE):
            if i:
                time.sleep(_BATCH_SLEEP)
            batch = tokens[i: i + _BATCH_SIZE]
            try:
                resp = s.getMarketData("FULL", {exchange: batch})
                self._check_auth_err(resp)
                for item in (resp or {}).get("data", {}).get("fetched") or []:
                    ltp = float(item.get("ltp") or 0)
                    if not ltp:
                        continue
                    bq         = int(item.get("totBuyQuan") or 0)
                    sq         = int(item.get("totSellQuan") or 0)
                    total_qty  = bq + sq
                    pct        = round(float(item.get("percentChange") or 0), 2)
                    prev_close = float(item.get("close") or 0)
                    if not prev_close and pct != -100:
                        prev_close = round(ltp / (1 + pct / 100), 2)
                    out.append(MarketSnapshot(
                        token         = str(item.get("symbolToken", "")),
                        ltp           = round(ltp, 2),
                        open          = round(float(item.get("open") or 0), 2),
                        high          = round(float(item.get("high") or 0), 2),
                        low           = round(float(item.get("low") or 0), 2),
                        prev_close    = round(prev_close, 2),
                        pct_change    = pct,
                        volume        = int(item.get("tradeVolume") or 0),
                        open_interest = int(float(item.get("opnInterest") or 0)),
                        buy_qty       = bq,
                        sell_qty      = sq,
                        buy_pct       = round(bq / total_qty * 100, 1) if total_qty else 0.0,
                        sell_pct      = round(sq / total_qty * 100, 1) if total_qty else 0.0,
                    ))
            except Exception as e:
                log.warning(f"[AngelOne] get_market_data batch {i}: {e}")
        return out

    def get_candles(
        self,
        token:    str,
        exchange: str,
        interval: str,
        from_dt:  str,
        to_dt:    str,
    ) -> pd.DataFrame:
        s = self._session()
        if not s:
            return pd.DataFrame()
        try:
            return fetch_candles(s, token, exchange, interval, from_dt, to_dt)
        except Exception as e:
            log.warning(f"[AngelOne] get_candles {token}/{interval}: {e}")
            return pd.DataFrame()
