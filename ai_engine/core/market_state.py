class MarketState:
    def __init__(self):
        self.data = {}

    def update(self, tick):
        token = tick.get("token") or tick.get("subscription_mode_val")
        if not token:
            return

        token = str(token)
        prev  = self.data.get(token, {})

        # ── Price ────────────────────────────────────────────────────────
        raw_ltp  = tick.get("last_traded_price")
        ltp      = (raw_ltp / 100) if raw_ltp is not None else prev.get("price", 0)
        prev_price = prev.get("price", ltp)

        # ── Open Interest ────────────────────────────────────────────────
        oi = tick.get("open_interest")
        if oi is None:
            oi = prev.get("oi", 0)
        prev_oi = prev.get("oi", oi)

        # ── Volume ───────────────────────────────────────────────────────
        vol = tick.get("volume_trade_for_the_day")
        if vol is None:
            vol = prev.get("volume", 0)
        prev_vol = prev.get("volume", vol)

        # ── Top-5 depth aggregation ──────────────────────────────────────
        # Summing all 5 levels gives a more spoof-resistant imbalance measure
        # than best-bid/ask alone. Falls back to total_buy/sell_qty if absent.
        best_buy  = tick.get("best_5_buy_data", []) or []
        best_sell = tick.get("best_5_sell_data", []) or []

        depth_buy_qty  = sum(lvl.get("quantity", 0) for lvl in best_buy)  if best_buy  else None
        depth_sell_qty = sum(lvl.get("quantity", 0) for lvl in best_sell) if best_sell else None

        self.data[token] = {
            "price":  ltp,
            "volume": vol,
            "oi":     oi,

            # Use depth quantities when available; fall back to totals
            "buy_qty":       tick.get("total_buy_quantity", 0) or 0,
            "sell_qty":      tick.get("total_sell_quantity", 0) or 0,
            "depth_buy_qty":  depth_buy_qty  if depth_buy_qty  is not None else tick.get("total_buy_quantity", 0) or 0,
            "depth_sell_qty": depth_sell_qty if depth_sell_qty is not None else tick.get("total_sell_quantity", 0) or 0,

            "timestamp":      tick.get("exchange_timestamp"),

            "price_change":   ltp - prev_price,
            "oi_change":      oi  - prev_oi,
            "volume_change":  vol - prev_vol,
        }

    def get(self, token):
        return self.data.get(str(token), None)
