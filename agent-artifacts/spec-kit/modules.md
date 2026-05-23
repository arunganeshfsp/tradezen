# TradeZen — Module Catalog

Each module = one frontend page (or page group) + its backend routes + Python classes.

---

## 1. trade-flow
**Page:** `public/trade_flow.html`  
**Purpose:** Pre-market bias dashboard — GIFT Nifty, prev-day OHLC, ORB, India VIX, CPR levels, live signal.

| Layer | Files / Routes |
|---|---|
| Frontend | `trade_flow.html` |
| Node route | `/api/trade-flow`, `/api/fetch-gift-nifty`, `/api/set-gift-nifty`, `/api/set-prev-ohlc`, `/api/set-nifty-open`, `/api/set-orb`, `/api/price`, `/api/cpr-levels` |
| Python routes | `/trade-flow`, `/fetch-gift-nifty`, `/set-*`, `/price`, `/cpr-levels` |
| Key Python | `core/market_state.MarketState`, `core/signal_engine.SignalEngine`, `data/candle_fetcher.py`, yfinance helpers |
| Dependencies | `market-psychology` (shares `/api/candles`), `cpr-monitor` (shares `/api/cpr-levels`) |

---

## 2. market-psychology (TradeFun)
**Page:** `public/market_psychology.html`  
**Purpose:** Educational live candle viewer — buyer/seller dominance, Supertrend, VWAP, candle pattern detection, day storytelling, closed-hours quiz.

| Layer | Files / Routes |
|---|---|
| Frontend | `market_psychology.html` (all logic self-contained in page) |
| Node route | `/api/psychology/candles`, `/api/psychology/tick`, `/api/psychology/levels`, `/api/candles` |
| Python routes | `/psychology/candles`, `/psychology/tick`, `/psychology/levels`, `/candles` |
| Key Python | `core/market_state.MarketState`, `core/indicators/vwap.py`, `core/indicators/supertrend.py` |
| Key JS | `detectCandlePattern()`, `generateDayStory()`, `renderStorySection()`, `drawCandleSVG()`, quiz engine |
| Dependencies | Shared UI (`halo-aurora`), CPR levels (`/api/cpr-levels`) |

---

## 3. options-analysis
**Page:** `public/options_analysis.html`  
**Purpose:** Live option chain viewer — IV, Greeks, Max Pain, PCR, signal score, strike selector, trade monitor.

| Layer | Files / Routes |
|---|---|
| Frontend | `options_analysis.html` |
| Node route | `/api/options/context`, `/api/options/expiries`, `/api/options/search`, `/api/options/chain`, `/api/options/score`, `/api/options/select-strike`, `/api/options/risk`, `/api/options/monitor`, `/api/options/past-expiries`, `/api/options/contract-history`, `/api/options/contract-history-nse`, `/api/options/parse-bhavcopy`, `/api/iv` |
| Python classes | `core/options/option_chain_fetcher.OptionChainFetcher`, `core/options/iv_analyzer.IVAnalyzer`, `core/options/greeks.GreeksCalculator`, `core/options/max_pain.MaxPainCalculator`, `core/options/signal_scorer.SignalScorer`, `core/options/strike_selector.StrikeSelector`, `core/options/risk_calculator.RiskCalculator`, `core/options/trade_monitor.TradeMonitor` |
| Dependencies | `data/instrument_master.InstrumentMaster`, `config/credentials.get_smart_api` |

---

## 4. stock-options
**Page:** `public/stock_options.html`  
**Purpose:** Individual stock option chain analysis — same engine as options-analysis but scoped to stocks.

| Layer | Files / Routes |
|---|---|
| Frontend | `stock_options.html` |
| Node route | `/api/options/*` (shares same routes as options-analysis) |
| Dependencies | Same Python classes as `options-analysis` |

---

## 5. cpr-monitor
**Page:** `public/cpr_monitor.html`  
**Purpose:** Daily CPR (Central Pivot Range) + Camarilla levels for Nifty/BankNifty — level visualization, candle chart with levels overlaid.

| Layer | Files / Routes |
|---|---|
| Frontend | `cpr_monitor.html` |
| Node route | `/api/cpr-levels`, `/api/candles-for-cpr` |
| Python routes | `/cpr-levels`, `/candles-for-cpr` |
| Key Python | CPR math inline in `main.py` (`/cpr-levels` route), `data/candle_fetcher.py` |
| Dependencies | LightweightCharts 4.2 (charting) |

