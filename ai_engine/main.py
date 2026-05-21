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

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

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
    "prev_ohlc":  None,   # {"high":..., "low":..., "close":..., "date":...}
    "gift_nifty": None,   # manually supplied GIFT Nifty price (pre-market)
    "nifty_open": None,   # first spot price at/after 9:15 AM IST
    "orb":        None,   # {"high":..., "low":...} — locked after 9:30 AM
    "_orb_acc":   {"high": None, "low": None},   # accumulator 9:15–9:30
    "india_vix":  None,   # fetched from yfinance ^INDIAVIX, refreshed every 5 min
    "last_ltp":   None,   # last known NIFTY price — persists across WebSocket drops
}
_vix_last_refresh: datetime = None   # tracks last VIX fetch time


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
            log.info(f"📅 Prev OHLC (yfinance): H={ohlc['high']} L={ohlc['low']} C={ohlc['close']} [{ohlc['date']}]")
            ohlc_loaded = True
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
            # Try yfinance first for ORB
            try:
                orb_yf = _yf_orb()
                trade_flow_data["orb"] = orb_yf
                trade_flow_data["_orb_acc"] = orb_yf.copy()
                log.info(f"📊 ORB (retroactive, yfinance): H={orb_yf['high']} L={orb_yf['low']}")
            except Exception as yf_orb_err:
                log.debug(f"yfinance ORB fetch failed: {yf_orb_err} — trying Angel One")
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
                            log.info(f"📊 ORB (retroactive, {exch}): H={orb_h} L={orb_l}")
                            break
                    except Exception as retro_err:
                        log.debug(f"ORB retroactive ({exch}/{token}): {retro_err}")

    except Exception as e:
        log.warning(f"⚠️ Prev OHLC fetch error: {e}")

    # 📊 Fetch India VIX at startup
    try:
        vix = _yf_vix()
        trade_flow_data["india_vix"] = vix
        log.info(f"📊 India VIX: {vix}")
    except Exception as vix_err:
        log.warning(f"⚠️ India VIX fetch failed: {vix_err}")

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
                            trade_flow_data["orb"] = {
                                "high": round(acc["high"], 2),
                                "low":  round(acc["low"],  2),
                            }
                            log.info(f"📊 ORB locked: H={trade_flow_data['orb']['high']} "
                                     f"L={trade_flow_data['orb']['low']}")

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
            try:
                log.info("🔄 Refreshing instrument master (daily pre-market)...")
                im.reload()
                log.info(f"✅ Instrument master refreshed — {len(im.data)} NIFTY options loaded")
            except Exception as _ire:
                log.error(f"❌ Instrument master refresh failed: {_ire}")

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
    global market_state, trade_flow_data

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

    # ── Auto scenario determination ───────────────────────────────────────────
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

    return {
        "phase":       phase,
        "time_ist":    now_ist.strftime("%H:%M:%S"),
        "date":        now_ist.strftime("%Y-%m-%d"),
        "prev_day":    prev,
        "gift_nifty":  trade_flow_data.get("gift_nifty"),
        "india_vix":   trade_flow_data.get("india_vix"),
        "cpr":         cpr,
        "nifty_open":  open_data,
        "orb":         orb_data,
        "nifty_ltp":   effective_ltp,
        "scenario":    scenario,
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


_smart_lock = threading.Lock()


def _get_smart():
    """Return the shared SmartAPI session; re-auth only if the global is None."""
    global smart
    if smart:
        return smart
    with _smart_lock:
        if smart:          # another thread may have re-authed while we waited
            return smart
        try:
            smart = get_smart_api()
            log.info("[SmartAPI] re-authenticated")
            return smart
        except Exception as e:
            log.warning(f"SmartAPI re-auth failed: {e}")
            return None


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
        # Fetch 5-min candles for the current day (from 9:15 AM)
        ticker = yf.Ticker("^NSEI")
        df_5m = ticker.history(period="1d", interval="5m")
        if df_5m.empty:
            return {"error": "No 5-min data available", "status": "offline"}

        # Convert to IST
        df_5m.index = df_5m.index.tz_convert("Asia/Kolkata")
        df_5m = df_5m[["Open", "High", "Low", "Close", "Volume"]].dropna()

        # Filter for today's trading hours (9:15 AM - 3:30 PM)
        df_5m = df_5m.between_time("09:15", "15:30")

        if df_5m.empty:
            return {"error": "Market hours data not available", "status": "offline"}

        # Normalize column names for S1 monitor
        df_5m.columns = ['open', 'high', 'low', 'close', 'volume']

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

        # Run S1 monitor
        s1_monitor = S1StrategyMonitor()
        result = s1_monitor.check_s1_setup(
            nifty_price=nifty_price,
            candles=df_5m,
            vix=india_vix or 20,
            current_time=datetime.now()
        )

        result['status'] = 'online'
        result['nifty_price'] = round(nifty_price, 2)
        result['india_vix'] = round(india_vix, 2) if india_vix else None
        result['timestamp'] = datetime.now().isoformat()
        result['candles_count'] = len(df_5m)

        # ────────────────────────────────────────────────────────────────────
        # Generate chart data (candles + indicators for lightweight-charts)
        # ────────────────────────────────────────────────────────────────────
        try:
            from core.indicators.ema import calculate_ema
            from core.indicators.rsi import calculate_rsi

            close = df_5m['close']
            ema9_series = calculate_ema(close, 9)
            ema21_series = calculate_ema(close, 21)
            rsi_series = calculate_rsi(close, 14)

            # Convert candles to lightweight-charts format
            chart_candles = []
            chart_ema9 = []
            chart_ema21 = []
            chart_rsi = []

            for idx, (ts, row) in enumerate(df_5m.iterrows()):
                # Unix timestamp in seconds
                time = int(ts.timestamp())

                # Candlestick
                chart_candles.append({
                    'time': time,
                    'open': round(float(row['open']), 2),
                    'high': round(float(row['high']), 2),
                    'low': round(float(row['low']), 2),
                    'close': round(float(row['close']), 2),
                })

                # EMA lines
                if idx < len(ema9_series):
                    ema9_val = float(ema9_series.iloc[idx])
                    chart_ema9.append({'time': time, 'value': round(ema9_val, 2)})

                if idx < len(ema21_series):
                    ema21_val = float(ema21_series.iloc[idx])
                    chart_ema21.append({'time': time, 'value': round(ema21_val, 2)})

                if idx < len(rsi_series):
                    rsi_val = float(rsi_series.iloc[idx])
                    chart_rsi.append({'time': time, 'value': round(rsi_val, 2)})

            result['chart_data'] = {
                'candles': chart_candles,
                'ema9': chart_ema9,
                'ema21': chart_ema21,
                'rsi': chart_rsi,
                'latest_ema9': round(float(ema9_series.iloc[-1]), 2) if len(ema9_series) > 0 else None,
                'latest_ema21': round(float(ema21_series.iloc[-1]), 2) if len(ema21_series) > 0 else None,
                'latest_rsi': round(float(rsi_series.iloc[-1]), 2) if len(rsi_series) > 0 else None,
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
    smart   = _get_smart()
    if not smart:
        return {"error": "SmartAPI auth failed"}

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

    # ── Fetch market data from Angel One ────────────────────────────────────
    resp = smart.getMarketData("FULL", {"NFO": [ce_token, pe_token]})

    ce_ltp = pe_ltp = ce_oi = pe_oi = None
    if resp and resp.get("data") and resp["data"].get("fetched"):
        for item in resp["data"]["fetched"]:
            tok = str(item.get("symbolToken", ""))
            ltp = item.get("ltp")
            # Angel One returns OI as 'opnInterest', not 'openInterest'
            oi  = item.get("opnInterest")
            if tok == str(ce_token):
                ce_ltp = round(float(ltp), 2) if ltp is not None else None
                ce_oi  = int(float(oi))        if oi  is not None else None
            elif tok == str(pe_token):
                pe_ltp = round(float(ltp), 2) if ltp is not None else None
                pe_oi  = int(float(oi))        if oi  is not None else None

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
# Market Psychology Engine — dominance scoring + Supertrend + VWAP per candle
# ══════════════════════════════════════════════════════════════════════════════

from core.indicators.supertrend import compute as _compute_supertrend

_PSYCH_CACHE: dict = {}          # {"{symbol}-{interval}": (unix_ts, result)}
_PSYCH_CACHE_TTL   = 10          # seconds before re-fetching

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

    yf_sym, yf_period = _YF_SYMBOLS.get(symbol, "^NSEI"), "1d"
    yf_interval, yf_period = _INTERVAL_MAP.get(interval, ("5m", "1d"))

    df = yf.Ticker(yf_sym).history(period=yf_period, interval=yf_interval)
    if df.empty:
        return {"error": "No intraday data — market closed or holiday", "candles": [], "market_closed": True}

    try:
        df.index = df.index.tz_convert("Asia/Kolkata")
    except Exception:
        pass

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # Require today's IST date — reject stale bars from previous sessions / holidays
    now_ist   = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today_ist = now_ist.date()

    if df.empty or df.index[-1].date() != today_ist:
        return {"error": "No trading session today — market closed or holiday", "candles": [], "market_closed": True}

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
            vdf = yf.Ticker(vol_proxy).history(period=yf_period, interval=yf_interval)
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


@app.get("/psychology/candles")
async def psychology_candles(symbol: str = "NIFTY", interval: str = "5m"):
    """Full candle history with VWAP, Supertrend and dominance scores."""
    loop = asyncio.get_event_loop()
    try:
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
async def psychology_levels(symbol: str = "NIFTY"):
    import yfinance as yf
    import datetime as _dt
    IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    yf_sym = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}.get(symbol.upper(), f"{symbol.upper()}.NS")
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
        "symbol": symbol.upper(),
        "spot":   spot,
        "cpr":    {"tc": tc, "pp": pp, "bc": bc, "r1": r1, "r2": r2, "s1": s1, "s2": s2},
        "camarilla": cam,
        "orb":    orb,
    }


