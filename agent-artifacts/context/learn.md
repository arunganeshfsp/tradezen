# Context: learn

**Files:** `public/learn_home.html` (new entry point), `public/learn_m1_l1.html` (new), `public/learn_dashboard.html`, `public/learn_technical.html`, `public/learn_quiz.html`, `public/learn_ch_ta_1.html` … `learn_ch_ta_10.html`, `public/learn-sidebar.js`  
**Halo Aurora assets:** `public/halo-aurora/css/halo-tokens.css`, `halo-aurora.css`, `public/halo-aurora/js/halo-aurora.js`, `public/halo-aurora/tutorial/tutorial.css`, `tutorial.js`  
**Last updated:** 2026-05-24

---

## Purpose

Two parallel learning systems coexist:

1. **Legacy system** — `learn_dashboard.html` entry point; 10 Tamil TA chapters; old gamification. Nav links sitewide now point away from this (see below).
2. **Halo Aurora system** — `learn_home.html` entry point; new Duolingo-style Story Cards format; all sitewide `📚 Learn` nav links now point here.

---

## Halo Aurora Learning Section

### Entry point
`learn_home.html` — Halo Aurora landing page. Reads `tz_learn` localStorage for XP/progress. Shows Module 1 with Lesson 1.1 available; Lessons 1.2–1.4 locked (COMING SOON). Modules 2 & 3 show as coming soon.

### Lesson pages
`learn_m1_l1.html` — Module 1, Lesson 1: "What is the Stock Market?" — 9 Story Cards (Option B format). Three interactive checkpoints gated with `data-needs-answer`: T/F, Tap-the-image, MCQ. On completion writes `m1l1` to `lessons_done[]` and XP to `tz_learn`.

### Halo Aurora assets (self-contained under `public/halo-aurora/`)
- `css/halo-tokens.css` — all `--tz-*` design tokens (dark + light)
- `css/halo-aurora.css` — Bootstrap 5.3.3 overrides + component styles
- `js/halo-aurora.js` — theme/lang toggle, filter chips, sparklines
- `tutorial/tutorial.css` — quiz primitives, result card, confetti
- `tutorial/tutorial.js` — TZTutor engine: scoreBook, confetti, renderResult, updateProgress; XP writes to `tz_learn`

### Key design rules
- Only `var(--tz-*)` tokens — no raw hex
- Bootstrap 5.3.3 + `data-bs-theme` for dark/light (separate from legacy `theme.css`)
- Fonts: DM Serif Display / DM Sans / JetBrains Mono / Noto Sans Tamil
- XP localStorage key: `tz_learn` — same key as legacy system (compatible: legacy uses `chapters_done`, new uses `lessons_done`)
- Lesson IDs: `m1l1`, `m1l2`, etc.

### Nav migration (2026-05-24)
All sitewide `📚 Learn` nav links (16 HTML files) updated from `learn_dashboard.html` → `learn_home.html`. Old tutorial pages (`learn_ch_ta_*.html`, `swing_trading_tutorial_tamil.html`, etc.) remain on disk and accessible by direct URL but are no longer linked from the primary nav.

---

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
- **Halo Aurora isolation**: Bootstrap 5.3.3 is loaded only on `learn_home.html` and `learn_m1_l*.html`. Do NOT add it to existing tool pages — they use a separate `theme.css` system.
- **`tz_learn` key coexistence**: Legacy uses `{chapters_done, xp, badges}`. New system adds `{lessons_done, streak, last_active}` to the same object — both can coexist without conflict.
- New lessons 1.2–1.4 wait for user content — duplicate `learn_m1_l1.html`, swap card content, change lesson ID (`m1l2`, etc.), update `learn_home.html` to mark that lesson available.