---

## 6. market-movers
**Page:** `public/stock_movers.html`  
**Purpose:** Top 10 gainers/losers across Nifty indices — live LTP polling, per-stock indicator modal (EMA, RSI, Supertrend, VWAP, entry bias score).

| Layer | Files / Routes |
|---|---|
| Frontend | `stock_movers.html` |
| Node route | `/api/stocks/movers`, `/api/stocks/live-prices`, `/api/stocks/indicators` |
| Python routes | `/stocks/movers`, `/stocks/live-prices`, `/stock-indicators/{symbol}` |
| Key Python | `core/movers.py`, `core/stock_indicators.StockIndicators` |
| Dependencies | None |

---

## 7. fno-scanner
**Page:** `public/fno_scanner.html`  
**Purpose:** F&O momentum scanner — OI buildup, volume spike, PCR trend across index options.

| Layer | Files / Routes |
|---|---|
| Frontend | `fno_scanner.html` |
| Node route | `/api/fno-scanner` |
| Python routes | `/fno-scanner` |
| Key Python | `core/options/oi_trend` (via indicators), `core/indicators/volume_spike.py`, `core/indicators/pcr.py` |
| Dependencies | `options-analysis` (shares option chain fetch) |

---

## 8. swing-trading
**Page:** `public/swing_trading.html`  
**Purpose:** Multi-timeframe swing setup scanner for stocks — EMA alignment, Supertrend, RSI, breakout setups.

| Layer | Files / Routes |
|---|---|
| Frontend | `swing_trading.html` |
| Node route | `/api/swing/analyse`, `/api/swing/scan`, `/api/swing/prices` |
| Python routes | `/swing/analyse`, `/swing/scan`, `/swing/prices` |
| Key Python | `core/swing_analyzer.SwingAnalyzer` |
| Dependencies | `core/stock_indicators.StockIndicators`, `data/candle_fetcher.py` |

---

## 9. market-profile
**Page:** `public/market_profile.html`  
**Purpose:** TPO / Volume Profile — daily and live intraday profiles, POC, VAH, VAL, IB range.

| Layer | Files / Routes |
|---|---|
| Frontend | `market_profile.html` |
| Node route | `/api/market-profile/daily`, `/api/market-profile/live`, `/api/market-profile/levels`, `/api/market-profile/multi-day` |
| Python routes | `/market-profile/*` |
| Key Python | `core/indicators/market_profile.MarketProfile` |
| Dependencies | `data/candle_fetcher.py` |

---

## 10. ai-signal
**Page:** `public/ai_signal.html`  
**Purpose:** Live signal dashboard — BUY/SELL/WAIT with confidence score, indicator breakdown, signal history.

| Layer | Files / Routes |
|---|---|
| Frontend | `ai_signal.html`, `public/ai_widget.js` |
| Node route | `/api/ai-signal`, `/api/nifty-ai-signal`, `/api/indicators/snapshot`, `/api/signal` |
| Python routes | `/signal`, `/indicators/snapshot` |
| Key Python | `core/signal_engine.SignalEngine`, `core/analysis/bias.py`, `core/analysis/entry.py`, `core/analysis/setup.py`, `core/analysis/trade_plan.py` |
| Dependencies | All indicators, `core/market_state.MarketState` |

---

## 11. s1-monitor
**Pages:** `public/s1_monitor.html`, `public/stock_s1_monitor.html`  
**Purpose:** S1 strategy monitor — tracks when price trades below/above S1 Camarilla level with reversal conditions.

| Layer | Files / Routes |
|---|---|
| Frontend | `s1_monitor.html`, `stock_s1_monitor.html` |
| Node route | `/api/s1-monitor`, `/api/stock-monitor` |
| Python routes | `/s1-monitor`, `/stock-monitor` |
| Key Python | `core/s1_monitor.S1Monitor`, `core/stock_monitor.StockMonitor` |
| Dependencies | `core/indicators/*`, `data/candle_fetcher.py` |

---

## 12. ema-scenario
**Page:** `public/ema_scenario.html`  
**Purpose:** EMA crossover scenario tool — simulate and backtest EMA 9/21 crossover setups.

| Layer | Files / Routes |
|---|---|
| Frontend | `ema_scenario.html` |
| Node route | `/api/ema-scenario`, `/api/ema-scenario/backtest` |
| Python routes | `/ema-scenario`, `/ema-scenario/backtest` |
| Key Python | `core/indicators/ema.py`, `ai_engine/backtest_trade_flow.py` |
| Dependencies | `data/candle_fetcher.py` |

