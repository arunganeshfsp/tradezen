# Company Money Machine — Module Context

**Built:** 2026-06-12 from `spec-kit/specs/company-money-machine.md`

## What this module is

Animated money-flow teaching tool at `public/company_money_machine.html`. A sandbox company ("Chai Garam Ltd") renders as a three-row flow: Revenue bar → "where it goes" segmented bar (running costs / fixed / interest / tax / profit) → profit-split bar (dividend / retained). Eight knobs drive it; five dials (EPS, PE arc, ROE arc, ROCE arc, interest cover) react live, plus a colour-coded consequence sentence. Serves all 7 Company Analysis lessons. Not on the home page (same decision as compounding-playground — lesson pages will link to it).

## Sandbox model (intentionally simplified — stated in page disclaimer)

- Revenue = units(lakh)×price; EBIT = revenue − variable − fixed; interest = 10% of loan; tax = 25% of max(PBT,0) (no tax on losses); equity = shares × ₹50 fixed book value.
- Defaults: 100L units @ ₹100, cost ₹60/unit, fixed ₹20 Cr, no loan, 1 Cr shares @ ₹300 → net ₹15 Cr, EPS ₹15, PE 20 (Fair), ROE 30%, ROCE 40%. Verified by unit test.
- Loan does NOT add capacity — debt-as-fuel is taught via the consequence line (interest share of EBIT), not the model.
- **PE colour bands must stay in sync with the stock-analyser scorecard** (<15 cheap / 15–25 fair / 25–40 stretched / >40 expensive) — comment in `peBand()` points to `stock-analyser.md`.

## Consequence line priority (renderConsequence)

loss-making (bad) → interest cover < 2 (bad) → debt present but covered (warn, "debt is fuel") → PE > 40 (warn) → healthy margin (ok). Dividend-on-loss is impossible by construction (divPaid = 0 when net ≤ 0; profit row hidden, loss chip shown instead).

## Real-company mode

- `GET /api/stock/analyse/{symbol}` → latest annual with revenue+net_income (sorted by period desc). Costs = revenue − operating_income; "Tax, interest & other" = operating_income − net_income (single lumped drain — interest is not separable from yfinance data). EPS/PE/ROE/price from `fundamentals`; dividend ≈ yield% × market_cap, clamped to net profit.
- ROCE and interest cover grey out in real mode (not derivable). Knobs visually disabled (`opacity .35`, `pointer-events none`); sandbox toggle restores.
- Zero-amount legend entries are hidden in real mode only.
- **Live smoke test pending** — the Node/Python servers were down at build time; mapping coded defensively against the documented response shape. Verify with TITAN/RELIANCE after server start.

## i18n / mobile

Standard `T(en, ta)` + `window.onLangChange → render()`. Flow bars are divs with CSS width transitions (no chart lib); dials are SVG semicircle arcs (`stroke-dasharray 100.5`). Dials grid: 5 → 3 (≤860px) → 2 (≤540px) columns; knobs column drops below the machine on mobile (`order-2 order-lg-1`).

## Open issues

- Real-mode smoke test against live API (servers were down).
- Lesson pages should link here when built ("Try it in the Lab").
