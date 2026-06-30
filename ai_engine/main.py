"""
TradeZen AI Engine — FastAPI server
Clean version with:
✔ Proper lifecycle
✔ Option chain subscription
✔ Non-blocking WebSocket
✔ Stable signal loop
"""

import asyncio
import json
import math
import os
import subprocess
import threading
import logging
from contextlib import asynccontextmanager
import datetime as _dt
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.credentials import get_smart_api
from data.instrument_master import InstrumentMaster
from data.websocket_client import start_websocket
from core.market_state import MarketState
from core.signal_engine import SignalEngine
from core.indicators.constants import SPOT_TOKEN   # "26000" — single source of truth
from providers.registry import get_provider

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Global Angel One request timeout
# SmartApi uses requests internally with no timeout → calls can block forever
# when Angel One's servers hang (rate limit, token expiry, network blip).
# Patching Session.request here applies to every SmartApi call site automatically.
# ──────────────────────────────────────────────
import requests as _req_mod
_orig_session_request = _req_mod.Session.request
def _session_request_with_timeout(self, method, url, **kwargs):
    if "timeout" not in kwargs:
        kwargs["timeout"] = 12        # 12 s max for any Angel One API call
    return _orig_session_request(self, method, url, **kwargs)
_req_mod.Session.request = _session_request_with_timeout

# ──────────────────────────────────────────────
# Global state (single source of truth)
# ──────────────────────────────────────────────
market_state = MarketState()
signal_engine = None
im = InstrumentMaster()          # kept globally so endpoints can query it
chain_map = []
smart = None                     # SmartAPI session — set in lifespan, used by options endpoints
last_signal = {
    "signal": "INITIALIZING",
    "confidence": 0,
    "reason": "Engine starting"
}

# Trade flow data — populated at startup and updated during the signal loop
trade_flow_data = {
    "prev_ohlc":   None,   # {"high":..., "low":..., "close":..., "date":...}
    "gift_nifty":  None,   # manually supplied GIFT Nifty price (pre-market)
    "nifty_open":  None,   # first spot price at/after 9:15 AM IST
    "orb":         None,   # {"high":..., "low":...} — locked after 9:30 AM
    "_orb_acc":    {"high": None, "low": None},   # accumulator 9:15–9:30
    "india_vix":   None,   # fetched from yfinance ^INDIAVIX, refreshed every 5 min
    "last_ltp":    None,   # last known NIFTY price — persists across WebSocket drops
    "prev_fut_oi": None,   # NIFTY futures OI at startup / 8:30 AM — used as daily baseline
}
_vix_last_refresh: datetime = None   # tracks last VIX fetch time
_ohlc_last_fetched_ist_date: str = None   # IST date when prev_ohlc was last refreshed


# ──────────────────────────────────────────────
# Yahoo Finance helpers (yfinance fallback)
# ──────────────────────────────────────────────
def _yf_prev_ohlc():
    """Fetch previous trading day NIFTY OHLC via yfinance (^NSEI). Primary source."""
    import yfinance as yf
    import datetime as _dt
    ticker = yf.Ticker("^NSEI")
    hist = ticker.history(period="5d", interval="1d")
    if hist.empty:
        raise ValueError("yfinance: no data for ^NSEI")
    hist.index = hist.index.normalize()
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    today = _dt.datetime.now(IST).date()
    past = hist[hist.index.date < today]
    if past.empty:
        raise ValueError("yfinance: no previous day data")
    row = past.iloc[-1]
    return {
        "high":  round(float(row["High"]),  2),
        "low":   round(float(row["Low"]),   2),
        "close": round(float(row["Close"]), 2),
        "date":  past.index[-1].strftime("%Y-%m-%d"),
    }


def _yf_live_price():
    """Fetch latest NIFTY spot price via yfinance (15-min delayed outside market hours)."""
    import yfinance as yf
    import datetime as _dt
    ticker = yf.Ticker("^NSEI")
    hist = ticker.history(period="1d", interval="1m")
    if hist.empty:
        raise ValueError("yfinance: no intraday data")
    hist.index = hist.index.tz_convert("Asia/Kolkata")
    return round(float(hist.iloc[-1]["Close"]), 2)


def _yf_orb():
    """Fetch 9:15–9:30 ORB H/L via yfinance (run after 9:30 AM IST)."""
    import yfinance as yf
    import datetime as _dt
    ticker = yf.Ticker("^NSEI")
    hist = ticker.history(period="1d", interval="1m")
    if hist.empty:
        raise ValueError("yfinance: no intraday data for ORB")
    hist.index = hist.index.tz_convert("Asia/Kolkata")
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)
    t_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
    t_orb  = now_ist.replace(hour=9, minute=30, second=0, microsecond=0)
    orb_data = hist[(hist.index >= t_open) & (hist.index <= t_orb)]
    if orb_data.empty:
        raise ValueError("yfinance: 9:15–9:30 candle not yet available")
    return {
        "high": round(float(orb_data["High"].max()), 2),
        "low":  round(float(orb_data["Low"].min()),  2),
    }


def _yf_vix():
    """Fetch India VIX current value via yfinance (^INDIAVIX)."""
    import yfinance as yf
    import datetime as _dt
    ticker = yf.Ticker("^INDIAVIX")
    hist = ticker.history(period="5d", interval="1d")
    if hist.empty:
        raise ValueError("yfinance: no data for ^INDIAVIX")
    hist.index = hist.index.normalize()
    return round(float(hist.iloc[-1]["Close"]), 2)


# ──────────────────────────────────────────────
# Lifespan (runs once on startup)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global signal_engine, chain_map, im, smart
    log.info("🚀 Starting AI Engine...")

    # Clear stale profile cache on every startup — ensures recomputed profiles
    # always use the latest build_profile algorithm (prevents stale cached results)
    try:
        from storage.sqlite_store import get_conn as _gc
        _c = _gc()
        _c.execute("DELETE FROM market_profile_cache")
        _c.commit()
        _c.close()
        log.info("🗑  Profile cache cleared (fresh start)")
    except Exception as _ce:
        log.warning(f"Could not clear profile cache: {_ce}")

    # 🔐 Connect SmartAPI
    smart = get_smart_api()

    # 📊 Load instruments (uses global im so endpoints can call it too)
    im.load()

    # 📅 Fetch previous trading day NIFTY OHLC for CPR calculation
    # Primary: yfinance (^NSEI) — reliable, no auth needed.
    # Fallback: Angel One getCandleData (may fail for NSE index token on some API versions).
    try:
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)

        # ── Primary: yfinance ──────────────────────────────────────────────────
        ohlc_loaded = False
        try:
            ohlc = _yf_prev_ohlc()
            trade_flow_data["prev_ohlc"] = ohlc
            _ohlc_last_fetched_ist_date = ist_now.strftime("%Y-%m-%d")
            log.info(f"📅 Prev OHLC (yfinance): H={ohlc['high']} L={ohlc['low']} C={ohlc['close']} [{ohlc['date']}]")
            # Staleness check: yfinance for ^NSEI lags 1 trading day — if the date is
            # behind the most recent weekday, discard and let Angel One fill it in.
            expected_prev = ist_now.date() - timedelta(days=1)
            while expected_prev.weekday() >= 5:
                expected_prev -= timedelta(days=1)
            yf_date = datetime.strptime(ohlc["date"], "%Y-%m-%d").date()
            if yf_date >= expected_prev:
                ohlc_loaded = True   # fresh enough
            else:
                log.warning(f"⚠️ yfinance OHLC dated {yf_date}, expected {expected_prev} — trying Angel One for fresher data")
        except Exception as yf_err:
            log.warning(f"⚠️ yfinance OHLC fetch failed: {yf_err} — trying Angel One API")

        # ── Fallback: Angel One getCandleData ──────────────────────────────────
        if not ohlc_loaded:
            prev = ist_now - timedelta(days=1)
            while prev.weekday() >= 5:
                prev -= timedelta(days=1)
            from_dt = prev.strftime("%Y-%m-%d 09:15")
            to_dt   = prev.strftime("%Y-%m-%d 15:30")

            fut_token = im.get_nifty_futures_token()
            log.info(f"📅 Nearest NIFTY futures token for OHLC fallback: {fut_token}")

            attempts = [
                ("NSE", SPOT_TOKEN,             "ONE_DAY"),
                ("NSE", SPOT_TOKEN,             "ONE_HOUR"),
                ("NFO", fut_token or SPOT_TOKEN, "ONE_DAY"),
                ("NFO", fut_token or SPOT_TOKEN, "ONE_HOUR"),
            ]

            for exch, token, interval in attempts:
                try:
                    resp = smart.getCandleData({
                        "exchange":    exch,
                        "symboltoken": token,
                        "interval":    interval,
                        "fromdate":    from_dt,
                        "todate":      to_dt,
                    })
                    log.debug(f"getCandleData({exch}/{token}/{interval}) raw: {resp}")
                    rows = (resp or {}).get("data") or []
                    if not rows:
                        continue
                    if interval == "ONE_DAY":
                        d = rows[-1]
                        H, L, C = float(d[2]), float(d[3]), float(d[4])
                    else:
                        H = max(float(r[2]) for r in rows)
                        L = min(float(r[3]) for r in rows)
                        C = float(rows[-1][4])
                    trade_flow_data["prev_ohlc"] = {
                        "high":  round(H, 2),
                        "low":   round(L, 2),
                        "close": round(C, 2),
                        "date":  prev.strftime("%Y-%m-%d"),
                    }
                    log.info(f"📅 Prev OHLC ({exch}/{interval}): H={H} L={L} C={C} [{prev.date()}]")
                    ohlc_loaded = True
                    break
                except Exception as attempt_err:
                    log.debug(f"getCandleData({exch}/{token}/{interval}) failed: {attempt_err}")
                    continue

        if not ohlc_loaded:
            log.warning(
                "⚠️ All OHLC fetch attempts failed (yfinance + Angel One). "
                "CPR on trade-flow page will show N/A. "
                "Use POST /set-prev-ohlc or the yellow banner on the page to supply values."
            )

        # Re-derive fut_token for retroactive ORB/open fetches below
        try:
            fut_token
        except NameError:
            fut_token = im.get_nifty_futures_token()

        # ── Retroactive: load today's opening price + ORB if engine started late ──
        # These are normally captured tick-by-tick in the signal loop, but if the
        # engine is started after 9:15/9:30 those ticks were missed.
        today_str  = ist_now.strftime("%Y-%m-%d")
        h_now, m_now = ist_now.hour, ist_now.minute
        retro_attempts = [
            ("NSE", SPOT_TOKEN),
            ("NFO", fut_token or SPOT_TOKEN),
        ]

        if (h_now > 9 or (h_now == 9 and m_now >= 15)) and trade_flow_data["nifty_open"] is None:
            for exch, token in retro_attempts:
                try:
                    resp = smart.getCandleData({
                        "exchange":    exch,
                        "symboltoken": token,
                        "interval":    "ONE_MINUTE",
                        "fromdate":    f"{today_str} 09:15",
                        "todate":      f"{today_str} 09:16",
                    })
                    rows = (resp or {}).get("data") or []
                    if rows:
                        trade_flow_data["nifty_open"] = round(float(rows[0][1]), 2)
                        log.info(f"📅 Opening price (retroactive, {exch}): {trade_flow_data['nifty_open']}")
                        break
                except Exception as retro_err:
                    log.debug(f"Opening price retroactive ({exch}/{token}): {retro_err}")

        if (h_now > 9 or (h_now == 9 and m_now >= 30)) and trade_flow_data["orb"] is None:
            # Angel One candle data is primary — it returns actual OHLC from the exchange.
            # yfinance ^NSEI frequently understates the opening-range high because the NSE
            # index is computed from a partial basket in the first few minutes of trading.
            orb_set = False
            for exch, token in retro_attempts:
                try:
                    resp = smart.getCandleData({
                        "exchange":    exch,
                        "symboltoken": token,
                        "interval":    "ONE_MINUTE",
                        "fromdate":    f"{today_str} 09:15",
                        "todate":      f"{today_str} 09:30",
                    })
                    rows = (resp or {}).get("data") or []
                    if rows:
                        orb_h = round(max(float(r[2]) for r in rows), 2)
                        orb_l = round(min(float(r[3]) for r in rows), 2)
                        trade_flow_data["orb"] = {"high": orb_h, "low": orb_l}
                        trade_flow_data["_orb_acc"] = {"high": orb_h, "low": orb_l}
                        log.info(f"📊 ORB (retroactive, {exch}): H={orb_h} L={orb_l}")
                        orb_set = True
                        break
                except Exception as retro_err:
                    log.debug(f"ORB retroactive ({exch}/{token}): {retro_err}")

            if not orb_set:
                try:
                    orb_yf = _yf_orb()
                    trade_flow_data["orb"] = orb_yf
                    trade_flow_data["_orb_acc"] = orb_yf.copy()
                    log.info(f"📊 ORB (retroactive, yfinance fallback): H={orb_yf['high']} L={orb_yf['low']}")
                except Exception as yf_orb_err:
                    log.debug(f"yfinance ORB fallback also failed: {yf_orb_err}")

    except Exception as e:
        log.warning(f"⚠️ Prev OHLC fetch error: {e}")

    # 📊 Fetch India VIX at startup
    try:
        vix = _yf_vix()
        trade_flow_data["india_vix"] = vix
        log.info(f"📊 India VIX: {vix}")
    except Exception as vix_err:
        log.warning(f"⚠️ India VIX fetch failed: {vix_err}")

    # 📊 Fetch NIFTY futures OI baseline (used by /trade-flow for 4-quadrant signal)
    try:
        _ft = im.get_nifty_futures_token()
        if _ft:
            _r = smart.getMarketData("FULL", {"NFO": [str(_ft)]})
            for _item in (_r or {}).get("data", {}).get("fetched", []):
                if str(_item.get("symbolToken")) == str(_ft):
                    _oi = _item.get("opnInterest")
                    if _oi:
                        trade_flow_data["prev_fut_oi"] = int(float(_oi))
                        log.info(f"📊 Futures OI baseline: {trade_flow_data['prev_fut_oi']:,}")
                    break
    except Exception as _fe:
        log.warning(f"⚠️ Futures OI baseline fetch failed: {_fe}")

    # 📈 Get NIFTY LTP
    ltp_data = smart.ltpData("NSE", "NIFTY", SPOT_TOKEN)
    ltp = ltp_data["data"]["ltp"]

    log.info(f"📊 NIFTY LTP: {ltp}")

    # 📊 Build option chain (ATM ± range)
    chain = im.get_option_chain(ltp, range_size=5)
    
    chain_map = chain
    # 🎯 Extract ATM tokens (for signal engine only)
    ce_token, pe_token = im.get_atm_tokens(smart)

    log.info(f"🎯 ATM Tokens → CE: {ce_token} PE: {pe_token}")

    # 📡 Build token list for WebSocket (FULL CHAIN)
    tokens = []
    for row in chain:
        tokens.append(str(row["ce"]["token"]))
        tokens.append(str(row["pe"]["token"]))

    log.info(f"📡 Subscribing {len(tokens)} tokens")

    # 🧠 Initialize signal engine (ATM focused)
    signal_engine = SignalEngine(ce_token, pe_token, market_state)

    # ──────────────────────────────────────────
    # 📡 Start WebSocket (non-blocking thread)
    # ──────────────────────────────────────────
    def run_ws():
        start_websocket(smart, tokens, market_state)

    threading.Thread(target=run_ws, daemon=True).start()

    # ──────────────────────────────────────────
    # 🔁 Background signal loop
    # ──────────────────────────────────────────
    async def signal_loop():
        global last_signal, _vix_last_refresh

        while True:
            try:
                if signal_engine:
                    result = signal_engine.generate()
                    if result:
                        last_signal = result

                # ── Refresh India VIX every 5 minutes ───────────────────
                now_i = datetime.utcnow() + timedelta(hours=5, minutes=30)
                if (_vix_last_refresh is None or
                        (now_i - _vix_last_refresh).total_seconds() >= 300):
                    try:
                        trade_flow_data["india_vix"] = _yf_vix()
                        _vix_last_refresh = now_i
                    except Exception:
                        pass   # keep stale value, don't spam logs

                # ── Track opening price and ORB ─────────────────────────
                spot = market_state.get(SPOT_TOKEN)
                if spot and spot.get("price"):
                    price  = spot["price"]
                    trade_flow_data["last_ltp"] = round(price, 2)   # persist across WS drops
                    now_i  = datetime.utcnow() + timedelta(hours=5, minutes=30)
                    h, m   = now_i.hour, now_i.minute

                    # First tick at/after 9:15 AM = opening price
                    if h == 9 and m >= 15 and trade_flow_data["nifty_open"] is None:
                        trade_flow_data["nifty_open"] = round(price, 2)
                        log.info(f"🔔 NIFTY Open captured: {trade_flow_data['nifty_open']}")

                    # Accumulate ORB range during 9:15–9:30
                    if h == 9 and 15 <= m < 30:
                        acc = trade_flow_data["_orb_acc"]
                        acc["high"] = price if acc["high"] is None else max(acc["high"], price)
                        acc["low"]  = price if acc["low"]  is None else min(acc["low"],  price)

                    # Lock ORB once 9:30 is reached (do once)
                    if trade_flow_data["orb"] is None and (h > 9 or (h == 9 and m >= 30)):
                        acc = trade_flow_data["_orb_acc"]
                        if acc["high"] is not None and acc["low"] is not None:
                            orb_h = round(acc["high"], 2)
                            orb_l = round(acc["low"],  2)

                            # LTP ticks can miss brief intraday spikes.
                            # Correct with Angel One 1-min OHLC candles (NSE spot token).
                            try:
                                day_str = now_i.strftime("%Y-%m-%d")
                                candle_resp = smart.getCandleData({
                                    "exchange":    "NSE",
                                    "symboltoken": SPOT_TOKEN,
                                    "interval":    "ONE_MINUTE",
                                    "fromdate":    f"{day_str} 09:15",
                                    "todate":      f"{day_str} 09:30",
                                })
                                candle_rows = (candle_resp or {}).get("data") or []
                                if candle_rows:
                                    orb_h = max(orb_h, round(max(float(r[2]) for r in candle_rows), 2))
                                    orb_l = min(orb_l, round(min(float(r[3]) for r in candle_rows), 2))
                            except Exception:
                                pass

                            trade_flow_data["orb"] = {"high": orb_h, "low": orb_l}
                            log.info(f"📊 ORB locked: H={orb_h} L={orb_l}")

                # ── Auto-generate daily report after 3:30 PM ────────────
                _maybe_auto_generate_report()

            except Exception as e:
                log.error(f"❌ Signal error: {e}")

            await asyncio.sleep(1)

    asyncio.create_task(signal_loop())

    # ──────────────────────────────────────────
    # 📅 Daily instrument master refresh at 08:30 IST
    # ──────────────────────────────────────────
    async def _daily_instrument_refresh():
        while True:
            now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
            target  = now_ist.replace(hour=8, minute=30, second=0, microsecond=0)
            if now_ist >= target:
                target += timedelta(days=1)
            while target.weekday() >= 5:   # skip Saturday (5) and Sunday (6)
                target += timedelta(days=1)
            wait_sec = (target - now_ist).total_seconds()
            log.info(f"📅 Instrument refresh scheduled: {target.strftime('%a %d-%b %H:%M IST')} ({wait_sec/3600:.1f}h away)")
            await asyncio.sleep(wait_sec)
            # ── Instrument master ──────────────────────────────────────────────
            try:
                log.info("🔄 Refreshing instrument master (daily pre-market)...")
                im.reload()
                log.info(f"✅ Instrument master refreshed — {len(im.data)} NIFTY options loaded")
            except Exception as _ire:
                log.error(f"❌ Instrument master refresh failed: {_ire}")
            # ── Previous day OHLC — refresh with SmartAPI fallback if yfinance lags ─
            try:
                ohlc = _yf_prev_ohlc()
                expected = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date() - timedelta(days=1)
                while expected.weekday() >= 5:
                    expected -= timedelta(days=1)
                import datetime as _dt2
                yf_d = _dt2.datetime.strptime(ohlc["date"], "%Y-%m-%d").date()
                if yf_d >= expected:
                    trade_flow_data["prev_ohlc"] = ohlc
                    log.info(f"📅 Prev OHLC refreshed (daily): [{ohlc['date']}]")
                else:
                    raise ValueError(f"yfinance stale: {yf_d} < {expected}")
            except Exception as _oe:
                log.warning(f"⚠️ Daily OHLC yfinance failed/stale ({_oe}) — trying SmartAPI")
                try:
                    _prev = (datetime.utcnow() + timedelta(hours=5, minutes=30)).date() - timedelta(days=1)
                    while _prev.weekday() >= 5:
                        _prev -= timedelta(days=1)
                    _s2 = smart or _get_smart()
                    for _ex, _tk in [("NSE", SPOT_TOKEN), ("NFO", im.get_nifty_futures_token() or SPOT_TOKEN)]:
                        _r = _s2.getCandleData({"exchange": _ex, "symboltoken": _tk, "interval": "ONE_DAY",
                                                "fromdate": _prev.strftime("%Y-%m-%d 09:15"),
                                                "todate":   _prev.strftime("%Y-%m-%d 15:30")})
                        _rows = (_r or {}).get("data") or []
                        if _rows:
                            d = _rows[-1]
                            trade_flow_data["prev_ohlc"] = {"high": round(float(d[2]), 2), "low": round(float(d[3]), 2),
                                                             "close": round(float(d[4]), 2), "date": _prev.strftime("%Y-%m-%d")}
                            log.info(f"📅 Prev OHLC refreshed via SmartAPI (daily): [{_prev}]")
                            break
                except Exception as _se:
                    log.error(f"❌ Daily OHLC SmartAPI fallback failed: {_se}")
            # ── Refresh futures OI baseline for the new day ───────────────────
            try:
                _ft2 = im.get_nifty_futures_token()
                if _ft2:
                    _s3 = smart or _get_smart()
                    _r2 = _s3.getMarketData("FULL", {"NFO": [str(_ft2)]})
                    for _item2 in (_r2 or {}).get("data", {}).get("fetched", []):
                        if str(_item2.get("symbolToken")) == str(_ft2):
                            _oi2 = _item2.get("opnInterest")
                            if _oi2:
                                trade_flow_data["prev_fut_oi"] = int(float(_oi2))
                                log.info(f"📊 Futures OI baseline refreshed: {trade_flow_data['prev_fut_oi']:,}")
                            break
            except Exception as _fe2:
                log.warning(f"⚠️ Daily futures OI baseline refresh failed: {_fe2}")
            # ── Reset intraday fields so today's open/ORB are captured fresh ────
            # gift_nifty is NOT reset — user may have entered it pre-market before 8:30
            trade_flow_data["nifty_open"] = None
            trade_flow_data["orb"]        = None
            log.info("🔄 Intraday fields reset for new trading day")

    asyncio.create_task(_daily_instrument_refresh())

    log.info("✅ AI Engine ready — WebSocket + signal loop running")

    yield

    log.info("🛑 Shutting down AI Engine...")


# ──────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────
app = FastAPI(title="TradeZen AI Engine", lifespan=lifespan)

# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/signal")
def get_signal():
    """
    Returns the latest AI signal plus live NIFTY spot data.
    `nifty_ltp` and `nifty_chg` are consumed by fno_signal.html toolbar.
    """
    global market_state

    response = dict(last_signal)   # don't mutate the shared dict

    spot = market_state.get(SPOT_TOKEN)
    if spot and spot.get("price"):
        response["nifty_ltp"] = round(spot["price"], 2)
        # price_change is tick-to-tick; express as % for the toolbar badge
        prev_price = spot["price"] - spot.get("price_change", 0)
        if prev_price and prev_price != spot["price"]:
            response["nifty_chg"] = round(spot.get("price_change", 0) / prev_price * 100, 2)
        else:
            response["nifty_chg"] = 0.0

    return response

@app.get("/option-chain/structured")
def get_structured_chain():
    """
    Returns strike-wise structured option chain
    """
    global market_state, signal_engine

    result = []

    if not signal_engine:
        return {"data": []}

    ce_token = signal_engine.ce_token
    pe_token = signal_engine.pe_token

    # Need to enhance this later with full mapping
    for token, data in market_state.data.items():
        result.append({
            "token": token,
            "price": data.get("price"),
            "oi": data.get("oi"),
            "volume": data.get("volume"),
        })

    return {"data": result}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "signal": last_signal.get("signal"),
    }


