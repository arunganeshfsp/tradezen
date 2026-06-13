"""
Reversal Radar — fallen-leader reversal scanner.

Finds quality large/mid-caps that have fallen meaningfully from their 52-week
high and are showing a CONFIRMED turn — not a falling knife or a dead-cat bounce.
This is the mean-reversion counterpart to swing_analyzer's trend-following engine,
which explicitly rejects fallen stocks (it requires price > EMA50, RSI 50-70,
15%+ above the 52-week low).

Reuses swing_analyzer's universe, market/sector fetchers, in-memory cache, ATR and
position sizing. Fundamental gate runs only on the chart-passing shortlist.
"""

import logging
import time
import datetime as _dt
import pandas as pd

from .indicators.rsi import calculate_rsi
from .indicators.macd import calculate_macd
from .swing_analyzer import (
    STOCK_INFO, NIFTY50, NIFTY_NEXT50,
    _fetch_nifty_data, _fetch_vix, _fetch_sector_1m, _fetch_stock_daily,
    _atr14, _position_size, _vix_zone, _evict_stale, _CACHE, _CACHE_TTL_STOCK,
)

log = logging.getLogger(__name__)
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

# ── Quality midcap extension (sector-mapped, ₹15,000 Cr+ liquid names) ──────────
MIDCAP_INFO: dict[str, dict] = {
    "COFORGE":    {"name": "Coforge",                  "sector": "IT"},
    "TATAELXSI":  {"name": "Tata Elxsi",               "sector": "IT"},
    "KPITTECH":   {"name": "KPIT Technologies",        "sector": "IT"},
    "SUPREMEIND": {"name": "Supreme Industries",       "sector": "Consumer"},
    "ASTRAL":     {"name": "Astral",                   "sector": "Consumer"},
    "DIXON":      {"name": "Dixon Technologies",       "sector": "Consumer"},
    "CUMMINSIND": {"name": "Cummins India",            "sector": "Capital Goods"},
    "THERMAX":    {"name": "Thermax",                  "sector": "Capital Goods"},
    "CGPOWER":    {"name": "CG Power & Industrial",    "sector": "Capital Goods"},
    "BHARATFORG": {"name": "Bharat Forge",             "sector": "Auto"},
    "ASHOKLEY":   {"name": "Ashok Leyland",            "sector": "Auto"},
    "BALKRISIND": {"name": "Balkrishna Industries",    "sector": "Auto"},
    "MRF":        {"name": "MRF",                      "sector": "Auto"},
    "ESCORTS":    {"name": "Escorts Kubota",           "sector": "Auto"},
    "AUROPHARMA": {"name": "Aurobindo Pharma",         "sector": "Pharma"},
    "ZYDUSLIFE":  {"name": "Zydus Lifesciences",       "sector": "Pharma"},
    "BIOCON":     {"name": "Biocon",                   "sector": "Pharma"},
    "MAXHEALTH":  {"name": "Max Healthcare",           "sector": "Healthcare"},
    "FORTIS":     {"name": "Fortis Healthcare",        "sector": "Healthcare"},
    "FEDERALBNK": {"name": "Federal Bank",             "sector": "Banking"},
    "AUBANK":     {"name": "AU Small Finance Bank",    "sector": "Banking"},
    "MUTHOOTFIN": {"name": "Muthoot Finance",          "sector": "Financials"},
    "SUNDARMFIN": {"name": "Sundaram Finance",         "sector": "Financials"},
    "PETRONET":   {"name": "Petronet LNG",             "sector": "Energy"},
    "NMDC":       {"name": "NMDC",                     "sector": "Metal"},
    "APLAPOLLO":  {"name": "APL Apollo Tubes",         "sector": "Metal"},
    "JUBLFOOD":   {"name": "Jubilant FoodWorks",       "sector": "Consumer"},
    "PRESTIGE":   {"name": "Prestige Estates",         "sector": "Realty"},
    "PHOENIXLTD": {"name": "Phoenix Mills",            "sector": "Realty"},
    "OFSS":       {"name": "Oracle Financial Services","sector": "IT"},
}
MIDCAP_SELECT = list(MIDCAP_INFO.keys())

