const YahooFinance = require('yahoo-finance2').default;
const { RSI, EMA } = require('technicalindicators');

// Nifty 50 constituents — symbol + sector
// Used as fallback if Yahoo screener fetch fails
const NIFTY50_FALLBACK = [
  { symbol: "ADANIENT",   name: "Adani Enterprises",  sector: "Conglomerate" },
  { symbol: "ADANIPORTS", name: "Adani Ports",         sector: "Infrastructure" },
  { symbol: "APOLLOHOSP", name: "Apollo Hospitals",    sector: "Healthcare" },
  { symbol: "ASIANPAINT", name: "Asian Paints",        sector: "Consumer" },
  { symbol: "AXISBANK",   name: "Axis Bank",           sector: "Banking" },
  { symbol: "BAJAJ-AUTO", name: "Bajaj Auto",          sector: "Auto" },
  { symbol: "BAJAJFINSV", name: "Bajaj Finserv",       sector: "Finance" },
  { symbol: "BAJFINANCE", name: "Bajaj Finance",       sector: "Finance" },
  { symbol: "BHARTIARTL", name: "Bharti Airtel",       sector: "Telecom" },
  { symbol: "BPCL",       name: "BPCL",                sector: "Energy" },
  { symbol: "BRITANNIA",  name: "Britannia",           sector: "FMCG" },
  { symbol: "CIPLA",      name: "Cipla",               sector: "Pharma" },
  { symbol: "COALINDIA",  name: "Coal India",          sector: "Energy" },
  { symbol: "DIVISLAB",   name: "Divi's Labs",         sector: "Pharma" },
  { symbol: "DRREDDY",    name: "Dr Reddy's",          sector: "Pharma" },
  { symbol: "EICHERMOT",  name: "Eicher Motors",       sector: "Auto" },
  { symbol: "GRASIM",     name: "Grasim Industries",   sector: "Cement" },
  { symbol: "HCLTECH",    name: "HCL Technologies",    sector: "IT" },
  { symbol: "HDFCBANK",   name: "HDFC Bank",           sector: "Banking" },
  { symbol: "HDFCLIFE",   name: "HDFC Life",           sector: "Insurance" },
  { symbol: "HEROMOTOCO", name: "Hero MotoCorp",       sector: "Auto" },
  { symbol: "HINDALCO",   name: "Hindalco",            sector: "Metals" },
  { symbol: "HINDUNILVR", name: "HUL",                 sector: "FMCG" },
  { symbol: "ICICIBANK",  name: "ICICI Bank",          sector: "Banking" },
  { symbol: "INDUSINDBK", name: "IndusInd Bank",       sector: "Banking" },
  { symbol: "INFY",       name: "Infosys",             sector: "IT" },
  { symbol: "ITC",        name: "ITC",                 sector: "FMCG" },
  { symbol: "JSWSTEEL",   name: "JSW Steel",           sector: "Metals" },
  { symbol: "KOTAKBANK",  name: "Kotak Mahindra Bank", sector: "Banking" },
  { symbol: "LT",         name: "Larsen & Toubro",     sector: "Infrastructure" },
  { symbol: "LTIM",       name: "LTIMindtree",         sector: "IT" },
  { symbol: "M&M",        name: "Mahindra & Mahindra", sector: "Auto" },
  { symbol: "MARUTI",     name: "Maruti Suzuki",       sector: "Auto" },
  { symbol: "NESTLEIND",  name: "Nestle India",        sector: "FMCG" },
  { symbol: "NTPC",       name: "NTPC",                sector: "Energy" },
  { symbol: "ONGC",       name: "ONGC",                sector: "Energy" },
  { symbol: "POWERGRID",  name: "Power Grid",          sector: "Energy" },
  { symbol: "RELIANCE",   name: "Reliance Industries", sector: "Energy" },
  { symbol: "SBILIFE",    name: "SBI Life Insurance",  sector: "Insurance" },
  { symbol: "SBIN",       name: "State Bank of India", sector: "Banking" },
  { symbol: "SHRIRAMFIN", name: "Shriram Finance",     sector: "Finance" },
  { symbol: "SUNPHARMA",  name: "Sun Pharma",          sector: "Pharma" },
  { symbol: "TATACONSUM", name: "Tata Consumer",       sector: "FMCG" },
  { symbol: "TATAMOTORS", name: "Tata Motors",         sector: "Auto" },
  { symbol: "TATASTEEL",  name: "Tata Steel",          sector: "Metals" },
  { symbol: "TCS",        name: "TCS",                 sector: "IT" },
  { symbol: "TECHM",      name: "Tech Mahindra",       sector: "IT" },
  { symbol: "TITAN",      name: "Titan Company",       sector: "Consumer" },
  { symbol: "ULTRACEMCO", name: "UltraTech Cement",    sector: "Cement" },
  { symbol: "WIPRO",      name: "Wipro",               sector: "IT" },
];

