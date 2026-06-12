# Compounding Playground — Module Context

**Built:** 2026-06-12 from `spec-kit/specs/compounding-playground.md`

## What this module is

Twin Race compounding visualizer at `public/compounding_playground.html`. Pure frontend — no backend, no Node route, no index.html card (user explicitly chose not to list it on the home page; it will be linked from learn-section lesson pages instead). Serves the Foundation lessons: Power of Compounding, Why Starting Early Matters, Long-Term Compounding, Inflation Explained, Why Money Should Grow.

## How it works

- Twin A (early, small monthly) vs Twin B (late, big monthly), shared return slider (4–18%, preset chips FD 7 / Index 12 / Aggressive 15) and end age.
- `buildTwin()` — monthly compounding `bal = bal*(1+r/12) + amount`; flat 0 before the twin's start age. **First deposit lands in the exact month the start age is reached (m=0 inclusive)** — an earlier draft had a `m > 0` guard that gave the chart-origin twin a one-month handicap; fixed for symmetry, verified by unit test in the build session.
- Chart: 4 datasets — each twin's deposited line (faint dashed) + value line filled down to it (`fill:'-1'`), so "money's own earnings" is the visible shaded region. Inflation toggle adds a 5th grey dashed line.
- `buildIdleCash()` — Twin A's contributions kept as cash, each deposit deflated at 6% p.a. from its deposit month (O(n²) loop, ~420 months, negligible).
- Animation: adaptive interval `clamp(12000/n, 25, 120)` ms, 1 month/frame (~12s journey) — same pacing pattern as Wealth Time-Lapse.
- Constraint logic in `readControls()`: B start age clamped ≥ A's; end age clamped > B start + 5.
- End card: per-twin stacked bar (deposited grey + growth in twin colour, width normalized to the larger final), winner highlight, lesson text with 3 branches (A wins & deposited less / A wins anyway / B wins) + inflation addendum. All EN+TA via `T()` + `window.onLangChange` re-render (pattern from wealth_timelapse.html).

## Known caveats

- Constant-return illustration — page disclaimer states this explicitly ("real investments fluctuate and can fall").
- Slider value labels (`aAgeV` etc.) are numerals — no i18n needed; all sentences and labels are translated.
- Chart x-axis labels are fractional ages as strings; tick callback shows only integer years.

## Open issues

- None. Lesson pages should add "Try it in the Lab" links to `/compounding_playground.html` when those lesson pages are built/updated.
