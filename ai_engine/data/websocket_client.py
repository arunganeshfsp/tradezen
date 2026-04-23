from core.market_state import MarketState
from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from config.credentials import CLIENT_ID
import time

from core.indicators.constants import SPOT_TOKEN as NIFTY_SPOT_TOKEN   # single source of truth

def start_websocket(smart, tokens, market_state):
    """
    Starts WebSocket and streams ticks into MarketState.

    Subscribes two feeds:
      • NFO options (mode 3 — full quote: price, OI, volume, top-5 depth)
      • NSE NIFTY spot (mode 1 — LTP only, used for underlying trend score)
    """

    auth_token = smart.access_token
    feed_token = smart.feed_token

    sws = SmartWebSocketV2(
        auth_token,
        smart.api_key,
        CLIENT_ID,
        feed_token
    )

    def on_open(ws):
        print("✅ WebSocket Connected")

        # Subscribe NFO options — mode 3 (full quote incl. OI + depth)
        sws.subscribe(
            correlation_id="nfo_options",
            mode=3,
            token_list=[{
                "exchangeType": 2,   # NFO
                "tokens": tokens
            }]
        )

        # Subscribe NIFTY spot — mode 1 (LTP is enough for trend calculation)
        sws.subscribe(
            correlation_id="nse_spot",
            mode=1,
            token_list=[{
                "exchangeType": 1,   # NSE
                "tokens": [NIFTY_SPOT_TOKEN]
            }]
        )

        print(f"📡 Subscribed: {len(tokens)} NFO tokens + NIFTY spot ({NIFTY_SPOT_TOKEN})")

    def on_data(ws, message):
        market_state.update(message)

    def on_error(ws, error):
        print("❌ WS Error:", error)

    def on_close(ws):
        print("🔌 WS Closed — reconnecting in 3s...")
        time.sleep(3)
        start_websocket(smart, tokens, market_state)

    sws.on_open  = on_open
    sws.on_data  = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    sws.connect()
