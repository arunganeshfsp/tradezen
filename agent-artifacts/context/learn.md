# Context: learn

**Files (active CMS system):** `public/learn/index.html`, `public/learn/lesson.html`, `public/learn/catalog.json`, `public/learn/lessons/*.json`  
**Routes:** `routes/learnRoute.js` (PostgreSQL-backed catalog + lesson API), `routes/adminLearnRoute.js` (admin CRUD)  
**Admin CMS:** `public/mgmt/learn-admin.html`  
**Legacy pages (kept but no longer linked from nav):** `public/learn_dashboard.html`, `public/learn_technical.html`, `public/learn_quiz.html`, `public/learn_ch_ta_1.html` … `learn_ch_ta_10.html`  
**Deprecated (for removal):** `public/training/learn_home.html`, `public/training/learn_m1_l1.html`, `public/training/learn_m1_l2.html`, `public/training/learn_m1_l3.html`  
**Last updated:** 2026-06-21

---

## Purpose

The CMS-driven system at `/learn/` is now the primary learn section.

- **Entry point:** `GET /learn/` → `public/learn/index.html` — catalog view, fetches `/api/learn/catalog`
- **Lesson renderer:** `public/learn/lesson.html` — single dynamic page, loads lesson by `?id=` from `/api/learn/lesson/:id`
- **Backend:** `routes/learnRoute.js` serves catalog and lesson data from PostgreSQL
- **Admin:** `/mgmt/learn-admin.html` manages content via `routes/adminLearnRoute.js` (protected by `ADMIN_TOKEN` header)

---

## Nav Migration (2026-05-27)

All sitewide `📚 Learn` nav links (25 HTML files) updated from `/training/learn_home.html` → `/learn/`.  
Files updated: cpr_monitor, fno_scanner, market_psychology, options_analysis, s1_monitor, stock_movers, swing_trading, trade_flow, index, learn_quiz, learn_technical, learn_dashboard, learn_ch_ta_1…10, swing_trading_tutorial_tamil, cup_handle_tutorial, learn/lesson.html, learn/index.html.

Back-links inside `learn/lesson.html` (close button, back button, "Back to Learn" button in rail) also updated to `/learn/`.

---

## CMS API

| Route | Returns |
|---|---|
| `GET /api/learn/catalog` | Category → module → chapter tree (single JOIN query) |
| `GET /api/learn/lesson/:id` | Full lesson with cards array |
| `GET /api/mgmt/learn/tree` | Admin tree (requires `ADMIN_TOKEN` header) |
| `GET /api/mgmt/learn/chapter/:slug` | Admin single chapter |

---

## Legacy / Old TA Course

Still accessible directly by URL; nav no longer links there:
- `learn_dashboard.html` — XP tracker + 10 Tamil TA chapters
- `learn_technical.html` — chapter listing
- `learn_ch_ta_1.html` … `learn_ch_ta_10.html` — Tamil TA chapter content
- `learn_quiz.html` — standalone quiz (uses `?module=ta&ch=N` params)

`learn_quiz.html` redirected to `/learn/` (fixed broken `/learn_home.html` href and `window.location.href`).

---

## Deprecated `/training/` pages

`public/training/learn_home.html` and `learn_m1_l1/l2/l3.html` are the old static Halo Aurora lesson pages. They are self-contained (only link to each other) and can be deleted by the user. Nothing outside `/training/` links to them anymore.

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

## Auth: Google SSO added (2026-06-20)

**Files changed:** `public/learn/auth.html`, `routes/authRoute.js`, `db/schema.sql`, `.env`, `package.json`

**What changed:**
- `auth.html` fully redesigned: Google "Continue with Google" button as primary CTA, email/password as fallback below an OR divider. Google section only renders if `GOOGLE_CLIENT_ID` is set.
- `/api/auth/config` (GET) — returns `{ google_client_id }` from env to the browser. Frontend loads GIS script dynamically only when a client ID is present.
- `/api/auth/google` (POST) — receives Google ID token, verifies with `google-auth-library` `OAuth2Client.verifyIdToken()`, finds-or-creates user. Links Google to existing email accounts (by email match, when `google_id` is NULL).
- `schema.sql` — `password_hash` made nullable (Google users have no password); `google_id TEXT` column added with partial unique index.
- `google-auth-library@^9` added to `package.json` and installed.