# Reversal-specific gates
FALL_MIN_DEFAULT = 15.0    # % below 52w high to even be a reversal candidate
FALL_MAX         = 65.0    # beyond this the fall is usually structural, not a dip
MCAP_FLOOR_CR    = 5_000   # large-cap quality floor
LIQ_FLOOR        = 300_000 # min avg shares/day
FUND_SHORTLIST   = 12      # run the (slow) fundamental gate on this many at most
_CACHE_TTL_FUND  = 3600    # 1h — fundamentals barely move intraday


def _info(sym: str) -> dict:
    return STOCK_INFO.get(sym) or MIDCAP_INFO.get(sym) or {"name": sym, "sector": "Unknown"}


# ── Small structural helpers ────────────────────────────────────────────────────

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _pivots(series: pd.Series, left: int = 3, right: int = 3, kind: str = "low") -> list[tuple[int, float]]:
    """Confirmed local minima/maxima. The trailing `right` bars cannot form a
    pivot yet — that confirmation lag is what stops us calling a low too early."""
    vals = series.values
    n = len(vals)
    out: list[tuple[int, float]] = []
    for i in range(left, n - right):
        window = vals[i - left:i + right + 1]
        if kind == "low" and vals[i] == window.min():
            out.append((i, float(vals[i])))
        elif kind == "high" and vals[i] == window.max():
            out.append((i, float(vals[i])))
    return out


def _bull_trigger(df: pd.DataFrame, lookback: int = 3) -> tuple[bool, str]:
    """A reversal candle in the last few bars: engulfing / hammer / strong up-close."""
    for k in range(1, lookback + 1):
        if len(df) < k + 1:
            break
        o = float(df["Open"].iloc[-k]);  c = float(df["Close"].iloc[-k])
        h = float(df["High"].iloc[-k]);  l = float(df["Low"].iloc[-k])
        po = float(df["Open"].iloc[-k - 1]); pc = float(df["Close"].iloc[-k - 1])
        rng  = (h - l) or 1e-9
        body = abs(c - o)
        if c > o and pc < po and c >= po and o <= pc:
            return True, "bullish engulfing"
        lower_wick = min(o, c) - l
        if c >= o and lower_wick > body * 1.5 and (c - l) / rng > 0.6:
            return True, "hammer (long lower wick)"
        if c > o and body / rng > 0.6 and c > pc:
            return True, "strong bullish close"
    return False, "no clear reversal candle yet"


def _fetch_fundamentals(symbol: str) -> dict:
    """Company-health gate via yfinance .info. Cached 1h. Returns a rating and a
    `sound` flag separating 'fell on sentiment' from 'fell on broken fundamentals'."""
    key = f"__f_{symbol}__"
    c = _CACHE.get(key)
    if c and time.time() - c["ts"] < _CACHE_TTL_FUND:
        return c["data"]

    import yfinance as yf
    roe = de = eg = pm = None
    try:
        info = yf.Ticker(symbol + ".NS").info or {}
        roe = info.get("returnOnEquity")
        de  = info.get("debtToEquity")
        eg  = info.get("earningsGrowth")
        pm  = info.get("profitMargins")
    except Exception as e:
        log.warning(f"[Reversal] fundamentals fetch failed {symbol}: {e}")

    roe_pct = round(roe * 100, 1) if roe is not None else None
    eg_pct  = round(eg * 100, 1) if eg is not None else None
    pm_pct  = round(pm * 100, 1) if pm is not None else None
    de_val  = round(float(de), 1) if de is not None else None

    pts = 0
    pts += 1 if (roe_pct is not None and roe_pct >= 12) else 0
    pts += 1 if (de_val is not None and de_val < 100) else 0          # de is in % form
    pts += 1 if (eg_pct is None or eg_pct >= -25) else 0              # tolerate a dip, not a collapse
    pts += 1 if (pm_pct is not None and pm_pct > 0) else 0

    have_any = any(v is not None for v in (roe_pct, de_val, eg_pct, pm_pct))
    if not have_any:
        rating, sound = "Unknown", True   # thin data — don't penalise, just flag
    elif pts >= 4:
        rating, sound = "Strong", True
    elif pts >= 3:
        rating, sound = "Healthy", True
    elif pts >= 2:
        rating, sound = "Mixed", True
    else:
        rating, sound = "Caution", False

    data = {
        "roe_pct": roe_pct, "de": de_val, "earnings_growth_pct": eg_pct,
        "profit_margin_pct": pm_pct, "rating": rating, "sound": sound, "points": pts,
    }
    _CACHE[key] = {"ts": time.time(), "data": data}
    return data


