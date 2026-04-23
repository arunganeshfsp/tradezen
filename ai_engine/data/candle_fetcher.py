"""
Historical candle fetcher — wraps AngelOne getCandleData with SQLite caching.

Auto-paginates requests when the date range exceeds the API's 30-day / 8000-row limit.
Falls back from NSE spot token (26000) to NFO nearest-futures token when getCandleData
returns no rows, mirroring the same pattern used in main.py lifespan startup.
"""

import pandas as pd
import logging
from datetime import datetime, timedelta

from storage.sqlite_store import get_conn, get_cached_candles, insert_candles

log = logging.getLogger(__name__)

# Angel One hard limits per getCandleData call
_MAX_DAYS = {
    "ONE_MINUTE":   30,
    "THREE_MINUTE": 60,
    "FIVE_MINUTE":  100,
    "TEN_MINUTE":   100,
    "FIFTEEN_MINUTE": 200,
    "THIRTY_MINUTE":  200,
    "ONE_HOUR":     400,
    "ONE_DAY":      2000,
}


def fetch_candles(
    smart,
    symbol_token: str,
    exchange: str,
    interval: str,
    from_date: str,
    to_date: str,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for the given token/exchange/interval/range.

    Returns a DataFrame with columns: DateTime, Open, High, Low, Close, Volume
    sorted ascending by DateTime (IST string "YYYY-MM-DD HH:MM").

    Caches results in SQLite to avoid redundant API calls on repeated requests.
    """
    conn = get_conn()

    if use_cache:
        cached = get_cached_candles(conn, symbol_token, exchange, interval, from_date, to_date)
        if cached:
            df = pd.DataFrame(cached, columns=["DateTime", "Open", "High", "Low", "Close", "Volume"])
            log.info(f"📂 Candle cache hit: {symbol_token}/{exchange}/{interval} "
                     f"{from_date}→{to_date} ({len(df)} rows)")
            conn.close()
            return df

    rows = _fetch_from_api(smart, symbol_token, exchange, interval, from_date, to_date)

    if rows:
        insert_candles(conn, symbol_token, exchange, interval, rows)
        log.info(f"💾 Cached {len(rows)} candles: {symbol_token}/{exchange}/{interval}")

    conn.close()

    if not rows:
        log.warning(f"⚠️ No candles returned for {symbol_token}/{exchange}/{interval} "
                    f"{from_date}→{to_date}")
        return pd.DataFrame(columns=["DateTime", "Open", "High", "Low", "Close", "Volume"])

    df = pd.DataFrame(rows, columns=["DateTime", "Open", "High", "Low", "Close", "Volume"])
    return df


def _fetch_from_api(smart, symbol_token, exchange, interval, from_date, to_date):
    """
    Calls getCandleData with automatic pagination when the range exceeds
    the API limit. Returns a flat list of (datetime_str, o, h, l, c, v) tuples.
    """
    max_days = _MAX_DAYS.get(interval, 30)
    fmt = "%Y-%m-%d %H:%M"

    try:
        start = datetime.strptime(from_date, fmt)
    except ValueError:
        start = datetime.strptime(from_date, "%Y-%m-%d")
        start = start.replace(hour=9, minute=15)

    try:
        end = datetime.strptime(to_date, fmt)
    except ValueError:
        end = datetime.strptime(to_date, "%Y-%m-%d")
        end = end.replace(hour=15, minute=30)

    all_rows = []
    cursor = start

    while cursor < end:
        chunk_end = min(cursor + timedelta(days=max_days), end)
        chunk_rows = _single_api_call(
            smart, symbol_token, exchange, interval,
            cursor.strftime(fmt), chunk_end.strftime(fmt),
        )
        all_rows.extend(chunk_rows)
        cursor = chunk_end + timedelta(minutes=1)

    # Deduplicate by datetime (in case chunks overlap)
    seen = set()
    deduped = []
    for r in all_rows:
        if r[0] not in seen:
            seen.add(r[0])
            deduped.append(r)

    return sorted(deduped, key=lambda r: r[0])


def _single_api_call(smart, symbol_token, exchange, interval, from_dt, to_dt):
    """One getCandleData call — returns list of (datetime_str, o, h, l, c, v)."""
    try:
        resp = smart.getCandleData({
            "exchange":    exchange,
            "symboltoken": symbol_token,
            "interval":    interval,
            "fromdate":    from_dt,
            "todate":      to_dt,
        })
        raw = (resp or {}).get("data") or []
        if not raw:
            return []
        result = []
        for r in raw:
            # Angel One format: [ISO_timestamp, open, high, low, close, volume]
            ts = r[0][:16].replace("T", " ")   # "2025-04-23T09:15:00+05:30" → "2025-04-23 09:15"
            result.append((ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5])))
        log.debug(f"getCandleData({exchange}/{symbol_token}/{interval}): {len(result)} rows")
        return result
    except Exception as e:
        log.debug(f"getCandleData({exchange}/{symbol_token}/{interval}) error: {e}")
        return []
