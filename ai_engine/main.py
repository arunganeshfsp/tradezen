"""
TradeZen AI Engine — FastAPI server
Clean version with:
✔ Proper lifecycle
✔ Option chain subscription
✔ Non-blocking WebSocket
✔ Stable signal loop
"""

import asyncio
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
}


# ──────────────────────────────────────────────
# Lifespan (runs once on startup)
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global signal_engine, chain_map, im
    log.info("🚀 Starting AI Engine...")

    # 🔐 Connect SmartAPI
    smart = get_smart_api()

    # 📊 Load instruments (uses global im so endpoints can call it too)
    im.load()

    # 📅 Fetch previous trading day NIFTY OHLC for CPR calculation
    # Angel One getCandleData works for equities; for NIFTY index (26000) it may
    # return an empty data list on some API versions.  We try ONE_DAY first; if
    # that is empty we fall back to ONE_HOUR and derive H/L/C from the day's bars.
    try:
        ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        prev = ist_now - timedelta(days=1)
        while prev.weekday() >= 5:       # skip weekends
            prev -= timedelta(days=1)
        from_dt = prev.strftime("%Y-%m-%d 09:15")
        to_dt   = prev.strftime("%Y-%m-%d 15:30")

        # Attempt order:
        #  1. NSE index token (26000) ONE_DAY  — works on some API versions
        #  2. NSE index token (26000) ONE_HOUR — derives daily H/L from hourly bars
        #  3. NFO nearest futures token ONE_DAY — always tradeable, ≈ spot ± basis
        #  4. NFO nearest futures token ONE_HOUR
        fut_token = im.get_nifty_futures_token()
        log.info(f"📅 Nearest NIFTY futures token for OHLC fallback: {fut_token}")

        attempts = [
            ("NSE", SPOT_TOKEN,             "ONE_DAY"),
            ("NSE", SPOT_TOKEN,             "ONE_HOUR"),
            ("NFO", fut_token or SPOT_TOKEN, "ONE_DAY"),
            ("NFO", fut_token or SPOT_TOKEN, "ONE_HOUR"),
        ]

        ohlc_loaded = False
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
                    d = rows[-1]             # [ts, open, high, low, close, vol]
                    H, L, C = float(d[2]), float(d[3]), float(d[4])
                else:
                    H = max(float(r[2]) for r in rows)   # day high from hourly bars
                    L = min(float(r[3]) for r in rows)   # day low
                    C = float(rows[-1][4])               # last bar's close
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
                "⚠️ All getCandleData attempts returned no rows. "
                "CPR on trade-flow page will show N/A. "
                "Use POST /set-prev-ohlc or the yellow banner on the page to supply values."
            )
    except Exception as e:
        log.warning(f"⚠️ Prev OHLC fetch error: {e}")

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
        global last_signal

        while True:
            try:
                if signal_engine:
                    result = signal_engine.generate()
                    if result:
                        last_signal = result

                # ── Track opening price and ORB ─────────────────────────
                spot = market_state.get(SPOT_TOKEN)
                if spot and spot.get("price"):
                    price  = spot["price"]
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

    # Live NIFTY price
    spot = market_state.get(SPOT_TOKEN)
    nifty_ltp = round(spot["price"], 2) if spot and spot.get("price") else None

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
        S1   = round(2 * PP - H, 2)
        S2   = round(PP - (H - L), 2)
        width = round(TC - BC, 2)             # always positive
        cpr = {
            "pp": PP, "tc": TC, "bc": BC,
            "r1": R1, "r2": R2, "s1": S1, "s2": S2,
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
        orb_data = {
            "high":    orb["high"],
            "low":     orb["low"],
            "range":   orb_range,
            "vs_cpr":  vs_cpr,
            "t1_bull": round(orb["high"] + orb_range, 2),
            "t2_bull": round(orb["high"] + 2 * orb_range, 2),
            "sl_bull": round(orb["high"] - 20, 2),
            "t1_bear": round(orb["low"] - orb_range, 2),
            "t2_bear": round(orb["low"] - 2 * orb_range, 2),
            "sl_bear": round(orb["low"] + 20, 2),
        }

    # ── Auto scenario determination ───────────────────────────────────────────
    scenario = "unknown"
    if open_data and orb_data:
        op = open_data["position"]
        ov = orb_data["vs_cpr"]
        if op == "above_tc" and ov == "above_tc":
            scenario = "bull"
        elif op == "below_bc" and ov == "below_bc":
            scenario = "bear"
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
        "gift_nifty":  trade_flow_data.get("gift_nifty"),   # None until set manually
        "cpr":         cpr,
        "nifty_open":  open_data,
        "orb":         orb_data,
        "nifty_ltp":   nifty_ltp,
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