# ── Core chart evaluation (no fundamentals, no market wrapper) ───────────────────

def _evaluate(df: pd.DataFrame, sym: str, capital: float, risk_pct: float,
              min_fall: float, nifty_1m: float) -> dict:
    close = df["Close"]; high = df["High"]; low = df["Low"]; vol = df["Volume"]
    n = len(close)
    info   = _info(sym)
    sector = info["sector"]
    ltp = round(float(close.iloc[-1]), 2)

    win        = min(252, n)
    high_252   = float(high.iloc[-win:].max())
    low_252    = float(low.iloc[-win:].min())
    drawdown   = round((high_252 - ltp) / high_252 * 100, 1) if high_252 > 0 else 0.0
    off_low    = round((ltp - low_252) / low_252 * 100, 1) if low_252 > 0 else 0.0

    sma20  = _sma(close, 20)
    sma50  = _sma(close, 50)
    sma200 = _sma(close, 200)
    rsi    = calculate_rsi(close, 14)
    macd   = calculate_macd(close)
    hist   = macd["macd_line"] - macd["signal_line"]
    atr    = round(_atr14(df), 2)

    vol20     = float(vol.iloc[-21:-1].mean()) if n >= 21 else float(vol.mean())
    vol20     = max(1.0, vol20)
    vol_today = float(vol.iloc[-1])
    mcap_cr   = None  # filled by caller via fast_info when available

    # ── Pivots / structure ──────────────────────────────────────────────────────
    p_lows  = _pivots(low, 3, 3, "low")
    p_highs = _pivots(high, 3, 3, "high")
    recent_swing_low = p_lows[-1][1] if p_lows else float(low.iloc[-20:].min())

    higher_low = False
    if len(p_lows) >= 2:
        higher_low = p_lows[-1][1] > p_lows[-2][1] * 1.002

    # Bullish RSI divergence: price made a lower low but RSI made a higher low.
    divergence = False
    if len(p_lows) >= 2:
        (i1, pp1), (i2, pp2) = p_lows[-2], p_lows[-1]
        if pp2 < pp1 and float(rsi.iloc[i2]) > float(rsi.iloc[i1]) + 1:
            divergence = True

    # ── Confirmation checks ─────────────────────────────────────────────────────
    sma20_now = float(sma20.iloc[-1]) if not pd.isna(sma20.iloc[-1]) else ltp
    above20   = ltp > sma20_now
    was_below = int((close.iloc[-15:-2] < sma20.iloc[-15:-2]).sum()) >= 3
    reclaim   = above20 and was_below

    rsi_now    = round(float(rsi.iloc[-1]), 1)
    rsi_min12  = float(rsi.iloc[-12:].min())
    rsi_turn   = rsi_min12 < 40 and rsi_now > 40 and rsi_now > float(rsi.iloc[-3:-1].min())

    macd_up = (float(hist.iloc[-1]) > float(hist.iloc[-2]) > float(hist.iloc[-4])) or (
        float(macd["macd_line"].iloc[-1]) > float(macd["signal_line"].iloc[-1])
        and float(macd["macd_line"].iloc[-2]) <= float(macd["signal_line"].iloc[-2]))

    bull_candle, candle_desc = _bull_trigger(df)

    rec      = df.iloc[-10:]
    up_vol   = float(rec.loc[rec["Close"] >= rec["Open"], "Volume"].sum())
    dn_vol   = float(rec.loc[rec["Close"] <  rec["Open"], "Volume"].sum())
    accumulation = up_vol > dn_vol
    vol_surge    = vol_today >= vol20 * 1.3
    vol_confirm  = accumulation or vol_surge
    vol_ratio    = round(vol_today / vol20, 2)

    momentum_ok = rsi_turn or macd_up
    confirmed   = higher_low and reclaim and momentum_ok and vol_confirm

    # ── Support quality ─────────────────────────────────────────────────────────
    sma200_now = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else None
    near_200   = sma200_now is not None and abs(ltp - sma200_now) / sma200_now <= 0.05
    near_52low = off_low <= 10
    demand_band = max(0.04, (atr / ltp) * 1.5) if ltp else 0.04
    near_demand = any(abs(ltp - p) / p <= demand_band for (_, p) in p_lows[:-1])
    support_count = sum([near_200, near_52low, near_demand])
    support_bits = []
    if near_200:    support_bits.append("200-DMA")
    if near_52low:  support_bits.append("52-week-low band")
    if near_demand: support_bits.append("prior demand zone")
    support_desc = " + ".join(support_bits) if support_bits else "no major support nearby"

    # ── Sector context (never rejects) ──────────────────────────────────────────
    sector_1m = _fetch_sector_1m(sector)
    sector_tail = sector_1m > nifty_1m
    sector_desc = (f"{sector} {sector_1m:+.1f}% vs Nifty {nifty_1m:+.1f}% — "
                   f"{'tailwind' if sector_tail else 'headwind'}")

    # ── Checklist (educational) ─────────────────────────────────────────────────
    def item(ok, label, note):
        return {"pass": bool(ok), "label": label, "note": note}

    checklist = [
        item(higher_low, "Higher low formed" if higher_low else "No higher low yet",
             "The stock has stopped making new lows — the most recent swing low sits above the previous one. This is the first sign sellers are losing control."
             if higher_low else "Price is still carving lower lows. Until a low holds above the prior one, the fall isn't over — this is the classic falling-knife trap."),
        item(reclaim, "Reclaimed 20-day average" if reclaim else "Below 20-day average",
             "Price has crossed back above its 20-day average after trading below it through the fall — short-term momentum has flipped up."
             if reclaim else "Price is still under its 20-day average. A reversal isn't confirmed until it reclaims this line."),
        item(momentum_ok, "Momentum turning up" + (" (RSI divergence)" if divergence else ""),
             ("Bullish RSI divergence: price made a lower low but momentum made a higher low — selling pressure is exhausting." if divergence
              else "RSI has turned up from oversold / MACD momentum is rising — buyers are stepping back in.")
             if momentum_ok else "Momentum (RSI / MACD) hasn't turned up yet. A bounce without a momentum shift often fades."),
        item(vol_confirm, f"Volume confirms ({vol_ratio}× avg)" if vol_confirm else f"Weak volume ({vol_ratio}× avg)",
             "Buyers actually showed up — up-day volume outweighs down-day volume / today's volume is above average. Participation validates the turn."
             if vol_confirm else "The bounce is on thin volume. A move nobody is buying is often a dead-cat bounce that rolls back over."),
        item(bull_candle, f"Reversal candle: {candle_desc}" if bull_candle else "No reversal candle",
             "A clean bullish reversal candle (engulfing / hammer / strong close) marks where buyers took over." if bull_candle
             else "No decisive bullish candle in the last few sessions — the turn lacks a clear trigger bar."),
        item(support_count > 0, f"At support: {support_desc}" if support_count else "Not at major support",
             "The turn is happening at a meaningful floor (moving average / old demand / 52-week-low band) — reversals that start at support hold better."
             if support_count else "Price isn't near a major support level, so there's little structural floor under this bounce."),
    ]

    # ── Reversal score (0-100; fundamentals folded in later by the caller) ───────
    conf_hits   = sum([higher_low, reclaim, momentum_ok, vol_confirm, bull_candle]) + (1 if divergence else 0)
    conf_score  = min(40.0, conf_hits / 5 * 40)
    support_sc  = support_count / 3 * 20
    vol_sc      = (0.6 if vol_surge else 0) * 15 + (0.4 if accumulation else 0) * 15
    sector_sc   = 10 if sector_tail else 4
    base_score  = round(conf_score + support_sc + vol_sc + sector_sc, 1)  # of 85; +15 fundamentals

    # ── Study levels (SEBI: descriptive, never directives) ──────────────────────
    reference   = round(recent_swing_low, 2)
    invalidation = round(min(recent_swing_low * 0.98, ltp - 1.5 * atr), 2)
    overhead = sorted([p for (_, p) in p_highs if p > ltp * 1.01])
    if sma50.iloc[-1] and not pd.isna(sma50.iloc[-1]) and float(sma50.iloc[-1]) > ltp:
        overhead.append(round(float(sma50.iloc[-1]), 2))
    if sma200_now and sma200_now > ltp:
        overhead.append(round(sma200_now, 2))
    overhead = sorted(set(round(x, 2) for x in overhead))
    supply_1 = overhead[0] if overhead else round(high_252, 2)
    supply_2 = overhead[1] if len(overhead) > 1 else round(high_252, 2)
    sl_dist  = max(ltp - invalidation, 0.01)
    rr       = round((supply_1 - ltp) / sl_dist, 2)
    pos      = _position_size(ltp, invalidation, capital, risk_pct)

    # ── Reject / bucket reasoning ───────────────────────────────────────────────
    knife    = (not higher_low) and abs(ltp - recent_swing_low) / max(recent_swing_low, 1) <= 0.04
    dead_cat = above20 and not vol_confirm and not accumulation

    bucket, reason = "watching", ""
    if drawdown < min_fall:
        bucket, reason = "not_fallen", f"Only {drawdown:.0f}% below its 52-week high — not in a correction yet."
    elif drawdown > FALL_MAX:
        bucket, reason = "rejected", f"Down {drawdown:.0f}% from high — too deep, usually a structural problem, not a dip."
    elif knife:
        bucket, reason = "rejected", "Still making lower lows — the knife is still falling. No higher low to lean on."
    elif confirmed and support_count > 0:
        bucket, reason = "candidate", f"Confirmed turn at support, down {drawdown:.0f}% from high."
    elif dead_cat:
        bucket, reason = "rejected", "Bounce on weak volume — dead-cat risk. Buyers haven't shown up."
    elif support_count == 0:
        bucket, reason = "rejected", "Turning, but not at any major support — weak floor under the bounce."
    else:
        done = sum([higher_low, reclaim, momentum_ok, vol_confirm])
        bucket, reason = "watching", f"Basing ({done}/4 confirmations) — not fully confirmed yet."

    return {
        "symbol": sym, "name": info["name"], "sector": sector,
        "ltp": ltp, "drawdown_pct": drawdown, "off_52w_low_pct": off_low,
        "high_52w": round(high_252, 2), "low_52w": round(low_252, 2),
        "rsi": rsi_now, "atr": atr, "vol_ratio": vol_ratio,
        "vol_today": int(vol_today), "vol_avg20": int(vol20),
        "divergence": divergence,
        "support": {"count": support_count, "desc": support_desc,
                    "near_200dma": near_200, "near_52w_low": near_52low, "near_demand": near_demand},
        "sector_ctx": {"sector_1m": sector_1m, "nifty_1m": nifty_1m,
                       "tailwind": sector_tail, "desc": sector_desc},
        "checklist": checklist,
        "confirmed": confirmed,
        "study_levels": {
            "reference_reversal": reference,
            "structure_invalidation": invalidation,
            "prior_supply_1": supply_1,
            "prior_supply_2": supply_2,
            "rr": rr,
        },
        "position": pos,
        "base_score": base_score,
        "bucket": bucket, "reason": reason,
    }


