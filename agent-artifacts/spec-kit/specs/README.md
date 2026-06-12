# Learn-Section Interactive Tools — Spec Index

Five planned interactive tools, each serving a cluster of learn-section lessons.
Specs are written **before** implementation (SDD). When a tool is built:
1. Update its `Status` here and in the spec file.
2. Write the module context file in `agent-artifacts/context/` as usual.
3. Record in the context file anything that diverged from the spec, and why.

| # | Spec | Lessons served | Effort | Status |
|---|---|---|---|---|
| 1 | [compounding-playground.md](compounding-playground.md) | 5 (Foundation) | Small — pure frontend | **built** |
| 2 | [company-money-machine.md](company-money-machine.md) | 7 (Company Analysis) | Medium | proposed |
| 3 | [portfolio-mixer.md](portfolio-mixer.md) | 5 (Long-Term Investing) | Small-Medium — reuses timelapse API | proposed |
| 4 | [price-discovery-game.md](price-discovery-game.md) | 3 (Stock Market Basics) | Medium | proposed |
| 5 | [trader-vs-investor.md](trader-vs-investor.md) | 2 | Medium — needs careful SEBI framing | proposed |

Recommended build order: 1 → 2 → 3 → 4 → 5 (cheapest first, then highest lesson coverage).

---

## Standard page requirements (apply to every tool — do not repeat in specs)

- **File:** one self-contained page in `public/` (vanilla JS, inline styles following the TradeZen dark theme vars: `--bg:#0A0C18`, `--bg2:#13162b`, `--accent:#7c6af7`, `--green:#2ecc71`, `--red:#e74c3c`, `--cyan:#00d4ff`; fonts Syne / DM Sans / JetBrains Mono).
- **Head:** 5 favicon links, Google Fonts, `css/halo-tokens.css`, Bootstrap 5.3.3, `css/halo-aurora.css`.
- **Nav:** standard `halo-navbar` with lang toggle + `data-theme-toggle` + Home button (copy from `wealth_timelapse.html`).
- **i18n:** `data-en`/`data-ta` on all static text; JS-generated strings via local `T(en, ta)` helper reading `document.documentElement.getAttribute('data-lang')`; register `window.onLangChange` to re-render dynamic regions (pattern established in `wealth_timelapse.html`).
- **Charts:** Chart.js 4.4.1 CDN where needed.
- **SEBI:** descriptive language only — no buy/sell directives, no "entry/exit" advice. Footer disclaimer on every page: *"For educational purposes only. Not investment advice. Consult a SEBI-registered adviser before trading."*
- **Home page:** add tool card (next number) + footer link in `public/index.html`.
- **Lesson linkage:** each lesson page this tool serves should get a "🧪 Try it in the Lab" link to the tool (and the tool may link back to its lessons).
- **After build:** context file + `context/index.md` row + `spec-kit/modules.md` entry.
