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

// ─── POST /api/set-gift-nifty ────────────────────────────────────────────────
// Manually supply current GIFT Nifty price (pre-market, from broker terminal)
// Body: { price }
router.post("/set-gift-nifty", async (req, res) => {
  try {
    const { price } = req.body;
    if (!price) return res.status(400).json({ error: "price is required" });
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

module.exports = router;