// ===== CACHE =====
let nifty50Cache = null;
let nifty50CacheTime = 0;
let indexCache = null;
let indexCacheTime = 0;
const CACHE_TTL_MS = 6 * 60 * 60 * 1000;

class StockService {
  constructor() {
    this.yf = new YahooFinance({
      suppressNotices: ['yahooSurvey', 'ripHistorical']
    });
  }

  // =========================
  // NIFTY50 LIST (DROPDOWN)
  // =========================
  async getNifty50List() {
    const now = Date.now();

    if (nifty50Cache && (now - nifty50CacheTime) < CACHE_TTL_MS) {
      return nifty50Cache;
    }

    const tickers = NIFTY50_FALLBACK.map(s => s.symbol + ".NS");

    let quotesMap = {};

    try {
      const results = await Promise.allSettled(
        tickers.map(t => this.yf.quote(t))
      );

      results.forEach((res, i) => {
        if (res.status === 'fulfilled' && res.value) {
          const sym = NIFTY50_FALLBACK[i].symbol;

          quotesMap[sym] = {
            cmp: res.value.regularMarketPrice ?? null,
            change: res.value.regularMarketChangePercent
              ? Number(res.value.regularMarketChangePercent.toFixed(2))
              : null
          };
        }
      });

    } catch (err) {
      console.error("Nifty50 fetch error:", err.message);
    }

    const list = NIFTY50_FALLBACK.map(s => ({
      symbol: s.symbol,
      name: s.name,
      sector: s.sector,
      cmp: quotesMap[s.symbol]?.cmp ?? null,
      change: quotesMap[s.symbol]?.change ?? null
    }));

    nifty50Cache = list;
    nifty50CacheTime = now;

    return list;
  }

  // =========================
  // MAIN STOCK DATA
  // =========================
  async getStockData(symbol) {
    const ticker = symbol + ".NS";

    // Fetch quote, chart and options in parallel; options failure is non-fatal
    const [quote, chart, oiData] = await Promise.all([
      this.yf.quote(ticker),
      this.yf.chart(ticker, {
        period1: "2023-01-01",
        period2: new Date(),
        interval: "1d"
      }),
      this.fetchOI(ticker),
    ]);

    const history = chart.quotes;

    if (!history || history.length < 50) {
      throw new Error("Not enough data");
    }

    const closes  = history.map(d => d.close);
    const volumes = history.map(d => d.volume);

    const rsi            = this.calculateRSI(closes);
    const trend          = this.calculateTrend(closes);
    const { support, resistance } = this.calculateSupportResistance(closes);
    const volumeSignal   = this.calculateVolumeSignal(volumes);
    const candlePattern  = this.detectCandlePattern(history);
    const indexTrend     = await this.getIndexTrend();
    const eventRisk      = this.getEventRisk();
    const { buyerVolume, sellerVolume, buySellRatio } = this.calcBuyerSellerVolume(history);

    return {
      cmp:      quote.regularMarketPrice,
      high_52w: quote.fiftyTwoWeekHigh,
      low_52w:  quote.fiftyTwoWeekLow,
      volume:   quote.regularMarketVolume,
      change:   Number((quote.regularMarketChangePercent ?? 0).toFixed(2)),

      rsi: Number(rsi.toFixed(2)),
      trend,
      support,
      resistance,
      volumeSignal,
      candlePattern,
      indexTrend,
      eventRisk,

      // Buyer / Seller volume (last 20 trading days)
      buyerVolume,
      sellerVolume,
      buySellRatio,

      // F&O Open Interest (from Yahoo Finance options chain)
      callOI:   oiData?.callOI   ?? null,
      putOI:    oiData?.putOI    ?? null,
      totalOI:  oiData?.totalOI  ?? null,
      pcr:      oiData?.pcr      ?? null,
    };
  }

