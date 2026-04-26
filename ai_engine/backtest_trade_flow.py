"""
TradeZen — Trade Flow Backtest
Replays CPR + ORB + lean scoring logic against historical NIFTY data.

FULL backtest  (last 7 days):   CPR + opening + ORB + lean score + actual result
LITE backtest  (last 40 days):  CPR + opening position only  (daily data, no ORB)

Run: python backtest_trade_flow.py
"""

import datetime
import yfinance as yf

TICKER = "^NSEI"

# ── CPR & scenario logic  (mirrors main.py exactly) ─────────────────────────

def calc_cpr(H, L, C):
    PP  = round((H + L + C) / 3, 2)
    _bc = round((H + L) / 2, 2)
    _tc = round(2 * PP - _bc, 2)
    TC  = max(_tc, _bc)
    BC  = min(_tc, _bc)
    return {"pp": PP, "tc": TC, "bc": BC, "width": round(TC - BC, 2)}


def open_vs_cpr(price, cpr):
    if price > cpr["tc"]:
        pos = "above_tc"
    elif price < cpr["bc"]:
        pos = "below_bc"
    else:
        pos = "inside_cpr"
    return {
        "price":    price,
        "position": pos,
        "vs_tc":    round(price - cpr["tc"], 2),
        "vs_bc":    round(price - cpr["bc"], 2),
    }


def orb_position(orb_high, orb_low, cpr):
    if orb_low > cpr["tc"]:
        return "above_tc"
    elif orb_high < cpr["bc"]:
        return "below_bc"
    return "straddles"


def lean_score(open_data, orb_high, orb_low, cpr, prev_close):
    s = {"bear": 0, "bull": 0}
    gap = open_data["price"] - prev_close

    # Factor 1: Gap
    if gap < -50:    s["bear"] += 2
    elif gap < -20:  s["bear"] += 1
    elif gap > 50:   s["bull"] += 2
    elif gap > 20:   s["bull"] += 1

    # Factor 2: Opening position
    pos = open_data["position"]
    if pos == "below_bc":
        s["bear"] += 2
    elif pos == "above_tc":
        s["bull"] += 2
    elif pos == "inside_cpr":
        near = cpr["width"] * 0.3
        if open_data["vs_bc"] < near:
            s["bear"] += 1
        elif open_data["vs_tc"] > -near:
            s["bull"] += 1

    # Factor 3: ORB extension scaled by CPR width
    below_bc = cpr["bc"] - orb_low
    above_tc = orb_high - cpr["tc"]
    if below_bc > cpr["width"]:   s["bear"] += 2
    elif below_bc > 0:            s["bear"] += 1
    if above_tc > cpr["width"]:   s["bull"] += 2
    elif above_tc > 0:            s["bull"] += 1

    if s["bear"] >= 3 and s["bear"] > s["bull"]:
        lean = "bear_lean"
    elif s["bull"] >= 3 and s["bull"] > s["bear"]:
        lean = "bull_lean"
    else:
        lean = "neutral"
    return lean, s


def scenario(open_data, vs_cpr, lean):
    pos = open_data["position"]
    if pos == "above_tc" and vs_cpr == "above_tc":       return "bull"
    elif pos == "below_bc" and vs_cpr == "below_bc":     return "bear"
    elif vs_cpr == "straddles" and lean == "bear_lean":  return "conditional_bear"
    elif vs_cpr == "straddles" and lean == "bull_lean":  return "conditional_bull"
    else:                                                return "skip"


# ── Data helpers ─────────────────────────────────────────────────────────────

def fetch_daily(period="60d"):
    df = yf.Ticker(TICKER).history(period=period, interval="1d")
    df.index = df.index.normalize()
    return df


def fetch_intraday(date: datetime.date):
    s = datetime.datetime.combine(date, datetime.time.min)
    e = s + datetime.timedelta(days=1)
    df = yf.Ticker(TICKER).history(start=s, end=e, interval="1m")
    if df.empty:
        return None
    df.index = df.index.tz_convert("Asia/Kolkata")
    return df


