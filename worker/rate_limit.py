"""Small process-local fixed-window limiter for costly worker routes."""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict


class RequestRateLimiter:
    def __init__(self, max_keys: int = 10_000):
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._max_keys = max_keys
        self._lock = threading.Lock()

    def retry_after(self, key: str, limit: int, window_seconds: int) -> int:
        now = time.monotonic()
        with self._lock:
            start, count = self._windows.pop(key, (now, 0))
            if now - start >= window_seconds:
                start, count = now, 0
            if count >= limit:
                self._windows[key] = (start, count)
                return max(1, math.ceil(window_seconds - (now - start)))
            self._windows[key] = (start, count + 1)
            if len(self._windows) > self._max_keys:
                self._windows.popitem(last=False)
        return 0
