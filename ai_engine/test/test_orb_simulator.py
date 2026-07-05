"""
Unit tests for core/orb_simulator.py — run from ai_engine/ directory.
  python -m pytest test/test_orb_simulator.py -v
  python test/test_orb_simulator.py   (direct)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.orb_simulator import (
    resolve_stop_loss, position_size, target_levels,
    sl_points_for, risk_reward, check_outcome, pnl_for,
    in_price_band, passes_volume_filter,
    SIM_TARGET_RUPEES, SIM_TICK,
)


# ── resolve_stop_loss ─────────────────────────────────────────────────────────

def test_sl_vwap_buy_valid():
    price, err = resolve_stop_loss("BUY", "VWAP", 1050, 980, 995, 1040, 985, None, 1051)
    assert err is None and price == 995.0

def test_sl_vwap_sell_valid():
    price, err = resolve_stop_loss("SELL", "VWAP", 1050, 980, 1020, 1040, 985, None, 1018)
    assert err is None and price == 1020.0

def test_sl_day_high_sell():
    # DAY_HIGH as SL for SELL = wide SL above entry → valid but leads to low R:R
    price, err = resolve_stop_loss("SELL", "DAY_HIGH", 1050, 980, 1020, 1045, 985, None, 1030)
    assert err is None and price == 1045.0

def test_sl_day_low_buy():
    price, err = resolve_stop_loss("BUY", "DAY_LOW", 1050, 980, 1010, 1040, 982, None, 1051)
    assert err is None and price == 982.0

def test_sl_custom_valid_buy():
    price, err = resolve_stop_loss("BUY", "CUSTOM", 1050, 980, 1010, 1040, 985, 990, 1055)
    assert err is None and price == 990.0

def test_sl_custom_none_returns_error():
    _, err = resolve_stop_loss("BUY", "CUSTOM", 1050, 980, 1010, 1040, 985, None, 1055)
    assert err is not None and "required" in err

def test_sl_outside_bench_range_high():
    _, err = resolve_stop_loss("BUY", "CUSTOM", 1050, 980, 1010, 1040, 985, 1060, 1070)
    assert err is not None and "outside benchmark range" in err

def test_sl_outside_bench_range_low():
    _, err = resolve_stop_loss("SELL", "CUSTOM", 1050, 980, 1010, 1040, 985, 970, 1030)
    assert err is not None and "outside benchmark range" in err

def test_sl_wrong_side_buy():
    # SL above entry for BUY — invalid
    _, err = resolve_stop_loss("BUY", "CUSTOM", 1050, 980, 1010, 1040, 985, 1045, 1040)
    assert err is not None and "below entry" in err

def test_sl_wrong_side_sell():
    # SL below entry for SELL — invalid
    _, err = resolve_stop_loss("SELL", "CUSTOM", 1050, 980, 1010, 1040, 985, 985, 1000)
    assert err is not None and "above entry" in err

def test_sl_vwap_none_returns_error():
    _, err = resolve_stop_loss("BUY", "VWAP", 1050, 980, None, 1040, 985, None, 1051)
    assert err is not None and "unavailable" in err

def test_sl_unknown_basis():
    _, err = resolve_stop_loss("BUY", "MAGIC", 1050, 980, 995, 1040, 985, None, 1051)
    assert err is not None

def test_sl_at_bench_boundary_low():
    # SL exactly at bench_low — allowed (inclusive) for BUY
    price, err = resolve_stop_loss("BUY", "CUSTOM", 1050, 980, 1010, 1040, 980, 980, 1051)
    assert err is None and price == 980.0

def test_sl_at_bench_boundary_high():
    # SL exactly at bench_high — allowed (inclusive) for SELL
    price, err = resolve_stop_loss("SELL", "CUSTOM", 1050, 980, 1010, 1050, 985, 1050, 1030)
    assert err is None and price == 1050.0


# ── position_size ─────────────────────────────────────────────────────────────

def test_position_size_700():
    # ₹700 lower band — inclusive; floor(100000/700) = 142
    assert position_size(700.0) == 142

def test_position_size_7000():
    # ₹7000 upper band — inclusive; floor(100000/7000) = 14
    assert position_size(7000.0) == 14

def test_position_size_6999():
    # floor(100000/6999) = 14
    assert position_size(6999.0) == 14

def test_position_size_zero_for_very_high_price():
    # entry > capital → qty = 0 (caller must skip)
    assert position_size(150000.0) == 0

def test_position_size_100001():
    assert position_size(100001.0) == 0

def test_position_size_typical():
    # floor(100000/2500) = 40
    assert position_size(2500.0) == 40

def test_position_size_floor_not_round():
    # floor(100000/3333) = 30, not 30 rounded from 30.00...
    assert position_size(3333.0) == 30

def test_position_size_zero_price_guard():
    assert position_size(0.0) == 0


# ── target_levels ─────────────────────────────────────────────────────────────

def test_target_buy_tick_snap():
    # qty=14, target_pts = 900/14 = 64.29 (2dp), entry=7000
    # raw = 7064.29, snap to 0.05: round(7064.29/0.05)*0.05 = round(141285.8)*0.05
    # = 141286 * 0.05 = 7064.30
    pts, price = target_levels("BUY", 7000.0, 14)
    assert pts == 64.29
    assert price == 7064.30

def test_target_sell_tick_snap():
    # qty=14, entry=7000, raw = 7000 - 64.29 = 6935.71
    # snap: round(6935.71/0.05)*0.05 = round(138714.2)*0.05 = 138714*0.05 = 6935.70
    pts, price = target_levels("SELL", 7000.0, 14)
    assert pts == 64.29
    assert price == 6935.70

def test_target_buy_exact():
    # qty=100, target_pts=9.0, entry=500 → price=509.00 (exact)
    pts, price = target_levels("BUY", 500.0, 100)
    assert pts == 9.0
    assert price == 509.0

def test_target_zero_qty_guard():
    pts, price = target_levels("BUY", 1000.0, 0)
    assert pts == 0.0 and price == 0.0

def test_target_tick_rounding_variant():
    # qty=142, entry=700, pts=900/142=6.34 (2dp)
    # BUY raw=706.34, snap to 0.05: round(706.34/0.05)*0.05 = round(14126.8)*0.05
    # = 14127*0.05 = 706.35
    pts, price = target_levels("BUY", 700.0, 142)
    assert pts == 6.34
    assert price == 706.35


# ── sl_points_for ─────────────────────────────────────────────────────────────

def test_sl_points_buy():
    assert sl_points_for("BUY", 1055.0, 995.0) == 60.0

def test_sl_points_sell():
    assert sl_points_for("SELL", 1000.0, 1045.0) == 45.0


# ── risk_reward ───────────────────────────────────────────────────────────────

def test_rr_normal():
    assert risk_reward(64.29, 50.0) == round(64.29 / 50.0, 2)

def test_rr_less_than_one():
    # wide SL scenario — DAY_HIGH basis on SELL
    # entry=1000, SL=1045 (DAY_HIGH), sl_pts=45, target_pts=9 (for qty=100)
    rr = risk_reward(9.0, 45.0)
    assert rr < 1.0
    assert rr == round(9.0 / 45.0, 2)

def test_rr_zero_sl_guard():
    assert risk_reward(50.0, 0.0) == 0.0


# ── check_outcome ─────────────────────────────────────────────────────────────

def test_outcome_buy_target():
    assert check_outcome("BUY", 1065.0, 1060.0, 990.0) == "TARGET_HIT"

def test_outcome_buy_sl():
    assert check_outcome("BUY", 985.0, 1060.0, 990.0) == "SL_HIT"

def test_outcome_buy_open():
    assert check_outcome("BUY", 1020.0, 1060.0, 990.0) is None

def test_outcome_sell_target():
    assert check_outcome("SELL", 935.0, 936.0, 1050.0) == "TARGET_HIT"

def test_outcome_sell_sl():
    assert check_outcome("SELL", 1055.0, 936.0, 1050.0) == "SL_HIT"

def test_outcome_sell_open():
    assert check_outcome("SELL", 990.0, 936.0, 1050.0) is None

def test_sl_precedence_over_target():
    # Pathological: ltp simultaneously satisfies both checks (shouldn't happen in practice)
    # For BUY: sl=1000, target=1000, ltp=1000 → SL checked first
    assert check_outcome("BUY", 1000.0, 1000.0, 1000.0) == "SL_HIT"

def test_outcome_buy_exactly_at_target():
    assert check_outcome("BUY", 1060.0, 1060.0, 990.0) == "TARGET_HIT"

def test_outcome_buy_exactly_at_sl():
    assert check_outcome("BUY", 990.0, 1060.0, 990.0) == "SL_HIT"

def test_outcome_sell_exactly_at_target():
    assert check_outcome("SELL", 936.0, 936.0, 1050.0) == "TARGET_HIT"

def test_outcome_sell_exactly_at_sl():
    assert check_outcome("SELL", 1050.0, 936.0, 1050.0) == "SL_HIT"


# ── pnl_for ───────────────────────────────────────────────────────────────────

def test_pnl_target_hit():
    # qty=100, target_pts=9.0 → pnl = +900
    assert pnl_for("TARGET_HIT", "BUY", 1000, None, 100, 9.0, 5.0) == 900.0

def test_pnl_sl_hit():
    # qty=100, sl_pts=5.0 → pnl = -500
    assert pnl_for("SL_HIT", "BUY", 1000, None, 100, 9.0, 5.0) == -500.0

def test_pnl_square_off_buy():
    # exit above entry
    assert pnl_for("SQUARE_OFF", "BUY", 1000, 1020, 100, 9.0, 5.0) == 2000.0

def test_pnl_square_off_sell():
    # exit below entry
    assert pnl_for("SQUARE_OFF", "SELL", 1000, 975, 100, 9.0, 5.0) == 2500.0

def test_pnl_square_off_loss_buy():
    assert pnl_for("SQUARE_OFF", "BUY", 1000, 990, 100, 9.0, 5.0) == -1000.0

def test_pnl_no_trade():
    assert pnl_for("NO_TRADE", "BUY", 1000, None, 100, 9.0, 5.0) == 0.0

def test_pnl_open():
    assert pnl_for("OPEN", "BUY", 1000, None, 100, 9.0, 5.0) == 0.0


# ── Band / volume filter helpers ──────────────────────────────────────────────

def test_in_price_band_inclusive_700():
    assert in_price_band(700.0)

def test_in_price_band_inclusive_7000():
    assert in_price_band(7000.0)

def test_out_of_band_low():
    assert not in_price_band(699.99)

def test_out_of_band_high():
    assert not in_price_band(7000.01)

def test_volume_filter_buy_passes():
    assert passes_volume_filter("BUY", 65.0, 35.0)

def test_volume_filter_buy_fails():
    assert not passes_volume_filter("BUY", 59.9, 40.1)

def test_volume_filter_buy_exactly_60():
    assert passes_volume_filter("BUY", 60.0, 40.0)

def test_volume_filter_sell_passes():
    assert passes_volume_filter("SELL", 30.0, 70.0)

def test_volume_filter_sell_fails():
    assert not passes_volume_filter("SELL", 50.0, 50.0)


# ── SQLite CRUD round-trip ────────────────────────────────────────────────────

def test_sqlite_candidate_roundtrip():
    import sqlite3, tempfile, os
    # Point the store at a temp DB
    import storage.sqlite_store as store
    orig = store.DB_PATH
    tmp = tempfile.mktemp(suffix=".db")
    store.DB_PATH = tmp
    try:
        conn = store.get_conn()
        store.orb_upsert_candidate(conn, "2026-07-05", "RELIANCE", "500325", "BUY", {
            "ltp_0916": 2800.0, "buy_pct": 65.0, "sell_pct": 35.0, "strength": 30.0,
            "bench_high": 2820.0, "bench_low": 2770.0, "sl_basis": "VWAP",
        })
        rows = store.orb_get_candidates(conn, "2026-07-05")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "RELIANCE"
        assert rows[0]["sl_basis"] == "VWAP"

        # SL basis update
        ok = store.orb_update_candidate_sl(conn, "2026-07-05", "RELIANCE", "BUY", "DAY_LOW")
        assert ok
        rows = store.orb_get_candidates(conn, "2026-07-05")
        assert rows[0]["sl_basis"] == "DAY_LOW"

        # Status update to TRIGGERED should lock SL updates
        store.orb_update_candidate_status(conn, "2026-07-05", "RELIANCE", "BUY", "TRIGGERED")
        ok = store.orb_update_candidate_sl(conn, "2026-07-05", "RELIANCE", "BUY", "VWAP")
        assert not ok

        conn.close()
    finally:
        store.DB_PATH = orig
        if os.path.exists(tmp):
            os.remove(tmp)


def test_sqlite_trade_roundtrip():
    import sqlite3, tempfile, os, uuid
    import storage.sqlite_store as store
    orig = store.DB_PATH
    tmp = tempfile.mktemp(suffix=".db")
    store.DB_PATH = tmp
    try:
        conn = store.get_conn()
        tid = str(uuid.uuid4())
        store.orb_insert_trade(conn, {
            "id": tid, "date": "2026-07-05", "symbol": "TCS", "direction": "BUY",
            "day_high_at_entry": 3600.0, "day_low_at_entry": 3550.0,
            "vwap_at_entry": 3565.0, "trigger_price": 3601.0,
            "entry_time": "09:20:05", "sl_basis": "VWAP", "stop_loss_price": 3565.0,
            "quantity": 27, "investment": 97227.0, "sl_points": 36.0,
            "target_points": 33.33, "target_price": 3634.35, "risk_reward": 0.93,
            "outcome": "OPEN", "pnl": 0, "return_amount": 97227.0,
        })
        trades = store.orb_get_trades(conn, "2026-07-05")
        assert len(trades) == 1
        assert trades[0]["symbol"] == "TCS"
        assert trades[0]["outcome"] == "OPEN"

        open_trades = store.orb_get_open_trades(conn, "2026-07-05")
        assert len(open_trades) == 1

        # Resolve trade
        store.orb_update_trade(conn, tid, {"outcome": "TARGET_HIT", "pnl": 899.91, "exit_price": 3634.35})
        open_trades = store.orb_get_open_trades(conn, "2026-07-05")
        assert len(open_trades) == 0

        conn.close()
    finally:
        store.DB_PATH = orig
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    import traceback
    tests = {k: v for k, v in globals().items() if k.startswith("test_")}
    passed = failed = 0
    for name, fn in tests.items():
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {passed+failed}")