  // =========================
  // BUYER / SELLER VOLUME
  // =========================
  calcBuyerSellerVolume(history) {
    const recent = history.slice(-20);
    let buyerVolume = 0, sellerVolume = 0;

    recent.forEach(d => {
      if (d.close > d.open)       buyerVolume  += (d.volume || 0);
      else if (d.close < d.open)  sellerVolume += (d.volume || 0);
      // doji candles (open === close) excluded from both
    });

    const buySellRatio = sellerVolume > 0
      ? Number((buyerVolume / sellerVolume).toFixed(2))
      : null;

    return {
      buyerVolume:  Math.round(buyerVolume),
      sellerVolume: Math.round(sellerVolume),
      buySellRatio,
    };
  }

  // =========================
  // F&O OPEN INTEREST (PCR)
  // =========================
  async fetchOI(ticker) {
    try {
      const opts = await this.yf.options(ticker);
      if (!opts?.options?.length) return null;

      const chain  = opts.options[0];   // nearest expiry
      const callOI = chain.calls.reduce((s, o) => s + (o.openInterest || 0), 0);
      const putOI  = chain.puts .reduce((s, o) => s + (o.openInterest || 0), 0);
      if (callOI + putOI === 0) return null;

      return {
        callOI,
        putOI,
        totalOI: callOI + putOI,
        pcr: Number((putOI / callOI).toFixed(2)),
      };
    } catch (_) {
      return null;
    }
  }

  // =========================
  // INDICATORS
  // =========================
  calculateRSI(closes) {
    const rsiArr = RSI.calculate({ values: closes, period: 14 });
    return rsiArr.slice(-1)[0];
  }

  calculateTrend(closes) {
    const ema20 = EMA.calculate({ values: closes, period: 20 }).slice(-1)[0];
    const ema50 = EMA.calculate({ values: closes, period: 50 }).slice(-1)[0];
    return ema20 > ema50 ? "UP" : "DOWN";
  }

  // =========================
  // SUPPORT / RESISTANCE
  // =========================
  calculateSupportResistance(closes) {
    const recent = closes.slice(-20);

    return {
      support: Math.min(...recent),
      resistance: Math.max(...recent)
    };
  }

  // =========================
  // VOLUME
  // =========================
  calculateVolumeSignal(volumes) {
    const recent = volumes.slice(-20);
    const avg = recent.reduce((a, b) => a + b, 0) / recent.length;
    const current = volumes[volumes.length - 1];

    if (current > avg * 1.5) return "HIGH";
    if (current < avg * 0.7) return "LOW";
    return "NORMAL";
  }

  // =========================
  // CANDLE PATTERN
  // =========================
  detectCandlePattern(history) {
    const last = history.slice(-2);
    if (last.length < 2) return "NONE";

    const prev = last[0];
    const curr = last[1];

    if (
      prev.close < prev.open &&
      curr.close > curr.open &&
      curr.close > prev.open &&
      curr.open < prev.close
    ) {
      return "BULLISH_ENGULFING";
    }

    if (
      prev.close > prev.open &&
      curr.close < curr.open &&
      curr.open > prev.close &&
      curr.close < prev.open
    ) {
      return "BEARISH_ENGULFING";
    }

    return "NONE";
  }

  // =========================
  // INDEX TREND
  // =========================
  

  async getIndexTrend() {
    try {
      const chart = await this.yf.chart("^NSEI", {
        period1: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000), // 90 days back
        period2: new Date(),
        interval: "1d"
      });

      const closes = chart.quotes.map(d => d.close);

      const ema20 = EMA.calculate({ values: closes, period: 20 }).slice(-1)[0];
      const ema50 = EMA.calculate({ values: closes, period: 50 }).slice(-1)[0];
      
      return ema20 > ema50 ? "UP" : "DOWN";

    } catch (err) {
      console.error("Index trend error:", err.message);
      return "UNKNOWN";
    }
  }

  // =========================
  // EVENT RISK
  // =========================
  getEventRisk() {
    const day = new Date().getDate();

    if (day >= 25 && day <= 31) return "RESULTS_SEASON";
    if (day >= 1 && day <= 5) return "MACRO_EVENTS";

    return "NONE";
  }
}

module.exports = new StockService();