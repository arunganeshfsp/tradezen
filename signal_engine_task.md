I’m building an AI-based NIFTY options signal engine using Angel One SmartAPI (Python).

Current status (already implemented and working):

SmartAPI authentication (API key + TOTP)
WebSocket connection (SmartWebSocketV2)
Instrument master integration using OpenAPIScripMaster.json
Filtering only NIFTY options (OPTIDX, NFO)
ATM strike detection based on LTP
Dynamic CE/PE token selection
Real-time WebSocket subscription for ATM CE & PE (mode=3)
Tick parsing (price, volume, OI, bid/ask)
MarketState module to store latest tick data
SignalEngine implemented:
Uses price change + OI change
Generates basic signals (BUY CALL / BUY PUT / SIDEWAYS / WAIT)

Tech stack:

Python (FastAPI planned)
SmartAPI (Angel One)
Node.js (existing backend)
Static frontend (HTML already built)

tradezen/
 ├── public/
 │    ├── index.html
 │    ├── login.html
 │    ├── contact.html
 │    ├── fno_sinal.html
 │    └── ...
 ├── server.js
 ├── package.json
 └── render.yaml
 ├── routes
 │    ├── stockRoutes.js
 ├── services
 │    ├── stockServices.js
ai_engine/
├── config/
├── data/
│ ├── instrument_master.py
│ ├── websocket_client.py
│ └── tick_buffer.py
├── core/
│ ├── market_state.py
│ ├── signal_engine.py
├── execution/
├── storage/
└── utils/
What I want to do next:
Improve the signal_engine. Currently, it gives false calls and always give buy call(false one). Important files to look on (fno_signal, ai_engine folder). Confirm me before editing the files
