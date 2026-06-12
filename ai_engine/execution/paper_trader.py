"""
Paper trading engine — virtual cash account with simulated stock and option
positions. Pure DB + accounting logic; live price resolution happens in main.py.

Cash model (keeps cash + open exposure always consistent):
  BUY  (long)  : place → cash -= qty*entry ;  close → cash += qty*exit
  SELL (short) : place → cash -= qty*entry (notional blocked as margin)
                 close → cash += qty*entry + (entry-exit)*qty
"""

import logging
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

DEFAULT_CAPITAL = 1_000_000.0


def _now_ist() -> str:
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")


def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS paper_account (
            id               INTEGER PRIMARY KEY CHECK (id = 1),
            starting_capital REAL NOT NULL,
            cash             REAL NOT NULL,
            created_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            instrument  TEXT NOT NULL,                -- STOCK | OPTION
            symbol      TEXT NOT NULL,                -- RELIANCE | NIFTY26JUN2524500CE
            token       TEXT,                         -- NFO token (options only)
            underlying  TEXT,                         -- NIFTY (options only)
            expiry      TEXT,
            strike      REAL,
            option_type TEXT,                         -- CE | PE
            side        TEXT NOT NULL,                -- BUY | SELL
            qty         INTEGER NOT NULL,             -- units (lots × lot_size for options)
            lots        INTEGER,
            lot_size    INTEGER,
            entry_price REAL NOT NULL,
            entry_time  TEXT NOT NULL,
            exit_price  REAL,
            exit_time   TEXT,
            status      TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | CLOSED
            pnl         REAL
        );
    """)
    conn.commit()


def get_account(conn) -> dict:
    ensure_tables(conn)
    row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO paper_account (id, starting_capital, cash, created_at) VALUES (1, ?, ?, ?)",
            (DEFAULT_CAPITAL, DEFAULT_CAPITAL, _now_ist()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM paper_account WHERE id = 1").fetchone()

    realized = conn.execute(
        "SELECT COALESCE(SUM(pnl), 0) AS p, COUNT(*) AS n FROM paper_trades WHERE status = 'CLOSED'"
    ).fetchone()
    open_count = conn.execute(
        "SELECT COUNT(*) AS n FROM paper_trades WHERE status = 'OPEN'"
    ).fetchone()["n"]

    return {
        "starting_capital": row["starting_capital"],
        "cash":             round(row["cash"], 2),
        "realized_pnl":     round(realized["p"], 2),
        "closed_trades":    realized["n"],
        "open_positions":   open_count,
        "created_at":       row["created_at"],
    }


def place_order(conn, *, instrument: str, symbol: str, side: str, qty: int,
                price: float, token=None, underlying=None, expiry=None,
                strike=None, option_type=None, lots=None, lot_size=None) -> dict:
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

    account = get_account(conn)
    cost    = round(qty * price, 2)
    if cost > account["cash"]:
        return {"error": f"Insufficient virtual cash: need ₹{cost:,.2f}, have ₹{account['cash']:,.2f}"}

    cur = conn.execute(
        """INSERT INTO paper_trades
           (instrument, symbol, token, underlying, expiry, strike, option_type,
            side, qty, lots, lot_size, entry_price, entry_time, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
        (instrument, symbol.upper(), str(token) if token else None,
         underlying.upper() if underlying else None, expiry, strike, option_type,
         side, int(qty), lots, lot_size, round(price, 4), _now_ist()),
    )
    conn.execute("UPDATE paper_account SET cash = cash - ? WHERE id = 1", (cost,))
    conn.commit()
    return {"success": True, "trade_id": cur.lastrowid, "symbol": symbol.upper(),
            "side": side, "qty": int(qty), "price": round(price, 4), "cost": cost}


def close_position(conn, trade_id: int, exit_price: float) -> dict:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT * FROM paper_trades WHERE id = ? AND status = 'OPEN'", (trade_id,)
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
    conn.execute("UPDATE paper_account SET cash = cash + ? WHERE id = 1", (release,))
    conn.commit()
    return {"success": True, "trade_id": trade_id, "symbol": row["symbol"],
            "exit_price": round(exit_price, 4), "pnl": pnl}


def list_positions(conn, status: str = "OPEN") -> list[dict]:
    ensure_tables(conn)
    order = "entry_time ASC" if status == "OPEN" else "exit_time DESC"
    rows = conn.execute(
        f"SELECT * FROM paper_trades WHERE status = ? ORDER BY {order}", (status,)
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


def reset_account(conn, capital: float = DEFAULT_CAPITAL) -> dict:
    ensure_tables(conn)
    conn.execute("DELETE FROM paper_trades")
    conn.execute(
        "INSERT OR REPLACE INTO paper_account (id, starting_capital, cash, created_at) VALUES (1, ?, ?, ?)",
        (capital, capital, _now_ist()),
    )
    conn.commit()
    return {"success": True, "starting_capital": capital}