**Required setup (user must do):**
1. Google Cloud Console → APIs & Services → OAuth 2.0 Client ID (Web Application)
2. Authorized JavaScript origins: `https://tradeze.in`, `http://localhost:3000`
3. Add the Client ID to `.env` as `GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com`
4. Restart server (schema migration runs automatically on `initDB()`)

**Token storage:** same as email auth — `localStorage.tz_learn_token` + `tz_learn_user`

---

## learn/index.html redesign (2026-06-20)

`public/learn/index.html` was fully redesigned from a flat catalog list to a modern dashboard layout targeting youngsters and homemakers.

**New layout:**
- **Welcome row** — time-of-day greeting + XP badge
- **Progress row** — three stat cards: 🔥 Day Streak | ✅ Completed | ⭐ XP Earned
- **Continue card** — shows first unpublished+undone lesson; says "Start Here" if no progress, "Continue →" if some done
- **All Courses grid** — 2-column colorful subject cards; each card has icon, title, progress bar, lesson list rows

**Key behaviours:**
- Streak: computed on page load from `last_active` / `streak` fields in `tz_learn` localStorage (backward compatible with legacy `chapters_done` field)
- Theme: syncs to `halo-theme` key (not `tz_theme`) to stay in sync with halo-aurora.js
- Lang: reads current lang from `document.documentElement.getAttribute('lang')` set by halo-aurora.js; no toggle button on this page
- Subject colours cycle through a 6-colour PALETTE array
- Draft lessons show with a 🔒 lock icon and `is-draft` class (not clickable)
- Catalog API: tries `/api/learn/catalog` first, falls back to `/learn/catalog.json`

---

## lesson.html — Animation + Mobile CTA fix (2026-06-21)

**What changed:**
- Card-slide animation upgraded: directional slide+scale (`translateX(var(--enter-from)) scale(0.97)` → `scale(1)`) using CSS custom properties set per-transition in JS. Spring-like cubic-bezier (0.16,1,0.3,1) at 390ms.
- `is-prev` now also scales down to 0.97 (exit-to custom prop). `prefers-reduced-motion` collapses to opacity-only.
- `goTo()` in `setupNav` sets `--exit-to` on the leaving card and `--enter-from` on the entering card before class switches. `dir = idx > current ? 1 : -1`. Forward: enter from +52px, exit to -52px. Backward: reversed.
- Dot progress bar logic improved: backward navigation removes `is-done` from segs at/after the target index.
- Touch swipe added on `.deck`: `touchstart`/`touchmove`/`touchend` with axis detection (after 10px movement, horizontal if |dx| ≥ |dy|). Swipe ≥ 50px triggers `goTo`. All listeners `passive: true`.
- Mobile viewport fix: `.stage` height changed from `100vh` to `100vh; height: 100dvh` (dvh fallback-after-vh pattern). `.workspace` min-height same. `dvh` = dynamic viewport that shrinks when browser chrome is visible.
- Bottom CTA safe-area: mobile media query adds `.stage-bottom { bottom: max(16px, calc(env(safe-area-inset-bottom, 0px) + 12px)) }` — keeps Continue button above Android nav bar.

**Why:**
- On Android Chrome, `100vh` equals viewport-with-browser-chrome-hidden. When the URL bar and system nav bar are visible, the `.stage-bottom` button at `bottom: 16px` inside a `100vh` stage ends up behind or at the very edge of the nav bar. `dvh` tracks the actual visible area.
- User screenshot showed Continue button as a barely-visible purple sliver at screen bottom.

**Known caveats:**
- `dvh` is supported Chrome 108+, Firefox 110+, Safari 15.4+. Phones older than ~2022 fall back to `vh` (button may still be clipped on very old devices).
- `env(safe-area-inset-bottom)` is 0 on Android; non-zero on notched iPhones — the `max()` handles both.

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
