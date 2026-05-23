# Context: trade-flow

**File:** `public/trade_flow.html`  
**Last updated:** 2026-05-23

---

## Purpose

Pre-market + intraday bias dashboard. Walks traders through a 6-step framework: GIFT Nifty gap → CPR width → scenario → opening price → ORB → live signal. Steps auto-advance based on market phase.

---

## Layout

6 step cards (accordion-style) + live signal sidebar. Steps revealed progressively.

```
nav → hero → step-nav (1–6 tabs) → detail-panel → signal sidebar
```

---

## Key State

| Variable | Purpose |
|---|---|
| `currentScenario` | `'bull'` \| `'bear'` \| `'conditional_bull'` \| `'conditional_bear'` |
| `currentStep` | Active step (1–6) |
| `flowData` | Latest `/api/trade-flow` response |
| `mpData` | Latest `/api/market-profile/levels` response (prev day levels) |
| `autoScenario` | Scenario computed by server |
| `editingOhlc / editingGift / editingOrb / editingNiftyOpen` | Guards that pause re-renders while user is entering data |
| `giftRefClose` | Reference close for GIFT Nifty gap = GIFT − giftRefClose |
| `lastAutoAdvancePhase` | Prevents re-triggering auto step-advance |

---

## Key Functions

| Function | What it does |
|---|---|
| `showStep(n)` | Reveals step n detail panel, updates step nav status |
| `setScenario(sc, fromAuto)` | Sets scenario + controls conditional bear/bull visibility |
| `renderStep1(d)` | GIFT Nifty gap card — shows gap label + bull/bear/neutral box |
| `renderStep2(d)` | CPR card — width, type (narrow/medium/wide), prev OHLC edit form |
| `autoFetchGiftNifty()` | POST `/api/fetch-gift-nifty` to get live GIFT Nifty price |
| `fmt(n)` | Locale-formatted number (en-IN, 0–2 decimal places) |

---

## API Dependencies

| Endpoint | Used for |
|---|---|
| `GET /api/trade-flow` | Main data: phase, CPR, prev OHLC, GIFT Nifty, ORB, VIX |
| `GET /api/cpr-levels` | CPR + Camarilla level values |
| `GET /api/market-profile/levels` | Prev day POC/VAH/VAL/IB |
| `GET /api/fetch-gift-nifty` | Auto-fetch GIFT Nifty from external source |
| `POST /api/set-gift-nifty` | User override GIFT Nifty price |
| `POST /api/set-prev-ohlc` | User override previous OHLC |
| `POST /api/set-nifty-open` | Set opening price at 9:15 |
| `POST /api/set-orb` | Set ORB high/low after 9:30 |

---

## Market Phase Logic

The server returns `d.phase` which drives auto step-advance:
- `pre_market` → show Step 1 (GIFT Nifty)
- `market_open` → show Step 3 (opening price)
- `orb_window` → show Step 5 (ORB)
- `live` → show Step 6 (signal)

---

## Known Caveats

- The 6 editing flags (`editingOhlc`, etc.) must be checked before re-rendering to avoid clearing in-progress user input on poll cycles.
- `giftRefClose` is null until the page fetches trade-flow data — GIFT gap calculation falls back to `prev.close` if not yet set.
- Steps 1–6 use IDs `s1-status` … `s6-status` and `detail1` … `detail6` — these are hardcoded in `showStep()`.
