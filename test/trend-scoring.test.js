// Unit tests for trend-scoring.js — run with: node test/trend-scoring.test.js
// Uses only built-in assert; no external dependencies.

const assert = require('assert');
const path   = require('path');
const { computeTrendScore, DEFAULT_WEIGHTS } = require(
  path.join(__dirname, '..', 'public', 'js', 'trend-scoring.js')
);

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  PASS  ${name}`);
    passed++;
  } catch (e) {
    console.error(`  FAIL  ${name}`);
    console.error(`        ${e.message}`);
    failed++;
  }
}

// ── All-bullish signals ───────────────────────────────────────────────────────
test('all-bullish signals → HIGH conviction', function () {
  const sigs = {
    gap_pts:               60,
    cpr_position:          'above_tc',
    orb_position:          'above',
    breadth_classification: 'strong_bullish',
    fut_oi_signal:         'long_buildup',
    bnf_alignment:         'aligned',
    pcr:                   1.5,
    trend_ind_bulls:       4,
    trend_ind_bears:       0,
  };
  const r = computeTrendScore(sigs);
  assert(r.score > 0, `score should be positive, got ${r.score}`);
  assert(r.conviction === 'HIGH', `expected HIGH, got ${r.conviction}`);
});

// ── All-bearish signals ───────────────────────────────────────────────────────
test('all-bearish signals → HIGH_BEAR conviction', function () {
  const sigs = {
    gap_pts:               -60,
    cpr_position:          'below_bc',
    orb_position:          'below',
    breadth_classification: 'strong_bearish',
    fut_oi_signal:         'short_buildup',
    bnf_alignment:         'diverging',
    pcr:                   0.5,
    trend_ind_bulls:       0,
    trend_ind_bears:       4,
  };
  const r = computeTrendScore(sigs);
  assert(r.score < 0, `score should be negative, got ${r.score}`);
  assert(r.conviction === 'HIGH_BEAR', `expected HIGH_BEAR, got ${r.conviction}`);
});

// ── Mixed / no-trade zone ─────────────────────────────────────────────────────
test('all-neutral signals → NONE conviction', function () {
  const sigs = {
    gap_pts:               0,
    cpr_position:          'inside',
    orb_position:          'inside',
    breadth_classification: 'mixed',
    fut_oi_signal:         null,
    bnf_alignment:         'neutral',
    pcr:                   1.0,
    trend_ind_bulls:       2,
    trend_ind_bears:       2,
  };
  const r = computeTrendScore(sigs);
  assert(r.conviction === 'NONE', `expected NONE, got ${r.conviction} (score ${r.score})`);
});

// ── Missing / null signals contribute 0, not NaN ──────────────────────────────
test('null/missing signals contribute 0, no NaN', function () {
  const sigs = {};
  const r = computeTrendScore(sigs);
  assert(!isNaN(r.score), 'score must not be NaN');
  assert(r.score === 0, `expected 0, got ${r.score}`);
  assert(r.conviction === 'NONE', `expected NONE, got ${r.conviction}`);
  for (const c of r.contributions) {
    assert(!isNaN(c.weighted), `weighted for ${c.name} is NaN`);
    assert(c.weighted === 0, `expected 0 contribution for null signal ${c.name}`);
  }
});

// ── Vol discount halves ORB weight ────────────────────────────────────────────
test('volRatio < 0.8 halves ORB weight and labels it "ORB (vol-discounted)"', function () {
  const sigsNormal = {
    orb_position: 'above',
    vol_ratio: 1.0,
  };
  const sigsWeak = {
    orb_position: 'above',
    vol_ratio: 0.5,
  };
  const normal = computeTrendScore(sigsNormal);
  const weak   = computeTrendScore(sigsWeak);

  const orbNormal = normal.contributions.find(c => c.name === 'ORB');
  const orbWeak   = weak.contributions.find(c => c.name === 'ORB (vol-discounted)');

  assert(orbNormal, 'ORB contribution missing in normal');
  assert(orbWeak,   'ORB (vol-discounted) contribution missing in weak');
  assert.strictEqual(
    orbWeak.weighted,
    orbNormal.weighted / 2,
    `expected ${orbNormal.weighted / 2}, got ${orbWeak.weighted}`
  );
});

// ── Breakdown sorted by abs magnitude ─────────────────────────────────────────
test('contributions sorted by absolute magnitude descending', function () {
  const sigs = {
    gap_pts:               60,
    cpr_position:          'above_tc',
    orb_position:          'above',
    breadth_classification: 'strong_bullish',
    fut_oi_signal:         'long_buildup',
    bnf_alignment:         'aligned',
    pcr:                   1.5,
    trend_ind_bulls:       4,
    trend_ind_bears:       0,
  };
  const r = computeTrendScore(sigs);
  for (let i = 1; i < r.contributions.length; i++) {
    assert(
      Math.abs(r.contributions[i-1].weighted) >= Math.abs(r.contributions[i].weighted),
      `contributions not sorted at index ${i}: ${r.contributions[i-1].name}(${r.contributions[i-1].weighted}) < ${r.contributions[i].name}(${r.contributions[i].weighted})`
    );
  }
});

// ── Custom weights applied ────────────────────────────────────────────────────
test('custom weights override defaults', function () {
  const sigs = { gap_pts: 60 };
  const defaultR = computeTrendScore(sigs);
  const customR  = computeTrendScore(sigs, { gap: 0 });
  const gapDefault = defaultR.contributions.find(c => c.name === 'gap');
  const gapCustom  = customR.contributions.find(c => c.name === 'gap');
  assert(gapDefault.weighted !== 0, 'default gap should contribute');
  assert(gapCustom.weighted  === 0,  'custom gap=0 should give 0 weighted');
});

// ── Moderate positive threshold ───────────────────────────────────────────────
test('score just above moderate threshold → MODERATE', function () {
  // Only gap (weight 1.0, raw 1) + breadth moderate_bullish (weight 2.0, raw 0.5)
  // gap: 1*1 = 1, breadth: 2*0.5 = 1 → total 2.0 — should be <= 2.0 → LOW or NONE
  // To hit MODERATE (≥4): need more signals
  const sigs = {
    gap_pts:               60,      // raw 1, weight 1 → +1
    cpr_position:          'above_tc', // raw 1, weight 2 → +2
    breadth_classification: 'moderate_bullish', // raw 0.5, weight 2 → +1
  };
  const r = computeTrendScore(sigs);
  // score = 1+2+1 = 4, exactly at moderate threshold
  assert(r.score === 4, `expected 4, got ${r.score}`);
  assert(r.conviction === 'MODERATE', `expected MODERATE, got ${r.conviction}`);
});

// ── Score capped at ±12 ───────────────────────────────────────────────────────
test('score is capped at +12 even with max signals', function () {
  const sigs = {
    gap_pts:               200,
    cpr_position:          'above_tc',
    orb_position:          'above',
    breadth_classification: 'strong_bullish',
    fut_oi_signal:         'long_buildup',
    bnf_alignment:         'aligned',
    pcr:                   2.0,
    trend_ind_bulls:       4,
    trend_ind_bears:       0,
    vol_ratio:             2.0,
  };
  const r = computeTrendScore(sigs);
  assert(r.score <= 12, `score ${r.score} exceeds cap of 12`);
});

// ── DEFAULT_WEIGHTS exported ──────────────────────────────────────────────────
test('DEFAULT_WEIGHTS is exported and has expected keys', function () {
  const expected = ['cpr', 'orb', 'breadth', 'fut_oi', 'bnf', 'gap', 'pcr', 'trend_ind'];
  for (const k of expected) {
    assert(DEFAULT_WEIGHTS[k] != null, `missing key ${k} in DEFAULT_WEIGHTS`);
  }
});

// ── gapState: 'holding' adds +0.5 bonus toward gap direction ─────────────────
test('gapState holding adds +0.5 bonus for gap-up', function () {
  const sigsBase    = { gap_pts: 60 };
  const sigsHolding = { gap_pts: 60, gapState: 'holding' };
  const base    = computeTrendScore(sigsBase);
  const holding = computeTrendScore(sigsHolding);
  const gapBase    = base.contributions.find(c => c.name === 'gap');
  const gapHolding = holding.contributions.find(c => c.name === 'gap');
  // Base gap_pts 60 → raw 1, holding → raw min(1, 1+0.5)=1 → same weighted (already at max)
  // Use a mid-range gap to see the bonus
  const sigsM  = { gap_pts: 35 };
  const sigsMH = { gap_pts: 35, gapState: 'holding' };
  const rM  = computeTrendScore(sigsM);
  const rMH = computeTrendScore(sigsMH);
  const gapM  = rM.contributions.find(c => c.name === 'gap');
  const gapMH = rMH.contributions.find(c => c.name === 'gap');
  assert(gapMH.weighted > gapM.weighted,
    `holding gap should produce higher contribution than no-state: ${gapMH.weighted} vs ${gapM.weighted}`);
});

test('gapState filled zeroes the gap contribution regardless of gap_pts', function () {
  const sigs = { gap_pts: 80, gapState: 'filled' };
  const r = computeTrendScore(sigs);
  const gapC = r.contributions.find(c => c.name === 'gap');
  assert.strictEqual(gapC.weighted, 0, `filled gap should contribute 0, got ${gapC.weighted}`);
});

test('gapState null leaves gap contribution unchanged (backward compat)', function () {
  const sigsNoState  = { gap_pts: 30 };
  const sigsNullSt   = { gap_pts: 30, gapState: null };
  const r1 = computeTrendScore(sigsNoState);
  const r2 = computeTrendScore(sigsNullSt);
  const g1 = r1.contributions.find(c => c.name === 'gap').weighted;
  const g2 = r2.contributions.find(c => c.name === 'gap').weighted;
  assert.strictEqual(g1, g2, `null gapState should not change contribution: ${g1} vs ${g2}`);
});

// ── Summary ───────────────────────────────────────────────────────────────────
console.log('');
console.log(`Results: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
