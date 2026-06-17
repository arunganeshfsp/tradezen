# Context: options-analysis

**File:** `public/options_analysis.html`  
**Last updated:** 2026-06-17

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
| `renderChain(chain)` | Full option chain table with IV, OI, volume, Greeks per strike. CE LTP and PE LTP cells are clickable — calls `openOptionCPR(strike, type)` |
| `openOptionCPR(strike, type)` | Builds contract symbol (e.g. `NIFTY24000CE`), reads current LTP from `chainData`, opens CPR slide-in drawer, fetches `GET /api/cpr-levels?symbol=` |
| `closeCprDrawer()` | Closes the CPR drawer and overlay |
| `_renderCprDrawer(d, ltp, type)` | Renders CPR level ladder (R2/R1/TC/PP/BC/S1/S2) with prev OHLC stats and LTP zone label inside the drawer |
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

## Option CPR Drawer — Added 2026-06-17

Clicking any CE LTP or PE LTP cell in the chain table opens a slide-in drawer from the right showing CPR levels for that specific option contract.

- Contract symbol is built as `{symbol}{strike}{CE|PE}` (e.g. `NIFTY24000CE`) — symbol from `symbolInput`, strike and type from the clicked row.
- Hits `GET /api/cpr-levels?symbol=NIFTY24000CE` — backend uses `im.get_option_token(strike, type)` with nearest expiry to find the SmartAPI NFO token, then fetches prev-day ONE_DAY premium OHLC.
- Drawer shows: CPR type badge, LTP vs CPR zone, prev-day OHLC grid, full level ladder (R2/R1/TC/PP/BC/S1/S2) with distance from LTP.
- Closes via overlay click or ✕ button.
- Backend caveat: uses **nearest expiry** regardless of which expiry is selected in the chain dropdown — the selected expiry is displayed as info only.

---

## Known Caveats

- `_expiriesLoading` flag prevents double-submitting `runAnalysis()` before expiries resolve.
- Score arc SVG uses `r=42` circle → circumference `2π×42 ≈ 263.9`. Hardcoded in `renderScore()`.
- If the engine is offline, `pingEngine()` shows a grey dot — analysis still proceeds but will fail gracefully with error messages per panel.
- Contract history has two paths: auto-fetch from NSE (`fetchContractHistoryNSE`) or manual bhavcopy CSV/ZIP upload (`loadContractHistory`).
