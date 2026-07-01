# Context: market-psychology (TradeFun)

**File:** `public/market_psychology.html`  
**Last updated:** 2026-07-01

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

## Logic Label (added 2026-05-27)

`buildLogicLabel(d, comp, score)` — generates a single consequence sentence shown below the Score Breakdown bars as `#logic-label`. Three special states override all scoring logic (absorption, fake_breakout, momentum_weakening). For all other states, a decision tree on `score`, `d.vwap_pos`, and `comp.st_dir` selects one of ~12 templated messages with an optional volume note. CSS classes: `.bull-label` (green border), `.bear-label` (red border), `.warn-label` (orange border). Called from `updatePanel`; reset to '—' in `showClosedHub`.

---

## Post-Game Summary (added 2026-05-27)

`buildPostGame(candles)` — generates 3 bullets from `_candles` data (no backend call):
1. **Morning Trend** — avg score of first 30% of candles → Bullish/Bearish/Mixed label + time
2. **Turning Point** — first `st_dir` flip in the session → reports time and direction; "no flip" if all-day trend
3. **Key Lesson** — derived from dominant state counts + VWAP position ratio (absorption → trending → VWAP play → mixed)

`renderPostGame()` — fills `#pg-body` and shows `#postgame-wrap`. Called from `tryBuildStory()`. Hidden by `clearStory()` and `showClosedHub`. Card is collapsible via `[data-sec]` pattern. Not shown in PRACTICE mode (clearStory is called). Shown in both LIVE and REPLAY modes whenever candles are loaded.

---

## Story Enhancements (added 2026-05-27)

- **Keyword coloring** — `_colorizeStory(text)` wraps bull/bear words in `.st-bull` / `.st-bear` spans. `_renderStoryViewer` uses `innerHTML` (safe — text is generated internally, no user input).
- **Chart jump** — "📍 See on chart" button in `.sv-footer` calls `storyJumpToChart()`. Uses `_chart.setCrosshairPosition(close, time, _candleSeries)` + `timeScale().setVisibleLogicalRange()` to scroll the chart to the story entry's candle (entry `.idx` maps directly to `_candles[idx]`).
- Both nav buttons (`storyFirst/Prev/Next/Last`) and the chart button use `event.stopPropagation()` to prevent triggering the `.sv-header` collapse toggle.

## Section Collapse System (added 2026-05-27)

Pattern: `[data-sec]` marks a collapsible section. `.sec-hdr` inside it is the clickable header (calls `toggleSec(this)`). `.sec-body` is the content to hide. CSS: `[data-sec].sec-collapsed .sec-body { display:none }`.

Collapsible sections:
- `hist-section` — Recent Candles strip
- `.pg-card` inside `#postgame-wrap` — Trading Diary / Post-Game Summary
- `.story-viewer` — Day Story (the inner card, not the wrap)
- `.dom-card` — Dominance meter (bar + pcts hidden, labels row stays as header)
- Unnamed `[data-sec]` wrapper — groups `state-card` + `insight-card` under "Market State & Insight" header
- `.bk-card` — Score Breakdown bars (includes `#logic-label` inside sec-body)
- `.ci-card` — Current Candle OHLCV
- `.cp-card` — Candle Pattern card (`id="cp-body"` div also gets `sec-body` class)

---

## Known Caveats

- `tryBuildStory()` is called from 3 places: `reload()`, `fetchAndDrawLevels()`, `pollTick()` (new candle). This is intentional — CPR and candles load asynchronously and either can arrive first.
- `setChartLoading()` must clear `el.className = ''` before anything else — otherwise the `closed-hub` class persists and breaks chart height.
- Story viewer is inside `chart-col` (not full-width after main-wrap) — this fills the vertical gap left by the shorter chart vs the taller sidebar. Do not move it out.
- Replay bar (`id="replay-bar"`) sits immediately after `</div><!-- /main-wrap -->` — the story viewer must stay inside main-wrap to keep the replay bar in its correct position.

---

## Cinematic Greek Animations (added 2026-07-01)

All four effects live in a new `// ─── CINEMATIC GREEK ANIMATIONS ───` block (~2730) inserted just before the ATM Greeks Strip section.

