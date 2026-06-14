# Context: stock_options_tutorial_tamil.html

Status: active

## What changed (2026-06-13)

Fully rewrote to match the Hawk Spread changes implemented in `stock_options.html`.

### Structure change
- Old: 9 sections covering single-leg workflow
- New: 11 sections with Spread as the primary (default) flow

### New sections added
1. **Section 2 — Hawk Spread Builder**: Explains 2-leg vertical spread, Buy/Sell leg roles, Call Spread vs Put Spread, auto-default strikes (ATM + ATM+1 step OTM), net debit/credit, max loss/profit, breakeven — with a RELIANCE example (1420/1460 CE) showing the full math table.
2. **Section 3 — Risk Unit**: Explains ₹2,500 default, suggested lots formula (`floor(risk_unit / max_loss_per_lot)`), what to do when 1 lot > risk unit (narrow the spread).
3. **Section 4 — Liquidity Gate**: Both-legs bid-ask check, 3% threshold table, 4-leg round-trip cost example, mid-cap warning.

### Updated sections
- **Section 1 (Setup)**: Added Trade Mode toggle (Spread default), Spread Type (Call/Put) as steps 3 and 4. Added benched names warning (PREMIERENE, JSWSTEEL).
- **Section 5 (Trade Flow)**: Reframed CPR signals in terms of Spread direction (Call Spread / Put Spread) instead of single-leg direction.
- **Section 9 (Monitor)**: Added note that in Spread mode, Entry LTP = net debit, Current LTP = live net value (Long LTP − Short LTP). Updated action table to reflect spread P&L framing.
- **Section 10 (Contract History)**: Added note that From Date auto-sets to 28 calendar days before expiry (monthly stock options, not weekly rollback).
- **Section 11 (Workflow)**: Full Hawk Call Spread workflow replacing old single-leg example — uses RELIANCE 1420/1440 CE spread with Risk Unit narrowing, Liquidity Gate, Monitor exit at T1.

## Why
User requested tutorial update to match Hawk Spread implementation in `stock_options.html`.

## Known caveats
- Tutorial is educational only; all framing is SEBI-compliant (no buy/sell directives, disclaimer in footer and Section 11).
- The RELIANCE numbers used (₹42/₹18 for 1420/1460 CE) are illustrative — not live data.
- Combined Greeks (Delta, Theta per spread) are not shown — deferred for a "Fetch Greeks" button in the tool.

## Open issues
- None blocking; future enhancement: add a visual P&L curve diagram for the spread.
