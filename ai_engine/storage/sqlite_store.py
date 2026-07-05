"""
SQLite persistence layer for TradeZen AI engine.
Provides candle cache and market profile cache.
"""

import sqlite3
import os
import json
import logging
from datetime import datetime

log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "tradezen.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS candle_cache (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol_token TEXT NOT NULL,
            exchange     TEXT NOT NULL,
            interval     TEXT NOT NULL,
            datetime     TEXT NOT NULL,
            open         REAL,
            high         REAL,
            low          REAL,
            close        REAL,
            volume       INTEGER,
            fetched_at   TEXT,
            UNIQUE(symbol_token, exchange, interval, datetime)
        );

        CREATE TABLE IF NOT EXISTS daily_reports (
            date         TEXT PRIMARY KEY,
            data         TEXT NOT NULL,
            generated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS market_profile_cache (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol_token TEXT NOT NULL,
            exchange     TEXT NOT NULL,
            date         TEXT NOT NULL,
            tick_size    REAL NOT NULL,
            profile_json TEXT NOT NULL,
            computed_at  TEXT NOT NULL,
            UNIQUE(symbol_token, exchange, date, tick_size)
        );

        CREATE TABLE IF NOT EXISTS orb_candidates (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            date           TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            token          TEXT NOT NULL,
            side           TEXT NOT NULL,
            ltp_0916       REAL,
            buy_pct        REAL,
            sell_pct       REAL,
            strength       REAL,
            bench_high     REAL,
            bench_low      REAL,
            sl_basis       TEXT DEFAULT 'VWAP',
            custom_sl_price REAL,
            status         TEXT DEFAULT 'WAITING',
            remark         TEXT,
            updated_at     TEXT,
            UNIQUE(date, symbol, side)
        );

        CREATE TABLE IF NOT EXISTS orb_stock_trades (
            id              TEXT PRIMARY KEY,
            date            TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            direction       TEXT NOT NULL,
            day_high_at_entry REAL,
            day_low_at_entry  REAL,
            vwap_at_entry   REAL,
            trigger_price   REAL,
            entry_time      TEXT,
            sl_basis        TEXT,
            custom_sl_price REAL,
            stop_loss_price REAL,
            quantity        INTEGER,
            investment      REAL,
            sl_points       REAL,
            target_points   REAL,
            target_price    REAL,
            risk_reward     REAL,
            exit_price      REAL,
            exit_time       TEXT,
            outcome         TEXT DEFAULT 'OPEN',
            pnl             REAL DEFAULT 0,
            return_amount   REAL,
            close_price     REAL,
            remarks         TEXT,
            created_at      TEXT,
            updated_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS orb_settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT
        );
    """)
    conn.commit()


# ── Candle cache helpers ───────────────────────────────────────────────────────

def get_cached_candles(conn, symbol_token, exchange, interval, from_dt, to_dt):
    """Return candles from cache for the given range, sorted ascending."""
    cur = conn.execute(
        """SELECT datetime, open, high, low, close, volume
           FROM candle_cache
           WHERE symbol_token=? AND exchange=? AND interval=?
             AND datetime >= ? AND datetime <= ?
           ORDER BY datetime ASC""",
        (symbol_token, exchange, interval, from_dt, to_dt),
    )
    return cur.fetchall()


def insert_candles(conn, symbol_token, exchange, interval, rows):
    """
    Insert candles into cache.
    rows: list of (datetime_str, open, high, low, close, volume)
    """
    now = datetime.utcnow().isoformat()
    conn.executemany(
        """INSERT OR REPLACE INTO candle_cache
           (symbol_token, exchange, interval, datetime, open, high, low, close, volume, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(symbol_token, exchange, interval, r[0], r[1], r[2], r[3], r[4], r[5], now) for r in rows],
    )
    conn.commit()


# ── Profile cache helpers ──────────────────────────────────────────────────────

def get_cached_profile(conn, symbol_token, exchange, date, tick_size):
    cur = conn.execute(
        """SELECT profile_json FROM market_profile_cache
           WHERE symbol_token=? AND exchange=? AND date=? AND tick_size=?""",
        (symbol_token, exchange, date, tick_size),
    )
    row = cur.fetchone()
    return json.loads(row["profile_json"]) if row else None


def list_reports(conn):
    cur = conn.execute("SELECT date, generated_at, data FROM daily_reports ORDER BY date DESC")
    return [{"date": r["date"], "generated_at": r["generated_at"], **json.loads(r["data"])} for r in cur.fetchall()]


def get_report(conn, date):
    cur = conn.execute("SELECT data, generated_at FROM daily_reports WHERE date=?", (date,))
    row = cur.fetchone()
    if not row: return None
    return {"date": date, "generated_at": row["generated_at"], **json.loads(row["data"])}


def upsert_report(conn, date, data: dict):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    conn.execute(
        "INSERT OR REPLACE INTO daily_reports (date, data, generated_at) VALUES (?, ?, ?)",
        (date, json.dumps(data), now),
    )
    conn.commit()
    return now


def delete_report(conn, date) -> bool:
    cur = conn.execute("DELETE FROM daily_reports WHERE date=?", (date,))
    conn.commit()
    return cur.rowcount > 0


def upsert_profile(conn, symbol_token, exchange, date, tick_size, profile):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO market_profile_cache
           (symbol_token, exchange, date, tick_size, profile_json, computed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (symbol_token, exchange, date, tick_size, json.dumps(profile), now),
    )
    conn.commit()


# ── ORB Simulator helpers ──────────────────────────────────────────────────────

