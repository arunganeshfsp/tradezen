# TradeZen Flutter — Session Prompt

Paste this entire prompt at the start of any Flutter development session. It is self-contained.

---

## What We Are Building

A **Flutter mobile + desktop application** for **TradeZen** — an Indian stock market analytics and education platform focused on Nifty/BankNifty intraday trading.

The web app already exists and is fully working. Flutter is a **new client only** — the backend does not change at all.

---

## Backend — Already Live, No Changes Needed

| Item | Value |
|---|---|
| Production URL | `https://tradeze.in` |
| Hosting | DigitalOcean |
| Node proxy | Express — serves static files, proxies `/api/*` to Python |
| Python API | FastAPI (`ai_engine/main.py`) |
| Database | SQLite only |
| Auth | **None required** — the Flutter app talks directly to tradeze.in with no login |

All Flutter HTTP calls use base URL `https://tradeze.in`. No authentication headers needed.

---

## Approach — Hybrid Native + WebView

Build most screens natively in Flutter. Use `webview_flutter` for pages that depend on JavaScript charting libraries (LightweightCharts, canvas).

### Build Natively in Flutter

| Screen | API endpoints used |
|---|---|
| Home / Strategy showcase | Static — no API |
| CPR Monitor | `GET /api/cpr-levels?symbol=NIFTY&timeframe=daily` |
| Market Movers | `GET /api/stocks/movers`, `GET /api/stocks/live-prices`, `GET /api/stocks/indicators` |
| F&O Scanner | `GET /api/fno-scanner` |
| King Fisher Strategy (S1 Monitor) | `GET /api/s1-monitor` |
| Orca Strategy (Swing Trading) | `GET /api/swing/scan`, `GET /api/swing/analyse`, `GET /api/swing/prices` |
| AI Signal | `GET /api/signal`, `GET /api/indicators/snapshot` |
| Trade Flow | `GET /api/trade-flow`, `GET /api/cpr-levels`, `GET /api/price` |
| Options Analysis | `GET /api/options/chain`, `GET /api/options/score`, `GET /api/options/expiries`, `GET /api/options/risk` |
| Reports | `GET /api/reports`, `POST /api/reports/generate`, `DELETE /api/reports/:date` |
| Learn Dashboard | Static — progress stored in `shared_preferences` (key: `tz_learn`) |
| EMA Scenario | `GET /api/ema-scenario?mode=sim|live`, `GET /api/ema-scenario/backtest` |

### Use WebView (load existing tradeze.in page)

| Screen | Why WebView | URL to load |
|---|---|---|
| TradeFun / Market Psychology | LightweightCharts + canvas replay + story viewer | `https://tradeze.in/market_psychology.html` |
| Market Profile | TPO histogram — custom canvas visualization | `https://tradeze.in/market_profile.html` |
| Learn Chapters | Static Tamil HTML content (10 chapters) | `https://tradeze.in/learn_ch_ta_1.html` … `learn_ch_ta_10.html` |
| CPR Monitor chart | LightweightCharts candlestick overlay | `https://tradeze.in/cpr_monitor.html` |

---

## Key API Response Shapes

### CPR Levels
```json
GET /api/cpr-levels?symbol=NIFTY&timeframe=daily
{
  "cpr": { "bc": 22100.5, "pp": 22250.0, "tc": 22399.5, "type": "narrow", "width": 299.0 },
  "camarilla": { "s1": 22180, "s2": 22110, "s3": 22040, "r1": 22320, "r2": 22390, "r3": 22460 }
}
```

### S1 Monitor (King Fisher Strategy)
```json
GET /api/s1-monitor
{
  "signal": "CE" | "PE" | "WAIT",
  "strike": 22200,
  "expiry": "22MAY2025",
  "entry_premium": 85.5,
  "sl": 55.6,
  "t1": 123.9,
  "ema_aligned": true,
  "supertrend": "up",
  "vwap_above": true,
  "rsi": 58.2,
  "volume_ok": true
}
```

### Swing Scan (Orca Strategy)
```json
GET /api/swing/scan
{
  "setups": [
    { "symbol": "RELIANCE", "setup_type": "A", "score": 82, "entry": 2850, "sl": 2780, "t1": 2950, "t2": 3050 }
  ]
}
```

### Market Movers
```json
GET /api/stocks/movers
{
  "index": "NIFTY50",
  "gainers": [{ "symbol": "TCS", "ltp": 3820, "pct": 2.4, "volume": 1200000 }],
  "losers":  [{ "symbol": "INFY", "ltp": 1450, "pct": -1.8, "volume": 980000 }]
}
```

### Signal
```json
GET /api/signal
{
  "signal": "BUY" | "SELL" | "WAIT",
  "confidence": 72,
  "bias": "bullish" | "bearish" | "neutral",
  "indicators": { "ema": "bullish", "vwap": "ABOVE", "rsi": 61, "supertrend": "up", "pcr": 1.4 }
}
```

