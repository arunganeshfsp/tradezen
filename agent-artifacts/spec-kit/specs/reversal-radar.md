# Spec — Reversal Radar (Swing "Reversal" tab)

**Status:** built (2026-06-13) — see `agent-artifacts/context/swing-trading.md`
**Page:** new **Reversal** tab inside `public/swing_trading.html`
**Backend:** new module `ai_engine/core/reversal_analyzer.py`; endpoints `GET /swing/reversal/analyse` and `GET /swing/reversal/scan` in `main.py`; proxy `GET /api/swing/reversal/*` in `routes/stockRoute.js`
**Reuses:** `swing_analyzer.py` shared helpers (`STOCK_INFO`, `_fetch_stock_daily`, `_fetch_nifty_data`, `_fetch_vix`, `_fetch_sector_1m`, `_atr14`, `_position_size`, `_CACHE`), and `_stock_analyse_sync` (fundamentals) for the quality gate.

## Why a separate strategy (not the existing 5-pillar swing)

The existing swing engine is **trend-following**: it requires price > EMA50, RSI 50–70, and ≥15% above the 52-week low. It would **reject** the target setup — a quality leader that has fallen ~30% from its high and is just turning. Reversal Radar is the **mean-reversion / fallen-leader** counterpart: buy quality at the bottom of a correction after the turn is *confirmed*. Built as a sibling tab so the two opposite rule-sets never blur into one verdict.

## User calibration (agreed)

| Decision | Choice |
|---|---|
| Placement | New tab in `swing_trading.html` |
| Signal timing | **Confirmed turn** (strict) — wait for proof the bottom is in |
| Fundamental gate | **Yes** — verify company health before flagging (avoid value traps) |
| Universe | **Nifty 100 + select quality midcaps** |

## Target user

Home-maker, completed trading courses, wants higher-conviction lower-frequency swing study candidates. Bias the defaults toward **safety and teaching** over signal count.

## Algorithm — "Confirmed reversal in a fallen quality leader"

Data: 1y daily OHLCV (≈250 candles — enough for 200-DMA + pivots). Batch `yf.download` for scan; per-symbol cached fetch for single analyse.

**Stage 0 — Quality gate (chart-cheap):** market cap ≥ floor (₹5,000 Cr large / ₹15,000 Cr midcap), avg daily volume ≥ liquidity floor (~3–5 lakh sh), ≥200 candles listed.

**Stage 1 — The fall (the differentiator):** `drawdown = (high_252 − ltp)/high_252`. Require `fall_min ≤ drawdown ≤ fall_max` (defaults 15%–65%; >65% off high = likely structural damage → exclude). Configurable min via UI (his TCS example ≈ 30%).

**Stage 2 — At real support (where it fell to):** score proximity to multiple references — 200-DMA (±5%), 52-week-low band (within ~8–10%), and prior **pivot-low demand zones** (significant swing lows in the past year, ATR-scaled band). More aligned references = stronger support.

**Stage 3 — Reversal confirmation (anti-fake core; strict requires a minimum count):**
1. **Higher low** — most recent swing low > prior swing low, or a held low (N days without undercut).
2. **20-DMA reclaim** — close crossed back above 20-DMA after being below it through the fall.
3. **RSI turning up from oversold** — RSI bottomed < 40 and is rising / back above 40; **bullish divergence** (price lower-low, RSI higher-low) scores extra.
4. **MACD shift** — histogram rising / line crossing above signal.
5. **Bullish trigger candle** — engulfing / hammer / strong up-close, ideally on the reclaim day.
6. **Volume confirmation** — up-day vol > down-day vol over ~10d (accumulation), and/or reclaim candle vol ≥ 1.3–1.5× 20-day avg; bonus if volume dried up at the low then expanded on the turn.

Strict ("Confirmed") requires: higher-low **AND** 20-DMA reclaim **AND** (RSI-up OR MACD-up) **AND** volume confirmation. (A future strict/normal/early toggle would loosen this count — not in v1, which is fixed strict.)

**Stage 4 — Explicit fake-reversal rejections (each surfaced as a teaching note):**
- Still making lower lows → "knife still falling."
- Bounce on weak volume → "dead-cat bounce."
- Price still below 20-DMA → not reclaimed.
- Down >65% from high → structural.
- RSI still falling → no turn yet.
- Single gap-up candle with no hold/follow-through → exhaustion-gap risk.
- VIX ≥ 25 → market in extreme fear, stand aside (context gate).

