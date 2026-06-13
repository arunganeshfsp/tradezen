# Stock Autocomplete Feature

## What's new

Wherever a user types a stock symbol in the **Swing Trading** page, they can now **type the company name** instead and see autocomplete suggestions. The system converts the name to the stock code automatically.

## Where it works

**Four pages now have autocomplete:**

### Swing Trading page (swing_trading.html)
1. **Analyse Stock tab** — "Type stock name" input
2. **Reversal Radar tab** — "Type a stock name" input  
3. **Portfolio Review tab** — "Symbol" input when adding a position

### Stock Analyser page (stock-analyser.html)
4. **Search input** — "Type stock name" input at the top

## How to use

**Example: User wants to analyze Reliance Industries (RELIANCE)**

1. Click the **Analyse Stock** tab
2. In the search box, type: `reliance` (or `rel`, or even just `iance`)
3. A dropdown appears showing:
   - **Reliance Industries** (RELIANCE)
   - Any other matching stocks
4. Click on "Reliance Industries"
5. The input field auto-fills with the code **RELIANCE**
6. Click "Analyse" — the code is sent to the backend

**The dropdown shows:**
- Stock name (e.g., "Reliance Industries")
- Stock code in grey (e.g., "(RELIANCE)")

You can search by:
- Full name: `reliance industries`
- Partial name: `reliance`, `industries`, `rel`, `ance`
- Stock code: `RELIANCE` or `reli` (matches the code)

## Technical details

**Files added:**
- `public/stocks-list.js` — 150+ stocks (Nifty 100 + quality midcaps), plus autocomplete logic

**Files modified:**
- `public/swing_trading.html` — added autocomplete inputs + initialization code

**How it works:**
1. `stocks-list.js` loads on page load, making a `window.STOCKS` array available
2. As the user types, JavaScript filters the list (no backend call — instant)
3. When selected, the input value is set to the stock **code** (not name)
4. The form sends the code to the backend as usual
5. No API changes needed

## Why this approach

- **Fast:** No network calls, instant filtering in the browser
- **No backend changes:** Works with existing endpoints
- **Comprehensive:** Covers ~150 stocks (every tool's universe combined)
- **Vanilla JS:** No jQuery, no libraries, just 50 lines of simple filtering + DOM updates
- **Auto-generated:** The stock list is built from your actual backend universes, so it stays in sync