---

## 13. reports
**Page:** `public/reports.html`  
**Purpose:** Daily trade journal — generate, view, and delete trade reports from the SQLite store.

| Layer | Files / Routes |
|---|---|
| Frontend | `reports.html` |
| Node route | `/api/reports`, `/api/reports/:date`, `POST /api/reports/generate`, `DELETE /api/reports/:date` |
| Python routes | `/reports`, `/reports/{date}`, `POST /reports/generate`, `DELETE /reports/{date}` |
| Key Python | `report/export.ReportExporter`, `storage/sqlite_store.SQLiteStore` |
| Dependencies | `core/signal_engine.SignalEngine` |

---

## 14. learn
**Pages:** `public/learn_dashboard.html`, `public/learn_technical.html`, `public/learn_quiz.html`, `public/learn_ch_ta_1.html` … `learn_ch_ta_10.html`  
**Purpose:** Structured candlestick + technical analysis learning path — 10 Tamil-language chapters with quiz.

| Layer | Files / Routes |
|---|---|
| Frontend | All `learn_*.html` + `learn-sidebar.js` |
| Backend | None (static content) |
| Key JS | `learn-sidebar.js` (chapter navigation sidebar) |
| i18n | All chapters available in Tamil (`data-ta` attributes) |
| Dependencies | `halo-aurora.js` (theme + language toggle) |

---

## 15. shared-ui
**Files:** `css/halo-tokens.css`, `css/halo-aurora.css`, `halo-aurora.js`, `theme.js`, `theme.css`, `tradezen.css`  
**Purpose:** Design system shared across all 25+ pages.

| Component | File | Notes |
|---|---|---|
| Design tokens | `css/halo-tokens.css` | CSS custom properties — colours, radius, shadows |
| Component styles | `css/halo-aurora.css` | Nav, buttons, cards, badges, grid |
| Theme + i18n runtime | `halo-aurora.js` | Dark/light toggle + EN/தமிழ் toggle |
| Legacy theme | `theme.js`, `theme.css` | Used on older pages not yet migrated to halo |
| Base layout | `tradezen.css` | Global resets and layout helpers |

**Rule:** New pages must use `halo-tokens` + `halo-aurora`. `theme.js`/`theme.css` are legacy — do not expand their use.

---

## 16. data-layer (Python)
**Files:** `ai_engine/data/*`, `ai_engine/storage/*`, `ai_engine/config/*`  
**Purpose:** All market data ingestion, caching, and persistence.

| Class / File | Responsibility |
|---|---|
| `data/websocket_client.WebSocketClient` | SmartAPI WebSocket — receives ticks |
| `data/tick_buffer.TickBuffer` | Aggregates ticks into OHLCV candles |
| `data/candle_fetcher.CandleFetcher` | SmartAPI REST candle history |
| `data/instrument_master.InstrumentMaster` | NSE symbol → token lookup |
| `storage/sqlite_store.SQLiteStore` | SQLite CRUD (trades, signals, reports) |
| `storage/parquet_store.ParquetStore` | Parquet candle cache for backtesting |
| `config/credentials.get_smart_api()` | Returns authenticated SmartAPI session |

---

## 17. indicators (Python)
**Files:** `ai_engine/core/indicators/*`  
**Purpose:** Stateless indicator computation functions — all take candle arrays, return values.

| File | Indicators |
|---|---|
| `vwap.py` | VWAP (cumulative, session-anchored) |
| `supertrend.py` | Supertrend (ATR-based, direction + value) |
| `ema.py` | EMA (any period) |
| `rsi.py` | RSI 14 |
| `macd.py` | MACD (12, 26, 9) |
| `market_profile.py` | TPO / Volume Profile |
| `volume_spike.py` | Relative volume spike detection |
| `pcr.py` | Put-Call Ratio from option chain |
| `imbalance.py` | Order flow imbalance |
| `candle_vwap.py` | Candle-level VWAP enrichment |
| `spot_trend.py` | Spot price trend classification |
| `price_trend.py` | Multi-candle trend direction |
| `oi_trend.py` | Open Interest trend |
| `time_window.py` | Market session time helpers |
| `constants.py` | `SPOT_TOKEN`, instrument constants |
