# Context: de-ai-polish

**Files changed:**
- `public/index.html` — homepage visual overhaul
- `public/css/halo-aurora.css` — two new utility classes added

**Last updated:** 2026-07-10

---

## What changed

**`halo-aurora.css`** — additive only, nothing removed:
- `.text-serif` — DM Serif Display italic, solid `--tz-fg-1` colour. Replaces gradient-clip words across the homepage.
- `.kicker` — mono uppercase with a thin accent rule via `::before`. Replaces pill eyebrows across the homepage.

**`public/index.html`**:
- **Hero background** — replaced purple radial glow with faint chart-grid "graph paper" texture (`repeating-linear-gradient`).
- **Hero h1 em** — removed gradient clip; now DM Serif Display italic at `1.06em` in solid ink.
- **`.title-panel-eyebrow`** — restyled to kicker treatment; removed `background`, `border`, `border-radius`, `padding`; added `::before` accent rule.
- **CPR-line motif** — three dashed lines (TC / PIVOT / BC) inserted below the CTA buttons, `.cpr-motif` CSS in page `<style>`.
- **`.btn-aurora` glow** — killed with `box-shadow: none !important` override in page `<style>`.
- **`.section-header h2`** — DM Serif Display, weight 400, added as homepage-scoped rule.
- **Strategy card glows** — removed 5 per-card radial-gradient `::before` variants and the `hover::before opacity:1` rule; replaced with chart-axis corner ticks (`::before` top-left, `::after` bottom-right) that fade in at 70% opacity on hover.
- **5 `text-gradient fst-italic` spans** → `text-serif` (Tools h2, Strategies h2, Learn h2, FAQ h2, footer h3).
- **4 `eyebrow` class instances** → `kicker` (Tools, Strategies, Learn, FAQ sections).

## Why
Competitor site (TrueTrendView) looks nearly identical — same navy/purple "AI dark SaaS" formula. These changes make TradeZen visually ownable without changing the layout or palette.

## Known caveats
- `.text-gradient` and `.eyebrow` classes left intact in `halo-aurora.css` — other pages still use them.
- `data-en` / `data-ta` attributes on all changed spans are untouched — Tamil toggle unaffected.
- DM Serif Display renders slightly smaller than the gradient span did; the `1.06em` bump on the hero `em` compensates.
- The CPR motif uses `right: -30px` on the `<i>` labels — needs 30px right-padding in the `.cpr-motif` container if labels clip on narrow viewports. Monitor at 375px.
