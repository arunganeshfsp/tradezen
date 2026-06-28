# TradeZen — Context Index

Module context files capture **non-obvious decisions, active bugs, in-progress work, and known constraints** that are not visible from reading the code alone. Read the relevant file before touching a module.

---

## Context Files

| Module | File | Status |
|---|---|---|
| trade-flow | `trade-flow.md` | active |
| market-psychology | `market-psychology.md` | active |
| options-analysis | `options-analysis.md` | active |
| stock-options | `stock-options.md` | active |
| cpr-monitor | `cpr-monitor.md` | active |
| market-movers | `market-movers.md` | active |
| fno-scanner | `fno-scanner.md` | active |
| swing-trading | `swing-trading.md` | active |
| market-profile | `market-profile.md` | active |
| ai-signal | `ai-signal.md` | active |
| s1-monitor | `s1-monitor.md` | active |
| ema-scenario | `ema-scenario.md` | active |
| reports | `reports.md` | active |
| learn | `learn.md` | active |
| shared-ui | `shared-ui.md` | active |
| data-layer | `data-layer.md` | active |
| indicators | `indicators.md` | active |
| stock-analyser | `stock-analyser.md` | active |
| stock-health | `stock-health.md` | active |
| osprey-ce-pe | `osprey-ce-pe.md` | active |
| paper-trading | `paper-trading.md` | active |
| wealth-timelapse | `wealth-timelapse.md` | active |
| compounding-playground | `compounding-playground.md` | active |
| company-money-machine | `company-money-machine.md` | active |
| stock-options-tutorial-tamil | `stock_options_tutorial_tamil.md` | active |
| stock-reversal | `stock-reversal.md` | active |
| stock-breakout | `stock_breakout.md` | active |

---

## How Context Files Are Used

- **Before modifying a module** — read its context file to understand current state, open issues, and constraints
- **After a significant change** — update the context file with what changed and why
- **Status meanings**
  - `pending` — file not yet written; no special context recorded
  - `active` — file written, has current information
  - `stale` — file exists but may be outdated; verify before trusting

---

## Update Protocol

When Claude makes a significant change to a module:
1. Update the relevant `(module).md` context file with: what changed, why, any known caveats
2. Update the `Status` column in this index from `pending` → `active`
