"""
Paper trading engine — virtual cash account with simulated stock and option
positions, isolated per user.

Cash model (keeps cash + open exposure always consistent):
  BUY  (long)  : place → cash -= qty*entry ;  close → cash += qty*exit
  SELL (short) : place → cash -= qty*entry (notional blocked as margin)
                 close → cash += qty*entry + (entry-exit)*qty

Schema version history:
  v0 — single shared account (id=1), no user_id
  v1 — per-user accounts keyed by user_id TEXT
"""

import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

DEFAULT_CAPITAL = 1_000_000.0
ANON = "anonymous"


def _now_ist() -> str:
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


# ── Schema migration ──────────────────────────────────────────────────────────

def ensure_tables(conn):
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    if v < 1:
        _migrate_v1(conn)
    else:
        # Idempotent: create tables if somehow missing on a v1+ DB
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS paper_account (
                user_id          TEXT PRIMARY KEY,
                starting_capital REAL NOT NULL,
                cash             REAL NOT NULL,
                created_at       TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL DEFAULT 'anonymous',
                instrument  TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                token       TEXT,
                underlying  TEXT,
                expiry      TEXT,
                strike      REAL,
                option_type TEXT,
                side        TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                lots        INTEGER,
                lot_size    INTEGER,
                entry_price REAL NOT NULL,
                entry_time  TEXT NOT NULL,
                exit_price  REAL,
                exit_time   TEXT,
                status      TEXT NOT NULL DEFAULT 'OPEN',
                pnl         REAL
            );
        """)


def _migrate_v1(conn):
    """Migrate from single-account (id=1) schema to per-user schema."""
    # ── paper_account ──────────────────────────────────────────────
    acct_cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_account)").fetchall()]
    if acct_cols and "id" in acct_cols and "user_id" not in acct_cols:
        # Old schema exists — preserve existing balance as 'anonymous'
        conn.executescript("""
            CREATE TABLE paper_account_v1 (
                user_id          TEXT PRIMARY KEY,
                starting_capital REAL NOT NULL,
                cash             REAL NOT NULL,
                created_at       TEXT NOT NULL
            );
            INSERT INTO paper_account_v1
            SELECT 'anonymous', starting_capital, cash, created_at
            FROM paper_account;
            DROP TABLE paper_account;
            ALTER TABLE paper_account_v1 RENAME TO paper_account;
        """)
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS paper_account (
                user_id          TEXT PRIMARY KEY,
                starting_capital REAL NOT NULL,
                cash             REAL NOT NULL,
                created_at       TEXT NOT NULL
            );
        """)

    # ── paper_trades ───────────────────────────────────────────────
    trade_cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_trades)").fetchall()]
    if trade_cols and "user_id" not in trade_cols:
        conn.execute("ALTER TABLE paper_trades ADD COLUMN user_id TEXT NOT NULL DEFAULT 'anonymous'")
        conn.commit()
    else:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL DEFAULT 'anonymous',
                instrument  TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                token       TEXT,
                underlying  TEXT,
                expiry      TEXT,
                strike      REAL,
                option_type TEXT,
                side        TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                lots        INTEGER,
                lot_size    INTEGER,
                entry_price REAL NOT NULL,
                entry_time  TEXT NOT NULL,
                exit_price  REAL,
                exit_time   TEXT,
                status      TEXT NOT NULL DEFAULT 'OPEN',
                pnl         REAL
            );
        """)

    conn.execute("PRAGMA user_version = 1")
    conn.commit()


# ── Account ───────────────────────────────────────────────────────────────────

def get_account(conn, user_id: str = ANON) -> dict:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT * FROM paper_account WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO paper_account (user_id, starting_capital, cash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, DEFAULT_CAPITAL, DEFAULT_CAPITAL, _now_ist()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM paper_account WHERE user_id = ?", (user_id,)
        ).fetchone()

    realized = conn.execute(
        "SELECT COALESCE(SUM(pnl), 0) AS p, COUNT(*) AS n FROM paper_trades WHERE status = 'CLOSED' AND user_id = ?",
        (user_id,),
    ).fetchone()
    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM paper_trades WHERE status = 'OPEN' AND user_id = ?",
        (user_id,),
    ).fetchone()["n"]

    return {
        "starting_capital": row["starting_capital"],
        "cash":             round(row["cash"], 2),
        "realized_pnl":     round(realized["p"], 2),
        "closed_trades":    realized["n"],
        "open_positions":   open_count,
        "created_at":       row["created_at"],
    }


# ── Orders ────────────────────────────────────────────────────────────────────

def place_order(conn, *, user_id: str = ANON, instrument: str, symbol: str,
                side: str, qty: int, price: float, token=None, underlying=None,
                expiry=None, strike=None, option_type=None, lots=None,
                lot_size=None) -> dict:
    instrument = instrument.upper()
    side       = side.upper()
    if instrument not in ("STOCK", "OPTION"):
        return {"error": "instrument must be STOCK or OPTION"}
    if side not in ("BUY", "SELL"):
        return {"error": "side must be BUY or SELL"}
    if not qty or qty <= 0:
        return {"error": "Quantity must be positive"}
    if not price or price <= 0:
        return {"error": "Price unavailable — try again during market hours or enter a price manually"}

    account = get_account(conn, user_id)
    cost    = round(qty * price, 2)
    if cost > account["cash"]:
        return {"error": f"Insufficient virtual cash: need ₹{cost:,.2f}, have ₹{account['cash']:,.2f}"}

    cur = conn.execute(
        """INSERT INTO paper_trades
           (user_id, instrument, symbol, token, underlying, expiry, strike, option_type,
            side, qty, lots, lot_size, entry_price, entry_time, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
        (user_id, instrument, symbol.upper(), str(token) if token else None,
         underlying.upper() if underlying else None, expiry, strike, option_type,
         side, int(qty), lots, lot_size, round(price, 4), _now_ist()),
    )
    conn.execute(
        "UPDATE paper_account SET cash = cash - ? WHERE user_id = ?", (cost, user_id)
    )
    conn.commit()
    return {"success": True, "trade_id": cur.lastrowid, "symbol": symbol.upper(),
            "side": side, "qty": int(qty), "price": round(price, 4), "cost": cost}