def get_orb(df):
    if df is None:
        return None
    ref  = df.index[0]
    t915 = ref.replace(hour=9,  minute=15, second=0, microsecond=0)
    t930 = ref.replace(hour=9,  minute=30, second=0, microsecond=0)
    orb  = df[(df.index >= t915) & (df.index <= t930)]
    if orb.empty:
        return None
    return {
        "high": round(float(orb["High"].max()), 2),
        "low":  round(float(orb["Low"].min()),  2),
    }


def get_open_price(df, fallback):
    if df is None:
        return fallback
    ref  = df.index[0]
    t915 = ref.replace(hour=9,  minute=15, second=0, microsecond=0)
    t916 = ref.replace(hour=9,  minute=16, second=0, microsecond=0)
    candle = df[(df.index >= t915) & (df.index < t916)]
    if candle.empty:
        return round(float(df.iloc[0]["Open"]), 2)
    return round(float(candle.iloc[0]["Open"]), 2)


# ── Outcome validation ───────────────────────────────────────────────────────

SC_LABEL = {
    "bull":             "🟢 BULL",
    "bear":             "🔴 BEAR",
    "conditional_bear": "🟠 COND BEAR",
    "conditional_bull": "🟡 COND BULL",
    "skip":             "⬜ SKIP",
    "unknown":          "❓ —",
}


def verdict(sc, day_open, day_close, orb_high=None, orb_low=None):
    chg     = round(day_close - day_open, 2)
    chg_pct = round(chg / day_open * 100, 2)
    arrow   = "↑" if chg >= 0 else "↓"

    triggered = None
    if orb_high and orb_low:
        if sc in ("bear", "conditional_bear"):
            triggered = day_close < orb_low
        elif sc in ("bull", "conditional_bull"):
            triggered = day_close > orb_high

    if sc in ("bear", "conditional_bear"):
        ok = chg < 0
    elif sc in ("bull", "conditional_bull"):
        ok = chg > 0
    else:
        ok = None

    icon = "✅" if ok is True else ("❌" if ok is False else "—")
    return icon, arrow, chg, chg_pct, triggered


# ── FULL backtest ─────────────────────────────────────────────────────────────

def run_full(daily_df):
    print("\n" + "═" * 110)
    print("  FULL BACKTEST  —  CPR + Opening position + ORB + Lean Score  (last ~7 days, 1-min data)")
    print("═" * 110)
    print(f"  {'Date':<12} {'Scenario':<20} {'Open pos':<14} {'ORB vs CPR':<14} "
          f"{'Bear/Bull':<11} {'Close Δ':<16} {'Triggered':<12} Result")
    print("─" * 110)

    today = datetime.date.today()
    rows  = daily_df[daily_df.index.date < today]
    # last 8 calendar trading days — 1m data only available ~7 days back
    target_days = sorted({rows.index[-i-1].date() for i in range(min(8, len(rows)-1))})

    for day in target_days:
        prev_rows = daily_df[daily_df.index.date < day]
        if prev_rows.empty:
            continue
        pr    = prev_rows.iloc[-1]
        H, L, C = float(pr["High"]), float(pr["Low"]), float(pr["Close"])
        cpr   = calc_cpr(H, L, C)

        today_rows = daily_df[daily_df.index.date == day]
        if today_rows.empty:
            continue
        day_close = round(float(today_rows.iloc[0]["Close"]), 2)

        intraday     = fetch_intraday(day)
        orb          = get_orb(intraday)
        day_open_px  = get_open_price(intraday, round(float(today_rows.iloc[0]["Open"]), 2))

        od  = open_vs_cpr(day_open_px, cpr)
        pos = {"above_tc": "above TC", "below_bc": "below BC", "inside_cpr": "inside CPR"}[od["position"]]

        if orb:
            vs   = orb_position(orb["high"], orb["low"], cpr)
            l, s = lean_score(od, orb["high"], orb["low"], cpr, C)
            sc   = scenario(od, vs, l)
            score_str = f"B{s['bear']}/U{s['bull']}"
            vs_str    = vs.replace("_", " ")
            icon, arrow, chg, pct, trig = verdict(sc, day_open_px, day_close, orb["high"], orb["low"])
            trig_str  = ("✅ yes" if trig else "❌ no") if trig is not None else "—"
        else:
            vs_str, score_str = "— (no data)", "—"
            sc = "bull" if od["position"] == "above_tc" else ("bear" if od["position"] == "below_bc" else "skip")
            icon, arrow, chg, pct, _ = verdict(sc, day_open_px, day_close)
            trig_str = "(no ORB)"

        print(f"  {str(day):<12} {SC_LABEL.get(sc,'?'):<22} {pos:<16} {vs_str:<16} "
              f"{score_str:<12} {arrow} {chg:>+8.1f} ({pct:>+5.2f}%)   {trig_str:<14} {icon}")

    print("─" * 110)
    print("  Triggered = did day-close cross ORB Low (bear signals) or ORB High (bull signals)")
    print("  ✅ signal direction matched actual close   ❌ did not match   — = SKIP / no verdict")


