"""
Time-based rolling window used by all indicators.
Bounded by wall-clock time rather than tick count — ensures the same
60-second window whether the market is fast (morning) or slow (afternoon).
"""

from collections import deque
import time

from .constants import WINDOW_SECONDS, MIN_WINDOW_POINTS


class TimeWindow:
    def __init__(self, seconds: int = WINDOW_SECONDS):
        self._data: deque = deque()
        self._seconds = seconds

    def push(self, v: float):
        self._data.append((time.time(), v))
        self._purge()

    def _purge(self):
        cutoff = time.time() - self._seconds
        while self._data and self._data[0][0] < cutoff:
            self._data.popleft()

    def values(self) -> list:
        self._purge()
        return [v for _, v in self._data]

    def __len__(self) -> int:
        return len(self.values())

    def full(self) -> bool:
        return len(self.values()) >= MIN_WINDOW_POINTS

    def avg(self) -> float:
        v = self.values()
        return sum(v) / len(v) if v else 0.0

    def std(self) -> float:
        v = self.values()
        if len(v) < 2:
            return 0.0
        mean = sum(v) / len(v)
        return (sum((x - mean) ** 2 for x in v) / len(v)) ** 0.5

    def ema(self, span: int = None) -> float:
        v = self.values()
        if not v:
            return 0.0
        alpha = 2.0 / (min(span or len(v), len(v)) + 1)
        result = v[0]
        for x in v[1:]:
            result = alpha * x + (1 - alpha) * result
        return result

    def first(self) -> float:
        v = self.values()
        return v[0] if v else 0.0

    def last(self) -> float:
        v = self.values()
        return v[-1] if v else 0.0
