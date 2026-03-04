from collections import deque
from datetime import datetime, timezone
from typing import Deque, Optional, Tuple


class WeightBuffer:
    def __init__(self, max_size: int = 64):
        self._buffer: Deque[Tuple[datetime, float]] = deque(maxlen=max_size)

    def add_reading(self, weight: float, timestamp: Optional[datetime] = None):
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        self._buffer.append((timestamp, weight))

    def get_flow_rate(self) -> Optional[float]:
        if len(self._buffer) < 2:
            return None

        (t1, w1), (t2, w2) = self._buffer[0], self._buffer[-1]
        dt = (t2 - t1).total_seconds()
        if dt == 0:
            return None

        return (w2 - w1) / dt

    def get_current_weight(self) -> Optional[float]:
        return self._buffer[-1][1] if self._buffer else None

    def is_ready(self, min_readings: int = 2) -> bool:
        return len(self._buffer) >= min_readings

    def is_stale(self, max_age_seconds: float = 2.0) -> bool:
        if not self._buffer:
            return True

        age = (datetime.now(timezone.utc) - self._buffer[-1][0]).total_seconds()
        return age > max_age_seconds

    def clear(self):
        self._buffer.clear()

    @property
    def size(self) -> int:
        return len(self._buffer)

    @property
    def max_size(self) -> int:
        return self._buffer.maxlen

    def get_readings(self) -> list:
        return list(self._buffer)
