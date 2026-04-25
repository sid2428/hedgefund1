"""Token-bucket async rate limiter."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Simple async token-bucket limiter.

    `acquire()` blocks until the next token is available. Thread/coroutine-safe
    via an asyncio.Lock.
    """

    def __init__(self, calls_per_second: float, burst: int | None = None) -> None:
        if calls_per_second <= 0:
            raise ValueError("calls_per_second must be positive")
        self.rate = float(calls_per_second)
        self.burst = burst if burst is not None else max(1, int(calls_per_second))
        self._tokens = float(self.burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                missing = 1.0 - self._tokens
                wait = missing / self.rate
                await asyncio.sleep(wait)
