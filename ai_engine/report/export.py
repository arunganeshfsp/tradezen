"""Trade report exporter — writes trade_report.txt to the ai_engine root."""
import datetime
from pathlib import Path

_OUT = Path(__file__).resolve().parent.parent / "trade_report.txt"


def _yn(v: bool | None) -> str:
    return "YES" if v else "NO"


def export_report(
    bias:  dict,
    setup: dict,
    entry: dict,
    plan:  dict,
    mode:  str = "sim",
) -> str:
    """Write the trade report and return the output file path."""
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    mode_label = "SIMULATION" if mode == "sim" else "LIVE"

    ep = entry.get("entry_price")
    ep_str = f"{ep:,.2f}" if ep else "—"

    lines = [
        "=" * 52,
        "  INTRADAY TRADE REPORT — NIFTY 50",
        f"  Mode : {mode_label}    Generated : {now}",
        "=" * 52,
        "",
        f"  INSTRUMENT : Nifty 50",
        f"  DATE       : {'Tuesday (simulated)' if mode == 'sim' else now[:10]}",
        "  DIRECTION  : LONG",
        "",
        "--- STEP 1: 1H BIAS CHECK ---",
        f"  Bias         : {bias['bias']}",
        f"  EMA stacked  : {_yn(bias['ema_stacked'])}"
        f"   (EMA9={bias['ema9']}  EMA21={bias['ema21']})",
        f"  EMA sloping  : {_yn(bias['ema_sloping'])}",
        f"  MACD > zero  : {_yn(bias['macd_positive'])}"
        f"   (hist={bias['macd_hist']})",
        f"  Above VWAP   : {_yn(bias['above_vwap'])}"
        f"   (close={bias['close']}  VWAP={bias['vwap']})",
        f"  Result       : {'ALL CONDITIONS MET ✓' if bias['all_conditions_met'] else 'CONDITIONS NOT MET ✗'}",
        "",
        "--- STEP 2: 15m SETUP ---",
        f"  Setup valid         : {_yn(setup['setup_valid'])}",
        f"  EMA crossover found : {_yn(setup['ema_crossover_found'])}",
        f"  Crossover above VWAP: {_yn(setup['crossover_above_vwap'])}",
        f"  MACD zero cross     : {_yn(setup['macd_zero_cross'])}",
        f"  Result              : {'SETUP CONFIRMED ✓' if setup['setup_valid'] else 'NO SETUP ✗'}",
        "",
        "--- STEP 3: 5m ENTRY TRIGGER ---",
        f"  Entry triggered     : {_yn(entry['entry_triggered'])}",
        f"  Pullback to EMA9    : {_yn(entry['pullback_to_ema9'])}"
        f"   (EMA9={entry.get('ema9_at_entry', '--')})",
        f"  Held above VWAP     : {_yn(entry['held_above_vwap'])}"
        f"   (VWAP={entry.get('vwap_at_entry', '--')})",
        f"  MACD histogram +ve  : {_yn(entry['macd_histogram_rising'])}",
        f"  Bullish candle      : {_yn(entry['bullish_candle'])}",
        f"  Entry price         : {ep_str}",
        "",
        "--- STEP 4: TRADE PLAN ---",
    ]

    if plan.get("entry", 0) > 0:
        lines += [
            f"  Entry           : {plan['entry']:>10,.2f}",
            f"  Stop loss       : {plan['stop']:>10,.2f}"
            f"  (risk: {plan['risk_pts']:.0f} pts)",
            f"  Target 1        : {plan['target1']:>10,.2f}"
            f"  (reward: {plan['reward_t1']:.0f} pts | RR 1:{plan['rr_t1']})",
            f"  Target 2        : {plan['target2']:>10,.2f}"
            f"  (reward: {plan['reward_t2']:.0f} pts | RR 1:{plan['rr_t2']})",
            f"  Capital         : ₹{plan['capital']:>9,.0f}",
            f"  Max risk (1%)   : ₹{plan['max_loss']:>9,.0f}",
            f"  Suggested qty   :  {plan['suggested_qty']:>9} units",
        ]
    else:
        lines.append("  No trade — entry not triggered.")

    lines += [
        "",
        "--- EXECUTION NOTES ---",
        "  - Enter on next candle open after entry trigger candle closes",
        "  - Book 50% at Target 1, move stop to breakeven",
        "  - Trail remaining with EMA 9 on 5m toward Target 2",
        "  - If price breaks below VWAP before T1, exit immediately",
        "",
        "=" * 52,
        "  Charts saved: charts/1h_chart.png",
        "                charts/15m_chart.png",
        "                charts/5m_chart.png",
        "=" * 52,
    ]

    _OUT.write_text("\n".join(lines), encoding="utf-8")
    return str(_OUT)