**Stage 5 — Fundamental health gate (shortlist only, to bound cost):** run `_stock_analyse_sync` on the **top ~12** chart-passing names. Check ROE positive, D/E not extreme, earnings not collapsing, scorecard financials ≠ "Concerning". Badge: "Financials: Strong / Healthy / Caution." Separates "fell on sentiment" from "fell on broken fundamentals."

**Stage 6 — Sector context (optional, non-rejecting):** `_fetch_sector_1m(sector)` + sector drawdown — is the sector also basing/turning? Display as tailwind/headwind bonus only.

## Reversal Score (0–100, ranking)

Reversal-confirmation strength 40 · support quality 20 · volume/accumulation 15 · fundamental soundness 15 · sector tailwind 10. Rank passing candidates; show top few as "setups worth studying."

## SEBI-compliant framing (mandatory)

Descriptive only. Study levels, never directives:
- **Reference reversal level** (support / swing low where the turn is occurring) — not "entry."
- **Structure-invalidation level** (below the recent swing low — where the reversal thesis fails) — "structure breaks below ₹X."
- **Prior supply zone** (overhead resistance / measured move) — not "target to book."
- ATR-based hypothetical size via `_position_size`, framed for paper/study; horizon = days to weeks.
- Copy style: "shows a bullish reversal setup worth studying," "reference level," "structure invalidation." Never buy/sell/entry/exit/invest/avoid.
- Tab carries the standard disclaimer: *"For educational purposes only. Not investment advice. Consult a SEBI-registered adviser before trading."*

## UI — new "Reversal" tab

- **Controls:** capital, risk %, min fall % slider, universe toggle (large-cap / +midcaps), (strictness fixed to Confirmed in v1).
- **Market strip:** Nifty vs weekly EMA50, VIX zone (reuse).
- **Candidate cards:** drawdown-from-high headline ("TCS −31% from 52w high"), support read, **reversal checklist** with educational notes (mirrors existing `score_items` pattern), volume/accumulation read, fundamental badge, sector context, Reversal Score, study levels + R:R.
- **"Why rejected" (expandable):** teaches fake reversals — "still lower lows (knife falling)", "bounce on weak volume (dead-cat)".
- **Single-stock Analyse:** she types any symbol → full reversal breakdown even if it doesn't pass, so any stock is studyable.
- Full `data-en`/`data-ta` + `T()` coverage (Tamil/EN), consistent with the rest of the page.

## New helpers required (in `reversal_analyzer.py`)

`_sma(series, n)` · pivot/swing-low detection (local minima, lookback window) · bullish RSI divergence (price LL vs RSI HL) · simple candle patterns (engulfing, hammer) · up/down-volume accumulation ratio · drawdown-from-252d-high.

## Universe additions

Extend with ~20–30 quality midcaps (sector-mapped) as `MIDCAP_SELECT` + `STOCK_INFO` rows. Keep midcap mcap floor higher (₹15,000 Cr) to stay "quality."

## Performance

Scan ~120–150 names via one batch `yf.download` (existing pattern). Fundamental gate only on the top ~12 chart-passing names (sequential `tk.info`, ~0.5–1s each, cached). First run ≈ 60–90s; cached faster. Matches the existing Scan tab's profile.

## Files to touch

1. `ai_engine/core/reversal_analyzer.py` — new module (imports shared helpers from `swing_analyzer`).
2. `ai_engine/main.py` — `GET /swing/reversal/analyse`, `GET /swing/reversal/scan`.
3. `routes/stockRoute.js` — proxy `GET /api/swing/reversal/*`.
4. `public/swing_trading.html` — new "Reversal" tab, render + i18n + disclaimer.
5. SDD: update `context/swing-trading.md` + this spec → built.

## Acceptance

- [ ] A quality stock down ~30% and confirmed-turning (TCS-style) is flagged; the same stock mid-fall (lower lows / weak-volume bounce) is rejected with a teaching reason.
- [ ] Strict confirmation requires higher-low + 20-DMA reclaim + (RSI or MACD up) + volume.
- [ ] Fundamental gate badges top candidates; a weak-financials fallen stock is flagged "Caution."
- [ ] Sector context shown but never used to reject.
- [ ] All copy descriptive (no buy/sell/entry); disclaimer present; full EN/TA.
- [ ] Scan completes in the same ballpark as the existing Scan tab.
