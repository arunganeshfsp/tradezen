# Context: options-analysis

**File:** `public/options_analysis.html`  
**Last updated:** 2026-05-23

---

## Purpose

Live option chain viewer for index options (NIFTY, BANKNIFTY). Shows IV, Greeks, Max Pain, PCR, signal score, recommended strike, risk calculator, and contract history. CE/PE toggle switches the analysis direction.

---

## Layout

```
nav → hero (symbol input + expiry select + CE/PE toggle + Analyze btn)
tabs: Chain | Analytics | Strike | Risk | Monitor | History
  Chain tab    → rendered option chain table (calls + puts side by side)
  Analytics    → IV skew, Max Pain, PCR, OI distribution charts
  Strike       → recommended strike with entry/SL/target
  Risk         → risk/reward calculator for chosen strike
  Monitor      → live trade monitor (if trade active)
  History      → contract history from bhavcopy or NSE fetch
```

---

## Key State

| Variable | Purpose |
|---|---|
| `direction` | `'CE'` or `'PE'` — controls which side is highlighted |
| `chainData` | Last fetched option chain response |
| `analyticsData` | Last fetched analytics response |

---

## Key Functions

| Function | What it does |
|---|---|
| `loadExpiries()` | GET `/api/options/expiries?symbol=` → populates expiry dropdown |
| `runAnalysis()` | Parallel fetch: context + chain, then score + strike + trade-flow; renders all tabs |
| `renderContext(ctx)` | VIX, bias, gap estimate summary bar |
| `renderScore(s)` | Signal score arc (SVG circle) + STRONG/MODERATE/WEAK/SKIP label |
| `renderChain(chain)` | Full option chain table with IV, OI, volume, Greeks per strike |
| `renderAnalytics(analytics, ctx, spot)` | IV skew, Max Pain, PCR panel |
| `renderStrike(strike, analytics)` | Recommended entry strike card |
| `renderRisk(risk)` | Risk/reward breakdown |
| `showTab(id, el)` | Tab switcher |
| `setDir(d)` | Toggle CE/PE — updates `direction` |
| `pingEngine()` | GET `/api/health` — shows green/grey dot |

---

## API Sequence on "Analyze"

```
parallel:
  GET /api/options/context?symbol=
  GET /api/options/chain?symbol=&expiry=
then parallel:
  GET /api/options/score?symbol=&direction=&expiry=
  GET /api/options/select-strike?symbol=&expiry=&direction=&spot_price=
  GET /api/trade-flow
then if strike found:
  GET /api/options/risk?entry_ltp=&lot_size=&direction=
```

---

## Known Caveats

- `_expiriesLoading` flag prevents double-submitting `runAnalysis()` before expiries resolve.
- Score arc SVG uses `r=42` circle → circumference `2π×42 ≈ 263.9`. Hardcoded in `renderScore()`.
- If the engine is offline, `pingEngine()` shows a grey dot — analysis still proceeds but will fail gracefully with error messages per panel.
- Contract history has two paths: auto-fetch from NSE (`fetchContractHistoryNSE`) or manual bhavcopy CSV/ZIP upload (`loadContractHistory`).
