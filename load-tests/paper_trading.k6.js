/**
 * k6 load test — Paper Trading page (tradeze.in)
 *
 * BEFORE RUNNING:
 *   1. Open tradeze.in/paper_trading.html in your browser and sign in
 *   2. Open DevTools → Application → Local Storage → find tz_learn_token
 *   3. Copy that token value
 *
 * INSTALL k6 (one-time):
 *   winget install k6          (Windows Package Manager)
 *   — or —
 *   choco install k6           (Chocolatey)
 *   — or —  download from https://github.com/grafana/k6/releases
 *
 * RUN (smoke — 1 user, verify everything works):
 *   k6 run -e TZ_TOKEN=<your_token> --vus 1 --iterations 1 paper_trading.k6.js
 *
 * RUN (full load test):
 *   k6 run -e TZ_TOKEN=<your_token> paper_trading.k6.js
 *
 * ⚠ WARNING — /api/paper/positions fetches live LTPs from Angel One.
 *   Run this test OUTSIDE market hours (before 9:15am or after 3:30pm IST)
 *   to avoid hammering Angel One's API. During market hours, use the
 *   LIGHT_MODE env flag to skip positions: -e LIGHT_MODE=1
 */

import http   from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend }         from 'k6/metrics';

// ── Config ────────────────────────────────────────────────────────────────────
const BASE    = 'https://tradeze.in';
const TOKEN   = __ENV.TZ_TOKEN;
const LIGHT   = !!__ENV.LIGHT_MODE;   // skip /positions when set

if (!TOKEN) {
  throw new Error(
    'Missing TZ_TOKEN.\n' +
    'Get it: DevTools → Application → Local Storage → tz_learn_token\n' +
    'Pass it: k6 run -e TZ_TOKEN=<value> paper_trading.k6.js'
  );
}

// ── Custom metrics ────────────────────────────────────────────────────────────
const durAccount   = new Trend('dur_account',   true);
const durPositions = new Trend('dur_positions', true);
const durHistory   = new Trend('dur_history',   true);
const errRate      = new Rate('error_rate');

// ── Load profile ──────────────────────────────────────────────────────────────
// Simulates users with the page open (auto-refresh every 10s).
// 15 concurrent users = realistic "small user base all active at once".
export const options = {
  stages: [
    { duration: '30s', target: 5  },   // warm up
    { duration: '60s', target: 15 },   // ramp to peak
    { duration: '90s', target: 15 },   // sustain peak
    { duration: '30s', target: 0  },   // ramp down
  ],
  thresholds: {
    error_rate:       ['rate<0.02'],    // < 2% errors overall
    http_req_failed:  ['rate<0.02'],
    dur_account:      ['p(95)<1500'],   // account: p95 under 1.5s
    dur_history:      ['p(95)<1500'],   // history: p95 under 1.5s
    dur_positions:    ['p(95)<8000'],   // positions: p95 under 8s (calls Angel One)
    http_req_duration:['p(95)<8000'],   // all requests combined
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function authHeaders() {
  return {
    'Authorization': `Bearer ${TOKEN}`,
    'Content-Type':  'application/json',
  };
}

function track(res, metricTrend, checkLabel) {
  metricTrend.add(res.timings.duration);
  const ok = check(res, {
    [`${checkLabel} status 200`]: r => r.status === 200,
    [`${checkLabel} no error`]:   r => {
      try { return !JSON.parse(r.body).error; } catch { return r.status === 200; }
    },
  });
  if (!ok) errRate.add(1);
}

// ── Main VU loop ──────────────────────────────────────────────────────────────
export default function () {
  // The frontend fires all 3 requests in parallel (Promise.all in refreshAll()).
  // k6 runs them sequentially per VU, which is fine — we're measuring server
  // response time, not frontend rendering time.

  group('account', () => {
    const res = http.get(`${BASE}/api/paper/account`, { headers: authHeaders() });
    track(res, durAccount, 'account');
  });

  // Skippable during market hours to avoid Angel One rate limits
  if (!LIGHT) {
    group('positions', () => {
      const res = http.get(`${BASE}/api/paper/positions`, { headers: authHeaders() });
      track(res, durPositions, 'positions');
    });
  }

  group('history', () => {
    const res = http.get(`${BASE}/api/paper/history`, { headers: authHeaders() });
    track(res, durHistory, 'history');
  });

  // Match the page's 10s auto-refresh interval.
  // k6 deducts request time from sleep, so actual cadence stays ~10s.
  sleep(10);
}

// ── Summary hook — print a human-readable verdict ────────────────────────────
export function handleSummary(data) {
  const p95 = ms => {
    const v = data.metrics[ms];
    return v ? (v.values['p(95)'] || 0).toFixed(0) + 'ms' : 'n/a';
  };
  const errors = data.metrics.error_rate
    ? (data.metrics.error_rate.values.rate * 100).toFixed(1) + '%'
    : '0%';

  const lines = [
    '',
    '═══════════════════════════════════════════════',
    '  PAPER TRADING LOAD TEST — SUMMARY',
    '═══════════════════════════════════════════════',
    `  Errors:           ${errors}`,
    `  /account   p95:   ${p95('dur_account')}`,
    `  /positions p95:   ${LIGHT ? 'skipped (LIGHT_MODE)' : p95('dur_positions')}`,
    `  /history   p95:   ${p95('dur_history')}`,
    '───────────────────────────────────────────────',
    `  Thresholds passed: ${data.metrics.http_req_failed?.values.rate < 0.02 ? '✓' : '✗'}`,
    '═══════════════════════════════════════════════',
    '',
  ];
  console.log(lines.join('\n'));

  // Also write standard JSON summary
  return { 'load-tests/results/paper_trading_summary.json': JSON.stringify(data, null, 2) };
}
