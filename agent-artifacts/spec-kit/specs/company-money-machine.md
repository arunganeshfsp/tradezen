# Spec 2 — Company Money Machine

**Status:** built (2026-06-12) — see `agent-artifacts/context/company-money-machine.md`
**Page:** `public/company_money_machine.html`
**Backend:** none for sandbox mode; real mode reuses `GET /api/stock/analyse/:symbol` (already exists — has revenue, net income, EPS, PE, ROE, dividend yield)
**Lessons served:** Revenue Explained · Profit Explained · Debt Explained · EPS Explained · PE Ratio Explained · ROE & ROCE Basics · Dividend Explained

## Concept

An animated money-flow diagram of a single imaginary company — a lemonade-stand-scale "machine". Money pours in at the top (Revenue), drains through cost pipes (Costs, Interest on Debt, Tax), and what's left (Profit) splits into Dividend and Retained. The user turns knobs and watches **both the flow widths and the ratio dials react live**. Seven jargon terms become physical parts of one machine.

## Core interaction loop

1. Sandbox mode opens with a friendly default company (₹100 Cr revenue scale).
2. User drags a knob (e.g., "take a bigger loan") → flow widths animate → EPS/PE/ROE dials swing → a one-line consequence appears ("Interest now eats 18% of profit").
3. "Real company" mode: type an NSE symbol → machine re-renders with actual numbers from the stock-analyser endpoint → user compares the real machine against their sandbox intuition.

## Controls (sandbox)

| Knob | Default | Teaches |
|---|---|---|
| Units sold / price per unit | — | Revenue = volume × price |
| Cost per unit + fixed costs | — | Profit ≠ Revenue |
| Loan amount (interest 10%) | 0 | Debt: fuel vs burden |
| Equity: number of shares | 1 Cr | EPS = profit ÷ shares |
| Market price per share | ₹50 | PE = price ÷ EPS (user sets price, sees PE move — "expensive vs cheap") |
| Dividend payout % | 30% | Dividend vs retained growth |

## Derived dials (live)

- **EPS** = net profit / shares
- **PE** = share price / EPS, with a colour band (cheap < 15 < fair < 25 < stretched < 40 < expensive — same thresholds as stock-analyser scorecard)
- **ROE** = net profit / equity (equity = share capital + retained, simplified)
- **ROCE** = EBIT / (equity + debt) — shown beside ROE with one-liner on the difference
- **Interest coverage** warning when EBIT/interest < 2 ("the machine is working mostly for the lender")

## Visual

Flow diagram drawn with plain divs/SVG (no chart lib needed): vertical waterfall, bar widths proportional to amounts, animated width transitions (CSS). Dials = simple SVG arcs. Mobile: waterfall stacks vertically — design for portrait first.

## Real-company mode

- Input symbol → `GET /api/stock/analyse/{symbol}` → map: revenue & net income (latest annual from `results.annual`), EPS, PE, ROE, dividend yield, D/E.
- Missing fields (common for thin stocks) → that machine part greys out with "data unavailable".
- Keep the knobs locked in real mode (read-only machine) — editing real numbers would invite "what should the price be" speculation. Descriptive only.

## Acceptance

- [ ] Every knob movement animates flows + dials within one frame
- [ ] Consequence one-liners cover: loss-making (costs > revenue), debt-heavy, dividend > profit (blocked, with explanation)
- [ ] Real mode renders TITAN / RELIANCE correctly and degrades gracefully on missing data
- [ ] PE band thresholds match stock-analyser scorecard exactly (single source of truth comment pointing there)
- [ ] Full `data-en/data-ta` + `T()` coverage; disclaimer present
