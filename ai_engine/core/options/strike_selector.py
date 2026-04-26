"""
Strike selector (Module 7).
Filters option chain rows to find the best CE/PE strike for a given direction.
Pure function — no I/O.
"""

import logging

log = logging.getLogger(__name__)

# Delta sweet-spot for directional option buys
_DELTA_MIN = 0.40
_DELTA_MAX = 0.65

# Maximum acceptable bid-ask spread as a % of the mid-price
_MAX_SPREAD_PCT = 0.05   # 5 %

# IV percentile cap — skip if IV is in the top 30 % of the chain
_IV_PERCENTILE_CAP = 0.70


def select_strike(
    chain: list[dict],
    direction: str,           # "CE" | "PE"
    spot_price: float,
    max_pain: float | None = None,
) -> dict:
    """
    Pick the best strike from a full chain for `direction`.

    Returns:
    {
        strike, token, symbol, ltp, iv, delta,
        lot_size, bid, ask, spread_pct,
        reason,      ← human-readable selection rationale
        candidates,  ← list of all filtered candidates (for UI)
    }
    or {"error": "reason"} if nothing qualifies.
    """
    direction = direction.upper()
    leg_key   = "ce" if direction == "CE" else "pe"

    if not chain:
        return {"error": "Empty chain"}

    # ── Step 1: filter strikes with usable data ───────────────────────────────
    usable = [
        s for s in chain
        if s.get(leg_key, {}).get("ltp") is not None
        and (s.get(leg_key, {}).get("ltp") or 0) > 0
    ]
    if not usable:
        return {"error": "No strikes with valid LTP data"}

    # ── Step 2: delta filter (if data available) ──────────────────────────────
    delta_filtered = [
        s for s in usable
        if _delta_in_range(s[leg_key].get("delta"), direction)
    ]
    # Fall back to ATM±3 range if delta not available
    if not delta_filtered:
        delta_filtered = _atm_range(usable, spot_price, leg_key, n=5)

    if not delta_filtered:
        return {"error": "No strikes within delta range"}

    # ── Step 3: bid-ask spread filter ────────────────────────────────────────
    liquid = [s for s in delta_filtered if _spread_ok(s[leg_key])]
    if not liquid:
        liquid = delta_filtered          # relax spread filter if all fail

    # ── Step 4: IV percentile filter (avoid IV crush risk) ───────────────────
    iv_values = [s[leg_key].get("iv") for s in usable if s[leg_key].get("iv")]
    if iv_values:
        iv_cap = sorted(iv_values)[int(len(iv_values) * _IV_PERCENTILE_CAP)]
        low_iv = [s for s in liquid if (s[leg_key].get("iv") or 0) <= iv_cap]
        if low_iv:
            liquid = low_iv

    # ── Step 5: rank by proximity to ATM (lower extrinsic decay) then by OI ──
    def _rank(s: dict) -> tuple:
        strike    = s["strike"]
        dist_atm  = abs(strike - spot_price)
        oi        = s[leg_key].get("oi") or 0
        return (dist_atm, -oi)

    liquid.sort(key=_rank)
    best  = liquid[0]
    leg   = best[leg_key]
    bid   = leg.get("bid") or 0
    ask   = leg.get("ask") or (leg.get("ltp") or 0)
    mid   = (bid + ask) / 2 if (bid + ask) > 0 else (leg.get("ltp") or 0)
    spread_pct = (ask - bid) / mid if mid > 0 else 0

    reason = _build_reason(best["strike"], spot_price, leg, direction, max_pain)

    candidates = [
        {
            "strike":     s["strike"],
            "ltp":        s[leg_key].get("ltp"),
            "iv":         s[leg_key].get("iv"),
            "delta":      s[leg_key].get("delta"),
            "oi":         s[leg_key].get("oi"),
        }
        for s in liquid[:10]
    ]

    return {
        "strike":     best["strike"],
        "token":      leg.get("token"),
        "symbol":     leg.get("symbol"),
        "ltp":        leg.get("ltp"),
        "iv":         leg.get("iv"),
        "delta":      leg.get("delta"),
        "oi":         leg.get("oi"),
        "lot_size":   leg.get("lot_size"),
        "bid":        bid,
        "ask":        ask,
        "spread_pct": round(spread_pct, 4),
        "reason":     reason,
        "candidates": candidates,
    }


def _delta_in_range(delta: float | None, direction: str) -> bool:
    if delta is None:
        return False
    d = abs(delta)
    return _DELTA_MIN <= d <= _DELTA_MAX


def _spread_ok(leg: dict) -> bool:
    bid = leg.get("bid") or 0
    ask = leg.get("ask") or 0
    if ask <= 0:
        return True    # no ask data — don't exclude
    mid = (bid + ask) / 2
    if mid <= 0:
        return True
    return (ask - bid) / mid <= _MAX_SPREAD_PCT


def _atm_range(chain: list[dict], spot: float, leg_key: str, n: int = 5) -> list[dict]:
    """Return n strikes closest to spot."""
    ranked = sorted(chain, key=lambda s: abs(s["strike"] - spot))
    return ranked[:n]


def _build_reason(strike: float, spot: float, leg: dict, direction: str,
                  max_pain: float | None) -> str:
    parts = []
    dist  = round(strike - spot, 1)
    if abs(dist) < 50:
        parts.append("ATM")
    elif (direction == "CE" and dist > 0) or (direction == "PE" and dist < 0):
        parts.append(f"OTM {abs(dist):.0f} pts")
    else:
        parts.append(f"ITM {abs(dist):.0f} pts")

    if leg.get("delta"):
        parts.append(f"δ={leg['delta']:.2f}")
    if leg.get("iv"):
        parts.append(f"IV={leg['iv']:.1f}%")
    if max_pain:
        mp_dist = round(strike - max_pain, 1)
        parts.append(f"MP offset {mp_dist:+.0f}")
    return " | ".join(parts)