def orb_upsert_candidate(conn, date: str, symbol: str, token: str, side: str, data: dict):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO orb_candidates
               (date, symbol, token, side, ltp_0916, buy_pct, sell_pct, strength,
                bench_high, bench_low, sl_basis, custom_sl_price, status, remark, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date, symbol, side) DO UPDATE SET
               token=excluded.token, ltp_0916=excluded.ltp_0916,
               buy_pct=excluded.buy_pct, sell_pct=excluded.sell_pct,
               strength=excluded.strength, bench_high=excluded.bench_high,
               bench_low=excluded.bench_low, status=excluded.status,
               remark=excluded.remark, updated_at=excluded.updated_at""",
        (date, symbol, token, side,
         data.get("ltp_0916"), data.get("buy_pct"), data.get("sell_pct"), data.get("strength"),
         data.get("bench_high"), data.get("bench_low"),
         data.get("sl_basis", "VWAP"), data.get("custom_sl_price"),
         data.get("status", "WAITING"), data.get("remark"), now),
    )
    conn.commit()


def orb_get_candidates(conn, date: str) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM orb_candidates WHERE date=? ORDER BY side, strength DESC",
        (date,),
    )
    return [dict(r) for r in cur.fetchall()]


def orb_update_candidate_sl(
    conn, date: str, symbol: str, side: str, sl_basis: str, custom_sl_price=None
) -> bool:
    """Returns False if candidate is already TRIGGERED (locked)."""
    cur = conn.execute(
        "SELECT status FROM orb_candidates WHERE date=? AND symbol=? AND side=?",
        (date, symbol, side),
    )
    row = cur.fetchone()
    if not row or row["status"] == "TRIGGERED":
        return False
    conn.execute(
        """UPDATE orb_candidates
           SET sl_basis=?, custom_sl_price=?, updated_at=?
           WHERE date=? AND symbol=? AND side=?""",
        (sl_basis, custom_sl_price, datetime.utcnow().isoformat(), date, symbol, side),
    )
    conn.commit()
    return True


def orb_update_candidate_status(
    conn, date: str, symbol: str, side: str, status: str, remark: str = None
):
    conn.execute(
        """UPDATE orb_candidates
           SET status=?, remark=?, updated_at=?
           WHERE date=? AND symbol=? AND side=?""",
        (status, remark, datetime.utcnow().isoformat(), date, symbol, side),
    )
    conn.commit()


def orb_insert_trade(conn, trade: dict):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO orb_stock_trades
               (id, date, symbol, direction, day_high_at_entry, day_low_at_entry,
                vwap_at_entry, trigger_price, entry_time, sl_basis, custom_sl_price,
                stop_loss_price, quantity, investment, sl_points, target_points,
                target_price, risk_reward, outcome, pnl, return_amount, remarks,
                created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (trade["id"], trade["date"], trade["symbol"], trade["direction"],
         trade.get("day_high_at_entry"), trade.get("day_low_at_entry"),
         trade.get("vwap_at_entry"), trade.get("trigger_price"), trade.get("entry_time"),
         trade.get("sl_basis"), trade.get("custom_sl_price"), trade.get("stop_loss_price"),
         trade.get("quantity"), trade.get("investment"), trade.get("sl_points"),
         trade.get("target_points"), trade.get("target_price"), trade.get("risk_reward"),
         trade.get("outcome", "OPEN"), trade.get("pnl", 0), trade.get("return_amount"),
         trade.get("remarks"), now, now),
    )
    conn.commit()


def orb_get_trades(conn, date: str) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM orb_stock_trades WHERE date=? ORDER BY entry_time",
        (date,),
    )
    return [dict(r) for r in cur.fetchall()]


def orb_get_open_trades(conn, date: str) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM orb_stock_trades WHERE date=? AND outcome='OPEN'",
        (date,),
    )
    return [dict(r) for r in cur.fetchall()]


def orb_update_trade(conn, trade_id: str, updates: dict):
    updates["updated_at"] = datetime.utcnow().isoformat()
    cols  = ", ".join(f"{k}=?" for k in updates)
    vals  = list(updates.values()) + [trade_id]
    conn.execute(f"UPDATE orb_stock_trades SET {cols} WHERE id=?", vals)
    conn.commit()


# ── ORB Settings helpers ───────────────────────────────────────────────────────

ORB_SETTING_DEFAULTS: dict = {
    "target_rupees":   "900",
    "universe":        "nifty500_fno",
    "price_min":       "700",
    "price_max":       "7000",
    "dom_min_pct":     "60",
    "max_slots":       "5",
    "default_sl_basis": "VWAP",
    "candidate_cap":   "25",
}


def orb_get_settings(conn) -> dict:
    cur = conn.execute("SELECT key, value FROM orb_settings")
    stored = {r["key"]: r["value"] for r in cur.fetchall()}
    result = dict(ORB_SETTING_DEFAULTS)
    result.update(stored)
    result["target_rupees"] = float(result["target_rupees"])
    result["price_min"]     = float(result["price_min"])
    result["price_max"]     = float(result["price_max"])
    result["dom_min_pct"]   = float(result["dom_min_pct"])
    result["max_slots"]     = int(result["max_slots"])
    result["candidate_cap"] = int(result["candidate_cap"])
    return result


def orb_upsert_settings(conn, updates: dict):
    now = datetime.utcnow().isoformat()
    conn.executemany(
        "INSERT OR REPLACE INTO orb_settings (key, value, updated_at) VALUES (?,?,?)",
        [(k, str(v), now) for k, v in updates.items()],
    )
    conn.commit()