@app.post("/reload-instruments")
def reload_instruments():
    """Force-refresh the instrument master from Angel One — use when new contracts aren't showing up."""
    from fastapi import HTTPException
    try:
        im.reload()
        return {"status": "ok", "count": len(im.data), "loaded_at": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug")
def debug():
    """
    Returns the full last signal including diagnostic scores.
    Use this to diagnose why a signal is being generated:
      bull/bear/side scores, which factors fired, raw vs emitted signal.
    """
    return last_signal


@app.get("/reset-signal")
def reset_signal():
    """
    Clears the signal engine state machine — useful during testing when the
    signal appears stuck.  Does NOT affect WebSocket data or indicator windows.
    """
    global signal_engine, last_signal
    if signal_engine:
        signal_engine._last_raw_signal    = None
        signal_engine._persist_count      = 0
        signal_engine._emitted_signal     = None
        signal_engine._emitted_confidence = 0
        signal_engine._low_score_since    = None
        signal_engine._signal_emitted_at  = None
    last_signal = {"signal": "WAIT", "confidence": 0, "reason": "Manual reset"}
    return {"status": "ok", "message": "Signal state cleared"}


# ──────────────────────────────────────────────
# CORS
# ──────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.get("/expiries")
def get_expiries():
    """
    Returns upcoming expiry dates so the frontend can populate the dropdown.
    nearest: the current active expiry (used by the signal engine).
    upcoming: all valid expiries including the nearest.
    """
    global im
    expiries = im.get_upcoming_expiries(n=4)
    return {
        "nearest":  expiries[0] if expiries else None,
        "upcoming": expiries,
    }


@app.get("/fetch-gift-nifty")
def fetch_gift_nifty_auto():
    """
    Auto-fetch NIFTY live price as a GIFT Nifty proxy.
    Source priority:
      1. Live WebSocket market_state (real-time, during market hours)
      2. yfinance ^NSEI (15-min delayed, works when Yahoo Finance is up)
    During pre-market (before 9:15 AM) neither source is available — user must enter manually.
    """
    global trade_flow_data, market_state

    # 1. Live WebSocket price (best — real-time during market hours)
    spot = market_state.get(SPOT_TOKEN)
    if spot and spot.get("price"):
        price = round(spot["price"], 2)
        trade_flow_data["gift_nifty"] = price
        log.info(f"📅 GIFT Nifty set from live WebSocket: {price}")
        return {"status": "ok", "gift_nifty": price, "source": "live (WebSocket)"}

    # 2. yfinance fallback (delayed, depends on Yahoo Finance availability)
    try:
        price = _yf_live_price()
        trade_flow_data["gift_nifty"] = price
        log.info(f"📅 GIFT Nifty set from yfinance: {price}")
        return {"status": "ok", "gift_nifty": price, "source": "yfinance (delayed)"}
    except Exception as yf_err:
        log.debug(f"yfinance GIFT Nifty fetch failed: {yf_err}")

    # Both failed — pre-market or Yahoo Finance is down
    return {
        "status": "error",
        "message": (
            "Auto-fetch unavailable: market not yet open or Yahoo Finance is down. "
            "Enter GIFT Nifty manually from your broker terminal (Kite / AngelOne)."
        ),
    }


class _PriceBody(BaseModel):
    price: float

@app.post("/set-gift-nifty")
def set_gift_nifty(body: _PriceBody):
    """
    Supply the current GIFT Nifty price manually (pre-market, from broker terminal).
    Body: { "price": 24204 }
    """
    global trade_flow_data
    trade_flow_data["gift_nifty"] = None if body.price == 0 else round(body.price, 2)
    log.info(f"📅 GIFT Nifty set: {trade_flow_data['gift_nifty']}")
    return {"status": "ok", "gift_nifty": trade_flow_data["gift_nifty"]}


@app.post("/set-prev-ohlc")
def set_prev_ohlc(high: float, low: float, close: float, date: str = None):
    """
    Manually supply previous day NIFTY H/L/C when getCandleData is unavailable.
    Example: POST /set-prev-ohlc?high=24801&low=24320&close=24680
    """
    global trade_flow_data
    from datetime import datetime
    trade_flow_data["prev_ohlc"] = {
        "high":  round(high, 2),
        "low":   round(low, 2),
        "close": round(close, 2),
        "date":  date or (datetime.utcnow() + timedelta(hours=5, minutes=30) - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    log.info(f"📅 Prev OHLC set manually: H={high} L={low} C={close}")
    return {"status": "ok", "prev_ohlc": trade_flow_data["prev_ohlc"]}


@app.post("/set-nifty-open")
def set_nifty_open(price: float):
    """
    Manually supply today's 9:15 AM opening price when engine started late.
    Example: POST /set-nifty-open?price=24420
    """
    global trade_flow_data
    trade_flow_data["nifty_open"] = None if price == 0 else round(price, 2)
    log.info(f"📅 Nifty open set manually: {trade_flow_data['nifty_open']}")
    return {"status": "ok", "nifty_open": trade_flow_data["nifty_open"]}


@app.post("/set-orb")
def set_orb(high: float, low: float):
    """
    Manually supply today's ORB (9:15–9:30 candle H/L) when engine started late.
    Example: POST /set-orb?high=24520&low=24390
    """
    global trade_flow_data
    trade_flow_data["orb"] = {"high": round(high, 2), "low": round(low, 2)}
    trade_flow_data["_orb_acc"] = {"high": round(high, 2), "low": round(low, 2)}
    log.info(f"📊 ORB set manually: H={high} L={low}")
    return {"status": "ok", "orb": trade_flow_data["orb"]}


@app.get("/trade-flow")
def get_trade_flow():
    """
    Returns live trade flow data for the Nifty Trade Flow decision framework.
    Covers 3 phases: Pre-Market (CPR + GIFT gap), 9:15 open, ORB (9:30+).
    """
    global market_state, trade_flow_data, chain_map

    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    h, m = now_ist.hour, now_ist.minute

    # Current phase
    if h < 9 or (h == 9 and m < 15):
        phase = "pre_market"
    elif h == 9 and m < 30:
        phase = "market_open"
    elif h < 15 or (h == 15 and m < 30):
        phase = "orb"
    else:
        phase = "closed"

    # Live NIFTY price — fall back to last known LTP if WebSocket has dropped
    spot = market_state.get(SPOT_TOKEN)
    nifty_ltp = round(spot["price"], 2) if spot and spot.get("price") else None
    effective_ltp = nifty_ltp or trade_flow_data.get("last_ltp")

    # ── CPR calculation from previous day OHLC ───────────────────────────────
    cpr = None
    prev = trade_flow_data.get("prev_ohlc")
    if prev:
        H, L, C = prev["high"], prev["low"], prev["close"]
        PP   = round((H + L + C) / 3, 2)
        _bc  = round((H + L) / 2, 2)          # raw midpoint
        _tc  = round(2 * PP - _bc, 2)         # 2·PP − BC
        # TC is always the numerically higher pivot, BC the lower
        TC   = max(_tc, _bc)
        BC   = min(_tc, _bc)
        R1   = round(2 * PP - L, 2)
        R2   = round(PP + (H - L), 2)
        R3   = round(H + 2 * (PP - L), 2)
        S1   = round(2 * PP - H, 2)
        S2   = round(PP - (H - L), 2)
        S3   = round(L - 2 * (H - PP), 2)
        width = round(TC - BC, 2)             # always positive
        cpr = {
            "pp": PP, "tc": TC, "bc": BC,
            "r1": R1, "r2": R2, "r3": R3,
            "s1": S1, "s2": S2, "s3": S3,
            "width": width,
            "type": "narrow" if width < 40 else ("moderate" if width <= 80 else "wide"),
        }

    # ── Opening price vs CPR ──────────────────────────────────────────────────
    open_data = None
    nifty_open = trade_flow_data.get("nifty_open")
    if nifty_open and cpr:
        if nifty_open > cpr["tc"]:
            position = "above_tc"
        elif nifty_open < cpr["bc"]:
            position = "below_bc"
        else:
            position = "inside_cpr"
        open_data = {
            "price":    nifty_open,
            "position": position,
            "vs_tc":    round(nifty_open - cpr["tc"], 2),
            "vs_bc":    round(nifty_open - cpr["bc"], 2),
        }

    # ── ORB analysis ─────────────────────────────────────────────────────────
    orb_data = None
    orb = trade_flow_data.get("orb")
    if orb and cpr:
        orb_range = round(orb["high"] - orb["low"], 2)
        if orb["low"] > cpr["tc"]:
            vs_cpr = "above_tc"
        elif orb["high"] < cpr["bc"]:
            vs_cpr = "below_bc"
        else:
            vs_cpr = "straddles"

        # ── Straddle lean: score-based directional bias ───────────────────
        # 3 factors scored. Threshold ≥ 3 to call a conditional scenario.
        #
        # Validated on 2026-04-24:
        #   gap +19 (0) + open near-BC/+2.46 (bear+1) + ORB 153 pts below BC/4.6×width (bear+2)
        #   = bear 3 → conditional_bear, bear_triggered=True, close 23897 < T1 23869 ✓
        #
        # Validated on 2026-04-23:
        #   gap −72.5 (bear+2) + open below_bc (bear+2) + ORB 133 pts below BC (bear+2)
        #   + ORB 58 pts above TC (bull+2) = bear 6 vs bull 2 → conditional_bear ✓
        straddle_lean = "neutral"
        lean_scores   = {"bear": 0, "bull": 0}
        if vs_cpr == "straddles" and open_data and prev:
            gap = open_data["price"] - prev["close"]

            # Factor 1: Gap direction (0/1/2 pts)
            if gap < -50:   lean_scores["bear"] += 2
            elif gap < -20: lean_scores["bear"] += 1
            elif gap > 50:  lean_scores["bull"] += 2
            elif gap > 20:  lean_scores["bull"] += 1

            # Factor 2: Opening position (with near-edge refinement)
            if open_data["position"] == "below_bc":
                lean_scores["bear"] += 2
            elif open_data["position"] == "above_tc":
                lean_scores["bull"] += 2
            elif open_data["position"] == "inside_cpr":
                # Opening within 30% of CPR width from BC or TC edge gets +1
                near_edge = cpr["width"] * 0.3
                if open_data["vs_bc"] < near_edge:     # barely above BC
                    lean_scores["bear"] += 1
                elif open_data["vs_tc"] > -near_edge:  # barely below TC
                    lean_scores["bull"] += 1

            # Factor 3: ORB extension beyond CPR — scaled by CPR width
            # Extension > 1× CPR width = strong momentum = +2, else +1
            orb_below_bc = cpr["bc"] - orb["low"]
            orb_above_tc = orb["high"] - cpr["tc"]
            if orb_below_bc > cpr["width"]:   lean_scores["bear"] += 2
            elif orb_below_bc > 0:            lean_scores["bear"] += 1
            if orb_above_tc > cpr["width"]:   lean_scores["bull"] += 2
            elif orb_above_tc > 0:            lean_scores["bull"] += 1

            if lean_scores["bear"] >= 3 and lean_scores["bear"] > lean_scores["bull"]:
                straddle_lean = "bear_lean"
            elif lean_scores["bull"] >= 3 and lean_scores["bull"] > lean_scores["bear"]:
                straddle_lean = "bull_lean"

        orb_data = {
            "high":    orb["high"],
            "low":     orb["low"],
            "range":   orb_range,
            "vs_cpr":  vs_cpr,
            "straddle_lean":  straddle_lean if vs_cpr == "straddles" else None,
            "lean_scores":    lean_scores   if vs_cpr == "straddles" else None,
            "bear_triggered": (effective_ltp < orb["low"])  if effective_ltp else None,
            "bull_triggered": (effective_ltp > orb["high"]) if effective_ltp else None,
            "t1_bull": round(orb["high"] + orb_range, 2),
            "t2_bull": round(orb["high"] + 2 * orb_range, 2),
            "t3_bull": round(orb["high"] + 3 * orb_range, 2),
            "sl_bull": round(orb["high"] - 20, 2),
            "t1_bear": round(orb["low"] - orb_range, 2),
            "t2_bear": round(orb["low"] - 2 * orb_range, 2),
            "t3_bear": round(orb["low"] - 3 * orb_range, 2),
            "sl_bear": round(orb["low"] + 20, 2),
        }

    # ── PCR from live chain_map (total across all strikes) ───────────────────
    oi_sentiment = None
    try:
        total_ce_oi = total_pe_oi = 0
        for row in chain_map:
            ce_tok = str(row["ce"]["token"])
            pe_tok = str(row["pe"]["token"])
            ce_oi  = (market_state.data.get(ce_tok) or {}).get("oi") or 0
            pe_oi  = (market_state.data.get(pe_tok) or {}).get("oi") or 0
            total_ce_oi += ce_oi
            total_pe_oi += pe_oi
        if total_ce_oi > 0 and total_pe_oi > 0:
            pcr_val = round(total_pe_oi / total_ce_oi, 2)
            if pcr_val > 1.3:
                pcr_label = "BULLISH"
            elif pcr_val < 0.7:
                pcr_label = "BEARISH"
            else:
                pcr_label = "NEUTRAL"
            oi_sentiment = {
                "pcr":          pcr_val,
                "label":        pcr_label,
                "total_pe_oi":  total_pe_oi,
                "total_ce_oi":  total_ce_oi,
            }
    except Exception:
        pass

    # Incorporate PCR into straddle lean as Factor 4 (if ORB straddles CPR)
    if oi_sentiment and orb_data and orb_data.get("vs_cpr") == "straddles":
        p = oi_sentiment["pcr"]
        if p > 1.5:    lean_scores["bull"] += 2
        elif p > 1.3:  lean_scores["bull"] += 1
        elif p < 0.5:  lean_scores["bear"] += 2
        elif p < 0.7:  lean_scores["bear"] += 1
        # Re-evaluate lean with updated scores
        if lean_scores["bear"] >= 3 and lean_scores["bear"] > lean_scores["bull"]:
            orb_data["straddle_lean"] = "bear_lean"
        elif lean_scores["bull"] >= 3 and lean_scores["bull"] > lean_scores["bear"]:
            orb_data["straddle_lean"] = "bull_lean"
        orb_data["lean_scores"] = lean_scores

    # ── Futures OI (near-month NIFTY futures) ────────────────────────────────
    fut_oi_data = None
    try:
        _s_f = smart or _get_smart()
        _ft_f = im.get_nifty_futures_token()
        if _ft_f and _s_f:
            _r_f = _s_f.getMarketData("FULL", {"NFO": [str(_ft_f)]})
            for _item_f in (_r_f or {}).get("data", {}).get("fetched", []):
                if str(_item_f.get("symbolToken")) == str(_ft_f):
                    _oi_f   = _item_f.get("opnInterest")
                    _ltp_f  = _item_f.get("ltp")
                    if _oi_f:
                        _oi_int   = int(float(_oi_f))
                        _base_oi  = trade_flow_data.get("prev_fut_oi")
                        _oi_chg   = (_oi_int - _base_oi) if _base_oi else None
                        _prev_c   = (trade_flow_data.get("prev_ohlc") or {}).get("close")
                        _ltp_val  = float(_ltp_f) if _ltp_f else None
                        _price_up = (_ltp_val > _prev_c) if (_ltp_val and _prev_c) else None
                        _oi_up    = (_oi_chg > 0)        if _oi_chg is not None else None
                        _signal   = None
                        if _price_up is not None and _oi_up is not None:
                            if   _price_up and _oi_up:      _signal = "long_buildup"
                            elif not _price_up and _oi_up:  _signal = "short_buildup"
                            elif _price_up and not _oi_up:  _signal = "short_covering"
                            else:                           _signal = "long_unwinding"
                        fut_oi_data = {
                            "oi":     _oi_int,
                            "oi_chg": _oi_chg,
                            "signal": _signal,
                            "ltp":    round(_ltp_val, 2) if _ltp_val else None,
                        }
                    break
    except Exception:
        pass

    # ── Auto scenario determination ───────────────────────────────────────────
    # Stage 1: CPR + ORB structure (price-based, uses yesterday's levels)
    scenario = "unknown"
    if open_data and orb_data:
        op   = open_data["position"]
        ov   = orb_data["vs_cpr"]
        lean = orb_data.get("straddle_lean", "neutral")
        if op == "above_tc" and ov == "above_tc":
            scenario = "bull"
        elif op == "below_bc" and ov == "below_bc":
            scenario = "bear"
        elif ov == "straddles" and lean == "bear_lean":
            scenario = "conditional_bear"
        elif ov == "straddles" and lean == "bull_lean":
            scenario = "conditional_bull"
        else:
            scenario = "skip"
    elif open_data:
        if open_data["position"] == "above_tc":
            scenario = "bull"
        elif open_data["position"] == "below_bc":
            scenario = "bear"
        else:
            scenario = "skip"

    # Stage 2: Futures OI modifier (intraday money flow confirmation)
    # Only strong signals (long_buildup / short_buildup) alter the scenario.
    # short_covering / long_unwinding are secondary — they don't add new positions,
    # so they don't constitute a directional conviction shift.
    _oi_sig = (fut_oi_data or {}).get("signal")
    if _oi_sig in ("long_buildup", "short_buildup"):
        if _oi_sig == "long_buildup":
            if   scenario == "bull":            pass                    # confirmed — no change
            elif scenario == "conditional_bull": scenario = "bull"      # OI upgrades the lean
            elif scenario == "bear":            scenario = "conditional_bear"  # OI diverges
            elif scenario in ("skip", "unknown"): scenario = "conditional_bull"
        elif _oi_sig == "short_buildup":
            if   scenario == "bear":            pass                    # confirmed — no change
            elif scenario == "conditional_bear": scenario = "bear"      # OI upgrades the lean
            elif scenario == "bull":            scenario = "conditional_bull"  # OI diverges
            elif scenario in ("skip", "unknown"): scenario = "conditional_bear"

    # Build a human-readable note when OI changed the scenario
    _oi_note = None
    if _oi_sig == "long_buildup" and scenario != "bull":
        _oi_note = "Long Buildup detected — bulls adding positions intraday"
    elif _oi_sig == "short_buildup" and scenario != "bear":
        _oi_note = "Short Buildup detected — bears adding positions intraday"
    elif _oi_sig == "long_buildup":
        _oi_note = "Long Buildup confirms bull scenario"
    elif _oi_sig == "short_buildup":
        _oi_note = "Short Buildup confirms bear scenario"

    return {
        "phase":            phase,
        "time_ist":         now_ist.strftime("%H:%M:%S"),
        "date":             now_ist.strftime("%Y-%m-%d"),
        "prev_day":         prev,
        "gift_nifty":       trade_flow_data.get("gift_nifty"),
        "india_vix":        trade_flow_data.get("india_vix"),
        "cpr":              cpr,
        "nifty_open":       open_data,
        "orb":              orb_data,
        "nifty_ltp":        effective_ltp,
        "scenario":         scenario,
        "scenario_oi_note": _oi_note,
        "oi_sentiment":     oi_sentiment,
        "fut_oi":           fut_oi_data,
    }


@app.get("/option-chain")
def get_option_chain(expiry: str = None):
    """
    Returns option chain for the given expiry.
    When expiry is omitted (or equals the nearest), returns live WebSocket data.
    For other expiries, returns static instrument data (no live prices).
    """
    global market_state, chain_map, im

    nearest = im.get_nearest_expiry()
    requested = (expiry or nearest).upper()
    is_live = (requested == nearest)

    # For the nearest expiry use the WebSocket-enriched chain_map.
    # For other expiries build a static chain from instrument data only
    # (no live prices — those tokens are not subscribed).
    if is_live:
        rows = chain_map
    else:
        spot = market_state.get(SPOT_TOKEN)
        ltp  = spot["price"] if spot and spot.get("price") else 24000
        rows = im.get_option_chain(ltp, range_size=5, expiry=requested)

    result = []
    for row in rows:
        ce_token = str(row["ce"]["token"])
        pe_token = str(row["pe"]["token"])

        ce_data = market_state.data.get(ce_token, {}) if is_live else {}
        pe_data = market_state.data.get(pe_token, {}) if is_live else {}

        result.append({
            "strike": row["strike"],
            "live":   is_live,          # frontend can show a badge

            "ce": {
                "token":        ce_token,
                "symbol":       row["ce"]["symbol"],
                "expiry":       row["ce"]["expiry"],
                "price":        ce_data.get("price"),
                "oi":           ce_data.get("oi"),
                "volume":       ce_data.get("volume"),
                "buy_qty":      ce_data.get("buy_qty"),
                "sell_qty":     ce_data.get("sell_qty"),
                "price_change": ce_data.get("price_change"),
                "oi_change":    ce_data.get("oi_change"),
            },

            "pe": {
                "token":        pe_token,
                "symbol":       row["pe"]["symbol"],
                "expiry":       row["pe"]["expiry"],
                "price":        pe_data.get("price"),
                "oi":           pe_data.get("oi"),
                "volume":       pe_data.get("volume"),
                "buy_qty":      pe_data.get("buy_qty"),
                "sell_qty":     pe_data.get("sell_qty"),
                "price_change": pe_data.get("price_change"),
                "oi_change":    pe_data.get("oi_change"),
            }
        })

    return {
        "count":   len(result),
        "expiry":  requested,
        "live":    is_live,
        "data":    result,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Market Profile endpoints
# ══════════════════════════════════════════════════════════════════════════════

from data.candle_fetcher import fetch_candles
from core.indicators.market_profile import build_profile, _calc_value_area
from storage.sqlite_store import get_conn, get_cached_profile, upsert_profile
from core.indicators.constants import TICK_SIZE_INDEX, VALUE_AREA_PCT


def _resolve_token_and_exchange(symbol_token: str, exchange: str, smart):
    """
    If the caller requests NSE 26000 (NIFTY spot index) but getCandleData fails
    for it, transparently fall back to the nearest NFO futures token.
    Returns (token, exchange) to actually use.
    """
    return symbol_token, exchange   # candle_fetcher handles empty-result case internally


_smart_lock    = threading.Lock()
_smart_auth_ts = 0.0
_SMART_TTL     = 8 * 3600       # re-auth every 8 hours (token valid 24 h but refresh proactively)
_SMART_AUTH_ERR_CODES = {"AB1010", "AG8001", "AB8050", "AB1011", "AB8051"}


def _get_smart(force: bool = False):
    """Return the shared SmartAPI session; re-auth on first call and every 8 hours."""
    import time as _t
    global smart, _smart_auth_ts
    now = _t.time()
    if not force and smart and (now - _smart_auth_ts) < _SMART_TTL:
        return smart
    with _smart_lock:
        now = _t.time()
        if not force and smart and (now - _smart_auth_ts) < _SMART_TTL:
            return smart
        try:
            smart = get_smart_api()
            _smart_auth_ts = now
            log.info("[SmartAPI] session refreshed")
            return smart
        except Exception as e:
            log.warning(f"[SmartAPI] re-auth failed: {e}")
            return None


def _invalidate_smart_on_auth_err(resp: dict):
    """If Angel One returns an auth-failure response, drop the cached session so the
    next call triggers a fresh login instead of hammering with an expired token."""
    global smart
    if not resp:
        return
    if resp.get("status") is False:
        ec = str(resp.get("errorcode", ""))
        if ec in _SMART_AUTH_ERR_CODES:
            log.warning(f"[SmartAPI] auth error {ec} — forcing re-login on next call")
            smart = None


def _build_daily_profile_with_smart(smart, symbol_token, exchange, date, tick_size, symbol, use_cache=True):
    """
    Core profile builder — accepts a pre-authenticated SmartAPI session.
    Called by both the daily endpoint and multi-day (to avoid re-auth per day).
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

    conn = get_conn()
    if use_cache:
        cached = get_cached_profile(conn, symbol_token, exchange, date, tick_size)
        if cached:
            conn.close()
            log.info(f"📂 Profile cache hit: {symbol_token}/{date}")
            return cached
    conn.close()

    from_dt = f"{date} 09:15"
    to_dt   = f"{date} 15:30"

    df = fetch_candles(smart, symbol_token, exchange, "ONE_MINUTE", from_dt, to_dt)
    if df.empty and exchange == "NSE":
        try:
            fut_token = im.get_nifty_futures_token()
            df = fetch_candles(smart, fut_token, "NFO", "ONE_MINUTE", from_dt, to_dt)
            if not df.empty:
                symbol_token, exchange = fut_token, "NFO"
        except Exception as fe:
            log.debug(f"NFO fallback failed: {fe}")

    if df.empty:
        return {"error": f"No candle data available for {symbol_token}/{exchange} on {date}"}

    profile = build_profile(df, tick_size=tick_size, symbol=symbol, date=date)

    if date != now_ist.strftime("%Y-%m-%d"):
        conn = get_conn()
        upsert_profile(conn, symbol_token, exchange, date, tick_size, profile)
        conn.close()

    return profile


@app.get("/market-profile/daily")
def market_profile_daily(
    symbol_token: str = "26000",
    exchange: str = "NSE",
    date: str = "",
    tick_size: float = TICK_SIZE_INDEX,
    symbol: str = "NIFTY",
    use_cache: bool = True,
):
    """
    Full TPO + volume profile for a given symbol and date.
    date: YYYY-MM-DD (defaults to today IST)
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    if not date:
        date = now_ist.strftime("%Y-%m-%d")

    smart = _get_smart()
    if not smart:
        return {"error": "SmartAPI authentication failed"}

    return _build_daily_profile_with_smart(smart, symbol_token, exchange, date, tick_size, symbol, use_cache)


@app.get("/market-profile/live")
def market_profile_live(
    symbol_token: str = "26000",
    exchange: str = "NSE",
    tick_size: float = TICK_SIZE_INDEX,
    symbol: str = "NIFTY",
):
    """
    Intraday profile for today — built from candles fetched up to the current minute.
    Never cached (always fresh).
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    date    = now_ist.strftime("%Y-%m-%d")
    to_dt   = now_ist.strftime("%Y-%m-%d %H:%M")

    smart = _get_smart()
    if not smart:
        return {"error": "SmartAPI authentication failed"}

    df = fetch_candles(smart, symbol_token, exchange, "ONE_MINUTE",
                       f"{date} 09:15", to_dt, use_cache=False)
    if df.empty and exchange == "NSE":
        try:
            fut_token = im.get_nifty_futures_token()
            df = fetch_candles(smart, fut_token, "NFO", "ONE_MINUTE",
                               f"{date} 09:15", to_dt, use_cache=False)
        except Exception:
            pass

    if df.empty:
        return {"error": "No intraday data yet"}

    return build_profile(df, tick_size=tick_size, symbol=symbol, date=date)


@app.get("/market-profile/levels")
def market_profile_levels(
    symbol_token: str = "26000",
    exchange: str = "NSE",
    date: str = "",
    tick_size: float = TICK_SIZE_INDEX,
    symbol: str = "NIFTY",
):
    """
    Key levels only — POC, VAH, VAL, IB High/Low, Naked POCs.
    Lighter response than /daily (no full histogram).
    """
    profile = market_profile_daily(symbol_token, exchange, date, tick_size, symbol)
    if "error" in profile:
        return profile
    return {
        "symbol":       profile["symbol"],
        "date":         profile["date"],
        "poc":          profile["poc"],
        "vah":          profile["vah"],
        "val":          profile["val"],
        "va_width":     profile["va_width"],
        "ib_high":      profile["ib_high"],
        "ib_low":       profile["ib_low"],
        "session_high": profile["session_high"],
        "session_low":  profile["session_low"],
        "poor_high":    profile["poor_high"],
        "poor_low":     profile["poor_low"],
        "naked_pocs":   profile["naked_pocs"],
        "tpo_count":    profile["tpo_count"],
    }


@app.get("/market-profile/multi-day")
def market_profile_multi_day(
    symbol_token: str = "26000",
    exchange: str = "NSE",
    days: int = 5,
    tick_size: float = TICK_SIZE_INDEX,
    symbol: str = "NIFTY",
):
    """
    Composite profile across the last N trading days.
    Merges TPO and volume histograms; computes combined POC and Value Area.
    Also returns per-day key levels for comparison.
    """
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    smart = _get_smart()
    if not smart:
        return {"error": "SmartAPI authentication failed"}

    profiles = []
    per_day  = []
    d = now_ist.date()
    max_lookback = days * 4 + 10   # guard against infinite loop on public holidays
    steps = 0

    while len(profiles) < days and steps < max_lookback:
        d -= timedelta(days=1)
        steps += 1
        if d.weekday() >= 5:   # skip weekends
            continue
        date_str = d.strftime("%Y-%m-%d")
        p = _build_daily_profile_with_smart(smart, symbol_token, exchange, date_str, tick_size, symbol)
        if "error" not in p and p.get("tpo_count", 0) > 0:
            profiles.append(p)
            per_day.append({
                "date":     date_str,
                "poc":      p["poc"],  "vah":    p["vah"],    "val":    p["val"],
                "ib_high":  p.get("ib_high"), "ib_low": p.get("ib_low"),
                "va_width": p.get("va_width"),
                "poor_high": p.get("poor_high"), "poor_low": p.get("poor_low"),
                "session_high": p.get("session_high"), "session_low": p.get("session_low"),
            })

    if not profiles:
        return {"error": "No profile data available for the requested range"}

    # Merge histograms
    merged_tpo: dict = {}
    merged_vol: dict = {}
    for p in profiles:
        for price_str, letters in p["tpo_profile"].items():
            price = float(price_str)
            merged_tpo[price] = merged_tpo.get(price, []) + letters
        for price_str, vol in p["volume_profile"].items():
            price = float(price_str)
            merged_vol[price] = merged_vol.get(price, 0) + vol

    sorted_prices = sorted(merged_tpo.keys())
    poc = max(merged_tpo, key=lambda p: len(merged_tpo[p]))
    total_tpos = sum(len(v) for v in merged_tpo.values())
    va_target = math.ceil(total_tpos * VALUE_AREA_PCT)
    vah, val = _calc_value_area(merged_tpo, sorted_prices, poc, va_target)

    return {
        "symbol":         symbol,
        "days":           len(profiles),
        "tpo_profile":    {round(k, 2): v for k, v in merged_tpo.items()},
        "volume_profile": {round(k, 2): v for k, v in merged_vol.items()},
        "poc":            round(poc, 2),
        "vah":            round(vah, 2),
        "val":            round(val, 2),
        "tpo_count":      total_tpos,
        "per_day":        per_day,
    }


@app.get("/price")
def get_live_price():
    """Live NIFTY spot price from in-memory market state."""
    spot = market_state.get(SPOT_TOKEN)
    if spot and spot.get("price"):
        return {"price": round(spot["price"], 2)}
    return {"price": None}


# ══════════════════════════════════════════════════════════════════════════════
# S1 Intraday Strategy Monitor
# ══════════════════════════════════════════════════════════════════════════════

def _s1_monitor_state() -> dict:
    """
    Real-time S1 intraday setup monitor
    Returns current conditions for NIFTY OR breakout + EMA cross + RSI confirmation
    """
    from core.s1_monitor import S1StrategyMonitor
    import yfinance as yf

    try:
        from core.indicators.ema import calculate_ema
        from core.indicators.rsi import calculate_rsi

        IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
        today_date = _dt.datetime.now(IST).date()

        # Fetch 5 days of 5-min data so Wilder RSI has enough history to converge.
        # (RSI seeded on only today's ~35 candles diverges from TradingView by 5–10 pts.)
        ticker = yf.Ticker("^NSEI")
        df_raw = ticker.history(period="5d", interval="5m")
        if df_raw.empty:
            return {"error": "No 5-min data available", "status": "offline"}

        df_raw.index = df_raw.index.tz_convert("Asia/Kolkata")
        df_raw = df_raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df_raw.columns = ['open', 'high', 'low', 'close', 'volume']

        # All 5 days filtered to trading hours — used only for RSI warm-up
        df_all = df_raw.between_time("09:15", "15:30")

        # Today's candles only — used for OR formation, EMA, chart, and price logic
        df_today = df_all[df_all.index.date == today_date]

        if df_today.empty:
            return {"error": "Market hours data not available", "status": "offline"}

        # Pre-compute RSI on full 5-day series so Wilder's smoothing is fully settled
        rsi_full = calculate_rsi(df_all['close'], 14)
        rsi_today_vals = rsi_full[rsi_full.index.date == today_date]
        latest_rsi_raw = float(rsi_full.iloc[-1]) if len(rsi_full) > 0 else None
        rsi_override = latest_rsi_raw if latest_rsi_raw is not None and not math.isnan(latest_rsi_raw) else None

        # Get live price
        spot = market_state.get(SPOT_TOKEN)
        nifty_price = spot.get("price") if spot else None

        if nifty_price is None:
            return {"error": "NIFTY price unavailable", "status": "offline"}

        # Fetch India VIX
        try:
            vix_ticker = yf.Ticker("^INDIAVIX")
            vix_hist = vix_ticker.history(period="1d", interval="1m")
            india_vix = float(vix_hist['Close'].iloc[-1]) if not vix_hist.empty else None
        except:
            india_vix = None

        # Run S1 monitor — today's candles for OR/EMA/price, rsi_override from 5-day history
        s1_monitor = S1StrategyMonitor()
        result = s1_monitor.check_s1_setup(
            nifty_price=nifty_price,
            candles=df_today,
            vix=india_vix or 20,
            current_time=datetime.now(IST),
            rsi_override=rsi_override,
        )

        result['status'] = 'online'
        result['nifty_price'] = round(nifty_price, 2)
        result['india_vix'] = round(india_vix, 2) if india_vix else None
        result['timestamp'] = datetime.now().isoformat()
        result['candles_count'] = len(df_today)

        # Directional bias (visible before full signal fires)
        ind = result.get('indicators', {})
        _ema9  = ind.get('ema9',  0) or 0
        _ema21 = ind.get('ema21', 0) or 0
        _rsi   = rsi_override or ind.get('rsi', 50) or 50
        _or_h  = ind.get('or_high', 0) or 0
        _or_l  = ind.get('or_low',  0) or 0
        ce_pts = int(_ema9 > _ema21) + int(_rsi > 55) + int(_or_h > 0 and nifty_price > _or_h)
        pe_pts = int(_ema9 < _ema21) + int(_rsi < 45) + int(_or_l > 0 and nifty_price < _or_l)
        if ce_pts >= 2 and ce_pts > pe_pts:
            _dir = 'CE'
        elif pe_pts >= 2 and pe_pts > ce_pts:
            _dir = 'PE'
        else:
            _dir = None
        result['direction'] = _dir
        result['direction_scores'] = {'ce': ce_pts, 'pe': pe_pts}

        # ────────────────────────────────────────────────────────────────────
        # Generate chart data (candles + indicators for lightweight-charts)
        # ────────────────────────────────────────────────────────────────────
        try:
            close_today = df_today['close']
            ema9_series  = calculate_ema(close_today, 9)
            ema21_series = calculate_ema(close_today, 21)
            # Use today's slice of the already-computed 5-day RSI series
            rsi_vals = rsi_today_vals.values

            chart_candles, chart_ema9, chart_ema21, chart_rsi = [], [], [], []

            IST_OFFSET = 19800  # +5h30m in seconds — shifts UTC epoch to IST for chart display

            for idx, (ts, row) in enumerate(df_today.iterrows()):
                t = int(ts.timestamp()) + IST_OFFSET

                chart_candles.append({
                    'time': t,
                    'open':  round(float(row['open']),  2),
                    'high':  round(float(row['high']),  2),
                    'low':   round(float(row['low']),   2),
                    'close': round(float(row['close']), 2),
                })

                if idx < len(ema9_series):
                    chart_ema9.append({'time': t, 'value': round(float(ema9_series.iloc[idx]), 2)})

                if idx < len(ema21_series):
                    chart_ema21.append({'time': t, 'value': round(float(ema21_series.iloc[idx]), 2)})

                if idx < len(rsi_vals):
                    rv = float(rsi_vals[idx])
                    if not math.isnan(rv):
                        chart_rsi.append({'time': t, 'value': round(rv, 2)})

            result['chart_data'] = {
                'candles':     chart_candles,
                'ema9':        chart_ema9,
                'ema21':       chart_ema21,
                'rsi':         chart_rsi,
                'latest_ema9':  round(float(ema9_series.iloc[-1]),  2) if len(ema9_series)  > 0 else None,
                'latest_ema21': round(float(ema21_series.iloc[-1]), 2) if len(ema21_series) > 0 else None,
                'latest_rsi':   round(rsi_override, 2) if rsi_override is not None else None,
            }

        except Exception as e:
            print(f"[S1 Monitor] Chart data error: {e}")
            result['chart_data'] = None

        return result

    except Exception as e:
        print(f"[S1 Monitor] Error: {e}")
        return {"error": str(e), "status": "error"}


@app.get("/s1-monitor")
def get_s1_monitor():
    """S1 intraday strategy monitor — real-time setup conditions"""
    return _s1_monitor_state()


@app.get("/stock-monitor")
def get_stock_monitor(symbol: str = "RELIANCE"):
    """Stock options monitor — S1 strategy adapted for individual F&O stocks"""
    from core.stock_monitor import StockOptionsMonitor
    import yfinance as yf

    import math

    def _f(v):
        """float → JSON-safe rounded value; NaN/Inf → None."""
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
        except Exception:
            return None

    symbol = symbol.upper().strip()

    try:
        ticker = yf.Ticker(f"{symbol}.NS")
        df_5m = ticker.history(period="2d", interval="5m")
        if df_5m.empty:
            return {"error": f"No data for {symbol}", "status": "offline"}

        df_5m.index = df_5m.index.tz_convert("Asia/Kolkata")
        df_5m = df_5m[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df_5m = df_5m.between_time("09:15", "15:30")
        df_5m.columns = ['open', 'high', 'low', 'close', 'volume']

        if df_5m.empty:
            return {"error": "Market hours data not available", "status": "offline"}

        # Use only the most recent trading session (handles pre-market / post-market)
        last_date = df_5m.index[-1].date()
        df_5m = df_5m[df_5m.index.date == last_date]

        # Live price — fast_info.last_price can be NaN; always fall back to last candle
        price = float(df_5m['close'].iloc[-1])
        try:
            lp = float(getattr(ticker.fast_info, 'last_price', None) or 0)
            if lp > 0 and not math.isnan(lp):
                price = lp
        except Exception:
            pass

        monitor = StockOptionsMonitor(symbol)
        result = monitor.check_setup(price=price, candles=df_5m, current_time=datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))))

        result['status'] = 'online'
        result['price'] = _f(price)
        result['symbol'] = symbol
        result['timestamp'] = datetime.now().isoformat()
        result['candles_count'] = len(df_5m)

        # Sanitize indicator floats so JSON serialisation never sees NaN
        ind = result.get('indicators', {})
        for k in list(ind.keys()):
            if isinstance(ind[k], float):
                ind[k] = _f(ind[k])

        # Chart data
        try:
            from core.indicators.ema import calculate_ema
            from core.indicators.rsi import calculate_rsi

            close = df_5m['close']
            ema9_s = calculate_ema(close, 9)
            ema21_s = calculate_ema(close, 21)
            rsi_s = calculate_rsi(close, 14)

            chart_candles, chart_ema9, chart_ema21, chart_rsi = [], [], [], []

            for idx, (ts, row) in enumerate(df_5m.iterrows()):
                t = int(ts.timestamp())
                chart_candles.append({'time': t, 'open': _f(row['open']),
                                       'high': _f(row['high']),
                                       'low': _f(row['low']),
                                       'close': _f(row['close'])})
                v9 = _f(ema9_s.iloc[idx]) if idx < len(ema9_s) else None
                v21 = _f(ema21_s.iloc[idx]) if idx < len(ema21_s) else None
                vr = _f(rsi_s.iloc[idx]) if idx < len(rsi_s) else None
                if v9 is not None:
                    chart_ema9.append({'time': t, 'value': v9})
                if v21 is not None:
                    chart_ema21.append({'time': t, 'value': v21})
                if vr is not None:
                    chart_rsi.append({'time': t, 'value': vr})

            result['chart_data'] = {
                'candles': chart_candles, 'ema9': chart_ema9,
                'ema21': chart_ema21, 'rsi': chart_rsi,
                'latest_ema9': _f(ema9_s.iloc[-1]) if len(ema9_s) > 0 else None,
                'latest_ema21': _f(ema21_s.iloc[-1]) if len(ema21_s) > 0 else None,
                'latest_rsi': _f(rsi_s.iloc[-1]) if len(rsi_s) > 0 else None,
            }
        except Exception as e:
            print(f"[StockMonitor] Chart error: {e}")
            result['chart_data'] = None

        return result

    except Exception as e:
        print(f"[StockMonitor] Error: {e}")
        return {"error": str(e), "status": "error"}


# ══════════════════════════════════════════════════════════════════════════════
# EMA + MACD + VWAP Scenario Endpoint
# ══════════════════════════════════════════════════════════════════════════════

def _ema_scenario_sync(mode: str) -> dict:
    """
    Synchronous worker — runs in thread pool so it doesn't block the event loop.
    mode = "sim" → synthetic textbook data
    mode = "live" → yfinance ^NSEI real candles
    """
    from core.analysis.bias       import check_1h_bias
    from core.analysis.setup      import check_15m_setup
    from core.analysis.entry      import check_5m_entry
    from core.analysis.trade_plan import calculate_trade_plan

    if mode == "sim":
        from data.generate import generate_all, SCENARIO
        data = generate_all()
        df_1h, df_15m, df_5m = data["1h"], data["15m"], data["5m"]
        sim_scenario = SCENARIO
    else:
        import yfinance as yf

        def _fetch(period: str, interval: str):
            df = yf.Ticker("^NSEI").history(period=period, interval=interval)
            if df.empty:
                return df
            df.index = df.index.tz_convert("Asia/Kolkata")
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            return df.between_time("09:15", "15:30")

        df_1h  = _fetch("5d", "60m").tail(30)
        df_15m = _fetch("5d", "15m").tail(52)
        df_5m  = _fetch("1d",  "5m")
        sim_scenario = None

        if df_1h.empty or df_15m.empty or df_5m.empty:
            return {"error": "No market data available (pre-market or market closed)", "mode": mode}

    bias  = check_1h_bias(df_1h)
    setup = check_15m_setup(df_15m)
    entry = check_5m_entry(df_5m)

    if mode == "sim" and sim_scenario:
        plan = calculate_trade_plan(
            sim_scenario["entry"], sim_scenario["stop"],
            sim_scenario["target1"], sim_scenario["target2"],
        )
    elif entry["entry_triggered"] and entry["entry_price"]:
        ep   = entry["entry_price"]
        e9   = entry.get("ema9_at_entry") or (ep - 70)
        stop = round(e9 - 20, 2)
        risk = round(ep - stop, 2)
        plan = calculate_trade_plan(ep, stop, round(ep + 2.0 * risk, 2), round(ep + 3.7 * risk, 2))
    else:
        plan = calculate_trade_plan(0.0, 0.0, 0.0, 0.0)

    missing = []
    if not bias["all_conditions_met"]:  missing.append("1H Bias")
    if not setup["setup_valid"]:        missing.append("15m Setup")
    if not entry["entry_triggered"]:    missing.append("5m Entry")

    return {
        "mode":    mode,
        "bias":    bias,
        "setup":   setup,
        "entry":   entry,
        "plan":    plan,
        "summary": {"all_ok": len(missing) == 0, "missing": missing},
    }


@app.get("/ema-scenario")
async def ema_scenario(mode: str = "sim"):
    """
    Run EMA 9/21 + MACD + VWAP intraday scenario analysis.
    mode=sim  → synthetic textbook data (always works, no market hours needed)
    mode=live → yfinance ^NSEI real candles (requires market to be open or recent data)
    """
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _ema_scenario_sync, mode)
        return result
    except Exception as e:
        log.error(f"EMA scenario error ({mode}): {e}")
        return {"error": str(e), "mode": mode}


# ─── EMA/MACD/VWAP backtest ────────────────────────────────────────────────────
def _ema_backtest_sync(days: int = 20) -> dict:
    import yfinance as yf
    import pandas as pd
    from core.analysis.bias import check_1h_bias
    from core.analysis.setup import check_15m_setup
    from core.analysis.entry import check_5m_entry

    days = min(max(days, 5), 55)

    def _fetch(period: str, interval: str) -> pd.DataFrame:
        df = yf.Ticker("^NSEI").history(period=period, interval=interval)
        if df.empty:
            return df
        df.index = df.index.tz_convert("Asia/Kolkata")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df.between_time("09:15", "15:30")

    period = f"{min(days + 10, 59)}d"
    df_1h_all  = _fetch(period, "60m")
    df_15m_all = _fetch(period, "15m")
    df_5m_all  = _fetch(period, "5m")

    if df_1h_all.empty or df_15m_all.empty or df_5m_all.empty:
        return {"error": "No market data available", "days_tested": 0}

    all_dates  = sorted(df_5m_all.index.normalize().unique())
    test_dates = all_dates[-days:]

    results                  = []
    wins = losses = no_setup = no_entry = 0

    for date in test_dates:
        date_str = str(date.date())

        # ── 1H bias: use PREVIOUS days only (pre-session assessment) ──────────
        # Bug fix: using today's data pushed the 3-candle EMA slope check into
        # today's volatile session and pulled the multi-day VWAP off-centre.
        ctx_1h   = df_1h_all[df_1h_all.index.normalize() < date].tail(30)

        # Previous-day 15m context for EMA/MACD warmup on intra-day scans
        prev_15m = df_15m_all[df_15m_all.index.normalize() < date].tail(40)

        # Today's candles only
        day_15m  = df_15m_all[df_15m_all.index.normalize() == date]
        day_5m   = df_5m_all[df_5m_all.index.normalize() == date]

        if len(ctx_1h) < 5 or len(prev_15m) < 10 or len(day_15m) < 6 or len(day_5m) < 10:
            results.append({"date": date_str, "outcome": "SKIP", "reason": "insufficient_data"})
            continue

        bias = check_1h_bias(ctx_1h)

        # Backtest uses EMA stack only as the bias gate.
        # all_conditions_met is too strict for choppy recovery markets — a single
        # sideways 1H candle breaks the monotonic-slope check and MACD can lag
        # the actual price recovery by several days.
        if not bias["ema_stacked"]:
            no_setup += 1
            results.append({
                "date":    date_str,
                "outcome": "NO_SETUP",
                "bias":    bias["bias"],
                "reason":  "no_1h_bias",
            })
            continue

        # ── 15m setup: EMA state check at session open ────────────────────────
        # check_15m_setup looks for a crossover EVENT in the last 3 candles.
        # In a multi-day recovery trend EMA9 already crossed above EMA21 days
        # ago — no new crossover fires, so every continuation day shows NO_SETUP.
        # Fix: just confirm EMA9 > EMA21 state at today's open (trend intact).
        morning_ctx = pd.concat([prev_15m, day_15m.iloc[:3]])
        ema9_15m    = morning_ctx["Close"].ewm(span=9,  adjust=False).mean()
        ema21_15m   = morning_ctx["Close"].ewm(span=21, adjust=False).mean()

        if float(ema9_15m.iloc[-1]) <= float(ema21_15m.iloc[-1]):
            no_setup += 1
            results.append({
                "date":    date_str,
                "outcome": "NO_SETUP",
                "bias":    bias["bias"],
                "reason":  "no_15m_setup",
            })
            continue

        scan_start_5m = 8

        entry_idx     = None
        entry_price   = None
        ema9_at_entry = None

        for i in range(scan_start_5m, len(day_5m)):
            window = day_5m.iloc[:i + 1]
            e = check_5m_entry(window)
            if e["entry_triggered"] and e["entry_candle_idx"] == len(window) - 1:
                entry_idx     = i
                entry_price   = e["entry_price"]
                ema9_at_entry = e.get("ema9_at_entry") or (entry_price - 70)
                break

        if entry_idx is None:
            no_entry += 1
            results.append({"date": date_str, "outcome": "NO_ENTRY", "bias": bias["bias"]})
            continue

        stop = round(ema9_at_entry - 20, 2)
        risk = round(entry_price - stop, 2)
        if risk <= 0:
            no_entry += 1
            results.append({"date": date_str, "outcome": "NO_ENTRY", "reason": "invalid_risk"})
            continue

        t1 = round(entry_price + 2.0 * risk, 2)

        # Check remaining candles for T1 or stop hit — first hit wins
        remaining  = day_5m.iloc[entry_idx + 1:]
        outcome    = "OPEN"
        exit_price = None

        for _, candle in remaining.iterrows():
            if float(candle["High"]) >= t1:
                outcome    = "WIN"
                exit_price = t1
                break
            if float(candle["Low"]) <= stop:
                outcome    = "LOSS"
                exit_price = stop
                break

        if outcome == "OPEN":
            exit_price = float(day_5m["Close"].iloc[-1])
            outcome    = "WIN" if exit_price > entry_price else "LOSS"

        pnl = round(exit_price - entry_price, 2)
        if outcome == "WIN":
            wins += 1
        else:
            losses += 1

        results.append({
            "date":        date_str,
            "outcome":     outcome,
            "entry":       entry_price,
            "stop":        stop,
            "t1":          t1,
            "exit":        exit_price,
            "pnl_pts":     pnl,
            "bias":        bias["bias"],
            "setup_valid": True,
        })

    total_trades = wins + losses
    win_pnls     = [r["pnl_pts"] for r in results if r.get("outcome") == "WIN"]
    loss_pnls    = [r["pnl_pts"] for r in results if r.get("outcome") == "LOSS"]

    return {
        "days_tested":   len(test_dates),
        "total_trades":  total_trades,
        "wins":          wins,
        "losses":        losses,
        "no_setup":      no_setup,
        "no_entry":      no_entry,
        "win_rate":      round(wins / total_trades * 100, 1) if total_trades > 0 else 0.0,
        "total_pnl_pts": round(sum(win_pnls) + sum(loss_pnls), 2),
        "avg_win":       round(sum(win_pnls)  / wins,   2) if wins   > 0 else 0.0,
        "avg_loss":      round(sum(loss_pnls) / losses, 2) if losses > 0 else 0.0,
        "results":       results,
    }


@app.get("/ema-scenario/backtest")
async def ema_scenario_backtest(days: int = 20):
    """
    Back-test EMA+MACD+VWAP over last N trading days (max 55).
    Bulk yfinance fetch — allow up to 60s for large day counts.
    """
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _ema_backtest_sync, days)
        return result
    except Exception as e:
        log.error(f"EMA backtest error: {e}")
        return {"error": str(e), "days_tested": 0}


# ══════════════════════════════════════════════════════════════════════════════
# Indicators Snapshot — VWAP · EMA 9/21 · MACD · RSI from today's 5-min candles
# ══════════════════════════════════════════════════════════════════════════════

def _safe_float(v, fallback=None):
    """Return float v unless it is NaN/inf — returns fallback instead."""
    try:
        f = float(v)
        return fallback if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return fallback


def _sanitize_floats(obj):
    """Recursively replace NaN/inf in any dict/list so FastAPI can JSON-encode it."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _indicators_snapshot_sync() -> dict:
    import yfinance as yf
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

    df = yf.Ticker("^NSEI").history(period="1d", interval="5m")
    df = df.dropna()
    if len(df) < 15:
        return {"error": "Not enough candle data — market may be closed"}

    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # VWAP — guard against zero-volume periods (pre/post market)
    typical   = (high + low + close) / 3
    total_vol = float(vol.cumsum().iloc[-1])
    vwap_val  = float((typical * vol).cumsum().iloc[-1] / total_vol) if total_vol > 0 else float(close.mean())
    spot      = float(close.iloc[-1])
    vwap_diff     = round(spot - vwap_val, 2)
    vwap_diff_pct = round(abs(vwap_diff) / vwap_val * 100, 2) if vwap_val else 0.0
    vwap_signal   = "bullish" if spot > vwap_val else "bearish"

    # EMA 9 / 21
    ema9  = close.ewm(span=9,  adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    e9, e21      = float(ema9.iloc[-1]), float(ema21.iloc[-1])
    pe9, pe21    = float(ema9.iloc[-2]), float(ema21.iloc[-2])
    ema_diff     = round(e9 - e21, 2)
    if e9 > e21:
        ema_signal = "bullish" if pe9 >= pe21 else "recovering"
    else:
        ema_signal = "bearish" if pe9 <= pe21 else "weakening"

    # MACD (12, 26, 9)
    ema12      = close.ewm(span=12, adjust=False).mean()
    ema26      = close.ewm(span=26, adjust=False).mean()
    macd_line  = ema12 - ema26
    sig_line   = macd_line.ewm(span=9, adjust=False).mean()
    hist_line  = macd_line - sig_line
    hist_val   = round(float(hist_line.iloc[-1]), 2)
    prev_hist  = float(hist_line.iloc[-2])
    if hist_val >= 0:
        macd_signal = "bullish" if hist_val >= prev_hist else "weakening"
    else:
        macd_signal = "bearish" if hist_val <= prev_hist else "recovering"

    # RSI (14) — guard against zero/NaN loss (all-gain candles produce division by zero)
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    g_val = float(gain.iloc[-1])
    l_val = float(loss.iloc[-1])
    if l_val > 0 and not math.isnan(l_val):
        rsi_val = round(100 - 100 / (1 + g_val / l_val), 1)
    elif g_val > 0:
        rsi_val = 100.0   # pure bull run — no down candles in window
    else:
        rsi_val = 50.0    # flat/no data — neutral fallback
    if rsi_val >= 70:
        rsi_signal = "overbought"
    elif rsi_val <= 30:
        rsi_signal = "oversold"
    elif rsi_val > 55:
        rsi_signal = "bullish"
    elif rsi_val < 45:
        rsi_signal = "bearish"
    else:
        rsi_signal = "neutral"

    return _sanitize_floats({
        "vwap": {
            "value":    round(vwap_val, 2),
            "diff":     vwap_diff,
            "diff_pct": str(vwap_diff_pct),
            "signal":   vwap_signal,
        },
        "ema": {
            "ema9":   round(e9, 2),
            "ema21":  round(e21, 2),
            "diff":   ema_diff,
            "signal": ema_signal,
        },
        "macd": {
            "macd":        str(_safe_float(macd_line.iloc[-1], 0.0)),
            "signal_line": str(_safe_float(sig_line.iloc[-1],  0.0)),
            "histogram":   str(hist_val),
            "signal":      macd_signal,
        },
        "rsi": {
            "value":  rsi_val,
            "signal": rsi_signal,
        },
        "candles": len(df),
        "as_of":   now_ist.strftime("%H:%M"),
    })


@app.get("/indicators/snapshot")
async def indicators_snapshot():
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _indicators_snapshot_sync)
        return result
    except Exception as e:
        log.error(f"[INDICATORS] snapshot error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# VWAP Quick — lightweight VWAP position for NIFTY or BANKNIFTY
# ══════════════════════════════════════════════════════════════════════════════

def _vwap_quick_sync(symbol: str) -> dict:
    import yfinance as yf
    _INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
    _PROXY = {"NIFTY": "NIFTYBEES.NS", "BANKNIFTY": "BANKBEES.NS"}
    sym_up = symbol.upper()
    ticker = _INDEX.get(sym_up, "^NSEI")
    df = yf.Ticker(ticker).history(period="1d", interval="5m").dropna()
    if len(df) < 5:
        return {"error": "Insufficient candle data — market may be closed"}
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    # Index tickers return zero volume on yfinance — use ETF proxy
    if float(vol.sum()) < 10 and sym_up in _PROXY:
        try:
            pf = yf.Ticker(_PROXY[sym_up]).history(period="1d", interval="5m").dropna()
            if not pf.empty:
                vol = pf["Volume"].reindex(df.index, fill_value=0)
        except Exception:
            pass
    typical   = (high + low + close) / 3
    total_vol = float(vol.sum())
    spot      = float(close.iloc[-1])
    vwap_val  = round(float((typical * vol).sum() / total_vol), 2) if total_vol > 0 else round(float(typical.mean()), 2)
    diff_pct  = (spot - vwap_val) / vwap_val * 100 if vwap_val else 0
    if abs(diff_pct) < 0.10:
        vwap_pos = "at"
    elif spot > vwap_val:
        vwap_pos = "above"
    else:
        vwap_pos = "below"
    return {"vwap": vwap_val, "spot": round(spot, 2), "vwap_pos": vwap_pos, "diff_pct": round(diff_pct, 2)}


@app.get("/indicators/vwap")
async def indicators_vwap_quick(symbol: str = "NIFTY"):
    """Quick VWAP position check for NIFTY or BANKNIFTY — used by Osprey strategy."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, lambda: _vwap_quick_sync(symbol))
    except Exception as e:
        log.error(f"[VWAP-QUICK] {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Nifty Candles — today's 5-min OHLCV for the chart widget
# ══════════════════════════════════════════════════════════════════════════════

def _nifty_candles_sync() -> dict:
    import yfinance as yf
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    df = yf.Ticker("^NSEI").history(period="1d", interval="5m")
    df = df.dropna()
    if df.empty:
        return {"error": "No candle data — market may be closed"}
    IST_OFFSET = 19800  # +5h30m in seconds — shifts UTC timestamps to IST for chart display
    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time":  int(ts.timestamp()) + IST_OFFSET,
            "open":  round(float(row["Open"]),  2),
            "high":  round(float(row["High"]),  2),
            "low":   round(float(row["Low"]),   2),
            "close": round(float(row["Close"]), 2),
        })
    return {"candles": candles, "count": len(candles), "as_of": now_ist.strftime("%H:%M")}


# ══════════════════════════════════════════════════════════════════════════════
# IV — ATM implied volatility for nearest NIFTY expiry via Angel One
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_iv_sync() -> dict:
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

    # ── Spot price ───────────────────────────────────────────────────────────
    spot = trade_flow_data.get("spot_price") or trade_flow_data.get("nifty_price")
    if not spot:
        try:
            import yfinance as yf
            hist = yf.Ticker("^NSEI").history(period="1d", interval="1m")
            spot = float(hist["Close"].iloc[-1]) if not hist.empty else None
        except Exception:
            pass
    if not spot:
        return {"error": "Could not determine NIFTY spot price"}

    atm_strike = round(spot / 50) * 50

    # ── Load instrument master ───────────────────────────────────────────────
    master_path = os.path.join(os.path.dirname(__file__), "data", "instrument_master.json")
    with open(master_path) as f:
        instruments = json.load(f)

    nifty_opts = [
        i for i in instruments
        if i.get("name", "").upper() == "NIFTY"
        and i.get("exch_seg") == "NFO"
        and i.get("instrumenttype") == "OPTIDX"
    ]
    if not nifty_opts:
        return {"error": "No NIFTY options in instrument master"}

    # ── Nearest expiry ───────────────────────────────────────────────────────
    today = now_ist.date()
    def _parse_exp(s):
        try:    return datetime.strptime(s, "%d%b%Y").date()
        except: return None

    future_expiries = sorted({
        _parse_exp(i["expiry"]) for i in nifty_opts
        if _parse_exp(i["expiry"]) and _parse_exp(i["expiry"]) >= today
    })
    if not future_expiries:
        return {"error": "No upcoming NIFTY expiries found"}

    nearest_exp      = future_expiries[0]
    nearest_exp_str  = nearest_exp.strftime("%d%b%Y").upper()

    # ── Find ATM CE + PE tokens ──────────────────────────────────────────────
    ce_token = pe_token = None
    for i in nifty_opts:
        if _parse_exp(i["expiry"]) != nearest_exp:
            continue
        strike = float(i.get("strike", 0)) / 100
        if abs(strike - atm_strike) < 1:
            sym = i.get("symbol", "")
            if sym.endswith("CE"):
                ce_token = i["token"]
            elif sym.endswith("PE"):
                pe_token = i["token"]
        if ce_token and pe_token:
            break

    if not ce_token or not pe_token:
        return {"error": f"ATM {atm_strike} tokens not found for expiry {nearest_exp_str}"}

    # ── Time to expiry in years ──────────────────────────────────────────────
    from core.options.greeks import implied_volatility as _bs_iv
    T_years = max((nearest_exp - today).days, 1) / 365.0

    # ── Fetch ATM CE + PE via provider ───────────────────────────────────────
    snaps = get_provider().get_option_market_data([str(ce_token), str(pe_token)])

    ce_ltp = pe_ltp = ce_oi = pe_oi = None
    for snap in snaps:
        if snap.token == str(ce_token):
            ce_ltp = snap.ltp if snap.ltp else None
            ce_oi  = snap.open_interest if snap.open_interest else None
        elif snap.token == str(pe_token):
            pe_ltp = snap.ltp if snap.ltp else None
            pe_oi  = snap.open_interest if snap.open_interest else None

    if ce_ltp is None and pe_ltp is None:
        return {"error": "No LTP returned — market may be closed or contracts illiquid"}

    # ── Compute IV via Black-Scholes bisection ───────────────────────────────
    ce_iv = _bs_iv("CE", ce_ltp, spot, atm_strike, T_years) if ce_ltp else None
    pe_iv = _bs_iv("PE", pe_ltp, spot, atm_strike, T_years) if pe_ltp else None

    if ce_iv is None and pe_iv is None:
        return {"error": "IV could not be computed — LTP may be zero or expiry too close"}

    avg_iv = round((ce_iv + pe_iv) / 2, 2) if ce_iv and pe_iv else (ce_iv or pe_iv)
    skew   = round(pe_iv - ce_iv, 2)        if ce_iv and pe_iv else None

    # Status based on avg IV level
    if avg_iv is None:      status = "UNKNOWN"
    elif avg_iv < 12:       status = "CHEAP"
    elif avg_iv < 18:       status = "FAIR"
    elif avg_iv < 25:       status = "ELEVATED"
    else:                   status = "EXPENSIVE"

    # Skew interpretation
    if skew is None:        skew_label = None
    elif skew > 2:          skew_label = "BEARISH"   # PE IV >> CE IV
    elif skew < -2:         skew_label = "BULLISH"   # CE IV >> PE IV
    else:                   skew_label = "NEUTRAL"

    vix     = trade_flow_data.get("india_vix")
    vix_gap = round(avg_iv - vix, 2) if avg_iv and vix else None
    pcr     = round(pe_oi / ce_oi, 2) if ce_oi and pe_oi and ce_oi > 0 else None

    return {
        "spot":        round(spot, 2),
        "atm_strike":  atm_strike,
        "expiry":      nearest_exp_str,
        "ce_iv":       ce_iv,
        "pe_iv":       pe_iv,
        "avg_iv":      avg_iv,
        "skew":        skew,
        "skew_label":  skew_label,
        "ce_ltp":      ce_ltp,
        "pe_ltp":      pe_ltp,
        "ce_oi":       ce_oi,
        "pe_oi":       pe_oi,
        "pcr":         pcr,
        "status":      status,
        "india_vix":   vix,
        "vix_gap":     vix_gap,
        "as_of":       now_ist.strftime("%H:%M"),
    }


@app.get("/fut-oi")
def get_fut_oi():
    """Lightweight endpoint returning NIFTY near-month futures OI + intraday signal."""
    try:
        _ft = im.get_nifty_futures_token()
        if not _ft:
            return {"error": "Futures token unavailable"}
        snaps = get_provider().get_option_market_data([str(_ft)])
        snap  = next((s for s in snaps if s.token == str(_ft)), None)
        if not snap or not snap.open_interest:
            return {"error": "No OI data"}
        _oi_int  = snap.open_interest
        _ltp_val = snap.ltp
        _base_oi = trade_flow_data.get("prev_fut_oi")
        _oi_chg  = (_oi_int - _base_oi) if _base_oi else None
        _prev_c  = (trade_flow_data.get("prev_ohlc") or {}).get("close")
        _price_up = (_ltp_val > _prev_c) if (_ltp_val and _prev_c) else None
        _oi_up    = (_oi_chg > 0)        if _oi_chg is not None else None
        _signal   = None
        if _price_up is not None and _oi_up is not None:
            if   _price_up and _oi_up:      _signal = "long_buildup"
            elif not _price_up and _oi_up:  _signal = "short_buildup"
            elif _price_up and not _oi_up:  _signal = "short_covering"
            else:                           _signal = "long_unwinding"
        return {"oi": _oi_int, "oi_chg": _oi_chg, "signal": _signal,
                "ltp": round(_ltp_val, 2) if _ltp_val else None}
    except Exception as e:
        return {"error": str(e)}


@app.get("/iv")
async def fetch_iv():
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _fetch_iv_sync)
    except Exception as e:
        log.error(f"[IV] error: {e}")
        return {"error": str(e)}


@app.get("/candles")
async def nifty_candles():
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _nifty_candles_sync)
    except Exception as e:
        log.error(f"[CANDLES] error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Market Summary — live quotes for landing-page index cards
# ══════════════════════════════════════════════════════════════════════════════

def _market_summary_sync() -> dict:
    import yfinance as yf
    import datetime as _dt
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)

    _SYMS = {"nifty": "^NSEI", "banknifty": "^NSEBANK", "vix": "^INDIAVIX"}
    result: dict = {"as_of": now_ist.strftime("%H:%M")}

    for key, sym in _SYMS.items():
        try:
            hist_d  = yf.Ticker(sym).history(period="5d",  interval="1d").dropna()
            hist_5m = yf.Ticker(sym).history(period="1d",  interval="5m").dropna()

            ltp        = round(float(hist_5m["Close"].iloc[-1])  if not hist_5m.empty else float(hist_d["Close"].iloc[-1]), 2)
            prev_close = round(float(hist_d["Close"].iloc[-2])   if len(hist_d) >= 2   else float(hist_d["Close"].iloc[-1]), 2)
            pct        = round((ltp - prev_close) / prev_close * 100, 2)

            spark: list = []
            if not hist_5m.empty:
                closes = hist_5m["Close"].tolist()[-32:]
                lo, hi = min(closes), max(closes)
                rng = hi - lo or 1
                spark = [round((c - lo) / rng, 3) for c in closes]

            result[key] = {"ltp": ltp, "prev": prev_close, "pct": pct, "spark": spark}
        except Exception as ex:
            result[key] = {"error": str(ex)}

    # Market session: weekday 09:15–15:30 IST
    t = now_ist.time()
    import datetime as _dt2
    result["is_open"] = (now_ist.weekday() < 5
                         and _dt2.time(9, 15) <= t <= _dt2.time(15, 30))
    return result


@app.get("/market-summary")
async def market_summary_endpoint():
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _market_summary_sync)
    except Exception as e:
        log.error(f"[MARKET-SUMMARY] error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Sector Spotlight — daily % change for 6 key NSE sector indices
# ══════════════════════════════════════════════════════════════════════════════

_SECTOR_SPOTLIGHT = [
    ("Banking",  "^NSEBANK"),
    ("IT",       "^CNXIT"),
    ("Auto",     "^CNXAUTO"),
    ("Pharma",   "^CNXPHARMA"),
    ("FMCG",     "^CNXFMCG"),
    ("Metal",    "^CNXMETAL"),
]

_sector_spotlight_cache: dict = {}
_sector_spotlight_ts: float = 0.0
_SECTOR_CACHE_TTL = 600  # 10 min


def _sector_spotlight_sync() -> list:
    global _sector_spotlight_cache, _sector_spotlight_ts
    import time as _time
    import yfinance as yf
    import datetime as _dt

    now = _time.time()
    if _sector_spotlight_cache and (now - _sector_spotlight_ts) < _SECTOR_CACHE_TTL:
        return _sector_spotlight_cache

    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    result = []
    for name, sym in _SECTOR_SPOTLIGHT:
        try:
            hist = yf.Ticker(sym).history(period="5d", interval="1d").dropna()
            if len(hist) < 2:
                result.append({"name": name, "pct": 0.0, "ltp": None})
                continue
            ltp  = round(float(hist["Close"].iloc[-1]), 2)
            prev = round(float(hist["Close"].iloc[-2]), 2)
            pct  = round((ltp - prev) / prev * 100, 2)
            result.append({"name": name, "pct": pct, "ltp": ltp})
        except Exception as ex:
            result.append({"name": name, "pct": 0.0, "ltp": None, "error": str(ex)})

    _sector_spotlight_cache = result
    _sector_spotlight_ts = now
    return result


@app.get("/sector-spotlight")
async def sector_spotlight_endpoint():
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _sector_spotlight_sync)
    except Exception as e:
        log.error(f"[SECTOR-SPOTLIGHT] error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# News Feed — Google News RSS for Indian market headlines
# ══════════════════════════════════════════════════════════════════════════════

_news_cache: list = []
_news_cache_ts: float = 0.0
_NEWS_CACHE_TTL = 600  # 10 min

_NEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q=india+stock+market+nifty+NSE"
    "&hl=en-IN&gl=IN&ceid=IN:en"
)


def _news_feed_sync() -> list:
    global _news_cache, _news_cache_ts
    import time as _time
    import requests as _req
    import xml.etree.ElementTree as _ET
    import datetime as _dt
    from email.utils import parsedate_to_datetime

    now = _time.time()
    if _news_cache and (now - _news_cache_ts) < _NEWS_CACHE_TTL:
        return _news_cache

    try:
        resp = _req.get(_NEWS_RSS, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TradeZen/1.0)"
        })
        resp.raise_for_status()
        root = _ET.fromstring(resp.content)
    except Exception as ex:
        log.warning(f"[NEWS] RSS fetch failed: {ex}")
        return _news_cache or []

    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=12)

    items = []
    for item in root.iter("item"):
        def _t(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        pub_raw = _t("pubDate")
        try:
            pub_dt = parsedate_to_datetime(pub_raw)
            # ensure tz-aware for comparison
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=_dt.timezone.utc)
            if pub_dt < cutoff:
                continue  # older than 12 hours — skip
            pub_iso = pub_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pub_iso = ""  # unparseable date — include anyway

        raw_title = _t("title")
        if " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title, source = parts[0].strip(), parts[1].strip()
        else:
            title, source = raw_title, ""

        link = _t("link")
        items.append({"title": title, "source": source, "link": link, "pub": pub_iso})
        if len(items) >= 6:
            break

    _news_cache    = items
    _news_cache_ts = now
    return items


@app.get("/news-feed")
async def news_feed_endpoint():
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _news_feed_sync)
    except Exception as e:
        log.error(f"[NEWS] error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Breakout Screener — on-demand Nifty-500 scan
# ══════════════════════════════════════════════════════════════════════════════
try:
    from screener import run_screener as _run_screener, screener_cache_stats as _screener_cache_stats
    _screener_ok = True
except ImportError as _se:
    log.warning(f"screener module not available: {_se}")
    _screener_ok = False


@app.get("/screener/breakouts")
async def screener_breakouts(category: str = "breakout_1y"):
    if not _screener_ok:
        return {"error": "Screener module unavailable", "stocks": []}
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run_screener, category)
    except Exception as e:
        log.error(f"[SCREENER] error: {e}")
        return {"error": str(e), "stocks": []}


# ── Cache diagnostics endpoint ─────────────────────────────────────────────────
@app.get("/debug/cache")
async def debug_cache():
    """
    Returns a snapshot of all in-process caches and the yfinance disk cache size.
    Use this to monitor memory usage and detect runaway growth.
    """
    import os, sys

    # Swing analyzer cache
    swing_stats: dict = {}
    try:
        from core.swing_analyzer import cache_stats as _swing_cache_stats, _CACHE
        swing_stats = _swing_cache_stats()
        swing_stats["estimated_ram_kb"] = round(
            sum(
                v["data"][0].memory_usage(deep=True).sum()  # true DataFrame footprint
                for k, v in _CACHE.items()
                if k.startswith("__s_") and isinstance(v.get("data"), tuple)
                and hasattr(v["data"][0], "memory_usage")
            ) / 1024, 1
        )
    except Exception as e:
        swing_stats = {"error": str(e)}

    # Screener result cache
    screener_stats: dict = {}
    try:
        screener_stats = _screener_cache_stats() if _screener_ok else {"error": "screener not loaded"}
    except Exception as e:
        screener_stats = {"error": str(e)}

    # yfinance disk cache
    yf_disk: dict = {}
    try:
        import yfinance as yf
        cache_dir = getattr(yf, "cache_path", None) or os.path.join(
            os.environ.get("APPDATA", os.path.expanduser("~")), "py-yfinance"
        )
        if os.path.isdir(cache_dir):
            total = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, files in os.walk(cache_dir)
                for f in files
            )
            yf_disk = {"path": cache_dir, "size_mb": round(total / 1024 / 1024, 2)}
        else:
            yf_disk = {"path": cache_dir, "size_mb": 0, "note": "directory not found"}
    except Exception as e:
        yf_disk = {"error": str(e)}

    return {
        "swing_analyzer": swing_stats,
        "screener":        screener_stats,
        "yfinance_disk":   yf_disk,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Market Psychology Engine — dominance scoring + Supertrend + VWAP per candle
# ══════════════════════════════════════════════════════════════════════════════

from core.indicators.supertrend import compute as _compute_supertrend

_PSYCH_CACHE: dict = {}          # {"{symbol}-{interval}": (unix_ts, result)}
_PSYCH_CACHE_TTL   = 30          # seconds before re-fetching

_YF_SYMBOLS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}

_INTERVAL_MAP = {          # interval → (yf_interval, yf_period)
    "1m":  ("1m",  "1d"),
    "5m":  ("5m",  "1d"),
    "15m": ("15m", "1d"),
}

IST_OFFSET = 19800   # +5h30m in seconds — aligns UTC unix timestamps to IST for chart display


# ── Dominance scoring for one candle ─────────────────────────────────────────

def _psych_dominance(o, h, l, c, v, vwap, vol_ma, st, history):
    """Compute buyer/seller dominance for a single candle. Returns a dict."""
    total_range = (h - l) if h != l else 0.0001
    body        = abs(c - o)
    bullish     = c >= o
    dir_sign    = 1 if bullish else -1

    body_pct    = body / total_range
    close_pos   = (c - l) / total_range          # 0 = close at low, 1 = close at high
    upper_wick  = (h - max(o, c)) / total_range
    lower_wick  = (min(o, c) - l) / total_range
    rel_volume  = (v / vol_ma) if vol_ma > 0 else 1.0

    # VWAP position
    if vwap and vwap > 0:
        vwap_diff = (c - vwap) / vwap * 100
        if   vwap_diff >  0.05: vwap_sign, vwap_pos = 1,  "above"
        elif vwap_diff < -0.05: vwap_sign, vwap_pos = -1, "below"
        else:                   vwap_sign, vwap_pos = 0,  "at"
    else:
        vwap_sign, vwap_pos = 0, "unknown"

    # Supertrend alignment
    st_dir = (st or {}).get("direction", "neutral")
    if   st_dir == "up"   and bullish:  trend_sign = 1
    elif st_dir == "down" and not bullish: trend_sign = -1
    elif st_dir == "neutral":           trend_sign = 0
    else:                               trend_sign = -0.5   # counter-trend

    # Weighted score: -100..+100
    body_score  = body_pct   * dir_sign * 30          # ±30
    close_score = (close_pos * 2 - 1)   * 20          # ±20  (independent of direction)
    vwap_score  = vwap_sign             * 15          # ±15
    trend_score = trend_sign            * 10          # ±10
    # Opposing wick reduces score
    opp_wick    = upper_wick if bullish else lower_wick
    wick_pen    = -dir_sign  * opp_wick * 12          # ±12 penalty

    vol_amp     = max(0.5, min(1.5, 0.6 + rel_volume * 0.45))
    raw         = body_score + close_score + vwap_score + trend_score + wick_pen
    score       = max(-100.0, min(100.0, round(raw * vol_amp, 1)))

    state   = _psych_state(score, body_pct, rel_volume, upper_wick, lower_wick, vwap_pos, st_dir, history)
    insight = _psych_insight(state, vwap_pos, st_dir)

    # Visual pct (0-100) — display only, not exact order flow
    buyer_pct  = round(max(0.0, min(100.0, (score + 100) / 2)), 1)
    seller_pct = round(100.0 - buyer_pct, 1)

    return {
        "score":      score,
        "state":      state,
        "insight":    insight,
        "buyer_pct":  buyer_pct,
        "seller_pct": seller_pct,
        "vwap_pos":   vwap_pos,
        "components": {
            "body_pct":   round(body_pct,   3),
            "close_pos":  round(close_pos,  3),
            "upper_wick": round(upper_wick, 3),
            "lower_wick": round(lower_wick, 3),
            "rel_volume": round(rel_volume, 3),
            "vwap_sign":  vwap_sign,
            "trend_sign": trend_sign,
            "st_dir":     st_dir,
        },
    }


def _psych_state(score, body_pct, rel_vol, upper_wick, lower_wick, vwap_pos, st_dir, history):
    """Classify market state for one candle."""
    # Fake breakout: strong prior move + wick rejection this candle
    if history:
        prev_score = history[-1]["score"]
        if prev_score > 50 and score < 15 and upper_wick > 0.45:
            return "fake_breakout"
        if prev_score < -50 and score > -15 and lower_wick > 0.45:
            return "fake_breakout"

    # Absorption: compressed body on heavy volume
    if body_pct < 0.28 and rel_vol > 1.3:
        return "absorption"

    # Momentum weakening: 3-candle shrinking body pattern during a trend
    if len(history) >= 3:
        comps  = [h["components"]["body_pct"] for h in history[-3:]]
        scores = [h["score"]                  for h in history[-3:]]
        if (comps[-1] < comps[-2] < comps[0] and
                (all(s > 35 for s in scores) or all(s < -35 for s in scores))):
            return "momentum_weakening"

    if   score >=  60: return "buyer_domination"
    elif score <= -60: return "seller_domination"
    elif score >=  30: return "buyer_pressure"
    elif score <= -30: return "seller_pressure"
    return "neutral"


_PSYCH_INSIGHTS = {
    "buyer_domination":   "Strong buyer control — bulls absorbing all supply",
    "seller_domination":  "Strong seller control — bears dominating session",
    "absorption":         "Possible absorption — watch next candle for direction",
    "momentum_weakening": "Momentum weakening — trend losing conviction",
    "fake_breakout":      "Breakout failed — strong wick rejection detected",
    "buyer_pressure":     "Mild buyer pressure — needs volume confirmation",
    "seller_pressure":    "Mild seller pressure — watch for breakdown signal",
    "neutral":            "Low participation — wait for directional signal",
}

def _psych_insight(state, vwap_pos, st_dir):
    """Return context-enriched educational insight string."""
    if vwap_pos == "above" and state == "buyer_domination":
        return "Buyers defending VWAP — bullish session bias confirmed"
    if vwap_pos == "above" and state == "buyer_pressure":
        return "Price holding above VWAP — buyers in slight control"
    if vwap_pos == "below" and state == "seller_domination":
        return "Sellers pressing below VWAP — bearish bias confirmed"
    if vwap_pos == "below" and state == "seller_pressure":
        return "Price below VWAP — sellers maintain slight edge"
    if vwap_pos == "at"    and state in ("buyer_pressure", "buyer_domination"):
        return "Breaking above VWAP — potential bullish momentum shift"
    if vwap_pos == "at"    and state in ("seller_pressure", "seller_domination"):
        return "Failing at VWAP — potential bearish rejection"
    if vwap_pos == "at"    and state == "neutral":
        return "Price at VWAP — indecision zone, wait for breakout direction"
    if st_dir == "up"   and state == "buyer_domination":
        return "Supertrend bullish + strong buyers — trend momentum at peak"
    if st_dir == "down" and state == "seller_domination":
        return "Supertrend bearish + strong sellers — trend momentum at peak"
    if state == "fake_breakout":
        return "Breakout lacks participation — possible reversal trap ahead"
    if state == "absorption":
        return "Absorption at key level — large players positioning quietly"
    return _PSYCH_INSIGHTS.get(state, "Analyzing market structure…")


# ── Full history computation ──────────────────────────────────────────────────

def _psychology_sync(symbol: str, interval: str) -> dict:
    import yfinance as yf
    import pandas as pd
    import time as _time

    symbol   = symbol.upper()
    interval = interval.lower()
    key      = f"{symbol}-{interval}"
    now      = _time.time()

    if key in _PSYCH_CACHE:
        cached_ts, cached_data = _PSYCH_CACHE[key]
        if now - cached_ts < _PSYCH_CACHE_TTL:
            return cached_data

    yf_sym = _YF_SYMBOLS.get(symbol, "^NSEI")
    yf_interval, _ = _INTERVAL_MAP.get(interval, ("5m", "1d"))
    # Fetch multi-day data so Wilder RSI has enough history to converge.
    # 1m: max 7d; 5m/15m: 5d is sufficient (~300 bars for Wilder seed).
    warmup_period = "7d" if yf_interval == "1m" else "5d"

    df_all = yf.Ticker(yf_sym).history(period=warmup_period, interval=yf_interval)
    if df_all.empty:
        return {"error": "No intraday data — market closed or holiday", "candles": [], "market_closed": True}

    try:
        df_all.index = df_all.index.tz_convert("Asia/Kolkata")
    except Exception:
        pass

    df_all = df_all[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # Require today's IST date — reject stale bars from previous sessions / holidays
    now_ist   = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_ist = now_ist.date()

    if df_all.empty or df_all.index[-1].date() != today_ist:
        return {"error": "No trading session today — market closed or holiday", "candles": [], "market_closed": True}

    # Pre-compute RSI on full multi-day series (trading hours) so Wilder is properly seeded
    try:
        from core.indicators.rsi import calculate_rsi as _calc_rsi
        df_session = df_all.between_time("09:15", "15:30")
        _rsi_full  = _calc_rsi(df_session["Close"], 14)
    except Exception:
        _rsi_full = None

    # Today's candles only for OHLCV / VWAP / Supertrend display
    df = df_all[df_all.index.date == today_ist]
    try:
        df = df.between_time("09:15", "15:30")
    except Exception:
        pass

    if df.empty:
        return {"error": "No intraday data — market closed or holiday today", "candles": [], "market_closed": True}

    # yfinance returns Volume=0 for index tickers (^NSEI, ^NSEBANK) on intraday data.
    # Use liquid ETF as volume proxy so VWAP and volume histogram work correctly.
    _VOL_PROXY = {"NIFTY": "NIFTYBEES.NS", "BANKNIFTY": "BANKBEES.NS"}
    vol_proxy = _VOL_PROXY.get(symbol.upper())
    if vol_proxy and (df["Volume"] == 0).all():
        try:
            vdf = yf.Ticker(vol_proxy).history(period=warmup_period, interval=yf_interval)
            if not vdf.empty:
                try:
                    vdf.index = vdf.index.tz_convert("Asia/Kolkata")
                except Exception:
                    pass
                vdf = vdf[["Volume"]].reindex(df.index, method="nearest", tolerance=pd.Timedelta("5min"))
                df["Volume"] = vdf["Volume"].fillna(0).astype(int)
        except Exception:
            pass

    # Intraday VWAP — all intervals now use 1d so simple cumsum is correct
    typical  = (df["High"] + df["Low"] + df["Close"]) / 3
    pv       = typical * df["Volume"]
    df["vwap"] = pv.cumsum() / df["Volume"].cumsum().replace(0, float("nan"))

    # Supertrend
    st_list = _compute_supertrend(df, period=10, multiplier=3.0)

    # 20-period volume moving average
    df["vol_ma"] = df["Volume"].rolling(20, min_periods=1).mean()

    candles_out = []
    history     = []

    for i in range(len(df)):
        row    = df.iloc[i]
        o, h, l, c = float(row.Open), float(row.High), float(row.Low), float(row.Close)
        v      = float(row.Volume)
        vwap   = float(row.vwap)   if not pd.isna(row.vwap)   else None
        vol_ma = float(row.vol_ma) if not pd.isna(row.vol_ma) else v
        st     = st_list[i] if i < len(st_list) else {"value": None, "direction": "neutral"}

        dom = _psych_dominance(o, h, l, c, v, vwap, vol_ma, st, history)

        ts_ist = int(row.name.timestamp()) + IST_OFFSET

        # RSI from pre-warmed 5-day series; None if not yet converged
        rsi_val = None
        if _rsi_full is not None:
            ts_key = row.name
            if ts_key in _rsi_full.index:
                rv = float(_rsi_full.loc[ts_key])
                if not math.isnan(rv):
                    rsi_val = round(rv, 2)

        candle = {
            "time":           ts_ist,
            "open":           round(o, 2),
            "high":           round(h, 2),
            "low":            round(l, 2),
            "close":          round(c, 2),
            "volume":         int(v),
            "vwap":           round(vwap, 2)              if vwap else None,
            "supertrend":     round(float(st["value"]), 2) if st.get("value") else None,
            "supertrend_dir": st["direction"],
            "dominance":      dom,
            "rsi":            rsi_val,
        }
        candles_out.append(candle)
        history.append({"score": dom["score"], "components": dom["components"]})

    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    result  = _sanitize_floats({
        "symbol":   symbol,
        "interval": interval,
        "candles":  candles_out,
        "count":    len(candles_out),
        "as_of":    now_ist.strftime("%H:%M"),
    })

    # Cache normal data for _PSYCH_CACHE_TTL; don't cache market-closed so it clears immediately when market opens
    if not result.get("market_closed"):
        _PSYCH_CACHE[key] = (now, result)
    return result


def _psychology_sync_historical(symbol: str, interval: str, date: str) -> dict:
    """Fetch a specific past session's candle data — same pipeline as live, no caching."""
    import yfinance as yf
    import pandas as pd
    from datetime import datetime as _dt2, timedelta as _td2, date as _date_cls

    symbol   = symbol.upper()
    interval = interval.lower()
    yf_sym   = _YF_SYMBOLS.get(symbol, "^NSEI")
    yf_interval, _ = _INTERVAL_MAP.get(interval, ("5m", "1d"))

    target    = _dt2.strptime(date, "%Y-%m-%d").date()
    today     = _date_cls.today()
    days_back = (today - target).days

    max_days = 7 if yf_interval == "1m" else 59
    if days_back < 0:
        return {"error": f"No data for {date} — date is in the future", "candles": [], "count": 0}
    if days_back > max_days:
        return {"error": f"No data for {date} — exceeds {max_days}-day limit for {interval} data", "candles": [], "count": 0}

    # Use period= instead of start/end — more stable with recent yfinance for intraday intervals
    period_days = min(days_back + 5, max_days)
    df = yf.Ticker(yf_sym).history(period=f"{period_days}d", interval=yf_interval)
    if df.empty:
        return {"error": f"No data for {date} — may be a holiday or weekend", "candles": [], "count": 0}

    try:
        df.index = df.index.tz_convert("Asia/Kolkata")
    except Exception:
        pass

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # Filter to the requested date only
    try:
        df = df[df.index.date == target]
    except Exception:
        df = df[pd.to_datetime(df.index).normalize().date == target]

    if df.empty:
        return {"error": f"No trading session on {date}", "candles": [], "count": 0}

    try:
        df = df.between_time("09:15", "15:30")
    except Exception:
        pass

    if df.empty:
        return {"error": f"No trading session on {date}", "candles": [], "count": 0}

    _VOL_PROXY = {"NIFTY": "NIFTYBEES.NS", "BANKNIFTY": "BANKBEES.NS"}
    vol_proxy = _VOL_PROXY.get(symbol)
    if vol_proxy and (df["Volume"] == 0).all():
        try:
            vdf = yf.Ticker(vol_proxy).history(period=f"{period_days}d", interval=yf_interval)
            if not vdf.empty:
                try:
                    vdf.index = vdf.index.tz_convert("Asia/Kolkata")
                except Exception:
                    pass
                vdf = vdf[vdf.index.date == target]
                vdf = vdf[["Volume"]].reindex(df.index, method="nearest", tolerance=pd.Timedelta("5min"))
                df["Volume"] = vdf["Volume"].fillna(0).astype(int)
        except Exception:
            pass

    typical      = (df["High"] + df["Low"] + df["Close"]) / 3
    pv           = typical * df["Volume"]
    df["vwap"]   = pv.cumsum() / df["Volume"].cumsum().replace(0, float("nan"))
    st_list      = _compute_supertrend(df, period=10, multiplier=3.0)
    df["vol_ma"] = df["Volume"].rolling(20, min_periods=1).mean()

    candles_out, history = [], []
    for i in range(len(df)):
        row    = df.iloc[i]
        o, h, l, c = float(row.Open), float(row.High), float(row.Low), float(row.Close)
        v      = float(row.Volume)
        vwap   = float(row.vwap)   if not pd.isna(row.vwap)   else None
        vol_ma = float(row.vol_ma) if not pd.isna(row.vol_ma) else v
        st     = st_list[i] if i < len(st_list) else {"value": None, "direction": "neutral"}
        dom    = _psych_dominance(o, h, l, c, v, vwap, vol_ma, st, history)
        ts_ist = int(row.name.timestamp()) + IST_OFFSET
        candle = {
            "time": ts_ist, "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2), "volume": int(v),
            "vwap": round(vwap, 2) if vwap else None,
            "supertrend": round(float(st["value"]), 2) if st.get("value") else None,
            "supertrend_dir": st["direction"], "dominance": dom,
        }
        candles_out.append(candle)
        history.append({"score": dom["score"], "components": dom["components"]})

    return _sanitize_floats({
        "symbol": symbol, "interval": interval, "date": date,
        "candles": candles_out, "count": len(candles_out), "as_of": date,
    })


@app.get("/psychology/candles")
async def psychology_candles(symbol: str = "NIFTY", interval: str = "5m", date: str = None):
    """Full candle history with VWAP, Supertrend and dominance scores.
    Pass ?date=YYYY-MM-DD for a specific historical session (up to 60 days back for 5m/15m, 7 days for 1m).
    """
    loop = asyncio.get_event_loop()
    try:
        if date:
            result = await loop.run_in_executor(None, _psychology_sync_historical, symbol, interval, date)
        else:
            result = await loop.run_in_executor(None, _psychology_sync, symbol, interval)
        return result
    except Exception as e:
        log.error(f"Psychology candles error ({symbol}/{interval}): {e}")
        return {"error": str(e), "candles": []}


@app.get("/psychology/tick")
async def psychology_tick(symbol: str = "NIFTY", interval: str = "5m"):
    """Latest candle + dominance — polled every ~5s by the live panel."""
    loop = asyncio.get_event_loop()
    try:
        full = await loop.run_in_executor(None, _psychology_sync, symbol, interval)
        if full.get("error") or not full.get("candles"):
            return full
        return {
            "symbol":   full["symbol"],
            "interval": full["interval"],
            "as_of":    full["as_of"],
            "candle":   full["candles"][-1],
        }
    except Exception as e:
        log.error(f"Psychology tick error ({symbol}/{interval}): {e}")
        return {"error": str(e)}


@app.get("/psychology/levels")
async def psychology_levels(symbol: str = "NIFTY", date: str = None):
    import yfinance as yf
    import datetime as _dt
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol.upper(), f"{symbol.upper()}.NS")

    if date:
        # Historical: fetch daily bars ending before the target date
        target = _dt.datetime.strptime(date, "%Y-%m-%d").date()
        start  = (target - _dt.timedelta(days=20)).strftime("%Y-%m-%d")
        df = yf.Ticker(yf_sym).history(start=start, end=date, interval="1d")
        if df.empty:
            return {"error": f"No daily data before {date}"}
        try:
            df.index = df.index.normalize()
            prev_row = df[df.index.date < target].iloc[-1]
        except Exception:
            prev_row = df.iloc[-1]
        prev = prev_row
    else:
        df = yf.Ticker(yf_sym).history(period="10d", interval="1d")
        if df.empty or len(df) < 2:
            return {"error": "Insufficient data"}
        today = _dt.datetime.now(IST).date()
        try:
            df.index = df.index.normalize()
            past = df[df.index.date < today]
            if past.empty:
                past = df.iloc[:-1]
        except Exception:
            past = df.iloc[:-1]
        if past.empty:
            return {"error": "No prior session data"}
        prev = past.iloc[-1]
    H, L, C = float(prev.High), float(prev.Low), float(prev.Close)
    pp    = round((H + L + C) / 3, 2)
    _bc   = round((H + L) / 2, 2)
    _tc   = round(2 * pp - _bc, 2)
    tc    = max(_tc, _bc)
    bc    = min(_tc, _bc)
    r1 = round(2 * pp - L, 2);  r2 = round(pp + (H - L), 2)
    s1 = round(2 * pp - H, 2);  s2 = round(pp - (H - L), 2)
    rng = H - L
    cam = {
        "h4": round(C + rng * 1.1 / 2, 2), "h3": round(C + rng * 1.1 / 4, 2),
        "l3": round(C - rng * 1.1 / 4, 2), "l4": round(C - rng * 1.1 / 2, 2),
    }
    # Latest spot from intraday
    spot = None
    try:
        intra = yf.Ticker(yf_sym).history(period="1d", interval="5m")
        if not intra.empty:
            spot = round(float(intra.iloc[-1]["Close"]), 2)
    except Exception:
        pass
    if spot is None:
        spot = round(float(df.iloc[-1]["Close"]), 2)
    # ORB — 9:15–9:30 IST
    orb = None
    try:
        intra2 = yf.Ticker(yf_sym).history(period="1d", interval="5m")
        if not intra2.empty:
            try:
                intra2.index = intra2.index.tz_convert("Asia/Kolkata")
            except Exception:
                pass
            t_open = _dt.datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
            t_orb  = _dt.datetime.now(IST).replace(hour=9, minute=30, second=0, microsecond=0)
            orb_bars = intra2[(intra2.index >= t_open) & (intra2.index <= t_orb)]
            if not orb_bars.empty:
                orb = {
                    "high": round(float(orb_bars["High"].max()), 2),
                    "low":  round(float(orb_bars["Low"].min()),  2),
                }
    except Exception:
        pass
    return {
        "symbol":     symbol.upper(),
        "spot":       spot,
        "prev_close": round(C, 2),
        "cpr":        {"tc": tc, "pp": pp, "bc": bc, "r1": r1, "r2": r2, "s1": s1, "s2": s2},
        "camarilla":  cam,
        "orb":        orb,
    }


# ══════════════════════════════════════════════════════════════════════════════
# F&O Scanner — buy/sell dominance for equities in a price range
# ══════════════════════════════════════════════════════════════════════════════

import time as _time

_fno_stock_cache: list = []
_fno_stock_cache_ts: float = 0.0
_all_eq_cache: list = []
_all_eq_cache_ts: float = 0.0


def _load_all_eq_stocks() -> list:
    global _all_eq_cache, _all_eq_cache_ts
    now = _time.time()
    if _all_eq_cache and (now - _all_eq_cache_ts) < 86400:
        return _all_eq_cache
    try:
        with open("data/instrument_master.json", "r") as f:
            raw = json.load(f)
        seen: set = set()
        stocks = []
        for inst in raw:
            name = inst.get("name", "").strip()
            sym  = inst.get("symbol", "")
            if (inst.get("exch_seg") == "NSE"
                    and inst.get("instrumenttype") == ""
                    and sym.endswith("-EQ")
                    and name not in seen):
                seen.add(name)
                stocks.append({"symbol": name, "token": str(inst["token"])})
        _all_eq_cache    = stocks
        _all_eq_cache_ts = now
        log.info(f"[ALL-EQ] {len(stocks)} NSE EQ stocks loaded")
        return stocks
    except Exception as e:
        log.error(f"[ALL-EQ] load failed: {e}")
        return []


def _load_fno_stocks() -> list:
    global _fno_stock_cache, _fno_stock_cache_ts
    now = _time.time()
    if _fno_stock_cache and (now - _fno_stock_cache_ts) < 86400:
        return _fno_stock_cache

    try:
        with open("data/instrument_master.json", "r") as f:
            raw = json.load(f)

        # Names of stocks that have options/futures in NFO
        fno_names: set = set()
        for inst in raw:
            if inst.get("exch_seg") == "NFO" and inst.get("instrumenttype") in ("OPTSTK", "FUTSTK"):
                name = inst.get("name", "").strip()
                if name:
                    fno_names.add(name)

        # Map to NSE EQ tokens — NSE equities have instrumenttype="" and symbol ending in "-EQ"
        seen: set = set()
        stocks = []
        for inst in raw:
            name = inst.get("name", "").strip()
            sym  = inst.get("symbol", "")
            if (inst.get("exch_seg") == "NSE"
                    and inst.get("instrumenttype") == ""
                    and sym.endswith("-EQ")
                    and name in fno_names
                    and name not in seen):
                seen.add(name)
                stocks.append({"symbol": name, "token": str(inst["token"])})

        _fno_stock_cache = stocks
        _fno_stock_cache_ts = now
        log.info(f"[FNO-SCANNER] {len(stocks)} F&O EQ stocks loaded")
        return stocks
    except Exception as e:
        log.error(f"[FNO-SCANNER] load_fno_stocks failed: {e}")
        return []


_NIFTY50_FALLBACK = {
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
    "BAJAJ-AUTO","BAJAJFINSV","BAJFINANCE","BHARTIARTL","BPCL",
    "BRITANNIA","CIPLA","COALINDIA","DRREDDY","EICHERMOT",
    "GRASIM","HCLTECH","HDFCBANK","HDFCLIFE","HEROMOTOCO",
    "HINDALCO","HINDUNILVR","ICICIBANK","INDUSINDBK","INFY",
    "ITC","JSWSTEEL","KOTAKBANK","LT","M&M",
    "MARUTI","NESTLEIND","NTPC","ONGC","POWERGRID",
    "RELIANCE","SBILIFE","SBIN","SHRIRAMFIN","SUNPHARMA",
    "TATACONSUM","TATAMOTORS","TATASTEEL","TCS","TECHM",
    "TITAN","TRENT","ULTRACEMCO","WIPRO","ZOMATO",
}

_NIFTY500_FALLBACK = {
    # Nifty 50
    "ADANIENT","ADANIPORTS","APOLLOHOSP","ASIANPAINT","AXISBANK",
    "BAJAJ-AUTO","BAJAJFINSV","BAJFINANCE","BHARTIARTL","BPCL",
    "BRITANNIA","CIPLA","COALINDIA","DRREDDY","EICHERMOT",
    "GRASIM","HCLTECH","HDFCBANK","HDFCLIFE","HEROMOTOCO",
    "HINDALCO","HINDUNILVR","ICICIBANK","INDUSINDBK","INFY",
    "ITC","JSWSTEEL","KOTAKBANK","LT","M&M",
    "MARUTI","NESTLEIND","NTPC","ONGC","POWERGRID",
    "RELIANCE","SBILIFE","SBIN","SHRIRAMFIN","SUNPHARMA",
    "TATACONSUM","TATAMOTORS","TATASTEEL","TCS","TECHM",
    "TITAN","TRENT","ULTRACEMCO","WIPRO","ZOMATO",
    # Nifty Next 50
    "ABB","ADANIGREEN","ADANIPOWER","AMBUJACEM","AUBANK",
    "BANDHANBNK","BEL","BERGEPAINT","BHEL","BOSCHLTD",
    "CANBK","CHOLAFIN","COLPAL","CONCOR","DLF",
    "GAIL","GODREJCP","GODREJPROP","HAL","HAVELLS",
    "ICICIGI","ICICILOMBARD","INDHOTEL","IOC","IGL",
    "IRCTC","JINDALSTEL","LICI","LTIM","LUPIN",
    "MARICO","MUTHOOTFIN","NAUKRI","PFC","PIDILITIND",
    "PNB","RECLTD","SAIL","SIEMENS","SRF",
    "TORNTPHARM","TVSMOTOR","UPL","VEDL","VOLTAS",
    "ZYDUSLIFE","UNIONBANK","UCOBANK","INDIANB",
    # Nifty Midcap 150 & other Nifty 500 F&O stocks
    "ABCAPITAL","ABFRL","AIAENG","ALKEM","APOLLOTYRE",
    "ASHOKLEY","ASTRAL","ATUL","AUROPHARMA","BALKRISIND",
    "BATAINDIA","BIOCON","BSOFT","CANFINHOME","CESC",
    "CGPOWER","CHOLAFIN","COFORGE","CROMPTON","CUMMINSIND",
    "DABUR","DEEPAKNTR","DELHIVERY","DIVISLAB","DIXON",
    "DMART","ESCORTS","ETERNAL","FEDERALBNK","GLENMARK",
    "GMRAIRPORT","GNFC","GRANULES","GSPL","HAPPSTMNDS",
    "HFCL","HINDPETRO","IDFCFIRSTB","IEX","IIFL",
    "INDIAMART","INDUSTOWER","INOXWIND","IPCALAB","JKCEMENT",
    "JSL","JUBLFOOD","KALYANKJIL","KANSAINER","KAYNES",
    "KPITTECH","LAURUSLABS","LICHSGFIN","LINDEINDIA","LTTS",
    "MANAPPURAM","MCX","METROPOLIS","MGL","MPHASIS",
    "MRF","NATCOPHARM","NAVINFLUOR","NMDC","OBEROIRLTY",
    "OFSS","PAGEIND","PERSISTENT","PETRONET","PHOENIXLTD",
    "PIIND","POLYCAB","PVRINOX","RAMCOCEM","RBLBANK",
    "REDINGTON","ROUTE","SCHAEFFLER","SHREECEM","SJVN",
    "SONACOMS","STAR","SUNDARMFIN","SUPREMEIND","SYNGENE",
    "TATACHEM","TATACOMM","TATAELXSI","TATAPOWER","THERMAX",
    "TIINDIA","TIMKEN","TORNTPOWER","TRIDENT","UJJIVANSFB",
    "UNOMINDA","UTIAMC","VBL","WHIRLPOOL","ZEEL",
    "SAPPHIRE","TRITURBINE","NATIONALUM","MOIL","NBCC",
}

_nifty50_cache: set = set()
_nifty50_cache_ts: datetime = None
_nifty500_cache: set = set()
_nifty500_cache_ts: datetime = None


_NSE_CSV_MAP = {
    "NIFTY 50":  "ind_nifty50list.csv",
    "NIFTY 500": "ind_nifty500list.csv",
}

def _fetch_nse_constituents(nse_index_name: str, min_count: int) -> set:
    """Fetch index constituents.
    1. NSE static CSV archive (no cookies needed — works from any server).
    2. Session-gated live API via movers session (browser-like warmup).
    Raises ValueError if neither returns enough symbols.
    """
    import requests as _req
    import csv as _csv, io as _io

    # ── Try static CSV first (most reliable from server IPs) ──
    csv_file = _NSE_CSV_MAP.get(nse_index_name)
    if csv_file:
        try:
            r = _req.get(
                f"https://nsearchives.nseindia.com/content/indices/{csv_file}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=15,
            )
            if r.status_code == 200:
                reader = _csv.DictReader(_io.StringIO(r.text))
                symbols = {row.get("Symbol", "").strip() for row in reader
                           if row.get("Symbol", "").strip()}
                if len(symbols) >= min_count:
                    log.info(f"[NSE-CSV] {nse_index_name}: {len(symbols)} symbols")
                    return symbols
                log.debug(f"[NSE-CSV] {nse_index_name}: only {len(symbols)} — trying API")
        except Exception as e:
            log.debug(f"[NSE-CSV] {nse_index_name} failed: {e}")

    # ── Fall back to session-gated API ──
    try:
        from core.movers import _fetch_nse
        rows    = _fetch_nse(nse_index_name)
        symbols = {r["symbol"] for r in rows if r.get("symbol")}
        if len(symbols) >= min_count:
            log.info(f"[NSE-API] {nse_index_name}: {len(symbols)} symbols")
            return symbols
        raise ValueError(f"only {len(symbols)} symbols from API for {nse_index_name}")
    except Exception as e:
        raise ValueError(str(e))


def _fetch_nifty50_symbols() -> set:
    global _nifty50_cache, _nifty50_cache_ts
    now = datetime.utcnow()
    if _nifty50_cache and _nifty50_cache_ts and (now - _nifty50_cache_ts).total_seconds() < 86400:
        return _nifty50_cache
    try:
        symbols = _fetch_nse_constituents("NIFTY 50", 45)
        _nifty50_cache    = symbols
        _nifty50_cache_ts = now
        log.info(f"[NIFTY50] fetched {len(symbols)} constituents from NSE")
        return symbols
    except Exception as e:
        log.warning(f"[NIFTY50] NSE fetch failed ({e}), using fallback list")
    return _NIFTY50_FALLBACK


def _fetch_nifty500_symbols() -> set:
    global _nifty500_cache, _nifty500_cache_ts
    now = datetime.utcnow()
    if _nifty500_cache and _nifty500_cache_ts and (now - _nifty500_cache_ts).total_seconds() < 86400:
        return _nifty500_cache
    try:
        symbols = _fetch_nse_constituents("NIFTY 500", 450)
        _nifty500_cache    = symbols
        _nifty500_cache_ts = now
        log.info(f"[NIFTY500] fetched {len(symbols)} constituents from NSE")
        return symbols
    except Exception as e:
        log.warning(f"[NIFTY500] NSE fetch failed ({e}), using fallback list")
    return _NIFTY500_FALLBACK


def _fno_scanner_sync(min_price: float, max_price: float, limit: int, dominance: str = "all", nifty50: bool = False, nifty500: bool = False) -> dict:
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    smart = _get_smart()
    if not smart:
        return {"error": "SmartAPI auth failed", "stocks": []}

    stocks = _load_fno_stocks()
    if not stocks:
        return {"error": "Instrument master unavailable", "stocks": []}

    n50 = _fetch_nifty50_symbols()
    if nifty500:
        n500 = _fetch_nifty500_symbols()
        stocks = [s for s in stocks if s["symbol"].upper() in n500]
    elif nifty50:
        stocks = [s for s in stocks if s["symbol"].upper() in n50]
    else:
        # "All F&O" mode excludes Nifty 50 to avoid duplicating the Nifty 50 tab
        stocks = [s for s in stocks if s["symbol"].upper() not in n50]

    # Batch getMarketData FULL — 50 tokens per call, 150ms gap to stay within rate limit
    import time as _time
    depth_map: dict = {}
    batch_size = 50
    for i in range(0, len(stocks), batch_size):
        if i > 0:
            _time.sleep(0.15)
        batch_tokens = [s["token"] for s in stocks[i: i + batch_size]]
        try:
            resp = smart.getMarketData("FULL", {"NSE": batch_tokens})
            if resp and resp.get("data") and resp["data"].get("fetched"):
                for item in resp["data"]["fetched"]:
                    depth_map[str(item.get("symbolToken"))] = item
        except Exception as e:
            log.warning(f"[FNO-SCANNER] depth batch {i} failed: {e}")

    # Filter by price range and calculate dominance
    result = []
    for s in stocks:
        d = depth_map.get(s["token"])
        if not d:
            continue
        ltp = float(d.get("ltp") or 0)
        if not nifty50 and not nifty500 and not (min_price <= ltp <= max_price):
            continue

        buy_qty  = int(d.get("totBuyQuan") or 0)
        sell_qty = int(d.get("totSellQuan") or 0)
        total    = buy_qty + sell_qty
        if total == 0:
            continue

        buy_pct  = round(buy_qty  / total * 100, 1)
        sell_pct = round(sell_qty / total * 100, 1)

        result.append({
            "symbol":      s["symbol"],
            "ltp":         round(ltp, 2),
            "change_pct":  round(float(d.get("percentChange") or 0), 2),
            "buy_qty":     buy_qty,
            "sell_qty":    sell_qty,
            "buy_pct":     buy_pct,
            "sell_pct":    sell_pct,
            "dominance":   "BUYER" if buy_pct >= sell_pct else "SELLER",
            "strength":    round(abs(buy_pct - sell_pct), 1),
            "volume":      int(d.get("tradeVolume") or 0),
        })

    # Apply dominance filter
    if dominance == "buyer":
        result = [r for r in result if r["dominance"] == "BUYER" and r["change_pct"] >= 0]
    elif dominance == "seller":
        result = [r for r in result if r["dominance"] == "SELLER" and r["change_pct"] <= 0]
    else:
        # All: buyers first, then sellers
        result.sort(key=lambda x: (0 if x["dominance"] == "BUYER" else 1, -x["strength"]))
        return {
            "stocks":        result[:limit],
            "total_matched": len(result),
            "timestamp":     now_ist.strftime("%H:%M:%S"),
            "min_price":     min_price,
            "max_price":     max_price,
        }

    # For buyer/seller filter: sort by strength desc
    result.sort(key=lambda x: -x["strength"])

    return {
        "stocks":        result[:limit],
        "total_matched": len(result),
        "timestamp":     now_ist.strftime("%H:%M:%S"),
        "min_price":     min_price,
        "max_price":     max_price,
    }


@app.get("/fno-scanner")
async def fno_scanner(min_price: float = 1000, max_price: float = 2000, limit: int = 10, dominance: str = "all", nifty50: bool = False, nifty500: bool = False):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _fno_scanner_sync, min_price, max_price, limit, dominance, nifty50, nifty500)
        return result
    except Exception as e:
        log.error(f"[FNO-SCANNER] error: {e}")
        return {"error": str(e), "stocks": []}


# ══════════════════════════════════════════════════════════════════════════════
# Stock Dominance Scanner — buy/sell dominance for NSE EQ stocks (not F&O)
# ══════════════════════════════════════════════════════════════════════════════

def _stock_scanner_sync(min_price: float, max_price: float, limit: int,
                         dominance: str = "all", universe: str = "nifty50",
                         sort_by: str = "dominance") -> dict:
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)

    all_eq = _load_all_eq_stocks()
    if not all_eq:
        return {"error": "Instrument master unavailable", "stocks": []}

    is_n50  = universe == "nifty50"
    is_n500 = universe == "nifty500"

    if is_n50:
        n50    = _fetch_nifty50_symbols()
        stocks = [s for s in all_eq if s["symbol"].upper() in n50]
    elif is_n500:
        n500   = _fetch_nifty500_symbols()
        stocks = [s for s in all_eq if s["symbol"].upper() in n500]
    else:
        stocks = all_eq

    token_to_sym = {s["token"]: s["symbol"] for s in stocks}
    snapshots    = get_provider().get_market_data(list(token_to_sym.keys()), "NSE")

    result = []
    for snap in snapshots:
        sym = token_to_sym.get(snap.token)
        if not sym:
            continue
        if not is_n50 and not is_n500 and not (min_price <= snap.ltp <= max_price):
            continue
        if (snap.buy_qty + snap.sell_qty) == 0:
            continue
        result.append({
            "symbol":     sym,
            "ltp":        snap.ltp,
            "change_pct": snap.pct_change,
            "buy_qty":    snap.buy_qty,
            "sell_qty":   snap.sell_qty,
            "buy_pct":    snap.buy_pct,
            "sell_pct":   snap.sell_pct,
            "dominance":  "BUYER" if snap.buy_pct >= snap.sell_pct else "SELLER",
            "strength":   round(abs(snap.buy_pct - snap.sell_pct), 1),
            "volume":     snap.volume,
        })

    if dominance == "buyer":
        result = [r for r in result if r["dominance"] == "BUYER" and r["change_pct"] >= 0]
    elif dominance == "seller":
        result = [r for r in result if r["dominance"] == "SELLER" and r["change_pct"] <= 0]

    if sort_by == "change":
        result.sort(key=lambda x: -abs(x["change_pct"]))
    elif dominance == "all":
        result.sort(key=lambda x: (0 if x["dominance"] == "BUYER" else 1, -x["strength"]))
    else:
        result.sort(key=lambda x: -x["strength"])

    return {"stocks": result[:limit], "total_matched": len(result),
            "timestamp": now_ist.strftime("%H:%M:%S")}


@app.get("/debug/nifty500")
def debug_nifty500():
    global _nifty500_cache, _nifty500_cache_ts
    import traceback as _tb

    _nifty500_cache_ts = None
    n500    = _fetch_nifty500_symbols()
    all_eq  = _load_all_eq_stocks()
    matched = [s for s in all_eq if s["symbol"].upper() in n500]

    smart = _get_smart()
    if not smart:
        return {"error": "SmartAPI not authenticated"}

    # Run all batches — same as the real scanner
    depth_map: dict = {}
    batch_results = []
    batch_size = 50
    for i in range(0, len(matched), batch_size):
        batch = matched[i: i + batch_size]
        tokens = [s["token"] for s in batch]
        try:
            resp    = smart.getMarketData("FULL", {"NSE": tokens})
            fetched = (resp or {}).get("data", {}).get("fetched") or []
            for item in fetched:
                depth_map[str(item.get("symbolToken"))] = item
            batch_results.append({"batch": i // batch_size, "sent": len(tokens), "returned": len(fetched)})
        except Exception as e:
            batch_results.append({"batch": i // batch_size, "sent": len(tokens), "error": str(e)})
        _time.sleep(0.15)

    # Tally outcomes for all 500 stocks
    no_data, zero_depth, has_depth = [], [], []
    for s in matched:
        d = depth_map.get(s["token"])
        if not d:
            no_data.append(s["symbol"])
        elif int(d.get("totBuyQuan") or 0) + int(d.get("totSellQuan") or 0) == 0:
            zero_depth.append(s["symbol"])
        else:
            has_depth.append(s["symbol"])

    return {
        "n500_count":       len(n500),
        "matched_count":    len(matched),
        "depth_map_size":   len(depth_map),
        "has_depth_count":  len(has_depth),
        "zero_depth_count": len(zero_depth),
        "no_data_count":    len(no_data),
        "no_data_sample":   no_data[:20],
        "zero_depth_sample": zero_depth[:20],
        "batch_results":    batch_results,
    }


@app.get("/stock-scanner")
async def stock_scanner(min_price: float = 100, max_price: float = 5000, limit: int = 20,
                         dominance: str = "all", universe: str = "nifty50",
                         sort_by: str = "dominance"):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, _stock_scanner_sync, min_price, max_price, limit, dominance, universe, sort_by)
        return result
    except Exception as e:
        log.error(f"[STOCK-SCANNER] error: {e}")
        return {"error": str(e), "stocks": []}


# ══════════════════════════════════════════════════════════════════════════════
# Stock Indicators — RSI, EMA trend, volume, candle pattern for any NSE stock
# ══════════════════════════════════════════════════════════════════════════════

def _stock_indicators_sync(symbol: str) -> dict:
    import yfinance as yf
    import pandas as pd
    import math

    ticker = symbol.upper() + ".NS"
    try:
        df = yf.Ticker(ticker).history(period="6mo", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 50:
            return {"error": f"Not enough data for {symbol}"}

        closes  = df["Close"].dropna().tolist()
        volumes = df["Volume"].dropna().tolist()
        opens   = df["Open"].dropna().tolist()
        highs   = df["High"].dropna().tolist()
        lows    = df["Low"].dropna().tolist()

        # RSI(14)
        delta = pd.Series(closes).diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs_last = float(loss.iloc[-1])
        if math.isnan(rs_last):
            rsi_val = None
        elif rs_last == 0:
            rsi_val = 100.0
        else:
            rs = float(gain.iloc[-1]) / rs_last
            rsi_val = round(100 - 100 / (1 + rs), 2) if not math.isnan(rs) else None

        # EMA trend
        s = pd.Series(closes)
        ema20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(s.ewm(span=50, adjust=False).mean().iloc[-1])
        trend = "UP" if ema20 > ema50 else "DOWN"

        # Volume signal (vs 20-day avg)
        avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes) / len(volumes)
        cur_vol = volumes[-1]
        if cur_vol > avg_vol * 1.5:    vol_signal = "HIGH"
        elif cur_vol < avg_vol * 0.7:  vol_signal = "LOW"
        else:                          vol_signal = "NORMAL"

        # Candle pattern (last candle, with previous for context)
        candle = "NONE"
        if len(closes) >= 2 and len(opens) >= 2 and len(highs) >= 2 and len(lows) >= 2:
            pc, cc = closes[-2], closes[-1]
            po, co = opens[-2],  opens[-1]
            ph, ch = highs[-2],  highs[-1]
            pl, cl = lows[-2],   lows[-1]
            body    = abs(cc - co)
            c_range = ch - cl if ch > cl else 0.01

            if pc < po and cc > co and cc > po and co < pc:
                candle = "BULLISH_ENGULFING"
            elif pc > po and cc < co and co > pc and cc < po:
                candle = "BEARISH_ENGULFING"
            elif body / c_range > 0.65 and (ch - cc) < 0.15 * c_range and cc > co:
                candle = "STRONG_BULL"         # big green, close near high
            elif body / c_range > 0.65 and (cc - cl) < 0.15 * c_range and cc < co:
                candle = "STRONG_BEAR"         # big red, close near low
            elif body / c_range < 0.35 and (co - cl) >= 2 * body and cc >= co:
                candle = "HAMMER"              # small body, long lower wick
            elif body / c_range < 0.35 and (ch - co) >= 2 * body and cc <= co:
                candle = "SHOOTING_STAR"       # small body, long upper wick
            elif body / c_range < 0.1:
                candle = "DOJI"                # open ≈ close, indecision
            elif ch < ph and cl > pl:
                candle = "INSIDE_BAR"          # range within prev candle, consolidation

        # Support / Resistance (20-day)
        recent = closes[-20:]
        support    = round(min(recent), 2)
        resistance = round(max(recent), 2)

        # Futures OI — near-month FUTSTK data via provider
        fut_oi = None
        try:
            _ft, _fexp = im.get_stock_futures_token(symbol)
            if _ft:
                _snaps = get_provider().get_option_market_data([str(_ft)])
                _snap  = next((s for s in _snaps if s.token == str(_ft)), None)
                if _snap and _snap.open_interest:
                    _price_up = _snap.pct_change > 0 if _snap.pct_change is not None else None
                    # OI change not in MarketSnapshot — derive from open_interest vs prev if available
                    _signal   = None
                    if _price_up is not None:
                        _signal = "long_buildup" if _price_up else "short_buildup"
                    fut_oi = {
                        "oi":     _snap.open_interest,
                        "oi_chg": None,
                        "signal": _signal,
                        "ltp":    _snap.ltp,
                        "expiry": _fexp,
                    }
        except Exception as _fe:
            log.warning(f"[INDICATORS] {symbol} futures OI: {_fe}")

        return {
            "symbol":       symbol.upper(),
            "rsi":          rsi_val,
            "trend":        trend,
            "ema20":        round(ema20, 2),
            "ema50":        round(ema50, 2),
            "volumeSignal": vol_signal,
            "volume":       int(cur_vol) if cur_vol and not math.isnan(float(cur_vol)) else 0,
            "candlePattern":candle,
            "support":      support,
            "resistance":   resistance,
            "fut_oi":       fut_oi,
        }
    except Exception as e:
        log.error(f"[INDICATORS] {symbol}: {e}")
        return {"error": str(e)}


@app.get("/stock-indicators/{symbol}")
async def stock_indicators(symbol: str):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _stock_indicators_sync, symbol)
        return result
    except Exception as e:
        log.error(f"[INDICATORS] error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Options Analysis Tool endpoints
# ══════════════════════════════════════════════════════════════════════════════

from core.options.iv_analyzer       import get_context       as _oc_context
from core.options.option_chain_fetcher import (
    get_expiries as _oc_expiries,
    search_contracts as _oc_search,
    fetch_chain as _oc_fetch_chain,
    fetch_chain_nse as _oc_fetch_chain_nse,
    get_oi_change_signals as _oc_oi_signals,
    compute_daily_oi_signals as _oc_daily_oi_signals,
)
from core.options.max_pain          import analyze_chain      as _oc_max_pain
from core.options.signal_scorer     import score_signals      as _oc_score
from core.options.strike_selector   import select_strike      as _oc_strike
from core.options.risk_calculator   import calculate          as _oc_risk
from core.options.bhavcopy          import (build_history as _bhav_history,
                                             parse_upload_multi as _bhav_parse_multi,
                                             fetch_contract_history_nse as _bhav_fetch_nse)
from core.options.trade_monitor     import evaluate           as _oc_monitor, update_position as _oc_update


@app.get("/options/context")
async def options_context(symbol: str = "NIFTY"):
    """Pre-market context: India VIX, previous OHLC, weekly range, spot, bias."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _oc_context, symbol)
    except Exception as e:
        log.error(f"options/context error: {e}")
        return {"error": str(e)}


@app.get("/options/expiries")
def options_expiries(symbol: str = "NIFTY"):
    """Return upcoming option expiries for a symbol (sorted chronologically)."""
    try:
        return {"symbol": symbol.upper(), "expiries": _oc_expiries(symbol)}
    except Exception as e:
        log.error(f"options/expiries error: {e}")
        return {"error": str(e)}


@app.get("/options/search")
def options_search(query: str, expiry_type: str = "weekly", spot_price: float = None):
    """Contract autocomplete — returns up to 40 NFO option contracts."""
    try:
        return {"contracts": _oc_search(query, expiry_type, spot_price)}
    except Exception as e:
        log.error(f"options/search error: {e}")
        return {"error": str(e)}


def _options_chain_sync(symbol: str, expiry: str, spot_price: float | None) -> dict:
    # Try NSE direct first — more accurate LTP for thinly-traded / far-dated contracts
    chain_data = _oc_fetch_chain_nse(symbol, expiry, spot_price)
    if "error" in chain_data:
        log.info(f"NSE chain fallback to provider for {symbol} {expiry}: {chain_data['error']}")
        chain_data = _oc_fetch_chain(symbol, expiry, spot_price)
    if "error" in chain_data:
        return chain_data
    chain     = chain_data.get("chain", [])
    spot      = chain_data.get("spot") or spot_price
    is_index  = symbol.upper() in _INDEX_UNDERLYINGS
    if not spot and is_index:
        # NIFTY/BANKNIFTY WebSocket price is only reliable for index underlyings
        try:
            ws = market_state.get(SPOT_TOKEN, {})
            if ws.get("price"):
                spot = float(ws["price"])
        except Exception:
            pass
    if not spot and is_index:
        spot = (trade_flow_data.get("prev_ohlc") or {}).get("close")
    if not spot and chain:
        # Last resort for stocks: use median strike as ATM proxy
        strikes = sorted(r["strike"] for r in chain)
        spot = strikes[len(strikes) // 2]
    analytics = _oc_max_pain(chain, spot)          # compute on full chain for accuracy
    chain     = _trim_chain_atm(chain, spot, n=5)  # then trim to ±5 for display
    oi_signals = _oc_oi_signals(symbol, expiry, chain)
    # No 5-min snapshot yet — derive OI signals from NSE daily change data instead
    if not oi_signals and chain_data.get("source") == "NSE":
        oi_signals = _oc_daily_oi_signals(chain)
    # Always return the resolved spot (may differ from chain_data["spot"] when fallback was used)
    return {**chain_data, "chain": chain, "analytics": analytics, "oi_signals": oi_signals, "spot": spot}


def _trim_chain_atm(chain: list, spot: float | None, n: int = 5) -> list:
    if not chain or spot is None:
        return chain
    strikes = [r["strike"] for r in chain]
    atm = min(strikes, key=lambda s: abs(s - spot))
    idx = strikes.index(atm)
    return chain[max(0, idx - n): idx + n + 1]


@app.get("/options/chain")
async def options_chain(symbol: str = "NIFTY", expiry: str = "", spot_price: float = None):
    """
    Full option chain with OI, LTP, IV, depth + max pain analytics + OI change signals.
    expiry: DDMMMYYYY e.g. 25APR2024. If omitted, uses nearest expiry.
    """
    if not expiry:
        exp_list = _oc_expiries(symbol)
        if not exp_list:
            return {"error": f"No expiries found for {symbol}"}
        expiry = exp_list[0]

    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _options_chain_sync, symbol, expiry, spot_price)
    except Exception as e:
        log.error(f"options/chain error: {e}")
        return {"error": str(e)}


def _compute_candle_data(symbol: str) -> dict | None:
    """Fetch today's 5-min bars and compute EMA9/21, VWAP, RSI, Volume for signal scoring."""
    import yfinance as yf
    import datetime as _dt
    import pandas as pd
    try:
        IST    = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
        yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "^CNXFIN"}.get(
                    symbol.upper(), f"{symbol.upper()}.NS")
        today  = _dt.datetime.now(IST).date()

        # Try "1d" first (faster); fall back to "5d" if today's data is thin
        df = None
        for period in ("1d", "5d"):
            try:
                raw = yf.Ticker(yf_sym).history(period=period, interval="5m", auto_adjust=True)
                if raw.empty:
                    continue
                raw.index = pd.DatetimeIndex(raw.index).tz_convert(IST)
                raw = raw[raw.index.date == today]
                if len(raw) >= 5:
                    df = raw
                    break
            except Exception as _fe:
                log.debug(f"_compute_candle_data {yf_sym} period={period}: {_fe}")
                continue

        if df is not None and not df.empty:
            closes  = df["Close"]
            volumes = df["Volume"]
            ema9       = float(closes.ewm(span=9,  adjust=False).mean().iloc[-1])
            ema21      = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
            close      = float(closes.iloc[-1])
            volume     = float(volumes.iloc[-1])
            avg_volume = float(volumes.mean())
            typical    = (df["High"] + df["Low"] + df["Close"]) / 3
            cum_vol    = volumes.replace(0, float("nan")).cumsum().iloc[-1]
            vwap       = float((typical * volumes).cumsum().iloc[-1] / cum_vol) if cum_vol and cum_vol > 0 else close
            delta      = closes.diff()
            gain       = delta.where(delta > 0, 0.0).ewm(com=13, adjust=False).mean()
            loss       = (-delta.where(delta < 0, 0.0)).ewm(com=13, adjust=False).mean()
            last_loss  = float(loss.iloc[-1])
            last_gain  = float(gain.iloc[-1])
            rsi = float(100 - 100 / (1 + last_gain / last_loss)) if last_loss > 0 else (100.0 if last_gain > 0 else 50.0)
            log.info(f"_compute_candle_data({symbol}): intraday close={close:.1f} ema9={ema9:.1f} ema21={ema21:.1f} vwap={vwap:.1f} rsi={rsi:.1f} bars={len(df)}")
            return {"close": close, "vwap": vwap, "volume": volume, "avg_volume": avg_volume, "ema9": ema9, "ema21": ema21, "rsi": rsi}

        # Intraday unavailable — fall back to daily bars for EMA/RSI/Volume
        # VWAP key is intentionally omitted so the scorer marks it as no_data
        log.warning(f"_compute_candle_data({symbol}): no intraday data, falling back to daily bars")
        daily = yf.Ticker(yf_sym).history(period="30d", interval="1d", auto_adjust=True)
        if daily is None or len(daily) < 14:
            log.warning(f"_compute_candle_data({symbol}): daily fallback insufficient")
            return None
        closes     = daily["Close"]
        volumes    = daily["Volume"]
        ema9       = float(closes.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21      = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
        close      = float(closes.iloc[-1])
        volume     = float(volumes.iloc[-1])
        avg_volume = float(volumes.iloc[-20:].mean())
        delta      = closes.diff()
        gain       = delta.where(delta > 0, 0.0).ewm(com=13, adjust=False).mean()
        loss       = (-delta.where(delta < 0, 0.0)).ewm(com=13, adjust=False).mean()
        last_loss  = float(loss.iloc[-1])
        last_gain  = float(gain.iloc[-1])
        rsi = float(100 - 100 / (1 + last_gain / last_loss)) if last_loss > 0 else (100.0 if last_gain > 0 else 50.0)
        log.info(f"_compute_candle_data({symbol}): daily close={close:.1f} ema9={ema9:.1f} ema21={ema21:.1f} rsi={rsi:.1f}")
        return {"close": close, "volume": volume, "avg_volume": avg_volume, "ema9": ema9, "ema21": ema21, "rsi": rsi}
    except Exception as e:
        log.warning(f"_compute_candle_data({symbol}): {e}")
        return None


@app.get("/options/score")
def options_score(
    symbol: str = "NIFTY",
    direction: str = "CE",
    expiry: str = "",
    strike: float = None,
    spot_price: float = None,
):
    """
    Composite signal score (0–17) for a CE/PE trade.
    Fetches real chain analytics, OI signals, and intraday candle data.
    """
    try:
        context        = _oc_context(symbol)
        effective_spot = spot_price or context.get("spot")

        if not expiry:
            exp_list = _oc_expiries(symbol)
            expiry   = exp_list[0] if exp_list else ""

        # Fetch real chain for OI walls + OI change signals
        analytics  = {"pcr": 1.0, "pcr_label": "NEUTRAL",
                      "resistance_wall": None, "support_wall": None, "max_pain": None}
        oi_signals = {}
        try:
            chain_data = _oc_fetch_chain_nse(symbol, expiry, effective_spot)
            if "error" in chain_data:
                chain_data = _oc_fetch_chain(symbol, expiry, effective_spot)
            if "error" not in chain_data:
                chain      = chain_data.get("chain", [])
                analytics  = _oc_max_pain(chain, effective_spot)
                oi_signals = _oc_oi_signals(symbol, expiry, chain)
                if not oi_signals and chain_data.get("source") == "NSE":
                    oi_signals = _oc_daily_oi_signals(chain)
        except Exception as ce:
            log.warning(f"options/score chain fetch skipped: {ce}")

        # Compute intraday candle indicators (EMA9/21, VWAP, RSI, Volume)
        candle_data = _compute_candle_data(symbol)

        result = _oc_score(
            direction       = direction,
            context         = context,
            chain_analytics = analytics,
            oi_signals      = oi_signals,
            target_strike   = strike,
            candle_data     = candle_data,
        )
        return result
    except Exception as e:
        log.error(f"options/score error: {e}")
        return {"error": str(e)}


@app.get("/options/select-strike")
def options_select_strike(
    symbol: str = "NIFTY",
    expiry: str = "",
    direction: str = "CE",
    spot_price: float = None,
):
    """
    Pick the best CE or PE strike from the full chain using delta + liquidity filters.
    Tries NSE first; falls back to Angel One via provider if NSE is unavailable.
    """
    try:
        if not expiry:
            exp_list = _oc_expiries(symbol)
            expiry   = exp_list[0] if exp_list else ""
        if not expiry:
            return {"error": "No expiry found"}
        chain_data = _oc_fetch_chain_nse(symbol, expiry, spot_price)
        if "error" in chain_data:
            chain_data = _oc_fetch_chain(symbol, expiry, spot_price)
        if "error" in chain_data:
            return chain_data
        analytics = _oc_max_pain(chain_data["chain"], spot_price)
        return _oc_strike(
            chain       = chain_data["chain"],
            direction   = direction,
            spot_price  = spot_price or chain_data.get("spot") or 0,
            max_pain    = analytics.get("max_pain"),
        )
    except Exception as e:
        log.error(f"options/select-strike error: {e}")
        return {"error": str(e)}


@app.get("/options/risk")
def options_risk(
    entry_ltp: float,
    lot_size: int,
    direction: str = "CE",
    capital: float = 500000,
    risk_pct: float = 0.01,
):
    """Position sizing and P&L plan for an option trade."""
    try:
        return _oc_risk(
            entry_ltp  = entry_ltp,
            lot_size   = lot_size,
            direction  = direction,
            capital    = capital,
            risk_pct   = risk_pct,
        )
    except Exception as e:
        log.error(f"options/risk error: {e}")
        return {"error": str(e)}


@app.get("/options/contract-history")
def options_contract_history(
    symbol:   str   = "NIFTY",
    strike:   float = 24300,
    expiry:   str   = "",
    opt_type: str   = "CE",
):
    """
    Historical EOD data for a specific options contract from NSE bhavcopy.
    Includes spot price, IV, theoretical theta-decay price, and daily theta.
    """
    if not expiry:
        return {"error": "expiry is required (format: YYYY-MM-DD)"}
    try:
        return _bhav_history(symbol, strike, expiry, opt_type)
    except Exception as e:
        log.error(f"options/contract-history error: {e}")
        return {"error": str(e)}


@app.post("/options/parse-bhavcopy")
async def options_parse_bhavcopy(
    files:    list[UploadFile] = File(...),
    symbol:   str   = "NIFTY",
    strike:   float = 24300,
    expiry:   str   = "",
    opt_type: str   = "CE",
):
    """
    Parse one or more uploaded NSE F&O Bhavcopy ZIP/CSV files.
    Combine into a multi-day theta decay history. Expiry auto-detected.
    """
    try:
        files_data = [(await f.read(), f.filename or "") for f in files]
        return _bhav_parse_multi(files_data, symbol, strike, expiry, opt_type)
    except Exception as e:
        log.error(f"options/parse-bhavcopy error: {e}")
        return {"error": str(e)}


@app.get("/options/contract-history-nse")
def options_contract_history_nse(
    symbol:   str   = "NIFTY",
    strike:   float = 24300,
    expiry:   str   = "08-May-2026",
    opt_type: str   = "CE",
    from_date: str = "01-Apr-2026",
    to_date:   str = "08-May-2026",
):
    """
    Fetch contract history directly from NSE's derivatives API.
    Dates must be in DD-MMM-YYYY format (e.g., "08-May-2026").
    """
    try:
        return _bhav_fetch_nse(symbol, strike, expiry, opt_type, from_date, to_date)
    except Exception as e:
        log.error(f"options/contract-history-nse error: {e}")
        return {"error": str(e)}


@app.get("/stocks/indicators")
def stocks_indicators(symbol: str = "RELIANCE"):
    """EMA 9/21 (5-min), EMA 50/200 (daily), VWAP, Supertrend + entry bias score."""
    from core.stock_indicators import fetch_indicators as _fetch_ind
    try:
        return _fetch_ind(symbol.upper())
    except Exception as e:
        log.error(f"stocks/indicators error: {e}")
        return {"error": str(e)}


def _nifty500_movers_sync() -> dict:
    import time as _time
    _TTL      = 300
    _STALE_OK = 1800
    cached = _ltp_cache.get("_n500_movers")
    if cached and (_time.time() - cached["ts"]) < _TTL:
        return cached["data"]

    n500    = _fetch_nifty500_symbols()
    all_eq  = _load_all_eq_stocks()
    matched = [s for s in all_eq if s["symbol"].upper() in n500]
    if not matched:
        if cached and (_time.time() - cached["ts"]) < _STALE_OK:
            return {**cached["data"], "stale": True}
        return {"error": "No Nifty 500 instruments found"}

    token_to_sym = {s["token"]: s["symbol"] for s in matched}
    snapshots    = get_provider().get_market_data(list(token_to_sym.keys()), "NSE")

    if not snapshots:
        if cached and (_time.time() - cached["ts"]) < _STALE_OK:
            log.warning("[N500-MOVERS] provider returned no data — serving stale cache")
            return {**cached["data"], "stale": True}
        return {"error": "No Nifty 500 data available"}

    rows = []
    for snap in snapshots:
        sym = token_to_sym.get(snap.token)
        if not sym:
            continue
        rows.append({
            "symbol":     sym,
            "ltp":        snap.ltp,
            "change":     round(snap.ltp - snap.prev_close, 2),
            "pct_change": snap.pct_change,
            "prev_close": snap.prev_close,
            "open":       snap.open,
            "high":       snap.high,
            "low":        snap.low,
            "volume":     snap.volume,
            "buy_qty":    snap.buy_qty,
            "sell_qty":   snap.sell_qty,
            "buy_pct":    snap.buy_pct,
            "sell_pct":   snap.sell_pct,
        })

    if not rows:
        if cached and (_time.time() - cached["ts"]) < _STALE_OK:
            return {**cached["data"], "stale": True}
        return {"error": "No Nifty 500 data available"}

    gainers_pool = [r for r in rows if r.get("pct_change", 0) > 0]
    losers_pool  = [r for r in rows if r.get("pct_change", 0) < 0]
    rows.sort(key=lambda r: r["pct_change"], reverse=True)
    now       = _time.time()
    advancing = sum(1 for r in rows if r["pct_change"] > 0)
    declining = sum(1 for r in rows if r["pct_change"] < 0)
    result    = {
        "index":      "NIFTY 500",
        "source":     "Live",
        "count":      len(rows),
        "advancing":  advancing,
        "declining":  declining,
        "unchanged":  len(rows) - advancing - declining,
        "gainers":    _volume_rank(gainers_pool, True)[:10],
        "losers":     _volume_rank(losers_pool, False)[:10],
        "all_rows":   rows,
        "fetched_at": int(now),
    }
    _ltp_cache["_n500_movers"] = {"data": result, "ts": now}
    return result


def _enrich_with_depth(rows: list) -> list:
    if not rows or "buy_qty" in rows[0]:
        return rows
    sym_set   = {r["symbol"].upper() for r in rows}
    all_eq    = _load_all_eq_stocks()
    token_map = {s["token"]: s["symbol"].upper()
                 for s in all_eq if s["symbol"].upper() in sym_set}
    if not token_map:
        return rows
    try:
        snapshots = get_provider().get_market_data(list(token_map.keys()), "NSE")
        depth = {
            token_map[snap.token]: {
                "buy_qty":  snap.buy_qty,  "sell_qty": snap.sell_qty,
                "buy_pct":  snap.buy_pct,  "sell_pct": snap.sell_pct,
            }
            for snap in snapshots if snap.token in token_map
        }
    except Exception as e:
        log.warning(f"[ENRICH-DEPTH] {e}")
        return rows
    return [{**r, **depth.get(r["symbol"].upper(), {})} for r in rows]


def _composite_score(r: dict, is_gainer: bool) -> float:
    """Rank score weighting pct_change by buyer/seller dominance confirmation."""
    pct      = abs(r.get("pct_change", 0))
    buy_pct  = r.get("buy_pct")  or 50.0
    sell_pct = r.get("sell_pct") or 50.0
    factor   = (buy_pct / 50.0) if is_gainer else (sell_pct / 50.0)
    return pct * max(0.1, factor)


def _volume_rank(rows: list, is_gainer: bool) -> list:
    """
    Two-tier sort: volume-confirmed moves first, unconfirmed moves second.
    Tier 1: buy_pct >= 50 for gainers (or sell_pct >= 50 for losers) — direction confirmed by order book.
    Tier 2: opposite dominance — price moved against the order book bias.
    Within each tier, ranked by composite score (pct_change weighted by dominance).
    """
    dom_field  = "buy_pct" if is_gainer else "sell_pct"
    confirmed   = [r for r in rows if (r.get(dom_field) or 50.0) >= 50.0]
    unconfirmed = [r for r in rows if (r.get(dom_field) or 50.0) <  50.0]
    confirmed.sort(  key=lambda r: _composite_score(r, is_gainer), reverse=True)
    unconfirmed.sort(key=lambda r: _composite_score(r, is_gainer), reverse=True)
    return confirmed + unconfirmed


@app.get("/stocks/movers")
def stocks_movers(index: str = "nifty50", min_price: float = 0,
                  max_price: float = 0, min_change: float = 0):
    """Top/bottom 10 movers for the given NSE index. Supports price and % filters."""
    try:
        if index == "nifty500":
            result = _nifty500_movers_sync()
        else:
            from core.movers import fetch_movers as _fetch_movers
            result = _fetch_movers(index)
    except Exception as e:
        log.error(f"stocks/movers error: {e}")
        return {"error": str(e)}

    if result.get("error"):
        return result

    if min_price > 0 or max_price > 0 or min_change > 0:
        all_rows = result.get("all_rows", [])
        filtered = [r for r in all_rows
                    if (min_price == 0 or r.get("ltp", 0) >= min_price)
                    and (max_price == 0 or r.get("ltp", 0) <= max_price)
                    and (min_change == 0 or abs(r.get("pct_change", 0)) >= min_change)]
        advancing = sum(1 for r in filtered if r.get("pct_change", 0) > 0)
        declining = sum(1 for r in filtered if r.get("pct_change", 0) < 0)
        result = {**result,
                  "count":     len(filtered),
                  "advancing": advancing,
                  "declining": declining,
                  "unchanged": len(filtered) - advancing - declining,
                  "gainers":   filtered[:10],
                  "losers":    list(reversed(filtered[-10:])) if filtered else []}

    result["gainers"] = _volume_rank(_enrich_with_depth(result.get("gainers", [])), True)
    result["losers"]  = _volume_rank(_enrich_with_depth(result.get("losers",  [])), False)
    return result


@app.get("/stocks/live-prices")
def stocks_live_prices(index: str = "nifty50"):
    """Current LTPs for index constituents. NSE primary, Yahoo fallback. 5-second cache."""
    from core.movers import fetch_live_prices as _fetch_prices
    try:
        return _fetch_prices(index)
    except Exception as e:
        log.error(f"stocks/live-prices error: {e}")
        return {"error": str(e)}


@app.get("/stocks/search")
def stocks_search(q: str = "", limit: int = 8):
    """Search for NSE/BSE stocks by code or name. Supports autocomplete."""
    from stocks_data import search_stocks
    if limit > 20:
        limit = 20  # cap at 20 to avoid abuse
    try:
        results = search_stocks(q, limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        log.error(f"stocks/search error: {e}")
        return {"error": str(e), "results": [], "count": 0}


# ══════════════════════════════════════════════════════════════════════════════
# Swing Trading (S4 framework) endpoints
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/swing/analyse")
def swing_analyse(symbol: str, capital: float = 75000, risk_pct: float = 2):
    """Full S4 5-pillar swing analysis for a single NSE stock."""
    from core.swing_analyzer import analyse_stock
    try:
        return analyse_stock(symbol.upper().strip(), capital, risk_pct)
    except Exception as e:
        log.error(f"swing/analyse error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/swing/scan")
def swing_scan(capital: float = 75000, risk_pct: float = 2, universe: str = "nifty100"):
    """Batch scan Nifty 50 + Next 50 stocks via S4 quick-filter. Returns top 3 + rejected."""
    try:
        from core.swing_analyzer import scan_stocks, NIFTY50, NIFTY_NEXT50
        symbols = NIFTY50 + NIFTY_NEXT50 if universe == "nifty100" else NIFTY50
        return scan_stocks(symbols, capital, risk_pct)
    except Exception as e:
        log.error(f"swing/scan error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/swing/prices")
def swing_prices(symbols: str):
    """Current LTPs for comma-separated NSE symbols (used by portfolio review tab)."""
    from core.swing_analyzer import fetch_swing_prices
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        if not sym_list:
            return {"prices": {}}
        return fetch_swing_prices(sym_list)
    except Exception as e:
        log.error(f"swing/prices error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/swing/reversal/analyse")
def swing_reversal_analyse(symbol: str, capital: float = 75000, risk_pct: float = 2,
                           min_fall: float = 15.0):
    """Reversal Radar: confirmed-turn analysis for one fallen NSE stock."""
    from core.reversal_analyzer import analyse_reversal
    try:
        return analyse_reversal(symbol.upper().strip(), capital, risk_pct, min_fall)
    except Exception as e:
        log.error(f"swing/reversal/analyse error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/swing/reversal/scan")
def swing_reversal_scan(capital: float = 75000, risk_pct: float = 2,
                        min_fall: float = 15.0, universe: str = "midcaps"):
    """Reversal Radar batch scan: quality large/mid-caps showing a confirmed turn."""
    from core.reversal_analyzer import scan_reversals, reversal_universe
    try:
        return scan_reversals(reversal_universe(universe), capital, risk_pct, min_fall)
    except Exception as e:
        log.error(f"swing/reversal/scan error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# Cup & Handle Pattern Detection endpoints
# ══════════════════════════════════════════════════════════════════════════════

# ── Extended universes (fallback lists; live data fetched from NSE when available)
_CH_MIDCAP150_FALLBACK: list = [
    "ABFRL","AIAENG","ALKEM","APLAPOLLO","APOLLOTYRE",
    "BALRAMCHIN","BATAINDIA","BHARATFORG","BLUESTARINDIA","CANFINHOME",
    "CESC","CHOLAFIN","COFORGE","CROMPTON","CYIENT",
    "DALBHARAT","DEEPAKNTR","DIXON","EMAMILTD","FEDERALBNK",
    "GLENMARK","GRANULES","HAPPSTMNDS","HDFCAMC","IDFCFIRSTB",
    "INDIAMART","INTELLECT","IPCA","IPCALAB","JKCEMENT",
    "JINDALSAW","JSPL","JUBLFOOD","KALYANKJIL","KPITTECH",
    "LAURUSLABS","LICHSGFIN","LALPATHLAB","LTTS","MUTHOOTFIN",
    "MANAPPURAM","MASTEK","MAXHEALTH","METROPOLIS","MFSL",
    "NATCOPHARM","NAVINFLUOR","NHPC","NYKAA","OBEROIRLTY",
    "OLECTRA","PAGEIND","PERSISTENT","PIRAMALENT","POLICYBZR",
    "RAMCOCEM","RATEGAIN","RBLBANK","REDINGTON","RVNL",
    "SJVN","SONATSOFTW","SUZLON","SYNGENE","TATACOMM",
    "TATAELXSI","TATATECH","TITAGARH","VGUARD","VOLTAS",
    "WELCORP","ZENSARTECH","SCHAEFFLER","SUNDARMFIN","UNOMINDA",
    "TRIDENT","UTIAMC","MCX","DELHIVERY","KAYNES",
]

_CH_SMALLCAP250_FALLBACK: list = [
    "AJANTPHARM","ALKYLAMINE","ANGELONE","ATUL","AVANTIFEED",
    "BALAMINES","BEML","BIRLACORPN","BSOFT","CAMS",
    "CAPLIPOINT","CARBORUNIV","CENTURYPLY","CLEAN","CRAFTSMAN",
    "ECLERX","ENDURANCE","EPIGRAL","EQUITAS","FINEORG",
    "FINOLEXCAB","FORCEMOT","GALAXYSURF","GNFC","GRINDWELL",
    "GSPL","HAPPEMIND","IIFLWAM","ISGEC","JBCHEPHARM",
    "JKPAPER","KAJARIACER","KANSAINER","KIMS","KIRLOSENG",
    "LATENTVIEW","LUXIND","MAHINDCIE","MCX","MSTC",
    "NAZARA","NOCIL","NUVOCO","PAYTM","RADICO",
    "RAILTEL","REPCO","ROUTE","SAFARI","SJVN",
    "SOLARINDS","SPANDANA","SUNTECK","SUPRAJIT","TEAMLEASE",
    "TIMKEN","TINPLATE","TRIDENT","UJJIVANSFB","UTIAMC",
    "VINATIORGA","WABAG","WESTLIFE","MOIL","NBCC",
    "ANUPAM","DIXON","IEX","HFCL","INOXWIND",
]

_CH_SECTORS: dict = {
    "banks": [
        "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK",
        "BAJFINANCE","BAJAJFINSV","INDUSINDBK","BANKBARODA","CANBK",
        "PNB","UNIONBANK","FEDERALBNK","IDFCFIRSTB","BANDHANBNK",
        "RBLBANK","CHOLAFIN","SHRIRAMFIN","MUTHOOTFIN","MANAPPURAM",
        "LICHSGFIN","PNBHOUSING","RECLTD","PFC","HDFCLIFE",
        "SBILIFE","ICICIPRULI","LICI","CANFINHOME","MFSL",
        "EQUITAS","UJJIVANSFB","SPANDANA","REPCO","IIFLWAM",
    ],
    "it": [
        "TCS","INFY","WIPRO","HCLTECH","TECHM",
        "LTIM","LTTS","MPHASIS","COFORGE","PERSISTENT",
        "OFSS","KPITTECH","TATAELXSI","MASTEK","BSOFT",
        "RATEGAIN","ZENSARTECH","SONATSOFTW","CYIENT","HEXAWARE",
        "INTELLECT","HAPPSTMNDS","LATENTVIEW","TATATECH","REDINGTON",
        "ECLERX","ROUTE","NAZARA","IEX",
    ],
    "pharma": [
        "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN",
        "AUROPHARMA","ABBOTINDIA","ALKEM","TORNTPHARM","IPCA",
        "BIOCON","GRANULES","NATCOPHARM","LAURUSLABS","GLENMARK",
        "APOLLOHOSP","FORTIS","METROPOLIS","LALPATHLAB","AJANTPHARM",
        "JBCHEPHARM","CAPLIPOINT","MAXHEALTH","IPCALAB","SYNGENE",
        "SUPRIYA","AVANTIFEED",
    ],
    "metals": [
        "TATASTEEL","JSWSTEEL","HINDALCO","VEDL","COALINDIA",
        "NMDC","SAIL","HINDZINC","NATIONALUM","HINDCOPPER",
        "WELCORP","APLAPOLLO","RATNAMANI","JSPL","JINDALSAW",
        "NAVINFLUOR","DEEPAKNTR","TINPLATE","MOIL","JSL",
        "CARBORUNIV","GRINDWELL","TIMKEN","SCHAEFFLER",
    ],
    "auto": [
        "MARUTI","TATAMOTORS","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT",
        "M&M","ASHOKLEY","TVSMOTOR","MRF","BALKRISIND",
        "MOTHERSON","BOSCHLTD","BHARATFORG","ENDURANCE","CEATLTD",
        "TIINDIA","APOLLOTYRE","CRAFTSMAN","MAHINDCIE","OLECTRA",
        "FORCEMOT","UNOMINDA","SUPRAJIT","SAFARI",
    ],
    "fmcg": [
        "HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR",
        "MARICO","GODREJCP","EMAMILTD","COLPAL","TATACONSUM",
        "RADICO","VBL","UBL","DMART","PAGEIND",
        "BATAINDIA","LUXIND","DEVYANI","WESTLIFE","JUBLFOOD",
        "AVANTIFEED","BALRAMCHIN",
    ],
    "energy": [
        "RELIANCE","ONGC","BPCL","IOC","HPCL",
        "POWERGRID","NTPC","ADANIPOWER","TATAPOWER","ADANIGREEN",
        "TORNTPOWER","CESC","GAIL","PETRONET","IGL",
        "MGL","ATGL","GSPL","SUZLON","NHPC",
        "SJVN","SOLARINDS","INOXWIND","HFCL",
    ],
    "chemicals": [
        "UPL","PIDILITIND","AARTIIND","DEEPAKNTR","NAVINFLUOR",
        "ALKYLAMINE","CLEAN","VINATIORGA","ATUL","NOCIL",
        "TATACHEM","GNFC","PIIND","FINEORG","EPIGRAL",
        "GALAXYSURF","BALAMINES","ANUPAM","SRF","GHCL",
    ],
    "realty": [
        "DLF","GODREJPROP","OBEROIRLTY","PRESTIGE","BRIGADE",
        "SOBHA","SUNTECK","PHOENIXLTD","ANANTRAJ","KOLTEPATIL",
        "LODHA","NUVOCO","IBREALEST","MAHLIFE",
    ],
    "infra": [
        "LT","ABB","SIEMENS","CUMMINSIND","BHEL",
        "BEL","HAL","RAILTEL","IRCTC","IRFC",
        "RVNL","TITAGARH","INDUSTOWER","BHARTIARTL","INDHOTEL",
        "CONCOR","BEML","ISGEC","PATELENG","WABAG",
        "NBCC","KAYNES","MSTC",
    ],
}

_ch_midcap_cache: list = []
_ch_midcap_cache_ts = None
_ch_smallcap_cache: list = []
_ch_smallcap_cache_ts = None


def _get_ch_symbols(universe: str, sector: str, symbols: str) -> list:
    global _ch_midcap_cache, _ch_midcap_cache_ts, _ch_smallcap_cache, _ch_smallcap_cache_ts
    from core.swing_analyzer import NIFTY50, NIFTY_NEXT50

    if universe == "watchlist":
        return [s.strip().upper() for s in symbols.split(",") if s.strip()] if symbols else []

    if universe == "midcap150":
        now = datetime.utcnow()
        if not _ch_midcap_cache or not _ch_midcap_cache_ts or (now - _ch_midcap_cache_ts).total_seconds() > 86400:
            try:
                _ch_midcap_cache = list(_fetch_nse_index("NIFTY%20MIDCAP%20150", 130))
                _ch_midcap_cache_ts = now
            except Exception:
                _ch_midcap_cache = _CH_MIDCAP150_FALLBACK
                _ch_midcap_cache_ts = now
        base_list = _ch_midcap_cache

    elif universe == "smallcap250":
        now = datetime.utcnow()
        if not _ch_smallcap_cache or not _ch_smallcap_cache_ts or (now - _ch_smallcap_cache_ts).total_seconds() > 86400:
            try:
                _ch_smallcap_cache = list(_fetch_nse_index("NIFTY%20SMALLCAP%20250", 200))
                _ch_smallcap_cache_ts = now
            except Exception:
                _ch_smallcap_cache = _CH_SMALLCAP250_FALLBACK
                _ch_smallcap_cache_ts = now
        base_list = _ch_smallcap_cache

    elif universe == "nifty50":
        base_list = list(NIFTY50)
    else:
        base_list = list(NIFTY50) + list(NIFTY_NEXT50)

    if sector and sector in _CH_SECTORS:
        sector_set = set(_CH_SECTORS[sector])
        intersection = [s for s in base_list if s in sector_set]
        return intersection if intersection else _CH_SECTORS[sector]

    return base_list


@app.get("/patterns/cup-handle/analyse")
async def ch_analyse(symbol: str, period: str = "1y"):
    """Analyse a single NSE stock for Cup & Handle pattern (3-stage detection).
    period: 3mo | 6mo | 1y | 2y | 3y | 5y"""
    from core.patterns.cup_handle import analyse as _ch_analyse
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _ch_analyse, symbol.upper().strip(), period)
        return result
    except Exception as e:
        log.error(f"patterns/cup-handle/analyse error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/patterns/cup-handle/scan")
async def ch_scan(universe: str = "nifty100", period: str = "1y",
                  sector: str = "", symbols: str = ""):
    """Scan for Cup & Handle patterns.
    universe: nifty50 | nifty100 | midcap150 | smallcap250 | watchlist
    sector:   banks | it | pharma | metals | auto | fmcg | energy | chemicals | realty | infra
    symbols:  comma-separated list (used when universe=watchlist)
    period:   3mo | 6mo | 1y | 2y"""
    from core.patterns.cup_handle import scan as _ch_scan
    loop = asyncio.get_event_loop()
    sym_list = _get_ch_symbols(universe, sector, symbols)
    if not sym_list:
        return {"count": 0, "scanned": 0, "universe": universe, "sector": sector, "period": period, "results": []}
    try:
        results = await loop.run_in_executor(None, _ch_scan, sym_list, period)
        return {
            "count":    len(results),
            "scanned":  len(sym_list),
            "universe": universe,
            "sector":   sector,
            "period":   period,
            "results":  results,
        }
    except Exception as e:
        log.error(f"patterns/cup-handle/scan error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


_NSE_HOLIDAYS = {
    _dt.date.fromisoformat(d) for d in [
        "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-06",
        "2025-04-14", "2025-04-18", "2025-05-01", "2025-06-07",
        "2025-08-15", "2025-08-27", "2025-10-02", "2025-10-20",
        "2025-10-21", "2025-11-05",
        "2026-01-26", "2026-02-17", "2026-03-03", "2026-04-03",
        "2026-04-14", "2026-05-01", "2026-08-14", "2026-10-02",
        "2026-10-22",
    ]
}

def _nse_expiry_date(candidate: "_dt.date") -> "_dt.date":
    """Shift a candidate expiry backward past weekends and holidays."""
    d = candidate
    while d.weekday() >= 5 or d in _NSE_HOLIDAYS:
        d -= _dt.timedelta(days=1)
    return d


@app.get("/options/past-expiries")
def options_past_expiries(symbol: str = "NIFTY"):
    """
    Return recent expiry dates for the given symbol.
    NIFTY / FINNIFTY → weekly Tuesdays
    BANKNIFTY / MIDCPNIFTY → weekly Wednesdays
    Stocks / others → monthly last-Thursday of each month.
    If an expiry day is a market holiday the date is shifted to the
    previous trading day (NSE rule).
    Returns up to 12 dates in reverse-chronological order (most recent first),
    from 90 days ago up to 7 days ahead (current/next week included).
    """
    sym   = symbol.upper()
    today = _dt.date.today()

    weekly = {"NIFTY": 1, "BANKNIFTY": 2, "MIDCPNIFTY": 2, "FINNIFTY": 1}

    expiries: list[str] = []
    seen:     set[str]  = set()          # deduplicate after holiday shifts

    if sym in weekly:
        target_wd = weekly[sym]
        d = today + _dt.timedelta(days=7)
        while d >= today - _dt.timedelta(days=90):
            if d.weekday() == target_wd:
                actual = _nse_expiry_date(d)
                iso = actual.isoformat()
                if iso not in seen:
                    expiries.append(iso)
                    seen.add(iso)
            d -= _dt.timedelta(days=1)
    else:
        import calendar
        yr, mo = today.year, today.month
        for _ in range(12):
            last_day = calendar.monthrange(yr, mo)[1]
            d = _dt.date(yr, mo, last_day)
            while d.weekday() != 3:          # last Thursday of month
                d -= _dt.timedelta(days=1)
            actual = _nse_expiry_date(d)
            if actual <= today + _dt.timedelta(days=7):
                iso = actual.isoformat()
                if iso not in seen:
                    expiries.append(iso)
                    seen.add(iso)
            mo -= 1
            if mo == 0:
                mo = 12; yr -= 1

    expiries = expiries[:12]
    return {"symbol": sym, "expiries": expiries}


@app.get("/options/monitor")
def options_monitor(
    entry_ltp: float,
    stop_price: float,
    target1_price: float,
    target2_price: float,
    current_ltp: float,
    lots: int = 1,
    lot_size: int = 50,
    direction: str = "CE",
    t1_hit: bool = False,
):
    """Evaluate live option P&L and recommend HOLD / EXIT_STOP / EXIT_T1 / EXIT_T2."""
    try:
        position = {
            "direction":     direction,
            "entry_ltp":     entry_ltp,
            "stop_price":    stop_price,
            "target1_price": target1_price,
            "target2_price": target2_price,
            "lots":          lots,
            "lot_size":      lot_size,
            "t1_hit":        t1_hit,
        }
        return _oc_monitor(position, current_ltp)
    except Exception as e:
        log.error(f"options/monitor error: {e}")
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# Paper Trading — virtual portfolio simulator (stocks + option contracts)
# ══════════════════════════════════════════════════════════════════════════════
from execution.paper_trader import (
    get_account     as _pt_account,
    place_order     as _pt_place,
    close_position  as _pt_close,
    list_positions  as _pt_list,
    unrealized_pnl  as _pt_mark,
    reset_account   as _pt_reset,
    DEFAULT_CAPITAL as _PT_DEFAULT_CAPITAL,
)


_ltp_cache: dict = {}   # key → {"data": {...}, "ts": float}
_LTP_TTL = 8.0          # seconds — Angel One LTP cache; frontend refreshes every 10 s

def _paper_stock_ltps(symbols: list) -> dict:
    """LTPs for NSE equity symbols → {symbol: ltp}."""
    cache_key = "stk:" + ",".join(sorted(s.upper() for s in symbols))
    entry = _ltp_cache.get(cache_key)
    if entry and (_time.time() - entry["ts"]) < _LTP_TTL:
        return entry["data"]
    try:
        sym_set   = {s.upper() for s in symbols}
        token_map = {}   # token → symbol
        for stock in _load_all_eq_stocks():
            name = stock["symbol"].upper()
            if name in sym_set and stock["token"] not in token_map:
                token_map[stock["token"]] = name
        if not token_map:
            return {}
        ltp_by_token = get_provider().get_ltp(list(token_map.keys()), "NSE")
        prices = {token_map[tok]: ltp for tok, ltp in ltp_by_token.items()}
        _ltp_cache[cache_key] = {"data": prices, "ts": _time.time()}
        return prices
    except Exception as e:
        log.warning(f"paper stock ltp error: {e}")
        return {}


def _paper_option_ltps(tokens: list) -> dict:
    """LTPs for NFO option tokens → {token: ltp}."""
    cache_key = "opt:" + ",".join(sorted(str(t) for t in tokens))
    entry = _ltp_cache.get(cache_key)
    if entry and (_time.time() - entry["ts"]) < _LTP_TTL:
        return entry["data"]
    try:
        prices = get_provider().get_option_ltp([str(t) for t in tokens])
        _ltp_cache[cache_key] = {"data": prices, "ts": _time.time()}
        return prices
    except Exception as e:
        log.warning(f"paper option ltp error: {e}")
        return {}


def _paper_ltp(instrument: str, symbol: str, token=None):
    if instrument.upper() == "OPTION" and token:
        return _paper_option_ltps([token]).get(str(token))
    return _paper_stock_ltps([symbol.upper()]).get(symbol.upper())


def _paper_user_id(request: Request) -> str:
    """Extract user_id forwarded by Node after JWT verification."""
    return request.headers.get("X-User-Id", "anonymous")


@app.get("/paper/account")
def paper_account(request: Request):
    """Virtual account summary: cash, realized P&L, position counts."""
    from storage.sqlite_store import get_conn
    try:
        return _pt_account(get_conn(), _paper_user_id(request))
    except Exception as e:
        log.error(f"paper/account error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/paper/positions")
def paper_positions(request: Request):
    """Open positions marked to live LTPs with unrealized P&L."""
    from storage.sqlite_store import get_conn
    try:
        user_id   = _paper_user_id(request)
        conn      = get_conn()
        positions = _pt_list(conn, user_id, "OPEN")

        stock_syms = sorted({p["symbol"] for p in positions if p["instrument"] == "STOCK"})
        opt_tokens = sorted({p["token"]  for p in positions if p["instrument"] == "OPTION" and p["token"]})
        stock_ltps = _paper_stock_ltps(stock_syms)   if stock_syms else {}
        opt_ltps   = _paper_option_ltps(opt_tokens)  if opt_tokens else {}

        total_unrealized = 0.0
        priced = 0
        for p in positions:
            ltp = (opt_ltps.get(str(p["token"])) if p["instrument"] == "OPTION"
                   else stock_ltps.get(p["symbol"]))
            p.update(_pt_mark(p, ltp))
            if p["pnl"] is not None:
                total_unrealized += p["pnl"]
                priced += 1

        return {"positions": positions,
                "unrealized_pnl": round(total_unrealized, 2),
                "priced": priced, "count": len(positions)}
    except Exception as e:
        log.error(f"paper/positions error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/paper/history")
def paper_history(request: Request):
    """Closed trades, most recent first."""
    from storage.sqlite_store import get_conn
    try:
        return {"trades": _pt_list(get_conn(), _paper_user_id(request), "CLOSED")}
    except Exception as e:
        log.error(f"paper/history error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/paper/quote")
def paper_quote(instrument: str, symbol: str = "", token: str = ""):
    """Live LTP preview before placing a paper order."""
    try:
        ltp = _paper_ltp(instrument, symbol, token or None)
        return {"instrument": instrument.upper(), "symbol": symbol.upper(),
                "token": token or None, "ltp": ltp}
    except Exception as e:
        log.error(f"paper/quote error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/paper/order")
def paper_order(request: Request, payload: dict):
    """
    Place a simulated order. Body:
      {instrument: STOCK|OPTION, symbol, side: BUY|SELL,
       qty (stocks) | lots+lot_size (options),
       token?, underlying?, expiry?, strike?, option_type?, price? (manual override)}
    Executes at live LTP when price is omitted.
    """
    from storage.sqlite_store import get_conn
    try:
        user_id    = _paper_user_id(request)
        instrument = (payload.get("instrument") or "").upper()
        symbol     = (payload.get("symbol") or "").strip().upper()
        if not symbol:
            return JSONResponse(status_code=400, content={"error": "symbol is required"})

        lots     = payload.get("lots")
        lot_size = payload.get("lot_size")
        if instrument == "OPTION":
            if not lots or not lot_size:
                return JSONResponse(status_code=400, content={"error": "lots and lot_size are required for options"})
            qty = int(lots) * int(lot_size)
        else:
            qty = int(payload.get("qty") or 0)

        price = payload.get("price")
        price = float(price) if price else _paper_ltp(instrument, symbol, payload.get("token"))

        result = _pt_place(
            get_conn(),
            user_id=user_id,
            instrument=instrument, symbol=symbol,
            side=payload.get("side", ""), qty=qty, price=price,
            token=payload.get("token"), underlying=payload.get("underlying"),
            expiry=payload.get("expiry"), strike=payload.get("strike"),
            option_type=payload.get("option_type"),
            lots=int(lots) if lots else None,
            lot_size=int(lot_size) if lot_size else None,
        )
        if "error" in result:
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        log.error(f"paper/order error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/paper/close/{trade_id}")
def paper_close(trade_id: int, request: Request, payload: dict = None):
    """Close an open position at live LTP (or manual price override in body)."""
    from storage.sqlite_store import get_conn
    try:
        user_id = _paper_user_id(request)
        conn    = get_conn()
        row = conn.execute(
            "SELECT instrument, symbol, token FROM paper_trades WHERE id = ? AND status = 'OPEN' AND user_id = ?",
            (trade_id, user_id),
        ).fetchone()
        if not row:
            return JSONResponse(status_code=404, content={"error": "Open position not found"})

        price = (payload or {}).get("price")
        price = float(price) if price else _paper_ltp(row["instrument"], row["symbol"], row["token"])

        result = _pt_close(conn, trade_id, price, user_id)
        if "error" in result:
            return JSONResponse(status_code=400, content=result)
        return result
    except Exception as e:
        log.error(f"paper/close error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/paper/reset")
def paper_reset(request: Request, payload: dict = None):
    """Wipe all paper trades and restore virtual cash. Body: {capital?}"""
    from storage.sqlite_store import get_conn
    try:
        user_id = _paper_user_id(request)
        capital = float((payload or {}).get("capital") or _PT_DEFAULT_CAPITAL)
        return _pt_reset(get_conn(), user_id, capital)
    except Exception as e:
        log.error(f"paper/reset error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# Daily Reports
# ══════════════════════════════════════════════════════════════════════════════
from storage.sqlite_store import list_reports, get_report, upsert_report, delete_report as _db_delete_report

_report_generated_date: str = None   # tracks which date we've already auto-generated


def _generate_report_sync(date_str: str = None) -> dict:
    import yfinance as yf
    now_ist  = datetime.utcnow() + timedelta(hours=5, minutes=30)
    date_str = date_str or now_ist.strftime("%Y-%m-%d")

    # ── EOD price data from yfinance ─────────────────────────────────────────
    ticker = yf.Ticker("^NSEI")
    hist   = ticker.history(period="5d", interval="1d")
    hist.index = hist.index.normalize()
    import datetime as _dt
    target = _dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    today_row = hist[hist.index.date == target]

    day_ohlc = None
    if not today_row.empty:
        r = today_row.iloc[0]
        day_ohlc = {
            "open":  round(float(r["Open"]),  2),
            "high":  round(float(r["High"]),  2),
            "low":   round(float(r["Low"]),   2),
            "close": round(float(r["Close"]), 2),
        }

    # ── Prev close for gap calc ───────────────────────────────────────────────
    prev_rows = hist[hist.index.date < target]
    prev_close = round(float(prev_rows.iloc[-1]["Close"]), 2) if not prev_rows.empty else None
    gap      = round(day_ohlc["open"] - prev_close, 2) if day_ohlc and prev_close else None
    gap_pct  = round(gap / prev_close * 100, 2)         if gap and prev_close      else None
    net_chg  = round(day_ohlc["close"] - prev_close, 2) if day_ohlc and prev_close else None
    net_pct  = round(net_chg / prev_close * 100, 2)     if net_chg and prev_close  else None

    # ── CPR — computed from prev_ohlc (same logic as get_trade_flow) ─────────
    cpr      = None
    prev_ohlc = trade_flow_data.get("prev_ohlc")
    if prev_ohlc:
        H, L, C  = prev_ohlc["high"], prev_ohlc["low"], prev_ohlc["close"]
        PP       = round((H + L + C) / 3, 2)
        _bc      = round((H + L) / 2, 2)
        _tc      = round(2 * PP - _bc, 2)
        TC, BC   = max(_tc, _bc), min(_tc, _bc)
        cpr = {
            "pp":    PP,
            "tc":    TC,
            "bc":    BC,
            "r1":    round(2 * PP - L, 2),
            "r2":    round(PP + (H - L), 2),
            "r3":    round(H + 2 * (PP - L), 2),
            "s1":    round(2 * PP - H, 2),
            "s2":    round(PP - (H - L), 2),
            "s3":    round(L - 2 * (H - PP), 2),
            "width": round(TC - BC, 2),
        }

    # ── Scenario — derived from stored open/orb/cpr ───────────────────────────
    orb  = trade_flow_data.get("orb")
    vix  = trade_flow_data.get("india_vix")
    scen = None
    nifty_open = trade_flow_data.get("nifty_open")
    if nifty_open and cpr:
        op = ("above_tc" if nifty_open > cpr["tc"]
              else ("below_bc" if nifty_open < cpr["bc"] else "inside_cpr"))
        if orb:
            if   orb["low"]  > cpr["tc"]:  ov = "above_tc"
            elif orb["high"] < cpr["bc"]:  ov = "below_bc"
            else:                          ov = "straddles"
            if   op == "above_tc" and ov == "above_tc":  scen = "bull"
            elif op == "below_bc" and ov == "below_bc":  scen = "bear"
            elif ov == "straddles":                      scen = "conditional"
            else:                                        scen = "skip"
        else:
            scen = ("bull" if op == "above_tc" else
                    ("bear" if op == "below_bc" else "skip"))

    # ── Levels tested (within 10 pts of day H/L) ─────────────────────────────
    levels_tested = []
    if day_ohlc and cpr:
        check = {
            "R1": cpr.get("r1"), "R2": cpr.get("r2"), "R3": cpr.get("r3"),
            "TC": cpr.get("tc"), "BC": cpr.get("bc"), "PP": cpr.get("pp"),
            "S1": cpr.get("s1"), "S2": cpr.get("s2"), "S3": cpr.get("s3"),
        }
        for name, price in check.items():
            if price and (abs(day_ohlc["high"] - price) <= 10 or abs(day_ohlc["low"] - price) <= 10):
                levels_tested.append(name)

    report = {
        "prev_close":     prev_close,
        "gap":            gap,
        "gap_pct":        gap_pct,
        "gap_direction":  "up" if gap and gap > 0 else ("down" if gap and gap < 0 else "flat"),
        "day_ohlc":       day_ohlc,
        "net_change":     net_chg,
        "net_change_pct": net_pct,
        "india_vix":      vix,
        "scenario":       scen,
        "orb":            {"high": orb["high"], "low": orb["low"]} if orb else None,
        "cpr":            cpr,
        "levels_tested":  levels_tested,
    }

    conn = get_conn()
    ts   = upsert_report(conn, date_str, report)
    conn.close()
    log.info(f"[REPORT] Generated for {date_str}")
    return {"date": date_str, "generated_at": ts, **report}


def _maybe_auto_generate_report():
    global _report_generated_date
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    if now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 30):
        return
    today = now_ist.strftime("%Y-%m-%d")
    if _report_generated_date == today:
        return
    conn = get_conn()
    existing = get_report(conn, today)
    conn.close()
    if existing:
        _report_generated_date = today
        return
    try:
        _generate_report_sync(today)
        _report_generated_date = today
    except Exception as e:
        log.warning(f"[REPORT] Auto-generate failed: {e}")


@app.get("/reports")
def reports_list():
    conn = get_conn()
    data = list_reports(conn)
    conn.close()
    return {"reports": data}


@app.get("/reports/{date}")
def report_get(date: str):
    conn = get_conn()
    r    = get_report(conn, date)
    conn.close()
    if not r:
        return {"error": f"No report for {date}"}
    return r


@app.post("/reports/generate")
async def report_generate(date: str = None):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _generate_report_sync, date)
        return result
    except Exception as e:
        log.error(f"[REPORT] generate error: {e}")
        return {"error": str(e)}


@app.delete("/reports/{date}")
def report_delete(date: str):
    conn = get_conn()
    ok   = _db_delete_report(conn, date)
    conn.close()
    return {"deleted": ok, "date": date}


# ══════════════════════════════════════════════════════════════════════════════
# CPR Levels — multi-timeframe, multi-symbol CPR for the CPR Monitor page
# ══════════════════════════════════════════════════════════════════════════════

def _parse_option_symbol(symbol: str):
    """Parse 'NIFTY24000CE' or 'RELIANCE1600CE' → ('NIFTY', 24000.0, 'CE'), or None."""
    import re
    m = re.match(r'^([A-Z]+)(\d+(?:\.\d+)?)(CE|PE)$', symbol.upper().strip())
    if not m:
        return None
    return m.group(1), float(m.group(2)), m.group(3)


# ── CPR levels cache (keyed by period so OHLC isn't re-fetched intraday) ─────
_cpr_cache: dict = {}


def _compute_atr(df, periods: int = 14) -> float | None:
    """Simple average true range over up to `periods` bars.
    Always called on daily 1-month bars for scale consistency across timeframes.
    """
    try:
        if len(df) < 3:
            return None
        h = df["High"].values.astype(float)
        l = df["Low"].values.astype(float)
        c = df["Close"].values.astype(float)
        tr = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
              for i in range(1, len(h))]
        n = min(periods, len(tr))
        return round(float(sum(tr[-n:]) / n), 2)
    except Exception:
        return None


def _cpr_cache_key(symbol: str, timeframe: str, today_ist) -> tuple:
    import datetime as _dt
    if timeframe == "daily":
        return (symbol.upper(), "daily", str(today_ist))
    elif timeframe == "weekly":
        week_start = today_ist - _dt.timedelta(days=today_ist.weekday())
        return (symbol.upper(), "weekly", str(week_start))
    elif timeframe == "monthly":
        return (symbol.upper(), "monthly", f"{today_ist.year}-{today_ist.month:02d}")
    return (symbol.upper(), timeframe, str(today_ist))


def _evict_cpr_cache(today_ist) -> None:
    import datetime as _dt
    week_start = today_ist - _dt.timedelta(days=today_ist.weekday())
    month_key  = f"{today_ist.year}-{today_ist.month:02d}"
    stale = [k for k in _cpr_cache
             if (k[1] == "daily"   and k[2] != str(today_ist))
             or (k[1] == "weekly"  and k[2] != str(week_start))
             or (k[1] == "monthly" and k[2] != month_key)]
    for k in stale:
        del _cpr_cache[k]


def _calc_cpr(H: float, L: float, C: float) -> dict:
    PP    = round((H + L + C) / 3, 2)
    _bc   = round((H + L) / 2, 2)
    _tc   = round(2 * PP - _bc, 2)
    TC    = round(max(_tc, _bc), 2)
    BC    = round(min(_tc, _bc), 2)
    return {
        "pp":    PP,
        "tc":    TC,
        "bc":    BC,
        "r1":    round(2 * PP - L, 2),
        "r2":    round(PP + (H - L), 2),
        "r3":    round(H + 2 * (PP - L), 2),
        "s1":    round(2 * PP - H, 2),
        "s2":    round(PP - (H - L), 2),
        "s3":    round(L - 2 * (H - PP), 2),
        "width": round(TC - BC, 2),
    }


_INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}

def _cpr_levels_option_sync(symbol: str, underlying: str, strike: float, opt_type: str,
                             timeframe: str, chain_expiry: str = "") -> dict:
    """CPR levels for a specific option contract (NIFTY24000CE, RELIANCE1600CE etc.)."""
    import datetime as _dt

    IST     = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)
    today   = now_ist.date()

    try:
        lookup_expiry = chain_expiry.strip().upper() if chain_expiry else None
        if underlying.upper() in _INDEX_UNDERLYINGS:
            token, sapi_sym, expiry = im.get_option_token(strike, opt_type, expiry=lookup_expiry)
            if not token:
                token, sapi_sym, expiry = im.get_option_token(strike, opt_type)
        else:
            token, sapi_sym, expiry = im.get_stock_option_token(underlying, strike, opt_type, expiry=lookup_expiry)
            if not token:
                token, sapi_sym, expiry = im.get_stock_option_token(underlying, strike, opt_type)
        if not token:
            return {"error": f"Option not found: {symbol}. Strike/expiry may not be in InstrumentMaster."}

        _evict_cpr_cache(today)
        cache_key = _cpr_cache_key(f"{symbol}@{expiry}", "daily", today)
        if cache_key in _cpr_cache:
            return {**_cpr_cache[cache_key], "ltp": None}

        expected_prev = today - _dt.timedelta(days=1)
        while expected_prev.weekday() >= 5:
            expected_prev -= _dt.timedelta(days=1)
        from_dt    = expected_prev.strftime("%Y-%m-%d 09:15")
        to_dt      = expected_prev.strftime("%Y-%m-%d 15:30")
        date_label = expected_prev.strftime("%Y-%m-%d")

        H = L = C = None
        for interval in ("ONE_DAY", "FIVE_MINUTE"):
            df = get_provider().get_candles(token, "NFO", interval, from_dt, to_dt)
            if df.empty:
                continue
            if interval == "ONE_DAY":
                H = float(df["High"].iloc[-1])
                L = float(df["Low"].iloc[-1])
                C = float(df["Close"].iloc[-1])
            else:
                H = float(df["High"].max())
                L = float(df["Low"].min())
                C = float(df["Close"].iloc[-1])
            log.info(f"[CPR-OPTION] {symbol} {interval} OHLC: H={H} L={L} C={C}")
            break

        if H is None:
            return {"error": f"No prev-day OHLC for {symbol} (expiry {expiry}). Option may not have traded."}

        cpr = _calc_cpr(H, L, C)
        atr = max(round(C * 0.20, 2), 5.0)

        payload = {
            "symbol":    symbol.upper(),
            "timeframe": "daily",
            "ohlc":      {"high": round(H, 2), "low": round(L, 2), "close": round(C, 2), "date": date_label},
            "cpr":       cpr,
            "atr":       atr,
            "expiry":    expiry,
        }
        _cpr_cache[cache_key] = payload
        log.info(f"[CPR-OPTION] {symbol} ({expiry}): H={H} L={L} C={C} CPR width={cpr['width']}")
        return {**payload, "ltp": None}

    except Exception as e:
        log.error(f"[CPR-OPTION] {symbol}: {e}")
        return {"error": str(e)}


def _candles_for_cpr_option_sync(symbol: str, underlying: str, strike: float, opt_type: str, timeframe: str) -> dict:
    """5-min intraday candles (or daily for weekly/monthly) for an option via provider."""
    import datetime as _dt
    _IST_OFF = 19800

    IST     = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)
    today   = now_ist.date()

    try:
        if underlying.upper() in _INDEX_UNDERLYINGS:
            token, _, expiry = im.get_option_token(strike, opt_type)
        else:
            token, _, expiry = im.get_stock_option_token(underlying, strike, opt_type)
        if not token:
            return {"candles": [], "interval": "5m", "count": 0,
                    "data_source": "provider", "as_of": None, "error": "Token not found"}

        if timeframe == "daily":
            from_dt  = today.strftime("%Y-%m-%d 09:15")
            to_dt    = today.strftime("%Y-%m-%d 15:30")
            interval = "FIVE_MINUTE"
        else:
            from_d   = (today - _dt.timedelta(days=today.weekday())) if timeframe == "weekly" else today.replace(day=1)
            from_dt  = from_d.strftime("%Y-%m-%d 09:15")
            to_dt    = today.strftime("%Y-%m-%d 15:30")
            interval = "ONE_DAY"

        df = get_provider().get_candles(token, "NFO", interval, from_dt, to_dt)
        intv_label = "5m" if timeframe == "daily" else "1d"
        if df.empty:
            return {"candles": [], "interval": intv_label, "count": 0,
                    "data_source": "provider", "as_of": None}

        candles = []
        for _, row in df.iterrows():
            try:
                ts = _dt.datetime.strptime(row["DateTime"], "%Y-%m-%d %H:%M")
                epoch = (int(ts.timestamp()) + _IST_OFF) if timeframe == "daily" else int(_dt.datetime(ts.year, ts.month, ts.day).timestamp())
                candles.append({
                    "time":  epoch,
                    "open":  round(float(row["Open"]),  2),
                    "high":  round(float(row["High"]),  2),
                    "low":   round(float(row["Low"]),   2),
                    "close": round(float(row["Close"]), 2),
                })
            except Exception:
                continue

        as_of = (candles[-1]["time"] - _IST_OFF) if (candles and timeframe == "daily") else (candles[-1]["time"] if candles else None)
        return {"candles": candles, "interval": intv_label, "count": len(candles),
                "data_source": "provider", "as_of": as_of}

    except Exception as e:
        log.error(f"[CANDLES-OPTION] {symbol}/{timeframe}: {e}")
        return {"candles": [], "interval": "5m", "count": 0,
                "data_source": "provider", "as_of": None, "error": str(e)}


def _cpr_levels_sync(symbol: str, timeframe: str, expiry: str = "") -> dict:
    _opt = _parse_option_symbol(symbol)
    if _opt:
        return _cpr_levels_option_sync(symbol, _opt[0], _opt[1], _opt[2], timeframe, chain_expiry=expiry)

    import yfinance as yf
    import datetime as _dt

    IST     = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)
    today   = now_ist.date()

    is_nifty = symbol.upper() in ("NIFTY", "^NSEI", "NIFTY50")
    yf_sym   = "^NSEI" if is_nifty else f"{symbol.upper()}.NS"

    # ── Serve from cache when available (LTP still recomputed live) ───────────
    _evict_cpr_cache(today)
    cache_key = _cpr_cache_key(symbol, timeframe, today)
    if cache_key in _cpr_cache:
        cached = _cpr_cache[cache_key]
        # For daily NIFTY: don't serve cache if stored OHLC date is stale.
        # yfinance can lag by 1 trading day; if SmartAPI also failed the first
        # time, the stale date gets stuck in cache all day. Evict and re-fetch.
        _serve_cache = True
        if timeframe == "daily" and is_nifty:
            _exp = today - _dt.timedelta(days=1)
            while _exp.weekday() >= 5:
                _exp -= _dt.timedelta(days=1)
            try:
                _cached_d = _dt.datetime.strptime(cached["ohlc"]["date"], "%Y-%m-%d").date()
            except Exception:
                _cached_d = _dt.date(2000, 1, 1)
            if _cached_d < _exp:
                log.info(f"[CPR] Cache has stale OHLC {_cached_d} (want {_exp}) — evicting, re-fetching")
                del _cpr_cache[cache_key]
                _serve_cache = False
        if _serve_cache:
            ltp = None
            if is_nifty:
                spot = market_state.get(SPOT_TOKEN)
                if spot and spot.get("price"):
                    ltp = round(float(spot["price"]), 2)
            if ltp is None:
                try:
                    intra = yf.Ticker(yf_sym).history(period="1d", interval="1m")
                    if not intra.empty:
                        ltp = round(float(intra["Close"].iloc[-1]), 2)
                except Exception:
                    pass
            return {**cached, "ltp": ltp}

    try:
        # ── Fetch prev-period OHLC ────────────────────────────────────────────
        if timeframe == "daily":
            df = yf.Ticker(yf_sym).history(period="10d", interval="1d")
            df.index = df.index.normalize()
            past = df[df.index.date < today]
            if past.empty:
                return {"error": "No previous day data available"}
            row        = past.iloc[-1]
            H, L, C    = float(row.High), float(row.Low), float(row.Close)
            date_label = past.index[-1].strftime("%Y-%m-%d")

            # yfinance for ^NSEI lags by 1 trading day — if the date is behind the
            # most recent weekday, fall back to SmartAPI getCandleData (exchange data).
            if is_nifty:
                expected_prev = today - _dt.timedelta(days=1)
                while expected_prev.weekday() >= 5:
                    expected_prev -= _dt.timedelta(days=1)
                yf_date = _dt.datetime.strptime(date_label, "%Y-%m-%d").date()
                if yf_date < expected_prev:
                    log.info(f"[CPR] yfinance returned {yf_date}, expected {expected_prev} — trying provider")
                    try:
                        _fut_tok = im.get_nifty_futures_token() or SPOT_TOKEN
                        _from_dt = expected_prev.strftime("%Y-%m-%d 09:15")
                        _to_dt   = expected_prev.strftime("%Y-%m-%d 15:30")
                        _attempts = [
                            ("NSE", SPOT_TOKEN, "ONE_DAY"),
                            ("NFO", _fut_tok,   "ONE_DAY"),
                            ("NSE", SPOT_TOKEN, "ONE_HOUR"),
                            ("NFO", _fut_tok,   "ONE_HOUR"),
                        ]
                        for _exch, _tok, _intv in _attempts:
                            try:
                                _df = get_provider().get_candles(_tok, _exch, _intv, _from_dt, _to_dt)
                                if _df.empty:
                                    continue
                                if _intv == "ONE_DAY":
                                    H = float(_df["High"].iloc[-1])
                                    L = float(_df["Low"].iloc[-1])
                                    C = float(_df["Close"].iloc[-1])
                                else:
                                    H = float(_df["High"].max())
                                    L = float(_df["Low"].min())
                                    C = float(_df["Close"].iloc[-1])
                                date_label = expected_prev.strftime("%Y-%m-%d")
                                log.info(f"[CPR] provider OHLC ({_exch}/{_intv}): H={H} L={L} C={C} [{date_label}]")
                                break
                            except Exception as _att_err:
                                log.debug(f"[CPR] provider {_exch}/{_intv} failed: {_att_err}")
                    except Exception as _sapi_err:
                        log.warning(f"[CPR] provider fallback failed: {_sapi_err}")

            # Keep trade_flow_data in sync so other endpoints (trade-flow, WebSocket) also use correct prev OHLC
            if is_nifty:
                trade_flow_data["prev_ohlc"] = {"high": round(H, 2), "low": round(L, 2), "close": round(C, 2), "date": date_label}

        elif timeframe == "weekly":
            df = yf.Ticker(yf_sym).history(period="3mo", interval="1wk")
            if len(df) < 2:
                return {"error": "Not enough weekly data"}
            df.index    = df.index.normalize()
            week_start  = today - _dt.timedelta(days=today.weekday())
            past_weeks  = df[df.index.date < week_start]
            if past_weeks.empty:
                past_weeks = df.iloc[:-1]
            row        = past_weeks.iloc[-1]
            H, L, C    = float(row.High), float(row.Low), float(row.Close)
            date_label = "W/E " + past_weeks.index[-1].strftime("%d %b %Y")

        elif timeframe == "monthly":
            df = yf.Ticker(yf_sym).history(period="6mo", interval="1mo")
            if len(df) < 2:
                return {"error": "Not enough monthly data"}
            df.index    = df.index.normalize()
            month_start = today.replace(day=1)
            past_months = df[df.index.date < month_start]
            if past_months.empty:
                past_months = df.iloc[:-1]
            row        = past_months.iloc[-1]
            H, L, C    = float(row.High), float(row.Low), float(row.Close)
            date_label = past_months.index[-1].strftime("%b %Y")

        else:
            return {"error": f"Unknown timeframe: {timeframe}"}

        cpr = _calc_cpr(H, L, C)

        # ── ATR on daily 1-month bars — used by frontend as a proximity scale unit.
        # Always daily bars regardless of CPR timeframe so the unit is consistent.
        # NIFTY ~24000: daily ATR ≈ 200 pts. Fallback: 1% of close.
        atr: float = round(C * 0.01, 2)
        try:
            atr_df   = yf.Ticker(yf_sym).history(period="1mo", interval="1d")
            computed = _compute_atr(atr_df)
            if computed:
                atr = computed
        except Exception:
            pass

        # ── LTP ───────────────────────────────────────────────────────────────
        ltp = None
        if is_nifty:
            spot = market_state.get(SPOT_TOKEN)
            if spot and spot.get("price"):
                ltp = round(float(spot["price"]), 2)
        if ltp is None:
            try:
                intra = yf.Ticker(yf_sym).history(period="1d", interval="1m")
                if not intra.empty:
                    ltp = round(float(intra["Close"].iloc[-1]), 2)
            except Exception:
                pass

        # ── Cache fixed data (ltp excluded — changes every call) ──────────────
        payload = {
            "symbol":    symbol.upper(),
            "timeframe": timeframe,
            "ohlc":      {"high": round(H, 2), "low": round(L, 2), "close": round(C, 2), "date": date_label},
            "cpr":       cpr,
            "atr":       atr,
        }
        # Don't cache daily NIFTY if OHLC is still stale (SmartAPI also failed).
        # Next request will re-fetch and try again instead of serving bad data all day.
        _ok_to_cache = True
        if timeframe == "daily" and is_nifty:
            try:
                _fetched_d = _dt.datetime.strptime(date_label, "%Y-%m-%d").date()
                _exp2 = today - _dt.timedelta(days=1)
                while _exp2.weekday() >= 5:
                    _exp2 -= _dt.timedelta(days=1)
                if _fetched_d < _exp2:
                    log.warning(f"[CPR] OHLC still stale ({date_label}, want {_exp2}) — skipping cache, will retry next request")
                    _ok_to_cache = False
            except Exception:
                pass
        if _ok_to_cache:
            _cpr_cache[cache_key] = payload
        return {**payload, "ltp": ltp}

    except Exception as e:
        log.error(f"[CPR-LEVELS] {symbol}/{timeframe}: {e}")
        return {"error": str(e)}


@app.get("/cpr-levels")
async def cpr_levels(symbol: str = "NIFTY", timeframe: str = "daily", expiry: str = ""):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _cpr_levels_sync, symbol, timeframe, expiry)
    except Exception as e:
        log.error(f"[CPR-LEVELS] endpoint error: {e}")
        return {"error": str(e)}


