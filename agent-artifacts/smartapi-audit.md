# SmartAPI Dependency Audit & Migration Plan

**Date:** 2026-05-30  
**Scope:** All 8 tools in TradeZen  
**Goal:** Identify SmartAPI exposure and map a broker-independent replacement strategy

---

## Dependency Summary

| # | Tool | SmartAPI? | What it needs | Fallback today |
|---|---|---|---|---|
| 01 | Trade Flow | **Yes – partial** | Live tick WebSocket, candle history (fallback) | yfinance for OHLC/VIX |
| 02 | Options Analysis | **Yes – critical** | Full option chain: LTP, OI, OI Δ, IV, Greeks, depth | None |
| 03 | F&O Scanner | **Yes – critical** | OI buildup, PCR, volume from option chain | yfinance for stock indicators |
| 04 | TradeFun | **Yes – WebSocket** | Live 1-2s ticks aggregated into candles | yfinance (historical only) |
| 05 | Market Movers | No | — | yfinance only |
| 06 | Cup & Handle | No | — | yfinance only |
| 07 | Stock Analyser | No | — | yfinance only |
| 08 | Trade Player | **Yes – live mode** | WebSocket ticks for live session; historical via yfinance | yfinance covers historical fully |

### What SmartAPI specifically provides

1. **WebSocket tick stream** — NIFTY/BANKNIFTY LTP every 1–2 seconds (Trade Flow, TradeFun, Trade Player live mode)
2. **Option chain snapshot** — LTP, OI, OI change, IV, Greeks, bid-ask for every strike (Options Analysis, F&O Scanner)
3. **Historical candles** — 1m/5m/15m OHLCV as a fallback when yfinance is slow or rate-limited
4. **Instrument master** — token → symbol mapping for all NSE/BSE instruments

---

## The Risk

AngelOne provides SmartAPI free today but there is no contractual guarantee. Historical precedent from other brokers (Zerodha KiteConnect → ₹2000/month, Upstox, Fyers) shows that broker APIs move to paid tiers once adoption is high. A single policy change by AngelOne makes **4 of 8 tools non-functional overnight** with no warning.

---

## Broker-Independent Alternatives

### 1. NSE Unofficial JSON API (Free, Fragile)

NSE exposes internal JSON endpoints used by their own website. Libraries like **`nsepython`** and **`nsedt`** wrap these with proper cookies/session handling.

```
Option chain:  https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY
OI data:       https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050
Quote:         https://www.nseindia.com/api/quote-derivative?symbol=NIFTY
```

**Covers:** Option chain OI, LTP, IV, historical EoD data  
**Does NOT cover:** Real-time sub-second ticks (WebSocket), intraday candles  
**Risk:** NSE can add auth/rate-limiting or change structure at any time — already happened twice in 2023–24. No official support.

**Verdict:** Good for option chain snapshot (refresh every 30s). Not suitable for tick-level live data.

---

### 2. Truedata (₹500–₹2,000/month — Recommended for production)

[Truedata.in](https://truedata.in) is a SEBI-registered market data vendor — not a broker. They provide:

- Live WebSocket feed (1s tick, 1m/5m candles)
- Full NSE/BSE option chain with OI, Greeks
- Historical intraday up to 10 years
- Python SDK + REST API

**Covers:** Everything SmartAPI provides today  
**Cost:** ₹500/month (delayed) to ₹2,000/month (real-time)  
**Risk:** Low — data vendors have more stable pricing than brokers because data is their only product  
**Migration effort:** Medium — replace WebSocket handler and option chain fetcher

---

### 3. MarketFeed (₹299–₹999/month)

[Marketfeed.in](https://marketfeed.in) — similar to Truedata, real-time NSE data API with Python support. Slightly cheaper.

**Covers:** Live ticks, option chain OI/IV, historical  
**Risk:** Smaller company than Truedata — less battle-tested

---

### 4. yfinance Extended (Free, Current Gaps)

Already used for: previous-day OHLC, VIX, historical candles, stock fundamentals.  
**Gaps:** No live ticks, no option chain OI/IV/Greeks for Indian markets, 15-minute delay on intraday.

For Trade Player (historical replay), yfinance already covers 100% of the need. The upgrade already done fixes the remaining gap.

---

### 5. Dhanhq API (Generous Free Tier)

Dhan is a broker but provides a free API tier with option chain and WebSocket data. Same broker-dependency risk but currently more generous than AngelOne was before SmartAPI.

---

## Recommended Migration Path

### Phase 1 — Eliminate broker dependency from historical/analytics tools (0 cost)

All three yfinance-only tools (Market Movers, Cup & Handle, Stock Analyser) plus Trade Player's historical mode are already broker-free. No action needed.

### Phase 2 — Replace option chain data with NSE unofficial API (0 cost, medium risk)

Swap `smart.getMarketData()` calls in Options Analysis and F&O Scanner with `nsepython` calls.  
- Implement a session refresher (cookies expire every ~10 minutes)  
- Add 30-second cache to reduce request rate  
- Acceptable for non-HFT use cases  

### Phase 3 — Replace live tick WebSocket with Truedata (₹500–2,000/month)

For Trade Flow and TradeFun live mode:
- Replace `smart.wsConnect()` + `smart.subscribe()` with Truedata WebSocket client  
- The rest of the app (candle aggregation, dominance scoring, psychology engine) stays identical  
- One file change: the WebSocket handler in `ai_engine/main.py`  

### Phase 4 — Drop instrument master dependency

Replace `instrument_master.json` (AngelOne-specific token file) with:
- NSE's own symbol list from their API
- A local static CSV updated weekly via a cron script

---

## Effort Estimate

| Phase | Tools affected | Effort | Cost |
|---|---|---|---|
| Phase 1 | Trade Player historical | Done ✓ | ₹0 |
| Phase 2 | Options Analysis, F&O Scanner | 2–3 days | ₹0 |
| Phase 3 | Trade Flow, TradeFun live mode | 1 day (WebSocket swap) | ₹500–2,000/month |
| Phase 4 | All (instrument master) | 0.5 day | ₹0 |

**Total to go fully broker-free:** ~4 days of work + ₹500/month for Truedata (live ticks only).  
Option chain (Options Analysis + F&O Scanner) can go free via NSE unofficial API in Phase 2.

---

## Quick Decision

| Need | Best free option | Best paid option |
|---|---|---|
| Option chain OI/IV | NSE unofficial API via `nsepython` | Truedata |
| Live ticks (WebSocket) | None (NSE doesn't provide) | Truedata (₹500/month) |
| Historical candles | yfinance ✓ | Truedata |
| Fundamentals | yfinance ✓ | — |
| Instrument master | NSE symbol CSV | — |
