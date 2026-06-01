# Stock Health Story — Context

**Status:** active  
**Page:** `public/stock_health.html`  
**API endpoint:** `GET /stock/health/{symbol}` → `_stock_health_sync()` in `ai_engine/main.py`  
**Tool number:** 09

---

## What it does

Translates 4 yfinance fundamental ratios into a "persona" that communicates stock health visually, without financial jargon. Designed for beginners.

---

## 4 Personas

| Persona | Logic | Color |
|---|---|---|
| Fortress | Score ≥ 7 | amber `#f5a524` |
| Spring Bud | Revenue growth > 20% (override — triggers before score calc) | green `#34d399` |
| Fading Giant | Score 4–6 | gray `#9ea3c0` |
| Leaky Bucket | Score < 4 (or profit_mg < 0 caps score to 2.5) | red `#f87171` |
| Unavailable | < 2 metrics available | muted `#585d7e` |

---

## Scoring (0–10)

Each of the 4 metrics contributes max 2.5 points:

| Metric | yfinance key | +2.5 | +1.5 | +0 |
|---|---|---|---|---|
| ROE | `returnOnEquity` (decimal) | ≥ 15% | 8–15% | < 8% |
| D/E | `debtToEquity` (yfinance stores 50 = 0.5×) | < 50 | 50–100 | > 100 |
| Net Margin | `profitMargins` (decimal) | ≥ 10% | 0–10% | negative |
| Revenue Growth | `revenueGrowth` (decimal) | ≥ 10% | 0–10% | negative |

**Hard cap:** if `profitMargins < 0`, score is capped at 2.5 before persona assignment.

---

## API Response Shape

```json
{
  "symbol": "RELIANCE",
  "company": "Reliance Industries Limited",
  "sector": "Energy",
  "cap_category": "Large Cap",
  "price": 2840.50,
  "change_pct": 0.85,
  "persona": "fortress",
  "score": 8.5,
  "metrics": {
    "roe":        { "display": "18.2%", "status": "good",    "label": "Return on Equity", "label_ta": "பங்கு வருமானம்" },
    "de_ratio":   { "display": "0.4x",  "status": "good",    "label": "Debt / Equity",    "label_ta": "கடன் / பங்கு" },
    "net_margin": { "display": "12.1%", "status": "good",    "label": "Net Margin",       "label_ta": "நிகர லாப வரம்பு" },
    "rev_growth": { "display": "+8.3%", "status": "neutral", "label": "Revenue Growth",   "label_ta": "வருவாய் வளர்ச்சி" }
  },
  "narrative": { "en": "...", "ta": "..." },
  "nudge": { "en": "...", "ta": "...", "link": "/stock-analyser.html?symbol=RELIANCE", "link_en": "...", "link_ta": "..." },
  "data_note": "Financial ratios from latest annual report via Yahoo Finance...",
  "available": true
}
```

---

## Frontend Design

- **Persona card**: SVG illustration (100×80 viewBox, `currentColor`) + persona label + health score gauge (SVG semicircle arc, r=80, dasharray from JS)
- **Metric grid**: 4 cards (2×2 on mobile), color-coded by status
- **Narrative box**: bilingual toggle (EN/TA) — templates filled with live metric values, no AI
- **Nudge box**: cross-links to Stock Analyser, F&O Scanner, or Market Movers depending on persona
- **SEBI disclaimer**: always shown, no exceptions

---

## Known Caveats

- yfinance `debtToEquity` uses a scale where 50 = 0.5× D/E (not the intuitive 0.5). Display divides by 100.
- Small caps and recent IPOs often have missing ratios → "unavailable" persona shown with a gray question-mark icon.
- Revenue growth > 20% triggers Spring Bud regardless of other metrics — intentional, models early-stage growth companies.
- Data is from the latest annual report (not quarterly) — no TTM recalculation performed.
- The nudge copy follows SEBI compliance rules: no "buy/sell/entry" language, framed as analysis tool links only.

---

## Reversal Screener (companion page)

**Page:** `public/stock_reversal.html`  
**API:** `GET /stock/reversal-scan` (Node) → `GET /stock/reversal-scan` (Python)  
**Scanner module:** `ai_engine/core/patterns/reversal_scanner.py`

Pattern detected: Peak → significant decline → support touch → 2-month+ sustained recovery.

**User-configurable filters:**
- Universe: nifty50 (50 stocks) | nifty500 (~250 stocks — Nifty50 + Midcap100 + Smallcap100 combined)
- Price range: optional min/max
- Min decline %: how far the stock must have fallen from peak (default 30%)
- Min recovery %: how far it has recovered from the support (default 10%)
- Support type: single | double bottom
- Reversal age: min/max trading days since the trough (default 40–130 days)

**Performance:** Uses `yf.download()` batch download — one API call for all tickers.  
Nifty50 ≈ 10s. Nifty500 proxy ≈ 30–60s.

**Sort options:** Recovery % | Decline % | Freshest (fewest days since trough)

**Cross-link:** Each result card links to `/stock_health.html?symbol=X` for health persona.  
Stock Health Story page has a "Reversal Screener" link next to quick picks.

## Open Issues

- No cap-size filter on the quick picks — ADANIENT can sometimes return unavailable if yfinance is rate-limited.
- `?symbol=` query param supported for deep-linking from Stock Analyser or other tools.
