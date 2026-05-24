"""
Confidence scoring (0-100) for Cup & Handle pattern quality.

Pillars:
  shape   (40 pts) — depth optimality, roundness, symmetry
  handle  (25 pts) — pullback optimality, near-breakout proximity
  volume  (20 pts) — handle volume dry-up vs cup body
  trend   (10 pts) — prior uptrend before the cup formed
  recovery (5 pts) — how close right rim is to left rim
"""


def score(
    cup: dict,
    handle: dict | None,
    vol_dry_ratio: float,
    prior_trend_pct: float,
) -> dict:
    """
    cup            — result of validate_cup()
    handle         — result of validate_handle(), or None if not yet formed
    vol_dry_ratio  — handle_vol_avg / cup_body_vol_avg  (<1 = dry-up, good)
    prior_trend_pct— % change in 60d before left rim (positive = uptrend)
    """

    # ── Shape (40 pts) ─────────────────────────────────────────────────────
    depth = cup.get("depth_pct", 25.0)
    if 12.0 <= depth <= 30.0:
        depth_s = 1.0
    elif depth < 12.0:
        depth_s = depth / 12.0
    else:
        depth_s = max(0.0, 1.0 - (depth - 30.0) / 10.0)

    roundness_s  = cup.get("roundness", 0.5)
    symmetry_s   = cup.get("symmetry", 0.5)
    shape_pts    = (depth_s * 0.40 + roundness_s * 0.40 + symmetry_s * 0.20) * 40.0

    # ── Handle (25 pts) ────────────────────────────────────────────────────
    if handle and handle.get("valid"):
        pb = handle.get("pullback_pct", 10.0)
        if 5.0 <= pb <= 10.0:
            pb_s = 1.0
        elif pb < 5.0:
            pb_s = pb / 5.0
        else:
            pb_s = max(0.0, 1.0 - (pb - 10.0) / 5.0)
        near_s      = 1.0 if handle.get("near_breakout") else 0.5
        handle_pts  = (pb_s * 0.60 + near_s * 0.40) * 25.0
    elif handle is None:
        # Cup complete, handle not yet started → half credit
        handle_pts = 12.5
    else:
        # Handle invalid (too deep / too long)
        handle_pts = 0.0

    # ── Volume (20 pts) ────────────────────────────────────────────────────
    if vol_dry_ratio <= 1.0:
        vol_pts = max(0.0, (1.0 - vol_dry_ratio)) * 20.0
    else:
        # Volume expanding in handle — moderate penalty
        vol_pts = max(0.0, (2.0 - vol_dry_ratio)) * 8.0

    # ── Prior trend (10 pts) ───────────────────────────────────────────────
    # 30% prior uptrend = full 10 pts
    trend_pts = min(10.0, max(0.0, prior_trend_pct / 3.0))

    # ── Recovery quality (5 pts) ───────────────────────────────────────────
    rec = cup.get("recovery_pct", 80.0)
    if 95.0 <= rec <= 105.0:
        rec_pts = 5.0
    elif rec >= 80.0:
        rec_pts = (rec - 80.0) / 15.0 * 5.0
    else:
        rec_pts = 0.0

    total = round(
        min(100.0, max(0.0, shape_pts + handle_pts + vol_pts + trend_pts + rec_pts)), 1
    )

    return {
        "total":    total,
        "shape":    round(shape_pts, 1),
        "handle":   round(handle_pts, 1),
        "volume":   round(vol_pts, 1),
        "trend":    round(trend_pts, 1),
        "recovery": round(rec_pts, 1),
    }
