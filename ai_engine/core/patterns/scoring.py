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

    Returns scores + a human-readable 'reasons' dict for each pillar.
    """

    # ── Shape (40 pts) ─────────────────────────────────────────────────────
    depth = cup.get("depth_pct", 25.0)
    if 12.0 <= depth <= 30.0:
        depth_s = 1.0
    elif depth < 12.0:
        depth_s = depth / 12.0
    else:
        depth_s = max(0.0, 1.0 - (depth - 30.0) / 10.0)

    roundness_s = cup.get("roundness", 0.5)
    symmetry_s  = cup.get("symmetry", 0.5)
    shape_pts   = (depth_s * 0.40 + roundness_s * 0.40 + symmetry_s * 0.20) * 40.0

    if 12.0 <= depth <= 30.0:
        depth_note = f"Depth {depth:.1f}% is in the ideal 12–30% range — full marks."
    elif depth < 12.0:
        depth_note = f"Depth {depth:.1f}% is shallow (ideal ≥ 12%) — partial credit."
    else:
        depth_note = f"Depth {depth:.1f}% is steep (ideal ≤ 30%) — penalty applied."

    roundness_note = (
        f"Roundness {roundness_s*100:.0f}% — {'smooth U-shape' if roundness_s >= 0.7 else 'moderately rounded' if roundness_s >= 0.5 else 'irregular base'} "
        f"(quadratic fit quality)."
    )
    symmetry_note = (
        f"Symmetry {symmetry_s*100:.0f}% — cup bottom is "
        f"{'well-centred' if symmetry_s >= 0.7 else 'slightly off-centre' if symmetry_s >= 0.4 else 'skewed'} "
        f"within the pattern."
    )
    shape_reason = f"{depth_note} {roundness_note} {symmetry_note}"

    # ── Handle (25 pts) ────────────────────────────────────────────────────
    if handle and handle.get("valid"):
        pb = handle.get("pullback_pct", 10.0)
        if 5.0 <= pb <= 10.0:
            pb_s = 1.0
        elif pb < 5.0:
            pb_s = pb / 5.0
        else:
            pb_s = max(0.0, 1.0 - (pb - 10.0) / 5.0)
        near_s     = 1.0 if handle.get("near_breakout") else 0.5
        handle_pts = (pb_s * 0.60 + near_s * 0.40) * 25.0

        if 5.0 <= pb <= 10.0:
            pb_note = f"Pullback {pb:.1f}% is ideal (5–10% range) — full marks."
        elif pb < 5.0:
            pb_note = f"Pullback {pb:.1f}% is too shallow (ideal ≥ 5%) — partial credit."
        else:
            pb_note = f"Pullback {pb:.1f}% is steep (ideal ≤ 10%) — penalty applied."

        near_note = (
            "Price is within 3% of handle high — breakout imminent."
            if handle.get("near_breakout")
            else "Price is not yet near the handle high — waiting for breakout trigger."
        )
        handle_len = handle.get("len_days", 0)
        handle_reason = (
            f"{pb_note} {near_note} "
            f"Handle is {handle_len} trading days long (valid range: 3–35 days)."
        )
    elif handle is None:
        handle_pts = 12.5
        handle_reason = (
            "Cup is fully formed but handle has not yet started. "
            "Half credit awarded — watch for a 3–15% pullback on lower volume to form the handle. "
            "Entry setup becomes clearer once the handle develops."
        )
    else:
        handle_pts = 0.0
        hr = handle.get("reason", "invalid")
        handle_reason = (
            f"Handle did not qualify: {hr}. "
            "A valid handle needs a 3–15% pullback lasting 3–35 trading days. "
            "Wait for the pattern to mature before considering entry."
        )

    # ── Volume (20 pts) ────────────────────────────────────────────────────
    if vol_dry_ratio <= 1.0:
        vol_pts = max(0.0, (1.0 - vol_dry_ratio)) * 20.0
    else:
        vol_pts = max(0.0, (2.0 - vol_dry_ratio)) * 8.0

    dry_pct = round(vol_dry_ratio * 100, 0)
    if vol_dry_ratio < 0.7:
        vol_reason = (
            f"Handle volume is {dry_pct:.0f}% of cup average — strong dry-up confirmed. "
            "Low volume during the handle shows sellers are exhausted, increasing breakout reliability. "
            "Ideal: handle volume < 70% of cup body average."
        )
    elif vol_dry_ratio < 1.0:
        vol_reason = (
            f"Handle volume is {dry_pct:.0f}% of cup average — mild dry-up. "
            "Some reduction in volume is present but not yet a strong signal. "
            "Watch for further volume contraction before the breakout."
        )
    else:
        vol_reason = (
            f"Handle volume is {dry_pct:.0f}% of cup average — volume is not drying up. "
            "Expanding volume during a handle often indicates distribution, reducing pattern reliability. "
            "Observe if volume contracts further as the handle develops."
        )

    # ── Prior trend (10 pts) ───────────────────────────────────────────────
    trend_pts = min(10.0, max(0.0, prior_trend_pct / 3.0))

    if prior_trend_pct >= 20:
        trend_reason = (
            f"Stock rose {prior_trend_pct:.1f}% in the 60 days before the cup formed — strong prior uptrend. "
            "Cup & Handle patterns work best when the stock was already in an uptrend before the consolidation. "
            "This setup has a healthy momentum base."
        )
    elif prior_trend_pct >= 8:
        trend_reason = (
            f"Stock rose {prior_trend_pct:.1f}% before the cup — moderate prior uptrend. "
            "A positive trend existed before consolidation, which is constructive. "
            "Stronger prior trends (> 20%) score higher."
        )
    elif prior_trend_pct >= 0:
        trend_reason = (
            f"Stock was roughly flat ({prior_trend_pct:.1f}%) before the cup formed. "
            "Cup & Handle patterns are more reliable when preceded by a clear uptrend. "
            "This pattern lacks a strong momentum base."
        )
    else:
        trend_reason = (
            f"Stock was down {abs(prior_trend_pct):.1f}% before the cup — no prior uptrend. "
            "Classic Cup & Handle theory requires a prior uptrend. "
            "This reduces the pattern's reliability significantly."
        )

    # ── Recovery quality (5 pts) ───────────────────────────────────────────
    rec = cup.get("recovery_pct", 80.0)
    if 95.0 <= rec <= 105.0:
        rec_pts = 5.0
    elif rec >= 80.0:
        rec_pts = (rec - 80.0) / 15.0 * 5.0
    else:
        rec_pts = 0.0

    if 95.0 <= rec <= 105.0:
        rec_reason = (
            f"Right rim ({rec:.1f}% of left rim) is nearly equal to the left rim — ideal. "
            "A symmetrical cup where both rims are at similar price levels shows balanced buying pressure. "
            "This is the highest-quality cup recovery."
        )
    elif rec >= 80.0:
        rec_reason = (
            f"Right rim is at {rec:.1f}% of the left rim — acceptable recovery. "
            "The stock has recovered most of the cup's decline but has not yet matched the left rim. "
            "Full recovery (95–105%) would score higher."
        )
    else:
        rec_reason = (
            f"Right rim is only at {rec:.1f}% of the left rim — weak recovery. "
            "The stock needs to recover more of the cup's depth before this pattern is valid. "
            "Minimum threshold is 80% recovery."
        )

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
        "reasons": {
            "shape":    shape_reason,
            "handle":   handle_reason,
            "volume":   vol_reason,
            "trend":    trend_reason,
            "recovery": rec_reason,
        },
    }
