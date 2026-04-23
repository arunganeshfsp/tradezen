from SmartApi.smartWebSocketV2 import SmartWebSocketV2
from test.test_login import login
from data.instrument_master import InstrumentMaster
from config.credentials import CLIENT_ID
from core.market_state import MarketState
from core.signal_engine import SignalEngine

market = MarketState()

engine = SignalEngine(
    ce_token=ce_token,
    pe_token=pe_token,
    market_state=market
)
def start_ws():
    result = login()
    if not result:
        print("❌ Login failed")
        return

    smart, auth_token, feed_token = result

    # 🔹 Load instrument master
    im = InstrumentMaster()
    im.load()

    # 🔹 Use last known LTP (temporary)
    ltp = 23842.65

    atm = im.get_atm_options(ltp)

    ce_token = atm["ce"]["token"]
    pe_token = atm["pe"]["token"]

    print("🎯 Subscribing to:")
    print("CE:", atm["ce"]["symbol"], ce_token)
    print("PE:", atm["pe"]["symbol"], pe_token)

    sws = SmartWebSocketV2(
        auth_token,
        smart.api_key,
        CLIENT_ID,
        feed_token
    )

    def on_open(ws):
        print("✅ WebSocket Connected")

        sws.subscribe(
            correlation_id="options_test",
            mode=3,  # 🔥 FULL DATA
            token_list=[{
                "exchangeType": 2,  # NFO (IMPORTANT)
                "tokens": [ce_token, pe_token]
            }]
        )

    def on_data(ws, message):
        market.update(message)
        result = engine.generate()
        print("📊 Signal:", result)

    def on_error(ws, error):
        print("❌ Error:", error)

    def on_close(ws):
        print("🔌 Closed")

    sws.on_open = on_open
    sws.on_data = on_data
    sws.on_error = on_error
    sws.on_close = on_close

    sws.connect()
        
if __name__ == "__main__":
    start_ws()