# ══════════════════════════════════════════════════════════════════════════════
# F&O Scanner — buy/sell dominance for equities in a price range
# ══════════════════════════════════════════════════════════════════════════════

import time as _time

_fno_stock_cache: list = []
_fno_stock_cache_ts: float = 0.0


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
    "ICICIGI","ICICIlombard","INDHOTEL","IOC","IGL",
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


def _fetch_nse_index(index_slug: str, min_count: int) -> set:
    import requests as _req
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/",
    }
    s = _req.Session()
    s.get("https://www.nseindia.com", headers=hdrs, timeout=8)
    r = s.get(f"https://www.nseindia.com/api/equity-stockIndices?index={index_slug}",
              headers=hdrs, timeout=10)
    data = r.json().get("data", [])
    symbols = {item["symbol"] for item in data[1:] if item.get("symbol")}
    if len(symbols) < min_count:
        raise ValueError(f"only {len(symbols)} symbols returned, expected >= {min_count}")
    return symbols


def _fetch_nifty50_symbols() -> set:
    global _nifty50_cache, _nifty50_cache_ts
    now = datetime.utcnow()
    if _nifty50_cache and _nifty50_cache_ts and (now - _nifty50_cache_ts).total_seconds() < 86400:
        return _nifty50_cache
    try:
        symbols = _fetch_nse_index("NIFTY%2050", 45)
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
        symbols = _fetch_nse_index("NIFTY%20500", 450)
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
        if not nifty50 and not (min_price <= ltp <= max_price):
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
# Stock Indicators — RSI, EMA trend, volume, candle pattern for any NSE stock
# ══════════════════════════════════════════════════════════════════════════════

