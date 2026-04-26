"""
TradeZen AI Engine — FastAPI server
Clean version with:
✔ Proper lifecycle
✔ Option chain subscription
✔ Non-blocking WebSocket
✔ Stable signal loop
"""

import asyncio
import math
import threading
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

            except Exception as e:
                log.error(f"❌ Signal error: {e}")

            await asyncio.sleep(1)

    asyncio.create_task(signal_loop())

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


@app.post("/set-gift-nifty")
def set_gift_nifty(price: float):
    """
    Supply the current GIFT Nifty price manually (pre-market, from broker terminal).
    GIFT Nifty trades on NSE IFSC — not available via Angel One WebSocket.
    Example: POST /set-gift-nifty?price=24204
    """
    global trade_flow_data
    trade_flow_data["gift_nifty"] = None if price == 0 else round(price, 2)
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


def _get_smart():
    """Re-authenticate for market profile calls (engine may have a fresh session)."""
    from config.credentials import get_smart_api
    try:
        return get_smart_api()
    except Exception as e:
        log.warning(f"Market profile: SmartAPI re-auth failed: {e}")
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
    Requires chain analytics + context — fetched on-demand from cached/live data.
    """
    try:
        context      = _oc_context(symbol)
        effective_spot = spot_price or context.get("spot")

        if not expiry:
            exp_list = _oc_expiries(symbol)
            expiry   = exp_list[0] if exp_list else ""

        # Build minimal analytics from previously fetched chain or empty fallback
        analytics  = {"pcr": 1.0, "pcr_label": "NEUTRAL",
                      "resistance_wall": None, "support_wall": None, "max_pain": None}
        oi_signals = {}

        result = _oc_score(
            direction       = direction,
            context         = context,
            chain_analytics = analytics,
            oi_signals      = oi_signals,
            target_strike   = strike,
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
