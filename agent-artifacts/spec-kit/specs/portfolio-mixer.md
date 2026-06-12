# Spec 3 — Portfolio Mixer

**Status:** proposed
**Page:** `public/portfolio_mixer.html`
**Backend:** reuses `GET /api/stock/timelapse/{symbol}?start=` (already returns aligned monthly series for stock + ^NSEI + GOLDBEES). Optionally extend with `&extra=` for a second stock — decide at build time; v1 can ship with Nifty/gold/FD only.
**Lessons served:** Diversification · Asset Allocation · What is a Portfolio · Mutual Funds Basics · Large Cap vs Mid Cap vs Small Cap (v2)

## Concept

Three linked sliders — **% equity (Nifty 50) / % gold / % FD** — always summing to 100. The user mixes a portfolio, replays real history (Wealth Time-Lapse engine), and sees two things side by side: the **ending value** and the **smoothness of the ride** (pain meter of the blended portfolio). The "aha": a 60/20/20 mix gives up little return but cuts the deepest fall dramatically. Diversification stops being a word and becomes a visible trade-off.

## Core interaction loop

1. Set the mix with three locked-sum sliders (drag one, the others rebalance proportionally; lock icon per slider to pin it).
2. Pick start year + SIP/lumpsum + amount (same controls as Wealth Time-Lapse — reuse markup).
3. ▶ Play: TWO lines race — "Your mix" vs "100% equity" benchmark — plus blended pain meter below.
4. End card: final values, XIRR both, max drawdown both, months-underwater both → the trade-off table.
5. Preset chips for instant comparisons: "All-in equity" · "Classic 60/40" · "Safety first (20/20/60)" · "Golden third (33/33/33)".

## Math

- Monthly rebalanced portfolio (teachable + simple): each month, portfolio return = Σ weightᵢ × assetᵢ monthly return; FD return = rate/12 constant. State this simplification in the page footnote ("rebalanced monthly").
- SIP/lumpsum contribution logic, XIRR, drawdown: **lift directly from `wealth_timelapse.html`** (`buildTrack`-equivalent on return series, `xirr`, `drawdownSeries`). Consider extracting these into `public/js/timelapse-math.js` shared by both pages — decide at build time; duplication is acceptable if extraction risks regressions.
- Pain meter runs on the blended portfolio *value* drawdown here (not single-asset price) — different from Wealth Time-Lapse; label it clearly.

## Layout

```
hero
mix card        — 3 sliders + donut showing current mix + preset chips
setup card      — start year / mode / amount / FD rate (reuse WTL controls)
race chart      — Your Mix vs 100% Equity, HUD chips
pain meter      — blended drawdown
end card        — trade-off table (return ↔ deepest fall ↔ months underwater) + lesson sentence
disclaimer
```

## Lesson sentences (templated, EN + TA)

1. Mix beats equity on drawdown with similar return → "You gave up X% of the ending value and avoided Y points of the deepest fall — that trade is what diversification means."
2. Heavy FD mix → "Smooth, but after ~6% inflation the real growth is thin — safety has its own quiet cost."
3. All-equity → "Everything rode on one asset class. The race only shows one history — in a different decade this line looked very different."

## v2 (do not build in v1)

- Mid/small-cap tracks (NIFTYMIDCAP yfinance symbols are flaky — research first) to serve the Large/Mid/Small lesson.
- "Crash zoom": click a drawdown valley to zoom both lines into that window.

## Acceptance

- [ ] Sliders always sum to 100, no dead-ends, presets work
- [ ] Blended math verified against hand-computed 2-month example (unit test in build session)
- [ ] Both XIRRs and both drawdown stats correct
- [ ] Monthly-rebalancing simplification stated on page
- [ ] Full i18n incl. dynamic strings; disclaimer present