def _candles_for_cpr_sync(symbol: str, timeframe: str) -> dict:
    _opt = _parse_option_symbol(symbol)
    if _opt:
        return _candles_for_cpr_option_sync(symbol, _opt[0], _opt[1], _opt[2], timeframe)

    import yfinance as yf
    import datetime as _dt
    import pandas as pd

    IST     = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    now_ist = _dt.datetime.now(IST)
    today   = now_ist.date()
    _IST_OFF = 19800  # +5h30m in seconds for chart display

    is_nifty = symbol.upper() in ("NIFTY", "^NSEI", "NIFTY50")
    yf_sym   = "^NSEI" if is_nifty else f"{symbol.upper()}.NS"

    try:
        if timeframe == "daily":
            df = yf.Ticker(yf_sym).history(period="1d", interval="5m")
            df = df.dropna()
            if df.empty:
                return {"candles": [], "interval": "5m", "count": 0, "data_source": "yfinance", "as_of": None}
            try:
                df.index = df.index.tz_convert("Asia/Kolkata")
                df = df.between_time("09:15", "15:30")
            except Exception:
                pass
            candles = []
            for ts, row in df.iterrows():
                candles.append({
                    "time":  int(ts.timestamp()) + _IST_OFF,
                    "open":  round(float(row["Open"]),  2),
                    "high":  round(float(row["High"]),  2),
                    "low":   round(float(row["Low"]),   2),
                    "close": round(float(row["Close"]), 2),
                })
            as_of_utc = (candles[-1]["time"] - _IST_OFF) if candles else None
            return {"candles": candles, "interval": "5m", "count": len(candles),
                    "data_source": "yfinance", "as_of": as_of_utc}

        else:
            period = "3mo" if timeframe == "monthly" else "1mo"
            df = yf.Ticker(yf_sym).history(period=period, interval="1d")
            df = df.dropna()
            if df.empty:
                return {"candles": [], "interval": "1d", "count": 0, "data_source": "yfinance", "as_of": None}
            try:
                df.index = df.index.normalize()
            except Exception:
                pass
            if timeframe == "weekly":
                week_start = today - _dt.timedelta(days=today.weekday())
                df = df[df.index.date >= week_start]
            elif timeframe == "monthly":
                month_start = today.replace(day=1)
                df = df[df.index.date >= month_start]
            candles = []
            for ts, row in df.iterrows():
                try:
                    day_ts = int(pd.Timestamp(str(ts.date())).timestamp())
                    candles.append({
                        "time":  day_ts,
                        "open":  round(float(row["Open"]),  2),
                        "high":  round(float(row["High"]),  2),
                        "low":   round(float(row["Low"]),   2),
                        "close": round(float(row["Close"]), 2),
                    })
                except Exception:
                    pass
            as_of_utc = candles[-1]["time"] if candles else None  # daily bars: UTC midnight epoch
            return {"candles": candles, "interval": "1d", "count": len(candles),
                    "data_source": "yfinance", "as_of": as_of_utc}

    except Exception as e:
        log.error(f"[CANDLES-FOR-CPR] {symbol}/{timeframe}: {e}")
        return {"candles": [], "interval": "5m", "count": 0,
                "data_source": "yfinance", "as_of": None, "error": str(e)}


