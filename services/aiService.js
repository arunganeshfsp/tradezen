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
            const res = await axios.get(`${AI_ENGINE_URL}/trade-flow`, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Trade flow error:", err.message);
            return { phase: "unknown", scenario: "unknown", cpr: null, orb: null };
        }
    }

    // Manually set GIFT Nifty price (pre-market, from broker terminal)
    async setGiftNifty(price) {
        try {
            const res = await axios.post(`${AI_ENGINE_URL}/set-gift-nifty?price=${price}`, {}, { timeout: 3000 });
            return res.data;
        } catch (err) {
            console.error("Set GIFT Nifty error:", err.message);
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
}

module.exports = new AIService();