# ── LITE backtest ─────────────────────────────────────────────────────────────

def run_lite(daily_df, n=40):
    print("\n" + "═" * 110)
    print(f"  LITE BACKTEST  —  CPR + Opening position only  (last {n} days, daily OHLC)")
    print("  NOTE: No ORB available — scenario uses 9:15 open vs CPR only (less precise)")
    print("═" * 110)
    print(f"  {'Date':<12} {'Prev C':>9}  {'BC':>9}  {'TC':>9}  {'W':>6}  "
          f"{'Open':>9}  {'Open pos':<14} {'Scenario':<20} {'Close Δ':<16} Result")
    print("─" * 110)

    today = datetime.date.today()
    rows  = daily_df[daily_df.index.date < today]
    if len(rows) < 2:
        print("  Not enough data.")
        return

    correct = wrong = skip = 0

    for i in range(1, min(n + 1, len(rows))):
        pr   = rows.iloc[-(i+1)]
        cr   = rows.iloc[-i]
        day  = rows.index[-i].date()

        H, L, C = float(pr["High"]), float(pr["Low"]), float(pr["Close"])
        cpr = calc_cpr(H, L, C)

        day_open  = round(float(cr["Open"]),  2)
        day_close = round(float(cr["Close"]), 2)

        od  = open_vs_cpr(day_open, cpr)
        pos = {"above_tc": "above TC", "below_bc": "below BC", "inside_cpr": "inside CPR"}[od["position"]]

        sc = ("bull"  if od["position"] == "above_tc"  else
              "bear"  if od["position"] == "below_bc"  else "skip")

        icon, arrow, chg, pct, _ = verdict(sc, day_open, day_close)

        if icon == "✅": correct += 1
        elif icon == "❌": wrong += 1
        else: skip += 1

        print(f"  {str(day):<12} {C:>9,.2f}  {cpr['bc']:>9,.2f}  {cpr['tc']:>9,.2f}  "
              f"{cpr['width']:>6.1f}  {day_open:>9,.2f}  {pos:<14} {SC_LABEL.get(sc,'?'):<22} "
              f"{arrow} {chg:>+8.1f} ({pct:>+5.2f}%)   {icon}")

    total = correct + wrong
    acc   = round(correct / total * 100, 1) if total else 0
    print("─" * 110)
    print(f"  Signals: {total}  |  ✅ Correct: {correct}  |  ❌ Wrong: {wrong}  "
          f"|  ⬜ Skip: {skip}  |  Accuracy (non-skip): {acc}%")
    print("  (Opening-position-only accuracy — add ORB filter for higher precision)")
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          TradeZen — Trade Flow Backtest  v1.0               ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("  Fetching NIFTY daily data (60d) from yfinance...")
    daily = fetch_daily("60d")
    print(f"  ✅  {len(daily)} trading days loaded\n")

    run_full(daily)
    run_lite(daily, n=40)
