"""
TradeZen — EMA + MACD + VWAP Intraday Scenario Runner

Usage:
  python run_scenario.py              # simulation mode  (synthetic NIFTY data)
  python run_scenario.py --mode live  # live mode        (yfinance ^NSEI real data)

Steps:
  1. 1H  bias check  — EMA 9/21 stack + MACD + VWAP
  2. 15m setup       — EMA crossover + VWAP confirmation + MACD zero cross
  3. 5m  entry       — pullback to EMA9 + VWAP hold + bullish candle
  4. Trade plan      — risk/reward + position sizing
  5. PNG charts      — saved to charts/
  6. trade_report.txt
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.analysis.bias       import check_1h_bias
from core.analysis.setup      import check_15m_setup
from core.analysis.entry      import check_5m_entry
from core.analysis.trade_plan import calculate_trade_plan
from charts.plot              import save_charts
from report.export            import export_report


# ── Display helpers ───────────────────────────────────────────────────────────

def _yn(v: bool | None) -> str:
    return "✅  YES" if v else "❌  NO "


def _section(title: str) -> None:
    print()
    print("─" * 58)
    print(f"  {title}")
    print("─" * 58)


# ── Simulation data ───────────────────────────────────────────────────────────

def _load_sim():
    from data.generate import generate_all, SCENARIO
    data = generate_all()
    return data["1h"], data["15m"], data["5m"], SCENARIO


# ── Live data via yfinance ────────────────────────────────────────────────────

def _load_live():
    import yfinance as yf
    import pandas as pd

    print("  📡  Fetching live NIFTY data from yfinance (^NSEI)...")

    def _fetch(period: str, interval: str):
        df = yf.Ticker("^NSEI").history(period=period, interval=interval)
        if df.empty:
            return df
        df.index = df.index.tz_convert("Asia/Kolkata")
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    def _mkt_hours(df):
        """Keep only 9:15–15:30 IST candles."""
        return df.between_time("09:15", "15:30") if not df.empty else df

    # 1H bias: last 5 days of 1H data (well enough for EMA21 to stabilise)
    df_1h_raw = _fetch("5d", "60m")
    df_1h     = _mkt_hours(df_1h_raw).tail(30)   # ~5 sessions × 6 bars

    # 15m setup: last 2 days so EMA/MACD have enough history, crossover is recent
    df_15m_raw = _fetch("5d", "15m")
    df_15m     = _mkt_hours(df_15m_raw).tail(52)  # ~2 sessions × 26 bars

    # 5m entry: today's session only — VWAP must start at 9:15 today
    df_5m_raw = _fetch("1d", "5m")
    df_5m     = _mkt_hours(df_5m_raw)

    for name, df in [("1H", df_1h), ("15m", df_15m), ("5m", df_5m)]:
        if df.empty:
            print(f"  ⚠️  {name}: no data (pre-market or market closed)")
        else:
            print(f"  ✅  {name}: {len(df)} candles  "
                  f"({df.index[0].strftime('%H:%M')} → {df.index[-1].strftime('%H:%M')})")

    return df_1h, df_15m, df_5m, None   # scenario=None; trade plan derived from entry


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="TradeZen EMA+MACD+VWAP Scenario")
    parser.add_argument(
        "--mode", choices=["sim", "live"], default="sim",
        help="sim = synthetic data (default)  |  live = yfinance real NIFTY data",
    )
    args = parser.parse_args()
    mode = args.mode

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║      TradeZen — EMA + MACD + VWAP  Scenario  v1.0      ║")
    if mode == "sim":
        print("║      Mode : SIMULATION  (synthetic Nifty 50 data)      ║")
    else:
        print("║      Mode : LIVE        (yfinance ^NSEI real data)      ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # ── Load data ─────────────────────────────────────────────────────────────
    if mode == "sim":
        df_1h, df_15m, df_5m, scenario = _load_sim()
    else:
        df_1h, df_15m, df_5m, scenario = _load_live()

    if df_1h.empty or df_15m.empty or df_5m.empty:
        print("\n  ⚠️  One or more DataFrames are empty. Cannot proceed.")
        sys.exit(1)

    # ── Step 1: 1H bias ───────────────────────────────────────────────────────
    print()
    print("[Step 1] Checking 1H bias...")
    bias = check_1h_bias(df_1h)

    _section("STEP 1 — 1H BIAS CHECK")
    print(f"  Bias          : {bias['bias']}")
    print(f"  EMA9 > EMA21  : {_yn(bias['ema_stacked'])}"
          f"   ({bias['ema9']:,.2f} vs {bias['ema21']:,.2f})")
    print(f"  EMAs sloping  : {_yn(bias['ema_sloping'])}")
    print(f"  MACD hist +ve : {_yn(bias['macd_positive'])}"
          f"   (hist = {bias['macd_hist']})")
    print(f"  Close > VWAP  : {_yn(bias['above_vwap'])}"
          f"   (close={bias['close']:,.2f}  VWAP={bias['vwap']:,.2f})")
    if bias["all_conditions_met"]:
        print("  → Result      : ALL CONDITIONS MET ✓  —  bullish bias confirmed")
    else:
        print("  → Result      : CONDITIONS NOT MET — no trade, bias unclear")

    # ── Step 2: 15m setup ─────────────────────────────────────────────────────
    print()
    print("[Step 2] Detecting 15m setup...")
    setup = check_15m_setup(df_15m)

    _section("STEP 2 — 15m SETUP")
    xo_note = f"   (candle {setup['crossover_candle_idx']})" if setup["crossover_candle_idx"] is not None else ""
    print(f"  EMA crossover    : {_yn(setup['ema_crossover_found'])}{xo_note}")
    print(f"  Crossover > VWAP : {_yn(setup['crossover_above_vwap'])}")
    print(f"  MACD zero cross  : {_yn(setup['macd_zero_cross'])}")
    if setup["setup_valid"]:
        print("  → Result         : SETUP CONFIRMED ✓")
    else:
        print("  → Result         : NO VALID SETUP — wait for crossover")

    # ── Step 3: 5m entry ──────────────────────────────────────────────────────
    print()
    print("[Step 3] Looking for 5m entry trigger...")
    entry = check_5m_entry(df_5m)

    _section("STEP 3 — 5m ENTRY TRIGGER")
    print(f"  Pullback to EMA9    : {_yn(entry['pullback_to_ema9'])}"
          f"   (EMA9 = {entry.get('ema9_at_entry', '--'):,.2f})")
    print(f"  Held above VWAP     : {_yn(entry['held_above_vwap'])}"
          f"   (VWAP = {entry.get('vwap_at_entry') or '--'})")
    print(f"  MACD hist ↑ positive: {_yn(entry['macd_histogram_rising'])}")
    print(f"  Bullish candle      : {_yn(entry['bullish_candle'])}")
    ep_str = f" @ {entry['entry_price']:,.2f}" if entry["entry_price"] else ""
    print(f"  → Entry triggered   : {_yn(entry['entry_triggered'])}{ep_str}")

    # ── Step 4: Trade plan ────────────────────────────────────────────────────
    print()
    print("[Step 4] Calculating trade plan...")

    if mode == "sim" and scenario:
        # Simulation: use the textbook scenario levels
        plan = calculate_trade_plan(
            scenario["entry"], scenario["stop"],
            scenario["target1"], scenario["target2"],
        )
    elif entry["entry_triggered"] and entry["entry_price"]:
        # Live: derive levels from EMA9 distance
        ep   = entry["entry_price"]
        e9   = entry.get("ema9_at_entry") or (ep - 70)
        stop = round(e9 - 20, 2)          # 20-pt buffer below EMA9
        risk = round(ep - stop, 2)
        t1   = round(ep + 2.0 * risk, 2)
        t2   = round(ep + 3.7 * risk, 2)
        plan = calculate_trade_plan(ep, stop, t1, t2)
    else:
        plan = calculate_trade_plan(0.0, 0.0, 0.0, 0.0)

    _section("STEP 4 — TRADE PLAN")
    if plan["entry"] > 0:
        print(f"  Entry       : ₹{plan['entry']:>10,.2f}")
        print(f"  Stop loss   : ₹{plan['stop']:>10,.2f}   (risk  : {plan['risk_pts']:.0f} pts)")
        print(f"  Target 1    : ₹{plan['target1']:>10,.2f}   (reward: {plan['reward_t1']:.0f} pts | RR 1:{plan['rr_t1']})")
        print(f"  Target 2    : ₹{plan['target2']:>10,.2f}   (reward: {plan['reward_t2']:.0f} pts | RR 1:{plan['rr_t2']})")
        print(f"  Capital     : ₹{plan['capital']:>10,.0f}")
        print(f"  Max risk 1% : ₹{plan['max_loss']:>10,.0f}")
        print(f"  Qty         :  {plan['suggested_qty']:>10} units")
    else:
        print("  No trade plan — entry not triggered.")

    # ── Charts ────────────────────────────────────────────────────────────────
    print()
    print("[Charts] Saving charts...")
    try:
        save_charts(
            df_1h, df_15m, df_5m,
            indicators_1h  = {"bias":  bias},
            indicators_15m = {"setup": setup},
            indicators_5m  = {"entry": entry, "plan": plan},
        )
        print("  ✅  Saved → charts/1h_chart.png  15m_chart.png  5m_chart.png")
    except ImportError:
        print("  ⚠️  matplotlib not installed.  Run:  pip install matplotlib")
    except Exception as e:
        print(f"  ⚠️  Chart generation failed: {e}")

    # ── Report ────────────────────────────────────────────────────────────────
    print()
    print("[Report] Exporting trade_report.txt...")
    try:
        path = export_report(bias, setup, entry, plan, mode)
        print(f"  ✅  Saved → {path}")
    except Exception as e:
        print(f"  ⚠️  Report export failed: {e}")

    # ── Final summary ─────────────────────────────────────────────────────────
    _section("SUMMARY")
    checks = [
        ("1H Bias",   bias["all_conditions_met"]),
        ("15m Setup", setup["setup_valid"]),
        ("5m Entry",  entry["entry_triggered"]),
    ]
    for label, ok in checks:
        print(f"  {'✅' if ok else '❌'}  {label}")

    all_ok = all(ok for _, ok in checks)
    print()
    if all_ok:
        print("  🟢  ALL SIGNALS CONFIRMED — trade setup is valid")
        if plan["entry"] > 0:
            print(f"      Entry ₹{plan['entry']:,.0f}  |  "
                  f"Stop ₹{plan['stop']:,.0f}  |  "
                  f"T1 ₹{plan['target1']:,.0f}  |  "
                  f"T2 ₹{plan['target2']:,.0f}")
    else:
        missing = [l for l, ok in checks if not ok]
        print(f"  🔴  INCOMPLETE — waiting on: {', '.join(missing)}")
    print()


if __name__ == "__main__":
    main()
