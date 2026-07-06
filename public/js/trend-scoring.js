// Weighted trend scoring engine — pure, no DOM, no fetch.
// Exported for both browser (window.TrendScoring) and Node (module.exports).

(function (root, factory) {
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = factory();
  } else {
    root.TrendScoring = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {

  const DEFAULT_WEIGHTS = {
    cpr:        2.0,
    orb:        2.0,
    breadth:    2.0,
    fut_oi:     1.5,
    bnf:        1.5,
    gap:        1.0,
    pcr:        1.0,
    trend_ind:  1.0,
  };

  const DEFAULT_THRESHOLDS = {
    high:     7.0,
    moderate: 4.0,
    low:      2.0,
    none_lo: -2.0,
    none_hi:  2.0,
  };

  // Raw signal values: each must be in [−1, +1] before weighting.
  // The scoring engine scales them; weights determine max contribution.

  function _safeNum(v) {
    return (v == null || isNaN(v)) ? null : Number(v);
  }

  // Each extractor returns a raw value in [−1, +1] or null (contributes 0).
  const EXTRACTORS = {
    gap: function (sigs) {
      const g = _safeNum(sigs.gap_pts);
      if (g == null) return null;
      // Base gap direction raw value
      var base;
      if (g > 50)  base =  1;
      else if (g > 20)  base =  0.5;
      else if (g < -50) base = -1;
      else if (g < -20) base = -0.5;
      else base = 0;
      // gapState bonus: held gap by 9:45 adds +0.5 in gap direction; filled gap zeroes contribution
      const st = sigs.gapState;
      if (st === 'filled') return 0;
      if (st === 'holding' && base !== 0) {
        base = base > 0 ? Math.min(1, base + 0.5) : Math.max(-1, base - 0.5);
      }
      return base;
    },
    cpr: function (sigs) {
      // +1 = above TC, −1 = below BC, 0 = inside
      const pos = sigs.cpr_position;
      if (pos === 'above_tc') return  1;
      if (pos === 'below_bc') return -1;
      if (pos === 'inside')   return  0;
      return null;
    },
    orb: function (sigs) {
      const pos = sigs.orb_position;
      if (pos === 'above')  return  1;
      if (pos === 'below')  return -1;
      if (pos === 'inside') return  0;
      return null;
    },
    breadth: function (sigs) {
      const cl = sigs.breadth_classification;
      if (!cl) return null;
      if (cl === 'strong_bullish')   return  1;
      if (cl === 'moderate_bullish') return  0.5;
      if (cl === 'strong_bearish')   return -1;
      if (cl === 'moderate_bearish') return -0.5;
      return 0; // mixed
    },
    fut_oi: function (sigs) {
      const sig = sigs.fut_oi_signal;
      if (sig === 'long_buildup')  return  1;
      if (sig === 'short_covering') return  0.5;
      if (sig === 'long_unwinding') return -0.5;
      if (sig === 'short_buildup') return -1;
      return null;
    },
    bnf: function (sigs) {
      const al = sigs.bnf_alignment;
      if (al === 'aligned')   return  1;
      if (al === 'diverging') return -1;
      if (al === 'neutral')   return  0;
      return null;
    },
    pcr: function (sigs) {
      const v = _safeNum(sigs.pcr);
      if (v == null) return null;
      if (v > 1.3) return  1;
      if (v < 0.7) return -1;
      return 0;
    },
    trend_ind: function (sigs) {
      const bulls = _safeNum(sigs.trend_ind_bulls);
      const bears = _safeNum(sigs.trend_ind_bears);
      if (bulls == null || bears == null) return null;
      const net = bulls - bears; // −4..+4 from 4 indicators
      return Math.max(-1, Math.min(1, net / 4));
    },
  };

  function computeTrendScore(signals, weights, thresholds) {
    const W = Object.assign({}, DEFAULT_WEIGHTS, weights || {});
    const T = Object.assign({}, DEFAULT_THRESHOLDS, thresholds || {});

    // Apply volume discount: if volRatio < 0.8, halve the ORB weight
    const volRatio = _safeNum(signals.vol_ratio);
    const orbWeightLabel = (volRatio != null && volRatio < 0.8) ? 'ORB (vol-discounted)' : 'ORB';
    const orbWeight = (volRatio != null && volRatio < 0.8) ? W.orb * 0.5 : W.orb;

    const contributions = [];
    let score = 0;

    const signalKeys = Object.keys(EXTRACTORS);
    for (var i = 0; i < signalKeys.length; i++) {
      const key = signalKeys[i];
      const raw = EXTRACTORS[key](signals);
      const w   = (key === 'orb') ? orbWeight : (W[key] != null ? W[key] : 0);
      const label = (key === 'orb') ? orbWeightLabel : key;
      const weighted = (raw != null) ? raw * w : 0;
      contributions.push({ name: label, raw: raw != null ? raw : null, weighted: weighted });
      score += weighted;
    }

    score = Math.max(-12, Math.min(12, score));

    // Map score to conviction
    let conviction;
    if      (score >= T.high)     conviction = 'HIGH';
    else if (score <= -T.high)    conviction = 'HIGH_BEAR';
    else if (score >= T.moderate) conviction = 'MODERATE';
    else if (score <= -T.moderate) conviction = 'MODERATE_BEAR';
    else if (score >= T.low)      conviction = 'LOW';
    else if (score <= -T.low)     conviction = 'LOW_BEAR';
    else                          conviction = 'NONE';

    contributions.sort(function (a, b) { return Math.abs(b.weighted) - Math.abs(a.weighted); });

    return { score: score, conviction: conviction, contributions: contributions };
  }

  return { computeTrendScore: computeTrendScore, DEFAULT_WEIGHTS: DEFAULT_WEIGHTS };
}));
