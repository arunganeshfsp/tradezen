# Spec 5 — Trader vs Investor Split-Screen

**Status:** proposed — **build last; needs the most careful SEBI framing**
**Page:** `public/trader_vs_investor.html`
**Backend:** reuses `GET /api/stock/timelapse/{symbol}` (monthly is too coarse for this — needs daily; small extension: `?interval=1d&period=1y` variant or a new lightweight `GET /stock/daily/{symbol}?period=1y` returning daily closes. Decide at build time.)
**Lessons served:** Investor vs Trader · Common Money Mistakes

## Concept

Same stock, same year, same starting ₹1,00,000 — two panels replaying side by side. The **left panel (Frequent Switcher)** follows a rule-based pattern that mimics common retail behaviour: jumps in after rallies, exits after dips, pays brokerage + STT + short-term tax on every round trip. The **right panel (Patient Holder)** does one entry and sits. The replay shows the friction meter on the left filling up with every switch. The point is NOT "trading is bad" — it is *costs and emotional switching are real and measurable*.

## Critical framing rule (SEBI)

- Both personas are **fictional behaviour patterns being studied**, not strategies being recommended or condemned.
- The switcher's rule must be labelled "a common emotional pattern" — never "a trading strategy".
- End-card language: comparative and descriptive ("the switcher paid ₹X in costs and missed the Y best days") — never prescriptive ("so you should hold").
- A third neutral line shows the same stock with NO money on it (just the price), so the page reads as *behaviour study on one historical path*, not advice.

## Behaviour rules (deterministic, explained on-page)

- **Switcher:** enters after the stock rises 5% in 10 days (FOMO), exits after it falls 5% from his entry (fear). Each round trip costs: brokerage flat ₹40 + 0.1% STT-ish friction + 15% tax on any gain. All knobs visible and adjustable ("make the fear stronger: exit at −3%").
- **Holder:** single entry on day 1, single exit at end. Same cost model applied once.
- Both fully deterministic for a given stock/year → replayable, debuggable, fair.

## Core interaction loop

1. Pick stock + year (default: a year with both a dip and a recovery — preselect 3 curated year choices per popular stock at build time).
2. ▶ Play: both panels animate day by day; switcher's entries/exits flash with cost toasts ("switched again — ₹412 friction"); friction meter accumulates.
3. End card: final value both sides, total friction paid, number of switches, days-in-market vs days-out, and the killer stat — **return missed by being out on the 5 best days**.
4. "Flip the year" chip: rerun on a different year where the switcher pattern accidentally wins (years exist!) — with the honest caption: "Sometimes the pattern works. The costs are the only thing guaranteed." This keeps the tool intellectually honest and SEBI-clean.

## Layout

```
hero
setup card     — stock, year chips, behaviour knobs (rise%, fall%, costs)
split stage    — two synced panels: mini price chart + position shading + value counter
                 friction meter (left only) · switch counter
tick captions  — one line per switch event
end card       — comparison table + missed-best-days stat + honest caveat sentence
disclaimer
```

## Math notes

- Daily closes, no intraday. Position shading = days holding.
- "Best days" stat: sort daily returns of the year desc, take top 5, compute holder return minus those days for the out-of-market overlay.
- Verify friction accumulation with a unit test (3 round trips on a synthetic series, hand-computed).

## Acceptance

- [ ] Both panels deterministic and synced; replay matches on every run
- [ ] Costs itemised per switch and totalled correctly (unit-tested)
- [ ] "Flip the year" produces at least one switcher-wins example with the caveat caption
- [ ] Zero prescriptive language — every string reviewed against the SEBI rules in CLAUDE.md before merge
- [ ] Full i18n; disclaimer present