def _stock_indicators_sync(symbol: str) -> dict:
    import yfinance as yf
    import pandas as pd

    ticker = symbol.upper() + ".NS"
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 50:
            return {"error": f"Not enough data for {symbol}"}

        closes  = df["Close"].squeeze().dropna().tolist()
        volumes = df["Volume"].squeeze().dropna().tolist()
        opens   = df["Open"].squeeze().dropna().tolist()
        highs   = df["High"].squeeze().dropna().tolist()
        lows    = df["Low"].squeeze().dropna().tolist()

        # RSI(14)
        delta = pd.Series(closes).diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss.replace(0, float('nan'))
        rsi_val = round(float(100 - 100 / (1 + rs.iloc[-1])), 2)

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

        return {
            "symbol":       symbol.upper(),
            "rsi":          rsi_val,
            "trend":        trend,
            "ema20":        round(ema20, 2),
            "ema50":        round(ema50, 2),
            "volumeSignal": vol_signal,
            "volume":       int(cur_vol),
            "candlePattern":candle,
            "support":      support,
            "resistance":   resistance,
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
    get_oi_change_signals as _oc_oi_signals,
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
    global smart
    _s = smart or _get_smart()
    chain_data = _oc_fetch_chain(_s, symbol, expiry, spot_price)
    if "error" in chain_data:
        return chain_data
    chain       = chain_data.get("chain", [])
    analytics   = _oc_max_pain(chain, spot_price)
    oi_signals  = _oc_oi_signals(symbol, expiry, chain)
    return {**chain_data, "analytics": analytics, "oi_signals": oi_signals}


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

        if df is None or df.empty:
            log.warning(f"_compute_candle_data({symbol}): no intraday data for today")
            return None

        closes  = df["Close"]
        volumes = df["Volume"]

        ema9       = float(closes.ewm(span=9,  adjust=False).mean().iloc[-1])
        ema21      = float(closes.ewm(span=21, adjust=False).mean().iloc[-1])
        close      = float(closes.iloc[-1])
        volume     = float(volumes.iloc[-1])
        avg_volume = float(volumes.mean())

        # VWAP
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        cum_vol  = volumes.replace(0, float("nan")).cumsum().iloc[-1]
        vwap     = float((typical * volumes).cumsum().iloc[-1] / cum_vol) if cum_vol and cum_vol > 0 else close

        # RSI(14) Wilder EWM
        delta     = closes.diff()
        gain      = delta.where(delta > 0, 0.0).ewm(com=13, adjust=False).mean()
        loss      = (-delta.where(delta < 0, 0.0)).ewm(com=13, adjust=False).mean()
        last_loss = float(loss.iloc[-1])
        last_gain = float(gain.iloc[-1])
        rsi = float(100 - 100 / (1 + last_gain / last_loss)) if last_loss > 0 else (100.0 if last_gain > 0 else 50.0)

        log.info(f"_compute_candle_data({symbol}): close={close:.1f} ema9={ema9:.1f} ema21={ema21:.1f} vwap={vwap:.1f} rsi={rsi:.1f} bars={len(df)}")
        return {
            "close": close, "vwap": vwap,
            "volume": volume, "avg_volume": avg_volume,
            "ema9": ema9, "ema21": ema21, "rsi": rsi,
        }
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
            global smart
            _s = smart or _get_smart()
            chain_data = _oc_fetch_chain(_s, symbol, expiry, effective_spot)
            if "error" not in chain_data:
                chain      = chain_data.get("chain", [])
                analytics  = _oc_max_pain(chain, effective_spot)
                oi_signals = _oc_oi_signals(symbol, expiry, chain)
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
    """
    global smart
    try:
        if not expiry:
            exp_list = _oc_expiries(symbol)
            expiry   = exp_list[0] if exp_list else ""
        if not expiry:
            return {"error": "No expiry found"}
        _s = smart or _get_smart()
        chain_data = _oc_fetch_chain(_s, symbol, expiry, spot_price)
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


@app.get("/stocks/movers")
def stocks_movers(index: str = "nifty50"):
    """Top/bottom 10 movers for the given NSE index. 5-minute cache."""
    from core.movers import fetch_movers as _fetch_movers
    try:
        return _fetch_movers(index)
    except Exception as e:
        log.error(f"stocks/movers error: {e}")
        return {"error": str(e)}


@app.get("/stocks/live-prices")
def stocks_live_prices(index: str = "nifty50"):
    """Current LTPs for index constituents. NSE primary, Yahoo fallback. 5-second cache."""
    from core.movers import fetch_live_prices as _fetch_prices
    try:
        return _fetch_prices(index)
    except Exception as e:
        log.error(f"stocks/live-prices error: {e}")
        return {"error": str(e)}


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
    from core.swing_analyzer import scan_stocks, NIFTY50, NIFTY_NEXT50
    try:
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


@app.get("/options/past-expiries")
def options_past_expiries(symbol: str = "NIFTY"):
    """
    Return recent expiry dates for the given symbol.
    NIFTY  → weekly Thursdays (weekday 3)
    BANKNIFTY / MIDCPNIFTY → weekly Wednesdays (weekday 2)
    FINNIFTY → weekly Tuesdays (weekday 1)
    Stocks / others → monthly last-Thursday of each month.
    Returns up to 12 dates in reverse-chronological order (most recent first),
    from 90 days ago up to 7 days ahead (current/next week included).
    """
    sym   = symbol.upper()
    today = _dt.date.today()

    # Weekly index expiry day
    weekly = {"NIFTY": 3, "BANKNIFTY": 2, "MIDCPNIFTY": 2, "FINNIFTY": 1}

    expiries: list[str] = []

    if sym in weekly:
        target_wd = weekly[sym]
        d = today + _dt.timedelta(days=7)          # start from 1 week ahead
        while d >= today - _dt.timedelta(days=90):
            if d.weekday() == target_wd:
                expiries.append(d.isoformat())
            d -= _dt.timedelta(days=1)
    else:
        # Monthly: last Thursday of each month
        import calendar
        yr, mo = today.year, today.month
        for _ in range(12):
            last_day = calendar.monthrange(yr, mo)[1]
            d = _dt.date(yr, mo, last_day)
            while d.weekday() != 3:
                d -= _dt.timedelta(days=1)
            if d <= today + _dt.timedelta(days=7):
                expiries.append(d.isoformat())
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
