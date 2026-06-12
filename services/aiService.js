const axios = require("axios");

const AI_ENGINE_URL = process.env.AI_ENGINE_URL || "http://localhost:8000";

class AIService {

    // 🔹 AI Signal
    async getSignal() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/signal`, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("AI service error:", err.message);
            return { signal: "ERROR", confidence: 0, reason: "Python engine unreachable" };
        }
    }

    // 🔹 Health
    async getHealth() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/health`, { timeout: 2000 });
            return res.data;
        } catch (err) {
            return { status: "error", ticks: 0, signal: "ERROR" };
        }
    }

    // Upcoming expiry dates for the frontend dropdown
    async getExpiries() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/expiries`, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Expiries error:", err.message);
            return { nearest: null, upcoming: [] };
        }
    }

    // Option chain — pass expiry param through when provided
    async getOptionChain(expiry) {
        try {
            const url = expiry
                ? `${AI_ENGINE_URL}/option-chain?expiry=${encodeURIComponent(expiry)}`
                : `${AI_ENGINE_URL}/option-chain`;
            const res = await axios.get(url, { timeout: 5000 });
            return res.data;
        } catch (err) {
            console.error("Option chain error:", err.message);
            return { data: [] };
        }
    }

    // Debug — full signal with diagnostic scores (bull/bear/side breakdown)
    async getDebug() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/debug`, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("AI debug error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Reset signal state machine — clears held/emitted signal for testing
    async resetSignal() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/reset-signal`, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Reset signal error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Trade flow — CPR levels, ORB, opening price, scenario for Trade Flow page
    async getTradeFlow() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/trade-flow`, { timeout: 10000 });
            return res.data;
        } catch (err) {
            console.error("Trade flow error:", err.message);
            return { phase: "unknown", scenario: "unknown", cpr: null, orb: null };
        }
    }

    // Auto-fetch GIFT Nifty proxy from engine (WebSocket LTP or yfinance fallback)
    async fetchGiftNifty() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/fetch-gift-nifty`, { timeout: 5000 });
            return res.data;
        } catch (err) {
            console.error("Fetch GIFT Nifty error:", err.message);
            return { status: "error", message: "Python engine unreachable" };
        }
    }

    // Manually set GIFT Nifty price (pre-market, from broker terminal)
    async setGiftNifty(price) {
        try {
            const res = await axios.post(`${AI_ENGINE_URL}/set-gift-nifty`, { price: parseFloat(price) }, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Set GIFT Nifty error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Manually set today's 9:15 opening price when engine started late
    async setNiftyOpen(price) {
        try {
            const res = await axios.post(`${AI_ENGINE_URL}/set-nifty-open?price=${price}`, {}, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Set nifty open error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Manually set today's ORB when engine started late (missed 9:15-9:30 window)
    async setOrb(high, low) {
        try {
            const params = new URLSearchParams({ high, low });
            const res = await axios.post(`${AI_ENGINE_URL}/set-orb?${params}`, {}, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Set ORB error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Manually set prev day OHLC when getCandleData API is unavailable
    async setPrevOhlc(high, low, close, date) {
        try {
            const params = new URLSearchParams({ high, low, close });
            if (date) params.append("date", date);
            const res = await axios.post(`${AI_ENGINE_URL}/set-prev-ohlc?${params}`, {}, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Set prev OHLC error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }
    // Market Profile — forward query params as-is
    async getMarketProfile(endpoint, params) {
        try {
            const qs = params ? `?${new URLSearchParams(params)}` : "";
            const res = await axios.get(`${AI_ENGINE_URL}/market-profile/${endpoint}${qs}`, { timeout: 15000 });
            return res.data;
        } catch (err) {
            console.error(`Market profile /${endpoint} error:`, err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Live NIFTY spot price from Python engine market state
    async getLivePrice() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/price`, { timeout: 2000 });
            return res.data;
        } catch (err) {
            return { price: null };
        }
    }

    // S1 intraday strategy monitor
    async getS1Monitor() {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/s1-monitor`, { timeout: 8000 });
            return res.data;
        } catch (err) {
            console.error("S1 monitor error:", err.message);
            return { status: "error", error: "Python engine unreachable" };
        }
    }

    async getStockMonitor(symbol = "RELIANCE") {
        try {
            const res = await axios.get(`${AI_ENGINE_URL}/stock-monitor`, {
                params: { symbol },
                timeout: 30000
            });
            return res.data;
        } catch (err) {
            const reason = err.code === 'ECONNABORTED' ? 'Request timed out — yfinance slow' : 'Python engine unreachable';
            console.error("Stock monitor error:", err.message);
            return { status: "error", error: reason };
        }
    }

    // EMA backtest — bulk yfinance fetch over last N trading days
    async getEmaBacktest(days = 20) {
        try {
            const res = await axios.get(
                `${AI_ENGINE_URL}/ema-scenario/backtest?days=${encodeURIComponent(days)}`,
                { timeout: 60000 }
            );
            return res.data;
        } catch (err) {
            console.error("EMA backtest error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // EMA + MACD + VWAP scenario analysis
    // mode = "sim" (synthetic) | "live" (yfinance ^NSEI)
    // live mode fetches from yfinance — allow up to 20s for the network call
    async getEmaScenario(mode) {
        try {
            const res = await axios.get(
                `${AI_ENGINE_URL}/ema-scenario?mode=${encodeURIComponent(mode)}`,
                { timeout: 20000 }
            );
            return res.data;
        } catch (err) {
            console.error("EMA scenario error:", err.message);
            return { error: "Python engine unreachable" };
        }
    }

    // Generic proxy — used by options routes to forward arbitrary GET calls
    // path: "/options/context?symbol=NIFTY"
    // data: optional JSON body for POST/PUT. Python error responses (4xx) are
    // passed through with their status so the frontend can show the message.
    async proxy(method, path, timeoutMs = 30000, data = undefined) {
        try {
            const res = await axios({ method, url: `${AI_ENGINE_URL}${path}`, timeout: timeoutMs, data });
            return res.data;
        } catch (err) {
            console.error(`AI proxy ${method} ${path} error:`, err.message);
            if (err.response && err.response.data) {
                const e = new Error(err.response.data.error || err.message);
                e.status = err.response.status;
                throw e;
            }
            return { error: "Python engine unreachable" };
        }
    }
}

module.exports = new AIService();