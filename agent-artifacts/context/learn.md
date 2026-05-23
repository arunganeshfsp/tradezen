# Context: learn

**Files:** `public/learn_dashboard.html`, `public/learn_technical.html`, `public/learn_quiz.html`, `public/learn_ch_ta_1.html` … `learn_ch_ta_10.html`, `public/learn-sidebar.js`  
**Last updated:** 2026-05-23

---

## Purpose

Structured candlestick + technical analysis learning path. 10 Tamil-language chapters with XP/badge gamification system. Progress tracked in localStorage. No backend dependency.

---

## Structure

```
learn_dashboard.html    → course home, XP tracker, badge display, chapter grid
learn_technical.html    → chapter listing page (links to ch_ta_1 … ch_ta_10)
learn_ch_ta_1.html      → Chapter 1: Introduction to Candlesticks
...
learn_ch_ta_10.html     → Chapter 10: [advanced topic]
learn_quiz.html         → standalone quiz
learn-sidebar.js        → shared chapter navigation sidebar
```

---

## Gamification (dashboard.html)

| Concept | Detail |
|---|---|
| XP | Earned per chapter completion — amounts defined in `BADGES` array |
| Levels | `LEVEL_KEYS` array — Beginner → Intermediate → Advanced → Expert → Master |
| Badges | `BADGES` array — Quick Start (3ch), Halfway (5ch), TA Master (10ch) |
| Storage key | `'tz_learn'` in localStorage — `{ chapters_done: [], xp: number, badges: [] }` |

---

## Key State & Functions (dashboard.html)

| Item | Purpose |
|---|---|
| `TA_CHAPTERS` | Array of 10 chapter objects `{id, title, href, xp}` |
| `LEVEL_KEYS` | Ordered array of level threshold objects |
| `loadProgress()` | Read `localStorage['tz_learn']` |
| `saveProgress(data)` | Write to localStorage |
| `getProgress()` | Returns normalised progress object with defaults |
| `getLevel(xp)` | Returns current level object from `LEVEL_KEYS` |
| `renderStats(p)` | Updates XP bar, level badge, chapter count |
| `renderTACourse(p)` | Renders chapter grid with completion state |

---

## i18n

Dashboard has a custom translation object `_T` with keys for both EN and Tamil (`ta`). Uses `t(k, vars)` helper — not the global `halo-aurora.js` system. This is a legacy pattern — newer pages use `data-en` / `data-ta` attributes with `halo-aurora.js`.

Chapters (`learn_ch_ta_*.html`) are written fully in Tamil — no EN toggle needed (they are Tamil-only content pages).

---

## learn-sidebar.js

Shared sidebar used across all chapter pages. Renders chapter list with completion indicators, "next chapter" navigation, and a "back to dashboard" link. Reads progress from the same `'tz_learn'` localStorage key.

---

## Known Caveats

- Progress is **browser-local only** — no server sync. Clearing browser data resets all progress.
- Chapter XP values are defined in `TA_CHAPTERS` in the dashboard — the chapter pages themselves just mark completion, they don't know their own XP value.
- `learn_quiz.html` is standalone — quiz score is **not** saved to progress or XP.
- The `_T` translation object in dashboard.html must be maintained separately from `halo-aurora.js` — it's not auto-synced.
- Adding a chapter 11 requires: add to `TA_CHAPTERS` array, create `learn_ch_ta_11.html`, update `renderTACourse` badge thresholds if needed.
