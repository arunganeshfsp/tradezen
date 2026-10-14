"""
Unit tests for core/indicators/delta_matrix.py — run from ai_engine/ directory.
  python -m pytest test/test_delta_matrix.py -v
  python test/test_delta_matrix.py   (direct)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

from core.indicators.delta_matrix import (
    build_matrix, lookback_days, bars_per_session, VOL_SPIKE_LOOKBACK,
)


def bar(ts, o, c, v, h=None, l=None):
    return (ts, o, h if h is not None else max(o, c), l if l is not None else min(o, c), c, v)


# ── updown classification ─────────────────────────────────────────────────────

def test_up_bar_is_all_buy_down_bar_is_all_sell():
    cols = build_matrix([bar("2026-09-22 09:15", 100, 101, 500),
                         bar("2026-09-22 09:16", 101, 100, 200)], tf=30)
    assert len(cols) == 1
    c = cols[0]
    assert c["buy_vol"] == 500 and c["sell_vol"] == 200 and c["delta"] == 300

def test_doji_uses_prev_close_then_prev_side():
    cols = build_matrix([bar("2026-09-22 09:15", 100, 101, 100),   # up
                         bar("2026-09-22 09:16", 102, 102, 40),    # doji above prev close → buy
                         bar("2026-09-22 09:17", 102, 102, 60)],   # doji at prev close → carries buy
                        tf=30)
    assert cols[0]["buy_vol"] == 200 and cols[0]["sell_vol"] == 0

def test_first_bar_doji_splits_evenly():
    cols = build_matrix([bar("2026-09-22 09:15", 100, 100, 100)], tf=5)
    assert cols[0]["buy_vol"] == 50 and cols[0]["sell_vol"] == 50 and cols[0]["delta"] == 0


# ── column bucketing ──────────────────────────────────────────────────────────

def test_30m_columns_anchor_to_0915():
    cols = build_matrix([bar("2026-09-22 09:15", 1, 2, 10),
                         bar("2026-09-22 09:44", 1, 2, 10),
                         bar("2026-09-22 09:45", 1, 2, 10)], tf=30)
    assert [c["label"] for c in cols] == ["09:15", "09:45"]
    assert cols[0]["volume"] == 20

def test_60m_last_column_is_1515_and_out_of_session_bars_dropped():
    cols = build_matrix([bar("2026-09-22 09:14", 1, 2, 999),
                         bar("2026-09-22 15:14", 1, 2, 10),
                         bar("2026-09-22 15:29", 1, 2, 10),
                         bar("2026-09-22 15:30", 1, 2, 999)], tf=60)
    assert [c["label"] for c in cols] == ["14:15", "15:15"]
    assert sum(c["volume"] for c in cols) == 20

def test_ohlc_aggregates_across_intrabars():
    cols = build_matrix([bar("2026-09-22 09:15", 100, 104, 10, h=105, l=99),
                         bar("2026-09-22 09:16", 104, 102, 10, h=106, l=101)], tf=5)
    c = cols[0]
    assert (c["open"], c["high"], c["low"], c["close"]) == (100, 106, 99, 102)


# ── max / min running delta ───────────────────────────────────────────────────

def test_max_min_track_running_delta_inside_column():
    cols = build_matrix([bar("2026-09-22 09:15", 1, 2, 100),    # +100
                         bar("2026-09-22 09:16", 2, 1, 300),    # -200
                         bar("2026-09-22 09:17", 1, 2, 50)],    # -150
                        tf=15)
    c = cols[0]
    assert c["delta"] == -150 and c["max_delta"] == 100 and c["min_delta"] == -200

def test_one_sided_column_min_is_positive():
    cols = build_matrix([bar("2026-09-22 09:15", 1, 2, 100),
                         bar("2026-09-22 09:16", 2, 3, 100)], tf=5)
    assert cols[0]["min_delta"] == 100 and cols[0]["max_delta"] == 200


# ── cumulative + session delta ────────────────────────────────────────────────

def test_session_delta_resets_on_new_date_cum_does_not():
    cols = build_matrix([bar("2026-09-21 15:15", 1, 2, 100),
                         bar("2026-09-22 09:15", 2, 1, 30),
                         bar("2026-09-22 09:45", 1, 2, 10)], tf=30)
    assert [c["session_delta"] for c in cols] == [100, -30, -20]
    assert [c["cum_delta"] for c in cols] == [100, 70, 80]
    assert [c["session_start"] for c in cols] == [True, True, False]

def test_delta_pct_is_absolute_share_of_volume():
    cols = build_matrix([bar("2026-09-22 09:15", 2, 1, 80),
                         bar("2026-09-22 09:16", 1, 2, 20)], tf=5)
    assert cols[0]["delta"] == -60 and cols[0]["delta_pct"] == 60.0


# ── volume spike ──────────────────────────────────────────────────────────────

def test_vol_spike_against_prior_average():
    rows = [bar(f"2026-09-22 {9 + (15 + 5 * i) // 60:02d}:{(15 + 5 * i) % 60:02d}", 1, 2, 100)
            for i in range(4)]
    rows.append(bar("2026-09-22 09:35", 1, 2, 160))
    cols = build_matrix(rows, tf=5)
    assert cols[0]["vol_ratio"] is None and cols[0]["vol_spike"] is False
    assert cols[3]["vol_spike"] is False
    assert cols[4]["vol_ratio"] == 1.6 and cols[4]["vol_spike"] is True

def test_vol_spike_lookback_is_bounded():
    rows = [bar("2026-09-22 09:15", 1, 2, 10_000)]
    rows += [bar(f"2026-09-22 {9 + (20 + 5 * i) // 60:02d}:{(20 + 5 * i) % 60:02d}", 1, 2, 100)
             for i in range(VOL_SPIKE_LOOKBACK)]
    rows.append(bar("2026-09-22 11:05", 1, 2, 150))
    cols = build_matrix(rows, tf=5)
    assert cols[-1]["vol_ratio"] == 1.5


# ── live column ───────────────────────────────────────────────────────────────

def test_live_flag_only_on_forming_column():
    rows = [bar("2026-09-22 09:15", 1, 2, 10), bar("2026-09-22 09:45", 1, 2, 10)]
    cols = build_matrix(rows, tf=30, now=datetime(2026, 9, 22, 9, 52))
    assert [c["live"] for c in cols] == [False, True]
    cols = build_matrix(rows, tf=30, now=datetime(2026, 9, 22, 16, 0))
    assert not any(c["live"] for c in cols)


# ── clv method ────────────────────────────────────────────────────────────────

def test_clv_splits_by_close_location():
    cols = build_matrix([("2026-09-22 09:15", 100, 110, 100, 107.5, 400)], tf=5, method="clv")
    assert cols[0]["buy_vol"] == 300 and cols[0]["sell_vol"] == 100 and cols[0]["delta"] == 200


# ── helpers + validation ──────────────────────────────────────────────────────

def test_lookback_days_covers_requested_columns():
    assert bars_per_session(30) == 13 and bars_per_session(60) == 7
    assert lookback_days(5, 16) == 6
    assert lookback_days(60, 60) == 18
    for tf in (5, 15, 30, 60):
        for cols in (4, 16, 60):
            sessions_needed = -(-cols // bars_per_session(tf))
            assert lookback_days(tf, cols) * 5 // 7 >= sessions_needed

def test_rejects_unknown_tf_and_method():
    for kwargs in ({"tf": 7}, {"tf": 5, "method": "tick"}):
        try:
            build_matrix([], **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")

def test_empty_input():
    assert build_matrix([], tf=30) == []


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