def _attach_fundamentals(rec: dict) -> dict:
    f = _fetch_fundamentals(rec["symbol"])
    rec["fundamentals"] = f
    fund_sc = {"Strong": 15, "Healthy": 12, "Mixed": 7, "Caution": 2, "Unknown": 8}.get(f["rating"], 8)
    rec["score"] = round(min(100.0, rec["base_score"] + fund_sc), 1)
    # A confirmed chart turn in a financially unsound company is demoted, not trusted.
    if not f["sound"] and rec["bucket"] == "candidate":
        rec["bucket"] = "watching"
        rec["reason"] = "Chart has turned, but financials look weak (possible value trap) — study, don't chase."
    return rec


# ── Public: single-stock analyse ────────────────────────────────────────────────

def analyse_reversal(symbol: str, capital: float = 75000, risk_pct: float = 2,
                     min_fall: float = FALL_MIN_DEFAULT) -> dict:
    _evict_stale()
    try:
        nifty_close, nifty_ema50_w, nifty_1m = _fetch_nifty_data()
        vix = _fetch_vix() or 15.0
        df, mcap_cr = _fetch_stock_daily(symbol)
    except Exception as e:
        log.error(f"reversal analyse error {symbol}: {e}", exc_info=True)
        return {"error": str(e), "symbol": symbol}

    rec = _evaluate(df, symbol, capital, risk_pct, min_fall, nifty_1m)
    rec["mcap_cr"] = round(mcap_cr, 0)
    rec = _attach_fundamentals(rec)

    vix_zone_name, vix_color = _vix_zone(vix)
    rec["market"] = {
        "nifty_close": round(nifty_close, 2),
        "nifty_ema50_w": round(nifty_ema50_w, 2),
        "nifty_vs_ema50": "ABOVE" if nifty_close > nifty_ema50_w else "BELOW",
        "nifty_1m_chg": nifty_1m,
        "vix": round(vix, 2), "vix_zone": vix_zone_name, "vix_color": vix_color,
    }
    if vix >= 25 and rec["bucket"] == "candidate":
        rec["bucket"] = "watching"
        rec["reason"] = f"Setup is confirmed, but VIX {vix:.0f} signals extreme market fear — stand aside."
    rec["date"] = str(_dt.datetime.now(IST).date())
    return rec


