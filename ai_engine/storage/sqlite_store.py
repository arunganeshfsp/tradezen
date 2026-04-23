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


def upsert_profile(conn, symbol_token, exchange, date, tick_size, profile):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO market_profile_cache
           (symbol_token, exchange, date, tick_size, profile_json, computed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (symbol_token, exchange, date, tick_size, json.dumps(profile), now),
    )
    conn.commit()
