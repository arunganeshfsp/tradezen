# TradeZen — Architecture

## Purpose
Indian stock market (Nifty / BankNifty) **trading education and analytics platform**. Real-time intraday dashboards, options analysis, candle education, swing screening, and trade reporting — all for retail traders learning the Indian market.

---

## Runtime Architecture

```
Browser
  │
  ▼
Node.js  :3000  (server.js + Express)
  │  serves  →  public/*.html  (static)
  │  proxies →  /api/*  →  Python :8000
  │  proxies →  /mgmt/* →  Python :8000
  │
  ▼
Python FastAPI  :8000  (ai_engine/main.py)
  │  reads  → SmartAPI WebSocket (AngelOne ticks)
  │  reads  → yfinance (prev-day OHLC, VIX)
  │  reads  → NSE website (option chain, bhav copy)
  │  writes → SQLite  (ai_engine/storage/tradezen.db)
  │
  └── Launcher  :9999  (launcher.js, basic-auth)
        starts / stops Node + Python processes
        streams logs to browser
```

---

## Directory Map

```
tradezen/
├── server.js                     Node entry point (Express static + proxy)
├── launcher.js                   Process manager UI (port 9999)
├── ecosystem.config.js           PM2 config
├── routes/
│   ├── stockRoute.js             All /api/* handlers (proxy to Python)
│   └── adminRoute.js             /mgmt/* handlers
├── services/
│   ├── aiService.js              Python proxy helpers
│   └── stockService.js           Stock data helpers
├── public/                       All frontend HTML/CSS/JS (static)
│   ├── css/
│   │   ├── halo-tokens.css       Design tokens (CSS vars)
│   │   └── halo-aurora.css       Shared component styles
│   ├── halo-aurora.js            Theme + i18n runtime (dark/light, EN/தமிழ்)
│   ├── theme.js                  Legacy theme toggle (older pages)
│   ├── theme.css                 Legacy theme variables
│   └── tradezen.css              Base layout styles
└── ai_engine/                    Python FastAPI backend
    ├── main.py                   Single FastAPI app (all routes)
    ├── config/
    │   ├── credentials.py        SmartAPI login (TOTP-based)
    │   └── settings.py           App-wide constants
    ├── data/
    │   ├── candle_fetcher.py     OHLC candle fetch (SmartAPI REST)
    │   ├── websocket_client.py   SmartAPI WebSocket tick feed
    │   ├── tick_buffer.py        In-memory tick aggregation → candles
    │   └── instrument_master.py  NSE instrument lookup
    ├── core/
    │   ├── market_state.py       Singleton — live tick state
    │   ├── signal_engine.py      Signal scoring loop
    │   ├── indicators/           EMA, VWAP, RSI, MACD, Supertrend, etc.
    │   ├── options/              Option chain, Greeks, IV, strike selection
    │   ├── analysis/             Bias, Entry, Setup, TradePlan
    │   ├── movers.py             Nifty index movers + stock indicators
    │   ├── s1_monitor.py         S1 strategy monitor
    │   ├── stock_monitor.py      Multi-stock indicator monitor
    │   ├── swing_analyzer.py     Swing setup scanner
    │   └── stock_indicators.py   Per-stock EMA/RSI/Supertrend/VWAP
    ├── storage/
    │   ├── sqlite_store.py       SQLite CRUD (trades, reports)
    │   └── parquet_store.py      Parquet candle cache
    ├── report/
    │   └── export.py             Trade report generation
    ├── execution/
    │   └── paper_trader.py       Paper trading simulator
    └── utils/
        └── logger.py             Daily rotating log files
```

---

## Data Flow — Live Tick

```
SmartAPI WebSocket
  → websocket_client.py  (on_tick callback)
  → tick_buffer.py       (aggregate ticks into 1m/5m/15m candles)
  → market_state.py      (MarketState singleton — current LTP, candle arrays)
  → signal_engine.py     (runs every ~5s in background thread)
  → /signal endpoint     (browser polls)
```

## Data Flow — Candle Fetch (REST)

```
Browser GET /api/candles?symbol=NIFTY&tf=5m
  → stockRoute.js  (proxy)
  → Python /candles
  → candle_fetcher.py  (SmartAPI getCandleData)
  → returns [{time, open, high, low, close, volume}...]
```

## Data Flow — Option Chain

```
Browser GET /api/option-chain
  → Python /option-chain
  → core/options/option_chain_fetcher.py  (NSE scrape or SmartAPI)
  → core/options/iv_analyzer.py, greeks.py, signal_scorer.py
  → structured JSON response
```

---

## Auth & Market Data Sources

| Source | Used for |
|---|---|
| AngelOne SmartAPI | Live ticks (WebSocket), candle history, option chain |
| yfinance (^NSEI, ^INDIAVIX) | Previous day OHLC, India VIX |
| NSE website | Bhav copy, option chain fallback |
| Manual POST endpoints | GIFT Nifty price, ORB levels, prev OHLC override |

---

## Shared Frontend System

| File | Purpose |
|---|---|
| `css/halo-tokens.css` | CSS custom properties (colours, radius, spacing) |
| `css/halo-aurora.css` | Component library (nav, buttons, cards, badges) |
| `halo-aurora.js` | Theme toggle (dark/light) + language toggle (EN/தமிழ்) |
| `theme.js` / `theme.css` | Legacy system — older pages not yet migrated |

Every page must include `halo-tokens.css`, `halo-aurora.css`, `halo-aurora.js` and render a `<nav class="halo-navbar">` with `#themeToggle` button and language toggle.

---

## Key Constraints

- Market hours: 09:15 – 15:30 IST (Mon–Fri, NSE)
- All timestamps in UTC internally; display in IST (+05:30)
- Python 3.14, FastAPI with async/await throughout
- Node.js proxy is thin — no business logic, just forward + return
- SQLite is the only persistent store (no PostgreSQL, no Redis)
- No user authentication implemented yet (login.html is placeholder)
