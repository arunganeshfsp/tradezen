# Spec 1 — Compounding Playground

**Status:** built (2026-06-12) — see `agent-artifacts/context/compounding-playground.md`
**Page:** `public/compounding_playground.html`
**Backend:** none — pure client-side math
**Lessons served:** Power of Compounding · Why Starting Early Matters · Long-Term Compounding · Inflation Explained Simply · Why Money Should Grow

## Concept

An abstract (no real market data) compounding visualizer built around one emotional hook: **the Twin Race**. Twin A starts a small monthly amount early; Twin B starts later with a bigger amount — and still loses. Sliders make the user *feel* exponential growth instead of reading about it. An inflation toggle shows idle money silently shrinking, which teaches "why money should grow" with zero extra UI.

## Core interaction loop

1. User sets the twins' parameters (or accepts defaults).
2. Hits ▶ Play — two value curves animate over the years (~10–14s, adaptive pacing like Wealth Time-Lapse).
3. End card states the result plainly: who ended with more, how much each actually deposited, and the "money's own earnings" share of each total.
4. User drags a slider → instant recompute → replay if wanted.

## Controls

| Control | Default | Range |
|---|---|---|
| Twin A: start age | 25 | 18–50 |
| Twin B: start age | 35 | 18–55 (must be ≥ A) |
| Twin A: monthly amount | ₹2,000 | 500–50,000 |
| Twin B: monthly amount | ₹4,000 | 500–50,000 |
| Annual return % | 12 | 4–18 (slider, with preset chips: FD 7 · Index 12 · Aggressive 15) |
| End age | 60 | 40–70 |
| Inflation toggle | off | shows a third dashed line: Twin A's deposits kept as idle cash, deflated at 6% p.a. |

## Math

- Monthly compounding: `bal = bal * (1 + r/12) + amount` from start-age month to end-age month; before start age the line is flat at 0.
- Split every point into `deposited` (Σ contributions) vs `growth` (bal − deposited) — the chart area-fills these in two shades so the "money earning money" region visibly overtakes deposits in later years. This split IS the lesson.
- Inflation line: `Σ contributions, each deflated by (1.06)^(years since deposit)` — idle cash losing purchasing power.

## Layout

```
hero (What-If Lab family tag)
controls card (twin A col | twin B col | shared sliders row)
race chart card  — HUD: current age · Twin A value · Twin B value (chips, live during play)
end card         — winner, totals, deposited-vs-growth bars, lesson sentence (3 templated branches)
disclaimer
```

## Lesson sentence branches (EN + TA required)

1. A wins (typical): "Twin A deposited less in total, yet finished ahead — the extra N years did the work, not the money."
2. B wins (user forces it): "Starting late can be offset — but notice how much more Twin B had to deposit every month to merely catch up."
3. Inflation toggle on: append "The grey line is money that was saved but never grew — by age 60 it buys X% less than what was put in."

## Acceptance

- [ ] Twin race animates and recomputes instantly on any slider change
- [ ] Deposited vs growth visually separated per twin
- [ ] Inflation line correct (6% deflation) and toggleable
- [ ] All dynamic strings via `T()`; lang toggle re-renders mid-animation
- [ ] No real-market claims anywhere; rate slider labelled "assumed rate, for study"