# ── Public: batch scan ──────────────────────────────────────────────────────────

def scan_reversals(symbols: list[str], capital: float = 75000, risk_pct: float = 2,
                   min_fall: float = FALL_MIN_DEFAULT) -> dict:
    import yfinance as yf
    _evict_stale()
    try:
        nifty_close, nifty_ema50_w, nifty_1m = _fetch_nifty_data()
        vix = _fetch_vix() or 15.0
    except Exception as e:
        return {"error": f"Market data unavailable: {e}"}

    vix_zone_name, vix_color = _vix_zone(vix)
    yf_syms = [s + ".NS" for s in symbols]
    log.info(f"[ReversalScan] batch-downloading {len(yf_syms)} symbols…")
    try:
        raw = yf.download(yf_syms, period="1y", interval="1d",
                          auto_adjust=False, progress=False, threads=True)
    except Exception as e:
        return {"error": f"Batch download failed: {e}"}

    def _col(field: str, sym: str) -> pd.Series:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                if (field, sym) in raw.columns:
                    return raw[field][sym].dropna()
                return pd.Series(dtype=float)
            if len(yf_syms) == 1 and field in raw.columns:
                return raw[field].dropna()
            return pd.Series(dtype=float)
        except Exception:
            return pd.Series(dtype=float)

    candidates: list[dict] = []
    watching:   list[dict] = []
    rejected:   list[dict] = []

    for sym in symbols:
        ys = sym + ".NS"
        try:
            df = pd.DataFrame({
                "Open":   _col("Open", ys),  "High":   _col("High", ys),
                "Low":    _col("Low", ys),   "Close":  _col("Close", ys),
                "Volume": _col("Volume", ys),
            }).dropna()
            if len(df) < 60:
                rejected.append({"symbol": sym, "name": _info(sym)["name"],
                                 "bucket": "rejected", "reason": "Insufficient price history."})
                continue

            vol_avg20 = float(df["Volume"].iloc[-21:-1].mean()) if len(df) >= 21 else float(df["Volume"].mean())
            if vol_avg20 < LIQ_FLOOR:
                rejected.append({"symbol": sym, "name": _info(sym)["name"],
                                 "bucket": "rejected", "reason": f"Low liquidity ({int(vol_avg20):,}/day)."})
                continue

            rec = _evaluate(df, sym, capital, risk_pct, min_fall, nifty_1m)

            if rec["bucket"] == "not_fallen":
                continue  # not a reversal candidate; omit from the teaching lists
            if rec["bucket"] == "candidate":
                candidates.append(rec)
            elif rec["bucket"] == "watching":
                watching.append(rec)
            else:
                rejected.append(rec)
        except Exception as e:
            log.warning(f"[ReversalScan] {sym}: {e}")
            rejected.append({"symbol": sym, "name": _info(sym)["name"],
                             "bucket": "rejected", "reason": f"Data error: {e}"})

    # Fundamental gate only on the strongest chart candidates (the slow part).
    candidates.sort(key=lambda r: r["base_score"], reverse=True)
    graded = [_attach_fundamentals(r) for r in candidates[:FUND_SHORTLIST]]
    for r in candidates[FUND_SHORTLIST:]:
        r["fundamentals"] = None
        r["score"] = r["base_score"]
    # Re-bucket: fundamentals may demote a candidate to watching.
    final_candidates = [r for r in graded if r["bucket"] == "candidate"] + candidates[FUND_SHORTLIST:]
    demoted = [r for r in graded if r["bucket"] != "candidate"]
    watching.extend(demoted)
    final_candidates.sort(key=lambda r: r["score"], reverse=True)
    watching.sort(key=lambda r: r.get("base_score", 0), reverse=True)

    if vix >= 25:
        for r in final_candidates:
            r["bucket"] = "watching"
            r["reason"] = f"Confirmed, but VIX {vix:.0f} = extreme fear. Stand aside."
        watching = final_candidates + watching
        final_candidates = []

    return {
        "scan_date": str(_dt.datetime.now(IST).date()),
        "total_scanned": len(symbols),
        "min_fall": min_fall,
        "market": {
            "nifty_close": round(nifty_close, 2),
            "nifty_ema50_w": round(nifty_ema50_w, 2),
            "nifty_vs_ema50": "ABOVE" if nifty_close > nifty_ema50_w else "BELOW",
            "nifty_1m_chg": nifty_1m,
            "vix": round(vix, 2), "vix_zone": vix_zone_name, "vix_color": vix_color,
        },
        "candidates": final_candidates,
        "watching": watching[:8],
        "rejected": rejected[:30],
        "counts": {"candidates": len(final_candidates), "watching": len(watching),
                   "rejected": len(rejected)},
    }


def reversal_universe(universe: str) -> list[str]:
    if universe == "midcaps":
        return NIFTY50 + NIFTY_NEXT50 + MIDCAP_SELECT
    return NIFTY50 + NIFTY_NEXT50
