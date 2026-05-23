# Context: reports

**File:** `public/reports.html`  
**Last updated:** 2026-05-23

---

## Purpose

Daily trade journal. Lists all saved reports (one per trading day) as expandable cards. Supports generating today's report from live data, viewing historical reports, and deleting entries.

---

## Key State

| Variable | Purpose |
|---|---|
| `_reports` | Array of report objects fetched from `/api/reports` |

---

## Key Functions

| Function | What it does |
|---|---|
| `loadReports()` | GET `/api/reports` → `renderList()` |
| `renderList()` | Renders all report cards into `#report-list` |
| `reportCard(r, i)` | Returns HTML for a single report card (collapsed) |
| `renderBody(r)` | Returns expanded body HTML (OHLC, CPR, ORB, signals) |
| `toggleCard(i)` | Expand/collapse card `i` |
| `generateReport()` | POST `/api/reports/generate` → re-loads list |
| `deleteReport(date, i)` | DELETE `/api/reports/{date}` → removes card |

---

## Report Data Shape

```json
{
  "date": "2026-05-22",
  "net_change": -45.5,
  "net_change_pct": -0.19,
  "scenario": "conditional_bear",
  "day_ohlc": { "open", "high", "low", "close" },
  "cpr": { "bc", "tc", "pp", "type", "width" },
  "orb": { "high", "low" },
  "signals": [{ "time", "signal", "confidence", "reason" }]
}
```

`scenario` is stored as snake_case (`conditional_bear`) — rendered with `.replace('_', ' ').toUpperCase()`.

---

## Level Chip Colours

```javascript
const lvlChip = (name) => {
  const cls = name.startsWith('R') ? 'lvl-r'
            : name.startsWith('S') ? 'lvl-s'
            : 'lvl-n';   // neutral (PP, BC, TC)
}
```

---

## Storage

Reports are stored in SQLite via `storage/sqlite_store.upsert_report()`. One row per date — generating a report for an existing date **overwrites** it (upsert, not insert).

---

## Known Caveats

- `generateReport()` always generates for **today** — no date picker. To generate for a past date, use the Python backend directly.
- Delete is irreversible — no confirmation dialog currently. Consider adding one if user data is important.
- `net_change` / `net_change_pct` are computed at report generation time from the day's open vs close — not recalculated on view.
- Cards start collapsed — `toggleCard(i)` toggles `.open` class on `#rbody-{i}` and rotates the chevron.