def close_position(conn, trade_id: int, exit_price: float, user_id: str = ANON) -> dict:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT * FROM paper_trades WHERE id = ? AND status = 'OPEN' AND user_id = ?",
        (trade_id, user_id),
    ).fetchone()
    if not row:
        return {"error": "Open position not found"}
    if not exit_price or exit_price <= 0:
        return {"error": "Exit price unavailable — try again during market hours or enter a price manually"}

    qty, entry = row["qty"], row["entry_price"]
    if row["side"] == "BUY":
        pnl     = round((exit_price - entry) * qty, 2)
        release = round(qty * exit_price, 2)
    else:
        pnl     = round((entry - exit_price) * qty, 2)
        release = round(qty * entry + pnl, 2)

    conn.execute(
        "UPDATE paper_trades SET status = 'CLOSED', exit_price = ?, exit_time = ?, pnl = ? WHERE id = ?",
        (round(exit_price, 4), _now_ist(), pnl, trade_id),
    )
    conn.execute(
        "UPDATE paper_account SET cash = cash + ? WHERE user_id = ?", (release, user_id)
    )
    conn.commit()
    return {"success": True, "trade_id": trade_id, "symbol": row["symbol"],
            "exit_price": round(exit_price, 4), "pnl": pnl}


def list_positions(conn, user_id: str = ANON, status: str = "OPEN") -> list[dict]:
    ensure_tables(conn)
    order = "entry_time ASC" if status == "OPEN" else "exit_time DESC"
    rows = conn.execute(
        f"SELECT * FROM paper_trades WHERE status = ? AND user_id = ? ORDER BY {order}",
        (status, user_id),
    ).fetchall()
    return [dict(r) for r in rows]


def unrealized_pnl(position: dict, ltp: float | None) -> dict:
    """Mark an open position to market. Returns {ltp, pnl, pnl_pct} (None when no LTP)."""
    if ltp is None or ltp <= 0:
        return {"ltp": None, "pnl": None, "pnl_pct": None}
    qty, entry = position["qty"], position["entry_price"]
    pnl = (ltp - entry) * qty if position["side"] == "BUY" else (entry - ltp) * qty
    base = entry * qty
    return {"ltp": round(ltp, 4), "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / base * 100, 2) if base else None}


def reset_account(conn, user_id: str = ANON, capital: float = DEFAULT_CAPITAL) -> dict:
    ensure_tables(conn)
    conn.execute("DELETE FROM paper_trades WHERE user_id = ?", (user_id,))
    conn.execute(
        "INSERT OR REPLACE INTO paper_account (user_id, starting_capital, cash, created_at) VALUES (?, ?, ?, ?)",
        (user_id, capital, capital, _now_ist()),
    )
    conn.commit()
    return {"success": True, "starting_capital": capital}
