# Spec 4 — Price Discovery Game

**Status:** proposed
**Page:** `public/price_discovery.html`
**Backend:** none — fully simulated market
**Lessons served:** Buyers vs Sellers · Why Price Moves · What is the Stock Market

## Concept

A beginner-grade toy market that answers the most basic question textbooks fumble: *who actually decides the price?* The screen shows a crowd of cartoon buyers (green, below the price line) and sellers (red, above it) for "Chai Wala Ltd". The user injects simple events — good news, bad news, festival rush, rumour — and watches the crowd shift, orders match in the middle, and the price tick up or down on a live chart. TradeFun teaches *reading* real buyer/seller dominance; this teaches *why the mechanism exists*. Strictly a toy — no real symbols, no real data, so it stays safely abstract.

## Core interaction loop

1. Market opens at ₹100 with a balanced crowd (~12 buyers, ~12 sellers at staggered price intentions).
2. User taps an event card → crowd animates (buyers raise their bids / some sellers leave / etc.) → matching engine pairs the highest bid with the lowest ask → trade prints → price chart ticks → a plain-language caption explains what just happened.
3. After ~8 events, a session summary: "price moved from 100 to X — every move happened because someone was willing to pay more, or accept less. Nobody 'set' the price."
4. Free-play sliders unlock after first guided round: buyer count, seller count, eagerness.

## Event cards (each = a crowd mutation + caption, EN + TA)

| Card | Effect | Teaches |
|---|---|---|
| 📰 Good news | buyers +4, bids shift up 2–4% | demand pull |
| 🌧 Bad news | sellers +4, asks shift down | supply push |
| 🎉 Festival demand | buyers more eager (bids jump toward asks) | aggression = faster moves |
| 🗣 Rumour | random ±, then reverts | noise vs information |
| 🏦 Big buyer (FII) | one buyer wants 5× quantity | size moves price (links Retail vs FII lesson) |
| 😴 Nobody trades | spread sits, no prints | no trade = no price change |

## Matching engine (simplified, but honest)

- Each participant: `{side, qty, limit}`; book sorted; trade executes when best bid ≥ best ask at the midpoint; print appends to the tick chart.
- One match per animation beat (~800ms) so the user can *watch* pairing happen — a line connects the matched buyer and seller figures before they fade out.
- Keep total participants ≤ 30 for readability; replenish quietly at the edges.

## Layout

```
hero
stage card    — price line in the middle, buyer figures below, seller figures above,
                matched-pair animation, last-traded-price badge
event rail    — horizontal card row (tap to fire), free-play sliders (locked initially)
tick chart    — running price line with event markers
caption strip — one sentence per event, plain language
summary card  — after guided round
disclaimer
```

## Tone & SEBI

- Fictional company, ₹ values, cartoon style — never frame any event as a signal ("good news → price rose *because more people wanted it*", not "buy on good news").
- Summary language is mechanical/descriptive throughout.

## Acceptance

- [ ] Guided round of 8 events runs without dead states; every event produces a visible crowd change + caption
- [ ] Matching animation clearly pairs one buyer with one seller before the price ticks
- [ ] "Nobody trades" card genuinely produces no print (teaches the difference between quote and trade)
- [ ] Free-play mode cannot crash the book (empty side handled: "no sellers left — price means nothing until someone sells")
- [ ] Full i18n; works on mobile portrait (crowd shrinks to dots with tooltips)