| Feature | Key function / element |
|---|---|
| **Odometer tween** | `_tweenNum(el, from, to, dur, fmt)` — rAF cubic-ease-out from `prev→val`. Duration clamped to `min(340, _rpMs*0.78)` so it never overruns a frame at 4×. Active RAF ids stored in `_gkActiveRafs` to cancel in-flight tweens. |
| **Sparklines** | `_gkSparkUpdate(id, val)` — rolling buffer (`_sparkBuf`, 40 values) → SVG `<polyline>` in viewBox `0 0 100 24` with `preserveAspectRatio="none"`. Inline SVG element `#gk-{id}-spark` inside each `.greek-box`. Color: delta green/red by trend; theta red (decay); vega cyan; gamma purple. |
| **Magnitude gauges** | `_gkGaugeUpdate(id, val)` — Delta: needle (`#gk-delta-needle`) on `-1…+1` track via `left` %. Gamma/Theta/Vega: fill bar (`#gk-{id}-fill`) normalized against rolling max (`_sparkGaugeMax`). CSS `transition:.4s ease` for smooth movement. |
| **Scaled glow ripple** | `_gkGlowRipple(box, diff, windowMax)` — intensity = `|diff| / windowMax`, sets `--glow-a / --glow-b` CSS vars, applies `gk-glow-up/dn` keyframes. Replaces old single-intensity `.gk-flash-*`. |
| **Buffer reset** | `_resetCinematicBuffers()` — clears sparklines, gauges, narration state, `_freezeLastIdx`. Called on: `setMode('replay')`, `reload()`, `rpSeek()`, `_gkSetType()`. |

## Cinematic Page Layers (added 2026-07-01)

| Feature | Element / function |
|---|---|
| **Ambient backdrop** | `#ambient-backdrop` — fixed `z-index:0` div; all body children get `z-index:1`. `_updateAmbient(score)` sets a radial-gradient green/red aura scaled to `|score|/45`. Called from both `updatePanel` (live) and `rpRender` (replay). `transition:1.8s`. |
| **Session intro card** | `#replay-intro` — fixed overlay, fades in/out via `.show` class. `_showIntroCard()` shows it once per replay session (gated by `_introShown` flag; reset in `setMode('replay')`). Triggered from `rpPlay()`. Auto-dissolves after 2s. |
| **Narration ticker** | `#scene-narration` — strip below main-wrap, visible only in replay mode. `_updateNarration(candle)` cross-fades phrase on state change using `_NARRATION` map (8 states × 3 rotating phrases). Chapter label (`#narration-chapter`) shows the nearest previous chapter marker. SEBI-safe: all phrases are descriptive, no buy/sell/entry. |
| **Chapter markers** | `_buildChapterMarkers(candles)` — scans candles for state entries of `buyer_domination / seller_domination / fake_breakout / absorption`; stores `{idx, label, time}` in `_chapterMarkers`. `_renderTimelineMarkers()` renders `.rp-chapter-tick` ticks inside `#rp-timeline-wrap` (wraps the slider). Called from `reload()`. |
| **Freeze-frame** | `_checkFreezeFrame(candle, prevCandle)` — called per `rpRender`. On strong pattern (marubozu/engulfing) or dominance flip, calls `rpStop()` then auto-resumes via `setTimeout(rpPlay, 950)`. Gated by `_freezeEnabled` flag and `_freezeLastIdx` (prevents re-triggering same candle). Cancel on manual seek. |

## Known Caveats (updated 2026-07-01)

- `tryBuildStory()` is called from 3 places: `reload()`, `fetchAndDrawLevels()`, `pollTick()` (new candle). This is intentional — CPR and candles load asynchronously and either can arrive first.
- `setChartLoading()` must clear `el.className = ''` before anything else — otherwise the `closed-hub` class persists and breaks chart height.
- Story viewer is inside `chart-col` (not full-width after main-wrap) — this fills the vertical gap left by the shorter chart vs the taller sidebar. Do not move it out.
- Replay bar (`id="replay-bar"`) and `#scene-narration` sit immediately after `</div><!-- /main-wrap -->`.
- Sparkline SVG uses `viewBox="0 0 100 24" preserveAspectRatio="none"` — JS plots X in 0–100 range (independent of actual pixel width), so it stretches correctly without a resize listener.
- `_updateAmbient` is called from both `updatePanel` (live) and `rpRender` (replay) — the `#ambient-backdrop` is always present and animates regardless of mode.
- `@media(prefers-reduced-motion:reduce)` disables glow, ambient transition, narration fade, gauge transitions — core value display still works.
- Freeze-frame auto-resume is cancelled if user manually calls `rpSeek`. `_freezeResumeTimer` is cleared in `_resetCinematicBuffers`.

## Open Issues

- None currently known.