@app.get("/candles-for-cpr")
async def candles_for_cpr(symbol: str = "NIFTY", timeframe: str = "daily"):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _candles_for_cpr_sync, symbol, timeframe)
    except Exception as e:
        log.error(f"[CANDLES-FOR-CPR] endpoint error: {e}")
        return {"candles": [], "interval": "5m", "count": 0,
                "data_source": "yfinance", "as_of": None, "error": str(e)}


# ── Node management (called by launcher when Node is offline) ──────────────────
# These live on Python so they work even when the Node server is stopped.
# Browser hits /api/mgmt/... → nginx strips /api/ → Python receives /mgmt/...

PM2_ENV = {**os.environ, "PATH": f"/usr/local/bin:/usr/bin:/bin:{os.environ.get('PATH', '')}"}
PM2_NAMES = {"node": "tradezen-node", "python": "tradezen-python"}

def _check_token(request: Request) -> bool:
    token = os.environ.get("ADMIN_TOKEN", "")
    return bool(token) and request.headers.get("x-admin-token", "").strip() == token

def _pm2(cmd: str) -> dict:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15, env=PM2_ENV)
    return {"ok": r.returncode == 0, "detail": r.stdout + r.stderr}

@app.get("/mgmt/status")
async def mgmt_status(request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    r = subprocess.run("pm2 jlist", shell=True, capture_output=True, text=True, timeout=10, env=PM2_ENV)
    try:
        procs = json.loads(r.stdout)
        status = {}
        for key, name in PM2_NAMES.items():
            proc = next((p for p in procs if p["name"] == name), None)
            status[key] = {"online": proc["pm2_env"]["status"] == "online",
                           "status": proc["pm2_env"]["status"],
                           "pid": proc["pid"]} if proc else {"online": False, "status": "not found", "pid": None}
        return status
    except Exception:
        return JSONResponse(status_code=500, content={"error": "Could not parse pm2 output"})

@app.post("/mgmt/start/{srv}")
async def mgmt_start(srv: str, request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    name = PM2_NAMES.get(srv)
    if not name:
        return JSONResponse(status_code=400, content={"error": "unknown server"})
    return _pm2(f"pm2 start {name}")

@app.post("/mgmt/stop/{srv}")
async def mgmt_stop(srv: str, request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    name = PM2_NAMES.get(srv)
    if not name:
        return JSONResponse(status_code=400, content={"error": "unknown server"})
    return _pm2(f"pm2 stop {name}")

@app.post("/mgmt/restart/all")
async def mgmt_restart_all(request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    _pm2("pm2 restart tradezen-python")
    _pm2("pm2 restart tradezen-node")
    return {"ok": True, "detail": "Restarting all…"}

@app.post("/mgmt/restart/{srv}")
async def mgmt_restart(srv: str, request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    name = PM2_NAMES.get(srv)
    if not name:
        return JSONResponse(status_code=400, content={"error": "unknown server"})
    return _pm2(f"pm2 restart {name}")

# ══════════════════════════════════════════════════════════════════════════════
# Stock Analyser — comprehensive fundamental + technical snapshot
# ══════════════════════════════════════════════════════════════════════════════

def _extract_financials(tk) -> dict:
    """Extract quarterly and annual income statement rows from a yfinance Ticker."""
    ROWS = {
        "revenue":          ["Total Revenue"],
        "gross_profit":     ["Gross Profit"],
        "operating_income": ["Operating Income", "Operating Revenue"],
        "ebitda":           ["EBITDA", "Normalized EBITDA"],
        "net_income":       ["Net Income", "Net Income Common Stockholders"],
        "eps":              ["Basic EPS", "Diluted EPS"],
    }

    def _safe(df, keys, col):
        for k in keys:
            try:
                if k in df.index:
                    v = df.at[k, col]
                    if v is not None and not (isinstance(v, float) and math.isnan(v)):
                        return round(float(v), 2)
            except Exception:
                pass
        return None

    def _build_rows(df, max_cols, label_fmt):
        rows = []
        if df is None or df.empty:
            return rows
        cols = [c for c in df.columns[:max_cols]]
        for col in cols:
            try:
                label = col.strftime(label_fmt) if hasattr(col, "strftime") else str(col)[:10]
                entry = {"period": label}
                for key, candidates in ROWS.items():
                    entry[key] = _safe(df, candidates, col)
                rows.append(entry)
            except Exception:
                pass
        return rows

    quarterly, annual = [], []
    try:
        quarterly = _build_rows(tk.quarterly_income_stmt, 4, "%b %Y")
    except Exception:
        pass
    try:
        annual = _build_rows(tk.income_stmt, 5, "%Y")
    except Exception:
        pass

    return {"quarterly": quarterly, "annual": annual}


def _stock_analyse_sync(symbol: str) -> dict:
    import yfinance as yf
    import pandas as pd
    from core.indicators.rsi import calculate_rsi

    raw = symbol.upper().strip()
    ticker_sym = raw if raw.endswith(".NS") or raw.startswith("^") else raw + ".NS"
    tk = yf.Ticker(ticker_sym)

    info = {}
    try:
        info = tk.info or {}
    except Exception:
        pass

    # ── Price history (1y daily) ──────────────────────────────────────────────
    hist = tk.history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 30:
        return {"error": f"No data for {raw}. Check if the symbol is listed on NSE."}

    closes  = hist["Close"].squeeze()
    volumes = hist["Volume"].squeeze()

    last_close  = round(float(closes.iloc[-1]), 2)
    prev_close  = round(float(closes.iloc[-2]), 2) if len(closes) > 1 else last_close
    change_pct  = round((last_close - prev_close) / prev_close * 100, 2) if prev_close else 0

    day_high = round(float(hist["High"].iloc[-1]), 2)
    day_low  = round(float(hist["Low"].iloc[-1]), 2)
    w52_high = round(float(hist["High"].max()), 2)
    w52_low  = round(float(hist["Low"].min()), 2)
    near52wh = last_close >= w52_high * 0.98

    avg_vol_20 = int(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else int(volumes.mean())
    cur_vol    = int(volumes.iloc[-1])

    # ── Volume pressure (last 20 sessions) ───────────────────────────────
    _n  = min(20, len(closes))
    _c  = closes.iloc[-_n:]
    _o  = hist["Open"].squeeze().iloc[-_n:]
    _h  = hist["High"].squeeze().iloc[-_n:]
    _l  = hist["Low"].squeeze().iloc[-_n:]
    _v  = volumes.iloc[-_n:]
    _hl = (_h - _l).clip(lower=1e-6)
    _up = _c > _o
    _dn = _c < _o
    _tv = float(_v.sum()) or 1.0
    buy_pct_20  = round(float(_v[_up].sum()) / _tv * 100, 1)
    sell_pct_20 = round(float(_v[_dn].sum()) / _tv * 100, 1)
    _mfm = ((_c - _l) - (_h - _c)) / _hl
    mf_score  = round(float((_mfm * _v).sum() / _tv * 100), 1)
    vol_ratio = round(cur_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

    # ── RSI (14) ─────────────────────────────────────────────────────────────
    rsi_series = calculate_rsi(closes, period=14)
    rsi_val    = round(float(rsi_series.iloc[-1]), 1)

    # ── MACD (12,26,9) ───────────────────────────────────────────────────────
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram   = macd_line - signal_line
    macd_val    = round(float(macd_line.iloc[-1]), 4)
    signal_val  = round(float(signal_line.iloc[-1]), 4)
    hist_val    = round(float(histogram.iloc[-1]), 4)
    # crossover: last bar crossed above/below signal?
    prev_hist   = float(histogram.iloc[-2]) if len(histogram) > 1 else 0
    if hist_val > 0 and prev_hist <= 0:
        macd_cross = "BULLISH_CROSS"
    elif hist_val < 0 and prev_hist >= 0:
        macd_cross = "BEARISH_CROSS"
    else:
        macd_cross = "NONE"

    # ── Moving averages ───────────────────────────────────────────────────────
    sma50_val  = round(float(closes.rolling(50).mean().iloc[-1]), 2) if len(closes) >= 50 else None
    sma200_val = round(float(closes.rolling(200).mean().iloc[-1]), 2) if len(closes) >= 200 else None
    above_50   = (last_close > sma50_val) if sma50_val else None
    above_200  = (last_close > sma200_val) if sma200_val else None
    golden_cross = (
        (sma50_val is not None and sma200_val is not None) and
        (sma50_val > sma200_val)
    )

    # ── Returns ───────────────────────────────────────────────────────────────
    def _ret(n_days: int) -> float | None:
        if len(closes) < n_days + 1:
            return None
        base = float(closes.iloc[-(n_days + 1)])
        if base == 0:
            return None
        return round((last_close - base) / base * 100, 2)

    ret_1m  = _ret(21)
    ret_3m  = _ret(63)
    ret_1y  = _ret(252)

    # ── Fundamentals from info dict ───────────────────────────────────────────
    def _f(key, decimals=2):
        v = info.get(key)
        if v is None or (isinstance(v, float) and (v != v)):   # NaN check
            return None
        try:
            return round(float(v), decimals)
        except (TypeError, ValueError):
            return None

    pe          = _f("trailingPE", 1)
    forward_pe  = _f("forwardPE", 1)
    pb          = _f("priceToBook", 2)
    ev_ebitda   = _f("enterpriseToEbitda", 1)
    eps         = _f("trailingEps", 2)
    div_yield   = _f("dividendYield", 4)   # yfinance may return fraction OR percent
    book_val    = _f("bookValue", 2)
    market_cap  = info.get("marketCap")    # raw integer (INR)

    # SEBI approximate thresholds (updated bi-annually by AMFI)
    # Large Cap: top 100 stocks  ≈ > ₹20,000 Cr
    # Mid Cap:   101–250          ≈ ₹5,000–20,000 Cr
    # Small Cap: 251+             ≈ < ₹5,000 Cr
    if market_cap is not None:
        if market_cap >= 200_000_000_000:   # ₹20,000 Cr
            cap_category = "Large Cap"
        elif market_cap >= 50_000_000_000:  # ₹5,000 Cr
            cap_category = "Mid Cap"
        else:
            cap_category = "Small Cap"
    else:
        cap_category = None
    roe         = _f("returnOnEquity", 4)
    roa         = _f("returnOnAssets", 4)
    de_ratio    = _f("debtToEquity", 2)
    rev_growth  = _f("revenueGrowth", 4)
    earn_growth = _f("earningsGrowth", 4)
    profit_mg   = _f("profitMargins", 4)
    oper_mg     = _f("operatingMargins", 4)
    beta        = _f("beta", 2)
    sector      = info.get("sector", "")
    industry    = info.get("industry", "")
    company     = info.get("longName") or info.get("shortName") or raw

    # Major holders (institutional %)
    inst_pct = None
    try:
        mh = tk.major_holders
        if mh is not None and not mh.empty:
            for _, row in mh.iterrows():
                val_str = str(row.iloc[0]).replace("%", "").strip()
                lbl     = str(row.iloc[1]).lower()
                if "institution" in lbl:
                    try:
                        inst_pct = round(float(val_str), 2)
                    except ValueError:
                        pass
    except Exception:
        pass

    # ── Scorecard ─────────────────────────────────────────────────────────────
    # Valuation signal
    val_label = "N/A"
    if pe is not None:
        if pe < 15:        val_label = "Cheap"
        elif pe < 25:      val_label = "Fair"
        elif pe < 40:      val_label = "Stretched"
        else:              val_label = "Expensive"

    # Momentum signal
    if rsi_val >= 70:      mom_label = "Overbought"
    elif rsi_val >= 55:    mom_label = "Bullish"
    elif rsi_val >= 45:    mom_label = "Neutral"
    elif rsi_val >= 30:    mom_label = "Bearish"
    else:                  mom_label = "Oversold"

    # Adjust for price vs MAs
    ma_bullish = (above_50 is True) and (above_200 is True)
    ma_bearish = (above_50 is False) and (above_200 is False)
    if mom_label == "Neutral":
        if ma_bullish:   mom_label = "Bullish"
        elif ma_bearish: mom_label = "Bearish"

    # Financials signal
    fin_score = 0
    if roe is not None:
        if roe > 0.15:    fin_score += 1
        elif roe < 0.05:  fin_score -= 1
    if de_ratio is not None:
        if de_ratio < 50:    fin_score += 1
        elif de_ratio > 150: fin_score -= 1
    if profit_mg is not None:
        if profit_mg > 0.10: fin_score += 1
        elif profit_mg < 0:  fin_score -= 1
    if earn_growth is not None:
        if earn_growth > 0.10: fin_score += 1
        elif earn_growth < 0:  fin_score -= 1

    if fin_score >= 3:      fin_label = "Strong"
    elif fin_score >= 1:    fin_label = "Healthy"
    elif fin_score == 0:    fin_label = "Mixed"
    else:                   fin_label = "Concerning"

    # Overall
    pos = sum([
        val_label in ("Cheap", "Fair"),
        mom_label in ("Bullish", "Overbought"),
        fin_label in ("Strong", "Healthy"),
    ])
    if pos >= 2:   overall = "positive"
    elif pos == 1: overall = "neutral"
    else:          overall = "negative"

    summary_parts = [
        f"{company} is trading at ₹{last_close}",
        f"({'+' if change_pct >= 0 else ''}{change_pct}% today).",
        f"Valuation: {val_label}.",
        f"Momentum: {mom_label} (RSI {rsi_val}).",
        f"Financials: {fin_label}.",
    ]
    summary = " ".join(summary_parts)

    # ── Quick note (plain-English analyst paragraph) ──────────────────────────
    note_parts = []

    # Sentence 1 — valuation
    if pe is not None:
        pe_ctx = f"PE of {pe}x is considered {val_label.lower()}"
        if forward_pe is not None:
            pe_ctx += f" (forward PE: {forward_pe}x)"
        note_parts.append(f"{company} trades at a {pe_ctx}.")
    else:
        note_parts.append(f"{company} is listed on NSE.")

    # Sentence 2 — price action & momentum
    ma_ctx = []
    if above_50 is True:  ma_ctx.append("above SMA 50")
    elif above_50 is False: ma_ctx.append("below SMA 50")
    if above_200 is True: ma_ctx.append("above SMA 200")
    elif above_200 is False: ma_ctx.append("below SMA 200")
    ma_str = " and ".join(ma_ctx) if ma_ctx else ""

    if rsi_val >= 70:
        rsi_str = f"RSI at {rsi_val} signals overbought conditions — watch for a potential pullback."
    elif rsi_val <= 30:
        rsi_str = f"RSI at {rsi_val} signals oversold territory — a bounce could be near."
    elif rsi_val >= 55:
        rsi_str = f"RSI at {rsi_val} reflects positive momentum."
    else:
        rsi_str = f"RSI at {rsi_val} indicates neutral momentum."

    price_sentence = f"The stock is {ma_str + ', with ' if ma_str else ''}{rsi_str}"
    if golden_cross:
        price_sentence += " A golden cross (SMA 50 > SMA 200) adds to the bullish structure."
    note_parts.append(price_sentence)

    # Sentence 3 — financial health
    fin_details = []
    if roe is not None:
        fin_details.append(f"ROE of {round(roe*100,1)}%")
    if de_ratio is not None:
        debt_desc = "low" if de_ratio < 50 else ("moderate" if de_ratio < 150 else "high")
        fin_details.append(f"{debt_desc} debt-to-equity ({round(de_ratio,1)})")
    if profit_mg is not None and profit_mg > 0:
        fin_details.append(f"profit margin of {round(profit_mg*100,1)}%")

    div_yield_pct_val = round(div_yield if div_yield is not None and div_yield > 1 else (div_yield * 100 if div_yield is not None else 0), 2) if div_yield is not None else None
    if div_yield_pct_val and div_yield_pct_val >= 1:
        fin_details.append(f"dividend yield of {div_yield_pct_val}%")

    if fin_details:
        note_parts.append(f"On fundamentals: {company} shows " + ", ".join(fin_details) + ".")

    # Sentence 4 — growth
    growth_parts = []
    if rev_growth is not None:
        dir_ = "growing" if rev_growth > 0 else "declining"
        growth_parts.append(f"revenue {dir_} at {round(rev_growth*100,1)}% YoY")
    if earn_growth is not None:
        dir_ = "growing" if earn_growth > 0 else "declining"
        growth_parts.append(f"earnings {dir_} at {round(earn_growth*100,1)}% YoY")
    if ret_1y is not None:
        dir_ = "up" if ret_1y >= 0 else "down"
        growth_parts.append(f"stock {dir_} {abs(ret_1y)}% over the past year")
    if growth_parts:
        note_parts.append("With " + ", ".join(growth_parts) + ".")

    # Sentence 5 — risk note
    risk_notes = []
    if beta is not None:
        if beta > 1.3:
            risk_notes.append(f"High beta ({beta}) means the stock is more volatile than the market")
        elif beta < 0.7:
            risk_notes.append(f"Low beta ({beta}) makes this a relatively defensive pick")
    if near52wh:
        risk_notes.append("trading near its 52-week high — momentum is strong but upside may be limited short-term")
    if risk_notes:
        note_parts.append(". ".join(risk_notes) + ".")

    note = " ".join(note_parts)

    return {
        "symbol":       raw,
        "company":      company,
        "sector":       sector,
        "industry":     industry,
        "cap_category": cap_category,

        # Price snapshot
        "price": {
            "last":        last_close,
            "change_pct":  change_pct,
            "day_high":    day_high,
            "day_low":     day_low,
            "week52_high": w52_high,
            "week52_low":  w52_low,
            "volume":      cur_vol,
            "avg_volume":  avg_vol_20,
        },

        # Fundamentals
        "fundamentals": {
            "market_cap":   market_cap,
            "pe":           pe,
            "forward_pe":   forward_pe,
            "pb":           pb,
            "ev_ebitda":    ev_ebitda,
            "eps":          eps,
            "book_value":   book_val,
            # yfinance inconsistency: some stocks return 0.0376 (fraction), others return 3.76 (already %)
            # Values > 1 are clearly already in percent form; multiply only true fractions.
            "dividend_yield_pct": round(div_yield if div_yield > 1 else div_yield * 100, 2) if div_yield is not None else None,
            "roe_pct":      round(roe * 100, 2) if roe is not None else None,
            "roa_pct":      round(roa * 100, 2) if roa is not None else None,
            "de_ratio":     de_ratio,
            "profit_margin_pct":   round(profit_mg * 100, 2) if profit_mg is not None else None,
            "operating_margin_pct": round(oper_mg * 100, 2) if oper_mg is not None else None,
            "revenue_growth_pct":  round(rev_growth * 100, 2) if rev_growth is not None else None,
            "earnings_growth_pct": round(earn_growth * 100, 2) if earn_growth is not None else None,
            "beta":         beta,
            "institutional_holding_pct": inst_pct,
        },

        # Technical
        "technicals": {
            "rsi":         rsi_val,
            "macd":        macd_val,
            "macd_signal": signal_val,
            "macd_hist":   hist_val,
            "macd_cross":  macd_cross,
            "sma50":       sma50_val,
            "sma200":      sma200_val,
            "above_sma50":  above_50,
            "above_sma200": above_200,
            "golden_cross": golden_cross,
        },

        # Returns
        "returns": {
            "ret_1m_pct": ret_1m,
            "ret_3m_pct": ret_3m,
            "ret_1y_pct": ret_1y,
        },

        # Scorecard
        "scorecard": {
            "valuation":  val_label,
            "momentum":   mom_label,
            "financials": fin_label,
            "overall":    overall,
            "summary":    summary,
        },

        # Quick analyst note
        "note": note,

        # Chart data — last 252 trading days of daily closes
        "chart": {
            "dates":  [d.strftime("%Y-%m-%d") for d in hist.index.date],
            "closes": [round(float(v), 2) for v in closes.tolist()],
        },

        # Volume pressure (calculated from last 20 sessions of daily OHLCV)
        "volume": {
            "buy_pct":   buy_pct_20,
            "sell_pct":  sell_pct_20,
            "mf_score":  mf_score,
            "vol_ratio": vol_ratio,
            "bid":       _f("bid", 2),
            "ask":       _f("ask", 2),
            "bid_size":  info.get("bidSize"),
            "ask_size":  info.get("askSize"),
        },

        # Financial results — quarterly and annual income statement
        "results": _extract_financials(tk),
    }


@app.get("/stock/analyse/{symbol}")
async def stock_analyse(symbol: str):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _stock_analyse_sync, symbol)
        return result
    except Exception as e:
        log.error(f"[STOCK-ANALYSER] {symbol}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# Wealth Time-Lapse — monthly close series for the what-if compounding lab
# ══════════════════════════════════════════════════════════════════════════════

def _timelapse_sync(symbol: str, start: str) -> dict:
    """
    Aligned monthly closes (dividend/split adjusted) for stock + Nifty + gold ETF.
    All SIP/lumpsum/FD math happens client-side so sliders recompute instantly.
    """
    import yfinance as yf
    import pandas as pd

    sym    = symbol.upper().strip()
    yf_sym = sym if sym.endswith(".NS") or sym.startswith("^") else f"{sym}.NS"

    def _monthly_closes(ticker: str) -> "pd.Series":
        try:
            h = yf.Ticker(ticker).history(start=start, interval="1mo", auto_adjust=True)
            if h.empty:
                return pd.Series(dtype=float)
            s = h["Close"].dropna()
            s.index = pd.DatetimeIndex(s.index).strftime("%Y-%m")
            return s[~s.index.duplicated(keep="last")]
        except Exception as e:
            log.warning(f"timelapse fetch {ticker}: {e}")
            return pd.Series(dtype=float)

    stock = _monthly_closes(yf_sym)
    if stock.empty:
        return {"error": f"No price history found for {sym} on NSE"}
    nifty = _monthly_closes("^NSEI")
    gold  = _monthly_closes("GOLDBEES.NS")   # gold ETF as rupee gold proxy

    months = list(stock.index)
    company = None
    try:
        company = yf.Ticker(yf_sym).info.get("longName")
    except Exception:
        pass

    def _aligned(s):
        return [round(float(s[m]), 4) if m in s.index else None for m in months]

    return {
        "symbol":  sym.replace(".NS", ""),
        "company": company,
        "months":  months,
        "stock":   [round(float(v), 4) for v in stock.tolist()],
        "nifty":   _aligned(nifty),
        "gold":    _aligned(gold),
    }


@app.get("/stock/timelapse/{symbol}")
async def stock_timelapse(symbol: str, start: str = "2007-01-01"):
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _timelapse_sync, symbol, start)
    except Exception as e:
        log.error(f"[TIMELAPSE] {symbol}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# Stock Health Story — 4-persona fundamental health report
# ══════════════════════════════════════════════════════════════════════════════

def _stock_health_sync(symbol: str) -> dict:
    import yfinance as yf

    raw        = symbol.upper().strip()
    ticker_sym = raw if raw.endswith(".NS") or raw.endswith(".BO") else raw + ".NS"
    tk         = yf.Ticker(ticker_sym)
    info       = tk.info or {}

    if not info or (
        info.get("currentPrice") is None
        and info.get("regularMarketPrice") is None
        and info.get("previousClose") is None
    ):
        return {"error": f"No data found for '{raw}'. Verify the NSE symbol and try again."}

    def _f(key, decimals=4):
        v = info.get(key)
        if v is None:
            return None
        try:
            f = float(v)
            return None if f != f else round(f, decimals)
        except (TypeError, ValueError):
            return None

    company = info.get("longName") or info.get("shortName") or raw
    sector  = info.get("sector") or ""
    short   = company.split()[0]

    price      = _f("currentPrice", 2) or _f("regularMarketPrice", 2) or _f("previousClose", 2)
    prev_close = _f("previousClose", 2)
    change_pct = (
        round((price - prev_close) / prev_close * 100, 2)
        if price and prev_close and prev_close != 0 else None
    )

    market_cap   = _f("marketCap", 0)
    cap_category = None
    if market_cap is not None:
        if market_cap >= 200_000_000_000:
            cap_category = "Large Cap"
        elif market_cap >= 50_000_000_000:
            cap_category = "Mid Cap"
        else:
            cap_category = "Small Cap"

    roe       = _f("returnOnEquity", 4)   # decimal 0.18 = 18 %
    de_raw    = _f("debtToEquity",   2)   # yfinance stores 50 = 0.5 × D/E
    profit_mg = _f("profitMargins",  4)   # decimal 0.12 = 12 %
    rev_gr    = _f("revenueGrowth",  4)   # decimal 0.20 = 20 %

    roe_pct    = round(roe * 100, 1)       if roe       is not None else None
    de_disp    = round(de_raw / 100, 2)    if de_raw    is not None else None
    margin_pct = round(profit_mg * 100, 1) if profit_mg is not None else None
    rev_pct    = round(rev_gr * 100, 1)    if rev_gr    is not None else None

    available = sum(1 for x in [roe, de_raw, profit_mg, rev_gr] if x is not None)

    if available < 2:
        persona, score = "unavailable", 0.0
    elif rev_gr is not None and rev_gr > 0.20:
        persona, score = "spring_bud", 6.5
    else:
        score = 0.0
        if roe       is not None: score += 2.5 if roe >= 0.15       else (1.5 if roe >= 0.08       else 0)
        if de_raw    is not None: score += 2.5 if de_raw < 50       else (1.5 if de_raw < 100       else 0)
        if profit_mg is not None: score += 2.5 if profit_mg >= 0.10 else (1.5 if profit_mg >= 0     else 0)
        if rev_gr    is not None: score += 2.5 if rev_gr >= 0.10    else (1.5 if rev_gr >= 0        else 0)
        if profit_mg is not None and profit_mg < 0:
            score = min(score, 2.5)
        persona = "fortress" if score >= 7 else ("fading_giant" if score >= 4 else "leaky_bucket")

    def _st_roe(v):
        if v is None: return "na"
        return "good" if v >= 0.15 else ("neutral" if v >= 0.08 else "concern")

    def _st_de(v):
        if v is None: return "na"
        return "good" if v < 50 else ("neutral" if v < 100 else "concern")

    def _st_mg(v):
        if v is None: return "na"
        return "good" if v >= 0.10 else ("neutral" if v >= 0 else "concern")

    def _st_rev(v):
        if v is None: return "na"
        return "good" if v >= 0.10 else ("neutral" if v >= 0 else "concern")

    def _pct(v, sign=False):
        if v is None: return "N/A"
        return (("+" if v >= 0 else "") + f"{v}%") if sign else f"{v}%"

    metrics = {
        "roe":        {"display": _pct(roe_pct),             "status": _st_roe(roe),    "label": "Return on Equity", "label_ta": "பங்கு வருமானம்"},
        "de_ratio":   {"display": f"{de_disp}x" if de_disp is not None else "N/A", "status": _st_de(de_raw), "label": "Debt / Equity", "label_ta": "கடன் / பங்கு"},
        "net_margin": {"display": _pct(margin_pct),          "status": _st_mg(profit_mg), "label": "Net Margin",    "label_ta": "நிகர லாப வரம்பு"},
        "rev_growth": {"display": _pct(rev_pct, sign=True),  "status": _st_rev(rev_gr), "label": "Revenue Growth",  "label_ta": "வருவாய் வளர்ச்சி"},
    }

    roe_s    = _pct(roe_pct)
    de_s     = f"{de_disp}x" if de_disp is not None else "N/A"
    margin_s = _pct(margin_pct)
    rev_s    = _pct(rev_pct, sign=True)

    _narr = {
        "fortress": {
            "en": f"{short} earns {roe_s} return on shareholder equity and carries a debt load of {de_s} — the structure of a financially disciplined business. Revenue is growing at {rev_s} with net margins at {margin_s}.",
            "ta": f"{short} பங்குதாரர் பணத்தில் {roe_s} வருமானம் ஈட்டுகிறது, கடன் சுமை {de_s} மட்டுமே உள்ளது. இது நிதி நிலையான நிறுவனத்தின் அமைப்பு — வருவாய் வளர்ச்சி {rev_s}, நிகர லாப வரம்பு {margin_s}.",
        },
        "spring_bud": {
            "en": f"{short} is expanding revenue at {rev_s} year over year — a pace that points to a business in fast-growth mode. Margins may be thin as the company invests in scale, but the direction is upward.",
            "ta": f"{short} வருடத்திற்கு {rev_s} வேகத்தில் வளர்கிறது — இது வேகமாக விரிவடையும் நிறுவனத்தின் அறிகுறி. வளர்ச்சியில் முதலீடு செய்வதால் லாப வரம்பு குறைவாக இருக்கலாம், ஆனால் திசை மேல்நோக்கியது.",
        },
        "fading_giant": {
            "en": f"{short} is profitable but momentum has softened — ROE of {roe_s} and revenue growth of {rev_s} suggest the business is in a consolidation phase. The core structure holds, but the energy has slowed.",
            "ta": f"{short} இன்னும் லாபகரமாக உள்ளது, ஆனால் வளர்ச்சி மெதுவாகிவிட்டது. ROE {roe_s}, வருவாய் வளர்ச்சி {rev_s} — நிறுவனம் நிலையான கட்டத்தில் உள்ளது. அடிப்படை கட்டமைப்பு நிலையாக உள்ளது, ஆனால் வேகம் குறைந்துள்ளது.",
        },
        "leaky_bucket": {
            "en": f"{short} is under financial pressure — net margins at {margin_s} and a debt ratio of {de_s} signal a business that needs to course-correct. The current metrics require careful observation before the picture improves.",
            "ta": f"{short} நிதி சவால்களை எதிர்கொள்கிறது — நிகர லாப வரம்பு {margin_s}, கடன் விகிதம் {de_s}. தற்போதைய குறிகாட்டிகள் நிறுவனத்திற்கு திசை திருத்தல் தேவை என்று காட்டுகின்றன.",
        },
        "unavailable": {
            "en": f"Insufficient financial data is available for {raw} at this time. Try a Nifty 500 stock for best results.",
            "ta": f"{raw}-க்கான போதுமான நிதி தரவு இப்போது கிடைக்கவில்லை. Nifty 500 பங்குகளில் சிறந்த முடிவுகள் கிடைக்கும்.",
        },
    }

    _nudge = {
        "fortress":     {"en": "Solid fundamentals. Study the recent price structure in Stock Analyser.",       "ta": "வலுவான அடிப்படை. Stock Analyser-ல் சமீபத்திய விலை அமைப்பை ஆராயுங்கள்.",             "link": f"/stock-analyser.html?symbol={raw}", "link_en": "Open Stock Analyser",   "link_ta": "Stock Analyser திறக்கவும்"},
        "spring_bud":   {"en": "High growth, elevated risk. Observe option activity in F&O Scanner to read market sentiment.", "ta": "அதிக வளர்ச்சி, அதிக ரிஸ்க். சந்தை உணர்வை படிக்க F&O Scanner-ல் ஆப்ஷன் நடவடிக்கையை கவனிக்கவும்.", "link": "/fno_scanner.html",                 "link_en": "Open F&O Scanner",       "link_ta": "F&O Scanner திறக்கவும்"},
        "fading_giant": {"en": "Signs of a slowdown. Observe the recent price trend in Stock Analyser.",       "ta": "மெதுவடைவின் அறிகுறிகள். Stock Analyser-ல் சமீபத்திய விலை போக்கை கவனிக்கவும்.",    "link": f"/stock-analyser.html?symbol={raw}", "link_en": "Open Stock Analyser",   "link_ta": "Stock Analyser திறக்கவும்"},
        "leaky_bucket": {"en": "High risk profile. Check Market Movers to observe if selling pressure is building.", "ta": "அதிக ரிஸ்க். விற்பனை அழுத்தம் அதிகரிக்கிறதா என Market Movers-ல் கவனிக்கவும்.", "link": "/stock_movers.html",                "link_en": "Open Market Movers",     "link_ta": "Market Movers திறக்கவும்"},
        "unavailable":  {"en": "Try Stock Analyser for available data on this symbol.",                        "ta": "இந்த பங்கின் தரவுக்கு Stock Analyser-ஐ முயற்சிக்கவும்.",                           "link": "/stock-analyser.html",               "link_en": "Open Stock Analyser",   "link_ta": "Stock Analyser திறக்கவும்"},
    }

    return {
        "symbol":       raw,
        "company":      company,
        "sector":       sector,
        "cap_category": cap_category,
        "price":        price,
        "change_pct":   change_pct,
        "persona":      persona,
        "score":        round(score, 1),
        "metrics":      metrics,
        "narrative":    _narr.get(persona, _narr["unavailable"]),
        "nudge":        _nudge.get(persona, _nudge["unavailable"]),
        "data_note":    "Financial ratios from latest annual report via Yahoo Finance. Prices ~15 min delayed.",
        "available":    persona != "unavailable",
    }


@app.get("/stock/reversal-scan")
async def stock_reversal_scan(
    universe:     str   = "nifty50",
    min_decline:  float = 30.0,
    max_recovery: float = 60.0,
    support_type: str   = "single",
    min_days:     int   = 40,
    max_days:     int   = 130,
    min_price:    float = None,
    max_price:    float = None,
    sector:       str   = "",
    symbols:      str   = "",
):
    from core.patterns.reversal_scanner import scan_reversals
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: scan_reversals(
            universe=universe,
            min_decline=min_decline,
            max_recovery=max_recovery,
            support_type=support_type,
            min_days=min_days,
            max_days=max_days,
            min_price=min_price if min_price else None,
            max_price=max_price if max_price else None,
            sector=sector,
            symbols=symbols,
        ))
        return result
    except Exception as e:
        log.error(f"[REVERSAL-SCAN] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/stock/reversal-check/{symbol}")
async def stock_reversal_check(
    symbol:       str,
    min_decline:  float = 30.0,
    max_recovery: float = 60.0,
    support_type: str   = "single",
    min_days:     int   = 40,
    max_days:     int   = 130,
):
    from core.patterns.reversal_scanner import check_single_stock
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: check_single_stock(
            symbol=symbol,
            min_decline=min_decline,
            max_recovery=max_recovery,
            support_type=support_type,
            min_days=min_days,
            max_days=max_days,
        ))
        return result
    except Exception as e:
        log.error(f"[REVERSAL-CHECK] {symbol}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/stock/breakout-scan")
async def stock_breakout_scan(
    universe:    str   = "nifty50",
    min_decline: float = 20.0,
    min_w:       int   = 4,
    max_w:       int   = 12,
    max_range:   float = 10.0,
    near_res:    float = 5.0,
    sector:      str   = "",
    symbols:     str   = "",
):
    from core.patterns.breakout_scanner import scan_breakouts
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: scan_breakouts(
            universe=universe, min_decline=min_decline,
            min_w=min_w, max_w=max_w, max_range=max_range,
            near_res=near_res, sector=sector, symbols=symbols,
        ))
        return result
    except Exception as e:
        log.error(f"[BREAKOUT-SCAN] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/stock/breakout-check/{symbol}")
async def stock_breakout_check(
    symbol:      str,
    min_decline: float = 20.0,
    min_w:       int   = 4,
    max_w:       int   = 12,
    max_range:   float = 10.0,
    near_res:    float = 5.0,
):
    from core.patterns.breakout_scanner import check_single_breakout
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, lambda: check_single_breakout(
            symbol=symbol, min_decline=min_decline,
            min_w=min_w, max_w=max_w, max_range=max_range, near_res=near_res,
        ))
        return result
    except Exception as e:
        log.error(f"[BREAKOUT-CHECK] {symbol}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/stock/health/{symbol}")
async def stock_health(symbol: str):
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, _stock_health_sync, symbol)
        return result
    except Exception as e:
        log.error(f"[STOCK-HEALTH] {symbol}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/mgmt/logs/{srv}")
async def mgmt_logs(srv: str, request: Request):
    if not _check_token(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    name = PM2_NAMES.get(srv)
    if not name:
        return JSONResponse(status_code=400, content={"error": "unknown server"})
    r = subprocess.run(
        f"pm2 logs {name} --nostream --lines 80 --no-color",
        shell=True, capture_output=True, text=True, timeout=15, env=PM2_ENV
    )
    lines = [l for l in (r.stdout + r.stderr).split("\n") if l.strip()][-80:]
    return {"logs": lines}
