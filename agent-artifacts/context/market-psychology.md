# Context: market-psychology (TradeFun)

**File:** `public/market_psychology.html`  
**Last updated:** 2026-05-23

---

## Current Layout

```
nav
hero
ctrl-bar (SYMBOL | TIMEFRAME | MODE: ⚡LIVE | ▶REPLAY | 🎮PRACTICE)
err-banner
main-wrap (CSS grid: chart-col 1fr | psych-sidebar 340px)
  chart-col (flex column, gap 16px)
    chart-panel          ← LightweightCharts canvas + RSI/MACD sub-panels + ind-bar
    hist-section         ← Recent Candles strip
    story-viewer-wrap    ← Day Story viewer (hidden until CPR + candles both loaded)
  psych-sidebar
    dom-card             ← Buyer/Seller dominance meter
    state-card           ← Market state badge
    insight-card         ← Educational insight text
    bk-card              ← Score breakdown bars
    ci-card              ← Current candle OHLCV
    cp-card              ← Candle Pattern card (SVG candle + name + desc)
replay-bar               ← Play/Pause/Speed/Slider (visible in REPLAY mode only)
closed-hours hub         ← Replaces chart-panel in PRACTICE/market-closed modes
```

---

## Key JavaScript State

| Variable | Purpose |
|---|---|
| `_sym` | Current symbol: `'NIFTY'` or `'BANKNIFTY'` |
| `_tf` | Timeframe: `'1m'`, `'5m'`, `'15m'` |
| `_mode` | `'live'` \| `'replay'` \| `'practice'` |
| `_candles` | Full candle array from server |
| `_cprData` | `{ cpr, cam }` — loaded async via `fetchAndDrawLevels()` |
| `_storyEntries` | All entries (dividers + real) from `generateDayStory()` |
| `_storyViewIdx` | Current position in real entries array (0-based) |
| `_rpIdx` | Current replay candle index |

---

## Key Functions

| Function | What it does |
|---|---|
| `reload()` | Fetches candles, builds chart, calls `tryBuildStory()` |
| `fetchAndDrawLevels()` | Loads CPR/Camarilla, also calls `tryBuildStory()` |
| `tryBuildStory()` | Safe builder — only runs when both `_candles` and `_cprData` loaded |
| `generateDayStory(candles, cprData)` | Returns entries array with dividers; each real entry has `.act`, `.time`, `.emoji`, `.tone`, `.text`, `.idx` |
| `renderStorySection(entries)` | Shows story-viewer-wrap, sets `_storyViewIdx` to last entry |
| `_renderStoryViewer()` | Renders current entry; reads `_SV_ACT_LABELS[e.act]` for act label |
| `storyFirst/Prev/Next/Last()` | Navigate story entries |
| `updateStoryReplayState(candleIdx)` | In replay mode — auto-advances story to matching candle |
| `detectCandlePattern(candle, prev)` | Returns a PATTERNS object entry |
| `renderPatternCard(pattern, isLive)` | Updates cp-card with SVG candle + description |
| `drawCandleSVG(candleArr, svgH)` | Renders representative SVG candle for a pattern |
| `setMode(mode)` | Switches live/replay/practice; practice calls `showClosedHub()` |
| `setChartLoading()` | Resets chart state; clears `el.className` first to remove `closed-hub` |
| `showClosedHub()` | Renders quiz/library hub inside chart panel |

---

## Story Viewer — Structure

Navigation: `⏮ ← [act pill | emoji | time | text | dots] → ⏭`

- Left column (`sv-nav-group`): `sv-first` (⏮) stacked above `sv-prev` (←)
- Right column (`sv-nav-group sv-nav-right`): `sv-next` (→) stacked above `sv-last` (⏭)
- Act label: reads `_SV_ACT_LABELS[e.act]` — keys are `1`, `2`, `3`
- Progress dots: shown only if ≤ 16 entries; classes `past`, `active`, empty
- Animation: `sv-anim` class toggled on `sv-entry` div on each navigation

---

## Candle Pattern System

`PATTERNS` object — 17 named patterns, each has `{ id, emoji, name, dir, color, desc, hint }`.  
All emojis are Unicode 6–8 (Windows 10 compatible — no Unicode 13/14).

`PATTERN_CANDLES` — representative OHLC (0–100 scale) for each pattern used in quiz + pattern card.

Detection priority (in `detectCandlePattern`):
1. Doji variants (body < 10% of range)
2. Marubozu (body > 90%)
3. Hammer / Hanging Man / Inverted Hammer / Shooting Star
4. Spinning Top
5. Two-candle patterns (Engulfing, Harami) — require `prevCandle`
6. Strong Bull/Bear (body > 60%)
7. Mild Bull/Bear (fallback)

---

## Closed-Hours Hub

Activated by: market closed OR 🎮 PRACTICE mode button (works any time).  
Two tabs: **Quiz** (random pattern → 4 options → score/streak) and **Library** (all 17 patterns as SVG grid).  
Switching back from PRACTICE calls `reload()` to restore the chart.

---

## Known Caveats

- `tryBuildStory()` is called from 3 places: `reload()`, `fetchAndDrawLevels()`, `pollTick()` (new candle). This is intentional — CPR and candles load asynchronously and either can arrive first.
- `setChartLoading()` must clear `el.className = ''` before anything else — otherwise the `closed-hub` class persists and breaks chart height.
- Story viewer is inside `chart-col` (not full-width after main-wrap) — this fills the vertical gap left by the shorter chart vs the taller sidebar. Do not move it out.
- Replay bar (`id="replay-bar"`) sits immediately after `</div><!-- /main-wrap -->` — the story viewer must stay inside main-wrap to keep the replay bar in its correct position.

---

## Open Issues

- None currently known.
