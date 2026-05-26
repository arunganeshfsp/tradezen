# Stock Analyser — Context

**Status:** active

## What it is
A standalone stock analysis tool for any NSE-listed equity. Users enter a symbol (e.g. RELIANCE, INFY) and get a comprehensive fundamental + technical snapshot with a traffic-light scorecard.

## Files
- `public/stock-analyser.html` — frontend UI
- `ai_engine/main.py` — `_stock_analyse_sync()` function + `GET /stock/analyse/{symbol}` endpoint
- `routes/stockRoute.js` — `GET /api/stock/analyse/:symbol` proxy to Python
- `public/index.html` — Tool card #07

## Backend endpoint
`GET /stock/analyse/{symbol}` (Python FastAPI, added at bottom of main.py before `/mgmt/logs`).

Data source: yfinance `tk.history(period="1y")` + `tk.info` + `tk.major_holders`.

Appends `.NS` unless symbol already ends in `.NS` or starts with `^`.

### Response shape
```
{
  symbol, company, sector, industry,
  price: { last, change_pct, day_high, day_low, week52_high, week52_low, volume, avg_volume },
  fundamentals: { market_cap, pe, forward_pe, pb, ev_ebitda, eps, book_value,
                  dividend_yield_pct, roe_pct, roa_pct, de_ratio,
                  profit_margin_pct, operating_margin_pct,
                  revenue_growth_pct, earnings_growth_pct, beta,
                  institutional_holding_pct },
  technicals: { rsi, macd, macd_signal, macd_hist, macd_cross,
                sma50, sma200, above_sma50, above_sma200, golden_cross },
  returns: { ret_1m_pct, ret_3m_pct, ret_1y_pct },
  scorecard: { valuation, momentum, financials, overall, summary }
}
```

## Scorecard logic
- **Valuation**: PE < 15 → Cheap, 15–25 → Fair, 25–40 → Stretched, >40 → Expensive
- **Momentum**: RSI primary. If Neutral (RSI 45–55), upgrade to Bullish if above both SMAs, downgrade to Bearish if below both
- **Financials**: scoring system (ROE, D/E, profit margin, earnings growth), maps to Strong/Healthy/Mixed/Concerning
- **Overall**: count of positive scorecard dimensions — 3 → positive, 2 → neutral, <2 → negative

## Known caveats
- `tk.info` can be empty for newly listed or thinly traded stocks — all fundamentals return `null` gracefully
- `major_holders` format is inconsistent across yfinance versions; institutional holding is best-effort
- D/E ratio from yfinance is in percentage form (e.g. 82.4 = 82.4%), not 0-1 fraction — scorecard thresholds set accordingly (< 50 = low debt, > 150 = high debt)
- FII/DII/promoter holding (SEBI-specific) is not available via yfinance; only shows total institutional %
- Prices are 15-min delayed outside market hours
- The endpoint uses `run_in_executor` to avoid blocking the event loop (yfinance is synchronous)