### Reports
```json
GET /api/reports
[{
  "date": "2026-05-22",
  "net_change": -45.5,
  "net_change_pct": -0.19,
  "scenario": "conditional_bear",
  "day_ohlc": { "open": 22300, "high": 22450, "low": 22180, "close": 22254 },
  "signals": [{ "time": "09:32", "signal": "PE", "confidence": 68, "reason": "Below BC" }]
}]
```

---

## Design Language

### Colours
| Token | Dark mode | Light mode |
|---|---|---|
| Background | `#0a0c18` | `#f8f7ff` |
| Surface | `#0e1124` | `#ffffff` |
| Border | `rgba(255,255,255,0.07)` | `rgba(0,0,0,0.08)` |
| Accent (purple) | `#7c6af7` | `#6c5de6` |
| Accent 2 (blue) | `#5b8af5` | `#4a7ae4` |
| Gain (green) | `#34d399` | `#0e9966` |
| Loss (red) | `#f87171` | `#c43d3d` |
| Foreground 1 | `#e8eaf6` | `#0f1020` |
| Foreground 2 | `#9ea3c8` | `#4a4f6a` |
| Foreground 3 (muted) | `#585d7e` | `#8a90aa` |

### App Icon
- **Dark mode:** `app-icon.svg` — amber stroke (`#F5A524`), rounded square with folded corner, "tz" text
- **Light mode:** `app-icon-light.svg` — same shape, dark stroke (`#0E0E0C`)
- Both SVGs available at `https://tradeze.in/app-icon.svg` and `https://tradeze.in/app-icon-light.svg`

### Typography
- Primary: Inter (or system sans-serif)
- Mono: JetBrains Mono (prices, timestamps, codes)

### Radius
- Cards: 16px
- Buttons: 10px
- Chips/badges: 999px (pill)

---

## Flutter Project Decisions

- **No auth** — no login screen, no token storage
- **Base URL** — `https://tradeze.in` (hardcoded constant, `AppConfig.baseUrl`)
- **Theme** — `ThemeData` dark/light, persisted via `shared_preferences` key `halo-theme`
- **Language** — EN / Tamil toggle, `flutter_localizations`, persisted via `shared_preferences` key `halo-lang`
- **Learn progress** — `shared_preferences` key `tz_learn` → `{ chapters_done: [], xp: int, badges: [] }`
- **Polling interval** — most live screens refresh every 5 seconds (match the web app)
- **Platforms** — Android, iOS, Windows, macOS

---

## Recommended Flutter Packages

| Package | Use |
|---|---|
| `http` or `dio` | API calls |
| `webview_flutter` | TradeFun, Market Profile, Learn chapters |
| `shared_preferences` | Theme, language, learn progress |
| `flutter_localizations` | EN / Tamil i18n |
| `fl_chart` | Charts for native screens (CPR levels line, signal history) |
| `provider` or `riverpod` | State management |
| `intl` | IST date/time formatting |

---

## Build Phases

### Phase 1 — Shell + Easy Screens (2 weeks)
- Flutter project setup, `AppConfig`, `ApiService` base class
- App shell: bottom nav or side drawer
- Theme toggle (dark/light), language toggle (EN/Tamil)
- Home screen: tool grid + strategy hero cards
- Reports screen
- CPR Monitor (numbers only, no chart)
- Market Movers

### Phase 2 — Strategy & Signal Screens (2 weeks)
- King Fisher Strategy (S1 signal card + readiness checklist)
- Orca Strategy (swing scan table + P&L tracker)
- AI Signal (confidence gauge, indicator breakdown)
- Trade Flow (CPR levels, scenario, bias)
- F&O Scanner

### Phase 3 — WebView Integrations (1 week)
- TradeFun → WebView `https://tradeze.in/market_psychology.html`
- Market Profile → WebView `https://tradeze.in/market_profile.html`
- Learn chapters → WebView per chapter URL

### Phase 4 — Learn Native + Polish (1 week)
- Learn Dashboard (XP bar, badge grid, chapter list → opens WebView per chapter)
- Options Analysis (tab layout, chain table)
- App icon, splash screen, responsive layout for desktop

---

## Market Context (Important for IST Handling)

- **Market hours:** 09:15 – 15:30 IST (Mon–Fri, NSE)
- **All server timestamps** are UTC internally; display as IST (UTC+5:30) in UI
- **King Fisher Strategy** only fires signals between 09:15 – 13:00 IST — show "Market Closed" / "Pre-market" states outside this window
- **Lot size** for Nifty options = 75 (verify — SEBI changes this periodically)

---

## What NOT to Do

- Do not change the backend or any Python/Node files
- Do not implement login, session tokens, or auth of any kind
- Do not replicate LightweightCharts in Flutter — use WebView
- Do not use `localhost` — always `https://tradeze.in`
