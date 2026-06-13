const express = require("express");
const router  = express.Router();

const stockService = require("../services/stockService");
const aiService    = require("../services/aiService");

// ─── GET /api/ai-signal ───────────────────────────────────────────────────────
// Proxies to Python FastAPI engine → /signal
// Consumed by fno_signal.html and ai_signal.html
router.get("/ai-signal", async (req, res) => {
  try {
    const data = await aiService.getSignal();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/health ─────────────────────────────────────────────────────────
// Returns Python engine status (tick count, last signal)
router.get("/health", async (req, res) => {
  try {
    const data = await aiService.getHealth();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── LEGACY route (same as /ai-signal) ───────────────────────────────────────
router.get("/nifty-ai-signal", async (req, res) => {
  try {
    const data = await aiService.getSignal();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/nifty50 ────────────────────────────────────────────────────────
router.get("/nifty50", async (req, res) => {
  try {
    const list = await stockService.getNifty50List();
    res.json(list);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stock-data?symbol=HDFCBANK ─────────────────────────────────────
router.get("/stock-data", async (req, res) => {
  try {
    const symbol = (req.query.symbol || "").trim().toUpperCase();

    if (!symbol) {
      return res.status(400).json({ error: "Symbol required" });
    }

    if (!/^[A-Z0-9\-&]{1,20}$/.test(symbol)) {
      return res.status(400).json({ error: `Invalid symbol format: ${symbol}` });
    }

    const data = await stockService.getStockData(symbol);
    res.json(data);

  } catch (err) {
    console.error("stock-data error:", err.message);

    const msg = err.message || "";
    if (
      msg.includes("No fundamentals data") ||
      msg.includes("Not found") ||
      msg.includes("No data") ||
      msg.includes("HTTPError") ||
      msg.includes("Not enough data")
    ) {
      return res.status(404).json({
        error: `'${req.query.symbol}' NSE-ல் கிடைக்கவில்லை. Symbol சரியாக உள்ளதா? (உதா: ZOMATO, TATACHEM, IRFC)`
      });
    }

    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/swing/analyse?symbol=INFY&capital=75000&risk_pct=2 ─────────────
// Full S4 5-pillar swing analysis for a single stock
router.get("/swing/analyse", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/swing/analyse?${params}`, 30000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/swing/scan?capital=75000&risk_pct=2 ────────────────────────────
// Batch S4 scan of Nifty 100 — may take 30–60 s
router.get("/swing/scan", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/swing/scan?${params}`, 120000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/swing/prices?symbols=INFY,TCS,RELIANCE ─────────────────────────
// Live LTPs for portfolio review tab
router.get("/swing/prices", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/swing/prices?${params}`, 15000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/swing/reversal/analyse?symbol=TCS&min_fall=15 ──────────────────
// Reversal Radar: confirmed-turn analysis for one fallen stock
router.get("/swing/reversal/analyse", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/swing/reversal/analyse?${params}`, 40000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/swing/reversal/scan?min_fall=15&universe=midcaps ───────────────
// Reversal Radar batch scan — may take 60–120 s (includes fundamental gate)
router.get("/swing/reversal/scan", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/swing/reversal/scan?${params}`, 180000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/s1-monitor ────────────────────────────────────────────────────────
// Real-time S1 intraday strategy monitor (OR breakout + EMA cross + RSI confirmation)
router.get("/s1-monitor", async (req, res) => {
  try {
    const data = await aiService.getS1Monitor();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stock-monitor ─────────────────────────────────────────────────
// Stock options monitor — S1 strategy for individual F&O stocks
router.get("/stock-monitor", async (req, res) => {
  try {
    const symbol = req.query.symbol || "RELIANCE";
    const data = await aiService.getStockMonitor(symbol);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/cpr-levels?symbol=NIFTY&timeframe=daily ────────────────────────
// Multi-timeframe CPR levels for NIFTY or any F&O stock
router.get("/cpr-levels", async (req, res) => {
  try {
    const qs = new URLSearchParams(req.query).toString();
    const data = await aiService.proxy("GET", `/cpr-levels?${qs}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/market-summary ─────────────────────────────────────────────────
// Live NIFTY / BANKNIFTY / India VIX quotes + sparkline + session status
router.get("/market-summary", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/market-summary", 20000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/candles ────────────────────────────────────────────────────────
// Live 5-min intraday candles for NIFTY 50 (today's session)
router.get("/candles", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/candles", 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/candles-for-cpr?symbol=NIFTY&timeframe=daily ───────────────────
// 5-min candles (daily) or daily candles (weekly/monthly) for CPR chart
router.get("/candles-for-cpr", async (req, res) => {
  try {
    const qs = new URLSearchParams(req.query).toString();
    const data = await aiService.proxy("GET", `/candles-for-cpr?${qs}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/expiries ───────────────────────────────────────────────────────
// Returns upcoming NIFTY expiry dates for the dropdown
router.get("/expiries", async (req, res) => {
  try {
    const data = await aiService.getExpiries();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/option-chain ───────────────────────────────────────────────────
// Proxies to Python FastAPI → /option-chain
// Optional query param: ?expiry=24APR2026
// Returns full strike-wise chain: { count, expiry, live, data: [{strike, ce:{...}, pe:{...}}] }
router.get("/option-chain", async (req, res) => {
  try {
    const data = await aiService.getOptionChain(req.query.expiry);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/debug ──────────────────────────────────────────────────────────
// Full signal with diagnostic scores — bull/bear/side breakdown for debugging
router.get("/debug", async (req, res) => {
  try {
    const data = await aiService.getDebug();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/reset-signal ───────────────────────────────────────────────────
// Clears the signal engine state — use when signal appears stuck during testing
router.get("/reset-signal", async (req, res) => {
  try {
    const data = await aiService.resetSignal();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/trade-flow ─────────────────────────────────────────────────────
// Returns live CPR, ORB, opening price and scenario for Nifty Trade Flow page
router.get("/trade-flow", async (req, res) => {
  try {
    const data = await aiService.getTradeFlow();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/fetch-gift-nifty ───────────────────────────────────────────────
// Auto-fetch GIFT Nifty proxy — tries live WebSocket price, then yfinance
router.get("/fetch-gift-nifty", async (req, res) => {
  try {
    const data = await aiService.fetchGiftNifty();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── POST /api/set-gift-nifty ────────────────────────────────────────────────
// Manually supply current GIFT Nifty price (pre-market, from broker terminal)
// Body: { price }
router.post("/set-gift-nifty", async (req, res) => {
  try {
    const { price } = req.body;
    if (price === undefined || price === null || isNaN(parseFloat(price))) {
      return res.status(400).json({ error: "price is required" });
    }
    const data = await aiService.setGiftNifty(price);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── POST /api/set-nifty-open ────────────────────────────────────────────────
// Manually supply today's 9:15 AM opening price when engine started late
// Body: { price }
router.post("/set-nifty-open", async (req, res) => {
  try {
    const { price } = req.body;
    if (!price) return res.status(400).json({ error: "price is required" });
    const data = await aiService.setNiftyOpen(price);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── POST /api/set-orb ───────────────────────────────────────────────────────
// Manually supply today's ORB H/L when engine started after 9:30 AM
// Body: { high, low }
router.post("/set-orb", async (req, res) => {
  try {
    const { high, low } = req.body;
    if (!high || !low) return res.status(400).json({ error: "high and low are required" });
    const data = await aiService.setOrb(high, low);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── POST /api/set-prev-ohlc ─────────────────────────────────────────────────
// Manually supply prev day H/L/C when getCandleData API fails
// Body: { high, low, close, date? }
router.post("/set-prev-ohlc", async (req, res) => {
  try {
    const { high, low, close, date } = req.body;
    if (!high || !low || !close) {
      return res.status(400).json({ error: "high, low, close are required" });
    }
    const data = await aiService.setPrevOhlc(high, low, close, date);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/ema-scenario/backtest ─────────────────────────────────────────
// Back-tests EMA+MACD+VWAP signal over last N trading days via yfinance
// ?days=10|20|30  (default 20, max 55)
router.get("/ema-scenario/backtest", async (req, res) => {
  try {
    const days = Math.min(Math.max(parseInt(req.query.days) || 20, 5), 55);
    const data = await aiService.getEmaBacktest(days);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/ema-scenario ───────────────────────────────────────────────────
// EMA 9/21 + MACD + VWAP scenario analysis
// ?mode=sim (synthetic textbook data) | ?mode=live (yfinance ^NSEI real candles)
router.get("/ema-scenario", async (req, res) => {
  try {
    const mode = req.query.mode === "live" ? "live" : "sim";
    const data = await aiService.getEmaScenario(mode);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/price ──────────────────────────────────────────────────────────
// Live NIFTY spot price from Python engine market state
router.get("/price", async (req, res) => {
  try {
    const data = await aiService.getLivePrice();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/market-profile/:endpoint ──────────────────────────────────────
// Proxy all market-profile sub-routes to FastAPI.
// Supported: daily, live, levels, multi-day
// Query params forwarded as-is: symbol_token, exchange, date, tick_size, symbol, days
["daily", "live", "levels", "multi-day"].forEach((ep) => {
  router.get(`/market-profile/${ep}`, async (req, res) => {
    try {
      const data = await aiService.getMarketProfile(ep, req.query);
      res.json(data);
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// Options Analysis Tool routes
// ══════════════════════════════════════════════════════════════════════════════

// ─── GET /api/options/context?symbol=NIFTY ───────────────────────────────────
router.get("/options/context", async (req, res) => {
  try {
    const symbol = (req.query.symbol || "NIFTY").toUpperCase();
    const data = await aiService.proxy("GET", `/options/context?symbol=${symbol}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/expiries?symbol=NIFTY ──────────────────────────────────
router.get("/options/expiries", async (req, res) => {
  try {
    const symbol = (req.query.symbol || "NIFTY").toUpperCase();
    const data = await aiService.proxy("GET", `/options/expiries?symbol=${symbol}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/search?query=NIFTY&expiry_type=weekly ─────────────────
router.get("/options/search", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.query)       params.set("query",       req.query.query);
    if (req.query.expiry_type) params.set("expiry_type", req.query.expiry_type);
    if (req.query.spot_price)  params.set("spot_price",  req.query.spot_price);
    const data = await aiService.proxy("GET", `/options/search?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/chain?symbol=NIFTY&expiry=25APR2024 ────────────────────
router.get("/options/chain", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.symbol)      params.set("symbol",      req.query.symbol);
    if (req.query.expiry)      params.set("expiry",      req.query.expiry);
    if (req.query.spot_price)  params.set("spot_price",  req.query.spot_price);
    const data = await aiService.proxy("GET", `/options/chain?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/score ───────────────────────────────────────────────────
router.get("/options/score", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/score?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/select-strike ─────────────────────────────────────────
router.get("/options/select-strike", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/select-strike?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/risk ────────────────────────────────────────────────────
router.get("/options/risk", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/risk?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/monitor ────────────────────────────────────────────────
router.get("/options/monitor", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/monitor?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/past-expiries ──────────────────────────────────────────
router.get("/options/past-expiries", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/past-expiries?${params}`);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/contract-history ───────────────────────────────────────
router.get("/options/contract-history", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/contract-history?${params}`, 60000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stocks/indicators ──────────────────────────────────────────────
router.get("/stocks/indicators", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/stocks/indicators?${params}`, 20000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stocks/movers ───────────────────────────────────────────────────
router.get("/stocks/movers", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/stocks/movers?${params}`, 30000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stocks/live-prices ─────────────────────────────────────────────
router.get("/stocks/live-prices", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/stocks/live-prices?${params}`, 8000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/options/contract-history-nse ───────────────────────────────────
router.get("/options/contract-history-nse", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/options/contract-history-nse?${params}`, 60000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── POST /api/options/parse-bhavcopy ────────────────────────────────────────
// Multipart file upload — pipe raw request stream to Python via native http
const _http = require("http");
const _PYTHON_HOST = "127.0.0.1";
const _PYTHON_PORT = parseInt((process.env.AI_ENGINE_URL || "http://127.0.0.1:8000").split(":")[2] || "8000");

router.post("/options/parse-bhavcopy", (req, res) => {
  const params = new URLSearchParams(req.query);
  const options = {
    hostname: _PYTHON_HOST,
    port:     _PYTHON_PORT,
    path:     `/options/parse-bhavcopy?${params}`,
    method:   "POST",
    headers:  { "content-type": req.headers["content-type"] },
  };
  const proxyReq = _http.request(options, (proxyRes) => {
    let body = "";
    proxyRes.on("data", (d) => { body += d; });
    proxyRes.on("end", () => {
      try { res.json(JSON.parse(body)); }
      catch { res.status(502).json({ error: "Bad response from Python engine" }); }
    });
  });
  proxyReq.on("error", (err) => {
    console.error("parse-bhavcopy proxy error:", err.message);
    res.status(500).json({ error: "Python engine unreachable" });
  });
  req.pipe(proxyReq);
});

// ─── GET /api/iv ─────────────────────────────────────────────────────────────
// ATM implied volatility for nearest NIFTY expiry via Angel One
router.get("/iv", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/iv", 10000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/candles ────────────────────────────────────────────────────────
// Today's 5-min OHLCV for NIFTY — used by the chart widget in trade_flow
router.get("/candles", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/candles", 10000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/psychology/candles ─────────────────────────────────────────────
// Full OHLCV + VWAP + Supertrend + dominance scores — used by TradeFun page
router.get("/psychology/candles", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.symbol)   params.set("symbol",   req.query.symbol);
    if (req.query.interval) params.set("interval", req.query.interval);
    if (req.query.date)     params.set("date",     req.query.date);
    const data = await aiService.proxy("GET", `/psychology/candles?${params}`, 30000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/psychology/tick ─────────────────────────────────────────────────
// Latest candle + dominance — polled every 5s for live updates
router.get("/psychology/tick", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.symbol)   params.set("symbol",   req.query.symbol);
    if (req.query.interval) params.set("interval", req.query.interval);
    const data = await aiService.proxy("GET", `/psychology/tick?${params}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/psychology/levels ──────────────────────────────────────────────
router.get("/psychology/levels", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.symbol) params.set("symbol", req.query.symbol);
    if (req.query.date)   params.set("date",   req.query.date);
    const data = await aiService.proxy("GET", `/psychology/levels?${params}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/indicators/snapshot ────────────────────────────────────────────
// VWAP · EMA 9/21 · MACD · RSI from today's 5-min yfinance candles
router.get("/indicators/snapshot", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/indicators/snapshot", 25000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/stock-indicators/:symbol ──────────────────────────────────────
// RSI, EMA trend, volume, candle pattern via Python/yfinance
router.get("/stock-indicators/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase();
    const data = await aiService.proxy("GET", `/stock-indicators/${symbol}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/fno-scanner ────────────────────────────────────────────────────
// Buy/sell dominance scanner for F&O equities in a price range
// ?min_price=1000&max_price=2000&limit=10
router.get("/fno-scanner", async (req, res) => {
  try {
    const params = new URLSearchParams();
    if (req.query.min_price)  params.set("min_price",  req.query.min_price);
    if (req.query.max_price)  params.set("max_price",  req.query.max_price);
    if (req.query.limit)      params.set("limit",      req.query.limit);
    if (req.query.dominance)  params.set("dominance",  req.query.dominance);
    if (req.query.nifty50)    params.set("nifty50",    req.query.nifty50);
    if (req.query.nifty500)   params.set("nifty500",   req.query.nifty500);
    const data = await aiService.proxy("GET", `/fno-scanner?${params}`, 15000);
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ─── GET /api/reports ────────────────────────────────────────────────────────
router.get("/reports", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/reports", 8000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/reports/:date ───────────────────────────────────────────────────
router.get("/reports/:date", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", `/reports/${req.params.date}`, 8000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── POST /api/reports/generate ──────────────────────────────────────────────
router.post("/reports/generate", async (req, res) => {
  try {
    const qs   = req.query.date ? `?date=${req.query.date}` : "";
    const data = await aiService.proxy("POST", `/reports/generate${qs}`, 20000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── DELETE /api/reports/:date ────────────────────────────────────────────────
router.delete("/reports/:date", async (req, res) => {
  try {
    const data = await aiService.proxy("DELETE", `/reports/${req.params.date}`, 8000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/screener/breakouts?category=multibagger ────────────────────────
// On-demand Nifty-500 breakout screener — may take 30–60 s
router.get("/screener/breakouts", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query).toString();
    const data = await aiService.proxy("GET", `/screener/breakouts?${params}`, 120000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

router.get("/debug/cache", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/debug/cache", 10000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/patterns/cup-handle/analyse?symbol=INFY ────────────────────────
router.get("/patterns/cup-handle/analyse", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/patterns/cup-handle/analyse?${params}`, 30000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/patterns/cup-handle/scan?universe=nifty100 ─────────────────────
router.get("/patterns/cup-handle/scan", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/patterns/cup-handle/scan?${params}`, 180000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/stock/analyse/:symbol ──────────────────────────────────────────
// Comprehensive fundamental + technical snapshot for any NSE-listed stock
router.get("/stock/analyse/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase().replace(/[^A-Z0-9\-\.&]/g, "");
    if (!symbol) return res.status(400).json({ error: "Symbol required" });
    const data = await aiService.proxy("GET", `/stock/analyse/${symbol}`, 30000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/stock/timelapse/:symbol?start=2015-01-01 ───────────────────────
// Monthly close series (stock + Nifty + gold ETF) for the Wealth Time-Lapse lab
router.get("/stock/timelapse/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase().replace(/[^A-Z0-9\-\.&^]/g, "");
    if (!symbol) return res.status(400).json({ error: "Symbol required" });
    const params = new URLSearchParams();
    if (req.query.start) params.set("start", req.query.start);
    const data = await aiService.proxy("GET", `/stock/timelapse/${symbol}?${params}`, 45000);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── GET /api/stock/reversal-scan ────────────────────────────────────────────
// Scans a stock universe for the Peak→Support→Recovery reversal pattern
router.get("/stock/reversal-scan", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/stock/reversal-scan?${params}`, 120000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ─── GET /api/stock/reversal-check/:symbol ───────────────────────────────────
// Single-stock reversal check — detailed pass/fail per criterion
router.get("/stock/reversal-check/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase().replace(/[^A-Z0-9\-\.&]/g, "");
    if (!symbol) return res.status(400).json({ error: "Symbol required" });
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/stock/reversal-check/${symbol}?${params}`, 30000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// ══════════════════════════════════════════════════════════════════════════════
// Paper Trading routes — virtual portfolio simulator
// ══════════════════════════════════════════════════════════════════════════════

// ─── GET /api/paper/account ──────────────────────────────────────────────────
router.get("/paper/account", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/paper/account", 8000);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── GET /api/paper/positions ────────────────────────────────────────────────
// Open positions marked to live LTPs (stock + option batch lookups)
router.get("/paper/positions", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/paper/positions", 20000);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── GET /api/paper/history ──────────────────────────────────────────────────
router.get("/paper/history", async (req, res) => {
  try {
    const data = await aiService.proxy("GET", "/paper/history", 8000);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── GET /api/paper/quote?instrument=STOCK&symbol=RELIANCE ───────────────────
router.get("/paper/quote", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query);
    const data = await aiService.proxy("GET", `/paper/quote?${params}`, 15000);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── POST /api/paper/order ───────────────────────────────────────────────────
// Body: { instrument, symbol, side, qty | lots+lot_size, token?, price?, ... }
router.post("/paper/order", async (req, res) => {
  try {
    const data = await aiService.proxy("POST", "/paper/order", 20000, req.body);
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── POST /api/paper/close/:id ───────────────────────────────────────────────
// Body: { price? }  — closes at live LTP when price omitted
router.post("/paper/close/:id", async (req, res) => {
  try {
    const data = await aiService.proxy("POST", `/paper/close/${req.params.id}`, 20000, req.body || {});
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── POST /api/paper/reset ───────────────────────────────────────────────────
router.post("/paper/reset", async (req, res) => {
  try {
    const data = await aiService.proxy("POST", "/paper/reset", 8000, req.body || {});
    res.json(data);
  } catch (err) { res.status(err.status || 500).json({ error: err.message }); }
});

// ─── GET /api/stock/health/:symbol ───────────────────────────────────────────
// 4-persona fundamental health report (Stock Health Story tool)
router.get("/stock/health/:symbol", async (req, res) => {
  try {
    const symbol = req.params.symbol.toUpperCase().replace(/[^A-Z0-9\-\.&]/g, "");
    if (!symbol) return res.status(400).json({ error: "Symbol required" });
    const data = await aiService.proxy("GET", `/stock/health/${symbol}`, 30000);
    res.json(data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

module.exports = router;
