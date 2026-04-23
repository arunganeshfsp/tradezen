from data.tick_buffer import TickBuffer
from core.market_state import MarketState
from core.signal_engine  import SignalEngine

class Engine:
    def __init__(self):
        self.buffer = TickBuffer()
        self.state = MarketState()
        self.strategy = SignalEngine()
        self.last_signal = {"signal": "HOLD"}

    def on_tick(self, tick):
        self.buffer.push(tick)
        self.state.update(tick)

        signal = self.strategy.generate(self.state)

        if signal:
            self.last_signal = signal

    def get_latest_signal(self):
        return self.last_signal