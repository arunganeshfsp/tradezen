# Load Tests — TradeZen

k6-based load tests for the TradeZen backend. Tests run against the production server at `tradeze.in`.

---

## Setup

### 1. Install k6

```powershell
# Windows Package Manager (built into Windows 10+)
winget install k6

# Chocolatey
choco install k6
```

Or download the `.msi` installer from the [k6 releases page](https://github.com/grafana/k6/releases/latest).

Verify installation:
```powershell
k6 version
```

### 2. Get your JWT token

The paper trading endpoints require authentication.

1. Open `https://tradeze.in/paper_trading.html` in Chrome and sign in
2. Open DevTools (`F12`) → **Application** → **Local Storage** → `https://tradeze.in`
3. Copy the value of `tz_learn_token`

> The token expires with your session. If the smoke test returns `401`, grab a fresh token.

---

## Running the tests

All commands should be run from the `load-tests/` directory.

```powershell
cd C:\Users\lenovo\Documents\tradingapp\tradezen\load-tests
```

### Smoke test (always run this first)

Fires a single request to each endpoint. Confirms auth, connectivity, and that the server is responding before applying load.

```powershell
k6 run -e TZ_TOKEN=<your_token> --vus 1 --iterations 1 paper_trading.k6.js
```

### Full load test

```powershell
k6 run -e TZ_TOKEN=<your_token> paper_trading.k6.js
```

### During market hours (9:15am – 3:30pm IST)

The `/api/paper/positions` endpoint fetches live LTPs from Angel One. Running it under load during market hours may trigger Angel One's rate limits. Use `LIGHT_MODE` to skip it:

```powershell
k6 run -e TZ_TOKEN=<your_token> -e LIGHT_MODE=1 paper_trading.k6.js
```

---

## Test files

| File | What it tests |
|---|---|
| `paper_trading.k6.js` | Paper Trading page — account, positions, history endpoints |

---

## What `paper_trading.k6.js` does

### Endpoints under test

| Endpoint | Auth | Timeout | Notes |
|---|---|---|---|
| `GET /api/paper/account` | JWT | 8s | SQLite read — lightweight |
| `GET /api/paper/positions` | JWT | 20s | Fetches live LTPs from Angel One |
| `GET /api/paper/history` | JWT | 8s | SQLite read — lightweight |

### Load profile

```
VUs
15 ┤              ████████████████
 5 ┤         ████
 0 ┤████                      ████
   └──────────────────────────────▶ time
     0s   30s  90s  180s  210s  240s
```

| Stage | Duration | VUs |
|---|---|---|
| Warm-up | 30s | 0 → 5 |
| Ramp-up | 60s | 5 → 15 |
| Sustain | 90s | 15 |
| Ramp-down | 30s | 15 → 0 |

Total duration: ~3 min 30s.

### What each VU does

Each virtual user simulates the `paper_trading.html` auto-refresh loop:

1. `GET /api/paper/account`
2. `GET /api/paper/positions` *(skipped in LIGHT_MODE)*
3. `GET /api/paper/history`
4. Sleep 10 seconds (matches the page's `setInterval(refreshAll, 10000)`)

### Pass/fail thresholds

| Metric | Threshold |
|---|---|
| Error rate | < 2% |
| `/account` p95 response time | < 1,500ms |
| `/history` p95 response time | < 1,500ms |
| `/positions` p95 response time | < 8,000ms |
| All requests p95 | < 8,000ms |

k6 exits with code `1` (test failed) if any threshold is breached.

---

## Reading the output

k6 prints a live summary during the run and a full table at the end. Key lines to watch:

```
✓ account status 200
✓ positions status 200
✓ history status 200

checks.........................: 100.00% ✓ 450  ✗ 0
http_req_duration..............: avg=312ms  min=88ms   med=280ms  max=1.2s   p(90)=540ms p(95)=720ms
dur_account....................: avg=95ms   p(95)=180ms
dur_positions..................: avg=620ms  p(95)=1.4s
dur_history....................: avg=88ms   p(95)=150ms
error_rate.....................: 0.00%
```

A JSON summary is also written to `load-tests/results/paper_trading_summary.json` after each run.

### Common failure patterns

| Symptom | Likely cause |
|---|---|
| `401` on all requests | Token expired — grab a fresh one from DevTools |
| `/positions` timeouts at high VUs | Angel One rate limit hit — run in LIGHT_MODE or outside market hours |
| High p95 on `/account` + `/history` | SQLite lock contention under concurrent writes — check if paper orders are being placed at the same time |
| Gradual latency increase during sustain | Memory pressure on the DigitalOcean droplet — check server RAM |

---

## Architecture note

```
Browser / k6
    │  Authorization: Bearer <jwt>
    ▼
Node.js (Express) :3000
    │  Verifies JWT → extracts user_id
    │  Adds X-User-Id header
    ▼
Python FastAPI :8000
    │  /paper/account  → SQLite read
    │  /paper/positions → SQLite + Angel One LTP fetch
    │  /paper/history  → SQLite read
```

All test requests go through the full Node → Python stack, so the results reflect end-to-end production latency.
