# Module: osprey-ce-pe

**File:** `public/ce_pe_crossover.html`  
**Tutorial:** `public/ce_pe_crossover_tutorial.html`  
**Status:** active

---

## What this module does

The Osprey CE-PE Crossover Calculator is a Nifty/BankNifty option signal tool. It:

1. Locks the 9:15 AM ATM CE and PE premiums as a base reference
2. Calculates % change from open for both legs in real time
3. Fires a **CE Setup Active ▲** or **PE Setup Active ▼** when one side dominates by >15% spread
4. Auto-fetches live premiums from the options chain every 30 seconds
5. Auto-detects and displays VWAP position via `/api/indicators/vwap?symbol=`

---

## Key signal logic

```
spread = CE% − PE%
DOMINANCE = 15

if spread > 15 AND CE% > 0  → CE SETUP ACTIVE ▲
if −spread > 15 AND PE% > 0 → PE SETUP ACTIVE ▼
else                         → NO TRADE
```

The 15% threshold was deliberately chosen (vs. a simpler 10% winner rule) because a 10% CE with −4% PE only gives 14% spread — barely committed. 15% dominance gap filters choppy days.

---

## Key functions (JS, inline in ce_pe_crossover.html)

| Function | Purpose |
|---|---|
| `setIdx(idx)` | Switches between NIFTY/BANKNIFTY; reloads expiries |
| `fetchSpot()` | Calls `/api/options/expiries` + spot endpoint; fills ATM strike |
| `fetchFromChain(autoApply)` | Pulls ATM CE/PE from `/api/options/chain`; `autoApply=true` during auto-refresh |
| `applyToBase()` | Locks chain-fetched premiums as 9:15 base |
| `applyToCurrent()` | Applies chain-fetched premiums as current values + calls `calc()` |
| `calc()` | Core signal calculation; updates `#signalBanner`, `#ceDelta`, `#peDelta`, chart |
| `logSnapshot()` | Appends a row to `dayLog[]` with time, CE%, PE%, signal, VWAP, contract string |
| `fetchVWAP(sym)` | Calls `/api/indicators/vwap?symbol=`; sets toggle + updates `#vwapPill` |
| `toggleAutoRefresh()` | Starts/stops 30s interval + countdown; also manages `visibilitychange` restart |

---

## Auto-refresh background-tab fix

Browser throttles `setInterval` to ~1/min when tab is inactive. The `visibilitychange` listener restarts the interval immediately when the tab regains focus (clears both `autoInterval` and `countdownTick`, then calls `fetchFromChain(true)` immediately).

---

## localStorage keys (date-gated — cleared when date changes)

- `osprey_base` — base premiums + strike + date
- `osprey_current` — last current premiums
- `osprey_log` — day log array

---

## ATM rounding

- NIFTY → nearest 50
- BANKNIFTY → nearest 100
- Applied on `blur` of `#atmStrike` input

---

## VWAP pill

`#vwapPill` — persistent badge next to the toggle showing `VWAP ₹X  ±Y%`. Color-coded: green=above, yellow=at, red=below. Hidden until first VWAP fetch succeeds.

---

## Backend dependency

`/api/indicators/vwap?symbol=NIFTY|BANKNIFTY` — added in `ai_engine/main.py`. Uses `^NSEI`/`^NSEBANK` for price, `NIFTYBEES.NS`/`BANKBEES.NS` as volume proxies (index tickers return 0 intraday volume on yfinance).

---

## Tutorial page

`public/ce_pe_crossover_tutorial.html` — full strategy guide with:
- 7-step setup walkthrough
- Signal cards showing 15% dominance rule
- VWAP confirmation table
- Interactive risk/lot-size calculator (sliders, JS inline)
- 3 Chart.js scenarios (CE win, PE win, choppy/no-trade)
- Morning checklist (tap-to-check)
- Do/don't grid
- Tamil localization via `data-en`/`data-ta`
- SEBI disclaimer
- Linked from main tool hero via "? Strategy Guide" button

---

## Tamil i18n

Both files use `data-en`/`data-ta` pattern handled by `halo-aurora.js`. Key UI elements tagged: hero text, all card titles, field labels, section headers.
